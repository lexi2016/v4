"""Scheduling proposal and nonblocking child supervision; SIMULATED process seam."""
from datetime import datetime
from pathlib import Path
from threading import Event
import time
from zoneinfo import ZoneInfo
import pytest

HK=ZoneInfo('Asia/Shanghai')


def test_proposal_windows_use_original_hk_calendar():
    from v4.manager_research.announcement_autorun import policy_due
    assert policy_due(datetime(2026,9,24,7,tzinfo=HK),'BALANCED_V1')
    assert not policy_due(datetime(2026,9,24,6,59,tzinfo=HK),'BALANCED_V1')
    assert not policy_due(datetime(2026,9,24,15,19,11,tzinfo=HK),'BALANCED_V1')
    assert not policy_due(datetime(2026,9,24,15,30,tzinfo=HK),'BALANCED_V1')
    assert not policy_due(datetime(2026,9,26,8,tzinfo=HK),'BALANCED_V1')
    assert policy_due(datetime(2026,9,24,15,40,tzinfo=HK),'BALANCED_V1')


def test_supervisor_does_not_queue_or_wait_for_owner(monkeypatch):
    from infrastructure.scheduling.manager_announcement_supervisor import AnnouncementSupervisor
    started=Event();release=Event();calls=[]
    def runner(path, stop):
        calls.append(path);started.set();release.wait(2)
    s=AnnouncementSupervisor('/absolute/optin.json',runner=runner)
    now=datetime(2026,9,24,8,tzinfo=HK)
    t=time.monotonic();s.tick(now);assert time.monotonic()-t<.2
    assert started.wait(1);s.tick(now);s.tick(now.replace(minute=1));assert len(calls)==1
    s.stop();assert s.cancel.is_set();release.set();s.thread.join(1)


def test_disabled_supervisor_has_no_worker_or_state(monkeypatch):
    from infrastructure.scheduling.manager_announcement_supervisor import AnnouncementSupervisor
    calls=[];s=AnnouncementSupervisor(None,runner=lambda *a:calls.append(a))
    s.tick(datetime(2026,9,24,8,tzinfo=HK));assert calls==[] and s.thread is None
    s.stop()


def test_tail_blackout_blocks_even_explicit_worker():
    from infrastructure.scheduling.manager_announcement_supervisor import AnnouncementSupervisor
    calls=[];s=AnnouncementSupervisor('/absolute/optin.json',runner=lambda *a:calls.append(a))
    s.tick(datetime(2026,9,24,15,30,tzinfo=HK));assert calls==[]
    s.stop()


def test_binding_rejects_missing_or_tampered_required_identity(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    with pytest.raises(ValueError):validate_binding({'enabled':True},tmp_path)


def test_timeout_terminates_only_spawned_process_group(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import supervise_child
    import subprocess,sys
    # Real short-lived, offline child. This is not V4 or a provider process.
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    started=time.monotonic();result=supervise_child(child,Event(),wall_seconds=.1,kill_grace=.1)
    assert time.monotonic()-started < 2
    assert result=='TIMEOUT' and child.poll() is not None


def _binding(tmp_path):
    import shutil,sys,hashlib
    from infrastructure.scheduling.manager_announcement_supervisor import binding_inventory,BINDING_SCHEMA
    app=tmp_path/'app';app.mkdir();original=Path(__file__).resolve().parents[1]
    for path in ('apps/api/v35_api','v4/manager_research','infrastructure','contracts','domains','stage_center','upstreams/v3_shared_data/shared_data'):
        shutil.copytree(original/path,app/path,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    shutil.copy2(original/'apps/__init__.py',app/'apps/__init__.py')
    shutil.copy2(original/'apps/api/__init__.py',app/'apps/api/__init__.py')
    (app/'ops').mkdir()
    for source in ('run_manager_announcement_cycle.py','run_manager_daily_announcement.py',
                   'manager_announcement_body_batch.py','daily_materialize.py'):
        shutil.copy2(original/'ops'/source,app/'ops'/source)
    shutil.copy2(original/'uv.lock',app/'uv.lock')
    master=tmp_path/'master';master.mkdir()
    python=Path(sys.executable).absolute()
    return dict(schema_version=BINDING_SCHEMA,enabled=False,policy_status='PROPOSAL_ONLY',policy='BALANCED_V1',
        app_root=str(app),manager_state_root=str(tmp_path/'state'),security_master_root=str(master),python=str(python),
        python_resolved=str(python.resolve()),python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),
        priority_codes=[],files=binding_inventory(app),research_only=True,
        production_allowed=False,buy_gate_updated=False,orders_sent=False)


def test_binding_inventory_includes_full_stage_and_body_capture_dependency_closure(tmp_path):
    files=_binding(tmp_path)['files']
    assert 'stage_center/consumer.py' in files
    assert 'stage_center/input_contracts.py' in files
    assert 'ops/daily_materialize.py' in files
    assert 'ops/manager_announcement_body_batch.py' in files


def _plan_only_binding(tmp_path, *, tamper_body_sha=False, same_owner_root=False):
    import hashlib,json
    import shutil
    from infrastructure.scheduling.manager_announcement_supervisor import PLAN_CANARY_SCHEMA,PLAN_CANARY_STATUS,PLAN_OWNER_SOURCE_FILES
    tmp_path.mkdir(parents=True,exist_ok=True)
    value=_binding(tmp_path);app=Path(value['app_root']);state=Path(value['manager_state_root'])
    value.update(enabled=True,plan_material_refresh_only=True,announcement_collection_enabled=False,
        plan_material_refresh={'enabled':True,'start_local':'16:00','end_local':'23:00',
            'max_attempts_per_target_date':3,'retry_backoff_seconds':600,'status':'PROPOSAL_ONLY'})
    target='20260929';run_id='1'*32;product_sha='2'*64;identity='3'*64
    owner='ManagerResearchJobService.refresh_workspace_plan'; evidence={}
    source_app=app if same_owner_root else tmp_path/'owner-source'/'app';owner_sources={}
    if not same_owner_root:
        for rel in PLAN_OWNER_SOURCE_FILES:
            source=(app/rel);destination=source_app/rel;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination)
            owner_sources[rel]=hashlib.sha256(source.read_bytes()).hexdigest()
        migration={'schema_version':'manager_daily_chain.plan_owner_source_migration.v1',
            'source_app_root':str(source_app),'candidate_app_root':str(app),'manager_state_root':str(state),
            'owner':owner,'owner_sources':owner_sources,'status':'IDENTICAL_OWNER_SOURCE_FILES'}
        migration_path=tmp_path/'owner-source-migration.json';migration_raw=json.dumps(migration,sort_keys=True).encode()
        migration_path.write_bytes(migration_raw)
    for name,method,url in (
        ('refresh','POST',f'http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date={target}'),
        ('readback','GET',f'http://127.0.0.1:8873/api/v4/manager/research/workspace?date={target}')):
        body=tmp_path/f'{name}-response.json';body.write_text('{}')
        path=tmp_path/f'{name}-receipt.json'
        plan={'status':'CURRENT','run_id':run_id,'sha256':product_sha,'original_owner':owner}
        readback={'target_trade_date':target,'plan_product':plan}
        if name=='refresh':
            readback.update(store_latest_matches_http_plan_product=True,
                persisted_store={'target_trade_date':target,'run_id':run_id,'product_sha256':product_sha,
                    'execution_kind':'MANUAL_REFRESH','owner':owner,'RESEARCH_ONLY':True,
                    'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},
                workspace_plan_attempt={'execution_kind':'MANUAL_REFRESH','state':'PARTIAL'},
                safety={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
        receipt={'schema_version':'manager_daily_chain.manual_refresh_receipt.v1' if name=='refresh'
                    else 'manager_daily_chain.http_readback_receipt.v1',
            'http_status':200,'content_type':'application/json',
            'request':{'method':method,'origin':'http://127.0.0.1:8873','url':url},
            'response':{'path':str(body),'bytes':2,
                'sha256':'4'*64 if tamper_body_sha and name=='readback'
                    else hashlib.sha256(body.read_bytes()).hexdigest()},'readback':readback}
        raw=json.dumps(receipt,sort_keys=True).encode();path.write_bytes(raw)
        evidence[name]={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    canary={'schema_version':PLAN_CANARY_SCHEMA,'status':PLAN_CANARY_STATUS,
        'app_root':str(app),'manager_state_root':str(state),'policy_status':'PROPOSAL_ONLY',
        'scope':'NEXT_HK_SESSION_MANUAL_REFRESH_WITH_HTTP_READBACK','plan_material_refresh_only':True,
        'candidate_binding_app_root':str(app),'owner_execution_app_root':str(source_app),
        'execution_mode':'HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK','hook_executed':False,
        'announcement_collection_enabled':False,'announcement_network_requests':0,'research_only':True,
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'target_trade_date':target,
        'run_id':run_id,'product_sha256':product_sha,'input_identity':identity,
        'execution_kind':'MANUAL_REFRESH','owner':owner,'owner_attempt_state':'PARTIAL',
        'formal_recommendation_count':0,'owner_evidence':evidence}
    if not same_owner_root:
        canary['source_migration_receipt']={'path':str(migration_path),'sha256':hashlib.sha256(migration_raw).hexdigest()}
    raw=json.dumps(canary,sort_keys=True).encode();receipt_path=tmp_path/'plan-canary.json';receipt_path.write_bytes(raw)
    value['plan_activation_receipt']={'path':str(receipt_path),'sha256':hashlib.sha256(raw).hexdigest()}
    return value,canary


def test_complete_bound_source_inventory_and_disabled_config(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    v=_binding(tmp_path);assert validate_binding(v)['enabled'] is False
    assert not Path(v['manager_state_root']).exists()


def test_plan_only_binding_requires_separate_matching_manual_owner_canary(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value,_=_plan_only_binding(tmp_path)
    assert validate_binding(value,Path(value['app_root']))['plan_material_refresh_only'] is True


def test_plan_only_binding_accepts_fresh_manual_owner_evidence_from_same_api_root(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value,canary=_plan_only_binding(tmp_path,same_owner_root=True)
    assert canary['owner_execution_app_root']==value['app_root']
    assert 'source_migration_receipt' not in canary
    assert validate_binding(value,Path(value['app_root']))['plan_material_refresh_only'] is True


def test_plan_only_binding_rejects_response_body_with_wrong_sha(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value,_=_plan_only_binding(tmp_path,tamper_body_sha=True)
    with pytest.raises(ValueError,match='PLAN_REFRESH_CANARY_RESPONSE_SHA_MISMATCH'):
        validate_binding(value,Path(value['app_root']))


def test_plan_only_binding_rejects_forged_or_announcement_canary(tmp_path):
    import hashlib,json
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value,canary=_plan_only_binding(tmp_path)
    canary['announcement_network_requests']=1
    raw=json.dumps(canary,sort_keys=True).encode();path=Path(value['plan_activation_receipt']['path']);path.write_bytes(raw)
    value['plan_activation_receipt']['sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='PLAN_REFRESH_CANARY_CONTRACT_INVALID'):
        validate_binding(value,Path(value['app_root']))
    value,canary=_plan_only_binding(tmp_path/'announcement-reuse')
    value['activation_receipt']={'path':str(Path(value['plan_activation_receipt']['path'])),'sha256':value['plan_activation_receipt']['sha256']}
    with pytest.raises(ValueError,match='PLAN_REFRESH_CANNOT_REUSE_ANNOUNCEMENT_RECEIPT'):
        validate_binding(value,Path(value['app_root']))


def test_plan_only_binding_rejects_owner_source_migration_mismatch(tmp_path):
    import hashlib,json
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value,canary=_plan_only_binding(tmp_path)
    migration_ref=canary['source_migration_receipt'];migration_path=Path(migration_ref['path'])
    migration=json.loads(migration_path.read_bytes())
    migration['owner_sources']['v4/manager_research/workspace.py']='0'*64
    raw=json.dumps(migration,sort_keys=True).encode();migration_path.write_bytes(raw)
    migration_ref['sha256']=hashlib.sha256(raw).hexdigest()
    canary_raw=json.dumps(canary,sort_keys=True).encode();canary_path=Path(value['plan_activation_receipt']['path'])
    canary_path.write_bytes(canary_raw);value['plan_activation_receipt']['sha256']=hashlib.sha256(canary_raw).hexdigest()
    with pytest.raises(ValueError,match='PLAN_REFRESH_CANARY_SOURCE_MIGRATION_MISMATCH'):
        validate_binding(value,Path(value['app_root']))


@pytest.mark.parametrize('case',['missing_catalog','unlisted_new_source','changed_source','state_overlap','python_target','unsafe_flag'])
def test_binding_rejects_source_and_root_drift(tmp_path,case):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    v=_binding(tmp_path);app=Path(v['app_root'])
    if case=='missing_catalog':del v['files']['infrastructure/scheduling/catalog.py']
    if case=='unlisted_new_source':(app/'v4/manager_research/new_injected.py').write_text('raise RuntimeError()')
    if case=='changed_source':(app/'v4/manager_research/store.py').write_text('pass')
    if case=='state_overlap':v['manager_state_root']=str(app/'state')
    if case=='python_target':v['python_resolved']='/wrong/python'
    if case=='unsafe_flag':v['orders_sent']=True
    with pytest.raises((ValueError,OSError)):validate_binding(v)


def test_daemon_disabled_hook_preserves_original_minute_dispatch(monkeypatch):
    from ops import run_v35_macos_scheduler_daemon as daemon
    import json
    monkeypatch.delenv('V4_MANAGER_ANNOUNCEMENT_BINDING',raising=False)
    monkeypatch.setenv('V35_RELEASE_ID','SIMULATED-OFFLINE')
    done=Event();calls=[]
    def main(argv):
        calls.append(argv);done.set()
        print(json.dumps(dict(status='TEST_ONLY',release_id='SIMULATED-OFFLINE',production_allowed=False,buy_gate_updated=False,orders_sent=False)))
        return 0
    assert daemon.run_daemon([],scheduler_main=main,clock=lambda:datetime(2026,9,24,15,30,tzinfo=HK),stop_event=done,install_signals=False)==0
    assert calls==[[]]


def test_revoked_binding_cancels_only_owned_child():
    from infrastructure.scheduling.manager_announcement_supervisor import supervise_child
    import subprocess,sys
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert supervise_child(child,Event(),revoked=lambda:True,kill_grace=.1)=='BINDING_REVOKED'
    assert child.poll() is not None


def test_worker_and_supervisor_executable_sources_parse_without_import_stubs():
    import ast
    root=Path(__file__).resolve().parents[1]
    for relative in ('ops/run_manager_announcement_cycle.py','infrastructure/scheduling/manager_announcement_supervisor.py'):
        ast.parse((root/relative).read_bytes(),filename=relative)


def test_worker_real_cli_missing_binding_is_json_failure_and_no_state(tmp_path):
    import subprocess,sys,json
    root=Path(__file__).resolve().parents[1]
    missing=tmp_path/'absent.json'
    result=subprocess.run([sys.executable,'-I',str(root/'ops/run_manager_announcement_cycle.py'),
        '--binding',str(missing),'--dry-run'],cwd=root,capture_output=True,text=True)
    assert result.returncode==2
    value=json.loads(result.stdout)
    assert value['status']=='FAILED' and value['orders_sent'] is False
    assert not missing.exists() and not list(tmp_path.iterdir())
