"""Offline importer for sanitized stage-workbench reference exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from contracts.stages import FROZEN_STAGE_IDS
from infrastructure.stage_store import StageStore


_SAFE_NUMERIC_FIELDS = (
    "d1_change_pct",
    "current_change_pct",
    "turnover",
    "support_primary_price",
    "pressure_price",
    "invalidation_price",
    "risk_reward_ratio",
)


def _number(value: Any) -> int | float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _safe_decision(row: Mapping[str, Any]) -> str:
    decision = str(
        row.get("stage_display_decision")
        or row.get("display_decision")
        or "人工观察"
    ).strip()
    if not decision or "买入" in decision or "BUY" in decision.upper() or "推荐" in decision:
        return "人工观察"
    return decision


def _normalize_row(source: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValueError("reference rows must be objects")
    market = str(source.get("market") or "").upper()
    if market not in {"A", "HK"}:
        raise ValueError("reference row market must be A or HK")
    code = str(source.get("code") or source.get("symbol") or source.get("stock_code") or "").strip()
    if not code:
        raise ValueError("reference row code is required")
    rank = _number(source.get("rank") or source.get("stage_rank"))
    if rank is None or rank < 1:
        raise ValueError("reference row rank is required")
    score = _number(
        source.get("score")
        if source.get("score") not in (None, "")
        else source.get("stage_score", source.get("stage_rtdata_score"))
    )
    row: dict[str, Any] = {
        "market": market,
        "code": code,
        "name": str(source.get("name") or source.get("stock_name") or code).strip(),
        "rank": int(rank),
        "score": score,
        "stage_display_decision": _safe_decision(source),
        "next_validation_time": str(source.get("next_validation_time") or "").strip(),
        "cannot_confirm": [
            str(item) for item in source.get("cannot_confirm", []) if str(item).strip()
        ] if isinstance(source.get("cannot_confirm", []), list) else [],
        "data_level": str(source.get("data_level") or source.get("evidence_level") or "CANNOT_CONFIRM"),
        "recommendation_status": "WATCH_ONLY",
    }
    for field in _SAFE_NUMERIC_FIELDS:
        numeric = _number(source.get(field))
        if numeric is not None:
            row[field] = numeric
    return row


def normalize_reference(source: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping) or source.get("schema_version") != "v3_stage_workbench.v2":
        raise ValueError("invalid stage workbench export schema")
    trade_date = str(source.get("trade_date") or "")
    if len(trade_date) != 8 or not trade_date.isdigit():
        raise ValueError("invalid stage workbench export date")
    stage = source.get("stage")
    if not isinstance(stage, Mapping):
        raise ValueError("stage workbench export requires stage metadata")
    stage_id = str(stage.get("stage_id") or "")
    if stage_id not in FROZEN_STAGE_IDS:
        raise ValueError("unknown stage workbench export stage")
    source_rows = source.get("unified_rows")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("stage workbench export requires candidate rows")
    rows = [_normalize_row(row) for row in source_rows]
    a_count = sum(row["market"] == "A" for row in rows)
    hk_count = sum(row["market"] == "HK" for row in rows)
    source_markets = source.get("markets") if isinstance(source.get("markets"), Mapping) else {}

    def market_summary(market: str, label: str, count: int) -> dict[str, Any]:
        value = source_markets.get(market) if isinstance(source_markets, Mapping) else {}
        value = value if isinstance(value, Mapping) else {}
        source_count = _number(value.get("source_rows"))
        return {
            "label": label,
            "candidate_count": count,
            "source_rows": int(source_count) if source_count is not None and source_count >= 0 else count,
            "data_level": str(value.get("data_level") or "CANNOT_CONFIRM"),
        }

    return {
        "schema_version": "v3_stage_workbench.v2",
        "trade_date": trade_date,
        "stage": {
            "stage_id": stage_id,
            "label": str(stage.get("label") or stage_id),
            "window": str(stage.get("window") or ""),
            "status": str(stage.get("status") or "CANNOT_CONFIRM"),
            "display_status": str(stage.get("display_status") or ""),
        },
        "markets": {
            "A": market_summary("A", "A股", a_count),
            "HK": market_summary("HK", "港股通", hk_count),
        },
        "selected_a_rows": a_count,
        "selected_hk_rows": hk_count,
        "selected_total_rows": len(rows),
        "unified_rows": rows,
        "migration_provenance": "AUTHORITY_EXPORT_REFERENCE",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }


def import_reference_file(store: StageStore, source: Path) -> dict[str, str]:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    return store.import_reference_workbench(normalize_reference(payload))


def _json_file(value: str) -> Path:
    if "://" in value:
        raise argparse.ArgumentTypeError("URLs are not accepted")
    path = Path(value)
    if not path.is_file() or path.suffix.casefold() != ".json":
        raise argparse.ArgumentTypeError("source must be a local JSON file")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import local stage-workbench exports as V3.5 reference snapshots"
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=_json_file)
    arguments = parser.parse_args()
    store = StageStore(arguments.data_root)
    for source in arguments.source:
        result = import_reference_file(store, source)
        print(json.dumps({"source": source.name, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
