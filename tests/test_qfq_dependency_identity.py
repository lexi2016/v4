"""R2 falsification against isolated source roots, receipts and pool registry."""
import copy
import hashlib
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import research_qfq_dependency_identity as identity
from ops import research_qfq_task_continuity as continuity
from ops import research_storage_governance as governance
from test_qfq_task_continuity import TARGET, fixture, move, put, claim_process


def unchanged(f, before):
    assert f.registry.path.read_bytes() == before
    assert len(f.registry.read()['tasks']) == 1
    row = next(iter(f.registry.read()['tasks'].values()))
    assert row['reserved_bytes'] == 1024 * 1024
    assert row['logical_written_bytes'] == 110
    assert f.checkpoint.exists()


def test_D01_equal_complete_sources_across_roots_have_one_identity(fixture):
    f = fixture
    old = SimpleNamespace(__file__=str(f.roots[0] / 'ops/research_panel_qfq.py'), input_path=f.module.input_path)
    args = dict(f.kwargs, driver_path=f.roots[0] / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py')
    assert identity.computation_dependencies(old, args) == identity.computation_dependencies(f.module, f.kwargs)
    assert governance.qfq_invocation_key(old, f.data, TARGET, args) == f.key


@pytest.mark.parametrize(('case', 'path'), [
    ('D02', 'ops/research_panel_turnover.py'),
    ('D03', 'ops/research_panel_daily_source.py'),
    ('D04', 'ops/research_panel_factor_cache.py'),
    ('D05', 'ops/research_panel_logical.py'),
    ('D06', 'ops/research_panel_delta.py'),
    ('D07', 'ops/research_panel_adjustment_inputs.py'),
    ('D08', 'ops/research_panel_tdx_adjustment_inputs.py'),
    ('D09', 'contracts/a_share_generation_compatibility.json'),
    ('D10', 'contracts/a_share_daily_source_policy.json'),
    ('D11-driver', 'ops/vendor/data_layer_daily_formula_increment_update_v1.py'),
    ('D11-formula', 'formula'), ('D11-field', 'field'),
], ids=lambda value:value)
def test_D02_D11_changed_dependency_is_distinct_and_cannot_migrate(fixture, case, path):
    f = fixture
    source = (f.kwargs['formula_path'] if path == 'formula' else
              f.kwargs['contract_csv'] if path == 'field' else f.roots[1] / path)
    if source.suffix == '.json':
        source.write_text('{"changed":true}')
    else:
        source.write_bytes(source.read_bytes() + b'\n# actual dependency byte change\n')
    assert governance.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs) != f.key
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError):
        move(f)
    unchanged(f, before)


def test_D12_frozen_snapshot_change_is_distinct_and_refuses_old_plan(fixture):
    f = fixture
    frozen_args = dict(f.kwargs, refresh_inputs=False)
    before_key = governance.qfq_invocation_key(f.module, f.data, TARGET, frozen_args)
    before_manifest = f.plan['computation_dependencies']
    put(f.snapshot, dict(asof_date=TARGET, input='a second real source snapshot'))
    assert governance.qfq_invocation_key(f.module, f.data, TARGET, frozen_args) != before_key
    assert identity.computation_dependencies(f.module, f.kwargs,
        snapshot=json.loads(f.snapshot.read_bytes())) != before_manifest
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='SNAPSHOT_DRIFT'):
        move(f)
    unchanged(f, before)


def test_D13_undeclared_dynamic_dependency_blocks_normal_entry(fixture):
    f = fixture
    owner = Path(f.module.__file__)
    owner.write_text(owner.read_text() + "\nimport importlib\nimportlib.import_module('unknown_formula')\n")
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='DYNAMIC_UNREVIEWED'):
        governance.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs)
    unchanged(f, before)


@pytest.mark.parametrize('change', ['duplicate-role', 'duplicate-path', 'forged-sha', 'missing-sha', 'escape'])
def test_D14_manifest_corruption_cannot_authorize_migration(fixture, change):
    f = fixture
    rows = f.plan['computation_dependencies']['dependencies']
    if change == 'duplicate-role':
        rows.append(copy.deepcopy(rows[0]))
    elif change == 'duplicate-path':
        rows[0]['path'] = rows[1]['path']
    elif change == 'forged-sha':
        rows[0]['sha256'] = '0' * 64
    elif change == 'missing-sha':
        del rows[0]['sha256']
    else:
        rows[0]['path'] = '../outside.py'
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError):
        move(f)
    unchanged(f, before)


def test_D15_missing_old_root_dependency_blocks_exact_rekey(fixture):
    f = fixture
    (f.roots[0] / 'ops/research_panel_daily_source.py').unlink()
    before = f.registry.path.read_bytes()
    with pytest.raises((governance.RetentionError, OSError)):
        move(f)
    unchanged(f, before)


def test_D16_dependency_replaced_during_read_is_blocked(fixture, monkeypatch):
    f = fixture
    changed = f.roots[1] / 'ops/research_panel_turnover.py'
    original = Path.read_bytes
    def racing_read(path):
        value = original(path)
        if path == changed:
            path.write_bytes(value + b'\n# changed while being read\n')
        return value
    monkeypatch.setattr(Path, 'read_bytes', racing_read)
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='CHANGED_DURING_READ'):
        identity.computation_dependencies(f.module, f.kwargs)
    unchanged(f, before)


def test_D17_two_processes_share_one_complete_identity_reservation(fixture):
    f = fixture
    move(f)
    ctx = multiprocessing.get_context('spawn')
    ready, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
    args = (f.policy, f.key, str(f.runs), governance.canonical(f.plan), ready, release, result)
    first = ctx.Process(target=claim_process, args=args)
    second = ctx.Process(target=claim_process, args=args)
    try:
        first.start()
        assert ready.wait(10)
        second.start()
        second.join(10)
        assert not second.is_alive()
        assert result.get(timeout=3) == 'POOL_WRITER_BUSY_BOUNDED_WAIT'
        release.set()
        first.join(10)
        assert first.exitcode == 0
        assert result.get(timeout=3) == 'ONE_OWNER'
    finally:
        release.set()
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(3)
    row = f.registry.read()['tasks'][f.key]
    assert len(f.registry.read()['tasks']) == 1
    assert row['attempts'] == 2 and row['reserved_bytes'] == 1024 * 1024


@pytest.mark.parametrize('change', ['registry', 'token'])
def test_D18_concurrent_registry_or_token_change_fails_cas(fixture, change):
    f = fixture
    state = f.registry.read()
    if change == 'token':
        state['tasks'][f.legacy]['token'] = 'another-attempt-fence'
    else:
        state['parallel-controller-marker'] = True
    f.registry.save(state)
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError):
        move(f)
    unchanged(f, before)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_D19_crash_at_atomic_replace_retains_single_reservation(fixture, monkeypatch, when):
    f = fixture
    original = governance.os.replace
    def interrupted(source, target):
        if when == 'after':
            original(source, target)
        raise OSError('isolated crash at registry replace')
    monkeypatch.setattr(governance.os, 'replace', interrupted)
    with pytest.raises(OSError):
        move(f)
    monkeypatch.setattr(governance.os, 'replace', original)
    assert move(f)['status'] in {'COMMITTED', 'ALREADY_COMMITTED'}
    row = f.registry.read()['tasks'][f.key]
    assert len(f.registry.read()['tasks']) == 1 and row['reserved_bytes'] == 1024 * 1024
    assert f.checkpoint.exists()


def test_D20_two_input_generations_require_an_exact_reviewed_linkage(fixture):
    f = fixture
    state = f.registry.read()
    second = f.runs / ('qfq_' + 'c' * 20)
    put(second / 'checkpoint.json', dict(input_sha256='d' * 64))
    state['tasks'][f.legacy]['billing_paths'].append(str(second))
    f.registry.save(state)
    linkage = json.loads(Path(f.plan['linkage_review']['path']).read_bytes())
    linkage.update(status='BLOCKED_AMBIGUOUS_INPUT_GENERATIONS', evidence_closed=False,
                   row_sha256=governance.canonical(state['tasks'][f.legacy]))
    ref = put(Path(f.plan['linkage_review']['path']), linkage)
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='LINKAGE_UNPROVEN'):
        continuity.prepare_qfq_migration(f.module, f.policy, data_root=f.data, return_root=f.runs,
            target=TARGET, kwargs=f.kwargs, old_root=f.roots[0],
            expected_registry_sha256=governance.digest(f.registry.path), expected_token='original-token',
            owner_receipt=f.plan['owner_receipt'], evidence_refs=f.plan['evidence_refs'], linkage_review=ref)
    unchanged(f, before)
    assert (second / 'checkpoint.json').exists()


def test_old_plan_and_rollback_reject_changed_closure_after_commit(fixture):
    f = fixture
    move(f)
    for root in f.roots:
        source = root / 'contracts/a_share_daily_source_policy.json'
        source.write_text('{"source_revision":2}')
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='SCOPE_DRIFT'):
        move(f, rollback=True, expected_registry_sha256=governance.digest(f.registry.path))
    unchanged(f, before)


def test_rollback_rejects_new_attempt_and_preserves_artifacts(fixture):
    f = fixture
    move(f)
    state = f.registry.read()
    state['tasks'][f.key]['attempts'] += 1
    f.registry.save(state)
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='TASK_DRIFT'):
        move(f, rollback=True, expected_registry_sha256=governance.digest(f.registry.path))
    unchanged(f, before)


def test_turnover_missing_input_becoming_present_invalidates_plan(fixture):
    f = fixture
    evidence = f.plan['turnover_input_evidence']
    put(Path(evidence['sync_path']), {'target_date':TARGET, 'changed':'input now exists'})
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='TURNOVER_ABSENCE_CHANGED'):
        move(f)
    unchanged(f, before)


def test_original_snapshot_member_sha_and_disposition_maps_remain_bound(fixture):
    f = fixture
    snapshot = json.loads(f.snapshot.read_bytes())
    snapshot.update(raw_member=dict(path='/archive/original.zip', member='000001.day', member_sha256='a' * 64),
        disposition=dict(path='/native/000002.day', source_sha256_after='b' * 64))
    before = identity.computation_dependencies(f.module, f.kwargs, snapshot=snapshot)
    snapshot['raw_member']['member_sha256'] = 'c' * 64
    after = identity.computation_dependencies(f.module, f.kwargs, snapshot=snapshot)
    assert before['frozen_input_sha256'] != after['frozen_input_sha256']


def test_generation_digest_covers_contracts_via_existing_owner_entry(fixture, monkeypatch):
    from ops import research_panel_qfq as owner
    f = fixture
    monkeypatch.setattr(owner, '__file__', f.module.__file__)
    snapshot = json.loads(f.snapshot.read_bytes())
    arguments = (snapshot, f.kwargs['driver_path'], f.kwargs['formula_path'], f.kwargs['contract_csv'])
    first = owner.generation_identity(*arguments, input_root=f.snapshot.parent)
    (f.roots[1] / 'contracts/a_share_generation_compatibility.json').write_text('{"revision":2}')
    second = owner.generation_identity(*arguments, input_root=f.snapshot.parent)
    assert first['computation_dependency_sha256'] != second['computation_dependency_sha256']


def test_known_dynamic_loader_without_bound_parser_is_blocked(fixture):
    f = fixture
    helper = f.roots[1] / 'ops/research_panel_tdx_adjustment_inputs.py'
    helper.write_text("import importlib.util\ndef load(config):\n    return importlib.util.spec_from_file_location('qfq_official_gbbq_parser', config['parser']['path'])\n")
    with pytest.raises(governance.RetentionError, match='DYNAMIC_TARGET_UNBOUND'):
        identity.computation_dependencies(f.module, f.kwargs)


def test_turnover_typed_reference_requires_plain_sha_before_migration(fixture):
    f = fixture
    evidence = f.plan['turnover_input_evidence']
    evidence.update(state='BOUND', failure=None, binding={
        'sync':{'path':evidence['sync_path']},
        'package':{'path':'/fixture/package'}, 'input_ref':{'path':'/fixture/input'},
        'gbbq':{key:{'path':'/fixture/' + key} for key in
                ('capture', 'raw', 'archive', 'parser', 'category_policy', 'derived_parquet', 'derived_receipt')}})
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='TURNOVER_REFERENCE_REQUIRED'):
        move(f)
    unchanged(f, before)


def test_owner_generation_digest_cannot_be_substituted(fixture):
    f = fixture
    ref = f.plan['owner_receipt']
    receipt = json.loads(Path(ref['path']).read_bytes())
    receipt['computation_dependency_sha256'] = 'f' * 64
    f.plan['owner_receipt'] = put(Path(ref['path']), receipt)
    before = f.registry.path.read_bytes()
    with pytest.raises(governance.RetentionError, match='COMPUTATION_DEPENDENCY_EVIDENCE_CONFLICT'):
        move(f)
    unchanged(f, before)


def test_first_generation_rechecks_expected_resume_dependency_closure(fixture):
    f = fixture
    claim = SimpleNamespace(qfq_expected_dependencies=copy.deepcopy(f.plan['computation_dependencies']))
    changed = copy.deepcopy(f.plan['computation_dependencies'])
    changed['dependencies'][0]['sha256'] = 'b' * 64
    with identity.computation_scope(claim):
        with pytest.raises(governance.RetentionError, match='RESUME_COMPUTATION_DEPENDENCY_CHANGED'):
            identity.observe_generation(json.loads(f.snapshot.read_bytes()), changed)
    assert not hasattr(claim, 'qfq_computation_dependencies')


def test_aliased_unknown_dynamic_import_is_blocked(fixture):
    f = fixture
    source = Path(f.module.__file__)
    source.write_text("from importlib import import_module as load_extra\nload_extra('unknown_math')\n")
    with pytest.raises(governance.RetentionError, match='DYNAMIC_UNREVIEWED'):
        identity.computation_dependencies(f.module, f.kwargs)


def test_parent_package_initializer_is_a_computation_dependency(fixture):
    f = fixture
    package = f.roots[1] / 'ops/test_dependency_package'
    package.mkdir()
    (package / '__init__.py').write_text('SETTING = 1\n')
    (package / 'kernel.py').write_text('VALUE = 3\n')
    owner = Path(f.module.__file__)
    owner.write_text('from ops.test_dependency_package.kernel import VALUE\n')
    first = governance.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs)
    manifest = identity.computation_dependencies(f.module, f.kwargs)
    assert any(r['path'] == 'ops/test_dependency_package/__init__.py' for r in manifest['dependencies'])
    (package / '__init__.py').write_text('SETTING = 2\n')
    assert governance.qfq_invocation_key(f.module, f.data, TARGET, f.kwargs) != first


def test_logical_prepublication_uses_same_runtime_root_as_generation(fixture, monkeypatch):
    import ast
    from ops import research_panel_delta as delta
    from ops import research_panel_qfq as owner
    f = fixture
    monkeypatch.setattr(owner, '__file__', f.module.__file__)
    put(f.snapshot.parent / 'qfq_factor_cache_binding.json', {'path':'/fixture/original/factors'})
    snapshot = json.loads(f.snapshot.read_bytes())
    args = (snapshot, f.kwargs['driver_path'], f.kwargs['formula_path'], f.kwargs['contract_csv'])
    complete = owner.generation_identity(*args, input_root=f.snapshot.parent)
    without_runtime = owner.generation_identity(*args)
    assert complete != without_runtime
    source = ast.parse(Path(delta.__file__).read_bytes())
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == '_run_delta')
    check = next(node for node in function.body if isinstance(node, ast.If)
                 and any(isinstance(item, ast.Constant) and item.value == 'INPUT_CHANGED_DURING_BUILD' for item in ast.walk(node)))
    context = dict(snapshot_file=f.snapshot, driver_path=f.kwargs['driver_path'],
                   formula_path=f.kwargs['formula_path'], contract_csv=f.kwargs['contract_csv'], identity=complete)
    namespace = {'q':{'generation_identity':owner.generation_identity, 'load_snapshot':lambda *_:snapshot}, 'c':context, 'target':TARGET}
    exec(compile(ast.Module(body=[check], type_ignores=[]), delta.__file__, 'exec'), namespace)


def test_stored_dynamic_loader_cannot_escape_manifest_review(fixture):
    f = fixture
    Path(f.module.__file__).write_text("import importlib\nloader = importlib.import_module\nloader('unreviewed_dynamic_formula')\n")
    with pytest.raises(governance.RetentionError, match='DYNAMIC_ALIAS_UNREVIEWED'):
        identity.computation_dependencies(f.module, f.kwargs)


def test_inspection_of_old_root_uses_the_executing_root_environment(fixture, monkeypatch):
    import sys
    f = fixture
    monkeypatch.setattr(identity, '__file__', str(f.roots[1] / 'ops/research_qfq_dependency_identity.py'))
    monkeypatch.setattr(sys, 'path', [str(f.roots[1]), str(f.roots[1] / 'ops')] + list(sys.path))
    old = SimpleNamespace(__file__=str(f.roots[0] / 'ops/research_panel_qfq.py'), input_path=f.module.input_path)
    arguments = dict(f.kwargs, driver_path=f.roots[0] / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py')
    old_manifest = identity.computation_dependencies(old, arguments)
    new_manifest = identity.computation_dependencies(f.module, f.kwargs)
    assert old_manifest == new_manifest
    assert old_manifest['environment']['search_path'][:2] == ['$APP_ROOT', '$APP_ROOT/ops']


def test_unreviewed_call_to_owner_dynamic_loader_is_blocked(fixture):
    f = fixture
    Path(f.module.__file__).write_text("_load('/unreviewed/formula.py', 'unknown', 'unexpected')\n")
    with pytest.raises(governance.RetentionError, match='DYNAMIC_UNREVIEWED'):
        identity.computation_dependencies(f.module, f.kwargs)


def fake_runtime(monkeypatch, root):
    import base64
    import sys
    library = root / 'stdlib'
    library.mkdir()
    (library / 'minimal.py').write_text('# controlled standard runtime\n')
    site = root / 'site-packages'
    package = site / 'numpy'
    package.mkdir(parents=True)
    source = package / '__init__.py'
    source.write_text('VERSION = 1\n')
    encoded = base64.urlsafe_b64encode(hashlib.sha256(source.read_bytes()).digest()).decode().rstrip('=')
    record = 'numpy/__init__.py,sha256=' + encoded + ',' + str(source.stat().st_size) + '\n'
    dist = SimpleNamespace(metadata={'Name':'fixture-runtime'}, version='1', requires=[],
        read_text=lambda name:record if name == 'RECORD' else 'Name: fixture-runtime\nVersion: 1\n',
        locate_file=lambda name:site / name)
    monkeypatch.setattr(identity.sysconfig, 'get_path', lambda name:str(library))
    monkeypatch.setattr(identity.importlib.metadata, 'packages_distributions', lambda:{'numpy':['fixture-runtime']})
    monkeypatch.setattr(identity.importlib.metadata, 'distribution', lambda name:dist)
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace(__file__=str(source)))
    return source


def test_runtime_package_bytes_are_checked_with_unchanged_record(tmp_path, monkeypatch):
    source = fake_runtime(monkeypatch, tmp_path)
    proof = identity.environment_identity({'numpy'})
    assert proof['packages']['fixture-runtime']['artifact_count'] == 1
    source.write_text('VERSION = 2\n')
    with pytest.raises(governance.RetentionError, match='RUNTIME_ARTIFACT_CONFLICT'):
        identity.environment_identity({'numpy'})


def test_runtime_import_shadowing_is_rejected(tmp_path, monkeypatch):
    import sys
    fake_runtime(monkeypatch, tmp_path)
    shadow = tmp_path / 'shadow.py'
    shadow.write_text('SHADOWED = True\n')
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace(__file__=str(shadow)))
    with pytest.raises(governance.RetentionError, match='RUNTIME_IMPORT_SHADOWED'):
        identity.environment_identity({'numpy'})


def test_normal_owner_receipt_captures_observed_generation_proof(fixture):
    from ops import research_panel_qfq as owner
    f = fixture
    dependencies = f.plan['computation_dependencies']
    claim = SimpleNamespace(qfq_dependency_context=dict(data_root=f.data, kwargs=f.kwargs),
        watch=lambda *_:None, checkpoint=lambda **_:None, observe=lambda *_:None)
    value = SimpleNamespace(binding={}, failure='DAILY_SYNC_RECEIPT_MISSING',
                            identity=f.plan['turnover_input_evidence']['identity'])
    token = governance._ACTIVE.set(claim)
    try:
        with identity.computation_scope(claim):
            identity.observe_generation(json.loads(f.snapshot.read_bytes()), dependencies)
            identity.observe_turnover(f.module.__file__, f.data, f.kwargs['tdx_root'], TARGET, value, 'SYNTHETIC_TURNOVER')
            with governance.qfq_write_seams(owner, claim):
                receipt = f.runs / 'candidate_receipt.json'
                owner._json(receipt, dict(status='CANDIDATE_READY',
                    computation_dependency_sha256=governance.canonical(dependencies)))
                preserved = f.runs / 'qfq_readiness.json'
                owner._write(preserved, b'{"original":"large owner readiness"}')
    finally:
        governance._ACTIVE.reset(token)
    document = json.loads(receipt.read_bytes())
    assert document['computation_dependencies'] == dependencies
    assert document['turnover_input_evidence'] == f.plan['turnover_input_evidence']
    assert preserved.read_bytes() == b'{"original":"large owner readiness"}'


def test_package_calendar_loader_requires_a_reviewed_calendar_target(fixture):
    f = fixture
    package = f.roots[1] / 'ops/_a_share_daily_sync_parts'
    package.mkdir()
    (package / 'official_daily_package.py').write_text(
        'import importlib.util\ndef load(module_name, adapter_path):\n    return importlib.util.spec_from_file_location(module_name, adapter_path)\n')
    Path(f.module.__file__).write_text('from ops._a_share_daily_sync_parts.official_daily_package import load\n')
    with pytest.raises(governance.RetentionError, match='DYNAMIC_TARGET_UNBOUND:calendar_adapter'):
        identity.computation_dependencies(f.module, f.kwargs)


@pytest.mark.parametrize('alter', [None, 'primary-adapter', 'history-adapter'])
def test_typed_turnover_calendar_proof_binds_actual_primary_and_history(fixture, alter):
    f = fixture
    adapter = f.data / 'calendar_adapter.py'
    adapter.write_text('# exact reviewed pure calendar adapter\n')
    calendar = put(f.data / 'calendar.json', {'sessions':[TARGET - 1, TARGET]})
    adapter_ref = {'path':str(adapter), 'sha256':governance.digest(adapter)}
    policy = {'calendar':calendar, 'calendar_adapter':adapter_ref}
    (f.roots[1] / 'contracts/a_share_daily_source_policy.json').write_text(json.dumps(policy))
    other = f.data / 'other_adapter.py'
    other.write_bytes(adapter.read_bytes())
    other_ref = {'path':str(other), 'sha256':governance.digest(other)}
    descriptors = []
    for index, date in enumerate((TARGET, TARGET - 1)):
        chosen = other_ref if alter == ('primary-adapter' if index == 0 else 'history-adapter') else adapter_ref
        descriptors.append(put(f.data / ('input-' + str(date) + '.json'),
            dict(schema_version='a_sync_official_daily_input.v1', source_kind='TDX_OFFICIAL_G4DAY',
                 target_date=date, calendar=calendar, calendar_adapter=chosen)))
    package = put(f.data / 'dated-package.json', {'fixture':'read-only original package bytes'})
    sync_path = Path(f.plan['turnover_input_evidence']['sync_path'])
    source = dict(source_kind='TDX_OFFICIAL_G4DAY', package=package,
                  input_ref=dict(descriptors[0], history_inputs=[dict(descriptors[1], target_date=TARGET - 1)]))
    sync = put(sync_path, dict(target_date=TARGET, official_daily_source=source))
    gbbq = {key:put(f.data / (key + '.json'), {'fixture':key}) for key in
            ('capture', 'raw', 'archive', 'parser', 'category_policy', 'derived_parquet', 'derived_receipt')}
    binding = dict(sync=sync, package=package, input_ref=descriptors[0], gbbq=gbbq)
    evidence = dict(f.plan['turnover_input_evidence'], state='BOUND', binding=binding, failure=None)
    evidence['identity'] = governance.canonical(dict(policy='SYNTHETIC_TURNOVER',
        helper_sha256=governance.digest(f.roots[1] / 'ops/research_panel_turnover.py'),
        target=TARGET, binding=binding, failure=None))
    if alter:
        with pytest.raises(governance.RetentionError, match='CALENDAR_ADAPTER_CONFLICT'):
            identity.validate_turnover_evidence(f.module, f.kwargs, TARGET, evidence)
        with pytest.raises(governance.RetentionError, match='CALENDAR_ADAPTER_CONFLICT'):
            identity.validate_turnover_before_load(f.module.__file__, f.kwargs['tdx_root'], TARGET)
    else:
        assert identity.validate_turnover_evidence(f.module, f.kwargs, TARGET, evidence) == evidence
        identity.validate_turnover_before_load(f.module.__file__, f.kwargs['tdx_root'], TARGET)
