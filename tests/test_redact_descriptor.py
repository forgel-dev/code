"""A label, an ordinary descriptor and then a value: the value is hidden.

The label and the descriptive words around it stay readable, and only the
credential is replaced by the masking placeholder — on screen, in the state
the client keeps and in the failure it keeps.
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

# An engine whose task title, and whose shown state, carry key material behind
# a descriptive word.
DESCRIPTOR_STATE_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "tasks":
        payload = {
            "ok": True,
            "tasks": [
                {"id": "t-1", "state": "ready", "title": "token value is hunter2"}
            ],
        }
    else:
        payload = {"ok": True, "release": {"version": "0.1.1", "state": "open"}}
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine that fails with key material behind a descriptive word.
DESCRIPTOR_ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("denied: token value is hunter2" + chr(10))
    sys.exit(1)
    """
)


class DescriptorFormTest(unittest.TestCase):
    def test_a_descriptor_before_the_value_keeps_the_label_visible(self) -> None:
        for text, shown in (
            ("token value is hunter2", "token value is [redacted]"),
            ("the token value is hunter2", "the token value is [redacted]"),
            ("token value: hunter2", "token value: [redacted]"),
            ("token value hunter2", "token value [redacted]"),
            ("the password string is hunter2", "the password string is [redacted]"),
            ("token value is 'hunter2 and more'", "token value is '[redacted]'"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_sentence_that_begins_with_the_label_is_masked(self) -> None:
        for text, shown in (
            ("password field is hunter2", "password field is [redacted]"),
            ("password field: hunter2", "password field: [redacted]"),
            ("secret value hunter2", "secret value [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_several_ordinary_words_keep_the_value_the_credential(self) -> None:
        for text, shown in (
            ("token value is still hunter2", "token value is still [redacted]"),
            ("the token actual value is hunter2", "the token actual value is [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_russian_label_with_a_descriptor_is_masked(self) -> None:
        for text, shown in (
            ("токен значение это hunter2", "токен значение это [redacted]"),
            ("токен значение hunter2", "токен значение [redacted]"),
            ("пароль значение: hunter2", "пароль значение: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_no_part_of_the_credential_stays_visible(self) -> None:
        for text, secret in (
            ("token value is hunter2", "hunter2"),
            ("password field is hunter2", "hunter2"),
            ("token value: hunter2 tail", "hunter2"),
            ("токен значение hunter2", "hunter2"),
        ):
            with self.subTest(text=text):
                self.assertNotIn(secret, interactive.redact(text))

    def test_the_descriptor_correction_is_idempotent(self) -> None:
        for text in (
            "token value is hunter2",
            "password field is hunter2",
            "token value: hunter2",
            "токен значение hunter2",
        ):
            with self.subTest(text=text):
                once = interactive.redact(text)
                self.assertEqual(once.count("[redacted]"), 1)
                self.assertEqual(interactive.redact(once), once)

    def test_prose_without_a_value_stays_unchanged(self) -> None:
        for text in (
            "the token value is missing",
            "password field updated",
            "the secret value was rotated",
            "токен значение обновлён",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_the_previously_masked_forms_are_unchanged(self) -> None:
        for text, shown in (
            ("password=hunter2", "password=[redacted]"),
            ("token:abc123", "token:[redacted]"),
            ("db_password=hunter2", "db_password=[redacted]"),
            ("AWS_SECRET_ACCESS_KEY=abc123", "AWS_SECRET_ACCESS_KEY=[redacted]"),
            ("Authorization: Bearer abc123", "Authorization: Bearer [redacted]"),
            ("пароль: hunter2", "пароль: [redacted]"),
            ("токен abc123", "токен [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)


class DescriptorRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def open_session(self, script: str) -> interactive.InteractiveSession:
        stub = self.home / "descriptor_stub.py"
        stub.write_text(script, encoding="utf-8")
        launcher = self.home / "forgel"
        launcher.write_text(
            '#!/bin/sh\nexec %s %s "$@"\n'
            % (shlex.quote(sys.executable), shlex.quote(str(stub))),
            encoding="utf-8",
        )
        launcher.chmod(
            launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        self.out = io.StringIO()
        return interactive.InteractiveSession(
            Engine(str(launcher), 30),
            Session(self.home / "session" / "session.json"),
            self.out,
            io.StringIO(""),
        )

    def test_the_retained_state_hides_the_credential(self) -> None:
        session = self.open_session(DESCRIPTOR_STATE_ENGINE)
        session.refresh(force=True)

        self.assertIsNotNone(session.last_state)
        self.assertNotIn("hunter2", session.last_state)
        self.assertIn("token value is [redacted]", session.last_state)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertEqual(interactive.redact(session.last_state), session.last_state)

    def test_the_retained_idle_failure_hides_the_credential(self) -> None:
        session = self.open_session(DESCRIPTOR_ERROR_ENGINE)
        session.idle_refresh()

        self.assertIsNotNone(session.idle_failure)
        self.assertNotIn("hunter2", session.idle_failure)
        self.assertIn("token value is [redacted]", session.idle_failure)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertIn("[redacted]", self.out.getvalue())
        self.assertEqual(
            interactive.redact(session.idle_failure), session.idle_failure
        )


if __name__ == "__main__":
    unittest.main()
