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
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .engine import DEFAULT_TIMEOUT, Engine, EngineError
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

# ``accept`` and ``rework`` lean on the engine's ``task`` command, whose first
# positional argument is the action: ``forgel task accept`` and
# ``forgel task reject``.
TASK_ACTIONS = {"accept": "accept", "rework": "reject"}

# The exit code the engine uses for a usage error: an unknown command or an
# unknown action. The client reads it from the return code, never from text.
ENGINE_USAGE_EXIT_CODE = 2

# The structured codes the engine uses for that same usage error. Any other
# code describes a failure of a command the engine knows, not a missing one.
USAGE_CODES = frozenset(
    [
        "unsupported_command",
        "unknown_command",
        "unknown_action",
        "usage",
        "invalid_choice",
    ]
)

# Engine commands that operate on the active project.
PROJECT_SCOPED = frozenset(
    [
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
    ]
)


class _ParserError(Exception):
    """An argument-parse error, raised instead of ``SystemExit``."""


class _ParserExit(Exception):
    """A parser request to stop (help or version), instead of ``SystemExit``."""

    def __init__(self, status: int = 0, message: Optional[str] = None) -> None:
        super().__init__(message or "")
        self.status = status
        self.message = message


class _Parser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose exits become exceptions the caller handles."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _ParserError(message)

    def exit(
        self, status: int = 0, message: Optional[str] = None
    ) -> None:  # type: ignore[override]
        raise _ParserExit(status, message)


def _global_options() -> argparse.ArgumentParser:
    """The parser that declares the global options exactly once.

    Every command parser inherits it through ``parents``, so ``--json``,
    ``--engine`` and ``--timeout`` are accepted before and after the command
    while being declared in a single place. ``SUPPRESS`` keeps a subparser from
    overwriting a value the main parser already stored.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print exactly one JSON object to stdout",
    )
    parser.add_argument(
        "--engine",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="engine executable to run (default: $FORGEL_ENGINE or 'forgel')",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=float,
        default=argparse.SUPPRESS,
        help=(
            "seconds to wait for the engine "
            "(default: $FORGEL_CODE_TIMEOUT or %g)" % DEFAULT_TIMEOUT
        ),
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    global_options = _global_options()
    parser = _Parser(
        prog="forgel-code",
        description=(
            "Thin console client for Forgel over the engine's machine-readable "
            "commands."
        ),
        parents=[global_options],
    )
    parser.add_argument(
        "--version", action="version", version="forgel-code %s" % __version__
    )

    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(
            name,
            help=help_text,
            description=help_text,
            parents=[global_options],
        )

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
    rework.add_argument("remarks", nargs="+", metavar="remarks")

    add("resume", "start or resume work")
    add("pause", "pause work")

    plan = add("plan", "decompose the milestone goal into tasks")
    plan.add_argument("goal", nargs="*", metavar="goal", help="milestone goal")
    plan.add_argument(
        "--milestone",
        metavar="KEY",
        default=None,
        help="milestone key the goal belongs to",
    )

    add("history", "show the short session history")
    add("projects", "list projects")
    add("session", "show the session the engine reports")

    use = add("use", "select the active project")
    use.add_argument("key", metavar="key")

    return parser


def engine_arguments(args: argparse.Namespace, project: Optional[str]) -> List[str]:
    """Translate parsed client arguments into the engine's own argv.

    ``project`` is the project key the engine accepted through
    ``forgel-code use``. While no project has been selected it stays ``None``
    and no ``--project`` argument is passed at all.
    """
    command = args.command

    def with_project(argv: List[str]) -> List[str]:
        if command in PROJECT_SCOPED and project:
            return argv + ["--project", project]
        return argv

    if command == "say":
        # The engine reserves its positional for the project key; the phrase
        # travels in --text so the two cannot consume each other.
        return with_project(["say", "--text", " ".join(args.phrase)])
    if command == "task":
        # The engine reads tasks through its list command; the client picks the
        # requested one out of that machine-readable answer.
        return with_project(["tasks"])
    if command == "accept":
        # The engine's ``task`` command takes the action as its first
        # positional argument: a task is accepted with ``task accept``.
        return with_project(["task", "accept", "--task", args.task_id])
    if command == "rework":
        # Sending a task back is the engine's ``reject`` action; the remarks
        # travel in the engine's ``--notes`` option.
        remarks = " ".join(args.remarks).strip()
        if not remarks:
            raise ValueError("rework needs remarks")
        return with_project(
            ["task", "reject", "--task", args.task_id, "--notes", remarks]
        )
    if command == "plan":
        # The free text is the goal; the milestone is an explicit option.
        argv = ["plan"]
        if args.milestone:
            argv.append(args.milestone)
        goal = " ".join(args.goal).strip()
        if goal:
            argv.extend(["--goal", goal])
        return with_project(argv)
    if command == "use":
        return ["use", args.key]
    return with_project([command])


def _listing_entries(payload: Any) -> List[Any]:
    """The top-level entries of the engine's task listing."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def select_task(payload: Any, task_id: str) -> Dict[str, Any]:
    """Pick the requested task out of the top-level entries of the listing."""
    matches: List[Dict[str, Any]] = []
    for entry in _listing_entries(payload):
        if not isinstance(entry, dict):
            continue
        for key in TASK_ID_KEYS:
            if key in entry and str(entry[key]) == task_id:
                matches.append(entry)
                break
    if not matches:
        raise EngineError("task %s is not in the engine's task list" % task_id, 1)
    if len(matches) > 1:
        raise EngineError(
            "task %s is ambiguous: the engine's task list has %d entries with "
            "that id" % (task_id, len(matches)),
            1,
        )
    return matches[0]


def missing_engine_command(command: str, exc: EngineError) -> Optional[str]:
    """Return an explicit report when the engine lacks the action, else ``None``.

    The decision rests on the engine's return code and structured fields, never
    on the human-readable wording of its message, so it is locale-independent.
    A code that describes something other than a usage error means the engine
    knows the command and it failed; that is not a missing command.
    """
    action = TASK_ACTIONS.get(command)
    if action is None:
        return None
    if exc.returncode != ENGINE_USAGE_EXIT_CODE:
        return None
    payload = exc.payload or {}
    if not payload.get("unsupported_command"):
        code = payload.get("code") or payload.get("kind")
        if code is not None and str(code) not in USAGE_CODES:
            return None
    return (
        "forgel-code %s: the engine reports no engine command for this action "
        "(`forgel task %s` is not available: %s)" % (command, action, exc.message)
    )


def _report_failure(
    command: Optional[str],
    project: Optional[str],
    message: str,
    as_json: bool,
    returncode: int,
    engine_error: Optional[Dict[str, Any]] = None,
) -> int:
    print(message, file=sys.stderr)
    if as_json:
        payload: Dict[str, Any] = {
            "command": command,
            "project": project,
            "ok": False,
            "error": message,
        }
        if engine_error is not None:
            payload["engine_error"] = engine_error
        print(json.dumps(payload, ensure_ascii=False))
    return returncode


def resolve_timeout(option: Optional[float]) -> float:
    """Option, then ``$FORGEL_CODE_TIMEOUT``, then the default."""
    if option is not None:
        return option
    raw = os.environ.get("FORGEL_CODE_TIMEOUT")
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            "FORGEL_CODE_TIMEOUT must be a number of seconds, got %r" % raw
        ) from None


def _json_requested(raw: Sequence[str]) -> bool:
    """Whether the caller asked for JSON even when parsing did not get that far.

    Nothing is removed from argv here; this only decides the shape of the
    error report for an argv that failed to parse.
    """
    return "--json" in raw


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
    except _ParserError as exc:
        return _report_failure(None, None, str(exc), _json_requested(raw), 2)
    except _ParserExit as exc:
        if exc.message:
            sys.stdout.write(exc.message)
        return exc.status

    as_json = bool(getattr(args, "json_output", False))
    command = args.command

    session = Session()
    # Only a key the engine accepted is handed back to the engine.
    engine_project = session.project() if session.selected() else None

    try:
        timeout = resolve_timeout(getattr(args, "timeout", None))
    except ValueError as exc:
        return _report_failure(command, engine_project, str(exc), as_json, 2)

    try:
        arguments = engine_arguments(args, engine_project)
    except ValueError as exc:
        return _report_failure(command, engine_project, str(exc), as_json, 2)

    configured = getattr(args, "engine", None)
    binary = configured or os.environ.get("FORGEL_ENGINE") or "forgel"
    engine = Engine(binary, timeout)
    # The project the JSON envelope reports: the key actually handed to the
    # engine, never the client's local session label.
    reported_project = engine_project
    try:
        result = engine.run(arguments)
        if command == "task":
            try:
                result = select_task(result, args.task_id)
            except EngineError as exc:
                # The engine answered; finding the task in its answer failed.
                raise engine.failure(exc.message, exc.returncode) from None
        if command == "use":
            session.save_project(args.key)
            reported_project = args.key
    except EngineError as exc:
        message = missing_engine_command(command, exc) or exc.message
        return _report_failure(
            command,
            engine_project,
            message,
            as_json,
            exc.returncode or 1,
            exc.payload,
        )

    if as_json:
        payload = {
            "command": command,
            "project": reported_project,
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
