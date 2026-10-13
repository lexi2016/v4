"""Read-only V7 active-base/delta/source/dependency verification; no server."""
from pathlib import Path
import hashlib,json,plistlib,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(ROOT))
from ops.api_release_integration import shared_api_release_lock,verify_api_release_candidate,inventory_tree
sha=lambda b:hashlib.sha256(b).hexdigest()
API=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist');SCHED=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')

def verify():
 r=json.loads((HERE/'deployment-deltas/isolated-candidate-build-v7-receipt.json').read_text());proof={}
 with shared_api_release_lock(API) as lease:
  # This installed generic owned_interprocess_lock yields None. Its actual
  # kernel lock remains held by this context; lease-object attestation is absent.
  proof['api']=verify_api_release_candidate(candidate_root=Path(r['candidate_api']).parent,active_api_plist_path=API,
      expected_manifest_sha256=r['api_manifest_sha256'],lock_lease=lease,require_shared_lock=lease is not None)
  proof['shared_kernel_lock_context_held']=True;proof['generic_lease_object_attested']=lease is not None
  if sha(API.read_bytes())!=r['base']['api_plist_sha256'] or sha(SCHED.read_bytes())!=r['base']['scheduler']['plist_sha256']:raise ValueError('ACTIVE_PLIST_DRIFT')
  sb=r['base']['scheduler'];base=Path(sb['app_root']);app=Path(r['candidate_scheduler'])
  if sha(Path(sb['manifest_path']).read_bytes())!=sb['manifest_sha256'] or inventory_tree(base)!=sb['inventory']:raise ValueError('SCHEDULER_ACTIVE_BASE_DRIFT')
  delta={e['path']:e for e in r['scheduler_delta_entries']};after={e['path']:e for e in inventory_tree(app)}
  for e in sb['inventory']:
   if e['path'] not in delta and after.get(e['path'])!=e:raise ValueError('SCHEDULER_NON_MANAGER_DRIFT')
  if set(after)!={e['path'] for e in sb['inventory']}|set(delta):raise ValueError('SCHEDULER_UNDECLARED_FILE')
  for rel,e in delta.items():
   if sha((app/rel).read_bytes())!=e['after_sha256']:raise ValueError('SCHEDULER_DELTA_DRIFT')
  proof['scheduler_non_delta_preserved']=True
  for role in ('api','scheduler'):
   candidate=Path(r['candidate_'+role]);mp=candidate.parent/'release-manifest.json';m=json.loads(mp.read_text())
   if sha(mp.read_bytes())!=r[role+'_manifest_sha256'] or inventory_tree(candidate)!=m['application_inventory']['entries']:raise ValueError('CANDIDATE_MANIFEST_DRIFT')
   for p in (ROOT/'v4/manager_workbench').rglob('*'):
    if p.is_file() and '__pycache__' not in p.parts and (p.suffix=='.py' or '_vendor' in p.parts):
     if (candidate/p.relative_to(ROOT)).read_bytes()!=p.read_bytes():raise ValueError('MANAGER_FROZEN_SOURCE_DRIFT')
   code='import '+('apps.api.v35_api.app' if role=='api' else 'ops.run_v35_macos_scheduler_daemon')+'; from v4.manager_workbench.inputs.pdf_pages import pinned_pypdf; print(pinned_pypdf().__version__)'
   result=subprocess.run([sys.executable,'-B','-c',code],cwd=candidate,capture_output=True,text=True)
   if result.returncode:raise ValueError(result.stderr)
   proof[role+'_import']=dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
  proof.update(status='PASS',api_manifest_sha256=r['api_manifest_sha256'],scheduler_manifest_sha256=r['scheduler_manifest_sha256'],frontend_assets_reused=r['frontend_assets_reused'],services_started=False,model_calls=0,network_calls=0)
 return proof
if __name__=='__main__':
 proof=verify();(HERE/'integration-v7-import-receipt.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
