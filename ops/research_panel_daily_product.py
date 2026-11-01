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
 def qualify(self,symbol):return self.helper.verify_symbol_admission(symbol,str(self.target),self.footer,self.receipt,self.quarantine,self.generation,Path(self.quarantine_ref['path']))
 def read(self,symbol):
  frame=self.reader.load_selector_ready(columns=['ts_code','trade_date','name','market_type','exchange','open','high','low','close','volume'],filters=[('ts_code','=',symbol),('trade_date','<=',str(self.target))],panel_path=self.panel,profile=None).sort_values('trade_date',kind='stable')
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

def source_inputs(context,symbol,bars,asof,qualification,*,retain=None):
 """Original formula/AST only; caller controls registered real computation."""
 engine=context.engine();result=engine.compute(bars,'prefix');
 if retain is not None:retain(result)
 rows=result['rows'];last=rows[-1];signals=context.core.signals(last['values']);breakout={r['trade_date']:tristate(engine.boolean(r['values'].get('突破'))) for r in rows}
 answer=dict(symbol=symbol,rows=rows,source_bar_exact={'amount':0},index_sha256=context.config_ref['sha256'])
 summary,_=_census(context.config['census'],asof,asof)(answer);stage=summary.get('stage','UNKNOWN');known=not stage.startswith('UNKNOWN')
 baseline=dict(original={'YES':'TRUE','NO':'FALSE','UNKNOWN':'UNKNOWN'}[signals['membership']],nav_pullback='UNKNOWN' if not known else 'TRUE' if stage in {'D28_RECOVERY_BELOW_KEY_HIGH','PULLBACK_SUPPORT_OBSERVATION_NOT_CONFIRMED'} else 'FALSE',nav_breakout='UNKNOWN' if not known else 'TRUE' if stage in {'D28_BREAKOUT','ABOVE_KEY_CONTINUATION_DISTANCE_DISCLOSED'} else 'FALSE')
 return dict(original_breakout_by_date=breakout,baseline_memberships=baseline,old_main_anchor_date=summary.get('main_anchor_date'),qualification_status=qualification['status'],raw_g4_reference=context.g4_reference(symbol,asof,qualification))

def compute_stock(context,symbol,*,evaluate=None,history_dates=(),chart_capture=None):
 from domains.research_daily_product import evaluate_daily_product
 from domains.research_daily_statistics import build_daily_event_statistics
 evaluate=evaluate or evaluate_daily_product;bars,name=context.read(symbol);q=context.qualify(symbol);target=context.target;calendar=context.calendars[symbol[-2:]];rule_sha=sha(Path(__file__).resolve().parents[1]/'domains/research_daily_product.py')
 if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' and (not bars or bars[-1]['trade_date']!=target or str(bars[0]['trade_date'])!=q['history_start_date']):q=dict(status='UNKNOWN',reason='ADMITTED_PREFIX_START_OR_TARGET_MISMATCH')
 captured=[]
 current_inputs=source_inputs(context,symbol,bars,target,q,**({'retain':captured.append} if chart_capture is not None else {})) if bars and q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
 current=evaluate(symbol=symbol,asof=target,fullprefix=bars,exchange_calendar=calendar,**current_inputs)
 history_root=context.root/'history'/rule_sha/symbol;cachefile=history_root/'checkpoint.json';cache=json.loads(cachefile.read_text()) if cachefile.is_file() else dict(rule_sha256=rule_sha,evaluations={},price_prefix_dates=[])
 rules_signature=digest(context.config)
 if cache.get('rules_signature',rules_signature)!=rules_signature or q['status']!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['rules_signature']=rules_signature
 old_end=max(map(int,cache['evaluations']),default=0);old_prefix=[b for b in bars if b['trade_date']<=old_end]
 if cache.get('prefix_sha256') and digest(old_prefix)!=cache['prefix_sha256']:cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['evaluations'][str(target)]=dict(groups={g:current['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True)
 # Current admission authorizes this full prefix; each historical formula is
 # recomputed on its own slice. This is descriptive replay, never historical PIT.
 for day in history_dates:
  day=int(day)
  if day>=target or str(day) in cache['evaluations']:continue
  prefix=[b for b in bars if b['trade_date']<=day]
  if not prefix or prefix[-1]['trade_date']!=day:continue
  inputs=source_inputs(context,symbol,prefix,day,q) if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
  earlier=evaluate(symbol=symbol,asof=day,fullprefix=prefix,exchange_calendar=calendar,**inputs)
  cache['evaluations'][str(day)]=dict(groups={g:earlier['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True,historical_PIT=False,historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION')
 evaluated=sorted(map(int,cache['evaluations']));expected=[b['trade_date'] for b in bars];complete=set(expected)<=set(evaluated)
 cache['prefix_sha256']=digest(bars);cache['source_identity']=context.identity;cache['coverage']=dict(requested_start=bars[0]['trade_date'] if bars else None,requested_end=target,evaluated_dates=evaluated,evaluated_count=len(evaluated),available_prefix_dates=len(expected),known_full_history=complete,historical_PIT=False,maximum_claim='DIRECTION_ONLY',historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION',unknown_by_group={g:sum(r['groups'][g]=='UNKNOWN' for r in cache['evaluations'].values()) for g in GROUPS},missing=[] if complete else ['HISTORICAL_FULL_CONDITION_BOOTSTRAP'])
 identity=dict(generation=context.generation,input=context.identity['input_sha256'],formula=context.config['formula']['sha256'],rule_sha256=rule_sha,asof=iso(target),market=symbol[-2:],basis='QFQ_ASOF',pit_status='NONPIT')
 groups=[dict(group_id=g,event_dates=[iso(int(d)) for d,r in sorted(cache['evaluations'].items()) if r['groups'][g]=='TRUE'],rule_sha256=rule_sha,source_identity=identity) for g in GROUPS]
 statistics=build_daily_event_statistics(close_rows=[dict(date=iso(b['trade_date']),close=float(b['close']) if b['close'] is not None else None) for b in bars],market_calendar=[iso(d) for d in calendar],asof=iso(target),event_groups=groups)
 row=dict(symbol=symbol,display_name=name,data_date=str(target),groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='TRUE'),pending_groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='UNKNOWN'),latest_new_anchor=str(next((current['groups'][g].get('anchor_date') for g in GROUPS if current['groups'][g].get('anchor_date')), '') or ''),reasons='|'.join(sorted({s for g in GROUPS for s in current['groups'][g].get('reasons',[])})),risk_clear=current.get('risk',{}).get('status','UNKNOWN'),evaluation=current,statistics=statistics,historical_coverage=cache['coverage'],qualification=q)
 if chart_capture is not None and row['groups'] and captured:chart_capture(symbol,bars,captured[0])
 return row,cache,cachefile

def materialize_daily_product(*,data_root,target,formula_result=None,symbols=None,history_dates=(),evaluate=None,output_root=None,original_charts=True,chart_png_renderer=None):
 """Called once from original run_a; no historical loop in normal daily mode."""
 context=SourceContext(data_root,target)
 if output_root is not None:context.root=Path(output_root).resolve()
 root=context.root;context.unchanged()
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
  indexfile=root/'index.json';index=json.loads(indexfile.read_text()) if indexfile.is_file() else dict(schema_version='v4.a_share.daily_product_index.v1',dates={})
  index['dates'][str(target)]=manifest_ref;index['latest_date']=max(index['dates']);index['latest']=index['dates'][index['latest_date']]
  if chart_descriptor is not None:index.setdefault('original_charts',{})[str(target)]=chart_descriptor
  save(indexfile,index)
  event=dict(schema_version='v4.a_share.daily_completion.v1',event_id=digest(manifest),data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],artifact=artifact,manifest=manifest_ref,processed_count=len(rows),source_universe_count=len(context.scope),unknown_count=unknown,status=product['status'],**FLAGS)
  if chart_descriptor is not None:
   event['original_charts']=chart_descriptor;event['event_id']=digest(dict(numeric_manifest=manifest_ref,original_charts=chart_descriptor))
  save(root/'events/latest.json',event)
 return dict(manifest=manifest_ref,artifact=artifact,status=product['status'],data_date=str(target),source_generation=context.generation,processed_count=len(rows),unique_count=len(candidates),unknown_count=unknown,history_status=product['history_status'],**FLAGS)


def _kb_supplement_types():
 """Explicit typed wide schema for the 81 append-only scoped fields."""
 import pyarrow as pa
 from ops.kb_supplemental_fields import DICTIONARY_FIELDS
 from ops.kb_anomaly_events import PROCESS_FIELDS
 path=Path(__file__).resolve().parents[1]/'contracts/a_share_kb_full_supplement_v1.json'
 spec=json.loads(path.read_text())
 if (tuple(spec['dictionary_fields'])!=DICTIONARY_FIELDS or tuple(spec['process_fields'])!=PROCESS_FIELDS
     or len(spec['f10_fields'])!=23):raise ValueError('SCOPED_KB_CONTRACT_FIELDS_CONFLICT')
 names=DICTIONARY_FIELDS+tuple(spec['f10_fields'])+PROCESS_FIELDS
 if len(names)!=81 or len(set(names))!=81:raise ValueError('SCOPED_KB_FIELD_COUNT_CONFLICT')
 booleans={'kb_yidong_above_60d','kb_b1_pass_30','kb_yidong_strong_wave','kb_yidong_ground_volume',
           'kb_yidong_support_ok','kb_yidong_resumed','kb_yidong_volume_resumed','kb_yidong_breakout'}
 integers={'kb_brick_count','kb_double_gun_gap_days','kb_concept_count','kb_gudongrenshu_asof','kb_finance_asof',
           'kb_ipo_date','kb_yidong_persistence_days5','kb_yidong_anchor_date','kb_yidong_peak_date',
           'kb_yidong_pullback_date','kb_yidong_resume_date'}
 strings={'kb_yidong_type','kb_brick_trend','kb_brick_action_desc','kb_violence_k_type','kb_signal',
          'kb_latest_announcement','kb_capital_action','kb_dividend_plan','kb_yidong_origin_class','kb_yidong_origin_ma60_class'}
 key_type=pa.list_(pa.struct([pa.field('date',pa.int64()),pa.field('close',pa.float64()),pa.field('pct',pa.float64()),
                             pa.field('type',pa.string()),pa.field('body_pct',pa.float64()),pa.field('vol_ratio',pa.float64()),pa.field('is_latest',pa.bool_())]))
 fields=[]
 for name in names:
  typ=(pa.bool_() if name in booleans else pa.int64() if name in integers else pa.string() if name in strings else
       key_type if name=='kb_key_k_list' else pa.list_(pa.string()) if name=='kb_concepts' else pa.float64())
  fields.append(pa.field(name,typ))
 return pa.schema(fields),spec,reference(path)


def _kb_event_schema():
 import pyarrow as pa
 dates={'asof_date','anchor_date','crossing_date','peak_date','pullback_date','resume_date','ground_tie_count'}
 flags={'complete_20','ground_volume','yellow_close_held','yellow_low_held','anchor_low_held','volume_resumed',
        'breakout','today_resumed','today_volume_resumed','today_breakout'}
 strings={'symbol','state','origin_line_version','origin_class','origin_class_3pct','ma60_class'}
 names=('symbol','asof_date','anchor_date','state','complete_20','origin_line_version','origin_distance_pct','origin_class',
        'origin_class_3pct','ma60_distance_pct','ma60_class','crossing_date','anchor_low','peak_date','peak_close',
        'peak_high','rally_high','pullback_date','resume_date','volume_vs_anchor','volume_vs_rally_peak',
        'volume_vs_rally_mean','ground_volume','ground_tie_count','yellow_slope','yellow_close_held','yellow_low_held',
        'anchor_low_held','volume_resumed','breakout','today_resumed','today_volume_resumed','today_breakout')
 return pa.schema([pa.field(name,pa.string() if name in strings else pa.int64() if name in dates else
                            pa.bool_() if name in flags else pa.float64()) for name in names])


def _kb_write_parquet(path,table):
 import pyarrow.parquet as pq
 from ops.research_panel_qfq import sha as streamed_sha
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():raise ValueError('SCOPED_KB_OUTPUT_EXISTS_WITHOUT_REUSABLE_RECEIPT:'+str(path))
 temp=path.with_name('.'+path.name+'.'+str(os.getpid())+'.pending')
 with temp.open('xb') as handle:
  pq.write_table(table,handle,compression='zstd');handle.flush();os.fsync(handle.fileno())
 os.replace(temp,path)
 return dict(path=str(path.resolve()),sha256=streamed_sha(path),bytes=path.stat().st_size)


def _kb_old_columns_identical(old,saved):
 """Compare exact floating bits, distinguishing valid NaN from Arrow null."""
 import numpy as np
 import pyarrow as pa
 if not old.schema.equals(saved.schema,check_metadata=False):return False
 for name in old.column_names:
  a=old.column(name).combine_chunks();b=saved.column(name).combine_chunks()
  if pa.types.is_floating(a.type):
   mask_a=np.asarray(a.is_null());mask_b=np.asarray(b.is_null())
   if not np.array_equal(mask_a,mask_b):return False
   av=a.to_numpy(zero_copy_only=False);bv=b.to_numpy(zero_copy_only=False)
   unsigned=np.dtype('u'+str(av.dtype.itemsize))
   if not np.array_equal(av.view(unsigned)[~mask_a],bv.view(unsigned)[~mask_b]):return False
  elif not a.equals(b):return False
 return True


def _kb_scoped_stock_worker(payload):
 """Existing owner stock-asset step: reuse parents and persist only additions."""
 import pyarrow as pa
 import pyarrow.parquet as pq
 from ops.kb_supplemental_fields import project_dictionary_fields
 from ops.kb_anomaly_events import project_anomaly_events
 from ops.research_panel_f10 import project_observed_history
 from ops.research_panel_qfq import sha as streamed_sha
 symbol,selector,backtest,f10_ref,f10_reason,identity,root=payload
 root=Path(root)/symbol;receipt_path=root/'receipt.json'
 if receipt_path.exists():
  old=json.loads(receipt_path.read_text())
  if old.get('identity')!=identity or old.get('symbol')!=symbol:raise ValueError('SCOPED_KB_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
  for ref in old['assets'].values():
   if streamed_sha(Path(ref['path']))!=ref['sha256']:raise ValueError('SCOPED_KB_CHECKPOINT_SHA_DRIFT:'+symbol)
  return old
 selector=selector.sort_by('trade_date');backtest=backtest.sort_by('trade_date')
 # The selector stores YYYYMMDD as text; the backtest stores it as an integer.
 # Compare their actual dates without changing either original role's type.
 try:
  sd=[int(value) for value in selector.column('trade_date').to_pylist()]
  bd=[int(value) for value in backtest.column('trade_date').to_pylist()]
 except (ValueError,TypeError,OverflowError) as error:raise ValueError('SCOPED_KB_TRADE_DATE_INVALID:'+symbol) from error
 if (not sd or sd!=bd or len(sd)!=len(set(sd)) or any(x!=symbol for x in selector.column('ts_code').to_pylist())
     or any(x!=symbol for x in backtest.column('ts_code').to_pylist())):raise ValueError('SCOPED_KB_ROLE_IDENTITY_CONFLICT:'+symbol)
 schema,spec,_=_kb_supplement_types()
 if set(schema.names)&(set(selector.column_names)|set(backtest.column_names)):raise ValueError('SCOPED_KB_EXISTING_COLUMN_COLLISION:'+symbol)
 data=selector.to_pandas();supplement=project_dictionary_fields(data);process,events=project_anomaly_events(data)
 if len(supplement)!=len(sd) or len(process)!=len(sd):raise ValueError('SCOPED_KB_ROW_ALIGNMENT_CONFLICT:'+symbol)
 extras={}
 for field in schema:
  if field.name in supplement:
   extras[field.name]=pa.array(supplement[field.name].tolist(),type=field.type,from_pandas=True)
  elif field.name in process:
   extras[field.name]=pa.array(process[field.name].tolist(),type=field.type,from_pandas=True)
  else:
   # The captured F10 observations are later than the market-history rows.
   # They are separately bound below; no current value is backfilled into bars.
   extras[field.name]=pa.nulls(len(sd),type=field.type)
 meta=canonical(dict(schema='v4.a_share.scoped_kb_asset.v1',symbol=symbol,identity=identity,
                     scope='TOP200_PARTIAL',historical_PIT=False,**FLAGS))
 refs={};role_tables={}
 for role,old in (('selector',selector),('backtest',backtest)):
  new=old
  for field in schema:new=new.append_column(field,extras[field.name])
  metadata=dict(new.schema.metadata or {});metadata[b'v4_scoped_kb_asset_v1']=meta
  new=new.replace_schema_metadata(metadata);ref=_kb_write_parquet(root/(role+'.parquet'),new)
  saved=pq.read_table(ref['path'])
  if not _kb_old_columns_identical(old,saved.select(old.column_names)):raise ValueError('SCOPED_KB_OLD_VALUES_CHANGED:'+symbol+':'+role)
  if any(not saved.column(name).combine_chunks().equals(extras[name]) for name in schema.names):raise ValueError('SCOPED_KB_EXTRA_READBACK_CONFLICT:'+symbol+':'+role)
  refs[role]=ref;role_tables[role]=saved
 for name in schema.names:
  if not role_tables['selector'].column(name).equals(role_tables['backtest'].column(name)):
   raise ValueError('SCOPED_KB_ROLE_VALUE_CONFLICT:'+symbol+':'+name)
 event_schema=_kb_event_schema()
 records=[dict(record,symbol=symbol) for record in events]
 event_table=pa.Table.from_pylist(records,schema=event_schema)
 if event_table.num_rows < len(sd):raise ValueError('SCOPED_KB_EVENT_COVERAGE_CONFLICT:'+symbol)
 refs['events']=_kb_write_parquet(root/'events.parquet',event_table)
 if f10_ref:
  snap=json.loads(checked(f10_ref).read_text())
  if snap.get('symbol')!=symbol:raise ValueError('SCOPED_KB_F10_SYMBOL_CONFLICT:'+symbol)
  company=project_observed_history(snap);company['source_snapshot']=f10_ref;company['f10_status']='OBSERVED'
 else:
  company=dict(schema='v4.a_share.f10_observed_history.v1',symbol=symbol,f10_status='UNKNOWN',reason=f10_reason,
               historical_PIT=False,**FLAGS)
 refs['company']=save(root/'company.json',company,immutable=True);refs['company']['bytes']=Path(refs['company']['path']).stat().st_size
 counts={}
 for name in schema.names:
  array=extras[name];counts[name]=dict(known=len(array)-array.null_count,unknown=array.null_count)
 result=dict(schema='v4.a_share.scoped_kb_stock_receipt.v1',status='UPDATED',symbol=symbol,identity=identity,
             rows=len(sd),first_date=int(sd[0]),last_date=int(sd[-1]),assets=refs,
             role_columns={'selector':len(selector.column_names)+len(schema),'backtest':len(backtest.column_names)+len(schema)},
             additions=schema.names,field_counts=counts,event_rows=len(events),f10_status=company['f10_status'],
             f10_reason=f10_reason if not f10_ref else None,old_values_equal=True,two_roles_equal=True,
             historical_PIT=False,**FLAGS)
 save(receipt_path,result,immutable=True)
 return result


def materialize_scoped_kb_assets(*,candidate_ref,validation_ref,f10_receipts,output_root,selected_symbols=None,workers=10):
 """Materialize precomputed per-stock assets at the existing daily owner boundary.

 It never writes CURRENT, a shared product index, a running release, or a
 scheduler.  Passing three selected symbols enables a canary whose immutable
 stock receipts are reused by a later full-scope invocation with the same
 identity.  All current F10 snapshots remain separate observed-at assets.
 """
 from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
 import multiprocessing
 import pyarrow.compute as pc
 import pyarrow.parquet as pq
 from ops.research_panel_qfq import sha as streamed_sha
 if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=14:raise ValueError('SCOPED_KB_WORKER_LIMIT')
 candidate=json.loads(checked(candidate_ref).read_text());validation=json.loads(checked(validation_ref).read_text())
 if (candidate.get('schema')!='qfq_scoped_kb_candidate.v3' or candidate.get('scope')!='TOP200_PARTIAL'
     or validation.get('status')!='PASS' or validation.get('generation_id')!=candidate.get('generation_id')
     or validation.get('candidate_receipt')!=candidate_ref or any(candidate.get(k)!=v for k,v in FLAGS.items())):
  raise ValueError('SCOPED_KB_PARENT_VALIDATION_CONFLICT')
 source_scope=json.loads(checked(candidate['scope_ref']).read_text())
 target=[x['symbol'] for x in source_scope['top200']]
 entries=candidate['per_symbol'];by_symbol={x['symbol']:x for x in entries}
 if (len(target)!=200 or len(set(target))!=200 or len(entries)!=200 or len(by_symbol)!=200
     or set(target)!=set(by_symbol)):raise ValueError('SCOPED_KB_ORIGINAL_TOP200_CONFLICT')
 available=sorted(x['symbol'] for x in entries if x['status'] in ('UPDATED','REUSED'))
 missing=[x for x in entries if x['status']=='UNKNOWN']
 if len(available)!=197 or len(missing)!=3:raise ValueError('SCOPED_KB_ADMISSION_COUNT_CONFLICT')
 selected=available if selected_symbols is None else sorted(set(selected_symbols))
 if not selected or not set(selected)<=set(available) or selected_symbols is not None and len(selected)!=len(selected_symbols):
  raise ValueError('SCOPED_KB_REQUEST_OUTSIDE_AVAILABLE_UNIVERSE')
 schema,spec,contract_ref=_kb_supplement_types()
 if candidate['generation_id']!=spec['parent_generation']:raise ValueError('SCOPED_KB_CONTRACT_GENERATION_CONFLICT')
 snapshots={}; failures={}
 for receipt_ref in f10_receipts:
  r=json.loads(checked(receipt_ref).read_text())
  if (r.get('schema')!='v4.a_share.f10_daily_receipt.v1' or r.get('source_generation')!=candidate['source_generation']
      or r.get('status') not in ('COMPLETE','PARTIAL') or r.get('historical_PIT') is not False
      or any(r.get(k)!=v for k,v in FLAGS.items())):raise ValueError('SCOPED_KB_F10_RECEIPT_CONFLICT')
  checkpoint=json.loads(checked(r['checkpoint']).read_text());items=checkpoint.get('items',{})
  if r.get('observed')!=len(items) or not set(items)<=set(available):raise ValueError('SCOPED_KB_F10_SCOPE_CONFLICT')
  for symbol,ref in items.items():
   if symbol in snapshots:raise ValueError('SCOPED_KB_F10_DUPLICATE_SOURCE:'+symbol)
   snapshots[symbol]=ref
  failures.update(r.get('failures',{}))
 for symbol in snapshots:failures.pop(symbol,None)
 identity=dict(schema='v4.a_share.scoped_kb_asset_identity.v1',scope_sha256=candidate['scope_ref']['sha256'],
     parent_candidate=candidate_ref,parent_validation=validation_ref,source_generation=candidate['source_generation'],
     parent_schema_generation=candidate['generation_id'],contract=contract_ref,f10_receipts=f10_receipts,
     producer_sha256=streamed_sha(Path(__file__)),
     supplemental_authority_sha256=streamed_sha(Path(__file__).with_name('kb_supplemental_fields.py')),
     anomaly_authority_sha256=streamed_sha(Path(__file__).with_name('kb_anomaly_events.py')),
     f10_projection_sha256=streamed_sha(Path(__file__).with_name('research_panel_f10.py')))
 generation=digest(identity);root=Path(output_root).resolve()/('scope197_asset_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 # A prior full validation is reused only after the exact staged bytes are pinned.
 paths={};stamps={}
 for role in ('selector','backtest'):
  item=candidate['staged'][role];path=Path(item['path'])
  if path.is_symlink() or path.resolve(strict=True)!=path or streamed_sha(path)!=item['sha256']:
   raise ValueError('SCOPED_KB_PARENT_BYTES_DRIFT:'+role)
  s=path.stat();stamps[role]=(s.st_size,s.st_mtime_ns,s.st_ino);paths[role]=path
  expected=312 if role=='selector' else 164
  if len(pq.read_schema(path).names)!=expected:raise ValueError('SCOPED_KB_PARENT_COLUMN_COUNT_CONFLICT:'+role)
 print('SCOPED_KB_SOURCE_VERIFIED '+generation,flush=True)
 tables={}
 for role in ('selector','backtest'):
  tables[role]=pq.read_table(paths[role],filters=[('ts_code','in',selected)])
  if tables[role].num_rows!=sum(by_symbol[s]['rows'] for s in selected):raise ValueError('SCOPED_KB_SOURCE_ROW_COUNT_CONFLICT:'+role)
  s=paths[role].stat()
  if (s.st_size,s.st_mtime_ns,s.st_ino)!=stamps[role]:raise ValueError('SCOPED_KB_PARENT_MOVED_DURING_READ:'+role)
 print('SCOPED_KB_SOURCE_READ rows='+str(tables['selector'].num_rows),flush=True)
 def payloads():
  for symbol in selected:
   role_tables=[]
   for role in ('selector','backtest'):
    tab=tables[role];role_tables.append(tab.filter(pc.equal(tab.column('ts_code'),symbol)))
   reason=(failures.get(symbol) or {}).get('reason') or 'F10_SNAPSHOT_NOT_AVAILABLE_IN_BOUND_RECEIPTS'
   yield (symbol,role_tables[0],role_tables[1],snapshots.get(symbol),reason,identity,str(root/'stocks'))
 results={};pending={};iterator=iter(payloads())
 with ProcessPoolExecutor(max_workers=min(workers,len(selected)),mp_context=multiprocessing.get_context('spawn')) as pool:
  def submit():
   while len(pending)<min(workers*2,len(selected)):
    try:p=next(iterator)
    except StopIteration:return
    pending[pool.submit(_kb_scoped_stock_worker,p)]=p[0]
  submit()
  while pending:
   done,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in done:
    symbol=pending.pop(future);item=future.result();results[symbol]=item
    if item['rows']!=by_symbol[symbol]['rows'] or item['first_date']!=by_symbol[symbol]['first_date']:
     raise ValueError('SCOPED_KB_STOCK_COVERAGE_CONFLICT:'+symbol)
    save(root/'progress.json',dict(schema='v4.a_share.scoped_kb_progress.v1',generation=generation,
         completed=len(results),requested=len(selected),full_scope=197,last_symbol=symbol,**FLAGS))
    if len(results)%20==0 or len(results)==len(selected):print('SCOPED_KB_PROGRESS '+str(len(results))+'/'+str(len(selected)),flush=True)
   submit()
 full=set(results)==set(available)
 aggregate={name:{'known':sum(r['field_counts'][name]['known'] for r in results.values()),
                  'unknown':sum(r['field_counts'][name]['unknown'] for r in results.values())} for name in schema.names}
 summary=dict(schema='v4.a_share.scoped_kb_assets_receipt.v1',status='READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',
      scope='TOP200_PARTIAL',generation=generation,identity=identity,source_date='20261030',
      target_manifest=candidate['scope_ref'],original_top200_count=200,available_count=197,processed_count=len(results),
      rows=sum(x['rows'] for x in results.values()),per_symbol=[results[s] for s in sorted(results)],
      unknown_symbols=missing,columns={'selector':393,'backtest':245},additional_columns=schema.names,
      field_counts=aggregate,f10_observed=sum(x['f10_status']=='OBSERVED' for x in results.values()),
      f10_unknown=sum(x['f10_status']!='OBSERVED' for x in results.values()),
      old_values_equal=all(x['old_values_equal'] for x in results.values()),
      two_roles_equal=all(x['two_roles_equal'] for x in results.values()),
      event_policy='ALL_ELIGIBLE_ANCHORS_20BARS_BY_ASOF; COVERAGE_ROWS_SUPPORT_TRISTATE_OR',
      global_current_unchanged_by_this_operation=True,historical_PIT=False,**FLAGS)
 if full and summary['rows']!=637839:raise ValueError('SCOPED_KB_FULL_HISTORY_ROW_COUNT_CONFLICT')
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 return dict(status=summary['status'],generation=generation,manifest=manifest,processed_count=len(results),
             rows=summary['rows'],f10_observed=summary['f10_observed'],f10_unknown=summary['f10_unknown'],**FLAGS)


def revise_scoped_company_assets(*,manifest_ref,validation_ref,output_root,selected_symbols=None):
 """Append current-vs-prior company facts; reuse every price/event asset."""
 from ops.research_panel_f10 import project_company_comparison
 from ops.research_panel_qfq import sha as streamed_sha
 old=json.loads(checked(manifest_ref).read_text());validation=json.loads(checked(validation_ref).read_text())
 if (old.get('schema')!='v4.a_share.scoped_kb_assets_receipt.v1' or old.get('processed_count')!=197
     or old.get('rows')!=637839 or validation.get('status')!='PASS'
     or validation.get('generation')!=old.get('generation')
     or validation.get('source_manifest_sha256')!=manifest_ref['sha256']
     or any(old.get(k)!=v for k,v in FLAGS.items())):raise ValueError('SCOPED_COMPANY_PARENT_CONFLICT')
 rows={r['symbol']:r for r in old['per_symbol']}
 if len(rows)!=197:raise ValueError('SCOPED_COMPANY_SYMBOL_CONFLICT')
 selected=sorted(rows) if selected_symbols is None else sorted(set(selected_symbols))
 if not selected or not set(selected)<=set(rows) or selected_symbols is not None and len(selected)!=len(selected_symbols):
  raise ValueError('SCOPED_COMPANY_OUTSIDE_SCOPE')
 identity={'schema':'v4.a_share.scoped_kb_company_revision_identity.v1',
           'parent_manifest':manifest_ref,'parent_validation':validation_ref,
           'parent_price_asset_generation':old['generation'],
           'company_projection_sha256':streamed_sha(Path(__file__).with_name('research_panel_f10.py')),
           'daily_owner_sha256':streamed_sha(Path(__file__))}
 generation=digest(identity);root=Path(output_root).resolve()/('company_revision_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 result=[];coverage=Counter()
 for symbol in selected:
  old_stock=rows[symbol];source_company=old_stock['assets']['company'];previous=json.loads(checked(source_company).read_text())
  if previous.get('symbol')!=symbol:raise ValueError('SCOPED_COMPANY_OLD_SYMBOL_CONFLICT:'+symbol)
  path=root/'stocks'/(symbol+'.json')
  if path.exists():
   company=json.loads(path.read_text())
   if company.get('revision_identity')!=identity or company.get('source_company')!=source_company:
    raise ValueError('SCOPED_COMPANY_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
   ref=reference(path)
  else:
   if previous.get('f10_status')=='OBSERVED':
    snapshot=json.loads(checked(previous['source_snapshot']).read_text())
    if snapshot.get('symbol')!=symbol:raise ValueError('SCOPED_COMPANY_SNAPSHOT_CONFLICT:'+symbol)
    company=project_company_comparison(snapshot);company['source_snapshot']=previous['source_snapshot'];company['f10_status']='OBSERVED'
   elif previous.get('f10_status')=='UNKNOWN':
    company=dict(schema='v4.a_share.f10_observed_history.v1',symbol=symbol,f10_status='UNKNOWN',
         reason=previous.get('reason'),comparison={'status':'UNKNOWN_SOURCE','reason':previous.get('reason'),
         'latest_report_period':None,'prior_report_period':None,'captured_at':None,'source_updated_date':None},
         historical_PIT=False,**FLAGS)
   else:raise ValueError('SCOPED_COMPANY_SOURCE_STATUS_CONFLICT:'+symbol)
   company['source_company']=source_company;company['revision_identity']=identity
   company['price_asset_generation']=old['generation'];company['company_revision']=generation
   ref=save(path,company,immutable=True)
  ref['bytes']=path.stat().st_size
  item=dict(old_stock);item['assets']=dict(old_stock['assets']);item['assets']['company']=ref
  item['source_company']=source_company;item['company_revision']=generation;result.append(item)
  coverage[company['f10_status']]+=1
  if company['f10_status']=='OBSERVED':
   comparison=company['comparison'];coverage['latest_report_period_known']+=comparison.get('latest_report_period') is not None
   coverage['prior_report_period_known']+=comparison.get('prior_report_period') is not None
   for name,metric in comparison['financial_metrics'].items():
    coverage['financial_'+name+'_latest']+=metric['latest'] is not None
    coverage['financial_'+name+'_prior']+=metric['prior'] is not None
   coverage['holders_comparable']+=comparison['shareholder_count']['status']=='COMPLETE'
   coverage['fund_ratio_comparable']+=comparison['holdings']['fund_hold_ratio_pct']['status']=='COMPLETE'
   coverage['holder_sources_differ']+=comparison['shareholder_count']['source_comparison']=='DIFFERENT_VALUES_DIFFERENT_SOURCE_TIMES'
  if len(result)%50==0 or len(result)==len(selected):print('SCOPED_COMPANY_PROGRESS '+str(len(result))+'/'+str(len(selected)),flush=True)
 full=len(result)==197
 summary=dict(old);summary.update(schema='v4.a_share.scoped_kb_assets_company_revision.v1',
      status='READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',
      generation=generation,price_asset_generation=old['generation'],company_revision_identity=identity,
      parent_manifest=manifest_ref,parent_validation=validation_ref,processed_count=len(result),
      rows=sum(r['rows'] for r in result),per_symbol=result,company_coverage=dict(coverage),
      old_price_and_event_assets_reused=True,source_date='20261030',
      company_current_policy='LATEST_OBSERVED_AT_CAPTURE_WITH_PRIOR_PERIOD; NO_HISTORICAL_BAR_BACKFILL')
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 return dict(status=summary['status'],generation=generation,price_asset_generation=old['generation'],
             manifest=manifest,processed_count=len(result),company_coverage=dict(coverage),**FLAGS)


def _kb_display_stock_worker(payload):
 """Project one already-verified paired stock asset without recomputation."""
 import pyarrow.parquet as pq
 from ops.research_panel_qfq import sha as streamed_sha
 stock,excluded,identity,root=payload;symbol=stock['symbol'];root=Path(root)/symbol;receipt=root/'receipt.json'
 if receipt.exists():
  old=json.loads(receipt.read_text())
  if old.get('identity')!=identity or old.get('symbol')!=symbol:raise ValueError('SCOPED_DISPLAY_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
  for item in old['display_roles'].values():
   if streamed_sha(Path(item['artifact']['path']))!=item['artifact']['sha256']:raise ValueError('SCOPED_DISPLAY_CHECKPOINT_SHA_DRIFT:'+symbol)
  return old
 outputs={}
 for role in ('selector','backtest'):
  parent=stock['assets'][role];path=Path(parent['path'])
  if streamed_sha(path)!=parent['sha256']:raise ValueError('SCOPED_DISPLAY_PARENT_SHA_DRIFT:'+symbol+':'+role)
  before=pq.read_table(path);expected=393 if role=='selector' else 245
  if len(before.column_names)!=expected or len(before)!=stock['rows']:raise ValueError('SCOPED_DISPLAY_PARENT_SCHEMA_CONFLICT:'+symbol+':'+role)
  removed=[name for name in excluded if name in before.column_names]
  kept=[name for name in before.column_names if name not in excluded]
  if len(removed)!=(25 if role=='selector' else 8) or 'kb_hold_volume_ok_reason' not in kept:
   raise ValueError('SCOPED_DISPLAY_POLICY_CONFLICT:'+symbol+':'+role)
  view=before.select(kept);metadata=dict(view.schema.metadata or {})
  metadata[b'a_share_top200_display_projection_v1']=canonical(dict(schema='a_share_top200_display_projection_v1',
     symbol=symbol,role=role,source_full_sha256=parent['sha256'],identity=identity,historical_PIT=False,**FLAGS))
  view=view.replace_schema_metadata(metadata);ref=_kb_write_parquet(root/(role+'.parquet'),view);read=pq.read_table(ref['path'])
  if not _kb_old_columns_identical(before.select(kept),read):raise ValueError('SCOPED_DISPLAY_RETAINED_VALUE_DRIFT:'+symbol+':'+role)
  outputs[role]={'artifact':ref,'source_full':parent,'rows':len(read),'columns':len(read.column_names),
                 'removed_fields':removed,'retained_values_equal':True}
 result={'schema':'v4.a_share.scoped_kb_display_stock.v1','status':'PROJECTED','symbol':symbol,'identity':identity,
         'rows':stock['rows'],'first_date':stock['first_date'],'last_date':stock['last_date'],'display_roles':outputs,
         'historical_PIT':False,**FLAGS}
 save(receipt,result,immutable=True)
 return result


def materialize_scoped_kb_display(*,company_manifest_ref,company_validation_ref,output_root,selected_symbols=None,workers=10):
 """Materialize the authorized 25/8-column display exclusion in existing assets."""
 from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
 import multiprocessing
 from ops.research_panel_qfq import sha as streamed_sha
 if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=14:raise ValueError('SCOPED_DISPLAY_WORKER_LIMIT')
 source=json.loads(checked(company_manifest_ref).read_text());valid=json.loads(checked(company_validation_ref).read_text())
 if (source.get('schema')!='v4.a_share.scoped_kb_assets_company_revision.v1' or source.get('processed_count')!=197
     or source.get('rows')!=637839 or valid.get('status')!='PASS'
     or valid.get('company_manifest_sha256')!=company_manifest_ref['sha256']
     or any(source.get(k)!=v for k,v in FLAGS.items())):raise ValueError('SCOPED_DISPLAY_PARENT_CONFLICT')
 policy_path=Path(__file__).resolve().parents[1]/'contracts/a_share_top200_display_projection_v1.json'
 policy=json.loads(policy_path.read_text());policy_ref=reference(policy_path);excluded=policy['excluded_from_display_projection']
 if (policy.get('schema')!='a_share_top200_display_projection_v1' or len(excluded)!=25 or len(set(excluded))!=25
     or policy.get('parent_single_stock_policy_sha256')!='da82c1fc206730c092ec7164c665dde9e0553af8be33b7d0b8f14047fcf47a4c'
     or any(policy.get(k)!=v for k,v in FLAGS.items())):raise ValueError('SCOPED_DISPLAY_POLICY_IDENTITY_CONFLICT')
 stocks={x['symbol']:x for x in source['per_symbol']}
 if len(stocks)!=197:raise ValueError('SCOPED_DISPLAY_SCOPE_CONFLICT')
 selected=sorted(stocks) if selected_symbols is None else sorted(set(selected_symbols))
 if not selected or not set(selected)<=set(stocks) or selected_symbols is not None and len(selected)!=len(selected_symbols):
  raise ValueError('SCOPED_DISPLAY_REQUEST_OUTSIDE_SCOPE')
 identity={'schema':'v4.a_share.scoped_kb_display_identity.v1','company_manifest':company_manifest_ref,
           'company_validation':company_validation_ref,'display_policy':policy_ref,
           'price_asset_generation':source['price_asset_generation'],'company_generation':source['generation'],
           'daily_owner_sha256':streamed_sha(Path(__file__))}
 generation=digest(identity);root=Path(output_root).resolve()/('display_revision_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 pending={};done={};iterator=iter(selected)
 with ProcessPoolExecutor(max_workers=min(workers,len(selected)),mp_context=multiprocessing.get_context('spawn')) as pool:
  def submit():
   while len(pending)<min(workers*2,len(selected)):
    try:symbol=next(iterator)
    except StopIteration:return
    pending[pool.submit(_kb_display_stock_worker,(stocks[symbol],excluded,identity,str(root/'stocks')))]=symbol
  submit()
  while pending:
   finished,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in finished:
    symbol=pending.pop(future);projection=future.result();original=stocks[symbol]
    item=dict(original);item['assets']=dict(original['assets'])
    item['archive_roles']={role:original['assets'][role] for role in ('selector','backtest')}
    for role in ('selector','backtest'):item['assets'][role]=projection['display_roles'][role]['artifact']
    item['display_roles']=projection['display_roles'];item['display_generation']=generation
    done[symbol]=item
    save(root/'progress.json',dict(schema='v4.a_share.scoped_kb_display_progress.v1',generation=generation,
         completed=len(done),requested=len(selected),last_symbol=symbol,**FLAGS))
    if len(done)%50==0 or len(done)==len(selected):print('SCOPED_DISPLAY_PROGRESS '+str(len(done))+'/'+str(len(selected)),flush=True)
   submit()
 full=len(done)==197
 summary=dict(source);summary.update(schema='v4.a_share.scoped_kb_display_manifest.v1',
   status='READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',generation=generation,display_identity=identity,
   company_generation=source['generation'],price_asset_generation=source['price_asset_generation'],
   company_manifest=company_manifest_ref,company_validation=company_validation_ref,
   processed_count=len(done),rows=sum(x['rows'] for x in done.values()),per_symbol=[done[s] for s in sorted(done)],
   columns={'selector':368,'backtest':237},excluded_selector=excluded,
   excluded_backtest=[name for name in excluded if name in next(iter(done.values()))['display_roles']['backtest']['removed_fields']],
   originals_retained_as_archive=True,retained_values_equal=all(v['display_roles'][r]['retained_values_equal'] for v in done.values() for r in ('selector','backtest')),
   display_scope='TOP200_PARTIAL_RESEARCH_ONLY; NOT_DRIVER_OR_MODEL_INPUT')
 if full and summary['rows']!=637839:raise ValueError('SCOPED_DISPLAY_ROW_COUNT_CONFLICT')
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 return dict(status=summary['status'],generation=generation,manifest=manifest,processed_count=len(done),rows=summary['rows'],
             columns=summary['columns'],excluded_selector=len(summary['excluded_selector']),excluded_backtest=len(summary['excluded_backtest']),**FLAGS)


def _kb_r3_stock_worker(payload):
 """Apply the exact R3 field lock to one precomputed full-history pair."""
 import pyarrow as pa
 import pyarrow.parquet as pq
 from ops.kb_action_authority import INPUT_FIELDS as ACTION_INPUTS,project_action,action_rule_sha256
 from ops.kb_yidong_authority import project_yidong_history,rule_sha256 as anomaly_rule_sha256
 from ops.kb_rebuild_authority import project_rebuild
 from ops.research_panel_qfq import sha as streamed_sha
 stock,contract,identity,root=payload;symbol=stock['symbol'];root=Path(root)/symbol;receipt=root/'receipt.json'
 if receipt.exists():
  old=json.loads(receipt.read_text())
  if old.get('identity')!=identity or old.get('symbol')!=symbol:raise ValueError('R3_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
  for section in ('calculation_roles','display_roles'):
   for ref in old[section].values():
    if streamed_sha(Path(ref['path']))!=ref['sha256']:raise ValueError('R3_CHECKPOINT_SHA_DRIFT:'+symbol)
  return old
 original={}
 for role in ('selector','backtest'):
  ref=stock['archive_roles'][role];path=Path(ref['path'])
  if streamed_sha(path)!=ref['sha256']:raise ValueError('R3_ARCHIVE_SHA_DRIFT:'+symbol+':'+role)
  original[role]=pq.read_table(path).sort_by('trade_date')
  if len(original[role])!=stock['rows'] or len(original[role].column_names)!=(393 if role=='selector' else 245):
   raise ValueError('R3_ARCHIVE_SCHEMA_CONFLICT:'+symbol+':'+role)
 selector=original['selector'];n=len(selector)
 sd=[int(x) for x in selector['trade_date'].to_pylist()];bd=[int(x) for x in original['backtest']['trade_date'].to_pylist()]
 if sd!=bd or len(set(sd))!=n:raise ValueError('R3_ROLE_DATE_CONFLICT:'+symbol)
 if selector['kb_rebuild'].null_count!=n or original['backtest']['kb_rebuild'].null_count!=n:
  raise ValueError('R3_REBUILD_ALREADY_KNOWN_CONFLICT:'+symbol)
 compute_cols=sorted(set(ACTION_INPUTS)|{'trade_date','open','close','volume','pct_chg','ma60','zge_yellow_line','kb_yidong','kb_yidong_type'})
 data=selector.select(compute_cols).to_pandas()
 rebuild=pa.array(project_rebuild(data),type=pa.bool_(),from_pandas=True)
 actions=[project_action(row,rule_sha256=action_rule_sha256()) for row in data[list(ACTION_INPUTS)].to_dict('records')]
 descriptions=project_yidong_history(data[['trade_date','open','close','volume','pct_chg','ma60','zge_yellow_line']].to_dict('records'),digest=anomaly_rule_sha256())
 native=selector['kb_yidong'].to_pylist();prior_type=selector['kb_yidong_type'].to_pylist()
 for i,(item,flag) in enumerate(zip(descriptions,native)):
  if flag is not None and item['kb_yidong_is'] is not None and flag!=item['kb_yidong_is']:
   raise ValueError('R3_NATIVE_ANOMALY_SOURCE_CONFLICT:'+symbol+':'+str(sd[i]))
  item['kb_yidong_is']=flag
  if flag is None:
   item['kb_yidong_type']=None
   if i>=64:item['kb_yidong_status']='NATIVE_SOURCE_INPUT_UNKNOWN'
  if item['kb_yidong_type']!=prior_type[i]:raise ValueError('R3_ANOMALY_TYPE_CONFLICT:'+symbol+':'+str(sd[i]))
 added={}
 for name in contract['action_fields']:added[name]=pa.array([x[name] for x in actions],type=pa.string(),from_pandas=True)
 ytypes={'bool':pa.bool_(),'string':pa.string(),'double':pa.float64(),'int8':pa.int8(),'int32':pa.int32()}
 from ops.kb_yidong_authority import FIELDS as YIDONG_TYPES
 if set(YIDONG_TYPES)!=set(contract['anomaly_fields']):raise ValueError('R3_YIDONG_CONTRACT_CONFLICT')
 for name in contract['anomaly_fields']:
  added[name]=pa.array([x[name] for x in descriptions],type=ytypes[YIDONG_TYPES[name]],from_pandas=True)
 for name in contract['supplemental_fields']:
  added[name]=selector[name].combine_chunks()
 company=json.loads(checked(stock['assets']['company']).read_text());concepts=None;concept_count=None
 if company.get('f10_status')=='OBSERVED' and company.get('concept_status')=='OBSERVED':
  items=company.get('concepts')
  if not isinstance(items,list) or not 0<len(items)<=127 or not all(isinstance(x,dict) and isinstance(x.get('name'),str) and x['name'] for x in items):
   raise ValueError('R3_CONCEPT_SOURCE_CONFLICT:'+symbol)
  names=[x['name'] for x in items]
  if len(names)!=len(set(names)):raise ValueError('R3_CONCEPT_DUPLICATE:'+symbol)
  concepts='、'.join(names);concept_count=len(names)
 calc_refs={};display_refs={};counts={};excluded=contract['excluded_fields'];derived_names=contract['action_fields']+contract['anomaly_fields']+contract['supplemental_fields']
 for role in ('selector','backtest'):
  source=original[role];base_count=233 if role=='selector' else 85;base=source.select(source.column_names[:base_count+78])
  if len([x for x in base.column_names if x.startswith('kb_')])!=78:raise ValueError('R3_EXISTING_KB_78_CONFLICT:'+role)
  index=base.schema.get_field_index('kb_rebuild');base=base.set_column(index,base.schema.field(index),rebuild)
  calc=base
  for name in derived_names:calc=calc.append_column(pa.field(name,added[name].type),added[name])
  if len(calc.column_names)!=(340 if role=='selector' else 192):raise ValueError('R3_CALCULATION_COLUMN_COUNT_CONFLICT:'+role)
  metadata=dict(calc.schema.metadata or {});metadata[b'a_share_top200_panel_r3_v1']=canonical(dict(identity=identity,symbol=symbol,role=role,view='CALCULATION',historical_PIT=False,**FLAGS))
  calc=calc.replace_schema_metadata(metadata);calc_ref=_kb_write_parquet(root/(role+'_calculation.parquet'),calc);calc_read=pq.read_table(calc_ref['path'])
  preserved=[name for name in base.column_names if name!='kb_rebuild']
  if not _kb_old_columns_identical(source.select(preserved),calc_read.select(preserved)):raise ValueError('R3_OLD_77_OR_BASE_DRIFT:'+symbol+':'+role)
  if not calc_read['kb_rebuild'].combine_chunks().equals(rebuild):raise ValueError('R3_REBUILD_READBACK_CONFLICT:'+symbol+':'+role)
  kept=[name for name in calc_read.column_names if name not in excluded];removed=[name for name in excluded if name in calc_read.column_names]
  if len(removed)!=(25 if role=='selector' else 8) or 'kb_hold_volume_ok_reason' not in kept:raise ValueError('R3_DISPLAY_DROP_CONFLICT:'+role)
  display=calc_read.select(kept)
  display=display.append_column(pa.field('kb_concepts',pa.string()),pa.array([None]*(n-1)+[concepts],type=pa.string()))
  display=display.append_column(pa.field('kb_concept_count',pa.int8()),pa.array([None]*(n-1)+[concept_count],type=pa.int8()))
  metadata=dict(display.schema.metadata or {});metadata[b'a_share_top200_panel_r3_v1']=canonical(dict(identity=identity,symbol=symbol,role=role,view='RESEARCH_DISPLAY',concept_observed_at=company.get('captured_at'),historical_PIT=False,**FLAGS))
  display=display.replace_schema_metadata(metadata);ref=_kb_write_parquet(root/(role+'_display.parquet'),display);view=pq.read_table(ref['path'])
  if len(view.column_names)!=(317 if role=='selector' else 186):raise ValueError('R3_DISPLAY_COLUMN_COUNT_CONFLICT:'+role)
  if not _kb_old_columns_identical(calc_read.select(kept),view.select(kept)):raise ValueError('R3_DISPLAY_VALUE_DRIFT:'+symbol+':'+role)
  if view['kb_concepts'].to_pylist()!=[None]*(n-1)+[concepts] or view['kb_concept_count'].to_pylist()!=[None]*(n-1)+[concept_count]:
   raise ValueError('R3_CONCEPT_TEMPORAL_CONFLICT:'+symbol+':'+role)
  calc_refs[role]=calc_ref;display_refs[role]=ref
  if role=='selector':
   for name in ['kb_rebuild']+derived_names:
    col=calc_read[name];counts[name]={'known':n-col.null_count,'unknown':col.null_count}
   counts['kb_concepts']={'known':1 if concepts is not None else 0,'unknown':n-(1 if concepts is not None else 0)}
  else:
   first=pq.read_table(calc_refs['selector']['path'],columns=['kb_rebuild']+derived_names)
   for name in ['kb_rebuild']+derived_names:
    if not first[name].combine_chunks().equals(calc_read[name].combine_chunks()):raise ValueError('R3_PAIR_VALUE_CONFLICT:'+symbol+':'+name)
 result={'schema':'v4.a_share.scoped_kb_r3_stock.v1','status':'UPDATED','symbol':symbol,'identity':identity,
   'rows':n,'first_date':sd[0],'last_date':sd[-1],'calculation_roles':calc_refs,'display_roles':display_refs,
   'field_counts':counts,'concept_observed_at':company.get('captured_at'),'concept_status':company.get('concept_status'),
   'old_77_and_baseline_equal':True,'rebuild_fixed':True,'paired_fields_equal':True,'historical_PIT':False,**FLAGS}
 save(receipt,result,immutable=True);return result


def materialize_scoped_kb_r3(*,display_manifest_ref,display_validation_ref,output_root,selected_symbols=None,workers=10):
 """Project the 107-field R3 lock without recomputing existing 77 fields."""
 from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
 import multiprocessing
 from ops.research_panel_qfq import sha as streamed_sha
 if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=14:raise ValueError('R3_WORKER_LIMIT')
 source=json.loads(checked(display_manifest_ref).read_text());validation=json.loads(checked(display_validation_ref).read_text())
 if (source.get('schema')!='v4.a_share.scoped_kb_display_manifest.v1' or source.get('processed_count')!=197
     or source.get('rows')!=637839 or validation.get('status')!='PASS'
     or validation.get('display_manifest_sha256')!=display_manifest_ref['sha256']
     or any(source.get(k)!=v for k,v in FLAGS.items())):raise ValueError('R3_PARENT_CONFLICT')
 path=Path(__file__).resolve().parents[1]/'contracts/a_share_top200_panel_r3_v1.json';contract=json.loads(path.read_text());contract_ref=reference(path)
 if (contract.get('schema')!='a_share_top200_panel_r3_v1' or len(contract['action_fields'])!=6
     or len(contract['anomaly_fields'])!=15 or len(contract['supplemental_fields'])!=8
     or len(contract['excluded_fields'])!=25 or any(contract.get(k)!=v for k,v in FLAGS.items())):raise ValueError('R3_CONTRACT_INVALID')
 stocks={x['symbol']:x for x in source['per_symbol']};selected=sorted(stocks) if selected_symbols is None else sorted(set(selected_symbols))
 if len(stocks)!=197 or not selected or not set(selected)<=set(stocks) or selected_symbols is not None and len(selected)!=len(selected_symbols):raise ValueError('R3_SYMBOL_SCOPE_CONFLICT')
 identity={'schema':'v4.a_share.scoped_kb_r3_identity.v1','source_display_manifest':display_manifest_ref,'source_display_validation':display_validation_ref,
           'r3_contract':contract_ref,'source_generation':source['identity']['source_generation'],
           'price_asset_generation':source['price_asset_generation'],'company_generation':source['company_generation'],
           'rebuild_source_sha256':'304544550c0a6cd34231a3f883c6c44a5ff881bc19c65f80cb2a5d7d9aec698d',
           'daily_owner_sha256':streamed_sha(Path(__file__)),'rebuild_authority_sha256':streamed_sha(Path(__file__).with_name('kb_rebuild_authority.py')),
           'action_authority_sha256':streamed_sha(Path(__file__).with_name('kb_action_authority.py')),
           'action_contract_sha256':streamed_sha(Path(__file__).resolve().parents[1]/'contracts/a_share_kb_action_v1.json'),
           'yidong_authority_sha256':streamed_sha(Path(__file__).with_name('kb_yidong_authority.py')),
           'yidong_contract_sha256':streamed_sha(Path(__file__).resolve().parents[1]/'contracts/a_share_kb_yidong_v1.json')}
 generation=digest(identity);root=Path(output_root).resolve()/('panel_r3_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 pending={};done={};iterator=iter(selected)
 with ProcessPoolExecutor(max_workers=min(workers,len(selected)),mp_context=multiprocessing.get_context('spawn')) as pool:
  def submit():
   while len(pending)<min(workers*2,len(selected)):
    try:s=next(iterator)
    except StopIteration:return
    pending[pool.submit(_kb_r3_stock_worker,(stocks[s],contract,identity,str(root/'stocks')))]=s
  submit()
  while pending:
   finished,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in finished:
    symbol=pending.pop(future);result=future.result();source_stock=stocks[symbol]
    item=dict(result);item['assets']={'selector':result['display_roles']['selector'],'backtest':result['display_roles']['backtest'],
       'events':source_stock['assets']['events'],'company':source_stock['assets']['company']}
    item['archive_roles']=source_stock['archive_roles'];item['f10_status']=source_stock['f10_status'];done[symbol]=item
    save(root/'progress.json',dict(schema='v4.a_share.scoped_kb_r3_progress.v1',generation=generation,completed=len(done),requested=len(selected),last_symbol=symbol,**FLAGS))
    if len(done)%25==0 or len(done)==len(selected):print('R3_PROGRESS '+str(len(done))+'/'+str(len(selected)),flush=True)
   submit()
 full=len(done)==197;fields=['kb_rebuild']+contract['action_fields']+contract['anomaly_fields']+contract['supplemental_fields']+['kb_concepts']
 counts={name:{'known':sum(v['field_counts'][name]['known'] for v in done.values()),'unknown':sum(v['field_counts'][name]['unknown'] for v in done.values())} for name in fields}
 summary={'schema':'v4.a_share.scoped_kb_r3_manifest.v1','status':'READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',
   'generation':generation,'identity':identity,'source_date':'20261030','original_top200_count':200,'available_count':197,
   'unknown_symbols':source['unknown_symbols'],'processed_count':len(done),'rows':sum(v['rows'] for v in done.values()),
   'calculation_columns':{'selector':340,'backtest':192},'display_columns':{'selector':317,'backtest':186},
   'display_excluded_selector':contract['excluded_fields'],
   'display_excluded_backtest':[x for x in contract['excluded_fields'] if x.startswith('user_v1_')],
   'kb_field_count':107,'concept_fields_display_only':True,'field_counts':counts,
   'per_symbol':[done[s] for s in sorted(done)],'company_coverage':source['company_coverage'],
   'event_policy':source['event_policy'],'old_77_and_baseline_equal':all(v['old_77_and_baseline_equal'] for v in done.values()),
   'paired_fields_equal':all(v['paired_fields_equal'] for v in done.values()),'historical_PIT':False,**FLAGS}
 if full and summary['rows']!=637839:raise ValueError('R3_TOTAL_ROW_COUNT_CONFLICT')
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 return dict(status=summary['status'],generation=generation,manifest=manifest,processed_count=len(done),rows=summary['rows'],
             calculation_columns=summary['calculation_columns'],display_columns=summary['display_columns'],**FLAGS)


def _kb_prior20_event_worker(payload):
 """Recompute only the event ledger, preserving precomputed price panels."""
 import pyarrow as pa
 import pyarrow.parquet as pq
 from ops.kb_anomaly_events import project_anomaly_events
 symbol,stock,identity,root=payload
 root=Path(root)/symbol;receipt=root/'receipt.json'
 if receipt.exists():
  saved=json.loads(receipt.read_text())
  if saved['identity']!=identity or saved['symbol']!=symbol:raise ValueError('PRIOR20_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
  checked(saved['event']);return saved
 src=stock['archive_roles']['selector'];path=checked(src)
 fields=['trade_date','open','high','low','close','volume','pct_chg','ma60','zge_yellow_line','kb_yidong']
 data=pq.read_table(path,columns=fields).to_pandas();dates=[int(x) for x in data['trade_date']]
 if (len(dates)!=stock['rows'] or dates!=sorted(dates) or len(set(dates))!=len(dates)
     or dates[0]!=stock['first_date'] or dates[-1]!=stock['last_date']):raise ValueError('PRIOR20_SOURCE_DATES_CONFLICT:'+symbol)
 _,events=project_anomaly_events(data);indexes={d:i for i,d in enumerate(dates)};coverage=set();anchor_count=0;known=0
 for event in events:
  day=event['asof_date'];i=indexes[day];anchor=event['anchor_date']
  if anchor is None:
   if event['state']!='COVERAGE' or day in coverage:raise ValueError('PRIOR20_COVERAGE_CONFLICT:'+symbol)
   coverage.add(day);known+=event['complete_20'] is True
   if i<20 and (event['complete_20'] is not False or event['today_resumed'] is not None):raise ValueError('PRIOR20_WARMUP_CONFLICT:'+symbol)
  else:
   if not 1<=i-indexes[anchor]<=20:raise ValueError('PRIOR20_ANCHOR_BOUNDARY_CONFLICT:'+symbol)
   peak=event.get('peak_date');pullback=event.get('pullback_date');resume=event.get('resume_date')
   if (peak is not None and not anchor<=peak<=day or pullback is not None and not peak<pullback<=day
       or resume is not None and not pullback<resume<=day):raise ValueError('PRIOR20_EVENT_ORDER_CONFLICT:'+symbol)
   anchor_count+=1
 if len(coverage)!=len(dates):raise ValueError('PRIOR20_COVERAGE_COUNT_CONFLICT:'+symbol)
 table=pa.Table.from_pylist([dict(item,symbol=symbol) for item in events],schema=_kb_event_schema())
 ref=_kb_write_parquet(root/'events.parquet',table)
 result={'schema':'v4.a_share.prior20_event_stock.v1','symbol':symbol,'identity':identity,'source_selector':src,
         'prior_event':stock['assets']['events'],'event':ref,'rows':len(dates),'event_rows':len(events),
         'anchor_rows':anchor_count,'known_coverage_rows':known,'historical_PIT':False,**FLAGS}
 save(receipt,result,immutable=True);return result


def materialize_scoped_kb_r3_prior20(*,parent_manifest_ref,parent_validation_ref,output_root,selected_symbols=None,workers=10):
 """Rebind only event sidecars to the strict previous-20-bar window."""
 from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
 import multiprocessing
 parent=json.loads(checked(parent_manifest_ref).read_text());prior=json.loads(checked(parent_validation_ref).read_text())
 if (parent.get('schema')!='v4.a_share.scoped_kb_r3_manifest.v1' or parent.get('processed_count')!=197
     or parent.get('rows')!=637839 or prior.get('status')!='PASS'
     or prior.get('manifest_sha256')!=parent_manifest_ref['sha256']):raise ValueError('PRIOR20_PARENT_CONFLICT')
 stocks={x['symbol']:x for x in parent['per_symbol']};selected=sorted(stocks) if selected_symbols is None else sorted(set(selected_symbols))
 if len(stocks)!=197 or not selected or not set(selected)<=set(stocks) or selected_symbols is not None and len(selected)!=len(selected_symbols):raise ValueError('PRIOR20_SCOPE_CONFLICT')
 event_identity={'schema':'v4.a_share.prior20_event_revision.v1','parent_manifest':parent_manifest_ref,
                 'parent_validation':parent_validation_ref,'event_authority_sha256':sha(Path(__file__).with_name('kb_anomaly_events.py')),
                 'daily_owner_sha256':sha(Path(__file__)),'window':'ASOF_MINUS_20_THROUGH_ASOF_MINUS_1',
                 'previous_20_coverage':'ASOF_MINUS_20_THROUGH_ASOF_MINUS_1_PLUS_CURRENT_BAR_VALID'}
 generation=digest(event_identity);root=Path(output_root).resolve()/('prior20_event_revision_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 done={};pending={};iterator=iter(selected)
 with ProcessPoolExecutor(max_workers=min(workers,len(selected)),mp_context=multiprocessing.get_context('spawn')) as pool:
  def submit():
   while len(pending)<min(workers*2,len(selected)):
    try:symbol=next(iterator)
    except StopIteration:return
    pending[pool.submit(_kb_prior20_event_worker,(symbol,stocks[symbol],event_identity,str(root/'stocks')))]=symbol
  submit()
  while pending:
   finished,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in finished:
    symbol=pending.pop(future);done[symbol]=future.result()
    save(root/'progress.json',dict(schema='v4.a_share.prior20_progress.v1',generation=generation,completed=len(done),requested=len(selected),last_symbol=symbol,**FLAGS))
    if len(done)%25==0 or len(done)==len(selected):print('PRIOR20_EVENT_PROGRESS '+str(len(done))+'/'+str(len(selected)),flush=True)
   submit()
 full=len(done)==197;summary=dict(parent);summary['identity']=dict(parent['identity'],event_revision=event_identity)
 summary.update(generation=generation,status='READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',
   processed_count=len(done),rows=sum(done[s]['rows'] for s in done),
   event_policy='ALL_PRIOR_20_ANCHORS_EXCLUDING_ASOF; COVERAGE_INCLUDES_ASOF_BAR_VALID; TRISTATE_OR',
   per_symbol=[dict(stocks[s],assets=dict(stocks[s]['assets'],events=done[s]['event']),prior_events=stocks[s]['assets']['events']) for s in sorted(done)])
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 result={'status':summary['status'],'generation':generation,'manifest':manifest,'processed_count':len(done),'rows':summary['rows'],
         'anchor_rows':sum(done[s]['anchor_rows'] for s in done),'known_coverage_rows':sum(done[s]['known_coverage_rows'] for s in done),**FLAGS}
 if full:
  if summary['rows']!=637839:raise ValueError('PRIOR20_TOTAL_ROW_COUNT_CONFLICT')
  valid=dict(prior);valid.update(generation=generation,manifest_sha256=manifest['sha256'],parent_validation=parent_validation_ref,
      prior20_event_validation={'status':'PASS','source_sha256':event_identity['event_authority_sha256'],
          'window':event_identity['window'],'coverage_rows':summary['rows'],'anchor_rows':result['anchor_rows'],
          'known_coverage_rows':result['known_coverage_rows'],'stock_count':197,'price_panels_reused':True})
  result['validation']=save(root/'validation.json',valid,immutable=True)
 return result


def _kb_r4_stock_worker(payload):
 """Revise the explicitly affected fields, preserving all other inputs."""
 import pyarrow as pa
 import pyarrow.parquet as pq
 from ops.kb_action_authority import INPUT_FIELDS,action_rule_sha256,project_action
 from ops.kb_confirmed_gap import DIAGNOSTICS,INPUTS,prefix_hashes,project_selected
 from ops.kb_hold_score import COMPONENTS,apply_n_score,volume_component
 from ops.kb_n_structure import project_n_history
 stock,identity,contract,allowed,root=payload;symbol=stock['symbol'];root=Path(root)/symbol;receipt=root/'receipt.json';started=time.monotonic()
 if receipt.exists():
  previous=json.loads(receipt.read_text())
  if previous.get('identity')!=identity or previous.get('symbol')!=symbol:raise ValueError('R4_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
  for section in ('calculation_roles','display_roles'):
   for ref in previous[section].values():checked(ref)
  checked(previous['diagnostics']);checked(previous['n_checkpoint']);return previous
 originals={}
 for section in ('calculation_roles','display_roles'):
  originals[section]={}
  for role in ('selector','backtest'):
   table=pq.read_table(checked(stock[section][role]));expected=contract['calculation_columns' if section=='calculation_roles' else 'research_projection_columns'][role]
   if len(table)!=stock['rows'] or len(table.column_names)!=expected:raise ValueError('R4_PARENT_SCHEMA_CONFLICT:'+symbol+':'+section+':'+role)
   originals[section][role]=table
 selector=originals['calculation_roles']['selector'];n=len(selector)
 dates=[int(x) for x in selector['trade_date'].to_pylist()]
 if dates!=sorted(set(dates)) or dates[0]!=stock['first_date'] or dates[-1]!=stock['last_date']:
  raise ValueError('R4_PARENT_DATES_CONFLICT:'+symbol)
 for section in originals.values():
  for table in section.values():
   if [int(x) for x in table['trade_date'].to_pylist()]!=dates or any(x!=symbol for x in table['ts_code'].to_pylist()):
    raise ValueError('R4_PARENT_ROLE_KEY_CONFLICT:'+symbol)
 needed={'trade_date','ts_code','open','high','low','close','volume','pre_close','pct_chg',
         'kb_double_gun','kb_violence_k','kb_yidong_vol_ratio_5'}
 frame=selector.select(sorted(needed)).to_pandas().rename(columns={'volume':'vol'})
 computed=project_selected(frame,range(n),allow_existing_input_conflict=True);prefixes=prefix_hashes(frame)
 price_rows=selector.select(['ts_code','trade_date','open','high','low','close','volume']).to_pylist()
 n_identity={'price_basis':'QFQ_ASOF','generation_id':identity['parent_panel_generation'],
             'input_sha256':stock['calculation_roles']['selector']['sha256'],
             'rule_sha256':identity['n_contract_sha256'],'helper_sha256':identity['n_authority_sha256'],
             'calendar_sha256':None,'price_basis_sha256':identity['adjustment_snapshot_sha256']}
 n_rows,n_checkpoint=project_n_history(symbol,price_rows,identity=n_identity)
 checkpoint_ref=save(root/'n_checkpoint.json',n_checkpoint,immutable=True)
 score_names=list(COMPONENTS)+['kb_hold_volume_ok_reason','kb_hold_trend_up_reason',
     'kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status']
 old_scores=selector.select(score_names).to_pylist();base_scores=[dict(row) for row in old_scores]
 for price,row in zip(price_rows,base_scores):row['kb_hold_volume_ok'],row['kb_hold_volume_ok_reason']=volume_component(price)
 scores=apply_n_score(symbol,price_rows,base_scores,n_rows,rule_sha256=identity['n_contract_sha256'],
                      helper_sha256=identity['n_authority_sha256'],allowed_symbols=allowed)
 rows=selector.select(sorted(INPUT_FIELDS|{'kb_action_no_position','kb_action_no_position_status',
     'kb_action_with_position','kb_action_with_position_status','kb_action_reasons','kb_action_rule_sha256'})).to_pylist()
 updates={name:[] for name in contract['modified_fields']};diag_rows=[];statuses={};n_states=Counter()
 for i,(old_row,score,n_row) in enumerate(zip(rows,scores,n_rows)):
  values,diag=computed[i]
  for name in ('kb_rebuild','kb_brick_trend','kb_brick_action_desc','kb_yidong_above_60d',
               'kb_double_gun_vol1','kb_double_gun_vol2','kb_double_gun_gap_days','kb_violence_k_type','kb_violence_k_body'):
   value=values[name]
   if name=='kb_double_gun_gap_days' and value is not None and (isinstance(value,bool) or not isinstance(value,int) or not 3<=value<=10):
    raise ValueError('R4_DOUBLE_GUN_GAP_INVALID:'+symbol+':'+str(dates[i]))
   updates[name].append(value)
  for name in ('kb_hold_volume_ok','kb_hold_volume_ok_reason','kb_hold_trend_up','kb_hold_trend_up_reason',
               'kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status'):
   updates[name].append(score[name])
  if any(score[name]!=old_scores[i][name] for name in ('kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status')):
   action=project_action(dict(old_row,**score),rule_sha256=action_rule_sha256())
   if any(action[name]!=old_row[name] for name in ('kb_action_no_position','kb_action_no_position_status','kb_action_rule_sha256')):
    raise ValueError('R4_UNAFFECTED_ACTION_DRIFT:'+symbol+':'+str(dates[i]))
  else:action=old_row
  for name in ('kb_action_with_position','kb_action_with_position_status','kb_action_reasons'):updates[name].append(action[name])
  if set(diag)!=set(DIAGNOSTICS):raise ValueError('R4_DIAGNOSTICS_CONFLICT:'+symbol)
  for name in ('kb_rebuild_reason','kb_brick_trend_reason','kb_brick_count_reason','kb_brick_action_desc_reason',
               'kb_yidong_above_60d_status','kb_double_gun_components_status','kb_bowl_components_status','kb_violence_k_components_status'):
   statuses.setdefault(name,Counter())[diag.get(name) or 'OBSERVED']+=1
  n_states[n_row['kb_n_structure']['state']]+=1
  diag_rows.append({'ts_code':symbol,'trade_date':dates[i],'diagnostics_json':json.dumps(diag,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False),
                    'prefix_input_sha256':prefixes[i],
                    'n_structure_json':json.dumps(n_row['kb_n_structure'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)})
 schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.int32()),('diagnostics_json',pa.string()),
                   ('prefix_input_sha256',pa.string()),('n_structure_json',pa.string())])
 diag_table=pa.Table.from_pylist(diag_rows,schema=schema)
 diag_meta=dict(identity=identity,symbol=symbol,calendar_status='CANNOT_CONFIRM',price_basis='QFQ_ASOF',historical_PIT=False,**FLAGS)
 diag_table=diag_table.replace_schema_metadata({b'v4.a_share.top200_r4_diagnostics.v1':canonical(diag_meta)})
 def persist(path,table):
  path=Path(path)
  if path.exists():
   found=pq.read_table(path)
   if not table.schema.equals(found.schema,check_metadata=True) or not _kb_old_columns_identical(table,found):
    raise ValueError('R4_PARTIAL_CHECKPOINT_CONFLICT:'+str(path))
   ref=reference(path);ref['bytes']=path.stat().st_size;return ref
  return _kb_write_parquet(path,table)
 diag_ref=persist(root/'diagnostics.parquet',diag_table)
 changed={};out_refs={};analysis_columns=['trade_date','ts_code','open','high','low','close','volume','pre_close','pct_chg','kb_violence_k','kb_yidong_is']
 for section in ('calculation_roles','display_roles'):
  out_refs[section]={}
  for role in ('selector','backtest'):
   old=originals[section][role];result=old
   for name,values in updates.items():
    index=result.schema.get_field_index(name)
    if index<0:raise ValueError('R4_MODIFIED_FIELD_MISSING:'+symbol+':'+name)
    old_field=result.schema.field(index);typ=pa.int32() if name=='kb_double_gun_gap_days' else old_field.type
    arr=pa.array(values,type=typ,from_pandas=True)
    result=result.set_column(index,pa.field(name,typ,nullable=old_field.nullable,metadata=old_field.metadata),arr)
    if section=='calculation_roles' and role=='selector':
     before=old[name].to_pylist();after=arr.to_pylist()
     def equal(a,b):return a==b or isinstance(a,float) and isinstance(b,float) and math.isnan(a) and math.isnan(b)
     changed[name]={'changed':sum(not equal(a,b) for a,b in zip(before,after)),
                    'known':n-arr.null_count,'unknown':arr.null_count}
   metadata=dict(result.schema.metadata or {});metadata[b'v4.a_share.top200_r4_alignment.v1']=canonical(dict(identity=identity,symbol=symbol,section=section,role=role,**FLAGS))
   result=result.replace_schema_metadata(metadata)
   preserved=[name for name in old.column_names if name not in updates]
   if not _kb_old_columns_identical(old.select(preserved),result.select(preserved)):
    raise ValueError('R4_UNAFFECTED_VALUE_CONFLICT:'+symbol+':'+section+':'+role)
   if role=='selector' and not _kb_old_columns_identical(old.select(analysis_columns),result.select(analysis_columns)):
    raise ValueError('R4_ANALYSIS_INPUT_CONFLICT:'+symbol)
   ref=persist(root/(role+'_'+section+'.parquet'),result);out_refs[section][role]=ref
  left=pq.read_table(out_refs[section]['selector']['path'],columns=list(updates))
  right=pq.read_table(out_refs[section]['backtest']['path'],columns=list(updates))
  if not _kb_old_columns_identical(left,right):raise ValueError('R4_ROLE_UPDATE_CONFLICT:'+symbol+':'+section)
 checked(stock['assets']['events'])
 result={'schema':'v4.a_share.scoped_kb_r4_stock.v1','status':'UPDATED','symbol':symbol,'identity':identity,
         'rows':n,'first_date':dates[0],'last_date':dates[-1],'calculation_roles':out_refs['calculation_roles'],
         'display_roles':out_refs['display_roles'],'diagnostics':diag_ref,'n_checkpoint':checkpoint_ref,
         'field_changes':changed,'diagnostic_status_counts':{k:dict(v) for k,v in statuses.items()},
         'n_state_counts':dict(n_states),'unchanged_all_other_columns':True,'analysis_inputs_equal':True,
         'event_sha256':stock['assets']['events']['sha256'],'elapsed_seconds':round(time.monotonic()-started,3),
         'historical_PIT':False,**FLAGS}
 save(receipt,result,immutable=True);return result


def materialize_scoped_kb_manual_r4(*,parent_manifest_ref,parent_validation_ref,output_root,selected_symbols=None,workers=10):
 """Reuse R3 history and materialize only user-requested manual differences."""
 from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
 import multiprocessing
 parent=json.loads(checked(parent_manifest_ref).read_text());validation=json.loads(checked(parent_validation_ref).read_text())
 path=Path(__file__).resolve().parents[1]/'contracts/a_share_top200_panel_r4_v1.json';contract=json.loads(path.read_text())
 if (parent.get('schema')!='v4.a_share.scoped_kb_r3_manifest.v1' or parent.get('processed_count')!=197
     or parent.get('rows')!=637839 or validation.get('status')!='PASS'
     or validation.get('manifest_sha256')!=parent_manifest_ref['sha256']
     or parent_manifest_ref['sha256']!=contract['parent_manifest_sha256']
     or parent_validation_ref['sha256']!=contract['parent_validation_sha256']):raise ValueError('R4_PARENT_CONFLICT')
 stocks={x['symbol']:x for x in parent['per_symbol']};selected=sorted(stocks) if selected_symbols is None else sorted(set(selected_symbols))
 if len(stocks)!=197 or not selected or not set(selected)<=set(stocks) or selected_symbols is not None and len(selected)!=len(selected_symbols):raise ValueError('R4_SCOPE_CONFLICT')
 snapshot=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/a_formula_runs/qfq_d22220537892215832f0/adjustment_input_snapshot.json')
 snap_sha=sha(snapshot);snap=json.loads(snapshot.read_text())
 if snap_sha!='e3a475a74dfd494fbf3177779e634c94509542551a27a6f40802b1c7c6e0202e' or snap.get('price_basis')!='QFQ_ASOF':
  raise ValueError('R4_PRICE_BASIS_IDENTITY_CONFLICT')
 code=Path(__file__).resolve().parent;contracts=code.parent/'contracts'
 identity={'schema':'v4.a_share.top200_r4_identity.v1','parent_manifest':parent_manifest_ref,'parent_validation':parent_validation_ref,
   'parent_panel_generation':parent['generation'],'source_generation':parent['identity']['source_generation'],
   'r4_contract':reference(path),'daily_owner_sha256':sha(Path(__file__)),'score_authority_sha256':sha(code/'kb_hold_score.py'),
   'score_contract_sha256':sha(contracts/'a_share_kb_hold_score_v1.json'),'n_authority_sha256':sha(code/'kb_n_structure.py'),
   'n_contract_sha256':sha(contracts/'a_share_kb_n_structure_v1.json'),'gap_authority_sha256':sha(code/'kb_confirmed_gap.py'),
   'gap_brick_sha256':sha(code/'kb_panel_rebuild_brick.py'),'gap_components_sha256':sha(code/'kb_panel_signal_components.py'),
   'gap_signal_authority_sha256':sha(code/'kb_signal_authority.py'),
   'gap_contract_sha256':sha(contracts/'a_share_kb_confirmed_gap_v1.json'),'adjustment_snapshot_sha256':snap_sha,
   'calendar_sha256':None,'calendar_status':'CANNOT_CONFIRM_FULL_HISTORY','historical_PIT':False}
 generation=digest(identity);root=Path(output_root).resolve()/('manual_r4_revision_'+generation[:20]);root.mkdir(parents=True,exist_ok=True)
 done={};pending={};iterator=iter(selected);allowed=tuple(sorted(stocks))
 with ProcessPoolExecutor(max_workers=min(workers,len(selected)),mp_context=multiprocessing.get_context('spawn')) as pool:
  def submit():
   while len(pending)<min(workers*2,len(selected)):
    try:symbol=next(iterator)
    except StopIteration:return
    pending[pool.submit(_kb_r4_stock_worker,(stocks[symbol],identity,contract,allowed,str(root/'stocks')))]=symbol
  submit()
  while pending:
   finished,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in finished:
    symbol=pending.pop(future);done[symbol]=future.result()
    save(root/'progress.json',dict(schema='v4.a_share.top200_r4_progress.v1',generation=generation,completed=len(done),requested=len(selected),last_symbol=symbol,**FLAGS))
    if len(done)%25==0 or len(done)==len(selected):print('R4_MANUAL_PROGRESS '+str(len(done))+'/'+str(len(selected)),flush=True)
   submit()
 full=len(done)==197;items=[]
 for symbol in sorted(done):
  old=stocks[symbol];result=done[symbol]
  if result['event_sha256']!=old['assets']['events']['sha256']:raise ValueError('R4_EVENT_IDENTITY_CONFLICT:'+symbol)
  item=dict(old,calculation_roles=result['calculation_roles'],display_roles=result['display_roles'],
            diagnostics=result['diagnostics'],n_checkpoint=result['n_checkpoint'],r4_field_changes=result['field_changes'],
            diagnostic_status_counts=result['diagnostic_status_counts'],n_state_counts=result['n_state_counts'])
  item['assets']=dict(old['assets'],selector=result['display_roles']['selector'],backtest=result['display_roles']['backtest'],diagnostics=result['diagnostics'])
  counts=dict(old['field_counts']);counts.update({name:{'known':c['known'],'unknown':c['unknown']} for name,c in result['field_changes'].items()})
  item['field_counts']=counts;items.append(item)
 summary=dict(parent);summary['identity']=dict(parent['identity'],manual_alignment=identity)
 summary.update(generation=generation,status='READY_FOR_INDEPENDENT_REVIEW' if full else 'CANARY_ONLY',
    processed_count=len(items),rows=sum(item['rows'] for item in items),per_symbol=items,
    r4_modified_fields=contract['modified_fields'],r4_added_wide_columns=0,
    analysis_inputs_equal=all(done[s]['analysis_inputs_equal'] for s in done),
    event_sha_unchanged=all(done[s]['event_sha256']==stocks[s]['assets']['events']['sha256'] for s in done))
 aggregate={}
 for name in contract['modified_fields']:
  aggregate[name]={key:sum(done[s]['field_changes'][name][key] for s in done) for key in ('changed','known','unknown')}
 summary['r4_field_changes']=aggregate
 field_counts=dict(parent.get('field_counts',{}));field_counts.update({name:{'known':c['known'],'unknown':c['unknown']} for name,c in aggregate.items()})
 summary['field_counts']=field_counts
 status_counts={}
 for value in done.values():
  for name,counts in value['diagnostic_status_counts'].items():
   target=status_counts.setdefault(name,Counter());target.update(counts)
 summary['r4_diagnostic_status_counts']={name:dict(counts) for name,counts in status_counts.items()}
 manifest=save(root/('manifest.json' if full else 'canary_manifest.json'),summary,immutable=True)
 result={'status':summary['status'],'generation':generation,'manifest':manifest,'processed_count':len(done),
         'rows':summary['rows'],'field_changes':aggregate,'analysis_inputs_equal':summary['analysis_inputs_equal'],
         'event_sha_unchanged':summary['event_sha_unchanged'],
         'slowest_symbol':max(done,key=lambda s:done[s]['elapsed_seconds']),
         'slowest_seconds':max(done[s]['elapsed_seconds'] for s in done),
         'checkpoint_root':str(root),**FLAGS}
 if full:
  if summary['rows']!=637839:raise ValueError('R4_TOTAL_ROW_COUNT_CONFLICT')
  report=dict(validation);report.update(generation=generation,manifest_sha256=manifest['sha256'],parent_validation=parent_validation_ref,
   r4_alignment={'status':'PASS','stock_count':197,'rows':summary['rows'],'modified_fields':contract['modified_fields'],
       'unmodified_columns_bit_equal':all(done[s]['unchanged_all_other_columns'] for s in done),
       'analysis_inputs_equal':summary['analysis_inputs_equal'],'event_sha_unchanged':summary['event_sha_unchanged'],
       'calendar_status':'CANNOT_CONFIRM_FULL_HISTORY','price_basis_snapshot_sha256':snap_sha})
  result['validation']=save(root/'validation.json',report,immutable=True)
 return result
