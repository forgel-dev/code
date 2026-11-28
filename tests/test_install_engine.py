"""The combined installation: the default run settles the engine beside the client.

Every scenario runs the real ``install.sh`` from the checkout against the
deterministic stand-in for the engine's own installer
(``tests/stub_engine_install.py``), which answers the offered version and writes
the engine binary the client would run.
"""

from __future__ import annotations

import json
import os
import shlex
import unittest
from pathlib import Path

from tests.test_install import (
    InstallerCase,
    _declared_minimum,
    _marker_count,
    _run,
)


class EngineCase(InstallerCase):
    """A scenario with a present engine it can place and inspect."""

    def setUp(self) -> None:
        super().setUp()
        self.log_path = self.env["FORGEL_STUB_ENGINE_LOG"]
        self.clear_log()

    def offer(self, version: str) -> None:
        """The version the configured engine source offers in this scenario."""
        self.env["FORGEL_STUB_ENGINE_AVAILABLE"] = version

    def clear_log(self) -> None:
        if os.path.exists(self.log_path):
            os.remove(self.log_path)

    def calls(self):
        """Every argv the stand-in for the engine's installer received."""
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def install_calls(self):
        """The recorded calls that asked for a version to be installed."""
        found = []
        for argv in self.calls():
            for argument in argv:
                if argument == "--install" or argument.startswith("--install="):
                    found.append(argv)
                    break
        return found

    def preinstall(self, version: str) -> None:
        """Place an engine at ``version``, as an earlier installation would."""
        directory = os.path.dirname(self.env["FORGEL_ENGINE"])
        if directory:
            os.makedirs(directory, exist_ok=True)
        result = _run(
            [
                self.env["FORGEL_ENGINE_INSTALLER"],
                "--source",
                "test",
                "--install",
                version,
            ],
            self.base,
            self.env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.clear_log()

    def engine_version(self) -> str:
        """The version the engine in place reports, or ``""`` when absent."""
        if not os.path.exists(self.env["FORGEL_ENGINE"]):
            return ""
        result = _run(
            [self.env["FORGEL_ENGINE"], "version", "--json"], self.base, self.env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["engine"]["version"]

    def report(self, result) -> str:
        """The whole output of one run, wherever a line was written."""
        return result.stdout + result.stderr


class EngineObtainedTest(EngineCase):
    """No engine is present: the offered version is installed."""

    def test_absent_engine_is_installed_and_reported(self) -> None:
        self.offer("0.2.0")
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), "0.2.0")
        self.assertTrue(self.launcher.is_file(), "no client launcher")
        self.assertIn("Engine: forgel 0.2.0 installed", result.stdout)
        self.assertEqual(len(self.install_calls()), 1)

    def test_installed_engine_is_at_or_above_the_declared_minimum(self) -> None:
        self.offer(_declared_minimum())
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), _declared_minimum())
        self.assertIn(
            "Engine: forgel %s installed" % _declared_minimum(), result.stdout
        )


class EngineKeptTest(EngineCase):
    """A present engine that needs no change is left exactly as it is."""

    def assert_kept(self, present: str, offered: str) -> None:
        self.offer(offered)
        self.preinstall(present)
        before = self.engine_version()
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), before)
        self.assertEqual(self.install_calls(), [])
        self.assertIn("Engine: forgel %s kept" % before, result.stdout)

    def test_engine_at_the_offered_version_is_kept(self) -> None:
        self.assert_kept("0.1.0", "0.1.0")

    def test_engine_above_the_offered_version_is_kept(self) -> None:
        self.assert_kept("9.9.9", "0.1.0")

    def test_a_prefix_or_trailing_zeros_do_not_make_a_newer_version(self) -> None:
        self.assert_kept("v0.1.0.0", "0.1")

    def test_a_supported_engine_answering_its_report_is_kept(self) -> None:
        """The present version comes from the report the engine really answers."""
        version = _declared_minimum()
        report = json.dumps(
            {"ok": True, "engine": {"name": "forgel", "version": version}}
        )
        asked = os.path.join(self.tmp, "engine-asked.log")
        binary = Path(self.env["FORGEL_ENGINE"])
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text(
            "#!/bin/sh\n"
            "echo \"$*\" >>%s\n"
            "if [ \"$1\" = version ]; then\n"
            "    echo %s\n"
            "    exit 0\n"
            "fi\n"
            "exit 1\n" % (shlex.quote(asked), shlex.quote(report)),
            encoding="utf-8",
        )
        binary.chmod(0o755)
        self.offer(version)

        result = self.install()

        self.assertEqual(result.returncode, 0, self.report(result))
        with open(asked, encoding="utf-8") as handle:
            self.assertEqual(
                [line.strip() for line in handle if line.strip()],
                ["version --json"],
            )
        self.assertEqual(self.install_calls(), [])
        self.assertIn("Engine: forgel %s kept" % version, result.stdout)


class EngineReplacedTest(EngineCase):
    """A strictly newer offered engine replaces the present one."""

    def test_strictly_newer_offered_engine_replaces_the_present_one(self) -> None:
        self.offer("0.2.0")
        self.preinstall("0.1.0")
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), "0.2.0")
        self.assertIn("Engine: forgel 0.2.0 replaced 0.1.0", result.stdout)
        self.assertEqual(len(self.install_calls()), 1)

    def test_replaced_engine_is_never_older_than_the_present_one(self) -> None:
        self.offer("0.1.0")
        self.preinstall("0.5.0")
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), "0.5.0")
        self.assertEqual(self.install_calls(), [])


class EngineFailureTest(EngineCase):
    """An unreachable supported engine ends the run as a failure."""

    def assert_failure(self, result, *fragments) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for fragment in fragments:
            self.assertIn(fragment, result.stderr)
        self.assertIn("required minimum engine version:", result.stderr)
        self.assertIn("what you can do:", result.stderr)

    def test_offered_version_below_the_minimum_and_no_engine_fails(self) -> None:
        self.offer("0.0.1")
        result = self.install()
        self.assert_failure(result, _declared_minimum(), "0.0.1", "--client-only")
        self.assertEqual(self.engine_version(), "")

    def test_engine_below_the_minimum_never_satisfies_it(self) -> None:
        self.offer("0.0.1")
        self.preinstall("0.0.1")
        result = self.install()
        self.assert_failure(result, _declared_minimum(), "0.0.1")
        self.assertEqual(self.install_calls(), [])

    def test_a_version_that_cannot_be_ordered_never_satisfies_the_minimum(self) -> None:
        self.offer("banana")
        result = self.install()
        self.assert_failure(result, _declared_minimum(), "banana")
        self.assertEqual(self.engine_version(), "")

    def test_failing_engine_installation_fails_the_run(self) -> None:
        self.offer("0.2.0")
        self.env["FORGEL_STUB_ENGINE_INSTALL_EXIT"] = "1"
        result = self.install()
        self.assert_failure(result, _declared_minimum(), "0.2.0")
        self.assertNotIn("installed from", result.stdout)

    def test_unreachable_engine_source_fails_the_run(self) -> None:
        self.env["FORGEL_STUB_ENGINE_AVAILABLE_EXIT"] = "1"
        result = self.install()
        self.assert_failure(result, _declared_minimum())
        self.assertIn("cannot determine the engine version", result.stderr)

    def test_an_unorderable_present_engine_is_replaced_by_a_supported_one(self) -> None:
        self.offer(_declared_minimum())
        self.preinstall("banana")
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), _declared_minimum())
        self.assertIn("replaced banana", result.stdout)


class ClientOnlyTest(EngineCase):
    """``--client-only`` installs the client and leaves the engine alone."""

    def test_client_only_queries_and_changes_no_engine(self) -> None:
        self.offer("0.2.0")
        self.preinstall("0.1.0")
        result = self.install("--client-only")
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.engine_version(), "0.1.0")
        self.assertTrue(self.launcher.is_file(), "no client launcher")
        self.assertIn("--client-only", result.stdout)


class RepeatedInstallTest(EngineCase):
    """A second default run leaves one client and the same engine."""

    def test_repeating_the_default_installation_changes_no_engine(self) -> None:
        self.offer("0.2.0")
        first = self.install()
        self.assertEqual(first.returncode, 0, self.report(first))
        self.assertEqual(self.engine_version(), "0.2.0")

        self.clear_log()
        second = self.install()
        self.assertEqual(second.returncode, 0, self.report(second))
        self.assertEqual(self.install_calls(), [])
        self.assertEqual(self.engine_version(), "0.2.0")
        self.assertEqual(_marker_count(self.profile), 1)
        self.assertTrue(self.launcher.is_file(), "no client launcher")


class RemovalTest(EngineCase):
    """Removing the client installs nothing and leaves the engine in place."""

    def test_uninstall_keeps_the_engine_and_removes_the_client(self) -> None:
        self.offer("0.2.0")
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), "0.2.0")

        self.clear_log()
        result = self.install("--uninstall")
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.install_calls(), [])
        self.assertEqual(self.engine_version(), "0.2.0")
        self.assertFalse(self.prefix.exists(), "the client prefix survived")
        self.assertFalse(self.launcher.exists(), "the launcher survived")
        self.assertEqual(_marker_count(self.profile), 0)


class ProfileOptOutTest(EngineCase):
    """Leaving the startup configuration alone does not skip the engine."""

    def test_opt_out_still_installs_the_engine(self) -> None:
        self.offer("0.2.0")
        self.env["FORGEL_CODE_NO_MODIFY_PATH"] = "1"
        result = self.install()
        self.assertEqual(result.returncode, 0, self.report(result))
        self.assertEqual(self.engine_version(), "0.2.0")
        self.assertIn("Engine: forgel 0.2.0 installed", result.stdout)
        self.assertFalse(self.profile.exists(), "the profile was edited anyway")


if __name__ == "__main__":
    unittest.main()
