"""PySide6-based skin validator GUI."""

from __future__ import annotations

import base64
import os
import sys

from PySide6.QtCore import QByteArray, QObject, QThread, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QStyleFactory,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

class _ValidationWorker(QObject):
    """Runs `validate_skin` on its own QThread; reports progress + result via signals."""
    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, skin_path: str, overrides: dict | None = None):
        super().__init__()
        self._skin_path = skin_path
        self._overrides = overrides

    def run(self):
        try:
            from kdk.core import validate_skin
            result = validate_skin(
                self._skin_path,
                config_overrides=self._overrides,
                progress_callback=lambda s, t, m: self.progress.emit(s, t, m),
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class KdkApp(QMainWindow):
    """Main validator window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("KDK - Kodi Skin Validator")
        self.resize(1000, 700)

        self._result: dict | None = None
        self._issue_data: dict[QTreeWidgetItem, dict] = {}
        self._editor_keys: list[str] = []
        self._worker_thread: QThread | None = None
        self._worker: _ValidationWorker | None = None

        self._build_ui()
        self._load_settings()
        self._restore_window_state()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)
        skin_row = QHBoxLayout()
        skin_row.addWidget(QLabel("Skin folder:"))
        self.path_edit = QLineEdit()
        self.path_edit.textChanged.connect(self._on_path_changed)
        skin_row.addWidget(self.path_edit, stretch=1)
        skin_btn = QPushButton("Browse...")
        skin_btn.clicked.connect(self._browse_skin)
        skin_row.addWidget(skin_btn)
        root.addLayout(skin_row)
        kodi_row = QHBoxLayout()
        kodi_row.addWidget(QLabel("Kodi path:"))
        self.kodi_edit = QLineEdit()
        self.kodi_edit.textChanged.connect(self._on_kodi_path_changed)
        kodi_row.addWidget(self.kodi_edit, stretch=1)
        kodi_btn = QPushButton("Browse...")
        kodi_btn.clicked.connect(self._browse_kodi)
        kodi_row.addWidget(kodi_btn)
        root.addLayout(kodi_row)

        self.kodi_hint = QLabel("")
        self.kodi_hint.setStyleSheet("color: gray;")
        root.addWidget(self.kodi_hint)
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Validate")
        self.run_btn.clicked.connect(self._run_validation)
        btn_row.addWidget(self.run_btn)

        self.report_btn = QPushButton("Save Report")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._save_report)
        btn_row.addWidget(self.report_btn)

        self.hide_includes_cb = QCheckBox("Hide include warnings")
        self.hide_includes_cb.setChecked(True)
        self.hide_includes_cb.toggled.connect(self._refresh_tree)
        btn_row.addWidget(self.hide_includes_cb)

        btn_row.addStretch(1)
        self.status_label = QLabel("Ready")
        btn_row.addWidget(self.status_label)
        root.addLayout(btn_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        # Fusion's default chunk color is a muted gray that looks washed-out in
        # light mode. Pin it to the icon's blue so it reads as a real fill.
        self.progress.setStyleSheet(
            "QProgressBar {"
            " border: 1px solid palette(mid);"
            " border-radius: 3px;"
            " background: palette(base);"
            " text-align: center;"
            "}"
            "QProgressBar::chunk {"
            " background-color: #1f7ad8;"
            " border-radius: 2px;"
            "}"
        )
        root.addWidget(self.progress)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Category", "File", "Line", "Message"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 220)
        self.tree.setColumnWidth(2, 60)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(28)  # bigger chevron click target
        self.tree.setStyleSheet(
            "QHeaderView::section { padding: 6px 10px; }"
            " QTreeView::item { padding: 4px 0; }"
            # Branch column gets extra horizontal room so the chevron has a
            # bigger hit area without needing a custom branch image.
            " QTreeView::branch { padding: 0 4px; }"
        )
        # Double-click toggles a category row, opens the file for a leaf row.
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        root.addWidget(self.tree, stretch=1)
        bottom = QHBoxLayout()
        self.summary_label = QLabel("")
        bottom.addWidget(self.summary_label)
        bottom.addStretch(1)

        bottom.addWidget(QLabel("Double-click opens in:"))
        self.editor_combo = QComboBox()
        self.editor_combo.setMinimumWidth(160)
        self.editor_combo.currentIndexChanged.connect(self._on_editor_changed)
        bottom.addWidget(self.editor_combo)

        from kdk import __version__
        self.version_btn = QPushButton(f"v{__version__}")
        self.version_btn.setFlat(True)
        self.version_btn.setToolTip("Click for about / version info")
        self.version_btn.setStyleSheet("color: gray; padding: 0 6px;")
        self.version_btn.clicked.connect(self._show_about)
        bottom.addWidget(self.version_btn)

        root.addLayout(bottom)

    def _load_settings(self):
        from kdk.config import load_config, detect_editors, EDITOR_DISPLAY_NAMES

        config = load_config()
        # Block signals so loading initial values doesn't fire change handlers.
        for w in (self.kodi_edit, self.editor_combo):
            w.blockSignals(True)

        self.kodi_edit.setText(config.get("kodi_path", "") or "")

        saved_editor = config.get("editor", "") or ""
        available = detect_editors()
        self._editor_keys = [""] + available
        if saved_editor and saved_editor not in self._editor_keys:
            self._editor_keys.append(saved_editor)
        self.editor_combo.clear()
        for key in self._editor_keys:
            self.editor_combo.addItem(EDITOR_DISPLAY_NAMES.get(key, key))
        if saved_editor in self._editor_keys:
            self.editor_combo.setCurrentIndex(self._editor_keys.index(saved_editor))

        for w in (self.kodi_edit, self.editor_combo):
            w.blockSignals(False)

        self._update_kodi_hint()

    def _restore_window_state(self):
        from kdk.config import load_config
        blob = load_config().get("window_geometry", "")
        if not blob:
            return
        try:
            self.restoreGeometry(QByteArray(base64.b64decode(blob)))
        except Exception:
            # Corrupt or from a different Qt version - fall back to default size.
            pass

    def closeEvent(self, event: QCloseEvent):
        from kdk.config import save_user_config
        try:
            blob = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            save_user_config("window_geometry", blob)
        except Exception:
            pass
        super().closeEvent(event)

    def _browse_kodi(self):
        path = QFileDialog.getExistingDirectory(self, "Select Kodi installation folder (optional)")
        if path:
            self.kodi_edit.setText(path)

    def _on_kodi_path_changed(self, _text=None):
        from kdk.config import save_user_config
        save_user_config("kodi_path", self.kodi_edit.text().strip())
        self._update_kodi_hint()

    def _update_kodi_hint(self):
        path = self.kodi_edit.text().strip()
        if path and os.path.isdir(path):
            self.kodi_hint.setText("")
            return
        if path:
            self.kodi_hint.setText("path not found - falling back to bundled snapshot")
            return
        try:
            from kdk.libs.addon.addon import Addon
            latest = Addon.RELEASES[-1]["name"] if Addon.RELEASES else ""
        except Exception:
            latest = ""
        if latest:
            self.kodi_hint.setText(
                f"empty - using bundled Kodi snapshot ({latest}); set this for higher accuracy"
            )
        else:
            self.kodi_hint.setText("empty - no Kodi reference data available")

    def _browse_skin(self):
        from kdk.config import load_config, save_user_config

        # Start at the parent of the last skin chosen, so siblings are one click away.
        start_dir = load_config().get("last_skin_parent", "") or ""
        if not start_dir or not os.path.isdir(start_dir):
            current = self.path_edit.text().strip()
            start_dir = os.path.dirname(current) if current and os.path.isdir(current) else ""

        path = QFileDialog.getExistingDirectory(self, "Select Kodi skin folder", start_dir)
        if path:
            self.path_edit.setText(path)
            save_user_config("last_skin_parent", os.path.dirname(path))

    def _on_path_changed(self, _text=None):
        """Clear stale results when the user picks/types a different skin path."""
        if not self._result:
            return
        if self.path_edit.text().strip() == self._result.get("skin_path"):
            return
        self._result = None
        self._issue_data.clear()
        self.tree.clear()
        self.summary_label.setText("")
        self.report_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("Ready")

    def _on_editor_changed(self, idx: int):
        from kdk.config import save_user_config
        if 0 <= idx < len(self._editor_keys):
            save_user_config("editor", self._editor_keys[idx])

    def _run_validation(self):
        skin_path = self.path_edit.text().strip()
        if not skin_path:
            QMessageBox.warning(self, "No path", "Please select a skin folder first.")
            return
        if not os.path.isdir(skin_path):
            QMessageBox.critical(self, "Invalid path", f"Not a directory: {skin_path}")
            return
        if not os.path.isfile(os.path.join(skin_path, "addon.xml")):
            QMessageBox.critical(self, "Not a skin", f"No addon.xml found in: {skin_path}")
            return
        if self._worker_thread and self._worker_thread.isRunning():
            return

        self.run_btn.setEnabled(False)
        self.report_btn.setEnabled(False)
        self.tree.clear()
        self._issue_data.clear()
        self.summary_label.setText("")
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status_label.setText("Running...")

        thread = QThread(self)
        worker = _ValidationWorker(skin_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._worker_thread = thread
        thread.start()

    def _on_progress(self, step: int, total: int, message: str):
        self.progress.setValue(int((step / total) * 100) if total else 0)
        self.status_label.setText(message)

    def _on_finished(self, result: dict):
        self._result = result
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("Done")
        if result.get("error"):
            QMessageBox.critical(self, "Validation error", result["error"])
            return
        self.report_btn.setEnabled(True)
        self._refresh_tree()

    def _on_failed(self, message: str):
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Validation error", message)

    def _refresh_tree(self):
        if not self._result or self._result.get("error"):
            return

        from kdk.core import filter_include_warnings

        all_issues = self._result["issues"]
        hide_includes = self.hide_includes_cb.isChecked()
        issues = filter_include_warnings(all_issues) if hide_includes else all_issues

        self.tree.clear()
        self._issue_data.clear()

        def _real(cat_issues):
            return [
                i for i in cat_issues
                if i.get("line", 0) > 0 or "not found" in i.get("message", "").lower()
            ]

        total_issues = 0
        for category, cat_issues in issues.items():
            real_issues = _real(cat_issues)
            if not real_issues:
                continue

            cat_node = QTreeWidgetItem(self.tree, [f"{category} ({len(real_issues)})", "", "", ""])
            # Span the category title across all columns so the row is one click target.
            cat_node.setFirstColumnSpanned(True)
            for issue in real_issues:
                full_path = issue.get("file", "")
                display_name = os.path.basename(full_path) if full_path else ""
                line_num = issue.get("line", 0)
                child = QTreeWidgetItem(
                    cat_node,
                    ["", display_name, str(line_num), issue.get("message", "")],
                )
                if full_path:
                    self._issue_data[child] = {"file": full_path, "line": line_num}
                total_issues += 1

        unfiltered_total = sum(len(_real(c)) for c in all_issues.values())
        hidden = unfiltered_total - total_issues
        summary = f"{self._result['skin_name']}  |  {total_issues} issues"
        if hide_includes and hidden > 0:
            summary += f"  ({hidden} include-warning{'s' if hidden != 1 else ''} hidden)"
        summary += f"  |  {self._result['duration']:.1f}s"
        self.summary_label.setText(summary)

    def _on_tree_double_clicked(self, item: QTreeWidgetItem, _col: int):
        """Issue row -> open file in editor. Category rows are left alone - Qt's
        default double-click handler already toggles expansion."""
        if item.childCount():
            return

        data = self._issue_data.get(item)
        if not data:
            return
        idx = self.editor_combo.currentIndex()
        editor = self._editor_keys[idx] if 0 <= idx < len(self._editor_keys) else ""
        from kdk.config import open_in_editor
        open_in_editor(data["file"], data["line"], editor)

    def _show_about(self):
        from kdk import __version__
        QMessageBox.about(
            self,
            "About kdk",
            (
                f"<b>kdk</b> v{__version__}<br><br>"
                "Standalone Kodi skin validator.<br>"
                "CLI + PySide6 GUI.<br><br>"
                "<a href='https://github.com/MikeSiLVO/kdk'>github.com/MikeSiLVO/kdk</a><br><br>"
                "GPL-2.0-only"
            ),
        )

    def _save_report(self):
        if not self._result:
            return
        from kdk.core import save_report, get_downloads_folder, filter_include_warnings
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save validation report",
            os.path.join(get_downloads_folder(), f"{self._result['skin_name']}_report.txt"),
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return

        # Mirror the GUI's current filter so what users see is what they save.
        result_for_report = self._result
        if self.hide_includes_cb.isChecked():
            result_for_report = {
                **self._result,
                "issues": filter_include_warnings(self._result["issues"]),
            }

        save_report(result_for_report, path)
        self.status_label.setText(f"Report saved: {os.path.basename(path)}")

def _platform_default_font() -> QFont | None:
    """Slightly larger than Qt's per-platform default for nicer readability."""
    if sys.platform == "win32":
        return QFont("Segoe UI", 11)
    if sys.platform == "darwin":
        return QFont("SF Pro Text", 13)
    return None  # Linux: trust the system default

def _bundled_icon() -> QIcon | None:
    """Locate `data/icon.ico` whether running from source or a PyInstaller bundle."""
    from importlib.resources import files
    try:
        path = files("kdk.data").joinpath("icon.ico")
        if path.is_file():
            return QIcon(str(path))
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    return None

def run_gui():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    icon = _bundled_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    font = _platform_default_font()
    if font is not None:
        app.setFont(font)

    win = KdkApp()
    if icon is not None:
        win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())
