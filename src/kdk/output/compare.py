"""Findings a head run adds, mutes or fixes against a base run, kept free of rich like the JSON."""

from __future__ import annotations

import re

from kdk import __version__

from .payload import FORMAT_VERSION

STATUSES = ("new", "muted", "fixed")

# caps the quadratic nearest-line pairing of one finding's rows
_PAIRING_LIMIT = 250_000

# a strings.po per language repeats one finding about a shared string id in every language
_LANGUAGE_FILE = re.compile(r"(^|/)resource\.language\.[^/]+/")


def mismatch(base, head):
    """Why two runs cannot be compared, or None when kdk, format and Kodi release all match."""
    for key, what in (("format_version", "format versions"), ("kdk_version", "kdk versions"),
                      ("kodi_release", "Kodi releases")):
        if base.get(key) != head.get(key):
            return f"base and head have different {what}: {base.get(key)} and {head.get(key)}"
    return None


def _rows(run):
    """Every row of a run's payload, its category dropped since the rule id carries the check."""
    return [row for rows in run.get("categories", {}).values() for row in rows]


def _key(row):
    """What makes two rows the same finding: rule, file and subject, never line or message."""
    return row.get("rule"), row.get("file"), row.get("subject")


def _pair(base_rows, head_rows):
    """Pair base and head rows of one finding, nearest first up to a cap; returns pairs and rest."""
    base = sorted(base_rows, key=lambda r: r.get("line") or 0)
    head = sorted(head_rows, key=lambda r: r.get("line") or 0)
    if len(base) * len(head) > _PAIRING_LIMIT:
        count = min(len(base), len(head))
        return list(zip(base[:count], head[:count])), base[count:], head[count:]
    candidates = sorted((abs((b.get("line") or 0) - (h.get("line") or 0)), j, i)
                        for i, b in enumerate(base) for j, h in enumerate(head))
    pairs, used_base, used_head = [], set(), set()
    for _distance, j, i in candidates:
        if i not in used_base and j not in used_head:
            pairs.append((base[i], head[j]))
            used_base.add(i)
            used_head.add(j)
    return (pairs, [b for i, b in enumerate(base) if i not in used_base],
            [h for j, h in enumerate(head) if j not in used_head])


def _row(row, status, **extra):
    """One compare row: rule, severity, file, line, subject, message and status, then any extra."""
    out = {key: row.get(key) for key in ("rule", "severity", "file", "line", "subject", "message")}
    out["status"] = status
    out.update(extra)
    return out


def _fold(rows):
    """Fold a finding repeated across language files into one row with count, files and lines."""
    groups, out = {}, []
    for row in rows:
        if _LANGUAGE_FILE.search(row.get("file") or ""):
            groups.setdefault((row["status"], row["rule"], row["subject"]), []).append(row)
        else:
            out.append(row)
    for group in groups.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda r: (r["file"], r["line"] or 0))
        out.append({**group[0], "count": len(group), "files": [r["file"] for r in group],
                    "lines": [r["line"] for r in group]})
    return out


def compare(base, head):
    """Payload of the findings head adds, mutes or fixes against base, with head's run metadata."""
    by_key = {}
    for side, run in (("base", base), ("head", head)):
        for row in _rows(run) if run else []:
            by_key.setdefault(_key(row), {"base": [], "head": []})[side].append(row)

    rows = []
    for sides in by_key.values():
        pairs, fixed, new = _pair(sides["base"], sides["head"])
        rows += [_row(b, "fixed", **({"muted": b["muted"]} if b.get("muted") else {})) for b in fixed]
        for h in new:
            rows.append(_row(h, "muted", muted=h["muted"], in_base=False) if h.get("muted") else _row(h, "new"))
        rows += [_row(h, "muted", muted=h["muted"], in_base=True) for b, h in pairs
                 if h.get("muted") and not b.get("muted")]

    rows = sorted(_fold(rows), key=lambda r: (STATUSES.index(r["status"]), r["file"] or "", r["line"] or 0,
                                               r["rule"] or "", r["subject"] or "", r["message"] or ""))
    totals = {status: sum(r.get("count", 1) for r in rows if r["status"] == status) for status in STATUSES}
    return {
        "format_version": FORMAT_VERSION,
        "kdk_version": __version__,
        "kodi_release": head.get("kodi_release"),
        "info_source": head.get("info_source"),
        "notices": head.get("notices") or [],
        "skin_name": head.get("skin_name"),
        "base": bool(base),
        **totals,
        "head": {key: head.get(key, 0) for key in ("errors", "warnings", "muted")},
        "rows": rows,
    }
