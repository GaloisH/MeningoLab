"""标签体数据与撤销/重做。"""
from __future__ import annotations

import numpy as np

Region = tuple  # tuple[slice, slice, slice]

MAX_UNDO_BYTES = 768 * 1024 * 1024
MAX_UNDO_STEPS = 100


def bbox_region(mask: np.ndarray) -> Region | None:
    """返回布尔数组中 True 元素的最小包围盒。"""
    if not mask.any():
        return None
    region = []
    for ax in range(mask.ndim):
        other = tuple(a for a in range(mask.ndim) if a != ax)
        hit = np.flatnonzero(mask.any(axis=other))
        region.append(slice(int(hit[0]), int(hit[-1]) + 1))
    return tuple(region)


class LabelMap:
    """uint8 标签体（与影像同为 RAS 规范方向），记录编辑历史。"""

    def __init__(self, shape: tuple[int, int, int], data: np.ndarray | None = None):
        self.data = np.zeros(shape, np.uint8) if data is None else np.ascontiguousarray(data, dtype=np.uint8)
        self._undo: list[tuple[Region, np.ndarray, np.ndarray]] = []
        self._redo: list[tuple[Region, np.ndarray, np.ndarray]] = []
        self.modified = False

    @property
    def shape(self):
        return self.data.shape

    def snapshot(self, region: Region) -> np.ndarray:
        return self.data[region].copy()

    def commit(self, region: Region, before: np.ndarray) -> bool:
        """在对 ``data[region]`` 完成修改后调用，记录一次可撤销操作。返回是否有变化。"""
        after = self.data[region]
        changed = before != after
        sub = bbox_region(changed)
        if sub is None:
            return False
        full = tuple(slice((r.start or 0) + s.start, (r.start or 0) + s.stop) for r, s in zip(region, sub))
        self._undo.append((full, before[sub].copy(), after[sub].copy()))
        self._redo.clear()
        self._trim()
        self.modified = True
        return True

    def _trim(self) -> None:
        total = sum(b.nbytes * 2 for _, b, _ in self._undo)
        while self._undo and (len(self._undo) > MAX_UNDO_STEPS or total > MAX_UNDO_BYTES):
            _, b, _ = self._undo.pop(0)
            total -= b.nbytes * 2

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Region | None:
        if not self._undo:
            return None
        region, before, after = self._undo.pop()
        self.data[region] = before
        self._redo.append((region, before, after))
        self.modified = True
        return region

    def redo(self) -> Region | None:
        if not self._redo:
            return None
        region, before, after = self._redo.pop()
        self.data[region] = after
        self._undo.append((region, before, after))
        self.modified = True
        return region

    def replace(self, new: np.ndarray) -> bool:
        """整体替换（如应用模型预测），可撤销。"""
        full = (slice(None),) * 3
        before = self.data.copy()
        self.data[...] = new
        return self.commit(full, before)

    def stats(self, spacing) -> dict[int, tuple[int, float]]:
        """各标签体素数与体积 (mL)。"""
        counts = np.bincount(self.data.ravel(), minlength=256)
        voxel_ml = float(np.prod(spacing)) / 1000.0
        return {v: (int(c), c * voxel_ml) for v, c in enumerate(counts) if v and c}
