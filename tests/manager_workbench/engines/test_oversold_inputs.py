from copy import deepcopy
from datetime import date,timedelta
from v4.manager_workbench.engines.common import RULE
from v4.manager_workbench.engines.oversold import run_oversold
from v4.manager_workbench.inputs import load_inputs


def ctx():
    return dict(market="HK_CONNECT",target_date="20261013",phase="PREOPEN",trigger="SCHEDULED",
        cutoff="2026-10-13T09:25:00+08:00",source_sessions={"HK":"20261012"},
        rules_version=RULE,scope_refs={})


def last_weekdays(before,count):
    days=[];d=before
    while len(days)<count:
        d-=timedelta(days=1)
        if d.weekday()<5:days.append(d.strftime("%Y%m%d"))
    return sorted(days)


def rec():
    previous="20261012";sixty=last_weekdays(date(2026,10,12),60);five=sixty[-5:]
    return dict(market="HK_CONNECT",target_date="20261013",symbol="HK.00001",name="oversold",
        owner="M02",source_sha256="a"*64,available_at="2026-10-13T09:00:00+08:00",
        evidence_ids=["over-1"],price_unit="HKD",volume_unit="SHARES",adjustment="RAW",
        membership=dict(verification="VERIFIED",owner="HK-monthly",sha256="b"*64,
            effective_from="20261001",effective_through="20261031",eligible=True,
            available_at="2026-10-12T17:00:00+08:00"),
        calendar=dict(verification="VERIFIED",sha256="c"*64,target_date="20261013",
            previous_session=previous,expected_high_sessions60=sixty,expected_volume_sessions5=five),
        previous_bar=dict(session=previous,close="80",volume="150",price_unit="HKD",volume_unit="SHARES",
            adjustment="RAW",available_at="2026-10-12T17:00:00+08:00"),
        high_history60=[dict(session=d,high="100",price_unit="HKD",adjustment="RAW") for d in sixty],
        volume_history5=[dict(session=d,volume="100",volume_unit="SHARES") for d in five])


def batch(items):
    return dict(lane="OVERSOLD",context=ctx(),universe_ref=dict(owner="M02",sha256="d"*64),
        scope_description="exact-date all eligible HKConnect",records=items,
        evidence_refs=[dict(evidence_id="over-1",owner="M02",role="panel",sha256="d"*64,
             verification="VERIFIED",available_at="2026-10-13T09:00:00+08:00")],
        input_sha256="e"*64,coverage=dict(scope_count=len(items),observed_count=len(items)),gaps=[])


def decision(r):return run_oversold(ctx(),batch([r]))["rows"][0]


def test_excludes_previous_session_from_both_baselines_and_accepts_boundaries():
    r=rec();out=decision(r)
    assert out["decision"]=="SELECTED"
    assert out["metrics"]["max_high_60"]=="100"
    assert out["metrics"]["volume_ratio"]=="1.5"


def test_price_only_and_volume_only_are_conditional_not_selected():
    r=rec();r["previous_bar"]["volume"]="149"
    assert decision(r)["decision"]=="CONDITIONAL_WATCH"
    r=rec();r["previous_bar"]["close"]="80.01"
    assert decision(r)["decision"]=="CONDITIONAL_WATCH"


def test_both_false_negative():
    r=rec();r["previous_bar"].update(close="90",volume="120")
    assert decision(r)["decision"]=="NOT_SELECTED"


def test_previous_day_cannot_be_in_60_or_5_history():
    r=rec();r["high_history60"][-1]["session"]="20261012"
    assert decision(r)["decision"]=="UNASSESSED"
    r=rec();r["volume_history5"][-1]["session"]="20261012"
    assert decision(r)["decision"]=="UNASSESSED"


def test_missing_history_and_duplicate_calendar_are_unassessed():
    r=rec();r["high_history60"].pop()
    assert decision(r)["decision"]=="UNASSESSED"
    r=rec();r["calendar"]["expected_high_sessions60"][3]=r["calendar"]["expected_high_sessions60"][2]
    assert decision(r)["decision"]=="UNASSESSED"


def test_wrong_units_and_zero_volume_denominator_unknown():
    r=rec();r["volume_history5"][0]["volume_unit"]="LOTS"
    assert decision(r)["decision"]=="UNASSESSED"
    r=rec()
    for x in r["volume_history5"]:x["volume"]="0"
    assert decision(r)["decision"]=="UNASSESSED"
    r=rec();r.pop("adjustment")
    assert decision(r)["decision"]=="UNASSESSED"


def test_stale_monthly_connect_is_unassessed_not_eligible():
    r=rec();r["membership"]["effective_through"]="20260930"
    assert decision(r)["decision"]=="UNASSESSED"
    r=rec();r["membership"]["eligible"]=False
    assert decision(r)["decision"]=="NOT_SELECTED"


def test_missing_adapter_not_empty_success():
    inputs=load_inputs(ctx(),{})
    assert inputs["OVERSOLD"]["coverage"]["scope_count"] is None
    assert "AUTHORITY_ADAPTER_NOT_BOUND" in inputs["OVERSOLD"]["gaps"]


def test_injected_owner_only_and_wrong_context_denied():
    c=ctx();a=batch([rec()])
    inp=load_inputs(c,{"OVERSOLD":lambda x:a})
    assert inp["OVERSOLD"]["input_sha256"]=="e"*64
    wrong=deepcopy(a);wrong["context"]["target_date"]="20261012"
    inp=load_inputs(c,{"OVERSOLD":lambda x:wrong})
    assert "AUTHORITY_CONTEXT_MISMATCH" in inp["OVERSOLD"]["gaps"]
