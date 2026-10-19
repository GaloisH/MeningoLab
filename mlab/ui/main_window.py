"""主窗口：组装各面板，负责病例切换、保存与模型推理调度。"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QScrollArea, QSizePolicy, QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import APP_TITLE, __version__
from ..core.project import STATUS_COLOR, STATUS_DONE, STATUS_PRE, STATUS_TEXT, STATUS_TODO, STATUS_WIP, Project
from ..core.segmentation import LabelMap
from ..core.volume import load_volumes
from ..inference.nnunet import NnUNetRunner, match_channels
from . import icons
from .case_panel import CasePanel
from .controller import AnnotationController
from .dialogs import ChannelMappingDialog, LabelEditorDialog, ShortcutsDialog
from .model_panel import APPLY_REPLACE, ModelPanel
from .session import TOOL_BRUSH, TOOL_ERASER, TOOL_GROW, TOOL_NAVIGATE, TOOL_POLYGON, TOOL_TEXT, Session
from .side_panels import DisplayPanel, LabelPanel, ToolOptionsPanel
from .theme import THEMES, apply_theme
from .viewer import Viewer
from .workers import InferenceWorker, start_worker

TOOL_ICONS = {TOOL_NAVIGATE: "navigate", TOOL_BRUSH: "brush", TOOL_ERASER: "eraser", TOOL_POLYGON: "polygon",
              TOOL_GROW: "wand"}


def save_prediction(project: Project, case, pred_path: str) -> None:
    """把模型输出对齐到病例参考序列并保存到 labels/。"""
    ref = load_volumes(case.images[:1])[0]
    ref.save_label(ref.load_label(pred_path), project.label_path(case))


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("MLab", "MLab")
        self.theme = THEMES.get(self.settings.value("theme", "dark"), THEMES["dark"])
        self.session = Session()
        self.ctrl = AnnotationController(self.session)
        self.project: Project | None = None
        self.runner = NnUNetRunner()
        self._worker: InferenceWorker | None = None
        self._thread = None
        self._icon_targets: list[tuple[object, str, int]] = []

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(icons.app_icon())
        self.resize(1560, 940)
        self._build_ui()
        self._build_actions()
        self._connect()
        self.apply_theme(self.theme.name)
        self.model_panel.set_models(self.settings.value("models", [], type=list) or [])
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        self._update_title()
        self._update_undo()

    # ================================================================== 界面
    def icon(self, name: str, size: int = 20):
        return icons.icon(name, self.theme.text, size)

    def _iconize(self, obj, name: str, size: int = 20):
        obj.setIcon(self.icon(name, size))
        self._icon_targets.append((obj, name, size))
        return obj

    def _build_ui(self) -> None:
        s = self.session
        self.case_panel = CasePanel(self.theme)
        self.case_panel.setMinimumWidth(220)

        # 左侧竖排工具条
        strip = QWidget()
        strip.setObjectName("ToolStrip")
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(4, 8, 4, 8)
        sl.setSpacing(2)
        self.tool_buttons: dict[str, QToolButton] = {}
        for tool in (TOOL_NAVIGATE, TOOL_BRUSH, TOOL_ERASER, TOOL_POLYGON, TOOL_GROW):
            b = QToolButton()
            b.setCheckable(True)
            b.setIconSize(b.iconSize().expandedTo(b.iconSize()) * 1.1)
            name, key = TOOL_TEXT[tool]
            b.setToolTip(f"{name}（{key}）")
            b.clicked.connect(lambda _=False, t=tool: s.set_tool(t))
            self._iconize(b, TOOL_ICONS[tool], 22)
            sl.addWidget(b)
            self.tool_buttons[tool] = b
        sl.addSpacing(10)
        self.interp_strip_btn = self._iconize(QToolButton(), "layers", 22)
        self.interp_strip_btn.setToolTip("层间插值当前标签（Ctrl+I）")
        sl.addWidget(self.interp_strip_btn)
        sl.addStretch(1)

        self.viewer = Viewer(s, self.ctrl, self.icon)
        center = QWidget()
        center.setObjectName("CentralArea")
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(strip)
        cl.addWidget(self.viewer, 1)

        # 右侧面板
        side = QWidget()
        side.setObjectName("SidePanel")
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(10, 10, 10, 10)
        side_l.setSpacing(10)
        self.label_panel = LabelPanel(s, self.theme, self.icon)
        self.tool_panel = ToolOptionsPanel(s, self.ctrl)
        self.display_panel = DisplayPanel(s)
        self.model_panel = ModelPanel(self.icon)
        for w in (self.label_panel, self.tool_panel, self.display_panel, self.model_panel):
            side_l.addWidget(w)
        side_l.addStretch(1)
        for cb in side.findChildren(QComboBox):  # 下拉框按内容计算的最小宽度会撑宽侧边栏
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(320)
        scroll.setObjectName("SidePanel")

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.case_panel)
        split.addWidget(center)
        split.addWidget(scroll)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([270, 960, 340])
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)

        sb = self.statusBar()
        self.hover_label = QLabel("")
        self.saved_label = QLabel("")
        sb.addPermanentWidget(self.hover_label)
        sb.addPermanentWidget(self.saved_label)

    def _build_actions(self) -> None:
        s = self.session
        mk = self._make_action
        self.act_open = mk("打开数据目录…", "folder", QKeySequence.Open, self.choose_project)
        self.act_save = mk("保存", "save", QKeySequence.Save, self.save_current)
        self.act_done = mk("标记完成", "check", "Ctrl+Return", self.mark_done)
        self.act_done.setToolTip("保存并标记为已完成，自动跳到下一例（Ctrl+Enter）")
        self.act_prev = mk("上一例", "prev", "Alt+Left", lambda: self.step_case(-1))
        self.act_next = mk("下一例", "next", "Alt+Right", lambda: self.step_case(1))
        self.act_undo = mk("撤销", "undo", QKeySequence.Undo, self.ctrl.undo)
        self.act_redo = mk("重做", "redo", "Ctrl+Y", self.ctrl.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.ctrl.redo)
        self.act_layout = mk("单视图 / 三视图", "grid", "F", self._toggle_layout)
        self.act_reset = mk("重置缩放", "refresh", "R", self.viewer.reset_views)
        self.act_theme = mk("切换深色 / 浅色主题", "sun", None, self.toggle_theme)
        self.act_keys = mk("快捷键", "keyboard", "F1", lambda: ShortcutsDialog(self).exec())
        self.act_labels = mk("编辑标签…", "edit", None, self.edit_labels)
        self.act_interp = mk("层间插值当前标签", "layers", "Ctrl+I",
                             lambda: self.ctrl.interpolate(self.tool_panel.interp_axis.currentData()))
        self.act_toggle_labels = mk("显示 / 隐藏标签", None, "H",
                                    lambda: s.set_display(show_labels=not s.show_labels))
        self.act_autosave = QAction("切换病例时自动保存", self, checkable=True)
        self.act_autosave.setChecked(self.settings.value("autosave", True, type=bool))
        self.act_autosave.toggled.connect(lambda on: self.settings.setValue("autosave", on))
        self.interp_strip_btn.clicked.connect(self.act_interp.trigger)

        self.tool_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        for tool, (name, key) in TOOL_TEXT.items():
            a = mk(name, TOOL_ICONS[tool], key, lambda _=False, t=tool: s.set_tool(t))
            a.setCheckable(True)
            group.addAction(a)
            self.tool_actions[tool] = a
        QShortcut(QKeySequence("["), self, lambda: s.set_tool_option(brush_size=max(1, s.brush_size - 1)))
        QShortcut(QKeySequence("]"), self, lambda: s.set_tool_option(brush_size=min(60, s.brush_size + 1)))
        for n in range(1, 10):
            QShortcut(QKeySequence(str(n)), self, lambda v=n: s.labelset.get(v) and s.set_active_label(v))

        # 菜单
        mb = self.menuBar()
        m = mb.addMenu("文件")
        for a in (self.act_open, self.act_save, self.act_done):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_autosave)
        m.addSeparator()
        m.addAction("退出", self.close)
        m = mb.addMenu("编辑")
        for a in (self.act_undo, self.act_redo):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_labels)
        m.addAction(self.act_interp)
        m = mb.addMenu("工具")
        for a in self.tool_actions.values():
            m.addAction(a)
        m = mb.addMenu("视图")
        for a in (self.act_layout, self.act_reset, self.act_toggle_labels, self.act_theme):
            m.addAction(a)
        m = mb.addMenu("帮助")
        m.addAction(self.act_keys)
        m.addAction("关于 MLab", self._about)

        # 顶部工具栏
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addAction(self.act_done)
        tb.addSeparator()
        tb.addAction(self.act_prev)
        self.case_title = QLabel("未打开病例")
        self.case_title.setTextFormat(Qt.RichText)
        self.case_title.setMinimumWidth(240)
        self.case_title.setAlignment(Qt.AlignCenter)
        tb.addWidget(self.case_title)
        tb.addAction(self.act_next)
        tb.addSeparator()
        for a in (self.act_undo, self.act_redo):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.addSeparator()
        for a in (self.act_layout, self.act_reset):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        for a in (self.act_theme, self.act_keys):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        for a in (self.act_prev, self.act_next):
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._sync_tool(s.tool)

    def _make_action(self, text, icon_name, shortcut, slot) -> QAction:
        a = QAction(text, self)
        if icon_name:
            self._iconize(a, icon_name)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(f"{text}（{QKeySequence(shortcut).toString(QKeySequence.NativeText)}）")
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _connect(self) -> None:
        s = self.session
        self.case_panel.caseActivated.connect(self.open_case)
        s.toolChanged.connect(self._sync_tool)
        s.labelsEdited.connect(lambda _: self._on_edit())
        s.modifiedChanged.connect(lambda _: self._update_title())
        s.caseLoaded.connect(self._update_undo)
        self.viewer.hovered.connect(self._on_hover)
        self.ctrl.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.label_panel.editRequested.connect(self.edit_labels)
        self.model_panel.modelsChanged.connect(lambda lst: self.settings.setValue("models", lst))
        self.model_panel.runCurrent.connect(self.predict_current)
        self.model_panel.runBatch.connect(self.predict_batch)
        self.model_panel.cancelRequested.connect(self._cancel_inference)

    # ================================================================== 主题
    def apply_theme(self, name: str) -> None:
        self.theme = THEMES[name]
        apply_theme(QApplication.instance(), self.theme)
        for obj, icon_name, size in self._icon_targets:
            obj.setIcon(self.icon(icon_name, size))
        self.act_theme.setIcon(self.icon("sun" if name == "dark" else "moon"))
        self.case_panel.set_theme(self.theme)
        self.label_panel.set_theme(self.theme)
        self.label_panel.refresh_icons()
        self.model_panel.refresh_icons()
        self.viewer.refresh_icons()
        self.settings.setValue("theme", name)
        self._update_title()

    def toggle_theme(self) -> None:
        self.apply_theme("light" if self.theme.name == "dark" else "dark")

    # ================================================================== 项目 / 病例
    def choose_project(self) -> None:
        start = self.settings.value("last_root", str(Path.home()))
        d = QFileDialog.getExistingDirectory(self, "选择数据根目录", start)
        if d:
            self.open_project(d)

    def open_project(self, root: str | Path) -> None:
        if not self.maybe_save():
            return
        try:
            project = Project(root)
        except OSError as e:
            QMessageBox.critical(self, "无法打开目录", str(e))
            return
        self.project = project
        self.session.project = project
        self.session.set_labelset(project.load_labelset())
        self.session.clear()
        self.case_panel.set_project(project)
        self.settings.setValue("last_root", str(project.root))
        if not project.cases:
            QMessageBox.information(self, "没有找到病例",
                                    "该目录中没有找到 .nii / .nii.gz / .png / .jpg 影像。\n"
                                    "支持：每个病例一个子文件夹（可含多个序列）、nnU-Net 命名 (case_0000.nii.gz)、"
                                    "或每个文件一个病例。")
        else:
            self.statusBar().showMessage(f"已打开 {project.root}，共 {len(project.cases)} 个病例", 5000)
            last = self.settings.value(self._last_case_key(), "")
            first = project.find(last) or next((c for c in project.cases if project.status(c) != STATUS_DONE),
                                               project.cases[0])
            self.open_case(first.case_id)
        self._update_title()

    def open_case(self, case_id: str) -> None:
        if not self.project:
            return
        cur = self.session.case
        if cur and cur.case_id == case_id:
            return
        if not self.maybe_save():
            if cur:
                self.case_panel.select(cur.case_id)
            return
        case = self.project.find(case_id)
        if case is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            vols = load_volumes(case.images)
            path = self.project.label_path(case)
            data = vols[0].load_label(path) if path.exists() else None
        except Exception as e:  # noqa: BLE001 - 损坏或格式不支持的文件
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "读取失败", f"无法读取病例 {case_id}：\n{e}")
            return
        QApplication.restoreOverrideCursor()
        if data is not None:  # 文件中出现但未定义的标签值，自动补充定义
            for v in np.unique(data):
                if v and not self.session.labelset.get(int(v)):
                    self.session.labelset.ensure(int(v))
            self.session.set_labelset(self.session.labelset)
        self.session.load(case, vols, LabelMap(vols[0].shape, data))
        self.case_panel.select(case_id)
        self.settings.setValue(self._last_case_key(), case_id)
        self._update_title()
        if len(vols) > 1 and any(v.shape != vols[0].shape for v in vols):
            self.statusBar().showMessage("部分序列与参考序列网格不同，已自动重采样对齐", 6000)

    def _last_case_key(self) -> str:
        # 路径中的斜杠/反斜杠会被 QSettings 当作分组分隔符，故使用哈希
        return "last_case/" + hashlib.md5(str(self.project.root.resolve()).encode("utf-8")).hexdigest()

    def step_case(self, step: int) -> None:
        cid = self.case_panel.neighbor(self.session.case.case_id if self.session.case else None, step)
        if cid:
            self.open_case(cid)
        else:
            self.statusBar().showMessage("已经是第一例" if step < 0 else "已经是最后一例", 3000)

    def maybe_save(self) -> bool:
        lm = self.session.labelmap
        if not lm or not lm.modified:
            return True
        if self.act_autosave.isChecked():
            return self.save_current()
        r = QMessageBox.question(self, "未保存的修改", f"病例 {self.session.case.case_id} 有未保存的标注，是否保存？",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save_current()
        return r == QMessageBox.Discard

    def save_current(self) -> bool:
        s = self.session
        if not (self.project and s.has_data):
            return False
        try:
            s.volumes[0].save_label(s.labelmap.data, self.project.label_path(s.case))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))
            return False
        if self.project.status(s.case) in (STATUS_TODO, STATUS_PRE) and s.labelmap.data.any():
            self.project.set_status(s.case, STATUS_WIP)
        s.mark_saved()
        self.case_panel.refresh_status()
        self._update_title()
        self.statusBar().showMessage(f"已保存 → {self.project.label_path(s.case)}", 4000)
        return True

    def mark_done(self) -> None:
        s = self.session
        if not s.has_data:
            return
        if not s.labelmap.data.any() and QMessageBox.question(
                self, "空标注", "当前病例没有任何标注（阴性病例？）。仍标记为已完成吗？") != QMessageBox.Yes:
            return
        if not self.save_current():
            return
        self.project.set_status(s.case, STATUS_DONE)
        self.case_panel.refresh_status()
        self._update_title()
        nxt = next((c for c in self.project.cases if self.project.status(c) != STATUS_DONE), None)
        if nxt:
            self.open_case(nxt.case_id)
        else:
            QMessageBox.information(self, "全部完成", "所有病例都已标注完成 🎉")

    # ================================================================== 标签
    def edit_labels(self) -> None:
        s = self.session
        used = set(np.unique(s.labelmap.data).tolist()) - {0} if s.has_data else set()
        dlg = LabelEditorDialog(s.labelset, used, self)
        if dlg.exec():
            s.set_labelset(dlg.result_labelset())

    # ================================================================== 推理
    def _model_files(self, case, info, interactive: bool):
        """返回送入模型的文件列表；模型与病例类型（二维/三维）不匹配时返回 None。"""
        if (case.kind == "2d") != info.is_2d_natural:
            if interactive:
                QMessageBox.warning(self, "模型不匹配",
                                    f"所选模型输入为{'二维图片' if info.is_2d_natural else '三维 NIfTI'}，"
                                    f"而当前病例是{'二维图片' if case.kind == '2d' else '三维影像'}。")
            return None
        if case.kind == "2d":
            return [case.images[0]]
        files = match_channels(case.images, info.channel_names)
        if files is None and interactive:
            dlg = ChannelMappingDialog(info.channel_names, case.images, self)
            files = dlg.files() if dlg.exec() else None
        return files

    def _register_model_labels(self, info) -> None:
        ls = self.session.labelset
        changed = False
        for v, name in info.labels.items():
            if not ls.get(v):
                ls.add(name, v)
                changed = True
        if changed:
            self.session.set_labelset(ls)

    def predict_current(self) -> None:
        s = self.session
        cfg, info = self.model_panel.config(), self.model_panel.current_info()
        if not s.has_data:
            QMessageBox.information(self, "预标注", "请先打开一个病例")
            return
        if cfg is None or self._thread is not None:
            return
        files = self._model_files(s.case, info, interactive=True)
        if not files:
            return
        self._register_model_labels(info)
        self._start_inference(cfg, [(s.case.case_id, files)], post=None)

    def predict_batch(self) -> None:
        cfg, info = self.model_panel.config(), self.model_panel.current_info()
        if not self.project or cfg is None or self._thread is not None:
            return
        todo = [c for c in self.project.cases
                if self.project.status(c) == STATUS_TODO and not self.project.label_path(c).exists()]
        if self.session.case in todo and self.session.labelmap.modified:
            todo.remove(self.session.case)
        if not todo:
            QMessageBox.information(self, "批量预标注", "没有需要预标注的病例（仅处理“未标注”且尚无标注文件的病例）。")
            return
        jobs, skipped = [], []
        for c in todo:
            files = self._model_files(c, info, interactive=False)
            (jobs.append((c.case_id, files)) if files else skipped.append(c.case_id))
        msg = f"将对 {len(jobs)} 个未标注病例运行模型并保存预标注结果。"
        if skipped:
            msg += (f"\n\n以下 {len(skipped)} 个病例与模型类型不匹配或无法自动匹配输入通道，将跳过：\n"
                    + "、".join(skipped[:10]))
        if not jobs or QMessageBox.question(self, "批量预标注", msg + "\n\n继续？") != QMessageBox.Yes:
            return
        self._register_model_labels(info)
        project = self.project
        cases = {c.case_id: c for c in todo}
        self._start_inference(cfg, jobs, post=lambda cid, out: save_prediction(project, cases[cid], str(out)))

    def _start_inference(self, cfg, jobs, post) -> None:
        self._batch = post is not None
        self._errors: list[str] = []
        worker = InferenceWorker(self.runner, cfg, jobs, post)
        worker.log.connect(lambda m: self.model_panel.set_busy(True, m))
        worker.progress.connect(self.model_panel.set_progress if len(jobs) > 1 else lambda *_: None)
        worker.caseFinished.connect(self._on_case_predicted)
        worker.finished.connect(self._on_inference_done)
        self._worker = worker
        self.model_panel.set_busy(True, "准备中 …")
        self._thread = start_worker(worker, self)

    def _cancel_inference(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.model_panel.set_busy(True, "正在取消（当前病例完成后停止）…")

    def _on_case_predicted(self, case_id: str, path: str, err: str) -> None:
        if err:
            self._errors.append(f"{case_id}: {err}")
            return
        try:
            if self._batch:
                case = self.project.find(case_id)
                self.project.set_status(case, STATUS_PRE, model=Path(self.model_panel.config().folder).name)
                self.case_panel.refresh_status()
                s = self.session
                if s.case and s.case.case_id == case_id and not s.labelmap.modified:
                    s.labelmap.replace(s.volumes[0].load_label(self.project.label_path(case)))
                    s.notify_edit(-1)
                    s.mark_saved()
            else:
                self._apply_prediction(case_id, path)
        finally:
            shutil.rmtree(Path(path).parent, ignore_errors=True)

    def _apply_prediction(self, case_id: str, path: str) -> None:
        s = self.session
        if not s.case or s.case.case_id != case_id:
            self.statusBar().showMessage("推理完成时已切换到其他病例，结果已丢弃", 6000)
            return
        pred = s.volumes[0].load_label(path)
        if self.model_panel.apply_mode == APPLY_REPLACE:
            new = pred
        else:
            new = s.labelmap.data.copy()
            m = (new == 0) & (pred > 0)
            new[m] = pred[m]
        if s.labelmap.replace(new):
            s.notify_edit(-1)
        if self.project.status(s.case) == STATUS_TODO:
            self.project.set_status(s.case, STATUS_PRE, model=Path(self.model_panel.config().folder).name)
            self.case_panel.refresh_status()
        n = int((pred > 0).sum())
        self.statusBar().showMessage(f"预标注完成：模型输出 {n} 个病灶体素（可 Ctrl+Z 撤销）", 8000)

    def _on_inference_done(self) -> None:
        self._thread, self._worker = None, None
        text = "完成" if not self._errors else f"完成，{len(self._errors)} 个失败"
        self.model_panel.set_busy(False, text)
        self._update_title()
        if self._errors:
            QMessageBox.warning(self, "推理出错", "\n\n".join(self._errors[:5]))

    # ================================================================== 状态显示
    def _sync_tool(self, tool: str) -> None:
        for t, b in self.tool_buttons.items():
            b.setChecked(t == tool)
        if hasattr(self, "tool_actions"):
            self.tool_actions[tool].setChecked(True)

    def _toggle_layout(self) -> None:
        if self.session.has_data:
            self.viewer.toggle_single(self.session.active_axis if self.viewer.single is None else self.viewer.single)

    def _on_edit(self) -> None:
        self._update_undo()  # 病例状态在保存时才更新，避免未保存就改变列表状态

    def _update_undo(self) -> None:
        lm = self.session.labelmap
        self.act_undo.setEnabled(bool(lm and lm.can_undo()))
        self.act_redo.setEnabled(bool(lm and lm.can_redo()))

    def _update_title(self) -> None:
        s = self.session
        modified = bool(s.labelmap and s.labelmap.modified)
        if s.case and self.project:
            st = self.project.status(s.case)
            idx = self.project.cases.index(s.case) + 1
            self.case_title.setText(
                f"<b>{s.case.case_id}</b>&nbsp;&nbsp;<span style='color:{STATUS_COLOR[st]}'>● {STATUS_TEXT[st]}</span>"
                f"&nbsp;&nbsp;<span style='color:{self.theme.muted}'>{idx}/{len(self.project.cases)}</span>")
            self.setWindowTitle(f"{APP_TITLE} — {s.case.case_id}{' *' if modified else ''}")
        else:
            self.case_title.setText(f"<span style='color:{self.theme.muted}'>未打开病例</span>")
            self.setWindowTitle(APP_TITLE)
        self.saved_label.setText("● 未保存" if modified else ("✓ 已保存" if s.case else ""))
        self.saved_label.setStyleSheet(f"color: {'#f0a630' if modified else '#3fb97c'};")
        has = s.has_data
        for a in (self.act_save, self.act_done, self.act_interp):
            a.setEnabled(has)
        self.act_prev.setEnabled(bool(self.project))
        self.act_next.setEnabled(bool(self.project))

    def _on_hover(self, voxel) -> None:
        s = self.session
        if voxel is None or not s.has_data:
            self.hover_label.setText("")
            return
        val = s.volume.data[voxel]
        lab = int(s.labelmap.data[voxel])
        lab_txt = s.labelset.name_of(lab) if lab else "—"
        if s.is_2d:
            x, y, _ = voxel
            h = s.shape[1]
            w = s.shape[0]
            pos = f"像素 ({w - 1 - x}, {h - 1 - y})"
        else:
            pos = f"体素 ({voxel[0]}, {voxel[1]}, {voxel[2]})"
        self.hover_label.setText(f"{pos}   强度 {val:.1f}   标签 {lab_txt}")

    def _about(self) -> None:
        QMessageBox.about(self, "关于 MLab",
                          f"<h3>MLab {__version__}</h3><p>脑膜炎病灶标注工具</p>"
                          "<p>支持 NIfTI 三维 MRI 与二维图片标注、nnU-Net v2 预标注。</p>")

    # ================================================================== 关闭
    def closeEvent(self, ev) -> None:
        if not self.maybe_save():
            ev.ignore()
            return
        if self._worker:
            self._worker.cancel()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self.settings.setValue("geometry", self.saveGeometry())
        ev.accept()
