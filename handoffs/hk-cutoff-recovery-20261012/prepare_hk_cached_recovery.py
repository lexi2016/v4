#!/usr/bin/env python3
"""Prepare one exact HK-only 2026-10-12 recovery from verified TDX probe output.

Default mode writes only below an isolated evidence root. --consume-attempt3 is
an explicit one-shot mode for the parent controller after independent review;
it never invokes a provider because its HK collector reads the pinned child
stdout files and verifies their manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

APP_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-0930-cutoff-recovery-20261012-r1/app")
CONFIG_PATH = APP_ROOT / "stage_center_tick_config.json"
SHARED_ROOT = APP_ROOT / "upstreams/v3_shared_data"
LIVE_RECEIPT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts/20261012/STAGE_0930_0935/receipt.json")
D1_PATH = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_pools/20261012/hkconnect_d1_top100.json")
CACHE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_CUTOFF_RECOVERY_20261012/evidence/tdx_fullbatch_100_20261012_r3")
EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_CUTOFF_RECOVERY_20261012/evidence")
UNSAFE_SNAPSHOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts/20261012/STAGE_0930_0935/attempt_evidence/dcb257c0b4084b44ac1e57abdff92e31/002_HK_SNAPSHOT.json")

TRADE_DATE = "20261012"
STAGE_ID = "STAGE_0930_0935"
MARKET = "HK_CONNECT"
RECOVERY_ORIGIN = "HK_ORIGINAL_BUDGET_RECOVERY"
EXPECTED_RECEIPT_SHA256 = "742b12bce16be0a009d9400d3804a54a9fcb4c24f3736d77765210682ea66721"
EXPECTED_D1_SHA256 = "220fd29bc907a1c4e431c75fb8eccb3204c5857130eb639f1e9b6a62b60cfe3d"
EXPECTED_CACHE_SHA256 = "d31415dd98b920d33817d37ebc3a18b5cdff295f6c7c1d3791f93c1c9b4a4203"
EXPECTED_CACHE_MANIFEST_SHA256 = "628ec543889782b863632cd6eba24a1786dd66159f8bcf324a3abe2c3081ce6c"
EXPECTED_PROBE_SHA256 = "9ce612fb06f022601841828bb25d11d1850cd4e3ab09de775babd56f7b8d0399"
EXPECTED_UNSAFE_SNAPSHOT_SHA256 = "00921e090fb2b55b29cf6582bea126ed1e8f23defda9676faf5692a17e35bb4a"
EXPECTED_UNSAFE_SNAPSHOT_PAYLOAD_SHA256 = "cb0f02525bba78e2bd989879839f0746734e591c3c9840dce85bdddaa1ce2c59"
EXPECTED_UNSAFE_CODES_SHA256 = "5e7ad70ddcd6bcf1ab5007ef8c5f365258e77d6e8d52ade5be2177cb24ae1223"
EXPECTED_FAILURE_REASONS = (
    "PyTDX ExHQ probe returned an error",
    "PyTDX ExHQ batch coverage incomplete: completed=0/100",
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFETY_FALSE = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha256(path.read_bytes())


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return sha256(raw)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_runtime():
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    return importlib.import_module("ops.run_stage_center_nodes")


def _manifest_verified_files(root: Path) -> tuple[dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = root / "sha256_manifest.json"
    if sha_file(manifest_path) != EXPECTED_CACHE_MANIFEST_SHA256:
        raise ValueError("fullbatch evidence manifest SHA changed")
    manifest = read_json(manifest_path)
    entries = manifest
    if set(entries) != {
        "batch_01/batch_metadata.json", "batch_01/child.stderr.raw", "batch_01/child.stdout.raw", "batch_01/request.stdin.raw",
        "batch_02/batch_metadata.json", "batch_02/child.stderr.raw", "batch_02/child.stdout.raw", "batch_02/request.stdin.raw",
        "noncanonical_reuse_cache.json", "run_spec.json", "run_summary.json",
    }:
        raise ValueError("fullbatch evidence manifest file set changed")
    expected_paths = set(entries) | {"sha256_manifest.json"}
    actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual_paths != expected_paths:
        raise ValueError("fullbatch evidence has missing or unmanifested files")
    for rel, expected_sha in entries.items():
        safe = PurePosixPath(rel)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("unsafe path in fullbatch manifest")
        path = root.joinpath(*safe.parts)
        if sha_file(path) != expected_sha:
            raise ValueError(f"fullbatch manifest mismatch: {rel}")
    if entries["noncanonical_reuse_cache.json"] != EXPECTED_CACHE_SHA256:
        raise ValueError("pinned noncanonical cache SHA changed")
    spec = read_json(root / "run_spec.json")
    summary = read_json(root / "run_summary.json")
    legacy_cache = read_json(root / "noncanonical_reuse_cache.json")
    return entries, spec, summary, legacy_cache


def load_verified_cached_rows(*, cache_root: Path = CACHE_ROOT, d1_path: Path = D1_PATH):
    """Return aggregate rows built only from hash-verified child stdout."""
    entries, spec, summary, _legacy_cache = _manifest_verified_files(cache_root)
    d1_raw = d1_path.read_bytes()
    if sha256(d1_raw) != EXPECTED_D1_SHA256:
        raise ValueError("exact HK D-1 Top100 SHA changed")
    pool = json.loads(d1_raw)
    if pool.get("trade_date") != TRADE_DATE or pool.get("market") != "HK":
        raise ValueError("exact D-1 Top100 date/market mismatch")
    d1_rows = pool.get("rows")
    if not isinstance(d1_rows, list) or len(d1_rows) != 100:
        raise ValueError("exact D-1 Top100 must have 100 rows")
    codes = [str(row.get("code") or "").strip().upper() for row in d1_rows]
    if len(set(codes)) != 100 or any(not code.startswith("HK.") or len(code) != 8 for code in codes):
        raise ValueError("exact D-1 Top100 code contract invalid")
    if spec.get("trade_date") != TRADE_DATE or spec.get("stage_id") != STAGE_ID or spec.get("market") != MARKET:
        raise ValueError("fullbatch run spec slot mismatch")
    if spec.get("pool_sha256") != EXPECTED_D1_SHA256 or spec.get("requested_code_count") != 100 or spec.get("requested_codes") != codes:
        raise ValueError("fullbatch request is not the pinned exact D-1 Top100")
    collector_summary = summary.get("collector_result") or {}
    if (
        collector_summary.get("status") != "READ_OK"
        or collector_summary.get("requested_code_count") != 100
        or collector_summary.get("completed_code_count") != 100
        or collector_summary.get("row_count") != 100
        or collector_summary.get("cannot_confirm")
        or collector_summary.get("no_data_codes")
        or summary.get("stage_runner_called") is not False
        or summary.get("stage_receipts_written") is not False
    ):
        raise ValueError("fullbatch aggregate is not READ_OK 100/100")
    probe_source = str(SHARED_ROOT / "scripts/live_acquisition/pytdx_exhq_probe.py")
    if summary.get("source_sha256", {}).get(probe_source) != EXPECTED_PROBE_SHA256:
        raise ValueError("fullbatch probe source identity mismatch")

    raw_rows: list[dict[str, Any]] = []
    per_code: dict[str, int] = {}
    batch_summaries = []
    source_batch_shas: list[str] = []
    for index in (1, 2):
        batch_dir = cache_root / f"batch_{index:02d}"
        meta = read_json(batch_dir / "batch_metadata.json")
        request_raw = (batch_dir / "request.stdin.raw").read_bytes()
        request = json.loads(request_raw)
        output_raw = (batch_dir / "child.stdout.raw").read_bytes()
        stderr_raw = (batch_dir / "child.stderr.raw").read_bytes()
        if sha256(request_raw) != entries[f"batch_{index:02d}/request.stdin.raw"]:
            raise ValueError("batch request hash mismatch")
        if sha256(output_raw) != entries[f"batch_{index:02d}/child.stdout.raw"]:
            raise ValueError("batch stdout hash mismatch")
        if stderr_raw or meta.get("returncode") != 0 or meta.get("runner_exception") is not None:
            raise ValueError(f"batch {index} was not a clean child success")
        if meta.get("pool_sha256") != EXPECTED_D1_SHA256 or meta.get("probe_source_sha256") != EXPECTED_PROBE_SHA256:
            raise ValueError(f"batch {index} source/pool identity mismatch")
        command = meta.get("command")
        expected_python = spec.get("configured_python")
        if command != [expected_python, "-m", "scripts.live_acquisition.pytdx_exhq_probe"]:
            raise ValueError("child command differs from the verified lexical venv path")
        if Path(expected_python).resolve() != Path(spec.get("configured_python_realpath", "")).resolve():
            raise ValueError("configured Python realpath does not match run spec")
        request_codes = request.get("codes")
        if request.get("trade_date") != TRADE_DATE or request.get("stage_id") != STAGE_ID or not isinstance(request_codes, list):
            raise ValueError(f"batch {index} request slot mismatch")
        if request_codes != meta.get("request_parameters", {}).get("codes"):
            raise ValueError(f"batch {index} request parameter mismatch")
        prefix = "__PYTDX_EXHQ_MINUTE_JSON__"
        output_text = output_raw.decode("utf-8")
        marker = output_text.find(prefix)
        if marker < 0:
            raise ValueError(f"batch {index} stdout marker missing")
        payload = json.loads(output_text[marker + len(prefix):].strip())
        if payload.get("requested_code_count") != len(request_codes) or payload.get("completed_code_count") != len(request_codes):
            raise ValueError(f"batch {index} probe coverage mismatch")
        if payload.get("errors") or payload.get("no_data_codes") or payload.get("error"):
            raise ValueError(f"batch {index} probe returned errors or no-data codes")
        if payload.get("source_host") != "119.97.142.130:7721":
            raise ValueError(f"batch {index} provider host mismatch")
        rows = payload.get("raw_rows")
        if not isinstance(rows, list):
            raise ValueError(f"batch {index} raw rows missing")
        batch_code_counts: dict[str, int] = {}
        for row in rows:
            code = str(row.get("code") or "").strip().upper()
            if code not in request_codes:
                raise ValueError(f"batch {index} returned an unrequested code")
            stamp = datetime.strptime(str(row.get("time_key") or ""), "%Y-%m-%d %H:%M:%S")
            if stamp.strftime("%Y%m%d") != TRADE_DATE or not ("09:31:00" <= stamp.strftime("%H:%M:%S") <= "09:35:00"):
                raise ValueError(f"batch {index} returned an out-of-window row")
            for field in ("open", "high", "low", "close", "volume", "turnover", "last_close"):
                value = row.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"batch {index} contains invalid {field}")
            batch_code_counts[code] = batch_code_counts.get(code, 0) + 1
        if set(batch_code_counts) != set(request_codes) or any(count != 5 for count in batch_code_counts.values()):
            raise ValueError(f"batch {index} did not produce exactly five bars per requested code")
        raw_rows.extend(rows)
        for code, count in batch_code_counts.items():
            per_code[code] = per_code.get(code, 0) + count
        source_batch_shas.append(entries[f"batch_{index:02d}/child.stdout.raw"])
        batch_summaries.append({
            "batch_index": index,
            "returncode": meta.get("returncode"),
            "elapsed_seconds": meta.get("elapsed_seconds"),
            "requested_code_count": len(request_codes),
            "completed_code_count": payload.get("completed_code_count"),
            "raw_row_count": len(rows),
            "source_host": payload.get("source_host"),
            "stdout_sha256": entries[f"batch_{index:02d}/child.stdout.raw"],
        })
    if len(raw_rows) != 500 or set(per_code) != set(codes) or any(per_code.get(code) != 5 for code in codes):
        raise ValueError("verified child stdout does not cover the full Top100")

    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    from stage_center.live_collectors import _load_shared_module
    module = _load_shared_module(SHARED_ROOT, "scripts.live_acquisition.pytdx_exhq")
    wrapper_path = SHARED_ROOT / "scripts/live_acquisition/pytdx_exhq.py"
    if sha_file(wrapper_path) != "19946fd9c09033a77b460fe5a68f70969623d3b1c26f058091349e702d482fdd":
        raise ValueError("verified release ExHQ aggregation wrapper changed")
    aggregate = module.aggregate_futu_minute_window_rows(TRADE_DATE, STAGE_ID, raw_rows)
    if len(aggregate) != 100 or {row.get("code") for row in aggregate} != set(codes):
        raise ValueError("existing stage-window aggregator did not produce the exact 100 rows")
    if any(row.get("bar_count") != 5 or row.get("temporal_cutoff_safe") is not True for row in aggregate):
        raise ValueError("existing stage-window aggregator contract changed")
    unsafe = read_json(UNSAFE_SNAPSHOT)
    if sha_file(UNSAFE_SNAPSHOT) != EXPECTED_UNSAFE_SNAPSHOT_SHA256:
        raise ValueError("prior same-day active snapshot evidence changed")
    unsafe_detail = unsafe.get("detail") or {}
    if (
        unsafe_detail.get("schema") != "stage.hk_temporal_diagnostic.v1"
        or unsafe_detail.get("trade_date") != TRADE_DATE
        or unsafe_detail.get("cutoff_at") != "09:35:05"
        or unsafe_detail.get("snapshot_sha256") != EXPECTED_UNSAFE_SNAPSHOT_PAYLOAD_SHA256
        or unsafe_detail.get("requested_codes_sha256") != EXPECTED_UNSAFE_CODES_SHA256
    ):
        raise ValueError("prior active-snapshot temporal evidence does not match the pinned cutoff")
    capture_at = spec.get("started_at_utc")
    if not capture_at or capture_at >= "2026-10-12T01:35:05+00:00":
        # The acquisition happened after 09:35:05 Asia/Shanghai (01:35:05 UTC).
        # The recorded raw bars remain observations; no PIT/cutoff claim is made.
        late_capture = True
    else:
        late_capture = False
    if not late_capture:
        raise ValueError("TDX cache capture is not demonstrably after the stage cutoff")

    provenance = {
        "schema_version": "hk.cached_observation_source.v1",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "market": MARKET,
        "source_id": "pytdx_exhq",
        "cache_root": str(cache_root),
        "cache_manifest_sha256": EXPECTED_CACHE_MANIFEST_SHA256,
        "noncanonical_cache_sha256": EXPECTED_CACHE_SHA256,
        "pool_path": str(d1_path),
        "pool_sha256": EXPECTED_D1_SHA256,
        "probe_source_sha256": EXPECTED_PROBE_SHA256,
        "batch_stdout_sha256s": source_batch_shas,
        "batch_summaries": batch_summaries,
        "request_code_count": 100,
        "raw_bar_count": 500,
        "aggregated_row_count": 100,
        "capture_started_at_utc": capture_at,
        "late_capture_after_cutoff": True,
        "prior_unsafe_active_snapshot_path": str(UNSAFE_SNAPSHOT),
        "prior_unsafe_active_snapshot_sha256": EXPECTED_UNSAFE_SNAPSHOT_SHA256,
        "prior_unsafe_snapshot_payload_sha256": EXPECTED_UNSAFE_SNAPSHOT_PAYLOAD_SHA256,
        "prior_unsafe_snapshot_requested_codes_sha256": EXPECTED_UNSAFE_CODES_SHA256,
        "cutoff_at": "09:35:05",
        "temporal_cutoff_safe": False,
        "pit_safe": False,
        "canonical_stage_artifact": False,
        "publication_performed": False,
        "safety": {"research_only": True, **SAFETY_FALSE},
    }
    evidence = (
        "route=shared_pytdx_exhq_hk_exact_d1_top100",
        f"hk_d1_json={d1_path}",
        f"hk_d1_sha256={EXPECTED_D1_SHA256}",
        "hk_d1_membership=exact_date_top100",
        "hk_acquisition_scope=EXACT_D1_TOP100",
        f"tdx_cache_manifest_sha256={EXPECTED_CACHE_MANIFEST_SHA256}",
        f"tdx_cache_noncanonical_sha256={EXPECTED_CACHE_SHA256}",
        f"tdx_probe_source_sha256={EXPECTED_PROBE_SHA256}",
        f"tdx_cache_capture_started_at_utc={capture_at}",
        "tdx_cache_capture_after_stage_cutoff=true",
        "same_day_late_observation_recovery=true",
        "active_snapshot_degraded_to_pytdx_observation=true",
        "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
        "active_snapshot_trade_date=20261012",
        "active_snapshot_cutoff=09:35:05",
        "active_snapshot_temporal_cutoff_safe=false",
        f"active_snapshot_sha256={EXPECTED_UNSAFE_SNAPSHOT_PAYLOAD_SHA256}",
        f"active_snapshot_codes_sha256={EXPECTED_UNSAFE_CODES_SHA256}",
        "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
        "temporal_cutoff_safe=false",
        "pit_safe=false",
        "data_class=TDX_HISTORICAL_OBSERVATION_CAPTURED_AFTER_CUTOFF",
    )
    return {
        "rows": tuple(aggregate),
        "codes": tuple(codes),
        "raw_row_count": len(raw_rows),
        "provenance": provenance,
        "source_evidence": evidence,
        "cannot_confirm": (
            "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
            "TDX_CACHE_CAPTURE_AFTER_STAGE_CUTOFF",
        ),
    }


def _expected_receipt_contract(receipt: Mapping[str, Any], raw: bytes) -> None:
    if sha256(raw) != EXPECTED_RECEIPT_SHA256:
        raise ValueError("attempt-2 receipt SHA does not match the one-shot pin")
    hk = (receipt.get("markets") or {}).get(MARKET)
    if (
        receipt.get("trade_date") != TRADE_DATE
        or receipt.get("stage_id") != STAGE_ID
        or receipt.get("node_id") != STAGE_ID
        or receipt.get("status") != "CANNOT_CONFIRM"
        or receipt.get("dispatch_mode") != "RECOVERY"
        or receipt.get("execution_origin") != RECOVERY_ORIGIN
        or receipt.get("execution_markets") != [MARKET]
        or receipt.get("node_attempt_count") != 2
        or receipt.get("node_outcome") != "TRANSIENT"
        or receipt.get("retry_exhausted") is not False
        or receipt.get("execution_pending") is not False
        or receipt.get("first_failed_layer") != "COLLECTION_OR_PUBLICATION"
        or receipt.get("error") != "all market collectors returned zero-row CANNOT_CONFIRM"
        or any(receipt.get(flag) is not False for flag in SAFETY_FALSE)
        or not isinstance(hk, dict)
        or hk.get("status") != "CANNOT_CONFIRM"
        or tuple(hk.get("cannot_confirm") or ()) != EXPECTED_FAILURE_REASONS
    ):
        raise ValueError("attempt-2 receipt fields do not match the pinned failure contract")


def _read_and_validate_attempt2(config: Mapping[str, Any], receipt_path: Path):
    raw = receipt_path.read_bytes()
    receipt = json.loads(raw)
    if not isinstance(receipt, dict):
        raise ValueError("attempt-2 receipt is not an object")
    _expected_receipt_contract(receipt, raw)
    max_attempts = int(config.get("node_max_attempts", 0))
    count = int(receipt.get("node_attempt_count", 0))
    if max_attempts != 3 or count != 2 or count + 1 != max_attempts:
        raise ValueError("only original attempt 3/3 is authorized")
    if config.get("safety") != SAFETY_FALSE:
        raise ValueError("research-only safety config changed")
    if (receipt_path.parent / "dependency_rearm.json").exists():
        raise ValueError("dependency rearm marker exists; one-shot cutoff recovery refuses")
    return raw, receipt, max_attempts


def _latest_pointer(root: Path, filename: str) -> dict[str, Any]:
    path = root / filename
    if not path.is_file():
        raise ValueError(f"required stage store pointer missing: {path}")
    data = read_json(path)
    if any(data.get(flag) is not False for flag in SAFETY_FALSE):
        raise ValueError(f"unsafe store pointer: {path}")
    if not isinstance(data.get("entries"), dict):
        raise ValueError(f"store pointer entries missing: {path}")
    return data


def _tree_sha_map(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): sha_file(p)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def protected_a_snapshot(config: Mapping[str, Any]) -> dict[str, Any]:
    raw_root = Path(str(config["raw_root"]))
    selection_root = Path(str(config["selection_root"]))
    receipt_root = Path(str(config["receipt_root"]))
    raw_latest = _latest_pointer(raw_root, "latest.json")
    selection_latest = _latest_pointer(selection_root, "selection_latest.json")
    keys = (
        f"{TRADE_DATE}/STAGE_0925/A_SHARE",
        f"{TRADE_DATE}/{STAGE_ID}/A_SHARE",
    )
    return {
        "raw_pointer_entries": {key: raw_latest["entries"].get(key) for key in keys},
        "selection_pointer_entries": {key: selection_latest["entries"].get(key) for key in keys},
        "raw_0925_tree": _tree_sha_map(raw_root / "runs" / TRADE_DATE / "A_SHARE_1MIN_STAGE_0925"),
        "selection_0925_tree": _tree_sha_map(selection_root / "selection_runs" / TRADE_DATE / "A_SHARE_SELECTION_STAGE_0925"),
        "receipt_0925_sha256": sha_file(receipt_root / TRADE_DATE / "STAGE_0925" / "receipt.json"),
    }


def _copy_run_from_entry(source_root: Path, destination_root: Path, entry: Mapping[str, Any], artifact_key: str) -> None:
    relative = PurePosixPath(str(entry.get(artifact_key) or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("unsafe immutable artifact pointer")
    source_run = source_root.joinpath(*relative.parts).parent
    prefix = PurePosixPath("runs") if artifact_key == "artifact_relative" and source_root.name == "raw" else PurePosixPath("selection_runs")
    try:
        relative_run = PurePosixPath(*source_run.relative_to(source_root).parts)
    except ValueError as exc:
        raise ValueError("immutable artifact pointer escaped its store root") from exc
    target_run = destination_root.joinpath(*relative_run.parts)
    if target_run.exists():
        raise ValueError("isolated A run path already exists")
    if not source_run.is_dir():
        raise ValueError(f"A sibling immutable run missing: {source_run}")
    shutil.copytree(source_run, target_run)


def seed_isolated_store_roots(config: dict[str, Any], prior: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    """Copy only immutable A sibling artifacts and indexes into temp stores."""
    live_raw = Path(str(config["raw_root"]))
    live_selection = Path(str(config["selection_root"]))
    temp_raw = output_root / "stage_state" / "raw"
    temp_selection = output_root / "stage_state" / "selection"
    temp_receipts = output_root / "stage_state" / "receipts"
    temp_raw.mkdir(parents=True, exist_ok=False)
    temp_selection.mkdir(parents=True, exist_ok=False)
    temp_receipts.mkdir(parents=True, exist_ok=False)
    raw_latest_raw = (live_raw / "latest.json").read_bytes()
    selection_latest_raw = (live_selection / "selection_latest.json").read_bytes()
    raw_latest = json.loads(raw_latest_raw)
    selection_latest = json.loads(selection_latest_raw)
    key = f"{TRADE_DATE}/{STAGE_ID}/A_SHARE"
    raw_entry = raw_latest.get("entries", {}).get(key)
    selection_entry = selection_latest.get("entries", {}).get(key)
    if not isinstance(raw_entry, dict) or raw_entry.get("artifact_sha256") != (prior.get("markets") or {}).get("A_SHARE", {}).get("raw_artifact_sha256"):
        raise ValueError("A same-stage raw pointer does not match the preserved receipt")
    if not isinstance(selection_entry, dict) or selection_entry.get("run_id") != (prior.get("markets") or {}).get("A_SHARE", {}).get("run_id"):
        raise ValueError("A same-stage selection pointer does not match the preserved receipt")
    _copy_run_from_entry(live_raw, temp_raw, raw_entry, "artifact_relative")
    _copy_run_from_entry(live_selection, temp_selection, selection_entry, "artifact_relative")
    (temp_raw / "latest.json").write_bytes(raw_latest_raw)
    (temp_selection / "selection_latest.json").write_bytes(selection_latest_raw)
    receipt_path = temp_receipts / TRADE_DATE / STAGE_ID / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=False)
    receipt_path.write_bytes((LIVE_RECEIPT.read_bytes()))
    config["raw_root"] = str(temp_raw)
    config["selection_root"] = str(temp_selection)
    config["receipt_root"] = str(temp_receipts)
    return {
        "raw_latest_sha256_before_copy": sha256(raw_latest_raw),
        "selection_latest_sha256_before_copy": sha256(selection_latest_raw),
        "a_raw_run_id": raw_entry.get("run_id"),
        "a_raw_artifact_sha256": raw_entry.get("artifact_sha256"),
        "a_selection_run_id": selection_entry.get("run_id"),
        "a_selection_artifact_sha256": selection_entry.get("artifact_sha256"),
        "target_receipt_sha256": sha_file(receipt_path),
        "isolated_root": str(output_root / "stage_state"),
    }


def _build_adapter(cache):
    from stage_center.acquisition import SourceResult

    def collector(plan, market):
        if market != MARKET or plan.trade_date != TRADE_DATE or plan.stage_id != STAGE_ID:
            raise ValueError("cached adapter called outside the pinned HK slot")
        if len(plan.codes_for(MARKET)) != len(cache["codes"]) or set(plan.codes_for(MARKET)) != set(cache["codes"]):
            raise ValueError("Stage plan codes differ from exact D-1 Top100")
        return SourceResult(
            source_id="pytdx_exhq",
            status="PARTIAL_WITH_ROWS",
            rows=cache["rows"],
            cannot_confirm=cache["cannot_confirm"],
            requested_rows=100,
            source_evidence=cache["source_evidence"],
        )
    return collector


def _decision_for_recovery(node, runner, evaluated_at):
    from ops._run_stage_center_nodes_parts import stage_dispatch
    decision = next(item for item in runner.due_decisions(TRADE_DATE, evaluated_at, historical_backfill=False) if item.stage_id == STAGE_ID)
    if decision.status != "LATE_CATCHUP_REPLAY":
        raise ValueError(f"expected same-day LATE_CATCHUP_REPLAY, got {decision.status}")
    decision.same_day_late_observation_recovery = stage_dispatch._same_day_late_observation_recovery(
        node.__dict__, mode="RECOVERY", trade_date=TRADE_DATE, evaluated_at=evaluated_at, decision=decision
    )
    if decision.same_day_late_observation_recovery is not True:
        raise ValueError("existing same-day late-observation helper did not authorize observation mode")
    return decision


def _read_cached_adapter(*, cache_root: Path = CACHE_ROOT, d1_path: Path = D1_PATH):
    return load_verified_cached_rows(cache_root=cache_root, d1_path=d1_path)


def _create_reservation(scoped_runner, receipt: dict[str, Any], mode: str, max_attempts: int) -> dict[str, Any]:
    return scoped_runner._write_receipt(
        {
            **receipt,
            "status": "CANNOT_CONFIRM",
            "node_outcome": "TRANSIENT",
            "node_attempt_count": 3,
            "retry_exhausted": 3 >= max_attempts,
            "dispatch_mode": mode,
            "execution_pending": True,
            "partial_commit_possible": True,
            "write_performed": False,
        },
        TRADE_DATE,
        STAGE_ID,
    )


def execute_scoped_once(
    *, config_path: Path = CONFIG_PATH,
    receipt_path: Path = LIVE_RECEIPT,
    output_root: Path,
    mode: str = "DRY_RUN",
    evaluated_at: datetime | None = None,
    collector_override: Callable[..., Any] | None = None,
    cache_root: Path = CACHE_ROOT,
    d1_path: Path = D1_PATH,
) -> dict[str, Any]:
    """Run one attempt in isolated roots, or consume the exact live attempt 3."""
    node = load_runtime()
    source_config = node._load_config(config_path)
    if source_config.get("release_id") != "hk-0930-cutoff-recovery-20261012-r1":
        raise ValueError("active release identity changed")
    if Path(str(source_config.get("shared_data_root"))).resolve() != SHARED_ROOT.resolve():
        raise ValueError("release shared-data root mismatch")
    cache = _read_cached_adapter(cache_root=cache_root, d1_path=d1_path)
    receipt_raw, receipt, max_attempts = _read_and_validate_attempt2(source_config, receipt_path)
    if evaluated_at is None:
        evaluated_at = datetime.now(SHANGHAI)
    if evaluated_at.tzinfo is None or evaluated_at.astimezone(SHANGHAI).strftime("%Y%m%d") != TRADE_DATE:
        raise ValueError("one-shot recovery only runs on the pinned same-day date")
    now = datetime.now(SHANGHAI)
    if now.strftime("%Y%m%d") != TRADE_DATE or evaluated_at > now:
        raise ValueError("evaluated time must be current same-day wall time")
    if evaluated_at <= datetime.strptime(f"{TRADE_DATE} 09:35:00", "%Y%m%d %H:%M:%S").replace(tzinfo=SHANGHAI):
        raise ValueError("cutoff recovery must run after the 09:35 stage window")
    if not node._retry_is_due(receipt, evaluated_at, retry_backoff_seconds=float(source_config.get("node_retry_backoff_seconds", 60))):
        raise ValueError("original stage retry backoff has not elapsed")
    if mode not in {"DRY_RUN", "CONSUME_ATTEMPT3"}:
        raise ValueError("unknown one-shot mode")
    if mode == "DRY_RUN":
        if output_root.exists():
            raise FileExistsError(f"isolated output root already exists: {output_root}")
        output_root.mkdir(parents=True, exist_ok=False)
        config = dict(source_config)
        seed = seed_isolated_store_roots(config, receipt, output_root)
        receipt_path = Path(config["receipt_root"]) / TRADE_DATE / STAGE_ID / "receipt.json"
        before_protected = protected_a_snapshot(source_config)
    else:
        if output_root.exists():
            raise FileExistsError(f"publish evidence root already exists: {output_root}")
        output_root.mkdir(parents=True, exist_ok=False)
        config = dict(source_config)
        seed = {"live_receipt_sha256": sha_file(receipt_path), "store_roots": "configured live roots"}
        before_protected = protected_a_snapshot(source_config)
    if Path(str(config["receipt_root"])).resolve() == Path(str(source_config["receipt_root"])).resolve() and mode != "CONSUME_ATTEMPT3":
        raise ValueError("dry-run receipt root accidentally points at live state")

    runner = node._build_runner(config)
    hk_binding = __import__("stage_center.runner", fromlist=["_build_hk_stage_binding"])._build_hk_stage_binding(
        runner.config.hk_d1_root,
        TRADE_DATE,
        preselection_source_root=runner.config.preselection_source_root,
    )
    if hk_binding.sha256 != EXPECTED_D1_SHA256 or len(hk_binding.codes) != 100 or set(hk_binding.codes) != set(cache["codes"]):
        raise ValueError("production HK binding does not match the pinned D-1 Top100")
    runner.collectors = {MARKET: collector_override or _build_adapter(cache)}
    decision = _decision_for_recovery(node, runner, evaluated_at)
    prior_bytes = receipt_path.read_bytes()
    prior = json.loads(prior_bytes)
    _expected_receipt_contract(prior, prior_bytes)
    if sha256(prior_bytes) != EXPECTED_RECEIPT_SHA256:
        raise ValueError("receipt changed before slot lock")

    from stage_center.runner import SlotLock, _slot_lock_path
    from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
    from stage_center.attempt_evidence import capture_attempt
    from stage_center import end_to_end_deadline as deadline

    lock = SlotLock(_slot_lock_path(runner.config, TRADE_DATE, STAGE_ID))
    if not lock.acquire():
        raise RuntimeError("stage slot lock is already held")
    try:
        locked_raw = receipt_path.read_bytes()
        locked_receipt = json.loads(locked_raw)
        _expected_receipt_contract(locked_receipt, locked_raw)
        if locked_raw != prior_bytes:
            raise ValueError("receipt bytes changed after slot lock")
        if config.get("safety") != SAFETY_FALSE:
            raise ValueError("research-only flags changed")
        scoped = scoped_recovery_runner(
            runner,
            markets=(MARKET,),
            prior_receipt=locked_receipt,
            attempt_count=3,
            origin=RECOVERY_ORIGIN,
        )
        reservation = _create_reservation(scoped, locked_receipt, "RECOVERY", max_attempts)
        if (
            reservation.get("node_attempt_count") != 3
            or reservation.get("execution_markets") != [MARKET]
            or reservation.get("execution_pending") is not True
            or reservation.get("retry_exhausted") is not True
            or reservation.get("markets", {}).get("A_SHARE") != locked_receipt.get("markets", {}).get("A_SHARE")
        ):
            raise AssertionError("attempt-3 reservation contract was not preserved")
        attempt_summary = None
        from stage_center import end_to_end_deadline
        deadline.due(decision.scheduled_at, trade_date=TRADE_DATE, stage_id=STAGE_ID,
                     due_status=decision.status, dispatch_mode="RECOVERY")
        deadline.checkpoint("BUSINESS_START", trade_date=TRADE_DATE, stage_id=STAGE_ID)
        with capture_attempt(
            scoped._receipt_path(TRADE_DATE, STAGE_ID).parent,
            trade_date=TRADE_DATE,
            stage_id=STAGE_ID,
            attempt_number=3,
            evaluated_at=evaluated_at.astimezone(SHANGHAI).isoformat(),
            due_status=decision.status,
        ) as journal:
            try:
                result = dict(scoped._run_one(decision))
            except Exception as error:
                result = scoped._write_receipt(
                    {
                        "status": "CANNOT_CONFIRM",
                        "trade_date": TRADE_DATE,
                        "stage_id": STAGE_ID,
                        "error": f"{type(error).__name__}:{error}",
                        "first_failed_layer": "SCOPED_EXECUTION",
                        "markets": {
                            MARKET: {
                                "status": "CANNOT_CONFIRM",
                                "selection_status": "CANNOT_CONFIRM",
                                "selected_rows": 0,
                                "cannot_confirm": [f"{type(error).__name__}:{error}"],
                                "write_performed": False,
                            }
                        },
                        "write_performed": False,
                    },
                    TRADE_DATE,
                    STAGE_ID,
                )
            journal.finish(result)
            attempt_summary = journal.summary()
        result["attempt_diagnostic"] = attempt_summary
        result.update({
            "node_id": STAGE_ID,
            "dispatch_mode": "RECOVERY",
            "node_attempt_count": 3,
            "pre_captures": [],
        })
        status = str(result.get("status") or "CANNOT_CONFIRM")
        if status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            result["status"] = status = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        elif status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is True:
            # The scope merger starts from the pinned failed receipt. Explicit
            # nulls prevent its old zero-row error/retry timer from surviving
            # a newly materialized partial observation.
            result["error"] = None
            result["first_failed_layer"] = None
            result["partial_commit_possible"] = False
        result["node_outcome"] = node._node_outcome(status, result)
        result["retry_exhausted"] = bool(result["node_outcome"] == "TRANSIENT" and 3 >= max_attempts)
        if result["node_outcome"] == "TRANSIENT" and not result["retry_exhausted"]:
            from datetime import timedelta
            result["retry_after"] = evaluated_at.astimezone(SHANGHAI).isoformat()
        else:
            result["retry_after"] = None
        persisted = scoped._write_receipt(result, TRADE_DATE, STAGE_ID)
        persisted = deadline.complete_receipt(
            scoped._receipt_path(TRADE_DATE, STAGE_ID),
            persisted,
            rewrite=lambda failed: scoped._write_receipt(failed, TRADE_DATE, STAGE_ID),
        )
    finally:
        lock.release()

    final_raw = receipt_path.read_bytes()
    final_receipt = json.loads(final_raw)
    if final_receipt.get("node_attempt_count") != 3 or final_receipt.get("execution_markets") != [MARKET]:
        raise AssertionError("final receipt did not remain HK-only attempt 3")
    if final_receipt.get("markets", {}).get("A_SHARE") != receipt.get("markets", {}).get("A_SHARE"):
        raise AssertionError("HK-only execution changed the preserved A_SHARE receipt lane")
    after_protected = protected_a_snapshot(source_config)
    if after_protected != before_protected:
        raise AssertionError("A/0925 protected artifacts or A pointers changed")
    if mode == "DRY_RUN" and sha_file(LIVE_RECEIPT) != EXPECTED_RECEIPT_SHA256:
        raise AssertionError("dry-run modified the live receipt")
    if mode == "DRY_RUN":
        live_d1_after = D1_PATH.read_bytes()
        if sha256(live_d1_after) != EXPECTED_D1_SHA256:
            raise AssertionError("dry-run modified the D-1 Top100 input")

    receipt_root = Path(str(config["receipt_root"]))
    preserved = receipt_root / TRADE_DATE / STAGE_ID / "attempt_evidence" / f"preserved-{EXPECTED_RECEIPT_SHA256}" / "PRIOR_RECEIPT.json"
    if not preserved.is_file() or preserved.read_bytes() != receipt_raw:
        raise AssertionError("scoped recovery did not preserve exact original attempt-2 receipt bytes")
    hk_lane = (final_receipt.get("markets") or {}).get(MARKET, {})
    selection_root = Path(str(config["selection_root"]))
    selection_latest_path = selection_root / "selection_latest.json"
    selection_summary = None
    if selection_latest_path.is_file():
        selection_latest = read_json(selection_latest_path)
        entry = selection_latest.get("entries", {}).get(f"{TRADE_DATE}/{STAGE_ID}/{MARKET}")
        if entry:
            from stage_center.selection import SelectionStore
            selection = SelectionStore(selection_root).read_verified(TRADE_DATE, STAGE_ID, MARKET)
            selection_summary = {
                "selection_status": selection.get("selection_status"),
                "selected_rows": selection.get("selected_rows"),
                "rows": len(selection.get("rows") or ()),
                "run_id": selection.get("run_id"),
                "artifact_sha256": entry.get("artifact_sha256"),
                "source_evidence": selection.get("source_evidence"),
                "all_rows_no_buy": all(row.get("action_level") == "NO_BUY" for row in selection.get("rows") or ()),
                "has_live_gainer_lane": any("LIVE_HKCONNECT_GAINER" in (row.get("candidate_lanes") or ()) for row in selection.get("rows") or ()),
                "has_rtd_confirmed_confidence": any(row.get("data_confidence") == "STAGE_RTDATA_CONFIRMED" for row in selection.get("rows") or ()),
            }
    raw_root = Path(str(config["raw_root"]))
    raw_latest_path = raw_root / "latest.json"
    raw_summary = None
    if raw_latest_path.is_file():
        raw_latest = read_json(raw_latest_path)
        entry = raw_latest.get("entries", {}).get(f"{TRADE_DATE}/{STAGE_ID}/{MARKET}")
        if entry:
            from stage_center.raw_store import RawStore
            verified = RawStore(raw_root).verify_latest(TRADE_DATE, STAGE_ID, MARKET)["verified"]
            raw_manifest = read_json(raw_root / str(verified["manifest_relative"]))
            raw_summary = {
                "status": verified.get("status"),
                "source_id": verified.get("source_id"),
                "row_count": verified.get("row_count"),
                "temporal_cutoff_safe": raw_manifest.get("temporal_cutoff_safe"),
                "artifact_sha256": entry.get("artifact_sha256"),
                "manifest_sha256": entry.get("manifest_sha256"),
            }
            if verified.get("status") != "PARTIAL_WITH_ROWS" or raw_manifest.get("temporal_cutoff_safe") is not False:
                raise AssertionError("cached observation raw artifact was not published as cutoff-unsafe partial")
    if selection_summary is not None:
        if (
            selection_summary.get("selection_status") != "PARTIAL_WITH_ROWS"
            or selection_summary.get("selected_rows") != 10
            or selection_summary.get("all_rows_no_buy") is not True
            or selection_summary.get("has_live_gainer_lane") is not False
            or selection_summary.get("has_rtd_confirmed_confidence") is not False
        ):
            raise AssertionError("HK selection does not meet the RECOVERY/WATCH_ONLY safety contract")
    report = {
        "schema_version": "hk.cached_recovery_preparation.v1",
        "mode": mode,
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "market_scope": [MARKET],
        "status": final_receipt.get("status"),
        "node_outcome": final_receipt.get("node_outcome"),
        "node_attempt_count": final_receipt.get("node_attempt_count"),
        "retry_exhausted": final_receipt.get("retry_exhausted"),
        "execution_pending": final_receipt.get("execution_pending"),
        "execution_origin": final_receipt.get("execution_origin"),
        "write_performed": final_receipt.get("write_performed"),
        "live_receipt_sha256_before": EXPECTED_RECEIPT_SHA256,
        "final_receipt_sha256": sha256(final_raw),
        "preserved_prior_receipt_sha256": sha_file(preserved),
        "pool_sha256": EXPECTED_D1_SHA256,
        "cache_manifest_sha256": EXPECTED_CACHE_MANIFEST_SHA256,
        "cached_source": cache["provenance"],
        "hk_lane": {key: hk_lane.get(key) for key in ("status", "source_status", "selection_status", "selected_rows", "cannot_confirm", "write_performed", "source_evidence")},
        "raw_store": raw_summary,
        "selection_store": selection_summary,
        "a_0925_and_a_sibling_protection": {"before_sha256": sha256(json.dumps(before_protected, sort_keys=True, default=str).encode()), "after_sha256": sha256(json.dumps(after_protected, sort_keys=True, default=str).encode()), "unchanged": before_protected == after_protected},
        "safety": {"research_only": True, **SAFETY_FALSE},
        "formal_publication_performed": mode == "CONSUME_ATTEMPT3" and bool(final_receipt.get("write_performed")),
        "provider_calls": 0,
        "attempt_diagnostic": attempt_summary,
    }
    report_path = output_root / "RECOVERY_PREPARED.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    report["report_sha256"] = sha_file(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "consume-attempt3"), default="dry-run")
    parser.add_argument("--output-root", type=Path, default=EVIDENCE_ROOT / "isolated_hk_recovery_20261012")
    args = parser.parse_args(argv)
    mode = "DRY_RUN" if args.mode == "dry-run" else "CONSUME_ATTEMPT3"
    report = execute_scoped_once(output_root=args.output_root, mode=mode)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
