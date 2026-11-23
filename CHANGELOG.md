# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Make the whole test suite fit the release audit's two-minute bound without weakening a test — the expensive duplicated work is gone instead of a scenario: one read-only checkout copy and one prepared installation per scenario group are shared by the tests that only read them, and the bounded-check cases configure a one-second limit below the product default. The README `## Tests` section now states the runtime bound and that the documented command runs the whole suite.

### Fixed

- Remove the PATH block from the profile named by `FORGEL_CODE_PROFILE` — `--uninstall` again cleans the marked block out of the profile the override variable names, in addition to the six standard profile files, so a block left by a completed install or by an install that failed its fresh-shell check no longer survives.

## [0.1.0] - 2026-11-20

### Added

- Declare test dependencies in pyproject.toml — Declare a test extra with pytest in pyproject.toml and emit it from the in-tree build backend.
