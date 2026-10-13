from pathlib import Path
import importlib.util,json,sys
HERE=Path(__file__).resolve().parent

def module(name):
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_formal_runner_uses_existing_runs_endpoint_and_no_state_override(tmp_path,monkeypatch):
 m=module('run_formal_us_oversold');monkeypatch.setattr(m,'HERE',tmp_path);(tmp_path/'.tmp').mkdir();output=tmp_path/'.tmp/run'
 calls=[]
 def request(path,body=None):
  calls.append((path,body))
  if path=='/runs':return dict(data=dict(job_id='job1',run_id='run1'))
  if path=='/runs/job1':return dict(data=dict(state='SUCCEEDED',run_id='run1'))
  return dict(data=dict(stocks=[dict(symbol='HK.00001',decision='NOT_SELECTED')],pagination=dict(total=1),counts=dict(total=1)))
 monkeypatch.setattr(m,'request',request);monkeypatch.setattr(sys,'argv',['runner','--output',str(output)])
 m.main();assert calls[0]==('/runs',dict(target_date='20261013',phase='RETROSPECTIVE',lanes=['US_MAPPING','OVERSOLD']))
 assert calls[1][0]=='/runs/job1' and json.loads((output/'receipt.json').read_bytes())['state_root_overrides']==0


def test_full_capture_requires_exact_accepted_canary_no_network(tmp_path,monkeypatch):
 from types import SimpleNamespace
 import pytest
 m=module('collect_tdxpy_61');monkeypatch.setattr(m,'HERE',tmp_path);(tmp_path/'.tmp').mkdir()
 args=SimpleNamespace(owner_root=tmp_path/'.tmp/owner',full_master=True,canary_code=None,accepted_canary=None,accepted_canary_sha256=None)
 monkeypatch.setattr(m,'sdk',lambda *a:pytest.fail('no connection before accepted canary'))
 with pytest.raises(ValueError,match='ACCEPTED_CANARY_PIN_REQUIRED'):m.collect(args)


def test_prepare_keeps_original_formal_state_root(tmp_path,monkeypatch):
 from types import SimpleNamespace
 from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner
 m=module('collect_tdxpy_61');monkeypatch.setattr(m,'HERE',tmp_path);(tmp_path/'.tmp').mkdir()
 state='/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench'
 cfg=tmp_path/'config.json';cfg.write_text(json.dumps(dict(state_root=state,shared_root='/not/requested',scheduled_lanes=['US_MAPPING','OVERSOLD'])))
 pin=tmp_path/'pin.json';pin.write_text(json.dumps(dict(profile='approved-local-test')))
 monkeypatch.setattr(owner,'read_tdxpy_panel_identity',lambda *a:dict(panel_sha256='1'*64,panel_manifest_sha256='3'*64))
 monkeypatch.setattr(owner,'_read_master_identity',lambda *a:(dict(artifact_sha256='2'*64,manifest_sha256='4'*64),['HK.00001']))
 monkeypatch.setattr(owner,'read_tdxpy_window_supplement',lambda *a,**kw:(dict(capture_scope='CANARY',ready_count=1,unassessed_count=0,available_at='2026-10-13T10:00:00Z'),[dict(code='HK.00001')]))
 args=SimpleNamespace(pin=pin,pin_sha256=m.sha(pin.read_bytes()),base_config=cfg,price_date='20261012',cutoff='2026-10-13T19:00:00+08:00',output=tmp_path/'.tmp/prepared')
 m.prepare(args);saved=json.loads((args.output/'base-config.json').read_bytes())
 assert saved['state_root']==state and saved['source_bindings']['hk_panel']['20261012']['tdxpy_history']==json.loads(pin.read_bytes())
