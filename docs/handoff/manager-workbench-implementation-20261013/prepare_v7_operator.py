"""Prepare exact V7 formal config, byte transfer, source sync and dual-plist plan.
Writes only this handoff. No formal activation; requires saved single canary proof.
"""
from pathlib import Path
import argparse,hashlib,json,sys,plistlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT))
from verify_v7_candidate import verify,API,SCHED
from stage_v7_cutover import main as stage_main
from v4.manager_workbench.config import WorkbenchConfig
sha=lambda b:hashlib.sha256(b).hexdigest()
FORMAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
CANONICAL=Path('/Users/lexi/Desktop/学习/v4_app')

def allowed_source(rel):
 return (rel in {'apps/api/v35_api/app.py','ops/run_v35_macos_scheduler_daemon.py','apps/web/src/manager-selection/main.ts','apps/web/manager-selection/index.html','contracts/us_equity_calendar.py','contracts/us_equity_calendar_2026.json'}
  or rel.startswith('v4/manager_workbench/') or rel.startswith('apps/web/src/manager-workbench/')) and '..' not in Path(rel).parts

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--canary-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 proof_path=Path(a.canary_proof).resolve(strict=True);proof=json.loads(proof_path.read_text());out=Path(a.output).resolve()
 if not out.is_relative_to(HERE):raise ValueError('HANDOFF_PREPARATION_ONLY')
 if proof.get('state')!='SUCCEEDED' or not proof.get('immutable_saved_readback') or proof.get('phase')!='RETROSPECTIVE':raise ValueError('SUCCESSFUL_SAVED_RETROSPECTIVE_CANARY_REQUIRED')
 verify();build=json.loads((HERE/'deployment-deltas/isolated-candidate-build-v7-receipt.json').read_text());isolated=Path(proof['config_path']).resolve().parent
 if '/T/mwb-live-capture-canary-' not in str(isolated):raise ValueError('KNOWN_ISOLATED_CANARY_ONLY')
 cfg=WorkbenchConfig.model_validate_json(Path(proof['config_path']).read_text())
 if cfg.capture_enabled or cfg.capture_lease_token:raise ValueError('CANARY_CAPTURE_MUST_BE_DISABLED')
 formal_cfg=cfg.model_copy(update=dict(state_root=FORMAL/'state/manager_workbench',capture_root=FORMAL/'state/manager_workbench_capture',capture_lease_root=FORMAL/'state/manager_workbench_source_leases',capture_enabled=False,capture_lease_token=None))
 WorkbenchConfig.model_validate(formal_cfg.model_dump());out.mkdir(parents=True,exist_ok=False)
 config_source=out/'manager-workbench-v7.json';config_source.write_text(formal_cfg.model_dump_json(indent=2)+'\n');config_target=FORMAL/'config/manager-workbench-v7.json'
 sys.argv=['stage_v7_cutover','--manager-config',str(config_source),'--output',str(out/'plists')];stage_main()
 pairs=json.loads((out/'plists/cutover-stage-receipt.json').read_text())['plist_pairs']
 for pair in pairs:
  path=Path(pair['staged']);d=plistlib.loads(path.read_bytes());d['EnvironmentVariables']['V4_MANAGER_WORKBENCH_CONFIG_PATH']=str(config_target)
  d['ProgramArguments']=[('V4_MANAGER_WORKBENCH_CONFIG_PATH='+str(config_target)) if x.startswith('V4_MANAGER_WORKBENCH_CONFIG_PATH=') else x for x in d['ProgramArguments']]
  path.write_bytes(plistlib.dumps(d,sort_keys=False));pair['staged_sha256']=sha(path.read_bytes())
 entries=[]
 def append(kind,source,target,expected_before=None):
  if source.is_symlink() or target.is_symlink():raise ValueError('EXACT_SOURCE_OR_TARGET_SYMLINK')
  raw=source.read_bytes();before=target.read_bytes() if target.exists() else None
  if expected_before is not None and (sha(before) if before is not None else None)!=expected_before:raise ValueError('CANONICAL_PREIMAGE_DRIFT:'+str(target))
  backup=None
  if before is not None:
   backup=out/'before'/str(len(entries));backup.parent.mkdir(exist_ok=True);backup.write_bytes(before)
  entries.append(dict(kind=kind,source=str(source),target=str(target),before_sha256=sha(before) if before is not None else None,after_sha256=sha(raw),backup=str(backup) if backup else None))
 append('config',config_source,config_target)
 for item in build['canonical_sync']:
  rel=item['path']
  if not allowed_source(rel):raise ValueError('CANONICAL_SYNC_PATH_FORBIDDEN')
  source=Path(item.get('source') or HERE/'deployment-deltas/canonical-candidate-v7'/rel)
  target=CANONICAL/rel;observed=sha(target.read_bytes()) if target.exists() else None
  if observed!=item['before_sha256'] or sha(source.read_bytes())!=item['after_sha256']:raise ValueError('CANONICAL_SYNC_IDENTITY_DRIFT:'+rel)
  append('canonical',source,target)
 # Immutable copies retain every content byte/ref, including failed attempts.
 # Copy no lease or transient lock and never replace a different saved product.
 for kind,source_root,target_root in [('saved_state',cfg.state_root,formal_cfg.state_root),('capture_material',cfg.capture_root,formal_cfg.capture_root)]:
  for source in sorted(source_root.rglob('*')):
   if not source.is_file() or source.suffix=='.lock' or any(x in {'locks','__pycache__'} for x in source.parts):continue
   if kind=='capture_material' and 'leases' in source.relative_to(source_root).parts:continue
   target=target_root/source.relative_to(source_root)
   if target.exists() and target.read_bytes()!=source.read_bytes():raise ValueError('IMMUTABLE_FORMAL_TRANSFER_CONFLICT')
   append(kind,source,target)
 for pair in pairs:append('plist',Path(pair['staged']),Path(pair['formal_path']),pair['original_sha256'])
 plan=dict(status='PREPARED_NOT_EXECUTED',canary_proof=str(proof_path),canary_proof_sha256=sha(proof_path.read_bytes()),run_id=proof['run_id'],product_sha256=proof['product_sha256'],phase='RETROSPECTIVE',natural_plan=False,
  candidate_api=build['candidate_api'],candidate_scheduler=build['candidate_scheduler'],api_manifest_sha256=build['api_manifest_sha256'],scheduler_manifest_sha256=build['scheduler_manifest_sha256'],
  config_target=str(config_target),config_sha256=sha(config_source.read_bytes()),capture_enabled=False,lease_auto_granted=False,plists=pairs,entries=entries,
  canonical_paths=[x['path'] for x in build['canonical_sync']],material_copy_policy='Exact bytes and relative refs; no reclassification as PIT or natural plan',formal_state_changed=False)
 pp=out/'operator-plan.json';pp.write_text(json.dumps(plan,indent=2)+'\n');print(json.dumps(dict(status=plan['status'],plan=str(pp),sha256=sha(pp.read_bytes()),entries=len(entries),run_id=plan['run_id'],formal_actions=0)))
if __name__=='__main__':main()
