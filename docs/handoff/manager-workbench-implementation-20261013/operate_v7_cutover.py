"""Exact-plan operator entry: dry-run by default; explicit apply/whole rollback.
The Writer prepares and tests this entry only. Service/formal actions are operator-only.
"""
from pathlib import Path
import argparse,hashlib,json,plistlib,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT))
from prepare_v7_operator import FORMAL,CANONICAL,allowed_source
from verify_v7_candidate import API,SCHED
from ops.api_release_integration import shared_api_release_lock,verify_api_release_candidate,inventory_tree
from infrastructure.owned_io import SafeRoot
sha=lambda b:hashlib.sha256(b).hexdigest()

def target_root(entry):
 path=Path(entry['target']);kind=entry['kind']
 roots={'config':FORMAL/'config','saved_state':FORMAL/'state/manager_workbench','capture_material':FORMAL/'state/manager_workbench_capture','canonical':CANONICAL,'plist':API.parent}
 root=roots.get(kind)
 if root is None or not path.is_relative_to(root) or '..' in path.parts:raise ValueError('OPERATOR_PATH_FORBIDDEN')
 if kind=='config' and path!=FORMAL/'config/manager-workbench-v7.json':raise ValueError('CONFIG_PATH_FORBIDDEN')
 if kind=='plist' and path not in {API,SCHED}:raise ValueError('PLIST_PATH_FORBIDDEN')
 if kind=='canonical' and not allowed_source(path.relative_to(root).as_posix()):raise ValueError('SOURCE_PATH_FORBIDDEN')
 if kind=='capture_material' and 'leases' in path.relative_to(root).parts:raise ValueError('CAPTURE_LEASE_TRANSFER_FORBIDDEN')
 for parent in [path,*path.parents]:
  if parent.is_symlink():raise ValueError('OPERATOR_SYMLINK_FORBIDDEN')
 return root

def current_sha(path):return sha(path.read_bytes()) if path.exists() else None

def validate(plan,mode):
 expected_labels={'com.lexi.v35.api-only','com.lexi.v35.scheduler'}
 if {p['label'] for p in plan['plists']}!=expected_labels:raise ValueError('OPERATOR_LABEL_FORBIDDEN')
 for e in plan['entries']:
  target_root(e);source=Path(e['source'])
  if source.is_symlink() or sha(source.read_bytes())!=e['after_sha256']:raise ValueError('OPERATOR_SOURCE_DRIFT')
  if e['backup'] and sha(Path(e['backup']).read_bytes())!=e['before_sha256']:raise ValueError('ROLLBACK_BACKUP_DRIFT')
  if mode=='rollback' and e['kind'] in {'saved_state','capture_material'}:continue
  expected=e['after_sha256'] if mode=='rollback' else e['before_sha256']
  if current_sha(Path(e['target']))!=expected:raise ValueError('OPERATOR_TARGET_PARALLEL_DRIFT:'+e['target'])
 cfg_entry=next(e for e in plan['entries'] if e['kind']=='config');cfg=json.loads(Path(cfg_entry['source']).read_text())
 if cfg.get('capture_enabled') or cfg.get('capture_lease_token'):raise ValueError('OPERATOR_CAPTURE_DISABLED_REQUIRED')
 lease=FORMAL/'state/manager_workbench_source_leases/leases/EASTMONEY_HK.json'
 if lease.exists() and json.loads(lease.read_text()).get('enabled'):raise ValueError('REVOKE_NEW_OWNER_BEFORE_CUTOVER_OR_ROLLBACK')
 for role in ('api','scheduler'):
  app=Path(plan['candidate_'+role]);mp=app.parent/'release-manifest.json';m=json.loads(mp.read_text())
  if sha(mp.read_bytes())!=plan[role+'_manifest_sha256'] or inventory_tree(app)!=m['application_inventory']['entries']:raise ValueError('OPERATOR_CANDIDATE_DRIFT')

def write(entry,restore=False):
 root=target_root(entry);path=Path(entry['target']);rel=path.relative_to(root).as_posix()
 observed=current_sha(path)
 expected=entry['after_sha256'] if restore else entry['before_sha256']
 if restore and observed==entry['before_sha256']:return
 if observed!=expected:raise ValueError('OPERATOR_TARGET_CHANGED_BEFORE_WRITE:'+str(path))
 io=SafeRoot(root)
 if restore:
  if entry['before_sha256'] is None:
   if path.exists():io.unlink_if_same(rel,Path(entry['source']).read_bytes())
  else:io.write_bytes(rel,Path(entry['backup']).read_bytes())
 else:
  raw=Path(entry['source']).read_bytes()
  if sha(raw)!=entry['after_sha256']:raise ValueError('OPERATOR_SOURCE_CHANGED_BEFORE_WRITE')
  if current_sha(path)==entry['after_sha256']:return
  io.write_bytes(rel,raw,require_absent=entry['before_sha256'] is None)
  if sha(path.read_bytes())!=entry['after_sha256']:raise ValueError('OPERATOR_READBACK_FAILED')

def launch(action,pair):
 uid=str(__import__('os').getuid())
 args=['launchctl',action,'gui/'+uid+'/'+pair['label']] if action=='bootout' else ['launchctl','bootstrap','gui/'+uid,pair['formal_path']]
 result=subprocess.run(args,capture_output=True,text=True)
 if result.returncode:raise RuntimeError('LAUNCHCTL_'+action.upper()+':'+result.stderr)

def execute(plan,mode,journal):
 changed=[];stopped=[];started=[]
 def record(status):journal.write_text(json.dumps(dict(status=status,mode=mode,changed=[e['target'] for e in changed],stopped=stopped,started=started),indent=2)+'\n')
 with shared_api_release_lock(API) as lease:
  validate(plan,mode)
  if mode=='apply':verify_api_release_candidate(candidate_root=Path(plan['candidate_api']).parent,active_api_plist_path=API,expected_manifest_sha256=plan['api_manifest_sha256'],lock_lease=lease,require_shared_lock=lease is not None)
  # Last preimage check and both service changes remain within the same lock.
  record('PREFLIGHT_PASS')
  try:
   for pair in reversed(plan['plists']):launch('bootout',pair);stopped.append(pair['label']);record('STOPPED')
   for e in plan['entries']:
    if mode=='rollback' and e['kind'] in {'saved_state','capture_material'}:continue
    write(e,restore=mode=='rollback');changed.append(e);record('WRITTEN')
   for pair in plan['plists']:launch('bootstrap',pair);started.append(pair['label']);record('STARTED')
   record('APPLIED_AWAITING_API_UI_VERIFY' if mode=='apply' else 'ROLLED_BACK_AWAITING_ORIGINAL_VERIFY')
  except BaseException:
   # Apply failures restore only this exact batch; saved immutable evidence stays.
   if mode=='apply':
    for pair in plan['plists']:
     if pair['label'] in started:launch('bootout',pair)
    for e in reversed(changed):
     if e['kind'] not in {'saved_state','capture_material'}:write(e,restore=True)
    for pair in plan['plists']:
     if pair['label'] in stopped:launch('bootstrap',pair)
   record('FAILED_PRESERVED_JOURNAL');raise

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True);p.add_argument('--plan-sha256',required=True);p.add_argument('--mode',choices=['apply','rollback'],default='apply');p.add_argument('--execute',action='store_true');a=p.parse_args()
 path=Path(a.plan).resolve(strict=True)
 if not path.is_relative_to(HERE) or sha(path.read_bytes())!=a.plan_sha256:raise ValueError('EXACT_PREPARED_PLAN_REQUIRED')
 plan=json.loads(path.read_text());validate(plan,a.mode)
 if a.execute:execute(plan,a.mode,path.parent/('operator-'+a.mode+'-journal.json'))
 print(json.dumps(dict(status='EXECUTED_AWAITING_READBACK' if a.execute else 'DRY_RUN_PASS',mode=a.mode,formal_writes=a.execute,capture_enabled=False,lease_granted=False,plan_sha256=a.plan_sha256)))
if __name__=='__main__':main()
