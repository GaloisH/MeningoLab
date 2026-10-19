"""对话框：标签编辑、通道匹配、快捷键说明。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..core.labels import PALETTE, Label, LabelSet
from .widgets import hint, row


class LabelEditorDialog(QDialog):
    def __init__(self, labelset: LabelSet, used_values: set[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑标签")
        self.resize(460, 420)
        self.used = used_values
        lay = QVBoxLayout(self)
        lay.addWidget(hint("标签值即保存到掩膜中的整数（与 nnU-Net dataset.json 中的 labels 对应）。"
                           "修改会保存到当前数据目录的 .mlab/labels.json。"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["值", "名称", "颜色"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.table, 1)
        add = QPushButton("添加标签")
        rm = QPushButton("删除所选")
        rm.setProperty("danger", True)
        lay.addLayout(row(add, rm, None))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        lay.addWidget(buttons)
        add.clicked.connect(self._add)
        rm.clicked.connect(self._remove)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        for lab in labelset:
            self._append(lab.value, lab.name, lab.color, lab.visible)

    def _append(self, value: int, name: str, color, visible: bool = True) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        sb = QSpinBox()
        sb.setRange(1, 255)
        sb.setValue(value)
        self.table.setCellWidget(r, 0, sb)
        item = QTableWidgetItem(name)
        item.setData(Qt.UserRole, visible)
        self.table.setItem(r, 1, item)
        btn = QPushButton()
        btn.setFixedWidth(64)
        self._set_btn_color(btn, color)
        btn.clicked.connect(lambda _=False, b=btn: self._pick(b))
        self.table.setCellWidget(r, 2, btn)

    @staticmethod
    def _set_btn_color(btn: QPushButton, color) -> None:
        btn.setProperty("rgb", tuple(color))
        btn.setStyleSheet(f"background: rgb{tuple(color)}; border-radius: 4px; min-height: 18px;")

    def _pick(self, btn: QPushButton) -> None:
        c = QColorDialog.getColor(QColor(*btn.property("rgb")), self, "选择标签颜色")
        if c.isValid():
            self._set_btn_color(btn, (c.red(), c.green(), c.blue()))

    def _values(self) -> list[int]:
        return [self.table.cellWidget(r, 0).value() for r in range(self.table.rowCount())]

    def _add(self) -> None:
        used = set(self._values())
        v = next(i for i in range(1, 256) if i not in used)
        self._append(v, f"病灶 {v}", PALETTE[(v - 1) % len(PALETTE)])
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 1))

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            v = self.table.cellWidget(r, 0).value()
            if v in self.used and QMessageBox.question(
                    self, "确认删除", f"当前病例中已有标签值 {v} 的标注，删除定义后这些体素仍会保留（显示为未定义）。继续？"
            ) != QMessageBox.Yes:
                continue
            self.table.removeRow(r)

    def _accept(self) -> None:
        vals = self._values()
        if len(vals) != len(set(vals)):
            QMessageBox.warning(self, "标签值重复", "每个标签的值必须唯一。")
            return
        self.accept()

    def result_labelset(self) -> LabelSet:
        labels = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            labels.append(Label(self.table.cellWidget(r, 0).value(), item.text().strip() or "未命名",
                                tuple(self.table.cellWidget(r, 2).property("rgb")), bool(item.data(Qt.UserRole))))
        return LabelSet(labels)


class ChannelMappingDialog(QDialog):
    """当序列文件无法自动对应到模型输入通道时，让用户手动选择。"""

    def __init__(self, channel_names: dict[int, str], images: list[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle("指定模型输入通道")
        self.images = images
        lay = QVBoxLayout(self)
        lay.addWidget(hint("无法根据文件名自动匹配模型输入通道，请为每个通道选择对应的序列："))
        form = QFormLayout()
        self.combos = []
        for ch in sorted(channel_names):
            cb = QComboBox()
            for p in images:
                cb.addItem(p.name, str(p))
            cb.setCurrentIndex(min(ch, len(images) - 1))
            form.addRow(f"通道 {ch} · {channel_names[ch]}", cb)
            self.combos.append(cb)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("开始推理")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def files(self) -> list[Path]:
        return [Path(cb.currentData()) for cb in self.combos]


SHORTCUTS = [
    ("文件", [("Ctrl+O", "打开数据目录"), ("Ctrl+S", "保存当前标注"), ("Ctrl+Enter", "保存并标记完成"),
              ("Alt+← / Alt+→", "上一例 / 下一例")]),
    ("工具", [("N", "浏览定位"), ("B", "画笔（Shift+拖动 = 擦除）"), ("E", "橡皮擦"), ("P", "多边形 / 套索"),
              ("G", "区域生长"), ("[ / ]", "减小 / 增大笔刷"), ("1–9", "切换标签"), ("Ctrl+I", "层间插值")]),
    ("编辑", [("Ctrl+Z", "撤销"), ("Ctrl+Y / Ctrl+Shift+Z", "重做")]),
    ("视图", [("滚轮 / ↑↓", "翻层（PageUp/PageDown 跳 5 层）"), ("Ctrl+滚轮", "缩放"),
              ("中键拖动 / 空格+左键", "平移"), ("右键拖动", "调节窗宽窗位"), ("H", "显示 / 隐藏标签"),
              ("F", "单视图 / 三视图切换"), ("R", "重置缩放")]),
    ("多边形", [("单击", "添加顶点"), ("双击 / 右键 / 回车", "闭合并填充"), ("按住拖动", "自由套索"),
               ("Backspace", "撤回顶点"), ("Esc", "取消")]),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键")
        self.resize(460, 560)
        lay = QVBoxLayout(self)
        html = ["<table cellspacing=0 cellpadding=4 width='100%'>"]
        for group, items in SHORTCUTS:
            html.append(f"<tr><td colspan=2 style='padding-top:10px'><b>{group}</b></td></tr>")
            for key, desc in items:
                html.append(f"<tr><td width='42%'><code>{key}</code></td><td>{desc}</td></tr>")
        html.append("</table>")
        lab = QLabel("".join(html))
        lab.setTextFormat(Qt.RichText)
        lab.setAlignment(Qt.AlignTop)
        lay.addWidget(lab, 1)
        btn = QDialogButtonBox(QDialogButtonBox.Close)
        btn.button(QDialogButtonBox.Close).setText("关闭")
        btn.rejected.connect(self.reject)
        lay.addWidget(btn)
