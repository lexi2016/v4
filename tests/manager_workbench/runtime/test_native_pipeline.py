import csv
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contracts.trading_calendar import load_market_calendar,previous_session
from v4.manager_workbench import engines
from v4.manager_workbench.contracts import RunContext,Lane,Phase,JobState,digest
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.inputs import NativeAdapters
from v4.manager_workbench.service import create_service
from v4.manager_workbench.api import create_router
from v4.manager_workbench.executors.schema_check import validate_output


def write(root,relative,value):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path,count=230):
    shared=tmp_path/'shared';manager=tmp_path/'manager';stage=tmp_path/'stage'
    shared.mkdir();manager.mkdir();stage.mkdir()
    symbols=[f'HK.{i:05d}' for i in range(1,count+1)]
    member=dict(market='HK_CONNECT',owner='monthly-fixture',version='M202610',effective_from='20261001',
        effective_to='20261031',codes=symbols,available_at='2026-10-12T17:00:00+08:00',source_url='https://www.hkex.com.hk/fixture')
    msha=write(shared,'membership.json',member)
    calendar=load_market_calendar();dates=['20261012'];cursor=dates[0]
    for _ in range(60):cursor=previous_session(calendar,cursor,market='hk_securities');dates.append(cursor)
    bars=[dict(code_norm=s,trade_date_compact=d,high=100.0,close=80.0,trade=150 if d=='20261012' else 100)
          for s in symbols for d in dates]
    panel=shared/'panel.parquet';pd.DataFrame(bars).to_parquet(panel,index=False)
    psha=hashlib.sha256(panel.read_bytes()).hexdigest()
    manifest=dict(panel_max_date='20261012',panel_sha256=psha,panel_relative='panel.parquet',research_only=True,production_allowed=False)
    pmsha=write(shared,'panel_manifest.json',manifest)
    master=shared/'master.csv'
    with master.open('w') as file:
        writer=csv.DictWriter(file,fieldnames=['code']);writer.writeheader();writer.writerows({'code':s} for s in symbols)
    master_sha=hashlib.sha256(master.read_bytes()).hexdigest()
    master_manifest=dict(trade_date='20261012',artifact_relative='master.csv',artifact_sha256=master_sha,
        row_count=count,captured_at='2026-10-12T17:00:00+08:00',production_allowed=False)
    mmsha=write(shared,'master_manifest.json',master_manifest)
    bindings=dict(membership={'20261013':dict(artifact_relative='membership.json',artifact_sha256=msha,owner='monthly-fixture')},
        hk_panel={'20261012':dict(manifest_relative='panel_manifest.json',manifest_sha256=pmsha,panel_relative='panel.parquet',
            available_at='2026-10-12T17:00:00+08:00',currency='HKD',price_basis='RAW',volume_unit='SHARES')},
        security_master={'20261012':dict(manifest_relative='master_manifest.json',manifest_sha256=mmsha,artifact_relative='master.csv')})
    return WorkbenchConfig(state_root=tmp_path/'derived',shared_root=shared,manager_root=manager,stage_root=stage,source_bindings=bindings)


def wait(service,job):
    for _ in range(200):
        value=service.jobs.get(job.job_id)
        if value.state not in {JobState.RUNNING,JobState.QUEUED}:return value
        time.sleep(.01)
    raise AssertionError('worker did not finish')


def test_native_parquet_master_to_real_engines_snapshot_api_complete_230(tmp_path):
    cfg=fixture(tmp_path);adapter=NativeAdapters(cfg)
    service=create_service(cfg,adapter,engines,object())
    try:
        job=wait(service,service.submit('20261013',Phase.MANUAL,lanes=[Lane.OVERSOLD],
            cutoff=datetime.fromisoformat('2026-10-13T09:00:00+08:00')))
        assert job.state==JobState.SUCCEEDED,job.model_dump()
        plan=service.store.read_plan(job.run_id)
        assert plan.counts.selected==230
        assert plan.context.scope_refs['source_cutoff']=='2026-10-13T09:00:00+08:00'
        assert plan.lanes[0].rows[0]['metrics']['volume_ratio']=='1.5'
        api=FastAPI();api.include_router(create_router(service));client=TestClient(api)
        before=sorted(str(p.relative_to(service.store.root)) for p in service.store.root.rglob('*'))
        response=client.get('/api/v4/manager-workbench/days/20261013',params={'offset':200,'limit':30})
        assert response.status_code==200
        assert len(response.json()['data']['stocks'])==30 and response.json()['data']['counts']['selected']==230
        client.get('/api/v4/manager-workbench/days/20261014')
        assert before==sorted(str(p.relative_to(service.store.root)) for p in service.store.root.rglob('*'))
        second=wait(service,service.submit('20261013',Phase.MANUAL,lanes=[Lane.OVERSOLD]))
        assert second.run_id==job.run_id
    finally:service.jobs.stop()


def test_native_unknown_units_do_not_become_selected(tmp_path):
    cfg=fixture(tmp_path,count=1);cfg.source_bindings['hk_panel']['20261012'].pop('volume_unit')
    a=NativeAdapters(cfg);context=a.prepare_context(RunContext(target_date='20261013',phase='MANUAL',
        trigger='MANUAL',cutoff='2026-10-13T10:00:00+08:00',rules_version=cfg.rules_version))
    value=a.load(Lane.OVERSOLD,context)
    result=engines.run_lanes(context,{Lane.OVERSOLD.value:value},None)
    assert result[Lane.OVERSOLD.value].rows[0]['decision']=='UNASSESSED'


def test_corrupt_pinned_source_does_not_silently_read_latest(tmp_path):
    cfg=fixture(tmp_path,1);cfg.source_bindings['hk_panel']['20261012']['manifest_sha256']='0'*64
    service=create_service(cfg,NativeAdapters(cfg),engines,object())
    try:
        job=wait(service,service.submit('20261013',Phase.MANUAL,lanes=[Lane.OVERSOLD]))
        plan=service.store.read_plan(job.run_id)
        assert job.state==JobState.PARTIAL and plan.counts.selected is None
        assert plan.lanes[0].state.value=='INPUT_MISSING'
        assert 'SOURCE_BYTES_SHA_MISMATCH' in plan.lanes[0].gaps
    finally:service.jobs.stop()


def test_schema_vocabulary_checks_nested_citations_and_no_extra_fields():
    from v4.manager_workbench.engines.announcement import READER_SCHEMA
    shape={'type':'object','required':['items'],'additionalProperties':False,
        'properties':{'items':{'type':'array','items':{'type':'string','enum':['PASS']}}}}
    validate_output({'items':['PASS']},shape)
    for value in ({'items':[True]},{'items':['NO']},{'items':['PASS'],'leak':'x'},{}):
        with pytest.raises(ValueError):validate_output(value,shape)
    with pytest.raises(ValueError):validate_output({}, {'type':'object','$ref':'unknown'})
    for prop in READER_SCHEMA['properties'].values():
        if prop['type']=='array':assert 'items' in prop


def corpus(cfg):
    text='Signed operating contract already completed; payment confirmed. Existing demand increased; cancellation risk remains.'
    bsha=hashlib.sha256(text.encode()).hexdigest();page=dict(page_index=1,page_total=1,text=text,text_sha256=bsha,
        retrieved_at='2026-10-12T18:00:00+08:00')
    body=dict(target_trade_date='20261013',input_identity_sha256='a'*64,article_count=1,source_variant_count=0,
        rows=[dict(art_code='AN1',body_text=text,body_text_sha256=bsha,body_status='COMPLETE_CONTENT_API_BODY',
            matched_connect_codes=['HK.00001'],pages=[page],listing_source_ref={'body_sha256':'b'*64})],source_variants=[])
    msha=write(cfg.manager_root,'manifest.json',dict(target_trade_date='20261013',input_identity_sha256='a'*64))
    body['source_manifest_sha256']=msha;csha=write(cfg.manager_root,'corpus.json',body)
    rsha=write(cfg.manager_root,'receipt.json',dict(target_trade_date='20261013',body_corpus_file_sha256=csha,
        body_corpus_manifest_file_sha256=msha,RESEARCH_ONLY=True,production_allowed=False,hkex_body_coverage_status='COMPLETE'))
    cfg.source_bindings['announcements']={'20261013':dict(corpus_relative='corpus.json',corpus_sha256=csha,
        manifest_relative='manifest.json',manifest_sha256=msha,receipt_relative='receipt.json',receipt_sha256=rsha)}


class Semantic:
    def __init__(self,cfg):
        self.models={r:cfg.model for r in ['READER','REVIEWER']};self.reasoning_effort={r:'max' for r in self.models}
        self.readers=0;self.reviewers=0;self.calls=0
    def execute(self,task):
        from v4.manager_workbench.contracts import HK
        self.calls+=1;now=datetime.now(HK).isoformat();data=task['materials']
        if task['role']=='READER':
            self.readers+=1;quote=dict(claim='Source-supported completed operating fact',quote=data['article_body'],locator='page 1')
            output=dict(disposition='SELECTED_EVENT',selection_basis='OPERATING_EVENT',direction='POSITIVE',
                evidence_sufficiency='VERIFIED_EXISTING_FACTS',reason='Source confirmed',risk_notes=['Cancellation risk'],
                facts=[quote],changes=[quote],impact=[quote],confirmation_conditions=[quote],counter_evidence=[quote],
                source_sha256=data['source_sha256'],body_sha256=data['body_sha256'])
        else:
            self.reviewers+=1
            if self.reviewers==1:raise RuntimeError('MODEL_TEMPORARILY_UNAVAILABLE')
            output=dict(confirmed=True,reason='Independently matched source',source_sha256=data['source_sha256'],
                body_sha256=data['body_sha256'],reader_output_sha256=data['reader_output_sha256'],disposition='SELECTED_EVENT',
                direction='POSITIVE',evidence_sufficiency='VERIFIED_EXISTING_FACTS')
        return dict(execution_id='synthetic-'+str(self.calls),execution_identity='synthetic-process-'+str(self.calls),
            status='SUCCEEDED',tool_isolation='VERIFIED',role=task['role'],success=True,simulated=True,
            process_pid=1000+self.calls,model=task['model'],prompt_version=task['prompt_version'],
            input_sha256=task['input_sha256'],source_sha256=task['source_sha256'],material_sha256=digest(data),
            output=output,output_sha256=digest(output),event_sha256='c'*64,started_at=now,finished_at=now,
            isolation_proof='SYNTHETIC_TEST_ONLY')


def test_partial_retry_only_failed_reviewer_and_preserves_original_plan(tmp_path):
    cfg=fixture(tmp_path,1);corpus(cfg);executor=Semantic(cfg)
    service=create_service(cfg,NativeAdapters(cfg),engines,executor)
    try:
        first=wait(service,service.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT,Lane.OVERSOLD]))
        assert first.state==JobState.PARTIAL and first.retryable,first.model_dump()
        assert first.failed_steps==['ANNOUNCEMENT']
        old=service.store.read_plan(first.run_id)
        second=wait(service,service.retry(first.job_id))
        assert second.state==JobState.SUCCEEDED,second.model_dump()
        assert second.run_id!=first.run_id and executor.readers==1 and executor.reviewers==2
        assert service.store.read_plan(first.run_id).product_sha256==old.product_sha256
        assert service.store.read_plan(second.run_id).counts.selected==1
    finally:service.jobs.stop()


def test_capture_owner_required_and_directory_never_cut_to_200(tmp_path):
    from v4.manager_workbench.inputs.capture import capture_announcements
    context=RunContext(target_date='20261013',phase='MANUAL',trigger='MANUAL',
        cutoff='2026-10-13T18:00:00+08:00',rules_version='POSITIVE_OPERATING_RESEARCH_V1')
    with pytest.raises(ValueError,match='EXCLUSIVE_OWNER'):capture_announcements(context,{},object())
    class Cache:
        def assert_exclusive_owner(self,owner):assert owner=='v4.manager_workbench.capture_announcements'
        def read_response(self,url):return None
        def save_response(self,url,raw,captured):pass
    class Response:
        status_code=200
        def __init__(self,start):
            self.content=json.dumps(dict(recordCount=230,result=[dict(NEWS_ID=str(i),STOCK_CODE=f'{i:05d}',
                FILE_LINK=f'/listedco/listconews/sehk/2026/1013/{i}.pdf') for i in range(start+1,min(start+101,231))])).encode()
    class Transport:
        def get(self,url,**kwargs):
            from urllib.parse import parse_qs,urlsplit
            return Response(int(parse_qs(urlsplit(url).query)['rowRange'][0]))
    result=capture_announcements(context,dict(from_date='20261013',to_date='20261013',max_bodies=0,
        transport=Transport()),Cache())
    assert result.coverage.scope_count==230 and result.coverage.observed_count==230 and len(result.records)==230
    assert all(r['body_complete'] is False for r in result.records)


def test_preopen_keeps_completed_rows_from_partial_lane_and_never_changes(tmp_path):
    from v4.manager_workbench.contracts import seal_snapshot,Counts
    cfg=fixture(tmp_path,1);adapter=NativeAdapters(cfg);service=create_service(cfg,adapter,engines,object())
    try:
        context=service.context('20261013',Phase.INTRADAY,trigger='SCHEDULED',
            cutoff=datetime.fromisoformat('2026-10-13T09:20:00+08:00'),lanes=[Lane.OVERSOLD])
        context.scope_refs['run_id']='prepared'
        batch=adapter.load(Lane.OVERSOLD,context)
        lane=engines.run_lanes(context,{'OVERSOLD':batch},None)['OVERSOLD']
        pending=dict(market='HK_CONNECT',symbol='HK.00002',decision='UNASSESSED',reason='MODEL_PENDING')
        from v4.manager_workbench.contracts import LaneState
        lane=lane.model_copy(update={'state':LaneState.PARTIAL,'rows':[*lane.rows,pending],'gaps':['PENDING_ROW']})
        # model_copy updates are normalized before seal_snapshot checks enums.
        stocks=engines.merge_decisions(context,[lane])
        plan=seal_snapshot(dict(context=context,run_id='prepared',input_sha256=batch.input_sha256,
            generated_at='2026-10-13T09:20:00+08:00',available_at='2026-10-13T09:20:00+08:00',
            lanes=[lane],stocks=stocks,counts=Counts(selected=1,unassessed=1,watch=0,observation_only=0,not_selected=0),gaps=['PENDING_ROW']))
        service.store.commit_plan(plan)
        cutoff=datetime.fromisoformat('2026-10-13T09:25:00+08:00')
        frozen=service.freeze_preopen('20261013',cutoff=cutoff)
        assert frozen.counts.selected==1 and frozen.context.cutoff==cutoff.isoformat()
        assert frozen.lanes[2].state.value=='PARTIAL' or next(l for l in frozen.lanes if l.lane==Lane.OVERSOLD).state.value=='PARTIAL'
        assert service.freeze_preopen('20261013',cutoff=datetime.fromisoformat('2026-10-13T13:00:00+08:00')).product_sha256==frozen.product_sha256
    finally:service.jobs.stop()


def test_failed_pointer_publication_keeps_prior_success(tmp_path,monkeypatch):
    from v4.manager_workbench.contracts import seal_snapshot
    cfg=fixture(tmp_path,1);service=create_service(cfg,NativeAdapters(cfg),engines,object())
    try:
        first=wait(service,service.submit('20261013',Phase.MANUAL,lanes=[Lane.OVERSOLD]))
        original=service.store.read_plan(first.run_id)
        data=original.model_dump(mode='json');data['run_id']='failedpublication'
        for lane in data['lanes']:lane['run_id']='failedpublication'
        data['generated_at']='2026-10-13T23:59:00+08:00';data['available_at']=data['generated_at']
        snap=seal_snapshot(data);write_original=service.store._write
        def failing(path,obj,**kwargs):
            if 'pointers' in path.parts:raise OSError('synthetic pointer failure')
            return write_original(path,obj,**kwargs)
        monkeypatch.setattr(service.store,'_write',failing)
        with pytest.raises(OSError):service.store.commit_plan(snap)
        assert service.store.get_plan('20261013').run_id==original.run_id
        assert [p.run_id for p in service.store.list_plans('20261013')]==[original.run_id]
    finally:service.jobs.stop()
