"""Checks of the add-on's files: what must not ship, endings, modes, names, XML and JSON."""

from __future__ import annotations

import fnmatch
import json
import xml.etree.ElementTree as StdET
from collections import defaultdict

from ..libs.validation.repo import WHITELIST
from .rules import finding
from .submission import DEV_FOLDERS, Submission

GIT_NAMES = {".git", ".github", ".gitignore", ".gitattributes", ".gitmodules", ".gitkeep", ".gitlab-ci.yml"}
DEV_FILES = ("*.pyc", "*.pyo", ".travis.yml", "setup.py", "setup.cfg", "manifest.in", "requirements*.txt", "tox.ini",
             "makefile", "pyproject.toml", ".editorconfig", ".pre-commit-config.yaml", "ruff.toml", ".ruff.toml",
             "pyrightconfig.json", ".pylintrc", ".flake8", ".ds_store", "thumbs.db", "desktop.ini", "*.orig", "*.bak",
             "*.swp", "*~", "* - copy.*", "*.rej")
# inside bundled third-party code only these count; its own packaging files are its business
BUNDLED_DEV = {"__pycache__", "*.pyc"}
DOC_FOLDERS = {"docs", "doc", "examples"}
BINARY_ENDINGS = (".so", ".dll", ".dylib", ".exe", ".pyd", ".mo", ".jar", ".apk")
BINARY_MAGIC = (b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe")


def check(sub: Submission) -> list[dict]:
    """Issue rows for the add-on's files; adds a notice when file modes cannot be checked."""
    rows, reported = _unwanted_rows(sub)
    if ".tests-config.json" in sub.files:
        rows.append(finding("files.tests-config", sub.abs(".tests-config.json"), 0, ".tests-config.json",
                            "The Kodi repo's checker reads .tests-config.json as its own settings, so a shipped "
                            "one changes what the repo's CI checks"))
    if ".module." not in sub.folder:
        for rel in sub.files:
            name = rel.rsplit("/", 1)[-1]
            if rel in reported or "." not in name:
                continue
            if not WHITELIST.match("." + name.rsplit(".", 1)[1]):
                rows.append(finding("files.whitelist", sub.abs(rel), 0, rel,
                                    f"{rel} has a file ending the Kodi repo's checker does not whitelist"))
    if not sub.exec_known:
        sub.notices.append("File modes cannot be read on Windows, so executable files were not checked")
    elif sub.files and all(sub.files.values()) and not sub.from_tree:
        sub.notices.append("Every file reads as executable, which a drive without file modes reports, so "
                           "executable files were not checked; pass --tree to check them")
    else:
        rows += [finding("files.executable", sub.abs(rel), 0, rel,
                         f"{rel} is marked executable; Kodi add-ons ship no executables, clear the bit")
                 for rel, executable in sub.files.items() if executable]
    return rows + _binary_rows(sub) + _name_rows(sub) + _parse_rows(sub) + _nested_rows(sub)


def _dev_name(name: str, bundled: bool) -> bool:
    """True when a file name is a development file, cache or leftover that must not ship."""
    patterns = BUNDLED_DEV if bundled else DEV_FILES
    return any(fnmatch.fnmatchcase(name.lower(), pattern) for pattern in patterns)


def _unwanted_rows(sub: Submission) -> tuple[list[dict], set[str]]:
    """Git, development and documentation files and folders, with the files those rows cover."""
    rows, reported, flagged = [], set(), []
    for rel in sorted(sub.dirs):
        if any(rel.startswith(f + "/") for f in flagged):
            continue
        name = rel.rsplit("/", 1)[-1]
        bundled = sub.bundled(rel + "/")
        if name in GIT_NAMES:
            rows.append(finding("files.git", sub.abs(rel), 0, rel + "/",
                                f"{rel}/ is a git folder; it does not belong in the add-on"))
        elif (name.lower() in DEV_FOLDERS or name.lower().endswith(".egg-info")) and \
                (not bundled or name == "__pycache__"):
            rows.append(finding("files.dev", sub.abs(rel), 0, rel + "/",
                                f"{rel}/ is a development folder; it does not belong in the add-on"))
        else:
            if name.lower() in DOC_FOLDERS and not bundled:
                rows.append(finding("files.dev-docs", sub.abs(rel), 0, rel + "/",
                                    f"{rel}/ holds documentation or examples, which users of the add-on never see"))
            continue
        flagged.append(rel)
        reported.update(f for f in sub.files if f.startswith(rel + "/"))
    for rel in sub.files:
        if rel in reported:
            continue
        name = rel.rsplit("/", 1)[-1]
        if name in GIT_NAMES:
            rows.append(finding("files.git", sub.abs(rel), 0, rel, f"{rel} is a git file; it does not belong in "
                                                                   f"the add-on"))
        elif _dev_name(name, sub.bundled(rel)):
            rows.append(finding("files.dev", sub.abs(rel), 0, rel,
                                f"{rel} is a development file, cache or leftover; it does not belong in the add-on"))
        else:
            if fnmatch.fnmatchcase(name.lower(), "example*.py") and not sub.bundled(rel):
                rows.append(finding("files.dev-docs", sub.abs(rel), 0, rel,
                                    f"{rel} is an example script, which users of the add-on never run"))
            continue
        reported.add(rel)
    return rows, reported


def _binary_rows(sub: Submission) -> list[dict]:
    """Compiled binaries and libraries, by ending or by their first bytes."""
    rows = []
    for rel in sub.files:
        binary = rel.lower().endswith(BINARY_ENDINGS)
        if not binary:
            try:
                with open(sub.abs(rel), "rb") as f:
                    binary = f.read(4).startswith(BINARY_MAGIC)
            except OSError:
                continue
        if binary:
            rows.append(finding("files.binary", sub.abs(rel), 0, rel,
                                f"{rel} is a compiled binary; the Kodi repo takes source only"))
    return rows


def _name_rows(sub: Submission) -> list[dict]:
    """Paths that differ only by case, and names with non-ASCII characters."""
    rows = []
    groups = defaultdict(list)
    for rel in sorted(set(sub.files) | sub.dirs):
        groups[rel.casefold()].append(rel)
        name = rel.rsplit("/", 1)[-1]
        if not name.isascii():
            rows.append(finding("files.non-ascii-name", sub.abs(rel), 0, rel,
                                f"{rel} has non-ASCII characters in its name, which some systems and zip tools "
                                f"mangle"))
    for key, paths in groups.items():
        if len(paths) > 1:
            rows.append(finding("files.case-clash", sub.abs(paths[1]), 0, key,
                                f"{' and '.join(paths)} differ only by case, so one overwrites the other on "
                                f"Windows and macOS"))
    return rows


def _parse_rows(sub: Submission) -> list[dict]:
    """XML files that are not well-formed and JSON files that do not parse."""
    rows = []
    for rel in sub.files:
        lower = rel.lower()
        if lower.endswith(".xml") and rel != "addon.xml":
            try:
                StdET.parse(sub.abs(rel))
            except StdET.ParseError as e:
                rows.append(finding("files.xml-invalid", sub.abs(rel), e.position[0], rel,
                                    f"{rel} is not well-formed XML: {str(e).split(':')[0]}"))
            except OSError:
                continue
        elif lower.endswith(".json"):
            try:
                with open(sub.abs(rel), encoding="utf8") as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                rows.append(finding("files.json-invalid", sub.abs(rel), e.lineno, rel,
                                    f"{rel} is not valid JSON: {e.msg}"))
            except UnicodeDecodeError:
                rows.append(finding("files.json-invalid", sub.abs(rel), 0, rel, f"{rel} is not saved as UTF-8"))
            except OSError:
                continue
    return rows


def _nested_rows(sub: Submission) -> list[dict]:
    """Folders inside the add-on that hold an addon.xml of their own."""
    folders = sorted(rel[:-len("/addon.xml")] for rel in sub.files if rel.endswith("/addon.xml"))
    outer = [f for f in folders if not any(f.startswith(o + "/") for o in folders)]
    return [finding("files.nested-addon", sub.abs(f), 0, f + "/",
                    f"{f}/ holds its own addon.xml, so it is a separate add-on; the Kodi repo takes one add-on per "
                    f"submission") for f in outer]
