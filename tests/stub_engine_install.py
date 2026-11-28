#!/usr/bin/env python3
"""The deterministic fake of the engine's own installer.

``install.sh`` consumes two abilities the engine owns and never reimplements:
it asks which engine version a source provides without installing anything, and
it asks for one version to be installed. Both are served here, exactly as the
dependency contract records them.

Contract:

  forgel-install --source SOURCE --available-version
      Prints the engine version SOURCE provides on stdout and exits 0. It
      installs nothing.

  forgel-install --source SOURCE --install VERSION
      Installs VERSION and exits 0, or prints why on stderr and exits non-zero.

The engine binary the installer writes answers the engine's own version report,
``forgel version --json``, with one JSON object on stdout that carries the
version it runs; every other argument gets the engine's structured
unsupported-command answer and a non-zero exit.

State, so a scenario can force any case:

  FORGEL_STUB_ENGINE_AVAILABLE       version the source provides (default 0.0.0)
  FORGEL_STUB_ENGINE_SOURCES         file of "source version" lines; overrides
  FORGEL_STUB_ENGINE_AVAILABLE_EXIT  exit code of --available-version
  FORGEL_STUB_ENGINE_INSTALL_EXIT    exit code of --install
  FORGEL_STUB_ENGINE_TARGET          path of the engine binary to write
  FORGEL_STUB_ENGINE_LOG             file that records every argv as JSON
"""

from __future__ import annotations

import json
import os
import sys

# The engine's own version report, as the recorded engine contract serves it:
# `forgel version --json` prints one JSON object that carries the version the
# engine runs. Any other argv gets the engine's structured unsupported-command
# answer, so a reader that asks in an undocumented form cannot look healthy.
ENGINE_BINARY = """#!/bin/sh
# Forgel engine written by the stub installer; answers `forgel version --json`.
if [ "$1" = "version" ]; then
    printf '%s\\n' '{report}'
    exit 0
fi
printf '%s\\n' '{unsupported}'
exit 2
"""


def record(argv) -> None:
    path = os.environ.get("FORGEL_STUB_ENGINE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv, ensure_ascii=False) + "\n")


def available(source: str) -> str:
    mapping = os.environ.get("FORGEL_STUB_ENGINE_SOURCES")
    if mapping:
        with open(mapping, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) == 2 and parts[0] == source:
                    return parts[1]
    return os.environ.get("FORGEL_STUB_ENGINE_AVAILABLE", "0.0.0")


def write_engine(version: str) -> int:
    target = os.environ.get("FORGEL_STUB_ENGINE_TARGET")
    if not target:
        print("stub engine installer: FORGEL_STUB_ENGINE_TARGET is unset", file=sys.stderr)
        return 2
    report = json.dumps(
        {"ok": True, "engine": {"name": "forgel", "version": version}},
        sort_keys=True,
    )
    unsupported = json.dumps(
        {
            "ok": False,
            "error": {
                "code": "unsupported_command",
                "message": "unsupported command: " + "$1",
            },
            "description": "unsupported command: " + "$1",
        },
        sort_keys=True,
    )
    body = ENGINE_BINARY.replace("{report}", report).replace(
        "{unsupported}", unsupported
    )
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(target, 0o755)
    return 0


def main(argv) -> int:
    record(argv)
    source = None
    action = None
    version = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--source" and index + 1 < len(argv):
            source = argv[index + 1]
            index += 2
            continue
        if argument.startswith("--source="):
            source = argument.split("=", 1)[1]
            index += 1
            continue
        if argument == "--available-version":
            action = "available"
            index += 1
            continue
        if argument == "--install" and index + 1 < len(argv):
            action = "install"
            version = argv[index + 1]
            index += 2
            continue
        if argument.startswith("--install="):
            action = "install"
            version = argument.split("=", 1)[1]
            index += 1
            continue
        print("stub engine installer: unsupported argument: %s" % argument, file=sys.stderr)
        return 64
    if source is None:
        print("stub engine installer: --source is required", file=sys.stderr)
        return 64
    if action == "available":
        code = int(os.environ.get("FORGEL_STUB_ENGINE_AVAILABLE_EXIT", "0"))
        if code != 0:
            print("stub engine installer: cannot reach %s" % source, file=sys.stderr)
            return code
        print(available(source))
        return 0
    if action == "install":
        code = int(os.environ.get("FORGEL_STUB_ENGINE_INSTALL_EXIT", "0"))
        if code != 0:
            print("stub engine installer: installing %s failed" % version, file=sys.stderr)
            return code
        return write_engine(version)
    print(
        "stub engine installer: expected --available-version or --install",
        file=sys.stderr,
    )
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
