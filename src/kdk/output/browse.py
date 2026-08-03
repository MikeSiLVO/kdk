"""Post-run picker so a finished run can be read instead of re-run."""

from __future__ import annotations

from .render import console, count_cells, render_issues, severity_counts


def _menu(issues):
    """Categories worth offering, in the order they are shown."""
    return [(category, rows) for category, rows in issues.items() if rows]


def browse(issues, skin_path):
    """Loop a category picker until quit; assumes a terminal and something to show."""
    entries = _menu(issues)
    if not entries:
        return

    width = max(len(category) for category, _ in entries)

    while True:
        console.print("  [bold]Show issues[/]")
        for index, (category, rows) in enumerate(entries, 1):
            count, detail = count_cells(*severity_counts(rows))
            console.print(f"    [dim]{index}[/]  [cyan]{category:<{width}}[/]  {count} {detail}")
        console.print("    [dim]a[/]  all")
        console.print("    [dim]q[/]  quit")
        console.print()

        try:
            choice = console.input("  [bold]>[/] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return

        console.print()
        if choice in ("q", ""):
            return
        if choice == "a":
            render_issues(issues, skin_path)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(entries):
            category, rows = entries[int(choice) - 1]
            render_issues({category: rows}, skin_path, show_category=False)
            continue
        console.print("  [dim]Pick a number, a, or q[/]")
        console.print()
