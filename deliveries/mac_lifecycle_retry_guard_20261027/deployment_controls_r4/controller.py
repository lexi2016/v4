"""Fixed lifecycle deployment. Root only; no business/provider calls.

Reuses original stage/CAS/identity and kernel locks. No schema adapter,
launchctl debug, process kill, task cancellation or lock-file deletion.
"""
from pathlib import Path
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import argparse, fcntl, hashlib, stat, importlib.util, json, os, plistlib, re, shutil, subprocess, sys, time

D=Path(__file__).resolve().parent
LABELS={'api':'com.lexi.v35.api-only','main':'com.lexi.v35.scheduler','collector':'com.lexi.v35.runtime-graph'}
TZ=ZoneInfo('Asia/Shanghai')
PRESTAGE_R1_JOURNAL_SHA='cdf0f99f3376e2381dc8cdfff9db12f31c8a55455979035a284f077414772fd0'
MATERIALIZED_R3_JOURNAL_SHA='9d34fc477f0a787bb6cc0b38122ffa7b7c5a40749831047b2113318005d00951'
class Stop(RuntimeError):pass

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def pin(p,h):
    if Path(p).is_symlink() or Path(p).resolve()!=Path(p) or sha(p)!=h:raise Stop('PIN_DRIFT:'+str(p))
def approve(review_path,review_sha):
    pin(review_path,review_sha);r=load(review_path)
    if r.get('verdict')!='PASS' or r.get('deployment_plan_sha256')!=sha(D/'PLAN.json') or r.get('controller_sha256')!=sha(__file__) or r.get('case_manifest_sha256')!=sha(D/'CASE_MANIFEST.json'):raise Stop('SCOPED_DELTA_REVIEW_REQUIRED')
    for relative,expected in load(D/'CASE_MANIFEST.json')['files'].items():
        p=D/relative
        if not p.resolve().is_relative_to(D) or p.is_symlink():raise Stop('CASE_PATH_UNSAFE')
        pin(p,expected)

def import_file(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def cycle_idle(records,minute):
    """Original dual-lane completion is diagnostic; actual locks/owner are gates."""
    cycles=[r for r in records if r.get('status')=='DAEMON_DISPATCH_CYCLE']
    if not cycles:return False
    r=cycles[-1]
    return r.get('minute')==minute and type(r.get('active_children')) is int and r['active_children']==0 and type(r.get('queued_slots')) is int and r['queued_slots']==0


def descendants(pid,rows):
    seen=set();todo={pid}
    while todo:
        todo={n for n,r in rows.items() if r['ppid'] in todo and n not in seen};seen.update(todo)
    return seen


class Journal:
    def __init__(self):
        self.path=D/'ROOT_EXECUTION.jsonl'
        if self.path.exists():raise Stop('PRIOR_EXECUTION_PRESERVED_NO_BLIND_RETRY')
        self.stream=self.path.open('x');self.action_counts={}
    def record(self,event,**fields):
        x={'at':datetime.now(TZ).isoformat(),'event':event,**fields};self.stream.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n');self.stream.flush();os.fsync(self.stream.fileno());print(json.dumps(x,ensure_ascii=False),flush=True)
    def command(self,args):
        key=tuple(args)
        self.action_counts[key]=self.action_counts.get(key,0)+1
        self.record('COMMAND_INTENT',args=args,invocation_count=self.action_counts[key])
        r=subprocess.run(args,capture_output=True,text=True,timeout=30)
        self.record('COMMAND_RESULT',args=args,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if r.returncode:raise Stop('COMMAND_NONZERO_OUTCOME_RECONCILE_NO_RETRY:'+str(args))
        return r


def validate_prestage_resume_r1_files(binding,plan):
    if binding.get('scope')!='FIXED_PRE_SERVICE_STAGE_FAILURE_R1_ONLY':raise Stop('PRESTAGE_RESUME_SCOPE_INVALID')
    prior=D/'ROOT_EXECUTION.jsonl';new=D/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl'
    if binding['prior_journal']!={'path':str(prior),'sha256':PRESTAGE_R1_JOURNAL_SHA} or binding['new_journal_path']!=str(new):raise Stop('PRESTAGE_RESUME_FIXED_JOURNAL_BINDING_INVALID')
    if os.path.lexists(new):raise Stop('PRESTAGE_RESUME_ALREADY_ATTEMPTED_NO_RETRY')
    for key in ('prior_journal','failure','accepted_prior_review','snapshot_map'):
        row=binding[key];pin(row['path'],row['sha256'])
    events=[json.loads(line) for line in prior.read_text().splitlines()]
    if len(events)!=3 or events[0].get('event')!='ROOT_DEPLOYMENT_STARTED' or set(events[0])!={'at','event','plan_sha256','review_sha256'}:raise Stop('PRIOR_JOURNAL_NOT_EXACT_PRE_SERVICE_THREE_EVENTS')
    identity=binding['prior_identity'];review=load(binding['accepted_prior_review']['path'])
    if review.get('verdict')!='PASS' or any(review.get(key)!=value for key,value in identity.items()):raise Stop('PRIOR_REVIEW_IDENTITY_MISMATCH')
    if events[0]['plan_sha256']!=identity['deployment_plan_sha256'] or events[0]['review_sha256']!=binding['accepted_prior_review']['sha256']:raise Stop('PRIOR_START_BINDING_MISMATCH')
    failure=load(binding['failure']['path'])
    if failure.get('status')!='FAILED_PRE_SERVICE_OLD_TREE_DECLARED_SYMLINK_REJECTED' or failure.get('journal_sha256')!=PRESTAGE_R1_JOURNAL_SHA or failure.get('exit_code')!=1 or failure.get('service_actions_in_journal')!=[] or not str(failure.get('error','')).startswith('Stop: UNEXPECTED_SYMLINK:'):raise Stop('PRIOR_FAILURE_NOT_KNOWN_PRE_SERVICE_LINK_FAILURE')
    targets=[plan['lifecycle_component']['target'],*(meta['release_root'] for meta in plan['components'].values())]
    if len(targets)!=4 or len(set(targets))!=4 or failure.get('new_release_roots')!={target:False for target in targets}:raise Stop('PRIOR_FAILURE_TARGET_PROOF_INVALID')
    for target in targets:
        if os.path.lexists(target):raise Stop('PRESTAGE_RESUME_TARGET_ALREADY_EXISTS:'+target)
    if len(binding['before_http'])!=2:raise Stop('PRESTAGE_RESUME_HTTP_REFS_INVALID')
    before={}
    for event,row,code in zip(events[1:],binding['before_http'],('601198.SH','601059.SH')):
        path=D/('ROOT_HTTP_before_'+code+'.json')
        if set(event)!={'at','code','event','path','phase','sha256'} or event.get('event')!='ROOT_BOUNDED_HTTP_READ' or event.get('phase')!='before' or event.get('code')!=code or event.get('path')!=str(path) or row!={'code':code,'path':str(path),'sha256':event.get('sha256')}:raise Stop('PRIOR_JOURNAL_HTTP_SEQUENCE_OR_PATH_INVALID')
        pin(path,row['sha256']);value=load(path)
        if value.get('ts_code')!=code or value.get('start_date')!='20261019' or value.get('end_date')!='20261026':raise Stop('PRIOR_HTTP_WINDOW_OR_SYMBOL_MISMATCH')
        before[code]=value
    for row in plan['operations']:
        pin(row['plist'],row['before_sha256'])
        if failure.get('plist_sha256',{}).get(row['label'])!=row['before_sha256']:raise Stop('PRIOR_FAILURE_BEFORE_PLIST_PROOF_INVALID')
    return before


class PrestageResumeR1Journal(Journal):
    def __init__(self,binding):
        # Only the fixed, validated pre-service attempt may use this new file.
        pin(D/'ROOT_EXECUTION.jsonl',PRESTAGE_R1_JOURNAL_SHA)
        self.path=D/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl'
        if os.path.lexists(self.path):raise Stop('PRESTAGE_RESUME_ALREADY_ATTEMPTED_NO_RETRY')
        self.stream=self.path.open('x');self.action_counts={}


def validate_materialized_r3_files(binding,plan):
    first=D/'ROOT_EXECUTION.jsonl';prior=D/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl';new=D/'ROOT_EXECUTION_MATERIALIZED_RESUME_R3.jsonl'
    if binding.get('scope')!='FIXED_FULLY_MATERIALIZED_R3_PROBE_FAILURE_ONLY' or binding['first_journal']!={'path':str(first),'sha256':PRESTAGE_R1_JOURNAL_SHA} or binding['materialized_journal']!={'path':str(prior),'sha256':MATERIALIZED_R3_JOURNAL_SHA} or binding['new_journal_path']!=str(new):raise Stop('MATERIALIZED_RESUME_FIXED_BINDING_INVALID')
    if os.path.lexists(new):raise Stop('MATERIALIZED_RESUME_ALREADY_ATTEMPTED_NO_RETRY')
    for key in ('first_journal','materialized_journal','failure','accepted_prior_review','snapshot_map','corrected_probe','corrected_probe_result','corrected_probe_stderr'):
        row=binding[key];pin(row['path'],row['sha256'])
    events=[json.loads(line) for line in prior.read_text().splitlines()]
    names=['ROOT_PRESTAGE_RESUME_R1_STARTED','PRIOR_BEFORE_HTTP_REUSED_NO_REFETCH','ORIGINAL_GRAPH_ACTIVE_TREE_VERIFIED_NO_SCHEMA_ADAPTER','ORIGINAL_API_DISPATCHER_MATERIALIZED','MATERIALIZED_ORIGINAL_LOADER_PROBE']
    if len(events)!=5 or [e.get('event') for e in events]!=names:raise Stop('MATERIALIZED_PRIOR_JOURNAL_NOT_EXACT_FIVE_PRE_SERVICE_EVENTS')
    fields=[{'at','event','plan_sha256','pre_service_only_proof','prior_failure','prior_journal_sha256','prior_review','review_sha256'},{'at','codes','event','prior_journal_sha256'},{'at','event'},{'at','event','exit_code','stderr','stdout'},{'at','event','exit_code','stderr','stdout'}]
    if any(set(e)!=allowed for e,allowed in zip(events,fields)):raise Stop('MATERIALIZED_PRIOR_EVENT_FIELDS_INVALID')
    review=load(binding['accepted_prior_review']['path'])
    if review.get('verdict')!='PASS' or any(review.get(k)!=v for k,v in binding['prior_identity'].items()):raise Stop('MATERIALIZED_PRIOR_REVIEW_MISMATCH')
    if events[0]['plan_sha256']!=binding['prior_identity']['deployment_plan_sha256'] or events[0]['review_sha256']!=binding['accepted_prior_review']['sha256'] or events[0]['pre_service_only_proof'] is not True or events[0]['prior_journal_sha256']!=PRESTAGE_R1_JOURNAL_SHA or events[1]['prior_journal_sha256']!=PRESTAGE_R1_JOURNAL_SHA or events[1]['codes']!=['601198.SH','601059.SH']:raise Stop('MATERIALIZED_PRIOR_CHAIN_MISMATCH')
    for key in ('prior_failure','prior_review'):
        row=events[0][key];pin(row['path'],row['sha256'])
    if events[3]['exit_code']!=0 or events[3]['stderr']!='':raise Stop('MATERIALIZED_PRIOR_DISPATCHER_NOT_PASS')
    meta=plan['components']['api'];root=Path(meta['release_root']);dispatcher=json.loads(events[3]['stdout'])
    if dispatcher!={'app_root':str(root/'app'),'release_id':root.name,'release_manifest_path':str(root/'release-manifest.json'),'release_manifest_sha256':meta['sha256']}:raise Stop('MATERIALIZED_PRIOR_DISPATCHER_IDENTITY_MISMATCH')
    if events[4]['exit_code']!=1 or events[4]['stdout']!='' or "KeyError: 'ops._a_share_daily_sync_parts.sync_workflow'" not in events[4]['stderr']:raise Stop('MATERIALIZED_PRIOR_PROBE_NOT_KNOWN_LAZY_FAILURE')
    failure=load(binding['failure']['path'])
    targets={plan['lifecycle_component']['target']:plan['lifecycle_component']['manifest_sha256'],**{m['release_root']:m['sha256'] for m in plan['components'].values()}}
    if failure.get('status')!='FAILED_MATERIALIZED_ENTRY_PROBE_PRE_SERVICE' or failure.get('prior_journal_sha256')!=MATERIALIZED_R3_JOURNAL_SHA or failure.get('service_actions')!=0 or failure.get('error')!='KeyError: ops._a_share_daily_sync_parts.sync_workflow' or failure.get('event_names')!=names or failure.get('new_release_roots')!={path:True for path in targets} or failure.get('materialized_manifest_sha256')!={Path(path).name:h for path,h in targets.items()}:raise Stop('MATERIALIZED_FAILURE_PROOF_INVALID')
    for path,digest in targets.items():pin(Path(path)/'release-manifest.json',digest)
    first_events=[json.loads(line) for line in first.read_text().splitlines()]
    if len(first_events)!=3 or first_events[0].get('event')!='ROOT_DEPLOYMENT_STARTED':raise Stop('MATERIALIZED_FIRST_JOURNAL_INVALID')
    before={}
    if len(binding['before_http'])!=2:raise Stop('MATERIALIZED_BEFORE_HTTP_REFS_INVALID')
    for event,row,code in zip(first_events[1:],binding['before_http'],('601198.SH','601059.SH')):
        path=D/('ROOT_HTTP_before_'+code+'.json')
        if event.get('event')!='ROOT_BOUNDED_HTTP_READ' or event.get('phase')!='before' or row!={'code':code,'path':str(path),'sha256':event.get('sha256')} or event.get('code')!=code or event.get('path')!=str(path):raise Stop('MATERIALIZED_BEFORE_HTTP_BINDING_INVALID')
        pin(path,row['sha256']);before[code]=load(path)
    probe=load(binding['corrected_probe_result']['path'])
    component=Path(plan['lifecycle_component']['target'])/'a_sync';main=Path(plan['components']['main']['release_root'])/'app'
    expected={'status':'MATERIALIZED_ORIGINAL_STRICT_LOADER_PASS','caller':str(main/'ops/macos_research_panel_daily_authority.py'),'entry':str(component/'app/ops/a_share_daily_sync.py'),'facade':str(component/'component/ops/a_share_daily_sync.py'),'workflow':str(component/'component/ops/_a_share_daily_sync_parts/sync_workflow.py'),'seed_path':str(component/'component/seed-evidence-descriptor.json'),'pins':15,'component_manifest_sha256':'67d3abe86e6035a4b2461941b07a57aee096e6be05c95d32f498c8e90fe7c1ef','provider_calls':0,'network_calls':0,'business_execution':False}
    if probe!=expected or Path(binding['corrected_probe_stderr']['path']).read_bytes()!=b'' or binding['corrected_probe']['path']!=str(D/'probe_materialized_entry.py'):raise Stop('MATERIALIZED_CORRECTED_PROBE_PROOF_INVALID')
    for row in plan['operations']:
        pin(row['plist'],row['before_sha256'])
        if failure.get('before_plist_sha256',{}).get(row['label'])!=row['before_sha256']:raise Stop('MATERIALIZED_BEFORE_PLIST_PROOF_INVALID')
    return before


class MaterializedResumeR3Journal(Journal):
    def __init__(self,binding):
        pin(D/'ROOT_EXECUTION.jsonl',PRESTAGE_R1_JOURNAL_SHA);pin(D/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl',MATERIALIZED_R3_JOURNAL_SHA)
        self.path=D/'ROOT_EXECUTION_MATERIALIZED_RESUME_R3.jsonl'
        if os.path.lexists(self.path):raise Stop('MATERIALIZED_RESUME_ALREADY_ATTEMPTED_NO_RETRY')
        self.stream=self.path.open('x');self.action_counts={}


class Capsule:
    def __init__(self,plan):
        self.p=plan;self.j=None;self.attempted_service_actions=set();self.graph_fd=None;self.graph_disabled_by_this_activation=False;self.forward_first_action_pending=True;self.action_progress={name:{} for name in LABELS}
        for row in load(D/'ORIGINAL_FUNCTIONS.json'):pin(row['path'],row['sha256'])
        self.op=import_file('lifecycle_original_graph_operator',plan['operator'])
        sys.path.insert(0,str(Path(plan['guard_recipe']).parent));self.guard=import_file('lifecycle_original_main_guard',plan['guard_recipe'])
        sys.path.insert(0,plan['old_api_app']);from ops import api_release_integration as integration
        if Path(integration.__file__).resolve()!=Path(plan['old_api_app'])/'ops/api_release_integration.py':raise Stop('API_HELPER_SHADOW')
        self.a=integration
        pin(plan['api_module_contract']['path'],plan['api_module_contract']['sha256'])
        self.a.MODULE_CONTRACT_PATH=Path(plan['api_module_contract']['path'])
        self.ledger_module=import_file('lifecycle_original_main_ledger',Path(plan['old_main_app'])/'infrastructure/scheduling/execution_ledger.py')
        self.ledger=self.ledger_module.ExecutionLedger(Path(plan['main_guard_parameters']['ledger_root']))
        self.g=self.guard.LiveOps(plan['main_guard_parameters'])
        pdf=import_file('lifecycle_original_main_pdf_reader',Path(plan['old_main_app'])/'infrastructure/zsxq_pdf_ingestion.py')
        self.g.pdf_reader=pdf.pending_pdf_tasks
        if set(r['component'] for r in plan['operations'])!=set(LABELS):raise Stop('FIXED_THREE_COMPONENTS_ONLY')
        if plan['protected_deploy_windows']!=[['0924','0927']]:raise Stop('OWNER_NATURAL_ACCEPTANCE_WINDOW_NOT_PRESERVED')
        if plan.get('minimum_switch_margin_seconds')!=300:raise Stop('FIXED_FIVE_MINUTE_DEPLOY_MARGIN_REQUIRED')
        expected_component=str(Path(plan['old_main_app']).parents[1]/'mac-lifecycle-retry-component-20261027-r1')
        if plan['lifecycle_component']['target']!=expected_component:raise Stop('COMPONENT_TARGET_SCOPE')
        for component,label in LABELS.items():
            row=self.op.op(plan,component)
            if row['label']!=label or row['plist']!=str(Path.home()/'Library/LaunchAgents'/(label+'.plist')):raise Stop('FIXED_LABEL_SCOPE')
        if plan['components']['api']['release_root']!=str(Path(plan['old_api_app']).parents[1]/'mac-lifecycle-notes-21-api-20261027-r2'):raise Stop('API_TARGET_SCOPE')
        if plan['components']['main']['release_root']!=str(Path(plan['old_main_app']).parents[1]/'mac-lifecycle-main-binding-20261027-r1'):raise Stop('MAIN_TARGET_SCOPE')

    def compare(self,after=False):
        for row in self.p['operations']:pin(row['plist'],row['after_sha256'] if after else row['before_sha256'])
        for row in self.p['base_manifests']:pin(row['path'],row['sha256'])
        for row in self.p['owner_projection_inputs']:pin(row['path'],row['sha256'])

    def exact_inventory(self,root,expected,declared_symlinks):
        root=Path(root);actual={};links={}
        def relative(value):
            p=Path(value)
            if not isinstance(value,str) or not value or p.is_absolute() or '..' in p.parts or p.as_posix()!=value:raise Stop('INVENTORY_RELATIVE_PATH_INVALID')
            return value
        wanted={relative(r['path']):(r.get('bytes',r.get('size')),r['sha256']) for r in expected}
        declared={relative(r['path']):r['target'] for r in declared_symlinks}
        if len(wanted)!=len(expected) or len(declared)!=len(declared_symlinks) or set(wanted)&set(declared):raise Stop('INVENTORY_DUPLICATE_OR_TYPE_CONFLICT')
        if any(not isinstance(target,str) or not target for target in declared.values()):raise Stop('DECLARED_LINK_TARGET_INVALID')
        # lstat and fd-relative opens do not traverse symlinks. Declared links
        # are opaque dependencies: only their original type/value is checked.
        def walk(fd,prefix=''):
            with os.scandir(fd) as entries:
                for entry in entries:
                    name=entry.name;rel=prefix+name;info=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        target=os.readlink(name,dir_fd=fd)
                        if rel not in declared or target!=declared[rel]:raise Stop('UNDECLARED_OR_CHANGED_SYMLINK:'+rel)
                        links[rel]=target
                    elif stat.S_ISDIR(info.st_mode):
                        child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                        try:walk(child,rel+'/')
                        finally:os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        leaf=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
                        try:
                            opened=os.fstat(leaf)
                            if not stat.S_ISREG(opened.st_mode):raise Stop('INVENTORY_FILE_TYPE_DRIFT:'+rel)
                            h=hashlib.sha256()
                            while block:=os.read(leaf,1024*1024):h.update(block)
                            actual[rel]=(opened.st_size,h.hexdigest())
                        finally:os.close(leaf)
                    else:raise Stop('INVENTORY_UNSUPPORTED_OBJECT:'+rel)
        fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:walk(fd)
        finally:os.close(fd)
        if actual!=wanted or links!=declared:raise Stop('INVENTORY_SET_OR_BYTES_OR_LINK_TYPE_DRIFT:'+str(root))

    def stage(self):
        self.compare()
        baseline=load(self.p['old_graph_plan'])
        for name in LABELS:
            self.op.verify_release(baseline,name)
            oldmeta=baseline['components'][name];oldroot=Path(oldmeta['release_root']);oldmanifest=load(oldroot/'release-manifest.json')
            self.exact_inventory(oldroot/'app',oldmanifest['app_files'],oldmanifest['symlinks'])
        self.j.record('ORIGINAL_GRAPH_ACTIVE_TREE_VERIFIED_NO_SCHEMA_ADAPTER')
        comp=self.p['lifecycle_component'];source=Path(comp['source']);target=Path(comp['target'])
        pin(source/'release-manifest.json',comp['manifest_sha256']);m=load(source/'release-manifest.json')
        expected={k:v for k,v in m['files'].items()}
        def check(root):
            actual={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and p.name!='release-manifest.json'}
            if any(p.is_symlink() for p in root.rglob('*')) or actual!=expected:raise Stop('COMPONENT_EXACT_SET_DRIFT')
            pin(root/'release-manifest.json',comp['manifest_sha256'])
        check(source)
        if target.exists():check(target)
        else:
            temp=target.with_name('.'+target.name+'.staging-'+str(os.getpid()));shutil.copytree(source,temp);check(temp)
            if target.exists():raise Stop('COMPONENT_TARGET_APPEARED')
            temp.rename(target)
        self.op.stage(self.p)
        for name in LABELS:
            self.op.verify_release(self.p,name)
            meta=self.p['components'][name];m=load(Path(meta['release_root'])/'release-manifest.json')
            self.exact_inventory(Path(meta['release_root'])/'app',m['app_files'],m['symlinks'])
        self.dispatcher()
        self.materialized_entry_probe()
        self.compare()
        self.j.record('STAGED_ALL_IMMUTABLE_RELEASES_VERIFIED')

    def materialized_entry_probe(self):
        r=subprocess.run([sys.executable,'-B',str(D/'probe_materialized_entry.py'),self.p['components']['main']['release_root']+'/app',self.p['lifecycle_component']['target']],cwd=self.p['components']['main']['release_root']+'/app',env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1'),capture_output=True,text=True)
        self.j.record('MATERIALIZED_ORIGINAL_LOADER_PROBE',exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if r.returncode:raise Stop('MATERIALIZED_ORIGINAL_LOADER_FAILED_NO_RELOAD')

    def dispatcher(self):
        meta=self.p['components']['api'];root=Path(meta['release_root']);m=load(root/'release-manifest.json')
        inv=m['application_inventory']
        if m['schema_version']!='v4.release_candidate.v1' or inv['entry_count']!=len(inv['entries']):raise Stop('STANDARD_INVENTORY_COUNT_REQUIRED')
        env=dict(os.environ,V35_APP_ROOT=str(root/'app'),V35_RELEASE_ID=root.name,V35_RELEASE_MANIFEST_PATH=str(root/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=meta['sha256'],PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
        code="from infrastructure.scheduling.dispatcher import validate_release_identity;import json;print(json.dumps(validate_release_identity(),sort_keys=True))"
        r=subprocess.run([sys.executable,'-B','-c',code],cwd=root/'app',env=env,text=True,capture_output=True)
        self.j.record('ORIGINAL_API_DISPATCHER_MATERIALIZED',exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if r.returncode:raise Stop('MATERIALIZED_DISPATCHER_FAILED')

    def deployment_boundary(self,now=None):
        now=now or datetime.now(TZ)
        margin=self.p['minimum_switch_margin_seconds']
        for start,end in self.p['protected_deploy_windows']:
            begin=now.replace(hour=int(start[:2]),minute=int(start[2:]),second=0,microsecond=0)
            finish=now.replace(hour=int(end[:2]),minute=int(end[2:]),second=0,microsecond=0)+timedelta(minutes=1)
            if begin-timedelta(seconds=margin)<=now<finish:
                return {'ready':False,'reason':'PROTECTED_OR_NEAR_WINDOW','observed_at':now.isoformat(),'protected_start':begin.isoformat(),'protected_end_exclusive':finish.isoformat(),'minimum_switch_margin_seconds':margin}
        return {'ready':True,'observed_at':now.isoformat(),'minimum_switch_margin_seconds':margin}

    def progress(self,name,action,state):
        if not hasattr(self,'action_progress'):self.action_progress={key:{} for key in LABELS}
        self.action_progress[name][action]=state
        self.j.record('SERVICE_PROGRESS',component=name,action=action,state=state)

    def idle(self,old):
        self.g.check_old(old)
        boundary=self.deployment_boundary()
        if not boundary['ready']:return boundary
        parameters=self.p['main_guard_parameters']
        pin(parameters['manager_config'],parameters['manager_config_sha256'])
        if load(parameters['manager_config']).get('capture_enabled') is not False:raise Stop('ANNOUNCEMENT_CAPTURE_NOT_EXCLUDED_NO_CONFIG_MUTATION')
        rows=self.g.processes()
        if descendants(old['pid'],rows):return {'ready':False,'reason':'DAEMON_DESCENDANTS_ACTIVE'}
        if any(r['pid']!=old['pid'] and r['pgid']==rows[old['pid']]['pgid'] for r in rows.values()):return {'ready':False,'reason':'MAIN_PROCESS_GROUP_ACTIVE'}
        producers=[r['pid'] for r in rows.values() if any(s in r['command'] for s in ['-m ops.run_zsxq_hourly_delta','-m ops.zsxq_pdf_ingestion','--pdf-queue-tick'])]
        if producers:return {'ready':False,'reason':'PDF_PRODUCER_ACTIVE','pids':producers}
        claims=self.g.claims(old['pid'])
        if claims['unfinished']:return {'ready':False,'reason':'UNFINISHED_DAEMON_CLAIM'}
        if not self.g.pdf_empty()['ready']:return {'ready':False,'reason':'PDF_PENDING'}
        path=Path(self.p['main_guard_parameters']['log_path'])
        with path.open('rb') as f:f.seek(max(0,path.stat().st_size-4*1024*1024));raw=f.read()
        records=[]
        for line in raw.splitlines():
            try:v=json.loads(line)
            except (ValueError,UnicodeDecodeError):continue
            if isinstance(v,dict):records.append(v)
        minute=datetime.now(TZ).strftime('%Y-%m-%dT%H:%M')
        if not cycle_idle(records,minute):return {'ready':False,'reason':'CURRENT_DUAL_LANE_CYCLE_NOT_IDLE'}
        self.g.check_old(old)
        if descendants(old['pid'],self.g.processes()):return {'ready':False,'reason':'DESCENDANTS_CHANGED'}
        if self.op.label_state(LABELS['collector']) not in (None,0):return {'ready':False,'reason':'GRAPH_COLLECTOR_NATURAL_DRAIN'}
        return {'ready':True,'minute':minute,'claim_epoch':claims['epoch'],'old':old}

    @contextmanager
    def natural_idle_lanes(self,old):
        while True:
            boundary=self.deployment_boundary()
            if not boundary['ready']:
                self.j.record('WAIT_PROTECTED_OR_NEAR_WINDOW_WITHOUT_BUSINESS_GUARDS',boundary=boundary)
                time.sleep(5);continue
            fds=[]
            try:
                for lane in ('A_LONG','DEFAULT'):
                    fd=self.ledger.try_acquire_scheduler_lane(lane)
                    if fd is None:break
                    fds.append(fd)
                if len(fds)==2:
                    proof=self.idle(old)
                    if proof['ready']:
                        self.j.record('NATURAL_IDLE_BOTH_STABLE_LANES_HELD',proof=proof,fd_identity=[list(os.fstat(fd)[:3]) for fd in fds]);yield;return
                else:proof={'reason':'ORIGINAL_STABLE_LANE_BUSY'}
                self.j.record('WAIT_NATURAL_IDLE_NO_SERVICE_ACTION',reason=proof['reason'])
            finally:
                for fd in fds:os.close(fd)  # close descriptor only; never unlink/unlock inode
            time.sleep(5)

    def try_graph_collector_lock(self):
        row=self.p['graph_collector_lock'];fd=os.open(row['path'],os.O_RDWR|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if (st.st_dev,st.st_ino)!=(row['device'],row['inode']):raise Stop('GRAPH_COLLECTOR_LOCK_INODE_DRIFT')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:os.close(fd);return False
            self.graph_fd=fd;return True
        except BaseException:os.close(fd);raise

    def release_graph_collector_lock(self):
        if self.graph_fd is not None:os.close(self.graph_fd);self.graph_fd=None

    @contextmanager
    def original_main_control_owner(self):
        owner=self.p['original_main_control_owner']
        while True:
            pin(owner['marker'],owner['marker_sha256'])
            marker=load(owner['marker'])
            if marker.get('active') is not False or marker.get('phase')!='DONE':raise Stop('PRIOR_MAIN_CONTROL_OPERATION_NOT_CLOSED')
            fd=os.open(owner['lock_path'],os.O_RDWR|os.O_NOFOLLOW)
            try:
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino)!=(owner['device'],owner['inode']):raise Stop('ORIGINAL_MAIN_CONTROL_LOCK_INODE_DRIFT')
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    self.j.record('WAIT_ORIGINAL_MAIN_CONTROL_OWNER_BUSY_NO_SERVICE_ACTION')
                else:
                    pin(owner['marker'],owner['marker_sha256'])
                    self.j.record('ORIGINAL_MAIN_CONTROL_OWNER_LOCK_HELD',device=info.st_dev,inode=info.st_ino)
                    yield;return
            finally:os.close(fd)
            time.sleep(5)

    @contextmanager
    def all_original_guards(self,old):
        # Do not hold API submission/release locks throughout a healthy long
        # scheduler wait. Once naturally idle, acquire API guards and recheck.
        while True:
            yielded=False
            with self.natural_idle_lanes(old):
                try:
                    with ExitStack() as stack:
                        activity=stack.enter_context(self.a.announcement_flash_cutover_guard(Path(self.p['workbench_root']),timeout_seconds=10))
                        stack.enter_context(self.a.shared_api_release_lock(Path(self.op.op(self.p,'api')['plist']),timeout_seconds=2))
                        if self.try_graph_collector_lock():
                            stack.callback(self.release_graph_collector_lock)
                            proof=self.idle(old)
                        else:proof={'ready':False,'reason':'GRAPH_COLLECTOR_LOCK_BUSY'}
                        if proof['ready']:
                            self.j.record('ALL_ORIGINAL_GUARDS_HELD',announcement=activity,idle=proof)
                            yielded=True;yield;return
                        self.j.record('WAIT_BOUNDARY_REVOKED_RELEASE_GUARDS',reason=proof['reason'])
                except ValueError as error:
                    if yielded:raise
                    # Only known busy conditions are healthy waits. Schema,
                    # ownership and all other errors remain hard stops.
                    if str(error) not in {'API_RELEASE_SHARED_LOCK_BUSY','API_RELEASE_ANNOUNCEMENT_SUBMIT_LOCK_BUSY','API_RELEASE_ANNOUNCEMENT_ACTIVITY_BUSY'}:raise
                    self.j.record('WAIT_ORIGINAL_API_GUARD_BUSY_NO_SERVICE_ACTION',reason=str(error))
            time.sleep(5)

    def bootout(self,component):
        row=self.op.op(self.p,component);state=self.op.label_state(row['label'])
        if state is None:return
        if component=='collector' and state!=0:raise Stop('GRAPH_COLLECTOR_BECAME_BUSY')
        identity=self.g.identity(state) if state else None
        token=('bootout',component,sha(row['plist']),json.dumps(identity,sort_keys=True))
        if token in self.attempted_service_actions:raise Stop('SERVICE_ACTION_ALREADY_ATTEMPTED_RECONCILE_NO_REPEAT')
        if getattr(self,'forward_first_action_pending',False):
            boundary=self.deployment_boundary()
            if not boundary['ready']:
                self.j.record('LAST_SERVICE_BOUNDARY_REVOKED_NO_ACTION',boundary=boundary)
                raise Stop('DEPLOYMENT_WINDOW_REVOKED_NO_SERVICE_ACTION')
            self.forward_first_action_pending=False
        self.attempted_service_actions.add(token)
        self.progress(component,'bootout','INTENT')
        self.j.command(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/'+row['label']])
        if self.op.label_state(row['label']) is not None:raise Stop('SERVICE_NOT_UNLOADED')
        self.progress(component,'bootout','CONFIRMED_UNLOADED')
        if component=='api':
            r=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:8873','-sTCP:LISTEN'],capture_output=True,text=True)
            self.j.record('API_PORT_EMPTY_CHECK',exit_code=r.returncode,stdout=r.stdout)
            if r.stdout.strip():raise Stop('API_PORT_STILL_LISTENING')

    def bootstrap(self,component):
        row=self.op.op(self.p,component)
        if self.op.label_state(row['label']) is not None:raise Stop('BOOTSTRAP_TARGET_ALREADY_LOADED')
        token=('bootstrap',component,sha(row['plist']))
        if token in self.attempted_service_actions:raise Stop('BOOTSTRAP_ALREADY_ATTEMPTED_RECONCILE_NO_REPEAT')
        self.attempted_service_actions.add(token)
        self.progress(component,'bootstrap','INTENT')
        self.j.command(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),row['plist']])
        self.progress(component,'bootstrap','COMMAND_SUCCEEDED')

    def verify(self):
        self.compare(after=True);new=self.g.new_binding()
        if new is None:raise Stop('MAIN_BINDING_STARTING_OR_UNCONFIRMED')
        # Original LiveOps verifies full Main package, native interpreter and loaded env.
        entry=self.p['lifecycle_component']['target']+'/a_sync/app/ops/a_share_daily_sync.py'
        text=self.g.service()['text']
        values=re.findall(r'^\s*V35_RESEARCH_PANEL_A_SYNC_SCRIPT\s*=>\s*(.*?)\s*$',text,re.M)
        if not values or set(values)!={entry}:raise Stop('MAIN_LOADED_LIFECYCLE_ENTRY_MISMATCH')
        from urllib.request import urlopen
        with urlopen('http://127.0.0.1:8873/api/v1/runs/date-list?date=20261026',timeout=30) as r:runtime=json.loads(r.read())['runtime_identity']
        if runtime.get('release_id')!=Path(self.p['components']['api']['release_root']).name or runtime.get('manifest_sha256')!=self.p['components']['api']['sha256'] or runtime.get('status')!='MANIFEST_EXECUTION_FILES_VERIFIED':raise Stop('API_STRONG_RUNTIME_IDENTITY_FAILED')
        obs=self.op.observe_api(self.p);self.op.validate_api_observation(self.p,obs)
        self.j.record('ACTUAL_API_MAIN_GRAPH_IDENTITY_VERIFIED_LANES_STILL_HELD',main=new,api_runtime=runtime,graph_observation=obs,lane_inhibition='EXPECTED_PERSISTED_LANE_OWNER_ACTIVE_UNTIL_RELEASE')

    def history_http(self,code,phase):
        from urllib.request import urlopen
        from urllib.parse import urlencode
        query=urlencode({'ts_code':code,'start_date':'20261019','end_date':'20261026','formula_version':'ACTIVE_MA_USER_20261021_V1'})
        with urlopen('http://127.0.0.1:8873/api/v3/research/a-share/history?'+query,timeout=30) as response:raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise Stop('BOUNDED_HISTORY_RESPONSE_LIMIT')
        path=D/('ROOT_HTTP_'+phase+'_'+code+'.json')
        with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        self.j.record('ROOT_BOUNDED_HTTP_READ',code=code,phase=phase,path=str(path),sha256=sha(path))
        return json.loads(raw)

    def bounded_http(self):
        for code in ('601198.SH','601059.SH'):
            actual=self.history_http(code,'after');before=self.baseline_http[code]
            if actual.get('status')!='CANNOT_CONFIRM' or actual.get('rows')!=[]:raise Stop('LIFECYCLE_HTTP_MUST_NOT_ADMIT_OR_SYNTHESIZE')
            previous=before.get('cannot_confirm');current=actual.get('cannot_confirm')
            if not isinstance(previous,list) or not previous or current[:len(previous)]!=previous or len(current)!=len(previous)+1 or '2026-10-19' not in current[-1]:raise Stop('LIFECYCLE_HTTP_OLD_ERROR_OR_NEW_FACT_MISMATCH')
        actual=self.history_http('000523.SZ','after')
        expected=load(self.p['saved_000523_envelope'])
        if actual!=expected:raise Stop('FUTU000523_ACTUAL_SAVED_ENVELOPE_MISMATCH')
        self.j.record('ROOT_BOUNDED_THREE_HTTP_PASS',scope='Two new broker notes preserve old error/empty rows; accepted000523 six-day full envelope exact; no recomputation')

    def graph_disabled(self):
        r=subprocess.run(['/bin/launchctl','print-disabled','gui/'+str(os.getuid())],capture_output=True,text=True)
        if r.returncode:raise Stop('GRAPH_DISABLED_STATE_UNCONFIRMED')
        found=re.search(r'"com\.lexi\.v35\.runtime-graph"\s*=>\s*(true|false)',r.stdout)
        return bool(found and found.group(1)=='true')

    def activate_original_graph(self):
        self.release_graph_collector_lock()
        def command(args):
            if args[0]=='bootstrap':self.progress('collector','activation_bootstrap','INTENT')
            result=self.j.command(['/bin/launchctl',*args])
            if args[0]=='bootstrap':self.progress('collector','activation_bootstrap','COMMAND_SUCCEEDED')
            if args[0]=='disable':self.graph_disabled_by_this_activation=True
            return result
        result=self.op.activate_graph(self.p,command=command)
        self.j.record('ORIGINAL_GRAPH_TWO_FRESH_GATES_AND_ACTIVATION',result=result)
        # Original queue collector cold-reconciles a changed config. Read only;
        # do not insert events, call another collector, or alter old snapshots.
        from urllib.request import urlopen
        started=time.monotonic()
        while True:
            with urlopen('http://127.0.0.1:8873/api/v3/runtime-graph/status',timeout=30) as response:raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise Stop('GRAPH_STATUS_RESPONSE_LIMIT')
            status=json.loads(raw)
            if status.get('config_sha256')==self.p['config_sha256'] and status.get('snapshot_sha256'):
                snapshot=Path(load(self.p['config_path'])['graph_root'])/'runtime_graph/v4/snapshot.json'
                pin(snapshot,status['snapshot_sha256'])
                if status.get('monitor',{}).get('registration')!='LOADED':raise Stop('GRAPH_MONITOR_REGISTRATION_NOT_LOADED')
                path=D/'ROOT_GRAPH_STATUS_AFTER.json'
                with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                self.j.record('ACTUAL_GRAPH_NEW_CONFIG_SNAPSHOT_READBACK',path=str(path),sha256=sha(path),config_sha256=self.p['config_sha256'],observed_graph_status=status.get('status'),overall_business_or_PIT_PASS='NOT_CLAIMED')
                return
            state=self.op.label_state(LABELS['collector'])
            if state is None:raise Stop('GRAPH_UNLOADED_BEFORE_ACTUAL_READBACK')
            if state==0 and time.monotonic()-started>15:raise Stop('GRAPH_COLLECTOR_RETURNED_WITHOUT_NEW_CONFIG_SNAPSHOT')
            self.j.record('WAIT_CANONICAL_GRAPH_COLD_RECONCILE_NO_CANCELLATION',pid=state,config_sha256=status.get('config_sha256'));time.sleep(1)

    @staticmethod
    def printed_arguments(text):
        lines=text.splitlines();result=[];indent=None
        for line in lines:
            if indent is None:
                if line.strip()=='arguments = {':indent=line[:len(line)-len(line.lstrip())]
                continue
            if line==indent+'}':return result
            result.append(line.strip())
        raise Stop('LOADED_ARGUMENTS_UNCONFIRMED')

    def observe_service_binding(self,component):
        row=self.op.op(self.p,component);digest=sha(row['plist'])
        if digest not in {row['before_sha256'],row['after_sha256']}:raise Stop('RECOVERY_FOREIGN_PLIST:'+component)
        before_path=D/(row['label']+'.before.plist');pin(before_path,row['before_sha256']);before=before_path.read_bytes()
        expected={'OLD':plistlib.loads(before),'NEW':plistlib.loads(self.op.proposed_bytes(row,before))}
        result=subprocess.run(['/bin/launchctl','print','gui/'+str(os.getuid())+'/'+row['label']],capture_output=True,text=True)
        file_version='OLD' if digest==row['before_sha256'] else 'NEW'
        if result.returncode:
            if result.returncode==113 or 'Could not find service' in result.stderr:return {'kind':'ABSENT','file_version':file_version,'plist_sha256':digest,'pid':None}
            raise Stop('RECOVERY_LABEL_READ_UNKNOWN:'+component)
        text=result.stdout;found=re.search(r'^[ \t]*pid = (\d+)[ \t]*$',text,re.M);pid=int(found.group(1)) if found else 0
        arguments=self.printed_arguments(text);matched=[]
        essential=('V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256','V4_RUNTIME_GRAPH_CONFIG','V35_RESEARCH_PANEL_A_SYNC_SCRIPT','PYTHONPATH')
        for version,value in expected.items():
            if arguments!=value['ProgramArguments']:continue
            directories=re.findall(r'^[ \t]*working directory = (.*?)[ \t]*$',text,re.M)
            if not directories or set(directories)!={value['WorkingDirectory']}:continue
            env=value.get('EnvironmentVariables',{});valid=True
            for key in essential:
                if key not in env:continue
                observed=re.findall(r'^[ \t]*'+re.escape(key)+r'[ \t]*=>[ \t]*(.*?)[ \t]*$',text,re.M)
                if not observed or set(observed)!={str(env[key])}:valid=False;break
            if not valid:continue
            if component=='collector' and any(str(path) not in text for path in value.get('QueueDirectories',[])):continue
            matched.append(version)
        if matched!=[file_version]:raise Stop('RECOVERY_LOADED_BINDING_UNKNOWN_OR_MISMATCH:'+component)
        identity=self.g.identity(pid) if pid else None
        if component!='collector' and not identity:raise Stop('RECOVERY_RUNNING_OWNER_UNCONFIRMED:'+component)
        if pid and self.g.cwd(pid)!=expected[file_version]['WorkingDirectory']:raise Stop('RECOVERY_LOADED_CWD_MISMATCH:'+component)
        return {'kind':'LOADED','file_version':file_version,'loaded_version':matched[0],'plist_sha256':digest,'pid':pid,'identity':identity,'loaded_arguments':arguments,'working_directory':expected[file_version]['WorkingDirectory']}

    @staticmethod
    def recovery_fingerprint(observation):
        return {key:observation.get(key) for key in ('kind','file_version','loaded_version','plist_sha256','pid','identity')}

    def restoration_plan(self):
        # Resolve every label before touching any. A still healthy OLD Main/API
        # is retained even when its earlier bootout command outcome was unknown.
        observed={name:self.observe_service_binding(name) for name in LABELS}
        disabled=self.graph_disabled()
        if disabled and not self.graph_disabled_by_this_activation:raise Stop('RECOVERY_FOREIGN_GRAPH_DISABLED_NO_OVERRIDE')
        stop=[];restore=[];start=[]
        for name,value in observed.items():
            if value['kind']=='LOADED' and value['file_version']=='OLD':continue
            if value['kind']=='LOADED':
                progress=getattr(self,'action_progress',{}).get(name,{})
                if not any(progress.get(key) for key in ('bootstrap','activation_bootstrap')):raise Stop('RECOVERY_NEW_OWNER_WITHOUT_OWN_BOOTSTRAP_PROGRESS:'+name)
                stop.append(name)
            elif value['kind']!='ABSENT':raise Stop('RECOVERY_LABEL_STATE_UNKNOWN:'+name)
            if value['file_version']=='NEW':restore.append(name)
            start.append(name)
        return {'observed':observed,'bootout':[name for name in ('collector','api','main') if name in stop],
                'restore_plist':[name for name in ('main','api','collector') if name in restore],
                'bootstrap':[name for name in ('main','api','collector') if name in start],
                'restore_graph_enabled':disabled}

    def rollback(self):
        self.forward_first_action_pending=False  # recovery is not a new forward cutover
        if self.graph_fd is None:
            while not self.try_graph_collector_lock():
                self.j.record('WAIT_GRAPH_NATURAL_DRAIN_FOR_RECOVERY');time.sleep(1)
        plan=self.restoration_plan();self.j.record('MINIMAL_RESTORATION_PLAN',plan=plan)
        for name in plan['bootout']:
            now=self.observe_service_binding(name)
            if self.recovery_fingerprint(now)!=self.recovery_fingerprint(plan['observed'][name]):raise Stop('RECOVERY_OWNER_CHANGED_BEFORE_BOOTOUT:'+name)
            self.bootout(name)
        for name in plan['restore_plist']:
            row=self.op.op(self.p,name)
            if self.op.label_state(row['label']) is not None:raise Stop('RECOVERY_CAS_LABEL_NOT_UNLOADED:'+name)
            pin(row['plist'],row['after_sha256'])
            self.j.record('ROLLBACK_CAS_INTENT',component=name);result=self.op.install_plist(row,rollback=True);self.j.record('ROLLBACK_CAS_RESULT',component=name,result=result)
        if plan['restore_graph_enabled']:
            self.j.command(['/bin/launchctl','enable','gui/'+str(os.getuid())+'/'+LABELS['collector']])
        for name in plan['bootstrap']:
            row=self.op.op(self.p,name);pin(row['plist'],row['before_sha256'])
            if name=='collector':self.release_graph_collector_lock()
            self.bootstrap(name)
        self.verify_rollback()

    def read_graph_status(self):
        from urllib.request import urlopen
        with urlopen('http://127.0.0.1:8873/api/v3/runtime-graph/status',timeout=30) as response:raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise Stop('GRAPH_STATUS_RESPONSE_LIMIT')
        return json.loads(raw)

    def verify_rollback(self):
        for row in self.p['operations']:pin(row['plist'],row['before_sha256'])
        bindings={name:self.observe_service_binding(name) for name in LABELS}
        if any(value['kind']!='LOADED' or value['file_version']!='OLD' for value in bindings.values()):raise Stop('ROLLBACK_OLD_LABEL_BINDING_NOT_RESTORED')
        if self.graph_disabled():raise Stop('ROLLBACK_OLD_COLLECTOR_DISABLED')
        oldplan=load(self.p['old_graph_plan'])
        self.op.verify_release(oldplan,'collector')
        pin(oldplan['config_target'],oldplan['config_sha256'])
        observed=self.op.observe_api(oldplan);self.op.validate_api_observation(oldplan,observed)
        status=self.read_graph_status();monitor=status.get('monitor',{})
        if status.get('config_sha256')!=oldplan['config_sha256'] or monitor.get('config_sha256')!=oldplan['config_sha256'] or monitor.get('registration')!='LOADED' or monitor.get('state') not in {'IDLE','PENDING'}:raise Stop('ROLLBACK_OLD_MONITOR_CONFIG_OR_REGISTRATION_UNCONFIRMED')
        snapshot=Path(load(oldplan['config_path'])['graph_root'])/'runtime_graph/v4/snapshot.json'
        if not status.get('snapshot_sha256'):raise Stop('ROLLBACK_OLD_SNAPSHOT_UNCONFIRMED')
        pin(snapshot,status['snapshot_sha256'])
        self.j.record('ROLLBACK_ORIGINAL_GRAPH_AUTHORITY_AND_MONITOR_PROOF_VERIFIED',observation=observed,collector_binding=bindings['collector'],monitor=monitor)
        self.j.record('ROLLBACK_EXACT_OLD_BINDINGS_CWD_VERIFIED',main_pid=bindings['main']['pid'],api_pid=bindings['api']['pid'],collector_pid=bindings['collector']['pid'],collector_enabled=True,standard_api_dispatcher='BASELINE_CUSTOM_SCHEMA_CANNOT_CONFIRM',graph_overall='NO_UPGRADE_TO_PASS')

    def validate_prestage_resume_r1(self,expected_main_pid):
        row=self.p['prestage_resume_r1'];pin(row['path'],row['sha256']);binding=load(row['path'])
        before=validate_prestage_resume_r1_files(binding,self.p)
        self.compare()
        current={name:self.recovery_fingerprint(self.observe_service_binding(name)) for name in LABELS}
        if current!=binding['expected_current_bindings'] or any(value.get('kind')!='LOADED' or value.get('file_version')!='OLD' for value in current.values()):raise Stop('PRESTAGE_RESUME_CURRENT_OLD_IDENTITY_DRIFT')
        if expected_main_pid!=current['main']['pid'] or self.graph_disabled():raise Stop('PRESTAGE_RESUME_CURRENT_OWNER_OR_GRAPH_DRIFT')
        self.g.initial_old(expected_main_pid)
        return binding,before

    def verify_materialized_r3_targets(self):
        # No copy, dispatcher execution, producer, data-link traversal or probe
        # rerun. Reuse their bound PASS only after exact immutable-tree parity.
        comp=self.p['lifecycle_component'];root=Path(comp['target']);source=Path(comp['source'])
        pin(root/'release-manifest.json',comp['manifest_sha256']);pin(source/'release-manifest.json',comp['manifest_sha256'])
        m=load(root/'release-manifest.json');entries=[{'path':rel,'bytes':(source/rel).stat().st_size,'sha256':h} for rel,h in m['files'].items()]
        entries.append({'path':'release-manifest.json','bytes':(source/'release-manifest.json').stat().st_size,'sha256':comp['manifest_sha256']})
        self.exact_inventory(root,entries,[])
        for name in LABELS:
            meta=self.p['components'][name];pin(Path(meta['release_root'])/'release-manifest.json',meta['sha256']);self.op.verify_release(self.p,name)
            m=load(Path(meta['release_root'])/'release-manifest.json');self.exact_inventory(Path(meta['release_root'])/'app',m['app_files'],m['symlinks'])
        pin(self.p['config_target'],self.p['config_sha256'])

    def validate_materialized_resume_r3(self,expected_main_pid):
        row=self.p['resume_materialized_r3'];pin(row['path'],row['sha256']);binding=load(row['path'])
        before=validate_materialized_r3_files(binding,self.p);self.compare();self.verify_materialized_r3_targets()
        current={name:self.recovery_fingerprint(self.observe_service_binding(name)) for name in LABELS}
        if current!=binding['expected_current_bindings'] or any(v.get('kind')!='LOADED' or v.get('file_version')!='OLD' for v in current.values()):raise Stop('MATERIALIZED_RESUME_OLD_RUNTIME_IDENTITY_DRIFT')
        if expected_main_pid!=current['main']['pid'] or self.graph_disabled():raise Stop('MATERIALIZED_RESUME_OWNER_OR_GRAPH_DRIFT')
        self.g.initial_old(expected_main_pid)
        return binding,before

    def execute(self,review_path,review_sha,expected_main_pid,*,resume_prestage_r1=False,resume_materialized_r3=False):
        approve(review_path,review_sha)
        if resume_prestage_r1 and resume_materialized_r3:raise Stop('FIXED_RESUME_FLAGS_MUTUALLY_EXCLUSIVE')
        reused_before=None
        if resume_materialized_r3:
            binding,reused_before=self.validate_materialized_resume_r3(expected_main_pid)
            self.j=MaterializedResumeR3Journal(binding)
            self.j.record('ROOT_MATERIALIZED_RESUME_R3_STARTED',plan_sha256=sha(D/'PLAN.json'),review_sha256=review_sha,first_journal_sha256=PRESTAGE_R1_JOURNAL_SHA,prior_journal_sha256=MATERIALIZED_R3_JOURNAL_SHA,prior_failure=binding['failure'],prior_review=binding['accepted_prior_review'],no_service_action_proof=True)
        elif resume_prestage_r1:
            binding,reused_before=self.validate_prestage_resume_r1(expected_main_pid)
            self.j=PrestageResumeR1Journal(binding)
            self.j.record('ROOT_PRESTAGE_RESUME_R1_STARTED',plan_sha256=sha(D/'PLAN.json'),review_sha256=review_sha,prior_journal_sha256=PRESTAGE_R1_JOURNAL_SHA,prior_failure=binding['failure'],prior_review=binding['accepted_prior_review'],pre_service_only_proof=True)
        else:
            self.j=Journal();self.j.record('ROOT_DEPLOYMENT_STARTED',plan_sha256=sha(D/'PLAN.json'),review_sha256=review_sha)
        self.compare()
        if self.graph_disabled():raise Stop('ORIGINAL_GRAPH_DISABLED_NO_UNREQUESTED_ENABLE')
        old=self.g.initial_old(expected_main_pid)
        if reused_before is None:self.baseline_http={code:self.history_http(code,'before') for code in ('601198.SH','601059.SH')}
        else:
            self.baseline_http=reused_before
            self.j.record('PRIOR_BEFORE_HTTP_REUSED_NO_REFETCH',prior_journal_sha256=PRESTAGE_R1_JOURNAL_SHA,codes=list(reused_before))
        if resume_materialized_r3:self.j.record('IMMUTABLE_TARGETS_DISPATCHER_AND_CORRECTED_PROBE_REUSED_NO_COPY',prior_journal_sha256=MATERIALIZED_R3_JOURNAL_SHA,probe_result=binding['corrected_probe_result'])
        else:self.stage()
        with self.original_main_control_owner():
            while True:
                with self.all_original_guards(old):
                    self.compare()
                    old_plan=load(self.p['old_graph_plan']);old_observation=self.op.observe_api(old_plan)
                    self.op.validate_api_observation(old_plan,old_observation)
                    api_pid=old_observation['api_pid'];api_birth=self.g.identity(api_pid)
                    if self.g.cwd(api_pid)!=self.p['old_api_app']:raise Stop('OLD_API_PROCESS_CWD_DRIFT')
                    self.j.record('FRESH_ORIGINAL_OLD_API_MAIN_GRAPH_GATE',observation=old_observation,api_process_identity=api_birth)
                    boundary=self.deployment_boundary()
                    if not boundary['ready']:
                        self.j.record('FINAL_FRESH_OBSERVATION_CROSSED_BOUNDARY_RELEASE_GUARDS',boundary=boundary);continue
                    before_actions=sum(self.j.action_counts.values())
                    try:
                        for name in ('collector','main','api'):self.bootout(name)
                        for name in ('main','api','collector'):
                            self.j.record('PLIST_CAS_INTENT',component=name);result=self.op.install_plist(self.op.op(self.p,name));self.j.record('PLIST_CAS_RESULT',component=name,result=result)
                        for name in ('main','api'):self.bootstrap(name)
                        self.dispatcher()
                        # Startup gets bounded read-only retries; commands never repeat.
                        for i in range(30):
                            try:self.verify();break
                            except Exception as error:
                                self.j.record('READBACK_PENDING_GUARDS_HELD',attempt=i,error=repr(error))
                                if i==29:raise
                                time.sleep(1)
                        self.bounded_http()
                        self.activate_original_graph()
                        self.j.record('ROOT_BINDINGS_VERIFIED_RELEASE_GUARDS_NEXT',outcome='NEW_BINDINGS_VERIFIED',natural_business='NOT_CLAIMED',http_ui='THREE_HTTP_PASS_UI_ROOT_READER_PENDING')
                    except BaseException as error:
                        mutated=sum(self.j.action_counts.values())>before_actions
                        self.j.record('FAILURE_GUARDS_RETAINED',error=repr(error),service_action_intent_started=mutated)
                        if not mutated:
                            if str(error) in {'GRAPH_COLLECTOR_BECAME_BUSY','DEPLOYMENT_WINDOW_REVOKED_NO_SERVICE_ACTION'}:
                                self.j.record('WAIT_BOUNDARY_REVOKED_NO_SERVICE_ACTION');continue
                            raise
                        print('GUARDS_HELD: ROLLBACK restores exact before bytes; VERIFY_ROLLBACK only rereads restored runtime. Reconcile unknown command outcomes from journal first.',flush=True)
                        while True:
                            cmd=sys.stdin.readline().strip()
                            if cmd in {'ROLLBACK','VERIFY_ROLLBACK'}:
                                try:
                                    if cmd=='ROLLBACK':self.rollback()
                                    else:self.verify_rollback()
                                    self.j.record('RECOVERY_COMPLETE_OLD_BINDINGS');break
                                except BaseException as recovery:self.j.record('ROLLBACK_UNCONFIRMED_GUARDS_HELD',error=repr(recovery),next_readonly_command='VERIFY_ROLLBACK')
                            else:time.sleep(1)
                break
        self.j.record('GUARDS_RELEASED',natural_work='MAY_START_AFTER_STABLE_LANE_FD_CLOSE')


def main():
    p=argparse.ArgumentParser();p.add_argument('--execute-reviewed',action='store_true');p.add_argument('--resume-prestage-r1',action='store_true');p.add_argument('--resume-materialized-r3',action='store_true');p.add_argument('--review',type=Path);p.add_argument('--review-sha');p.add_argument('--expected-main-pid',type=int);args=p.parse_args()
    if not (D/'PLAN.json').exists():print('OWNER_PROJECTION_PENDING_NO_ACTION');return 2
    plan=load(D/'PLAN.json')
    if not args.execute_reviewed:print(json.dumps({'status':'PLAN_ONLY','plan_sha256':sha(D/'PLAN.json')}));return 0
    if not args.review or not args.review_sha or not args.expected_main_pid:raise Stop('EXACT_REVIEW_AND_FRESH_MAIN_PID_REQUIRED')
    approve(args.review,args.review_sha)
    Capsule(plan).execute(args.review,args.review_sha,args.expected_main_pid,resume_prestage_r1=args.resume_prestage_r1,resume_materialized_r3=args.resume_materialized_r3);return 0
if __name__=='__main__':raise SystemExit(main())
