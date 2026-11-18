"""Packaging tests: the wheel really carries the ``forgel-code`` command."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _build_backend  # noqa: E402  (in-tree PEP 517 backend)


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

    def test_metadata_names_the_project_and_the_license(self) -> None:
        metadata = _build_backend._metadata()
        self.assertIn("Name: forgel-code", metadata)
        self.assertIn("License: Apache-2.0", metadata)

    def test_backend_needs_no_build_requirements(self) -> None:
        self.assertEqual(_build_backend.get_requires_for_build_wheel(), [])
        self.assertEqual(_build_backend.get_requires_for_build_sdist(), [])


class PyprojectTest(unittest.TestCase):
    def test_pyproject_declares_the_in_tree_backend(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('build-backend = "_build_backend"', text)
        self.assertIn('backend-path = ["."]', text)
        self.assertIn('forgel-code = "forgel_code.cli:main"', text)
        self.assertIn('dependencies = []', text)


if __name__ == "__main__":
    unittest.main()
