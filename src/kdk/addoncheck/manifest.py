"""Checks of addon.xml: version against the branches, id, schemas, extensions and metadata."""

from __future__ import annotations

import copy
import os
import re
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

from lxml import etree as ET
from lxml.etree import XMLSchema

from ..libs.validation.repo import VERSION, _plain_schema_error
from . import versions
from .packaging.version import Version
from .releases import BRANCHES, CORE, display, higher, possessive
from .rules import WARNING, finding
from .submission import METADATA_POINTS, Submission

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "data", "schemas")

VERSION_STYLE = re.compile(r"^\d+\.\d+\.\d+([+~][0-9A-Za-z.]+)?$")
ID_CHARS = re.compile(r"^[a-z0-9._-]+$")
LANG_CODE = re.compile(r"^[a-z]{2,3}_[A-Z]{2}(@\S+)?$")
SCHEMA_LANG = re.compile(r"^[a-z]{2,3}(_[A-Z]{2}(@\S+)?)?$")

# schema base name per point; the file is the newest <branch>_<base> at or below the target
VALID_POINTS = {
    "kodi.audiodecoder": "binary_audiodecoder.xsd", "kodi.audioencoder": "binary_audioencoder.xsd",
    "kodi.context.item": "contextitem.xsd", "kodi.gameclient": "binary_gameclient.xsd",
    "kodi.game.controller": "controller.xsd", "kodi.imagedecoder": "binary_imagedecoder.xsd",
    "kodi.inputstream": "binary_inputstream.xsd", "kodi.peripheral": "binary_peripheral.xsd",
    "kodi.pvrclient": "binary_pvr.xsd", "kodi.resource.games": "games.xsd", "kodi.resource.images": "images.xsd",
    "kodi.resource.language": "language.xsd", "kodi.addon.metadata": "metadata.xsd",
    "kodi.resource.uisounds": "uisounds.xsd", "kodi.resource.font": "font.xsd", "kodi.vfs": "binary_vfs.xsd",
    "xbmc.addon.metadata": "metadata.xsd", "xbmc.addon.repository": "repository.xsd", "xbmc.gui.skin": "skin.xsd",
    "xbmc.metadata.scraper.albums": "scraper.xsd", "xbmc.metadata.scraper.artists": "scraper.xsd",
    "xbmc.metadata.scraper.movies": "scraper.xsd", "xbmc.metadata.scraper.musicvideos": "scraper.xsd",
    "xbmc.metadata.scraper.tvshows": "scraper.xsd", "xbmc.metadata.scraper.library": "scraper.xsd",
    "xbmc.player.musicviz": "binary_visualization.xsd", "xbmc.python.script": "pythonscript.xsd",
    "xbmc.python.lyrics": "script.xsd", "xbmc.python.weather": "script.xsd", "xbmc.python.library": "script.xsd",
    "xbmc.python.pluginsource": "pluginsource.xsd", "xbmc.python.module": "script.xsd",
    "xbmc.service": "service.xsd", "xbmc.subtitle.module": "script.xsd", "xbmc.ui.screensaver": "script.xsd",
    "xbmc.webinterface": "webinterface.xsd",
}

# the id prefix the Kodi repo uses for an add-on whose first extension is at the point
ID_PREFIXES = {
    "xbmc.python.pluginsource": "plugin.", "xbmc.python.script": "script.", "xbmc.service": "service.",
    "kodi.context.item": "context.", "xbmc.python.weather": "weather.", "xbmc.python.module": "script.module.",
}

# platform names Kodi reads in <platform>, a few of them missing from the schema's list
KODI_PLATFORMS = {
    "all", "android", "android-aarch64", "android-armv7", "android-i686", "android-x86_64", "darwin_embedded",
    "freebsd", "ios", "ios-aarch64", "linux", "linux-aarch64", "linux-armv7", "linux-armv8", "linux-i686",
    "linux-x86_64", "osx", "osx-arm64", "osx-x86_64", "osx64", "osxarm64", "tvos", "tvos-aarch64", "windows",
    "windows-arm64", "windows-i686", "windows-x86_64", "windowsstore", "windx",
}

TEXT_TAGS = ("summary", "description", "disclaimer", "lifecyclestate")
URL_TAGS = ("source", "website", "forum", "email")
PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net")
PLACEHOLDER_TOKENS = ("your-username", "yourusername", "your_username", "your_name", "username/repo", "user@example")
PLACEHOLDER_WORDS = re.compile(r"\b(TODO|CHANGEME|FIXME)\b|(?i:\blorem ipsum\b)")

_schemas: dict[str, XMLSchema] = {}


def check(sub: Submission) -> list[dict]:
    """Issue rows for addon.xml; a missing or malformed one gives that row alone."""
    if sub.missing:
        return [finding("addon.missing", sub.xml_path, 0, "addon.xml",
                        "The add-on folder has no addon.xml at its root, so Kodi cannot install it")]
    root = sub.root
    if root is None:
        line, message = sub.parse_error or (0, "")
        return [finding("addon.parse", sub.xml_path, line, "addon.xml",
                        f"addon.xml is not well-formed XML: {message}. Every other addon.xml check is skipped")]
    rows = _version_rows(sub, root) + _id_rows(sub, root)
    if sub.broken:
        return rows
    return rows + _schema_rows(sub, root) + _extension_rows(sub, root) + _metadata_rows(sub, root)


def _version_rows(sub: Submission, root) -> list[dict]:
    """Version form and style, against this, older, newer branches; notice when it can't compare."""
    version = sub.version
    if not version or not VERSION.match(version):
        what = f"Version {version!r} is not a version the Kodi repo accepts" if version else "addon.xml has no version"
        return [finding("addon.version-format", sub.xml_path, root.sourceline, version,
                        f"{what}; use major.minor.revision such as 1.0.0, optionally with a suffix such as "
                        f"+matrix.1")]
    rows = []
    if not VERSION_STYLE.match(version):
        rows.append(finding("addon.version-style", sub.xml_path, root.sourceline, version,
                            f"Version {version} is not major.minor.revision such as 1.0.0"))
    parsed = versions.parse(version)
    if parsed is None:
        sub.notices.append(f"Version {version} is not a PEP 440 version, so it was not compared with the "
                           f"versions the branches hold")
        return rows
    for branch in BRANCHES[:BRANCHES.index(sub.release) + 1]:
        held = sub.index.highest(branch, sub.addon_id)
        held_parsed = versions.parse(held)
        if held_parsed is not None and parsed <= held_parsed:
            name = display(branch)
            rows.append(finding("addon.version-not-higher", sub.xml_path, root.sourceline, branch,
                                f"{name} already holds version {held}, not below this {version}, so users on "
                                f"{name} never get this update"))
    for branch in higher(sub.release):
        held = sub.index.highest(branch, sub.addon_id)
        held_parsed = versions.parse(held)
        if held_parsed is None or parsed < held_parsed:
            continue
        name = display(branch)
        # a branch's list also carries older branches' copies, which the server falls back to
        own = sub.index.own_copy(branch)
        if own is None:
            sub.notices.append(f"No copies.json entry for {name}, so addon.version-above-newer did not compare "
                               f"with {name}")
        if not own:
            continue
        if _core_rises(sub, root, branch):
            rows.append(finding("addon.version-above-newer", sub.xml_path, root.sourceline, branch,
                                f"{name} holds version {held}, not above this {version}, and a core import this "
                                f"build uses is too old for {name}, so users moving to {name} will not get "
                                f"the update"))
        else:
            rows.append(finding("addon.version-above-newer", sub.xml_path, root.sourceline, branch,
                                f"{name} holds version {held}, not above this {version}, so users on {name} "
                                f"can be offered this build instead of {possessive(branch)} own", WARNING))
    return rows


def _core_rises(sub: Submission, root, branch: str) -> bool:
    """True when the oldest version a core import accepts rises on the branch."""
    for node in root.findall("requires/import"):
        table = CORE.get(node.get("addon") or "")
        if table and Version(table[branch].floor) > Version(table[sub.release].floor):
            return True
    return False


def _id_rows(sub: Submission, root) -> list[dict]:
    """The id against the folder name, and the form of a new add-on's id."""
    addon_id = sub.addon_id
    rows = []
    if addon_id != sub.folder:
        rows.append(finding("addon.id-folder", sub.xml_path, root.sourceline, addon_id,
                            f"The id {addon_id} differs from the folder name {sub.folder}; Kodi installs an add-on in "
                            f"a folder named after its id"))
    if sub.broken or not sub.index.has(sub.release) or sub.index.contains(sub.release, addon_id):
        return rows
    points = [e.get("point") for e in root.findall("extension") if e.get("point") not in METADATA_POINTS]
    prefix = ID_PREFIXES.get(points[0] or "") if points else None
    if not ID_CHARS.match(addon_id):
        rows.append(finding("addon.id-format", sub.xml_path, root.sourceline, addon_id,
                            f"The id {addon_id} has uppercase letters or characters other than a-z, 0-9, '.', '_' and "
                            f"'-'"))
    elif prefix and not addon_id.startswith(prefix):
        rows.append(finding("addon.id-format", sub.xml_path, root.sourceline, addon_id,
                            f"The id {addon_id} does not start with {prefix}, the prefix the Kodi repo uses for a "
                            f"{points[0]} add-on"))
    return rows


def _schema(release: str, base: str) -> XMLSchema | None:
    """The schema the Kodi repo's checker validates a point against on the branch, or None."""
    for branch in reversed(BRANCHES[:BRANCHES.index(release) + 1]):
        path = os.path.join(SCHEMA_DIR, f"{branch}_{base}")
        if os.path.isfile(path):
            if path not in _schemas:
                _schemas[path] = XMLSchema(ET.parse(path))
            return _schemas[path]
    return None


def _root_schema() -> XMLSchema:
    """The schema for the addon element with its extensions removed."""
    path = os.path.join(SCHEMA_DIR, "addon.xsd")
    if path not in _schemas:
        _schemas[path] = XMLSchema(ET.parse(path))
    return _schemas[path]


def _schema_rows(sub: Submission, root) -> list[dict]:
    """Each extension against its point's schema, then the root with every extension removed."""
    rows = []
    bare = copy.deepcopy(root)
    for ext in list(bare.findall("extension")):
        bare.remove(ext)
    for ext in root.findall("extension"):
        point = ext.get("point") or ""
        base = VALID_POINTS.get(point)
        if base is None:
            rows.append(finding("addon.extension-point", sub.xml_path, ext.sourceline, point,
                                f"{point or 'An empty point'} is not an extension point the Kodi repo knows"))
            continue
        schema = _schema(sub.release, base)
        if schema is not None:
            rows += _errors(sub, schema, ext, point)
    return rows + _errors(sub, _root_schema(), bare, "addon")


def _errors(sub: Submission, schema: XMLSchema, element, point: str) -> list[dict]:
    """Issue rows for each error the schema finds in the element, in plain words where known."""
    if schema.validate(element):
        return []
    rows, seen = [], set()
    for error in schema.error_log:
        if point == "xbmc.service" and "attribute 'start'" in error.message:
            continue
        message, subject = _explain(error.message)
        # a list value that fails reports once for the item and once for the list
        if (error.line, subject, message) not in seen:
            seen.add((error.line, subject, message))
            rows.append(finding("addon.schema", sub.xml_path, error.line, subject, message))
    return rows


def _explain(message: str) -> tuple[str, str]:
    """A schema error in plain words, with the element, or element@attribute, it is about."""
    found = re.match(r"Element '([^']+)'(?:, attribute '([^']+)')?", message)
    tag, attr = (found.group(1), found.group(2)) if found else ("", None)
    subject = f"{tag}@{attr}" if attr else tag
    if "attribute 'lang' is required" in message and tag in ("summary", "description", "disclaimer"):
        return (f"<{tag}> has no lang attribute, which the Kodi repo's schema requires; Kodi itself reads a "
                f"missing lang as en_GB", f"{tag}@lang")
    if tag == "news" and attr == "lang":
        return "<news> has a lang attribute, which the Kodi repo's schema refuses", subject
    if tag == "thumb" and "not expected" in message:
        return "<thumb> is not in the schema's list for <assets>; Kodi reads it, the Kodi repo's checker refuses it", tag
    if tag == "platform":
        value = re.search(r"'([^']*)' is not a valid value|The value '([^']*)'", message)
        name = next((g for g in value.groups() if g is not None), "") if value else ""
        for item in name.split():
            if item in KODI_PLATFORMS:
                return (f"<platform> lists {item}, which Kodi knows but the Kodi repo's schema does not",
                        f"platform@{item}")
        return f"<platform> lists {name!r}, which is not a platform Kodi knows", subject
    if "Element content is not allowed" in message:
        return f"<{tag}> holds an element inside it; it takes plain text only", tag
    if "This element is not expected" in message:
        return f"<{tag}> is not an element the Kodi repo's schema allows here", tag
    return _plain_schema_error(message), subject


def _extension_rows(sub: Submission, root) -> list[dict]:
    """Missing metadata, entry points that do not exist and a start attribute on a service."""
    rows = []
    if sub.metadata is None:
        rows.append(finding("addon.no-metadata", sub.xml_path, root.sourceline, "xbmc.addon.metadata",
                            "addon.xml has no xbmc.addon.metadata extension, which holds what the repo shows"))
    for ext in root.findall("extension"):
        point = ext.get("point") or ""
        nodes = [ext] + (list(ext.iter("item")) if point == "kodi.context.item" else [])
        for node in nodes:
            library = node.get("library")
            if library and not os.path.exists(sub.abs(library.replace("\\", "/"))):
                rows.append(finding("addon.entrypoint-missing", sub.xml_path, node.sourceline, library,
                                    f"{library} does not exist, so Kodi has nothing to run for {point}"))
        if point == "xbmc.service" and ext.get("start") is not None:
            rows.append(finding("addon.service-start", sub.xml_path, ext.sourceline, "start",
                                "The start attribute on xbmc.service is refused by the Kodi repo's schema; Kodi "
                                "ignores it, so remove it"))
    return rows


def _metadata_rows(sub: Submission, root) -> list[dict]:
    """Languages, news, empty elements, links, placeholders and the name in the metadata."""
    meta = sub.metadata
    rows = []
    name = root.get("name") or ""
    if re.search(r"(?i)\b(kodi|xbmc)\b", name) and not sub.addon_id.startswith("script.module."):
        rows.append(finding("addon.name-kodi", sub.xml_path, root.sourceline, name,
                            f"The name {name!r} uses Kodi or XBMC, which the Kodi team asks add-ons to leave out"))
    if meta is None:
        return rows
    rows += _language_rows(sub, meta) + _news_rows(sub, meta)
    for tag in ("email", "forum", "language"):
        for node in meta.findall(tag):
            if not (node.text or "").strip():
                rows.append(finding("addon.empty-element", sub.xml_path, node.sourceline, tag,
                                    f"<{tag}> is empty; remove it or fill it in"))
    for node in meta.findall("forum"):
        url = (node.text or "").strip()
        if url and not _forum_thread(url):
            rows.append(finding("addon.forum-url", sub.xml_path, node.sourceline, "forum",
                                f"{url} is not a forum thread; link the add-on's own thread"))
    return rows + _placeholder_rows(sub, meta)


def _language_rows(sub: Submission, meta) -> list[dict]:
    """Translated text without an en_GB variant, and lang values that are not ll_CC."""
    rows = []
    for tag in TEXT_TAGS:
        nodes = meta.findall(tag)
        langs = [node.get("lang") for node in nodes]
        if len(nodes) >= 2 and not any(lang in (None, "en_GB") for lang in langs):
            rows.append(finding("addon.lang-en-gb", sub.xml_path, nodes[0].sourceline, tag,
                                f"<{tag}> has {len(nodes)} languages and none is lang=\"en_GB\", so users whose "
                                f"language matches none of them see an empty {tag}"))
        elif len(nodes) == 1 and langs[0] is not None and langs[0] != "en_GB":
            rows.append(finding("addon.lang-en-gb", sub.xml_path, nodes[0].sourceline, tag,
                                f"The only <{tag}> has lang=\"{langs[0]}\"; the source text is lang=\"en_GB\"",
                                WARNING))
        for node in nodes:
            lang = node.get("lang")
            if lang and lang != "no" and SCHEMA_LANG.match(lang) and not LANG_CODE.match(lang):
                rows.append(finding("addon.lang-format", sub.xml_path, node.sourceline, f"{tag}@{lang}",
                                    f"lang=\"{lang}\" on <{tag}> is not a language and country code such as "
                                    f"de_DE"))
    return rows


def _news_rows(sub: Submission, meta) -> list[dict]:
    """News missing, news repeated for one language, and a changelog.txt that news hides."""
    rows = []
    news = meta.findall("news")
    if not any((node.text or "").strip() for node in news):
        rows.append(finding("addon.news-missing", sub.xml_path, meta.sourceline, "news",
                            "No <news>, so users browsing the repo see no list of changes"))
    elif "changelog.txt" in sub.files:
        rows.append(finding("addon.changelog-file", sub.abs("changelog.txt"), 0, "changelog.txt",
                            "Kodi reads changelog.txt only when <news> is empty, so beside <news> it is never shown"))
    by_lang = defaultdict(list)
    for node in news:
        by_lang[node.get("lang")].append(node)
    for lang, nodes in by_lang.items():
        if len(nodes) > 1:
            rows.append(finding("addon.news-multiple", sub.xml_path, nodes[1].sourceline, lang or "news",
                                f"{len(nodes)} <news> elements for one language; Kodi shows only the first"))
    return rows


def _forum_thread(url: str) -> bool:
    """True unless the link is on forum.kodi.tv and is not a thread."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    if (parsed.hostname or "").lower() not in ("forum.kodi.tv", "www.forum.kodi.tv"):
        return True
    path = parsed.path or "/"
    if path.startswith("/showthread.php"):
        return any(tid.isdigit() for tid in parse_qs(parsed.query).get("tid", []))
    return bool(re.match(r"^/thread-\d+", path))


def _placeholder(text: str) -> bool:
    """True when the text holds a placeholder link token."""
    return any(token in text.lower() for token in PLACEHOLDER_TOKENS)


def _placeholder_rows(sub: Submission, meta) -> list[dict]:
    """Placeholder links and addresses, errors, and placeholder text, warnings."""
    rows = []
    for tag in URL_TAGS:
        for node in meta.findall(tag):
            value = (node.text or "").strip()
            host = (urlparse(value if "://" in value else "https://" + value).hostname or "").lower()
            if host in PLACEHOLDER_HOSTS or host.endswith(tuple("." + h for h in PLACEHOLDER_HOSTS)) or \
                    _placeholder(value):
                rows.append(finding("addon.placeholder", sub.xml_path, node.sourceline, tag,
                                    f"<{tag}> holds placeholder text: {value}"))
    for tag in ("summary", "description", "disclaimer", "news"):
        for node in meta.findall(tag):
            text = node.text or ""
            if _placeholder(text) or PLACEHOLDER_WORDS.search(text):
                rows.append(finding("addon.placeholder", sub.xml_path, node.sourceline, tag,
                                    f"<{tag}> holds placeholder text", WARNING))
    en_gb = "resources/language/resource.language.en_gb/strings.po"
    if en_gb in sub.files:
        try:
            with open(sub.abs(en_gb), encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        for number, line in enumerate(lines, 1):
            msgid = re.match(r'\s*msgid\s+"(.*)"\s*$', line)
            if msgid and (_placeholder(msgid.group(1)) or PLACEHOLDER_WORDS.search(msgid.group(1))):
                rows.append(finding("addon.placeholder", sub.abs(en_gb), number, msgid.group(1)[:40],
                                    "An English string holds placeholder text", WARNING))
    return rows
