"""Only masked engine text is kept in memory for the session.

Displaying a text is not enough: a copy the client retains must already be
masked, otherwise a later repeat of that copy would reveal the secret.
"""

from __future__ import annotations

import io
import json
import shlex
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forgel_code import interactive  # noqa: E402
from forgel_code.engine import Engine  # noqa: E402
from forgel_code.session import Session  # noqa: E402

# An engine whose task title carries key material.
SECRET_STATE_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "tasks":
        payload = {
            "ok": True,
            "tasks": [
                {"id": "t-1", "state": "ready", "title": "use password=hunter2"}
            ],
        }
    else:
        payload = {"ok": True, "release": {"version": "0.1.1", "state": "open"}}
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine whose state carries no key material.
CLEAN_STATE_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "tasks":
        payload = {
            "ok": True,
            "tasks": [
                {"id": "t-1", "state": "ready", "title": "add a login screen"}
            ],
        }
    else:
        payload = {"ok": True, "release": {"version": "0.1.1", "state": "open"}}
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine that fails with key material in its error message.
SECRET_ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("denied: password: hunter2" + chr(10))
    sys.exit(1)
    """
)


def _launcher(directory: Path, script: str) -> Path:
    stub = directory / "retained_stub.py"
    stub.write_text(script, encoding="utf-8")
    launcher = directory / "forgel"
    launcher.write_text(
        '#!/bin/sh\nexec %s %s "$@"\n'
        % (shlex.quote(sys.executable), shlex.quote(str(stub))),
        encoding="utf-8",
    )
    launcher.chmod(
        launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    return launcher


class RetainedTextCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def open_session(self, script: str) -> interactive.InteractiveSession:
        launcher = _launcher(self.home, script)
        self.out = io.StringIO()
        return interactive.InteractiveSession(
            Engine(str(launcher), 30),
            Session(self.home / "session" / "session.json"),
            self.out,
            io.StringIO(""),
        )


class RetainedStateTest(RetainedTextCase):
    def test_the_state_is_masked_before_it_is_retained(self) -> None:
        session = self.open_session(SECRET_STATE_ENGINE)
        lines = session.state_lines()
        session.show_state(lines)

        self.assertIsNotNone(session.last_state)
        self.assertNotIn("hunter2", session.last_state)
        self.assertIn("password=[redacted]", session.last_state)
        self.assertEqual(session.last_state, interactive.redact("\n".join(lines)))
        self.assertNotIn("hunter2", self.out.getvalue())

    def test_a_forced_refresh_retains_the_masked_state(self) -> None:
        session = self.open_session(SECRET_STATE_ENGINE)
        session.refresh(force=True)

        self.assertNotIn("hunter2", session.last_state)
        self.assertIn("password=[redacted]", session.last_state)
        self.assertNotIn("hunter2", self.out.getvalue())

    def test_repeating_a_retained_state_display_shows_the_mask(self) -> None:
        session = self.open_session(SECRET_STATE_ENGINE)
        session.refresh(force=True)
        self.out.seek(0)
        self.out.truncate(0)

        session.write(session.last_state)
        repeated = self.out.getvalue()

        self.assertNotIn("hunter2", repeated)
        self.assertIn("password=[redacted]", repeated)
        self.assertEqual(interactive.redact(session.last_state), session.last_state)

    def test_secret_free_state_is_retained_unchanged(self) -> None:
        session = self.open_session(CLEAN_STATE_ENGINE)
        lines = session.state_lines()
        session.show_state(lines)

        self.assertEqual(session.last_state, "\n".join(lines))
        self.assertIn("add a login screen", self.out.getvalue())


class RetainedFailureTest(RetainedTextCase):
    def test_the_idle_failure_is_masked_before_it_is_retained(self) -> None:
        session = self.open_session(SECRET_ERROR_ENGINE)
        session.idle_refresh()

        self.assertIsNotNone(session.idle_failure)
        self.assertNotIn("hunter2", session.idle_failure)
        self.assertIn("[redacted]", session.idle_failure)
        self.assertNotIn("hunter2", self.out.getvalue())

    def test_repeating_a_retained_failure_display_shows_the_mask(self) -> None:
        session = self.open_session(SECRET_ERROR_ENGINE)
        session.idle_refresh()
        first = self.out.getvalue()
        self.assertIn("[redacted]", first)

        # The same outage is stated once, and repeating it reveals nothing.
        self.out.seek(0)
        self.out.truncate(0)
        session.idle_refresh()
        self.assertEqual(self.out.getvalue(), "")

        session.write(session.idle_failure)
        repeated = self.out.getvalue()
        self.assertNotIn("hunter2", repeated)
        self.assertIn("[redacted]", repeated)
        self.assertEqual(
            interactive.redact(session.idle_failure), session.idle_failure
        )


if __name__ == "__main__":
    unittest.main()
