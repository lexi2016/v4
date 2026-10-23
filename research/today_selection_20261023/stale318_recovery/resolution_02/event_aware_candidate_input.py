"""Research-only same-owner RAW validation and D22 event-affine/share-volume projection."""
import argparse,csv,hashlib,json,math,os,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def normalized_events(rows,from_cache=False):
 from affine_forward_adjust import event_coefficients
 out=[];unsupported=[]
 for e in rows:
  if from_cache:d=int(e['_xdxr_trade_date']);cat=1;vals={k:e['xdxr_'+k] for k in ['fenhong','peigujia','songzhuangu','peigu']}
  else:d=int(e['year'])*10000+int(e['month'])*100+int(e['day']);cat=e['category'];vals={k:e.get(k) for k in ['fenhong','peigujia','songzhuangu','peigu']}
  from datetime import datetime
  datetime.strptime(str(d),'%Y%m%d')
  if d>20261022:continue
  if cat in (11,12):unsupported.append({'date':d,'category':cat,'row':e})
  if cat!=1:continue
  a,b=event_coefficients(vals);out.append({'date':d,'A':a,'B':b,'share_multiplier':1+vals['songzhuangu']/10+vals['peigu']/10,'source_fields':vals})
 out.sort(key=lambda e:e['date']);assert len({e['date'] for e in out})==len(out),'EVENT_DUPLICATES';return out,unsupported
def validate(rows,owner,events,unsupported):
 dates=[];failures=[];explained=[];raw_exceedances=[]
 for i,row in enumerate(rows):
  d=owner.day_int(row);valid,why=owner.valid_hq_bar(row)
  if not valid:failures.append({'date':d,'reason':'ORIGINAL_OWNER_FIELD:'+str(why)})
  if dates and d<=dates[-1]:failures.append({'date':d,'reason':'DATE_ORDER_OR_DUPLICATE'})
  if d>20261022:failures.append({'date':d,'reason':'FUTURE_PRICE_FORBIDDEN'})
  if i:
   prev=rows[i-1];pd=owner.day_int(prev);ratio=row['close']/prev['close'];limit=owner.MAX_CROSS_DAY_CLOSE_RATIO
   if not 1/limit<=ratio<=limit:
    ref=prev['close'];matched=[e for e in events if pd<e['date']<=d]
    for e in matched:ref=ref*e['A']+e['B']
    adjusted=row['close']/ref if ref>0 else None
    fact={'previous_date':pd,'date':d,'previous_bar':dict(prev),'bar':dict(row),'raw_ratio':ratio,'matched_events':matched,'adjusted_previous_close':ref,'adjusted_ratio':adjusted,'unchanged_original_ratio_limit':limit};raw_exceedances.append(fact)
    if matched and adjusted is not None and 1/limit<=adjusted<=limit:explained.append(fact)
    else:failures.append({**fact,'reason':'UNEXPLAINED_RAW_CONTINUITY_DISCONTINUITY'})
  dates.append(d)
 if not dates or dates[-1]!=20261022:failures.append({'reason':'D22_MISSING'})
 if dates:
  failures.extend({'reason':'UNSUPPORTED_SPLIT_OR_CONSOLIDATION_EVENT','event':e} for e in unsupported if dates[0]<e['date']<=dates[-1])
 return {'accepted_research_candidate':not failures,'rows':len(rows),'first_date':dates[0] if dates else None,'last_date':dates[-1] if dates else None,'failures':failures,'raw_exceedances':raw_exceedances,'explained_by_exact_event':explained,'ratio_limit_changed':False}
def project(raw,events):
 """No rounding/fitting; price events affine, volume only disclosed share-growth."""
 out=[]
 for r in raw:
  d=int(r['trade_date']);a,b,g=1.,0.,1.
  for e in events:
   if d<e['date']<=20261022:a,b,g=a*e['A'],b*e['A']+e['B'],g*e['share_multiplier']
  q=dict(r)
  for f in ['open','high','low','close']:q[f]=r[f]*a+b
  q['volume']=r['volume']*g;q.update(event_A=a,event_B=b,share_volume_multiplier=g,anchor='20261022');out.append(q)
 return out
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=json.loads(Path(cp).read_text());b=c['input_identity'];out=Path(c['output_directory'])
 def fence(event,args):
  if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_ONLY')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):assert out.resolve() in Path(os.fsdecode(args[0])).resolve().parents,'OUTPUT_ONLY'
 sys.addaudithook(fence);sys.modules['pytdx']=None;sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 import pyarrow.dataset as ds
 cols=['ts_code','_xdxr_trade_date','xdxr_fenhong','xdxr_peigujia','xdxr_songzhuangu','xdxr_peigu'];cached=ds.dataset(b['event_cache'],format='parquet').scanner(columns=cols,filter=ds.field('ts_code').isin(c['codes']),use_threads=False).to_table().to_pylist();results=[]
 for code in c['codes']:
  spec=b['codes'][code];fresh=spec.get('fresh_event_response')
  if fresh:
   capture=json.loads(Path(fresh).read_text());assert capture['code']==code and capture['response_error'] is None;ev,unsupported=normalized_events(capture['response_rows'])
  else:ev,unsupported=normalized_events([r for r in cached if r['ts_code']==code],True)
  records={};outputs=[]
  for role in ['candidate','full_archive']:
   path=Path(spec[role]);payload=path.read_bytes();assert len(payload)%32==0;rows=owner.read_hq_day_bars(path,tail_records=None);assert len(rows)==len(payload)//32,'OWNER_READER_DROPPED_ROWS';validation=validate(rows,owner,ev,unsupported);signatures=owner._local_field_signature_violations(path,symbol=code.split('.')[0],market=spec['market'],run_id=c['execution_id'],recorded_at=None);validation['signature_count']=len(signatures);validation['accepted_research_candidate']=validation['accepted_research_candidate'] and not signatures;validation['path']=str(path);validation['sha256']=sha(path);records[role]=validation
   if role=='full_archive' and validation['accepted_research_candidate']:
    raw=[]
    for i,r in enumerate(rows):
     v=struct.unpack('<IIIIIfII',payload[i*32:(i+1)*32]);assert owner.day_int(r)==v[0];assert v[6]==int(round(r['vol']*100)),'OWNER_CODEC_VOLUME_ROUNDTRIP'
     raw.append({'ts_code':code,'trade_date':str(v[0]),**{f:float(r[f]) for f in ['open','high','low','close']},'volume':int(v[6])})
    qfq=project(raw,ev);assert len(raw)==len(qfq) and int(raw[-1]['trade_date'])==20261022
    for basis,data in [('RAW',raw),('QFQ_EVENT_AFFINE_SHARE_VOLUME_UNROUNDED',qfq)]:
     p=out/(code+'_'+basis+'.csv')
     with p.open('x',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
     outputs.append({'basis':basis,'path':str(p),'sha256':sha(p),'row_sha256':digest(data),'rows':len(data),'first_date':data[0]['trade_date'],'last_date':data[-1]['trade_date']})
  no_event=validate(owner.read_hq_day_bars(Path(spec['candidate']),tail_records=None),owner,[],[]);assert not no_event['accepted_research_candidate'],'NEGATIVE_NO_EVENT_CONTROL_WAS_NOT_REJECTED'
  results.append({'code':code,'event_source':'ACTUAL55_SAME_TDX_CURRENT_RESPONSE' if fresh else 'EXISTING_TDX_CATEGORY1_CACHE','events':ev,'unsupported_events':unsupported,'validation':records,'negative_without_events_rejected':True,'output_candidates':outputs,'source_and_original_native_unchanged':True})
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'AFTER_SOURCE_DRIFT:'+p
 result={'schema':'SAME_OWNER_EVENT_AWARE_RAW_QFQ_RESEARCH_CANDIDATES_V1','execution_id':c['execution_id'],'verified_start':gate,'results':results,'accepted_full_history_codes':sum(r['validation']['full_archive']['accepted_research_candidate'] for r in results),'accepted_native_range_candidates':sum(r['validation']['candidate']['accepted_research_candidate'] for r in results),'price_basis':'TDX_RAW_PLUS_TDX_EVENT_AFFINE_UNROUNDED_D22_RESEARCH_REPLICA','volume_basis':'TDX_ORIGINAL_STORAGE_UINT32_COUNT_DOMAIN_TIMES_EXPLICIT_SONGZHUAN_RIGHTS_GROWTH;NO_CASH_FACTOR_NO_AUTOFITTING;NOT_GLOBAL_CROSS_VENDOR_UNIT_PARITY','cash_parameter_vendor_difference':'49 documentsFutu effectiveB differsTDX per10cash; preserved/notfitted; notFutuLiveparity','historic_announcements_available_asof_D22':None,'source_or_native_writes':0,'live_data_recovered':0,'network_calls':0,'full_pool_runs':0,'status':'READY_FOR_COMBINED_INDEPENDENT_DATA_INPUT_REVIEW_NOT_PROMOTED','research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};(out/'DATA_INPUT_CANDIDATE_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'accepted_full_history_codes':result['accepted_full_history_codes'],'accepted_native_range_candidates':result['accepted_native_range_candidates'],'status':result['status'],'network_calls':0,'live_data_recovered':0},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
