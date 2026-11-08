"""Checks of Kodi's Python API use: removed and deprecated names, waits, builtins and JSON-RPC."""

from __future__ import annotations

import ast
import functools
import json
import os

from .names import Names
from .rules import HINT, WARNING, finding
from .submission import Submission

# names that raise on every branch the add-on checks cover, with what replaced them
REMOVED = {
    "xbmc.LOGNOTICE": "use xbmc.LOGINFO",
    "xbmc.LOGSEVERE": "use xbmc.LOGFATAL",
    "xbmc.abortRequested": "use xbmc.Monitor().abortRequested()",
    "xbmc.makeLegalFilename": "it moved to xbmcvfs.makeLegalFilename",
    "xbmc.validatePath": "it moved to xbmcvfs.validatePath",
    "xbmcgui.ListItem.setIconImage": "use setArt",
    "xbmcgui.ListItem.setThumbnailImage": "use setArt",
}

# names that still work from nexus on but log a deprecation warning on every call
LOGGED = {
    "xbmcgui.ListItem.setInfo": "the InfoTagVideo, InfoTagMusic, InfoTagPicture or InfoTagGame setters",
    "xbmcgui.ListItem.setUniqueIDs": "InfoTagVideo.setUniqueIDs()",
    "xbmcgui.ListItem.setRating": "InfoTagVideo.setRating()",
    "xbmcgui.ListItem.addSeason": "InfoTagVideo.addSeason()",
    "xbmcgui.ListItem.getUniqueID": "InfoTagVideo.getUniqueID()",
    "xbmcgui.ListItem.getRating": "InfoTagVideo.getRating()",
    "xbmcgui.ListItem.getVotes": "InfoTagVideo.getVotesAsInt()",
    "xbmcgui.ListItem.setCast": "InfoTagVideo.setCast()",
    "xbmcgui.ListItem.addAvailableArtwork": "InfoTagVideo.addAvailableArtwork()",
    "xbmcgui.ListItem.addStreamInfo": "InfoTagVideo.addVideoStream(), addAudioStream() or addSubtitleStream()",
    "xbmc.InfoTagVideo.getVotes": "getVotesAsInt()",
    "xbmc.InfoTagVideo.getLastPlayed": "getLastPlayedAsW3C()",
    "xbmc.InfoTagVideo.getPremiered": "getPremieredAsW3C()",
    "xbmc.InfoTagVideo.getFirstAired": "getFirstAiredAsW3C()",
    "xbmc.InfoTagMusic.getLastPlayed": "getLastPlayedAsW3C()",
}
LOGGED_PIERS = {"xbmcgui.ListItem.setAvailableFanart": "InfoTagVideo.setAvailableFanart()"}
RESUME_KEYS = {"resumetime", "totaltime"}

# names deprecated in Kodi's documentation from nexus on, without a warning at run time
DOCUMENTED = {
    **{f"xbmcaddon.Addon.{verb}Setting{kind}": f"Addon().getSettings().{verb}{kind}()"
       for verb in ("get", "set") for kind in ("Bool", "Int", "Number", "String")},
    "xbmc.InfoTagVideo.getDirector": "getDirectors()",
    "xbmc.InfoTagVideo.getWritingCredits": "getWriters()",
    "xbmc.InfoTagVideo.getGenre": "getGenres()",
    "xbmc.InfoTagVideo.getCast": "getActors()",
    "xbmc.InfoTagMusic.getGenre": "getGenres()",
}


@functools.lru_cache(maxsize=1)
def _jsonrpc() -> dict:
    """Each branch's JSON-RPC methods by lowercased name, with their name and allowed properties."""
    with open(os.path.join(os.path.dirname(__file__), "data", "jsonrpc.json"), encoding="utf-8") as f:
        return json.load(f)["methods"]


def check(sub: Submission) -> list[dict]:
    """Issue rows for the Kodi API use in the add-on's own Python."""
    rows = []
    for rel, tree in sub.own_code().items():
        names = Names(tree)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        reported = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
                rows += _name_rows(sub, rel, node, names.qualify(node), parents, reported)
            elif isinstance(node, ast.Call):
                rows += _call_rows(sub, rel, node, names.call(node), names)
    return rows


def _name_rows(sub: Submission, rel: str, node, name: str | None, parents: dict, reported: set) -> list[dict]:
    """Rows for a name not yet reported on its line: translatePath, removed and deprecated names."""
    if not name or (node.lineno, name) in reported:
        return []
    reported.add((node.lineno, name))
    path, line = sub.abs(rel), node.lineno
    if name == "xbmc.translatePath" and not _translatepath_fallback(node, parents):
        severity = WARNING if sub.release == "matrix" else None
        return [finding("py.translatepath", path, line, name,
                        "xbmc.translatePath is gone from Kodi 20 and raises AttributeError there; use "
                        "xbmcvfs.translatePath" if severity is None else
                        "xbmc.translatePath is deprecated and gone from Kodi 20; use xbmcvfs.translatePath", severity)]
    if name in REMOVED:
        return [finding("py.removed-api", path, line, name,
                        f"{name} no longer exists and raises at run time; {REMOVED[name]}")]
    if sub.release == "matrix":
        return []
    logged = LOGGED.get(name) or (LOGGED_PIERS.get(name) if sub.release == "piers" else None)
    if logged:
        return [finding("py.deprecated-logged", path, line, name,
                        f"{name} logs a deprecation warning on every call; use {logged}")]
    if name in DOCUMENTED:
        return [finding("py.deprecated-doc", path, line, name, f"{name} is deprecated; use {DOCUMENTED[name]}")]
    return []


def _translatepath_fallback(node, parents: dict) -> bool:
    """True when xbmc.translatePath backs up xbmcvfs.translatePath or handles an AttributeError."""
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
            before = parent.values[:parent.values.index(child)] if child in parent.values else []
            if any("translatePath" in ast.dump(value) for value in before):
                return True
        if isinstance(parent, ast.IfExp) and child is not parent.test and "translatePath" in ast.dump(parent.test):
            return True
        if isinstance(parent, ast.ExceptHandler) and parent.type is not None and \
                "AttributeError" in ast.dump(parent.type):
            return True
        child, parent = parent, parents.get(parent)
    return False


def _keywords(node: ast.Call) -> set[str]:
    """Names of the keyword arguments a call passes."""
    return {k.arg for k in node.keywords if k.arg}


def _call_rows(sub: Submission, rel: str, node: ast.Call, called: str | None, names: Names) -> list[dict]:
    """Rows for one call: removed arguments, resume keys, zero waits, builtins and JSON-RPC."""
    path, line, rows = sub.abs(rel), node.lineno, []
    keywords = _keywords(node)
    removed = None
    if called == "xbmcgui.ListItem" and (keywords & {"iconImage", "thumbnailImage"} or (
            len(node.args) > 3 and not (isinstance(node.args[3], ast.Constant) and isinstance(node.args[3].value, bool)))):
        removed = "xbmcgui.ListItem() takes label, label2, path and offscreen; set icons with setArt"
    elif called in ("xbmcgui.Dialog.yesno", "xbmcgui.Dialog.ok") and (
            keywords & {"line1", "line2", "line3"} or (called.endswith(".ok") and len(node.args) > 2)):
        removed = f"{called.rsplit('.', 1)[1]}() takes a heading and one message; line1 to line3 are gone"
    elif called in ("xbmcgui.DialogProgress.create", "xbmcgui.DialogProgress.update") and (
            keywords & {"line2", "line3"} or len(node.args) > 2):
        removed = f"DialogProgress.{called.rsplit('.', 1)[1]}() takes one message; line2 and line3 are gone"
    elif called == "xbmcgui.ControlEdit" and "isPassword" in keywords:
        removed = "ControlEdit no longer takes isPassword; use setType with xbmcgui.INPUT_TYPE_PASSWORD"
    elif called == "xbmc.startServer" and sub.release != "matrix" and (len(node.args) > 2 or "bWait" in keywords):
        removed = "xbmc.startServer() no longer takes the wait argument"
    if removed:
        rows.append(finding("py.removed-api", path, line, called or "", f"{removed}; the call raises at run time"))
    method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if method in ("setProperty", "getProperty") and called and called.startswith("xbmcgui.ListItem.") and \
            sub.release != "matrix" and _literal(node.args[0] if node.args else None).lower() in RESUME_KEYS:
        rows.append(finding("py.deprecated-logged", path, line, _literal(node.args[0]),
                            f"the {_literal(node.args[0])} property logs a deprecation warning; use "
                            f"InfoTagVideo.setResumePoint() and getResumeTime()"))
    if method == "waitForAbort" and node.args and _waits_forever(node.args[0]):
        rows.append(finding("py.waitforabort-zero", path, line, "waitForAbort",
                            "waitForAbort with a timeout of 0 or less waits until Kodi exits; give a positive "
                            "number of seconds"))
    rows += _builtin_rows(sub, rel, node, called, names, method)
    return rows


def _literal(node) -> str:
    """The text of a string literal, or of the literal parts of an f-string; empty otherwise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def _waits_forever(node) -> bool:
    """True when a timeout constant is 0, negative or rounds to 0 milliseconds."""
    sign = 1
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        node, sign = node.operand, -1
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        return False
    return sign * node.value < 0.0005


def _builtin_rows(sub: Submission, rel: str, node: ast.Call, called: str | None, names: Names,
                  method: str) -> list[dict]:
    """The inputstreamaddon property, Notification builtins and JSON-RPC outside the schema."""
    path, line, rows = sub.abs(rel), node.lineno, []
    first = node.args[0] if node.args else None
    if (method == "setProperty" and _literal(first) == "inputstreamaddon") or \
            "#kodiprop:inputstreamaddon" in _literal(first).lower():
        rows.append(finding("api.inputstreamaddon", path, line, "inputstreamaddon",
                            "inputstreamaddon still works but logs a deprecation on every play; use inputstream"))
    if called == "xbmc.executebuiltin" and _literal(first).lower().startswith("notification("):
        rows.append(finding("api.notification-builtin", path, line, "Notification",
                            "xbmcgui.Dialog().notification() shows the same notification without building a "
                            "builtin string", HINT))
    if called == "xbmc.executeJSONRPC" and first is not None:
        rows += _jsonrpc_rows(sub, rel, line, first, names)
    return rows


def _payload(node, names: Names) -> tuple[str | None, list[str]]:
    """Method and literal properties of a literal JSON-RPC payload; (None, []) otherwise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            data = json.loads(node.value)
        except ValueError:
            return None, []
        params = data.get("params") if isinstance(data, dict) else None
        props = params.get("properties") if isinstance(params, dict) else None
        method = data.get("method") if isinstance(data, dict) else None
        return (method if isinstance(method, str) else None,
                [p for p in props if isinstance(p, str)] if isinstance(props, list) else [])
    if isinstance(node, ast.Call) and names.call(node) == "json.dumps" and node.args and \
            isinstance(node.args[0], ast.Dict):
        fields = _dict_fields(node.args[0])
        method = fields.get("method")
        params = fields.get("params")
        props = _dict_fields(params).get("properties") if isinstance(params, ast.Dict) else None
        items = [e.value for e in props.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)] \
            if isinstance(props, (ast.List, ast.Tuple)) else []
        return (method.value if isinstance(method, ast.Constant) and isinstance(method.value, str) else None), items
    return None, []


def _dict_fields(node: ast.Dict) -> dict:
    """The values of a dict literal by their string keys."""
    return {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}


def _jsonrpc_rows(sub: Submission, rel: str, line: int, node, names: Names) -> list[dict]:
    """A literal JSON-RPC call to a method the branch lacks, or a property the method refuses."""
    method, props = _payload(node, names)
    if not method:
        return []
    known = _jsonrpc()[sub.release].get(method.lower())
    if known is None:
        return [finding("api.jsonrpc-schema", sub.abs(rel), line, method,
                        f"{method} is not a JSON-RPC method on {sub.release}, so the call fails")]
    name, allowed = known
    bad = [p for p in props if allowed is not None and p not in allowed]
    return [finding("api.jsonrpc-schema", sub.abs(rel), line, f"{name} {p}",
                    f"{name} does not accept the property {p} on {sub.release}, so the call fails") for p in bad]
