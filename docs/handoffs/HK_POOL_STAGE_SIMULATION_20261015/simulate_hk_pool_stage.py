#!/usr/bin/env python3
"""Isolated read-path and fail-closed Stage simulation for HK 20261016.

All writes are confined to the supplied temporary root.  This script never
starts a producer, market-data client, dispatcher, or scheduled Stage job.
Every generated quote is synthetic and carries an explicitly unsafe temporal
marker; the active Stage validator is expected to reject it before raw or
selection publication.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True


TRADE_DATE = "20261016"
SIGNAL_DATE = "20261015"
STAGE_ID = "STAGE_0930_0935"
APP_SUPPORT = Path.home() / "Library/Application Support"
V4_HOME = APP_SUPPORT / "com.lexi.v4.local"
V35_HOME = APP_SUPPORT / "com.lexi.v35.local"
API_APP = V4_HOME / "releases/hk-tdx-conflict-repair-api-20261015-r5/app"
MAIN_APP = V4_HOME / "releases/hk-tdx-conflict-repair-main-20261015-r2/app"
STAGE_APP = V4_HOME / "releases/hk-auto-execution-audit-20261015-r3/app"
API_RELEASE = API_APP.parent
MAIN_RELEASE = MAIN_APP.parent
STAGE_RELEASE = STAGE_APP.parent
V4_DATA = V4_HOME / "state/data"
V35_DATA = V35_HOME / "state/data"
POOL_DAY = V35_DATA / "preselection_pools" / TRADE_DATE


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def a_code_set_sha(codes) -> str:
    normalized = tuple(sorted({str(code).strip().upper() for code in codes if str(code).strip()}))
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def api_phase(temp_root: Path) -> dict:
    sys.path.insert(0, str(API_APP))
    from apps.api.v35_api import preselection_service as service

    pool_ids = service.POOL_ORDER
    source_pools = []
    for pool_id in pool_ids:
        path = POOL_DAY / f"{pool_id}.json"
        if path.is_file():
            source_pools.append(json.loads(path.read_text(encoding="utf-8")))
    if not source_pools:
        raise RuntimeError("current exact-date source pool artifacts are unavailable")

    baseline = service._preselection_response_from_pools(
        source_pools, trade_date=TRADE_DATE, limit=500, offset=0
    )
    normalized_a_codes = {
        f"A.{match.group(1)}"
        for row in baseline.get("a_all_pool_rows", [])
        if (match := re.search(r"(\d{6})", str(row.get("code") or row.get("symbol") or row.get("stock_code") or "")))
    }
    if (
        baseline.get("a_all_pool_row_count") != 169
        or len(baseline.get("a_all_pool_rows", [])) != 169
        or len(normalized_a_codes) != 169
        or baseline.get("daily_readiness_status") != "PARTIAL_WITH_ROWS"
        or baseline.get("production_allowed") is not False
        or baseline.get("buy_gate_updated") is not False
        or baseline.get("orders_sent") is not False
    ):
        raise AssertionError("API projection did not preserve the expected full A partial aggregate")

    # Exercise the active API store's per-pool quarantine only on a copied
    # date directory under temp; shared source and manifest remain untouched.
    fixture_root = temp_root / "api-quarantine-fixture"
    fixture_day = fixture_root / "preselection_pools" / TRADE_DATE
    shutil.copytree(POOL_DAY, fixture_day)
    bad_optional_id = "a_share_baimao_research_map"
    bad_optional = fixture_day / f"{bad_optional_id}.json"
    if not bad_optional.is_file():
        raise RuntimeError("optional Baimao fixture artifact is unavailable for quarantine probe")
    bad_optional.write_bytes(b'{"SIMULATION_ONLY_corrupt_optional_artifact":true}\n')
    snapshots, errors = service.PreselectionPoolStore(fixture_root).read_all_with_quarantine(TRADE_DATE)
    quarantined = [error.pool_id for error in errors]
    if bad_optional_id not in quarantined:
        raise AssertionError("active API pool store did not quarantine the corrupted optional pool")
    good_pools = [item.get("artifact", item) for item in snapshots]
    projected = service._preselection_response_from_pools(
        good_pools, trade_date=TRADE_DATE, limit=500, offset=0
    )
    if (
        projected.get("a_all_pool_row_count") != 169
        or len(projected.get("a_all_pool_rows", [])) != 169
        or projected.get("daily_readiness_status") != "PARTIAL_WITH_ROWS"
    ):
        raise AssertionError("quarantining an optional pool blocked or truncated the A aggregate")
    return {
        "status": "PASS",
        "simulation_only": True,
        "source_pool_ids_read": [item.get("pool_id") for item in source_pools],
        "a_all_pool_rows": len(baseline["a_all_pool_rows"]),
        "a_all_pool_row_count": baseline["a_all_pool_row_count"],
        "a_all_pool_code_set_sha256": a_code_set_sha(normalized_a_codes),
        "a_all_pool_complete": baseline.get("a_all_pool_complete"),
        "daily_readiness_status": baseline["daily_readiness_status"],
        "optional_status": baseline.get("optional_pool_status"),
        "bad_optional_pool_quarantined": quarantined,
        "after_quarantine_a_all_pool_rows": len(projected["a_all_pool_rows"]),
        "after_quarantine_daily_readiness_status": projected["daily_readiness_status"],
        "safety": {
            "production_allowed": baseline["production_allowed"],
            "buy_gate_updated": baseline["buy_gate_updated"],
            "orders_sent": baseline["orders_sent"],
        },
        "sha256": {
            "api_manifest": file_sha(API_RELEASE / "release-manifest.json"),
            "api_service": file_sha(API_APP / "apps/api/v35_api/preselection_service.py"),
            "main_manifest": file_sha(MAIN_RELEASE / "release-manifest.json"),
            "main_mapper": file_sha(MAIN_APP / "infrastructure/scheduling/executor_registry_preselection.py"),
            "source_hk_pool": file_sha(POOL_DAY / "hkconnect_d1_top100.json"),
        },
    }


def stage_phase(temp_root: Path) -> dict:
    sys.path.insert(0, str(STAGE_APP))
    from stage_center.acquisition import SourceResult
    from stage_center.candidate_input import read_candidate_input
    from stage_center.research_context import ResearchContextError
    from stage_center.runner import RunnerConfig, StageCenterRunner, _build_hk_stage_binding
    from stage_center.scheduler import evaluate_due
    from infrastructure.stage_acquisition_universe_commit import EvidenceIdentity, StageAcquisitionUniverseCommit
    from ops.materialize_stage_acquisition_universe import build_artifact

    binding = _build_hk_stage_binding(
        V4_DATA, TRADE_DATE, preselection_source_root=V35_DATA
    )
    if binding.trade_date != TRADE_DATE or binding.market != "HK_CONNECT" or len(binding.codes) != 100:
        raise AssertionError("active Stage resolver/validator/extractor did not bind exact HK Top100")
    source_pool = json.loads((POOL_DAY / "hkconnect_d1_top100.json").read_text(encoding="utf-8"))
    if (
        source_pool.get("signal_date") != SIGNAL_DATE
        or source_pool.get("trade_date") != TRADE_DATE
        or source_pool.get("target_date") != TRADE_DATE
        or binding.sha256 != file_sha(POOL_DAY / "hkconnect_d1_top100.json")
    ):
        raise AssertionError("active Stage binding is not pinned to the current exact-date 20261016/signal15 pool")

    a_collector_calls = []

    def synthetic_a_collector(plan, market):
        a_collector_calls.append(market)
        raise AssertionError("A collector must not run when the exact A current is absent")

    def synthetic_hk_collector(plan, market):
        if market != "HK_CONNECT":
            raise AssertionError("unexpected market collector requested")
        rows = tuple({
            "batch_index": index,
            "code": code,
            "name": "",
            "update_time": "2026-10-16 09:34:00",
            "last_price": "10.01",
            "open_price": "10.00",
            "high_price": "10.10",
            "low_price": "9.90",
            "prev_close_price": "10.00",
            "turnover": "100000",
            "volume": "10000",
            "bid_price": "10.00",
            "ask_price": "10.02",
            "bid_vol": "100",
            "ask_vol": "100",
            "window_start": "2026-10-16 09:30:00",
            "window_end": "2026-10-16 09:34:00",
            "bar_count": "5",
            "temporal_cutoff_safe": False,
        } for index, code in enumerate(plan.codes_for(market), start=1))
        return SourceResult(
            source_id="SIMULATION_ONLY_SYNTHETIC_QUOTES",
            status="PARTIAL_WITH_ROWS",
            rows=rows,
            cannot_confirm=(
                "SIMULATION_ONLY_NO_REAL_MINUTE_DATA",
                "SIMULATION_ONLY_PIT_CANNOT_CONFIRM",
                "SIMULATION_ONLY_NATURAL_TIME_CANNOT_CONFIRM",
            ),
            requested_rows=len(rows),
            source_evidence=(
                "SIMULATION_ONLY=true",
                "temporal_cutoff_safe=false",
                "pit_safe=CANNOT_CONFIRM",
                "natural_time=CANNOT_CONFIRM",
                "production_allowed=false",
                "buy_gate_updated=false",
                "orders_sent=false",
            ),
        )

    config = RunnerConfig(
        candidate_acquisition_root=temp_root / "no-a-candidate",
        raw_root=temp_root / "stage-raw",
        selection_root=temp_root / "stage-selection",
        receipt_root=temp_root / "stage-receipts",
        hk_d1_root=V4_DATA,
        preselection_source_root=V35_DATA,
        shared_data_root=temp_root / "unused-shared-bridge-root",
        python_path=Path(sys.executable),
    )
    runner = StageCenterRunner(
        config,
        collectors={"A_SHARE": synthetic_a_collector, "HK_CONNECT": synthetic_hk_collector},
    )
    evaluated_at = datetime(2026, 10, 16, 9, 35, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    decision = evaluate_due(STAGE_ID, TRADE_DATE, evaluated_at)
    if decision.status != "DUE":
        raise RuntimeError(f"representative Stage did not resolve to DUE: {decision.status}")
    result = runner._run_one(decision)
    receipt_path = temp_root / "stage-receipts" / TRADE_DATE / STAGE_ID / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else result
    raw_artifacts = list((temp_root / "stage-raw").rglob("artifact.csv")) if (temp_root / "stage-raw").exists() else []
    if (
        receipt.get("status") != "CANNOT_CONFIRM"
        or receipt.get("write_performed") is not False
        or raw_artifacts
        or "SIMULATION_ONLY=true" not in str(receipt)
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or "temporal_cutoff_safe must be true" not in str(receipt)
    ):
        raise AssertionError("Stage did not fail closed before raw/selection publication on synthetic unsafe rows")

    # Positive 09:35 canary: materialize only a temporary strict candidate
    # pointer from the existing exact-date A pool snapshot, then feed the real
    # Stage runner synthetic rows whose frozen-clock relation satisfies the
    # existing validator.  This does not authorize PIT or natural evidence.
    positive_root = temp_root / "positive-0935"
    candidate_root = positive_root / "candidate"
    candidate_artifact = build_artifact(
        V35_DATA,
        TRADE_DATE,
        preselection_source_root=V35_DATA,
    )
    if len(candidate_artifact.get("codes", ())) != 169:
        raise AssertionError("strict Stage candidate builder did not retain the complete A 169-code input")
    candidate_store = StageAcquisitionUniverseCommit(
        candidate_root,
        preselection_source_root=V35_DATA,
    )
    candidate_store.publish(
        candidate_artifact,
        run_id="SIMULATION_ONLY_HK_POOL_STAGE_20261016",
        identity=EvidenceIdentity(
            owner_id="V3_5_STAGE_CENTER",
            producer_id="ops.materialize_stage_acquisition_universe",
            release_id="SIMULATION_ONLY_HK_POOL_STAGE_20261015",
            lane_id="A_SHARE_STAGE_ACQUISITION",
        ),
    )
    candidate = read_candidate_input(candidate_root, TRADE_DATE)
    if len(candidate.codes) != 169 or candidate.run_id != "SIMULATION_ONLY_HK_POOL_STAGE_20261016":
        raise AssertionError("strict Stage candidate reader did not consume the isolated A 169-code fixture")

    positive_counts = {"A_SHARE": 0, "HK_CONNECT": 0}
    positive_calls = []

    def synthetic_rows(codes):
        return tuple({
            "batch_index": index,
            "code": code,
            "name": code,
            "update_time": "2026-10-16 09:34:59",
            "last_price": "10.01",
            "open_price": "10.00",
            "high_price": "10.10",
            "low_price": "9.90",
            "prev_close_price": "10.00",
            "turnover": "100000",
            "volume": "10000",
            "bid_price": "10.00",
            "ask_price": "10.02",
            "bid_vol": "100",
            "ask_vol": "100",
            "window_start": "2026-10-16 09:30:00",
            "window_end": "2026-10-16 09:34:59",
            "bar_count": "5",
            # Per the parent canary brief, true here means only that these
            # synthetic timestamps satisfy the frozen 09:35 cutoff relation.
            "temporal_cutoff_safe": True,
        } for index, code in enumerate(codes, start=1))

    def positive_collector(plan, market):
        if market not in positive_counts:
            raise AssertionError(f"unexpected market collector requested: {market}")
        codes = plan.codes_for(market)
        expected = 169 if market == "A_SHARE" else 100
        if len(codes) != expected:
            raise AssertionError(f"{market} plan code count {len(codes)} != expected {expected}")
        positive_counts[market] = len(codes)
        positive_calls.append(market)
        return SourceResult(
            source_id=f"SIMULATION_ONLY_SYNTHETIC_{market}_MINUTES",
            status="PARTIAL_WITH_ROWS",
            rows=synthetic_rows(codes),
            cannot_confirm=(
                "SIMULATION_ONLY_SYNTHETIC_MARKET_ROWS",
                "SIMULATION_ONLY_NO_REAL_MINUTE_DATA",
                "SIMULATION_ONLY_PIT_CANNOT_CONFIRM",
                "SIMULATION_ONLY_NATURAL_TIME_CANNOT_CONFIRM",
            ),
            requested_rows=len(codes),
            source_evidence=(
                "SIMULATION_ONLY=true",
                "fixture_kind=SYNTHETIC_MINUTE_ROWS",
                "frozen_evaluation_clock=2026-10-16T09:35:05+08:00",
                "synthetic_window=2026-10-16 09:30:00..09:34:59",
                "temporal_cutoff_safe=true; synthetic frozen-clock relation only",
                "pit_safe=CANNOT_CONFIRM",
                "natural_time=CANNOT_CONFIRM",
                "production_allowed=false",
                "buy_gate_updated=false",
                "orders_sent=false",
            ),
        )

    import stage_center.live_collectors as live_collectors
    from stage_center.selection import select_a_live_stage
    from unittest import mock

    research_root = positive_root / "unavailable-exact-date-research"
    morning_root = positive_root / "unavailable-exact-date-morning-news"
    active_builders = live_collectors.production_selection_builders(
        STAGE_ID,
        research_root=research_root,
        morning_root=morning_root,
    )
    a_selection_context_errors = []

    def a_selection_builder(source, plan, raw):
        try:
            return active_builders["A_SHARE"](source, plan, raw)
        except ResearchContextError as error:
            # Keep the production builder's missing exact-date research gate
            # explicit, while letting the existing pure selector publish a
            # fail-closed simulation envelope so the HK lane can be read back.
            error_text = str(error)
            if "V4 research data root is missing" not in error_text:
                raise
            a_selection_context_errors.append("V4_RESEARCH_DATA_ROOT_MISSING")
            adapted_rows = tuple({
                "code": row.get("code"),
                "name": row.get("name"),
                "stock_name": row.get("name"),
                "formal_eligible": False,
                "formal_rank": "",
                "candidate": {"score": None},
                "qmt": {
                    "open": row.get("open_price"),
                    "lastPrice": row.get("last_price"),
                    "lastClose": row.get("prev_close_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "amount": row.get("turnover"),
                    "bidVol": [row.get("bid_vol")],
                    "askVol": [row.get("ask_vol")],
                },
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
                "acquisition_rank": row.get("batch_index"),
                "lane_evidence": ["STAGE_ACQUISITION_UNIVERSE"],
            } for row in source.rows)
            return select_a_live_stage(
                adapted_rows,
                plan.trade_date,
                plan.stage_id,
                str(raw["artifact_sha256"]),
                source_status="CANNOT_CONFIRM",
                requested_rows=raw["requested_rows"],
                missing_symbols=raw["missing_symbols"],
                cannot_confirm=tuple(source.cannot_confirm) + (
                    "SIMULATION_ONLY_EXACT_DATE_RESEARCH_CONTEXT_NOT_BOUND",
                ),
                source_evidence=tuple(raw["source_evidence"]) + tuple(source.source_evidence) + (
                    "SIMULATION_ONLY=true",
                    "research_context=CANNOT_CONFIRM",
                    "pit_safe=CANNOT_CONFIRM",
                    "production_allowed=false",
                    "buy_gate_updated=false",
                    "orders_sent=false",
                ),
            )

    positive_config = RunnerConfig(
        candidate_acquisition_root=candidate_root,
        raw_root=positive_root / "stage-raw",
        selection_root=positive_root / "stage-selection",
        receipt_root=positive_root / "stage-receipts",
        v4_research_data_root=research_root,
        v4_morning_news_root=morning_root,
        hk_d1_root=V4_DATA,
        preselection_source_root=V35_DATA,
        shared_data_root=positive_root / "unused-shared-bridge-root",
        python_path=Path(sys.executable),
    )
    with mock.patch.object(
        live_collectors,
        "production_selection_builders",
        lambda _stage_id, **_kwargs: {
            "A_SHARE": a_selection_builder,
            "HK_CONNECT": active_builders["HK_CONNECT"],
        },
    ):
        positive_runner = StageCenterRunner(
            positive_config,
            collectors={"A_SHARE": positive_collector, "HK_CONNECT": positive_collector},
        )
        positive_result = positive_runner._run_one(decision)

    positive_receipt_path = positive_root / "stage-receipts" / TRADE_DATE / STAGE_ID / "receipt.json"
    positive_receipt = json.loads(positive_receipt_path.read_text(encoding="utf-8"))
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore

    raw_store = RawStore(positive_root / "stage-raw")
    raw_bundle = raw_store.read_verified_bundle(TRADE_DATE, STAGE_ID)
    raw_market_receipts = raw_bundle["receipt"]["markets"]
    raw_readbacks = {}
    for market, expected in (("A_SHARE", 169), ("HK_CONNECT", 100)):
        market_receipt = raw_market_receipts[market]
        raw_readbacks[market] = raw_store.verify_run(
            TRADE_DATE, STAGE_ID, market, str(market_receipt["run_id"])
        )
        if raw_readbacks[market].get("row_count") != expected:
            raise AssertionError(f"verified {market} raw row count does not match {expected}")
        if "SIMULATION_ONLY=true" not in str(raw_readbacks[market].get("source_evidence")):
            raise AssertionError(f"verified {market} raw artifact lost its SIMULATION_ONLY marker")
        raw_artifact_path = positive_root / "stage-raw" / raw_readbacks[market]["artifact_relative"]
        with raw_artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
            persisted_rows = list(csv.DictReader(stream))
        if (
            len(persisted_rows) != expected
            or any(str(row.get("temporal_cutoff_safe", "")).strip().lower() != "true" for row in persisted_rows)
        ):
            raise AssertionError(f"{market} raw readback lost the synthetic frozen-clock temporal marker")
    selection_store = SelectionStore(positive_root / "stage-selection")
    selection_readbacks = {
        market: selection_store.read_verified(TRADE_DATE, STAGE_ID, market)
        for market in ("A_SHARE", "HK_CONNECT")
    }
    selection_artifact_count = len(list((positive_root / "stage-selection").rglob("*.json")))
    if (
        positive_result.get("write_performed") is not True
        or positive_result.get("status") not in {"PARTIAL_WITH_ROWS", "CANNOT_CONFIRM"}
        or set(positive_receipt.get("markets", {})) != {"A_SHARE", "HK_CONNECT"}
        or selection_artifact_count < 2
        or any(positive_receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or any(
            selection_readbacks[market].get(flag) is not False
            for market in selection_readbacks
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
        )
        or any(
            "SIMULATION_ONLY=true" not in str(selection_readbacks[market].get("source_evidence"))
            for market in selection_readbacks
        )
        or "SIMULATION_ONLY" not in str(positive_receipt)
        or positive_counts != {"A_SHARE": 169, "HK_CONNECT": 100}
        or set(positive_calls) != {"A_SHARE", "HK_CONNECT"}
        or not a_selection_context_errors
    ):
        raise AssertionError("positive Stage runner canary did not reach isolated raw, selection, and receipt readback")

    return {
        "status": "PASS_FAIL_CLOSED_AND_SELECTION_CANARIES",
        "simulation_only": True,
        "stage_id": STAGE_ID,
        "trade_date": TRADE_DATE,
        "signal_date": SIGNAL_DATE,
        "binding_code_count": len(binding.codes),
        "binding_source_sha256": binding.sha256,
        "binding_evidence": list(binding.evidence),
        "synthetic_market_rows": len(binding.codes),
        "a_collector_calls": len(a_collector_calls),
        "runner_receipt_status": receipt.get("status"),
        "runner_first_failed_layer": receipt.get("first_failed_layer"),
        "runner_error": receipt.get("error"),
        "raw_artifact_count": len(raw_artifacts),
        "selection_root_has_entries": any((temp_root / "stage-selection").rglob("*.json")),
        "safe_boundary": "Negative rows explicitly carry temporal_cutoff_safe=false; the active Stage raw validator rejects them before raw or selection publication.",
        "selection_and_receipt_full_path": "CANNOT_CONFIRM for the negative unsafe-row probe; see the separate positive synthetic-clock canary below.",
        "safety": {
            "production_allowed": receipt.get("production_allowed"),
            "buy_gate_updated": receipt.get("buy_gate_updated"),
            "orders_sent": receipt.get("orders_sent"),
        },
        "sha256": {
            "stage_manifest": file_sha(STAGE_RELEASE / "release-manifest.json"),
            "stage_config": file_sha(STAGE_APP / "stage_center_tick_config.json"),
            "stage_runner": file_sha(STAGE_APP / "stage_center/runner.py"),
            "stage_raw_validator": file_sha(STAGE_APP / "stage_center/_raw_store_parts/receipt_identity.py"),
            "stage_candidate_builder": file_sha(STAGE_APP / "ops/materialize_stage_acquisition_universe.py"),
            "stage_candidate_commit": file_sha(STAGE_APP / "infrastructure/stage_acquisition_universe_commit.py"),
            "stage_candidate_reader": file_sha(STAGE_APP / "stage_center/candidate_input.py"),
            "stage_selection_builder_registry": file_sha(STAGE_APP / "stage_center/_live_collectors_parts/selection_builder_registry.py"),
            "a_live_selector": file_sha(STAGE_APP / "stage_center/_selection_parts/a_live.py"),
            "hk_four_lane_selector": file_sha(STAGE_APP / "stage_center/_selection_parts/hk_four_lanes.py"),
        },
        "positive_selection_receipt_canary": {
            "status": "PASS_SELECTION_AND_RECEIPT_SIMULATION",
            "simulation_only": True,
            "stage_id": STAGE_ID,
            "trade_date": TRADE_DATE,
            "signal_date": SIGNAL_DATE,
            "frozen_evaluation_clock": "2026-10-16T09:35:05+08:00",
            "synthetic_window": "2026-10-16 09:30:00..09:34:59",
            "temporal_cutoff_safe_meaning": "Synthetic frozen-clock relationship only; not a PIT or real-market assertion.",
            "a_candidate_code_count": len(candidate.codes),
            "a_candidate_code_set_sha256": a_code_set_sha(candidate.codes),
            "a_candidate_current_sha256": candidate.current_sha256,
            "a_candidate_pool_set_sha256": candidate.source_pool_set_sha256,
            "hk_binding_code_count": len(binding.codes),
            "hk_binding_source_sha256": binding.sha256,
            "collector_calls": positive_calls,
            "collector_code_counts": positive_counts,
            "synthetic_raw_rows": {market: raw_readbacks[market]["row_count"] for market in raw_readbacks},
            "synthetic_raw_temporal_marker": "temporal_cutoff_safe=true in persisted fixture rows; means frozen synthetic clock relation only",
            "verified_selection_status": {
                market: selection_readbacks[market]["selection_status"]
                for market in selection_readbacks
            },
            "verified_selection_rows": {
                market: selection_readbacks[market].get("selected_rows", len(selection_readbacks[market].get("rows", ())))
                for market in selection_readbacks
            },
            "selection_artifact_count": selection_artifact_count,
            "runner_receipt_status": positive_receipt.get("status"),
            "runner_receipt_sha256_in_temp": file_sha(positive_receipt_path),
            "a_exact_research_context_error": a_selection_context_errors[0],
            "raw_projection_source_ids": {
                market: raw_readbacks[market].get("source_id") for market in raw_readbacks
            },
            "temporary_artifacts_confined_to_supplied_temp_root": True,
            "safety": {
                "production_allowed": positive_receipt.get("production_allowed"),
                "buy_gate_updated": positive_receipt.get("buy_gate_updated"),
                "orders_sent": positive_receipt.get("orders_sent"),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("api", "stage"))
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    if args.phase:
        if args.temp_root is None:
            raise SystemExit("--temp-root is required for a phase")
        result = api_phase(args.temp_root) if args.phase == "api" else stage_phase(args.temp_root)
        emit(result)
        return 0

    with tempfile.TemporaryDirectory(prefix="hk-pool-stage-sim-", dir="/private/tmp") as value:
        temp_root = Path(value)
        phases = {}
        for phase in ("api", "stage"):
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--phase", phase, "--temp-root", str(temp_root)],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[3]),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{phase} phase failed: {completed.stderr.strip() or completed.stdout.strip()}"
                )
            phases[phase] = json.loads(completed.stdout)
        api_code_sha = phases["api"].get("a_all_pool_code_set_sha256")
        stage_code_sha = (phases["stage"].get("positive_selection_receipt_canary") or {}).get(
            "a_candidate_code_set_sha256"
        )
        if api_code_sha != stage_code_sha:
            raise AssertionError("API A169 aggregate and strict Stage candidate code sets differ")
        emit({
            "schema_version": "hk_pool_stage_simulation.v1",
            "simulation_only": True,
            "phases": phases,
            "cross_phase_contract": {
                "status": "PASS",
                "a_code_count": 169,
                "api_a_all_pool_code_set_sha256": api_code_sha,
                "stage_candidate_code_set_sha256": stage_code_sha,
            },
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
