"""Checks of the <import> elements: core versions per branch, availability and required imports."""

from __future__ import annotations

from . import versions
from .packaging.version import Version
from .releases import BRANCHES, CORE
from .rules import WARNING, finding
from .submission import Submission

# imports the Kodi repo's checker never looks up in the branch's list
IGNORED = {
    "xbmc.metadata.scraper.albums", "xbmc.metadata.scraper.movies", "xbmc.metadata.scraper.musicvideos",
    "xbmc.metadata.scraper.tvshows", "xbmc.metadata.scraper.library", "xbmc.ui.screensaver", "xbmc.player.musicviz",
    "xbmc.python.pluginsource", "xbmc.python.script", "xbmc.python.weather", "xbmc.python.lyrics",
    "xbmc.python.library", "xbmc.python.module", "xbmc.subtitle.module", "kodi.context.item", "kodi.game.controller",
    "xbmc.gui.skin", "xbmc.webinterface", "xbmc.addon.repository", "xbmc.pvrclient", "kodi.gameclient",
    "kodi.peripheral", "kodi.resource", "xbmc.addon.video", "xbmc.addon.audio", "xbmc.addon.image",
    "xbmc.addon.executable", "kodi.addon.game", "kodi.audioencoder", "kodi.audiodecoder", "xbmc.service",
    "kodi.resource.images", "kodi.resource.language", "kodi.resource.uisounds", "kodi.resource.games",
    "kodi.resource.font", "kodi.inputstream", "kodi.vfs", "kodi.imagedecoder", "xbmc.addon", "xbmc.gui",
    "xbmc.json", "xbmc.metadata", "xbmc.python", "script.module.pil", "kodi.binary.global.main",
    "kodi.binary.global.audioengine", "kodi.binary.global.filesystem", "kodi.binary.global.general",
    "kodi.binary.global.gui", "kodi.binary.global.network", "kodi.binary.global.tools",
    "kodi.binary.instance.audiodecoder", "kodi.binary.instance.audioencoder", "kodi.binary.instance.game",
    "kodi.binary.instance.imagedecoder", "kodi.binary.instance.inputstream", "kodi.binary.instance.peripheral",
    "kodi.binary.instance.pvr", "kodi.binary.instance.screensaver", "kodi.binary.instance.vfs",
    "kodi.binary.instance.videocodec", "kodi.binary.instance.visualization", "script.module.pycryptodome",
}

# the import each extension point needs
EXTENSIONS = {
    "kodi.gameclient": "kodi.binary.instance.game", "xbmc.gui.skin": "xbmc.gui",
    "kodi.vfs": "kodi.binary.instance.vfs", "xbmc.metadata.scraper.albums": "xbmc.metadata",
    "xbmc.metadata.scraper.artists": "xbmc.metadata", "xbmc.metadata.scraper.library": "xbmc.metadata",
    "xbmc.metadata.scraper.movies": "xbmc.metadata", "xbmc.metadata.scraper.musicvideos": "xbmc.metadata",
    "xbmc.metadata.scraper.tvshows": "xbmc.metadata", "xbmc.pvrclient": "kodi.binary.instance.pvr",
    "xbmc.python.library": "xbmc.python", "xbmc.python.lyrics": "xbmc.python", "xbmc.python.module": "xbmc.python",
    "xbmc.python.pluginsource": "xbmc.python", "xbmc.python.script": "xbmc.python",
    "xbmc.python.weather": "xbmc.python", "xbmc.ui.screensaver": "xbmc.python", "xbmc.webinterface": "xbmc.json",
}


def check(sub: Submission) -> list[dict]:
    """Issue rows for the imports; a broken add-on gets only the Python 3 check."""
    root = sub.root
    if root is None:
        return []
    rows = []
    imports = root.findall("requires/import")
    for node in imports:
        addon, version = node.get("addon") or "", node.get("version")
        parsed = versions.parse(version)
        if addon == "xbmc.python" and parsed is not None and parsed < Version("3.0.0"):
            rows.append(finding("deps.python-below-3", sub.xml_path, node.sourceline, addon,
                                f"xbmc.python {version} is below 3.0.0; add-ons must target Python 3"))
        if sub.broken:
            continue
        if addon in CORE:
            rows += _core_rows(sub, node, addon, version)
        elif node.get("optional") != "true":
            rows += _module_rows(sub, node, addon, version)
        if addon == "script.module.simplejson":
            rows.append(finding("deps.simplejson", sub.xml_path, node.sourceline, addon,
                                "script.module.simplejson is not needed; Python's own json module does the same"))
        if addon == "xbmc.addon":
            rows.append(finding("deps.unneeded-core", sub.xml_path, node.sourceline, addon,
                                "the xbmc.addon import is not needed by Python add-ons; remove it"))
        elif addon == "xbmc.gui" and not any(rel.startswith("resources/skins/") and rel.lower().endswith(".xml")
                                             for rel in sub.files):
            rows.append(finding("deps.unneeded-core", sub.xml_path, node.sourceline, addon,
                                "the xbmc.gui import is needed only for window XML under resources/skins; this "
                                "add-on has none"))
    if sub.broken:
        return rows
    imported = {node.get("addon") for node in imports}
    for ext in root.findall("extension"):
        needed = EXTENSIONS.get(ext.get("point") or "")
        if needed and needed not in imported:
            rows.append(finding("deps.extension-import", sub.xml_path, ext.sourceline, needed,
                                f"{ext.get('point')} needs an import of {needed}"))
    return rows + _consumer_rows(sub, root)


def _core_rows(sub: Submission, node, addon: str, version: str | None) -> list[dict]:
    """A core import against the oldest version the branch accepts, ships first and advises."""
    abi = CORE[addon][sub.release]
    if not version:
        if node.get("optional") == "true":
            return []
        return [finding("deps.no-version", sub.xml_path, node.sourceline, addon,
                        f"the {addon} import has no version, which Kodi reads as too old to install")]
    parsed = versions.parse(version)
    if parsed is None:
        return []
    rows = []
    floor, ceiling, advised = (Version(v) for v in abi)
    needed = versions.parse(node.get("minversion")) or parsed
    if parsed < floor:
        rows.append(finding("deps.abi-below-min", sub.xml_path, node.sourceline, addon,
                            f"{addon} {version} is below {abi.floor}, the oldest {sub.release} accepts, so Kodi "
                            f"refuses to install the add-on"))
    elif needed > ceiling:
        rows.append(finding("deps.abi-above-branch", sub.xml_path, node.sourceline, addon,
                            f"{addon} {node.get('minversion') or version} is above {abi.ceiling}, which "
                            f"{sub.release}'s first release ships, so the add-on cannot install there"))
    elif parsed < advised <= ceiling:
        rows.append(finding("deps.not-advised", sub.xml_path, node.sourceline, addon,
                            f"the Kodi repo advises {addon} {abi.advised} for {sub.release}; {version} installs "
                            f"fine"))
    return rows


def _module_rows(sub: Submission, node, addon: str, version: str | None) -> list[dict]:
    """A non-core import missing from the branch, above what it holds, or without a version."""
    if addon in IGNORED:
        return []
    if sub.index.has(sub.release):
        held = sub.index.highest(sub.release, addon)
        if held is None:
            return [finding("deps.unavailable", sub.xml_path, node.sourceline, addon,
                            f"{addon} is not in the {sub.release} repository, so the add-on cannot install "
                            f"until it is")]
        held_parsed, parsed = versions.parse(held), versions.parse(version)
        if parsed is not None and held_parsed is not None and held_parsed < parsed:
            return [finding("deps.version-unavailable", sub.xml_path, node.sourceline, addon,
                            f"{addon} {version} is needed but the {sub.release} repository holds {held}, so "
                            f"Kodi will not install the add-on")]
    if not version:
        return [finding("deps.no-version", sub.xml_path, node.sourceline, addon,
                        f"the {addon} import has no version; give the oldest version the add-on works with",
                        WARNING)]
    return []


def _consumer_rows(sub: Submission, root) -> list[dict]:
    """A module nothing imports on this or an older branch, nor a newer one holding it unchanged."""
    addon_id = sub.addon_id
    if not addon_id.startswith("script.module.") or not all(sub.index.has(b) for b in BRANCHES):
        return []
    target = BRANCHES.index(sub.release)
    consumers: set[tuple[str, str]] = set()
    for branch in BRANCHES[:target]:
        consumers |= sub.index.dependents(branch, addon_id)
    held = None
    for branch in BRANCHES[target:]:
        found = sub.index.highest(branch, addon_id)
        if found and held and found != held:
            break
        held = found
        consumers |= sub.index.dependents(branch, addon_id)
    if consumers:
        return []
    return [finding("deps.module-no-consumer", sub.xml_path, root.sourceline, addon_id,
                    f"no add-on in the Kodi repo imports {addon_id}; a module is accepted for the add-ons that "
                    f"use it")]
