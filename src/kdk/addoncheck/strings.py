"""Checks of the string ids the add-on reads against those it defines, and untranslated text."""

from __future__ import annotations

import ast
import functools
import json
import os
import re
from typing import NamedTuple, cast

from lxml import etree as ET

from .names import Names
from .rules import finding
from .submission import PARSER, Submission
from .translations import read, source_path
from .wrappers import SOURCE_ADDON, SOURCE_KODI, FileFacts, Resolver, callee_text

ADDON_RANGES = ((30000, 30999), (32000, 32999))
SKIN_RANGE = (31000, 31999)
LABEL_TAGS = ("label", "label2", "altlabel", "hinttext")

_ADDON_MACRO = re.compile(r"\$ADDON\[\s*([\w.\-]+)\s+(\d+)\s*\]")
_LOCALIZE_MACRO = re.compile(r"\$LOCALIZE\[\s*(\d+)\s*\]")
_NOT_WORDS = re.compile(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sdifr]|\{[^{}]*\}|"
                        r"\[/?(?:B|I|CR|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|COLOR[^\]]*)\]", re.IGNORECASE)

# what a use reads: own strings, own then Kodi's, Kodi's, a script window's labels, or other text
OWN, OWN_THEN_KODI, KODI, SKIN, ELSEWHERE = "own", "own-then-kodi", "kodi", "skin", "elsewhere"

# user-facing text arguments of Kodi calls: positions and keywords of each
UI_TEXT = {
    "xbmcgui.Dialog.ok": ((0, 1), ("heading", "message")),
    "xbmcgui.Dialog.yesno": ((0, 1, 2, 3), ("heading", "message", "nolabel", "yeslabel")),
    "xbmcgui.Dialog.yesnocustom": ((0, 1, 2, 3, 4), ("heading", "message", "customlabel", "nolabel", "yeslabel")),
    "xbmcgui.Dialog.notification": ((0, 1), ("heading", "message")),
    "xbmcgui.Dialog.select": ((0, 1), ("heading", "list")),
    "xbmcgui.Dialog.multiselect": ((0, 1), ("heading", "options")),
    "xbmcgui.Dialog.contextmenu": ((0,), ("list",)),
    "xbmcgui.Dialog.input": ((0,), ("heading",)),
    "xbmcgui.Dialog.numeric": ((1,), ("heading",)),
    "xbmcgui.Dialog.browse": ((1,), ("heading",)),
    "xbmcgui.Dialog.browseSingle": ((1,), ("heading",)),
    "xbmcgui.Dialog.browseMultiple": ((1,), ("heading",)),
    "xbmcgui.Dialog.textviewer": ((0, 1), ("heading", "text")),
    "xbmcgui.DialogProgress.create": ((0, 1), ("heading", "message")),
    "xbmcgui.DialogProgress.update": ((1,), ("message",)),
    "xbmcgui.DialogProgressBG.create": ((0, 1), ("heading", "message")),
    "xbmcgui.DialogProgressBG.update": ((1, 2), ("heading", "message")),
    "xbmcgui.ListItem": ((0, 1), ("label", "label2")),
    "xbmcgui.ListItem.setLabel": ((0,), ("label",)),
    "xbmcgui.ListItem.setLabel2": ((0,), ("label",)),
    "xbmcgui.ControlLabel": ((4,), ("label",)),
    "xbmcgui.ControlButton": ((4,), ("label",)),
    "xbmcgui.ControlFadeLabel.addLabel": ((0,), ("label",)),
    "xbmcgui.ControlTextBox.setText": ((0,), ("text",)),
}


class Use(NamedTuple):
    """One string id the add-on reads: the id, where its text comes from, and its file and line."""

    string_id: int
    source: str
    rel: str
    line: int


@functools.lru_cache(maxsize=1)
def _core_ids() -> dict[str, frozenset[int]]:
    """Kodi's own en_gb string ids per branch, which settings fall back to."""
    with open(os.path.join(os.path.dirname(__file__), "data", "corestrings.json"), encoding="utf-8") as f:
        return {branch: frozenset(ids) for branch, ids in json.load(f)["ids"].items()}


def uses(sub: Submission) -> tuple[list[Use], bool]:
    """Each string id the add-on reads, and if it also looks up computed ids; cached per run."""
    if "strings.uses" not in sub.shared:
        found, computed = _python_uses(sub)
        sub.shared["strings.uses"] = (found + _xml_uses(sub), computed)
    return cast("tuple[list[Use], bool]", sub.shared["strings.uses"])


def _python_uses(sub: Submission) -> tuple[list[Use], bool]:
    """String ids code reads by getLocalizedString, wrappers or macros; whether any is computed."""
    trees = sub.own_code()
    resolver = Resolver({sub.abs(rel): FileFacts(tree) for rel, tree in trees.items()})
    found, computed = [], False
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            text = callee_text(node.func)
            where = resolver.source(sub.abs(rel), text) if text else None
            if where is None:
                continue
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool):
                source = {SOURCE_ADDON: OWN, SOURCE_KODI: KODI}.get(where, OWN_THEN_KODI)
                found.append(Use(arg.value, source, rel, node.lineno))
            else:
                computed = True
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found += _macro_uses(sub, node.value, rel, getattr(node, "lineno", 0), ELSEWHERE)
    return found, computed


def _macro_uses(sub: Submission, text: str, rel: str, line: int, localize: str) -> list[Use]:
    """Ids of $ADDON[] naming this add-on, and of $LOCALIZE[], in a piece of text."""
    found = [Use(int(m.group(2)), OWN, rel, line) for m in _ADDON_MACRO.finditer(text) if m.group(1) == sub.addon_id]
    return found + [Use(int(m.group(1)), localize, rel, line) for m in _LOCALIZE_MACRO.finditer(text)]


def _xml_uses(sub: Submission) -> list[Use]:
    """String ids in window XML, settings.xml and the context menu labels of addon.xml."""
    found = []
    for rel in sorted(sub.files):
        if not rel.lower().endswith(".xml"):
            continue
        try:
            root = ET.parse(sub.abs(rel), PARSER).getroot()
        except (OSError, ET.XMLSyntaxError):
            continue
        in_skins = rel.startswith("resources/skins/")
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            text = (node.text or "").strip()
            for value in [text, *node.attrib.values()]:
                found += _macro_uses(sub, value, rel, node.sourceline or 0, SKIN if in_skins else ELSEWHERE)
            if in_skins and node.tag in LABEL_TAGS and text.isdigit():
                found.append(Use(int(text), SKIN, rel, node.sourceline or 0))
            elif rel == "resources/settings.xml":
                found += _setting_uses(node, rel)
            elif rel == "addon.xml" and node.tag == "label" and text.isdigit() and \
                    any(a.get("point") == "kodi.context.item" for a in node.iterancestors("extension")):
                found.append(Use(int(text), OWN, rel, node.sourceline or 0))
    return found


def _setting_uses(node, rel: str) -> list[Use]:
    """String ids one settings.xml element reads: label, help, heading, lvalues and <heading>."""
    line = node.sourceline or 0
    values = [node.get(attr) or "" for attr in ("label", "help", "heading")]
    values += (node.get("lvalues") or "").split("|")
    if node.tag == "heading":
        values.append((node.text or "").strip())
    return [Use(int(v), OWN_THEN_KODI, rel, line) for v in values if v.strip().isdigit()]


def check(sub: Submission) -> list[dict]:
    """Issue rows for missing ids, own ids read as Kodi's, ranges, unused ids and raw text."""
    source_rel = source_path(sub)
    parsed = read(sub.abs(source_rel)) if source_rel else None
    found, computed = uses(sub)
    rows = _hardcoded_rows(sub)
    if not source_rel or parsed is None:
        return rows
    defined = {int(k): entry for k, entry in parsed[0].items()}
    core = _core_ids()[sub.release]
    reported = set()
    for use in found:
        missing = (use.source == OWN and use.string_id not in defined) or \
                  (use.source == OWN_THEN_KODI and use.string_id not in defined and use.string_id not in core)
        if missing and (use.string_id, use.rel) not in reported:
            reported.add((use.string_id, use.rel))
            rows.append(finding("strings.missing-id", sub.abs(use.rel), use.line, str(use.string_id),
                                f"String {use.string_id} is used but not in en_gb's strings.po, so it shows "
                                f"empty"))
        elif use.source in (KODI, SKIN) and use.string_id in defined:
            rows.append(finding("strings.core-lookup", sub.abs(use.rel), use.line, str(use.string_id),
                                f"String {use.string_id} is the add-on's own, but this lookup reads Kodi's and "
                                f"the skin's strings, so it shows their string {use.string_id}; use "
                                f"$ADDON[{sub.addon_id} {use.string_id}] or Addon().getLocalizedString"))
        elif use.source == OWN and use.rel.startswith("resources/skins/") and \
                SKIN_RANGE[0] <= use.string_id <= SKIN_RANGE[1]:
            rows.append(finding("strings.range", sub.abs(use.rel), use.line, str(use.string_id),
                                f"String {use.string_id} is in 31000-31999, the range readers take for a skin's "
                                f"own strings"))
    for string_id, entry in sorted(defined.items()):
        if not any(low <= string_id <= high for low, high in ADDON_RANGES):
            rows.append(finding("strings.range", sub.abs(source_rel), entry.line, str(string_id),
                                f"String {string_id} is outside 30000-30999 and 32000-32999, the ranges add-ons "
                                f"use by convention"))
    if not computed:
        used = {use.string_id for use in found}
        rows += [finding("strings.unused", sub.abs(source_rel), entry.line, str(string_id),
                         f"String {string_id} is never used") for string_id, entry in sorted(defined.items())
                 if string_id not in used]
    return rows


def _ui_text(node: ast.AST, name: str, provider: str) -> str | None:
    """Literal text holding a word not in capitals, unless add-on name, provider, URL or path."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    elif isinstance(node, ast.JoinedStr):
        text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    else:
        return None
    bare, stripped = _NOT_WORDS.sub("", text), text.strip()
    product = stripped == provider or bool(stripped and re.search(rf"(?<!\w){re.escape(stripped)}(?!\w)", name))
    words = [run for run in re.findall(r"[^\W\d_]{2,}", bare) if not run.isupper()]
    if not words or product or "://" in text or text.startswith("/"):
        return None
    return text


def _hardcoded_rows(sub: Submission) -> list[dict]:
    """Literal text handed to Kodi's dialogs, list items and controls, and settings labels."""
    name = (sub.root.get("name") if sub.root is not None else "") or ""
    provider = (sub.root.get("provider-name") if sub.root is not None else "") or ""
    rows = []
    for rel, tree in sub.own_code().items():
        names = Names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = names.call(node)
            spec = UI_TEXT.get(called or "")
            if spec is None:
                continue
            positions, keywords = spec
            args = [node.args[i] for i in positions if i < len(node.args)]
            args += [k.value for k in node.keywords if k.arg in keywords]
            items = [e for a in args if isinstance(a, (ast.List, ast.Tuple)) for e in a.elts]
            for arg in args + items:
                text = _ui_text(arg, name, provider)
                if text:
                    rows.append(finding("strings.hardcoded-ui", sub.abs(rel), node.lineno, text[:60],
                                        f"\"{text[:60]}\" is shown to users untranslated; put it in strings.po and "
                                        f"read it with getLocalizedString"))
    rows += _settings_text_rows(sub)
    return rows


def _settings_text_rows(sub: Submission) -> list[dict]:
    """Labels, help and headings in settings.xml written as text instead of string ids."""
    rel = "resources/settings.xml"
    if rel not in sub.files:
        return []
    try:
        root = ET.parse(sub.abs(rel), PARSER).getroot()
    except (OSError, ET.XMLSyntaxError):
        return []
    rows = []
    for node in root.iter():
        if not isinstance(node.tag, str) or node.tag == "setting" and _hidden(node):
            continue
        # an option's label is a fixed value such as a language's own name
        values = [node.get("help")] + ([node.get("label")] if node.tag != "option" else [])
        values += [node.text] if node.tag == "heading" else []
        for value in values:
            value = (value or "").strip()
            if value and not value.isdigit() and re.search(r"[^\W\d_]", value) and "$" not in value:
                rows.append(finding("strings.hardcoded-ui", sub.abs(rel), node.sourceline or 0, value[:60],
                                    f"\"{value[:60]}\" in settings.xml is shown untranslated; use a string id"))
    return rows


def _hidden(setting) -> bool:
    """True when a setting is never shown, by its visible attribute or its <visible> element."""
    return (setting.get("visible") or "").strip().lower() == "false" or \
        any((child.text or "").strip().lower() == "false" for child in setting if child.tag == "visible")
