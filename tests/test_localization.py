"""The session answers in the owner's language, engine answer included."""

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

# The stand-in engine of the client: one JSON object per call, and every argv
# appended to ``SESSION_STUB_LOG``. ``SESSION_STUB_ECHO`` makes ``say`` answer
# with the owner's own sentence, as a model-composed answer follows the
# language of the request. ``SESSION_STUB_FAIL_SAY`` makes it fail in its own
# words instead of answering.
STUB_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys

    argv = sys.argv[1:]
    log = os.environ.get("SESSION_STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv, ensure_ascii=False) + chr(10))

    payload = json.loads(os.environ["SESSION_STUB_PAYLOAD"])
    command = argv[0] if argv else ""
    if command == "say":
        if os.environ.get("SESSION_STUB_FAIL_SAY"):
            sys.stderr.write("the engine refused the request in its own words" + chr(10))
            sys.exit(3)
        if os.environ.get("SESSION_STUB_ECHO"):
            text = argv[argv.index("--text") + 1] if "--text" in argv else ""
            payload = {"ok": True, "reply": "echo: " + text}
        else:
            payload = {"ok": True, "reply": "the agent answered"}
    elif command == "plan":
        payload = {
            "ok": True,
            "plan": {
                "tasks": [
                    {"id": "t-1", "state": "planned", "title": "first"},
                    {"id": "t-2", "state": "planned", "title": "second"},
                ]
            },
        }
    elif command == "use" and os.environ.get("SESSION_STUB_REJECT_USE"):
        payload = {
            "ok": False,
            "error": {"code": "unknown_project", "message": "no such project"},
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + chr(10))
    sys.stdout.flush()
    """
)

STATE = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "ready", "title": "add a login screen"},
        {"id": "t-2", "state": "done", "title": "write the docs"},
    ],
    "release": {"version": "0.1.1", "state": "open"},
}

FRENCH = "bonjour, quelle est la version du projet ?"
SPANISH = "hola, \u00bfqu\u00e9 pasa con el proyecto?"
RUSSIAN = "\u043f\u0440\u0438\u0432\u0435\u0442, \u0447\u0442\u043e \u043f\u043e \u0440\u0435\u043b\u0438\u0437\u0443?"

# The sensitive explicit actions of the session, written as ordinary French and
# Spanish sentences: another verb form, another word order and the same words
# without diacritics are the same request.
FRENCH_SENSITIVE = (
    "cr\u00e9e un projet",
    "cr\u00e9er un projet",
    "je veux cr\u00e9er un projet",
    "cree un projet",
    "un nouveau projet",
    "d\u00e9finir le mot de passe",
    "d\u00e9finis le mot de passe",
    "mettre \u00e0 jour la configuration",
    "changer la configuration",
    "d\u00e9finir le jeton d'acc\u00e8s",
)
SPANISH_SENSITIVE = (
    "crear un proyecto",
    "crea un proyecto",
    "quiero crear un proyecto",
    "un proyecto nuevo",
    "definir la contrase\u00f1a",
    "definir la contrasena",
    "asignar la clave",
    "cambiar la configuraci\u00f3n",
    "cambiar la configuracion",
    "modificar los par\u00e1metros",
)

# The audited phrases together with their low-variation forms.
REFUSED = FRENCH_SENSITIVE + SPANISH_SENSITIVE

ORDINARY = (
    "bonjour, quelle est la version du projet ?",
    "hola, \u00bfqu\u00e9 pasa con el proyecto?",
    "merci, montre les t\u00e2ches",
    "gracias, muestre las tareas",
    "comment vas-tu ?",
    "je voudrais voir les t\u00e2ches en cours",
    "\u00bfc\u00f3mo est\u00e1s?",
    "quiero ver las tareas",
)

ENGLISH_WORDING = ("project:", "tasks:", "release:", "session ended")
FRENCH_WORDING = ("projet :", "t\u00e2ches :", "publication :", "session termin\u00e9e")
SPANISH_WORDING = ("proyecto:", "tareas:", "publicaci\u00f3n:", "sesi\u00f3n terminada")
RUSSIAN_WORDING = (
    "\u043f\u0440\u043e\u0435\u043a\u0442:",
    "\u0437\u0430\u0434\u0430\u0447\u0438:",
    "\u0440\u0435\u043b\u0438\u0437:",
    "\u0441\u0435\u0430\u043d\u0441 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d",
)


def _write_engine(directory: Path) -> Path:
    script = directory / "session_stub.py"
    script.write_text(STUB_ENGINE, encoding="utf-8")
    launcher = directory / "forgel"
    launcher.write_text(
        '#!/bin/sh\nexec %s %s "$@"\n'
        % (shlex.quote(sys.executable), shlex.quote(str(script))),
        encoding="utf-8",
    )
    launcher.chmod(
        launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    return launcher


class LocalizationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.engine_path = _write_engine(self.bin_dir)
        self.log = self.home / "argv.log"
        self.store = Session(self.home / "session" / "session.json")
        self.env = dict(os.environ)
        self.env["SESSION_STUB_PAYLOAD"] = json.dumps(STATE)
        self.env["SESSION_STUB_LOG"] = str(self.log)
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        for name in (
            "SESSION_STUB_ECHO",
            "SESSION_STUB_FAIL_SAY",
            "SESSION_STUB_REJECT_USE",
        ):
            self.env.pop(name, None)

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

    def reply_of_first_message(self, text: str) -> str:
        """Everything the session composed from its first message onwards."""
        return text[text.index(interactive.PROMPT):]

    def assert_wording(self, text: str, wording) -> None:
        for fragment in wording:
            self.assertIn(fragment, text)

    def assert_no_wording(self, text: str, wording) -> None:
        for fragment in wording:
            self.assertNotIn(fragment, text)


class DetectionTest(unittest.TestCase):
    def test_each_language_is_recognised(self) -> None:
        self.assertEqual(interactive.language_of(FRENCH), "fr")
        self.assertEqual(interactive.language_of(SPANISH), "es")
        self.assertEqual(interactive.language_of(RUSSIAN), "ru")
        self.assertEqual(interactive.language_of("status"), "en")

    def test_a_french_elision_is_recognised(self) -> None:
        self.assertEqual(interactive.language_of("l'\u00e9tat de la t\u00e2che"), "fr")

    def test_a_message_without_a_signal_keeps_the_current_language(self) -> None:
        self.assertEqual(interactive.language_of("123", "fr"), "fr")
        self.assertEqual(interactive.language_of("t-1", "es"), "es")
        self.assertEqual(interactive.language_of("?!", "ru"), "ru")

    def test_a_fresh_session_starts_in_english(self) -> None:
        self.assertEqual(interactive.language_of("123"), "en")

    def test_diacritics_case_and_whitespace_carry_no_meaning(self) -> None:
        self.assertEqual(
            interactive._fold("  CR\u00c9E   un  Projet  "), "cree un projet"
        )
        self.assertEqual(
            interactive._fold("cambiar la configuraci\u00f3n"),
            "cambiar la configuracion",
        )


class SensitiveDetectionTest(unittest.TestCase):
    """The sensitive explicit actions are refused in every accepted language."""

    def test_french_phrasings_are_sensitive(self) -> None:
        for phrase in FRENCH_SENSITIVE:
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "sensitive")

    def test_spanish_phrasings_are_sensitive(self) -> None:
        for phrase in SPANISH_SENSITIVE:
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "sensitive")

    def test_english_and_russian_phrasings_keep_their_result(self) -> None:
        for phrase in (
            "adopt this repository",
            "create a project",
            "set the api key",
            "change the settings",
            "\u0441\u043e\u0437\u0434\u0430\u0439 \u043f\u0440\u043e\u0435\u043a\u0442",
            "\u043f\u043e\u043c\u0435\u043d\u044f\u0439 \u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446\u0438\u044e",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "sensitive")

    def test_ordinary_french_and_spanish_stay_free_text(self) -> None:
        for phrase in ORDINARY:
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "say")


class SensitiveRefusalTest(LocalizationCase):
    def test_a_refused_request_is_answered_and_passes_nothing_onward(self) -> None:
        refusals = tuple(interactive.MESSAGES["sensitive"].values())
        for phrase in REFUSED:
            with self.subTest(phrase=phrase):
                self.log.unlink(missing_ok=True)
                _, text = self.run_session([phrase])
                self.assertTrue(any(value in text for value in refusals), text)
                for call in self.calls():
                    self.assertNotEqual(call[0], "say")
                    self.assertNotEqual(call[0], "use")
                    self.assertNotEqual(call[0], "task")
                    self.assertNotIn(phrase, " ".join(call))

    def test_a_french_refusal_reads_in_the_existing_style(self) -> None:
        _, text = self.run_session(["cr\u00e9e un projet"])
        reply = self.reply_of_first_message(text)
        self.assertIn(interactive.MESSAGES["sensitive"]["fr"], reply)

    def test_a_spanish_refusal_reads_in_the_existing_style(self) -> None:
        _, text = self.run_session(["\u00bfpuedo crear un proyecto?"])
        reply = self.reply_of_first_message(text)
        self.assertIn(interactive.MESSAGES["sensitive"]["es"], reply)

    def test_ordinary_french_and_spanish_reach_the_engine_unchanged(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        for phrase in ORDINARY:
            with self.subTest(phrase=phrase):
                self.log.unlink(missing_ok=True)
                _, text = self.run_session([phrase])
                self.assertIn("echo: " + phrase, text)
                self.assertIn(["say", "--text", phrase, "--json"], self.calls())


class WordingSetTest(unittest.TestCase):
    def test_the_four_languages_carry_the_same_sentences(self) -> None:
        languages = {"en", "ru", "fr", "es"}
        self.assertTrue(interactive.MESSAGES)
        for key, entry in interactive.MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(set(entry), languages)
                for language, value in entry.items():
                    self.assertTrue(value.strip(), (key, language))

    def test_a_missing_language_is_never_filled_from_another(self) -> None:
        # A sentence is looked up in the current language only: there is no
        # fallback that would quietly borrow another language's wording.
        for key in interactive.MESSAGES:
            with self.subTest(key=key):
                with self.assertRaises(KeyError):
                    interactive._message(key, "de")


class OwnerLanguageTest(LocalizationCase):
    def test_a_french_message_composes_every_sentence_in_french(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        _, text = self.run_session([FRENCH])
        reply = self.reply_of_first_message(text)
        self.assert_wording(reply, FRENCH_WORDING)
        self.assert_no_wording(reply, ENGLISH_WORDING)
        # The engine's answer to that message is shown, and the engine received
        # the owner's sentence unaltered.
        self.assertIn("echo: " + FRENCH, reply)
        self.assertIn(["say", "--text", FRENCH, "--json"], self.calls())

    def test_a_spanish_message_composes_every_sentence_in_spanish(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        _, text = self.run_session([SPANISH])
        reply = self.reply_of_first_message(text)
        self.assert_wording(reply, SPANISH_WORDING)
        self.assert_no_wording(reply, ENGLISH_WORDING)
        self.assertIn("echo: " + SPANISH, reply)

    def test_a_russian_message_reaches_the_engine_unaltered(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        _, text = self.run_session([RUSSIAN])
        reply = self.reply_of_first_message(text)
        self.assert_wording(reply, RUSSIAN_WORDING)
        self.assertIn(["say", "--text", RUSSIAN, "--json"], self.calls())
        self.assertIn("echo: " + RUSSIAN, reply)

    def test_an_english_message_keeps_every_sentence_english(self) -> None:
        _, text = self.run_session(["status"])
        self.assert_wording(text, ENGLISH_WORDING)

    def test_a_message_without_letters_keeps_the_current_language(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        _, text = self.run_session([FRENCH, "123"])
        after = text[text.index("echo: 123"):]
        self.assert_wording(
            after, ("projet :", "t\u00e2ches :", "session termin\u00e9e")
        )
        self.assert_no_wording(after, ENGLISH_WORDING)

    def test_a_later_message_in_another_language_moves_the_session(self) -> None:
        self.env["SESSION_STUB_ECHO"] = "1"
        _, text = self.run_session(["status", FRENCH])
        french = text.index("echo: bonjour")
        self.assert_no_wording(text[:french], FRENCH_WORDING)
        self.assert_wording(text[french:], FRENCH_WORDING)
        self.assert_no_wording(text[french:], ENGLISH_WORDING)

    def test_following_replies_stay_in_the_signalled_language(self) -> None:
        _, text = self.run_session([FRENCH, "merci, montre les t\u00e2ches"])
        french = text.index("projet :")
        self.assert_wording(text[french:], FRENCH_WORDING)
        self.assert_no_wording(text[french:], ENGLISH_WORDING)

    def test_engine_values_are_shown_as_the_engine_reported_them(self) -> None:
        _, text = self.run_session([FRENCH])
        for value in ("t-1", "t-2", "ready", "done", "0.1.1", "open"):
            with self.subTest(value=value):
                self.assertIn(value, text)


class FailureFramingTest(LocalizationCase):
    def test_a_french_failure_is_framed_in_french_and_quotes_the_engine(self) -> None:
        self.env["SESSION_STUB_FAIL_SAY"] = "1"
        raw = "the engine refused the request in its own words"
        _, text = self.run_session([FRENCH])
        reply = self.reply_of_first_message(text)
        self.assertIn("\u00e9chec :", reply)
        self.assertIn("le moteur a r\u00e9pondu : \u00ab ", reply)
        self.assertIn("\u00e9tape suivante :", reply)
        self.assert_no_wording(reply, ("failed:", "the engine said:", "next step:"))
        # The engine's own words appear only inside the attributed quotation.
        quoted = [line for line in reply.splitlines() if raw in line]
        self.assertEqual(len(quoted), 1, reply)
        self.assertTrue(quoted[0].startswith("le moteur a r\u00e9pondu : \u00ab "))


if __name__ == "__main__":
    unittest.main()
