"""In-tree PEP 517 build backend that needs nothing but the standard library.

Setuptools is not always available where a pinned revision is installed
(offline machines and isolated build environments without a package index). The
client has no runtime dependencies, so a small backend is enough to build its
wheel and its sdist without downloading anything.

The version has one source, ``forgel_code/__init__.py:__version__``; this
backend reads it from there instead of keeping a second literal. The optional
dependencies have one source too: ``pyproject.toml``. This backend reads that
table back out of the same file and republishes it as ``Provides-Extra`` and
``Requires-Dist`` so the declaration and the built metadata cannot drift.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
NAME = "forgel-code"
MODULE = "forgel_code"
SUMMARY = (
    "Thin console client for Forgel over the engine's machine-readable commands"
)

# The one table of ``pyproject.toml`` this backend republishes.
EXTRAS_TABLE = "project.optional-dependencies"


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


def _strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment that does not sit inside a string."""
    kept: List[str] = []
    quote = ""
    escaped = False
    for char in line:
        if quote:
            kept.append(char)
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            kept.append(char)
            continue
        if char == "#":
            break
        kept.append(char)
    return "".join(kept)


def _header_parts(line: str) -> Optional[List[str]]:
    """The dotted key of a ``[table]`` header line, or ``None`` for other lines."""
    stripped = line.strip()
    if not stripped.startswith("[") or stripped.startswith("[["):
        return None
    if not stripped.endswith("]"):
        return None
    parts: List[str] = []
    for raw in stripped[1:-1].split("."):
        part = raw.strip()
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        if not part:
            raise RuntimeError("cannot parse a table header: %r" % line)
        parts.append(part)
    return parts


def _bracket_delta(line: str) -> int:
    """How many array brackets a line opens, ignoring brackets in strings."""
    delta = 0
    quote = ""
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "[":
            delta += 1
        elif char == "]":
            delta -= 1
    return delta


def _table_body(text: str, table: str) -> str:
    """The lines of one ``[table]``, without comments, or ``""`` when absent."""
    wanted = table.split(".")
    collected: List[str] = []
    inside = False
    depth = 0
    for line in text.splitlines():
        without_comment = _strip_comment(line)
        if depth <= 0:
            parts = _header_parts(without_comment)
            if parts is not None:
                inside = parts == wanted
                depth = 0
                continue
        if not inside:
            continue
        collected.append(without_comment)
        depth += _bracket_delta(without_comment)
    return "\n".join(collected)


def _parse_string(text: str, index: int) -> Tuple[str, int]:
    """Read one single- or double-quoted string, returning it and the new index."""
    quote = text[index]
    if quote not in "\"'":
        raise RuntimeError(
            "expected a quoted string at %r" % text[index : index + 20]
        )
    index += 1
    chars: List[str] = []
    while index < len(text):
        char = text[index]
        if char == "\\" and quote == '"' and index + 1 < len(text):
            escaped = text[index + 1]
            chars.append({"n": "\n", "t": "\t", "r": "\r"}.get(escaped, escaped))
            index += 2
            continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise RuntimeError("unterminated string in the extras table")


def _parse_key(text: str, index: int) -> Tuple[str, int]:
    """Read a bare or quoted key, returning it and the new index."""
    if text[index] in "\"'":
        return _parse_string(text, index)
    start = index
    while index < len(text) and (text[index].isalnum() or text[index] in "_-"):
        index += 1
    if start == index:
        raise RuntimeError("cannot parse a key at %r" % text[index : index + 20])
    return text[start:index], index


def _parse_string_array(text: str, index: int) -> Tuple[List[str], int]:
    """Read an array of strings, returning it and the index after the closing ``]``."""
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    if index >= len(text) or text[index] != "[":
        raise RuntimeError(
            "expected an array of strings at %r" % text[index : index + 20]
        )
    index += 1
    values: List[str] = []
    while True:
        while index < len(text) and text[index] in " \t\r\n,":
            index += 1
        if index >= len(text):
            raise RuntimeError("unterminated array in the extras table")
        if text[index] == "]":
            return values, index + 1
        value, index = _parse_string(text, index)
        values.append(value)


def _parse_extras(text: str) -> Dict[str, List[str]]:
    """Parse the extras table without ``tomllib`` (Python 3.9 and 3.10).

    Only the shape ``pyproject.toml`` uses is understood: a
    ``[project.optional-dependencies]`` table of string arrays, with multi-line
    arrays, inline comments and either quote style.
    """
    body = _table_body(text, EXTRAS_TABLE)
    extras: Dict[str, List[str]] = {}
    index = 0
    while True:
        while index < len(body) and body[index] in " \t\r\n,":
            index += 1
        if index >= len(body):
            return extras
        key, index = _parse_key(body, index)
        while index < len(body) and body[index] in " \t\r\n":
            index += 1
        if index >= len(body) or body[index] != "=":
            raise RuntimeError(
                "expected '=' after the %r extra at %r"
                % (key, body[index : index + 20])
            )
        values, index = _parse_string_array(body, index + 1)
        extras[key] = values


def _read_extras(path: Path) -> Dict[str, List[str]]:
    """Read the extras table of ``pyproject.toml``, via ``tomllib`` when present."""
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:  # Python 3.9 and 3.10 ship no tomllib.
        return _parse_extras(text)
    project = tomllib.loads(text).get("project", {})
    table = project.get("optional-dependencies", {})
    return {
        str(name): [str(requirement) for requirement in requirements]
        for name, requirements in table.items()
    }


VERSION = _read_version()
EXTRAS = _read_extras(ROOT / "pyproject.toml")
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


def _extra_lines() -> List[str]:
    """``Provides-Extra`` and ``Requires-Dist`` lines for every declared extra."""
    lines: List[str] = []
    for extra, requirements in EXTRAS.items():
        lines.append("Provides-Extra: %s" % extra)
        for requirement in requirements:
            lines.append('Requires-Dist: %s; extra == "%s"' % (requirement, extra))
    return lines


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
    lines.extend(_extra_lines())
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
