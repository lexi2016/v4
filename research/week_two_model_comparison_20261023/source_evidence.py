"""Close source-identity evidence using saved bindings and no formula or return replay."""
import json,sys
from pathlib import Path
from collections import Counter
import weekly_compare as w

def main():
 c=w.load(w.OUT/'EXECUTION_CONTRACT.json');p=c['input_identity']['raw_selector'];old=Path(p['binding_path']);oldb=w.load(old);q=oldb['selector'];s=Path(p['path']).stat();actual=dict(inode=s.st_ino,mtime_ns=s.st_mtime_ns,size_bytes=s.st_size)
 assert actual==p['stat']==q['target_stat'] and p['path']==q['target_path'] and p['sha256']==q['expected_sha256']
 bindings=w.load(w.OUT/'signals/RAW_INPUT_BINDINGS.json');assert len(bindings)==5531
 verified={};branches=Counter();rows=0;coverage=[]
 for b in bindings:
  sources=b['sources'];branches['+'.join(r['role'] for r in sources)]+=1;rows+=b['rows']
  for r in sources:
   if 'path' not in r:continue
   path=r['path'];expected=r['sha256']
   if path in verified:assert verified[path]==expected;continue
   assert w.sha(path)==expected,'SOURCE_CHANGED_AFTER_SIGNAL:'+path;verified[path]=expected
  coverage.append(dict(code=b['code'],rows=b['rows'],first_date=b['first_date'],last_date=b['last_date'],source_branch='+'.join(r['role'] for r in sources),raw_sixfield_sha256=b['raw_sixfield_sha256'],source_binding_sha256=w.digest(b),window_key_scope='All retained original source keys; full64 OHLCV projection parity; no historical-all-A certification'))
 owner=w.load(w.R/'canonical_research_input_60/CONTRACT.json');decoder=Path(owner['input_identity']['owner_worktree'])/'ops/_a_share_daily_sync_parts/day_file_format.py';decoder_sha=w.sha(decoder)
 receipt=dict(selector_fast_bind=dict(path=p['path'],expected_sha256=p['sha256'],full_sha_origin_binding=str(old),full_sha_origin_binding_sha256=w.sha(old),origin_price_basis=oldb['price_basis'],origin_amount_unit=oldb['amount_unit'],original_binding_stat=q['target_stat'],post_signal_stat=actual,stat_unchanged=True,rehashed=False,policy='Reuse prior full fileSHA only with exact inode/size/mtime unchanged; not global historical certification'),native_decoder=dict(path=str(decoder),sha256=decoder_sha,existing_contract_declared_sha256=owner['frozen_source_bindings'].get(str(decoder)),semantics='DAY_STRUCT <IIIIIfII; raw OHLC integer/100; amount_f copied directly, no scaling or adjustment; native volume_u is retained native count domain here',source_lines='day_file_format.py:85-89'),actual_checks=dict(codes=5531,rows=rows,complete_raw_OHLCV_parity_against64=True,all_six_fields_finite=True,raw_prices_positive=True,raw_OHLC_geometry_valid=True,volume_and_amount_nonnegative=True,full_prefix_preserved=True,source_branches=dict(branches),unique_source_files_rehashed_after_signal=len(verified),source_file_bytes_unchanged_vs_bound_before_read=True,formula_replays=0,outcome_reads=0),validation_limitations=['OPEN/AMOUNT exact source record precedence and field validity checked; no global cross-vendor parity or full original-amount value audit was performed','Original selector whole six-field prefix uses its existing RAW_UNADJUSTED producer binding. Current native snapshots overwrite all six fields by exact date; 63 captured archive records overwrite original repaired-prefix records before native overlay','67 is reused only for its existing OHLCV/input scope; new O/AMOUNT fields are separately source-bound and validity-checked, not certified by 67','RAW source identity and current file immutability do not prove publication/revision/available_at historical PIT or historical security eligibility'],**w.FLAGS)
 if receipt['native_decoder']['existing_contract_declared_sha256']:assert decoder_sha==receipt['native_decoder']['existing_contract_declared_sha256']
 w.csvwrite(w.OUT/'SOURCE_BRANCH_COVERAGE.csv',coverage);w.save(w.OUT/'SOURCE_IDENTITY_SUPPLEMENT.json',receipt)
 w.register(w.OUT/'EXECUTION_CONTRACT.json','CHECKPOINT','WEEK_SOURCE_IDENTITY_CLOSED',[w.OUT/'SOURCE_IDENTITY_SUPPLEMENT.json',w.OUT/'SOURCE_BRANCH_COVERAGE.csv',Path(__file__).resolve()],dict(source_codes=5531,formula_replays=0,outcome_reads=0),decision='SOURCE_IDENTITY_AND_SIX_FIELD_SCOPE_DOCUMENTED_NOT_GLOBAL_PIT_CERTIFICATION')
 print(json.dumps(receipt['actual_checks']))
if __name__=='__main__':main()
