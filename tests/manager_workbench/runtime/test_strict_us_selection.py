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


def test_positive_a_path_selects_and_keeps_unknown_suspension_as_risk():
    result = _run()

    assert result["state"] == "READY"
    assert result["selected_count"] == 1
    assert result["selected"][0]["symbol"] == "HK.00001"
    assert result["panel_available_at"] == "2026-10-18T21:00:00+00:00"
    assert result["rows"][0]["metrics"]["suspension_status"] == "UNKNOWN"
    assert "SUSPENSION_STATUS_UNKNOWN" in result["rows"][0]["risks"]
    assert result["RESEARCH_ONLY"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_negative_primary_proxy_return_is_not_selected():
    result = _run(relations=[_relation(return_pct="0.5")])

    assert result["state"] == "READY"
    assert result["selected_count"] == 0
    assert result["rows"][0]["decision"] == "NOT_SELECTED"
    assert result["rows"][0]["reason"] == "PRIMARY_SIGNED_PROXY_RETURN_BELOW_1_PERCENT"


def test_missing_amount_field_is_unassessed_not_zero_or_a_candidate():
    payload = _payload()
    latest = payload["hk_history"]["rows"][0]["bars"][-1]
    latest.pop("amount")
    result = _run(payload=payload)

    assert result["state"] == "CANNOT_CONFIRM"
    assert result["selected_count"] is None
    assert "HK_HISTORY_WINDOW_HAS_NO_COMPLETE_STOCKS" in result["gaps"]
    assert result["rows"][0]["decision"] == "UNASSESSED"
    assert result["rows"][0]["reason"] == "HK_AMOUNT_FIELD_MISSING"


def test_fixed_secondary_negative_path_conflicts_with_positive_a_primary():
    industry = {"symbol": "HK.00001", "source_industry": "石油及天然气",
        "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00",
        "proxy_paths": [
            {"proxy_symbols": ["XLE"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "1.2", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
            {"proxy_symbols": ["FCG"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "-1.1", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
        ]}
    result = _run(industry_rows=[industry])

    assert result["selected_count"] == 0
    assert result["rows"][0]["reason"] == "SECONDARY_A_B_PROXY_CONFLICT"
    assert [path["proxy_symbol"] for path in result["rows"][0]["conflict_paths"]] == ["FCG"]


def test_theme_cap_ranks_by_turnover_without_widening_scope():
    codes = [f"HK.{number:05d}" for number in range(1, 5)]
    turnover = {codes[0]: 21_000_000, codes[1]: 22_000_000,
        codes[2]: 23_000_000, codes[3]: 24_000_000}
    payload = _payload(codes, [_history(code, turnover[code]) for code in codes])
    result = _run(payload=payload, relations=[_relation(code, return_pct="1.5") for code in codes])

    assert result["monthly_observed_scope_count"] == 4
    assert [row["symbol"] for row in result["selected"]] == [codes[3], codes[2], codes[1]]
    assert result["rows"][0]["reason"] == "PRIMARY_THEME_CAP_REACHED"


def _single_membership(codes):
    return {
        "status": "VERIFIED", "market": "HK_CONNECT", "owner": "FUTU_HKCONNECT_PLATE_MEMBERSHIP",
        "target_month": "202610", "source_date": "20261012", "artifact_sha256": SHA,
        "codes": list(codes),
        "codes_sha256": owner_digest({"market": "HK_CONNECT", "codes": sorted(codes)}),
    }


def _single_context():
    return {"target_date": "20261020", "phase": "MANUAL",
        "source_sessions": {"us": "20261016", "hk_price": "20261016"},
        "cutoff": "2026-10-19T03:00:00+00:00"}


def _single_day(codes, relations=(), industries=(), industry_status="READY"):
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping

    return run_single_day_mapping(_single_context(), relation_rows=list(relations),
        industry_rows=list(industries),
        factor_summary={"industry_summary": {"source_status": industry_status,
            "source_asof": "20261012", "source_artifact_sha256": SHA}},
        membership=_single_membership(codes))


def test_single_day_mapping_uses_full_membership_without_history_and_separates_categories():
    codes = [f"HK.{number:05d}" for number in range(1, 8)]
    a_positive = _relation(codes[0], return_pct="1.5")
    a_negative = _relation(codes[1], return_pct="-1.2")
    a_small = _relation(codes[2], return_pct="0.5")
    c_relation = dict(_relation(codes[3], return_pct="2.0"),
        relation_type="INDIRECT_STRATEGIC_PLATFORM_COLLABORATION",
        relation_status="REVIEWED", research_basis="间接合作只作为 C 级观察")
    broad_c = {"symbol": codes[4], "source_industry": "家庭电器及用品",
        "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00",
        "proxy_paths": [{"proxy_symbols": ["XLY", "XLP"], "source_session": "20261016",
            "status": "VERIFIED", "return_pct": "1.2", "source_sha256": SHA,
            "owner": "US_PROXY_OWNER", "available_at": "2026-10-18T20:00:00+00:00"}]}
    a_unassessed = _relation(codes[6], return_pct="0.7")
    a_unassessed["owner"] = None
    result = _single_day(codes, [a_positive, a_negative, a_small, c_relation,
        _relation("HK.09999", return_pct="2.5"), a_unassessed], [broad_c])

    assert result["monthly_observed_scope_count"] == 7
    assert len(result["rows"]) == 7
    assert [row["decision"] for row in result["rows"]] == [
        "BENEFIT", "RISK", "OBSERVATION", "OBSERVATION", "OBSERVATION", "UNMAPPED", "UNASSESSED"]
    assert result["counts"] == {
        "BENEFIT": 1, "RISK": 1, "CONFLICT": 0,
        "OBSERVATION": 3, "UNMAPPED": 1, "UNASSESSED": 1,
        "SMALL_MOVE_WATCH": 1, "C_WATCH": 2}
    assert result["rows"][3]["mapping_grade"] == "C"
    assert result["rows"][4]["mapping_paths"][0]["grade"] == "C"
    assert result["rows"][5]["decision"] == "UNMAPPED"
    assert result["rows"][6]["decision"] == "UNASSESSED"
    assert [row["symbol"] for row in result["outside_pool_observations"]] == ["HK.09999"]
    assert result["strict_v1_status"] == "PAUSED_NOT_EXECUTED"
    assert result["deferred_gates"] == ["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"]
    assert result["RESEARCH_ONLY"] is True and result["production_allowed"] is False
    assert result["buy_gate_updated"] is False and result["orders_sent"] is False


def test_single_day_primary_is_fixed_before_returns_and_conflict_paths_are_retained():
    code = "HK.00001"
    industries = [{"symbol": code, "source_industry": "半导体",
        "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00",
        "proxy_paths": [{"proxy_symbols": ["SOXX"], "source_session": "20261016",
            "status": "VERIFIED", "return_pct": "-1.4", "source_sha256": SHA,
            "available_at": "2026-10-18T20:00:00+00:00"}]}]
    result = _single_day(["HK.00001"], [
        _relation(code, return_pct="4.0", us_symbol="NVDA"),
        _relation(code, return_pct="1.1", us_symbol="AMD")], industries)

    row = result["rows"][0]
    assert row["decision"] == "CONFLICT"
    assert row["primary_us_symbol"] == "AMD"
    assert row["primary_signed_return_pct"] == "1.1"
    assert [path["us_symbol"] for path in row["mapping_paths"] if path["grade"] == "A"] == ["AMD", "NVDA"]
    assert [path["proxy_symbol"] for path in row["conflict_paths"]] == ["SOXX"]
    assert row["frozen_policy_conflict"] is True


def test_single_day_frozen_b_primary_precedes_secondary_regardless_of_proxy_symbol():
    industry = {"symbol": "HK.00001", "source_industry": "石油及天然气",
        "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00",
        "proxy_paths": [
            {"proxy_symbols": ["XLE"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "-1.2", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
            {"proxy_symbols": ["FCG"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "0.5", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
        ]}

    result = _single_day(["HK.00001"], industries=[industry])

    row = result["rows"][0]
    assert [path["proxy_symbol"] for path in row["mapping_paths"] if path["grade"] == "B"] == ["XLE", "FCG"]
    assert row["primary_proxy"] == "XLE"
    assert row["primary_signed_return_pct"] == "-1.2"
    assert row["decision"] == "RISK"
    assert row["reason"] == "PRIMARY_AB_SIGNED_RETURN_AT_MOST_MINUS_1_PERCENT"


def test_single_day_catalog_placeholder_with_broad_c_path_sorts_without_proxy_symbol():
    catalog_observation = {"symbol": "HK.00027", "us_symbol": None,
        "relation_type": "CATALOG_OBSERVATION_ONLY", "relation_status": "CANNOT_CONFIRM",
        "decision": "UNASSESSED", "record_role": "CATALOG_OBSERVATION",
        "owner": None, "source_sha256": None, "source_session": "20261016",
        "available_at": "2026-10-17T15:35:31Z", "quote": None}
    broad_c = {"symbol": "HK.00027", "source_industry": "旅游及消闲设施",
        "identity_status": "VERIFIED", "available_at": "2026-10-14T11:03:29.919614+08:00",
        "proxy_paths": [{"proxy_symbols": ["XLY", "XLP"], "source_session": "20261016",
            "status": "VERIFIED", "return_pct": "0.1233899552273611267146694300",
            "source_sha256": SHA, "owner": "research_peripheral.external_finance",
            "available_at": "2026-10-17T15:35:31Z"}]}

    result = _single_day(["HK.00027"], relations=[catalog_observation], industries=[broad_c])

    row = result["rows"][0]
    assert row["decision"] == "OBSERVATION"
    assert row["reason"] == "C_MAPPING_OBSERVE_ONLY"
    assert any(path["source_type"] == "C_RELATIONSHIP_OBSERVATION"
        and path["status"] == "UNASSESSED" for path in row["mapping_paths"])
    assert any(path["source_type"] == "BROAD_CONSUMPTION_OBSERVATION"
        and path["status"] == "VERIFIED" for path in row["mapping_paths"])


def test_single_day_rejects_other_target_date_without_claiming_a_result():
    context = _single_context()
    context["target_date"] = "20261019"
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping
    result = run_single_day_mapping(context, relation_rows=[], industry_rows=[],
        factor_summary={}, membership=_single_membership(["HK.00001"]))

    assert result["state"] == "CANNOT_CONFIRM"
    assert result["rows"] == []
    assert result["gaps"] == ["SINGLE_DAY_DATE_OR_PHASE_BINDING_MISMATCH"]
    assert result["formal_target_eligibility"] == "CANNOT_CONFIRM"
