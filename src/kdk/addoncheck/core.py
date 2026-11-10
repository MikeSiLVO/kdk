"""Runner of every add-on check over one folder, shared by the command line and tests."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from . import (api, artwork, dependencies, files, languages, licenses, manifest, practices, strings, syntax,
               translations)
from .index import Index
from .releases import TARGETS, display
from .rules import ERROR, PREFIXES, finding
from .submission import Submission

logger = logging.getLogger("kdk.addoncheck")

CHECKS = (manifest, dependencies, files, languages, translations, strings, licenses, artwork, syntax, practices, api)

# a broken add-on still gets its version, id and Python 3 import checked
BROKEN_CHECKS = (manifest, dependencies)


def validate_addon(path: str, release: str, *, index_dir: str | None = None, tree: str | None = None) -> dict:
    """Run the checks the folder's addon.xml allows; returns issues by category, or an error."""
    path = os.path.abspath(path)
    started = time.time()
    result = {"issues": {}, "addon_name": os.path.basename(path), "addon_path": path, "addon_id": "",
              "addon_version": "", "provider_name": "", "kodi_release": release, "notices": [],
              "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "duration": 0.0, "error": None}
    if not os.path.isdir(path):
        return {**result, "error": f"{path} is not a directory"}
    if release not in TARGETS:
        return {**result, "error": f"{release} is not a branch the add-on checks cover; "
                                   f"use one of {', '.join(TARGETS)}"}
    if tree and not os.path.isfile(tree):
        return {**result, "error": f"{tree} is not a file"}
    index = Index(index_dir)
    sub = Submission(path, release, index, tree)
    checks = (manifest,) if sub.missing else BROKEN_CHECKS if sub.broken else CHECKS
    rows = []
    for check in checks:
        try:
            rows += check.check(sub)
        except Exception as e:
            logger.error("Check %s failed: %s", check.__name__, e, exc_info=True)
            rows.append(finding("kdk.check-failed", sub.path, 0, check.__name__.rsplit(".", 1)[-1],
                                f"Check failed: {e}", ERROR))
    notices = list(sub.notices)
    if sub.broken:
        notices.insert(0, "addon.xml marks the add-on broken, so only its version and Python import were checked")
    if not index_dir:
        notices.append("No index folder was given, so rules that compare against the Kodi repo's add-on lists "
                       "were skipped")
    notices += [f"No usable {b}.xml.gz in the index folder, so rules that need the {display(b)} add-on list were "
                f"skipped" for b in index.missing]
    issues: dict[str, list[dict]] = {}
    for row in rows:
        issues.setdefault(PREFIXES[row["rule"].split(".")[0]], []).append(row)
    root = sub.root
    return {**result, "issues": issues, "notices": notices, "duration": time.time() - started,
            "addon_name": (root.get("name") if root is not None else "") or sub.folder,
            "addon_id": sub.addon_id, "addon_version": sub.version,
            "provider_name": (root.get("provider-name") if root is not None else "") or "",
            "bundled": sorted(folder + "/" for folder in sub.bundled_roots())}
