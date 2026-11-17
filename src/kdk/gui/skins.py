"""Skin folders the GUI opens: the Kodi release addon.xml implies, and whether a chosen one fits."""

from __future__ import annotations

import os

from lxml import etree

from kdk.libs.addon.addon import Addon

RELEASES: tuple[str, ...] = tuple(item["name"] for item in Addon.RELEASES)
_BY_NAME = {item["name"]: item for item in Addon.RELEASES}


def gui_import(skin_path: str) -> tuple[str, int]:
    """Version and line of addon.xml's xbmc.gui import; empty and 0 when there is none to read."""
    try:
        root = etree.parse(os.path.join(skin_path, "addon.xml")).getroot()
    except (OSError, etree.XMLSyntaxError):
        return "", 0
    node = root.find(".//import[@addon='xbmc.gui']")
    if node is None:
        return "", 0
    return node.get("version") or "", node.sourceline or 0


def implied_release(version: str) -> str:
    """Release used when none is picked: the oldest covering the import, else the newest."""
    wanted = Addon._safe_version_tuple(version)
    if wanted is not None:
        for item in Addon.RELEASES:
            target = Addon._safe_version_tuple(item["gui_version"])
            if target is not None and wanted <= target:
                return item["name"]
    return RELEASES[-1]


def needed_import(version: str, release: str) -> str:
    """Version of xbmc.gui the release needs in place of this import; empty when it loads it."""
    wanted = Addon._safe_version_tuple(version)
    item = _BY_NAME.get(release)
    if wanted is None or item is None:
        return ""
    lowest = Addon._safe_version_tuple(item["gui_abi"])
    highest = Addon._safe_version_tuple(item["gui_version"])
    if lowest is None or highest is None or lowest <= wanted <= highest:
        return ""
    return item["gui_version"]
