"""Projection glue tests; frozen R5/statistics tests are deliberately not repeated."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pytest
from unittest.mock import patch
from types import SimpleNamespace

from ops import research_panel_daily_product as product

class ProjectionGlueTests(unittest.TestCase):
 def context(self, root):
  bars=[dict(trade_date=d,open='10',high='11',low='9',close='10',vol='100') for d in (20261026,20261027,20261028,20261029)]
  return SimpleNamespace(root=root,target=20261029,calendars={'SH':[20261026,20261027,20261028,20261029,20261030,20261102,20261103,20261104,20261105]},generation='a'*64,identity={'input_sha256':'b'*64},config={'formula':{'sha256':'c'*64}},read=lambda s:(copy.deepcopy(bars),None),qualify=lambda s:{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH','history_start_date':'20261026'})
 def test_historical_slices_are_recomputed_and_not_borrowed(self):
  with tempfile.TemporaryDirectory() as td:
   ctx=self.context(Path(td)); calls=[]
   def inputs(c,s,bars,day,q):
    calls.append((day,[b['trade_date'] for b in bars]));return dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
   def evaluate(**kw):
    return {'groups':{g:{'status':'TRUE' if kw['asof']==20261027 else 'UNKNOWN','anchor_date':20261026,'reasons':[]} for g in product.GROUPS}}
   with patch.object(product,'source_inputs',inputs):row,cache,path=product.compute_stock(ctx,'600025.SH',evaluate=evaluate,history_dates=[20261026,20261027,20261028])
   self.assertEqual(calls,[(20261029,[20261026,20261027,20261028,20261029]),(20261026,[20261026]),(20261027,[20261026,20261027]),(20261028,[20261026,20261027,20261028])])
   self.assertTrue(row['historical_coverage']['known_full_history']);self.assertFalse(row['historical_coverage']['historical_PIT'])
   self.assertEqual(row['statistics']['price_distribution']['all_history']['n'],4)
   self.assertEqual(row['statistics']['groups'][0]['eligible_event_count'],1)
 def test_revised_prefix_invalidates_old_events(self):
  with tempfile.TemporaryDirectory() as td:
   ctx=self.context(Path(td));rule=product.sha(Path(product.__file__).parents[1]/'domains/research_daily_product.py');cachefile=Path(td)/'history'/rule/'600025.SH/checkpoint.json'
   product.save(cachefile,dict(evaluations={'20261026':{'groups':{g:'TRUE' for g in product.GROUPS}}},prefix_sha256='bad'))
   def evaluate(**kw):return {'groups':{g:{'status':'UNKNOWN','reasons':[]} for g in product.GROUPS}}
   with patch.object(product,'source_inputs',return_value=dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status='UNKNOWN',raw_g4_reference=None)):
    row,cache,_=product.compute_stock(ctx,'600025.SH',evaluate=evaluate)
   self.assertTrue(cache['invalidated_previous_source']);self.assertNotIn('20261026',cache['evaluations'])
 def test_pin_drift_and_immutable_restart_failclosed(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'x.json';ref=product.save(p,{'x':1},immutable=True);self.assertEqual(product.checked(ref),p.resolve())
   product.save(p,{'x':1},immutable=True)
   with self.assertRaisesRegex(ValueError,'IMMUTABLE'):product.save(p,{'x':2},immutable=True)
   p.write_text('changed')
   with self.assertRaisesRegex(ValueError,'PIN_DRIFT'):product.checked(ref)

if __name__=='__main__':unittest.main()

class ProductReaderTests(unittest.TestCase):
 def test_partial_product_chain_and_independent_event(self):
  from infrastructure.research_lane_source import ResearchLaneSource
  with tempfile.TemporaryDirectory() as td:
   base=Path(td).resolve();root=base/'daily_products/a_share';source=ResearchLaneSource(base,a_share_daily_root=base)
   row=product.save(root/'stock.json',dict(symbol='600025.SH',data_date='20261029',statistics={},**product.FLAGS))
   artifact=product.save(root/'product.json',dict(schema_version=product.SCHEMA,data_date='20261029',source_generation='a'*64,source_identity={'input_sha256':'b'*64},sample_only=False,processed_count=2,source_universe_count=2,row_refs={'600025.SH':row},rows=[],**product.FLAGS))
   manifest=dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date='20261029',source_generation='a'*64,input_sha256='b'*64,sample_only=False,processed_count=2,source_universe_count=2,status='PARTIAL_WITH_ROWS',artifact=artifact,**product.FLAGS)
   ref=product.save(root/'manifest.json',manifest);product.save(root/'index.json',dict(dates={'20261029':ref},latest_date='20261029'))
   event=dict(schema_version='v4.a_share.daily_completion.v1',event_id='e'*64,manifest=ref,artifact=artifact,data_date='20261029',source_generation='a'*64,input_sha256='b'*64,processed_count=2,source_universe_count=2,status='PARTIAL_WITH_ROWS',**product.FLAGS)
   product.save(root/'events/latest.json',event)
   self.assertEqual(source.read_a_daily_product(symbol='600025.SH')['row']['symbol'],'600025.SH')
   self.assertEqual(source.read_a_daily_latest_event()['event_id'],'e'*64)
   self.assertIsNone(source.read_latest_event())
   changed=dict(event,source_generation='wrong');product.save(root/'events/latest.json',changed)
   with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):source.read_a_daily_latest_event()
 def test_sample_product_is_not_publishable(self):
  from infrastructure.research_lane_source import ResearchLaneSource
  with tempfile.TemporaryDirectory() as td:
   base=Path(td).resolve();root=base/'daily_products/a_share';source=ResearchLaneSource(base,a_share_daily_root=base)
   artifact=product.save(root/'product.json',dict(schema_version=product.SCHEMA,data_date='20261029',source_generation='a',source_identity={},sample_only=True,processed_count=1,**product.FLAGS))
   ref=product.save(root/'manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date='20261029',source_generation='a',artifact=artifact,sample_only=True,processed_count=1,**product.FLAGS));product.save(root/'index.json',dict(dates={'20261029':ref},latest_date='20261029'))
   with self.assertRaisesRegex(ValueError,'COVERAGE_CONFLICT'):source.read_a_daily_product()

class NativeReaderSchemaTests(unittest.TestCase):
 def test_string_date_filter_matches_current_native_schema(self):
  observed={}
  class Empty:
   empty=True
   def sort_values(self,*a,**kw):return self
  def read(**kw):observed.update(kw);return Empty()
  context=product.SourceContext.__new__(product.SourceContext);context.target=20261029;context.panel=Path('/bound/panel');context.reader=SimpleNamespace(load_selector_ready=read)
  self.assertEqual(context.read('600025.SH'),([],None));self.assertEqual(observed['filters'],[('ts_code','=','600025.SH'),('trade_date','<=','20261029')])

class G4BlockReadTests(unittest.TestCase):
 def test_each_md1_member_is_read_once_not_once_per_symbol(self):
  import struct
  from unittest.mock import patch
  import sys,types
  official_daily_package=types.ModuleType("ops._a_share_daily_sync_parts.official_daily_package");official_daily_package.parse_package=lambda *a:None
  with tempfile.TemporaryDirectory() as td:
   package=Path(td).resolve()/'package.zip';package.write_bytes(b'pinned fixture')
   parsed={};blocks={};reads=[]
   for market,prefix in [(0,'sz'),(1,'sh'),(2,'bj')]:
    name=prefix+'.md1';block=bytearray(1024);struct.pack_into('<d',block,4,9.5);struct.pack_into('<d',block,516,10.5);blocks[name]=bytes(block)
    for i,code in enumerate(['000001','000002']):parsed[(market,code)]=({'open':10,'high':11,'low':9,'close':10},{'md1_member':{'name':name},'md1_byte_offset':i*512},100)
   class Zip:
    def __init__(self,p):pass
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,name):reads.append(name);return blocks[name]
   context=product.SourceContext.__new__(product.SourceContext);context.config={'dated_g4_packages':{'20261029':product.reference(package)}};context._g4={}
   with patch.dict(sys.modules,{'ops._a_share_daily_sync_parts.official_daily_package':official_daily_package}),patch.object(official_daily_package,'parse_package',return_value=(parsed,{})),patch.object(product.zipfile,'ZipFile',Zip):
    first=context.g4_reference('000001.SZ',20261029,{});second=context.g4_reference('000002.BJ',20261029,{})
   self.assertEqual(sorted(reads),['bj.md1','sh.md1','sz.md1']);self.assertEqual(first['prev_close'],9.5);self.assertEqual(second['prev_close'],10.5)

class FullMaterializerOutputTests(unittest.TestCase):
 def test_research_output_complete_scope_and_restart_no_recompute(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();default=root/'must_remain_absent';output=root/'research_output';calls=[]
   context=SimpleNamespace(root=default,target=20261029,scope=['600025.SH','000878.SZ','920005.BJ'],identity={'input_sha256':'b'*64},generation='a'*64,config_ref={'path':'config','sha256':'c'*64},snapshot_ref={'path':'snapshot','sha256':'d'*64},unchanged=lambda:None)
   def compute(c,s,**kw):
    calls.append(s);status='UNKNOWN' if s.endswith('.BJ') else 'TRUE';row=dict(symbol=s,display_name=None,data_date='20261029',groups='original' if status=='TRUE' else '',pending_groups='original' if status=='UNKNOWN' else '',evaluation={'groups':{g:{'status':status if g=='original' else 'FALSE'} for g in product.GROUPS}})
    return row,{},output/'history'/(s+'.json')
   with patch.object(product,'SourceContext',return_value=context),patch.object(product,'compute_stock',side_effect=compute):
    first=product.materialize_daily_product(data_root='/read-only',target=20261029,output_root=output)
    second=product.materialize_daily_product(data_root='/read-only',target=20261029,output_root=output)
   self.assertEqual(len(calls),3);self.assertEqual(first,second);self.assertFalse(default.exists())
   payload=json.loads(Path(first['artifact']['path']).read_text());self.assertFalse(payload['sample_only']);self.assertEqual(payload['processed_count'],3);self.assertEqual(payload['source_universe_count'],3);self.assertEqual(payload['unique_count'],2);self.assertEqual(payload['unknown_count'],1)


def test_actual_executor_new_reuse_and_failed_source_share_same_derivative_stage(monkeypatch,tmp_path):
 import ast,dataclasses,os
 from typing import Any
 from types import SimpleNamespace,MethodType
 path=Path(__file__).resolve().parents[1]/'infrastructure/scheduling/executor_registry.py';tree=ast.parse(path.read_bytes())
 error=next(node for node in tree.body if isinstance(node,ast.ClassDef)and node.name=='WorkloadExecutionError')
 cls=next(node for node in tree.body if isinstance(node,ast.ClassDef)and node.name=='FixedExecutorRegistry')
 method=next(node for node in cls.body if isinstance(node,ast.FunctionDef)and node.name=='_run_a_daily')
 scope=dict(__name__=__name__,dataclass=dataclasses.dataclass,Any=Any,os=os,Path=Path)
 exec(compile(ast.fix_missing_locations(ast.Module(body=[error,method],type_ignores=[])),str(path),'exec'),scope)
 WorkloadExecutionError=scope['WorkloadExecutionError']
 import ops.research_panel_top200 as continuation
 calls=[];executor=SimpleNamespace();executor._run_a_daily=MethodType(scope['_run_a_daily'],executor)
 for key in ['V4_A_SHARE_DAILY_PRODUCT_ROOT','V4_RESEARCH_PANEL_A_DATA_ROOT','V4_RESEARCH_PANEL_RECEIPT_ROOT','V4_WORKBENCH_CLASSIFICATION_ROOT']:monkeypatch.setenv(key,str(tmp_path))
 request=SimpleNamespace(mode=SimpleNamespace(value='LIVE'),business_date='20261102',slot='1540')
 monkeypatch.setattr(continuation,'complete_daily_derivatives',lambda *args:(calls.append(args)or dict(status='CANNOT_CONFIRM' if args[5] is not None else 'COMPLETE_DESCRIPTIVE_NONPIT')))
 for source in [dict(status='SUCCEEDED',migration_reuse=False),dict(status='SUCCEEDED',migration_reuse=True)]:
  executor._run_a_daily_source=lambda request:source
  result=executor._run_a_daily(request)
  assert result['migration_reuse']==source['migration_reuse'] and result['daily_derivatives']['status']=='COMPLETE_DESCRIPTIVE_NONPIT'
 assert len(calls)==2 and all(args[1]==20261102 for args in calls)
 def failed(request):raise WorkloadExecutionError(dict(status='FAILED',exit_code=1,reason='SOURCE_FAILED'))
 executor._run_a_daily_source=failed
 with __import__('pytest').raises(WorkloadExecutionError)as captured:executor._run_a_daily(request)
 assert captured.value.result['status']=='FAILED' and captured.value.result['daily_derivatives']['status']=='CANNOT_CONFIRM'
 assert len(calls)==3
 executor._run_a_daily_source=lambda request:dict(status='FAILED',reason='A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY')
 executor._run_a_daily(request);assert len(calls)==3


def test_automatic_source_failure_saves_exact_date_without_reusing_another_day(monkeypatch,tmp_path):
 import ops.research_panel_top200 as continuation
 import ops.research_panel_daily_product as owner
 import pytest
 calls=[]
 monkeypatch.setattr(owner,'SourceContext',lambda *args:(_ for _ in ()).throw(ValueError('DAILY_PAIRED_GENERATION_OR_DATE_CONFLICT')))
 monkeypatch.setattr(continuation,'record_daily_attempt',lambda root,receipt:(calls.append(receipt.copy())or dict(path='/attempt',sha256='a'*64)))
 result=continuation.complete_daily_derivatives(tmp_path,20261102,tmp_path/'products',tmp_path,tmp_path)
 assert result['status']=='CANNOT_CONFIRM' and result['data_date']=='20261102'
 assert calls[0]['error']=='DAILY_PAIRED_GENERATION_OR_DATE_CONFLICT'
 assert 'history' not in result and 'top200' not in result
 assert __import__('json').loads((tmp_path/'products/continuations/20261102/latest_receipt.json').read_bytes())['data_date']=='20261102'


def test_same_day_generation_change_reuses_pinned_formula_result_and_rejects_changed_prefix(monkeypatch):
    import json,copy
    from types import SimpleNamespace
    from ops.research_daily_product_parallel import retained_same_day_formula
    from ops.bootstrap_stock_event_history import load,retained_sample
    from pathlib import Path
    batch=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1/execution/history64')
    if not batch.exists():__import__('pytest').skip('Frozen Mac retained source unavailable')
    contract=json.loads((batch/'CONTRACT.json').read_bytes())
    from ops import bootstrap_stock_event_history as adapter
    monkeypatch.setattr(adapter,'TARGET',20261030)
    root=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share')
    calendar=load(contract['refs']['calendar'])['dates'];config=load(contract['refs']['source_config'])
    for symbol in ['000035.SZ','600118.SH','920101.BJ']:
        entry=contract['entries'][symbol];projection=load(entry['projection']);_,bars=retained_sample(projection,load(entry['source_cache']))
        identity={**contract['source_identity'],'generation':'f'*64}
        context=SimpleNamespace(root=root,target=20261030,config_ref=contract['refs']['source_config'],config=config,identity=identity,calendars=calendar)
        result,reuse=retained_same_day_formula(context,symbol,bars)
        assert result==projection['formula_result'] and reuse['formula_engine_compute_calls']==0
        revised=copy.deepcopy(bars);revised[-1]['close']='0.01'
        assert retained_same_day_formula(context,symbol,revised) is None
        context.calendars=copy.deepcopy(calendar);context.calendars[symbol[-2:]]=calendar[symbol[-2:]][:-1]
        assert retained_same_day_formula(context,symbol,bars) is None


def test_failed_same_date_source_cannot_relabel_an_old_same_date_product_complete(monkeypatch,tmp_path):
    import ops.research_panel_top200 as continuation
    import ops.research_panel_daily_product as owner
    def forbidden(*args):raise AssertionError('FAILED_SOURCE_MUST_NOT_READ_OLD_PAIRED_PRODUCT')
    monkeypatch.setattr(owner,'SourceContext',forbidden)
    monkeypatch.setattr(continuation,'record_daily_attempt',lambda root,receipt:dict(path='/attempt',sha256='a'*64))
    result=continuation.complete_daily_derivatives(tmp_path,20261030,tmp_path,tmp_path,tmp_path,dict(status='FAILED',reason='NEW_REVISION_NOT_COMMITTED'))
    assert result['status']=='CANNOT_CONFIRM' and result['error']=='UPSTREAM_DAILY_SOURCE_FAILED:NEW_REVISION_NOT_COMMITTED'


@pytest.fixture
def paired_reuse_executor(monkeypatch,tmp_path):
    """Actual two executor methods, isolated valid-source preconditions only."""
    import ast,dataclasses,hashlib,json,os,sys,types
    from types import SimpleNamespace,MethodType
    from typing import Any
    from datetime import datetime
    import ops.research_panel_daily_product as owner
    import ops.research_panel_top200 as continuation
    path=Path(__file__).resolve().parents[1]/'infrastructure/scheduling/executor_registry.py';tree=ast.parse(path.read_bytes())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='FixedExecutorRegistry')
    error=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='WorkloadExecutionError')
    methods=[next(n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name==name)for name in ['_run_a_daily','_run_a_daily_source']]
    scope=dict(__name__=__name__,dataclass=dataclasses.dataclass,Any=Any,os=os,Path=Path,json=json,hashlib=hashlib,shanghai_now=lambda:datetime(2026,10,30,16,10),_read_exact_dated_receipt=lambda *a,**kw:({'row_count':100},None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[error,*methods],type_ignores=[])),str(path),'exec'),scope)
    receipts=types.ModuleType('ops.macos_research_panel_daily_receipts');receipts.validate_a_receipt=lambda *a,**kw:'PARTIAL_WITH_ROWS'
    gate=types.ModuleType('ops.macos_research_panel_daily_gate');gate.selector_pointer_is_ready=lambda *a:True
    monkeypatch.setitem(sys.modules,'ops.macos_research_panel_daily_receipts',receipts);monkeypatch.setitem(sys.modules,'ops.macos_research_panel_daily_gate',gate)
    for key in ['V4_A_SHARE_DAILY_PRODUCT_ROOT','V4_RESEARCH_PANEL_A_DATA_ROOT','V4_RESEARCH_PANEL_RECEIPT_ROOT','V4_WORKBENCH_CLASSIFICATION_ROOT','V4_RESEARCH_PANEL_A_SELECTOR_POINTER','V4_RESEARCH_PANEL_A_BACKTEST_POINTER']:monkeypatch.setenv(key,str(tmp_path))
    (tmp_path/'a-20261030.json').write_text('{}')
    from ops.research_panel_daily_product import save
    from ops import research_panel_qfq as qfq
    snapshot=save(tmp_path/'snapshot.json',{})
    identity=dict(generation='a'*64,input_sha256='b'*64,snapshot=snapshot,selector_artifact_sha256='c'*64,asof=20261030,basis={'price_basis':'QFQ_ASOF'},historical_PIT=False)
    paired=dict(row_count=100,selector=str(tmp_path/'selector.parquet'),selector_sha256=identity['selector_artifact_sha256'],backtest=str(tmp_path/'backtest.parquet'),formula={'authority':{'generation_id':identity['generation'],'source_sha256':identity['input_sha256']}})
    footer=dict(asof_date=20261030,generation_id=identity['generation'],input_sha256=identity['input_sha256'],adjustment_snapshot=snapshot,snapshot_file_sha256=snapshot['sha256'],market_basis={'A':identity['basis']})
    selector_pointer=tmp_path/'selector.txt';backtest_pointer=tmp_path/'backtest.txt';selector_pointer.write_text(paired['selector']);backtest_pointer.write_text(paired['backtest'])
    monkeypatch.setenv('V4_RESEARCH_PANEL_A_SELECTOR_POINTER',str(selector_pointer));monkeypatch.setenv('V4_RESEARCH_PANEL_A_BACKTEST_POINTER',str(backtest_pointer))
    scope['_read_exact_dated_receipt']=lambda *a,**kw:(paired,None)
    monkeypatch.setattr(qfq,'panel_contract',lambda path:footer.copy())
    executor=SimpleNamespace(_active_workload_id='preserve-owner')
    for method in methods:setattr(executor,method.name,MethodType(scope[method.name],executor))
    executor._research_panel_daily=lambda *a,**kw:pytest.fail('READY paired source must never collect/regenerate source')
    calls=[]
    monkeypatch.setattr(continuation,'complete_daily_derivatives',lambda *args:(calls.append(('derivatives',args))or dict(status='CANNOT_CONFIRM'if args[5]is not None else'COMPLETE_DESCRIPTIVE_NONPIT')))
    root=tmp_path/'daily_products/a_share'
    def saved():
        from ops.research_panel_daily_product import save
        artifact=save(tmp_path/'product.json',dict(data_date='20261030',sample_only=False,status='PARTIAL_WITH_ROWS',source_identity=identity,source_generation=identity['generation'],rows=[{'symbol':'600025.SH'}]))
        manifest=save(tmp_path/'manifest.json',dict(artifact=artifact,source_generation=identity['generation'],input_sha256=identity['input_sha256'],snapshot=identity['snapshot']))
        asset=save(tmp_path/'asset.json',{})
        chart=save(tmp_path/'chart.json',dict(samples={'600025.SH':{key:asset for key in ('html','PNG','projection')}}))
        receipt=save(tmp_path/'chart_receipt.json',dict(status='OWNER_CHARTS_COMPLETED'))
        save(root/'index.json',dict(dates={'20261030':manifest},original_charts={'20261030':dict(numeric_manifest=manifest,manifest=chart,receipt=receipt)}))
        return dict(status='PARTIAL_WITH_ROWS',manifest=manifest)
    def materialize(**kwargs):
        calls.append(('materialize',kwargs))
        assert kwargs==dict(data_root=str(tmp_path),target=20261030,output_root=root)
        return saved()
    monkeypatch.setattr(owner,'materialize_daily_product',materialize)
    return SimpleNamespace(executor=executor,request=SimpleNamespace(mode=SimpleNamespace(value='LIVE'),business_date='20261030',slot='1610'),scope=scope,calls=calls,saved=saved,root=root,owner=owner,error=scope['WorkloadExecutionError'],identity=identity,paired=paired,footer=footer,selector_pointer=selector_pointer,backtest_pointer=backtest_pointer)


@pytest.mark.parametrize('missing',['index','date','product','chart_descriptor','chart_manifest','chart_receipt_partial'])
def test_paired_source_retry_recovers_only_missing_original_numeric_chart_leaf(paired_reuse_executor,missing):
    import json
    f=paired_reuse_executor
    if missing!='index':f.saved()
    if missing=='date':
        index=json.loads((f.root/'index.json').read_bytes());index['dates']={};(f.root/'index.json').write_text(json.dumps(index))
    elif missing=='product':(f.root.parents[1]/'product.json').unlink()
    elif missing=='chart_descriptor':
        index=json.loads((f.root/'index.json').read_bytes());index.pop('original_charts');(f.root/'index.json').write_text(json.dumps(index))
    elif missing=='chart_manifest':(f.root.parents[1]/'chart.json').unlink()
    elif missing=='chart_receipt_partial':
        from ops.research_panel_daily_product import save
        receipt=save(f.root.parents[1]/'partial.json',{'status':'OWNER_CHARTS_PARTIAL'})
        index=json.loads((f.root/'index.json').read_bytes());index['original_charts']['20261030']['receipt']=receipt;(f.root/'index.json').write_text(json.dumps(index))
    answer=f.executor._run_a_daily(f.request)
    assert [kind for kind,_ in f.calls]==['materialize','derivatives']
    assert answer['provider_invoked'] is False and answer['source_recomputed'] is False
    assert answer['original_chart_leaf']['recovered_by_original_materializer'] is True
    assert answer['daily_derivatives']['status']=='COMPLETE_DESCRIPTIVE_NONPIT'
    assert f.executor._active_workload_id=='preserve-owner'
    f.calls.clear();repeat=f.executor._run_a_daily(f.request)
    assert [kind for kind,_ in f.calls]==['derivatives']
    assert repeat['original_chart_leaf']['numeric_recomputed'] is False


def test_paired_source_leaf_recovery_failure_is_same_date_failure_and_not_success(paired_reuse_executor,monkeypatch):
    f=paired_reuse_executor
    def failure(**kwargs):f.calls.append(('materialize',kwargs));raise OSError('SIMULATED_MISSING_LEAF_IO_ERROR')
    monkeypatch.setattr(f.owner,'materialize_daily_product',failure)
    with pytest.raises(f.error)as caught:f.executor._run_a_daily(f.request)
    value=caught.value.result
    assert value['status']=='FAILED' and value['target_date']=='20261030' and value['lane_status']=='PARTIAL_WITH_ROWS'
    assert value['provider_invoked'] is False and value['daily_derivatives']['status']=='CANNOT_CONFIRM'
    assert value['reason']=='A_DAILY_PRODUCT_LEAF_RECOVERY_FAILED'
    assert 'SIMULATED_MISSING_LEAF_IO_ERROR' in value['original_chart_leaf']['reason']
    assert not (f.root/'index.json').exists()


@pytest.mark.parametrize('moment',[(2026,10,30,15,39),(2026,10,30,17,0),(2026,10,31,9,0)])
def test_paired_source_outside_window_skips_both_materializer_and_derivatives(paired_reuse_executor,moment):
    from datetime import datetime
    f=paired_reuse_executor;f.scope['shanghai_now']=lambda:datetime(*moment)
    answer=f.executor._run_a_daily(f.request)
    assert f.calls==[] and answer['reason']=='A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY'
    assert answer['original_chart_leaf']['reason']=='A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY'
    assert answer['daily_derivatives']['status']=='SKIPPED_OUTSIDE_WINDOW'
    assert answer['natural_1540_verified'] is False and not (f.root/'index.json').exists()


@pytest.mark.parametrize('component',['generation','input_sha256','selector_artifact_sha256','snapshot'])
def test_paired_source_new_identity_recovers_stale_complete_same_day_leaf(paired_reuse_executor,component):
    import copy
    from ops.research_panel_daily_product import save
    f=paired_reuse_executor;f.saved()
    original_product=(f.root.parents[1]/'product.json').read_bytes()
    if component=='snapshot':f.identity[component]=save(f.root.parents[1]/'new_snapshot.json',{'revised':True})
    else:f.identity[component]='e'*64
    f.paired['selector_sha256']=f.identity['selector_artifact_sha256']
    f.paired['formula']['authority'].update(generation_id=f.identity['generation'],source_sha256=f.identity['input_sha256'])
    f.footer.update(generation_id=f.identity['generation'],input_sha256=f.identity['input_sha256'],adjustment_snapshot=f.identity['snapshot'],snapshot_file_sha256=f.identity['snapshot']['sha256'])
    # Leave every old product/chart byte intact until the real-owner entry is
    # invoked; changing metadata alone in saved_leaf cannot satisfy this case.
    assert (f.root.parents[1]/'product.json').read_bytes()==original_product
    answer=f.executor._run_a_daily(f.request)
    assert [kind for kind,_ in f.calls]==['materialize','derivatives']
    assert answer['original_chart_leaf']['recovered_by_original_materializer'] is True
    assert answer['daily_derivatives']['status']=='COMPLETE_DESCRIPTIVE_NONPIT'
    current=__import__('json').loads((f.root.parents[1]/'product.json').read_bytes())
    assert current['source_identity']==f.identity
    f.calls.clear();f.executor._run_a_daily(f.request)
    assert [kind for kind,_ in f.calls]==['derivatives']


def test_paired_source_stale_materializer_result_cannot_be_rebound_or_reported_success(paired_reuse_executor,monkeypatch):
    f=paired_reuse_executor;f.saved();before=(f.root.parents[1]/'product.json').read_bytes()
    f.identity['generation']='e'*64
    f.paired['formula']['authority']['generation_id']=f.identity['generation'];f.footer['generation_id']=f.identity['generation']
    def incomplete(**kwargs):f.calls.append(('materialize',kwargs));return {'status':'PARTIAL_WITH_ROWS'}
    monkeypatch.setattr(f.owner,'materialize_daily_product',incomplete)
    with pytest.raises(f.error)as caught:f.executor._run_a_daily(f.request)
    value=caught.value.result
    assert value['status']=='FAILED' and value['target_date']=='20261030' and value['reason']=='A_DAILY_PRODUCT_LEAF_RECOVERY_FAILED'
    assert 'CURRENT_PAIRED_IDENTITY_CONFLICT' in value['original_chart_leaf']['reason']
    assert value['daily_derivatives']['status']=='CANNOT_CONFIRM'
    assert (f.root.parents[1]/'product.json').read_bytes()==before

@pytest.fixture(scope='module')
def actual_exact_typed_end_context():
    import os,json,plistlib
    from unittest.mock import patch
    from ops.research_panel_daily_product import SourceContext
    b=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1')
    path=b/'execution/current_binding_r10/TYPED_METADATA_FACT_V2.json'
    if not path.exists():pytest.skip('Actual exact D30 typed RAW end evidence not available')
    config=plistlib.loads((Path.home()/'Library/LaunchAgents/com.lexi.v4.scheduler.plist').read_bytes())['EnvironmentVariables']['V4_RESEARCH_DAILY_PRODUCT_CONFIG']
    from ops.research_panel_daily_product import sha
    with patch.dict(os.environ,{'V4_RESEARCH_DAILY_PRODUCT_CONFIG':config,'V4_A_DAILY_TYPED_END_FACT_PATH':str(path),'V4_A_DAILY_TYPED_END_FACT_SHA256':sha(path)}):
        context=SourceContext(Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据'),20261030)
        yield context,path


def test_exact_typed_end_actual_original_checks_and_raw_snapshot_unchanged(actual_exact_typed_end_context,monkeypatch):
    from ops.research_panel_daily_product import sha
    context,path=actual_exact_typed_end_context
    monkeypatch.setattr(context,'engine',lambda:pytest.fail('Metadata admission must not compute a formula'))
    before=sha(context.snapshot_ref['path']);item=context.snapshot['symbols']['002731.SZ'];assert 'history_end_date'not in item
    original=context.helper.verify_symbol_admission('002731.SZ','20261030',context.footer,context.receipt,context.quarantine,context.generation,Path(context.quarantine_ref['path']))
    assert original=={'status':'UNKNOWN','reason':'CURRENT_SYMBOL_HISTORY_END_MISMATCH'}
    result=context.qualify('002731.SZ')
    assert result['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
    assert result['history_end_date']=='20261030'and result['history_end_metadata']['effective_date_is_derived']
    assert result['history_end_metadata']['original_admission']==original
    assert result['verified_raw_sources']and result['verified_acceptance_references']
    assert sha(context.snapshot_ref['path'])==before and 'history_end_date'not in item


@pytest.mark.parametrize('mutation',['symbol','date','snapshot','native','pairedref','pairedvalue','evidence_sha','helper_ast','resolved_count'])
def test_exact_typed_end_rejects_changed_fact(actual_exact_typed_end_context,tmp_path,monkeypatch,mutation):
    import json,copy
    from ops.research_panel_daily_product import sha
    context,path=actual_exact_typed_end_context;proof=json.loads(path.read_bytes())
    if mutation=='symbol':proof['symbol']='002732.SZ'
    elif mutation=='date':proof['target_date']=20261029
    elif mutation=='snapshot':proof['snapshot']['sha256']='0'*64
    elif mutation=='native':proof['native']['sha256']='0'*64
    elif mutation=='pairedref':proof['paired_roles']['selector']['sha256']='0'*64
    elif mutation=='pairedvalue':proof['paired_roles']['selector']['target_row']['close']=1.
    elif mutation=='helper_ast':proof['helper_function_ast_sha256']='0'*64
    elif mutation=='resolved_count':proof['resolved_rows']=2818
    changed=tmp_path/'fact.json';changed.write_text(json.dumps(proof))
    monkeypatch.setenv('V4_A_DAILY_TYPED_END_FACT_PATH',str(changed));monkeypatch.setenv('V4_A_DAILY_TYPED_END_FACT_SHA256','0'*64 if mutation=='evidence_sha'else sha(changed))
    with pytest.raises(ValueError):context.qualify('002731.SZ')


def test_exact_typed_end_present_conflicting_metadata_is_not_replaced(actual_exact_typed_end_context,monkeypatch):
    context,_=actual_exact_typed_end_context;monkeypatch.setitem(context.snapshot['symbols']['002731.SZ'],'history_end_date',20261029)
    assert context.qualify('002731.SZ')=={'status':'UNKNOWN','reason':'CURRENT_SYMBOL_HISTORY_END_MISMATCH'}


@pytest.mark.parametrize('mutation,reason',[('target_set','SYMBOL_ABSENT_FROM_CURRENT_PRODUCER_TARGET_SET'),('raw_sha','CURRENT_SYMBOL_RAW_SOURCE_HASH_MISMATCH'),('archive_sha','CURRENT_SYMBOL_ARCHIVE_MEMBER_HASH_CONFLICT'),('raw_absent','CURRENT_SYMBOL_RAW_SOURCES_MISSING'),('accept_sha','CURRENT_SYMBOL_ACCEPTANCE_REFERENCE_HASH_MISMATCH'),('accept_absent','CURRENT_SYMBOL_ACCEPTANCE_REFERENCES_MISSING')])
def test_exact_typed_end_retains_all_original_checks_after_date(actual_exact_typed_end_context,mutation,reason):
    import copy,json
    from types import SimpleNamespace
    from ops.research_panel_daily_product import _exact_typed_end_validator
    context,path=actual_exact_typed_end_context;proof=json.loads(path.read_bytes());snapshot=copy.deepcopy(context.snapshot);item=snapshot['symbols']['002731.SZ']
    if mutation=='target_set':snapshot['original_target_codes'].remove('002731.SZ')
    elif mutation=='raw_sha':item['raw_files'][0]['sha256']='0'*64
    elif mutation=='archive_sha':item['raw_files'][0]['original_ref']={'member_sha256':'0'*64}
    elif mutation=='raw_absent':item['raw_files']=[]
    elif mutation=='accept_sha':item['accepted_evidence']=[{'path':proof['producer_receipt']['path'],'sha256':'0'*64}]
    elif mutation=='accept_absent':
        for key in ['accepted_evidence','source_config','source_policy']:item.pop(key,None)
    helper=SimpleNamespace(**context.helper.__dict__);helper.read_json=lambda p:snapshot
    validator=_exact_typed_end_validator(helper,context.config['admission_helper'],proof,derive_references=mutation!='accept_absent')
    result=validator('002731.SZ','20261030',context.footer,context.receipt,context.quarantine,context.generation,Path(context.quarantine_ref['path']))
    assert result['status']=='UNKNOWN'and result['reason']==reason

@pytest.mark.parametrize('mutation',['symbol','date','source_row','capture_other_stock','data_evidence_sha','empty_refs'])
def test_exact_typed_end_rejects_inapplicable_source_data_references(actual_exact_typed_end_context,tmp_path,monkeypatch,mutation):
    import json
    from ops.research_panel_daily_product import sha
    context,path=actual_exact_typed_end_context;proof=json.loads(path.read_bytes());source=json.loads(Path(proof['accepted_evidence'][0]['path']).read_bytes())
    if mutation=='symbol':source['symbol']='920002.BJ'
    elif mutation=='date':source['target_date']=20261029
    elif mutation=='source_row':source['original_source_row_sha256']='0'*64
    elif mutation=='capture_other_stock':
        other=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1/execution/source44/tdx_pair3/raw_responses/20261030/920003.BJ/aef154747d8e112ac27bffb71d7b29ceda61c5006713e692f0b691d8e051c972.json')
        source['original_capture']={'path':str(other),'sha256':sha(other)}
    elif mutation=='data_evidence_sha':source['original_source_admission']['sha256']='0'*64
    changed=tmp_path/'source_refs.json';changed.write_text(json.dumps(source));proof['accepted_evidence']=[]if mutation=='empty_refs'else[{'path':str(changed),'sha256':sha(changed)}]
    fact=tmp_path/'fact.json';fact.write_text(json.dumps(proof));monkeypatch.setenv('V4_A_DAILY_TYPED_END_FACT_PATH',str(fact));monkeypatch.setenv('V4_A_DAILY_TYPED_END_FACT_SHA256',sha(fact))
    with pytest.raises(ValueError):context.qualify('002731.SZ')


@pytest.mark.parametrize('field',['accepted_evidence','source_config','source_policy'])
def test_exact_typed_end_present_invalid_original_reference_is_not_overridden(actual_exact_typed_end_context,monkeypatch,field):
    context,path=actual_exact_typed_end_context;bad={'path':str(path),'sha256':'0'*64}
    monkeypatch.setitem(context.snapshot['symbols']['002731.SZ'],field,[bad]if field=='accepted_evidence'else bad)
    result=context.qualify('002731.SZ')
    assert result['status']=='UNKNOWN'and result['reason']=='CURRENT_SYMBOL_ACCEPTANCE_REFERENCE_HASH_MISMATCH'
