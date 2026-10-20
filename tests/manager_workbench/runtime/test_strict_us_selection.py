from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

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


def _single_context(target_date="20261020", *, us_session="20261016", hk_price_session="20261016",
                    phase="MANUAL", cutoff=None):
    cutoff = cutoff or ("2026-10-20T03:00:00+00:00" if target_date == "20261021"
        else "2026-10-19T03:00:00+00:00")
    return {"target_date": target_date, "phase": phase,
        "source_sessions": {"us": us_session, "hk_price": hk_price_session},
        "cutoff": cutoff}


def _manual_quote_scope(values):
    from v4.manager_workbench.engines.us_mapping_consumption import (
        MANUAL_QUOTE_OWNER, MANUAL_QUOTE_SCOPE_SHA256,
    )
    quotes = {}
    for symbol, raw_change in values.items():
        change = Decimal(str(raw_change))
        previous_close = Decimal("100")
        last = previous_close * (Decimal(1) + change / Decimal(100))
        quotes[symbol] = {"symbol": symbol, "session_date": "20261016", "session_time": "16:00:02",
            "last": format(last, "f"), "previous_close": format(previous_close, "f"),
            "change_pct": raw_change}
    return dict(state="READY", owner=MANUAL_QUOTE_OWNER,
        scope_sha256=MANUAL_QUOTE_SCOPE_SHA256, us_session_date="20261016",
        payload_sha256=SHA, receipt_sha256="e" * 64, manifest_sha256="f" * 64,
        available_at="2026-10-18T20:00:00+00:00",
        quotes=quotes, symbol_gaps={})


def _single_day(codes, relations=(), industries=(), industry_status="READY",
                catalog_rows=(), catalog_stock_identities=None,
                catalog_expected_stock_count=None, manual_quote_scope=None, context=None):
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping

    return run_single_day_mapping(context or _single_context(), relation_rows=list(relations),
        catalog_rows=list(catalog_rows), manual_quote_scope=manual_quote_scope,
        catalog_stock_identities=catalog_stock_identities,
        catalog_expected_stock_count=catalog_expected_stock_count,
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
        "BENEFIT", "RISK", "OBSERVATION", "OBSERVATION", "UNASSESSED", "UNMAPPED", "UNASSESSED"]
    assert result["counts"] == {
        "BENEFIT": 1, "RISK": 1, "CONFLICT": 0,
        "OBSERVATION": 2, "UNMAPPED": 1, "UNASSESSED": 2,
        "SMALL_MOVE_WATCH": 1, "C_WATCH": 1}
    assert result["rows"][3]["mapping_grade"] == "C"
    assert result["rows"][4]["mapping_paths"][0]["grade"] == "C"
    assert result["rows"][5]["decision"] == "UNMAPPED"
    assert result["rows"][6]["decision"] == "UNASSESSED"
    assert [row["symbol"] for row in result["outside_pool_observations"]] == ["HK.09999"]
    assert result["strict_v1_status"] == "PAUSED_NOT_EXECUTED"
    assert result["deferred_gates"] == ["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"]
    assert result["RESEARCH_ONLY"] is True and result["production_allowed"] is False
    assert result["buy_gate_updated"] is False and result["orders_sent"] is False


def test_single_day_industry_baseline_cannot_conflict_with_direct_peer_paths():
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
    assert row["decision"] == "BENEFIT"
    assert row["primary_us_symbol"] == "AMD"
    assert row["primary_signed_return_pct"] == "1.1"
    assert [path["us_symbol"] for path in row["mapping_paths"] if path["grade"] == "A"] == ["AMD", "NVDA"]
    assert row["conflict_paths"] == []
    assert not row.get("frozen_policy_conflict")
    assert any(path["source_type"] == "BROAD_SECTOR_BACKGROUND"
        and path["signed_return_pct"] is None for path in row["mapping_paths"])


def test_single_day_sector_etfs_are_secondary_observations_not_primary_paths():
    industry = {"symbol": "HK.00001", "source_industry": "石油及天然气",
        "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00",
        "proxy_paths": [
            {"proxy_symbols": ["XLE"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "-1.2", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
            {"proxy_symbols": ["FCG"], "source_session": "20261016", "status": "VERIFIED",
                "return_pct": "0.5", "source_sha256": SHA, "available_at": "2026-10-18T20:00:00+00:00"},
        ]}

    result = _single_day(["HK.00001"], industries=[industry],
        manual_quote_scope=_manual_quote_scope({"XLE": "-1.2", "FCG": "0.5"}))

    row = result["rows"][0]
    paths = [path for path in row["mapping_paths"] if path["source_type"] == "BROAD_SECTOR_BACKGROUND"]
    assert [path["proxy_symbol"] for path in paths] == ["FCG", "XLE"]
    assert row["primary_proxy"] is None
    assert all(path["signed_return_pct"] is None and path["status"] == "VERIFIED" for path in paths)
    assert row["decision"] == "OBSERVATION"
    assert row["open_reaction_status"] == "PENDING_OPEN"
    assert row["post_open_status"] == "PENDING_OPEN"


def test_single_day_utilities_insurance_and_consumer_subsectors_use_frozen_baselines():
    cases = [
        ("公用事业", {"XLU": "0.4"}, ["XLU"]),
        ("保险", {"KIE": "-0.3"}, ["KIE"]),
        ("食物饮品", {"XLP": "0.2"}, ["XLP"]),
        ("专业零售", {"XLY": "0.8"}, ["XLY"]),
        ("家庭电器及用品", {"XLY": "0.8"}, ["XLY", "XLP"]),
    ]
    for index, (industry_label, values, expected_symbols) in enumerate(cases, start=1):
        code = f"HK.{index:05d}"
        industry = {"symbol": code, "source_industry": industry_label,
            "identity_status": "VERIFIED", "available_at": "2026-10-18T20:00:00+00:00"}
        result = _single_day([code], industries=[industry],
            manual_quote_scope=_manual_quote_scope(values))
        row = result["rows"][0]
        path = next(path for path in row["mapping_paths"]
            if path["source_type"] == "BROAD_SECTOR_BACKGROUND")
        assert path["proxy_symbols"] == expected_symbols
        assert path["signed_return_pct"] is None
        assert path["status"] == ("PARTIAL" if industry_label == "家庭电器及用品" else "VERIFIED")
        assert row["primary_proxy"] is None


def test_single_day_post_open_state_requires_bound_opening_owner():
    context = _single_context()
    context["cutoff"] = "2026-10-20T10:00:00+08:00"
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping
    result = run_single_day_mapping(context, relation_rows=[], industry_rows=[],
        catalog_rows=[], factor_summary={}, membership=_single_membership(["HK.00001"]))

    row = result["rows"][0]
    assert row["open_reaction_status"] == "CANNOT_CONFIRM"
    assert row["post_open_status"] == "CANNOT_CONFIRM"
    assert row["post_open_reason"] == "HK_OPENING_DATA_OWNER_NOT_BOUND_AT_CUTOFF"


def test_single_day_projects_catalog_dispositions_and_partial_peer_basket_per_target():
    from v4.manager_workbench.engines.us_mapping_consumption import (
        MANUAL_QUOTE_OWNER, MANUAL_QUOTE_SCOPE_SHA256,
    )
    binding = dict(state="PARTIAL", owner=MANUAL_QUOTE_OWNER,
        scope_sha256=MANUAL_QUOTE_SCOPE_SHA256, us_session_date="20261016",
        available_at="2026-10-18T20:00:00+00:00", payload_sha256=SHA,
        receipt_sha256="e" * 64, manifest_sha256="f" * 64,
        quotes={"AAPL": {"symbol": "AAPL", "session_date": "20261016",
            "session_time": "16:00:02", "last": "101.25", "previous_close": "100",
            "change_pct": "1.25"}},
        symbol_gaps={"MSFT": "QUOTE_PROVIDER_SYMBOL_MISSING"})

    def catalog_relation(relation_id, symbol, relation_type="BUSINESS_PEER", *, condition=""):
        source = {"关系编号": relation_id, "code": "00001", "type": relation_type,
            "asset_code": symbol, "fact": "Named business relationship.", "segment": "Cloud software",
            "研究行业": "Software", "condition": condition, "direction": "positive"}
        relation = {"relation_id": relation_id, "hk_code": "00001", "source_row": 12,
            "source_record": source, "recovery_v2r1": {"closure_status": "CLOSED_RESEARCH_SCOPE",
                "current_applicability_state": "CURRENT_RESEARCH_SCOPE",
                "use_scope": {"FACT_VERIFIED_SCOPE": {"state": "LIMITED"}}}}
        return {"symbol": "HK.00001", "record_role": "CATALOG_OBSERVATION",
            "catalog_relation_id": relation_id, "catalog_relation": relation}

    result = _single_day(["HK.00001"], catalog_rows=[
        catalog_relation("R001", "AAPL"), catalog_relation("R002", "MSFT"),
        catalog_relation("R003", "AAPL", "SUPPLY_CHAIN",
            condition="Only when the disclosed customer award remains active.")],
        catalog_stock_identities=[{"hk_code": "00001", "name": "Mapped"}],
        catalog_expected_stock_count=1,
        manual_quote_scope=binding)

    summary = result["catalog_consumption"]
    stocks = result["catalog_stock_reconciliation"]
    row = result["rows"][0]
    assert summary["relation_count"] == 3
    assert summary["unique_relation_id_count"] == 3
    assert summary["state"] == "PARTIAL"
    assert stocks["catalog_stock_count"] == 1
    assert stocks["in_monthly_pool_stock_count"] == 1
    assert stocks["outside_monthly_pool_stock_count"] == 0
    assert row["catalog_peer_baskets"][0]["signal_type"] == "SINGLE_PEER_REFERENCE"
    assert len(result["catalog_candidates"]) == 1
    candidate = result["catalog_candidates"][0]
    assert candidate["symbol"] == "HK.00001"
    assert candidate["relation_count"] == 2
    assert candidate["positive_relation_ids"] == ["R001"]
    assert candidate["unknown_relation_ids"] == ["R002"]
    assert candidate["qualification"] == "CURRENT_SUPPORTED"
    assert result["catalog_candidate_ordering"] == (
        "QUALIFICATION_THEN_SOURCE_DIRECTION_THEN_POSITIVE_US_SOURCE_RETURN_DESC_THEN_HK_CODE")
    assert result["catalog_candidate_return_note"].endswith("not an HK return forecast.")
    proxy_coverage = result["sector_proxy_coverage_observations"][0]
    assert proxy_coverage["source_symbol"] == "ITA"
    assert proxy_coverage["mapping_status"] == "MAPPING_PENDING"
    assert proxy_coverage["mapped_hk_symbols"] == []
    assert proxy_coverage["edge_created"] is False
    basket = row["catalog_peer_baskets"][0]
    assert basket["coverage_state"] == "PARTIAL"
    assert basket["declared_count"] == 2 and basket["valid_count"] == 1
    assert basket["source_move_direction"] == "UP"
    assert "not HK expected return" in basket["interpretation"]
    dispositions = {item["relation_id"]: item for item in row["catalog_relation_dispositions"]}
    assert dispositions["R001"]["disposition"] == "ADOPTED_BUSINESS_PEER"
    assert dispositions["R002"]["quote_missing_reason"] == "QUOTE_PROVIDER_SYMBOL_MISSING"
    assert dispositions["R003"]["disposition"] == "ADOPTED_CONDITIONAL_ROUTE"
    assert dispositions["R003"]["condition_trigger_state"] == "NOT_EVALUATED"
    assert dispositions["R003"]["active_transmission"] is False
    assert all(item["signed_hk_return_pct"] is None for item in dispositions.values())
    assert row["decision"] == "UNMAPPED"
    assert row["primary_proxy"] is None


def test_catalog_stock_reconciliation_separates_no_relation_from_monthly_pool_additions():
    relation_id = "R001"
    source = {"关系编号": relation_id, "code": "00001", "type": "BUSINESS_PEER",
        "asset_code": "AAPL", "fact": "Documented business exposure.",
        "segment": "Cloud software", "研究行业": "Software"}
    relation = {"relation_id": relation_id, "hk_code": "00001", "hk_name": "Mapped",
        "source_record": source, "recovery_v2r1": {"closure_status": "CLOSED_RESEARCH_SCOPE",
            "current_applicability_state": "CURRENT_RESEARCH_SCOPE",
            "use_scope": {"FACT_VERIFIED_SCOPE": {"state": "VERIFIED_DATED_FACT"}}}}
    catalog_row = {"symbol": "HK.00001", "record_role": "CATALOG_OBSERVATION",
        "catalog_relation_id": relation_id, "catalog_relation": relation}

    result = _single_day(["HK.00001", "HK.01528", "HK.09999"],
        catalog_rows=[catalog_row],
        catalog_stock_identities=[
            {"hk_code": "00001", "name": "Mapped"},
            {"hk_code": "01528", "name": "No relation"},
        ], catalog_expected_stock_count=2)

    reconciliation = result["catalog_stock_reconciliation"]
    assert result["catalog_consumption"]["relation_count"] == 1
    assert result["catalog_consumption"]["unique_relation_id_count"] == 1
    assert reconciliation["catalog_stock_identity_state"] == "READY"
    assert reconciliation["catalog_stock_count"] == 2
    assert reconciliation["relation_target_stock_count"] == 1
    assert reconciliation["catalog_stock_with_relation_count"] == 1
    assert reconciliation["no_relation_stock_count"] == 1
    assert reconciliation["no_relation_stocks"] == [
        {"symbol": "HK.01528", "name": "No relation"}]
    assert reconciliation["monthly_pool_stock_count"] == 3
    assert reconciliation["in_monthly_pool_stock_count"] == 2
    assert reconciliation["monthly_pool_not_in_catalog_stock_count"] == 1
    assert reconciliation["monthly_pool_not_in_catalog_stock_symbols"] == ["HK.09999"]


def test_single_day_catalog_placeholder_keeps_catalog_row_and_broad_sector_display_only():
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

    result = _single_day(["HK.00027"], relations=[catalog_observation], industries=[broad_c],
        catalog_rows=[catalog_observation],
        manual_quote_scope=_manual_quote_scope({"XLY": "0.8", "XLP": "0.2"}))

    row = result["rows"][0]
    assert row["decision"] == "OBSERVATION"
    assert row["reason"] == "C_MAPPING_OBSERVE_ONLY"
    assert len(result["catalog_relation_dispositions"]) == 1
    assert not any(path["source_type"] == "C_RELATIONSHIP_OBSERVATION"
        for path in row["mapping_paths"])
    assert any(path["source_type"] == "BROAD_SECTOR_BACKGROUND"
        and path["status"] == "VERIFIED" and path["signed_return_pct"] is None
        for path in row["mapping_paths"])


def test_single_day_uses_calendar_bound_sessions_for_ordinary_and_post_holiday_targets():
    from contracts.trading_calendar import load_market_calendar, next_session
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping
    calendar = load_market_calendar()
    post_holiday_target = next_session(calendar, "20261018", market="hk_connect")
    ordinary_target = next_session(calendar, post_holiday_target, market="hk_connect")
    assert post_holiday_target == "20261020"
    assert ordinary_target == "20261021"

    post_holiday = run_single_day_mapping(
        _single_context(post_holiday_target, us_session="20261016", hk_price_session="20261016"),
        relation_rows=[], industry_rows=[], factor_summary={},
        membership=_single_membership(["HK.00001"]))
    ordinary = run_single_day_mapping(
        _single_context(ordinary_target, us_session="20261020", hk_price_session="20261020",
            phase="NEXT_DAY"),
        relation_rows=[], industry_rows=[], factor_summary={},
        membership=_single_membership(["HK.00001"]))

    assert post_holiday["state"] != "CANNOT_CONFIRM"
    assert post_holiday["target_date"] == post_holiday_target
    assert ordinary["state"] != "CANNOT_CONFIRM"
    assert ordinary["target_date"] == ordinary_target


def test_single_day_rejects_source_session_on_or_after_target():
    context = _single_context("20261020", us_session="20261020", hk_price_session="20261016")
    from v4.manager_workbench.engines.strict_us_selection import run_single_day_mapping
    result = run_single_day_mapping(context, relation_rows=[], industry_rows=[],
        factor_summary={}, membership=_single_membership(["HK.00001"]))

    assert result["state"] == "CANNOT_CONFIRM"
    assert result["rows"] == []
    assert result["gaps"] == ["SINGLE_DAY_DATE_OR_PHASE_BINDING_MISMATCH"]
    assert result["formal_target_eligibility"] == "CANNOT_CONFIRM"
