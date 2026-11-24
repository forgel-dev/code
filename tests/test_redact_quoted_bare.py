"""A quoted label binds the bare value that follows it after whitespace."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forgel_code import interactive  # noqa: E402


class QuotedLabelBareValueTest(unittest.TestCase):
    def test_a_single_quoted_label_masks_a_bare_value(self) -> None:
        for text, shown in (
            ("'token' abc123", "'token' [redacted]"),
            ("'password' hunter2", "'password' [redacted]"),
            ("'token' abc", "'token' [redacted]"),
            ("the 'secret' swordfish", "the 'secret' [redacted]"),
            ("'api-key' ab-12 tail", "'api-key' [redacted] tail"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_double_quoted_label_masks_a_bare_value(self) -> None:
        for text, shown in (
            ('"token" abc123', '"token" [redacted]'),
            ('"password" hunter2', '"password" [redacted]'),
            ('the "secret" swordfish', 'the "secret" [redacted]'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_bare_value_ending_the_clause_is_masked(self) -> None:
        for text, shown in (
            ("'token' abc123.", "'token' [redacted]."),
            ('"token" abc123, rest', '"token" [redacted], rest'),
            ("'token'\nabc123", "'token'\n[redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_label_with_a_separator_is_still_masked(self) -> None:
        for text, shown in (
            ("'token': abc123", "'token': [redacted]"),
            ('"password" = hunter2', '"password" = [redacted]'),
            ("'token':: abc123", "'token':: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_label_with_a_quoted_value_is_still_masked(self) -> None:
        for text, shown in (
            ("'token' 'abc123'", "'token' '[redacted]'"),
            ('"password" "hunter2 and more"', '"password" "[redacted]"'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_an_unquoted_label_still_masks_a_bare_value(self) -> None:
        for text, shown in (
            ("token abc123", "token [redacted]"),
            ("the password hunter2", "the password [redacted]"),
            ("set secret swordfish", "set secret [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_quoted_word_without_a_value_is_left_alone(self) -> None:
        for text in (
            "'token'",
            '"secret"',
            "the word 'token' appears here",
            'say "password" please',
            "the 'token' was rotated.",
            '"secret" is missing',
            "ask about 'token', then wait",
            "'token'. Next sentence",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_a_quoted_word_that_merely_continues_the_sentence_is_left_alone(
        self,
    ) -> None:
        for text in (
            "the 'token' appears here",
            '"password" value is missing',
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_output_without_a_binding_is_unchanged(self) -> None:
        for text in (
            "",
            "release: 0.1.1 open",
            "tasks: (none) -- punctuation, spacing and wording stay!",
            "нажмите на кнопку (дважды)!",
            "the quoted 'word' and \"another\" stay",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_the_new_form_is_idempotent_and_carries_one_marker(self) -> None:
        for text, secret in (
            ("'token' abc123", "abc123"),
            ('"password" hunter2', "hunter2"),
            ("the 'secret' swordfish", "swordfish"),
        ):
            with self.subTest(text=text):
                once = interactive.redact(text)
                self.assertNotIn(secret, once)
                self.assertEqual(once.count("[redacted]"), 1)
                self.assertEqual(interactive.redact(once), once)


if __name__ == "__main__":
    unittest.main()
