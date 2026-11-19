"""Documentation test: README.md leads with plain pip, pipx is optional and late."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*\S)\s*$")
FENCE_RE = re.compile(r"^\s*```")
# A pip install run through the interpreter: no pipx, no bare ``pip`` script.
PLAIN_PIP_PREFIXES = ("python3 -m pip install", "python -m pip install")
VCS_PIN_RE = re.compile(r"@(?P<ref>[^\s\"'#]+)")
EXACT_VERSION_RE = re.compile(r"==(?P<version>[0-9][^\s\"'#]*)")
# A ref that names a moving branch is not a pinned revision.
BRANCH_REFS = frozenset({"head", "main", "master", "trunk", "develop", "default"})


def _read_lines():
    return README.read_text(encoding="utf-8").splitlines()


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


def _section_lines(lines, title):
    """The body lines of the first section whose heading reads ``title``."""
    headings = _headings(lines)
    for position, (index, level, heading) in enumerate(headings):
        if heading.strip().lower() != title:
            continue
        end = len(lines)
        for next_index, next_level, _ in headings[position + 1:]:
            if next_level <= level:
                end = next_index
                break
        return lines[index + 1:end]
    raise AssertionError("README.md has no section titled %r" % title)


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


def _install_commands(commands):
    return [
        command
        for command in commands
        if "pip install" in command or "pipx install" in command
    ]


def _is_plain_pip(command):
    return command.startswith(PLAIN_PIP_PREFIXES)


def _is_pinned(command):
    """True when the command names an exact revision, not a moving branch."""
    for match in VCS_PIN_RE.finditer(command):
        if match.group("ref").strip().lower() not in BRANCH_REFS:
            return True
    return bool(EXACT_VERSION_RE.search(command))


def _assert_first_install_is_plain_pip(lines):
    """The first install command of the install section must be plain pip."""
    install = _section_lines(lines, "install")
    blocks = [block for _, block in _code_blocks(install)]
    if not blocks:
        raise AssertionError("the install section shows no command block")
    commands = _commands(blocks[0])
    installs = _install_commands(commands)
    if not installs:
        raise AssertionError(
            "the first command block of the install section has no pip install command"
        )
    if not _is_plain_pip(installs[0]):
        raise AssertionError(
            "the first install command is not plain pip: %s" % installs[0]
        )
    for command in commands:
        if "pipx" in command:
            raise AssertionError(
                "the first command block needs pipx: %s" % command
            )
    return installs[0]


def _assert_pipx_is_optional_and_late(lines):
    """pipx is at most one line, marked optional, after the pip instructions."""
    lowered = [line.lower() for line in lines]
    total = sum(line.count("pipx") for line in lowered)
    if total == 0:
        return
    mentions = [index for index, line in enumerate(lowered) if "pipx" in line]
    if total > 1:
        raise AssertionError("pipx is mentioned %d times; at most one is allowed" % total)
    if len(mentions) != 1:
        raise AssertionError("pipx is not on a single line")
    index = mentions[0]
    if "optional" not in lowered[index]:
        raise AssertionError("the pipx line is not marked optional: %s" % lines[index])
    pip_lines = [
        position
        for position, line in enumerate(lowered)
        if _is_plain_pip(line.strip())
    ]
    if not pip_lines:
        raise AssertionError("README.md documents no plain pip install command")
    if index < min(pip_lines):
        raise AssertionError("pipx appears before the pip installation instructions")


class InstallSectionTest(unittest.TestCase):
    """The install section, read structurally: headings plus fenced blocks."""

    def setUp(self) -> None:
        self.lines = _read_lines()
        self.install = _section_lines(self.lines, "install")
        self.text = "\n".join(self.install)

    def test_first_install_command_is_plain_pip(self) -> None:
        command = _assert_first_install_is_plain_pip(self.lines)
        self.assertTrue(_is_plain_pip(command), command)

    def test_first_install_command_is_pinned(self) -> None:
        command = _assert_first_install_is_plain_pip(self.lines)
        self.assertTrue(_is_pinned(command), command)

    def test_virtual_environment_install(self) -> None:
        commands = [
            command
            for block in _code_blocks(self.install)
            for command in _commands(block[1])
        ]
        self.assertTrue(
            any(command.startswith("python3 -m venv") for command in commands),
            commands,
        )
        self.assertTrue(
            any("activate" in command for command in commands),
            commands,
        )
        self.assertTrue(
            any(_is_plain_pip(command) and "--user" not in command for command in commands),
            commands,
        )

    def test_user_install(self) -> None:
        commands = [
            command
            for block in _code_blocks(self.install)
            for command in _commands(block[1])
        ]
        user_installs = [
            command
            for command in commands
            if _is_plain_pip(command) and "--user" in command
        ]
        self.assertTrue(user_installs, commands)
        self.assertIn("without a virtual environment", self.text.lower())

    def test_executable_location_and_path_help(self) -> None:
        self.assertIn("bin/forgel-code", self.text)
        self.assertIn("Scripts", self.text)
        self.assertIn("~/.local/bin", self.text)
        self.assertIn("PATH", self.text)
        self.assertIn("export PATH=", self.text)
        self.assertIn("pip show -f forgel-code", self.text)

    def test_module_fallback_with_version_check(self) -> None:
        self.assertIn("python3 -m forgel_code --version", self.text)
        self.assertIn("forgel-code --version", self.text)

    def test_update_section_switches_pinned_revision(self) -> None:
        update = "\n".join(_section_lines(self.lines, "update"))
        lowered = update.lower()
        self.assertIn("pip install --upgrade", update)
        self.assertIn("--force-reinstall", update)
        self.assertIn("unchanged", lowered)
        self.assertIn("commit", lowered)
        self.assertIn("version", lowered)
        commands = [
            command
            for block in _code_blocks(update.splitlines())
            for command in _commands(block[1])
        ]
        upgrades = [command for command in commands if "--upgrade" in command]
        self.assertTrue(upgrades, commands)
        self.assertTrue(all(_is_plain_pip(command) for command in upgrades), commands)
        self.assertTrue(any(_is_pinned(command) for command in upgrades), commands)

    def test_pipx_is_optional_and_after_the_pip_instructions(self) -> None:
        _assert_pipx_is_optional_and_late(self.lines)

    def test_existing_constraints_are_kept(self) -> None:
        lowered = self.text.lower()
        self.assertIn("no dependencies", lowered)
        self.assertIn("offline", lowered)
        self.assertIn("pip install -e", lowered)
        self.assertIn("editable installs", lowered)
        self.assertIn("--engine", self.text)
        self.assertIn("$FORGEL_ENGINE", self.text)


# A tiny README with the same shape, used to prove the checks fail as designed.
FIXTURE = [
    "# demo",
    "",
    "## Install",
    "",
    "```sh",
    'python3 -m pip install "git+https://example.invalid/demo@v1.0.0"',
    "```",
    "",
    "1. Activate the virtual environment.",
    "",
    "## Commands",
    "",
    "pipx is an optional isolation alternative.",
]


class ChecksFailAsDesignedTest(unittest.TestCase):
    """The documentation checks reject the regressions they exist for."""

    def test_accepts_the_good_shape(self) -> None:
        command = _assert_first_install_is_plain_pip(FIXTURE)
        self.assertTrue(_is_pinned(command), command)
        _assert_pipx_is_optional_and_late(FIXTURE)

    def test_rejects_pipx_as_the_first_install_command(self) -> None:
        lines = [
            'pipx install "git+https://example.invalid/demo@v1.0.0"'
            if line.startswith("python3 -m pip install")
            else line
            for line in FIXTURE
        ]
        with self.assertRaises(AssertionError):
            _assert_first_install_is_plain_pip(lines)

    def test_rejects_a_bare_pip_script(self) -> None:
        lines = [
            'pip install "git+https://example.invalid/demo@v1.0.0"'
            if line.startswith("python3 -m pip install")
            else line
            for line in FIXTURE
        ]
        with self.assertRaises(AssertionError):
            _assert_first_install_is_plain_pip(lines)

    def test_rejects_a_floating_branch(self) -> None:
        lines = [
            'python3 -m pip install "git+https://example.invalid/demo@main"'
            if line.startswith("python3 -m pip install")
            else line
            for line in FIXTURE
        ]
        command = _assert_first_install_is_plain_pip(lines)
        self.assertFalse(_is_pinned(command), command)

    def test_rejects_pipx_before_the_pip_instructions(self) -> None:
        lines = ["pipx is optional.", ""] + FIXTURE
        with self.assertRaises(AssertionError):
            _assert_pipx_is_optional_and_late(lines)

    def test_rejects_pipx_without_the_optional_marker(self) -> None:
        lines = [
            "pipx installs it too." if "pipx" in line else line for line in FIXTURE
        ]
        with self.assertRaises(AssertionError):
            _assert_pipx_is_optional_and_late(lines)

    def test_rejects_two_pipx_mentions(self) -> None:
        lines = FIXTURE + ["pipx is optional."]
        with self.assertRaises(AssertionError):
            _assert_pipx_is_optional_and_late(lines)


if __name__ == "__main__":
    unittest.main()
