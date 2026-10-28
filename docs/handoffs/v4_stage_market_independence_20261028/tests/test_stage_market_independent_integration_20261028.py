import importlib.util
import os
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('stage_retry_fixture', Path(os.environ['V4_TEST_RUNTIME_APP']) / 'tests/test_stage_20260924_market_retry_regression.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.parametrize('failed,other', [('A_SHARE','HK_CONNECT'),('HK_CONNECT','A_SHARE')])
def test_builder_failure_does_not_block_other_market(tmp_path, monkeypatch, failed, other):
    runner, _ = fixture._runner(tmp_path,monkeypatch,hk_failures=0)
    def failed_builder(*args):
        raise ValueError('INJECTED_BUILDER_FAILURE')
    runner.config.selection_builders[failed] = failed_builder
    receipt = runner._run_one(fixture._decision(runner))
    assert receipt['markets'][failed]['selection_status']=='CANNOT_CONFIRM'
    assert 'INJECTED_BUILDER_FAILURE' in receipt['markets'][failed]['cannot_confirm'][0]
    assert receipt['markets'][other]['selection_status']=='READY'
    assert receipt['markets'][other]['selected_rows']==1
    assert receipt['status']=='PARTIAL_WITH_ROWS'
    assert fixture.SelectionStore(runner.config.selection_root).read_verified(fixture.TRADE_DATE,fixture.STAGE_ID,other)['selection_status']=='READY'
    for market in (failed,other):
        assert fixture.RawStore(runner.config.raw_root).verify_latest(fixture.TRADE_DATE,fixture.STAGE_ID,market)['verified']['row_count']==1


@pytest.mark.parametrize('failed,other', [('A_SHARE','HK_CONNECT'),('HK_CONNECT','A_SHARE')])
def test_projection_failure_preserves_other_market(tmp_path, monkeypatch, failed, other):
    import stage_center.runner as runner_module
    runner, _ = fixture._runner(tmp_path,monkeypatch,hk_failures=0)
    original = runner_module._project_raw_rows
    def project(rows, *, trade_date, stage_id, market, **kwargs):
        if market == failed: raise ValueError('INJECTED_PROJECTION_FAILURE')
        return original(rows, trade_date=trade_date, stage_id=stage_id, market=market, **kwargs)
    monkeypatch.setattr(runner_module, '_project_raw_rows', project)
    receipt = runner._run_one(fixture._decision(runner))
    assert receipt['markets'][failed]['selection_status'] == 'CANNOT_CONFIRM'
    assert 'INJECTED_PROJECTION_FAILURE' in receipt['markets'][failed]['cannot_confirm'][0]
    assert receipt['markets'][other]['selection_status'] == 'READY'
    assert fixture.SelectionStore(runner.config.selection_root).read_verified(fixture.TRADE_DATE,fixture.STAGE_ID,other)['selection_status']=='READY'

@pytest.mark.parametrize('failed,other', [('A_SHARE','HK_CONNECT'),('HK_CONNECT','A_SHARE')])
def test_actual_api_consumer_sees_independent_lane(tmp_path, monkeypatch, failed, other):
    import json, os, subprocess, sys
    runner, _ = fixture._runner(tmp_path,monkeypatch,hk_failures=0)
    def failed_builder(*args): raise ValueError('INJECTED_BUILDER_FAILURE')
    runner.config.selection_builders[failed] = failed_builder
    receipt = runner._run_one(fixture._decision(runner))
    assert receipt['markets'][other]['selection_status']=='READY'
    api_app = os.environ['V4_TEST_API_APP']
    script = '''
import json,sys
from pathlib import Path
from apps.api.v35_api.app import create_app
app=create_app(data_root=Path(sys.argv[1])/'api_data',stage_center_selection_root=Path(sys.argv[1])/'selection')
endpoint=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/v3/stage-center/selection')
value=endpoint(date='20260924',stage='STAGE_0945_1030',limit=50)
print(json.dumps(value,ensure_ascii=False))
'''
    env=os.environ.copy();env.pop('PYTHONPATH',None)
    proc=subprocess.run([sys.executable,'-B','-c',script,str(tmp_path)],cwd=api_app,env=env,text=True,capture_output=True,check=True)
    projection=json.loads(proc.stdout.strip().splitlines()[-1])
    good='A' if other=='A_SHARE' else 'HK';bad='HK' if good=='A' else 'A'
    assert projection['markets'][good]['candidate_count'] == 1
    assert projection['markets'][bad]['status'] == 'CANNOT_CONFIRM'
    assert projection['status']=='PARTIAL_WITH_ROWS'


def test_hk_exact_input_oserror_does_not_block_a_0925(tmp_path, monkeypatch):
    from datetime import datetime
    import stage_center.runner as runner_module
    monkeypatch.setattr(fixture, 'STAGE_ID', 'STAGE_0925')
    monkeypatch.setattr(fixture, 'ATTEMPT_AT', datetime(2026,9,24,9,25,5,tzinfo=fixture.SHANGHAI))
    original_row=fixture._raw_row
    def row(market):
        result=original_row(market)
        result.update(update_time='2026-09-24 09:25:00',window_start='2026-09-24 09:25:00',window_end='2026-09-24 09:25:00')
        return result
    monkeypatch.setattr(fixture,'_raw_row',row)
    runner,_=fixture._runner(tmp_path,monkeypatch,hk_failures=0)
    original=runner_module._validate_exact_selection_inputs
    def validate(config, date, stage, *, market, hk_binding):
        if market=='HK_CONNECT':raise OSError('INJECTED_HK_0925_CSV_ERROR')
        return original(config,date,stage,market=market,hk_binding=hk_binding)
    monkeypatch.setattr(runner_module,'_validate_exact_selection_inputs',validate)
    result=runner._run_one(fixture._decision(runner))
    assert result['markets']['HK_CONNECT']['selection_status']=='CANNOT_CONFIRM'
    assert 'INJECTED_HK_0925_CSV_ERROR' in result['markets']['HK_CONNECT']['cannot_confirm'][0]
    assert result['markets']['A_SHARE']['selection_status']=='READY'
    assert fixture.SelectionStore(runner.config.selection_root).read_verified(fixture.TRADE_DATE,'STAGE_0925','A_SHARE')['selection_status']=='READY'


def test_hk_second_filter_oserror_does_not_block_a_0925(tmp_path, monkeypatch):
    from datetime import datetime
    from dataclasses import replace
    from stage_center.acquisition import StageUniverseBinding
    import stage_center.runner as runner_module
    monkeypatch.setattr(fixture,'STAGE_ID','STAGE_0925')
    monkeypatch.setattr(fixture,'ATTEMPT_AT',datetime(2026,9,24,9,25,5,tzinfo=fixture.SHANGHAI))
    original_row=fixture._raw_row
    def row(market):
        value=original_row(market)
        value.update(update_time='2026-09-24 09:25:00',window_start='2026-09-24 09:25:00',window_end='2026-09-24 09:25:00')
        return value
    monkeypatch.setattr(fixture,'_raw_row',row)
    runner,_=fixture._runner(tmp_path,monkeypatch,hk_failures=0)
    runner.config=replace(runner.config,hk_d1_root=tmp_path,hk_second_filter_root=tmp_path,shared_data_root=tmp_path,python_path=tmp_path/'python')
    monkeypatch.setattr(runner_module.RunnerConfig,'injected_test_mode',property(lambda self:False))
    binding=StageUniverseBinding.ready(market='HK_CONNECT',trade_date=fixture.TRADE_DATE,role='HK_TEST',codes=('HK.00001',),source_run_id='hk',sha256='f'*64)
    monkeypatch.setattr(runner_module,'_build_hk_stage_binding',lambda *a,**k:binding)
    monkeypatch.setattr(runner_module,'_validated_hk_binding_evidence',lambda *a,**k:())
    monkeypatch.setattr(runner_module,'_validate_exact_selection_inputs',lambda *a,**k:())
    def fail(*args):raise OSError('INJECTED_HK_SECOND_CSV_ERROR')
    monkeypatch.setattr(runner_module,'_hk_second_filter_codes',fail)
    result=runner._run_one(fixture._decision(runner))
    assert result['markets']['HK_CONNECT']['selection_status']=='CANNOT_CONFIRM',result
    assert 'INJECTED_HK_SECOND_CSV_ERROR' in result['markets']['HK_CONNECT']['cannot_confirm'][0]
    assert result['markets']['A_SHARE']['selection_status']=='READY',result
