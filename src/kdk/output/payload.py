"""Counts, paths and the JSON payload, kept free of rich so `--json` runs without it."""

from __future__ import annotations

import os
from collections import Counter

from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING


def counts(issues):
    """Error and warning totals across a `{category: [issue]}` map."""
    flat = [i for rows in issues.values() for i in rows]
    return severity_counts(flat)


def severity_counts(rows):
    """Error and warning totals for one flat list of issues."""
    by_severity = Counter(i.get("severity") for i in rows)
    return by_severity[SEVERITY_ERROR], by_severity[SEVERITY_WARNING]


def relative(path, root):
    """Path relative to a root, falling back to the original when it isn't under it."""
    if not path:
        return ""
    try:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path
    # A path outside root relativizes to a run of `..`, which helps nobody
    return path if rel.startswith("../") else rel


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
