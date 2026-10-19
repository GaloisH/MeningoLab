"""影像读写。

所有影像在内存中统一为 RAS+ 规范方向的三维数组 ``data[x, y, z]``：
+x 指向患者右侧，+y 指向前方，+z 指向头侧。二维图片视为 z 方向只有一层的体数据。
保存标签时再变换回原始文件的方向与仿射矩阵，保证与原图逐体素对齐（可直接用于 nnU-Net 训练）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel import orientations as ornt
from PIL import Image

NIFTI_SUFFIXES = (".nii.gz", ".nii")
IMAGE2D_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

_RAS = ornt.axcodes2ornt(("R", "A", "S"))


def file_kind(path: Path | str) -> str | None:
    """返回 ``"3d"``（NIfTI）、``"2d"``（普通图片）或 ``None``。"""
    name = Path(path).name.lower()
    if name.endswith(NIFTI_SUFFIXES):
        return "3d"
    if name.endswith(IMAGE2D_SUFFIXES):
        return "2d"
    return None


def strip_suffix(name: str) -> str:
    """去掉影像扩展名（兼容 ``.nii.gz`` 双扩展名）。"""
    lower = name.lower()
    for suf in NIFTI_SUFFIXES + IMAGE2D_SUFFIXES:
        if lower.endswith(suf):
            return name[: -len(suf)]
    return name


@dataclass
class Volume:
    """一个影像序列（或一张二维图片）。"""

    data: np.ndarray  # float32 (X, Y, Z)，RAS 方向
    spacing: tuple[float, float, float]
    path: Path
    name: str
    is_2d: bool = False
    rgb: np.ndarray | None = None  # uint8 (X, Y, Z, 3)，仅彩色二维图片
    affine: np.ndarray = field(default_factory=lambda: np.eye(4))  # 规范方向下的仿射矩阵
    orig_affine: np.ndarray | None = None
    orig_header: nib.Nifti1Header | None = None
    orig_ornt: np.ndarray | None = None
    _window: tuple[float, float] | None = None

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(self.data.shape[:3])  # type: ignore[return-value]

    def auto_window(self) -> tuple[float, float]:
        """按 0.5%~99.5% 分位数估计显示窗口。"""
        if self._window is None:
            d = self.data
            step = max(1, d.size // 2_000_000)
            sample = d.reshape(-1)[::step]
            nz = sample[sample != 0]
            if nz.size > 100:
                sample = nz
            lo, hi = np.percentile(sample, [0.5, 99.5]) if sample.size else (0.0, 1.0)
            if hi <= lo:
                hi = lo + 1.0
            self._window = (float(lo), float(hi))
        return self._window

    @property
    def value_range(self) -> tuple[float, float]:
        return float(self.data.min()), float(self.data.max())

    # ------------------------------------------------------------------ 标签读写
    def to_original(self, arr: np.ndarray) -> np.ndarray:
        """把规范方向下的数组变换回原始文件的体素顺序。"""
        if self.is_2d:
            return np.ascontiguousarray(arr[:, :, 0].T[::-1, ::-1])
        transform = ornt.ornt_transform(_RAS, self.orig_ornt)
        return np.ascontiguousarray(ornt.apply_orientation(arr, transform))

    def save_label(self, label: np.ndarray, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = self.to_original(label).astype(np.uint8)
        if self.is_2d:
            Image.fromarray(out, mode="L").save(path)
            return
        header = self.orig_header.copy()
        header.set_data_dtype(np.uint8)
        img = nib.Nifti1Image(out, self.orig_affine, header=header)
        img.header.set_slope_inter(1, 0)
        img.header["cal_min"] = 0
        img.header["cal_max"] = 0
        nib.save(img, str(path))

    def load_label(self, path: Path | str) -> np.ndarray:
        """读取标签文件并对齐到本影像的规范网格（几何不一致时最近邻重采样）。"""
        path = Path(path)
        if file_kind(path) == "2d":
            arr = np.asarray(Image.open(path).convert("L"))
            lab = arr[::-1, ::-1].T[..., None]
        else:
            img = nib.as_closest_canonical(nib.load(str(path)))
            if img.shape[:3] != self.shape or not np.allclose(img.affine, self.affine, atol=1e-3):
                from nibabel.processing import resample_from_to

                img = resample_from_to(img, (self.shape, self.affine), order=0)
            lab = np.asanyarray(img.dataobj)
            lab = lab.reshape(lab.shape[:3]) if lab.ndim > 3 else lab
        if lab.shape != self.shape:
            raise ValueError(f"标签尺寸 {lab.shape} 与影像尺寸 {self.shape} 不一致")
        return np.clip(np.rint(lab), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------- 读取
def _nifti_to_canonical(img: nib.spatialimages.SpatialImage) -> tuple[np.ndarray, nib.Nifti1Image]:
    canon = nib.as_closest_canonical(img)
    data = np.asanyarray(canon.dataobj).astype(np.float32)
    if data.ndim == 2:
        data = data[..., None]
    elif data.ndim > 3:
        data = data.reshape(data.shape[:3] + (-1,))[..., 0]
    return data, canon


def load_nifti(path: Path | str, reference: Volume | None = None) -> Volume:
    """读取 NIfTI。若给出 ``reference`` 且网格不同，则线性重采样到参考网格。"""
    path = Path(path)
    img = nib.load(str(path))
    if img.ndim > 3:
        img = img.slicer[..., 0]
    data, canon = _nifti_to_canonical(img)
    affine = canon.affine
    if reference is not None and (data.shape != reference.shape or not np.allclose(affine, reference.affine, atol=1e-3)):
        from nibabel.processing import resample_from_to

        canon = resample_from_to(canon, (reference.shape, reference.affine), order=1)
        data = np.asanyarray(canon.dataobj).astype(np.float32)
        affine = reference.affine
    zooms = tuple(float(z) for z in canon.header.get_zooms()[:3])
    zooms = (zooms + (1.0, 1.0, 1.0))[:3]
    header = img.header.copy() if isinstance(img.header, nib.Nifti1Header) else nib.Nifti1Header()
    return Volume(
        data=np.ascontiguousarray(data),
        spacing=zooms,
        path=path,
        name=strip_suffix(path.name),
        affine=affine,
        orig_affine=img.affine,
        orig_header=header,
        orig_ornt=ornt.io_orientation(img.affine),
    )


def load_image2d(path: Path | str) -> Volume:
    path = Path(path)
    im = Image.open(path)
    rgb = None
    if im.mode in ("I;16", "I;16B", "I", "F"):
        gray = np.asarray(im, dtype=np.float32)
    else:
        if im.mode not in ("L", "1"):
            rgb_arr = np.asarray(im.convert("RGB"))
            if not (np.array_equal(rgb_arr[..., 0], rgb_arr[..., 1]) and np.array_equal(rgb_arr[..., 0], rgb_arr[..., 2])):
                rgb = rgb_arr
        gray = np.asarray(im.convert("L"), dtype=np.float32)
    if gray.ndim == 3:
        gray = gray[..., 0]
    data = np.ascontiguousarray(gray[::-1, ::-1].T[..., None])
    rgb_vol = None
    if rgb is not None:
        rgb_vol = np.ascontiguousarray(rgb[::-1, ::-1].transpose(1, 0, 2)[:, :, None, :])
    return Volume(data=data, spacing=(1.0, 1.0, 1.0), path=path, name=strip_suffix(path.name), is_2d=True, rgb=rgb_vol)


def load_volumes(paths: list[Path]) -> list[Volume]:
    """读取一个病例的全部序列，第一个序列为参考网格，其余序列对齐到参考网格。"""
    if not paths:
        raise ValueError("病例中没有影像文件")
    if file_kind(paths[0]) == "2d":
        return [load_image2d(paths[0])]
    ref = load_nifti(paths[0])
    vols = [ref]
    for p in paths[1:]:
        vols.append(load_nifti(p, reference=ref))
    return vols


# ---------------------------------------------------------------------- 切片几何
# 屏幕显示采用放射学惯例：轴位/冠状位患者右侧在屏幕左侧；矢状位前方在左侧。
SAGITTAL, CORONAL, AXIAL = 0, 1, 2
PLANE_NAMES = {AXIAL: "轴位", CORONAL: "冠状位", SAGITTAL: "矢状位"}
PLANE_EN = {AXIAL: "Axial", CORONAL: "Coronal", SAGITTAL: "Sagittal"}
# 屏幕四边方位标记：(左, 右, 上, 下)
ORIENTATION_MARKS = {
    AXIAL: ("R", "L", "A", "P"),
    CORONAL: ("R", "L", "S", "I"),
    SAGITTAL: ("A", "P", "S", "I"),
}


def plane_axes(axis: int) -> tuple[int, int]:
    """返回切片平面内的两个体素轴 (列轴 i, 行轴 j)。"""
    i, j = [a for a in range(3) if a != axis]
    return i, j


def slice_view(arr: np.ndarray, axis: int, index: int) -> np.ndarray:
    """取出用于显示的二维切片（返回视图，可原地写入）。形状为 (行, 列[, 通道])。"""
    idx: list = [slice(None)] * 3
    idx[axis] = index
    s = arr[tuple(idx)]
    return np.swapaxes(s, 0, 1)[::-1, ::-1]


def screen_to_voxel(shape: tuple[int, int, int], axis: int, index: int, row: int, col: int) -> tuple[int, int, int]:
    i, j = plane_axes(axis)
    v = [0, 0, 0]
    v[axis] = index
    v[i] = shape[i] - 1 - col
    v[j] = shape[j] - 1 - row
    return tuple(v)  # type: ignore[return-value]


def voxel_to_screen(shape: tuple[int, int, int], axis: int, voxel) -> tuple[int, int]:
    """返回体素在该平面中的 (行, 列)。"""
    i, j = plane_axes(axis)
    return shape[j] - 1 - voxel[j], shape[i] - 1 - voxel[i]


def plane_spacing(spacing, axis: int) -> tuple[float, float]:
    """返回 (行间距, 列间距)。"""
    i, j = plane_axes(axis)
    return float(spacing[j]), float(spacing[i])
