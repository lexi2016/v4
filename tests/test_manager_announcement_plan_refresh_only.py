from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import run_manager_announcement_cycle as cycle
from v4.manager_research import workspace


AFTER_CLOSE={
    'enabled':True,'start_local':'16:00','end_local':'23:00',
    'max_attempts_per_target_date':3,'retry_backoff_seconds':600,
}


def saved_plan(identity,*,kind='MANUAL_REFRESH',run_id='a'*32):
    return {
        'run_id':run_id,'sha256':'b'*64,'input_identity':identity,'execution_kind':kind,
        'owner':'ManagerResearchJobService.refresh_workspace_plan',
        'workspace':{'input_identity':identity,'semantic_version':'test-v1',
                     'plan_context':{'research_cutoff':'2026-09-28T16:01:00+08:00'}},
    }


def current_workspace(identity,cutoff='2026-09-28T18:00:00+08:00'):
    return {'input_identity':identity,'semantic_version':'test-v1',
            'plan_context':{'research_cutoff':cutoff}}


def test_next_hk_session_uses_frozen_hk_calendar():
    assert cycle.next_hk_session_date('20260928')=='20260929'
    assert cycle.next_hk_session_date('20260924')=='20260925'
    with pytest.raises(ValueError,match='SOURCE_DATE_NOT_TRADING_DAY'):
        cycle.next_hk_session_date('20260926')


def test_same_authoritative_input_sha_skips_new_refresh_even_when_cutoff_moves(tmp_path,monkeypatch):
    identity='a'*64
    prior=saved_plan(identity)
    monkeypatch.setattr(workspace,'_read_plan',lambda *_:prior)
    monkeypatch.setattr(workspace,'get_workspace',lambda *_,**__:current_workspace(identity,'2026-09-28T22:00:00+08:00'))
    service=SimpleNamespace(store=SimpleNamespace(root=Path(tmp_path)),
        refresh_workspace_plan=lambda *_,**__:pytest.fail('same-input plan was re-published'))
    result=cycle.run_next_hk_session_plan_material_refresh(service,'20260928',
        now=datetime.fromisoformat('2026-09-28T22:00:00+08:00'),config=AFTER_CLOSE)
    assert result['status']=='ALREADY_CURRENT'
    assert result['run_id']==prior['run_id']
    assert result['input_identity']==identity


def test_evening_draft_never_replaces_valid_scheduled_preopen_freeze(tmp_path,monkeypatch):
    prior=saved_plan('b'*64,kind='SCHEDULED_PREOPEN')
    monkeypatch.setattr(workspace,'_read_plan',lambda *_:prior)
    monkeypatch.setattr(workspace,'get_workspace',lambda *_,**__:pytest.fail('freeze must be preserved'))
    service=SimpleNamespace(store=SimpleNamespace(root=Path(tmp_path)),
        refresh_workspace_plan=lambda *_,**__:pytest.fail('freeze must not be overwritten'))
    result=cycle.run_next_hk_session_plan_material_refresh(service,'20260928',
        now=datetime.fromisoformat('2026-09-28T22:00:00+08:00'),config=AFTER_CLOSE)
    assert result['status']=='PRESERVED_SCHEDULED_PREOPEN'
    assert result['run_id']==prior['run_id']


def test_changed_input_persists_next_session_through_original_manual_owner(tmp_path,monkeypatch):
    state={'saved':saved_plan('a'*64)};calls=[]
    monkeypatch.setattr(workspace,'_read_plan',lambda *_:state['saved'])
    monkeypatch.setattr(workspace,'get_workspace',lambda *_,**__:current_workspace('c'*64))
    class Service:
        store=SimpleNamespace(root=Path(tmp_path))
        def refresh_workspace_plan(self,date,**kwargs):
            calls.append((date,kwargs))
            state['saved']=saved_plan('c'*64,run_id='d'*32)
            return {'workspace_plan_attempt':{'state':'PARTIAL','failure_reasons':['INPUT_GAP']}}
    result=cycle.run_next_hk_session_plan_material_refresh(Service(),'20260928',
        now=datetime.fromisoformat('2026-09-28T22:00:00+08:00'),config=AFTER_CLOSE)
    assert calls==[('20260929',{'execution_kind':'MANUAL_REFRESH',
        'now':datetime.fromisoformat('2026-09-28T22:00:00+08:00')})]
    assert result['status']=='PARTIAL'
    assert result['target_trade_date']=='20260929'
    assert result['execution_kind']=='MANUAL_REFRESH'
    assert result['owner_attempt_state']=='PARTIAL'


def test_failed_same_input_is_backed_off_and_retry_budget_is_bounded(tmp_path,monkeypatch):
    identity='a'*64
    monkeypatch.setattr(workspace,'_read_plan',lambda *_:None)
    monkeypatch.setattr(workspace,'get_workspace',lambda *_,**__:current_workspace(identity))
    failed={'state':'FAILED','input_identity':identity,
        'started_at':'2026-09-28T13:00:00+00:00','finished_at':'2026-09-28T13:00:05+00:00'}
    monkeypatch.setattr(cycle,'_attempts_today',lambda *args:[failed])
    service=SimpleNamespace(store=SimpleNamespace(root=Path(tmp_path)),
        refresh_workspace_plan=lambda *_,**__:pytest.fail('retry backoff not honored'))
    result=cycle.run_next_hk_session_plan_material_refresh(service,'20260928',
        now=datetime.fromisoformat('2026-09-28T21:05:00+08:00'),config=AFTER_CLOSE)
    assert result['status']=='RETRY_BACKOFF'
    monkeypatch.setattr(cycle,'_attempts_today',lambda *args:[failed,failed,failed])
    result=cycle.run_next_hk_session_plan_material_refresh(service,'20260928',
        now=datetime.fromisoformat('2026-09-28T22:00:00+08:00'),config=AFTER_CLOSE)
    assert result['status']=='RETRY_LIMIT_REACHED'


def test_plan_only_cycle_never_invokes_announcement_collection(monkeypatch):
    monkeypatch.setattr(cycle,'run_next_hk_session_plan_material_refresh',
        lambda *args,**kwargs:{'status':'ALREADY_CURRENT','target_trade_date':'20260929'})
    monkeypatch.setattr('v4.manager_research.workspace_plan_autorun.run_scheduled_preopen_plan_safe',
        lambda *args,**kwargs:{'status':'NOT_DUE'})
    class Service:
        def refresh_announcements(self,*args,**kwargs):pytest.fail('announcement fetch must stay disabled')
    result=cycle.run_plan_material_refresh_only_cycle(Service(),'20260928',
        now=datetime.fromisoformat('2026-09-28T22:00:00+08:00'),plan_config=AFTER_CLOSE)
    assert result['status']=='SUCCEEDED'
    assert result['announcement_collection']=={
        'status':'DISABLED_PLAN_REFRESH_ONLY','announcement_network_requests':0}


def test_plan_refresh_window_is_bounded_and_not_backfilled():
    assert cycle.run_next_hk_session_plan_material_refresh(None,'20260928',
        now=datetime.fromisoformat('2026-09-28T15:59:00+08:00'),config=AFTER_CLOSE)['status']=='NOT_DUE'
    assert cycle.run_next_hk_session_plan_material_refresh(None,'20260928',
        now=datetime.fromisoformat('2026-09-28T23:00:00+08:00'),config=AFTER_CLOSE)['status']=='EXPIRED_NO_BACKFILL'
