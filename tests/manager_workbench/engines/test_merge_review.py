from copy import deepcopy
from v4.manager_workbench.engines.common import RULE,VERSION
from v4.manager_workbench.engines import merge_decisions as _merge, evaluate_review as _review, run_lanes as _lanes
from v4.manager_workbench.engines.common import plain

def merge_decisions(*args):return [plain(v) for v in _merge(*args)]
def evaluate_review(*args):return plain(_review(*args))
def run_lanes(*args):return {k:plain(v) for k,v in _lanes(*args).items()}



def context():
    return dict(market="HK_CONNECT",target_date="20261013",phase="PREOPEN",
                trigger="SCHEDULED",cutoff="2026-10-13T09:25:00+08:00",
                rules_version=RULE,source_sessions={},scope_refs={"review_universe":"full-connect","run_id":"freeze-1"})


def lane(name,rows,state="READY"):
    return dict(lane=name,state=state,rows=rows,coverage=dict(scope_count=len(rows),
        observed_count=len(rows),assessed_count=len(rows),unassessed_count=0,gaps=[]),
        input_sha256="a"*64,rules_version=RULE,run_id="x",evidence_refs=[],gaps=[])


def stock(code,decision):
    return dict(market="HK_CONNECT",symbol="HK."+code,name=code,decision=decision,
        evidence_ids=[],conditions=[],invalidation_conditions=[],risks=[],reason=decision,
        membership=dict(verification="VERIFIED",eligible=True,owner="M02",sha256="b"*64,
            effective_from="20261001",effective_through="20261031",available_at="2026-10-12T17:00:00+08:00"))


def test_complete_long_run_over_200_untruncated():
    c=context()
    expected=[stock(f"{i:05d}","SELECTED") for i in range(1,251)]
    l=[lane("ANNOUNCEMENT",expected)]
    decisions=merge_decisions(c,l)
    assert len(decisions)==250
    assert sum(x["decision"]=="SELECTED" for x in decisions)==250


def test_selected_lane_survives_other_failure():
    r=merge_decisions(context(),[lane("ANNOUNCEMENT",[stock("00001","SELECTED")]),lane("OVERSOLD",[],"FAILED")])
    assert r[0]["decision"]=="SELECTED"


def test_observation_is_never_automatically_selected():
    r=merge_decisions(context(),[lane("STAGE_REFERENCE",[stock("00001","OBSERVATION_ONLY")])])
    assert r[0]["decision"]=="OBSERVATION_ONLY"


def test_negative_with_failed_other_lane_is_unknown():
    r=merge_decisions(context(),[lane("ANNOUNCEMENT",[stock("00001","NOT_SELECTED")]),lane("OVERSOLD",[],"FAILED")])
    assert r[0]["decision"]=="UNASSESSED"


def test_duplicate_across_lanes_preserves_provenance():
    r=merge_decisions(context(),[lane("ANNOUNCEMENT",[stock("00001","CONDITIONAL_WATCH")]),
                                     lane("OVERSOLD",[stock("00001","SELECTED")])])
    assert r[0]["decision"]=="SELECTED"
    assert len(r[0]["lane_decisions"])==2


def test_review_complete_strict_and_extended_distinct():
    stocks=merge_decisions(context(),[lane("ANNOUNCEMENT",[stock("00001","SELECTED")]),
        lane("US_MAPPING",[stock("00002","CONDITIONAL_WATCH")]),lane("OVERSOLD",[stock("00003","SELECTED")])])
    plan=dict(schema_version=VERSION,context=context(),run_id="freeze-1",stocks=stocks)
    close=dict(market="HK_CONNECT",target_date="20261013",ranking_date="20261013",full_scope_verified=True,
        scope_ref="full-connect",source_sha256="c"*64,owner="closing-authority",
        scope_count=20,rows=[dict(rank=i,symbol=f"HK.{i:05d}") for i in range(1,21)])
    out=evaluate_review(plan,close)
    assert out["strict_coverage"]["covered"]==2
    assert out["extended_coverage"]["covered"]==3
    assert out["strict_coverage"]["denominator"]==20
    assert out["lane_incremental_coverage"]["US_MAPPING"]["strict_added"]==0
    assert out["lane_incremental_coverage"]["US_MAPPING"]["extended_added"]==1
    assert len(out["top20_rows"])==20


def test_missing_close_authority_never_reports_zero_coverage():
    plan=dict(schema_version=VERSION,context=context(),run_id="freeze-1",stocks=[])
    out=evaluate_review(plan,None)
    assert out["strict_coverage"]["ratio"] is None
    assert out["strict_coverage"]["denominator"] is None
    assert out["mode"]=="NOT_EVALUATED"


def test_zero_denominator_is_null_not_zero_ratio():
    plan=dict(schema_version=VERSION,context=context(),run_id="freeze-1",stocks=[])
    close=dict(market="HK_CONNECT",target_date="20261013",ranking_date="20261013",full_scope_verified=True,
        scope_ref="full-connect",source_sha256="c"*64,owner="closing-authority",
        scope_count=0,rows=[])
    out=evaluate_review(plan,close)
    assert out["strict_coverage"]["covered"]==0
    assert out["strict_coverage"]["denominator"]==0
    assert out["strict_coverage"]["ratio"] is None


def test_stage_does_not_consume_unauthorized_final_rank_as_research_input():
    c=context(); batch=dict(context=c,lane="STAGE_REFERENCE",records=[dict(market="HK_CONNECT",
        symbol="HK.00001",name="stage",target_date="20261013",owner="stage-owner",source_sha256="a"*64,
        available_at="2026-10-13T09:00:00+08:00")],universe_ref="stage:exact-owner",
        evidence_refs=[],input_sha256="a"*64,scope_description="stage",coverage=dict(scope_count=1,observed_count=1),gaps=[])
    inputs={"STAGE_REFERENCE":batch}
    r=run_lanes(c,inputs,None)
    assert r["STAGE_REFERENCE"]["rows"][0]["decision"]=="OBSERVATION_ONLY"
    assert r["ANNOUNCEMENT"]["state"]=="INPUT_MISSING"


def test_missing_adapter_gap_survives_lane_dispatch():
    c = context()
    missing = run_lanes(c, {}, None)["ANNOUNCEMENT"]
    assert missing["state"] == "INPUT_MISSING"
    assert "AUTHORITY_BATCH_ABSENT_OR_CHANGED" in missing["gaps"]
    from v4.manager_workbench.inputs import load_inputs
    bound = load_inputs(c, {})
    result = run_lanes(c, bound, None)["ANNOUNCEMENT"]
    assert "AUTHORITY_ADAPTER_NOT_BOUND" in result["gaps"]


def test_stage_cross_date_material_cannot_be_research_reference():
    c = context()
    raw = dict(market="HK_CONNECT", symbol="HK.00001", target_date="20261012",
        name="stage", owner="stage-owner", source_sha256="a" * 64,
        available_at="2026-10-13T09:00:00+08:00")
    b = dict(context=c, lane="STAGE_REFERENCE", records=[raw], universe_ref="stage:exact-owner",
        evidence_refs=[], input_sha256="a"*64, scope_description="stage",
        coverage=dict(scope_count=1, observed_count=1), gaps=[])
    r = run_lanes(c, {"STAGE_REFERENCE": b}, None)["STAGE_REFERENCE"]
    assert r["rows"][0]["decision"] == "UNASSESSED"
    assert r["rows"][0]["reason"] == "REFERENCE_OWNER_OR_DATE_NOT_VERIFIED"


def test_failed_lane_cannot_supply_formal_selected_rows():
    c = context()
    rows = [stock("00001", "SELECTED")]
    r = merge_decisions(c, [lane("ANNOUNCEMENT", rows, "FAILED")])
    assert r == []

