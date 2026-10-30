"""Run module."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int | None:
    """Run the package bootstrap entrypoint."""
    from jparty.app.bootstrap import main as bootstrap_main

    return bootstrap_main()


if __name__ == "__main__":
    raise SystemExit(main())
