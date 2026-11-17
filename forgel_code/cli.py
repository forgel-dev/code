"""``forgel-code`` command line entry point.

Every command is a thin wrapper over an existing engine command invoked as
``forgel <command> --json``. The client never imports the engine and never
invents behaviour the engine does not provide.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .engine import Engine, EngineError
from .render import render_human
from .session import Session

# Pareto scope items the engine has no command for yet. The client says so
# instead of inventing behaviour.
UNSUPPORTED = {
    "accept": (
        "the engine has no command to accept a task yet; "
        "nothing was sent to the engine"
    ),
    "rework": (
        "the engine has no command to send a task back for rework with remarks "
        "yet; nothing was sent to the engine"
    ),
}

# Commands from the Pareto scope, in help order.
COMMANDS = [
    "say",
    "status",
    "tasks",
    "task",
    "accept",
    "rework",
    "resume",
    "pause",
    "plan",
    "history",
    "projects",
    "session",
    "use",
]

GLOBAL_FLAGS = ("--json", "--engine")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgel-code",
        description=(
            "Thin console client for Forgel over the engine's machine-readable "
            "commands."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="print exactly one JSON object to stdout",
    )
    parser.add_argument(
        "--engine",
        metavar="PATH",
        help="engine executable to run (default: $FORGEL_ENGINE or 'forgel')",
    )

    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, description=help_text)

    say = add("say", "turn a free phrase into a task")
    say.add_argument("phrase", nargs="+", metavar="phrase", help="free phrase")

    add("status", "show the state of the task and the milestone")
    add("tasks", "list tasks")

    task = add("task", "show the state of one task")
    task.add_argument("task_id", metavar="task")

    accept = add("accept", "accept a task (no engine command yet)")
    accept.add_argument("task_id", metavar="task")

    rework = add(
        "rework", "send a task back for rework with remarks (no engine command yet)"
    )
    rework.add_argument("task_id", metavar="task")
    rework.add_argument("remarks", nargs="*", metavar="remark")

    add("resume", "start or resume work")
    add("pause", "pause work")

    plan = add("plan", "decompose the milestone goal into tasks")
    plan.add_argument("goal", nargs="*", metavar="goal")

    add("history", "show the short session history")
    add("projects", "list projects")
    add("session", "show the active client session")

    use = add("use", "select the active project")
    use.add_argument("key", metavar="key")

    return parser


def split_global_flags(argv: Sequence[str]) -> Tuple[List[str], bool, Optional[str]]:
    """Pull ``--json`` and ``--engine`` out of argv wherever they appear.

    Doing it before parsing keeps the flags interchangeable in front of and
    behind the command name. Everything after ``--`` is left untouched.
    """
    rest: List[str] = []
    as_json = False
    engine: Optional[str] = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            rest.extend(argv[index:])
            break
        if token == "--json":
            as_json = True
        elif token == "--engine":
            index += 1
            if index >= len(argv):
                raise ValueError("--engine needs a path")
            engine = argv[index]
        elif token.startswith("--engine="):
            engine = token.split("=", 1)[1]
        else:
            rest.append(token)
        index += 1
    return rest, as_json, engine


def engine_arguments(args: argparse.Namespace) -> List[str]:
    """Translate parsed client arguments into engine argv."""
    command = args.command
    if command == "say":
        return ["say", " ".join(args.phrase)]
    if command == "task":
        return ["task", args.task_id]
    if command == "use":
        return ["use", args.key]
    if command == "plan":
        goal = " ".join(args.goal).strip()
        return ["plan", goal] if goal else ["plan"]
    return [command]


def _report_failure(
    command: str, project: str, message: str, as_json: bool, returncode: int
) -> int:
    print(message, file=sys.stderr)
    if as_json:
        payload: Dict[str, Any] = {
            "command": command,
            "project": project,
            "ok": False,
            "error": message,
        }
        print(json.dumps(payload, ensure_ascii=False))
    return returncode


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        rest, as_json, engine_path = split_global_flags(raw)
    except ValueError as exc:
        parser.error(str(exc))
    args = parser.parse_args(rest)

    session = Session()
    project = session.project()
    command = args.command

    if command in UNSUPPORTED:
        return _report_failure(command, project, UNSUPPORTED[command], as_json, 2)

    engine = Engine(engine_path or os.environ.get("FORGEL_ENGINE") or "forgel")
    try:
        result = engine.run(engine_arguments(args))
    except EngineError as exc:
        return _report_failure(
            command, project, exc.message, as_json, exc.returncode or 1
        )

    if command == "use":
        session.save_project(args.key)
        project = args.key

    if as_json:
        payload = {
            "command": command,
            "project": project,
            "ok": True,
            "result": result,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for line in render_human(result):
            print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
