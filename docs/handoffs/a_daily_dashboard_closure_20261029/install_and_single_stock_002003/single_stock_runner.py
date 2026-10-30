"""One registered002003 existing-owner run; metadata prepare is not execution."""
from pathlib import Path
import argparse,copy,hashlib,importlib.abc,importlib.util,json,re,runpy,sys,time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
PARENT=B.parent.parent;PRODUCT_PARENT=PARENT/'today_full_r1';DATA=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据');SYMBOL='002003.SZ';TARGET=20261029
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(Path(p).resolve()),'sha256':sha(p)}
def save(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n');return ref(p)
def load_owner():
 boot=runpy.run_path(str(ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/run_real_canary.py'),run_name='candidate_source_imports')
 class OnlyComposed(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   if fullname in {'ops.research_panel_daily_product','domains.research_daily_product','domains.research_daily_statistics'}:
    p=HERE/'composed_source'/Path(*fullname.split('.')).with_suffix('.py');return importlib.util.spec_from_file_location(fullname,p)
 sys.meta_path.insert(0,OnlyComposed())
 for name in ('ops.research_panel_daily_product','domains.research_daily_product','domains.research_daily_statistics'):sys.modules.pop(name,None)
 owner=importlib.import_module('ops.research_panel_daily_product')
 config_path=ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json';cfg=json.loads(config_path.read_text())
 context=owner.SourceContext(DATA,TARGET,source_config=(cfg,ref(config_path)))
 return owner,context

def prepare():
 owner,ctx=load_owner();ctx.root=PRODUCT_PARENT/'daily_products/a_share';bars,name=ctx.read(SYMBOL);q=ctx.qualify(SYMBOL)
 if q['status']!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':raise ValueError('SINGLE_INPUT_QUALIFICATION_UNKNOWN:'+str(q))
 assert bars[-1]['trade_date']==TARGET and str(bars[0]['trade_date'])==q['history_start_date'];ctx.unchanged()
 prior=json.loads((PARENT/'TODAY_FULL_INPUTS.json').read_text());assert ctx.generation==prior['generation'] and ctx.identity['input_sha256']==prior['input_sha256']
 assert all(getattr(ctx.panel.stat(),k)==v for k,v in prior['selector']['stat'].items())
 index=json.loads((ctx.root/'index.json').read_text());manifest=index['dates'][str(TARGET)];m=json.loads(owner.checked(manifest).read_text());product=json.loads(owner.checked(m['artifact']).read_text());assert SYMBOL in product['row_refs']
 rule=ref(HERE/'composed_source/domains/research_daily_product.py');history=ctx.root/'history'/rule['sha256']/SYMBOL/'checkpoint.json';cache=json.loads(history.read_text()) if history.exists() else {'evaluations':{}}
 if cache.get('prefix_sha256') and cache['prefix_sha256']!=owner.digest(bars):raise ValueError('EXISTING_HISTORY_PREFIX_DRIFT')
 evaluated=sorted(map(int,cache['evaluations']));dates=[b['trade_date'] for b in bars];missing=[d for d in dates if d<TARGET and d not in evaluated]
 calendar=save(B/'BOUND_SZ_CALENDAR.json',{'market':'SZ','dates':ctx.calendars['SZ'],'source_generation':ctx.generation,'input_sha256':ctx.identity['input_sha256'],'future_calendar':ctx.config.get('future_calendar')})
 chart_manifest=B.parent/'original_formula_charts_247/MANIFEST.json';chart=json.loads(chart_manifest.read_text())['samples'][SYMBOL]
 pins={k:ctx.config[k] for k in ('engine','formula','tri_state_core','census','admission_helper','future_calendar')}
 for pin in pins.values():owner.checked(pin)
 binding={'schema':'v4.single_history_run_binding.v1','status':'PREPARED_WAIT_ROOT_RUN_STARTED','symbol':SYMBOL,'target':TARGET,'data_root':str(DATA),'product_parent':str(PRODUCT_PARENT),'source_generation':ctx.generation,'input_sha256':ctx.identity['input_sha256'],'source_identity':ctx.identity,'source_config':ctx.config_ref,'pins':pins,'code':[ref(HERE/'composed_source/ops/research_panel_daily_product.py'),rule,ref(HERE/'composed_source/domains/research_daily_statistics.py'),ref(Path(__file__))],'selector':prior['selector'],'pointers':prior['pointers'],'receipt':ctx.receipt_ref,'snapshot':ctx.snapshot_ref,'quarantine':ctx.quarantine_ref,'reader':ctx.reader_ref,'bars':{'rows':len(bars),'first':dates[0],'last':dates[-1],'sha256':owner.digest(bars)},'qualification':q,'market_calendar':calendar,'historical_g4_refs':ctx.config.get('dated_g4_packages',{}),'prior_manifest':manifest,'prior_product':m['artifact'],'prior_row':product['row_refs'][SYMBOL],'prior_history_cache':ref(history) if history.exists() else None,'already_evaluated_dates':evaluated,'missing_history_dates':missing,'parity_cutoffs':[dates[0],dates[min(113,len(dates)-2)],dates[-6]],'chart_manifest':ref(chart_manifest),'chart_completion':ref(chart_manifest.parent/'COMPLETION_RECEIPT_247.json'),'existing_chart':chart,'output_root':str(B/'single_run'),'registration_required':True,'historical_PIT':False,'maximum_claim':'DIRECTION_ONLY',**owner.FLAGS}
 save(B/'CANARY_BINDING.json',binding);print(json.dumps({'status':binding['status'],'binding':ref(B/'CANARY_BINDING.json'),'rows':len(bars),'missing':len(missing),'parity_cutoffs':binding['parity_cutoffs']}),flush=True)

def run(authorization):
 binding_path=B/'CANARY_BINDING.json';binding=json.loads(binding_path.read_text());permit=json.loads(Path(authorization).read_text())
 if permit.get('status')!='ROOT_RUN_STARTED_REGISTERED' or permit.get('binding')!=ref(binding_path) or not re.fullmatch('[a-f0-9]{64}',permit.get('event_sha256','')):raise ValueError('REAL_EXECUTION_REQUIRES_ROOT_RUN_STARTED_BINDING')
 owner,ctx=load_owner()
 for pin in [*binding['code'],*binding['pins'].values(),*binding['pointers'],binding['receipt'],binding['snapshot'],binding['quarantine'],binding['reader'],binding['source_config'],binding['market_calendar']]:owner.checked(pin)
 assert ctx.generation==binding['source_generation'] and ctx.identity==binding['source_identity'];ctx.unchanged();bars,_=ctx.read(SYMBOL);assert owner.digest(bars)==binding['bars']['sha256'];q=ctx.qualify(SYMBOL);assert q==binding['qualification']
 output=Path(binding['output_root']);output.mkdir(parents=True,exist_ok=True);ctx.root=output/'daily_products/a_share';rule=binding['code'][1]['sha256'];cachefile=ctx.root/'history'/rule/SYMBOL/'checkpoint.json'
 if not cachefile.exists() and binding['prior_history_cache']:
  source=owner.checked(binding['prior_history_cache']);owner.save(cachefile,json.loads(source.read_text()))
 from domains.research_daily_product import evaluate_daily_product
 cache=json.loads(cachefile.read_text()) if cachefile.exists() else {'rule_sha256':rule,'evaluations':{}}
 dates=[b['trade_date'] for b in bars];missing=[d for d in dates if d<TARGET and str(d) not in cache['evaluations']];started=time.perf_counter();last_save=started;count=0;parity_done=False;parity_evaluations={};original_inputs=owner.source_inputs;engine=ctx.engine();original_compute=engine.compute;calls=[]
 def counted(*a,**kw):calls.append(len(a[0]));return original_compute(*a,**kw)
 engine.compute=counted
 def checked_inputs(c,s,prefix,day,qual,**kwargs):
  nonlocal parity_done
  witness=kwargs.get('prefix_reuse')
  if witness is not None and not parity_done:
   cases=[]
   for cutoff in binding['parity_cutoffs']:
    sliced=[bar for bar in bars if bar['trade_date']<=cutoff]
    legacy=original_inputs(c,s,sliced,cutoff,qual);fast=original_inputs(c,s,sliced,cutoff,qual,prefix_reuse=witness)
    if owner.canonical(legacy)!=owner.canonical(fast):raise ValueError('REAL_SINGLE_SOURCE_INPUT_PARITY_FAILED:'+str(cutoff))
    args=dict(symbol=s,asof=cutoff,fullprefix=sliced,exchange_calendar=ctx.calendars['SZ'])
    left=evaluate_daily_product(**args,**legacy);right=evaluate_daily_product(**args,**fast)
    if owner.canonical(left)!=owner.canonical(right):raise ValueError('REAL_SINGLE_PREDICATE_PARITY_FAILED:'+str(cutoff))
    parity_evaluations[cutoff]=right;cases.append({'cutoff':cutoff,'prefix_rows':len(sliced),'source_inputs_sha256':owner.digest(fast),'evaluation_sha256':owner.digest(right),'groups':{g:right['groups'][g]['status'] for g in owner.GROUPS}})
   parity_done=True;owner.save(output/'PARITY_RESULT.json',{'status':'PASS_ONE_REGISTERED_SYMBOL_LEGACY_FAST','symbol':SYMBOL,'cases':cases,'binding':ref(binding_path),'historical_PIT':False,**owner.FLAGS});print(json.dumps({'event':'PARITY_PASS','cases':len(cases)}),flush=True)
  return original_inputs(c,s,prefix,day,qual,**kwargs)
 def evaluated(**kwargs):
  nonlocal count,last_save
  day=int(kwargs['asof']);result=parity_evaluations.get(day) or evaluate_daily_product(**kwargs)
  item=dict(groups={g:result['groups'][g]['status'] for g in owner.GROUPS},source_identity=ctx.identity,qualification=q,exact_full_conditions=True)
  if day<TARGET:item.update(historical_PIT=False,historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION')
  cache['evaluations'][str(day)]=item;count+=1;now=time.perf_counter()
  if count%25==0 or now-last_save>=5:
   ctx.unchanged();cache.update(rules_signature=owner.digest(ctx.config),prefix_sha256=owner.digest(bars),source_identity=ctx.identity);owner.save(cachefile,cache)
   progress={'status':'RUNNING','symbol':SYMBOL,'completed_evaluations':len(cache['evaluations']),'available_rows':len(bars),'last_cutoff':day,'elapsed_seconds':now-started,'engine_compute_calls':len(calls),'parity_done':parity_done};owner.save(output/'PROGRESS.json',progress);print(json.dumps(progress),flush=True);last_save=now
  return result
 try:
  owner.source_inputs=checked_inputs;row,final_cache,path=owner.compute_stock(ctx,SYMBOL,evaluate=evaluated,history_dates=missing,reuse_history_prefix=True)
  if missing and not parity_done:raise ValueError('PARITY_GATE_NOT_VISITED')
  ctx.unchanged();row.update(owner.FLAGS);owner.save(path,final_cache);owner.save(output/(SYMBOL+'.json'),row)
  result={'status':'COMPLETED_WAIT_REAL_LINEAGE_ACCEPTANCE','symbol':SYMBOL,'binding':ref(binding_path),'row':ref(output/(SYMBOL+'.json')),'history_cache':ref(path),'parity':ref(output/'PARITY_RESULT.json') if parity_done else None,'rows':len(bars),'evaluated_dates':len(final_cache['evaluations']),'missing':final_cache['coverage']['missing'],'coverage':final_cache['coverage'],'group_statistics':row['statistics']['groups'],'engine_compute_prefix_rows':calls,'elapsed_seconds':time.perf_counter()-started,'historical_PIT':False,'maximum_claim':'DIRECTION_ONLY',**owner.FLAGS};owner.save(output/'RESULT.json',result);print(json.dumps({'status':result['status'],'elapsed_seconds':result['elapsed_seconds'],'rows':result['rows']}),flush=True)
 except Exception as error:
  owner.save(output/'ERROR.json',{'status':'CANNOT_CONFIRM','error':repr(error),'elapsed_seconds':time.perf_counter()-started,'completed_evaluations':len(cache['evaluations']),**owner.FLAGS});raise
 finally:owner.source_inputs=original_inputs;engine.compute=original_compute

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--run-started',type=Path);args=parser.parse_args()
 if args.prepare:prepare()
 elif args.run_started:run(args.run_started)
 else:parser.error('metadata --prepare or Root registered --run-started file required')
