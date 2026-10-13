from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import json
import pytest
from test_native_pipeline import fixture
from test_integration import context
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.validation import raw_sha
from v4.manager_workbench.contracts import Lane
from v4.manager_workbench.engines.oversold import screen_one,run_oversold
from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner
ROOT=Path(__file__).resolve().parents[3]
CAL=ROOT/'docs/handoff/manager-workbench-implementation-20261013/deployment-deltas/isolated-api-candidate-v7-final/app/contracts/market_calendar_2026.json'
REAL=ROOT/'docs/handoff/manager-workbench-implementation-20261013/.tmp/tdxpy-market31-diagnostic-r1/116.205.143.214-raw.json'

@pytest.fixture(autouse=True)
def calendar(monkeypatch):
 from contracts import trading_calendar as tc
 from v4.manager_workbench.inputs import native
 monkeypatch.setattr(tc,'CALENDAR_PATH',CAL)
 original=tc.load_market_calendar
 monkeypatch.setattr(tc,'load_market_calendar',lambda:original(CAL))
 monkeypatch.setattr(native,'CALENDAR_PATH',CAL);monkeypatch.setattr(native,'load_market_calendar',lambda:original(CAL))

class API:
 def __init__(self,codes,rows=None,missing=None):
  self.codes=codes;self.rows=rows if rows is not None else json.loads(REAL.read_bytes());self.calls=[];self.missing=missing
 def get_markets(self):return [dict(market=m,name=n,category=2) for m,n in owner.TDXPY_MARKETS.items()]
 def get_instrument_count(self):return len(self.codes)
 def get_instrument_info(self,start,count):return [dict(code=c[3:],market=31,category=2,name=c) for c in self.codes][start:start+count]
 def get_instrument_bars(self,*args):
  self.calls.append(args)
  if args[2]==self.missing:raise ConnectionError('bounded failure')
  return deepcopy(self.rows)
 def disconnect(self):pass

def setup(tmp_path,monkeypatch,count=692):
 (tmp_path/'input').mkdir()
 cfg=fixture(tmp_path/'input',count=count)
 pin=cfg.source_bindings['hk_panel']['20261012'];pm=json.loads((cfg.shared_root/pin['manifest_relative']).read_bytes())
 mp=cfg.source_bindings['security_master']['20261012'];mm=json.loads((cfg.shared_root/mp['manifest_relative']).read_bytes())
 codes=['HK.'+str(i).zfill(5) for i in range(1,count+1)]
 panel=dict(panel_manifest_relative=pin['manifest_relative'],panel_manifest_sha256=raw_sha((cfg.shared_root/pin['manifest_relative']).read_bytes()),panel_sha256=pm['panel_sha256'],manifest_prepared_at='2026-10-12T10:00:00+00:00')
 master=dict(manifest_sha256=raw_sha((cfg.shared_root/mp['manifest_relative']).read_bytes()),artifact_sha256=mm['artifact_sha256'],captured_at='2026-10-12T10:00:00+00:00',universe_codes_sha256=owner._sha(owner._canonical(codes)))
 monkeypatch.setattr(owner,'_read_panel_identity',lambda *args,**kw:panel)
 monkeypatch.setattr(owner,'_read_master_identity',lambda *args:(master,codes))
 api=API(codes);clock=lambda:datetime(2026,10,13,10,tzinfo=timezone.utc)
 return cfg,codes,api,clock,panel,master

def capture(tmp_path,monkeypatch,count=692,subset=('HK.00001',)):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,count)
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',canary_codes=subset,
      connector=lambda endpoint:api,output_root=tmp_path/'owner',clock=clock)
 return cfg,codes,api,clock,panel,master,pin

def read(pin,panel,master,codes,cutoff='2026-10-13T18:00:00+08:00'):
 return owner.read_tdxpy_window_supplement(pin,target_date='20261012',cutoff=cutoff,
   expected_panel_sha=panel['panel_sha256'],expected_master_sha=master['artifact_sha256'],expected_codes=codes)

def test_real_native_61_profile_full692_no_volume_conversion(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch)
 manifest,records=read(pin,panel,master,codes)
 assert manifest['ready_count']==1 and len(records[0]['bars'])==61
 assert records[0]['outside_requested_sessions'][-1]=='20261013' and records[0]['bars'][-1]['trade']==34348
 cfg.source_bindings['hk_panel']['20261012']['tdxpy_history']=pin
 for key in ('currency','price_basis','volume_unit'):cfg.source_bindings['hk_panel']['20261012'].pop(key)
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T18:00:00+08:00'));b=a.load(Lane.OVERSOLD,c)
 result=run_oversold(c.model_dump(mode='json'),b.model_dump(mode='json'))
 assert result['coverage']['scope_count']==692 and len(result['rows'])==692
 selected=next(r for r in result['rows'] if r['symbol']=='HK.00001')
 assert selected['decision']=='NOT_SELECTED' and selected['metrics']['price_pass'] is False and selected['metrics']['volume_pass'] is False
 assert selected['metrics']['volume']=='34348.0'
 assert len([r for r in result['rows'] if r['decision']=='UNASSESSED'])==691
 row=next(r for r in b.records if r['symbol']=='HK.00001')
 assert row['owner']=='TDXPY_0_2_7' and row['adjustment']=='TDX_PROTOCOL_PARAM1_FIXED'
 assert row['volume_unit'] is None and row['price_unit'] is None


def test_success_cache_reused_old_available_no_network_bars(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch,count=2)
 pin2=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',canary_codes=['HK.00001'],
    connector=lambda e:api,output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,11,tzinfo=timezone.utc))
 assert len(api.calls)==1 and pin2['cache_hits']==1 and pin2['network_bar_requests']==0
 _,a=read(pin,panel,master,codes);_,b=read(pin2,panel,master,codes,'2026-10-13T19:00:00+08:00')
 assert a[0]['response_sha256']==b[0]['response_sha256'] and a[0]['request_finished_at']==b[0]['request_finished_at']


@pytest.mark.parametrize('mutation',['raw_sha','manifest_sha','cutoff','master','profile','missing','mixed_market','catalogue','volume','unknown_status'])
def test_corrupt_evidence_rejected(tmp_path,monkeypatch,mutation):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch,count=2)
 if mutation=='raw_sha':pin['raw_sha256']='0'*64
 elif mutation=='manifest_sha':pin['manifest_sha256']='0'*64
 elif mutation=='cutoff':
  with pytest.raises(ValueError):read(pin,panel,master,codes,'2026-10-13T17:59:59+08:00')
  return
 elif mutation=='master':master['artifact_sha256']='0'*64
 else:
  root=Path(pin['source_local_path']);raw=json.loads((root/pin['raw_relative']).read_bytes())
  if mutation=='profile':raw['profile']['param1']=0
  elif mutation=='missing':raw['records'][0]['source_rows']=[r for r in raw['records'][0]['source_rows'] if r['datetime'][:10]!='2026-09-25'];raw['records'][0]['response_sha256']=owner._sha(owner._canonical(raw['records'][0]['source_rows']));raw['records'][0]['returned_count']-=1
  elif mutation=='mixed_market':raw['records'][0]['request']['market']=71
  elif mutation=='catalogue':raw['catalogues'][0]['rows'][0]['market']=71
  elif mutation=='volume':raw['records'][0]['bars'][-1]['trade']*=100
  else:raw['records'][0]['status']='COMPLETE'
  data=owner._canonical(raw);(root/pin['raw_relative']).write_bytes(data);pin['raw_sha256']=owner._sha(data)
  m=json.loads((root/pin['manifest_relative']).read_bytes());m['raw_sha256']=pin['raw_sha256'];m['run_id']=pin['raw_sha256'][:24]
  mb=owner._canonical(m);(root/pin['manifest_relative']).write_bytes(mb);pin['manifest_sha256']=owner._sha(mb)
 with pytest.raises((ValueError,KeyError)):read(pin,panel,master,codes)


def test_missing_identity_no_bar_request_and_full_scope_unknown(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,2)
 api.codes=['HK.00001']
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 m,records=read(pin,panel,master,codes)
 assert m['code_count']==2 and m['ready_count']==1 and records[1]['status']=='UNASSESSED'
 assert all(call[2]!='00002' for call in api.calls)


def test_market48_explicit_and_ambiguous_rejected(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,1)
 api.get_instrument_info=lambda start,count:[dict(code='00001',market=48,category=2,name='HK GEM')]
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 assert api.calls==[(4,48,'00001',0,128)]
 read(pin,panel,master,codes)
 catalogue=owner._catalogue(api,owner.TDXPY_NODES[0],clock)
 catalogue['rows'].append(dict(code='00001',market=31,category=2,name='duplicate security'))
 with pytest.raises(ValueError):owner._catalogue_security(catalogue,'HK.00001')


def test_old_default_still_six_sessions():
 dates,_=owner.requested_sessions('20261012');assert len(dates)==6
 dates,_=owner.requested_sessions('20261012',61);assert len(dates)==61


def test_only_failed_stock_retried_success_cache_preserved(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,2);api.missing='00002'
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 m,rows=read(pin,panel,master,codes);assert m['ready_count']==1 and m['unassessed_count']==1
 raw=json.loads((Path(pin['source_local_path'])/pin['raw_relative']).read_bytes())
 assert len(raw['failed_attempts'])==2 and all(a['request']['code']=='HK.00002' for a in raw['failed_attempts'])
 api.calls=[];api.missing=None
 p2=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,11,tzinfo=timezone.utc))
 assert p2['cache_hits']==1 and len(api.calls)==1 and api.calls[0][2]=='00002'
 m,rows=read(p2,panel,master,codes,'2026-10-13T19:00:00+08:00');assert m['ready_count']==2


def test_profile_cannot_change_wire_market_or_mix_bars(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch,count=1)
 cfg.source_bindings['hk_panel']['20261012']['tdxpy_history']=pin
 for key in ('currency','price_basis','volume_unit'):cfg.source_bindings['hk_panel']['20261012'].pop(key)
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T18:00:00+08:00'));row=a.load(Lane.OVERSOLD,c).records[0]
 for field,value in [('param1',0),('market',71),('endpoint','119.97.142.130:7721'),('adjustment','RAW')]:
  bad=deepcopy(row);bad['comparison_basis']['request']['request'][field]=value
  assert screen_one(c.model_dump(mode='json'),bad)['decision']=='UNASSESSED'
 bad=deepcopy(row);bad['high_history60'][0]['source_metadata']['source']='FUTU'
 assert screen_one(c.model_dump(mode='json'),bad)['decision']=='UNASSESSED'


def test_original_and_thresholds_still_select_only_both_proven(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,1)
 dates,_=owner.requested_sessions('20261012',61)
 api.rows=[dict(datetime=d[:4]+'-'+d[4:6]+'-'+d[6:]+' 15:00',open=70.,close=70.,high=100.,low=60.,trade=10 if d!=dates[-1] else 20,amount=1) for d in dates]
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 cfg.source_bindings['hk_panel']['20261012']['tdxpy_history']=pin
 for key in ('currency','price_basis','volume_unit'):cfg.source_bindings['hk_panel']['20261012'].pop(key)
 a=NativeAdapters(cfg);c=a.prepare_context(context(cutoff='2026-10-13T18:00:00+08:00'));r=a.load(Lane.OVERSOLD,c).records[0]
 selected=screen_one(c.model_dump(mode='json'),r)
 assert selected['decision']=='SELECTED' and selected['reason']=='OVERSOLD_AND_VERIFIED'
 assert selected['metrics']['price_threshold']=='80.00' and selected['metrics']['volume_ratio']=='2'


def test_owner_exclusive_lock_no_duplicate_requests(tmp_path,monkeypatch):
 import fcntl
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,1);output=tmp_path/'owner';output.mkdir()
 with (output/'.capture.lock').open('a+b') as locked:
  fcntl.flock(locked.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  with pytest.raises(BlockingIOError):owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=output,clock=clock)
 assert api.calls==[] and not (output/'runs').exists()


def test_catalogue_total_changed_is_partial_but_observed_stock_valid(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,1)
 total_calls=[]
 def count():
  total_calls.append(True);return 1 if len(total_calls)%2 else 2
 api.get_instrument_count=count
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 raw=json.loads((Path(pin['source_local_path'])/pin['raw_relative']).read_bytes())
 assert pin['ready_count']==1 and len(api.calls)==1
 assert raw['catalogues'][0]['coverage_status']=='PARTIAL'
 assert any(g['code']=='TDXPY_CATALOGUE_TOTAL_CHANGED' for g in raw['catalogues'][0]['coverage_gaps'])
 read(pin,panel,master,codes)


def test_owner_wrong_parent_manifest_sha_rejected(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch,count=1)
 with pytest.raises(ValueError):owner.read_tdxpy_window_supplement(pin,target_date='20261012',cutoff='2026-10-13T18:00:00+08:00',
    expected_panel_sha=panel['panel_sha256'],expected_master_sha=master['artifact_sha256'],expected_codes=codes,expected_master_manifest_sha='0'*64)


REAL_FAILED_ROOT=ROOT/'docs/handoff/manager-workbench-implementation-20261013/.tmp/tdxpy61-owner-r1'
REAL_FAILED_RAW='runs/20261012/db3feb890556e427001fbd0d/raw_capture.json'


def test_real_partial_catalogue_recovery_keeps_original_shas_and_identity():
 before=raw_sha((REAL_FAILED_ROOT/REAL_FAILED_RAW).read_bytes())
 for endpoint in owner.TDXPY_NODES:
  doc=owner._recover_catalogue(REAL_FAILED_ROOT,endpoint)
  assert doc['coverage_status']=='PARTIAL' and doc['recovered_from']['raw_sha256']==before
  assert owner._catalogue_security(doc,'HK.00001')['security']['market']==31
  assert owner._catalogue_security(doc,'HK.02800')['security']['market']==49
  assert owner._catalogue_security(doc,'HK.02828')['security']['market']==49
  assert any(g['code']=='TDXPY_GLOBAL_CATALOGUE_COVERAGE_PARTIAL' for g in doc['coverage_gaps'])
 assert raw_sha((REAL_FAILED_ROOT/REAL_FAILED_RAW).read_bytes())==before


def test_real_saved_pages_recovery_requests_bars_only(tmp_path,monkeypatch):
 import shutil
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,1)
 output=tmp_path/'owner'
 for name in ('raw_capture.json','manifest.json'):
  relative=Path(REAL_FAILED_RAW).with_name(name);dst=output/relative;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(REAL_FAILED_ROOT/relative,dst)
 api.get_markets=lambda:pytest.fail('no repeated global catalogue request')
 api.get_instrument_count=lambda:pytest.fail('no repeated global catalogue request')
 api.get_instrument_info=lambda *a:pytest.fail('no repeated global catalogue request')
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',canary_codes=['HK.00001'],
   connector=lambda endpoint:api,output_root=output,clock=lambda:datetime(2026,10,13,12,tzinfo=timezone.utc))
 assert pin['ready_count']==1 and pin['network_bar_requests']==1 and api.calls==[(4,31,'00001',0,128)]
 read(pin,panel,master,codes,'2026-10-13T20:00:00+08:00')


@pytest.mark.parametrize('market',[31,48,49])
def test_partial_catalogue_known_identity_accepted_unknown_or_conflict_isolated(tmp_path,monkeypatch,market):
 cfg,codes,api,clock,panel,master=setup(tmp_path,monkeypatch,2)
 api.get_instrument_info=lambda start,count:[dict(code='00001',market=market,category=2,name='existing security')]
 pin=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',connector=lambda e:api,output_root=tmp_path/'owner',clock=clock)
 manifest,records=read(pin,panel,master,codes)
 assert manifest['code_count']==2 and manifest['ready_count']==1 and records[1]['status']=='UNASSESSED'
 assert manifest['catalogue_coverage_status']=='PARTIAL'
 assert api.calls==[(4,market,'00001',0,128)]
 raw=json.loads((Path(pin['source_local_path'])/pin['raw_relative']).read_bytes())
 assert raw['catalogues'][0]['coverage_status']=='PARTIAL'
 doc=deepcopy(raw['catalogues'][0]);doc['rows'].append(dict(code='00001',market=48 if market==31 else 31,name='conflict'))
 with pytest.raises(ValueError):owner._catalogue_security(doc,'HK.00001')


def test_explicit_historical_panel_pin_survives_latest_date_advance(tmp_path):
 root=tmp_path/'authority';asset=root/'assets/hk_0_2';asset.mkdir(parents=True)
 data=b'immutable panel bytes';artifact=asset/'panels/12/panel.parquet';artifact.parent.mkdir(parents=True);artifact.write_bytes(data)
 manifest=dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs',
   panel_max_date='20261012',panel_relative='panels/12/panel.parquet',panel_sha256=owner._sha(data),manifest_prepared_at='2026-10-12T09:00:00Z',**owner.SAFETY)
 old=asset/'panels/12/manifest.json';old.write_bytes(owner._canonical(manifest));original=old.read_bytes()
 latest=asset/'panels/13/manifest.json';latest.parent.mkdir();latest.write_bytes(owner._canonical(dict(manifest,panel_max_date='20261013')))
 pointer=asset/'panel_latest.json';pointer.write_bytes(owner._canonical(dict(manifest_relative='panels/13/manifest.json')));pointer_bytes=pointer.read_bytes()
 with pytest.raises(ValueError,match='PANEL_IDENTITY_INVALID'):owner._read_panel_identity(root,'20261012')
 good=owner._read_panel_identity(root,'20261012',manifest_relative='assets/hk_0_2/panels/12/manifest.json',manifest_sha256=owner._sha(original))
 assert good['panel_max_date']=='20261012' and good['panel_manifest_sha256']==owner._sha(original)
 with pytest.raises(ValueError,match='PIN_SHA_MISMATCH'):owner._read_panel_identity(root,'20261012',manifest_relative='assets/hk_0_2/panels/12/manifest.json',manifest_sha256='0'*64)
 assert pointer.read_bytes()==pointer_bytes and old.read_bytes()==original


def test_saved_panel_binding_is_inherited_not_latest(tmp_path,monkeypatch):
 cfg,codes,api,clock,panel,master,pin=capture(tmp_path,monkeypatch,count=1)
 passed=[]
 def historical(root,date,**kw):
  passed.append(kw)
  if not kw:raise ValueError('latest was advanced')
  return panel
 monkeypatch.setattr(owner,'_read_panel_identity',historical)
 p2=owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',canary_codes=['HK.00001'],connector=lambda e:api,
    output_root=tmp_path/'owner',clock=lambda:datetime(2026,10,13,11,tzinfo=timezone.utc))
 assert p2['ready_count']==1 and p2['cache_hits']==1
 assert passed==[dict(manifest_relative=panel['panel_manifest_relative'],manifest_sha256=panel['panel_manifest_sha256'])]
 with pytest.raises(ValueError,match='SAVED_PANEL_BINDING_DRIFT'):owner.capture_tdxpy_window_supplement(cfg.shared_root,target_date='20261012',
   connector=lambda e:api,output_root=tmp_path/'owner',clock=clock,panel_binding=dict(manifest_relative='wrong',manifest_sha256='0'*64))
