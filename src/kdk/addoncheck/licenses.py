"""Checks of licensing: the license file, the <license> SPDX expression, and the two agreeing."""

from __future__ import annotations

import ast
import functools
import io
import json
import os
import re
import tokenize

from .rules import WARNING, finding
from .submission import Submission

ROOT_LICENSE = re.compile(r"(?i)^(LICENSE|LICENCE|COPYING)(\.(txt|md|rst))?$")
ANY_LICENSE = re.compile(r"(?i)^(licen[cs]e|copying)([._-].*)?$")

# header phrases only that license's text carries, lowercased, spaces collapsed; first match wins
FINGERPRINTS = (
    ("AGPL-3.0", ("gnu affero general public license version 3, 19 november 2007",)),
    ("LGPL-3.0", ("gnu lesser general public license version 3, 29 june 2007",)),
    ("LGPL-2.1", ("gnu lesser general public license version 2.1, february 1999",)),
    ("GPL-3.0", ("gnu general public license version 3, 29 june 2007",)),
    ("GPL-2.0", ("gnu general public license version 2, june 1991",)),
    ("Apache-2.0", ("apache license version 2.0, january 2004",)),
    ("MPL-2.0", ("mozilla public license version 2.0",)),
    ("MIT", ("permission is hereby granted, free of charge, to any person obtaining a copy",
             "the above copyright notice and this permission notice shall be included")),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms, with or without modification, are "
                      "permitted", "neither the name of")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms, with or without modification, are "
                      "permitted",)),
    ("ISC", ("distribute this software for any purpose with or without fee is hereby granted",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
    ("CC0-1.0", ("cc0 1.0 universal",)),
)

GNU_PLACEHOLDERS = ("<one line to give the program's name and a brief idea of what it does.>", "<name of author>",
                    "<year>", "Foobar is free software")

_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9.\-:]+\+?)")


@functools.lru_cache(maxsize=1)
def _lists() -> dict:
    """The SPDX license and exception ids, each with whether it is deprecated."""
    with open(os.path.join(os.path.dirname(__file__), "data", "spdx.json"), encoding="utf-8") as f:
        return json.load(f)


def check(sub: Submission) -> list[dict]:
    """Issue rows for the license file, the <license> expression and placeholder notices."""
    rows = []
    has_dir = any(rel.startswith("LICENSES/") for rel in sub.files)
    if not has_dir and not any("/" not in rel and ROOT_LICENSE.match(rel) for rel in sub.files):
        rows.append(finding("license.file-missing", sub.path, 0, "LICENSE",
                            "No license file such as LICENSE.txt in the add-on's root; the Kodi repo needs the "
                            "license text shipped"))
    ids = None
    meta = sub.metadata
    if meta is not None:
        node = meta.find("license")
        if node is None:
            rows.append(finding("license.tag-missing", sub.xml_path, meta.sourceline, "license",
                                "addon.xml has no <license>; give the license as an SPDX id such as "
                                "GPL-2.0-or-later"))
        elif (node.text or "").strip():
            text = node.text.strip()
            ids, problem = parse_spdx(text)
            if problem:
                rows.append(finding("license.spdx", sub.xml_path, node.sourceline, text,
                                    f"<license> {text!r} is not a valid SPDX expression: {problem}"))
                ids = None
            else:
                rows += [finding("license.spdx-deprecated", sub.xml_path, node.sourceline, i,
                                 f"{i} is a deprecated SPDX id; use {i}-only or {i}-or-later"
                                 if re.match(r"^(A|L)?GPL-\d\.\d$|^GFDL-1\.\d$", i) else
                                 f"{i} is a deprecated SPDX id")
                         for i in sorted(ids) if _lists()["licenses"].get(i)]
    return rows + _file_rows(sub, ids) + _placeholder_rows(sub)


def parse_spdx(text: str) -> tuple[set[str], str | None]:
    """License ids an SPDX expression names, plus why it is invalid, or None when it is valid."""
    tokens, pos = [], 0
    while pos < len(text):
        found = _TOKEN.match(text, pos)
        if not found:
            if text[pos:].strip():
                return set(), f"unexpected {text[pos:].strip()[:20]!r}"
            break
        tokens.append(found.group(1))
        pos = found.end()
    licenses = {k.lower(): k for k in _lists()["licenses"]}
    exceptions = {k.lower(): k for k in _lists()["exceptions"]}
    ids: set[str] = set()
    at = 0

    def take():
        nonlocal at
        at += 1
        return tokens[at - 1] if at <= len(tokens) else None

    def peek():
        return tokens[at] if at < len(tokens) else None

    def simple():
        token = take()
        if token is None:
            raise ValueError("it ends where a license id is expected")
        if token == "(":
            expression()
            if take() != ")":
                raise ValueError("a '(' is never closed")
            return
        if token in (")", "AND", "OR", "WITH"):
            raise ValueError(f"{token!r} where a license id is expected")
        base = token[:-1] if token.endswith("+") else token
        if re.match(r"^(DocumentRef-[A-Za-z0-9.\-]+:)?LicenseRef-[A-Za-z0-9.\-]+$", base):
            return
        if base.lower() not in licenses:
            raise ValueError(f"{base} is not an SPDX license id")
        ids.add(licenses[base.lower()])
        if peek() == "WITH":
            take()
            exception = take()
            if exception is None or exception.lower() not in exceptions:
                raise ValueError(f"{exception} is not an SPDX exception id")

    def conjunction():
        simple()
        while peek() == "AND":
            take()
            simple()

    def expression():
        conjunction()
        while peek() == "OR":
            take()
            conjunction()

    try:
        expression()
        if peek() is not None:
            raise ValueError(f"{peek()!r} where AND or OR is expected")
    except ValueError as e:
        return set(), str(e)
    return ids, None


def _family(license_id: str) -> str:
    """The license a SPDX id names, without its -only, -or-later or + form."""
    return re.sub(r"(-only|-or-later|\+)$", "", license_id)


def identify(text: str) -> str | None:
    """The license whose text this is, from its header phrases; None when no known one matches."""
    flat = " ".join(text.lower().split())
    for license_id, phrases in FINGERPRINTS:
        if all(phrase in flat for phrase in phrases):
            return license_id
    return None


def _file_rows(sub: Submission, ids: set[str] | None) -> list[dict]:
    """License files whose license the <license> expression does not name."""
    if not ids:
        return []
    named = {_family(i) for i in ids}
    rows = []
    for rel in sorted(sub.files):
        parent, _, name = rel.rpartition("/")
        in_root = not parent or parent == "LICENSES"
        if not (ANY_LICENSE.match(name) or parent == "LICENSES"):
            continue
        try:
            with open(sub.abs(rel), encoding="utf-8", errors="replace") as f:
                found = identify(f.read())
        except OSError:
            continue
        if found and found not in named:
            rows.append(finding("license.mismatch", sub.abs(rel), 0, rel,
                                f"{rel} holds the {found} license, which <license> does not name",
                                None if in_root else WARNING))
    return rows


def _placeholder_rows(sub: Submission) -> list[dict]:
    """GNU notice placeholders in comments, docstrings or a license file lacking the full text."""
    rows = []
    for rel in sorted(sub.files):
        name = rel.rpartition("/")[2]
        if rel.endswith(".py") and not sub.bundled(rel):
            for line, text in _commentary(sub.abs(rel)):
                if any(p in text for p in GNU_PLACEHOLDERS):
                    rows.append(finding("license.placeholder", sub.abs(rel), line, rel,
                                        "The GNU license notice still has its placeholders; fill in the program "
                                        "name, year and author"))
                    break
        elif ANY_LICENSE.match(name):
            try:
                with open(sub.abs(rel), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if "TERMS AND CONDITIONS" not in text and any(p in text for p in GNU_PLACEHOLDERS):
                rows.append(finding("license.placeholder", sub.abs(rel), 0, rel,
                                    f"{rel} has the GNU notice's placeholders; fill in the program name, year and "
                                    f"author"))
    return rows


def _commentary(path: str) -> list[tuple[int, str]]:
    """Line and text of each comment and docstring in a Python file; empty when it does not read."""
    try:
        with open(path, "rb") as f:
            source = f.read()
        found = [(t.start[0], t.string) for t in tokenize.tokenize(io.BytesIO(source).readline)
                 if t.type == tokenize.COMMENT]
        tree = ast.parse(source)
    except (OSError, SyntaxError, tokenize.TokenError, UnicodeDecodeError, ValueError):
        return []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body:
                found.append((node.body[0].lineno, doc))
    return found
