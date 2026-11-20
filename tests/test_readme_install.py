"""Documentation guard: README.md documents exactly one one-command install path."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# The command the README must lead with, character for character.
INSTALL_COMMAND = (
    "curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh"
    " | sh"
)
INSTALL_TAG = "v0.1.0"

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*\S)\s*$")
FENCE_RE = re.compile(r"^\s*```")
# Anything that names another installation path for the client.
MAIN_PATH_TOKENS = (
    "pip install",
    "pip3 install",
    "python -m venv",
    "python3 -m venv",
    "pipx",
    "--user",
)
# The same alternatives anywhere in the file, Windows line excepted.
FORBIDDEN_TOKENS = ("pipx", "python -m venv", "python3 -m venv")
# An editable install: the shorthand flag as a word of its own, or the long one.
EDITABLE_RE = re.compile(r"(^|\s)-e(\s|$)|--editable\b")
PIPELINE_RE = re.compile(
    r"curl\b[^\n]*?"
    r"raw\.githubusercontent\.com/forgel-dev/code/"
    r"(?P<tag>v[0-9][^\s/]*)/install\.sh\b[^\n]*?\|\s*sh\b"
)


def _read_lines():
    return README.read_text(encoding="utf-8").splitlines()


def _windows_lines(lines):
    return [
        position
        for position, line in enumerate(lines)
        if "windows" in line.lower()
    ]


def _headings(lines):
    """``[(line_index, level, title)]`` for every ATX heading outside a fence."""
    found = []
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            found.append((index, len(match.group("hashes")), match.group("title")))
    return found


def _locate_section(lines, title):
    """``(start, end)`` line indices of the section ``title``, or ``None``."""
    headings = _headings(lines)
    for position, (index, level, heading) in enumerate(headings):
        if heading.strip().lower() != title:
            continue
        end = len(lines)
        for next_index, next_level, _ in headings[position + 1:]:
            if next_level <= level:
                end = next_index
                break
        return index + 1, end
    return None


def _section_range(lines, title):
    """``(start, end)`` line indices of the section whose heading reads ``title``."""
    found = _locate_section(lines, title)
    if found is None:
        raise AssertionError("README.md has no section titled %r" % title)
    return found


def _section_lines(lines, title):
    """The body lines of the section whose heading reads ``title``."""
    start, end = _section_range(lines, title)
    return lines[start:end]


def _code_blocks(lines):
    """``[(index_of_fence, [line, ...])]`` for every fenced code block."""
    blocks = []
    current = None
    start = 0
    for index, line in enumerate(lines):
        if FENCE_RE.match(line):
            if current is None:
                current = []
                start = index
            else:
                blocks.append((start, current))
                current = None
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        blocks.append((start, current))
    return blocks


def _commands(block):
    """The runnable lines of a block: no blanks, no comments."""
    return [
        line.strip()
        for line in block
        if line.strip() and not line.strip().startswith("#")
    ]


def _section_commands(lines, title):
    return [
        command
        for _, block in _code_blocks(_section_lines(lines, title))
        for command in _commands(block)
    ]


def assert_installer_command_is_first(lines):
    """The first installation command is the one-line installer, nothing before it."""
    section = _section_lines(lines, "install")
    blocks = _code_blocks(section)
    if not blocks:
        raise AssertionError("the install section shows no command block")
    commands = _commands(blocks[0][1])
    if not commands:
        raise AssertionError("the first command block of the install section is empty")
    if commands[0] != INSTALL_COMMAND:
        raise AssertionError(
            "the first installation command is not the one-command installer: %r"
            % commands[0]
        )
    index = next(
        position
        for position, line in enumerate(section)
        if line.strip() == INSTALL_COMMAND
    )
    for position, line in enumerate(section[:index]):
        lowered = line.lower()
        for token in MAIN_PATH_TOKENS:
            if token in lowered:
                raise AssertionError(
                    "the install section offers %r before the one-command "
                    "installer on line %d: %s" % (token, position + 1, line)
                )
    return INSTALL_COMMAND


def assert_no_alternative_main_path(lines):
    """Only the one-command installer is a main path; the Windows line is marked.

    The single exception is the ``## Tests`` section: it may show a
    ``pip install`` line that carries the ``[test]`` extra, because that line
    fetches the test runner rather than installing the client for daily use.
    """
    windows = set(_windows_lines(lines))
    start, end = _section_range(lines, "install")
    for position in range(start, end):
        if position in windows:
            continue
        lowered = lines[position].lower()
        for token in MAIN_PATH_TOKENS:
            if token in lowered:
                raise AssertionError(
                    "the install section names another installation path (%r): %s"
                    % (token, lines[position])
                )
    tests = _locate_section(lines, "tests")
    for position, line in enumerate(lines):
        if position in windows:
            continue
        lowered = line.lower()
        if "pip install" in lowered or "--user" in lowered:
            in_tests = tests is not None and tests[0] <= position < tests[1]
            if in_tests and "[test]" in lowered and "--user" not in lowered:
                continue
            raise AssertionError(
                "a pip install line sits on the main path: %s" % line
            )
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                raise AssertionError(
                    "README.md names another installation path (%r): %s"
                    % (token, line)
                )


def assert_no_editable_install(lines):
    """README.md never proposes an editable install the backend cannot serve."""
    for position, line in enumerate(lines):
        match = EDITABLE_RE.search(line.lower())
        if match:
            raise AssertionError(
                "README.md proposes an editable install (%r) on line %d: %s"
                % (match.group(0).strip(), position + 1, line)
            )


def assert_tests_section(lines):
    """The Tests section shows the ``[test]`` install and the no-install path."""
    commands = _section_commands(lines, "tests")
    extra_installs = [
        command
        for command in commands
        if "pip install" in command.lower() and "[test]" in command.lower()
    ]
    if len(extra_installs) != 1:
        raise AssertionError(
            "expected exactly one pip install line with the test extra in the "
            "Tests section, found %r" % (extra_installs,)
        )
    if "python -m pytest -q" not in commands:
        raise AssertionError(
            "the Tests section does not run python -m pytest -q: %r" % (commands,)
        )
    if "python -m unittest discover -s tests" not in commands:
        raise AssertionError(
            "the Tests section drops the no-install unittest path: %r"
            % (commands,)
        )
    return extra_installs[0]


def assert_prerequisites(lines):
    """Python 3 and the engine on PATH, with the custom engine path, are stated."""
    text = "\n".join(_section_lines(lines, "install"))
    lowered = text.lower()
    if "python 3" not in lowered:
        raise AssertionError(
            "the install section does not state the Python 3 requirement"
        )
    if "forgel" not in lowered or "engine" not in lowered:
        raise AssertionError(
            "the install section does not state the forgel engine requirement"
        )
    if "path" not in lowered:
        raise AssertionError("the install section does not put the engine on PATH")
    if "--engine" not in text or "$FORGEL_ENGINE" not in text:
        raise AssertionError(
            "the install section does not say how to point at a custom engine path"
        )


def assert_single_update_and_uninstall(lines):
    """Exactly one update line and exactly one uninstall line, same command."""
    installs = []
    updates = []
    uninstalls = []
    for line in lines:
        if "install.sh" not in line:
            continue
        if "--uninstall" in line:
            uninstalls.append(line.strip())
            continue
        match = PIPELINE_RE.search(line)
        if not match:
            continue
        if match.group("tag") == INSTALL_TAG:
            installs.append(line.strip())
        else:
            updates.append(line.strip())
    if installs != [INSTALL_COMMAND]:
        raise AssertionError(
            "expected exactly one installation command, found %r" % (installs,)
        )
    if len(updates) != 1:
        raise AssertionError(
            "expected exactly one update line, found %d: %r"
            % (len(updates), updates)
        )
    if len(uninstalls) != 1:
        raise AssertionError(
            "expected exactly one uninstall line, found %d: %r"
            % (len(uninstalls), uninstalls)
        )
    for command in (updates[0], uninstalls[0]):
        if "| sh" not in command:
            raise AssertionError(
                "the update or uninstall line is not the same command: %s" % command
            )
    return updates[0], uninstalls[0]


def assert_single_windows_line(lines):
    """One short Windows line, outside the main path, using ``pip install --user``."""
    windows = _windows_lines(lines)
    if len(windows) != 1:
        raise AssertionError(
            "expected exactly one Windows line, found %d: %r"
            % (len(windows), [lines[position] for position in windows])
        )
    position = windows[0]
    line = lines[position]
    lowered = line.lower()
    installer_positions = [
        index
        for index, candidate in enumerate(lines)
        if candidate.strip() == INSTALL_COMMAND
    ]
    if not installer_positions:
        raise AssertionError("README.md does not show the installation command")
    if position < installer_positions[0]:
        raise AssertionError("the Windows line preempts the main installation path")
    if "pip install --user" not in lowered:
        raise AssertionError(
            "the Windows line does not use pip install --user: %s" % line
        )
    if "not the main" not in lowered and "fallback" not in lowered:
        raise AssertionError(
            "the Windows line is not marked as outside the main path: %s" % line
        )


class ReadmeInstallTest(unittest.TestCase):
    """The README's installation section, read structurally."""

    def setUp(self) -> None:
        self.lines = _read_lines()

    def test_first_install_command_is_the_installer_line(self) -> None:
        self.assertEqual(
            assert_installer_command_is_first(self.lines), INSTALL_COMMAND
        )

    def test_no_alternative_main_path(self) -> None:
        assert_no_alternative_main_path(self.lines)

    def test_no_editable_install(self) -> None:
        self.assertIsNone(assert_no_editable_install(self.lines))

    def test_tests_section_shows_the_extra_install(self) -> None:
        command = assert_tests_section(self.lines)
        self.assertIn("[test]", command)

    def test_installer_line_is_inside_a_code_block(self) -> None:
        self.assertIn(INSTALL_COMMAND, _section_commands(self.lines, "install"))

    def test_prerequisites_are_kept(self) -> None:
        assert_prerequisites(self.lines)

    def test_one_update_line_and_one_uninstall_line(self) -> None:
        update, uninstall = assert_single_update_and_uninstall(self.lines)
        self.assertIn("| sh", update)
        self.assertIn("--uninstall", uninstall)

    def test_one_windows_line_outside_the_main_path(self) -> None:
        assert_single_windows_line(self.lines)


# A tiny README with the same shape, used to prove the guards fail as designed.
FIXTURE = [
    "# demo",
    "",
    "## Install",
    "",
    "```sh",
    INSTALL_COMMAND,
    "```",
    "",
    "Python 3 and the `forgel` engine on `PATH` are required; `--engine PATH` or",
    "`$FORGEL_ENGINE` point at a custom engine path.",
    "",
    "### Update",
    "",
    "```sh",
    "curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.1/install.sh | sh",
    "```",
    "",
    "### Uninstall",
    "",
    "```sh",
    "curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.0/install.sh | sh -s -- --uninstall",
    "```",
    "",
    "Windows is not the main installation method; use `python -m pip install --user`.",
    "",
    "## Commands",
    "",
]

# The Tests section the guards must accept: the extra install plus the
# no-install path.
TESTS_FIXTURE = [
    "## Tests",
    "",
    "```sh",
    'python3 -m pip install "https://example.invalid/code-v0.1.1.tar.gz[test]"',
    "python -m pytest -q",
    "```",
    "",
    "From a checkout, with nothing installed:",
    "",
    "```sh",
    "python -m unittest discover -s tests",
    "```",
    "",
]


class ChecksFailAsDesignedTest(unittest.TestCase):
    """The documentation guard rejects the regressions it exists for."""

    def assert_rejected(self, check, lines) -> None:
        with self.assertRaises(AssertionError):
            check(lines)

    def test_accepts_the_good_shape(self) -> None:
        self.assertEqual(
            assert_installer_command_is_first(FIXTURE), INSTALL_COMMAND
        )
        assert_no_alternative_main_path(FIXTURE)
        assert_prerequisites(FIXTURE)
        assert_single_update_and_uninstall(FIXTURE)
        assert_single_windows_line(FIXTURE)

    def test_accepts_the_extra_install_inside_the_tests_section(self) -> None:
        lines = FIXTURE + TESTS_FIXTURE
        assert_no_alternative_main_path(lines)
        assert_no_editable_install(lines)
        command = assert_tests_section(lines)
        self.assertIn("[test]", command)

    def test_rejects_a_tests_section_without_the_runner(self) -> None:
        lines = FIXTURE + [
            line for line in TESTS_FIXTURE if "pytest" not in line
        ]
        self.assert_rejected(assert_tests_section, lines)

    def test_rejects_a_tests_section_without_the_no_install_path(self) -> None:
        lines = FIXTURE + [
            line for line in TESTS_FIXTURE if "unittest" not in line
        ]
        self.assert_rejected(assert_tests_section, lines)

    def test_rejects_a_pip_install_outside_the_tests_section(self) -> None:
        lines = FIXTURE + ['python3 -m pip install "forgel-code[test]"']
        self.assert_rejected(assert_no_alternative_main_path, lines)

    def test_rejects_a_pip_install_in_the_tests_section_without_the_extra(
        self,
    ) -> None:
        lines = FIXTURE + [
            line.replace("[test]", "") for line in TESTS_FIXTURE
        ]
        self.assert_rejected(assert_no_alternative_main_path, lines)

    def test_rejects_an_editable_install(self) -> None:
        lines = FIXTURE + ["```sh", "python3 -m pip install -e .", "```"]
        self.assert_rejected(assert_no_editable_install, lines)

    def test_rejects_the_editable_long_flag(self) -> None:
        lines = FIXTURE + ["An editable install with `--editable` works."]
        self.assert_rejected(assert_no_editable_install, lines)

    def test_rejects_pip_before_the_installer(self) -> None:
        lines = (
            FIXTURE[:5]
            + ["python3 -m pip install --user forgel-code"]
            + FIXTURE[5:]
        )
        self.assert_rejected(assert_installer_command_is_first, lines)
        self.assert_rejected(assert_no_alternative_main_path, lines)

    def test_rejects_a_pip_install_first_command(self) -> None:
        lines = [
            FIXTURE[0],
            "",
            "## Install",
            "",
            "```sh",
            "python3 -m pip install --user forgel-code",
            "```",
        ] + FIXTURE[8:]
        self.assert_rejected(assert_installer_command_is_first, lines)

    def test_rejects_a_virtual_environment_block(self) -> None:
        lines = list(FIXTURE)
        lines.insert(7, "```")
        lines.insert(8, "python3 -m venv .venv")
        self.assert_rejected(assert_no_alternative_main_path, lines)

    def test_rejects_pipx_as_an_alternative(self) -> None:
        lines = FIXTURE + ["pipx is an optional alternative."]
        self.assert_rejected(assert_no_alternative_main_path, lines)

    def test_rejects_two_update_lines(self) -> None:
        lines = FIXTURE + [
            "```sh",
            "curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v0.1.2/install.sh | sh",
            "```",
        ]
        self.assert_rejected(assert_single_update_and_uninstall, lines)

    def test_rejects_a_missing_uninstall_line(self) -> None:
        lines = [line for line in FIXTURE if "--uninstall" not in line]
        self.assert_rejected(assert_single_update_and_uninstall, lines)

    def test_rejects_a_second_windows_line(self) -> None:
        self.assert_rejected(
            assert_single_windows_line,
            FIXTURE + ["Windows users can also use pip install --user."],
        )

    def test_rejects_a_windows_line_above_the_installer(self) -> None:
        lines = [
            "Windows: pip install --user forgel-code, not the main method.",
            "",
        ] + FIXTURE
        self.assert_rejected(assert_single_windows_line, lines)

    def test_rejects_windows_offered_as_the_main_path(self) -> None:
        lines = [
            line.replace(
                "is not the main installation method; use", "is the main path:"
            )
            for line in FIXTURE
        ]
        self.assert_rejected(assert_single_windows_line, lines)

    def test_rejects_a_missing_engine_prerequisite(self) -> None:
        lines = [
            line
            for line in FIXTURE
            if "engine" not in line.lower() and "--engine" not in line
        ]
        self.assert_rejected(assert_prerequisites, lines)


if __name__ == "__main__":
    unittest.main()
