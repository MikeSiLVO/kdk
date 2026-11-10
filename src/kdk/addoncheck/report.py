"""JSON payloads of an add-on run and of the add-on rules, in the shape of the skin report."""

from __future__ import annotations

from collections import Counter

from kdk import __version__ as KDK_VERSION

from ..output.payload import FORMAT_VERSION, _rows
from . import __version__
from .rules import ADDON_CHECKER, ERROR, HINT, PREFIXES, RULES, WARNING


def totals(issues: dict) -> tuple[int, int, int]:
    """Error, warning and hint totals across a `{category: [issue]}` map."""
    by_severity = Counter(row.get("severity") for rows in issues.values() for row in rows)
    return by_severity[ERROR], by_severity[WARNING], by_severity[HINT]


def render_json(result: dict, issues: dict) -> dict:
    """Machine-readable payload of an add-on run, with versions, add-on metadata and notices."""
    errors, warnings, hints = totals(issues)
    return {
        "format_version": FORMAT_VERSION,
        "kdk_version": KDK_VERSION,
        "addoncheck_version": __version__,
        "domain": "addon",
        "kodi_release": result.get("kodi_release"),
        "notices": result.get("notices") or [],
        "addon_name": result["addon_name"],
        "addon_id": result.get("addon_id", ""),
        "addon_version": result.get("addon_version", ""),
        "provider_name": result.get("provider_name", ""),
        "bundled": result.get("bundled", []),
        "timestamp": result["timestamp"],
        "duration_seconds": round(result["duration"], 2),
        "errors": errors,
        "warnings": warnings,
        "hints": hints,
        "muted": 0,
        "categories": {c: _rows(rows, result["addon_path"]) for c, rows in issues.items() if rows},
    }


def rule_rows() -> list[dict]:
    """Each add-on rule with its check, severity, description and kodi-addon-checker level."""
    return [{"id": rule, "check": PREFIXES[rule.split(".")[0]], "severity": severity, "description": text,
             "addon_checker": ADDON_CHECKER.get(rule)}
            for rule, (severity, text) in sorted(RULES.items())]


def render_rules() -> dict:
    """Payload listing the add-on rules alone."""
    return {"format_version": FORMAT_VERSION, "kdk_version": KDK_VERSION, "addoncheck_version": __version__,
            "addon_rules": rule_rows()}
