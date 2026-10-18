"""Root-owned guarded cutover; business bytes and config remain frozen."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess,time,urllib.request,plistlib
from ops import api_release_integration as integ
H=Path.cwd()/'docs/handoffs/monthly_membership_research_fix_20261018'
P=json.loads((H/'ROOT_API_ACTIVATION_PLAN_R4.json').read_text())
LIVE,STAGE,BACKUP=(Path(P[k]) for k in ('live_plist','staged_plist_path','rollback_plist_path'))
CAND=Path(P['candidate_root']);CFG=Path(P['new_config_path']);WB=Path(P['manager_state_root'])
TMP=LIVE.with_name('.com.lexi.v35.api-only.monthly-membership.tmp')
sha=lambda b:hashlib.sha256(b).hexdigest();DOMAIN='gui/'+str(os.getuid());TARGET=DOMAIN+'/com.lexi.v35.api-only'
R={'started_at':datetime.now(timezone.utc).isoformat(),'status':'PRECHECK','independent_review_sha256':P['independent_review_sha256'],'selection_submitted':False}

def run(args,check=True):
    r=subprocess.run(args,capture_output=True,text=True,timeout=10)
    if check and r.returncode:raise RuntimeError('SUBPROCESS_FAILED:'+args[0]+':'+str(r.returncode))
    return r

def pid_of():
    m=re.search(r'^\s*pid = (\d+)\s*$',run(['launchctl','print',TARGET],False).stdout,re.M)
    return int(m.group(1)) if m else None

def cwd(pid):
    return next((s[1:] for s in run(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn']).stdout.splitlines() if s.startswith('n')),None)

def listeners():
    return sorted(set(int(s) for s in run(['/usr/sbin/lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-t'],False).stdout.splitlines() if s.isdigit()))

def alive(pid):
    if pid is None:return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False

def drain(pid):
    start=time.monotonic()
    while time.monotonic()-start<20:
        if not alive(pid) and not listeners():return {'seconds':round(time.monotonic()-start,3),'old_pid_exited':True,'port8873_empty':True}
        time.sleep(.25)
    raise RuntimeError('API_DRAIN_NOT_COMPLETE')

def install(raw):
    with TMP.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    TMP.chmod(0o600);os.replace(TMP,LIVE)

def health():
    end=time.monotonic()+25
    while time.monotonic()<end:
        try:
            states={}
            for endpoint in ('/healthz','/readyz'):
                with urllib.request.urlopen('http://127.0.0.1:8873'+endpoint,timeout=2) as r:states[endpoint]=r.status
            if all(v==200 for v in states.values()):return states
        except Exception:pass
        time.sleep(.5)
    raise RuntimeError('API_NOT_READY')

try:
    assert sha((H/'INDEPENDENT_R4_REVIEW.json').read_bytes())==P['independent_review_sha256']
    pl=plistlib.loads(STAGE.read_bytes());env=dict(pl['EnvironmentVariables'])
    if pl['ProgramArguments'][0]=='/usr/bin/env':
        for token in pl['ProgramArguments'][1:]:
            key,sep,value=token.partition('=')
            if sep and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key):env[key]=value
            else:break
    assert all(env.get(k)==pl['EnvironmentVariables'].get(k) for k in P['effective_identity_checked_keys'])
    with integ.shared_api_release_lock(LIVE,timeout_seconds=5) as lease:
      with integ.announcement_flash_cutover_guard(WB,timeout_seconds=5) as guard:
        changed=False
        try:
            assert sha(LIVE.read_bytes())==P['base_plist_sha256'] and sha(STAGE.read_bytes())==P['staged_plist_sha256'] and sha(BACKUP.read_bytes())==P['rollback_plist_sha256']
            assert sha(CFG.read_bytes())==P['new_config_sha256']
            verified=integ.verify_api_release_candidate(candidate_root=CAND,active_api_plist_path=LIVE,expected_manifest_sha256=P['candidate_manifest_sha256'],active_pointer='base',role='gateway',base_role='gateway',lock_lease=lease,require_shared_lock=True)
            old=integ.read_active_release(LIVE);oldpid=pid_of()
            assert oldpid and listeners()==[oldpid] and cwd(oldpid)==old['app_root']
            R.update(status='CUTOVER',pre_identity={'release_id':old['release_id'],'pid':oldpid,'cwd':old['app_root']},guard=guard)
            run(['launchctl','bootout',TARGET]);changed=True;R['old_process_drain']=drain(oldpid)
            install(STAGE.read_bytes());run(['launchctl','bootstrap',DOMAIN,str(LIVE)]);R['health']=health();newpid=pid_of()
            assert newpid and newpid!=oldpid and listeners()==[newpid] and cwd(newpid)==str(CAND/'app')
            after=integ.verify_api_release_candidate(candidate_root=CAND,active_api_plist_path=LIVE,expected_manifest_sha256=P['candidate_manifest_sha256'],active_pointer='candidate',role='gateway',base_role='gateway',lock_lease=lease,require_shared_lock=True)
            assert sha(CFG.read_bytes())==P['new_config_sha256']
            loaded=run(['launchctl','print',TARGET]).stdout
            assert all(v in loaded for v in (str(CAND/'app'),CAND.name,P['candidate_manifest_sha256'],str(CFG)))
            R.update(status='DEPLOYED_API_HEALTH_IDENTITY_VERIFIED',post_identity={'release_id':CAND.name,'pid':newpid,'cwd':cwd(newpid),'plist_sha256':sha(LIVE.read_bytes()),'manifest_sha256':sha((CAND/'release-manifest.json').read_bytes())},integrity_postcheck=after['status'],config_preserved=True,rollback_performed=False)
        except Exception as exc:
            R.update(status='ACTIVATION_FAILED',error_type=type(exc).__name__,error=str(exc))
            if changed:
                try:
                    current=pid_of();run(['launchctl','bootout',TARGET],False);R['rollback_drain']=drain(current)
                    install(BACKUP.read_bytes());run(['launchctl','bootstrap',DOMAIN,str(LIVE)]);R['rollback_health']=health();R['rollback_performed']=True
                except Exception as exc2:R['rollback_error']=type(exc2).__name__+':'+str(exc2)
except Exception as exc:R.update(status='PRECHECK_FAILED',error_type=type(exc).__name__,error=str(exc))
R['finished_at']=datetime.now(timezone.utc).isoformat();R['safety']={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
(H/'ROOT_API_ACTIVATION_RECEIPT_R4.json').write_text(json.dumps(R,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(R,ensure_ascii=False));raise SystemExit(0 if R['status']=='DEPLOYED_API_HEALTH_IDENTITY_VERIFIED' else 2)
