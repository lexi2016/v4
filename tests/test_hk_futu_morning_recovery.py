"""Regression: Futu opening recovery uses exact bars and remains NO_BUY."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from stage_center._live_collectors_parts.hk_minute import _collect_hk_minute_body
from stage_center.acquisition import AcquisitionPlan
from ops._run_stage_center_nodes_parts.stage_dispatch import _same_day_hk_0930_0935_cutoff_recovery_shape

ROOT = Path(os.environ.get('V4_TEST_STAGE_APP_ROOT', Path(__file__).resolve().parents[1]))


def test_plan_carries_recovery_flag():
    assert 'same_day_late_observation_recovery' in AcquisitionPlan.__dataclass_fields__


def receipt():
    return {'schema_version':'stage_center.runner.receipt.v1', 'trade_date':'20261013',
            'stage_id':'STAGE_0930_0935', 'node_id':'STAGE_0930_0935',
            'status':'PARTIAL_WITH_ROWS', 'due_status':'LATE_CATCHUP_REPLAY',
            'dispatch_mode':'RECOVERY', 'node_outcome':'SETTLED_PARTIAL',
            'node_attempt_count':2, 'write_performed':True,
            'production_allowed':False, 'buy_gate_updated':False, 'orders_sent':False,
            'markets':{'HK_CONNECT':{'market':'HK_CONNECT','status':'CANNOT_CONFIRM',
                'source_status':'CANNOT_CONFIRM','selection_status':'CANNOT_CONFIRM',
                'selected_rows':0,'write_performed':False,
                'cannot_confirm':['HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE']}}}


def match(r, **overrides):
    args=dict(mode='RECOVERY',trade_date='20261013',stage_id='STAGE_0930_0935',attempt_count=2,max_attempts=3)
    return _same_day_hk_0930_0935_cutoff_recovery_shape(r, **(args | overrides))


def test_cutoff_repair_not_frozen_to_yesterday():
    assert match(receipt())


@pytest.mark.parametrize('change', ['date','selected','reason','safety'])
def test_recovery_rejects_unrelated_receipt(change):
    r=receipt()
    if change=='date':r['trade_date']='20261012'
    if change=='selected':r['markets']['HK_CONNECT']['selected_rows']=10
    if change=='reason':r['markets']['HK_CONNECT']['cannot_confirm']=['OTHER']
    if change=='safety':r['orders_sent']=True
    assert not match(r)


def test_recovery_retains_budget_and_manual_boundary():
    assert not match(receipt(), attempt_count=3)
    assert not match(receipt(), mode='NATURAL')


def test_futu_bridge_full_history_and_exact_window(tmp_path):
    # Import the same shared package that the running collector loads.
    import sys
    sys.path.insert(0,str(ROOT/'upstreams/v3_shared_data'))
    from scripts.live_acquisition import futu_bridge as bridge
    bars=[]
    for date,minute in [('2026-10-12',31),('2026-10-13',30),*[( '2026-10-13',i) for i in range(31,37)]]:
        bars.append(dict(code='HK.02915',name='sample',time_key=f'{date} 09:{minute}:00',open=10,close=11,high=12,low=9,volume=10,turnover=100,last_close=9))
    captured='2026-10-13T12:00:00+08:00'
    def process(args,**kwargs):
        request=json.loads(kwargs['input'])
        assert request['num_bars']==1000 and request['market']=='HK_CONNECT'
        assert 'is_first_push=hk' in args[2] and 'ft.AuType.NONE if hk' in args[2]
        return SimpleNamespace(returncode=0,stderr='',stdout=bridge.MARKER+json.dumps({'rows':bars,'errors':[],'no_data_codes':[],'captured_at':captured})+'provider trailing log')
    result=bridge.collect_futu_minute(Path(sys.executable),'20261013','STAGE_0930_0935',['HK.02915'],market='HK_CONNECT',process_runner=process)
    row=result.rows[0]
    assert row['bar_count']==5 and row['window_start']=='2026-10-13 09:31:00'
    assert row['window_end']=='2026-10-13 09:35:00' and row['futu_captured_at']==captured
    assert len(row['futu_provider_rows_sha256'])==64


def test_late_futu_does_not_call_current_book():
    import stage_center.live_collectors as live
    from stage_center.acquisition import SourceResult
    scope=dict(vars(live))
    rows=({'code':'HK.02915','futu_captured_at':'2026-10-13T12:00:00+08:00'},)
    module=SimpleNamespace(collect_futu_minute=lambda *a,**kw:object())
    scope.update(_shared_scripts_root=lambda r:r,_load_shared_module=lambda *a:module,
                 _scoped_process_runner=lambda *a:None,
                 _to_source=lambda *a,**kw:SourceResult('futu','READY',rows=rows,requested_rows=1),
                 refresh_hk_active_lanes=lambda *a,**kw:pytest.fail('current book must not reconstruct an earlier stage'))
    plan=SimpleNamespace(stage_id='STAGE_0930_0935',trade_date='20261013',same_day_late_observation_recovery=True)
    import inspect
    extra={'snapshot_root':None} if 'snapshot_root' in inspect.signature(_collect_hk_minute_body).parameters else {}
    result=_collect_hk_minute_body(scope,plan,codes=['HK.02915'],python_path='python',shared_root='root',process_runner=None,replay_provider=None,**extra)
    assert len(result.rows)==1 and result.status=='PARTIAL_WITH_ROWS'
    assert 'HK_HISTORICAL_ORDERBOOK_UNAVAILABLE' in result.cannot_confirm
    assert 'pit_safe=false' in result.source_evidence
    assert not result.rows[0].get('candidate_lanes')
