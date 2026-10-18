# kdk

Standalone Kodi skin validation tool. CLI and GUI.

It runs the checks of the [KodiDevKit](https://github.com/MikeSiLVO/KodiDevKit) Sublime Text plugin,
and its [validation guide](https://github.com/MikeSiLVO/KodiDevKit/blob/main/docs/validation.md)
lists what each one reports.

## Install

### Pre-built binaries

Each release ships two binaries per OS: a CLI build and a GUI build. Both
contain the same code; the GUI build runs without a console window, so
double-clicking it doesn't open a terminal. No Python install needed.

Download them from the [Releases page](https://github.com/MikeSiLVO/kdk/releases).
`<version>` is the release tag, such as `v3.0.1`:

- **Windows (x86_64)**: `kdk-gui-<version>-windows-x86_64.exe` and
  `kdk-cli-<version>-windows-x86_64.exe`.
- **macOS (Apple Silicon)**: `kdk-gui-<version>-macos-arm64.zip` and
  `kdk-cli-<version>-macos-arm64.zip`. The binaries are not notarized, so macOS
  blocks the first launch; allow it with Open Anyway under System Settings >
  Privacy & Security.
- **Linux (x86_64)**: `kdk-gui-<version>-linux-x86_64.tar.gz` and
  `kdk-cli-<version>-linux-x86_64.tar.gz`. Extract with `tar -xzf`, then run the
  file inside.

### From PyPI

```bash
pip install kdk            # CLI
pip install "kdk[gui]"     # CLI and GUI
```

Requires Python 3.10+. The CLI needs only `lxml` and `rich`; the GUI adds PySide6.

On Linux the GUI needs a few system libraries that most desktop installs
already have. On Debian and Ubuntu they are `libegl1`, `libxkbcommon0`,
`libdbus-1-3` and `libxcb-cursor0`.

### From source

```bash
git clone https://github.com/MikeSiLVO/kdk.git
cd kdk
pip install -e .           # or -e ".[gui]" for the GUI
```

### Building a local binary

```bash
python make_binaries.py
```

It installs PyInstaller and the GUI dependencies on first run, then writes two
binaries to `dist/`:

- `kdk` (or `kdk.exe`): the CLI build.
- `kdk-gui` (or `kdk-gui.exe`): the GUI build.

The release binaries are built with the same script.

## Usage

```bash
kdk-gui                        # Launch the GUI
kdk validate                   # Validate the current directory
kdk validate /path/to/skin     # Summary, then pick a category to read
kdk validate --list            # Print every issue instead of the picker
kdk validate --quiet           # Summary only
kdk validate --report          # Also save a text report in Downloads
kdk validate -o report.txt     # Save the text report to this path
```

On a terminal `validate` ends with a category picker. Redirected or piped it
prints every issue instead, so CI logs are complete. The summary names the Kodi
release checked and anything that weakened the run, such as a `kodi_path`
without Kodi's data in it.

`kdk issues` shows the last run's findings again without validating:

```bash
kdk issues                     # Every issue from the last run
kdk issues --browse            # Pick a category
kdk issues --summary           # Append the per-category summary
```

Every finding carries a `rule` id, such as `fonts.undefined`, and a `subject`, the name it is
about, such as the font name or the image path as written. `kdk rules` lists every id with what it
reports, and `kdk rules --json` adds the check each belongs to. An id never changes once released.

Both commands take these:

- `--severity error` or `--severity warning`: that severity only.
- `--category <text>`: categories whose name contains the text, such as `fonts`.
- `--show-include-warnings`: also list warnings from include content, hidden by
  default. Errors from include content are always listed.
- `--json`: machine-readable output. With `validate -o` it goes to that file.
- `--strict`, `--exit-zero` and `--github`, described below.
- `--debug`: engine logging on stderr.

`validate` also takes `--kodi-path`, `--release` and `--language`, which override
the `kodi_path`, `kodi_release` and `language` [settings](#configuration), and
`--isolated`.

Exit code is `1` if any errors are found, `2` when kdk could not finish the run,
and `0` otherwise. Add `--strict` to fail on warnings too:

```bash
kdk validate --strict .
```

`--exit-zero` gives `0` for any finished run, so a non-zero code only ever means
kdk failed. With `--json`, a failed run prints `format_version`, `kdk_version` and
`error` in place of the results.

## Comparing two runs

`kdk compare <base> <head>` lists what head adds, mutes or fixes against base. Each side is a skin
folder or a run saved with `kdk validate --json -o`. Given only a head, every finding of the new
skin is new.

```bash
kdk compare old/skin.test new/skin.test
kdk compare --json -o diff.json base.json new/skin.test
```

Findings match on rule, file and subject, so one that only moves lines is neither new nor fixed.
A finding repeated across language files is one row, with `count`, `files` and the `lines` that
go with them. A finding muted on head that is new, or was not muted on base, is listed as `muted`
with the comment's reason, and never counts as new.

Exit code is `1` when head adds a finding, `2` when kdk could not finish, and `0` otherwise;
`--exit-zero` gives `0` for any finished run. Runs from different kdk versions or Kodi releases
are not compared.

## GitHub Actions

`--github` also prints each issue as a workflow command, so it shows up as an
inline annotation on the commit and on the pull request diff:

```yaml
      - run: pip install kdk
      - run: kdk validate --strict --github .
```

Annotation paths are relative to `GITHUB_WORKSPACE`, so a skin in a subdirectory
still points at the right file.

Run it on `ubuntu-latest`. Windows runners check text files out with CRLF line
endings, which File Integrity reports as errors.

## Silencing a finding

An XML comment mutes findings the skin has already judged, the way a
`# type: ignore` does in Python. `kdk-ignore-file` covers the whole file it sits
in and `kdk-ignore` a single line. Text after a `;` is the reason, shown to
anyone reading the results:

```xml
<!-- kdk-ignore-file: labels; debug overlay -->   whole file, Labels only
<!-- kdk-ignore: labels, images; add-on name -->   one line, Labels and Images
<!-- kdk-ignore: labels -->                        one line, Labels, no reason
<!-- kdk-ignore -->                                one line, every check
```

A file-wide comment needs both the checks it covers and a reason. If either is
missing, it mutes nothing and is reported as a warning.

A one-line comment sharing its line with markup applies to that line; one
sitting on its own line applies to the line below it:

```xml
<label>SiLVO</label> <!-- kdk-ignore: labels; theme name -->

<!-- kdk-ignore: labels; theme name -->
<label>Superman</label>
```

Comments are read in the XML files of the skin's resolution folders, such as
`xml` or `1080i`. A finding in any other file, `addon.xml` and the language
files included, cannot be muted.

Category names are the ones in the summary (`Labels`, `Fonts`, `Images`, `IDs`,
`Variables`, `Maps`, `Includes`, `XML Validation`, `File Integrity`, `Kodi Repo`),
matched without regard to case, spaces, or hyphens. A name that matches no check
is reported as a warning; the names it got right still apply.

A muted finding is not dropped. `--json` keeps it with a `muted` field holding the
comment's line and reason, and the saved report lists it with the same. The
terminal list, `--github` annotations and the exit code leave it out, and the
summary counts it apart.

## Configuration

Settings are loaded in priority order:

1. CLI flags
2. `.kdk.json` in the skin directory
3. User config (OS-native location):
   - Linux: `~/.config/kdk/config.json`
   - macOS: `~/Library/Application Support/kdk/config.json`
   - Windows: `%APPDATA%\kdk\config.json`
4. Built-in defaults

`--isolated` skips both config files, so only CLI flags and the defaults apply.
The GUI saves its Kodi path and editor choice to the user config.

Example config file:

```json
{
    "kodi_path": "/usr/share/kodi",
    "editor": "code"
}
```

| Setting | Default | Effect |
|---------|---------|--------|
| `kodi_path` | `""` | Kodi installation folder. Kodi's core colors and label ids are read from it, and font files the skin does not ship are looked for in it. Empty, or a folder without Kodi's `colors.xml` and `strings.po`, uses the copies bundled for the release checked. An xbmc source checkout works too, and its info names replace the bundled list; `info_source` in `--json` says which was used. A folder that does not exist is reported as an error. |
| `kodi_release` | `""` | Release to check against: `omega` (Kodi 21) or `piers` (Kodi 22). Empty uses the release the skin's `xbmc.gui` import names, or the newest when it names none. A forced release that will not load the skin is reported. An unknown value is reported and ignored. |
| `language` | `"resource.language.en_gb"` | Language of the skin's `strings.po` that label ids are looked up in, as the folder name or its code (`en_gb`). |
| `validation_exclude` | `["shortcuts"]` | Folder or file names XML Validation skips, matched against any part of the path. |
| `editor` | `""` | Editor a double-click in the GUI opens the issue in: `code`, `sublime`, `notepad++`, `vim`, `nano`, `kate` or `gedit`. Empty opens the file in the system's default app, without going to the line. |

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

Based on the original [KodiDevKit](https://github.com/phil65/KodiDevKit) by Philipp Temminghoff (phil65), Copyright (C) 2015-2019, licensed GPL-3.0-or-later.

### Bundled Kodi data

`src/kdk/data/` carries reference data taken from [Kodi](https://github.com/xbmc/xbmc), Copyright (C) Team Kodi, licensed GPL-2.0-or-later and used here under GPL-3.0-or-later:

- `src/kdk/data/kodi/<release>/` - `colors.xml` and `strings.po`, copied verbatim by `scripts/refresh.py`.
- `src/kdk/data/<release>/data.xml` - builtin and boolean-condition names with their descriptions, taken from the Kodi sources and maintained by hand.
- `src/kdk/data/<release>/infonames.json` - the infolabel and boolean-condition names Kodi's parser accepts, taken from the Kodi sources.
- `src/kdk/data/<release>/windows.json` and `obsolete_windows.json` - window names, ids and files, taken from the Kodi sources.
- `src/kdk/data/addon_schema/` - addon.xml schemas copied verbatim from [kodi-addon-checker](https://github.com/xbmc/addon-check), Copyright (C) Team Kodi, licensed GPL-3.0-only.
