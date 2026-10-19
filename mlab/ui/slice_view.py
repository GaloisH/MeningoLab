"""单个切片视图：影像 + 标签叠加 + 十字线 + 笔刷/多边形预览。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QFrame, QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPathItem,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                               QLineEdit, QSlider, QToolButton, QVBoxLayout, QWidget)

from ..core.render import compose, window_to_uint8
from ..core.volume import (AXIAL, ORIENTATION_MARKS, PLANE_EN, PLANE_NAMES, plane_axes, plane_spacing,
                           screen_to_voxel, slice_view)
from .controller import AnnotationController
from .session import TOOL_BRUSH, TOOL_ERASER, TOOL_NAVIGATE, TOOL_POLYGON, Session
from .theme import PLANE_COLORS


class SliceCanvas(QGraphicsView):
    hovered = Signal(int, object)  # axis, voxel 或 None
    maximizeRequested = Signal(int)

    def __init__(self, axis: int, session: Session, controller: AnnotationController, parent=None):
        super().__init__(parent)
        self.axis = axis
        self.s = session
        self.ctrl = controller
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setBackgroundBrush(QColor("#0b0d10"))

        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.FastTransformation)
        self._scene.addItem(self._pix)
        self._vline = QGraphicsLineItem()
        self._hline = QGraphicsLineItem()
        for ln in (self._vline, self._hline):
            ln.setZValue(5)
            self._scene.addItem(ln)
        self._brush = QGraphicsEllipseItem()
        self._brush.setZValue(10)
        self._brush.setVisible(False)
        self._scene.addItem(self._brush)
        self._poly = QGraphicsPathItem()
        self._poly.setZValue(11)
        self._scene.addItem(self._poly)

        self._zoom = 1.0
        self._center: QPointF | None = None
        self._img_size = (0, 0)  # (h, w)
        self._sp = (1.0, 1.0)  # (行间距, 列间距)
        self._drag_mode = None  # "pan" / "wl" / "tool"
        self._drag_start = None
        self._wl_start = None
        self._space = False
        self._hover_rc: tuple[float, float] | None = None

    # ------------------------------------------------------------------ 坐标
    def _scene_to_rc(self, pt: QPointF) -> tuple[float, float]:
        sp_r, sp_c = self._sp
        return pt.y() / sp_r, pt.x() / sp_c

    def _event_rc(self, ev) -> tuple[float, float]:
        return self._scene_to_rc(self.mapToScene(ev.position().toPoint()))

    # ------------------------------------------------------------------ 渲染
    def refresh(self) -> None:
        s = self.s
        if not s.has_data:
            self._pix.setPixmap(QPixmap())
            self._vline.setVisible(False)
            self._hline.setVisible(False)
            self.viewport().update()
            return
        vol = s.volume
        idx = s.cursor[self.axis]
        if vol.rgb is not None:
            base = slice_view(vol.rgb, self.axis, idx)
        else:
            lo, hi = s.window()
            base = window_to_uint8(slice_view(vol.data, self.axis, idx), lo, hi)
        lab = slice_view(s.labelmap.data, self.axis, idx) if s.show_labels else None
        rgb = compose(base, lab, s.labelset.lut(), s.opacity, s.outline)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pix.setPixmap(QPixmap.fromImage(qimg))
        sp = plane_spacing(vol.spacing, self.axis)
        geometry_changed = (h, w) != self._img_size or sp != self._sp
        self._img_size, self._sp = (h, w), sp
        self._pix.setTransform(QTransform.fromScale(sp[1], sp[0]))
        self._update_crosshair()
        self._update_overlays()
        if geometry_changed:
            self._center = None
            self._zoom = 1.0
            self.apply_view_transform()
        self.viewport().update()

    def _update_crosshair(self) -> None:
        s = self.s
        show = s.show_crosshair and not s.is_2d
        self._vline.setVisible(show)
        self._hline.setVisible(show)
        if not show:
            return
        i, j = plane_axes(self.axis)
        shape = s.shape
        sp_r, sp_c = self._sp
        h, w = self._img_size
        x = (shape[i] - 1 - s.cursor[i] + 0.5) * sp_c
        y = (shape[j] - 1 - s.cursor[j] + 0.5) * sp_r
        for line, axis_color, coords in ((self._vline, i, (x, 0, x, h * sp_r)), (self._hline, j, (0, y, w * sp_c, y))):
            c = QColor(PLANE_COLORS[axis_color])
            c.setAlphaF(0.75)
            pen = QPen(c, 1)
            pen.setCosmetic(True)
            pen.setStyle(Qt.DashLine)
            line.setPen(pen)
            line.setLine(*coords)

    def _update_overlays(self) -> None:
        """笔刷光标与多边形预览。"""
        s = self.s
        sp_r, sp_c = self._sp
        if s.tool in (TOOL_BRUSH, TOOL_ERASER) and self._hover_rc is not None:
            rr, rc = self.ctrl.brush_radius(self.axis)
            r, c = self._hover_rc
            color = QColor("#ffffff") if s.tool == TOOL_ERASER else QColor(*(s.labelset.get(s.active_label).color
                                                                             if s.labelset.get(s.active_label) else (255, 255, 255)))
            pen = QPen(color, 1.5)
            pen.setCosmetic(True)
            if s.tool == TOOL_ERASER:
                pen.setStyle(Qt.DashLine)
            self._brush.setPen(pen)
            self._brush.setRect(QRectF((c - rc) * sp_c, (r - rr) * sp_r, 2 * rc * sp_c, 2 * rr * sp_r))
            self._brush.setVisible(True)
        else:
            self._brush.setVisible(False)

        path = QPainterPath()
        if s.tool == TOOL_POLYGON and self.ctrl.poly_axis == self.axis and self.ctrl.poly_points:
            pts = [QPointF(c * sp_c, r * sp_r) for r, c in self.ctrl.poly_points]
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            if self.ctrl.poly_hover is not None:
                hr, hc = self.ctrl.poly_hover
                path.lineTo(QPointF(hc * sp_c, hr * sp_r))
            lab = s.labelset.get(s.active_label)
            color = QColor(*(lab.color if lab else (255, 255, 255)))
            pen = QPen(color, 1.8)
            pen.setCosmetic(True)
            self._poly.setPen(pen)
            fill = QColor(color)
            fill.setAlphaF(0.18)
            self._poly.setBrush(QBrush(fill))
        self._poly.setPath(path)

    def apply_view_transform(self) -> None:
        h, w = self._img_size
        if not h or not w:
            return
        sp_r, sp_c = self._sp
        sw, sh = w * sp_c, h * sp_r
        vw, vh = max(self.viewport().width(), 1), max(self.viewport().height(), 1)
        fit = min(vw / sw, vh / sh) * 0.96
        scale = fit * self._zoom
        big = max(sw, sh) * 20
        self.setSceneRect(QRectF(-big, -big, sw + 2 * big, sh + 2 * big))
        self.setTransform(QTransform.fromScale(scale, scale))
        self.centerOn(self._center if self._center is not None else QPointF(sw / 2, sh / 2))

    def reset_view(self) -> None:
        self._zoom, self._center = 1.0, None
        self.apply_view_transform()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.apply_view_transform()

    # ------------------------------------------------------------------ 前景文字
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        s = self.s
        if not s.has_data:
            return
        painter.save()
        painter.resetTransform()
        vw, vh = self.viewport().width(), self.viewport().height()
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        painter.setFont(font)

        def text(x, y, txt, align, color="#d7dde6"):
            r = QRectF(x, y, vw - 16, vh - 12)
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(r.translated(1, 1), align, txt)
            painter.setPen(QColor(color))
            painter.drawText(r, align, txt)

        lo, hi = s.window()
        if s.volume.rgb is None:
            text(8, 6, f"W {hi - lo:.0f}  L {(hi + lo) / 2:.0f}", Qt.AlignLeft | Qt.AlignBottom)
        text(8, 6, f"{self._zoom * 100:.0f}%", Qt.AlignRight | Qt.AlignBottom, "#8b95a5")
        if len(s.volumes) > 1:
            text(8, 6, s.volume.name, Qt.AlignRight | Qt.AlignTop, "#8b95a5")
        if not s.is_2d:
            left, right, top, bottom = ORIENTATION_MARKS[self.axis]
            font.setBold(True)
            font.setPointSizeF(11)
            painter.setFont(font)
            col = "#e8c46a"
            text(8, 0, left, Qt.AlignLeft | Qt.AlignVCenter, col)
            text(8, 0, right, Qt.AlignRight | Qt.AlignVCenter, col)
            text(8, 6, top, Qt.AlignHCenter | Qt.AlignTop, col)
            text(8, 6, bottom, Qt.AlignHCenter | Qt.AlignBottom, col)
        painter.restore()

    # ------------------------------------------------------------------ 鼠标
    def mousePressEvent(self, ev) -> None:
        if not self.s.has_data:
            return
        self.setFocus()
        self.s.set_active_axis(self.axis)
        btn = ev.button()
        self._drag_start = ev.position()
        if btn == Qt.MiddleButton or (btn == Qt.LeftButton and self._space):
            self._drag_mode = "pan"
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif btn == Qt.RightButton:
            if self.s.tool == TOOL_POLYGON and self.ctrl.poly_points:
                self.ctrl.close_polygon()  # 右键闭合多边形
                return
            if self.s.volume.rgb is None:
                self._drag_mode = "wl"
                self._wl_start = self.s.window()
        elif btn == Qt.LeftButton:
            self._drag_mode = "tool"
            rf, cf = self._event_rc(ev)
            self.ctrl.press(self.axis, rf, cf, shift=bool(ev.modifiers() & Qt.ShiftModifier))

    def mouseMoveEvent(self, ev) -> None:
        if not self.s.has_data:
            return
        rf, cf = self._event_rc(ev)
        self._hover_rc = (rf, cf)
        h, w = self._img_size
        voxel = None
        if 0 <= rf < h and 0 <= cf < w:
            voxel = screen_to_voxel(self.s.shape, self.axis, self.s.cursor[self.axis], int(rf), int(cf))
        self.hovered.emit(self.axis, voxel)
        if self._drag_mode == "pan":
            d = ev.position() - self._drag_start
            self._drag_start = ev.position()
            scale = self.transform().m11()
            center = self.mapToScene(self.viewport().rect().center())
            self._center = QPointF(center.x() - d.x() / scale, center.y() - d.y() / scale)
            self.centerOn(self._center)
        elif self._drag_mode == "wl":
            d = ev.position() - self._drag_start
            lo, hi = self._wl_start
            width, level = hi - lo, (hi + lo) / 2
            vmin, vmax = self.s.volume.value_range
            step = max(vmax - vmin, 1e-3) / 600.0
            width = max(width + d.x() * step * 2, step)
            level = level - d.y() * step
            self.s.set_window(level - width / 2, level + width / 2)
        else:
            self.ctrl.move(self.axis, rf, cf, pressed=self._drag_mode == "tool")
            if self.s.tool in (TOOL_BRUSH, TOOL_ERASER):
                self._update_overlays()

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag_mode == "tool":
            rf, cf = self._event_rc(ev)
            self.ctrl.release(self.axis, rf, cf)
        self._drag_mode = None
        self._update_cursor_shape()

    def mouseDoubleClickEvent(self, ev) -> None:
        if not self.s.has_data or ev.button() != Qt.LeftButton:
            return
        rf, cf = self._event_rc(ev)
        if not self.ctrl.double_click(self.axis, rf, cf) and self.s.tool == TOOL_NAVIGATE:
            self.maximizeRequested.emit(self.axis)

    def leaveEvent(self, ev) -> None:
        self._hover_rc = None
        self._brush.setVisible(False)
        self.hovered.emit(self.axis, None)
        super().leaveEvent(ev)

    def enterEvent(self, ev) -> None:
        self._update_cursor_shape()
        # 鼠标移入即可用键盘翻层；正在输入文字时不抢焦点
        if not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox)):
            self.setFocus()
        super().enterEvent(ev)

    def wheelEvent(self, ev) -> None:
        if not self.s.has_data:
            return
        delta = ev.angleDelta().y()
        if not delta:
            return
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.15 if delta > 0 else 1 / 1.15
            anchor = self.mapToScene(ev.position().toPoint())
            old_center = self.mapToScene(self.viewport().rect().center())
            self._zoom = float(np.clip(self._zoom * factor, 0.2, 40))
            # 以鼠标位置为锚点缩放
            self._center = QPointF(anchor.x() + (old_center.x() - anchor.x()) / factor,
                                   anchor.y() + (old_center.y() - anchor.y()) / factor)
            self.apply_view_transform()
            self.viewport().update()
        elif not self.s.is_2d:
            self.s.set_active_axis(self.axis)
            self.s.move_slice(self.axis, 1 if delta > 0 else -1)

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        if key == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif key in (Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Down, Qt.Key_PageDown) and self.s.has_data:
            step = 1 if key in (Qt.Key_Up, Qt.Key_PageUp) else -1
            if key in (Qt.Key_PageUp, Qt.Key_PageDown):
                step *= 5
            self.s.move_slice(self.axis, step)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and self.ctrl.poly_points:
            self.ctrl.close_polygon()
        elif key == Qt.Key_Escape and self.ctrl.poly_points:
            self.ctrl.cancel_polygon()
        elif key == Qt.Key_Backspace and self.ctrl.poly_points:
            self.ctrl.undo_polygon_point()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self._update_cursor_shape()
        super().keyReleaseEvent(ev)

    def _update_cursor_shape(self) -> None:
        tool = self.s.tool
        if self._space:
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif tool in (TOOL_BRUSH, TOOL_ERASER):
            self.viewport().setCursor(Qt.BlankCursor if self.s.has_data else Qt.ArrowCursor)
        elif tool == TOOL_NAVIGATE:
            self.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.CrossCursor)


class ViewPanel(QFrame):
    """带标题栏（平面名称、层滑块、最大化按钮）的视图容器。"""

    def __init__(self, axis: int, session: Session, controller: AnnotationController, icon_fn, parent=None):
        super().__init__(parent)
        self.setObjectName("ViewPanel")
        self.axis = axis
        self.s = session
        self._icon_fn = icon_fn
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

        header = QWidget()
        header.setObjectName("ViewHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 4, 6, 4)
        hl.setSpacing(8)
        color = PLANE_COLORS[axis]
        self.title = QLabel(f"<span style='color:{color}; font-size:13pt'>●</span>&nbsp; <b>{PLANE_NAMES[axis]}</b>"
                            f"&nbsp;<span style='color:#8b95a5'>{PLANE_EN[axis]}</span>")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimumWidth(60)
        self.slider.valueChanged.connect(self._on_slider)
        self.index_label = QLabel("–")
        self.index_label.setMinimumWidth(64)
        self.index_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.index_label.setProperty("muted", True)
        self.max_btn = QToolButton()
        self.max_btn.setToolTip("最大化 / 还原该视图")
        self.max_btn.setAutoRaise(True)
        hl.addWidget(self.title)
        hl.addWidget(self.slider, 1)
        hl.addWidget(self.index_label)
        hl.addWidget(self.max_btn)
        lay.addWidget(header)
        self.header = header

        self.canvas = SliceCanvas(axis, session, controller, self)
        lay.addWidget(self.canvas, 1)
        self._updating = False
        self.refresh_icons()

    def refresh_icons(self, maximized: bool = False) -> None:
        self.max_btn.setIcon(self._icon_fn("minimize" if maximized else "maximize"))

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def sync_slider(self) -> None:
        s = self.s
        if not s.has_data:
            self.index_label.setText("–")
            return
        n = s.shape[self.axis]
        self._updating = True
        self.slider.setRange(0, n - 1)
        self.slider.setValue(s.cursor[self.axis])
        self._updating = False
        self.slider.setVisible(not s.is_2d)
        self.index_label.setText(f"{s.cursor[self.axis] + 1} / {n}" if not s.is_2d else "二维图像")

    def _on_slider(self, v: int) -> None:
        if self._updating or not self.s.has_data:
            return
        cur = list(self.s.cursor)
        cur[self.axis] = v
        self.s.set_active_axis(self.axis)
        self.s.set_cursor(cur)

    def refresh(self) -> None:
        self.sync_slider()
        self.canvas.refresh()


__all__ = ["SliceCanvas", "ViewPanel", "AXIAL"]
