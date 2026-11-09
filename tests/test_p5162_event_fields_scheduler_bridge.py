"""Exercise the active 7e99 scheduler body against the real cached owner seam."""
import ast
import importlib
import importlib.util
import json
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import materialize_p5162_event_fields as adapter
from test_p5162_event_fields import SYMBOL, source_row, bar, CAL


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT/'docs/handoffs/p5162_event_fields_daily_20261109/scheduler_runtime_bridge.patch'
BASE_SHA = '6f848524e991ccb3631cb56927d3beb7361f6ee8882a2eceea5b8a58903bcf4f'
AFTER_SHA = '70b5483c0ca012f6a0293e06ae67436d2f370c38cda55b72f82d97fbd9d7b185'


def bridge_applicator():
    spec=importlib.util.spec_from_file_location('p5162_scheduler_bridge_apply',PATCH.with_name('apply_scheduler_bridge.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def scheduler_method(tmp_path, namespace):
    # Apply the reviewed hunk to the exact Git blob also used by current Main.
    # Compile the real method without importing or starting the active app.
    blob = subprocess.check_output(['git','show','7e99fdc78:infrastructure/scheduling/executor_registry.py'],cwd=ROOT)
    path=tmp_path/'bridge/infrastructure/scheduling/executor_registry.py';path.parent.mkdir(parents=True);path.write_bytes(blob)
    assert adapter.sha(path)==BASE_SHA
    assert bridge_applicator().apply(tmp_path/'bridge')['before']==BASE_SHA
    assert adapter.sha(path)==AFTER_SHA
    tree=ast.parse(path.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FixedExecutorRegistry')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_run_a_daily_source')
    source=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),method],type_ignores=[])
    exec(compile(ast.fix_missing_locations(source),str(path),'exec'),namespace)
    return namespace['_run_a_daily_source']


def test_bridge_rejects_any_base_drift_without_writing(tmp_path):
    blob=subprocess.check_output(['git','show','7e99fdc78:infrastructure/scheduling/executor_registry.py'],cwd=ROOT)
    path=tmp_path/'bridge/infrastructure/scheduling/executor_registry.py';path.parent.mkdir(parents=True)
    changed=blob+b'\n';path.write_bytes(changed)
    with pytest.raises(ValueError,match='BRIDGE_BASE_SHA_DRIFT'):
        bridge_applicator().apply(tmp_path/'bridge')
    assert path.read_bytes()==changed


@pytest.mark.parametrize('drift',['algorithm','config','completion_generation','completion_input_sha'])
def test_same_day_missing_fields_calls_cached_owner_and_reuses(tmp_path,monkeypatch,drift):
    pair=types.ModuleType('ops.research_storage_pair');pair.paired_request=lambda fn:fn
    monkeypatch.setitem(sys.modules,'ops.research_storage_pair',pair)
    sys.modules.pop('ops.research_panel_daily_product',None)
    owner=importlib.import_module('ops.research_panel_daily_product')
    prefill=types.ModuleType('ops.research_daily_product_parallel');prefill.prefill_missing=lambda *a,**k:{'chart_gaps':{}}
    monkeypatch.setitem(sys.modules,'ops.research_daily_product_parallel',prefill)
    score=types.ModuleType('ops.materialize_workbench_score_action');score.materialize=lambda *a,**k:{'status':'FIXTURE'}
    monkeypatch.setitem(sys.modules,'ops.materialize_workbench_score_action',score)
    target='20261027';gen='same-generation';symbols=[SYMBOL,'000914.SZ']
    root=tmp_path/'product_root'/'daily_products/a_share';root.mkdir(parents=True)
    source=tmp_path/'source';source.mkdir();panel=source/'selector.parquet';back=source/'backtest.parquet'
    pq.write_table(pa.Table.from_pylist([bar(s,target) for s in symbols]),panel);back.write_bytes(b'backtest-fixture')
    basis={'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME','asof_date':int(target)}
    snapshot={'path':'snapshot-fixture','sha256':'f'*64}
    identity=dict(generation=gen,input_sha256='a'*64,snapshot=snapshot,selector_artifact_sha256='b'*64,
                  asof=int(target),basis=basis,historical_PIT=False)
    ctx=SimpleNamespace(root=root,target=int(target),generation=gen,identity=identity,scope=symbols,
        config_ref={'sha256':'config'},snapshot_ref=snapshot,panel=panel,calendars={'SZ':CAL},unchanged=lambda:None)
    monkeypatch.setattr(owner,'SourceContext',lambda *a:ctx)
    monkeypatch.setattr(owner,'config',lambda: ({},ctx.config_ref))
    def compute(context,symbol,**kwargs):
        row=source_row(symbol,target,gen)
        if symbol==symbols[1]:row['evaluation']['symbol']='000001.SZ'
        return row,{},root/'history'/symbol/'checkpoint.json'
    monkeypatch.setattr(owner,'compute_stock',compute)
    initial=owner.materialize_daily_product(data_root=tmp_path,target=int(target),original_charts=False)
    indexpath=root/'index.json';eventpath=root/'events/latest.json';index=json.loads(indexpath.read_bytes())
    product=adapter.checked(adapter.checked(initial['manifest'])['artifact'])
    assets={}
    for item in product['rows']:
        symbol=item['symbol'];assets[symbol]={}
        for kind in ('html','PNG','projection'):
            p=tmp_path/'chart'/symbol/kind;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(kind)
            assets[symbol][kind]={'path':str(p)}
    chart=owner.save(tmp_path/'charts.json',{'samples':assets})
    chart_receipt=owner.save(tmp_path/'chart_receipt.json',{'status':'OWNER_CHARTS_COMPLETED'})
    index['original_charts']={target:{'numeric_manifest':initial['manifest'],'manifest':chart,'receipt':chart_receipt}}
    index['p5162_event_fields'].pop(target)
    owner.save(indexpath,index)
    event=json.loads(eventpath.read_bytes());event.pop('p5162_event_fields');owner.save(eventpath,event)
    sp=tmp_path/'selector.current';bp=tmp_path/'backtest.current';sp.write_text(str(panel));bp.write_text(str(back))
    receipt_root=tmp_path/'receipts';receipt_root.mkdir();(receipt_root/('a-'+target+'.json')).write_text('{}')
    receipt={'selector':str(panel),'backtest':str(back),'selector_sha256':identity['selector_artifact_sha256'],
        'formula':{'authority':{'generation_id':gen,'source_sha256':identity['input_sha256']}},
        'row_count':2,'accepted_count':2,'quarantine_count':0,'target_count':2,'coverage_rate':1}
    for key,value in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':receipt_root,'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':sp,
        'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':bp,'V4_RESEARCH_PANEL_A_DATA_ROOT':tmp_path/'data',
        'V4_A_SHARE_DAILY_PRODUCT_ROOT':tmp_path/'product_root'}.items():monkeypatch.setenv(key,str(value))
    footer={'asof_date':int(target),'generation_id':gen,'input_sha256':identity['input_sha256'],
        'adjustment_snapshot':snapshot,'snapshot_file_sha256':snapshot['sha256'],'market_basis':{'A':basis}}
    guard=[]
    def governed(function,**kwargs):guard.append(kwargs);return function(**kwargs)
    governance=types.ModuleType('ops.research_storage_governance');governance.governed_product=governed
    monkeypatch.setitem(sys.modules,'ops.research_storage_governance',governance)
    qfq=types.ModuleType('ops.research_panel_qfq');qfq.panel_contract=lambda p:footer
    monkeypatch.setitem(sys.modules,'ops.research_panel_qfq',qfq)
    receipts=types.ModuleType('ops.macos_research_panel_daily_receipts');receipts.validate_a_receipt=lambda *a,**k:'PARTIAL_WITH_ROWS'
    monkeypatch.setitem(sys.modules,'ops.macos_research_panel_daily_receipts',receipts)
    gate=types.ModuleType('ops.macos_research_panel_daily_gate');gate.selector_pointer_is_ready=lambda *a:True
    monkeypatch.setitem(sys.modules,'ops.macos_research_panel_daily_gate',gate)
    def forbidden(*args,**kwargs):raise AssertionError('ORIGINAL_NUMERIC_OR_SCORE_MUST_NOT_RUN')
    prefill.prefill_missing=forbidden;score.materialize=forbidden;monkeypatch.setattr(owner,'compute_stock',forbidden)
    import hashlib,os
    class ExecutionError(Exception):pass
    env={'os':os,'json':json,'Path':Path,'hashlib':hashlib,'WorkloadExecutionError':ExecutionError,
         'shanghai_now':lambda:datetime(2026,10,27,15,50),
         '_read_exact_dated_receipt':lambda *a,**k:(receipt,None)}
    method=scheduler_method(tmp_path,env)
    host=SimpleNamespace(_active_workload_id='',_research_panel_daily=forbidden,_failure_result=forbidden)
    request=SimpleNamespace(mode=SimpleNamespace(value='LIVE'),slot='1540',business_date=target)
    first=method(host,request)
    assert first['status']=='SUCCEEDED' and first['provider_invoked'] is False
    assert first['original_chart_leaf']['event_fields_recovered_by_original_owner'] is True
    assert first['numeric_recomputed'] is False and guard[0]['require_cached_numeric'] is True
    descriptor=first['original_chart_leaf']['p5162_event_fields']; index=adapter.checked(descriptor['index'])
    assert descriptor['counts']['total']==2 and descriptor['counts']['source_isolated']==1
    second=method(host,request);assert second['status']=='SUCCEEDED' and len(guard)==1
    Path(index['items'][SYMBOL]['path']).unlink()
    third=method(host,request)
    assert third['status']=='SUCCEEDED' and len(guard)==2 and guard[1]['require_cached_numeric'] is True
    assert ctx._p5162_event_fields_last_run=={'computed':1,'reused':1}
    assert adapter.checked(adapter.checked(third['original_chart_leaf']['p5162_event_fields']['index'])['items'][symbols[1]])['status']=='SOURCE_ISOLATED'
    assert method(host,request)['status']=='SUCCEEDED' and len(guard)==2
    previous=third['original_chart_leaf']['p5162_event_fields']; old_index=adapter.checked(previous['index'])
    old_index_bytes=Path(previous['index']['path']).read_bytes()
    old_record_bytes=Path(old_index['items'][SYMBOL]['path']).read_bytes()
    before_index=indexpath.read_bytes();before_event=eventpath.read_bytes()
    if drift=='algorithm':
        changed={**adapter.algorithm_identity(),'domain_sha256':'changed-domain-fixture'}
        monkeypatch.setattr(adapter,'algorithm_identity',lambda:changed)
        fresh=method(host,request)
        assert fresh['status']=='SUCCEEDED' and len(guard)==3 and guard[-1]['require_cached_numeric'] is True
        fresh_index=adapter.checked(fresh['original_chart_leaf']['p5162_event_fields']['index'])
        assert fresh_index['algorithm']==changed
        assert adapter.checked(fresh_index['items'][SYMBOL])['panel_reference']==adapter.checked(old_index['items'][SYMBOL])['panel_reference']
        assert Path(previous['index']['path']).read_bytes()==old_index_bytes
        assert Path(old_index['items'][SYMBOL]['path']).read_bytes()==old_record_bytes
    else:
        if drift=='config':ctx.config_ref={'sha256':'new-config'}
        else:
            event=json.loads(before_event)
            event['source_generation' if drift=='completion_generation' else 'input_sha256']='mismatched'
            owner.save(eventpath,event)
        changed_event=eventpath.read_bytes()
        with pytest.raises(ExecutionError) as failure:method(host,request)
        reason='EVENT_FIELDS_EXISTING_SOURCE_CONFIG_CONFLICT' if drift=='config' else 'EVENT_FIELDS_EXISTING_PUBLICATION_IDENTITY_CONFLICT'
        assert reason in failure.value.args[0]['original_chart_leaf']['reason']
        assert len(guard)==3 and guard[-1]['require_cached_numeric'] is True
        assert indexpath.read_bytes()==before_index and eventpath.read_bytes()==changed_event
