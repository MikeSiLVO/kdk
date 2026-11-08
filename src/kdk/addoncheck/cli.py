"""The `kdk addon` subcommands: validate an add-on folder, list the add-on rules."""

from __future__ import annotations

import json
import sys

from .releases import TARGETS
from .rules import ERROR, HINT, WARNING


def add_parser(subparsers):
    """Add `kdk addon` with its validate and rules subcommands."""
    parser = subparsers.add_parser("addon", help="Check a Kodi add-on against the xbmc/repo-scripts rules")
    commands = parser.add_subparsers(dest="addon_command")
    parser.set_defaults(func=lambda args: _usage(parser))

    validate = commands.add_parser("validate", help="Check an add-on folder")
    validate.add_argument("path", nargs="?", default=".", help="Path to the add-on folder")
    validate.add_argument("--release", required=True, choices=TARGETS, help="Kodi repo branch the add-on targets")
    validate.add_argument("--index", metavar="DIR",
                          help="Folder holding <branch>.xml.gz, the Kodi repo's add-on list of each branch")
    validate.add_argument("--tree", metavar="FILE",
                          help="`git ls-tree -r` output to take the file list and modes from, in place of the disk")
    validate.add_argument("--isolated", action="store_true",
                          help="Accepted for symmetry with `kdk validate`; the add-on checks read no config")
    validate.add_argument("--output", "-o", help="Write output to this path")
    validate.add_argument("--severity", choices=[ERROR, WARNING, HINT], help="Only show issues of this severity")
    validate.add_argument("--category", help="Only show categories matching this text (e.g. artwork)")
    validate.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too; hints never count")
    validate.add_argument("--exit-zero", action="store_true",
                          help="Exit 0 whenever the run finishes, issues or not; 2 still means kdk failed")
    validate.add_argument("--json", action="store_true", help="Output JSON instead of the terminal view")
    validate.add_argument("--github", action="store_true",
                          help="Emit GitHub Actions annotations so CI shows each issue inline")
    validate.set_defaults(func=cmd_validate)

    rules = commands.add_parser("rules", help="List every add-on rule id with what it reports")
    rules.add_argument("--json", action="store_true", help="Output JSON instead of the terminal view")
    rules.set_defaults(func=cmd_rules)


def _usage(parser) -> int:
    """Print the `kdk addon` help; returns 2, as for any command line missing its subcommand."""
    parser.print_help(sys.stderr)
    return 2


def _visible(issues: dict, args) -> dict:
    """The issues narrowed to the --severity and --category asked for."""
    wanted = (args.category or "").lower()
    result = {}
    for category, rows in issues.items():
        if wanted and wanted not in category.lower():
            continue
        if args.severity:
            rows = [row for row in rows if row.get("severity") == args.severity]
        if rows:
            result[category] = rows
    return result


def _exit_code(issues: dict, args) -> int:
    """1 on errors, or on warnings under --strict, never on hints; 0 under --exit-zero."""
    from .report import totals

    errors, warnings, _ = totals(issues)
    if args.exit_zero:
        return 0
    return 1 if errors or (args.strict and warnings) else 0


def cmd_validate(args) -> int:
    """Validate an add-on folder and report its issues; returns the exit code."""
    from kdk.__main__ import fail

    from .core import validate_addon
    from .report import render_json

    result = validate_addon(args.path, args.release, index_dir=args.index, tree=args.tree)
    if result["error"]:
        return fail(result["error"], args.json)
    issues = _visible(result["issues"], args)
    if args.json:
        text = json.dumps(render_json(result, issues), indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"Written: {args.output}", file=sys.stderr)
        else:
            print(text)
        return _exit_code(issues, args)

    from kdk.output.render import render_github, render_issues

    if args.github:
        render_github(issues)
    _render_summary(result, issues)
    render_issues(issues, result["addon_path"])
    return _exit_code(issues, args)


def _render_summary(result: dict, issues: dict) -> None:
    """Render the add-on, branch, notices and the totals per category."""
    from rich.markup import escape

    from kdk.output.render import console

    from .report import totals

    console.print()
    console.print(f"  [bold]{escape(result['addon_name'])}[/]  [dim]{result['addon_id']} {result['addon_version']}  "
                  f"{result['kodi_release']}  {result['duration']:.1f}s[/]")
    console.print()
    for notice in result["notices"]:
        console.print(f"  [yellow]{escape(notice)}[/]")
    if result["notices"]:
        console.print()
    for category, rows in issues.items():
        errors, warnings, hints = totals({category: rows})
        console.print(f"  [cyan]{category:<14}[/] {_count_text(errors, warnings, hints)}")
    errors, warnings, hints = totals(issues)
    console.print()
    console.print("  [green]No issues found[/]" if not (errors or warnings or hints)
                  else f"  {_count_text(errors, warnings, hints)}")
    console.print()


def _count_text(errors: int, warnings: int, hints: int) -> str:
    """`N errors, M warnings, K hints`, leaving out the zero counts."""
    parts = [(errors, "error", "red"), (warnings, "warning", "yellow"), (hints, "hint", "blue")]
    return ", ".join(f"[{colour}]{n} {word}{'' if n == 1 else 's'}[/]" for n, word, colour in parts if n)


def cmd_rules(args) -> int:
    """Print every add-on rule with what it reports, as the JSON payload when asked; returns 0."""
    from .report import render_rules

    payload = render_rules()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    from rich.markup import escape

    from kdk.output.render import console

    width = max(len(rule["id"]) for rule in payload["addon_rules"])
    for rule in payload["addon_rules"]:
        console.print(f"  [cyan]{rule['id']:<{width}}[/]  {rule['severity']:<7}  {escape(rule['description'])}")
    return 0
