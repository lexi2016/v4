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
N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022')
E='A_SHARE_WINDOWS37_D21_PANEL_REPAIR_20261022_R3_01'
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
 code=target['ts_code'];stage=root/code;stage.mkdir();started=time.monotonic();log=Log(stage/'owner.log')
 owner=base.owner_module(cfg,stage)
 reuse=cfg.get('reuse_canary_preflight') if code=='920146.BJ' else None
 if reuse:
  # Reuse the actual failed01 preflight, not its failed policy verdict. The
  # source files/stock tables/context are exact frozen inputs; no rawplan rerun.
  prior=json.loads(Path(reuse['raw_plan_path']).read_text())
  assert all(s.startswith('UNRESOLVED_CROSS_SOURCE_RAW:')and s.endswith(':volume')for s in prior['failures'])
  hist=owner.read_day_tail(code,Path(reuse['context_path']),tail_records=prior['full_context_rows'])
  hist=hist.sort_values('trade_date').reset_index(drop=True)
  old={role:pq.read_table(p)for role,p in reuse['stock_tables'].items()}
  raw_plan=prior['roles']
  for role,plan in raw_plan.items():
   assert all(x['equal']for x in plan['D21_raw_checks'])
   for cell in plan['raw_changes']:
    d=str(cell['trade_date']);col=cell['column']
    assert d in target['known_OHLC_fields']
    if col in ('open','high','low','close'):assert col in target['known_OHLC_fields'][d]
  save(stage/'RAW_SOURCE_AND_DTYPE_PLAN.json',{'ts_code':code,'roles':raw_plan,'failures':[],
   'prior_failed_policy_failures_preserved':prior['failures'],'prior_raw_plan':reuse['raw_plan_path'],
   'prior_raw_plan_sha256':sha(reuse['raw_plan_path']),'authority_policy':'Actualacceptednative→originalowner→roledtype; archiveprecisiondifferences recorded separately without tolerance/normalization',
   'full_context_rows':len(hist),'context_sha256':sha(reuse['context_path']),'native_writes':0,'raw_plan_recomputed':False})
 else:
  archive=base.native(Path(target['archive_member_path']).read_bytes())
  native=base.native(Path(target['native_path']).read_bytes())
  assert sha(target['native_path'])==sha(target['accepted_snapshot_path'])==target['native_sha256']
  # All source history provides recursive context; only existing panel keys in
  # the affected interval are emitted. Native wins its actual accepted overlap.
  context={d:b for d,b in archive.items()if d<=cfg['signal_date']}
  context.update({d:b for d,b in native.items()if d<=cfg['signal_date']})
  ctx=stage/'full_original_context.day';ctx.open('xb').write(b''.join(context[d]for d in sorted(context)))
  hist=owner.read_day_tail(code,ctx,tail_records=len(context));hist=hist.sort_values('trade_date').reset_index(drop=True)
  assert len(hist)==len(context) and hist['ts_code'].eq(code).all()
  byhist={int(x['trade_date']):x for x in hist.to_dict('records')}
  af=owner.read_day_tail(code,Path(target['archive_member_path']),tail_records=len(archive))
  archiveframe={int(x['trade_date']):x for x in af.to_dict('records')}
  old={};raw_plan={};plan_failures=[]
  for role,p in cfg['panels'].items():
   table=ds.dataset(p['path'],format='parquet').to_table(filter=ds.field('ts_code')==code)
   assert table.num_rows and len(set(table['trade_date'].to_pylist()))==table.num_rows
   pq.write_table(table,stage/(role+'_original_stock.parquet'));old[role]=table
   vf=p['volume_field'];before={int(r['trade_date']):r for r in table.to_pylist()}
   dates=sorted(d for d in before if target['repair_first_date']<=d<=cfg['signal_date'])
   missing=sorted(set(dates)-set(byhist));assert not missing,'Existing panel keys absent from source:'+str(missing)
   changes=[];d21=[];source_only=[]
   for col in RAW:
    field=table.schema.field(vf if col=='volume'else col);actualcol=vf if col=='volume'else col
    expected=owner.coerce_series_to_arrow(pd.Series([byhist[d][actualcol]for d in dates]),field).to_pylist()
    arc_dates=[d for d in dates if d in archiveframe]
    arc_expected=dict(zip(arc_dates,owner.coerce_series_to_arrow(pd.Series([archiveframe[d][actualcol]for d in arc_dates]),field).to_pylist()))
    for d,v in zip(dates,expected):
     original=before[d][actualcol]
     if d==cfg['signal_date']:
      d21.append({'column':actualcol,'old':clean(original),'source_dtype':clean(v),'equal':equal(original,v)})
      if not equal(original,v):plan_failures.append('D21_RAW_DISAGREEMENT:'+role+':'+col)
     if equal(original,v):continue
     consensus=d in arc_expected and equal(v,arc_expected[d])
     known=col in ('open','high','low','close')and str(d)in target['known_OHLC_fields']and col in target['known_OHLC_fields'][str(d)]
     item={'trade_date':d,'column':actualcol,'old':clean(original),'accepted_native_owner_dtype':clean(v),
           'archive_owner_dtype':clean(arc_expected.get(d)),'native_archive_dtype_equal':consensus,
           'known_independently_accepted_OHLC_cell':known}
     changes.append(item)
     # New unexplained source-vintage volume/amount disagreements are not
     # silently normalized, and extra prices are not silently added to scope.
     if col in ('open','high','low','close')and not known:plan_failures.append('UNAPPROVED_EXTRA_OHLC:'+role+':'+str(d)+':'+col)
     if col in ('amount','volume')and str(d)not in target['known_OHLC_fields']:plan_failures.append('UNAPPROVED_EXTRA_RAW_DATE:'+role+':'+str(d)+':'+col)
    for d in arc_dates:
     if not equal(byhist[d][actualcol],archiveframe[d][actualcol]):source_only.append({'trade_date':d,'column':actualcol,
       'accepted_native_value':clean(byhist[d][actualcol]),'archive_value':clean(archiveframe[d][actualcol]),
       'classification':'SOURCE_VINTAGE_OR_PRECISION_NO_ASSUMED_TOLERANCE'})
   raw_plan[role]={'repair_dates':dates,'raw_changes':changes,'D21_raw_checks':d21,'cross_source_disagreements':source_only,
     'old_stock_rows':table.num_rows,'existing_first_date':min(before),'existing_last_date':max(before),
     'repair_first_date':min(dates),'repair_last_date':max(dates),'raw_types':{c:str(table.schema.field(vf if c=='volume'else c).type)for c in RAW}}
  save(stage/'RAW_SOURCE_AND_DTYPE_PLAN.json',{'ts_code':code,'roles':raw_plan,'failures':plan_failures,
        'full_context_rows':len(hist),'context_sha256':sha(ctx),'native_writes':0})
  assert not plan_failures,'SOURCE_PLAN_STOP; see persisted RAW_SOURCE_AND_DTYPE_PLAN.json'
 latest=max(int(d)for d in old['legacy_selector']['trade_date'].to_pylist())
 static=owner.read_latest_static_map(Path(reuse['stock_tables']['legacy_selector']) if reuse else stage/'legacy_selector_original_stock.parquet',latest,owner.STATIC_MAP_CANDIDATES,log,active_ts_codes=[code])
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
    values=[existing[int(d)].get(col)for d in frame['trade_date']]
    values=[None if v is None or pd.isna(v)else v for v in values]
    projected=projected.set_column(schema.get_field_index(col),field,pa.array(values,type=field.type))
  for col in RAW:
   actualcol=vf if col=='volume'else col
   assert projected[actualcol].combine_chunks().equals(owner.coerce_series_to_arrow(frame[actualcol],schema.field(actualcol))), 'RAW_PROJECTION_DRIFT'
  d21=projected.filter(pc.equal(projected['trade_date'],str(cfg['signal_date'])if pa.types.is_string(schema.field('trade_date').type)else cfg['signal_date']))
  old21=table.filter(pc.equal(table['trade_date'],str(cfg['signal_date'])if pa.types.is_string(schema.field('trade_date').type)else cfg['signal_date']))
  base.same_values(d21.select(['open','high','low','close','amount',vf]),old21.select(['open','high','low','close','amount',vf]))
  out=stage/(role+'_repair.parquet');pq.write_table(projected,out)
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

def merge(cfg,root,base):
 rows=[json.loads((root/t['ts_code']/'CHECKPOINT.json').read_text())for t in cfg['targets']]
 assert all(r['peak_rss_bytes']<cfg['max_rss_bytes']for r in rows)
 owner=base.owner_module(cfg,root);log=Log(root/'merge.log');roles={}
 for role,p in cfg['panels'].items():
  pieces=[]
  for r in rows:
   q=r['roles'][role];assert sha(q['repair_table_path'])==q['repair_table_sha256'];pieces.append(pq.read_table(q['repair_table_path']))
  new=pa.concat_tables(pieces);keys=new.select(['ts_code','trade_date']).to_pandas();assert not keys.duplicated().any()
  rp=root/(role+'_combined_repair.parquet');pq.write_table(new,rp)
  out=root/(role+'_UNPUBLISHED.parquet');wr=owner.write_appended_parquet(Path(p['path']),new,out,log,retire_keys=[])
  assert wr['current_rows_retired']==0 and wr['new_rows_inserted']==0
  affected={(str(x['ts_code']),int(x['trade_date']))for x in keys.to_dict('records')}
  a,b=pq.ParquetFile(p['path']),pq.ParquetFile(out);rg=0;retained=0
  for batch in a.iter_batches(batch_size=65536):
   table=pa.Table.from_batches([batch],schema=a.schema_arrow)
   keep=[(str(x['ts_code']),int(x['trade_date']))not in affected for x in table.select(['ts_code','trade_date']).to_pylist()]
   expected=table if all(keep)else table.filter(pa.array(keep,type=pa.bool_()))
   if expected.num_rows:base.same_values(expected,b.read_row_group(rg));rg+=1;retained+=expected.num_rows
  tail=pa.concat_tables([b.read_row_group(i)for i in range(rg,b.metadata.num_row_groups)]);base.same_values(new,tail)
  assert retained==wr['current_rows_retained']
  roles[role]={'candidate_path':str(out),'candidate_sha256':sha(out),'candidate_stat':stat(out),'writer':wr,
   'repair_table_path':str(rp),'repair_table_sha256':sha(rp),'all_unaffected_fields_equal_rows':retained,'all_affected_rows':new.num_rows,'D21_raw_exact_preserved':True}
  del a,b,new,tail,pieces;gc.collect()
 return {'status':'PAIRED_UNPUBLISHED_TWO_STOCK_PANELS_READY','roles':roles,'native_writes':0,'authority_writes':0,'pointer_writes':0,'network_calls':0,'formula_calls':0,'full_schema_ready':False}

def main():
 arg=argparse.ArgumentParser();arg.add_argument('phase',choices=('canary','remaining','merge'));a=arg.parse_args()
 cfg=json.loads((N/'CONTRACT_R3.json').read_text());assert E in Path(cfg['start_receipt']).read_text()and'RUN_STARTED'in Path(cfg['start_receipt']).read_text()
 frozen(cfg);root=N/'runs'/E;started=time.monotonic();base=load(cfg['reused_helper_path'],'reviewed_original_recipe')
 if a.phase=='canary':root.mkdir(parents=True,exist_ok=False);result=stock(cfg,cfg['targets'][0],root,base)
 elif a.phase=='remaining':
  assert json.loads((root/'canary_RECEIPT.json').read_text())['safe_to_continue'];result=stock(cfg,cfg['targets'][1],root,base)
 else:
  assert json.loads((root/'remaining_RECEIPT.json').read_text())['safe_to_continue'];result=merge(cfg,root,base)
 frozen(cfg);result.update(execution_id=E,phase=a.phase,elapsed_seconds=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
 assert result['peak_rss_bytes']<cfg['max_rss_bytes'];result['safe_to_continue']=True
 save(root/(a.phase+'_RECEIPT.json'),result)
 print(json.dumps({k:v for k,v in result.items()if k not in ('roles',)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
