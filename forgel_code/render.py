"""Turn an engine JSON answer into human readable text lines."""

from __future__ import annotations

from typing import Any, List


def format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_human(value: Any, indent: int = 0) -> List[str]:
    """Render any engine answer as a flat list of text lines."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "(empty)"]
        lines: List[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append("%s%s:" % (pad, key))
                lines.extend(render_human(item, indent + 1))
            else:
                lines.append("%s%s: %s" % (pad, key, format_scalar(item)))
        return lines
    if isinstance(value, list):
        if not value:
            return [pad + "(empty)"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(pad + "-")
                lines.extend(render_human(item, indent + 1))
            else:
                lines.append("%s- %s" % (pad, format_scalar(item)))
        return lines
    return [pad + format_scalar(value)]
