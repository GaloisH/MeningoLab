"""运行环境信息：区分源码运行与打包后的安装版（PyInstaller）。"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from . import APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """可执行文件所在目录；源码运行时为仓库根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def build_info() -> dict:
    """打包时写入的版本信息（edition: base / ai / ai-cpu / ai-gpu，ai 为 macOS 版）；源码运行时为空字典。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return {}
    try:
        return json.loads((Path(base) / "build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def edition() -> str:
    return build_info().get("edition", "")


def edition_label() -> str:
    return {"base": "基础版", "ai": "AI 版", "ai-cpu": "AI 版（CPU）", "ai-gpu": "AI 版（GPU）"}.get(edition(), "")


def bundled_model_root() -> Path | None:
    """随安装包分发的模型目录（与可执行文件同级的 ``models/``；macOS 为 ``.app/Contents/Resources/models``）。"""
    if not is_frozen():
        return None
    exe_dir = app_dir()
    for d in (exe_dir / "models", exe_dir.parent / "Resources" / "models"):
        if d.is_dir():
            return d
    return None


def log_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    else:
        root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP_NAME.lower()
    return root / "logs"


def setup_frozen_logging() -> Path | None:
    """打包后的窗口程序没有控制台（Windows 下 sys.stdout/stderr 为 None），
    将输出与未捕获异常重定向到日志文件，便于排查医生电脑上的问题。"""
    if not is_frozen():
        return None
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / "mlab.log"
        if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
            path.replace(d / "mlab.old.log")
        f = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - 进程生命周期内保持打开
    except OSError:
        return None
    if sys.stdout is None or not sys.stdout.isatty():
        sys.stdout = f
    if sys.stderr is None or not sys.stderr.isatty():
        sys.stderr = f
    import faulthandler

    faulthandler.enable(f)
    return path
