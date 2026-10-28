"""stage_center.live_collectors: hk_minute (review candidate, not deployment)."""
from __future__ import annotations
from typing import Any, Mapping
import hashlib
import json
import os
from pathlib import Path
from ._namespace import read_global as _v4_global


_FUTU_AFTERFACT_DATASET_PROFILES = {
    "STAGE_1300_1315": {
        "dataset_sha256": "63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0",
        "window": "13:00-13:15",
        "cutoff": "13:15:00",
        "observed_times": tuple(f"2026-10-12 13:{minute:02d}:00" for minute in range(1, 15)),
    },
    "STAGE_1445_1500": {
        "dataset_sha256": "4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0",
        "window": "14:45-15:00",
        "cutoff": "15:00:00",
        "observed_times": tuple(f"2026-10-12 14:{minute:02d}:00" for minute in range(45, 60)),
    },
}

_HK_MORNING_CACHED_DATE = "20261015"
_HK_MORNING_CACHED_D1_SHA256 = "66225363e4dd1b9da4f316d75a8dcc5f249bc0968128c646e9632a1a8b1b1c67"
_HK_MORNING_CACHED_D1_RUN_ID = "20261015-hk-connect-d1-top100-0-2-1d08535262fd"
_HK_MORNING_CACHED_SOURCE_ID = "futu_cached_minute_capture"
_HK_MORNING_CACHED_CAPTURE_SHA256 = "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455"
_HK_MORNING_CACHED_CAPTURE_STAGE_ID = "STAGE_0945_1030"
_HK_MORNING_CACHED_CAPTURED_AT = "2026-10-15T10:31:03.491290+08:00"
_HK_MORNING_CACHED_STAGE_IDS = frozenset({
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
})


def _hk_morning_cached_d1_provenance(binding, requested):
    """Read the pinned D1 artifact to distinguish its producer run from the binding id."""
    if (
        binding is None
        or binding.status != "READY"
        or binding.market != "HK_CONNECT"
        or binding.trade_date != _HK_MORNING_CACHED_DATE
        or binding.sha256 != _HK_MORNING_CACHED_D1_SHA256
        or set(binding.codes) != set(requested)
    ):
        return None
    evidence = {
        str(item).split("=", 1)[0]: str(item).split("=", 1)[1]
        for item in binding.evidence
        if "=" in str(item)
    }
    path_text = evidence.get("hk_d1_json", "")
    if not path_text or evidence.get("hk_d1_sha256") != _HK_MORNING_CACHED_D1_SHA256:
        return None
    path = Path(path_text).expanduser()
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            return None
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != _HK_MORNING_CACHED_D1_SHA256:
            return None
        artifact = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    rows = artifact.get("rows") if isinstance(artifact, dict) else None
    artifact_codes = {
        str(row.get("code") or "").upper()
        for row in rows
        if isinstance(row, dict)
    } if isinstance(rows, list) else set()
    if (
        not isinstance(artifact, dict)
        or artifact.get("trade_date") != _HK_MORNING_CACHED_DATE
        or artifact.get("target_date") != _HK_MORNING_CACHED_DATE
        or artifact.get("signal_date") != "20261014"
        or artifact.get("pool_id") != "hkconnect_d1_top100"
        or artifact.get("source_run_id") != _HK_MORNING_CACHED_D1_RUN_ID
        or artifact.get("stage_selection_eligible") is not True
        or any(artifact.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or not isinstance(rows, list)
        or len(rows) != 100
        or len(artifact_codes) != 100
        or artifact_codes != set(requested)
        or any(
            not isinstance(row, dict)
            or row.get("target_date") != _HK_MORNING_CACHED_DATE
            or row.get("signal_date") != "20261014"
            for row in rows
        )
    ):
        return None
    return _HK_MORNING_CACHED_DATE, "20261014", _HK_MORNING_CACHED_D1_RUN_ID


def _load_hk_morning_cached_source(_v4_scope, /, plan, *, codes, shared_root):
    """Project only the frozen 2026-10-15 Futu capture through the existing Futu window aggregator."""
    dataset_path = os.environ.get("V4_HK_MORNING_CACHED_CAPTURE")
    if not dataset_path:
        return None
    from stage_center.acquisition import SourceResult

    requested = tuple(str(code).upper() for code in codes)
    if (
        plan.trade_date != _HK_MORNING_CACHED_DATE
        or plan.stage_id not in _HK_MORNING_CACHED_STAGE_IDS
        or getattr(plan, "historical_backfill", False) is not True
        or len(requested) != 100
        or len(set(requested)) != 100
    ):
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_CAPTURE_SCOPE_MISMATCH",),
            source_evidence=("historical_provider=futu_cached_minute_capture",),
        )
    binding = getattr(plan, "universe_bindings", {}).get("HK_CONNECT")
    if _hk_morning_cached_d1_provenance(binding, requested) is None:
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_D1_BINDING_MISMATCH",),
            source_evidence=("historical_provider=futu_cached_minute_capture",),
        )
    path = Path(dataset_path).expanduser()
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("capture is not a bounded regular file")
        path = path.resolve(strict=True)
        raw_bytes = path.read_bytes()
        capture_sha = hashlib.sha256(raw_bytes).hexdigest()
        if capture_sha != _HK_MORNING_CACHED_CAPTURE_SHA256:
            raise ValueError("capture SHA mismatch")
        dataset = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=(f"HK_MORNING_CACHED_CAPTURE_INVALID:{type(error).__name__}",),
            source_evidence=(
                "historical_provider=futu_cached_minute_capture",
                f"futu_capture_path={path}",
            ),
        )
    return _build_hk_morning_cached_source(
        _v4_scope,
        plan,
        codes=requested,
        shared_root=shared_root,
        capture_path=path,
        capture_sha256=capture_sha,
        dataset=dataset,
    )


def _build_hk_morning_cached_source(
    _v4_scope,
    /,
    plan,
    *,
    codes,
    shared_root,
    capture_path,
    capture_sha256,
    dataset,
):
    """Validate a capture envelope and construct an after-fact SourceResult without I/O beyond imports."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from stage_center.acquisition import SourceResult
    from stage_center.raw_store import (
        HISTORICAL_OBSERVATION_CONTRACT_ID,
        HISTORICAL_OBSERVATION_MANIFEST_SCHEMA,
        _HISTORICAL_OBSERVATION_REQUIRED_CANNOT_CONFIRM,
        _raw_artifact_csv_sha256,
        historical_observation_manifest_markers,
    )

    requested = tuple(str(code).upper() for code in codes)
    rows = dataset.get("rows") if isinstance(dataset, dict) else None
    capture_codes = dataset.get("codes") if isinstance(dataset, dict) else None
    captured_at_text = str(dataset.get("captured_at") or "") if isinstance(dataset, dict) else ""
    try:
        captured_at = datetime.fromisoformat(captured_at_text)
    except ValueError:
        captured_at = None
    if (
        capture_sha256 != _HK_MORNING_CACHED_CAPTURE_SHA256
        or plan.trade_date != _HK_MORNING_CACHED_DATE
        or plan.stage_id not in _HK_MORNING_CACHED_STAGE_IDS
        or getattr(plan, "historical_backfill", False) is not True
        or not isinstance(dataset, dict)
        or dataset.get("trade_date") != _HK_MORNING_CACHED_DATE
        or dataset.get("stage_id") != _HK_MORNING_CACHED_CAPTURE_STAGE_ID
        or dataset.get("market") != "HK_CONNECT"
        or dataset.get("adjustment") != "NONE"
        or captured_at_text != _HK_MORNING_CACHED_CAPTURED_AT
        or captured_at is None
        or captured_at.tzinfo is None
        or captured_at.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d") != _HK_MORNING_CACHED_DATE
        or not isinstance(capture_codes, list)
        or len(capture_codes) != 100
        or len(set(str(code).upper() for code in capture_codes)) != 100
        or set(str(code).upper() for code in capture_codes) != set(requested)
        or not isinstance(rows, list)
        or len(rows) != 100000
        or len(requested) != 100
        or len(set(requested)) != 100
    ):
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_CAPTURE_IDENTITY_MISMATCH",),
            source_evidence=(
                "historical_provider=futu_cached_minute_capture",
                f"futu_capture_sha256={capture_sha256}",
                f"futu_capture_path={capture_path}",
            ),
        )

    binding = getattr(plan, "universe_bindings", {}).get("HK_CONNECT")
    d1_provenance = _hk_morning_cached_d1_provenance(binding, requested)
    if d1_provenance is None:
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_D1_BINDING_MISMATCH",),
            source_evidence=(
                "historical_provider=futu_cached_minute_capture",
                f"futu_capture_sha256={capture_sha256}",
            ),
        )

    capture_row_codes = {
        str(row.get("code") or "").upper()
        for row in rows
        if isinstance(row, dict)
    }
    if capture_row_codes != set(requested) or any(not isinstance(row, dict) for row in rows):
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_CAPTURE_CODE_SET_MISMATCH",),
            source_evidence=(
                "historical_provider=futu_cached_minute_capture",
                f"futu_capture_sha256={capture_sha256}",
            ),
        )

    root = _v4_global(_v4_scope, "_shared_scripts_root")(shared_root)
    module = _v4_global(_v4_scope, "_load_shared_module")(
        root, "scripts.live_acquisition.futu_bridge"
    )
    window = module.STAGE_WINDOWS.get(plan.stage_id)
    if window is None:
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_STAGE_WINDOW_UNAVAILABLE",),
        )
    start_text, end_text, cutoff_text = window
    target_day = f"{_HK_MORNING_CACHED_DATE[:4]}-{_HK_MORNING_CACHED_DATE[4:6]}-{_HK_MORNING_CACHED_DATE[6:]}"
    from datetime import timedelta

    window_start = datetime.strptime(f"{target_day} {start_text}", "%Y-%m-%d %H:%M:%S") + timedelta(minutes=1)
    window_end = datetime.strptime(f"{target_day} {end_text}", "%Y-%m-%d %H:%M:%S")
    expected_last_bar = window_end - timedelta(seconds=5)
    target_rows = [
        row for row in rows
        if str(row.get("time_key") or "").startswith(target_day + " ")
    ]
    selected_window_rows = []
    counts = {}
    seen = set()
    for row in target_rows:
        try:
            moment = datetime.strptime(str(row.get("time_key") or ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if window_start <= moment < window_end:
            code = str(row.get("code") or "").upper()
            key = (code, moment)
            if key in seen:
                return SourceResult(
                    _HK_MORNING_CACHED_SOURCE_ID,
                    "CANNOT_CONFIRM",
                    requested_rows=len(requested),
                    cannot_confirm=("HK_MORNING_CACHED_WINDOW_DUPLICATE_BAR",),
                )
            seen.add(key)
            selected_window_rows.append(row)
            counts[code] = counts.get(code, 0) + 1
    if (
        len(selected_window_rows) != 500
        or set(counts) != set(requested)
        or any(counts.get(code) != 5 for code in requested)
    ):
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_WINDOW_COVERAGE_MISMATCH",),
        )

    provider_rows_sha256 = hashlib.sha256(
        json.dumps(
            sorted(selected_window_rows, key=lambda row: (str(row.get("code") or "").upper(), str(row.get("time_key") or ""))),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    projected = module.aggregate_futu_minute_window_rows(
        _HK_MORNING_CACHED_DATE,
        plan.stage_id,
        target_rows,
    )
    if (
        len(projected) != 100
        or {str(row.get("code") or "").upper() for row in projected} != set(requested)
        or any(
            row.get("bar_count") != 5
            or row.get("update_time") != f"{target_day} {expected_last_bar.strftime('%H:%M:%S')}"
            or row.get("window_start") != f"{target_day} {window_start.strftime('%H:%M:%S')}"
            or row.get("window_end") != f"{target_day} {expected_last_bar.strftime('%H:%M:%S')}"
            for row in projected
        )
    ):
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_AGGREGATION_BOUNDARY_MISMATCH",),
        )
    normalized_rows = tuple({**row, "temporal_cutoff_safe": False} for row in projected)
    raw_sha256 = _raw_artifact_csv_sha256(_HK_MORNING_CACHED_DATE, normalized_rows)
    if raw_sha256 is None:
        return SourceResult(
            _HK_MORNING_CACHED_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_MORNING_CACHED_RAW_PROJECTION_INVALID",),
        )

    source_date, signal_date, producer_run_id = d1_provenance
    code_set_sha256 = hashlib.sha256(
        json.dumps(tuple(sorted(requested)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    window_label = f"{start_text[:5]}-{end_text[:5]}"
    evidence_values = [
        f"historical_provider={_HK_MORNING_CACHED_SOURCE_ID}",
        "historical_capture_after_target_cutoff=true",
        "historical_temporal_cutoff_safe=false",
        "historical_formal_stage_eligibility=CANNOT_CONFIRM",
        "historical_natural_time_capture=CANNOT_CONFIRM",
        "historical_pit_safe=false",
        f"historical_price_signal_date={signal_date}",
        f"hk_d1_producer_run_id={producer_run_id}",
        f"hk_d1_producer_artifact_sha256={binding.sha256}",
        f"historical_source_page_set_sha256={capture_sha256}",
        f"futu_capture_path={capture_path}",
        f"futu_capture_sha256={capture_sha256}",
        f"futu_capture_stage_id={_HK_MORNING_CACHED_CAPTURE_STAGE_ID}",
        f"futu_capture_captured_at={captured_at_text}",
        "futu_capture_market=HK_CONNECT",
        "futu_capture_adjustment=NONE",
        f"futu_capture_window={plan.stage_id}:{start_text}-{end_text}",
        f"futu_capture_window_provider_rows_sha256={provider_rows_sha256}",
        "futu_capture_window_input_rows=500",
        "futu_capture_window_codes=100",
        "futu_capture_window_bars_per_code=5",
        "futu_capture_orderbook_available=false",
        f"futu_afterfact_dataset_sha256={capture_sha256}",
        f"futu_afterfact_stage_id={plan.stage_id}",
        f"futu_afterfact_window={window_label}",
        f"futu_afterfact_window_start={target_day} {window_start.strftime('%H:%M:%S')}",
        f"futu_afterfact_window_end_exclusive={target_day} {window_end.strftime('%H:%M:%S')}",
        f"futu_afterfact_last_bar={target_day} {expected_last_bar.strftime('%H:%M:%S')}",
        f"futu_afterfact_provider_rows_sha256={provider_rows_sha256}",
        f"futu_afterfact_raw_artifact_sha256={raw_sha256}",
        "futu_afterfact_temporal_cutoff_safe=false",
        "futu_afterfact_pit_safe=false",
        "futu_afterfact_formal_stage_eligibility=CANNOT_CONFIRM",
        "futu_afterfact_natural_time_capture=CANNOT_CONFIRM",
        "futu_afterfact_orderbook_unavailable=true",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    ]
    required_evidence = sorted(set(evidence_values))
    manifest = {
        "schema_version": HISTORICAL_OBSERVATION_MANIFEST_SCHEMA,
        "contract_id": HISTORICAL_OBSERVATION_CONTRACT_ID,
        "target": {
            "trade_date": _HK_MORNING_CACHED_DATE,
            "stage_id": plan.stage_id,
            "market": "HK_CONNECT",
            "source_id": _HK_MORNING_CACHED_SOURCE_ID,
            "source_status": "PARTIAL_WITH_ROWS",
            "historical_backfill": True,
            "observation_mode": "AFTERFACT_RESEARCH_ONLY",
            "requested_rows": 100,
        },
        "pool": {
            "source_date": source_date,
            "signal_date": signal_date,
            "source_run_id": producer_run_id,
            "artifact_sha256": binding.sha256,
            "code_set_sha256": code_set_sha256,
            "codes": sorted(requested),
        },
        "observation": {
            "price_signal_date": signal_date,
            "capture_after_target_cutoff": True,
            "temporal_cutoff_safe": False,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
            "natural_time_capture": "CANNOT_CONFIRM",
            "pit_safe": False,
            "source_page_set_sha256": capture_sha256,
            "raw_artifact_sha256": raw_sha256,
            "required_source_evidence_sha256": hashlib.sha256(
                json.dumps(required_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "requested_rows": 100,
            "observed_rows": 100,
            "missing_count": 0,
            "observed_codes": sorted(requested),
            "missing_codes": [],
            "capture_sha256": capture_sha256,
            "capture_path": str(capture_path),
            "capture_stage_id": _HK_MORNING_CACHED_CAPTURE_STAGE_ID,
            "capture_captured_at": captured_at_text,
            "capture_market": "HK_CONNECT",
            "capture_adjustment": "NONE",
            "capture_window": f"{plan.stage_id}:{start_text}-{end_text}",
            "capture_window_provider_rows_sha256": provider_rows_sha256,
            "capture_window_input_rows": 500,
            "capture_window_codes": 100,
            "capture_window_bars_per_code": 5,
            "raw_window_start": f"{target_day} {window_start.strftime('%H:%M:%S')}",
            "raw_window_end": f"{target_day} {expected_last_bar.strftime('%H:%M:%S')}",
        },
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "required_source_evidence": required_evidence,
    }
    token, manifest_marker, mode_marker = historical_observation_manifest_markers(manifest)
    evidence_values.extend((manifest_marker, mode_marker))
    return SourceResult(
        _HK_MORNING_CACHED_SOURCE_ID,
        "PARTIAL_WITH_ROWS",
        normalized_rows,
        cannot_confirm=tuple(_HISTORICAL_OBSERVATION_REQUIRED_CANNOT_CONFIRM) + (
            "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE",
        ),
        requested_rows=100,
        missing_symbols=(),
        source_evidence=tuple(dict.fromkeys(evidence_values)),
    )


def _load_futu_afterfact_source(plan, *, codes):
    """Read only the frozen date/stage RT_DATA evidence when recovery enables it."""
    dataset_path = os.environ.get("V4_HK_FUTU_AFTERFACT_DATASET")
    if not dataset_path:
        return None
    from stage_center.acquisition import SourceResult
    from stage_center.raw_store import (
        HK_FUTU_RTDATA_CODE_SET_SHA256,
        HK_FUTU_RTDATA_OBSERVATION_CONTRACT,
        HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256,
        HK_FUTU_RTDATA_POOL_SOURCE_SHA256,
        HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1300,
        HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1445,
        HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1300,
        HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1445,
        HK_FUTU_RTDATA_SOURCE_ID,
        _HK_FUTU_RTDATA_CANNOT_CONFIRM,
        _HK_FUTU_RTDATA_STAGE_PROFILES,
        _futu_rtd_observation_markers,
        _futu_rtd_raw_projection_sha256,
    )

    profile = _FUTU_AFTERFACT_DATASET_PROFILES.get(plan.stage_id)
    if (
        profile is None
        or plan.trade_date != "20261012"
        or getattr(plan, "same_day_late_observation_recovery", False) is not True
        or getattr(plan, "historical_backfill", False)
    ):
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_AFTERFACT_SCOPE_MISMATCH",),
            source_evidence=("futu_afterfact_dataset_enabled=true",),
        )
    dataset_file = Path(dataset_path).expanduser()
    try:
        dataset_bytes = dataset_file.read_bytes()
        dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
        dataset = json.loads(dataset_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=(f"FUTU_RT_DATA_DATASET_UNAVAILABLE:{type(error).__name__}",),
            source_evidence=("futu_afterfact_dataset_enabled=true",),
        )
    stage_profile = _HK_FUTU_RTDATA_STAGE_PROFILES.get(plan.stage_id)
    if (
        dataset_sha != profile["dataset_sha256"]
        or dataset.get("trade_date") != "20261012"
        or dataset.get("stage_id") != plan.stage_id
        or dataset.get("pool", {}).get("artifact_sha256") != HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256
        or dataset.get("pool", {}).get("source_sha256") != HK_FUTU_RTDATA_POOL_SOURCE_SHA256
        or dataset.get("pool", {}).get("code_set_sha256") != HK_FUTU_RTDATA_CODE_SET_SHA256
        or dataset.get("pool", {}).get("code_count") != 100
        or set(str(code).upper() for code in codes) != set(str(code).upper() for code in dataset.get("pool", {}).get("codes", ()))
        or len({str(code).upper() for code in codes}) != len(codes)
        or len({str(code).upper() for code in dataset.get("pool", {}).get("codes", ())}) != len(dataset.get("pool", {}).get("codes", ()))
        or len(codes) != 100
        or stage_profile is None
    ):
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_CAPTURE_IDENTITY_MISMATCH",),
            source_evidence=("futu_afterfact_dataset_enabled=true", f"futu_afterfact_capture_sha256={dataset_sha}"),
        )

    target_start, target_end = profile["window"].split("-")
    target = [
        row for row in dataset.get("provider_rows", ())
        if isinstance(row, dict)
        and str(row.get("code") or "").upper() in set(str(code).upper() for code in codes)
        and row.get("is_blank") is False
        and f"2026-10-12 {target_start}:00" <= str(row.get("time") or "") < f"2026-10-12 {target_end}:00"
    ]
    code_order = [str(code).upper() for code in codes]
    per_code = {code: [] for code in code_order}
    for row in target:
        per_code[str(row["code"]).upper()].append(row)
    expected_times = profile["observed_times"]
    if (
        len(target) != len(code_order) * len(expected_times)
        or any(tuple(sorted(str(row.get("time") or "") for row in per_code[code])) != expected_times for code in code_order)
    ):
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_TARGET_WINDOW_COVERAGE_MISMATCH",),
            source_evidence=("futu_afterfact_dataset_enabled=true", f"futu_afterfact_capture_sha256={dataset_sha}"),
        )
    provider_rows_sha256 = hashlib.sha256(
        json.dumps(
            sorted(target, key=lambda row: (str(row.get("code") or "").upper(), str(row.get("time") or ""))),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_provider_sha = stage_profile[7]
    if provider_rows_sha256 != expected_provider_sha:
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_PROVIDER_ROWS_SHA_MISMATCH",),
            source_evidence=("futu_afterfact_dataset_enabled=true", f"futu_afterfact_capture_sha256={dataset_sha}"),
        )

    capture_batch = {
        str(code).upper(): batch_index
        for batch_index, capture in enumerate(dataset.get("capture_sources", ()), start=1)
        for code in capture.get("codes", ())
    }
    last_timestamp = expected_times[-1]
    last_rows = {str(row["code"]).upper(): row for row in target if row.get("time") == last_timestamp}
    row_start = f"2026-10-12 {stage_profile[2]}"
    row_end = f"2026-10-12 {stage_profile[3]}"
    observations_per_code = stage_profile[4]
    rows = []
    for code in code_order:
        row = last_rows[code]
        rows.append({
            "batch_index": capture_batch.get(code),
            "code": code,
            "name": row.get("name") or "",
            "update_time": last_timestamp,
            "last_price": row.get("cur_price"),
            "open_price": None,
            "high_price": None,
            "low_price": None,
            "prev_close_price": row.get("last_close"),
            "turnover": row.get("turnover"),
            "volume": row.get("volume"),
            "bid_price": None,
            "ask_price": None,
            "bid_vol": None,
            "ask_vol": None,
            "window_start": row_start,
            "window_end": row_end,
            "bar_count": observations_per_code,
            "temporal_cutoff_safe": False,
        })
    expected_projection_sha = stage_profile[8]
    if _futu_rtd_raw_projection_sha256(rows) != expected_projection_sha:
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_RAW_PROJECTION_SHA_MISMATCH",),
            source_evidence=("futu_afterfact_dataset_enabled=true", f"futu_afterfact_capture_sha256={dataset_sha}"),
        )
    evidence = list(_futu_rtd_observation_markers(plan.stage_id, dataset_sha))
    evidence.extend((
        f"futu_afterfact_target_provider_rows_sha256={provider_rows_sha256}",
        "futu_afterfact_provider_fields=avg_price,code,cur_price,is_blank,last_close,name,opened_mins,time,turnover,volume",
        "futu_afterfact_missing_ohlc_fields=open_price,high_price,low_price",
        "futu_afterfact_missing_orderbook_fields=bid_price,ask_price,bid_vol,ask_vol",
        "futu_afterfact_dataset_basename=rt_data_fixedpool100_dataset_20261012.json" if plan.stage_id == "STAGE_1300_1315" else "futu_afterfact_dataset_basename=rt_data_fixedpool100_1445_dataset_20261012.json",
    ))
    expected_projection_marker = (
        f"futu_afterfact_raw_projection_sha256={HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1300}"
        if plan.stage_id == "STAGE_1300_1315"
        else f"futu_afterfact_raw_projection_sha256={HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1445}"
    )
    if expected_projection_marker not in evidence:
        return SourceResult(
            HK_FUTU_RTDATA_SOURCE_ID,
            "CANNOT_CONFIRM",
            requested_rows=len(codes),
            cannot_confirm=("FUTU_RT_DATA_CONTRACT_MARKERS_INVALID",),
            source_evidence=tuple(evidence),
        )
    return SourceResult(
        source_id=HK_FUTU_RTDATA_SOURCE_ID,
        status="PARTIAL_WITH_ROWS",
        rows=tuple(rows),
        cannot_confirm=tuple(_HK_FUTU_RTDATA_CANNOT_CONFIRM),
        requested_rows=100,
        missing_symbols=(),
        source_evidence=tuple(dict.fromkeys(evidence)),
    )




def _collect_hk_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, snapshot_root, process_runner, replay_provider):
    """Use the existing shared Futu minute route for the afternoon HK stages.

    An explicitly authorized, SHA-bound after-fact RT_DATA bundle is available
    only to same-day recovery and remains observation-only. Stage 8 continues
    to use its exact replay source and never falls back to a live provider.
    """
    if plan.stage_id == "STAGE_1545_1555":
        # Stage 8 is a historical RT_DATA replay contract.  A live ExHQ/Futu
        # scan is not an equivalent source and must never be used as a
        # fallback when the exact replay provider is unavailable.
        return _v4_global(_v4_scope, '_collect_hk_stage8_replay')(plan, codes=codes, replay_provider=replay_provider)
    cached_morning = _load_hk_morning_cached_source(
        _v4_scope, plan, codes=codes, shared_root=shared_root
    )
    if cached_morning is not None:
        return cached_morning
    futu_afterfact = _load_futu_afterfact_source(plan, codes=codes)
    if futu_afterfact is not None:
        return futu_afterfact
    if plan.stage_id in {"STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500"}:
        # Reuse the proven Futu bridge; keep the fixed D-1 input and stage window.
        root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
        module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.futu_bridge")
        result = module.collect_futu_minute(
            python_path, plan.trade_date, plan.stage_id, list(codes), market="HK_CONNECT",
            process_runner=_v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner),
            capture_root=snapshot_root,
        )
        source = _v4_global(_v4_scope, '_to_source')(
            result, source_id="futu", route="shared_futu_hkconnect_minute", requested=len(codes),
        )
        if not source.rows:
            return source
        provenance = tuple(dict.fromkeys(
            f"{key}={row[key]}" for row in source.rows
            for key in ("futu_captured_at", "futu_provider_rows_sha256", "futu_capture_path", "futu_capture_sha256") if row.get(key)
        ))
        source = _v4_global(_v4_scope, 'replace')(
            source, source_evidence=(*source.source_evidence, *provenance, "futu_adjustment=NONE"),
        )
        if getattr(plan, "same_day_late_observation_recovery", False):
            # Current quotes cannot reconstruct the opening book. Keep bars as
            # a watch list and preserve this gap instead of probing quotes again.
            recovered = _v4_global(_v4_scope, 'replace')(
                source, status="PARTIAL_WITH_ROWS",
                cannot_confirm=(*source.cannot_confirm, "FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE", "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE"),
                source_evidence=(*source.source_evidence, "same_day_late_observation_recovery=true",
                                 "active_snapshot_degraded_to_futu_observation=true", "pit_safe=false", "natural_time_capture=CANNOT_CONFIRM"),
            )
            return _mark_hk_futu_capture_pit_metadata(_v4_scope, plan, recovered)
        from inspect import signature
        refresh = _v4_global(_v4_scope, 'refresh_hk_active_lanes')
        optional = {"snapshot_root": locals().get("snapshot_root"),
                    "pool_artifact_sha256": getattr(plan.universe_bindings.get("HK_CONNECT"), "sha256", None)}
        enriched = refresh(source, codes=codes, python_path=python_path, shared_root=root,
                       process_runner=process_runner, trade_date=plan.trade_date, stage_id=plan.stage_id,
                       cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
                       **{key: value for key, value in optional.items() if key in signature(refresh).parameters})
        # A missing timed snapshot must remain a gap, but must not discard
        # the already collected afternoon bars from the observation list.
        # A valid snapshot with no matching gainer is not this failure case.
        snapshot_gaps = {"HK_ACTIVE_SNAPSHOT_UNAVAILABLE", "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"}
        if (
            plan.stage_id in {"STAGE_1300_1315", "STAGE_1445_1500"}
            and enriched.cannot_confirm
            and set(enriched.cannot_confirm).issubset(set(source.cannot_confirm) | snapshot_gaps)
            and set(enriched.cannot_confirm) & snapshot_gaps
        ):
            recovered = _v4_global(_v4_scope, 'replace')(
                source, status="PARTIAL_WITH_ROWS",
                cannot_confirm=(*enriched.cannot_confirm, "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE"),
                source_evidence=(*enriched.source_evidence,
                                 "active_snapshot_degraded_to_futu_observation=true", "pit_safe=false"),
            )
            return _mark_hk_futu_capture_pit_metadata(_v4_scope, plan, recovered)
        return _mark_hk_futu_capture_pit_metadata(_v4_scope, plan, enriched)
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.pytdx_exhq")
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    result = module.collect_pytdx_exhq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        _v4_global(_v4_scope, 'list')(codes),
        market="HK_CONNECT",
        process_runner=scoped_runner,
    )
    source = _v4_global(_v4_scope, '_to_source')(result, source_id="pytdx_exhq", route="shared_pytdx_exhq_hk_exact_d1_top100", requested=_v4_global(_v4_scope, 'len')(codes))
    if not source.rows:
        return source

    # The immutable pre-capture is the only source for the active trigger.
    hk_binding = plan.universe_bindings.get("HK_CONNECT")
    same_day_late_observation_recovery = bool(
        _v4_global(_v4_scope, 'getattr')(plan, "same_day_late_observation_recovery", False)
    )
    if (
        same_day_late_observation_recovery
        and plan.trade_date == "20261012"
        and plan.stage_id == "STAGE_0930_0935"
    ):
        return _refresh_hk_active_lanes_body(
            _v4_scope,
            source,
            codes=codes,
            python_path=python_path,
            shared_root=root,
            snapshot_root=snapshot_root,
            process_runner=process_runner,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
            pool_artifact_sha256=getattr(hk_binding, "sha256", None),
            same_day_late_observation_recovery=True,
        )
    return _v4_global(_v4_scope, 'refresh_hk_active_lanes')(
        source,
        codes=codes,
        python_path=python_path,
        shared_root=root,
        snapshot_root=snapshot_root,
        process_runner=process_runner,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
        pool_artifact_sha256=getattr(hk_binding, "sha256", None),
    )


def _mark_hk_futu_capture_pit_metadata(_v4_scope, plan, source):
    """Report capture-clock facts separately from the existing bar-window flag."""
    if plan.stage_id not in {"STAGE_1300_1315", "STAGE_1445_1500"} or not source.rows:
        return source

    from datetime import datetime
    from zoneinfo import ZoneInfo

    hong_kong = ZoneInfo("Asia/Hong_Kong")
    stage = _v4_global(_v4_scope, 'STAGE_BY_ID').get(plan.stage_id)
    cutoff_text = str(getattr(stage, "cutoff", ""))
    trade_date = str(getattr(plan, "trade_date", ""))
    try:
        if len(trade_date) != 8 or not trade_date.isdigit() or not cutoff_text:
            raise ValueError("stage cutoff scope is unavailable")
        cutoff_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        cutoff_at = datetime.fromisoformat(f"{cutoff_date}T{cutoff_text}").replace(tzinfo=hong_kong)
        capture_times = []
        for row in source.rows:
            captured_at = row.get("futu_captured_at") if isinstance(row, Mapping) else None
            if not isinstance(captured_at, str) or not captured_at.strip():
                raise ValueError("capture clock is unavailable")
            parsed = datetime.fromisoformat(captured_at)
            if parsed.tzinfo is None:
                raise ValueError("capture clock has no timezone")
            capture_times.append(parsed.astimezone(hong_kong))
    except (OverflowError, TypeError, ValueError):
        clock_available = False
        date_matches = None
        before_cutoff = None
        gap = "HK_FUTU_CAPTURE_CLOCK_UNAVAILABLE"
    else:
        clock_available = True
        date_matches = all(captured_at.date() == cutoff_at.date() for captured_at in capture_times)
        before_cutoff = all(captured_at < cutoff_at for captured_at in capture_times) if date_matches else None
        gap = (
            "HK_FUTU_CAPTURE_CLOCK_DATE_MISMATCH" if not date_matches
            else "HK_FUTU_FULL_CHAIN_PIT_UNVERIFIED" if before_cutoff
            else "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF"
        )

    before_value = "CANNOT_CONFIRM" if before_cutoff is None else str(before_cutoff).lower()
    date_value = "CANNOT_CONFIRM" if date_matches is None else str(date_matches).lower()
    evidence = (
        f"futu_capture_clock_available={str(clock_available).lower()}",
        f"futu_capture_clock_date_matches_stage={date_value}",
        f"futu_capture_before_stage_cutoff={before_value}",
        "futu_full_chain_pit_status=CANNOT_CONFIRM",
        "futu_capture_clock_alone_is_not_pit_proof=true",
    )
    return _v4_global(_v4_scope, 'replace')(
        source,
        # PIT incompleteness is an observation qualifier, not a raw-data error.
        # Keep the source partial so downstream cards cannot label it formal.
        status="PARTIAL_WITH_ROWS" if source.status == "READY" else source.status,
        source_evidence=tuple(dict.fromkeys((*source.source_evidence, *evidence,
                                           f"futu_pit_cannot_confirm={gap}"))),
    )


def _refresh_hk_active_lanes_body(_v4_scope, /, source, *, codes, python_path, shared_root, snapshot_root, process_runner, trade_date, stage_id, cutoff_at, pool_artifact_sha256, same_day_late_observation_recovery=False):
    """Rebuild the V3 active trigger from the persisted exact-stage snapshot.

    This is the recovery path after raw publication has succeeded but a
    selection publication failed. It never calls a provider or changes the
    immutable raw rows. The date, stage, cutoff and D1 code SHA must match the
    immutable pre-capture.
    """
    requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(
        _v4_global(_v4_scope, '_canonical_hk_code')(code)
        for code in codes if _v4_global(_v4_scope, '_canonical_hk_code')(code)
    ))
    active: dict[str, Mapping[str, Any]] = {}
    active_snapshot_rows: dict[str, Mapping[str, Any]] = {}
    probe_errors: tuple[str, ...] = ()
    if snapshot_root is None or not trade_date or not stage_id or not cutoff_at:
        probe_errors = ("HK_ACTIVE_SNAPSHOT_UNAVAILABLE",)
        evidence = (
            "active_snapshot_status=PERSISTED_EXACT_STAGE_UNAVAILABLE",
            "active_snapshot_temporal_cutoff_safe=false",
        )
    else:
        from stage_center.hk_stage8 import load_hk_active_snapshot

        loaded = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=requested,
            cutoff_at=cutoff_at,
            pool_artifact_sha256=pool_artifact_sha256,
        )
        evidence = tuple(loaded.get("source_evidence") or ())
        if loaded.get("status") not in {"READY", "PARTIAL_WITH_ROWS"}:
            probe_errors = tuple(loaded.get("cannot_confirm") or ("HK_ACTIVE_SNAPSHOT_UNAVAILABLE",))
            evidence += (
                "active_snapshot_status=PERSISTED_EXACT_STAGE_UNAVAILABLE",
                "active_snapshot_temporal_cutoff_safe=false",
            )
            if "HK_ACTIVE_SNAPSHOT_NO_ELIGIBLE_ROWS" in probe_errors:
                return _v4_global(_v4_scope, 'replace')(
                    source,
                    status="CANNOT_CONFIRM",
                    rows=(),
                    cannot_confirm=_v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors))
                    ),
                    source_evidence=_v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))
                    ),
                )
        if loaded.get("status") in {"READY", "PARTIAL_WITH_ROWS"}:
            probe_errors = ()
            snapshot_rows = tuple(loaded.get("rows") or ())
            active_snapshot_rows = {str(row.get("code") or ""): row for row in snapshot_rows}
            eligible_snapshot_rows = {
                code: row for code, row in active_snapshot_rows.items()
                if row.get("active_snapshot_eligible") is True
            }
            excluded_snapshot_rows = {
                code: row for code, row in active_snapshot_rows.items()
                if row.get("active_snapshot_eligible") is False
            }
            if (
                set(active_snapshot_rows) != set(requested)
                or len(active_snapshot_rows) != len(requested)
                or not eligible_snapshot_rows
                or len(eligible_snapshot_rows) != loaded.get("eligible_rows_count")
                or len(excluded_snapshot_rows) != loaded.get("excluded_rows_count")
            ):
                probe_errors = ("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING",)
                active_snapshot_rows = {}
                eligible_snapshot_rows = {}
                excluded_snapshot_rows = {}
            else:
                for code, snapshot in eligible_snapshot_rows.items():
                    previous = snapshot.get("prev_close_price")
                    last = snapshot.get("last_price")
                    turnover = snapshot.get("turnover")
                    volume_ratio = snapshot.get("volume_ratio")
                    pct = (
                        (_v4_global(_v4_scope, 'float')(last) / _v4_global(_v4_scope, 'float')(previous) - 1.0) * 100.0
                        if previous not in (None, 0) and last is not None
                        else None
                    )
                    if (
                        pct is not None
                        and pct > 0
                        and turnover is not None
                        and turnover >= 20_000_000
                        and volume_ratio is not None
                        and volume_ratio >= 1
                    ):
                        active[code] = snapshot
                evidence += (
                    "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
                    "active_snapshot_scope=EXPLICIT_REQUESTED_CODES",
                    f"active_snapshot_trade_date={trade_date}",
                    f"active_snapshot_cutoff={cutoff_at}",
                    f"active_snapshot_sha256={loaded.get('active_snapshot_sha256')}",
                    f"active_snapshot_codes_sha256={loaded.get('active_snapshot_codes_sha256')}",
                    f"active_snapshot_pool_artifact_sha256={loaded.get('active_snapshot_pool_artifact_sha256')}",
                    "active_snapshot_temporal_cutoff_safe=true",
                    "active_snapshot_temporal_cutoff_scope=eligible_rows_only",
                    f"active_snapshot_requested_rows={len(requested)}",
                    f"active_snapshot_eligible_rows={len(eligible_snapshot_rows)}",
                    f"active_snapshot_excluded_rows={len(excluded_snapshot_rows)}",
                    f"active_snapshot_exclusions_json={_v4_global(_v4_scope, 'json').dumps(loaded.get('exclusions') or [], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}",
                    f"active_snapshot_active_rows={len(active)}",
                )
                if stage_id != "STAGE_1545_1555":
                    from stage_center.hk_stage8.snapshot import _stage8_market_timestamp
                    book_gaps = []
                    for code, snapshot in eligible_snapshot_rows.items():
                        book = snapshot.get("order_book")
                        requested_at = _stage8_market_timestamp(snapshot.get("order_book_requested_at"), trade_date)
                        received_at = _stage8_market_timestamp(snapshot.get("order_book_received_at"), trade_date)
                        cutoff = _stage8_market_timestamp(cutoff_at, trade_date)
                        if (not isinstance(book, dict) or not isinstance(book.get("Bid"), list)
                                or not isinstance(book.get("Ask"), list) or snapshot.get("order_book_error")
                                or requested_at is None or received_at is None
                                or requested_at.strftime("%Y%m%d") != trade_date
                                or not requested_at <= received_at < cutoff):
                            book_gaps.append(code)
                    evidence += (f"futu_order_book_eligible_rows={len(eligible_snapshot_rows) - len(book_gaps)}",)
                    if book_gaps:
                        probe_errors += ("HK_STAGE_ORDERBOOK_INCOMPLETE",)
                        evidence += ("futu_order_book_missing_codes=" + ",".join(book_gaps),)
    if (
        same_day_late_observation_recovery
        and trade_date == "20261012"
        and stage_id == "STAGE_0930_0935"
        and "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors
    ):
        return _v4_global(_v4_scope, 'replace')(
            source,
            status="PARTIAL_WITH_ROWS",
            rows=_v4_global(_v4_scope, 'tuple')(source.rows),
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(
                _v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors))
            ),
            source_evidence=_v4_global(_v4_scope, 'tuple')(
                _v4_global(_v4_scope, 'dict').fromkeys((
                    *source.source_evidence,
                    *evidence,
                    "same_day_late_observation_recovery=true",
                    "active_snapshot_degraded_to_pytdx_observation=true",
                    "observation_trade_status=WATCH_ONLY",
                ))
            ),
        )
    enriched: list[dict[str, Any]] = []
    for row in source.rows:
        code = _v4_global(_v4_scope, '_canonical_hk_code')(row.get("code"))
        merged = _v4_global(_v4_scope, 'dict')(row)
        # A lane is valid only when the persisted exact-stage snapshot matched
        # the code. Never carry a D-1/static lane into the live minute copy.
        merged["candidate_lanes"] = []
        for field in ("source_universe", "data_confidence", "active_gainer_pass", "active_snapshot_status"):
            merged.pop(field, None)
        merged.pop("volume_ratio", None)
        book = active_snapshot_rows.get(code, {}).get("order_book") or {}
        for side, price_field, volume_field in (("Bid", "bid_price", "bid_vol"), ("Ask", "ask_price", "ask_vol")):
            levels = book.get(side) or []
            if levels and len(levels[0]) >= 2:
                merged[price_field], merged[volume_field] = levels[0][:2]
        snapshot = active_snapshot_rows.get(code)
        if snapshot is not None and set(active_snapshot_rows) == set(requested):
            # Full D-1 membership enters ranking. The strong predicate only
            # supplies its truthful lane bonus; retain every captured ratio.
            eligible = snapshot.get("active_snapshot_eligible") is True
            merged["candidate_lanes"] = ["LIVE_HKCONNECT_GAINER"] if eligible and code in active else []
            merged["source_universe"] = "HK_CONNECT_D1_TOP100"
            merged["data_confidence"] = "STAGE_RTDATA_CONFIRMED" if eligible else "ACTIVE_QUOTE_UNAVAILABLE"
            merged["active_gainer_pass"] = eligible and code in active
            merged["volume_ratio"] = snapshot.get("volume_ratio")
            merged["active_snapshot_eligible"] = eligible
            merged["active_snapshot_exclusion_reason"] = snapshot.get("active_snapshot_exclusion_reason")
            merged["active_snapshot_status"] = (
                "FUTU_HKCONNECT_FULL_SCAN" if eligible else "EXCLUDED_TEMPORAL_CUTOFF"
            )
        enriched.append(merged)
    cannot = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors)))
    if "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors:
        return _v4_global(_v4_scope, 'replace')(
            source,
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=cannot,
            source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))),
        )
    excluded_rows = tuple(row for row in active_snapshot_rows.values() if row.get("active_snapshot_eligible") is False)
    status = "PARTIAL_WITH_ROWS" if excluded_rows and source.status == "READY" else source.status
    return _v4_global(_v4_scope, 'replace')(
        source,
        status=status,
        rows=_v4_global(_v4_scope, 'tuple')(enriched),
        cannot_confirm=cannot,
        source_evidence=_v4_global(_v4_scope, 'tuple')(
            _v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))
        ),
    )
