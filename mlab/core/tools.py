"""标注算法：画笔、多边形填充、区域生长、层间插值。均为纯 numpy/scipy 实现，便于测试。"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage


def disk_mask(shape: tuple[int, int], center: tuple[float, float], radius_rc: tuple[float, float]) -> np.ndarray:
    """以连续坐标 ``center=(行, 列)`` 为圆心的椭圆形笔刷（行/列半径可不同以补偿各向异性）。"""
    h, w = shape
    cr, cc = center
    rr, rc = max(radius_rc[0], 0.5), max(radius_rc[1], 0.5)
    r0, r1 = max(int(np.floor(cr - rr)), 0), min(int(np.ceil(cr + rr)) + 1, h)
    c0, c1 = max(int(np.floor(cc - rc)), 0), min(int(np.ceil(cc + rc)) + 1, w)
    mask = np.zeros(shape, bool)
    if r0 >= r1 or c0 >= c1:
        return mask
    rows = (np.arange(r0, r1) + 0.5 - cr) / rr
    cols = (np.arange(c0, c1) + 0.5 - cc) / rc
    mask[r0:r1, c0:c1] = rows[:, None] ** 2 + cols[None, :] ** 2 <= 1.0
    pr, pc = int(np.floor(cr)), int(np.floor(cc))
    if 0 <= pr < h and 0 <= pc < w:  # 最小笔刷也至少覆盖光标下的像素
        mask[pr, pc] = True
    return mask


def stroke_mask(shape, p0, p1, radius_rc) -> np.ndarray:
    """从 p0 到 p1 的连续笔划。"""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    dist = float(np.hypot(*(p1 - p0)))
    step = max(0.5 * min(radius_rc), 0.5)
    n = max(int(np.ceil(dist / step)), 1)
    mask = np.zeros(shape, bool)
    for t in np.linspace(0.0, 1.0, n + 1):
        mask |= disk_mask(shape, tuple(p0 + (p1 - p0) * t), radius_rc)
    return mask


def polygon_mask(shape: tuple[int, int], points: list[tuple[float, float]]) -> np.ndarray:
    """以 (行, 列) 连续坐标给出的多边形内部区域。"""
    h, w = shape
    if len(points) < 3:
        return np.zeros(shape, bool)
    img = Image.new("1", (w, h), 0)
    ImageDraw.Draw(img).polygon([(c - 0.5, r - 0.5) for r, c in points], fill=1, outline=1)
    return np.asarray(img, dtype=bool)


def constrain(mask: np.ndarray, label: np.ndarray, value: int, *, image: np.ndarray | None = None,
              intensity_range: tuple[float, float] | None = None, protect_others: bool = False,
              erase_only: int | None = None) -> np.ndarray:
    """根据强度范围、标签保护等选项收紧绘制区域。``value == 0`` 表示擦除。"""
    m = mask
    if intensity_range is not None and image is not None:
        lo, hi = intensity_range
        m = m & (image >= lo) & (image <= hi)
    if value == 0:
        if erase_only is not None:
            m = m & (label == erase_only)
    elif protect_others:
        m = m & ((label == 0) | (label == value))
    return m


def paint(label: np.ndarray, mask: np.ndarray, value: int, **opts) -> np.ndarray:
    """在 ``label`` 上原地绘制，返回实际生效的掩膜。"""
    m = constrain(mask, label, value, **opts)
    label[m] = value
    return m


def region_grow(image: np.ndarray, seed: tuple[int, ...], lo: float, hi: float, connectivity: int = 1) -> np.ndarray:
    """从种子点出发、强度位于 [lo, hi] 的连通区域（2D 或 3D）。"""
    inside = (image >= lo) & (image <= hi)
    if not inside[seed]:
        return np.zeros(image.shape, bool)
    structure = ndimage.generate_binary_structure(image.ndim, connectivity)
    lab, _ = ndimage.label(inside, structure=structure)
    return lab == lab[seed]


def _signed_distance(mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return np.full(mask.shape, np.inf, np.float32)
    inside = ndimage.distance_transform_edt(mask)
    outside = ndimage.distance_transform_edt(~mask)
    return (outside - inside).astype(np.float32)


def interpolate_slices(label: np.ndarray, value: int, axis: int) -> tuple[np.ndarray, int]:
    """沿 ``axis`` 对标签 ``value`` 做层间插值（基于符号距离场）。

    只填补两个已标注层之间、该标签为空的层，且不覆盖其他标签。
    返回 (新增体素掩膜, 填补的层数)。
    """
    present = np.flatnonzero((label == value).any(axis=tuple(a for a in range(3) if a != axis)))
    added = np.zeros(label.shape, bool)
    filled = 0
    for a, b in zip(present[:-1], present[1:]):
        if b - a <= 1:
            continue
        sa = np.take(label, a, axis=axis) == value
        sb = np.take(label, b, axis=axis) == value
        da, db = _signed_distance(sa), _signed_distance(sb)
        for k in range(a + 1, b):
            t = (k - a) / (b - a)
            m = ((1 - t) * da + t * db) < 0
            idx = [slice(None)] * 3
            idx[axis] = k
            cur = label[tuple(idx)]
            m &= cur == 0
            if m.any():
                cur[m] = value
                added[tuple(idx)] |= m
                filled += 1
    return added, filled
