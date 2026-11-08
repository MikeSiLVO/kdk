"""The Kodi repo's add-on list per branch, read from addons.xml.gz files the caller downloaded."""

from __future__ import annotations

import gzip
import os
import xml.etree.ElementTree as ET
from typing import NamedTuple

from . import versions


class Import(NamedTuple):
    """One <import> of a listed add-on: its id and whether it is optional."""

    addon: str
    optional: bool


class Entry(NamedTuple):
    """One listed copy of an add-on: version, imports and extension points."""

    version: str
    imports: tuple[Import, ...]
    points: tuple[str, ...]


class Index:
    """Add-on lists of the branches whose <branch>.xml.gz the folder holds, read on first use."""

    def __init__(self, folder: str | None):
        self.folder = folder
        self._branches: dict[str, dict[str, list[Entry]] | None] = {}
        # branches asked for whose list is missing, for the run's notices
        self.missing: list[str] = []

    def has(self, branch: str) -> bool:
        """True when the branch's list was given and reads."""
        return self._load(branch) is not None

    def _load(self, branch: str) -> dict[str, list[Entry]] | None:
        """Branch entries by add-on id, cached; None if missing or broken, noted in missing."""
        if branch not in self._branches:
            self._branches[branch] = self._read(branch)
            if self._branches[branch] is None and self.folder and branch not in self.missing:
                self.missing.append(branch)
        return self._branches[branch]

    def _read(self, branch: str) -> dict[str, list[Entry]] | None:
        """Read the branch's list into entries by add-on id; None when absent or unreadable."""
        if not self.folder:
            return None
        path = os.path.join(self.folder, f"{branch}.xml.gz")
        entries: dict[str, list[Entry]] = {}
        try:
            with gzip.open(path, "rb") as stream:
                for _, node in ET.iterparse(stream, events=("end",)):
                    if node.tag != "addon":
                        continue
                    addon_id = node.get("id")
                    if addon_id:
                        imports = tuple(Import(i.get("addon") or "", i.get("optional") == "true")
                                        for i in node.iterfind("requires/import"))
                        points = tuple(e.get("point") or "" for e in node.iterfind("extension"))
                        entries.setdefault(addon_id, []).append(Entry(node.get("version") or "", imports, points))
                    node.clear()
        except (OSError, EOFError, ET.ParseError):
            return None
        return entries

    def highest(self, branch: str, addon_id: str) -> str | None:
        """Highest listed version of the add-on on the branch, None when it is not listed there."""
        listed = (self._load(branch) or {}).get(addon_id)
        if not listed:
            return None
        known = [(parsed, e.version) for e in listed if (parsed := versions.parse(e.version)) is not None]
        return max(known)[1] if known else listed[0].version

    def contains(self, branch: str, addon_id: str) -> bool:
        """True when the branch lists the add-on."""
        return addon_id in (self._load(branch) or {})

    def dependents(self, branch: str, addon_id: str) -> set[tuple[str, str]]:
        """Id and version of every listed copy on the branch that imports the add-on."""
        return {(other, entry.version) for other, listed in (self._load(branch) or {}).items()
                for entry in listed if any(i.addon == addon_id for i in entry.imports)}

    def with_point(self, branch: str, point: str) -> set[str]:
        """Ids of the add-ons on the branch with an extension at the point."""
        return {addon_id for addon_id, listed in (self._load(branch) or {}).items()
                if any(point in entry.points for entry in listed)}

    def ids(self, branch: str) -> set[str]:
        """Every add-on id the branch lists."""
        return set(self._load(branch) or {})
