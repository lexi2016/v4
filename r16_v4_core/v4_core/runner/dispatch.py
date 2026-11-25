"""Evaluate the scheduled business lanes without running auxiliary owners."""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from typing import Any, Callable

from v4_core.config import V4Config
from v4_core.runner.a_daily_authority import publish_a_daily
from v4_core.runner.cache_lanes import publish_stage7, read_hk_cache, read_stage7, write_hk_cache
from v4_core.runner.evidence import DatedInputs, EvidenceError, SAFETY_FLAGS, aware_time, iso_date, mapping, require, symbol
from v4_core.runner.main_windows import materialize_stage_window
from v4_core.runner.review_inputs import compose_review_core, lane_or_gap
from v4_core.runner.schedule import MAIN_STAGES, folded_readbacks
from v4_core.runner.state import WriterLease
from v4_core.storage.db import V4Store


def _gap(reason: str) -> dict[str, Any]:
    return {"status": "CANNOT_CONFIRM", "reason": reason, **SAFETY_FLAGS}


def _bind_factors(inputs: DatedInputs, store: V4Store) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    entry = inputs.entry("a_daily")
    evidence = inputs.file(entry.get("factors"))
    rows = evidence.json()
    require(isinstance(rows, list) and rows, "A_VERIFIED_FACTORS_UNAVAILABLE")
    references = store.get_a_daily_reference_inputs(inputs.trade_date)
    expected = {(row["symbol"], inputs.trade_date) for row in references}
    allowed = expected | {(row["symbol"], row["prior_date"]) for row in references if row["prior_date"]}
    checked: dict[tuple[str, str], dict] = {}
    for value in rows:
        row = mapping(value, "A_VERIFIED_FACTOR_INVALID")
        code = symbol(row.get("symbol"), "A")
        factor = row.get("adj_factor")
        day = iso_date(row.get("trade_date"))
        key = (code, day)
        require(row.get("market") == "A" and key in allowed and key not in checked
                and type(factor) in {int, float} and math.isfinite(factor) and factor > 0,
                "A_VERIFIED_FACTOR_IDENTITY_MISMATCH")
        checked[key] = {"market": "A", "symbol": code, "trade_date": day, "adj_factor": factor}
    require(expected <= checked.keys(), "A_VERIFIED_FACTORS_SYMBOL_MISMATCH")
    store.upsert_adj_factors(list(checked.values()))
    bound: dict[str, dict[str, float]] = {}
    for (code, day), row in checked.items():
        bound.setdefault(code, {})[day] = row["adj_factor"]
    return evidence.identity(), bound


def _qualified_asof(entry: dict, day: str, asof: datetime, lane: str) -> None:
    observed = aware_time(entry.get("observed_at"))
    require(observed.date().isoformat() == day and observed <= asof,
            f"{lane}_EVIDENCE_AFTER_READBACK:{observed.isoformat()}")


def dispatch_window(
    cfg: V4Config, start: datetime, observed: datetime, phase: str, slot: str, lease: WriterLease,
    *, inputs: DatedInputs | None, inputs_gap: str, run_slot: Callable[..., dict],
    hk_bars_json: Path | None, run_a_pipeline: Callable[[dict[str, dict[str, float]]], dict],
    wait_for_observation: Callable[[dict], dict] | None = None,
    stage_owner_root: Path | None = None,
) -> tuple[str, dict, dict]:
    day = start.date().isoformat()
    main = MAIN_STAGES.get((start.hour, start.minute))
    if main:
        folded = folded_readbacks(inputs, main, observed)
        if stage_owner_root is None:
            workload = run_slot(cfg, day, slot, phase=phase, stage=main.stage_id, lease=lease)
        else:
            store = V4Store(cfg.db_path)
            isolated = set(store.get_a_workbench_quarantines(day))
            stage_result = materialize_stage_window(
                cfg.data_dir, stage_owner_root, start, main.stage_id, observed, isolated_a=isolated,
            )
            status = "DONE" if stage_result["status"] == "READY" else stage_result["status"]
            workload = store.record_slot_execution(
                day, slot, f"Stage Center {main.stage_id}", start.strftime("%H:%M"), status,
                lease.owner["token"], stage_result,
            )
        details: dict[str, Any] = {"folded_tasks": folded}
        if phase == "main_stage7":
            try:
                require(inputs is not None, inputs_gap)
                _qualified_asof(inputs.entry("stage7"), day, observed, "STAGE7")
                details["stage7_formal"] = publish_stage7(cfg.data_dir, inputs)
            except EvidenceError as exc:
                details["stage7_formal"] = _gap(str(exc))
        if phase == "main_preopen" and inputs and inputs.payload.get("stage7_prior_source_date"):
            try:
                source = iso_date(inputs.payload["stage7_prior_source_date"])
                details["stage7_prior"], _ = read_stage7(cfg.data_dir, source, day)
            except EvidenceError as exc:
                details["stage7_prior"] = _gap(str(exc))
        all_ready = workload.get("status") == "DONE" and all(value["status"] == "READY" for value in folded.values())
        linked = [value["status"] for key, value in details.items() if key != "folded_tasks"]
        all_ready = all_ready and all(status == "READY" for status in linked)
        any_ready = workload.get("status") in {"DONE", "PARTIAL"} or "READY" in linked or any(
            value["status"] == "READY" for value in folded.values()
        )
        return ("DONE" if all_ready else "PARTIAL" if any_ready else "CANNOT_CONFIRM"), workload, details

    if phase == "source_check":
        try:
            formal, _ = read_stage7(cfg.data_dir, day)
        except EvidenceError as exc:
            formal = _gap(str(exc))
            if inputs is not None and str(exc) == "VERIFIED_STAGE7_REGISTRY_UNAVAILABLE":
                try:
                    _qualified_asof(inputs.entry("stage7"), day, observed, "STAGE7")
                    publish_stage7(cfg.data_dir, inputs)
                    formal, _ = read_stage7(cfg.data_dir, day)
                except EvidenceError as fallback:
                    formal = _gap(str(fallback))
        return formal["status"], formal, {}

    if phase == "hk_ingest":
        workload = run_slot(cfg, day, slot, phase=phase, hk_bars_json=hk_bars_json, lease=lease)
        return workload["status"], workload, {}

    if inputs is None:
        paired = ({"next_day_observation": _gap("NEXT_DAY_OBSERVATION_UPSTREAM_COMPLETION_UNVERIFIED")}
                  if phase == "evening" else {})
        return "CANNOT_CONFIRM", _gap(inputs_gap), paired

    if phase == "a_daily":
        hk_close = lane_or_gap(cfg, inputs, "hk_close", observed, stage_owner_root=stage_owner_root)
        phases = {"hk_connect_close_review": hk_close}
        try:
            _qualified_asof(inputs.entry("a_daily"), day, observed, "A_DAILY")
            store = V4Store(cfg.db_path)
            authority = publish_a_daily(cfg.data_dir, store, inputs, lease)
        except EvidenceError as exc:
            workload = _gap(str(exc))
            return ("PARTIAL" if hk_close["status"] in {"READY", "PARTIAL"} else "CANNOT_CONFIRM"), workload, phases
        try:
            factor_identity, bound_factors = _bind_factors(inputs, store)
            downstream = run_a_pipeline(bound_factors)
            downstream["factor_identity"] = factor_identity
        except EvidenceError as exc:
            downstream = _gap(str(exc))
        workload = {**authority, "downstream": downstream}
        done = (authority["status"] == "READY" and downstream["status"] == "DONE"
                and downstream.get("top200_reference_status") == "READY" and hk_close["status"] == "READY")
        return ("DONE" if done else "PARTIAL"), workload, phases

    if phase in {"hk_cache_write", "hk_cache_read"}:
        try:
            if phase == "hk_cache_write":
                workload = write_hk_cache(cfg.data_dir, inputs, asof=observed)
            else:
                entry = inputs.entry("hk_cache")
                workload, _ = read_hk_cache(
                    cfg.data_dir, day, iso_date(entry.get("target_date")), expected_entry=entry, asof=observed,
                )
        except EvidenceError as exc:
            workload = _gap(str(exc))
        return workload["status"], workload, {}

    if phase == "evening":
        hourly = lane_or_gap(cfg, inputs, "hourly_announcements", observed)
        if hourly["status"] == "READY":
            observation = (wait_for_observation(hourly) if wait_for_observation is not None
                           else lane_or_gap(cfg, inputs, "next_day_observation", observed, hourly=hourly))
        else:
            observation = _gap("NEXT_DAY_OBSERVATION_UPSTREAM_COMPLETION_UNVERIFIED")
        status = "DONE" if hourly["status"] == observation["status"] == "READY" else (
            "PARTIAL" if hourly["status"] in {"READY", "PARTIAL"} else "CANNOT_CONFIRM"
        )
        return status, hourly, {"next_day_observation": observation}

    if phase == "review":
        workload = compose_review_core(cfg, inputs, observed, stage_owner_root=stage_owner_root)
        return workload["status"], workload, {}

    raise ValueError(f"Unknown scheduled phase: {phase}")
