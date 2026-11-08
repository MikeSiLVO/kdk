"""Add-on version ordering the Kodi repo tools use: PEP 440 once ~alpha and ~beta lose the ~."""

from __future__ import annotations

from .packaging.version import InvalidVersion, Version


def parse(text: str | None) -> Version | None:
    """The version as PEP 440 orders it, or None when it is missing or not PEP 440."""
    if not text:
        return None
    if "~beta" in text or "~alpha" in text:
        text = text.replace("~", "")
    try:
        return Version(text.lower())
    except InvalidVersion:
        return None
