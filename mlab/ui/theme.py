"""深色 / 浅色主题。影像画布在两种主题下都保持深色背景，便于阅片。"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    card: str
    card_hover: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    accent_soft: str
    danger: str
    canvas: str = "#0b0d10"
    canvas_text: str = "#d7dde6"


DARK = Theme(
    name="dark", bg="#16191e", panel="#1d2127", card="#242931", card_hover="#2c323b",
    border="#343b46", text="#e6eaf0", muted="#97a1b0", accent="#3d8bfd", accent_text="#ffffff",
    accent_soft="rgba(61,139,253,0.18)", danger="#f0625a",
)
LIGHT = Theme(
    name="light", bg="#eef1f5", panel="#f8f9fb", card="#ffffff", card_hover="#f1f4f8",
    border="#d8dee7", text="#1d2430", muted="#6b7585", accent="#2f6fe0", accent_text="#ffffff",
    accent_soft="rgba(47,111,224,0.12)", danger="#d9433a",
)
THEMES = {"dark": DARK, "light": LIGHT}

# 三个解剖平面的标识色（十字线、视图标题）
PLANE_COLORS = {0: "#f2a33a", 1: "#3fb97c", 2: "#4f9cff"}


def ui_font() -> QFont:
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
                      "Source Han Sans SC", "WenQuanYi Zen Hei", "Segoe UI", "sans-serif"])
    font.setPointSizeF(10)
    return font


def stylesheet(t: Theme) -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t.text}; background: transparent; }}
QMainWindow, QDialog, #CentralArea {{ background: {t.bg}; }}
QToolTip {{ background: {t.card}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px; border-radius: 4px; }}

QMenuBar {{ background: {t.panel}; border-bottom: 1px solid {t.border}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {t.card_hover}; }}
QMenu {{ background: {t.card}; border: 1px solid {t.border}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}

QToolBar {{ background: {t.panel}; border: none; border-bottom: 1px solid {t.border}; padding: 4px 8px; spacing: 4px; }}
QToolBar::separator {{ width: 1px; background: {t.border}; margin: 6px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 5px; }}
QToolButton:hover {{ background: {t.card_hover}; border-color: {t.border}; }}
QToolButton:checked {{ background: {t.accent_soft}; border-color: {t.accent}; }}
QToolButton:disabled {{ color: {t.muted}; }}
QToolBar QToolButton {{ padding: 5px 8px; }}

#SidePanel, #ToolStrip {{ background: {t.panel}; }}
#SidePanel {{ border-left: 1px solid {t.border}; }}
#CasePanel {{ background: {t.panel}; border-right: 1px solid {t.border}; }}
#ToolStrip {{ border-right: 1px solid {t.border}; }}
#ToolStrip QToolButton {{ padding: 8px; margin: 2px 4px; }}

#Card {{ background: {t.card}; border: 1px solid {t.border}; border-radius: 10px; }}
#CardHeader {{ font-weight: 600; padding: 0; text-align: left; border: none; }}
#CardTitle {{ font-weight: 600; font-size: 10.5pt; }}
#Muted, QLabel[muted="true"] {{ color: {t.muted}; }}
#PanelTitle {{ font-size: 11pt; font-weight: 700; }}
#Hint {{ color: {t.muted}; font-size: 9pt; }}

QPushButton {{ background: {t.card_hover}; border: 1px solid {t.border}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:pressed {{ background: {t.accent_soft}; }}
QPushButton:disabled {{ color: {t.muted}; border-color: {t.border}; }}
QPushButton[primary="true"] {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {t.accent}; border-color: {t.text}; }}
QPushButton[primary="true"]:disabled {{ background: {t.card_hover}; color: {t.muted}; border-color: {t.border}; }}
QPushButton[danger="true"]:hover {{ border-color: {t.danger}; color: {t.danger}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t.panel}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px 8px; min-height: 20px;
    selection-background-color: {t.accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {t.card}; border: 1px solid {t.border}; selection-background-color: {t.accent_soft}; selection-color: {t.text}; padding: 2px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t.border}; border-radius: 4px; background: {t.panel}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: none; }}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t.text}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {t.accent}; }}

QProgressBar {{ background: {t.card_hover}; border: none; border-radius: 3px; height: 6px; text-align: center; font-size: 1px; color: transparent; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}

QListView, QTreeView, QTableWidget {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {t.card}; border: none; border-bottom: 1px solid {t.border}; padding: 4px; color: {t.muted}; }}
QTableWidget {{ gridline-color: {t.border}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {t.panel}; border-top: 1px solid {t.border}; color: {t.muted}; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 0 6px; }}
QSplitter::handle {{ background: {t.border}; }}

#ViewPanel {{ background: {t.canvas}; border: 1px solid {t.border}; border-radius: 8px; }}
#ViewPanel[active="true"] {{ border-color: {t.accent}; }}
#ViewHeader {{ background: {t.panel}; border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 1px solid {t.border}; }}
#ViewHeader QLabel {{ background: transparent; }}
#EmptyHint {{ color: {t.muted}; font-size: 12pt; }}
"""


def apply_theme(app: QApplication, t: Theme) -> None:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t.bg))
    pal.setColor(QPalette.WindowText, QColor(t.text))
    pal.setColor(QPalette.Base, QColor(t.panel))
    pal.setColor(QPalette.AlternateBase, QColor(t.card))
    pal.setColor(QPalette.Text, QColor(t.text))
    pal.setColor(QPalette.Button, QColor(t.card))
    pal.setColor(QPalette.ButtonText, QColor(t.text))
    pal.setColor(QPalette.Highlight, QColor(t.accent))
    pal.setColor(QPalette.HighlightedText, QColor(t.accent_text))
    pal.setColor(QPalette.ToolTipBase, QColor(t.card))
    pal.setColor(QPalette.ToolTipText, QColor(t.text))
    pal.setColor(QPalette.PlaceholderText, QColor(t.muted))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
