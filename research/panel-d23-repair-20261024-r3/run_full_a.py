"""One reviewed A-only dispatch through original dispatcher/registry; default is read-only."""
from pathlib import Path
import argparse,dataclasses,datetime,hashlib,json,os,stat,struct,subprocess,sys,tempfile
from zoneinfo import ZoneInfo
from publication_guard_r2 import PublicationGuard,manual_window_open,run_directories
E=Path(__file__).resolve().parents[1];specpath=E/'execution/FULL_A_EXECUTION_SPEC.json';spec=json.loads(specpath.read_text())
a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');args=a.parse_args()
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(name,value):
 (E/'execution'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
def require(condition,message):
 if not condition:raise RuntimeError(message)
guard_path=Path(spec['r2_publication_guard_path']);require(guard_path.resolve()==(E/'execution/publication_guard_r2.py').resolve(),'R2_PUBLICATION_GUARD_PATH_CAS');require(digest(guard_path)==spec['r2_publication_guard_sha256'],'R2_PUBLICATION_GUARD_SHA_CAS')
manifest=json.loads(Path(spec['child_manifest']).read_text());require(digest(spec['child_manifest'])==spec['child_manifest_sha256'],'CHILD_MANIFEST_CAS')
child=Path(spec['child_app'])
for row in manifest['files']:require(digest(child/row['path'])==row['sha256'],'CHILD_SOURCE_CAS:'+row['path'])
require(digest(spec['preimages'])==spec['preimages_sha256'],'PREIMAGE_MANIFEST_CAS');pre=json.loads(Path(spec['preimages']).read_text())
require(digest(spec['six_candidate_manifest'])==spec['six_candidate_manifest_sha256'],'SIX_CANDIDATE_MANIFEST_CAS');quotes=json.loads(Path(spec['six_candidate_manifest']).read_text())
for row in pre['files']:require(digest(row['path'])==row['sha256'],'DAY_PREIMAGE_CAS:'+row['path'])
for row in pre['receipt_pointer_preimages']:require(digest(row['path'])==row['sha256'],'RECEIPT_POINTER_CAS:'+row['path'])
for q in quotes:
 require(digest(q['candidate_path'])==q['candidate_sha256'],'SIX_CANDIDATE_BYTES_CAS')
 b=Path(q['candidate_path']).read_bytes();old=Path(q['source_path']).read_bytes()
 require(b[:len(old)]==old and len(b)==len(old)+32 and struct.unpack_from('<I',b,len(old))[0]==20261023,'SIX_APPEND_SHAPE')
# Scope is the controller-reviewed half-open manual window for this same D23.
# It cannot drift to another target date or become an unattended launcher.
window=spec.get('manual_execution_window',{});now=datetime.datetime.now(ZoneInfo('Asia/Shanghai'));require(all(str(spec['request'].get(k))==str(window.get('target_date')) for k in ['scheduled_date','business_date','target_date']),'MANUAL_WINDOW_REQUEST_DATE_CAS');require(manual_window_open(window,str(spec['request']['target_date']),now),'MANUAL_WINDOW_CLOSED_REVIEW_REQUIRED')
os.environ.update(spec['env'])
for p in reversed(spec['env']['PYTHONPATH'].split(':')):sys.path.insert(0,p)
from contracts.runtime_tasks import DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops.run_v35_macos_scheduler_due import resolve_due_slot
catalog=load_workload_catalog();selected=tuple(w for w in catalog.workloads if w.workload_id==spec['workload_id']);require(len(selected)==1 and selected[0].enabled,'A_CATALOG_OWNER_UNAVAILABLE')
only_a=dataclasses.replace(catalog,workloads=selected)
ledgerroot=Path(spec['ledger_root']);request=DispatchRequest(**spec['request'])
claim_state={p:(ledgerroot/p).read_text() if (ledgerroot/p).exists() else None for p in spec['claim_paths']}
require(all(v is None for v in claim_state.values()),'CLAIM_EXISTS_STOP_NO_RECLAIM')
# All currently loaded A entry processes must be absent. This is supplementary
# evidence; actual ownership comes from original atomic dispatch+workload claims.
ps=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True)
active=[line for line in ps.splitlines() if any(s in line for s in ['-m ops.macos_research_panel_daily','/a_share_daily_sync.py','data_layer_daily_formula_increment_update_v1.py']) and not line.lstrip().startswith(str(os.getpid())+' ')]
require(not active,'ACTIVE_A_CHILD_STOP')
readproof={'observed_at':now.isoformat(),'due':resolve_due_slot(ledger_root=ledgerroot,now=now),'claim_preimages':claim_state,'active_a_processes':active,'a_catalog':dataclasses.asdict(selected[0]),'catalog_path':str(child/'contracts/runtime_workloads.json'),'catalog_sha256':digest(child/'contracts/runtime_workloads.json'),'target_count':pre['target_count'],'preimages_verified':True,'child_source_verified':True,'mode':'EXECUTE' if args.execute else 'READ_ONLY_PREFLIGHT','does_not_claim_global_quiescence':True}
write('FULL_A_PREFLIGHT.json',readproof);print(json.dumps({'status':'PREFLIGHT_OK','target_count':pre['target_count'],'execute':args.execute}),flush=True)
if not args.execute:sys.exit(0)
require(not (E/'execution/FULL_A_DISPATCH_RESULT.json').exists(),'EXISTING_RESULT_STOP_NO_REPEAT')
registry=FixedExecutorRegistry(data_root=spec['data_root'],repo_root=child,timeout_seconds=600,a_daily_timeout_seconds=spec['a_daily_timeout_seconds'],hk_0_2_python_executable='/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/app/ops/launch_hk_0_2_python_nosite.sh')
write('RESOURCE_BEFORE.json',{'observed_at':now.isoformat(),'swapusage':subprocess.check_output(['sysctl','-n','vm.swapusage'],text=True)})
seeded=[];publication_guard_result=None
def owned_a_executor(workload,req,decision):
 global publication_guard_result
 require(workload.workload_id==spec['workload_id'],'NON_A_EXECUTOR_FORBIDDEN')
 claims=[json.loads((ledgerroot/p).read_text()) for p in spec['claim_paths']]
 require(all(c['pid']==os.getpid() and c['business_date']=='20261023' and c['slot']=='1700' for c in claims) and claims[0]['run_id']==claims[1]['run_id'],'NATIVE_DOUBLE_CLAIM_OWNERSHIP_REQUIRED')
 write('FULL_A_NATIVE_OWNER.json',{'claims':claims,'owner_pid':os.getpid(),'claim_source':'unchanged ExecutionLedger originalO_EXCL acquisition; no custom lock; no manualclaim deletion','child_only':True})
 # Validate every source after both native claims are held, before any mutation.
 for row in pre['files']:require(digest(row['path'])==row['sha256'],'LOCKED_DAY_PREIMAGE_CAS:'+row['path'])
 for row in pre['receipt_pointer_preimages']:require(digest(row['path'])==row['sha256'],'LOCKED_RECEIPT_POINTER_CAS:'+row['path'])
 # Reuse exact independently reviewed six original-producer postimages. The
 # full producer subsequently admits them as ALREADY_CURRENT, with all guards.
 for q in quotes:
  p=Path(q['source_path']);require(digest(p)==q['source_sha256_before'],'LOCKED_SIX_CAS');payload=Path(q['candidate_path']).read_bytes();mode=stat.S_IMODE(p.stat().st_mode)
  fd,temp=tempfile.mkstemp(prefix=p.name+'.a23-',dir=p.parent)
  try:
   with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
   os.chmod(temp,mode);require(digest(p)==q['source_sha256_before'],'LAST_SIX_CAS');os.replace(temp,p)
  finally:
   if os.path.exists(temp):os.unlink(temp)
  require(digest(p)==q['candidate_sha256'],'SIX_POSTIMAGE_CAS');seeded.append({'path':str(p),'before':q['source_sha256_before'],'after':q['candidate_sha256']});write('SIX_REVIEWED_IMAGES_REUSED.json',seeded)
 formula_root=Path(spec['env']['V35_RESEARCH_PANEL_A_RETURN_ROOT']);lane_path=Path(spec['env']['V35_RESEARCH_PANEL_RECEIPT_ROOT'])/'a-20261023.json'
 publication_guard=PublicationGuard(selector_pointer=spec['env']['V35_RESEARCH_PANEL_A_SELECTOR_POINTER'],backtest_pointer=spec['env']['V35_RESEARCH_PANEL_A_BACKTEST_POINTER'],lane_receipt=lane_path,formula_runs_root=formula_root,preimage_rows=pre['receipt_pointer_preimages'],existing_run_names=run_directories(formula_root),ledger_root=ledgerroot,claim_paths=spec['claim_paths'],pid=os.getpid(),run_id=claims[0]['run_id'],target_date='20261023',slot='1700')
 publication_guard_result={'preimages':publication_guard.capture(),'status':'SNAPSHOT_CAPTURED_UNDER_NATIVE_DOUBLE_CLAIMS'}
 try:
  output=registry(workload,req,decision)
 except BaseException as exc:
  publication_guard_result=publication_guard.reconcile(error=exc)
  if str(publication_guard_result.get('status','')).startswith('STOP_'):raise RuntimeError('PUBLICATION_GUARD_STOP:'+str(publication_guard_result.get('reason'))) from exc
  raise
 publication_guard_result=publication_guard.reconcile(executor_output=output)
 if str(publication_guard_result.get('status','')).startswith('STOP_'):raise RuntimeError('PUBLICATION_GUARD_STOP:'+str(publication_guard_result.get('reason')))
 return output
try:
 result=dispatch_due(request,only_a,owned_a_executor,ledger=ExecutionLedger(ledgerroot))
 write('FULL_A_DISPATCH_RESULT.json',dataclasses.asdict(result))
 print(json.dumps({'dispatch_status':result.status,'run_id':result.run_id,'receipt_path':result.receipt_path}),flush=True)
finally:
 # A process return is never the pass signal. Record complete physical writes,
 # including a failed/partial producer, and preserve all original prefixes.
 post=[];errors=[]
 for row in pre['files']:
  p=Path(row['path']);b=p.read_bytes();old=Path(row['backup']).read_bytes();same=b==old;prefix=b[:len(old)]==old;shape=same or (len(b)==len(old)+32 and struct.unpack_from('<I',b,len(old))[0]==20261023)
  if not(prefix and shape):errors.append(str(p))
  post.append({'path':str(p),'before_sha256':row['sha256'],'after_sha256':hashlib.sha256(b).hexdigest(),'before_bytes':len(old),'after_bytes':len(b),'changed':not same,'historical_prefix_exact':prefix,'only_target_day_append':shape})
 write('FULL_A_PHYSICAL_WRITE_RECEIPT.json',{'files':post,'historical_prefix_errors':errors,'changed_count':sum(r['changed'] for r in post),'publication_guard':publication_guard_result,'schema':'a23.physical_append_audit.v1'})
 write('RESOURCE_AFTER.json',{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'swapusage':subprocess.check_output(['sysctl','-n','vm.swapusage'],text=True)})
 require(not errors,'HISTORICAL_PREFIX_OR_APPEND_VIOLATION_STOP')
# Exact dated authority/panel/six readback is a separate receipt/review step.
require(result.status=='SUCCEEDED','DISPATCH_NOT_SUCCEEDED_PRESERVE_RECEIPTS_NO_BLIND_RETRY')
