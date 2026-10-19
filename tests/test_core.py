import json

import nibabel as nib
import numpy as np
import pytest
from PIL import Image

from mlab.core import tools
from mlab.core.labels import LabelSet
from mlab.core.project import STATUS_DONE, STATUS_TODO, Project
from mlab.core.segmentation import LabelMap
from mlab.core.volume import (AXIAL, CORONAL, SAGITTAL, load_image2d, load_nifti, load_volumes, screen_to_voxel,
                              slice_view, voxel_to_screen)
from mlab.inference.nnunet import find_model_folders, inspect_model, match_channels


@pytest.mark.parametrize("affine", [np.diag([-0.9, -0.9, 3.0, 1.0]), np.diag([1.0, 2.0, 3.0, 1.0]),
                                    np.array([[0, 0, 2.0, 0], [-1.0, 0, 0, 0], [0, -1.5, 0, 0], [0, 0, 0, 1]])])
def test_label_roundtrip_keeps_original_grid(tmp_path, affine):
    rng = np.random.default_rng(0)
    data = rng.random((10, 12, 8)).astype(np.float32)
    nib.save(nib.Nifti1Image(data, affine), tmp_path / "img.nii.gz")
    vol = load_nifti(tmp_path / "img.nii.gz")
    lab = np.zeros(vol.shape, np.uint8)
    lab[2:4, 3:7, 1] = 2
    vol.save_label(lab, tmp_path / "lab.nii.gz")
    saved = nib.load(tmp_path / "lab.nii.gz")
    assert saved.shape == data.shape
    assert np.allclose(saved.affine, affine)
    assert saved.get_data_dtype() == np.uint8
    # 保存的标签在原始体素顺序下与原图对应：同一物理点的值一致
    canon_img = nib.as_closest_canonical(nib.load(tmp_path / "img.nii.gz"))
    canon_lab = nib.as_closest_canonical(saved)
    assert np.array_equal(np.asanyarray(canon_lab.dataobj), lab)
    assert np.allclose(np.asanyarray(canon_img.dataobj), vol.data)
    assert np.array_equal(vol.load_label(tmp_path / "lab.nii.gz"), lab)


def test_multisequence_resampled_to_reference(tmp_path):
    nib.save(nib.Nifti1Image(np.ones((10, 10, 6), np.float32), np.diag([1, 1, 2, 1.0])), tmp_path / "a.nii.gz")
    nib.save(nib.Nifti1Image(np.ones((20, 20, 12), np.float32), np.diag([0.5, 0.5, 1, 1.0])), tmp_path / "b.nii.gz")
    vols = load_volumes([tmp_path / "a.nii.gz", tmp_path / "b.nii.gz"])
    assert vols[1].shape == vols[0].shape


def test_image2d_roundtrip(tmp_path):
    arr = np.arange(6 * 9, dtype=np.uint8).reshape(6, 9)
    Image.fromarray(arr).save(tmp_path / "x.png")
    vol = load_image2d(tmp_path / "x.png")
    assert vol.shape == (9, 6, 1)
    assert np.array_equal(slice_view(vol.data, AXIAL, 0), arr)  # 显示方向与原图一致
    lab = np.zeros(vol.shape, np.uint8)
    slice_view(lab, AXIAL, 0)[1, 2] = 3
    vol.save_label(lab, tmp_path / "lab.png")
    out = np.asarray(Image.open(tmp_path / "lab.png"))
    assert out.shape == arr.shape and out[1, 2] == 3 and out.sum() == 3
    assert np.array_equal(vol.load_label(tmp_path / "lab.png"), lab)


@pytest.mark.parametrize("axis", [SAGITTAL, CORONAL, AXIAL])
def test_screen_voxel_mapping(axis):
    shape = (5, 7, 9)
    arr = np.arange(np.prod(shape)).reshape(shape)
    v = (1, 2, 3)
    r, c = voxel_to_screen(shape, axis, v)
    assert slice_view(arr, axis, v[axis])[r, c] == arr[v]
    assert screen_to_voxel(shape, axis, v[axis], r, c) == v


def test_slice_view_is_writable_view():
    lab = np.zeros((4, 5, 6), np.uint8)
    slice_view(lab, CORONAL, 2)[0, 0] = 7
    assert lab.sum() == 7 and lab[:, 2, :].sum() == 7


def test_paint_constraints():
    lab = np.zeros((20, 20), np.uint8)
    lab[0:5, :] = 2
    img = np.zeros((20, 20))
    img[:, 10:] = 100
    mask = np.ones((20, 20), bool)
    tools.paint(lab, mask, 1, protect_others=True, intensity_range=(50, 200), image=img)
    assert (lab[0:5] == 2).all()
    assert (lab[5:, 10:] == 1).all() and (lab[5:, :10] == 0).all()
    tools.paint(lab, mask, 0, erase_only=2)
    assert not (lab == 2).any() and (lab == 1).any()


def test_disk_and_polygon():
    m = tools.disk_mask((21, 21), (10.5, 10.5), (3, 3))
    assert m[10, 10] and not m[0, 0] and 20 < m.sum() < 40
    p = tools.polygon_mask((10, 10), [(2, 2), (2, 8), (8, 8), (8, 2)])
    assert p[5, 5] and not p[0, 0]


def test_region_grow():
    img = np.zeros((10, 10, 10))
    img[2:5, 2:5, 2:5] = 10
    img[7:9, 7:9, 7:9] = 10
    m = tools.region_grow(img, (3, 3, 3), 5, 15)
    assert m.sum() == 27


def test_interpolation_fills_gap():
    lab = np.zeros((20, 20, 10), np.uint8)
    lab[5:15, 5:15, 2] = 1
    lab[7:13, 7:13, 6] = 1
    added, filled = tools.interpolate_slices(lab, 1, axis=2)
    assert filled == 3
    for k in (3, 4, 5):
        assert lab[:, :, k].sum() > 0
    assert lab[:, :, 7].sum() == 0


def test_labelmap_undo_redo():
    lm = LabelMap((5, 5, 5))
    region = (slice(None), slice(None), slice(2, 3))
    before = lm.snapshot(region)
    lm.data[1, 1, 2] = 4
    assert lm.commit(region, before)
    assert not lm.commit(region, lm.snapshot(region))  # 无变化不记录
    lm.undo()
    assert lm.data.sum() == 0
    lm.redo()
    assert lm.data[1, 1, 2] == 4
    assert lm.stats((1, 1, 1)) == {4: (1, 0.001)}


def test_labelset(tmp_path):
    ls = LabelSet.default()
    assert len(ls) >= 1
    lab = ls.add("新病灶")
    assert ls.get(lab.value).name == "新病灶"
    ls.save(tmp_path / "l.json")
    assert [l.name for l in LabelSet.load(tmp_path / "l.json")] == [l.name for l in ls]
    lut = ls.lut()
    assert lut.shape == (256, 4) and lut[0, 3] == 0


def _write(p, shape=(4, 4, 4)):
    p.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros(shape, np.float32), np.eye(4)), p)


def test_project_scan_and_status(tmp_path):
    _write(tmp_path / "p1" / "FLAIR.nii.gz")
    _write(tmp_path / "p1" / "T1C.nii.gz")
    _write(tmp_path / "p1" / "p1_seg.nii.gz")  # 掩膜文件不应被当作序列
    _write(tmp_path / "x_0000.nii.gz")
    _write(tmp_path / "x_0001.nii.gz")
    _write(tmp_path / "single.nii")
    _write(tmp_path / "imagesTr" / "a_0000.nii.gz")
    _write(tmp_path / "imagesTr" / "b_0000.nii.gz")
    _write(tmp_path / "labels" / "single.nii.gz")
    Image.fromarray(np.zeros((4, 4), np.uint8)).save(tmp_path / "img.png")
    proj = Project(tmp_path)
    ids = {c.case_id: c for c in proj.cases}
    assert set(ids) == {"p1", "x", "single", "a", "b", "img"}
    assert [p.name for p in ids["p1"].images] == ["T1C.nii.gz", "FLAIR.nii.gz"]  # 增强 T1 优先
    assert ids["x"].channels == [0, 1]
    assert ids["img"].kind == "2d"
    assert proj.status(ids["single"]) != STATUS_TODO  # 已有标签文件
    proj.set_status(ids["p1"], STATUS_DONE)
    assert Project(tmp_path).status(ids["p1"]) == STATUS_DONE
    assert json.loads((tmp_path / ".mlab" / "project.json").read_text(encoding="utf-8"))["cases"]["p1"]["status"] == STATUS_DONE


def test_match_channels(tmp_path):
    t1c, flair = tmp_path / "T1C.nii.gz", tmp_path / "FLAIR.nii.gz"
    assert match_channels([flair, t1c], {0: "T1C", 1: "FLAIR"}) == [t1c, flair]
    a0, a1 = tmp_path / "c_0000.nii.gz", tmp_path / "c_0001.nii.gz"
    assert match_channels([a1, a0], {0: "x", 1: "y"}) == [a0, a1]
    assert match_channels([t1c], {0: "a", 1: "b"}) is None


def test_inspect_model(tmp_path):
    m = tmp_path / "Dataset101_Men" / "nnUNetTrainer__nnUNetPlans__3d_fullres"
    (m / "fold_0").mkdir(parents=True)
    (m / "fold_1").mkdir()
    (m / "fold_0" / "checkpoint_final.pth").write_bytes(b"")
    (m / "dataset.json").write_text(json.dumps({"channel_names": {"0": "T1C", "1": "FLAIR"},
                                                "labels": {"background": 0, "enh": 1, "abscess": 2},
                                                "file_ending": ".nii.gz"}))
    (m / "plans.json").write_text("{}")
    assert find_model_folders(tmp_path) == [m]
    info = inspect_model(m)
    assert info.labels == {1: "enh", 2: "abscess"} and info.folds == ["0", "1"]
    assert info.configuration == "3d_fullres" and info.dataset_name == "Dataset101_Men"
