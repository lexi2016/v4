from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from contracts.research_day_product import (
    MANAGER_DECISION_PHASE,
    MANAGER_DECISION_SCHEMA_VERSION,
    MANAGER_DECISION_STATE,
    RESEARCH_SUPPLY_PHASE,
    RESEARCH_SUPPLY_SCHEMA_VERSION,
    RESEARCH_SUPPLY_TYPE,
    validate_manager_research_decision,
)


SOURCE_DATE = "20260828"
TARGET_DATE = "20260831"
RUN_ID = "recovery-contract-test"
SHA = "a" * 64
SAFETY = {
    "RESEARCH_ONLY": True,
    "WATCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _supply_envelope(
    *,
    generated_at: str = "2026-08-28T22:00:00+08:00",
    cutoff_at: str = "2026-08-28T22:00:00+08:00",
) -> dict[str, object]:
    frozen_payload = {
        "route_status": {key: "READY" for key in ("R1", "R2", "R3", "R4", "R5", "R6")},
        "source_receipts": [],
        "event_cards": [],
        "core_research_candidates": [],
        "conditional_watch_candidates": [],
        "KEEP": [],
        "ADD": [],
        "REMOVE": [],
        "safety": SAFETY,
    }
    return {
        "type": RESEARCH_SUPPLY_TYPE,
        "schema_version": RESEARCH_SUPPLY_SCHEMA_VERSION,
        "owner": "baimao-researcher",
        "phase": RESEARCH_SUPPLY_PHASE,
        "run_id": RUN_ID,
        "source_date": SOURCE_DATE,
        "target_trade_date": TARGET_DATE,
        "generated_at": generated_at,
        "coverage_started_at": cutoff_at,
        "coverage_through": cutoff_at,
        "cutoff_at": cutoff_at,
        "frozen_payload": frozen_payload,
        "frozen_payload_sha256": _canonical_sha(frozen_payload),
    }


def _decision(
    *,
    generated_at: str = "2026-08-28T22:30:00+08:00",
    cutoff_at: str = "2026-08-28T22:00:00+08:00",
    supply: dict[str, object] | None = None,
) -> dict[str, object]:
    supply = supply or _supply_envelope()
    return {
        "schema_version": MANAGER_DECISION_SCHEMA_VERSION,
        "phase": MANAGER_DECISION_PHASE,
        "decision_state": MANAGER_DECISION_STATE,
        "source_date": SOURCE_DATE,
        "target_trade_date": TARGET_DATE,
        "run_id": RUN_ID,
        "generated_at": generated_at,
        "cutoff_at": cutoff_at,
        "supply_ref": {
            "path": "/tmp/supply.json",
            "raw_sha256": SHA,
            "frozen_payload_sha256": supply["frozen_payload_sha256"],
            "run_id": RUN_ID,
        },
        "baseline_ref": None,
        "core": [],
        "conditional": [],
        "KEEP": [],
        "ADD": [],
        "REMOVE": [],
        "qualification_refs": [],
        "safety": deepcopy(SAFETY),
    }


def _validate(decision: dict[str, object], supply: dict[str, object] | None = None) -> str:
    return validate_manager_research_decision(
        decision,
        candidate_ids=[],
        supply_envelope=supply or _supply_envelope(),
    )


def test_same_source_date_decision_remains_valid() -> None:
    assert _validate(_decision()) == TARGET_DATE


def test_post_source_recovery_before_target_is_valid() -> None:
    decision = _decision(generated_at="2026-08-29T09:00:00+08:00")

    assert _validate(decision) == TARGET_DATE


def test_post_source_recovery_uses_hkt_day_boundaries() -> None:
    # 16:00 UTC is 00:00 HKT on the day after source_date, still before target.
    decision = _decision(generated_at="2026-08-28T16:00:00Z")

    assert _validate(decision) == TARGET_DATE


def test_generated_at_before_supply_remains_rejected() -> None:
    decision = _decision(
        generated_at="2026-08-28T21:30:00+08:00",
        cutoff_at="2026-08-28T21:00:00+08:00",
    )

    with pytest.raises(ValueError, match="predates supply envelope"):
        _validate(decision)


@pytest.mark.parametrize(
    "generated_at",
    [
        "2026-08-31T00:00:00+08:00",
        "2026-08-31T09:00:00+08:00",
    ],
)
def test_target_day_start_and_later_remain_rejected(generated_at: str) -> None:
    decision = _decision(generated_at=generated_at)

    with pytest.raises(ValueError, match="generated_at source date mismatch"):
        _validate(decision)


def test_cutoff_stays_on_source_date_and_not_before_supply_cutoff() -> None:
    post_source = _decision(generated_at="2026-08-29T09:00:00+08:00")
    post_source["cutoff_at"] = "2026-08-29T00:00:00+08:00"
    with pytest.raises(ValueError, match="cutoff source date mismatch"):
        _validate(post_source)

    before_supply_cutoff = _decision(
        generated_at="2026-08-29T09:00:00+08:00",
        cutoff_at="2026-08-28T21:59:00+08:00",
    )
    with pytest.raises(ValueError, match="cutoff predates supply coverage"):
        _validate(before_supply_cutoff)


@pytest.mark.parametrize("action_field", ["core", "conditional"])
def test_source_target_run_supply_and_safety_constraints_remain_strict(
    action_field: str,
) -> None:
    source_mismatch = _decision()
    source_mismatch["source_date"] = "20260827"
    source_mismatch["generated_at"] = "2026-08-27T22:30:00+08:00"
    source_mismatch["cutoff_at"] = "2026-08-27T21:00:00+08:00"
    with pytest.raises(ValueError, match="supply source date mismatch"):
        _validate(source_mismatch)

    target_mismatch = _decision()
    target_mismatch["target_trade_date"] = "20260901"
    with pytest.raises(ValueError, match="supply target date mismatch"):
        _validate(target_mismatch)

    run_mismatch = _decision()
    run_mismatch["run_id"] = "other-run"
    with pytest.raises(ValueError, match="supply run_id mismatch"):
        _validate(run_mismatch)

    supply_ref_mismatch = _decision()
    supply_ref_mismatch["supply_ref"] = {
        **supply_ref_mismatch["supply_ref"],  # type: ignore[misc]
        "run_id": "other-run",
    }
    with pytest.raises(ValueError, match="supply run binding mismatch"):
        _validate(supply_ref_mismatch)

    unsafe = _decision()
    unsafe["safety"] = {**SAFETY, "production_allowed": True}
    with pytest.raises(ValueError, match="unsafe manager decision safety boundary"):
        _validate(unsafe)

    too_many = _decision()
    too_many[action_field] = [
        {"candidate_id": f"HK.0000{i}|0000{i}.HK", "reason": "test"}
        for i in range(6)
    ]
    with pytest.raises(ValueError, match=f"{action_field} exceeds maximum size"):
        _validate(too_many)
