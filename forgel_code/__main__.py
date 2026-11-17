"""Allow ``python -m forgel_code``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
