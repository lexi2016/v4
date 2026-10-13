"""Prepare both launch plists and exact rollback originals. Never activates."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,sys
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from verify_v7_candidate import verify,API,SCHED
sha=lambda b:hashlib.sha256(b).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manager-config',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 config=Path(a.manager_config).resolve(strict=True);output=Path(a.output).resolve()
 if not output.is_relative_to(HERE):raise ValueError('HANDOFF_STAGE_OUTPUT_ONLY')
 value=json.loads(config.read_text())
 from v4.manager_workbench.config import WorkbenchConfig
 WorkbenchConfig.model_validate(value)
 if value.get('capture_enabled') or value.get('capture_lease_token'):raise ValueError('STAGE_REQUIRES_CAPTURE_DISABLED_NO_TOKEN')
 proof=verify();r=json.loads((HERE/'deployment-deltas/isolated-candidate-build-v7-receipt.json').read_text())
 output.mkdir(parents=True,exist_ok=False);items=[]
 for role,path in [('api',API),('scheduler',SCHED)]:
  raw=path.read_bytes();old=plistlib.loads(raw);new=copy.deepcopy(old);app=Path(r['candidate_'+role]);manifest=app.parent/'release-manifest.json'
  fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID='manager-workbench-20261013-v7-'+role,
    V35_RELEASE_MANIFEST_PATH=str(manifest),V35_RELEASE_MANIFEST_SHA256=sha(manifest.read_bytes()),V4_MANAGER_WORKBENCH_CONFIG_PATH=str(config))
  oldapp=r['base']['api' if role=='api' else 'scheduler']['app_root']
  env=new.setdefault('EnvironmentVariables',{})
  # API launch uses /usr/bin/env assignments; scheduler uses EnvironmentVariables.
  args=new['ProgramArguments'];assignment_keys=set()
  for i,arg in enumerate(args):
   if '=' in arg and not arg.startswith('--'):
    key,text=arg.split('=',1);assignment_keys.add(key)
    if key in fields:args[i]=key+'='+fields[key]
    elif key=='PYTHONPATH':args[i]=key+'='+text.replace(oldapp,str(app))
   elif role=='scheduler' and arg==oldapp+'/ops/launch_v35_macos_scheduler.sh':args[i]=str(app/'ops/launch_v35_macos_scheduler.sh')
  for key,text in fields.items():
   if key not in assignment_keys:env[key]=text
  if 'PYTHONPATH' in env:env['PYTHONPATH']=env['PYTHONPATH'].replace(oldapp,str(app))
  if new.get('WorkingDirectory')==oldapp:new['WorkingDirectory']=str(app)
  original=output/(role+'-original.plist');staged=output/(role+'-v7.plist');original.write_bytes(raw);staged.write_bytes(plistlib.dumps(new,sort_keys=False))
  items.append(dict(role=role,label=old['Label'],formal_path=str(path),original=str(original),original_sha256=sha(raw),staged=str(staged),staged_sha256=sha(staged.read_bytes())))
 result=dict(status='STAGED_NOT_ACTIVATED',config_path=str(config),config_sha256=sha(config.read_bytes()),capture_enabled=False,lease_auto_granted=False,
  plist_pairs=items,verification=proof,whole_rollback='Restore BOTH original plists after draining/revoking new capture; original services and old binding bytes were never rewritten.',services_changed=False,formal_state_changed=False)
 (output/'cutover-stage-receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
