"""Colours measured on CapCut 9.6 screenshots (1920x1080, dark theme) + the Qt style sheet."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont


class C:
    # editor
    bg = "#141414"          # window / gaps between panels
    panel = "#262626"       # panel body, timeline body
    header = "#303030"      # panel header strips
    raised = "#3B3B3B"      # drop zone, side buttons
    track = "#2A2A2A"       # empty-track strip
    button = "#4F4F4F"      # secondary buttons (Partager, Modifier)
    menu_btn = "#343337"
    accent = "#00C1CD"      # Exporter, selected tab, links
    text = "#E1E1E1"
    muted = "#8C8C8C"
    line = "#3A3A3A"
    warn = "#F2C921"        # yellow tooltip bubble
    danger = "#FF5C5C"
    # clips (not measured: no clips on the screenshots)
    clip_video = "#3C4A63"
    clip_audio = "#1D6D73"
    clip_text = "#6B5BA8"
    clip_other = "#7A5C2E"
    select = "#FFFFFF"
    playhead = "#E1E1E1"
    # home screen
    h_bg = "#041214"
    h_nav = "#112326"
    h_user = "#0B2125"
    h_card = "#0F1A1C"
    h_tile = "#162628"
    h_line = "#233031"
    h_input = "#175B68"
    h_a1 = "#60D5E1"
    h_a2 = "#19B1CF"
    h_muted = "#8AA0A3"


FONT_FAMILY = "Segoe UI"


def app_font(px: int = 12) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def qcolor(h: str, alpha: float = 1.0) -> QColor:
    c = QColor(h)
    c.setAlphaF(alpha)
    return c


def stylesheet() -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}", "Inter", "Noto Sans", "DejaVu Sans"; font-size: 12px; color: {C.text}; outline: 0; }}
QMainWindow, QDialog {{ background: {C.bg}; }}
QToolTip {{ background: {C.header}; color: {C.text}; border: 1px solid {C.line}; padding: 4px 6px; }}
QLabel {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #4A4A4A; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #4A4A4A; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QMenu {{ background: {C.header}; border: 1px solid {C.line}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C.raised}; }}
QMenu::item:disabled {{ color: #666; }}
QMenu::separator {{ height: 1px; background: {C.line}; margin: 4px 6px; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {C.raised}; border: 1px solid transparent; border-radius: 4px; padding: 4px 8px; selection-background-color: {C.accent}; }}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {C.accent}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {C.header}; border: 1px solid {C.line}; selection-background-color: {C.raised}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}
QSlider::groove:horizontal {{ height: 3px; background: #4A4A4A; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {C.accent}; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: {C.text}; width: 10px; height: 10px; margin: -4px 0; border-radius: 5px; }}
QPushButton {{ background: {C.button}; border: none; border-radius: 4px; padding: 5px 14px; }}
QPushButton:hover {{ background: #5C5C5C; }}
QPushButton[accent="true"] {{ background: {C.accent}; color: #04282B; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: #20D2DD; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px; background: {C.raised}; }}
QCheckBox::indicator:checked {{ background: {C.accent}; }}
QProgressBar {{ background: {C.raised}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {C.accent}; border-radius: 3px; }}
"""
