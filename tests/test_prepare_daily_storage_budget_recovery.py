from copy import deepcopy
import json
from pathlib import Path
import types

import pytest

from ops import prepare_daily_storage_budget_recovery as release


def base_policy(tmp_path):
    return dict(data_root=str(tmp_path),run_root=str(tmp_path/'outputs'),formal_roots={},
        protected=['CURRENT','rollback','raw','unfinished'],auto_gc_enabled=False,dry_run=True,
        managed_pin_inventory={'path':'/fixed/pins','sha256':'exact-pins'},
        governance=dict(enabled=True,pool_id='isolated',pool_identity_verified=True,
            registry_root=str(tmp_path/'registry'),ordinary_peak_budget_bytes=224*release.GIB,
            reserve_bytes=64*release.GIB,safety_bytes=4*release.GIB,minimum_free_ratio=.10))


def test_exact_one_field_policy_change_and_all_protections_retained(tmp_path):
    before=base_policy(tmp_path);original=deepcopy(before)
    after=release.budget_policy(before)
    assert before==original
    assert after['governance']['ordinary_peak_budget_bytes']==280_246_616_064
    unchanged=deepcopy(after);unchanged['governance']['ordinary_peak_budget_bytes']=224*release.GIB
    assert unchanged==before
    release.assert_policy_delta(before,after)
    for mutation in ('reserve_bytes','safety_bytes','minimum_free_ratio'):
        bad=deepcopy(after);bad['governance'][mutation]=0
        with pytest.raises(ValueError,match='POLICY_CHANGE_OUTSIDE'):
            release.assert_policy_delta(before,bad)
    bad=deepcopy(after);bad['auto_gc_enabled']=True
    with pytest.raises(ValueError,match='POLICY_CHANGE_OUTSIDE'):release.assert_policy_delta(before,bad)


def test_original_gate_retains_all_reservations_and_accepts_bounded_capacity(tmp_path,monkeypatch):
    import importlib
    import ops
    app=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r1/v4-daily-storage-recovery-20261110-r1-main/app')
    monkeypatch.setattr(ops,'__path__',[str(app/'ops'),*ops.__path__])
    gate=importlib.import_module('ops.research_storage_governance')
    before=base_policy(tmp_path)
    config=gate.configuration(before)
    registry=gate.Registry(config,tmp_path)
    state={'tasks':{'old':dict(reserved_bytes=34_713_824_729,written_bytes=12_313,
        logical_written_bytes=0,category='ordinary',state='FAILED_RECOVERABLE')}}
    monkeypatch.setattr(gate.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=294_229_622_784,total=1_995_165_736_960))
    def sample():
        return registry.space(state,'new',68_719_476_736,category='ordinary',optional_full=False,category_used=176_179_710_037)
    with pytest.raises(gate.SpaceBlocked,match='CATEGORY_BUDGET_BLOCKED'):sample()
    config['ordinary_peak_budget_bytes']=release.NEW_BUDGET
    assert sample()['other_remaining_bytes']==34_713_812_416
    assert state['tasks']['old']['reserved_bytes']==34_713_824_729
    assert sum(release.CAPACITY.values())==279_613_011_502
    assert release.NEW_BUDGET-sum(release.CAPACITY.values())==633_604_562
    monkeypatch.setattr(gate.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=70*release.GIB,total=1000*release.GIB))
    with pytest.raises(gate.SpaceBlocked):sample()


def test_preflight_runs_exact_pinned_original_gate_with_same_interpreter(tmp_path,monkeypatch):
    pins=tmp_path/'pins.json';pins.write_text(json.dumps({'expected_main_app_root':'/exact/main/app'}))
    policy=base_policy(tmp_path);policy['managed_pin_inventory']=release.record(pins)
    seen=[]
    def run(argv,**kw):
        seen.append((argv,kw))
        return types.SimpleNamespace(returncode=0,stdout=json.dumps({'gate_source':'/exact/main/app/ops/research_storage_governance.py','other_remaining_bytes':34_713_812_416,'logical_other_remaining_bytes':34_713_824_729,'category_baseline_bytes':176_179_710_037,'free_bytes':294_229_622_784,'total_bytes':1_995_165_736_960}))
    monkeypatch.setattr(release.subprocess,'run',run)
    sample=release.capacity_check(release.budget_policy(policy))
    assert sample['other_remaining_bytes']==34_713_812_416
    argv,kw=seen[0]
    assert argv[:3]==[release.sys.executable,'-B','-c'] and argv[4]=='/exact/main/app'
    assert kw['capture_output'] is True and json.loads(kw['input'])==release.budget_policy(policy)
    assert 'with registry.writer(),registry.transaction()' in argv[3]
    assert 'registry.space' in argv[3] and 'registry.save' not in argv[3]


@pytest.fixture
def transaction(tmp_path,monkeypatch):
    events=[]
    live=tmp_path/'live.plist';live.write_bytes(b'original')
    draft=tmp_path/'draft.plist';draft.write_bytes(b'candidate')
    policy=tmp_path/'policy.json';policy.write_text('{}')
    main=dict(live_plist=str(live),draft_plist=str(draft),label='com.lexi.v4.scheduler',
        before_sha256=release.sha(live),draft_plist_sha256=release.sha(draft))
    locks=tmp_path/'locks';locks.mkdir()
    packet=tmp_path/'PACKET.json'
    value=dict(services={'main':main},policy=release.record(policy),scheduler_lane_lock_root=str(locks))
    packet.write_text(json.dumps(value))
    review=tmp_path/'REVIEW.json';review.write_text(json.dumps(dict(verdict='PASS',packet_sha256=release.sha(packet))))
    monkeypatch.setattr(release,'validate',lambda *a,**kw:events.append(('validate',kw)))
    monkeypatch.setattr(release,'loaded_environment_check',lambda _:events.append(('loaded-env','main')))
    monkeypatch.setattr(release,'capacity_check',lambda _:events.append(('capacity','all-reservations')))
    monkeypatch.setattr(release.svc,'require_idle_main',lambda _:events.append(('idle','main')))
    monkeypatch.setattr(release.svc,'loaded',lambda _:(types.SimpleNamespace(returncode=0,stdout='running'),123))
    monkeypatch.setattr(release.svc,'descendants',lambda _:[123])
    monkeypatch.setattr(release.svc,'wait_drained',lambda label,pids:events.append(('drained',label)))
    monkeypatch.setattr(release.svc,'wait_running',lambda _:events.append(('running','main')))
    def run(argv):
        events.append(('service',argv[1],argv[-1]))
        return types.SimpleNamespace(check_returncode=lambda:None)
    monkeypatch.setattr(release.svc,'run',run)
    return packet,review,live,main,events


def test_main_only_transaction_and_explicit_rollback(transaction):
    packet,review,live,main,events=transaction
    result=release.cutover(packet,review)
    assert live.read_bytes()==b'candidate'
    assert result['control_roles']==['main']
    assert result['status']=='ACTIVATED_MAIN_POLICY_ONLY'
    assert not result['api_service_operation'] and not result['stage_service_operation']
    calls=[e for e in events if e[0]=='service']
    assert [e[1] for e in calls]==['bootout','bootstrap']
    assert all('scheduler' in e[2] or e[2]==str(live) for e in calls)
    result=release.cutover(packet,review,rollback=True)
    assert live.read_bytes()==b'original' and result['status']=='RESTORED_ORIGINAL_MAIN_POLICY'


def test_busy_main_stops_before_service_control(transaction,monkeypatch):
    packet,review,live,main,events=transaction
    def busy(_):raise RuntimeError('active child')
    monkeypatch.setattr(release.svc,'require_idle_main',busy)
    with pytest.raises(RuntimeError,match='active child'):release.cutover(packet,review)
    assert not any(e[0]=='service' for e in events)
    assert live.read_bytes()==b'original'


def test_wrong_review_does_not_control_any_service(transaction):
    packet,review,live,main,events=transaction
    review.write_text(json.dumps(dict(verdict='PASS',packet_sha256='wrong')))
    with pytest.raises(ValueError,match='INDEPENDENT_REVIEW'):release.cutover(packet,review)
    assert events==[] and live.read_bytes()==b'original'


def test_failed_install_recovers_main_only_original_policy(transaction,monkeypatch):
    packet,review,live,main,events=transaction
    def fail_wait(_):raise RuntimeError('new main failed')
    monkeypatch.setattr(release.svc,'wait_running',fail_wait)
    def restore(services,backup,stopped):
        assert set(services)=={'main'} and stopped==['main']
        live.write_bytes((backup/'main.plist').read_bytes())
        events.append(('restore','main'))
        return dict(status='RESTORED_EXACT_PREVIOUS_TUPLE')
    monkeypatch.setattr(release.svc,'restore_services',restore)
    with pytest.raises(RuntimeError,match='new main failed'):release.cutover(packet,review)
    assert live.read_bytes()==b'original' and ('restore','main') in events


def test_remaining_chain_worst_case_and_genuine_space_limits(tmp_path):
    policy=release.budget_policy(base_policy(tmp_path))
    sample=dict(category_baseline_bytes=176_179_710_037,logical_other_remaining_bytes=34_713_824_729,
        other_remaining_bytes=34_713_812_416,free_bytes=294_229_622_784,total_bytes=1_995_165_736_960)
    rows=release.remaining_chain_projection(policy,sample)
    assert [r['category_worst_bytes'] for r in rows]==[245_253_273_134,279_613_011_502]
    assert all(r['category_pass'] and r['ratio_pass'] and r['reserve_pass'] for r in rows)
    bad=dict(sample,free_bytes=250_000_000_000)
    with pytest.raises(ValueError,match='REMAINING_CHAIN_CAPACITY_REJECTED'):
        release.remaining_chain_projection(policy,bad)
    bad=dict(sample,category_baseline_bytes=176_179_710_037+633_604_563)
    with pytest.raises(ValueError,match='REMAINING_CHAIN_CAPACITY_REJECTED'):
        release.remaining_chain_projection(policy,bad)
