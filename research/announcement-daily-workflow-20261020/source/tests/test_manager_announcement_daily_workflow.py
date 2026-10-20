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
            response=client.post(url,json={'phase':'FIRST','report_sha256':pre['preprocessing']['sha256']})
            assert response.status_code==202 and response.json()['data']['job_id']==job.job_id
            first=settled();assert first.state==JobState.PARTIAL and first.completed_count==1
            first_delivery,first_binding=read_delivery(store.io,job.job_id)
            first_bytes=store.io.read_bytes(first_binding['artifact_ref'])
            response=client.post(url,json={'phase':'CONTINUE','report_sha256':pre['preprocessing']['sha256'],
                'first_delivery_sha256':first_binding['sha256']})
            assert response.status_code==202
            final=settled();assert final.state==JobState.SUCCEEDED and final.completed_count==2
            assert calls==[('EASTMONEY:NEW_A','ordinary'),('EASTMONEY:NEW_B','ordinary')]
            assert store.io.read_bytes(first_binding['artifact_ref'])==first_bytes
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
