"""Import V3 materialized stage workbench snapshots as V4 reference workbench.

The V3 runtime scheduler materializes per-stage workbench snapshots with the
full second-filter row model (support/pressure/invalidation lines, stage score,
decision level). V4 reads those snapshots as read-only reference workbench so
the stage workbench renders the same rows V3 shows. Nothing writes to V3.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from infrastructure.stage_store import StageStore


# v3 snapshot files per stage (limit10/limit20 variants; prefer limit20)
STAGE_SNAPSHOTS = {
    "STAGE_0925": "STAGE_0925_limit20.json",
    "STAGE_0930_0935": "STAGE_0930_0935_limit20.json",
    "STAGE_0935_0940": "STAGE_0935_0940_limit20.json",
    "STAGE_0940_0945": "STAGE_0940_0945_limit20.json",
    "STAGE_0945_1030": "STAGE_0945_1030_limit20.json",
    "STAGE_1300_1315": "STAGE_1300_1315_limit20.json",
    "STAGE_1445_1500": "STAGE_1445_1500_limit20.json",
    "STAGE_1545_1555": "STAGE_1545_1555_limit20.json",
}


def adapt_snapshot(payload: dict) -> dict:
    """Map a V3 stage workbench row into the V4 read-only field subset.

    V3 rows carry BUY-gate action fields that the V4 safety boundary rejects.
    Keep only the fields the V4 workbench renders (support/pressure/invalidation
    lines, stage score, decision), so the stage rows are pure observation data.
    """
    allowed = {
        "code", "name", "rank", "market", "stage_id",
        "stage_score", "pool_score", "score", "stage_rtdata_score",
        "change_pct", "current_change_pct", "d1_change_pct",
        "support_primary_price", "support_primary_basis",
        "pressure_price", "pressure_basis",
        "invalidation_price", "invalidation_condition",
        "stage_display_decision", "decision_level", "next_validation_time",
        "source_label", "evidence_level", "stop_loss",
        "low_price", "high_price", "current_price",
        "window_change_pct", "amount_in_window", "turnover",
    }
    rows = payload.get("unified_rows") or []
    adapted_rows = []
    for row in rows:
        adapted = {key: row.get(key) for key in allowed if key in row}
        adapted["market"] = adapted.get("market") or "A"
        adapted["stage_id"] = adapted.get("stage_id") or ""
        adapted["rank"] = adapted.get("rank") or 0
        adapted["code"] = adapted.get("code") or ""
        adapted["name"] = adapted.get("name") or adapted.get("code")
        adapted["recommendation_status"] = "WATCH_ONLY"
        adapted["production_allowed"] = False
        adapted["buy_gate_updated"] = False
        adapted["orders_sent"] = False
        adapted_rows.append(adapted)
    adapted = dict(payload)
    # Drop V3 scheduling metadata whose "action" keys trip the V4 safety
    # boundary. The rows are observation data; the schedule is not rendered.
    for key in ("opening_second_filter", "sidebar", "empty_state", "materialized_snapshot", "response_source", "snapshot_path", "module_card", "startup_ensure", "markets"):
        adapted.pop(key, None)
    adapted["unified_rows"] = adapted_rows
    adapted["recommendation_status"] = "WATCH_ONLY_BACKTEST_GATED"
    adapted["production_allowed"] = False
    adapted["buy_gate_updated"] = False
    adapted["orders_sent"] = False
    return adapted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--v3-snapshot-root", required=True, type=Path)
    parser.add_argument("--data-root", type=Path, default=Path.cwd() / ".runtime" / "data")
    args = parser.parse_args()

    store = StageStore(args.data_root)
    imported = []
    for stage_id, filename in STAGE_SNAPSHOTS.items():
        snapshot_path = args.v3_snapshot_root / filename
        if not snapshot_path.is_file():
            imported.append({"stage_id": stage_id, "status": "SOURCE_MISSING"})
            continue
        payload = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        adapted = adapt_snapshot(payload)
        try:
            store.import_reference_workbench(adapted)
            imported.append({
                "stage_id": stage_id,
                "status": "IMPORTED",
                "total_rows": len(adapted.get("unified_rows") or []),
            })
        except ValueError as error:
            imported.append({"stage_id": stage_id, "status": f"REJECTED: {error}"})
    print(json.dumps({"trade_date": args.trade_date, "imported": imported}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
