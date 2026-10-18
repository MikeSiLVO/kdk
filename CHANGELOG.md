# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `--release` checks against a chosen Kodi release and reports a skin that release will not load.
- `--isolated` ignores the user config and the skin's `.kdk.json`.
- `--exit-zero` exits 0 for any finished run.
- The summary names the Kodi release checked and anything that weakened the run, such as a `kodi_path` without Kodi's data in it.
- `--json` carries `format_version`, `kdk_version`, `kodi_release`, `info_source`, `notices` and a `muted` count, with paths relative to the skin.
- Every finding carries a stable `rule` id and a `subject`, the name it is about. `kdk rules` lists the ids with what each reports.
- `kdk compare` lists the findings a head run adds, mutes or fixes against a base, each side a skin folder or a saved run.
- A Kodi source checkout as `kodi_path` gives the info names its sources define, in place of the bundled list.
- A `kdk-ignore` comment takes a reason after `;`. Muted findings stay in `--json` and the saved report, marked with the comment's line and reason, and the summary counts them apart.
- A Kodi Repo check of `addon.xml`, artwork and language files against the Kodi repo's add-on checker rules, as warnings labeled "Kodi repo".
- File Integrity reports files Kodi repo review rejects, file names that clash on case-insensitive systems, 16-bit PNGs, and a BOM in any text file.
- New checks report:
  - Faults in `<map>` definitions and `$MAP[]` references.
  - Conditions Kodi cannot parse, and info names it does not know.
  - `$VAR` and `$INFO` in tags Kodi reads as written.
  - Constants that are undefined, or used where Kodi does not substitute them.
  - Includes, variables, expressions and constants Kodi drops as later duplicates, and includes with a `<param>` but no `<definition>`.
  - `<include file>` references Kodi cannot open or that lie outside the skin folder, and a Font.xml or Includes.xml named in the wrong case.
  - Undefined ids in every action and navigation tag, checked against the window that uses them.
  - Window names Kodi does not know, custom windows it refuses to load or whose id is outside 1100-1199, and window files the release never loads.
  - A `defaultcontrol` that can never take focus.
  - Read-once tags Kodi drops, and tags that repeat what the control's `<default>` sets.
  - A control nested in a control that is not a group, and a control type not written in lowercase.
  - Bool attributes whose spelling Kodi misreads, unknown viewtypes, and label blocks missing their closing `]`.
  - Undefined label ids in `viewtype`, `fallback`, `idloc` and any `$LOCALIZE`, and skin strings outside 31000-31999 on Kodi 22.
- Images are checked against Textures.xbt and theme bundles. An image found only in the bundle, and a bundle shipped beside its source images, are reported.

### Changed

- `kdk-ignore-file` needs the checks it covers and a reason. Without either it mutes nothing and is reported as a warning, as is a check name that does not exist.
- A run kdk cannot finish exits 2 instead of 1, and under `--json` prints an error object.
- A file that fails to parse is reported instead of skipped. One broken only by faults Kodi's parser tolerates is checked, with the fault still reported.
- An include or expression fault is reported once, at its definition, instead of at every call.
- An unused include is reported on the line that names it.
- A font file whose name does not end in .ttf, one with no extension included, is reported as never loaded, and Fonts.xml is no longer read.
- Label text that is an info Kodi knows, such as `Player.Title`, is reported as a missing `$INFO[]` wrapper.
- BOM and line ending findings say the Kodi repo's review rejects them, and leave the file name to the file field.
- `allowoverlay`, `<system>` in `<coordinates>`, and `borderpercent` are reported as tags Kodi does not read.

### Removed

- `skin_path` from `--json`.

### Fixed

- `--github` prints an absolute path for a skin outside the workspace instead of a run of `..`.
- No longer flagged: `selected` and `usealttexture` on both toggle controls, `focusedcolor` on spincontrol, `background`, `flip` and `infill` on every texture, `textwidth` on labels, grouplist auto width, group `enable` and `allowhiddenfocus` conditions, and a grouplist inside a grouplist.
- Counted as used: a variable named in a SetProperty value, `$VAR` and `$MAP` in any shortcuts file, and an include reached through a `$PARAM`-only name.
- Include params from the shortcuts files and `$PARAM` values forwarded from an outer include call are filled in, and a `$PARAM` font name is checked as each call fills it.
- Include files in subfolders and the generated shortcuts include file are loaded.
- An include whose condition is always false is skipped.
- A tag is called redundant only when every conditional default agrees, and windows that call no include are compared with their defaults too.
- Font duplicates are counted from the first unconditional copy.
- An add-on id of any type prefix is not reported as untranslated text.
- A nested add-on is reported once and its files left out.
- `noop` and `-` are reported as values Kodi does not read as empty, instead of as missing files.
- A skin that imports xbmc.python is checked as a skin.
- Entities declared in a DTD are never expanded.
- Issues come out in the same order on every run.
- A `special://skin/` image path is looked up from the skin folder and a bare one in `media/`, and a wrong path names where Kodi looks for it.
- The GUI lists findings with no line, such as 16-bit PNGs and file-level Kodi repo warnings.
- The GUI can validate again after a run finishes.
- A strings.po syntax error says what is wrong with the line, such as a msgstr that follows no msgid.
- Definitions in a file that a window's include call names count for every check.

## [2.0.0] - 2026-08-03

### Added

- `kdk issues` reads the last run's findings without validating again.
- `kdk-ignore` comments mute findings for a whole file or a single line.
- `--github` prints findings as GitHub Actions annotations, so a red run shows them inline instead of only in the log.
- `--strict` exits non-zero on warnings as well as errors.
- `--severity`, `--category`, `--list` and `-q` narrow or shorten the output.
- `kodi_release` setting to override the detected Kodi release.

### Changed

- `validate` prints the findings themselves, grouped by file. On a terminal it offers a category picker; redirected, it prints all of them.
- Progress is one self-updating line on a terminal and nothing at all when redirected. Per-file detail is behind `--debug`.
- Progress no longer reports issue counts. They were counted before filtering and disagreed with the summary.
- `-o` writes whichever format is selected, including `--json`.
- Kodi reference snapshots are committed rather than fetched at build time, so a source checkout validates correctly.
- `validate` prints its summary to stdout, so redirecting to a file captures it. Progress stays on stderr.
- `validate` reports the Kodi release and reference data it loaded; step-by-step engine detail is behind `--debug`.

### Removed

- PySide6 is no longer a runtime dependency, so a CLI install no longer pulls Qt. Install the GUI with `pip install kdk[gui]`; the GUI binaries are unaffected.

### Fixed

- Font findings name the include that defines the font instead of Fonts.xml.
- A font pulled into several fontsets is reported once rather than once per fontset.
- Font paths in a subdirectory are matched case-insensitively, so a case mismatch reports as one instead of as a missing file.
- Constants now resolve; bare names in whitelisted nodes and attributes were left untouched.
- `validate --json` exits non-zero when errors are found.
- `--debug` is accepted after the subcommand, not only before it.
- Line-ending and BOM errors now count toward the summary and the exit code.
- A check that crashes reports an error instead of passing silently.
- Script and service add-ons no longer always resolve to Omega.

## [1.1.0] - 2026-07-22

### Added

- Boolean conditions are checked against Kodi's parser: a `$VAR` or `$INFO` inside a condition, a misplaced operator, or an undefined `$EXP` is flagged instead of silently evaluating false at runtime.

## [1.0.1] - 2026-06-24

### Fixed

- No more false "control ID not defined" errors on reused includes or in Timers.xml.
- `pulseonselect` no longer flagged as invalid on mover controls.
- Errors in Defaults.xml now show at their source, not on every control that uses the default.

## [1.0.0] - 2026-05-11

Initial release.

- Standalone Kodi skin validator extracted from KodiDevKit.
- CLI (`kdk validate`) with terminal summary, JSON output, and text reports.
- PySide6 GUI with double-click to open issues at the offending line.
- Pre-built binaries for Linux, macOS (Apple Silicon), and Windows.
- Bundled Kodi reference snapshots (Omega + Piers) so it works without a Kodi install.
