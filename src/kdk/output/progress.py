"""Live progress for a validation run, and the log muting that keeps it readable."""

from __future__ import annotations

import logging

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from .render import err_console


class DedupeFilter(logging.Filter):
    """Pass each distinct message once; one bad include resolved in 80 places logs 80 times."""

    def __init__(self):
        super().__init__()
        self._seen = set()

    def filter(self, record):
        key = (record.name, record.levelno, record.getMessage())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class RunProgress:
    """Single self-updating progress line for the check sequence; a no-op when not on a terminal."""

    _task: TaskID

    def __init__(self, skin_path, total_steps, *, enabled=True):
        self.skin_path = skin_path
        self.total_steps = total_steps
        self.enabled = enabled and err_console.is_terminal
        self._progress = None

    def __enter__(self):
        if not self.enabled:
            return self
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=24),
            TextColumn("[dim]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=err_console,
            transient=True,
        )
        self._progress.start()
        self._task = self._progress.add_task("Starting", total=self.total_steps)
        return self

    def __exit__(self, *_):
        if self._progress:
            self._progress.stop()
        return False

    def update(self, step, total, message):
        """Progress callback: show the phase only, never a running issue count."""
        if not self._progress:
            return
        # Counts here are pre-filter, so they would contradict the summary
        phase = message.split(":", 1)[0].strip().rstrip(".")
        self._progress.update(self._task, completed=step, total=total, description=phase)


def quiet_engine_logging(debug=False):
    """Route engine logs to stderr, deduplicated, and mute the per-file INFO narration."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.addFilter(DedupeFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if debug else logging.ERROR)

    # Whatever the engine logs below ERROR is already a reported issue
    logging.getLogger("kdk").setLevel(logging.DEBUG if debug else logging.ERROR)
