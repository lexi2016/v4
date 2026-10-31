"""Dated four-group projection at the existing A producer completion boundary.

No acquisition or GET execution. Historical bootstrap is explicit and bounded;
the normal daily path evaluates only its target date and reuses validated history.
"""
from __future__ import annotations
import ast,hashlib,importlib.util,json,math,os,struct,sys,time,zipfile
from collections import Counter
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from contextlib import nullcontext

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
GROUPS=('original','nav_smallk','nav_pullback','nav_breakout')
CONFIG=Path(__file__).resolve().parents[1]/'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json'
SCHEMA='v4.a_share.daily_product.v1'

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=lambda x:str(x) if isinstance(x,Decimal) else (_ for _ in ()).throw(TypeError(type(x).__name__))).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def reference(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def checked(r):
 p=Path(r['path'])
 if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p or sha(p)!=r['sha256']:raise ValueError('DAILY_SOURCE_PIN_DRIFT:'+str(p))
 return p
def save(p,v,immutable=False):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);raw=canonical(v)+b'\n'
 if immutable and p.exists():
  if p.read_bytes()!=raw:raise ValueError('DAILY_IMMUTABLE_CONFLICT:'+str(p))
  return reference(p)
 tmp=p.with_name('.'+p.name+f'.{os.getpid()}.pending')
 with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p);return reference(p)
def module(r,name):
 p=checked(r);raw=p.read_bytes();spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;exec(compile(raw,str(p),'exec'),m.__dict__);return m

def iso(d):return datetime.strptime(str(d),'%Y%m%d').strftime('%Y-%m-%d')
def tristate(v):return 'TRUE' if v is True else 'FALSE' if v is False else 'UNKNOWN'
def config():
 p=Path(os.environ.get('V4_RESEARCH_DAILY_PRODUCT_CONFIG') or CONFIG);v=json.loads(p.read_text())
 if v.get('schema')!='research_daily_product_sources.v1':raise ValueError('DAILY_SOURCE_CONFIG_SCHEMA')
 for k in ('engine','formula','tri_state_core','admission_helper','census'):checked(v[k])
 for ref in v.get('dated_g4_packages',{}).values():checked(ref)
 if v.get('future_calendar'):checked(v['future_calendar'])
 return v,reference(p)

def _exact_typed_end_fact(context,symbol):
 """Exact already-published source fact; never edits its source snapshot."""
 path=os.environ.get('V4_A_DAILY_TYPED_END_FACT_PATH');expected=os.environ.get('V4_A_DAILY_TYPED_END_FACT_SHA256')
 if not path and not expected:return None,None
 if not path or not expected:raise ValueError('TYPED_END_FACT_BINDING_INCOMPLETE')
 ref=dict(path=path,sha256=expected);proof=json.loads(checked(ref).read_bytes());item=context.snapshot['symbols'][symbol]
 if (proof.get('schema')!='V4_EXACT_002731_D30_TYPED_METADATA_V2' or symbol!='002731.SZ' or context.target!=20261030
     or proof.get('symbol')!=symbol or proof.get('target_date')!=context.target or 'history_end_date'in item
     or proof.get('source_generation')!=context.generation
     or context.generation!='d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
     or proof.get('snapshot')!=context.snapshot_ref
     or context.snapshot_ref['sha256']!='e3a475a74dfd494fbf3177779e634c94509542551a27a6f40802b1c7c6e0202e'
     or proof.get('producer_receipt')!=context.receipt_ref or proof.get('raw_refs')!=item['raw_files']
     or proof.get('original_missing_field')is not True or proof.get('original_reason')!='CURRENT_SYMBOL_HISTORY_END_MISMATCH'
     or proof.get('effective_history_end_date')!=context.target or proof.get('resolved_rows')!=2819
     or proof.get('historical_PIT')is not False or any(proof.get(k)!=v for k,v in FLAGS.items())):
  raise ValueError('TYPED_END_EXACT_SOURCE_SCOPE_CONFLICT')
 helper={key:context.config['admission_helper'][key]for key in ('path','sha256')}
 if proof.get('helper')!=helper or helper['sha256']!='7d67ba9898ebc1e816d082ae43ca0f51e3a9bc16278a589c0104524af925047a':raise ValueError('TYPED_END_HELPER_BINDING_CONFLICT')
 checked(helper);checked(proof['snapshot']);checked(proof['producer_receipt'])
 native=proof['native']
 if native not in item['raw_files'] or native['sha256']!='87c5e2c62f250f72a87cee8dafac4bddd69d38f36a23e6330539911e6dca50af':raise ValueError('TYPED_END_NATIVE_BINDING_CONFLICT')
 checked(native)
 from ops import research_panel_qfq as q
 if sha(Path(q.__file__))!=proof['resolved_owner']['sha256']:raise ValueError('TYPED_END_ORIGINAL_RAW_OWNER_DRIFT')
 checked(proof['resolved_owner']);driver,_=q.authorities(checked(proof['driver']),checked(proof['formula']))
 raw=q.resolved_raw_history(symbol,item,context.target,driver)
 if len(raw)!=2819 or int(raw.trade_date.max())!=context.target:raise ValueError('TYPED_END_RESOLVED_HISTORY_CONFLICT')
 columns=('open','high','low','close','vol','amount');last=raw.loc[raw.trade_date.eq(context.target)]
 if len(last)!=1:raise ValueError('TYPED_END_TARGET_RAW_ROW_CONFLICT')
 target={key:float(last.iloc[0][key])for key in columns}
 if target!=proof['target_ohlcva'] or not all(math.isfinite(v)and v>0 for v in target.values()):raise ValueError('TYPED_END_TARGET_RAW_VALUES_CONFLICT')
 import pyarrow as pa
 import pyarrow.parquet as pq
 if set(proof['paired_roles'])!={'selector','backtest'}:raise ValueError('TYPED_END_PAIRED_ROLES_CONFLICT')
 context.unchanged()
 for role,path in context.receipt['candidates'].items():
  bound=proof['paired_roles'][role];p=Path(path);stamp=p.stat();schema=pq.read_schema(p)
  if (bound['path']!=path or bound['sha256']!=context.receipt['candidate_sha256'][role]
      or bound['generation_id']!=context.generation or bound['stat']!={'size':stamp.st_size,'mtime_ns':stamp.st_mtime_ns}
      or q.panel_contract(p).get('generation_id')!=context.generation):raise ValueError('TYPED_END_PAIRED_REFERENCE_CONFLICT')
  volume='volume'if'volume'in schema.names else'vol';date=context.target if pa.types.is_integer(schema.field('trade_date').type)else str(context.target)
  table=pq.read_table(p,columns=['ts_code','trade_date','open','high','low','close',volume,'amount'],filters=[('ts_code','=',symbol),('trade_date','=',date)])
  if len(table)!=1:raise ValueError('TYPED_END_PAIRED_TARGET_ROW_MISSING')
  record=table.to_pylist()[0];values={key:float(record[volume if key=='vol'else key])for key in columns}
  if values!=target or values!=bound['target_row'] or p.stat()!=stamp:raise ValueError('TYPED_END_PAIRED_TARGET_VALUES_CONFLICT')
 _exact_typed_acceptance_references(context,proof)
 context.unchanged();return proof,ref


def _exact_typed_acceptance_references(context,proof):
 """Metadata aggregation over real stock-specific accepted source receipts."""
 refs=proof.get('accepted_evidence')
 if not isinstance(refs,list)or len(refs)!=1:raise ValueError('TYPED_SOURCE_REFERENCE_SCOPE_CONFLICT')
 evidence=json.loads(checked(refs[0]).read_bytes())
 if (evidence.get('schema')!='V4_EXACT_002731_D30_EXISTING_SOURCE_REFERENCES_V1' or evidence.get('symbol')!='002731.SZ'
     or evidence.get('target_date')!=20261030 or evidence.get('source_generation')!=context.generation
     or evidence.get('snapshot')!=context.snapshot_ref or evidence.get('native')!=proof['native']
     or evidence.get('raw_refs')!=proof['raw_refs'] or evidence.get('producer_receipt')!=context.receipt_ref
     or evidence.get('historical_PIT')is not False or any(evidence.get(k)!=v for k,v in FLAGS.items())):raise ValueError('TYPED_SOURCE_REFERENCE_APPLICABILITY_CONFLICT')
 admission=json.loads(checked(evidence['original_source_admission']).read_bytes());rows=[r for r in admission['symbol_reconciliation']if r.get('symbol')=='002731'and r.get('market')==0]
 if (admission.get('target_date')!='20261030' or admission.get('technical_failure_count')!=0 or len(rows)!=1):raise ValueError('TYPED_SOURCE_ADMISSION_SCOPE_CONFLICT')
 row=rows[0];lineage=row.get('source_lineage',{})
 if (digest(row)!=evidence['original_source_row_sha256'] or row.get('classification')!='ACCEPTED' or row.get('quarantine')is not False
     or row.get('source_sha256_after')!=proof['native']['sha256'] or row.get('last_date_after')!=20261030 or row.get('target_date_ready')is not True
     or lineage.get('code')!='002731' or lineage.get('market')!=0 or lineage.get('target_date')!=20261030):raise ValueError('TYPED_SOURCE_ADMISSION_ROW_CONFLICT')
 for ref in row.get('raw_response_snapshots',[]):checked(ref)
 checked(lineage['input_ref']);checked(lineage['package'])
 activation=json.loads(checked(evidence['original_native_activation']).read_bytes());items=[r for r in activation['items']if r['symbol']=='002731.SZ']
 if (activation.get('canonical_activated')is not True or len(items)!=1 or digest(items[0])!=evidence['original_native_item_sha256']):raise ValueError('TYPED_SOURCE_NATIVE_ACTIVATION_CONFLICT')
 item=items[0]
 if item['original']['path']!=proof['native']['path'] or item['candidate']['sha256']!=proof['native']['sha256'] or item['backup']['sha256']!=item['original']['sha256']:raise ValueError('TYPED_SOURCE_NATIVE_IDENTITY_CONFLICT')
 checked(item['backup']);checked(item['candidate'])
 preparation=json.loads(checked(evidence['original_preparation']).read_bytes());entries=[r for r in preparation['items']if r['symbol']=='002731.SZ']
 if len(entries)!=1 or digest(entries[0])!=evidence['original_preparation_entry_sha256']or entries[0]['candidate']['sha256']!=row['source_sha256_before']:raise ValueError('TYPED_SOURCE_REPAIR_CHAIN_CONFLICT')
 checked(entries[0]['candidate']);capture=json.loads(checked(evidence['original_capture']).read_bytes())
 if (capture.get('symbol')!='002731.SZ' or str(capture.get('target_date'))!='20261030' or capture.get('response_error')is not None
     or capture.get('request',{}).get('code')!='002731' or capture['request'].get('market')!=0):raise ValueError('TYPED_SOURCE_RAW_CAPTURE_APPLICABILITY_CONFLICT')
 seed=json.loads(checked(evidence['seed_descriptor']).read_bytes());boundary=seed.get('delisting_first_session_boundaries',{}).get('002731.SZ')
 if (boundary!=evidence.get('first_retirement_session')or boundary.get('session_date')!=20261023
     or boundary.get('type')!='SZSE_DELISTING_CONSOLIDATION_FIRST_SESSION_NO_PRICE_LIMIT'
     or boundary.get('raw_source')!=entries[0]['candidate']):raise ValueError('TYPED_SOURCE_HISTORICAL_EXCEPTION_SCOPE_CONFLICT')
 checked(boundary['official_notice']);publication=json.loads(checked(evidence['paired_publication']).read_bytes())
 if publication.get('status')!='ACTUAL_PAIRED_READY_POINTERS_COMMITTED'or publication.get('generation_id')!=context.generation:raise ValueError('TYPED_SOURCE_PAIRED_PUBLICATION_CONFLICT')
 journal=json.loads(checked(publication['publication_journal']).read_bytes());published=json.loads(checked(publication['producer_receipt']).read_bytes())
 if journal.get('status')!='COMMITTED'or published.get('status')!='READY'or published.get('generation_id')!=context.generation:raise ValueError('TYPED_SOURCE_PAIRED_ACTUAL_STATUS_CONFLICT')
 for role,path in context.receipt['candidates'].items():
  if (publication['pointers'][role]['actual_target']!=path or journal['after'][role].strip()!=path
      or published['candidate_sha256'][role]!=context.receipt['candidate_sha256'][role]):raise ValueError('TYPED_SOURCE_PAIRED_ACTUAL_IDENTITY_CONFLICT')
 return refs


def _exact_typed_end_validator(helper,helper_ref,proof,*,derive_references=True):
 """Only two original metadata nodes get typed facts; all other AST remains."""
 import copy
 if helper_ref.get('sha256')!='7d67ba9898ebc1e816d082ae43ca0f51e3a9bc16278a589c0104524af925047a':raise ValueError('TYPED_END_HELPER_INTERFACE_DRIFT')
 source=checked(helper_ref);tree=ast.parse(source.read_text());functions=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='verify_symbol_admission']
 if len(functions)!=1:raise ValueError('TYPED_END_HELPER_INTERFACE_DRIFT')
 original=functions[0]
 if ([arg.arg for arg in original.args.args]!=['code','target_date','source_contract','generation_receipt','quarantine','generation_id','quarantine_path']
     or original.args.posonlyargs or original.args.kwonlyargs or original.args.defaults or original.args.vararg or original.args.kwarg or original.decorator_list
     or hashlib.sha256(ast.dump(original,include_attributes=False).encode()).hexdigest()!=proof['helper_function_ast_sha256']):raise ValueError('TYPED_END_HELPER_INTERFACE_DRIFT')
 predicate=ast.parse("str(symbol.get('history_end_date')) != target_date",mode='eval').body
 nodes=[(i,n)for i,n in enumerate(original.body)if isinstance(n,ast.If)and ast.dump(n.test,include_attributes=False)==ast.dump(predicate,include_attributes=False)]
 expected=ast.parse("if str(symbol.get('history_end_date')) != target_date:\n return {'status':'UNKNOWN','reason':'CURRENT_SYMBOL_HISTORY_END_MISMATCH'}").body[0]
 if len(nodes)!=1 or ast.dump(nodes[0][1],include_attributes=False)!=ast.dump(expected,include_attributes=False):raise ValueError('TYPED_END_HELPER_PREDICATE_DRIFT')
 index,_=nodes[0];adapted=copy.deepcopy(original);adapted.body[index].test=ast.parse('str(_typed_history_end_date) != target_date',mode='eval').body
 lookup=ast.parse("references = [*symbol.get('accepted_evidence', [])]").body[0]
 assignments=[i for i,node in enumerate(original.body)if ast.dump(node,include_attributes=False)==ast.dump(lookup,include_attributes=False)]
 if len(assignments)!=1:raise ValueError('TYPED_END_HELPER_REFERENCE_LOOKUP_DRIFT')
 lookup_index=assignments[0];state={'used':False}
 def references(symbol):
  value=symbol.get('accepted_evidence',[])
  if not isinstance(value,list):raise ValueError('TYPED_END_EXISTING_REFERENCE_FIELD_INVALID')
  if 'accepted_evidence'not in symbol or value==[]:
   state['used']=True;return proof['accepted_evidence']
  return value
 if derive_references:adapted.body[lookup_index].value.elts[0].value=ast.parse('_typed_accepted_evidence(symbol)',mode='eval').body
 restored=copy.deepcopy(adapted);restored.body[index].test=copy.deepcopy(original.body[index].test)
 if derive_references:restored.body[lookup_index]=copy.deepcopy(original.body[lookup_index])
 if ast.dump(restored,include_attributes=False)!=ast.dump(original,include_attributes=False):raise ValueError('TYPED_END_HELPER_OTHER_AST_DRIFT')
 environment={**helper.__dict__,'_typed_history_end_date':proof['effective_history_end_date'],'_typed_accepted_evidence':references}
 exec(compile(ast.fix_missing_locations(ast.Module(body=[adapted],type_ignores=[])),str(source),'exec'),environment)
 validator=environment['verify_symbol_admission'];validator.typed_reference_state=state;return validator


def _census(r,asof,observation):
 p=checked(r);tree=ast.parse(p.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='analyze')
 class BindDate(ast.NodeTransformer):
  def visit_Constant(self,node):
   if type(node.value) is int and node.value in (20261027,20261028):return ast.copy_location(ast.Constant(asof if node.value==20261027 else observation),node)
   # Keep the reviewed R5 descriptor namespace stable; values carry actual dates.
   if isinstance(node.value,str):return ast.copy_location(ast.Constant(node.value.replace('D27','D28').replace('D26','D27')),node)
   return node
 env={'math':math};exec(compile(ast.fix_missing_locations(ast.Module(body=[BindDate().visit(fn)],type_ignores=[])),str(p),'exec'),env);return env['analyze']

class SourceContext:
 def __init__(self,data_root,target,*,source_config=None):
  from ops.research_panel_qfq import panel_contract
  self.data_root=Path(data_root).resolve();self.target=int(target);self.config,self.config_ref=(source_config if source_config else config());self.root=self.data_root/'daily_products/a_share'
  self.pointer=self.data_root/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';self.backpointer=self.data_root/'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt';self.pointer_bytes=self.pointer.read_bytes();self.back_bytes=self.backpointer.read_bytes()
  self.panel=Path(self.pointer_bytes.decode('utf-8-sig').strip());self.footer=panel_contract(self.panel);back=panel_contract(Path(self.back_bytes.decode('utf-8-sig').strip()))
  if self.footer.get('asof_date')!=self.target or self.footer.get('generation_id')!=back.get('generation_id'):raise ValueError('DAILY_PAIRED_GENERATION_OR_DATE_CONFLICT')
  self.generation=self.footer['generation_id'];self.receipt_ref=reference(Path(self.footer['generation_manifest_path']));self.receipt=json.loads(checked(self.receipt_ref).read_text());self.snapshot_ref=self.receipt['adjustment_snapshot'];self.snapshot=json.loads(checked(self.snapshot_ref).read_text());self.quarantine_ref=self.receipt['quarantine_manifest'];self.quarantine=json.loads(checked(self.quarantine_ref).read_text())
  if self.receipt.get('generation_id')!=self.generation or self.quarantine.get('generation_id')!=self.generation or self.snapshot.get('asof_date')!=self.target:raise ValueError('DAILY_RECEIPT_SNAPSHOT_IDENTITY_CONFLICT')
  if (self.footer.get('snapshot_file_sha256')!=self.snapshot_ref['sha256'] or self.receipt.get('snapshot_file_sha256')!=self.snapshot_ref['sha256'] or self.receipt['candidates']['selector']!=str(self.panel)):raise ValueError('DAILY_SNAPSHOT_SHA_CONFLICT')
  self.scope=sorted(self.snapshot.get('original_target_codes') or self.snapshot['symbols'])
  if len(self.scope)!=len(set(self.scope)) or not self.scope:raise ValueError('DAILY_PROCESSED_UNIVERSE_INVALID')
  self.panel_stat=self.panel.stat();self.identity=dict(generation=self.generation,input_sha256=self.footer['input_sha256'],snapshot=self.snapshot_ref,selector_artifact_sha256=self.receipt['candidate_sha256']['selector'],asof=self.target,basis=self.footer['market_basis']['A'],historical_PIT=False)
  self.label_results={}
  label_root=os.environ.get('V4_RESEARCH_EVENT_LABEL_SOURCE_ROOT')
  if label_root:
   label_root=Path(label_root)
   if not label_root.is_absolute() or label_root.is_symlink() or label_root.resolve(strict=True)!=label_root:raise ValueError('DAILY_LABEL_SOURCE_ROOT_INVALID')
   label_index=json.loads((label_root/'index.json').read_text())
   for old_day,sync in sorted(label_index.get('history_sync',{}).items()):
    if int(old_day)<=self.target:self.label_results.update(sync.get('stock_results',{}))
  self.helper=module(self.config['admission_helper'],'dated_original_admission');self.hash_cache={};original_read=self.helper.read_json;self.helper.read_json=lambda p:self.snapshot if Path(p)==Path(self.snapshot_ref['path']) else original_read(p);self.helper.sha256_file=self.cached_sha
  reader=self.pointer.with_name('DATA_LAYER_INTERFACE.py');self.reader_ref=reference(reader);self.reader=module(self.reader_ref,'dated_original_shared_reader');self._engine=None;self.calendars=self._calendars();self._g4={}
 def cached_sha(self,p):
  p=Path(p);s=p.stat();stamp=(s.st_size,s.st_mtime_ns,s.st_ino)
  if str(p) in self.hash_cache:
   old,h=self.hash_cache[str(p)]
   if old!=stamp:raise ValueError('DAILY_REFERENCE_CHANGED:'+str(p))
   return h
  h=sha(p);self.hash_cache[str(p)]=(stamp,h);return h
 def unchanged(self):
  s=self.panel.stat()
  if self.pointer.read_bytes()!=self.pointer_bytes or self.backpointer.read_bytes()!=self.back_bytes or (s.st_size,s.st_mtime_ns,s.st_ino)!=(self.panel_stat.st_size,self.panel_stat.st_mtime_ns,self.panel_stat.st_ino):raise ValueError('DAILY_GENERATION_CHANGED_DURING_PROJECTION')
 def _calendars(self):
  import pyarrow.parquet as pq
  dates={e:set() for e in ('SH','SZ','BJ')}
  for batch in pq.ParquetFile(self.panel).iter_batches(columns=['exchange','trade_date'],batch_size=131072):
   for e,d in zip(batch.column(0).to_pylist(),batch.column(1).to_pylist()):
    if e in dates and int(d)<=self.target:dates[e].add(int(d))
  if self.config.get('future_calendar'):
   pinned=json.loads(checked(self.config['future_calendar']).read_text());periods=pinned['markets']['a_share']['holiday_periods'];day=datetime.strptime(str(self.target),'%Y%m%d')+timedelta(days=1)
   while day.year==pinned['year']:
    if day.weekday()<5 and not any(v['start']<=day.strftime('%Y%m%d')<=v['end'] for v in periods):
     for values in dates.values():values.add(int(day.strftime('%Y%m%d')))
    day+=timedelta(days=1)
  return {e:sorted(v) for e,v in dates.items()}
 def qualify(self,symbol):
  args=(symbol,str(self.target),self.footer,self.receipt,self.quarantine,self.generation,Path(self.quarantine_ref['path']))
  original=self.helper.verify_symbol_admission(*args)
  if (symbol!='002731.SZ' or self.target!=20261030 or original.get('reason')!='CURRENT_SYMBOL_HISTORY_END_MISMATCH'
      or 'history_end_date' in self.snapshot.get('symbols',{}).get(symbol,{})):return original
  proof,proof_ref=_exact_typed_end_fact(self,symbol)
  if proof is None:return original
  date_only=_exact_typed_end_validator(self.helper,self.config['admission_helper'],proof,derive_references=False)(*args)
  validator=_exact_typed_end_validator(self.helper,self.config['admission_helper'],proof)
  result=validator(*args)if date_only.get('reason')=='CURRENT_SYMBOL_ACCEPTANCE_REFERENCES_MISSING'else date_only
  if result.get('status')=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
   result.update(history_end_date=str(proof['effective_history_end_date']),history_end_metadata=dict(
    schema='EXACT_D30_002731_TYPED_METADATA_CONSUMER_V2',original_missing_fields=proof['original_missing_fields'],original_admission=original,
    date_only_admission=date_only,effective_date_is_derived=True,evidence=proof_ref,original_helper=proof['helper'],
    derived_accepted_evidence=proof['accepted_evidence']if validator.typed_reference_state['used']else[],
    validator=reference(Path(__file__)),snapshot_bytes_unchanged=True))
  return result
 def _read_frame(self,symbol):
  columns=['ts_code','trade_date','name','market_type','exchange','open','high','low','close','volume'];self.unchanged()
  cache=getattr(self,'_selector_read_cache',None)
  if cache is None:
   # The original reader validates profile/basis and the paired publication
   # before this context reuses one Dataset's parsed Parquet metadata.
   frame=self.reader.load_selector_ready(columns=columns,filters=[('ts_code','=',symbol),('trade_date','<=',str(self.target))],panel_path=self.panel,profile=None)
   self.unchanged()
   import pyarrow.dataset as ds
   paths=[self.panel,Path(self.back_bytes.decode('utf-8-sig').strip()),Path(self.receipt_ref['path']),Path(self.reader_ref['path'])]
   stamps={p:(p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns) for p in paths}
   journal=self.data_root/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json'
   self._selector_read_cache=dict(dataset=ds.dataset(self.panel,format='parquet'),stamps=stamps,journal=journal,journal_bytes=journal.read_bytes())
   return frame
  for path,stamp in cache['stamps'].items():
   s=path.stat()
   if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=stamp:raise ValueError('DAILY_READ_BINDING_CHANGED:'+str(path))
  if cache['journal'].read_bytes()!=cache['journal_bytes']:raise ValueError('DAILY_READ_PUBLICATION_JOURNAL_CHANGED')
  import pyarrow.dataset as ds
  return cache['dataset'].to_table(columns=list(dict.fromkeys(['trade_date','ts_code',*columns])),filter=(ds.field('ts_code')==symbol)&(ds.field('trade_date')<=str(self.target))).to_pandas().reset_index(drop=True)
 def read(self,symbol):
  frame=self._read_frame(symbol).sort_values('trade_date',kind='stable')
  if frame.empty:return [],None
  if frame.trade_date.duplicated().any() or not frame.ts_code.eq(symbol).all() or not frame.exchange.astype(str).eq(symbol[-2:]).all() or not set(frame.market_type.astype(str))<={'A_SHARE','BJ'}:raise ValueError('DAILY_SYMBOL_PREFIX_CONFLICT:'+symbol)
  bars=[dict(trade_date=int(r.trade_date),open=str(r.open),high=str(r.high),low=str(r.low),close=str(r.close),vol=str(r.volume)) for r in frame.itertuples()]
  names=frame.name[frame.name.map(lambda value:isinstance(value,str) and bool(value.strip()))]
  name=names.iloc[-1].strip() if len(names) else None
  return bars,name
 def engine(self):
  if self._engine is None:self._engine=module(self.config['engine'],'dated_exact_original_engine');self.core=module(self.config['tri_state_core'],'dated_original_tristate')
  return self._engine
 def g4_reference(self,symbol,date,qualification):
  # Source is an existing bound dated package; never fetch in this projection.
  date=int(date);pin=self.config.get('dated_g4_packages',{}).get(str(date))
  if pin is None:
   syncpath=Path(os.environ.get('V4_RESEARCH_PANEL_RECEIPT_ROOT') or self.data_root.parent.parent/'research_panel_daily/receipts')/'a_sync_authority/official_daily'/str(date)/'input.json'
   if syncpath.is_file():pin=json.loads(syncpath.read_text()).get('package')
  if pin is None:return dict(date=date,correspondence_status='UNKNOWN',reason='RAW_G4_PREV_CLOSE_SOURCE_MISSING')
  if date not in self._g4:
   from ops._a_share_daily_sync_parts.official_daily_package import parse_package
   p=checked(pin);raw=p.read_bytes();parsed,_=parse_package(raw,date);values={}
   with zipfile.ZipFile(p) as z:
    blocks={name:z.read(name) for name in {lineage['md1_member']['name'] for _,lineage,_ in parsed.values()}}
    for (market,code),(bar,lineage,volume) in parsed.items():
     block=blocks[lineage['md1_member']['name']];previous=struct.unpack_from('<d',block,lineage['md1_byte_offset']+4)[0];values[code+'.'+{0:'SZ',1:'SH',2:'BJ'}[market]]=dict(date=date,close=bar['close'],prev_close=previous,ohlc={k:bar[k] for k in ('open','high','low','close')},source=pin)
   self._g4[date]=values
  value=self._g4[date].get(symbol)
  if value is None:return dict(date=date,correspondence_status='UNKNOWN',reason='RAW_G4_SYMBOL_ABSENT')
  matches=[]
  for r in qualification.get('verified_raw_sources',[]):
   raw=checked(r).read_bytes()
   for off in range(0,len(raw),32):
    if struct.unpack_from('<I',raw,off)[0]==date:
     prices=struct.unpack_from('<4I',raw,off+4);matches.append(all(Decimal(str(value['ohlc'][k])).quantize(Decimal('.01'))==Decimal(v)/100 for k,v in zip(('open','high','low','close'),prices)))
  return dict(value,correspondence_status='TRUE' if matches and all(matches) else 'UNKNOWN',reason=None if matches and all(matches) else 'RAW_G4_NATIVE_PARITY_UNCONFIRMED')

def source_inputs(context,symbol,bars,asof,qualification,*,retain=None,prefix_reuse=None):
 """Original formula/AST only; caller controls registered real computation."""
 engine=context.engine()
 if prefix_reuse is None:
  result=engine.compute(bars,'prefix')
  if retain is not None:retain(result)
  rows=result['rows']
 else:
  fields=('B1','B2','B3','突破','突破接十字星','零上二金','零下二金','一级买点','二级买点')
  if retain is not None or prefix_reuse.get('fields')!=fields:raise ValueError('CANNOT_CONFIRM_PREFIX_REUSE_CONSUMED_FIELDS')
  pins={'engine':'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c','formula':'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac','tri_state_core':'e5bbeed5cfa665ef863f0cacb0bb6b13a17ebe957c1429eaaa8dea0acaf44a35','census':'75ed99318a149f2b57cbedd42618e5d5910d60ae2dd11f7fcb159c3fb3a6f2ef'}
  if any(context.config[k]['sha256']!=value or context.cached_sha(Path(context.config[k]['path']))!=value for k,value in pins.items()):raise ValueError('CANNOT_CONFIRM_PREFIX_CAUSALITY_PINS')
  if context.cached_sha(Path(context.config_ref['path']))!=context.config_ref['sha256']:raise ValueError('CANNOT_CONFIRM_PREFIX_CONFIG_DRIFT')
  if (prefix_reuse.get('symbol')!=symbol or prefix_reuse.get('generation')!=context.generation
      or prefix_reuse.get('identity')!=digest(context.identity) or prefix_reuse.get('config')!=digest(context.config)
      or prefix_reuse.get('config_ref')!=digest(context.config_ref) or prefix_reuse.get('qualification')!=digest(qualification) or prefix_reuse.get('target')!=context.target
      or not bars or bars[-1]['trade_date']!=int(asof) or int(asof)>context.target
      or tuple(b['trade_date'] for b in bars)!=prefix_reuse['dates'][:len(bars)]
      or digest(bars)!=prefix_reuse['prefix_sha256'].get(int(asof))):raise ValueError('CANNOT_CONFIRM_PREFIX_REUSE_IDENTITY_OR_PREFIX_DRIFT')
  proof_key=tuple((k,context.config[k]['path'],v) for k,v in pins.items())
  if getattr(context,'_history_prefix_causal_proof',None)!=proof_key:
   assignments={a['name']:engine.Parser(a['expression']).parse() for a in engine.inventory()['assignments']};proved=set();visiting=set()
   def visit(node):
    kind=node[0]
    if kind=='var':
     variable=node[1]
     if variable in {'OPEN','HIGH','LOW','CLOSE','VOL','DRAWNULL'}:return
     if variable not in assignments or variable in visiting:raise ValueError('CANNOT_CONFIRM_PREFIX_NONCAUSAL_VARIABLE:'+variable)
     if variable not in proved:
      visiting.add(variable);visit(assignments[variable]);visiting.remove(variable);proved.add(variable)
    elif kind=='call':
     if node[1] not in {'MA','EMA','SMA','REF','COUNT','BARSLAST','CROSS','HHV','LLV'}:raise ValueError('CANNOT_CONFIRM_PREFIX_NONCAUSAL_FUNCTION:'+node[1])
     for argument in node[2]:visit(argument)
    elif kind=='binary':visit(node[2]);visit(node[3])
    elif kind=='unary':visit(node[2])
    elif kind not in {'number','text'}:raise ValueError('CANNOT_CONFIRM_PREFIX_AST_UNKNOWN')
   for field in fields:visit(('var',field))
   context._history_prefix_causal_proof=proof_key
  rows=list(prefix_reuse['rows'][:len(bars)])
 last=rows[-1];signals=context.core.signals(last['values']);breakout={r['trade_date']:tristate(engine.boolean(r['values'].get('突破'))) for r in rows}
 answer=dict(symbol=symbol,rows=rows,source_bar_exact={'amount':0},index_sha256=context.config_ref['sha256'])
 summary,_=_census(context.config['census'],asof,asof)(answer);stage=summary.get('stage','UNKNOWN');known=not stage.startswith('UNKNOWN')
 baseline=dict(original={'YES':'TRUE','NO':'FALSE','UNKNOWN':'UNKNOWN'}[signals['membership']],nav_pullback='UNKNOWN' if not known else 'TRUE' if stage in {'D28_RECOVERY_BELOW_KEY_HIGH','PULLBACK_SUPPORT_OBSERVATION_NOT_CONFIRMED'} else 'FALSE',nav_breakout='UNKNOWN' if not known else 'TRUE' if stage in {'D28_BREAKOUT','ABOVE_KEY_CONTINUATION_DISTANCE_DISCLOSED'} else 'FALSE')
 return dict(original_breakout_by_date=breakout,baseline_memberships=baseline,old_main_anchor_date=summary.get('main_anchor_date'),qualification_status=qualification['status'],raw_g4_reference=context.g4_reference(symbol,asof,qualification))

def accepted_label_cache(context,symbol,rule_sha,cache):
 """Restore the original completed labels by their saved result/cache SHA."""
 ref=getattr(context,'label_results',{}).get(symbol)
 if not ref:return cache
 result=json.loads(checked(ref).read_text())
 if result.get('status')!='COMPLETE_DESCRIPTIVE_NONPIT' or result.get('symbol')!=symbol or any(result.get(k)!=v for k,v in FLAGS.items()):raise ValueError('DAILY_ACCEPTED_LABEL_RESULT_INVALID')
 previous=json.loads(checked(result['history_cache']).read_text())
 if previous.get('rule_sha256')!=rule_sha or previous.get('rules_signature')!=digest(context.config):raise ValueError('DAILY_ACCEPTED_LABEL_RULE_IDENTITY_CONFLICT')
 return previous if len(previous.get('evaluations',{}))>len(cache.get('evaluations',{})) else cache


def cached_daily_statistics(context,symbol,bars,calendar,groups,store):
 """Reuse the accepted durable owner without changing event or return rules."""
 from domains.research_daily_statistics import build_daily_event_statistics
 from domains.research_event_case_cache import EventCaseCache
 closes=[dict(date=iso(b['trade_date']),close=float(b['close']) if b['close'] is not None else None) for b in bars]
 dates=[iso(d) for d in calendar];asof=iso(context.target)
 # Original validation, provenance and price-distribution fields; no historical
 # return is evaluated for an empty event set.
 result=build_daily_event_statistics(close_rows=closes,market_calendar=dates,asof=asof,event_groups=[{**g,'event_dates':[]} for g in groups])
 basis=context.identity.get('basis')
 if not isinstance(basis,dict) or not context.reader_ref:raise ValueError('DAILY_CACHE_SEMANTIC_IDENTITY_UNBOUND')
 identity=dict(symbol=symbol,market=symbol[-2:],basis={k:v for k,v in basis.items() if k!='asof_date'},source_authority=dict(reader=context.reader_ref),rule_sha256=groups[0]['rule_sha256'],formula_sha256=context.config['formula']['sha256'])
 cache=EventCaseCache(store);all_groups={};counters=[]
 try:
  for original,summary in zip(groups,result['groups']):
   events=sorted(d for d in original['event_dates'] if d<=asof)
   value=cache.build(identity=identity,event_dates=events,close_rows=closes,calendar=dates,asof=asof)
   all_groups[original['group_id']]=value['horizons'];counters.append(dict(group=original['group_id'],**value['cache']))
   summary.update(status='AVAILABLE' if events else 'EMPTY_EVENT_SET',eligible_event_count=len(events))
   for h,horizon in value['horizons'].items():
    # Keep the established numerical contract byte-for-value; the complete
    # cases/conditional view is saved separately for the existing API.
    summary['horizons'][h]={k:v for k,v in horizon.items() if k not in ('conditional','cases')}
    summary['horizons'][h]['cases']=[{k:c[k] for k in ('event_date','target_date','status','detail_status','return_pct')} for c in horizon['cases'][:20]]
 finally:cache.close()
 return result,all_groups,counters


def compute_stock(context,symbol,*,evaluate=None,history_dates=(),chart_capture=None,reuse_history_prefix=False):
 from domains.research_daily_product import evaluate_daily_product
 from domains.research_daily_statistics import build_daily_event_statistics
 history_dates=tuple(history_dates)
 evaluate=evaluate or evaluate_daily_product;bars,name=context.read(symbol);q=context.qualify(symbol);target=context.target;calendar=context.calendars[symbol[-2:]];rule_sha=sha(Path(__file__).resolve().parents[1]/'domains/research_daily_product.py')
 if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' and (not bars or bars[-1]['trade_date']!=target or str(bars[0]['trade_date'])!=q['history_start_date']):q=dict(status='UNKNOWN',reason='ADMITTED_PREFIX_START_OR_TARGET_MISMATCH')
 captured=[]
 current_inputs=source_inputs(context,symbol,bars,target,q,**({'retain':captured.append} if chart_capture is not None or (reuse_history_prefix and history_dates) else {})) if bars and q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
 current=evaluate(symbol=symbol,asof=target,fullprefix=bars,exchange_calendar=calendar,**current_inputs)
 history_root=context.root/'history'/rule_sha/symbol;cachefile=history_root/'checkpoint.json';cache=json.loads(cachefile.read_text()) if cachefile.is_file() else dict(rule_sha256=rule_sha,evaluations={},price_prefix_dates=[])
 cache=accepted_label_cache(context,symbol,rule_sha,cache)
 rules_signature=digest(context.config)
 if cache.get('rules_signature',rules_signature)!=rules_signature or q['status']!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['rules_signature']=rules_signature
 old_end=max(map(int,cache['evaluations']),default=0);old_prefix=[b for b in bars if b['trade_date']<=old_end]
 if cache.get('prefix_sha256') and digest(old_prefix)!=cache['prefix_sha256']:cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['evaluations'][str(target)]=dict(groups={g:current['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True)
 # Explicit reuse is opt-in. Census/G4/qualification still use each cutoff;
 # only proven causal formula fields may come from the exact same full start.
 prefix_reuse=None
 if reuse_history_prefix and history_dates and q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
  from types import MappingProxyType
  if not captured:raise ValueError('CANNOT_CONFIRM_PREFIX_FULL_RESULT_MISSING')
  result=captured[0];fields=('B1','B2','B3','突破','突破接十字星','零上二金','零下二金','一级买点','二级买点');dates=tuple(b['trade_date'] for b in bars)
  if (result.get('mode')!='prefix' or result.get('formula_sha256')!=context.config['formula']['sha256'] or result.get('field_count')!=51 or result.get('drawing_count')!=22
      or tuple(r['trade_date'] for r in result['rows'])!=dates):raise ValueError('CANNOT_CONFIRM_PREFIX_FULL_RESULT_IDENTITY')
  chain=hashlib.sha256(b'[');prefix_hashes={}
  for index,bar in enumerate(bars):
   if index:chain.update(b',')
   chain.update(canonical(bar));point=chain.copy();point.update(b']');prefix_hashes[bar['trade_date']]=point.hexdigest()
  frozen_rows=tuple(MappingProxyType(dict(trade_date=r['trade_date'],ohlcv=MappingProxyType(dict(r['ohlcv'])),values=MappingProxyType({field:r['values'][field] for field in fields}))) for r in result['rows'])
  prefix_reuse=MappingProxyType(dict(symbol=symbol,generation=context.generation,identity=digest(context.identity),config=digest(context.config),config_ref=digest(context.config_ref),qualification=digest(q),target=context.target,fields=fields,dates=dates,prefix_sha256=MappingProxyType(prefix_hashes),rows=frozen_rows))
 for day in history_dates:
  day=int(day)
  if day>=target or str(day) in cache['evaluations']:continue
  prefix=[b for b in bars if b['trade_date']<=day]
  if not prefix or prefix[-1]['trade_date']!=day:continue
  inputs=source_inputs(context,symbol,prefix,day,q,**({'prefix_reuse':prefix_reuse} if prefix_reuse is not None else {})) if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
  earlier=evaluate(symbol=symbol,asof=day,fullprefix=prefix,exchange_calendar=calendar,**inputs)
  cache['evaluations'][str(day)]=dict(groups={g:earlier['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True,historical_PIT=False,historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION')
 evaluated=sorted(map(int,cache['evaluations']));expected=[b['trade_date'] for b in bars];complete=set(expected)<=set(evaluated)
 cache['prefix_sha256']=digest(bars);cache['source_identity']=context.identity;cache['coverage']=dict(requested_start=bars[0]['trade_date'] if bars else None,requested_end=target,evaluated_dates=evaluated,evaluated_count=len(evaluated),available_prefix_dates=len(expected),known_full_history=complete,historical_PIT=False,maximum_claim='DIRECTION_ONLY',historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION',unknown_by_group={g:sum(r['groups'][g]=='UNKNOWN' for r in cache['evaluations'].values()) for g in GROUPS},missing=[] if complete else ['HISTORICAL_FULL_CONDITION_BOOTSTRAP'])
 identity=dict(generation=context.generation,input=context.identity['input_sha256'],formula=context.config['formula']['sha256'],rule_sha256=rule_sha,asof=iso(target),market=symbol[-2:],basis='QFQ_ASOF',pit_status='NONPIT')
 groups=[dict(group_id=g,event_dates=[iso(int(d)) for d,r in sorted(cache['evaluations'].items()) if r['groups'][g]=='TRUE'],rule_sha256=rule_sha,source_identity=identity) for g in GROUPS]
 store=os.environ.get('V4_RESEARCH_EVENT_CASE_CACHE');cached_groups=None;reuse=None
 if store:
  if not Path(store).is_absolute() or not Path(store).is_file():raise ValueError('EXISTING_DAILY_EVENT_CACHE_REQUIRED')
  with getattr(context,'_event_case_cache_lock',None) or nullcontext():
   statistics,cached_groups,reuse=cached_daily_statistics(context,symbol,bars,calendar,groups,Path(store))
 else:statistics=build_daily_event_statistics(close_rows=[dict(date=iso(b['trade_date']),close=float(b['close']) if b['close'] is not None else None) for b in bars],market_calendar=[iso(d) for d in calendar],asof=iso(target),event_groups=groups)
 row=dict(symbol=symbol,display_name=name,data_date=str(target),groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='TRUE'),pending_groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='UNKNOWN'),latest_new_anchor=str(next((current['groups'][g].get('anchor_date') for g in GROUPS if current['groups'][g].get('anchor_date')), '') or ''),reasons='|'.join(sorted({s for g in GROUPS for s in current['groups'][g].get('reasons',[])})),risk_clear=current.get('risk',{}).get('status','UNKNOWN'),evaluation=current,statistics=statistics,historical_coverage=cache['coverage'],qualification=q)
 if cached_groups is not None:row['_daily_cached_groups']=cached_groups;row['_daily_cache_reuse']=reuse
 if chart_capture is not None and row['groups'] and captured:chart_capture(symbol,bars,captured[0])
 return row,cache,cachefile

def materialize_daily_product(*,data_root,target,formula_result=None,symbols=None,history_dates=(),evaluate=None,output_root=None,original_charts=True,chart_png_renderer=None):
 """Called once from original run_a; no historical loop in normal daily mode."""
 context=SourceContext(data_root,target)
 if output_root is not None:context.root=Path(output_root).resolve()
 root=context.root;context.unchanged()
 index_start=(root/'index.json').read_bytes() if (root/'index.json').is_file() else None
 if formula_result and (str(context.panel)!=str(formula_result['selector']) or formula_result['selector_sha256']!=context.receipt['candidate_sha256']['selector']):raise ValueError('DAILY_FORMULA_COMPLETION_IDENTITY_CONFLICT')
 selected=sorted(symbols if symbols is not None else context.scope)
 if not set(selected)<=set(context.scope):raise ValueError('DAILY_PROJECTION_OUTSIDE_PROCESSED_UNIVERSE')
 rows=[];row_refs={};runkey=digest(dict(identity=context.identity,config=context.config_ref,symbols=selected,history_dates=list(history_dates)));parts=root/'checkpoints'/str(target)/runkey
 chart_gaps={}
 def capture(symbol,bars,result):
  try:
   from ops.render_original_formula_projection import retain_owner_result
   retain_owner_result(context,parts,symbol,bars,result)
  except Exception as error:chart_gaps[symbol]='RETAINED_RESULT_UNAVAILABLE:'+str(error)
 if symbols is None and not history_dates and evaluate is None:
  from ops.research_daily_product_parallel import prefill_missing
  chart_gaps.update(prefill_missing(context,parts,selected,original_charts=original_charts)['chart_gaps'])
 for i,symbol in enumerate(selected):
  checkpoint=parts/(symbol+'.json')
  if checkpoint.is_file():row=json.loads(checkpoint.read_text())
  else:
   try:
    row,cache,path=compute_stock(context,symbol,evaluate=evaluate,history_dates=history_dates,**({'chart_capture':capture} if original_charts else {}));save(path,cache)
   except (ValueError,KeyError,TypeError,OSError) as error:
    row=dict(symbol=symbol,display_name=None,data_date=str(target),groups='',pending_groups='|'.join(GROUPS),latest_new_anchor='',reasons='SOURCE_ISOLATED:'+str(error),risk_clear='UNKNOWN',evaluation={'groups':{g:{'status':'UNKNOWN','reasons':['SOURCE_ISOLATED:'+str(error)]} for g in GROUPS}},statistics=None,historical_coverage={'known_full_history':False,'evaluated_count':0,'missing':['SOURCE_ISOLATED']},qualification={'status':'UNKNOWN','reason':str(error)})
   row.update(FLAGS);save(checkpoint,row,immutable=True)
  rows.append(row);row_refs[symbol]=reference(checkpoint);save(parts/'progress.json',dict(completed=i+1,total=len(selected),target_date=target,generation=context.generation,**FLAGS))
 context.unchanged();counts={g:dict(Counter(r['evaluation']['groups'][g]['status'] for r in rows)) for g in GROUPS};candidates=[r for r in rows if r['groups']];unknown=sum(bool(r['pending_groups']) for r in rows)
 product=dict(schema_version=SCHEMA,status='PARTIAL_WITH_ROWS' if unknown else 'READY',data_date=str(target),observation_date=None,source_generation=context.generation,source_identity=context.identity,source_config=context.config_ref,processed_universe=selected,processed_count=len(rows),source_universe_count=len(context.scope),sample_only=symbols is not None,unique_count=len(candidates),group_counts={g:counts[g].get('TRUE',0) for g in GROUPS},three_value_counts=counts,unknown_count=unknown,rows=[{k:v for k,v in row.items() if k in ('symbol','display_name','data_date','groups','pending_groups','latest_new_anchor','reasons','risk_clear')} for row in candidates],row_refs=row_refs,history_status='PARTIAL_NEEDS_BOOTSTRAP',history_bootstrap_in_daily_path=False,**FLAGS)
 content_sha=digest(product);version=root/'versions'/str(target)/context.generation/content_sha;artifact=save(version/'product.json',product,immutable=True);manifest=dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],snapshot=context.snapshot_ref,artifact=artifact,processed_count=len(rows),source_universe_count=len(context.scope),counts=counts,status=product['status'],sample_only=symbols is not None,history_status=product['history_status'],**FLAGS);manifest_ref=save(version/'manifest.json',manifest,immutable=True)
 chart_descriptor=None
 if original_charts:
  try:
   from ops.render_original_formula_projection import finalize_owner_charts
   chart_descriptor=finalize_owner_charts(context,parts,product,manifest_ref,artifact,gaps=chart_gaps,png_renderer=chart_png_renderer)
  except Exception as error:
   chart_descriptor=dict(status='CANNOT_CONFIRM',numeric_manifest=manifest_ref,reason='CHART_FINALIZATION_FAILED:'+str(error))
 try:context.unchanged()
 except Exception as error:
  save(parts/'publication_error.json',dict(status='CANNOT_CONFIRM',reason='SOURCE_CHANGED_BEFORE_PUBLICATION:'+str(error),manifest=manifest_ref,artifact=artifact,original_charts=chart_descriptor,**FLAGS))
  raise
 if symbols is None:
  if ((root/'index.json').read_bytes() if (root/'index.json').is_file() else None)!=index_start:raise ValueError('DAILY_PUBLICATION_INDEX_CAS_MOVED')
  indexfile=root/'index.json';index=json.loads(indexfile.read_text()) if indexfile.is_file() else dict(schema_version='v4.a_share.daily_product_index.v1',dates={})
  index['dates'][str(target)]=manifest_ref;index['latest_date']=max(index['dates']);index['latest']=index['dates'][index['latest_date']]
  if chart_descriptor is not None:index.setdefault('original_charts',{})[str(target)]=chart_descriptor
  if os.environ.get('V4_RESEARCH_EVENT_CASE_CACHE'):
   items={}
   for row in candidates:
    if row.get('_daily_cached_groups') is None:continue
    shard=dict(schema_version='v4.a_share.event_cases.v1',symbol=row['symbol'],data_date=str(target),numeric_manifest=manifest_ref,source_generation=context.generation,input_sha256=context.identity['input_sha256'],statistics_sha256=digest(row['statistics']),projection=(json.loads(checked(chart_descriptor['manifest']).read_text()).get('samples',{}).get(row['symbol'],{}).get('projection') if chart_descriptor and chart_descriptor.get('manifest') else None),groups=row['_daily_cached_groups'],cache_reuse=row['_daily_cache_reuse'],**FLAGS)
    items[row['symbol']]=save(version/'event_cases'/(row['symbol']+'.json'),shard,immutable=True)
   cases_index=dict(schema_version='v4.a_share.event_cases_index.v1',data_date=str(target),numeric_manifest=manifest_ref,source_generation=context.generation,input_sha256=context.identity['input_sha256'],items=items,**FLAGS)
   index.setdefault('event_cases',{})[str(target)]=save(version/'event_cases_index.json',cases_index,immutable=True)
  save(indexfile,index)
  statistics_root=os.environ.get('V4_WORKBENCH_STATISTICS_ROOT')
  if statistics_root:
   try:
    from ops.build_mac_workbench import materialize_statistics
    materialize_statistics(root,Path(statistics_root))
   except (ValueError,OSError,KeyError,TypeError) as error:
    save(parts/'workbench_statistics_error.json',dict(status='CANNOT_CONFIRM',error=str(error),numeric_manifest=manifest_ref,**FLAGS))
  event=dict(schema_version='v4.a_share.daily_completion.v1',event_id=digest(manifest),data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],artifact=artifact,manifest=manifest_ref,processed_count=len(rows),source_universe_count=len(context.scope),unknown_count=unknown,status=product['status'],**FLAGS)
  if chart_descriptor is not None:
   event['original_charts']=chart_descriptor;event['event_id']=digest(dict(numeric_manifest=manifest_ref,original_charts=chart_descriptor))
  save(root/'events/latest.json',event)
 return dict(manifest=manifest_ref,artifact=artifact,status=product['status'],data_date=str(target),source_generation=context.generation,processed_count=len(rows),unique_count=len(candidates),unknown_count=unknown,history_status=product['history_status'],**FLAGS)
