"""Progress card shown while a skin is validated, with Cancel."""

from __future__ import annotations

import re

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QHideEvent, QPainter, QPaintEvent, QPalette, QShowEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from kdk.core import CHECK_SEQUENCE
from kdk.gui.icons import icon

_COUNT = re.compile(r"\((\d+)/(\d+)\)")
# rough share of a run's time each check takes
_WEIGHTS = {"Variables": 1, "Maps": 0.5, "Includes": 1, "Labels": 8, "Fonts": 3.5, "IDs": 0.5, "Images": 0.5,
            "XML Validation": 68, "File Integrity": 12, "Kodi Repo": 3}
_BAR_STYLE = (
    "QProgressBar { border: 1px solid palette(mid); border-radius: 4px; background: palette(base); }"
    " QProgressBar::chunk { background-color: #1f7ad8; border-radius: 3px; }"
)


class _Spinner(QWidget):
    """The shipped spinner image, turned a step at a time while shown."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(18, 18)
        self._pixmap = icon("spinner").pixmap(QSize(16, 16), self.devicePixelRatioF())
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._turn)

    def showEvent(self, event: QShowEvent):
        """Start turning."""
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent):
        """Stop turning."""
        self._timer.stop()
        super().hideEvent(event)

    def _turn(self):
        """Turn one step and repaint."""
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent):
        """Paint the image rotated about its center."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        painter.drawPixmap(QPointF(-8, -8), self._pixmap)


class RunCard(QWidget):
    """Layer over the results or the whole window, holding the card: time, progress, Cancel."""

    cancel_requested = Signal()
    pick_requested = Signal()

    def __init__(self, pages: QWidget, whole: QWidget):
        super().__init__(pages)
        self._pages = pages
        self._whole = whole
        self._host = pages
        self._covers = False
        pages.installEventFilter(self)
        self.card = QFrame(self)
        self.card.setObjectName("runCard")
        self.card.setStyleSheet("#runCard { background: palette(window); border: 1px solid palette(mid);"
                                " border-radius: 8px; }")
        self.card.setFixedWidth(470)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        box = QVBoxLayout(self.card)
        box.setContentsMargins(20, 18, 20, 16)
        box.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(_Spinner())
        self.title = QLabel()
        bold = self.title.font()
        bold.setBold(True)
        bold.setPointSizeF(bold.pointSizeF() * 1.1)
        self.title.setFont(bold)
        head.addWidget(self.title, stretch=1)
        self.elapsed = QLabel()
        self.elapsed.setStyleSheet("color: gray;")
        head.addWidget(self.elapsed)
        box.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet(_BAR_STYLE)
        box.addWidget(self.bar)

        step_row = QHBoxLayout()
        self.step = QLabel()
        step_font = self.step.font()
        step_font.setBold(True)
        self.step.setFont(step_font)
        self.step_of = QLabel()
        self.step_of.setStyleSheet("color: gray;")
        step_row.addWidget(self.step, stretch=1)
        step_row.addWidget(self.step_of)
        box.addLayout(step_row)
        self.detail = QLabel()
        self.detail.setStyleSheet("color: gray;")
        box.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.pick_btn = QPushButton("Choose another skin")
        self.pick_btn.setObjectName("linkButton")
        self.pick_btn.setStyleSheet("#linkButton { border: none; background: transparent; color: palette(link);"
                                    " padding: 0 4px; }")
        self.pick_btn.clicked.connect(self.pick_requested)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_requested)
        buttons.addWidget(self.pick_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        box.addLayout(buttons)

        self._clock = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._show_elapsed)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep covering the parent as it resizes."""
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return False

    def paintEvent(self, event: QPaintEvent):
        """Dim the results behind the card, or hide the whole window behind its own color."""
        fill = self.palette().color(QPalette.ColorRole.Window) if self._covers else QColor(0, 0, 0, 110)
        QPainter(self).fillRect(self.rect(), fill)

    def start(self, skin: str, pickable: bool = True, covers: bool = False):
        """Show the card for a new run, clock at zero, dimming the results or hiding the window."""
        self._covers = covers
        self._move_to(self._whole if covers else self._pages)
        self.title.setText(f"Validating {skin}")
        self.bar.setValue(0)
        self.step.setText("Loading the skin")
        self.step_of.setText("Before the checks")
        self._set_detail("")
        self.cancel_btn.setText("Cancel")
        self.pick_btn.setVisible(pickable)
        for button in (self.cancel_btn, self.pick_btn):
            button.setEnabled(True)
        self._clock.start()
        self._show_elapsed()
        self._tick.start()
        self.show()
        self.raise_()
        self.cancel_btn.setFocus()

    def _move_to(self, host: QWidget):
        """Move the layer onto the widget, watching its resizes, and size it to match."""
        if host is not self._host:
            self._host.removeEventFilter(self)
            self.setParent(host)
            host.installEventFilter(self)
            self._host = host
        self.setGeometry(host.rect())

    def show_progress(self, step: int, total: int, message: str):
        """Show the check under way, the run's progress weighted by check cost, and the report."""
        names = [name for name, _method in CHECK_SEQUENCE]
        done = 0.0
        if 1 <= step <= len(names):
            self.step.setText(names[step - 1])
            self.step_of.setText(f"Check {step} of {total}")
            match = _COUNT.search(message)
            part = min(int(match[1]) / int(match[2]), 1.0) if match and int(match[2]) else 0.0
            finished = sum(_WEIGHTS.get(name, 1) for name in names[:step - 1])
            done = (finished + _WEIGHTS.get(names[step - 1], 1) * part) / sum(_WEIGHTS.get(n, 1) for n in names)
        # a check's second counted pass starts its count again
        self.bar.setValue(max(self.bar.value(), int(done * 1000)))
        self._set_detail(message.split(": ", 1)[1] if ": " in message else message)

    def stopping(self):
        """Say the run is stopping and take both buttons away."""
        self.cancel_btn.setText("Stopping...")
        for button in (self.cancel_btn, self.pick_btn):
            button.setEnabled(False)

    def stop(self):
        """Hide the card and stop its clock."""
        self._tick.stop()
        self.hide()

    def _set_detail(self, text: str):
        """Set the report line, shortened in the middle to fit the card."""
        width = self.card.width() - 40
        self.detail.setText(QFontMetrics(self.detail.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, width))

    def _show_elapsed(self):
        """Show the minutes and seconds the run has taken so far."""
        seconds = self._clock.elapsed() // 1000 if self._clock.isValid() else 0
        self.elapsed.setText(f"{seconds // 60}:{seconds % 60:02d}")
