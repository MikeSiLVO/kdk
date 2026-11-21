"""Texture tools of the GUI: pack or unpack a bundle on a worker thread, with Cancel."""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from kdk import xbt
from kdk.gui.progress import RunCard

_SHOWN = 12


class _Worker(QObject):
    """Worker running one pack or unpack job on its own thread; `cancel` stops it between images."""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Callable[[threading.Event, Callable[[int, int, str], None]], object]):
        super().__init__()
        self._job = job
        self.cancel = threading.Event()

    def run(self):
        """Run the job, sending its result, or the text of the file error it raised."""
        try:
            self.finished.emit(self._job(self.cancel, lambda n, t, m: self.progress.emit(n, t, m)))
        except (OSError, ValueError) as e:
            self.failed.emit(str(e))


class TextureTools(QObject):
    """Texture tools of the window, asking for paths and showing the job on the progress card."""

    def __init__(self, window: QWidget, card: RunCard, on_start_page: Callable[[], bool]):
        super().__init__(window)
        self._window = window
        self._card = card
        self._on_start_page = on_start_page
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._report: Callable[[Any], None] = lambda _result: None

    def busy(self) -> bool:
        """True while a pack or unpack runs."""
        return self._thread is not None

    def cancel(self):
        """Cancel the running job before its next image."""
        if self._worker:
            self._worker.cancel.set()
            self._card.stopping()

    def stop_for_close(self) -> QThread | None:
        """Stop the running job for a closing window, its finish ignored; the thread to wait for."""
        if self._worker:
            self._worker.finished.disconnect(self._on_finished)
            self._worker.failed.disconnect(self._on_failed)
            self._worker.cancel.set()
        return self._thread

    def unpack(self, start: str):
        """Ask for a bundle and a folder, then unpack it there; files already there are kept."""
        if not self._ready():
            return
        bundle, _filter = QFileDialog.getOpenFileName(self._window, "Choose a texture bundle to unpack", start,
                                                      "Texture bundles (*.xbt)")
        if not bundle:
            return
        folder = QFileDialog.getExistingDirectory(self._window, "Choose the folder to unpack into",
                                                  os.path.dirname(bundle))
        if not folder:
            return
        skin = xbt.skin_of(bundle)
        names = xbt.media_names(skin) if skin else None
        self._report = lambda result: self._unpacked(result, folder)
        self._run(f"Unpacking {os.path.basename(bundle)}", "Unpacking",
                  lambda cancel, progress: xbt.unpack(bundle, folder, names, progress=progress, cancel=cancel))

    def pack(self, start: str):
        """Ask for a folder of images and where to save the bundle, then pack them into it."""
        if not self._ready():
            return
        folder = QFileDialog.getExistingDirectory(self._window, "Choose the folder of images to pack", start)
        if not folder:
            return
        bundle, _filter = QFileDialog.getSaveFileName(self._window, "Save the texture bundle as",
                                                      os.path.join(folder, "Textures.xbt"), "Texture bundles (*.xbt)")
        if not bundle:
            return
        self._report = lambda result: self._packed(result, bundle)
        self._run(f"Packing {os.path.basename(folder)}", "Packing",
                  lambda cancel, progress: xbt.pack(folder, bundle, progress=progress, cancel=cancel))

    def _ready(self) -> bool:
        """True when no job runs and Pillow and lzallright import; warns when they don't."""
        if self.busy():
            return False
        hint = xbt.missing_libraries()
        if hint:
            QMessageBox.warning(self._window, "Texture tools", f"Packing and unpacking need Pillow and lzallright.\n\n{hint}")
            return False
        return True

    def _run(self, title: str, step: str, job: Callable[[threading.Event, Callable[[int, int, str], None]], object]):
        """Run the job on a thread under the card, which hides the window from the start page."""
        self._card.start(title, step, "", pickable=False, covers=self._on_start_page())
        thread = QThread(self)
        worker = _Worker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        for signal in (worker.finished, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(self._on_thread_done)
        thread.finished.connect(thread.deleteLater)
        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_progress(self, done: int, total: int, path: str):
        """Show the job's progress on the card, from the window's thread."""
        self._card.show_count(done, total, path)

    def _on_thread_done(self):
        """Forget the finished thread and its worker."""
        self._thread = None
        self._worker = None

    def _on_finished(self, result):
        """Hide the card and report what the job did."""
        self._card.stop()
        self._report(result)

    def _on_failed(self, message: str):
        """Hide the card and show why the job could not finish."""
        self._card.stop()
        QMessageBox.critical(self._window, "Texture tools", message)

    def _unpacked(self, result: xbt.UnpackResult, folder: str):
        """Report an unpack: written, recased and kept counts, unread paths; offer the folder."""
        lines = [f"Unpacked {len(result.written)} textures into {folder}."]
        if result.cancelled:
            lines[0] = f"Cancelled after unpacking {len(result.written)} textures into {folder}."
        if result.recased:
            lines.append(f"{result.recased} names took their case from the skin's XML; the rest stay lowercase.")
        if result.kept:
            lines.append(f"{len(result.kept)} files already there were kept.")
        self._show_result(lines, result.unreadable, "Not unpacked", folder)

    def _packed(self, result: xbt.PackResult, bundle: str):
        """Report a pack: how many were stored, shared and left out; offer the folder."""
        if result.cancelled:
            self._show_result(["Packing was cancelled; no bundle was written."], [], "", "")
            return
        lines = [f"Packed {len(result.packed)} images into {bundle}."]
        if result.duplicates:
            lines.append(f"{result.duplicates} were identical to another image and are stored once.")
        self._show_result(lines, result.unreadable, "Left out, unreadable or its lowercase name taken",
                          os.path.dirname(bundle))

    def _show_result(self, lines: list[str], skipped: list[str], heading: str, folder: str):
        """Show the report, the first skipped paths under the heading, and an Open folder button."""
        if skipped:
            listed = "\n".join(f"  {path}" for path in skipped[:_SHOWN])
            more = f"\n  and {len(skipped) - _SHOWN} more" if len(skipped) > _SHOWN else ""
            lines.append(f"{heading}:\n{listed}{more}")
        box = QMessageBox(QMessageBox.Icon.Information, "Texture tools", "\n\n".join(lines), parent=self._window)
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole) if folder else None
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if open_btn is not None and box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
