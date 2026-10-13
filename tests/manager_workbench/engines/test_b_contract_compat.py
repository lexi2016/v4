"""Run against B's frozen 761df4b6 public models after combining A/B commits."""
import pytest
b = pytest.importorskip("v4.manager_workbench.contracts")
from v4.manager_workbench.engines.common import RULE,VERSION,digest
from v4.manager_workbench.engines import run_lanes,merge_decisions,evaluate_review
from v4.manager_workbench.inputs import load_inputs


def ctx():
    return dict(market="HK_CONNECT",target_date="20261013",phase="PREOPEN",trigger="SCHEDULED",
        cutoff="2026-10-13T09:25:00+08:00",source_sessions={"hk":"20261012"},
        rules_version=RULE,scope_refs={"run_id":"test-run","review_universe":"M02:FULL_CLOSE"})


def test_a_to_b_typed_input_lane_stock_review_and_snapshot():
    c=ctx()
    a=load_inputs(b.RunContext.model_validate(c),{})
    for ln,input_batch in a.items():
        assert b.InputBatch.model_validate(input_batch).lane.value==ln
    lanes=run_lanes(b.RunContext.model_validate(c),a,None)
    assert all(b.LaneResult.model_validate(value).run_id=="test-run" for value in lanes.values())
    assert merge_decisions(c,lanes)==[]
    plan=b.seal_snapshot(dict(context=c,run_id="test-run",input_sha256="a"*64,
        generated_at="2026-10-13T09:25:01+08:00",available_at="2026-10-13T09:25:02+08:00",
        lanes=[x.model_dump(mode="json") for x in lanes.values()],stocks=[],counts=dict(selected=0,watch=0,unassessed=0,observation_only=0,
            not_selected=0),changes={},review_refs=[],gaps=["NO_BOUND_LANES"]))
    assert plan.product_sha256
    out=evaluate_review(plan,None)
    assert b.ReviewSummary.model_validate(out).strict_coverage["ratio"] is None
    assert digest(dict(a=1))==b.digest(dict(a=1))


def test_b_stock_decision_shape_and_complete_close_inputbatch_review():
    c=ctx()
    member=dict(verification="VERIFIED",owner="M02",sha256="b"*64,eligible=True,
        effective_from="20261001",effective_through="20261031",available_at="2026-10-12T17:00:00+08:00")
    row=dict(market="HK_CONNECT",symbol="HK.00001",name="fixture",decision="SELECTED",
        evidence_ids=[],reason="VERIFIED",membership=member)
    source=dict(lane="OVERSOLD",state="READY",rows=[row],input_sha256="a"*64,rules_version=RULE,
        run_id="test-run",evidence_refs=[],gaps=[],coverage=dict(scope_count=1,observed_count=1,assessed_count=1,
            unassessed_count=0,gaps=[]))
    stocks=merge_decisions(c,[b.LaneResult.model_validate(source)])
    assert len(stocks)==1
    assert isinstance(stocks[0],b.StockDecision)
    assert stocks[0].decision.value=="SELECTED"
    close=b.InputBatch.model_validate(dict(context=c,lane="CLOSE_REFERENCE",universe_ref="M02:FULL_CLOSE",
        scope_description="complete authoritative close ranking",input_sha256="d"*64,
        coverage=dict(scope_count=20,observed_count=20,assessed_count=20,unassessed_count=0,gaps=[]),gaps=[],
        records=[dict(rank=i,symbol=f"HK.{i:05d}") for i in range(1,21)],
        evidence_refs=[dict(evidence_id="close-1",owner="HK-close",role="FULL_CLOSE_RANKING",
            sha256="c"*64,source_date="20261013",verification="VERIFIED",
            manifest_ref="fixed:manifest",receipt_ref="fixed:receipt")]))
    plan=b.seal_snapshot(dict(context=c,run_id="test-run",input_sha256="a"*64,
        generated_at="2026-10-13T09:25:01+08:00",available_at="2026-10-13T09:25:02+08:00",
        lanes=[source],stocks=[stocks[0].model_dump(mode="json")],counts=dict(selected=1,watch=0,
            unassessed=0,observation_only=0,not_selected=0),changes={},review_refs=[],gaps=[]))
    review=evaluate_review(plan,close)
    assert isinstance(review,b.ReviewSummary)
    assert review.strict_coverage["covered"]==1
    assert review.strict_coverage["denominator"]==20
    assert review.top20_rows[0]["strict_hit"] is True

