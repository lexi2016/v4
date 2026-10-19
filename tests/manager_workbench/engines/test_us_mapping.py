from copy import deepcopy
from collections import Counter
import hashlib
import pytest
from v4.manager_workbench.engines.common import RULE
from v4.manager_workbench.engines.core import merge_decisions
from v4.manager_workbench.engines.us_mapping import run_us_mapping as _run_us_mapping
from v4.manager_workbench.inputs.us_universe import (
    LEGACY_US_SYMBOLS,
    build_us_universe_contract,
)

def run_us_mapping(context, batch):
    return _run_us_mapping(batch["context"],batch)


def ctx():
    return dict(market="HK_CONNECT",target_date="20261013",phase="PREOPEN",trigger="SCHEDULED",
        cutoff="2026-10-13T09:25:00+08:00",source_sessions={"US":"20261012"},
        rules_version=RULE,scope_refs={})


def eligible():
    return dict(verification="VERIFIED",owner="M02",sha256="b"*64,eligible=True,
        effective_from="20261001",effective_through="20261031",available_at="2026-10-12T17:00:00+08:00")


def make_batch():
    symbols=list(LEGACY_US_SYMBOLS)
    records=[]
    for sym in symbols:
        records.append(dict(us_symbol=sym,source_session="20261012",source_status="PRIORITY",owner="US-owner",
            source_sha256="a"*64,available_at="2026-10-13T09:00:00+08:00",
            relations=[dict(status="REVIEWED",sha256="b"*64,review_owner="reviewer",
                target_symbol="HK.00001",target_name="company",relation_type="OBSERVED_SUPPLY_RELATION",
                available_at="2026-10-13T09:00:00+08:00",published_at="2026-10-12T17:00:00+08:00",
                membership=eligible())]))
    universe_ref="us:LEGACY_US_UNIVERSE_V1:20261013"
    c=ctx();c["scope_refs"]["US_MAPPING"]=dict(universe_ref=universe_ref,configured_symbols=symbols,source_session="20261012",verification="VERIFIED",
            calendar_verified=True,sha256="c"*64)
    return dict(lane="US_MAPPING",context=c,records=records,evidence_refs=[],
        universe_ref=universe_ref,input_sha256="d"*64,scope_description="fixed 33 US origins",
        coverage=dict(scope_count=33,observed_count=33),gaps=[])


def test_reviewed_relation_not_strict_selected():
    data=make_batch();r=run_us_mapping(ctx(),data)
    assert r["state"]=="READY"
    assert r["rows"][0]["decision"]=="CONDITIONAL_WATCH"
    assert not any(x["decision"]=="SELECTED" for x in r["rows"])
    assert r["coverage"]["scope_count"]==33


def test_unreviewed_relation_and_late_publication_unknown():
    a=make_batch();a["records"][0]["relations"][0]["status"]="UNREVIEWED"
    assert run_us_mapping(ctx(),a)["rows"][0]["decision"]=="UNASSESSED"
    b=make_batch();b["records"][0]["relations"][0]["available_at"]="2026-10-13T09:26:00+08:00"
    assert run_us_mapping(ctx(),b)["rows"][0]["decision"]=="UNASSESSED"


@pytest.mark.parametrize("change_pct", [0, -1.25])
@pytest.mark.parametrize("relation_status", ["PROPOSED", "REVIEWED"])
def test_valid_nonpositive_trigger_is_path_local_and_retains_unknown_qualification(change_pct, relation_status):
    data = make_batch()
    source = data["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": change_pct})
    relation = source["relations"][0]
    relation.update(
        status=relation_status,
        membership=None,
        relation_source_refs=[{"artifact_ref": "relation-body.json", "sha256": "f" * 64}],
        publication_time_gaps=["RELATION_SOURCE_PUBLICATION_TIME_UNKNOWN"],
    )
    if relation_status == "PROPOSED":
        relation["pit_status"] = "PIT_UNCONFIRMED"

    row = run_us_mapping(ctx(), data)["rows"][0]

    assert row["decision"] == "NOT_SELECTED"
    assert row["reason"] == "US_SOURCE_CHANGE_NOT_POSITIVE"
    assert row["symbol"] == "HK.00001"
    assert row["conditions"] == ["DIRECT_RELATION_PATH_ONLY", "NOT_STOCK_LEVEL_DECISION"]
    assert row["path_disposition_scope"] == "DIRECT_US_HK_RELATION_ONLY"
    assert row["membership"] is None
    assert row["relation_status"] == relation_status
    assert row["relation_pit_status"] == relation.get("pit_status")
    assert row["relation_source_refs"] == relation["relation_source_refs"]
    assert row["publication_time_gaps"] == relation["publication_time_gaps"]
    assert "CONNECT_MEMBERSHIP_UNKNOWN" in row["diagnostic_gaps"]
    if relation_status == "PROPOSED":
        assert "US_RELATION_PROPOSED_PIT_UNCONFIRMED" in row["diagnostic_gaps"]


@pytest.mark.parametrize("change_pct", [None, True, float("nan"), float("inf"), "NaN", "invalid"])
def test_invalid_or_missing_quote_cannot_dispose_direct_relation_path(change_pct):
    data = make_batch()
    source = data["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": change_pct})
    source["relations"][0].update(status="PROPOSED", pit_status="PIT_UNCONFIRMED", membership=None)

    row = run_us_mapping(ctx(), data)["rows"][0]

    assert row["decision"] == "UNASSESSED"
    assert row["reason"] == "US_RELATION_PROPOSED_PIT_UNCONFIRMED"


def test_quote_gap_and_unverified_source_cannot_dispose_direct_relation_path():
    quote_gap = make_batch()
    source = quote_gap["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": -1.0},
        quote_missing_reason="US_QUOTE_SOURCE_GAP", source_gaps=["US_QUOTE_SOURCE_GAP"])
    assert run_us_mapping(ctx(), quote_gap)["rows"][0]["decision"] == "UNASSESSED"
    assert run_us_mapping(ctx(), quote_gap)["rows"][0]["reason"] == "US_SOURCE_CHANGE_EVIDENCE_UNVERIFIED"

    unverified = make_batch()
    source = unverified["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": -1.0}, source_sha256="invalid")
    assert run_us_mapping(ctx(), unverified)["rows"][0]["decision"] == "UNASSESSED"


def test_negative_quote_requires_exact_true_trigger_flag_and_valid_hk_target():
    wrong_flag = make_batch()
    wrong_flag["records"][0].update(positive_change_required=1, quote={"change_pct": -1.0})
    wrong_flag_row = run_us_mapping(ctx(), wrong_flag)["rows"][0]
    assert wrong_flag_row["decision"] == "UNASSESSED"
    assert wrong_flag_row["reason"] == "US_SOURCE_CHANGE_EVIDENCE_UNVERIFIED"

    invalid_target = make_batch()
    source = invalid_target["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": -1.0})
    source["relations"][0].update(status="PROPOSED", pit_status="PIT_UNCONFIRMED", target_symbol="not-hk")
    invalid_target_row = run_us_mapping(ctx(), invalid_target)["rows"][0]
    assert invalid_target_row["decision"] == "UNASSESSED"
    assert invalid_target_row["symbol"] is None

    no_relation = make_batch()
    no_relation["records"][0].update(positive_change_required=True, quote={"change_pct": -1.0}, relations=[])
    no_relation_row = run_us_mapping(ctx(), no_relation)["rows"][0]
    assert no_relation_row["decision"] == "UNASSESSED"
    assert no_relation_row["symbol"] is None


def test_mixed_positive_unknown_path_keeps_aggregate_stock_unassessed():
    data = make_batch()
    negative, positive = data["records"][:2]
    negative.update(positive_change_required=True, quote={"change_pct": -1.0})
    negative["relations"][0].update(target_symbol="HK.00002", membership=None)
    positive.update(positive_change_required=True, quote={"change_pct": 1.0})
    positive["relations"][0].update(target_symbol="HK.00002", status="PROPOSED",
        pit_status="PIT_UNCONFIRMED", membership=None)
    for source in data["records"][2:]:
        source["relations"] = []

    lane = run_us_mapping(ctx(), data)
    target_paths = [row for row in lane["rows"] if row.get("symbol") == "HK.00002"]
    stocks = merge_decisions(data["context"], [lane])

    assert {row["decision"] for row in target_paths} == {"NOT_SELECTED", "UNASSESSED"}
    assert len(target_paths) == 2
    assert next(stock for stock in stocks if stock["symbol"] == "HK.00002")["decision"] == "UNASSESSED"


def test_verified_positive_reviewed_path_keeps_existing_conditional_watch_result():
    data = make_batch()
    source = data["records"][0]
    source.update(positive_change_required=True, quote={"change_pct": 0.5})

    row = run_us_mapping(ctx(), data)["rows"][0]

    assert row["decision"] == "CONDITIONAL_WATCH"
    assert row["reason"] == "US_REVIEWED_RELATION_CONDITIONAL_ONLY"
    assert "path_disposition_scope" not in row


def test_34th_or_lost_origin_causes_coverage_gap():
    a=make_batch();a["records"].pop()
    r=run_us_mapping(ctx(),a)
    assert r["state"]=="PARTIAL"
    assert "US_SOURCE_33_COVERAGE_INCOMPLETE" in r["gaps"]


def test_calendar_unknown_blocks_priority():
    a=make_batch();a["context"]["scope_refs"]["US_MAPPING"]["calendar_verified"]=False
    assert run_us_mapping(ctx(),a)["rows"][0]["decision"]=="UNASSESSED"


def test_no_reviewed_relationship_remains_unknown():
    a=make_batch();a["records"][0]["relations"]=[]
    r=run_us_mapping(ctx(),a)
    assert r["rows"][0]["symbol"] is None
    assert r["rows"][0]["decision"]=="UNASSESSED"


def test_single_us_origin_can_have_two_distinct_hk_relations_without_inflating_33():
    a=make_batch();second=deepcopy(a["records"][0]["relations"][0]);second["target_symbol"]="HK.00002"
    a["records"][0]["relations"].append(second)
    r=run_us_mapping(ctx(),a)
    assert len(r["rows"])==34
    assert r["coverage"]["assessed_count"]==33


def test_v3_48_symbol_scope_and_proposed_relations_remain_observation_only():
    contract = build_us_universe_contract()
    c = ctx()
    universe_ref = "us:" + contract["version"] + ":" + c["target_date"]
    c["scope_refs"]["US_MAPPING"] = dict(
        universe_ref=universe_ref,
        configured_symbols=contract["symbols"],
        universe_version=contract["version"],
        universe_contract=contract,
        universe_contract_sha256=contract["contract_sha256"],
        source_session="20261012",
        verification="VERIFIED",
        calendar_verified=True,
        sha256="c" * 64,
    )
    records = [
        dict(
            us_symbol=symbol,
            source_session="20261012",
            source_status="CANNOT_CONFIRM",
            owner="US-owner",
            source_sha256="a" * 64,
            available_at="2026-10-13T09:00:00+08:00",
            positive_change_required=True,
            quote={"change_pct": 1.0},
            relations=[dict(
                status="PROPOSED",
                pit_status="PIT_UNCONFIRMED",
                target_symbol="HK.00700",
                target_name="Tencent Holdings",
                relation_type="BUSINESS_SEGMENT_PEER",
                relation_source_refs=[{"url": "https://example.invalid/filing"}],
            )],
        )
        for symbol in contract["symbols"]
    ]
    data = dict(context=c, records=records, lane="US_MAPPING", evidence_refs=[],
        universe_ref=universe_ref, input_sha256="d" * 64,
        scope_description="48 configured US observations",
        coverage=dict(scope_count=48, observed_count=48), gaps=[])
    result = run_us_mapping(ctx(), data)
    assert result["coverage"]["scope_count"] == 48
    assert len(result["rows"]) == 48
    assert {row["decision"] for row in result["rows"]} == {"UNASSESSED"}
    assert {row["reason"] for row in result["rows"]} == {"US_RELATION_PROPOSED_PIT_UNCONFIRMED"}
    assert not any(row["decision"] == "SELECTED" for row in result["rows"])

    data["records"].pop()
    incomplete = run_us_mapping(ctx(), data)
    assert "US_SOURCE_UNIVERSE_COVERAGE_INCOMPLETE" in incomplete["gaps"]


def test_unknown_universe_version_is_rejected_as_unassessed():
    data = make_batch()
    context = data["context"]
    scope = context["scope_refs"]["US_MAPPING"]
    scope["universe_version"] = "US_MAPPING_UNIVERSE_CONTRACT_V9"
    scope["universe_ref"] = "us:US_MAPPING_UNIVERSE_CONTRACT_V9:20261013"
    data["universe_ref"] = scope["universe_ref"]

    result = run_us_mapping(context, data)

    assert "US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED" in result["gaps"]
    assert {row["decision"] for row in result["rows"]} == {"UNASSESSED"}
    assert not any(row["decision"] == "CONDITIONAL_WATCH" for row in result["rows"])



def test_full_overlay_relations_are_consumed_as_non_selectable_observations():
    data = make_batch()
    closure_statuses = (["CLOSED_RESEARCH_SCOPE"] * 757 + ["OPEN"] * 221
                        + ["CLOSED_EXCLUDED_SCOPE"] * 25)
    research_uses = (["PENDING_REVIEW"] * 985 + ["BACKGROUND_HISTORICAL"] * 10
                     + ["EXCLUDED_CURRENT"] * 5 + ["CONDITIONAL_OBSERVATION"] * 3)
    summary = {
        "state": "READY",
        "stock_count": 667,
        "relation_count": 1003,
        "status_counts": dict(Counter(closure_statuses)),
        "catalog_file_sha256": "e" * 64,
        "review_overlay_file_sha256": "f" * 64,
        "recovery_overlay_integrity_sha256": "a" * 64,
    }
    data["context"]["scope_refs"]["US_MAPPING"]["full_overlay_summary"] = summary
    for index in range(1003):
        relation_id = f"R{index + 1:04d}"
        field_sha256 = {
            field: hashlib.sha256(f"{relation_id}:{field}".encode()).hexdigest()
            for field in ("fact", "mechanism", "condition", "direction", "timescale", "failure", "reporting_period")
        }
        use_scope = {
            "FACT_VERIFIED_SCOPE": {"state": "VERIFIED_DATED_FACT", "relation_id": relation_id},
            "CURRENT_APPLICABILITY": {"state": "PENDING_CURRENT_CHECK", "relation_id": relation_id},
        }
        relation = {
            "target_symbol": f"HK.{index % 667 + 1:05d}",
            "target_name": "catalog observation",
            "status": "CANNOT_CONFIRM",
            "sha256": hashlib.sha256(relation_id.encode()).hexdigest(),
            "relation_type": "CATALOG_OBSERVATION_ONLY",
            "research_priority": "NONE",
            "catalog_relation": {
                "relation_id": relation_id,
                "source_row": index + 1,
                "source_review_status": "SOURCE_REVIEWED" if index < 700 else "NOT_PROCESSED",
                "independent_verification": "NOT_RUN",
                "research_use": research_uses[index],
                "recovery_v2r1": {
                    "relation_id": relation_id,
                    "closure_status": closure_statuses[index],
                    "primary_research_use": research_uses[index],
                    "field_sha256": field_sha256,
                    "use_scope": use_scope,
                },
            },
            "catalog_relation_id": relation_id,
            "catalog_research_use": research_uses[index],
            "catalog_recovery_status": closure_statuses[index],
        }
        data["records"].append({
            "us_symbol": None,
            "source_session": "20261012",
            "source_status": "CATALOG_OBSERVATION",
            "owner": "v4.manager_workbench.us_mapping_catalog",
            "source_sha256": "e" * 64,
            "available_at": None,
            "positive_change_required": False,
            "quote": {},
            "relations": [relation],
            "evidence_ids": [],
        })

    result = run_us_mapping(ctx(), data)
    summary_row = next(row for row in result["rows"] if "us_mapping_catalog_summary" in row)

    assert summary_row["us_mapping_catalog_summary"]["stock_count"] == 667
    assert summary_row["us_mapping_catalog_summary"]["relation_count"] == 1003
    assert summary_row["us_mapping_catalog_summary"]["consumed_relation_count"] == 1003
    catalog_rows = [row for row in result["rows"] if row.get("catalog_relation_id") is not None]
    assert len(catalog_rows) == len({row["catalog_relation_id"] for row in catalog_rows}) == 1003
    assert len({row["symbol"] for row in catalog_rows}) == 667
    assert Counter(row["catalog_recovery_status"] for row in catalog_rows) == Counter(summary["status_counts"])
    assert Counter(row["catalog_research_use"] for row in catalog_rows) == Counter(research_uses)
    assert Counter(row["catalog_relation"]["source_review_status"] for row in catalog_rows) == {
        "SOURCE_REVIEWED": 700, "NOT_PROCESSED": 303,
    }
    for index, row in enumerate(catalog_rows):
        relation_id = f"R{index + 1:04d}"
        recovery = row["catalog_relation"]["recovery_v2r1"]
        expected_field_sha = {
            field: hashlib.sha256(f"{relation_id}:{field}".encode()).hexdigest()
            for field in ("fact", "mechanism", "condition", "direction", "timescale", "failure", "reporting_period")
        }
        assert row["catalog_relation"]["relation_id"] == relation_id
        assert row["decision"] == "UNASSESSED"
        assert row["relation_status"] == "CANNOT_CONFIRM"
        assert row["catalog_research_use"] == research_uses[index]
        assert row["catalog_recovery_status"] == closure_statuses[index]
        assert recovery["field_sha256"] == expected_field_sha
        assert recovery["use_scope"] == {
            "FACT_VERIFIED_SCOPE": {"state": "VERIFIED_DATED_FACT", "relation_id": relation_id},
            "CURRENT_APPLICABILITY": {"state": "PENDING_CURRENT_CHECK", "relation_id": relation_id},
        }
    assert all(row["decision"] != "SELECTED" for row in result["rows"])
    assert result["coverage"]["scope_count"] == 33
    assert result["coverage"]["observed_count"] == 33
    assert result["coverage"]["assessed_count"] == 33
    assert result["coverage"]["unassessed_count"] == 0
    assert "OBSERVED_COUNT_MISMATCH" not in result["gaps"]
    assert "SCOPE_COUNT_MISMATCH" not in result["gaps"]
    assert "US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH" not in result["gaps"]


def test_us_mapping_entry_runs_single_day_candidate_aggregation_for_ordinary_session(monkeypatch):
    import json
    import v4.manager_workbench.engines.us_mapping as mapping_module
    from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION

    data = make_batch()
    context = data["context"]
    context["rules_version"] = US_FACTOR_RULES_VERSION
    context["phase"] = "NEXT_DAY"
    context["target_date"] = "20261021"
    context["cutoff"] = "2026-10-21T09:25:00+08:00"
    context["source_sessions"] = {"US": "20261020", "us": "20261020",
        "HK_PRICE": "20261020", "hk_price": "20261020"}
    context["scope_refs"]["US_MAPPING"]["source_session"] = "20261020"
    for record in data["records"]:
        record["source_session"] = "20261020"

    codes = ["HK.00001"]
    membership = {"status": "VERIFIED", "market": "HK_CONNECT",
        "owner": "FUTU_HKCONNECT_PLATE_MEMBERSHIP", "target_month": "202610",
        "source_date": "20261012", "artifact_sha256": "f" * 64, "codes": codes,
        "codes_sha256": hashlib.sha256(json.dumps(
            {"market": "HK_CONNECT", "codes": codes}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()}
    data["records"][0]["us_factor_payload"] = {
        "single_day_mapping_payload": {"monthly_membership": membership},
        "manual_quote_scope": None,
    }
    monkeypatch.setattr(mapping_module, "run_us_factor", lambda *_: ([], {
        "display_only": True, "factor_decision_counts": {},
        "industry_summary": {"source_status": "READY", "source_asof": "20261020"},
    }))

    result = run_us_mapping(context, data)
    holder = next(row for row in result["rows"] if "us_factor_summary" in row)
    single_day = holder["us_factor_summary"]["single_day_mapping"]

    assert single_day["target_date"] == "20261021"
    assert single_day["source_session"] == "20261020"
    assert single_day["state"] != "CANNOT_CONFIRM"
    assert single_day["catalog_candidate_ordering"] == (
        "QUALIFICATION_THEN_SOURCE_DIRECTION_THEN_POSITIVE_US_SOURCE_RETURN_DESC_THEN_HK_CODE")


def test_real_us_mapping_entry_quarantines_excluded_use_and_invalid_manual_quotes(monkeypatch):
    import json
    import v4.manager_workbench.engines.us_mapping as mapping_module
    from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
    from v4.manager_workbench.engines.us_mapping_consumption import (
        MANUAL_QUOTE_OWNER, MANUAL_QUOTE_SCOPE_SHA256,
    )

    data = make_batch()
    context = data["context"]
    context["rules_version"] = US_FACTOR_RULES_VERSION
    context["phase"] = "NEXT_DAY"
    context["target_date"] = "20261021"
    context["cutoff"] = "2026-10-21T09:25:00+08:00"
    context["source_sessions"] = {"US": "20261020", "us": "20261020",
        "HK_PRICE": "20261020", "hk_price": "20261020"}
    context["scope_refs"]["US_MAPPING"]["source_session"] = "20261020"
    for record in data["records"]:
        record["source_session"] = "20261020"

    codes = ["HK.00001", "HK.00002", "HK.00003", "HK.00004", "HK.00005", "HK.00006"]
    membership = {"status": "VERIFIED", "market": "HK_CONNECT",
        "owner": "FUTU_HKCONNECT_PLATE_MEMBERSHIP", "target_month": "202610",
        "source_date": "20261012", "artifact_sha256": "f" * 64, "codes": codes,
        "codes_sha256": hashlib.sha256(json.dumps(
            {"market": "HK_CONNECT", "codes": codes}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()}

    def quote(symbol, change_pct, *, last=None, previous_close="100"):
        return {"symbol": symbol, "session_date": "20261020", "session_time": "16:00:02",
            "last": str(last if last is not None else 100 * (1 + float(change_pct) / 100)),
            "previous_close": previous_close, "change_pct": str(change_pct)}

    manual_quotes = {
        # A matching map key must not override the different inner quote identity.
        "BAD": {"symbol": "WMT", "session_date": "20261020", "session_time": "16:00:02",
            "change_pct": "80"},
        # A matching identity and numeric change_pct still need valid prices.
        "NOPREV": {"symbol": "NOPREV", "session_date": "20261020", "session_time": "16:00:02",
            "last": "101", "change_pct": "1"},
        "BADRETURN": quote("BADRETURN", "1", last="120"),
        "NONFINITE": {"symbol": "NONFINITE", "session_date": "20261020", "session_time": "16:00:02",
            "last": "NaN", "previous_close": "100", "change_pct": "NaN"},
        "GOOD": quote("GOOD", "1.25", last="101.25"),
    }
    binding = {"state": "PARTIAL", "owner": MANUAL_QUOTE_OWNER,
        "scope_sha256": MANUAL_QUOTE_SCOPE_SHA256, "us_session_date": "20261020",
        "available_at": "2026-10-21T06:00:00+08:00", "payload_sha256": "a" * 64,
        "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64,
        "quotes": manual_quotes, "symbol_gaps": {}}
    data["records"][0]["us_factor_payload"] = {
        "single_day_mapping_payload": {"monthly_membership": membership},
        "manual_quote_scope": binding,
    }

    def catalog_record(relation_id, code, us_symbol, research_use):
        source = {"关系编号": relation_id, "code": code, "type": "BUSINESS_PEER",
            "asset_code": us_symbol, "fact": "Named synthetic business relation.",
            "segment": "Cloud software", "研究行业": "Software"}
        relation = {"relation_id": relation_id, "hk_code": code, "hk_name": f"Target {code}",
            "research_use": research_use, "source_record": source,
            "recovery_v2r1": {"closure_status": "CLOSED_RESEARCH_SCOPE",
                "current_applicability_state": "CURRENT_RESEARCH_SCOPE",
                "fact_state": "FACT_SCOPE_RECORDED", "identity_state": "IDENTITY_SCOPE_RECORDED"}}
        return {"record_role": "CATALOG_OBSERVATION", "source_session": "20261020",
            "source_status": "CATALOG_OBSERVATION", "owner": "v4.manager_workbench.us_mapping_catalog",
            "source_sha256": "d" * 64, "available_at": "2026-10-21T05:00:00+08:00",
            "positive_change_required": False, "quote": {}, "evidence_ids": [],
            "relations": [{"status": "CANNOT_CONFIRM", "target_symbol": f"HK.{code}",
                "target_name": f"Target {code}", "relation_type": "BUSINESS_PEER",
                "catalog_relation_id": relation_id, "catalog_research_use": research_use,
                "catalog_relation": relation}]}

    data["records"].extend([
        catalog_record("R-EXCLUDED", "00001", "GOOD", "EXCLUDED_CURRENT"),
        catalog_record("R-BAD-QUOTE", "00002", "BAD", "CONDITIONAL_OBSERVATION"),
        catalog_record("R-NO-PREV", "00003", "NOPREV", "CONDITIONAL_OBSERVATION"),
        catalog_record("R-BAD-RETURN", "00005", "BADRETURN", "CONDITIONAL_OBSERVATION"),
        catalog_record("R-NONFINITE", "00006", "NONFINITE", "CONDITIONAL_OBSERVATION"),
        catalog_record("R-GOOD", "00004", "GOOD", "CONDITIONAL_OBSERVATION"),
    ])
    monkeypatch.setattr(mapping_module, "run_us_factor", lambda *_: ([], {
        "display_only": True, "factor_decision_counts": {},
        "industry_summary": {"source_status": "READY", "source_asof": "20261020"},
    }))

    result = run_us_mapping(context, data)
    holder = next(row for row in result["rows"] if "us_factor_summary" in row)
    single_day = holder["us_factor_summary"]["single_day_mapping"]
    dispositions = {row["catalog_relation_id"]: row
        for row in single_day["catalog_relation_dispositions"]}
    candidates = {row["symbol"]: row for row in single_day["catalog_candidates"]}

    mismatched = dispositions["R-BAD-QUOTE"]
    assert mismatched["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert mismatched["quote_missing_reason"] == "MANUAL_QUOTE_SYMBOL_MISMATCH"
    missing_price = dispositions["R-NO-PREV"]
    assert missing_price["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert missing_price["quote_missing_reason"] == "MANUAL_QUOTE_PRICE_INVALID"
    assert candidates["HK.00002"]["direction_group"] == "FLAT_OR_UNKNOWN"
    assert candidates["HK.00002"]["unknown_relation_ids"] == ["R-BAD-QUOTE"]
    assert candidates["HK.00003"]["direction_group"] == "FLAT_OR_UNKNOWN"
    assert candidates["HK.00003"]["unknown_relation_ids"] == ["R-NO-PREV"]
    bad_return = dispositions["R-BAD-RETURN"]
    assert bad_return["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert bad_return["quote_missing_reason"] == "MANUAL_QUOTE_RETURN_MISMATCH"
    assert candidates["HK.00005"]["direction_group"] == "FLAT_OR_UNKNOWN"
    nonfinite = dispositions["R-NONFINITE"]
    assert nonfinite["quote_status"] == "MISSING_OR_UNVERIFIED"
    assert nonfinite["quote_missing_reason"] == "MANUAL_QUOTE_PRICE_INVALID"
    assert candidates["HK.00006"]["direction_group"] == "FLAT_OR_UNKNOWN"
    assert candidates["HK.00004"]["direction_group"] == "POSITIVE_WITHOUT_NEGATIVE"
    assert candidates["HK.00004"]["positive_relation_ids"] == ["R-GOOD"]

    excluded = dispositions["R-EXCLUDED"]
    assert excluded["catalog_disposition"] == "EXCLUDED_FOR_SPECIFIED_RESEARCH_USE"
    assert excluded["catalog_disposition_reason"] == "CATALOG_RESEARCH_USE_EXPLICITLY_EXCLUDED"
    assert "HK.00001" not in candidates
