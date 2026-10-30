"""Root-only C9 publication/API CAS. Main and numeric artifacts stay unchanged."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,subprocess,time
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/readable_stock_materials')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wait_absent(service,timeout=45):
    deadline=time.monotonic()+timeout
    while True:
        seen=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
        if seen.returncode==113 and 'could not find service' in seen.stderr.lower():return
        if time.monotonic()>=deadline:raise RuntimeError('C9_SERVICE_NOT_ABSENT_NO_BOOTSTRAP:'+seen.stderr)
        time.sleep(.2)
def load_publisher(plan):
    reference=plan['owner_publisher']
    if sha(reference['path'])!=reference['sha256']:raise ValueError('C9_ORIGINAL_MAIN_OWNER_SHA_DRIFT')
    spec=importlib.util.spec_from_file_location('c9_owner_save',Path(reference['path']));owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner);return owner

def stop_and_wait_absent(service,rollback):
    stop=subprocess.run(['launchctl','bootout',service],capture_output=True,text=True)
    if stop.returncode:
        seen=subprocess.run(['launchctl','print',service],capture_output=True,text=True) if rollback else None
        if seen is None or seen.returncode!=113 or 'could not find service' not in seen.stderr.lower():raise RuntimeError('C9_GRACEFUL_BOOTOUT_FAILED:'+stop.stderr)
    wait_absent(service)

def main():
    p=argparse.ArgumentParser();p.add_argument('--review',required=True,type=Path);p.add_argument('--publish',action='store_true');p.add_argument('--api',action='store_true');p.add_argument('--rollback',action='store_true');a=p.parse_args()
    c=json.loads((B/'CANDIDATES.json').read_text())['api'];plan=json.loads((B/'PUBLICATION_PLAN.json').read_text());review=json.loads(a.review.read_text())
    if (review.get('status')!='REVIEWED_PASS_C9' or review.get('publication_plan_sha256')!=sha(B/'PUBLICATION_PLAN.json') or review.get('api_manifest_sha256')!=c['manifest']['sha256']):raise ValueError('C9_EXACT_REVIEW_REQUIRED')
    if sha(c['manifest']['path'])!=c['manifest']['sha256']:raise ValueError('C9_MANIFEST_DRIFT')
    lock=open(B/'control.lock','a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    if a.publish:
        # Reuse the existing owner atomic save, not a second publisher format.
        owner=load_publisher(plan)
        if a.rollback:
            prior=json.loads((B/'PUBLICATION_RECEIPT.json').read_text());steps={k:dict(target=plan[k]['target'],before=prior['after'][k],candidate=prior['preimages'][k]) for k in ['index','event']}
        else:steps={k:plan[k] for k in ['index','event']}
        for r in [plan['numeric_manifest_unchanged'],plan['numeric_artifact_unchanged']]:owner.checked(r)
        for step in steps.values():
            owner.checked(step['before']);owner.checked(step['candidate'])
        preimages={};after={}
        for k,step in steps.items():
            if not a.rollback:preimages[k]=owner.save(B/('prepublication_'+k+'.json'),json.loads(Path(step['target']).read_text()))
            after[k]=owner.save(step['target'],json.loads(Path(step['candidate']['path']).read_text()))
        value=dict(status='C9_METADATA_ROLLED_BACK' if a.rollback else 'C9_METADATA_PUBLISHED',after=after,preimages=preimages,numeric_artifact_unchanged=plan['numeric_artifact_unchanged'],**owner.FLAGS);owner.save(B/('PUBLICATION_ROLLBACK_RECEIPT.json' if a.rollback else 'PUBLICATION_RECEIPT.json'),value);print(json.dumps(value));return
    if not a.api:p.error('--publish or --api required')
    live=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist');target=c['plist_before'] if a.rollback else c['plist_candidate'];expected=c['plist_candidate']['sha256'] if a.rollback else c['plist_before']['sha256']
    if sha(target['path'])!=target['sha256'] or sha(live)!=expected:raise ValueError('C9_LIVE_PLIST_CAS_DRIFT_NO_STOP')
    service=f'gui/{os.getuid()}/com.lexi.v4.api';stop_and_wait_absent(service,a.rollback)
    if sha(live)!=expected:raise ValueError('C9_LIVE_PLIST_CHANGED_DURING_STOP')
    pending=live.with_name('.'+live.name+'.c9-pending');pending.write_bytes(Path(target['path']).read_bytes());os.replace(pending,live)
    start=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(live)],capture_output=True,text=True)
    if start.returncode:raise RuntimeError('C9_BOOTSTRAP_FAILED_NO_BLIND_RETRY:'+start.stderr)
    value=dict(status='C9_API_ROLLBACK_REQUESTED' if a.rollback else 'C9_API_CUTOVER_REQUESTED',live_plist_sha256=sha(live),main='UNCHANGED',runtime_verification='ROOT_READBACK_REQUIRED');(B/'API_CONTROL_RECEIPT.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
if __name__=='__main__':main()
