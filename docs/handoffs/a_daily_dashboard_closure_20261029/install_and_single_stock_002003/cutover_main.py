"""Root-only this Main candidate, after actual no-healthy-work observation."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,subprocess
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
LIVE=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist');LABEL='com.lexi.v4.scheduler';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--review',required=True,type=Path);p.add_argument('--idle-receipt',required=True,type=Path);p.add_argument('--rollback',action='store_true');a=p.parse_args();r=json.loads((B/'MAIN_CANDIDATE_RECEIPT.json').read_text());review=json.loads(a.review.read_text());idle=json.loads(a.idle_receipt.read_text())
 if review.get('status')!='REVIEWED_PASS_COMPOSED_BINDING' or review.get('main_manifest_sha256')!=r['manifest']['sha256']:raise ValueError('EXACT_MAIN_COMPOSED_REVIEW_REQUIRED')
 if idle.get('status')!='ROOT_NO_HEALTHY_MAIN_WORK_VERIFIED' or idle.get('healthy_active_work') is not False:raise ValueError('ROOT_REAL_NO_HEALTHY_WORK_CHECK_REQUIRED')
 target=r['plist_before'] if a.rollback else r['plist_candidate'];expected=r['plist_candidate']['sha256'] if a.rollback else r['plist_before']['sha256']
 if sha(target['path'])!=target['sha256'] or sha(r['manifest']['path'])!=r['manifest']['sha256']:raise ValueError('REVIEWED_MAIN_BYTES_CHANGED')
 lock=open(B/'main-cutover.lock','a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 if sha(LIVE)!=expected:raise ValueError('MAIN_PLIST_CAS_DRIFT')
 service=f'gui/{os.getuid()}/{LABEL}';stop=subprocess.run(['launchctl','bootout',service],capture_output=True,text=True)
 if stop.returncode!=0:
  observed=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
  absent=observed.returncode==113 and 'could not find service' in observed.stderr.lower()
  if not (a.rollback and absent):raise RuntimeError('MAIN_GRACEFUL_BOOTOUT_FAILED:'+stop.stderr)
 if sha(LIVE)!=expected:raise ValueError('MAIN_PLIST_CHANGED_DURING_STOP')
 pending=LIVE.with_name('.'+LIVE.name+'.this-cutover-pending');pending.write_bytes(Path(target['path']).read_bytes());os.replace(pending,LIVE)
 start=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(LIVE)],capture_output=True,text=True)
 if start.returncode!=0:raise RuntimeError('MAIN_BOOTSTRAP_FAILED_ROLLBACK_REQUIRED:'+start.stderr)
 receipt={'status':'MAIN_ROLLBACK_REQUESTED' if a.rollback else 'MAIN_CUTOVER_REQUESTED','live_plist_sha256':sha(LIVE),'review':str(a.review),'idle_observation':{'path':str(a.idle_receipt),'sha256':sha(a.idle_receipt)},'before_cas_sha256':expected,'manifest_sha256':r['manifest']['sha256'],'no_other_service_actions':True,'natural_1540':'NOT_RUN','live_readback':'Root must verify current PID/release/daemon before installed claim'}
 (B/('MAIN_ROLLBACK_CONTROL_RECEIPT.json' if a.rollback else 'MAIN_CUTOVER_CONTROL_RECEIPT.json')).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
