"""后台推理线程，避免界面卡顿。"""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..inference.nnunet import NnUNetRunner, PredictorConfig


class InferenceWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    caseFinished = Signal(str, str, str)  # case_id, 预测文件路径（失败为空）, 错误信息
    finished = Signal()

    def __init__(self, runner: NnUNetRunner, cfg: PredictorConfig, jobs: list[tuple[str, list[Path]]], post=None):
        super().__init__()
        self.runner, self.cfg, self.jobs, self.post = runner, cfg, jobs, post
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        total = len(self.jobs)
        for i, (case_id, files) in enumerate(self.jobs):
            if self._cancel:
                self.log.emit("已取消")
                break
            prefix = f"[{i + 1}/{total}] {case_id}：" if total > 1 else ""
            self.progress.emit(i, total)
            try:
                out = self.runner.predict(self.cfg, files, log=lambda m: self.log.emit(prefix + m))
                if self.post is not None:  # 批量模式：在工作线程中直接保存
                    self.post(case_id, out)
                self.caseFinished.emit(case_id, str(out), "")
            except Exception as e:  # noqa: BLE001 - 把任何推理错误反馈给界面
                traceback.print_exc()
                self.caseFinished.emit(case_id, "", f"{type(e).__name__}: {e}")
        self.progress.emit(total, total)
        self.finished.emit()


def start_worker(worker: InferenceWorker, parent: QObject) -> QThread:
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
