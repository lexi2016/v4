"""Existing collector with synthetic transport only; real temporal predicate."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import stage_center.live_collectors as lc

DATE='20260928'

def fetch(monkeypatch,time='2026-09-28 09:35:06'):
    def bridge(codes,**kw):
        return [dict(code=c,prev_close_price=10,last_price=11,turnover=30_000_000,volume_ratio=2,update_time=time) for c in codes],[]
    monkeypatch.setattr(lc,'_load_shared_module',lambda *a:SimpleNamespace(fetch_futu_snapshot=bridge))
    return lc._futu_hkconnect_active_snapshot(Path('/synthetic'),codes=['HK.00001'],python_path='synthetic-python',process_runner=lambda *a,**k: None,trade_date=DATE,cutoff_at='09:35:05')

def diag(evidence):
    raw=next((x.split('=',1)[1] for x in evidence if x.startswith('active_snapshot_temporal_diagnostic=')),None)
    assert raw is not None,'row-level cutoff diagnostic must survive via source_evidence'
    return json.loads(raw)

def test_after_cutoff_stays_rejected_with_exact_row_reason(monkeypatch):
    active,ev,errs=fetch(monkeypatch)
    assert not active and 'HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE' in errs
    report=diag(ev)
    assert report['rows'][0]['code']=='HK.00001'
    assert report['rows'][0]['reason']=='AFTER_CUTOFF'
    assert report['rows'][0]['update_time']=='2026-09-28 09:35:06'
    assert report['fetch_started_at'] and report['fetch_finished_at']

@pytest.mark.parametrize('time,reason',[('', 'MISSING_OR_UNPARSEABLE'),('2026-09-27 09:00:00','WRONG_TRADE_DATE'),('2026-09-28 09:35:05','WITHIN_CUTOFF')])
def test_temporal_boundaries_preserve_original_gate(monkeypatch,time,reason):
    active,ev,errs=fetch(monkeypatch,time);report=diag(ev)
    assert report['rows'][0]['reason']==reason
    assert bool(active)==(reason=='WITHIN_CUTOFF')

def journal_module():
    assert importlib.util.find_spec('stage_center.attempt_evidence') is not None,'attempt journal required'
    from stage_center import attempt_evidence
    return attempt_evidence

def test_distinct_attempt_events_not_overwritten(tmp_path):
    mod=journal_module()
    for i in (1,2):
        with mod.capture_attempt(tmp_path,trade_date=DATE,stage_id='STAGE_0930_0935',attempt_number=i,evaluated_at='historical-evaluation',due_status='LATE_CATCHUP_REPLAY') as j:
            mod.emit_snapshot({'cutoff_at':'09:35:05','rows':[{'code':'HK.00001','reason':'AFTER_CUTOFF'}]})
            j.finish({'status':'CANNOT_CONFIRM'})
    paths=list(tmp_path.glob('attempt_evidence/*/*.json'))
    assert len(paths)==6
    data=[json.loads(p.read_text()) for p in paths]
    assert len({x['attempt_id'] for x in data})==2
    assert sum(x['event']=='START' for x in data)==2

def test_exception_is_not_swallowed_and_event_preserved(tmp_path):
    mod=journal_module()
    with pytest.raises(RuntimeError,match='synthetic'):
        with mod.capture_attempt(tmp_path,trade_date=DATE,stage_id='STAGE_0930_0935',attempt_number=1,evaluated_at='t',due_status='DUE'):
            raise RuntimeError('synthetic')
    events=[json.loads(p.read_text()) for p in tmp_path.glob('attempt_evidence/*/*.json')]
    assert any(x['event']=='RAISED' for x in events)

def test_diagnostic_write_failure_does_not_enable_or_retry_business(tmp_path):
    mod=journal_module();(tmp_path/'attempt_evidence').write_text('block directory')
    with mod.capture_attempt(tmp_path,trade_date=DATE,stage_id='STAGE_0930_0935',attempt_number=1,evaluated_at='t',due_status='DUE') as j:
        j.finish({'status':'CANNOT_CONFIRM'})
    assert j.summary()['status']=='INCOMPLETE'

def test_snapshot_diagnostic_is_written_into_current_attempt(monkeypatch,tmp_path):
    mod=journal_module()
    with mod.capture_attempt(tmp_path,trade_date=DATE,stage_id='STAGE_0930_0935',attempt_number=3,evaluated_at='2026-09-28T09:40:00+08:00',due_status='LATE_CATCHUP_REPLAY') as journal:
        _,ev,errs=fetch(monkeypatch)
        journal.finish({'status':'CANNOT_CONFIRM'})
    event=[json.loads(p.read_text()) for p in tmp_path.glob('attempt_evidence/*/*_HK_SNAPSHOT.json')][0]
    assert event['attempt_number']==3
    assert event['detail']==diag(ev)
    assert event['grants_retry'] is False

def test_snapshot_hash_not_changed_by_new_diagnostic(monkeypatch):
    import hashlib
    _,ev,_=fetch(monkeypatch,'2026-09-28 09:35:05')
    normalized=[dict(code='HK.00001',prev_close_price=10.0,last_price=11.0,turnover=30000000.0,volume_ratio=2.0,update_time='2026-09-28 09:35:05')]
    expected=hashlib.sha256(json.dumps(normalized,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert 'active_snapshot_sha256='+expected in ev

def test_late_dispatch_three_attempts_preserve_each_history_without_new_budget(monkeypatch,tmp_path):
    from datetime import datetime,timezone,timedelta
    import ops.run_stage_center_nodes as node
    from ops._run_stage_center_nodes_parts.stage_dispatch import __dispatch_stage_body
    mod=journal_module();current=[None];calls=[]
    stage_id='STAGE_0930_0935';now=datetime(2026,9,28,9,36,tzinfo=timezone(timedelta(hours=8)))
    decision=SimpleNamespace(stage_id=stage_id,status='LATE_CATCHUP_REPLAY',scheduled_at=now)
    class Runner:
        config=SimpleNamespace(receipt_root=tmp_path)
        def due_decisions(self,*a,**k):return [decision]
        def _receipt_path(self,d,s):return tmp_path/d/s/'receipt.json'
        def _run_one(self,d):
            calls.append(1);fetch(monkeypatch);return dict(status='CANNOT_CONFIRM',write_performed=False)
        def _write_receipt(self,result,d,s):
            current[0]=dict(result);p=self._receipt_path(d,s);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result));return result
    class Deadline:
        def checkpoint(self,*a,**k):pass
        def due(self,*a,**k):pass
        def event(self,*a,**k):pass
        def complete_receipt(self,path,result,**kw):return result
    scope=dict(vars(node));scope.update(_deadline=Deadline(),_calendar_gate=lambda *a,**k:{'status':'ELIGIBLE'},_read_receipt=lambda *a:current[0],_exact_hk_d1_dependency_rearm=lambda *a:None,_retry_is_due=lambda *a,**k:True,_receipt_path=lambda c,d,s:tmp_path/d/s/'receipt.json')
    runner=Runner();config={'node_max_attempts':3,'node_retry_backoff_seconds':0}
    for i in range(1,4):
        result=__dispatch_stage_body(scope,config,DATE,stage_id,now,mode='SCHEDULED',runner=runner,precaptures=[])
        assert result['node_attempt_count']==i and result['attempt_diagnostic']['status']=='RECORDED'
    result=__dispatch_stage_body(scope,config,DATE,stage_id,now,mode='SCHEDULED',runner=runner,precaptures=[])
    assert result['status']=='SKIPPED_RETRY_EXHAUSTED' and len(calls)==3
    assert len(list(tmp_path.glob(DATE+'/'+stage_id+'/attempt_evidence/*/*_HK_SNAPSHOT.json')))==3
