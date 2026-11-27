#!/usr/bin/env python3
"""The deterministic fake engine from the task's dependency contract.

It is never imported by the client and never imported by the tests: they run it
as a child process, exactly like the real ``forgel`` executable.

``FORGEL_STUB_LOG`` records the argv it received, ``FORGEL_STUB_SLEEP`` makes it
hang past a client timeout, and ``FORGEL_STUB_STDOUT`` / ``FORGEL_STUB_EXIT``
replay a canned answer with a chosen exit code.
"""

import json
import os
import sys
import time

COMMANDS = {
    "status",
    "tasks",
    "task",
    "say",
    "plan",
    "resume",
    "pause",
    "history",
    "projects",
    "session",
    "accept",
    "rework",
}


def engine():
    return {
        "name": "forgel-stub",
        "version": os.environ.get("FORGEL_STUB_VERSION", "0.1.0"),
    }


ENGINE = engine()


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True), flush=True)
    raise SystemExit(code)


def project_of(args):
    for i, a in enumerate(args):
        if a == "--project" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--project="):
            return a.split("=", 1)[1]
    return None


def main(argv):
    log = os.environ.get("FORGEL_STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            print(json.dumps(argv, ensure_ascii=False), file=f)
    sleep = os.environ.get("FORGEL_STUB_SLEEP")
    if sleep:
        time.sleep(float(sleep))
    if argv and argv[0] in ("--version", "version"):
        emit({"ok": True, "engine": ENGINE})
    canned = os.environ.get("FORGEL_STUB_STDOUT")
    if canned is not None:
        sys.stdout.write(canned)
        sys.stdout.flush()
        raise SystemExit(int(os.environ.get("FORGEL_STUB_EXIT", "0")))
    if not argv or argv == ["--help"]:
        emit({"ok": True, "engine": ENGINE, "commands": sorted(COMMANDS)})
    cmd = argv[0]
    if cmd not in COMMANDS:
        msg = "unsupported command: " + cmd
        emit(
            {
                "ok": False,
                "engine": ENGINE,
                "code": "unsupported_command",
                "unsupported_command": True,
                "error": {"code": "unsupported_command", "description": msg},
                "description": msg,
            },
            2,
        )
    emit(
        {
            "ok": True,
            "engine": ENGINE,
            "command": cmd,
            "args": argv[1:],
            "project": project_of(argv[1:]),
        }
    )


if __name__ == "__main__":
    main(sys.argv[1:])
