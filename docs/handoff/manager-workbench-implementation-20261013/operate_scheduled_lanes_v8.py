"""Exact-plan operator; bounded launchd transient-5 recovery, no activation by default."""
from pathlib import Path
import json,os,plistlib,subprocess,sys,time
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parents[2]))
from v8_active_release import install
install()
import operate_v7_cutover as operator
from ops.api_release_integration import _plist_environment


AUDIT_PATH=None

def audit(args,result,expected):
 if AUDIT_PATH is None:return
 event=dict(monotonic=time.monotonic(),action=args[1],label=args[-1] if args[1]=='print' else None,
     returncode=result.returncode,stdout_sha256=operator.sha(result.stdout.encode()),stderr=result.stderr[:1000],
     expected_identity=expected,identity_matches={k:expected[k] in result.stdout for k in ('V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_SHA256')} if args[1]=='print' and result.returncode==0 else None)
 with AUDIT_PATH.open('a') as stream:stream.write(json.dumps(event)+'\n')


def bootout_and_wait(pair):
 uid=str(os.getuid());label='gui/'+uid+'/'+pair['label'];formal=Path(pair['formal_path']);raw=formal.read_bytes()
 if operator.sha(raw) not in {pair['original_sha256'],pair['staged_sha256']}:raise ValueError('BOOTOUT_PLIST_IDENTITY_DRIFT')
 expected=_plist_environment(plistlib.loads(raw));deadline=time.monotonic()+10
 def command(args):
  if formal.read_bytes()!=raw:raise ValueError('BOOTOUT_PLIST_IDENTITY_DRIFT')
  remaining=deadline-time.monotonic()
  if remaining<=0:raise RuntimeError('BOOTOUT_LABEL_EXIT_TIMEOUT')
  result=subprocess.run(args,capture_output=True,text=True,timeout=min(2,remaining));audit(args,result,expected);return result
 def exists():
  result=command(['launchctl','print',label])
  if result.returncode==0:
   if any(expected[k] not in result.stdout for k in ('V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_SHA256')):raise RuntimeError('BOOTOUT_LOADED_IDENTITY_MISMATCH')
   return True
  if result.returncode not in (3,113) and 'Could not find service' not in result.stderr:raise RuntimeError('BOOTOUT_LABEL_QUERY_FAILED:'+result.stderr)
  return False
 if not exists():return
 result=command(['launchctl','bootout',label])
 if result.returncode:raise RuntimeError('LAUNCHCTL_BOOTOUT:'+result.stderr)
 while exists():
  if time.monotonic()+.2>=deadline:raise RuntimeError('BOOTOUT_LABEL_EXIT_TIMEOUT')
  time.sleep(.2)


def launch(action,pair):
 if action=='bootout':return bootout_and_wait(pair)
 if action!='bootstrap':raise ValueError('LAUNCH_ACTION_FORBIDDEN')
 uid=str(os.getuid());label='gui/'+uid+'/'+pair['label'];formal=Path(pair['formal_path'])
 raw=formal.read_bytes()
 if operator.sha(raw) not in {pair['original_sha256'],pair['staged_sha256']}:raise ValueError('BOOTSTRAP_PLIST_IDENTITY_DRIFT')
 expected=_plist_environment(plistlib.loads(raw));deadline=time.monotonic()+8;last=None
 def command(args):
  if formal.read_bytes()!=raw:raise ValueError('BOOTSTRAP_PLIST_IDENTITY_DRIFT')
  remaining=deadline-time.monotonic()
  if remaining<=0:raise RuntimeError('LAUNCHCTL_BOOTSTRAP_TRANSIENT_5_EXHAUSTED')
  result=subprocess.run(args,capture_output=True,text=True,timeout=min(2,remaining));audit(args,result,expected);return result
 def loaded():
  result=command(['launchctl','print',label])
  if result.returncode==0:
   if any(expected[k] not in result.stdout for k in ('V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_SHA256')):raise RuntimeError('BOOTSTRAP_LOADED_IDENTITY_MISMATCH')
   return True
  if result.returncode not in (3,113) and 'Could not find service' not in result.stderr:raise RuntimeError('BOOTSTRAP_LABEL_QUERY_FAILED:'+result.stderr)
  return False
 for attempt in range(4):
  if loaded():return
  last=command(['launchctl','bootstrap','gui/'+uid,str(formal)])
  if last.returncode==0:
   if not loaded():raise RuntimeError('BOOTSTRAP_SUCCESS_LABEL_ABSENT')
   return
  if last.returncode!=5:raise RuntimeError('LAUNCHCTL_BOOTSTRAP:'+last.stderr)
  if loaded():return
  if attempt<3:
   delay=(.5,1,2)[attempt]
   if time.monotonic()+delay>=deadline:break
   time.sleep(delay)
 raise RuntimeError('LAUNCHCTL_BOOTSTRAP_TRANSIENT_5_EXHAUSTED:'+last.stderr)

ORIGINAL_LAUNCH=operator.launch
operator.launch=launch


def main():
 # Journals are immutable attempts. The reviewed operator keeps its final status
 # entry even when a restore/bootstrap fails; this wrapper retains the exception.
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--plan-sha256',required=True);parser.add_argument('--mode',choices=['apply','rollback'],default='apply');parser.add_argument('--execute',action='store_true');args=parser.parse_args()
 path=Path(args.plan).resolve(strict=True)
 if not path.is_relative_to(HERE) or operator.sha(path.read_bytes())!=args.plan_sha256:raise ValueError('EXACT_PREPARED_PLAN_REQUIRED')
 plan=json.loads(path.read_text());operator.validate(plan,args.mode)
 if args.execute:
  from datetime import datetime,timezone
  stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');journal=path.parent/('operator-'+args.mode+'-'+stamp+'-journal.json')
  global AUDIT_PATH
  AUDIT_PATH=journal.with_name(journal.stem+'-launch-events.jsonl')
  try:
   operator.execute(plan,args.mode,journal)
   value=json.loads(journal.read_text());value['launch_events_path']=str(AUDIT_PATH);journal.write_text(json.dumps(value,indent=2)+'\n')
  except BaseException as exc:
   value=json.loads(journal.read_text()) if journal.exists() else {}
   value.update(status='FAILED_RESTORE_OR_ACTIVATION_REQUIRES_READBACK',error_type=type(exc).__name__,error=str(exc),launch_events_path=str(AUDIT_PATH));journal.write_text(json.dumps(value,indent=2)+'\n');raise
 print(json.dumps(dict(status='EXECUTED_AWAITING_READBACK' if args.execute else 'DRY_RUN_PASS',mode=args.mode,formal_writes=args.execute,capture_enabled=False,lease_granted=False,plan_sha256=args.plan_sha256)))
if __name__=='__main__':main()
