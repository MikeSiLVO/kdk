"""Rich rendering of validation results for the terminal."""

from __future__ import annotations

import os
import sys
from collections import defaultdict

from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

from .payload import counts, relative, severity_counts

# Redirected output would otherwise wrap at rich's 80-column default
_PIPE_WIDTH = 200

# Auto-highlighting colours numbers and paths, fighting the severity colour
console = Console(width=None if sys.stdout.isatty() else _PIPE_WIDTH, highlight=False)
err_console = Console(stderr=True, width=None if sys.stderr.isatty() else _PIPE_WIDTH, highlight=False)

SEVERITY_STYLE = {
    SEVERITY_ERROR: ("error", "red"),
    SEVERITY_WARNING: ("warn", "yellow"),
}


def severity_parts(severity):
    """Short label and color for a severity, defaulting to a dim `info`."""
    return SEVERITY_STYLE.get(severity, ("info", "dim"))


_COUNT_WORDS = (("error", "errors", "red"), ("warning", "warnings", "yellow"), ("muted", "muted", "dim"))


def count_cells(errors, warnings, muted=0):
    """`N errors, M warnings, K muted` split after the leading number so a table can align on it."""
    parts = [(n, one if n == 1 else many, colour)
             for n, (one, many, colour) in zip((errors, warnings, muted), _COUNT_WORDS) if n]
    lead, word, colour = parts[0] if parts else (0, "warnings", "yellow")
    detail = ", ".join([f"[{colour}]{word}[/]"] + [f"[{c}]{n} {w}[/]" for n, w, c in parts[1:]])
    return f"[{colour}]{lead}[/]", detail


def render_summary(result, issues):
    """Render the release, notices, a row per category with something to say, and the totals."""
    release = result.get("kodi_release")
    checked = f"Kodi {release.capitalize()}  " if release else ""
    console.print()
    console.print(f"  [bold]{result['skin_name']}[/]  [dim]{checked}{result['duration']:.1f}s[/]")
    console.print()

    notices = result.get("notices") or []
    for notice in notices:
        console.print(f"  [yellow]{escape(notice)}[/]")
    if notices:
        console.print()

    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 1))
    table.add_column("category", style="cyan", no_wrap=True)
    table.add_column("count", justify="right", no_wrap=True)
    table.add_column("detail", no_wrap=True)

    for category, rows in issues.items():
        if not rows:
            continue
        count, detail = count_cells(*severity_counts(rows))
        table.add_row(category, count, detail)

    if table.row_count:
        console.print(Padding(table, (0, 0, 0, 2), expand=False))
        console.print()

    total_errors, total_warnings, total_muted = counts(issues)
    if not total_errors and not total_warnings:
        console.print("  [green]No issues found[/]" + (f"  [dim]{total_muted} muted[/]" if total_muted else ""))
    else:
        count, detail = count_cells(total_errors, total_warnings, total_muted)
        console.print(f"  {count} {detail}")
    console.print()


def render_issues(issues, skin_path, *, show_category=True):
    """Render issues grouped by file and sorted by line, collapsing repeats of one message."""
    by_file = defaultdict(list)
    for category, rows in issues.items():
        for issue in rows:
            by_file[relative(issue.get("file"), skin_path)].append((category, issue))

    if not by_file:
        console.print("  [green]No issues found[/]")
        console.print()
        return

    for path in sorted(by_file):
        entries = sorted(by_file[path], key=lambda e: e[1].get("line") or 0)

        # One include used in N places repeats its issue N times, line apart
        grouped = {}
        for category, issue in entries:
            key = (category, issue.get("message"), issue.get("severity"))
            grouped.setdefault(key, []).append(issue.get("line") or 0)

        console.print(f"  [bold]{path or '(no file)'}[/]")
        for (category, message, severity), lines in grouped.items():
            label, colour = severity_parts(severity)
            line = Text("    ")
            line.append(f"{min(lines):>6}", style="dim")
            line.append(f"  {label:<5}", style=colour)
            if show_category:
                line.append(f"  {category:<14}", style="cyan dim")
            line.append(f"  {message}")
            if len(lines) > 1:
                line.append(f"  (x{len(lines)})", style="dim")
            console.print(line)
        console.print()


def _escape(text, *, prop=False):
    """Escape for a workflow command; property values also swallow `,` and `:`."""
    out = str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        out = out.replace(",", "%2C").replace(":", "%3A")
    return out


def render_github(issues):
    """Render one workflow command per issue so CI shows them as inline annotations."""
    # Annotations anchor to the checkout root, which is not always the skin root
    root = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()

    for category, rows in issues.items():
        for issue in rows:
            level = {SEVERITY_ERROR: "error", SEVERITY_WARNING: "warning"}.get(
                issue.get("severity"), "notice"
            )
            path = relative(issue.get("file"), root)
            parts = [f"title={_escape(category, prop=True)}"]
            if path:
                parts.insert(0, f"file={_escape(path, prop=True)}")
            if issue.get("line"):
                parts.insert(-1, f"line={issue['line']}")
            console.print(
                f"::{level} {','.join(parts)}::{_escape(issue.get('message', ''))}",
                highlight=False,
                markup=False,
                soft_wrap=True,
            )

