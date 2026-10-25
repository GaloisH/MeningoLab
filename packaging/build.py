"""一键打包 MLab：生成图标 → PyInstaller → 自检 → 安装程序（Windows .exe / macOS .dmg / Linux .tar.gz）。

    python packaging/build.py                       # 基础版（不含 AI 推理组件）
    python packaging/build.py --edition ai          # AI 版：打包当前环境中的 PyTorch 与 nnU-Net
    python packaging/build.py --edition ai --models 模型目录   # 同时把训练好的模型放进安装包

AI 版是 CPU 版还是 GPU 版取决于当前环境安装的 PyTorch（有 CUDA 即为 GPU 版）。
产物位于 ``dist/installer/``。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))


def log(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def resolve_edition(edition: str) -> str:
    if edition == "base":
        return "base"
    try:
        import nnunetv2  # noqa: F401
        import torch
    except ImportError as e:
        sys.exit(f"AI 版需要在当前环境中安装 torch 与 nnunetv2：{e}")
    if sys.platform == "darwin":
        return "ai"
    return "ai-gpu" if torch.version.cuda else "ai-cpu"


def make_icons(out: Path) -> None:
    """由程序内置的 SVG 图标生成 .png / .ico / .icns。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtGui import QGuiApplication

    from mlab.ui.icons import render_app_icon

    _ = QGuiApplication.instance() or QGuiApplication([])
    out.mkdir(parents=True, exist_ok=True)
    png = out / "mlab.png"
    render_app_icon(1024).save(str(png))
    img = Image.open(png)
    img.save(out / "mlab.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    img.save(out / "mlab.icns")


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def app_paths(edition: str) -> tuple[Path, Path, Path]:
    """返回（分发目录, 可执行文件, 模型应放置的目录）。"""
    if sys.platform == "darwin":
        app = DIST / "MLab.app"
        return app, app / "Contents" / "MacOS" / "MLab", app / "Contents" / "Resources" / "models"
    d = DIST / "MLab"
    return d, d / ("MLab.exe" if sys.platform == "win32" else "MLab"), d / "models"


def self_test(exe: Path, model: Path | None) -> None:
    report = Path(tempfile.mkdtemp(prefix="mlab_build_")) / "self_test.txt"
    cmd = [str(exe), "--self-test", "--report", str(report)]
    if model:
        cmd += ["--model", str(model)]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run(cmd, env=env, timeout=900)
    print(report.read_text(encoding="utf-8") if report.exists() else "（未生成自检报告）")
    if r.returncode != 0:
        sys.exit(f"打包后的程序自检失败（退出码 {r.returncode}）")


def find_iscc() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA") and str(Path(os.environ["LOCALAPPDATA"]) / "Programs")):
        if base and (Path(base) / "Inno Setup 6" / "ISCC.exe").is_file():
            return str(Path(base) / "Inno Setup 6" / "ISCC.exe")
    return None


def package(edition: str, version: str, icons: Path) -> Path:
    out = DIST / "installer"
    out.mkdir(parents=True, exist_ok=True)
    src, _, _ = app_paths(edition)
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                      platform.machine())
    if sys.platform == "win32":
        iscc = find_iscc()
        if not iscc:
            sys.exit("未找到 Inno Setup 6（ISCC.exe），请从 https://jrsoftware.org/isdl.php 安装，或使用 --no-installer")
        defines = [f"/DAppVersion={version}", f"/DEdition={edition}", f"/DSourceDir={src}",
                   f"/DOutputDir={out}", f"/DIconFile={icons / 'mlab.ico'}"]
        if dir_size(src) > 3 * 1024 ** 3:  # GPU 版：拆分为 setup.exe + .bin，避免单文件过大
            defines.append("/DDiskSpanning")
        subprocess.run([iscc, *defines, str(PKG / "installer.iss")], check=True)
        return out / f"MLab-{version}-{edition}-windows-{arch}-setup.exe"
    if sys.platform == "darwin":
        dmg = out / f"MLab-{version}-{edition}-macos-{arch}.dmg"
        stage = Path(tempfile.mkdtemp(prefix="mlab_dmg_"))
        shutil.copytree(src, stage / src.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        dmg.unlink(missing_ok=True)
        subprocess.run(["hdiutil", "create", "-volname", "MLab", "-srcfolder", str(stage), "-ov",
                        "-format", "UDZO", str(dmg)], check=True)
        return dmg
    tgz = out / f"MLab-{version}-{edition}-linux-{arch}.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(src, arcname="MLab")
    return tgz


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", choices=["base", "ai"], default="base")
    ap.add_argument("--models", type=Path, help="随安装包分发的 nnU-Net 训练结果目录（可含多个模型）")
    ap.add_argument("--selftest-model", type=Path, help="自检时用于推理测试的模型（默认取 --models 中的第一个）")
    ap.add_argument("--no-installer", action="store_true", help="只生成程序目录，不制作安装程序")
    ap.add_argument("--skip-self-test", action="store_true")
    args = ap.parse_args()

    from mlab import __version__
    from mlab.inference.nnunet import find_model_folders

    edition = resolve_edition(args.edition)
    models = find_model_folders(args.models) if args.models else []
    if args.models and not models:
        sys.exit(f"{args.models} 下没有找到 nnU-Net 训练结果目录")
    log(f"MLab {__version__} · {edition} · {sys.platform} · Python {platform.python_version()}")

    icons = BUILD / "icons"
    make_icons(icons)
    info = BUILD / "build_info.json"
    info.write_text(json.dumps({
        "version": __version__,
        "edition": edition,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
    }, ensure_ascii=False), encoding="utf-8")

    log("PyInstaller 打包")
    shutil.rmtree(DIST / "MLab", ignore_errors=True)
    shutil.rmtree(DIST / "MLab.app", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", str(PKG / "mlab.spec"), "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--",
                    "--edition", edition, "--icon-dir", str(icons), "--build-info", str(info),
                    "--version", __version__], check=True, cwd=ROOT)

    src, exe, model_dir = app_paths(edition)
    if models:
        log(f"复制 {len(models)} 个模型到 {model_dir}")
        root = args.models.resolve()
        for m in models:
            m = m.resolve()
            dest = model_dir / (m.relative_to(root) if m != root else m.name)
            shutil.copytree(m, dest, dirs_exist_ok=True)
    log(f"程序目录 {src}（{dir_size(src) / 1024 ** 2:.0f} MB）")

    if not args.skip_self_test:
        log("自检")
        test_model = args.selftest_model or (find_model_folders(model_dir)[0] if models else None)
        self_test(exe, test_model if edition != "base" else None)

    if not args.no_installer:
        log("制作安装程序")
        artifact = package(edition, __version__, icons)
        log(f"完成：{artifact}")


if __name__ == "__main__":
    main()
