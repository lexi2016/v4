from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import (
    materialize_frozen_hk_0_2,
    read_verified_hk_0_2_pool,
    restore_verified_hk_0_2_source,
)
from shared_data.store import StoreError


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the frozen HK Connect 0.2 D-1 Top100")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, default=None)
    parser.add_argument(
        "--restore-source-root",
        type=Path,
        default=None,
        help="One-time exact verified shared root to migrate; never an online fallback",
    )
    parser.add_argument("--signal-date", required=True)
    parser.add_argument(
        "--eligibility-source-date",
        default=None,
        help="Verified Connect eligibility/security-master as-of date; defaults to --signal-date",
    )
    parser.add_argument("--target-date", required=True)
    args = parser.parse_args()
    if args.restore_source_root is not None:
        try:
            outcome = restore_verified_hk_0_2_source(
                args.restore_source_root,
                args.store_root,
                signal_date=args.signal_date,
                target_date=args.target_date,
            )
        except StoreError as error:
            outcome = {
                "ok": False,
                "status": "FAILED",
                "error": str(error),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        print(json.dumps(outcome, ensure_ascii=False))
        return 0 if outcome.get("status") == "READY" else 1
    try:
        existing = read_verified_hk_0_2_pool(
            args.store_root,
            target_date=args.target_date,
            expected_signal_date=args.signal_date,
            expected_eligibility_source_date=args.eligibility_source_date,
        )
        outcome = {
            "ok": True,
            "already_exists": True,
            "status": existing.run.receipt["status"],
            **existing.run.verification,
        }
    except StoreError:
        if args.asset_root is not None:
            outcome = materialize_frozen_hk_0_2(
                args.store_root,
                args.asset_root,
                signal_date=args.signal_date,
                eligibility_source_date=args.eligibility_source_date,
                target_date=args.target_date,
            )
        else:
            outcome = {
                "ok": False,
                "status": "FAILED",
                "error": "--asset-root or --restore-source-root is required when exact target is absent",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
