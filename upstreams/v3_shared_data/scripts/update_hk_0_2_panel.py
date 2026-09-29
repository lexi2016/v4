from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import update_hk_0_2_panel_from_vipdoc
from shared_data.store import StoreError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atomically append a verified TDX VIPDOC day to the shared HK 0.2 panel"
    )
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--tdx-root", type=Path, required=True)
    parser.add_argument("--through-date", required=True)
    args = parser.parse_args()
    try:
        outcome = update_hk_0_2_panel_from_vipdoc(
            args.asset_root,
            tdx_root=args.tdx_root,
            through_date=args.through_date,
        )
    except StoreError as error:
        outcome = {
            "status": "FAILED",
            "error": str(error),
            "through_date": args.through_date,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
