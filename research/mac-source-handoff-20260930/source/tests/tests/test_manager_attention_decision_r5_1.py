from v4.manager_research.attention_decision import attention_sort_key, enrich_attention_card


def card(*lanes, classification=None, score=0, lane_count=None):
    return {
        "qualified_lanes": list(lanes),
        "screen_classification": classification,
        "research_attention_score": score,
        "qualified_lane_count": len(lanes) if lane_count is None else lane_count,
        "evidence": [],
    }


def test_company_and_market_is_first_group_even_with_lower_score():
    direct = card("COMPANY_MATERIAL", "STRICT_NEAR_SCREEN", classification="NEAR_CONDITION", score=30)
    market_only = card("STRICT_NEAR_SCREEN", "TREND_CONTINUATION", classification="STRICT_REBOUND", score=90)
    direct["decision"] = enrich_attention_card(direct)
    market_only["decision"] = enrich_attention_card(market_only)
    assert direct["decision"]["state"] == "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION"
    assert market_only["decision"]["state"] == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE"
    assert attention_sort_key(direct) < attention_sort_key(market_only)


def test_company_evidence_without_market_waits_for_confirmation():
    row = card("OFFICIAL_ANNOUNCEMENT", score=42)
    row["evidence"] = [{
        "evidence_lane": "OFFICIAL_ANNOUNCEMENT",
        "evidence_class": "OFFICIAL_PARSED_DOCUMENT",
        "body_status": "BODY_PARSED",
    }]
    decision = enrich_attention_card(row)
    assert decision["state"] == "COMPANY_EVIDENCE_WAIT_MARKET"
    assert decision["company_evidence_strength"] == 3
    assert decision["market_confirmation_strength"] == 0
    assert "不因事件本身升级" in decision["summary"]


def test_parsed_company_material_does_not_upgrade_unreadable_official_document():
    row = card("OFFICIAL_ANNOUNCEMENT", "COMPANY_MATERIAL", score=42)
    row["evidence"] = [
        {
            "evidence_lane": "OFFICIAL_ANNOUNCEMENT",
            "evidence_class": "OFFICIAL_DIRECTORY_ONLY",
            "body_status": "BODY_UNREADABLE",
        },
        {
            "evidence_lane": "COMPANY_MATERIAL",
            "evidence_class": "VERIFIED_COMPANY_SPECIFIC_MATERIAL",
            "body_status": "BODY_PARSED",
        },
    ]
    decision = enrich_attention_card(row)
    assert decision["state"] == "COMPANY_EVIDENCE_WAIT_MARKET"
    assert decision["company_evidence_strength"] == 2


def test_market_only_never_becomes_company_catalyst():
    row = card("STRICT_NEAR_SCREEN", classification="STRICT_REBOUND", score=10)
    decision = enrich_attention_card(row)
    assert decision["state"] == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE"
    assert "公司公告" in decision["next_check"]
    assert decision["formal_rank_writeback"] is False
    assert decision["stage_writeback"] is False
    assert decision["buy_gate_writeback"] is False


def test_verified_us_only_stays_context_only():
    row = card("US_INDIVIDUAL_MAPPING", score=24)
    decision = enrich_attention_card(row)
    assert decision["state"] == "CONTEXT_ONLY"
    assert "不能替代" in decision["summary"]


def test_no_evidence_stays_insufficient_and_does_not_fabricate_zero_success():
    decision = enrich_attention_card(card(score=0))
    assert decision["state"] == "INSUFFICIENT"
    assert decision["group_order"] == 4
    assert decision["why_now_readable"] == []


def test_existing_score_is_preserved_not_recomputed():
    row = card("COMPANY_MATERIAL", "STRICT_NEAR_SCREEN", classification="STRICT_REBOUND", score=44)
    before = dict(row)
    decision = enrich_attention_card(row)
    assert row == before
    assert decision["research_priority_key"][1] == -44


def test_existing_score_is_the_secondary_order_inside_each_evidence_state():
    lower = card("COMPANY_MATERIAL", score=24)
    higher = card("COMPANY_MATERIAL", score=42)
    lower["decision"] = enrich_attention_card(lower)
    higher["decision"] = enrich_attention_card(higher)
    assert lower["decision"]["state"] == higher["decision"]["state"]
    assert attention_sort_key(higher) < attention_sort_key(lower)
