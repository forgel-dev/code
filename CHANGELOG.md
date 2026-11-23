# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Speed up the suite without weakening a test — the expensive duplicated work is gone instead of a scenario: one read-only checkout copy and one prepared installation per scenario group are shared by the tests that only read them, and the bounded-check cases configure a limit below the product default.
- Remove every statement of a suite completion time, duration or runtime bound from the documentation — the README `## Tests` section still says that one documented command runs the whole suite, that the installer situations are covered by a real installation into a throwaway home location with a real detected login shell, and that a run from a source checkout needs only the Python standard library and no network access, but it no longer promises how long such a run takes.

### Fixed

- Remove the PATH block from the profile named by `FORGEL_CODE_PROFILE` — `--uninstall` again cleans the marked block out of the profile the override variable names, in addition to the six standard profile files, so a block left by a completed install or by an install that failed its fresh-shell check no longer survives.
- Point the README install, update and uninstall commands at the current `v0.1.1` release installer — the documented commands no longer fetch the stale install script, all three name one and the same install-script URL, and the guard in `tests/test_readme_install.py` fails the suite when any of them carries an older tag or a divergent install-script URL.

## [0.1.0] - 2026-11-20

### Added

- Declare test dependencies in pyproject.toml — Declare a test extra with pytest in pyproject.toml and emit it from the in-tree build backend.
