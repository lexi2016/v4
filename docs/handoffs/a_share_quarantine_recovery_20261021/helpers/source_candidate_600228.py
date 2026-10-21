"""One-stock native-byte staging with original-owner validation; no authority/pointer writes."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import datetime as dt,fcntl,hashlib,importlib.util,json,os,struct,time
ROOT=Path(__file__).resolve().parents[1];WT=Path('/Users/lexi/Desktop/学习/因子工厂/worktrees/a_share_quarantine_recovery_20261021');EXECUTION='A_SHARE_QUARANTINE_SOURCE_CANDIDATE_600228_20261021_01'
OWNER=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260910-d1-partial-provenance-v14/app/runtime/v1/data_layer_daily_formula_increment_update_v1.py')
FIELDS=['date','open','high','low','close','amount_bits','volume_raw','reserved']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,j):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def write(p,b):
 with Path(p).open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
def rows(p,digest):
 assert sha(p)==digest;raw=Path(p).read_bytes();assert len(raw)%32==0;out={};previous=None
 for off in range(0,len(raw),32):
  b=raw[off:off+32];v=struct.unpack('<8I',b);d=v[0];dt.datetime.strptime(str(d),'%Y%m%d');assert d not in out and (previous is None or previous<d);out[d]={'raw':b,'values':v,'row_index':off//32,'sha256':hashlib.sha256(b).hexdigest()};previous=d
 return out
def main():
 started=time.monotonic();gate=(ROOT/'registry_receipts/SOURCE_CANDIDATE_600228_REGISTRY_START.json').read_text();assert EXECUTION in gate and 'RUN_STARTED' in gate
 lock=(ROOT/'SOURCE_CANDIDATE_600228.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 c=json.loads((ROOT/'SOURCE_CANDIDATE_600228_CONTRACT.json').read_text())
 for x in c['input_bindings']:assert sha(x['path'])==x['sha256'],'Frozen input/source drift'
 closure=json.loads((ROOT/'SOURCE_IMPORT_CLOSURE.json').read_text())
 for x in closure['files']:assert sha(WT/x['relative_path'])==x['sha256'],'WT source drift'
 originals=json.loads((ROOT/'CLASS_CANARY_INPUT_MANIFEST.json').read_text());old=next(x for x in originals['samples'] if x['canonical_code']=='600228.SH')
 arc=json.loads((ROOT/'ARCHIVE_SAMPLE_600228.SH.json').read_text());wm=json.loads((ROOT/'PARITY_CODEC_INPUT_MANIFEST.json').read_text());win=next(x for x in wm['windows_existing_snapshots'] if x['canonical_code']=='600228.SH')
 orig=rows(old['native_snapshot_path'],old['native_actual_sha256']);archive=rows(arc['selected_member_path'],arc['selected_member_sha256']);windows=rows(win['path'],win['sha256']);first=min(orig);last=20261021
 canonical={d:{**r,'source':'ARCHIVE_NATIVE','file_sha256':arc['selected_member_sha256']} for d,r in archive.items() if first<=d<=20261019}
 for d in [20261020,20261021]:assert d in windows;canonical[d]={**windows[d],'source':'WINDOWS_EXISTING_NATIVE_TAIL','file_sha256':win['sha256']}
 assert min(canonical)==first and max(canonical)==last
 stage=ROOT/'source_candidate_600228'/EXECUTION;stage.mkdir(mode=0o700,parents=True,exist_ok=False)
 write(stage/'original_native_backup.day',Path(old['native_snapshot_path']).read_bytes())
 ledger=[];quarantined=[]
 for d in sorted(set(orig)|set(canonical)):
  a=orig.get(d);b=canonical.get(d)
  disposition='INSERTED' if a is None else 'QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE' if b is None else 'RETAINED_BYTE_IDENTICAL' if a['raw']==b['raw'] else 'REPLACED_WITH_VERIFIED_NATIVE'
  item={'date':d,'disposition':disposition,'original_row_index':a['row_index'] if a else None,'original_row_sha256':a['sha256'] if a else None,'original_raw_words':list(a['values']) if a else None,'candidate_row_sha256':b['sha256'] if b else None,'candidate_raw_words':list(b['values']) if b else None,'source':b['source'] if b else None,'source_file_sha256':b['file_sha256'] if b else None,'source_row_index':b['row_index'] if b else None,'field_changes':[FIELDS[i] for i in range(8) if a['values'][i]!=b['values'][i]] if a and b else None}
  if b is None:
   item.update({'reason':'Originaldate absent from both authenticatedarchive-native and existingWindows-native canonical sequences','semantic_classification':'CANNOT_CONFIRM_HALT_OR_OTHER_ORIGIN; not calledbad and not normalized','original_32bytes_hex':a['raw'].hex()});quarantined.append(a['raw'])
  ledger.append(item)
 save(stage/'ROW_DISPOSITION.json',{'canonical_code':'600228.SH','original_first_date':first,'target_date':last,'policy':'Controllerexplicitdecision: verifiednative canonical sequence in originalsource datebounds; all Mac-only originalbytes preserved in rollback+quarantineledger; no reason guess','rows':ledger})
 write(stage/'quarantined_original_records.day',b''.join(quarantined));assembled=stage/'provenance_assembled_input.day';write(assembled,b''.join(canonical[d]['raw'] for d in sorted(canonical)));assembledsha=sha(assembled)
 save(stage/'ASSEMBLED_INPUT_BINDING.json',{'path':str(assembled),'sha256':assembledsha,'source_policy_contract_sha256':sha(ROOT/'SOURCE_CANDIDATE_600228_CONTRACT.json'),'row_ledger_sha256':sha(stage/'ROW_DISPOSITION.json')})
 sys.path.insert(0,str(WT));from ops import a_share_daily_sync as producer
 candidate=stage/'candidate_sh600228.day';assert not candidate.exists()
 build=producer.build_rebuild_candidate(assembled,[],candidate,expected_source_sha256=assembledsha,expected_replacement_sha256={},expected_replacement_dates=[])
 assert sha(candidate)==assembledsha,'Existingbuilder altered native32B bytes'
 bars,reason=producer._local_history_status(candidate,last)
 violations=producer._local_field_signature_violations(candidate,symbol='600228',market=1,run_id=EXECUTION,recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
 assert reason is None and not violations,'Original unchanged validator rejects staging'
 assert producer.read_last_date(candidate)==last
 counts={k:sum(x['disposition']==k for x in ledger) for k in ['INSERTED','QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE','RETAINED_BYTE_IDENTICAL','REPLACED_WITH_VERIFIED_NATIVE']}
 assert len(orig)==counts['QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE']+counts['RETAINED_BYTE_IDENTICAL']+counts['REPLACED_WITH_VERIFIED_NATIVE']
 assert len(canonical)==counts['INSERTED']+counts['RETAINED_BYTE_IDENTICAL']+counts['REPLACED_WITH_VERIFIED_NATIVE']
 assert sha(stage/'original_native_backup.day')==old['native_actual_sha256']
 # Actual configured owner input projection only, never its main/feature/side-effect entrypoint.
 spec=importlib.util.spec_from_file_location('bound_current_owner_input_projection',OWNER);owner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owner;spec.loader.exec_module(owner)
 projected=owner.read_day_tail('600228.SH',candidate,tail_records=owner.DAILY_FORMULA_LOOKBACK_RECORDS);assert int(projected['trade_date'].max())==last
 projection={'owner_path':str(OWNER),'owner_sha256':sha(OWNER),'function':'read_day_tail','lookback_records':owner.DAILY_FORMULA_LOOKBACK_RECORDS,'projected_rows':len(projected),'min_date':int(projected['trade_date'].min()),'max_date':int(projected['trade_date'].max()),'scope':'Originalowner rawinput mapping only; no formula compute or panel rebuild performed'};save(stage/'ORIGINAL_OWNER_INPUT_PROJECTION.json',projection)
 import pyarrow.dataset as ds
 binding=json.loads((ROOT/'INTAKE_MANIFEST.json').read_text());quarantine_dates={x['date'] for x in ledger if x['disposition']=='QUARANTINED_ORIGINAL_NOT_IN_CANONICAL_SOURCE'};panel_results={}
 for role,p in binding['panels'].items():
  s=Path(p['target_path']).stat();assert {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}==p['stat'],'Panel stat drift'
  table=ds.dataset(p['target_path'],format='parquet').to_table(columns=['ts_code','trade_date','open','high','low','close'],filter=ds.field('ts_code')=='600228.SH');existing={};differences=[]
  for row in table.to_pylist():
   d=int(str(row['trade_date']).replace('-',''));assert d not in existing;existing[d]=row
   if d in canonical:
    price_diffs={k:{'panel_value':row[k],'candidate_cents':canonical[d]['values'][i]} for i,k in enumerate(['open','high','low','close'],1) if round(float(row[k])*100)!=canonical[d]['values'][i]}
    if price_diffs:differences.append({'date':d,'price_fields':price_diffs})
  panel_results[role]={'current_single_stock_rows':len(existing),'current_max_date':max(existing),'retire_keys_if_native_policy_accepted':sorted(quarantine_dates&set(existing)),'OHLC_replace_requirements':differences,'missing_candidate_dates_from_current_panel':sorted(set(canonical)-set(existing)),'existing_older_dates_preserved':sorted(d for d in existing if d<first),'original_writer_capability':'write_appended_parquet replaces only supplied newkeys; cannot retire absentcanonical keys without explicit minimalowner extension','formula_or_panel_rebuild_performed':False}
  now=Path(p['target_path']).stat();assert (now.st_ino,now.st_mtime_ns,now.st_size)==(s.st_ino,s.st_mtime_ns,s.st_size)
 save(stage/'PANEL_KEY_REPAIR_REQUIREMENTS.json',panel_results)
 receipt={'execution_id':EXECUTION,'status':'SOURCE_CANDIDATE_CANARY_COMPLETE','stage_dir':str(stage),'candidate_path':str(candidate),'candidate_sha256':sha(candidate),'original_sha256':old['native_actual_sha256'],'row_disposition_counts':counts,'original_validator':{'cross_ratio_limit':producer.MAX_CROSS_DAY_CLOSE_RATIO,'history_reason':reason,'field_signature_count':len(violations),'target_date':producer.read_last_date(candidate)},'builder_receipt':build,'panel_repair_requirements_path':str(stage/'PANEL_KEY_REPAIR_REQUIREMENTS.json'),'artifacts':[{'path':str(p),'sha256':sha(p)} for p in sorted(stage.iterdir()) if p.is_file()],'elapsed_seconds':time.monotonic()-started,'network_calls':0,'canonical_source_writes':0,'panel_writes':0,'pointer_writes':0,'formula_calls':0,'independent_review':'PENDING','research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
 save(ROOT/'SOURCE_CANDIDATE_600228_RECEIPT.json',receipt);print(json.dumps({k:v for k,v in receipt.items() if k not in ['artifacts','builder_receipt']}))
if __name__=='__main__':main()
