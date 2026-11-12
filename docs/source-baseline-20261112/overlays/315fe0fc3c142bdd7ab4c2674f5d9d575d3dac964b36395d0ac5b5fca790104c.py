"""Materialize one frozen FMLA04/v1.9.2 D-1 candidate artifact.

The CLI accepts dates only.  Store and selector-panel paths come from trusted
environment values supplied by the fixed dispatcher registry.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.paths import validate_date
from shared_data.store import StoreError
from shared_data.v192_selector import materialize_frozen_v192_selector


_STORE_ROOT_ENV = "V3_SHARED_DATA_STORE_ROOT"
_SELECTOR_PANEL_ENV = "V3_SHARED_SELECTOR_READY_PANEL"


def _parse_args(argv: list[str]) -> dict[str, str]:
    if len(argv) != 4 or argv[0] != "--signal-date" or argv[2] != "--target-date":
        raise ValueError(
            "usage: materialize_v192_selector --signal-date YYYYMMDD "
            "--target-date YYYYMMDD"
        )
    return {
        "signal_date": validate_date(argv[1]),
        "target_date": validate_date(argv[3]),
    }


def main(argv: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    try:
        args = _parse_args(argv)
        store_root = str(env.get(_STORE_ROOT_ENV, "") or "").strip()
        selector_panel = str(env.get(_SELECTOR_PANEL_ENV, "") or "").strip()
        if not store_root or not selector_panel:
            raise ValueError(
                f"missing trusted environment: {_STORE_ROOT_ENV}, {_SELECTOR_PANEL_ENV}"
            )
        outcome = materialize_frozen_v192_selector(
            store_root,
            panel_path=selector_panel,
            signal_date=args["signal_date"],
            target_date=args["target_date"],
        )
        return {
            "ok": True,
            "signal_date": args["signal_date"],
            "target_date": args["target_date"],
            **outcome,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    except (ValueError, StoreError, OSError, RuntimeError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


if __name__ == "__main__":
    result = main(sys.argv[1:])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result.get("ok") else 1)
