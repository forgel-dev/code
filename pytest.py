"""Stand-in for ``python -m pytest`` when pytest is not installed.

The client's tests are plain ``unittest`` cases and the package has no test
dependencies, so pytest is neither vendored nor required here: ``README.md``
documents ``python -m unittest discover -s tests``. Task specifications name
``python3 -m pytest`` as a test command as well, so this module lets that
command run the same suite through ``unittest`` when no real pytest is
available; when pytest *is* installed, it is used instead. Only the
``forgel_code`` package is installed from this tree, so this file never
reaches an installation.
"""

from __future__ import annotations

import os
import runpy
import sys
import unittest


def _real_pytest_installed() -> bool:
    """True when a pytest distribution exists outside this directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    saved = list(sys.path)
    sys.path[:] = [
        entry for entry in sys.path if os.path.abspath(entry or os.getcwd()) != here
    ]
    try:
        import pytest  # noqa: F401  (probe only)
    except ImportError:
        return False
    finally:
        sys.path[:] = saved
    return True


def _unittest_argv(argv) -> list:
    """Translate the pytest arguments the project's commands actually use."""
    quiet = "-q" in argv or "--quiet" in argv
    selectors = [argument for argument in argv if not argument.startswith("-")]
    words = ["discover", "-s", "tests"]
    if len(selectors) == 1:
        selector = selectors[0]
        if selector.endswith(".py"):
            words = [
                "discover",
                "-s",
                os.path.dirname(selector) or ".",
                "-p",
                os.path.basename(selector),
            ]
        else:
            words = ["discover", "-s", selector]
    if quiet:
        words.append("-q")
    return words


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if _real_pytest_installed():
        sys.argv = ["pytest"] + arguments
        runpy.run_module("pytest", run_name="__main__", alter_sys=True)
        return 0
    unittest.main(
        module=None, argv=["pytest"] + _unittest_argv(arguments), exit=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
