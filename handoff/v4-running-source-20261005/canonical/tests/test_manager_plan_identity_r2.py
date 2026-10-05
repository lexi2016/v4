"""Real pure projection + isolated in-memory store; no historical backfill."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from contextlib import nullcontext
import pytest
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace_projection import digest
from v4.manager_research import workspace as w
from v4.manager_research import workspace_plan_autorun as auto
from tests.test_us_relation_pipeline_r2 import CTX,cards,material,us


def out(ctx,rows=None):
 return build_research_attention('20260928',context=ctx,market_screen={'cards':[],'input_identity':'a'*64},
  stocks=[],material_cards=rows or [],themes=[],announcement_observation={'status':'NOT_RUN'},us_market=us())

def test_read_clock_alone_does_not_change_material_input_identity():
 a=out(CTX);b=out({**CTX,'research_cutoff':'2026-09-28T08:01:00+08:00'})
 assert a['cards']==b['cards']
 assert a['input_identity']==b['input_identity']
 assert a['research_cutoff']!=b['research_cutoff']


def test_moving_fallback_boundary_only_changes_identity_when_admission_changes():
 ctx={**CTX,'focus_window_start':None}
 assert out(ctx)['input_identity']==out({**ctx,'research_cutoff':'2026-09-28T08:01:00+08:00'})['input_identity']


def test_expiration_and_new_source_changes_still_invalidate():
 rows=cards(material('星海科技发布光伏组件业务订单增长公告。'))
 a=out(CTX,rows)
 b=out({**CTX,'research_cutoff':'2026-10-05T08:00:00+08:00'},rows)
 assert a['input_identity']!=b['input_identity']
 rows2=deepcopy(rows);rows2[0]['source_refs'][0]['payload_sha256']='9'*64
 assert a['input_identity']!=out(CTX,rows2)['input_identity']

class Store:
 def __init__(self):
  from pathlib import Path
  self.root=Path('/NOT_LIVE/test');self.writes={}
 def _read(self,path):return self.writes.get(str(path))
 def _write_atomic(self,path,value):self.writes[str(path)]=deepcopy(value)
 def _transaction(self,*a):return nullcontext()


def current(identity='new',cutoff='2026-09-28T09:28:00+08:00'):
 return {'input_identity':identity,'semantic_version':'fixture','plan_context':{'research_cutoff':cutoff},
   'gaps':[],'stocks':[],'existing_material_coverage':{},'summary':{},'lanes':[]}

def saved(identity='old',cutoff='2026-09-28T08:00:00+08:00'):
 return {'input_identity':identity,'workspace':current(identity,cutoff),'generated_at':cutoff,
  'run_id':'a'*32,'sha256':'b'*64,'execution_kind':'MANUAL_REFRESH'}


def test_saved_plan_from_later_cutoff_not_consumed_in_earlier_read(monkeypatch):
 monkeypatch.setattr(w,'_read_plan',lambda *a:saved('same','2026-09-28T09:29:00+08:00'))
 got=w._readback_plan(Store(),'20260928',current('same'))
 assert not got['plan_product']['consumed']
 assert got['plan_product']['status']=='PLAN_AFTER_READ_CUTOFF'


def test_scheduled_existing_plan_is_not_reused_when_inputs_changed(monkeypatch):
 store=Store();svc=SimpleNamespace(store=store)
 read_plan=w._read_plan
 # Before publication expose the old plan; after it, validate the actual write.
 monkeypatch.setattr(w,'_read_plan',lambda store,date:read_plan(store,date)
     if str(store.root/'workspace_plans'/date/'latest.json') in store.writes else saved())
 monkeypatch.setattr(w,'get_workspace',lambda *a,**kw:{'target_trade_date':'20260928',**current()})
 monkeypatch.setattr(w,'_now',lambda:'2026-09-28T01:28:01+00:00')
 result=w.refresh_workspace_plan(svc,'20260928',execution_kind='SCHEDULED_PREOPEN',
  now=datetime.fromisoformat('2026-09-28T09:28:00+08:00'),deadline=datetime.fromisoformat('2026-09-28T09:30:00+08:00'))
 assert result['plan_product']['status']=='CURRENT'
 assert result['plan_product']['consumed'] is True
 assert result['workspace_plan_attempt']['input_identity']=='new'
 assert any('/workspace_plans/' in path for path in store.writes)


def test_scheduled_same_inputs_do_not_double_publish(monkeypatch):
 store=Store();svc=SimpleNamespace(store=store)
 monkeypatch.setattr(w,'_read_plan',lambda *a:saved('same'))
 monkeypatch.setattr(w,'get_workspace',lambda *a,**kw:current('same'))
 result=w.refresh_workspace_plan(svc,'20260928',execution_kind='SCHEDULED_PREOPEN',
  now=datetime.fromisoformat('2026-09-28T09:28:00+08:00'),deadline=datetime.fromisoformat('2026-09-28T09:30:00+08:00'))
 assert result['plan_product']['status']=='ALREADY_MATERIALIZED'
 assert not store.writes


def test_autorun_cannot_shortcut_stale_plan_by_timestamp_alone(monkeypatch):
 monkeypatch.setattr(auto,'preopen_window',lambda *a,**kw:(datetime.fromisoformat('2026-09-28T09:27:00+08:00'),datetime.fromisoformat('2026-09-28T09:30:00+08:00')))
 calls=[]
 svc=SimpleNamespace(get_workspace_plan=lambda date:saved(),
     refresh_workspace_plan=lambda date,**kw:(calls.append(kw) or {
       'plan_product':{'status':'CURRENT','generated_at':'2026-09-28T09:28:01+08:00','run_id':'r'},'plan_context':{}}))
 result=auto.run_scheduled_preopen_plan(svc,'20260928',now=datetime.fromisoformat('2026-09-28T09:28:00+08:00'))
 assert calls
 assert result['status']=='MATERIALIZED'


def test_late_call_never_creates_preopen_plan(monkeypatch):
 monkeypatch.setattr(auto,'preopen_window',lambda *a,**kw:(datetime.fromisoformat('2026-09-28T09:27:00+08:00'),datetime.fromisoformat('2026-09-28T09:30:00+08:00')))
 svc=SimpleNamespace(refresh_workspace_plan=lambda *a,**kw:pytest.fail('late refresh'))
 assert auto.run_scheduled_preopen_plan(svc,'20260928',now=datetime.fromisoformat('2026-09-28T09:30:00+08:00'))['status']=='EXPIRED_NO_BACKFILL'


def test_read_contract_tracks_new_stage_calendar_dependencies(tmp_path,monkeypatch):
 from v4.manager_research import workspace_read_control as control
 package=tmp_path/'v4/manager_research';package.mkdir(parents=True)
 (package/'workspace_read_control.py').write_text('#fixture')
 stage=tmp_path/'stage_center';stage.mkdir();p=stage/'scheduler.py';p.write_text('before')
 monkeypatch.setattr(control,'__file__',str(package/'workspace_read_control.py'))
 a=control.contract_identity();p.write_text('after')
 assert a!=control.contract_identity()
