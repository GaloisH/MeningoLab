"""当前病例的界面状态，所有视图与面板通过信号同步。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.labels import LabelSet
from ..core.project import Case, Project
from ..core.segmentation import LabelMap
from ..core.volume import AXIAL, Volume

TOOL_NAVIGATE, TOOL_BRUSH, TOOL_ERASER, TOOL_POLYGON, TOOL_GROW = "navigate", "brush", "eraser", "polygon", "grow"
TOOL_TEXT = {
    TOOL_NAVIGATE: ("浏览定位", "N"),
    TOOL_BRUSH: ("画笔", "B"),
    TOOL_ERASER: ("橡皮擦", "E"),
    TOOL_POLYGON: ("多边形 / 套索", "P"),
    TOOL_GROW: ("区域生长", "G"),
}


class Session(QObject):
    caseLoaded = Signal()
    labelsEdited = Signal(int)  # 编辑所在的平面轴；-1 表示三维范围的修改
    cursorChanged = Signal()
    displayChanged = Signal()
    labelSetChanged = Signal()
    activeLabelChanged = Signal(int)
    toolChanged = Signal(str)
    toolOptionsChanged = Signal()
    modifiedChanged = Signal(bool)
    activeAxisChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self.case: Case | None = None
        self.volumes: list[Volume] = []
        self.seq_index = 0
        self.labelmap: LabelMap | None = None
        self.labelset = LabelSet.default()
        self.active_label = self.labelset.labels[0].value if len(self.labelset) else 1
        self.cursor = [0, 0, 0]
        self.windows: dict[int, tuple[float, float]] = {}
        self.active_axis = AXIAL
        # 显示
        self.opacity = 0.45
        self.outline = True
        self.show_labels = True
        self.show_crosshair = True
        # 工具
        self.tool = TOOL_BRUSH
        self.brush_size = 6
        self.protect_others = True
        self.erase_active_only = False
        self.thr_enabled = False
        self.thr_range = (0.0, 1.0)
        self.grow_tolerance = 10.0  # 窗宽的百分比
        self.grow_3d = False

    # ------------------------------------------------------------------ 基本属性
    @property
    def has_data(self) -> bool:
        return bool(self.volumes) and self.labelmap is not None

    @property
    def volume(self) -> Volume:
        return self.volumes[self.seq_index]

    @property
    def is_2d(self) -> bool:
        return self.has_data and self.volume.is_2d

    @property
    def shape(self):
        return self.volume.shape

    def window(self) -> tuple[float, float]:
        return self.windows.get(self.seq_index) or self.volume.auto_window()

    # ------------------------------------------------------------------ 修改
    def load(self, case: Case, volumes: list[Volume], labelmap: LabelMap) -> None:
        self.case, self.volumes, self.labelmap = case, volumes, labelmap
        self.seq_index = 0
        self.windows = {}
        self.cursor = [s // 2 for s in volumes[0].shape]
        lo, hi = volumes[0].auto_window()
        self.thr_range = (lo + (hi - lo) * 0.5, hi)
        self.caseLoaded.emit()
        self.modifiedChanged.emit(False)

    def clear(self) -> None:
        self.case, self.volumes, self.labelmap = None, [], None
        self.caseLoaded.emit()

    def set_cursor(self, voxel) -> None:
        if not self.has_data:
            return
        v = [int(min(max(c, 0), s - 1)) for c, s in zip(voxel, self.shape)]
        if v != self.cursor:
            self.cursor = v
            self.cursorChanged.emit()

    def move_slice(self, axis: int, delta: int) -> None:
        v = list(self.cursor)
        v[axis] += delta
        self.set_cursor(v)

    def set_window(self, lo: float, hi: float) -> None:
        if hi - lo < 1e-6:
            hi = lo + 1e-6
        self.windows[self.seq_index] = (lo, hi)
        self.displayChanged.emit()

    def reset_window(self) -> None:
        self.windows.pop(self.seq_index, None)
        self.displayChanged.emit()

    def set_sequence(self, index: int) -> None:
        if 0 <= index < len(self.volumes) and index != self.seq_index:
            self.seq_index = index
            self.displayChanged.emit()

    def set_display(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.displayChanged.emit()

    def set_tool(self, tool: str) -> None:
        if tool != self.tool:
            self.tool = tool
            self.toolChanged.emit(tool)

    def set_tool_option(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.toolOptionsChanged.emit()

    def set_active_label(self, value: int) -> None:
        if value != self.active_label:
            self.active_label = value
            self.activeLabelChanged.emit(value)

    def set_active_axis(self, axis: int) -> None:
        if axis != self.active_axis:
            self.active_axis = axis
            self.activeAxisChanged.emit(axis)

    def set_labelset(self, ls: LabelSet) -> None:
        self.labelset = ls
        if not ls.get(self.active_label) and len(ls):
            self.active_label = ls.labels[0].value
        if self.project:
            self.project.save_labelset(ls)
        self.labelSetChanged.emit()

    def notify_edit(self, axis: int = -1) -> None:
        if self.labelmap:
            self.labelmap.modified = True
        self.labelsEdited.emit(axis)
        self.modifiedChanged.emit(True)

    def mark_saved(self) -> None:
        if self.labelmap:
            self.labelmap.modified = False
        self.modifiedChanged.emit(False)
