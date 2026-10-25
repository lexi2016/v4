"""Read-only, saved-selection descriptive audit. No fit/predict/market collection."""
import sys,csv,json,hashlib,math,re,shutil,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import pandas as pd
import pyarrow.parquet as pq
from register import OUT,save,sha
STAGES=['STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500']
STORE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection')
def norm(x):
 s=str(x).upper().strip()
 if re.fullmatch(r'(SH|SZ|BJ)\.\d{6}',s):return s[3:]+'.'+s[:2]
 if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',s):return s
 if re.fullmatch(r'(A\.)?\d{6}',s):
  s=s[-6:];return s+'.'+('SH' if s[0]=='6' else 'BJ' if s[0] in '489' else 'SZ')
 raise ValueError('INVALID_A_CODE:'+s)
def unique_codes(rows):
 codes=[norm(r.get('ts_code') or r.get('code') or r.get('symbol')) for r in rows]
 if len(set(codes))!=len(codes):raise ValueError('DUPLICATE_SELECTED_CODE')
 return codes
def top100(frame):
 f=frame.copy();f['return_pct']=(f['close']/f['pre_close']-1)*100
 valid=f['close'].gt(0)&f['pre_close'].gt(0)&f['return_pct'].map(math.isfinite)
 if f[['trade_date','ts_code']].duplicated().any():raise ValueError('DUPLICATE_TRUTH_KEY')
 f=f[valid].sort_values(['return_pct','ts_code'],ascending=[False,True],kind='stable');f['daily_rank']=range(1,len(f)+1)
 return f

def cell_metrics(selected,truth,initial=None):
 if selected is None:return dict(actual_selected_count=None,hit_count=None,hit_precision=None,top100_recall=None,initial_pool_top100_hits=None,screen_retention=None,selection_slots=None,truth_positive_denominator=None)
 keys=unique_codes(selected);lookup=set(truth.head(100).ts_code);hits=len(set(keys)&lookup);known=set(truth.ts_code)
 poolhits=None if initial is None else len(set(initial)&lookup)
 return dict(actual_selected_count=len(keys),hit_count=hits,hit_precision=hits/len(keys) if keys else None,top100_recall=hits/min(100,len(truth)) if len(truth) else None,initial_pool_top100_hits=poolhits,screen_retention=hits/poolhits if poolhits else None,selection_slots=len(keys),truth_positive_denominator=min(100,len(truth)),selected_truth_missing_count=len(set(keys)-known))
def fetch(url,p):
 if p.exists():return {'path':str(p),'sha256':sha(p),'url':url,'capture_time_qualification':'EXISTING_IMMUTABLE_CAPTURE_REUSED'}
 try:
  with urllib.request.urlopen('http://127.0.0.1:8873'+url,timeout=40) as r:raw=r.read()
  json.loads(raw);p.write_bytes(raw)
 except Exception as e:save(p,{'capture_error':type(e).__name__+':'+str(e),'url':url})
 return {'path':str(p),'sha256':sha(p),'url':url,'captured_at':datetime.now(timezone.utc).isoformat()}
def capture():
 snap=OUT/'snapshots';snap.mkdir(exist_ok=True);api=snap/'api';api.mkdir(exist_ok=True);saved=snap/'saved';saved.mkdir(exist_ok=True)
 dates=json.loads((OUT/'CALENDAR.json').read_text())['dates'];refs=[]
 refs.append(fetch('/api/v1/runs/date-list',api/'date_list.json'))
 tasks=[(f'/api/v3/workbench/stage?date={d}&stage={s}&limit=50',api/f'{d}_{s}.json') for d in dates for s in STAGES]
 with ThreadPoolExecutor(max_workers=4) as ex:refs.extend(ex.map(lambda t:fetch(*t),tasks))
 for d in dates:
  offset=0
  for page in range(100):
   p=api/f'{d}_pools_{offset}.json';refs.append(fetch(f'/api/v3/preselection-pools?date={d}&limit=300&offset={offset}',p));j=json.loads(p.read_text());pag=j.get('pagination',{});has=pag.get('has_more',False)
   # Continue any child array/pool that still has pages, irrespective global readiness.
   more=[v.get('next_offset') for v in [*pag.get('arrays',{}).values(),*pag.get('pools',{}).values()] if v.get('has_more')]
   if not more and not has:break
   offset=min(x for x in more if x is not None) if more else offset+300
   if offset<=page*300:raise ValueError('PAGINATION_NO_PROGRESS')
  else:raise ValueError('PAGINATION_BOUND_EXCEEDED')
 latest=STORE/'selection_latest.json';
 if not (saved/'selection_latest.json').exists():shutil.copy2(latest,saved/'selection_latest.json')
 j=json.loads((saved/'selection_latest.json').read_text());entries={}
 for d in dates:
  for s in STAGES:
   key=f'{d}/{s}/A_SHARE';e=j['entries'].get(key)
   if e is None:continue
   dest=saved/d/s;dest.mkdir(parents=True,exist_ok=True);entry=dict(e)
   for fn,hkey in [('artifact.csv','artifact_sha256'),('manifest.json','manifest_sha256'),('receipt.json','receipt_sha256')]:
    p=(STORE/e['artifact_relative']).parent/fn;target=dest/fn

    if not target.exists():shutil.copy2(p,target)
    entry[fn+'_identity_valid']=sha(target)==e[hkey];refs.append(dict(path=str(target),source_path=str(p),sha256=sha(target)))
   entries[key]=entry
 save(snap/'SAVED_ENTRIES.json',entries)
 # Freeze compact immutable truth projection, excluding legacy-preserved ambiguous codes.
 b=json.loads((OUT/'INPUT_BINDING.json').read_text());p=Path(b['panel_path']);before=p.stat();expected=b['refs'][str(p)]
 assert sha(p)==expected,'CURRENT_PANEL_SHA_DRIFT'
 cols=['trade_date','ts_code','market_type','name','close','pre_close','pct_chg','volume'];kind=pq.ParquetFile(p).schema_arrow.field('trade_date').type
 import pyarrow as pa
 cast=str if pa.types.is_string(kind) or pa.types.is_large_string(kind) else int
 f=pq.read_table(p,columns=cols,filters=[('trade_date','>=',cast(dates[0])),('trade_date','<=',cast(dates[-1]))]).to_pandas();f=f[f.market_type.eq('A_SHARE')].copy();f['trade_date']=f.trade_date.astype(str)
 meta=json.loads((OUT/'PANEL_METADATA.json').read_text());legacy=json.loads(Path(meta['legacy_preservation_policy']['path']).read_text());excluded=set(legacy.get('codes',[]));f=f[~f.ts_code.isin(excluded)]
 assert p.stat()==before,'PANEL_CHANGED_DURING_SNAPSHOT';f.to_csv(snap/'truth_projection.csv',index=False);save(snap/'TRUTH_QUALIFICATION.json',dict(source_path=str(p),source_sha256=expected,projection_sha256=sha(snap/'truth_projection.csv'),excluded_legacy_codes=sorted(excluded),return_formula='100*(QFQ_close/QFQ_pre_close-1)',label='AVAILABLE_CURRENT_RESEARCH_PANEL_TOP100_QFQ_RETURN',full_A_membership_certified=False,historical_PIT=False,natural_verified=False))
 save(snap/'CAPTURE_MANIFEST.json',dict(captured_at=datetime.now(timezone.utc).isoformat(),refs=refs,truth_projection_sha256=sha(snap/'truth_projection.csv')))
 return {'api_snapshots':len(refs),'truth_rows':len(f),'saved_cells':len(entries)}

def saved_rows(d,s):
 snap=OUT/'snapshots';entries=json.loads((snap/'SAVED_ENTRIES.json').read_text());e=entries.get(f'{d}/{s}/A_SHARE');api=json.loads((snap/'api'/f'{d}_{s}.json').read_text());am=(api.get('selection_markets') or {}).get('A_SHARE') or (api.get('markets') or {}).get('A') or {}
 info=dict(api_status=am.get('status'),api_selection_status=am.get('selection_status'),api_error=api.get('capture_error'),saved_run_id=e.get('run_id') if e else None,temporal_qualification='SAVED_AT_UNKNOWN_OR_AFTER_CUTOFF_DESCRIPTIVE_ONLY',natural_verified=False,late_stage_predictive=False if s=='STAGE_1445_1500' else None)
 if not e:return None,{**info,'selection_state':'MISSING_SAVED_ARTIFACT'}
 binding=json.loads((snap/'SAVED_VERIFIER_BINDING.json').read_text());runtime=binding['runtime_root']
 if runtime not in sys.path:sys.path.insert(0,runtime)
 from stage_center.selection import SelectionStore
 try:env=SelectionStore(snap/'verified_store').read_verified(d,s,'A_SHARE')
 except Exception as ex:return None,{**info,'selection_state':'INVALID_SAVED_ARTIFACT','verification_error':type(ex).__name__+':'+str(ex)}
 rows=env.get('rows',[])
 unique_codes(rows)
 info.update(selected_source_modes=sorted({str(r.get('source_mode')) for r in rows}),saved_selection_status=env.get('selection_status'),saved_source_status=env.get('source_status'),saved_source_evidence=env.get('source_evidence'),saved_requested_rows=env.get('requested_rows'),saved_source_rows=env.get('source_rows'),saved_cannot_confirm=env.get('cannot_confirm'),selection_state='SAVED_SELECTED_LIST' if rows else 'CONFIRMED_EMPTY_SAVED_LIST')
 if not rows and env.get('selection_status') not in ['READY','EMPTY','NO_CANDIDATES','SELECTED','COMPLETE','READY_EMPTY']:return None,{**info,'selection_state':'UNAVAILABLE_EMPTY_ARTIFACT'}
 return rows,info

def initial_pool(d):
 files=sorted((OUT/'snapshots/api').glob(f'{d}_pools_*.json'));codes=set();total=None;names={}
 for p in files:
  j=json.loads(p.read_text());a=j.get('a_all_pool_rows',[])
  for r in a:
   try:k=norm(r.get('ts_code') or r.get('code') or r.get('symbol'))
   except ValueError:continue
   codes.add(k);names[k]=r.get('stock_name') or r.get('display_name')
  total=j.get('pagination',{}).get('arrays',{}).get('a_all_pool_rows',{}).get('total_rows',total)
 return (codes if total is not None and len(codes)==total else None),names,dict(initial_pool_capture_count=len(codes),initial_pool_total=total,initial_pool_complete=total is not None and len(codes)==total,initial_pool_temporal_qualification='CURRENT_READBACK_NOT_PROVEN_HISTORICAL_STAGE_INPUT')

def evaluate(dates,dest):
 dest.mkdir(exist_ok=False);f=pd.read_csv(OUT/'snapshots/truth_projection.csv',dtype={'trade_date':str,'ts_code':str});cells=[];details=[];winners=[];daily=[];gaps=[]
 last5=json.loads((OUT/'CALENDAR.json').read_text())['dates'][-5:]
 for d in dates:
  truth=top100(f[f.trade_date.eq(d)]);pool,names,pinfo=initial_pool(d);union=set();per={};valid=0;look=truth.set_index('ts_code').to_dict('index')
  for s in STAGES:
   rows,info=saved_rows(d,s);sb=json.loads((OUT/'snapshots/STAGE_INPUT_BINDINGS.json').read_text()).get(f'{d}/{s}/A_SHARE',{});stagepool=set(sb['codes']) if 'codes' in sb else None;metrics=cell_metrics(rows,truth,stagepool);info.update({k:v for k,v in sb.items() if k!='codes'});metrics.update(current_captured_pool_top100_hits=len(pool&set(truth.head(100).ts_code)) if pool is not None else None,initial_pool_top100_coverage=metrics['initial_pool_top100_hits']/min(100,len(truth)) if metrics['initial_pool_top100_hits'] is not None and len(truth) else None,selected_outside_bound_stage_input_count=len(set(unique_codes(rows))-stagepool) if rows is not None and stagepool is not None else None);cell=dict(trade_date=d,stage=s,benchmark='AVAILABLE_CURRENT_RESEARCH_PANEL_TOP100_QFQ_RETURN',truth_available_count=len(truth),**pinfo,**metrics,**{k:v for k,v in info.items() if k not in ['saved_source_evidence','saved_cannot_confirm']});cells.append(cell)
   gaps.append(dict(trade_date=d,stage=s,**info))
   keys=unique_codes(rows) if rows is not None else [];per[s]=set(keys);union.update(keys);valid+=rows is not None
   if d in last5:
    if rows is None:details.append(dict(trade_date=d,stage=s,selection_state=info['selection_state'],ts_code=None,name=None,return_pct=None,daily_rank=None,top100_hit=None))
    for r,k in zip(rows or [],keys):
     t=look.get(k);details.append(dict(trade_date=d,stage=s,selection_state=info['selection_state'],ts_code=k,name=(t or {}).get('name') or names.get(k),return_pct=(t or {}).get('return_pct'),daily_rank=(t or {}).get('daily_rank'),top100_hit=(t['daily_rank']<=100 if t else None),selected_rank=r.get('rank'),selected_score=r.get('score'),close=(t or {}).get('close'),pre_close=(t or {}).get('pre_close')))
  for _,r in truth.head(100).iterrows():
   k=r.ts_code;hits=[s for s in STAGES if k in per[s]];inpool=k in pool if pool is not None else None
   cls='SELECTED_IN_AT_LEAST_ONE_SAVED_STAGE' if hits else 'NOT_IN_CURRENT_CAPTURED_INITIAL_POOL' if inpool is False else 'IN_CURRENT_POOL_NOT_SELECTED_IN_AVAILABLE_SAVED_STAGES' if inpool and valid else 'NO_AVAILABLE_STAGE_SELECTION_EVIDENCE' if valid==0 else 'INITIAL_POOL_MEMBERSHIP_UNKNOWN'
   winners.append(dict(trade_date=d,ts_code=k,name=r['name'],return_pct=r.return_pct,daily_rank=r.daily_rank,initial_pool_member=inpool,stage_hits='|'.join(hits),stage_hit_count=len(hits),known_miss_classification=cls,classification_limit='CURRENT_POOL_DESCRIPTIVE_ONLY; MISSING_STAGES_NOT_FAILURES',**{s:k in per[s] if any(c['trade_date']==d and c['stage']==s and c['actual_selected_count'] is not None for c in cells) else None for s in STAGES}))
  daily.append(dict(trade_date=d,truth_available_count=len(truth),truth_top100_count=min(100,len(truth)),available_saved_stage_count=valid,missing_stage_count=7-valid,crossstage_unique_selected_codes=len(union) if valid else None,crossstage_unique_top100_hits=len(union&set(truth.head(100).ts_code)) if valid else None,**pinfo))
 for name,rows in [('stage_cells',cells),('daily_summary',daily),('last5_selected_stocks',details),('daily_top100_stage_hits',winners)]:pd.DataFrame(rows).to_csv(dest/(name+'.csv'),index=False)
 save(dest/'source_gaps.json',gaps)
 sums=[]
 for s in STAGES:
  rows=[c for c in cells if c['stage']==s and c['actual_selected_count'] is not None];slots=sum(c['selection_slots'] for c in rows);hits=sum(c['hit_count'] for c in rows);den=sum(c['truth_positive_denominator'] for c in rows)
  sums.append(dict(stage=s,available_cells=len(rows),missing_cells=len(dates)-len(rows),actual_selection_slots=slots,hit_count=hits,hit_precision=hits/slots if slots else None,truth_positive_denominator=den,top100_recall=hits/den if den else None,all20_recall=None,all20_recall_reason='MISSING_CELLS_EXCLUDED_NOT_ZERO' if len(rows)<len(dates) else 'USE_TOP100_RECALL'))
 pd.DataFrame(sums).to_csv(dest/'stage_summary.csv',index=False)
 result=dict(status='DIRECTION_ONLY',benchmark='AVAILABLE_CURRENT_RESEARCH_PANEL_TOP100_QFQ_RETURN',full_A_market_top100='CANNOT_CONFIRM',dates=dates,calendar_rows=len(daily),stage_cells=len(cells),last5_dates=last5,available_cells=sum(c['actual_selected_count'] is not None for c in cells),missing_cells=sum(c['actual_selected_count'] is None for c in cells),selection_slots=sum(c['selection_slots'] or 0 for c in cells),hit_count=sum(c['hit_count'] or 0 for c in cells),truth_positive_denominator=sum(c['truth_positive_denominator'] or 0 for c in cells),natural_verified=False,historical_PIT=False,late_stage_predictive_claim=False,upstream_sameK='NOT_COMPUTED_HISTORICAL_FULL_INPUT_RANKING_NOT_BOUND',RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 save(dest/'RESULT.json',result);save(dest/'OUTPUT_MANIFEST.json',{str(p.relative_to(dest)):sha(p) for p in dest.iterdir() if p.is_file() and p.name!='OUTPUT_MANIFEST.json'});return result
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['capture','canary','full']);a=p.parse_args()
 print(json.dumps(capture() if a.mode=='capture' else evaluate([json.loads((OUT/'CALENDAR.json').read_text())['dates'][-2]] if a.mode=='canary' else json.loads((OUT/'CALENDAR.json').read_text())['dates'],OUT/('canary_r3b' if a.mode=='canary' else 'results')),ensure_ascii=False))
