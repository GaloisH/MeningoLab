"""AI 预标注面板（nnU-Net v2）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QToolButton, QWidget)

from ..inference.nnunet import (ModelInfo, PredictorConfig, available_devices, find_model_folders, inspect_model,
                                nnunet_status)
from .widgets import Card, hint, row

APPLY_REPLACE, APPLY_FILL = "replace", "fill"


class ModelPanel(Card):
    runCurrent = Signal()
    runBatch = Signal()
    cancelRequested = Signal()
    modelsChanged = Signal(list)

    def __init__(self, icon_fn, parent=None):
        super().__init__("AI 预标注 · nnU-Net", parent)
        self._icon_fn = icon_fn
        self.infos: list[ModelInfo] = []
        ok, msg = nnunet_status()
        self.available = ok
        self.status = QLabel(("● " if ok else "○ ") + msg)
        self.status.setStyleSheet(f"color: {'#3fb97c' if ok else '#f0a630'};")
        self.status.setWordWrap(True)
        self.add(self.status)

        self.model = QComboBox()
        self.model.setPlaceholderText("尚未添加模型")
        self.add_btn = QToolButton()
        self.add_btn.setToolTip("添加 nnU-Net 训练结果目录")
        self.del_btn = QToolButton()
        self.del_btn.setToolTip("从列表移除所选模型")
        for b in (self.add_btn, self.del_btn):
            b.setAutoRaise(True)
        self.add(row(self.model, self.add_btn, self.del_btn))
        self.info = hint("")
        self.info.setTextFormat(Qt.RichText)
        self.add(self.info)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.device = QComboBox()
        self._devices_loaded = False
        self.device.addItem("自动选择", "auto")
        self.folds = QComboBox()
        self.ckpt = QComboBox()
        self.tta = QCheckBox("镜像测试增强 (TTA，更准但更慢)")
        self.mode = QComboBox()
        self.mode.addItem("仅填充空白区域（保留已有标注）", APPLY_FILL)
        self.mode.addItem("覆盖当前全部标注", APPLY_REPLACE)
        for r, (name, w) in enumerate((("设备", self.device), ("折 (fold)", self.folds),
                                       ("权重", self.ckpt), ("应用方式", self.mode))):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(w, r, 1)
        grid.setColumnStretch(1, 1)
        holder = QWidget()
        holder.setLayout(grid)
        self.add(holder)
        self.add(self.tta)

        self.run_btn = QPushButton("预标注当前病例")
        self.run_btn.setProperty("primary", True)
        self.batch_btn = QPushButton("批量预标注")
        self.batch_btn.setToolTip("对所有“未标注”病例运行模型并保存结果")
        self.add(row(self.run_btn, self.batch_btn, stretch_last=False))
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setVisible(False)
        self.log = hint("")
        self.add(self.progress)
        self.add(row(self.log, self.cancel_btn, stretch_last=False))

        self.add_btn.clicked.connect(self._add_model)
        self.del_btn.clicked.connect(self._remove_model)
        self.model.currentIndexChanged.connect(self._on_model)
        self.run_btn.clicked.connect(self.runCurrent)
        self.batch_btn.clicked.connect(self.runBatch)
        self.cancel_btn.clicked.connect(self.cancelRequested)
        self.refresh_icons()
        self._on_model()

    def refresh_icons(self) -> None:
        self.add_btn.setIcon(self._icon_fn("plus", 16))
        self.del_btn.setIcon(self._icon_fn("trash", 16))

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if not self._devices_loaded and self.available:
            self._devices_loaded = True
            QTimer.singleShot(300, self._load_devices)  # 窗口显示后再导入 torch，加快启动

    def _load_devices(self) -> None:
        current = self.device.currentData()
        self.device.clear()
        for key, name in available_devices():
            self.device.addItem(name, key)
        self.device.setCurrentIndex(max(self.device.findData(current), 0))

    # ------------------------------------------------------------------ 模型列表
    def set_models(self, folders: list[str]) -> None:
        self.infos = []
        for f in folders:
            try:
                self.infos.append(inspect_model(f))
            except (OSError, ValueError) as e:  # 目录被移动或损坏
                self.log.setText(f"无法读取模型 {f}：{e}")
        self.model.blockSignals(True)
        self.model.clear()
        for info in self.infos:
            self.model.addItem(info.display_name, str(info.folder))
        if self.infos:  # 有占位文字时 QComboBox 不会自动选中第一项
            self.model.setCurrentIndex(0)
        self.model.blockSignals(False)
        self._on_model()

    def _add_model(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择 nnU-Net 训练结果目录（含 dataset.json / plans.json）")
        if not d:
            return
        found = find_model_folders(d)
        if not found:
            QMessageBox.warning(self, "未找到模型",
                                "该目录下没有找到 nnU-Net 训练结果。\n请选择形如 "
                                "nnUNet_results/DatasetXXX_Name/nnUNetTrainer__nnUNetPlans__3d_fullres 的目录。")
            return
        folders = [str(i.folder) for i in self.infos]
        for f in found:
            if str(f) not in folders:
                folders.append(str(f))
        self.set_models(folders)
        self.model.setCurrentIndex(self.model.findData(str(found[0])))
        self.modelsChanged.emit(folders)

    def _remove_model(self) -> None:
        i = self.model.currentIndex()
        if i < 0:
            return
        folders = [str(x.folder) for j, x in enumerate(self.infos) if j != i]
        self.set_models(folders)
        self.modelsChanged.emit(folders)

    def current_info(self) -> ModelInfo | None:
        i = self.model.currentIndex()
        return self.infos[i] if 0 <= i < len(self.infos) else None

    def _on_model(self, *_):
        info = self.current_info()
        self.folds.clear()
        self.ckpt.clear()
        if info is None:
            self.info.setText("添加训练好的 nnU-Net 模型后，可一键生成预标注，再由医生修改确认。")
        else:
            chans = "、".join(f"{k}:{v}" for k, v in sorted(info.channel_names.items()))
            labels = "、".join(f"{k}:{v}" for k, v in sorted(info.labels.items()))
            self.info.setText(f"<b>输入通道</b> {chans}<br><b>输出标签</b> {labels or '–'}<br>"
                              f"<span>{Path(info.folder).name.replace('_', '_&#8203;')}</span>")
            for f in info.folds:
                self.folds.addItem(f"fold {f}", (f,))
            if len(info.folds) > 1:
                self.folds.addItem(f"全部 {len(info.folds)} 折集成", tuple(info.folds))
            for c in info.checkpoints:
                self.ckpt.addItem(c, c)
            self.info.setToolTip(str(info.folder))
        self.set_busy(False)

    def config(self) -> PredictorConfig | None:
        info = self.current_info()
        if info is None or self.folds.currentData() is None:
            return None
        return PredictorConfig(
            folder=str(info.folder),
            device=self.device.currentData() or "auto",
            folds=tuple(self.folds.currentData()),
            checkpoint=self.ckpt.currentData() or "checkpoint_final.pth",
            use_mirroring=self.tta.isChecked(),
        )

    @property
    def apply_mode(self) -> str:
        return self.mode.currentData()

    def set_busy(self, busy: bool, text: str = "") -> None:
        ready = self.available and self.current_info() is not None and bool(self.folds.count())
        self.run_btn.setEnabled(ready and not busy)
        self.batch_btn.setEnabled(ready and not busy)
        self.model.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        if text or not busy:
            self.log.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
