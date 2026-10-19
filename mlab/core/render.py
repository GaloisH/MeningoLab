"""切片渲染：窗宽窗位 + 标签半透明叠加 + 轮廓线。"""
from __future__ import annotations

import numpy as np


def window_to_uint8(img: np.ndarray, lo: float, hi: float) -> np.ndarray:
    scale = 255.0 / max(hi - lo, 1e-6)
    out = (img.astype(np.float32) - lo) * scale
    return np.clip(out, 0, 255).astype(np.uint8)


def label_edges(lab: np.ndarray) -> np.ndarray:
    """标签边界像素（与四邻域取值不同的非零像素）。"""
    edge = np.zeros(lab.shape, bool)
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    edge[:-1, :] |= lab[:-1, :] != lab[1:, :]
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge[:, :-1] |= lab[:, :-1] != lab[:, 1:]
    return edge & (lab > 0)


def compose(base: np.ndarray, lab: np.ndarray | None, lut: np.ndarray, opacity: float, outline: bool) -> np.ndarray:
    """``base`` 为 (H, W) 灰度或 (H, W, 3) 彩色 uint8，返回连续的 (H, W, 3) uint8。"""
    rgb = np.repeat(base[..., None], 3, axis=2) if base.ndim == 2 else base
    if lab is None or not lab.any():
        return np.ascontiguousarray(rgb)
    colors = lut[lab]  # (H, W, 4)
    alpha = colors[..., 3] * opacity
    if outline:
        edge = label_edges(lab)
        alpha = np.where(edge, colors[..., 3], alpha)
    a = alpha[..., None]
    out = rgb.astype(np.float32) * (1 - a) + colors[..., :3] * a
    return np.ascontiguousarray(out.astype(np.uint8))
