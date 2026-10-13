"""Exit codes of the kdk command line (kdk-only, no editor counterpart)."""

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
SKIN = Path(__file__).resolve().parent / "fixtures" / "dirty_skin"


def run(*args, prelude="pass"):
    """Run `kdk` in a subprocess with the arguments, after any setup code; returns its exit code."""
    code = f"import sys\n{prelude}\nfrom kdk.__main__ import main\nsys.argv = ['kdk'] + sys.argv[1:]\nsys.exit(main())"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, env=env, check=False).returncode


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
