"""The client session: which project the user is working on right now."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_PROJECT = "local"


def session_home() -> Path:
    """Directory holding the client session file."""
    override = os.environ.get("FORGEL_CODE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "forgel-code"


class Session:
    """A tiny key/value store with the active project key."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else session_home() / "session.json"

    def load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"project": DEFAULT_PROJECT}
        if not isinstance(data, dict):
            return {"project": DEFAULT_PROJECT}
        project = data.get("project")
        if not isinstance(project, str) or not project:
            project = DEFAULT_PROJECT
        return {"project": project}

    def project(self) -> str:
        return self.load()["project"]

    def save_project(self, key: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"project": key}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
