"""Read-only final SOP check against Root's exact activation receipt, no controls."""
from pathlib import Path
import argparse,hashlib,json,plistlib,subprocess,urllib.parse,urllib.request

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(ref):
 p=Path(ref['path'])
 if sha(p)!=ref['sha256']:raise ValueError('ACTIVATION_PIN_DRIFT:'+str(p))
 return p
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
  responses=[]
  for url in e['api_getters']:
   parsed=urllib.parse.urlsplit(url)
   if parsed.scheme!='http' or parsed.hostname!='127.0.0.1':raise ValueError('GETTER_NOT_LOOPBACK')
   with urllib.request.urlopen(url,timeout=30) as r:payload=json.load(r)
   if payload.get('status')!='READY' or not payload.get('rows'):raise ValueError('API_GETTER_NOT_READY')
   if any(payload.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise ValueError('API_SAFETY_FLAGS')
   responses.append({'url':url,'rows':len(payload['rows']),'identity':payload.get('identity')})
  checks=dict(main_inventory=True,api_inventory=True,static_assets_unchanged=455,A_slot='1610',exact_graph_binding=True,two_tuple_acceptance=True,current_generation_ready=True,api_getters=responses)
 except Exception as exc:errors.append(str(exc))
 result={'status':'PASS_ACTIVATED' if not errors else 'FAIL','checks':checks,'errors':errors,'natural_1610_verified':False,'natural_note':'This readback cannot establish a new natural scheduled run; Root must bind the next dated receipt separately.','RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':result['status'],'errors':errors}));raise SystemExit(0 if not errors else 2)
if __name__=='__main__':main()
