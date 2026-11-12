"""Existing Main/Stage coordinated activation recipe; default read-only.

Only the controller executes after the single independent review. No API role,
source data, schedules, permissions or policy limits are changed.
"""
import argparse,hashlib,json,os,plistlib,re,subprocess,sys,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent
DOMAIN='gui/'+str(os.getuid())
LABELS={'main':'com.lexi.v4.scheduler','stage':'com.lexi.stage-center.scheduler'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def run(*a):return subprocess.run(a,text=True,capture_output=True)
def state(label):
    r=run('launchctl','print',DOMAIN+'/'+label)
    if r.returncode:return dict(loaded=False)
    pid=re.search(r'^\s*pid = (\d+)',r.stdout,re.M);status=re.search(r'^\s*state = ([^\n]+)',r.stdout,re.M)
    return dict(loaded=True,pid=int(pid[1])if pid else None,state=status[1].strip()if status else None)
def atomic(path,raw):
    p=Path(path);temp=p.with_name(p.name+'.v192-'+str(os.getpid())+'.tmp')
    with temp.open('xb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
    temp.chmod(0o644);os.replace(temp,p)
def unloaded():
    end=time.monotonic()+20
    while time.monotonic()<end:
        if not any(state(label)['loaded']for label in LABELS.values()):return
        time.sleep(.25)
    raise RuntimeError('JOB_UNLOAD_NOT_COMPLETE')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--review-file',type=Path)
    args=parser.parse_args();plan=load(HERE/'INACTIVE_CANDIDATES_R3.json')
    records=plan['roles'];originals={}
    for role,record in records.items():
        for key in ['original_plist','prepared_plist']:
            assert sha(record[key]['path'])==record[key]['sha256'],(role,key,'FRESH_PLIST_CAS_FAILED')
        assert sha(record['binding']['manifest_path'])==record['binding']['manifest_sha256']
        originals[role]=Path(record['original_plist']['path']).read_bytes()
    old=plistlib.loads(originals['main']);env=old['EnvironmentVariables'];policy=load(env['V4_RESEARCH_RETENTION_POLICY'])
    assert sha(env['V4_RESEARCH_RETENTION_POLICY'])==env['V4_RESEARCH_RETENTION_POLICY_SHA256']==plan['control']['base_policy']['sha256']
    assert sha(plan['control']['prepared_policy']['path'])==plan['control']['prepared_policy']['sha256']
    registry=load(Path(policy['governance']['registry_root'])/'registry.json')
    sys.path.insert(0,env['V4_APP_ROOT']);from ops.research_storage_governance import owner_state
    claims=[dict(key=k,state=v.get('state'),owner_state=owner_state(v['owner']))for k,v in registry['tasks'].items()if v.get('state')in ['RUNNING','VALIDATING']]
    active=[x for x in claims if x['owner_state']!='DEAD']
    assert not active,('ACTIVE_OR_UNKNOWN_CLAIM_KEEP_RUNNING',active)
    before={role:state(label)for role,label in LABELS.items()};lines=run('ps','-axo','pid=,ppid=,comm=').stdout.splitlines();busy=[]
    for role,value in before.items():
        if value.get('pid'):
            children=[line.strip()for line in lines if len(line.split(None,2))>=2 and line.split(None,2)[1]==str(value['pid'])]
            if children or role=='stage':busy.append(dict(role=role,pid=value['pid'],children=children))
    assert not busy,('HEALTHY_CHILD_OR_STAGE_KEEP_RUNNING',busy)
    preflight=dict(status='PREFLIGHT_PASS_NO_ACTIVATION',at=datetime.now(timezone.utc).isoformat(),before=before,active_claims=active,
                   dead_claim_count=len(claims),prepared_plan_sha256=sha(HERE/'INACTIVE_CANDIDATES_R3.json'))
    if not args.execute:print(json.dumps(preflight,indent=2));return
    assert args.review_file is not None,'EXACT_INDEPENDENT_REVIEW_REQUIRED'
    review=load(args.review_file)
    assert review['verdict']=='REVIEWED/PASS'and review['frozen_scope_sha256']==sha(HERE/'FROZEN_HANDOFF.json')
    frozen=load(HERE/'FROZEN_HANDOFF.json')
    for reference in frozen['evidence_files']:
        assert sha(reference['path'])==reference['sha256'],'REVIEWED_FILE_DRIFT:'+reference['path']
    # Recheck no service has changed since the preflight; preserve original
    # plists for the existing coordinated half-switch rollback.
    assert before=={role:state(label)for role,label in LABELS.items()},'SERVICE_STATE_CHANGED'
    for role,record in records.items():
        assert sha(record['original_plist']['path'])==record['original_plist']['sha256']
        backup=HERE/(role+'_BEFORE_ACTIVATION.plist')
        if backup.exists():assert backup.read_bytes()==originals[role]
        else:backup.write_bytes(originals[role]);backup.chmod(0o600)
    save(HERE/'ACTIVATION_PREFLIGHT.json',preflight)
    try:
        for role,label in LABELS.items():
            if before[role]['loaded']:
                result=run('launchctl','bootout',DOMAIN+'/'+label);assert result.returncode==0,(role,result.stderr)
        unloaded()
        for role,record in records.items():atomic(record['original_plist']['path'],Path(record['prepared_plist']['path']).read_bytes())
        for role in ['stage','main']:
            result=run('launchctl','bootstrap',DOMAIN,records[role]['original_plist']['path']);assert result.returncode==0,(role,result.stderr)
        end=time.monotonic()+20
        while time.monotonic()<end:
            after={role:state(label)for role,label in LABELS.items()}
            if after['main'].get('pid')and after['main'].get('state')=='running'and after['stage']['loaded']:break
            time.sleep(.25)
        else:raise RuntimeError('MAIN_STAGE_LIVENESS_NOT_CONFIRMED')
        for role,label in LABELS.items():
            record=records[role];assert sha(record['original_plist']['path'])==record['prepared_plist']['sha256']
            e=plistlib.loads(Path(record['original_plist']['path']).read_bytes())['EnvironmentVariables'];out=run('launchctl','print',DOMAIN+'/'+label).stdout
            assert all(e[key]in out for key in ['V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_SHA256'])
        e=plistlib.loads(Path(records['main']['original_plist']['path']).read_bytes())['EnvironmentVariables'];child_env=os.environ.copy();child_env.update(e);child_env['PYTHONPATH']=e['V4_APP_ROOT']+os.pathsep+child_env.get('PYTHONPATH','')
        code='from ops.research_storage_governance import configured_policy; assert configured_policy(); from infrastructure.formula_generation import read_selector_source_binding; print("NEW_MAIN_POLICY_AND_SOURCE_BINDING_PASS")'
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=e['V4_APP_ROOT'],env=child_env,text=True,capture_output=True)
        assert result.returncode==0,('NEW_MAIN_POLICY_FAILED',result.stderr[-1500:])
        with urllib.request.urlopen('http://127.0.0.1:8873/healthz',timeout=5)as response:health=json.load(response)
        assert health.get('status')=='ok'
        save(HERE/'ACTIVATION.json',dict(status='MAIN_STAGE_ACTIVATED_IDENTITY_POLICY_HEALTH_VERIFIED',before=before,after=after,roles=records,healthz=health,API_changed=False,natural='NOT_YET_VERIFIED'))
        print('MAIN_STAGE_ACTIVATED_IDENTITY_POLICY_HEALTH_VERIFIED')
    except BaseException as error:
        for label in LABELS.values():
            if state(label)['loaded']:run('launchctl','bootout',DOMAIN+'/'+label)
        unloaded();rollback=[]
        for role,record in records.items():atomic(record['original_plist']['path'],originals[role])
        for role in ['stage','main']:
            if before[role]['loaded']:
                result=run('launchctl','bootstrap',DOMAIN,records[role]['original_plist']['path']);rollback.append(dict(role=role,returncode=result.returncode,stderr=result.stderr[-500:]))
        save(HERE/'ACTIVATION_FAILURE.json',dict(error=repr(error),rollback=rollback,after={role:state(label)for role,label in LABELS.items()}));raise
if __name__=='__main__':main()
