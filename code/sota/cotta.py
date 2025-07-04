from copy import deepcopy

import torch
import torch.nn as nn
import torch.jit

import PIL
import torchvision.transforms as transforms
import my_transforms as my_transforms
from time import time
import logging
import torchio as tio


def get_tta_transforms(gaussian_std: float=0.005, soft=False):
    clip_min, clip_max = 0.0, 1.0
    p_hflip = 0.5
    tta_transforms = []
    tta_transforms.append(tio.RescaleIntensity(out_min_max=(clip_min, clip_max)))
    tta_transforms.append(tio.RandomGamma(log_gamma=(-0.3, 0.3)))
    tta_transforms.append(tio.RandomAffine(
        scales=(0.95, 1.05) if soft else (0.9, 1.1),
        degrees=(-8, 8) if soft else (-15, 15),
        translation=(0.0625, 0.0625, 0.0625),  # Convert to 3D translations
        isotropic=False
    ))
    tta_transforms.append(tio.RandomFlip(axes=(1), flip_probability=p_hflip))
    if soft:
        tta_transforms.append(tio.RandomBlur(std=(0.001, 0.25)))
    else:
        tta_transforms.append(tio.RandomBlur(std=(0.001, 0.5)))
    tta_transforms.append(tio.RandomNoise(mean=0, std=gaussian_std))
    # 根据CoTTA的源代码，好像在最后又进行了一次归一
    tta_transforms.append(tio.RescaleIntensity(out_min_max=(clip_min, clip_max)))
    transform = tio.Compose(tta_transforms)
    
    return transform


def update_ema_variables(ema_model, model, alpha_teacher):
    for ema_param, param in zip(ema_model.parameters(), model.parameters()):
        ema_param.data[:] = alpha_teacher * ema_param[:].data[:] + (1 - alpha_teacher) * param[:].data[:]
    return ema_model


class CoTTA(nn.Module):
    """CoTTA adapts a model by entropy minimization during testing.

    Once tented, a model adapts itself by updating on every forward.
    """
    def __init__(self, model, optimizer, steps=1, episodic=False, mt_alpha=0.99, rst_m=0.1, ap=0.9):
        super().__init__()
        self.model = model
        self.optimizer = optimizer
        self.steps = steps
        assert steps > 0, "cotta requires >= 1 step(s) to forward and update"
        self.episodic = episodic
        
        self.model_state, self.optimizer_state, self.model_ema, self.model_anchor = \
            copy_model_and_optimizer(self.model, self.optimizer)
        self.transform = get_tta_transforms()    
        self.mt = mt_alpha
        self.rst = rst_m
        self.ap = ap

    def forward_no_adapt(self, x):
        outputs = self.model(x)

        return outputs
    
    def forward(self, x):
        if self.episodic:
            self.reset()

        for _ in range(self.steps):
            outputs = self.forward_and_adapt(x, self.model, self.optimizer)

        return outputs

    def reset(self):
        if self.model_state is None or self.optimizer_state is None:
            raise Exception("cannot reset without saved model/optimizer state")
        load_model_and_optimizer(self.model, self.optimizer,
                                 self.model_state, self.optimizer_state)
        # Use this line to also restore the teacher model                         
        self.model_state, self.optimizer_state, self.model_ema, self.model_anchor = \
            copy_model_and_optimizer(self.model, self.optimizer)


    @torch.enable_grad()  # ensure grads in possible no grad context for testing
    def forward_and_adapt(self, x, model, optimizer):
        outputs = self.model(x)
        # Teacher Prediction
        anchor_prob = torch.nn.functional.softmax(self.model_anchor(x), dim=1).max(1)[0]
        standard_ema = self.model_ema(x)
        # Augmentation-averaged Prediction
        N = 32 
        outputs_emas = []
        for i in range(N):
            x_trans = self.transform(x[0].cpu()).cuda()
            x_trans = torch.unsqueeze(x_trans, 0)
            outputs_  = self.model_ema(x_trans).detach()
            outputs_emas.append(outputs_)
            # print(outputs_.shape,x.shape,self.transform(x).shape,'106')
        # Threshold choice discussed in supplementary
        if anchor_prob.mean()<self.ap:
            outputs_ema = torch.stack(outputs_emas).mean(0)
        else:
            outputs_ema = standard_ema
        # Student update
        loss = (softmax_entropy(outputs, outputs_ema)).mean(0) 
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        # Teacher update
        self.model_ema = update_ema_variables(ema_model = self.model_ema, model = self.model, alpha_teacher=self.mt)
        # Stochastic restore
        if True:
            for nm, m  in self.model.named_modules():
                for npp, p in m.named_parameters():
                    if npp in ['weight', 'bias'] and p.requires_grad:
                        mask = (torch.rand(p.shape)<self.rst).float().cuda() 
                        with torch.no_grad():
                            p.data = self.model_state[f"{nm}.{npp}"] * mask + p * (1.-mask)
        return outputs_ema
    
    @torch.no_grad()  # ensure grads in possible no grad context for testing
    def infer(self, x):
        # outputs = self.model(x)
        # Teacher Prediction
        # anchor_prob = torch.nn.functional.softmax(self.model_anchor(x), dim=1).max(1)[0]
        anchor_prob = torch.nn.functional.softmax(self.model_anchor(x), dim=1).max()
       
        standard_ema = self.model_ema(x)
        
        outputs_ema = standard_ema
        
        return outputs_ema


@torch.jit.script
def softmax_entropy(x, x_ema):# -> torch.Tensor:
    """Entropy of softmax distribution from logits."""
    b, c, d, h, w =  x.shape
    # print(x.shape,x_ema.shape,'145')
    entropy1 = -(x_ema.softmax(1) * x.log_softmax(1)).sum() / \
        (b * d * h * w * torch.log2(torch.tensor(c, dtype=torch.float)))
    print(entropy1)
    return entropy1

def collect_params(model):
    """Collect all trainable parameters.

    Walk the model's modules and collect all parameters.
    Return the parameters and their names.

    Note: other choices of parameterization are possible!
    """
    params = []
    names = []
    print(model.named_modules)
    for nm, m in model.named_modules():
        print(nm, m)
        if True:
            for np, p in m.named_parameters():
                if np in ['weight', 'bias'] and p.requires_grad:
                    params.append(p)
                    names.append(f"{nm}.{np}")
                    # print(nm, np)
    return params, names


def copy_model_and_optimizer(model, optimizer):
    """Copy the model and optimizer states for resetting after adaptation."""
    model_state = deepcopy(model.state_dict())
    model_anchor = deepcopy(model)
    optimizer_state = deepcopy(optimizer.state_dict())
    ema_model = deepcopy(model)
    for param in ema_model.parameters():
        param.detach_()
    return model_state, optimizer_state, ema_model, model_anchor


def load_model_and_optimizer(model, optimizer, model_state, optimizer_state):
    """Restore the model and optimizer states from copies."""
    model.load_state_dict(model_state, strict=True)
    optimizer.load_state_dict(optimizer_state)


def configure_model(model):
    """Configure model for use with tent."""
    # train mode, because tent optimizes the model to minimize entropy
    model.train()
    # disable grad, to (re-)enable only what we update
    model.requires_grad_(False)
    # enable all trainable
    for m in model.modules():
        if isinstance(m, nn.BatchNorm3d):
            m.requires_grad_(True)
            # force use of batch stats in train and eval modes
            m.track_running_stats = False
            m.running_mean = None
            m.running_var = None
        else:
            m.requires_grad_(True)
    return model


def check_model(model):
    """Check model for compatability with tent."""
    is_training = model.training
    assert is_training, "tent needs train mode: call model.train()"
    param_grads = [p.requires_grad for p in model.parameters()]
    has_any_params = any(param_grads)
    has_all_params = all(param_grads)
    assert has_any_params, "tent needs params to update: " \
                           "check which require grad"
    assert not has_all_params, "tent should not update all params: " \
                               "check which require grad"
    has_bn = any([isinstance(m, nn.BatchNorm2d) for m in model.modules()])
    assert has_bn, "tent needs normalization for its optimization"
