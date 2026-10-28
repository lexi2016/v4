"""SIMULATED concurrency/projection tests. Real threading, no live source claims."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
import pytest
from v4.manager_research.workspace_read_control import ReadCoordinator,WorkspaceReadError,checkpoint,ProjectionMemo

def test_same_key_singleflight_deepcopy_and_completed_reads_not_reused():
    control=ReadCoordinator();started=Event();release=Event();calls=[]
    def compute():calls.append(1);started.set();assert release.wait(2);return {'stocks':[{'name':'SIMULATED'}]}
    with ThreadPoolExecutor(2) as pool:
        one=pool.submit(control.run,('20260922','historical'),compute);assert started.wait(2)
        two=pool.submit(control.run,('20260922','historical'),compute)
        time.sleep(.05);release.set();a,b=one.result(2),two.result(2)
    assert len(calls)==1 and b['read_metrics']['joined_inflight']
    a['stocks'][0]['name']='mutation';assert b['stocks'][0]['name']=='SIMULATED'
    control.run(('20260922','historical'),compute);assert len(calls)==2

def test_leader_cancellation_does_not_kill_live_follower():
    control=ReadCoordinator();first=Event();second=Event();started=Event();release=Event()
    def compute():started.set();assert release.wait(2);checkpoint();return {'stocks':[]}
    with ThreadPoolExecutor(2) as pool:
        one=pool.submit(control.run,('d','h'),compute,cancelled=first);assert started.wait(2)
        two=pool.submit(control.run,('d','h'),compute,cancelled=second);time.sleep(.05)
        first.set();release.set()
        with pytest.raises(WorkspaceReadError,match='CANCELLED'):one.result(2)
        assert two.result(2)['read_metrics']['joined_inflight']

def test_all_cancelled_retains_slot_until_native_call_returns():
    control=ReadCoordinator(max_active=1);token=Event();started=Event();release=Event()
    def compute():started.set();assert release.wait(2);checkpoint();return {}
    with ThreadPoolExecutor(1) as pool:
        f=pool.submit(control.run,('d','h'),compute,cancelled=token);assert started.wait(2);token.set()
        with pytest.raises(WorkspaceReadError,match='BUSY'):control.run(('other','h'),lambda:{})
        release.set()
        with pytest.raises(WorkspaceReadError,match='CANCELLED'):f.result(2)
    assert control.run(('other','h'),lambda:{})['read_metrics']['outcome']=='RETURNED'

def test_subscriber_count_has_finite_bound():
    control=ReadCoordinator(max_subscribers=1);started=Event();release=Event()
    def compute():started.set();assert release.wait(2);return {}
    with ThreadPoolExecutor(1) as pool:
        f=pool.submit(control.run,('d','h'),compute);assert started.wait(2)
        with pytest.raises(WorkspaceReadError,match='BUSY'):control.run(('d','h'),lambda:{})
        release.set();f.result(2)

def test_deadline_checked_at_cooperative_boundary():
    with pytest.raises(WorkspaceReadError,match='TIMEOUT'):
        ReadCoordinator().run(('d','h'),lambda: (time.sleep(.02),checkpoint(),{})[-1],seconds=.005)

def test_projection_memo_keys_cutoff_inputs_reader_and_not_mutable_results(monkeypatch):
    from v4.manager_research import workspace_read_control as m
    memo=ProjectionMemo();calls=[]
    def calc():calls.append(1);return {'v':[len(calls)]}
    a=memo.compute('m',{'cutoff':'one','negative':'risk'},calc)
    a['v'][0]=999
    assert memo.compute('m',{'cutoff':'one','negative':'risk'},calc)=={'v':[1]}
    memo.compute('m',{'cutoff':'two','negative':'risk'},calc)
    memo.compute('m',{'cutoff':'two','negative':'risk changed'},calc)
    monkeypatch.setattr(m,'contract_identity',lambda:'new-READER')
    memo.compute('m',{'cutoff':'two','negative':'risk changed'},calc)
    assert len(calls)==4

def test_projection_memo_capacity_bytes_ttl_and_exceptions():
    memo=ProjectionMemo(capacity=2,max_bytes=100,ttl=.015)
    for i in range(4):memo.compute('x',i,lambda:{'x':1})
    assert len(memo._values)==2 and memo._bytes<=100
    memo.compute('x','big',lambda:{'x':'large'*100});assert len(memo._values)==2
    time.sleep(.02);memo.compute('x','now',lambda:{'x':1});assert len(memo._values)==1
    for _ in range(2):
        with pytest.raises(ValueError):memo.compute('x','failure',lambda:(_ for _ in []).throw(ValueError('source invalid')))
    assert len(memo._values)==1

def test_optional_material_pure_memo_runs_only_after_missing_master_gate(tmp_path):
    from v4.manager_research.workspace_discovery import read_material_discovery
    class Forbidden:
        def compute(self,*a,**k):pytest.fail('raw identity validation cannot be skipped')
    result=read_material_discovery([],{'market_session':'20260921'},None,projection_memo=Forbidden())
    assert result['status']=='CANNOT_CONFIRM'

def test_native_io_validator_source_change_changes_contract(monkeypatch):
    from pathlib import Path
    from v4.manager_research.workspace_read_control import contract_identity
    import io
    before=contract_identity();original=Path.open
    def altered(path,*args,**kwargs):
        if path.name=='owned_io.py':
            with original(path,'rb') as handle:raw=handle.read()
            return io.BytesIO(raw+b'\n# SIMULATED validator revision')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',altered)
    assert contract_identity()!=before
