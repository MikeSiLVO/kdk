"""Settings dialog of the kdk GUI."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from kdk.gui.style import control_height, round_popups

PANES = (("bottom", "Below the list"), ("right", "Right of the list"))


class SettingsDialog(QDialog):
    """Dialog for the Kodi path, language, editor, detail pane and update check."""

    def __init__(self, parent: QWidget, config: dict, pane: str):
        super().__init__(parent)
        from kdk.config import EDITOR_DISPLAY_NAMES, detect_editors

        self.setWindowTitle("Settings")
        self.setMinimumWidth(540)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(10)

        self.kodi_edit = QLineEdit(config.get("kodi_path", "") or "")
        self.kodi_edit.textChanged.connect(self._update_kodi_hint)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_kodi)
        kodi_row = QHBoxLayout()
        kodi_row.setSpacing(8)
        kodi_row.addWidget(self.kodi_edit, stretch=1)
        kodi_row.addWidget(browse)
        form.addRow("Kodi path", kodi_row)
        self.kodi_hint = QLabel()
        self.kodi_hint.setStyleSheet("color: gray;")
        self.kodi_hint.setWordWrap(True)
        form.addRow("", self.kodi_hint)

        self.language_edit = QLineEdit(config.get("language", "") or "")
        form.addRow("Language", self.language_edit)

        saved = config.get("editor", "") or ""
        editors = [""] + detect_editors()
        if saved not in editors:
            editors.append(saved)
        self.editor_combo = QComboBox()
        for key in editors:
            self.editor_combo.addItem(EDITOR_DISPLAY_NAMES.get(key, key), key)
        self._select(self.editor_combo, saved)
        form.addRow("Open files in", self.editor_combo)

        self.pane_combo = QComboBox()
        for key, label in PANES:
            self.pane_combo.addItem(label, key)
        self._select(self.pane_combo, pane)
        form.addRow("Issue details", self.pane_combo)

        self.update_cb = QCheckBox("Check for new releases once a day")
        self.update_cb.setChecked(bool(config.get("update_check", True)))
        form.addRow("", self.update_cb)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("primary", True)
        root.addWidget(buttons)
        height = control_height(self)
        for widget in (self.kodi_edit, browse, self.language_edit, self.editor_combo,
                       self.pane_combo, *buttons.buttons()):
            widget.setFixedHeight(height)
        round_popups(self)
        self._update_kodi_hint()

    @staticmethod
    def _select(combo: QComboBox, value: str):
        """Select the combo entry holding the value, leaving the first when none does."""
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    def _browse_kodi(self):
        """Pick the Kodi folder with a folder dialog."""
        path = QFileDialog.getExistingDirectory(self, "Select Kodi installation folder", self.kodi_edit.text())
        if path:
            self.kodi_edit.setText(path)

    def _update_kodi_hint(self):
        """Say what an empty or missing Kodi path falls back to."""
        path = self.kodi_edit.text().strip()
        if path and os.path.isdir(path):
            self.kodi_hint.setText("")
        elif path:
            self.kodi_hint.setText("Folder not found. A run reports it and uses the bundled Kodi snapshot.")
        else:
            self.kodi_hint.setText("Empty uses the bundled Kodi snapshot for the skin's release.")
        self.kodi_hint.setVisible(bool(self.kodi_hint.text()))

    def values(self) -> dict:
        """User config entries the dialog sets, by key."""
        from kdk.config import DEFAULTS
        return {
            "kodi_path": self.kodi_edit.text().strip(),
            "language": self.language_edit.text().strip() or DEFAULTS["language"],
            "editor": self.editor_combo.currentData(),
            "update_check": self.update_cb.isChecked(),
        }

    def pane(self) -> str:
        """Where the detail pane goes: below or right of the list."""
        return self.pane_combo.currentData()
