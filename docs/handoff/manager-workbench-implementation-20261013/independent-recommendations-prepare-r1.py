"""Exact API-only recommendation display delta. Dry-run by default; no scheduler actions."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,re,sys
H=Path(__file__).resolve().parent;W=H.parents[2];sys.path.insert(0,str(W));sys.path.insert(0,str(H));sys.dont_write_bytecode=True
import ops.api_release_integration as generic
from ops.api_release_integration import shared_api_release_lock,inventory_tree,inventory_digest,_base_binding,_diff_proof,build_integrated_app,verify_api_release_candidate
import operate_v7_cutover as operator
import operate_scheduled_lanes_v8 as bounded
from prepare_v7_operator import CANONICAL
API=operator.API
SOURCE_RECEIPT=H/'independent-recommendations-implementation-r1.json'
SOURCE_SHA='8eef2383cfb7ceb3181ee42dff9703b4ef78edef56ccee881ea3e44bcf47f195'
BASE_ROOT=H/'.tmp/us29-closure-v14-r2/manager-workbench-20261013-v14-api/app'
BASE_PLIST_SHA='ea0485de2f672ed6a126029ac486d52ba3fa50e4cbd6358cc5e3ac95e9eca481'
BASE_MANIFEST_SHA='92b42ed0c18a8f111953e195631a8005f6f9cf6b207557618ff99ce90c3d89f0'
SOURCES={'v4/manager_workbench/api.py','v4/manager_workbench/display_read.py',*[f'apps/web/src/manager-workbench/{name}' for name in ['api.ts','types.ts','useWorkbench.ts','Workbench.vue','display.ts']]}
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def guard_base(active,raw):
 if Path(active['app_root'])!=BASE_ROOT or sha(raw)!=BASE_PLIST_SHA or active['release_manifest_sha256']!=BASE_MANIFEST_SHA:raise ValueError('EXACT_API_ACTIVE_BASE_DRIFT')
def assets(dist):
 pending=[dist/'manager-selection/index.html'];payload={};seen=set()
 while pending:
  path=pending.pop()
  if path in seen:continue
  if path.is_symlink() or not path.is_relative_to(dist) or not path.is_file():raise ValueError('MANAGER_ASSET_CLOSURE_INVALID')
  seen.add(path);payload['apps/web/dist/'+path.relative_to(dist).as_posix()]=path.read_bytes()
  for filename in re.findall(r'[A-Za-z0-9_.-]+\.(?:js|css|woff2?|svg|png)',path.read_text()):
   dependency=dist/'assets'/filename
   if dependency.is_file() and dependency not in seen:pending.append(dependency)
 return payload

def write_manifest(candidate,result):
 app=candidate/'app';inv=inventory_tree(app)
 manifest=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',candidate=dict(root=str(candidate),app_root=str(app),release_id=candidate.name,module_role='gateway',module_contract_sha256=None),application_inventory=dict(entries=inv,aggregate_sha256=inventory_digest(inv),entry_count=len(inv)),api_integration=result,verification_gaps=['Formal API-only cutover/UI/natural slot NOT_RUN'])
 path=candidate/'release-manifest.json';dump(path,manifest);return path

def stage_plist(raw,app,manifest,manifest_sha):
 old=plistlib.loads(raw)
 if old.get('WorkingDirectory')!=str(BASE_ROOT):raise ValueError('API_WORKING_DIRECTORY_PREIMAGE_DRIFT')
 new=copy.deepcopy(old);new['WorkingDirectory']=str(app)
 fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID=app.parent.name,V35_RELEASE_MANIFEST_PATH=str(manifest),V35_RELEASE_MANIFEST_SHA256=manifest_sha)
 env=new.setdefault('EnvironmentVariables',{});env.update(fields)
 if 'PYTHONPATH' in env:env['PYTHONPATH']=env['PYTHONPATH'].replace(str(BASE_ROOT),str(app))
 args=[]
 for arg in new['ProgramArguments']:
  key=arg.split('=',1)[0] if '=' in arg else None
  args.append(key+'='+fields[key] if key in fields else arg.replace(str(BASE_ROOT),str(app)))
 new['ProgramArguments']=args
 return new

def target_root(entry):
 path=Path(entry['target'])
 if entry['kind']=='plist' and path==API:return operator.target_root_original(entry)
 if entry['kind']=='canonical' and path.is_relative_to(CANONICAL) and path.relative_to(CANONICAL).as_posix() in SOURCES:return operator.target_root_original(entry)
 raise ValueError('API_ONLY_TARGET_FORBIDDEN')
operator.target_root_original=operator.target_root

def validate(plan,mode):
 if plan['schema_version']!='manager_workbench.independent_recommendations.api_only.v1':raise ValueError('API_ONLY_PLAN_SCHEMA_INVALID')
 if len(plan['plists'])!=1 or plan['plists'][0]['role']!='api' or plan['plists'][0]['label']!='com.lexi.v35.api-only' or Path(plan['plists'][0]['formal_path'])!=API:raise ValueError('API_ONLY_SERVICE_SCOPE_REQUIRED')
 if {e['target'] for e in plan['entries']}!={str(CANONICAL/p) for p in SOURCES}|{str(API)} or len(plan['entries'])!=len(SOURCES)+1:raise ValueError('API_ONLY_EXACT_TARGET_SET_REQUIRED')
 folder=Path(plan['candidate_api']).parent.parent
 if not folder.is_relative_to(H/'.tmp') or folder.is_symlink():raise ValueError('API_ONLY_CANDIDATE_PATH_INVALID')
 if plan['source_receipt_sha256']!=SOURCE_SHA or sha(SOURCE_RECEIPT.read_bytes())!=SOURCE_SHA:raise ValueError('FROZEN_SOURCE_RECEIPT_DRIFT')
 for e in plan['entries']:
  target_root(e)
  for field in ['source','backup']:
   p=Path(e[field])
   if p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()):raise ValueError('API_ONLY_SUPPORT_FILE_PATH_INVALID')
  if sha(Path(e['source']).read_bytes())!=e['after_sha256'] or sha(Path(e['backup']).read_bytes())!=e['before_sha256']:raise ValueError('API_ONLY_SUPPORT_FILE_DRIFT')
  expected=e['before_sha256'] if mode=='apply' else e['after_sha256']
  if operator.current_sha(Path(e['target']))!=expected:raise ValueError('OPERATOR_TARGET_PARALLEL_DRIFT:'+e['target'])
 app=Path(plan['candidate_api']);manifest=app.parent/'release-manifest.json'
 if sha(manifest.read_bytes())!=plan['api_manifest_sha256'] or inventory_tree(app)!=json.loads(manifest.read_text())['application_inventory']['entries']:raise ValueError('API_ONLY_CANDIDATE_DRIFT')


def prepare(out,review,review_sha):
 if out.exists() or not out.is_relative_to(H/'.tmp'):raise ValueError('NEW_HANDOFF_TMP_REQUIRED')
 if not review.is_relative_to(H) or sha(review.read_bytes())!=review_sha:raise ValueError('EXACT_INDEPENDENT_REVIEW_REQUIRED')
 if sha(SOURCE_RECEIPT.read_bytes())!=SOURCE_SHA:raise ValueError('SOURCE_RECEIPT_DRIFT')
 receipt=json.loads(SOURCE_RECEIPT.read_text());files=[e for e in receipt['scope'] if e['path'] in SOURCES]
 if {e['path'] for e in files}!=SOURCES:raise ValueError('EXACT_SEVEN_SOURCE_SCOPE_REQUIRED')
 with shared_api_release_lock(API) as lease:
  active=generic.read_active_release(API);araw=API.read_bytes();guard_base(active,araw);before_inventory=inventory_tree(BASE_ROOT);payload={}
  for e in files:
   rel=e['path'];raw=(W/rel).read_bytes()
   if sha(raw)!=e['after_sha256']:raise ValueError('FROZEN_SOURCE_DRIFT:'+rel)
   if sha((BASE_ROOT/rel).read_bytes())!=e['before_sha256'] or sha((CANONICAL/rel).read_bytes())!=e['canonical_before_sha256']:raise ValueError('SOURCE_PREIMAGE_DRIFT:'+rel)
   payload[rel]=raw
  payload.update(assets(H/'.tmp/independent-recommendations-web-build-r1'))
  payload={p:b for p,b in payload.items() if not (BASE_ROOT/p).exists() or (BASE_ROOT/p).read_bytes()!=b}
  out.mkdir(parents=True);src=out/'delta-source';src.mkdir();entries=[]
  for rel,raw in sorted(payload.items()):
   p=src/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);old=(BASE_ROOT/rel).read_bytes() if (BASE_ROOT/rel).exists() else None
   diff,hunks=_diff_proof(old,raw) if old is not None else (None,None)
   entries.append(dict(path=rel,before_sha256=sha(old) if old is not None else None,after_sha256=sha(raw),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
  delta=out/'api-delta.json';dump(delta,dict(schema_version=generic.DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries))
  candidate=out/'manager-workbench-20261013-independent-recommendations-api';candidate.mkdir()
  result=build_integrated_app(active_api_plist_path=API,source_root=src,candidate_root=candidate,delta_receipt_path=delta,explicit_untracked_paths=[e['path'] for e in entries if e['before_sha256'] is None])
  manifest=write_manifest(candidate,result);manifest_sha=sha(manifest.read_bytes());app=candidate/'app';after_inventory=inventory_tree(app)
  if {e['path']:e for e in before_inventory if e['path'] not in payload}!={e['path']:e for e in after_inventory if e['path'] not in payload}:raise ValueError('API_NON_DELTA_DRIFT')
  verify_api_release_candidate(candidate_root=candidate,active_api_plist_path=API,expected_manifest_sha256=manifest_sha,lock_lease=lease,require_shared_lock=lease is not None)
  plists=out/'plists';plists.mkdir();original=plists/'api-original.plist';staged=plists/'api-independent.plist';original.write_bytes(araw);new=stage_plist(araw,app,manifest,manifest_sha)
  staged.write_bytes(plistlib.dumps(new,sort_keys=False));plan_entries=[];backup=out/'rollback';backup.mkdir()
  for e in files:
   rel=e['path'];old=CANONICAL/rel;save=backup/rel;save.parent.mkdir(parents=True,exist_ok=True);save.write_bytes(old.read_bytes());plan_entries.append(dict(kind='canonical',target=str(old),source=str(src/rel),before_sha256=sha(save.read_bytes()),after_sha256=e['after_sha256'],backup=str(save)))
  plan_entries.append(dict(kind='plist',target=str(API),source=str(staged),before_sha256=sha(araw),after_sha256=sha(staged.read_bytes()),backup=str(original)))
  pair=dict(role='api',label=new['Label'],formal_path=str(API),original=str(original),original_sha256=sha(araw),staged=str(staged),staged_sha256=sha(staged.read_bytes()))
  plan=dict(schema_version='manager_workbench.independent_recommendations.api_only.v1',status='PREPARED_NOT_EXECUTED',candidate_api=str(app),api_manifest_sha256=manifest_sha,plists=[pair],entries=plan_entries,source_receipt_sha256=SOURCE_SHA,review_receipt=dict(path=str(review),sha256=review_sha),base=_base_binding(active),api_plist_sha256=sha(araw))
  if API.read_bytes()!=araw or inventory_tree(BASE_ROOT)!=before_inventory:raise ValueError('API_PARALLEL_DRIFT')
  validate(plan,'apply');path=out/'operator-plan.json';dump(path,plan)
  report=dict(status='PREPARED_DRY_RUN_PASS',plan=str(path),plan_sha256=sha(path.read_bytes()),candidate_api=str(app),api_manifest_sha256=manifest_sha,base=plan['base'],api_plist_sha256=sha(araw),api_delta_paths=sorted(payload),canonical_sync_paths=sorted(SOURCES),non_delta_preserved=True,scheduler_writes=0,config_writes=0,snapshot_writes=0,services_changed=False,source_receipt_sha256=SOURCE_SHA,independent_review=plan['review_receipt'],operator_helper_sha256=sha(Path(__file__).read_bytes()))
  dump(out/'prepared-receipt.json',report);print(json.dumps(report,ensure_ascii=False))

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True);q=s.add_parser('prepare');q.add_argument('--out',required=True);q.add_argument('--review-receipt',required=True);q.add_argument('--review-sha256',required=True)
 q=s.add_parser('operate');q.add_argument('--plan',required=True);q.add_argument('--plan-sha256',required=True);q.add_argument('--mode',choices=['apply','rollback'],default='apply');q.add_argument('--execute',action='store_true');a=p.parse_args()
 if a.command=='prepare':return prepare(Path(a.out).resolve(),Path(a.review_receipt).resolve(),a.review_sha256)
 path=Path(a.plan).resolve(strict=True)
 if not path.is_relative_to(H/'.tmp') or sha(path.read_bytes())!=a.plan_sha256:raise ValueError('EXACT_PREPARED_PLAN_REQUIRED')
 plan=json.loads(path.read_text());validate(plan,a.mode)
 operator.validate=validate;operator.target_root=target_root;operator.launch=bounded.launch
 if not a.execute:return print(json.dumps(dict(status='DRY_RUN_PASS',mode=a.mode,plan_sha256=a.plan_sha256,services_changed=False)))
 from datetime import datetime,timezone
 journal=path.parent/('api-only-'+a.mode+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-journal.json');bounded.AUDIT_PATH=journal.with_suffix('.launch-events.jsonl')
 operator.execute(plan,a.mode,journal);print(journal)
if __name__=='__main__':main()
