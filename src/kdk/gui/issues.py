"""Rows the GUI shows for a run: filtered, merged, sorted and grouped, with no Qt involved."""

from __future__ import annotations

from dataclasses import dataclass, field

from kdk.libs.validation.constants import SEVERITY_ERROR

BUCKETS: tuple[str, ...] = ("error", "warning", "include", "muted")
COLUMNS: tuple[str, ...] = ("severity", "file", "line", "rule", "include", "message")
GROUPINGS: tuple[str, ...] = ("category", "file", "rule", "severity", "none")
_SEARCHED = ("message", "file", "rule", "subject", "include_name")


@dataclass
class Row:
    """One tree row: an issue, or every issue in a file with the same message once merged."""

    category: str
    issues: list[dict]

    @property
    def issue(self) -> dict:
        """First issue of the row, the one opening and copying act on."""
        return self.issues[0]

    @property
    def lines(self) -> list[int]:
        """Line of each issue in the row."""
        return [i.get("line", 0) for i in self.issues]

    @property
    def is_error(self) -> bool:
        """True when the row's issues are errors."""
        return self.issue.get("severity") == SEVERITY_ERROR

    def key(self) -> tuple:
        """Key of the row's first issue, the one a selection of the row remembers."""
        return issue_key(self.category, self.issue)

    def holds(self, key: tuple | None) -> bool:
        """True when one of the row's issues has the key."""
        return any(issue_key(self.category, i) == key for i in self.issues)


@dataclass
class Group:
    """Rows under one tree heading, with their error, warning and muted counts."""

    name: str
    rows: list[Row] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    muted: int = 0


def issue_key(category: str, issue: dict) -> tuple:
    """Identity of an issue that survives a rebuild or a rerun, for keeping the selection."""
    return category, issue.get("file", ""), issue.get("line", 0), issue.get("rule", ""), issue.get("message", "")


def bucket(issue: dict) -> str:
    """Filter toggle that shows the issue: muted, error, include warning or warning."""
    if issue.get("muted"):
        return "muted"
    if issue.get("severity") == SEVERITY_ERROR:
        return "error"
    return "include" if issue.get("include_name") else "warning"


def matches(issue: dict, text: str) -> bool:
    """True when the issue's searched fields hold the text, ignoring case and slash direction."""
    needle = text.strip().lower().replace("\\", "/")
    return not needle or any(needle in str(issue.get(key) or "").lower().replace("\\", "/") for key in _SEARCHED)


def counts(issues: dict[str, list[dict]], text: str) -> dict[str, int]:
    """Issues per filter toggle among those the search text matches."""
    tally: dict[str, int] = {name: 0 for name in BUCKETS}
    for rows in issues.values():
        for issue in rows:
            if matches(issue, text):
                tally[bucket(issue)] += 1
    return tally


def shown_issues(issues: dict[str, list[dict]], shown: set[str], text: str) -> dict[str, list[dict]]:
    """The run's issues by category, keeping those the toggles and the search text let through."""
    return {category: [i for i in rows if bucket(i) in shown and matches(i, text)]
            for category, rows in issues.items()}


def build_rows(issues: dict[str, list[dict]], merge: bool) -> list[Row]:
    """Build a row per issue, or once merged, per file and message with every line in it."""
    rows: list[Row] = []
    merged: dict[tuple, Row] = {}
    for category, cat_issues in issues.items():
        for issue in cat_issues:
            if not merge:
                rows.append(Row(category, [issue]))
                continue
            key = (category, issue.get("file", ""), issue.get("severity"), bool(issue.get("muted")),
                   issue.get("message", ""))
            if key in merged:
                merged[key].issues.append(issue)
            else:
                merged[key] = Row(category, [issue])
                rows.append(merged[key])
    for row in merged.values():
        row.issues.sort(key=lambda i: i.get("line", 0))
    return rows


_SORT_KEYS = {
    "severity": lambda r: not r.is_error,
    "file": lambda r: r.issue.get("file", "").lower(),
    "line": lambda r: r.issue.get("line", 0),
    "rule": lambda r: r.issue.get("rule", ""),
    "include": lambda r: (not r.issue.get("include_name"), r.issue.get("include_name") or ""),
    "message": lambda r: r.issue.get("message", "").lower(),
}


def sort_rows(rows: list[Row], column: str | None, descending: bool) -> list[Row]:
    """Sort rows by the column, file and line breaking ties; errors first when no column is set."""
    by_place = sorted(rows, key=lambda r: (r.issue.get("file", "").lower(), r.issue.get("line", 0)))
    return sorted(by_place, key=_SORT_KEYS[column or "severity"], reverse=bool(column) and descending)


def _group_name(row: Row, grouping: str) -> str:
    """Heading the row falls under for the grouping; empty when ungrouped."""
    if grouping == "category":
        return row.category
    if grouping == "file":
        return row.issue.get("file", "")
    if grouping == "rule":
        return row.issue.get("rule", "")
    if grouping == "severity":
        return "Errors" if row.is_error else "Warnings"
    return ""


def group_rows(rows: list[Row], grouping: str, categories: list[str]) -> list[Group]:
    """Group rows under headings: categories in check order, others errors first, then by name."""
    groups: dict[str, Group] = {}
    for row in rows:
        name = _group_name(row, grouping)
        group = groups.setdefault(name, Group(name))
        group.rows.append(row)
        if row.issue.get("muted"):
            group.muted += len(row.issues)
        elif row.is_error:
            group.errors += len(row.issues)
        else:
            group.warnings += len(row.issues)
    if grouping == "category":
        rank = {name: n for n, name in enumerate(categories)}
        return sorted(groups.values(), key=lambda g: rank.get(g.name, len(rank)))
    if grouping == "severity":
        return sorted(groups.values(), key=lambda g: g.name != "Errors")
    if grouping == "none":
        return list(groups.values())
    return sorted(groups.values(), key=lambda g: (not g.errors, g.name.lower()))
