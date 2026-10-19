"""左侧病例列表。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QComboBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..core.project import STATUS_COLOR, STATUS_ORDER, STATUS_TEXT, Project
from .theme import Theme
from .widgets import row

ROLE_CASE = Qt.UserRole + 1
ROLE_STATUS = Qt.UserRole + 2
ROLE_SUB = Qt.UserRole + 3


class CaseDelegate(QStyledItemDelegate):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 52)

    def paint(self, p: QPainter, option, index) -> None:
        t = self.theme
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 3, -6, -3)
        selected = option.state & QStyle.State_Selected
        hover = option.state & QStyle.State_MouseOver
        if selected:
            p.setPen(QColor(t.accent))
            bg = QColor(t.accent)
            bg.setAlphaF(0.16)
            p.setBrush(bg)
        elif hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.card_hover))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)

        status = index.data(ROLE_STATUS)
        color = QColor(STATUS_COLOR[status])
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(r.left() + 12, r.center().y() - 4, 9, 9)

        font = QFont(option.font)
        font.setPointSizeF(10)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(t.text))
        text_left = r.left() + 30
        pill_w = 54
        name_rect = QRect(text_left, r.top() + 6, r.width() - 30 - pill_w - 14, 20)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideMiddle, name_rect.width()))
        font.setBold(False)
        font.setPointSizeF(8.5)
        p.setFont(font)
        p.setPen(QColor(t.muted))
        sub_rect = QRect(text_left, r.top() + 25, name_rect.width(), 16)
        p.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(index.data(ROLE_SUB) or "", Qt.ElideRight, sub_rect.width()))

        pill = QRect(r.right() - pill_w - 8, r.center().y() - 10, pill_w, 20)
        bg = QColor(color)
        bg.setAlphaF(0.18)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(color)
        p.drawText(pill, Qt.AlignCenter, STATUS_TEXT[status])
        p.restore()


class CasePanel(QWidget):
    caseActivated = Signal(str)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.setObjectName("CasePanel")
        self.project: Project | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(8)
        title = QLabel("病例")
        title.setObjectName("PanelTitle")
        self.count_label = QLabel("")
        self.count_label.setProperty("muted", True)
        lay.addLayout(row(title, None, self.count_label))
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索病例…")
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        self.filter.addItem("全部", None)
        for st in STATUS_ORDER:
            self.filter.addItem(STATUS_TEXT[st], st)
        lay.addLayout(row(self.search, self.filter, stretch_last=False))
        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.delegate = CaseDelegate(theme, self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        lay.addWidget(self.list, 1)
        self.legend = QLabel()
        self.legend.setObjectName("Hint")
        self.legend.setWordWrap(True)
        lay.addWidget(self.legend)

        self.search.textChanged.connect(self._apply_filter)
        self.filter.currentIndexChanged.connect(self._apply_filter)
        self.list.itemActivated.connect(lambda it: self.caseActivated.emit(it.data(ROLE_CASE)))
        self.list.itemClicked.connect(lambda it: self.caseActivated.emit(it.data(ROLE_CASE)))

    def set_theme(self, theme: Theme) -> None:
        self.delegate.theme = theme
        self.list.viewport().update()

    def set_project(self, project: Project | None) -> None:
        self.project = project
        self.list.clear()
        if project:
            for c in project.cases:
                it = QListWidgetItem(c.case_id)
                it.setData(ROLE_CASE, c.case_id)
                n = len(c.images)
                kind = "二维图像" if c.kind == "2d" else (f"{n} 个序列" if n > 1 else "单序列")
                seqs = " · ".join(c.sequence_names) if n > 1 else c.images[0].name
                it.setData(ROLE_SUB, f"{kind}  {seqs}")
                it.setToolTip("\n".join(str(p) for p in c.images))
                self.list.addItem(it)
        self.refresh_status()

    def refresh_status(self) -> None:
        p = self.project
        if not p:
            self.count_label.setText("")
            self.progress.setValue(0)
            self.legend.setText("")
            return
        for i in range(self.list.count()):
            it = self.list.item(i)
            case = p.find(it.data(ROLE_CASE))
            it.setData(ROLE_STATUS, p.status(case))
        counts = p.counts()
        total = len(p.cases)
        self.count_label.setText(f"已完成 {counts['done']} / {total}")
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(counts["done"])
        cells = [f"<td><span style='color:{STATUS_COLOR[s]}'>●</span> {STATUS_TEXT[s]} <b>{counts[s]}</b></td>"
                 for s in STATUS_ORDER]
        self.legend.setText(f"<table width='100%' cellspacing=0 cellpadding=1><tr>{cells[0]}{cells[1]}</tr>"
                            f"<tr>{cells[2]}{cells[3]}</tr></table>")
        self._apply_filter()
        self.list.viewport().update()

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        st = self.filter.currentData()
        for i in range(self.list.count()):
            it = self.list.item(i)
            ok = (not text or text in it.data(ROLE_CASE).lower()) and (st is None or it.data(ROLE_STATUS) == st)
            it.setHidden(not ok)

    def select(self, case_id: str) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_CASE) == case_id:
                self.list.blockSignals(True)
                self.list.setCurrentItem(it)
                self.list.blockSignals(False)
                self.list.scrollToItem(it)
                return

    def neighbor(self, case_id: str | None, step: int) -> str | None:
        """当前筛选下的上/下一个病例。"""
        ids = [self.list.item(i).data(ROLE_CASE) for i in range(self.list.count()) if not self.list.item(i).isHidden()]
        if not ids:
            return None
        if case_id not in ids:
            return ids[0]
        j = ids.index(case_id) + step
        return ids[j] if 0 <= j < len(ids) else None
