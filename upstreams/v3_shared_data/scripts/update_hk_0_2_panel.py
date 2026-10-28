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
    parser.add_argument(
        "--through-date", required=True,
        help="exact owner market_session date in YYYYMMDD, never the plan trade date",
    )
    parser.add_argument(
        "--daily-supplement",
        action="store_true",
        help="capture a research-only category-4 sidecar; do not update the HK0.2 panel",
    )
    parser.add_argument(
        "--canary-codes", nargs="+",
        help="optional comma-separated or individual HK codes; at most three, staged without a consumer pointer",
    )
    args = parser.parse_args()
    if args.canary_codes is not None and not args.daily_supplement:
        outcome = {
            "status": "FAILED",
            "error": "CANARY_CODES_REQUIRE_DAILY_SUPPLEMENT",
            "through_date": args.through_date,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(outcome, ensure_ascii=False))
        return 1
    if args.daily_supplement:
        try:
            from shared_data.hk_daily_supplement import (
                capture_daily_supplement,
                normalize_canary_codes,
            )

            asset_root = args.asset_root.expanduser().resolve()
            if asset_root.name != "hk_0_2" or asset_root.parent.name != "assets":
                raise ValueError("HK_DAILY_SUPPLEMENT_ASSET_ROOT_INVALID")
            authority_root = asset_root.parent.parent
            canary_codes = normalize_canary_codes(args.canary_codes)
            outcome = capture_daily_supplement(
                authority_root,
                target_date=args.through_date,
                canary_codes=canary_codes,
            )
        except (StoreError, OSError, ValueError, RuntimeError, ConnectionError) as error:
            message = str(error)
            outcome = {
                "status": "FAILED",
                "error": message if message.startswith("HK_DAILY_SUPPLEMENT_") else type(error).__name__,
                "through_date": args.through_date,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        print(json.dumps(outcome, ensure_ascii=False))
        return 0 if outcome.get("status") in {
            "READY", "PARTIAL_WITH_PENDING", "CANARY_STAGED",
        } else 1
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
