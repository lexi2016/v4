"""B regression on A's *actual* public keyed API shape (no business stub promotion)."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench.api import PREFIX,create_router
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import Coverage, InputBatch, JobState, Lane, LaneResult, Phase, StockDecision
from v4.manager_workbench.service import create_service
from v4.manager_workbench.store import WorkbenchStore, StorageUnavailable
from v4.manager_workbench.executors.codex import AuditedExecutor, verify_review_pair,SemanticFailure
from v4.manager_workbench.contracts import digest
from test_runtime import config, done


class KeyedNativeA:
    """Strict structural test double of A's fixed public signatures.

    Behavioral tests against the ACTUAL A modules are separately provided by
    test_a_original_joint.py and are NOT included in this double's assertions.
    """
    def __init__(self,transient=True):
        self.fail=True
        self.transient=transient
        self.calls=[]
        self.inputs=0
        self.sha='a'*64

    def load_inputs(self, context, adapters):
        self.inputs+=1
        return {ln:InputBatch(context=context,lane=Lane(ln),universe_ref="owner:fixed",
                              records=[],evidence_refs=[],input_sha256=self.sha,
                              scope_description="SYNTHETIC",coverage=Coverage(scope_count=0,observed_count=0))
                for ln in (x.value for x in Lane)}

    def run_lanes(self, context, inputs, semantic_executor):
        assert isinstance(inputs,dict) and all(isinstance(x,InputBatch) for x in inputs.values())
        assert context.scope_refs['run_id']==context.scope_refs['mwb_run_id']
        self.calls += [tuple(sorted(inputs))]
        ret={}
        for name,batch in inputs.items():
            fail = self.fail and name==Lane.OVERSOLD.value
            ret[name]=LaneResult(lane=Lane(name),state="FAILED" if fail else "READY_EMPTY",
                                 rows=[],input_sha256=batch.input_sha256,rules_version=context.rules_version,
                                 run_id=context.scope_refs['run_id'],evidence_refs=[],
                                 coverage=Coverage(scope_count=0,observed_count=0),
                                 gaps=["TRANSIENT_PROVIDER_FAILURE" if self.transient else "PERMANENT_SCHEMA_ERROR"] if fail else [])
        return ret

    def merge_decisions(self,context,lanes):
        assert isinstance(lanes,dict)
        assert all(isinstance(x,LaneResult) for x in lanes.values())
        return []

    def evaluate_review(self,plan,close_inputs):
        raise RuntimeError('No close data is installed')


def keyed(tmp_path,*,transient=True):
    engine=KeyedNativeA(transient)
    svc=create_service(config(tmp_path),{},engine,object())
    app=FastAPI();app.include_router(create_router(svc))
    return svc,engine,TestClient(app)


def test_native_keyed_a_partial_retry_only_failed_lane_no_second_snapshot_overwrite(tmp_path):
    svc,engine,api=keyed(tmp_path)
    try:
        job=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT,Lane.OVERSOLD]))
        assert job.state==JobState.PARTIAL
        assert job.failed_steps==['LANE:OVERSOLD'] and job.retryable and job.failure_code=='RECOVERABLE_LANE_FAILURE'
        first=svc.store.read_plan(job.run_id)
        assert first.context.scope_refs['run_id']==first.run_id
        assert engine.calls==[('ANNOUNCEMENT','OVERSOLD')]
        engine.fail=False
        retried=done(svc,svc.retry(job.job_id))
        assert retried.state==JobState.SUCCEEDED and retried.run_id!=first.run_id
        assert engine.calls==[('ANNOUNCEMENT','OVERSOLD'),('OVERSOLD',)]
        assert svc.store.read_plan(first.run_id)==first  # prior PARTIAL version immutable
        assert len(svc.store.list_plans('20261013'))==2
        assert retried.failed_steps==[] and not retried.retryable
        assert api.get(PREFIX+'/days/20261013',params={'run_id':retried.run_id}).json()['data']['snapshot']['run_id']==retried.run_id
        assert api.post(PREFIX+'/runs/'+job.job_id+'/retry').status_code==409
    finally:svc.jobs.stop()


def test_permanent_lane_failure_rejected_as_retry(tmp_path):
    svc,engine,api=keyed(tmp_path,transient=False)
    try:
        record=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT,Lane.OVERSOLD]))
        assert record.state==JobState.PARTIAL and record.failed_steps==['LANE:OVERSOLD']
        assert record.retryable is False and record.failure_code=='LANE_FAILURE_NOT_RETRYABLE'
        assert api.post(PREFIX+'/runs/'+record.job_id+'/retry').status_code==409
        assert engine.calls==[('ANNOUNCEMENT','OVERSOLD')]
    finally:svc.jobs.stop()


def test_retry_rejects_changed_authority_identity_without_reusing_completed_lane(tmp_path):
    svc,engine,_=keyed(tmp_path)
    try:
        job=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT,Lane.OVERSOLD]))
        original=svc.store.read_plan(job.run_id)
        engine.sha='b'*64
        job=done(svc,svc.retry(job.job_id))
        assert job.state==JobState.FAILED and job.failure_code=='RETRY_COMPLETED_LANE_IDENTITY_CHANGED'
        assert svc.store.read_plan(original.run_id)==original
        assert engine.calls==[('ANNOUNCEMENT','OVERSOLD')]
    finally:svc.jobs.stop()


def test_unknown_gets_zero_filesystem_side_effects_and_symlinks_denied(tmp_path):
    # Service constructor, unknown reads and no-data reviews must not create root.
    state_root=tmp_path/'never'
    svc,engine,client=keyed(state_root)
    try:
        before={p.relative_to(tmp_path).as_posix():p.read_bytes() if p.is_file() else None
                for p in tmp_path.rglob('*')}
        assert client.get(PREFIX+'/runs/missing').status_code==404
        assert client.get(PREFIX+'/days/20261013').json()['state']=='NOT_RUN'
        assert client.get(PREFIX+'/history?date=20261013').json()['state']=='NOT_RUN'
        assert client.get(PREFIX+'/reviews/20261013?plan_run_id=missing').status_code==404
        assert client.get(PREFIX+'/stocks/HK.00001?date=20261013&run_id=missing').status_code==404
        after={p.relative_to(tmp_path).as_posix():p.read_bytes() if p.is_file() else None
               for p in tmp_path.rglob('*')}
        assert before==after and not (state_root/'manager_workbench').exists()
    finally:svc.jobs.stop()
    unsafe=tmp_path/'link';unsafe.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(StorageUnavailable,match='UNSAFE_STATE_ROOT'):
        WorkbenchStore(unsafe)


def test_reference_selected_is_never_promoted(tmp_path):
    class Promoter(KeyedNativeA):
        def run_lanes(self,context,inputs,semantic_executor):
            out=super().run_lanes(context,inputs,semantic_executor)
            name='STAGE_REFERENCE';item=out[name]
            item.state='READY'
            item.rows=[{'market':'HK_CONNECT','symbol':'HK.00001','decision':'SELECTED'}]
            return out
    engine=Promoter()
    svc=create_service(config(tmp_path),{},engine,object())
    try:
        job=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.STAGE_REFERENCE]))
        assert job.state==JobState.FAILED and job.failure_code=='REFERENCE_LANE_PROMOTED_TO_RESEARCH'
    finally:svc.jobs.stop()


def test_a_executor_reader_and_reviewer_same_source_but_different_task_sha(tmp_path):
    class Fake:
        def execute(self,task):
            return self._result(task)
        def _result(self,task):
            role=task['role'];source=task['materials']['source_sha256'];body=task['materials']['body_sha256']
            out={'synthetic':'NO_REAL_LUNA_MAX'}
            return {'role':role,'status':'SUCCEEDED','success':True,'tool_isolation':'VERIFIED',
                    'execution_identity':'sim-'+role,'execution_id':'sim-id-'+role,
                    'process_pid':301 if role=='READER' else 302,'input_sha256':task['input_sha256'],
                    'source_sha256':source,'body_sha256':body,'model':task['model'],
                    'prompt_version':task['prompt_version'],'material_sha256':'a'*64,
                    'event_sha256':'b'*64,'output_sha256':digest(out),'output':out,
                    'started_at':'2026-10-13T08:50:00+08:00','finished_at':'2026-10-13T08:51:00+08:00',
                    'isolation_proof':'SIMULATED_TEST_ONLY','simulated':True}
    store=WorkbenchStore(tmp_path)
    audited=AuditedExecutor(Fake(),config=config(tmp_path),store=store,job_id='test_job_1')
    tasks=[]
    for role,sha in [('READER','a'*64),('REVIEWER','b'*64)]:
        t={'role':role,'task_id':'mwb-'+sha,'model':'test-luna','reasoning_effort':'max',
           'prompt_version':'P1','input_sha256':sha,
           'materials':{'source_sha256':'c'*64,'body_sha256':'d'*64}}
        tasks.append(t)
        audited.execute(t)
    assert audited.refs[0]['input_sha256']!=audited.refs[1]['input_sha256']
    audited.assert_independent_review(True)
    assert audited.read_cached(tasks[0]['task_id'])['execution_id']=='sim-id-READER'
    assert len(audited.refs)==2
    assert all(r['simulated'] for r in audited.refs)
    with pytest.raises(SemanticFailure,match='REVIEWER_SOURCE_SHA_MISMATCH'):
        verify_review_pair(audited.refs[0],{**audited.refs[1],'body_sha256':'e'*64})
