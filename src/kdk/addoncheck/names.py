"""Imported names in add-on Python: what a name, attribute chain or call refers to."""

from __future__ import annotations

import ast

# Kodi methods whose result is an instance of another Kodi class
RETURNS = {
    "xbmcgui.ListItem.getVideoInfoTag": "xbmc.InfoTagVideo",
    "xbmcgui.ListItem.getMusicInfoTag": "xbmc.InfoTagMusic",
    "xbmcgui.ListItem.getPictureInfoTag": "xbmc.InfoTagPicture",
    "xbmcgui.ListItem.getGameInfoTag": "xbmc.InfoTagGame",
    "xbmc.Player.getVideoInfoTag": "xbmc.InfoTagVideo",
    "xbmc.Player.getMusicInfoTag": "xbmc.InfoTagMusic",
    "xbmcaddon.Addon.getSettings": "xbmcaddon.Settings",
}


class Names:
    """Names one file binds: imported modules, classes and functions, and instances of classes."""

    def __init__(self, tree: ast.AST):
        # local name, or ".attr" for self.attr, to a dotted name; an instance ends in "()"
        self.bound: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.bound.setdefault(alias.asname or alias.name.split(".")[0],
                                          alias.name if alias.asname else alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    if alias.name != "*":
                        self.bound.setdefault(alias.asname or alias.name, f"{node.module}.{alias.name}")
        # aliases of aliases settle over a few rounds
        for _ in range(3):
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    name = self.qualify(node.value)
                    if not name:
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        key = _key(target)
                        if key:
                            self.bound.setdefault(key, name)

    def qualify(self, node: ast.AST | None) -> str | None:
        """Dotted name of the expression, ending "()" for an instance; None when untraced."""
        if isinstance(node, ast.Name):
            return self.bound.get(node.id)
        if isinstance(node, ast.Attribute):
            key = _key(node)
            if key and key in self.bound:
                return self.bound[key]
            base = self.qualify(node.value)
            if base is None:
                return None
            return f"{base[:-2] if base.endswith('()') else base}.{node.attr}"
        if isinstance(node, ast.Call):
            called = self.qualify(node.func)
            if called in RETURNS:
                return RETURNS[called] + "()"
            return f"{called}()" if called and not called.endswith("()") else None
        return None

    def call(self, node: ast.Call) -> str | None:
        """Dotted name of what a call runs, such as xbmcgui.Dialog.ok; None when untraced."""
        return self.qualify(node.func)


def _key(target: ast.AST) -> str | None:
    """Binding key of a target: the name, or ".attr" for self.attr or cls.attr; None otherwise."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in ("self", "cls"):
        return "." + target.attr
    return None
