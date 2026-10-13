"""The `--json` output of `kdk validate` (kdk-only, no editor counterpart)."""

import json
import os
import subprocess
import sys
from pathlib import Path

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
