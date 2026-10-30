"""Root-only bounded C8 metadata publication and the two existing service CASes."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,subprocess
HERE=Path(__file__).resolve().parent
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/display_name_chart_interaction_fix')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--review',required=True,type=Path);p.add_argument('--publish',action='store_true');p.add_argument('--service',choices=['api','main']);p.add_argument('--rollback',action='store_true');p.add_argument('--idle-receipt',type=Path);a=p.parse_args()
 c=json.loads((B/'CANDIDATES.json').read_text());plan=json.loads((B/'PUBLICATION_PLAN.json').read_text());review=json.loads(a.review.read_text())
 if review.get('status')!='REVIEWED_PASS_C8' or review.get('publication_plan_sha256')!=sha(B/'PUBLICATION_PLAN.json') or any(review.get(role+'_manifest_sha256')!=c[role]['manifest']['sha256'] for role in ['api','main']):raise ValueError('C8_EXACT_REVIEW_REQUIRED')
 for role in ['api','main']:
  if sha(c[role]['manifest']['path'])!=c[role]['manifest']['sha256']:raise ValueError('C8_REVIEWED_MANIFEST_CHANGED')
 lock=open(B/'c8-control.lock','a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 if a.publish:
  spec=importlib.util.spec_from_file_location('c8_owner_save',Path(c['main']['release'])/'app/ops/research_panel_daily_product.py');owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
  if a.rollback:
   prior=json.loads((B/'PUBLICATION_RECEIPT.json').read_text());steps={key:dict(target=plan[key]['target'],before=prior['after'][key],candidate=prior['preimages'][key]) for key in ['index','event']}
  else:steps={key:plan[key] for key in ['index','event']}
  for r in [plan['numeric_manifest_unchanged'],plan['numeric_artifact_unchanged']]:owner.checked(r)
  for step in steps.values():
   owner.checked(step['before']);owner.checked(step['candidate'])
  preimages={};after={}
  for key,step in steps.items():
   if not a.rollback:preimages[key]=owner.save(B/('prepublication_'+key+'.json'),json.loads(Path(step['target']).read_text()))
   after[key]=owner.save(step['target'],json.loads(Path(step['candidate']['path']).read_text()))
  value=dict(status='C8_METADATA_ROLLED_BACK' if a.rollback else 'C8_METADATA_PUBLISHED',review=str(a.review),after=after,preimages=preimages,numeric_artifact_unchanged=plan['numeric_artifact_unchanged'],**owner.FLAGS);owner.save(B/('PUBLICATION_ROLLBACK_RECEIPT.json' if a.rollback else 'PUBLICATION_RECEIPT.json'),value);print(json.dumps(value));return
 if not a.service:p.error('--publish or --service required')
 role=a.service;label='com.lexi.v4.api' if role=='api' else 'com.lexi.v4.scheduler';r=c[role];live=Path('/Users/lexi/Library/LaunchAgents')/(label+'.plist')
 if role=='main':
  idle=json.loads(a.idle_receipt.read_text()) if a.idle_receipt else {}
  if idle.get('status')!='ROOT_NO_HEALTHY_MAIN_WORK_VERIFIED' or idle.get('healthy_active_work') is not False:raise ValueError('ROOT_ACTUAL_IDLE_MAIN_OBSERVATION_REQUIRED')
 target=r['plist_before'] if a.rollback else r['plist_candidate'];expected=r['plist_candidate']['sha256'] if a.rollback else r['plist_before']['sha256']
 if sha(target['path'])!=target['sha256'] or sha(live)!=expected:raise ValueError('C8_LIVE_PLIST_CAS_DRIFT')
 service=f'gui/{os.getuid()}/{label}';stop=subprocess.run(['launchctl','bootout',service],capture_output=True,text=True)
 if stop.returncode:
  observed=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
  if not (a.rollback and observed.returncode==113 and 'could not find service' in observed.stderr.lower()):raise RuntimeError('C8_GRACEFUL_BOOTOUT_FAILED:'+stop.stderr)
 if sha(live)!=expected:raise ValueError('C8_LIVE_PLIST_CHANGED_DURING_STOP')
 pending=live.with_name('.'+live.name+'.c8-pending');pending.write_bytes(Path(target['path']).read_bytes());os.replace(pending,live)
 start=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(live)],capture_output=True,text=True)
 if start.returncode:raise RuntimeError('C8_BOOTSTRAP_FAILED_ROOT_CHECK_ABSENT_BEFORE_SAME_BYTE_RETRY_OR_ROLLBACK:'+start.stderr)
 value=dict(status='C8_ROLLBACK_REQUESTED' if a.rollback else 'C8_CUTOVER_REQUESTED',service=label,live_plist_sha256=sha(live),manifest_sha256=r['manifest']['sha256'],live_API_UI_natural='Root readback required');(B/(role+'_CONTROL_RECEIPT.json')).write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
if __name__=='__main__':main()
