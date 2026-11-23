"""Translate a client intent into the engine's own argv.

The one-shot commands and the interactive session share this table, so the two
surfaces can never ask the engine for different things.
"""

from __future__ import annotations

from typing import Any, List, Optional

# Engine commands that operate on the active project.
PROJECT_SCOPED = frozenset(
    [
        "say",
        "status",
        "tasks",
        "task",
        "accept",
        "rework",
        "retry",
        "resume",
        "pause",
        "plan",
        "history",
        "projects",
        "session",
    ]
)

# The action positional the engine's ``task`` command takes for a client action.
TASK_ACTIONS = {"accept": "accept", "rework": "reject", "retry": "retry"}


def _scoped(command: str, argv: List[str], project: Optional[str]) -> List[str]:
    if command in PROJECT_SCOPED and project:
        return argv + ["--project", project]
    return argv


def build(
    command: str,
    project: Optional[str] = None,
    text: Optional[str] = None,
    task_id: Optional[str] = None,
    notes: Optional[str] = None,
    goal: Optional[str] = None,
    milestone: Optional[str] = None,
    key: Optional[str] = None,
) -> List[str]:
    """The engine argv for one client intent.

    Raises ``ValueError`` when the intent is missing something the engine needs.
    """
    if command == "say":
        # The engine reserves its positional for the project key; the phrase
        # travels in --text so the two cannot consume each other.
        return _scoped("say", ["say", "--text", text or ""], project)
    if command == "task":
        # The engine reads tasks through its list command; the client picks the
        # requested one out of that machine-readable answer.
        return _scoped("task", ["tasks"], project)
    if command in ("accept", "retry"):
        return _scoped(
            command,
            ["task", TASK_ACTIONS[command], "--task", str(task_id)],
            project,
        )
    if command == "rework":
        remarks = (notes or "").strip()
        if not remarks:
            raise ValueError("rework needs remarks")
        return _scoped(
            "rework",
            ["task", "reject", "--task", str(task_id), "--notes", remarks],
            project,
        )
    if command == "plan":
        # The free text is the goal; the milestone is an explicit option.
        argv = ["plan"]
        if milestone:
            argv.append(milestone)
        target = (goal or "").strip()
        if target:
            argv.extend(["--goal", target])
        return _scoped("plan", argv, project)
    if command == "use":
        return ["use", str(key)]
    return _scoped(command, [command], project)


def listing_entries(payload: Any) -> List[Any]:
    """The top-level entries of an engine listing answer."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for name in ("tasks", "items", "result"):
            value = payload.get(name)
            if isinstance(value, list):
                return value
    return []
