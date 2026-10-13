"""Issue #40 regression: A boundaries against the B-owned public models/runner receipt.

The receipt fixtures use precisely the fields in B @5010f866:
success/process_pid/isolation_proof/source_sha256/material_sha256/output_sha256.
No synthetic status/execution_identity/tool_isolation fields are accepted.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
import hashlib
import json
import pytest
from v4.manager_workbench.contracts import InputBatch, LaneResult, RunContext
from v4.manager_workbench.engines import run_lanes, merge_decisions
from v4.manager_workbench.engines.announcement import (
    _task, READER_SCHEMA, REVIEWER_SCHEMA, PROMPT_VERSION, run_announcements,
)
from v4.manager_workbench.engines.common import RULE, digest, plain
from v4.manager_workbench.inputs import load_inputs
from test_announcement import article, batch as announcement_batch, FakeExecutor
from test_merge_review import context as merge_context

def context(phase="MANUAL", cutoff="2026-10-13T09:00:00+08:00"):
    return RunContext.model_validate({
        "market":"HK_CONNECT","target_date":"20261013","phase":phase,"trigger":"MANUAL",
        "cutoff":cutoff,"source_sessions":{},"rules_version":RULE,
        "scope_refs":{"mwb_run_id":"b-real-job-1"}
    })

def test_b_list_input_and_list_output_with_real_contract_types():
    c=context()
    batches = load_inputs(c,{})
    values= [InputBatch.model_validate(batch) for batch in batches.values()]
    response=run_lanes(c,values,None)
    assert isinstance(response,list)  # B service.py:130 consumes an iterable of LaneResult
    assert len(response)==len(values)==5
    assert {x.lane.value for x in response}=={p.lane.value for p in values}
    for item in response:
        parsed = LaneResult.model_validate(item)
        assert parsed.run_id=="b-real-job-1"
    assert merge_decisions(c,response)==[]

def test_a_core_keeps_keyed_lane_mapping_for_injected_direct_consumers():
    c=context()
    inputs=load_inputs(c,{})
    response=run_lanes(c,inputs,None)
    assert isinstance(response,dict)
    assert list(response)==["ANNOUNCEMENT","US_MAPPING","OVERSOLD","STAGE_REFERENCE","CLOSE_REFERENCE"]
    assert all(LaneResult.model_validate(x).run_id=="b-real-job-1" for x in response.values())

def test_conflicting_run_ids_fail_closed():
    c=context().model_dump(mode="json")
    c["scope_refs"]["run_id"]="different-run"
    with pytest.raises(ValueError,match="RUN_ID"):
        run_lanes(c,load_inputs(context(),{}),None)

def test_stage_verified_receipt_never_admits_strict_selected():
    c=context()
    c.scope_refs["mwb_run_id"]="ref-run"
    member=dict(verification="VERIFIED",sha256="c"*64, owner="HK-monthly",
         effective_from="20261001",effective_through="20261031",
         available_at="2026-10-12T17:00:00+08:00",eligible=True)
    record=dict(market="HK_CONNECT",symbol="HK.00001",target_date="20261013",
        owner="M08",source_sha256="b"*64,available_at="2026-10-13T08:55:00+08:00",
        membership=member,original_formal_admission=True,original_rule_verified=True,
        original_owner_receipt_sha256="a"*64,original_rule_version=None)
    inputs=load_inputs(c,{"STAGE_REFERENCE":lambda _: dict(
        context=c.model_dump(mode="json"),lane="STAGE_REFERENCE",records=[record],
        universe_ref="M08:exact",scope_description="stage observation",
        input_sha256="d"*64,evidence_refs=[],
        coverage=dict(scope_count=1,observed_count=1),gaps=[])})
    result=run_lanes(c,list(inputs.values()),None)
    stage=next(x for x in result if x.lane.value=="STAGE_REFERENCE")
    assert stage.rows[0]["decision"]=="OBSERVATION_ONLY"
    assert stage.rows[0]["original_stage"]["rule"] is None
    assert stage.rows[0]["original_stage"]["owner_receipt_sha256"]=="a"*64
    assert stage.rows[0]["original_stage"]["original_formal_admission"] is True
    stocks=merge_decisions(c,result)
    assert stocks[0].decision.value=="OBSERVATION_ONLY"

def test_announcement_json_schema_arrays_are_executable_and_typed():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(READER_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(REVIEWER_SCHEMA)
    for name in ("risk_notes","facts","changes","impact","confirmation_conditions","counter_evidence"):
        prop=READER_SCHEMA["properties"][name]
        assert prop["type"]=="array" and "items" in prop
    for name in ("facts","changes","impact","confirmation_conditions","counter_evidence"):
        p=READER_SCHEMA["properties"][name]["items"]
        assert p["type"]=="object" and set(p["required"])=={"claim","quote","locator"}

class RealBShapedExecutor:
    """Synthetic process receipts use B's *actual* AuditedExecutor fields.

    JSON bytes use B's SHA(raw) provenance; arbitrary whitespace is permitted,
    not silently confused with A's canonical semantic digest.
    """
    def __init__(self):
        self.delegate=SimpleNamespace(config=SimpleNamespace(
            model="model-from-b",prompt_version=PROMPT_VERSION))
        self.tasks=[]
        self.receipts=[]
    def execute(self, task):
        from test_announcement import FakeExecutor
        f=FakeExecutor()
        # Consume the business-output fixture only; the receipt is B-shaped.
        raw_output=f.execute({**task,"materials":task["materials"]})["output"]
        raw_bytes=json.dumps(raw_output,ensure_ascii=True,indent=2).encode("utf-8")
        pid=20001 if task["role"]=="READER" else 20002
        stamp=("2026-10-13T09:00:01+08:00" if pid==20001
               else "2026-10-13T09:00:02+08:00")
        receipt=dict(role=task["role"],success=True,execution_id=f"execution-{pid}",
            process_pid=pid,isolation_proof=f"host-proof-{pid}",
            model=task["model"],prompt_version=task["prompt_version"],
            input_sha256=task["input_sha256"],source_sha256=task["source_sha256"],
            material_sha256=digest(dict(refs=task["input_refs"],data=task["materials"])),event_sha256="f"*64,output_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            started_at=stamp,finished_at=stamp,output=raw_output)
        self.tasks.append(task);self.receipts.append(receipt)
        return receipt

def b_announcement(phase="MANUAL"):
    c=context(phase)
    a=article()
    c.scope_refs["ANNOUNCEMENT"]=dict(scope_state="VERIFIED",article_ids=[a["article_id"]],
        sha256="c"*64,owner="catalog",universe_ref="catalog:verified")
    b=announcement_batch([a])
    b["context"]=c.model_dump(mode="json")
    return c,b

def test_b_audited_style_receipts_share_source_input_and_preserve_independent_pids():
    c,b=b_announcement()
    e=RealBShapedExecutor()
    result=run_announcements(plain(c),b,e)
    assert result["rows"][0]["decision"]=="SELECTED"
    assert [t["role"] for t in e.tasks]==["READER","REVIEWER"]
    assert e.tasks[0]["input_sha256"]==e.tasks[1]["input_sha256"]
    assert e.tasks[0]["source_sha256"]==e.tasks[1]["source_sha256"]
    assert e.tasks[0]["task_id"]!=e.tasks[1]["task_id"]
    assert e.receipts[0]["process_pid"]!=e.receipts[1]["process_pid"]
    assert result["rows"][0]["semantic"]["analysis_available_at"]=="2026-10-13T09:00:02+08:00"

def test_preopen_rejects_late_analysis_but_manual_retrospective_accept():
    for phase in ("MANUAL","RETROSPECTIVE"):
        c,b=b_announcement(phase)
        assert run_announcements(plain(c),b,RealBShapedExecutor())["rows"][0]["decision"]=="SELECTED"
    c,b=b_announcement("PREOPEN")
    assert run_announcements(plain(c),b,RealBShapedExecutor())["rows"][0]["decision"]=="UNASSESSED"

def test_b_receipt_mismatched_source_sha_and_same_pid_fail_closed():
    c,b=b_announcement()
    class Corrupt(RealBShapedExecutor):
        def execute(self,task):
            r=super().execute(task)
            if task["role"]=="REVIEWER":
                r=dict(r,process_pid=20001)
            return r
    assert run_announcements(plain(c),b,Corrupt())["rows"][0]["decision"]=="UNASSESSED"
    class SourceMismatch(RealBShapedExecutor):
        def execute(self,task):
            r=super().execute(task)
            if task["role"]=="REVIEWER":
                r=dict(r,source_sha256="0"*64)
            return r
    assert run_announcements(plain(c),b,SourceMismatch())["rows"][0]["decision"]=="UNASSESSED"

def test_b_output_raw_sha_is_not_assumed_canonical_sha():
    c,b=b_announcement()
    e=RealBShapedExecutor()
    result=run_announcements(plain(c),b,e)
    assert result["rows"][0]["decision"]=="SELECTED"
    assert e.receipts[0]["output_sha256"]!=digest(e.receipts[0]["output"])
    assert result["rows"][0]["semantic"]["reader_output_raw_sha256"]==e.receipts[0]["output_sha256"]
    assert result["rows"][0]["semantic"]["reader_output_canonical_sha256"]==digest(e.receipts[0]["output"])


def test_b_material_sha_must_bind_exact_task_data_not_only_look_hex():
    c,b=b_announcement()
    class WrongMaterial(RealBShapedExecutor):
        def execute(self,task):
            return dict(super().execute(task),material_sha256='0'*64)
    assert run_announcements(plain(c),b,WrongMaterial())['rows'][0]['decision']=='UNASSESSED'


def test_reviewer_cannot_start_before_reader_finishes():
    c,b=b_announcement()
    class ReversedClock(RealBShapedExecutor):
        def execute(self,task):
            out=super().execute(task)
            if task['role']=='REVIEWER':
                out=dict(out,started_at='2026-10-13T09:00:00+08:00',
                         finished_at='2026-10-13T09:00:02+08:00')
            return out
    assert run_announcements(plain(c),b,ReversedClock())['rows'][0]['decision']=='UNASSESSED'


def test_unbound_production_executor_no_implicit_model_guess():
    c,b=b_announcement()
    class OldStyleFake:
        models={'READER':'arbitrary','REVIEWER':'arbitrary'}
        reasoning_effort={'READER':'high','REVIEWER':'high'}
        def execute(self,task):
            raise AssertionError('must refuse before execute')
    assert run_announcements(plain(c),b,OldStyleFake())['rows'][0]['decision']=='UNASSESSED'


def test_external_reference_selected_row_never_upgrades_merge():
    c=context()
    member=dict(verification='VERIFIED',sha256='b'*64,owner='HK',eligible=True,
        effective_from='20261001',effective_through='20261031',
        available_at='2026-10-12T17:00:00+08:00')
    row=dict(market='HK_CONNECT',symbol='HK.00001',name='stage-only',
        decision='SELECTED',reason='UNTRUSTED_OWNER_FLAG',membership=member,evidence_ids=[])
    results=[LaneResult.model_validate(dict(lane='STAGE_REFERENCE',state='READY',rows=[row],
        coverage=dict(scope_count=1,observed_count=1,assessed_count=1,unassessed_count=0,gaps=[]),
        input_sha256='a'*64,rules_version=RULE,run_id='b-real-job-1',evidence_refs=[],gaps=[]))]
    merged=merge_decisions(c,results)
    assert merged[0].decision.value=='OBSERVATION_ONLY'
    assert merged[0].lane_decisions['STAGE_REFERENCE'][0]['decision']=='OBSERVATION_ONLY'


def test_b_service_injected_engines_namespace_exposes_load_inputs():
    from v4.manager_workbench import engines
    c=context()
    batches=engines.load_inputs(c,{})
    assert len(batches)==5
    assert all(isinstance(b,InputBatch) for b in batches.values())


def test_b_original_service_lane_identity_requires_exact_input_sha_even_when_missing():
    from v4.manager_workbench import engines
    c=context()
    batches=engines.load_inputs(c,{})
    inputs=[InputBatch.model_validate(x) for x in batches.values()]
    outcomes=engines.run_lanes(c,inputs,None)
    by_input={p.lane.value:p.input_sha256 for p in inputs}
    assert all(o.input_sha256==by_input[o.lane.value] for o in outcomes)


def test_b_requested_lane_subset_is_not_expanded_to_all_lanes():
    from v4.manager_workbench import engines
    c=context()
    c.scope_refs['requested_lanes']=['OVERSOLD']
    inputs=engines.load_inputs(c,{})
    assert list(inputs)==['OVERSOLD']
    outputs=engines.run_lanes(c,list(inputs.values()),None)
    assert len(outputs)==1 and outputs[0].lane.value=='OVERSOLD'


def test_b_missing_authority_lane_preserves_bound_external_batch_sha():
    c=context()
    inputs=[InputBatch.model_validate(dict(context=c.model_dump(mode='json'),lane='OVERSOLD',
        universe_ref=None,records=[],evidence_refs=[],scope_description='SOURCE_UNKNOWN',
        input_sha256='9'*64,coverage=dict(scope_count=None,observed_count=None),gaps=['SOURCE_UNKNOWN']))]
    out=run_lanes(c,inputs,None)
    assert len(out)==1
    assert out[0].input_sha256=='9'*64
    assert out[0].state.value=='INPUT_MISSING'


def test_b_failed_lane_keeps_original_input_sha(monkeypatch):
    from v4.manager_workbench.engines import core
    c=context()
    record=dict(market='HK_CONNECT',symbol='HK.00001',target_date='20261013',
        owner='M02',source_sha256='a'*64,available_at='2026-10-13T08:00:00+08:00')
    inputs=[InputBatch.model_validate(dict(context=c.model_dump(mode='json'),lane='OVERSOLD',
        universe_ref='M02:exact',records=[record],evidence_refs=[],
        scope_description='M02 valid source',input_sha256='8'*64,
        coverage=dict(scope_count=1,observed_count=1),gaps=[]))]
    def crash(*args):
        raise RuntimeError('isolated failure')
    monkeypatch.setattr(core,'run_oversold',crash)
    lanes=run_lanes(c,inputs,None)
    assert lanes[0].state.value=='FAILED'
    assert lanes[0].input_sha256=='8'*64
