"""The help description stays the text the previous release printed."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forgel_code import cli  # noqa: E402

# The description the help output carried before the interactive client was
# added: one sentence, no mention of the interactive session.
RELEASED_DESCRIPTION = (
    "Thin console client for Forgel over the engine's machine-readable commands."
)


class HelpDescriptionTest(unittest.TestCase):
    def test_the_parser_description_is_the_released_text(self) -> None:
        self.assertEqual(cli.build_parser().description, RELEASED_DESCRIPTION)

    def test_the_help_output_carries_the_released_text(self) -> None:
        text = cli.build_parser().format_help()
        self.assertIn(RELEASED_DESCRIPTION, text)

    def test_the_help_output_does_not_advertise_the_interactive_session(self) -> None:
        text = cli.build_parser().format_help().lower()
        self.assertNotIn("interactive", text)

    def test_help_printed_as_a_process_carries_the_released_text(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "forgel_code", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(RELEASED_DESCRIPTION, completed.stdout)
        self.assertNotIn("interactive", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
