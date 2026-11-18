"""Packaging tests: the wheel and the sdist really carry the ``forgel-code`` package."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import forgel_code  # noqa: E402  (the package the backend is supposed to pack)

VERSION = forgel_code.__version__

# The whole checkout is copied, so a test never writes into the real tree and a
# build never picks up a leftover from an interrupted run.
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


def _load_backend(root: Path):
    """Load a fresh copy of the in-tree backend that builds ``root``."""
    path = root / "_build_backend.py"
    spec = importlib.util.spec_from_file_location(
        "forgel_code_build_backend_%s" % root.parent.name, path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_env() -> dict:
    """An environment that cannot redirect ``forgel_code`` elsewhere."""
    env = dict(os.environ)
    for name in (
        "FORGEL_ENGINE",
        "FORGEL_CODE_HOME",
        "FORGEL_CODE_TIMEOUT",
        "FORGEL_STUB_MODE",
    ):
        env.pop(name, None)
    env["FORGEL_CODE_HOME"] = tempfile.mkdtemp(prefix="forgel-code-home-")
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return env


class TempProjectTest(unittest.TestCase):
    """Build from a throw-away copy so no test touches the checked-out tree."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "project"
        shutil.copytree(ROOT, self.root, ignore=IGNORED)
        self.out = base / "dist"
        self.out.mkdir()
        self.backend = _load_backend(self.root)

    def write_package_extra(self) -> None:
        """Add a subpackage and package data to the temporary copy."""
        extra = self.root / "forgel_code" / "extra"
        extra.mkdir()
        (extra / "__init__.py").write_text("", encoding="utf-8")
        (extra / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        (extra / "schema.json").write_text("{}\n", encoding="utf-8")
        (self.root / "forgel_code" / "data.txt").write_text(
            "package data\n", encoding="utf-8"
        )

    def version_output(self) -> str:
        """``forgel-code --version`` from the package in this checkout."""
        from forgel_code.cli import main

        stdout = io.StringIO()
        old_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(_clean_env())
        try:
            with contextlib.redirect_stdout(stdout):
                code = main(["--version"])
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        self.assertEqual(code, 0)
        return stdout.getvalue().strip()


class BuildBackendTest(TempProjectTest):
    def test_wheel_contains_the_client_and_the_console_script(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        self.assertEqual(name, self.backend.WHEEL_NAME)
        wheel = self.out / name
        self.assertTrue(wheel.is_file())

        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            for module in sorted((self.root / "forgel_code").glob("*.py")):
                self.assertIn("forgel_code/%s" % module.name, names)
            dist_info = self.backend.DIST_INFO
            self.assertIn("%s/METADATA" % dist_info, names)
            self.assertIn("%s/RECORD" % dist_info, names)
            entry_points = archive.read("%s/entry_points.txt" % dist_info)
            self.assertEqual(
                entry_points.decode("utf-8"),
                "[console_scripts]\nforgel-code = forgel_code.cli:main\n",
            )
            record = archive.read("%s/RECORD" % dist_info).decode("utf-8")
            self.assertIn("%s/RECORD,," % dist_info, record)
            self.assertIn("forgel_code/cli.py,sha256=", record)

    def test_wheel_carries_subpackages_and_package_data(self) -> None:
        self.write_package_extra()

        name = self.backend.build_wheel(str(self.out))
        with zipfile.ZipFile(self.out / name) as archive:
            names = set(archive.namelist())
        self.assertIn("forgel_code/extra/__init__.py", names)
        self.assertIn("forgel_code/extra/mod.py", names)
        self.assertIn("forgel_code/data.txt", names)
        self.assertIn("forgel_code/extra/schema.json", names)

    def test_sdist_is_pep625_shaped(self) -> None:
        name = self.backend.build_sdist(str(self.out))
        self.assertEqual(name, "forgel_code-%s.tar.gz" % VERSION)
        archive_path = self.out / name
        self.assertTrue(archive_path.is_file())
        with tarfile.open(archive_path) as archive:
            names = archive.getnames()
        root = "forgel_code-%s" % VERSION
        self.assertIn("%s/PKG-INFO" % root, names)
        self.assertIn("%s/pyproject.toml" % root, names)
        self.assertIn("%s/forgel_code/cli.py" % root, names)
        self.assertIn("%s/_build_backend.py" % root, names)
        for member in names:
            self.assertTrue(member.startswith(root + "/"), member)

    def test_sdist_and_wheel_contents(self) -> None:
        """One check for both artefacts named in the acceptance criterion."""
        self.write_package_extra()

        wheel_name = self.backend.build_wheel(str(self.out))
        sdist_name = self.backend.build_sdist(str(self.out))

        self.assertEqual(sdist_name, "forgel_code-%s.tar.gz" % VERSION)
        root = "forgel_code-%s" % VERSION
        with tarfile.open(self.out / sdist_name) as archive:
            sdist_names = set(archive.getnames())
        self.assertIn("%s/PKG-INFO" % root, sdist_names)
        self.assertIn("%s/forgel_code/extra/mod.py" % root, sdist_names)
        self.assertIn("%s/forgel_code/data.txt" % root, sdist_names)

        with zipfile.ZipFile(self.out / wheel_name) as archive:
            wheel_names = set(archive.namelist())
        self.assertIn("forgel_code/extra/mod.py", wheel_names)
        self.assertIn("forgel_code/extra/schema.json", wheel_names)
        self.assertIn("forgel_code/data.txt", wheel_names)

    def test_sdist_pkg_info_names_the_version(self) -> None:
        name = self.backend.build_sdist(str(self.out))
        with tarfile.open(self.out / name) as archive:
            member = archive.extractfile("forgel_code-%s/PKG-INFO" % VERSION)
            assert member is not None
            text = member.read().decode("utf-8")
        self.assertIn("Name: forgel-code", text)
        self.assertIn("Version: %s" % VERSION, text)

    def test_metadata_names_the_project_and_the_license(self) -> None:
        metadata = self.backend._metadata()
        self.assertIn("Name: forgel-code", metadata)
        self.assertIn("License: Apache-2.0", metadata)

    def test_backend_needs_no_build_requirements(self) -> None:
        self.assertEqual(self.backend.get_requires_for_build_wheel(), [])
        self.assertEqual(self.backend.get_requires_for_build_sdist(), [])


class VersionSourceTest(TempProjectTest):
    def test_backend_reads_the_package_version(self) -> None:
        self.assertEqual(self.backend.VERSION, VERSION)
        self.assertEqual(self.backend.DIST_INFO, "forgel_code-%s.dist-info" % VERSION)

    def test_built_metadata_matches_the_package_version(self) -> None:
        self.assertIn("Version: %s" % VERSION, self.backend._metadata())

    def test_pyproject_does_not_duplicate_the_version(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', text)
        self.assertNotIn('version = "%s"' % VERSION, text)

    def test_version_option_prints_the_single_source(self) -> None:
        self.assertEqual(self.version_output(), "forgel-code %s" % VERSION)

    def test_version_option_matches_built_metadata(self) -> None:
        printed = self.version_output()
        self.assertEqual(printed, "forgel-code %s" % VERSION)
        self.assertIn("Version: %s" % printed.split()[-1], self.backend._metadata())

    def test_wheel_metadata_version_matches_the_version_option(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        with zipfile.ZipFile(self.out / name) as archive:
            metadata = archive.read("%s/METADATA" % self.backend.DIST_INFO)
        self.assertIn("Version: %s" % VERSION, metadata.decode("utf-8"))

        printed = self.version_output()
        self.assertEqual(printed.split()[-1], VERSION)


class PyprojectTest(unittest.TestCase):
    def test_pyproject_declares_the_in_tree_backend(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('build-backend = "_build_backend"', text)
        self.assertIn('backend-path = ["."]', text)
        self.assertIn('forgel-code = "forgel_code.cli:main"', text)
        self.assertIn("dependencies = []", text)


if __name__ == "__main__":
    unittest.main()
