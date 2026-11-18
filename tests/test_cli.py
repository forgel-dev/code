"""Tests for the ``forgel-code`` client against a stand-in engine."""

from __future__ import annotations

import json
import os
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
# ``FORGEL_STUB_MODE`` models engines the client must report honestly about:
#   * ``no-task-action`` - no ``task`` command at all;
#   * ``no-task-accept`` - ``task`` exists but has no ``accept`` action.
STUB_ENGINE = textwrap.dedent(
    """\
    import json
    import os
    import sys

    argv = sys.argv[1:]
    with open(os.environ["FORGEL_STUB_ARGV"], "w", encoding="utf-8") as handle:
        json.dump(argv, handle)

    mode = os.environ.get("FORGEL_STUB_MODE", "ok")
    if mode == "error":
        sys.stderr.write("engine refused: task is already closed\\n")
        sys.exit(3)
    if mode == "no-task-action" and argv[:1] == ["task"]:
        sys.stderr.write("engine: unknown command 'task'\\n")
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
                "engine: the following arguments are required: action\\n"
            )
            sys.exit(2)
        action = argv[1]
        known_actions = TASK_ACTIONS
        if mode == "no-task-accept":
            known_actions = tuple(a for a in TASK_ACTIONS if a != "accept")
        if action not in known_actions:
            sys.stderr.write(
                "engine: argument action: invalid choice: '%s'\\n" % action
            )
            sys.exit(2)
        index = 2
        while index < len(argv):
            token = argv[index]
            if token in TASK_VALUE_OPTIONS:
                index += 1
                if index >= len(argv):
                    sys.stderr.write(
                        "engine: argument %s: expected one argument\\n" % token
                    )
                    sys.exit(2)
            elif token not in TASK_FLAGS:
                sys.stderr.write(
                    "engine: unrecognized arguments: %s\\n" % token
                )
                sys.exit(2)
            index += 1

    if argv[:1] == ["use"] and len(argv) < 2:
        sys.stderr.write("engine: use needs a project key\\n")
        sys.exit(2)

    payload = json.loads(os.environ["FORGEL_STUB_PAYLOAD"])
    sys.stdout.write(json.dumps(payload) + "\\n")
    """
)

PAYLOAD = {
    "ok": True,
    "tasks": [
        {"id": "t-1", "state": "ready", "title": "add a login screen"},
        {"id": "t-2", "state": "done", "title": "write the docs"},
    ],
}


def _write_stub(directory: Path) -> Path:
    stub = directory / "forgel"
    stub.write_text("#!%s\n%s" % (sys.executable, STUB_ENGINE), encoding="utf-8")
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
        _write_stub(self.bin_dir)

        self.env = dict(os.environ)
        self.env["PATH"] = str(self.bin_dir) + os.pathsep + self.env.get("PATH", "")
        self.env["FORGEL_CODE_HOME"] = str(self.home / "session")
        self.env["FORGEL_STUB_ARGV"] = str(self.argv_file)
        self.env["FORGEL_STUB_PAYLOAD"] = json.dumps(PAYLOAD)
        self.env.pop("FORGEL_STUB_MODE", None)
        self.env.pop("FORGEL_ENGINE", None)

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


class CommandTest(ClientTestCase):
    # Every command from the Pareto scope with the engine argv it must produce
    # while no project has been selected yet. The engine's own ``--json`` flag
    # is appended by the client.
    CASES = [
        (("say", "add", "a", "login", "screen"), ["say", "add a login screen"]),
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
        (("plan", "m-1"), ["plan", "m-1"]),
        (("plan", "m-1", "ship", "v1"), ["plan", "m-1", "--goal", "ship v1"]),
        (("history",), ["history"]),
        (("projects",), ["projects"]),
        (("session",), ["session"]),
        (("use", "other"), ["use", "other"]),
    ]

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


class TaskStateTest(ClientTestCase):
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


class AcceptReworkTest(ClientTestCase):
    def test_accept_reaches_the_engine(self) -> None:
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.last_engine_argv(),
            ["task", "accept", "--task", "t-1", "--json"],
        )

    def test_accept_uses_the_active_project(self) -> None:
        # The project the client session made active is forwarded to the engine.
        self.assertEqual(self.run_client("use", "acme")[0], 0)
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        argv = self.last_engine_argv()
        self.assertEqual(argv[:2], ["task", "accept"])
        self.assertIn("--project", argv)
        self.assertEqual(argv[argv.index("--project") + 1], "acme")
        self.assertIn("--task", argv)
        self.assertEqual(argv[argv.index("--task") + 1], "t-1")

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

    def test_default_session_key_never_reaches_the_engine(self) -> None:
        for args in (("accept", "t-1"), ("rework", "t-1", "no tests")):
            with self.subTest(command=args[0]):
                code, _, _ = self.run_client(*args)
                self.assertEqual(code, 0)
                argv = self.last_engine_argv()
                self.assertNotIn("--project", argv)
                self.assertNotIn("local", argv)

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
        self.assertEqual(self.run_client("rework", "t-1", "no tests")[0], 0)
        self.assertEqual(
            self.last_engine_argv(),
            [
                "task",
                "reject",
                "--task",
                "t-1",
                "--notes",
                "no tests",
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
        with self.assertRaises(SystemExit):
            self.run_client("rework", "t-1")

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
    """FR-4: with no engine command the client says so, it invents nothing."""

    def test_accept_reports_a_missing_engine_command(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task accept", stderr)
        self.assertIn("unknown command", stderr)

    def test_rework_reports_a_missing_engine_command(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, _, stderr = self.run_client("rework", "t-1", "no tests")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task reject", stderr)

    def test_accept_reports_a_missing_accept_action(self) -> None:
        # The engine knows ``task`` but not its ``accept`` action; the explicit
        # missing-command report must cover that shape as well.
        self.env["FORGEL_STUB_MODE"] = "no-task-accept"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        self.assertIn("forgel task accept", stderr)
        self.assertIn("invalid choice", stderr)

    def test_missing_engine_command_with_json_flag_emits_one_object(self) -> None:
        self.env["FORGEL_STUB_MODE"] = "no-task-action"
        code, stdout, stderr = self.run_client("accept", "t-1", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("no engine command", stderr)
        parsed = json.loads(stdout)
        self.assertFalse(parsed["ok"])
        self.assertIn("no engine command", parsed["error"])

    def test_other_engine_errors_are_passed_through_unchanged(self) -> None:
        # An ordinary engine failure is not turned into the missing-command
        # report; the engine's own text reaches the user as is.
        self.env["FORGEL_STUB_MODE"] = "error"
        code, _, stderr = self.run_client("accept", "t-1")
        self.assertNotEqual(code, 0)
        self.assertIn("engine refused: task is already closed", stderr)
        self.assertNotIn("no engine command", stderr)


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
        parsed = json.loads(stdout)
        self.assertFalse(parsed["ok"])
        self.assertIn("engine refused", parsed["error"])

    def test_missing_engine_is_reported(self) -> None:
        code, _, stderr = self.run_client("--engine", "forgel-missing", "status")
        self.assertNotEqual(code, 0)
        self.assertIn("forgel-missing", stderr)


class SessionTest(ClientTestCase):
    def test_default_project_is_local(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertEqual(session.project(), "local")
        self.assertFalse(session.selected())

    def test_use_persists_the_active_project(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertEqual(session.project(), "local")
        code, _, _ = self.run_client("use", "acme")
        self.assertEqual(code, 0)
        self.assertEqual(session.project(), "acme")
        self.assertTrue(session.selected())

    def test_projects_command_goes_to_the_engine(self) -> None:
        code, _, _ = self.run_client("projects")
        self.assertEqual(code, 0)
        self.assertEqual(self.last_engine_argv(), ["projects", "--json"])


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


class PackagingTest(unittest.TestCase):
    def test_entry_point_points_at_the_client(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('forgel-code = "forgel_code.cli:main"', text)

    def test_license_and_readme_are_present(self) -> None:
        self.assertTrue((ROOT / "LICENSE").is_file())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("forgel-code", readme)
        for command in ("say", "status", "tasks", "task", "plan", "use"):
            self.assertIn(command, readme)

    def test_readme_documents_the_engine_commands_the_client_calls(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
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
            self.assertIn(fragment, readme)
        self.assertNotIn("--reason", readme)
        self.assertNotIn("forgel task --accept", readme)

    def test_readme_documents_the_missing_engine_command_report(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("no engine command", readme)


if __name__ == "__main__":
    unittest.main()
