"""Four-state US relation assessment and Connect-input separation contracts."""
from v4.manager_research.research_evidence import us_mapping_diagnostics
from v4.manager_research.workspace import (
    _research_relation_material_cards,
    _research_relation_material_input,
)


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def material_input(*, complete, status=None, pre=1, post=1, relation=None, gaps=None):
    return {
        **FLAGS,
        "status": status or ("READY" if complete else "PARTIAL"),
        "complete": complete,
        "source_material_record_count": pre,
        "pre_connect_material_card_count": pre,
        "post_connect_material_card_count": post,
        "research_relation_material_card_count": pre if relation is None else relation,
        "connect_rejection_count": pre - post,
        "target_connect_scope_status": "OWNER_VERIFIED",
        "target_connect_membership_counts": {"CANNOT_CONFIRM": pre - post} if pre > post else {},
        "connect_rejection_reasons": {"TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED": pre - post} if pre > post else {},
        "gaps": gaps or [],
        "input_identity": "a" * 64,
        "relation_use": "RESEARCH_ONLY_NOT_FORMAL_SELECTION_FOCUS_OR_BUY",
    }


def assessment(market, *, material_count, industry=None, individual=None):
    return us_mapping_diagnostics(
        market, {}, {}, industry or {}, individual or {}, material_count=material_count,
    )


def ready_market(*, complete, status="READY"):
    return {
        **FLAGS,
        "status": status,
        "mapping_eligible": status == "READY",
        "gaps": [] if status == "READY" else ["US_MARKET_SNAPSHOT_NOT_READY"],
        "research_material_input": material_input(complete=complete),
        "raw_industry_up": [],
        "raw_individual_up": [],
    }


def test_not_evaluated_keeps_count_null_when_market_snapshot_is_missing():
    market = ready_market(complete=True, status="CANNOT_CONFIRM")
    out = assessment(market, material_count=1)
    assert out["assessment_state"] == "NOT_EVALUATED"
    assert out["accepted_hk_mapping_count"] is None
    assert "US_MARKET_SNAPSHOT_NOT_READY" in out["assessment_reasons"]


def test_insufficient_inputs_do_not_turn_a_zero_candidate_scan_into_a_zero_result():
    out = assessment(ready_market(complete=False), material_count=1)
    assert out["assessment_state"] == "INSUFFICIENT"
    assert out["accepted_hk_mapping_count"] is None
    assert "MATERIAL_INPUT_COMPLETENESS_UNVERIFIED" in out["assessment_reasons"]


def test_assessed_zero_requires_complete_material_and_market_inputs():
    out = assessment(ready_market(complete=True), material_count=1)
    assert out["assessment_state"] == "ASSESSED_ZERO"
    assert out["accepted_hk_mapping_count"] == 0
    assert "NO_QUALIFIED_RELATION_AFTER_COMPLETE_TWO_SOURCE_PIT_EVALUATION" in out["assessment_reasons"]


def test_positive_verified_mapping_has_separate_state_and_keeps_two_source_gate():
    mover = {"label": "机器人", "status": "READY"}
    market = ready_market(complete=True)
    market["raw_industry_up"] = [mover]
    relation = {
        "evidence_lane": "US_INDUSTRY_MAPPING",
        "evidence_class": "VERIFIED_US_INDUSTRY_WITH_HK_ISSUER_RELATION",
        "us_mover": mover,
        "hk_relation": {"source_refs": [{"status": "VERIFIED"}]},
    }
    out = assessment(market, material_count=1, industry={"HK.01234": [relation]})
    assert out["assessment_state"] == "ASSESSED_WITH_RELATIONS"
    assert out["accepted_hk_mapping_count"] == 1
    assert out["relation_gate"] == "TWO_SOURCE_PIT_VERIFIED_REQUIRED"


def test_research_relation_copies_pre_connect_cards_with_membership_unverified():
    pre_connect = [{"card_id": "card-1", "title": "issuer material"}]
    scope = {
        "status": "CANNOT_CONFIRM", "identity": "saved-connect-master", "target_trade_date": "20261002",
        "gaps": ["TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED"],
    }
    rejections = [{"card_id": "card-1", "reason": "TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED"}]
    relation_cards = _research_relation_material_cards(pre_connect, scope, rejections, "20261002")
    # The relation audit retains the card, while the formal selection list stays empty.
    formal_cards = []
    assert formal_cards == []
    assert len(relation_cards) == 1
    assert relation_cards[0]["target_connect_membership"]["status"] == "CANNOT_CONFIRM"
    assert relation_cards[0]["target_connect_membership"]["target_trade_date"] == "20261002"
    assert "target_connect_membership" not in pre_connect[0]

    diag = _research_relation_material_input(
        pre_connect_cards=pre_connect,
        post_connect_cards=formal_cards,
        relation_cards=relation_cards,
        connect_scope=scope,
        connect_rejections=rejections,
        material_discovery={"status": "READY", "gaps": []},
        selection_materials=[{"material_id": "source-1"}],
        existing={"gaps": []},
        announcement_inputs={"gaps": []},
    )
    assert diag["pre_connect_material_card_count"] == 1
    assert diag["post_connect_material_card_count"] == 0
    assert diag["research_relation_material_card_count"] == 1
    assert diag["target_connect_membership_counts"] == {"CANNOT_CONFIRM": 1}
    assert diag["relation_use"] == "RESEARCH_ONLY_NOT_FORMAL_SELECTION_FOCUS_OR_BUY"
    assert diag["production_allowed"] is False and diag["buy_gate_updated"] is False
