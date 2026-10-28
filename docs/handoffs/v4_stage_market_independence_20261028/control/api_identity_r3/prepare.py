from pathlib import Path
import hashlib,json,plistlib,sys,subprocess,importlib.util,types
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
spec=importlib.util.spec_from_file_location('r7_identity_base',BASE/'main_api_controller.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
assert b.sha(b.read(BASE/'main_api_controller.py'))=='44c65823ed11d6819939b3ac10388a74c3c879379a5b615249b170f81239c80e'
def main():
 if (HERE/'PLAN.json').exists():raise RuntimeError('NO_OVERWRITE_PLAN')
 path=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist');raw=b.pin(path,'7820f02d0726c4f0dc00d0b163c3a1e1b660f633793eecdf623616b895da32e6');old=b'V35_RELEASE_ID=mac-panel-r5-rebound-20261028-r1-api';new=b'V35_RELEASE_ID=stage-market-independence-20261028-r7-api';assert raw.count(old)==1;after=raw.replace(old,new);before=b.plistlib.loads(raw);target=b.plistlib.loads(after);diff=[i for i,(x,y) in enumerate(zip(before['ProgramArguments'],target['ProgramArguments'])) if x!=y];assert len(diff)==1 and len(before['ProgramArguments'])==len(target['ProgramArguments']);before['ProgramArguments'][diff[0]]=target['ProgramArguments'][diff[0]];assert before==target
 (HERE/'api.before.plist').write_bytes(raw);(HERE/'api.after.plist').write_bytes(after);md=b.metadata.snapshot(path)
 row=dict(role='api',label='com.lexi.v35.api-only',plist=str(path),before_file=str(HERE/'api.before.plist'),after_file=str(HERE/'api.after.plist'),before_sha256=b.sha(raw),after_sha256=b.sha(after),plist_metadata=md,plist_metadata_sha256=b.metadata.digest(md),old_app_root=target['WorkingDirectory'],new_app_root=target['WorkingDirectory'])
 release_root=Path(target['WorkingDirectory']).parent;manifest=release_root/'release-manifest.json';m=json.loads(b.pin(manifest,'54b82f90fa583db180c7c71f466e74937f5b1b563f727018e1382502239bd715'));release={k:m[k] for k in ('release_id','app_root')};release.update(role='api',manifest=str(manifest),manifest_sha256=b.sha(b.read(manifest)))
 pins=[]
 for label in ('com.lexi.v35.scheduler','com.lexi.stage-center.scheduler','com.lexi.stage-center.a-opening-precapture','com.lexi.v35.runtime-graph'):
  p=Path('/Users/lexi/Library/LaunchAgents')/(label+'.plist');pins.append(dict(path=str(p),sha256=b.sha(b.read(p))))
 pins.append(dict(path=str(manifest),sha256=release['manifest_sha256']))
 prior=b.load(BASE/'PLAN_REVIEW_ONLY_R7.json');g=prior['owner_guard'];identity=b.Live(prior).identity
 h=b.load(BASE.parent/'deployment_safety_20261028/EXECUTION_HANDOFF_R7_5fbaa125bafa4355b5af0f4135478b40.json')
 for x in h['data_pins']:b.pin(x['path'],x['sha256'])
 for x in h['data_stats']:
  s=Path(x['path']).stat();assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==(x['device'],x['inode'],x['size'],x['mtime_ns'])
 inv={x['path']:x['sha256'] for x in m['app_files']};frontend={'index_sha256':inv['apps/web/dist/index.html'],'api_release_id':release['release_id'],'api_manifest_sha256':release['manifest_sha256']}
 plan=dict(schema='v4.api_identity_r3.v1',operations=[row],releases=[release],owner_guard=g,static_protected_pins=pins,drain_source_pins=[],workbench_configs=[],protected_main_identity=identity(66933),expected_api_identity=identity(67002),expected_original_pids={'api':67002},data_pins=h['data_pins'],data_stats=h['data_stats'],guard_seconds=604800,guard_program_sha256=b.sha(b.read('/bin/sleep')),base_source_sha256=b.sha(b.read(BASE/'main_api_controller.py')),single_changed_argument_index=diff[0],frontend_expected=frontend,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 assert plan['protected_main_identity'] and plan['expected_api_identity'];b.save(HERE/'PLAN.json',plan);print(json.dumps({'after_sha256':row['after_sha256'],'argument_index':diff[0],'api_identity':plan['expected_api_identity'],'data_pins':len(h['data_pins']),'data_stats':len(h['data_stats'])}))
if __name__=='__main__':main()
