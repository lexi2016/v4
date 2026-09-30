from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from tests.r3_scoped_loader import install as _install_scoped
_install_scoped()

from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.research_evidence import company_evidence
from v4.manager_research.evidence_identity import acquired_at, event_identity, merge_event_rows
from v4.manager_research.recommendation import derive_investment_advice

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def empty_us():
    return {
        "schema_version":"v4.manager_research.us_market_bridge.v1",
        "target_trade_date":"20260925",
        "research_cutoff":"2026-09-25T08:59:30+08:00",
        "status":"INPUT_MISSING","raw_industry_up":[],"raw_individual_up":[],
        "coverage":{},"mapping_eligible":False,"mapping_ineligible_reasons":["missing"],
        "gaps":["missing"],**FLAGS,
    }


def test_duplicate_company_event_merges_provenance_and_uses_existing_acquisition_time():
    base = {
        "symbol":"HK.03317","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
        "published_at":"2026-09-24T09:00:00+08:00","first_seen_at":"2026-09-24T10:00:00+08:00",
        "source_url":"https://example.test/report","title":"JPM report",
        "source_excerpt":"same issuer event","source_refs":[{"payload_sha256":"a"*64}],
    }
    rows=[]
    for idx in range(3):
        row={**base,"evidence_id":str(idx+1)*64,"source_refs":[{"payload_sha256":chr(97+idx)*64}]}
        rows.append(row)
    result=company_evidence([],rows,__import__('datetime').datetime.fromisoformat('2026-09-23T08:59:30+08:00'),__import__('datetime').datetime.fromisoformat('2026-09-25T08:59:30+08:00'))
    assert len(result["HK.03317"]) == 1
    merged=result["HK.03317"][0]
    assert merged["acquired_at"] == "2026-09-24T10:00:00+08:00"
    assert merged["provenance_count"] == 3
    assert len(merged["source_refs"]) == 3
    assert len(merged["merged_provenance"]) == 3


def test_score_explanation_reconciles_cross_lane_bonus_exactly():
    context={"research_cutoff":"2026-09-25T08:59:30+08:00"}
    screen={"strict":[{"code":"HK.03317","name":"迅策","classification":"STRICT_REBOUND","research_priority_rank":1,
        "recent_3_session_return_pct":1.0,"recent_5_session_return_pct":2.0}],"near":[],"pending":[],"cards":[],"input_identity":"a"*64}
    material={"symbol":"HK.03317","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
        "published_at":"2026-09-24T09:00:00+08:00","first_seen_at":"2026-09-24T10:00:00+08:00",
        "source_url":"https://example.test/r","title":"report","source_excerpt":"issuer evidence","source_refs":[{"payload_sha256":"b"*64}]}
    out=build_research_attention("20260925",context=context,market_screen=screen,stocks=[],material_cards=[material],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    card=out["cards"][0]
    assert card["research_attention_score"] == 52  # material24 + strict10 + trend8 + cross10
    assert sum(row["points"] for row in card["score_components"]) == card["research_attention_score"]
    assert {row["component"] for row in card["score_components"]} >= {"COMPANY_MATERIAL","STRICT_NEAR_SCREEN","TREND_CONTINUATION","CROSS_LANE_BONUS"}
    assert "CROSS_LANE_BONUS:10" in card["why_now"]


def test_missing_profit_or_operating_cashflow_downgrades_research_opinion_not_stage_or_buy():
    evidence={
        "fact_count":2,"comparable_count":2,"positive_count":2,"negative_count":0,
        "missing_dimensions":["PROFIT_LOSS","OPERATING_CASHFLOW"],"conflict_dimensions":[],
        "adverse_dimensions":[],"negative_dimensions":[],"evidence_grade":"B",
        "dimensions":{
            "revenue":{"dimension":"REVENUE","state":"POSITIVE","current":"120","previous":"100","period":"H1"},
            "gross":{"dimension":"GROSS_PROFIT","state":"POSITIVE","current":"50","previous":"40","period":"H1"},
        },
    }
    result=derive_investment_advice(evidence,market_snapshot={"price":1,"volume":1,"support":1,"pressure":2})
    assert result["action"] == "DATA_INSUFFICIENT"
    assert result["status"] == "NOT_GENERATED"
    assert "PROFIT_LOSS" in result["missing_dimensions"] and "OPERATING_CASHFLOW" in result["missing_dimensions"]


def test_us_zero_mapping_is_not_hidden_and_bridge_semantics_are_not_full_market_claims():
    from v4.manager_research.us_market_bridge import _empty
    row=_empty("20260925","2026-09-25T08:59:30+08:00",status="INPUT_MISSING",gaps=["x"],expected_session="20260924")
    assert row["coverage_scope"] == "FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET"
    assert row["raw_industry_up"] == [] and row["raw_individual_up"] == []
    assert row["selection_semantics"] == "POSITIVE_CHANGE_GT_ZERO_NOT_LARGE_GAIN_SCREEN"
    assert row["mapping_diagnostics"]["accepted_hk_mapping_count"] is None
    assert row["mapping_diagnostics"]["status"] == "NOT_COMPUTED_BY_BRIDGE"

def test_us_mapping_diagnostics_explain_zero_without_relaxing_relation_gate():
    from v4.manager_research.research_evidence import collect_attention_evidence
    us={**empty_us(),"status":"READY","mapping_eligible":True,"captured_at":"2026-09-25T06:00:00+08:00",
        "raw_industry_up":[{"label":"AI算力","pct_change":2.1,"status":"READY"}],
        "raw_individual_up":[{"symbol":"NVDA","change_pct":3.2}],"source_identity":{"status":"VERIFIED"}}
    e=collect_attention_evidence(market_screen={"strict":[],"near":[],"cards":[]},stocks=[],material_cards=[],themes=[],
        announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=us,
        start=__import__('datetime').datetime.fromisoformat('2026-09-24T00:00:00+08:00'),
        cutoff=__import__('datetime').datetime.fromisoformat('2026-09-25T08:59:30+08:00'))
    diag=e.us_mapping_diagnostics
    assert diag["accepted_hk_mapping_count"]==0
    assert diag["industry"][0]["reason"]=="NO_CUTOFF_BOUND_HK_ISSUER_RELATION"
    assert diag["individual"][0]["reason"]=="NO_STRUCTURED_HK_US_RELATION"


def test_company_evidence_fails_closed_when_any_acquisition_clock_is_after_cutoff():
    row={
        "symbol":"HK.00001","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
        "published_at":"2026-09-24T09:00:00+08:00",
        "available_at":"2026-09-24T10:00:00+08:00",
        "retrieved_at":"2026-09-24T10:01:00+08:00",
        "first_seen_at":"2026-09-26T08:00:00+08:00",
        "collected_at":"2026-09-24T10:02:00+08:00",
        "archive_recorded_at":"2026-09-24T10:03:00+08:00",
        "source_url":"https://example.test/report","title":"same issuer event",
        "source_excerpt":"same issuer event","source_refs":[{"payload_sha256":"a"*64}],
    }
    start=datetime.fromisoformat("2026-09-23T00:00:00+08:00")
    cutoff=datetime.fromisoformat("2026-09-25T20:44:11+08:00")
    assert company_evidence([], [row], start, cutoff)=={}


def test_acquired_at_uses_first_owner_observation_instead_of_minimum_of_unlike_clocks():
    row={
        "available_at":"2026-09-24T09:55:00+08:00",
        "retrieved_at":"2026-09-24T09:59:00+08:00",
        "first_seen_at":"2026-09-24T10:00:00+08:00",
        "collected_at":"2026-09-24T10:05:00+08:00",
        "archive_recorded_at":"2026-09-24T10:09:00+08:00",
    }
    assert acquired_at(row)=="2026-09-24T10:00:00+08:00"


def test_event_identity_preserves_url_path_case_but_normalizes_scheme_and_host_case():
    row={"published_at":"2026-09-24T09:00:00+08:00","title":"Issuer result",
         "source_excerpt":"Company reports two agreements"}
    mixed_case={**row,"source_url":"HTTPS://EXAMPLE.TEST/Report/A.pdf"}
    normalized_host={**row,"source_url":"https://example.test/Report/A.pdf"}
    different_path_case={**row,"source_url":"https://example.test/report/a.pdf"}
    assert event_identity("HK.00001",mixed_case)==event_identity("HK.00001",normalized_host)
    assert event_identity("HK.00001",mixed_case)!=event_identity("HK.00001",different_path_case)
    merged=merge_event_rows("HK.00001",[mixed_case,normalized_host,different_path_case])
    assert len(merged)==2


def test_us_rejected_mover_count_is_per_raw_mover_not_unique_hk_symbol_count():
    context={"research_cutoff":"2026-09-25T08:59:30+08:00"}
    relation={"symbol":"HK.01234","relationship_type":"INDUSTRY_INFERENCE",
        "issuer_quote":"issuer-specific business exposure",
        "issuer_published_at":"2026-09-24T10:00:00+08:00",
        "issuer_available_at":"2026-09-24T10:01:00+08:00",
        "issuer_retrieved_at":"2026-09-24T10:02:00+08:00",
        "source_refs":[{"payload_sha256":"b"*64}]}
    us={**empty_us(),"status":"READY","mapping_eligible":True,
        "captured_at":"2026-09-25T06:00:00+08:00",
        "source_identity":{"status":"VERIFIED","payload_sha256":"a"*64,
            "receipt_sha256":"b"*64,"manifest_sha256":"c"*64},
        "raw_industry_up":[
            {"label":"AI算力","pct_change":3.0,"status":"READY"},
            {"label":"CPO","pct_change":2.0,"status":"READY"},
            {"label":"机器人","pct_change":1.0,"status":"READY"},
        ]}
    out=build_research_attention("20260925",context=context,
        market_screen={"strict":[],"near":[],"pending":[],"cards":[],"input_identity":"a"*64},
        stocks=[],material_cards=[],themes=[{"theme":"AI_COMPUTE","mappings":[relation]}],
        announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=us)
    coverage=out["coverage"]
    diagnostics=out["us_mapping_diagnostics"]["industry"]
    assert coverage["raw_us_industry_up_count"]==3
    assert coverage["us_industry_mapped_symbol_count"]==1
    assert [row["accepted_mapping_count"] for row in diagnostics]==[1,1,0]
    assert coverage["us_mapping_rejected_industry_count"]==1
