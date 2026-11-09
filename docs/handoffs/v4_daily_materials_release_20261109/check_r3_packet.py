from pathlib import Path
import os,json,sys,subprocess,plistlib,inspect
from ops.prepare_daily_materials_release import validate_dependency_packet,sha
P=Path(__file__).parent
packet=json.loads((P/'PACKET_FINAL_R3.json').read_text());result=validate_dependency_packet(packet);(P/'DEPENDENCY_CHECK_R3.json').write_text(json.dumps(result,indent=2)+'\n')
main=packet['services']['main'];cfg=plistlib.loads(Path(main['draft_plist']).read_bytes());env=dict(os.environ,**cfg['EnvironmentVariables']);env['PYTHONPATH']=main['app_root']+':'+env.get('PYTHONPATH','');env['V4_REPAIR_PACKET']=str(P/'PACKET_FINAL_R3.json')
code='''import os,json,inspect
from pathlib import Path
from ops import research_storage_retention as r,research_storage_governance as g
p=json.loads(Path(os.environ['V4_REPAIR_PACKET']).read_text());sub={x['live_plist']:x['draft_plist'] for x in p['services'].values()}
policy=g.configured_policy();pins=r.read_json(Path(policy['managed_pin_inventory']['path']))
checks=[]
for item in pins['source_bindings']:
 source=Path(sub.get(item['path'],item['path']));value=r._checked_file(source,item['sha256']);checks.append(dict(source_binding=item['path'],checked_path=str(source),sha256=value['sha256']))
consumers={name:inspect.getsource(fn) for name,fn in [('run_with_retention',r.run_with_retention),('configured_policy',g.configured_policy)]}
assert all('V4_RESEARCH_RETENTION_POLICY' in text and 'storage_phase2' not in text for text in consumers.values())
print(json.dumps(dict(status='PASS_ACTUAL_RETENTION_CHECKER_DRAFT_PLIST_SUBSTITUTIONS_ONLY',policy_path=os.environ['V4_RESEARCH_RETENTION_POLICY'],source_bindings=checks,authority_consumers={name:dict(module=fn.__module__,source_sha256=r.digest(Path(inspect.getfile(fn)))) for name,fn in [('run_with_retention',r.run_with_retention),('configured_policy',g.configured_policy)]},main_manifest_policy_note='Historical storage_phase2 provenance retained; runtime authority is explicit Main plist env path and SHA.'),ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],cwd=main['app_root'],env=env,capture_output=True,text=True,timeout=60)
(P/'POLICY_AUTHORITY_CHECK_R3.stderr').write_text(r.stderr);(P/'POLICY_AUTHORITY_CHECK_R3.json').write_text(r.stdout);assert r.returncode==0,r.stderr
print(json.dumps(dict(dependency=result,retention_checker=json.loads(r.stdout)['status'])))
