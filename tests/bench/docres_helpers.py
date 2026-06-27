"""Small helpers ported verbatim from the DocRes repo (appearance task only).
No MBD / skimage needed for the appearance pipeline."""
import cv2
import numpy as np
from collections import OrderedDict


def convert_state_dict(state_dict):
    """Strip a leading 'module.' (DataParallel) from keys if present."""
    new = OrderedDict()
    for k, v in state_dict.items():
        new[k[7:] if k.startswith("module.") else k] = v
    return new


def stride_integral(img, stride=8):
    """Top/left replicate-pad so H,W become multiples of `stride`. Returns img,padH,padW."""
    h, w = img.shape[:2]
    padding_h = (stride - h % stride) % stride
    padding_w = (stride - w % stride) % stride
    if padding_h:
        img = cv2.copyMakeBorder(img, padding_h, 0, 0, 0, borderType=cv2.BORDER_REPLICATE)
    if padding_w:
        img = cv2.copyMakeBorder(img, 0, 0, padding_w, 0, borderType=cv2.BORDER_REPLICATE)
    return img, padding_h, padding_w


def appearance_prompt(img):
    """DTS prompt for the 'appearance' task (verbatim from DocRes inference.py).
    img: BGR uint8 -> 3-channel background-normalized prompt at the same size."""
    h, w = img.shape[:2]
    img = cv2.resize(img, (1024, 1024))
    planes = cv2.split(img)
    norm_planes = []
    for plane in planes:
        dilated = cv2.dilate(plane, np.ones((7, 7), np.uint8))
        bg = cv2.medianBlur(dilated, 21)
        diff = 255 - cv2.absdiff(plane, bg)
        norm = cv2.normalize(diff, None, alpha=0, beta=255,
                             norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
        norm_planes.append(norm)
    result_norm = cv2.merge(norm_planes)
    return cv2.resize(result_norm, (w, h))
