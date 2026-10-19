from v4.manager_workbench.engines.us_mapping_consumption import (
    MANUAL_QUOTE_OWNER,
    MANUAL_QUOTE_SCOPE_SHA256,
    build_peer_baskets,
    project_catalog_relation,
)

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
    return {"symbol": symbol, "session_date": day, "session_time": clock,
        "change_pct": change, "last": "10", "previous_close": "9.875"}


def _row(relation_id, symbol, relation_type="BUSINESS_PEER", *, segment="Cloud software",
         current="CURRENT_RESEARCH_SCOPE", closure="CLOSED_RESEARCH_SCOPE",
         condition="", direction=""):
    source = {
        "关系编号": relation_id,
        "code": "00001",
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
        "hk_code": "00001",
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
    return {"record_role": "CATALOG_OBSERVATION", "symbol": "HK.00001",
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
