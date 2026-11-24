"""French and Spanish secret labels are masked like English and Russian ones."""

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

# An engine whose reply labels secrets in French.
FRENCH_REPLY_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    payload = {
        "ok": True,
        "reply": "mot de passe : hunter2 et clé : abc123",
    }
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine whose reply labels secrets in Spanish.
SPANISH_REPLY_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    payload = {
        "ok": True,
        "reply": "contraseña: hunter2 y clave: abc123",
    }
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine whose retained task title carries a French and a Spanish value.
STATE_ENGINE = textwrap.dedent(
    """\
    import json
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "tasks":
        payload = {
            "ok": True,
            "tasks": [
                {
                    "id": "t-1",
                    "state": "ready",
                    "title": "définir mot de passe : hunter2",
                },
                {
                    "id": "t-2",
                    "state": "ready",
                    "title": "definir contraseña=abc123",
                },
            ],
        }
    else:
        payload = {"ok": True, "release": {"version": "0.1.1", "state": "open"}}
    sys.stdout.write(json.dumps(payload) + chr(10))
    sys.stdout.flush()
    """
)

# An engine that fails with French and then Spanish key material.
FRENCH_ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("échec: mot de passe: hunter2" + chr(10))
    sys.exit(1)
    """
)

SPANISH_ERROR_ENGINE = textwrap.dedent(
    """\
    import sys

    sys.stderr.write("fallo: contraseña: hunter2" + chr(10))
    sys.exit(1)
    """
)


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


class FrenchLabelTest(unittest.TestCase):
    def test_a_french_password_label_is_masked(self) -> None:
        for text, shown in (
            ("mot de passe: hunter2", "mot de passe: [redacted]"),
            ("Mot de passe: hunter2", "Mot de passe: [redacted]"),
            ("MOT DE PASSE = hunter2", "MOT DE PASSE = [redacted]"),
            ("mots de passe=hunter2", "mots de passe=[redacted]"),
            ("Mots De Passe : hunter2", "Mots De Passe : [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_a_french_password_label_tolerates_any_whitespace(self) -> None:
        for text, shown in (
            ("mot  de   passe : hunter2", "mot  de   passe : [redacted]"),
            ("mot\nde\npasse: hunter2", "mot\nde\npasse: [redacted]"),
            ("mot de\tpasse\n= hunter2", "mot de\tpasse\n= [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_the_french_words_for_key_token_and_secret_are_masked(self) -> None:
        for text, shown in (
            ("clé: hunter2", "clé: [redacted]"),
            ("cle: hunter2", "cle: [redacted]"),
            ("Clés: hunter2", "Clés: [redacted]"),
            ("CLEF: hunter2", "CLEF: [redacted]"),
            ("clefs: hunter2", "clefs: [redacted]"),
            ("jeton: abc123", "jeton: [redacted]"),
            ("Jetons: abc123", "Jetons: [redacted]"),
            ("secret: hunter2", "secret: [redacted]"),
            ("secrets: hunter2", "secrets: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_the_french_separators_match_the_existing_ones(self) -> None:
        for text, shown in (
            ("clé:hunter2", "clé:[redacted]"),
            ("clé==hunter2", "clé==[redacted]"),
            ("clé = = hunter2", "clé = = [redacted]"),
            ("clé:\nhunter2", "clé:\n[redacted]"),
            ("clé\nhunter2", "clé\n[redacted]"),
            ("clé: !hunter2", "clé: [redacted]"),
            ("clé: [hunter2]", "clé: [redacted]"),
            ('clé: "hunter2 and more"', 'clé: "[redacted]"'),
            ("'clé': 'hunter2'", "'clé': '[redacted]'"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_every_french_value_of_one_line_is_masked(self) -> None:
        for text, shown in (
            ("clé: abc123 et jeton: xyz789", "clé: [redacted] et jeton: [redacted]"),
            (
                "mot de passe: hunter2, secret: swordfish",
                "mot de passe: [redacted], secret: [redacted]",
            ),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)
                self.assertEqual(interactive.redact(text).count("[redacted]"), 2)

    def test_no_part_of_a_french_value_stays_visible(self) -> None:
        for text, secret in (
            ("mot de passe: hunter2", "hunter2"),
            ("clé: abc123", "abc123"),
            ("jeton: tok-9", "tok-9"),
            ("secret: swordfish", "swordfish"),
        ):
            with self.subTest(text=text):
                self.assertNotIn(secret, interactive.redact(text))

    def test_a_french_label_inside_another_language_is_masked(self) -> None:
        for text, shown in (
            ("the mot de passe is hunter2", "the mot de passe is [redacted]"),
            ("la clave: hunter2 et password: abc123", "la clave: [redacted] et password: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_french_prose_without_a_value_is_unchanged(self) -> None:
        for text in (
            "la clé du projet est prête",
            "le mot de passe est requis",
            "les jetons sont expirés",
            "le secret est conservé",
            "mot de passe oublié",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_french_masking_is_idempotent(self) -> None:
        for text in (
            "mot de passe: hunter2",
            "clé: abc123",
            "clef=hunter2",
            "jeton: tok-9",
        ):
            with self.subTest(text=text):
                once = interactive.redact(text)
                self.assertEqual(once.count("[redacted]"), 1)
                self.assertEqual(interactive.redact(once), once)


class SpanishLabelTest(unittest.TestCase):
    def test_a_spanish_password_label_is_masked(self) -> None:
        for text, shown in (
            ("contraseña: hunter2", "contraseña: [redacted]"),
            ("Contraseña: hunter2", "Contraseña: [redacted]"),
            ("CONTRASENA = hunter2", "CONTRASENA = [redacted]"),
            ("contrasena: hunter2", "contrasena: [redacted]"),
            ("contrasenas=hunter2", "contrasenas=[redacted]"),
            ("Contraseñas: hunter2", "Contraseñas: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_the_spanish_words_for_key_and_secret_are_masked(self) -> None:
        for text, shown in (
            ("clave: hunter2", "clave: [redacted]"),
            ("Claves: hunter2", "Claves: [redacted]"),
            ("secreto: hunter2", "secreto: [redacted]"),
            ("Secretos: hunter2", "Secretos: [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_the_spanish_separators_match_the_existing_ones(self) -> None:
        for text, shown in (
            ("clave:hunter2", "clave:[redacted]"),
            ("clave = = hunter2", "clave = = [redacted]"),
            ("clave:\nhunter2", "clave:\n[redacted]"),
            ("clave\nhunter2", "clave\n[redacted]"),
            ("contraseña: !hunter2", "contraseña: [redacted]"),
            ("contraseña: [hunter2]", "contraseña: [redacted]"),
            ('clave: "hunter2 and more"', 'clave: "[redacted]"'),
            ('"clave": "hunter2"', '"clave": "[redacted]"'),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)

    def test_every_spanish_value_of_one_line_is_masked(self) -> None:
        text = "contraseña: hunter2 y clave: abc123"
        self.assertEqual(
            interactive.redact(text), "contraseña: [redacted] y clave: [redacted]"
        )
        self.assertEqual(interactive.redact(text).count("[redacted]"), 2)

    def test_no_part_of_a_spanish_value_stays_visible(self) -> None:
        for text, secret in (
            ("contraseña: hunter2", "hunter2"),
            ("clave: abc123", "abc123"),
            ("secreto: swordfish", "swordfish"),
        ):
            with self.subTest(text=text):
                self.assertNotIn(secret, interactive.redact(text))

    def test_a_spanish_label_inside_another_language_is_masked(self) -> None:
        text = "the clave is abc123 and la contraseña: hunter2"
        shown = interactive.redact(text)
        self.assertNotIn("abc123", shown)
        self.assertNotIn("hunter2", shown)
        self.assertIn("clave is [redacted]", shown)
        self.assertIn("contraseña: [redacted]", shown)

    def test_spanish_prose_without_a_value_is_unchanged(self) -> None:
        for text in (
            "la contraseña es segura",
            "los secretos del proyecto",
            "la clave del proyecto",
            "la contrasena es segura",
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), text)

    def test_spanish_masking_is_idempotent(self) -> None:
        for text in (
            "contraseña: hunter2",
            "clave: abc123",
            "secreto=hunter2",
            "contrasena: abc123",
        ):
            with self.subTest(text=text):
                once = interactive.redact(text)
                self.assertEqual(once.count("[redacted]"), 1)
                self.assertEqual(interactive.redact(once), once)

    def test_the_english_and_russian_forms_are_unchanged(self) -> None:
        for text, shown in (
            ("password: hunter2", "password: [redacted]"),
            ("token=abc123", "token=[redacted]"),
            ("пароль: hunter2", "пароль: [redacted]"),
            ("токен abc123", "токен [redacted]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(interactive.redact(text), shown)


class FrenchAndSpanishSessionTest(unittest.TestCase):
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

    def test_a_french_reply_is_masked_before_display(self) -> None:
        session = self.open_session(FRENCH_REPLY_ENGINE, "french_reply")
        session.speak("bonjour")
        text = self.out.getvalue()
        self.assertNotIn("hunter2", text)
        self.assertNotIn("abc123", text)
        self.assertIn("mot de passe : [redacted]", text)
        self.assertIn("clé : [redacted]", text)

    def test_a_spanish_reply_is_masked_before_display(self) -> None:
        session = self.open_session(SPANISH_REPLY_ENGINE, "spanish_reply")
        session.speak("hola")
        text = self.out.getvalue()
        self.assertNotIn("hunter2", text)
        self.assertNotIn("abc123", text)
        self.assertIn("contraseña: [redacted]", text)
        self.assertIn("clave: [redacted]", text)

    def test_the_french_state_is_retained_masked(self) -> None:
        session = self.open_session(STATE_ENGINE, "french_state")
        session.lang = "fr"
        session.refresh(force=True)

        self.assertIsNotNone(session.last_state)
        self.assertNotIn("hunter2", session.last_state)
        self.assertIn("mot de passe : [redacted]", session.last_state)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertEqual(interactive.redact(session.last_state), session.last_state)

    def test_the_spanish_state_is_retained_masked(self) -> None:
        session = self.open_session(STATE_ENGINE, "spanish_state")
        session.lang = "es"
        session.refresh(force=True)

        self.assertIsNotNone(session.last_state)
        self.assertNotIn("abc123", session.last_state)
        self.assertIn("contraseña=[redacted]", session.last_state)
        self.assertNotIn("abc123", self.out.getvalue())
        self.assertEqual(interactive.redact(session.last_state), session.last_state)

    def test_a_french_error_is_masked_before_display_and_retention(self) -> None:
        session = self.open_session(FRENCH_ERROR_ENGINE, "french_error")
        session.idle_refresh()

        self.assertIsNotNone(session.idle_failure)
        self.assertNotIn("hunter2", session.idle_failure)
        self.assertIn("mot de passe: [redacted]", session.idle_failure)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertIn("[redacted]", self.out.getvalue())
        self.assertEqual(
            interactive.redact(session.idle_failure), session.idle_failure
        )

    def test_a_spanish_error_is_masked_before_display_and_retention(self) -> None:
        session = self.open_session(SPANISH_ERROR_ENGINE, "spanish_error")
        session.idle_refresh()

        self.assertIsNotNone(session.idle_failure)
        self.assertNotIn("hunter2", session.idle_failure)
        self.assertIn("contraseña: [redacted]", session.idle_failure)
        self.assertNotIn("hunter2", self.out.getvalue())
        self.assertIn("[redacted]", self.out.getvalue())
        self.assertEqual(
            interactive.redact(session.idle_failure), session.idle_failure
        )


if __name__ == "__main__":
    unittest.main()
