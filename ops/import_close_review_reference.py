"""Offline importer for sanitized close-review reference exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from contracts.stages import FROZEN_STAGE_IDS
from infrastructure.review_store import ReviewStore


_METRIC_FIELDS = (
    "evidence_status",
    "selected_count",
    "hit_count",
    "coverage",
    "precision",
    "coverage_pct",
    "precision_pct",
)
_ROW_FIELDS = {
    "close_top20": ("rank", "code", "name", "pct_chg", "pct_chg_close", "close", "pre_close", "amount", "trade_date"),
    "model_rows": ("rank", "code", "name", "strategy", "pool_version", "trade_date", "hit_top20"),
    "stage_rows": ("stage_id", "stage_rank", "code", "name", "trade_date", "hit_top20"),
    "top20_attribution": (
        "rank", "code", "name", "pct_chg", "pct_chg_close", "close", "pre_close", "amount",
        "trade_date", "model_0_2_hit", "stage_union_hit", "first_stage", "all_stages", "classification",
    ),
}


def _number(value: Any) -> int | float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _metric(source: Any) -> dict[str, Any]:
    source = source if isinstance(source, Mapping) else {}
    result: dict[str, Any] = {}
    for field in _METRIC_FIELDS:
        value = source.get(field)
        if field == "evidence_status":
            result[field] = str(value or "MISSING")
        else:
            result[field] = _number(value)
    for field in ("selected_codes", "hit_codes"):
        values = source.get(field)
        result[field] = [str(value) for value in values if str(value).strip()] if isinstance(values, list) else []
    return result


def _rows(source: Any, kind: str, trade_date: str) -> list[dict[str, Any]]:
    if not isinstance(source, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, Mapping):
            continue
        row = {field: item[field] for field in _ROW_FIELDS[kind] if field in item}
        row["trade_date"] = trade_date
        if "all_stages" in row:
            stages = row["all_stages"]
            row["all_stages"] = [
                str(stage) for stage in stages if str(stage) in FROZEN_STAGE_IDS
            ] if isinstance(stages, list) else []
        rows.append(row)
    return rows


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def normalize_review_reference(source: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValueError("invalid review export")
    trade_date = str(source.get("trade_date") or "")
    if len(trade_date) != 8 or not trade_date.isdigit():
        raise ValueError("invalid review export date")
    markets = source.get("market_reviews")
    hk = markets.get("HK") if isinstance(markets, Mapping) else None
    review = hk.get("model_selection_review") if isinstance(hk, Mapping) else None
    if not isinstance(review, Mapping) or str(review.get("trade_date") or trade_date) != trade_date:
        raise ValueError("review export identity mismatch")
    source_models = review.get("models") if isinstance(review.get("models"), Mapping) else {}
    source_stages = review.get("stages") if isinstance(review.get("stages"), Mapping) else {}
    models = {str(key): _metric(value) for key, value in source_models.items()}
    stages = {
        str(key): _metric(value)
        for key, value in source_stages.items()
        if str(key) in FROZEN_STAGE_IDS
    }
    return {
        "schema_version": "v3_5.close_review_reference.v1",
        "trade_date": trade_date,
        "status": str(review.get("status") or "CANNOT_CONFIRM"),
        "primary_kpi": str(review.get("primary_kpi") or "全港股通收盘涨幅Top20覆盖率"),
        "models": models,
        "stages": stages,
        "stage_union": _metric(review.get("stage_union")),
        "kpi": {
            str(key): value
            for key, value in (review.get("kpi") or {}).items()
            if isinstance(key, str) and _number(value) is not None
        } if isinstance(review.get("kpi"), Mapping) else {},
        "row_counts": {
            str(key): int(number)
            for key, value in (review.get("row_counts") or {}).items()
            if isinstance(key, str) and (number := _number(value)) is not None and number >= 0
        } if isinstance(review.get("row_counts"), Mapping) else {},
        "close_top20": _rows(review.get("close_top20"), "close_top20", trade_date),
        "model_rows": _rows(review.get("model_rows"), "model_rows", trade_date),
        "stage_rows": _rows(review.get("stage_rows"), "stage_rows", trade_date),
        "top20_attribution": _rows(review.get("top20_attribution"), "top20_attribution", trade_date),
        "missing_stages": [
            stage for stage in _string_list(review.get("missing_stages")) if stage in FROZEN_STAGE_IDS
        ],
        "cannot_confirm": _string_list(review.get("cannot_confirm")),
        "reference_snapshot": True,
        "write_policy": "review_only_read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def import_reference_file(store: ReviewStore, source: Path) -> dict[str, str]:
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    return store.import_reference(normalize_review_reference(payload))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a local V3 close-review export")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    result = import_reference_file(ReviewStore(args.data_root), args.source)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
