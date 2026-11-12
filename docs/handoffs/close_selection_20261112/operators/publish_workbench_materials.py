"""One-batch original workbench execution-module material reference operator.
Default PREPARE only. Root executes the reviewed plan after Drive delivery.
Original owner.save serializer + stable A_LONG lock + exact latest CAS.
Adds node1 materials/evidence only; never sets a stage status or score/ABC row.
"""
import argparse,copy,datetime,fcntl,hashlib,importlib.util,json,os,pathlib,plistlib,sys
N=pathlib.Path(__file__).resolve().parents[1]
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
FOLDER='https://drive.google.com/drive/folders/1wF32W3_Vf0bydNo54XjQTzbQFYdY5eu1'
EXECUTION='/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/workbench_engineering_rectification_20261030/execution'
LOCK='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners/A_LONG.lock'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def ref(p):return dict(path=str(p),sha256=sha(p))
def read(p):return json.loads(pathlib.Path(p).read_bytes())
def expected(p):
 p=pathlib.Path(p)
 if p.is_symlink():raise ValueError('POINTER_SYMLINK')
 return sha(p)if p.exists()else None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');ap.add_argument('--plan-sha256');a=ap.parse_args();freeze=read(N/'RUN_FREEZE.json');env=freeze['env'];sys.path.insert(0,env['V4_APP_ROOT'])
 from ops import research_panel_daily_product as owner
 live=plistlib.load(open('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist','rb'))['EnvironmentVariables']
 if any(live.get(k)!=env[k]for k in ('V4_APP_ROOT','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256')):raise ValueError('MAIN_RUNTIME_IDENTITY_MOVED')
 api=plistlib.load(open('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist','rb'))['EnvironmentVariables'];binding_ref=dict(path=api['V4_WORKBENCH_HOST_BINDING'],sha256=api['V4_WORKBENCH_HOST_BINDING_SHA256']);binding=json.loads(owner.checked(binding_ref).read_bytes());assert binding['execution_root']==EXECUTION
 path=pathlib.Path(EXECUTION)/'2026-11-13/latest.json';planpath=N/'WORKBENCH_MATERIALS_PUBLICATION_PLAN.json';lock=pathlib.Path(LOCK);stat=lock.lstat();assert lock.is_file()and not lock.is_symlink()
 if not a.execute:
  before=expected(path);oldptr=read(path)if before else None;old={}
  if oldptr:
   assert oldptr['schema']=='V4_WORKBENCH_MODULE_COMMIT_V1'and oldptr['module']=='execution'and oldptr['date']=='2026-11-13'
   old=json.loads(owner.checked(oldptr['artifact']).read_bytes());receipt=json.loads(owner.checked(oldptr['receipt']).read_bytes());assert receipt['status']=='COMMITTED'and receipt['artifact']==oldptr['artifact']
  value=copy.deepcopy(old)if old else dict(source_date='2026-11-12',observation_date='2026-11-13',nodes={},**FLAGS)
  assert value['observation_date']=='2026-11-13'
  # This is a materials index. Missing future node statuses stay absent.
  node=value.setdefault('nodes',{}).setdefault('1',{});materials=list(node.get('materials',[]));material=dict(label='D12收盘研究：5809全市场重算、三折AI角色展示、人工复核A0',url=FOLDER,source_asof='2026-11-12T15:00:00+08:00',status='RESEARCH_MATERIAL_ONLY_NOT_BUY_OR_FUTURE_NODE_COMPLETION')
  if material not in materials:materials.append(material)
  node['materials']=materials;evidence=list(node.get('evidence',[]))
  for name in ('FINAL_RESULTS.json','NUMERIC_COMPLETION.json','FULL_UNIVERSE_COVERAGE.json','FIVE_OPPORTUNITY_COVERAGE.json','IDENTITY_RISK_OVERRIDES.json','SHORTLIST_IDENTITY_RISK_CHECK.json','ROOT_VISUAL_REVIEW.md'):
   r=ref(N/name)
   if r not in evidence:evidence.append(r)
  node['evidence']=evidence
  # Preserve every existing status/recorded_at/missing/future node field.
  expectedvalue=copy.deepcopy(old)
  if old:
   for k,v in old.items():
    if k!='nodes':assert value[k]==v
   for k,v in old.get('nodes',{}).items():
    if k!='1':assert value['nodes'][k]==v
   for k,v in old.get('nodes',{}).get('1',{}).items():
    if k not in ('materials','evidence'):assert node[k]==v
  stage=N/'workbench_materials_stage';stage.mkdir(exist_ok=True);artifact=owner.save(stage/'artifact.json',value)
  plan=dict(status='PREPARED_ONLY_REVIEW_REQUIRED',source_date='2026-11-12',observation_date='2026-11-13',target_latest=str(path),expected_latest_sha256=before,source_binding=binding_ref,owner=owner.reference(pathlib.Path(owner.__file__)),shared_owner_lock=dict(path=LOCK,device=stat.st_dev,inode=stat.st_ino),staged_artifact=artifact,preserve_existing=old,material_url=FOLDER,node_statuses_changed=False,original_formula_scores_changed=False,left_panel_ABC_changed=False,completion_claim='MATERIAL_REFERENCE_ONLY; NOT_FUTURE_NATURAL_EXECUTION',script_sha256=sha(__file__),**FLAGS);owner.save(planpath,plan);print(json.dumps(dict(status=plan['status'],plan=ref(planpath),target_latest=str(path),expected_latest_sha256=before)));return
 if a.plan_sha256!=sha(planpath):raise ValueError('PLAN_SHA_MISMATCH')
 plan=read(planpath);assert plan['script_sha256']==sha(__file__)and plan['target_latest']==str(path)and plan['source_binding']==binding_ref;owner.checked(plan['owner']);owner.checked(binding_ref)
 fd=os.open(LOCK,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);held=os.fstat(fd);current=os.stat(LOCK,follow_symlinks=False);assert (held.st_dev,held.st_ino)==(plan['shared_owner_lock']['device'],plan['shared_owner_lock']['inode'])==(current.st_dev,current.st_ino)
  if expected(path)!=plan['expected_latest_sha256']:raise ValueError('EXECUTION_LATEST_CAS_MOVED_REPREPARE_PRESERVING_OTHER_CHANGES')
  value=json.loads(owner.checked(plan['staged_artifact']).read_bytes())
  for evidence in value['nodes']['1']['evidence']:owner.checked(evidence)
  root=path.parent/owner.digest(value);artifact=owner.save(root/'artifact.json',value,immutable=True);receipt=owner.save(root/'receipt.json',dict(status='COMMITTED',artifact=artifact,claim=plan['completion_claim'],**FLAGS),immutable=True)
  if expected(path)!=plan['expected_latest_sha256']:raise ValueError('EXECUTION_LATEST_CAS_MOVED_BEFORE_POINTER')
  pointer=owner.save(path,dict(schema='V4_WORKBENCH_MODULE_COMMIT_V1',module='execution',date='2026-11-13',artifact=artifact,receipt=receipt,**FLAGS));result=dict(status='PUBLISHED_ORIGINAL_WORKBENCH_MATERIAL_REFERENCE_ONLY',pointer=pointer,artifact=artifact,receipt=receipt,source_date='2026-11-12',observation_date='2026-11-13',node_statuses_changed=False,original_scores_unchanged=True,left_ABC_unchanged=True,**FLAGS);owner.save(N/'WORKBENCH_MATERIALS_PUBLICATION_RECEIPT.json',result);print(json.dumps(result))
 finally:os.close(fd)
if __name__=='__main__':main()
