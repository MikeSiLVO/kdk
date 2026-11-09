"""Checks of add-on Python against the oldest Python and the practices repo reviewers ask."""

from __future__ import annotations

import ast
import re

from lxml import etree as ET

from .names import Names
from .rules import HINT, finding
from .submission import MODULE_NAMES, PARSER, Submission

BUILTIN_GENERICS = {"list", "dict", "tuple", "set", "frozenset", "type"}

# standard library names newer than Python 3.8, with the version that added them
NEWER_NAMES = {
    "functools.cache": "3.9", "math.lcm": "3.9", "random.randbytes": "3.9", "itertools.pairwise": "3.10",
    "asyncio.TaskGroup": "3.11", "datetime.UTC": "3.11", "itertools.batched": "3.12",
}
NEWER_METHODS = {"removeprefix": "3.9", "removesuffix": "3.9", "bit_count": "3.10"}
NEWER_MODULES = {"zoneinfo": "3.9", "graphlib": "3.9", "tomllib": "3.11"}
NEWER_BUILTINS = {"aiter": "3.10", "anext": "3.10", "ExceptionGroup": "3.11"}
GUARD_ERRORS = {"ImportError", "ModuleNotFoundError", "AttributeError", "NameError", "Exception", "BaseException"}

REQUESTS = {f"requests.{m}" for m in ("get", "post", "put", "patch", "delete", "head", "request")} | \
           {f"requests.Session.{m}" for m in ("get", "post", "put", "patch", "delete", "head", "request")}

ABSOLUTE = re.compile(r"^(/home/|/storage/|/sdcard/|/mnt/|/media/|/Users/|/var/lib/kodi|/root/|[A-Za-z]:\\)")
KODI_FILES = re.compile(r"special://(?:userdata|profile)/keymaps|advancedsettings\.xml|guisettings\.xml|"
                        r"(?<![\w.])sources\.xml", re.IGNORECASE)
OTHER_ADDON = re.compile(r"special://(?:profile|userdata)/addon_data/([\w.\-]+)|special://home/addons/([\w.\-]+)")
DATABASES = re.compile(r"special://database|special://profile/database|"
                       r"(?:MyVideos|MyMusic|Addons|Textures|ViewModes|Epg|TV)\d+\.db", re.IGNORECASE)

KEY_NAMES = ("api_key", "apikey", "api-key", "client_secret", "secret", "token", "password")
KEY_VALUE = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def check(sub: Submission) -> list[dict]:
    """Issue rows for the add-on's own Python, then bundled modules and keys in settings.xml."""
    rows = []
    for rel, tree in sub.own_code().items():
        rows += _file_rows(sub, rel, tree)
    names = MODULE_NAMES | {i[len("script.module."):].lower().replace("-", "_")
                            for i in sub.index.ids(sub.release) if i.startswith("script.module.")}
    for root in sub.bundled_roots():
        package = root.rsplit("/", 1)[-1]
        if package.lower() in names:
            rows.append(finding("py.vendored-module", sub.abs(root), 0, root + "/",
                                f"{root}/ bundles {package}, which the Kodi repo ships as a module add-on; import "
                                f"that instead", HINT))
    return rows + _settings_key_rows(sub)


def _file_rows(sub: Submission, rel: str, tree: ast.Module) -> list[dict]:
    """Rows for one file of the add-on's own code."""
    names = Names(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and
                 any(a.name == "annotations" for a in n.names) for n in tree.body)
    bound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} | \
            {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} | \
            set(names.bound)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    rows = [] if future else _annotation_rows(sub, rel, tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rows += _call_rows(sub, rel, node, names, parents, bound)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for module in modules:
                version = NEWER_MODULES.get(module.split(".")[0])
                if version and not _guarded(node, parents):
                    rows.append(_newer(sub, rel, node, module, version))
        elif isinstance(node, (ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Load):
            rows += _name_rows(sub, rel, node, names, parents, bound)
        elif isinstance(node, ast.AugAssign) and names.qualify(node.target) == "sys.path":
            rows.append(_sys_path(sub, rel, node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            rows += _string_rows(sub, rel, node, parents)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Dict, ast.Call)):
            rows += _key_rows(sub, rel, node)
    return rows


def _annotation_rows(sub: Submission, rel: str, tree: ast.Module) -> list[dict]:
    """Annotations Python 3.8 evaluates at import that use list[...] or X | Y."""
    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = args.posonlyargs + args.args + args.kwonlyargs + [a for a in (args.vararg, args.kwarg) if a]
            annotations += [a.annotation for a in every if a.annotation] + ([node.returns] if node.returns else [])
    for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        annotations += [stmt.annotation for stmt in scope.body if isinstance(stmt, ast.AnnAssign)]
    rows = []
    for annotation in annotations:
        for node in ast.walk(annotation):
            generic = isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and \
                node.value.id in BUILTIN_GENERICS
            union = isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
            if generic or union:
                text = ast.unparse(node)
                rows.append(finding("py.annotations-floor", sub.abs(rel), getattr(node, "lineno", 0), text,
                                    f"The annotation {text} raises TypeError on Python 3.8 when the module loads; "
                                    f"add from __future__ import annotations or use the typing names"))
                break
    return rows


def _guarded(node, parents: dict) -> bool:
    """True inside a try that catches the failure, or under a sys.version_info test."""
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.Try) and child in parent.body:
            for handler in parent.handlers:
                if handler.type is None or GUARD_ERRORS & {n.id for n in ast.walk(handler.type)
                                                           if isinstance(n, ast.Name)}:
                    return True
        if isinstance(parent, ast.If) and "version_info" in ast.dump(parent.test):
            return True
        child, parent = parent, parents.get(parent)
    return False


def _newer(sub: Submission, rel: str, node, what: str, version: str) -> dict:
    """The row for a standard library name newer than Python 3.8."""
    return finding("py.stdlib-floor", sub.abs(rel), node.lineno, what,
                   f"{what} needs Python {version}, and Kodi on this branch can run Python 3.8; guard it or use an "
                   f"older equivalent")


def _name_rows(sub: Submission, rel: str, node, names: Names, parents: dict, bound: set) -> list[dict]:
    """Standard library names and builtins newer than Python 3.8."""
    if isinstance(node, ast.Name):
        version = NEWER_BUILTINS.get(node.id) if node.id not in bound else None
        return [_newer(sub, rel, node, node.id, version)] if version and not _guarded(node, parents) else []
    name = names.qualify(node)
    version = NEWER_NAMES.get(name or "")
    return [_newer(sub, rel, node, name or "", version)] if version and not _guarded(node, parents) else []


def _sys_path(sub: Submission, rel: str, node) -> dict:
    """The row for a change to sys.path."""
    return finding("py.sys-path", sub.abs(rel), node.lineno, "sys.path",
                   "Changing sys.path makes imports depend on the order add-ons load; import through "
                   "resources.lib or a module add-on")


def _enclosing(node, parents: dict):
    """Yield (child, parent) pairs up from the node to its function, class or module."""
    child, parent = node, parents.get(node)
    while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                                                         ast.ClassDef)):
        yield child, parent
        child, parent = parent, parents.get(parent)


def _abort_test(test) -> bool:
    """True when a condition holds only once Kodi has asked the add-on to stop."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return any(_abort_test(value) for value in test.values)
    return isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and \
        test.func.attr in ("waitForAbort", "abortRequested")


def _after_abort(node, parents: dict) -> bool:
    """True when the node runs only after an abort check returned True."""
    return any(isinstance(parent, ast.If) and child in parent.body and _abort_test(parent.test)
               for child, parent in _enclosing(node, parents))


def _iterations(node, parents: dict) -> float | None:
    """Iterations of enclosing loops: constant ranges multiplied, else inf; None outside loops."""
    count, looped = 1.0, False
    for _, parent in _enclosing(node, parents):
        if isinstance(parent, ast.While):
            return float("inf")
        if isinstance(parent, (ast.For, ast.AsyncFor)):
            looped = True
            bounds = parent.iter.args if isinstance(parent.iter, ast.Call) and \
                isinstance(parent.iter.func, ast.Name) and parent.iter.func.id == "range" else None
            values = [_number(arg) for arg in bounds or []]
            if not bounds or any(v is None or v != int(v) for v in values):
                return float("inf")
            count *= len(range(*(int(v) for v in values if v is not None)))
    return count if looped else None


def _number(node) -> float | None:
    """The value of a number constant, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _main_block(node, parents: dict) -> bool:
    """True under an `if __name__ == "__main__":` test."""
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.If) and "__main__" in ast.dump(parent.test):
            return True
        parent = parents.get(parent)
    return False


def _call_rows(sub: Submission, rel: str, node: ast.Call, names: Names, parents: dict, bound: set) -> list[dict]:
    """Rows for one call: newer features, sleeps, prints, sys.path, own ids, timeouts, strptime."""
    called = names.call(node)
    path, line, rows = sub.abs(rel), node.lineno, []
    keywords = {k.arg for k in node.keywords}
    method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if method in NEWER_METHODS and not _guarded(node, parents):
        rows.append(_newer(sub, rel, node, f".{method}()", NEWER_METHODS[method]))
    if isinstance(node.func, ast.Name) and node.func.id == "zip" and "zip" not in bound and "strict" in keywords \
            and not _guarded(node, parents):
        rows.append(_newer(sub, rel, node, "zip(strict=...)", "3.10"))
    if isinstance(node.func, ast.Name) and node.func.id in ("isinstance", "issubclass") and \
            node.func.id not in bound and len(node.args) > 1 and isinstance(node.args[1], ast.BinOp) and \
            isinstance(node.args[1].op, ast.BitOr):
        text = ast.unparse(node.args[1])
        rows.append(finding("py.annotations-floor", path, line, text,
                            f"{text} in {node.func.id}() raises TypeError on Python 3.8, even with "
                            f"from __future__ import annotations; pass a tuple instead"))
    if called in ("time.sleep", "xbmc.sleep") and not _after_abort(node, parents):
        value = _number(node.args[0]) if node.args else None
        seconds = None if value is None else value / 1000 if called == "xbmc.sleep" else value
        runs = _iterations(node, parents)
        if runs is not None and (runs == float("inf") or (seconds is not None and runs * seconds >= 1)):
            rows.append(finding("py.sleep-loop", path, line, called,
                                f"{called} in a loop does not wake when Kodi asks the add-on to stop; use "
                                f"xbmc.Monitor().waitForAbort() and break when it returns True"))
        elif runs is None and seconds is not None and seconds >= 1:
            rows.append(finding("py.sleep-loop", path, line, called,
                                f"{called} blocks without seeing Kodi's abort; xbmc.Monitor().waitForAbort() "
                                f"returns early when Kodi stops", HINT))
    if isinstance(node.func, ast.Name) and node.func.id == "print" and "print" not in bound and \
            not _main_block(node, parents):
        target = next((k.value for k in node.keywords if k.arg == "file"), None)
        if target is None or names.qualify(target) == "sys.stdout":
            rows.append(finding("py.print", path, line, "print",
                                "print() writes to the Kodi log at debug level, one entry per write; use xbmc.log"))
    if called in ("sys.path.append", "sys.path.insert", "sys.path.extend", "site.addsitedir"):
        rows.append(_sys_path(sub, rel, node))
    if called == "xbmcaddon.Addon":
        given = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "id"), None)
        if isinstance(given, ast.Constant) and given.value == sub.addon_id:
            rows.append(finding("py.addon-own-id", path, line, sub.addon_id,
                                "xbmcaddon.Addon() finds its own id; the id is needed only when the code runs "
                                "through RunScript by path", HINT))
    if (called in REQUESTS and "timeout" not in keywords and None not in keywords) or \
            (called == "urllib.request.urlopen" and "timeout" not in keywords and len(node.args) < 3):
        rows.append(finding("py.requests-timeout", path, line, called,
                            f"{called} without a timeout can hang the add-on, and Kodi's shutdown with it, on a "
                            f"server that stops answering", HINT))
    if called == "datetime.datetime.strptime":
        rows.append(finding("py.strptime", path, line, "strptime",
                            "datetime.strptime can raise TypeError after its first use in a Kodi session; use "
                            "datetime(*time.strptime(text, format)[:6]) or fromisoformat", HINT))
    return rows


def _string_rows(sub: Submission, rel: str, node: ast.Constant, parents: dict) -> list[dict]:
    """Absolute paths, Kodi's files and databases, and other add-ons' files, in a string literal."""
    text, path, line, rows = str(node.value), sub.abs(rel), node.lineno, []
    parent = parents.get(node)
    compared = isinstance(parent, ast.Compare) or (
        isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and
        parent.func.attr in ("startswith", "endswith", "find", "index", "count"))
    if ABSOLUTE.match(text) and not compared:
        rows.append(finding("py.absolute-path", path, line, text[:60],
                            f"{text[:60]} is a path on one machine; build paths from special:// with "
                            f"xbmcvfs.translatePath"))
    found = KODI_FILES.search(text)
    other = next((m for m in OTHER_ADDON.finditer(text) if (m.group(1) or m.group(2)) != sub.addon_id), None)
    database = DATABASES.search(text)
    if found or other:
        target = found.group(0) if found else other.group(0) if other else ""
        rows.append(finding("py.kodi-files", path, line, target,
                            f"{target} belongs to Kodi or another add-on; an add-on writes only its own "
                            f"addon_data"))
    elif database:
        target = database.group(0)
        rows.append(finding("py.kodi-files", path, line, target,
                            f"{target} is Kodi's database; reading it directly breaks on MySQL setups and schema "
                            f"changes, JSON-RPC does not", HINT))
    return rows


def _key_name(name: str | None) -> bool:
    """True when a name says it holds a key, secret, token or password."""
    if not name:
        return False
    return any(word in name.lower() for word in KEY_NAMES)


def _key_value(node) -> str | None:
    """A literal that looks like a key: 16 or more key characters, not a placeholder."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return None
    return node.value if _looks_like_key(node.value) else None


def _looks_like_key(value: str) -> bool:
    """True for 16 or more key characters that are not a placeholder."""
    lowered = value.lower()
    return bool(KEY_VALUE.match(value)) and len(set(value)) > 1 and \
        not any(word in lowered for word in ("placeholder", "your_", "xxx"))


def _key_rows(sub: Submission, rel: str, node) -> list[dict]:
    """A key-shaped literal assigned to a name, dict key or keyword that says it holds a secret."""
    pairs = []
    if isinstance(node, ast.Assign):
        pairs = [(t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else None, node.value)
                 for t in node.targets]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
        pairs = [(target.id if isinstance(target, ast.Name) else getattr(target, "attr", None), node.value)]
    elif isinstance(node, ast.Dict):
        pairs = [(k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None, v)
                 for k, v in zip(node.keys, node.values)]
    elif isinstance(node, ast.Call):
        pairs = [(k.arg, k.value) for k in node.keywords]
    return [finding("py.plaintext-key", sub.abs(rel), node.lineno, name or "",
                    f"{name} is written in plain text; obfuscate it, as Kodi repo reviewers ask")
            for name, value in pairs if _key_name(name) and _key_value(value)]


def _settings_key_rows(sub: Submission) -> list[dict]:
    """Key-shaped defaults of settings whose id says they hold a secret."""
    rel = "resources/settings.xml"
    if rel not in sub.files:
        return []
    try:
        root = ET.parse(sub.abs(rel), PARSER).getroot()
    except (OSError, ET.XMLSyntaxError):
        return []
    rows = []
    for node in root.iter("setting"):
        setting = node.get("id") or ""
        default = node.get("default") or (node.findtext("default") or "")
        if _key_name(setting) and _looks_like_key(default.strip()):
            rows.append(finding("py.plaintext-key", sub.abs(rel), node.sourceline or 0, setting,
                                f"The default of {setting} is a key in plain text; obfuscate it, as Kodi repo "
                                f"reviewers ask"))
    return rows
