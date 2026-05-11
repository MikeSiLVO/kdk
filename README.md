# kdk

Standalone Kodi skin validation tool. CLI and GUI.

Originally extracted from the [KodiDevKit](https://github.com/MikeSiLVO/KodiDevKit) Sublime Text plugin to run as a self-contained app.

## Install

### Pre-built binaries (recommended)

Each release ships two binaries per OS: a CLI build and a GUI build. Both
contain the same code; the GUI build just runs without a console window so
double-clicking doesn't pop a terminal.

Download the latest from the [Releases page](https://github.com/MikeSiLVO/kdk/releases):

Filenames follow `kdk-<cli|gui>-<version>-<os>-<arch>` (e.g. `kdk-gui-v0.1.0-windows-x86_64.exe`).

- **Windows (x86_64)**:
  - `kdk-gui-<version>-windows-x86_64.exe`: double-click to launch the GUI.
  - `kdk-cli-<version>-windows-x86_64.exe`: for terminal use.
- **macOS (Apple Silicon)**:
  - `kdk-gui-<version>-macos-arm64.zip`: unzip, right-click then Open the first time (unsigned binary).
  - `kdk-cli-<version>-macos-arm64.zip`: CLI build for terminal use.
- **Linux (x86_64)**:
  - `kdk-gui-<version>-linux-x86_64.tar.gz`: `tar -xzf kdk-gui-*.tar.gz && ./kdk-gui-*`.
  - `kdk-cli-<version>-linux-x86_64.tar.gz`: CLI build (`tar -xzf` then run).

No Python install needed.

### From source

```bash
git clone https://github.com/MikeSiLVO/kdk.git
cd kdk
pip install -e .
```

Requires Python 3.10+. The GUI uses PySide6, installed automatically via pip. On
Linux you may need a few X/wayland system packages (`libxkbcommon`, `libgl1`)
which most desktop installs already have.

### Building a local binary

```bash
python make_binaries.py
```

`make_binaries.py` will install any missing build-time deps (PyInstaller + kdk's
runtime deps) on first run. End users of the resulting `.exe` need nothing
installed.

Produces two binaries in `dist/`:

- `kdk` (or `kdk.exe`): console build for CLI use.
- `kdk-gui` (or `kdk-gui.exe`): windowed build that launches the GUI without a
  console flash on double-click.

Same args as CI, so a local build that works should match the released artifact.

## Usage

```bash
kdk-gui                                   # Launch the GUI
kdk validate /path/to/skin                # Terminal summary + exit code
kdk validate /path/to/skin --report       # Also save text report to ~/Downloads
kdk validate /path/to/skin --json         # Machine-readable JSON
kdk validate /path/to/skin --output X     # Custom report path
kdk validate /path/to/skin --show-include-warnings   # Don't filter include-originated warnings
```

Exit code is `1` if any errors are found, `0` otherwise. Useful for CI on a skin repo.

## Configuration

Settings are loaded in priority order:

1. CLI flags
2. `.kdk.json` in the skin directory
3. User config (OS-native location):
   - Linux: `~/.config/kdk/config.json`
   - macOS: `~/Library/Application Support/kdk/config.json`
   - Windows: `%APPDATA%\kdk\config.json`
4. Built-in defaults

Example config file:

```json
{
    "language": "resource.language.en_gb",
    "editor": "code"
}
```

- `editor`: which editor opens when you double-click an issue in the GUI. Supported: `code`, `sublime`, `notepad++`, `vim`, `nano`, `kate`, `gedit`, or `""` for OS default.

## License

GPL-2.0-only. See [LICENSE](LICENSE).
