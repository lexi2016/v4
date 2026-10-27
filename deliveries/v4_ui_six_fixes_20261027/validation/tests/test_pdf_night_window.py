"""Admission-only regressions for the existing owned PDF queue and child owner."""
from __future__ import annotations
import hashlib, json, sys, threading
from datetime import datetime
from pathlib import Path
import pytest
from infrastructure import zsxq_pdf_ingestion as pdf
from ops import run_v35_macos_scheduler_daemon as daemon


def moment(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


@pytest.mark.parametrize(('value','allowed'),[
    ('2026-10-27T01:59:59.999999+08:00',False),
    ('2026-10-27T02:00:00+08:00',True),
    ('2026-10-27T08:29:59.999999+08:00',True),
    ('2026-10-27T08:30:00+08:00',False),
    ('2026-10-27T23:59:59+08:00',False),
    ('2026-10-26T18:00:00Z',True),
    ('2026-10-27T00:29:59Z',True),
    ('2026-10-27T00:30:00Z',False),
])
def test_exact_shanghai_night_bounds_and_utc_conversion(value,allowed):
    result=pdf.pdf_queue_night_admission(moment(value))
    assert result['allowed'] is allowed
    assert result['status']==('ADMITTED' if allowed else 'DEFERRED')
    assert result['window_timezone']=='Asia/Shanghai'


def test_unknown_timezone_fails_closed():
    assert pdf.pdf_queue_night_admission(datetime(2026,10,27,2))['allowed'] is False


def fixture_hook(tmp_path,clock,popen):
    return daemon.PdfQueueDrainHook(app_root=tmp_path,data_root=tmp_path,python_path=Path(sys.executable),
        clock=clock,popen_factory=popen,poll_seconds=0.01,wall_seconds=150,idle_seconds=1)


def test_daytime_starts_zero_children_and_never_probes_queue(tmp_path,monkeypatch):
    calls=[]
    hook=fixture_hook(tmp_path,lambda:moment('2026-10-27T09:25:00+08:00'),lambda *a,**k:calls.append(a))
    monkeypatch.setattr(hook,'_queue_probe',lambda:pytest.fail('daytime must not probe owned queue'))
    assert hook._child_due()[0] is False
    assert hook._run_child()['status']=='DEFERRED'
    hook.thread.start()
    hook.stop(join_seconds=1)
    assert not hook.thread.is_alive() and not calls


def test_daytime_direct_tick_zero_ocr_preserves_pending_checkpoints_and_success(tmp_path,monkeypatch):
    index=tmp_path/pdf.STATE_RELATIVE;index.parent.mkdir(parents=True)
    index.write_text(json.dumps({'pending':{'status':'PARTIAL','processed_page_count':8,'pages_file_sha256':'checkpoint'},
                                 'success':{'status':'READY','pages_file_sha256':'completed-original'}}))
    checkpoint=tmp_path/'pages.json';checkpoint.write_text('[{"page_number":1,"text":"已有正文"}]')
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (index,checkpoint)}
    monkeypatch.setattr(pdf,'pending_pdf_tasks',lambda *_a,**_k:pytest.fail('daytime must not enumerate/admit a task'))
    monkeypatch.setattr(pdf,'process_pdf_batch',lambda *_a,**_k:pytest.fail('daytime must not invoke download/OCR'))
    result=pdf.process_next_pdf_task(tmp_path,now=lambda:moment('2026-10-27T08:30:00+08:00'))
    assert result['status']=='DEFERRED' and result['processed_document_count']==0
    assert result['ocr_invoked'] is False and result['queue_mutated'] is False
    assert result['pending_task_count'] is None  # unknown, never fake an empty queue
    assert {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before}==before
    assert all(result[key] is False for key in ('production_allowed','buy_gate_updated','orders_sent'))


def test_night_reuses_existing_backlog_task_and_keeps_other_success(tmp_path,monkeypatch):
    task={'document_id':'existing-pending','trade_date':'20261025','slot':'0830','source_run_id':'original-source','file_id':'original-file'}
    partial={'status':'PARTIAL','attempts':1,'processed_page_count':8,'page_count':18,
             'progress_updated_at':'2026-10-25T08:31:00+08:00','pages_file_sha256':'original-checkpoint'}
    successful={'status':'READY','processed_page_count':2,'pages_file_sha256':'completed-original'}
    index={'documents':{'existing-pending':{'engine_runs':{'engine':partial}},'completed':{'engine_runs':{'engine':successful}}}}
    success_before=json.dumps(successful,sort_keys=True)
    monkeypatch.setattr(pdf,'pending_pdf_tasks',lambda *_a,**_k:[task] if partial['status']!='READY' else [])
    monkeypatch.setattr(pdf,'_read_index',lambda *_a:index)
    monkeypatch.setattr(pdf,'_latest_engine_run',lambda row:('engine',row['engine_runs']['engine']))
    calls=[]
    def original_batch(**kwargs):
        assert kwargs['trade_date']=='20261025' and kwargs['source_run_id']=='original-source'
        assert kwargs['file_id']=='original-file' and kwargs['limit']==1
        assert partial['processed_page_count']==8 and partial['pages_file_sha256']=='original-checkpoint'
        calls.append(kwargs);partial.update(status='READY',processed_page_count=18)
        return {'processed_this_batch':[{'status':'READY'}],'done_total':2,'partial_total':0,'failed_total':0,'pending_total':0}
    monkeypatch.setattr(pdf,'process_pdf_batch',original_batch)
    result=pdf.process_next_pdf_task(tmp_path,now=lambda:moment('2026-10-27T02:00:00+08:00'))
    assert result['status']=='READY' and result['processed_document_count']==1
    assert result['before_status']=='PARTIAL' and result['before_attempts']==1
    assert len(calls)==1 and json.dumps(successful,sort_keys=True)==success_before


def test_night_child_uses_existing_owner_and_finishes_across_close_without_signal(tmp_path,monkeypatch):
    current=[moment('2026-10-27T08:29:59+08:00')];calls=[];signals=[]
    class Child:
        pid=424242
        returncode=None
        polls=0
        def poll(self):
            self.polls+=1
            if self.polls>1:self.returncode=0
            return self.returncode
        def wait(self,timeout=None):return self.returncode
    def popen(command,**kwargs):
        calls.append(command);current[0]=moment('2026-10-27T08:30:01+08:00')
        kwargs['stdout'].write(b'{"status":"READY","processed_document_count":1,"processed_page_count":2}')
        kwargs['stdout'].flush();return Child()
    hook=fixture_hook(tmp_path,lambda:current[0],popen)
    monkeypatch.setattr(daemon.os,'killpg',lambda *args:signals.append(args))
    monkeypatch.setattr(hook,'_finish_child',lambda *a,**k:pytest.fail('window close must never cancel inflight child'))
    monkeypatch.setattr(hook,'_queue_probe',lambda:{'status':'PDF_QUEUE_INPUT_PENDING'})
    assert hook._child_due()[0] is True
    result=hook._run_child()
    assert result['status']=='READY' and hook.child is None
    assert len(calls)==1 and calls[0][0]==sys.executable and calls[0][1]=='-B'
    assert '--pdf-queue-tick' in calls[0]
    assert hook._child_due()[0] is False
    assert hook._run_child()['status']=='DEFERRED'
    assert len(calls)==1 and not signals
