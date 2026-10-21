"""Two-stock original canonical projection. No native mutation/publication.

The legacy owner, formula and exact-key merge are imported unchanged. Source
differences are measured before choosing repair cells; D21 raw is invariant.
"""
import sys
sys.dont_write_bytecode=True
import argparse,gc,hashlib,importlib.util,json,math,os,resource,time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022/formal001210_repair')
E='A_SHARE_FORMAL001210_PANEL_REPAIR_20261022_01'
RAW=('open','high','low','close','amount','volume')

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}
def save(p,x):
 with Path(p).open('x')as f:
  json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
def clean(v):
 if v is None:return None
 if isinstance(v,(np.integer,)):return int(v)
 if isinstance(v,(float,np.floating)):return float(v) if math.isfinite(float(v))else str(v)
 return v
def equal(a,b):
 return a==b or (isinstance(a,float) and isinstance(b,float) and math.isnan(a) and math.isnan(b))
def frozen(cfg):
 for x in cfg['input_bindings']:assert sha(x['path'])==x['sha256'],'FROZEN_INPUT_DRIFT:'+x['path']
 for p in cfg['panels'].values():
  assert stat(p['path'])==p['stat'],'PANEL_STAT_DRIFT'
  assert sha(p['pointer_path'])==p['pointer_sha256'],'POINTER_DRIFT'
  assert Path(p['pointer_path']).read_text(encoding='utf-8-sig').strip()==p['path']
 assert not (Path(cfg['tdx_root'])/'T0002/hq_cache/gbbq').exists(),'XDXR_PRESENCE_DRIFT'

class Log:
 def __init__(self,p):self.f=Path(p).open('x')
 def log(self,x):self.f.write(str(x)+'\n');self.f.flush()

def stock(cfg,target,root,base):
 code=target['ts_code'];assert code=='001210.SZ'
 stage=root/code;stage.mkdir();started=time.monotonic();log=Log(stage/'owner.log')
 owner=base.owner_module(cfg,stage)
 bits=load(cfg['carry_oracle_path'],'accepted_valid_value_oracle')
 assert sha(target['native_path'])==sha(target['accepted_snapshot_path'])==target['native_sha256']
 # Consume every existing accepted native record, through D21, as recursive
 # context. No archive-vintage substitution, unit conversion or source writes.
 native=base.native(Path(target['native_path']).read_bytes())
 context={d:b for d,b in native.items()if d<=cfg['signal_date']}
 ctx=stage/'full_original_context.day';ctx.open('xb').write(b''.join(context[d]for d in sorted(context)))
 hist=owner.read_day_tail(code,ctx,tail_records=len(context)).sort_values('trade_date').reset_index(drop=True)
 assert len(hist)==len(context)and hist['ts_code'].eq(code).all()
 byhist={int(x['trade_date']):x for x in hist.to_dict('records')}
 old={};raw_plan={};failures=[]
 approved={(int(d),c)for d,cols in target['allowed_raw_cells'].items()for c in cols}
 for role,p in cfg['panels'].items():
  table=ds.dataset(p['path'],format='parquet').to_table(filter=ds.field('ts_code')==code)
  before={int(r['trade_date']):r for r in table.to_pylist()}
  assert table.num_rows==len(before)>0
  pq.write_table(table,stage/(role+'_original_stock.parquet'));old[role]=table
  dates=sorted(d for d in before if target['repair_first_date']<=d<=cfg['signal_date'])
  assert dates and not set(dates)-set(byhist),'Missing existing key in original source'
  changes=[];d21=[];vf=p['volume_field']
  for col in RAW:
   ac=vf if col=='volume'else col;field=table.schema.field(ac)
   projected=owner.coerce_series_to_arrow(pd.Series([byhist[d][ac]for d in dates]),field).to_pylist()
   for d,v in zip(dates,projected):
    prior=before[d][ac]
    if d==cfg['signal_date']:
     d21.append({'column':ac,'equal':equal(prior,v),'old':clean(prior),'accepted_native_owner_dtype':clean(v)})
     if not equal(prior,v):failures.append('D21_RAW_DISAGREEMENT:'+role+':'+col)
    if equal(prior,v):continue
    changes.append({'trade_date':d,'column':ac,'logical_raw_field':col,'old':clean(prior),'accepted_native_owner_dtype':clean(v)})
    if (d,col)not in approved:failures.append('UNAPPROVED_RAW_CELL:'+role+':'+str(d)+':'+col)
  actual={(x['trade_date'],x['logical_raw_field'])for x in changes}
  if actual!=approved:failures.append('EXACT20_RAW_PLAN_MISMATCH:'+role)
  raw_plan[role]={'repair_dates':dates,'raw_changes':changes,'D21_raw_checks':d21,'old_stock_rows':table.num_rows,'raw_types':{c:str(table.schema.field(vf if c=='volume'else c).type)for c in RAW}}
 save(stage/'RAW_SOURCE_AND_DTYPE_PLAN.json',{'ts_code':code,'roles':raw_plan,'failures':failures,'authority':'Frozen accepted native projected by original owner and each role dtype','full_context_rows':len(hist),'context_sha256':sha(ctx),'native_writes':0})
 assert not failures,'SOURCE_PLAN_STOP: persisted actual observations'
 latest=max(int(d)for d in old['legacy_selector']['trade_date'].to_pylist())
 static=owner.read_latest_static_map(stage/'legacy_selector_original_stock.parquet',latest,owner.STATIC_MAP_CANDIDATES,log,active_ts_codes=[code])
 capture={};original=owner._compute_canonical_v192_formula
 def retain(frame):
  ans=original(frame);capture['full']=ans.copy();return ans
 owner._compute_canonical_v192_formula=retain
 try:generated=owner.compute_formula_features(hist,target['repair_first_date']-1,static,log,emit_all_rows=True,xdxr_events=owner.empty_xdxr_events())
 finally:owner._compute_canonical_v192_formula=original
 for col in capture['full']:
  if col not in generated:generated[col]=capture['full'][col].to_numpy()
 assert owner.audit_pre_close_chain(generated)['status']=='PASS'
 roles={}
 for role,table in old.items():
  schema=table.schema;vf=cfg['panels'][role]['volume_field'];dates=raw_plan[role]['repair_dates']
  frame=generated[generated['trade_date'].isin(dates)].copy().reset_index(drop=True)
  assert set(map(int,frame['trade_date']))==set(dates)
  gate=owner.validate_new_selector_rows(frame,old['legacy_selector'].schema,cfg['signal_date']);assert gate['status']=='PASS'
  if role=='legacy_selector':frame=owner.append_contract_provenance(frame,Path(cfg['panels'][role]['path']),owner.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'])
  else:frame=owner.append_backtest_provenance_and_tradeability(frame,Path(cfg['panels'][role]['path']))
  missing=[f.name for f in schema if f.name not in frame]
  projected,align=owner.build_table_for_schema(frame,schema,'selector'if role=='legacy_selector'else'backtest',policy=None)
  existing={int(x['trade_date']):x for x in table.to_pylist()};carry=set(missing)|(set(owner.STATIC_MAP_CANDIDATES)&set(schema.names))
  for field in schema:
   col=field.name
   # Same-key undefined and noncomputed/static fields are retained. No new
   # keys are introduced, no missing definitions are guessed or zero-filled.
   if col in carry or col in cfg['unavailable_derived_columns']:
    ix={int(d):i for i,d in enumerate(table['trade_date'].to_pylist())}
    original_take=table.take(pa.array([ix[int(d)]for d in frame['trade_date']],type=pa.int64()))
    projected=projected.set_column(schema.get_field_index(col),field,original_take[col])
  for col in RAW:
   actualcol=vf if col=='volume'else col
   assert projected[actualcol].combine_chunks().equals(owner.coerce_series_to_arrow(frame[actualcol],schema.field(actualcol))), 'RAW_PROJECTION_DRIFT'
  d21=projected.filter(pc.equal(projected['trade_date'],str(cfg['signal_date'])if pa.types.is_string(schema.field('trade_date').type)else cfg['signal_date']))
  old21=table.filter(pc.equal(table['trade_date'],str(cfg['signal_date'])if pa.types.is_string(schema.field('trade_date').type)else cfg['signal_date']))
  base.same_values(d21.select(['open','high','low','close','amount',vf]),old21.select(['open','high','low','close','amount',vf]))
  out=stage/(role+'_repair.parquet');pq.write_table(projected,out)
  persisted=pq.read_table(out)
  preserved=sorted((carry|set(cfg['unavailable_derived_columns']))&set(schema.names))
  observations={c:{'original':bits.array_observation(original_take[c]),'persisted':bits.array_observation(persisted[c])}for c in preserved}
  save(stage/(role+'_CARRY_BIT_OBSERVATIONS.json'),observations)
  assert persisted.schema==projected.schema and bits.keys(persisted)==bits.keys(projected)
  for c in preserved:assert bits.array_digest(original_take[c])==bits.array_digest(persisted[c]),'VALID_VALUE_OR_MASK_DRIFT:'+c
  base.same_values(projected,persisted)
  roles[role]={'repair_table_path':str(out),'repair_table_sha256':sha(out),'repair_rows':projected.num_rows,
    'retire_keys':[],'inserted_keys':0,'replaced_keys':projected.num_rows,'raw_change_cells':len(raw_plan[role]['raw_changes']),
    'same_key_preserved_columns':sorted(carry|set(cfg['unavailable_derived_columns'])),'formula_gate':gate,'D21_raw_exact_preserved':True,
    'full_schema_ready':False,'missing_definitions':missing,'alignment_observed':align}
 result={'execution_id':E,'ts_code':code,'status':'ORIGINAL_OWNER_TWO_ROLE_REPAIR_TABLES_READY',
  'context_first_date':int(hist['trade_date'].min()),'context_last_date':int(hist['trade_date'].max()),'context_rows':len(hist),
  'full_history_recursive_context':True,'formula_calls':1,'roles':roles,'raw_plan_path':str(stage/'RAW_SOURCE_AND_DTYPE_PLAN.json'),
  'raw_plan_sha256':sha(stage/'RAW_SOURCE_AND_DTYPE_PLAN.json'),'elapsed_seconds':time.monotonic()-started,
  'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'native_writes':0,'authority_writes':0,'pointer_writes':0,'network_calls':0}
 assert result['peak_rss_bytes']<cfg['max_rss_bytes'];save(stage/'CHECKPOINT.json',result);log.f.close();return result

def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=('canary','merge'));args=p.parse_args()
 cfg=json.loads((N/'CONTRACT.json').read_text());start=json.loads(Path(cfg['start_receipt']).read_text())
 assert start['execution_id']==E and start['event_type']=='RUN_STARTED'
 frozen(cfg);root=N/'runs'/E;t=time.monotonic();base=load(cfg['reused_helper_path'],'original_owner_recipe_001210')
 if args.phase=='canary':
  root.mkdir(parents=True,exist_ok=False);result=stock(cfg,cfg['targets'][0],root,base)
 else:
  phase=json.loads((root/'canary_RECEIPT.json').read_text());assert phase['safe_to_continue']and phase['peak_rss_bytes']<cfg['max_rss_bytes']
  prior=load(cfg['reviewed_merge_helper_path'],'unchanged_reviewed_merge_001210');result=prior.merge(cfg,root,base)
 frozen(cfg);peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;assert peak<cfg['max_rss_bytes']
 result.update(execution_id=E,phase=args.phase,elapsed_seconds=time.monotonic()-t,peak_rss_bytes=peak,safe_to_continue=True)
 save(root/(args.phase+'_RECEIPT.json'),result)
 print(json.dumps({k:v for k,v in result.items()if k!='roles'},ensure_ascii=False))
if __name__=='__main__':main()
