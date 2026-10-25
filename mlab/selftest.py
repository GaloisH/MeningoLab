"""安装包自检：``mlab --self-test [--model 训练结果目录] [--report 结果文件]``。

在离屏模式下创建主窗口、打开一套合成病例、画一笔并保存；AI 版还会检查 PyTorch / nnU-Net
能否正常导入（打包后最容易出问题的地方），给出 ``--model`` 时再做一次真实推理。
结果写到标准输出（打包后为日志文件），退出码 0 表示通过。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def _check_gui(tmp: Path) -> str:
    import nibabel as nib
    import numpy as np
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    root = tmp / "data"
    (root / "case_a").mkdir(parents=True)
    img = np.zeros((32, 32, 8), np.float32)
    img[8:24, 8:24, 2:6] = 100
    for name in ("T1C", "FLAIR"):
        nib.save(nib.Nifti1Image(img, np.diag([-1.0, -1.0, 2.0, 1.0])), root / "case_a" / f"{name}.nii.gz")
    _ = QApplication.instance() or QApplication([])
    win = MainWindow(QSettings(str(tmp / "settings.ini"), QSettings.IniFormat))
    win.open_project(root)
    s = win.session
    assert s.case is not None and len(s.volumes) == 2, "未能打开合成病例"
    s.labelmap.data[10:20, 10:20, 4] = 1
    s.labelmap.modified = True
    assert win.save_current(), "保存标注失败"
    out = root / "labels" / "case_a.nii.gz"
    assert out.is_file(), "未写出标注文件"
    win.close()
    return f"界面与读写正常（{out.name}）"


def _check_nnunet() -> str:
    import pydoc

    import torch
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor  # noqa: F401

    # nnU-Net 通过扫描源码目录查找训练器类，打包时若只收进归档会在这里失败
    try:
        from nnunetv2.utilities.find_objects import recursive_find_trainer_class_by_name
    except ImportError:  # nnunetv2 < 2.7
        import nnunetv2
        from nnunetv2.utilities.find_class_by_name import recursive_find_python_class

        def recursive_find_trainer_class_by_name(name):
            return recursive_find_python_class(str(Path(nnunetv2.__path__[0]) / "training" / "nnUNetTrainer"),
                                               name, "nnunetv2.training.nnUNetTrainer")
    trainer = recursive_find_trainer_class_by_name("nnUNetTrainer")
    assert trainer is not None, "找不到 nnUNetTrainer（nnunetv2 源码未被打包）"
    net = pydoc.locate("dynamic_network_architectures.architectures.unet.PlainConvUNet")
    assert net is not None, "找不到 PlainConvUNet（dynamic_network_architectures 未被打包）"
    y = torch.nn.functional.conv3d(torch.ones(1, 1, 4, 4, 4), torch.ones(1, 1, 3, 3, 3))
    assert float(y.sum()) > 0
    cuda = f"CUDA {torch.version.cuda}，GPU 可用={torch.cuda.is_available()}" if torch.version.cuda else "CPU 版"
    return f"PyTorch {torch.__version__}（{cuda}）、nnU-Net v2 可用"


def _check_inference(model: str, tmp: Path) -> str:
    import nibabel as nib
    import numpy as np

    from .core.volume import load_nifti
    from .inference.nnunet import NnUNetRunner, PredictorConfig, inspect_model

    info = inspect_model(model)
    files = []
    for ch in sorted(info.channel_names):
        p = tmp / f"infer_{ch:04d}{info.file_ending}"
        data = np.random.default_rng(ch).random((40, 48, 16)).astype(np.float32)
        nib.save(nib.Nifti1Image(data, np.diag([-1.0, -1.0, 2.0, 1.0])), p)
        files.append(p)
    cfg = PredictorConfig(folder=str(info.folder), device="cpu", folds=(info.folds[0],),
                          checkpoint=info.checkpoints[0])
    out = NnUNetRunner().predict(cfg, files, log=lambda m: None)
    lab = load_nifti(files[0]).load_label(out)
    assert lab.shape == (40, 48, 16), f"预测结果尺寸不符：{lab.shape}"
    return f"模型推理正常（{info.display_name}）"


def run(argv: list[str]) -> int:
    from . import __version__
    from .inference.nnunet import nnunet_status
    from .runtime import edition, is_frozen

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "--report" in argv:  # Windows 窗口程序没有标准输出，可把结果写到指定文件
        sys.stdout = sys.stderr = open(argv[argv.index("--report") + 1], "w", encoding="utf-8")  # noqa: SIM115
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    ed = edition()
    need_ai = ed.startswith("ai") or "--require-ai" in argv or model is not None
    print(f"MLab {__version__} 自检（{ed or 'source'}，{'安装版' if is_frozen() else '源码'}，Python {sys.version.split()[0]}）")

    checks = [("界面", _check_gui)]
    if need_ai:
        checks.append(("AI 组件", lambda tmp: _check_nnunet()))
        if model:
            checks.append(("推理", lambda tmp: _check_inference(model, tmp)))
    failed = 0
    with tempfile.TemporaryDirectory(prefix="mlab_selftest_") as d:
        for name, fn in checks:
            try:
                print(f"[通过] {name}：{fn(Path(d))}")
            except Exception:  # noqa: BLE001 - 汇总所有失败项
                failed += 1
                print(f"[失败] {name}：\n{traceback.format_exc()}")
    if not need_ai:
        print(f"[信息] AI 组件：{nnunet_status()[1]}")
    print("自检通过" if not failed else f"自检失败：{failed} 项")
    sys.stdout.flush()
    return 1 if failed else 0
