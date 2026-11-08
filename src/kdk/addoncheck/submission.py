"""One add-on folder as the checks see it: its addon.xml, its files and the branch it targets."""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as StdET

from lxml import etree as ET

from .index import Index

METADATA_POINTS = ("xbmc.addon.metadata", "kodi.addon.metadata")

# import names of modules the Kodi repo ships, beyond those an id spells out
MODULE_NAMES = {"requests", "urllib3", "chardet", "idna", "certifi", "six", "bs4", "soupsieve", "dateutil",
                "simplejson", "yaml", "html5lib", "websocket", "routing"}

_LICENSE_FILE = re.compile(r"(?i)^(license|licence|copying)")
_GIT_QUOTED = re.compile(r'^"(.*)"$')

PARSER = ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=True)


class Submission:
    """An add-on folder with its parsed addon.xml, file list, target branch and branch lists."""

    def __init__(self, path: str, release: str, index: Index, tree: str | None = None):
        self.path = os.path.abspath(path)
        self.folder = os.path.basename(os.path.normpath(self.path))
        self.release = release
        self.index = index
        self.notices: list[str] = []
        self.xml_path = os.path.join(self.path, "addon.xml")
        self.missing = not os.path.isfile(self.xml_path)
        # (line, message) when addon.xml is not well-formed
        self.parse_error: tuple[int, str] | None = None
        self.root = None if self.missing else self._parse()
        self.metadata = self._metadata()
        self.files, self.dirs = self._tree(tree) if tree else self._walk()
        self.from_tree = bool(tree)
        self.exec_known = self.from_tree or sys.platform != "win32"
        self._bundled_roots: tuple[str, ...] | None = None

    @property
    def addon_id(self) -> str:
        """The id addon.xml gives, empty when it gives none."""
        return (self.root.get("id") if self.root is not None else "") or ""

    @property
    def version(self) -> str:
        """The version addon.xml gives, empty when it gives none."""
        return (self.root.get("version") if self.root is not None else "") or ""

    @property
    def broken(self) -> bool:
        """True when addon.xml marks the add-on broken, which leaves most checks out."""
        if self.root is None:
            return False
        if self.root.findall("*//broken"):
            return True
        state = self.root.find("*//lifecyclestate")
        return state is not None and state.get("type") == "broken"

    def _parse(self):
        """Parse addon.xml with line numbers; records the fault and returns None when malformed."""
        try:
            StdET.parse(self.xml_path)
        except StdET.ParseError as e:
            self.parse_error = (e.position[0], _plain_parse_error(str(e)))
            return None
        try:
            return ET.parse(self.xml_path, PARSER).getroot()
        except ET.XMLSyntaxError as e:
            self.parse_error = (e.lineno or 0, _plain_parse_error(e.msg))
            return None

    def _metadata(self):
        """The first metadata extension, or None."""
        if self.root is None:
            return None
        return next((e for e in self.root.findall("extension") if e.get("point") in METADATA_POINTS), None)

    def _walk(self) -> tuple[dict[str, bool], set[str]]:
        """File paths with their executable bit, and folders, from the disk."""
        files, dirs = {}, set()
        for root, folders, names in os.walk(self.path):
            rel_root = os.path.relpath(root, self.path).replace(os.sep, "/")
            prefix = "" if rel_root == "." else rel_root + "/"
            folders.sort()
            for folder in folders:
                dirs.add(prefix + folder)
            # git's own store is reported once as a folder, never listed file by file
            folders[:] = [f for f in folders if f != ".git"]
            for name in sorted(names):
                full = os.path.join(root, name)
                try:
                    executable = bool(os.stat(full).st_mode & 0o111) and not os.path.islink(full)
                except OSError:
                    executable = False
                files[prefix + name] = executable
        return files, dirs

    def _tree(self, tree: str) -> tuple[dict[str, bool], set[str]]:
        """File paths with their executable bit, and folders, from `git ls-tree -r` output."""
        with open(tree, encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        files, dirs = {}, set()
        for line in text.split("\0") if "\0" in text else text.splitlines():
            meta, _, rel = line.partition("\t")
            parts = meta.split()
            if len(parts) < 3 or parts[1] != "blob":
                continue
            quoted = _GIT_QUOTED.match(rel)
            if quoted:
                rel = quoted.group(1).encode("latin-1", "backslashreplace").decode("unicode_escape")
                rel = rel.encode("latin-1", "replace").decode("utf-8", "replace")
            if rel.startswith(self.folder + "/"):
                rel = rel[len(self.folder) + 1:]
            files[rel] = parts[0] == "100755"
            segments = rel.split("/")[:-1]
            dirs.update("/".join(segments[:i]) for i in range(1, len(segments) + 1))
        return files, dirs

    def bundled(self, rel: str) -> bool:
        """True when the path lies inside third-party code bundled with the add-on."""
        if self._bundled_roots is None:
            self._bundled_roots = self._find_bundled()
        return any(rel.startswith(root + "/") for root in self._bundled_roots)

    def _find_bundled(self) -> tuple[str, ...]:
        """Find package folders that hold a license, sit beside package metadata or are a module."""
        names = MODULE_NAMES | {i[len("script.module."):].lower().replace("-", "_")
                                for i in self.index.ids(self.release) if i.startswith("script.module.")}
        packages = sorted({rel.rsplit("/", 1)[0] for rel in self.files if rel.endswith("/__init__.py")})
        roots = []
        for package in packages:
            parent, _, name = package.rpartition("/")
            prefix = parent + "/" if parent else ""
            inside = [rel[len(package) + 1:] for rel in self.files if rel.startswith(package + "/")]
            beside = [d[len(prefix):] for d in self.dirs if d.startswith(prefix) and "/" not in d[len(prefix):]]
            meta = name.lower().replace("-", "_")
            if (any("/" not in f and _LICENSE_FILE.match(f) for f in inside) or name.lower() in names
                    or any(d.lower().replace("-", "_").startswith(meta) and d.endswith((".dist-info", ".egg-info"))
                           for d in beside)):
                roots.append(package)
        return tuple(r for r in roots if not any(r.startswith(o + "/") for o in roots))

    def abs(self, rel: str) -> str:
        """Absolute path of a path relative to the add-on folder."""
        return os.path.join(self.path, *rel.split("/")) if rel else self.path


_PARSE_WORDS = (
    (re.compile(r"not well-formed \(invalid token\)|xmlParseEntityRef|EntityRef: expecting ';'|"
                r"StartTag: invalid element name"),
     "a character XML does not allow here, usually a bare & or < that should be written &amp; or &lt;"),
    (re.compile(r"mismatched tag|Opening and ending tag mismatch"), "a closing tag that does not match its opening tag"),
    (re.compile(r"no element found|Premature end of data|EndTag: '</' not found"),
     "the file ends before every tag is closed"),
    (re.compile(r"junk after document element|Extra content at the end of the document"),
     "content after the closing </addon>"),
    (re.compile(r"unclosed token|Couldn't find end of Start Tag"), "a tag that is never closed"),
    (re.compile(r"duplicate attribute|Attribute \S+ redefined"), "the same attribute twice on one element"),
)


def _plain_parse_error(message: str) -> str:
    """The parse error in plain words where its form is known, else as the parser words it."""
    for pattern, plain in _PARSE_WORDS:
        if pattern.search(message):
            return plain
    return re.sub(r":?\s*line \d+, column \d+$", "", message)
