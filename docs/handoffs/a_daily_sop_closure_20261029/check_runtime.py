"""Read-only final SOP check against Root's exact activation receipt, no controls."""
from pathlib import Path
import argparse,hashlib,json,os,plistlib,re,subprocess,urllib.parse,urllib.request
from datetime import datetime,timezone

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(ref):
 p=Path(ref['path'])
 if sha(p)!=ref['sha256']:raise ValueError('ACTIVATION_PIN_DRIFT:'+str(p))
 return p
def loopback_json(url):
 if urllib.parse.urlsplit(url).hostname!='127.0.0.1':raise ValueError('PROOF_NOT_LOOPBACK')
 with urllib.request.urlopen(url,timeout=30) as response:return json.load(response)
def loaded_observation(spec):
 """Capture only argv/PID/cwd, never process environments."""
 result=subprocess.run(['/bin/launchctl','print',f'gui/{os.getuid()}/'+spec['label']],capture_output=True,text=True,check=True)
 text=result.stdout;match=re.search(r'(?m)^\s*arguments = \{\s*(.*?)^\s*\}',text,re.S)
 args=[x.strip() for x in match.group(1).splitlines() if x.strip()] if match else []
 cwd=re.search(r'(?m)^\s*working directory = (.+)$',text);pid=re.search(r'(?m)^\s*pid = (\d+)\s*$',text)
 value=dict(loaded_argv=args,loaded_cwd=cwd.group(1).strip() if cwd else None,pid=int(pid.group(1)) if pid else None)
 if value['pid']:
  actual=subprocess.run(['/usr/sbin/lsof','-a','-p',str(value['pid']),'-d','cwd','-Fn'],capture_output=True,text=True,check=True)
  paths=[x[1:] for x in actual.stdout.splitlines() if x.startswith('n')]
  command=subprocess.run(['/bin/ps','-p',str(value['pid']),'-o','command='],capture_output=True,text=True,check=True).stdout.strip()
  value.update(cwd=paths[0] if len(paths)==1 else None,command=command)
 return value
def verify_loaded(e,observations,proof):
 for role,spec in e['loaded'].items():
  actual=observations[role]
  if actual['loaded_argv']!=spec['argv'] or actual['loaded_cwd']!=spec['cwd']:raise ValueError('LOADED_CONFIG_DRIFT:'+role)
  pid=actual['pid']
  if pid is None and role=='graph':continue
  if type(pid) is not int or pid<=0 or pid in e['forbidden_pre_control_pids']:raise ValueError('LOADED_PID_INVALID_OR_OLD:'+role)
  if actual.get('cwd')!=spec['cwd'] or not actual.get('command','').startswith(spec['process_executable']+' '):raise ValueError('ACTUAL_PROCESS_ROOT_OR_EXECUTABLE_DRIFT:'+role)
  if any(text not in actual['command'] for text in spec['command_required']):raise ValueError('ACTUAL_PROCESS_ARGUMENT_DRIFT:'+role)
 runtime=proof.get('runtime_binding',{});api=proof.get('proof_runtime',{})
 if (proof.get('schema_version')!='v4.runtime_graph_authority.v1' or proof.get('config_sha256')!=e['graph_config']['sha256']
     or proof.get('authority_identity')!=e['expected_graph_main'] or proof.get('business_date')!=e['target_date']
     or runtime.get('status')!='VERIFIED' or runtime.get('current_runtime_verified') is not True
     or runtime.get('pid')!=observations['main']['pid'] or runtime.get('launcher')!=e['main_launcher']
     or api.get('pid')!=observations['api']['pid'] or api.get('module_file')!=e['api_proof_module']['path']
     or api.get('module_sha256')!=e['api_proof_module']['sha256']):raise ValueError('ACTUAL_API_MAIN_GRAPH_PROOF_DRIFT')
 age=(datetime.now(timezone.utc)-datetime.fromisoformat(proof['observed_at'])).total_seconds()
 if not -5<=age<=30:raise ValueError('ACTUAL_RUNTIME_PROOF_STALE')
 return {role:{'pid':v['pid'],'cwd':v.get('cwd',v['loaded_cwd']),'loaded_argv':v['loaded_argv']} for role,v in observations.items()}
def verify_getter(payload,expected):
 if payload.get('status')!='READY' or not payload.get('rows'):raise ValueError('API_GETTER_NOT_READY')
 if any(payload.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise ValueError('API_SAFETY_FLAGS')
 identity=payload.get('identity',{})
 if any(identity.get(k)!=v for k,v in expected.items()):raise ValueError('API_GETTER_IDENTITY_DRIFT')
 if not {'generation_id','input_sha256','artifact_sha256','asof_date','verification_basis','historical_PIT'}.issubset(expected):raise ValueError('GETTER_EXPECTED_IDENTITY_INCOMPLETE')
 return identity
def main():
 a=argparse.ArgumentParser();a.add_argument('--expected',type=Path,required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args();e=json.loads(args.expected.read_text());checks={};errors=[]
 try:
  if e['schema']!='a_daily_sop_activation_binding.v1':raise ValueError('EXPECTED_BINDING_SCHEMA')
  main=plistlib.loads(pin(e['main_plist']).read_bytes());api=plistlib.loads(pin(e['api_plist']).read_bytes());graph=plistlib.loads(pin(e['graph_plist']).read_bytes())
  if main['Label']!='com.lexi.v4.scheduler' or main['WorkingDirectory']!=e['main_app_root']:raise ValueError('MAIN_OWNER_OR_ROOT_MISMATCH')
  env=main['EnvironmentVariables'];manifest=pin({'path':env['V4_RELEASE_MANIFEST_PATH'],'sha256':env['V4_RELEASE_MANIFEST_SHA256']});m=json.loads(manifest.read_text())
  if m['app_root']!=e['main_app_root']:raise ValueError('MAIN_MANIFEST_ROOT_MISMATCH')
  for row in m['application_inventory']['entries']:
   if row['kind']=='file' and sha(Path(m['app_root'])/row['path'])!=row['sha256']:raise ValueError('MAIN_INVENTORY_DRIFT:'+row['path'])
  am=json.loads(pin(e['api_manifest']).read_text())
  if am['app_root']!=e['api_app_root'] or api['WorkingDirectory']!=e['api_app_root']:raise ValueError('API_ROOT_MISMATCH')
  for row in am['application_inventory']['entries']:
   if row['kind']=='file' and sha(Path(am['app_root'])/row['path'])!=row['sha256']:raise ValueError('API_INVENTORY_DRIFT:'+row['path'])
  assets=json.loads(pin(e['static_manifest']).read_text())['files']
  if len(assets)!=455:raise ValueError('STATIC_ASSET_COUNT_DRIFT')
  for row in assets:
   if sha(Path(e['static_root'])/row['path'])!=row['sha256']:raise ValueError('STATIC_ASSET_SHA_DRIFT:'+row['path'])
  catalog=json.loads((Path(m['app_root'])/'contracts/runtime_workloads.json').read_text());lane=next(x for x in catalog['workloads'] if x['workload_id']=='research_panel_daily_a')
  if lane['slots']!=['1610']:raise ValueError('A_SLOT_NOT_1610')
  gpath=pin(e['graph_config']);g=json.loads(gpath.read_text())
  if api['EnvironmentVariables']['V4_RUNTIME_GRAPH_CONFIG']!=str(gpath) or str(gpath)!=graph['ProgramArguments'][graph['ProgramArguments'].index('--config')+1]:raise ValueError('GRAPH_CONSUMER_BINDING_MISMATCH')
  if (g['main']['app_root']!=e['main_app_root'] or g['main']['catalog_sha256']!=sha(Path(m['app_root'])/'contracts/runtime_workloads.json') or g['main']['registry_sha256']!=sha(Path(m['app_root'])/'infrastructure/scheduling/executor_registry.py')):raise ValueError('GRAPH_MAIN_IDENTITY_MISMATCH')
  for name in ('MAIN','MANAGER_WORKBENCH','ZSXQ_PDF'):
   entry=g['entry_sources'][name]
   if not Path(entry['module_file']).is_relative_to(Path(m['app_root'])) or sha(entry['module_file'])!=entry['module_sha256']:raise ValueError('GRAPH_ENTRY_SOURCE_MISMATCH:'+name)
  acceptance=json.loads(pin(e['convention_acceptance']).read_text())
  if acceptance['code_binding']!=e['old_code_binding'] or len(acceptance['approved_tuple_entries'])!=1 or acceptance['approved_tuple_entries'][0]['code_binding']!=e['new_code_binding'] or acceptance['approved_tuple_entries'][0]['status']!='PASS':raise ValueError('TWO_TUPLE_ACCEPTANCE_MISMATCH')
  code="import os,sys; sys.path.insert(0,sys.argv[1]); from pathlib import Path; from ops.research_panel_qfq import pointer_ready,input_path; p=Path(sys.argv[2]); print(pointer_ready(p,int(sys.argv[3]),input_path(p.parent.parent)))"
  child=subprocess.run([e['python'],'-I','-B','-c',code,e['main_app_root'],env['V4_RESEARCH_PANEL_A_SELECTOR_POINTER'],e['target_date']],capture_output=True,text=True,env=__import__('os').environ|env,check=True)
  if child.stdout.strip()!='True':raise ValueError('ACTUAL_CURRENT_GENERATION_NOT_READY')
  observations={role:loaded_observation(spec) for role,spec in e['loaded'].items()}
  proof=loopback_json(e['runtime_proof_url']);actual_runtime=verify_loaded(e,observations,proof)
  responses=[]
  for url in e['api_getters']:
   parsed=urllib.parse.urlsplit(url)
   if parsed.scheme!='http' or parsed.hostname!='127.0.0.1':raise ValueError('GETTER_NOT_LOOPBACK')
   payload=loopback_json(url);code=urllib.parse.parse_qs(parsed.query)['ts_code'][0]
   identity=verify_getter(payload,e['getter_expected_identity'][code])
   responses.append({'url':url,'rows':len(payload['rows']),'identity':identity})
  checks=dict(main_inventory=True,api_inventory=True,static_assets_unchanged=455,A_slot='1610',exact_graph_binding=True,two_tuple_acceptance=True,current_generation_ready=True,actual_runtime=actual_runtime,api_getters=responses)
 except Exception as exc:errors.append(str(exc))
 result={'status':'PASS_ACTIVATED' if not errors else 'FAIL','checks':checks,'errors':errors,'natural_1610_verified':False,'natural_note':'This readback cannot establish a new natural scheduled run; Root must bind the next dated receipt separately.','RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':result['status'],'errors':errors}));raise SystemExit(0 if not errors else 2)
if __name__=='__main__':main()
