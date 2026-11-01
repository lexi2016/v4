"""Fixed, reversible API r4 + Stage/pre r3 cutover. No business writes.

prepare only captures preimages and validates; activate requires the exact plan
SHA and controller GO. rollback restores the three actual captured preimages.
No high-level legacy activation/preparation code is called.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]
LOCAL = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
LA = Path('/Users/lexi/Library/LaunchAgents')
EVIDENCE = Path('/private/tmp/v4-stage-four-release-20261101-r2')
PYTHON = LOCAL/'runtime/venvs/v4-mac/bin/python'
DOMAIN = f'gui/{os.getuid()}'
API = LOCAL/'candidates/stage-four-repairs-20261101-r4-api'
BUNDLE = LOCAL/'candidates/stage-four-repairs-20261101-r3'
BASE_API = LOCAL/'candidates/junda-single-20261101-8e342a6d64746507'
TARGETS = {
    'stage': ('com.lexi.stage-center.scheduler', LOCAL/'releases/a-stage-owner-compatibility-20261030-r2-stage',
        '9ef8f0bdebca08a7ac5cc04f42ef4a323d186d2d894ee29a8062908802361d35',
        BUNDLE/'stage-four-repairs-20261101-r3-stage', 'ff62078ab7fb5d05318233fbfab18bd34408a0fc5b162359080c080633ee4115'),
    'pre': ('com.lexi.stage-center.a-opening-precapture', LOCAL/'releases/a-snapshot-recovery-20261029-r1-stage',
        '8b9e9c22f4641c395e853dcfd2b0c7054f9fdcd416d9ed0bc86412da617a5694',
        BUNDLE/'stage-four-repairs-20261101-r3-a_precapture', 'e497fcb246747269cf8d6b4911c4a89d7ffd85fd56d53fb27e54dbb754c56b3b'),
    'api': ('com.lexi.v4.api', BASE_API, '80ef9ab95df0eb2168051ec62c628dea0a6efe63173059fab85bbeda087b5c7b',
        API, '21fb1a6b8c272ae29441b5d5af1814be78e9d4dbd8615d1c5d880a752131107a'),
}
ENV_PIN = '44ff66523c1d1024d82a818eec039e24b334d69dd6c021626556aa235f82f3a4'
# Explicit controller decision after preserved OPERATIONAL_PREFLIGHT.json FAIL.
# This changes only this operation's protection pin, never the sealed candidate.
PANEL_GENERATION_PIN = 'f5c4b58901f7c40ae905df96e787b93ffa1b5e840c74650ca5bcc559efc204a3'
PANEL_GENERATION_COUNT = 488
TOOLS_PIN = '35ac1a9b6f3ea885b2788a9476dbc2f4dc21f42f43a359b63a0c22265c1fd154'
IDENTITY = ('V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256')
PROTECTED_LABELS = ('com.lexi.v4.scheduler', 'com.lexi.stage-center.hk-deadline',
                    'com.lexi.review-core.daily','com.lexi.vibe-astock.local')

def sha(raw): return hashlib.sha256(raw).hexdigest()
def require(ok, message):
    if not ok: raise ValueError(message)
def write_json(path, obj):
    with path.open('x') as out:
        json.dump(obj,out,ensure_ascii=False,indent=2,sort_keys=True);out.write('\n')
def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
def lc(*args): return subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=12)
def api_get(route):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8873'+route,timeout=10) as out:
        require(out.status==200,'HTTP_STATUS');return json.load(out)
def pinned(path, digest):
    require(not path.is_symlink() and sha(path.read_bytes())==digest,'PIN_CHANGED:'+str(path))
def tools():
    path=BASE_API/'app/ops/api_release_integration.py';pinned(path,TOOLS_PIN)
    return module('stage4_release_inventory',path)
def verify_release(root, digest, inventory_tools):
    pinned(root/'release-manifest.json',digest)
    m=json.loads((root/'release-manifest.json').read_text())
    require(m['candidate']['app_root']==str(root/'app') and m['candidate']['release_id']==root.name,'RELEASE_IDENTITY')
    require(m.get('RESEARCH_ONLY') is True and all(m.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),'SAFETY_FLAGS')
    entries=inventory_tools.inventory_tree(root/'app');record=m['application_inventory']
    require(record=={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_tools.inventory_digest(entries)} and m['app_files']==entries,'INVENTORY_DRIFT:'+str(root))
    return {'root':str(root),'manifest_sha256':digest,'entries':len(entries),'inventory_sha256':record['aggregate_sha256']}
def loaded(label, raw, *, missing=False):
    result=lc('print',DOMAIN+'/'+label)
    if result.returncode:
        require(missing and 'Could not find service' in result.stderr,'JOB_STATE_UNKNOWN:'+label+':'+result.stderr)
        return None
    p=plistlib.loads(raw);text=result.stdout
    for field,value in {'path':str(LA/(label+'.plist')),'program':p['ProgramArguments'][0],'working directory':p['WorkingDirectory']}.items():
        require(re.search(r'^\s*'+re.escape(field)+r' = '+re.escape(value)+r'\s*$',text,re.M),'LOADED_'+field+':'+label)
    block=re.search(r'^\targuments = \{\n(.*?)^\t\}',text,re.M|re.S)
    require(block is not None and [line.strip() for line in block[1].splitlines()]==p['ProgramArguments'],'LOADED_ARGV:'+label)
    block=re.search(r'^\tenvironment = \{\n(.*?)^\t\}',text,re.M|re.S)
    require(block is not None,'LOADED_ENV_ABSENT')
    env=dict(re.findall(r'^\t\t([^\n]+?) => ([^\n]*)$',block[1],re.M))
    require(all(env.get(k)==str(v) for k,v in p['EnvironmentVariables'].items()),'LOADED_ENV_DISK_MISMATCH:'+label)
    # Preserve all explicitly loaded values; only launchd's own additions differ.
    require(set(env)-set(p['EnvironmentVariables']) <= {'OSLogRateLimit','XPC_SERVICE_NAME'},'UNEXPECTED_LOADED_ENV:'+label)
    if 'StartCalendarInterval' in p:
        expected=p['StartCalendarInterval'];expected=expected if isinstance(expected,list) else [expected]
        descriptors=re.findall(r'descriptor = \{(.*?)\n\s*\}',text,re.S)
        actual=[]
        for value in descriptors:
            actual.append({key:int(number) for key,number in re.findall(r'"(\w+)" => (\d+)',value)})
        require(sorted(map(lambda v:json.dumps(v,sort_keys=True),actual))==sorted(map(lambda v:json.dumps(v,sort_keys=True),expected)),'LOADED_CALENDAR_MISMATCH:'+label)
    pid=re.search(r'^\s*pid = (\d+)\s*$',text,re.M)
    state=re.search(r'^\tstate = ([^\n]+)',text,re.M)
    return {'pid':int(pid[1]) if pid else None,'state':state[1] if state else None,
            'loaded_definition_sha256':sha(json.dumps({'argv':p['ProgramArguments'],'env':env,'cwd':p['WorkingDirectory']},sort_keys=True).encode()),
            'plist_sha256':sha(raw),'release_id':p['EnvironmentVariables'].get('V4_RELEASE_ID')}
def pid_alive(pid):
    try: os.kill(pid,0);return True
    except ProcessLookupError:return False
def assert_idle(api_pid):
    rows=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,command='],text=True)
    processes=[]
    for line in rows.splitlines():
        parts=line.strip().split(None,2)
        if len(parts)==3:processes.append((int(parts[0]),int(parts[1]),parts[2]))
    descendants={api_pid}
    while True:
        more={pid for pid,parent,_ in processes if parent in descendants}
        if more <= descendants:break
        descendants |= more
    require(descendants=={api_pid},'API_HEALTHY_CHILDREN_ACTIVE')
    active=[pid for pid,_,command in processes if pid!=os.getpid() and not command.startswith(('/bin/zsh -c','rg ')) and
            re.search(r'(?:python\S*|Python) .*?(?:ops/run_stage_center_nodes\.py|ops/stage_data_recovery\.py|manual_collection_owner)',command)]
    require(not active,'STAGE_OR_MANUAL_PROCESS_ACTIVE:'+str(active))
    manual=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manual_collection')
    if (manual/'owner_active.json').exists():
        owner=json.loads((manual/'owner_active.json').read_text());require(not pid_alive(owner['pid']),'MANUAL_OWNER_ACTIVE')
    jobs=[]
    for path in (manual/'jobs').glob('*.json'):
        job=json.loads(path.read_text())
        require(job.get('status') not in {'RUNNING','PENDING'},'MANUAL_JOB_ACTIVE:'+path.name);jobs.append(path.name)
    lockroot=LOCAL/'state/stage/receipts/.locks'
    for path in lockroot.glob('*.lock'):
        raw=path.read_bytes()
        try: owner=json.loads(raw);pid=owner.get('pid')
        except (ValueError,AttributeError):raise ValueError('UNKNOWN_STAGE_LOCK:'+str(path))
        require(type(pid) is int and not pid_alive(pid),'LIVE_STAGE_LOCK:'+str(path))
    return {'api_children':[],'stage_manual_processes':[],'manual_terminal_jobs':len(jobs),'stage_live_lock_owners':[]}
def external_protection():
    pinned(API/'activation-environment.json',ENV_PIN);act=json.loads((API/'activation-environment.json').read_text())
    bindings=copy.deepcopy(act['preserved_external_binding_sha256'])
    asset_binding=bindings['V4_RESEARCH_PANEL_ASSET_MANIFEST']
    require(asset_binding=={'path':str(BASE_API/'research-panel-assets.json'),'sha256':'0296a5755aaa7eae60e31e8b89a647bd1aab78b2a71033127d013e5211b023e9'},'ORIGINAL_PANEL_PIN_CHANGED')
    asset_binding['sha256']=PANEL_GENERATION_PIN
    for item in bindings.values():pinned(Path(item['path']),item['sha256'])
    panel=Path(act['api_environment']['V4_RESEARCH_PANEL_ROOT'])
    assets=json.loads(Path(act['api_environment']['V4_RESEARCH_PANEL_ASSET_MANIFEST']).read_text())['files']
    require(len(assets)==PANEL_GENERATION_COUNT,'PANEL_GENERATION_COUNT_CHANGED')
    for item in assets:pinned(panel/item['path'],item['sha256'])
    protected={}
    for label in PROTECTED_LABELS:
        path=LA/(label+'.plist');raw=path.read_bytes();job=loaded(label,raw)
        protected[label]={'plist_sha256':sha(raw),'job':job}
    return {'external_bindings':bindings,'original_candidate_external_bindings':act['preserved_external_binding_sha256'],
            'override_scope':'Controller-approved one external asset manifest generation, same Junda root, preserve 488 current assets',
            'panel_root':str(panel),'panel_asset_count':len(assets),'protected_jobs':protected}
def data_protection():
    """Mechanical size/mtime/mode inventory plus one content sample per root."""
    result={}
    for name in ('raw','selection','receipts'):
        root=LOCAL/'state/stage'/name;entries=[];sample=None
        for directory,dirs,files in os.walk(root):
            dirs[:]=sorted(d for d in dirs if d not in ('.locks','__pycache__'))
            for filename in sorted(files):
                path=Path(directory)/filename;info=path.lstat()
                entries.append([str(path.relative_to(root)),info.st_size,info.st_mtime_ns,stat.S_IMODE(info.st_mode)])
                if sample is None and path.is_file() and not path.is_symlink():sample={'path':str(path),'sha256':sha(path.read_bytes())}
        result[name]={'root':str(root),'entries':len(entries),'stat_inventory_sha256':sha(json.dumps(entries).encode()),'content_sample':sample}
    return result
def staged(role, raw):
    label,old,_,new,digest=TARGETS[role];payload=copy.deepcopy(plistlib.loads(raw));env=payload['EnvironmentVariables']
    payload['WorkingDirectory']=str(new/'app')
    if role=='api':
        act=json.loads((API/'activation-environment.json').read_text())
        for k,v in act['api_environment'].items():
            if k not in IDENTITY and k!='V4_MANUAL_COLLECTION_STAGE_CONFIG':require(env.get(k)==v,'EXTERNAL_BINDING_CHANGED')
        env.update(act['api_environment'])
    else:
        payload['ProgramArguments']=[s.replace(str(old/'app'),str(new/'app')) for s in payload['ProgramArguments']]
        env['PYTHONPATH']=env['PYTHONPATH'].replace(str(old/'app'),str(new/'app'))
        env['STAGE_CENTER_CONFIG']=str(new/'app/stage_center_tick_config.json')
        env.update(dict(zip(IDENTITY,(str(new/'app'),new.name,str(new/'release-manifest.json'),digest))))
    return plistlib.dumps(payload,sort_keys=True)
def guards():
    sys.path.insert(0,str(BASE_API/'app'))
    from infrastructure.interprocess_lock import owned_interprocess_lock
    stack=ExitStack()
    try:
        stack.enter_context(owned_interprocess_lock(LA/'.com.lexi.v4.api.release.lock',timeout_seconds=2,timeout_message='API_RELEASE_SHARED_LOCK_BUSY'))
        manual=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manual_collection')
        for name in ('.claim','.execution'):
            stack.enter_context(owned_interprocess_lock(manual/name,timeout_seconds=1,timeout_message='MANUAL_COLLECTION_BUSY'))
        config=json.loads((LOCAL/'config/us-industry-observed-api-20261018-r1.json').read_text())
        stack.enter_context(tools().announcement_flash_cutover_guard(Path(config['state_root'])/'manager_workbench',timeout_seconds=2))
        return stack
    except BaseException:stack.close();raise
def live_api(raw):
    job=loaded(TARGETS['api'][0],raw);env=plistlib.loads(raw)['EnvironmentVariables'];require(job['pid'] is not None,'API_PID_ABSENT')
    listeners=subprocess.check_output(['/usr/sbin/lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-t'],text=True,timeout=5)
    require(set(listeners.split())=={str(job['pid'])},'API_LISTENER_PID')
    require(api_get('/healthz')=={'status':'ok'},'HEALTHZ')
    require(api_get('/readyz')=={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},'READYZ_SAFETY')
    identity=api_get('/api/v1/runs/date-list')['runtime_identity']
    require(identity.get('status')=='MANIFEST_EXECUTION_FILES_VERIFIED' and identity.get('release_id')==env['V4_RELEASE_ID'] and identity.get('manifest_sha256')==env['V4_RELEASE_MANIFEST_SHA256'],'API_RUNTIME_IDENTITY')
    return {'job':job,'runtime_identity':identity}
def prepare():
    require(sys.executable==str(PYTHON),'PINNED_PYTHON_REQUIRED')
    require(not EVIDENCE.exists(),'PREPARATION_ALREADY_EXISTS')
    inv=tools();releases=[];records={}
    with guards():
        for role,(label,old,oldsha,new,newsha) in TARGETS.items():
            path=LA/(label+'.plist');require(not path.is_symlink(),'PLIST_SYMLINK');raw=path.read_bytes();p=plistlib.loads(raw);env=p['EnvironmentVariables']
            require(tuple(env[k] for k in IDENTITY)==(str(old/'app'),old.name,str(old/'release-manifest.json'),oldsha),'OLD_RELEASE_CHANGED:'+role)
            job=loaded(label,raw)
            if role!='api':require(job['pid'] is None and job['state']=='not running','CALENDAR_JOB_BUSY')
            for root,digest in ((old,oldsha),(new,newsha)):releases.append(verify_release(root,digest,inv))
            newraw=staged(role,raw)
            before,after=p,plistlib.loads(newraw)
            env_delta={k:{'before':env.get(k),'after':v} for k,v in after['EnvironmentVariables'].items() if env.get(k)!=v}
            records[role]={'label':label,'path':str(path),'mode':stat.S_IMODE(path.stat().st_mode),'original_sha256':sha(raw),'staged_sha256':sha(newraw),'loaded':job,
                'env_delta':env_delta,'argv_before':p['ProgramArguments'],'argv_after':after['ProgramArguments'],
                'cwd_before':p['WorkingDirectory'],'cwd_after':after['WorkingDirectory'],'calendar':p.get('StartCalendarInterval')}
        idle=assert_idle(records['api']['loaded']['pid']);health=live_api((LA/'com.lexi.v4.api.plist').read_bytes())
        protection=external_protection();data=data_protection()
        EVIDENCE.mkdir(mode=0o700)
        for role,record in records.items():
            raw=Path(record['path']).read_bytes();require(sha(raw)==record['original_sha256'],'PREPARE_CAS_CHANGED')
            for suffix,content in (('original',raw),('staged',staged(role,raw))):
                path=EVIDENCE/(role+'.'+suffix+'.plist');path.write_bytes(content);path.chmod(record['mode'])
        script_sha=sha(Path(__file__).read_bytes())
        command=f"PYTHONDONTWRITEBYTECODE=1 {shlex.quote(str(PYTHON))} -B {shlex.quote(str(Path(__file__).resolve()))}"
        plan={'status':'PREPARED_NOT_ACTIVATED','GOAL':'Activate only accepted API r4 / Stage r3 / A pre-capture r3 preserving Junda panel and raw data',
            'Writer':'stage_release_operator','Reviewer':'controller independent operational review',
            'ALLOWED_PATHS':[r['path'] for r in records.values()]+[str(Path(__file__).resolve()),str(EVIDENCE)],
            'FORBIDDEN_PATHS':['business source/candidate bytes','Main/HK deadline/collector/8910 service','research panel source/assets/data','all business data writes','Git merge/push'],
            'PASS_SIGNAL':'3 exact loaded jobs/calendars, API healthy manifest identity, r3 manual binding, sealed SOP, unchanged protected bytes; UI/raw live-path proof controller-owned',
            'STOP_RULE':'Any actual identity drift or busy task stops before unload; post-mutation failure restores actual 3 preimages; unknown external CAS conflict stops without overwrite',
            'source_root':str(SOURCE),'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),
            'script_sha256':script_sha,'records':records,'releases':releases,'idle':idle,'health':health,'protection':protection,'data_protection':data,
            'rollback_command_template':command+' rollback --plan-sha <SHA256 of preparation.json>',
            'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'NATURAL_VERIFIED':'NOT_RUN'}
        write_json(EVIDENCE/'preparation.json',plan)
    print(json.dumps({'status':plan['status'],'receipt':str(EVIDENCE/'preparation.json'),'sha256':sha((EVIDENCE/'preparation.json').read_bytes()),'records':records},ensure_ascii=False))
def cas(record, expected):
    path=Path(record['path']);require(not path.is_symlink() and path.read_bytes()==expected and stat.S_IMODE(path.stat().st_mode)==record['mode'],'ACTIVE_PLIST_CAS_CHANGED:'+record['label'])
def replace(record, expected, desired):
    cas(record,expected);path=Path(record['path'])
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.stage-four-',delete=False) as out:
        temp=Path(out.name)
        try:
            out.write(desired);out.flush();os.fsync(out.fileno());temp.chmod(record['mode']);cas(record,expected);os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)
def unload(role, raw, oldjob):
    label=TARGETS[role][0];current=loaded(label,raw,missing=True)
    if current:
        require(oldjob is not None and (oldjob['pid'] is None or current['pid'] in (None,oldjob['pid'])),'EXTERNAL_PID_CHANGED')
        if role!='api':require(current['pid'] is None and current['state']=='not running','CALENDAR_BUSY_BEFORE_BOOTOUT')
        result=lc('bootout',DOMAIN+'/'+label);require(result.returncode==0,'BOOTOUT_FAILED:'+result.stderr)
    end=time.monotonic()+25
    while time.monotonic()<end:
        current=loaded(label,raw,missing=True)
        if current is None:
            if role!='api':return
            oldpid=(oldjob or {}).get('pid')
            with socket.socket() as sock:
                sock.settimeout(.2);listening=sock.connect_ex(('127.0.0.1',8873))==0
            if not listening and (oldpid is None or not pid_alive(oldpid)):return
        time.sleep(.2)
    raise RuntimeError('UNLOAD_JOB_PID_SOCKET_TIMEOUT_NO_BOOTSTRAP')
def start(role, raw, ownership):
    label=TARGETS[role][0];result=lc('bootstrap',DOMAIN,str(LA/(label+'.plist')))
    require(result.returncode==0,'BOOTSTRAP_FAILED:'+result.stderr)
    ownership[role]={'pid':None}
    end=time.monotonic()+35;last=None
    while time.monotonic()<end:
        try:
            job=loaded(label,raw);ownership[role]=job
            if role=='api':return live_api(raw)
            require(job['pid'] is None and job['state']=='not running','CALENDAR_STARTED_UNEXPECTEDLY');return job
        except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:last=repr(error);time.sleep(.3)
    raise RuntimeError('START_READINESS_TIMEOUT:'+str(last))
def verify_forward():
    sop={}
    for doc,relative in (('overview','docs/SOP.md'),('stage-selection','docs/operations/STAGE_SELECTION_SOP.md'),('repair-20261028-29','docs/operations/records/2026-10-28_29-stage-selection-repair.md')):
        value=api_get('/api/v4/operations/sop?doc='+doc);require(value.get('sha256')==sha((API/'app'/relative).read_bytes()) and value.get('write_performed') is False,'SOP_READBACK_FAILED');sop[doc]=value['sha256']
    pinned(API/'app/config/api-v4_manual_collection_stage_config.json','1fade05041d43e60e253c00f82dbe8a5e8a5815b669dbba62d6e985a11c9a9b9')
    return {'sealed_sop_sha256':sop,'manual_loaded_env_config_pinned':True,'manual_actual_service_execution':'CONTROLLER_PENDING','raw_actual_executed_path':'CONTROLLER_PENDING'}
def restore_touched(touched, records, raws, ownership, event, *, rollback=False):
    """Attempt every owned target independently; never overwrite a conflict."""
    recovery=[];failures=[]
    for role in reversed(touched):
        record=records[role];old,new=raws[role];previous,desired=(new,old) if rollback else (old,new)
        try:
            current=Path(record['path']).read_bytes();require(current in (previous,desired),'ROLLBACK_EXTERNAL_CAS_CONFLICT')
            unload(role,current,ownership.get(role));replace(record,current,previous)
            result=start(role,previous,ownership)
            recovery.append({'role':role,'result':result})
            event('ROLLBACK_TARGET_VERIFIED',role=role,result=result)
        except BaseException as error:
            failure={'role':role,'error':repr(error)};failures.append(failure)
            event('ROLLBACK_TARGET_FAILED',**failure)
    return recovery,failures
def switch(plan_sha, rollback=False):
    pinned(EVIDENCE/'preparation.json',plan_sha);plan=json.loads((EVIDENCE/'preparation.json').read_text());pinned(Path(__file__),plan['script_sha256'])
    records=plan['records'];raws={};ownership={};touched=[];events=[]
    for role,record in records.items():
        old=(EVIDENCE/(role+'.original.plist')).read_bytes();new=(EVIDENCE/(role+'.staged.plist')).read_bytes()
        require(sha(old)==record['original_sha256'] and sha(new)==record['staged_sha256'],'BACKUP_DRIFT');raws[role]=(old,new)
    def event(name,**fields):
        events.append({'event':name,**fields});write_json(EVIDENCE/(f'event-{time.time_ns()}.json'),events[-1]);print(json.dumps(events[-1]),flush=True)
    with guards():
        # Fresh identity/idle/CAS admission under the release mutex and existing
        # manual/announcement submission+execution locks. No task cancellation.
        for role,record in records.items():
            current=raws[role][1 if rollback else 0];cas(record,current);job=loaded(record['label'],current)
            if not rollback:require(job==record['loaded'],'LOADED_JOB_CHANGED_SINCE_PREPARATION:'+role)
            if role!='api':require(job['pid'] is None and job['state']=='not running','CALENDAR_BUSY')
            ownership[role]=job
        assert_idle(ownership['api']['pid']);before_protection=external_protection();before_data=data_protection()
        require(before_protection==plan['protection'],'PROTECTED_BASELINE_CHANGED')
        # A page acceptance request may have created an authentic failure/raw
        # receipt. Rollback preserves that current data; it never restores data
        # snapshots or requires discarding legitimate post-cutover evidence.
        if not rollback:require(before_data==plan['data_protection'],'STAGE_DATA_CHANGED_SINCE_PREPARE')
        inv=tools()
        for role,(_,old,oldsha,new,newsha) in TARGETS.items():verify_release(new,newsha,inv);verify_release(old,oldsha,inv)
        event('ADMISSION_PASS',rollback=rollback)
        try:
            # Arm idle calendar owners first; only API then has a short outage.
            for role in ('stage','pre','api'):
                record=records[role];old,new=raws[role];previous,desired=(new,old) if rollback else (old,new)
                # Track before unload: a failure after a successful bootout but
                # before plist replacement must still restore this exact owner.
                touched.append(role);unload(role,previous,ownership[role]);event('UNLOADED',role=role)
                replace(record,previous,desired);event('PLIST_REPLACED',role=role,sha256=sha(desired))
                result=start(role,desired,ownership);event('STARTED_VERIFIED',role=role,result=result)
            forward={} if rollback else verify_forward()
            require(external_protection()==before_protection,'PROTECTED_BINDINGS_OR_JOBS_CHANGED')
            require(data_protection()==before_data,'STAGE_BUSINESS_DATA_CHANGED')
            event('ROLLBACK_VERIFIED' if rollback else 'ACTIVATED_OPERATIONAL_VERIFIED',postchecks=forward,
                  UI_VERIFIED='CONTROLLER_PENDING',NATURAL_VERIFIED='NOT_RUN')
        except BaseException as primary:
            event('CUTOVER_FAILED',error=repr(primary))
            recovery,failures=restore_touched(touched,records,raws,ownership,event,rollback=rollback)
            if failures:
                event('AUTOMATIC_ROLLBACK_FAILED',primary_error=repr(primary),failures=failures,restored=recovery)
                raise RuntimeError('CUTOVER_FAILED:'+repr(primary)+'; RECOVERY_FAILURES:'+json.dumps(failures)) from primary
            event('AUTOMATIC_ROLLBACK_VERIFIED',restored=recovery);raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','activate','rollback'));parser.add_argument('--plan-sha')
    args=parser.parse_args()
    if args.action=='prepare':prepare()
    else:
        require(bool(args.plan_sha),'PLAN_SHA_REQUIRED');switch(args.plan_sha,rollback=args.action=='rollback')
