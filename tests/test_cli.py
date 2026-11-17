"""Tests for the ``forgel-code`` client against a stand-in engine."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "forgel_code"

sys.path.insert(0, str(ROOT))

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

    payload = json.loads(os.environ["FORGEL_STUB_PAYLOAD"])
    sys.stdout.write(json.dumps(payload) + "\\n")
    """
)

PAYLOAD = {"ok": True, "task": {"id": "t-1", "state": "ready"}}


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
    CASES = [
        (("say", "add", "a", "login", "screen"), ["say", "add a login screen"]),
        (("status",), ["status"]),
        (("tasks",), ["tasks"]),
        (("task", "t-1"), ["task", "t-1"]),
        (("resume",), ["resume"]),
        (("pause",), ["pause"]),
        (("plan",), ["plan"]),
        (("plan", "ship", "v1"), ["plan", "ship v1"]),
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
                self.assertIn("state: ready", stdout)
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
                self.assertEqual(parsed["result"], PAYLOAD)
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

    def test_unsupported_commands_are_reported_explicitly(self) -> None:
        from forgel_code.cli import UNSUPPORTED

        self.assertTrue(UNSUPPORTED)
        for command in sorted(UNSUPPORTED):
            with self.subTest(command=command):
                code, _, stderr = self.run_client(command, "t-1")
                self.assertNotEqual(code, 0)
                self.assertIn("no command", stderr)
                self.assertFalse(self.argv_file.exists())

    def test_unsupported_command_with_json_flag(self) -> None:
        code, stdout, _ = self.run_client("accept", "t-1", "--json")
        self.assertNotEqual(code, 0)
        parsed = json.loads(stdout)
        self.assertFalse(parsed["ok"])


class SessionTest(ClientTestCase):
    def test_default_project_is_local(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertEqual(session.project(), "local")

    def test_use_persists_the_active_project(self) -> None:
        from forgel_code.session import Session

        session = Session(Path(self.env["FORGEL_CODE_HOME"]) / "session.json")
        self.assertEqual(session.project(), "local")
        code, _, _ = self.run_client("use", "acme")
        self.assertEqual(code, 0)
        self.assertEqual(session.project(), "acme")

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


if __name__ == "__main__":
    unittest.main()
