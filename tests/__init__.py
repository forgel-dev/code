"""Tests for the Forgel Code client."""

from __future__ import annotations

import sys
from pathlib import Path

# The suites describe the checkout, so the checkout must win: an installed copy
# of ``forgel-code`` that is importable first must never answer for it.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_from_checkout(module: object) -> bool:
    location = getattr(module, "__file__", None)
    if not location:
        return False
    try:
        Path(location).resolve().relative_to(ROOT)
    except ValueError:
        return False
    return True


for _name in [name for name in sys.modules if name.split(".")[0] == "forgel_code"]:
    if not _is_from_checkout(sys.modules[_name]):
        del sys.modules[_name]
