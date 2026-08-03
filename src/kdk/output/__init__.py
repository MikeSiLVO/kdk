"""Terminal presentation for the CLI: progress, rendering, browsing, run cache."""

from .browse import browse
from .cache import load as load_run, save as save_run
from .progress import RunProgress, quiet_engine_logging
from .render import (
    console,
    count_cells,
    counts,
    err_console,
    render_github,
    render_issues,
    render_json,
    render_summary,
    severity_counts,
)

__all__ = [
    "RunProgress",
    "browse",
    "console",
    "count_cells",
    "counts",
    "err_console",
    "load_run",
    "quiet_engine_logging",
    "render_github",
    "render_issues",
    "render_json",
    "render_summary",
    "save_run",
    "severity_counts",
]
