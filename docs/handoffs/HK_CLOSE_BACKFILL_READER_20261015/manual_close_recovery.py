"""Operator plan by default; apply/rollback only after independent PASS.

No scheduling, provider, selection, service or dispatcher mutation. Writes on
apply are only the existing close publisher plus its existing lock lifecycle.
"""
from pathlib import Path
import sys,argparse,json,hashlib,plistlib,datetime,os,stat,tempfile
O=Path(__file__).parent;DATE='20261015'
D=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
P=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')
DISPATCH=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/receipts/live/20261015/1610/06e39b51fda142449ad1cf9a8c1af480.dispatch-receipt.json')
SELECTION=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection')
OLD='54688edbcd5edb6f2f5f559e1dccb6a31acd872a555968b586dd671c331b341d'
DISPATCH_SHA='0e5031eaf9c82b21f00b9b47ee51e372ca8a31e25837fa7d63c939e6571d0a3e'
FROZEN_MANIFEST_SHA='50166a5fc50bf37c7de385c489f773dca94218d3291891f8240eab51aade7875'
FROZEN_INVENTORY_FILE_SHA='2def7bbf658fcae7b7e8c9d580c93bc6caae3fe23e0b94c1d20203c854009e69'
sha=lambda b:hashlib.sha256(b).hexdigest()
def dump(p,d):
 # A committed operation record must survive a later assertion or process exit.
 raw=(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 fd,temp=tempfile.mkstemp(prefix='.'+p.name+'.',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(temp,p)
  parent=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(parent)
  finally:os.close(parent)
 finally:
  if os.path.exists(temp):os.unlink(temp)
def verify_frozen_runtime(app,seal):
 # Compare actual bytes and modes, not another mutable prepared app. The full
 # inventory includes every runtime dependency and refuses extra/missing files.
 if seal['manifest']['sha256']!=FROZEN_MANIFEST_SHA:raise ValueError('frozen manifest identity mismatch')
 if sha((app.parent/'release-manifest.json').read_bytes())!=FROZEN_MANIFEST_SHA:raise ValueError('active manifest drift')
 raw=(O/'candidate-complete-inventory.json').read_bytes()
 if sha(raw)!=FROZEN_INVENTORY_FILE_SHA:raise ValueError('frozen inventory identity mismatch')
 frozen=json.loads(raw);actual=[]
 for directory,directories,files in os.walk(app,followlinks=False):
  for name in sorted(directories+files):
   p=Path(directory)/name;info=p.lstat();e=dict(path=p.relative_to(app).as_posix(),mode=f'{stat.S_IMODE(info.st_mode):04o}')
   if p.is_symlink():
    target=os.readlink(p);e.update(kind='symlink',target=target,size=len(os.fsencode(target)),sha256=sha(os.fsencode(target)))
   elif p.is_file():
    b=p.read_bytes();e.update(kind='file',size=len(b),sha256=sha(b))
   elif p.is_dir():e.update(kind='directory')
   else:raise ValueError('unsupported active runtime inventory entry')
   actual.append(e)
 actual.sort(key=lambda e:e['path'])
 if actual!=frozen['entries']:raise ValueError('active runtime inventory drift')
 return dict(manifest_sha256=FROZEN_MANIFEST_SHA,inventory_file_sha256=FROZEN_INVENTORY_FILE_SHA,inventory_aggregate_sha256=frozen['aggregate_sha256'])
def main():
 parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group();g.add_argument('--apply',action='store_true');g.add_argument('--rollback',type=Path)
 parser.add_argument('--reviewer-receipt',type=Path);parser.add_argument('--reviewer-sha256');parser.add_argument('--expected-current-sha256');a=parser.parse_args()
 binding=json.loads((O/'bindings.json').read_text());seal=json.loads((O/'candidate-seal.json').read_text())
 plan=dict(mode='PLAN_ONLY',source_root=str(D),selection_root=str(SELECTION),original_close_sha256=OLD,original_dispatcher_sha256=DISPATCH_SHA,original_natural_run='06e39b51fda142449ad1cf9a8c1af480',candidate_manifest_sha256=seal['manifest']['sha256'],candidate_staged_plist_sha256=seal['staged_plist']['sha256'],publish='CAS existing ReviewStore.publish_native; only close artifact/receipt/key and supersession change',provider_or_scheduler_invocation=False,requires='Independent Reviewer PASS; safe window with healthy child jobs complete; candidate installed and activated by main; exact CAS; original full byte archive. Never invoke1610executor or UI manual LLM generation.')
 if not a.apply and a.rollback is None:print(json.dumps(plan,ensure_ascii=False,indent=2));return
 if not a.reviewer_receipt or not a.reviewer_sha256 or sha(a.reviewer_receipt.read_bytes())!=a.reviewer_sha256:raise ValueError('exact independent reviewer receipt required')
 # Parent must inspect the independent verdict; a digest is identity, not an
 # invented signature or automatic claim of a reviewer PASS.
 assert sha(P.read_bytes())==seal['staged_plist']['sha256'],'active plist drift / candidate not activated'
 app=Path(plistlib.loads(P.read_bytes())['WorkingDirectory']);assert app==Path(binding['target_app'])
 runtime_binding=verify_frozen_runtime(app,seal)
 sys.path.insert(0,str(app))
 from infrastructure.review_store import ReviewStore
 from infrastructure.data_store import _sha256
 store=ReviewStore(D);current=store.read_reference(DATE);assert current is not None
 if a.rollback is not None:
  record=json.loads((a.rollback/'operation.json').read_bytes());oldbytes=(a.rollback/'original-close.json').read_bytes()
  assert record['state'] in {'COMMITTED_PENDING_POSTCHECKS','COMMITTED_POSTCHECK_FAILED','POSTCHECK_VERIFIED'}
  archive_raw=(a.rollback/'archive-inventory.json').read_bytes()
  assert sha(archive_raw)==record['archive_inventory_sha256'],'rollback archive binding mismatch'
  for name,entry in json.loads(archive_raw).items():
   assert Path(name).name==name and sha((a.rollback/name).read_bytes())==entry['sha256'],'rollback archive byte drift'
  assert sha(oldbytes)==OLD and a.expected_current_sha256==record['publication']['sha256']
  assert _sha256(current)==a.expected_current_sha256,'rollback CAS drift'
  result=store.publish_native(json.loads(oldbytes),expected_sha256=a.expected_current_sha256)
  dump(a.rollback/'rollback.json',dict(publication=result,reviewer_sha256=a.reviewer_sha256,rolled_back_at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
  print(json.dumps(result));return
 assert sha(DISPATCH.read_bytes())==DISPATCH_SHA,'original natural dispatcher changed'
 assert _sha256(current)==OLD,'original close changed; STOP, do not overwrite'
 # Never trigger an existing pending pool reconcile during a manual recovery.
 from infrastructure.preselection_pool_store import PreselectionPoolStore
 pool=PreselectionPoolStore(D);pending=D/pool._pending_relative(pool_id='hkconnect_d1_top100',trade_date=DATE)
 assert not pending.exists() and not pending.is_symlink(),'pending D1 commit; STOP'
 files={'original-close.json':D/f'close_reviews/{DATE}.json','original-import-receipt.json':D/f'receipts/close_reviews/{DATE}.json','original-full-manifest.json':D/'manifest.json','original-dispatcher.json':DISPATCH}
 raws={name:p.read_bytes() for name,p in files.items()};assert sha(raws['original-close.json'])==OLD
 assert all(p.read_bytes()==raws[name] for name,p in files.items()),'archive input changed during snapshot'
 A=O/'manual-operations'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');A.mkdir(parents=True,exist_ok=False)
 for name,raw in raws.items():(A/name).write_bytes(raw)
 inventory={name:dict(source=str(files[name]),sha256=sha(raw),size=len(raw)) for name,raw in raws.items()};dump(A/'archive-inventory.json',inventory)
 context=dict(mode='MANUAL_HISTORICAL_RECOVERY',trade_date=DATE,original_natural_run_id=plan['original_natural_run'],original_close_sha256=OLD,original_import_receipt_sha256=sha(raws['original-import-receipt.json']),original_dispatcher_receipt_sha256=DISPATCH_SHA,archive_inventory_sha256=sha((A/'archive-inventory.json').read_bytes()))
 dump(A/'manual-context.json',context)
 pool_inputs=[D/f'preselection_pools/{DATE}/hkconnect_d1_top100.json',D/f'preselection_pools/{DATE}/manifest.json',D/f'preselection_pools/{DATE}/receipts/hkconnect_d1_top100.json']
 pool_sha={str(p):sha(p.read_bytes()) for p in pool_inputs}
 from ops.build_close_review import build_close_review
 prepared=dict(state='PREPARED_NO_COMMIT',archive_inventory_sha256=context['archive_inventory_sha256'],original_close_sha256=OLD,runtime_binding=runtime_binding,reviewer_receipt=str(a.reviewer_receipt),reviewer_sha256=a.reviewer_sha256)
 dump(A/'operation.json',prepared)
 try:
  result=build_close_review(D,DATE,stage_selection_root=SELECTION,manual_recovery=context)
 except BaseException as error:
  dump(A/'failed-operation.json',dict(type=type(error).__name__,message=str(error),natural_dispatcher_unchanged=sha(DISPATCH.read_bytes())==DISPATCH_SHA));raise
 # First action after the publisher returns: persist the replacement SHA and
 # archive binding. No pool/dispatcher reads or postchecks may precede it.
 committed={**prepared,'state':'COMMITTED_PENDING_POSTCHECKS','publication':result['publication'],'recovery_provenance':result['review']['recovery_provenance']}
 dump(A/'operation.json',committed)
 try:
  assert all(sha(Path(p).read_bytes())==h for p,h in pool_sha.items()),'pool changed during recovery; preserve all evidence'
  assert sha(DISPATCH.read_bytes())==DISPATCH_SHA,'original natural dispatcher changed after publication'
 except BaseException as error:
  failure=dict(type=type(error).__name__,message=str(error))
  dump(A/'operation.json',{**committed,'state':'COMMITTED_POSTCHECK_FAILED','postcheck_error':failure})
  dump(A/'postcheck-failure.json',dict(**failure,publication=result['publication'],archive_inventory_sha256=context['archive_inventory_sha256'],rollback_available=True))
  raise
 dump(A/'operation.json',{**committed,'state':'POSTCHECK_VERIFIED','original_dispatcher_unchanged':True})
 print(json.dumps(dict(operation_directory=str(A),publication=result['publication'],row_counts=result['review']['row_counts'],mode='MANUAL_HISTORICAL_RECOVERY'),ensure_ascii=False))
if __name__=='__main__':main()
