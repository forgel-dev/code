"""The timeout verdict follows the check's own duration, not a recorded marker.

A checked step that runs past the configured bound and exits on its own before
the watchdog has recorded a timeout must still fail: the installer times the
check itself, so the absence of a recorded timeout at the moment the result
becomes available is never evidence that the step kept its bound. That verdict
holds for a step that ends just after the bound, at it, or well past it. The
clock the check is timed with is a stub, so the moment the step ends relative to
the bound is forced explicitly and nothing waits for real time to pass.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_install import (  # noqa: E402  (path set up above)
    CHECK_PREFIX,
    INSTALL_SH,
    _Installation,
    _run,
    _shell_quote,
)

# The fabricated clock the installer is handed: the nanoseconds since the epoch
# it answers for the check's start, and the distance to the answer it gives for
# the check's result. The distances are expressed against the one-second bound
# under test: three times the bound has provably overrun it, one millisecond
# over it ends just after it, and a zero distance keeps the step well inside it.
CLOCK_BASE_NS = 1700000000000000000
CLOCK_OVERRUN_NS = 3000000000
CLOCK_JUST_AFTER_NS = 1001000000
CLOCK_AT_LIMIT_NS = 1000000000
CLOCK_IN_BOUND_NS = 0

# The stand-in for the clock the check is timed with, exactly as the external
# dependency records it: ``date +%s%N`` answers a timestamp, so the stub answers
# a timestamp too. It advances by FORGEL_STUB_CLOCK_STEP nanoseconds and counts
# its invocations in FORGEL_STUB_CLOCK_COUNTER, so the distance between the
# check's start and its result is fixed by the test and not by real time.
CLOCK_STUB = """#!/bin/sh
# Deterministic stand-in for `date +%s%N`.
# Answers FORGEL_STUB_CLOCK_BASE plus one FORGEL_STUB_CLOCK_STEP per call.
counter=$FORGEL_STUB_CLOCK_COUNTER
call=0
if [ -r "$counter" ]; then
    call=$(cat "$counter" 2>/dev/null) || call=0
fi
case $call in
    ''|*[!0-9]*) call=0 ;;
esac
call=$((call + 1))
printf '%s\\n' "$call" > "$counter" 2>/dev/null || true
printf '%s\\n' "$((FORGEL_STUB_CLOCK_BASE + (call - 1) * FORGEL_STUB_CLOCK_STEP))"
"""


def _fast_login_shell(
    directory: Path, exit_status: int, launcher: Optional[Path] = None
) -> Path:
    """A handled shell name whose login session answers at once.

    With a ``launcher`` it prints exactly the report a successful check prints,
    so only the verdict can fail it; without one it stays silent.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "bash"
    body = "#!/bin/sh\n"
    if launcher is not None:
        body += (
            "printf 'forgel-fresh-path=%s\\n' '/usr/bin:/bin'\n"
            "printf 'forgel-fresh-resolved=%s\\n' " + _shell_quote(launcher) + "\n"
        )
    body += "exit %d\n" % exit_status
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


class TimeoutVerdictOrderingTest(unittest.TestCase):
    """A checked step gets one verdict, forced through the real installer."""

    def setUp(self) -> None:
        self.installation = _Installation()
        self.addCleanup(self.installation.remove)
        self.base = self.installation.base
        self.home = self.installation.home
        self.launcher = self.installation.launcher
        self.tmp = self.base / "tmp"
        self.tmp.mkdir()
        self.env = dict(self.installation.env)
        self.env.pop("FORGEL_CODE_PROFILE", None)
        self.env["TMPDIR"] = str(self.tmp)
        self.env["FORGEL_CODE_TIMEOUT"] = "1"

    def controlled_clock(self, step_nanoseconds: int) -> None:
        """Hand the installer a clock that advances by that many nanoseconds."""
        stubs = self.base / "stubs"
        stubs.mkdir(parents=True, exist_ok=True)
        clock = stubs / "date"
        clock.write_text(CLOCK_STUB, encoding="utf-8")
        clock.chmod(0o755)
        self.env["PATH"] = os.pathsep.join(
            [str(stubs), self.env.get("PATH", "/usr/bin:/bin")]
        )
        self.env["FORGEL_STUB_CLOCK_COUNTER"] = str(self.base / "clock.count")
        self.env["FORGEL_STUB_CLOCK_BASE"] = str(CLOCK_BASE_NS)
        self.env["FORGEL_STUB_CLOCK_STEP"] = str(step_nanoseconds)

    def check_entries(self):
        """Every temporary entry the bounded check left under the test's TMPDIR."""
        return sorted(
            path.name
            for path in self.tmp.iterdir()
            if path.name.startswith(CHECK_PREFIX)
        )

    def install(self):
        return _run(["sh", str(INSTALL_SH)], self.base, self.env)

    def assert_overrun_reported_as_timeout(self, result) -> None:
        """The run failed and named the time limit, whatever else it printed."""
        self.assertNotEqual(
            result.returncode,
            0,
            "install.sh reported success for a step that overran its bound:\n%s\n%s"
            % (result.stdout, result.stderr),
        )
        self.assertIn("stopped after 1s", result.stderr)
        self.assertIn("did not put forgel-code on PATH", result.stderr)
        self.assertNotIn("PATH block written", result.stdout)
        self.assertNotIn("Fresh login shell check", result.stdout)

    def test_overrun_that_ends_before_the_timeout_is_recorded_is_a_failure(
        self,
    ) -> None:
        """An overrunning step that exits on its own first is still a timeout.

        The clock says the step outlived its one-second bound; the step itself
        prints the report of a successful check and exits at once, so its
        result is available while only the watchdog's ``finished`` marker
        exists. No ``timed-out`` marker is ever written, which is exactly the
        ordering that used to be reported as a verified success.
        """
        self.controlled_clock(CLOCK_OVERRUN_NS)
        self.env["SHELL"] = str(
            _fast_login_shell(self.base / "stubs", 0, self.launcher)
        )

        result = self.install()

        self.assert_overrun_reported_as_timeout(result)
        self.assertEqual(
            self.check_entries(),
            [],
            "the timed-out check left its private directory behind",
        )

    def test_step_ending_just_after_the_limit_is_a_failure(self) -> None:
        """A step that ends just after the bound fails and names the limit."""
        self.controlled_clock(CLOCK_JUST_AFTER_NS)
        self.env["SHELL"] = str(
            _fast_login_shell(self.base / "stubs", 0, self.launcher)
        )

        result = self.install()

        self.assert_overrun_reported_as_timeout(result)
        self.assertEqual(
            self.check_entries(),
            [],
            "the timed-out check left its private directory behind",
        )

    def test_step_ending_at_the_limit_is_a_failure(self) -> None:
        """A step that ends exactly at the bound fails and names the limit."""
        self.controlled_clock(CLOCK_AT_LIMIT_NS)
        self.env["SHELL"] = str(
            _fast_login_shell(self.base / "stubs", 0, self.launcher)
        )

        result = self.install()

        self.assert_overrun_reported_as_timeout(result)
        self.assertEqual(
            self.check_entries(),
            [],
            "the timed-out check left its private directory behind",
        )

    def test_step_inside_the_bound_keeps_its_own_nonzero_outcome(self) -> None:
        """A step that finished in time yields its own status, not a timeout."""
        self.controlled_clock(CLOCK_IN_BOUND_NS)
        self.env["SHELL"] = str(_fast_login_shell(self.base / "stubs", 3))

        result = self.install()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("the fresh login shell exited with status 3", result.stderr)
        self.assertNotIn("stopped after 1s", result.stderr)
        self.assertNotIn("PATH block written", result.stdout)
        self.assertEqual(
            self.check_entries(),
            [],
            "the failed check left its private directory behind",
        )


if __name__ == "__main__":
    unittest.main()
