"""Plain-text validation report writer."""

import os
from datetime import datetime
from .. import utils
from ..validation.constants import SEVERITY_ERROR, SEVERITY_WARNING


def generate_text_report(all_issues, skin_name, skin_path, output_path=None):
    """Build a plain-text report from `all_issues`; writes to `output_path` if given. Returns `(text, output_path)`."""

    filtered = {}
    total_runtime_excluded = 0
    for category, issues in all_issues.items():
        normal = [i for i in issues if not utils.is_runtime_generated_file(i.get("file", ""))]
        total_runtime_excluded += len(issues) - len(normal)
        if normal:
            filtered[category] = normal

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_errors = 0
    total_warnings = 0
    for issues in filtered.values():
        for issue in issues:
            sev = issue.get("severity", "warning")
            if sev == SEVERITY_ERROR:
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
    lines.append(f"Total:     {total_errors} errors, {total_warnings} warnings")

    if total_runtime_excluded > 0:
        lines.append(f"Excluded:  {total_runtime_excluded} runtime-generated issues")

    lines.append("")

    # Summary table
    lines.append("-" * 80)
    lines.append(f"{'Category':<25s} {'Errors':>8s} {'Warnings':>10s}")
    lines.append("-" * 80)

    for category, issues in filtered.items():
        errors = sum(1 for i in issues if i.get("severity") == SEVERITY_ERROR)
        warnings = sum(1 for i in issues if i.get("severity") == SEVERITY_WARNING)
        if errors or warnings:
            lines.append(f"{category:<25s} {errors:>8d} {warnings:>10d}")

    lines.append("-" * 80)
    lines.append("")

    # Detailed issues by category
    for category, issues in filtered.items():
        if not issues:
            continue

        lines.append("")
        lines.append(f"{'=' * 60}")
        lines.append(f" {category.upper()} ({len(issues)} issues)")
        lines.append(f"{'=' * 60}")
        lines.append("")

        # Group by file
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

            lines.append(f"  {rel_path}")

            for issue in sorted(file_issues, key=lambda i: i.get("line", 0)):
                line_num = issue.get("line", 0)
                message = issue.get("message", "")
                sev = issue.get("severity", "warning")
                marker = "E" if sev == SEVERITY_ERROR else "W"

                inc_name = issue.get("include_name", "")
                inc_suffix = f"  (from include: {inc_name})" if inc_name else ""

                lines.append(f"    {marker} L{line_num:<5d} {message}{inc_suffix}")

            lines.append("")

    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)

    text = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

    return text, output_path
