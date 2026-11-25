"""The client reports its own version and its engine floor as one machine report.

``forgel-code --version --json`` must answer with both versions, use the
installed client distribution's version, and answer on a machine where no engine
is installed and the engine cannot be run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forgel_code import MIN_ENGINE_VERSION, __version__, version_report  # noqa: E402

# The only place in the product that may spell out the engine floor.
DECLARATION = ROOT / "forgel_code" / "__init__.py"


def _clean_env() -> dict:
    """The environment without anything that could point the client at an engine."""
    env = dict(os.environ)
    for name in ("FORGEL_ENGINE", "FORGEL_STUB_MODE", "FORGEL_CODE_TIMEOUT"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(ROOT)
    env["FORGEL_CODE_HOME"] = tempfile.mkdtemp(prefix="forgel-code-home-")
    return env


def _distribution_version() -> str:
    """The version the in-tree backend packs into the built distribution."""
    path = ROOT / "_build_backend.py"
    spec = importlib.util.spec_from_file_location("version_report_backend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for line in module._metadata().splitlines():
        if line.startswith("Version: "):
            return line.split(": ", 1)[1].strip()
    raise AssertionError("the built metadata names no version")


class VersionReportTest(unittest.TestCase):
    """AC-1: one report carries the client version and the engine floor."""

    def run_client(self, *args: str, env: dict = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "forgel_code", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env or _clean_env(),
        )

    def report(self, *args: str, env: dict = None) -> dict:
        completed = self.run_client(*args, env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_the_report_carries_both_versions_under_distinct_names(self) -> None:
        report = self.report("--version", "--json")
        self.assertEqual(report["forgel_code_version"], __version__)
        self.assertEqual(report["minimum_engine_version"], MIN_ENGINE_VERSION)
        self.assertNotEqual(
            report["forgel_code_version"], report["minimum_engine_version"]
        )

    def test_the_json_flag_is_accepted_after_the_version_flag(self) -> None:
        self.assertEqual(
            self.report("--version", "--json"), self.report("--json", "--version")
        )

    def test_the_client_version_is_the_distribution_version(self) -> None:
        report = self.report("--version", "--json")
        self.assertEqual(report["forgel_code_version"], _distribution_version())

    def test_the_minimum_is_a_single_well_formed_version_number(self) -> None:
        self.assertRegex(MIN_ENGINE_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            version_report()["minimum_engine_version"], MIN_ENGINE_VERSION
        )

    def test_the_report_is_produced_with_no_engine_installed(self) -> None:
        env = _clean_env()
        # An engine path that exists nowhere, and a PATH that cannot resolve one.
        missing = tempfile.mkdtemp(prefix="forgel-code-empty-")
        env["FORGEL_ENGINE"] = os.path.join(missing, "no-such-forgel")
        env["PATH"] = missing
        completed = self.run_client("--version", "--json", env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["minimum_engine_version"], MIN_ENGINE_VERSION)

    def test_the_report_never_runs_the_engine(self) -> None:
        tmp = tempfile.mkdtemp(prefix="forgel-code-log-")
        log = os.path.join(tmp, "argv.json")
        env = _clean_env()
        env["FAKE_ENGINE_LOG"] = log
        completed = self.run_client("--version", "--json", env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(os.path.exists(log), "the report ran an engine")

    def test_the_human_readable_version_output_is_unchanged(self) -> None:
        completed = self.run_client("--version")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "forgel-code %s" % __version__)
        with self.assertRaises(ValueError):
            json.loads(completed.stdout)


class VersionDetectionTest(unittest.TestCase):
    """Only the client's own ``--version`` asks for the version."""

    def test_the_option_before_any_command_is_the_version(self) -> None:
        from forgel_code.cli import version_requested

        self.assertTrue(version_requested(["--version"]))
        self.assertTrue(version_requested(["--json", "--version"]))

    def test_a_command_owns_the_words_after_its_name(self) -> None:
        from forgel_code.cli import version_requested

        self.assertFalse(version_requested(["say", "--version"]))
        self.assertFalse(version_requested(["say", "--", "--version"]))


class SingleDeclarationTest(unittest.TestCase):
    """AC-5: the engine floor is declared once and read from there."""

    def test_no_other_product_module_restates_the_engine_floor(self) -> None:
        offenders = []
        for module in sorted((ROOT / "forgel_code").glob("*.py")):
            if module == DECLARATION:
                continue
            if MIN_ENGINE_VERSION in module.read_text(encoding="utf-8"):
                offenders.append(module.name)
        self.assertEqual(offenders, [], "the engine floor is restated")

    def test_the_engine_floor_is_declared_exactly_once(self) -> None:
        text = DECLARATION.read_text(encoding="utf-8")
        self.assertEqual(text.count("MIN_ENGINE_VERSION ="), 1)
        self.assertEqual(text.count(MIN_ENGINE_VERSION), 1)


if __name__ == "__main__":
    unittest.main()
