from copy import deepcopy
from v4.manager_workbench.engines.common import RULE
from v4.manager_workbench.engines.us_mapping import run_us_mapping as _run_us_mapping

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
    symbols=[f"US{i:02}" for i in range(33)]
    records=[]
    for sym in symbols:
        records.append(dict(us_symbol=sym,source_session="20261012",source_status="PRIORITY",owner="US-owner",
            source_sha256="a"*64,available_at="2026-10-13T09:00:00+08:00",
            relations=[dict(status="REVIEWED",sha256="b"*64,review_owner="reviewer",
                target_symbol="HK.00001",target_name="company",relation_type="OBSERVED_SUPPLY_RELATION",
                available_at="2026-10-13T09:00:00+08:00",published_at="2026-10-12T17:00:00+08:00",
                membership=eligible())]))
    c=ctx();c["scope_refs"]["US_MAPPING"]=dict(universe_ref="M03:fixed-us-33",configured_symbols=symbols,source_session="20261012",verification="VERIFIED",
            calendar_verified=True,sha256="c"*64)
    return dict(lane="US_MAPPING",context=c,records=records,evidence_refs=[],
        universe_ref="M03:fixed-us-33",input_sha256="d"*64,scope_description="fixed 33 US origins",
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
