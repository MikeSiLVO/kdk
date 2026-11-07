"""The newer-release notice: when it looks, what it caches and where it stays quiet (kdk-only)."""

import argparse
import io
import json
import time

from kdk import config, update


def _args(**flags):
    """A validate command line with the flags given set and the rest off."""
    names = ("json", "github", "quiet", "isolated")
    return argparse.Namespace(**{name: flags.get(name, False) for name in names})


def _no_network(*_args, **_kwargs):
    """Stand-in for urlopen that fails the test if the lookup reaches GitHub."""
    raise AssertionError("looked up GitHub")


def test_only_a_higher_version_is_newer(monkeypatch):
    """A release is newer only when its numbers are higher than this kdk's."""
    monkeypatch.setattr(update, "__version__", "3.3.1")
    for latest, newer in (("3.3.2", "3.3.2"), ("3.10.0", "3.10.0"), ("3.3.1", None), ("3.2.9", None)):
        monkeypatch.setattr(update, "latest_version", lambda timeout=3.0, v=latest: v)
        assert update.newer_version() == newer
    monkeypatch.setattr(update, "latest_version", lambda timeout=3.0: None)
    assert update.newer_version() is None


def test_a_fresh_cache_answers_without_github(tmp_path, monkeypatch):
    """A lookup under a day old is reused, even when it found nothing."""
    monkeypatch.setattr(update, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(update.urllib.request, "urlopen", _no_network)
    for version in ("3.4.0", None):
        (tmp_path / "update.json").write_text(json.dumps({"checked": time.time(), "version": version}))
        assert update.latest_version() == version


def test_a_stale_cache_looks_again_and_records_it(tmp_path, monkeypatch):
    """A lookup over a day old asks GitHub, strips the v and caches the answer."""
    monkeypatch.setattr(update, "cache_root", lambda: tmp_path)
    (tmp_path / "update.json").write_text(json.dumps({"checked": time.time() - 2 * 86400, "version": "3.3.1"}))
    reply = io.BytesIO(json.dumps({"tag_name": "v3.4.0"}).encode())
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: reply)
    assert update.latest_version() == "3.4.0"
    assert json.loads((tmp_path / "update.json").read_text())["version"] == "3.4.0"


def test_a_failed_lookup_is_quiet_and_waits_a_day(tmp_path, monkeypatch):
    """No network gives no version, and the next run within a day does not look again."""
    monkeypatch.setattr(update, "cache_root", lambda: tmp_path)

    def offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(update.urllib.request, "urlopen", offline)
    assert update.latest_version() is None
    monkeypatch.setattr(update.urllib.request, "urlopen", _no_network)
    assert update.latest_version() is None


def test_the_cli_looks_only_for_a_person_at_a_terminal(monkeypatch):
    """CI, machine output, quiet and isolated runs and a redirected stderr never look."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(update, "enabled", lambda: True)
    monkeypatch.setattr(update.sys.stderr, "isatty", lambda: True, raising=False)
    assert update.cli_wanted(_args())
    for flag in ("json", "github", "quiet", "isolated"):
        assert not update.cli_wanted(_args(**{flag: True}))
    monkeypatch.setenv("CI", "true")
    assert not update.cli_wanted(_args())
    monkeypatch.delenv("CI")
    monkeypatch.setattr(update.sys.stderr, "isatty", lambda: False, raising=False)
    assert not update.cli_wanted(_args())


def test_the_check_can_be_turned_off(tmp_path, monkeypatch):
    """KDK_NO_UPDATE_CHECK or update_check false in the user config turns it off."""
    user = tmp_path / "user.json"
    monkeypatch.setattr(config, "_user_config_path", lambda: user)
    monkeypatch.delenv("KDK_NO_UPDATE_CHECK", raising=False)
    assert update.enabled()
    monkeypatch.setenv("KDK_NO_UPDATE_CHECK", "1")
    assert not update.enabled()
    monkeypatch.delenv("KDK_NO_UPDATE_CHECK")
    user.write_text('{"update_check": false}')
    assert not update.enabled()


def test_the_hint_fits_the_install(monkeypatch):
    """A binary points at the releases page, a package at pip."""
    monkeypatch.setattr(update.sys, "frozen", True, raising=False)
    assert update.RELEASES_PAGE in update.upgrade_hint()
    monkeypatch.setattr(update.sys, "frozen", False, raising=False)
    assert "pip install -U kdk" in update.upgrade_hint()
