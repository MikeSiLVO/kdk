"""Checks of the language folders and of each strings.po on its own."""

from __future__ import annotations

import re
from types import SimpleNamespace

from ..libs.addon.translations import strings_po_faults
from ..libs.validation.label import _PO_EFFECTS, _PO_PROBLEMS
from ..libs.validation.repo import LANG_CODE, ValidationRepo
from .rules import finding
from .strings import uses
from .submission import Submission

BASE = "resources/language"

# ships inside Kodi itself, never in a branch list
CORE_LANGUAGE = "resource.language.en_gb"

# the Kodi repo rule each shared strings.po check reports under here
PO_RULES = {
    "repo.po-encoding": "lang.po-encoding",
    "repo.po-header": "lang.po-header",
    "repo.po-duplicate-id": "lang.duplicate-id",
    "repo.po-bom": "lang.po-bom",
    "repo.po-parse": "lang.po-parse",
}

# entries Weblate uses to translate addon.xml, which carry no string id
METADATA_CONTEXTS = {"Addon Summary", "Addon Description", "Addon Disclaimer"}

_MSGCTXT = re.compile(r'^\s*msgctxt\s+"(.*)"\s*$')


def check(sub: Submission) -> list[dict]:
    """Issue rows for the language folders and every strings.po."""
    rows = _folder_rows(sub)
    po_files = sorted(rel for rel in sub.files if rel.rsplit("/", 1)[-1] == "strings.po")
    invalid = set()
    for rel in po_files:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if "resource.language." in parent:
            code = parent.rpartition(".")[2]
            if not LANG_CODE.match(code):
                invalid.add(parent)
                rows.append(finding("lang.code-invalid", sub.abs(rel), 0, code,
                                    f"{code} in {parent} is not a language code, so no Kodi language reads it"))
                continue
        rows += _po_rows(sub, rel)
    rows += _known_code_rows(sub, po_files, invalid)
    new_style = [rel for rel in po_files if "resource.language." in rel]
    language_addon = sub.root is not None and any(e.get("point") == "kodi.resource.language"
                                                  for e in sub.root.findall("extension"))
    if new_style and not language_addon and not any(
            rel.rsplit("/", 2)[-2].casefold() == "resource.language.en_gb" for rel in new_style):
        rows.append(finding("lang.no-en-gb", sub.abs(BASE), 0, "resource.language.en_gb",
                            "there is no resource.language.en_gb folder; Kodi falls back to it for every string a "
                            "translation lacks"))
    if not po_files:
        read_ids = uses(sub)[0]
        if "resources/settings.xml" in sub.files or read_ids:
            where = read_ids[0].rel if read_ids else "resources/settings.xml"
            rows.append(finding("lang.no-po", sub.abs(where), read_ids[0].line if read_ids else 0, "strings.po",
                                "the add-on has settings or reads string ids but has no strings.po, so its "
                                "text cannot be translated"))
    for path, line, string_id, problem, effect in strings_po_faults(sub.path):
        message = f"String {string_id or 'in the header'} {_PO_PROBLEMS[problem]}"
        if effect:
            message += f", so Kodi {_PO_EFFECTS[effect]}"
        elif problem == "unclosed":
            message += ", so Weblate and gettext tools cannot load the file"
        else:
            message += ", which msgfmt rejects"
        rows.append(finding("lang.po-broken-string", path, line, string_id, message))
    return rows


def _folder_rows(sub: Submission) -> list[dict]:
    """Old layout, language files outside resources/language, strings.xml and uppercase folders."""
    rows = []
    for rel in sorted(sub.dirs):
        parent, _, name = rel.rpartition("/")
        if parent == BASE and "resource.language." not in name:
            rows.append(finding("lang.layout", sub.abs(rel), 0, name,
                                f"{rel} uses the old language folder layout; name it resource.language.<code>"))
        elif name.startswith("resource.language.") and parent != BASE:
            rows.append(finding("lang.base-folder", sub.abs(rel), 0, rel,
                                f"{rel} is outside {BASE}, the only place Kodi reads an add-on's strings"))
        if parent == BASE and name.startswith("resource.language.") and name != name.lower():
            rows.append(finding("lang.folder-case", sub.abs(rel), 0, name,
                                f"{name} has uppercase letters; Kodi's language ids are lowercase, such as "
                                f"resource.language.de_de"))
    for rel in sorted(sub.files):
        parent, _, name = rel.rpartition("/")
        if name == "strings.po" and parent.rpartition("/")[0] != BASE and \
                not parent.rpartition("/")[2].startswith("resource.language."):
            rows.append(finding("lang.base-folder", sub.abs(rel), 0, rel,
                                f"{rel} is outside {BASE}, the only place Kodi reads an add-on's strings"))
        elif name == "strings.xml" and rel.startswith(BASE + "/"):
            rows.append(finding("lang.strings-xml", sub.abs(rel), 0, rel,
                                f"{rel} is in the old format Kodi no longer reads; move its strings to strings.po"))
    return rows


def _known_code_rows(sub: Submission, po_files: list[str], invalid: set[str]) -> list[dict]:
    """Language folders with a strings.po that no Kodi language on the branch is named after."""
    if not sub.index.has(sub.release):
        return []
    known = {i.casefold() for i in sub.index.with_point(sub.release, "kodi.resource.language")} | {CORE_LANGUAGE}
    rows = []
    for rel in po_files:
        parent, _, _ = rel.rpartition("/")
        folder_parent, _, name = parent.rpartition("/")
        if folder_parent == BASE and name.startswith("resource.language.") and parent not in invalid \
                and name.casefold() not in known:
            rows.append(finding("lang.code-unknown", sub.abs(parent), 0, name,
                                f"no Kodi language is named {name.casefold()}, so Kodi never reads this "
                                f"translation"))
    return rows


def _po_rows(sub: Submission, rel: str) -> list[dict]:
    """One strings.po: encoding, header, BOM, parsing, duplicate ids, CRLF, entries Kodi skips."""
    repo = ValidationRepo(SimpleNamespace(path=sub.path))
    repo._check_po(rel, sub.abs(rel))
    rows = [finding(PO_RULES[issue["rule"]], issue["file"], issue["line"], issue["subject"],
                    issue["message"].removeprefix("Kodi repo: "))
            for issue in repo.issues if issue["rule"] in PO_RULES]
    try:
        with open(sub.abs(rel), "rb") as f:
            data = f.read()
    except OSError:
        return rows
    if b"\r\n" in data:
        rows.append(finding("lang.po-crlf", sub.abs(rel), 0, rel,
                            f"{rel} has Windows line endings; Kodi converts them, Unix line endings are usual"))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return rows
    return rows + _msgctxt_rows(sub, rel, text)


def _msgctxt_rows(sub: Submission, rel: str, text: str) -> list[dict]:
    """Entries Kodi never loads: a msgctxt other than #<number>, or two in one entry."""
    rows = []
    seen_in_entry = 0
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if not line.strip():
            seen_in_entry = 0
            continue
        found = _MSGCTXT.match(line)
        if not found:
            continue
        seen_in_entry += 1
        value = found.group(1)
        if seen_in_entry > 1:
            rows.append(finding("lang.msgctxt", sub.abs(rel), number, value,
                                f"a second msgctxt in one entry; without a blank line between them Kodi reads one "
                                f"entry, and string {value} is lost"))
        elif not re.fullmatch(r"#\d+", value) and value not in METADATA_CONTEXTS:
            rows.append(finding("lang.msgctxt", sub.abs(rel), number, value,
                                f"msgctxt \"{value}\" is not \"#\" and a number, so Kodi never loads this string"))
    return rows
