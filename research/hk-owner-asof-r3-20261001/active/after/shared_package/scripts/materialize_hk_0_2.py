from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import materialize_frozen_hk_0_2, read_verified_hk_0_2_pool
from shared_data.store import StoreError


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the frozen HK Connect 0.2 D-1 Top100")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--eligibility-source-date", default=None)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--eligibility-universe-root", type=Path, default=None)
    args = parser.parse_args()
    try:
        existing = read_verified_hk_0_2_pool(
            args.store_root,
            target_date=args.target_date,
            expected_signal_date=args.signal_date,
            expected_eligibility_source_date=args.eligibility_source_date,
            eligibility_universe_root=args.eligibility_universe_root,
        )
        outcome = {
            "ok": True,
            "already_exists": True,
            "status": existing.run.receipt["status"],
            **existing.run.verification,
        }
    except StoreError:
        outcome = materialize_frozen_hk_0_2(
            args.store_root,
            args.asset_root,
            signal_date=args.signal_date,
            eligibility_source_date=args.eligibility_source_date,
            eligibility_universe_root=args.eligibility_universe_root,
            target_date=args.target_date,
        )
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
