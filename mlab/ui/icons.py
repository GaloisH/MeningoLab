"""线性 SVG 图标，按当前主题着色。"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3"/><path d="M7 21v-7h10v7"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "prev": '<path d="M15 18l-6-6 6-6"/>',
    "next": '<path d="M9 18l6-6-6-6"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "navigate": '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
    "brush": '<path d="M19.5 3.5a2.1 2.1 0 0 1 3 3L12 17l-3-3z"/><path d="M8.5 14.5C6 14.5 4.5 16 4.5 18c0 1.2-.8 2-2 2.5 3.5 1 8 .5 8.5-3.5"/>',
    "eraser": '<path d="M7 21h13"/><path d="m14.5 3.5 6 6a1.5 1.5 0 0 1 0 2.1L11.1 21H7l-3.6-3.6a1.5 1.5 0 0 1 0-2.1L12.4 3.5a1.5 1.5 0 0 1 2.1 0z"/><path d="m8.5 9.5 7 7"/>',
    "polygon": '<path d="M12 3.5 20 9l-3 10.5H7L4 9z"/><circle cx="12" cy="3.5" r="1.4" fill="currentColor"/><circle cx="20" cy="9" r="1.4" fill="currentColor"/><circle cx="17" cy="19.5" r="1.4" fill="currentColor"/><circle cx="7" cy="19.5" r="1.4" fill="currentColor"/><circle cx="4" cy="9" r="1.4" fill="currentColor"/>',
    "wand": '<path d="m3 21 10-10"/><path d="M15 3v3M15 12v3M9 9h3M18 9h3M17.5 6.5l1.8-1.8M17.5 11.5l1.8 1.8M12.5 6.5l-1.8-1.8"/>',
    "layers": '<path d="m12 2.5 9.5 5-9.5 5-9.5-5z"/><path d="m2.5 12 9.5 5 9.5-5"/><path d="m2.5 16.5 9.5 5 9.5-5"/>',
    "grid": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M14 3v18M14 12h7"/>',
    "square": '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "minimize": '<path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3"/>',
    "moon": '<path d="M20.5 13.5A8.5 8.5 0 1 1 10.5 3.5a6.5 6.5 0 0 0 10 10z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "sparkles": '<path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M19 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6.5 0 10 7 10 7a17.7 17.7 0 0 1-3.2 4.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7c1.9 0 3.6-.6 5-1.5"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
}

_cache: dict[tuple[str, str, int], QIcon] = {}


def _svg(name: str, color: str, opacity: float = 1.0) -> bytes:
    body = _PATHS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'opacity="{opacity}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>').encode()


def pixmap(name: str, color: str, size: int = 20, dpr: float = 2.0, opacity: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, color, opacity)))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 20) -> QIcon:
    key = (name, color, size)
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(pixmap(name, color, size), QIcon.Normal)
        ic.addPixmap(pixmap(name, color, size, opacity=0.35), QIcon.Disabled)
        _cache[key] = ic
    return _cache[key]


APP_ICON_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4f9cff"/><stop offset="1" stop-color="#7b5cff"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>
<path d="M14 46V20l18 16 18-16v26" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="47" cy="47" r="6" fill="#ff6347" stroke="#fff" stroke-width="2.5"/></svg>"""


def render_app_icon(size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 32, 64, 128, 256):
        ic.addPixmap(render_app_icon(s))
    return ic
