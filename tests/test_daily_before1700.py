"""Bounded tests against an actual Main clone; no canonical data or services."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

APP = os.environ.get('V4_BEFORE1700_CANDIDATE_APP')
if not APP:
    pytest.skip('Pin the actual Main clone dependency root', allow_module_level=True)
sys.path.insert(0, APP)
from ops import research_daily_product_parallel as parallel
from ops import research_panel_daily_product as owner
from ops import research_panel_top200 as top
from ops import sync_stock_history_completion as sync

G = 1024 ** 3

def observed(available=119, rss=19, cores=18, total=128):
    return dict(physical_memory_bytes=total*G, available_bytes=available*G,
                cumulative_rss_bytes=rss*G, cpu_cores=cores)


def test_resource_plan_keeps_four_gib_envelope_reserve_and_bounded_fourteen():
    plan = parallel.resource_plan(observed(), 5808)
    assert plan['workers'] == 14 and plan['max_pending'] == 28
    assert plan['estimated_worker_bytes'] == 4*G
    assert plan['memory_guard_bytes'] == 80*G and plan['reserve_available_bytes'] == 24*G
    assert 19*G + plan['workers']*plan['estimated_worker_bytes'] <= plan['memory_guard_bytes']
    assert plan['memory_guard_bytes'] + plan['reserve_available_bytes'] <= 128*G
    low = parallel.resource_plan(observed(available=80), 5808)
    assert low['workers'] == 9 and low['max_pending'] == 18
    assert parallel.resource_plan(observed(cores=32, total=256, available=220), 5808)['workers'] == 14
    assert parallel.resource_plan(observed(), 3)['workers'] == 3


def test_pressure_stops_new_submissions_and_preserves_completed_checkpoints(tmp_path, monkeypatch):
    submitted = []
    class Pool:
        def __init__(self, **kwargs):
            assert kwargs['max_workers'] == 14
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, symbol):
            submitted.append(symbol)
            done = concurrent.futures.Future()
            done.set_result(dict(symbol=symbol,ref=owner.save(tmp_path/(symbol+'.result.json'),{'symbol':symbol}),chart_gaps={}))
            return done
    monkeypatch.setattr(parallel, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(parallel, 'memory_state', lambda: observed(available=23, rss=2))
    context = SimpleNamespace(generation='test-only',target=20261105,data_root=tmp_path,root=tmp_path,
        identity={},config_ref={},unchanged=lambda:None)
    symbols = [f'{i:06}.SZ' for i in range(40)]
    with pytest.raises(MemoryError, match='RESOURCE_GUARD_DRAINED'):
        parallel.run_pending(context,tmp_path,symbols,symbols,original_charts=False,
                             resources=parallel.resource_plan(observed(),40),sources={})
    assert len(submitted) == 28
    state = json.loads(next(tmp_path.glob('parallel_run_*.json')).read_text())
    assert state['status'] == 'FAILED_DRAINED' and state['stop_new_submissions'] is True
    assert state['completed'] == 28 and len(list(tmp_path.glob('*.result.json'))) == 28


def prior_case(tmp_path):
    snapshot = owner.save(tmp_path/'snapshot.json',{'fixture':'prior'})
    identity = dict(generation='old-generation',input_sha256='input',snapshot=snapshot,
                    selector_artifact_sha256='a'*64,asof=20261029)
    receipt = dict(generation_id=identity['generation'],input_sha256=identity['input_sha256'],
                   adjustment_snapshot=snapshot,candidate_sha256={'selector':'a'*64},
                   candidates={'selector':str(tmp_path/'missing.parquet')})
    owner.save(tmp_path/'candidate_receipt.json',receipt)
    cache = {'000001.SZ':{'evaluations':{'20261029':{'source_identity':identity}}}}
    return identity, receipt, cache


def test_only_verified_missing_prior_panel_gets_typed_isolation(tmp_path):
    identity, receipt, cache = prior_case(tmp_path)
    context = SimpleNamespace(identity={'generation':'new-generation'})
    with pytest.raises(top.HistoryPriorPanelUnavailable) as raised:
        top._prior_generation_proofs(context,cache,{'000001.SZ':[]})
    assert raised.value.evidence['source_identity'] == identity
    assert raised.value.evidence['receipt']['path'].endswith('candidate_receipt.json')
    receipt['generation_id'] = 'WRONG'
    owner.save(tmp_path/'candidate_receipt.json',receipt)
    with pytest.raises(ValueError, match='HISTORY_PRIOR_RECEIPT_IDENTITY_CONFLICT') as raised:
        top._prior_generation_proofs(context,cache,{'000001.SZ':[]})
    assert not isinstance(raised.value, top.HistoryPriorPanelUnavailable)


def continuation(tmp_path, monkeypatch, history):
    root = tmp_path/'daily';root.mkdir();owner.save(root/'index.json',{'dates':{},'top200':{}})
    receipt_root = tmp_path/'receipts';owner.save(receipt_root/'a_sync_authority/official_daily/20261105/input.json',{'fixture':True})
    calls=[]
    monkeypatch.setattr(owner,'SourceContext',lambda *args:SimpleNamespace(generation='current-generation'))
    def run(*args):
        calls.append('history')
        if isinstance(history,Exception): raise history
        return history
    monkeypatch.setattr(top,'run_incremental_history',run)
    monkeypatch.setattr(top,'publish_current_history_view',lambda *args:calls.append('history_view')or{'status':'COMPLETE'})
    monkeypatch.setattr(top,'build',lambda *args:(calls.append('build')or{'fixture':'same-source'}, {'reused':False}))
    monkeypatch.setattr(top,'stage',lambda *args:calls.append('stage')or{'status':'PREPARED_TOP200'})
    monkeypatch.setattr(sync,'publish',lambda *args:calls.append('publish')or{'status':'PUBLISHED_TOP200'})
    monkeypatch.setattr(top,'record_daily_attempt',lambda *args:{'path':'fixture-only','sha256':'b'*64})
    f10=types.ModuleType('ops.research_panel_f10')
    f10.complete_f10=lambda *args,**kwargs:calls.append('f10')or{'receipt':{}}
    f10.publish_f10_completion=lambda *args:calls.append('f10_publish')or{'status':'TEST_ONLY'}
    monkeypatch.setitem(sys.modules,'ops.research_panel_f10',f10)
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT',raising=False)
    return root,receipt_root,calls


def test_missing_old_history_still_uses_original_top200_but_never_promotes_complete_or_f10(tmp_path, monkeypatch):
    failure=top.HistoryPriorPanelUnavailable('/prior/missing.parquet',{'path':'prior-receipt','sha256':'c'*64},{'generation':'old'})
    root,receipt_root,calls=continuation(tmp_path,monkeypatch,failure)
    old=owner.save(root/'attempts/20261105/old/receipt.json',{'status':'CANNOT_CONFIRM','error':'original prior failure'})
    old_bytes=Path(old['path']).read_bytes()
    result=top.complete_daily_derivatives(tmp_path,20261105,root,receipt_root,tmp_path)
    assert calls == ['history','build','stage','publish']
    assert result['status']=='CANNOT_CONFIRM' and result['reason']=='HISTORY_INCOMPLETE_TOP200_AVAILABLE'
    assert result['top200']['status']=='PUBLISHED_TOP200' and result['history']['status']=='CANNOT_CONFIRM'
    assert result['history_view']['status']=='NOT_RUN_HISTORY_INCOMPLETE' and 'f10' not in result
    assert Path(old['path']).read_bytes()==old_bytes


@pytest.mark.parametrize('failure',[ValueError('HISTORY_SOURCE_DRIFT'),ValueError('HISTORY_PRIOR_RECEIPT_IDENTITY_CONFLICT'),FileNotFoundError('untyped other input missing')])
def test_other_failures_remain_closed_without_top200(tmp_path,monkeypatch,failure):
    root,receipt_root,calls=continuation(tmp_path,monkeypatch,failure)
    result=top.complete_daily_derivatives(tmp_path,20261105,root,receipt_root,tmp_path)
    assert result['status']=='CANNOT_CONFIRM' and calls==['history'] and 'top200'not in result


def test_complete_history_keeps_existing_complete_and_f10_path(tmp_path,monkeypatch):
    root,receipt_root,calls=continuation(tmp_path,monkeypatch,{'status':'COMPLETE_NO_HISTORY_GAPS'})
    result=top.complete_daily_derivatives(tmp_path,20261105,root,receipt_root,tmp_path)
    assert result['status']=='COMPLETE_DESCRIPTIVE_NONPIT'
    assert calls==['history','history_view','build','stage','publish','f10','f10_publish']
