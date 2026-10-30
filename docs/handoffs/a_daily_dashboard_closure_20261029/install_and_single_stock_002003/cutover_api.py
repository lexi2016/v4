"""Root-only exact API cutover/rollback for this reviewed inactive candidate."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,plistlib,subprocess,time
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
LIVE=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist');LABEL='com.lexi.v4.api';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--review',required=True,type=Path);p.add_argument('--rollback',action='store_true');a=p.parse_args();r=json.loads((B/'API_CANDIDATE_RECEIPT.json').read_text());review=json.loads(a.review.read_text());target=r['plist_before'] if a.rollback else r['plist_candidate'];expected=r['plist_candidate']['sha256'] if a.rollback else r['plist_before']['sha256']
 if review.get('status')!='REVIEWED_PASS_COMPOSED_BINDING' or review.get('api_manifest_sha256')!=r['manifest']['sha256']:raise ValueError('EXACT_COMPOSED_REVIEW_REQUIRED')
 if sha(target['path'])!=target['sha256'] or sha(r['manifest']['path'])!=r['manifest']['sha256']:raise ValueError('REVIEWED_BYTES_CHANGED')
 lock=open(B/'api-cutover.lock','a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 if sha(LIVE)!=expected:raise ValueError('API_PLIST_CAS_DRIFT')
 # Ordinary Uvicorn graceful termination only; no SIGKILL, unrelated labels or user windows.
 service=f'gui/{os.getuid()}/{LABEL}';stop=subprocess.run(['launchctl','bootout',service],capture_output=True,text=True)
 if stop.returncode!=0:
  observed=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
  absent=observed.returncode==113 and 'could not find service' in observed.stderr.lower()
  if not (a.rollback and absent):raise RuntimeError('API_GRACEFUL_BOOTOUT_FAILED:'+stop.stderr)
 if sha(LIVE)!=expected:raise ValueError('API_PLIST_CHANGED_DURING_STOP')
 pending=LIVE.with_name('.'+LIVE.name+'.this-cutover-pending');pending.write_bytes(Path(target['path']).read_bytes());os.replace(pending,LIVE)
 start=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(LIVE)],capture_output=True,text=True)
 if start.returncode!=0:raise RuntimeError('API_BOOTSTRAP_FAILED_ROLLBACK_REQUIRED:'+start.stderr)
 receipt={'status':'API_ROLLBACK_REQUESTED' if a.rollback else 'API_CUTOVER_REQUESTED','live_plist_sha256':sha(LIVE),'review':str(a.review),'before_cas_sha256':expected,'manifest_sha256':r['manifest']['sha256'],'no_other_service_actions':True,'live_readback':'Root must verify current PID/release/8873 health/API/UI before claim'}
 (B/('API_ROLLBACK_CONTROL_RECEIPT.json' if a.rollback else 'API_CUTOVER_CONTROL_RECEIPT.json')).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
