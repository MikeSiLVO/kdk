"""Checks of add-on Python against the oldest Python and the practices repo reviewers ask."""

from __future__ import annotations

import ast
import re
from collections import Counter
from typing import NamedTuple

from lxml import etree as ET

from .names import Names
from .releases import PACKAGED_PYTHON, python_level, python_reason
from .rules import ERROR, HINT, finding
from .submission import MODULE_NAMES, PARSER, Submission

BUILTIN_GENERICS = {"list", "dict", "tuple", "set", "frozenset", "type"}

# standard library names newer than Python 3.8, with the version that added them
NEWER_NAMES = {
    "functools.cache": "3.9", "math.lcm": "3.9", "random.randbytes": "3.9", "itertools.pairwise": "3.10",
    "asyncio.TaskGroup": "3.11", "datetime.UTC": "3.11", "itertools.batched": "3.12",
    "warnings.deprecated": "3.13", "copy.replace": "3.13",
}
NEWER_METHODS = {"removeprefix": "3.9", "removesuffix": "3.9", "bit_count": "3.10"}
NEWER_MODULES = {"zoneinfo": "3.9", "graphlib": "3.9", "tomllib": "3.11", "annotationlib": "3.14",
                 "string.templatelib": "3.14", "compression": "3.14", "concurrent.interpreters": "3.14"}
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

LOOPS = (ast.For, ast.AsyncFor, ast.While)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
ABORT_METHODS = ("waitForAbort", "abortRequested")
CLOCKS = {"time.time", "time.monotonic", "time.perf_counter"}
LOOP_WAIT = 3.0
ABORT_POLL = 0.5


class FileScope(NamedTuple):
    """What the sleep check reads from a whole file, and the abort callables of the add-on."""

    tree: ast.Module
    names: Names
    numbers: dict[str, float]
    stops: set[str]


def check(sub: Submission) -> list[dict]:
    """Issue rows for the add-on's own Python, then bundled modules and keys in settings.xml."""
    rows = []
    stops = _abort_callables(sub)
    for rel, tree in sub.own_code().items():
        rows += _file_rows(sub, rel, tree, stops)
    names = MODULE_NAMES | {i[len("script.module."):].lower().replace("-", "_")
                            for i in sub.index.ids(sub.release) if i.startswith("script.module.")}
    for root in sub.bundled_roots():
        package = root.rsplit("/", 1)[-1]
        if package.lower() in names:
            rows.append(finding("py.vendored-module", sub.abs(root), 0, root + "/",
                                f"{root}/ bundles {package}, which the Kodi repo ships as a module add-on; import "
                                f"that instead", HINT))
    return rows + _settings_key_rows(sub)


def _file_rows(sub: Submission, rel: str, tree: ast.Module, stops: set[str]) -> list[dict]:
    """Rows for one file of the add-on's own code."""
    names = Names(tree)
    scope = FileScope(tree, names, _module_numbers(tree), stops)
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
            rows += _call_rows(sub, rel, node, names, parents, bound) + _sleep_rows(sub, rel, node, parents, scope)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for module in modules:
                version = NEWER_MODULES.get(module) or NEWER_MODULES.get(module.split(".")[0])
                if version and not _guarded(node, parents):
                    rows += _newer(sub, rel, node, module, version)
        elif isinstance(node, (ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Load):
            rows += _name_rows(sub, rel, node, names, parents, bound)
        elif isinstance(node, ast.AugAssign) and names.qualify(node.target) == "sys.path":
            rows.append(_sys_path(sub, rel, node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            rows += _string_rows(sub, rel, node, parents)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Dict, ast.Call)):
            rows += _key_rows(sub, rel, node)
    return rows + _kodi_file_rows(sub, rel, tree, names, bound)


def _annotation_rows(sub: Submission, rel: str, tree: ast.Module) -> list[dict]:
    """Annotations evaluated at import that use list[...] or X | Y past the branch's floor."""
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
                break
        else:
            continue
        # an inner union still needs 3.10 when an outer generic came first
        needed = (3, 10) if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
                                for n in ast.walk(annotation)) else (3, 9)
        text, fix = ast.unparse(node), "add from __future__ import annotations or use the typing names"
        rows += _floor_rows(sub, rel, getattr(node, "lineno", 0), "py.annotations-floor", text, needed,
                            f"The annotation {text} raises TypeError on Python 3.8 when the module loads; {fix}",
                            f"The annotation {text}", fix)
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


def _floor_rows(sub: Submission, rel: str, line: int, rule: str, subject: str, needed: tuple[int, int],
                firm: str, what: str, fix: str) -> list[dict]:
    """Row for code needing a Python past the branch's floor, at the level the branch gives it."""
    level = python_level(sub.release, needed)
    if level is None:
        return []
    if sub.release not in PACKAGED_PYTHON:
        return [finding(rule, sub.abs(rel), line, subject, firm)]
    return [finding(rule, sub.abs(rel), line, subject,
                    f"{what} needs Python {needed[0]}.{needed[1]}; {python_reason(sub.release, needed)}; {fix}",
                    HINT if level == "hint" else ERROR)]


def _newer(sub: Submission, rel: str, node, what: str, version: str) -> list[dict]:
    """The row for a standard library feature newer than the branch's Python floor."""
    major, minor = (int(part) for part in version.split("."))
    fix = "guard it or use an older equivalent"
    return _floor_rows(sub, rel, node.lineno, "py.stdlib-floor", what, (major, minor),
                       f"{what} needs Python {version}, and Kodi on this branch can run Python 3.8; {fix}", what, fix)


def _name_rows(sub: Submission, rel: str, node, names: Names, parents: dict, bound: set) -> list[dict]:
    """Standard library names and builtins newer than the branch's Python floor."""
    if isinstance(node, ast.Name) and node.id in NEWER_BUILTINS:
        version = NEWER_BUILTINS[node.id] if node.id not in bound else None
        return _newer(sub, rel, node, node.id, version) if version and not _guarded(node, parents) else []
    name = names.qualify(node)
    version = NEWER_NAMES.get(name or "")
    return _newer(sub, rel, node, name or "", version) if version and not _guarded(node, parents) else []


def _sys_path(sub: Submission, rel: str, node) -> dict:
    """The row for a change to sys.path."""
    return finding("py.sys-path", sub.abs(rel), node.lineno, "sys.path",
                   "Changing sys.path makes imports depend on the order add-ons load; import through "
                   "resources.lib or a module add-on")


def _enclosing(node, parents: dict):
    """Yield (child, parent) pairs up from the node to its function, class or module."""
    child, parent = node, parents.get(node)
    while parent is not None and not isinstance(parent, SCOPES):
        yield child, parent
        child, parent = parent, parents.get(parent)


def _function_of(node, parents: dict):
    """The function definition holding the node, or None at module level."""
    parent = parents.get(node)
    while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        parent = parents.get(parent)
    return parent


def _abort_callables(sub: Submission) -> set[str]:
    """Names the add-on's code binds or passes an uncalled abortRequested or waitForAbort under."""
    found = set()
    for tree in sub.own_code().values():
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg and _abort_method(node.value):
                found.add(node.arg)
            elif isinstance(node, ast.Assign) and _abort_method(node.value):
                found.update(t.id if isinstance(t, ast.Name) else t.attr for t in node.targets
                             if isinstance(t, (ast.Name, ast.Attribute)))
    return found


def _abort_method(node) -> bool:
    """True for a waitForAbort or abortRequested attribute."""
    return isinstance(node, ast.Attribute) and node.attr in ABORT_METHODS


def _abort_test(test, stops: set[str]) -> bool:
    """True when a condition holds only once Kodi has asked the add-on to stop."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return any(_abort_test(value, stops) for value in test.values)
    if not isinstance(test, ast.Call):
        return False
    func = test.func
    return _abort_method(func) or (isinstance(func, ast.Attribute) and func.attr in stops) or \
        (isinstance(func, ast.Name) and func.id in stops)


def _until_abort(test, stops: set[str]) -> bool:
    """True when a loop condition turns false once Kodi has asked the add-on to stop."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return any(_until_abort(value, stops) for value in test.values)
    return isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and _abort_test(test.operand, stops)


def _after_abort(node, parents: dict, stops: set[str]) -> bool:
    """True when the node runs only after an abort check returned True."""
    return any(isinstance(parent, ast.If) and child in parent.body and _abort_test(parent.test, stops)
               for child, parent in _enclosing(node, parents))


def _polls_abort(loop, stops: set[str]) -> bool:
    """True when the loop leaves once an abort check in its own turns returns True."""
    if isinstance(loop, ast.While) and _until_abort(loop.test, stops):
        return True
    stack: list[ast.AST] = list(loop.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.If) and _abort_test(node.test, stops) and \
                any(isinstance(s, (ast.Return, ast.Raise, ast.Break)) for s in node.body):
            return True
        if not isinstance(node, LOOPS + SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    return False


def _range_count(loop, numbers: dict[str, float]) -> int | None:
    """Turns of a for loop over range() with number arguments; None for any other loop."""
    it = loop.iter
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range" and it.args):
        return None
    values = [_value(arg, numbers) for arg in it.args]
    if any(v is None or v != int(v) for v in values) or (len(values) == 3 and values[2] == 0):
        return None
    return len(range(*(int(v) for v in values if v is not None)))


def _time_cap(test, names: Names, numbers: dict[str, float]) -> float | None:
    """Seconds a while condition allows when it compares elapsed clock time with a number."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        caps = [cap for cap in (_time_cap(value, names, numbers) for value in test.values) if cap is not None]
        return min(caps) if caps else None
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Lt, ast.LtE))):
        return None
    left = test.left
    if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Sub) and isinstance(left.left, ast.Call) and \
            names.call(left.left) in CLOCKS:
        return _value(test.comparators[0], numbers)
    return None


def _value(node, numbers: dict[str, float]) -> float | None:
    """A number expression's value, the names given filled in; None for any other expression."""
    if isinstance(node, ast.Name):
        return numbers.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        left, right = _value(node.left, numbers), _value(node.right, numbers)
        if left is None or right is None:
            return None
        return left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) \
            else left * right
    return _number(node)


def _module_numbers(tree: ast.Module) -> dict[str, float]:
    """Module-level names bound once in the file, to a number."""
    stores = Counter(n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
    numbers: dict[str, float] = {}
    for stmt in tree.body:
        target, value = (stmt.targets[0], stmt.value) if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
            else (stmt.target, stmt.value) if isinstance(stmt, ast.AnnAssign) else (None, None)
        if isinstance(target, ast.Name) and stores[target.id] == 1:
            found = _value(value, numbers)
            if found is not None:
                numbers[target.id] = found
    return numbers


def _unpassed_defaults(function, tree: ast.Module) -> dict[str, float]:
    """Number defaults of the function's parameters that no call by its name in the file passes."""
    args = function.args
    positional = args.posonlyargs + args.args
    skip = 1 if positional and positional[0].arg in ("self", "cls") else 0
    pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults)) + \
        [(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None]
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and function.name ==
             (c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None))]
    numbers = {}
    for arg, default in pairs:
        position = positional.index(arg) - skip if arg in positional else len(positional)
        value = _number(default)
        if value is not None and not any(
                len(c.args) > position or any(isinstance(a, ast.Starred) for a in c.args) or
                any(k.arg in (arg.arg, None) for k in c.keywords) for c in calls):
            numbers[arg.arg] = value
    return numbers


def _blocked(node, parents: dict, seconds: float | None, scope: FileScope) -> float | None:
    """Seconds sleep blocks before next abort check; inf when unbounded, None when unknown."""
    total = seconds
    for child, parent in _enclosing(node, parents):
        if not isinstance(parent, LOOPS) or child not in parent.body:
            continue
        if total is not None and total <= ABORT_POLL and _polls_abort(parent, scope.stops):
            return 0.0
        if isinstance(parent, ast.While):
            function = _function_of(parent, parents)
            numbers = {**scope.numbers, **_unpassed_defaults(function, scope.tree)} if function else scope.numbers
            cap = _time_cap(parent.test, scope.names, numbers)
            total = float("inf") if cap is None or total is None else max(cap, total)
        else:
            count = _range_count(parent, scope.numbers)
            if count is None:
                return float("inf")
            total = None if total is None else total * count
    return total


def _sleep_rows(sub: Submission, rel: str, node: ast.Call, parents: dict, scope: FileScope) -> list[dict]:
    """The row for a sleep that blocks a second or more in all without seeing Kodi's abort."""
    called = scope.names.call(node)
    if called not in ("time.sleep", "xbmc.sleep") or _after_abort(node, parents, scope.stops):
        return []
    value = _number(node.args[0]) if node.args else None
    seconds = None if value is None else value / 1000 if called == "xbmc.sleep" else value
    looped = any(isinstance(parent, LOOPS) and child in parent.body for child, parent in _enclosing(node, parents))
    total = _blocked(node, parents, seconds, scope)
    total = None if total is None else round(total, 3)
    if looped and total is not None and total > LOOP_WAIT:
        return [finding("py.sleep-loop", sub.abs(rel), node.lineno, called,
                        f"{called} in a loop does not wake when Kodi asks the add-on to stop; use "
                        f"xbmc.Monitor().waitForAbort() and break when it returns True")]
    if total is not None and total >= 1:
        blocks = f"{called} in this loop blocks up to {total:g} s in all" if looped else f"{called} blocks"
        return [finding("py.sleep-loop", sub.abs(rel), node.lineno, called,
                        f"{blocks} without seeing Kodi's abort; xbmc.Monitor().waitForAbort() returns early "
                        f"when Kodi stops", HINT)]
    return []


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
    """Rows for one call: newer features, prints, sys.path, own ids, timeouts, strptime."""
    called = names.call(node)
    path, line, rows = sub.abs(rel), node.lineno, []
    keywords = {k.arg for k in node.keywords}
    method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if method in NEWER_METHODS and not _guarded(node, parents):
        rows += _newer(sub, rel, node, f".{method}()", NEWER_METHODS[method])
    if isinstance(node.func, ast.Name) and node.func.id == "zip" and "zip" not in bound and "strict" in keywords \
            and not _guarded(node, parents):
        rows += _newer(sub, rel, node, "zip(strict=...)", "3.10")
    if isinstance(node.func, ast.Name) and node.func.id in ("isinstance", "issubclass") and \
            node.func.id not in bound and len(node.args) > 1 and isinstance(node.args[1], ast.BinOp) and \
            isinstance(node.args[1].op, ast.BitOr):
        text, fix = ast.unparse(node.args[1]), "pass a tuple instead"
        rows += _floor_rows(sub, rel, line, "py.annotations-floor", text, (3, 10),
                            f"{text} in {node.func.id}() raises TypeError on Python 3.8, even with "
                            f"from __future__ import annotations; {fix}", f"{text} in {node.func.id}()", fix)
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
        # in a module add-on, Addon() without an id is the add-on importing it
        module = sub.root is not None and any(e.get("point") == "xbmc.python.module"
                                              for e in sub.root.findall("extension"))
        if isinstance(given, ast.Constant) and given.value == sub.addon_id and not module:
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
    """Absolute paths and Kodi's databases named in a string literal."""
    text, path, line, rows = str(node.value), sub.abs(rel), node.lineno, []
    parent = parents.get(node)
    compared = isinstance(parent, ast.Compare) or (
        isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and
        parent.func.attr in ("startswith", "endswith", "find", "index", "count"))
    if ABSOLUTE.match(text) and not compared:
        rows.append(finding("py.absolute-path", path, line, text[:60],
                            f"{text[:60]} is a path on one machine; build paths from special:// with "
                            f"xbmcvfs.translatePath"))
    database = DATABASES.search(text)
    if database:
        rows.append(finding("py.kodi-files", path, line, database.group(0),
                            f"{database.group(0)} is Kodi's database; reading it directly breaks on MySQL setups "
                            f"and schema changes, JSON-RPC does not", HINT))
    return rows


def _kodi_target(sub: Submission, text: str) -> str | None:
    """The Kodi file or other add-on's path a string names, or None."""
    found = KODI_FILES.search(text)
    if found:
        return found.group(0)
    other = next((m for m in OTHER_ADDON.finditer(text) if (m.group(1) or m.group(2)) != sub.addon_id), None)
    return other.group(0) if other else None


def _write_paths(node: ast.Call, names: Names, bound: set) -> list[ast.expr]:
    """The path arguments a call writes, deletes or creates; empty for any other call."""
    called = names.call(node) or ""
    args = node.args
    mode = next((k.value for k in node.keywords if k.arg == "mode"), args[1] if len(args) > 1 else None)
    writes = isinstance(mode, ast.Constant) and isinstance(mode.value, str) and bool(set(mode.value) & set("wax+"))
    if (isinstance(node.func, ast.Name) and node.func.id == "open" and "open" not in bound or called == "io.open") \
            and writes:
        return args[:1]
    if called == "xbmcvfs.File" and writes:
        return args[:1]
    if called in ("xbmcvfs.copy", "xbmcvfs.rename", "os.rename", "os.replace", "shutil.copy", "shutil.copy2",
                  "shutil.copyfile", "shutil.move"):
        return args[1:2]
    if called in ("xbmcvfs.delete", "xbmcvfs.rmdir", "xbmcvfs.mkdir", "xbmcvfs.mkdirs", "os.remove", "os.unlink",
                  "os.mkdir", "os.makedirs", "shutil.rmtree"):
        return args[:1]
    return []


def _kodi_file_rows(sub: Submission, rel: str, tree: ast.Module, names: Names, bound: set) -> list[dict]:
    """Kodi files and other add-ons' paths the code writes, deletes or creates, one row per line."""
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and _kodi_target(sub, n.value)]
    sinks = [path for call in ast.walk(tree) if isinstance(call, ast.Call)
             for path in _write_paths(call, names, bound)]
    rows, lines = [], set()
    for literal in literals:
        if literal.lineno in lines or not sinks or not _reaches(tree, literal, sinks):
            continue
        lines.add(literal.lineno)
        target = _kodi_target(sub, str(literal.value)) or ""
        rows.append(finding("py.kodi-files", sub.abs(rel), literal.lineno, target,
                            f"The add-on changes {target}, which belongs to Kodi or another add-on; an add-on "
                            f"changes only its own addon_data"))
    return rows


def _reaches(tree: ast.Module, literal: ast.Constant, sinks: list[ast.expr]) -> bool:
    """True when the string reaches a write path, directly or through names assigned from it."""
    tainted: set[str] = set()

    def holds(expr) -> bool:
        return any(n is literal or (isinstance(n, ast.Name) and n.id in tainted) or
                   (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and
                    "." + n.attr in tainted) for n in ast.walk(expr))

    for _ in range(4):
        before = len(tainted)
        for node in ast.walk(tree):
            pairs = []
            if isinstance(node, ast.Assign):
                pairs = [(t, node.value) for t in node.targets]
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                pairs = [(node.target, node.value)]
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                pairs = [(node.target, node.iter)]
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                pairs = [(node.optional_vars, node.context_expr)]
            for target, value in pairs:
                if holds(value):
                    for n in ast.walk(target):
                        if isinstance(n, ast.Name):
                            tainted.add(n.id)
                        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                            tainted.add("." + n.attr)
        if len(tainted) == before:
            break
    return any(holds(sink) for sink in sinks)


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
