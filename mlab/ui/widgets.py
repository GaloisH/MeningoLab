"""通用小部件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolButton,
                               QVBoxLayout, QWidget)


class Card(QFrame):
    """带标题、可折叠的卡片容器。"""

    def __init__(self, title: str, parent=None, collapsible: bool = True):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.toggle = QToolButton()
        self.toggle.setObjectName("CardHeader")
        self.toggle.setText(("▾  " if collapsible else "") + title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.toggle.setStyleSheet("QToolButton { font-weight: 600; font-size: 10.5pt; border: none; padding: 0; }"
                                  "QToolButton:hover { background: transparent; }")
        self.toggle.setEnabled(collapsible)
        self._title = title
        self._collapsible = collapsible
        head.addWidget(self.toggle)
        head.addStretch(1)
        self.header_layout = head
        outer.addLayout(head)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        outer.addWidget(self.body)
        self.toggle.clicked.connect(self._toggle)

    def _toggle(self) -> None:
        vis = not self.body.isVisible()
        self.body.setVisible(vis)
        self.toggle.setText(("▾  " if vis else "▸  ") + self._title)

    def add(self, w) -> None:
        if isinstance(w, QWidget):
            self.body_layout.addWidget(w)
        else:
            self.body_layout.addLayout(w)


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Hint")
    lab.setWordWrap(True)
    lab.setMinimumWidth(40)  # 长路径等无法断行的文本不应撑宽侧边栏
    return lab


def row(*widgets, stretch_last: bool = False, spacing: int = 6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
        else:
            lay.addLayout(w)
    return lay


class LabeledSlider(QWidget):
    """标题 + 滑块 + 数值。"""

    valueChanged = Signal(int)

    def __init__(self, title: str, lo: int, hi: int, value: int, suffix: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.title = QLabel(title)
        self.title.setMinimumWidth(56)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.value_label = QLabel()
        self.value_label.setMinimumWidth(42)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._suffix = suffix
        lay.addWidget(self.title)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._changed)
        self._changed(value, emit=False)

    def _changed(self, v: int, emit: bool = True) -> None:
        self.value_label.setText(f"{v}{self._suffix}")
        if emit:
            self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int) -> None:
        self.slider.setValue(v)


class ColorDot(QWidget):
    def __init__(self, color=(255, 255, 255), size: int = 14, parent=None):
        super().__init__(parent)
        self._color = QColor(*color)
        self.setFixedSize(size, size)

    def set_color(self, color) -> None:
        self._color = QColor(*color)
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, 4, 4)


def spin(lo: float, hi: float, value: float, decimals: int = 1, step: float = 1.0) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(value)
    sb.setKeyboardTracking(False)
    sb.setMinimumWidth(64)  # 避免按量程计算出过大的最小宽度撑破侧边栏
    sb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return sb
