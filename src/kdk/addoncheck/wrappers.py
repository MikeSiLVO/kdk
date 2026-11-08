"""String lookups in add-on Python: getLocalizedString and the wrappers that pass ids along."""

from __future__ import annotations

import ast
import os

SOURCE_ADDON = "addon"
SOURCE_KODI = "kodi"
SOURCE_BOTH = "both"

_LOOKUP = "getLocalizedString"


def lookup_source(callee):
    """Which strings a direct getLocalizedString call reads, or None for any other call."""
    if callee.rsplit(".", 1)[-1] != _LOOKUP:
        return None
    # xbmc.getLocalizedString reads Kodi's tables; Addon().getLocalizedString only the add-on's
    return SOURCE_KODI if callee in ("xbmc." + _LOOKUP, _LOOKUP) else SOURCE_ADDON


def callee_text(node):
    """Dotted text of a call target such as `self.addon.getLocalizedString`, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append("")
    else:
        return None
    return ".".join(reversed(parts))


def _passes_param(call, param):
    """True when the call's first argument is the param, bare or through int()."""
    if not call.args:
        return False
    arg = call.args[0]
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "int":
        arg = arg.args[0] if arg.args else arg
    return isinstance(arg, ast.Name) and arg.id == param


def _first_param(args, is_method):
    """Name of the first parameter a caller fills, past self or cls; None when there is none."""
    names = [a.arg for a in args.posonlyargs + args.args]
    if is_method and names and names[0] in ("self", "cls"):
        names = names[1:]
    return names[0] if names else None


def _forwarded_calls(body_nodes, param):
    """Callee texts of every call in the body that takes the param as its first argument."""
    found = []
    if not param:
        return found
    for node in body_nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _passes_param(sub, param):
                text = callee_text(sub.func)
                if text:
                    found.append(text)
    return found


def _assigned_calls(value):
    """Callee texts a lambda or bound-method alias forwards to."""
    if isinstance(value, ast.Lambda):
        return _forwarded_calls([value.body], _first_param(value.args, False))
    if isinstance(value, ast.Attribute):
        text = callee_text(value)
        return [text] if text else []
    return []


class FileFacts:
    """What one Python file says about wrappers: its own names, its methods and its imports."""

    def __init__(self, tree):
        self.names = {}
        self.attrs = {}
        self.imports = {}
        self.stars = []
        self._collect(tree, in_class=False)

    def _collect(self, node, in_class):
        """Collect a scope's imports, and its wrappers as names or, in classes, as attrs."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not (child.name.startswith("__") and child.name.endswith("__")):
                    calls = _forwarded_calls(child.body, _first_param(child.args, in_class))
                    if calls:
                        table = self.attrs if in_class else self.names
                        table.setdefault(child.name, []).extend(calls)
                self._collect(child, in_class=False)
            elif isinstance(child, ast.ClassDef):
                self._collect(child, in_class=True)
            elif isinstance(child, ast.Assign):
                calls = _assigned_calls(child.value)
                for target in child.targets if calls else ():
                    if isinstance(target, ast.Name):
                        table = self.attrs if in_class else self.names
                        table.setdefault(target.id, []).extend(calls)
                    elif isinstance(target, ast.Attribute):
                        self.attrs.setdefault(target.attr, []).extend(calls)
            elif isinstance(child, ast.Import):
                for a in child.names:
                    top = a.name.split(".")[0]
                    self.imports[a.asname or top] = (a.name if a.asname else top, 0, None)
            elif isinstance(child, ast.ImportFrom):
                for a in child.names:
                    if a.name == "*":
                        self.stars.append((child.module or "", child.level))
                    else:
                        self.imports[a.asname or a.name] = (child.module or "", child.level, a.name)
            else:
                self._collect(child, in_class)


class Resolver:
    """Wrapper sources across a set of files, resolving each call as Python would from its file."""

    def __init__(self, facts):
        self.facts = facts
        self._by_suffix = {}
        for path in facts:
            parts = os.path.splitext(path.replace("\\", "/"))[0].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                self._by_suffix.setdefault(".".join(parts[i:]), path)
        self.names = {}
        self.attrs = {}
        self._settle()

    def _module_file(self, path, module, level):
        """File a module name imported from the path points at, or None when it is not scanned."""
        if level:
            base = os.path.dirname(path)
            for _ in range(level - 1):
                base = os.path.dirname(base)
            rel = os.path.join(base, *module.split(".")) if module else base
            for candidate in (rel + ".py", os.path.join(rel, "__init__.py")):
                if candidate in self.facts:
                    return candidate
            return None
        return self._by_suffix.get(module)

    def _imported(self, path, local):
        """Where a name imported into the file comes from, as (file or None, name or None)."""
        module, level, real = self.facts[path].imports[local]
        if real is None:
            return self._module_file(path, module, level), None
        sub = self._module_file(path, f"{module}.{real}" if module else real, level)
        if sub:
            return sub, None
        return self._module_file(path, module, level), real

    def source(self, path, callee):
        """Which strings a call written in the file reads, or None when it is no string lookup."""
        direct = lookup_source(callee)
        if direct:
            return direct
        parts = callee.split(".")
        if len(parts) == 1:
            return self._bare(path, parts[0], set())
        facts = self.facts.get(path)
        if len(parts) == 2 and facts and parts[0] in facts.imports:
            target, real = self._imported(path, parts[0])
            if target and real is None:
                return self.names.get((target, parts[1]))
        return self.attrs.get(parts[-1])

    def _bare(self, path, name, seen):
        """Source of a bare name as the file sees it: its own def, an import, or a star import."""
        facts = self.facts.get(path)
        if not facts or path in seen:
            return None
        seen.add(path)
        if name in facts.names:
            return self.names.get((path, name))
        if name in facts.imports:
            target, real = self._imported(path, name)
            return self._bare(target, real, seen) if target and real else None
        for module, level in facts.stars:
            target = self._module_file(path, module, level)
            found = self._bare(target, name, seen) if target else None
            if found:
                return found
        return None

    def _settle(self):
        """Settle every candidate against the others until nothing changes."""
        pending = [(path, name, calls, False) for path, f in self.facts.items()
                   for name, calls in f.names.items()]
        pending += [(path, name, calls, True) for path, f in self.facts.items()
                    for name, calls in f.attrs.items()]
        for _ in range(len(pending) + 1):
            changed = False
            for path, name, calls, is_attr in pending:
                table, key = (self.attrs, name) if is_attr else (self.names, (path, name))
                sources = {self.source(path, callee) for callee in calls} - {None}
                sources.add(table.get(key))
                sources.discard(None)
                source = next(iter(sources)) if len(sources) == 1 else SOURCE_BOTH if sources else None
                if source and table.get(key) != source:
                    table[key] = source
                    changed = True
            if not changed:
                break
