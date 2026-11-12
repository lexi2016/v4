"""Read exact D12 original-owner panel once for requested symbols; no producer."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,hashlib,json,pathlib,sys,time,collections,gzip
import pandas as pd,pyarrow as pa,pyarrow.parquet as pq
N=pathlib.Path(__file__).resolve().parents[1]
COLUMNS=['ts_code','trade_date','market_type','exchange','name','open','high','low','close','volume','amount','BBI','zge_white_line','zge_yellow_line','J','kdj_k','kdj_d','macd_dif','macd_dea','macd_hist','brick_type_value','brick_length','formula_source','field_contract_version','B1','B2','B3','user_v1_B1','user_v1_B2','user_v1_B3','user_v1_break_prev_low','user_v1_under_yellow','user_v1_white_yellow_death_cross','user_v1_hold_yesterday_keyline_daily','user_v1_break_yesterday_keyline_daily','user_v1_sell_signal_daily']
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['canary','remaining']);args=a.parse_args();f=json.loads((N/'RUN_FREEZE.json').read_text());os.environ.update(f['env']);sys.path.insert(0,f['env']['V4_APP_ROOT'])
 from ops import research_panel_daily_product as prod,research_panel_logical as logical
 for key in ('selector','receipt','snapshot','quarantine','source_config'):prod.checked(f[key])
 if args.phase=='canary':keys=['601689.SH','002371.SZ','920001.BJ']
 else:
  progress=json.loads((N/'ENGINE_PROGRESS.json').read_text());assert progress['status']=='FRESH_FULL_UNIVERSE_COMPLETE' and progress['completed']==len(f['scope'])
  rows=[];candidates=[];contexts=[]
  for symbol in f['scope']:
   proof=json.loads((N/'engine_proofs'/(symbol+'.json')).read_text());row=json.loads(prod.checked(proof['row']).read_bytes());assert row['symbol']==symbol and row['data_date']=='20261112' and proof['generation']==f['source_identity']['generation']
   out=dict(security_code=symbol,display_name=row.get('display_name'),source_date='2026-11-12',source_generation=f['source_identity']['generation'],groups=row['groups'],pending_groups=row['pending_groups'],candidate=bool(row['groups']),qualification_status=row['qualification'].get('status'),qualification_reason=row['qualification'].get('reason'),fresh_engine_kernel_called=proof['original_kernel_called'],formula_engine_compute_calls=proof['engine_compute_calls'],row_sha256=proof['row']['sha256'],row_path=proof['row']['path'])
   for group in prod.GROUPS:out[group+'_status']=row['evaluation']['groups'][group]['status']
   rows.append(out)
   if row['groups']:
    candidates.append(dict(symbol=symbol,name=row.get('display_name') or symbol,source_date='2026-11-12',source_generation=f['source_identity']['generation'],groups=row['groups'],pending_groups=row['pending_groups'],latest_new_anchor=row.get('latest_new_anchor'),risk_clear=row.get('risk_clear'),computation_row_sha256=proof['row']['sha256']))
    contexts.append(dict(symbol=symbol,evaluation=row['evaluation'],computation_row_sha256=proof['row']['sha256'],qualification=row['qualification'],historical_coverage=row['historical_coverage']))
  data=N/'data';data.mkdir(exist_ok=True);pd.DataFrame(rows).to_csv(data/'FULL_UNIVERSE_FRESH_LEDGER.csv',index=False);pd.DataFrame(candidates).to_csv(data/'CANDIDATES.csv',index=False)
  with gzip.open(data/'STRUCTURE_CONTEXT.json.gz','wt')as h:json.dump(dict(source_generation=f['source_identity']['generation'],data_date='20261112',rows=contexts),h,ensure_ascii=False)
  counts=dict(total=len(rows),candidates=len(candidates),pending=sum(bool(r['pending_groups'])for r in rows),by_group={g:dict(collections.Counter(r[g+'_status']for r in rows))for g in prod.GROUPS},qualification=dict(collections.Counter(r['qualification_status']for r in rows)),kernel_calls=sum(r['formula_engine_compute_calls']for r in rows),every_symbol_kernel_called=all(r['fresh_engine_kernel_called']for r in rows));save(N/'FULL_UNIVERSE_COVERAGE.json',counts)
  keys=[c['symbol']for c in candidates if c['symbol']not in {'601689.SH','002371.SZ','920001.BJ'}]
 p=N/'data'/(args.phase.upper()+'_PREFIX.parquet');p.parent.mkdir(exist_ok=True)
 if p.exists():raise RuntimeError('PROJECTION_EXISTS_NO_OVERWRITE')
 reader=logical.parquet.ParquetFile(f['selector']['path']);contract=json.loads(reader.schema_arrow.metadata[b'a_share_qfq_contract_v1']);assert contract['asof_date']==20261112 and contract['generation_id']==f['source_identity']['generation']
 missing=set(COLUMNS)-set(reader.schema_arrow.names);assert not(set(COLUMNS[:24])&missing),'MISSING_ESSENTIAL:'+str(missing)
 t=time.perf_counter();table=reader.read(columns=[c for c in COLUMNS if c not in missing],filters=[('ts_code','in',keys),('trade_date','<=','20261112')]);df=table.to_pandas();df['trade_date']=df.trade_date.astype(str)
 ok=((df.market_type=='A_SHARE')&df.exchange.isin(['SH','SZ','BJ']))|((df.market_type=='BJ')&(df.exchange=='BJ'));df=df[ok].sort_values(['ts_code','trade_date']).reset_index(drop=True)
 assert not df.duplicated(['ts_code','trade_date']).any() and (df.trade_date<='20261112').all() and set(df.ts_code)<=set(keys)
 for col in missing:df[col]=float('nan')
 pq.write_table(pa.Table.from_pandas(df,preserve_index=False),p,compression='zstd');today=df[df.trade_date=='20261112']
 receipt=dict(status='EXACT_D12_PREFIX_PROJECTED',phase=args.phase,keys=keys,requested=len(keys),exact_D_symbols=today.ts_code.nunique(),missing_D=sorted(set(keys)-set(today.ts_code)),rows=len(df),source_generation=f['source_identity']['generation'],max_date=df.trade_date.max(),missing_columns=sorted(missing),projection_sha256=sha(p),source_sha256=f['selector']['sha256'],wall_seconds=time.perf_counter()-t,fit_count=0)
 save(N/'validation'/(args.phase.upper()+'_PROJECTION.json'),receipt);print(json.dumps({k:v for k,v in receipt.items()if k!='keys'}),flush=True)
if __name__=='__main__':main()
