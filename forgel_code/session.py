"""The client session: which project the user is working on right now."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# The client's own default session key. It is a local label, not a project the
# engine is guaranteed to know: the engine resolves ``--project`` as a real
# project id/prefix/name, so the client never sends this key to the engine.
DEFAULT_PROJECT = "local"


def session_home() -> Path:
    """Directory holding the client session file."""
    override = os.environ.get("FORGEL_CODE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "forgel-code"


class Session:
    """A tiny key/value store with the active project key.

    A project only counts as selected once ``forgel-code use <key>`` has handed
    the key to the engine and the engine accepted it. Until then the client
    leaves the project choice to the engine's own active project.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else session_home() / "session.json"

    def load(self) -> Dict[str, Any]:
        default: Dict[str, Any] = {"project": DEFAULT_PROJECT, "selected": False}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        if not isinstance(data, dict) or data.get("selected") is not True:
            return default
        project = data.get("project")
        if not isinstance(project, str) or not project:
            return default
        return {"project": project, "selected": True}

    def project(self) -> str:
        return self.load()["project"]

    def selected(self) -> bool:
        return bool(self.load()["selected"])

    def save_project(self, key: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"project": key, "selected": True}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
