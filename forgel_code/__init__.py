"""Thin console client for Forgel over the engine's machine-readable commands."""

from typing import Dict

__version__ = "0.2.0"

# The oldest engine version the client supports. The declaration has exactly one
# source: the installation enforces this value, and the startup check reads it
# from here too. Version ordering ignores a leading marker, so a release tag and
# a plain version compare equal.
MIN_ENGINE_VERSION = "0.1.0"


def version_report() -> Dict[str, str]:
    """The machine-readable report: the client's version and its engine floor.

    Both values are the client's own and come from the declaration above, so the
    report answers with no engine installed and without contacting the network.
    """
    return {
        "forgel_code_version": __version__,
        "minimum_engine_version": MIN_ENGINE_VERSION,
    }
