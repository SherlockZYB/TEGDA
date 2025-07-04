import numpy as np
from medpy import metric

def dice_eval(predict,label,num_classes):
    #Computer Dice coefficient
    # print(predict.shape,label.shape,'6')
    dice = np.zeros(num_classes)
    eps = 1e-7
    for c in range(num_classes):
        inter = 2.0 * (np.sum((predict==c)*(label==c),dtype=np.float32))
        p_sum = np.sum(predict==c,dtype=np.float32)
        gt_sum = np.sum(label==c,dtype=np.float32)
        dice[c] = (inter+eps)/(p_sum+gt_sum+eps)
        
    return dice[1:]
    
def assd_eval(predict,label,num_classes):
    #Average Symmetric Surface Distance (ASSD)
    assd_all = np.zeros(num_classes)
    for c in range(num_classes):
        reference = (label==c) * 1
        result = (predict==c) * 1
        assd_all[c] = metric.binary.assd(result,reference)
    return assd_all[1:]
def hd95_eval(predict,label,num_classes):
    hd_all = np.zeros(num_classes)
    for c in range(num_classes):
        reference = (label==c) * 1
        result = (predict==c) * 1
        hd_all[c] = metric.binary.hd95(result,reference)
    return hd_all[1:]
    
def create_visual_anno(anno):
    assert np.max(anno) < 13 # only 7 classes are supported, add new color in label2color_dict
    label2color_dict = {
        0: [0, 0, 0],
        1: [0,0,255],  
        2: [0, 255, 0], 
        3: [0, 0, 255], 
        4: [255, 215, 0],  
        5: [160, 32, 100],  
        6: [255, 64, 64],  
        7: [139, 69, 19], 
        8: [140, 0, 199],
        9: [158, 3, 168],
        10:[84, 8, 46],
        11:[143, 188, 143],
        12:[140,210,180] 
    }
    # visualize
    visual_anno = np.zeros((anno.shape[0], anno.shape[1], 3), dtype=np.uint8)
    for i in range(visual_anno.shape[0]):  # i for h
        for j in range(visual_anno.shape[1]):
            color = label2color_dict[anno[i, j]]
            visual_anno[i, j, 0] = color[0]
            visual_anno[i, j, 1] = color[1]
            visual_anno[i, j, 2] = color[2]

    return visual_anno