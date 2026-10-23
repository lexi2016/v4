"""One scoped event-only waiting executor; no business/control code mutation."""
import datetime, hashlib, json, os, plistlib, re, select, subprocess, sys, time
from pathlib import Path
W=Path(__file__).resolve().parent;O=W.parent;E=O.parents[1];sys.path.insert(0,str(O))
import control_prepare as c
import activation_driver as driver
CAP=E/'ledger/activation-action-capsule-r2-event.json';CAP_SHA='ecda86a7d4abbb6326066742c8c5cca7378f703d7d815d848e7a7533e79c4e46'
SCOPE=E/'ledger/event-continuation-scope.json';SCOPE_SHA='1504759ab8bd48c69428bdc466db323783d914c0277ccf25bc2c0e6c94ba44cf'
assert hashlib.sha256(SCOPE.read_bytes()).hexdigest()==SCOPE_SHA
PRIOR_PATH=O/'tdx-daily-closure-r2-after1800-20261023-activate.json'
assert hashlib.sha256(PRIOR_PATH.read_bytes()).hexdigest()=='22410f6af09eec282f2f8067f21e8df64f01adf79ea056644c939be8643f3dcd'
PRIOR=json.loads(PRIOR_PATH.read_bytes());assert PRIOR['phase']=='PREFLIGHT' and PRIOR['live_mutated'] is False
WINDOW_START=datetime.datetime.now(datetime.timezone.utc)
REMAINING=600
START=time.monotonic();DEADLINE=START+REMAINING
authority_active=True
STATE={'schema':'v4.producer_event_wait.v1','owner':'/root/tdx_activation_owner','executor_pid':os.getpid(),'started_at_utc':WINDOW_START.isoformat(),'executor_started_at_utc':WINDOW_START.isoformat(),'prior_waiter':'No live waiter; prior two driver attempts stopped at PREFLIGHT with zero mutation','deadline_at':(WINDOW_START+datetime.timedelta(seconds=REMAINING)).isoformat(),'scope_sha256':SCOPE_SHA,'phase':'VALIDATING','driver_invocations':0,'live_service_mutations_by_waiter':False,'source_business_calls':0,'events':[]}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save():
    STATE['updated_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();p=W/'state-event-r2.json';tmp=W/'state-event-r2.json.tmp';tmp.write_text(json.dumps(STATE,ensure_ascii=False,indent=2,sort_keys=True)+'\n');os.replace(tmp,p)
def log(event,**values):
    row={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'event':event,**values}
    with (W/'events-event-r2.jsonl').open('a') as stream:stream.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    STATE['events']=(STATE['events']+[row])[-32:];save();print(json.dumps(row,ensure_ascii=False),flush=True)
def run(cmd):return subprocess.run(cmd,capture_output=True,text=True,timeout=10,check=True).stdout

cap,packet=driver.load_capsule(CAP,CAP_SHA,'activate');ops=driver.RealOps(packet)
expected=plistlib.loads(Path(packet['original_plist']).read_bytes());env=expected['EnvironmentVariables'];root=Path(env['V35_DATA_ROOT']);ledger=Path(env['V35_DISPATCH_LEDGER_ROOT']);oldpid=cap['expected_start_pid']
sys.path.insert(0,packet['baseline_app'])
from infrastructure.zsxq_pdf_ingestion import pending_pdf_tasks,_latest_engine_run,STATE_RELATIVE
index_path=root/STATE_RELATIVE

def identity():
    driver.require(sha(CAP)==CAP_SHA,'capsule drift')
    driver.require(c.sha(c.PLIST)==packet['original_plist_sha256'],'live plist drift')
    driver.require(ops.override()=='enabled','original enabled override drift')
    driver.require(ops.registration(expected)==oldpid,'unexpected producer PID/release identity')

def children():
    table=run(['ps','-axo','pid=,ppid=']);return c.descendants(oldpid,[tuple(map(int,row.split())) for row in table.splitlines()])

def pdf():
    before=index_path.read_bytes();index=json.loads(before);pending=pending_pdf_tasks(root);after=index_path.read_bytes()
    if before!=after:return None  # defer until next real index event, never blind retry
    latest=[x for row in index['documents'].values() if (x:=_latest_engine_run(row))]
    return {'sha256':hashlib.sha256(after).hexdigest(),'retryable':len(pending),'processing':sum(x[1].get('status')=='PROCESSING' for x in latest)}


def diagnostic_process_identity(pid):
    """No environment or raw argv/stderr output; strict partial identity only."""
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:
        return {'status':'CANNOT_CONFIRM','reason':'positive integer PID unavailable'}
    result=subprocess.run(['ps','-p',str(pid),'-o','pid=,ppid=,lstart=,args='],capture_output=True,text=True,timeout=3)
    if result.returncode!=0:return {'status':'CANNOT_CONFIRM','reason':'process identity unavailable','exit_code':result.returncode}
    fields=result.stdout.strip().split(None,7)
    if len(fields)!=8 or fields[0]!=str(pid) or not fields[1].isdigit() or not re.fullmatch(r'[A-Za-z]{3} [A-Za-z]{3} [0-9]{1,2} [0-9:]{8} [0-9]{4}',' '.join(fields[2:7])):
        return {'status':'CANNOT_CONFIRM','reason':'process identity format unavailable'}
    output={'pid':pid,'ppid':int(fields[1]),'process_start':' '.join(fields[2:7]),'status':'PARTIAL_IDENTITY','argv_status':'CANNOT_CONFIRM_NOT_ALLOWLISTED','argv':[]}
    executables={sys.executable,str(Path(packet['runtime_root'])/'venvs/v3.5-mac/bin/python'),'/usr/bin/python3','/Applications/Xcode.app/Contents/Developer/usr/bin/python3'}
    raw=fields[7]
    for executable in sorted(executables,key=len,reverse=True):
        if raw==executable or raw.startswith(executable+' '):
            argv=[executable];tokens=raw[len(executable):].split();safe_flags={'-B','-S','-u','-s','-E','-I'}
            while tokens and tokens[0] in safe_flags:argv.append(tokens.pop(0))
            modules={'ops.run_v35_macos_scheduler_daemon','ops.macos_research_panel_daily_authority','ops.macos_research_panel_daily_gate','ops.a_share_daily_sync'}
            if len(tokens)>=2 and tokens[0]=='-m' and tokens[1] in modules:argv.extend(tokens[:2])
            output.update(argv=argv,argv_status='ALLOWLISTED_PREFIX_ONLY',unlisted_arguments_omitted=True)
            break
    return output


def log_other_owner_stop(row):
    """Diagnostic failures never replace the original guard's STOP."""
    diagnostic={key:row.get(key) for key in ['path','pid','run_id','workload_id','receipt_path','sha256']}
    diagnostic['receipt_state']=row.get('state');diagnostic['identity_observed_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:diagnostic['process_identity']=diagnostic_process_identity(row.get('pid'))
    except Exception as error:diagnostic['process_identity']={'status':'CANNOT_CONFIRM','error_type':type(error).__name__}
    STATE['other_live_owner_stop_diagnostic']=diagnostic
    try:log('OTHER_LIVE_OWNER_STOP_DIAGNOSTIC',diagnostic=diagnostic)
    except Exception:pass


def claims():
    rows=c.claims_observation(ledger,oldpid);active=[]
    for row in rows:
        if row.get('pid')==oldpid and row['state']!='TERMINAL_MATCH':
            driver.require(row['state']=='ACTIVE_OR_UNCONFIRMED','invalid current owned claim receipt')
            active.append({k:row.get(k) for k in ['path','run_id','workload_id','receipt_path','sha256']})
        elif row.get('pid')!=oldpid and row['state']!='TERMINAL_MATCH':
            other_owner_allowed=row.get('pid') and not ops.pid_alive(row['pid'])
            if not other_owner_allowed:log_other_owner_stop(row)
            driver.require(other_owner_allowed,'other healthy live owner claim')
    return active

def admissible(state):
    if state['children'] or state['pdf'] is None or state['pdf']['retryable'] or state['pdf']['processing']:return False
    return all('/20261023/1730/' in row['path'] and row['workload_id'] in {None,'preselection_pools','research_panel_runtime_evidence'} for row in state['active_claims'])

queue=select.kqueue();fds={};fdpaths={};proc_pids=set()

def watch_path(p):
    p=Path(p)
    if not p.exists():return
    old=fds.get(str(p))
    if old is not None:
        try:
            if os.fstat(old).st_ino==p.stat().st_ino:return
        except OSError:pass
        try:queue.control([select.kevent(old,filter=select.KQ_FILTER_VNODE,flags=select.KQ_EV_DELETE)],0,0)
        except OSError:pass
        os.close(old);fdpaths.pop(old,None)
    fd=os.open(p,getattr(os,'O_EVTONLY',os.O_RDONLY));fds[str(p)]=fd;fdpaths[fd]=str(p)
    flags=select.KQ_NOTE_WRITE|select.KQ_NOTE_RENAME|select.KQ_NOTE_DELETE|select.KQ_NOTE_EXTEND|select.KQ_NOTE_ATTRIB
    queue.control([select.kevent(fd,filter=select.KQ_FILTER_VNODE,flags=select.KQ_EV_ADD|select.KQ_EV_CLEAR,fflags=flags)],0,0)

def watch_pid(pid):
    if pid in proc_pids:return
    try:queue.control([select.kevent(pid,filter=select.KQ_FILTER_PROC,flags=select.KQ_EV_ADD|select.KQ_EV_ONESHOT,fflags=select.KQ_NOTE_EXIT)],0,0);proc_pids.add(pid)
    except ProcessLookupError:pass

pool_dir=root/'preselection_pools/20261026';protected_pins={}
for ref in cap['protected_bindings']:
    driver.require(sha(ref['path'])==ref['sha256'],'protected binding receipt drift')
    doc=json.loads(Path(ref['path']).read_bytes());protected_pins.update(doc['protected_files']);protected_pins.update(doc.get('protected_replacement',{}))
protected_paths=[Path(p) for p in protected_pins]
# Observe only already packet-bound authority/source/config bytes on exact vnode events.
authority_pins={str(CAP):CAP_SHA,str(c.BINDING):cap['source_binding_sha256'],str(O/'activation_driver.py'):cap['driver_sha256'],str(O/'control_prepare.py'):cap['control_prepare_sha256'],str(O/'pdf_readonly.py'):cap['pdf_readonly_sha256'],cap['prepared_packet_path']:cap['prepared_packet_sha256'],packet['release_manifest']:packet['release_manifest_sha256'],packet['candidate_plist']:packet['candidate_plist_sha256'],packet['original_plist']:packet['original_plist_sha256'],packet['manager_config_path']:packet['manager_config_sha256']}
for rel,want in packet['source_sha256'].items():authority_pins[str(Path(packet['candidate_app'])/rel)]=want
for key in ['independent_source_review','independent_control_review']:
    ref=cap[key];authority_pins[ref['path']]=ref['sha256']

def source_authority_identity():
    for path,want in authority_pins.items():driver.require(sha(path)==want,'source/config/authority drift: '+path)

def subscribe_claim_paths(active_claims):
    # Original observation supplies exact owned claim/receipt relatives, including
    # newly observed cycles. Missing receipt files are watched through their parent.
    for row in active_claims:
        for key in ['path','receipt_path']:
            relative=Path(row[key]);driver.require(not relative.is_absolute() and '..' not in relative.parts,'owned event path escape')
            path=ledger/relative
            for observed_path in [path.parent,path]:
                if observed_path not in watched:watched.append(observed_path)
                watch_path(observed_path)

watched=[index_path,index_path.parent,c.PLIST,c.PLIST.parent,*protected_paths,*{p.parent for p in protected_paths},*[Path(p) for p in authority_pins],pool_dir,pool_dir/'receipts']
claim_days=[ledger/kind/'live/20261023' for kind in ['claims','workloads','receipts']]
watched.extend(claim_days)

def subscribe_slot_parents():
    # Initial subscription and actual day-directory events only. Register existing
    # owned slot parents before claim observation, closing the observed-claim race.
    for day in claim_days:
        if not day.is_dir():continue
        for slot in day.iterdir():
            if re.fullmatch(r'[0-9]{4}',slot.name) and slot.is_dir() and not slot.is_symlink():
                if slot not in watched:watched.append(slot)
                watch_path(slot)

try:
    driver.require(not (W/'activation.started').exists(),'one activation already attempted by this owner')
    identity();source_authority_identity();ops.verify_protected(cap['protected_bindings']);watch_pid(oldpid)
    for p in watched:watch_path(p)
    subscribe_slot_parents()
    STATE['phase']='WAITING_RELEVANT_EVENT';STATE['capsule_sha256']=CAP_SHA;STATE['packet_sha256']=cap['prepared_packet_sha256']
    observed={'children':children(),'pdf':pdf(),'active_claims':claims()};STATE['guarded_state']=observed
    subscribe_claim_paths(observed['active_claims'])
    for pid in observed['children']:watch_pid(pid)
    log('WAIT_OWNER_STARTED',state=observed)
    # No periodic state/mtime/protected scan. Only real kernel events below
    # trigger relevant observations. An empty timeout only returns to kqueue.
    while not (admissible(observed) and authority_active):
        remaining=DEADLINE-time.monotonic()
        if remaining<=0:
            STATE['phase']='COMPLETION_PENDING_AUDIT';STATE['next_condition']='exact observed owned claims/receipt/PDF/child event clears original unchanged admission; source/PID/config/protected identity must remain pinned';log('BOUNDED_WAIT_PENDING',state=observed);raise SystemExit(3)
        events=queue.control(None,64,min(60,remaining))
        if not events:continue
        paths={fdpaths.get(event.ident) for event in events if event.filter==select.KQ_FILTER_VNODE}
        exited={int(event.ident) for event in events if event.filter==select.KQ_FILTER_PROC}
        if paths & {str(day) for day in claim_days}:subscribe_slot_parents()
        driver.require(oldpid not in exited,'old producer PID exited unexpectedly while waiting')
        if c.PLIST.as_posix() in paths:identity()
        if paths & set(authority_pins):source_authority_identity()
        if any(str(p) in paths for p in [*protected_paths,*{p.parent for p in protected_paths},pool_dir,pool_dir/'receipts']):ops.verify_protected(cap['protected_bindings'])
        relevant_pdf=bool(paths & {str(index_path),str(index_path.parent)})
        relevant_claim=any(p and p.startswith(str(ledger)) for p in paths)
        changed={}
        if relevant_pdf:
            new_pdf=pdf()
            if new_pdf is None:
                log('PDF_READ_COHERENCE_PENDING',next_condition='next actual index write/replace event')
            elif new_pdf!=observed['pdf']:observed['pdf']=new_pdf;changed['pdf']=new_pdf
        if exited or relevant_claim:
            new_children=children();new_claims=claims()
            if new_children!=observed['children']:observed['children']=new_children;changed['children']=new_children
            if new_claims!=observed['active_claims']:observed['active_claims']=new_claims;changed['active_claims']=new_claims
        subscribe_claim_paths(observed['active_claims'])
        for p in watched:watch_path(p)
        for pid in observed['children']:watch_pid(pid)
        STATE['guarded_state']=observed
        if changed:log('RELEVANT_PROGRESS',changed=changed)
    # Qualifying real progress (or initial state now clear) reached guarded
    # eligibility. One exact final readback, then ONE unchanged reviewed driver.
    identity();source_authority_identity();ops.verify_protected(cap['protected_bindings']);observed={'children':children(),'pdf':pdf(),'active_claims':claims()};driver.require(admissible(observed),'admission changed before single activation; no driver invoked')
    STATE['guarded_state']=observed;STATE['phase']='ACTIVATING_ONCE';STATE['driver_invocations']=1
    command=[sys.executable,'-B',str(O/'activation_driver.py'),'--capsule',str(CAP),'--capsule-sha256',CAP_SHA,'--action','activate']
    (W/'activation.started').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':command})+'\n');log('ADMISSION_CLEAR_EXECUTING_ONCE',command=command)
    with (W/'driver.stdout').open('w') as out,(W/'driver.stderr').open('w') as err:
        child=subprocess.Popen(command,stdout=out,stderr=err,cwd=O);STATE['driver_pid']=child.pid;save();rc=child.wait()
    STATE['driver_exit_code']=rc
    if rc==0:
        STATE['phase']='DRIVER_SUCCESS';log('DRIVER_SUCCESS',driver_receipt=str(O/(cap['operation_id']+'-activate.json')))
    elif rc==3:
        STATE['phase']='DRAIN_PENDING_PRESERVED';log('DRAIN_PENDING_PRESERVED',reason='healthy disabled process retained; exactPID exit event and same-capsule --resume required, no TERM repetition')
    else:
        STATE['phase']='DRIVER_STOPPED';log('DRIVER_STOPPED',exit_code=rc)
except SystemExit:raise
except Exception as error:
    STATE['phase']='STOPPED_GUARD';STATE['error']=f'{type(error).__name__}: {error}';log('STOPPED_GUARD',error=STATE['error'])
finally:
    queue.close()
    for fd in fds.values():
        try:os.close(fd)
        except OSError:pass
    save()
