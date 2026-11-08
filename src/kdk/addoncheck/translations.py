"""Checks of each translation against resource.language.en_gb, and of en_gb against addon.xml."""

from __future__ import annotations

import re
from collections import Counter
from typing import NamedTuple

from ..libs.polib.polib import pofile
from .rules import WARNING, finding
from .submission import Submission

BASE = "resources/language"
SOURCE_FOLDER = "resource.language.en_gb"

# en_gb entries Weblate fills from addon.xml, by the metadata element each one mirrors
METADATA_CONTEXTS = {"Addon Summary": "summary", "Addon Description": "description",
                     "Addon Disclaimer": "disclaimer"}

FORMAT_TOKEN = re.compile(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sdifr]|\{[^{}]*\}")
MARKUP_TOKEN = re.compile(r"\[/?(?:B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|COLOR)(?: [^\]]*)?\]|\[CR\]|\n",
                          re.IGNORECASE)


class Entry(NamedTuple):
    """One strings.po entry with a string id: its msgid, msgstr and line."""

    msgid: str
    msgstr: str
    line: int


def read(path: str) -> tuple[dict[str, Entry], dict[str, Entry]] | None:
    """Entries by string id and other msgctxt, the first of each kept; None when it won't parse."""
    try:
        po = pofile(path, encoding="utf-8")
    except Exception:
        return None
    by_id: dict[str, Entry] = {}
    other: dict[str, Entry] = {}
    for entry in po:
        if entry.obsolete or not entry.msgctxt:
            continue
        found = re.fullmatch(r"#(\d+)", entry.msgctxt)
        table, key = (by_id, found.group(1)) if found else (other, entry.msgctxt)
        table.setdefault(key, Entry(entry.msgid, entry.msgstr, entry.linenum))
    return by_id, other


def source_path(sub: Submission) -> str | None:
    """Path of the en_gb strings.po, its folder matched in any case; None when there is none."""
    return next((rel for rel in sorted(sub.files) if rel.rpartition("/")[0].casefold() == f"{BASE}/{SOURCE_FOLDER}"
                 and rel.endswith("/strings.po")), None)


def check(sub: Submission) -> list[dict]:
    """Issue rows for translations against en_gb, its msgstr text, and en_gb against addon.xml."""
    source_rel = source_path(sub)
    source = read(sub.abs(source_rel)) if source_rel else None
    if not source_rel or source is None:
        return []
    by_id, other = source
    rows = _source_rows(sub, source_rel, by_id, other)
    for rel in sorted(sub.files):
        folder = rel.rpartition("/")[0]
        if rel == source_rel or not rel.endswith("/strings.po") or folder.rpartition("/")[0] != BASE \
                or not folder.rpartition("/")[2].startswith("resource.language."):
            continue
        translation = read(sub.abs(rel))
        if translation is not None:
            rows += _translation_rows(sub, rel, translation[0], by_id)
    return rows


def _source_rows(sub: Submission, rel: str, by_id: dict[str, Entry], other: dict[str, Entry]) -> list[dict]:
    """The en_gb msgstr text Kodi never shows, and metadata entries that differ from addon.xml."""
    rows = []
    for string_id, entry in by_id.items():
        if entry.msgstr and entry.msgstr != entry.msgid:
            rows.append(finding("lang.en-gb-msgstr", sub.abs(rel), entry.line, string_id,
                                f"string {string_id} has a msgstr that differs from its msgid; Kodi shows the "
                                f"msgid for English, so the msgstr text never appears"))
    meta = sub.metadata
    for context, tag in METADATA_CONTEXTS.items():
        entry = other.get(context)
        if entry is None or meta is None:
            continue
        texts = [(node.text or "") for node in meta.findall(tag) if node.get("lang") in (None, "en_GB")]
        if texts and " ".join(texts[0].split()) != " ".join(entry.msgid.split()):
            rows.append(finding("lang.metadata-mismatch", sub.abs(rel), entry.line, context,
                                f"\"{context}\" differs from the English <{tag}> in addon.xml, so translators "
                                f"work from other text than users read"))
    return rows


def _translation_rows(sub: Submission, rel: str, entries: dict[str, Entry], source: dict[str, Entry]) -> list[dict]:
    """Ids en_gb lacks, translations of older English text, and placeholders that do not match."""
    rows = []
    for string_id, entry in entries.items():
        english = source.get(string_id)
        if english is None:
            rows.append(finding("lang.orphan-id", sub.abs(rel), entry.line, string_id,
                                f"string {string_id} is not in en_gb, so Kodi never asks for it"))
            continue
        if not entry.msgstr:
            continue
        if entry.msgid != english.msgid:
            rows.append(finding("lang.outdated", sub.abs(rel), entry.line, string_id,
                                f"string {string_id} translates an older English text; Kodi shows the English "
                                f"string until the translation is updated"))
        else:
            rows += _placeholder_rows(sub, rel, string_id, entry)
    return rows


def _format_tokens(text: str) -> list[str]:
    """The % and {} placeholders in the text, in order, %% and doubled braces left out."""
    return FORMAT_TOKEN.findall(text.replace("%%", "").replace("{{", "").replace("}}", ""))


def _markup(text: str) -> Counter:
    """Kodi label tags and line breaks in the text, color values left out."""
    return Counter(re.sub(r"(?i)^\[COLOR .*\]$", "[COLOR]", tag).upper() for tag in MARKUP_TOKEN.findall(text))


def _placeholder_rows(sub: Submission, rel: str, string_id: str, entry: Entry) -> list[dict]:
    """A translation whose placeholders, or label tags, differ from its own msgid's."""
    rows = []
    source, target = _format_tokens(entry.msgid), _format_tokens(entry.msgstr)
    positional = [t for t in source if t.startswith("%") and not t.startswith("%(")]
    translated = [t for t in target if t.startswith("%") and not t.startswith("%(")]
    if Counter(source) != Counter(target) or positional != translated:
        rows.append(finding("lang.placeholders", sub.abs(rel), entry.line, string_id,
                            f"string {string_id} has placeholders {' '.join(target) or 'none'} where the English "
                            f"has {' '.join(source) or 'none'}, so the add-on's formatting call fails"))
    if _markup(entry.msgid) != _markup(entry.msgstr):
        rows.append(finding("lang.placeholders", sub.abs(rel), entry.line, string_id,
                            f"string {string_id} has other label tags or line breaks than the English, so "
                            f"formatting can run into the rest of the label", WARNING))
    return rows
