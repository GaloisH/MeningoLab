"""生成一个随机权重的微型 nnU-Net v2 训练结果目录，用于测试推理流程与安装包（不代表任何真实模型）。

    python scripts/make_dummy_nnunet_model.py 输出目录

会在输出目录下得到 ``Dataset999_MLabDummy/nnUNetTrainer__nnUNetPlans__3d_fullres``（2 个输入通道、
1 个前景标签），可用于 ``MLAB_TEST_NNUNET_MODEL`` 或 ``mlab --self-test --model``。
plans.json 由当前安装的 nnU-Net 自带的规划器生成，因此与其版本保持一致。
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np

DATASET_ID, DATASET_NAME = 999, "Dataset999_MLabDummy"
CONFIG = "3d_fullres"


def _write_raw(raw: Path) -> None:
    d = raw / DATASET_NAME
    (d / "imagesTr").mkdir(parents=True)
    (d / "labelsTr").mkdir()
    affine = np.diag([-1.0, -1.0, 2.0, 1.0])
    rng = np.random.default_rng(0)
    for i in range(2):
        seg = np.zeros((40, 48, 16), np.uint8)
        seg[10 + i:28, 12:30, 4:12] = 1
        for ch in range(2):
            img = (rng.random(seg.shape) + seg * (1 + ch)).astype(np.float32)
            nib.save(nib.Nifti1Image(img, affine), d / "imagesTr" / f"case_{i:03d}_{ch:04d}.nii.gz")
        nib.save(nib.Nifti1Image(seg, affine), d / "labelsTr" / f"case_{i:03d}.nii.gz")
    (d / "dataset.json").write_text(json.dumps({
        "channel_names": {"0": "T1C", "1": "FLAIR"},
        "labels": {"background": 0, "lesion": 1},
        "numTraining": 2,
        "file_ending": ".nii.gz",
    }))


def main(out: str) -> Path:
    out = Path(out).resolve()
    work = Path(tempfile.mkdtemp(prefix="mlab_dummy_"))
    for k in ("raw", "preprocessed", "results"):
        os.environ[f"nnUNet_{k}"] = str(work / k)
    _write_raw(work / "raw")

    # nnunetv2.paths 在导入时读取环境变量，必须在设置之后导入
    import torch
    from nnunetv2.experiment_planning.plan_and_preprocess_api import extract_fingerprints, plan_experiments
    from nnunetv2.utilities.plans_handling.plans_handler import PlansManager

    try:
        from nnunetv2.utilities.find_objects import recursive_find_trainer_class_by_name
    except ImportError:  # nnunetv2 < 2.7
        import nnunetv2
        from nnunetv2.utilities.find_class_by_name import recursive_find_python_class

        def recursive_find_trainer_class_by_name(name):
            return recursive_find_python_class(os.path.join(nnunetv2.__path__[0], "training", "nnUNetTrainer"),
                                               name, "nnunetv2.training.nnUNetTrainer")
    from nnunetv2.utilities.label_handling.label_handling import determine_num_input_channels

    extract_fingerprints([DATASET_ID], num_processes=1, check_dataset_integrity=False, clean=True, verbose=False)
    plans_identifier = plan_experiments([DATASET_ID]) or "nnUNetPlans"
    pre = work / "preprocessed" / DATASET_NAME
    plans = json.loads((pre / f"{plans_identifier}.json").read_text())
    dataset_json = json.loads((pre / "dataset.json").read_text())

    pm = PlansManager(plans)
    cm = pm.get_configuration(CONFIG)
    n_in = determine_num_input_channels(pm, cm, dataset_json)
    n_out = pm.get_label_manager(dataset_json).num_segmentation_heads
    trainer = recursive_find_trainer_class_by_name("nnUNetTrainer")
    if "plans_manager" in inspect.signature(trainer.build_network_architecture).parameters:
        net = trainer.build_network_architecture(pm, cm, n_in, n_out, enable_deep_supervision=False)
    else:
        net = trainer.build_network_architecture(cm.network_arch_class_name, cm.network_arch_init_kwargs,
                                                 cm.network_arch_init_kwargs_req_import, n_in, n_out,
                                                 enable_deep_supervision=False)

    model = out / DATASET_NAME / f"nnUNetTrainer__{plans_identifier}__{CONFIG}"
    (model / "fold_0").mkdir(parents=True, exist_ok=True)
    shutil.copy(pre / f"{plans_identifier}.json", model / "plans.json")
    shutil.copy(pre / "dataset.json", model / "dataset.json")
    torch.save({
        "network_weights": net.state_dict(),
        "trainer_name": "nnUNetTrainer",
        "init_args": {"configuration": CONFIG, "fold": 0},
        "inference_allowed_mirroring_axes": (0, 1, 2),
    }, model / "fold_0" / "checkpoint_final.pth")
    shutil.rmtree(work, ignore_errors=True)
    print(model)
    return model


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
