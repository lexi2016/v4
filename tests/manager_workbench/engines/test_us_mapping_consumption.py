from decimal import Decimal

from v4.manager_workbench.engines.us_mapping_consumption import (
    MANUAL_QUOTE_OWNER,
    MANUAL_QUOTE_SCOPE_SHA256,
    build_catalog_candidates,
    build_peer_baskets,
    project_catalog_relation,
)
from v4.manager_workbench.inputs.source_bindings import _adapt_effective_research_schema

SHA = "a" * 64
CUTOFF = "2026-10-20T08:00:00+08:00"


def _binding(quotes):
    return {
        "state": "PARTIAL",
        "owner": MANUAL_QUOTE_OWNER,
        "scope_sha256": MANUAL_QUOTE_SCOPE_SHA256,
        "us_session_date": "20261016",
        "available_at": "2026-10-19T19:00:00+08:00",
        "payload_sha256": SHA,
        "receipt_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "quotes": quotes,
        "symbol_gaps": {"MSFT": "QUOTE_PROVIDER_SYMBOL_MISSING"},
    }


def _quote(symbol, *, day="20261016", clock="16:00:01", change="1.25"):
    previous_close = Decimal("100")
    last = previous_close * (Decimal(1) + Decimal(str(change)) / Decimal(100))
    return {"symbol": symbol, "session_date": day, "session_time": clock,
        "change_pct": change, "last": format(last, "f"),
        "previous_close": format(previous_close, "f")}


def _row(relation_id, symbol, relation_type="BUSINESS_PEER", *, segment="Cloud software",
         current="CURRENT_RESEARCH_SCOPE", closure="CLOSED_RESEARCH_SCOPE", code="00001",
         condition="", direction=""):
    source = {
        "关系编号": relation_id,
        "code": code,
        "type": relation_type,
        "asset_code": symbol,
        "fact": "Documented business exposure in the named segment.",
        "segment": segment,
        "研究行业": "Software",
        "condition": condition,
        "direction": direction,
    }
    relation = {
        "relation_id": relation_id,
        "hk_code": code,
        "hk_name": "Target",
        "source_row": 12,
        "research_use": "CONDITIONAL_OBSERVATION",
        "source_record": source,
        "recovery_v2r1": {
            "closure_status": closure,
            "current_applicability_state": current,
            "fact_state": "FACT_SCOPE_RECORDED",
            "use_scope": {"EXCLUDED_SCOPE": {"state": "NONE_RECORDED"}},
            "research_layers": {},
            "remaining_gaps": [],
        },
    }
    return {"record_role": "CATALOG_OBSERVATION", "symbol": f"HK.{code}",
        "catalog_relation": relation, "catalog_relation_id": relation_id}


def _project(row, binding):
    return project_catalog_relation(row, manual_binding=binding,
        expected_session="20261016", cutoff=CUTOFF)


def test_current_peer_relation_keeps_identity_fact_and_exact_date_quote():
    projected = _project(_row("R001", "AAPL"), _binding({"AAPL": _quote("AAPL")}))

    assert projected["catalog_relation_id"] == "R001"
    assert projected["catalog_disposition"] == "ADOPTED_BUSINESS_PEER"
    assert projected["catalog_disposition_reason"]
    assert projected["catalog_fact"] == "Documented business exposure in the named segment."
    assert projected["quote_status"] == "VERIFIED"
    assert projected["us_source_return_pct"] == "1.25"
    assert projected["signed_hk_return_pct"] is None
    assert projected["active_transmission"] is False


def test_nested_six_layer_dated_state_is_normalized_without_filling_true_missing_fields():
    adapted = _adapt_effective_research_schema({
        "six_layers": {"CURRENT_APPLICABILITY": {"state": "DATED_SCOPE_ONLY"}},
        "whitelist_scope": {},
    })
    missing = _adapt_effective_research_schema({"six_layers": {}, "whitelist_scope": {}})

    assert adapted["current_applicability_state"] == "DATED_SCOPE_ONLY"
    assert adapted["six_layers"]["CURRENT_APPLICABILITY"]["state"] == "DATED_SCOPE_ONLY"
    assert adapted["state_conflicts"] == {}
    assert missing["current_applicability_state"] is None
    assert missing["state_conflicts"] == {}


def test_r924_r955_r942_nested_dated_relations_remain_visible_as_weak_candidates():
    binding = _binding({
        "WMT": _quote("WMT", change="0.797489"),
        "KO": _quote("KO", change="0.5"),
        "PG": _quote("PG", change="-0.25"),
    })
    cases = (("R924", "WMT", "00001"), ("R955", "KO", "00002"), ("R942", "PG", "00003"))
    projected = []
    for relation_id, symbol, code in cases:
        row = _row(relation_id, symbol, code=code)
        adapted = _adapt_effective_research_schema({
            "whitelist_scope": {},
            "research_layers": {},
            "six_layers": {
                "CURRENT_APPLICABILITY": {"state": "DATED_SCOPE_ONLY"},
                "FACT_VERIFIED_SCOPE": {"state": "FACT_SCOPE_RECORDED"},
                "IDENTITY_SCOPE": {"state": "IDENTITY_SCOPE_RECORDED"},
            },
        })
        recovery = row["catalog_relation"]["recovery_v2r1"]
        recovery.update(current_applicability_state=adapted["current_applicability_state"],
            fact_state=adapted["fact_state"], identity_state=adapted["identity_state"],
            use_scope=adapted["use_scope"], research_layers=adapted["research_layers"],
            six_layers=adapted["six_layers"], state_conflicts=adapted["state_conflicts"])
        projected.append(_project(row, binding))

    candidates = build_catalog_candidates(projected)

    assert {row["catalog_relation_id"] for row in projected} == {"R924", "R955", "R942"}
    assert all(row["catalog_current_applicability"] == "DATED_SCOPE_ONLY" for row in projected)
    assert all(row["catalog_disposition"] != "ADOPTED_BUSINESS_PEER" for row in projected)
    assert all(row["qualification"] == "DATED_WEAK_PEER" for row in candidates)
    assert {relation["catalog_relation_id"] for candidate in candidates
        for relation in candidate["relations"]} == {"R924", "R955", "R942"}


def test_conflicting_recovery_state_is_explicit_and_never_promoted():
    adapted = _adapt_effective_research_schema({
        "current_applicability_state": "CURRENT_RESEARCH_SCOPE",
        "six_layers": {"CURRENT_APPLICABILITY": {"state": "DATED_SCOPE_ONLY"}},
    })
    row = _row("R-CONFLICT", "AAPL")
    row["catalog_relation"]["recovery_v2r1"].update({
        "current_applicability_state": adapted["current_applicability_state"],
        "six_layers": adapted["six_layers"],
        "state_conflicts": adapted["state_conflicts"],
    })
    projected = _project(row, _binding({"AAPL": _quote("AAPL")}))

    assert adapted["current_applicability_state"] is None
    assert adapted["state_conflicts"]["current_applicability_state"]
    assert projected["catalog_current_applicability_conflict"] is True
    assert projected["catalog_disposition"] == "PEER_CURRENT_SCOPE_UNCONFIRMED"
    assert projected["catalog_disposition_reason"] == "CURRENT_APPLICABILITY_TOP_LEVEL_NESTED_CONFLICT"
    assert build_catalog_candidates([projected])[0]["qualification"] == "PENDING_REVIEW"


def test_dated_and_unknown_current_scope_states_remain_review_candidates():
    dated = _project(_row("R-DATED", "WMT", current="DATED_SCOPE_ONLY"),
        _binding({"WMT": _quote("WMT")}))
    unknown = _project(_row("R-UNKNOWN", "AAPL", current="FUTURE_SCOPE_ENUM", code="00002"),
        _binding({"AAPL": _quote("AAPL")}))
    dated_candidate, unknown_candidate = build_catalog_candidates([dated, unknown])

    assert dated["catalog_current_scope_class"] == "DATED_OR_PENDING_SCOPE"
    assert dated["catalog_disposition"] == "PEER_BACKGROUND_OR_PENDING"
    assert dated_candidate["qualification"] == "DATED_WEAK_PEER"
    assert unknown["catalog_current_scope_class"] == "UNRECOGNIZED_CURRENT_APPLICABILITY"
    assert unknown["catalog_disposition"] == "PEER_CURRENT_SCOPE_UNCONFIRMED"
    assert unknown_candidate["qualification"] == "PENDING_REVIEW"


def test_candidate_gate_rejects_explicitly_excluded_research_use_even_if_disposition_is_stale():
    row = _project(_row("R-EXCLUDED", "AAPL"),
        _binding({"AAPL": _quote("AAPL")}))
    row["catalog_research_use"] = "EXCLUDED_CURRENT"
    row["catalog_disposition"] = "ADOPTED_BUSINESS_PEER"

    assert build_catalog_candidates([row]) == []


def test_candidate_rows_deduplicate_hk_codes_preserve_opposing_evidence_and_sort_deterministically():
    binding = _binding({
        "AAPL": _quote("AAPL", change="3.0"),
        "MSFT": _quote("MSFT", change="-1.0"),
        "WMT": _quote("WMT", change="2.0"),
        "NVDA": _quote("NVDA", change="0"),
    })
    rows = [
        _project(_row("R-POS-2", "AAPL", code="00002"), binding),
        _project(_row("R-NEG-2", "MSFT", code="00002"), binding),
        _project(_row("R-POS-1", "WMT", code="00001"), binding),
        _project(_row("R-FLAT", "NVDA", code="00003"), binding),
        _project(_row("R-DATED", "AAPL", current="DATED_SCOPE_ONLY", code="00004"), binding),
    ]
    candidates = build_catalog_candidates(rows, monthly_pool_symbols={"HK.00002"})

    assert [row["symbol"] for row in candidates] == [
        "HK.00001", "HK.00002", "HK.00003", "HK.00004"]
    assert candidates[0]["qualification"] == "CURRENT_SUPPORTED"
    assert candidates[0]["positive_source_move_strength_pct"] == "2.0"
    assert candidates[1]["direction_group"] == "MIXED_POSITIVE_NEGATIVE"
    assert candidates[1]["positive_relation_ids"] == ["R-POS-2"]
    assert candidates[1]["negative_relation_ids"] == ["R-NEG-2"]
    assert candidates[1]["relation_count"] == 2
    assert candidates[1]["in_monthly_pool"] is True
    assert candidates[2]["direction_group"] == "FLAT_OR_UNKNOWN"
    assert candidates[3]["qualification"] == "DATED_WEAK_PEER"


def test_preclose_quote_degrades_only_its_relation_and_never_creates_negative_direction():
    binding = _binding({"AAPL": _quote("AAPL", change="1.25"),
        "MSFT": _quote("MSFT", clock="15:59:59", change="-2.0")})
    positive = _project(_row("R-POS", "AAPL"), binding)
    preclose = _project(_row("R-PRECLOSE", "MSFT"), binding)
    candidate = build_catalog_candidates([positive, preclose])[0]

    assert positive["quote_status"] == "VERIFIED"
    assert preclose["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert preclose["quote_missing_reason"] == "MANUAL_QUOTE_BEFORE_OFFICIAL_CLOSE"
    assert candidate["direction_group"] == "POSITIVE_WITHOUT_NEGATIVE"
    assert candidate["unknown_relation_ids"] == ["R-PRECLOSE"]


def test_peer_basket_deduplicates_members_and_publishes_partial_equal_weight_coverage():
    binding = _binding({"AAPL": _quote("AAPL")})
    rows = [
        _project(_row("R001", "AAPL"), binding),
        _project(_row("R002", "AAPL"), binding),
        _project(_row("R003", "MSFT"), binding),
    ]
    basket = build_peer_baskets(rows)["HK.00001"][0]

    assert basket["signal_type"] == "SINGLE_PEER_REFERENCE"
    assert basket["coverage_state"] == "PARTIAL"
    assert basket["declared_count"] == 2
    assert basket["valid_count"] == 1
    assert basket["coverage_fraction"] == 0.5
    assert basket["members"] == [{"symbol": "AAPL", "return_pct": "1.25",
        "weight": 1.0, "relation_ids": ["R001", "R002"]}]
    assert basket["missing_symbols"][0]["symbol"] == "MSFT"
    assert basket["relation_ids"] == ["R001", "R002", "R003"]


def test_same_issuer_and_conditional_supply_routes_never_emit_hk_sign():
    binding = _binding({"AAPL": _quote("AAPL")})
    issuer = _project(_row("R004", "AAPL", "SAME_ISSUER"), binding)
    supply = _project(_row("R005", "AAPL", "SUPPLY_CHAIN",
        condition="Only when named order volume exceeds the disclosed threshold.", direction="positive"), binding)

    assert issuer["catalog_disposition"] == "ADOPTED_SAME_ISSUER_CONTEXT"
    assert issuer["route"] == "SAME_ISSUER_ADR_CONTEXT"
    assert issuer["signed_hk_return_pct"] is None
    assert issuer["active_transmission"] is False
    assert supply["catalog_disposition"] == "ADOPTED_CONDITIONAL_ROUTE"
    assert supply["catalog_condition"] == "Only when named order volume exceeds the disclosed threshold."
    assert supply["catalog_direction_raw"] == "positive"
    assert supply["condition_trigger_state"] == "NOT_EVALUATED"
    assert supply["signed_hk_return_pct"] is None
    assert supply["active_transmission"] is False


def test_invalid_provider_session_or_time_format_keeps_symbol_unquoted():
    bad_date = _project(_row("R006", "AAPL"), _binding({"AAPL": _quote("AAPL", day="20261015")}))
    bad_time = _project(_row("R007", "AAPL"), _binding({"AAPL": _quote("AAPL", clock="invalid")}))

    assert bad_date["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert bad_date["quote_missing_reason"] == "MANUAL_QUOTE_SESSION_DATE_MISMATCH"
    assert bad_time["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert bad_time["quote_missing_reason"] == "MANUAL_QUOTE_PROVIDER_TIME_INVALID"
