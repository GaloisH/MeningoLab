"""生成用于试用 MLab 的合成数据（非真实病例）。

用法：python scripts/make_demo_data.py demo_data
"""
from __future__ import annotations

import sys
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image
from scipy import ndimage


def phantom(shape=(160, 192, 48), seed=0, lesion_side=1.0):
    rng = np.random.default_rng(seed)
    x, y, z = np.meshgrid(*[np.linspace(-1, 1, n) for n in shape], indexing="ij")
    head = (x / 0.85) ** 2 + (y / 0.95) ** 2 + (z / 1.15) ** 2
    brain = (x / 0.75) ** 2 + (y / 0.86) ** 2 + (z / 1.02) ** 2 < 1
    skull = (head < 1) & ~((x / 0.79) ** 2 + (y / 0.9) ** 2 + (z / 1.07) ** 2 < 1)
    vent = ((np.abs(x) - 0.15) / 0.1) ** 2 + (y / 0.35) ** 2 + (z / 0.4) ** 2 < 1
    shell = brain & ~ndimage.binary_erosion(brain, iterations=2)
    meninges = shell & (x * lesion_side > 0.05) & (y > -0.4)  # 一侧脑膜强化
    abscess = ((x + 0.4 * lesion_side) / 0.12) ** 2 + ((y - 0.25) / 0.12) ** 2 + (z / 0.3) ** 2 < 1
    edema = (((x + 0.4 * lesion_side) / 0.25) ** 2 + ((y - 0.25) / 0.25) ** 2 + (z / 0.5) ** 2 < 1) & ~abscess
    smooth = ndimage.gaussian_filter(rng.normal(0, 1, shape), 3) * 25

    t1c = np.where(head < 1, 120.0, 0.0)
    t1c[skull] = 60
    t1c[brain] = 300 + smooth[brain]
    t1c[vent] = 80
    t1c[edema] = 240
    t1c[abscess] = 90
    abscess_rim = abscess & ~ndimage.binary_erosion(abscess, iterations=2)
    t1c[abscess_rim] = 720
    t1c[meninges] = 760
    flair = np.where(head < 1, 90.0, 0.0)
    flair[brain] = 260 + smooth[brain]
    flair[vent] = 40
    flair[edema | abscess] = 520
    flair[meninges] = 430
    noise = lambda a: (a + rng.normal(0, 12, shape)).clip(0)  # noqa: E731
    gt = np.zeros(shape, np.uint8)
    gt[meninges] = 1
    gt[edema] = 2
    gt[abscess] = 3
    gt[vent] = 4
    return noise(t1c).astype(np.float32), noise(flair).astype(np.float32), gt


def main(out: str = "demo_data") -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # 体素间距 0.9 x 0.9 x 3 mm，使用 LPS 方向（类似 DICOM 转换结果），用于检验方向处理
    affine = np.diag([-0.9, -0.9, 3.0, 1.0])
    for i, side in enumerate((1.0, -1.0, 1.0), start=1):
        t1c, flair, _ = phantom(seed=i, lesion_side=side)
        case_dir = out / f"case_{i:03d}"
        case_dir.mkdir(exist_ok=True)
        nib.save(nib.Nifti1Image(t1c, affine), case_dir / "T1C.nii.gz")
        nib.save(nib.Nifti1Image(flair, affine), case_dir / "FLAIR.nii.gz")
    # nnU-Net 命名的病例
    t1c, flair, _ = phantom(seed=7, lesion_side=-1.0)
    nib.save(nib.Nifti1Image(t1c, affine), out / "case_004_0000.nii.gz")
    nib.save(nib.Nifti1Image(flair, affine), out / "case_004_0001.nii.gz")
    # 二维图片病例
    sl = t1c[:, :, 24]
    img = np.clip(sl / 800 * 255, 0, 255).astype(np.uint8).T[::-1]
    Image.fromarray(img).save(out / "slice_005.png")
    print(f"已生成演示数据：{out.resolve()}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
