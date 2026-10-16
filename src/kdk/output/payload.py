"""Counts, paths and the JSON payload, kept free of rich so `--json` runs without it."""

from __future__ import annotations

import os
from collections import Counter

from kdk import __version__
from kdk.libs.validation.constants import SEVERITY_ERROR, SEVERITY_WARNING

# raised only when a field changes meaning or goes away; new fields keep it
FORMAT_VERSION = 1

PATH_KEYS = ("file", "include_file", "call_file")


def counts(issues):
    """Error, warning and muted totals across a `{category: [issue]}` map."""
    flat = [i for rows in issues.values() for i in rows]
    return severity_counts(flat)


def severity_counts(rows):
    """Error, warning and muted totals for a flat list of issues; muted ones count only as muted."""
    by_severity = Counter("muted" if i.get("muted") else i.get("severity") for i in rows)
    return by_severity[SEVERITY_ERROR], by_severity[SEVERITY_WARNING], by_severity["muted"]


def unmuted(issues):
    """The `{category: [issue]}` map without muted issues or empty categories."""
    kept = {category: [i for i in rows if not i.get("muted")] for category, rows in issues.items()}
    return {category: rows for category, rows in kept.items() if rows}


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


def _rows(rows, root):
    """Copies of the issues with skin-relative paths, sorted by file, line and message."""
    out = [{**issue, **{key: relative(issue[key], root) for key in PATH_KEYS if issue.get(key)}}
           for issue in rows]
    return sorted(out, key=lambda i: (i.get("file") or "", i.get("line") or 0, i.get("message") or ""))


def render_error(message):
    """Payload for a run that could not finish."""
    return {"format_version": FORMAT_VERSION, "kdk_version": __version__, "error": message}


def render_json(result, issues):
    """Machine-readable payload of the run's issues, muted ones too, with versions and notices."""
    total_errors, total_warnings, total_muted = counts(issues)
    return {
        "format_version": FORMAT_VERSION,
        "kdk_version": __version__,
        "kodi_release": result.get("kodi_release"),
        "info_source": result.get("info_source"),
        "notices": result.get("notices") or [],
        "skin_name": result["skin_name"],
        "timestamp": result["timestamp"],
        "duration_seconds": round(result["duration"], 2),
        "errors": total_errors,
        "warnings": total_warnings,
        "muted": total_muted,
        "categories": {c: _rows(rows, result["skin_path"]) for c, rows in issues.items() if rows},
    }
