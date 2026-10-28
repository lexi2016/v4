from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.data_store import NativeDataStore, _canonical_bytes
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.stage_acquisition_universe_contracts import (
    StageAcquisitionContractError,
    _semantic_sha,
    read_strict_a_preselection_snapshot,
    validate_artifact_against_snapshot,
    validate_strict_stage_acquisition_artifact,
)
from infrastructure.stage_acquisition_universe_commit import (
    EvidenceIdentity,
    StrictCommitError,
    _validate_artifact,
)
from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
from stage_center.acquisition import SourceResult, build_plan
from stage_center.candidate_input import read_candidate_input
from stage_center.consumer import StageSelectionConsumer
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract
from stage_center.live_collectors import production_selection_builders
from stage_center.raw_store import publish_raw_artifact
from stage_center.runner import _with_candidate_evidence
from stage_center.selection import SelectionStore


TRADE_DATE = "20260911"
BROKEN_POOL = "a_d1_fupan_watchlist_pool"


def _pool_payload(pool_id: str, codes: list[str]) -> dict:
    status, producer_id, source_role = a_pool_contract(pool_id)
    rows = [
        {"pool_id": pool_id, "symbol": code, "market": "A"}
        for code in codes
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": TRADE_DATE,
        "target_date": TRADE_DATE,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A",
        "status": status,
        "producer_id": producer_id,
        "source_role": source_role,
        "source_path": f"fixture/{TRADE_DATE}/{pool_id}.json",
        "source_sha256": hashlib.sha256(
            f"source:{TRADE_DATE}:{pool_id}".encode()
        ).hexdigest(),
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_released_materialize_lock(root: Path) -> None:
    lock_path = root / "preselection_pools" / ".materialize.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "v3_5_interprocess_lock.v1",
        "pid": 2147483647,
        "token": "RELEASED",
    }
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, separators=(",", ":")))


def _raw_row(code: str, index: int) -> dict:
    return {
        "batch_index": index,
        "code": code,
        "name": f"SYNTHETIC_{code}",
        "update_time": f"2026-09-11 09:35:00",
        "last_price": 10.1,
        "open_price": 10.0,
        "high_price": 10.2,
        "low_price": 9.9,
        "prev_close_price": 10.0,
        "turnover": 1_000_000.0,
        "volume": 10_000.0,
        "bid_price": 10.0,
        "ask_price": 10.1,
        "bid_vol": 100.0,
        "ask_vol": 100.0,
        "window_start": "2026-09-11 09:30:00",
        "window_end": "2026-09-11 09:35:00",
        "bar_count": 1,
        "temporal_cutoff_safe": True,
    }


def _safe_consumer_response_summary(payload: dict) -> dict:
    """Expose response shape/status on failure without serializing row data."""
    return {
        "keys": sorted(payload),
        "status": payload.get("status"),
        "selection_status": payload.get("selection_status"),
        "source_status": payload.get("source_status"),
        "cannot_confirm_count": len(payload.get("cannot_confirm") or []),
        "row_count": len(payload.get("rows") or []),
        "row_action_levels": sorted(
            {str(row.get("action_level")) for row in payload.get("rows") or []}
        ),
        "source_evidence_present": "source_evidence" in payload,
    }


def _selection_row(code: str, index: int) -> dict:
    return {
        **_raw_row(code, index),
        "acquisition_rank": index,
    }


def test_locked_a_pool_gap_flows_through_candidate_and_selection_readback(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "physical-pools"
    candidate_root = tmp_path / "candidate"
    pool_store = PreselectionPoolStore(source_root)
    a_codes = [f"A.{index:06d}" for index in range(1, 206)]
    pool_codes = {
        REQUIRED_A_STAGE_POOL_IDS[0]: a_codes,
        BROKEN_POOL: ["A.000901"],
        REQUIRED_A_STAGE_POOL_IDS[2]: ["A.000206"],
        REQUIRED_A_STAGE_POOL_IDS[3]: ["A.000207"],
        REQUIRED_A_STAGE_POOL_IDS[4]: ["A.000208"],
        REQUIRED_A_STAGE_POOL_IDS[5]: ["A.000209"],
    }
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        pool_store.materialize(_pool_payload(pool_id, pool_codes[pool_id]))
    _write_released_materialize_lock(source_root)

    manifest_path = source_root / f"preselection_pools/{TRADE_DATE}/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[BROKEN_POOL] = "0" * 64
    manifest_path.write_bytes(_canonical_bytes(manifest))

    published_candidate = materialize_stage_acquisition_universe(
        candidate_root,
        TRADE_DATE,
        preselection_source_root=source_root,
        run_id="r8-pool-gap-canary",
        release_id="r8-pool-gap-test",
    )
    candidate = read_candidate_input(candidate_root, TRADE_DATE)
    assert published_candidate["status"] == "READY"
    assert len(candidate.codes) == len(set(candidate.codes))
    assert len(candidate.codes) == 209
    assert len(candidate.codes) > 200
    assert "A.000208" in candidate.codes  # Baimao pool contributes.
    assert "A.000209" in candidate.codes  # WeChat pool contributes.
    assert "A.000901" not in candidate.codes  # Corrupt sibling is quarantined.
    broken_reasons = dict(candidate.pool_diagnostics)[BROKEN_POOL]
    assert broken_reasons
    with pytest.raises(TypeError):
        candidate.source_pool_provenance[0]["status"] = "FORGED"

    plan = build_plan(candidate_root, TRADE_DATE, "STAGE_0930_0935", candidate=candidate)
    rows = tuple(_selection_row(code, index) for index, code in enumerate(plan.codes_for("A_SHARE"), 1))
    collected = SourceResult(
        source_id="SYNTHETIC_STAGE_POOL_CANARY",
        status="READY",
        rows=rows,
        requested_rows=len(rows),
        source_evidence=("synthetic_quote_input=true",),
    )
    source = _with_candidate_evidence(
        collected,
        candidate,
        candidate_sha=candidate.current_sha256,
        candidate_run_id=candidate.run_id,
    )
    assert len(source.rows) == 209
    assert source.status == "CANNOT_CONFIRM"
    assert any(reason.startswith(f"{BROKEN_POOL}:") for reason in source.cannot_confirm)
    assert any(
        item == f"candidate_source_pool_id={REQUIRED_A_STAGE_POOL_IDS[4]}"
        for item in source.source_evidence
    )
    assert any(
        item == f"candidate_source_pool_id={REQUIRED_A_STAGE_POOL_IDS[5]}"
        for item in source.source_evidence
    )

    raw = publish_raw_artifact(
        tmp_path / "raw",
        trade_date=TRADE_DATE,
        stage_id="STAGE_0930_0935",
        market="A_SHARE",
        source_id=source.source_id,
        source_status=source.status,
        rows=source.rows,
        cannot_confirm=source.cannot_confirm,
        source_evidence=source.source_evidence,
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        window="09:30-09:35",
        cutoff_at="09:35:05",
    )
    assert raw["status"] == "CANNOT_CONFIRM"

    import stage_center.research_context as research_context

    monkeypatch.setattr(
        research_context,
        "load_research_context",
        lambda *args, **kwargs: SimpleNamespace(
            by_code={}, source_evidence=("synthetic_empty_research_context=true",), cannot_confirm=()
        ),
    )
    builder_raw = {**raw, "_v4_research_data_root": tmp_path / "research"}
    envelope = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        source, plan, builder_raw
    )
    assert envelope["source_status"] == "CANNOT_CONFIRM"
    assert envelope["selection_status"] != "READY"
    assert envelope["source_rows"] == 209
    assert envelope["selected_rows"] <= 10
    assert all(row["action_level"] == "WATCH_ONLY" for row in envelope["rows"])
    evidence = set(envelope["source_evidence"])
    assert f"candidate_source_pool_provenance_sha256={candidate.source_pool_provenance_sha256}" in evidence
    broken_provenance = next(
        item for item in candidate.source_pool_provenance if item["pool_id"] == BROKEN_POOL
    )
    assert f"candidate_source_pool_status={broken_provenance['status']}" in evidence
    assert any(
        item.startswith(f"candidate_source_pool_diagnostic={BROKEN_POOL}:")
        for item in evidence
    )
    for pool_id in (REQUIRED_A_STAGE_POOL_IDS[4], REQUIRED_A_STAGE_POOL_IDS[5]):
        provenance = next(item for item in candidate.source_pool_provenance if item["pool_id"] == pool_id)
        assert f"candidate_source_pool_sha256={provenance['pool_sha256']}" in evidence
        assert f"candidate_source_pool_artifact_raw_sha256={provenance['artifact_raw_sha256']}" in evidence

    selection_store = SelectionStore(tmp_path / "selection")
    selection_store.publish(envelope, market="A_SHARE")
    readback = selection_store.read_verified(TRADE_DATE, "STAGE_0930_0935", "A_SHARE")
    assert readback["selection_status"] == envelope["selection_status"]
    assert readback["source_status"] == "CANNOT_CONFIRM"
    assert readback["rows"] == envelope["rows"]
    assert all(row["action_level"] == "WATCH_ONLY" for row in readback["rows"])
    assert f"candidate_source_pool_provenance_sha256={candidate.source_pool_provenance_sha256}" in readback["source_evidence"]

    consumer = StageSelectionConsumer(tmp_path / "selection").get(
        TRADE_DATE,
        "STAGE_0930_0935",
        markets=("A_SHARE",),
    )
    consumed_a = consumer["markets"]["A_SHARE"]
    assert consumed_a["source_status"] == "CANNOT_CONFIRM"
    assert consumed_a["selection_status"] != "READY"
    assert any(reason.startswith(f"{BROKEN_POOL}:") for reason in consumed_a["cannot_confirm"])
    assert all(row["action_level"] == "WATCH_ONLY" for row in consumed_a["rows"])
    assert "source_evidence" in consumed_a, json.dumps(
        _safe_consumer_response_summary(consumed_a), sort_keys=True
    )
    assert f"candidate_source_pool_provenance_sha256={candidate.source_pool_provenance_sha256}" in consumed_a["source_evidence"]


def test_rejected_available_a_pool_stays_unavailable_through_selection_readback(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "physical-pools-available-rejected"
    candidate_root = tmp_path / "candidate-available-rejected"
    pool_store = PreselectionPoolStore(source_root)
    valid_empty_pool = REQUIRED_A_STAGE_POOL_IDS[0]
    sibling_codes = {
        pool_id: [f"A.{index:06d}"]
        for index, pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS, 1)
        if pool_id not in {BROKEN_POOL, valid_empty_pool}
    }
    rejected_code = "A.009901"
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        if pool_id == BROKEN_POOL:
            codes = [rejected_code]
        elif pool_id == valid_empty_pool:
            codes = []
        else:
            codes = sibling_codes[pool_id]
        payload = _pool_payload(pool_id, codes)
        if pool_id == BROKEN_POOL:
            payload["status"] = "AVAILABLE"
        elif pool_id == valid_empty_pool:
            payload["status"] = "VALID_EMPTY"
        pool_store.materialize(payload)
    _write_released_materialize_lock(source_root)

    published_candidate = materialize_stage_acquisition_universe(
        candidate_root,
        TRADE_DATE,
        preselection_source_root=source_root,
        run_id="r8-rejected-available-canary",
        release_id="r8-rejected-available-test",
    )
    candidate = read_candidate_input(candidate_root, TRADE_DATE)
    assert published_candidate["status"] == "READY"
    assert len(candidate.codes) == len(REQUIRED_A_STAGE_POOL_IDS) - 2
    for pool_id, codes in sibling_codes.items():
        assert codes[0] in candidate.codes
    assert rejected_code not in candidate.codes

    rejected = next(
        item for item in candidate.source_pool_provenance
        if item["pool_id"] == BROKEN_POOL
    )
    assert rejected["status"] == "CANNOT_CONFIRM"
    assert rejected["diagnostics"]
    assert any(reason.startswith("SOURCE_REJECTED:") for reason in rejected["diagnostics"])
    assert rejected["pool_sha256"]
    assert rejected["artifact_raw_sha256"]
    assert rejected["manifest_raw_sha256"]
    assert rejected["receipt_raw_sha256"]
    assert dict(candidate.pool_diagnostics)[BROKEN_POOL]
    valid_empty = next(
        item for item in candidate.source_pool_provenance
        if item["pool_id"] == valid_empty_pool
    )
    assert valid_empty["status"] == "VALID_EMPTY"
    assert valid_empty["row_count"] == 0
    assert valid_empty["available"] is True
    assert valid_empty["valid_empty"] is True
    assert valid_empty_pool in published_candidate["artifact"]["available_pool_ids"]
    assert BROKEN_POOL not in published_candidate["artifact"]["available_pool_ids"]

    plan = build_plan(candidate_root, TRADE_DATE, "STAGE_0930_0935", candidate=candidate)
    rows = tuple(
        _selection_row(code, index)
        for index, code in enumerate(plan.codes_for("A_SHARE"), 1)
    )
    collected = SourceResult(
        source_id="SYNTHETIC_REJECTED_AVAILABLE_CANARY",
        status="READY",
        rows=rows,
        requested_rows=len(rows),
        source_evidence=("synthetic_quote_input=true",),
    )
    source = _with_candidate_evidence(
        collected,
        candidate,
        candidate_sha=candidate.current_sha256,
        candidate_run_id=candidate.run_id,
    )
    assert len(source.rows) == len(sibling_codes)
    assert source.status == "CANNOT_CONFIRM"
    assert any(reason.startswith(f"{BROKEN_POOL}:") for reason in source.cannot_confirm)
    assert any(
        item.startswith(f"candidate_source_pool_diagnostic={BROKEN_POOL}:")
        for item in source.source_evidence
    )
    assert (
        f"candidate_source_pool_sha256={rejected['pool_sha256']}"
        in source.source_evidence
    )

    raw = publish_raw_artifact(
        tmp_path / "raw-available-rejected",
        trade_date=TRADE_DATE,
        stage_id="STAGE_0930_0935",
        market="A_SHARE",
        source_id=source.source_id,
        source_status=source.status,
        rows=source.rows,
        cannot_confirm=source.cannot_confirm,
        source_evidence=source.source_evidence,
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        window="09:30-09:35",
        cutoff_at="09:35:05",
    )
    assert raw["status"] == "CANNOT_CONFIRM"

    import stage_center.research_context as research_context

    monkeypatch.setattr(
        research_context,
        "load_research_context",
        lambda *args, **kwargs: SimpleNamespace(
            by_code={}, source_evidence=("synthetic_empty_research_context=true",), cannot_confirm=()
        ),
    )
    envelope = production_selection_builders("STAGE_0930_0935")["A_SHARE"](
        source, plan, {**raw, "_v4_research_data_root": tmp_path / "research-available-rejected"}
    )
    assert envelope["source_status"] == "CANNOT_CONFIRM"
    assert envelope["selection_status"] != "READY"
    assert envelope["source_rows"] == len(sibling_codes)
    assert envelope["selected_rows"] <= 10
    assert all(row["action_level"] == "WATCH_ONLY" for row in envelope["rows"])
    selection_store = SelectionStore(tmp_path / "selection-available-rejected")
    selection_store.publish(envelope, market="A_SHARE")
    readback = selection_store.read_verified(TRADE_DATE, "STAGE_0930_0935", "A_SHARE")
    assert readback["source_status"] == "CANNOT_CONFIRM"
    assert all(row["action_level"] == "WATCH_ONLY" for row in readback["rows"])
    readback_evidence = set(readback["source_evidence"])
    assert f"candidate_source_pool_provenance_sha256={candidate.source_pool_provenance_sha256}" in readback_evidence
    assert f"candidate_source_pool_status={rejected['status']}" in readback_evidence
    assert f"candidate_source_pool_sha256={rejected['pool_sha256']}" in readback_evidence
    assert f"candidate_source_pool_artifact_raw_sha256={rejected['artifact_raw_sha256']}" in readback_evidence
    assert any(
        item.startswith(f"candidate_source_pool_diagnostic={BROKEN_POOL}:")
        for item in readback_evidence
    )
    consumed = StageSelectionConsumer(tmp_path / "selection-available-rejected").get(
        TRADE_DATE, "STAGE_0930_0935", markets=("A_SHARE",)
    )["markets"]["A_SHARE"]
    assert consumed["source_status"] == "CANNOT_CONFIRM"
    assert consumed["selection_status"] != "READY"
    assert all(row["action_level"] == "WATCH_ONLY" for row in consumed["rows"])
    assert any(reason.startswith(f"{BROKEN_POOL}:") for reason in consumed["cannot_confirm"])
    assert "source_evidence" in consumed, json.dumps(
        _safe_consumer_response_summary(consumed), sort_keys=True
    )
    assert (
        f"candidate_source_pool_provenance_sha256={candidate.source_pool_provenance_sha256}"
        in consumed["source_evidence"]
    )

    # The physical rejected AVAILABLE lane cannot be projected as accepted
    # availability or a valid empty result.  The explicit VALID_EMPTY sibling
    # above keeps its existing availability and empty-lane semantics.
    assert (rejected["available"], rejected["valid_empty"]) == (False, False)

    artifact = published_candidate["artifact"]
    assert validate_strict_stage_acquisition_artifact(artifact) == TRADE_DATE
    identity = EvidenceIdentity.from_mapping(artifact)
    _validate_artifact(artifact, TRADE_DATE, identity)
    snapshot = read_strict_a_preselection_snapshot(
        NativeDataStore(source_root), TRADE_DATE
    )

    def rejected_variant(change):
        variant = deepcopy(artifact)
        item = next(
            row for row in variant["source_pool_provenance"]
            if row["pool_id"] == BROKEN_POOL
        )
        change(item)
        variant["source_pool_provenance_sha256"] = _semantic_sha(
            variant["source_pool_provenance"]
        )
        variant["pool_diagnostics"][BROKEN_POOL] = list(item["diagnostics"])
        variant["cannot_confirm"] = [
            "{}:{}".format(pool["pool_id"], reason)
            for pool in variant["source_pool_provenance"]
            for reason in pool["diagnostics"]
        ]
        return variant

    rejected_bindings = (
        lambda item: item.update(pool_sha256="invalid"),
        lambda item: item.update(producer_id=""),
        lambda item: item.update(source_role=""),
        lambda item: item["diagnostics"].remove("SOURCE_STATUS_REJECTED:AVAILABLE"),
        lambda item: item["diagnostics"].__setitem__(
            slice(None),
            [reason for reason in item["diagnostics"] if not reason.startswith("SOURCE_REJECTED:")],
        ),
        lambda item: item.update(row_count=1),
        lambda item: item.update(status="FAILED"),
        lambda item: item.update(available=True),
        lambda item: item.update(valid_empty=True),
    )
    for change in rejected_bindings:
        malformed = rejected_variant(change)
        with pytest.raises(StageAcquisitionContractError):
            validate_strict_stage_acquisition_artifact(malformed)
        with pytest.raises(StrictCommitError):
            _validate_artifact(malformed, TRADE_DATE, identity)

    mismatched_physical_sha = rejected_variant(
        lambda item: item.update(pool_sha256="0" * 64)
    )
    # A syntactically valid but substituted hash still cannot be rebound to
    # the exact-date physical snapshot that authorized publication.
    assert validate_strict_stage_acquisition_artifact(mismatched_physical_sha) == TRADE_DATE
    with pytest.raises(StageAcquisitionContractError):
        validate_artifact_against_snapshot(mismatched_physical_sha, snapshot)
