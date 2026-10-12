#!/usr/bin/env python3
"""Build or explicitly publish the frozen after-fact HK Futu K_1M overlay.

Candidate-build mode reads verified SelectionStore runs and previously captured
K_1M rows without calling OpenD or writing the formal store. The separate
``--publish-reviewed-candidate`` path requires exact candidate, baseline, and
original-run hashes and uses the narrow SelectionStore compare-and-swap method.
``--canary-only`` exercises that same path on an isolated latest-pointer/run
clone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
R5_EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_AFTERNOON_AUTO_STAGES_20261012/futu/kline_enrichment_r5/writer"
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stage_center.consumer import StageSelectionConsumer  # noqa: E402
from stage_center.selection import SelectionStore, _stage_card_evidence  # noqa: E402
from upstreams.v3_shared_data.scripts.live_acquisition.contracts import (  # noqa: E402
    STAGE_WINDOWS,
)
from upstreams.v3_shared_data.scripts.live_acquisition.futu_minute import (  # noqa: E402
    aggregate_futu_minute_window_rows,
)


SCHEMA = "v4_hk_stage_futu_kline_enrichment_overlay_r5_v1"
TARGET_DATE = "20261012"
MARKET = "HK_CONNECT"
STAGE_IDS = ("STAGE_1300_1315", "STAGE_1445_1500")
STAGE_KEYS = {"STAGE_1300_1315": "1300", "STAGE_1445_1500": "1445"}
CARD_FIELDS = (
    "current_change_pct",
    "open_price",
    "last_price",
    "high_price",
    "low_price",
    "support",
    "pressure",
    "invalidation",
    "source_last_bar_time",
    "support_primary_price",
    "pressure_price",
    "invalidation_price",
)
REPLACED_CANNOT_CONFIRM = "FUTU_RT_DATA_OHLC_AND_ORDERBOOK_UNAVAILABLE"
ORDERBOOK_CANNOT_CONFIRM = "FUTU_ORDERBOOK_HISTORICAL_SNAPSHOT_UNAVAILABLE"
AFTERFACT_CANNOT_CONFIRM = "FUTU_KLINE_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT"
EXPECTED_RUN_IDS = {
    "STAGE_1300_1315": "run-bdede6a8a80bda3266e69e68",
    "STAGE_1445_1500": "run-504b199463282379e17b0cb4",
}


class EnrichmentError(ValueError):
    """Raised when frozen inputs or Futu evidence fail closed validation."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EnrichmentError(f"cannot read JSON evidence: {path}: {error}") from error


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise EnrichmentError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise EnrichmentError(f"{label} must be a finite number") from error
    if not math.isfinite(number):
        raise EnrichmentError(f"{label} must be a finite number")
    return number


def _expected_window_keys(trade_date: str, stage_id: str) -> tuple[list[str], str]:
    if stage_id not in STAGE_IDS or stage_id not in STAGE_WINDOWS:
        raise EnrichmentError(f"unsupported stage: {stage_id}")
    if len(trade_date) != 8 or not trade_date.isdigit():
        raise EnrichmentError(f"invalid trade date: {trade_date}")
    day = datetime.strptime(trade_date, "%Y%m%d")
    start_text, end_text, cutoff_text = STAGE_WINDOWS[stage_id]
    start = datetime.combine(day.date(), datetime.strptime(start_text, "%H:%M:%S").time())
    end = datetime.combine(day.date(), datetime.strptime(end_text, "%H:%M:%S").time())
    # This is the existing canonical Futu minute-window contract. In
    # particular, both afternoon stages begin at window_start + 1 minute.
    current = start.replace(second=0) + timedelta(minutes=1)
    keys: list[str] = []
    while current < end:
        keys.append(current.strftime("%Y-%m-%d %H:%M:%S"))
        current += timedelta(minutes=1)
    return keys, cutoff_text


def validate_provider_receipt(
    code: str,
    raw_path: Path,
    receipt_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
    receipt = read_json(receipt_path)
    if not isinstance(receipt, Mapping):
        raise EnrichmentError(f"provider receipt must be an object: {receipt_path}")
    if receipt.get("schema") not in {
        "v4_futu_kline_enrichment_r5_kline_canary_v1",
        "v4_futu_kline_enrichment_r5_kline_receipt_v1",
    }:
        raise EnrichmentError(f"unexpected provider receipt schema for {code}")
    if receipt.get("source_id") != "futu_openapi_get_cur_kline":
        raise EnrichmentError(f"provider source mismatch for {code}")
    if receipt.get("method") != "get_cur_kline(code,1000,SubType.K_1M,AuType.NONE)":
        raise EnrichmentError(f"provider K_1M method mismatch for {code}")
    if receipt.get("target_date") != TARGET_DATE or receipt.get("market") != MARKET:
        raise EnrichmentError(f"provider date/market mismatch for {code}")
    if receipt.get("code") != code or receipt.get("ret") != 0:
        raise EnrichmentError(f"provider code/ret mismatch for {code}")
    if receipt.get("pit_safe") is not False:
        raise EnrichmentError(f"provider PIT marker must remain false for {code}")
    if receipt.get("production_allowed") is not False or receipt.get("buy_gate_updated") is not False or receipt.get("orders_sent") is not False:
        raise EnrichmentError(f"provider safety marker mismatch for {code}")
    if receipt.get("selection_action_boundary") != "NO_BUY":
        raise EnrichmentError(f"provider action boundary mismatch for {code}")
    if receipt.get("sdk_time_key_timezone") != "Asia/Shanghai":
        raise EnrichmentError(f"provider time-key timezone missing for {code}")
    if receipt.get("formal_stage_eligibility") != "CANNOT_CONFIRM":
        raise EnrichmentError(f"provider formal eligibility marker mismatch for {code}")
    capture_start = receipt.get("captured_at_start_utc")
    capture_end = receipt.get("captured_at_end_utc")
    if not capture_start or not capture_end:
        raise EnrichmentError(f"provider capture timestamps missing for {code}")
    try:
        capture_start_dt = datetime.fromisoformat(str(capture_start))
        capture_end_dt = datetime.fromisoformat(str(capture_end))
    except ValueError as error:
        raise EnrichmentError(f"provider capture timestamp malformed for {code}") from error
    if capture_start_dt.tzinfo is None or capture_end_dt.tzinfo is None or capture_end_dt < capture_start_dt:
        raise EnrichmentError(f"provider capture timestamp order/timezone invalid for {code}")
    final_cutoff = datetime.combine(
        datetime.strptime(TARGET_DATE, "%Y%m%d").date(),
        datetime.strptime(STAGE_WINDOWS["STAGE_1445_1500"][2], "%H:%M:%S").time(),
        tzinfo=ZoneInfo("Asia/Hong_Kong"),
    ).astimezone(timezone.utc)
    if capture_start_dt.astimezone(timezone.utc) < final_cutoff:
        raise EnrichmentError(f"provider capture began before the final target cutoff for {code}")
    raw_sha = sha256_file(raw_path)
    if receipt.get("provider_raw_sha256") != raw_sha:
        raise EnrichmentError(f"provider raw SHA mismatch for {code}")
    declared_raw_path = receipt.get("provider_raw_path")
    if declared_raw_path and Path(str(declared_raw_path)).resolve() != raw_path.resolve():
        raise EnrichmentError(f"provider raw path mismatch for {code}")
    raw_payload = read_json(raw_path)
    if not isinstance(raw_payload, list) or not raw_payload:
        raise EnrichmentError(f"provider rows missing for {code}")
    if any(not isinstance(row, Mapping) for row in raw_payload):
        raise EnrichmentError(f"provider row must be an object for {code}")
    rows = [dict(row) for row in raw_payload]
    if any(str(row.get("code") or "").upper() != code for row in rows):
        raise EnrichmentError(f"provider row code mismatch for {code}")
    target_rows = [row for row in rows if str(row.get("time_key") or "").startswith("2026-10-12 ")]
    if not target_rows:
        raise EnrichmentError(f"provider returned no target-date rows for {code}")
    seen: set[str] = set()
    for row in target_rows:
        time_key = str(row.get("time_key") or "")
        try:
            parsed = datetime.strptime(time_key, "%Y-%m-%d %H:%M:%S")
        except ValueError as error:
            raise EnrichmentError(f"malformed Futu time_key for {code}: {time_key}") from error
        if parsed.strftime("%Y%m%d") != TARGET_DATE:
            raise EnrichmentError(f"wrong Futu date for {code}: {time_key}")
        if time_key in seen:
            raise EnrichmentError(f"duplicate Futu time_key for {code}: {time_key}")
        seen.add(time_key)
        for field in ("open", "high", "low", "close", "volume", "turnover"):
            _finite_number(row.get(field), label=f"{code}.{time_key}.{field}")
    return rows, dict(receipt), raw_sha, sha256_file(receipt_path)


def aggregate_code_window(
    *, trade_date: str, stage_id: str, code: str, raw_rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_keys, cutoff = _expected_window_keys(trade_date, stage_id)
    target_rows = [
        row
        for row in raw_rows
        if str(row.get("time_key") or "").startswith(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} ")
    ]
    target_by_time = {str(row.get("time_key")): row for row in target_rows}
    missing = [time_key for time_key in expected_keys if time_key not in target_by_time]
    if missing:
        raise EnrichmentError(f"incomplete canonical K_1M window for {code} {stage_id}: {missing}")
    selected = [target_by_time[time_key] for time_key in expected_keys]
    for row in selected:
        open_price = _finite_number(row.get("open"), label=f"{code}.{row['time_key']}.open")
        high_price = _finite_number(row.get("high"), label=f"{code}.{row['time_key']}.high")
        low_price = _finite_number(row.get("low"), label=f"{code}.{row['time_key']}.low")
        close_price = _finite_number(row.get("close"), label=f"{code}.{row['time_key']}.close")
        volume = _finite_number(row.get("volume"), label=f"{code}.{row['time_key']}.volume")
        _finite_number(row.get("turnover"), label=f"{code}.{row['time_key']}.turnover")
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price) or low_price > high_price or volume < 0:
            raise EnrichmentError(f"invalid OHLCV relation for {code} {row['time_key']}")
    aggregated = aggregate_futu_minute_window_rows(trade_date, stage_id, target_rows)
    matches = [row for row in aggregated if row.get("code") == code]
    if len(matches) != 1:
        raise EnrichmentError(f"canonical minute aggregator did not return exactly one row for {code} {stage_id}")
    summary = matches[0]
    last_expected = expected_keys[-1]
    if summary.get("bar_count") != len(expected_keys):
        raise EnrichmentError(f"canonical bar count mismatch for {code} {stage_id}")
    if summary.get("window_start") != expected_keys[0] or summary.get("window_end") != last_expected:
        raise EnrichmentError(f"canonical window boundary mismatch for {code} {stage_id}")
    if summary.get("temporal_cutoff_safe") is not True:
        raise EnrichmentError(f"canonical aggregator window check failed for {code} {stage_id}")
    # The aggregator's flag describes its clock-window filter only. This raw
    # data was collected after the target cutoff, so the candidate cannot be
    # promoted as PIT-safe.
    summary = dict(summary)
    summary["temporal_cutoff_safe"] = False
    summary["configured_cutoff"] = cutoff
    summary["expected_time_keys"] = expected_keys
    summary["vendor_bar_boundary_semantics"] = "CANNOT_CONFIRM_FROM_OFFICIAL_TIME_KEY_FIELD_DESCRIPTION"
    return summary, {
        "expected_bar_count": len(expected_keys),
        "present_bar_count": len(selected),
        "first_time_key": expected_keys[0],
        "last_time_key": expected_keys[-1],
        "configured_cutoff": cutoff,
        "canonical_window_contract": "window_start_plus_1_minute_le_time_key_lt_window_end",
        "window_contract_complete": True,
        "vendor_bar_boundary_semantics": "CANNOT_CONFIRM_FROM_OFFICIAL_TIME_KEY_FIELD_DESCRIPTION",
        "temporal_cutoff_safe": False,
    }


def enrich_stage_rows(
    envelope: Mapping[str, Any],
    summaries: Mapping[str, Mapping[str, Any]],
    *,
    kline_provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise EnrichmentError("source selection rows are missing")
    enriched_rows: list[dict[str, Any]] = []
    for row_value in rows:
        if not isinstance(row_value, Mapping):
            raise EnrichmentError("source selection row is not an object")
        row = dict(row_value)
        code = str(row.get("code") or "").upper()
        summary = summaries.get(code)
        if summary is None:
            raise EnrichmentError(f"no canonical K_1M summary for selected code {code}")
        card = _stage_card_evidence(
            row,
            code=code,
            open_price=summary.get("open_price"),
            last_price=summary.get("last_price"),
            high_price=summary.get("high_price"),
            low_price=summary.get("low_price"),
            source_last_bar_time=summary.get("update_time"),
            next_validation_time=row.get("next_validation_time"),
        )
        row.update({field: card[field] for field in CARD_FIELDS})
        enriched_rows.append(row)

    evidence = [str(item) for item in envelope.get("source_evidence") or []]
    stage_id = str(envelope.get("stage_id") or "")
    evidence.extend(
        [
            "futu_kline_enrichment=r5_display_only_afterfact",
            "futu_kline_source=futu_openapi_get_cur_kline",
            "futu_kline_adjustment=AuType.NONE",
            "futu_kline_time_key_timezone=Asia/Shanghai",
            "futu_kline_market_timezone=Asia/Hong_Kong",
            "futu_kline_window_contract=window_start_plus_1_minute_le_time_key_lt_window_end",
            f"futu_kline_vendor_bar_boundary_semantics=CANNOT_CONFIRM:{stage_id}",
            "futu_historical_orderbook=CANNOT_CONFIRM_NO_CUTOFF_BOUND_CACHE",
            AFTERFACT_CANNOT_CONFIRM,
        ]
    )
    for code, source in sorted(kline_provenance.items()):
        evidence.append(f"futu_kline_raw_sha256={code}:{source['raw_sha256']}")
        evidence.append(f"futu_kline_receipt_sha256={code}:{source['receipt_sha256']}")
    evidence = list(dict.fromkeys(evidence))

    cannot_confirm = [
        str(item)
        for item in envelope.get("cannot_confirm") or []
        if str(item) != REPLACED_CANNOT_CONFIRM
    ]
    cannot_confirm.extend(
        [
            "FUTU_RT_DATA_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT",
            "FUTU_RT_DATA_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
            "FUTU_RT_DATA_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
            ORDERBOOK_CANNOT_CONFIRM,
            AFTERFACT_CANNOT_CONFIRM,
        ]
    )
    return {
        "trade_date": envelope["trade_date"],
        "stage_id": stage_id,
        "market": envelope["market"],
        "source_selection_run_id": envelope["run_id"],
        "source_selection_artifact_id": envelope["artifact_id"],
        "source_selection_status": envelope["selection_status"],
        "source_status": envelope["source_status"],
        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
        "algorithm_id": envelope["algorithm_id"],
        "algorithm_sha256": envelope["algorithm_sha256"],
        "requested_rows": envelope["requested_rows"],
        "source_rows": envelope["source_rows"],
        "selected_rows": envelope["selected_rows"],
        "coverage_ratio": envelope["coverage_ratio"],
        "missing_symbols": list(envelope.get("missing_symbols") or []),
        "rows": enriched_rows,
        "source_evidence": evidence,
        "cannot_confirm": list(dict.fromkeys(cannot_confirm)),
        "selection_action_boundary": "NO_BUY",
        "research_only": True,
        "formal_stage_eligibility": "CANNOT_CONFIRM",
        "pit_safe": False,
        "temporal_cutoff_safe": False,
        "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
        "current_orderbook_queried": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _evidence_values(evidence: Sequence[Any], key: str) -> list[str]:
    prefix = f"{key}="
    return [str(item)[len(prefix) :] for item in evidence if str(item).startswith(prefix)]


def _single_evidence_value(evidence: Sequence[Any], key: str, *, label: str) -> str:
    values = list(dict.fromkeys(_evidence_values(evidence, key)))
    if len(values) != 1 or not values[0]:
        raise EnrichmentError(f"{label} must contain exactly one {key} value")
    return values[0]


def d1_pool_lineage(envelope: Mapping[str, Any]) -> dict[str, str]:
    """Extract the existing D-1 pool hashes separately from the stage raw SHA."""
    rows = envelope.get("rows") or []
    if not rows:
        raise EnrichmentError("selection envelope has no rows for D-1 pool lineage")
    source_hashes = {
        _single_evidence_value(
            row.get("d1_source_evidence") or [],
            "hk_d1_source_sha256",
            label="selected row D-1 evidence",
        )
        for row in rows
    }
    pool_versions = {
        _single_evidence_value(
            row.get("d1_source_evidence") or [],
            "hk_d1_pool_version",
            label="selected row D-1 evidence",
        )
        for row in rows
    }
    if len(source_hashes) != 1 or len(pool_versions) != 1:
        raise EnrichmentError("selected rows disagree on fixed D-1 pool lineage")
    pool_artifact_sha = _single_evidence_value(
        envelope.get("source_evidence") or [],
        "hk_d1_json_sha256",
        label="selection envelope source evidence",
    )
    return {
        "pool_version": next(iter(pool_versions)),
        "pool_source_sha256": next(iter(source_hashes)),
        "pool_artifact_sha256": pool_artifact_sha,
    }


def _baseline_file_map(baseline: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = baseline.get("files")
    if not isinstance(records, list):
        raise EnrichmentError("frozen input baseline files are missing")
    result: dict[str, Mapping[str, Any]] = {}
    for item in records:
        if isinstance(item, Mapping) and item.get("label"):
            result[str(item["label"])] = item
    return result


def verify_frozen_inputs(
    baseline: Mapping[str, Any],
    *,
    selection_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    if baseline.get("schema") != "v4_futu_kline_enrichment_r5_input_baseline_v1":
        raise EnrichmentError("input baseline schema mismatch")
    if baseline.get("target_date") != TARGET_DATE or baseline.get("market") != MARKET:
        raise EnrichmentError("input baseline date/market mismatch")
    if baseline.get("target_code_count") != 11:
        raise EnrichmentError("input baseline target-code count must be 11")
    codes = baseline.get("target_code_union")
    if not isinstance(codes, list) or len(codes) != 11 or len(set(codes)) != 11:
        raise EnrichmentError("input baseline target-code union mismatch")
    for collection in (baseline.get("files") or [], baseline.get("r4_datasets") or []):
        if not isinstance(collection, list):
            raise EnrichmentError("frozen input manifest is malformed")
        for record in collection:
            if not isinstance(record, Mapping):
                raise EnrichmentError("frozen input entry is malformed")
            path = Path(str(record.get("path") or ""))
            if not path.is_file() or sha256_file(path) != record.get("sha256"):
                raise EnrichmentError(f"frozen input SHA mismatch: {record.get('label')}")

    file_map = _baseline_file_map(baseline)
    unchanged = baseline.get("unchanged_scope_sha")
    if not isinstance(unchanged, Mapping):
        raise EnrichmentError("unchanged A/1555 source SHA manifest is missing")
    unchanged_labels = {
        "a1300_raw": "a1300_raw_artifact.csv",
        "a1445_raw": "a1445_raw_artifact.csv",
        "hk1555_raw": "hk1555_raw_artifact.csv",
        "hk1555_selection": "hk1555_selection_artifact.csv",
    }
    for scope_key, label in unchanged_labels.items():
        record = file_map.get(label)
        if not record or unchanged.get(scope_key) != record.get("sha256"):
            raise EnrichmentError(f"unchanged-scope SHA cross-reference mismatch for {scope_key}")
    store = SelectionStore(selection_root)
    envelopes: dict[str, dict[str, Any]] = {}
    for stage_id in STAGE_IDS:
        key = STAGE_KEYS[stage_id]
        source = baseline.get("selection", {}).get(key)
        if not isinstance(source, Mapping):
            raise EnrichmentError(f"frozen source selection is missing for {stage_id}")
        if source.get("run_id") != EXPECTED_RUN_IDS[stage_id]:
            raise EnrichmentError(f"frozen source run identity mismatch for {stage_id}")
        envelope = store.read_verified(TARGET_DATE, stage_id, MARKET)
        if envelope.get("run_id") != source.get("run_id"):
            raise EnrichmentError(f"SelectionStore latest run differs from frozen run for {stage_id}")
        raw_artifact_record = file_map.get(f"hk{key}_raw_artifact.csv")
        if not raw_artifact_record or envelope.get("raw_artifact_sha256") != raw_artifact_record.get("sha256"):
            raise EnrichmentError(f"SelectionStore raw artifact binding mismatch for {stage_id}")
        if envelope.get("requested_rows") != 100 or envelope.get("source_rows") != 100:
            raise EnrichmentError(f"SelectionStore must retain the full 100-row input for {stage_id}")
        if envelope.get("selected_rows") != 10 or len(envelope.get("rows") or []) != 10:
            raise EnrichmentError(f"frozen selected-row count mismatch for {stage_id}")
        codes_expected = source.get("codes")
        codes_actual = [str(row.get("code") or "").upper() for row in envelope.get("rows") or []]
        if codes_actual != codes_expected:
            raise EnrichmentError(f"source selection order/codes changed for {stage_id}")
        if any(row.get("action_level") != "NO_BUY" for row in envelope.get("rows") or []):
            raise EnrichmentError(f"source selection action boundary changed for {stage_id}")
        artifact_label = f"hk{key}_selection_artifact.csv"
        manifest_label = f"hk{key}_selection_manifest.json"
        receipt_label = f"hk{key}_selection_receipt.json"
        expected_artifact = file_map.get(artifact_label)
        expected_manifest = file_map.get(manifest_label)
        expected_receipt = file_map.get(receipt_label)
        if not all((expected_artifact, expected_manifest, expected_receipt)):
            raise EnrichmentError(f"baseline selection triplet missing for {stage_id}")
        if expected_artifact.get("sha256") != source.get("selection_sha256"):
            raise EnrichmentError(f"baseline artifact SHA cross-reference mismatch for {stage_id}")
        actual_artifact = Path(str(expected_artifact.get("path")))
        actual_manifest = Path(str(expected_manifest.get("path")))
        actual_receipt = Path(str(expected_receipt.get("path")))
        for path, record in ((actual_artifact, expected_artifact), (actual_manifest, expected_manifest), (actual_receipt, expected_receipt)):
            if not path.is_file() or sha256_file(path) != record.get("sha256"):
                raise EnrichmentError(f"frozen selection source SHA mismatch: {path}")
            try:
                path.resolve().relative_to(selection_root.resolve())
            except ValueError as error:
                raise EnrichmentError(f"frozen selection source is outside supplied store: {path}") from error
        envelopes[stage_id] = dict(envelope)
    return envelopes, {label: dict(item) for label, item in file_map.items()}


def expected_original_identities_from_baseline(
    baseline: Mapping[str, Any],
    *,
    envelopes: Mapping[str, Mapping[str, Any]],
    selection_root: Path,
) -> dict[str, dict[str, str]]:
    file_map = _baseline_file_map(baseline)
    store = SelectionStore(selection_root)
    identities: dict[str, dict[str, str]] = {}
    for stage_id in STAGE_IDS:
        stage_key = STAGE_KEYS[stage_id]
        prefix = f"hk{stage_key}_"
        envelope = envelopes[stage_id]
        records = {
            field: file_map.get(f"{prefix}selection_{suffix}.json" if suffix in ("manifest", "receipt") else f"{prefix}selection_artifact.csv")
            for field, suffix in (
                ("artifact_sha256", "artifact"),
                ("manifest_sha256", "manifest"),
                ("receipt_sha256", "receipt"),
            )
        }
        raw_record = file_map.get(f"{prefix}raw_artifact.csv")
        if not raw_record or not all(records.values()):
            raise EnrichmentError(f"frozen original selection identity is incomplete for {stage_id}")
        identity = {
            "run_id": str(envelope.get("run_id") or ""),
            "artifact_id": str(envelope.get("artifact_id") or ""),
            "artifact_sha256": str(records["artifact_sha256"].get("sha256") or ""),
            "manifest_file_sha256": str(records["manifest_sha256"].get("sha256") or ""),
            "receipt_file_sha256": str(records["receipt_sha256"].get("sha256") or ""),
            "raw_artifact_sha256": str(raw_record.get("sha256") or ""),
            "algorithm_sha256": str(envelope.get("algorithm_sha256") or ""),
        }
        verified = store._verify_run(TARGET_DATE, stage_id, MARKET, identity["run_id"])
        identity["manifest_sha256"] = str(verified.get("manifest_sha256") or "")
        identity["receipt_sha256"] = str(verified.get("receipt_sha256") or "")
        if (
            identity["run_id"] != EXPECTED_RUN_IDS[stage_id]
            or envelope.get("raw_artifact_sha256") != identity["raw_artifact_sha256"]
            or verified.get("artifact_sha256") != identity["artifact_sha256"]
        ):
            raise EnrichmentError(f"frozen original selection identity changed for {stage_id}")
        identities[stage_id] = identity
    return identities


def _selection_root_from_baseline(baseline: Mapping[str, Any]) -> Path:
    file_map = _baseline_file_map(baseline)
    record = file_map.get("hk1300_selection_manifest.json")
    if not record:
        raise EnrichmentError("baseline has no original HK 1300 selection manifest")
    path = Path(str(record.get("path") or "")).resolve()
    if len(path.parents) < 5:
        raise EnrichmentError("baseline original selection manifest path is malformed")
    return path.parents[4]


def _copy_selection_store_canary(
    source_root: Path,
    canary_store_root: Path,
    *,
    expected_originals_by_stage: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    source_store = SelectionStore(source_root)
    if canary_store_root.exists() or canary_store_root.is_symlink():
        raise EnrichmentError(f"refusing to reuse isolated publication canary path: {canary_store_root}")
    latest_bytes = source_store.latest_path.read_bytes()
    latest = json.loads(latest_bytes)
    if latest.get("schema_version") != "stage_center.selection.latest.v1" or latest.get("owner") != "stage_center":
        raise EnrichmentError("source selection latest pointer schema/owner mismatch")
    canary_store_root.mkdir(parents=True, exist_ok=False)
    _write_new_file(canary_store_root / "selection_latest.json", latest_bytes)
    copied_runs: dict[str, str] = {}
    for stage_id in STAGE_IDS:
        expected = expected_originals_by_stage[stage_id]
        role = source_store._role(stage_id, MARKET)
        source_run = source_store.runs_root / TARGET_DATE / role / expected["run_id"]
        try:
            source_run.resolve().relative_to(source_store.root.resolve())
        except ValueError as error:
            raise EnrichmentError(f"source run path escapes SelectionStore for {stage_id}") from error
        if source_run.is_symlink() or not source_run.is_dir():
            raise EnrichmentError(f"source immutable selection run is missing for {stage_id}")
        for name in ("artifact.csv", "manifest.json", "receipt.json"):
            path = source_run / name
            if path.is_symlink() or not path.is_file():
                raise EnrichmentError(f"source immutable selection run trio is incomplete for {stage_id}")
        destination_run = canary_store_root / "selection_runs" / TARGET_DATE / role / expected["run_id"]
        destination_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_run, destination_run, symlinks=False)
        copied_runs[stage_id] = expected["run_id"]
    if source_store.latest_path.read_bytes() != latest_bytes:
        raise EnrichmentError("source selection latest changed while the canary copy was created")
    canary_store = SelectionStore(canary_store_root)
    for stage_id in STAGE_IDS:
        verified = canary_store._verify_run(
            TARGET_DATE,
            stage_id,
            MARKET,
            str(expected_originals_by_stage[stage_id]["run_id"]),
        )
        expected = expected_originals_by_stage[stage_id]
        if (
            verified.get("run_id") != expected["run_id"]
            or verified["envelope"].get("artifact_id") != expected["artifact_id"]
            or any(
                verified.get(field) != expected[field]
                for field in ("artifact_sha256", "manifest_sha256", "receipt_sha256")
            )
        ):
            raise EnrichmentError(f"canary source trio SHA mismatch for {stage_id}")
    return {
        "source_latest_sha256": sha256_bytes(latest_bytes),
        "copied_original_runs": copied_runs,
        "canary_selection_root": str(canary_store_root),
    }


def publish_reviewed_candidate(
    *,
    selection_root: Path,
    input_baseline_path: Path,
    expected_input_baseline_sha256: str,
    reviewed_candidate_path: Path,
    expected_candidate_sha256: str,
    expected_originals_by_stage: Mapping[str, Mapping[str, str]],
    canary_output_root: Path | None = None,
) -> dict[str, Any]:
    """CAS-publish the explicit reviewed R5 candidate, optionally to a clone."""
    baseline_sha = sha256_file(input_baseline_path)
    if baseline_sha != expected_input_baseline_sha256:
        raise EnrichmentError("input baseline SHA does not match the frozen expected SHA")
    baseline = read_json(input_baseline_path)
    if not isinstance(baseline, Mapping):
        raise EnrichmentError("input baseline must be a JSON object")
    if str(baseline.get("_input_baseline_sha256") or baseline_sha) != baseline_sha:
        raise EnrichmentError("input baseline identity mismatch")
    baseline = dict(baseline)
    baseline["_input_baseline_sha256"] = baseline_sha
    canonical_selection_root = _selection_root_from_baseline(baseline)
    if selection_root.resolve() != canonical_selection_root:
        raise EnrichmentError("selection root does not match the frozen original SelectionStore")
    original_envelopes, _file_map = verify_frozen_inputs(
        baseline,
        selection_root=canonical_selection_root,
    )
    frozen_originals = expected_original_identities_from_baseline(
        baseline,
        envelopes=original_envelopes,
        selection_root=canonical_selection_root,
    )
    if dict(expected_originals_by_stage) != frozen_originals:
        raise EnrichmentError("explicit expected original identities differ from the frozen baseline")
    candidate_bytes = reviewed_candidate_path.read_bytes()
    candidate_sha = sha256_bytes(candidate_bytes)
    if candidate_sha != expected_candidate_sha256:
        raise EnrichmentError("reviewed candidate SHA does not match the explicit expected SHA")

    canary_copy: dict[str, Any] | None = None
    if canary_output_root is not None:
        canary_parent = (R5_EVIDENCE_ROOT / "publication_canaries").resolve()
        try:
            canary_output_root.resolve().relative_to(canary_parent)
        except ValueError as error:
            raise EnrichmentError("publication canary output must remain under the R5 publication_canaries directory") from error
        if canary_output_root.exists() or canary_output_root.is_symlink():
            raise EnrichmentError(f"refusing to overwrite publication canary evidence: {canary_output_root}")
        canary_output_root.mkdir(parents=True, exist_ok=False)
        target_store_root = canary_output_root / "selection"
        canary_copy = _copy_selection_store_canary(
            canonical_selection_root,
            target_store_root,
            expected_originals_by_stage=frozen_originals,
        )
    else:
        target_store_root = canonical_selection_root

    target_store = SelectionStore(target_store_root)
    before_latest = target_store._latest()
    result = target_store.publish_hk_futu_kline_enrichment_pair(
        candidate_bytes,
        expected_candidate_sha256=expected_candidate_sha256,
        expected_input_baseline_sha256=baseline_sha,
        expected_originals_by_stage=frozen_originals,
    )
    after_latest = target_store._latest()
    target_keys = {
        target_store._key(TARGET_DATE, stage_id, MARKET)
        for stage_id in STAGE_IDS
    }
    before_entries = before_latest.get("entries") or {}
    after_entries = after_latest.get("entries") or {}
    if {
        key: value for key, value in before_entries.items() if key not in target_keys
    } != {
        key: value for key, value in after_entries.items() if key not in target_keys
    }:
        raise EnrichmentError("publication changed a latest entry outside the two frozen HK stages")

    candidate = json.loads(candidate_bytes.decode("utf-8"))
    consumer_readback = {}
    consumer = StageSelectionConsumer(target_store_root)
    for stage_id in STAGE_IDS:
        response = consumer.get(TARGET_DATE, stage_id, markets=(MARKET,))
        lane = response.get("markets", {}).get(MARKET)
        stage_candidate = candidate["stages"][stage_id]
        expected_rows = stage_candidate.get("rows") or []
        if (
            not isinstance(lane, Mapping)
            or lane.get("selected_rows") != 10
            or len(lane.get("rows") or []) != 10
            or lane.get("run_id") != result["stage_publications"][stage_id]["run_id"]
            or [str(row.get("code") or "").upper() for row in lane["rows"]]
            != [str(row.get("code") or "").upper() for row in expected_rows]
        ):
            raise EnrichmentError(f"existing StageSelectionConsumer did not read back the published {stage_id} rows")
        for actual_row, expected_row in zip(lane["rows"], expected_rows):
            for field in ("current_change_pct", "support", "pressure", "invalidation"):
                if actual_row.get(field) != expected_row.get(field):
                    raise EnrichmentError(f"existing StageSelectionConsumer readback mismatch: {stage_id}/{field}")
            if actual_row.get("action_level") != "NO_BUY":
                raise EnrichmentError(f"existing StageSelectionConsumer changed the {stage_id} NO_BUY boundary")
        consumer_readback[stage_id] = {
            "run_id": lane.get("run_id"),
            "selected_rows": lane.get("selected_rows"),
            "codes": [str(row.get("code") or "").upper() for row in lane["rows"]],
            "four_card_fields_read": ["current_change_pct", "support", "pressure", "invalidation"],
            "candidate_formal_stage_eligibility": stage_candidate.get("formal_stage_eligibility"),
            "candidate_pit_safe": stage_candidate.get("pit_safe"),
            "candidate_temporal_cutoff_safe": stage_candidate.get("temporal_cutoff_safe"),
            "candidate_selection_action_boundary": stage_candidate.get("selection_action_boundary"),
        }
    for stage_id in STAGE_IDS:
        old_run_id = frozen_originals[stage_id]["run_id"]
        old_verified = target_store._verify_run(TARGET_DATE, stage_id, MARKET, old_run_id)
        if (
            old_verified.get("run_id") != frozen_originals[stage_id]["run_id"]
            or old_verified["envelope"].get("artifact_id") != frozen_originals[stage_id]["artifact_id"]
            or any(
                old_verified.get(field) != frozen_originals[stage_id][field]
                for field in ("artifact_sha256", "manifest_sha256", "receipt_sha256")
            )
        ):
            raise EnrichmentError(f"publication did not preserve the previous immutable run for {stage_id}")
    for record in [*(baseline.get("files") or []), *(baseline.get("r4_datasets") or [])]:
        path = Path(str(record.get("path") or ""))
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise EnrichmentError(f"publication changed a frozen source artifact: {record.get('label')}")

    result.update(
        {
            "publication_mode": "ISOLATED_CANARY" if canary_output_root is not None else "CANONICAL_CAS_AFTER_REVIEW",
            "selection_root": str(target_store_root),
            "latest_entries_outside_target_pair_unchanged": True,
            "old_immutable_runs_preserved": True,
            "frozen_inputs_unchanged": True,
            "canary_copy": canary_copy,
            "consumer_readback": consumer_readback,
        }
    )
    if canary_output_root is not None:
        receipt_path = canary_output_root / "publication_receipt.json"
        _write_new_file(receipt_path, canonical_json_bytes(result))
        result["publication_receipt_path"] = str(receipt_path)
        result["publication_receipt_sha256"] = sha256_file(receipt_path)
    return result


def load_provider_universe(
    provider_root: Path,
    codes: Sequence[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_files = sorted(provider_root.glob("*/get_cur_kline_1000_none.json"))
    candidate_by_code: dict[str, list[Path]] = {code: [] for code in codes}
    for raw_path in raw_files:
        receipt_path = raw_path.parent / "receipt.json"
        if not receipt_path.is_file():
            continue
        receipt = read_json(receipt_path)
        code = str(receipt.get("code") or "").upper() if isinstance(receipt, Mapping) else ""
        if code in candidate_by_code:
            candidate_by_code[code].append(raw_path)
    raw_by_code: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for code in codes:
        matches = candidate_by_code.get(code, [])
        if len(matches) != 1:
            raise EnrichmentError(f"expected one immutable provider raw file for {code}, found {len(matches)}")
        raw_path = matches[0]
        receipt_path = raw_path.parent / "receipt.json"
        rows, receipt, raw_sha, receipt_sha = validate_provider_receipt(code, raw_path, receipt_path)
        raw_by_code[code] = rows
        provenance[code] = {
            "raw_sha256": raw_sha,
            "receipt_sha256": receipt_sha,
            "captured_at_start_utc": receipt["captured_at_start_utc"],
            "captured_at_end_utc": receipt["captured_at_end_utc"],
            "target_date_bar_count": receipt.get("target_date_bar_count"),
            "capture_after_target_cutoff": True,
        }
        receipts[code] = receipt
    return raw_by_code, provenance, receipts


def build_overlay(
    *,
    baseline: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
    raw_by_code: Mapping[str, list[dict[str, Any]]],
    kline_provenance: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    stages: dict[str, Any] = {}
    stage_receipts: dict[str, Any] = {}
    for stage_id in STAGE_IDS:
        envelope = envelopes[stage_id]
        rows = envelope.get("rows") or []
        summaries: dict[str, Mapping[str, Any]] = {}
        code_summaries: dict[str, Any] = {}
        for source_row in rows:
            code = str(source_row.get("code") or "").upper()
            if code not in raw_by_code:
                raise EnrichmentError(f"missing provider raw for selected code {code}")
            summary, coverage = aggregate_code_window(
                trade_date=TARGET_DATE,
                stage_id=stage_id,
                code=code,
                raw_rows=raw_by_code[code],
            )
            summaries[code] = summary
            code_summaries[code] = {
                "provider_raw_sha256": kline_provenance[code]["raw_sha256"],
                "provider_receipt_sha256": kline_provenance[code]["receipt_sha256"],
                "provider_capture_start_utc": kline_provenance[code]["captured_at_start_utc"],
                "provider_capture_end_utc": kline_provenance[code]["captured_at_end_utc"],
                "provider_capture_after_target_cutoff": kline_provenance[code]["capture_after_target_cutoff"],
                "provider_target_date_bar_count": kline_provenance[code]["target_date_bar_count"],
                "bar_count": summary["bar_count"],
                "window_start": summary["window_start"],
                "window_end": summary["window_end"],
                "configured_cutoff": summary["configured_cutoff"],
                "window_contract_complete": coverage["window_contract_complete"],
                "vendor_bar_boundary_semantics": coverage["vendor_bar_boundary_semantics"],
                "temporal_cutoff_safe": False,
            }
        stage = enrich_stage_rows(envelope, summaries, kline_provenance=kline_provenance)
        source_item = baseline["selection"][STAGE_KEYS[stage_id]]
        stage["source_selection_artifact_sha256"] = source_item["selection_sha256"]
        stage["source_selection_manifest_sha256"] = next(
            item["sha256"]
            for item in baseline["files"]
            if item.get("label") == f"hk{STAGE_KEYS[stage_id]}_selection_manifest.json"
        )
        stage["source_selection_receipt_sha256"] = next(
            item["sha256"]
            for item in baseline["files"]
            if item.get("label") == f"hk{STAGE_KEYS[stage_id]}_selection_receipt.json"
        )
        stages[stage_id] = stage
        stage_receipts[stage_id] = {
            "source_selection_run_id": envelope["run_id"],
            "requested_rows": envelope["requested_rows"],
            "source_rows": envelope["source_rows"],
            "selected_rows": envelope["selected_rows"],
            "unchanged_order_codes": [str(row.get("code")) for row in rows],
            "canonical_window_contract": "window_start_plus_1_minute_le_time_key_lt_window_end",
            "effective_window_bar_counts": sorted({item["bar_count"] for item in code_summaries.values()}),
            "effective_window_start_times": sorted({item["window_start"] for item in code_summaries.values()}),
            "effective_window_end_times": sorted({item["window_end"] for item in code_summaries.values()}),
            "configured_cutoff": STAGE_WINDOWS[stage_id][2],
            "excluded_from_1445_contract": ["2026-10-12 14:45:00"] if stage_id == "STAGE_1445_1500" else [],
            "codes": code_summaries,
            "vendor_bar_boundary_semantics": "CANNOT_CONFIRM_FROM_OFFICIAL_TIME_KEY_FIELD_DESCRIPTION",
            "temporal_cutoff_safe": False,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
            "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
            "selection_action_boundary": "NO_BUY",
        }

    union = baseline["target_code_union"]
    d1_lineage = {stage_id: d1_pool_lineage(envelopes[stage_id]) for stage_id in STAGE_IDS}
    artifact = {
        "schema": SCHEMA,
        "candidate_status": "REVIEW_REQUIRED_NOT_FORMALLY_PUBLISHED",
        "candidate_kind": "DISPLAY_EVIDENCE_OVERLAY_ONLY",
        "trade_date": TARGET_DATE,
        "market": MARKET,
        "source": {
            "selection_store_root": str(baseline["raw_and_selection_files"][0]["path"]).split("/selection_runs/")[0],
            "input_baseline_sha256": baseline.get("_input_baseline_sha256"),
            "fixed_d1_pool_row_count": 100,
            "unchanged_scope_sha256": baseline.get("unchanged_scope_sha"),
            "fixed_d1_pool_source_sha256_by_stage": {
                stage_id: d1_lineage[stage_id]["pool_source_sha256"] for stage_id in STAGE_IDS
            },
            "fixed_d1_pool_artifact_sha256_by_stage": {
                stage_id: d1_lineage[stage_id]["pool_artifact_sha256"] for stage_id in STAGE_IDS
            },
            "fixed_d1_pool_version_by_stage": {
                stage_id: d1_lineage[stage_id]["pool_version"] for stage_id in STAGE_IDS
            },
            "stage_raw_artifact_sha256_by_stage": {
                stage_id: envelopes[stage_id]["raw_artifact_sha256"] for stage_id in STAGE_IDS
            },
            "target_code_union": union,
            "target_code_count": len(union),
            "selection_run_ids": {
                stage_id: envelopes[stage_id]["run_id"] for stage_id in STAGE_IDS
            },
            "selection_artifact_sha256_by_stage": {
                stage_id: stages[stage_id]["source_selection_artifact_sha256"]
                for stage_id in STAGE_IDS
            },
        },
        "provenance": {
            "source_id": "futu_openapi_get_cur_kline",
            "method": "get_cur_kline(code,1000,SubType.K_1M,AuType.NONE)",
            "price_adjustment": "AuType.NONE",
            "market_timezone": "Asia/Hong_Kong",
            "sdk_time_key_timezone": "Asia/Shanghai",
            "vendor_time_key_field_description": "Futu documents time_key as K-line time in yyyy-MM-dd HH:mm:ss; HK uses Beijing time",
            "vendor_bar_boundary_semantics": "CANNOT_CONFIRM_FROM_OFFICIAL_TIME_KEY_FIELD_DESCRIPTION",
            "provider_raw_sha256_by_code": {
                code: kline_provenance[code]["raw_sha256"] for code in union
            },
            "provider_receipt_sha256_by_code": {
                code: kline_provenance[code]["receipt_sha256"] for code in union
            },
            "provider_capture_start_utc_by_code": {
                code: kline_provenance[code]["captured_at_start_utc"] for code in union
            },
            "provider_capture_end_utc_by_code": {
                code: kline_provenance[code]["captured_at_end_utc"] for code in union
            },
            "provider_target_date_bar_count_by_code": {
                code: kline_provenance[code]["target_date_bar_count"] for code in union
            },
            "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
            "current_orderbook_queried": False,
            "provider_subscription_release_receipt_status": "CANNOT_CONFIRM",
            "provider_subscription_release_receipt_note": (
                "The provider run did not write a formal unsubscribe/context-close receipt."
            ),
        },
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "selection_action_boundary": "NO_BUY",
            "pit_safe": False,
            "temporal_cutoff_safe": False,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
        },
        "stages": stages,
    }
    receipt = {
        "schema": "v4_hk_stage_futu_kline_enrichment_receipt_r5_v1",
        "candidate_status": "REVIEW_REQUIRED_NOT_FORMALLY_PUBLISHED",
        "trade_date": TARGET_DATE,
        "market": MARKET,
        "input_baseline_sha256": baseline.get("_input_baseline_sha256"),
        "target_code_union_sha256": sha256_bytes(canonical_json_bytes(union)),
        "target_code_count": len(union),
        "stage_receipts": stage_receipts,
        "unchanged_scope_sha256": baseline.get("unchanged_scope_sha"),
        "provider_receipt_stage_checks_used_for_aggregation": False,
        "aggregation_contract_note": "Provider receipts contain acquisition coverage checks; K_1M aggregation was independently re-applied with the canonical window_start+1 minute filter.",
        "safety": artifact["safety"],
        "formal_store_write_performed": False,
        "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
        "current_orderbook_queried": False,
        "provider_subscription_release_receipt_status": "CANNOT_CONFIRM",
        "provider_subscription_release_receipt_note": (
            "The provider run did not write a formal unsubscribe/context-close receipt."
        ),
    }
    return artifact, receipt


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise EnrichmentError(f"refusing to overwrite candidate evidence: {path}") from error


def run(
    *,
    selection_root: Path,
    input_baseline_path: Path,
    expected_input_baseline_sha256: str,
    provider_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    baseline_sha = sha256_file(input_baseline_path)
    if baseline_sha != expected_input_baseline_sha256:
        raise EnrichmentError("input baseline SHA does not match the frozen expected SHA")
    baseline = read_json(input_baseline_path)
    if not isinstance(baseline, Mapping):
        raise EnrichmentError("input baseline must be a JSON object")
    baseline = dict(baseline)
    baseline["_input_baseline_sha256"] = baseline_sha
    envelopes, _file_map = verify_frozen_inputs(baseline, selection_root=selection_root)
    code_union = list(baseline["target_code_union"])
    raw_by_code, provenance, _receipts = load_provider_universe(provider_root, code_union)
    artifact, receipt = build_overlay(
        baseline=baseline,
        envelopes=envelopes,
        raw_by_code=raw_by_code,
        kline_provenance=provenance,
    )
    output_root = output_dir.resolve()
    try:
        output_root.relative_to((R5_EVIDENCE_ROOT / "candidates").resolve())
    except ValueError as error:
        raise EnrichmentError("candidate output must remain under the R5 writer candidates directory") from error
    artifact_path = output_root / "candidate_overlay.json"
    artifact_bytes = canonical_json_bytes(artifact)
    _write_new_file(artifact_path, artifact_bytes)
    receipt["candidate_artifact_path"] = str(artifact_path)
    receipt["candidate_artifact_sha256"] = sha256_bytes(artifact_bytes)
    receipt["candidate_artifact_bytes"] = len(artifact_bytes)
    receipt["candidate_receipt_path"] = str(output_root / "receipt.json")
    receipt_bytes = canonical_json_bytes(receipt)
    _write_new_file(output_root / "receipt.json", receipt_bytes)
    return {
        "candidate_artifact_path": str(artifact_path),
        "candidate_artifact_sha256": sha256_bytes(artifact_bytes),
        "candidate_receipt_path": str(output_root / "receipt.json"),
        "candidate_receipt_sha256": sha256_bytes(receipt_bytes),
        "candidate_status": artifact["candidate_status"],
        "stage_ids": list(STAGE_IDS),
        "selected_rows_by_stage": {stage: len(artifact["stages"][stage]["rows"]) for stage in STAGE_IDS},
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-root", required=True, type=Path)
    parser.add_argument("--input-baseline", required=True, type=Path)
    parser.add_argument("--expected-input-baseline-sha256", required=True)
    parser.add_argument("--provider-root", type=Path, help="Required only when building a new candidate.")
    parser.add_argument("--output-dir", type=Path, help="Required only when building a new candidate.")
    parser.add_argument(
        "--publish-reviewed-candidate",
        action="store_true",
        help="Explicitly CAS-publish the frozen reviewed R5 candidate into SelectionStore.",
    )
    parser.add_argument("--reviewed-candidate", type=Path)
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument("--expected-original-identities-json")
    parser.add_argument(
        "--canary-only",
        action="store_true",
        help="Copy the full latest pointer and both original run trios, then publish/read only the isolated clone.",
    )
    parser.add_argument("--canary-output-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.publish_reviewed_candidate:
            if not all(
                (
                    args.reviewed_candidate,
                    args.expected_candidate_sha256,
                    args.expected_original_identities_json,
                )
            ):
                raise EnrichmentError(
                    "reviewed publication requires candidate path/SHA and explicit original identities"
                )
            if args.provider_root is not None or args.output_dir is not None:
                raise EnrichmentError("provider/output build arguments are invalid in reviewed publication mode")
            if args.canary_only != (args.canary_output_root is not None):
                raise EnrichmentError("--canary-only and --canary-output-root must be supplied together")
            try:
                expected_originals = json.loads(args.expected_original_identities_json)
            except json.JSONDecodeError as error:
                raise EnrichmentError("expected original identities must be valid JSON") from error
            if not isinstance(expected_originals, Mapping):
                raise EnrichmentError("expected original identities must be a JSON object")
            result = publish_reviewed_candidate(
                selection_root=args.selection_root,
                input_baseline_path=args.input_baseline,
                expected_input_baseline_sha256=args.expected_input_baseline_sha256,
                reviewed_candidate_path=args.reviewed_candidate,
                expected_candidate_sha256=args.expected_candidate_sha256,
                expected_originals_by_stage=expected_originals,
                canary_output_root=args.canary_output_root if args.canary_only else None,
            )
        else:
            if any(
                (
                    args.reviewed_candidate,
                    args.expected_candidate_sha256,
                    args.expected_original_identities_json,
                    args.canary_only,
                    args.canary_output_root,
                )
            ):
                raise EnrichmentError("reviewed-candidate arguments require --publish-reviewed-candidate")
            if args.provider_root is None or args.output_dir is None:
                raise EnrichmentError("candidate build requires --provider-root and --output-dir")
            result = run(
                selection_root=args.selection_root,
                input_baseline_path=args.input_baseline,
                expected_input_baseline_sha256=args.expected_input_baseline_sha256,
                provider_root=args.provider_root,
                output_dir=args.output_dir,
            )
    except EnrichmentError as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
