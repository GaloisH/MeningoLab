# -*- mode: python ; coding: utf-8 -*-
"""MLab 的 PyInstaller 打包配置。请通过 ``python packaging/build.py`` 调用，
它会先生成图标与版本信息，再以 ``pyinstaller mlab.spec -- --edition ...`` 的形式运行本文件。"""
import argparse
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

parser = argparse.ArgumentParser()
parser.add_argument("--edition", default="base")
parser.add_argument("--icon-dir", required=True)
parser.add_argument("--build-info", required=True)
parser.add_argument("--version", required=True)
opts = parser.parse_args()

ROOT = Path(SPECPATH).parent
AI = opts.edition != "base"
ICON_DIR = Path(opts.icon_dir)

datas = collect_data_files("mlab") + [(opts.build_info, ".")]
hiddenimports = []
module_collection_mode = {}
# 同时存在多个 Qt 绑定时 PyInstaller 会报错；其余为开发/交互环境才用到的大包
excludes = ["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "notebook", "pytest", "sphinx"]

if AI:
    # nnU-Net 按名称在磁盘上的源码目录里查找训练器类（recursive_find_python_class），
    # 网络结构则通过 pydoc.locate 动态导入，静态分析都看不到，需要整包收集
    for pkg in ("nnunetv2", "dynamic_network_architectures", "batchgenerators", "batchgeneratorsv2", "acvl_utils"):
        try:
            hiddenimports += collect_submodules(pkg, on_error="ignore")
            datas += collect_data_files(pkg)
        except Exception as e:  # noqa: BLE001 - 旧版 nnU-Net 不依赖其中某些包
            print(f"[mlab.spec] 跳过 {pkg}: {e}")
    module_collection_mode["nnunetv2"] = "pyz+py"
    for dist in ("nnunetv2", "torch", "blosc2", "SimpleITK", "acvl-utils", "batchgenerators"):
        try:
            datas += copy_metadata(dist)
        except Exception:  # noqa: BLE001
            pass
else:
    # 基础版：即使构建环境装了 PyTorch / nnU-Net 也不打进去（它们只在函数内延迟导入）
    excludes += ["torch", "torchvision", "nnunetv2", "dynamic_network_architectures", "batchgenerators",
                 "batchgeneratorsv2", "acvl_utils", "SimpleITK", "matplotlib", "pandas", "skimage", "sklearn"]

a = Analysis(
    [str(ROOT / "mlab" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    module_collection_mode=module_collection_mode,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(ICON_DIR / ("mlab.ico" if sys.platform == "win32" else "mlab.icns" if sys.platform == "darwin" else "mlab.png"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MLab",
    console=False,
    # UPX 压缩会损坏部分 Qt / CUDA 动态库，也更容易被医院的杀毒软件误报
    upx=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MLab", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MLab.app",
        icon=icon,
        bundle_identifier="org.mlab.MLab",
        version=opts.version,
        info_plist={
            "CFBundleDisplayName": "MLab",
            "CFBundleShortVersionString": opts.version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
