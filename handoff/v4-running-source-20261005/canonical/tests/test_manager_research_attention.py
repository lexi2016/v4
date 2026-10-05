import hashlib
import json
from pathlib import Path
from copy import deepcopy

from v4.manager_research.research_attention import build_research_attention

HERE=Path(__file__).resolve().parent
FIXTURE=HERE/'fixtures'/'manager_20260924_preopen_screen.json'
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


def empty_us():
    return {"schema_version":"v4.manager_research.us_market_bridge.v1","target_trade_date":"20260924",
      "research_cutoff":"2026-09-24T09:27:35.408396+08:00","status":"INPUT_MISSING",
      "expected_us_session":"20260923","coverage_scope":"FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET",
      "raw_industry_up":[],"raw_individual_up":[],"coverage":{},"source_identity":None,
      "mapping_eligible":False,"mapping_ineligible_reasons":["missing"],"gaps":["missing"],**FLAGS}


def test_real_preopen_screen_is_not_mutated_and_top5_remain_near():
    fixture=json.loads(FIXTURE.read_text())
    screen=fixture["market_screen"]
    before=sha(screen)
    out=build_research_attention("20260924",context=fixture["plan_context"],market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    assert sha(screen)==before
    assert len(screen["strict"])==fixture["expected"]["strict_count"]==21
    assert len(screen["near"])==fixture["expected"]["near_count"]==260
    assert out["config"]["display_limit"] == 30
    cards={row["symbol"]:row for row in out["cards"]}
    near={row["code"]:row for row in screen["near"]}
    for symbol,rank in fixture["expected"]["sample_near_ranks"].items():
        assert near[symbol]["classification"]=="NEAR_CONDITION"
        assert near[symbol]["research_priority_rank"]==rank
        assert cards[symbol]["screen_classification"]=="NEAR_CONDITION"
        assert cards[symbol]["original_screen_rank"]==rank


def test_cutoff_bound_official_event_can_raise_a_near_name_without_changing_screen_rank():
    fixture=json.loads(FIXTURE.read_text());screen=fixture["market_screen"]
    announcement={"status":"SUCCEEDED","official_documents":[{
      "event_id":"e"*64,"symbol":"HK.09690","title":"SIMULATED official document",
      "published_at":"2026-09-24T08:14:00+08:00","retrieved_at":"2026-09-24T08:20:00+08:00","available_at":"2026-09-24T08:20:00+08:00",
      "body_status":"BODY_PARSED","document_sha256":"d"*64,"source_url":"https://www.hkexnews.hk/simulated.pdf"
    }]}
    out=build_research_attention("20260924",context=fixture["plan_context"],market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation=announcement,us_market=empty_us())
    card=next(r for r in out["cards"] if r["symbol"]=="HK.09690")
    assert card["screen_classification"]=="NEAR_CONDITION"
    assert card["original_screen_rank"]==185
    assert "OFFICIAL_ANNOUNCEMENT" in card["qualified_lanes"]
    assert card["research_attention_score"] >= 42


def test_after_cutoff_event_does_not_score_and_duplicate_documents_do_not_double_score():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[{"code":"HK.01234","name":"Fixture","classification":"NEAR_CONDITION","research_priority_rank":9,
       "recent_3_session_return_pct":-1,"recent_5_session_return_pct":-2}],"pending":[],"cards":[],"input_identity":"a"*64}
    pre={"event_id":"1"*64,"symbol":"HK.01234","title":"pre","published_at":"2026-09-24T08:00:00+08:00","retrieved_at":"2026-09-24T08:01:00+08:00","available_at":"2026-09-24T08:01:00+08:00","body_status":"BODY_PARSED"}
    post={**pre,"event_id":"2"*64,"title":"post","published_at":"2026-09-24T10:00:00+08:00","retrieved_at":"2026-09-24T10:01:00+08:00","available_at":"2026-09-24T10:01:00+08:00"}
    out=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation={"status":"SUCCEEDED","official_documents":[pre,deepcopy(pre),post]},us_market=empty_us())
    card=out["cards"][0]
    assert card["research_attention_score"]==58  # official 42 + near 6 + cross-lane 10; duplicate does not add a lane
    assert len([e for e in card["evidence"] if e.get("title")=="post"])==0
    assert len([e for e in card["evidence"] if e.get("title")=="pre"])==1


def test_us_industry_mapping_requires_existing_issuer_relation_and_individual_requires_structured_symbol():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[],"pending":[],"cards":[],"input_identity":"a"*64}
    relation={"symbol":"HK.01234","relationship_type":"INDUSTRY_INFERENCE","issuer_quote":"issuer-specific business exposure",
      "issuer_published_at":"2026-09-23T12:00:00+08:00","issuer_available_at":"2026-09-23T12:02:00+08:00","source_refs":[{"payload_sha256":"b"*64}]}
    themes=[{"theme":"AI_COMPUTE","mappings":[relation]}]
    direct={"symbol":"HK.01234","semantic_status":"ACCEPTED","published_at":"2026-09-23T12:00:00+08:00",
      "first_seen_at":"2026-09-23T12:01:00+08:00","source_refs":[{"payload_sha256":"b"*64}],
      "identity_pair_basis":{"us_symbol":"NVDA"}}
    us={**empty_us(),"status":"READY","source_identity":{"status":"VERIFIED","payload_sha256":"a"*64,"receipt_sha256":"b"*64,"manifest_sha256":"c"*64},
       "mapping_eligible":True,"captured_at":"2026-09-24T06:30:00+08:00","raw_industry_up":[{"label":"AI算力","pct_change":3.0,"status":"READY"}],"raw_individual_up":[{"symbol":"NVDA","change_pct":2.0}]}
    mapped=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[direct],themes=themes,announcement_observation={"status":"SUCCEEDED","official_documents":[]},us_market=us)
    card=mapped["cards"][0]
    assert {"US_INDUSTRY_MAPPING","US_INDIVIDUAL_MAPPING"}.issubset(card["qualified_lanes"])
    mapped_us=[row for row in card["evidence"] if row.get("evidence_lane") in {"US_INDUSTRY_MAPPING","US_INDIVIDUAL_MAPPING"}]
    assert mapped_us and all(row.get("available_at")=="2026-09-24T06:30:00+08:00" for row in mapped_us)
    unmapped=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation={"status":"SUCCEEDED","official_documents":[]},us_market=us)
    assert unmapped["cards"]==[]
    assert len(us["raw_industry_up"])==1 and len(us["raw_individual_up"])==1

def test_fresh_material_card_can_raise_broad_screen_name_without_existing_stock_detail():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[{"code":"HK.04567","name":"Broad Pool Only","classification":"NEAR_CONDITION","research_priority_rank":77,
       "recent_3_session_return_pct":0.5,"recent_5_session_return_pct":1.5}],"pending":[],"cards":[],"input_identity":"a"*64}
    card={"symbol":"HK.04567","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
      "published_at":"2026-09-24T08:00:00+08:00","first_seen_at":"2026-09-24T08:05:00+08:00",
      "evidence_id":"m"*64,"source_refs":[{"payload_sha256":"b"*64}],"title":"SIMULATED issuer material"}
    out=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[card],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    row=out["cards"][0]
    assert row["symbol"]=="HK.04567"
    assert row["original_screen_rank"]==77
    assert "COMPANY_MATERIAL" in row["qualified_lanes"]
    assert row["research_attention_score"]==48  # material 24 + near 6 + trend 8 + cross-lane 10

def test_official_event_is_not_globally_gated_by_oversold_screen_membership():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    announcement={"status":"SUCCEEDED","official_documents":[{"event_id":"9"*64,"symbol":"HK.05432","title":"SIMULATED non-screen issuer event",
      "published_at":"2026-09-24T08:00:00+08:00","retrieved_at":"2026-09-24T08:02:00+08:00","available_at":"2026-09-24T08:02:00+08:00","body_status":"BODY_PARSED"}]}
    out=build_research_attention("20260924",context=context,market_screen={"strict":[],"near":[],"pending":[],"cards":[],"input_identity":"a"*64},stocks=[],material_cards=[],themes=[],announcement_observation=announcement,us_market=empty_us())
    assert [row["symbol"] for row in out["cards"]] == ["HK.05432"]
    assert out["cards"][0]["screen_classification"] is None
    assert out["cards"][0]["research_attention_score"] == 42

def test_priority_evidence_expires_by_plan_window_or_configured_lookback():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[{"code":"HK.07890","name":"Expiry Fixture","classification":"NEAR_CONDITION","research_priority_rank":12,
       "recent_3_session_return_pct":-1,"recent_5_session_return_pct":-2}],"pending":[],"cards":[],"input_identity":"a"*64}
    stale={"event_id":"7"*64,"symbol":"HK.07890","title":"stale","published_at":"2026-09-18T08:00:00+08:00",
      "retrieved_at":"2026-09-18T08:01:00+08:00","available_at":"2026-09-18T08:01:00+08:00","body_status":"BODY_PARSED"}
    fresh={**stale,"event_id":"8"*64,"title":"fresh","published_at":"2026-09-24T08:00:00+08:00",
      "retrieved_at":"2026-09-24T08:01:00+08:00","available_at":"2026-09-24T08:01:00+08:00"}
    out=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[],
      announcement_observation={"status":"SUCCEEDED","official_documents":[stale,fresh]},us_market=empty_us())
    row=out["cards"][0]
    assert [e["title"] for e in row["evidence"] if e.get("evidence_lane")=="OFFICIAL_ANNOUNCEMENT"] == ["fresh"]
    assert out["freshness"]["max_evidence_age_hours"] == 120
    assert out["freshness"]["status"] == "PROPOSAL_ONLY"

def test_expired_company_material_is_visible_nowhere_in_attention_score():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[{"code":"HK.01234","name":"Fixture","classification":"NEAR_CONDITION","research_priority_rank":9,
       "recent_3_session_return_pct":-1,"recent_5_session_return_pct":-2}],"pending":[],"cards":[],"input_identity":"a"*64}
    old={"symbol":"HK.01234","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
      "published_at":"2026-09-18T08:00:00+08:00","first_seen_at":"2026-09-18T08:05:00+08:00",
      "evidence_id":"o"*64,"source_refs":[{"payload_sha256":"b"*64}],"title":"SIMULATED stale material"}
    out=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[old],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    row=out["cards"][0]
    assert "COMPANY_MATERIAL" not in row["qualified_lanes"]
    assert all(e.get("title")!="SIMULATED stale material" for e in row["evidence"])
    assert "NO_FRESH_COMPANY_SPECIFIC_MATERIAL" in row["missing"]


def test_stock_evidence_without_published_at_does_not_borrow_acquisition_time_for_freshness():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    stock={"symbol":"HK.01234","name":"Publication-Time Fixture","evidence":[{
      "semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION",
      "retrieved_at":"2026-09-24T08:01:00+08:00","available_at":"2026-09-24T08:02:00+08:00",
      "evidence_id":"p"*64,"source_refs":[{"payload_sha256":"b"*64}],"title":"SIMULATED missing publication time"
    }]}
    out=build_research_attention("20260924",context=context,
      market_screen={"strict":[],"near":[],"pending":[],"cards":[],"input_identity":"a"*64},
      stocks=[stock],material_cards=[],themes=[],
      announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    row=out["cards"][0]
    assert "COMPANY_MATERIAL" not in row["qualified_lanes"]
    assert all(e.get("title")!="SIMULATED missing publication time" for e in row["evidence"])
    assert "NO_FRESH_COMPANY_SPECIFIC_MATERIAL" in row["missing"]


def test_after_cutoff_duplicate_does_not_shadow_pre_cutoff_copy():
    fixture=json.loads(FIXTURE.read_text());screen=fixture["market_screen"];context=fixture["plan_context"]
    late={"event_id":"a"*64,"symbol":"HK.09690","title":"same","published_at":"2026-09-24T10:00:00+08:00","retrieved_at":"2026-09-24T10:01:00+08:00","available_at":"2026-09-24T10:01:00+08:00","body_status":"BODY_PARSED"}
    early={**late,"published_at":"2026-09-24T08:00:00+08:00","retrieved_at":"2026-09-24T08:01:00+08:00","available_at":"2026-09-24T08:01:00+08:00"}
    out=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation={"status":"SUCCEEDED","official_documents":[late,early]},us_market=empty_us())
    card=next(row for row in out["cards"] if row["symbol"]=="HK.09690")
    assert "OFFICIAL_ANNOUNCEMENT" in card["qualified_lanes"]
    docs=[row for row in card["evidence"] if row.get("evidence_lane")=="OFFICIAL_ANNOUNCEMENT"]
    assert len(docs)==1 and docs[0]["published_at"]=="2026-09-24T08:00:00+08:00"


def test_us_hk_mapping_fails_closed_without_both_acquisition_times():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[],"pending":[],"cards":[],"input_identity":"a"*64}
    base_relation={"symbol":"HK.01234","relationship_type":"INDUSTRY_INFERENCE","issuer_quote":"issuer exposure","issuer_published_at":"2026-09-23T12:00:00+08:00","source_refs":[{"payload_sha256":"b"*64}]}
    us={**empty_us(),"status":"READY","mapping_eligible":True,"captured_at":"2026-09-24T06:30:00+08:00","source_identity":{"status":"VERIFIED","payload_sha256":"a"*64,"receipt_sha256":"b"*64,"manifest_sha256":"c"*64},"raw_industry_up":[{"label":"AI算力","pct_change":3.0,"status":"READY"}]}
    missing_hk_acquired=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[{"theme":"AI_COMPUTE","mappings":[base_relation]}],announcement_observation={"status":"SUCCEEDED","official_documents":[]},us_market=us)
    assert missing_hk_acquired["cards"]==[]
    relation={**base_relation,"issuer_available_at":"2026-09-23T12:02:00+08:00"}
    missing_us_acquired=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[],themes=[{"theme":"AI_COMPUTE","mappings":[relation]}],announcement_observation={"status":"SUCCEEDED","official_documents":[]},us_market={**us,"captured_at":None})
    assert missing_us_acquired["cards"]==[]


def test_missing_cutoff_fails_closed_without_attention_cards():
    screen={"strict":[],"near":[{"code":"HK.01234","classification":"NEAR_CONDITION","research_priority_rank":1,"recent_3_session_return_pct":2,"recent_5_session_return_pct":3}],"pending":[],"cards":[],"input_identity":"a"*64}
    out=build_research_attention("20260924",context={},market_screen=screen,stocks=[],material_cards=[],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    assert out["status"]=="CANNOT_CONFIRM"
    assert out["cards"]==[]
    assert "RESEARCH_ATTENTION_CUTOFF_UNVERIFIED" in out["gaps"]


def test_material_evidence_changes_attention_input_identity():
    context={"research_cutoff":"2026-09-24T09:27:35.408396+08:00"}
    screen={"strict":[],"near":[{"code":"HK.01234","classification":"NEAR_CONDITION","research_priority_rank":1}],"pending":[],"cards":[],"input_identity":"a"*64}
    base={"symbol":"HK.01234","semantic_status":"ACCEPTED","temporal_role":"NEW_PLAN_PUBLICATION","published_at":"2026-09-24T08:00:00+08:00","first_seen_at":"2026-09-24T08:01:00+08:00","source_refs":[{"payload_sha256":"b"*64}],"evidence_id":"1"*64,"title":"one"}
    first=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[base],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    second=build_research_attention("20260924",context=context,market_screen=screen,stocks=[],material_cards=[{**base,"evidence_id":"2"*64,"title":"two"}],themes=[],announcement_observation={"status":"NOT_RUN","official_documents":[]},us_market=empty_us())
    assert first["input_identity"] != second["input_identity"]
