from copy import deepcopy
from datetime import date, timedelta

from v4.manager_workbench.engines.strict_us_selection import run_strict_us_selection
from v4.manager_workbench.inputs.validation import owner_digest


END = date(2026, 10, 16)
SESSIONS = [(END - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(20, -1, -1)]
CUTOFF = "2026-10-19T03:00:00+00:00"
SHA = "a" * 64


def _history(symbol="HK.00001", turnover=25_000_000):
    bars = []
    for index, day in enumerate(SESSIONS):
        bar = {"date": day, "close": "100"}
        if index > 0:
            bar["amount"] = str(turnover)
        bars.append(bar)
    return {"symbol": symbol, "bars": bars, "history_holds": {}}


def _relation(symbol="HK.00001", *, return_pct="1.5", us_symbol="NVDA"):
    value = float(return_pct)
    return dict(symbol=symbol, us_symbol=us_symbol,
        relation_type="NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER",
        relation_status="REVIEWED", relation_pit_status=None,
        publication_time_gaps=[], diagnostic_gaps=[], owner="US_QUOTE_OWNER",
        source_sha256=SHA, source_session="20261016", available_at="2026-10-18T21:00:00+00:00",
        quote={"session_date": "20261016", "last": str(100 + value),
            "previous_close": "100", "change_pct": str(value)},
        relation_source_refs=[])


def _payload(codes=("HK.00001",), histories=None):
    return {
        "monthly_membership": {"status": "VERIFIED", "target_eligibility": "CANNOT_CONFIRM",
            "source_date": "20261012", "source_sha256": SHA,
            "codes_sha256": owner_digest({"market": "HK_CONNECT", "codes": sorted(codes)}),
            "owner": "FUTU_HKCONNECT_PLATE_MEMBERSHIP", "codes": list(codes)},
        "hk_history": {"status": "READY", "rows": histories or [_history(code) for code in codes],
            "close_sessions": SESSIONS, "amount_sessions": SESSIONS[-20:],
            "panel_sha256": SHA, "panel_manifest_sha256": SHA,
            "panel_available_at": "2026-10-18T21:00:00+00:00",
            "history_resolution_manifest_sha256": SHA,
            "history_resolution_proof_sha256": SHA,
            "amount_unit_status": "SOURCE_SCALE_CHECKED",
            "basic_unit_check_sha256": "6118718612b3be075d7757e37874564ca7fa09b35dddfca2f6c943aacbfc0d03"},
    }


def _context():
    return {"target_date": "20261020", "phase": "MANUAL",
        "cutoff": CUTOFF, "source_sessions": {"us": "20261016", "hk_price": "20261016"}}


def _run(payload=None, relations=None, industry_rows=None):
    return run_strict_us_selection(_context(),
        relation_rows=relations if relations is not None else [_relation()],
        industry_rows=industry_rows or [],
        factor_summary={"industry_summary": {"source_status": "READY"}},
        payload=payload or _payload())


def test_legacy_scale_check_and_unknown_suspension_are_not_proof():
    result = _run()
    assert result["selected_count"] == 0
    assert result["rows"][0]["decision"] == "PENDING"
    assert any("PROOF_PENDING" in reason for reason in result["rows"][0]["reasons"])


def test_unproven_quote_identity_and_weekend_window_cannot_select():
    relation = _relation()
    relation["quote"]["symbol"] = "AMD"
    result = _run(relations=[relation])
    row = result["rows"][0]
    assert "QUOTE_SYMBOL_MISMATCH" in row["reasons"]
    assert "HK_FROZEN_SESSION_WINDOW_INVALID" in row["reasons"]
    assert row["decision"] == "PENDING"


def test_strict_contract_rejects_an_impossible_selected_branch():
    import pytest
    from pydantic import ValidationError
    from v4.manager_workbench.contracts import StrictSelectionDecision
    with pytest.raises(ValidationError, match="STRICT_SELECTION_REQUIRES_ALL_GATES_PASS"):
        StrictSelectionDecision(symbol="HK.00001",state="PASS",decision="SELECTED",qualified=True,
            gates=[dict(gate="pit",state="PENDING")])


def test_legacy_entry_is_same_policy_and_preserves_safety():
    from v4.manager_workbench.engines.us_mapping_policy import POLICY_SHA256
    result = _run()
    assert result["policy_sha256"] == POLICY_SHA256
    assert result["RESEARCH_ONLY"] is True
    assert all(result[key] is False for key in ["production_allowed", "buy_gate_updated", "orders_sent"])
