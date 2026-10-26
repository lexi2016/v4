"""Resume-safe fixed wrapper for the shared v1.9.2 preselection artifact."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from infrastructure.isolated_package_loader import load_isolated_package_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--target-date", required=True)
    args = parser.parse_args(argv)
    package_root = Path(os.environ["V35_SHARED_PACKAGE_ROOT"])
    store_root = Path(os.environ["V3_SHARED_DATA_STORE_ROOT"])
    panel_value = os.environ.get("V3_SHARED_SELECTOR_READY_PANEL")
    panel = Path(panel_value) if panel_value else None
    selector_module = load_isolated_package_module(
        package_root,
        package_directory="shared_data",
        module_leaf="v192_selector",
        namespace_prefix="v35_shared_v192_selector",
    )
    StoreError = getattr(selector_module, "StoreError")
    materialize_frozen_v192_selector = getattr(
        selector_module, "materialize_frozen_v192_selector"
    )
    read_verified_v192_pool = getattr(selector_module, "read_verified_v192_pool")

    try:
        existing = read_verified_v192_pool(
            store_root,
            target_date=args.target_date,
            expected_signal_date=args.signal_date,
        )
        outcome = {
            "ok": True,
            "already_exists": True,
            "status": existing.run.receipt["status"],
            **existing.run.verification,
        }
    except StoreError:
        if panel is None or not panel.is_file():
            print(json.dumps({
                "ok": False,
                "status": "CANNOT_CONFIRM",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "A_V192_EXACT_INPUT_MISSING:selector panel unavailable",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }, sort_keys=True))
            return 1
        try:
            outcome = materialize_frozen_v192_selector(
                store_root,
                panel_path=panel,
                signal_date=args.signal_date,
                target_date=args.target_date,
            )
            outcome = {"ok": True, **outcome}
        except (OSError, RuntimeError, StoreError, ValueError) as error:
            outcome = {"ok": False, "status": "FAILED", "error": str(error)}
    outcome.update(
        {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome.get("ok") and outcome.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
