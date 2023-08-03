# -*- coding: UTF-8 -*-
# !/usr/bin/env python3
################################################################################
#
# Copyright (c) 2022 Chinatelecom.cn, Inc. All Rights Reserved
#
################################################################################
"""
本文件实现数据增加方法, 支持对 img, mask, bbox, landmark(lamk)同步处理.

Authors: zouzhaofan(zouzhf41@chinatelecom.cn)
Date:    2021/12/20 22:30:33
"""

import cv2
import random
import warnings
import numpy as np
# import albumentations as A
from typing import Iterable, List, Optional, Sequence, Tuple, Union


class Normalize(object):
    """Normalize image.

    Args:
        mean (tuple, np.ndarray): Normalized mean.
        std (tuple, np.ndarray): Normalized variance.
        to_rgb (bool): Whether to transform to RGB.
    """

    def __init__(self,
                 mean=(0, 0, 0),
                 std=(1, 1, 1),
                 to_rgb=False):
        self.mean = np.array(mean, dtype=np.float32)
        self.std = np.array(std, dtype=np.float32)
        self.to_rgb = to_rgb

    def __call__(self, data):
        img = data['img'].astype(np.float32)
        if self.to_rgb:
            cv2.cvtColor(img, cv2.COLOR_BGR2RGB, img)
        cv2.subtract(img, np.float64(self.mean.reshape(1, -1)), img)
        cv2.multiply(img, 1 / np.float64(self.std.reshape(1, -1)), img)

        for k in data.keys():
            if 'mask' in k:
                data[k] = data[k].transpose(2, 0, 1).astype(np.float32) / 255.0

        data['img'] = img.transpose(2, 0, 1)
        return data


class Resize(object):
    """Resize images & bbox & depth & landmarks & reflection.

    Args:
        scale (tuple): Images scales(w, h) for resizing.
        keep_ratio (bool): Whether to keep the aspect ratio when
            resizing the image.
        interpolation (string): Type of interpolation
    """

    def __init__(self,
                 scale,
                 keep_ratio=False,
                 interpolation='linear'):
        self.scale = scale
        self.keep_ratio = keep_ratio
        self.interpolation = interpolation

    def __call__(self, data):
        if self.keep_ratio:
            raise NotImplementedError
        h, w = data['img'].shape[:2]
        w_scale = self.scale[0] / w
        h_scale = self.scale[1] / h
        if self.interpolation == 'linear':
            data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_LINEAR)
        elif self.interpolation == 'nearest':
            data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_NEAREST)
        elif self.interpolation == 'cubic':
            data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_CUBIC)
        for k in data.keys():
            if 'mask' in k:
                data[k] = cv2.resize(data[k], self.scale, interpolation=cv2.INTER_LINEAR)
            elif k in ['bbox', 'lamk']:
                data[k][0::2] *= w_scale
                data[k][1::2] *= h_scale

        return data


class RandomResize(object):
    """Random Resize.

        Args:
            ratio (float): the probability of random resize.
            scale (tuple): Images scales(w, h) for resizing.
        """

    def __init__(self,
                 ratio=0.5,
                 scale=(32, 32)):
        self.ratio = ratio
        self.scale = scale

    def __call__(self, data):
        if np.random.uniform(0, 1) < self.ratio:
            t = np.random.randint(3)
            if t == 0:
                data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_LINEAR)
            elif t == 1:
                data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_NEAREST)
            elif t == 2:
                data['img'] = cv2.resize(data['img'], self.scale, interpolation=cv2.INTER_CUBIC)
            else:
                print('ttt')
                print('interpolation error, t=', t)
        return data


class PhotoMetricDistortion(object):
    """Apply photometric distortion to image sequentially, every transformation
    is applied with a probability of 0.5. The position of random contrast is in
    second or second to last.

    Args:
        hue (int): delta of hue.
        graying (float): the probability of graying.
        contrast (tuple): the range of contrast.
        brightness (tuple): the range of brightness.
        saturation (tuple): the range of saturation.
        blur_sharpen (float): the probability of blur or sharpen.
        swap_channels (bool): whether randomly swap channels
    """

    def __init__(self,
                 hue=0,
                 graying=0.0,
                 gamma=None,
                 contrast=None,
                 brightness=None,
                 saturation=None,
                 motion_blur = 0.0,
                 blur_sharpen=0.0,
                 swap_channels=False):
        self.hue = hue
        self.gamma = gamma
        self.graying = graying
        self.contrast = contrast
        self.brightness = brightness
        self.saturation = saturation
        self.motion_blur = motion_blur
        self.blur_sharpen = blur_sharpen
        self.swap_channels = swap_channels

    # 运动模糊退化图像 (Motion blur degradation)
    def motionBlur(self, image, degree=10, angle=45):
        image = np.array(image)
        M = cv2.getRotationMatrix2D(((degree-1)/2, (degree-1)/2), angle, 1)  # 无损旋转
        kernel = np.diag(np.ones(degree) / degree)  # 运动模糊内核
        kernel = cv2.warpAffine(kernel, M, (degree, degree))

        blurred = cv2.filter2D(image, -1, kernel)  # 图像卷积
        blurredNorm = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX) # 归一化为 [0,255]
        return blurredNorm

    def __call__(self, data):
        img = data['img'].astype(np.float32)

        # random graying
        if np.random.uniform(0, 1) < self.graying and (data['label'] != 0).any():  # only apply to attack
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)[:, :, np.newaxis].repeat(3, 2)

        # random brightness
        if self.brightness is not None and np.random.randint(2):
            if len(self.brightness) == 2:
                img += np.random.uniform(self.brightness[0], self.brightness[1])
            else:
                img += np.random.uniform(self.brightness[0], self.brightness[1], 3)
        # random contrast
        if self.contrast is not None and np.random.randint(2):
            img *= np.random.uniform(self.contrast[0], self.contrast[0]) # 线性对比度应保证平均亮度不变，y = avg+(x-avg)*contrast, 且容易超出255
            
        if self.gamma is not None and np.random.randint(2):
            img = 255*((np.clip(img, 0, 255)/255)**np.random.uniform(self.gamma[0], self.gamma[1])) # 采样gamma对比度, y=255*((x/255)**gamma)
        
        # random blur or sharpen
        if np.random.uniform(0, 1) < self.motion_blur:
            img = self.motionBlur(img, 5, np.random.randint(0,360))

        if np.random.uniform(0, 1) < self.blur_sharpen:
            if np.random.randint(2):
                img = cv2.GaussianBlur(img, (3, 3), 0)
                # img = self.motionBlur(img, 5, np.random.randint(0,360))
            else:
                kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], np.float32)
                img = cv2.filter2D(img, -1, kernel=kernel)

        # if np.random.uniform(0, 1) < self.blur_sharpen:
        #     flag = np.random.randint(3)
        #     if flag==0:
        #         # img = cv2.GaussianBlur(img, (3, 3), 0)
        #         kernel = 2*np.random.randint(1, 5)+1
        #         img = cv2.GaussianBlur(img, (kernel, kernel), 25)
        #     elif flag==1:
        #         img = self.motionBlur(img, np.random.randint(3, 10), np.random.randint(0,360))
        #     else:
        #         kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], np.float32)
        #         img = cv2.filter2D(img, -1, kernel=kernel)

        # convert color from BGR to HSV
        if self.saturation is not None:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            # random saturation
            if np.random.randint(2):
                img[..., 1] *= np.random.uniform(self.saturation[0], self.saturation[1])

            # random hue
            if np.random.randint(2):
                img[..., 0] += np.random.uniform(-self.hue, self.hue)
                img[..., 0][img[..., 0] > 360] -= 360
                img[..., 0][img[..., 0] < 0] += 360

            # convert color from HSV to BGR
            img = cv2.cvtColor(img, cv2.COLOR_HSV2BGR)

        # randomly swap channels
        if np.random.uniform(0, 1) < self.swap_channels:
            img = img[..., np.random.permutation(3)]

        data['img'] = np.clip(img, 0, 255)
        return data


class GaussianBlur(object):
    """AGaussian Blur.

        Args:
            blur (float): the probability of blur.
            kernal_size (int): kernal size.
            sigma (float): Normalized variance.
        """

    def __init__(self,
                 blur=0.5,
                 kernal_size=3,
                 sigma=1.6):
        self.blur = blur
        self.kernal_size = kernal_size
        self.sigma = sigma

    def __call__(self, data):
        if np.random.uniform(0, 1) < self.blur:
            img = cv2.GaussianBlur(data['img'], (self.kernal_size, self.kernal_size), self.sigma)
            data['img'] = img
        return data


class RandomFlip(object):
    """Random Flip the images & bbox & depth & landmarks & reflection.

    Args:
        hflip_ratio (float, optional): The horizontal flipping probability.
        vflip_ratio (float, optional): The vertical flipping probability.
    """

    def __init__(self,
                 hflip_ratio=0,
                 vflip_ratio=0):
        self.hflip_ratio = hflip_ratio
        self.vflip_ratio = vflip_ratio

    def horizontal_flip(self, data):
        # horizontal filp img or mask
        h, w = data['img'].shape[:2]
        for k in data.keys():
            if 'img' in k or 'mask' in k:
                data[k] = np.flip(data[k], axis=1)
            elif k in ['bbox']:
                bbox = data['bbox'].copy()
                data['bbox'][0], data['bbox'][2] = w - bbox[2], w - bbox[0]
        if 'lamk' in data:
            # TODO: base on landmark order
            raise NotImplementedError

        return data

    def vertical_flip(self, data):
        # vertical filp img or mask
        h, w = data['img'].shape[:2]
        for k in data.keys():
            if 'img' in k or 'mask' in k:
                data[k] = np.flip(data[k], axis=0)
        if 'bbox' in data:
            bbox = data['bbox'].copy()
            data['bbox'][1], data['bbox'][3] = h - bbox[3], h - bbox[1]
        if 'lamk' in data:
            # TODO: base on landmark order
            raise NotImplementedError
        return data

    def __call__(self, data):
        if np.random.uniform(0, 1) < self.hflip_ratio:
            data = self.horizontal_flip(data)
        if np.random.uniform(0, 1) < self.vflip_ratio:
            data = self.vertical_flip(data)
        return data


class RandomRotate(object):
    """Rotate the images & bbox & depth & landmarks & reflection

    Args:
        rotate_ratio (float): rotate probability.
        max_angle (int): Maximum angle of rotation clockwise and
            counterclockwise.
    """

    def __init__(self,
                 max_angle=10,
                 rotate_ratio=0):
        self.max_angle = max_angle
        self.rotate_ratio = rotate_ratio

    def __call__(self, data):
        if np.random.uniform(0, 1) > self.rotate_ratio:
            return data
        h, w = data['img'].shape[:2]
        angle = np.random.randint(-self.max_angle, self.max_angle)
        M = cv2.getRotationMatrix2D((w/2, h/2), angle, 1)
        for k in data.keys():
            if 'img' in k or 'mask' in k:
                data[k] = cv2.warpAffine(data[k], M, (w, h))
            elif k in ['bbox']:
                bbox = data[k]
                bbox = np.array([bbox[0], bbox[1], bbox[2], bbox[1],
                                 bbox[2], bbox[3], bbox[0], bbox[3]])
                bbox_ = bbox.copy()
                bbox_[0::2] = bbox[0::2]*M[0, 0] + bbox[1::2]*M[0, 1] + M[0, 2]
                bbox_[1::2] = bbox[0::2]*M[1, 0] + bbox[1::2]*M[1, 1] + M[1, 2]
                bbox_ = np.array([bbox_[0::2].min(), bbox_[1::2].min(),
                                  bbox_[0::2].max(), bbox_[1::2].max()])
                bbox_[0::2] = np.clip(bbox_[0::2], 0, w)
                bbox_[1::2] = np.clip(bbox_[1::2], 0, h)
                data[k] = bbox_
            elif k in ['lamk']:
                points = data[k].copy()
                points[0::2] = data[k][0::2]*M[0, 0] + data[k][1::2]*M[0, 1] + M[0, 2]
                points[1::2] = data[k][0::2]*M[1, 0] + data[k][1::2]*M[1, 1] + M[1, 2]
                points[0::2] = np.clip(points[0::2], 0, w)
                points[1::2] = np.clip(points[1::2], 0, h)
                data[k] = points
        return data


class RandomCrop(object):
    """Random crop the images & bbox & depth & landmarks & reflection.

    Args:
        crop_ratio (float): random crop probability.
        crop_range (tuple): Crop edge range, e.g. (0.1, 0.2) means new region
            begin 0.1*w, 0.2*h, end 0.9*w, 0.8*h.
    """

    def __init__(self,
                 crop_ratio=0,
                 crop_range=(0.1, 0.1)):
        self.crop_ratio = crop_ratio
        self.crop_range = crop_range

    def __call__(self, data):
        if np.random.uniform(0, 1) > self.crop_ratio:
            return data
        h, w = data['img'].shape[:2]
        rx1 = np.random.randint(0, int(w * self.crop_range[0]))
        ry1 = np.random.randint(0, int(h * self.crop_range[1]))
        rx2 = np.random.randint(int((1-self.crop_range[0]) * w), w)
        ry2 = np.random.randint(int((1-self.crop_range[1]) * h), h)
        for k in data.keys():
            if 'img' in k or 'mask' in k:
                data[k] = data[k][ry1:ry2, rx1:rx2, :]
            elif k in ['bbox', 'lamk']:
                data[k][0::2] = np.clip(data[k][0::2] - rx1, 0, w)
                data[k][1::2] = np.clip(data[k][1::2] - ry1, 0, h)
        return data


class RandomFixSizeCrop(object):
    """Random Fixed size crop the images & depth & reflection.

    Args:
        scale (tuple): Images scales(w, h) for cropping.
        shift_ratio (tuple): shift ratio for each image side (w, h).
    """

    def __init__(self,
                 scale,
                 shift_ratio=(0, 0)):
        self.scale = scale
        self.shift_ratio = shift_ratio

    def __call__(self, data):
        h, w = data['img'].shape[:2]
        crop = self.scale[0] <= min(h, w)
        if crop:
            rx1 = int(w / 2 - self.scale[0] / 2)
            ry1 = int(h / 2 - self.scale[1] / 2)
            rx1 += int(np.random.uniform(-1, 1) * self.shift_ratio[0] * (w - self.scale[0]) / 2)
            ry1 += int(np.random.uniform(-1, 1) * self.shift_ratio[1] * (h - self.scale[1]) / 2)
            rx2 = rx1 + self.scale[0]
            ry2 = ry1 + self.scale[1]
        for k in data.keys():
            if 'img' in k or 'mask' in k:
                if crop:
                    data[k] = data[k][ry1:ry2, rx1:rx2]
                else:
                    data[k] = cv2.resize(data[k], self.scale, interpolation=cv2.INTER_LINEAR)
            elif k in ['bbox', 'lamk']:
                raise NotImplementedError
        return data


class RandomErase(object):
    """Random erase some region on image

    Args:
        erase_ratio (float): random erase probability.
        erase_shape (tuple): the shape of erase region, e.g. (0.05, 0.05) means
            shape of (0.05*w, 0.05*h).
        erase_fill (tuple): The value of pixel to fill in the erase regions.
            Default: (0, 0, 0)
    """

    def __init__(self,
                 erase_ratio=0,
                 erase_shape=(0.05, 0.05),
                 erase_fill=(0, 0, 0)):
        self.erase_ratio = erase_ratio
        self.erase_shape = erase_shape
        self.erase_fill = erase_fill

    def __call__(self, data):
        if np.random.uniform(0, 1) > self.erase_ratio:
            return data
        num_region = np.random.randint(1, 3)
        h, w = data['img'].shape[:2]
        for _ in range(num_region):
            ew = np.random.randint(0, int(self.erase_shape[0] * w))
            eh = np.random.randint(0, int(self.erase_shape[1] * h))

            x = np.random.randint(0, w - ew)
            y = np.random.randint(0, h - eh)

            data['img'][y:y+eh, x:x+ew, :] = self.erase_fill

        return data


class PatchShuffle(object):
    """Random repatch the images.

    Args:
        num_patch (int): number patch of each edge.
        shuffer_ratio (float): random crop probability.
    """
    def __init__(self,
                 num_patch=3,
                 shuffer_ratio=0.0):
        self.shuffer_ratio = shuffer_ratio
        self.num_patch = num_patch

    def __call__(self, data):
        if np.random.uniform(0, 1) > self.shuffer_ratio:
            return data
        # if np.random.randint(2):
        inds = np.arange(self.num_patch**2)
        np.random.shuffle(inds)
        # else:
        #     inds=np.random.randint(self.num_patch**2,size=self.num_patch**2)
        h, w = data['img'].shape[:2]
        ph, pw = h // self.num_patch, w // self.num_patch
        img = np.zeros_like(data['img'])
        for i, ind in enumerate(inds):
            ih = int(i / self.num_patch)
            iw = int(i % self.num_patch)
            jh = int(ind / self.num_patch)
            jw = int(ind % self.num_patch)
            img[ih * ph: (ih + 1) * ph, iw * pw: (iw + 1) * pw] = \
                data['img'][jh * ph: (jh + 1) * ph, jw * pw: (jw + 1) * pw].copy()
        data['img'] = img
        return data


class CoarseDropout(object):
    """Random erase image rectangle region

    Args:  
        max_holes (int): Maximum number of regions to zero out.
        max_height (int, float): Maximum height of the hole.
            If float, it is calculated as a fraction of the image height.
        max_width (int, float): Maximum width of the hole.
            If float, it is calculated as a fraction of the image width.
        min_holes (int): Minimum number of regions to zero out. If `None`,
            `min_holes` is be set to `max_holes`. Default: `None`.
        min_height (int, float): Minimum height of the hole. Default: None. If `None`,
            `min_height` is set to `max_height`. Default: `None`.
            If float, it is calculated as a fraction of the image height.
        min_width (int, float): Minimum width of the hole. If `None`, `min_height` is
            set to `max_width`. Default: `None`.
            If float, it is calculated as a fraction of the image width.
        fill_value (int, float, list of int, list of float): value for dropped pixels.  

    """
    def __init__(self,
                max_holes: int = 8,
                max_height: int = 8,
                max_width: int = 8,
                min_holes: Optional[int] = None,
                min_height: Optional[int] = None,
                min_width: Optional[int] = None,
                fill_value: int = 0,
                p: float = 0.5) -> None:

        self.max_holes = max_holes
        self.max_height = max_height
        self.max_width = max_width
        self.min_holes = min_holes if min_holes is not None else max_holes
        self.min_height = min_height if min_height is not None else max_height
        self.min_width = min_width if min_width is not None else max_width
        self.fill_value = fill_value
        self.p = p
        if not 0 < self.min_holes <= self.max_holes:
            raise ValueError("Invalid combination of min_holes and max_holes. Got: {}".format([min_holes, max_holes]))

        self.check_range(self.max_height)
        self.check_range(self.min_height)
        self.check_range(self.max_width)
        self.check_range(self.min_width)

        if not 0 < self.min_height <= self.max_height:
            raise ValueError(
                "Invalid combination of min_height and max_height. Got: {}".format([min_height, max_height])
            )
        if not 0 < self.min_width <= self.max_width:
            raise ValueError("Invalid combination of min_width and max_width. Got: {}".format([min_width, max_width]))

    def check_range(self, dimension):
        if isinstance(dimension, float) and not 0 <= dimension < 1.0:
            raise ValueError(
            "Invalid value {}. If using floats, the value should be in the range [0.0, 1.0)".format(dimension)
            )

    def get_holes(self,
                  img:np.ndarray,
                  ) -> Iterable[Tuple[int, int, int, int]]:
        height, width = img.shape[:2]
        holes = []
        for _n in range(random.randint(self.min_holes, self.max_holes)):
            if all(
                [
                    isinstance(self.min_height, int),
                    isinstance(self.min_width, int),
                    isinstance(self.max_height, int),
                    isinstance(self.max_width, int),
                ]
            ):
                hole_height = random.randint(self.min_height, self.max_height)
                hole_width = random.randint(self.min_width, self.max_width)
            elif all(
                [
                    isinstance(self.min_height, float),
                    isinstance(self.min_width, float),
                    isinstance(self.max_height, float),
                    isinstance(self.max_width, float),
                ]
            ):
                hole_height = int(height * random.uniform(self.min_height, self.max_height))
                hole_width = int(width * random.uniform(self.min_width, self.max_width))
            else:
                raise ValueError(
                    "Min width, max width, \
                    min height and max height \
                    should all either be ints or floats. \
                    Got: {} respectively".format(
                        [
                            type(self.min_width),
                            type(self.max_width),
                            type(self.min_height),
                            type(self.max_height),
                        ]
                    )
                )

            y1 = random.randint(0, height - hole_height)
            x1 = random.randint(0, width - hole_width)
            y2 = y1 + hole_height
            x2 = x1 + hole_width
            holes.append((x1, y1, x2, y2))
        return holes

    def __call__(self, data: dict = None,
                ) -> dict:
        if np.random.uniform(0, 1) > self.p:
            return data
        img = data['img'].copy()
        holes = self.get_holes(img)
        for x1, y1, x2, y2 in holes:
            img[y1:y2, x1:x2] = self.fill_value
        data['img'] = img
        return data


class AlbumAug(object):
    def __init__(self, album_conf, select_type):
        transform_list = []
        
        for k,v in album_conf.items():
            func = f"A.{k}(**album_conf['{k}'])"
            transform_list.append(eval(func))

        if select_type[0] == "SomeOf":
            transform_list = A.SomeOf(transform_list, **select_type[1])
        elif select_type[0] == "OneOf":
            transform_list = A.OneOf(transform_list, **select_type[1])
        elif select_type[0] == "Seq":
            transform_list = A.Sequential(transform_list, **select_type[1])
        else:
            raise NotImplemented
        self.aug = transform_list
        # self.aug = A.Compose(transform_list)

    def __call__(self, data):
        data['img'] = self.aug(image=data['img'])['image']
        return data


class AddNoise(object):
    """Add Noises.

    Args:
        ratio (float): ratio of samples adding noise.
        sigma (float): amplitude of gaussian noise.
        mean (float): Normalized mean.
        std (float): Normalized variance.
    """

    def __init__(self,
                 ratio=0.1,
                 sigma=0.3,
                 mean=0.0,
                 std=0.1):
        self.ratio = ratio
        self.sigma = sigma
        self.mean = mean
        self.std = std

    def __call__(self, data):
        if np.random.uniform(0, 1) < self.ratio:
            noise = np.random.normal(self.mean, self.std, data['img'].shape) * self.sigma
            img = np.clip(data['img'] + noise * 255, 0, 255)
            data['img'] = img
        return data


class Transforms(object):
    """Data preprocessing, including data augmentation and normalization.

    Args:
        pipeline (dict): Sequence of transform config dict to be executed.
        data (dict): input data to be preprocessed.
        Example:
            pipline = dict(
                RandomFlip=dict(hflip_ratio=0.5, vflip_ratio=0),
                RandomRotate=dict(max_angle=8, rotate_ratio=0.5),
                PatchShuffle=dict(num_patch=3, shuffer_ratio=0.3),
                RandomCrop=dict(crop_ratio=0.3, crop_range=(0.1, 0.1)),
                PhotoMetricDistortion=dict(
                    hue=10,
                    graying=0.2,
                    contrast=(0.8, 1.2),
                    brightness=(-16, 16),
                    saturation=(0.9, 1.1),
                    blur_sharpen=0.2,
                    swap_channels=False),
                Resize=dict(scale=(224, 224)),
                Normalize=dict(mean=[127.5, 127.5, 127.5], std=[255, 255, 255], to_rgb=False)
            )
            data = dict(
                img = np.ndarray (dtype=np.float32) shape of (h, w, 3),
                label = np.ndarray (dtype=np.int64) shape of (1, ),
                bbox = np.ndarray (dtype=np.float32) shape of (4,),
                lamk = np.ndarray (dtype=np.float32) shape of (2*k, ),
                *_mask = np.ndarray (dtype=np.float32) shape of (h, w, 3),
            )
    """

    def __init__(self, pipeline):
        self.transforms = []
        if pipeline is None:
            return
        if 'AlbumAug' in pipeline:
            self.transforms.append(AlbumAug(**pipeline['AlbumAug']))
        if 'Resize' in pipeline:
            self.transforms.append(Resize(**pipeline['Resize']))
        for k, args in pipeline.items():
            if k in ['RandomFlip', 'RandomRotate', 'RandomCrop',
                     'PatchShuffle', 'RandomErase', 'PhotoMetricDistortion', 'GaussianBlur', 'CoarseDropout']:
                self.transforms.append(eval(f'{k}')(**args))
            elif k in ['Resize', 'RandomResize', 'RandomFixSizeCrop', 'Normalize', 'AlbumAug', 'AddNoise']:
                continue
            else:
                warnings.warn(f'Augmentation {k} has not yet been implemented')
        # 'Resize and Normalize should be added last'
        if 'AddNoise' in pipeline:
            self.transforms.append((AddNoise(**pipeline['AddNoise'])))
        if 'RandomFixSizeCrop' in pipeline:
            self.transforms.append(RandomFixSizeCrop(**pipeline['RandomFixSizeCrop']))
        if 'RandomResize' in pipeline:
            self.transforms.append(RandomResize(**pipeline['RandomResize']))
        if 'Resize' in pipeline:
            self.transforms.append(Resize(**pipeline['Resize']))
        if 'Normalize' in pipeline:
            self.transforms.append(Normalize(**pipeline['Normalize']))

    def __call__(self, data):
        for transform in self.transforms:
            data = transform(data)
        return data
        
