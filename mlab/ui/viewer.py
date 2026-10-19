"""三视图（轴位 / 冠状位 / 矢状位）布局与联动。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget

from ..core.volume import AXIAL, CORONAL, SAGITTAL
from .controller import AnnotationController
from .session import Session
from .slice_view import ViewPanel


class Viewer(QWidget):
    hovered = Signal(object)  # voxel 或 None
    layoutChanged = Signal(bool)  # 是否单视图

    def __init__(self, session: Session, controller: AnnotationController, icon_fn, parent=None):
        super().__init__(parent)
        self.s = session
        self.ctrl = controller
        self.panels = {ax: ViewPanel(ax, session, controller, icon_fn) for ax in (AXIAL, CORONAL, SAGITTAL)}
        self.single: int | None = None
        self._was_2d = False

        self._stack = QStackedLayout(self)
        self._empty = QLabel("打开数据目录开始标注\n\n文件 → 打开数据目录（Ctrl+O）")
        self._empty.setObjectName("EmptyHint")
        self._empty.setAlignment(Qt.AlignCenter)
        holder = QWidget()
        self._grid = QGridLayout(holder)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(8)
        self._grid.addWidget(self.panels[AXIAL], 0, 0, 2, 1)
        self._grid.addWidget(self.panels[CORONAL], 0, 1)
        self._grid.addWidget(self.panels[SAGITTAL], 1, 1)
        self._grid.setColumnStretch(0, 3)
        self._grid.setColumnStretch(1, 2)
        empty_holder = QWidget()
        QVBoxLayout(empty_holder).addWidget(self._empty)
        self._stack.addWidget(empty_holder)
        self._stack.addWidget(holder)

        for ax, p in self.panels.items():
            p.max_btn.clicked.connect(lambda _=False, a=ax: self.toggle_single(a))
            p.canvas.maximizeRequested.connect(self.toggle_single)
            p.canvas.hovered.connect(lambda axis, v: self.hovered.emit(v))

        s = session
        s.caseLoaded.connect(self._on_case_loaded)
        s.cursorChanged.connect(self.refresh_all)
        s.displayChanged.connect(self.refresh_all)
        s.labelSetChanged.connect(self.refresh_all)
        s.labelsEdited.connect(lambda _axis: self.refresh_all())
        s.activeAxisChanged.connect(self._on_active_axis)
        s.toolChanged.connect(self._on_tool)
        s.activeLabelChanged.connect(lambda _: self._on_tool(s.tool))
        s.toolOptionsChanged.connect(lambda: self._on_tool(s.tool))
        controller.liveEdit.connect(lambda ax: self.panels[ax].canvas.refresh())
        controller.previewChanged.connect(lambda ax: self.panels[ax].canvas._update_overlays())
        self._on_active_axis(s.active_axis)

    def _on_case_loaded(self) -> None:
        has = self.s.has_data
        self._stack.setCurrentIndex(1 if has else 0)
        if has and self.s.is_2d:
            self.set_single(AXIAL)
        elif has and self._was_2d:  # 从二维图片切回三维病例时恢复三视图
            self.set_single(None)
        self._was_2d = has and self.s.is_2d
        for p in self.panels.values():
            p.canvas._img_size = (0, 0)  # 强制重新适配窗口
            p.max_btn.setVisible(not self.s.is_2d)
        self.refresh_all()

    def refresh_all(self) -> None:
        for ax, p in self.panels.items():
            if self.single is None or self.single == ax:
                p.refresh()

    def _on_active_axis(self, axis: int) -> None:
        for ax, p in self.panels.items():
            p.set_active(ax == axis)

    def _on_tool(self, _tool: str) -> None:
        for p in self.panels.values():
            p.canvas._update_overlays()
            p.canvas._update_cursor_shape()

    def toggle_single(self, axis: int) -> None:
        self.set_single(None if self.single == axis else axis)

    def set_single(self, axis: int | None) -> None:
        if self.s.has_data and self.s.is_2d:
            axis = AXIAL
        self.single = axis
        for ax, p in self.panels.items():
            p.setVisible(axis is None or ax == axis)
            p.refresh_icons(maximized=axis == ax)
        if axis is not None:
            self._grid.setColumnStretch(0, 1 if axis == AXIAL else 0)
            self._grid.setColumnStretch(1, 0 if axis == AXIAL else 1)
            self.s.set_active_axis(axis)
        else:
            self._grid.setColumnStretch(0, 3)
            self._grid.setColumnStretch(1, 2)
        self.layoutChanged.emit(axis is not None)
        self.refresh_all()

    def reset_views(self) -> None:
        for p in self.panels.values():
            p.canvas.reset_view()

    def refresh_icons(self) -> None:
        for ax, p in self.panels.items():
            p.refresh_icons(maximized=self.single == ax)
