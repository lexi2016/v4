"""Injected capture -> persisted binding -> real native/engine/API integration."""
from datetime import datetime,timedelta
import hashlib
import json
import threading
import time
from types import SimpleNamespace
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_native_pipeline import fixture,Semantic,wait,corpus
from test_capture_takeover import Transport,listing,content_url
from v4.manager_workbench import engines
from v4.manager_workbench.contracts import HK,Lane,Phase,JobState
from v4.manager_workbench.inputs import NativeAdapters
from v4.manager_workbench.inputs.capture_store import CaptureStore
from v4.manager_workbench.inputs.capture_binding import resolve,read_binding
from v4.manager_workbench.service import create_service
from v4.manager_workbench.api import create_router
from v4.manager_workbench.scheduler import tick


class Clock:
    def __init__(self,value='2026-10-13T10:00:30+08:00'):self.value=datetime.fromisoformat(value)
    def __call__(self):return self.value
    def advance(self):self.value+=timedelta(minutes=1)


class Model(Semantic):
    def __init__(self,cfg):
        super().__init__(cfg);self.reviewers=1;self.roles=[];self.tasks=[]
    def execute(self,task):
        self.roles.append(task['role']);self.tasks.append(task)
        return super().execute(task)


def setup(tmp_path,rows=None,clock=None):
    cfg=fixture(tmp_path,4);clock=clock or Clock();t=Transport(rows)
    cache=CaptureStore(tmp_path/'capture',lease_root=tmp_path/'lease',clock=clock)
    token=cache.grant(expires_at=clock()+timedelta(hours=12))
    cfg=cfg.model_copy(update=dict(capture_enabled=True,capture_root=cache.io.root,
        capture_lease_root=cache.leases.root,capture_lease_token=token))
    model=Model(cfg);service=create_service(cfg,NativeAdapters(cfg),engines,model,capture_transport=t,capture_clock=clock)
    return service,t,model,cache,clock


def capture_job(service,clock,phase=Phase.INTRADAY,target='20261013'):
    ctx=service.context(target,phase,trigger='SCHEDULED',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
    job=service.request_capture(ctx);assert job is not None
    return wait(service,job)


def research_job(service,target='20261013'):
    pointer=service.store.cursor('capture_analysis_'+target);assert pointer is not None
    return wait(service,service.jobs.get(pointer['job_id']))


def test_complete_capture_native_save_and_real_http(tmp_path):
    s,t,m,cache,clock=setup(tmp_path)
    try:
        c=capture_job(s,clock);assert c.state==JobState.SUCCEEDED,c.model_dump()
        r=research_job(s);assert r.state==JobState.SUCCEEDED,r.model_dump()
        plan=s.store.read_plan(r.run_id)
        assert plan.counts.selected==1 and m.roles==['READER','REVIEWER']
        assert plan.context.scope_refs['source_cutoff']==clock().isoformat()
        assert plan.context.scope_refs['capture_original_window']['research_cutoff']=='2026-10-13T10:00:30+08:00'
        assert plan.context.phase==Phase.INTRADAY and plan.context.scope_refs['capture_incremental']
        assert m.tasks[0]['input_sha256']==m.tasks[1]['input_sha256']
        assert m.tasks[0]['input_refs'][0]['owner']=='EASTMONEY_MIRROR'
        api=FastAPI();api.include_router(create_router(s));client=TestClient(api)
        assert client.get('/api/v4/manager-workbench/runs/'+c.job_id).status_code==200
        response=client.get('/api/v4/manager-workbench/days/20261013').json()['data']
        assert response['counts']['selected']==1 and response['stocks'][0]['symbol']=='HK.00001'
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in s.store.root.rglob('*') if p.is_file()}
        client.get('/api/v4/manager-workbench/runs/'+c.job_id)
        assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in s.store.root.rglob('*') if p.is_file()}
    finally:s.stop()


def test_new_article_only_executes_new_exact_identity_and_old_plan_immutable(tmp_path):
    s,t,m,cache,clock=setup(tmp_path,[listing(1),listing(2,code='00002')])
    try:
        assert capture_job(s,clock).state==JobState.SUCCEEDED
        old=research_job(s);assert old.state==JobState.SUCCEEDED,old.model_dump()
        old_plan=s.store.read_plan(old.run_id);old_sha=old_plan.product_sha256
        old_ids=[task['task_id'] for task in m.tasks]
        ctx=s.context('20261013',Phase.INTRADAY,trigger='MANUAL',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        old_manifest,old_material=read_binding(s.config,resolve(s.config,ctx),ctx)
        old_raw=json.loads(cache.io.read_bytes(old_manifest['product_ref']['artifact_ref']))
        assert len(m.roles)==4
        clock.advance();t.rows.append(listing(3,code='00003'))
        assert capture_job(s,clock).state==JobState.SUCCEEDED
        new=research_job(s);assert new.state==JobState.SUCCEEDED,new.model_dump()
        assert m.roles==['READER','REVIEWER']*3
        assert not set(old_ids)&set(task['task_id'] for task in m.tasks[4:])
        assert s.store.read_plan(new.run_id).counts.selected==3
        ctx=s.context('20261013',Phase.INTRADAY,trigger='MANUAL',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        new_manifest,new_material=read_binding(s.config,resolve(s.config,ctx),ctx)
        new_raw=json.loads(cache.io.read_bytes(new_manifest['product_ref']['artifact_ref']))
        old_day=old_raw['catalogues'][-1]['page_receipts'][0]
        new_day=new_raw['catalogues'][-1]['page_receipts'][0]
        assert old_day['request_sha256']!=new_day['request_sha256']
        assert old_day['sha256']!=new_day['sha256'] and old_day['available_at']<new_day['available_at']
        assert old_raw['window']['research_cutoff']!=new_raw['window']['research_cutoff']
        assert new_raw['rows'][0]['source_sha256']!=old_raw['rows'][0]['source_sha256']
        assert new_material['rows'][:2]==old_material['rows']
        assert len(new_manifest['article_material_refs'])==2
        assert s.store.read_plan(old.run_id).product_sha256==old_sha
        # A new observation of identical material submits no extra model job.
        clock.advance();calls=len(m.roles);previous=new.job_id
        capture_job(s,clock);assert research_job(s).job_id==previous and len(m.roles)==calls
    finally:s.stop()


def test_api_and_scheduler_process_queues_deduplicate_same_capture(tmp_path):
    s,t,m,cache,clock=setup(tmp_path)
    other=create_service(s.config,NativeAdapters(s.config),engines,m,capture_transport=t,capture_clock=clock)
    try:
        ctx=s.context('20261013',Phase.INTRADAY,trigger='MANUAL',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        a=s.request_capture(ctx);b=other.request_capture(ctx)
        assert a.job_id==b.job_id
        assert wait(s,a).state==JobState.SUCCEEDED
        assert len([u for u in t.calls if 'art_code=' in u])==1
        assert research_job(s).state==JobState.SUCCEEDED
    finally:other.stop();s.stop()


def test_partial_retry_repairs_missing_page_persists_each_binding(tmp_path):
    s,t,m,cache,clock=setup(tmp_path);t.body_pages=2;missing=content_url(listing()['art_code'],2);t.fail.add(missing)
    try:
        first=capture_job(s,clock);assert first.state==JobState.PARTIAL and first.retryable,first.model_dump()
        assert research_job(s).state==JobState.PARTIAL and not m.roles
        old_bindings=list((s.store.root/'capture_bindings'/'20261013').glob('*.json'))
        before=len(t.calls);t.fail.clear();clock.advance()
        second=wait(s,s.retry(first.job_id));assert second.state==JobState.SUCCEEDED,second.model_dump()
        assert t.calls[before:]==[missing]
        assert research_job(s).state==JobState.SUCCEEDED and len(m.roles)==2
        assert all(p.exists() for p in old_bindings)
    finally:s.stop()


def test_revoke_zero_requests_and_no_legacy_fallback(tmp_path):
    s,t,m,cache,clock=setup(tmp_path);corpus(s.config);cache.revoke()
    before={str(p):p.read_bytes() for p in cache.io.root.rglob('*') if p.is_file()}
    try:
        job=wait(s,s.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT],cutoff=clock()))
        plan=s.store.read_plan(job.run_id)
        assert job.state==JobState.PARTIAL and not t.calls and not m.roles
        assert 'NEW_CAPTURE_OWNER_EXACT_DATE_BINDING_MISSING' in plan.lanes[0].gaps
        assert before=={str(p):p.read_bytes() for p in cache.io.root.rglob('*') if p.is_file()}
        assert s.capture_gap=='CAPTURE_OWNER_UNAVAILABLE'
    finally:s.stop()


def test_preopen_fixed_cutoff_does_not_wait_for_capture(tmp_path):
    clock=Clock('2026-10-13T09:25:01+08:00');s,t,m,cache,clock=setup(tmp_path,clock=clock)
    entered=threading.Event();release=threading.Event()
    def block(url):entered.set();assert release.wait(5)
    t.after=block
    try:
        ctx=s.context('20261013',Phase.INTRADAY,trigger='SCHEDULED',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        c=s.request_capture(ctx);assert entered.wait(1)
        cal=SimpleNamespace(is_hk_session=lambda d:True)
        start=time.monotonic();result=tick(s,calendar=cal,stage_feed=SimpleNamespace(completed_runs=lambda d:[]),at=clock())
        assert time.monotonic()-start<1
        plan=s.store.get_plan('20261013','PREOPEN');assert plan.context.cutoff=='2026-10-13T09:25:00+08:00'
        assert plan.counts.selected is None and not m.roles
        release.set();assert wait(s,c).state==JobState.SUCCEEDED
        assert research_job(s).state==JobState.SUCCEEDED
        assert s.store.get_plan('20261013','PREOPEN').product_sha256==plan.product_sha256
    finally:release.set();s.stop()


def test_nextday_target_and_publication_cutoff_are_separate(tmp_path,monkeypatch):
    clock=Clock('2026-10-13T16:30:30+08:00');s,t,m,cache,clock=setup(tmp_path,clock=clock)
    monkeypatch.setattr('v4.manager_workbench.service.now',lambda:clock().isoformat())
    # Monthly evidence applies to the next target in this synthetic fixture.
    s.config.source_bindings['membership']['20261014']=s.config.source_bindings['membership']['20261013']
    try:
        c=capture_job(s,clock,Phase.NEXT_DAY,'20261014');assert c.state==JobState.SUCCEEDED,c.model_dump()
        r=research_job(s,'20261014');assert r.state==JobState.SUCCEEDED,r.model_dump()
        plan=s.store.read_plan(r.run_id)
        assert plan.context.phase==Phase.NEXT_DAY and plan.context.target_date=='20261014'
        w=plan.context.scope_refs['capture_original_window'];assert w['publication_dates']==['2026-10-12','2026-10-13']
        assert w['research_cutoff']=='2026-10-13T16:30:30+08:00'
        assert all('2026-10-14' not in u for u in t.calls)
    finally:s.stop()


def test_restart_recovers_capture_operation_and_never_grants_lease(tmp_path):
    from v4.manager_workbench.contracts import JobRecord
    s,t,m,cache,clock=setup(tmp_path)
    ctx=s.context('20261013',Phase.INTRADAY,trigger='SCHEDULED',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
    ctx.cutoff=clock().replace(second=0,microsecond=0).isoformat()
    ctx.scope_refs={'requested_lanes':['ANNOUNCEMENT'],'capture_operation':'CAPTURE_MATERIAL'}
    orphan=JobRecord(job_id='deadcapture',run_id='deadcapture',context=ctx,state='RUNNING',step='CAPTURE_MATERIAL',
        execution_refs=[{'kind':'host','pid':99999999}])
    s.store.save_job(orphan);s.stop()
    lease_bytes=cache.leases.read_bytes(cache.lease_path)
    restarted=create_service(s.config,NativeAdapters(s.config),engines,m,capture_transport=t,capture_clock=clock)
    try:
        recovered=restarted.jobs.get(orphan.job_id)
        assert recovered.state==JobState.INTERRUPTED and recovered.retryable
        done=wait(restarted,restarted.retry(orphan.job_id));assert done.state==JobState.SUCCEEDED,done.model_dump()
        assert research_job(restarted).state==JobState.SUCCEEDED
        assert lease_bytes==cache.leases.read_bytes(cache.lease_path)
    finally:restarted.stop()


def test_binding_pin_raw_sha_cutoff_and_corrupt_candidate_are_checked(tmp_path):
    s,t,m,cache,clock=setup(tmp_path)
    try:
        assert capture_job(s,clock).state==JobState.SUCCEEDED
        assert research_job(s).state==JobState.SUCCEEDED
        ctx=s.context('20261013',Phase.INTRADAY,trigger='MANUAL',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        pin=resolve(s.config,ctx);manifest,product=read_binding(s.config,pin,ctx)
        with pytest.raises(ValueError,match='SHA_MISMATCH'):
            read_binding(s.config,{**pin,'capture_binding_sha256':'0'*64},ctx)
        early=ctx.model_copy(deep=True);early.cutoff='2026-10-13T10:00:00+08:00'
        with pytest.raises(ValueError,match='CUTOFF'):read_binding(s.config,pin,early)
        # One corrupt candidate is isolated rather than hiding the valid one.
        path=s.store.root/'capture_bindings'/'20261013'/('0'*64+'.json');path.write_text('{}')
        assert resolve(s.config,ctx)==pin
        original=cache.io.read_bytes(product['rows'][0]['pages'][0]['source_ref']['artifact_ref'])
        raw_path=cache.io.root/product['rows'][0]['pages'][0]['source_ref']['artifact_ref']
        raw_path.write_bytes(original+b' ')
        with pytest.raises(ValueError,match='RAW_SHA'):read_binding(s.config,pin,ctx)
    finally:s.stop()


def test_default_disabled_no_capture_queue_and_enabled_requires_explicit_token(tmp_path):
    from v4.manager_workbench.config import WorkbenchConfig
    cfg=fixture(tmp_path,1);service=create_service(cfg,NativeAdapters(cfg),engines,object())
    try:assert service.capture_jobs is None
    finally:service.stop()
    with pytest.raises(ValueError,match='EXPLICIT_ROOTS'):
        WorkbenchConfig.model_validate({**cfg.model_dump(),'capture_enabled':True})
    with pytest.raises(ValueError,match='OVERLAP'):
        WorkbenchConfig.model_validate({**cfg.model_dump(),'capture_enabled':True,'capture_root':cfg.manager_root,
            'capture_lease_root':tmp_path/'lease','capture_lease_token':'a'*32})


def test_http_submission_returns_before_capture_and_exposes_separate_progress(tmp_path):
    clock=Clock(datetime.now(HK).isoformat());s,t,m,cache,clock=setup(tmp_path,clock=clock)
    entered=threading.Event();release=threading.Event()
    t.after=lambda url:(entered.set(),release.wait(5))
    api=FastAPI();api.include_router(create_router(s));client=TestClient(api)
    try:
        start=time.monotonic();response=client.post('/api/v4/manager-workbench/runs',json={
            'target_date':'20261013','phase':'MANUAL','lanes':['ANNOUNCEMENT']})
        assert response.status_code==202 and time.monotonic()-start<1
        assert entered.wait(1)
        initial=wait(s,s.jobs.get(response.json()['data']['job_id']))
        assert initial.state==JobState.PARTIAL and not m.roles
        linked=next(r for r in initial.execution_refs if r.get('kind')=='capture_job')
        progress=client.get(linked['status_url'])
        assert progress.status_code==200 and progress.json()['data']['state']=='RUNNING'
        clock.value=datetime.now(HK)  # Completion clock must follow the actual HTTP submission.
        release.set();completed=wait(s,s.jobs.get(linked['job_id']))
        assert completed.state==JobState.SUCCEEDED,completed.model_dump()
        assert research_job(s).state==JobState.SUCCEEDED
        assert linked in s.jobs.get(initial.job_id).execution_refs
    finally:release.set();s.stop()


def test_membership_source_change_reassesses_unchanged_article(tmp_path):
    from test_native_pipeline import write
    s,t,m,cache,clock=setup(tmp_path)
    try:
        capture_job(s,clock);first=research_job(s);assert first.state==JobState.SUCCEEDED
        old_input=m.tasks[0]['input_sha256'];clock.advance()
        membership=json.loads((s.config.shared_root/'membership.json').read_text())
        membership['version']='M202610-REISSUED'
        s.config.source_bindings['membership']['20261013']['artifact_sha256']=write(s.config.shared_root,'membership.json',membership)
        capture_job(s,clock);second=research_job(s)
        assert second.state==JobState.SUCCEEDED and second.job_id!=first.job_id
        assert m.roles==['READER','REVIEWER']*2 and m.tasks[2]['input_sha256']!=old_input
        assert m.tasks[2]['source_sha256']==m.tasks[0]['source_sha256']
    finally:s.stop()


def test_failed_catalogue_never_becomes_verified_zero_selection(tmp_path):
    from test_capture_takeover import date_scoped_url
    s,t,m,cache,clock=setup(tmp_path);t.fail.add(date_scoped_url('20261013',1))
    try:
        job=capture_job(s,clock);assert job.state==JobState.PARTIAL,job.model_dump()
        research=research_job(s);plan=s.store.read_plan(research.run_id)
        assert research.state==JobState.PARTIAL and plan.counts.selected is None
        assert plan.gaps and not m.roles
    finally:s.stop()


def test_two_os_processes_share_one_capture_claim(tmp_path):
    import subprocess
    import sys
    s,t,m,cache,clock=setup(tmp_path);s.stop()
    config=tmp_path/'process-config.json';config.write_text(json.dumps(s.config.model_dump(mode='json')))
    worker='''
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests/manager_workbench/runtime'))
from test_capture_wiring import Model,Clock,capture_job,research_job
from test_capture_takeover import Transport
from v4.manager_workbench.config import load_config
from v4.manager_workbench.inputs import NativeAdapters
from v4.manager_workbench import engines
from v4.manager_workbench.service import create_service
cfg=load_config(sys.argv[1]);clock=Clock();t=Transport();t.after=lambda _:time.sleep(.03)
s=create_service(cfg,NativeAdapters(cfg),engines,Model(cfg),capture_transport=t,capture_clock=clock)
try:
 c=capture_job(s,clock);r=research_job(s)
 print(json.dumps(dict(capture_id=c.job_id,state=c.state.value,research_state=r.state.value,body_calls=sum('art_code=' in u for u in t.calls))))
finally:s.stop()
'''
    root=Path(__file__).resolve().parents[3]
    children=[subprocess.Popen([sys.executable,'-c',worker,str(config)],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[]
    for child in children:
        out,err=child.communicate(timeout=15)
        assert child.returncode==0,err
        results.append(json.loads(out))
    assert results[0]['capture_id']==results[1]['capture_id']
    assert sum(r['body_calls'] for r in results)==1
    assert all(r['state']=='SUCCEEDED' and r['research_state']=='SUCCEEDED' for r in results)


def test_claim_minute_keeps_first_actual_cutoff_and_includes_subminute_article(tmp_path):
    row=listing();row['display_time']='2026-10-13 10:00:15:001'
    s,t,m,cache,clock=setup(tmp_path,[row])
    try:
        first_ctx=s.context('20261013',Phase.INTRADAY,trigger='SCHEDULED',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
        first=s.request_capture(first_ctx)
        later_ctx=first_ctx.model_copy(deep=True);later_ctx.cutoff='2026-10-13T10:00:59+08:00'
        later=s.request_capture(later_ctx)
        assert later.job_id==first.job_id
        done=wait(s,first);assert done.state==JobState.SUCCEEDED,done.model_dump()
        assert done.context.cutoff=='2026-10-13T10:00:30+08:00'
        research=research_job(s);plan=s.store.read_plan(research.run_id)
        assert plan.context.scope_refs['capture_original_window']['research_cutoff']=='2026-10-13T10:00:30+08:00'
        assert research.state==JobState.SUCCEEDED and plan.counts.selected==1
        assert m.roles==['READER','REVIEWER']
        assert plan.lanes[0].rows[0]['symbol']=='HK.00001'
    finally:s.stop()
