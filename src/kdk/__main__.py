"""CLI entry point; subcommands are `validate` and `gui` (run `kdk --help` for details)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def cmd_validate(args):
    from kdk.core import validate_skin, save_report, filter_include_warnings
    from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

    skin_path = os.path.abspath(args.path)
    if not os.path.isdir(skin_path):
        print(f"Error: {skin_path} is not a directory", file=sys.stderr)
        return 1

    overrides = {}
    if args.language:
        overrides["language"] = args.language
    if args.kodi_path:
        overrides["kodi_path"] = args.kodi_path

    def progress(step, total, message):
        if not args.json:
            print(f"  [{step}/{total}] {message}", file=sys.stderr)

    if not args.json:
        print(f"Validating: {skin_path}", file=sys.stderr)
        print(file=sys.stderr)

    result = validate_skin(skin_path, config_overrides=overrides, progress_callback=progress)

    if not args.show_include_warnings:
        result["issues"] = filter_include_warnings(result["issues"])

    if result["error"]:
        if args.json:
            json.dump({"error": result["error"]}, sys.stdout, indent=2)
        else:
            print(f"\nError: {result['error']}", file=sys.stderr)
        return 1

    if args.json:
        output = {
            "skin_name": result["skin_name"],
            "skin_path": result["skin_path"],
            "timestamp": result["timestamp"],
            "duration_seconds": round(result["duration"], 2),
            "categories": {},
        }
        for category, issues in result["issues"].items():
            real_issues = [i for i in issues if i.get("line", 0) > 0 or "not found" in i.get("message", "").lower()]
            if real_issues:
                output["categories"][category] = real_issues
        json.dump(output, sys.stdout, indent=2)
        print()
        return 0

    print(file=sys.stderr)
    print(f"  Skin: {result['skin_name']}", file=sys.stderr)
    print(f"  Time: {result['duration']:.1f}s", file=sys.stderr)
    print(file=sys.stderr)

    total_errors = 0
    total_warnings = 0

    for category, issues in result["issues"].items():
        real_issues = [i for i in issues if i.get("line", 0) > 0 or "not found" in i.get("message", "").lower()]
        if not real_issues:
            continue

        errors = sum(1 for i in real_issues if i.get("severity") == SEVERITY_ERROR)
        warnings = sum(1 for i in real_issues if i.get("severity") == SEVERITY_WARNING)
        other = len(real_issues) - errors - warnings
        total_errors += errors
        total_warnings += warnings

        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        if other:
            parts.append(f"{other} issue{'s' if other != 1 else ''}")

        print(f"  {category:20s} {', '.join(parts)}", file=sys.stderr)

    print(file=sys.stderr)
    print(f"  Total: {total_errors} errors, {total_warnings} warnings", file=sys.stderr)

    if args.report or args.output:
        report_path = save_report(result, args.output)
        print(f"\n  Report saved: {report_path}", file=sys.stderr)

    return 1 if total_errors > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        prog="kdk",
        description="KDK - Kodi skin validation tool (CLI). Use kdk-gui for the GUI.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    p_validate = subparsers.add_parser("validate", help="Validate a Kodi skin")
    p_validate.add_argument("path", help="Path to the skin addon directory")
    p_validate.add_argument("--report", action="store_true", help="Save text report to file")
    p_validate.add_argument("--json", action="store_true", help="Output JSON instead of terminal summary")
    p_validate.add_argument("--output", "-o", help="Output path for report file")
    p_validate.add_argument("--show-include-warnings", action="store_true",
                            help="Show warnings from include content (hidden by default)")
    p_validate.add_argument("--language", help="Language code (e.g. resource.language.en_gb)")
    p_validate.add_argument("--kodi-path", help="Path to Kodi installation")
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    setup_logging(args.debug)

    if not args.command:
        parser.print_help(sys.stderr)
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
