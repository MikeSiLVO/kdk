"""The GUI's icons, loaded from the PNGs shipped in kdk/data/gui."""

from __future__ import annotations

from functools import cache
from importlib.resources import files

from PySide6.QtGui import QIcon


@cache
def icon(name: str) -> QIcon:
    """Icon from its shipped 16 and 32 px PNGs; empty when neither is found."""
    result = QIcon()
    folder = files("kdk.data").joinpath("gui")
    for suffix in ("", "@2x"):
        path = folder.joinpath(f"{name}{suffix}.png")
        if path.is_file():
            result.addFile(str(path))
    return result
