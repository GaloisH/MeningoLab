"""界面端到端测试（离屏运行）。"""
import nibabel as nib
import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mlab.core.project import STATUS_DONE, STATUS_WIP  # noqa: E402
from mlab.core.volume import AXIAL, voxel_to_screen  # noqa: E402
from mlab.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def data_root(tmp_path):
    affine = np.diag([-1.0, -1.0, 2.0, 1.0])
    img = np.zeros((40, 40, 12), np.float32)
    img[10:30, 10:30, 3:9] = 100
    for name in ("T1C", "FLAIR"):
        d = tmp_path / "case_a"
        d.mkdir(exist_ok=True)
        nib.save(nib.Nifti1Image(img, affine), d / f"{name}.nii.gz")
    nib.save(nib.Nifti1Image(img, affine), tmp_path / "case_b.nii.gz")
    Image.fromarray((np.arange(30 * 20) % 255).reshape(20, 30).astype(np.uint8)).save(tmp_path / "pic.png")
    return tmp_path


@pytest.fixture
def win(app, tmp_path, data_root):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    w = MainWindow(settings)
    w.resize(1400, 900)
    w.show()
    QTest.qWaitForWindowExposed(w)
    w.open_project(data_root)
    yield w
    w.session.labelmap and setattr(w.session.labelmap, "modified", False)
    w.close()


def _canvas_point(w, voxel):
    canvas = w.viewer.panels[AXIAL].canvas
    r, c = voxel_to_screen(w.session.shape, AXIAL, voxel)
    sp_r, sp_c = canvas._sp
    return canvas, canvas.mapFromScene(QPointF((c + 0.5) * sp_c, (r + 0.5) * sp_r))


def test_paint_save_reload(win, data_root):
    s = win.session
    assert s.case.case_id == "case_a" and len(s.volumes) == 2
    s.set_tool("brush")
    s.set_active_label(1)
    s.set_cursor((20, 20, 5))
    canvas, p = _canvas_point(win, (20, 20, 5))
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, p)
    QTest.mouseMove(canvas.viewport(), p + QPoint(30, 0))
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, p + QPoint(30, 0))
    assert s.labelmap.data[:, :, 5].sum() > 0
    assert s.labelmap.modified and win.act_undo.isEnabled()
    painted = s.labelmap.data.copy()
    win.act_save.trigger()
    path = data_root / "labels" / "case_a.nii.gz"
    assert path.exists() and not s.labelmap.modified
    assert win.project.status(s.case) == STATUS_WIP
    # 撤销 / 重做
    win.act_undo.trigger()
    assert s.labelmap.data.sum() == 0
    win.act_redo.trigger()
    assert np.array_equal(s.labelmap.data, painted)
    s.labelmap.modified = False
    # 切换到另一个病例再切回，标注从文件恢复
    win.open_case("case_b")
    assert s.case.case_id == "case_b" and s.labelmap.data.sum() == 0
    win.open_case("case_a")
    assert np.array_equal(s.labelmap.data, painted)


def test_tools_via_controller(win):
    s, ctrl = win.session, win.ctrl
    s.set_cursor((20, 20, 4))
    s.set_active_label(2)
    # 多边形
    s.set_tool("polygon")
    for rc in [(12, 12), (12, 28), (28, 28), (28, 12)]:
        ctrl.press(AXIAL, *rc)
        ctrl.release(AXIAL, *rc)
    ctrl.close_polygon()
    assert (s.labelmap.data[:, :, 4] == 2).sum() > 100
    # 在第 8 层画，再插值
    s.set_cursor((20, 20, 8))
    for rc in [(14, 14), (14, 26), (26, 26), (26, 14)]:
        ctrl.press(AXIAL, *rc)
    ctrl.close_polygon()
    ctrl.interpolate(AXIAL)
    assert all((s.labelmap.data[:, :, k] == 2).any() for k in (5, 6, 7))
    # 三维区域生长（保护其他标签）
    s.set_active_label(3)
    s.set_tool("grow")
    s.set_tool_option(grow_3d=True)
    s.set_cursor((20, 20, 3))
    r, c = voxel_to_screen(s.shape, AXIAL, (20, 20, 3))
    ctrl.press(AXIAL, r + 0.5, c + 0.5)
    lab = s.labelmap.data
    assert (lab == 3).sum() > 0 and (lab == 2).sum() > 100
    ctrl.undo()
    assert (s.labelmap.data == 3).sum() == 0


def test_view_interactions(win):
    s = win.session
    canvas, p = _canvas_point(win, (20, 20, 6))
    s.set_cursor((20, 20, 6))
    ev = QWheelEvent(QPointF(p), QPointF(canvas.mapToGlobal(p)), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    canvas.wheelEvent(ev)
    assert s.cursor[2] == 7
    lo, hi = s.window()
    QTest.mousePress(canvas.viewport(), Qt.RightButton, Qt.NoModifier, p)
    QTest.mouseMove(canvas.viewport(), p + QPoint(40, 20))
    QTest.mouseRelease(canvas.viewport(), Qt.RightButton, Qt.NoModifier, p + QPoint(40, 20))
    assert s.window() != (lo, hi)
    win.viewer.toggle_single(AXIAL)
    assert win.viewer.panels[2].isVisible() and not win.viewer.panels[1].isVisible()
    win.viewer.toggle_single(AXIAL)
    win.toggle_theme()
    assert win.theme.name == "light"
    s.set_sequence(1)
    assert s.volume.name == "FLAIR"


def test_2d_case_and_mark_done(win, data_root):
    s = win.session
    win.open_case("pic")
    assert s.is_2d and s.shape == (30, 20, 1)
    assert not win.viewer.panels[1].isVisible()
    s.set_tool("brush")
    s.set_active_label(1)
    win.ctrl.press(AXIAL, 5, 5)
    win.ctrl.release(AXIAL, 5, 5)
    win.mark_done()
    out = np.asarray(Image.open(data_root / "labels" / "pic.png"))
    assert out.shape == (20, 30) and out[5, 5] == 1
    assert win.project.status(win.project.find("pic")) == STATUS_DONE
    # 自动跳到下一个未完成病例，且切回三视图
    assert s.case.case_id != "pic" and win.viewer.panels[1].isVisible()


def test_modified_flag_after_save(win):
    s = win.session
    s.set_tool("brush")
    s.set_active_label(1)
    win.ctrl.press(AXIAL, 10, 10)
    win.ctrl.release(AXIAL, 10, 10)
    assert win.windowTitle().endswith("*")
    win.save_current()
    assert not win.windowTitle().endswith("*")
    win.ctrl.press(AXIAL, 20, 20)
    win.ctrl.release(AXIAL, 20, 20)
    assert win.windowTitle().endswith("*") and "未保存" in win.saved_label.text()
