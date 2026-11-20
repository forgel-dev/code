"""The ``test`` extra is declared once and published into the built metadata.

The declaration lives in ``pyproject.toml``; ``_build_backend.py`` reads it back
out of that file, so the wheel, the sdist and the source tree cannot disagree.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
BACKEND = ROOT / "_build_backend.py"

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
EXTRA = "test"
MARKER = 'extra == "%s"' % EXTRA


def _load_backend(root: Path, name: str):
    """Load a fresh copy of the in-tree backend that builds ``root``."""
    path = root / "_build_backend.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_extras() -> dict:
    """The extras ``pyproject.toml`` declares, read with a TOML parser."""
    text = PYPROJECT.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:  # Python 3.9 and 3.10 have no tomllib in the stdlib.
        backend = _load_backend(ROOT, "forgel_code_extras_declared")
        return backend._parse_extras(text)
    return tomllib.loads(text).get("project", {}).get("optional-dependencies", {})


def _clean_environment() -> dict:
    """The developer's environment without anything that could reach an index."""
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
        "PIP_CONFIG_FILE",
    ):
        env.pop(name, None)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PIP_CONFIG_FILE"] = os.devnull
    return env


def _candidate_pythons():
    """The interpreter running the tests first, then ``python3`` on PATH."""
    yield sys.executable
    for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10"):
        found = shutil.which(name)
        if found and found != sys.executable:
            yield found


def _pip_python() -> str:
    """A Python 3.9+ that owns pip, so the install test owns its toolchain."""
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
    raise AssertionError("no Python 3.9+ with pip found for the extras tests")


def _header_lines(metadata: str):
    """The metadata header block: every line before the first blank one."""
    lines = []
    for line in metadata.splitlines():
        if not line.strip():
            break
        lines.append(line)
    return lines


def _requires_dist(metadata: str):
    return [
        line.split(":", 1)[1].strip()
        for line in _header_lines(metadata)
        if line.startswith("Requires-Dist:")
    ]


def _provides_extra(metadata: str):
    return [
        line.split(":", 1)[1].strip()
        for line in _header_lines(metadata)
        if line.startswith("Provides-Extra:")
    ]


class ExtrasCase(unittest.TestCase):
    """A throw-away copy of the tree and the backend loaded for it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.base = base
        self.root = base / "project"
        shutil.copytree(ROOT, self.root, ignore=IGNORED)
        self.out = base / "dist"
        self.out.mkdir()
        self.backend = _load_backend(self.root, "forgel_code_extras_%s" % id(self))

    def wheel_metadata(self, name: str) -> str:
        with zipfile.ZipFile(self.out / name) as archive:
            data = archive.read("%s/METADATA" % self.backend.DIST_INFO)
        return data.decode("utf-8")

    def sdist_pkg_info(self, name: str) -> str:
        with tarfile.open(self.out / name) as archive:
            member = archive.extractfile("%s/PKG-INFO" % self.backend.SDIST_ROOT)
            assert member is not None
            return member.read().decode("utf-8")


class PyprojectExtrasTest(unittest.TestCase):
    """R1 and R2: one ``test`` extra, a lower bound, no runtime dependency."""

    def setUp(self) -> None:
        self.extras = _declared_extras()
        self.text = PYPROJECT.read_text(encoding="utf-8")

    def test_exactly_one_extra_named_test(self) -> None:
        self.assertEqual(sorted(self.extras), [EXTRA])

    def test_the_extra_declares_one_requirement(self) -> None:
        self.assertEqual(len(self.extras[EXTRA]), 1)

    def test_the_requirement_is_pytest_with_a_lower_bound_only(self) -> None:
        requirement = self.extras[EXTRA][0]
        match = re.fullmatch(
            r"pytest>=(?P<floor>[0-9][0-9A-Za-z.\-]*)", requirement
        )
        self.assertIsNotNone(
            match, "the test extra is not a lower-bounded pytest: %r" % requirement
        )
        for token in ("<", "<=", "==", "~=", ","):
            self.assertNotIn(token, requirement)

    def test_runtime_dependencies_stay_empty(self) -> None:
        self.assertIn("dependencies = []", self.text)
        backend = _load_backend(ROOT, "forgel_code_extras_empty")
        self.assertEqual(backend.EXTRAS, self.extras)

    def test_the_backend_does_not_restate_the_requirement(self) -> None:
        requirement = self.extras[EXTRA][0]
        source = BACKEND.read_text(encoding="utf-8")
        self.assertNotIn(requirement, source)
        self.assertNotIn('"pytest', source)
        self.assertNotIn("'pytest", source)
        for forbidden in ("tomli", "setuptools", "hatchling", "flit"):
            self.assertNotIn("import %s" % forbidden, source)


class WheelExtrasTest(ExtrasCase):
    """R3, R6 and R7: the extra reaches the wheel metadata."""

    def test_wheel_metadata_provides_the_test_extra(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        metadata = self.wheel_metadata(name)
        self.assertEqual(_provides_extra(metadata), [EXTRA])
        self.assertIn("Provides-Extra: %s" % EXTRA, _header_lines(metadata))

    def test_wheel_metadata_requires_pytest_behind_the_marker(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        metadata = self.wheel_metadata(name)
        declared = _declared_extras()[EXTRA]
        self.assertEqual(
            _requires_dist(metadata),
            ["%s; %s" % (requirement, MARKER) for requirement in declared],
        )

    def test_wheel_requirement_equals_the_pyproject_requirement(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        metadata = self.wheel_metadata(name)
        declared = _declared_extras()[EXTRA][0]
        expected = '%s; extra == "%s"' % (declared, EXTRA)
        self.assertIn(expected, _requires_dist(metadata))

    def test_prepared_metadata_matches_the_wheel(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        wheel = self.wheel_metadata(name)
        prepared_dir = self.base / "prepared"
        prepared_dir.mkdir()
        dist_info = self.backend.prepare_metadata_for_build_wheel(str(prepared_dir))
        prepared = (prepared_dir / dist_info / "METADATA").read_text(encoding="utf-8")
        self.assertEqual(prepared, wheel)

    def test_the_build_needs_no_requirements(self) -> None:
        self.assertEqual(self.backend.get_requires_for_build_wheel(), [])
        self.assertEqual(self.backend.get_requires_for_build_sdist(), [])


class SdistExtrasTest(ExtrasCase):
    """R6: the sdist PKG-INFO carries the same two lines as the wheel."""

    def test_sdist_pkg_info_matches_the_wheel_metadata(self) -> None:
        wheel_name = self.backend.build_wheel(str(self.out))
        sdist_name = self.backend.build_sdist(str(self.out))
        wheel = self.wheel_metadata(wheel_name)
        pkg_info = self.sdist_pkg_info(sdist_name)

        self.assertEqual(_provides_extra(pkg_info), [EXTRA])
        self.assertEqual(_requires_dist(pkg_info), _requires_dist(wheel))
        declared = _declared_extras()[EXTRA][0]
        self.assertIn(
            'Requires-Dist: %s; extra == "%s"' % (declared, EXTRA),
            _header_lines(pkg_info),
        )


class SingleSourceTest(ExtrasCase):
    """R4: rewriting the table in a copy changes the emitted metadata."""

    def test_rewriting_the_table_changes_the_metadata(self) -> None:
        declared = _declared_extras()[EXTRA][0]
        path = self.root / "pyproject.toml"
        original = path.read_text(encoding="utf-8")
        changed = original.replace(declared, "pytest>=99")
        self.assertNotEqual(
            changed, original, "the pyproject requirement was not found"
        )
        path.write_text(changed, encoding="utf-8")

        backend = _load_backend(self.root, "forgel_code_extras_rewritten")
        self.assertEqual(backend.EXTRAS, {EXTRA: ["pytest>=99"]})

        name = backend.build_wheel(str(self.out))
        with zipfile.ZipFile(self.out / name) as archive:
            metadata = archive.read("%s/METADATA" % backend.DIST_INFO).decode("utf-8")
        self.assertIn(
            'Requires-Dist: pytest>=99; extra == "%s"' % EXTRA,
            _header_lines(metadata),
        )
        self.assertNotIn(declared, metadata)


class FallbackParserTest(ExtrasCase):
    """R5: without ``tomllib`` the same metadata comes out."""

    def setUp(self) -> None:
        super().setUp()
        self.without_tomllib = self._load_without_tomllib()

    def _load_without_tomllib(self):
        saved = sys.modules.get("tomllib", "missing")
        sys.modules["tomllib"] = None  # makes ``import tomllib`` raise ImportError
        try:
            module = _load_backend(self.root, "forgel_code_extras_fallback")
        finally:
            if saved == "missing":
                sys.modules.pop("tomllib", None)
            else:
                sys.modules["tomllib"] = saved
        return module

    def test_the_fallback_returns_the_real_table(self) -> None:
        declared = _declared_extras()
        self.assertEqual(self.without_tomllib.EXTRAS, declared)

    def test_the_fallback_metadata_is_byte_identical(self) -> None:
        self.assertEqual(self.without_tomllib.EXTRAS, self.backend.EXTRAS)
        self.assertEqual(self.without_tomllib._metadata(), self.backend._metadata())
        self.assertIn(
            "Requires-Dist: %s; %s" % (_declared_extras()[EXTRA][0], MARKER),
            _header_lines(self.without_tomllib._metadata()),
        )

    def test_the_fallback_declares_no_build_requirement(self) -> None:
        self.assertEqual(self.without_tomllib.get_requires_for_build_wheel(), [])
        self.assertEqual(self.without_tomllib.get_requires_for_build_sdist(), [])

    def test_the_fallback_handles_comments_and_quote_styles(self) -> None:
        table = """
[project.optional-dependencies]
# a full-line comment
test = [
    'pytest>=7',  # an inline comment
    "coverage[toml]",
    'tomli; python_version < "3.11"',
]
docs = ["sphinx"]

[project.scripts]
forgel-code = "forgel_code.cli:main"
"""
        expected = {
            "test": [
                "pytest>=7",
                "coverage[toml]",
                'tomli; python_version < "3.11"',
            ],
            "docs": ["sphinx"],
        }
        self.assertEqual(self.without_tomllib._parse_extras(table), expected)

    def test_the_fallback_agrees_with_tomllib_on_the_sample(self) -> None:
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib is unavailable, so there is nothing to compare")
        sample = """
[project]
classifiers = [
    "License :: OSI Approved :: Apache Software License",
]
dependencies = []

[project.optional-dependencies]
test = ["pytest>=7"]
"""
        expected = tomllib.loads(sample)["project"]["optional-dependencies"]
        self.assertEqual(self.without_tomllib._parse_extras(sample), expected)

    def test_the_fallback_handles_the_empty_table(self) -> None:
        self.assertEqual(self.without_tomllib._parse_extras("[project]\n"), {})
        self.assertEqual(
            self.without_tomllib._parse_extras(
                "[project.optional-dependencies]\n"
            ),
            {},
        )


class OfflineExtraInstallTest(unittest.TestCase):
    """R15: a real, offline ``pip install`` of the local tree with ``[test]``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="forgel-code-extras-")
        base = Path(cls.tmp)
        cls.base = base
        cls.source = base / "source"
        shutil.copytree(ROOT, cls.source, ignore=IGNORED)
        cls.target = base / "target"
        cls.target.mkdir()
        cls.python = _pip_python()
        cls.env = _clean_environment()
        cls.install = cls._install()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _install(cls) -> subprocess.CompletedProcess:
        """pip, no index, no build isolation, no deps, into the temp target."""
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
                "--no-cache-dir",
                "--disable-pip-version-check",
                "--no-warn-script-location",
                "%s[%s]" % (cls.source, EXTRA),
            ],
            cwd=str(cls.base),
            env=cls.env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

    def test_install_exits_zero(self) -> None:
        self.assertEqual(
            self.install.returncode,
            0,
            "pip install .[%s] failed:\n%s\n%s"
            % (EXTRA, self.install.stdout, self.install.stderr),
        )

    def test_the_installed_metadata_declares_the_extra(self) -> None:
        self.assertEqual(self.install.returncode, 0, self.install.stderr)
        metadata_files = sorted(self.target.glob("forgel_code-*.dist-info/METADATA"))
        self.assertTrue(metadata_files, "pip wrote no forgel_code METADATA")
        metadata = metadata_files[0].read_text(encoding="utf-8")
        self.assertEqual(_provides_extra(metadata), [EXTRA])
        declared = _declared_extras()[EXTRA][0]
        self.assertIn("%s; %s" % (declared, MARKER), _requires_dist(metadata))


if __name__ == "__main__":
    unittest.main()
