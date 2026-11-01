"""Projection glue tests; frozen R5/statistics tests are deliberately not repeated."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from types import SimpleNamespace

from ops import research_panel_daily_product as product

class ProjectionGlueTests(unittest.TestCase):
 def context(self, root, extra_history=False):
  earlier=[];day=date(2026,4,1)
  while extra_history and day<date(2026,10,26):
   if day.weekday()<5:earlier.append(int(day.strftime('%Y%m%d')))
   day+=timedelta(days=1)
  dates=earlier+[20261026,20261027,20261028,20261029]
  bars=[dict(trade_date=d,open='10',high='11',low='9',close='10',vol='100') for d in dates]
  return SimpleNamespace(root=root,target=20261029,calendars={'SH':dates+[20261030,20261102,20261103,20261104,20261105]},generation='a'*64,identity={'input_sha256':'b'*64},config={'formula':{'sha256':'c'*64}},read=lambda s:(copy.deepcopy(bars),None),qualify=lambda s:{'status':'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH','history_start_date':str(dates[0])})
 def test_historical_slices_are_recomputed_and_not_borrowed(self):
  with tempfile.TemporaryDirectory() as td:
   ctx=self.context(Path(td),extra_history=True); calls=[]
   def inputs(c,s,bars,day,q):
    calls.append((day,[b['trade_date'] for b in bars]));return dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
   def evaluate(**kw):
    return {'groups':{g:{'status':'TRUE' if kw['asof']==20261027 else 'UNKNOWN','anchor_date':20261026,'reasons':[]} for g in product.GROUPS}}
   with patch.object(product,'source_inputs',inputs):row,cache,path=product.compute_stock(ctx,'600025.SH',evaluate=evaluate,history_dates=[20261026,20261027,20261028])
   self.assertEqual([day for day,_ in calls],[20261029,20261026,20261027,20261028])
   for day,prefix in calls:self.assertEqual(prefix[-1],day);self.assertGreaterEqual(len(prefix),114)
   self.assertFalse(row['historical_coverage']['known_full_history']);self.assertFalse(row['historical_coverage']['historical_PIT'])
   self.assertEqual(row['statistics']['price_distribution']['all_history']['n'],len(ctx.read('600025.SH')[0]))
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
   config=product.save(root/'config.json',{'formula':{'sha256':'c'*64}})
   identity={'generation':'a'*64,'input_sha256':'b'*64,'asof':20261029,'basis':{'price_basis':'QFQ_ASOF'}}
   binding={'generation':'a'*64,'input':'b'*64,'asof':'2026-10-29','market':'SH','formula':'c'*64,'basis':'QFQ_ASOF','rule_sha256':'d'*64}
   qualification={'symbol':'600025.SH','source_generation':'a'*64,'target_date':'20261029'}
   stats={'asof':'2026-10-29','groups':[{'identity_status':'BOUND','rule_sha256':'d'*64,'source_identity':binding}]}
   row=product.save(root/'stock.json',dict(symbol='600025.SH',data_date='20261029',statistics=stats,qualification=qualification,**product.FLAGS))
   artifact=product.save(root/'product.json',dict(schema_version=product.SCHEMA,data_date='20261029',source_generation='a'*64,source_identity=identity,source_config=config,sample_only=False,processed_count=2,source_universe_count=2,row_refs={'600025.SH':row},rows=[],**product.FLAGS))
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
   identity={'generation':'a'*64,'input_sha256':'b'*64,'asof':20261029}
   artifact=product.save(root/'product.json',dict(schema_version=product.SCHEMA,data_date='20261029',source_generation='a'*64,source_identity=identity,sample_only=True,processed_count=1,**product.FLAGS))
   ref=product.save(root/'manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date='20261029',source_generation='a'*64,input_sha256='b'*64,artifact=artifact,sample_only=True,processed_count=1,**product.FLAGS));product.save(root/'index.json',dict(dates={'20261029':ref},latest_date='20261029'))
   with self.assertRaisesRegex(ValueError,'COVERAGE_CONFLICT'):source.read_a_daily_product()

class NativeReaderSchemaTests(unittest.TestCase):
 def test_string_date_filter_matches_current_native_schema(self):
  import pandas as pd
  import pyarrow as pa
  import pyarrow.parquet as pq
  observed={}
  def read(**kw):observed.update(kw);return pd.DataFrame(columns=['trade_date'])
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);panel=root/'panel.parquet';pq.write_table(pa.table({'ts_code':pa.array([],type=pa.string()),'trade_date':pa.array([],type=pa.string())}),panel)
   pointer=root/'selector';pointer.write_text(str(panel));back=root/'backtest';back.write_text(str(panel));receipt=root/'receipt';receipt.write_text('{}');reader=root/'reader';reader.write_text('{}')
   journal=root/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json';journal.parent.mkdir(parents=True);journal.write_text('{}')
   context=product.SourceContext.__new__(product.SourceContext);context.target=20261029;context.panel=panel;context.panel_stat=panel.stat();context.data_root=root;context.pointer=pointer;context.backpointer=back;context.pointer_bytes=pointer.read_bytes();context.back_bytes=back.read_bytes();context.receipt_ref={'path':str(receipt)};context.reader_ref={'path':str(reader)};context.reader=SimpleNamespace(load_selector_ready=read)
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
   with patch.object(product,'SourceContext',return_value=context),patch.object(product,'compute_stock',side_effect=compute),patch('ops.research_daily_product_parallel.prefill_missing',return_value={'chart_gaps':{}}):
    first=product.materialize_daily_product(data_root='/read-only',target=20261029,output_root=output,original_charts=False)
    second=product.materialize_daily_product(data_root='/read-only',target=20261029,output_root=output,original_charts=False)
   self.assertEqual(len(calls),3);self.assertEqual(first,second);self.assertFalse(default.exists())
   payload=json.loads(Path(first['artifact']['path']).read_text());self.assertFalse(payload['sample_only']);self.assertEqual(payload['processed_count'],3);self.assertEqual(payload['source_universe_count'],3);self.assertEqual(payload['unique_count'],2);self.assertEqual(payload['unknown_count'],1)
