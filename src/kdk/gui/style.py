"""Look of the kdk GUI: the shared control style and height, and the severity colors."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QWidget

CONTROL_STYLE = (
    "QPushButton { padding: 0 14px; border: 1px solid palette(mid); border-radius: 4px; background: palette(button); }"
    " QPushButton:hover { border-color: palette(highlight); }"
    " QPushButton:pressed { background: palette(mid); }"
    " QPushButton:disabled { color: palette(mid); }"
    " QPushButton[primary=\"true\"] { background: #1f6fd1; color: white; border-color: #2b7de0; }"
    " QPushButton[primary=\"true\"]:hover { background: #2f80e4; }"
    " QPushButton[primary=\"true\"]:disabled { background: palette(button); color: palette(mid);"
    " border-color: palette(mid); }"
    " QLineEdit, QComboBox { padding: 0 8px; border: 1px solid palette(mid); border-radius: 4px;"
    " background: palette(base); }"
    " QLineEdit:focus, QComboBox:focus { border-color: palette(highlight); }"
    " QComboBox QLineEdit { padding: 0; border: none; background: transparent; }"
    " QComboBoxPrivateContainer { border: none; background: transparent; }"
    " QComboBox QAbstractItemView { padding: 4px; border: 1px solid palette(mid); border-radius: 4px;"
    " background: palette(base); outline: none; }"
    " QComboBox QAbstractItemView::item { padding: 4px 8px; border-radius: 3px; color: palette(text); }"
    " QComboBox QAbstractItemView::item:selected { background: palette(highlight);"
    " color: palette(highlighted-text); }"
    " QToolButton#skinButton, QToolButton#releaseButton { padding: 0 10px; border: 1px solid palette(mid);"
    " border-radius: 4px; background: palette(button); }"
    " QToolButton#skinButton:hover, QToolButton#releaseButton:hover { border-color: palette(highlight); }"
    " QToolButton#skinButton { padding-right: 34px; font-weight: 600; }"
    " QToolButton#skinButton::menu-button { width: 26px; border: none; border-left: 1px solid palette(mid); }"
    " QToolButton#releaseButton { padding-right: 26px; }"
    " QToolButton#releaseButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center;"
    " right: 9px; }"
    " QPushButton#toolsButton::menu-indicator { image: none; width: 0; }"
)
_ARROW_STYLE = (
    " QComboBox::drop-down { width: 22px; border: none; background: transparent; }"
    ' QComboBox::down-arrow { image: url("%(arrow)s"); width: 10px; height: 10px; }'
    ' QToolButton#skinButton::menu-arrow, QToolButton#releaseButton::menu-indicator { image: url("%(arrow)s");'
    " width: 10px; height: 10px; }"
)
TOGGLE_STYLE = (
    "QToolButton { padding: 0 12px 0 9px; border: 1px solid palette(mid); border-radius: %dpx; }"
    " QToolButton:hover { border-color: palette(highlight); }"
    " QToolButton:checked { background: rgba(31, 111, 209, 0.28); border-color: rgba(31, 111, 209, 0.8); }"
    " QToolButton:disabled { color: gray; }"
    " QToolButton:checked:disabled { background: transparent; border-color: palette(mid); }"
)
_SEVERITY_COLORS = {
    "error": (("#45201f", "#ffa49e"), ("#fbe1df", "#a3241d")),
    "warning": (("#3d3115", "#f6cd72"), ("#fdf0cf", "#7a5200")),
    "muted": (("#2c3036", "#a3a9b3"), ("#e6e7ea", "#555b63")),
}


def control_style(widget: QWidget) -> str:
    """Stylesheet for buttons and boxes, with the bundled combo arrow for the palette."""
    name = "arrow-for-dark.png" if is_dark(widget) else "arrow-for-light.png"
    try:
        arrow = files("kdk.data").joinpath("gui").joinpath(name)
    except ModuleNotFoundError:
        return CONTROL_STYLE
    if not arrow.is_file():
        return CONTROL_STYLE
    return CONTROL_STYLE + _ARROW_STYLE % {"arrow": Path(str(arrow)).as_posix()}


def round_popups(root: QWidget):
    """Round every combo list in the window: frameless see-through popup, styled items."""
    for combo in root.findChildren(QComboBox):
        combo.setItemDelegate(QStyledItemDelegate(combo))
        popup = combo.view().window()
        popup.setWindowFlags(popup.windowFlags() | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def control_height(widget: QWidget) -> int:
    """Height every button, box and toggle shares, from the widget's font."""
    return widget.fontMetrics().height() + 10


def is_dark(widget: QWidget) -> bool:
    """True when the widget's palette has a dark window color."""
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def severity_colors(kind: str, dark: bool) -> tuple[str, str]:
    """Background and text color of an error, warning or muted pill, for a dark or light palette."""
    dark_pair, light_pair = _SEVERITY_COLORS[kind]
    return dark_pair if dark else light_pair
