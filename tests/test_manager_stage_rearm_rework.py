"""SIMULATED bounded recovery tests. No production task is invoked."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import copy
import json
import pytest
from ops import run_stage_center_nodes as nodes
from stage_center.acquisition import StageUniverseBinding
SH=ZoneInfo('Asia/Shanghai')
NOW=datetime(2026,9,18,9,42,tzinfo=SH)
DATE='20260918'; STAGE='STAGE_0935_0940'

def receipt(**changes):
    out=dict(schema_version='stage_center.runner.receipt.v1',trade_date=DATE,stage_id=STAGE,status='CANNOT_CONFIRM',first_failed_layer='EXACT_SELECTION_INPUT_BINDING',node_attempt_count=3,retry_exhausted=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,markets={'HK_CONNECT':{'status':'CANNOT_CONFIRM','selected_rows':0,'cannot_confirm':['exact-date input missing: hkconnect_d1_top100.json']}})
    out.update(changes); return out

@pytest.fixture
def setup(monkeypatch,tmp_path):
    binding=StageUniverseBinding.ready(market='HK_CONNECT',trade_date=DATE,role='HK_CONNECT_D1_TOP100',codes=tuple(f'HK.{i:05}' for i in range(1,101)),source_run_id='hk-d1-'+'a'*16,sha256='a'*64)
    monkeypatch.setattr('stage_center.runner._build_hk_d1_binding',lambda *a:binding)
    monkeypatch.setattr(nodes,'_rearm_wall_now',lambda:NOW,raising=False)
    return {'hk_d1_root':str(tmp_path/'pools'),'receipt_root':str(tmp_path/'receipts'),'node_max_attempts':3},binding

def test_same_day_verified_dependency_one_shot(setup):
    cfg,_=setup
    r=nodes._exact_hk_d1_dependency_rearm(cfg,DATE,receipt(),NOW)
    assert r['dependency_rearm_count']==1
    assert r['dependency_rearm_source_sha256']=='a'*64
    assert nodes._exact_hk_d1_dependency_rearm(cfg,DATE,receipt(**r),NOW) is None

@pytest.mark.parametrize('change',[{'trade_date':'20260917'},{'first_failed_layer':'RAW_ACQUISITION'},{'dependency_rearm_count':1},{'dependency_rearm_count':True},{'dependency_rearm_count':'0'},{'node_attempt_count':True},{'node_attempt_count':4},{'node_attempt_count':'3'},{'retry_exhausted':1},{'production_allowed':True},{'status':'READY'}])
def test_ineligible_receipts_never_rearm(setup,change):
    cfg,_=setup
    assert nodes._exact_hk_d1_dependency_rearm(cfg,DATE,receipt(**change),NOW) is None

def test_historical_evaluation_cannot_impersonate_today(setup,monkeypatch):
    cfg,_=setup
    monkeypatch.setattr(nodes,'_rearm_wall_now',lambda:NOW.replace(day=19))
    assert nodes._exact_hk_d1_dependency_rearm(cfg,DATE,receipt(),NOW) is None

def test_only_exact_hk_missing_input_class(setup):
    cfg,_=setup
    r=receipt(); r['markets']['HK_CONNECT']['cannot_confirm']=['bad sha hkconnect_d1_top100.json']
    assert nodes._exact_hk_d1_dependency_rearm(cfg,DATE,r,NOW) is None

def test_string_or_partial_binding_cannot_rearm(setup,monkeypatch):
    cfg,_=setup
    monkeypatch.setattr('stage_center.runner._build_hk_d1_binding',lambda *a:SimpleNamespace(status='READY',source_run_id='x',sha256='a'*64))
    assert nodes._exact_hk_d1_dependency_rearm(cfg,DATE,receipt(),NOW) is None

def _dispatch_fixture(setup,monkeypatch):
    cfg,_=setup; persisted=receipt(); writes=[]; calls=[]
    path=Path(cfg['receipt_root'])/DATE/STAGE/'receipt.json'; path.parent.mkdir(parents=True); path.write_text(json.dumps(persisted))
    def write(r,*args):
        r={**r,'trade_date':DATE,'stage_id':STAGE}; path.write_text(json.dumps(r)); writes.append(copy.deepcopy(r)); return r
    def run(d):
        calls.append(d); assert json.loads(path.read_text())['dependency_rearm_count']==1
        return receipt()
    runner=SimpleNamespace(config=SimpleNamespace(lock_root=path.parent/'locks'),due_decisions=lambda *a,**kw:[SimpleNamespace(stage_id=STAGE,status='LATE_CATCHUP_REPLAY')],_run_one=run,_write_receipt=write)
    monkeypatch.setattr(nodes,'_calendar_gate',lambda *a,**kw:{'status':'ELIGIBLE'})
    monkeypatch.setattr('stage_center.runner._slot_lock_path',lambda *a:path.parent/'slot.lock')
    return cfg,runner,path,writes,calls

def test_reservation_persisted_before_run_and_only_one_extra_attempt(setup,monkeypatch):
    cfg,runner,path,writes,calls=_dispatch_fixture(setup,monkeypatch)
    out=nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)
    assert len(calls)==1 and out['node_attempt_count']==4 and out['dependency_rearm_count']==1
    assert out['retry_exhausted'] is True
    again=nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)
    assert again['status']=='SKIPPED_RETRY_EXHAUSTED' and len(calls)==1

def test_lock_reread_does_not_overwrite_competing_receipt(setup,monkeypatch):
    cfg,runner,path,writes,calls=_dispatch_fixture(setup,monkeypatch)
    class Lock:
        def __init__(self,*a): pass
        def acquire(self): path.write_text(json.dumps(receipt(dependency_rearm_count=1))); return True
        def release(self): pass
    monkeypatch.setattr('stage_center.runner.SlotLock',Lock)
    out=nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)
    assert out['status']=='SKIPPED_RECEIPT_CHANGED' and calls==[] and writes==[]

def test_crash_after_reservation_does_not_grant_another_rearm(setup,monkeypatch):
    cfg,runner,path,writes,calls=_dispatch_fixture(setup,monkeypatch)
    def fail(d): raise RuntimeError('SIMULATED crash')
    runner._run_one=fail
    with pytest.raises(RuntimeError): nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)
    assert json.loads(path.read_text())['dependency_rearm_count']==1
    assert nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)['status']=='SKIPPED_RETRY_EXHAUSTED'

def test_inner_runner_receipt_replacement_cannot_erase_consumed_chance(setup,monkeypatch):
    cfg,runner,path,writes,calls=_dispatch_fixture(setup,monkeypatch)
    def inner(d):
        # The real runner owns a receipt writer too: model its intermediate write.
        runner._write_receipt(receipt(node_attempt_count=0),DATE,STAGE)
        raise RuntimeError('SIMULATED inner runner crashed after intermediate receipt')
    runner._run_one=inner
    with pytest.raises(RuntimeError): nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)
    assert nodes._dispatch_stage(cfg,DATE,STAGE,NOW,mode='RECOVERY',runner=runner)['status']=='SKIPPED_RETRY_EXHAUSTED'
