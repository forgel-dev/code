"""Installation tests: the real ``install.sh`` runs offline into a temporary HOME."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"

# The markers the installer writes around its PATH block.
MARKER_START = "# >>> forgel-code >>>"
MARKER_END = "# <<< forgel-code <<<"

# Shell profiles an install must not touch when the opt-out variable is set.
PROFILE_NAMES = (
    ".profile",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".bash_logout",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".kshrc",
)

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


def _source_version() -> str:
    """The single source of the version: ``forgel_code/__init__.py``."""
    text = (ROOT / "forgel_code" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise AssertionError("forgel_code/__init__.py declares no __version__")


def _clean_environment() -> dict:
    """The developer's environment without anything that could redirect us."""
    env = dict(os.environ)
    for name in (
        "FORGEL_ENGINE",
        "FORGEL_CODE_HOME",
        "FORGEL_CODE_BIN",
        "FORGEL_CODE_SOURCE",
        "FORGEL_CODE_PROFILE",
        "FORGEL_CODE_PYTHON",
        "FORGEL_CODE_TAG",
        "FORGEL_CODE_REPOSITORY",
        "FORGEL_CODE_NO_MODIFY_PATH",
        "FORGEL_CODE_NO_PROFILE_EDIT",
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
    return env


def _candidate_pythons():
    """The interpreter running the tests first, then ``python3`` on PATH."""
    yield sys.executable
    for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10"):
        found = shutil.which(name)
        if found and found != sys.executable:
            yield found


def _install_python() -> str:
    """A Python 3.9+ with pip, which is what the installer requires.

    The interpreter that runs the suite is not always the one that owns the
    client: a test runner installed for an older Python is a valid host for
    these tests, and the installer refuses an interpreter that is too old.
    """
    for candidate in _candidate_pythons():
        try:
            result = subprocess.run(
                [
                    candidate,
                    "-c",
                    "import pip, sys; "
                    "sys.exit(0 if sys.version_info >= (3, 9) else 1)",
                ],
                capture_output=True,
                env=_clean_environment(),
                timeout=TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return candidate
    raise AssertionError("no Python 3.9+ with pip found for the installer tests")


def _run(argv, cwd, env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(arg) for arg in argv],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def _installer_environment(home: Path, **extra) -> dict:
    """An environment whose HOME and targets all live under the temp tree."""
    env = _clean_environment()
    env["HOME"] = str(home)
    # A predictable profile choice even when the developer runs zsh or bash.
    env["SHELL"] = "/bin/sh"
    # The interpreter that owns pip here, so the test does not depend on which
    # python3 happens to be first on the developer's PATH.
    env["FORGEL_CODE_PYTHON"] = _install_python()
    env.update(extra)
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


def _marker_count(profile: Path) -> int:
    if not profile.is_file():
        return 0
    return sum(
        1
        for line in profile.read_text(encoding="utf-8").splitlines()
        if line.strip() == MARKER_START
    )


class InstallerCase(unittest.TestCase):
    """A temp HOME with the real installer run against a local source tree."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="forgel-code-installer-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = Path(self.tmp)
        self.source = self.base / "source"
        shutil.copytree(ROOT, self.source, ignore=IGNORED)
        self.home = self.base / "home"
        self.home.mkdir()
        self.prefix = self.base / "prefix"
        self.bin_dir = self.base / "bin"
        self.profile = self.home / ".profile"
        self.launcher = self.bin_dir / "forgel-code"
        self.env = _installer_environment(
            self.home,
            FORGEL_CODE_SOURCE=str(self.source),
            FORGEL_CODE_HOME=str(self.prefix),
            FORGEL_CODE_BIN=str(self.bin_dir),
            FORGEL_CODE_PROFILE=str(self.profile),
        )

    def install(self, *args) -> subprocess.CompletedProcess:
        return _run(["sh", str(INSTALL_SH), *args], self.base, self.env)

    def launcher_version(self) -> subprocess.CompletedProcess:
        """The launcher from a shell that never activated anything."""
        return _run([str(self.launcher), "--version"], self.base, self.env)

    def assert_installed(self) -> None:
        self.assertTrue(
            self.launcher.is_file(), "no launcher at %s" % self.launcher
        )
        self.assertTrue(
            os.access(str(self.launcher), os.X_OK),
            "the launcher is not executable",
        )
        version = _installed_version(self.prefix)
        result = self.launcher_version()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "forgel-code %s" % version)


class InstallerTest(InstallerCase):
    """One command installs the client, without network and without a venv."""

    def test_script_is_executable_and_parses_with_sh(self) -> None:
        self.assertTrue(INSTALL_SH.is_file(), "no install.sh at the repository root")
        self.assertTrue(
            os.access(str(INSTALL_SH), os.X_OK), "install.sh is not executable"
        )
        result = _run(["sh", "-n", str(INSTALL_SH)], ROOT, _clean_environment())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_exits_zero_and_prints_the_version(self) -> None:
        result = self.install()
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertIn("forgel-code %s" % _source_version(), result.stdout)

    def test_install_creates_the_launcher_in_the_bin_directory(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_installed()

    def test_launcher_prints_the_installed_version(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_installed()
        self.assertEqual(_installed_version(self.prefix), _source_version())

    def test_profile_gets_one_marked_path_block(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.profile.read_text(encoding="utf-8")
        self.assertEqual(_marker_count(self.profile), 1, text)
        self.assertIn(MARKER_END, text)
        self.assertIn('export PATH="%s:$PATH"' % self.bin_dir, text)

    def test_second_run_is_idempotent(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        block = self.profile.read_text(encoding="utf-8")

        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.profile.read_text(encoding="utf-8"), block)
        self.assertEqual(_marker_count(self.profile), 1)
        self.assert_installed()

    def test_piped_install_does_not_read_the_script_from_stdin(self) -> None:
        """The documented ``curl ... | sh`` shape, with the script on stdin."""
        script = INSTALL_SH.read_text(encoding="utf-8")
        result = subprocess.run(
            ["sh"],
            cwd=str(self.base),
            env=self.env,
            input=script,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        self.assertEqual(
            result.returncode,
            0,
            "piped install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assert_installed()
        self.assertEqual(_marker_count(self.profile), 1)

    def test_missing_interpreter_fails_with_a_message(self) -> None:
        env = dict(self.env)
        env["FORGEL_CODE_PYTHON"] = str(self.base / "no-such-python")
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python", result.stderr.lower())
        self.assertFalse(self.launcher.exists())


class InstallerOptOutTest(InstallerCase):
    """The opt-out variable keeps every profile file untouched."""

    def opt_out_environment(self) -> dict:
        env = dict(self.env)
        env["FORGEL_CODE_NO_MODIFY_PATH"] = "1"
        return env

    def profiles(self):
        """Shell profile files in the temporary HOME, created or not."""
        return sorted(
            path.name for path in self.home.iterdir() if path.name in PROFILE_NAMES
        )

    def test_opt_out_leaves_the_profile_untouched(self) -> None:
        env = self.opt_out_environment()
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertFalse(self.profile.exists(), "the profile was created")
        self.assertEqual(self.profiles(), [], "a shell profile was written")
        self.assertIn('export PATH="%s:$PATH"' % self.bin_dir, result.stdout)
        self.assertTrue(self.launcher.is_file())

    def test_opt_out_writes_nothing_outside_the_target_directories(self) -> None:
        env = self.opt_out_environment()
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.profiles(), [], "a shell profile was written")
        self.assertEqual(
            sorted(path.name for path in self.base.iterdir()),
            ["bin", "home", "prefix", "source"],
            "the installer wrote outside its target directories",
        )
        for entry in self.home.iterdir():
            self.assertFalse(
                entry.is_dir() and entry.name in PROFILE_NAMES,
                "the installer created a profile directory: %s" % entry,
            )

    def test_legacy_opt_out_name_is_honoured_too(self) -> None:
        env = dict(self.env)
        env["FORGEL_CODE_NO_PROFILE_EDIT"] = "1"
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.profile.exists())
        self.assertIn('export PATH="%s:$PATH"' % self.bin_dir, result.stdout)


class InstallerUninstallTest(InstallerCase):
    """``--uninstall`` removes the installation and the block it added."""

    def test_uninstall_removes_everything(self) -> None:
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertTrue(self.launcher.is_file())
        self.assertEqual(_marker_count(self.profile), 1)

        result = self.install("--uninstall")
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertFalse(self.prefix.exists(), "the installation directory stayed")
        self.assertFalse(self.launcher.exists(), "the launcher stayed")
        self.assertEqual(_marker_count(self.profile), 0)
        self.assertNotIn(MARKER_END, self.profile.read_text(encoding="utf-8"))

    def test_uninstall_keeps_the_rest_of_the_profile(self) -> None:
        self.profile.write_text("export EDITOR=vi\n", encoding="utf-8")
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        result = self.install("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.profile.read_text(encoding="utf-8"), "export EDITOR=vi\n"
        )


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
        cls.python = _install_python()
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
                cls.python,
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

    def _run_local(self, args) -> subprocess.CompletedProcess:
        """Run an installed entry point against the temp target only."""
        env = dict(self.env)
        env["PYTHONPATH"] = str(self.target)
        return _run(args, self.base, env)

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
        result = self._run_local([script, "--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().split()[-1], _installed_version(self.target)
        )
        self.assertIn("forgel-code", result.stdout)

    def test_module_entry_point_prints_the_installed_version(self) -> None:
        self.assertEqual(self.install.returncode, 0, self.install.stderr)
        result = self._run_local([self.python, "-m", "forgel_code", "--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().split()[-1], _installed_version(self.target)
        )
        self.assertIn("forgel-code", result.stdout)


def _pip_environment(base: Path) -> dict:
    """An environment that cannot reach an index or a proxy."""
    env = _clean_environment()
    env["FORGEL_CODE_HOME"] = str(base / "home")
    return env


if __name__ == "__main__":
    unittest.main()
