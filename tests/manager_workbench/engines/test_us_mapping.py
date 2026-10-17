from copy import deepcopy
from v4.manager_workbench.engines.common import RULE
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
    summary = {
        "state": "READY",
        "stock_count": 667,
        "relation_count": 1003,
        "status_counts": {
            "CLOSED_RESEARCH_SCOPE": 757,
            "OPEN": 221,
            "CLOSED_EXCLUDED_SCOPE": 25,
        },
        "catalog_file_sha256": "e" * 64,
        "review_overlay_file_sha256": "f" * 64,
        "recovery_overlay_integrity_sha256": "a" * 64,
    }
    data["context"]["scope_refs"]["US_MAPPING"]["full_overlay_summary"] = summary
    for index in range(1003):
        relation = {
            "target_symbol": "HK.00001",
            "target_name": "catalog observation",
            "status": "CANNOT_CONFIRM",
            "sha256": format(index + 1, "064x"),
            "relation_type": "CATALOG_OBSERVATION_ONLY",
            "research_priority": "NONE",
            "catalog_relation": {
                "relation_id": f"R{index + 1:04d}",
                "source_review_status": "NOT_PROCESSED",
                "research_use": "PENDING_REVIEW",
                "recovery_v2r1": {"closure_status": "CLOSED_RESEARCH_SCOPE"},
            },
            "catalog_relation_id": f"R{index + 1:04d}",
            "catalog_research_use": "PENDING_REVIEW",
            "catalog_recovery_status": "CLOSED_RESEARCH_SCOPE",
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
    assert sum(row.get("catalog_relation_id") is not None for row in result["rows"]) == 1003
    assert all(row["decision"] != "SELECTED" for row in result["rows"])
    assert result["coverage"]["scope_count"] == 33
