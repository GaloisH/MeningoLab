"""nnU-Net 真实推理测试：需要安装 nnunetv2，并设置环境变量 MLAB_TEST_NNUNET_MODEL 指向一个
训练结果目录（输入通道为 2 个、file_ending 为 .nii.gz 的三维模型）。未设置时自动跳过。"""
import os

import nibabel as nib
import numpy as np
import pytest

from mlab.core.volume import load_nifti
from mlab.inference.nnunet import NnUNetRunner, PredictorConfig, inspect_model, nnunet_status

MODEL = os.environ.get("MLAB_TEST_NNUNET_MODEL")
pytestmark = pytest.mark.skipif(not MODEL or not nnunet_status()[0], reason="未配置 nnU-Net 测试模型")


def test_predict_aligned_with_reference(tmp_path):
    info = inspect_model(MODEL)
    affine = np.diag([-1.2, -1.2, 3.0, 1.0])
    files = []
    for ch in sorted(info.channel_names):
        p = tmp_path / f"case_{ch:04d}.nii.gz"
        nib.save(nib.Nifti1Image(np.random.default_rng(ch).random((48, 56, 20)).astype(np.float32), affine), p)
        files.append(p)
    cfg = PredictorConfig(folder=MODEL, device="cpu", folds=(info.folds[0],), checkpoint=info.checkpoints[0])
    out = NnUNetRunner().predict(cfg, files, log=lambda m: None)
    ref = load_nifti(files[0])
    lab = ref.load_label(out)
    assert lab.shape == ref.shape
    assert set(np.unique(lab)) <= {0, *info.labels}
