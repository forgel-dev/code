"""The wheel and the sdist carry a PEP 561 type marker and package data.

The checkout has no subpackages and no type marker of its own, so this test
adds them to a throw-away copy and asserts they land in both artefacts. The
build itself never touches the real tree.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import forgel_code  # noqa: E402  (its version names the artefacts)

VERSION = forgel_code.__version__

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
    path = root / "_build_backend.py"
    spec = importlib.util.spec_from_file_location(
        "forgel_code_types_backend_%s" % root.parent.name, path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TypeFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "project"
        shutil.copytree(ROOT, self.root, ignore=IGNORED)
        self.out = base / "dist"
        self.out.mkdir()
        self.backend = _load_backend(self.root)

        # A PEP 561 marker plus a nested subpackage and package data, the
        # shapes a wheel must not drop.
        (self.root / "forgel_code" / "py.typed").write_text("", encoding="utf-8")
        sub = self.root / "forgel_code" / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("", encoding="utf-8")
        (sub / "schema.json").write_text("{}\n", encoding="utf-8")

    def test_wheel_contains_the_type_file_and_the_subpackage(self) -> None:
        name = self.backend.build_wheel(str(self.out))
        with zipfile.ZipFile(self.out / name) as archive:
            names = set(archive.namelist())
        self.assertIn("forgel_code/py.typed", names)
        self.assertIn("forgel_code/sub/__init__.py", names)
        self.assertIn("forgel_code/sub/schema.json", names)

    def test_sdist_contains_the_type_file_and_the_subpackage(self) -> None:
        name = self.backend.build_sdist(str(self.out))
        root = "forgel_code-%s" % VERSION
        with tarfile.open(self.out / name) as archive:
            names = set(archive.getnames())
        self.assertIn("%s/forgel_code/py.typed" % root, names)
        self.assertIn("%s/forgel_code/sub/__init__.py" % root, names)
        self.assertIn("%s/forgel_code/sub/schema.json" % root, names)


if __name__ == "__main__":
    unittest.main()
