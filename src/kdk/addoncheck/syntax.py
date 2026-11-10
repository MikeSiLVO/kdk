"""Python checks the Kodi repo's checker runs: syntax on the oldest Python, entry point size."""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
import warnings

from .radon.raw import analyze
from .releases import PACKAGED_PYTHON, PYTHON_FLOOR, python_level, python_reason
from .rules import HINT, finding
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
        problem = _parse_problem(source) or _newer_syntax(source)
        if problem:
            line, message, needed = problem
            level = python_level(sub.release, needed) if needed else "fail"
            if needed is None:
                rows.append(finding("py.syntax", sub.abs(rel), line, rel, f"{rel} does not parse: {message}"))
                continue
            if level and sub.release not in PACKAGED_PYTHON:
                rows.append(finding("py.syntax", sub.abs(rel), line, rel,
                                    f"{rel} does not parse on Python 3.8: {message}"))
                continue
            if level:
                rows.append(finding("py.syntax", sub.abs(rel), line, rel,
                                    f"{rel} needs Python {needed[0]}.{needed[1]}: {message}; "
                                    f"{python_reason(sub.release, needed)}", HINT if level == "hint" else None))
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


def _parse_problem(source: str) -> tuple[int, str, tuple[int, int] | None] | None:
    """Line, message and oldest Python that parses the source, None for none; None when 3.8 does."""
    try:
        _parse(source, None)
    except SyntaxError as e:
        return e.lineno or 0, e.msg, None
    except ValueError as e:
        return 0, str(e), None
    failed = None
    for minor in range(PYTHON_FLOOR[1], sys.version_info[1] + 1):
        try:
            _parse(source, (3, minor))
        except (SyntaxError, ValueError) as e:
            failed = e
            continue
        if failed is None:
            return None
        return getattr(failed, "lineno", 0) or 0, getattr(failed, "msg", str(failed)), (3, minor)
    return None


def _parse(source: str, version: tuple[int, int] | None) -> ast.Module:
    """Parse the source with the grammar of the Python version given, or of the running one."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source, feature_version=version) if version else ast.parse(source)


def _newer_syntax(source: str) -> tuple[int, str, tuple[int, int]] | None:
    """Line, message and needed Python for newer syntax the grammar-version parse lets through."""
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)) and _parenthesized(lines, node):
            return node.lineno, "context managers in parentheses need Python 3.10", (3, 10)
    found = _same_quote_fstring(source)
    return (*found, (3, 12)) if found else None


def _after_string(text: str, i: int) -> int:
    """Index just past the string literal starting at the index; the end when it never closes."""
    quote = text[i:i + 3] if text[i:i + 3] in ('"""', "'''") else text[i]
    j = i + len(quote)
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text.startswith(quote, j):
            return j + len(quote)
        else:
            j += 1
    return len(text)


def _top_level(text: str) -> list[tuple[int, str]]:
    """Index and character of each character outside strings and outside nested brackets."""
    found, depth, i = [], 0, 0
    while i < len(text):
        char = text[i]
        if char in "'\"":
            i = _after_string(text, i)
            continue
        if depth == 0:
            found.append((i, char))
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        i += 1
    return found


def _parenthesized(lines: list[str], node) -> bool:
    """True for `with (a as b, c):`, the bracketed form Python 3.8 reads as one expression."""
    first = lines[node.lineno - 1].encode("utf-8")[node.col_offset:].decode("utf-8", "ignore")
    text = "\n".join([first] + lines[node.lineno:])
    found = re.match(r"(async\s+)?with\s*\(", text)
    if not found:
        return False
    rest = text[found.end():]
    close = next((i for i, char in _top_level(rest) if char == ")"), -1)
    if close < 0 or not rest[close + 1:].lstrip().startswith(":"):
        return False
    inner = rest[:close]
    return any(char == "," or (re.match(r"as\b", inner[i:]) and not inner[i - 1:i].isalnum())
               for i, char in _top_level(inner))


def _same_quote_fstring(source: str) -> tuple[int, str] | None:
    """Line and message for a string in an f-string reusing its quotes, which needs Python 3.12."""
    if sys.version_info < (3, 12):
        return None
    outer: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.FSTRING_START, tokenize.STRING) and outer:
                body = token.string.lstrip("rRbBuUfF")
                quote = body[:3] if body[:3] in ('"""', "'''") else body[:1]
                if quote == outer[-1] or (len(outer[-1]) == 1 and quote[:1] == outer[-1]):
                    return token.start[0], "a string inside an f-string with the same quotes needs Python 3.12"
            if token.type == tokenize.FSTRING_START:
                body = token.string.lstrip("rRbBuUfF")
                outer.append(body[:3] if body[:3] in ('"""', "'''") else body[:1])
            elif token.type == tokenize.FSTRING_END and outer:
                outer.pop()
    except (tokenize.TokenError, SyntaxError):
        return None
    return None
