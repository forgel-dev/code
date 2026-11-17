"""Run the Forgel engine as a separate process and read its JSON answer.

The client never imports the engine. The only channel is
``forgel <command> --json`` executed as a child process whose stdout holds
exactly one JSON object.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Sequence


class EngineError(Exception):
    """The engine failed or answered with something the client cannot read."""

    def __init__(self, message: str, returncode: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.returncode = returncode


def parse_json_object(output: str) -> Dict[str, Any]:
    """Return the single JSON object the engine printed on stdout."""
    text = output.strip()
    if not text:
        raise EngineError("engine printed no output")
    data: Any
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise EngineError("engine output is not a JSON object: %s" % text) from None
        try:
            data, end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            raise EngineError("engine output is not a JSON object: %s" % text) from None
        rest = text[start + end:].strip()
        if rest:
            raise EngineError("engine printed more than one JSON value: %s" % text)
    if not isinstance(data, dict):
        raise EngineError(
            "engine printed a JSON value that is not an object: %s" % text
        )
    return data


class Engine:
    """A handle on the ``forgel`` executable."""

    def __init__(self, binary: str = "forgel") -> None:
        self.binary = binary

    def command(self, arguments: Sequence[str]) -> List[str]:
        """Return the child argv: ``forgel <command> --json``."""
        return [self.binary, *arguments, "--json"]

    def run(self, arguments: Sequence[str]) -> Dict[str, Any]:
        """Run one engine command and return its JSON object."""
        argv = self.command(arguments)
        try:
            completed = subprocess.run(argv, capture_output=True, text=True)
        except FileNotFoundError:
            raise EngineError(
                "engine executable not found: %s" % self.binary, 127
            ) from None
        except OSError as exc:
            raise EngineError("cannot run engine: %s" % exc, 126) from None
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            if not message:
                message = "engine exited with code %d" % completed.returncode
            raise EngineError(message, completed.returncode or 1)
        return parse_json_object(completed.stdout)
