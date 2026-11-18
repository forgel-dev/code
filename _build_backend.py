"""In-tree PEP 517 build backend that needs nothing but the standard library.

Setuptools is not always available where ``pip install .`` runs (offline
machines and isolated build environments without a package index). The client
has no runtime dependencies, so a small backend is enough to build its wheel
without downloading anything.
"""

from __future__ import annotations

import base64
import hashlib
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
NAME = "forgel-code"
MODULE = "forgel_code"
VERSION = "0.1.0"
SUMMARY = (
    "Thin console client for Forgel over the engine's machine-readable commands"
)
DIST_INFO = "%s-%s.dist-info" % (MODULE, VERSION)
WHEEL_NAME = "%s-%s-py3-none-any.whl" % (MODULE, VERSION)
SDIST_NAME = "%s-%s.tar.gz" % (NAME, VERSION)


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


def _payload() -> Dict[str, bytes]:
    """Every file that goes into the wheel, keyed by its archive name."""
    files: Dict[str, bytes] = {}
    package = ROOT / MODULE
    for path in sorted(package.glob("*.py")):
        files["%s/%s" % (MODULE, path.name)] = path.read_bytes()
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


def build_sdist(
    sdist_directory: str, config_settings: Optional[dict] = None
) -> str:
    target = Path(sdist_directory) / SDIST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = "%s-%s" % (NAME, VERSION)
    with tarfile.open(target, "w:gz") as archive:
        for path in [ROOT / "pyproject.toml", ROOT / "README.md", ROOT / "LICENSE"]:
            if path.is_file():
                archive.add(path, arcname="%s/%s" % (prefix, path.name))
        for path in sorted((ROOT / MODULE).glob("*.py")):
            archive.add(path, arcname="%s/%s/%s" % (prefix, MODULE, path.name))
        archive.add(ROOT / "_build_backend.py", arcname="%s/_build_backend.py" % prefix)
    return SDIST_NAME
