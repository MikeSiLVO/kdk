"""Rich rendering of validation results for the terminal."""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

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
    """Short label and colour for a severity, defaulting to a dim `info`."""
    return SEVERITY_STYLE.get(severity, ("info", "dim"))


def _plural(count, noun):
    return noun if count == 1 else f"{noun}s"


def counts(issues):
    """Error and warning totals across a `{category: [issue]}` map."""
    flat = [i for rows in issues.values() for i in rows]
    return severity_counts(flat)


def severity_counts(rows):
    """Error and warning totals for one flat list of issues."""
    by_severity = Counter(i.get("severity") for i in rows)
    return by_severity[SEVERITY_ERROR], by_severity[SEVERITY_WARNING]


def count_cells(errors, warnings):
    """`N errors, M warnings` split after the leading number so a table can align on it."""
    if errors and warnings:
        return (
            f"[red]{errors}[/]",
            f"[red]{_plural(errors, 'error')}[/], [yellow]{warnings} {_plural(warnings, 'warning')}[/]",
        )
    if errors:
        return f"[red]{errors}[/]", f"[red]{_plural(errors, 'error')}[/]"
    return f"[yellow]{warnings}[/]", f"[yellow]{_plural(warnings, 'warning')}[/]"


def render_summary(result, issues):
    """One row per category that has something to say, then the totals line."""
    console.print()
    console.print(f"  [bold]{result['skin_name']}[/]  [dim]{result['duration']:.1f}s[/]")
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

    total_errors, total_warnings = counts(issues)
    if not total_errors and not total_warnings:
        console.print("  [green]No issues found[/]")
    else:
        count, detail = count_cells(total_errors, total_warnings)
        console.print(f"  {count} {detail}")
    console.print()


def _relative(path, root):
    """Path relative to the skin root, falling back to the original on any mismatch."""
    if not path:
        return ""
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


def render_issues(issues, skin_path, *, show_category=True):
    """Print issues grouped by file and sorted by line, collapsing repeats of one message."""
    by_file = defaultdict(list)
    for category, rows in issues.items():
        for issue in rows:
            by_file[_relative(issue.get("file"), skin_path)].append((category, issue))

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
    """Emit one workflow command per issue so CI shows them as inline annotations."""
    # Annotations anchor to the checkout root, which is not always the skin root
    root = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()

    for category, rows in issues.items():
        for issue in rows:
            level = {SEVERITY_ERROR: "error", SEVERITY_WARNING: "warning"}.get(
                issue.get("severity"), "notice"
            )
            path = _relative(issue.get("file"), root)
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


def render_json(result, issues):
    """Machine-readable payload mirroring what the terminal shows."""
    total_errors, total_warnings = counts(issues)
    return {
        "skin_name": result["skin_name"],
        "skin_path": result["skin_path"],
        "timestamp": result["timestamp"],
        "duration_seconds": round(result["duration"], 2),
        "errors": total_errors,
        "warnings": total_warnings,
        "categories": {c: rows for c, rows in issues.items() if rows},
    }
