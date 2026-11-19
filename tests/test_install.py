"""Installation test: plain pip installs the client offline into a temp target."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Copying the checkout keeps the build away from the real tree and from
# leftovers of an interrupted run, exactly like the packaging tests do.
IGNORED = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".wheelcheck",
    "*.egg-info",
    "*.pyc",
)

TIMEOUT = 600
SCRIPT_NAMES = ("forgel-code", "forgel-code.exe", "forgel-code-script.py")


def _pip_environment(base: Path) -> dict:
    """An environment that cannot reach an index or a proxy."""
    env = dict(os.environ)
    for name in (
        "FORGEL_ENGINE",
        "FORGEL_CODE_HOME",
        "FORGEL_CODE_TIMEOUT",
        "FORGEL_STUB_MODE",
        "PYTHONPATH",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
    ):
        env.pop(name, None)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["FORGEL_CODE_HOME"] = str(base / "home")
    return env


def _installed_version(target: Path) -> str:
    """The version METADATA of the installed distribution carries."""
    for metadata in sorted(target.glob("forgel_code-*.dist-info/METADATA")):
        for line in metadata.read_text(encoding="utf-8").splitlines():
            if line.startswith("Version: "):
                return line.split(":", 1)[1].strip()
    raise AssertionError("no forgel_code dist-info with a Version in %s" % target)


def _script_path(target: Path):
    """Where pip wrote the ``forgel-code`` console script for a --target run."""
    for directory in (target, target / "bin", target / "Scripts"):
        for name in SCRIPT_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


class PlainPipInstallTest(unittest.TestCase):
    """A plain, offline ``python3 -m pip install`` of the local source tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="forgel-code-install-")
        base = Path(cls.tmp)
        cls.base = base
        cls.source = base / "source"
        shutil.copytree(ROOT, cls.source, ignore=IGNORED)
        cls.target = base / "target"
        cls.target.mkdir()
        cls.env = _pip_environment(base)
        cls.install = cls._install()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _install(cls) -> subprocess.CompletedProcess:
        """Plain pip, no index, no build isolation, into the temp target."""
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(cls.target),
                "--no-index",
                "--no-build-isolation",
                "--no-deps",
                "--disable-pip-version-check",
                "--no-warn-script-location",
                str(cls.source),
            ],
            cwd=str(cls.base),
            env=cls.env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

    def _run(self, args) -> subprocess.CompletedProcess:
        """Run an installed entry point against the temp target only."""
        env = dict(self.env)
        env["PYTHONPATH"] = str(self.target)
        env["PATH"] = os.pathsep.join(
            [str(self.base / "bin"), env.get("PATH", "")]
        )
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=str(self.base),
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

    def test_install_exits_zero(self) -> None:
        self.assertEqual(
            self.install.returncode,
            0,
            "plain pip install failed:\n%s\n%s" % (
                self.install.stdout,
                self.install.stderr,
            ),
        )

    def test_install_needs_no_network_and_no_build_requirements(self) -> None:
        self.assertEqual(self.install.returncode, 0, self.install.stderr)
        self.assertEqual(_installed_version(self.target), _source_version())

    def test_console_script_prints_the_installed_version(self) -> None:
        self.assertEqual(self.install.returncode, 0, self.install.stderr)
        script = _script_path(self.target)
        self.assertIsNotNone(
            script,
            "pip wrote no forgel-code script into %s" % self.target,
        )
        result = self._run([script, "--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().split()[-1], _installed_version(self.target)
        )
        self.assertIn("forgel-code", result.stdout)

    def test_module_entry_point_prints_the_installed_version(self) -> None:
        self.assertEqual(self.install.returncode, 0, self.install.stderr)
        result = self._run([sys.executable, "-m", "forgel_code", "--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().split()[-1], _installed_version(self.target)
        )
        self.assertIn("forgel-code", result.stdout)


def _source_version() -> str:
    """The single source of the version: ``forgel_code/__init__.py``."""
    text = (ROOT / "forgel_code" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"\'')
    raise AssertionError("forgel_code/__init__.py declares no __version__")


if __name__ == "__main__":
    unittest.main()
