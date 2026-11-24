"""The session refreshes task and release state on its own while the owner waits.

The supplying side of the input stays silent for the whole observation, so the
refresh is proven by the engine's reported state changing without a sentence.
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
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forgel_code import interactive  # noqa: E402
from forgel_code.engine import Engine  # noqa: E402
from forgel_code.session import Session  # noqa: E402

# The stand-in engine reads its task and release state from a file the test
# changes while the session waits, so a change is visible without any input.
# ``IDLE_STUB_FAIL`` names a marker: while it exists the state commands fail.
STUB_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys

    argv = sys.argv[1:]
    if not argv:
        sys.stdout.write(json.dumps({"ok": True}) + chr(10))
        raise SystemExit(0)
    log = os.environ.get("IDLE_STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv, ensure_ascii=False) + chr(10))
    command = argv[0]
    fail = os.environ.get("IDLE_STUB_FAIL")
    if command in ("tasks", "status") and fail and os.path.exists(fail):
        sys.stderr.write("the engine is down" + chr(10))
        raise SystemExit(3)
    if command == "say":
        payload = {"ok": True, "reply": "the agent answered"}
    else:
        with open(os.environ["IDLE_STUB_STATE"], encoding="utf-8") as handle:
            payload = json.load(handle)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + chr(10))
    sys.stdout.flush()
    """
)

STATE_ONE = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "ready", "title": "add a login screen"},
        {"id": "t-2", "state": "done", "title": "write the docs"},
    ],
    "release": {"version": "0.1.1", "state": "open"},
}

STATE_TWO = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "done", "title": "add a login screen"},
        {"id": "t-2", "state": "done", "title": "write the docs"},
    ],
    "release": {"version": "0.1.2", "state": "closed"},
}

STATE_THREE = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "done", "title": "add a login screen"},
        {"id": "t-9", "state": "planned", "title": "show the release"},
    ],
    "release": {"version": "0.2.0", "state": "open"},
}


def _write_engine(directory: Path) -> Path:
    script = directory / "idle_stub.py"
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


def wait_for(predicate, timeout: float = 20.0, interval: float = 0.05) -> bool:
    """Wait until ``predicate`` holds; the engine calls are real processes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class RecordingOutput(io.StringIO):
    """Output a test can read while the session thread keeps writing."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            return super().write(text)

    def getvalue(self) -> str:
        with self._lock:
            return super().getvalue()


class IdleCase(unittest.TestCase):
    """A session whose input supplies no sentence until the test types one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.engine_path = _write_engine(self.bin_dir)
        self.state_file = self.home / "state.json"
        self.log = self.home / "argv.log"
        self.fail_marker = self.home / "engine-down"
        self.store = Session(self.home / "session" / "session.json")
        self.env = dict(os.environ)
        self.env["IDLE_STUB_STATE"] = str(self.state_file)
        self.env["IDLE_STUB_LOG"] = str(self.log)
        self.env["IDLE_STUB_FAIL"] = str(self.fail_marker)
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")

    def set_state(self, state) -> None:
        temporary = self.state_file.with_name("state.json.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, self.state_file)

    def calls(self):
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def start(self):
        """Run the session in a thread; its input waits for the test."""
        read_fd, self.write_fd = os.pipe()
        reader = os.fdopen(read_fd, "r", encoding="utf-8")
        self.out = RecordingOutput()
        session = interactive.InteractiveSession(
            Engine(str(self.engine_path), 30),
            self.store,
            self.out,
            reader,
        )
        self.code = []
        previous = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        thread = threading.Thread(
            target=lambda: self.code.append(session.run()), daemon=True
        )
        thread.start()

        def stop() -> None:
            self.end_input()
            thread.join(30)
            reader.close()
            os.environ.clear()
            os.environ.update(previous)

        self.addCleanup(stop)
        return session, thread

    def type(self, text: str) -> None:
        os.write(self.write_fd, text.encode("utf-8"))

    def end_input(self) -> None:
        if self.write_fd is not None:
            os.close(self.write_fd)
            self.write_fd = None

    def wait_for_exit(self, thread) -> int:
        self.end_input()
        thread.join(30)
        self.assertFalse(thread.is_alive(), "the session did not end on end of input")
        self.assertTrue(self.code, "the session thread produced no outcome")
        return self.code[0]


class IdleRefreshTest(IdleCase):
    def test_changes_while_the_owner_waits_show_without_a_sentence(self) -> None:
        self.set_state(STATE_ONE)
        _, thread = self.start()
        output = self.out.getvalue
        self.assertTrue(
            wait_for(lambda: "release: 0.1.1 open" in output()),
            "the first state never appeared: %r" % output(),
        )

        # The supplying side stays silent; the engine's state changes twice.
        self.set_state(STATE_TWO)
        self.assertTrue(
            wait_for(lambda: "release: 0.1.2 closed" in output()),
            "the first idle change never appeared: %r" % output(),
        )
        first = output().index("release: 0.1.2 closed")

        self.set_state(STATE_THREE)
        self.assertTrue(
            wait_for(lambda: "t-9  planned" in output()),
            "the second idle change never appeared: %r" % output(),
        )
        second = output().index("t-9  planned")

        self.assertLess(first, second)
        self.assertIn("release: 0.2.0 open", output())
        self.assertEqual(
            [call for call in self.calls() if call and call[0] == "say"],
            [],
            "an idle refresh must not depend on a sentence",
        )

        # A sentence half typed survives a refresh that happens meanwhile.
        self.type("sta")
        time.sleep(1.0)
        self.set_state(STATE_ONE)
        self.assertTrue(
            wait_for(lambda: output().count("release: 0.1.1 open") == 2),
            "the refresh did not run while the owner was typing: %r" % output(),
        )
        self.type("tus\n")
        self.assertTrue(
            wait_for(lambda: "the agent answered" in output()),
            "the typed sentence never reached the engine: %r" % output(),
        )

        code = self.wait_for_exit(thread)
        self.assertEqual(code, 0)
        self.assertIn("session ended", output())
        self.assertIn(["say", "--text", "status", "--json"], self.calls())

    def test_an_unchanged_state_is_not_repeated_while_the_owner_waits(self) -> None:
        self.set_state(STATE_ONE)
        _, thread = self.start()
        output = self.out.getvalue
        self.assertTrue(wait_for(lambda: "release: 0.1.1 open" in output()))

        before = len(self.calls())
        time.sleep(3.0)
        after = len(self.calls())
        text = output()
        self.assertEqual(text.count("release: 0.1.1 open"), 1)
        self.assertEqual(text.count("tasks:"), 1)
        self.assertEqual(text.count("t-1"), 1)
        self.assertGreater(
            after - before, 2, "the idle refresh did not keep reading the state"
        )
        self.assertEqual(self.wait_for_exit(thread), 0)
        self.assertIn("session ended", output())

    def test_an_engine_failure_while_idle_keeps_the_session_usable(self) -> None:
        self.set_state(STATE_ONE)
        self.fail_marker.write_text("down", encoding="utf-8")
        _, thread = self.start()
        output = self.out.getvalue
        self.assertTrue(
            wait_for(lambda: "the engine is down" in output()),
            "the idle failure was never stated: %r" % output(),
        )
        self.assertIn("failed:", output())
        self.assertIn("next step:", output())

        self.type("status\n")
        self.assertTrue(
            wait_for(lambda: "the agent answered" in output()),
            "the session stopped answering after an idle failure: %r" % output(),
        )
        code = self.wait_for_exit(thread)
        self.assertEqual(code, 0)
        self.assertIn("session ended", output())
        self.assertIn(["say", "--text", "status", "--json"], self.calls())

    def test_input_that_ends_at_once_still_prompts_and_ends_cleanly(self) -> None:
        self.set_state(STATE_ONE)
        _, thread = self.start()
        code = self.wait_for_exit(thread)
        text = self.out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(interactive.PROMPT, text)
        self.assertIn("session ended", text)


if __name__ == "__main__":
    unittest.main()
