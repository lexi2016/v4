"""Resume one coherent ten-entry input catalog; reuse only byte-identical previously evaluated inputs."""
import argparse,csv,hashlib,json,math,multiprocessing,os,sys,time,resource
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.dont_write_bytecode=True

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,x):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def csv_write(p,fields,rows):
 with Path(p).open('x',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def fence(event,args):
 if event.startswith(('socket.connect','socket.bind','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_SINGLE_BOUND_INPUT_ONLY')
def kernel_at(path):
 import importlib.util
 spec=importlib.util.spec_from_file_location('frozen_ten_kernel',path);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m

def evaluate_chunk(specs,kernel_path):
 sys.addaudithook(fence);kernel=kernel_at(kernel_path);import numpy as np
 out=[]
 for code,spec in specs:
  source=spec.get('path');base={'code':code,'signal_date':'20261022','history_rows':0,'history_start':None,'history_end':None,'candidate':'UNKNOWN','execution_status':'FAILED','hit_rules':[],'unknown_rules':list(kernel.RULES),'rules':[{'rule_id':k,'source_name':v,'status':'DATA_UNAVAILABLE','value':None,'reason':'INPUT_UNAVAILABLE:'+spec.get('reason',spec['status']),'evidence':{}} for k,v in kernel.RULES.items()],'indicators':{},'risks':{},'input_status':spec['status'],'input_source_sha256':spec.get('sha256'),'input_row_sha256':spec.get('row_sha256'),'row_identity_sha256':None}
  if not source:out.append(base);continue
  try:
   assert sha(source)==spec['sha256'],'INPUT_FILE_DRIFT'
   cols=['ts_code','trade_date','close','high','low','volume']
   if spec['format']=='csv':
    with Path(source).open(encoding='utf-8-sig',newline='') as f:rows=[{k:r[k] for k in cols} for r in csv.DictReader(f)]
   else:
    import pyarrow.parquet as pq
    rows=pq.read_table(source,columns=cols).to_pylist()
   assert len(rows)==spec['rows'] and all(r['ts_code']==code for r in rows),'CODE_OR_ROW_COUNT_DRIFT';dates=[str(r['trade_date']).replace('-','') for r in rows];assert dates==sorted(set(dates)) and dates[0]==spec['first_date'] and dates[-1]==spec['last_date']=='20261022' and all(d<='20261022' for d in dates),'DATE_IDENTITY_DRIFT'
   raw={k:np.asarray([float(r[v]) if r[v] is not None else float('nan') for r in rows]) for k,v in [('C','close'),('H','high'),('L','low'),('VOL','volume')]}
   identity=kernel.canonical_sha({'code':code,'dates':dates,'raw':{k:[float(x) if math.isfinite(x) else None for x in v] for k,v in raw.items()}});row=kernel.evaluate_stock(code,dates,raw,signal_date='20261022');row.update(input_status=spec['status'],input_source_path=source,input_source_sha256=spec['sha256'],input_row_sha256=spec['row_sha256'],row_identity_sha256=identity);assert sha(source)==spec['sha256'],'INPUT_CHANGED_DURING_EVALUATION';out.append(row)
  except Exception as e:
   if isinstance(e,AssertionError):raise
   base.update(error_type=type(e).__name__,error=str(e));out.append(base)
 return out

def evaluate_chunk_reusing(specs,kernel_path,reuse_rows,reuse_source_sha):
 out=[]
 for code,spec in specs:
  prior=reuse_rows.get(code)
  if prior is not None and prior.get('input_source_sha256')==spec.get('sha256') and prior.get('input_row_sha256')==spec.get('row_sha256') and prior.get('input_status')==spec['status']:
   row=dict(prior);row['evaluation_provenance']={'kind':'REUSED_IDENTICAL_SOURCE_INPUT_AND_FROZEN_KERNEL','prior_execution':'ZGE_PARTIAL_CANONICAL_TEN_RECALL_20261023_61','prior_result_file_sha256':reuse_source_sha};out.append(row)
  else:
   row=evaluate_chunk([(code,spec)],kernel_path)[0];row['evaluation_provenance']={'kind':'EVALUATED_NEW_SOURCE_BOUND_INPUT_THIS_EXECUTION'};out.append(row)
 return out

def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=load(cp);out=Path(c['output_directory']);b=c['input_identity'];assert sha(b['independent_canary_receipt'])==b['independent_canary_receipt_sha256'] and load(b['independent_canary_receipt'])['boundary_status']=='PASS_TEN_ROUTE_CANARY_ONLY','FORMULA_CANARY_GATE';assert sha(b['input_manifest'])==b['input_manifest_sha256'];manifest=load(b['input_manifest']);targets=load(b['target_list'])['targets'];status={r['code']:r for r in manifest['all_input_statuses']};assert len(targets)==len(status)==5533 and {r['code'] for r in targets}==set(status),'CANONICAL_KEY_COVERAGE';assert len(manifest['catalog'])==manifest['ready_canonical_codes'];assert c['workers']==2
 sys.addaudithook(fence);sys.path.insert(0,b['registrar_directory']);from mac_registry import register
 kernel=kernel_at(c['kernel_path']);assert sha(b['reuse_results'])==b['reuse_results_sha256'];previous=load(b['reuse_contract']);assert previous['kernel_path']==c['kernel_path'];
 for p,h in previous['frozen_source_bindings'].items():
  if p in c['kernel_dependency_sha256']:assert h==c['kernel_dependency_sha256'][p] and sha(p)==h,'REUSE_KERNEL_DEPENDENCY_DRIFT'
 reuse_rows={}
 with Path(b['reuse_results']).open(encoding='utf-8') as f:
  for line in f:
   r=json.loads(line);assert r['code'] not in reuse_rows;reuse_rows[r['code']]=r
 assert len(reuse_rows)==5533;partdir=out/'parts';partdir.mkdir();start=time.monotonic();allrows=[];parts=[];chunks=[targets[i:i+c['chunk_size']] for i in range(0,len(targets),c['chunk_size'])]
 with ProcessPoolExecutor(max_workers=c['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
  pending=[]
  for i,chunk in enumerate(chunks):
   pending.append((i,pool.submit(evaluate_chunk_reusing,[(t['code'],status[t['code']]) for t in chunk],c['kernel_path'],{t['code']:reuse_rows[t['code']] for t in chunk},b['reuse_results_sha256'])))
   if len(pending)<c['workers'] and i+1<len(chunks):continue
   while pending:
    index,future=pending.pop(0);rows=future.result();assert len(rows)==len(chunks[index]);p=partdir/(str(index).zfill(3)+'.jsonl')
    with p.open('x',encoding='utf-8') as f:
     for r in rows:f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
    allrows.extend(rows);parts.append({'path':str(p),'sha256':sha(p),'rows':len(rows),'codes':[r['code'] for r in rows]});receipt=register(cp,'CHECKPOINT','FULL61_PART_'+str(index).zfill(3),[p],{'processed':len(allrows),'candidate_YES':sum(r['candidate']=='YES' for r in allrows)},'RUNNING_SINGLE_TEN_ENTRY_RECALL');save(out/('REGISTRY_PART_'+str(index).zfill(3)+'.json'),receipt);print(json.dumps({'processed':len(allrows),'candidate_YES':sum(r['candidate']=='YES' for r in allrows)},ensure_ascii=False),flush=True)
 allrows.sort(key=lambda r:r['code']);assert len(allrows)==len({r['code'] for r in allrows})==5533
 with (out/'ALL_CANONICAL_RESULTS.jsonl').open('x',encoding='utf-8') as f:
  for r in allrows:f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
 names={r['code']:r.get('name','') for r in manifest['all_input_statuses']};long=[];union=[];coverage={rid:Counter() for rid in kernel.RULES}
 for r in allrows:
  for rr in r['rules']:
   coverage[rr['rule_id']][rr['status']]+=1;long.append({'code':r['code'],'name':names[r['code']],'signal_asof':'20261022','selection_date':'20261023','rule_id':rr['rule_id'],'rule_name':rr['source_name'],'status':rr['status'],'reason':rr['reason'],'candidate':r['candidate'],'execution_status':r['execution_status'],'history_rows':r['history_rows'],'input_sha256':r['input_source_sha256'],'row_identity_sha256':r['row_identity_sha256']})
  if r['candidate']=='YES':union.append({'code':r['code'],'name':names[r['code']],'signal_asof':'20261022','selection_date':'20261023','hit_rules':'|'.join(r['hit_rules']),'unknown_rules':'|'.join(r['unknown_rules']),'execution_status':r['execution_status'],'history_start':r['history_start'],'history_rows':r['history_rows'],'price_basis':c['price_basis'],'volume_basis':c['volume_basis'],'risks':json.dumps(r['risks'],ensure_ascii=False),'input_sha256':r['input_source_sha256'],'row_identity_sha256':r['row_identity_sha256']})
 fields=['code','name','signal_asof','selection_date','hit_rules','unknown_rules','execution_status','history_start','history_rows','price_basis','volume_basis','risks','input_sha256','row_identity_sha256'];csv_write(out/'UNION_CANDIDATES.csv',fields,union);csv_write(out/'TEN_ROUTE_LONG.csv',list(long[0]),long)
 for rid in kernel.RULES:csv_write(out/(rid+'_CANDIDATES.csv'),fields,[r for r in union if rid in r['hit_rules'].split('|')])
 coverage_rows=[{'rule_id':k,'TRIGGERED':v['TRIGGERED'],'NOT_TRIGGERED':v['NOT_TRIGGERED'],'DATA_UNAVAILABLE':v['DATA_UNAVAILABLE']} for k,v in coverage.items()];assert all(sum(v.values())==5533 for v in coverage.values());csv_write(out/'RULE_COVERAGE.csv',list(coverage_rows[0]),coverage_rows)
 bycode={r['code']:r for r in allrows};lineage=load(b['original318_disposition']);slice318=[]
 for r in lineage:
  s=bycode.get(r['canonical_code']);slice318.append({**r,'candidate':s['candidate'] if s else 'NOT_EVALUATED_DISPOSITION','hit_rules':'|'.join(s['hit_rules']) if s else '', 'unknown_rules':'|'.join(s['unknown_rules']) if s else '', 'execution_status':s['execution_status'] if s else 'SOURCE_DISPOSITION_ONLY','name':names.get(r['canonical_code'],'')})
 assert len(slice318)==len({r['source_key'] for r in slice318})==318;csv_write(out/'ORIGINAL318_SAME_RUN_SLICE.csv',list(slice318[0]),slice318);hits318=[r for r in slice318 if r['candidate']=='YES'];csv_write(out/'ORIGINAL318_HITS.csv',list(slice318[0]),hits318)
 states=Counter(r['execution_status'] for r in allrows);decisions=Counter(r['candidate'] for r in allrows);summary={'status':'SAME_INPUT_TEN_ENTRY_RESULT_READY_FOR_INDEPENDENT_REVIEW','execution_id':c['execution_id'],'verified_start':gate,'signal_asof':'20261022','selection_date':'20261023','original_research_source_keys':5812,'original_owner_target_keys':5800,'canonical_source_eligible_count':5533,'canonical_input_ready':manifest['ready_canonical_codes'],'canonical_input_unavailable':manifest['unavailable_canonical_codes'],'new_D22_research_inputs':manifest['new_D22_research_input_codes'],'requested':5533,'not_scanned':0,'execution_status_counts':dict(states),'candidate_counts':dict(decisions),'unique_selected':len(union),'original318_source_rows':318,'original318_hit_source_keys':len(hits318),'original318_hit_unique_canonical_securities':len({r['canonical_code'] for r in hits318}),'original318_disposition_counts':manifest['original318_dispositions'],'rule_coverage':coverage_rows,'parts':parts,'price_basis':c['price_basis'],'volume_basis':c['volume_basis'],'numerical_identity':'FORMULA_FILE_REPLICA_NOT_LIVE_FUTU_PARITY','source_vintage':'20261023_RETRIEVAL_CUTOFF_20261022_NOT_ARCHIVED_PIT_CERTIFIED','current_V4_API_UI':'NOT_VERIFIED_NOT_CHANGED','live_native_recovery':0,'evaluation_provenance_counts':dict(Counter(r['evaluation_provenance']['kind'] for r in allrows)),'elapsed_seconds':time.monotonic()-start,'parent_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'top_code_examples':union[:10],'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};save(out/'RESULT_RECEIPT.json',summary)
 save(out/'OUTPUT_MANIFEST.json',{'input_manifest_sha256':b['input_manifest_sha256'],'files':{str(p):sha(p) for p in out.iterdir() if p.is_file() and p.suffix in ('.csv','.jsonl')},'parts':parts});(out/'REPORT.md').write_text('十入口 OR 宽召回，信号20261022，展示20261023。\n\n'+f'唯一候选{len(union)}只；请求5533，输入可用{manifest["ready_canonical_codes"]}，候选UNKNOWN{decisions["UNKNOWN"]}。原318同run命中源key{len(hits318)}，去重证券{summary["original318_hit_unique_canonical_securities"]}。\n\n按代码展示，不表示买入顺序；没有TopN/共振/分数门。未知与非股票/退市单列，不造D22行情。\n\nTDX事件仿射前复权及股本口径成交量研究副本；不声明liveFutu逐值等价/完整历史PIT。当前V4页面与正式源未改。\n\n待独立输入/结果验收；未执行第二层、回测、训练或交易。\n',encoding='utf-8');print(json.dumps({k:summary[k] for k in ['status','unique_selected','candidate_counts','original318_hit_source_keys','original318_hit_unique_canonical_securities','rule_coverage','top_code_examples']},ensure_ascii=False),flush=True);return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
