"""Focused regressions for B04 pure-helper phase boundaries."""
from __future__ import annotations

import copy

import pytest

import infrastructure.research_store as research_store
from infrastructure._research_store_parts.overlay_successor import (
    _b04_validate_successor_source_records,
)
from infrastructure.stage_acquisition_universe_contracts import (
    STRICT_POOL_SNAPSHOT_AUTHORITY,
    StageAcquisitionContractError,
    StrictAPreselectionSnapshot,
    VerifiedPoolSnapshot,
    build_strict_stage_acquisition_universe,
    validate_strict_stage_acquisition_artifact,
)
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract


def _strict_ready_artifact() -> dict:
    trade_date = "20260911"
    code = "A.000001"
    digest = "a" * 64
    pools = []
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        status, producer_id, source_role = a_pool_contract(pool_id)
        pools.append(
            VerifiedPoolSnapshot(
                pool_id=pool_id,
                trade_date=trade_date,
                artifact={
                    "status": status,
                    "producer_id": producer_id,
                    "source_role": source_role,
                    "rows": [{"symbol": code}],
                },
                manifest={},
                receipt={},
                artifact_relative_path=(
                    f"preselection_pools/{trade_date}/{pool_id}.json"
                ),
                manifest_relative_path=(
                    f"preselection_pools/{trade_date}/manifest.json"
                ),
                receipt_relative_path=(
                    f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
                ),
                artifact_raw_sha256=digest,
                manifest_raw_sha256=digest,
                receipt_raw_sha256=digest,
                pool_sha256=digest,
            )
        )
    snapshot = StrictAPreselectionSnapshot(
        trade_date=trade_date,
        pools=tuple(pools),
        codes=(code,),
        code_sources={code: tuple(REQUIRED_A_STAGE_POOL_IDS)},
        a_all_pool_rows=({"symbol": code},),
        pool_diagnostics={pool_id: () for pool_id in REQUIRED_A_STAGE_POOL_IDS},
        pool_contribution_counts={pool_id: 1 for pool_id in REQUIRED_A_STAGE_POOL_IDS},
    )
    artifact = build_strict_stage_acquisition_universe(snapshot)
    assert artifact["authority"] == STRICT_POOL_SNAPSHOT_AUTHORITY
    return artifact


def test_strict_artifact_valid_physical_snapshot_survives_helper_split() -> None:
    artifact = _strict_ready_artifact()
    assert validate_strict_stage_acquisition_artifact(artifact) == "20260911"


def test_strict_artifact_keeps_preflight_rejections_after_helper_split() -> None:
    with pytest.raises(StageAcquisitionContractError, match="must be an object"):
        validate_strict_stage_acquisition_artifact([])
    with pytest.raises(StageAcquisitionContractError, match="authority must be"):
        validate_strict_stage_acquisition_artifact({})

    artifact = _strict_ready_artifact()
    invalid_cases = (
        ({"trade_date": "20260931"}, "trade date is invalid"),
        ({"status": "PARTIAL"}, "must be READY"),
        ({"source_projection_status": "PARTIAL"}, "not READY_WITH_ROWS"),
        ({"blocking_reasons": ["BLOCKED"]}, "blocking_reasons must be empty"),
    )
    for updates, expected_message in invalid_cases:
        candidate = {**artifact, **updates}
        with pytest.raises(StageAcquisitionContractError, match=expected_message):
            validate_strict_stage_acquisition_artifact(candidate)


def _successor_source_context() -> dict:
    ticker = "600000.SH"
    candidate_id = "SH.600000|600000.SH"
    card = {
        "ticker": ticker,
        "candidate_id": candidate_id,
        "event_id": "event-600000",
        "entity": ticker,
        "market": "A",
    }
    base_supply = {"frozen_payload": {"event_cards": [copy.deepcopy(card)]}}
    successor_supply = {"frozen_payload": {"event_cards": [copy.deepcopy(card)]}}
    record = {
        "candidate_id": candidate_id,
        "ticker": ticker,
        "before_card_sha": research_store.ResearchSelectionStore._canonical_sha(card),
        "after_card_sha": research_store.ResearchSelectionStore._canonical_sha(card),
        "changed_paths": [],
    }
    proof = {
        "records": [record],
        "candidate_ids": [candidate_id],
        "envelope_changed_paths": [],
    }
    return {
        "proof": proof,
        "candidate_ids": [candidate_id],
        "base_supply": base_supply,
        "successor_supply": successor_supply,
        "base_cards": {ticker: card},
        "successor_cards": {ticker: card},
    }


def test_successor_source_records_use_cards_bound_in_phase_context() -> None:
    context = _successor_source_context()
    _b04_validate_successor_source_records(
        vars(research_store), research_store.ResearchSelectionStore, context
    )


def test_successor_source_records_keep_card_sha_rejection() -> None:
    context = _successor_source_context()
    context["proof"]["records"][0]["before_card_sha"] = "0" * 64
    with pytest.raises(ValueError, match="proof before card SHA mismatch"):
        _b04_validate_successor_source_records(
            vars(research_store), research_store.ResearchSelectionStore, context
        )
