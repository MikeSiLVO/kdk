"""Detail pane of the kdk GUI: the selected issue in full, with links and actions."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from kdk.gui.style import is_dark, severity_colors
from kdk.gui.issues import Row
from kdk.output.payload import relative


def _fact_label() -> QLabel:
    """Selectable rich-text value cell whose links the pane handles itself."""
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    return label


class DetailPane(QScrollArea):
    """Pane showing the selected row in full: message, location, include and actions."""

    open_requested = Signal(str, int)
    copy_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._row: Row | None = None
        self._targets: dict[str, tuple[str, int]] = {}

        body = QWidget()
        body.setBackgroundRole(QPalette.ColorRole.AlternateBase)
        body.setAutoFillBackground(True)
        self.setWidget(body)
        stack = QVBoxLayout(body)
        stack.setContentsMargins(14, 12, 14, 12)
        self.empty = QLabel("Select an issue to see it in full.")
        self.empty.setStyleSheet("color: gray;")
        stack.addWidget(self.empty)
        self.filled = QWidget()
        stack.addWidget(self.filled)
        stack.addStretch(1)

        self.outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.filled)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(24)
        content = QVBoxLayout()
        content.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.severity = QLabel()
        pill = self.severity.font()
        pill.setBold(True)
        pill.setPointSizeF(pill.pointSizeF() - 1.5)
        pill.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        self.severity.setFont(pill)
        self.rule = QLabel()
        self.rule.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.rule.setStyleSheet("background: rgba(127, 127, 127, 0.2); border-radius: 4px; padding: 2px 7px;")
        self.rule.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.category = QLabel()
        self.category.setStyleSheet("color: gray;")
        for widget in (self.severity, self.rule, self.category):
            head.addWidget(widget)
        head.addStretch(1)
        content.addLayout(head)

        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        larger = self.message.font()
        larger.setPointSizeF(larger.pointSizeF() + 1)
        self.message.setFont(larger)
        content.addWidget(self.message)

        facts = QGridLayout()
        facts.setHorizontalSpacing(14)
        facts.setVerticalSpacing(6)
        facts.setColumnStretch(1, 1)
        self._facts: dict[str, tuple[QLabel, QLabel]] = {}
        for n, name in enumerate(("Location", "Include", "Called from", "Subject")):
            title = QLabel(name)
            title.setStyleSheet("color: gray;")
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value = _fact_label()
            value.linkActivated.connect(self._on_link)
            facts.addWidget(title, n, 0)
            facts.addWidget(value, n, 1)
            self._facts[name] = (title, value)
        content.addLayout(facts)
        self.outer.addLayout(content, 1)

        self.buttons = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.buttons.setSpacing(8)
        self.open_btn = QPushButton("Open")
        self.open_btn.setProperty("primary", True)
        self.open_btn.clicked.connect(self._open_first)
        copy_message = QPushButton("Copy message")
        copy_message.clicked.connect(lambda: self._copy("message"))
        self.copy_location_btn = QPushButton("Copy location")
        self.copy_location_btn.clicked.connect(lambda: self._copy("location"))
        for button in (self.open_btn, copy_message, self.copy_location_btn):
            self.buttons.addWidget(button)
        self.buttons.addStretch(1)
        self.outer.addLayout(self.buttons)
        self.show_row(None, "", "")

    def set_below(self, below: bool):
        """Set the buttons beside the text for a pane below the list, else in a row under it."""
        ltr, ttb = QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.TopToBottom
        self.outer.setDirection(ltr if below else ttb)
        self.buttons.setDirection(ttb if below else ltr)

    def show_row(self, row: Row | None, skin_path: str, editor_name: str):
        """Show the row in full, or the empty hint when there is none."""
        self._row = row
        self.empty.setVisible(row is None)
        self.filled.setVisible(row is not None)
        if row is None:
            return
        issue = row.issue
        kind = "muted" if issue.get("muted") else "error" if row.is_error else "warning"
        background, color = severity_colors(kind, is_dark(self))
        self.severity.setText(kind.upper())
        self.severity.setStyleSheet(f"background: {background}; color: {color}; border-radius: 9px;"
                                    " padding: 2px 10px;")
        self.rule.setText(issue.get("rule", ""))
        self.category.setText(row.category)
        self.message.setText(issue.get("message", ""))
        self.open_btn.setText(f"Open in {editor_name}" if editor_name else "Open file")

        self._targets = {}
        path = issue.get("file", "")
        self.open_btn.setEnabled(bool(path))
        self.copy_location_btn.setEnabled(bool(path))
        lines = ", ".join(self._link(path, line) for line in row.lines)
        word = "lines" if len(row.lines) > 1 else "line"
        location = f"<code>{html.escape(relative(path, skin_path))}</code> {word} {lines}"
        self._set_fact("Location", location if path else "")

        include = issue.get("include_name") or ""
        text = f"<b>{html.escape(include)}</b>"
        if issue.get("include_file"):
            where = f"{relative(issue['include_file'], skin_path)}:{issue.get('include_line', 1)}"
            text += f" defined at {self._link(issue['include_file'], issue.get('include_line', 1), where)}"
        self._set_fact("Include", text if include else "")

        call = issue.get("call_file") or ""
        call_line = issue.get("call_line") or 1
        shown = f"{relative(call, skin_path)}:{call_line}" if issue.get("call_line") else relative(call, skin_path)
        self._set_fact("Called from", self._link(call, call_line, shown) if call and call != path else "")

        subject = issue.get("subject") or ""
        self._set_fact("Subject", f"<code>{html.escape(subject)}</code>" if subject and subject != include else "")

    def _set_fact(self, name: str, text: str):
        """Fill one fact row, hiding it when there is nothing to say."""
        title, value = self._facts[name]
        value.setText(text)
        title.setVisible(bool(text))
        value.setVisible(bool(text))

    def _link(self, path: str, line: int, text: str = "") -> str:
        """Anchor that opens the file at the line, shown as the text or the line number."""
        href = str(len(self._targets))
        self._targets[href] = (path, line)
        label = html.escape(text) if text else str(line)
        return f'<a href="{href}">{label}</a>'

    def _on_link(self, href: str):
        """Ask for the linked file to open at its line."""
        if href in self._targets:
            self.open_requested.emit(*self._targets[href])

    def _open_first(self):
        """Ask for the row's file to open at its first line."""
        if self._row:
            self.open_requested.emit(self._row.issue.get("file", ""), self._row.issue.get("line", 1))

    def _copy(self, what: str):
        """Ask for the row's message or its file and line to be copied."""
        if not self._row:
            return
        issue = self._row.issue
        if what == "message":
            self.copy_requested.emit(issue.get("message", ""), "Message")
        else:
            self.copy_requested.emit(f"{issue.get('file', '')}:{issue.get('line', 1)}", "Location")
