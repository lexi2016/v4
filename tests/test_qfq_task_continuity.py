"""Synthetic shared-pool recovery only; no live registry or QFQ producer."""
import copy
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import research_storage_governance as g
from ops import research_qfq_task_continuity as continuity
from ops.research_storage_retention import owner_lock

TARGET = 20261120


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    g.atomic_json(path, value)
    return {'path':str(path), 'sha256':g.digest(path)}


@pytest.fixture
def fixture(tmp_path):
    roots = [tmp_path / name for name in ('old-app', 'new-app')]
    for root in roots:
        ops = root / 'ops'
        (ops / 'vendor').mkdir(parents=True)
        (ops / 'research_panel_qfq.py').write_text('same owner bytes\n')
        (ops / 'vendor/data_layer_daily_formula_increment_update_v1.py').write_text('same driver bytes\n')
    data = tmp_path / 'data'; data.mkdir()
    runs = tmp_path / 'runs'; runs.mkdir()
    formula = tmp_path / 'formula.py'; formula.write_text('original formula')
    contract = tmp_path / 'contract.csv'; contract.write_text('original contract')
    snapshot_path = data / 'snapshot.json'
    put(snapshot_path, {'asof_date':TARGET, 'input':'frozen-input'})
    module = SimpleNamespace(__file__=str(roots[1] / 'ops/research_panel_qfq.py'), input_path=lambda _:snapshot_path)
    kwargs = dict(driver_path=roots[1] / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py',
        formula_path=formula, contract_csv=contract, tdx_root=data,
        refresh_inputs=True, storage_layout='arrow_blocks_v1')
    policy = dict(data_root=str(data), run_root=str(runs), governance=dict(enabled=True,
        pool_id='test-pool', pool_identity_verified=True, registry_root=str(tmp_path / 'registry')))
    registry = g.Registry(g.configuration(policy), data)
    old_kwargs = dict(kwargs, driver_path=roots[0] / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py')
    old_module = SimpleNamespace(__file__=str(roots[0] / 'ops/research_panel_qfq.py'),input_path=module.input_path)
    legacy = g.qfq_invocation_key(old_module, data, TARGET, old_kwargs, legacy=True)
    key = g.qfq_invocation_key(module, data, TARGET, kwargs)
    checkpoint = runs / ('qfq_' + 'a' * 20) / 'checkpoint.json'
    checkpoint_ref = put(checkpoint, {'stock':'000001.SZ', 'source_sha256':'b' * 64})
    receipt = dict(status='CANDIDATE_READY', target_date=TARGET, generation_id='a' * 64,
        run_dir=str(checkpoint.parent), snapshot_file_sha256=g.digest(snapshot_path),
        input_sha256=g.canonical(json.loads(snapshot_path.read_bytes())),
        adapter_sha256=g.digest(Path(module.__file__)), driver_sha256=g.digest(kwargs['driver_path']),
        formula_sha256=g.digest(formula), field_contract_sha256=g.digest(contract))
    receipt_ref = put(checkpoint.parent / 'candidate_receipt.json', receipt)
    row = dict(state='FAILED_RECOVERABLE', owner=dict(pid=999999999, started='dead fixture'),
        token='original-token', directory=str(runs), attempts=1, reserved_bytes=1024 * 1024,
        written_bytes=100, logical_written_bytes=110, category='ordinary', heartbeat=0,
        billing_paths=[str(checkpoint.parent)], initial_children={}, error='original failure',
        space={'original':'space sample'}, arbitrary_preserved={'nested':[1,2]})
    state = registry.read(); state['tasks'][legacy] = row
    with registry.writer(), registry.transaction():
        registry.save(state)
    linkage = put(data / 'reviewed-linkage.json', dict(schema='v4.qfq_task_artifact_linkage.v1',
        status='REVIEWED_SAME_TASK', evidence_closed=True, reviewer='synthetic test reviewer',
        row_sha256=g.canonical(registry.read()['tasks'][legacy]), old_key=legacy, target=TARGET,
        registry_root=str(registry.root), data_root=str(data), directory=str(runs),
        snapshot={'path':str(snapshot_path),'sha256':g.digest(snapshot_path)}, owner_receipt=receipt_ref))
    plan = continuity.prepare_qfq_migration(module, policy, data_root=data, return_root=runs,
        target=TARGET, kwargs=kwargs, old_root=roots[0], expected_registry_sha256=g.digest(registry.path),
        expected_token='original-token', owner_receipt=receipt_ref, evidence_refs=[checkpoint_ref], linkage_review=linkage)
    return SimpleNamespace(module=module, data=data, runs=runs, roots=roots, kwargs=kwargs,
        policy=policy, registry=registry, key=key, legacy=legacy, plan=plan, snapshot=snapshot_path,
        checkpoint=checkpoint)


def move(f, **kwargs):
    return continuity.migrate_qfq_task(f.module, f.policy, f.plan, data_root=f.data,
        return_root=f.runs, target=TARGET, kwargs=f.kwargs, **kwargs)


def configure_bridge(f):
    ref = put(f.data / 'migration-plan.json', f.plan)
    f.policy['governance']['qfq_legacy_resume'] = ref


def required(f):
    return continuity.require_migrated_resume(f.module, f.policy, f.data, f.runs,
        TARGET, f.kwargs, f.key)


def test_normal_key_is_root_stable_and_legacy_key_remains_reproducible(fixture):
    f = fixture
    module = SimpleNamespace(__file__=str(f.roots[0] / 'ops/research_panel_qfq.py'),input_path=f.module.input_path)
    args = dict(f.kwargs, driver_path=f.roots[0] / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py')
    assert g.qfq_invocation_key(module, f.data, TARGET, args) == f.key
    assert g.qfq_invocation_key(module, f.data, TARGET, args, legacy=True) == f.legacy
    assert g.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs, legacy=True) != f.legacy
    assert f.key != f.legacy


@pytest.mark.parametrize('changed', ['owner', 'driver', 'formula', 'contract', 'target', 'parameters', 'external-driver-path'])
def test_real_calculation_identity_changes_are_distinct(fixture, changed):
    f = fixture; target = TARGET; args = dict(f.kwargs)
    paths = dict(owner=Path(f.module.__file__), driver=args['driver_path'], formula=args['formula_path'],contract=args['contract_csv'])
    if changed in paths:
        paths[changed].write_bytes(paths[changed].read_bytes() + b' real source change')
    elif changed == 'target':
        target += 1
    elif changed == 'parameters':
        args['storage_layout'] = 'different-layout'
    else:
        external = f.data / 'external-driver.py'; external.write_bytes(args['driver_path'].read_bytes())
        args['driver_path'] = external
    assert g.qfq_invocation_key(f.module, f.data, target, args) != f.key
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError):
        continuity.migrate_qfq_task(f.module, f.policy, f.plan, data_root=f.data,
            return_root=f.runs, target=target, kwargs=args)
    assert f.registry.path.read_bytes() == before


def test_refresh_operation_and_frozen_legacy_input_have_different_contracts(fixture):
    f = fixture
    explicit = dict(f.kwargs, refresh_inputs=False)
    prior_explicit = g.qfq_invocation_key(f.module, f.data, TARGET, explicit)
    put(f.snapshot, {'asof_date':TARGET, 'input':'revised-real-input'})
    assert g.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs) == f.key
    assert g.qfq_invocation_key(f.module, f.data, TARGET, explicit) != prior_explicit
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError, match='SNAPSHOT_DRIFT'):
        move(f)
    assert f.registry.path.read_bytes() == before


def test_rekey_preserves_every_old_row_field_and_one_reservation(fixture):
    f = fixture; original = copy.deepcopy(f.registry.read()['tasks'][f.legacy])
    result = move(f)
    assert result['status'] == 'COMMITTED'
    tasks = f.registry.read()['tasks']
    assert set(tasks) == {f.key} and tasks[f.key] == original
    assert tasks[f.key]['reserved_bytes'] == 1024 * 1024
    assert tasks[f.key]['logical_written_bytes'] == 110
    assert f.checkpoint.read_bytes()
    before = f.registry.path.read_bytes()
    assert move(f)['status'] == 'ALREADY_COMMITTED'
    assert f.registry.path.read_bytes() == before


def test_bridge_blocks_normal_owner_until_explicit_atomic_migration(fixture):
    f = fixture; configure_bridge(f)
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError, match='MIGRATION_REQUIRED'):
        required(f)
    assert f.registry.path.read_bytes() == before
    move(f)
    assert required(f) == f.plan
    put(f.snapshot, {'asof_date':TARGET, 'input':'changed after approval'})
    with pytest.raises(g.RetentionError, match='SNAPSHOT_DRIFT'):
        required(f)


@pytest.mark.parametrize('changed', ['registry', 'token', 'row', 'directory', 'new-key'])
def test_cas_or_directory_conflict_leaves_current_registry_bytes(fixture, changed):
    f = fixture
    if changed == 'registry':
        f.plan['expected_registry_sha256'] = 'f' * 64
    elif changed == 'token':
        f.plan['token'] = 'wrong token'
    elif changed == 'directory':
        f.runs = f.data
    else:
        state = f.registry.read()
        if changed == 'row':state['tasks'][f.legacy]['heartbeat'] = 10
        else:state['tasks'][f.key] = copy.deepcopy(state['tasks'][f.legacy])
        f.registry.save(state)
        f.plan['expected_registry_sha256'] = g.digest(f.registry.path)
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError):move(f)
    assert f.registry.path.read_bytes() == before


@pytest.mark.parametrize('status', ['LIVE', 'UNKNOWN'])
def test_live_or_unknown_recorded_owner_is_never_taken_over(fixture, monkeypatch, status):
    f = fixture; monkeypatch.setattr(g, 'owner_state', lambda _:status)
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError, match='OWNER_LIVE_OR_UNKNOWN'):move(f)
    assert f.registry.path.read_bytes() == before


@pytest.mark.parametrize('publication', [False, True])
def test_original_owner_lock_blocks_even_when_recorded_pid_is_dead(fixture, publication):
    f = fixture; before = f.registry.path.read_bytes()
    with owner_lock(f.policy, publication=publication):
        with pytest.raises(g.RetentionError, match='OWNER_ALREADY_ACTIVE'):move(f)
    assert f.registry.path.read_bytes() == before


@pytest.mark.parametrize('failure', ['before-save', 'before-replace', 'after-replace'])
def test_atomic_migration_faults_recover_without_two_rows(fixture, monkeypatch, failure):
    f = fixture; original = f.registry.path.read_bytes()
    save = g.Registry.save; replace = g.os.replace
    if failure == 'before-save':
        def failing(*args, **kwargs):raise OSError('before save')
        monkeypatch.setattr(g.Registry, 'save', failing)
    else:
        def failing(source, destination):
            if failure == 'after-replace':replace(source, destination)
            raise OSError('replace fault')
        monkeypatch.setattr(g.os, 'replace', failing)
    with pytest.raises(OSError):move(f)
    monkeypatch.setattr(g.Registry, 'save', save);monkeypatch.setattr(g.os, 'replace', replace)
    if failure == 'after-replace':
        assert set(f.registry.read()['tasks']) == {f.key}
        assert move(f)['status'] == 'ALREADY_COMMITTED'
    else:
        assert f.registry.path.read_bytes() == original
        assert move(f)['status'] == 'COMMITTED'
    assert len(f.registry.read()['tasks']) == 1


def test_rollback_restores_exact_old_row_and_rejects_changes(fixture):
    f = fixture; row = copy.deepcopy(f.registry.read()['tasks'][f.legacy])
    move(f); before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError, match='REGISTRY_DRIFT'):
        move(f, rollback=True, expected_registry_sha256='bad')
    assert f.registry.path.read_bytes() == before
    assert move(f, rollback=True, expected_registry_sha256=g.digest(f.registry.path))['status'] == 'ROLLED_BACK'
    assert f.registry.read()['tasks'] == {f.legacy:row}
    assert move(f, rollback=True)['status'] == 'ALREADY_ROLLED_BACK'


def test_rollback_rejects_a_claim_that_has_already_resumed(fixture):
    f = fixture;move(f)
    state = f.registry.read();state['tasks'][f.key]['attempts'] += 1;f.registry.save(state)
    before = f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError, match='TASK_DRIFT'):
        move(f, rollback=True, expected_registry_sha256=g.digest(f.registry.path))
    assert f.registry.path.read_bytes() == before


def test_repeated_failure_reuses_original_peak_and_cumulative_accounting(fixture):
    f = fixture;move(f);configure_bridge(f)
    plan = required(f)
    for attempt in (2,3):
        with g.admission(f.policy, key=f.key, directory=f.runs, predicted=1024,
                         reuse_ready=False, preserve_existing=True, required_migration=g.canonical(plan)) as (claim,_):
            claim.checkpoint()
            row = f.registry.read()['tasks'][f.key]
            assert row['attempts'] == attempt and row['reserved_bytes'] == 1024 * 1024
            assert row['written_bytes'] == 100 and row['logical_written_bytes'] == 110
            assert row['space']['other_remaining_bytes'] == 0
            claim.finish(error=g.RetentionError('continued same failure'))
        assert len(f.registry.read()['tasks']) == 1
    row = f.registry.read()['tasks'][f.key]
    assert row['state'] == 'FAILED_RECOVERABLE' and row['reserved_bytes'] == 1024 * 1024


def test_success_uses_normal_artifact_manifest_and_terminal_accounting(fixture):
    f = fixture;move(f);configure_bridge(f);plan = required(f)
    with g.admission(f.policy, key=f.key, directory=f.runs, predicted=1024,
                     reuse_ready=False, preserve_existing=True, required_migration=g.canonical(plan)) as (claim,_):
        product = f.runs / 'verified-result.json';product.write_bytes(b'fixture result')
        claim.finish({'status':'READY'}, [product])
    row = f.registry.read()['tasks'][f.key]
    assert row['state'] == 'READY' and row['reserved_bytes'] == row['written_bytes'] == 0
    g.validate_artifacts(row['artifacts'])
    assert row['logical_written_bytes'] == 110 and len(f.registry.read()['tasks']) == 1


def claim_process(policy, key, directory, migration, ready, release, result):
    try:
        with g.admission(policy, key=key, directory=Path(directory), predicted=1024,
                         reuse_ready=False, preserve_existing=True, required_migration=migration) as (claim,_):
            ready.set();release.wait(10)
            claim.finish(error=g.RetentionError('child completed fixture'))
        result.put('ONE_OWNER')
    except g.RetentionError as error:
        result.put(str(error))


def test_two_processes_claim_one_shared_reservation(fixture):
    f = fixture;move(f)
    ctx = multiprocessing.get_context('spawn');ready = ctx.Event();release = ctx.Event();result = ctx.Queue()
    args=(f.policy,f.key,str(f.runs),g.canonical(f.plan),ready,release,result)
    first=ctx.Process(target=claim_process,args=args);second=ctx.Process(target=claim_process,args=args)
    try:
        first.start();assert ready.wait(10)
        second.start();second.join(10);assert not second.is_alive()
        blocked=result.get(timeout=3);assert blocked=='POOL_WRITER_BUSY_BOUNDED_WAIT'
        release.set();first.join(10);assert not first.is_alive()
        assert result.get(timeout=3)=='ONE_OWNER'
    finally:
        release.set()
        for process in (first,second):
            if process.is_alive():process.terminate();process.join(3)
    row=f.registry.read()['tasks'][f.key]
    assert row['attempts']==2 and row['reserved_bytes']==1024*1024
    assert len(f.registry.read()['tasks'])==1


def test_snapshot_refresh_guard_rejects_before_replacing_bound_input(fixture):
    f=fixture
    claim=SimpleNamespace(qfq_resume_snapshot={'path':str(f.snapshot),'sha256':g.digest(f.snapshot)})
    original=f.snapshot.read_bytes()
    g._guard_qfq_resume_snapshot(claim,f.snapshot,original)
    g._guard_qfq_resume_snapshot(claim,f.snapshot,json.loads(original),json_value=True)
    for proposed in (b'revised',dict(asof_date=TARGET,input='changed')):
        with pytest.raises(g.RetentionError,match='QFQ_RESUME_SNAPSHOT_CHANGED'):
            g._guard_qfq_resume_snapshot(claim,f.snapshot,proposed,json_value=isinstance(proposed,dict))
    assert f.snapshot.read_bytes()==original


def test_roll_back_between_read_validation_and_claim_cannot_create_a_second_row(fixture):
    f=fixture;move(f);configure_bridge(f);plan=required(f)
    move(f,rollback=True,expected_registry_sha256=g.digest(f.registry.path))
    before=f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError,match='MIGRATION_REQUIRED'):
        with g.admission(f.policy,key=f.key,directory=f.runs,predicted=1024,
                         preserve_existing=True,required_migration=g.canonical(plan)):
            pytest.fail('claim must not start')
    assert f.registry.path.read_bytes()==before


def test_same_root_legacy_task_blocks_unconfigured_canonical_admission(fixture):
    f=fixture
    old_module=SimpleNamespace(__file__=str(f.roots[0]/'ops/research_panel_qfq.py'),input_path=f.module.input_path)
    args=dict(f.kwargs,driver_path=f.roots[0]/'ops/vendor/data_layer_daily_formula_increment_update_v1.py')
    before=f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError,match='QFQ_LEGACY_RESUME_CONTROL_REQUIRED'):
        continuity.require_migrated_resume(old_module,f.policy,f.data,f.runs,TARGET,args,f.key)
    assert f.registry.path.read_bytes()==before


@pytest.mark.parametrize('field', ['snapshot_file_sha256','input_sha256','target_date','adapter_sha256',
                                   'driver_sha256','formula_sha256','field_contract_sha256','generation_id','run_dir'])
def test_hand_built_plan_cannot_substitute_nonmatching_owner_evidence(fixture,field):
    f=fixture
    ref=f.plan['owner_receipt'];receipt=json.loads(Path(ref['path']).read_bytes())
    receipt[field]=0 if field=='target_date' else 'different'
    f.plan['owner_receipt']=put(Path(ref['path']),receipt)
    before=f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError):move(f)
    assert f.registry.path.read_bytes()==before


def test_actual_governed_owner_does_not_start_an_unresolved_bridge(fixture,monkeypatch):
    from ops import research_panel_qfq as q
    f=fixture;configure_bridge(f)
    monkeypatch.setattr(q,'__file__',f.module.__file__)
    monkeypatch.setattr(q,'input_path',f.module.input_path)
    before=f.registry.path.read_bytes();calls=[]
    def producer(**kwargs):calls.append('producer');raise AssertionError('must not run')
    with pytest.raises(g.RetentionError,match='MIGRATION_REQUIRED'):
        g.governed_qfq(producer,f.policy,{'predicted_bytes':1024},data_root=f.data,
                      return_root=f.runs,pointers={},target=TARGET,**f.kwargs)
    assert calls==[] and f.registry.path.read_bytes()==before


def test_actual_governed_write_and_load_boundaries_reject_changed_snapshot(fixture,monkeypatch):
    from ops import research_panel_qfq as q
    f=fixture;move(f);configure_bridge(f)
    monkeypatch.setattr(q,'__file__',f.module.__file__)
    monkeypatch.setattr(q,'input_path',f.module.input_path)
    monkeypatch.setattr(q,'load_snapshot',lambda path,*args: json.loads(Path(path).read_bytes()))
    original=f.snapshot.read_bytes();calls=[]
    def producer(**kwargs):
        calls.append('producer')
        assert q.load_snapshot(f.snapshot,TARGET)['input']=='frozen-input'
        q._json(f.snapshot,json.loads(original))
        assert f.snapshot.read_bytes()==original
        with pytest.raises(g.RetentionError,match='QFQ_RESUME_SNAPSHOT_CHANGED'):
            q._json(f.snapshot,{'asof_date':TARGET,'input':'changed by refresh'})
        return {'status':'FAILED'}
    result=g.governed_qfq(producer,f.policy,{'predicted_bytes':1024},data_root=f.data,
                         return_root=f.runs,pointers={},target=TARGET,**f.kwargs)
    assert result['status']=='FAILED' and calls==['producer']
    assert f.snapshot.read_bytes()==original
    row=f.registry.read()['tasks'][f.key]
    assert row['state']=='FAILED_RECOVERABLE' and row['reserved_bytes']==1024*1024
    assert row['written_bytes']==100 and row['logical_written_bytes']==110


def test_input_alias_snapshot_write_seam_guards_original_qfq_json_writer(fixture,monkeypatch):
    from ops import research_panel_adjustment_inputs as inputs
    f=fixture;move(f)
    original=f.snapshot.read_bytes()
    with g.admission(f.policy,key=f.key,directory=f.runs,predicted=1024,preserve_existing=True) as (claim,_):
        claim.qfq_resume_snapshot={'path':str(f.snapshot),'sha256':g.digest(f.snapshot)}
        with g.input_write_seams(claim):
            with pytest.raises(g.RetentionError,match='QFQ_RESUME_SNAPSHOT_CHANGED'):
                inputs._json(f.snapshot,{'asof_date':TARGET,'input':'changed during prepare_snapshot'})
        assert f.snapshot.read_bytes()==original
        claim.finish(error=g.RetentionError('fixture finishes'))


def test_native_snapshot_publisher_alias_is_guarded_before_call(fixture,monkeypatch):
    from ops import research_panel_adjustment_inputs as inputs
    f=fixture;move(f);calls=[]
    original=f.snapshot.read_bytes()
    def native_publisher(path,snapshot):
        calls.append('native-atomic-publisher')
        return {'fixture':'already published'}
    monkeypatch.setattr(inputs,'publish_adjustment_snapshot',native_publisher,raising=False)
    with g.admission(f.policy,key=f.key,directory=f.runs,predicted=1024,preserve_existing=True) as (claim,_):
        claim.qfq_resume_snapshot={'path':str(f.snapshot),'sha256':g.digest(f.snapshot)}
        with g.input_write_seams(claim):
            with pytest.raises(g.RetentionError,match='QFQ_RESUME_SNAPSHOT_CHANGED'):
                inputs.publish_adjustment_snapshot(f.snapshot,{'asof_date':TARGET,'input':'changed during native refresh'})
            assert calls==[] and f.snapshot.read_bytes()==original
            inputs.publish_adjustment_snapshot(f.snapshot,json.loads(original))
            assert calls==['native-atomic-publisher']
        claim.finish(error=g.RetentionError('fixture done'))


def test_legacy_row_created_after_preflight_is_blocked_in_claim_transaction(fixture):
    f=fixture
    before=f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError,match='QFQ_LEGACY_RESUME_CONTROL_REQUIRED'):
        with g.admission(f.policy,key=f.key,directory=f.runs,predicted=1024,
                         preserve_existing=True,forbidden_legacy_key=f.legacy):
            pytest.fail('legacy race must fail before a new claim')
    assert f.registry.path.read_bytes()==before


@pytest.mark.parametrize('field', ['old_key','row_sha256','snapshot','owner_receipt','registry_root',
                                   'data_root','directory','target','evidence_closed','reviewer','status'])
def test_reviewed_linkage_drift_never_authorizes_registry_mutation(fixture,field):
    f=fixture;ref=f.plan['linkage_review'];proof=json.loads(Path(ref['path']).read_bytes())
    proof[field] = False if field == 'evidence_closed' else (' ' if field == 'reviewer' else 'unproven')
    f.plan['linkage_review']=put(Path(ref['path']),proof)
    before=f.registry.path.read_bytes()
    with pytest.raises(g.RetentionError,match='TASK_ARTIFACT_LINKAGE_UNPROVEN'):
        move(f)
    assert f.registry.path.read_bytes()==before


def test_policy_budget_or_owner_root_drift_rejects_migration(fixture):
    f=fixture;before=f.registry.path.read_bytes()
    f.policy['governance']['ordinary_peak_budget_bytes']=200*g.GIB
    with pytest.raises(g.RetentionError,match='SCOPE_DRIFT'):move(f)
    assert f.registry.path.read_bytes()==before
    f.policy['data_root']=str(f.runs)
    with pytest.raises(g.RetentionError,match='POLICY_OWNER_ROOT_DRIFT'):move(f)
    assert f.registry.path.read_bytes()==before
