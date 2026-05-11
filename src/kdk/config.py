"""Plain-JSON config. Precedence: CLI overrides > `.kdk.json` (skin dir) > `~/.config/kdk/config.json` > defaults."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("kdk.config")


def _user_config_path() -> Path:
    """OS-native location for the user config file."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "kdk" / "config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kdk" / "config.json"
    return Path.home() / ".config" / "kdk" / "config.json"

DEFAULTS = {
    "language": "resource.language.en_gb",
    "language_folders": ["resource.language.en_gb"],
    "kodi_path": "",
    "debug_mode": False,
    # Editor for "open at line" - one of: code, sublime, notepad++, vim, nano, kate, gedit
    # or empty string for OS default (no line number support)
    "editor": "",
}

# {file} and {line} are substituted at call time. Sublime is handled specially
# (see `_open_in_sublime`) because the path:line CLI suffix is unreliable.
EDITOR_PATTERNS = {
    "code":       ["code", "--goto", "{file}:{line}"],
    "notepad++":  ["notepad++", "-n{line}", "{file}"],
    "vim":        ["vim", "+{line}", "{file}"],
    "nano":       ["nano", "+{line}", "{file}"],
    "kate":       ["kate", "--line", "{line}", "{file}"],
    "gedit":      ["gedit", "+{line}", "{file}"],
}


def load_config(skin_path: str | None = None, overrides: dict | None = None) -> dict:
    """Merge defaults, OS-native user config, `<skin_path>/.kdk.json`, and `overrides` (in that order)."""
    config = dict(DEFAULTS)

    user_config = _user_config_path()
    if user_config.exists():
        try:
            with open(user_config) as f:
                config.update(json.load(f))
        except Exception as e:
            logger.warning("Failed to load user config %s: %s", user_config, e)

    if skin_path:
        project_config_path = Path(skin_path) / ".kdk.json"
        if project_config_path.exists():
            try:
                with open(project_config_path) as f:
                    config.update(json.load(f))
            except Exception as e:
                logger.warning("Failed to load project config %s: %s", project_config_path, e)

    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})

    return config


class Settings:
    """Dict-like settings wrapper matching the interface expected by libs/."""

    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str):
        return self._data[key]


def detect_editors() -> list[str]:
    """Return list of editors found on PATH or common install locations."""
    import shutil
    import sys

    candidates = [
        ("code", ["code", "code.cmd"]),
        ("sublime", ["subl", "subl.exe", "sublime_text", "sublime_text.exe"]),
        ("notepad++", ["notepad++", "notepad++.exe"]),
        ("kate", ["kate"]),
        ("gedit", ["gedit"]),
        ("vim", ["vim"]),
        ("nano", ["nano"]),
    ]

    # Bundled installs of these editors don't always add themselves to PATH on Windows.
    win_paths = [
        ("code", [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft VS Code\bin\code.cmd"),
        ]),
        ("sublime", [
            os.path.expandvars(r"%PROGRAMFILES%\Sublime Text\subl.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Sublime Text 3\subl.exe"),
            os.path.expandvars(r"%PROGRAMFILES(x86)%\Sublime Text\subl.exe"),
        ]),
        ("notepad++", [
            os.path.expandvars(r"%PROGRAMFILES%\Notepad++\notepad++.exe"),
            os.path.expandvars(r"%PROGRAMFILES(x86)%\Notepad++\notepad++.exe"),
        ]),
    ]

    found = []
    for name, exes in candidates:
        if any(shutil.which(exe) for exe in exes):
            found.append(name)
            continue
        # On Windows, check common install locations
        if sys.platform == "win32":
            for wname, wpaths in win_paths:
                if wname == name and any(os.path.isfile(p) for p in wpaths):
                    found.append(name)
                    break

    return found


EDITOR_DISPLAY_NAMES = {
    "": "System Default",
    "code": "VS Code",
    "sublime": "Sublime Text",
    "notepad++": "Notepad++",
    "vim": "Vim",
    "nano": "Nano",
    "kate": "Kate",
    "gedit": "Gedit",
}


def save_user_config(key: str, value) -> None:
    """Save a single key to the user config file."""
    config_path = _user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing = json.load(f)
        except Exception:
            pass

    existing[key] = value
    with open(config_path, "w") as f:
        json.dump(existing, f, indent=2)


def _resolve_editor_exe(exe_name: str, editor_key: str) -> str | None:
    """Resolve `exe_name` via PATH, falling back to known Windows install paths; `None` means use `exe_name` as-is."""
    import shutil
    import sys

    if shutil.which(exe_name):
        return None

    if sys.platform != "win32":
        return None

    win_exe_map = {
        "code": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft VS Code\bin\code.cmd"),
        ],
        "sublime": [
            os.path.expandvars(r"%PROGRAMFILES%\Sublime Text\subl.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Sublime Text 3\subl.exe"),
        ],
        "notepad++": [
            os.path.expandvars(r"%PROGRAMFILES%\Notepad++\notepad++.exe"),
            os.path.expandvars(r"%PROGRAMFILES(x86)%\Notepad++\notepad++.exe"),
        ],
    }

    for path in win_exe_map.get(editor_key, []):
        if os.path.isfile(path):
            return path

    return None


def _resolve_sublime_exe() -> str | None:
    """Find a Sublime executable.

    Prefer `subl.exe` (the CLI wrapper) over `sublime_text.exe` because the
    wrapper routes args through Sublime's existing-instance IPC. Calling
    `sublime_text.exe` directly on Windows can spawn a new (hidden) instance
    that receives the line jump while the user's visible Sublime stays put -
    making the jump look broken even when it technically worked.
    """
    import shutil
    import sys

    if sys.platform == "win32":
        candidates = [
            r"%PROGRAMFILES%\Sublime Text\subl.exe",
            r"%PROGRAMFILES%\Sublime Text 3\subl.exe",
            r"%PROGRAMFILES(x86)%\Sublime Text\subl.exe",
            r"%PROGRAMFILES%\Sublime Text\sublime_text.exe",
            r"%PROGRAMFILES%\Sublime Text 3\sublime_text.exe",
        ]
        for c in candidates:
            expanded = os.path.expandvars(c)
            if os.path.isfile(expanded):
                return expanded
        return shutil.which("subl") or shutil.which("sublime_text")
    return shutil.which("subl") or shutil.which("sublime_text")


def _open_in_sublime(file_path: str, line: int) -> bool:
    """Open `file_path` at `line` in Sublime via `subl FILE:LINE:COL`.

    The path is normalized to forward slashes - Sublime's path:line:col parser
    is happier with forward-slash paths on Windows even though backslash paths
    are documented to work too.
    """
    import subprocess

    exe = _resolve_sublime_exe()
    if not exe:
        logger.warning("Sublime not found")
        return False

    abs_path = os.path.abspath(file_path).replace("\\", "/")
    arg = f"{abs_path}:{int(line)}:0" if line and line > 0 else abs_path
    try:
        subprocess.Popen([exe, arg])
        return True
    except FileNotFoundError:
        logger.warning("Sublime executable not launchable: %s", exe)
        return False


def open_in_editor(file_path: str, line: int = 1, editor: str = "") -> bool:
    """Open `file_path:line` in `editor`; falls back to OS default if `editor` is empty or missing."""
    import subprocess
    import sys

    editor = editor.strip().lower()

    if editor == "sublime":
        return _open_in_sublime(file_path, line)

    if editor and editor in EDITOR_PATTERNS:
        cmd = [
            part.replace("{file}", file_path).replace("{line}", str(line))
            for part in EDITOR_PATTERNS[editor]
        ]
        exe = _resolve_editor_exe(cmd[0], editor)
        if exe:
            cmd[0] = exe
        try:
            subprocess.Popen(cmd)
            return True
        except FileNotFoundError:
            logger.warning("Editor %r not found, falling back to OS default", editor)

    # OS default opener can't take a line number.
    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
        return True
    except Exception as e:
        logger.warning("Failed to open file: %s", e)
        return False
