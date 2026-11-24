"""Sensitive free-text requests are refused and never reach the engine.

The guard exists so a sentence can never trigger an action the product reserves
for an explicit operation. Every recognised form of the three guarded families
is exercised in both interface languages, through the same entry path a typed
line takes, and the stand-in engine records every request it receives so the
absence of a passthrough is observable.
"""

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

# The stand-in answers ``say`` with a reply and every other command with an
# empty project state, and appends every argv to ``GUARD_STUB_LOG``.
STUB_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys

    argv = sys.argv[1:]
    log = os.environ.get("GUARD_STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv, ensure_ascii=False) + chr(10))
    command = argv[0] if argv else ""
    if command == "say":
        payload = {"ok": True, "reply": "the agent answered"}
    else:
        payload = {
            "ok": True,
            "tasks": [],
            "release": {"version": "0.1.1", "state": "open"},
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + chr(10))
    sys.stdout.flush()
    """
)

# The explicit operation every refusal must name, so the owner can act.
EXPLICIT_OPERATION = "forgel-code"

# The request the engine answers, so its presence means a passthrough.
ANSWERED = "the agent answered"

# Every recognised form, by guarded category and interface language.
KEY_MATERIAL_EN = (
    "create a key",
    "set the key",
    "change the key",
    "put a new key here",
    "rotate the key",
    "create a password",
    "set the token",
    "store the credential",
)
KEY_MATERIAL_RU = (
    "создай ключ",
    "задай ключ",
    "смени ключ",
    "установи пароль",
    "поменяй токен",
)

CONFIGURATION_EN = (
    "change the config",
    "update the configuration",
    "edit the settings",
    "set the preferences",
)
CONFIGURATION_RU = (
    "поменяй настройки",
    "измени конфиг",
    "обнови конфигурацию",
    "смени параметры",
)

PROJECT_EN = (
    "scaffold a project",
    "create a new project",
    "bootstrap the project",
    "initialize a project",
    "init a project",
    "generate a project",
)
PROJECT_RU = (
    "создай проект",
    "заскаффолди проект",
    "инициализируй проект",
    "сгенерируй каркас",
    "создай каркас проекта",
)

GUARDED = {
    "key material": {
        "en": KEY_MATERIAL_EN,
        "ru": KEY_MATERIAL_RU,
    },
    "configuration": {
        "en": CONFIGURATION_EN,
        "ru": CONFIGURATION_RU,
    },
    "project creation": {
        "en": PROJECT_EN,
        "ru": PROJECT_RU,
    },
}

# Ordinary conversation in the same two languages: it mentions the same subjects
# without asking to create or change them, so it must still reach the engine.
ORDINARY = (
    "what is left in the milestone?",
    "how is the project going?",
    "what does the config hold?",
    "пожалуйста, покажи задачи",
    "как дела с проектом?",
)


def forms(language):
    """Every recognised form of every guarded category in one language."""
    return [
        phrase
        for category in GUARDED.values()
        for phrase in category[language]
    ]


class GuardCase(unittest.TestCase):
    """A session over a stand-in engine that records every request."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.engine_path = self._write_engine()
        self.log = self.home / "argv.log"
        self.store = Session(self.home / "session" / "session.json")
        self.env = dict(os.environ)
        self.env["GUARD_STUB_LOG"] = str(self.log)
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")

    def _write_engine(self) -> Path:
        script = self.bin_dir / "guard_stub.py"
        script.write_text(STUB_ENGINE, encoding="utf-8")
        launcher = self.bin_dir / "forgel"
        launcher.write_text(
            '#!/bin/sh\nexec %s %s "$@"\n'
            % (shlex.quote(sys.executable), shlex.quote(str(script))),
            encoding="utf-8",
        )
        launcher.chmod(
            launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return launcher

    def run_session(self, lines):
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        out = io.StringIO()
        try:
            session = interactive.InteractiveSession(
                Engine(str(self.engine_path), 30),
                self.store,
                out,
                io.StringIO("".join(line + "\n" for line in lines)),
            )
            code = session.run()
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue()

    def calls(self):
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def assert_no_passthrough(self, text, phrases):
        """No request of these phrases reached the engine and none was answered."""
        self.assertNotIn(ANSWERED, text)
        self.assertNotIn("say", [call[0] for call in self.calls() if call])
        for call in self.calls():
            joined = " ".join(call)
            for phrase in phrases:
                self.assertNotIn(phrase, joined)


def _messages(language):
    return interactive.MESSAGES["sensitive"][language]


class RecognisedFormTest(unittest.TestCase):
    """Every guarded form is decided as a sensitive request."""

    def test_every_guarded_form_is_recognised(self) -> None:
        for category, by_language in GUARDED.items():
            for language, phrases in by_language.items():
                for phrase in phrases:
                    with self.subTest(
                        category=category, language=language, phrase=phrase
                    ):
                        self.assertEqual(
                            interactive.resolve(phrase)["kind"], "sensitive"
                        )

    def test_existing_refusals_are_kept(self) -> None:
        for phrase in (
            "adopt the repository acme",
            "create a project acme",
            "set the secret token abc123",
            "change the configuration",
            "создай проект",
            "поменяй конфигурацию",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "sensitive")

    def test_a_mention_without_a_request_stays_ordinary(self) -> None:
        for phrase in ORDINARY:
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "say")


class RefusedWithoutRequestTest(GuardCase):
    """A guarded request is refused in the client and never forwarded."""

    def check_language(self, language: str) -> None:
        phrases = forms(language)
        code, text = self.run_session(list(phrases))
        self.assertEqual(code, 0)
        self.assert_no_passthrough(text, phrases)
        # One refusal per phrase, and every one of them names the operation.
        self.assertEqual(text.count(EXPLICIT_OPERATION), len(phrases))

    def test_every_english_form_is_refused_without_a_request(self) -> None:
        self.check_language("en")

    def test_every_russian_form_is_refused_without_a_request(self) -> None:
        self.check_language("ru")

    def test_the_refusal_speaks_the_language_of_the_session(self) -> None:
        _, text = self.run_session(["create a key", "создай ключ"])
        self.assertIn(_messages("en"), text)
        self.assertIn(_messages("ru"), text)
        self.assert_no_passthrough(text, ["create a key", "создай ключ"])

    def test_the_refusal_states_the_action_is_explicit_and_names_it(self) -> None:
        _, text = self.run_session(["scaffold a project", "поменяй настройки"])
        english, russian = _messages("en"), _messages("ru")
        self.assertIn("explicit separate", english)
        self.assertIn(EXPLICIT_OPERATION, english)
        self.assertIn("явные", russian)
        self.assertIn(EXPLICIT_OPERATION, russian)
        self.assertIn(english, text)
        self.assertIn(russian, text)

    def test_ordinary_conversation_still_reaches_the_engine(self) -> None:
        _, text = self.run_session(list(ORDINARY))
        self.assertEqual(text.count(ANSWERED), len(ORDINARY))
        said = [call for call in self.calls() if call and call[0] == "say"]
        self.assertEqual(len(said), len(ORDINARY))
        self.assertNotIn(_messages("en"), text)
        self.assertNotIn(_messages("ru"), text)


if __name__ == "__main__":
    unittest.main()
