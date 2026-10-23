"""Final six-code source-bound delta; legal exceptions are exact dated events, not tuned ratios."""
import argparse,csv,hashlib,json,struct,sys,zipfile
from pathlib import Path
from datetime import datetime
from collections import Counter
sys.dont_write_bytecode=True
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(p,x):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=load(cp);b=c['input_identity'];out=Path(c['output_directory']);base=load(b['parent_manifest']);targets=[r for r in base['all_input_statuses'] if r['status']=='CANNOT_CONFIRM'];assert {r['code'] for r in targets}==set(c['codes'])
 def fence(event,args):
  if event.startswith(('socket.connect','socket.bind','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_SAME_SOURCE_ONLY')
 sys.addaudithook(fence);import pyarrow.dataset as ds,pyarrow as pa,pyarrow.parquet as pq
 sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 from event_aware_candidate_input import normalized_events,validate,project
 panel=b['raw_selector'];archive=b['archive'];assert c['codes']==sorted(c['codes']);stat=lambda p:{'inode':Path(p).stat().st_ino,'mtime_ns':Path(p).stat().st_mtime_ns,'size_bytes':Path(p).stat().st_size};assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat'];frames={code:[] for code in c['codes']}
 for batch in ds.dataset(panel['path'],format='parquet').scanner(columns=['ts_code','trade_date','open','high','low','close','volume'],filter=ds.field('ts_code').isin(c['codes'])&(ds.field('trade_date')<='20261022'),use_threads=False,batch_size=65536).to_batches():
  for row in batch.to_pylist():frames[row['ts_code']].append(row)
 eventrefs=load(b['event_index']);records=[];catalog=dict(base['catalog']);out.joinpath('inputs').mkdir();out.joinpath('raw').mkdir()
 with zipfile.ZipFile(archive['path']) as z:
  members={i.filename.replace('\\','/').lower():i for i in z.infolist()};calendars={};calendar_bindings=[]
  for name in c['calendar_date_only_members']:
   info=members[name];dates=[];h=hashlib.sha256()
   with z.open(info) as f:
    while True:
     raw=f.read(32)
     if not raw:break
     assert len(raw)==32;h.update(raw);d=str(struct.unpack('<I',raw[:4])[0]);datetime.strptime(d,'%Y%m%d');assert not dates or d>dates[-1];dates.append(d)
   calendars[name]=[d for d in dates if '20240801'<=d<='20261022'];calendar_bindings.append({'member':info.filename,'CRC':info.CRC,'sha256':h.hexdigest(),'date_only_projection':True,'selected_date_count':len(calendars[name]),'first_selected_date':calendars[name][0],'last_selected_date':calendars[name][-1],'price_fields_decoded':0})
  assert len({tuple(d) for d in calendars.values()})==1,'TWO_INDEX_MARKET_CALENDAR_DATE_CONFLICT';market_dates=next(iter(calendars.values()))
  inherited_ipo=[]
  for e in base['prefix63_exact_IPO_exceptions']:
   d=e['listing']['date'];five=[x for x in market_dates if x>=d][:5];assert five[0]==d and e['date'] in five and e['previous_date'] in five,'63IPO_MARKET_CALENDAR_MISMATCH';inherited_ipo.append({'code':e['code'],'date':e['date'],'listing_date':d,'exact_first_five_market_dates':five,'source63_exception_accepted_with_calendar':True})
  for old in targets:
   code=old['code'];num,ex=code.split('.');original=sorted(frames[code],key=lambda r:r['trade_date']);first=original[0]['trade_date'];oldkeys={r['trade_date'] for r in original};info=members[ex.lower()+'/lday/'+ex.lower()+num+'.day'];h=hashlib.sha256();selected=[];rawbytes=[];alldates=[]
   with z.open(info) as f:
    while True:
     raw=f.read(32)
     if not raw:break
     assert len(raw)==32;h.update(raw);d=str(struct.unpack('<I',raw[:4])[0]);datetime.strptime(d,'%Y%m%d');assert not alldates or d>alldates[-1];alldates.append(d)
     if not first<=d<='20261022':continue
     rawbytes.append(raw);v=struct.unpack('<IIIIIfII',raw);selected.append({'ts_code':code,'trade_date':d,'open':v[1]/100,'high':v[2]/100,'low':v[3]/100,'close':v[4]/100,'volume':v[6]})
   keys={r['trade_date'] for r in selected};record={'code':code,'old_status':'CANNOT_CONFIRM','status':'CANNOT_CONFIRM','compute_window_start':first,'window_rule':'ORIGINAL_BOUND_SELECTOR_FIRSTDATE_NOT_ERROR_DRIVEN_TRUNCATION','original_rows':len(original),'source_member':info.filename,'source_member_sha256':h.hexdigest(),'source_first_date':alldates[0],'source_last_date':alldates[-1],'missing_original_dates_from_archive':sorted(oldkeys-keys),'original_source_rows_preserved_in_bound_panel':True,'source_row_count_in_window':len(selected),'source_last_date_in_window':selected[-1]['trade_date'] if selected else None}
   if oldkeys-keys:record['reason']='ORIGINAL_DERIVED_DATE_KEYS_ABSENT_FROM_CURRENT_OFFICIAL_SOURCE_RETAIN_UNKNOWN';record['source_calendar_near_missing']={d:[x for x in alldates if str(int(d)-5)<=x<=str(int(d)+5)] for d in sorted(oldkeys-keys)};records.append(record);continue
   p=out/'raw'/(code+'.day');p.write_bytes(b''.join(rawbytes));bars=owner.read_hq_day_bars(p,tail_records=None);assert len(bars)==len(rawbytes);invalid=[{'date':owner.day_int(r),'reason':owner.valid_hq_bar(r)[1]} for r in bars if not owner.valid_hq_bar(r)[0]];ref=eventrefs[code];assert sha(ref['path'])==ref['sha256'];ev,unsupported=normalized_events(load(ref['path'])['response_rows']);sigs=owner._local_field_signature_violations(p,symbol=num,market=1 if ex=='SH' else 0,run_id=c['execution_id'],recorded_at=None)
   if invalid or sigs:record.update(reason='ORIGINAL_OWNER_RAW_FIELD_OR_SIGNATURE_GUARD_FAILED',invalid=invalid,signature_count=len(sigs));records.append(record);continue
   v=validate(bars,owner,ev,unsupported);allowed=[];remaining=[];legal=c['exact_market_event_rules'].get(code)
   for error in v['failures']:
    accept=False
    if legal and error.get('reason')=='UNEXPLAINED_RAW_CONTINUITY_DISCONTINUITY':
     d=str(error['date']);pd=str(error['previous_date'])
     if legal['type']=='IPO_FIRST_FIVE_UNRESTRICTED':
      five=[x for x in market_dates if x>=legal['listing_date']][:5];accept=alldates[0]==legal['listing_date'] and d in five and pd in five
     else:five=None;accept=d==legal['event_date']
     if accept:allowed.append({'original_failure':error,'exact_legal_rule':legal,'exact_first_five_market_dates':five,'threshold_changed':False})
    if not accept:remaining.append(error)
   record.update(unchanged_owner_field_signature_pass=True,validation_original=v,exact_legal_exceptions=allowed,remaining_errors=remaining,raw_path=str(p),raw_sha256=sha(p))
   if remaining:record['reason']='UNEXPLAINED_RATIO_OR_EVENT_REMAINS';records.append(record);continue
   adjusted=project(selected,ev);q=out/'inputs'/(code+'.parquet');pq.write_table(pa.Table.from_pylist(adjusted),q,compression='zstd');record.update(status='READY',name=old['name'],path=str(q),format='parquet',sha256=sha(q),row_sha256=digest(adjusted),rows=len(adjusted),first_date=adjusted[0]['trade_date'],last_date=adjusted[-1]['trade_date'],price_basis=c['price_basis'],volume_basis=c['volume_basis'],risk_flags=['DELISTING_CONSOLIDATION_PERIOD'] if code=='301139.SZ' else []);records.append(record);catalog[code]={**old,**record}
 statuses=[catalog.get(r['code'],{**r,'final64_failure':next((x for x in records if x['code']==r['code']),None)}) for r in base['all_input_statuses']];lineage=load(b['parent318'])
 for r in lineage:
  code=r['canonical_code']
  if code in catalog:r['input_status']=catalog[code]['status'];r['disposition']='D22_RESEARCH_INPUT_AVAILABLE_ALIAS_REUSED' if code!=r['source_key'] else 'D22_RESEARCH_INPUT_RECOVERED';r['reason']='SOURCE_BOUND_RESEARCH_INPUT_AVAILABLE_NO_LIVE_NATIVE_PROMOTION'
 save(out/'ORIGINAL318_DISPOSITION.json',lineage);manifest={**base,'execution_id':c['execution_id'],'verified_start':gate,'parent_manifest_sha256':b['parent_manifest_sha256'],'catalog':catalog,'all_input_statuses':statuses,'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':5533-len(catalog),'new_D22_research_input_codes':sum(r['code'] not in {x['code'] for x in base['all_input_statuses'] if not x['new_D22_research_input']} for r in catalog.values()),'final64_calendar_bindings':calendar_bindings,'final64_inherited63_IPO_calendar_rechecked':inherited_ipo,'final64_records':records,'original318_dispositions':dict(Counter(r['disposition'] for r in lineage))};save(out/'INPUT_MANIFEST.json',manifest);save(out/'MARKET_EVENT_DELTA_RECEIPT.json',{'execution_id':c['execution_id'],'records':records,'calendar_bindings':calendar_bindings,'inherited63_IPO_calendar_rechecked':inherited_ipo,'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':5533-len(catalog),'healthy5527_inputs_recomputed':0,'native_writes':0,'network':0,'threshold_changed':False,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False});assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat'];print(json.dumps({'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':5533-len(catalog),'delta_ready':sum(r['status']=='READY' for r in records),'unavailable':[(r['code'],r.get('reason')) for r in records if r['status']!='READY']},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
