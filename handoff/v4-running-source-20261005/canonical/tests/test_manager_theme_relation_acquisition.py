from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from v4.manager_research.research_evidence import (
    structured_us_issuer_relations,
    us_mappings,
    verified_theme_relations,
)
from v4.manager_research.workspace_briefing import build_briefing
from v4.manager_research.workspace_projection import timestamp


CONTEXT = {
    "plan_trade_date": "20260924",
    "market_session": "20260923",
    "focus_window_start": "2026-09-22T16:10:00+08:00",
    "research_cutoff": "2026-09-24T09:27:35.408396+08:00",
}
ISSUER_REF = {"source_id": "FIXTURE_ISSUER_OWNER", "payload_sha256": "a" * 64}
THEME_REF = {"source_id": "FIXTURE_THEME_OWNER", "payload_sha256": "b" * 64}
ACQUIRED = "2026-09-23T08:05:00+08:00"


def _inputs(*, published_at: str = "2026-09-23T07:30:00+08:00",
            available_at: str | None = None, retrieved_at: str | None = None,
            first_seen_at: str | None = ACQUIRED, collected_at: str | None = ACQUIRED):
    theme_material = {
        "material_id": "theme-material-1",
        "published_at": "2026-09-23T08:00:00+08:00",
        "available_at": "2026-09-23T08:01:00+08:00",
        "source_refs": [copy.deepcopy(THEME_REF)],
        "source_row": {
            "evidence_sentence": "AI算力服务器需求提升，相关公司完成订单交付。",
        },
    }
    issuer_evidence = {
        "material_id": "issuer-material-1",
        "published_at": published_at,
        "available_at": available_at,
        "retrieved_at": retrieved_at,
        "first_seen_at": first_seen_at,
        "collected_at": collected_at,
        "source_refs": [copy.deepcopy(ISSUER_REF)],
        "propositions": [{
            "evidence_id": "c" * 64,
            "proposition_id": "d" * 64,
            "symbol": "HK.06166",
            "theme": "AI_COMPUTE",
            "quote": "公司经营AI算力服务器业务。",
            "source_field": "source_row.evidence_sentence",
            "start": 0,
            "end": len("公司经营AI算力服务器业务。"),
            "subject_role": "ISSUER_EVENT",
            "event_type": "ISSUER_RESEARCH",
            "claim_status": "REPORTED_CLAIM",
        }],
    }
    stock = {
        "symbol": "HK.06166",
        "name": "Cambridge Fixture",
        "evidence": [issuer_evidence],
        "plan": {"actions": []},
    }
    us_market = {
        "status": "READY",
        "mapping_eligible": True,
        "captured_at": "2026-09-24T06:30:00+08:00",
        "source_identity": {"status": "VERIFIED", "payload_sha256": "e" * 64},
        "raw_industry_up": [{"label": "AI算力", "status": "READY", "pct_change": 2.0}],
        "raw_individual_up": [],
    }
    return theme_material, stock, issuer_evidence, us_market


def _project_and_extract(theme_material, stock, us_market):
    projected = build_briefing([theme_material], [copy.deepcopy(stock)], CONTEXT)
    relation = next(
        row
        for theme in projected["themes"]
        for row in theme["mappings"]
        if row["symbol"] == "HK.06166"
    )
    start = timestamp(CONTEXT["focus_window_start"])
    cutoff = timestamp(CONTEXT["research_cutoff"])
    extracted = verified_theme_relations(projected["themes"], start, cutoff)
    mapped, individual = us_mappings(us_market, extracted, {})
    return projected, relation, extracted, mapped, individual


def test_production_projection_passes_same_issuer_acquisition_time_to_mapping_gate():
    theme, stock, evidence, us = _inputs()
    projected, relation, extracted, mapped, individual = _project_and_extract(theme, stock, us)

    assert relation["issuer_available_at"] == evidence["first_seen_at"] == ACQUIRED
    assert ISSUER_REF in relation["source_refs"]
    assert relation["issuer_published_at"] == evidence["published_at"]
    assert "HK.06166" in extracted
    assert mapped["HK.06166"][0]["hk_relation"]["issuer_available_at"] == ACQUIRED
    assert mapped["HK.06166"][0]["evidence_lane"] == "US_INDUSTRY_MAPPING"
    assert individual == {}


def test_unknown_issuer_acquisition_time_is_not_borrowed_from_theme_support():
    theme, stock, _, us = _inputs(first_seen_at=None, collected_at=None)
    _, relation, extracted, mapped, _ = _project_and_extract(theme, stock, us)

    assert relation["issuer_available_at"] is None
    assert relation["theme_published_at"] is not None
    assert "HK.06166" not in extracted
    assert mapped == {}


def test_out_of_window_issuer_acquisition_time_is_rejected():
    theme, stock, _, us = _inputs(
        first_seen_at="2026-09-22T15:00:00+08:00",
        collected_at="2026-09-22T15:00:00+08:00",
    )
    _, relation, extracted, mapped, _ = _project_and_extract(theme, stock, us)

    assert relation["issuer_available_at"] == "2026-09-22T15:00:00+08:00"
    assert "HK.06166" not in extracted
    assert mapped == {}


def test_issuer_publication_window_is_checked_separately_from_acquisition_window():
    theme, stock, _, us = _inputs(
        published_at="2026-09-22T15:00:00+08:00",
        first_seen_at=ACQUIRED,
        collected_at=ACQUIRED,
    )
    _, relation, extracted, mapped, _ = _project_and_extract(theme, stock, us)

    assert relation["issuer_available_at"] == ACQUIRED
    assert relation["issuer_published_at"] == "2026-09-22T15:00:00+08:00"
    assert "HK.06166" not in extracted
    assert mapped == {}


def test_frozen_current_payload_remains_zero_after_correct_time_projection():
    frozen_path = Path(
        "/Users/lexi/Downloads/V4_MANAGER_UNIFIED_LOCAL_20260925/controller/"
        "workspace_after_api_switch.json"
    )
    if not frozen_path.exists():
        pytest.skip("local frozen API payload is not available outside the packaged workspace")
    raw = frozen_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "e295a2758250b7b96b35cb448df59962b89b5741922ef7807ff4dbb67fa2dc97"
    )
    payload = json.loads(raw)
    briefing = build_briefing(payload["materials"], copy.deepcopy(payload["stocks"]), payload["plan_context"])
    start = timestamp(payload["plan_context"]["focus_window_start"])
    cutoff = timestamp(payload["plan_context"]["research_cutoff"])
    accepted = verified_theme_relations(briefing["themes"], start, cutoff)
    direct = structured_us_issuer_relations(payload["material_discovery_evidence"]["cards"], start, cutoff)
    industry, individual = us_mappings(payload["us_market_attention"], accepted, direct)

    assert payload["research_attention"]["coverage"]["us_industry_mapped_symbol_count"] == 0
    assert payload["research_attention"]["coverage"]["us_individual_mapped_symbol_count"] == 0
    assert sum(len(rows) for rows in industry.values()) == 0
    assert sum(len(rows) for rows in individual.values()) == 0
