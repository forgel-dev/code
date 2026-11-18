"""Packaging tests: the wheel and the sdist really carry the ``forgel-code`` package."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _build_backend  # noqa: E402  (in-tree PEP 517 backend)
import forgel_code  # noqa: E402

VERSION = forgel_code.__version__


def _write_package_extra(subpackage: Path):
    """Add a subpackage and package data, returning a cleanup callable."""
    subpackage.mkdir()
    created = [
        subpackage / "__init__.py",
        subpackage / "mod.py",
        subpackage / "schema.json",
        ROOT / "forgel_code" / "data.txt",
    ]
    created[0].write_text("", encoding="utf-8")
    created[1].write_text("VALUE = 1\n", encoding="utf-8")
    created[2].write_text("{}\n", encoding="utf-8")
    created[3].write_text("package data\n", encoding="utf-8")

    def cleanup() -> None:
        for path in created:
            if path.exists():
                path.unlink()
        if subpackage.exists():
            subpackage.rmdir()

    return cleanup


class BuildBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_wheel_contains_the_client_and_the_console_script(self) -> None:
        name = _build_backend.build_wheel(str(self.out))
        self.assertEqual(name, _build_backend.WHEEL_NAME)
        wheel = self.out / name
        self.assertTrue(wheel.is_file())

        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            for module in sorted((ROOT / "forgel_code").glob("*.py")):
                self.assertIn("forgel_code/%s" % module.name, names)
            dist_info = _build_backend.DIST_INFO
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
        cleanup = _write_package_extra(ROOT / "forgel_code" / "extra")
        self.addCleanup(cleanup)

        name = _build_backend.build_wheel(str(self.out))
        with zipfile.ZipFile(self.out / name) as archive:
            names = set(archive.namelist())
        self.assertIn("forgel_code/extra/__init__.py", names)
        self.assertIn("forgel_code/extra/mod.py", names)
        self.assertIn("forgel_code/data.txt", names)
        self.assertIn("forgel_code/extra/schema.json", names)

    def test_sdist_is_pep625_shaped(self) -> None:
        name = _build_backend.build_sdist(str(self.out))
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

    def test_sdist_pkg_info_names_the_version(self) -> None:
        name = _build_backend.build_sdist(str(self.out))
        with tarfile.open(self.out / name) as archive:
            member = archive.extractfile("forgel_code-%s/PKG-INFO" % VERSION)
            assert member is not None
            text = member.read().decode("utf-8")
        self.assertIn("Name: forgel-code", text)
        self.assertIn("Version: %s" % VERSION, text)

    def test_metadata_names_the_project_and_the_license(self) -> None:
        metadata = _build_backend._metadata()
        self.assertIn("Name: forgel-code", metadata)
        self.assertIn("License: Apache-2.0", metadata)

    def test_backend_needs_no_build_requirements(self) -> None:
        self.assertEqual(_build_backend.get_requires_for_build_wheel(), [])
        self.assertEqual(_build_backend.get_requires_for_build_sdist(), [])


class VersionSourceTest(unittest.TestCase):
    def test_backend_reads_the_package_version(self) -> None:
        self.assertEqual(_build_backend.VERSION, VERSION)
        self.assertEqual(
            _build_backend.DIST_INFO, "forgel_code-%s.dist-info" % VERSION
        )

    def test_built_metadata_matches_the_package_version(self) -> None:
        self.assertIn("Version: %s" % VERSION, _build_backend._metadata())

    def test_pyproject_does_not_duplicate_the_version(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', text)
        self.assertNotIn('version = "%s"' % VERSION, text)

    def test_version_option_prints_the_single_source(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "forgel_code", "--version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "forgel-code %s" % VERSION)

    def test_version_option_matches_built_metadata(self) -> None:
        from forgel_code.cli import main

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--version"])
        self.assertEqual(code, 0)
        printed = stdout.getvalue().strip()
        self.assertEqual(printed, "forgel-code %s" % VERSION)
        self.assertIn("Version: %s" % printed.split()[-1], _build_backend._metadata())


class PyprojectTest(unittest.TestCase):
    def test_pyproject_declares_the_in_tree_backend(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('build-backend = "_build_backend"', text)
        self.assertIn('backend-path = ["."]', text)
        self.assertIn('forgel-code = "forgel_code.cli:main"', text)
        self.assertIn('dependencies = []', text)


if __name__ == "__main__":
    unittest.main()
