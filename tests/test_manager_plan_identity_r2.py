"""Real pure projection + isolated in-memory store; no historical backfill."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from contextlib import nullcontext
from zoneinfo import ZoneInfo
import pytest
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace_projection import digest
from v4.manager_research.workspace_identity import INPUT_IDENTITY_SCHEMA, identity_component, semantic_digest
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
 bindings={'plan_date':'20260928','selection_date':'20260928','announcement_date':'20260928'}
 return {'target_trade_date':'20260928','input_identity':semantic_digest({'fixture_identity':identity}),
   'input_identity_schema':INPUT_IDENTITY_SCHEMA,
   'input_identity_components':{'fixture_materials':identity_component({'fixture_identity':identity})},
   'semantic_version':'fixture','date_bindings':bindings,'plan_context':{'research_cutoff':cutoff},
   'gaps':[],'stocks':[],'existing_material_coverage':{},'summary':{},'lanes':[]}

def saved(identity='old',cutoff='2026-09-28T08:00:00+08:00',execution_kind='MANUAL_REFRESH'):
 workspace=current(identity,cutoff)
 product={'schema_version':w.PLAN_SCHEMA,'target_trade_date':'20260928','run_id':'a'*32,
  'generated_at':cutoff,'owner':'ManagerResearchJobService.refresh_workspace_plan',
  'input_identity':workspace['input_identity'],'execution_kind':execution_kind,'workspace':workspace,**w.FLAGS}
 product['sha256']=digest(product)
 return product

def saved_owner_attempt(store,product):
 workspace=product['workspace']
 attempt={'schema_version':w.ATTEMPT_SCHEMA,'target_trade_date':'20260928','run_id':product['run_id'],
  'owner':'ManagerResearchJobService.refresh_workspace_plan','state':'SUCCEEDED',
  'execution_kind':product['execution_kind'],'started_at':'2026-09-28T00:00:00+00:00',
  'finished_at':'2026-09-28T00:00:01+00:00','last_success_at':product['generated_at'],
  'input_identity':product['input_identity'],'failure_reasons':[],**w.FLAGS}
 path=store.root/'workspace_plan_runs'/'20260928'/(product['run_id']+'.json')
 store.writes[str(path)]=w.seal_attempt(attempt)
 return path


def test_saved_plan_from_later_cutoff_not_consumed_in_earlier_read(monkeypatch):
 monkeypatch.setattr(w,'_read_plan',lambda *a:saved('same','2026-09-28T09:29:00+08:00'))
 got=w._readback_plan(Store(),'20260928',current('same'))
 assert not got['plan_product']['consumed']
 assert got['plan_product']['status']=='PLAN_AFTER_READ_CUTOFF'


def test_scheduled_existing_plan_is_not_reused_when_inputs_changed(monkeypatch):
 store=Store();svc=SimpleNamespace(store=store)
 read_plan=w._read_plan
 existing=saved('old',execution_kind='SCHEDULED_PREOPEN')
 saved_owner_attempt(store,existing)
 # Before publication expose the old plan; after it, validate the actual write.
 latest_path=str(store.root/'workspace_plans'/'20260928'/'latest.json')
 def read_before_or_after_commit(view,date):
  candidate_reads=getattr(view,'_candidate_reads',None)
  if isinstance(candidate_reads,dict) and view.root/'workspace_plans'/date/'latest.json' in candidate_reads:
   return read_plan(view,date)
  if latest_path in getattr(view,'writes',{}):
   return read_plan(view,date)
  return existing
 monkeypatch.setattr(w,'_read_plan',read_before_or_after_commit)
 monkeypatch.setattr(w,'get_workspace',lambda *a,**kw:current())
 monkeypatch.setattr(w,'_now',lambda:'2026-09-28T01:28:01+00:00')
 result=w.refresh_workspace_plan(svc,'20260928',execution_kind='SCHEDULED_PREOPEN',
  now=datetime.fromisoformat('2026-09-28T09:28:00+08:00'),deadline=datetime.fromisoformat('2026-09-28T09:30:00+08:00'))
 assert result['plan_product']['status']=='CURRENT'
 assert result['plan_product']['consumed'] is True
 assert result['workspace_plan_attempt']['input_identity']==current()['input_identity']
 assert any('/workspace_plans/' in path for path in store.writes)


def test_scheduled_same_inputs_do_not_double_publish(monkeypatch):
 store=Store();svc=SimpleNamespace(store=store)
 product=saved('same',execution_kind='SCHEDULED_PREOPEN')
 attempt_path=saved_owner_attempt(store,product)
 before=deepcopy(store.writes)
 monkeypatch.setattr(w,'_read_plan',lambda *a:product)
 monkeypatch.setattr(w,'get_workspace',lambda *a,**kw:current('same'))
 monkeypatch.setattr(w,'_now',lambda:'2026-09-28T01:28:01+00:00')
 result=w.refresh_workspace_plan(svc,'20260928',execution_kind='SCHEDULED_PREOPEN',
  now=datetime.fromisoformat('2026-09-28T09:28:00+08:00'),deadline=datetime.fromisoformat('2026-09-28T09:30:00+08:00'))
 assert result['plan_product']['status']=='ALREADY_MATERIALIZED'
 assert result['workspace_plan_attempt']['run_id']=='a'*32
 assert str(attempt_path) in store.writes
 assert store.writes==before


def test_scheduled_current_target_owner_uses_shared_calendar_yesterday_default(monkeypatch):
 from v4.manager_research import workspace_daily_channels as daily
 target='20261012'
 now=datetime(2026,10,12,9,28,tzinfo=ZoneInfo('Asia/Hong_Kong'))
 deadline=datetime(2026,10,12,9,30,tzinfo=ZoneInfo('Asia/Hong_Kong'))
 store=Store();svc=SimpleNamespace(store=store)
 monkeypatch.setattr(w,'plan_context',lambda date,now=None:{
  'plan_trade_date':date,'research_cutoff':now.isoformat()})
 def compute(service,date,*,context,**kwargs):
  value=current('phase7-current-target',context['research_cutoff'])
  value['target_trade_date']=date
  value['plan_context']=dict(context)
  value.update(w.FLAGS)
  return value
 monkeypatch.setattr(w,'_compute_workspace',compute)
 monkeypatch.setattr(daily,'build_daily_channels',lambda value:{'status':'FIXTURE'})
 monkeypatch.setattr(w,'_now',lambda:'2026-10-12T01:28:01+00:00')
 original_get_workspace=w.get_workspace
 owner_reads=[]
 def capture_get_workspace(service,date,**kwargs):
  value=original_get_workspace(service,date,**kwargs)
  owner_reads.append((date,dict(kwargs),value['date_bindings']))
  return value
 monkeypatch.setattr(w,'get_workspace',capture_get_workspace)

 result=w.refresh_workspace_plan(svc,target,execution_kind='SCHEDULED_PREOPEN',now=now,deadline=deadline)

 assert len(owner_reads)==1
 date,kwargs,bindings=owner_reads[0]
 assert date==target
 assert 'announcement_date' not in kwargs
 assert bindings=={'plan_date':target,'selection_date':target,'announcement_date':'20261011'}
 assert result['plan_product']['execution_kind']=='SCHEDULED_PREOPEN'
 assert result['date_bindings']==bindings
 assert result['plan_context']['research_cutoff']==now.isoformat()
 assert result['RESEARCH_ONLY'] is True
 assert result['production_allowed'] is False
 assert result['buy_gate_updated'] is False
 assert result['orders_sent'] is False


def test_workspace_explicit_publication_date_overrides_shared_default(monkeypatch):
 from v4.manager_research import announcement_analysis, workspace_daily_channels as daily
 target='20261012'
 now=datetime(2026,10,12,8,53,tzinfo=ZoneInfo('Asia/Hong_Kong'))
 monkeypatch.setattr(announcement_analysis,'default_announcement_publication_date',
  lambda *a,**kw:pytest.fail('explicit publication must not use the default resolver'))
 monkeypatch.setattr(w,'plan_context',lambda date,now=None:{
  'plan_trade_date':date,'research_cutoff':now.isoformat()})
 def compute(service,date,*,context,**kwargs):
  value=current('explicit-publication',context['research_cutoff'])
  value['target_trade_date']=date
  value['plan_context']=dict(context)
  value.update(w.FLAGS)
  return value
 monkeypatch.setattr(w,'_compute_workspace',compute)
 monkeypatch.setattr(daily,'build_daily_channels',lambda value:{'status':'FIXTURE'})
 result=w.get_workspace(SimpleNamespace(),target,include_saved=False,view='dynamic',now=now,
  announcement_date='2026-10-09')
 assert result['date_bindings']=={
  'plan_date':target,'selection_date':target,'announcement_date':'20261009'}
 assert result['plan_context']['announcement_publication_date']=='2026-10-09'


def test_autorun_cannot_shortcut_stale_plan_by_timestamp_alone(monkeypatch):
 monkeypatch.setattr(auto,'preopen_window',lambda *a,**kw:(datetime.fromisoformat('2026-09-28T09:27:00+08:00'),datetime.fromisoformat('2026-09-28T09:30:00+08:00')))
 calls=[]
 identity='c'*64;run_id='d'*32;generated='2026-09-28T09:28:01+08:00'
 product={'status':'CURRENT','consumed':True,'original_owner':auto.PLAN_OWNER,
  'run_id':run_id,'input_identity':identity,'generated_at':generated,
  'execution_kind':'SCHEDULED_PREOPEN'}
 product['sha256']=digest(product)
 attempt=w.seal_attempt({'schema_version':w.ATTEMPT_SCHEMA,'target_trade_date':'20260928',
  'run_id':run_id,'owner':auto.PLAN_OWNER,'state':'SUCCEEDED',
  'execution_kind':'SCHEDULED_PREOPEN','started_at':'2026-09-28T09:28:00+08:00',
  'finished_at':'2026-09-28T09:28:02+08:00','last_success_at':generated,
  'input_identity':identity,'failure_reasons':[],**w.FLAGS})
 svc=SimpleNamespace(get_workspace_plan=lambda date:saved(),
     refresh_workspace_plan=lambda date,**kw:(calls.append(kw) or {
       'target_trade_date':date,'input_identity':identity,'plan_product':product,
       'workspace_plan_attempt':attempt,'plan_context':{'research_cutoff':generated}}))
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
