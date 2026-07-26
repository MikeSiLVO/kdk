# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Constants now resolve; bare names in whitelisted nodes and attributes were left untouched.
- `validate --json` exits non-zero when errors are found.
- Line-ending and BOM errors now count toward the summary and the exit code.
- A check that crashes reports an error instead of passing silently.
- Script and service add-ons no longer always resolve to Omega.

### Added

- `kodi_release` setting to override the detected Kodi release.

### Changed

- Kodi reference snapshots are committed rather than fetched at build time, so a source checkout validates correctly.
- Engine progress now prints during `validate`; it was silent regardless of `--debug`.

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
