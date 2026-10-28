from __future__ import annotations
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from test_manager_announcement_flash_runner import _bridge_module, _classification_capture
from test_manager_announcement_classification import article, address_article
from v4.manager_workbench import announcement_membership as membership
from v4.manager_workbench.announcement_classification import policy
from v4.manager_workbench.announcement_delivery import read as read_delivery


def _fixture(tmp_path, monkeypatch, *, include_long=False):
    bridge=_bridge_module();helper=bridge._load_helper()
    monkeypatch.setattr(bridge,'_load_helper',lambda:helper)
    import batch_runner as runner
    import announcement_queue
    import automatic_canary_server
    from v4.manager_workbench import announcement_chunks as chunks
    header='Company name: Synthetic Issuer Limited\nStock code: 00001\n\nOpening balance 100\nIncrease / decrease 0\n\n'
    a=article(header+'公司新增重大收購事項，已完成一項經營項目。','经营事项 A');a['article_id']='EASTMONEY:NEW_A'
    b=article(header+'公司新增重大收購事項，已完成另一項經營項目。','经营事项 B');b['article_id']='EASTMONEY:NEW_B'
    sources=[address_article(),a,b]
    if include_long:
        long=article(header+('\n\n'.join('公司新增重大收購事項，完整附帶條件與經營詳情。'+str(i)+'文'*13000 for i in range(12))), '经营长文')
        long['article_id']='EASTMONEY:LONG';sources.append(long)
    for source in sources:source['article_metadata']['symbol']='HK.00001'
    product,ref=_classification_capture(tmp_path/'capture',sources)
    gate={'status':'VERIFIED','codes':['HK.00001'],'authority_sha256':'a'*64,'target_date':'20261016',
        'market':'HK_CONNECT','cutoff':'2026-10-16T13:00:00+08:00'}
    value={'schema':'v4.manager_workbench.announcement_flash_input.v1','job_id':'a'*32,'target_date':'20261016',
        'cutoff':gate['cutoff'],'capture_product':ref,'membership_gate':gate,'classification_policy':policy(),
        'daily_workflow':'P23'}
    state=tmp_path/'owner'/'manager_workbench';state.mkdir(parents=True)
    monkeypatch.setattr(membership,'revalidate_membership_gate',lambda *_a:deepcopy(gate))
    monkeypatch.setattr(bridge,'_pinned_candidate_history',lambda:[])
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *_a,**_kw:SimpleNamespace(encode=lambda text,**_k:[0]*max(1,len(text)//2)))))
    monkeypatch.setattr(helper,'_token_count',lambda _t,messages:len(json.dumps(messages,ensure_ascii=False))//2)
    monkeypatch.setattr(runner,'load_local_api_key',lambda:'synthetic-no-secret')
    monkeypatch.setattr(automatic_canary_server,'GatedStreamingTransport',lambda *_a,**_kw:SimpleNamespace(close=lambda:None))
    calls=[];observations=[]
    def execute(job):
        payload=job.payload;aid=payload['article_id'];kind=payload.get('queue_task_kind','ordinary')
        calls.append((aid,kind))
        old,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
        observations.append((aid,kind,deepcopy(old)))
        unit_map=runner.build_source_unit_map(payload['article_body'],payload['body_sha256'])
        units=unit_map['units']
        if kind=='announcement_reader_part':
            start=payload['part_descriptor']['start_source_unit_id'];end=payload['part_descriptor']['end_source_unit_id']
        elif kind=='announcement_reader_synthesis':
            cite=payload['synthesis_input']['part_reports'][0]['citation_ranges'][0]
            start,end=cite['start_source_unit_id'].split('::')[-1],cite['end_source_unit_id'].split('::')[-1]
        else:
            event=next((u for u in units if '公司新增' in u['text']),units[0]);start=end=event['source_unit_id']
        cite={'claim':'原文披露经营事项及条件。','start_source_unit_id':aid+'::'+start,'end_source_unit_id':aid+'::'+end}
        selected=aid=='EASTMONEY:NEW_B' and kind=='ordinary'
        output={'disposition':'SELECTED_EVENT' if selected else 'NOT_SELECTED',
            'selection_basis':'OPERATING_EVENT' if selected else 'NOT_SELECTED','direction':'POSITIVE' if selected else 'NEUTRAL',
            'evidence_sufficiency':'VERIFIED_EXISTING_FACTS','reason':'已按完整来源核对的离线合成响应。',
            'risk_notes':[],'facts':[],'changes':[cite] if selected else [],'impact':[cite],
            'confirmation_conditions':[],'counter_evidence':[],'source_sha256':'','body_sha256':''}
        return json.dumps({'action':'complete','lookup_request':None,'reader_output':output},ensure_ascii=False)
    monkeypatch.setattr(bridge,'_transport_executor',lambda *_a,**_kw:execute)
    return bridge,value,state,tmp_path/'capture',calls,observations


def test_preprocess_then_first_then_continue_same_job_delivers_before_batch_end(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,observations=_fixture(tmp_path,monkeypatch)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _value:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    assert pre['state']=='PREPROCESSING_COMPLETE' and calls==[]
    assert pre['report']['counts']['model_required_articles']==2
    assert pre['report']['counts']['raw_rows']==3
    assert not (state/'announcement_flash/queue/queue-state.json').exists()
    report_sha=pre['preprocessing']['sha256']
    first=bridge._run(value,**kwargs,execute_report_sha256=report_sha,execution_phase='FIRST')
    assert calls==[('EASTMONEY:NEW_A','ordinary')]
    delivered,binding=read_delivery(bridge.SafeRoot(state),value['job_id'])
    assert next(e for e in delivered['articles'] if e['article_id']=='EASTMONEY:NEW_A')['state']=='SUCCEEDED'
    old_ref=state/binding['artifact_ref'];old_bytes=old_ref.read_bytes()
    continued=bridge._run(value,**kwargs,execute_report_sha256=report_sha,execution_phase='CONTINUE')
    assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_B','ordinary')]
    assert old_ref.read_bytes()==old_bytes
    assert observations[1][2] and next(e for e in observations[1][2]['articles'] if e['article_id']=='EASTMONEY:NEW_A')['state']=='SUCCEEDED'
    current,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    assert current['stocks'][0]['articles'][0]['article_id']=='EASTMONEY:NEW_B'
    assert not (state/'announcement_flash/jobs'/value['job_id']/'result.json').exists()
    assert continued['execution_phase']=='CONTINUE'


def test_continue_requires_first_success_and_report_tamper_blocks_before_any_request(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _value:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    with pytest.raises(bridge.FlashRunError,match='FIRST_ARTICLE_NOT_COMPLETE'):
        bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    with pytest.raises(bridge.FlashRunError,match='REPORT_SHA_CHANGED'):
        bridge._run(value,**kwargs,execute_report_sha256='0'*64,execution_phase='FIRST')
    assert calls==[]


def test_long_synthesis_runs_as_soon_as_its_parts_are_ready_and_never_publishes_part_as_candidate(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,observations=_fixture(tmp_path,monkeypatch,include_long=True)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _value:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    counts=pre['report']['counts'];assert counts['model_long_articles']==1 and counts['reader_parts']<=6
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    synth=[i for i,c in enumerate(calls) if c==('EASTMONEY:LONG','announcement_reader_synthesis')]
    assert len(synth)==1
    part_indices=[i for i,c in enumerate(calls) if c==('EASTMONEY:LONG','announcement_reader_part')]
    assert synth[0]==max(part_indices)+1
    for aid,kind,snapshot in observations:
        if kind=='announcement_reader_part' and snapshot:
            assert not any(a.get('article_id')=='EASTMONEY:LONG' for stock in snapshot['stocks'] for a in stock['articles'])
    final,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    long=next(e for e in final['articles'] if e['article_id']=='EASTMONEY:LONG')
    assert long['state']=='SUCCEEDED' and long['source_coverage']=='COMPLETE_SYNTHESIS'


def test_api_reports_preprocessing_and_incremental_delivery_while_preserving_prior_candidates(tmp_path,monkeypatch):
    from datetime import datetime
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from v4.manager_workbench import announcement_update as update_module
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    from v4.manager_workbench.api import create_router
    from v4.manager_workbench.contracts import JobRecord,JobState,RunContext,Phase,HK
    from v4.manager_workbench.jobs import JobCoordinator
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,observations=_fixture(tmp_path,monkeypatch)
    store=WorkbenchStore(tmp_path/'owner');jobs=JobCoordinator(store,workers=1)
    config=SimpleNamespace(capture_root=capture,shared_root=tmp_path/'shared',source_bindings={})
    service=SimpleNamespace(store=store,jobs=jobs,config=config)
    update=AnnouncementUpdate(service)
    context=RunContext(target_date=value['target_date'],cutoff=value['cutoff'],phase=Phase.MANUAL,
        trigger='MANUAL',rules_version='V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1',scope_refs={'capture_operation':'ANNOUNCEMENT_FLASH_INCREMENTAL'})
    job=JobRecord(job_id=value['job_id'],run_id=value['job_id'],context=context,state=JobState.PARTIAL,step='DONE',retryable=True)
    store.save_job(job);store.set_cursor('announcement_flash_latest',{'job_id':job.job_id,'target_date':context.target_date})
    store.io.write_bytes(update._job_ref(job.job_id,'input.json'),bridge.canonical(value))
    gate=value['membership_gate']
    monkeypatch.setattr(membership,'resolve_membership_gate',lambda *_a:deepcopy(gate))
    old={'symbol':'HK.00001','name':'Historical Issuer','reasons':['historical result preserved'],
        'articles':[{'article_id':'HISTORY:OLD','title':'历史成功公告','body_sha256':'f'*64,'source_origins':[]}],
        'review_status':'PRIOR_INDEPENDENT_REVIEW_PASS_WITH_LIMITATION'}
    monkeypatch.setattr(update_module,'read_pinned_candidates',lambda:{'state':'PARTIAL','source_date':'2026-10-15',
        'target_trade_date':context.target_date,'stocks':[deepcopy(old)],'failures':[],'pending':[],'gaps':[],
        'counts':{'displayed_stocks':1,'failed':0,'pending':0,'model_succeeded':1,'body_gaps':0}})
    monkeypatch.setattr(AnnouncementUpdate,'resume_snapshot',lambda *_a:{'eligible':False})
    progress=lambda value:store.io.write_bytes(update._job_ref(job.job_id,'progress.json'),bridge.canonical(value)+b'\n')
    app=FastAPI();app.include_router(create_router(service))
    kwargs=dict(state_root=state,capture_root=capture,job_id=job.job_id,progress=progress,shared_root=config.shared_root)
    try:
        pre=bridge._run(value,**kwargs,preprocess_only=True)
        with TestClient(app) as client:
            pre_api=client.get('/api/v4/manager-workbench/announcement-flash?target_date='+context.target_date).json()
            assert pre_api['data']['preprocessing']['counts']['model_required_articles']==2
            assert pre_api['data']['preprocessing']['counts']['raw_rows']==3
            assert calls==[]
            bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
            first_api=client.get('/api/v4/manager-workbench/announcement-flash?target_date='+context.target_date).json()
            assert first_api['data']['daily_delivery']['counts']['SUCCEEDED']==1
            saved_delivery,saved_binding=read_delivery(store.io,job.job_id)
            assert first_api['data']['daily_delivery']==saved_delivery
            analysis=first_api['data']['daily_analysis']
            assert analysis['delivery_sha256']==saved_binding['sha256']
            assert analysis['articles'][0]['analysis_state']=='AVAILABLE'
            assert 'facts' in analysis['articles'][0]['reader_output']
            assert any(e['article_id']=='HISTORY:OLD' for stock in first_api['data']['stocks'] for e in stock['articles'])
            bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
            final_api=client.get('/api/v4/manager-workbench/announcement-flash?target_date='+context.target_date).json()
            assert final_api['data']['daily_delivery']['counts']['SUCCEEDED']==2
            assert {e['article_id'] for stock in final_api['data']['stocks'] for e in stock['articles']}=={'HISTORY:OLD','EASTMONEY:NEW_B'}
            import os
            evidence=os.environ.get('ANNOUNCEMENT_WORKFLOW_EVIDENCE_ROOT')
            if evidence:
                for name,data in [('preprocessing-api.json',pre_api),('first-api.json',first_api),('final-api.json',final_api)]:
                    (Path(evidence)/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    finally:jobs.stop()


def test_api_execution_keeps_job_id_and_committed_first_result_and_finishes_only_unattempted(tmp_path,monkeypatch):
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from v4.manager_workbench import api as api_module
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    from v4.manager_workbench.contracts import JobRecord,JobState,RunContext,Phase
    from v4.manager_workbench.jobs import JobCoordinator
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    store=WorkbenchStore(tmp_path/'owner');jobs=JobCoordinator(store,workers=1)
    service=SimpleNamespace(store=store,jobs=jobs,config=SimpleNamespace(capture_root=capture,shared_root=tmp_path/'shared'))
    def popen(command,**_kwargs):
        code=bridge._main(command[3:],signalled=[])
        return SimpleNamespace(returncode=code,poll=lambda:code)
    update=AnnouncementUpdate(service,popen=popen)
    context=RunContext(target_date=value['target_date'],cutoff=value['cutoff'],phase=Phase.MANUAL,
        trigger='MANUAL',rules_version='V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1',scope_refs={'capture_operation':'ANNOUNCEMENT_FLASH_INCREMENTAL'})
    job=JobRecord(job_id=value['job_id'],run_id=value['job_id'],context=context,state=JobState.PARTIAL,step='PREPROCESSING_COMPLETE',retryable=True)
    store.save_job(job)
    store.io.write_bytes(update._job_ref(job.job_id,'input.json'),bridge.canonical(value))
    progress=lambda data:store.io.write_bytes(update._job_ref(job.job_id,'progress.json'),bridge.canonical(data)+b'\n')
    pre=bridge._run(value,state_root=state,capture_root=capture,job_id=job.job_id,progress=progress,
        shared_root=service.config.shared_root,preprocess_only=True)
    # A prior job's saved delivery remains historical even for the same target day.
    from v4.manager_workbench.announcement_delivery import publish,SCHEMA
    old_job_id='b'*32
    old_snapshot={'schema':SCHEMA,'job_id':old_job_id,'target_trade_date':context.target_date,
        'preprocessing_report_sha256':'2'*64,'state':'PARTIAL','counts':{'SUCCEEDED':1},
        'articles':[{'article_id':pre['report']['first_article_id'],
            'body_sha256':pre['report']['execution_manifest'][0]['body_sha256'],'state':'SUCCEEDED'}]}
    old_binding=publish(store.io,old_job_id,old_snapshot)
    old_bytes=store.io.read_bytes(old_binding['artifact_ref'])
    old_pointer=store.io.read_bytes(f'announcement_flash/jobs/{old_job_id}/deliveries/latest.json')
    store.set_cursor('announcement_flash_delivery_index',{'items':[{'job_id':old_job_id,'target_date':context.target_date}]})
    monkeypatch.setattr(api_module,'AnnouncementUpdate',lambda _service:update)
    app=FastAPI();app.include_router(api_module.create_router(service))
    def settled():
        for _ in range(200):
            saved=jobs.get(job.job_id)
            if saved.state not in {JobState.QUEUED,JobState.RUNNING}:return saved
            time.sleep(0.01)
        pytest.fail('offline worker did not terminalize')
    try:
        with TestClient(app) as client:
            url=f'/api/v4/manager-workbench/announcement-flash/{job.job_id}/execute-preprocessed'
            assert client.post(url,json={'phase':'FIRST','report_sha256':'0'*64}).status_code==409
            assert client.post(url,json={'phase':'CONTINUE','report_sha256':pre['preprocessing']['sha256'],
                'first_delivery_sha256':old_binding['sha256']}).status_code==409
            assert calls==[]
            response=client.post(url,json={'phase':'FIRST','report_sha256':pre['preprocessing']['sha256']})
            assert response.status_code==202 and response.json()['data']['job_id']==job.job_id
            first=settled();assert first.state==JobState.PARTIAL and first.completed_count==1
            first_delivery,first_binding=read_delivery(store.io,job.job_id)
            first_bytes=store.io.read_bytes(first_binding['artifact_ref'])
            assert first_delivery['job_id']==job.job_id
            assert first_delivery['preprocessing_report_sha256']==pre['preprocessing']['sha256']
            assert client.post(url,json={'phase':'FIRST','report_sha256':pre['preprocessing']['sha256']}).status_code==409
            assert client.post(url,json={'phase':'CONTINUE','report_sha256':pre['preprocessing']['sha256'],
                'first_delivery_sha256':old_binding['sha256']}).status_code==409
            assert calls==[('EASTMONEY:NEW_A','ordinary')]
            response=client.post(url,json={'phase':'CONTINUE','report_sha256':pre['preprocessing']['sha256'],
                'first_delivery_sha256':first_binding['sha256']})
            assert response.status_code==202
            final=settled();assert final.state==JobState.SUCCEEDED and final.completed_count==2
            assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_B','ordinary')]
            assert store.io.read_bytes(first_binding['artifact_ref'])==first_bytes
            assert read_delivery(store.io,old_job_id)==(old_snapshot,old_binding)
            assert store.io.read_bytes(old_binding['artifact_ref'])==old_bytes
            assert store.io.read_bytes(f'announcement_flash/jobs/{old_job_id}/deliveries/latest.json')==old_pointer
            assert not (state/update._job_ref(job.job_id,'result.json')).exists()
    finally:jobs.stop()


def test_historical_running_same_model_is_not_recovered_or_dispatched_in_new_only_path(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    import announcement_queue
    import batch_runner as runner
    root=state/'announcement_flash/queue'
    old_queue=announcement_queue.SerialAnnouncementQueue(root,bridge.QUEUE_ID,runner.MODEL_ID,max_attempts=1)
    body='user-stopped historical body'
    old_payload={'date':'2026-10-19','market':'HK','article_id':'EASTMONEY:AN202610191830690060',
        'source_sha256':'8'*64,'body_sha256':bridge.sha(body.encode()),'article_body':body,
        'prompt_sha256':'9'*64,'model_id':runner.MODEL_ID,'configuration_sha256':'7'*64,
        'rules':'historical-frozen','role':'announcement_reader_part','stage':'historical-frozen'}
    old=old_queue.enqueue(old_payload);old_key=old['idempotency_key']
    saved=old_queue._load_state();claimed=old_queue._claim_next_locked(saved,{old_key})
    assert claimed['status']=='RUNNING' and claimed['attempt_count']==1
    old_record=old_queue._load_state()['jobs'][old_key]
    frozen=bridge.canonical(old_record)
    payload_bytes=(root/old_record['input_path']).read_bytes()
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _value:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    after=old_queue._load_state()['jobs'][old_key]
    assert bridge.canonical(after)==frozen and (root/old_record['input_path']).read_bytes()==payload_bytes
    assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_B','ordinary')]
    assert after['attempt_count']==1 and after['status']=='RUNNING'


def test_first_phase_binds_exact_version_when_same_article_id_has_revised_body(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    raw_path=capture/value['capture_product']['artifact_ref'];product=json.loads(raw_path.read_text())
    product['rows'][2]['art_code']=product['rows'][1]['art_code']
    raw=bridge.canonical(product);digest=bridge.sha(raw)
    value['capture_product']={'artifact_ref':f'products/{digest}.json','sha256':digest}
    (capture/value['capture_product']['artifact_ref']).write_bytes(raw)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _v:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    assert pre['report']['counts']['model_required_articles']==2
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
    assert len(calls)==1
    first,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    assert sum(e['state']=='SUCCEEDED' for e in first['articles'])==1
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    assert len(calls)==2
    final,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    success=[e for e in final['articles'] if e['state']=='SUCCEEDED']
    assert len({e['body_sha256'] for e in success})==2


def test_new_foreign_history_after_frozen_report_stops_without_claim_or_model(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    import announcement_queue,batch_runner as runner
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _v:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    queue=announcement_queue.SerialAnnouncementQueue(state/'announcement_flash/queue',bridge.QUEUE_ID,runner.MODEL_ID,max_attempts=1)
    entry=pre['report']['execution_manifest'][0]
    payload={'date':entry['source_date'],'market':'HK','article_id':entry['article_id'],
        'source_sha256':entry['source_sha256'],'body_sha256':entry['body_sha256'],'article_body':'existing foreign history',
        'prompt_sha256':'8'*64,'model_id':runner.MODEL_ID,'configuration_sha256':'9'*64,
        'rules':'other-processed-context','role':'announcement_reader','stage':'history'}
    queue.enqueue(payload);before=queue.state_path.read_bytes()
    with pytest.raises(bridge.FlashRunError,match='NEW_ONLY_HISTORY_APPEARED'):
        bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
    assert calls==[] and queue.state_path.read_bytes()==before


def test_cooperative_stop_keeps_current_article_success_and_other_article_deferred(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _v:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    original=bridge._transport_executor
    stopping=[]
    def factory(*args,**kw):
        execute=original(*args,**kw)
        def run(job):
            raw=execute(job);stopping.append(True);return raw
        return run
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    result=bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST',
        stop_requested=lambda:bool(stopping))
    assert result['state']=='USER_STOPPED' and calls==[('EASTMONEY:NEW_A','ordinary')]
    snapshot,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    assert snapshot['state']=='USER_STOPPED'
    assert next(e for e in snapshot['articles'] if e['article_id']=='EASTMONEY:NEW_A')['state']=='SUCCEEDED'
    assert next(e for e in snapshot['articles'] if e['article_id']=='EASTMONEY:NEW_B')['state']=='DEFERRED'


def test_single_article_failure_is_visible_and_never_retried_by_continuation(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,_=_fixture(tmp_path,monkeypatch)
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=lambda _v:None,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True)
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='FIRST')
    original=bridge._transport_executor
    def factory(*args,**kw):
        execute=original(*args,**kw)
        def run(job):
            raw=execute(job)
            return '{invalid-json' if job.payload['article_id']=='EASTMONEY:NEW_B' else raw
        return run
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    snapshot,_=read_delivery(bridge.SafeRoot(state),value['job_id'])
    failed=next(e for e in snapshot['articles'] if e['article_id']=='EASTMONEY:NEW_B')
    assert failed['state']=='FAILED' and len(snapshot['failures'])==1
    state_file=state/'announcement_flash/queue/queue-state.json'
    jobs=json.loads(state_file.read_text())['jobs'];old=deepcopy(jobs[failed['queue_key']])
    bridge._run(value,**kwargs,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE')
    assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_B','ordinary')]
    assert json.loads(state_file.read_text())['jobs'][failed['queue_key']]==old


def _saved_analysis_fixture(tmp_path, coverage='COMPLETE_ARTICLE'):
    """Only persisted, isolated artifacts: no runner or model invocation."""
    import hashlib
    from infrastructure.owned_io import SafeRoot
    from v4.manager_workbench.announcement_delivery import publish
    from v4.manager_workbench.announcement_preprocessing import encoded
    io=SafeRoot(tmp_path);key='1'*64;aid='EASTMONEY:SAVED_ANALYSIS'
    reader={'disposition':'NOT_SELECTED','direction':'NEUTRAL','selection_basis':'NOT_SELECTED',
        'evidence_sufficiency':'VERIFIED_EXISTING_FACTS','reason':'完整已保存理由。',
        'facts':[{'claim':f'事实{i}','quote':f' 原文事实{i}。\n','locator':f'article_body[codepoint:{i}:{i+1}]',
                  'start_source_unit_id':f'{aid}::U{i}'} for i in range(4)],
        'changes':[],'impact':[],'confirmation_conditions':[],'counter_evidence':[],
        'risk_notes':['已披露风险一。','已披露风险二。','输入元数据：pit_status=CANNOT_CONFIRM；OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND'],
        'source_sha256':'2'*64,'body_sha256':'3'*64}
    result={'results':[{'article_id':aid,'reader_output':reader}]}
    ref=f'jobs/{key}/attempt-0001.validated.json';raw=encoded(result)+b'\n'
    io.write_bytes('announcement_flash/queue/'+ref,raw)
    entry={k:reader[k] for k in ('source_sha256','body_sha256','disposition','direction','selection_basis','reason')}
    entry.update(article_id=aid,title='已保存完整公告',state='SUCCEEDED',source_coverage=coverage,
                 queue_key=key,result_ref=ref,result_sha256=hashlib.sha256(raw).hexdigest())
    delivery={'schema':'v4.manager_workbench.announcement_delivery.v1','job_id':'a'*32,
              'articles':[entry],'stocks':[],'counts':{'SUCCEEDED':1}}
    binding=publish(io,delivery['job_id'],delivery)
    return io,delivery,binding,reader,result


@pytest.mark.parametrize('coverage',['COMPLETE_ARTICLE','COMPLETE_SYNTHESIS'])
def test_saved_full_analysis_is_readonly_and_preserves_all_evidence_and_empty_sections(tmp_path,coverage):
    from v4.manager_workbench.announcement_delivery import read_analysis
    io,delivery,binding,reader,_=_saved_analysis_fixture(tmp_path,coverage)
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    original=deepcopy(delivery)
    projection=read_analysis(io,delivery,binding)
    assert projection['delivery_sha256']==binding['sha256']
    article=projection['articles'][0]
    assert article['analysis_state']=='AVAILABLE' and article['reader_output']==reader
    assert len(article['reader_output']['facts'])==4 and len(article['reader_output']['risk_notes'])==3
    assert article['reader_output']['confirmation_conditions']==[]
    assert delivery==original
    assert before=={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    # The returned business objects do not alias the stored delivery/result.
    article['reader_output']['facts'][0]['claim']='mutated client copy'
    assert read_analysis(io,delivery,binding)['articles'][0]['reader_output']==reader


@pytest.mark.parametrize('case',[
    'sha','missing','symlink','traversal','wrong_queue_key','wrong_article','wrong_source','wrong_body',
    'summary_decision','invalid_evidence','part_coverage','delivery_binding',
])
def test_saved_analysis_bad_reference_or_identity_is_unavailable_without_replacing_success(tmp_path,case):
    import hashlib
    from v4.manager_workbench.announcement_delivery import read_analysis,publish
    from v4.manager_workbench.announcement_preprocessing import encoded
    io,delivery,binding,reader,result=_saved_analysis_fixture(tmp_path)
    entry=delivery['articles'][0];ref='announcement_flash/queue/'+entry['result_ref'];path=tmp_path/ref
    if case=='sha':path.write_bytes(path.read_bytes()+b' ')
    elif case=='missing':path.unlink()
    elif case=='symlink':
        target=tmp_path/'elsewhere.json';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    elif case=='traversal':entry['result_ref']='../elsewhere.json'
    elif case=='wrong_queue_key':entry['queue_key']='f'*64
    elif case=='summary_decision':entry['direction']='POSITIVE'
    elif case=='part_coverage':entry['source_coverage']='INCOMPLETE_PARTS'
    elif case=='delivery_binding':binding['sha256']='f'*64
    else:
        if case=='wrong_article':result['results'][0]['article_id']='OTHER'
        elif case=='wrong_source':reader['source_sha256']='4'*64
        elif case=='wrong_body':reader['body_sha256']='4'*64
        elif case=='invalid_evidence':reader['facts'][0]['quote']=None
        raw=encoded(result)+b'\n';path.write_bytes(raw);entry['result_sha256']=hashlib.sha256(raw).hexdigest()
    if case!='delivery_binding':binding=publish(io,delivery['job_id'],delivery)
    before=deepcopy(delivery)
    projection=read_analysis(io,delivery,binding)
    assert projection['articles'][0]['analysis_state']=='UNAVAILABLE'
    assert projection['articles'][0]['failure_code'].startswith('ANALYSIS_')
    assert 'reader_output' not in projection['articles'][0]
    assert delivery==before and delivery['counts']=={'SUCCEEDED':1} and delivery['articles'][0]['state']=='SUCCEEDED'


def test_saved_analysis_one_bad_entry_does_not_hide_other_results_and_parts_are_not_complete(tmp_path):
    from v4.manager_workbench.announcement_delivery import read_analysis,publish
    io,delivery,_,reader,_=_saved_analysis_fixture(tmp_path)
    bad=deepcopy(delivery['articles'][0]);bad['article_id']='UNBOUND'
    pending=deepcopy(bad);pending.update(article_id='PENDING_PART',state='PENDING',source_coverage='INCOMPLETE_PARTS')
    delivery['articles'] += [bad,pending]
    binding=publish(io,delivery['job_id'],delivery)
    rows=read_analysis(io,delivery,binding)['articles']
    assert [e['analysis_state'] for e in rows]==['AVAILABLE','UNAVAILABLE']
    assert rows[0]['reader_output']==reader


def _semantic_failure_fixture(tmp_path, monkeypatch, *, include_long=False):
    bridge,value,state,capture,calls,observations=_fixture(tmp_path,monkeypatch,include_long=include_long)
    normal=bridge._transport_executor
    first=[True]
    def factory(*args,**kwargs):
        execute=normal(*args,**kwargs)
        def wrapped(job):
            raw=execute(job)
            if first[0] and job.payload['article_id']=='EASTMONEY:NEW_A':
                first[0]=False;data=json.loads(raw);data['reader_output'].update(disposition='SELECTED_PERFORMANCE',selection_basis='PERFORMANCE_RESEARCH',direction='MIXED');raw=json.dumps(data,ensure_ascii=False)
            return raw
        return wrapped
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    io=bridge.SafeRoot(state);prefix=f'announcement_flash/jobs/{value["job_id"]}'
    io.write_bytes(prefix+'/input.json',bridge.canonical(value))
    progress=lambda data:io.write_bytes(prefix+'/progress.json',bridge.canonical(data)+b'\n')
    kwargs=dict(state_root=state,capture_root=capture,job_id=value['job_id'],progress=progress,shared_root=tmp_path/'shared')
    pre=bridge._run(value,**kwargs,preprocess_only=True);report_sha=pre['preprocessing']['sha256']
    io.write_bytes(prefix+'/execution-request.json',bridge.canonical({'report_sha256':report_sha,'phase':'FIRST','first_delivery_sha256':None}))
    bridge._run(value,**kwargs,execute_report_sha256=report_sha,execution_phase='FIRST')
    q=json.loads((state/'announcement_flash/queue/queue-state.json').read_bytes())['jobs'];key=next(k for k,j in q.items() if j['status']=='FAILED');old=q[key]
    payload=json.loads((state/'announcement_flash/queue'/old['input_path']).read_bytes())
    trace=f'announcement_flash/evidence/streams/{key}/attempt-0001/'
    io.write_bytes(trace+'round-01.request-input.json',bridge.canonical({'messages':payload['messages'],'structured_outputs':{'json':payload['structured_output_schema']}}))
    io.write_bytes(trace+'round-01.raw.sse',b'SYNTHETIC_OFFLINE_TRANSPORT_FIXTURE')
    io.write_bytes(trace+'stream-receipt.json',b'{"synthetic":true}')
    plan,sha=bridge._extension_plan(state,capture,value['job_id'],report_sha)
    io.write_bytes(prefix+'/execution-extensions/'+sha+'.json',bridge.canonical(plan)+b'\n')
    io.write_bytes(prefix+'/execution-extensions/latest.json',bridge.canonical({'sha256':sha})+b'\n')
    return bridge,value,state,capture,calls,kwargs,pre,plan,sha,key,old


def test_semantic_extension_recovers_once_then_all_remaining_and_preserves_original_failure(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch)
    root=state/'announcement_flash/queue';raw=(root/old['raw_path']).read_bytes();frozen=(state/pre['preprocessing']['artifact_ref']).read_bytes()
    # A full source-bound success produced under another prompt/config must be reused.
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_A','ordinary')]
    after=json.loads((root/'queue-state.json').read_bytes())['jobs'];assert after[key]==old and (root/old['raw_path']).read_bytes()==raw
    new=[j for k,j in after.items() if k!=key];assert len(new)==1
    recovered_payload=json.loads((root/new[0]['input_path']).read_bytes());assert recovered_payload['recovery_of']['logical_attempt']==2
    assert bridge._extension_checkpoint(state,plan,sha)[1]=='SUCCEEDED'
    # Repeating the recovery does not create another attempt or request.
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    assert len(calls)==2
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    assert calls[-1]==('EASTMONEY:NEW_B','ordinary') and len(calls)==3
    delivered,_=read_delivery(bridge.SafeRoot(state),value['job_id']);assert delivered['counts']['SUCCEEDED']==2
    assert delivered['model_progress']['total']==2 and (state/pre['preprocessing']['artifact_ref']).read_bytes()==frozen
    assert json.loads((root/'queue-state.json').read_bytes())['jobs'][key]==old
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    assert len(calls)==3


def test_semantic_extension_first_gate_drift_and_nonpositive_answers_stay_honest(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch)
    with pytest.raises(bridge.FlashRunError,match='CANARY_NOT_SUCCEEDED'):
        bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    assert len(calls)==1
    import batch_runner as runner
    import announcement_queue as qm
    import build_length_canary as lc
    helper=bridge._load_helper();contract=runner.load_active_contract(bridge.REPO_ROOT/'v4/manager_workbench/engines/announcement.py');material=bridge._owned_request_material(helper,runner,contract)
    from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT
    assert SEMANTIC_CONTRACT in material['prompt'] and '不得为获得入选而把方向改成 POSITIVE' in material['prompt']
    payload=json.loads((state/'announcement_flash/queue'/old['input_path']).read_bytes());raw=json.loads((state/'announcement_flash/queue'/old['raw_path']).read_bytes());validate=bridge._validator(qm,runner,contract,material,lc)
    with pytest.raises(qm.ValidationRejected,match='ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'):validate(SimpleNamespace(payload=payload),raw)
    for direction in ('MIXED','NEGATIVE'):
        honest=deepcopy(raw);honest['reader_output'].update(disposition='NOT_SELECTED',selection_basis='NOT_SELECTED',direction=direction)
        assert validate(SimpleNamespace(payload=payload),honest)['results'][0]['reader_output']['direction']==direction
    (state/'announcement_flash/queue'/old['raw_path']).write_bytes(b'changed')
    with pytest.raises(bridge.FlashRunError,match='SOURCE_ARTIFACT_CHANGED'):bridge._extension_plan(state,capture,value['job_id'],pre['preprocessing']['sha256'],sha)
    assert len(calls)==1


def test_semantic_extension_preserves_215_identity_and_all_seven_frozen_long_budgets():
    from v4.manager_workbench.announcement_preprocessing import build_extension,extension_entries,SCHEMA
    entries=[]
    for i in range(208):entries.append({'article_id':f'NEWS:{i}','source_sha256':f'{i:064x}','body_sha256':f'{i+1000:064x}','symbol':'HK.00001','primary_disposition':'MODEL_ORDINARY','part_count':0,'expected_requests':1})
    for i,n in enumerate((5,3,2,2,4,9,13)):entries.append({'article_id':f'LONG:{i}','source_sha256':f'{i+500:064x}','body_sha256':f'{i+1500:064x}','symbol':'HK.00001','primary_disposition':'MODEL_LONG','part_count':n,'expected_requests':n+1})
    preserved=[{'article_id':f'HISTORY:{i}','primary_disposition':'OTHER_HISTORY_PRESERVED'} for i in range(247)]+[{'article_id':'STOPPED','primary_disposition':'USER_STOPPED_EXCLUDED'}]
    report={'schema':SCHEMA,'accounting_closed':True,'job_id':'a'*32,'target_date':'20261021','first_article_id':'NEWS:0','catalogue':entries+preserved,'counts':{'model_required_articles':215,'expected_model_requests':253},'history_context':preserved,'capture_product':{},'membership_gate_sha256':'a'*64,'policy':{},'limits':{'max_articles':8,'max_model_requests':16,'max_reader_parts_per_article':6},'safety':{}}
    old=deepcopy(report);failed={**entries[0],'failure_code':'ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'}
    result=build_extension(report,report_sha256='b'*64,source_artifacts=[],failed=failed,execution_contract={})
    assert result['workload']=={'articles':215,'expected_requests':253} and report==old
    assert [e['part_count'] for e in result['entries'] if e['primary_disposition']=='MODEL_LONG']==[5,3,2,2,4,9,13]
    assert len(result['entries'])==215 and not any(e['article_id'].startswith(('HISTORY:','STOPPED')) for e in result['entries'])


def test_semantic_extension_long_parts_and_synthesis_use_original_plan(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch,include_long=True)
    original={p.name:p.read_bytes() for p in (state/'announcement_flash/jobs'/value['job_id']/'long-body').iterdir()}
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    kinds=[kind for aid,kind in calls if aid=='EASTMONEY:LONG'];assert kinds[-1]=='announcement_reader_synthesis' and all(kind=='announcement_reader_part' for kind in kinds[:-1])
    assert {p.name:p.read_bytes() for p in (state/'announcement_flash/jobs'/value['job_id']/'long-body').iterdir()}==original
    delivered,_=read_delivery(bridge.SafeRoot(state),value['job_id']);assert next(e for e in delivered['articles'] if e['article_id']=='EASTMONEY:LONG')['source_coverage']=='COMPLETE_SYNTHESIS'


def test_semantic_extension_cross_prompt_success_reused_and_new_semantic_failures_continue(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    import announcement_queue as qm
    import batch_runner as runner
    import build_length_canary as lc
    helper=bridge._load_helper();contract=runner.load_active_contract(bridge.REPO_ROOT/'v4/manager_workbench/engines/announcement.py');material=bridge._owned_request_material(helper,runner,contract)
    queue=bridge._new_only_queue(qm,state/'announcement_flash/queue',runner.MODEL_ID)
    jobs=queue._load_state()['jobs'];recovered=next(j for k,j in jobs.items() if k!=key)
    payload=bridge._queue_payload(state/'announcement_flash/queue',recovered)
    old_success=deepcopy(payload);old_success['prompt_sha256']='f'*64;old_success['configuration_sha256']='e'*64
    old_success['rules']+=':old-version';old_success.pop('execution_extension_sha256');old_success.pop('recovery_of')
    from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
    old_success['rules']=old_success['rules'].replace(SEMANTIC_CONTRACT_VERSION,'historical_version')
    old_success['messages'][0]['content']=old_success['messages'][0]['content'].replace(SEMANTIC_CONTRACT,'历史版本仅按来源分析。')
    old_success.pop('semantic_contract_version',None)
    old_success['prompt_sha256']=bridge.sha(old_success['messages'][0]['content'].encode())
    queue.enqueue(old_success)
    validator=bridge._validator(qm,runner,contract,material,lc)
    raw=(state/'announcement_flash/queue'/recovered['raw_path']).read_text()
    old_item=queue.run_next(lambda _j:raw,validator,idempotency_keys={bridge._stable_queue_identity(queue,old_success)},wait_for_model_slot=False)
    old_saved=queue._load_state()['jobs'][old_item['idempotency_key']];old_bytes=(state/'announcement_flash/queue'/old_saved['validated_path']).read_bytes()
    candidate=bridge._extension_payload(payload,material,plan,sha,lambda _m:1,999999)
    candidate['rules']+=':another-prompt';candidate['prompt_sha256']='d'*64
    selected=bridge._extension_saved_task(candidate,queue,state/'announcement_flash/queue',validator,failed_key=key,extension_sha256=sha)
    assert selected[1]['status']=='SUCCEEDED' and (state/'announcement_flash/queue'/old_saved['validated_path']).read_bytes()==old_bytes
    # A new failure is kept as failed; a repeated continuation cannot retry it.
    normal=bridge._transport_executor
    def factory(*args,**kwargs):
        execute=normal(*args,**kwargs)
        def invalid(job):
            result=json.loads(execute(job))
            if job.payload['article_id']=='EASTMONEY:NEW_B':result['reader_output']['direction']='MIXED'
            return json.dumps(result,ensure_ascii=False)
        return invalid
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    count=len(calls);delivered,_=read_delivery(bridge.SafeRoot(state),value['job_id']);assert delivered['counts']['FAILED']==1
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    assert len(calls)==count


def test_semantic_extension_model_lock_busy_and_user_stop_leave_checkpoint_without_claim(tmp_path,monkeypatch):
    import fcntl,os
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch)
    import announcement_queue as qm
    import batch_runner as runner
    q=bridge._new_only_queue(qm,state/'announcement_flash/queue',runner.MODEL_ID)
    fd=os.open(q._model_lock_path,os.O_RDONLY)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    assert result['system_stop']['failure_code']=='MODEL_LOCK_BUSY' and len(calls)==1
    jobs=q._load_state()['jobs'];pending=next(j for k,j in jobs.items() if k!=key)
    assert pending['status']=='PENDING' and pending['attempt_count']==0
    result=bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha,stop_requested=lambda:True)
    assert result['state']=='USER_STOPPED' and len(calls)==1


@pytest.mark.parametrize('busy_first',[False,True])
def test_semantic_extension_api_bound_submit_and_no_repeat_first(tmp_path,monkeypatch,busy_first):
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from v4.manager_workbench import api as api_module
    from v4.manager_workbench import announcement_update as update_module
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    from v4.manager_workbench.contracts import JobRecord,JobState,RunContext,Phase
    from v4.manager_workbench.jobs import JobCoordinator
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=_semantic_failure_fixture(tmp_path,monkeypatch)
    # The API imports the same owned runner; retain the offline test transport.
    import ops.run_manager_flash_announcements as live_bridge
    for name in ('_extension_plan','_extension_checkpoint'):monkeypatch.setattr(live_bridge,name,getattr(bridge,name))
    store=WorkbenchStore(tmp_path/'owner');jobs=JobCoordinator(store,workers=1)
    service=SimpleNamespace(store=store,jobs=jobs,config=SimpleNamespace(capture_root=capture,shared_root=tmp_path/'shared'))
    def popen(command,**_kw):
        code=bridge._main(command[3:],signalled=[]);return SimpleNamespace(returncode=code,poll=lambda:code)
    update=AnnouncementUpdate(service,popen=popen)
    context=RunContext(target_date=value['target_date'],cutoff=value['cutoff'],phase=Phase.MANUAL,trigger='MANUAL',rules_version='V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1',scope_refs={'capture_operation':'ANNOUNCEMENT_FLASH_INCREMENTAL'})
    job=JobRecord(job_id=value['job_id'],run_id=value['job_id'],context=context,state=JobState.PARTIAL,step='DONE',retryable=True);store.save_job(job)
    monkeypatch.setattr(api_module,'AnnouncementUpdate',lambda _s:update)
    app=FastAPI();app.include_router(api_module.create_router(service))
    def settled():
        for _ in range(200):
            saved=jobs.get(job.job_id)
            if saved.state not in {JobState.QUEUED,JobState.RUNNING}:return saved
            time.sleep(.01)
        pytest.fail('offline worker failed to terminalize')
    try:
        with TestClient(app) as client:
            url=f'/api/v4/manager-workbench/announcement-flash/{job.job_id}/execute-preprocessed'
            s=update.semantic_recovery_snapshot(job.job_id,pre['preprocessing']['sha256']);assert s['eligible'] and s['phase']=='RECOVER_FAILED'
            request={'phase':s['phase'],'report_sha256':s['report_sha256'],'extension_sha256':s['extension_sha256'],'first_delivery_sha256':s['delivery_sha256']}
            assert client.post(url,json={**request,'extension_sha256':'0'*64}).status_code==409
            assert client.post(url,json={**request,'first_delivery_sha256':'0'*64}).status_code==409
            assert len(calls)==1
            if busy_first:
                import announcement_queue as qm, batch_runner as runner,fcntl,os
                queue=bridge._new_only_queue(qm,state/'announcement_flash/queue',runner.MODEL_ID)
                fd=os.open(queue._model_lock_path,os.O_RDONLY)
                try:
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    assert client.post(url,json=request).status_code==202;assert settled().state==JobState.PARTIAL
                finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
                assert len(calls)==1
                pending=update.semantic_recovery_snapshot(job.job_id,pre['preprocessing']['sha256'])
                assert pending['eligible'] and pending['phase']=='RECOVER_FAILED' and pending['checkpoint_state']=='PENDING'
                request={**request,'first_delivery_sha256':pending['delivery_sha256']}
            assert client.post(url,json=request).status_code==202;assert settled().state==JobState.PARTIAL
            assert len(calls)==2
            assert client.post(url,json=request).status_code==409
            assert client.post(url,json={'phase':'FIRST','report_sha256':s['report_sha256']}).status_code==409
            s=update.semantic_recovery_snapshot(job.job_id,pre['preprocessing']['sha256']);assert s['phase']=='CONTINUE_REMAINING'
            assert client.post(url,json={'phase':s['phase'],'report_sha256':s['report_sha256'],'extension_sha256':s['extension_sha256'],'first_delivery_sha256':s['delivery_sha256']}).status_code==202
            assert settled().state==JobState.SUCCEEDED and len(calls)==3
    finally:jobs.stop()


def test_semantic_extension_real_shape_history_preserved_sources_do_not_block_recovery(tmp_path,monkeypatch):
    """Reviewer P1: prepared C sources still include history after report admission."""
    import test_manager_announcement_daily_workflow as workflow
    original=workflow._fixture
    def with_history(*args,**kwargs):
        fixture=original(*args,**kwargs);bridge,value,state,capture,calls,observations=fixture
        product=json.loads((capture/value['capture_product']['artifact_ref']).read_bytes())
        row=next(r for r in product['rows'] if r['art_code']=='NEW_B')
        monkeypatch.setattr(bridge,'_pinned_candidate_history',lambda:[{'identity':{'article_id':'EASTMONEY:NEW_B','body_sha256':row['body_text_sha256']},'status':'SUCCEEDED'}])
        return fixture
    monkeypatch.setattr(workflow,'_fixture',with_history)
    bridge,value,state,capture,calls,kw,pre,plan,sha,key,old=workflow._semantic_failure_fixture(tmp_path,monkeypatch)
    assert pre['report']['counts']['model_required_articles']==1
    assert next(e for e in pre['report']['catalogue'] if e['article_id']=='EASTMONEY:NEW_B')['primary_disposition']=='OTHER_HISTORY_PRESERVED'
    args=dict(execute_report_sha256=pre['preprocessing']['sha256'],extension_sha256=sha)
    result=bridge._run(value,**kw,**args,execution_phase='RECOVER_FAILED')
    assert result['counts']['queue']['succeeded']==1 and calls==[('EASTMONEY:NEW_A','ordinary')]*2
    saved=json.loads((state/'announcement_flash/queue/queue-state.json').read_bytes())['jobs']
    assert saved[key]==old and not any(j['identity']['article_id']=='EASTMONEY:NEW_B' for j in saved.values())


def _semantic_prepared_identity_shape():
    import os
    fixture=os.environ.get('ANNOUNCEMENT_PREPARED_IDENTITY_FIXTURE')
    if fixture:
        data=json.loads(Path(fixture).read_bytes());entries=data['eligible'];prepared=data['prepared']
    else:
        entries=[]
        for i in range(215):
            parts=0 if i<208 else (5,3,2,2,4,9,13)[i-208]
            entries.append({'article_id':f'NEWS:{i}','source_sha256':f'{i:064x}','body_sha256':f'{i+1000:064x}',
                'source_date':'2026-10-20','symbol':'HK.00001','primary_disposition':'MODEL_LONG' if parts else 'MODEL_ORDINARY','part_count':parts})
        prepared=deepcopy(entries)+[{'article_id':f'EXCLUDED:{i}','source_sha256':f'{i+500:064x}',
            'body_sha256':f'{i+1500:064x}','source_date':'2026-10-16','symbol':'HK.00002',
            'primary_disposition':'OTHER_HISTORY_PRESERVED' if i<242 else 'USER_STOPPED_EXCLUDED','part_count':2 if i%24==0 else 0} for i in range(244)]
    ordinary=[];long={}
    for entry in prepared:
        article={f:entry[f] for f in ('article_id','source_sha256','body_sha256')}
        article['article_metadata']={'publication_date':entry['source_date'],'symbol':entry['symbol']}
        if entry['part_count']:
            long[entry['article_id']]={'article':article,'part_payloads':[{**deepcopy(article),'date':entry['source_date']} for _ in range(entry['part_count'])]}
        else:ordinary.append({**article,'date':entry['source_date']})
    return entries,ordinary,long,prepared


def test_semantic_extension_full459_shape_filters_history_and_stopped():
    bridge=_bridge_module();entries,ordinary,long,prepared=_semantic_prepared_identity_shape()
    original=deepcopy((ordinary,long));assert len(prepared)==459 and len(entries)==215
    excluded=[e for e in prepared if e['primary_disposition'] not in {'MODEL_ORDINARY','MODEL_LONG'}]
    assert sum(e['primary_disposition']=='OTHER_HISTORY_PRESERVED' for e in excluded)==242
    assert sum(e['primary_disposition']=='USER_STOPPED_EXCLUDED' for e in excluded)==2
    selected,selected_long=bridge._extension_prepared_subset(entries,ordinary,long)
    assert len(selected)==208 and len(selected_long)==7
    assert {p['article_id'] for p in selected}|set(selected_long)=={e['article_id'] for e in entries}
    assert not ({p['article_id'] for p in selected}|set(selected_long)) & {e['article_id'] for e in excluded}
    assert sorted(len(s['part_payloads']) for s in selected_long.values())==[2,2,3,4,5,9,13]
    assert (ordinary,long)==original


@pytest.mark.parametrize('field',['article_id','source_sha256','body_sha256','date','symbol','publication_date','missing','duplicate','long_part_date'])
def test_semantic_extension_prepared_identity_drift_never_hides_eligible_missing(field):
    bridge=_bridge_module();entries,ordinary,long,prepared=_semantic_prepared_identity_shape()
    first=next(p for p in ordinary if p['article_id']==next(e['article_id'] for e in entries if e['primary_disposition']=='MODEL_ORDINARY'))
    if field in ('symbol','publication_date'):first['article_metadata'][field]='WRONG'
    elif field=='missing':ordinary.remove(first)
    elif field=='duplicate':ordinary.append(deepcopy(first))
    elif field=='long_part_date':
        aid=next(e['article_id'] for e in entries if e['primary_disposition']=='MODEL_LONG');long[aid]['part_payloads'][0]['date']='2026-10-19'
    else:first[field]='WRONG'
    with pytest.raises(bridge.FlashRunError,match='EXTENSION_PREPARED_COVERAGE_CHANGED'):
        bridge._extension_prepared_subset(entries,ordinary,long)


def test_semantic_fix_risk_extract_is_new_identity_only_and_never_edits_raw():
    from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
    bridge=_bridge_module();bridge._load_helper();import batch_runner as runner
    material={'configuration_sha256':'c'*64,'configuration_material':{'semantic_contract_version':SEMANTIC_CONTRACT_VERSION}}
    payload={'article_body':'公告限定：未经审计。\n\n另段文字。','messages':[{'content':SEMANTIC_CONTRACT}],
        'configuration_sha256':'c'*64,'prompt_sha256':bridge.sha(SEMANTIC_CONTRACT.encode()),'body_sha256':'b'*64,
        'semantic_contract_version':SEMANTIC_CONTRACT_VERSION}
    for notes in ([],['未经 审计。'],['公告限定：未经审计。']):
        raw={'reader_output':{'risk_notes':notes}};original=deepcopy(raw)
        bridge._risk_extract_guard(payload,raw,material,runner);assert raw==original
    for notes in (['未经审计，可能影响后续经营。'],[''],[1]):
        raw={'reader_output':{'risk_notes':notes}};original=deepcopy(raw)
        with pytest.raises(bridge.FlashRunError,match='RISK_EXTRACT_SOURCE_UNSUPPORTED'):
            bridge._risk_extract_guard(payload,raw,material,runner)
        assert raw==original
    legacy={**payload,'messages':[{'content':'original historical contract'}],'configuration_sha256':'d'*64}
    legacy.pop('semantic_contract_version')
    bridge._risk_extract_guard(legacy,{'reader_output':{'risk_notes':['历史格式允许改写，回放不增加新规则。']}},material,runner)
    with pytest.raises(bridge.FlashRunError,match='CONTRACT_IDENTITY'):
        bridge._risk_extract_guard({**legacy,'rules':'semantic-contract:'+SEMANTIC_CONTRACT_VERSION},{'reader_output':{'risk_notes':[]}},material,runner)
    with pytest.raises(bridge.FlashRunError,match='CONTRACT_IDENTITY'):
        bridge._risk_extract_guard({**payload,'configuration_sha256':'d'*64},{'reader_output':{'risk_notes':[]}},material,runner)
    # A part may not cite a risk from outside the frozen chunk it was shown.
    body=payload['article_body'];units=runner.build_source_unit_map(body,bridge.sha(body.encode()))['units']
    first=units[0]['source_unit_id']
    part={**payload,'queue_task_kind':'announcement_reader_part','body_sha256':bridge.sha(body.encode()),
        'part_descriptor':{'start_source_unit_id':first,'end_source_unit_id':first}}
    assert len(units)>1
    with pytest.raises(bridge.FlashRunError,match='SOURCE_UNSUPPORTED'):
        bridge._risk_extract_guard(part,{'reader_output':{'risk_notes':[units[-1]['text'].strip()]}},material,runner)
    synthesis={**part,'queue_task_kind':'announcement_reader_synthesis','allowed_source_intervals':[[0,0]]}
    bridge._risk_extract_guard(synthesis,{'reader_output':{'risk_notes':['未经审计。']}},material,runner)
    with pytest.raises(bridge.FlashRunError,match='SOURCE_UNSUPPORTED'):
        bridge._risk_extract_guard(synthesis,{'reader_output':{'risk_notes':[units[-1]['text'].strip()]}},material,runner)


def test_semantic_fix_actual_raw_rejected_new_contract_but_legacy_replay_unchanged():
    import os
    fixture=os.environ.get('ANNOUNCEMENT_SEMANTIC_FIX_FIXTURE')
    if not fixture:pytest.skip('Set actual read-only semantic diagnosis fixture path for live-shape replay')
    root=Path(fixture);bridge=_bridge_module();helper=bridge._load_helper()
    import batch_runner as runner,announcement_queue as qm,build_length_canary as lc
    contract=runner.load_active_contract(bridge.REPO_ROOT/'v4/manager_workbench/engines/announcement.py')
    material=bridge._owned_request_material(helper,runner,contract);validator=bridge._validator(qm,runner,contract,material,lc)
    payload=json.loads((root/'input.json').read_bytes());raw=json.loads((root/'raw.json').read_bytes());saved=json.loads((root/'validated.json').read_bytes())
    assert validator(SimpleNamespace(payload=payload),raw)==saved
    original=deepcopy(raw);new=deepcopy(payload)
    new['messages'][0]['content']=material['prompt'];new['prompt_sha256']=material['prompt_sha256'];new['configuration_sha256']=material['configuration_sha256']
    with pytest.raises(qm.ValidationRejected,match='RISK_EXTRACT_SOURCE_UNSUPPORTED'):
        validator(SimpleNamespace(payload=new),raw)
    assert raw==original
    # Keep the original selected-direction oracle: never manufacture POSITIVE.
    old_raw=json.loads((root.parent/'diagnosis/failed-raw.json').read_bytes());old_raw['reader_output']['risk_notes']=[]
    with pytest.raises(qm.ValidationRejected,match='ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'):
        validator(SimpleNamespace(payload=new),old_raw)


def test_semantic_fix_transport_stops_before_second_model_http_and_lookup():
    bridge=_bridge_module();calls=[]
    class Base:
        def __init__(self,*a,**kw):self._round=0
        def begin_job(self):self._round=0
        def _stream_completion(self,*a,**kw):self._round+=1;calls.append('HTTP');return 'response'
        def _call_simple_workflow_lookup(self,*a,**kw):calls.append('lookup')
    transport=bridge._single_http_canary_transport(SimpleNamespace(GatedStreamingTransport=Base),SimpleNamespace(TransportError=RuntimeError))
    transport.begin_job();assert transport._stream_completion()=='response'
    with pytest.raises(RuntimeError,match='ONE_HTTP_LIMIT'):transport._stream_completion()
    with pytest.raises(RuntimeError,match='ONE_HTTP_LIMIT'):transport._call_simple_workflow_lookup({})
    assert calls==['HTTP']


def _semantic_reviewed_success_fixture(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,old_plan,old_sha,failed_key,failed=_semantic_failure_fixture(tmp_path,monkeypatch)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=old_sha)
    io=bridge.SafeRoot(state);root=state/'announcement_flash/queue';jobs=json.loads((root/'queue-state.json').read_bytes())['jobs']
    reviewed_key=next(k for k in jobs if k!=failed_key);item=jobs[reviewed_key];payload=bridge._queue_payload(root,item)
    trace=f'announcement_flash/evidence/streams/{reviewed_key}/attempt-0001/'
    io.write_bytes(trace+'round-01.request-input.json',bridge.canonical({'messages':payload['messages'],'structured_outputs':{'json':payload['structured_output_schema']}}))
    io.write_bytes(trace+'stream-receipt.json',bridge.canonical({'rounds':[{'synthetic':True}]}))
    io.write_bytes(trace+'round-01.raw.sse',b'SYNTHETIC_OFFLINE_RESPONSE')
    evidence=tmp_path/'review-evidence';(evidence/'live-review').mkdir(parents=True)
    review={'status':'LIVE_RECOVERY_SEMANTIC_FAIL','actual_calls':{'new_queue_jobs':1,'physical_new_attempts':1,
        'request_rounds':1,'logical_attempt':2,'new_key':reviewed_key},'job_id':value['job_id'],
        'source_report_sha256':pre['preprocessing']['sha256'],'execution_extension_sha256':old_sha,'identity_binding':{'new_key':reviewed_key}}
    review_raw=bridge.canonical(review);(evidence/'live-review/receipt.json').write_bytes(review_raw)
    pins={**bridge.SEMANTIC_REPAIR,'job_id':value['job_id'],'report_sha256':pre['preprocessing']['sha256'],
        'predecessor_sha256':old_sha,'review_sha256':bridge.sha(review_raw),'queue_key':reviewed_key,'queue_record_sha256':bridge.sha(bridge.canonical(item)),
        **{f:item[f] for f in ('payload_sha256','raw_sha256','validated_sha256')},
        'request_sha256':bridge.sha(io.read_bytes(trace+'round-01.request-input.json')),
        'stream_sha256':bridge.sha(io.read_bytes(trace+'stream-receipt.json')),'sse_sha256':bridge.sha(io.read_bytes(trace+'round-01.raw.sse'))}
    monkeypatch.setattr(bridge,'SEMANTIC_REPAIR',pins);monkeypatch.setattr(bridge,'SEMANTIC_REPAIR_EVIDENCE_ROOT',evidence)
    # Offline transport executor fixture returns directly and never makes HTTP.
    monkeypatch.setattr(bridge,'_single_http_canary_transport',lambda *a,**kw:SimpleNamespace(close=lambda:None))
    plan,sha=bridge._extension_plan(state,capture,value['job_id'],pre['preprocessing']['sha256'])
    prefix=f'announcement_flash/jobs/{value["job_id"]}'
    io.write_bytes(prefix+'/execution-extensions/'+sha+'.json',bridge.canonical(plan)+b'\n')
    io.write_bytes(prefix+'/execution-extensions/latest.json',bridge.canonical({'sha256':sha})+b'\n')
    return bridge,value,state,capture,calls,kw,pre,plan,sha,pins,jobs,evidence


def _semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence,*,verdict=None):
    root=state/'announcement_flash/queue';jobs=json.loads((root/'queue-state.json').read_bytes())['jobs']
    key,item=next((k,j) for k,j in jobs.items() if bridge._queue_payload(root,j).get('execution_extension_sha256')==sha)
    payload=bridge._queue_payload(root,item);io=bridge.SafeRoot(state)
    trace=f'announcement_flash/evidence/streams/{key}/attempt-0001/'
    request=bridge.canonical({'messages':payload['messages'],'structured_outputs':{'json':payload['structured_output_schema']}})
    io.write_bytes(trace+'round-01.request-input.json',request);io.write_bytes(trace+'stream-receipt.json',bridge.canonical({'rounds':[{'synthetic':True}]}))
    receipt={'schema':'v4.manager_workbench.semantic_canary_acceptance.v1','reviewer':'independent-offline-test',
        'verdict':verdict,'source_faithfulness':verdict,'job_id':plan['job_id'],'queue_key':key,'report_sha256':plan['report_sha256'],
        'capture_sha256':plan['capture_product']['sha256'],'extension_sha256':sha,'payload_sha256':item['payload_sha256'],
        'raw_sha256':item['raw_sha256'],'validated_sha256':item['validated_sha256'],'request_sha256':bridge.sha(request),
        **{f:payload[f] for f in ('article_id','source_sha256','body_sha256','prompt_sha256','configuration_sha256')},'actual_calls':1}
    path=evidence/bridge.SEMANTIC_ACCEPTANCE_REF
    if verdict is not None:path.parent.mkdir(exist_ok=True);path.write_bytes(bridge.canonical(receipt))
    return key,item,payload,receipt,path


def test_semantic_fix_only_reviewed_success_recovers_once_and_continue_waits_for_bound_pass(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    root=state/'announcement_flash/queue';prefix=f'announcement_flash/jobs/{value["job_id"]}';io=bridge.SafeRoot(state)
    assert plan['failed']['logical_attempt']==3 and plan['semantic_repair']['max_canary_model_http_requests']==1
    assert len(plan['entries'])==2
    kwargs=dict(execute_report_sha256=pre['preprocessing']['sha256'],extension_sha256=sha)
    bridge._run(value,**kw,**kwargs,execution_phase='RECOVER_FAILED');assert len(calls)==3
    key,item,payload,receipt,path=_semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence)
    assert payload['semantic_recovery_of']['queue_key']==pins['queue_key'] and payload['recovery_of']['logical_attempt']==3
    assert bridge._extension_checkpoint(state,plan,sha)==(key,'AWAITING_SEMANTIC_REVIEW')
    bridge._run(value,**kw,**kwargs,execution_phase='RECOVER_FAILED');assert len(calls)==3
    with pytest.raises(bridge.FlashRunError,match='SEMANTIC_CANARY_NOT_ACCEPTED'):
        bridge._run(value,**kw,**kwargs,execution_phase='CONTINUE_REMAINING')
    path.parent.mkdir(exist_ok=True);path.write_bytes(bridge.canonical({**receipt,'verdict':'PASS','source_faithfulness':'PASS','raw_sha256':'0'*64}))
    with pytest.raises(bridge.FlashRunError,match='SEMANTIC_REVIEW_BINDING_CHANGED'):bridge._extension_checkpoint(state,plan,sha)
    path.write_bytes(bridge.canonical({**receipt,'verdict':'FAIL','source_faithfulness':'FAIL'}))
    assert bridge._extension_checkpoint(state,plan,sha)==(key,'SEMANTIC_REVIEW_FAILED')
    path.write_bytes(bridge.canonical({**receipt,'verdict':'PASS','source_faithfulness':'PASS'}));approval=bridge.sha(path.read_bytes())
    assert bridge._extension_checkpoint(state,plan,sha)==(key,'SUCCEEDED')
    # The runner requires the exact evidence admitted by the existing submit owner.
    request={'phase':'CONTINUE_REMAINING','report_sha256':pre['preprocessing']['sha256'],'extension_sha256':sha,'semantic_review_sha256':'0'*64}
    def save_request(request):
        raw=bridge.canonical(request)+b'\n';rsha=bridge.sha(raw);ref=prefix+'/extension-requests/'+rsha+'.json'
        io.write_bytes(ref,raw);io.write_bytes(prefix+'/extension-request.json',bridge.canonical({'artifact_ref':ref,'sha256':rsha}))
    save_request(request)
    with pytest.raises(bridge.FlashRunError,match='SEMANTIC_APPROVAL_CHANGED'):
        bridge._run(value,**kw,**kwargs,execution_phase='CONTINUE_REMAINING')
    assert len(calls)==3
    save_request({**request,'semantic_review_sha256':approval})
    bridge._run(value,**kw,**kwargs,execution_phase='CONTINUE_REMAINING');assert len(calls)==4
    after=json.loads((root/'queue-state.json').read_bytes())['jobs'];assert all(after[k]==v for k,v in old.items())
    # The exact rejected old success is never overwritten, nor globally retried.
    assert after[pins['queue_key']]['status']=='SUCCEEDED' and after[key]['attempt_count']==1


def test_semantic_fix_seed_rejects_drift_and_other_successes_remain_reusable(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    root=state/'announcement_flash/queue';item=old[pins['queue_key']];original=(root/item['raw_path']).read_bytes()
    (root/item['raw_path']).write_bytes(original+b' ')
    with pytest.raises(bridge.FlashRunError,match='SAVED_ARTIFACT_CHANGED'):bridge._extension_plan(state,capture,value['job_id'],pre['preprocessing']['sha256'])
    (root/item['raw_path']).write_bytes(original)
    receipt=evidence/'live-review/receipt.json';original_review=receipt.read_bytes();receipt.write_bytes(original_review+b' ')
    with pytest.raises(bridge.FlashRunError,match='REVIEW_CHANGED'):bridge._extension_plan(state,capture,value['job_id'],pre['preprocessing']['sha256'])
    receipt.write_bytes(original_review)
    helper=bridge._load_helper();import announcement_queue as qm,batch_runner as runner,build_length_canary as lc
    contract=runner.load_active_contract(bridge.REPO_ROOT/'v4/manager_workbench/engines/announcement.py');material=bridge._owned_request_material(helper,runner,contract)
    validator=bridge._validator(qm,runner,contract,material,lc);queue=bridge._new_only_queue(qm,root,runner.MODEL_ID)
    payload=bridge._queue_payload(root,item);candidate=bridge._extension_payload(payload,material,plan,sha,lambda _:1,999999)
    # Without the exact independent failure exception this saved full success wins.
    preserved=bridge._extension_saved_task(candidate,queue,root,validator,failed_key=plan['failed']['queue_key'],extension_sha256=sha)
    assert preserved[0]==pins['queue_key']
    assert bridge._extension_saved_task(candidate,queue,root,validator,failed_key=plan['failed']['queue_key'],extension_sha256=sha,semantic_repair=plan['semantic_repair']) is None


def test_semantic_fix_rest_gate_and_current_candidate_projection_preserve_saved_history(tmp_path,monkeypatch):
    from v4.manager_workbench import announcement_update as update_module
    from v4.manager_workbench.announcement_update import AnnouncementUpdate,_semantic_project_stocks
    from v4.manager_workbench.contracts import JobState
    from v4.manager_workbench.jobs import JobConflict
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    import ops.run_manager_flash_announcements as live_bridge
    for name in ('_extension_plan','_extension_checkpoint','_semantic_canary_review','_semantic_quarantined_results'):
        monkeypatch.setattr(live_bridge,name,getattr(bridge,name))
    store=WorkbenchStore(tmp_path/'owner');job=SimpleNamespace(state=JobState.PARTIAL)
    service=SimpleNamespace(store=store,jobs=SimpleNamespace(get=lambda _:job),config=SimpleNamespace(capture_root=capture))
    update=AnnouncementUpdate(service);monkeypatch.setattr(update,'_stop_requested',lambda _:False)
    snapshot=update.semantic_recovery_snapshot(value['job_id'],pre['preprocessing']['sha256'])
    assert snapshot['phase']=='RECOVER_FAILED' and snapshot['semantic_review_state']=='SOURCE_SEMANTIC_FAIL_RECOVERABLE'
    delivered,_=read_delivery(bridge.SafeRoot(state),value['job_id']);quarantine=snapshot['quarantined_results']
    bad={'queue_key':pins['queue_key'],'result_sha256':pins['validated_sha256'],'reason':'bad','article_id':'FIRST'}
    good={'queue_key':'e'*64,'result_sha256':'f'*64,'reason':'good','article_id':'OTHER'}
    stocks=[{'symbol':'HK.00001','articles':[bad,good],'reasons':['bad','good']},{'symbol':'HK.00002','articles':[good],'reasons':['good']}]
    original=deepcopy(stocks);projected=_semantic_project_stocks(stocks,quarantine)
    assert stocks==original and projected[0]['articles']==[good] and projected[1]==stocks[1]
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    key,item,payload,receipt,path=_semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence)
    blocked=update.semantic_recovery_snapshot(value['job_id'],pre['preprocessing']['sha256'])
    assert not blocked['eligible'] and blocked['phase'] is None and blocked['checkpoint_state']=='AWAITING_SEMANTIC_REVIEW'
    assert len(blocked['quarantined_results'])==2
    with pytest.raises(JobConflict,match='EXTENSION_EXECUTION_NOT_ELIGIBLE'):
        update._submit_semantic_recovery(value['job_id'],pre['preprocessing']['sha256'],'CONTINUE_REMAINING',sha,blocked['delivery_sha256'])
    assert len(calls)==3


def test_semantic_fix_api_cannot_continue_without_review_and_pins_pass_at_submit(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from v4.manager_workbench import api as api_module
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    from v4.manager_workbench.contracts import JobRecord,JobState,RunContext,Phase
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    import ops.run_manager_flash_announcements as live_bridge
    for name in ('_extension_plan','_extension_checkpoint','_semantic_canary_review','_semantic_quarantined_results'):
        monkeypatch.setattr(live_bridge,name,getattr(bridge,name))
    store=WorkbenchStore(tmp_path/'owner')
    context=RunContext(target_date=value['target_date'],cutoff=value['cutoff'],phase=Phase.MANUAL,trigger='MANUAL',rules_version='V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1',scope_refs={'capture_operation':'ANNOUNCEMENT_FLASH_INCREMENTAL'})
    job=JobRecord(job_id=value['job_id'],run_id=value['job_id'],context=context,state=JobState.PARTIAL,step='DONE',retryable=True)
    service=SimpleNamespace(store=store,jobs=SimpleNamespace(get=lambda _:job,submit=lambda *a,**kw:job),config=SimpleNamespace(capture_root=capture))
    update=AnnouncementUpdate(service);monkeypatch.setattr(update,'_stop_requested',lambda _:False);monkeypatch.setattr(update,'_active_flash_attempts',lambda **kw:[])
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    key,item,payload,receipt,path=_semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence)
    snapshot=update.semantic_recovery_snapshot(value['job_id'],pre['preprocessing']['sha256'])
    monkeypatch.setattr(api_module,'AnnouncementUpdate',lambda _:update)
    app=FastAPI();app.include_router(api_module.create_router(service))
    request={'phase':'CONTINUE_REMAINING','report_sha256':pre['preprocessing']['sha256'],'extension_sha256':sha,'first_delivery_sha256':snapshot['delivery_sha256']}
    with TestClient(app) as client:
        assert client.post(f'/api/v4/manager-workbench/announcement-flash/{value["job_id"]}/execute-preprocessed',json=request).status_code==409
    assert len(calls)==3
    path.parent.mkdir(exist_ok=True);path.write_bytes(bridge.canonical({**receipt,'verdict':'PASS','source_faithfulness':'PASS'}))
    update._submit_semantic_recovery(value['job_id'],pre['preprocessing']['sha256'],'CONTINUE_REMAINING',sha,snapshot['delivery_sha256'])
    prefix=f'announcement_flash/jobs/{value["job_id"]}'
    io=bridge.SafeRoot(state);binding=json.loads(io.read_bytes(prefix+'/extension-request.json'));saved=json.loads(io.read_bytes(binding['artifact_ref']))
    assert saved['semantic_review_sha256']==bridge.sha(path.read_bytes()) and saved['extension_sha256']==sha
    assert len(calls)==3 # Submit fixture does not launch another executor.


def test_semantic_fix_failed_third_attempt_is_preserved_and_never_automatically_retried(tmp_path,monkeypatch):
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    normal=bridge._transport_executor
    def factory(*a,**kw):
        execute=normal(*a,**kw)
        def unsupported(job):
            raw=json.loads(execute(job));raw['reader_output']['risk_notes']=['未披露的未来经营风险。']
            return json.dumps(raw,ensure_ascii=False)
        return unsupported
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    args=dict(execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    bridge._run(value,**kw,**args);assert len(calls)==3
    root=state/'announcement_flash/queue';jobs=json.loads((root/'queue-state.json').read_bytes())['jobs']
    key,item=next((k,j) for k,j in jobs.items() if bridge._queue_payload(root,j).get('execution_extension_sha256')==sha)
    assert item['status']=='FAILED' and item['last_error']['code']=='RISK_EXTRACT_SOURCE_UNSUPPORTED'
    raw=(root/item['raw_path']).read_bytes();assert '未披露的未来经营风险' in raw.decode()
    assert bridge._extension_checkpoint(state,plan,sha)==(key,'FAILED')
    bridge._run(value,**kw,**args);assert len(calls)==3 and (root/item['raw_path']).read_bytes()==raw
    with pytest.raises(bridge.FlashRunError,match='CANARY_NOT_SUCCEEDED'):
        bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='CONTINUE_REMAINING',extension_sha256=sha)
    after=json.loads((root/'queue-state.json').read_bytes())['jobs'];assert all(after[k]==v for k,v in old.items())


def test_semantic_correction_synthesis_uses_authoritative_integer_intervals_and_rejects_unseen_units():
    from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT,SEMANTIC_CONTRACT_VERSION
    from v4.manager_workbench import announcement_chunks as chunks
    bridge=_bridge_module();bridge._load_helper();import batch_runner as runner
    body='第一风险：未经审计。\n\n中间段：另一限定。\n\n最后段：不同事项。'
    bsha=bridge.sha(body.encode());unit_map=runner.build_source_unit_map(body,bsha);units=unit_map['units'];assert len(units)==3
    aid='EASTMONEY:INTEGER_INTERVAL';first=units[0]['source_unit_id']
    reports=[{'part_index':1,'part_count':1,'part_result_sha256':'a'*64,'part_raw_response_sha256':'b'*64,
        'part_descriptor':{'part_index':1,'part_count':1,'source_unit_ids':[first]},
        'citation_ranges':[{'start_source_unit_id':aid+'::'+first,'end_source_unit_id':aid+'::'+first}]}]
    intervals=chunks.synthesis_intervals_from_reports(reports,article_id=aid,unit_map=unit_map);assert intervals==[[0,0]]
    material={'configuration_sha256':'c'*64,'configuration_material':{'semantic_contract_version':SEMANTIC_CONTRACT_VERSION}}
    payload={'article_body':body,'body_sha256':bsha,'messages':[{'content':SEMANTIC_CONTRACT}],
        'prompt_sha256':bridge.sha(SEMANTIC_CONTRACT.encode()),'configuration_sha256':'c'*64,
        'semantic_contract_version':SEMANTIC_CONTRACT_VERSION,'queue_task_kind':'announcement_reader_synthesis','allowed_source_intervals':intervals}
    raw={'reader_output':{'risk_notes':['第一风险：未经审计。']}};original=deepcopy(raw)
    bridge._risk_extract_guard(payload,raw,material,runner);assert raw==original
    with pytest.raises(bridge.FlashRunError,match='SOURCE_UNSUPPORTED'):
        bridge._risk_extract_guard(payload,{'reader_output':{'risk_notes':[units[1]['text'].strip()]}},material,runner)
    for invalid in ([[first,first]],[[-1,0]],[[0,len(units)]],[[1,0]],[[True,0]],[[0]],None):
        with pytest.raises(bridge.FlashRunError,match='SOURCE_INTERVAL_INVALID'):
            bridge._risk_extract_guard({**payload,'allowed_source_intervals':invalid},raw,material,runner)
    # Adjacent visible units share the existing union allowance; gaps remain unseen.
    joined=units[0]['text']+units[1]['text']
    bridge._risk_extract_guard({**payload,'allowed_source_intervals':[[0,0],[1,1]]},{'reader_output':{'risk_notes':[joined]}},material,runner)
    with pytest.raises(bridge.FlashRunError,match='SOURCE_UNSUPPORTED'):
        bridge._risk_extract_guard({**payload,'allowed_source_intervals':[[0,0],[2,2]]},{'reader_output':{'risk_notes':[body]}},material,runner)


@pytest.mark.parametrize('acceptance',['missing','FAIL','wrong_raw','wrong_key','invalid_json'])
def test_semantic_correction_review_errors_keep_verified_quarantine_and_other_stock_contributions(tmp_path,monkeypatch,acceptance):
    from v4.manager_workbench.announcement_update import AnnouncementUpdate,_semantic_project_stocks
    from v4.manager_workbench.contracts import JobState
    from v4.manager_workbench.store import WorkbenchStore
    from v4.manager_workbench.announcement_delivery import read_analysis
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    normal=bridge._transport_executor
    def factory(*a,**kwargs):
        execute=normal(*a,**kwargs)
        def selected(job):
            raw=json.loads(execute(job));out=raw['reader_output'];out.update(disposition='SELECTED_EVENT',selection_basis='OPERATING_EVENT',direction='POSITIVE');out['changes']=list(out['impact'])
            return json.dumps(raw,ensure_ascii=False)
        return selected
    monkeypatch.setattr(bridge,'_transport_executor',factory)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    key,item,payload,receipt,path=_semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence)
    if acceptance!='missing':
        path.parent.mkdir(exist_ok=True);review={**receipt,'verdict':'PASS','source_faithfulness':'PASS'}
        if acceptance=='FAIL':review.update(verdict='FAIL',source_faithfulness='FAIL')
        elif acceptance=='wrong_raw':review['raw_sha256']='0'*64
        elif acceptance=='wrong_key':review['queue_key']='0'*64
        path.write_bytes(b'{' if acceptance=='invalid_json' else bridge.canonical(review))
    import ops.run_manager_flash_announcements as live_bridge
    for name in ('_extension_plan','_extension_checkpoint','_semantic_canary_review','_semantic_quarantined_results','FlashRunError'):
        monkeypatch.setattr(live_bridge,name,getattr(bridge,name))
    service=SimpleNamespace(store=WorkbenchStore(tmp_path/'owner'),jobs=SimpleNamespace(get=lambda _:SimpleNamespace(state=JobState.PARTIAL)),config=SimpleNamespace(capture_root=capture))
    update=AnnouncementUpdate(service);monkeypatch.setattr(update,'_stop_requested',lambda _:False)
    delivered,binding=read_delivery(bridge.SafeRoot(state),value['job_id']);saved=deepcopy(delivered)
    root=state/'announcement_flash/queue';raw_before=(root/item['raw_path']).read_bytes();validated_before=(root/item['validated_path']).read_bytes();queue_before=(root/'queue-state.json').read_bytes()
    snapshot=update.semantic_recovery_snapshot(value['job_id'],pre['preprocessing']['sha256'])
    assert snapshot['eligible'] is False
    assert {'queue_key':key,'result_sha256':item['validated_sha256']} in snapshot['quarantined_results']
    if acceptance.startswith('wrong'):assert snapshot['reason']=='SEMANTIC_REVIEW_BINDING_CHANGED'
    assert any(a['queue_key']==key for stock in delivered['stocks'] for a in stock['articles'])
    stocks=deepcopy(delivered['stocks']);good={**stocks[0]['articles'][0],'queue_key':'9'*64,'result_sha256':'8'*64,'article_id':'OTHER_VALID','reason':'其它已验收贡献'}
    stocks[0]['articles'].append(good);stocks[0]['reasons'].append(good['reason']);original=deepcopy(stocks)
    projected=_semantic_project_stocks(stocks,snapshot['quarantined_results'])
    assert stocks==original and projected[0]['articles']==[good] and projected[0]['reasons']==[good['reason']]
    assert all(a.get('queue_key')!=key for stock in projected for a in stock['articles'])
    analysis=read_analysis(bridge.SafeRoot(state),delivered,binding)
    assert any(a.get('result_sha256')==item['validated_sha256'] and a['analysis_state']=='AVAILABLE' for a in analysis['articles'])
    assert delivered==saved and (root/item['raw_path']).read_bytes()==raw_before
    assert (root/item['validated_path']).read_bytes()==validated_before and (root/'queue-state.json').read_bytes()==queue_before


def test_semantic_correction_exact_pass_releases_only_the_accepted_canary_quarantine(tmp_path,monkeypatch):
    from v4.manager_workbench.announcement_update import AnnouncementUpdate,_semantic_project_stocks
    from v4.manager_workbench.contracts import JobState
    from v4.manager_workbench.store import WorkbenchStore
    bridge,value,state,capture,calls,kw,pre,plan,sha,pins,old,evidence=_semantic_reviewed_success_fixture(tmp_path,monkeypatch)
    bridge._run(value,**kw,execute_report_sha256=pre['preprocessing']['sha256'],execution_phase='RECOVER_FAILED',extension_sha256=sha)
    key,item,payload,receipt,path=_semantic_write_new_trace_and_acceptance(bridge,state,plan,sha,evidence,verdict='PASS')
    import ops.run_manager_flash_announcements as live_bridge
    for name in ('_extension_plan','_extension_checkpoint','_semantic_canary_review','_semantic_quarantined_results','FlashRunError'):
        monkeypatch.setattr(live_bridge,name,getattr(bridge,name))
    service=SimpleNamespace(store=WorkbenchStore(tmp_path/'owner'),jobs=SimpleNamespace(get=lambda _:SimpleNamespace(state=JobState.PARTIAL)),config=SimpleNamespace(capture_root=capture))
    update=AnnouncementUpdate(service);monkeypatch.setattr(update,'_stop_requested',lambda _:False)
    snapshot=update.semantic_recovery_snapshot(value['job_id'],pre['preprocessing']['sha256'])
    assert snapshot['eligible'] is True and snapshot['phase']=='CONTINUE_REMAINING'
    assert snapshot['semantic_review_sha256']==bridge.sha(path.read_bytes())
    assert snapshot['quarantined_results']==[{'queue_key':pins['queue_key'],'result_sha256':pins['validated_sha256']}]
    approved={'queue_key':key,'result_sha256':item['validated_sha256'],'reason':'已验收'}
    stock={'symbol':'HK.00001','articles':[approved],'reasons':['已验收']}
    assert _semantic_project_stocks([stock],snapshot['quarantined_results'])==[stock]
