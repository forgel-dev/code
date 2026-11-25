"""Thin console client for Forgel over the engine's machine-readable commands."""

__version__ = "0.2.0"

# The oldest engine version the client supports. The declaration has exactly one
# source: the installation enforces this value, and the startup check reads it
# from here too. Version ordering ignores a leading marker, so a release tag and
# a plain version compare equal.
MIN_ENGINE_VERSION = "0.1.0"
