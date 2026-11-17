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
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .engine import Engine, EngineError
from .render import render_human
from .session import Session

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

# Keys the engine may use for the identifier of a task in its JSON answer.
TASK_ID_KEYS = ("id", "task_id")


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

    accept = add("accept", "accept a task")
    accept.add_argument("task_id", metavar="task")

    rework = add("rework", "send a task back for rework with remarks")
    rework.add_argument("task_id", metavar="task")
    rework.add_argument("remarks", nargs="+", metavar="remark")

    add("resume", "start or resume work")
    add("pause", "pause work")

    plan = add("plan", "decompose the milestone goal into tasks")
    plan.add_argument(
        "milestone", nargs="?", metavar="milestone", help="milestone key"
    )
    plan.add_argument("goal", nargs="*", metavar="goal", help="milestone goal")

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


def engine_arguments(args: argparse.Namespace, project: Optional[str]) -> List[str]:
    """Translate parsed client arguments into the engine's own argv.

    ``project`` is a project key the engine already accepted through
    ``forgel-code use``; while the user has not picked one it stays ``None`` so
    the engine keeps its own active project and never sees the client's local
    session label.
    """
    command = args.command

    def with_project(argv: List[str]) -> List[str]:
        if project:
            return argv + ["--project", project]
        return argv

    if command == "say":
        return ["say", " ".join(args.phrase)]
    if command == "task":
        # The engine reads tasks through its list command; the client picks the
        # requested one out of that machine-readable answer.
        return ["tasks"]
    if command == "accept":
        return with_project(["task", "accept"]) + ["--task", args.task_id]
    if command == "rework":
        # The engine's ``task`` parser carries the remarks of a rejection in
        # ``--notes``; it has no ``--reason`` option.
        remarks = " ".join(args.remarks).strip()
        if not remarks:
            raise ValueError("rework needs remarks")
        return with_project(["task", "reject"]) + [
            "--task",
            args.task_id,
            "--notes",
            remarks,
        ]
    if command == "plan":
        if not args.milestone:
            return ["plan"]
        argv = ["plan", args.milestone]
        goal = " ".join(args.goal).strip()
        if goal:
            argv.extend(["--goal", goal])
        return argv
    if command == "use":
        return ["use", args.key]
    return [command]


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def select_task(payload: Any, task_id: str) -> Dict[str, Any]:
    """Pick the requested task out of the engine's task listing."""
    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        for key in TASK_ID_KEYS:
            if key in node and str(node[key]) == task_id:
                return node
    raise EngineError("task %s is not in the engine's task list" % task_id, 1)


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
    # The session key names the active project on the client side.
    project = session.project()
    # Only a key the engine accepted is handed back to the engine.
    engine_project = project if session.selected() else None
    command = args.command

    try:
        arguments = engine_arguments(args, engine_project)
    except ValueError as exc:
        parser.error(str(exc))

    engine = Engine(engine_path or os.environ.get("FORGEL_ENGINE") or "forgel")
    try:
        result = engine.run(arguments)
        if command == "task":
            result = select_task(result, args.task_id)
        if command == "use":
            session.save_project(args.key)
            project = args.key
    except EngineError as exc:
        return _report_failure(
            command, project, exc.message, as_json, exc.returncode or 1
        )

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
