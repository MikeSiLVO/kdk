"""Live progress for a validation run."""

from __future__ import annotations

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from .render import err_console


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

