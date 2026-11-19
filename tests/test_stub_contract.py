"""Exercise the deterministic engine stub from the dependency contract.

The stub (``tests/stub_engine.py``) is the authoritative fake for the engine's
``forgel <command> --json`` protocol: one JSON object on stdout, the active
project as ``--project <key>``, ``ok: false`` for failures and exit code 2 plus
``code: unsupported_command`` for an unsupported command. These tests run it as
a child process, exactly as the client does, and never import it.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUB = Path(__file__).resolve().parent / "stub_engine.py"
sys.path.insert(0, str(ROOT))

# Every project-scoped command from R1 with the client argv that reaches the
# engine. ``task`` also needs a task listing, which the canned output supplies.
PROJECT_CASES = [
    (("say", "add a login screen"), None),
    (("status",), None),
    (("tasks",), None),
    (("task", "t-1"), {"ok": True, "tasks": [{"id": "t-1", "state": "ready"}]}),
    (("accept", "t-1"), None),
    (("rework", "t-1", "the button is dead"), None),
    (("resume",), None),
    (("pause",), None),
    (("plan", "ship v1"), None),
    (("history",), None),
    (("projects",), None),
    (("session",), None),
]


class StubContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.log = self.home / "argv.log"

        self.env = dict(os.environ)
        for name in (
            "FORGEL_STUB_STDOUT",
            "FORGEL_STUB_EXIT",
            "FORGEL_STUB_SLEEP",
            "FORGEL_CODE_TIMEOUT",
            "FORGEL_ENGINE",
        ):
            self.env.pop(name, None)
        self.session_path = self.home / "session" / "session.json"
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        self.launcher = self._write_launcher()
        self.env["FORGEL_ENGINE"] = str(self.launcher)
        self.env["FORGEL_STUB_LOG"] = str(self.log)

    def _write_launcher(self) -> Path:
        launcher = self.home / "forgel"
        launcher.write_text(
            "#!/bin/sh\nexec %s %s \"$@\"\n"
            % (shlex.quote(sys.executable), shlex.quote(str(STUB))),
            encoding="utf-8",
        )
        launcher.chmod(
            launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return launcher

    def run_client(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "forgel_code", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

    def select_project(self, key: str) -> None:
        """Record a selected project the way ``forgel-code use`` does."""
        from forgel_code.session import Session

        Session(self.session_path).save_project(key)

    def recorded_argv(self):
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_the_selected_key_reaches_every_scoped_command(self) -> None:
        self.select_project("acme")
        for args, canned in PROJECT_CASES:
            with self.subTest(command=args[0]):
                self.log.unlink(missing_ok=True)
                if canned is None:
                    self.env.pop("FORGEL_STUB_STDOUT", None)
                else:
                    self.env["FORGEL_STUB_STDOUT"] = json.dumps(canned)
                completed = self.run_client(*args)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                argv = self.recorded_argv()[-1]
                index = argv.index("--project")
                self.assertEqual(argv[index + 1], "acme", argv)

    def test_no_default_project_key_is_sent_without_use(self) -> None:
        for args, canned in PROJECT_CASES:
            with self.subTest(command=args[0]):
                self.log.unlink(missing_ok=True)
                if canned is None:
                    self.env.pop("FORGEL_STUB_STDOUT", None)
                else:
                    self.env["FORGEL_STUB_STDOUT"] = json.dumps(canned)
                self.run_client(*args)
                argv = self.recorded_argv()[-1]
                self.assertNotIn("--project", argv)
                self.assertNotIn("local", argv)

    def test_ok_false_with_exit_zero_is_a_failure(self) -> None:
        self.env["FORGEL_STUB_STDOUT"] = json.dumps(
            {
                "ok": False,
                "error": {"code": "task_closed", "message": "already closed"},
            }
        )
        completed = self.run_client("status", "--json")

        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["engine_error"]["code"], "task_closed")

    def test_unsupported_command_is_a_structured_signal(self) -> None:
        completed = subprocess.run(
            [str(self.launcher), "no-such-command", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "unsupported_command")


if __name__ == "__main__":
    unittest.main()
