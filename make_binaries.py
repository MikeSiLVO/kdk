"""Build the kdk console CLI and windowed GUI into dist/ as single-file PyInstaller binaries."""

# not build.py: at the repo root it shadows the PyPA `build` package and breaks `python -m build`
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
    # Pillow imports numpy whenever the build host has it; kdk never uses it
    "--exclude-module", "numpy",
    *(["--icon", str(ICON_PATH)] if ICON_PATH.is_file() else []),
]

CLI_EXTRA = [
    "--exclude-module", "kdk.gui",
    "--exclude-module", "PySide6",
    "--exclude-module", "shiboken6",
]

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
    """Retry the call with backoff on an OSError, such as a lock Windows holds on a new file."""
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except (PermissionError, OSError) as e:
            last = e
            time.sleep(0.25 * (2 ** attempt))
    if last:
        raise last


def _wipe(*paths: Path) -> None:
    """Wipe files and folder contents, renaming locked ones aside; stuck file raises, rest warn."""
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

        # the folder itself can stay locked when the files in it are not
        problems: list[Path] = []
        for child in p.iterdir():
            try:
                if child.is_dir():
                    _retry(lambda c=child: shutil.rmtree(c))
                else:
                    _retry(child.unlink)
            except (PermissionError, OSError):
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
    """Run PyInstaller for one binary, with or without a console; its exit code."""
    args = ["--name", name, *BASE_ARGS, *extra]
    if windowed:
        args.append("--noconsole")
    args.append(str(entry))

    print(f"\n=== Building {name} ({'GUI/windowed' if windowed else 'CLI/console'}) ===")
    return subprocess.run(["pyinstaller", *args], cwd=REPO_ROOT).returncode


def _ensure_build_deps() -> int:
    """Ensure the build deps and PyInstaller are present, else pip-install them; exit code."""
    try:
        import lzallright  # noqa: F401
        import lxml  # noqa: F401
        import PIL  # noqa: F401
        import PySide6  # noqa: F401
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
    """Install any missing build deps, wipe build/ and dist/, build both binaries; exit code."""
    rc = _ensure_build_deps()
    if rc != 0:
        return rc

    if shutil.which("pyinstaller") is None:
        print('pyinstaller still not found after install. Aborting.', file=sys.stderr)
        return 1

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
