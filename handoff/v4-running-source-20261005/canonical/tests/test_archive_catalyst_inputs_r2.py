"""Synthetic original-reader callbacks; no live archive, native store or provider."""
import importlib.util
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime
import pytest
from v4.manager_research.existing_materials import project_archive
from v4.manager_research.workspace_projection import digest
from v4.manager_research.workspace_discovery import project_material_discovery
from tests.test_us_relation_pipeline_r2 import MASTER,IDENTITY,CTX,REF

CTX={**CTX,'source_dates':['20260925']}

def module():
 assert importlib.util.find_spec('v4.manager_research.archive_catalyst_inputs'), 'archive-source owner integration is absent'
 from v4.manager_research import archive_catalyst_inputs
 return archive_catalyst_inputs

def row(id='ok',**kw):
 return {'article_id':id,'source_title':'星海科技记录','body':'星海科技发布光伏组件业务订单增长公告。',
  'published_at':'2026-09-25T12:00:00+08:00','retrieved_at':'2026-09-25T12:01:00+08:00',
  'available_at':'2026-09-25T12:02:00+08:00',**kw}

def setup(monkeypatch,articles):
 m=module();state={'payload':{'archive_date':'20260925','articles':articles,'source_generated_at':'2026-09-25T13:00:00+08:00'}}
 def original(source,day,slot):
  if slot:return [],[],None
  payload=state['payload'];binding={**REF,'payload_sha256':digest(payload)}
  rows,gaps=project_archive(payload,binding,day)
  return rows,gaps,binding
 def discovery(rows,context,root):
  assert root=='native-root'
  cards=project_material_discovery(rows,MASTER,IDENTITY,context)
  return {'status':'READY','cards':cards,'gaps':[],'identity_witness':deepcopy(IDENTITY),'rejected_relations':[]}
 monkeypatch.setattr(m,'_read_archive',original);monkeypatch.setattr(m,'read_material_discovery',discovery)
 source=SimpleNamespace(hourly_store=SimpleNamespace(list_slots=lambda *a,**kw:[]))
 return m,source,state


def test_valid_archive_material_makes_independent_cards_even_if_one_clock_is_bad(monkeypatch):
 m,src,state=setup(monkeypatch,[row(),row('bad',available_at=None,collected_at='2026-09-25T12:02:00+08:00')])
 result=m.project_archive_catalysts(src,CTX,'native-root')
 assert len(result['cards'])==1
 assert result['coverage']['rejected_material_count']==1
 assert result['rejected_materials'][0]['reason']=='ARCHIVE_EXPLICIT_ACQUISITION_TIME_REQUIRED'
 assert result['cards'][0]['claim_type']=='RESEARCH_OPINION'
 assert result['cards'][0]['captured_at_target'] is False
 assert result['cards'][0]['orders_sent'] is False

@pytest.mark.parametrize('field,value', [('published_at',None),('available_at',None),('retrieved_at',None),
 ('available_at','bad'),('available_at','2026-09-28T08:00:01+08:00'),('first_seen_at','2026-09-28T09:00:00+08:00'),
 ('first_seen_at','bad')])
def test_bad_clock_is_never_filled_from_other_fields(monkeypatch,field,value):
 m,src,state=setup(monkeypatch,[row(**{field:value})])
 result=m.project_archive_catalysts(src,CTX,'native-root')
 assert not result['cards'];assert result['rejected_materials']


def test_frozen_replay_rechecks_original_binding_not_self_hash(monkeypatch):
 m,src,state=setup(monkeypatch,[row()]);result=m.project_archive_catalysts(src,CTX,'native-root')
 replay=m.project_archive_catalysts(src,CTX,'native-root',frozen=result['snapshot'])
 assert replay==result
 state['payload']['articles'][0]['body']='星海科技发布光伏组件业务订单下降公告。'
 with pytest.raises(ValueError,match='ARCHIVE_CATALYST_SOURCE_CHANGED'):
  m.project_archive_catalysts(src,CTX,'native-root',frozen=result['snapshot'])


def test_new_archive_slots_do_not_rewrite_committed_input_set(monkeypatch):
 m,src,state=setup(monkeypatch,[row()]);result=m.project_archive_catalysts(src,CTX,'native-root')
 src.hourly_store.list_slots=lambda *a,**kw:pytest.fail('must replay only sealed slots')
 assert m.project_archive_catalysts(src,CTX,'native-root',frozen=result['snapshot'])==result


def test_missing_archive_source_is_an_input_gap_not_empty_success(monkeypatch):
 m=module();r=m.project_archive_catalysts(None,CTX,'native-root')
 assert not r['cards']
 assert 'RESEARCH_ARCHIVE_READER_NOT_BOUND' in r['gaps']


def test_frozen_identity_drift_is_not_accepted(monkeypatch):
 m,src,state=setup(monkeypatch,[row()]);r=m.project_archive_catalysts(src,CTX,'native-root')
 previous=m.read_material_discovery
 def drift(*args):
  value=previous(*args);value['identity_witness']['artifact_sha256']='8'*64;return value
 monkeypatch.setattr(m,'read_material_discovery',drift)
 with pytest.raises(ValueError,match='ARCHIVE_CATALYST_IDENTITY_CHANGED'):
  m.project_archive_catalysts(src,CTX,'native-root',frozen=r['snapshot'])


def test_independent_archive_product_coverage_is_visible_in_material_lane():
 from v4.manager_research.workspace_projection import build_workspace
 value=build_workspace('20260928',catalyst={'target_trade_date':'20260928','status':'READY','cards':[],
  'archive_projection':{'coverage':{'read_material_count':3,'clock_admitted_material_count':2,'native_issuer_card_count':1,'rejected_material_count':1}}},plan_context=CTX)
 lane=next(l for l in value['lanes'] if l['lane']=='CATALYST')
 assert lane['input_coverage']['archive_materials']['clock_admitted_material_count']==2
