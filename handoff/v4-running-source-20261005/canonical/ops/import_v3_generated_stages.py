"""Adapt V3 generated_stage CSVs into V3.5-owned stage input JSON.

Reads the V3 runtime's ``generated_stages/{date}/generated_stage*_*.csv``
(Futu OpenD real captures) and writes equivalent ``v3_5.stage_input.v1``
payloads into the V3.5 stage store. This is the read-only bridge the V3.5
decision desk uses when pytdx is unavailable: V3 already captured the stage
quotes, V3.5 only re-wraps them under its own schema. Nothing writes to V3.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from contracts.stages import FROZEN_STAGE_IDS
from infrastructure.stage_store import StageStore


# v3 stage file -> v3.5 stage id
STAGE_FILE_MAP = {
    "STAGE_0925": "generated_stage1_0925_auction_{date}.csv",
    "STAGE_0930_0935": "generated_stage2_0930_0935_1min_replay_{date}.csv",
    "STAGE_0935_0940": "generated_stage3_0935_0940_1min_replay_{date}.csv",
    "STAGE_0940_0945": "generated_stage4_0940_0945_1min_replay_{date}.csv",
    "STAGE_0945_1030": "generated_stage5_0945_1030_1min_replay_{date}.csv",
    "STAGE_1300_1315": "generated_stage6_1300_1315_1min_replay_{date}.csv",
    "STAGE_1445_1500": "generated_stage7_1445_1500_1min_replay_{date}.csv",
    "STAGE_1545_1555": "generated_stage8_1545_1555_1min_replay_{date}.csv",
}


def _f(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _a_symbol(ts_code: str) -> str:
    match = __import__("re").search(r"(\d{6})", str(ts_code or ""))
    return f"A.{match.group(1)}" if match else ""


def _hk_symbol(code: str) -> str:
    match = __import__("re").search(r"(\d{5})", str(code or ""))
    return f"HK.{match.group(1)}" if match else ""


def build_stage_input(stage_id: str, trade_date: str, csv_path: Path, source_sha: str, *, hk_csv: Path | None = None) -> dict:
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        raw_rows = list(csv.DictReader(source))
    a_rows: list[dict] = []
    hk_rows: list[dict] = []
    for index, raw in enumerate(raw_rows, start=1):
        ts = str(raw.get("ts_code") or "")
        name = str(raw.get("name") or raw.get("display_name") or "")
        first_open = _f(raw.get("first_open"))
        last_close = _f(raw.get("last_close"))
        high = _f(raw.get("high_price"))
        low = _f(raw.get("low_price"))
        change_pct = _f(raw.get("window_change_pct"))
        amount = _f(raw.get("amount_in_window"))
        pool_score = _f(raw.get("pool_score"))
        if ts.startswith("HK.") or ts.startswith("hk"):
            symbol = _hk_symbol(ts)
            market = "HK"
        else:
            symbol = _a_symbol(ts)
            market = "A"
        if not symbol:
            continue
        row = {
            "symbol": symbol,
            "market": market,
            "pool_id": raw.get("candidate_source") or "v3_generated_stage",
            "pool_rank": index,
            "pool_score": pool_score,
            "stock_name": name,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "data_level": raw.get("data_level") or "V3_GENERATED_STAGE_CSV",
            "open_price": first_open,
            "last_price": last_close,
            "high_price": high,
            "low_price": low,
            "window_change_pct": change_pct,
            "amount_in_window": amount,
            "source_method": "v3_generated_stage_csv_read_only",
            "source_trace_sha256": source_sha[:64],
            "source_label": "v3 generated stage capture (read-only rewrap)",
        }
        (a_rows if market == "A" else hk_rows).append(row)
    if hk_csv is not None and hk_csv.is_file():
        with hk_csv.open(encoding="utf-8-sig", newline="") as source:
            hk_raw_rows = list(csv.DictReader(source))
        for index, raw in enumerate(hk_raw_rows, start=1):
            code = str(raw.get("code") or "")
            symbol = _hk_symbol(code)
            if not symbol:
                continue
            hk_rows.append({
                "symbol": symbol,
                "market": "HK",
                "pool_id": "v3_hkconnect_rtdata_stage_replay",
                "pool_rank": index,
                "pool_score": _f(raw.get("pct_chg")),
                "stock_name": str(raw.get("name") or symbol),
                "recommendation_status": "WATCH_ONLY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "data_level": "V3_HKCONNECT_RTDATA_STAGE_REPLAY",
                "open_price": 0.0,
                "last_price": _f(raw.get("last_price")),
                "high_price": 0.0,
                "low_price": 0.0,
                "window_change_pct": _f(raw.get("pct_chg")),
                "amount_in_window": _f(raw.get("turnover_hkd")),
                "source_method": "v3_hkconnect_rtdata_replay_read_only",
                "source_trace_sha256": source_sha[:64],
                "source_label": "v3 hkconnect rtdata stage replay (read-only rewrap)",
            })
    return {
        "schema_version": "v3_5.stage_input.v1",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "cutoff_reached": True,
        "market_status": {
            "A": "READY" if a_rows else "CANNOT_CONFIRM",
            "HK": "READY" if hk_rows else "CANNOT_CONFIRM",
        },
        "rows": {"A": a_rows, "HK": hk_rows},
        "source_evidence": [
            {"path": csv_path.name, "sha256": source_sha[:64], "kind": "v3_generated_stage_csv"}
        ],
        "source_summary": {
            "quote_source": "V3_GENERATED_STAGE_CSV_READ_ONLY",
            "cannot_confirm": [
                "V3_GENERATED_STAGE_CSV_REWRAP: prices are V3-captured, not V3.5 realtime",
            ],
        },
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--v3-stage-root", required=True, type=Path)
    parser.add_argument("--v3-hk-replay-root", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=Path.cwd() / ".runtime" / "data")
    parser.add_argument("--stages", default=",".join(FROZEN_STAGE_IDS))
    args = parser.parse_args()

    store = StageStore(args.data_root)
    wanted = {sid for sid in str(args.stages).split(",") if sid}
    imported = []
    for stage_id, pattern in STAGE_FILE_MAP.items():
        if stage_id not in wanted:
            continue
        csv_path = args.v3_stage_root / pattern.format(date=args.trade_date)
        if not csv_path.is_file():
            imported.append({"stage_id": stage_id, "status": "SOURCE_MISSING"})
            continue
        source_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        hk_csv = None
        if args.v3_hk_replay_root is not None:
            hk_csv = args.v3_hk_replay_root / stage_id / f"hkconnect_rtdata_stage_replay_{args.trade_date}_{stage_id}.csv"
        payload = build_stage_input(stage_id, args.trade_date, csv_path, source_sha, hk_csv=hk_csv)
        try:
            store.import_input(payload)
            imported.append({
                "stage_id": stage_id,
                "status": "IMPORTED",
                "a_rows": len(payload["rows"]["A"]),
                "hk_rows": len(payload["rows"]["HK"]),
            })
        except ValueError as error:
            imported.append({"stage_id": stage_id, "status": f"REJECTED: {error}"})
    print(json.dumps({"trade_date": args.trade_date, "imported": imported}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
