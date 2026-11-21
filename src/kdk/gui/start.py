"""Start screen of the GUI: browse for a skin, pick a recent one or drop a folder; texture tools."""

from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QVBoxLayout, QWidget,
)

PATH_ROLE = Qt.ItemDataRole.UserRole + 1
NOTE_ROLE = Qt.ItemDataRole.UserRole + 2
_PAD = 7


class RecentDelegate(QStyledItemDelegate):
    """Two-line painter for a skin folder: name, its parent in gray, a note at the right."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        """Room for both lines and their padding."""
        return QSize(option.rect.width(), 2 * option.fontMetrics.height() + 2 * _PAD + 2)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex):
        """Paint the row background, the bold name, the folder below it and the note."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        path = str(index.data(PATH_ROLE) or "")
        note = str(index.data(NOTE_ROLE) or "")
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        color = opt.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        dim = QColor(color)
        dim.setAlphaF(0.65)
        metrics = opt.fontMetrics
        rect = opt.rect.adjusted(12, _PAD, -12, -_PAD)
        note_width = metrics.horizontalAdvance(note) + 16 if note else 0
        width = rect.width() - note_width
        line = metrics.height()

        painter.save()
        bold = QFont(opt.font)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(color)
        name = QFontMetrics(bold).elidedText(os.path.basename(path), Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(rect.left(), rect.top(), width, line), Qt.AlignmentFlag.AlignVCenter, name)
        painter.setFont(opt.font)
        painter.setPen(dim)
        folder = metrics.elidedText(os.path.dirname(path), Qt.TextElideMode.ElideMiddle, width)
        painter.drawText(QRect(rect.left(), rect.top() + line + 2, width, line), Qt.AlignmentFlag.AlignVCenter,
                         folder)
        if note:
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, note)
        painter.restore()


def fill_recents(view: QListWidget, paths: list[str], current: str):
    """Fill the list with the skin folders, the current one noted, sized to show them all."""
    view.clear()
    for path in paths:
        item = QListWidgetItem()
        item.setData(PATH_ROLE, path)
        item.setData(NOTE_ROLE, "current" if path == current else "")
        item.setToolTip(path)
        view.addItem(item)
    row = view.sizeHintForRow(0) if paths else 0
    view.setFixedHeight(row * len(paths) + 2 * view.frameWidth())


class StartScreen(QWidget):
    """Page for picking a skin: Browse, recent skins, Kodi data checks use, texture tools."""

    browse_requested = Signal()
    skin_picked = Signal(str)
    back_requested = Signal()
    settings_requested = Signal()
    unpack_requested = Signal()
    pack_requested = Signal()

    def __init__(self):
        super().__init__()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        scroll.setWidget(page)
        frame = QVBoxLayout(self)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.addWidget(scroll)
        outer = QHBoxLayout(page)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(16)
        column.addStretch(1)
        body = QWidget()
        body.setMaximumWidth(560)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(16)

        title = QLabel("Validate a skin")
        big = title.font()
        big.setPointSizeF(big.pointSizeF() * 1.5)
        big.setBold(True)
        title.setFont(big)
        intro = QLabel("Pick a skin folder, the one holding addon.xml. kdk checks its includes, variables, "
                       "labels, fonts, images and every window file.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray;")
        stack.addWidget(title)
        stack.addWidget(intro)

        self.drop_target = QToolButton()
        self.drop_target.setText("Choose a skin folder\nor drop one anywhere on this window")
        self.drop_target.setMinimumHeight(170)
        self.drop_target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.drop_target.setStyleSheet(
            "QToolButton { border: 2px dashed palette(mid); border-radius: 10px; font-weight: 600; }"
            " QToolButton:hover { border-color: palette(highlight); }")
        self.drop_target.clicked.connect(self.browse_requested)
        stack.addWidget(self.drop_target)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.browse_btn = QPushButton("Browse for a skin...")
        self.browse_btn.setProperty("primary", True)
        self.browse_btn.clicked.connect(self.browse_requested)
        self.back_btn = QPushButton()
        self.back_btn.clicked.connect(self.back_requested)
        buttons.addWidget(self.browse_btn)
        buttons.addWidget(self.back_btn)
        buttons.addStretch(1)
        stack.addLayout(buttons)

        self.recent_label = QLabel("RECENT SKINS")
        small = self.recent_label.font()
        small.setPointSizeF(small.pointSizeF() * 0.85)
        small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        self.recent_label.setFont(small)
        self.recent_label.setStyleSheet("color: gray;")
        self.recent_list = QListWidget()
        self.recent_list.setItemDelegate(RecentDelegate(self.recent_list))
        self.recent_list.setMouseTracking(True)
        self.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_list.setStyleSheet("QListWidget { border: 1px solid palette(mid); border-radius: 6px; }")
        self.recent_list.itemClicked.connect(lambda item: self.skin_picked.emit(item.data(PATH_ROLE)))
        self.recent_list.itemActivated.connect(lambda item: self.skin_picked.emit(item.data(PATH_ROLE)))
        stack.addWidget(self.recent_label)
        stack.addWidget(self.recent_list)

        textures = QVBoxLayout()
        textures.setSpacing(8)
        heading = QLabel("TEXTURES")
        heading.setFont(small)
        heading.setStyleSheet("color: gray;")
        about = QLabel("Unpack a Textures.xbt back into images, or pack a folder of images into one."
                       " No skin needed.")
        about.setWordWrap(True)
        about.setStyleSheet("color: gray;")
        unpack_btn = QPushButton("Unpack a Textures.xbt...")
        unpack_btn.clicked.connect(self.unpack_requested)
        pack_btn = QPushButton("Pack a folder...")
        pack_btn.clicked.connect(self.pack_requested)
        texture_buttons = QHBoxLayout()
        texture_buttons.setSpacing(8)
        texture_buttons.addWidget(unpack_btn)
        texture_buttons.addWidget(pack_btn)
        texture_buttons.addStretch(1)
        textures.addWidget(heading)
        textures.addWidget(about)
        textures.addLayout(texture_buttons)
        stack.addLayout(textures)

        self.setup = QLabel()
        self.setup.setWordWrap(True)
        self.setup.setStyleSheet("color: gray;")
        self.setup.linkActivated.connect(lambda _href: self.settings_requested.emit())
        stack.addWidget(self.setup)

        column.addWidget(body)
        column.addStretch(2)
        outer.addLayout(column, stretch=4)
        outer.addStretch(1)

    def show_state(self, recents: list[str], current: str, back_to: str, kodi_path: str):
        """Show the recent skins or the big folder target, the way back, and the Kodi data used."""
        has_recents = bool(recents)
        self.drop_target.setVisible(not has_recents)
        self.browse_btn.setVisible(has_recents)
        self.recent_label.setVisible(has_recents)
        self.recent_list.setVisible(has_recents)
        fill_recents(self.recent_list, recents, current)
        self.back_btn.setText(f"Back to {back_to}")
        self.back_btn.setVisible(bool(back_to) and has_recents)
        folder = kodi_path if kodi_path and os.path.isdir(kodi_path) else ""
        kodi = f"Kodi folder: {folder}" if folder else "Kodi folder: not set, so kdk uses its bundled Kodi data"
        self.setup.setText("Kodi release: from each skin's addon.xml, or pick one per skin in the header. "
                           f"{kodi}. <a href='settings'>Settings...</a>")
