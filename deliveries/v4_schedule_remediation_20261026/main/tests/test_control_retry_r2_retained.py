# R2 retains prior retry/sibling checks; A producer identity expectation corrected per C-P2-002.
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import os
import pytest
from ops import run_v35_macos_scheduler as scheduler
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.dispatcher import refresh_retry_source_identity, capture_retry_source_identity, dispatch_due
from infrastructure.scheduling.catalog import load_workload_catalog
from contracts.runtime_tasks import DispatchRequest, DispatchMode

DAY='20261026'
START=datetime(2026,10,26,9,1,tzinfo=scheduler.SHANGHAI)


def identity(tmp_path):
    p=tmp_path/'source.txt';p.write_text('source-run-1 / receipt-sha-1')
    return p, refresh_retry_source_identity({'descriptors':[{'path':str(p),'kind':'pointer'}]})


def receipt(root, at, source=None, failure='UPSTREAM_NOT_READY', status='FAILED', slot='0901', **extra):
    ledger=ExecutionLedger(root)
    rel=f'receipts/live/{DAY}/{slot}/{at:%H%M%S}.dispatch-receipt.json'
    ledger.write_receipt(rel,{'status':status,'finished_at':at.isoformat(),
        'business_date':DAY,'slot':slot,'failure_class':failure,'source_identity':source,**extra})


def blocks(root, at, **kwargs):
    return scheduler._slot_blocks_retry(root,DAY,kwargs.pop('slot','0901'),moment=at,**kwargs)


def test_same_known_source_only_initial_and_deadline_fallback(tmp_path):
    source, ident=identity(tmp_path)
    root=tmp_path/'ledger'
    receipt(root,START,ident)
    for minute in range(1,59):
        assert blocks(root,START+timedelta(minutes=minute))
    assert not blocks(root,START+timedelta(minutes=59))
    receipt(root,START+timedelta(minutes=59),ident)
    assert blocks(root,START+timedelta(minutes=59,seconds=20))


def test_changed_source_waits_300s_then_can_resume(tmp_path):
    source, ident=identity(tmp_path);root=tmp_path/'ledger'
    receipt(root,START,ident)
    source.write_text('source-run-2 / receipt-sha-2')
    assert blocks(root,START+timedelta(seconds=299))
    assert not blocks(root,START+timedelta(seconds=300))
    receipt(root,START+timedelta(seconds=300),refresh_retry_source_identity(ident))
    assert blocks(root,START+timedelta(minutes=10))


def test_release_mtime_and_updated_timestamp_are_not_new_data(tmp_path):
    source, ident=identity(tmp_path);root=tmp_path/'ledger'
    receipt(root,START,ident,release_id='old',upstream_fingerprint='old-code')
    os.utime(source,None)
    assert blocks(root,START+timedelta(minutes=10),release_id='new',upstream_fingerprint='new-code')
    latest=tmp_path/'latest.json'
    def write(run,stamp,other='other1'):
        latest.write_text(json.dumps({'entries':{DAY+'/ROLE':{'run_id':run,'artifact_sha256':'a'*64,'updated_at':stamp},'other/ROLE':{'run_id':other}}}))
    write('r1','one')
    descriptor={'descriptors':[{'path':str(latest),'kind':'shared_latest','entry_keys':[DAY+'/ROLE']}]}
    a=refresh_retry_source_identity(descriptor)
    write('r1','two','other2')
    assert refresh_retry_source_identity(descriptor)['fingerprint']==a['fingerprint']
    write('r2','three')
    assert refresh_retry_source_identity(descriptor)['fingerprint']!=a['fingerprint']


def test_unknown_identity_is_bounded_and_not_permanently_disabled(tmp_path):
    root=tmp_path/'ledger';unknown=refresh_retry_source_identity({'descriptors':[]})
    assert unknown['status']=='CANNOT_CONFIRM'
    receipt(root,START,unknown,failure='INPUT_MISSING')
    assert not blocks(root,START+timedelta(minutes=5))
    receipt(root,START+timedelta(minutes=5),unknown,failure='INPUT_MISSING')
    assert blocks(root,START+timedelta(minutes=10))
    assert not blocks(root,START+timedelta(minutes=59))


def test_missing_pointer_appearance_is_new_identity(tmp_path):
    path=tmp_path/'pending.txt'
    old=refresh_retry_source_identity({'descriptors':[{'path':str(path),'kind':'pointer'}]})
    assert old['status']=='IDENTIFIED' and old['items'][0]['state']=='MISSING'
    root=tmp_path/'ledger';receipt(root,START,old)
    path.write_text('source-run-new')
    assert not blocks(root,START+timedelta(minutes=5))


def test_hk_auction_never_reopens_after_0919_even_new_source(tmp_path):
    source,ident=identity(tmp_path);root=tmp_path/'ledger'
    at=START.replace(minute=15)
    receipt(root,at,ident,slot='0915')
    source.write_text('new')
    assert blocks(root,at+timedelta(minutes=5),slot='0915')
    due=scheduler.resolve_due_slot(ledger_root=root,now=at+timedelta(minutes=5))
    assert due['slot']!='0915'


def test_success_and_live_claim_survive_code_or_source_change(tmp_path):
    source,ident=identity(tmp_path);root=tmp_path/'ledger'
    receipt(root,START,ident,status='SUCCEEDED')
    source.write_text('new')
    assert blocks(root,START+timedelta(minutes=10),release_id='new-code')
    request=DispatchRequest(DAY,DAY,DAY,'0925',DispatchMode.LIVE)
    claim=ExecutionLedger(root).try_claim_dispatch(request)
    assert claim.acquired and blocks(root,START.replace(minute=30),slot='0925')


def test_network_keeps_independent_backoff(tmp_path):
    root=tmp_path/'ledger';receipt(root,START,None,failure='NETWORK')
    assert blocks(root,START+timedelta(seconds=299))
    assert not blocks(root,START+timedelta(seconds=300))


def test_dispatcher_records_small_source_and_preserves_successful_work(tmp_path):
    root=tmp_path/'ledger'
    selector=tmp_path/'selector'
    p=selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt'
    p.parent.mkdir(parents=True);p.write_text('source1')
    class Executor:
        selector_data_root=selector
        shared_data_root=None
        def __init__(self): self.calls=[]
        def __call__(self,workload,request,decision):
            self.calls.append(workload.workload_id)
            return {'status':'FAILED','failure_class':'INPUT_MISSING'} if workload.workload_id=='research_panel_daily_a' else {'status':'SUCCEEDED'}
    executor=Executor()
    request=DispatchRequest(DAY,DAY,DAY,'1700',DispatchMode.LIVE)
    first=dispatch_due(request,load_workload_catalog(),executor,ledger=ExecutionLedger(root))
    assert first.status=='FAILED' and first.failure_class=='INPUT_MISSING'
    assert first.source_identity['status']=='CANNOT_CONFIRM'
    assert first.source_identity['reason']=='A_DAILY_INPUT_IDENTITY_UNAVAILABLE'
    before=list(executor.calls)
    second=dispatch_due(request,load_workload_catalog(),executor,ledger=ExecutionLedger(root))
    assert executor.calls[len(before):]==['research_panel_daily_a']
    assert 'hourly_research' in before
    assert list(root.rglob('*.dispatch-receipt.json'))
