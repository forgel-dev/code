"""The French password label is masked joined with underscores or hyphens."""

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

JOINED = ("mot_de_passe", "mot-de-passe", "MOT_DE_PASSE", "Mot-De-Passe")

# An engine whose reply and whose retained task title carry a joined label.
REPLY_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "say":
        payload = {
            "ok": True,
            "reply": "mot-de-passe: hunter2 et mot_de_passe=abc123",
        }
    elif command == "tasks":
        payload = {
            "ok": True,
            "tasks": [
                {"id": "t-1", "state": "ready", "title": "mot_de_passe : swordfish"}
            ],
        }
    else:
        payload = {"ok": True, "release": {"version": "0.1.1", "state": "open"}}
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine that fails with a joined French password label.
ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("\u00e9chec: mot-de-passe: hunter2" + chr(10))
    sys.exit(1)
    """
)


class JoinedFrenchLabelTest(unittest.TestCase):
    def test_a_joined_label_masks_its_value(self) -> None:
        for label in JOINED:
            with self.subTest(label=label):
                shown = interactive.redact(label + ": hunter2")
                self.assertNotIn("hunter2", shown)
                self.assertEqual(shown, label + ": [redacted]")

    def test_a_joined_label_matches_its_spaced_equivalent(self) -> None:
        for text in (
            "mot de passe: hunter2",
            "mot de passe = hunter2",
            "mot de passe==hunter2",
            "mot de passe : hunter2",
            "Mot de Passe: hunter2",
            'mot de passe: "hunter2 and more"',
            "mot de passe: 'hunter2 and more'",
            "mot de passe \"hunter2 and more\"",
            "mot de passe hunter2",
            "the mot de passe is hunter2",
            "mot de passe: [hunter2]",
            "mot de passe: !hunter2",
            "'mot de passe': 'hunter2'",
            '"mot de passe": "hunter2"',
            "'mot de passe' hunter2",
            "[mot de passe]: hunter2",
            "mot de passe:\nhunter2",
            "mots de passe: hunter2",
        ):
            spaced = interactive.redact(text)
            for joiner in ("_", "-"):
                with self.subTest(text=text, joiner=joiner):
                    joined_text = text.replace("mot de passe", "mot" + joiner + "de" + joiner + "passe")
                    joined_text = joined_text.replace(
                        "mots de passe", "mots" + joiner + "de" + joiner + "passe"
                    )
                    self.assertEqual(
                        interactive.redact(joined_text),
                        spaced.replace("mot de passe", "mot" + joiner + "de" + joiner + "passe").replace(
                            "mots de passe", "mots" + joiner + "de" + joiner + "passe"
                        ),
                    )

    def test_every_joined_spelling_removes_the_value(self) -> None:
        for label in JOINED:
            for text in (
                label + ": hunter2",
                label + "=hunter2",
                label + ' = "hunter2 and more"',
                "'" + label + "': hunter2",
            ):
                with self.subTest(text=text):
                    shown = interactive.redact(text)
                    self.assertNotIn("hunter2", shown)
                    self.assertEqual(shown.count("[redacted]"), 1)

    def test_a_joined_label_without_a_value_is_left_alone(self) -> None:
        for text in (
            "mot_de_passe",
            "mot-de-passe",
            "le mot_de_passe est requis",
            "mot-de-passe oubli\u00e9",
            "les mots_de_passe sont expir\u00e9s",
            "le mot-de-passe du projet est pr\u00eat",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_other_labels_and_the_spaced_form_still_redact(self) -> None:
        for text, shown in (
            ("mot de passe: hunter2", "mot de passe: [redacted]"),
            ("cl\u00e9: hunter2", "cl\u00e9: [redacted]"),
            ("password: hunter2", "password: [redacted]"),
            ("\u043f\u0430\u0440\u043e\u043b\u044c: hunter2", "\u043f\u0430\u0440\u043e\u043b\u044c: [redacted]"),
            ("contrase\u00f1a: hunter2", "contrase\u00f1a: [redacted]"),
            ("db_password=hunter2", "db_password=[redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_joined_masking_is_idempotent(self) -> None:
        for label in JOINED:
            with self.subTest(label=label):
                once = interactive.redact(label + ": hunter2")
                self.assertEqual(once.count("[redacted]"), 1)
                self.assertEqual(interactive.redact(once), once)


def _launcher(directory: Path, script: str, name: str) -> Path:
    stub = directory / (name + ".py")
    stub.write_text(script, encoding="utf-8")
    launcher = directory / (name + "-forgel")
    launcher.write_text(
        '#!/bin/sh\nexec %s %s "$@"\n'
        % (shlex.quote(sys.executable), shlex.quote(str(stub))),
        encoding="utf-8",
    )
    launcher.chmod(
        launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    return launcher


class JoinedFrenchRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.out = io.StringIO()

    def open_session(self, script: str, name: str) -> interactive.InteractiveSession:
        launcher = _launcher(self.home, script, name)
        self.out = io.StringIO()
        return interactive.InteractiveSession(
            Engine(str(launcher), 30),
            Session(self.home / "session" / "session.json"),
            self.out,
            io.StringIO(""),
        )

    def test_a_joined_reply_is_masked_before_display(self) -> None:
        session = self.open_session(REPLY_ENGINE, "joined_reply")
        session.speak("bonjour")
        text = self.out.getvalue()
        self.assertNotIn("hunter2", text)
        self.assertNotIn("abc123", text)
        self.assertIn("mot-de-passe: [redacted]", text)
        self.assertIn("mot_de_passe=[redacted]", text)

    def test_the_joined_state_is_retained_masked(self) -> None:
        session = self.open_session(REPLY_ENGINE, "joined_state")
        session.refresh(force=True)

        self.assertIsNotNone(session.last_state)
        self.assertNotIn("swordfish", session.last_state)
        self.assertIn("mot_de_passe : [redacted]", session.last_state)
        self.assertNotIn("swordfish", self.out.getvalue())
        self.assertEqual(interactive.redact(session.last_state), session.last_state)

    def test_a_joined_error_is_masked_before_display_and_retention(self) -> None:
        session = self.open_session(ERROR_ENGINE, "joined_error")
        session.idle_refresh()

        self.assertIsNotNone(session.idle_failure)
        self.assertNotIn("hunter2", session.idle_failure)
        self.assertIn("mot-de-passe: [redacted]", session.idle_failure)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertIn("[redacted]", self.out.getvalue())
        self.assertEqual(
            interactive.redact(session.idle_failure), session.idle_failure
        )


if __name__ == "__main__":
    unittest.main()
