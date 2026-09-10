"""Capture the exact-date public close-review bundle into the shared store."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.public_fupan import capture_public_fupan


def main(argv: list[str], *, env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    if len(argv) != 2 or argv[0] != "--trade-date":
        return {"ok": False, "status": "FAILED", "error": "usage: capture_public_fupan --trade-date YYYYMMDD"}
    root = str(env.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    if not root:
        return {"ok": False, "status": "FAILED", "error": "V3_SHARED_DATA_STORE_ROOT missing"}
    try:
        return capture_public_fupan(Path(root), argv[1])
    except (OSError, ValueError) as error:
        return {"ok": False, "status": "FAILED", "error": str(error)}


if __name__ == "__main__":
    outcome = main(sys.argv[1:])
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if outcome.get("ok") else 1)
