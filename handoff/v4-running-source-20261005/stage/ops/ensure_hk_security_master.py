"""Materialize exact-date HK names with distinct universe and asset roots.

The shared producer historically assumed that immutable universe manifests and
mutable assets lived below one root.  The Mac runtime deliberately separates
those roots, so this bounded bridge verifies the exact universe from its
read-only root and publishes only the security-master asset to the shared
runtime store.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def ensure_hk_security_master(
    *,
    store_root: Path,
    universe_root: Path,
    shared_package_root: Path,
    trade_date: str,
    futu_python: Path,
) -> dict[str, object]:
    package_root = shared_package_root.expanduser().resolve()
    if not package_root.is_dir():
        raise ValueError(f"shared package root missing: {package_root}")
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

    from scripts.acquire_hk_security_master import collect_futu_hk_security_master
    from scripts.live_acquisition.universe import resolve_stage_universe
    from shared_data.hk_security_master import (
        load_verified_hk_security_master,
        publish_hk_security_master,
    )
    from shared_data.store import StoreError

    universe = resolve_stage_universe(universe_root, trade_date, "HK_CONNECT")
    try:
        rows, manifest = load_verified_hk_security_master(store_root, trade_date)
    except StoreError:
        rows, manifest = {}, {}
    if (
        manifest.get("universe_codes_sha256") == universe.codes_sha256
        and manifest.get("valuation_eligibility_field") == "circular_market_val"
        and set(rows) == set(universe.codes)
    ):
        return {
            "ok": True,
            "status": "READY",
            "reused": True,
            "trade_date": trade_date,
            "row_count": len(rows),
            "run_id": manifest.get("run_id"),
            "universe_codes_sha256": universe.codes_sha256,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    collected = collect_futu_hk_security_master(futu_python, list(universe.codes))
    published = publish_hk_security_master(
        store_root,
        trade_date=trade_date,
        rows=collected,
        universe_codes_sha256=universe.codes_sha256,
        captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    return {
        "ok": True,
        "status": "READY",
        "reused": False,
        "trade_date": trade_date,
        "row_count": published["row_count"],
        "run_id": published["run_id"],
        "universe_codes_sha256": universe.codes_sha256,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", required=True, type=Path)
    parser.add_argument("--universe-root", required=True, type=Path)
    parser.add_argument("--shared-package-root", required=True, type=Path)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--futu-python", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = ensure_hk_security_master(
            store_root=args.store_root,
            universe_root=args.universe_root,
            shared_package_root=args.shared_package_root,
            trade_date=args.trade_date,
            futu_python=args.futu_python,
        )
    except Exception as error:  # scheduler boundary: emit one fail-closed JSON result
        result = {
            "ok": False,
            "status": "FAILED",
            "error": f"{type(error).__name__}: {error}",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
