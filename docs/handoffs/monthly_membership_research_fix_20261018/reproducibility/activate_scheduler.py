"""Root-owned release integration. Never modifies PDF queue or business source."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import hashlib, importlib.util, json, os, plistlib, re, subprocess, time
from ops.api_release_integration import announcement_flash_cutover_guard, inventory_tree, inventory_digest
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.scheduling.execution_ledger import _ledger_digest

H = Path.cwd() / 'docs/handoffs/monthly_membership_research_fix_20261018'
P = json.loads((H/'ROOT_SCHEDULER_ACTIVATION_PLAN.json').read_text())
LIVE, STAGE, BACKUP = (Path(P[k]) for k in ('live_plist','staged_plist_path','rollback_plist_path'))
CFG, CAND = Path(P['new_config_path']), Path(P['candidate_root'])
OLD = plistlib.loads(BACKUP.read_bytes()); ENV = OLD['EnvironmentVariables']
OUT, ERR = Path(OLD['StandardOutPath']), Path(OLD['StandardErrorPath'])
DOMAIN = 'gui/'+str(os.getuid()); TARGET = DOMAIN+'/com.lexi.v35.scheduler'
TMP = LIVE.with_name('.com.lexi.v35.scheduler.monthly-membership.tmp')
MANAGER = Path(P['manager_state_root']); LEDGER = Path(ENV['V35_DISPATCH_LEDGER_ROOT'])
INDEX = Path(ENV['V35_DATA_ROOT'])/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json'
PDFLOCK = INDEX.parent/'.zsxq_pdf_ingestion.lock'
sha = lambda b: hashlib.sha256(b).hexdigest()
R = {'started_at':datetime.now(timezone.utc).isoformat(),'status':'PRECHECK','controlled_label':'com.lexi.v35.scheduler','selection_submitted_by_root':False,'safety':{'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}}

def run(argv, check=True):
    r = subprocess.run(argv,capture_output=True,text=True,timeout=8)
    if check and r.returncode: raise RuntimeError('COMMAND_FAILED:'+argv[0]+':'+str(r.returncode))
    return r

def pid_of():
    m = re.search(r'^\s*pid = (\d+)\s*$',run(['launchctl','print',TARGET],False).stdout,re.M)
    return int(m.group(1)) if m else None

def children(pid):
    return [int(v) for v in run(['/usr/bin/pgrep','-P',str(pid)],False).stdout.splitlines() if v.isdigit()]

def cwd(pid):
    return next((v[1:] for v in run(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn']).stdout.splitlines() if v.startswith('n')),None)

def alive(pid):
    if pid is None: return False
    try: os.kill(pid,0); return True
    except ProcessLookupError: return False

def records(path,offset=None):
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-524288) if offset is None else offset); raw=f.read()
    rows=[]
    for line in raw.splitlines():
        try:
            row=json.loads(line)
            if isinstance(row,dict): rows.append(row)
        except (ValueError,UnicodeError): pass
    return rows

def no_pdf_handle():
    r=run(['/usr/sbin/lsof','-nP',str(PDFLOCK)],False)
    assert r.returncode in (0,1), 'PDF_LOCK_HANDLE_UNCONFIRMED'
    assert not r.stdout.strip(), 'PDF_LOCK_OPEN'

def non_pdf_checks(pid):
    now=datetime.now(timezone.utc); local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    cycles=[x for x in records(OUT) if x.get('status')=='DAEMON_CYCLE' and x.get('pid')==pid]
    assert cycles and cycles[-1].get('minute')==local.strftime('%Y-%m-%dT%H:%M'),'CURRENT_MINUTE_CYCLE_NOT_CLOSED'
    assert not children(pid),'SCHEDULER_CHILD_ACTIVE'
    for q in (MANAGER/'attempts').glob('*.json'):
        assert json.loads(q.read_text()).get('state') not in ('QUEUED','RUNNING'),'MANAGER_ATTEMPT_ACTIVE'
    for q in (MANAGER/'cursors').glob('oversold_daily_*.json'):
        x=json.loads(q.read_text()); assert x.get('state') not in ('RUNNING','JOB_PENDING'),'OVERSOLD_ACTIVE'
        if x.get('state')=='RETRY_WAIT':
            t=datetime.fromisoformat(str(x.get('next_retry_at')).replace('Z','+00:00'))
            assert t.tzinfo and t>now+timedelta(seconds=45),'OVERSOLD_RETRY_DUE'
    dirs=sorted([d for d in (LEDGER/'claims/live').iterdir() if d.is_dir() and len(d.name)==8 and d.name.isdigit()])[-7:]
    for d in [LEDGER/'claims/live'/local.strftime('%Y%m%d'),LEDGER/'claims/live'/'20261020']:
        if d.is_dir() and d not in dirs: dirs.append(d)
    n=0
    for d in dirs:
        for q in d.glob('*/dispatch.claim.json'):
            n+=1; x=json.loads(q.read_text()); date=q.parent.parent.name; slot=q.parent.name; rid=x.get('run_id')
            receipt=LEDGER/'receipts/live'/date/slot/(str(rid)+'.dispatch-receipt.json')
            assert x.get('schema_version')=='v3_5.dispatch_claim.v1' and x.get('business_date')==date and x.get('slot')==slot and x.get('mode')=='LIVE' and rid and receipt.is_file(),'UNRESOLVED_CLAIM'
            y=json.loads(receipt.read_text()); assert all(y.get(k)==x.get(k) for k in ('run_id','business_date','slot','mode')) and y.get('ledger_sha256')==_ledger_digest(y) and y.get('status')!='FAILED' and all(y.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),'CLAIM_RECEIPT_INVALID'
    return {'active_manager_attempts':0,'active_oversold_cursors':0,'checked_dispatch_claims':n,'closed_cycle_minute':cycles[-1]['minute']}

def install(raw):
    with TMP.open('xb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
    TMP.chmod(0o600);os.replace(TMP,LIVE)

def drain(pid):
    start=time.monotonic()
    while time.monotonic()-start<25:
        if not alive(pid): return {'old_pid_exited':True,'seconds':round(time.monotonic()-start,3)}
        time.sleep(.2)
    raise RuntimeError('OLD_PID_DRAIN_TIMEOUT')

changed=False
try:
    for name,expected in [('INDEPENDENT_REVIEW.json',P['independent_review_sha256'])]:
        assert sha((H/name).read_bytes())==expected,'REVIEW_RECEIPT_DRIFT'
        R[name+'_sha256']=expected
    assert sha(LIVE.read_bytes())==P['base_plist_sha256'] and sha(STAGE.read_bytes())==P['staged_plist_sha256'] and sha(BACKUP.read_bytes())==P['rollback_plist_sha256'],'PLIST_DRIFT'
    assert sha(CFG.read_bytes())==P['new_config_sha256'] and sha((CAND/'release-manifest.json').read_bytes())==P['candidate_manifest_sha256'],'CANDIDATE_DRIFT'
    manifest=json.loads((CAND/'release-manifest.json').read_text()); inv=inventory_tree(CAND/'app')
    assert inv==manifest['application_inventory']['entries'] and inventory_digest(inv)==P['candidate_inventory_sha256'],'INVENTORY_DRIFT'
    staged=plistlib.loads(STAGE.read_bytes()); effective=dict(staged['EnvironmentVariables'])
    for arg in staged['ProgramArguments'][1:]:
        if '=' in arg and not arg.startswith('/'):
            k,v=arg.split('=',1);effective[k]=v
        else: break
    for key in P['effective_identity_checked_keys']: assert effective.get(key)==staged['EnvironmentVariables'].get(key),'INLINE_ENV_IDENTITY_CONFLICT'
    with owned_interprocess_lock(Path(P['release_lock']),timeout_seconds=3,timeout_message='SCHEDULER_RELEASE_LOCK_BUSY'):
      with announcement_flash_cutover_guard(MANAGER,timeout_seconds=3) as flash:
        oldpid=pid_of();assert oldpid is not None and cwd(oldpid)==P['base_app_root'],'ACTIVE_IDENTITY_CHANGED'
        offset=ERR.stat().st_size; deadline=time.monotonic()+55; fresh_tick=None
        while time.monotonic()<deadline:
            ticks=[x for x in records(ERR,offset) if x.get('schema_version')=='v4.zsxq_pdf_queue_tick.v1' and x.get('status') in ('RETRY_BACKOFF','NO_RETRYABLE_TASKS')]
            if ticks: fresh_tick=ticks[-1];fresh_at=time.monotonic();break
            time.sleep(.2)
        assert fresh_tick is not None,'DEFERRED_NO_FRESH_COMPLETED_TICK'
        assert not children(oldpid);no_pdf_handle();before=INDEX.read_bytes();old_index=json.loads(before)
        time.sleep(8)
        assert sha(INDEX.read_bytes())==sha(before) and not children(oldpid),'PDF_QUEUE_NOT_QUIET';no_pdf_handle()
        current_ticks=[x for x in records(ERR,offset) if x.get('schema_version')=='v4.zsxq_pdf_queue_tick.v1'];assert current_ticks and current_ticks[-1]==fresh_tick,'PDF_TICK_CHANGED'
        checks=non_pdf_checks(oldpid);assert time.monotonic()-fresh_at<40,'QUIET_WINDOW_EXPIRED'
        assert sha(LIVE.read_bytes())==P['base_plist_sha256'];assert not children(oldpid);no_pdf_handle()
        R.update(status='CUTOVER',flash_guard=flash,fresh_idle_checks=checks,pdf_quiet_gate={'observed_at':datetime.now(timezone.utc).isoformat(),'fresh_completed_tick':{k:fresh_tick.get(k) for k in ('status','processed_document_count','pending_task_count','retry_after_seconds')},'quiet_seconds':8,'index_sha256':sha(before),'index_document_count':len(old_index.get('documents',{})),'owned_children':0,'open_pdf_lock_handles':0,'elapsed_since_fresh_tick':round(time.monotonic()-fresh_at,3)},pre_identity={'pid':oldpid,'release_id':ENV['V35_RELEASE_ID'],'cwd':cwd(oldpid)})
        outoff,erroff=OUT.stat().st_size,ERR.stat().st_size
        run(['launchctl','bootout',TARGET]);changed=True;R['old_pid_drain']=drain(oldpid)
        assert not children(oldpid);no_pdf_handle();assert sha(INDEX.read_bytes())==sha(before),'QUEUE_CHANGED_DURING_DRAIN'
        stopped=[x for x in records(OUT,outoff) if x.get('status')=='DAEMON_STOPPED' and x.get('pid')==oldpid];assert stopped,'GRACEFUL_STOP_NOT_OBSERVED'
        R['graceful_stop_observed']=True;R['queue_unchanged_before_restart']=True
        install(STAGE.read_bytes());run(['launchctl','bootstrap',DOMAIN,str(LIVE)])
        end=time.monotonic()+25;ready=None
        while time.monotonic()<end:
            newpid=pid_of(); newrows=records(OUT,outoff)
            assert not [x for x in newrows if x.get('release_id')==CAND.name and x.get('status') in ('DAEMON_FATAL','ANNOUNCEMENT_HOOK_DISABLED')],'DAEMON_HOOK_FAILURE'
            matches=[x for x in newrows if x.get('status')=='DAEMON_READY' and x.get('release_id')==CAND.name and x.get('pid')==newpid]
            if matches and cwd(newpid)==str(CAND/'app'):ready=matches[-1];break
            time.sleep(.2)
        assert ready is not None,'DAEMON_READY_NOT_OBSERVED'
        assert all(ready.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),'SAFETY_FLAG_CHANGED'
        loaded=run(['launchctl','print',TARGET]).stdout
        assert all(v in loaded for v in (str(CAND/'app'),CAND.name,P['candidate_manifest_sha256'],str(CFG))),'LOADED_BINDING_MISMATCH'
        assert sha(LIVE.read_bytes())==P['staged_plist_sha256'] and inventory_tree(CAND/'app')==inv
        after=json.loads(INDEX.read_text());assert set(old_index.get('documents',{}))<=set(after.get('documents',{})),'QUEUE_DOCUMENT_LOST'
        R.update(status='DEPLOYED_LOADED_IDENTITY_VERIFIED',post_identity={'pid':newpid,'release_id':CAND.name,'cwd':cwd(newpid),'plist_sha256':sha(LIVE.read_bytes()),'manifest_sha256':P['candidate_manifest_sha256'],'config_sha256':sha(CFG.read_bytes())},daemon_ready={k:ready.get(k) for k in ('status','release_id','pid','production_allowed','buy_gate_updated','orders_sent','pdf_queue_drain')},pdf_resume_log_offset=erroff,queue_document_ids_preserved=True,rollback_performed=False,API_or_digest_service_actions=False)
except Exception as exc:
    R.update(status='DEFERRED_OR_FAILED',error_type=type(exc).__name__,error=str(exc))
    if changed:
        current=pid_of();run(['launchctl','bootout',TARGET],False);drain(current);install(BACKUP.read_bytes());run(['launchctl','bootstrap',DOMAIN,str(LIVE)]);R['rollback_performed']=True
R['finished_at']=datetime.now(timezone.utc).isoformat()
(H/'ROOT_SCHEDULER_BETWEEN_TICK_ACTIVATION_RECEIPT.json').write_text(json.dumps(R,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(R,ensure_ascii=False));raise SystemExit(0 if R['status']=='DEPLOYED_LOADED_IDENTITY_VERIFIED' else 3)
