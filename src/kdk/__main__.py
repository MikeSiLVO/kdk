"""CLI entry point; run `kdk --help` for the available subcommands."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

# kdk could not finish the run; argparse also uses 2 for a bad command line
FAILED = 2


def fail(message, as_json):
    """Report a run kdk could not finish, as the JSON error object when asked; returns 2."""
    if as_json:
        from kdk.output.payload import render_error
        print(json.dumps(render_error(message), indent=2))
    else:
        print(f"Error: {message}", file=sys.stderr)
    return FAILED


class Parser(argparse.ArgumentParser):
    """Argument parser that reports a bad command line as the JSON error object under --json."""

    def error(self, message):
        """Exit 2 after the usage, with the error object on stdout when JSON was asked for."""
        if "--json" not in sys.argv[1:]:
            super().error(message)
        self.print_usage(sys.stderr)
        sys.exit(fail(message, True))


def visible_issues(raw, args):
    """Apply the include filter and any --severity/--category narrowing."""
    from kdk.core import filter_include_warnings

    issues = raw if args.show_include_warnings else filter_include_warnings(raw)

    wanted = (args.category or "").lower()
    result = {}
    for category, rows in issues.items():
        if wanted and wanted not in category.lower():
            continue
        if args.severity:
            rows = [i for i in rows if i.get("severity") == args.severity]
        if rows:
            result[category] = rows
    return result


def exit_code(issues, args):
    """1 on errors, or warnings counted as failures, muted ones never; 0 when asked."""
    from kdk.output.payload import counts

    if args.exit_zero:
        return 0
    errors, warnings, _ = counts(issues)
    if errors:
        return 1
    return 1 if args.strict and warnings else 0


def cmd_validate(args):
    """Validate a skin and cache its run, then show, save or print its issues; returns exit code."""
    from kdk.core import CHECK_SEQUENCE, save_report, validate_skin
    from kdk.output.cache import save as save_run
    from kdk.output.payload import render_json

    skin_path = os.path.abspath(args.path)
    if not os.path.isdir(skin_path):
        return fail(f"{skin_path} is not a directory", args.json)

    overrides = {}
    if args.language:
        overrides["language"] = args.language
    if args.kodi_path:
        overrides["kodi_path"] = args.kodi_path
    if args.release:
        overrides["kodi_release"] = args.release

    if args.json or args.quiet:
        result = validate_skin(skin_path, config_overrides=overrides, isolated=args.isolated)
    else:
        from kdk.output.progress import RunProgress
        with RunProgress(skin_path, len(CHECK_SEQUENCE)) as bar:
            result = validate_skin(skin_path, config_overrides=overrides, isolated=args.isolated, progress_callback=bar.update)

    if result["error"]:
        return fail(result["error"], args.json)

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
        return exit_code(issues, args)

    from kdk.output.browse import browse
    from kdk.output.payload import unmuted
    from kdk.output.render import console, render_github, render_issues, render_summary

    listed = unmuted(issues)
    if args.github:
        render_github(listed)

    render_summary(result, issues)

    if args.report or args.output:
        report_path = save_report(result, args.output)
        console.print(f"  [dim]Report saved: {report_path}[/]")
        console.print()

    if listed and not args.quiet:
        interactive = console.is_terminal and not args.list and sys.stdin.isatty()
        if interactive:
            browse(listed, skin_path)
        else:
            render_issues(listed, skin_path)

    return exit_code(issues, args)


def cmd_issues(args):
    """Show the issues of the last validate run of a skin; returns the exit code."""
    from kdk.output.cache import load as load_run
    from kdk.output.payload import render_json

    skin_path = os.path.abspath(args.path)
    run = load_run(skin_path)
    if not run:
        return fail(f"No cached run for {skin_path} - run 'kdk validate' first", args.json)

    issues = visible_issues(run["issues"], args)

    if args.json:
        print(json.dumps(render_json(run, issues), indent=2))
        return exit_code(issues, args)

    from kdk.output.browse import browse
    from kdk.output.payload import unmuted
    from kdk.output.render import console, render_github, render_issues, render_summary

    listed = unmuted(issues)
    if args.github:
        render_github(listed)

    console.print()
    console.print(f"  [bold]{run['skin_name']}[/]  [dim]validated {run['timestamp']}[/]")
    console.print()

    if args.browse and console.is_terminal and sys.stdin.isatty():
        browse(listed, skin_path)
    else:
        render_issues(listed, skin_path)

    if args.summary:
        render_summary(run, issues)

    return exit_code(issues, args)


def cmd_rules(args):
    """Print every rule id with what it reports, as the JSON payload when asked; returns 0."""
    from kdk.output.payload import render_rules

    payload = render_rules()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    from rich.markup import escape

    from kdk.output.render import console

    width = max(len(rule["id"]) for rule in payload["rules"])
    for rule in payload["rules"]:
        console.print(f"  [cyan]{rule['id']:<{width}}[/]  {escape(rule['description'])}")
    return 0


def add_filters(parser):
    """Add the flags shared by `validate` and `issues`."""
    from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

    parser.add_argument("--severity", choices=[SEVERITY_ERROR, SEVERITY_WARNING],
                        help="Only show issues of this severity")
    parser.add_argument("--category", help="Only show categories matching this text (e.g. fonts)")
    parser.add_argument("--show-include-warnings", action="store_true",
                        help="Include warnings that come from include content (hidden by default)")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too, not just errors")
    parser.add_argument("--exit-zero", action="store_true",
                        help="Exit 0 whenever the run finishes, issues or not; 2 still means kdk failed")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of the terminal view")
    parser.add_argument("--github", action="store_true",
                        help="Emit GitHub Actions annotations so CI shows each issue inline")


def main():
    """Run the subcommand given; returns its exit code, 2 if none was given or it crashed."""
    from kdk.libs.addon.addon import Addon

    parser = Parser(
        prog="kdk",
        description="KDK - Kodi skin validation tool (CLI). Use kdk-gui for the GUI.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    p_validate = subparsers.add_parser("validate", help="Validate a Kodi skin")
    # SUPPRESS so omitting it here keeps the same flag given before the subcommand
    p_validate.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                            help="Enable debug logging")
    p_validate.add_argument("path", nargs="?", default=".", help="Path to the skin addon directory")
    p_validate.add_argument("--quiet", "-q", action="store_true", help="Summary only, no issue list")
    p_validate.add_argument("--list", action="store_true", help="Print every issue instead of the picker")
    p_validate.add_argument("--report", action="store_true", help="Also save the full text report")
    p_validate.add_argument("--output", "-o", help="Write output to this path")
    p_validate.add_argument("--language", help="Language code (e.g. resource.language.en_gb)")
    p_validate.add_argument("--kodi-path", help="Path to Kodi installation")
    p_validate.add_argument("--release", choices=[r["name"] for r in Addon.RELEASES],
                            help="Kodi release to check against, instead of the one addon.xml gives")
    p_validate.add_argument("--isolated", action="store_true",
                            help="Ignore the user config and the skin's .kdk.json")
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

    p_rules = subparsers.add_parser("rules", help="List every rule id with what it reports")
    p_rules.add_argument("--json", action="store_true", help="Output JSON instead of the terminal view")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args()

    from kdk.output.logs import quiet_engine_logging
    quiet_engine_logging(args.debug)

    if not args.command:
        parser.print_help(sys.stderr)
        return FAILED

    try:
        return args.func(args)
    except Exception as e:
        traceback.print_exc()
        return fail(f"kdk crashed: {e!r}", args.json)


if __name__ == "__main__":
    sys.exit(main())
