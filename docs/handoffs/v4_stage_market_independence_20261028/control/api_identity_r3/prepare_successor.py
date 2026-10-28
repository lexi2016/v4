"""Case-only immutable successor, identical app bytes; no live writes/imports."""
from pathlib import Path
import copy,hashlib,json,os,plistlib,shutil,stat,sys
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import api_only_controller as c
BASE_ID='stage-market-independence-20261028-r7-api';NEW_ID=BASE_ID+'-identity-r3'
def main():
 original=c.load(HERE/'PLAN.json');out=HERE/'candidate'/NEW_ID;app=out/'app'
 if out.exists():raise RuntimeError('NO_CANDIDATE_OVERWRITE')
 old=Path(original['releases'][0]['app_root']).parent;raw=c.pin(old/'release-manifest.json','54b82f90fa583db180c7c71f466e74937f5b1b563f727018e1382502239bd715');m=json.loads(raw);intended=old.parent/NEW_ID
 assert shutil.disk_usage(HERE).free>2*sum(x['bytes'] for x in m['app_files'])+1024**3
 app.mkdir(parents=True)
 rows=m['application_inventory']['entries'];by={r['path']:r for r in rows}
 for item in m['app_files']:
  rel=item['path'];source=old/'app'/rel;data=c.pin(source,item['sha256']);p=app/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(int(by[rel]['mode'],8));assert c.sha(p.read_bytes())==item['sha256']
 assert {str(p.relative_to(app)) for p in app.rglob('*') if p.is_file()}==set(by)
 new=copy.deepcopy(m);new.update(schema_version='v4.release_candidate.v1',release_id=NEW_ID,app_root=str(intended/'app'),candidate_app_root=str(intended/'app'),baseline_app=str(old/'app'),baseline_release_manifest=str(old/'release-manifest.json'),baseline_release_manifest_sha256=c.sha(raw),status='SEALED_NOT_ACTIVATED',activation_performed=False)
 new['candidate']={'root':str(intended),'app_root':str(intended/'app'),'release_id':NEW_ID,'module_role':'gateway'}
 new['api_identity_metadata_repair']={'scope':'Only releaseidentitymetadata; app_files/application_inventory/files/externaldependencies unchanged','parent_manifest_sha256':c.sha(raw),'new_business_source_bytes':0,'canonical_manifest_verifier_requires_successor_root':True}
 c.save(out/'release-manifest.json',new);newsha=c.sha(c.read(out/'release-manifest.json'))
 # Preserve exactly the original one-token-only failed candidate/control before replacement.
 retained=HERE/'one_token_only_retained';retained.mkdir(exist_ok=False)
 for name in ('PLAN.json','api.after.plist','prepare.py','api_only_controller.py','test_api_identity.py','EFFECTIVE_ENV_DIAGNOSTIC.json'):
  shutil.copy2(HERE/name,retained/name)
 row=original['operations'][0];b=plistlib.loads(c.pin(row['before_file'],row['before_sha256']));oldroot=str(old);newroot=str(intended)
 def rewrite(v):
  if isinstance(v,str):return v.replace(oldroot,newroot).replace('54b82f90fa583db180c7c71f466e74937f5b1b563f727018e1382502239bd715',newsha).replace('V35_RELEASE_ID=mac-panel-r5-rebound-20261028-r1-api','V35_RELEASE_ID='+NEW_ID)
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 a=rewrite(b);a['EnvironmentVariables']['V35_RELEASE_ID']=NEW_ID;after=plistlib.dumps(a,sort_keys=False);(HERE/'api.after.plist').write_bytes(after);row.update(after_sha256=c.sha(after),new_app_root=str(intended/'app'))
 original['schema']='v4.api_identity_successor_r3.v1';original['releases']=[dict(role='api',release_id=NEW_ID,app_root=str(intended/'app'),manifest=str(intended/'release-manifest.json'),manifest_sha256=newsha,candidate_app=str(app),candidate_manifest=str(out/'release-manifest.json'))];original.pop('single_changed_argument_index');original['frontend_expected']={'api_release_id':NEW_ID,'api_manifest_sha256':newsha,'index_sha256':'35747eeb38ba56528cfee1592bd5d191d532baab2119a1183509b2fe3e76eef4','bundle_sha256':'8d189f73b483b60c5768324076825c099d8a24f178b66ae4d820a0319f2fe2be'};original['identity_baseline_release_id']=BASE_ID
 c.save(HERE/'PLAN.json',original)
 c.save(HERE/'SUCCESSOR_CANDIDATE_SEAL.json',{'status':'EXACT_UNACTIVATED_CASE_CANDIDATE','candidate':str(out),'intended':str(intended),'file_count':len(rows),'total_app_bytes':sum(x['bytes'] for x in m['app_files']),'unchanged_app_files':new['app_files']==m['app_files'],'unchanged_application_inventory':new['application_inventory']==m['application_inventory'],'unchanged_files_map':new['files']==m['files'],'manifest_sha256':newsha,'after_plist_sha256':row['after_sha256'],'source_changes':0,'live_actions':0})
 print(json.dumps(c.load(HERE/'SUCCESSOR_CANDIDATE_SEAL.json')))
if __name__=='__main__':main()
