from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from v4.manager_research import store as store_module
from v4.manager_research import workspace as workspace_owner
from v4.manager_research.us_mapping_research import (
    CURRENT_RELATION_EVIDENCE_PATH,
    CURRENT_RELATION_REVIEW_PATH,
    attach_current_relation_evidence,
)
from v4.manager_research.workspace_projection import (
    build_workspace,
    digest,
    identity_component,
    timestamp,
)


TARGET_DATE = "20261012"
SAVED_CUTOFF = "2026-10-12T03:18:19.084242+08:00"
RELOAD_CUTOFF = "2026-10-12T03:32:31.526271+08:00"
SCREEN_SOURCE_SHA = "1" * 64
US_SOURCE_SHA = "2" * 64
PLAN_RUN_ID = "a" * 32
FIXED_RESEARCH_ATTENTION_ID = "b" * 64
FIXED_ANNOUNCEMENT_INPUT_ID = "c" * 64


def _screen(
    cutoff: str,
    *,
    target_date: str = TARGET_DATE,
    source_sha: str = SCREEN_SOURCE_SHA,
    rows: list[dict] | None = None,
    decision_identity: str = "d" * 64,
) -> dict:
    cards = deepcopy(rows) if rows is not None else [
        {
            "code": "00001",
            "classification": "STRICT_REBOUND",
            "close": 10.0,
            "source_refs": [{"payload_sha256": source_sha}],
        }
    ]
    return {
        "schema_version": "v4.manager_research.rebound_screen.v1",
        "rule_version": "REBOUND_V3",
        "target_trade_date": target_date,
        "verified_session": "20261009",
        "status": "READY_WITH_GAPS",
        "cards": cards,
        "strict": deepcopy(cards),
        "near": [],
        "pending": [],
        "excluded": [],
        "screen_unresolved": [],
        "decision_identity": decision_identity,
        "gaps": ["SYNTHETIC_SOURCE_GAP"],
        "coverage": {"strict_count": len(cards), "near_count": 0},
        "input_identity": "e" * 64,
        "authority": {
            "panel_witness": {
                "owner": "SYNTHETIC_TEST_FIXTURE",
                "payload_sha256": source_sha,
                "panel_manifest_sha256": "f" * 64,
            }
        },
        "data_context": {
            "plan_trade_date": target_date,
            "planning_market_session": "20261009",
            "market_session": "20261009",
            "market_session_close": "2026-10-09T16:00:00+08:00",
            "screen_target_trade_date": target_date,
            "screen_phase": "PREOPEN_COMPLETED_SESSION",
            "screen_session_policy": "COMPLETED_FULL_HK_SECURITIES_SESSION",
            "screen_calendar_sha256": "0" * 64,
            "screen_session_status": "EXPECTED_COMPLETED_SESSION_NOT_DATA_VERIFICATION",
            "research_cutoff": cutoff,
        },
        "main_screen_ready": True,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _relation_symbols() -> list[str]:
    artifact = json.loads(CURRENT_RELATION_EVIDENCE_PATH.read_bytes())
    return sorted(
        {
            str(item["us_symbol"])
            for item in [*artifact.get("relations", []), *artifact.get("symbol_assessments", [])]
            if isinstance(item, dict) and item.get("us_symbol")
        }
    )


def _bridge(
    cutoff: str,
    *,
    target_date: str = TARGET_DATE,
    source_sha: str = US_SOURCE_SHA,
) -> dict:
    return {
        "status": "READY",
        "target_trade_date": target_date,
        "expected_us_session": "20261009",
        "research_cutoff": cutoff,
        "source_identity": {"status": "VERIFIED", "payload_sha256": source_sha},
        "symbol_assessments": [
            {"symbol": symbol, "quote_status": "VERIFIED"}
            for symbol in _relation_symbols()
        ],
    }


def _workspace_product(
    cutoff: str,
    *,
    target_date: str = TARGET_DATE,
    screen_source_sha: str = SCREEN_SOURCE_SHA,
    screen_rows: list[dict] | None = None,
    screen_decision: str = "d" * 64,
    us_source_sha: str = US_SOURCE_SHA,
) -> dict:
    screen = _screen(
        cutoff,
        target_date=target_date,
        source_sha=screen_source_sha,
        rows=screen_rows,
        decision_identity=screen_decision,
    )
    projection = build_workspace(
        target_date,
        catalyst={"status": "EMPTY", "target_trade_date": target_date, "cards": [], "gaps": []},
        market_screen=screen,
        plan_context={
            "plan_trade_date": target_date,
            "research_cutoff": cutoff,
            "market_session": "20261009",
            "planning_market_session": "20261009",
            "market_session_close": "2026-10-09T16:00:00+08:00",
            "screen_phase": "PREOPEN_COMPLETED_SESSION",
            "screen_calendar_sha256": "0" * 64,
        },
    )

    # Match the existing production identity composition for the projection,
    # research attention, announcement input, and current US-relation identity.
    # The two unrelated extensions stay fixed so the test isolates the changed
    # source components without invoking any live owner or request path.
    us_market = attach_current_relation_evidence(
        _bridge(cutoff, target_date=target_date, source_sha=us_source_sha)
    )
    relation_evidence = us_market["relation_evidence"]
    base_identity = projection["input_identity"]
    components = projection["input_identity_components"]
    components["gated_projection"] = identity_component(base_identity)
    components["us_relation_evidence"] = identity_component(
        relation_evidence["assessment_identity"],
        sources=[deepcopy(dict(relation_evidence))],
    )
    projection["us_market_attention"] = us_market
    projection["input_identity"] = digest(
        [
            base_identity,
            FIXED_RESEARCH_ATTENTION_ID,
            FIXED_ANNOUNCEMENT_INPUT_ID,
            relation_evidence["assessment_identity"],
        ]
    )
    return projection


def _save_readback_fixture(tmp_path: Path, product: dict):
    store = store_module.ManagerResearchStore(tmp_path)
    target_date = product["target_trade_date"]
    generated_at = product["plan_context"]["research_cutoff"]
    generated = datetime.fromisoformat(generated_at)
    row = {
        "schema_version": workspace_owner.PLAN_SCHEMA,
        "target_trade_date": target_date,
        "run_id": PLAN_RUN_ID,
        "generated_at": generated_at,
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "execution_kind": "MANUAL_REFRESH",
        "input_identity": product["input_identity"],
        "workspace": deepcopy(product),
        "read_contract_sha256": "f" * 64,
        **workspace_owner.FLAGS,
    }
    row["sha256"] = digest({key: value for key, value in row.items() if key != "sha256"})
    store._write_atomic(
        store.root / "workspace_plans" / target_date / "latest.json",
        row,
    )

    attempt = {
        "schema_version": workspace_owner.ATTEMPT_SCHEMA,
        "target_trade_date": target_date,
        "run_id": PLAN_RUN_ID,
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "state": "SUCCEEDED_EMPTY",
        "execution_kind": "MANUAL_REFRESH",
        "input_identity": product["input_identity"],
        "started_at": (generated - timedelta(seconds=1)).isoformat(),
        "finished_at": (generated + timedelta(seconds=1)).isoformat(),
        "failure_reasons": [],
        **workspace_owner.FLAGS,
    }
    attempt = workspace_owner.seal_attempt(attempt)
    attempt_root = store.root / "workspace_plan_runs" / target_date
    store._write_atomic(attempt_root / (PLAN_RUN_ID + ".json"), attempt)
    store._write_atomic(attempt_root / "latest.json", attempt)
    return store


def _readback(store, product: dict) -> dict:
    read_at = datetime.fromisoformat(product["plan_context"]["research_cutoff"])
    return workspace_owner._readback_plan(
        store,
        TARGET_DATE,
        deepcopy(product),
        read_at=read_at,
    )


def test_same_sources_and_eligibility_remain_current_after_dynamic_reload(tmp_path):
    saved = _workspace_product(SAVED_CUTOFF)
    fresh = _workspace_product(RELOAD_CUTOFF)

    assert saved["market_screen"]["data_context"]["research_cutoff"] == SAVED_CUTOFF
    assert fresh["market_screen"]["data_context"]["research_cutoff"] == RELOAD_CUTOFF
    assert saved["us_market_attention"]["research_cutoff"] == SAVED_CUTOFF
    assert fresh["us_market_attention"]["research_cutoff"] == RELOAD_CUTOFF
    assert saved["market_screen"]["data_context"] != fresh["market_screen"]["data_context"]
    assert (
        saved["us_market_attention"]["relation_evidence"]
        == fresh["us_market_attention"]["relation_evidence"]
    )
    assert saved["input_identity"] == fresh["input_identity"]

    store = _save_readback_fixture(tmp_path, saved)
    reloaded = _readback(store, fresh)
    assert reloaded["plan_product"]["status"] == "CURRENT"
    assert reloaded["plan_product"]["consumed"] is True
    assert reloaded["plan_product"]["run_id"] == PLAN_RUN_ID
    assert reloaded["plan_context"]["research_cutoff"] == SAVED_CUTOFF
    assert reloaded["market_screen"]["data_context"]["research_cutoff"] == RELOAD_CUTOFF
    assert reloaded["us_market_attention"]["research_cutoff"] == RELOAD_CUTOFF


@pytest.mark.parametrize(
    "change",
    ["screen_source_sha", "screen_rows", "screen_decision", "us_source_sha", "target_date"],
)
def test_real_source_row_decision_or_date_changes_still_fail_closed(tmp_path, change):
    saved = _workspace_product(SAVED_CUTOFF)
    store = _save_readback_fixture(tmp_path, saved)
    kwargs = {}
    target_date = TARGET_DATE
    if change == "screen_source_sha":
        kwargs["screen_source_sha"] = "7" * 64
    elif change == "screen_rows":
        kwargs["screen_rows"] = [
            {
                "code": "00001",
                "classification": "STRICT_REBOUND",
                "close": 11.0,
                "source_refs": [{"payload_sha256": SCREEN_SOURCE_SHA}],
            }
        ]
    elif change == "screen_decision":
        kwargs["screen_decision"] = "8" * 64
    elif change == "us_source_sha":
        kwargs["us_source_sha"] = "9" * 64
    elif change == "target_date":
        target_date = "20261013"

    changed = _workspace_product(RELOAD_CUTOFF, target_date=target_date, **kwargs)
    assert changed["input_identity"] != saved["input_identity"]
    reloaded = _readback(store, changed)
    assert reloaded["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert reloaded["plan_product"]["consumed"] is False


def test_actual_available_at_crossings_change_cutoff_result_and_saved_identity(tmp_path):
    artifact = json.loads(CURRENT_RELATION_EVIDENCE_PATH.read_bytes())
    review = json.loads(CURRENT_RELATION_REVIEW_PATH.read_bytes())
    card = artifact["relations"][0]
    source_available_at = timestamp(card["available_at"])
    review_available_at = timestamp(review["reviewed_at"])
    assert source_available_at is not None
    assert review_available_at is not None
    effective_available_at = max(source_available_at, review_available_at)

    before_source = (source_available_at - timedelta(seconds=1)).isoformat()
    after_source = (source_available_at + timedelta(seconds=1)).isoformat()
    before_source_projection = attach_current_relation_evidence(_bridge(before_source))[
        "relation_evidence"
    ]
    after_source_projection = attach_current_relation_evidence(_bridge(after_source))[
        "relation_evidence"
    ]
    assert (
        before_source_projection["post_cutoff_relation_count"]
        > after_source_projection["post_cutoff_relation_count"]
    )
    assert (
        before_source_projection["assessment_identity"]
        != after_source_projection["assessment_identity"]
    )

    before_review = (effective_available_at - timedelta(seconds=1)).isoformat()
    after_review = (effective_available_at + timedelta(seconds=1)).isoformat()
    before_review_projection = attach_current_relation_evidence(_bridge(before_review))[
        "relation_evidence"
    ]
    after_review_projection = attach_current_relation_evidence(_bridge(after_review))[
        "relation_evidence"
    ]
    assert before_review_projection["current_reviewed_relation_count"] == 0
    assert after_review_projection["current_reviewed_relation_count"] > 0
    assert (
        before_review_projection["assessment_identity"]
        != after_review_projection["assessment_identity"]
    )

    saved = _workspace_product(before_review)
    changed = _workspace_product(after_review)
    assert changed["input_identity"] != saved["input_identity"]
    store = _save_readback_fixture(tmp_path, saved)
    reloaded = _readback(store, changed)
    assert reloaded["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert reloaded["plan_product"]["consumed"] is False
