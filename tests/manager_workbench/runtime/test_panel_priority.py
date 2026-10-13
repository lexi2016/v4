from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import json
import pandas as pd
import pytest
from test_native_pipeline import fixture,write
from test_integration import context
from test_tdxpy_owner_window import setup,API,CAL
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.source_bindings import hk_panel
from v4.manager_workbench.inputs.validation import raw_sha
from v4.manager_workbench.contracts import Lane,Phase
from v4.manager_workbench.engines.oversold import run_oversold,window_metrics
from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner

@pytest.fixture(autouse=True)
def accepted_calendar(monkeypatch):
 from contracts import trading_calendar as tc
 from v4.manager_workbench.inputs import native
 original=tc.load_market_calendar
 monkeypatch.setattr(tc,'CALENDAR_PATH',CAL);monkeypatch.setattr(tc,'load_market_calendar',lambda:original(CAL))
 monkeypatch.setattr(native,'CALENDAR_PATH',CAL);monkeypatch.setattr(native,'load_market_calendar',lambda:original(CAL))

def inputs(tmp_path,count=2):
 cfg=fixture(tmp_path,count);a=NativeAdapters(cfg)
 c=a.prepare_context(context(cutoff='2026-10-13T18:00:00+08:00'))
 return cfg,a,c

def replace_panel(cfg,transform):
 pin=cfg.source_bindings['hk_panel']['20261012'];path=cfg.shared_root/'panel.parquet'
 frame=transform(pd.read_parquet(path));frame.to_parquet(path,index=False)
 manifest=json.loads((cfg.shared_root/pin['manifest_relative']).read_bytes());manifest['panel_sha256']=raw_sha(path.read_bytes())
 pin['manifest_sha256']=write(cfg.shared_root,pin['manifest_relative'],manifest)

@pytest.mark.parametrize('selected',[True,False])
def test_effective_panel_wins_even_if_supplement_has_opposite_result(tmp_path,monkeypatch,selected):
 cfg,a,c=inputs(tmp_path)
 if not selected:replace_panel(cfg,lambda df:df.assign(close=99,trade=100))
 p=cfg.source_bindings['hk_panel']['20261012'];p['futu_history']=[dict(symbol='HK.00001')];p['tdxpy_history']={'unused':'invalid'}
 def forbidden(*args,**kwargs):raise AssertionError('effective panel must not read supplement')
 monkeypatch.setattr(a,'_futu_history',forbidden);monkeypatch.setattr(a,'_tdxpy_history',forbidden)
 b=a.load(Lane.OVERSOLD,c);out=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert len(out['rows'])==2
 assert {r['decision'] for r in out['rows']}==({'SELECTED'} if selected else {'NOT_SELECTED'})
 assert all(r['window_origin']=='PANEL' and not r['panel_window_gaps'] for r in b.records)


def test_missing_panel_uses_whole_verified_window_only_for_gap_and_keeps_692(tmp_path,monkeypatch):
 from test_futu_same_response import prepared
 cfg,a,c,pin=prepared(tmp_path,count=692)
 # Real Futu HK00001 is negative. All other complete panel windows have proven
 # absolute units, while only HK00001 genuinely lacks the three dates.
 cfg.source_bindings['hk_panel']['20261012'].update(currency='HKD',price_basis='RAW',volume_unit='SHARES')
 replace_panel(cfg,lambda df:df[~((df.code_norm=='HK.00001') & df.trade_date_compact.isin(['20261005','20261006','20261007']))])
 b=a.load(Lane.OVERSOLD,c);out=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert len(out['rows'])==692 and out['coverage']['scope_count']==692
 assert out['rows'][0]['decision']=='NOT_SELECTED'
 assert b.records[0]['window_origin']=='PANEL_OWNER_SUPPLEMENT' and b.records[0]['owner']=='FUTU'
 assert b.records[1]['window_origin']=='PANEL' and out['rows'][1]['decision']=='SELECTED'
 assert len(b.records[0]['high_history60'])==60 and len(b.records[0]['volume_history5'])==5


def test_mixed_panel_not_proven_and_legacy_six_day_not_spliced(tmp_path):
 cfg,a,c=inputs(tmp_path,count=1)
 replace_panel(cfg,lambda df:df.assign(source=['OLD' if i else 'REPAIR' for i in range(len(df))]))
 cfg.source_bindings['hk_panel']['20261012']['supplement']={'manifest_relative':'never-read-missing'}
 b=a.load(Lane.OVERSOLD,c);r=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))['rows'][0]
 assert r['decision']=='UNASSESSED' and r['reason']=='PANEL_MIXED_SOURCE_COMPARISON_UNVERIFIED'
 assert 'LEGACY_SIX_DAY_SUPPLEMENT_COMPARISON_UNVERIFIED' in b.gaps


def latest13(cfg):
 pin=cfg.source_bindings['hk_panel']['20261012']
 replace_panel(cfg,lambda df:pd.concat([df,pd.DataFrame([dict(code_norm='HK.00001',trade_date_compact='20261013',close=1,high=100000,trade=999999)])],ignore_index=True))
 old=json.loads((cfg.shared_root/pin['manifest_relative']).read_bytes())
 rel='assets/hk_0_2/panels/20261013-fixture/manifest.json'
 old.update(panel_max_date='20261013',panel_relative='panels/20261013-fixture/panel.parquet',manifest_prepared_at='2026-10-13T17:20:00+08:00')
 path=cfg.shared_root/'assets/hk_0_2'/old['panel_relative'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((cfg.shared_root/'panel.parquet').read_bytes())
 sha=write(cfg.shared_root,rel,old)
 write(cfg.shared_root,'assets/hk_0_2/panel_latest.json',{'manifest_relative':'panels/20261013-fixture/manifest.json'})
 return rel,sha


def test_retrospective_projects_latest13_preserves_actual_identity_excludes13(tmp_path):
 cfg,a,c=inputs(tmp_path,count=1);rel,sha=latest13(cfg);c.phase=Phase.RETROSPECTIVE
 pin=hk_panel(cfg,c);assert pin['manifest_relative']==rel and pin['manifest_sha256']==sha
 pin.update(currency='HKD',price_basis='RAW',volume_unit='SHARES')
 c.scope_refs['owner_bindings']={'hk_panel':pin}
 b=a.load(Lane.OVERSOLD,c);r=b.records[0]
 assert r['previous_bar']['session']=='20261012' and r['previous_bar']['close']=='80.0'
 assert max(x['session'] for x in r['high_history60'])<'20261012'
 ref=next(ref for ref in b.evidence_refs if ref.role=='HK_DAILY_PANEL')
 assert ref.source_date=='20261013' and ref.available_at=='2026-10-13T17:20:00+08:00'
 assert r['panel_origin']['actual_panel_max_date']=='20261013' and r['panel_origin']['projection_price_date']=='20261012'
 assert window_metrics(c.model_dump(mode='json'),r)['volume_ratio']=='1.5'


@pytest.mark.parametrize('phase,cutoff',[('PREOPEN','2026-10-13T18:00:00+08:00'),('RETROSPECTIVE','2026-10-13T17:19:59+08:00')])
def test_newer_panel_not_a_preopen_or_earlier_cutoff_escape(tmp_path,phase,cutoff):
 cfg,a,c=inputs(tmp_path,count=1);rel,sha=latest13(cfg);c.phase=Phase(phase);c.cutoff=cutoff
 c.scope_refs['owner_bindings']={'hk_panel':dict(manifest_relative=rel,manifest_sha256=sha,available_at='2026-10-13T17:20:00+08:00')}
 with pytest.raises(ValueError,match='HK_PANEL'):a.oversold(c)


def gap_setup(tmp_path,monkeypatch,count=3,complete=False):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,count)
 panel.update(panel_max_date='20261012')
 if not complete:replace_panel(cfg,lambda df:df[~((df.code_norm=='HK.00001') & df.trade_date_compact.isin(['20261005','20261006','20261007']))])
 # Setup's parent projection refers to the actual updated raw panel.
 pp=cfg.source_bindings['hk_panel']['20261012'];pm=json.loads((cfg.shared_root/pp['manifest_relative']).read_bytes())
 panel.update(panel_sha256=pm['panel_sha256'],panel_manifest_sha256=pp['manifest_sha256'])
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T17:00:00+08:00'));c.phase=Phase.RETROSPECTIVE
 plan=a.panel_gap_plan(c)
 return cfg,codes,api,panel,master,plan


def test_machine_gap_subset_one_not_full_master_and_valid_zero_requests(tmp_path,monkeypatch):
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path,monkeypatch)
 assert plan['gap_codes']==['HK.00001'] and plan['panel_valid_count']==2
 assert plan['records'][0]['missing_sessions']==['20261005','20261006','20261007']
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,
     panel_gap_plan=plan,output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
 manifest,records=owner.read_tdxpy_window_supplement(pin,target_date='20261012',cutoff='2026-10-13T19:00:00+08:00',
     expected_panel_sha=panel['panel_sha256'],expected_master_sha=master['artifact_sha256'],expected_codes=codes)
 assert len(api.calls)==1 and manifest['capture_scope']=='PANEL_GAPS' and manifest['master_code_count']==3
 assert [r['code'] for r in records]==['HK.00001'] and len(records[0]['bars'])==61
 cfg.source_bindings['hk_panel']['20261012']['tdxpy_history']=pin
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T19:00:00+08:00'))
 b=a.load(Lane.OVERSOLD,c)
 assert b.records[0]['window_origin']=='PANEL_OWNER_SUPPLEMENT'
 assert b.records[1]['window_origin']=='PANEL'
 assert [r['decision'] for r in run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))['rows']]==['NOT_SELECTED','SELECTED','SELECTED']


def test_zero_gaps_no_connector_no_owner_writes(tmp_path,monkeypatch):
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path,monkeypatch,complete=True)
 assert plan['gap_codes']==[]
 def forbidden(endpoint):raise AssertionError('zero gaps must have zero requests')
 output=tmp_path/'never-created'
 result=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=forbidden,
     panel_gap_plan=plan,output_root=output)
 assert result['status']=='NO_PANEL_GAPS' and result['network_bar_requests']==0 and not output.exists()


@pytest.mark.parametrize('change',['non_gap','parent','scope','cutoff','calendar','projection_phase'])
def test_gap_parent_and_machine_scope_fail_closed(tmp_path,monkeypatch,change):
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path,monkeypatch)
 subset=None
 if change=='non_gap':subset=['HK.00002']
 elif change=='parent':plan['panel_identity']=dict(plan['panel_identity'],panel_sha256='0'*64)
 elif change=='scope':plan['records'].pop()
 elif change=='cutoff':plan['cutoff']='2026-10-13T21:00:00+08:00'
 elif change=='calendar':plan['calendar_sha256']='0'*64
 else:
  panel['panel_max_date']='20261013';plan['phase']='PREOPEN'
 with pytest.raises(ValueError,match='TDXPY'):
  owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,
       panel_gap_plan=plan,canary_codes=subset,output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
 assert api.calls==[]


def test_gap_owner_retains_actual_parent13_and_projection12(tmp_path,monkeypatch):
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path,monkeypatch)
 panel.update(panel_max_date='20261013',manifest_prepared_at='2026-10-13T17:20:00+08:00')
 plan['cutoff']='2026-10-13T18:00:00+08:00'
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,
     panel_gap_plan=plan,canary_codes=['HK.00001'],output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,11,tzinfo=timezone.utc))
 manifest,records=owner.read_tdxpy_window_supplement(pin,target_date='20261012',cutoff='2026-10-13T19:01:00+08:00',
     expected_panel_sha=panel['panel_sha256'],expected_master_sha=master['artifact_sha256'],expected_codes=codes)
 assert manifest['capture_scope']=='PANEL_GAP_CANARY'
 assert manifest['panel_identity']['panel_max_date']=='20261013' and manifest['projection_price_date']=='20261012'
 assert len(records[0]['bars'])==61 and records[0]['bars'][-1]['trade_date']=='20261012'
 assert '20261013' in records[0]['outside_requested_sessions']


def test_invalid_one_panel_value_keeps_other_valid_rows(tmp_path):
 cfg,a,c=inputs(tmp_path)
 # Parquet has a homogeneous numeric type; NaN is the real malformed shape.
 replace_panel(cfg,lambda df:df.assign(close=df.close.where(~((df.code_norm=='HK.00001') & (df.trade_date_compact=='20261012')),float('nan'))))
 b=a.load(Lane.OVERSOLD,c);out=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert out['rows'][0]['decision']=='UNASSESSED' and out['rows'][1]['decision']=='SELECTED'
 assert b.records[0]['panel_window_gaps'] and b.records[1]['panel_window_gaps']==[]


def test_prepare_and_capture_operator_zero_gap_no_sdk_or_output(tmp_path,monkeypatch):
 import importlib.util
 from types import SimpleNamespace
 here=Path(__file__).resolve().parents[3]/'docs/handoff/manager-workbench-implementation-20261013'
 spec=importlib.util.spec_from_file_location('panel_gap_collect',here/'collect_tdxpy_61.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 monkeypatch.setattr(m,'HERE',tmp_path);(tmp_path/'.tmp').mkdir()
 (tmp_path/'fixtures').mkdir()
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path/'fixtures',monkeypatch,complete=True)
 path=tmp_path/'plan.json';path.write_text(json.dumps(plan))
 def forbidden(*args):raise AssertionError('zero gaps must not load sdk')
 monkeypatch.setattr(m,'sdk',forbidden)
 output=tmp_path/'.tmp/capture'
 args=SimpleNamespace(owner_root=output,authority_root=cfg.shared_root,price_date='20261012',
     full_master=False,gap_subset=True,canary_code=None,panel_gaps=path,panel_gaps_sha256=m.sha(path.read_bytes()),
     panel_manifest_relative=None,panel_manifest_sha256=None)
 m.collect(args)
 assert not output.exists()


def test_bad_optional_six_day_owner_does_not_hide_valid_panel(tmp_path):
 cfg,a,c=inputs(tmp_path,count=1);rel,sha=latest13(cfg);c.phase=Phase.RETROSPECTIVE
 write(cfg.shared_root,'assets/hk_0_2/daily_supplements/pointers/20261012.json',{'manifest_relative':'missing.json'})
 pin=hk_panel(cfg,c)
 # The malformed optional sidecar is isolated; valid actual panel is still bound.
 assert pin['manifest_relative']==rel and pin['manifest_sha256']==sha
 pin.update(currency='HKD',price_basis='RAW',volume_unit='SHARES')
 c.scope_refs['owner_bindings']={'hk_panel':pin}
 b=a.load(Lane.OVERSOLD,c)
 assert run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))['rows'][0]['decision']=='SELECTED'


def test_failed_gap_capture_does_not_discard_valid_panel_securities(tmp_path,monkeypatch):
 cfg,codes,api,panel,master,plan=gap_setup(tmp_path,monkeypatch)
 api.missing='00001'
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,
     panel_gap_plan=plan,output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
 cfg.source_bindings['hk_panel']['20261012']['tdxpy_history']=pin
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T19:00:00+08:00'))
 b=a.load(Lane.OVERSOLD,c);out=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert len(out['rows'])==3 and out['coverage']['scope_count']==3
 assert [r['decision'] for r in out['rows']]==['UNASSESSED','SELECTED','SELECTED']
 assert 'TDXPY_EXACT_HISTORY_UNAVAILABLE:HK.00001' in b.gaps
