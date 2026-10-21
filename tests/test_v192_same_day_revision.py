"""Registered, synthetic-only acceptance against the pinned release libraries.

No live data root is opened. The session guard precedes fixture generation.
The controller supplies a separate RUN_STARTED context for each execution.
"""
import copy
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'ops/runtime_payloads/v192_same_day_revision_v1.py'
spec = importlib.util.spec_from_file_location('same_day_revision_test_payload', PAYLOAD)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture(scope='session', autouse=True)
def registered_scope():
    context = json.loads(Path(os.environ['NEXT_V192_PUBLISH_ADAPTER_TEST_CONTEXT']).read_text())
    contract_path = Path(context['contract_path'])
    contract = json.loads(contract_path.read_text())
    assert contract['payload_sha256'] == m.file_sha(PAYLOAD)
    assert contract['test_sha256'] == m.file_sha(Path(__file__))
    assert contract['scope'] == 'SYNTHETIC_SAME_DAY_REVISION_ONLY'
    events = []
    with Path(context['registry_path']).open() as stream:
        for line in stream:
            if line.strip():
                event = json.loads(line)
                if event['execution_id'] == context['execution_id']:
                    events.append(event)
    assert events and events[-1]['event_type'] == 'RUN_STARTED'
    assert events[-1]['contract_sha256'] == m.file_sha(contract_path)


@pytest.fixture(scope='session')
def runtime(registered_scope):
    return m.Runtime()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m.canonical(value))
    return {'path': str(path), 'sha256': m.file_sha(path)}


def row(selector, code='000661.SZ', rank=1, score=91.5):
    return dict(ts_code=code, stock_code=code[:6], stock_name='synthetic',
                candidate_role='TEST_ONLY_BUY_CANDIDATE', multi_head_final_role='B2_FRESH_ENTRY',
                entry_pool=True, review_rank_v19=rank, final_score=score, fresh_b2_entry_score=80,
                continuation_entry_score=0, risk_chase_score=12,
                rank_usage_boundary=selector.V192_RANK_BOUNDARY, formal_recommendation_allowed=False,
                primary_buy_signal=1, secondary_buy_signal=0, gold_brick_context='none',
                brick_resonance_context=0, brick_buy=0, brick_buy1_low_absorb=0, brick_buy2_attack=0,
                brick_resonance1=0, brick_resonance2=0, brick_resonance=0, ref_hold_score=4,
                B1=0, B2=1, B3=0, BG=1, amount=1_500_000_000, pct_chg=1.5,
                route_context='fixture', brick_context='fixture',
                formula_source=selector.CANONICAL_FORMULA_SOURCE,
                field_contract_version='formula_signal_v2_reference_score')


def build_generation(root):
    import pyarrow as pa
    import pyarrow.parquet as pq
    root.mkdir()
    keys = [f'{n:06d}.SZ' for n in range(1, 26)]
    table = pa.table({'trade_date': [m.SIGNAL] * len(keys), 'ts_code': keys})
    details = {}
    for role in ('selector', 'backtest', 'selector_source', 'selector_sidecar'):
        path = root / (role + '.parquet')
        pq.write_table(table, path)
        details[role] = dict(path=path.name, bytes=path.stat().st_size, sha256=m.file_sha(path))
    source_sha = m.digest({'source': 'synthetic-original-producer'})
    manifest = {'target_date': m.SIGNAL, 'source_sha256': source_sha, 'manifest_sha256': 'b' * 64}
    manifest_path = root / 'input_manifest.json'
    write(manifest_path, manifest)
    source_receipt = write(root / 'sync_receipt.json', dict(status='READY', target_date=m.SIGNAL,
        production_allowed=False, buy_gate_updated=False, orders_sent=False))
    generation_id = m.digest({k: details[k] for k in ('selector', 'backtest')})
    pointer = dict(schema='v4.a_formula.generation_pointer.v1', status='READY', generation_id=generation_id,
        target_date=m.SIGNAL, run_id='synthetic-generation', **details,
        source=dict(name='synthetic-original-producer', sha256=source_sha,
                    sync_receipt_path=source_receipt['path'], sync_receipt_sha256=source_receipt['sha256']),
        input_manifest=dict(path=manifest_path.name, bytes=manifest_path.stat().st_size,
                            sha256=m.file_sha(manifest_path), manifest_sha256='b' * 64))
    evidence = write(root / 'CURRENT_FORMULA_GENERATION.json', pointer)
    universe = dict(signal_date=m.SIGNAL, key_count=len(keys), key_sha256=m.digest(sorted(keys)))
    universe['producer_evidence'] = write(root / 'producer_universe.json', {'original_summary': dict(universe)})
    universe['producer_fields'] = {k: ['original_summary', k] for k in ('signal_date', 'key_count', 'key_sha256')}
    universe['scope'] = 'WHOLE_POOL'
    return dict(pointer=evidence['path'], pointer_sha256=evidence['sha256'], generation_id=generation_id), universe


@pytest.fixture
def case(tmp_path, runtime):
    # Code is imported from the actual pinned release; all artifacts are fixtures.
    tmp_path = tmp_path.resolve()
    s = runtime.selector
    generation, universe = build_generation(tmp_path / 'generation')
    panel = Path(generation['pointer']).parent / 'selector.parquet'
    old_panel = tmp_path / 'old_panel.bin'
    old_panel.write_bytes(b'previous-synthetic-panel')
    shared_root, candidate_root, local_root = (tmp_path / name for name in ('shared', 'candidate', 'local'))
    s.publish_v192_rows(shared_root, panel_path=old_panel, signal_date=m.SIGNAL, target_date=m.TARGET,
                       rows=[row(s, score=80)], oracle_sha256s=s.FROZEN_ORACLE_SHA256S)
    s.publish_v192_rows(candidate_root, panel_path=panel, signal_date=m.SIGNAL, target_date=m.TARGET,
                       rows=[row(s), row(s, '600000.SH', 2), row(s, '300001.SZ', 3)],
                       oracle_sha256s=s.FROZEN_ORACLE_SHA256S)
    local = runtime.local_module.PreselectionPoolStore(local_root)
    previous = runtime.materializer.build_shared_v192_premarket_pool(shared_root,
        trade_date=m.TARGET, signal_date=m.SIGNAL, shared_package_root=m.SHARED_PACKAGE_ROOT)
    local.materialize(previous)
    snapshot = local.read_pool_snapshot(m.TARGET, m.POOL)
    control = tmp_path / 'gate_control'
    control.mkdir()
    permit_source = tmp_path / 'permit_source'
    permit_source.mkdir()
    keys = [dict(business_key='synthetic-A-only', trade_date=m.TARGET, pool_id=m.POOL)]
    permit = dict(schema_version='v4.preselection.exact_scope.v1', decision_id='synthetic-decision',
                  owner_id='synthetic-owner', source_release_sha256='d' * 64, target_release_sha256='c' * 64,
                  source_root=str(permit_source), target_root=str(local_root), keys=keys,
                  business_key_set_sha256=m.digest(keys))
    permit_evidence = write(control / 'permit.json', permit)
    write(control / 'gate.json', dict(schema_version='v4.preselection.gate.v1',
          permit_sha256=permit_evidence['sha256'], revision=1, state='OPEN'))
    gate_binding = dict(control_dir=str(control), expected_permit_sha256=permit_evidence['sha256'],
                        expected_owner_id='synthetic-owner', expected_release_sha256='c' * 64,
                        expected_root=str(local_root))
    context = runtime.local_module.StoreGateContext(**dict(gate_binding, control_dir=control, expected_root=local_root))
    local = runtime.local_module.PreselectionPoolStore(local_root, write_gate_context=context,
                                                      require_write_gate_context=True)
    shared = s._V192ManifestStore(shared_root, role=m.ROLE)
    candidate = s._V192ManifestStore(candidate_root, role=m.ROLE)
    binding = dict(schema='v192.same_day_revision.binding.v1', revision_mode='SAME_DAY_WHOLE_POOL_REVISION',
        operation_id='fixture-revision', signal_date=m.SIGNAL, target_date=m.TARGET,
        dependencies=m.DEPENDENCIES, safety=m.FLAGS, local_root=str(local_root), shared_root=str(shared_root),
        write_gate=dict(require_write_gate_context=True, context=gate_binding),
        expected_previous_shared=m.identity(shared.verify_latest(m.TARGET, m.ROLE)['verified']),
        expected_previous_local={k: snapshot[k] for k in ('artifact_sha256', 'receipt_raw_sha256',
                                                        'artifact_relative', 'receipt_relative')},
        candidate=dict(store_root=str(candidate_root), identity=m.identity(candidate.verify_latest(m.TARGET, m.ROLE)['verified'])),
        generation=generation, universe=universe,
        source_panel=dict(path=str(panel), sha256=m.file_sha(panel), generation_role='selector'))
    proof = dict(schema='v192.whole_pool_independent_pass.v1', scope='WHOLE_POOL', decision='PASS',
                 independent=True, partial=False, writer='synthetic-writer', reviewer='synthetic-reviewer',
                 binding={k: copy.deepcopy(binding[k]) for k in ('candidate', 'generation', 'source_panel',
                         'universe', 'dependencies', 'signal_date', 'target_date', 'safety')})
    binding['independent_pass'] = write(tmp_path / 'whole_pool_independent_pass.json', proof)
    return dict(binding=binding, runtime=runtime, local=local, shared=shared, root=tmp_path,
                old_run_bytes={str(p.relative_to(shared_root)): p.read_bytes()
                               for p in (shared_root / 'runs').rglob('*') if p.is_file()})


def adapter(case):
    return m.SameDayRevision(case['binding'], local_store=case['local'], runtime=case['runtime'])


def tree_bytes(case):
    return {str(p.relative_to(case['root'])): p.read_bytes()
            for root in (case['local'].root, case['shared'].root) for p in root.rglob('*') if p.is_file()}


def assert_old_run_unchanged(case):
    for relative, raw in case['old_run_bytes'].items():
        assert (case['shared'].root / relative).read_bytes() == raw


def hk_payload():
    return dict(schema_version='v3_5.preselection_pool.v1', trade_date=m.TARGET,
        pool_id='hkconnect_d1_top100', display_name='fixture-HK', market='HK', status='READY',
        producer_id='fixture-only', source_role='RAW_SOURCE', source_path='fixture.csv',
        source_sha256='a' * 64, rows=[{'symbol': 'HK.00001'}], cannot_confirm=[],
        production_allowed=False, buy_gate_updated=False, orders_sent=False)


def replace_local(case, payload):
    local = case['local']
    pool_id = payload['pool_id']
    ap, rp = local._relative(m.TARGET, pool_id)
    manifest_path = f'preselection_pools/{m.TARGET}/manifest.json'
    manifest = local._read(manifest_path)
    manifest[pool_id] = m.digest(payload)
    local._write(ap, payload)
    local._write(rp, local._receipt(trade_date=m.TARGET, pool_id=pool_id,
                 artifact_path=ap, artifact_sha256=m.digest(payload), payload=payload))
    local._write(manifest_path, manifest)


def test_normal_exact_projection_idempotence_and_old_run_bytes(case):
    result = adapter(case).apply()
    expected = case['runtime'].materializer.build_shared_v192_premarket_pool(case['shared'].root,
        trade_date=m.TARGET, signal_date=m.SIGNAL, shared_package_root=m.SHARED_PACKAGE_ROOT)
    assert case['local'].read_pool(m.TARGET, m.POOL) == expected
    assert result['phase'] == 'LOCAL_COMMITTED'
    before = tree_bytes(case)
    assert adapter(case).apply()['new_shared'] == result['new_shared']
    assert tree_bytes(case) == before
    assert result['new_shared']['artifact_sha256'] == case['binding']['candidate']['identity']['artifact_sha256']
    # A new real receipt/manifest is generated, rather than copied from candidate.
    assert result['new_shared']['receipt_sha256'] != case['binding']['candidate']['identity']['receipt_sha256']
    assert_old_run_unchanged(case)


def test_shared_commit_then_local_exception_resumes(case, monkeypatch):
    op = adapter(case)
    with monkeypatch.context() as patch:
        patch.setattr(case['local'], '_commit_main_snapshot', lambda *a, **k: (_ for _ in ()).throw(OSError('fixture-local-error')))
        with pytest.raises(OSError, match='fixture-local-error'):
            op.apply()
    assert case['shared'].verify_latest(m.TARGET, m.ROLE)['verified']['run_id'] == op.expected_run
    assert case['local'].read_pool_snapshot(m.TARGET, m.POOL)['artifact_sha256'] == case['binding']['expected_previous_local']['artifact_sha256']
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'
    assert_old_run_unchanged(case)


def test_actual_process_exit_after_shared_before_receipt_resumes(case):
    def child():
        op = adapter(case)
        original = op._save
        def exit_before_receipt(state, phase):
            if phase == 'SHARED_COMMITTED':
                os._exit(73)
            return original(state, phase)
        op._save = exit_before_receipt
        op.apply()
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start()
    process.join(20)
    assert not process.is_alive() and process.exitcode == 73
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'
    assert_old_run_unchanged(case)


class HardExit(BaseException):
    pass


@pytest.mark.parametrize('point', ['artifact', 'receipt', 'manifest'])
def test_each_local_trio_write_interruption_resumes(case, monkeypatch, point):
    local = case['local']
    ap, rp = local._relative(m.TARGET, m.POOL)
    target = {'artifact': ap, 'receipt': rp, 'manifest': f'preselection_pools/{m.TARGET}/manifest.json'}[point]
    original = local._write
    def crash_after(relative, value):
        original(relative, value)
        if relative == target:
            raise HardExit()
    with monkeypatch.context() as patch:
        patch.setattr(local, '_write', crash_after)
        with pytest.raises(HardExit):
            adapter(case).apply()
    assert local._path(local._pending_relative(trade_date=m.TARGET, pool_id=m.POOL)).is_file()
    # Force operation receipt lag all the way back to PREPARED.
    op = adapter(case)
    state = local._read(op.record)
    for k in ('new_shared', 'new_local_sha256', 'new_local_receipt_sha256'):
        state.pop(k, None)
    state['phase'] = 'PREPARED'
    local._write(op.record, state)
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'
    assert_old_run_unchanged(case)


def test_receipt_phase_lag_with_both_roots_new(case):
    op = adapter(case)
    op.apply()
    state = case['local']._read(op.record)
    state['phase'] = 'PREPARED'
    for k in ('new_shared', 'new_local_sha256', 'new_local_receipt_sha256'):
        state.pop(k, None)
    case['local']._write(op.record, state)
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'


@pytest.mark.parametrize('where', ['shared', 'local'])
@pytest.mark.parametrize('action', ['apply', 'rollback'])
def test_third_a_revision_is_rejected_without_store_write(case, where, action):
    adapter(case).apply()
    if where == 'shared':
        third = case['root'] / 'third'
        third_panel = case['root'] / 'third_panel'
        third_panel.write_bytes(b'third')
        s = case['runtime'].selector
        s.publish_v192_rows(third, panel_path=third_panel, signal_date=m.SIGNAL, target_date=m.TARGET,
                           rows=[row(s, score=77)], oracle_sha256s=s.FROZEN_ORACLE_SHA256S)
        # Fixture copies the independently valid third run into the current slot.
        import shutil
        shutil.copytree(third / 'runs', case['shared'].root / 'runs', dirs_exist_ok=True)
        (case['shared'].root / 'latest.json').write_bytes((third / 'latest.json').read_bytes())
    else:
        payload = case['local'].read_pool(m.TARGET, m.POOL)
        payload['display_name'] = 'third-A-revision'
        replace_local(case, payload)
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_.*A_CAS'):
        getattr(adapter(case), action)()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('what', ['generation', 'candidate', 'pass', 'panel', 'producer_universe', 'dependency'])
def test_admission_identity_drift_is_rejected_without_store_write(case, what, monkeypatch):
    b = case['binding']
    if what == 'generation':
        path = Path(b['generation']['pointer'])
    elif what == 'candidate':
        path = Path(b['candidate']['store_root']) / b['candidate']['identity']['artifact_relative']
    elif what == 'pass':
        path = Path(b['independent_pass']['path'])
    elif what == 'panel':
        path = Path(b['source_panel']['path'])
    elif what == 'producer_universe':
        path = Path(b['universe']['producer_evidence']['path'])
    else:
        monkeypatch.setattr(case['runtime'], 'check_dependencies', lambda: m.require(False, 'STOP_DEPENDENCY_DRIFT'))
        path = None
    if path:
        path.write_bytes(path.read_bytes() + b' ')
    before = tree_bytes(case)
    with pytest.raises(Exception):
        adapter(case).apply()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('kind', ['six-ticket-canary', 'partial', 'self-review', 'wrong-universe', 'bare-whole-boolean'])
def test_whole_pool_claim_must_bind_independent_scope_and_original_universe(case, kind):
    evidence = case['binding']['independent_pass']
    proof = json.loads(Path(evidence['path']).read_text())
    if kind == 'six-ticket-canary':
        proof['scope'] = 'CURRENT6_ENGINEERING_CANARY'
    elif kind == 'partial':
        proof['partial'] = True
    elif kind == 'self-review':
        proof['reviewer'] = proof['writer']
    elif kind == 'wrong-universe':
        proof['binding']['universe']['key_count'] = 6
    else:
        proof = dict(whole_pool=True, scope='WHOLE_POOL', decision='PASS')
    case['binding']['independent_pass'] = write(Path(evidence['path']), proof)
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop):
        adapter(case).apply()
    assert tree_bytes(case) == before


def test_normal_other_pool_updates_are_preserved_on_apply_and_rollback(case, monkeypatch):
    local = case['local']
    local.materialize(hk_payload())
    hk_before = local.read_pool_snapshot(m.TARGET, 'hkconnect_d1_top100')
    shared = case['shared']
    latest = shared._load_latest()
    latest['entries']['20261021/HK_FIXTURE_ROLE'] = {'fixture': 'HK-unchanged'}
    shared._write_json(shared.latest_path, latest)
    adapter(case).apply()
    # A normal later HK revision is present before the rollback import lock.
    hk = hk_payload()
    hk['display_name'] = 'later-HK'
    replace_local(case, hk)
    result = adapter(case).rollback()
    assert result['phase'] == 'ROLLED_BACK'
    assert local.read_pool(m.TARGET, 'hkconnect_d1_top100') == hk
    assert shared._load_latest()['entries']['20261021/HK_FIXTURE_ROLE'] == {'fixture': 'HK-unchanged'}
    assert local.read_pool_snapshot(m.TARGET, m.POOL)['artifact_sha256'] == case['binding']['expected_previous_local']['artifact_sha256']
    assert hk_before['artifact_sha256'] != m.digest(hk)
    assert_old_run_unchanged(case)


def test_a_pending_then_hk_drift_stops_with_zero_recovery_writes(case, monkeypatch):
    local = case['local']
    ap, _ = local._relative(m.TARGET, m.POOL)
    original = local._write
    def crash_after_artifact(relative, value):
        original(relative, value)
        if relative == ap:
            raise HardExit()
    with monkeypatch.context() as patch:
        patch.setattr(local, '_write', crash_after_artifact)
        with pytest.raises(HardExit):
            adapter(case).apply()
    # Simulate a later HK writer while the A journal remains pending.
    local.materialize(hk_payload())
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_PENDING_OTHER_POOL_DRIFT'):
        adapter(case).apply()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('point', ['after-shared', 'local-artifact', 'local-receipt', 'local-manifest'])
def test_rollback_interruptions_reenter_both_sides(case, monkeypatch, point):
    op = adapter(case)
    op.apply()
    local = case['local']
    original = local._write
    ap, rp = local._relative(m.TARGET, m.POOL)
    targets = {'local-artifact': ap, 'local-receipt': rp,
               'local-manifest': f'preselection_pools/{m.TARGET}/manifest.json'}
    def crash(relative, value):
        if point == 'after-shared' and relative == op.record and value.get('phase') == 'ROLLBACK_SHARED_COMMITTED':
            raise HardExit()
        original(relative, value)
        if relative == targets.get(point):
            raise HardExit()
    with monkeypatch.context() as patch:
        patch.setattr(local, '_write', crash)
        with pytest.raises(HardExit):
            op.rollback()
    assert adapter(case).rollback()['phase'] == 'ROLLED_BACK'
    before = tree_bytes(case)
    assert adapter(case).rollback()['phase'] == 'ROLLED_BACK'
    assert tree_bytes(case) == before
    assert_old_run_unchanged(case)


def test_other_pool_pending_is_rejected_and_generic_conflict_stays(case):
    local = case['local']
    local.materialize(hk_payload())
    changed = hk_payload()
    changed['display_name'] = 'different-HK'
    with pytest.raises(ValueError, match='conflicting'):
        local.materialize(changed)
    local._write(local._pending_relative(trade_date=m.TARGET, pool_id='hkconnect_d1_top100'), {'unowned': True})
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_PENDING_OTHER_POOL'):
        adapter(case).apply()
    assert tree_bytes(case) == before


def test_no_explicit_revision_mode_rejects_before_store_change(case):
    case['binding'].pop('revision_mode')
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_EXPLICIT_REVISION_REQUIRED'):
        adapter(case)
    assert tree_bytes(case) == before


def test_closed_gate_and_missing_context_refuse_before_store_change(case):
    context = case['local']._write_gate_context
    write(context.control_dir / 'gate.json', dict(schema_version='v4.preselection.gate.v1',
          permit_sha256=context.expected_permit_sha256, revision=2, state='FENCED'))
    before = tree_bytes(case)
    with pytest.raises(case['runtime'].local_module.GateConfigurationError):
        adapter(case).apply()
    assert tree_bytes(case) == before
    case['local'] = case['runtime'].local_module.PreselectionPoolStore(case['local'].root)
    with pytest.raises(m.RevisionStop, match='STOP_WRITE_GATE_BINDING'):
        adapter(case)
    assert tree_bytes(case) == before


def test_original_default_none_gate_semantics_are_preserved(case):
    case['local'] = case['runtime'].local_module.PreselectionPoolStore(case['local'].root)
    case['binding']['write_gate'] = dict(require_write_gate_context=False, context=None)
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'


def test_signal_day_generation_projects_to_next_target_without_future_rows(case):
    import pyarrow.parquet as pq
    g = case['binding']['generation']
    verified = case['runtime'].generation.read_formula_generation(
        g['pointer'], expected_target_date=m.SIGNAL, require_source=True)
    for role in ('selector', 'backtest', 'selector_source', 'selector_sidecar'):
        assert set(pq.read_table(verified[role], columns=['trade_date']).column(0).to_pylist()) == {m.SIGNAL}
    assert adapter(case).apply()['phase'] == 'LOCAL_COMMITTED'
    pool = case['local'].read_pool(m.TARGET, m.POOL)
    assert pool['signal_date'] == m.SIGNAL and pool['target_date'] == m.TARGET


def test_generation_cannot_be_redated_to_pool_target_to_pass_admission(case):
    binding = case['binding']
    path = Path(binding['generation']['pointer'])
    pointer = json.loads(path.read_text())
    pointer['target_date'] = m.TARGET
    binding['generation']['pointer_sha256'] = write(path, pointer)['sha256']
    proof_path = Path(binding['independent_pass']['path'])
    proof = json.loads(proof_path.read_text())
    proof['binding']['generation'] = copy.deepcopy(binding['generation'])
    binding['independent_pass'] = write(proof_path, proof)
    before = tree_bytes(case)
    with pytest.raises(case['runtime'].generation.FormulaGenerationError, match='target_date mismatch'):
        adapter(case).apply()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('action', ['apply', 'rollback'])
@pytest.mark.parametrize('third_component', ['complete-trio', 'artifact', 'receipt', 'manifest'])
def test_pending_journal_never_overwrites_third_a_components(case, monkeypatch, action, third_component):
    local = case['local']
    ap, rp = local._relative(m.TARGET, m.POOL)
    manifest_path = f'preselection_pools/{m.TARGET}/manifest.json'
    original = local._write
    def crash_after_artifact(relative, value):
        original(relative, value)
        if relative == ap:
            raise HardExit()
    with monkeypatch.context() as patch:
        patch.setattr(local, '_write', crash_after_artifact)
        with pytest.raises(HardExit):
            adapter(case).apply()
    payload = local._read(ap)
    payload['display_name'] = 'later-third-A'
    if third_component == 'complete-trio':
        replace_local(case, payload)
    elif third_component == 'artifact':
        local._write(ap, payload)
    elif third_component == 'receipt':
        receipt = local._read(rp)
        receipt['artifact_sha256'] = m.digest(payload)
        local._write(rp, receipt)
    else:
        manifest = local._read(manifest_path)
        manifest[m.POOL] = m.digest(payload)
        local._write(manifest_path, manifest)
    before = tree_bytes(case)
    writes = []
    def forbid_recovery_write(relative, value):
        writes.append(relative)
        raise AssertionError('unexpected recovery write before A CAS')
    with monkeypatch.context() as patch:
        patch.setattr(local, '_write', forbid_recovery_write)
        with pytest.raises(m.RevisionStop, match='STOP_LOCAL_A_CAS'):
            getattr(adapter(case), action)()
    assert writes == []
    assert tree_bytes(case) == before
    assert local._path(local._pending_relative(trade_date=m.TARGET, pool_id=m.POOL)).is_file()


def exit_between_archive_components(case, archive_side):
    """Run a real fixture child exit after the selected archive artifact write."""
    def child():
        local = case['local']
        original = local._write
        prefix = f'preselection_revisions/{m.TARGET}/{m.POOL}/'
        old_sha = case['binding']['expected_previous_local']['artifact_sha256']
        def crash_after_archive_artifact(relative, value):
            original(relative, value)
            if relative.startswith(prefix) and not relative.endswith('.receipt.json'):
                side = 'old' if m.digest(value) == old_sha else 'new'
                if side == archive_side:
                    os._exit(74)
        local._write = crash_after_archive_artifact
        adapter(case).apply()
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start()
    process.join(20)
    assert not process.is_alive() and process.exitcode == 74
    state = case['local']._read(adapter(case).record)
    assert state['local_archive_intent']
    return state


@pytest.mark.parametrize('archive_side', ['old', 'new'])
@pytest.mark.parametrize('action', ['apply', 'rollback'])
def test_claimed_old_and_new_half_archives_resume_after_process_exit(case, archive_side, action):
    exit_between_archive_components(case, archive_side)
    result = getattr(adapter(case), action)()
    assert result['phase'] == ('LOCAL_COMMITTED' if action == 'apply' else 'ROLLED_BACK')
    for relative, sha in result['local_archive_intent'].items():
        assert m.file_sha(case['local']._path(relative)) == sha
    if action == 'rollback':
        assert m.identity(case['shared'].verify_latest(m.TARGET, m.ROLE)['verified']) == case['binding']['expected_previous_shared']
        assert case['local'].read_pool_snapshot(m.TARGET, m.POOL)['artifact_sha256'] == case['binding']['expected_previous_local']['artifact_sha256']
    assert_old_run_unchanged(case)


@pytest.mark.parametrize('archive_side', ['old', 'new'])
def test_claimed_half_archive_drift_is_never_overwritten(case, archive_side):
    state = exit_between_archive_components(case, archive_side)
    local = case['local']
    paths = list(state['local_archive_intent'])
    partial_artifact = next(path for path in paths if not path.endswith('.receipt.json')
                            and local._path(path).is_file()
                            and not local._path(path[:-5] + '.receipt.json').exists())
    raw = local._io.read_bytes(partial_artifact)
    local._io.write_bytes(partial_artifact, raw + b' ')
    before = tree_bytes(case)
    op = adapter(case)
    local_lock_path = local.root / '.import.lock'
    local_lock_relative = str(local_lock_path.relative_to(case['root']))
    local_owner = json.loads(before[local_lock_relative])
    child_claim = local._read(op.lock_claim_relative)
    assert local_owner['schema_version'] == 'v3_5_interprocess_lock.v1'
    assert type(local_owner['pid']) is int and local_owner['pid'] > 0
    assert local_owner['pid'] == child_claim['owner']['pid']
    with pytest.raises(ProcessLookupError):
        os.kill(local_owner['pid'], 0)
    with pytest.raises(m.RevisionStop, match='STOP_ARCHIVE_IDENTITY_DRIFT'):
        op.apply()
    after = tree_bytes(case)
    # The exact proven-dead lock/control claim may be released by original
    # acquisition. Every business/archive byte must still remain unchanged.
    control_paths = ('shared/.store.lock', 'local/' + op.lock_claim_relative, local_lock_relative)
    for relative in control_paths:
        before.pop(relative, None)
        after.pop(relative, None)
    assert after == before
    assert not case['shared'].lock_path.exists()
    assert not local_lock_path.exists()


def test_unclaimed_matching_half_archive_is_not_adopted(case):
    local = case['local']
    snapshot = local.read_pool_snapshot(m.TARGET, m.POOL)
    sha = snapshot['artifact_sha256']
    local._archive_recovery_revision(m.TARGET, m.POOL, sha, snapshot['artifact'], snapshot['receipt'])
    artifact_path, receipt_path = local._revision_relative(m.TARGET, m.POOL, sha)
    # Fixture-only orphan predates this operation and has no durable claim.
    local._path(receipt_path).unlink()
    raw = local._io.read_bytes(artifact_path)
    with pytest.raises(m.RevisionStop, match='STOP_UNOWNED_PARTIAL_ARCHIVE'):
        adapter(case).apply()
    assert local._io.read_bytes(artifact_path) == raw
    assert not local._path(receipt_path).exists()


def test_rollback_then_new_operation_refuses_retained_ready_run_without_writes(case):
    op = adapter(case)
    result = op.apply()
    op.rollback()
    new = result['new_shared']
    retained_dir = case['shared'].root / Path(new['artifact_relative']).parent
    retained = {p.name: p.read_bytes() for p in retained_dir.iterdir() if p.is_file()}
    case['binding']['operation_id'] = 'different-operation-same-candidate'
    before = tree_bytes(case)
    other = adapter(case)
    with pytest.raises(m.RevisionStop, match='STOP_RETAINED_TARGET_RUN'):
        other.apply()
    assert tree_bytes(case) == before
    assert not case['local']._path(other.record).exists()
    assert {p.name: p.read_bytes() for p in retained_dir.iterdir() if p.is_file()} == retained
    assert_old_run_unchanged(case)


def test_target_run_appearance_at_original_replay_lock_stops_before_rewrite(case, monkeypatch):
    # Retain a real READY fixture run outside the live fixture root, then reset
    # only the fixture's pointed-to state with the adapter's conditional rollback.
    op = adapter(case)
    result = op.apply()
    op.rollback()
    import shutil
    run_dir = case['shared'].root / Path(result['new_shared']['artifact_relative']).parent
    saved = case['root'] / 'saved-ready-run'
    shutil.copytree(run_dir, saved)
    shutil.rmtree(run_dir)  # Fixture only, never a live operation.
    case['binding']['operation_id'] = 'race-at-replay-lock'
    racing = adapter(case)
    original = racing.shared.replay_file
    def concurrent_run_before_inherited_lock(**kwargs):
        shutil.copytree(saved, run_dir)
        return original(**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(racing.shared, 'replay_file', concurrent_run_before_inherited_lock)
        with pytest.raises(m.RevisionStop, match='STOP_RETAINED_TARGET_RUN'):
            racing.apply()
    assert {p.name: p.read_bytes() for p in run_dir.iterdir() if p.is_file()} == {
        p.name: p.read_bytes() for p in saved.iterdir() if p.is_file()}
    assert m.identity(case['shared'].verify_latest(m.TARGET, m.ROLE)['verified']) == case['binding']['expected_previous_shared']


def test_shared_lock_live_bound_owner_is_refused_even_when_legacy_age_is_stale(case, monkeypatch):
    op = adapter(case)
    op.apply()
    op.shared.lock_path.write_bytes(f'{os.getpid()}:{"a" * 32}'.encode('ascii'))
    # This is fixture metadata, not a change to either original lock threshold.
    old = m.time.time() - 60
    os.utime(op.shared.lock_path, (old, old))
    owner = op._shared_lock_snapshot()
    case['local']._io.write_bytes(op.lock_claim_relative, m.canonical(op._lock_claim(owner)))
    def forbidden_original_lock():
        raise AssertionError('live owner must not reach original age-based cleanup')
    monkeypatch.setattr(op.shared, '_lock', forbidden_original_lock)
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_OWNER_NOT_DEAD'):
        op.apply()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('raw', [b'unknown-lock-format', b'1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'])
def test_shared_lock_unknown_owner_is_never_delegated_or_deleted(case, monkeypatch, raw):
    op = adapter(case)
    op.apply()
    op.shared.lock_path.write_bytes(raw)
    old = m.time.time() - 60
    os.utime(op.shared.lock_path, (old, old))
    def forbidden_original_lock():
        raise AssertionError('unknown owner must not reach original age-based cleanup')
    monkeypatch.setattr(op.shared, '_lock', forbidden_original_lock)
    before = tree_bytes(case)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_(UNKNOWN_OWNER|UNBOUND_OR_REPLACED)'):
        op.apply()
    assert tree_bytes(case) == before


@pytest.mark.parametrize('replacement', ['healthy-token', 'new-inode-same-token'])
def test_shared_lock_token_or_inode_replacement_during_wait_stops(case, monkeypatch, replacement):
    exit_between_archive_components(case, 'old')
    op = adapter(case)
    op._admit()
    claim = op._read_lock_claim()
    retained = op.shared.lock_path.read_bytes()
    replacement_raw = (f'{os.getpid()}:{"c" * 32}'.encode('ascii')
                       if replacement == 'healthy-token' else retained)
    calls = []
    def replace_on_wait(delay):
        calls.append(delay)
        other = case['root'] / 'replacement-lock'
        other.write_bytes(replacement_raw)
        os.replace(other, op.shared.lock_path)
    monkeypatch.setattr(m.time, 'sleep', replace_on_wait)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_UNBOUND_OR_REPLACED'):
        op._wait_for_original_shared_lock(claim, deadline=m.time.monotonic() + 40)
    assert calls and op.shared.lock_path.read_bytes() == replacement_raw


def test_shared_lock_claim_must_belong_to_exact_operation_binding(case):
    exit_between_archive_components(case, 'old')
    op = adapter(case)
    op._admit()
    claim = case['local']._read(op.lock_claim_relative)
    claim['binding_sha256'] = '0' * 64
    case['local']._io.write_bytes(op.lock_claim_relative, m.canonical(claim))
    before = tree_bytes(case)
    local_lock_path = case['local'].root / '.import.lock'
    local_lock_relative = str(local_lock_path.relative_to(case['root']))
    local_owner = json.loads(before[local_lock_relative])
    assert local_owner['schema_version'] == 'v3_5_interprocess_lock.v1'
    assert type(local_owner['pid']) is int and local_owner['pid'] > 0
    assert local_owner['pid'] == claim['owner']['pid']
    with pytest.raises(ProcessLookupError):
        os.kill(local_owner['pid'], 0)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_CLAIM_DRIFT'):
        op.apply()
    after = tree_bytes(case)
    before.pop(local_lock_relative)
    after.pop(local_lock_relative, None)
    assert after == before
    assert not local_lock_path.exists()


@pytest.mark.parametrize('probe_error', [PermissionError(m.errno.EPERM, 'fixture'), OSError(m.errno.EIO, 'fixture')])
def test_shared_lock_only_esrch_is_death_evidence(case, monkeypatch, probe_error):
    def unknown_probe(pid, signal):
        raise probe_error
    monkeypatch.setattr(m.os, 'kill', unknown_probe)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_OWNER_NOT_DEAD'):
        m.SameDayRevision._require_dead_pid(1)


def test_shared_lock_dead_owner_wait_reserves_original_timeout_and_stops_at_budget(case, monkeypatch):
    exit_between_archive_components(case, 'old')
    op = adapter(case)
    op._admit()
    claim = op._read_lock_claim()
    before = tree_bytes(case)
    monkeypatch.setattr(m.time, 'monotonic', lambda: 100.0)
    def forbidden_sleep(delay):
        raise AssertionError('deadline must stop before another wait')
    monkeypatch.setattr(m.time, 'sleep', forbidden_sleep)
    with pytest.raises(m.RevisionStop, match='STOP_SHARED_LOCK_RECOVERY_DEADLINE'):
        op._wait_for_original_shared_lock(claim, deadline=109.999)
    assert tree_bytes(case) == before


def test_shared_lock_original_strict_stale_boundary_is_preserved(case, monkeypatch):
    exit_between_archive_components(case, 'old')
    op = adapter(case)
    op._admit()
    claim = op._read_lock_claim()
    original_raw = op.shared.lock_path.read_bytes()
    clock = [claim['owner']['mtime_ns'] / 1_000_000_000 + 30.0]
    waits = []
    monkeypatch.setattr(m.time, 'time', lambda: clock[0])
    monkeypatch.setattr(m.time, 'monotonic', lambda: 0.0)
    def advance_wait(delay):
        waits.append(delay)
        clock[0] += delay
    monkeypatch.setattr(m.time, 'sleep', advance_wait)
    op._wait_for_original_shared_lock(claim, deadline=40.0)
    assert waits and op.shared.lock_path.read_bytes() == original_raw
    assert op.shared_store_module.STORE_LOCK_TIMEOUT_SECONDS == 10.0
    assert op.shared_store_module.STORE_LOCK_STALE_SECONDS == 30.0
