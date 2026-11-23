"""Tests for the ``forgel-code`` client against a stand-in engine."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "forgel_code"

sys.path.insert(0, str(ROOT))

# The stub mirrors the real engine's ``task`` parser: the action is a required
# positional argument (``accept``/``reject``/...), the option set is fixed and
# ``--accept`` is an option that takes a value. A client that invents
# ``--reason`` or calls ``forgel task --accept --task X`` therefore fails here
# exactly as it fails against the engine.
#
# ``FORGEL_STUB_MODE`` models the engine shapes the client must handle:
#   * ``error``               - plain failure, exit 3, text on stderr;
#   * ``structured-error``    - ``{"ok": false, "error": {...}}`` with exit 0;
#   * ``structured-error-string`` - the same with a string ``error``;
#   * ``no-task-action``      - no ``task`` command at all (exit 2, text);
#   * ``no-task-action-ru``   - the same with a non-English message;
#   * ``no-task-accept``      - ``task`` exists but has no ``accept`` action;
#   * ``usage-other``         - exit 2 with a structured non-usage error;
#   * ``noisy``               - a log line with ``{`` before the JSON answer;
#   * ``garbage``             - output with no decodable JSON object;
#   * ``non-ascii``           - UTF-8 text in the answer;
#   * ``stdin``               - records whatever arrives on stdin;
#   * ``sleep``               - never answers before the timeout.
STUB_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys
    import time

    argv = sys.argv[1:]
    with open(os.environ["FORGEL_STUB_ARGV"], "w", encoding="utf-8") as handle:
        json.dump(argv, handle)

    mode = os.environ.get("FORGEL_STUB_MODE", "ok")


    def emit(payload, code=0):
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.write(chr(10))
        sys.stdout.flush()
        sys.exit(code)


    if mode == "sleep":
        time.sleep(float(os.environ.get("FORGEL_STUB_SLEEP", "10")))
        emit({"ok": True})

    if mode == "stdin":
        data = sys.stdin.buffer.read()
        with open(os.environ["FORGEL_STUB_STDIN"], "wb") as handle:
            handle.write(data)
        emit({"ok": True, "stdin_bytes": len(data)})

    if mode == "non-ascii":
        emit({"ok": True, "text": "Привет, мир"})

    if mode == "noisy":
        sys.stdout.write("log line with a brace { and no json here")
        sys.stdout.write(chr(10))
        emit(json.loads(os.environ["FORGEL_STUB_PAYLOAD"]))

    if mode == "garbage":
        sys.stdout.write("engine fell over before answering: {broken")
        sys.stdout.write(chr(10))
        sys.exit(0)

    if mode == "structured-error":
        emit(
            {
                "ok": False,
                "error": {
                    "code": "task_closed",
                    "kind": "conflict",
                    "message": "task is already closed",
                },
            },
            0,
        )

    if mode == "structured-error-string":
        emit({"ok": False, "error": "the milestone is missing"}, 0)

    if mode == "usage-other":
        emit({"ok": False, "error": {"code": "validation", "message": "bad"}}, 2)

    if mode == "error":
        sys.stderr.write("engine refused: task is already closed")
        sys.stderr.write(chr(10))
        sys.exit(3)

    if mode in ("no-task-action", "no-task-action-ru") and argv[:1] == ["task"]:
        if mode == "no-task-action":
            sys.stderr.write("engine: unknown command 'task'")
        else:
            sys.stderr.write("движок: неизвестная команда 'task'")
        sys.stderr.write(chr(10))
        sys.exit(2)

    # Argument contract of the engine's ``task`` command.
    TASK_ACTIONS = ("accept", "reject", "retry", "cancel", "add")
    TASK_VALUE_OPTIONS = {
        "--task",
        "--actor",
        "--notes",
        "--title",
        "--require",
        "--accept",
        "--constraint",
        "--repo",
        "--test-command",
        "--project",
    }
    TASK_FLAGS = {"--json"}

    if argv[:1] == ["task"]:
        if len(argv) < 2 or argv[1].startswith("-"):
            sys.stderr.write(
                "engine: the following arguments are required: action"
            )
            sys.stderr.write(chr(10))
            sys.exit(2)
        action = argv[1]
        known_actions = TASK_ACTIONS
        if mode == "no-task-accept":
            known_actions = tuple(a for a in TASK_ACTIONS if a != "accept")
        if action not in known_actions:
            sys.stderr.write(
                "engine: argument action: invalid choice: '%s'" % action
            )
            sys.stderr.write(chr(10))
            sys.exit(2)
        index = 2
        while index < len(argv):
            token = argv[index]
            if token in TASK_VALUE_OPTIONS:
                index += 1
                if index >= len(argv):
                    sys.stderr.write(
                        "engine: argument %s: expected one argument" % token
                    )
                    sys.stderr.write(chr(10))
                    sys.exit(2)
            elif token not in TASK_FLAGS:
                sys.stderr.write("engine: unrecognized arguments: %s" % token)
                sys.stderr.write(chr(10))
                sys.exit(2)
            index += 1

    if argv[:1] == ["use"] and len(argv) < 2:
        sys.stderr.write("engine: use needs a project key")
        sys.stderr.write(chr(10))
        sys.exit(2)

    emit(json.loads(os.environ["FORGEL_STUB_PAYLOAD"]))
    """
)

PAYLOAD = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "ready", "title": "add a login screen"},
        {"id": "t-2", "state": "done", "title": "write the docs"},
    ],
}

# Every command from the Pareto scope with the engine argv it must produce
# while no project has been selected yet. The engine's own ``--json`` flag is
# appended by the client.
COMMAND_CASES = [
    (
        ("say", "add", "a", "login", "screen"),
        ["say", "--text", "add a login screen"],
    ),
    (("status",), ["status"]),
    (("tasks",), ["tasks"]),
    (("task", "t-1"), ["tasks"]),
    (("accept", "t-1"), ["task", "accept", "--task", "t-1"]),
    (
        ("rework", "t-1", "the", "button", "is", "dead"),
        [
            "task",
            "reject",
            "--task",
            "t-1",
            "--notes",
            "the button is dead",
        ],
    ),
    (("resume",), ["resume"]),
    (("pause",), ["pause"]),
    (("plan",), ["plan"]),
    (("plan", "ship", "v1"), ["plan", "--goal", "ship v1"]),
    (
        ("plan", "--milestone", "m-1", "ship", "v1"),
        ["plan", "m-1", "--goal", "ship v1"],
    ),
    (("history",), ["history"]),
    (("projects",), ["projects"]),
    (("session",), ["session"]),
    (("use", "other"), ["use", "other"]),
]


def _write_stub(directory: Path) -> Path:
    """Write a launcher that starts the stub with this test interpreter.

    The interpreter is reached through a POSIX shell, so a Python installed
    under a path with spaces still works and the stub does not depend on a
    ``#!`` line the kernel could truncate.
    """
    stub = directory / "forgel"
    script = directory / "forgel_stub.py"
    script.write_text(STUB_ENGINE, encoding="utf-8")
    stub.write_text(
        '#!/bin/sh\nexec %s %s "$@"\n'
        % (shlex.quote(sys.executable), shlex.quote(str(script))),
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


class ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.argv_file = self.home / "argv.json"
        self.stdin_file = self.home / "stdin.bin"
        _write_stub(self.bin_dir)

        self.env = dict(os.environ)
        self.env["PATH"] = str(self.bin_dir) + os.pathsep + self.env.get("PATH", "")
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        self.env["FORGEL_STUB_ARGV"] = str(self.argv_file)
        self.env["FORGEL_STUB_STDIN"] = str(self.stdin_file)
        self.env["FORGEL_STUB_PAYLOAD"] = json.dumps(PAYLOAD)
        for name in (
            "FORGEL_STUB_MODE",
            "FORGEL_ENGINE",
            "FORGEL_CODE_TIMEOUT",
            "FORGEL_STUB_SLEEP",
        ):
            self.env.pop(name, None)

    def run_client(self, *args: str):
        import contextlib
        import io

        from forgel_code.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        old_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(list(args))
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        return code, stdout.getvalue(), stderr.getvalue()

    def last_engine_argv(self):
        return json.loads(self.argv_file.read_text(encoding="utf-8"))

    def run_stub(self, *args: str):
        return subprocess.run(
            [str(self.bin_dir / "forgel"), *args],
            capture_output=True,
            text=True,
            env=self.env,
        )

    def assert_single_json_error(self, stdout: str) -> dict:
        self.assertEqual(stdout.count("\n"), 1, stdout)
        parsed = json.loads(stdout)
        self.assertIsInstance(parsed, dict)
        self.assertFalse(parsed["ok"])
        self.assertTrue(str(parsed["error"]).strip())
        self.assertNotIn("usage:", stdout.lower())
        return parsed


class HelpTest(unittest.TestCase):
    def test_scope_commands_are_exactly_the_pareto_set(self) -> None:
        from forgel_code.cli import COMMANDS

        self.assertEqual(
            sorted(COMMANDS),
            sorted(
                [
                    "say",
                    "status",
                    "tasks",
                    "task",
                    "accept",
                    "rework",
                    "resume",
                    "pause",
                    "plan",
                    "history",
                    "projects",
                    "session",
                    "use",
                ]
            ),
        )

    def test_help_lists_the_commands_and_nothing_else(self) -> None:
        from forgel_code.cli import COMMANDS, build_parser

        parser = build_parser()
        actions = [
            action
            for action in parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
        ]
        self.assertEqual(sorted(actions), sorted(COMMANDS))
        text = parser.format_help()
        for command in COMMANDS:
            self.assertIn(command, text)

    def test_global_options_are_declared_once(self) -> None:
        text = (SRC / "cli.py").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        self.assertEqual(lines.count('"--json",'), 1, text)
        self.assertEqual(lines.count('"--engine",'), 1, text)
        self.assertEqual(lines.count('"--timeout",'), 1, text)


class CliSmokeTests(unittest.TestCase):
    """``forgel-code --help`` and ``forgel-code --version`` exit 0."""

    def run_main(self, *args: str):
        import contextlib
        import io

        from forgel_code.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_exits_zero_and_lists_the_commands(self) -> None:
        code, stdout, stderr = self.run_main("--help")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        for command in ("say", "status", "plan", "use"):
            self.assertIn(command, stdout)

    def test_command_help_exits_zero(self) -> None:
        code, stdout, stderr = self.run_main("plan", "--help")
        self.assertEqual(code, 0, stderr)
        self.assertIn("--milestone", stdout)

    def test_version_exits_zero_and_prints_the_client_version(self) -> None:
        from forgel_code import __version__

        code, stdout, stderr = self.run_main("--version")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout.strip(), "forgel-code %s" % __version__)

    def test_help_and_version_exit_zero_as_processes(self) -> None:
        for argv in (["--help"], ["--version"]):
            with self.subTest(argv=argv):
                completed = subprocess.run(
                    [sys.executable, "-m", "forgel_code", *argv],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip())


class CommandTest(ClientTestCase):
    CASES = COMMAND_CASES

    def test_text_output_without_flag(self) -> None:
        for args, expected in self.CASES:
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.run_client(*args)
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertIn("state:", stdout)
                self.assertNotIn("{", stdout)
                self.assertEqual(self.last_engine_argv(), expected + ["--json"])

    def test_json_output_with_flag(self) -> None:
        for args, expected in self.CASES:
            with self.subTest(command=args[0]):
                code, stdout, stderr = self.run_client(*args, "--json")
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                parsed = json.loads(stdout)
                self.assertIsInstance(parsed, dict)
                self.assertTrue(parsed["ok"])
                self.assertEqual(parsed["command"], args[0])
                expected_result = PAYLOAD
                if args[0] == "task":
                    expected_result = PAYLOAD["tasks"][0]
                self.assertEqual(parsed["result"], expected_result)
                self.assertEqual(stdout.strip().count("\n"), 0)
                self.assertEqual(self.last_engine_argv(), expected + ["--json"])

    def test_json_flag_before_the_command(self) -> None:
        code, stdout, _ = self.run_client("--json", "status")
        self.assertEqual(code, 0)
        self.assertIsInstance(json.loads(stdout), dict)

    def test_engine_is_always_called_with_json_flag(self) -> None:
        for args, _ in self.CASES:
            with self.subTest(command=args[0]):
                self.run_client(*args)
                self.assertEqual(self.last_engine_argv()[-1], "--json")

    def test_say_keeps_a_phrase_mentioning_json(self) -> None:
        code, stdout, stderr = self.run_client("say", "add the --json flag", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            self.last_engine_argv(),
            ["say", "--text", "add the --json flag", "--json"],
        )
        self.assertEqual(json.loads(stdout)["result"], PAYLOAD)

    def test_engine_option_is_parsed_not_scanned(self) -> None:
        stub = str(self.bin_dir / "forgel")
        code, _, stderr = self.run_client("status", "--engine", stub)
        self.assertEqual(code, 0, stderr)
        code, _, stderr = self.run_client("--engine", stub, "--json", "status")
        self.assertEqual(code, 0, stderr)


class ProjectPropagationTest(ClientTestCase):
    PROJECT_SCOPED = [
        case
        for case in COMMAND_CASES
        if case[0][0] != "use"
    ]

    def test_selected_project_reaches_every_scoped_command(self) -> None:
        self.assertEqual(self.run_client("use", "acme")[0], 0)
        for args, expected in self.PROJECT_SCOPED:
            with self.subTest(command=args[0]):
                self.run_client(*args)
                argv = self.last_engine_argv()
                self.assertEqual(
                    argv, expected + ["--project", "acme", "--json"], args
                )

    def test_without_use_no_project_is_passed(self) -> None:
        for args, _ in self.PROJECT_SCOPED:
            with self.subTest(command=args[0]):
                self.run_client(*args)
                argv = self.last_engine_argv()
                self.assertNotIn("--project", argv)
                self.assertNotIn("local", argv)

    def test_json_envelope_reports_the_project_actually_passed(self) -> None:
        code, stdout, _ = self.run_client("status", "--json")
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(stdout)["project"])

        self.assertEqual(self.run_client("use", "acme")[0], 0)
        code, stdout, _ = self.run_client("status", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["project"], "acme")


class ArgumentParseErrorTest(ClientTestCase):
    """FR-2: a parse error still yields exactly one JSON object with --json."""

    BROKEN_ARGV = [
        ("unknown-cmd", "--json"),
        ("status", "extra-argument", "--json"),
        ("status", "--no-such-flag", "--json"),
        ("--timeout", "soon", "status", "--json"),
        ("task", "--json"),
    ]

    def test_every_parse_error_emits_one_json_object(self) -> None:
        for argv in self.BROKEN_ARGV:
            with self.subTest(argv=argv):
                code, stdout, _ = self.run_client(*argv)
                self.assertNotEqual(code, 0)
                self.assert_single_json_error(stdout)

    def test_unknown_command_with_json_has_an_error_field(self) -> None:
        code, stdout, _ = self.run_client("unknown-cmd", "--json")
        self.assertNotEqual(code, 0)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("unknown-cmd", parsed["error"])

    def test_extra_positional_with_json_has_an_error_field(self) -> None:
        code, stdout, _ = self.run_client("status", "extra-argument", "--json")
        self.assertNotEqual(code, 0)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("extra-argument", parsed["error"])

    def test_parse_error_without_json_writes_nothing_to_stdout(self) -> None:
        code, stdout, stderr = self.run_client("unknown-cmd")
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("unknown-cmd", stderr)


class TimeoutTest(ClientTestCase):
    def test_default_timeout_is_ten_minutes(self) -> None:
        from forgel_code.engine import DEFAULT_TIMEOUT

        self.assertEqual(DEFAULT_TIMEOUT, 600)

    def test_option_then_environment_then_default(self) -> None:
        from forgel_code.cli import resolve_timeout

        try:
            os.environ.pop("FORGEL_CODE_TIMEOUT", None)
            self.assertEqual(resolve_timeout(None), 600)
            os.environ["FORGEL_CODE_TIMEOUT"] = "42"
            self.assertEqual(resolve_timeout(None), 42)
            self.assertEqual(resolve_timeout(7), 7)
        finally:
            os.environ.pop("FORGEL_CODE_TIMEOUT", None)

    def test_option_times_out_a_slow_engine(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "sleep"
        self.env["FORGEL_STUB_SLEEP"] = "1.5"
        code, _, stderr = self.run_client("--timeout", "0.2", "status")
        self.assertNotEqual(code, 0)
        self.assertIn("timed out", stderr)
        self.assertIn("0.2", stderr)

    def test_environment_times_out_a_slow_engine_with_json(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "sleep"
        self.env["FORGEL_STUB_SLEEP"] = "1.5"
        self.env["FORGEL_CODE_TIMEOUT"] = "0.2"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("timed out", stderr)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("timed out", parsed["error"])


class EngineCallTest(ClientTestCase):
    def test_utf8_output_is_decoded_regardless_of_the_locale(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "non-ascii"
        env = dict(self.env)
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env["PYTHONCOERCECLOCALE"] = "0"
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [sys.executable, "-m", "forgel_code", "status", "--json"],
            cwd=str(ROOT),
            capture_output=True,
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(payload["result"]["text"], "Привет, мир")

    def test_engine_does_not_receive_the_client_stdin(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "stdin"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["result"]["stdin_bytes"], 0)
        self.assertEqual(self.stdin_file.read_bytes(), b"")


class StructuredErrorTest(ClientTestCase):
    def test_ok_false_with_exit_zero_is_a_failure(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "structured-error"
        code, stdout, stderr = self.run_client("status")
        self.assertNotEqual(code, 0)
        self.assertIn("task_closed", stderr)
        self.assertIn("task is already closed", stderr)
        self.assertEqual(stdout, "")

    def test_structured_fields_reach_the_json_object(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "structured-error"
        code, stdout, _ = self.run_client("status", "--json")
        self.assertNotEqual(code, 0)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("task_closed", parsed["error"])
        self.assertEqual(parsed["engine_error"]["code"], "task_closed")
        self.assertEqual(parsed["engine_error"]["kind"], "conflict")
        self.assertEqual(
            parsed["engine_error"]["message"], "task is already closed"
        )

    def test_string_error_is_carried_through(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "structured-error-string"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("the milestone is missing", stderr)
        self.assertIn("the milestone is missing", json.loads(stdout)["error"])


class JsonExtractionTest(ClientTestCase):
    def test_a_brace_in_a_log_line_does_not_hide_the_answer(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "noisy"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["result"], PAYLOAD)

    def test_undecodable_output_is_reported_with_an_excerpt(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "garbage"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("engine fell over", stderr)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("engine fell over", parsed["error"])


class TaskLookupTest(ClientTestCase):
    def test_task_shows_only_the_requested_task(self) -> None:
        code, stdout, _ = self.run_client("task", "t-2")
        self.assertEqual(code, 0)
        self.assertIn("t-2", stdout)
        self.assertIn("done", stdout)
        self.assertNotIn("t-1", stdout)

    def test_unknown_task_is_reported(self) -> None:
        code, _, stderr = self.run_client("task", "t-404")
        self.assertNotEqual(code, 0)
        self.assertIn("t-404", stderr)

        code, stdout, _ = self.run_client("task", "t-404", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("t-404", json.loads(stdout)["error"])

    def test_only_top_level_entries_are_matched(self) -> None:
        self.env["FORGEL_STUB_PAYLOAD"] = json.dumps(
            {
                "ok": True,
                "tasks": [{"id": "t-1", "state": "ready"}],
                "milestone": {"current": {"task": {"id": "t-9"}}},
            }
        )
        code, _, stderr = self.run_client("task", "t-9")
        self.assertNotEqual(code, 0)
        self.assertIn("t-9", stderr)

    def test_task_id_field_is_understood(self) -> None:
        self.env["FORGEL_STUB_PAYLOAD"] = json.dumps(
            {"ok": True, "tasks": [{"task_id": "t-7", "state": "ready"}]}
        )
        code, stdout, _ = self.run_client("task", "t-7")
        self.assertEqual(code, 0)
        self.assertIn("t-7", stdout)

    def test_ambiguous_task_is_an_error(self) -> None:
        self.env["FORGEL_STUB_PAYLOAD"] = json.dumps(
            {
                "ok": True,
                "tasks": [{"id": "t-1", "state": "ready"}, {"id": "t-1", "state": "done"}],
            }
        )
        code, stdout, stderr = self.run_client("task", "t-1", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("ambiguous", stderr)
        self.assertIn("ambiguous", json.loads(stdout)["error"])


class AcceptReworkTest(ClientTestCase):
    def test_accept_reaches_the_engine(self) -> None:
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.last_engine_argv(),
            ["task", "accept", "--task", "t-1", "--json"],
        )

    def test_rework_reaches_the_engine_and_carries_remarks(self) -> None:
        code, _, stderr = self.run_client("rework", "t-1", "no", "tests")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.last_engine_argv(),
            [
                "task",
                "reject",
                "--task",
                "t-1",
                "--notes",
                "no tests",
                "--json",
            ],
        )

    def test_selected_project_is_passed_to_the_engine(self) -> None:
        self.assertEqual(self.run_client("use", "acme")[0], 0)
        self.assertEqual(self.run_client("accept", "t-1")[0], 0)
        self.assertEqual(
            self.last_engine_argv(),
            [
                "task",
                "accept",
                "--task",
                "t-1",
                "--project",
                "acme",
                "--json",
            ],
        )

    def test_rejected_use_does_not_change_the_session(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "error"
        code, _, _ = self.run_client("use", "acme")
        self.assertNotEqual(code, 0)

        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertFalse(session.selected())

    def test_rework_requires_remarks(self) -> None:
        code, stdout, stderr = self.run_client("rework", "t-1", "--json")
        self.assertNotEqual(code, 0)
        self.assert_single_json_error(stdout)
        self.assertIn("remarks", stderr)

    def test_accept_and_rework_report_engine_errors(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "error"
        for command in ("accept", "rework"):
            args = [command, "t-1"]
            if command == "rework":
                args.append("no tests")
            with self.subTest(command=command):
                code, _, stderr = self.run_client(*args)
                self.assertNotEqual(code, 0)
                self.assertIn("engine refused", stderr)


class MissingEngineCommandTest(ClientTestCase):
    """FR-9: a missing engine command is inferred from the return code."""

    def test_accept_reports_a_missing_engine_command(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task accept", stderr)

    def test_rework_reports_a_missing_engine_command(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, _, stderr = self.run_client("rework", "t-1", "no tests")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task reject", stderr)

    def test_accept_reports_a_missing_accept_action(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-accept"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task accept", stderr)

    def test_detection_does_not_depend_on_the_message_language(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action-ru"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)

    def test_a_structured_non_usage_error_is_not_a_missing_command(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "usage-other"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertNotIn("no engine command", stderr)

    def test_missing_engine_command_with_json_flag_emits_one_object(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, stdout, stderr = self.run_client("accept", "t-1", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("no engine command", parsed["error"])

    def test_other_engine_errors_are_passed_through_unchanged(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "error"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("engine refused: task is already closed", stderr)
        self.assertNotIn("no engine command", stderr)

    def test_the_client_has_no_english_error_markers(self) -> None:
        text = (SRC / "cli.py").read_text(encoding="utf-8")
        for marker in ("unrecognized", "invalid choice", "no such command"):
            self.assertNotIn(marker, text)


class StubContractTest(ClientTestCase):
    """The stand-in must behave like the engine's real ``task`` parser."""

    def test_stub_accepts_the_calls_the_client_makes(self) -> None:
        for argv in (
            ["task", "accept", "--task", "t-1", "--json"],
            ["task", "reject", "--task", "t-1", "--notes", "no tests", "--json"],
            ["task", "accept", "--task", "t-1", "--project", "acme", "--json"],
            ["task", "accept", "--accept", "x", "--task", "t-1", "--json"],
        ):
            with self.subTest(argv=argv):
                completed = self.run_stub(*argv)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_stub_rejects_a_missing_action(self) -> None:
        for argv in (
            ["task", "--accept", "--task", "t-1", "--json"],
            ["task", "--task", "t-1", "--notes", "no tests", "--json"],
        ):
            with self.subTest(argv=argv):
                completed = self.run_stub(*argv)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("required: action", completed.stderr)

    def test_stub_rejects_an_unknown_action(self) -> None:
        completed = self.run_stub("task", "approve", "--task", "t-1", "--json")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("invalid choice", completed.stderr)

    def test_stub_rejects_the_unknown_options_the_client_must_not_send(self) -> None:
        for flag in ("--reason", "--approve"):
            with self.subTest(flag=flag):
                completed = self.run_stub(
                    "task", "accept", flag, "x", "--task", "t-1", "--json"
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("unrecognized arguments", completed.stderr)
                self.assertIn(flag, completed.stderr)


class FailureTest(ClientTestCase):
    def test_engine_error_is_reported_and_exit_code_is_non_zero(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "error"
        code, stdout, stderr = self.run_client("status")
        self.assertNotEqual(code, 0)
        self.assertIn("engine refused: task is already closed", stderr)
        self.assertEqual(stdout, "")

    def test_engine_error_with_json_flag_emits_one_object(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "error"
        code, stdout, stderr = self.run_client("status", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("engine refused", stderr)
        parsed = self.assert_single_json_error(stdout)
        self.assertIn("engine refused", parsed["error"])

    def test_missing_engine_is_reported(self) -> None:
        code, _, stderr = self.run_client("--engine", "forgel-missing", "status")
        self.assertNotEqual(code, 0)
        self.assertIn("forgel-missing", stderr)


class SessionTest(ClientTestCase):
    def test_default_project_is_not_selected(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertFalse(session.selected())

    def test_use_persists_the_active_project(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertFalse(session.selected())
        code, _, _ = self.run_client("use", "acme")
        self.assertEqual(code, 0)
        self.assertEqual(session.project(), "acme")
        self.assertTrue(session.selected())

    def test_projects_command_goes_to_the_engine(self) -> None:
        code, _, _ = self.run_client("projects")
        self.assertEqual(code, 0)
        self.assertEqual(self.last_engine_argv(), ["projects", "--json"])


class PlanShapeTest(ClientTestCase):
    def test_free_text_is_the_goal(self) -> None:
        code, _, stderr = self.run_client("plan", "ship", "v1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.last_engine_argv(), ["plan", "--goal", "ship v1", "--json"])

    def test_milestone_is_an_explicit_option(self) -> None:
        code, _, stderr = self.run_client("plan", "--milestone", "m-1", "ship", "v1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            self.last_engine_argv(),
            ["plan", "m-1", "--goal", "ship v1", "--json"],
        )

    def test_a_goal_alone_is_never_read_as_a_milestone(self) -> None:
        code, _, stderr = self.run_client("plan", "m-1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.last_engine_argv(), ["plan", "--goal", "m-1", "--json"])


class NoEngineImportTest(unittest.TestCase):
    ALLOWED_STDLIB = {
        "__future__",
        "argparse",
        "json",
        "os",
        "pathlib",
        "subprocess",
        "sys",
        "typing",
    }

    def test_client_sources_import_only_stdlib(self) -> None:
        import ast

        files = sorted(SRC.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest(file=path.name, module=name):
                        self.assertIn(top, self.ALLOWED_STDLIB)

    def test_client_sources_never_mention_the_engine_package(self) -> None:
        for path in sorted(SRC.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn("import forgel\n", text)
                self.assertNotIn("from forgel import", text)


class ReadmeTest(unittest.TestCase):
    INSTALL_URL = "https://raw.githubusercontent.com/forgel-dev/code/main/install.sh"

    def setUp(self) -> None:
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_readme_documents_the_engine_commands_the_client_calls(self) -> None:
        for fragment in (
            "forgel say",
            "forgel status",
            "forgel tasks",
            "forgel task accept",
            "forgel task reject",
            "--notes",
            "forgel plan",
            "forgel resume",
            "forgel pause",
            "forgel history",
            "forgel projects",
            "forgel use",
        ):
            self.assertIn(fragment, self.readme)
        self.assertNotIn("--reason", self.readme)
        self.assertNotIn("forgel task --accept", self.readme)

    def test_readme_documents_the_missing_engine_command_report(self) -> None:
        self.assertIn("no engine command", self.readme)

    def test_readme_has_a_pinned_install_command(self) -> None:
        self.assertIn(
            "curl -fsSL %s | sh" % self.INSTALL_URL,
            self.readme,
        )
        self.assertNotRegex(self.readme, r"/v[0-9][^\s/]*/install\.sh")

    def test_readme_has_no_tag_pinned_install(self) -> None:
        self.assertNotRegex(self.readme, r"/v[0-9][^\s/]*/install\.sh")
        for line in self.readme.splitlines():
            stripped = line.strip()
            if "raw.githubusercontent.com/forgel-dev/code" in stripped:
                self.assertNotRegex(stripped, r"/v[0-9][^\s/]*/install\.sh")
                self.assertIn(self.INSTALL_URL, stripped)

    def test_readme_has_no_editable_install_recommendation(self) -> None:
        self.assertNotIn("pip install .", self.readme)
        self.assertIn("Editable installs", self.readme)
        self.assertIn("not supported", self.readme)

    def test_readme_documents_the_update_path(self) -> None:
        self.assertIn("### Update", self.readme)
        self.assertIn(self.INSTALL_URL, self.readme)


if __name__ == "__main__":
    unittest.main()
