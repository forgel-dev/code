"""Installation tests: the real ``install.sh`` runs offline into a temporary HOME."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
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

# Every profile file an uninstall cleans, wherever an install put the block.
# ``.bashrc`` is listed because a bash user's startup file may carry the block
# even when the login profile is a different file.
CANDIDATE_PROFILES = (
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
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

# The stub for the macOS Directory Service call, exactly as the external
# dependency records it. It answers ``dscl . -read <home> UserShell`` from
# FORGEL_STUB_USER_SHELL, so the macOS branch is deterministic off macOS.
DSCL_STUB = """#!/bin/sh
# Deterministic test stub for the macOS Directory Service call:
#   dscl . -read "$HOME" UserShell
# The shell is selected by FORGEL_STUB_USER_SHELL (default /bin/zsh).
if [ "$#" -ne 4 ] || [ "$1" != "." ] || [ "$2" != "-read" ] || [ "$4" != "UserShell" ]; then
    printf '%s\\n' 'dscl stub: supports only: dscl . -read <home> UserShell' >&2
    exit 64
fi
shell=${FORGEL_STUB_USER_SHELL:-/bin/zsh}
printf 'UserShell: %s\\n' "$shell"
"""



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
        "FORGEL_STUB_USER_SHELL",
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


def _write_dscl_stub(directory: Path) -> Path:
    """The macOS Directory Service stub, first on PATH for the detection tests."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "dscl"
    stub.write_text(DSCL_STUB, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _shell_that_keeps_shell_unset(env) -> str | None:
    """A shell interpreter that leaves an unset ``SHELL`` unset.

    ``bash`` assigns ``SHELL`` from the account database when it starts without
    one, so a script interpreted by it never sees an unset value. Hosts whose
    only shell does that cannot run the unset case, and other shells are tried
    first.
    """
    probe = 'printf "%s" "${SHELL-}"'
    for name in ("dash", "ksh", "ksh93", "mksh", "yash", "ash", "zsh"):
        found = shutil.which(name)
        if not found:
            continue
        try:
            result = subprocess.run(
                [found, "-c", probe],
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout == "":
            return found
    return None


def _fresh_login_shell(shell, home: Path) -> subprocess.CompletedProcess:
    """The shell as a login interactive shell started from a cleared environment."""
    return subprocess.run(
        [str(shell), "-l", "-i", "-c", "command -v forgel-code"],
        cwd=str(home),
        env={
            "HOME": str(home),
            "SHELL": str(shell),
            "TERM": "dumb",
            "PATH": "/usr/bin:/bin",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def _resolved_by(shell, home: Path) -> Path:
    """What ``command -v forgel-code`` answers in a fresh login shell of ``shell``."""
    fresh = _fresh_login_shell(shell, home)
    lines = [line for line in fresh.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError(
            "the fresh %s printed nothing:\n%s" % (shell, fresh.stderr)
        )
    return Path(lines[-1]).resolve()


def _path_occurrences(path_value: str, entry: Path) -> int:
    """How many colon-separated entries of ``path_value`` equal ``entry``."""
    return sum(1 for part in path_value.split(os.pathsep) if part == str(entry))


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


def _guarded_line(bin_dir: Path) -> str:
    """The line that prepends the launcher directory, guarded by ``case``."""
    return '    *) PATH="%s:$PATH" ;;' % bin_dir


def _unguarded_line(bin_dir: Path) -> str:
    """The bare ``export PATH=...`` line the block must never contain."""
    return 'export PATH="%s:$PATH"' % bin_dir


def _marked_block(bin_dir: Path) -> str:
    """The exact block the install path appends to the profile it selects."""
    return (
        "%s\n"
        'case ":$PATH:" in\n'
        '    *":%s:"*) ;;\n'
        '    *) PATH="%s:$PATH" ;;\n'
        "esac\n"
        "export PATH\n"
        "%s\n" % (MARKER_START, bin_dir, bin_dir, MARKER_END)
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
        self.assertIn(_guarded_line(self.bin_dir), text)
        self.assertNotIn(
            _unguarded_line(self.bin_dir),
            text,
            "the block carries a bare export PATH= line",
        )

    def test_install_reports_the_shell_profile_and_the_fresh_check(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/bin/sh", result.stdout)
        self.assertIn(str(self.profile), result.stdout)
        self.assertIn(
            "Fresh login shell check: command -v forgel-code -> %s" % self.launcher,
            result.stdout,
        )

    def test_login_shell_resolves_forgel_code_after_install(self) -> None:
        """A cleared, freshly started login shell finds the launcher unaided."""
        result = self.install()
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertEqual(
            _resolved_by("/bin/sh", self.home), self.launcher.resolve()
        )

    def test_failed_verification_reports_file_block_shell_and_path(self) -> None:
        ignored = self.home / ".ignored_profile"
        env = dict(self.env)
        env["FORGEL_CODE_PROFILE"] = str(ignored)
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(ignored), result.stderr)
        self.assertIn("login shell: /bin/sh", result.stderr)
        self.assertIn(MARKER_START, result.stderr)
        self.assertIn(_guarded_line(self.bin_dir), result.stderr)
        self.assertIn("PATH in the fresh shell:", result.stderr)
        self.assertIn("/usr/bin:/bin", result.stderr)
        self.assertEqual(_marker_count(ignored), 1)
        self.assertNotIn("PATH block written", result.stdout)

    def test_profile_the_login_shell_ignores_fails_verification(self) -> None:
        """A block in a file the login shell never reads fails the check."""
        ignored = self.home / ".bashrc"
        env = dict(self.env)
        env["FORGEL_CODE_PROFILE"] = str(ignored)
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertNotEqual(
            result.returncode,
            0,
            "install.sh claimed success for a profile /bin/sh does not read:\n%s"
            % result.stdout,
        )
        self.assertIn("did not put forgel-code on PATH", result.stderr)
        self.assertIn(str(ignored), result.stderr)
        self.assertIn("login shell: /bin/sh", result.stderr)
        self.assertIn(MARKER_START, result.stderr)
        self.assertIn(_guarded_line(self.bin_dir), result.stderr)
        self.assertIn("PATH in the fresh shell:", result.stderr)
        self.assertEqual(_marker_count(ignored), 1)
        self.assertFalse(
            self.profile.exists(), "the installer edited a second profile"
        )

    def test_repeated_install_keeps_one_block_and_one_path_entry(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        block = self.profile.read_text(encoding="utf-8")
        self.assertEqual(block, _marked_block(self.bin_dir))

        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.profile.read_text(encoding="utf-8"), block)
        self.assertEqual(_marker_count(self.profile), 1)
        self.assert_installed()

        fresh = _fresh_login_shell("/bin/sh", self.home)
        path_value = subprocess.run(
            ["/bin/sh", "-l", "-i", "-c", 'printf "%s" "$PATH"'],
            cwd=str(self.home),
            env={
                "HOME": str(self.home),
                "SHELL": "/bin/sh",
                "TERM": "dumb",
                "PATH": "/usr/bin:/bin",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        ).stdout.strip()
        self.assertTrue(fresh.returncode == 0, fresh.stderr)
        self.assertEqual(
            _path_occurrences(path_value, self.bin_dir),
            1,
            "the launcher directory appears more than once in %s" % path_value,
        )

    def test_second_run_is_idempotent(self) -> None:
        """Running the installer again leaves the profile exactly as it was."""
        first = self.install()
        self.assertEqual(
            first.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (first.stdout, first.stderr),
        )
        after_first = self.profile.read_text(encoding="utf-8")
        self.assertEqual(_marker_count(self.profile), 1)

        second = self.install()
        self.assertEqual(
            second.returncode,
            0,
            "the second install.sh failed:\n%s\n%s"
            % (second.stdout, second.stderr),
        )
        self.assertEqual(self.profile.read_text(encoding="utf-8"), after_first)
        self.assertEqual(_marker_count(self.profile), 1)
        self.assertNotIn(_unguarded_line(self.bin_dir), after_first)
        self.assert_installed()

    def test_guard_keeps_one_entry_when_several_profiles_are_sourced(self) -> None:
        """Sourcing each profile that carries the block adds the entry once."""
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        block = self.profile.read_text(encoding="utf-8")
        self.assertEqual(block, _marked_block(self.bin_dir))
        extra = []
        for name in (".bashrc", ".zshrc"):
            path = self.home / name
            path.write_text("# keep-%s\n" % name + block, encoding="utf-8")
            extra.append(path)

        script = '; '.join('. "%s"' % path for path in [self.profile] + extra)
        script += '; printf "%s" "$PATH"'
        sourced = subprocess.run(
            ["/bin/sh", "-c", script],
            cwd=str(self.home),
            env={
                "HOME": str(self.home),
                "SHELL": "/bin/sh",
                "PATH": "/usr/bin:/bin",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        self.assertEqual(sourced.returncode, 0, sourced.stderr)
        self.assertEqual(
            _path_occurrences(sourced.stdout.strip(), self.bin_dir),
            1,
            "the launcher directory appears more than once in %s"
            % sourced.stdout.strip(),
        )

    def test_piped_install_reads_the_script_from_stdin(self) -> None:
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
        self.assertEqual(
            _resolved_by("/bin/sh", self.home), self.launcher.resolve()
        )

    def test_piped_install_does_not_read_the_script_from_stdin(self) -> None:
        """The installer leaves the rest of stdin to the shell that read it."""
        script = INSTALL_SH.read_text(encoding="utf-8")
        tail = 'printf "forgel-stdin-tail-ok\\n"\n'
        result = subprocess.run(
            ["sh"],
            cwd=str(self.base),
            env=self.env,
            input=script + "\n" + tail,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        self.assertEqual(
            result.returncode,
            0,
            "piped install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertIn(
            "forgel-stdin-tail-ok",
            result.stdout,
            "the installer consumed the lines after the script on stdin",
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


class InstallerShellDetectionTest(InstallerCase):
    """The edited profile follows the login shell, not $SHELL alone."""

    def detection_environment(self, **extra) -> dict:
        """The base environment with an unusable $SHELL and the targets kept."""
        env = dict(self.env)
        env.pop("FORGEL_CODE_PROFILE", None)
        # An empty $SHELL is the unusable value a login shell reports when the
        # invoking process lost it; a removed one is re-exported by the shell.
        env["SHELL"] = ""
        env.update(extra)
        return env

    def zsh_environment(self):
        """A detection environment whose account login shell is ``zsh``.

        The macOS Directory Service stub answers for the account entry, so the
        branch is exercised on every host that has zsh installed.
        """
        zsh = shutil.which("zsh")
        if not zsh:
            self.skipTest("zsh is not installed")
        stub_dir = self.base / "stubs"
        _write_dscl_stub(stub_dir)
        env = self.detection_environment(
            FORGEL_STUB_USER_SHELL=zsh,
            PATH=os.pathsep.join(
                [str(stub_dir), os.environ.get("PATH", "/usr/bin:/bin")]
            ),
        )
        return zsh, env

    def test_zsh_without_shell_puts_the_block_in_zshrc(self) -> None:
        zsh, env = self.zsh_environment()
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        zshrc = self.home / ".zshrc"
        self.assertTrue(
            zshrc.is_file(),
            "no .zshrc in the temporary HOME; the installer said:\n%s\n%s\nhome: %s"
            % (
                result.stdout,
                result.stderr,
                sorted(path.name for path in self.home.iterdir()),
            ),
        )
        self.assertEqual(_marker_count(zshrc), 1)
        self.assertIn(_guarded_line(self.bin_dir), zshrc.read_text())
        self.assertFalse(
            (self.home / ".profile").exists(),
            "the installer fell back to ~/.profile",
        )
        self.assertIn("Login shell: %s" % zsh, result.stdout)
        self.assertEqual(_resolved_by(zsh, self.home), self.launcher.resolve())

    def test_unset_shell_puts_the_block_in_zshrc(self) -> None:
        """Without $SHELL at all the account login shell still decides."""
        zsh, env = self.zsh_environment()
        env.pop("SHELL", None)
        interpreter = _shell_that_keeps_shell_unset(env)
        if interpreter is None:
            self.skipTest(
                "every installed shell assigns SHELL from the account database "
                "when it starts without one, so an unset SHELL cannot reach "
                "the installer on this host"
            )
        result = _run([interpreter, str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        zshrc = self.home / ".zshrc"
        self.assertTrue(
            zshrc.is_file(),
            "no .zshrc in the temporary HOME; the installer said:\n%s\n%s\n"
            "home: %s"
            % (
                result.stdout,
                result.stderr,
                sorted(path.name for path in self.home.iterdir()),
            ),
        )
        self.assertEqual(_marker_count(zshrc), 1)
        self.assertIn(_guarded_line(self.bin_dir), zshrc.read_text())
        self.assertFalse(
            (self.home / ".profile").exists(),
            "the installer fell back to ~/.profile without a shell to name",
        )
        self.assertFalse(
            (self.home / ".bash_profile").exists(),
            "an unset $SHELL produced a bash decision",
        )
        self.assertIn("Login shell: %s" % zsh, result.stdout)
        self.assertEqual(_resolved_by(zsh, self.home), self.launcher.resolve())

    def test_bash_uses_an_existing_bash_profile(self) -> None:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not installed")
        profile = self.home / ".bash_profile"
        profile.write_text("export EDITOR=vi\n", encoding="utf-8")
        env = self.detection_environment(SHELL=bash)
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        text = profile.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("export EDITOR=vi\n"), text)
        self.assertEqual(_marker_count(profile), 1)
        self.assertIn(_guarded_line(self.bin_dir), text)
        self.assertFalse(
            (self.home / ".bashrc").exists(),
            "the installer created ~/.bashrc for a login bash",
        )
        self.assertEqual(_resolved_by(bash, self.home), self.launcher.resolve())

    def test_bash_creates_a_bash_profile_when_none_exists(self) -> None:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not installed")
        env = self.detection_environment(SHELL=bash)
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        profile = self.home / ".bash_profile"
        self.assertTrue(profile.is_file(), "no ~/.bash_profile was created")
        self.assertEqual(_marker_count(profile), 1)
        self.assertIn(_guarded_line(self.bin_dir), profile.read_text())
        for name in (".bashrc", ".bash_login"):
            self.assertFalse(
                (self.home / name).exists(), "the installer created %s" % name
            )
        self.assertEqual(_resolved_by(bash, self.home), self.launcher.resolve())

    def test_unknown_shell_writes_profile_and_warns(self) -> None:
        """A POSIX shell outside zsh and bash gets ~/.profile plus a warning."""
        posix_shell = "/bin/sh"
        env = self.detection_environment(SHELL=posix_shell)
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        profile = self.home / ".profile"
        self.assertTrue(profile.is_file(), "no ~/.profile was created")
        self.assertEqual(_marker_count(profile), 1)
        self.assertIn(_guarded_line(self.bin_dir), profile.read_text())
        self.assertIn("warning", result.stderr)
        self.assertIn(str(profile), result.stderr)
        self.assertIn(posix_shell, result.stderr)
        for name in (".zshrc", ".bash_profile", ".bash_login"):
            self.assertFalse(
                (self.home / name).exists(), "the installer created %s" % name
            )
        self.assertEqual(
            _resolved_by(posix_shell, self.home), self.launcher.resolve()
        )


def _hanging_shell(directory: Path) -> Path:
    """A handled shell name whose login session never finishes."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "bash"
    stub.write_text("#!/bin/sh\nsleep 120\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


class InstallerWatchdogTest(InstallerCase):
    """The post-write check is bounded, so a hanging shell cannot hang it."""

    def test_hanging_login_shell_is_killed_and_reported(self) -> None:
        stub = _hanging_shell(self.base / "stubs")
        profile = self.home / ".bash_profile"
        env = dict(self.env)
        env.pop("FORGEL_CODE_PROFILE", None)
        env["SHELL"] = str(stub)
        started = time.monotonic()
        result = _run(["sh", str(INSTALL_SH)], self.base, env)
        elapsed = time.monotonic() - started
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertLess(elapsed, 90, "the check did not honour its time bound")
        self.assertIn("did not put forgel-code on PATH", result.stderr)
        self.assertIn(str(profile), result.stderr)


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
        self.assertIn(_unguarded_line(self.bin_dir), result.stdout)
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
        self.assertIn(_unguarded_line(self.bin_dir), result.stdout)


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

    def test_uninstall_clears_every_candidate_profile(self) -> None:
        touched = {}
        for name in CANDIDATE_PROFILES:
            path = self.home / name
            path.write_text(
                "export EDITOR=vi\n" + _marked_block(self.bin_dir), encoding="utf-8"
            )
            touched[name] = path
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)

        result = self.install("--uninstall")
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        for name, path in touched.items():
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "export EDITOR=vi\n",
                "%s kept the PATH block" % name,
            )

    def test_uninstall_removes_the_marked_block_from_bashrc(self) -> None:
        """A bash home whose block lives in ``~/.bashrc`` is cleaned too."""
        bashrc = self.home / ".bashrc"
        bashrc.write_text(
            "# keep-before\nexport EDITOR=vi\n" + _marked_block(self.bin_dir)
            + "# keep-after\n",
            encoding="utf-8",
        )
        self.assertFalse(
            (self.home / ".bash_profile").exists(),
            "the fixture must not create ~/.bash_profile",
        )

        result = self.install("--uninstall")
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertEqual(
            bashrc.read_text(encoding="utf-8"),
            "# keep-before\nexport EDITOR=vi\n# keep-after\n",
        )
        self.assertEqual(_marker_count(bashrc), 0)
        self.assertNotIn(MARKER_END, bashrc.read_text(encoding="utf-8"))

    def test_repeated_uninstall_of_bashrc_is_idempotent(self) -> None:
        """A second ``--uninstall`` leaves every candidate file unchanged."""
        for name in CANDIDATE_PROFILES:
            (self.home / name).write_text(
                "# keep-%s\n" % name + _marked_block(self.bin_dir),
                encoding="utf-8",
            )

        first = self.install("--uninstall")
        self.assertEqual(
            first.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (first.stdout, first.stderr),
        )
        snapshot = {
            name: (self.home / name).read_text(encoding="utf-8")
            for name in CANDIDATE_PROFILES
        }
        for name, text in snapshot.items():
            self.assertEqual(text, "# keep-%s\n" % name, "%s kept the block" % name)

        second = self.install("--uninstall")
        self.assertEqual(
            second.returncode,
            0,
            "second uninstall failed:\n%s\n%s" % (second.stdout, second.stderr),
        )
        for name, text in snapshot.items():
            path = self.home / name
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                text,
                "%s changed on the second uninstall" % name,
            )
            self.assertEqual(_marker_count(path), 0, name)
        self.assertNotIn("Removed the PATH block", second.stdout)


class InstallerProfileOverrideUninstallTest(InstallerCase):
    """``--uninstall`` also cleans the profile ``FORGEL_CODE_PROFILE`` names."""

    def custom_profile(self) -> Path:
        return self.home / "custom_profile"

    def write_block(self, profile: Path) -> None:
        profile.write_text(
            "# keep-before\n"
            + _marked_block(self.bin_dir)
            + "# keep-after\n",
            encoding="utf-8",
        )

    def uninstall(self, **extra) -> subprocess.CompletedProcess:
        env = dict(self.env)
        env.update({name: str(value) for name, value in extra.items()})
        return _run(["sh", str(INSTALL_SH), "--uninstall"], self.base, env)

    def test_uninstall_removes_the_block_from_the_override_profile(self) -> None:
        profile = self.custom_profile()
        self.write_block(profile)
        result = self.uninstall(FORGEL_CODE_PROFILE=profile)
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertEqual(
            profile.read_text(encoding="utf-8"),
            "# keep-before\n# keep-after\n",
        )
        self.assertIn("Removed the PATH block from %s" % profile, result.stdout)

    def test_uninstall_removes_the_block_of_an_override_that_installed(self) -> None:
        # ``/bin/sh`` reads ``$HOME/.profile``, so an override naming it installs
        # cleanly and the block it wrote is the one the uninstall must remove.
        self.profile.write_text("# keep\n", encoding="utf-8")
        installed = self.install()
        self.assertEqual(
            installed.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (installed.stdout, installed.stderr),
        )
        self.assertEqual(_marker_count(self.profile), 1)

        result = self.uninstall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.profile.read_text(encoding="utf-8").rstrip("\n"), "# keep"
        )
        self.assertEqual(_marker_count(self.profile), 0)

    def test_uninstall_removes_the_block_a_failed_install_left(self) -> None:
        profile = self.custom_profile()
        env = dict(self.env)
        env["FORGEL_CODE_PROFILE"] = str(profile)
        failed = _run(["sh", str(INSTALL_SH)], self.base, env)
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertEqual(_marker_count(profile), 1)

        result = self.uninstall(FORGEL_CODE_PROFILE=profile)
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertEqual(_marker_count(profile), 0)
        self.assertNotIn(MARKER_END, profile.read_text(encoding="utf-8"))

    def test_uninstall_without_the_override_cleans_the_standard_profile(self) -> None:
        self.write_block(self.profile)
        env = {
            name: value
            for name, value in self.env.items()
            if name != "FORGEL_CODE_PROFILE"
        }
        result = _run(["sh", str(INSTALL_SH), "--uninstall"], self.base, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.profile.read_text(encoding="utf-8"),
            "# keep-before\n# keep-after\n",
        )

    def test_uninstall_tolerates_a_missing_override_profile(self) -> None:
        absent = self.home / "absent_profile"
        result = self.uninstall(FORGEL_CODE_PROFILE=absent)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(absent.exists(), "the uninstall created the override file")

    def test_uninstall_leaves_a_marker_free_override_profile_alone(self) -> None:
        profile = self.custom_profile()
        profile.write_text("no markers here\n", encoding="utf-8")
        result = self.uninstall(FORGEL_CODE_PROFILE=profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile.read_text(encoding="utf-8"), "no markers here\n")

    def test_override_naming_a_standard_profile_is_cleaned_once(self) -> None:
        self.profile.write_text(
            "# keep\n" + _marked_block(self.bin_dir) + "# tail\n",
            encoding="utf-8",
        )
        result = self.uninstall(FORGEL_CODE_PROFILE=self.profile)
        self.assertEqual(
            result.returncode,
            0,
            "uninstall failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        self.assertEqual(self.profile.read_text(encoding="utf-8"), "# keep\n# tail\n")
        self.assertEqual(
            result.stdout.count("Removed the PATH block from %s" % self.profile),
            1,
            result.stdout,
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
