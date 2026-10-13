"""Exact semantic identity claims across independent capture research jobs."""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import time
import pytest
from test_native_pipeline import fixture,Semantic
from v4.manager_workbench.engines import announcement
from v4.manager_workbench.executors.codex import AuditedExecutor,SemanticFailure
from v4.manager_workbench.store import WorkbenchStore
from v4.manager_workbench.contracts import digest


def article():
    return dict(article_id='article-1',source_sha256='a'*64,body_sha256='b'*64,symbol='HK.00001',
        observed_at='2026-10-13T09:00:00+08:00',available_at='2026-10-13T09:00:00+08:00',
        owner='EASTMONEY_MIRROR',evidence_ids=['original-ref'])


class Delegate(Semantic):
    def __init__(self,cfg):super().__init__(cfg);self.entered=threading.Event();self.release=threading.Event();self.block=False;self.fail=False
    def execute(self,task):
        if self.block:self.entered.set();assert self.release.wait(5)
        if self.fail:raise RuntimeError('synthetic bounded model failure')
        return super().execute(task)


def test_concurrent_exact_task_one_execution_and_shared_original_identity(tmp_path):
    cfg=fixture(tmp_path,1);store=WorkbenchStore(cfg.state_root);delegate=Delegate(cfg);delegate.block=True
    a=AuditedExecutor(delegate,store=store,job_id='first');b=AuditedExecutor(delegate,store=store,job_id='second')
    task=announcement._task(a,'READER',article=article(),body='Raw source substring')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(a.execute,task);assert delegate.entered.wait(1)
        second=pool.submit(b.execute,task);delegate.release.set()
        one,two=first.result(),second.result()
    assert delegate.readers==1 and one==two
    assert a.refs[0]['execution_id']==b.refs[0]['execution_id']
    checkpoint='semantic_'+digest(task['task_id'])
    assert store.load_checkpoint('second',checkpoint)==one
    with pytest.raises(SemanticFailure,match='CACHED_TASK_IDENTITY_INVALID'):
        a.execute({**task,'materials':{'different':'input'}})


@pytest.mark.parametrize('change',['owner','refs','prompt'])
def test_owner_ref_prompt_change_invalidates_cache_and_failure_keeps_success(tmp_path,monkeypatch,change):
    cfg=fixture(tmp_path,1);store=WorkbenchStore(cfg.state_root);delegate=Delegate(cfg)
    a=AuditedExecutor(delegate,store=store,job_id='first')
    first=announcement._task(a,'READER',article=article(),body='Raw source substring');one=a.execute(first)
    revised=article()
    if change=='owner':revised['owner']='HKEX_OFFICIAL'
    elif change=='refs':revised['evidence_ids']=['new-source-ref']
    else:monkeypatch.setattr(announcement,'PROMPT_VERSION',announcement.PROMPT_VERSION+'-TEST-NEW')
    b=AuditedExecutor(delegate,store=store,job_id='second')
    second=announcement._task(b,'READER',article=revised,body='Raw source substring')
    assert first['task_id']!=second['task_id'] and b.read_cached(second['task_id']) is None
    delegate.fail=True
    with pytest.raises(RuntimeError):b.execute(second)
    assert b.read_cached(first['task_id'])==one
    delegate.fail=False;two=b.execute(second)
    assert delegate.readers==2 and two['execution_id']!=one['execution_id']
    assert store.load_checkpoint('semantic_cache','semantic_'+digest(first['task_id']))['result']==one


def test_changed_eligibility_claim_not_swallowed_by_active_material_scope():
    from v4.manager_workbench.jobs import JobCoordinator
    from v4.manager_workbench.contracts import RunContext
    a=RunContext(target_date='20261013',phase='INTRADAY',trigger='SCHEDULED',cutoff='2026-10-13T10:00:00+08:00',
        rules_version='POSITIVE_OPERATING_RESEARCH_V1',scope_refs={'requested_lanes':['ANNOUNCEMENT'],
            'capture_input_sha256':'a'*64,'capture_analysis_identity':'b'*64})
    b=a.model_copy(deep=True);b.scope_refs['capture_analysis_identity']='c'*64
    assert JobCoordinator._scope(a)!=JobCoordinator._scope(b)
