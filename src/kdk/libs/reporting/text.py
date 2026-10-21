"""Plain-text validation report writer."""

import os
from datetime import datetime
from ..validation.constants import SEVERITY_ERROR, SEVERITY_WARNING
from ..validation.suppress import muted_note


def generate_text_report(all_issues, skin_name, skin_path, output_path=None):
    """Generate the plain-text report and write it to a path when given; returns text and path."""
    filtered = {category: issues for category, issues in all_issues.items() if issues}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_errors = 0
    total_warnings = 0
    total_muted = 0
    for issues in filtered.values():
        for issue in issues:
            sev = issue.get("severity", "warning")
            if issue.get("muted"):
                total_muted += 1
            elif sev == SEVERITY_ERROR:
                total_errors += 1
            elif sev == SEVERITY_WARNING:
                total_warnings += 1

    lines = []
    lines.append("=" * 80)
    lines.append("KODI SKIN VALIDATION REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Skin:      {skin_name}")
    lines.append(f"Path:      {skin_path}")
    lines.append(f"Generated: {timestamp}")
    lines.append(f"Total:     {total_errors} errors, {total_warnings} warnings"
                 + (f", {total_muted} muted" if total_muted else ""))

    lines.append("")

    lines.append("-" * 80)
    lines.append(f"{'Category':<25s} {'Errors':>8s} {'Warnings':>10s}")
    lines.append("-" * 80)

    for category, issues in filtered.items():
        counted = [i for i in issues if not i.get("muted")]
        errors = sum(1 for i in counted if i.get("severity") == SEVERITY_ERROR)
        warnings = sum(1 for i in counted if i.get("severity") == SEVERITY_WARNING)
        muted = len(issues) - len(counted)
        if errors or warnings or muted:
            lines.append(f"{category:<25s} {errors:>8d} {warnings:>10d}" + (f"   {muted} muted" if muted else ""))

    lines.append("-" * 80)
    lines.append("")

    for category, issues in filtered.items():
        if not issues:
            continue

        lines.append("")
        lines.append(f"{'=' * 60}")
        lines.append(f" {category.upper()} ({len(issues)} issues)")
        lines.append(f"{'=' * 60}")
        lines.append("")

        by_file = {}
        for issue in issues:
            file_path = issue.get("file", "")
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(issue)

        for file_path in sorted(by_file.keys()):
            file_issues = by_file[file_path]
            rel_path = file_path
            if skin_path and file_path.startswith(skin_path):
                rel_path = os.path.relpath(file_path, skin_path)

            lines.append(f"  {rel_path}{_muted_count(file_issues)}")

            by_mute = {}
            for issue in sorted(file_issues, key=lambda i: i.get("line", 0)):
                mute = issue.get("muted")
                if mute:
                    by_mute.setdefault((mute["line"], mute.get("reason") or ""), []).append(issue)
                else:
                    lines.append(f"    {_row(issue)}")
            for key in sorted(by_mute):
                lines.append(f"    {muted_note(by_mute[key][0])}")
                lines.extend(f"      {_row(issue)}" for issue in by_mute[key])

            lines.append("")

    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)

    text = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

    return text, output_path


def _row(issue):
    """One issue as its severity, line and message, plus the include it came from."""
    label = issue.get("severity", SEVERITY_WARNING).upper()
    inc_name = issue.get("include_name", "")
    inc_suffix = f"  (from include: {inc_name})" if inc_name else ""
    return f"{label:<8s} line {issue.get('line', 0):<5d} {issue.get('message', '')}{inc_suffix}"


def _muted_count(issues):
    """Heading note counting a file's muted issues per severity; empty when none are muted."""
    muted = [issue.get("severity", SEVERITY_WARNING) for issue in issues if issue.get("muted")]
    parts = []
    for sev in (SEVERITY_ERROR, SEVERITY_WARNING):
        count = muted.count(sev)
        if count:
            parts.append(f"{count} muted {sev}{'s' if count != 1 else ''}")
    return f"  ({', '.join(parts)})" if parts else ""
