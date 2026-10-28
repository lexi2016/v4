"""Focused contract checks for the R5 change without needing the full V4 runtime."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest


def _timestamp(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _load_isolated_attention_module():
    package_name = "v4.manager_research"
    importlib.import_module(package_name)
    projection_name = f"{package_name}.workspace_projection"
    evidence_name = f"{package_name}.research_evidence"
    missing = object()
    prior_projection = sys.modules.get(projection_name, missing)
    prior_evidence = sys.modules.get(evidence_name, missing)

    projection = types.ModuleType(projection_name)
    projection.FLAGS = {
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    projection.timestamp = _timestamp
    projection.digest = _digest
    evidence = types.ModuleType(evidence_name)
    evidence.US_LABEL_TO_MANAGER_THEMES = {}
    evidence.collect_attention_evidence = lambda **_: None
    sys.modules[projection_name] = projection
    sys.modules[evidence_name] = evidence
    module_path = Path(__file__).resolve().parents[1] / "v4" / "manager_research" / "research_attention.py"
    name = f"{package_name}._r5_attention_contract_isolated"
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("R5_ISOLATED_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
        if prior_projection is missing:
            sys.modules.pop(projection_name, None)
        else:
            sys.modules[projection_name] = prior_projection
        if prior_evidence is missing:
            sys.modules.pop(evidence_name, None)
        else:
            sys.modules[evidence_name] = prior_evidence
    return module


research_attention_module = _load_isolated_attention_module()
ResearchAttentionConfig = research_attention_module.ResearchAttentionConfig
_rejected_raw_mover_count = research_attention_module._rejected_raw_mover_count
_score_card = research_attention_module._score_card


def test_existing_44_point_explanation_is_preserved_but_decision_is_state_first():
    row = _score_card(
        symbol="HK.TEST",
        screen={"classification": "STRICT_REBOUND", "research_priority_rank": 7, "name": "测试"},
        stock={},
        official=[],
        company=[{"published_at": "2026-09-25T08:00:00+08:00", "acquired_at": "2026-09-25T08:05:00+08:00"}],
        us_industry=[],
        us_individual=[],
        trend=None,
        config=ResearchAttentionConfig(),
    )
    assert row["research_attention_score"] == 44  # 24 + 10 + cross-lane 10
    assert row["score_reconciled"] is True
    assert row["decision"]["state"] == "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION"
    assert row["original_screen_rank"] == 7
    assert row["decision"]["formal_rank_writeback"] is False


def test_publication_and_acquisition_clocks_are_not_collapsed():
    row = _score_card(
        symbol="HK.TIME",
        screen=None,
        stock={},
        official=[],
        company=[
            {
                "published_at": "2026-09-25T08:00:00+08:00",
                "acquired_at": "2026-09-25T12:00:00+08:00",
            },
            {
                "published_at": "2026-09-25T09:30:00+08:00",
                "acquired_at": "2026-09-25T09:31:00+08:00",
            },
        ],
        us_industry=[],
        us_individual=[],
        trend=None,
        config=ResearchAttentionConfig(),
    )
    assert row["freshest_published_at"].startswith("2026-09-25T09:30:00")
    assert row["freshest_acquired_at"].startswith("2026-09-25T12:00:00")
    assert row["freshest_evidence_at"].startswith("2026-09-25T12:00:00")


def test_rebased_r5_preserves_r3_rejected_raw_mover_semantics():
    raw = [{"id": 1}, {"id": 2}, {"id": 3}]
    diagnostics = [
        {"accepted_mapping_count": 2},
        {"accepted_mapping_count": 0},
        {"accepted_mapping_count": 0},
    ]
    assert _rejected_raw_mover_count(raw, diagnostics) == 2


def test_published_and_system_capture_clocks_remain_separate_when_published_time_is_unknown():
    row = _score_card(
        symbol="HK.CLOCK",
        screen=None,
        stock={},
        official=[],
        company=[],
        us_industry=[],
        us_individual=[],
        trend={"captured_at": "2026-09-25T12:00:00+08:00"},
        config=ResearchAttentionConfig(),
    )
    assert row["freshest_published_at"] is None
    assert row["freshest_acquired_at"] == "2026-09-25T12:00:00+08:00"


def test_build_orders_research_by_state_then_score_without_mutating_source_arrays(monkeypatch):
    company_row = {
        "published_at": "2026-09-25T08:00:00+08:00",
        "acquired_at": "2026-09-25T08:05:00+08:00",
        "source_refs": [{"payload_sha256": "a" * 64}],
    }
    trend_row = {"available_at": "2026-09-25T08:06:00+08:00"}
    screen_rows = {
        "HK.MKT": {"classification": "STRICT_REBOUND", "research_priority_rank": 1, "reason_for_group": "fixture"},
        "HK.CO": {"classification": None, "research_priority_rank": 2, "reason_for_group": "fixture"},
    }
    company_rows = {"HK.CO": [company_row]}
    trend_rows = {"HK.MKT": trend_row}
    source = {
        "screen_rows": screen_rows,
        "company_rows": company_rows,
        "trend_rows": trend_rows,
        "company_row": company_row,
        "trend_row": trend_row,
    }
    before = deepcopy(source)
    collected = SimpleNamespace(
        symbols=["HK.MKT", "HK.CO"],
        screen_rows=screen_rows,
        stock_rows={},
        official={},
        company=company_rows,
        us_industry={},
        us_individual={},
        trend=trend_rows,
        us_mapping_diagnostics={"industry": [], "individual": []},
    )
    monkeypatch.setattr(research_attention_module, "collect_attention_evidence", lambda **_: collected)
    screen = {"strict": [{"code": "HK.MKT"}], "near": []}
    materials = [company_row]
    themes = [{"mappings": [{"symbol": "HK.CO"}]}]
    input_before = deepcopy((screen, materials, themes))
    result = research_attention_module.build_research_attention(
        "20260925",
        context={"research_cutoff": "2026-09-25T09:40:00+08:00"},
        market_screen=screen,
        stocks=[],
        material_cards=materials,
        themes=themes,
        announcement_observation={"status": "SUCCEEDED", "official_documents": []},
        us_market={"status": "INPUT_MISSING", "raw_industry_up": [], "raw_individual_up": []},
    )
    assert source == before
    assert (screen, materials, themes) == input_before
    assert result["cards"][0]["symbol"] == "HK.CO"
    assert result["cards"][0]["research_attention_score"] == 24
    assert result["cards"][1]["symbol"] == "HK.MKT"
    assert result["cards"][1]["research_attention_score"] == 28
    assert result["cards"][0]["decision"]["state"] == "COMPANY_EVIDENCE_WAIT_MARKET"
    assert result["cards"][1]["decision"]["state"] == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE"
    assert result["strict_near_unchanged"] is True
    assert result["stage_unchanged"] is True
