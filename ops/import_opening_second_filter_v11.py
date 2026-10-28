"""One-time offline migration of a frozen legacy v1.1 CSV + acceptance pair."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from domains.opening_second_filter import (
    CHAMPION_CONTRACT,
    MODEL_ID,
    SCHEMA_VERSION,
    TOP_N,
)
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore


_ROW_FIELDS = {
    "rank",
    "code",
    "ts_code",
    "name",
    "target_date",
    "signal_date",
    "preselect_rank",
    "preselect_lane",
    "auction_rank",
    "auction_score",
    "auction_label",
    "auction_ref_gap_pct",
    "first_to_last_ref_pct",
    "visible_depth_hkd",
    "bid_ask_imbalance",
    "spread_pct",
    "last_price",
    "prev_close_price",
    "bid_price",
    "ask_price",
    "bid_vol",
    "ask_vol",
    "turnover",
    "update_time",
    "collector_wall_time",
    "second_filter_status",
    "reference_price_hkd",
    "strict_failure_price_hkd",
    "strict_failure_pct",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric


def _normalize_row(source: dict[str, str]) -> dict[str, Any]:
    row = {key: source.get(key, "") for key in _ROW_FIELDS}
    for field in {
        "rank",
        "preselect_rank",
        "auction_rank",
        "auction_score",
        "auction_ref_gap_pct",
        "first_to_last_ref_pct",
        "visible_depth_hkd",
        "bid_ask_imbalance",
        "spread_pct",
        "last_price",
        "prev_close_price",
        "bid_price",
        "ask_price",
        "bid_vol",
        "ask_vol",
        "turnover",
        "reference_price_hkd",
        "strict_failure_price_hkd",
        "strict_failure_pct",
    }:
        row[field] = _number(row[field])
    row["rank"] = int(row["rank"]) if row["rank"] is not None else 0
    row["recommendation_status"] = "WATCH_ONLY"
    cannot_confirm = source.get("cannot_confirm", "")
    row["cannot_confirm"] = [cannot_confirm] if cannot_confirm else []
    return row


def import_legacy_v11_files(
    store: OpeningSecondFilterStore,
    acceptance_path: Path,
    csv_path: Path,
) -> dict[str, Any]:
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
    source_sha = _sha256_file(csv_path)
    if (
        acceptance.get("schema_version") != "hkconnect_0920_auction_second_filter.v2"
        or acceptance.get("status") != "AUCTION_SECOND_FILTER_READY"
        or acceptance.get("signal_cutoff") != "09:19:59"
        or acceptance.get("publication_time") != "09:20:00"
        or acceptance.get("row_count") != TOP_N
        or acceptance.get("required_row_count") != TOP_N
        or acceptance.get("csv_sha256") != source_sha
    ):
        raise ValueError("legacy v1.1 acceptance or CSV SHA does not match frozen contract")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [_normalize_row(dict(row)) for row in csv.DictReader(handle)]
    if len(rows) != TOP_N:
        raise ValueError("legacy v1.1 CSV must contain Top20")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "version": "1.1",
        "champion_contract": CHAMPION_CONTRACT,
        "trade_date": str(acceptance["target_date"]),
        "signal_date": str(acceptance["signal_date"]),
        "stage_id": "STAGE_0925",
        "signal_cutoff": "09:19:59",
        "publication_time": "09:20:00",
        "status": "AUCTION_SECOND_FILTER_READY",
        "row_count": len(rows),
        "required_row_count": TOP_N,
        "d1_membership_model": "0.2",
        "same_day_rerank_model": "1.1",
        "preselect_row_count": int(acceptance.get("preselect_row_count") or 0),
        "auction_row_count": int(acceptance.get("auction_row_count") or 0),
        "rows": rows,
        "source_evidence": {
            "d1_pool_sha256": str(acceptance["preselect_sha256"]),
            "auction_source_sha256": str(acceptance["auction_source_sha256"]),
            "source_output_sha256": source_sha,
        },
        "migration_provenance": "FROZEN_V1_1_ACCEPTANCE_AND_CSV",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    return store.publish(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import frozen v1.1 second-filter evidence")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()
    result = import_legacy_v11_files(
        OpeningSecondFilterStore(args.data_root),
        args.acceptance,
        args.csv,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
