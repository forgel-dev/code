"""Key material never reaches the session screen."""

from __future__ import annotations

import io
import json
import os
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

# An engine whose reply and whose task titles carry key material.
REPLY_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "say":
        payload = {
            "ok": True,
            "reply": "'token': 'abc123' and the token: abc123 was stored",
        }
    elif command == "tasks":
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

# An engine that fails with key material in its error message.
ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("denied: password: hunter2" + chr(10))
    sys.exit(1)
    """
)


def _launcher(directory: Path, script: str) -> Path:
    stub = directory / "redact_stub.py"
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


class RedactFormTest(unittest.TestCase):
    def test_a_colon_joined_value_is_masked(self) -> None:
        self.assertEqual(
            interactive.redact("password: hunter2"), "password: [redacted]"
        )
        self.assertEqual(
            interactive.redact("password:hunter2"), "password:[redacted]"
        )
        self.assertEqual(interactive.redact("token:abc123"), "token:[redacted]")

    def test_an_equals_joined_value_is_masked(self) -> None:
        self.assertEqual(
            interactive.redact("password=hunter2"), "password=[redacted]"
        )
        self.assertEqual(
            interactive.redact("password = hunter2"), "password = [redacted]"
        )

    def test_every_separator_character_stays_visible(self) -> None:
        for text, shown in (
            ("password==hunter2", "password==[redacted]"),
            ("token::abc", "token::[redacted]"),
            ("password = = hunter2", "password = = [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_value_is_masked_between_its_quotes(self) -> None:
        for text, shown in (
            ('password: "hunter2 and more"', 'password: "[redacted]"'),
            ("password: 'hunter2 and more'", "password: '[redacted]'"),
            ("password: `hunter2 and more`", "password: `[redacted]`"),
            ("password: «hunter2 and more»", "password: «[redacted]»"),
            ('password "hunter2 and more"', 'password "[redacted]"'),
            ('password: "hunter2 and more', 'password: "[redacted]'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_single_quoted_label_keeps_its_quotes_and_masks_the_value(self) -> None:
        for text, shown in (
            ("'token': 'abc123'", "'token': '[redacted]'"),
            ("'password'='hunter2'", "'password'='[redacted]'"),
            ("the 'secret': 'swordfish' stays", "the 'secret': '[redacted]' stays"),
            ("'api-key': 'ab-12 cd'", "'api-key': '[redacted]'"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_double_quoted_label_keeps_its_quotes_and_masks_the_value(self) -> None:
        for text, shown in (
            ('"token": "abc123"', '"token": "[redacted]"'),
            ('"password" = "hunter2 and more"', '"password" = "[redacted]"'),
            ('"secret" : "swordfish"', '"secret" : "[redacted]"'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_json_style_label_masks_its_value(self) -> None:
        for text, shown in (
            ('{"token":"abc123"}', '{"token":"[redacted]"}'),
            ('{"password":"hunter2"}', '{"password":"[redacted]"}'),
            (
                '{"key": "abc123", "release": "0.1.1"}',
                '{"key": "[redacted]", "release": "0.1.1"}',
            ),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_label_masks_an_unquoted_value(self) -> None:
        for text, shown in (
            ("'token': abc123 now", "'token': [redacted] now"),
            ('"password": hunter2, rest', '"password": [redacted], rest'),
            ("'secret'=swordfish", "'secret'=[redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_label_keeps_repeated_separators_visible(self) -> None:
        for text, shown in (
            ("'token':: abc123", "'token':: [redacted]"),
            ('"token" == "abc123"', '"token" == "[redacted]"'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_label_does_not_mask_its_neighbours(self) -> None:
        for text in (
            'the word "token" appears here',
            "say 'password' please",
            '"secret" is missing',
            "the 'token' was rotated.",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_a_whitespace_joined_value_still_is_masked(self) -> None:
        self.assertEqual(interactive.redact("token abc"), "token [redacted]")
        self.assertEqual(interactive.redact("the token abc"), "the token [redacted]")
        self.assertEqual(
            interactive.redact("set password swordfish"), "set password [redacted]"
        )

    def test_an_authorization_scheme_stays_visible(self) -> None:
        self.assertEqual(
            interactive.redact("Authorization: Bearer abc123"),
            "Authorization: Bearer [redacted]",
        )
        self.assertEqual(
            interactive.redact("the token Bearer secretvalue"),
            "the token Bearer [redacted]",
        )

    def test_a_russian_label_is_masked(self) -> None:
        self.assertEqual(interactive.redact("пароль: hunter2"), "пароль: [redacted]")
        self.assertEqual(interactive.redact("Пароль=hunter2"), "Пароль=[redacted]")
        self.assertEqual(interactive.redact("токен abc123"), "токен [redacted]")
        self.assertEqual(interactive.redact("токен: abc123"), "токен: [redacted]")

    def test_a_compound_label_is_masked(self) -> None:
        for text, shown in (
            ("db_password=hunter2", "db_password=[redacted]"),
            ("aws.secret.key: hunter2", "aws.secret.key: [redacted]"),
            ("api-key=hunter2", "api-key=[redacted]"),
            ("AWS_SECRET_ACCESS_KEY=abc123", "AWS_SECRET_ACCESS_KEY=[redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_mentioned_label_is_left_alone(self) -> None:
        for text in (
            "Password updated.",
            "Secret rotation scheduled",
            "the token is missing",
            "rotate the password please",
            "send the secret later",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_secret_free_text_is_unchanged(self) -> None:
        for text in (
            "",
            "release: 0.1.1 open",
            "tasks: (none) -- punctuation, spacing and wording stay!",
            "нажмите на кнопку (дважды)!",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_redaction_is_idempotent(self) -> None:
        for text in (
            "password: hunter2",
            "password==hunter2",
            'password: "hunter2 and more"',
            "token abc",
            "Authorization: Bearer abc123",
            "пароль: hunter2",
            "db_password=hunter2",
            "'token': 'abc123'",
            '"token": "abc123"',
            '{"token":"abc123"}',
            "'token': abc123",
        ):
            with self.subTest(text=text):
                once = interactive.redact(text)
                self.assertEqual(interactive.redact(once), once)
                self.assertIn("[redacted]", once)
                self.assertEqual(once.count("[redacted]"), 1)

    def test_each_masked_value_carries_exactly_one_marker(self) -> None:
        for text in (
            "password: hunter2",
            "password==hunter2",
            'password: "hunter2 and more"',
            "'token': 'abc123'",
            '"token": "abc123"',
            '{"token":"abc123"}',
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text).count("[redacted]"), 1)

    def test_no_character_of_a_quoted_secret_stays_visible(self) -> None:
        for text, secret in (
            ("'token': 'abc123'", "abc123"),
            ('"token": "abc123"', "abc123"),
            ('{"token":"abc123"}', "abc123"),
            ("'token': abc123 tail", "abc123"),
        ):
            with self.subTest(text=text):
                self.assertNotIn(secret, interactive.redact(text))


class ScreenMaskingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.backup = dict(os.environ)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.environ.clear()
        os.environ.update(self.backup)

    def run_session(self, script: str, lines) -> str:
        launcher = _launcher(self.home, script)
        out = io.StringIO()
        session = interactive.InteractiveSession(
            Engine(str(launcher), 30),
            Session(self.home / "session" / "session.json"),
            out,
            io.StringIO("".join(line + "\n" for line in lines)),
        )
        session.run()
        return out.getvalue()

    def test_an_engine_reply_is_masked_before_display(self) -> None:
        text = self.run_session(REPLY_ENGINE, ["hello there"])
        self.assertNotIn("abc123", text)
        self.assertIn("token: [redacted]", text)

    def test_a_quoted_label_in_an_engine_reply_is_masked(self) -> None:
        text = self.run_session(REPLY_ENGINE, ["hello there"])
        self.assertNotIn("abc123", text)
        self.assertIn("'token': '[redacted]'", text)

    def test_engine_state_shown_in_the_session_is_masked(self) -> None:
        text = self.run_session(REPLY_ENGINE, ["hello there"])
        self.assertNotIn("hunter2", text)
        self.assertIn("password=[redacted]", text)

    def test_an_engine_error_is_masked_before_display(self) -> None:
        text = self.run_session(ERROR_ENGINE, ["hello there"])
        self.assertNotIn("hunter2", text)
        self.assertIn("[redacted]", text)


if __name__ == "__main__":
    unittest.main()
