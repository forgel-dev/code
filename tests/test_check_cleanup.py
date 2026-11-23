"""The bounded check leaves no process behind on its success and timeout paths.

A check whose login shell starts a background process must not leave that
process running once the check returns, whether the check succeeded or elapsed
its bound. The checked login shell leads a process group of its own and the
cleanup signals that group.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_install import (  # noqa: E402  (path set up above)
    CHECK_PREFIX,
    INSTALL_SH,
    _Installation,
    _process_exists,
    _run,
    _shell_quote,
)

# How long a test waits for a process to disappear after the check returned.
GONE_WAIT = 10.0

# The background process a checked login shell starts. It ignores the graceful
# stop, so only the forceful stop of the check's process group can end it; it
# bounds its own life, so a leak cannot outlive the test run by long.
BACKGROUND_LOOP = (
    "sh -c 'trap \"\" TERM; i=0; "
    "while [ \"$i\" -lt 120 ]; do sleep 1; i=$((i + 1)); done' "
    "< /dev/null > /dev/null 2>&1 &\n"
)


def _record_line(record: Path) -> str:
    """The shell line recording the background pid, its pid and its group."""
    return (
        'printf \'%s %s %s\\n\' "$!" "$$" "$(ps -o pgid= -p $$ | tr -d \' \')" > '
        + _shell_quote(record)
        + "\n"
    )


def _login_shell_starting_a_background_process(
    directory: Path, record: Path, launcher: Path
) -> Path:
    """A handled shell name that leaves a background process and succeeds."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "bash"
    stub.write_text(
        "#!/bin/sh\n"
        + BACKGROUND_LOOP
        + _record_line(record)
        + "printf 'forgel-fresh-path=%s\\n' '/usr/bin:/bin'\n"
        + "printf 'forgel-fresh-resolved=%s\\n' "
        + _shell_quote(launcher)
        + "\n"
        + "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _login_shell_starting_a_background_process_and_hanging(
    directory: Path, record: Path
) -> Path:
    """A handled shell name that leaves a background process and hangs."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "bash"
    stub.write_text(
        "#!/bin/sh\n"
        + BACKGROUND_LOOP
        + _record_line(record)
        + "trap '' TERM\n"
        + "while :; do sleep 1; done\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _wait_until_gone(pid: int, timeout: float = GONE_WAIT) -> bool:
    """Whether the process is gone within ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.05)
    return not _process_exists(pid)


class CheckCleanupTest(unittest.TestCase):
    """A check that starts a background process leaves none of it behind."""

    def setUp(self) -> None:
        self.installation = _Installation()
        self.addCleanup(self.installation.remove)
        self.base = self.installation.base
        self.home = self.installation.home
        self.launcher = self.installation.launcher
        self.record = self.base / "checked.pid"
        self.env = dict(self.installation.env)
        # The stub login shell defines the check, not the profile it reads.
        self.env.pop("FORGEL_CODE_PROFILE", None)

    def install(self, **extra) -> "object":
        env = dict(self.env)
        env.update({name: str(value) for name, value in extra.items()})
        return _run(["sh", str(INSTALL_SH)], self.base, env)

    def recorded(self, result=None):
        """The background pid, the checked shell's pid and the shell's group."""
        if not self.record.exists():
            raise AssertionError(
                "the checked shell recorded nothing at %s; base holds %r; "
                "install.sh said:\n%s\n%s"
                % (
                    self.record,
                    sorted(path.name for path in self.base.iterdir()),
                    getattr(result, "stdout", ""),
                    getattr(result, "stderr", ""),
                )
            )
        fields = self.record.read_text(encoding="utf-8").split()
        self.assertEqual(
            len(fields),
            3,
            "the checked shell recorded no process identity: %r" % (fields,),
        )
        return int(fields[0]), int(fields[1]), int(fields[2])

    def assert_own_group(self, shell_pid: int, group: int) -> None:
        self.assertEqual(
            group,
            shell_pid,
            "the checked shell %d was not put in a process group of its own"
            % shell_pid,
        )

    def test_successful_check_stops_its_background_process(self) -> None:
        stub = _login_shell_starting_a_background_process(
            self.base / "stubs", self.record, self.launcher
        )
        result = self.install(SHELL=stub)
        self.assertEqual(
            result.returncode,
            0,
            "install.sh failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        background, shell_pid, group = self.recorded(result)
        self.assert_own_group(shell_pid, group)
        self.assertTrue(
            _wait_until_gone(background),
            "the successful check left its background process %d running"
            % background,
        )

    def test_timed_out_check_stops_its_background_process(self) -> None:
        tmp = self.base / "tmp"
        tmp.mkdir(exist_ok=True)
        stub = _login_shell_starting_a_background_process_and_hanging(
            self.base / "stubs", self.record
        )
        result = self.install(SHELL=stub, TMPDIR=tmp, FORGEL_CODE_TIMEOUT=1)
        self.assertNotEqual(
            result.returncode,
            0,
            "install.sh reported success for a check that never answered:\n%s"
            % result.stdout,
        )
        self.assertIn("stopped after 1s", result.stderr)
        background, shell_pid, group = self.recorded(result)
        self.assert_own_group(shell_pid, group)
        self.assertTrue(
            _wait_until_gone(background),
            "the timed-out check left its background process %d running"
            % background,
        )
        self.assertEqual(
            sorted(
                path.name
                for path in tmp.iterdir()
                if path.name.startswith(CHECK_PREFIX)
            ),
            [],
            "the timed-out check left its private directory behind",
        )


if __name__ == "__main__":
    unittest.main()
