"""Builders of throwaway add-on folders, branch lists and images for the add-on check tests."""

from __future__ import annotations

import gzip
import os
import shutil
import struct
import tempfile
import unittest
import zlib

from kdk.addoncheck.core import validate_addon

ADDON_XML = """<?xml version="1.0" encoding="UTF-8"?>
<addon id="{id}" name="{name}" version="{version}" provider-name="Someone">
  <requires>
{imports}
  </requires>
  <extension point="xbmc.python.script" library="default.py"/>
  <extension point="xbmc.addon.metadata">
{metadata}
  </extension>
</addon>
"""

IMPORTS = '    <import addon="xbmc.python" version="3.0.0"/>'

METADATA = """    <summary lang="en_GB">Shows a thing</summary>
    <description lang="en_GB">Shows a thing on screen.</description>
    <license>GPL-2.0-or-later</license>
    <forum>https://forum.kodi.tv/showthread.php?tid=12345</forum>
    <news>v1.0.0 - first release</news>
    <assets>
      <icon>resources/icon.png</icon>
      <fanart>resources/fanart.jpg</fanart>
    </assets>"""

PO_HEADER = 'msgid ""\nmsgstr ""\n"Language: en_GB\\n"\n\n'

GPL_TEXT = ("                    GNU GENERAL PUBLIC LICENSE\n                       Version 2, June 1991\n\n"
            " Copyright (C) 1989, 1991 Free Software Foundation, Inc.\n")
MIT_TEXT = ("Permission is hereby granted, free of charge, to any person obtaining a copy of this software, to deal "
            "in the Software without restriction.\n\nThe above copyright notice and this permission notice shall be "
            "included in all copies or substantial portions of the Software.\n")


def png(width: int, height: int, alpha: int | None = None) -> bytes:
    """A PNG of one color, RGB, or RGBA with the alpha given."""
    channels = 3 if alpha is None else 4
    pixel = b"\x10\x20\x30" + (b"" if alpha is None else bytes([alpha]))
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2 if channels == 3 else 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(width: int, height: int, padding: int = 0) -> bytes:
    """A JPEG header of the size given, padded to a file size."""
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + frame + b"\x00" * padding + b"\xff\xd9"


def addon_xml(addon_id="script.test", name="Test", version="1.0.0", imports=IMPORTS, metadata=METADATA) -> str:
    """An addon.xml for a script with the parts given."""
    return ADDON_XML.format(id=addon_id, name=name, version=version, imports=imports, metadata=metadata)


def clean_files(addon_id="script.test", **xml) -> dict:
    """Files of an add-on that passes every check, its addon.xml shaped by the keywords."""
    return {
        "addon.xml": addon_xml(addon_id, **xml),
        "default.py": "from resources.lib import main\nmain.run()\n",
        "LICENSE.txt": GPL_TEXT,
        "resources/icon.png": png(256, 256),
        "resources/fanart.jpg": jpeg(1280, 720),
        "resources/settings.xml": '<?xml version="1.0"?>\n<settings version="1"/>\n',
        "resources/language/resource.language.en_gb/strings.po": PO_HEADER + 'msgctxt "#32000"\nmsgid "Hello"\n'
                                                                             'msgstr ""\n',
    }


def index_entry(addon_id: str, version: str, imports=(), points=("xbmc.python.script",)) -> str:
    """One <addon> of a branch list."""
    requires = "".join(f'<import addon="{i}" version="1.0.0"/>' for i in imports)
    extensions = "".join(f'<extension point="{p}"/>' for p in points)
    return f'<addon id="{addon_id}" version="{version}"><requires>{requires}</requires>{extensions}</addon>'


class AddonCase(unittest.TestCase):
    """Test case that writes add-on folders and branch lists under a temporary folder."""

    def setUp(self):
        """Set up a temp folder with an empty index folder inside."""
        self.tmp = tempfile.mkdtemp()
        self.index = os.path.join(self.tmp, "index")
        os.makedirs(self.index)

    def tearDown(self):
        """Tear down the temp folder."""
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_index(self, branch: str, *entries: str) -> None:
        """Write the branch's list with the entries."""
        body = "<addons>" + "".join(entries) + "</addons>"
        with gzip.open(os.path.join(self.index, f"{branch}.xml.gz"), "wb") as f:
            f.write(body.encode("utf-8"))

    def write_all_indexes(self, *entries: tuple[str, str]) -> None:
        """Write every branch's list, empty unless entries are given for it as (branch, entry)."""
        from kdk.addoncheck.releases import BRANCHES

        for branch in BRANCHES:
            self.write_index(branch, *[e for b, e in entries if b == branch])

    def make(self, files: dict, folder: str = "script.test") -> str:
        """Write the files into a folder named after the add-on; returns its path."""
        path = os.path.join(self.tmp, folder)
        for rel, content in files.items():
            full = os.path.join(path, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def run_check(self, files: dict, release="omega", folder="script.test", index=True, tree=None) -> dict:
        """Validate the add-on built from the files; returns the result."""
        path = self.make(files, folder)
        return validate_addon(path, release, index_dir=self.index if index else None, tree=tree)

    def rows(self, files: dict, rule_prefix="", **kwargs) -> list[dict]:
        """Rows of the run whose rule starts with the prefix given."""
        result = self.run_check(files, **kwargs)
        return [r for rows in result["issues"].values() for r in rows if r["rule"].startswith(rule_prefix)]

    def rules(self, files: dict, rule_prefix="", **kwargs) -> list[str]:
        """Rule ids of the run's rows that start with the prefix, sorted."""
        return sorted(r["rule"] for r in self.rows(files, rule_prefix, **kwargs))
