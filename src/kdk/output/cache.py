"""Last-run storage so issues can be reviewed without paying for another validation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("kdk.output.cache")


def _cache_dir() -> Path:
    """OS-native location for cached run results."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "kdk" / "runs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "kdk" / "runs"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kdk" / "runs"


def _cache_file(skin_path: str) -> Path:
    """One slot per skin, named by a hash so two skins never collide."""
    digest = hashlib.sha256(os.path.abspath(skin_path).encode()).hexdigest()[:16]
    return _cache_dir() / f"{digest}.json"


def save(skin_path: str, result: dict, issues: dict) -> None:
    """Store a finished run unfiltered, so `kdk issues` can re-filter without revalidating."""
    path = _cache_file(skin_path)
    payload = {
        "skin_name": result["skin_name"],
        "skin_path": result["skin_path"],
        "timestamp": result["timestamp"],
        "duration": result["duration"],
        "issues": issues,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as e:
        logger.debug("Could not cache run for %s: %s", skin_path, e)


def load(skin_path: str) -> dict | None:
    """Return the last stored run for `skin_path`, or None if there isn't a usable one."""
    path = _cache_file(skin_path)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        logger.debug("Could not read cached run for %s: %s", skin_path, e)
        return None
