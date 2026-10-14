"""The `--json` output of `kdk validate` (kdk-only, no editor counterpart)."""

import json
import os
import subprocess
import sys
from pathlib import Path

from kdk import __version__
from kdk.output.payload import render_json

SRC = Path(__file__).resolve().parent.parent / "src"
SKIN = Path(__file__).resolve().parent / "fixtures" / "dirty_skin"

# rich set to None in sys.modules makes any `import rich` fail
RUN = ("import sys; sys.modules['rich'] = None; "
       "sys.argv = ['kdk', 'validate', '--json'] + sys.argv[1:]; "
       "from kdk.__main__ import main; sys.exit(main())")


def run_json(*args):
    """Run `kdk validate --json` on the dirty fixture with rich unimportable."""
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-c", RUN, str(SKIN), *args],
                          capture_output=True, text=True, env=env, check=False)


def test_json_runs_without_rich():
    """The JSON path never imports the terminal library."""
    proc = run_json()
    assert proc.returncode in (0, 1), proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["errors"] + payload["warnings"] > 0


def test_payload_carries_versions_release_and_notices():
    """A consumer can tell which kdk and format wrote the run, and what weakened it."""
    payload = json.loads(run_json().stdout)
    assert (payload["format_version"], payload["kdk_version"]) == (1, __version__)
    assert payload["kodi_release"] in ("omega", "piers")
    assert payload["info_source"] == "snapshot"
    assert isinstance(payload["notices"], list)


def test_payload_holds_no_absolute_path():
    """Nothing in the output names where the skin sits on disk."""
    proc = run_json()
    assert str(SKIN) not in proc.stdout
    assert "skin_path" not in json.loads(proc.stdout)


def test_paths_are_skin_relative_and_rows_sorted():
    """Every path key is relative to the skin, and rows run by file, then line."""
    root = os.path.join(os.sep, "skins", "skin.test")
    rows = [{"file": os.path.join(root, "16x9", "b.xml"), "line": 3, "message": "x"},
            {"file": os.path.join(root, "16x9", "a.xml"), "line": 9, "message": "y",
             "include_file": os.path.join(root, "16x9", "Includes.xml"),
             "call_file": os.path.join(root, "16x9", "a.xml")},
            {"file": os.path.join(root, "16x9", "a.xml"), "line": 2, "message": "z"}]
    result = {"skin_name": "skin.test", "skin_path": root, "timestamp": "", "duration": 0}
    out = render_json(result, {"Fonts": rows})["categories"]["Fonts"]
    assert [(r["file"], r["line"]) for r in out] == [("16x9/a.xml", 2), ("16x9/a.xml", 9), ("16x9/b.xml", 3)]
    assert (out[1]["include_file"], out[1]["call_file"]) == ("16x9/Includes.xml", "16x9/a.xml")
    assert rows[0]["file"].startswith(root)
