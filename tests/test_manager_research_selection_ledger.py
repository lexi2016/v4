from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
import pytest

from v4.manager_research.research_attention import (
    DEFAULT_CONFIG,
    _score_card,
    build_research_selection_ledger,
)
from v4.manager_research.workspace_plan import _screen_empty
from v4.manager_research.workspace import PLAN_SCHEMA
from v4.manager_research import workspace as workspace_module
from v4.manager_research.workspace_projection import FLAGS, digest


TARGET = "20261002"
SESSION = "20260930"
INPUT_IDENTITY = "a" * 64


def _refs(seed: str = "a"):
    return [
        {
            "owner": "panel-owner",
            "payload_path": "/owner/panel.json",
            "payload_sha256": seed * 64,
            "manifest_path": "/owner/panel.manifest.json",
            "manifest_sha256": "b" * 64,
        },
        {
            "owner": "master-owner",
            "payload_path": "/owner/master.json",
            "payload_sha256": "c" * 64,
            "manifest_path": "/owner/master.manifest.json",
            "manifest_sha256": "d" * 64,
        },
    ]


def _row(code, **extra):
    return {
        "code": code,
        "name": code,
        "target_monday": int(TARGET),
        "verified_session": int(SESSION),
        "qualification_status": "RESEARCH_ONLY_CANDIDATE",
        "source_refs": _refs(),
        **extra,
    }


def _fixture():
    strict = _row(
        "HK.00001",
        classification="STRICT_REBOUND",
        history_status="KNOWN",
        strict_two_gate_oversold_5dvolume=True,
        oversold_flag=True,
        volume_flag_5d_ge_1_5=True,
        reason_for_group="原strict两门均通过；成交额与反弹只作观察",
        close=8.0,
        oversold_cutoff_80pct_prior60_high=8.2,
        volume_ratio_5d=1.7,
    )
    near = _row(
        "HK.00002",
        classification="NEAR_CONDITION",
        history_status="KNOWN",
        strict_two_gate_oversold_5dvolume=False,
        near_two_gate_one_missing=True,
        oversold_flag=True,
        volume_flag_5d_ge_1_5=False,
        near_failed_gate="volume_5d_ratio",
        near_failed_value=1.2,
        near_gate_value=1.5,
        near_gate_gap_ratio=0.2,
        reason_for_group="仅60日超跌通过，前5日量比≥1.5未通过",
        close=8.0,
        oversold_cutoff_80pct_prior60_high=8.2,
        volume_ratio_5d=1.2,
    )
    pending = _row(
        "HK.00003",
        classification=None,
        history_status="PARTIAL_UNKNOWN",
        history_unknown_reasons="PRIOR_60_SESSIONS_INCOMPLETE:57",
        strict_two_gate_oversold_5dvolume=False,
    )
    excluded = _row(
        "HK.00004",
        classification="EXCLUDED_REBOUND_SCREEN",
        history_status="KNOWN",
        screen_decision="EXCLUDED",
        exclusion_reason_code="BOTH_REBOUND_GATES_FAILED",
        reason_for_exclusion="收盘高于超跌门槛且前5日量比低于1.5",
        oversold_flag=False,
        volume_flag_5d_ge_1_5=False,
        close=9.0,
        oversold_cutoff_80pct_prior60_high=8.2,
        volume_ratio_5d=1.2,
    )
    screen = {
        "schema_version": "v4.manager_research.rebound_v3_screen.v1",
        "rule_version": "TEST_REBOUND_SCREEN_V2",
        "target_trade_date": TARGET,
        "verified_session": SESSION,
        "status": "READY_WITH_GAPS",
        "main_screen_ready": True,
        "input_identity": INPUT_IDENTITY,
        "strict": [strict],
        "near": [near],
        "pending": [pending],
        "excluded": [excluded],
        "screen_unresolved": [],
        "cards": [strict, near],
        "gaps": ["SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:HK.00003"],
        "coverage": {
            "input_candidate_count": 4,
            "history_complete_count": 3,
            "history_pending_count": 1,
            "strict_count": 1,
            "near_candidate_count": 1,
            "selected_count": 2,
            "excluded_count": 1,
            "screen_unresolved_count": 0,
            "row_accounted_count": 4,
        },
    }
    cards = [
        _score_card(
            symbol=row["code"], screen=row, stock=None, official=[], company=[],
            us_industry=[], us_individual=[], trend=None, config=DEFAULT_CONFIG,
        )
        for row in (strict, near)
    ]
    return screen, cards


def test_ledger_accounts_for_strict_near_pending_and_excluded_rows_without_changing_inputs():
    screen, cards = _fixture()
    before = deepcopy(screen)

    ledger = build_research_selection_ledger(screen, cards, TARGET)

    assert screen == before
    assert ledger["status"] == "READY_WITH_GAPS"
    assert ledger["coverage"] == {
        "input_row_count": 4,
        "accounted_input_row_count": 4,
        "unique_decision_count": 4,
        "selected_count": 1,
        "near_watch_count": 1,
        "excluded_count": 1,
        "unresolved_count": 1,
        "source_group_counts": {
            "strict": 1,
            "near": 1,
            "pending": 1,
            "excluded": 1,
            "screen_unresolved": 0,
        },
    }
    by_symbol = {row["symbol"]: row for row in ledger["decisions"]}
    assert by_symbol["HK.00001"]["decision_status"] == "SELECTED"
    assert by_symbol["HK.00001"]["research_priority"]["priority_rank"] == 1
    assert by_symbol["HK.00002"]["decision_status"] == "NEAR_WATCH"
    assert by_symbol["HK.00002"]["source_metrics"]["near_failed_value"] == 1.2
    assert by_symbol["HK.00003"]["decision_status"] == "UNRESOLVED"
    assert "PRIOR_60_SESSIONS_INCOMPLETE" in by_symbol["HK.00003"]["decision_reason"]
    assert by_symbol["HK.00004"]["decision_status"] == "EXCLUDED"
    assert by_symbol["HK.00004"]["decision_reason_code"] == "BOTH_REBOUND_GATES_FAILED"
    assert ledger["formal_selection_input"] is False
    assert ledger["universe_exhaustive"] is False


def test_duplicate_and_unverifiable_rows_fail_closed_without_hiding_other_decisions():
    screen, cards = _fixture()
    duplicate = deepcopy(screen["strict"][0])
    duplicate["source_refs"] = []
    screen["strict"].append(duplicate)
    screen["cards"] = [*screen["strict"], *screen["near"]]
    screen["coverage"].update(input_candidate_count=5, history_complete_count=4,
                              strict_count=2, selected_count=3, row_accounted_count=5)
    cards.append(cards[0])

    ledger = build_research_selection_ledger(screen, cards, TARGET)

    by_symbol = {row["symbol"]: row for row in ledger["decisions"]}
    assert by_symbol["HK.00001"]["decision_status"] == "UNRESOLVED"
    assert by_symbol["HK.00001"]["source_row_count"] == 2
    assert by_symbol["HK.00001"]["decision_reason_code"] == "DUPLICATE_REBOUND_SCREEN_SYMBOL"
    assert by_symbol["HK.00002"]["decision_status"] == "NEAR_WATCH"
    assert ledger["coverage"]["accounted_input_row_count"] == 5
    assert "REBOUND_SCREEN_DUPLICATE_SYMBOL:HK.00001" in ledger["gaps"]


def test_target_date_mismatch_turns_rows_unresolved_instead_of_reusing_them():
    screen, cards = _fixture()
    screen["target_trade_date"] = "20261001"

    ledger = build_research_selection_ledger(screen, cards, TARGET)

    assert ledger["status"] == "CANNOT_CONFIRM"
    assert {row["decision_status"] for row in ledger["decisions"]} == {"UNRESOLVED"}
    assert "REBOUND_SCREEN_TARGET_DATE_MISMATCH" in ledger["gaps"]


def test_full_sized_screen_ledger_preserves_689_row_partition_and_existing_priority():
    strict = [
        _row(f"HK.{index:05d}", classification="STRICT_REBOUND", history_status="KNOWN",
             strict_two_gate_oversold_5dvolume=True, oversold_flag=True,
             volume_flag_5d_ge_1_5=True,
             reason_for_group="原strict两门均通过；成交额与反弹只作观察",
             close=8.0, oversold_cutoff_80pct_prior60_high=8.2, volume_ratio_5d=1.7)
        for index in range(1, 59)
    ]
    near = []
    for index in range(59, 408):
        volume_failed = index % 2 == 0
        near.append(_row(
            f"HK.{index:05d}", classification="NEAR_CONDITION", history_status="KNOWN",
            strict_two_gate_oversold_5dvolume=False, near_two_gate_one_missing=True,
            oversold_flag=volume_failed, volume_flag_5d_ge_1_5=not volume_failed,
            near_failed_gate="volume_5d_ratio" if volume_failed else "oversold_close_le_80pct_prior60_high",
            near_failed_value=1.2 if volume_failed else 8.3,
            near_gate_value=1.5 if volume_failed else 8.2,
            reason_for_group="剩余两项准入中仅一项通过，另一项门槛未通过",
            close=8.3 if not volume_failed else 8.0,
            oversold_cutoff_80pct_prior60_high=8.2, volume_ratio_5d=1.2 if volume_failed else 1.7,
        ))
    pending = [
        _row(f"HK.{index:05d}", classification=None, history_status="PARTIAL_UNKNOWN",
             history_unknown_reasons="PRIOR_60_SESSIONS_INCOMPLETE:57",
             strict_two_gate_oversold_5dvolume=False)
        for index in range(408, 440)
    ]
    excluded = [
        _row(f"HK.{index:05d}", classification="EXCLUDED_REBOUND_SCREEN", history_status="KNOWN",
             screen_decision="EXCLUDED", exclusion_reason_code="BOTH_REBOUND_GATES_FAILED",
             reason_for_exclusion="两项严格门均未通过；原筛选排除。",
             oversold_flag=False, volume_flag_5d_ge_1_5=False,
             close=9.0, oversold_cutoff_80pct_prior60_high=8.2, volume_ratio_5d=1.2)
        for index in range(440, 690)
    ]
    screen = {
        "schema_version": "v4.manager_research.rebound_v3_screen.v1",
        "rule_version": "TEST_REBOUND_SCREEN_V2",
        "target_trade_date": TARGET,
        "verified_session": SESSION,
        "status": "READY_WITH_GAPS",
        "main_screen_ready": True,
        "input_identity": INPUT_IDENTITY,
        "strict": strict,
        "near": near,
        "pending": pending,
        "excluded": excluded,
        "screen_unresolved": [],
        "cards": [*strict, *near],
        "gaps": [f"SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:{row['code']}" for row in pending],
        "coverage": {
            "input_candidate_count": 689,
            "history_complete_count": 657,
            "history_pending_count": 32,
            "strict_count": 58,
            "near_candidate_count": 349,
            "selected_count": 407,
            "excluded_count": 250,
            "screen_unresolved_count": 0,
            "row_accounted_count": 689,
        },
    }
    cards = [
        _score_card(
            symbol=row["code"], screen=row, stock=None, official=[], company=[],
            us_industry=[], us_individual=[], trend=None, config=DEFAULT_CONFIG,
        )
        for row in [*strict, *near]
    ]

    ledger = build_research_selection_ledger(screen, cards, TARGET)

    assert ledger["status"] == "READY_WITH_GAPS"
    assert ledger["coverage"]["input_row_count"] == 689
    assert ledger["coverage"]["accounted_input_row_count"] == 689
    assert ledger["coverage"]["unique_decision_count"] == 689
    assert ledger["coverage"]["selected_count"] == 58
    assert ledger["coverage"]["near_watch_count"] == 349
    assert ledger["coverage"]["unresolved_count"] == 32
    assert ledger["coverage"]["excluded_count"] == 250
    by_symbol = {row["symbol"]: row for row in ledger["decisions"]}
    assert by_symbol["HK.00001"]["decision_status"] == "SELECTED"
    assert by_symbol["HK.00407"]["decision_status"] == "NEAR_WATCH"
    assert by_symbol["HK.00408"]["decision_status"] == "UNRESOLVED"
    assert by_symbol["HK.00689"]["decision_status"] == "EXCLUDED"
    assert by_symbol["HK.00689"]["decision_reason_code"] == "BOTH_REBOUND_GATES_FAILED"
    assert by_symbol["HK.00689"]["research_priority"] is None


def test_missing_screen_keeps_all_coverage_unknown_instead_of_zero():
    for screen in (None, _screen_empty({"plan_trade_date": TARGET, "market_session": SESSION},
            ["PLAN_HK_02_EXACT_DATE_PANEL_MISSING"])):
        ledger = build_research_selection_ledger(screen, [], TARGET)

        assert ledger["status"] == "CANNOT_CONFIRM"
        assert ledger["decisions"] == []
        assert "REBOUND_SCREEN_INPUT_NOT_AVAILABLE" in ledger["gaps"]
        if screen:
            assert "PLAN_HK_02_EXACT_DATE_PANEL_MISSING" in ledger["gaps"]
        assert ledger["coverage"] == {
            "input_row_count": None,
            "accounted_input_row_count": None,
            "unique_decision_count": None,
            "selected_count": None,
            "near_watch_count": None,
            "excluded_count": None,
            "unresolved_count": None,
            "source_group_counts": {"strict": None, "near": None, "pending": None, "excluded": None, "screen_unresolved": None},
        }


def test_dynamic_get_current_saved_plan_readback_uses_actual_research_projection(monkeypatch, tmp_path):
    artifact_path = os.environ.get("OCT2_RESEARCH_SELECTION_PROJECTION")
    if not artifact_path:
        pytest.skip("actual Oct 2 projection artifact not supplied")
    with gzip.open(Path(artifact_path), "rt", encoding="utf-8") as source:
        artifact = json.load(source)
    attention = artifact["research_attention"]
    cutoff = artifact["source"]["research_cutoff"]
    current = {
        "target_trade_date": TARGET,
        "semantic_version": "actual-oct2-research-projection",
        "input_identity": attention["input_identity"],
        "plan_context": {"research_cutoff": cutoff},
        "market_screen": artifact["market_screen"],
        "research_attention": attention,
        "selection_diagnostics": {"formal_selection": {"status": "CANNOT_CONFIRM"}},
        "gaps": [],
        "stocks": [], "focus_symbols": [], "lanes": [], "runtime_gaps": [],
        "run_accounting": {}, "continuity_gap": None, "owner_chain": {},
        "market_screen_evidence": {}, "announcement_review": {},
        "announcement_observation": {}, "us_market_attention": {},
        "stage_read_timing": {}, "repair_contract": "READ_ONLY_TEST",
        **FLAGS,
    }
    saved_workspace = deepcopy(current)
    saved_workspace["research_attention"] = {"input_identity": "stale-prior-projection"}
    saved = {
        "schema_version": PLAN_SCHEMA,
        "target_trade_date": TARGET,
        "run_id": "1" * 32,
        "execution_kind": "MANUAL_REFRESH",
        "generated_at": cutoff,
        "workspace": saved_workspace,
        "input_identity": current["input_identity"],
        **FLAGS,
    }
    saved["sha256"] = digest(saved)
    sealed_copy = deepcopy(saved)

    class Store:
        root = tmp_path
        def _read(self, path):
            return deepcopy(saved) if "workspace_plans" in path.parts else None

    store = Store()
    service = SimpleNamespace(store=store)
    calls = []

    def project_dynamic_get(service_arg, date, *, include_saved, context):
        calls.append((date, include_saved, context["plan_trade_date"]))
        return workspace_module._readback_plan(service_arg.store, date, current)

    monkeypatch.setattr(workspace_module, "_compute_workspace", project_dynamic_get)
    result = workspace_module.get_workspace(
        service, TARGET, include_saved=True, view="dynamic",
        now=datetime.fromisoformat("2026-10-04T10:00:00+08:00"),
    )

    assert calls == [(TARGET, True, TARGET)]
    assert result["plan_product"]["status"] == "CURRENT"
    assert result["observation_mode"] == "EXACT_DATE_PLAN_READBACK"
    assert result["research_attention"] == attention
    assert result["research_attention"]["research_selection"]["coverage"]["input_row_count"] == 689
    assert result["market_screen"]["input_identity"] == artifact["source"]["screen_input_identity"]
    assert saved == sealed_copy
