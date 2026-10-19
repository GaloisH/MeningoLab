"""把视图中的鼠标操作转换为标注编辑。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core import tools
from ..core.segmentation import bbox_region
from ..core.volume import plane_spacing, screen_to_voxel, slice_view
from .session import TOOL_BRUSH, TOOL_ERASER, TOOL_GROW, TOOL_NAVIGATE, TOOL_POLYGON, Session

FREEHAND_MIN_POINTS = 6


class AnnotationController(QObject):
    liveEdit = Signal(int)  # 拖动绘制中，仅刷新该平面视图
    previewChanged = Signal(int)  # 多边形预览变化
    message = Signal(str)

    def __init__(self, session: Session):
        super().__init__()
        self.s = session
        self._stroke = None  # (axis, index, region, before, value)
        self._last = None
        self.poly_axis: int | None = None
        self.poly_index = 0
        self.poly_points: list[tuple[float, float]] = []
        self.poly_hover: tuple[float, float] | None = None
        self._poly_drag = 0
        session.toolChanged.connect(lambda _: self.cancel_polygon())
        session.caseLoaded.connect(self.cancel_polygon)
        session.cursorChanged.connect(self._on_cursor)

    # ------------------------------------------------------------------ 公共工具
    def brush_radius(self, axis: int) -> tuple[float, float]:
        sp_r, sp_c = plane_spacing(self.s.volume.spacing, axis)
        r_phys = self.s.brush_size / 2.0 * min(self.s.volume.spacing)
        return r_phys / sp_r, r_phys / sp_c

    def _slice_region(self, axis: int, index: int):
        region = [slice(None)] * 3
        region[axis] = slice(index, index + 1)
        return tuple(region)

    def _paint_opts(self, value: int) -> dict:
        s = self.s
        return dict(
            intensity_range=s.thr_range if s.thr_enabled else None,
            protect_others=s.protect_others,
            erase_only=s.active_label if (value == 0 and s.erase_active_only) else None,
        )

    def _in_bounds(self, axis: int, rf: float, cf: float) -> bool:
        h, w = slice_view(self.s.labelmap.data, axis, 0).shape
        return 0 <= rf < h and 0 <= cf < w

    # ------------------------------------------------------------------ 鼠标事件
    def press(self, axis: int, rf: float, cf: float, shift: bool = False) -> None:
        s = self.s
        if not s.has_data:
            return
        tool = s.tool
        if tool == TOOL_NAVIGATE:
            self._navigate(axis, rf, cf)
        elif tool in (TOOL_BRUSH, TOOL_ERASER):
            value = 0 if (tool == TOOL_ERASER or shift) else s.active_label
            if value and not s.labelset.get(value):
                self.message.emit("请先在“标签”面板中添加并选择一个标签")
                return
            idx = s.cursor[axis]
            region = self._slice_region(axis, idx)
            self._stroke = (axis, idx, region, s.labelmap.snapshot(region), value)
            self._last = (rf, cf)
            self._paint_segment(axis, (rf, cf), (rf, cf))
        elif tool == TOOL_POLYGON:
            if self.poly_axis is None or self.poly_axis != axis or self.poly_index != s.cursor[axis]:
                self.poly_axis, self.poly_index, self.poly_points = axis, s.cursor[axis], []
            self.poly_points.append((rf, cf))
            self._poly_drag = 0
            self.previewChanged.emit(axis)
        elif tool == TOOL_GROW:
            if self._in_bounds(axis, rf, cf):
                self._grow(axis, int(rf), int(cf), erase=shift)

    def move(self, axis: int, rf: float, cf: float, pressed: bool) -> None:
        s = self.s
        if not s.has_data:
            return
        if s.tool == TOOL_NAVIGATE and pressed:
            self._navigate(axis, rf, cf)
        elif self._stroke and pressed and self._stroke[0] == axis:
            self._paint_segment(axis, self._last, (rf, cf))
            self._last = (rf, cf)
        elif s.tool == TOOL_POLYGON and self.poly_axis == axis and self.poly_points:
            if pressed:
                lr, lc = self.poly_points[-1]
                if np.hypot(rf - lr, cf - lc) >= 1.0:
                    self.poly_points.append((rf, cf))
                    self._poly_drag += 1
            self.poly_hover = (rf, cf)
            self.previewChanged.emit(axis)

    def release(self, axis: int, rf: float, cf: float) -> None:
        if self._stroke:
            ax, _, region, before, _ = self._stroke
            self._stroke = None
            if self.s.labelmap.commit(region, before):
                self.s.notify_edit(ax)
            else:
                self.liveEdit.emit(ax)
        elif self.s.tool == TOOL_POLYGON and self._poly_drag >= FREEHAND_MIN_POINTS:
            self.close_polygon()  # 按住拖动 = 套索，松开即闭合

    def double_click(self, axis: int, rf: float, cf: float) -> bool:
        if self.s.tool == TOOL_POLYGON and self.poly_points:
            self.close_polygon()
            return True
        return False

    # ------------------------------------------------------------------ 具体操作
    def _navigate(self, axis: int, rf: float, cf: float) -> None:
        if self._in_bounds(axis, rf, cf):
            self.s.set_cursor(screen_to_voxel(self.s.shape, axis, self.s.cursor[axis], int(rf), int(cf)))

    def _paint_segment(self, axis, p0, p1) -> None:
        s = self.s
        _, idx, _, _, value = self._stroke
        lab2d = slice_view(s.labelmap.data, axis, idx)
        mask = tools.stroke_mask(lab2d.shape, p0, p1, self.brush_radius(axis))
        img2d = slice_view(s.volume.data, axis, idx)
        tools.paint(lab2d, mask, value, image=img2d, **self._paint_opts(value))
        self.liveEdit.emit(axis)

    def close_polygon(self) -> None:
        s = self.s
        axis, pts = self.poly_axis, list(self.poly_points)
        self.cancel_polygon()
        if axis is None or len(pts) < 3 or not s.has_data:
            return
        if not s.labelset.get(s.active_label):
            self.message.emit("请先选择一个标签")
            return
        idx = self.poly_index
        region = self._slice_region(axis, idx)
        before = s.labelmap.snapshot(region)
        lab2d = slice_view(s.labelmap.data, axis, idx)
        mask = tools.polygon_mask(lab2d.shape, pts)
        tools.paint(lab2d, mask, s.active_label, image=slice_view(s.volume.data, axis, idx),
                    **self._paint_opts(s.active_label))
        if s.labelmap.commit(region, before):
            s.notify_edit(axis)

    def cancel_polygon(self) -> None:
        axis = self.poly_axis
        self.poly_axis, self.poly_points, self.poly_hover, self._poly_drag = None, [], None, 0
        if axis is not None:
            self.previewChanged.emit(axis)

    def undo_polygon_point(self) -> None:
        if self.poly_points:
            self.poly_points.pop()
            self.previewChanged.emit(self.poly_axis)

    def _on_cursor(self) -> None:
        if self.poly_axis is not None and self.s.cursor[self.poly_axis] != self.poly_index:
            self.cancel_polygon()

    def _grow(self, axis: int, r: int, c: int, erase: bool = False) -> None:
        s = self.s
        value = 0 if erase else s.active_label
        if value and not s.labelset.get(value):
            self.message.emit("请先选择一个标签")
            return
        lo_w, hi_w = s.window()
        tol = abs(hi_w - lo_w) * s.grow_tolerance / 100.0
        voxel = screen_to_voxel(s.shape, axis, s.cursor[axis], r, c)
        seed_val = float(s.volume.data[voxel])
        lo, hi = seed_val - tol, seed_val + tol
        if s.thr_enabled:
            lo, hi = max(lo, s.thr_range[0]), min(hi, s.thr_range[1])
        if s.grow_3d and not s.is_2d:
            mask = tools.region_grow(s.volume.data, voxel, lo, hi)
            region = bbox_region(mask)
            if region is None:
                self.message.emit("种子点不在强度范围内")
                return
            before = s.labelmap.snapshot(region)
            m = tools.paint(s.labelmap.data[region], mask[region], value, **self._paint_opts(value) | {"intensity_range": None})
            changed = s.labelmap.commit(region, before)
            edit_axis = -1
        else:
            img2d = slice_view(s.volume.data, axis, s.cursor[axis])
            mask = tools.region_grow(img2d, (r, c), lo, hi)
            region = self._slice_region(axis, s.cursor[axis])
            before = s.labelmap.snapshot(region)
            lab2d = slice_view(s.labelmap.data, axis, s.cursor[axis])
            m = tools.paint(lab2d, mask, value, **self._paint_opts(value) | {"intensity_range": None})
            changed = s.labelmap.commit(region, before)
            edit_axis = axis
        if changed:
            s.notify_edit(edit_axis)
            self.message.emit(f"区域生长：{int(m.sum())} 个体素（强度 {lo:.1f} ~ {hi:.1f}）")
        else:
            self.message.emit("区域生长未产生变化")

    # ------------------------------------------------------------------ 菜单/按钮操作
    def interpolate(self, axis: int) -> None:
        s = self.s
        if not s.has_data or s.is_2d:
            return
        before = s.labelmap.data.copy()
        _, filled = tools.interpolate_slices(s.labelmap.data, s.active_label, axis)
        full = (slice(None),) * 3
        if filled and s.labelmap.commit(full, before):
            s.notify_edit(-1)
            self.message.emit(f"层间插值完成：补全 {filled} 层「{s.labelset.name_of(s.active_label)}」")
        else:
            self.message.emit("没有可插值的层：请先在至少两个不相邻的层上勾画当前标签")

    def clear_slice(self, axis: int, only_active: bool = True) -> None:
        s = self.s
        if not s.has_data:
            return
        idx = s.cursor[axis]
        region = self._slice_region(axis, idx)
        before = s.labelmap.snapshot(region)
        lab2d = slice_view(s.labelmap.data, axis, idx)
        if only_active:
            lab2d[lab2d == s.active_label] = 0
        else:
            lab2d[...] = 0
        if s.labelmap.commit(region, before):
            s.notify_edit(axis)

    def undo(self) -> None:
        if self.s.has_data and self.s.labelmap.undo() is not None:
            self.s.notify_edit(-1)

    def redo(self) -> None:
        if self.s.has_data and self.s.labelmap.redo() is not None:
            self.s.notify_edit(-1)
