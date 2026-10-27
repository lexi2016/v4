"""Three-stock isolated candidate adapter. Never original fullprefix computation or release."""
from pathlib import Path
import importlib.util,json,gzip,hashlib,shutil,struct,datetime
H=Path(__file__).resolve().parent;R=H.parents[3];O=H.parent/'mother_overlay_v1'
def module(n,p):
 spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def sha(b):return hashlib.sha256(b).hexdigest()
W=module('consumer_reviewed_sources',O/'writer.py');E=module('consumer_state',H/'state_engine.py');J=module('consumer_journal',H/'journal.py')
STOP=O/'batch_runs/20261027T104520Z/STOPPED_PARTIAL_INDEX.json';STOP_SHA='edb6154eb2878a847e45a9551b8f0b0c2815534057104a51fae55cceac282200'
CODE_PINS={'core.py':'77dd24e1ae1b88e714c6e8e754ed594d02d2c0b7c70b865ab3451810133807c0','writer.py':'f95cd88876b06f059da23e3fa3fedfeeab12500cae568649e09bb672cc85827b'}
def authority():
 a=E.root_scope()
 for n,v in CODE_PINS.items():
  if sha((O/n).read_bytes())!=v:raise ValueError('REVIEWED_SOURCE_CODE_HASH')
 return a
def route(symbol):
 a=authority()
 if symbol not in a['routes']:raise ValueError('ROOT_THREE_SYMBOL_SCOPE')
 return a['routes'][symbol]
REUSE_CHECK_SHA='dc1ee9d05834d4bb9444764a60282701465c1e5b0f4549a4ef724a417f56567a'
def reviewed_reuse(symbol):
 route(symbol);base=R/'research_outputs/independent_stopped1556_20261027';raw=(base/'CHECK.json').read_bytes()
 if sha(raw)!=REUSE_CHECK_SHA:raise ValueError('REUSE_REVIEW_HASH')
 check=json.loads(raw);itemsraw=(base/'DISPLAY_CANDIDATE_SYMBOLS.json').read_bytes()
 if check['status']!='PASS_1556_STOPPED_OUTPUT_CANDIDATE_REUSE_ONLY'or check['batch_index_sha256']!=STOP_SHA or check['display_symbols_sha256']!=sha(itemsraw):raise ValueError('REUSE_REVIEW_SCOPE')
 items={x['symbol']:x for x in json.loads(itemsraw)['success']}
 if symbol not in items:raise ValueError('NO_REVIEWED_REUSE_TAIL')
 item=items[symbol]
 if item['source_date']!=20261027:raise ValueError('REUSE_REVIEW_DATE')
 return item
def output(path,obj):J.write_new(path,E.canonical(obj))
def query(symbol,asof,limit=1,fields=('ohlcv','values','drawings'),before_date=None):
 W.C.validate_request(symbol,asof,limit,fields,set(authority()['symbols']))
 return {'symbol':symbol,'asof':asof,'status':'NEW_CONSUMER_DISPLAY_ADMISSION_REQUIRED','research_consumption_allowed':False,'rows':[]}
COMPLETED_RUN='canary3_20261027T115802Z'
COMPLETED_INDEX_SHA='2735004245823d81641b170ba898386ffa63d3869a58094be8be9ac467b0d655'
def load_completed_index(run_id):
 if run_id!=COMPLETED_RUN:raise ValueError('EXACT_COMPLETED_CANARY_RUN')
 path=H/'runs'/run_id/'APPEND_INDEX.json';raw=path.read_bytes()
 if sha(raw)!=COMPLETED_INDEX_SHA:raise ValueError('COMPLETED_CANDIDATE_INDEX_HASH')
 data=json.loads(raw);a=authority()
 if data['root_scope_sha256']!=E.ROOT_SCOPE_SHA or set(data['entries'])!=set(a['symbols'])or data['research_consumption_allowed']is not False:raise ValueError('COMPLETED_SCOPE')
 for n in ('state_engine.py','journal.py'):
  if data['code_hashes'][n]!=sha((H/n).read_bytes()):raise ValueError('COMPLETED_ALGORITHM_VERSION')
 for symbol,item in data['entries'].items():
  if item['symbol']!=symbol or item['route']!=route(symbol)or item['root_scope_sha256']!=E.ROOT_SCOPE_SHA:raise ValueError('COMPLETED_ITEM_SCOPE')
 return data
class Consumer:
 def __init__(self,run_id):
  authority();self.journal=J.Journal(run_id);self.run_id=run_id;self.context=W.Context();self.index={};self.step_calls={};self.full_formula_calls=0
  b=STOP.read_bytes()
  if sha(b)!=STOP_SHA:raise ValueError('STOP_INDEX_HASH')
  self.stopped=json.loads(b);self.tails={x['symbol']:x['tail']for x in self.stopped['entries']}
 def resume_candidates(self):
  data=load_completed_index(self.run_id);self.index=data['entries']
  for symbol in self.index:self.inspect(symbol)
  return {'status':'RESTORED_CANDIDATES_ONLY','symbols':sorted(self.index),'step_calls':0,'original_compute_calls':0}
 def prepare(self,symbol):
  route(symbol);c=self.context;P=W.P
  if symbol not in c.eligible or symbol in c.data['policy']['securities']:raise ValueError('POLICY_OR_EVENT_SCOPE')
  W.read_bound(R/c.config['bindings']['policy']['path'],c.config['bindings']['policy'])
  if P.code_identity()!=c.code:raise ValueError('ORIGINAL_CODE_CHANGED')
  rec=dict(c.records[symbol],_volume_encoding=c.data['manifest']['volume_contract']['volume_encoding'],_volume_decoder_sha256=c.data['manifest']['volume_contract']['decoder_sha256']);P.validate_risk(c.risks[symbol],set(c.allowed))
  if rec['identity']not in('SH_A_CODE_CANDIDATE','SZ_A_CODE_CANDIDATE')or not rec.get('qfq_candidate'):raise ValueError('NORMAL_IDENTITY_PREFIX')
  raw=P.read_rows(c.root,rec['raw']);q=P.read_rows(c.root,rec['qfq_candidate'])
  if len(raw)!=rec['rows']or len(q)!=len(raw)or any(a['trade_date']!=b['trade_date']for a,b in zip(raw,q))or raw[-1]['trade_date']!=20261026:raise ValueError('FULL_PREFIX_COVERAGE')
  raw,q,vc=P.VOLUME.normalize_pair(raw,q,rec['_volume_encoding'],rec['_volume_decoder_sha256']);P.VOLUME.validate_g4(c.daily[symbol]);merged,appended=P.merge_daily(raw,c.daily[symbol],'20261027',c.data['calendar'])
  if not appended:raise ValueError('EXACT_ONE_NEW_DAY')
  olde=P.relevant_events(c.old.get(symbol,[]),raw[0]['trade_date'],20261026);newe=P.relevant_events(c.events.get(symbol,[]),raw[0]['trade_date'],20261027)
  if olde!=newe:raise ValueError('EVENT_CHANGE_REQUIRES_REVIEW')
  P.validate_events(newe,symbol,raw[0]['trade_date'],20261027,set(c.allowed))
  fs=next(x for x in c.data['receipt']['stocks'][symbol]['files']if x['path']==f'stocks/{symbol}/formula.json.gz');old=json.loads(gzip.decompress(W.read_bound(c.root/fs['path'],fs)))
  if old['symbol']!=symbol or len(old['rows'])!=len(q)or old['rows'][-1]['trade_date']!=20261026:raise ValueError('DAILY_PREFIX_IDENTITY')
  normalized=E.F.normalize(q)
  if any(E.encode(x)!=row['ohlcv']for x,row in zip(normalized,old['rows'])):raise ValueError('FORMULA_PREFIX_OHLCV_BINDING')
  return old,fs,merged[-1],vc
 def binding(self,symbol,rows,fs):
  c=self.context;cal=c.data['calendar']
  return {'symbol':symbol,'purpose':'THREE_STOCK_STATE_CONSUMER_CANDIDATE_ONLY','price_coordinate':'FIXED_VINTAGE_QFQ_NONPIT','event_sha256':c.config['bindings']['events']['sha256'],'policy_sha256':c.config['bindings']['policy']['sha256'],'source_formula_sha256':fs['sha256'],'volume_contract_sha256':sha(E.canonical(c.data['manifest']['volume_contract'])),'bootstrap_prefix_sha256':sha(E.canonical(rows)),'date_contract':{'kind':'VERIFIED_CALENDAR_RESEARCH_CANDIDATE','open_dates':[int(x)for x in cal['open_dates']],'coverage_start':cal['coverage_start'],'coverage_end':cal['coverage_end'],'calendar_sha256':c.config['bindings']['calendar']['sha256']}}
 def run_one(self,symbol):
  mode=route(symbol)
  if symbol in self.index:
   self.inspect(symbol);return self.index[symbol]
  if (H/'runs'/COMPLETED_RUN/'APPEND_INDEX.json').exists():raise ValueError('CANARY_ALREADY_COMPLETED_USE_READONLY_RESUME')
  if shutil.disk_usage(H).free<3*1024**3:raise ValueError('SPACE_FLOOR')
  old,fs,bar,vc=self.prepare(symbol);prior_hash=sha(E.canonical(old));c=self.context
  if mode.startswith('reuse'):
   if symbol not in self.tails:raise ValueError('EXPECTED_EXISTING_TAIL')
   spec=self.tails[symbol]
   if spec['path']!=f'tails/{symbol}.json':raise ValueError('TAIL_PATH')
   approved=reviewed_reuse(symbol)
   if approved['tail_sha256']!=spec['sha256']:raise ValueError('REUSE_REVIEW_EXACT_TAIL')
   tail=json.loads(W.read_bound(O/spec['path'],spec))
   if tail['symbol']!=symbol or tail['old_formula']['sha256']!=fs['sha256']or tail['history_values_drawings_ohlcv_sha256']!=sha(E.canonical(old['rows']))or tail['source_bar_exact']!=c.daily[symbol]or tail['config_sha256']!=W.CONFIG_SHA or tail['common_bindings_sha256']!=c.common_sha or tail['original_code']!=c.code:raise ValueError('REUSED_TAIL_BINDINGS')
   if (mode=='reuse_reviewed123')!=(symbol in c.approved):raise ValueError('REUSE_REVIEW_CLASS')
   daily=tail['formula_lastbar'];newrows=old['rows']+[daily];W.C.validate_append(symbol,old,dict(old,rows=newrows));W.C.validate_source(c.daily[symbol],daily)
   b=self.binding(symbol,newrows,fs);state=E.bootstrap(symbol,newrows,20261027,b);state['last_transition']={'previous_state_sha256':None,'reused_daily_sha256':sha(E.canonical(daily)),'new_indicator_rows':0,'old_history_rows_recomputed':0,'original_compute_calls':0,'bootstrap_after_existing_day':True};state=E.seal(state);calls=0
  else:
   if symbol in self.tails or (O/'tails'/f'{symbol}.json').exists():raise ValueError('MISSING_ROUTE_HAS_EXISTING_TAIL')
   b=self.binding(symbol,old['rows'],fs);prior=E.bootstrap(symbol,old['rows'],20261026,b);daily,state=E.step(prior,bar,b);calls=1;W.C.validate_append(symbol,old,dict(old,rows=old['rows']+[daily]));W.C.validate_source(c.daily[symbol],daily)
  if sha(E.canonical(old))!=prior_hash:raise ValueError('OLD_HISTORY_CHANGED')
  self.journal.commit(symbol,daily,state);cp=self.journal.paths(symbol,20261027)[2]
  item={'symbol':symbol,'route':mode,'baseline_date':20261026,'indicator_date':20261027,'source_date':20261027,'old_formula':dict(fs,path=str((c.root/fs['path']).relative_to(R))),'old_rows':len(old['rows']),'old_history_sha256':sha(E.canonical(old['rows'])),'checkpoint_sha256':sha(cp.read_bytes()),'daily_sha256':sha(E.canonical(daily)),'state_sha256':state['state_sha256'],'root_scope_sha256':E.ROOT_SCOPE_SHA,'source_bar_exact':c.daily[symbol],'source_bindings':c.config['bindings'],'common_bindings_sha256':c.common_sha,'volume_check':vc,'amount_contract':'exact official source amount separate from formula float32','formula_amount_float32':struct.unpack('<f',struct.pack('<f',c.daily[symbol]['amount']))[0],'D27_step_calls':calls,'original_compute_calls':0,'qualification':W.P.QUALIFICATION,'risk':c.risks[symbol],'prior_tail':self.tails.get(symbol),'prior_display_reviewed':mode=='reuse_reviewed123','research_consumption_allowed':False,'production_allowed':False,'PIT':False,'training_eligible':False}
  output(self.journal.root/symbol/'APPEND_RECORD.json',item);self.index[symbol]=item;self.step_calls[symbol]=calls;return item
 def inspect(self,symbol,asof=20261027,limit=1,fields=('ohlcv','values','drawings'),before_date=None):
  W.C.validate_request(symbol,asof,limit,fields,set(authority()['symbols']))
  if symbol not in self.index:raise ValueError('NOT_COMMITTED_IN_CURRENT_CANDIDATE')
  item=self.index[symbol]
  if item['route'].startswith('reuse'):
   approved=reviewed_reuse(symbol)
   if approved['tail_sha256']!=item['prior_tail']['sha256']or approved['old_formula_sha256']!=item['old_formula']['sha256']:raise ValueError('READ_REUSE_REVIEW_BINDING')
  cp=self.journal.paths(symbol,20261027)[2]
  if sha(cp.read_bytes())!=item['checkpoint_sha256']:raise ValueError('CHECKPOINT_CHANGED')
  W.read_bound(R/self.context.config['bindings']['policy']['path'],self.context.config['bindings']['policy']);old=json.loads(gzip.decompress(W.read_bound(R/item['old_formula']['path'],item['old_formula'])));pair=self.journal.read(symbol,20261027)
  if sha(E.canonical(pair['daily']))!=item['daily_sha256']or sha(E.canonical(old['rows']))!=item['old_history_sha256']:raise ValueError('COMPOSITE_BINDING')
  if item['source_bar_exact']!=self.context.daily[symbol]:raise ValueError('READ_SOURCE_CHANGED')
  W.C.validate_append(symbol,old,dict(old,rows=old['rows']+[pair['daily']]));W.C.validate_source(item['source_bar_exact'],pair['daily'])
  rows=old['rows']+[pair['daily']];page,cursor=W.C.page_rows(rows,limit,before_date)
  return {'symbol':symbol,'indicator_date':20261027,'source_date':20261027,'baseline_date':20261026,'rows':[{'trade_date':r['trade_date'],**{k:r[k]for k in fields}}for r in page],'next_before_date':cursor,'total_rows':len(rows),'source_bar_exact':item['source_bar_exact'],'status':'THREE_STOCK_CANDIDATE_INSPECTION_ONLY','research_consumption_allowed':False}
