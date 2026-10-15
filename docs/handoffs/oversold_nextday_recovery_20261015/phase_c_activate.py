"""Reviewed config-selector activation only, using the existing release lock."""
from datetime import datetime, timezone
import copy, hashlib, json, os, plistlib, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parents[2];sys.path.insert(0,str(ROOT))
from ops.api_release_integration import shared_api_release_lock
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
CONFIG=BASE/'config/oversold-nextday-recovery-20261015-r1.json';OLD_CONFIG=BASE/'config/manager-workbench-v9.json'
RELEASE=BASE/'releases/us-hk-mapping-finish-20261015-r2'
EXPECTED=dict(plist='579d18f1d3fa5cde7b26787936fe0e43969a9f826485f55ca39deb8eb910916e',base_config='48fd88d8bc8921181a67c059af7907a56c6a78ef20bec480338409e553e60a9d',candidate_config='f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158',manifest='5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684')
R=dict(previous_attempt='phase_c_activation.json',previous_failure_reason='Health guard expected absent RESEARCH_ONLY in readyz; exact old plist restored; 3 false flags and research env verified',started_at=datetime.now(timezone.utc).isoformat(),status='PRECHECK',commands=[],rollback_performed=False,changes=['EnvironmentVariables.V4_MANAGER_WORKBENCH_CONFIG_PATH'],expected_sha256=EXPECTED)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args):
 x=subprocess.run(args,capture_output=True,text=True,timeout=30);return x
def launch(*args,check=True):
 x=command(['/bin/launchctl',*args]);R['commands'].append(dict(command=['launchctl',*args],exit_code=x.returncode,stdout=x.stdout,stderr=x.stderr))
 if check and x.returncode:raise RuntimeError('LAUNCHCTL_FAILED:'+args[0])
 return x
def pids():return [int(x) for x in command(['/usr/sbin/lsof','-t','-nP','-iTCP:8873','-sTCP:LISTEN']).stdout.split()]
def atomic(raw,mode):
 fd,tmp=tempfile.mkstemp(prefix='.com.lexi.v35.api-only.oversold-',dir=PLIST.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,mode);os.replace(tmp,PLIST)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def detach(target,check=True):
 old=pids();launch('bootout',target,check=check)
 for _ in range(30):
  absent=command(['/bin/launchctl','print',target]).returncode!=0
  alive=[pid for pid in old if command(['/bin/kill','-0',str(pid)]).returncode==0]
  if absent and not alive:
   time.sleep(2);R.setdefault('detach_checks',[]).append(dict(old_pids=old,old_pids_exited=True,label_absent=True,settle_seconds=2));return
  time.sleep(.5)
 raise RuntimeError('SERVICE_DETACH_NOT_CONFIRMED')
def health():
 for attempt in range(25):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8873/healthz',timeout=2) as x:assert json.load(x)['status']=='ok'
   with urllib.request.urlopen('http://127.0.0.1:8873/readyz',timeout=2) as x:safety=json.load(x)
   assert safety.get('production_allowed') is False and safety.get('buy_gate_updated') is False and safety.get('orders_sent') is False
   return safety
  except Exception:
   if attempt==24:raise
   time.sleep(1)
def main():
 assert not (H/'phase_c_activation_r2.json').exists(),'Activation already attempted; inspect receipt'
 review=H/'INDEPENDENT_REVIEW.md';assert 'REVIEWED=PASS' in review.read_text()
 R.update(review_sha256=sha(review),old_config_path=str(OLD_CONFIG),new_config_path=str(CONFIG),release_root=str(RELEASE))
 target='gui/'+str(os.getuid());label='com.lexi.v35.api-only';full=target+'/'+label
 with shared_api_release_lock(PLIST,timeout_seconds=5,role='gateway') as lease:
  assert sha(PLIST)==EXPECTED['plist'],'ACTIVE_PLIST_CAS_CHANGED'
  assert sha(OLD_CONFIG)==EXPECTED['base_config'] and sha(CONFIG)==EXPECTED['candidate_config'],'CONFIG_CAS_CHANGED'
  assert sha(RELEASE/'release-manifest.json')==EXPECTED['manifest'],'MANIFEST_CAS_CHANGED'
  old=PLIST.read_bytes();doc=plistlib.loads(old);env=doc['EnvironmentVariables']
  assert env['V4_MANAGER_WORKBENCH_CONFIG_PATH']==str(OLD_CONFIG)
  assert 'RESEARCH_ONLY=1' in doc['ProgramArguments']
  assert doc['WorkingDirectory']==str(RELEASE/'app') and env['V35_RELEASE_ID']==RELEASE.name
  assert pids()==[7153],'ACTIVE_PID_CHANGED'
  cwd=command(['/usr/sbin/lsof','-a','-p','7153','-d','cwd','-Fn']).stdout;assert '\nn'+str(RELEASE/'app')+'\n' in cwd
  runtime=command(['/bin/launchctl','print',full]);assert runtime.returncode==0 and str(OLD_CONFIG) in runtime.stdout and 'pid = 7153' in runtime.stdout
  original_cfg=json.loads(OLD_CONFIG.read_bytes());candidate_cfg=json.loads(CONFIG.read_bytes());restored_cfg=copy.deepcopy(candidate_cfg)
  restored_cfg['source_bindings']['hk_panel'].pop('20261015');assert restored_cfg==original_cfg,'CANDIDATE_CONFIG_SCOPE_CHANGED'
  R['old_pid']=7153;R['old_plist_sha256']=sha(PLIST);R['lock_path']=str(lease.path)
  (H/'phase_c_preimage.local.plist').write_bytes(old);mode=PLIST.stat().st_mode&0o777
  staged=copy.deepcopy(doc);staged['EnvironmentVariables']['V4_MANAGER_WORKBENCH_CONFIG_PATH']=str(CONFIG)
  back=copy.deepcopy(staged);back['EnvironmentVariables']['V4_MANAGER_WORKBENCH_CONFIG_PATH']=str(OLD_CONFIG);assert back==doc
  new=plistlib.dumps(staged,fmt=plistlib.FMT_XML,sort_keys=True);(H/'phase_c_candidate.local.plist').write_bytes(new)
  R['new_plist_sha256']=hashlib.sha256(new).hexdigest()
  try:
   detach(full);assert sha(PLIST)==EXPECTED['plist'];atomic(new,mode);launch('bootstrap',target,str(PLIST));R['safety']=health()
   newpids=pids();assert len(newpids)==1 and newpids[0]!=7153
   state=command(['/bin/launchctl','print',full]);assert state.returncode==0 and str(CONFIG) in state.stdout
   assert sha(OLD_CONFIG)==EXPECTED['base_config'] and sha(CONFIG)==EXPECTED['candidate_config']
   assert sha(RELEASE/'release-manifest.json')==EXPECTED['manifest'] and sha(PLIST)==R['new_plist_sha256']
   cwd=command(['/usr/sbin/lsof','-a','-p',str(newpids[0]),'-d','cwd','-Fn']).stdout;assert '\nn'+str(RELEASE/'app')+'\n' in cwd
   R.update(status='CONFIG_ACTIVATED_HEALTHY',new_pid=newpids[0],release_manifest_unchanged=True,v9_unchanged=True)
  except BaseException:
   detach(full,check=False);atomic(old,mode);R['rollback_performed']=True;launch('bootstrap',target,str(PLIST));health();R['status']='FAILED_EXACT_ROLLBACK_HEALTHY';raise
if __name__=='__main__':
 try:main()
 except BaseException as e:R.update(error_type=type(e).__name__,error=str(e));raise
 finally:
  R['finished_at']=datetime.now(timezone.utc).isoformat()
  with (H/'phase_c_activation_r2.json').open('x') as f:json.dump(R,f,ensure_ascii=False,indent=2);f.write('\n')
  print(json.dumps(R,ensure_ascii=False))
