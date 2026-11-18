"""Run the Forgel engine as a separate process and read its JSON answer.

The client never imports the engine. The only channel is
``forgel <command> --json`` executed as a child process whose stdout holds one
JSON object.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Optional, Sequence

# Seconds to wait for one engine call before giving up. ``--timeout`` and
# ``$FORGEL_CODE_TIMEOUT`` override it.
DEFAULT_TIMEOUT = 600.0

# How much of an unreadable engine answer an error message quotes.
EXCERPT_LIMIT = 300

# Exit code the client uses when the engine did not answer in time.
TIMEOUT_EXIT_CODE = 124


def _format_seconds(value: float) -> str:
    return "%g" % float(value)


def _excerpt(text: str) -> str:
    """A bounded, single-line excerpt of what the engine printed."""
    flat = " ".join(text.split())
    if len(flat) <= EXCERPT_LIMIT:
        return flat
    return flat[:EXCERPT_LIMIT] + "..."


def _structured_message(error: Any) -> str:
    """Render the engine's structured error fields without inventing any."""
    if isinstance(error, str):
        return error.strip()
    if isinstance(error, dict):
        parts = []
        for key in ("code", "kind", "message"):
            if error.get(key) is not None:
                parts.append("%s=%s" % (key, error[key]))
        for key in sorted(error):
            if key in ("code", "kind", "message"):
                continue
            value = error[key]
            if isinstance(value, (str, int, float, bool)) and value != "":
                parts.append("%s=%s" % (key, value))
        if parts:
            return "engine reported " + ", ".join(parts)
        return "engine reported an empty error"
    if error is None:
        return ""
    return json.dumps(error, ensure_ascii=False, sort_keys=True)


class EngineError(Exception):
    """The engine failed or answered with something the client cannot read."""

    def __init__(
        self,
        message: str,
        returncode: int = 1,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.returncode = returncode
        # The engine's own structured error object, when it supplied one.
        self.payload = payload


def parse_json_object(output: str) -> Dict[str, Any]:
    """Return the JSON object the engine printed, wherever it starts.

    The first decodable JSON object in the output wins: a log line that merely
    contains ``{`` must not make the real answer unreadable.
    """
    text = output.strip()
    if not text:
        raise EngineError("engine printed no output")

    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, dict):
        return whole
    if whole is not None:
        raise EngineError(
            "engine printed a JSON value that is not an object: %s" % _excerpt(text)
        )

    decoder = json.JSONDecoder()
    index = text.find("{")
    while index >= 0:
        try:
            candidate, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict):
            return candidate
        index = text.find("{", index + 1)
    raise EngineError(
        "engine printed no JSON object; received: %s" % _excerpt(text)
    )


class Engine:
    """A handle on the ``forgel`` executable."""

    def __init__(self, binary: str = "forgel", timeout: float = DEFAULT_TIMEOUT) -> None:
        self.binary = binary
        self.timeout = float(timeout)

    def command(self, arguments: Sequence[str]) -> list:
        """Return the child argv: ``forgel <command> --json``."""
        return [self.binary, *arguments, "--json"]

    def run(self, arguments: Sequence[str]) -> Dict[str, Any]:
        """Run one engine command and return its JSON object."""
        argv = self.command(arguments)
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise EngineError(
                "engine executable not found: %s" % self.binary, 127
            ) from None
        except subprocess.TimeoutExpired:
            raise EngineError(
                "engine timed out after %s seconds: %s"
                % (_format_seconds(self.timeout), self.binary),
                TIMEOUT_EXIT_CODE,
            ) from None
        except OSError as exc:
            raise EngineError("cannot run engine: %s" % exc, 126) from None

        # The engine always speaks UTF-8; the process locale must not matter.
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")

        payload: Optional[Dict[str, Any]] = None
        unreadable: Optional[EngineError] = None
        try:
            payload = parse_json_object(stdout)
        except EngineError as exc:
            unreadable = exc

        returncode = completed.returncode
        if returncode != 0:
            error = payload.get("error") if payload is not None else None
            if error is not None:
                message = _structured_message(error)
                fields = error if isinstance(error, dict) else None
            else:
                message = stderr.strip() or stdout.strip()
                if not message:
                    message = "engine exited with code %d" % returncode
                fields = None
            raise EngineError(message, returncode or 1, fields)

        if payload is None:
            message = unreadable.message if unreadable is not None else "engine printed no output"
            raise EngineError(message, 1)

        if payload.get("ok") is False:
            # A structured refusal is a failure even when the engine exited 0,
            # and its own fields are carried through instead of raw output.
            error = payload.get("error")
            if error is not None:
                message = _structured_message(error)
            else:
                message = stderr.strip() or stdout.strip() or "engine reported ok=false"
            raise EngineError(
                message, 1, error if isinstance(error, dict) else None
            )

        return payload
