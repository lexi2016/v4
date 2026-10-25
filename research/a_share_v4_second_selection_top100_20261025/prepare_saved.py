"""Arrange immutable saved trios for the existing V4 verifier; retain input identities."""
from audit import *
import sys
RUNTIME=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-share-history-consumer-20261025-r1/app')
DATA=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data')
def canonical(j):return hashlib.sha256(json.dumps(j,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def prepare():
 snap=OUT/'snapshots';saved=snap/'saved';verified=snap/'verified_store';verified.mkdir(exist_ok=True);shutil.copy2(saved/'selection_latest.json',verified/'selection_latest.json');entries=json.loads((snap/'SAVED_ENTRIES.json').read_text());source=[];bindings={}
 for key,e in entries.items():
  d,s,_=key.split('/');src=saved/d/s;dest=(verified/e['artifact_relative']).parent;dest.mkdir(parents=True,exist_ok=True)
  for n in ['artifact.csv','manifest.json','receipt.json']:shutil.copy2(src/n,dest/n)
  env=json.loads((src/'manifest.json').read_text())['selection_envelope'];ev=env.get('source_evidence',[]);pairs={x.split('=',1)[0]:x.split('=',1)[1] for x in ev if '=' in x};run=pairs.get('candidate_run_id');info=dict(candidate_run_id=run,candidate_current_sha256=pairs.get('candidate_current_sha256'),qualification='CANNOT_CONFIRM_STAGE_INPUT')
  rr=STORE.parent/'receipts'/d/s/'receipt.json'
  if rr.exists():
   p=snap/'runner_receipts'/d/s/'receipt.json';p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(rr,p);r=json.loads(p.read_text());info.update(runner_receipt_path=str(p),runner_receipt_sha256=sha(p),dispatch_mode=r.get('dispatch_mode'),recorded_at=r.get('recorded_at'),record_time_source=r.get('record_time_source'))
  if run and re.fullmatch(r'[A-Za-z0-9_.-]+',run):
   dr=DATA/'runs'/d/'A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3'/run
   if dr.is_dir():
    dst=snap/'candidate_inputs'/d/run;dst.mkdir(parents=True,exist_ok=True)
    for n in ['artifact.json','manifest.json','receipt.json','commit.json']:
     if (dr/n).exists() and not (dst/n).exists():shutil.copy2(dr/n,dst/n)
    try:
     a=json.loads((dst/'artifact.json').read_text());m=json.loads((dst/'manifest.json').read_text());r=json.loads((dst/'receipt.json').read_text());co=json.loads((dst/'commit.json').read_text());rawmode=m.get('digest_mode')=='RAW_BYTES_V1';dig=lambda p:sha(p) if rawmode else canonical(json.loads(p.read_text()))
     checks=[m.get('trade_date')==d,m.get('run_id')==run,m.get('row_count')==len(a['codes']),len(set(a['codes']))==len(a['codes']),a.get('source_pool_provenance_sha256')==pairs.get('candidate_source_pool_provenance_sha256'),canonical(a.get('source_pool_provenance'))==a.get('source_pool_provenance_sha256'),m.get('artifact_bytes_sha256',m.get('artifact_sha256'))==dig(dst/'artifact.json'),r.get('manifest_bytes_sha256',r.get('manifest_sha256'))==dig(dst/'manifest.json'),co.get('receipt_bytes_sha256',co.get('receipt_sha256'))==dig(dst/'receipt.json')]
     if all(checks):info.update(qualification='SAVED_STAGE_BOUND_FULL_CANDIDATE_CODES_PROVENANCE_PARITY',codes=[norm(x) for x in a['codes']],candidate_artifact_path=str(dst/'artifact.json'),candidate_artifact_sha256=sha(dst/'artifact.json'),candidate_pool_count=len(a['codes']))
     else:info.update(candidate_checks=checks)
    except Exception as ex:info.update(candidate_error=type(ex).__name__+':'+str(ex))
  bindings[key]=info
 save(snap/'STAGE_INPUT_BINDINGS.json',bindings)
 save(snap/'SAVED_VERIFIER_BINDING.json',dict(runtime_root=str(RUNTIME),refs={str(p):sha(p) for p in [RUNTIME/'stage_center/selection.py',RUNTIME/'stage_center/consumer.py',RUNTIME/'apps/api/v35_api/app.py']},GET_callpath='stage_workbench->shared_selection_consumer.get->SelectionStore.read_verified/read_stage_execution; write_performed=false',historical_error_note='PYTDX_0925_REPLAY_ERROR is stored Oct23 attempt, not current Oct25 network activity',snapshot_store=str(verified)))
 print(json.dumps({'prepared_cells':len(entries),'bound_initial_pool_cells':sum('codes'in v for v in bindings.values())}))
if __name__=='__main__':prepare()
