# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `--github` prints an absolute path for a skin outside the workspace instead of a run of `..`.

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
