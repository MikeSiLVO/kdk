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

Requires Python 3.10+. The CLI needs only `lxml` and `rich`.

The GUI is an extra, so a plain install leaves it out:

```bash
pip install -e ".[gui]"
```

On Linux the GUI may need a few X/wayland system packages (`libxkbcommon`,
`libgl1`) which most desktop installs already have.

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
kdk-gui                        # Launch the GUI
kdk validate                   # Validate the current directory
kdk validate /path/to/skin     # Summary, then pick a category to read
kdk validate --list            # Print every issue instead of the picker
kdk validate --quiet           # Summary only
```

On a terminal `validate` ends with a category picker. Redirected or piped it
prints every issue instead, so CI logs are complete.

Results are cached per skin, so you can read a finished run without paying for
another one:

```bash
kdk issues                     # Every issue from the last run
kdk issues --browse            # Pick a category
kdk issues --category fonts    # One category
kdk issues --severity error    # Errors only
```

Both commands take `--json` for machine-readable output, `--output` to write to
a file, and `--show-include-warnings` to stop filtering warnings that originate
inside include content.

Exit code is `1` if any errors are found, `0` otherwise. Add `--strict` to fail
on warnings too, which is usually what you want in CI:

```bash
kdk validate --strict .
```

## GitHub Actions

`--github` additionally prints each issue as a workflow command, so it shows up
as an inline annotation on the commit and on the pull request diff instead of
being buried in the log:

```yaml
      - run: pip install kdk
      - run: kdk validate --strict --github .
```

Annotation paths are relative to `GITHUB_WORKSPACE`, so a skin in a subdirectory
still points at the right file.

Run it on `ubuntu-latest`. A case-sensitive filesystem is the point: a reference
whose case doesn't match the file on disk works on Windows and macOS and fails on
Linux and Android, so a Windows-only check cannot find that class of bug.

## Silencing a finding

An XML comment mutes findings the skin has already judged, the way a
`# type: ignore` does in Python. Put it at the top of a file to cover the whole
file, or on a line to cover just that line:

```xml
<!-- kdk-ignore-file: labels -->        whole file, Labels only
<!-- kdk-ignore-file -->                whole file, every check
<!-- kdk-ignore: labels, images -->     one line, Labels and Images
<!-- kdk-ignore -->                     one line, every check
```

Both placements work. A directive sharing its line with markup applies to that
markup; one sitting on its own line applies to the line below it:

```xml
<label>SiLVO</label> <!-- kdk-ignore: labels -->

<!-- kdk-ignore: labels -->
<label>Superman</label>
```

Category names are the ones in the summary (`Labels`, `Fonts`, `Images`, `IDs`,
`Variables`, `Includes`, `XML Validation`, `File Integrity`), matched without
regard to case, spaces, or hyphens.

Useful for a debug overlay whose labels are deliberately untranslated:

```xml
<!-- kdk-ignore-file: labels -->
```

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
