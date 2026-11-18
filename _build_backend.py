"""In-tree PEP 517 build backend that needs nothing but the standard library.

Setuptools is not always available where a pinned revision is installed
(offline machines and isolated build environments without a package index). The
client has no runtime dependencies, so a small backend is enough to build its
wheel and its sdist without downloading anything.

The version has one source, ``forgel_code/__init__.py:__version__``; this
backend reads it from there instead of keeping a second literal.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
NAME = "forgel-code"
MODULE = "forgel_code"
SUMMARY = (
    "Thin console client for Forgel over the engine's machine-readable commands"
)


def _read_version() -> str:
    """Read ``__version__`` from the package without importing it."""
    source = ROOT / MODULE / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]
        if "__version__" not in targets:
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise RuntimeError("%s declares no __version__ string" % source)


VERSION = _read_version()
DIST_INFO = "%s-%s.dist-info" % (MODULE, VERSION)
WHEEL_NAME = "%s-%s-py3-none-any.whl" % (MODULE, VERSION)
# PEP 625: the sdist filename and its archive root use the normalized name.
NORMALIZED_NAME = NAME.replace("-", "_").replace(".", "_")
SDIST_ROOT = "%s-%s" % (NORMALIZED_NAME, VERSION)
SDIST_NAME = "%s.tar.gz" % SDIST_ROOT


def _long_description() -> str:
    readme = ROOT / "README.md"
    if not readme.is_file():
        return ""
    return readme.read_text(encoding="utf-8")


def _metadata() -> str:
    lines = [
        "Metadata-Version: 2.1",
        "Name: %s" % NAME,
        "Version: %s" % VERSION,
        "Summary: %s" % SUMMARY,
        "License: Apache-2.0",
        "Requires-Python: >=3.9",
        "Classifier: License :: OSI Approved :: Apache Software License",
        "Classifier: Programming Language :: Python :: 3",
        "Description-Content-Type: text/markdown",
    ]
    return "\n".join(lines) + "\n\n" + _long_description() + "\n"


def _wheel_metadata() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: forgel-code-build-backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
        ]
    ) + "\n"


def _entry_points() -> str:
    return "[console_scripts]\nforgel-code = forgel_code.cli:main\n"


def _package_files() -> List[Path]:
    """Every file of the package: modules, subpackages and package data."""
    package = ROOT / MODULE
    files: List[Path] = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files.append(path)
    return files


def _payload() -> Dict[str, bytes]:
    """Every file that goes into the wheel, keyed by its archive name."""
    files: Dict[str, bytes] = {}
    for path in _package_files():
        relative = path.relative_to(ROOT / MODULE).as_posix()
        files["%s/%s" % (MODULE, relative)] = path.read_bytes()
    files["%s/METADATA" % DIST_INFO] = _metadata().encode("utf-8")
    files["%s/WHEEL" % DIST_INFO] = _wheel_metadata().encode("utf-8")
    files["%s/entry_points.txt" % DIST_INFO] = _entry_points().encode("utf-8")
    license_file = ROOT / "LICENSE"
    if license_file.is_file():
        files["%s/LICENSE" % DIST_INFO] = license_file.read_bytes()
    return files


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _record(files: Dict[str, bytes]) -> bytes:
    lines: List[str] = []
    for name, data in files.items():
        lines.append("%s,%s,%d" % (name, _hash(data), len(data)))
    lines.append("%s/RECORD,," % DIST_INFO)
    return ("\n".join(lines) + "\n").encode("utf-8")


def get_requires_for_build_wheel(config_settings: Optional[dict] = None) -> List[str]:
    return []


def get_requires_for_build_sdist(config_settings: Optional[dict] = None) -> List[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: Optional[dict] = None
) -> str:
    target = Path(metadata_directory) / DIST_INFO
    target.mkdir(parents=True, exist_ok=True)
    (target / "METADATA").write_text(_metadata(), encoding="utf-8")
    (target / "WHEEL").write_text(_wheel_metadata(), encoding="utf-8")
    (target / "entry_points.txt").write_text(_entry_points(), encoding="utf-8")
    return DIST_INFO


def build_wheel(
    wheel_directory: str,
    config_settings: Optional[dict] = None,
    metadata_directory: Optional[str] = None,
) -> str:
    files = _payload()
    files["%s/RECORD" % DIST_INFO] = _record(files)
    target = Path(wheel_directory) / WHEEL_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return WHEEL_NAME


def _add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def build_sdist(
    sdist_directory: str, config_settings: Optional[dict] = None
) -> str:
    target = Path(sdist_directory) / SDIST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as archive:
        _add(archive, "%s/PKG-INFO" % SDIST_ROOT, _metadata().encode("utf-8"))
        for name in ("pyproject.toml", "README.md", "LICENSE", "_build_backend.py"):
            path = ROOT / name
            if path.is_file():
                _add(archive, "%s/%s" % (SDIST_ROOT, name), path.read_bytes())
        for path in _package_files():
            relative = path.relative_to(ROOT / MODULE).as_posix()
            _add(
                archive,
                "%s/%s/%s" % (SDIST_ROOT, MODULE, relative),
                path.read_bytes(),
            )
    return SDIST_NAME
