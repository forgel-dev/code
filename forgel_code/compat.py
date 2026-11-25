"""Confirm the engine before the client uses it.

The client declares one minimum supported engine version, asks the engine for
its own version once per invocation, and refuses to use an engine that is
missing, older than that minimum, or unable to confirm its version.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from . import MIN_ENGINE_VERSION, __version__
from .engine import Engine, EngineError

# The engine command that reports which version the engine runs.
CONFIRM_ARGUMENTS = ("version",)

# One runnable line that installs the client together with the engine it needs.
INSTALL_INSTRUCTION = (
    "curl -fsSL https://raw.githubusercontent.com/forgel-dev/code/v%s/install.sh"
    " | sh" % __version__
)


def numeric_version(version: Any) -> Optional[Tuple[int, ...]]:
    """The numeric components of a version, trailing zero components dropped.

    Components compare one at a time from the first, so a version with fewer
    components equals the same version with trailing zero components, and a
    non-numeric suffix after the numeric components affects nothing.
    """
    if version is None:
        return None
    text = str(version).strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    components = []
    for part in text.split("."):
        digits = ""
        for character in part.strip():
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        components.append(int(digits))
    if not components:
        return None
    while len(components) > 1 and components[-1] == 0:
        components.pop()
    return tuple(components)


def reported_version(payload: Any) -> Optional[str]:
    """The version the engine reports about itself, if it reports one."""
    if not isinstance(payload, dict):
        return None
    engine = payload.get("engine")
    if isinstance(engine, dict):
        value = engine.get("version")
        if value is not None and str(value).strip():
            return str(value).strip()
    value = payload.get("version")
    if value is not None and str(value).strip():
        return str(value).strip()
    return None


def supported(version: Any, minimum: str = MIN_ENGINE_VERSION) -> bool:
    """Whether ``version`` is at or above the declared minimum."""
    found = numeric_version(version)
    required = numeric_version(minimum)
    if found is None or required is None:
        return False
    return found >= required


def upgrade_instruction() -> str:
    """The line that installs a newer engine."""
    return "Upgrade the engine by running:\n  %s" % INSTALL_INSTRUCTION


def missing_message(detail: str) -> str:
    """The failure for an engine that cannot be found or cannot be started."""
    return (
        "forgel-code requires the `forgel` engine, and it could not be started: "
        "%s\nInstall the engine by running:\n  %s" % (detail, INSTALL_INSTRUCTION)
    )


def outdated_message(found: str) -> str:
    """The failure for an engine below the declared minimum."""
    return (
        "forgel-code requires engine version %s or newer, but the engine "
        "reports %s.\n%s" % (MIN_ENGINE_VERSION, found, upgrade_instruction())
    )


def unconfirmed_message() -> str:
    """The failure for an engine that answers but names no usable version."""
    return (
        "forgel-code requires engine version %s or newer, and could not confirm "
        "the engine's version from its answer.\n%s"
        % (MIN_ENGINE_VERSION, upgrade_instruction())
    )


def confirm(engine: Engine) -> str:
    """Ask the engine for its version once and refuse an unsupported engine.

    Returns the confirmed version. Raises ``EngineError`` whose message already
    names the engine and says what to install or upgrade.
    """
    try:
        payload = engine.run(CONFIRM_ARGUMENTS)
    except EngineError as exc:
        raise EngineError(missing_message(exc.message), exc.returncode or 1) from None
    found = reported_version(payload)
    if found is None:
        raise EngineError(unconfirmed_message(), 1)
    if not supported(found):
        raise EngineError(outdated_message(found), 1)
    return found
