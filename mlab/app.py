"""程序入口：``python -m mlab [数据目录]``。"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    from . import runtime

    if "--self-test" in argv:
        from .selftest import run

        return run(argv)
    if runtime.setup_frozen_logging():
        from datetime import datetime

        from . import __version__

        print(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} MLab {__version__} {runtime.edition()} 启动 =====")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui import icons
    from .ui.main_window import MainWindow
    from .ui.theme import ui_font

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setWindowIcon(icons.app_icon())
    win = MainWindow()
    win.show()
    if len(argv) > 1 and Path(argv[1]).is_dir():
        win.open_project(argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
