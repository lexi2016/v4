from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.r3_scoped_loader import install as _install_scoped
_install_scoped()

from v4.manager_research.workspace import seal_attempt, validate_attempt


def test_scheduled_preopen_attempt_contract_is_distinct_and_accepted():
    row = seal_attempt({
        "schema_version": "v4.manager_research.workspace_attempt.v1",
        "target_trade_date": "20260925",
        "run_id": "a" * 32,
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "state": "RUNNING",
        "execution_kind": "SCHEDULED_PREOPEN",
        "started_at": "2026-09-25T00:59:30+00:00",
        "last_success_at": None,
        "failure_reasons": [],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    })
    assert validate_attempt(row, "20260925")["execution_kind"] == "SCHEDULED_PREOPEN"


def test_preopen_autorun_is_due_only_inside_native_preopen_window_and_never_backfills():
    from v4.manager_research.workspace_plan_autorun import preopen_window, run_scheduled_preopen_plan
    from v4.manager_research.workspace_projection import HK

    start, end = preopen_window("20260925", lead_seconds=60)
    assert start.isoformat() == "2026-09-25T09:29:00+08:00"
    assert end.isoformat() == "2026-09-25T09:30:00+08:00"

    calls = []
    service = SimpleNamespace(
        get_workspace_plan=lambda date: None,
        refresh_workspace_plan=lambda date, **kw: calls.append((date, kw)) or {
            "plan_product": {"status": "CURRENT", "run_id": "b" * 32, "generated_at": kw["now"].isoformat()},
            "plan_context": {"research_cutoff": kw["now"].isoformat()},
        },
    )
    before = run_scheduled_preopen_plan(
        service, "20260925", now=datetime(2026, 9, 25, 9, 28, 59, tzinfo=HK),
        config={"enabled": True, "lead_seconds": 60},
    )
    assert before["status"] == "NOT_DUE" and calls == []

    due = run_scheduled_preopen_plan(
        service, "20260925", now=datetime(2026, 9, 25, 9, 29, 30, tzinfo=HK),
        config={"enabled": True, "lead_seconds": 60},
    )
    assert due["status"] == "MATERIALIZED"
    assert calls[0][1]["execution_kind"] == "SCHEDULED_PREOPEN"

    late = run_scheduled_preopen_plan(
        service, "20260925", now=datetime(2026, 9, 25, 9, 30, 0, tzinfo=HK),
        config={"enabled": True, "lead_seconds": 60},
    )
    assert late["status"] == "EXPIRED_NO_BACKFILL"
    assert len(calls) == 1


def test_preopen_autorun_returns_owner_same_input_plan_without_duplicate_publication():
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan
    from v4.manager_research.workspace_projection import HK

    calls = []
    service = SimpleNamespace(
        refresh_workspace_plan=lambda date, **kw: calls.append((date, kw)) or {
            "plan_product": {
                "status": "ALREADY_MATERIALIZED",
                "run_id": "c" * 32,
                "generated_at": "2026-09-25T09:29:10+08:00",
            },
            "plan_context": {"research_cutoff": "2026-09-25T09:29:05+08:00"},
        },
    )
    result = run_scheduled_preopen_plan(
        service, "20260925", now=datetime(2026, 9, 25, 9, 29, 40, tzinfo=HK),
        config={"enabled": True, "lead_seconds": 60},
    )
    assert result["status"] == "ALREADY_MATERIALIZED"
    assert result["run_id"] == "c" * 32
    assert len(calls) == 1
    assert calls[0][0] == "20260925"
    assert calls[0][1]["execution_kind"] == "SCHEDULED_PREOPEN"


def test_vibe_preflight_is_explicit_a_share_context_and_never_claims_hk_coverage():
    from v4.manager_research.vibe_binding_preflight import preflight_vibe_binding

    missing = preflight_vibe_binding(None, ["20260924", "20260925"])
    assert missing["status"] == "NOT_CONFIGURED"
    assert missing["hk_candidate_coverage"] == "NOT_PROVIDED_BY_VIBE_A_SHARE_REVIEW_CONTRACT"
    assert missing["network_requests"] == 0
    assert missing["required_inputs"] == ["binding_json", "implementation_manifest_sha256", "input_sha256_by_date:20260924", "input_sha256_by_date:20260925"]


def test_writer_namespace_compatibility_gate_requires_disjoint_writers_and_concurrent_union():
    from v4.manager_research.activation_canary import evaluate_writer_namespaces

    passed = evaluate_writer_namespaces(
        announcement_paths={"workspace_announcements/20260925/a.json", "materials/blobs/x"},
        materializer_paths={"workbench_research/20260925/1530.json"},
        concurrent_paths={"workspace_announcements/20260925/a.json", "materials/blobs/x", "workbench_research/20260925/1530.json"},
    )
    assert passed["status"] == "PASS"

    overlap = evaluate_writer_namespaces(
        announcement_paths={"workbench_research/20260925/shared.json"},
        materializer_paths={"workbench_research/20260925/shared.json"},
        concurrent_paths={"workbench_research/20260925/shared.json"},
    )
    assert overlap["status"] == "STOP"
    assert overlap["overlap"] == ["workbench_research/20260925/shared.json"]

def test_us_activation_decision_requires_real_producer_and_manager_readback_same_payload():
    from v4.manager_research.activation_canary import evaluate_us_activation
    good=evaluate_us_activation({
        "producer_invoked":True,"producer_status":"READY","payload_sha256":"a"*64,
        "reader_lineage":{"status":"VERIFIED","payload_sha256":"a"*64,"receipt_sha256":"b"*64,"manifest_sha256":"c"*64},
        "bridge_status":"READY","expected_us_session":"20260924","producer_us_session":"20260924",
        "source_unchanged":True,
    })
    assert good["status"]=="PASS"
    bad=evaluate_us_activation({**good["evidence"],"producer_invoked":False})
    assert bad["status"]=="STOP" and "US_PRODUCER_NOT_INVOKED" in bad["gaps"]

def test_vibe_preflight_can_close_only_as_a_share_context_after_exact_owner_reads():
    from v4.manager_research.vibe_binding_preflight import preflight_vibe_binding, finalize_vibe_preflight
    config={"schema_version":"v4.manager_existing_vibe_binding.v1","implementation_manifest_sha256":"a"*64,
            "input_sha256_by_date":{"20260924":"b"*64,"20260925":"c"*64}}
    started=preflight_vibe_binding(config,["20260924","20260925"])
    closed=finalize_vibe_preflight(started,verified_dates=["20260924","20260925"],failed_dates=[])
    assert closed["status"]=="READY_A_SHARE_CONTEXT_ONLY"
    assert closed["verified_dates"]==["20260924","20260925"]
    assert closed["hk_candidate_coverage"]=="NOT_PROVIDED_BY_VIBE_A_SHARE_REVIEW_CONTRACT"


def test_preopen_safe_wrapper_never_blocks_announcement_on_plan_failure():
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe
    from v4.manager_research.workspace_projection import HK
    class Broken:
        def refresh_workspace_plan(self, date, **kwargs):
            raise ValueError("BROKEN_SAVED_PLAN")
    row=run_scheduled_preopen_plan_safe(Broken(),"20260925",now=datetime(2026,9,25,9,29,10,tzinfo=HK),config={"enabled":True,"lead_seconds":60})
    assert row["status"]=="FAILED"
    assert row["reason"]=="ValueError"
    assert row["blocks_announcement"] is False


def test_preopen_autorun_rejects_materialization_that_finishes_after_continuous_open():
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan
    from v4.manager_research.workspace_projection import HK
    service=SimpleNamespace(
        get_workspace_plan=lambda date: None,
        refresh_workspace_plan=lambda date, **kw: {
            "plan_product":{"status":"CURRENT","run_id":"d"*32,"generated_at":"2026-09-25T09:30:00.000001+08:00"},
            "plan_context":{"research_cutoff":kw["now"].isoformat()},
        },
    )
    row=run_scheduled_preopen_plan(service,"20260925",now=datetime(2026,9,25,9,29,59,tzinfo=HK),config={"enabled":True,"lead_seconds":60})
    assert row["status"]=="MISSED_COMPLETION_BOUNDARY"
    assert row["generated_at"]=="2026-09-25T09:30:00.000001+08:00"


def test_recovery_gate_requires_observed_interrupt_and_successful_both_writer_recovery():
    from v4.manager_research.activation_canary import evaluate_recovery
    good=evaluate_recovery(interruption_observed=True,announcement_returncode=0,materializer_returncode=0,
        recovery_paths={"workspace_announcements/20260925/a.json","workbench_research/20260925/1530.json"},
        allowed_paths={"workspace_announcements/20260925/a.json","workbench_research/20260925/1530.json"},
        pre_interrupt_change_observed=True)
    assert good["status"]=="CANNOT_CONFIRM"
    bad=evaluate_recovery(interruption_observed=False,announcement_returncode=0,materializer_returncode=0,
        recovery_paths=set(),allowed_paths=set())
    assert bad["status"]=="STOP"
    assert "INTERRUPTION_NOT_OBSERVED" in bad["gaps"]


def test_writer_gate_compares_stable_namespaces_not_uuid_file_names():
    from v4.manager_research.activation_canary import evaluate_writer_namespaces
    row=evaluate_writer_namespaces(
        announcement_paths={"workspace_announcements/20260925/run-a.json","materials/blobs/a"},
        materializer_paths={"workbench_research/20260925/run-a.json"},
        concurrent_paths={"workspace_announcements/20260925/run-b.json","materials/blobs/b","workbench_research/20260925/run-b.json"},
    )
    assert row["status"]=="PASS"
    assert row["missing_concurrent_namespaces"]==[]


def test_recovery_gate_allows_new_crash_artifacts_only_inside_verified_writer_namespaces():
    from v4.manager_research.activation_canary import evaluate_recovery
    good=evaluate_recovery(interruption_observed=True,announcement_returncode=0,materializer_returncode=0,
        recovery_paths={"workspace_announcements/20260925/recovery.json","workbench_research/20260925/1530-new.json"},
        allowed_paths={"workspace_announcements/20260925/run-a.json","workbench_research/20260925/run-a.json"},
        pre_interrupt_change_observed=True)
    assert good["status"]=="CANNOT_CONFIRM"
    bad=evaluate_recovery(interruption_observed=True,announcement_returncode=0,materializer_returncode=0,
        recovery_paths={"foreign_root/escape.json"},allowed_paths={"workspace_announcements/20260925/run-a.json"})
    assert bad["status"]=="STOP"
    assert bad["unexpected_recovery_writes"]==["foreign_root/escape.json"]


def test_shared_root_canary_refuses_unverified_fake_owner_commands_before_launch(tmp_path):
    import json, sys
    from ops.run_manager_state_compatibility_canary import main
    source=tmp_path/'source'; source.mkdir(); (source/'seed.txt').write_text('seed')
    app=Path(__file__).resolve().parents[1]
    fake=tmp_path/'fake_announcement.py'
    receipt=tmp_path/'receipt.json'
    marker=tmp_path/'was-launched'
    fake.write_text(f"from pathlib import Path; Path({str(marker)!r}).write_text('launched')\n")
    args=[
        '--source-state-root',str(source),'--app-root',str(app),
        '--announcement-command-json',json.dumps([sys.executable,'-B',str(fake),'--state-root','{state_root}','--trade-date','20260925']),
        '--materializer-command-json',json.dumps([sys.executable,'-B','-m','ops.materialize_manager_close_discovery','--state-root','{state_root}','--trade-date','20260925']),
        '--timeout-seconds','2','--interrupt-after-seconds','1.0','--receipt',str(receipt),
    ]
    with pytest.raises(ValueError,match='CANARY_ANNOUNCEMENT_OWNER_IDENTITY_UNVERIFIED'):
        main(args)
    assert not marker.exists()
    assert not receipt.exists()


@pytest.mark.parametrize('blocked_flag',['--universe-root','--universe-only','--data-root'])
def test_shared_root_canary_refuses_materializer_without_verified_external_inputs(tmp_path,blocked_flag):
    import json, sys
    from ops.run_manager_state_compatibility_canary import _command
    app=Path(__file__).resolve().parents[1]
    source=tmp_path/'source';source.mkdir()
    external=tmp_path/'external';external.mkdir()
    command=[sys.executable,'-B','-m','ops.materialize_manager_close_discovery',
        '--state-root','{state_root}','--trade-date','20260925']
    if blocked_flag!='--universe-only':command.extend([blocked_flag,str(external)])
    else:command.append(blocked_flag)
    with pytest.raises(ValueError,match='CANARY_EXTERNAL_OWNER_INPUT_NOT_ISOLATED:'+blocked_flag):
        _command(json.dumps(command),tmp_path/'sandbox',source,app,'materializer')


def test_shared_root_canary_refuses_materializer_when_no_offline_replay_interface_exists(tmp_path):
    import json,sys
    from ops.run_manager_state_compatibility_canary import _command
    app=Path(__file__).resolve().parents[1];source=tmp_path/'source';source.mkdir()
    command=json.dumps([sys.executable,'-B','-m','ops.materialize_manager_close_discovery',
        '--state-root','{state_root}','--trade-date','20260925'])
    with pytest.raises(ValueError,match='CANARY_MATERIALIZER_OFFLINE_REPLAY_REQUIRED'):
        _command(command,tmp_path/'sandbox',source,app,'materializer')


def test_recovery_gate_requires_observed_change_before_interrupt():
    from v4.manager_research.activation_canary import evaluate_recovery
    row=evaluate_recovery(interruption_observed=True,pre_interrupt_change_observed=False,announcement_returncode=0,materializer_returncode=0,
        recovery_paths={"workspace_announcements/20260925/a.json"},allowed_paths={"workspace_announcements/20260925/base.json"})
    assert row["status"]=="STOP"
    assert "PRE_INTERRUPT_CHANGE_NOT_OBSERVED" in row["gaps"]


def test_scheduled_workspace_plan_never_persists_if_computation_finishes_after_deadline(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import v4.manager_research.workspace as workspace
    from v4.manager_research.workspace_projection import HK

    class Store:
        def __init__(self, root):
            self.root=root
            self.rows={}
        @contextmanager
        def _transaction(self, *args):
            yield
        def _read(self, path):
            return self.rows.get(str(path))
        def _write_atomic(self, path, value):
            self.rows[str(path)]=value

    store=Store(tmp_path)
    service=SimpleNamespace(store=store)
    monkeypatch.setattr(workspace, 'get_workspace', lambda *a, **k: {
        'gaps':[], 'stocks':[{'symbol':'HK.00001'}], 'input_identity':'a'*64,
        'existing_material_coverage':{}, 'summary':{}, 'semantic_version':'fixture',
    })
    monkeypatch.setattr(workspace, '_now', lambda: '2026-09-25T01:30:01+00:00')
    with pytest.raises(TimeoutError):
        workspace.refresh_workspace_plan(
            service,'20260925',execution_kind='SCHEDULED_PREOPEN',
            now=datetime(2026,9,25,9,29,50,tzinfo=HK),
            deadline=datetime(2026,9,25,9,30,0,tzinfo=HK),
        )
    assert not any('/workspace_plans/' in key for key in store.rows)
    latest=store.rows[str(tmp_path/'workspace_plan_runs'/'20260925'/'latest.json')]
    assert latest['state']=='FAILED'
    assert latest['failure_reasons']==['WORKSPACE_PLAN_REFRESH_FAILED:TimeoutError']


def test_activation_receipt_gate_rejects_in_memory_and_empty_pass_shaped_receipts(tmp_path):
    import json
    from v4.manager_research.activation_canary import validate_activation_receipt
    announcement={
      'schema_version':'v4.manager_research.shared_root_canary.v3',
      'decision':{'status':'PASS'},
      'writes':{'announcement':[],'materializer':[],'concurrent':[]},
      'recovery':{'interruption_observed':True,'pre_interrupt_change_observed':True,'writes':[],
        'announcement_result':{'returncode':0,'timed_out':False},'materializer_result':{'returncode':0,'timed_out':False},
        'decision':{'status':'PASS'}},
      'seed_manifest_sha256':'a'*64,'source_manifest_before_sha256':'a'*64,'source_manifest_after_sha256':'a'*64,
      'source_unchanged':True,'app_unchanged':True,'simulated':False,'production_allowed':False,
      'buy_gate_updated':False,'orders_sent':False,
    }
    receipt=tmp_path/'forged.json'; receipt.write_text(json.dumps(announcement))
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ACTIVATION_RECEIPT_INVALID'):
        validate_activation_receipt(announcement,'announcement')
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ACTIVATION_RECEIPT_INVALID'):
        validate_activation_receipt(receipt,'announcement')
    v6_receipt={**announcement,'schema_version':'v4.manager_research.shared_root_canary.v6'}
    v6_path=tmp_path/'old-v6.json'; v6_path.write_text(json.dumps(v6_receipt))
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ACTIVATION_RECEIPT_INVALID'):
        validate_activation_receipt(v6_path,'announcement')

    evidence={
        'producer_invoked':True,'producer_status':'READY','payload_sha256':'b'*64,
        'reader_lineage':{'status':'VERIFIED','payload_sha256':'b'*64,'receipt_sha256':'c'*64,'manifest_sha256':'d'*64},
        'bridge_status':'READY','expected_us_session':'20260924','producer_us_session':'20260924','source_unchanged':True,
    }
    us={'schema_version':'v4.manager_research.us_activation_canary.v2',
        'decision':{'status':'PASS','evidence':evidence},'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    from v4.manager_research.activation_canary import evaluate_us_activation
    assert evaluate_us_activation(evidence)['status']=='PASS'
    forged={'schema_version':'v4.manager_research.us_activation_canary.v2',
            'decision':{'status':'PASS','evidence':{'source_unchanged':True}},
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    with pytest.raises(ValueError,match='US_ACTIVATION_RECEIPT_INVALID'):
        validate_activation_receipt(forged,'us')
    forged_with_claims={**us,'producer':{'payload_sha256':'b'*64,'market_snapshot_status':'READY'},
        'bridge':{'status':'READY','expected_us_session':'20260924'}}
    claimed_receipt=tmp_path/'forged-us.json';claimed_receipt.write_text(json.dumps(forged_with_claims))
    with pytest.raises(ValueError,match='US_ACTIVATION_RECEIPT_INVALID'):
        validate_activation_receipt(claimed_receipt,'us')


def test_activation_gate_rejects_v6_receipts_without_actual_per_invocation_evidence(tmp_path):
    from v4.manager_research.activation_canary import _activation_invocation_evidence_valid
    raw={'prepared_announcement_invocations':[],'prepared_materializer_invocations':[],
        'scenario_evidence_root':str(tmp_path/'receipt.json.evidence')}
    artifacts={'invocation_evidence.json':{
        'schema_version':'v4.manager_research.canary_invocation_evidence.v1',
        'capture_status':'COMPLETE','invocations':[]}}
    assert not _activation_invocation_evidence_valid(
        raw,artifacts,{}, {}, {}, tmp_path, {})


def test_shared_root_canary_rejects_receipt_inside_source_before_writing(tmp_path):
    import json, sys
    from ops.run_manager_state_compatibility_canary import main

    source=tmp_path/'source'; source.mkdir(); (source/'seed.txt').write_text('seed')
    app=Path(__file__).resolve().parents[1]
    receipt=source/'receipt.json'
    args=[
        '--source-state-root',str(source),'--app-root',str(app),
        '--announcement-command-json',json.dumps([sys.executable,'-c','pass','{state_root}']),
        '--materializer-command-json',json.dumps([sys.executable,'-c','pass','{state_root}']),
        '--timeout-seconds','2','--interrupt-after-seconds','1','--receipt',str(receipt),
    ]
    with pytest.raises(ValueError,match='CANARY_RECEIPT_MUST_BE_OUTSIDE_SOURCE_AND_APP_ROOT'):
        main(args)
    assert (source/'seed.txt').read_text()=='seed'
    assert not receipt.exists()


def test_shared_root_canary_refuses_symlinked_source_tree_before_launch(tmp_path):
    source=tmp_path/'source'; source.mkdir(); (source/'seed.txt').write_text('seed')
    external=tmp_path/'external'; external.mkdir(); target=external/'target.txt'; target.write_text('original')
    (source/'linked').symlink_to(external,target_is_directory=True)
    from ops.run_manager_state_compatibility_canary import _copy_seed,manifest
    with pytest.raises(ValueError,match='CANARY_SOURCE_STATE_SYMLINK_UNSUPPORTED'):
        _copy_seed(source,tmp_path/'copy')
    assert target.read_text()=='original'
    scenario=tmp_path/'scenario';scenario.mkdir()
    (scenario/'escape').symlink_to(external,target_is_directory=True)
    with pytest.raises(ValueError,match='CANARY_SCENARIO_SYMLINK_UNSUPPORTED'):
        manifest(scenario)


def test_legacy_r2_workspace_plan_without_execution_kind_remains_readable(tmp_path):
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.workspace import PLAN_SCHEMA, _read_plan
    from v4.manager_research.workspace_projection import FLAGS, digest

    store=ManagerResearchStore(tmp_path/'manager')
    date='20260925'; identity='e'*64
    workspace={'target_trade_date':date,'input_identity':identity}
    product={
        'schema_version':PLAN_SCHEMA,'target_trade_date':date,'run_id':'f'*32,
        'generated_at':'2026-09-25T01:20:00+00:00','input_identity':identity,
        'workspace':workspace,**FLAGS,
    }
    product['sha256']=digest(product)
    store._write_atomic(store.root/'workspace_plans'/date/'latest.json',product)
    loaded=_read_plan(store,date)
    assert loaded==product
    assert 'execution_kind' not in loaded


def test_concurrent_preopen_autorun_rechecks_plan_under_owner_transaction(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.workspace_projection import HK
    import v4.manager_research.workspace as workspace
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan

    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    compute_lock=Lock(); computes=[]
    def project(*args,**kwargs):
        with compute_lock:
            computes.append(1)
        return {'target_trade_date':'20260925','gaps':[],'stocks':[{'symbol':'HK.00001'}],'input_identity':'a'*64,
            'existing_material_coverage':{},'summary':{},'semantic_version':'fixture',
            'plan_context':{'research_cutoff':'2026-09-25T09:29:30+08:00'}}
    monkeypatch.setattr(workspace,'get_workspace',project)
    monkeypatch.setattr(workspace,'_now',lambda:'2026-09-25T01:29:40+00:00')
    now=datetime(2026,9,25,9,29,30,tzinfo=HK)
    config={'enabled':True,'lead_seconds':60}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run_scheduled_preopen_plan,service,'20260925',now=now,config=config) for _ in range(2)]
        rows=[future.result(timeout=10) for future in futures]
    assert sorted(row['status'] for row in rows)==['ALREADY_MATERIALIZED','MATERIALIZED']
    assert len(computes)==2
    assert rows[0]['run_id']==rows[1]['run_id']
    plan_files=list((tmp_path/'manager'/'workspace_plans'/'20260925').glob('*.json'))
    assert len(plan_files)==2


def test_canary_namespace_tree_overlap_and_missing_owner_transaction_evidence_stop_activation():
    from v4.manager_research.activation_canary import evaluate_recovery,evaluate_writer_namespaces
    collided=evaluate_writer_namespaces(
        announcement_paths={'shared/root/a.json'},
        materializer_paths={'shared/root/b.json'},
        concurrent_paths={'shared/root/a.json','shared/root/b.json'},
    )
    assert collided['status']=='STOP'
    assert collided['namespace_overlap']==['shared/root']
    no_pre_interrupt_change=evaluate_recovery(interruption_observed=True,announcement_returncode=0,materializer_returncode=0,
        recovery_paths={'workspace_announcements/20260925/recovery.json'},
        allowed_paths={'workspace_announcements/20260925/base.json'})
    assert no_pre_interrupt_change['status']=='STOP'
    assert 'PRE_INTERRUPT_CHANGE_NOT_OBSERVED' in no_pre_interrupt_change['gaps']


def test_canary_environment_is_allowlisted_and_timeout_terminates_spawned_process_group(tmp_path,monkeypatch):
    import os,signal,subprocess,sys,tempfile,time
    from ops.run_manager_state_compatibility_canary import _env,_result
    monkeypatch.setenv('PYTHONPATH','/unsafe/inherited')
    monkeypatch.setenv('V4_MANAGER_STATE_ROOT','/unsafe/state')
    monkeypatch.setenv('API_TOKEN','never-copy-this')
    env=_env()
    assert 'PYTHONPATH' not in env and 'V4_MANAGER_STATE_ROOT' not in env and 'API_TOKEN' not in env
    assert set(env)=={'PATH','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE','PRODUCTION_ALLOWED',
        'BUY_GATE_UPDATED','ORDERS_SENT','TMPDIR','LANG','LC_ALL'}
    assert env['TMPDIR']==str(Path(tempfile.gettempdir()).resolve())
    assert env['PRODUCTION_ALLOWED']=='false' and env['BUY_GATE_UPDATED']=='false' and env['ORDERS_SENT']=='false'

    marker=tmp_path/'surviving-child.txt'
    child_code=("import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"time.sleep(.6); pathlib.Path({str(marker)!r}).write_text('alive')")
    parent_code=("import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-B','-c',{child_code!r}]); time.sleep(30)")
    parent=subprocess.Popen([sys.executable,'-B','-c',parent_code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,env=env,start_new_session=True)
    result=_result(parent,.1)
    time.sleep(.7)
    assert result['timed_out'] is True
    assert not marker.exists()


def _enabled_binding_for_gate(tmp_path):
    import hashlib,sys
    from infrastructure.scheduling.manager_announcement_supervisor import BINDING_SCHEMA,binding_inventory
    app=Path(__file__).resolve().parents[1]
    master=tmp_path/'master';master.mkdir()
    python=Path(sys.executable).absolute()
    return {'schema_version':BINDING_SCHEMA,'enabled':True,'policy_status':'PROPOSAL_ONLY','policy':'BALANCED_V1',
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'research_only':True,
        'app_root':str(app),'manager_state_root':str(tmp_path/'state'),'security_master_root':str(master),
        'python':str(python),'python_resolved':str(python.resolve()),
        'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'priority_codes':[],
        'files':binding_inventory(app)}


def test_enabled_announcement_binding_requires_real_persisted_canary_evidence(tmp_path):
    import hashlib,json
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    value=_enabled_binding_for_gate(tmp_path)
    with pytest.raises(ValueError,match='ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_REQUIRED'):
        validate_binding(value)
    forged={'schema_version':'v4.manager_research.shared_root_canary.v5','decision':{'status':'PASS'},
        'writes':{'announcement':[],'materializer':[],'concurrent':[]},
        'results':{'announcement':[{'returncode':0,'timed_out':False}],
            'materializer':[{'returncode':0,'timed_out':False}],
            'concurrent':[{'returncode':0,'timed_out':False},{'returncode':0,'timed_out':False}]},
        'recovery':{'interruption_observed':True,'pre_interrupt_change_observed':True,'writes':[],
            'pre_interrupt_changed_paths':[],'owner_transaction_state':None,'announcement_result':{'returncode':0,'timed_out':False},
            'materializer_result':{'returncode':0,'timed_out':False},
            'interrupted_result':{'returncode':-15,'timed_out':False},'decision':{'status':'PASS'}},
        'seed_manifest_sha256':'a'*64,'source_manifest_before_sha256':'a'*64,
        'source_manifest_after_sha256':'a'*64,'app_inventory_sha256_before':'a'*64,
        'app_inventory_sha256_after':'a'*64,'source_state_root':str(tmp_path/'source'),
        'app_root':value['app_root'],'source_unchanged':True,'app_unchanged':True,
        'simulated':False,'environment_policy':'SANITIZED_V1','environment_keys':[
            'PATH','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE','PRODUCTION_ALLOWED','BUY_GATE_UPDATED','ORDERS_SENT'],
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    receipt=tmp_path/'forged.json';receipt.write_text(json.dumps(forged))
    value['activation_receipt']={'path':str(receipt),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
    with pytest.raises(ValueError,match='ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_INVALID'):
        validate_binding(value)


def test_enabled_announcement_binding_renderer_requires_canary_receipt(tmp_path):
    from ops.render_manager_announcement_binding import main
    with pytest.raises(ValueError,match='ANNOUNCEMENT_ACTIVATION_RECEIPT_REQUIRED'):
        main(['--app-root',str(tmp_path/'app'),'--manager-state-root',str(tmp_path/'state'),
            '--security-master-root',str(tmp_path/'master'),'--python',str(Path(__import__('sys').executable).absolute()),
            '--output',str(tmp_path/'binding.json'),'--enabled'])


def _legacy_r2_plan_for_history(tmp_path, *, execution_kind='__OMIT__'):
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.workspace import PLAN_SCHEMA
    from v4.manager_research.workspace_plan import plan_context
    from v4.manager_research.workspace_projection import FLAGS, SCHEMA, HK, digest
    from v4.manager_research.workspace_semantics import SEMANTIC_VERSION

    date='20260925'
    cutoff=datetime(2026,9,25,9,29,0,tzinfo=HK)
    context=plan_context(date,now=cutoff)
    body={
        'schema_version':SCHEMA,
        'semantic_version':SEMANTIC_VERSION,
        'decision_projection_version':'20260921.manager-decision-ux.a1',
        'target_trade_date':date,
        'stocks':[],'themes':[],'materials':[],'company_events':[],
        'focus_symbols':[],'rejected_relations':[],'briefing':{},'summary':{},
        'market_screen':{},'announcement_review':{},'plan_context':context,
        'input_identity':'e'*64,'gaps':[],**FLAGS,
    }
    product={
        'schema_version':PLAN_SCHEMA,'target_trade_date':date,'run_id':'f'*32,
        'generated_at':context['research_cutoff'],'input_identity':body['input_identity'],
        'owner':'ManagerResearchJobService.refresh_workspace_plan',
        'workspace':body,**FLAGS,
    }
    if execution_kind!='__OMIT__':
        product['execution_kind']=execution_kind
    product['sha256']=digest(product)
    store=ManagerResearchStore(tmp_path/'manager')
    store._write_atomic(store.root/'workspace_plans'/date/'latest.json',product)
    return store,product,body


def test_legacy_r2_plan_without_execution_kind_passes_the_actual_historical_read_gate(tmp_path,monkeypatch):
    from copy import deepcopy
    import v4.manager_research.workspace as workspace
    from v4.manager_research.workspace_history import read_history

    store,product,body=_legacy_r2_plan_for_history(tmp_path)
    calls=[]
    def revalidate(service,date,*,include_saved,context):
        calls.append((date,include_saved,context['research_cutoff']))
        return deepcopy(body)
    monkeypatch.setattr(workspace,'_compute_workspace',revalidate)
    result=read_history(SimpleNamespace(store=store),'20260925')
    assert calls and calls[0][0]=='20260925' and calls[0][1] is False
    assert result['read_context']['status'] in {'VERIFIED','VERIFIED_WITH_GAPS'}
    assert result['plan_product']['status']=='CURRENT'
    assert result['plan_product']['consumed'] is True
    assert result['read_context']['legacy_full_revalidation'] is True
    assert 'execution_kind' not in product


def test_history_plan_rejects_explicit_unknown_execution_kind(tmp_path):
    from v4.manager_research.workspace_history import _read_candidate
    store,_,_=_legacy_r2_plan_for_history(tmp_path,execution_kind='UNRECOGNIZED')
    with pytest.raises(ValueError,match='HISTORY_PLAN_IDENTITY_INVALID'):
        _read_candidate(store,'20260925','latest.json')


def test_standalone_announcement_canary_refuses_existing_app_root_before_owner_calls(tmp_path,monkeypatch):
    import v4.manager_research.materials as materials_module
    import v4.manager_research.store as store_module
    import v4.manager_research.hkex_provider as provider_module
    import v4.manager_research.service as service_module
    from ops.run_manager_announcement_owner_canary import main

    app=Path(__file__).resolve().parents[1]
    calls=[]
    monkeypatch.setattr(materials_module,'MaterialStore',lambda *a,**k:calls.append(('materials',a)))
    monkeypatch.setattr(store_module,'ManagerResearchStore',lambda *a,**k:calls.append(('store',a)))
    monkeypatch.setattr(provider_module,'HkexOfficialProvider',lambda *a,**k:calls.append(('provider',a)))
    monkeypatch.setattr(service_module,'ManagerResearchJobService',lambda *a,**k:calls.append(('service',a)))
    with pytest.raises(ValueError,match='ANNOUNCEMENT_CANARY_SANDBOX_IDENTITY_INVALID'):
        main(['--state-root',str(app),'--security-master-root',str(app),
            '--trade-date','20260925','--sandbox-identity',str(tmp_path/'identity.json'),
            '--receipt',str(tmp_path/'receipt.json')])
    assert calls==[]
    assert not (tmp_path/'receipt.json').exists()


def test_standalone_us_canary_rejects_marker_only_root_before_producer(tmp_path,monkeypatch):
    from ops.run_manager_us_activation_canary import main
    import ops.us_market_digest as producer_module

    root=tmp_path/'existing-data';root.mkdir()
    (root/'.manager-us-activation-canary').write_text('marker is not an identity')
    calls=[]
    monkeypatch.setattr(producer_module,'materialize_us_market_phase',lambda **kw:calls.append(kw))
    with pytest.raises(ValueError,match='US_CANARY_SANDBOX_IDENTITY_INVALID'):
        main(['--data-root',str(root),'--us-session-date','20260924',
            '--target-hk-date','20260925','--manager-cutoff','2026-09-25T08:59:30+08:00',
            '--sandbox-identity',str(tmp_path/'identity.json'),'--receipt',str(tmp_path/'receipt.json')])
    assert calls==[]
    assert not (tmp_path/'receipt.json').exists()


def test_canary_identity_binds_fresh_temp_roots_receipt_owner_tree_and_exact_arguments(tmp_path):
    import tempfile
    from v4.manager_research.activation_canary import write_canary_sandbox_identity,validate_canary_sandbox_identity,claim_canary_sandbox_identity

    app=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='manager-state-canary-') as temp:
        sandbox=Path(temp).resolve()
        state=sandbox/'announcement';state.mkdir()
        master=sandbox/'master';master.mkdir();(master/'keys.json').write_text('{}')
        identity=sandbox/'identities'/'announcement.json';identity.parent.mkdir()
        receipt=sandbox/'receipts'/'announcement.json';receipt.parent.mkdir()
        args=['--state-root',str(state),'--security-master-root',str(master),
            '--trade-date','20260925','--sandbox-identity',str(identity),'--receipt',str(receipt)]
        write_canary_sandbox_identity(identity,'announcement',data_root=state,receipt_path=receipt,
            app_root=app,security_master_root=master,argv=args)
        verified=validate_canary_sandbox_identity(identity,'announcement',data_root=state,
            receipt_path=receipt,app_root=app,security_master_root=master,argv=args)
        assert verified['status']=='VERIFIED'
        assert verified['run_id']
        wrong_args=[*args];wrong_args[wrong_args.index('--trade-date')+1]='20260926'
        with pytest.raises(ValueError,match='CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH'):
            validate_canary_sandbox_identity(identity,'announcement',data_root=state,
                receipt_path=receipt,app_root=app,security_master_root=master,argv=wrong_args)
        claimed=claim_canary_sandbox_identity(identity,'announcement',data_root=state,
            receipt_path=receipt,app_root=app,security_master_root=master,argv=args)
        assert claimed['status']=='VERIFIED'
        with pytest.raises(ValueError,match='CANARY_SANDBOX_IDENTITY_INVALID'):
            validate_canary_sandbox_identity(identity,'announcement',data_root=state,
                receipt_path=receipt,app_root=app,security_master_root=master,argv=args)


def _announcement_command_identity(tmp_path,master):
    import hashlib,json,sys
    app=Path(__file__).resolve().parents[1]
    entrypoint=app/'ops/run_manager_announcement_owner_canary.py'
    argv=[str(Path(sys.executable).absolute()),'-B','-m','ops.run_manager_announcement_owner_canary',
        '--state-root','{state_root}','--security-master-root',str(master),
        '--trade-date','20260925','--sandbox-identity','{sandbox_identity}','--receipt','{receipt}']
    executable=Path(argv[0])
    return {'role':'announcement','argv_template':argv,
        'argv_sha256':hashlib.sha256(json.dumps(argv,ensure_ascii=False,sort_keys=True,indent=2).encode()).hexdigest(),
        'executable_path':str(executable),'executable_resolved':str(executable.resolve()),
        'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'entrypoint_kind':'module','entrypoint_name':'ops.run_manager_announcement_owner_canary',
        'entrypoint_path':str(entrypoint),'entrypoint_sha256':hashlib.sha256(entrypoint.read_bytes()).hexdigest()}


def test_shared_root_harness_renders_identity_and_receipt_for_child_claim(tmp_path):
    import json
    import subprocess
    import sys
    import tempfile
    from ops.run_manager_state_compatibility_canary import _env,_prepare_announcement_invocation

    app=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='manager-state-canary-') as temp:
        sandbox=Path(temp).resolve()
        data_root=sandbox/'announcement';data_root.mkdir()
        security_master=sandbox/'master';security_master.mkdir()
        (security_master/'keys.json').write_text('{}')
        template=_announcement_command_identity(tmp_path,security_master)['argv_template']
        argv,identity,receipt,identity_doc=_prepare_announcement_invocation(
            template,sandbox_root=sandbox,data_root=data_root,app=app,invocation_id='announcement')

        assert argv[argv.index('--state-root')+1]==str(data_root)
        assert argv[argv.index('--sandbox-identity')+1]==str(identity)
        assert argv[argv.index('--receipt')+1]==str(receipt)
        assert all('{state_root}' not in part and '{sandbox_identity}' not in part and '{receipt}' not in part
            for part in argv)
        assert identity_doc['run_id']
        assert not receipt.exists()

        child_code=(
            'import json,sys; '
            'from v4.manager_research.activation_canary import claim_canary_sandbox_identity; '
            'identity,data,receipt,app,master,argv_json=sys.argv[1:]; '
            'doc=claim_canary_sandbox_identity(identity,"announcement",data_root=data,receipt_path=receipt, '
            'app_root=app,security_master_root=master,argv=json.loads(argv_json)); '
            'print(doc["status"])'
        )
        completed=subprocess.run(
            [sys.executable,'-B','-c',child_code,str(identity),str(data_root),str(receipt),str(app),
                str(security_master),json.dumps(argv)],
            cwd=app,
            env=_env(),
            text=True,capture_output=True,check=False,
        )
        assert completed.returncode==0,completed.stderr
        assert completed.stdout.strip()=='VERIFIED'
        assert identity.with_name(identity.name+'.started').is_file()
        assert not receipt.exists()


def test_us_canary_identity_requires_fresh_temp_data_and_receipt_paths():
    import tempfile
    from v4.manager_research.activation_canary import write_canary_sandbox_identity,claim_canary_sandbox_identity
    app=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='manager-us-activation-canary-') as temp:
        sandbox=Path(temp).resolve();data=sandbox/'data';data.mkdir()
        identity=sandbox/'identities'/'us.json';identity.parent.mkdir()
        receipt=sandbox/'receipts'/'us.json';receipt.parent.mkdir()
        args=['--data-root',str(data),'--us-session-date','20260924','--target-hk-date','20260925',
            '--manager-cutoff','2026-09-25T08:59:30+08:00','--capture-phase','PRE_OPEN',
            '--sandbox-identity',str(identity),'--receipt',str(receipt)]
        write_canary_sandbox_identity(identity,'us',data_root=data,receipt_path=receipt,
            app_root=app,argv=args)
        claimed=claim_canary_sandbox_identity(identity,'us',data_root=data,receipt_path=receipt,
            app_root=app,argv=args)
        assert claimed['status']=='VERIFIED' and claimed['kind']=='us'


def test_activation_command_identity_rejects_security_master_root_drift(tmp_path):
    from v4.manager_research.activation_canary import _stored_command_identity
    app=Path(__file__).resolve().parents[1]
    master_a=tmp_path/'master-a';master_a.mkdir()
    master_b=tmp_path/'master-b';master_b.mkdir()
    identity=_announcement_command_identity(tmp_path,master_a)
    assert _stored_command_identity(identity,'announcement',app,expected_security_master_root=master_a)
    assert not _stored_command_identity(identity,'announcement',app,expected_security_master_root=master_b)


def test_enabled_binding_passes_its_security_master_root_to_receipt_validator(tmp_path,monkeypatch):
    import hashlib,json
    import v4.manager_research.activation_canary as activation_module
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    binding=_enabled_binding_for_gate(tmp_path)
    receipt=tmp_path/'activation.json';receipt.write_text('{}')
    binding['activation_receipt']={'path':str(receipt),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
    captured={}
    def validate(path,kind,**kwargs):
        captured.update(kwargs)
        return {'status':'PASS'}
    monkeypatch.setattr(activation_module,'validate_activation_receipt',validate)
    validate_binding(binding)
    assert captured['expected_security_master_root']==Path(binding['security_master_root'])


def test_completed_atomic_file_change_without_owner_transaction_state_is_cannot_confirm():
    from v4.manager_research.activation_canary import evaluate_recovery
    decision=evaluate_recovery(interruption_observed=True,pre_interrupt_change_observed=True,
        announcement_returncode=0,materializer_returncode=0,
        recovery_paths={'workspace_announcements/20260925/complete_atomic.json'},
        allowed_paths={'workspace_announcements/20260925/complete_atomic.json'})
    assert decision['status']=='CANNOT_CONFIRM'
    assert 'OWNER_TRANSACTION_STATE_UNVERIFIED' in decision['gaps']
