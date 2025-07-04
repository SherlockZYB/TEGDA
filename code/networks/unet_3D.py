import torch
from torch import nn
from torch.nn import init
import torch.nn.functional as F

def weights_init_normal(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find('Linear') != -1:
        init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find('Norm') != -1:
        init.normal_(m.weight.data, 1.0, 0.02)
        init.constant_(m.bias.data, 0.0)

def weights_init_xavier(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        init.xavier_normal_(m.weight.data, gain=1)
    elif classname.find('Linear') != -1:
        init.xavier_normal_(m.weight.data, gain=1)
    elif classname.find('Norm') != -1:
        init.normal_(m.weight.data, 1.0, 0.02)
        init.constant_(m.bias.data, 0.0)

def weights_init_kaiming(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        init.kaiming_normal_(m.weight.data, a=0, mode='fan_in')
    elif classname.find('Linear') != -1:
        init.kaiming_normal_(m.weight.data, a=0, mode='fan_in')
    elif classname.find('Norm') != -1:
        init.normal_(m.weight.data, 1.0, 0.02)
        init.constant_(m.bias.data, 0.0)

def weights_init_orthogonal(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        init.orthogonal_(m.weight.data, gain=1)
    elif classname.find('Linear') != -1:
        init.orthogonal_(m.weight.data, gain=1)
    elif classname.find('Norm') != -1:
        init.normal_(m.weight.data, 1.0, 0.02)
        init.constant_(m.bias.data, 0.0)

def init_weights(net, init_type='normal'):
    if init_type == 'normal':
        net.apply(weights_init_normal)
    elif init_type == 'xavier':
        net.apply(weights_init_xavier)
    elif init_type == 'kaiming':
        net.apply(weights_init_kaiming)
    elif init_type == 'orthogonal':
        net.apply(weights_init_orthogonal)
    else:
        raise NotImplementedError(f'initialization method [{init_type}] is not implemented')

class ResUnetConv3(nn.Module):
    """
    结果: conv3d + (BN) + ReLU + Conv3d + (BN) + ReLU
    """

    def __init__(self, in_size, out_size, dropout_p, is_batchnorm, kernel_size=(3, 3, 1), padding_size=(1, 1, 0),
                 init_stride=(1, 1, 1)):
        super(ResUnetConv3, self).__init__()

        self.in_size = in_size
        self.out_size = out_size

        if in_size != out_size:
            self.conv_trans = nn.Sequential(
                nn.Conv3d(in_size, out_size, kernel_size=1),
                nn.BatchNorm3d(out_size),
                nn.LeakyReLU(inplace=True),
            )

        if is_batchnorm:
            self.conv1 = nn.Sequential(
                nn.Conv3d(in_size, out_size, kernel_size, init_stride, padding_size),
                nn.BatchNorm3d(out_size),
                nn.LeakyReLU(inplace=True),
            )
            self.conv2 = nn.Sequential(
                nn.Conv3d(out_size, out_size, kernel_size, 1, padding_size),
                nn.BatchNorm3d(out_size),
            )
        else:
            self.conv1 = nn.Sequential(
                nn.Conv3d(in_size, out_size, kernel_size, init_stride, padding_size),
                nn.LeakyReLU(inplace=True),
            )
            self.conv2 = nn.Conv3d(out_size, out_size, kernel_size, 1, padding_size)

        self.dropout = nn.Dropout(dropout_p)
        self.activate = nn.LeakyReLU(inplace=True)

        # 初始化权重
        for m in self.children():
            init_weights(m, init_type='kaiming')

    def forward(self, inputs):
        outputs = self.conv1(inputs)
        outputs = self.dropout(outputs)
        outputs = self.conv2(outputs)

        if self.in_size != self.out_size:
            inputs_trans = self.conv_trans(inputs)
        else:
            inputs_trans = inputs

        outputs = self.activate(inputs_trans + outputs)

        return outputs

class Encoder_dropout(nn.Module):
    def __init__(self, params):
        super(Encoder_dropout, self).__init__()
        self.params = params
        self.in_channels = self.params['in_chns']
        self.is_batchnorm = self.params['is_batchnorm']
        self.dropout = self.params['dropout']

        filters = self.params['filters']

        self.conv1 = ResUnetConv3(
            self.in_channels, filters[0], self.dropout[0], self.is_batchnorm,
            kernel_size=(1, 3, 3), padding_size=[(i - 1) // 2 for i in (1, 3, 3)]
        )
        self.pool1 = nn.Sequential(
            nn.Conv3d(filters[0], filters[1], kernel_size=(1, 2, 2), stride=(1, 2, 2)),
            nn.BatchNorm3d(filters[1]),
            nn.LeakyReLU(inplace=True)
        )

        self.conv2 = ResUnetConv3(
            filters[1], filters[1], self.dropout[1], self.is_batchnorm,
            kernel_size=(3, 3, 3), padding_size=[(i - 1) // 2 for i in (3, 3, 3)]
        )
        self.pool2 = nn.Sequential(
            nn.Conv3d(filters[1], filters[2], kernel_size=(2, 2, 2), stride=(2, 2, 2)),
            nn.BatchNorm3d(filters[2]),
            nn.LeakyReLU(inplace=True)
        )

        self.conv3 = ResUnetConv3(
            filters[2], filters[2], self.dropout[2], self.is_batchnorm,
            kernel_size=(3, 3, 3), padding_size=[(i - 1) // 2 for i in (3, 3, 3)]
        )
        self.pool3 = nn.Sequential(
            nn.Conv3d(filters[2], filters[3], kernel_size=(2, 2, 2), stride=(2, 2, 2)),
            nn.BatchNorm3d(filters[3]),
            nn.LeakyReLU(inplace=True)
        )

        self.conv4 = ResUnetConv3(
            filters[3], filters[3], self.dropout[3], self.is_batchnorm,
            kernel_size=(3, 3, 3), padding_size=[(i - 1) // 2 for i in (3, 3, 3)]
        )
        self.pool4 = nn.Sequential(
            nn.Conv3d(filters[3], filters[4], kernel_size=(2, 2, 2), stride=(2, 2, 2)),
            nn.BatchNorm3d(filters[4]),
            nn.LeakyReLU(inplace=True)
        )

        self.conv5 = ResUnetConv3(
            filters[4], filters[4], self.dropout[4], self.is_batchnorm,
            kernel_size=(3, 3, 3), padding_size=[(i - 1) // 2 for i in (3, 3, 3)]
        )
        self.pool5 = nn.Sequential(
            nn.Conv3d(filters[4], filters[5], kernel_size=(2, 2, 2), stride=(2, 2, 2)),
            nn.BatchNorm3d(filters[5]),
            nn.LeakyReLU(inplace=True)
        )

        self.center = ResUnetConv3(
            filters[5], filters[5], 0, self.is_batchnorm,
            kernel_size=(3, 3, 3), padding_size=[(i - 1) // 2 for i in (3, 3, 3)]
        )

        # 初始化权重
        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                init_weights(m, init_type='kaiming')
            elif isinstance(m, nn.BatchNorm3d):
                init_weights(m, init_type='kaiming')

    def forward(self, inputs):
        conv1 = self.conv1(inputs)
        pool1 = self.pool1(conv1)

        conv2 = self.conv2(pool1)
        pool2 = self.pool2(conv2)

        conv3 = self.conv3(pool2)
        pool3 = self.pool3(conv3)

        conv4 = self.conv4(pool3)
        pool4 = self.pool4(conv4)

        conv5 = self.conv5(pool4)
        pool5 = self.pool5(conv5)

        center = self.center(pool5)

        return [conv1, conv2, conv3, conv4, conv5, center]

class UnetConv3(nn.Module):
    """
    结果: conv3d + (BN) + ReLU + Conv3d + (BN)
    """

    def __init__(self, in_size, out_size, dropout_p, is_batchnorm, kernel_size=(3, 3, 1), padding_size=(1, 1, 0),
                 init_stride=(1, 1, 1)):
        super(UnetConv3, self).__init__()

        if is_batchnorm:
            self.conv1 = nn.Sequential(
                nn.Conv3d(in_size, out_size, kernel_size, init_stride, padding_size),
                nn.BatchNorm3d(out_size),
                nn.LeakyReLU(inplace=True),
            )
            self.conv2 = nn.Sequential(
                nn.Conv3d(out_size, out_size, kernel_size, 1, padding_size),
                nn.BatchNorm3d(out_size),
            )
        else:
            self.conv1 = nn.Sequential(
                nn.Conv3d(in_size, out_size, kernel_size, init_stride, padding_size),
                nn.LeakyReLU(inplace=True),
            )
            self.conv2 = nn.Sequential(
                nn.Conv3d(out_size, out_size, kernel_size, 1, padding_size)
            )

        self.dropout = nn.Dropout(dropout_p)

        # 初始化权重
        for m in self.children():
            init_weights(m, init_type='kaiming')

    def forward(self, inputs):
        outputs = self.conv1(inputs)
        outputs = self.dropout(outputs)
        outputs = self.conv2(outputs)
        return outputs

class UnetUp3_CT_HM(nn.Module):
    """
    上采样 + 拼接 + 卷积（含 Dropout）
    """

    def __init__(self, in_size, out_size, kernel_size, dropout_p=0.5, up_factor=(2, 2, 2), is_batchnorm=True):
        super(UnetUp3_CT_HM, self).__init__()

        self.up = nn.Sequential(
            nn.ConvTranspose3d(in_size, out_size, kernel_size=up_factor, stride=up_factor),
            nn.BatchNorm3d(out_size),
            nn.LeakyReLU(inplace=True)
        )

        self.conv = UnetConv3(
            out_size * 2, out_size, dropout_p, is_batchnorm,
            kernel_size=kernel_size, padding_size=[(i - 1) // 2 for i in kernel_size]
        )
        self.activate = nn.LeakyReLU(inplace=True)

        # 初始化权重
        for m in self.children():
            if m.__class__.__name__.find('UnetConv3') != -1:
                continue
            init_weights(m, init_type='kaiming')

    def forward(self, input1, input2):
        # input1 是来自编码器的特征，input2 是来自上一层的特征
        output2 = self.up(input2)

        # 对齐尺寸（如果需要的话，可以在这里添加尺寸匹配的代码）
        # output2 = self._match_size(input1, output2)

        x = torch.cat([input1, output2], 1)
        outputs = self.conv(x)
        outputs = self.activate(outputs + output2)
        return outputs

    # 可选：如果上采样后的尺寸与跳跃连接的特征尺寸不匹配，可以实现一个尺寸匹配函数
    # def _match_size(self, input1, input2):
    #     # 实现尺寸匹配的逻辑，例如通过裁剪或填充
    #     return input2

class Decoder_dropout(nn.Module):
    def __init__(self, params):
        super(Decoder_dropout, self).__init__()
        self.params = params
        self.is_batchnorm = self.params['is_batchnorm']
        self.dropout_p = self.params['dropout']

        filters = self.params['filters']

        self.up_concat5 = UnetUp3_CT_HM(
            filters[5], filters[4], kernel_size=(3, 3, 3), up_factor=(2, 2, 2),
            dropout_p=self.dropout_p[0], is_batchnorm=self.is_batchnorm
        )
        self.up_concat4 = UnetUp3_CT_HM(
            filters[4], filters[3], kernel_size=(3, 3, 3), up_factor=(2, 2, 2),
            dropout_p=self.dropout_p[1], is_batchnorm=self.is_batchnorm
        )
        self.up_concat3 = UnetUp3_CT_HM(
            filters[3], filters[2], kernel_size=(3, 3, 3), up_factor=(2, 2, 2),
            dropout_p=self.dropout_p[2], is_batchnorm=self.is_batchnorm
        )
        self.up_concat2 = UnetUp3_CT_HM(
            filters[2], filters[1], kernel_size=(3, 3, 3), up_factor=(2, 2, 2),
            dropout_p=self.dropout_p[3], is_batchnorm=self.is_batchnorm
        )
        self.up_concat1 = UnetUp3_CT_HM(
            filters[1], filters[0], kernel_size=(1, 3, 3), up_factor=(1, 2, 2),
            dropout_p=self.dropout_p[4], is_batchnorm=self.is_batchnorm
        )

        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                init_weights(m, init_type='kaiming')
            elif isinstance(m, nn.BatchNorm3d):
                init_weights(m, init_type='kaiming')

    def forward(self, feature):
        conv1 = feature[0]
        conv2 = feature[1]
        conv3 = feature[2]
        conv4 = feature[3]
        conv5 = feature[4]
        center = feature[5]

        up5 = self.up_concat5(conv5, center)
        up4 = self.up_concat4(conv4, up5)
        up3 = self.up_concat3(conv3, up4)
        up2 = self.up_concat2(conv2, up3)
        up1 = self.up_concat1(conv1, up2)
        return up1

class unet_3D(nn.Module):
    def __init__(self, in_channels=1, n_classes=2, is_batchnorm=True):
        super(unet_3D, self).__init__()
        print("Using UNet_3D with BatchNorm3d")

        params_encoder = {
            'in_chns': in_channels,
            'dropout': [0.05, 0.1, 0.2, 0.3, 0.5],
            'is_batchnorm': is_batchnorm,
            'filters': [16, 32, 64, 128, 256, 512]
        }

        params_decoder_main = {
            'dropout': [0, 0, 0, 0, 0],
            'is_batchnorm': is_batchnorm,
            'filters': [16, 32, 64, 128, 256, 512]
        }

        self.encoder = Encoder_dropout(params_encoder)
        self.main_decoder_1 = Decoder_dropout(params_decoder_main)

        self.n_class = n_classes
        self.main_final_1 = nn.Conv3d(16, self.n_class, 1)

    def forward(self, x):
        feature_0 = self.encoder(x)
        main_outfeature_1 = self.main_decoder_1(feature_0)
        main_seg_1 = self.main_final_1(main_outfeature_1)

        return main_seg_1
    
    def get_feature(self, x):
        feature = self.encoder(x)
        return feature
    
    def get_output(self, encoder_feature):
        decoder_feature = self.main_decoder_1(encoder_feature)
        seg = self.main_final_1(decoder_feature)
        return seg
    
    @torch.enable_grad()
    def forward_no_adapt(self, x):
        feature_0 = self.encoder(x)
        main_outfeature_1 = self.main_decoder_1(feature_0)
        main_seg_1 = self.main_final_1(main_outfeature_1)

        return main_seg_1

