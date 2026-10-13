from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,sys
import pytest
HERE=Path(__file__).resolve().parent

def module():
 spec=importlib.util.spec_from_file_location('v10_candidate_preparation',HERE/'prepare_us_tdx_v10.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_exact_owner_allowlist_rejects_other_upstreams_and_mirror(monkeypatch):
 m=module();import operate_v7_cutover as operator
 original=operator.allowed_source
 monkeypatch.setattr(operator,'allowed_source',original)
 m.install_exact_owner_guard()
 assert operator.allowed_source(m.OWNER)
 for rel in ['upstreams/v3_shared_data/shared_data/paths.py',m.MIRROR,'upstreams/v3_shared_data/shared_data/hk_daily_supplement.py.bak','upstreams/v3_shared_data/shared_data/../hk_daily_supplement.py','/upstreams/v3_shared_data/shared_data/hk_daily_supplement.py']:
  assert not operator.allowed_source(rel)
 assert operator.allowed_source('v4/manager_workbench/inputs/native.py')


def test_exact_five_sources_and_source_receipt_drift_reject(tmp_path):
 m=module();snapshot=json.loads((HERE/'panel-priority-implementation-r1.json').read_bytes())
 p=tmp_path/'current-source-snapshot.json';p.write_text(json.dumps(snapshot));items=m.sources(p,m.sha(p.read_bytes()))
 assert {x['path'] for x in items}==m.BUSINESS
 assert next(x for x in items if x['path']==m.OWNER)['before_sha256']=='5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c'
 with pytest.raises(ValueError,match='RECEIPT_DRIFT'):m.sources(p,'0'*64)
 snapshot['files']['v4/manager_workbench/inputs/native.py']['after_sha256']='0'*64
 p.write_text(json.dumps(snapshot))
 with pytest.raises(ValueError,match='REVIEWED_SOURCE_DRIFT'):m.sources(p,m.sha(p.read_bytes()))
 p.write_text(json.dumps({'scope_files':[]}))
 with pytest.raises(ValueError,match='PANEL_FIRST_SOURCE_RECEIPT_REQUIRED'):m.sources(p,m.sha(p.read_bytes()))


def test_prepare_config_only_exact_bindings_keeps_formal_state_and_pause(tmp_path,monkeypatch):
 m=module();from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner
 original=importlib.util.spec_from_file_location
 class Loader:
  def create_module(self,spec):return None
  def exec_module(self,module):module.install_runtime=lambda:None
 def spec(name,path,*a,**kw):
  if name=='v10_accepted_calendar':return importlib.util.spec_from_loader(name,Loader())
  return original(name,path,*a,**kw)
 monkeypatch.setattr(importlib.util,'spec_from_file_location',spec)
 monkeypatch.setattr(owner,'read_tdxpy_panel_identity',lambda *a:dict(panel_sha256='1'*64,panel_manifest_sha256='2'*64))
 monkeypatch.setattr(owner,'_read_master_identity',lambda *a:(dict(artifact_sha256='3'*64,manifest_sha256='4'*64),['HK.'+str(i).zfill(5) for i in range(1,693)]))
 manifest=dict(capture_scope='PANEL_GAPS',code_count=2,master_code_count=692,gap_codes=['HK.00001','HK.00002'],panel_valid_count=690,projection_price_date='20261012',panel_gap_plan_sha256='a'*64)
 records=[dict(code='HK.00001'),dict(code='HK.00002')]
 monkeypatch.setattr(owner,'read_tdxpy_window_supplement',lambda *a,**kw:(manifest,records))
 raw=(HERE/'.tmp/v9-us-futu-r2/before/0').read_bytes()
 old=json.loads(raw);pin=tmp_path/'pin.json';pin.write_text(json.dumps(dict(symbol='FULL_SCOPE_TEST_NO_NETWORK')))
 new,proof=m.prepare_config(raw,pin,m.sha(pin.read_bytes()),'2026-10-13T21:00:00+08:00')
 assert new['state_root']==old['state_root'] and new['scheduled_lanes']==['US_MAPPING','OVERSOLD'] and new['capture_enabled'] is False
 assert new['source_bindings']['hk_panel']['20261012']['tdxpy_history']==json.loads(pin.read_bytes())
 changed=json.loads(json.dumps(new));changed['source_bindings']['hk_panel']['20261012'].pop('tdxpy_history');changed['source_bindings']['hk_panel']['20261012'].pop('futu_history')
 if not changed['source_bindings']['hk_panel']['20261012']:changed['source_bindings']['hk_panel'].pop('20261012')
 if not changed['source_bindings']['hk_panel']:changed['source_bindings'].pop('hk_panel')
 assert changed==old
 for key,value in [('capture_scope','FULL_MASTER'),('capture_scope','PANEL_GAP_CANARY'),('master_code_count',2),('panel_valid_count',692),('projection_price_date','20261013'),('gap_codes',['HK.00001'])]:
  previous=manifest[key];manifest[key]=value
  with pytest.raises(ValueError,match='EXACT_PANEL_GAPS'):m.prepare_config(raw,pin,m.sha(pin.read_bytes()),'2026-10-13T21:00:00+08:00')
  manifest[key]=previous
 assert new.get('dynamic_source_bindings')==old.get('dynamic_source_bindings')
 assert all(k not in new['source_bindings']['hk_panel']['20261012'] for k in ['actual_panel_max_date','projection_price_date','panel_relative','manifest_relative'])


def test_operate_delegates_unchanged_reviewed_v8_wrapper(monkeypatch):
 m=module();import operate_scheduled_lanes_v8 as op
 called=[];monkeypatch.setattr(op,'main',lambda:called.append(list(sys.argv)))
 monkeypatch.setattr(op.operator,'allowed_source',op.operator.allowed_source)
 launch=op.operator.launch
 monkeypatch.setattr(sys,'argv',['v10','operate','--plan','/not/executed/plan','--plan-sha256','1'*64,'--operation','rollback'])
 m.main()
 assert called==[[str(HERE/'operate_scheduled_lanes_v8.py'),'--plan','/not/executed/plan','--plan-sha256','1'*64,'--mode','rollback']]
 assert op.operator.launch is launch
