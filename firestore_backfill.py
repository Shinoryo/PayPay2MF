"""Source checkout compatibility wrapper for the Firestore backfill CLI."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def _run() -> None:
    main = importlib.import_module("paypay2mf.firestore_backfill").main
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
