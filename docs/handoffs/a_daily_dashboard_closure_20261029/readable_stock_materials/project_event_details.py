"""One registered002003 projection of accepted events, returns and fixed buckets."""
from pathlib import Path
import argparse,gzip,hashlib,importlib.util,json,sys,time
HERE=Path(__file__).resolve().parent;TASK=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/readable_stock_materials');B.mkdir(exist_ok=True)
DAILY=B.parent.parent/'today_full_r1/daily_products/a_share'
canonical=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref=lambda p:dict(path=str(Path(p).resolve()),sha256=sha(p))
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
def load(r):
 p=Path(r['path']);raw=p.read_bytes()
 if sha(p)!=r['sha256']:raise ValueError('FROZEN_REFERENCE_DRIFT:'+str(p))
 return json.loads(gzip.decompress(raw) if p.suffix=='.gz' else raw)
def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical(value)+b'\n');return ref(path)
def prepare():
 index=json.loads((DAILY/'index.json').read_text());mf=index['dates']['20261029'];manifest=load(mf);product=load(manifest['artifact']);rowref=product['row_refs']['002003.SZ'];row=load(rowref)
 charts=load(index['original_charts']['20261029']['manifest']);projection=charts['samples']['002003.SZ']['projection'];rule=row['statistics']['groups'][0]['rule_sha256'];cache=DAILY/'history'/rule/'002003.SZ/checkpoint.json';calendar=B.parent/'install_and_single_stock_002003/BOUND_SZ_CALENDAR.json'
 inputs=dict(numeric_manifest=mf,numeric_product=manifest['artifact'],row=rowref,projection=projection,accepted_cache=ref(cache),calendar=ref(calendar),source_config=product['source_config'])
 config=dict(symbol='002003.SZ',asof='2026-10-29',lookback=250,bucket_edges=[0,.2,.4,.6,.8,1],rank='count(valid_close <= event_close)/250 includingevent; eachprefixonly',event_source='accepted_cache.evaluations[group]==TRUE',returns='unchanged _horizon_statistics/_evaluate_event_return; all56 events, flat included in valid denominator; no label/formula/marketrecompute',overall_required={'d2':{'positive':25,'valid':55},'d5':{'positive':17,'valid':54}},maximum_claim='DESCRIPTIVE_NONPIT_NOT_FORECAST')
 contract=dict(status='FROZEN_SYNTHETIC7PASS_REAL_NOT_RUN',GOAL='Same002003 currentbucket subset of accepted eventreturns',BASELINE_ID='current002003 accepted56events; overall25/55 and17/54',ONE_VARIABLE='historical event ownprefix250positiveclose fixed20ppbucket; no overall change',inputs=inputs,code=[ref(TASK/'domains/research_daily_statistics.py'),ref(Path(__file__))],config=config,config_sha256=hashlib.sha256(canonical(config)).hexdigest(),source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],PASS_SIGNAL='all old20cases exact; fullcase aggregates identical; conditionalsubset reconciles; no future price leakage',STOP_RULE='any source/parity failure stops; only002003; no otherstock calculation',WRITER='/root/dashboard_repair_sol',**FLAGS)
 print(json.dumps({'contract':save(B/'STRATA_CONTRACT.json',contract),'config_sha256':contract['config_sha256'],'code':contract['code'],'input_sha256':contract['input_sha256'],'real':'NOT_RUN'},ensure_ascii=False))
def run(authorization):
 cp=B/'STRATA_CONTRACT.json';contract=json.loads(cp.read_text());a=json.loads(authorization.read_text())
 if a.get('status')!='ROOT_RUN_STARTED_REGISTERED' or a.get('contract_sha256')!=sha(cp) or not isinstance(a.get('event_sha256'),str) or len(a['event_sha256'])!=64:raise ValueError('ROOT_REGISTERED_RUN_AUTHORIZATION_REQUIRED')
 for r in contract['code']+list(contract['inputs'].values()):
  if sha(r['path'])!=r['sha256']:raise ValueError('REGISTERED_BINDING_DRIFT')
 spec=importlib.util.spec_from_file_location('frozen_c9_statistics',contract['code'][0]['path']);stats=importlib.util.module_from_spec(spec);spec.loader.exec_module(stats)
 inputs=contract['inputs'];row=load(inputs['row']);cache=load(inputs['accepted_cache']);product=load(inputs['numeric_product']);projection=load(inputs['projection']);cal=load(inputs['calendar'])
 if cache['source_identity']!=product['source_identity'] or cal['source_generation']!=contract['source_generation'] or cal['input_sha256']!=contract['input_sha256']:raise ValueError('ACCEPTED_HISTORY_SOURCE_CONFLICT')
 iso=lambda d:f'{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}'
 calendar=[iso(d) for d in cal['dates']];positions={d:i for i,d in enumerate(calendar)};closes=[dict(date=iso(r['trade_date']),close=float(r['ohlcv']['close']) if r['ohlcv']['close'] is not None else None) for r in projection['formula_result']['rows']];bydate={r['date']:r['close'] for r in closes};asof=contract['config']['asof'];groups={};parity=[];started=time.monotonic()
 for group in row['statistics']['groups']:
  gid=group['group_id'];events=sorted(iso(day) for day,value in cache['evaluations'].items() if value['groups'][gid]=='TRUE');full={}
  for key,sessions in [('d2',2),('d5',5)]:
   allstats=stats._horizon_statistics(events,horizon_sessions=sessions,calendar=calendar,calendar_index=positions,asof_index=positions[asof],close_by_date=bydate,case_limit=max(20,len(events)))
   accepted=group['horizons'][key]
   if {k:v for k,v in allstats.items() if k!='cases'}!={k:v for k,v in accepted.items() if k!='cases'} or allstats['cases'][:len(accepted['cases'])]!=accepted['cases']:raise ValueError('ACCEPTED_OVERALL_OR_SAVED_CASE_PARITY_FAILED:'+gid+':'+key)
   full[key]=allstats
  strata=stats.stratify_event_cases_by_prefix_percentile(close_rows=closes,event_cases={k:v['cases'] for k,v in full.items()},asof=asof)
  groups[gid]={}
  for key,value in full.items():
   value['cases']=strata['horizons'][key]['cases'];value['conditional']=strata['horizons'][key]['conditional'];groups[gid][key]=value;parity.append(dict(group=gid,horizon=key,total=value['total'],valid=value['valid'],positive=value['positive'],conditional=value['conditional']))
 result=dict(schema_version='v4.a_share.event_cases.v1',symbol='002003.SZ',data_date='20261029',numeric_manifest=inputs['numeric_manifest'],source_generation=contract['source_generation'],input_sha256=contract['input_sha256'],statistics_sha256=hashlib.sha256(canonical(row['statistics'])).hexdigest(),projection=inputs['projection'],accepted_cache=inputs['accepted_cache'],calendar=inputs['calendar'],contract=ref(cp),groups=groups,**FLAGS)
 shard=save(B/'event_cases/002003.SZ.json',result);receipt=dict(status='COMPLETED_DESCRIPTIVE_SINGLE_STOCK_PARITY_PASS',symbol='002003.SZ',contract=ref(cp),authorization=ref(authorization),event_sha256=a['event_sha256'],elapsed_seconds=time.monotonic()-started,shard=shard,parity=parity,no_formula_or_label_recalculation=True,**FLAGS);save(B/'STRATA_RESULT.json',receipt);print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--run-started',type=Path);a=p.parse_args()
 if a.prepare:prepare()
 elif a.run_started:run(a.run_started)
 else:p.error('--prepare or --run-started required')
