"""One source-bound research projection; never replaces native data or an authority pointer."""
import argparse,csv,gzip,hashlib,json,math,os,struct,sys,zipfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
FIELDS=('open','high','low','close','volume')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 if isinstance(x,float) and not math.isfinite(x):return None
 return x
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,x):
 p=Path(p);assert not p.exists();p.write_text(json.dumps(clean(x),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size_bytes':s.st_size}
def date8(x):return str(x).replace('-','')[:8]
def consumer_check(rows,events,unsupported,limit):
 dates=[int(r['trade_date']) for r in rows];errors=[];missing={f:sum(not math.isfinite(r[f]) or (r[f]<=0 if f!='volume' else r[f]<0) for r in rows) for f in FIELDS}
 if not dates or dates!=sorted(set(dates)) or dates[-1]!=20261022 or max(dates)>20261022:errors.append('EMPTY_DUPLICATE_DATE_ORDER_FUTURE_OR_STALE')
 if dates and any(dates[0]<e['date']<=20261022 for e in unsupported):errors.append('UNSUPPORTED_SPLIT_CONSOLIDATION_EVENT')
 for prev,row in zip(rows,rows[1:]):
  if not (math.isfinite(prev['close']) and math.isfinite(row['close']) and prev['close']>0 and row['close']>0):continue
  ratio=row['close']/prev['close']
  if 1/limit<=ratio<=limit:continue
  relevant=[e for e in events if int(prev['trade_date'])<e['date']<=int(row['trade_date'])];ref=prev['close']
  for e in relevant:ref=ref*e['A']+e['B']
  if not relevant or ref<=0 or not 1/limit<=row['close']/ref<=limit:errors.append({'reason':'UNEXPLAINED_RAW_RATIO','previous_date':prev['trade_date'],'date':row['trade_date'],'raw_ratio':ratio,'event_normalized_ratio':row['close']/ref if ref>0 else None})
 return {'errors':errors,'missing_fields':missing,'ready':not errors}
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=load(cp);b=c['input_identity'];out=Path(c['output_directory']);panel=Path(b['raw_selector']['path']);archive=Path(b['archive']['path']);assert stat(panel)==b['raw_selector']['stat'] and stat(archive)==b['archive']['stat']
 def fence(event,args):
  if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_DATA_BUILD_ONLY')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   p=Path(os.fsdecode(args[0])).resolve();d=Path(b['registry_helper_directory']);root=d.parent.parent;admin={root/'contracts/EXPERIMENT_REGISTRY.jsonl',root/'contracts/.EXPERIMENT_REGISTRY.jsonl.lock',root/'contracts/ACTIVE_RESEARCH_INDEX.json',root/'contracts/ACTIVE_RESEARCH_INDEX.today.tmp',root/'CURRENT_STATE.md',root/'HK_OHLCV_RESEARCH_STATE.md',root/'PROGRESS.md'};assert out.resolve() in p.parents or p in admin or p.parent==d/'registry','WRITE_BOUNDARY'
 sys.addaudithook(fence);sys.modules['pytdx']=None;sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 from event_aware_candidate_input import normalized_events,validate,project
 import pyarrow as pa,pyarrow.dataset as ds,pyarrow.parquet as pq
 sys.path.insert(0,b['registry_helper_directory']);from mac_registry import register
 target=load(b['target_list'])['targets'];assert len(target)==5533;current={r['ts_code']:r for r in csvrows(b['universe']) if r['trade_date']=='20261022'};assert len(current)==5494
 native_refs=load(b['native_refs']);event_refs=load(b['event_refs']);matrix=csvrows(b['matrix']);identity={r['ts_code']:r for r in csvrows(b['identity_projection'])};names={r['ts_code']:r['name'] for r in csvrows(b['universe'])}
 for code,row in identity.items():
  if not names.get(code):names[code]=row.get('resolution_observed_name') or row.get('source_short_name') or row.get('input_name') or ''
 for row in csvrows(b['current_positive_names']):
  if int(row['evidence_count'] or 0)>0:
   evidence=json.loads(row['evidence_json']);observed={e['source_company_name'] for e in evidence if e.get('source_company_name')}
   if len(observed)==1:names[row['source_key']]=next(iter(observed))
 bound_status={r['code']:r for r in load(b['bound_status48'])['rows']}
 statuses=[];patch_counts=Counter();zero_by_date=Counter();native_conflict_by_date=Counter();native_rebuilds=[];catalog={};new_data_count=0;unknown_types=set(r['instrument_type'] for r in matrix)-set(c['instrument_type_partition']);assert not unknown_types,'UNHANDLED_IDENTITY_TYPE_ENUM:'+str(unknown_types)
 dataset=ds.dataset(str(panel),format='parquet');date_integer=pa.types.is_integer(dataset.schema.field('trade_date').type);hi=20261022 if date_integer else '20261022';ledger_path=out/'SOURCE_REPAIR_LEDGER.jsonl.gz';out.joinpath('inputs').mkdir();out.joinpath('native_candidates').mkdir()
 with gzip.open(ledger_path,'xt',encoding='utf-8') as ledger,zipfile.ZipFile(archive) as z:
  members={}
  for info in z.infolist():
   norm=info.filename.replace('\\','/').lower();assert norm not in members;members[norm]=info
  for start in range(0,len(target),c['chunk_size']):
   chunk=target[start:start+c['chunk_size']];codes=[r['code'] for r in chunk];frames={code:[] for code in codes}
   for batch in dataset.scanner(columns=['ts_code','trade_date',*FIELDS],filter=ds.field('ts_code').isin(codes)&(ds.field('trade_date')<=hi),batch_size=65536,use_threads=False).to_batches():
    for r in batch.to_pylist():
     r['trade_date']=date8(r['trade_date']);frames[r['ts_code']].append({**r,**{f:float(r[f]) if r[f] is not None else float('nan') for f in FIELDS}})
   for target_row in chunk:
    code=target_row['code'];num,ex=code.split('.');timestamp=datetime.now(timezone.utc).isoformat();record={'code':code,'name':names.get(code,''),'status':'CANNOT_CONFIRM','first_date':None,'last_date':None,'rows':0,'patch_count':0,'new_D22_research_input':code not in current,'observed_listing_date':identity.get(code,{}).get('resolution_listing_date'),'issuer_name_limitation':identity.get(code,{}).get('resolution_issuer_name_limit')};ref=event_refs[code];assert sha(ref['path'])==ref['sha256'],'EVENT_SOURCE_DRIFT';capture=load(ref['path']);assert capture['response_error'] is None and isinstance(capture['response_rows'],list)
    try:ev,unsupported=normalized_events(capture['response_rows'])
    except (ValueError,AssertionError,TypeError,KeyError) as error:record.update(reason='EVENT_SOURCE_UNEVALUABLE:'+type(error).__name__+':'+str(error));statuses.append(record);continue
    record.update(event_response_path=ref['path'],event_response_sha256=ref['sha256'],event_semantics_sha256=digest([{'date':e['date'],'A':e['A'],'B':e['B'],'share_multiplier':e['share_multiplier']} for e in ev]),event_count_le_D22=len(ev))
    oldrows=sorted(frames[code],key=lambda r:r['trade_date']);old_keys={r['trade_date'] for r in oldrows};assert len(old_keys)==len(oldrows),'DUPLICATE_BOUND_RAW_KEY'
    reuse=b.get('reuse_verified_inputs',{}).get(code)
    if reuse and record['event_semantics_sha256']==reuse['event_semantics_sha256']:
     assert sha(reuse['path'])==reuse['sha256'];record.update(status='READY',path=reuse['path'],format='csv',sha256=reuse['sha256'],row_sha256=reuse['row_sha256'],rows=reuse['rows'],first_date=reuse['first_date'],last_date=reuse['last_date'],price_basis=c['price_basis'],volume_basis=c['volume_basis'],raw_source='REUSED_INDEPENDENT57_FULL_PREFIX_CSV_IDENTICAL_NUMERICAL_EVENT_INPUT',original_prefix_all_keys_preserved=True,review57_receipt_sha256=b['review57_receipt_sha256']);statuses.append(record);catalog[code]=record;new_data_count+=int(code not in current);continue
    def log_patch(d,before,after,reason,source_sha,offset=None,raw32_sha=None):
     changes={f:{'before':clean(before.get(f)) if before else None,'after':clean(after.get(f))} for f in FIELDS if before is None or before.get(f)!=after.get(f)}
     if not changes:return
     ledger.write(json.dumps({'code':code,'date':d,'rule_id':reason,'applied_at':timestamp,'before_row_sha256':digest(before) if before is not None else None,'after_row_sha256':digest(after),'source_file_sha256':source_sha,'source_byte_offset':offset,'source_raw32_sha256':raw32_sha,'changes':changes},ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n');record['patch_count']+=1
     for field in changes:patch_counts[field]+=1
    if code in current:
     nr=native_refs[code];path=Path(nr['path']);assert sha(path)==nr['sha256'],'ACCEPTED_SNAPSHOT_SOURCE_DRIFT';payload=path.read_bytes();assert len(payload)%32==0;bars=owner.read_hq_day_bars(path,tail_records=None);assert len(bars)==len(payload)//32
     invalid=[{'date':owner.day_int(row),'reason':owner.valid_hq_bar(row)[1]} for row in bars if not owner.valid_hq_bar(row)[0]]
     if invalid:record.update(reason='ACCEPTED_NATIVE_INVALID_RAW_FIELD',field_failures=invalid);statuses.append(record);continue
     nv=validate(bars,owner,ev,unsupported);sigs=owner._local_field_signature_violations(path,symbol=num,market=target_row['market'],run_id=c['execution_id'],recorded_at=None)
     if not nv['accepted_research_candidate'] or sigs:record.update(reason='ACCEPTED_NATIVE_REVALIDATION_FAILED',native_validation=nv,signature_count=len(sigs));statuses.append(record);continue
     mapped={r['trade_date']:dict(r) for r in oldrows}
     for i,row in enumerate(bars):
      raw32=payload[i*32:(i+1)*32];v=struct.unpack('<IIIIIfII',raw32);d=str(v[0]);assert v[6]==int(round(row['vol']*100));after={'ts_code':code,'trade_date':d,**{f:float(row[f]) for f in FIELDS[:4]},'volume':int(v[6])};before=mapped.get(d)
      if before is not None:
       if before['volume']==0 and v[6]>0:zero_by_date[d]+=1
       if any(before[f]!=after[f] for f in FIELDS[:4]):native_conflict_by_date[d]+=1
      log_patch(d,before,after,'ACCEPTED_D22_OWNER_SNAPSHOT_NATIVE_WINS_DERIVED_PROJECTION_V1',nr['sha256'],i*32,hashlib.sha256(raw32).hexdigest());mapped[d]=after
     rawrows=[mapped[d] for d in sorted(mapped)];assert old_keys.issubset(mapped),'ORIGINAL_PREFIX_DATE_LOSS';record.update(raw_source='ORIGINAL_BOUND_RAW_PREFIX_PLUS_ACCEPTED_D22_OWNER_SNAPSHOT_PATCHES',native_source_path=nr['path'],native_source_sha256=nr['sha256'],original_prefix_rows=len(oldrows),original_prefix_all_keys_preserved=True)
    else:
     expected=ex.lower()+'/lday/'+ex.lower()+num+'.day';info=members.get(expected)
     if info is None or info.file_size%32:record['reason']='EXACT_ARCHIVE_MEMBER_MISSING_OR_SHAPE';statuses.append(record);continue
     dest=out/'native_candidates'/code;dest.mkdir();full=dest/'archive_le_D22.day';h=hashlib.sha256();last=None
     with z.open(info) as f,full.open('xb') as g:
      while True:
       raw32=f.read(32)
       if not raw32:break
       assert len(raw32)==32;h.update(raw32);d=struct.unpack('<I',raw32[:4])[0];datetime.strptime(str(d),'%Y%m%d');assert last is None or d>last;last=d
       if d<=20261022:g.write(raw32)
     fullbytes=full.read_bytes();bars=owner.read_hq_day_bars(full,tail_records=None);assert len(bars)==len(fullbytes)//32
     invalid=[{'date':owner.day_int(row),'reason':owner.valid_hq_bar(row)[1]} for row in bars if not owner.valid_hq_bar(row)[0]]
     if invalid:record.update(reason='ARCHIVE_INVALID_RAW_FIELD',field_failures=invalid);statuses.append(record);continue
     av=validate(bars,owner,ev,unsupported);sig=owner._local_field_signature_violations(full,symbol=num,market=target_row['market'],run_id=c['execution_id'],recorded_at=None)
     if not av['accepted_research_candidate'] or sig:record.update(reason='ARCHIVE_FULL_HISTORY_VALIDATION_FAILED',validation=av,signature_count=len(sig));statuses.append(record);continue
     rawrows=[]
     for i,row in enumerate(bars):
      v=struct.unpack('<IIIIIfII',fullbytes[i*32:(i+1)*32]);rawrows.append({'ts_code':code,'trade_date':str(v[0]),**{f:float(row[f]) for f in FIELDS[:4]},'volume':int(v[6])})
     if not old_keys.issubset({r['trade_date'] for r in rawrows}):record.update(reason='OLD_SELECTOR_KEYS_ABSENT_FROM_VALIDATED_ARCHIVE',missing_dates=sorted(old_keys-{r['trade_date'] for r in rawrows}));statuses.append(record);continue
     # Preserve old native bytes and use the existing builder wherever its source preconditions hold.
     nr=native_refs.get(code)
     if nr and Path(nr['path']).exists():
      source=Path(nr['path']);assert sha(source)==nr['sha256'],'OLD_NATIVE_SOURCE_DRIFT';before_bytes=source.read_bytes();backup=dest/'ORIGINAL_NATIVE_BACKUP.day';backup.write_bytes(before_bytes);prior=owner.read_hq_day_bars(source,tail_records=None);first=owner.day_int(prior[0]) if prior else 19900101;replacements=[r for r in bars if owner.day_int(r)>=first];dates=[owner.day_int(r) for r in replacements];expected_rows={d:hashlib.sha256(owner.pack_hq_bar(r)).hexdigest() for d,r in zip(dates,replacements)};save(dest/'FROZEN_REPLACEMENT_PLAN.json',{'source_sha256':nr['sha256'],'archive_member_sha256':h.hexdigest(),'replacement_dates':dates,'replacement_encoded_sha256':expected_rows,'original_source_kept':True});candidate=dest/'candidate_unique.day';assert not candidate.exists()
      try:br=owner.build_rebuild_candidate(source,replacements,candidate,expected_source_sha256=nr['sha256'],expected_replacement_sha256=expected_rows,expected_replacement_dates=dates);cv=validate(owner.read_hq_day_bars(candidate,tail_records=None),owner,ev,unsupported);record['native_side_candidate_ready']=cv['accepted_research_candidate'];save(dest/'OWNER_BUILDER_RECEIPT.json',br)
      except Exception as error:record['native_side_candidate_ready']=False;record['native_side_candidate_failure']=type(error).__name__+':'+str(error);record['native_failure_does_not_modify_or_promote_source']=True
      assert sha(source)==nr['sha256'];native_rebuilds.append({'code':code,'native_side_candidate_ready':record['native_side_candidate_ready']})
     before_by_date={r['trade_date']:r for r in oldrows}
     for i,r in enumerate(rawrows):log_patch(r['trade_date'],before_by_date.get(r['trade_date']),r,'EXACT_OFFICIAL_TDX_ARCHIVE_FULL_PREFIX_RESEARCH_RECOVERY_V1',h.hexdigest(),i*32,hashlib.sha256(fullbytes[i*32:(i+1)*32]).hexdigest())
     record.update(raw_source='VALIDATED_ORIGINAL_TDX_ARCHIVE_FULL_PREFIX_RESEARCH_CANDIDATE',archive_member=info.filename,archive_member_sha256=h.hexdigest(),raw_full_history_path=str(full),raw_full_history_sha256=sha(full),original_prefix_rows=len(oldrows),original_prefix_all_keys_preserved=True)
    validation=consumer_check(rawrows,ev,unsupported,owner.MAX_CROSS_DAY_CLOSE_RATIO);record['consumer_validation']=validation
    if not validation['ready']:record['reason']='CONSUMER_HLCV_DATE_OR_EVENT_CONTINUITY_UNAVAILABLE';statuses.append(record);continue
    adjusted=project(rawrows,ev);assert len(adjusted)==len(rawrows);p=out/'inputs'/(code+'.parquet');assert not p.exists();pq.write_table(pa.Table.from_pylist(clean(adjusted)),p,compression='zstd');record.update(status='READY' if not any(validation['missing_fields'].values()) else 'READY_WITH_ROUTE_LEVEL_MISSING_FIELDS',path=str(p),format='parquet',sha256=sha(p),row_sha256=digest(adjusted),raw_row_sha256=digest(rawrows),rows=len(adjusted),first_date=adjusted[0]['trade_date'],last_date=adjusted[-1]['trade_date'],price_basis=c['price_basis'],volume_basis=c['volume_basis']);statuses.append(record);catalog[code]=record
    if code not in current:new_data_count+=1
   assert stat(panel)==b['raw_selector']['stat'] and stat(archive)==b['archive']['stat']
   progress=out/('CHECKPOINT_'+str(start+len(chunk)).zfill(6)+'.json');save(progress,{'processed':len(statuses),'ready':len(catalog),'new_D22_research_inputs':new_data_count,'status_by_code':[{k:r[k] for k in ['code','status']} for r in statuses[-len(chunk):]]});s=register(cp,'CHECKPOINT','INPUT60_'+str(start+len(chunk)).zfill(6),[progress],{'processed':len(statuses),'ready':len(catalog),'new_D22_research_inputs':new_data_count},'CANONICAL_RESEARCH_INPUT_BUILD_CHECKPOINT');save(out/('REGISTRY_'+str(start+len(chunk)).zfill(6)+'.json'),s);print(json.dumps({'processed':len(statuses),'ready':len(catalog),'new_D22_research_inputs':new_data_count},ensure_ascii=False),flush=True)
 status_by_code={r['code']:r for r in statuses};assert len(status_by_code)==5533;lineage=[]
 for r in matrix:
  key=r['source_key'];kind=c['instrument_type_partition'][r['instrument_type']];canonical=None
  if kind=='NON_EQUITY':disposition='NO_UPDATE_NON_EQUITY'
  elif kind=='UNKNOWN':disposition='IDENTITY_CANNOT_CONFIRM'
  elif bound_status.get(key,{}).get('D22_status')=='DELISTED_BEFORE_D22':disposition='NO_D22_BAR_OFFICIAL_DELISTING_EVENT'
  elif r['current_resolution_state'].startswith('NO_D22_BAR_'):disposition=r['current_resolution_state']
  else:
   canonical=key
   if r['observed_official_old_code']==key.split('.')[0] and r['observed_official_new_code']:canonical=r['observed_official_new_code']+'.BJ'
   if canonical in catalog:disposition='D22_RESEARCH_INPUT_AVAILABLE_ALIAS_REUSED' if canonical!=key else 'D22_RESEARCH_INPUT_RECOVERED'
   else:disposition='D22_INPUT_CANNOT_CONFIRM_NO_BAR_FABRICATED'
  conflict=identity[key].get('resolution_name_conflict_json');conflict=json.loads(conflict) if conflict else None
  lineage.append({'source_key':key,'canonical_code':canonical,'instrument_type':r['instrument_type'],'disposition':disposition,'input_status':status_by_code.get(canonical,{}).get('status'),'reason':status_by_code.get(canonical,{}).get('reason',r['resolution_reason']),'bound_official_D22_status':bound_status.get(key,{}).get('D22_status'),'alias_evidence_mode':'CURRENT_EXACT_OFFICIAL_PAIR_POLICY_CHAIN_INFERENCE_NOT_HISTORICAL_PIT' if canonical and canonical!=key else None,'historical_available_asof_D22':None,'name_conflict':bool(conflict),'old_source_records_preserved':True})
 save(out/'ORIGINAL318_DISPOSITION.json',lineage)
 with (out/'ORIGINAL318_DISPOSITION.csv').open('x',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(lineage[0]));w.writeheader();w.writerows(lineage)
 manifest={'schema':'CANONICAL_D22_RESEARCH_INPUT_MANIFEST_V1','execution_id':c['execution_id'],'verified_start':gate,'original_research_source_keys':5812,'original_daily_owner_targets':5800,'original_current_codes':5494,'prospective_canonical_source_eligible_codes':5533,'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':len(statuses)-len(catalog),'new_D22_research_input_codes':new_data_count,'original318_rows':318,'original318_dispositions':dict(Counter(r['disposition'] for r in lineage)),'catalog':catalog,'all_input_statuses':statuses,'source_repair_counts_by_field':dict(patch_counts),'selector_zero_native_positive_by_date':dict(zero_by_date),'native_price_projection_conflicts_by_date':dict(native_conflict_by_date),'native_side_candidate_results':native_rebuilds,'repair_ledger_path':str(ledger_path),'repair_ledger_sha256':sha(ledger_path),'price_basis':c['price_basis'],'volume_basis':c['volume_basis'],'fresh_event_target_count':5533,'event_retrieval_vintage':'20261023','feature_cutoff':'20261022','PIT_and_live_platform_parity':'NOT_CERTIFIED','original_source_or_pointer_writes':0,'live_native_files_repaired':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};save(out/'INPUT_MANIFEST.json',manifest);print(json.dumps({k:manifest[k] for k in ['ready_canonical_codes','unavailable_canonical_codes','new_D22_research_input_codes','original318_dispositions']},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
