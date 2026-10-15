"""Activate only the independently reviewed HK code/pointer bindings, with rollback."""
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime,timezone
import collections,ctypes,hashlib,importlib.util,json,os,plistlib,re,stat,subprocess,sys,time
import urllib.request,urllib.error,urllib.parse

H=Path(__file__).resolve().parent;ROOT=H.parents[2];sys.path.insert(0,str(ROOT))
from ops import api_release_integration as integration
from ops.prepare_api_only_cutover import extract_environment
from infrastructure.interprocess_lock import owned_interprocess_lock
PUB=json.loads((H/'PUBLICATION_RECEIPT.json').read_text());BIND=json.loads((H/'PREACTIVATION_BINDINGS.json').read_text())['bindings']
OWNER=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2')
EVENTS=[];R=dict(status='PREPARING',commands=EVENTS,rollback_performed=False,started_at=datetime.now(timezone.utc).isoformat(),
    production_allowed=False,buy_gate_updated=False,orders_sent=False,research_only=True)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def write(name,obj):(H/name).write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def now():return datetime.now(timezone.utc).isoformat()
def flush():write('ACTIVATION_RECEIPT.json',R)
def command(args,allowed=(0,),filter_status=False):
    began=now();p=subprocess.run(args,capture_output=True,text=True)
    output=p.stdout
    if filter_status:output='\n'.join(l.strip() for l in output.splitlines() if re.match(r'\s*(pid|state|path|program|last exit code) =',l))
    EVENTS.append(dict(command=args,started_at=began,finished_at=now(),exit_code=p.returncode,stdout=output,stderr=p.stderr));flush()
    if p.returncode not in allowed:raise RuntimeError('COMMAND_FAILED:'+args[0]+':'+str(p.returncode))
    return p.stdout
def service(role):
    label='com.lexi.v35.api-only' if role=='api' else 'com.lexi.v35.scheduler'
    raw=command(['launchctl','print',f'gui/{os.getuid()}/{label}'],filter_status=True)
    match=re.search(r'^\s*pid = (\d+)$',raw,re.M);assert match and re.search(r'^\s*state = running$',raw,re.M)
    return int(match.group(1))
def cwd(pid):
    raw=command(['lsof','-a','-p',str(pid),'-d','cwd','-Fn'])
    return next(l[1:] for l in raw.splitlines() if l.startswith('n'))
def alive(pid):
    try:os.kill(int(pid),0);return True
    except (ProcessLookupError,ValueError,TypeError):return False
def live_environment(pid,keys):
    libc=ctypes.CDLL(None,use_errno=True);mib=(ctypes.c_int*3)(1,49,pid);buf=ctypes.create_string_buffer(1024*1024);size=ctypes.c_size_t(len(buf))
    if libc.sysctl(mib,3,buf,ctypes.byref(size),None,0)!=0:raise OSError(ctypes.get_errno(),'selected process environment unavailable')
    raw=buf.raw[:size.value];argc=int.from_bytes(raw[:4],sys.byteorder);offset=raw.index(b'\0',4)+1
    while offset<len(raw) and raw[offset]==0:offset+=1
    for _ in range(argc):offset=raw.index(b'\0',offset)+1
    selected={}
    for item in raw[offset:].split(b'\0'):
        if b'=' not in item:continue
        key,value=item.split(b'=',1);key=key.decode(errors='replace')
        if key in keys:selected[key]=value.decode(errors='replace')
    return selected
def process_table():
    raw=subprocess.run(['ps','-axo','pid=,ppid=,lstart=,comm='],capture_output=True,text=True,check=True).stdout
    rows={}
    for line in raw.splitlines():
        match=re.match(r'\s*(\d+)\s+(\d+)\s+(.{24})\s+(.+)',line)
        if match:rows[int(match[1])]=(int(match[2]),match[3],match[4])
    return rows
def queue_snapshot(pids):
    table=process_table();healthy=[];legacy=[];summaries=[]
    roots=[Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/jobs'),
        Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/attempts')]
    for root in roots:
        counts=collections.Counter()
        for path in sorted(root.glob('*.json')):
            obj=json.loads(path.read_text());state=str(obj.get('state',obj.get('status','UNKNOWN'))).upper();counts[state]+=1
            if state not in ['QUEUED','RUNNING']:continue
            pid=obj.get('owner_pid',obj.get('pid'));item=dict(relative=path.name,state=state,owner_pid=pid,updated_at=obj.get('updated_at'))
            if pid and not alive(pid):item['reason']='OWNER_ABSENT';legacy.append(item);continue
            if pid in table and obj.get('updated_at'):
                started=datetime.strptime(table[pid][1],'%a %b %d %H:%M:%S %Y').astimezone()
                updated=datetime.fromisoformat(obj['updated_at'].replace('Z','+00:00'))
                if started>updated:item['reason']='PID_REUSED_AFTER_LAST_UPDATE';legacy.append(item);continue
            healthy.append(item)
        summaries.append(dict(root=str(root),counts=dict(counts)))
    ledger=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher');day=datetime.now().strftime('%Y%m%d')
    completed={json.loads(p.read_text()).get('run_id') for p in (ledger/'receipts/live'/day).glob('*/*.json')}
    for path in (ledger/'claims/live'/day).glob('*/*.json'):
        obj=json.loads(path.read_text())
        if obj.get('run_id') not in completed and alive(obj.get('pid')):
            healthy.append(dict(kind='DISPATCH_CLAIM_WITHOUT_COMPLETED_RECEIPT',relative=str(path.relative_to(ledger)),owner_pid=obj.get('pid')))
    descendants=[];parents=set(pids)
    while True:
        children={pid for pid,row in table.items() if row[0] in parents}-parents
        if not children:break
        descendants.extend(dict(pid=pid,parent_pid=table[pid][0],command=table[pid][2]) for pid in children);parents|=children
    return dict(healthy=healthy,legacy_active_metadata=legacy,roots=summaries,service_descendants=descendants,
                drained=not healthy and not descendants,records_modified=False)
def get(route):
    with urllib.request.urlopen('http://127.0.0.1:8873'+route,timeout=30) as response:return response.status,json.load(response)
def A_control():
    status,body=get('/api/v3/stage-center/selection?date=20261015&stage=STAGE_0940_0945&limit=1');a=body['markets']['A'];digest=hashlib.sha256(canonical(a)).hexdigest()
    assert status==200 and digest=='2d709f625c7dff8d81a3777e2bcf672b00a8156278a01febff5403055928c0fb'
    assert a['artifact_id']=='selection-b37a1ee172cd45451d78e35b' and a['run_id']=='run-b37a1ee172cd45451d78e35b' and a['status']=='PARTIAL_WITH_ROWS'
    return dict(http_status=status,sha256=digest,artifact_id=a['artifact_id'],run_id=a['run_id'],status=a['status'],rows_exported=False)
def protect():
    source=json.loads((ROOT/'docs/handoffs/hk_history_live_unification_20261015/SOURCE_MOVE_RECEIPT.json').read_text());refs=[]
    for package in source['owner_packages_after'].values():
        assert Path(package['path']).stat().st_ino==package['inode'];refs+=package['files']
    def walk(obj):
        if isinstance(obj,dict):
            if 'path' in obj and 'sha256' in obj:refs.append(obj)
            else:
                for value in obj.values():walk(value)
    walk(source['protected_state_before_after']['C_panel_model']['after'])
    refs.append(dict(path=str(OWNER/'research_history.json'),sha256='71e168716374b306e7bebb71da5d00b2b5bfe9bf0f3c91010a12902a6954802e'))
    for ref in refs:
        path=Path(ref['path']);assert sha(path)==ref['sha256']
        if 'inode' in ref:assert path.stat().st_ino==ref['inode']
        if 'size_bytes' in ref:assert path.stat().st_size==ref['size_bytes']
    return dict(file_count=len(refs),two_directory_inodes_preserved=True,source_panel_model_SHA_unchanged=True)
def verify_candidates():
    for role in ['shared','scheduler','materializer','reviewcore']:
        d=PUB[role];manifest=Path(d['candidate_root'])/'release-manifest.json';assert sha(manifest)==d['manifest_sha256'];obj=json.loads(manifest.read_text())
        current=integration.inventory_tree(Path(d['app_root']));assert current==obj['application_inventory']['entries']
        base=[r for r in integration.inventory_tree(Path(d['base_root'])) if not any(p in ['.runtime','__pycache__','.pytest_cache'] for p in Path(r['path']).parts)]
        assert integration.inventory_digest(base)==obj['base']['inventory_sha256']
        changed={r['path'] for r in obj['delta_entries']};assert [r for r in base if r['path'] not in changed]==[r for r in current if r['path'] not in changed]
def atomic(path,raw):
    began=now()
    temp=path.with_name('.'+path.name+'.hk-adjudication-staged')
    assert not temp.exists();mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    with os.fdopen(fd,'wb') as file:file.write(raw);file.flush();os.fsync(file.fileno())
    os.replace(temp,path)
    R.setdefault('atomic_installs',[]).append(dict(path=str(path),sha256=sha(path),started_at=began,finished_at=now(),atomic=True));flush()
def online():
    expected=json.loads((H/'ENFORCEMENT_RECEIPT.json').read_text());results=[]
    for pin in expected['api_canaries']:
        item=dict(date=pin['date'])
        for mode in ['usable','audit']:
            params=urllib.parse.urlencode(dict(symbol='HK.00001',start=pin['date'],end=pin['date'],mode=mode,limit=1));began=time.monotonic()
            status,body=get('/api/v4/manager-workbench/hk-history?'+params);data=body['data'];assert status==200 and body['state']=='READY'
            assert all(body[k] is False for k in ['production_allowed','buy_gate_updated','orders_sent']) and data['scoring_allowed'] is False
            assert '/Users/' not in json.dumps(body)
            digest=hashlib.sha256(canonical(data)).hexdigest();assert digest==pin[mode]['data_sha256'],(pin['date'],mode,'LIVE_PAYLOAD_MISMATCH')
            item[mode]=dict(http_status=status,data_sha256=digest,row_count=len(data['rows']),quarantine_count=data['quarantine_count'],elapsed_seconds=round(time.monotonic()-began,3))
        results.append(item)
    invalid=[]
    for params in [dict(symbol='bad'),dict(symbol='HK.00001',fields='bad'),dict(symbol='HK.00001',mode='bad'),dict(symbol='HK.00001',limit=201)]:
        try:get('/api/v4/manager-workbench/hk-history?'+urllib.parse.urlencode(params));raise AssertionError('INVALID_QUERY_ACCEPTED')
        except urllib.error.HTTPError as error:invalid.append(error.code)
    assert invalid==[422]*4
    return dict(canaries=results,invalid_http_statuses=invalid,A_control=A_control(),raw_market_values_exported=False)
def main():
    assert not (H/'ACTIVATION_RECEIPT.json').exists(),'No blind activation retry'
    review=json.loads((H/'CANDIDATE_REVIEW_R2.json').read_text());assert review['verdict']=='PASS' and review['findings']==[]
    paths={role:Path(d['active_plist_path']) for role,d in BIND.items()};before={role:(H/f'{role}.plist.before').read_bytes() for role in paths};staged={role:(H/f'{role}.plist.staged').read_bytes() for role in paths}
    pointer=OWNER/'history_resolution_latest.json';pointer_raw=(H/'history_resolution_latest.staged.json').read_bytes();assert not pointer.exists()
    stopped=set();started=set();changed=set();pointer_installed=False
    with ExitStack() as stack:
        lease=stack.enter_context(integration.shared_api_release_lock(paths['api'],timeout_seconds=2))
        for lock in ['.com.lexi.v35.scheduler.release.lock','com.lexi.v35.scheduler.release.lock']:
            stack.enter_context(owned_interprocess_lock(paths['scheduler'].parent/lock,timeout_seconds=2,timeout_message='SCHEDULER_RELEASE_LOCK_BUSY'))
        R['locks']=['API_SHARED','.com.lexi.v35.scheduler.release.lock','com.lexi.v35.scheduler.release.lock']
        for role,path in paths.items():
            assert sha(path)==BIND[role]['before_sha256'] and path.read_bytes()==before[role],'SELECTED_PLIST_CAS_DRIFT'
            assert hashlib.sha256(staged[role]).hexdigest()==BIND[role]['staged_sha256']
        verify_candidates();R['API_base_verification']=integration.verify_api_release_candidate(candidate_root=Path(PUB['api']['candidate_root']),active_api_plist_path=paths['api'],expected_manifest_sha256=PUB['api']['manifest_sha256'],active_pointer='base',lock_lease=lease,require_shared_lock=True)
        pids={role:service(role) for role in paths};R['before_PIDs']=pids
        for role,pid in pids.items():assert cwd(pid)==extract_environment(plistlib.loads(before[role]))['V35_APP_ROOT']
        R['protected_before']=protect();R['A_before']=A_control()
        api_env=extract_environment(plistlib.loads(before['api']));config_path=Path(api_env['V4_MANAGER_WORKBENCH_CONFIG_PATH']);config=json.loads(config_path.read_text())
        assert config['manager_root']==api_env['V4_MANAGER_RESEARCH_STATE_ROOT']
        assert Path(config['shared_root']).resolve()==OWNER.parent.parent
        R['effective_manager_roots']=dict(config_path=str(config_path),config_sha256=sha(config_path),manager_root=config['manager_root'],state_root=config['state_root'],shared_root=config['shared_root'])
        while True:
            snapshot=queue_snapshot(list(pids.values()));R['drain']=snapshot;flush()
            if snapshot['drained'] and 10<=datetime.now().second<=35:break
            print(json.dumps(dict(status='WAIT_HEALTHY_DRAIN',healthy=len(snapshot['healthy']),descendants=len(snapshot['service_descendants']))),flush=True);time.sleep(15)
        for role,path in paths.items():assert path.read_bytes()==before[role]
        R['drain_immediately_before_stop']=queue_snapshot(list(pids.values()));assert R['drain_immediately_before_stop']['drained']
        try:
            for role in ['scheduler','api']:
                label='com.lexi.v35.scheduler' if role=='scheduler' else 'com.lexi.v35.api-only'
                command(['launchctl','bootout',f'gui/{os.getuid()}/{label}']);stopped.add(role)
                while alive(pids[role]):time.sleep(.5)
            atomic(pointer,pointer_raw);pointer_installed=True;R['owner_pointer_sha256']=sha(pointer)
            for role,path in paths.items():atomic(path,staged[role]);changed.add(role)
            for role in ['api','scheduler']:
                command(['launchctl','bootstrap',f'gui/{os.getuid()}',str(paths[role])]);started.add(role)
            for _ in range(120):
                try:R['A_after_start']=A_control();break
                except (OSError,urllib.error.URLError):time.sleep(.5)
            else:raise RuntimeError('API_STARTUP_FAILED')
            R['API_candidate_verification']=integration.verify_api_release_candidate(candidate_root=Path(PUB['api']['candidate_root']),active_api_plist_path=paths['api'],expected_manifest_sha256=PUB['api']['manifest_sha256'],active_pointer='candidate',lock_lease=lease,require_shared_lock=True)
            R['after_services']={}
            selected=['V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256','V35_SHARED_PACKAGE_ROOT','V4_MANAGER_MATERIALIZER_APP_ROOT','V4_MANAGER_MATERIALIZER_SHA256','V35_REVIEW_CORE_PACKAGE_ROOT','V4_MANAGER_RESEARCH_STATE_ROOT','V35_SHARED_DATA_ROOT']
            for role in paths:
                pid=service(role);assert pid!=pids[role] and cwd(pid)==PUB[role]['app_root']
                expected=extract_environment(plistlib.loads(staged[role]));actual=live_environment(pid,selected)
                assert actual=={k:expected[k] for k in selected if k in expected},'LIVE_EFFECTIVE_BINDING_MISMATCH'
                R['after_services'][role]=dict(pid=pid,cwd=PUB[role]['app_root'],selected_environment=actual,plist_sha256=sha(paths[role]))
            result=online();R['protected_after']=protect();verify_candidates()
            assert sha(config_path)==R['effective_manager_roots']['config_sha256']
            R['queue_after']=queue_snapshot([d['pid'] for d in R['after_services'].values()])
            assert pointer.read_bytes()==pointer_raw
            R.update(status='ACTIVATED_WRITER_ONLINE_PASS_PENDING_INDEPENDENT_REVIEW',finished_at=now(),rollback_chain_preserved=True)
            result.update(status='WRITER_ONLINE_PASS_PENDING_INDEPENDENT_REVIEW',observed_at=now(),services=R['after_services'],owner_pointer_sha256=sha(pointer),model_status='HOLD',actual_model_score_count=0,model_reason='HK_HISTORY_RESOLUTION_PROXY_UNIVERSE_INSUFFICIENT',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
            write('ONLINE_RECEIPT.json',result);flush()
        except BaseException as error:
            R.update(status='ACTIVATION_FAILED',failure=dict(type=type(error).__name__,message=str(error)));flush()
            for role in ['scheduler','api']:
                if role in started:
                    command(['launchctl','bootout',f"gui/{os.getuid()}/"+('com.lexi.v35.scheduler' if role=='scheduler' else 'com.lexi.v35.api-only')]);started.remove(role)
                if role in changed:atomic(paths[role],before[role])
            if pointer_installed:pointer.unlink()
            for role in ['api','scheduler']:
                if role in stopped:command(['launchctl','bootstrap',f'gui/{os.getuid()}',str(paths[role])])
            R['rollback_performed']=bool(stopped);R['finished_at']=now();flush();raise
    print(json.dumps(dict(status=R['status'],services=R.get('after_services'),rollback_performed=R['rollback_performed']),sort_keys=True))

if __name__=='__main__':
    try:main()
    except BaseException as error:
        if R['status']=='PREPARING':R.update(status='PREACTIVATION_BLOCKED_NO_SERVICE_MUTATION',failure=dict(type=type(error).__name__,message=str(error)),finished_at=now());flush()
        raise
