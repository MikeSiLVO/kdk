"""PySide6-based skin validator GUI."""

from __future__ import annotations

import base64
import html
import os
import sys
import threading
from datetime import datetime
from typing import Callable

from PySide6.QtCore import (
    QByteArray, QEvent, QMimeData, QModelIndex, QObject, QPoint, QPointF, QRectF, QSize, QThread, QTimer, QUrl, Qt,
    Signal,
)
from PySide6.QtGui import (
    QActionGroup, QCloseEvent, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QFontMetrics,
    QGuiApplication, QIcon, QKeySequence, QPainter, QPaintEvent, QPalette, QShortcut, QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
    QSplitterHandle, QStackedWidget, QStyle, QStyledItemDelegate, QStyleFactory, QStyleOptionViewItem, QToolButton,
    QTreeView, QVBoxLayout, QWidget, QWidgetAction,
)

from kdk.gui import issues, skins
from kdk.gui.detail import DetailPane
from kdk.gui.icons import icon
from kdk.gui.progress import RunCard
from kdk.gui.settings import SettingsDialog
from kdk.gui.start import PATH_ROLE, RecentDelegate, StartScreen, fill_recents
from kdk.gui.textures import TextureTools
from kdk.gui.style import TOGGLE_STYLE, control_height, control_style, is_dark, round_popups, severity_colors
from kdk.output.payload import relative

ROW_ROLE = Qt.ItemDataRole.UserRole + 1
GROUP_ROLE = Qt.ItemDataRole.UserRole + 2
HEADING_ROLE = Qt.ItemDataRole.UserRole + 3
COLUMN_NAMES = {"severity": "Severity", "file": "File", "line": "Line", "rule": "Rule", "include": "Include",
                "message": "Message"}
COLUMN_WIDTHS = {"severity": 48, "file": 240, "line": 90, "rule": 200, "include": 180}
DEFAULT_HIDDEN: tuple[str, ...] = ("rule", "include")
HEADING_COLUMN = issues.COLUMNS[0]
DEFAULT_SHOWN: tuple[str, ...] = ("error", "warning")
NAMED_BY_GROUP = ("file", "rule")
BUCKET_LABELS = {"error": "Errors", "warning": "Warnings", "include": "Include warnings", "muted": "Muted"}
BUCKET_TIPS = {
    "error": "Show errors",
    "warning": "Show warnings",
    "include": "Show warnings that come from include content",
    "muted": "Show rows a kdk-ignore comment mutes",
}
GROUP_LABELS = {"category": "Category", "file": "File", "rule": "Rule", "severity": "Severity",
                "none": "Nothing (flat)"}
SPLIT_DEFAULTS = {"bottom": [560, 230], "right": [800, 420]}
RECENT_LIMIT = 8


def _plural(count: int, word: str) -> str:
    """Count and word, the word plural unless the count is one."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def _count_parts(errors: int, warnings: int, muted: int) -> list[tuple[str, str]]:
    """Text and severity of each nonzero count, most severe first."""
    parts = ((errors, _plural(errors, "error"), "error"), (warnings, _plural(warnings, "warning"), "warning"),
             (muted, f"{muted} muted", "muted"))
    return [(text, kind) for count, text, kind in parts if count]


def _decode(blob) -> QByteArray | None:
    """Decode saved Qt state from its base64 text; None when missing or unreadable."""
    if not isinstance(blob, str) or not blob:
        return None
    try:
        return QByteArray(base64.b64decode(blob))
    except ValueError:
        return None


def _encode(state: QByteArray) -> str:
    """Encode a Qt state as base64 text for the JSON config."""
    return base64.b64encode(state.data()).decode("ascii")


class _Banner(QFrame):
    """Dismissible strip above the filters, tinted by the RGB triple it is given."""

    closed = Signal()

    def __init__(self, rgb: str):
        super().__init__()
        self.setObjectName("banner")
        self.setStyleSheet(f"#banner {{ background: rgba({rgb}, 0.16); border: 1px solid rgba({rgb}, 0.55);"
                           " border-radius: 4px; }")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 5, 5, 5)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._row.addWidget(self.text, stretch=1)
        self.close_button = QToolButton()
        self.close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("Dismiss")
        self.close_button.clicked.connect(self._dismiss)
        self._row.addWidget(self.close_button)
        self.setVisible(False)

    def add_button(self, text: str, slot):
        """Add a button before the close button, calling the slot when clicked."""
        button = QPushButton(text)
        button.clicked.connect(slot)
        self._row.insertWidget(self._row.count() - 1, button)

    def _dismiss(self):
        """Dismiss the banner and say it was closed."""
        self.setVisible(False)
        self.closed.emit()


class _ElidedLabel(QLabel):
    """Label that cuts its text short with an ellipsis instead of widening its row."""

    def minimumSizeHint(self) -> QSize:
        """Height only, leaving the row free to take all of its width."""
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent):
        """Paint the text cut short at the right to fit the label."""
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width())
        self.style().drawItemText(QPainter(self), self.contentsRect(), int(self.alignment()), self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


class _Handle(QSplitterHandle):
    """Splitter bar drawn as a strip with edge lines and a grip between tree and detail pane."""

    def paintEvent(self, event: QPaintEvent):
        """Paint the strip, its two edge lines and the grip in the middle."""
        palette = self.palette()
        rect = QRectF(self.rect())
        painter = QPainter(self)
        painter.fillRect(rect, palette.color(QPalette.ColorRole.Window))
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        center = rect.center()
        if self.orientation() == Qt.Orientation.Vertical:
            painter.drawLine(rect.topLeft(), rect.topRight())
            painter.drawLine(rect.bottomLeft() - QPointF(0, 1), rect.bottomRight() - QPointF(0, 1))
            grip = QRectF(center.x() - 20, center.y() - 1, 40, 2)
        else:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
            painter.drawLine(rect.topRight() - QPointF(1, 0), rect.bottomRight() - QPointF(1, 0))
            grip = QRectF(center.x() - 1, center.y() - 20, 2, 40)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawRoundedRect(grip, 1, 1)
        painter.end()


class _Splitter(QSplitter):
    """Splitter whose handles are drawn as a strip with a grip."""

    def createHandle(self) -> QSplitterHandle:
        """Create a handle drawn as a strip with a grip."""
        return _Handle(self.orientation(), self)


class _HeadingDelegate(QStyledItemDelegate):
    """Painter for group headings: bold name, count pill, then counts colored by severity."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """Paint a heading, leaving every other cell to the default painter."""
        heading = index.data(HEADING_ROLE)
        if not heading:
            super().paint(painter, option, index)
            return
        name, errors, warnings, muted, total_only = heading
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        text_color = opt.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        dark = is_dark(widget) if widget else False
        rect = QRectF(opt.rect.adjusted(6, 0, -6, 0))
        middle = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bold = QFont(opt.font)
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        label = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, max(int(rect.width()) // 2, 80))
        painter.setFont(bold)
        painter.setPen(text_color)
        painter.drawText(rect, middle, label)
        x = rect.left() + metrics.horizontalAdvance(label) + 10

        small = QFont(opt.font)
        small.setPointSizeF(small.pointSizeF() - 1.5)
        small_metrics = QFontMetrics(small)
        count = str(errors + warnings + muted)
        pill = QRectF(x, rect.center().y() - small_metrics.height() / 2 - 1,
                      small_metrics.horizontalAdvance(count) + 14, small_metrics.height() + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(127, 127, 127, 70))
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.setFont(small)
        painter.setPen(text_color)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, count)
        x = pill.right() + 12

        if not total_only:
            painter.setFont(opt.font)
            for text, kind in _count_parts(errors, warnings, muted):
                painter.setPen(QColor(severity_colors(kind, dark)[1]))
                painter.drawText(QRectF(x, rect.top(), max(rect.right() - x, 0), rect.height()), middle, text)
                x += opt.fontMetrics.horizontalAdvance(text) + 14
        painter.restore()


class _ValidationWorker(QObject):
    """Worker running `validate_skin` on its own thread; `cancel` stops it at its next report."""

    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, skin_path: str, release: str):
        super().__init__()
        self._skin_path = skin_path
        self._release = release
        self.cancel = threading.Event()

    def run(self):
        """Validate the skin at its release; send the result, a cancel, or the error's text."""
        from kdk.core import Cancelled, validate_skin
        try:
            result = validate_skin(
                self._skin_path,
                config_overrides={"kodi_release": self._release},
                progress_callback=lambda s, t, m: self.progress.emit(s, t, m),
                cancel=self.cancel,
            )
            self.finished.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(str(e))


class KdkApp(QMainWindow):
    """Main validator window."""

    def __init__(self):
        super().__init__()
        from kdk.config import load_config

        self.setWindowTitle("KDK - Kodi Skin Validator")
        self.resize(1200, 800)
        config = load_config()
        self._gui: dict = dict(config.get("gui") or {})
        self._editor: str = config.get("editor", "") or ""
        self._result: dict | None = None
        self._skin = ""
        self._result_skin = ""
        self._import_line = 0
        self._after_run: Callable[[], None] | None = None
        self._from_start = False
        self._shown: set[str] = set(self._gui.get("shown", DEFAULT_SHOWN)) & set(issues.BUCKETS)
        self._hidden_columns: set[str] = (set(self._gui.get("hidden_columns", DEFAULT_HIDDEN))
                                          & set(issues.COLUMNS) - {HEADING_COLUMN})
        sort_column = self._gui.get("sort_column")
        self._sort_column: str | None = sort_column if sort_column in issues.COLUMNS else None
        self._sort_descending = bool(self._gui.get("sort_descending", False))
        self._collapsed: set[tuple[str, str]] = set()
        self._selected_key: tuple | None = None
        self._rebuilding = False
        self._pane = ""
        self._worker_thread: QThread | None = None
        self._worker: _ValidationWorker | None = None
        self._lookup = None
        self._update_timer: QTimer | None = None
        self._update_version = ""

        self._build_ui()
        self._restore_state()
        self._start_update_check()

    def _build_ui(self):
        """Build window: toolbar, banners, start and results pages, progress card, status bar."""
        self.setStyleSheet(control_style(self))
        self._height = control_height(self)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 4)
        root.setSpacing(8)
        self._build_toolbar(root)
        self._build_banners(root)
        self.start = StartScreen()
        self.start.browse_requested.connect(self._browse_skin)
        self.start.skin_picked.connect(self._open_skin)
        self.start.back_requested.connect(self._show_results)
        self.start.settings_requested.connect(self._open_settings)
        self.start.unpack_requested.connect(lambda: self._texture_tool(unpack=True))
        self.start.pack_requested.connect(lambda: self._texture_tool(unpack=False))
        self.results = QWidget()
        page = QVBoxLayout(self.results)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(8)
        self._build_filters(page)
        self._build_split(page)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.start)
        self.pages.addWidget(self.results)
        root.addWidget(self.pages, stretch=1)
        self.run_card = RunCard(self.pages, central)
        self.run_card.cancel_requested.connect(self._cancel_job)
        self.run_card.pick_requested.connect(self._go_start)
        self.textures = TextureTools(self, self.run_card, lambda: self.pages.currentWidget() is self.start)
        self._build_status()
        controls: list[QWidget] = [self.skin_btn, self.release_btn, self.search_edit, self.group_combo,
                                   *self._toggles.values()]
        controls += self.findChildren(QPushButton)
        controls += [banner.close_button for banner in (self.update_banner, self.notice_banner)]
        for widget in controls:
            widget.setFixedHeight(self._height)
        round_popups(self)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self).activated.connect(self._run_validation)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self).activated.connect(self._focus_search)

    def _build_toolbar(self, root: QVBoxLayout):
        """Build row: skin, release, import pill, Validate, summary, Report, Tools, Settings."""
        row = QHBoxLayout()
        self.skin_btn = QToolButton()
        self.skin_btn.setObjectName("skinButton")
        self.skin_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.skin_btn.clicked.connect(self._go_start)
        self.skin_menu = QMenu(self.skin_btn)
        self.skin_list = QListWidget()
        self.skin_list.setItemDelegate(RecentDelegate(self.skin_list))
        self.skin_list.setFrameShape(QFrame.Shape.NoFrame)
        self.skin_list.setMinimumWidth(380)
        self.skin_list.setMouseTracking(True)
        self.skin_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.skin_list.itemClicked.connect(self._pick_from_menu)
        self.skin_list.itemActivated.connect(self._pick_from_menu)
        listed = QWidgetAction(self.skin_menu)
        listed.setDefaultWidget(self.skin_list)
        self.skin_menu.addAction(listed)
        self.skin_menu.addSeparator()
        self.skin_menu.addAction("Browse for a skin...", self._browse_skin)
        self.skin_menu.addAction("Start screen", self._go_start)
        self.skin_menu.aboutToShow.connect(self._fill_skin_menu)
        self.skin_btn.setMenu(self.skin_menu)
        row.addWidget(self.skin_btn)

        self.release_btn = QToolButton()
        self.release_btn.setObjectName("releaseButton")
        self.release_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.release_btn.setToolTip("Kodi release the checks of this skin run against")
        self.release_menu = QMenu(self.release_btn)
        self.release_menu.aboutToShow.connect(self._fill_release_menu)
        self.release_btn.setMenu(self.release_menu)
        row.addWidget(self.release_btn)

        self.gui_pill = QPushButton()
        self.gui_pill.setIcon(icon("warning"))
        self.gui_pill.clicked.connect(self._open_gui_import)
        background, color = severity_colors("warning", is_dark(self))
        self.gui_pill.setStyleSheet(f"QPushButton {{ background: {background}; color: {color}; border: 1px solid"
                                    f" {color}; border-radius: {self._height // 2}px; padding: 0 12px 0 9px; }}")
        row.addWidget(self.gui_pill)

        self.run_btn = QPushButton("Validate")
        self.run_btn.setIcon(icon("play"))
        self.run_btn.setToolTip("Validate (F5)")
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(self._run_validation)
        row.addWidget(self.run_btn)
        self.run_summary = _ElidedLabel()
        self.run_summary.setStyleSheet("color: gray;")
        row.addSpacing(6)
        row.addWidget(self.run_summary)
        row.addStretch(1)
        self.report_btn = QPushButton("Save Report...")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._save_report)
        row.addWidget(self.report_btn)
        tools_btn = QPushButton()
        tools_btn.setObjectName("toolsButton")
        tools_btn.setIcon(icon("wrench-for-dark" if is_dark(self) else "wrench-for-light"))
        tools_btn.setToolTip("Tools")
        tools_btn.setAccessibleName("Tools")
        tools_btn.setFixedWidth(self._height + 4)
        tools_menu = QMenu(tools_btn)
        tools_menu.addAction("Unpack textures...", lambda: self._texture_tool(unpack=True))
        tools_menu.addAction("Pack textures...", lambda: self._texture_tool(unpack=False))
        tools_btn.setMenu(tools_menu)
        row.addWidget(tools_btn)
        settings_btn = QPushButton()
        settings_btn.setIcon(icon("gear-for-dark" if is_dark(self) else "gear-for-light"))
        settings_btn.setToolTip("Settings")
        settings_btn.setAccessibleName("Settings")
        settings_btn.setFixedWidth(self._height + 4)
        settings_btn.clicked.connect(self._open_settings)
        row.addWidget(settings_btn)
        root.addLayout(row)

    def _build_banners(self, root: QVBoxLayout):
        """Add the update banner and the run notices banner, both hidden until needed."""
        self.update_banner = _Banner("31, 111, 209")
        self.update_banner.add_button("Download" if getattr(sys, "frozen", False) else "What's new",
                                      self._open_releases)
        self.update_banner.add_button("Skip this version", self._skip_update)
        self.update_banner.closed.connect(lambda: self.update_badge.setVisible(bool(self._update_version)))
        root.addWidget(self.update_banner)
        self.notice_banner = _Banner("233, 177, 59")
        root.addWidget(self.notice_banner)

    def _build_filters(self, root: QVBoxLayout):
        """Add the search box, the filter toggles, Group by and Merge repeats."""
        row = QHBoxLayout()
        row.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter issues (Ctrl+F)")
        self.search_edit.setToolTip("Matches messages, file paths, rule ids, subjects and include names")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(240)
        self.search_edit.setMaximumWidth(440)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._refresh_tree)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        row.addWidget(self.search_edit, stretch=1)

        self._toggles: dict[str, QToolButton] = {}
        for name in issues.BUCKETS:
            button = QToolButton()
            button.setCheckable(True)
            button.setChecked(name in self._shown)
            button.setIcon(icon(name))
            button.setText(BUCKET_LABELS[name])
            button.setToolTip(BUCKET_TIPS[name])
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setStyleSheet(TOGGLE_STYLE % (self._height // 2))
            button.toggled.connect(lambda on, n=name: self._on_toggle(n, on))
            row.addWidget(button)
            self._toggles[name] = button

        row.addSpacing(12)
        row.addWidget(QLabel("Group by"))
        self.group_combo = QComboBox()
        for key in issues.GROUPINGS:
            self.group_combo.addItem(GROUP_LABELS[key], key)
        self.group_combo.setCurrentIndex(max(self.group_combo.findData(self._gui.get("group_by", "category")), 0))
        self.group_combo.currentIndexChanged.connect(self._on_grouping_changed)
        row.addWidget(self.group_combo)
        self.merge_cb = QCheckBox("Merge repeats")
        self.merge_cb.setToolTip("One row per file and message, listing every line")
        self.merge_cb.setChecked(bool(self._gui.get("merge_repeats", False)))
        self.merge_cb.toggled.connect(self._refresh_tree)
        row.addWidget(self.merge_cb)
        row.addStretch(1)
        root.addLayout(row)

    def _build_split(self, root: QVBoxLayout):
        """Add the issue tree and the detail pane, split by a draggable handle."""
        self.model = QStandardItemModel(0, len(issues.COLUMNS), self)
        self.model.setHorizontalHeaderLabels(["" if c == "severity" else COLUMN_NAMES[c] for c in issues.COLUMNS])
        tree = self.tree = QTreeView()
        tree.setModel(self.model)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setIndentation(18)
        tree.setStyleSheet("QTreeView::item { padding: 3px 0; }")
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._row_menu)
        tree.doubleClicked.connect(self._on_double_clicked)
        tree.expanded.connect(lambda index: self._on_group_toggled(index, False))
        tree.collapsed.connect(lambda index: self._on_group_toggled(index, True))
        tree.selectionModel().currentChanged.connect(self._on_current_changed)
        for key, slot in ((QKeySequence(QKeySequence.StandardKey.Copy), self._copy_message),
                          (QKeySequence(Qt.Key.Key_Return), self._activate),
                          (QKeySequence(Qt.Key.Key_Enter), self._activate)):
            shortcut = QShortcut(key, tree)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(slot)

        header = tree.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        header.setToolTip("Click to sort, right-click to pick columns")
        header.sectionClicked.connect(self._on_header_clicked)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_menu)
        self._default_widths()

        tree.setFrameShape(QFrame.Shape.NoFrame)
        tree.setItemDelegate(_HeadingDelegate(tree))
        self.detail = DetailPane()
        self.detail.open_requested.connect(self._open)
        self.detail.copy_requested.connect(self._copy)
        self.splitter = _Splitter()
        self.splitter.setHandleWidth(7)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(tree)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 1)
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setStyleSheet("#panel { border: 1px solid palette(mid); border-radius: 4px; }")
        box = QVBoxLayout(panel)
        box.setContentsMargins(1, 1, 1, 1)
        box.addWidget(self.splitter)
        root.addWidget(panel, stretch=1)

    def _build_status(self):
        """Fill the status bar: summary left, update badge and version right."""
        from kdk import __version__

        bar = self.statusBar()
        self.summary_label = QLabel("Ready")
        bar.addWidget(self.summary_label, 1)
        self.update_badge = QLabel()
        self.update_badge.setOpenExternalLinks(True)
        self.update_badge.setVisible(False)
        bar.addPermanentWidget(self.update_badge)
        version = QToolButton()
        version.setText(f"v{__version__}")
        version.setAutoRaise(True)
        version.setToolTip("About kdk")
        version.setStyleSheet("color: gray; padding: 0 6px;")
        version.clicked.connect(self._show_about)
        bar.addPermanentWidget(version)

    def _restore_state(self):
        """Restore size, columns, pane and sort from the user config, then show the start screen."""
        geometry = _decode(self._gui.get("geometry"))
        if geometry is not None:
            self.restoreGeometry(geometry)
        header_state = _decode(self._gui.get("header"))
        if header_state is not None:
            self.tree.header().restoreState(header_state)
        self._apply_columns()
        self._apply_pane(self._gui.get("detail_pane", "bottom"))
        self._show_sort()
        self._show_start()

    def closeEvent(self, event: QCloseEvent):
        """Remember window, columns, filters; mid-run or job, hide, stop it, quit once it stops."""
        self._remember_split()
        header = self.tree.header()
        for n, column in enumerate(issues.COLUMNS):
            header.setSectionHidden(n, column in self._hidden_columns)
        self._gui.update({
            "geometry": _encode(self.saveGeometry()),
            "header": _encode(header.saveState()),
            "detail_pane": self._pane,
            "hidden_columns": sorted(self._hidden_columns),
            "shown": sorted(self._shown),
            "group_by": self._grouping(),
            "merge_repeats": self.merge_cb.isChecked(),
            "sort_column": self._sort_column or "",
            "sort_descending": self._sort_descending,
        })
        self._save_gui()
        if self._worker_thread and self._worker_thread.isRunning():
            self._after_run = None
            if self._worker:
                self._worker.finished.disconnect(self._on_finished)
                self._worker.failed.disconnect(self._on_failed)
                self._worker.cancelled.disconnect(self._on_cancelled)
                self._worker.cancel.set()
            self.hide()
            self._worker_thread.finished.connect(QApplication.quit)
            event.ignore()
            return
        texture_thread = self.textures.stop_for_close()
        if texture_thread is not None:
            self.hide()
            texture_thread.finished.connect(QApplication.quit)
            event.ignore()
            return
        super().closeEvent(event)

    def _save_gui(self):
        """Save the GUI state to the user config, skipping a config that cannot be written."""
        from kdk.config import save_user_config
        try:
            save_user_config("gui", self._gui)
        except OSError:
            pass

    def _apply_pane(self, pane: str):
        """Apply the pane position, below or right of the tree, at the sizes last used there."""
        if self._pane:
            self._remember_split()
        self._pane = pane if pane in SPLIT_DEFAULTS else "bottom"
        below = self._pane == "bottom"
        self.splitter.setOrientation(Qt.Orientation.Vertical if below else Qt.Orientation.Horizontal)
        self.detail.set_below(below)
        sizes = (self._gui.get("detail_sizes") or {}).get(self._pane)
        if not (isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(s, int) and s > 0 for s in sizes)):
            sizes = SPLIT_DEFAULTS[self._pane]
        self.splitter.setSizes(sizes)

    def _remember_split(self):
        """Remember the splitter sizes for where the detail pane sits now."""
        self._gui.setdefault("detail_sizes", {})[self._pane] = self.splitter.sizes()

    def _recents(self) -> list[str]:
        """Skin folders validated last, newest first, each once in the system's path form."""
        paths = [os.path.normpath(p) for p in self._gui.get("recent_skins") or [] if isinstance(p, str) and p]
        return list(dict.fromkeys(paths))

    def _remember_skin(self, path: str):
        """Remember the skin at the top of the recent list and save the GUI state."""
        self._gui["recent_skins"] = ([path] + [p for p in self._recents() if p != path])[:RECENT_LIMIT]
        self._save_gui()

    def _browse_skin(self):
        """Pick a skin folder, starting beside the last one picked, and validate it."""
        start = self._gui.get("last_skin_parent") or ""
        if not os.path.isdir(start):
            start = os.path.dirname(self._skin) if os.path.isdir(self._skin) else ""
        path = QFileDialog.getExistingDirectory(self, "Select Kodi skin folder", start)
        if path:
            self._gui["last_skin_parent"] = os.path.dirname(path)
            self._open_skin(path)

    def _open_skin(self, path: str):
        """Open picked or dropped skin and validate it, stopping a run; not during a texture job."""
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            QMessageBox.critical(self, "Invalid path", f"Not a directory: {path}")
            return
        if not os.path.isfile(os.path.join(path, "addon.xml")):
            QMessageBox.critical(self, "Not a skin", f"No addon.xml found in: {path}")
            return
        if self.textures.busy():
            self.statusBar().showMessage("Wait for the texture job to finish, or cancel it", 5000)
            return
        if self._worker:
            self._cancel_run(lambda: self._open_skin(path))
            return
        self._skin = path
        self._run_validation()

    def _media_dir(self) -> str:
        """Media folder of the open or shown skin, where texture dialogs start; else the skin."""
        skin = self._skin or self._result_skin
        media = os.path.join(skin, "media") if skin else ""
        return media if os.path.isdir(media) else skin

    def _texture_tool(self, unpack: bool):
        """Start an unpack or pack from the skin's media folder, unless a validation runs."""
        if self._worker:
            self.statusBar().showMessage("Wait for the validation to finish, or cancel it", 5000)
        elif unpack:
            self.textures.unpack(self._media_dir())
        else:
            self.textures.pack(self._media_dir())

    def _pick_from_menu(self, item: QListWidgetItem):
        """Close the skin menu and validate the skin picked in its list."""
        self.skin_menu.close()
        self._open_skin(item.data(PATH_ROLE))

    def _fill_skin_menu(self):
        """Fill the skin menu with recent skins, the open one noted, ready for the arrow keys."""
        fill_recents(self.skin_list, self._recents(), self._skin)
        QTimer.singleShot(0, self.skin_list.setFocus)

    def _release_choice(self) -> str:
        """Release picked for the open skin, empty for the one its addon.xml implies."""
        choice = (self._gui.get("releases") or {}).get(self._skin, "")
        return choice if choice in skins.RELEASES else ""

    def _fill_release_menu(self):
        """Fill the menu with the xbmc.gui import, then releases with the skin's pick checked."""
        menu = self.release_menu
        menu.clear()
        version, _line = skins.gui_import(self._skin)
        heading = menu.addAction(f"addon.xml imports xbmc.gui {version}" if version
                                 else "addon.xml has no xbmc.gui import")
        heading.setEnabled(False)
        menu.addSeparator()
        group = QActionGroup(menu)
        choice = self._release_choice()
        implied = skins.implied_release(version).capitalize()
        entries = [("", f"From addon.xml (checks as {implied})")] + [(r, r.capitalize()) for r in skins.RELEASES]
        for value, label in entries:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == choice)
            action.setActionGroup(group)
            action.triggered.connect(lambda _on=False, v=value: self._choose_release(v))

    def _choose_release(self, release: str):
        """Choose skin's release, empty for addon.xml's; save, stop any run, validate again."""
        releases = self._gui.setdefault("releases", {})
        if release:
            releases[self._skin] = release
        else:
            releases.pop(self._skin, None)
        self._save_gui()
        if self._worker:
            self._cancel_run(lambda path=self._skin: self._open_skin(path))
        else:
            self._run_validation()

    def _settle_release(self):
        """Settle the open skin's release, dropping a pick addon.xml now implies itself."""
        releases = self._gui.get("releases") or {}
        choice = releases.get(self._skin)
        if choice and choice == skins.implied_release(skins.gui_import(self._skin)[0]):
            del releases[self._skin]
            self._save_gui()

    def _refresh_header(self):
        """Refresh the results-page header: skin, release, any import the release won't load."""
        on_skin = bool(self._skin) and self.pages.currentWidget() is self.results
        for widget in (self.skin_btn, self.release_btn, self.run_btn, self.run_summary, self.report_btn):
            widget.setVisible(on_skin)
        version, self._import_line = skins.gui_import(self._skin) if on_skin else ("", 0)
        choice = self._release_choice()
        release = choice or skins.implied_release(version)
        need = skins.needed_import(version, release)
        self.gui_pill.setVisible(on_skin and bool(need))
        if not on_skin:
            return
        name = release.capitalize()
        self.skin_btn.setText(os.path.basename(self._skin))
        self.skin_btn.setToolTip(f"{self._skin}\nClick for the start screen, or the arrow for recent skins")
        self.release_btn.setText(f"Kodi {name}" if choice else f"Kodi {name} (auto)")
        self.gui_pill.setText(f"xbmc.gui {version}: {name} will not load it")
        self.gui_pill.setToolTip(f"addon.xml imports xbmc.gui {version}. Set it to {need} for {name}."
                                 " Click to open addon.xml at the import.")

    def _open_gui_import(self):
        """Open the open skin's addon.xml at its xbmc.gui import."""
        self._open(os.path.join(self._skin, "addon.xml"), self._import_line or 1)

    def _show_start(self):
        """Show the start screen with the recent skins and the way back to the results shown."""
        from kdk.config import load_config
        back = os.path.basename(self._result_skin) if self._result else ""
        self.start.show_state(self._recents(), self._skin, back, load_config().get("kodi_path", "") or "")
        self.pages.setCurrentWidget(self.start)
        self._refresh_header()

    def _show_results(self):
        """Show the filters, the tree and the detail pane of the open skin."""
        self.pages.setCurrentWidget(self.results)
        self._refresh_header()

    @staticmethod
    def _dropped_folder(mime: QMimeData) -> str:
        """Local folder a drag carries, empty when it carries none."""
        urls = mime.urls() if mime.hasUrls() else []
        path = urls[0].toLocalFile() if urls else ""
        return path if path and os.path.isdir(path) else ""

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Accept a folder dragged over the window."""
        if self._dropped_folder(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Validate the folder dropped on the window."""
        path = self._dropped_folder(event.mimeData())
        if path:
            event.acceptProposedAction()
            self._open_skin(path)

    def changeEvent(self, event: QEvent):
        """Refresh the header from addon.xml whenever the window comes back to the front."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._refresh_header()

    def _open_settings(self):
        """Open the settings dialog, then save and apply what it returns."""
        from kdk.config import load_config, save_user_config

        dialog = SettingsDialog(self, load_config(), self._pane)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        for key, value in values.items():
            save_user_config(key, value)
        self._editor = values["editor"]
        if dialog.pane() != self._pane:
            self._apply_pane(dialog.pane())
        self._gui["detail_pane"] = self._pane
        self._save_gui()
        if self.pages.currentWidget() is self.start:
            self._show_start()
        if not values["update_check"]:
            self.update_banner.setVisible(False)
            self.update_badge.setVisible(False)
        self._on_current_changed(self.tree.currentIndex(), QModelIndex())

    def _start_update_check(self):
        """Start looking up a newer release in the background, unless the user turned it off."""
        from kdk import update
        if not update.enabled():
            return
        self._lookup = update.Lookup()
        timer = QTimer(self)
        timer.timeout.connect(self._show_update)
        timer.start(500)
        self._update_timer = timer

    def _show_update(self):
        """Show the update banner once the lookup finds a newer release that was not skipped."""
        if self._lookup is None or self._update_timer is None or not self._lookup.done():
            return
        self._update_timer.stop()
        version = self._lookup.version
        if not version or version == self._gui.get("skipped_update"):
            return
        from kdk import __version__, update
        self._update_version = version
        text = f"kdk {version} is out. You have {__version__}."
        if not getattr(sys, "frozen", False):
            text += f" To update, {update.upgrade_hint()}."
        self.update_banner.text.setText(text)
        self.update_banner.setVisible(True)
        self.update_badge.setText(f'<a href="{update.RELEASES_PAGE}">v{version} available</a>')
        self.update_badge.setToolTip(update.upgrade_hint().capitalize())

    def _open_releases(self):
        """Open the latest release page in the browser."""
        from kdk import update
        QDesktopServices.openUrl(QUrl(update.RELEASES_PAGE))

    def _skip_update(self):
        """Stop announcing this release, banner and badge both, until a newer one appears."""
        self._gui["skipped_update"] = self._update_version
        self._save_gui()
        self.update_banner.setVisible(False)
        self.update_badge.setVisible(False)

    def _run_validation(self):
        """Validate open skin in background; card hides window for new skin or start-screen run."""
        if not self._skin or (self._worker_thread and self._worker_thread.isRunning()) or self.textures.busy():
            return
        self._from_start = self.pages.currentWidget() is self.start
        self._settle_release()
        self._show_results()
        for widget in (self.run_btn, self.report_btn):
            widget.setEnabled(False)
        self.notice_banner.setVisible(False)
        self.summary_label.setText("Validating...")
        self.run_card.start(f"Validating {os.path.basename(self._skin)}", pickable=not self._from_start,
                            covers=self._from_start or self._skin != self._result_skin)

        thread = QThread(self)
        worker = _ValidationWorker(self._skin, self._release_choice())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        thread.finished.connect(self._on_thread_done)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._worker_thread = thread
        thread.start()

    def _on_thread_done(self):
        """Forget the finished thread, then run what was waiting for the run to stop."""
        self._worker_thread = None
        self._worker = None
        then, self._after_run = self._after_run, None
        if then:
            then()

    def _cancel_job(self):
        """Cancel the validation or texture job the progress card shows."""
        if self._worker:
            self._cancel_run()
        else:
            self.textures.cancel()

    def _cancel_run(self, then: Callable[[], None] | None = None):
        """Cancel the run at its next progress report, queueing what to do once it has stopped."""
        if not self._worker:
            if then:
                then()
            return
        if then:
            self._after_run = then
        self._worker.cancel.set()
        self.run_card.stopping()

    def _go_start(self):
        """Show the start screen, stopping a run first."""
        if self._worker:
            self._cancel_run(self._show_start)
        else:
            self._show_start()

    def _on_progress(self, step: int, total: int, message: str):
        """Show the run's progress on the progress card."""
        self.run_card.show_progress(step, total, message)

    def _on_cancelled(self):
        """Return to the screen the run started from, unless an action is queued."""
        self._end_run()
        self._skin = self._result_skin
        if self._after_run:
            return
        if self._result and not self._from_start:
            self._show_results()
            self.statusBar().showMessage("Validation cancelled; the previous results are still shown", 5000)
        else:
            self._show_start()
            self.statusBar().showMessage("Validation cancelled", 5000)

    def _on_finished(self, result: dict):
        """Show the run's rows and notices, say it is done and remember the skin."""
        if result.get("error"):
            self._on_failed(result["error"])
            return
        self._result = result
        self._result_skin = self._skin
        self._end_run()
        self._remember_skin(self._skin)
        self._refresh_tree()
        tally = issues.counts(result["issues"], "")
        parts = _count_parts(tally["error"], tally["warning"] + tally["include"], tally["muted"])
        counts = ", ".join(text for text, _kind in parts) or "no issues"
        self.run_summary.setText(f"Validated {datetime.now():%H:%M}   |   {counts}   |   {result['duration']:.1f} s")
        self.statusBar().showMessage(f"Done: {counts}", 5000)

    def _on_failed(self, message: str):
        """Report a failed run, then go back to the screen it started from."""
        self._end_run()
        self.summary_label.setText("Error")
        self._skin = self._result_skin
        if self._result and not self._from_start:
            self._refresh_header()
        else:
            self._show_start()
        QMessageBox.critical(self, "Validation error", message)

    def _end_run(self):
        """Hide the progress card; restore Validate, Save Report and the shown rows' notices."""
        self.run_btn.setEnabled(True)
        self.run_card.stop()
        self.report_btn.setEnabled(self._result is not None)
        notices = (self._result or {}).get("notices") or []
        self.notice_banner.text.setText("\n".join(notices))
        self.notice_banner.setVisible(bool(notices))

    def _grouping(self) -> str:
        """Grouping picked in Group by."""
        return self.group_combo.currentData() or "category"

    def _skin_root(self) -> str:
        """Folder of the skin the shown results came from, empty before a run."""
        return self._result["skin_path"] if self._result else ""

    def _editor_label(self) -> str:
        """Name of the editor files open in, empty for the system default."""
        from kdk.config import EDITOR_DISPLAY_NAMES
        return EDITOR_DISPLAY_NAMES.get(self._editor, self._editor) if self._editor else ""

    def _set_counts(self, tally: dict[str, int] | None):
        """Show each toggle's count, none before a run; disable a toggle with nothing to show."""
        for name, button in self._toggles.items():
            count = tally[name] if tally else None
            button.setText(BUCKET_LABELS[name] if count is None else f"{BUCKET_LABELS[name]}  {count}")
            button.setEnabled(count != 0)

    def _on_toggle(self, name: str, on: bool):
        """Show or hide the toggle's rows."""
        if on:
            self._shown.add(name)
        else:
            self._shown.discard(name)
        self._refresh_tree()

    def _on_grouping_changed(self, _index: int):
        """Regroup the tree, hiding the column the group headings now name."""
        self._apply_columns()
        self._refresh_tree()

    def _focus_search(self):
        """Put the cursor in the search box with its text selected."""
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _refresh_tree(self):
        """Refresh the tree, toggle counts and summary, keeping the selection and closed groups."""
        if not self._result:
            return
        all_issues = self._result["issues"]
        skin_path = self._result["skin_path"]
        text = self.search_edit.text()
        self._set_counts(issues.counts(all_issues, text))
        rows = issues.build_rows(issues.shown_issues(all_issues, self._shown, text), self.merge_cb.isChecked())
        rows = issues.sort_rows(rows, self._sort_column, self._sort_descending)
        grouping = self._grouping()

        self._rebuilding = True
        self.model.removeRows(0, self.model.rowCount())
        self.tree.setRootIsDecorated(grouping != "none")
        selected = None
        for group in issues.group_rows(rows, grouping, list(all_issues)):
            parent = self.model.invisibleRootItem()
            if grouping != "none":
                parent = self._group_item(group, grouping, skin_path)
                self.model.appendRow(parent)
                self.tree.setFirstColumnSpanned(parent.row(), QModelIndex(), True)
            for row in group.rows:
                cells = self._row_cells(row, skin_path)
                parent.appendRow(cells)
                if row.holds(self._selected_key):
                    selected = cells[0]
            if grouping != "none":
                self.tree.setExpanded(parent.index(), (grouping, group.name) not in self._collapsed)
        self._apply_columns()
        self._rebuilding = False

        if selected is not None:
            # a current item in a closed group would otherwise reopen it
            self.tree.setAutoScroll(False)
            self.tree.setCurrentIndex(selected.index())
            self.tree.setAutoScroll(True)
            group = selected.parent()
            if group is None or self.tree.isExpanded(group.index()):
                self.tree.scrollTo(selected.index())
        else:
            self.detail.show_row(None, "", "")
        self._update_summary(sum(len(row.issues) for row in rows), sum(len(r) for r in all_issues.values()))

    @staticmethod
    def _group_item(group: issues.Group, grouping: str, skin_path: str) -> QStandardItem:
        """Heading for a group: name, then counts by severity, or the total when grouped by it."""
        name = relative(group.name, skin_path) if grouping == "file" else group.name
        if grouping == "severity":
            counts = str(group.errors + group.warnings + group.muted)
        else:
            counts = ", ".join(text for text, _kind in _count_parts(group.errors, group.warnings, group.muted))
        item = QStandardItem(f"{name}   {counts}")
        item.setData(group.name, GROUP_ROLE)
        item.setData((name, group.errors, group.warnings, group.muted, grouping == "severity"), HEADING_ROLE)
        item.setEditable(False)
        return item

    @staticmethod
    def _row_cells(row: issues.Row, skin_path: str) -> list[QStandardItem]:
        """Cells for one row, the row itself stored on the first."""
        issue = row.issue
        kind = "muted" if issue.get("muted") else "error" if row.is_error else "warning"
        path = relative(issue.get("file", ""), skin_path)
        lines = row.lines
        line_text = ", ".join(map(str, lines[:2])) + (f" +{len(lines) - 2}" if len(lines) > 2 else "")
        message = issue.get("message", "")
        cells = [
            QStandardItem(icon(kind), ""),
            QStandardItem(os.path.basename(path)),
            QStandardItem(line_text),
            QStandardItem(issue.get("rule", "")),
            QStandardItem(issue.get("include_name") or ""),
            QStandardItem(message),
        ]
        cells[0].setData(row, ROW_ROLE)
        cells[0].setData(kind.capitalize(), Qt.ItemDataRole.AccessibleTextRole)
        cells[0].setToolTip(kind.capitalize())
        cells[1].setToolTip(path)
        cells[2].setToolTip(", ".join(map(str, lines)))
        cells[5].setToolTip(f"<p>{html.escape(message)}</p>")
        for cell in cells:
            cell.setEditable(False)
        return cells

    def _update_summary(self, shown: int, total: int):
        """Set the status line to how many of the run's issues the filters show."""
        self.summary_label.setText(f"{shown} of {total} issues shown")

    @staticmethod
    def _row_at(index: QModelIndex) -> issues.Row | None:
        """Row behind the index, or None on a group heading or nothing."""
        if not index.isValid():
            return None
        data = index.siblingAtColumn(0).data(ROW_ROLE)
        return data if isinstance(data, issues.Row) else None

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex):
        """Show the current row in the detail pane and remember it for the next rebuild."""
        if self._rebuilding:
            return
        row = self._row_at(current)
        if row is None or not row.holds(self._selected_key):
            self._selected_key = row.key() if row else None
        self.detail.show_row(row, self._skin_root(), self._editor_label())

    def _on_group_toggled(self, index: QModelIndex, collapsed: bool):
        """Remember which groups the user closed, per grouping."""
        if self._rebuilding or index.parent().isValid():
            return
        key = (self._grouping(), index.siblingAtColumn(0).data(GROUP_ROLE))
        if collapsed:
            self._collapsed.add(key)
        else:
            self._collapsed.discard(key)

    def _on_double_clicked(self, index: QModelIndex):
        """Open a double-clicked row; a heading is left to open or close."""
        row = self._row_at(index)
        if row:
            self._open(row.issue.get("file", ""), row.issue.get("line", 1))

    def _activate(self):
        """Open the current row, or open or close the current heading."""
        index = self.tree.currentIndex().siblingAtColumn(0)
        row = self._row_at(index)
        if row:
            self._open(row.issue.get("file", ""), row.issue.get("line", 1))
        elif index.isValid():
            self.tree.setExpanded(index, not self.tree.isExpanded(index))

    def _copy_message(self):
        """Copy the current row's message."""
        row = self._row_at(self.tree.currentIndex())
        if row:
            self._copy(row.issue.get("message", ""), "Message")

    def _open(self, path: str, line: int):
        """Open the file at the line in the Settings editor; nothing for a row without a file."""
        if not path:
            return
        from kdk.config import open_in_editor
        open_in_editor(path, line, self._editor)

    def _copy(self, text: str, what: str):
        """Copy the text and say what was copied."""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        self.statusBar().showMessage(f"{what} copied", 3000)

    def _row_menu(self, pos: QPoint):
        """Show the actions for the row under the cursor."""
        index = self.tree.indexAt(pos)
        row = self._row_at(index)
        if row is None:
            return
        self.tree.setCurrentIndex(index)
        issue = row.issue
        path, line, rule = issue.get("file", ""), issue.get("line", 1), issue.get("rule", "")
        editor = self._editor_label()
        menu = QMenu(self)
        open_file = menu.addAction(f"Open in {editor}" if editor else "Open file", lambda: self._open(path, line))
        menu.addSeparator()
        menu.addAction("Copy message", lambda: self._copy(issue.get("message", ""), "Message"))
        location = menu.addAction("Copy location", lambda: self._copy(f"{path}:{line}", "Location"))
        menu.addAction("Copy rule id", lambda: self._copy(rule, "Rule id"))
        menu.addSeparator()
        menu.addAction("Show only this rule", lambda: self.search_edit.setText(rule))
        only_file = menu.addAction(
            "Show only this file", lambda: self.search_edit.setText(relative(path, self._skin_root())))
        for action in (open_file, location, only_file):
            action.setEnabled(bool(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_header_clicked(self, section: int):
        """Sort by the clicked column, a second click reversing it."""
        column = issues.COLUMNS[section]
        if column == self._sort_column:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_column, self._sort_descending = column, False
        self._show_sort()
        self._refresh_tree()

    def _show_sort(self):
        """Point the header's sort arrow at the sorted column, or show none."""
        header = self.tree.header()
        if self._sort_column is None:
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            return
        order = Qt.SortOrder.DescendingOrder if self._sort_descending else Qt.SortOrder.AscendingOrder
        header.setSortIndicator(issues.COLUMNS.index(self._sort_column), order)

    def _column_menu(self, pos: QPoint):
        """Show a checkable entry per column, and Reset columns."""
        grouping = self._grouping()
        menu = QMenu(self)
        for column in issues.COLUMNS:
            name = COLUMN_NAMES[column]
            in_heading = column == grouping and column in NAMED_BY_GROUP
            action = menu.addAction(f"{name} (in group headings)" if in_heading else name)
            action.setCheckable(True)
            action.setChecked(column not in self._hidden_columns)
            action.setEnabled(column != HEADING_COLUMN)
            action.toggled.connect(lambda on, c=column: self._set_column(c, on))
        menu.addSeparator()
        menu.addAction("Reset columns", self._reset_columns)
        menu.exec(self.tree.header().mapToGlobal(pos))

    def _set_column(self, column: str, visible: bool):
        """Show or hide a column."""
        if visible:
            self._hidden_columns.discard(column)
        else:
            self._hidden_columns.add(column)
        self._apply_columns()

    def _reset_columns(self):
        """Put the columns back to the default set and widths."""
        self._hidden_columns = set(DEFAULT_HIDDEN)
        self._default_widths()
        self._apply_columns()

    def _default_widths(self):
        """Size every column but the stretching last one to its default width."""
        header = self.tree.header()
        for n, column in enumerate(issues.COLUMNS):
            if column in COLUMN_WIDTHS:
                header.resizeSection(n, COLUMN_WIDTHS[column])

    def _apply_columns(self):
        """Hide user-hidden columns and the one the headings name; size the icon column to fit."""
        grouping = self._grouping()
        for n, column in enumerate(issues.COLUMNS):
            named = column == grouping and column in NAMED_BY_GROUP
            self.tree.setColumnHidden(n, column in self._hidden_columns or named)
        # grouped rows sit two indents deep
        indent = 2 * self.tree.indentation() if grouping != "none" else 0
        self.tree.header().resizeSection(issues.COLUMNS.index("severity"), indent + 30)

    def _show_about(self):
        """Show the version, project link and license."""
        from kdk import __version__
        QMessageBox.about(
            self,
            "About kdk",
            (
                f"<b>kdk</b> v{__version__}<br><br>"
                "Standalone Kodi skin validator.<br>"
                "CLI + PySide6 GUI.<br><br>"
                "<a href='https://github.com/MikeSiLVO/kdk'>github.com/MikeSiLVO/kdk</a><br><br>"
                "GPL-3.0-or-later"
            ),
        )

    def _save_report(self):
        """Save the issues the filters show as a text report."""
        if not self._result:
            return
        from kdk.core import get_downloads_folder, save_report
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save validation report",
            os.path.join(get_downloads_folder(), f"{self._result['skin_name']}_report.txt"),
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        shown = issues.shown_issues(self._result["issues"], self._shown, self.search_edit.text())
        save_report({**self._result, "issues": shown}, path)
        self.statusBar().showMessage(f"Report saved: {os.path.basename(path)}", 5000)


def _platform_default_font() -> QFont | None:
    """Font a little larger than Qt's default on Windows and macOS; None elsewhere."""
    if sys.platform == "win32":
        return QFont("Segoe UI", 11)
    if sys.platform == "darwin":
        return QFont("SF Pro Text", 13)
    return None


def _bundled_icon() -> QIcon | None:
    """App icon from `data/icon.ico`, run from source or a PyInstaller bundle; None when missing."""
    from importlib.resources import files
    try:
        path = files("kdk.data").joinpath("icon.ico")
        if path.is_file():
            return QIcon(str(path))
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    return None


def run_gui():
    """Run the GUI until its window closes, then exit with Qt's code."""
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    app_icon = _bundled_icon()
    if app_icon is not None:
        app.setWindowIcon(app_icon)
    font = _platform_default_font()
    if font is not None:
        app.setFont(font)

    win = KdkApp()
    if app_icon is not None:
        win.setWindowIcon(app_icon)
    win.show()
    sys.exit(app.exec())
