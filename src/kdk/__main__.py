"""CLI entry point; run `kdk --help` for the available subcommands."""

from __future__ import annotations

import argparse
import json
import os
import sys


def real_issues(issues):
    """Drop the sentinel rows checks return when clean: no severity and no source line."""
    return [i for i in issues if i.get("severity") or (i.get("line") or 0) > 0]


def visible_issues(raw, args):
    """Apply the include filter, sentinel filter, and any --severity/--category narrowing."""
    from kdk.core import filter_include_warnings

    issues = raw if args.show_include_warnings else filter_include_warnings(raw)

    wanted = (args.category or "").lower()
    result = {}
    for category, rows in issues.items():
        if wanted and wanted not in category.lower():
            continue
        rows = real_issues(rows)
        if args.severity:
            rows = [i for i in rows if i.get("severity") == args.severity]
        if rows:
            result[category] = rows
    return result


def exit_code(issues, strict):
    """1 on errors, or on anything at all under --strict."""
    from kdk.output import counts

    errors, warnings = counts(issues)
    if errors:
        return 1
    return 1 if strict and warnings else 0


def cmd_validate(args):
    from kdk.core import CHECK_SEQUENCE, save_report, validate_skin
    from kdk.output import (
        RunProgress, browse, console, render_github, render_issues, render_json,
        render_summary, save_run,
    )

    skin_path = os.path.abspath(args.path)
    if not os.path.isdir(skin_path):
        print(f"Error: {skin_path} is not a directory", file=sys.stderr)
        return 1

    overrides = {}
    if args.language:
        overrides["language"] = args.language
    if args.kodi_path:
        overrides["kodi_path"] = args.kodi_path

    with RunProgress(skin_path, len(CHECK_SEQUENCE), enabled=not args.json and not args.quiet) as bar:
        result = validate_skin(skin_path, config_overrides=overrides, progress_callback=bar.update)

    if result["error"]:
        if args.json:
            json.dump({"error": result["error"]}, sys.stdout, indent=2)
            print()
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    save_run(skin_path, result, result["issues"])
    issues = visible_issues(result["issues"], args)

    if args.json:
        payload = render_json(result, issues)
        text = json.dumps(payload, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"Written: {args.output}", file=sys.stderr)
        else:
            print(text)
        return exit_code(issues, args.strict)

    if args.github:
        render_github(issues)

    render_summary(result, issues)

    if args.report or args.output:
        report_path = save_report(result, args.output)
        console.print(f"  [dim]Report saved: {report_path}[/]")
        console.print()

    if issues and not args.quiet:
        interactive = console.is_terminal and not args.list and sys.stdin.isatty()
        if interactive:
            browse(issues, skin_path)
        else:
            render_issues(issues, skin_path)

    return exit_code(issues, args.strict)


def cmd_issues(args):
    from kdk.output import browse, console, load_run, render_github, render_issues, render_json, render_summary

    skin_path = os.path.abspath(args.path)
    run = load_run(skin_path)
    if not run:
        print(f"No cached run for {skin_path} - run 'kdk validate' first", file=sys.stderr)
        return 1

    issues = visible_issues(run["issues"], args)

    if args.json:
        print(json.dumps(render_json(run, issues), indent=2))
        return exit_code(issues, args.strict)

    if args.github:
        render_github(issues)

    console.print()
    console.print(f"  [bold]{run['skin_name']}[/]  [dim]validated {run['timestamp']}[/]")
    console.print()

    if args.browse and console.is_terminal and sys.stdin.isatty():
        browse(issues, skin_path)
    else:
        render_issues(issues, skin_path)

    if args.summary:
        render_summary(run, issues)

    return exit_code(issues, args.strict)


def add_filters(parser):
    """Flags shared by `validate` and `issues` so both narrow results the same way."""
    from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

    parser.add_argument("--severity", choices=[SEVERITY_ERROR, SEVERITY_WARNING],
                        help="Only show issues of this severity")
    parser.add_argument("--category", help="Only show categories matching this text (e.g. fonts)")
    parser.add_argument("--show-include-warnings", action="store_true",
                        help="Include warnings that come from include content (hidden by default)")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too, not just errors")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of the terminal view")
    parser.add_argument("--github", action="store_true",
                        help="Emit GitHub Actions annotations so CI shows each issue inline")


def main():
    parser = argparse.ArgumentParser(
        prog="kdk",
        description="KDK - Kodi skin validation tool (CLI). Use kdk-gui for the GUI.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    p_validate = subparsers.add_parser("validate", help="Validate a Kodi skin")
    # SUPPRESS so omitting it here does not overwrite the same flag given
    # before the subcommand.
    p_validate.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                            help="Enable debug logging")
    p_validate.add_argument("path", nargs="?", default=".", help="Path to the skin addon directory")
    p_validate.add_argument("--quiet", "-q", action="store_true", help="Summary only, no issue list")
    p_validate.add_argument("--list", action="store_true", help="Print every issue instead of the picker")
    p_validate.add_argument("--report", action="store_true", help="Also save the full text report")
    p_validate.add_argument("--output", "-o", help="Write output to this path")
    p_validate.add_argument("--language", help="Language code (e.g. resource.language.en_gb)")
    p_validate.add_argument("--kodi-path", help="Path to Kodi installation")
    add_filters(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    p_issues = subparsers.add_parser("issues", help="Show issues from the last validate run")
    p_issues.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                          help="Enable debug logging")
    p_issues.add_argument("path", nargs="?", default=".", help="Path to the skin addon directory")
    p_issues.add_argument("--browse", action="store_true", help="Pick a category instead of printing everything")
    p_issues.add_argument("--summary", action="store_true", help="Append the per-category summary")
    add_filters(p_issues)
    p_issues.set_defaults(func=cmd_issues)

    args = parser.parse_args()

    from kdk.output import quiet_engine_logging
    quiet_engine_logging(args.debug)

    if not args.command:
        parser.print_help(sys.stderr)
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
