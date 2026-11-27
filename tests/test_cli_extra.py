"""End-to-end checks the in-process suite does not cover.

Every test here runs ``python -m forgel_code`` as a real process against a
small fake engine, so the assertions see exactly what a user gets: the exit
code, stdout and stderr. The fake engine records the argv it received, can
sleep past the client's limit and can answer with a structured error.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys
    import time

    argv = sys.argv[1:]
    log = os.environ.get("FAKE_ENGINE_LOG")
    if log:
        with open(log, "w", encoding="utf-8") as handle:
            json.dump(argv, handle)

    if argv[:1] == ["version"]:
        sys.stdout.write(
            json.dumps({"ok": True, "engine": {"name": "fake", "version": "1.0.0"}})
            + chr(10)
        )
        sys.stdout.flush()
        raise SystemExit(0)

    sleep = os.environ.get("FAKE_ENGINE_SLEEP")
    if sleep:
        time.sleep(float(sleep))

    mode = os.environ.get("FAKE_ENGINE_MODE", "ok")
    if mode == "error-exit3":
        sys.stderr.write("engine refused: task is already closed" + chr(10))
        raise SystemExit(3)

    if mode == "structured-exit2":
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": {"code": "validation", "message": "bad goal"}}
            )
            + chr(10)
        )
        sys.stdout.flush()
        raise SystemExit(2)

    sys.stdout.write(
        json.dumps({"ok": True, "args": argv}, ensure_ascii=False) + chr(10)
    )
    sys.stdout.flush()
    """
)


class ClientProcessTest(unittest.TestCase):
    """Run the client as a child process against the fake engine."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.engine_log = self.home / "argv.json"
        self.engine = self._write_engine()

        self.env = dict(os.environ)
        for name in (
            "FORGEL_CODE_TIMEOUT",
            "FAKE_ENGINE_MODE",
            "FAKE_ENGINE_SLEEP",
            "FORGEL_STUB_MODE",
        ):
            self.env.pop(name, None)
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        self.env["FORGEL_ENGINE"] = str(self.engine)
        self.env["FAKE_ENGINE_LOG"] = str(self.engine_log)

    def _write_engine(self) -> Path:
        script = self.home / "fake_engine.py"
        script.write_text(FAKE_ENGINE, encoding="utf-8")
        launcher = self.home / "forgel"
        launcher.write_text(
            '#!/bin/sh\nexec %s %s "$@"\n'
            % (shlex.quote(sys.executable), shlex.quote(str(script))),
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

    def engine_argv(self):
        return json.loads(self.engine_log.read_text(encoding="utf-8"))


class CliSmokeTests(ClientProcessTest):
    """AC-2: ``--help`` and ``--version`` exit 0."""

    def test_help_exits_zero_and_lists_the_commands(self) -> None:
        completed = self.run_client("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for command in ("say", "status", "tasks", "use"):
            self.assertIn(command, completed.stdout)

    def test_version_exits_zero(self) -> None:
        from forgel_code import __version__

        completed = self.run_client("--version")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "forgel-code %s" % __version__)


class ExactPhraseTest(ClientProcessTest):
    """AC-8: flag-like words inside a phrase are not swallowed."""

    def test_the_task_example_phrase_reaches_the_engine_unchanged(self) -> None:
        phrase = "добавь флаг --json"
        completed = self.run_client("say", phrase)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.engine_argv(), ["say", "--text", phrase, "--json"]
        )

    def test_a_remark_that_starts_with_a_hyphen_is_kept(self) -> None:
        remark = "--notes не тот"
        completed = self.run_client("rework", "t-1", remark)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.engine_argv(),
            ["task", "reject", "--task", "t-1", "--notes", remark, "--json"],
        )


class TimeoutBoundTest(ClientProcessTest):
    """AC-5: the client returns within the limit plus a margin."""

    def test_client_returns_within_the_limit_plus_a_margin(self) -> None:
        self.env["FAKE_ENGINE_SLEEP"] = "5"
        started = time.monotonic()
        completed = self.run_client("--timeout", "0.3", "status", "--json")
        elapsed = time.monotonic() - started

        self.assertNotEqual(completed.returncode, 0)
        self.assertLess(elapsed, 0.3 + 2.0, elapsed)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("timed out", payload["error"])


class StructuredErrorPassthroughTest(ClientProcessTest):
    """AC-6: a non-zero exit with an error object delivers its fields."""

    def test_non_zero_exit_error_object_fields_are_delivered(self) -> None:
        self.env["FAKE_ENGINE_MODE"] = "structured-exit2"
        completed = self.run_client("status", "--json")

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.count("\n"), 1, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["engine_error"]["code"], "validation")
        self.assertEqual(payload["engine_error"]["message"], "bad goal")
        self.assertIn("validation", payload["error"])
        self.assertIn("bad goal", payload["error"])

    def test_the_human_channel_shows_the_same_fields(self) -> None:
        self.env["FAKE_ENGINE_MODE"] = "structured-exit2"
        completed = self.run_client("status")

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("validation", completed.stderr)
        self.assertIn("bad goal", completed.stderr)


class EngineIdentityTest(ClientProcessTest):
    """AC-6/R12: a failure names the engine that answered."""

    def test_failure_names_the_engine_that_answered(self) -> None:
        self.env["FAKE_ENGINE_MODE"] = "error-exit3"
        completed = self.run_client("status")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(str(self.engine), completed.stderr)
        self.assertIn("engine refused", completed.stderr)

    def test_timeout_names_the_engine(self) -> None:
        self.env["FAKE_ENGINE_SLEEP"] = "5"
        completed = self.run_client("--timeout", "0.3", "status")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(str(self.engine), completed.stderr)


if __name__ == "__main__":
    unittest.main()
