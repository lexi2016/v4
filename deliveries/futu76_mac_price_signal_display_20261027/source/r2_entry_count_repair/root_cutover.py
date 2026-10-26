"""Root-only API cutover using original shared lock, activity guard and CAS.

No launchctl, process signal, service reload, permission change, or HTTP retry.
Root performs the explicit API-only reload while this process holds the guards.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

B=Path(__file__).resolve().parent
R1=B.parent
W=Path('/Users/lexi/.codex/worktrees/futu76-mac-integration-20261026/v4_app')
sys.path.insert(0,str(W))
from ops import api_release_integration as a
a.MODULE_CONTRACT_PATH=R1/'control/api_module_contracts.json'
P=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
RELEASES=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
OLD=RELEASES/'schedule-remediation-20261026-api-r2'
TARGET=RELEASES/'futu76-mac-price-signal-api-20261027-r2'
PACKAGE=B/'package'/TARGET.name
BASE_PLIST_SHA='a25fdaa0dbcca7fa68785bfe991e6c2048e4a4f71b50e9854032bbacfab2026d'
BASE_MANIFEST_SHA='6d2754c2af947ae1aa2bcd1d6d5fbed6faeae6f008f1688a6cf16d60c247d0f6'
ATOMIC=R1.parent/'a_share_local_panel_completion_20261024/consumer_activation_r1/activate_api_r1.py'
ATOMIC_SHA='dec2c48103f67f67516fdd80f9f9503f08d09dbc59fae4c37f4a273e077955a1'
RESULT=B/'control/ROOT_API_CUTOVER_RESULT.json'
STATE={}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def pin(path,digest):
    if sha(Path(path).read_bytes())!=digest:raise RuntimeError('IDENTITY_DRIFT:'+str(path))


def project_manifest():
    package=json.loads((B/'control/PACKAGE_RESULT.json').read_text())
    raw=(PACKAGE/'release-manifest.json').read_bytes();assert sha(raw)==package['manifest_sha256']
    old_literal=json.dumps(str(PACKAGE),ensure_ascii=False)[1:-1].encode()
    new_literal=json.dumps(str(TARGET),ensure_ascii=False)[1:-1].encode()
    assert raw.count(old_literal)==2
    projected=raw.replace(old_literal,new_literal)
    parsed=json.loads(projected)
    assert parsed['candidate']['root']==str(TARGET) and parsed['candidate']['app_root']==str(TARGET/'app')
    return raw,projected


def candidate_plist(raw,manifest_sha):
    before=plistlib.loads(raw);after=plistlib.loads(raw)
    expected=dict(V35_APP_ROOT=str(OLD/'app'),V35_RELEASE_ID=OLD.name,
        V35_RELEASE_MANIFEST_PATH=str(OLD/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=BASE_MANIFEST_SHA)
    replacement=dict(V35_APP_ROOT=str(TARGET/'app'),V35_RELEASE_ID=TARGET.name,
        V35_RELEASE_MANIFEST_PATH=str(TARGET/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=manifest_sha)
    def value(key,original):
        if key in expected:
            assert original==expected[key],'PLIST_BASE_ENV_DRIFT:'+key
            return replacement[key]
        if key=='PYTHONPATH':
            return ':'.join(str(TARGET/'app')+part[len(str(OLD/'app')):]
                if part==str(OLD/'app') or part.startswith(str(OLD/'app')+'/') else part for part in original.split(':'))
        return original
    for key,original in before.get('EnvironmentVariables',{}).items():after['EnvironmentVariables'][key]=value(key,original)
    for i,original in enumerate(before['ProgramArguments']):
        if '=' in original:
            key,text=original.split('=',1);after['ProgramArguments'][i]=key+'='+value(key,text)
    assert before['WorkingDirectory']==str(OLD/'app')
    after['WorkingDirectory']=str(TARGET/'app')
    allowed={*expected,'PYTHONPATH'}
    assert before.keys()==after.keys()
    for key in before:
        if key not in {'WorkingDirectory','ProgramArguments','EnvironmentVariables'}:assert before[key]==after[key]
    for key in before.get('EnvironmentVariables',{}):
        if key not in allowed:assert before['EnvironmentVariables'][key]==after['EnvironmentVariables'][key]
    for old,new in zip(before['ProgramArguments'],after['ProgramArguments']):
        if old.split('=',1)[0] not in allowed:assert old==new
    assert a._plist_environment(after)['V35_APP_ROOT']==str(TARGET/'app')
    return plistlib.dumps(after,sort_keys=False)


def record(**changes):
    STATE.update(changes,observed_at_utc=datetime.now(timezone.utc).isoformat())
    try:
        raw=(json.dumps(STATE,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        with RESULT.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    except (OSError,ValueError,TypeError) as error:
        if not STATE.get('guards_held'):raise
        STATE['reporting_error']=repr(error)
        try:os.write(2,b'POST_CAS_REPORTING_FAILED_GUARDS_HELD; ROLLBACK_OR_HANDOFF_RECOVERY\n')
        except OSError:pass


def emit(status):
    try:print(json.dumps(dict(status=status,receipt=str(RESULT))),flush=True)
    except (OSError,ValueError,TypeError):
        if not STATE.get('guards_held'):raise


def project_only():
    _,projected=project_manifest()
    pin(P,BASE_PLIST_SHA);pin(OLD/'release-manifest.json',BASE_MANIFEST_SHA)
    old=P.read_bytes();new=candidate_plist(old,sha(projected))
    for name,raw in [('release-manifest.materialized.json',projected),('api-only.before.plist',old),('api-only.candidate.plist',new)]:
        path=B/'control'/name
        with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    print(json.dumps(dict(status='PROJECTED_LOCAL_ONLY',materialized_manifest_sha256=sha(projected),
        candidate_plist_sha256=sha(new),old_plist_sha256=sha(old))))


def original_atomic_and_locks():
    pin(ATOMIC,ATOMIC_SHA)
    spec=importlib.util.spec_from_file_location('accepted_original_api_atomic',ATOMIC)
    atomic=importlib.util.module_from_spec(spec);spec.loader.exec_module(atomic)
    assert atomic.LIVE==P
    sys.path.insert(0,str(OLD/'app'))
    from infrastructure import interprocess_lock, owned_io
    for module,relative in [(interprocess_lock,'infrastructure/interprocess_lock.py'),
                            (owned_io,'infrastructure/owned_io.py')]:
        assert Path(module.__file__).resolve()==(OLD/'app'/relative).resolve()
    for dependency in json.loads((R1/'control/ORIGINAL_LOCK_DEPENDENCIES.json').read_text()):
        pin(dependency['path'],dependency['sha256'])
    return atomic


def old_baseline_runtime_proof():
    """Verify restoration capabilities of the actual legacy baseline.

    That custom-schema baseline cannot pass the standard dispatch manifest
    validator. Retain its identity evidence gaps while proving exact binding,
    complete typed inventory and the same serving PID/root through Graph.
    """
    pin(P,BASE_PLIST_SHA);pin(OLD/'release-manifest.json',BASE_MANIFEST_SHA)
    active=a.read_active_release(P)
    assert active['release_id']==OLD.name and active['release_manifest_sha256']==BASE_MANIFEST_SHA
    with urlopen('http://127.0.0.1:8873/api/v3/runtime-graph/status',timeout=30) as response:
        raw=response.read();body=json.loads(raw);identity=body.get('runtime_identity',{})
    listener=subprocess.run(['/usr/sbin/lsof','-nP','-t','-iTCP:8873','-sTCP:LISTEN'],text=True,capture_output=True)
    assert listener.returncode==0
    pids=set(listener.stdout.split());assert len(pids)==1 and str(identity.get('pid')) in pids
    pid=int(next(iter(pids)))
    cwd=subprocess.run(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn'],text=True,capture_output=True)
    assert cwd.returncode==0 and 'n'+str(OLD/'app') in cwd.stdout.splitlines()
    for key in ('cwd','serving_app_root','declared_app_root'):assert identity.get(key)==str(OLD/'app')
    assert identity.get('app_root_status')=='VERIFIED'
    assert identity.get('release_id')==OLD.name
    assert identity.get('release_manifest_sha256')==BASE_MANIFEST_SHA
    assert identity.get('release_manifest_sha_status')=='VERIFIED'
    assert identity.get('plist_sha256')==BASE_PLIST_SHA
    expected={'V35_APP_ROOT':str(OLD/'app'),'V35_RELEASE_ID':OLD.name,'V35_RELEASE_MANIFEST_SHA256':BASE_MANIFEST_SHA}
    bindings=identity.get('plist_bindings',{})
    for key,value in expected.items():
        item=bindings.get(key,{})
        assert item.get('status')=='MATCH' and item.get('environment')==value and item.get('plist')==value
    return dict(status='OLD_BASELINE_EXACT_BINDING_TYPED_INVENTORY_AND_SAME_PROCESS_RESTORED',pid=pid,
        cwd=str(OLD/'app'),release_id=OLD.name,manifest_sha256=BASE_MANIFEST_SHA,plist_sha256=BASE_PLIST_SHA,
        typed_application_inventory_sha256=active['application_inventory_sha256'],
        typed_application_inventory_entry_count=active['application_inventory_entry_count'],
        graph_response_sha256=sha(raw),graph_status=body.get('status'),
        runtime_identity_overall_status=identity.get('status'),original_standard_validator='CANNOT_CONFIRM_LEGACY_CUSTOM_SCHEMA',
        graph_selected_proof={k:identity.get(k) for k in ('pid','cwd','serving_app_root','declared_app_root',
            'release_id','release_manifest_sha256','release_manifest_sha_status','app_root_status','plist_sha256')},
        primary_plist_bindings={key:bindings[key] for key in expected})


def original_dispatcher_identity(app_root,manifest_path,release_id,manifest_sha):
    environment=dict(os.environ,V35_APP_ROOT=str(app_root),V35_RELEASE_ID=release_id,
        V35_RELEASE_MANIFEST_PATH=str(manifest_path),V35_RELEASE_MANIFEST_SHA256=manifest_sha,
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from infrastructure.scheduling.dispatcher import validate_release_identity;print(json.dumps({'validator_source':validate_release_identity.__code__.co_filename,'verified':validate_release_identity()},sort_keys=True))"
    result=subprocess.run([sys.executable,'-B','-c',code,str(app_root)],cwd=app_root,
        env=environment,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('ORIGINAL_DISPATCHER_IDENTITY_FAILED:'+result.stderr[-1200:])
    verified=json.loads(result.stdout)
    assert verified['validator_source']==str(app_root/'infrastructure/scheduling/dispatcher.py')
    assert verified['verified']==dict(app_root=str(app_root),release_id=release_id,
        release_manifest_path=str(manifest_path),release_manifest_sha256=manifest_sha)
    return verified


def cutover(review_path):
    if RESULT.exists() or TARGET.exists():raise RuntimeError('PRIOR_CUTOVER_OR_TARGET_EXISTS_STOP')
    review=json.loads(Path(review_path).read_text())
    if (review.get('verdict')!='PASS_FUTU76_ENTRY_COUNT_R2_INCREMENTAL'
            or review.get('candidate_manifest_sha256')!=sha((R1/'full/candidate_manifest.json').read_bytes())
            or review.get('package_manifest_sha256')!=sha((PACKAGE/'release-manifest.json').read_bytes())
            or review.get('root_controller_sha256')!=sha(Path(__file__).read_bytes())
            or review.get('api_release_integration_sha256')!=sha(Path(a.__file__).read_bytes())
            or not review.get('reviewer_id')):raise RuntimeError('REAL_INCREMENTAL_INDEPENDENT_REVIEW_REQUIRED')
    package_raw,projected=project_manifest();new_manifest_sha=sha(projected)
    pin(B/'control/release-manifest.materialized.json',new_manifest_sha)
    pin(P,BASE_PLIST_SHA);pin(OLD/'release-manifest.json',BASE_MANIFEST_SHA);pin(ATOMIC,ATOMIC_SHA)
    old=P.read_bytes();new=candidate_plist(old,new_manifest_sha)
    assert new==(B/'control/api-only.candidate.plist').read_bytes()
    # The tracked worktree has older lock dependencies. Load the exact active
    # release implementations, while retaining this task's typed assembler.
    atomic=original_atomic_and_locks()
    before_runtime=old_baseline_runtime_proof()
    with a.shared_api_release_lock(P,timeout_seconds=2):
        pin(P,BASE_PLIST_SHA)
        shutil.copytree(PACKAGE,TARGET,symlinks=True)
        pin(TARGET/'release-manifest.json',sha(package_raw))
        (TARGET/'release-manifest.json').write_bytes(projected)
        pin(TARGET/'release-manifest.json',new_manifest_sha)
        record(status='MATERIALIZED_INACTIVE',review_path=str(review_path),review_sha256=sha(Path(review_path).read_bytes()),
            old_plist_sha256=sha(old),new_plist_sha256=sha(new),new_manifest_sha256=new_manifest_sha,
            original_baseline_runtime_proof=before_runtime)
    with a.announcement_flash_cutover_guard(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench'),timeout_seconds=10) as guard:
        with a.shared_api_release_lock(P,timeout_seconds=2) as lease:
            pin(P,BASE_PLIST_SHA);pin(OLD/'release-manifest.json',BASE_MANIFEST_SHA)
            check=a.verify_api_release_candidate(candidate_root=TARGET,active_api_plist_path=P,
                expected_manifest_sha256=new_manifest_sha,lock_lease=lease,require_shared_lock=True)
            dispatcher=original_dispatcher_identity(TARGET/'app',TARGET/'release-manifest.json',TARGET.name,new_manifest_sha)
            STATE['guards_held']=True
            try:
                atomic.atomic_plist(new,sha(old));pin(P,sha(new))
                record(status='CANDIDATE_PLIST_INSTALLED_GUARDS_HELD',guard=guard,preflight=check,
                    materialized_original_dispatcher=dispatcher)
            except Exception as error:
                record(status='CAS_ERROR_GUARDS_HELD',cas_error=repr(error))
            emit(STATE['status'])
            while True:
                try:command=sys.stdin.readline().strip()
                except OSError as error:
                    record(stdin_error=repr(error));time.sleep(1);continue
                if command=='VERIFY':
                    try:
                        pin(P,sha(new))
                        check=a.verify_api_release_candidate(candidate_root=TARGET,active_api_plist_path=P,
                            expected_manifest_sha256=new_manifest_sha,active_pointer='candidate',lock_lease=lease,require_shared_lock=True)
                        # Root has already executed its single authorized API-only
                        # reload; read runtime identity once, no target-stock GETs.
                        with urlopen('http://127.0.0.1:8873/api/v1/runs/date-list?date=20261026',timeout=30) as response:
                            runtime=json.loads(response.read()).get('runtime_identity',{})
                        assert runtime.get('release_id')==TARGET.name
                        assert runtime.get('manifest_sha256')==new_manifest_sha
                        assert runtime.get('status')=='MANIFEST_EXECUTION_FILES_VERIFIED'
                        record(status='API_SOURCE_ACTIVE_VERIFIED_ADMISSION_PENDING',verification=check,runtime_identity=runtime)
                        emit(STATE['status']);break
                    except Exception as error:
                        record(verify_error=repr(error));emit('VERIFY_FAILED_GUARDS_HELD')
                elif command=='ROLLBACK':
                    try:
                        atomic.atomic_plist(old,sha(new));pin(P,sha(old))
                        record(status='ROLLBACK_PLIST_INSTALLED_RELOAD_PENDING');emit(STATE['status'])
                    except Exception as error:
                        record(rollback_error=repr(error));emit('ROLLBACK_FAILED_GUARDS_HELD')
                elif command=='VERIFY_ROLLBACK':
                    try:
                        restored=old_baseline_runtime_proof()
                        record(status='ROLLED_BACK_TO_EXACT_OLD_BASELINE_IDENTITY_GAPS_RETAINED',rollback_proof=restored)
                        emit(STATE['status']);break
                    except Exception as error:
                        record(rollback_verify_error=repr(error));emit('ROLLBACK_VERIFY_FAILED_GUARDS_HELD')
                elif command=='HANDOFF_RECOVERY':
                    record(status='ROOT_EXPLICIT_RECOVERY_HANDOFF_UNVERIFIED');emit(STATE['status']);break
                elif not command:
                    record(stdin_error='INPUT_CLOSED_GUARDS_HELD');time.sleep(1)
                else:emit('EXPECT_VERIFY_ROLLBACK_VERIFY_ROLLBACK_OR_HANDOFF_RECOVERY')
    record(guards_held=False);emit('GUARDS_RELEASED')


def recover_after_release():
    """Explicit Root inverse-CAS after the successful cutover session ended."""
    saved=json.loads(RESULT.read_text())
    old=(B/'control/api-only.before.plist').read_bytes()
    new=(B/'control/api-only.candidate.plist').read_bytes()
    assert sha(old)==BASE_PLIST_SHA==saved['old_plist_sha256']
    assert sha(new)==saved['new_plist_sha256']
    admission=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/runtime/cache/data_layer_daily_formula_increment_update_v1/futu_direct_qfq76_admission.json')
    if admission.exists():raise RuntimeError('ROLLBACK_OWNED_ADMISSION_FIRST')
    pin(P,sha(new))
    atomic=original_atomic_and_locks()
    STATE.update(saved)
    with a.announcement_flash_cutover_guard(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench'),timeout_seconds=10):
        with a.shared_api_release_lock(P,timeout_seconds=2) as lease:
            pin(P,sha(new))
            a.verify_api_release_candidate(candidate_root=TARGET,active_api_plist_path=P,
                expected_manifest_sha256=saved['new_manifest_sha256'],active_pointer='candidate',
                lock_lease=lease,require_shared_lock=True)
            STATE['guards_held']=True
            try:
                atomic.atomic_plist(old,sha(new));pin(P,sha(old))
                record(status='ROLLBACK_PLIST_INSTALLED_RELOAD_PENDING')
            except Exception as error:record(status='RECOVERY_CAS_ERROR_GUARDS_HELD',recovery_error=repr(error))
            emit(STATE['status'])
            while True:
                try:command=sys.stdin.readline().strip()
                except OSError as error:record(stdin_error=repr(error));time.sleep(1);continue
                if command=='VERIFY_ROLLBACK':
                    try:
                        restored=old_baseline_runtime_proof()
                        record(status='ROLLED_BACK_TO_EXACT_OLD_BASELINE_IDENTITY_GAPS_RETAINED',rollback_proof=restored)
                        emit(STATE['status']);break
                    except Exception as error:record(rollback_verify_error=repr(error));emit('ROLLBACK_VERIFY_FAILED_GUARDS_HELD')
                elif command=='HANDOFF_RECOVERY':
                    record(status='ROOT_EXPLICIT_RECOVERY_HANDOFF_UNVERIFIED');emit(STATE['status']);break
                elif not command:record(stdin_error='INPUT_CLOSED_GUARDS_HELD');time.sleep(1)
                else:emit('EXPECT_VERIFY_ROLLBACK_OR_HANDOFF_RECOVERY')
    record(guards_held=False);emit('GUARDS_RELEASED')


if __name__=='__main__':
    if sys.argv[1]=='project':project_only()
    elif sys.argv[1]=='cutover':cutover(sys.argv[2])
    elif sys.argv[1]=='recover':recover_after_release()
    else:raise RuntimeError('EXPLICIT_PROJECT_OR_ROOT_CUTOVER_REQUIRED')
