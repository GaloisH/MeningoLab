"""右侧面板：标签、工具选项、显示设置。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from ..core.volume import AXIAL, CORONAL, PLANE_NAMES, SAGITTAL
from .controller import AnnotationController
from .session import TOOL_BRUSH, TOOL_ERASER, TOOL_GROW, TOOL_POLYGON, TOOL_TEXT, Session
from .theme import Theme
from .widgets import Card, ColorDot, LabeledSlider, hint, row, spin


class LabelRow(QFrame):
    clicked = Signal(int)
    visibilityToggled = Signal(int, bool)

    def __init__(self, value: int, name: str, color, visible: bool, icon_fn, parent=None):
        super().__init__(parent)
        self.value = value
        self._icon_fn = icon_fn
        self.setObjectName("LabelRow")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 6, 5)
        lay.setSpacing(8)
        self.dot = ColorDot(color, 16)
        self.key = QLabel(str(value) if value <= 9 else "")
        self.key.setFixedWidth(16)
        self.key.setAlignment(Qt.AlignCenter)
        self.key.setProperty("muted", True)
        self.key.setToolTip(f"快捷键 {value}" if value <= 9 else "")
        self.name = QLabel(name)
        self.vol = QLabel("–")
        self.vol.setProperty("muted", True)
        self.vol.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.eye = QToolButton()
        self.eye.setCheckable(True)
        self.eye.setChecked(visible)
        self.eye.setAutoRaise(True)
        self.eye.setStyleSheet("QToolButton, QToolButton:checked { border: none; background: transparent; padding: 2px; }")
        self.eye.setToolTip("显示 / 隐藏该标签")
        self.eye.toggled.connect(self._eye)
        self._eye(visible, emit=False)
        lay.addWidget(self.key)
        lay.addWidget(self.dot)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.vol)
        lay.addWidget(self.eye)

    def _eye(self, on: bool, emit: bool = True) -> None:
        self.eye.setIcon(self._icon_fn("eye" if on else "eye-off", 16))
        if emit:
            self.visibilityToggled.emit(self.value, on)

    def set_active(self, active: bool, theme: Theme) -> None:
        if active:
            self.setStyleSheet(f"#LabelRow {{ background: {theme.accent_soft}; border: 1px solid {theme.accent};"
                               f" border-radius: 7px; }} #LabelRow QLabel {{ font-weight: 600; }}")
        else:
            self.setStyleSheet(f"#LabelRow {{ background: transparent; border: 1px solid transparent;"
                               f" border-radius: 7px; }} #LabelRow:hover {{ background: {theme.card_hover}; }}")

    def mousePressEvent(self, ev) -> None:
        self.clicked.emit(self.value)
        super().mousePressEvent(ev)


class LabelPanel(Card):
    editRequested = Signal()

    def __init__(self, session: Session, theme: Theme, icon_fn, parent=None):
        super().__init__("标签", parent)
        self.s = session
        self.theme = theme
        self._icon_fn = icon_fn
        self.edit_btn = QToolButton()
        self.edit_btn.setToolTip("编辑标签（名称、颜色、增删）")
        self.edit_btn.setAutoRaise(True)
        self.edit_btn.clicked.connect(self.editRequested)
        self.header_layout.addWidget(self.edit_btn)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(2)
        self.add(self.rows_box)
        self.total = hint("")
        self.add(self.total)
        self.rows: dict[int, LabelRow] = {}
        session.labelSetChanged.connect(self.rebuild)
        session.activeLabelChanged.connect(lambda _: self._highlight())
        session.labelsEdited.connect(lambda _: self.update_stats())
        session.caseLoaded.connect(self.update_stats)
        self.refresh_icons()
        self.rebuild()

    def refresh_icons(self) -> None:
        self.edit_btn.setIcon(self._icon_fn("edit", 16))
        for r in self.rows.values():
            r._eye(r.eye.isChecked(), emit=False)

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._highlight()

    def rebuild(self) -> None:
        while self.rows_box.count():
            w = self.rows_box.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.rows = {}
        for lab in self.s.labelset:
            r = LabelRow(lab.value, lab.name, lab.color, lab.visible, self._icon_fn)
            r.clicked.connect(self.s.set_active_label)
            r.visibilityToggled.connect(self._toggle_visible)
            self.rows_box.addWidget(r)
            self.rows[lab.value] = r
        if not self.rows:
            self.rows_box.addWidget(hint("还没有标签，点击右上角编辑按钮添加。"))
        self._highlight()
        self.update_stats()

    def _toggle_visible(self, value: int, on: bool) -> None:
        lab = self.s.labelset.get(value)
        if lab:
            lab.visible = on
            self.s.displayChanged.emit()

    def _highlight(self) -> None:
        for v, r in self.rows.items():
            r.set_active(v == self.s.active_label, self.theme)

    def update_stats(self) -> None:
        if not self.s.has_data:
            for r in self.rows.values():
                r.vol.setText("–")
            self.total.setText("数字键 1–9 快速切换标签")
            return
        stats = self.s.labelmap.stats(self.s.volume.spacing)
        unit_2d = self.s.is_2d
        for v, r in self.rows.items():
            n, ml = stats.get(v, (0, 0.0))
            r.vol.setText((f"{n} px" if unit_2d else f"{ml:.2f} mL") if n else "–")
        unknown = [v for v in stats if v not in self.rows]
        extra = f"；存在未定义的标签值 {unknown}" if unknown else ""
        self.total.setText("数字键 1–9 快速切换标签" + extra)


class ToolOptionsPanel(Card):
    def __init__(self, session: Session, controller: AnnotationController, parent=None):
        super().__init__("工具选项", parent)
        self.s = session
        self.ctrl = controller
        self.tool_title = QLabel()
        self.tool_title.setStyleSheet("font-weight: 600;")
        self.add(self.tool_title)

        # 画笔
        self.brush_box = QWidget()
        bl = QVBoxLayout(self.brush_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.brush = LabeledSlider("笔刷大小", 1, 60, session.brush_size, " px")
        self.brush.valueChanged.connect(lambda v: session.set_tool_option(brush_size=v))
        bl.addWidget(self.brush)
        self.erase_only = QCheckBox("橡皮仅擦除当前标签")
        self.erase_only.toggled.connect(lambda on: session.set_tool_option(erase_active_only=on))
        bl.addWidget(self.erase_only)
        self.add(self.brush_box)

        # 区域生长
        self.grow_box = QWidget()
        gl = QVBoxLayout(self.grow_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(6)
        self.tol = LabeledSlider("容差", 1, 60, int(session.grow_tolerance), " %")
        self.tol.valueChanged.connect(lambda v: session.set_tool_option(grow_tolerance=float(v)))
        gl.addWidget(self.tol)
        self.grow3d = QCheckBox("三维生长（跨层）")
        self.grow3d.toggled.connect(lambda on: session.set_tool_option(grow_3d=on))
        gl.addWidget(self.grow3d)
        gl.addWidget(hint("点击病灶内部作为种子点，按种子强度 ± 容差（窗宽百分比）生长；Shift+点击 擦除。"))
        self.add(self.grow_box)

        self.poly_hint = hint("单击添加顶点，双击 / 右键 / 回车闭合填充；按住左键拖动为自由套索。"
                              "Backspace 撤回顶点，Esc 取消。")
        self.add(self.poly_hint)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(128,128,128,0.25);")
        self.add(line)

        self.protect = QCheckBox("保护其他标签（不覆盖）")
        self.protect.setChecked(session.protect_others)
        self.protect.toggled.connect(lambda on: session.set_tool_option(protect_others=on))
        self.add(self.protect)

        self.thr = QCheckBox("强度范围限制")
        self.thr.setToolTip("画笔、多边形只在强度位于范围内的像素上生效，便于勾画强化的脑膜")
        self.thr.toggled.connect(self._thr_changed)
        self.lo = spin(-1e6, 1e6, 0)
        self.hi = spin(-1e6, 1e6, 1)
        self.lo.valueChanged.connect(self._thr_changed)
        self.hi.valueChanged.connect(self._thr_changed)
        self.from_window = QPushButton("取当前窗")
        self.from_window.setToolTip("用当前窗宽窗位的范围作为强度限制")
        self.from_window.clicked.connect(self._take_window)
        self.add(self.thr)
        self.add(row(QLabel("下限"), self.lo, QLabel("上限"), self.hi))
        self.add(self.from_window)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: rgba(128,128,128,0.25);")
        self.add(line2)
        self.interp_axis = QComboBox()
        for ax in (AXIAL, CORONAL, SAGITTAL):
            self.interp_axis.addItem(PLANE_NAMES[ax], ax)
        self.interp_btn = QPushButton("层间插值")
        self.interp_btn.setToolTip("在已勾画的不相邻层之间自动补全当前标签（Ctrl+I）")
        self.interp_btn.clicked.connect(lambda: controller.interpolate(self.interp_axis.currentData()))
        self.add(row(self.interp_axis, self.interp_btn, stretch_last=True))
        self.clear_btn = QPushButton("清除本层当前标签")
        self.clear_btn.setProperty("danger", True)
        self.clear_btn.clicked.connect(lambda: controller.clear_slice(session.active_axis))
        self.add(self.clear_btn)

        session.toolChanged.connect(self._on_tool)
        session.caseLoaded.connect(self._on_case)
        session.toolOptionsChanged.connect(self._sync)
        self._on_tool(session.tool)

    def _on_tool(self, tool: str) -> None:
        name, key = TOOL_TEXT[tool]
        self.tool_title.setText(f"当前：{name}（{key}）")
        self.brush_box.setVisible(tool in (TOOL_BRUSH, TOOL_ERASER))
        self.erase_only.setVisible(tool == TOOL_ERASER)
        self.grow_box.setVisible(tool == TOOL_GROW)
        self.poly_hint.setVisible(tool == TOOL_POLYGON)

    def _on_case(self) -> None:
        s = self.s
        if not s.has_data:
            return
        vmin, vmax = s.volume.value_range
        step = max((vmax - vmin) / 200.0, 0.01)
        for sb in (self.lo, self.hi):
            sb.blockSignals(True)
            sb.setRange(vmin - abs(vmax - vmin), vmax + abs(vmax - vmin))
            sb.setSingleStep(step)
        self.lo.setValue(s.thr_range[0])
        self.hi.setValue(s.thr_range[1])
        for sb in (self.lo, self.hi):
            sb.blockSignals(False)
        is3d = not s.is_2d
        self.interp_axis.setEnabled(is3d)
        self.interp_btn.setEnabled(is3d)
        self.grow3d.setEnabled(is3d)

    def _thr_changed(self, *_):
        self.s.set_tool_option(thr_enabled=self.thr.isChecked(), thr_range=(self.lo.value(), self.hi.value()))

    def _take_window(self) -> None:
        if self.s.has_data:
            lo, hi = self.s.window()
            self.lo.setValue(lo)
            self.hi.setValue(hi)
            self.thr.setChecked(True)

    def _sync(self) -> None:
        if self.brush.value() != self.s.brush_size:
            self.brush.slider.blockSignals(True)
            self.brush.setValue(self.s.brush_size)
            self.brush._changed(self.s.brush_size, emit=False)
            self.brush.slider.blockSignals(False)


class DisplayPanel(Card):
    def __init__(self, session: Session, parent=None):
        super().__init__("显示", parent)
        self.s = session
        self.seq = QComboBox()
        self.seq.currentIndexChanged.connect(lambda i: session.set_sequence(i) if i >= 0 else None)
        self.seq_row = row(QLabel("底图序列"), self.seq, stretch_last=True)
        self.add(self.seq_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.ww = spin(0.001, 1e7, 1, 1)
        self.wl = spin(-1e7, 1e7, 0, 1)
        self.ww.valueChanged.connect(self._wl_changed)
        self.wl.valueChanged.connect(self._wl_changed)
        self.auto_btn = QPushButton("自动")
        self.auto_btn.setToolTip("按影像强度分布自动设置窗宽窗位")
        self.auto_btn.clicked.connect(session.reset_window)
        grid.addWidget(QLabel("窗宽"), 0, 0)
        grid.addWidget(self.ww, 0, 1)
        grid.addWidget(QLabel("窗位"), 1, 0)
        grid.addWidget(self.wl, 1, 1)
        grid.addWidget(self.auto_btn, 0, 2, 2, 1)
        grid.setColumnStretch(1, 1)
        self.wl_widget = QWidget()
        self.wl_widget.setLayout(grid)
        self.add(self.wl_widget)
        self.add(hint("右键拖动调节窗宽窗位；滚轮翻层，Ctrl+滚轮缩放，中键或空格+左键平移。"))

        self.opacity = LabeledSlider("标签透明度", 0, 100, int(session.opacity * 100), " %")
        self.opacity.valueChanged.connect(lambda v: session.set_display(opacity=v / 100.0))
        self.add(self.opacity)
        self.outline = QCheckBox("显示轮廓线")
        self.outline.setChecked(session.outline)
        self.outline.toggled.connect(lambda on: session.set_display(outline=on))
        self.labels = QCheckBox("显示标签 (H)")
        self.labels.setChecked(session.show_labels)
        self.labels.toggled.connect(lambda on: session.set_display(show_labels=on))
        self.cross = QCheckBox("十字定位线")
        self.cross.setChecked(session.show_crosshair)
        self.cross.toggled.connect(lambda on: session.set_display(show_crosshair=on))
        self.add(row(self.outline, self.cross, None))
        self.add(self.labels)

        session.caseLoaded.connect(self._on_case)
        session.displayChanged.connect(self._sync)

    def _on_case(self) -> None:
        s = self.s
        self.seq.blockSignals(True)
        self.seq.clear()
        if s.has_data:
            names = s.case.sequence_names if s.case else [v.name for v in s.volumes]
            for i, v in enumerate(s.volumes):
                self.seq.addItem(names[i] if i < len(names) else v.name)
        self.seq.blockSignals(False)
        self.seq.setEnabled(len(s.volumes) > 1)
        self._sync()

    def _sync(self) -> None:
        s = self.s
        if not s.has_data:
            return
        self.wl_widget.setEnabled(s.volume.rgb is None)
        lo, hi = s.window()
        for sb, val in ((self.ww, hi - lo), (self.wl, (hi + lo) / 2)):
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)
        if self.seq.currentIndex() != s.seq_index:
            self.seq.blockSignals(True)
            self.seq.setCurrentIndex(s.seq_index)
            self.seq.blockSignals(False)
        for cb, val in ((self.labels, s.show_labels), (self.outline, s.outline), (self.cross, s.show_crosshair)):
            if cb.isChecked() != val:
                cb.blockSignals(True)
                cb.setChecked(val)
                cb.blockSignals(False)

    def _wl_changed(self, *_):
        w, l = self.ww.value(), self.wl.value()
        self.s.set_window(l - w / 2, l + w / 2)
