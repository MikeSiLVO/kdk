"""Notice of a newer kdk release, looked up on GitHub at most once a day."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request

from kdk import __version__
from kdk.output.cache import cache_root

LATEST_API = "https://api.github.com/repos/MikeSiLVO/kdk/releases/latest"
RELEASES_PAGE = "https://github.com/MikeSiLVO/kdk/releases/latest"
_DAY = 24 * 60 * 60


def _version_tuple(text: str) -> tuple[int, ...]:
    """Numeric parts of a version such as v3.3.1, up to the first part that is not a number."""
    parts = []
    for part in text.lstrip("v").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def latest_version(timeout: float = 3.0) -> str | None:
    """Latest release without its v, from a cache under a day old or GitHub; caches None too."""
    path = cache_root() / "update.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - cached.get("checked", 0) < _DAY:
            return cached.get("version")
    except (OSError, ValueError, AttributeError):
        pass
    version = None
    try:
        request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                              "User-Agent": "kdk"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            version = json.load(response).get("tag_name", "").lstrip("v") or None
    except Exception:
        pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked": time.time(), "version": version}), encoding="utf-8")
    except OSError:
        pass
    return version


def newer_version(timeout: float = 3.0) -> str | None:
    """The latest release when it is newer than this kdk, else None."""
    latest = latest_version(timeout)
    if latest and _version_tuple(latest) > _version_tuple(__version__):
        return latest
    return None


def upgrade_hint() -> str:
    """How this install updates: the releases page for a binary, pip for the package."""
    if getattr(sys, "frozen", False):
        return f"download it from {RELEASES_PAGE}"
    return "run: pip install -U kdk"


def enabled() -> bool:
    """True unless KDK_NO_UPDATE_CHECK is set or the user config turns update_check off."""
    if os.environ.get("KDK_NO_UPDATE_CHECK"):
        return False
    from kdk.config import load_config
    return bool(load_config().get("update_check", True))


def cli_wanted(args) -> bool:
    """True with the check on at a terminal: no CI, machine output, quiet or isolated run."""
    if any(getattr(args, flag, False) for flag in ("json", "github", "quiet", "isolated")):
        return False
    if os.environ.get("CI") or not sys.stderr.isatty():
        return False
    return enabled()


class Lookup:
    """Lookup of a newer release on a daemon thread, which a run never waits on past wait()."""

    def __init__(self):
        self.version: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """Store the newer release, if any, for wait to return."""
        self.version = newer_version()

    def done(self) -> bool:
        """True once the lookup has ended, found or not."""
        return not self._thread.is_alive()

    def wait(self, seconds: float) -> str | None:
        """Wait up to the seconds given for the lookup; the newer release if found, else None."""
        self._thread.join(seconds)
        return self.version
