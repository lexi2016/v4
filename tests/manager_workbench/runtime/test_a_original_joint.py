"""Synthetic full chain using A's ORIGINAL modules, not a reimplemented engine.

Mac integration combines A@290592aa0c0934a69811eff9fb65284e39618a0e
with B; this fixture executes A.load_inputs/run_lanes/merge_decisions and
A's actual Reader/Reviewer validation. Skipped, not claimed PASS, when
standalone B handoff lacks A-owned sources. No real model is called here.
"""
from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

import pytest

from v4.manager_workbench.api import PREFIX, create_router
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import Lane,Phase,JobState,digest
from v4.manager_workbench.service import create_service
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_runtime import done


def _mounted_a():
    from importlib import import_module
    engine = pytest.importorskip("v4.manager_workbench.engines", reason="A original commit not mounted into B isolated tree")
    inputs = pytest.importorskip("v4.manager_workbench.inputs", reason="A original inputs not mounted")
    from v4.manager_workbench.engines import announcement
    assert announcement.PROMPT_VERSION == "MWB_ANNOUNCEMENT_READER_REVIEWER_V1_20261013"
    return engine, inputs, announcement


class AExecutionFixture:
    """Synthetic receipts. They NEVER prove a real CLI model/isolation."""
    def __init__(self, announcement, *, same_identity=False, bad_sha=False, fail_reviewer_once=False):
        self.announcement=announcement
        self.same_identity=same_identity
        self.bad_sha=bad_sha
        self.fail_reviewer_once=fail_reviewer_once
        self.calls={"READER":0,"REVIEWER":0}
        self.reader_sha=None

    def execute(self, task):
        role=task['role'];self.calls[role]+=1
        if role == 'REVIEWER' and self.fail_reviewer_once and self.calls[role]==1:
            from v4.manager_workbench.executors.codex import SemanticFailure
            raise SemanticFailure('CODEX_EXEC_FAILED')
        materials=task['materials']
        src=materials['source_sha256'];body=materials['body_sha256']
        quote='Verified completed capacity and customer orders.'
        item=[{'claim':'Synthetic evidence','quote':quote,'locator':'synthetic-p1'}]
        if role=='READER':
            output={'disposition':'SELECTED_EVENT','selection_basis':'OPERATING_EVENT',
                    'direction':'POSITIVE','evidence_sufficiency':'VERIFIED_EXISTING_FACTS',
                    'reason':'Synthetic valid fixture, not a real operating conclusion','risk_notes':[],
                    'facts':item,'changes':item,'impact':item,
                    'confirmation_conditions':item,'counter_evidence':item,
                    'source_sha256':src,'body_sha256':body}
            self.reader_sha=digest(output)
        else:
            output={'confirmed':True,'reason':'Synthetic only','source_sha256':src,
                    'body_sha256':body,'reader_output_sha256':materials['reader_output_sha256'],
                    'disposition':'SELECTED_EVENT','direction':'POSITIVE',
                    'evidence_sufficiency':'VERIFIED_EXISTING_FACTS'}
        if self.bad_sha and role=='REVIEWER':src='f'*64
        return {'status':'SUCCEEDED','success':True,'role':role,
                'execution_id':'synthetic-'+role,
                'execution_identity':'synthetic-reader' if role=='READER' or self.same_identity else 'synthetic-reviewer',
                'process_pid':101 if role=='READER' or self.same_identity else 202,
                'tool_isolation':'VERIFIED','simulated':True,'isolation_proof':'SIMULATED_TEST_ONLY',
                'input_sha256':task['input_sha256'],'source_sha256':src,'body_sha256':body,
                'material_sha256':digest({'refs':task['input_refs'],'data':task['materials']}),
                'event_sha256':'a'*64,'output_sha256':digest(output),'output':output,
                'model':task['model'],'prompt_version':task['prompt_version'],
                'started_at':'2026-10-13T09:20:00+08:00',
                'finished_at':'2026-10-13T09:21:00+08:00' if role=='READER' else '2026-10-13T09:23:00+08:00'}


def _case(tmp_path, *, same_identity=False,bad_sha=False,fail_reviewer_once=False):
    a,inputs,announcement=_mounted_a()
    body='Verified completed capacity and customer orders.'
    source='a'*64
    quote_sha=sha256(body.encode()).hexdigest()
    availability='2026-10-13T09:10:00+08:00'
    article={'market':'HK_CONNECT','symbol':'HK.00001','name':'Synthetic only',
             'target_date':'20261013','owner':'HKEX-ORIGINAL-TEST','source_sha256':source,
             'article_id':'HKEX:42','body':body,'body_sha256':quote_sha,'body_complete':True,
             'observed_at':availability,'available_at':availability,
             'evidence_ids':['article-1'],
             'membership':{'verification':'VERIFIED','eligible':True,'owner':'M02-FIXTURE',
                 'sha256':'b'*64,'effective_from':'20261001','effective_through':'20261031',
                 'available_at':availability}}
    def load_article(context):
        # A's original injected owner adapter signature: callable(context_dict)
        return {'context':context,'lane':'ANNOUNCEMENT','universe_ref':'HKEX:ONE_ARTICLE',
                'records':[article],'evidence_refs':[
                    {'evidence_id':'article-1','owner':'HKEX-ORIGINAL-TEST','role':'ARTICLE_BODY',
                     'sha256':source,'available_at':availability,'verification':'VERIFIED'}],
                'input_sha256':'d'*64,'scope_description':'Synthetic exact one-article verified catalog',
                'coverage':{'scope_count':1,'observed_count':1,'assessed_count':1,
                            'unassessed_count':0,'gaps':[]},'gaps':[]}
    facade=SimpleNamespace(load_inputs=inputs.load_inputs,run_lanes=a.run_lanes,
                           merge_decisions=a.merge_decisions,evaluate_review=a.evaluate_review)
    execution=AExecutionFixture(announcement,same_identity=same_identity,bad_sha=bad_sha,
                                fail_reviewer_once=fail_reviewer_once)
    cfg=WorkbenchConfig(state_root=tmp_path,rules_version='POSITIVE_OPERATING_RESEARCH_V1',
                        prompt_version=announcement.PROMPT_VERSION,model='Luna Max',
                        reasoning_effort='max',legacy_root=tmp_path/'old')
    svc=create_service(cfg,{'ANNOUNCEMENT':load_article},facade,execution)
    api=FastAPI();api.include_router(create_router(svc))
    scope={'ANNOUNCEMENT':{'scope_state':'VERIFIED','sha256':'c'*64,
                           'owner':'HKEX-ORIGINAL-TEST','universe_ref':'HKEX:ONE_ARTICLE',
                           'article_ids':['HKEX:42']}}
    return svc,execution,TestClient(api),scope


def test_actual_a_original_one_article_reader_reviewer_saved_api_readback(tmp_path):
    svc,executor,http,scope=_case(tmp_path)
    try:
        ctx_time=__import__('datetime').datetime.fromisoformat('2026-10-13T09:25:00+08:00')
        job=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT],
                                cutoff=ctx_time,scope_refs=scope))
        assert job.state==JobState.SUCCEEDED,job.model_dump(mode='json')
        assert executor.calls=={'READER':1,'REVIEWER':1}
        assert job.run_id==svc.store.read_plan(job.run_id).lanes[0].run_id
        snap=svc.store.read_plan(job.run_id)
        assert snap.counts.selected==1 and snap.stocks[0].decision.value=='SELECTED'
        assert isinstance(snap.stocks[0].lane_decisions['ANNOUNCEMENT'],list)
        assert snap.review_refs[0]['source_sha256']==snap.review_refs[1]['source_sha256']
        assert snap.review_refs[0]['body_sha256']==snap.review_refs[1]['body_sha256']
        assert snap.review_refs[0]['input_sha256']!=snap.review_refs[1]['input_sha256']
        assert snap.review_refs[0]['execution_identity']!=snap.review_refs[1]['execution_identity']
        page=http.get(PREFIX+'/days/20261013',params={'run_id':job.run_id})
        assert page.status_code==200
        assert page.json()['data']['snapshot']['product_sha256']==snap.product_sha256
        detail=http.get(PREFIX+'/stocks/HK.00001',params={'date':'20261013','run_id':job.run_id})
        assert len(detail.json()['data']['lane_details'][0]['evidence_refs'])==1
        assert all(x['simulated'] for x in snap.review_refs)  # NOT real canary
    finally:svc.jobs.stop()


def test_actual_a_original_reader_reviewer_identity_or_sha_conflict_not_selected(tmp_path):
    for which in ('same_identity','bad_sha'):
        case_dir=tmp_path/which
        svc,execution,http,scope=_case(case_dir,**{which:True})
        try:
            cutoff=__import__('datetime').datetime.fromisoformat('2026-10-13T09:25:00+08:00')
            job=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT],
                                    cutoff=cutoff,scope_refs=scope))
            assert job.state in (JobState.FAILED,JobState.PARTIAL,JobState.SUCCEEDED)
            if job.state != JobState.FAILED:
                snap=svc.store.read_plan(job.run_id)
                assert snap.counts.selected==0
        finally:svc.jobs.stop()


def test_actual_a_original_transient_reviewer_resume_reader_cache(tmp_path):
    svc,execution,http,scope=_case(tmp_path,fail_reviewer_once=True)
    try:
        cutoff=__import__('datetime').datetime.fromisoformat('2026-10-13T09:25:00+08:00')
        first=done(svc,svc.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT],
                                  cutoff=cutoff,scope_refs=scope))
        assert first.state==JobState.PARTIAL and first.retryable
        assert first.failed_steps==['LANE:ANNOUNCEMENT']
        old=svc.store.read_plan(first.run_id)
        assert old.counts.selected==0
        final=done(svc,svc.retry(first.job_id))
        assert final.state==JobState.SUCCEEDED
        assert execution.calls=={'READER':1,'REVIEWER':2}
        assert svc.store.read_plan(first.run_id)==old
        assert svc.store.read_plan(final.run_id).counts.selected==1
    finally:svc.jobs.stop()
