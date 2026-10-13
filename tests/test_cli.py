"""Exit codes of the kdk command line (kdk-only, no editor counterpart)."""

import json
import os
import subprocess
import sys
from pathlib import Path

from kdk import config

SRC = Path(__file__).resolve().parent.parent / "src"
SKIN = Path(__file__).resolve().parent / "fixtures" / "dirty_skin"


def run(*args, prelude="pass"):
    """Run `kdk` in a subprocess with the arguments, after any setup code; returns its exit code."""
    return _process(*args, prelude=prelude).returncode


def _process(*args, prelude="pass"):
    """Run `kdk` in a subprocess after the setup code; returns the finished process and output."""
    code = f"import sys\n{prelude}\nfrom kdk.__main__ import main\nsys.argv = ['kdk'] + sys.argv[1:]\nsys.exit(main())"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env, check=False)


def test_errors_exit_one_unless_exit_zero():
    """A finished run with errors exits 1, or 0 with --exit-zero."""
    assert run("validate", "--json", str(SKIN)) == 1
    assert run("validate", "--json", "--exit-zero", str(SKIN)) == 0


def test_kdk_failure_exits_two_even_with_exit_zero():
    """A missing folder or a crash inside kdk exits 2, whatever the flags."""
    assert run("validate", "--json", str(SKIN / "missing")) == 2
    assert run("validate", "--json", "--exit-zero", str(SKIN / "missing")) == 2
    crash = "import kdk.core; kdk.core.validate_skin = lambda *a, **k: 1 / 0"
    assert run("validate", "--json", "--exit-zero", str(SKIN), prelude=crash) == 2


def test_isolated_ignores_both_config_files(tmp_path, monkeypatch):
    """Only the defaults and the overrides apply to an isolated run."""
    user = tmp_path / "user.json"
    user.write_text('{"language": "resource.language.de_de"}')
    (tmp_path / ".kdk.json").write_text('{"kodi_release": "omega"}')
    monkeypatch.setattr(config, "_user_config_path", lambda: user)
    shared = config.load_config(str(tmp_path))
    assert (shared["language"], shared["kodi_release"]) == ("resource.language.de_de", "omega")
    isolated = config.load_config(str(tmp_path), {"kodi_path": "/kodi"}, isolated=True)
    assert "kodi_release" not in isolated
    assert (isolated["language"], isolated["kodi_path"]) == (config.DEFAULTS["language"], "/kodi")


def test_release_flag_picks_the_release_checked(tmp_path):
    """The named release is the one checked; a name kdk does not know stops the run."""
    out = tmp_path / "run.json"
    assert run("validate", "--json", "--release", "piers", "-o", str(out), str(SKIN)) == 1
    payload = json.loads(out.read_text())
    assert payload["kodi_release"] == "piers"
    assert not [i for i in payload["categories"].get("Kodi Repo", []) if "will not load" in i["message"]]
    assert run("validate", "--json", "--release", "nexus", str(SKIN)) == 2


def test_every_failure_prints_the_error_object_under_json():
    """A bad flag, a missing folder and a crash each print the error object to stdout."""
    crash = "import kdk.core; kdk.core.validate_skin = lambda *a, **k: 1 / 0"
    for args, prelude, expected in ((("--release", "nope", str(SKIN)), "pass", "invalid choice: 'nope'"),
                                    ((str(SKIN / "missing"),), "pass", "is not a directory"),
                                    ((str(SKIN),), crash, "ZeroDivisionError")):
        proc = _process("validate", "--json", *args, prelude=prelude)
        payload = json.loads(proc.stdout)
        assert proc.returncode == 2
        assert (payload["format_version"], set(payload)) == (1, {"format_version", "kdk_version", "error"})
        assert expected in payload["error"]
