"""Local PyInstaller wrapper. Run `python make_binaries.py` from the repo root.

Named to avoid shadowing the `build` PyPA package: `build.py` at CWD wins
sys.path resolution against the installed `build` package, breaking
`python -m build` for wheel/sdist creation.

Builds two single-file executables into `dist/`:
  - `kdk`     - console build (CLI).
  - `kdk-gui` - windowed build (no console flash on double-click).

Both bundle the same code; the GUI binary uses `--noconsole` so launching the
GUI doesn't pop a terminal. Mirrors `.github/workflows/release.yml`.

Requires `pip install -e ".[build]"` first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CLI_ENTRY = REPO_ROOT / "src" / "kdk" / "__main__.py"
GUI_ENTRY = REPO_ROOT / "src" / "kdk" / "gui" / "__main__.py"

ICON_PATH = REPO_ROOT / "src" / "kdk" / "data" / "icon.ico"

BASE_ARGS = [
    "--onefile",
    "--collect-data", "kdk",
    "--hidden-import", "lxml.etree",
    "--hidden-import", "lxml._elementpath",
    *(["--icon", str(ICON_PATH)] if ICON_PATH.is_file() else []),
]

# CLI binary excludes the gui package + Qt entirely so it stays small.
CLI_EXTRA = [
    "--exclude-module", "kdk.gui",
    "--exclude-module", "PySide6",
    "--exclude-module", "shiboken6",
]

# GUI binary needs PySide6 - but only Core/Gui/Widgets. PyInstaller's PySide6
# hook follows our imports automatically; we just exclude the heavy unused Qt
# modules so the hook can't pull them in transitively.
GUI_EXTRA = [
    "--exclude-module", "PySide6.QtNetwork",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtMultimediaWidgets",
    "--exclude-module", "PySide6.QtOpenGL",
    "--exclude-module", "PySide6.QtOpenGLWidgets",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtPrintSupport",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuickControls2",
    "--exclude-module", "PySide6.QtQuickWidgets",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtDataVisualization",
    "--exclude-module", "PySide6.QtBluetooth",
    "--exclude-module", "PySide6.QtNfc",
    "--exclude-module", "PySide6.QtSensors",
    "--exclude-module", "PySide6.QtSerialPort",
    "--exclude-module", "PySide6.QtPositioning",
    "--exclude-module", "PySide6.QtLocation",
    "--exclude-module", "PySide6.QtWebChannel",
    "--exclude-module", "PySide6.QtWebEngine",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtWebSockets",
    "--exclude-module", "PySide6.QtWebView",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtHelp",
    "--exclude-module", "PySide6.QtUiTools",
    "--exclude-module", "PySide6.QtSvg",
    "--exclude-module", "PySide6.QtSvgWidgets",
    "--exclude-module", "PySide6.QtXml",
    "--exclude-module", "PySide6.Qt3DCore",
    "--exclude-module", "PySide6.Qt3DRender",
    "--exclude-module", "PySide6.Qt3DInput",
    "--exclude-module", "PySide6.Qt3DLogic",
    "--exclude-module", "PySide6.Qt3DAnimation",
    "--exclude-module", "PySide6.Qt3DExtras",
]


def _retry(fn, attempts: int = 5):
    """Run `fn`; on PermissionError/OSError retry with exponential backoff.

    Windows AV / search-indexer / Explorer hold transient locks on freshly-created
    .exe files; usually clears within a few seconds.
    """
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except (PermissionError, OSError) as e:
            last = e
            time.sleep(0.25 * (2 ** attempt))  # 0.25, 0.5, 1, 2, 4s
    if last:
        raise last


def _wipe(*paths: Path) -> None:
    """Empty/remove each path; tolerant of Windows file locks.

    For files and `.spec` paths: delete with retry, fall back to rename-out-of-way.
    For directories (`build/`, `dist/`): empty the *contents* rather than removing
    the directory itself. The directory entry is sometimes locked even when the
    files inside aren't - emptying still gives PyInstaller a clean slate to work in.
    """
    for p in paths:
        if not p.exists():
            continue

        if p.is_file():
            try:
                _retry(p.unlink)
            except (PermissionError, OSError):
                stale = p.with_name(f"{p.name}.stale.{os.getpid()}")
                try:
                    p.rename(stale)
                    print(f"NOTE: {p.name} locked; renamed to {stale.name}.", file=sys.stderr)
                except Exception:
                    raise
            continue

        # Directory: empty its contents in place.
        problems: list[Path] = []
        for child in p.iterdir():
            try:
                if child.is_dir():
                    _retry(lambda c=child: shutil.rmtree(c))
                else:
                    _retry(child.unlink)
            except (PermissionError, OSError):
                # Try rename-out-of-way for this individual entry so PyInstaller
                # can still write its replacement.
                stale = child.with_name(f"{child.name}.stale.{os.getpid()}")
                try:
                    child.rename(stale)
                except Exception:
                    problems.append(child)

        if problems:
            names = ", ".join(p.name for p in problems)
            print(
                f"WARNING: could not clear these inside {p.name}/: {names}\n"
                f"  Close any running kdk*.exe and Explorer windows in {p}, "
                "or reboot if it persists.",
                file=sys.stderr,
            )


def _run_pyinstaller(name: str, entry: Path, *, windowed: bool, extra: list[str]) -> int:
    args = ["--name", name, *BASE_ARGS, *extra]
    if windowed:
        args.append("--noconsole")
    args.append(str(entry))

    print(f"\n=== Building {name} ({'GUI/windowed' if windowed else 'CLI/console'}) ===")
    return subprocess.run(["pyinstaller", *args], cwd=REPO_ROOT).returncode


def _ensure_build_deps() -> int:
    """Install missing build-time deps. The end-user binary is self-contained;
    only the build host needs these installed."""
    try:
        import PySide6  # noqa: F401
        import lxml  # noqa: F401
        if shutil.which("pyinstaller"):
            return 0
    except ImportError:
        pass

    print("Installing build dependencies...")
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[build]"],
        cwd=REPO_ROOT,
    ).returncode
    if rc != 0:
        print(
            "Failed to install build deps. Try manually:\n"
            f"  {sys.executable} -m pip install -e \".[build]\"",
            file=sys.stderr,
        )
    return rc


def main() -> int:
    rc = _ensure_build_deps()
    if rc != 0:
        return rc

    if shutil.which("pyinstaller") is None:
        print('pyinstaller still not found after install. Aborting.', file=sys.stderr)
        return 1

    # Each PyInstaller invocation creates its own subdir under `build/` and a
    # `<name>.spec` next to this script. Wipe everything so repeated builds
    # don't pick up stale data.
    _wipe(
        REPO_ROOT / "build",
        REPO_ROOT / "dist",
        REPO_ROOT / "kdk.spec",
        REPO_ROOT / "kdk-gui.spec",
    )

    rc = _run_pyinstaller("kdk", CLI_ENTRY, windowed=False, extra=CLI_EXTRA)
    if rc != 0:
        return rc
    rc = _run_pyinstaller("kdk-gui", GUI_ENTRY, windowed=True, extra=GUI_EXTRA)
    if rc != 0:
        return rc

    suffix = ".exe" if sys.platform == "win32" else ""
    print()
    for binary in ("kdk", "kdk-gui"):
        out = REPO_ROOT / "dist" / f"{binary}{suffix}"
        if out.exists():
            size_mb = out.stat().st_size / (1024 * 1024)
            print(f"Built: {out}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
