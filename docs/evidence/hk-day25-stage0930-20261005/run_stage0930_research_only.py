#!/usr/bin/env python3
"""Run one isolated HK 2026-09-25 STAGE_0930_0935 research observation.

The adapter reads only the previously verified 81-row raw artifact and the
separately hashed 19-member research projection. It then calls the current
V4 StageCenterRunner with its production selector and exact D-1 validator.
No market-data provider is invoked by this script.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
sys.path.insert(0, str(PROJECT_ROOT))

from stage_center.acquisition import SourceResult
from stage_center.raw_store import RAW_FIELDS, RawStore, validate_rows
from stage_center.runner import StageCenterRunner, build_production_config
from stage_center.selection import SelectionStore


TARGET_DATE = "20260925"
STAGE_ID = "STAGE_0930_0935"
MARKET = "HK_CONNECT"
SOURCE_ID = "hk_stage0930_research_observation_r1"
RESEARCH_CONTRACT = "HK_STAGE0930_RESEARCH_ONLY"
PIT_STATUS = "NOT_FORMAL_PIT_MINUTE_CAPTURE_OCCURRED_AFTER_TARGET_CUTOFF"
EXPECTED = {
    "base_raw": "eabaa273897b0db7261d0e0d3245493e75297e5f148edad665061d90fb5f6070",
    "gap_fields": "11e256bec4ee181f956bb2792260290b1e2b5784a9838ebef91b3074eebbcc3e",
    "gap_csv": "d02371d0d8fdb28fad944bc0881943ba1deb4899bf57b11f9a4f3d1adb6a7546",
    "gap_receipt": "1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a",
    "d1_pool": "c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0",
    "d1_codes": "07e8760a9c3171691d26a43240795c6b56e7a494fadb6acbd5f153b7801b7b34",
}
MISSING_LAST = {"HK.03268", "HK.03355", "HK.03881", "HK.09690"}
ZERO_VOLUME_REFERENCES = {"HK.01304", "HK.01333", "HK.01377"}
ALLOWED_ROW_SOURCES = {
    "futu_request_history_kline_none",
    "EASTMONEY_HK_HISTORICAL_1M",
    "YAHOO_FINANCE_CHART_1M",
}

HERE = Path(__file__).resolve().parent
DAY_ROOT = HERE.parent
STAGE_ROOT = DAY_ROOT / "stage0930_true_d1"
INPUT_ROOT = STAGE_ROOT / "minute_gap19_repair" / "necessary_fields_20261005_r1"
BASE_RAW_ROOT = STAGE_ROOT / "raw" / "backfill" / "hk_observation_restore_r2_20261004_r1"
D1_ROOT = DAY_ROOT / "newpool_projection"
RUN_ROOT = HERE / "runtime_hk0930_research_binding_r2"
CONFIG_PATH = HERE / "tick_config_hk0930_research_binding_r2.json"
RUN_RECEIPT_PATH = HERE / "runner_invocation_receipt_hk0930_research_binding_r2.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _label(value: Any) -> datetime:
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"supplement row label is not an ISO timestamp: {value}")
    if parsed.tzinfo is not None:
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() != 8 * 60 * 60:
            raise ValueError(f"supplement row label is not Asia/Hong_Kong local time: {value}")
        parsed = parsed.replace(tzinfo=None)
    if parsed.strftime("%Y%m%d") != TARGET_DATE:
        raise ValueError(f"supplement row label date mismatch: {value}")
    if not datetime.strptime("2026-09-25 09:30:00", "%Y-%m-%d %H:%M:%S") <= parsed < datetime.strptime(
        "2026-09-25 09:35:05", "%Y-%m-%d %H:%M:%S"
    ):
        raise ValueError(f"supplement row label falls outside stage bounds: {value}")
    return parsed


def _load_inputs(plan) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], tuple[str, ...]]:
    if plan.trade_date != TARGET_DATE or plan.stage_id != STAGE_ID:
        raise ValueError("research adapter received an unexpected date or stage")

    pool_path = D1_ROOT / "preselection_pools" / TARGET_DATE / "hkconnect_d1_top100.json"
    if _sha256(pool_path) != EXPECTED["d1_pool"]:
        raise ValueError("exact D-1 pool file SHA mismatch")
    pool_payload = json.loads(pool_path.read_text(encoding="utf-8"))
    pool_rows = pool_payload.get("rows", pool_payload.get("data")) or []
    pool_codes = tuple(
        sorted(str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").upper() for row in pool_rows)
    )
    if len(pool_codes) != 100 or len(set(pool_codes)) != 100:
        raise ValueError("exact D-1 pool must have 100 unique codes")
    pool_codes_sha = hashlib.sha256(
        json.dumps(pool_codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if pool_codes_sha != EXPECTED["d1_codes"] or set(pool_codes) != set(plan.codes_for(MARKET)):
        raise ValueError("runner D-1 membership differs from the pinned 100-code pool")
    d1_by_code = {
        str(row.get("code") or row.get("ts_code") or row.get("stock_code") or "").upper(): row
        for row in pool_rows
    }

    verified_slot = RawStore(BASE_RAW_ROOT).verify_latest(TARGET_DATE, STAGE_ID, MARKET)
    entry = verified_slot["latest"]
    verified = verified_slot["verified"]
    if verified.get("artifact_sha256") != EXPECTED["base_raw"]:
        raise ValueError("previous 81-row baseline is absent or has changed")
    if verified.get("run_id") != "20260925-hk_connect_1min_stage_0930_0935-d875c550a3d8f564":
        raise ValueError("previous baseline run identity mismatch")
    if any(entry.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("previous baseline latest safety flags must remain false")
    manifest_path = BASE_RAW_ROOT / verified["manifest_relative"]
    receipt_path = BASE_RAW_ROOT / verified["receipt_relative"]
    artifact_path = BASE_RAW_ROOT / verified["artifact_relative"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("trade_date") != TARGET_DATE
        or manifest.get("stage_id") != STAGE_ID
        or manifest.get("market") != MARKET
        or manifest.get("source_id") != "futu_request_history_kline_none"
        or manifest.get("status") != "PARTIAL_WITH_ROWS"
        or manifest.get("requested_rows") != 100
        or any(manifest.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise ValueError("previous baseline manifest identity/status mismatch")
    if _sha256(artifact_path) != EXPECTED["base_raw"]:
        raise ValueError("previous baseline raw artifact SHA mismatch")
    with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
        base_rows = list(csv.DictReader(stream))
    if len(base_rows) != 81:
        raise ValueError(f"expected 81 prior raw rows, found {len(base_rows)}")

    fields_path = INPUT_ROOT / "fields_by_code.json"
    gap_csv_path = INPUT_ROOT / "fields_by_code.csv"
    gap_receipt_path = INPUT_ROOT / "gap_receipt.json"
    if _sha256(fields_path) != EXPECTED["gap_fields"]:
        raise ValueError("necessary fields JSON SHA mismatch")
    if _sha256(gap_csv_path) != EXPECTED["gap_csv"]:
        raise ValueError("necessary fields CSV SHA mismatch")
    if _sha256(gap_receipt_path) != EXPECTED["gap_receipt"]:
        raise ValueError("gap receipt SHA mismatch")
    gap_payload = json.loads(fields_path.read_text(encoding="utf-8"))
    if (
        gap_payload.get("target_date") != TARGET_DATE
        or gap_payload.get("signal_date") != "20260924"
        or gap_payload.get("stage_id") != STAGE_ID
    ):
        raise ValueError("necessary fields date/stage identity mismatch")
    supplements = gap_payload.get("rows")
    if not isinstance(supplements, list) or len(supplements) != 19:
        raise ValueError("necessary fields must contain the exact 19-member gap")

    base_missing = {str(code).upper() for code in manifest.get("missing_symbols", ())}
    supplemental_codes = {str(row.get("code") or "").upper() for row in supplements}
    if supplemental_codes != base_missing or len(supplemental_codes) != 19:
        raise ValueError("necessary fields do not exactly cover the prior Top100 gap")
    if not base_missing.issubset(set(pool_codes)):
        raise ValueError("prior Top100 gap is outside exact runner membership")

    code_rows: dict[str, dict[str, Any]] = {}
    base_source_id = str(manifest.get("source_id") or "")
    if base_source_id not in ALLOWED_ROW_SOURCES:
        raise ValueError("prior baseline source identity is not permitted")
    for raw in base_rows:
        code = str(raw.get("code") or "").upper()
        if code not in pool_codes or code in code_rows:
            raise ValueError("prior raw rows contain a duplicate or out-of-pool code")
        row = dict(raw)
        for key in ("batch_index", "bar_count"):
            row[key] = int(row[key])
        for key in ("last_price", "open_price", "high_price", "low_price", "prev_close_price", "turnover", "volume", "bid_price", "ask_price", "bid_vol", "ask_vol"):
            row[key] = _number(row.get(key))
        row["temporal_cutoff_safe"] = str(row.get("temporal_cutoff_safe", "")).lower() == "true"
        volume = row.get("volume")
        if volume == 0:
            row.update(last_price=None, open_price=None, high_price=None, low_price=None, turnover=None)
        row.update(
            historical_source_id=base_source_id,
            historical_turnover_unit="HKD",
            historical_observation_contract=RESEARCH_CONTRACT,
            formal_pit_status=PIT_STATUS,
            volume_ratio=None,
            turnover_rate=None,
            platform_circular_market_cap_hkd_yi=None,
            offer_float_market_cap_hkd_yi=None,
        )
        code_rows[code] = row

    supplemental_source_by_code: dict[str, str] = {}
    supplement_price_label_by_code: dict[str, str] = {}
    yahoo_amount_codes: list[str] = []
    eastmoney_amount_codes: list[str] = []
    missing_last_codes: list[str] = []
    zero_reference_codes: list[str] = []
    for item in supplements:
        code = str(item.get("code") or "").upper()
        source_id = str(item.get("minute_source_id") or "")
        if code not in pool_codes or source_id not in ALLOWED_ROW_SOURCES or code in code_rows:
            raise ValueError(f"supplement row identity invalid: {code}")
        supplemental_source_by_code[code] = source_id
        if source_id == "YAHOO_FINANCE_CHART_1M":
            yahoo_amount_codes.append(code)
        amount_unit = str(item.get("turnover_unit") or "")
        if amount_unit == "HKD" and source_id == "EASTMONEY_HK_HISTORICAL_1M":
            eastmoney_amount_codes.append(code)

        evidence_class = str(item.get("last_price_evidence_class") or "")
        if evidence_class == "NO_VALID_WINDOW_PRICE":
            if item.get("last_price_candidate") is not None:
                raise ValueError(f"missing-price code unexpectedly has a price: {code}")
            missing_last_codes.append(code)
            continue

        window_rows = item.get("window_rows") or []
        observed_labels = [_label(row.get("label")) for row in window_rows if row.get("label")]
        if not observed_labels:
            raise ValueError(f"supplement observation window label missing: {code}")
        observation_end = max(observed_labels)
        if evidence_class == "SOURCE_REPORTED_PRICE_REFERENCE_ZERO_WINDOW_VOLUME":
            if _number(item.get("window_volume_sum_source_native")) != 0.0:
                raise ValueError(f"zero-volume reference does not have a verified zero volume sum: {code}")
            if item.get("last_positive_volume_label") is not None:
                raise ValueError(f"zero-volume reference cannot have a positive-price label: {code}")
            price_label = None
            last_price = None
            volume = 0.0
            turnover = 0.0 if amount_unit == "HKD" else None
            zero_reference_codes.append(code)
        elif evidence_class == "POSITIVE_VOLUME_OBSERVED_SOMEWHERE_IN_WINDOW":
            label_value = str(item.get("last_positive_volume_label") or "")
            match = next((row for row in window_rows if str(row.get("label") or "") == label_value), None)
            if match is None or _number(match.get("volume")) is None or _number(match.get("volume")) <= 0:
                raise ValueError(f"positive-volume price label does not match a positive-volume source row: {code}")
            price_label = _label(label_value)
            last_price = _number(item.get("last_positive_volume_price_candidate"))
            if last_price is None or last_price <= 0:
                raise ValueError(f"positive-volume price is missing or non-positive: {code}")
            volume = _number(item.get("window_volume_sum_source_native")) if item.get("volume_unit") == "shares" else None
            turnover = _number(item.get("window_turnover_sum_source_native")) if amount_unit == "HKD" else None
        elif evidence_class == "POSITIVE_VOLUME_COMPLETE_BAR":
            complete = [
                row for row in window_rows
                if (_number(row.get("volume")) or 0.0) > 0
                and all(_number(row.get(key)) is not None for key in ("open", "high", "low", "close"))
            ]
            if not complete:
                raise ValueError(f"positive-volume complete bar is absent: {code}")
            selected = max(complete, key=lambda row: str(row.get("label") or ""))
            price_label = _label(selected.get("label"))
            last_price = _number(selected.get("close"))
            if last_price is None or last_price <= 0:
                raise ValueError(f"complete-bar price is missing or non-positive: {code}")
            # Yahoo source-native volume units are not confirmed by its receipt.
            volume = None
            turnover = None
        else:
            raise ValueError(f"unknown last-price evidence class for {code}: {evidence_class}")

        d1_row = d1_by_code.get(code) or {}
        prev_close = _number(item.get("d1_prev_close_hkd"))
        d1_prev_close = _number(d1_row.get("d1_close_hkd") or d1_row.get("d1_snapshot_close_hkd"))
        if prev_close is None or d1_prev_close is None or not math.isclose(prev_close, d1_prev_close, rel_tol=0, abs_tol=1e-5):
            raise ValueError(f"signal-date D-1 close differs between pool and gap input: {code}")
        observation_start = min(observed_labels)
        if price_label is not None:
            supplement_price_label_by_code[code] = price_label.strftime("%H:%M:%S")
        start = observation_start.strftime("%Y-%m-%d %H:%M:%S")
        end = observation_end.strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "batch_index": pool_codes.index(code) + 1,
            "code": code,
            "name": str(item.get("name") or code),
            # RawStore's immutable 19-field schema requires update_time to
            # equal window_end, so retain the actual full observation-window
            # end here. Selection gets this separate price-bar timestamp.
            "update_time": end,
            "source_last_bar_time": price_label.strftime("%Y-%m-%d %H:%M:%S") if price_label else None,
            "last_price": last_price,
            "open_price": None,
            "high_price": None,
            "low_price": None,
            "prev_close_price": prev_close,
            "turnover": turnover,
            "volume": volume,
            "bid_price": None,
            "ask_price": None,
            "bid_vol": None,
            "ask_vol": None,
            "window_start": start,
            "window_end": end,
            "bar_count": int(item.get("window_row_count") or len(window_rows) or 1),
            "temporal_cutoff_safe": True,
            "historical_source_id": source_id,
            "historical_turnover_unit": "HKD" if amount_unit == "HKD" else None,
            "historical_observation_contract": RESEARCH_CONTRACT,
            "formal_pit_status": PIT_STATUS,
            "volume_ratio": None,
            "turnover_rate": None,
            "platform_circular_market_cap_hkd_yi": None,
            "offer_float_market_cap_hkd_yi": None,
        }
        if code in ZERO_VOLUME_REFERENCES and last_price is not None:
            raise ValueError(f"zero-volume reference price cannot be used: {code}")
        code_rows[code] = row

    if set(missing_last_codes) != MISSING_LAST or set(zero_reference_codes) != ZERO_VOLUME_REFERENCES:
        raise ValueError("supplement missing-price or zero-volume reference set changed")
    if len(code_rows) != 96 or set(code_rows) | set(missing_last_codes) != set(pool_codes):
        raise ValueError("combined source rows do not match the exact 100-code D-1 pool")
    rows = tuple(code_rows[code] for code in pool_codes if code in code_rows)
    if len(rows) != 96 or any(set(RAW_FIELDS) - set(row) for row in rows):
        raise ValueError("combined research rows do not satisfy the raw-store contract")
    raw_projection = tuple({field: row[field] for field in RAW_FIELDS} for row in rows)
    _, row_issues = validate_rows(raw_projection, trade_date=TARGET_DATE, stage_id=STAGE_ID, market=MARKET)
    if row_issues:
        raise ValueError(f"combined research rows failed raw-store validation: {row_issues[:3]}")

    input_markers = [
        f"historical_observation_contract={RESEARCH_CONTRACT}",
        f"historical_base_raw_sha256={EXPECTED['base_raw']}",
        f"historical_gap_fields_sha256={EXPECTED['gap_fields']}",
        f"historical_gap_csv_sha256={EXPECTED['gap_csv']}",
        f"historical_gap_receipt_sha256={EXPECTED['gap_receipt']}",
        f"historical_d1_pool_sha256={EXPECTED['d1_pool']}",
        "historical_formal_pit=false",
        "historical_active_lane_authority=UNVERIFIED",
        "historical_minute_label_boundary=CANNOT_CONFIRM",
        "historical_volume_ratio=UNKNOWN",
        "historical_turnover_rate=UNKNOWN",
        "historical_platform_cap_mapping=UNKNOWN",
        "historical_free_float_cap=UNKNOWN",
        "historical_amount_02402=UNKNOWN_UNIT_NOT_USED",
        f"historical_zero_volume_price_reference_only_codes={','.join(sorted(zero_reference_codes))}",
        f"historical_missing_last_price_codes={','.join(sorted(missing_last_codes))}",
        f"historical_base_source_id={base_source_id}",
        f"historical_source_row_count_{base_source_id}={len(base_rows)}",
        "historical_source_row_count_EASTMONEY_HK_HISTORICAL_1M=" + str(sum(v == "EASTMONEY_HK_HISTORICAL_1M" for v in supplemental_source_by_code.values())),
        "historical_source_row_count_YAHOO_FINANCE_CHART_1M=" + str(sum(v == "YAHOO_FINANCE_CHART_1M" for v in supplemental_source_by_code.values())),
        "historical_supplement_hkd_amount_code_count=" + str(len(eastmoney_amount_codes)),
        f"historical_yahoo_amount_unavailable_codes={','.join(sorted(yahoo_amount_codes))}",
        f"historical_observed_last_price_labels={json.dumps(supplement_price_label_by_code, sort_keys=True, separators=(',', ':'))}",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    ]
    input_markers.extend(
        f"historical_supplement_source_id={code}:{source_id}"
        for code, source_id in sorted(supplemental_source_by_code.items())
    )
    input_markers.extend(
        f"historical_supplement_last_positive_label={code}:{label}"
        for code, label in sorted(supplement_price_label_by_code.items())
    )
    input_markers.extend(
        f"historical_zero_volume_reference_only={code}"
        for code in sorted(zero_reference_codes)
    )
    cannot_confirm = (
        "HISTORICAL_MINUTE_LABEL_BOUNDARY_NOT_FULLY_CONFIRMED",
        "HISTORICAL_ACTIVE_LANE_AUTHORITY_UNVERIFIED",
        "HISTORICAL_VOLUME_RATIO_MISSING",
        "HISTORICAL_TURNOVER_RATE_MISSING",
        "HISTORICAL_PLATFORM_CAP_MAPPING_UNVERIFIED",
        "HISTORICAL_FREE_FLOAT_CAP_UNVERIFIED",
        "HISTORICAL_AMOUNT_02402_UNIT_UNVERIFIED",
        "HISTORICAL_YAHOO_AMOUNT_UNAVAILABLE",
        *(f"HISTORICAL_NO_VALID_LAST_PRICE:{code}" for code in sorted(missing_last_codes)),
    )
    return rows, tuple(cannot_confirm), tuple(input_markers)


def _collector(plan, market):
    if market != MARKET:
        raise ValueError("research adapter is HK-only")
    rows, cannot_confirm, evidence = _load_inputs(plan)
    return SourceResult(
        source_id=SOURCE_ID,
        status="PARTIAL_WITH_ROWS",
        rows=rows,
        cannot_confirm=cannot_confirm,
        requested_rows=100,
        missing_symbols=tuple(sorted(MISSING_LAST)),
        source_evidence=evidence,
    )


def _store_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
    path.write_bytes(encoded)


def main() -> int:
    original_config_path = STAGE_ROOT / "tick_config.json"
    original = json.loads(original_config_path.read_text(encoding="utf-8"))
    output_config = {
        "schema_version": "hk_stage0930_research_only_runner_config.v1",
        "candidate_acquisition_root": str(RUN_ROOT / "candidate"),
        "raw_root": str(RUN_ROOT / "raw"),
        "selection_root": str(RUN_ROOT / "selection"),
        "receipt_root": str(RUN_ROOT / "receipts"),
        "hk_d1_root": str(D1_ROOT),
        "preselection_source_root": str(D1_ROOT),
        "shared_data_root": str(Path(original["shared_data_root"])),
        "python_path": str(Path(original["python_path"])),
        "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        "collector": "local hash-pinned file adapter; no provider call",
        "selection_builders": "current production_selection_builders; selection_builders=None",
    }
    _store_json(CONFIG_PATH, output_config)
    config = build_production_config(
        candidate_acquisition_root=output_config["candidate_acquisition_root"],
        raw_root=output_config["raw_root"],
        selection_root=output_config["selection_root"],
        receipt_root=output_config["receipt_root"],
        hk_d1_root=output_config["hk_d1_root"],
        preselection_source_root=output_config["preselection_source_root"],
        shared_data_root=output_config["shared_data_root"],
        python_path=output_config["python_path"],
    )
    if config.injected_test_mode:
        raise RuntimeError("runner unexpectedly entered injected-test mode")

    runner = StageCenterRunner(config, collectors={MARKET: _collector})
    receipts_before = set(
        (RUN_ROOT / "receipts" / "backfill").glob(f"*/{TARGET_DATE}/{STAGE_ID}/receipt.json")
    )
    result = runner.tick(
        TARGET_DATE,
        datetime.fromisoformat("2026-10-05T12:00:00+08:00"),
        stage_id=STAGE_ID,
        historical_backfill=True,
        historical_markets=(MARKET,),
        historical_research_contract=RESEARCH_CONTRACT,
        _skip_precapture=True,
    )
    actual_receipts = list((RUN_ROOT / "receipts" / "backfill").glob(f"*/{TARGET_DATE}/{STAGE_ID}/receipt.json"))
    new_receipts = [path for path in actual_receipts if path not in receipts_before]
    if len(new_receipts) != 1:
        raise RuntimeError(f"expected exactly one new runner execution receipt, found {len(new_receipts)}")
    actual_receipt = new_receipts[0]
    backfill_run_id = actual_receipt.parents[2].name
    raw_run_root = RUN_ROOT / "raw" / "backfill" / backfill_run_id
    selection_run_root = RUN_ROOT / "selection" / "backfill" / backfill_run_id
    raw_latest_path = raw_run_root / "latest.json"
    selection_latest_path = selection_run_root / "selection_latest.json"
    raw_latest = json.loads(raw_latest_path.read_text(encoding="utf-8")) if raw_latest_path.is_file() else {}
    selection_latest = json.loads(selection_latest_path.read_text(encoding="utf-8")) if selection_latest_path.is_file() else {}
    slot_key = f"{TARGET_DATE}/{STAGE_ID}/{MARKET}"
    raw_entry = raw_latest.get("entries", {}).get(slot_key)
    selection_entry = selection_latest.get("entries", {}).get(slot_key)
    market_result = result.get("markets", {}).get(MARKET, {})
    if not raw_entry or not selection_entry:
        output_receipt = {
            "schema_version": "hk_stage0930_research_only_runner_receipt.v1",
            "runner_call": {
                "trade_date": TARGET_DATE,
                "stage_id": STAGE_ID,
                "historical_backfill": True,
                "historical_markets": [MARKET],
                "historical_research_contract": RESEARCH_CONTRACT,
                "skip_precapture": True,
                "injected_test_mode": config.injected_test_mode,
            },
            "config_path": str(CONFIG_PATH),
            "config_sha256": _sha256(CONFIG_PATH),
            "candidate_run_id": backfill_run_id,
            "actual_runner_receipt": {
                "path": str(actual_receipt),
                "sha256": _sha256(actual_receipt),
            },
            "runner_lane_result": market_result,
            "runner_result": result,
            "provider_calls": 0,
            "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        _store_json(RUN_RECEIPT_PATH, output_receipt)
        print(json.dumps({
            "pass": False,
            "run_receipt": str(RUN_RECEIPT_PATH),
            "runner_receipt": str(actual_receipt),
            "selection_status": market_result.get("selection_status"),
            "selected_rows": market_result.get("selected_rows"),
            "candidate_run_id": backfill_run_id,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    raw_verified = RawStore(raw_run_root).verify_latest(
        TARGET_DATE, STAGE_ID, MARKET
    )["verified"]
    selection_envelope = SelectionStore(selection_run_root).read_verified(
        TARGET_DATE, STAGE_ID, MARKET
    )
    raw_artifact = raw_run_root / raw_entry["artifact_relative"]
    selection_artifact = selection_run_root / selection_entry["artifact_relative"]
    selection_manifest = selection_artifact.parent / "manifest.json"
    output_receipt = {
        "schema_version": "hk_stage0930_research_only_runner_receipt.v1",
        "runner_call": {
            "trade_date": TARGET_DATE,
            "stage_id": STAGE_ID,
            "historical_backfill": True,
            "historical_markets": [MARKET],
            "historical_research_contract": RESEARCH_CONTRACT,
            "skip_precapture": True,
            "injected_test_mode": config.injected_test_mode,
        },
        "config_path": str(CONFIG_PATH),
        "config_sha256": _sha256(CONFIG_PATH),
        "candidate_run_id": backfill_run_id,
        "actual_runner_receipt": {
            "path": str(actual_receipt),
            "sha256": _sha256(actual_receipt),
        },
        "raw_artifact": {
            "path": str(raw_artifact),
            "sha256": raw_verified.get("artifact_sha256"),
            "source_id": raw_verified.get("source_id"),
            "status": raw_verified.get("status"),
            "row_count": raw_verified.get("row_count"),
            "requested_rows": raw_verified.get("requested_rows"),
            "missing_symbols": raw_verified.get("missing_symbols"),
        },
        "selection_manifest": {
            "path": str(selection_manifest),
            "sha256": _sha256(selection_manifest),
            "artifact_sha256": selection_entry.get("artifact_sha256"),
            "selection_envelope_sha256": hashlib.sha256(
                json.dumps(selection_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "status": selection_envelope.get("selection_status"),
            "selected_rows": market_result.get("selected_rows"),
            "raw_artifact_sha256": selection_envelope.get("raw_artifact_sha256"),
        },
        "runner_lane_result": market_result,
        "runner_result": result,
        "provider_calls": 0,
        "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    _store_json(RUN_RECEIPT_PATH, output_receipt)
    passed = (
        market_result.get("selection_status") == "PARTIAL_WITH_ROWS"
        and market_result.get("selected_rows") == 10
        and raw_verified.get("source_id") == SOURCE_ID
        and raw_verified.get("status") == "PARTIAL_WITH_ROWS"
        and raw_verified.get("row_count") == 96
        and raw_verified.get("requested_rows") == 100
        and selection_envelope.get("selection_status") == "PARTIAL_WITH_ROWS"
        and len(selection_envelope.get("rows") or ()) == 10
        and selection_envelope.get("raw_artifact_sha256") == raw_verified.get("artifact_sha256")
        and selection_entry.get("artifact_sha256") == _sha256(selection_artifact)
        and all(output_receipt["safety"][flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    )
    print(json.dumps({
        "pass": passed,
        "run_receipt": str(RUN_RECEIPT_PATH),
        "runner_receipt": str(actual_receipt),
        "raw_artifact_sha256": raw_entry.get("artifact_sha256"),
        "selection_artifact_sha256": selection_entry.get("artifact_sha256"),
        "selection_status": market_result.get("selection_status"),
        "selected_rows": market_result.get("selected_rows"),
        "candidate_run_id": backfill_run_id,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
