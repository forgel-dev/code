"""The interactive session of the client, against a stand-in engine."""

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

# The stand-in answers like the engine's machine-readable form: one JSON object
# per call. ``say`` answers with a reply, ``plan`` with planned tasks, and
# ``use`` can refuse a project. Every argv is appended to ``SESSION_STUB_LOG``.
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
    if command == "version":
        payload = {"ok": True, "engine": {"name": "forgel", "version": "0.1.1"}}
    elif command == "say":
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
        {"id": "t-3", "state": "failed", "title": "ship it"},
    ],
    "release": {"version": "0.1.1", "state": "open"},
}


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


class InteractiveCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.engine_path = _write_engine(self.bin_dir)
        self.log = self.home / "argv.log"
        self.session_file = self.home / "session" / "session.json"
        self.store = Session(self.session_file)
        self.env = dict(os.environ)
        self.env["SESSION_STUB_PAYLOAD"] = json.dumps(STATE)
        self.env["SESSION_STUB_LOG"] = str(self.log)
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        self.env["FORGEL_ENGINE"] = str(self.engine_path)
        self.env.pop("SESSION_STUB_REJECT_USE", None)

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

    def task_calls(self):
        return [call for call in self.calls() if call and call[0] == "task"]


class BareStartTest(InteractiveCase):
    def test_no_arguments_shows_a_prompt_and_keeps_the_session_open(self) -> None:
        from forgel_code.cli import main

        out = io.StringIO()
        old_stdout, old_stdin = sys.stdout, sys.stdin
        old_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        try:
            sys.stdout = out
            sys.stdin = io.StringIO("")
            code = main([])
        finally:
            sys.stdout, sys.stdin = old_stdout, old_stdin
            os.environ.clear()
            os.environ.update(old_env)
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(interactive.PROMPT, text)
        self.assertIn("session ended", text)
        self.assertNotIn("usage:", text.lower())

    def test_help_still_prints_help(self) -> None:
        from forgel_code.cli import main

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            code = main(["--help"])
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("say", out.getvalue())
        self.assertNotIn(interactive.PROMPT, out.getvalue())


class SessionFlowTest(InteractiveCase):
    def test_the_selected_project_is_shown(self) -> None:
        self.store.save_project("acme")
        _, text = self.run_session([])
        self.assertIn("project: acme", text)

    def test_a_phrase_is_answered_and_the_session_stays_open(self) -> None:
        code, text = self.run_session(["please look at the release", "status"])
        self.assertEqual(code, 0)
        self.assertIn("the agent answered", text)
        self.assertIn("t-1", text)
        self.assertGreaterEqual(len(self.calls()), 3)

    def test_a_plan_is_shown_in_plan_order_with_states(self) -> None:
        _, text = self.run_session(["plan ship v1"])
        self.assertIn("plan:", text)
        self.assertLess(text.index("first"), text.index("second"))
        self.assertIn("planned", text)
        self.assertIn(["plan", "--goal", "ship v1", "--json"], self.calls())

    def test_a_task_is_shown_with_its_title_and_state(self) -> None:
        _, text = self.run_session(["status"])
        self.assertIn("t-1", text)
        self.assertIn("ready", text)
        self.assertIn("t-2", text)
        self.assertIn("done", text)

    def test_task_and_release_state_refresh_without_being_asked(self) -> None:
        _, text = self.run_session(["", ""])
        self.assertIn("tasks:", text)
        self.assertIn("release: 0.1.1 open", text)

    def test_accept_and_rework_reach_the_engine(self) -> None:
        self.run_session(["accept t-2", "rework t-1 the button is dead"])
        task_calls = self.task_calls()
        self.assertIn(["task", "accept", "--task", "t-2", "--json"], task_calls)
        self.assertIn(
            [
                "task",
                "reject",
                "--task",
                "t-1",
                "--notes",
                "the button is dead",
                "--json",
            ],
            task_calls,
        )

    def test_retry_pause_and_resume_reach_the_engine(self) -> None:
        self.run_session(["retry t-3", "pause", "resume"])
        calls = self.calls()
        self.assertIn(["task", "retry", "--task", "t-3", "--json"], calls)
        self.assertIn(["pause", "--json"], calls)
        self.assertIn(["resume", "--json"], calls)

    def test_switching_project_applies_to_later_requests(self) -> None:
        _, text = self.run_session(["switch the project to acme", "status"])
        self.assertIn("project: acme", text)
        calls = self.calls()
        self.assertIn(["use", "acme", "--json"], calls)
        later = [
            call
            for call in calls[calls.index(["use", "acme", "--json"]) + 1:]
            if call and call[0] in ("say", "tasks", "status")
        ]
        self.assertTrue(later)
        for call in later:
            self.assertIn("--project", call)
            self.assertIn("acme", call)

    def test_a_refused_switch_keeps_the_previous_project(self) -> None:
        self.env["SESSION_STUB_REJECT_USE"] = "1"
        _, text = self.run_session(["switch the project to ghost"])
        self.assertFalse(self.store.selected())
        self.assertIn("unknown_project", text)


class FailureTest(InteractiveCase):
    def test_a_failure_shows_the_cause_and_the_next_step(self) -> None:
        self.env["SESSION_STUB_REJECT_USE"] = "1"
        _, text = self.run_session(["switch the project to ghost"])
        self.assertIn("failed:", text)
        self.assertIn("unknown_project", text)
        self.assertIn("next step:", text)

    def test_the_session_stays_usable_after_a_failure(self) -> None:
        self.env["SESSION_STUB_REJECT_USE"] = "1"
        code, text = self.run_session(["switch the project to ghost", "status"])
        self.assertEqual(code, 0)
        self.assertIn("failed:", text)
        self.assertIn("t-1", text)


class ClarifyTest(InteractiveCase):
    def test_several_matching_actions_ask_for_clarification(self) -> None:
        _, text = self.run_session(["accept and rework t-1"])
        self.assertIn("more than one action", text)

    def test_an_ambiguous_request_performs_no_action(self) -> None:
        self.run_session(["accept t-1 and retry t-2"])
        self.assertEqual(self.task_calls(), [])

    def test_a_task_without_an_action_asks_for_clarification(self) -> None:
        _, text = self.run_session(["t-1"])
        self.assertIn("no action", text)

    def test_an_action_without_a_task_asks_for_a_task(self) -> None:
        _, text = self.run_session(["accept it please"])
        self.assertIn("names no task", text)
        self.assertEqual(self.task_calls(), [])

    def test_a_send_back_without_remarks_asks_for_remarks(self) -> None:
        _, text = self.run_session(["rework t-1"])
        self.assertIn("carries no remarks", text)
        self.assertEqual(self.task_calls(), [])


class SensitiveTest(InteractiveCase):
    def test_sensitive_intents_are_never_carried_out(self) -> None:
        for phrase in (
            "adopt the repository acme",
            "create a project acme",
            "set the secret token abc123",
            "change the configuration",
        ):
            with self.subTest(phrase=phrase):
                self.log.unlink(missing_ok=True)
                _, text = self.run_session([phrase])
                self.assertIn("explicit separate", text)
                for call in self.calls():
                    self.assertNotEqual(call[0], "use")
                    self.assertNotEqual(call[0], "task")


class SecretTest(InteractiveCase):
    def test_key_material_is_redacted(self) -> None:
        self.assertEqual(interactive.redact("password: hunter2"), "password: [redacted]")
        self.assertEqual(interactive.redact("token abc"), "token [redacted]")

    def test_a_secret_never_reaches_the_screen(self) -> None:
        _, text = self.run_session(["my token is abc123"])
        self.assertNotIn("abc123", text)

    def test_the_session_keeps_no_transcript(self) -> None:
        self.run_session(["my token is abc123", "status"])
        for path in self.home.rglob("*"):
            if not path.is_file() or path in (self.log, self.engine_path):
                continue
            if path.suffix == ".py":
                continue
            self.assertNotIn("abc123", path.read_text(encoding="utf-8", errors="ignore"))


class LanguageTest(InteractiveCase):
    def test_a_russian_message_gets_a_russian_reply(self) -> None:
        _, text = self.run_session(["привет, что по релизу?"])
        self.assertIn("проект:", text)
        self.assertIn("задачи:", text)

    def test_leaving_in_russian_ends_the_session(self) -> None:
        _, text = self.run_session(["выход", "status"])
        self.assertIn("сеанс завершён", text)


class LeaveTest(InteractiveCase):
    def test_leaving_ends_the_session_immediately(self) -> None:
        code, text = self.run_session(["quit", "status"])
        self.assertEqual(code, 0)
        self.assertIn("session ended", text)
        # Only the state refresh ran; ``status`` after ``quit`` never reached the
        # engine as a request of its own.
        self.assertEqual([call for call in self.calls() if call[0] == "say"], [])
        self.assertEqual(self.task_calls(), [])

    def test_the_end_of_input_ends_the_session(self) -> None:
        code, text = self.run_session([])
        self.assertEqual(code, 0)
        self.assertIn("session ended", text)

    def test_no_request_continues_after_leaving(self) -> None:
        session = interactive.InteractiveSession(
            Engine(str(self.engine_path), 30),
            self.store,
            io.StringIO(),
            io.StringIO(""),
        )
        self.assertEqual(session.handle("quit"), "leave")
        session.stopped = True
        self.assertIsNone(session.call(["status"]))


class ResolveTest(unittest.TestCase):
    def test_a_plain_sentence_is_a_free_request(self) -> None:
        self.assertEqual(
            interactive.resolve("what is left in the milestone?")["kind"], "say"
        )

    def test_accept_names_the_task(self) -> None:
        intent = interactive.resolve("accept t-7")
        self.assertEqual(intent["kind"], "action")
        self.assertEqual(intent["action"], "accept")
        self.assertEqual(intent["task"], "t-7")

    def test_sending_back_carries_the_remarks(self) -> None:
        intent = interactive.resolve("send t-7 back for rework with remarks: no tests")
        self.assertEqual(intent["kind"], "action")
        self.assertEqual(intent["action"], "rework")
        self.assertEqual(intent["task"], "t-7")
        self.assertIn("no tests", intent["remarks"])

    def test_switching_names_the_project(self) -> None:
        self.assertEqual(
            interactive.resolve("switch to acme"),
            {"kind": "switch", "key": "acme"},
        )

    def test_switching_without_a_key_asks_for_one(self) -> None:
        self.assertEqual(interactive.resolve("switch to")["reason"], "clarify_project")

    def test_leaving_is_recognised(self) -> None:
        self.assertEqual(interactive.resolve("leave")["kind"], "leave")
        self.assertEqual(interactive.resolve("пока")["kind"], "leave")

    def test_sensitive_intents_are_recognised(self) -> None:
        for phrase in (
            "adopt this repository",
            "create a project",
            "set the api key",
            "change the settings",
            "создай проект",
            "поменяй конфигурацию",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(interactive.resolve(phrase)["kind"], "sensitive")


class ThinClientTest(unittest.TestCase):
    def test_the_session_does_not_call_a_model_or_read_project_files(self) -> None:
        source = (ROOT / "forgel_code" / "interactive.py").read_text(encoding="utf-8")
        for forbidden in ("import forgel\n", "from forgel import"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("open(", source)


class OneShotUnchangedTest(InteractiveCase):
    def run_one_shot(self, *args):
        import contextlib

        from forgel_code.cli import main

        out, err = io.StringIO(), io.StringIO()
        old_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(list(args) + ["--engine", str(self.engine_path)])
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        return code, out.getvalue(), err.getvalue()

    def test_one_shot_output_and_exit_status_are_unchanged(self) -> None:
        code, out, err = self.run_one_shot("status")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("t-1", out)
        self.assertNotIn(interactive.PROMPT, out)

    def test_the_machine_readable_form_is_unchanged(self) -> None:
        code, out, err = self.run_one_shot("status", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "status")
        self.assertEqual(payload["result"], STATE)
        self.assertEqual(out.strip().count("\n"), 0)


if __name__ == "__main__":
    unittest.main()
