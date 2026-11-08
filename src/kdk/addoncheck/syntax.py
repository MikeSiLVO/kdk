"""Python checks the Kodi repo's checker runs: syntax on the oldest Python, entry point size."""

from __future__ import annotations

import ast
import warnings

from .radon.raw import analyze
from .releases import PYTHON_FLOOR
from .rules import finding
from .submission import Submission

# logical lines from which the Kodi repo's checker calls an entry point complex
ENTRYPOINT_LINES = 15


def check(sub: Submission) -> list[dict]:
    """Issue rows for Python files that do not decode or parse, and entry points too long."""
    rows = []
    sources = {}
    for rel in sorted(sub.files):
        if not rel.endswith(".py"):
            continue
        try:
            with open(sub.abs(rel), "rb") as f:
                data = f.read()
        except OSError:
            continue
        try:
            source = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            rows.append(finding("py.syntax", sub.abs(rel), data[:e.start].count(b"\n") + 1, rel,
                                f"{rel} is not saved as UTF-8, so Kodi cannot load it"))
            continue
        problem = _parse_problem(source)
        if problem:
            line, message = problem
            rows.append(finding("py.syntax", sub.abs(rel), line, rel, f"{rel} does not parse: {message}"))
            continue
        sources[rel] = source
    if sub.root is None or sub.broken:
        return rows
    for ext in sub.root.findall("extension"):
        library = (ext.get("library") or "").replace("\\", "/")
        if library not in sources:
            continue
        try:
            lines = analyze(sources[library]).lloc
        except (SyntaxError, ValueError):
            continue
        if lines >= ENTRYPOINT_LINES:
            rows.append(finding("py.entrypoint-complex", sub.abs(library), 0, library,
                                f"{library} has {lines} logical lines and the Kodi repo's checker warns from "
                                f"{ENTRYPOINT_LINES}; keep the entry point a short call into resources/lib"))
    return rows


def _parse_problem(source: str) -> tuple[int, str] | None:
    """Line and message when the source fails on the oldest or the running Python, else None."""
    for version in (PYTHON_FLOOR, None):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if version:
                    ast.parse(source, feature_version=version)
                else:
                    ast.parse(source)
        except SyntaxError as e:
            where = f" on Python {version[0]}.{version[1]}" if version else ""
            return e.lineno or 0, f"{e.msg}{where}"
        except ValueError as e:
            return 0, str(e)
    return None
