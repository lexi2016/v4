"""Repair only INPUT60 rejected source prefixes; preserve accepted outputs and original bytes."""
import argparse,csv,gzip,hashlib,importlib.util,json,math,struct,sys,zipfile
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
sys.dont_write_bytecode=True
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(p,x):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size_bytes':s.st_size}
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=load(cp);b=c['input_identity'];out=Path(c['output_directory']);base=load(b['input60_manifest']);oldstatuses={r['code']:r for r in base['all_input_statuses']};currenttargets=[r for r in oldstatuses.values() if r['status']=='CANNOT_CONFIRM' and not r['new_D22_research_input']];assert len(currenttargets)==814
 def fence(event,args):
  if event.startswith(('socket.connect','socket.bind','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_EXISTING_SAME_SOURCE_ONLY')
 sys.addaudithook(fence);import pyarrow as pa,pyarrow.dataset as ds,pyarrow.parquet as pq
 from event_aware_candidate_input import normalized_events,project
 spec=importlib.util.spec_from_file_location('immutable_input60',b['input60_code']);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 sys.path.insert(0,b['registrar_directory']);from mac_registry import register
 panel=b['raw_selector'];archive=b['archive'];assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat'];native=load(b['native_index']);eventrefs=load(b['event_index']);boundmembers={r['code']:r for r in load(b['source62_memberbindings'])};listing={};roster=b['szse_roster'];assert sha(roster['capture_path'])==roster['capture_sha256']
 from xml.etree import ElementTree as ET
 ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 with zipfile.ZipFile(roster['capture_path']) as z:
  strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',ns)] if 'xl/sharedStrings.xml' in z.namelist() else [];header=None
  for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:sheetData/s:row',ns):
   vals={}
   for cell in row.findall('s:c',ns):
    v=cell.find('s:v',ns);text=v.text if v is not None else '';text=strings[int(text)] if cell.get('t')=='s' and text else ''.join(cell.find('s:is',ns).itertext()) if cell.get('t')=='inlineStr' and cell.find('s:is',ns) is not None else text;vals[''.join(x for x in cell.get('r','') if x.isalpha())]=text
   if header is None:header=vals;continue
   r={header.get(k,k):v for k,v in vals.items()};code=r.get('A股代码','').zfill(6)+'.SZ';date=r.get('A股上市日期','').replace('-','').replace('/','')
   if len(date)==8 and date.isdigit():listing[code]={'date':date,'source_row':row.get('r'),'code_field':'A股代码','date_field':'A股上市日期','source_path':roster['capture_path'],'source_sha256':roster['capture_sha256'],'historical_availability':None}
 dataset=ds.dataset(panel['path'],format='parquet');out.joinpath('inputs').mkdir();records=[];patches=0;datecounts=Counter();sourcepriceconflicts=[];exceptions=[];rawviews=out/'raw_views';rawviews.mkdir()
 with zipfile.ZipFile(archive['path']) as z,gzip.open(out/'PREFIX_PATCH_LEDGER.jsonl.gz','xt',encoding='utf-8') as ledger:
  members={i.filename.replace('\\','/').lower():i for i in z.infolist()}
  for offset in range(0,len(currenttargets),c['chunk_size']):
   chunk=currenttargets[offset:offset+c['chunk_size']];codes=[r['code'] for r in chunk];frames={code:[] for code in codes}
   for batch in dataset.scanner(columns=['ts_code','trade_date','open','high','low','close','volume'],filter=ds.field('ts_code').isin(codes)&(ds.field('trade_date')<='20261022'),batch_size=65536,use_threads=False).to_batches():
    for r in batch.to_pylist():frames[r['ts_code']].append(r)
   for old in chunk:
    code=old['code'];num,ex=code.split('.');rows=sorted(frames[code],key=lambda r:str(r['trade_date']));original={str(r['trade_date']):dict(r) for r in rows};assert len(original)==len(rows);ref=eventrefs[code];assert sha(ref['path'])==ref['sha256'];ev,unsupported=normalized_events(load(ref['path'])['response_rows']);info=members.get(ex.lower()+'/lday/'+ex.lower()+num+'.day');record={'code':code,'old_status':'CANNOT_CONFIRM','status':'CANNOT_CONFIRM','original_rows':len(rows),'original_date_keys_preserved':True,'price_basis':c['price_basis'],'volume_basis':c['volume_basis'],'source_rule':'ACCEPTED_OWNER_SNAPSHOT_WINS_MATCHED_DATES_OFFICIAL_ARCHIVE_REPAIRS_OLDER_ORIGINAL_DATES_ONLY_NO_HISTORY_TRUNCATION','applied_at':datetime.now(timezone.utc).isoformat()};arc={};all_dates=[];h=hashlib.sha256();archive_raw_records=[];invalid_archive=[]
    if info is None:record['reason']='EXACT_ARCHIVE_MEMBER_MISSING';records.append(record);continue
    with z.open(info) as f:
     while True:
      raw=f.read(32)
      if not raw:break
      assert len(raw)==32;h.update(raw);d=str(struct.unpack('<I',raw[:4])[0]);datetime.strptime(d,'%Y%m%d');assert not all_dates or d>all_dates[-1];all_dates.append(d)
      if d>'20261022':continue
      if d not in original:continue
      v=struct.unpack('<IIIIIfII',raw);archive_raw_records.append(raw);valid,why=owner.valid_hq_bar({'year':int(d[:4]),'month':int(d[4:6]),'day':int(d[6:]),'open':v[1]/100,'high':v[2]/100,'low':v[3]/100,'close':v[4]/100,'amount':v[5],'vol':v[6]/100});invalid_archive.extend([{'date':d,'reason':why}] if not valid else []);arc[d]={'ts_code':code,'trade_date':d,'open':v[1]/100,'high':v[2]/100,'low':v[3]/100,'close':v[4]/100,'volume':v[6],'raw32_sha256':hashlib.sha256(raw).hexdigest(),'offset':f.tell()-32}
    assert h.hexdigest()==boundmembers[code]['member_sha256'],'ARCHIVE_MEMBER62_DRIFT';source_prefix_path=rawviews/(code+'_SOURCE_NATIVE_RECORDS.day');source_prefix_path.write_bytes(b''.join(archive_raw_records));signatures=owner._local_field_signature_violations(source_prefix_path,symbol=num,market=1 if ex=='SH' else 0 if ex=='SZ' else 2,run_id=c['execution_id'],recorded_at=None);record.update(archive_raw_fields_invalid=invalid_archive,archive_native_signature_count=len(signatures),archive_prefix_native_path=str(source_prefix_path),archive_prefix_native_sha256=sha(source_prefix_path));
    if invalid_archive or signatures:record['reason']='ARCHIVE_PREFIX_OWNER_FIELD_OR_SIGNATURE_GUARD_REJECTED';records.append(record);continue
    nr=native[code];assert sha(nr['path'])==nr['sha256'];payload=Path(nr['path']).read_bytes();assert len(payload)%32==0;native_rows={}
    for i in range(0,len(payload),32):
     raw=payload[i:i+32];v=struct.unpack('<IIIIIfII',raw);d=str(v[0]);assert d<='20261022';native_rows[d]={'ts_code':code,'trade_date':d,'open':v[1]/100,'high':v[2]/100,'low':v[3]/100,'close':v[4]/100,'volume':v[6],'raw32_sha256':hashlib.sha256(raw).hexdigest(),'offset':i}
    overlap=set(arc)&set(native_rows);diff=[d for d in sorted(overlap) if any(arc[d][f]!=native_rows[d][f] for f in ['open','high','low','close'])];record.update(archive_member=info.filename,archive_member_sha256=h.hexdigest(),archive_first_date=all_dates[0],archive_source_last_date=all_dates[-1],native_sha256=nr['sha256'],native_path=nr['path'],native_archive_overlap=len(overlap),native_archive_OHLC_conflict_dates=diff,missing_original_dates_in_archive=sorted(set(original)-set(arc)))
    if diff:record['reason']='ACCEPTED_NATIVE_ARCHIVE_OHLC_CONFLICT_RETAIN_UNRESOLVED';sourcepriceconflicts.append({'code':code,'dates':diff});records.append(record);continue
    merged={d:dict(r) for d,r in original.items()};count=0
    for d in sorted(set(arc)|set(native_rows)):
     if d not in original and d not in native_rows:continue
     src=native_rows.get(d) or arc[d];after={k:src[k] for k in ['ts_code','trade_date','open','high','low','close','volume']};before=merged.get(d);changes={f:{'before':before[f] if before else None,'after':after[f]} for f in ['open','high','low','close','volume'] if before is None or before[f]!=after[f]}
     if changes:ledger.write(json.dumps({'code':code,'date':d,'rule_id':'SOURCE_BOUND_PREFIX_REPAIR_V1','changes':changes,'before_row_sha256':digest(before) if before else None,'after_row_sha256':digest(after),'source_sha256':nr['sha256'] if d in native_rows else h.hexdigest(),'source_raw32_sha256':src['raw32_sha256'],'source_byte_offset':src['offset'],'applied_at':record['applied_at']},ensure_ascii=False,separators=(',',':'))+'\n');count+=1;datecounts[d]+=1
     merged[d]=after
    rawrows=[merged[d] for d in sorted(merged)];assert set(original).issubset(merged);validation=mod.consumer_check(rawrows,ev,unsupported,owner.MAX_CROSS_DAY_CLOSE_RATIO);listing_ref=listing.get(code);ipo_dates=all_dates[:5] if listing_ref and listing_ref['date']==all_dates[0] and all_dates[0]>='20230217' else [];retained=[]
    for error in validation['errors']:
     if isinstance(error,dict) and error.get('reason')=='UNEXPLAINED_RAW_RATIO' and error['date'] in ipo_dates and error['previous_date'] in ipo_dates:
      exception={'code':code,'reason':'SZSE_OFFICIAL_IPO_FIRST_FIVE_TRADING_DAYS_NOT_PRICE_LIMITED','previous_date':error['previous_date'],'date':error['date'],'raw_ratio':error['raw_ratio'],'listing':listing_ref,'exact_archive_first_five_dates':ipo_dates,'legal_source':b['szse_ipo_rule'],'ratio_threshold_unchanged_other_dates':True};exceptions.append(exception)
     else:retained.append(error)
    record.update(patch_count=count,consumer_validation_original=validation,exact_IPO_rule_exceptions=[e for e in exceptions if e['code']==code],remaining_errors=retained);patches+=count
    if retained:record['reason']='SOURCE_REPAIRED_BUT_UNEXPLAINED_EVENT_OR_RATIO_REMAINS';records.append(record);continue
    rawpath=rawviews/(code+'.parquet');pq.write_table(pa.Table.from_pylist(rawrows),rawpath,compression='zstd');adjusted=project(rawrows,ev);path=out/'inputs'/(code+'.parquet');pq.write_table(pa.Table.from_pylist(adjusted),path,compression='zstd');record.update(status='READY',path=str(path),format='parquet',sha256=sha(path),row_sha256=digest(adjusted),rows=len(adjusted),first_date=adjusted[0]['trade_date'],last_date=adjusted[-1]['trade_date'],raw_path=str(rawpath),raw_sha256=sha(rawpath));records.append(record)
   progress=out/('CHECKPOINT_'+str(offset+len(chunk)).zfill(4)+'.json');save(progress,{'processed':len(records),'recovered':sum(r['status']=='READY' for r in records)});r=register(cp,'CHECKPOINT','PREFIX63_'+str(offset+len(chunk)).zfill(4),[progress],{'processed':len(records),'recovered':sum(r['status']=='READY' for r in records)},'RUNNING_BOUND_PREFIX_SOURCE_REPAIR');save(out/('REGISTRY_'+str(offset+len(chunk)).zfill(4)+'.json'),r);print(json.dumps({'processed':len(records),'recovered':sum(r['status']=='READY' for r in records)}),flush=True)
 newstatuses=[];delta={r['code']:r for r in records};catalog=dict(base['catalog'])
 for r in base['all_input_statuses']:
  n=delta.get(r['code']);v={**r,**n} if n and n['status']=='READY' else dict(r)
  if n and n['status']!='READY':v['prefix63_remaining_failure']=n
  if n and n['status']=='READY':catalog[r['code']]=v
  newstatuses.append(v)
 lineage=load(b['original318_disposition']);status_by_code={r['code']:r for r in newstatuses}
 for r in lineage:
  code=r['canonical_code']
  if code in catalog:r['input_status']=catalog[code]['status'];r['disposition']='D22_RESEARCH_INPUT_AVAILABLE_ALIAS_REUSED' if code!=r['source_key'] else 'D22_RESEARCH_INPUT_RECOVERED';r['reason']='SOURCE_BOUND_RESEARCH_INPUT_AVAILABLE_NO_LIVE_NATIVE_PROMOTION'
 save(out/'ORIGINAL318_DISPOSITION.json',lineage)
 manifest={**base,'execution_id':c['execution_id'],'verified_start':gate,'parent_input60_manifest_sha256':b['input60_manifest_sha256'],'catalog':catalog,'all_input_statuses':newstatuses,'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':5533-len(catalog),'prefix63_recovered_current_codes':sum(r['status']=='READY' for r in records),'prefix63_patches':patches,'prefix63_patch_rows_by_date':dict(datecounts),'prefix63_exact_IPO_exceptions':exceptions,'prefix63_source_conflicts':sourcepriceconflicts,'original318_dispositions':dict(Counter(r['disposition'] for r in lineage))};save(out/'INPUT_MANIFEST.json',manifest);save(out/'PREFIX_REPAIR_RECEIPT.json',{'execution_id':c['execution_id'],'codes':len(records),'recovered':sum(r['status']=='READY' for r in records),'unresolved':sum(r['status']!='READY' for r in records),'records':records,'patches':patches,'IPO_exceptions':exceptions,'native_writes':0,'network':0,'threshold_changed':False,'original_prefix_keys_lost':0,'parent_healthy4717_recomputed':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False});assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat'];print(json.dumps({'ready_canonical_codes':len(catalog),'unavailable_canonical_codes':5533-len(catalog),'prefix63_recovered':sum(r['status']=='READY' for r in records),'IPO_exception_count':len(exceptions)},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
