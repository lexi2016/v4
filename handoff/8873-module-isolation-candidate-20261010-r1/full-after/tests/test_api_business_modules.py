"""Synthetic same-gateway module release contracts; never use a live plist."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib

import pytest

from ops import api_release_integration as integration
from ops import build_release_candidate as builder
from ops.prepare_api_only_cutover import rewrite_api_only_plist


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def setup_active(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    contract_path = root / 'approved-module-owners.json'
    contract = {
        'schema_version': 'v4.api_business_module_owners.v1',
        'status': 'APPROVED', 'approval_id': 'SYNTHETIC_TEST_ONLY',
        'protected_external_roots': [str(root / 'synthetic-state')],
        'modules': [
            {'module_id': 'alpha', 'source_owner': 'synthetic-alpha',
             'paths': ['modules/alpha.py', 'modules/alpha_extra.py'], 'depends_on': [],
             'routes': [{'method': 'GET', 'path': '/alpha'}], 'state_compatibility': 'UNCHANGED'},
            {'module_id': 'beta', 'source_owner': 'synthetic-beta',
             'paths': ['modules/beta.py'], 'depends_on': [],
             'routes': [{'method': 'GET', 'path': '/beta'}], 'state_compatibility': 'UNCHANGED'},
        ],
        'shared_paths': [{'path': 'shared/registry.py', 'source_owner': 'synthetic-platform'}],
    }
    dump(contract_path, contract)
    release = root / 'G'
    app = release / 'app'
    files = {
        'modules/alpha.py': b'ALPHA = 0\n', 'modules/beta.py': b'BETA = 0\n',
        'shared/registry.py': b'ROUTES = ("alpha", "beta")\n',
        'apps/api/v35_api/app.py': b'GATEWAY = True\n',
        'apps/web/dist/index.html': b'<p>current</p>\n',
        'apps/web/dist/assets/current.js': b'console.log("current")\n',
        'config/current.json': b'{"read_only":true}\n',
    }
    for relative, raw in files.items():
        path = app / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    inventory = integration.inventory_tree(app)
    manifest = {'schema_version': 'v4.release_candidate.v1',
                'candidate': {'root': str(release), 'app_root': str(app), 'release_id': 'G'},
                'application_inventory': {'entries': inventory, 'aggregate_sha256': integration.inventory_digest(inventory)}}
    dump(release / 'release-manifest.json', manifest)
    state = root / 'synthetic-state'; state.mkdir(); (state / 'sentinel').write_bytes(b'NEVER_WRITE\n')
    plist = root / 'LaunchAgents/com.lexi.v35.api-only.plist'; plist.parent.mkdir()
    plist.write_bytes(plistlib.dumps({
        'Label': 'com.lexi.v35.api-only', 'WorkingDirectory': str(app),
        'ProgramArguments': ['/usr/bin/env', 'RESEARCH_ONLY=1', 'production_allowed=false',
            'buy_gate_updated=false', 'orders_sent=false', f'V4_MANAGER_RESEARCH_STATE_ROOT={state}',
            f'V35_APP_ROOT={app}', 'V35_RELEASE_ID=G',
            f'V35_RELEASE_MANIFEST_PATH={release / "release-manifest.json"}',
            f'V35_RELEASE_MANIFEST_SHA256={sha((release / "release-manifest.json").read_bytes())}',
            f'V35_API_MODULE_OWNERSHIP_PATH={contract_path}',
            f'V35_API_MODULE_OWNERSHIP_SHA256={sha(contract_path.read_bytes())}',
            f'PYTHONPATH={app / "upstreams"}:{app}', '/usr/bin/python3', '-m', 'apps.api.v35_api.run',
            '--host', '127.0.0.1', '--port', '8873'],
    }, sort_keys=True))
    return {'root': root, 'plist': plist, 'contract': contract_path, 'state': state, 'initial_app': app}


def change_contract(active: dict, update) -> None:
    value = json.loads(active['contract'].read_text()); update(value); dump(active['contract'], value)
    payload = plistlib.loads(active['plist'].read_bytes())
    payload['ProgramArguments'] = [
        f'V35_API_MODULE_OWNERSHIP_SHA256={sha(active["contract"].read_bytes())}'
        if x.startswith('V35_API_MODULE_OWNERSHIP_SHA256=') else x for x in payload['ProgramArguments']]
    active['plist'].write_bytes(plistlib.dumps(payload, sort_keys=True))


def make_delta(active: dict, name: str, module: str, changes: dict[str, bytes | None]) -> tuple[Path, Path]:
    identity = integration.read_active_release(active['plist'])
    source = active['root'] / (name + '-source'); source.mkdir()
    rows = []
    for relative, after in sorted(changes.items()):
        base = Path(identity['app_root']) / relative
        before = base.read_bytes() if base.is_file() else None
        if after is not None:
            target = source / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(after)
        proof, count = integration._diff_proof(before, after) if before is not None and after is not None else (None, None)
        rows.append({'path': relative, 'before_sha256': sha(before) if before is not None else None,
                     'after_sha256': sha(after) if after is not None else None,
                     'unified_diff_sha256': proof, 'unified_diff_hunk_count': count})
    receipt = active['root'] / (name + '-delta.json')
    dump(receipt, {'schema_version': integration.DELTA_SCHEMA_VERSION,
        'base': integration._base_binding(identity), 'entries': rows,
        'business_module': {'module_id': module, 'owner_contract_sha256': sha(active['contract'].read_bytes()),
            'base_generation': identity.get('generation', 0), 'operation': 'forward'}})
    return source, receipt


def build(active: dict, name: str, module: str, changes: dict[str, bytes | None]) -> Path:
    source, receipt = make_delta(active, name, module, changes)
    candidate = active['root'] / name
    builder.build_module_candidate(source_root=source, candidate_root=candidate,
        active_api_plist_path=active['plist'], release_id=name, role='gateway',
        api_integration_delta_receipt_path=receipt, module_id=module,
        formal_release_root=active['root'] / 'unused-formal',
        include_untracked_paths=[p for p in changes if not (Path(integration.read_active_release(active['plist'])['app_root']) / p).exists()])
    return candidate


def synthetic_commit(active: dict, candidate: Path) -> dict:
    """Only an isolated plist is changed; native service seam has separate tests."""
    manifest = candidate / 'release-manifest.json'
    with integration.shared_api_release_lock(active['plist']) as lease:
        proof = integration.verify_api_release_candidate(candidate_root=candidate,
            active_api_plist_path=active['plist'], expected_manifest_sha256=sha(manifest.read_bytes()),
            lock_lease=lease, require_shared_lock=True, require_business_module=True)
        staged = rewrite_api_only_plist(plistlib.loads(active['plist'].read_bytes()),
            candidate_app_root=candidate / 'app', release_id=candidate.name,
            manifest_path=manifest, manifest_sha256=sha(manifest.read_bytes()))
        active['plist'].write_bytes(plistlib.dumps(staged, sort_keys=True))
        integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=active['plist'],
            active_pointer='candidate', lock_lease=lease, require_shared_lock=True, require_business_module=True)
        return proof


def test_gateway_business_receipt_cannot_cross_owner(tmp_path):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'cross', 'alpha', {'modules/beta.py': b'BETA = 9\n'})
    candidate = tmp_path / 'bad'; candidate.mkdir()
    before = active['plist'].read_bytes()
    with pytest.raises(ValueError, match='API_BUSINESS_PATH_OWNER_CONFLICT'):
        integration.build_integrated_app(active_api_plist_path=active['plist'], source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt)
    assert list(candidate.iterdir()) == []
    assert active['plist'].read_bytes() == before


@pytest.mark.parametrize('path', ['shared/registry.py', 'apps/api/v35_api/app.py',
    'apps/web/dist/index.html', 'apps/web/dist/assets/new.js', 'apps/web/vite.config.ts',
    'apps/web/src/contracts/thing.ts', 'config/current.json'])
def test_shared_or_static_change_rejected_before_write(tmp_path, path):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'shared', 'alpha', {path: b'CHANGED\n'})
    candidate = tmp_path / 'bad'; candidate.mkdir()
    with pytest.raises(ValueError, match='API_BUSINESS_SHARED_SEAM'):
        integration.build_integrated_app(active_api_plist_path=active['plist'], source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt,
            explicit_untracked_paths=[path] if not (active['initial_app'] / path).exists() else [])
    assert list(candidate.iterdir()) == []


@pytest.mark.parametrize('damage,code', [
    ('missing_module', 'API_BUSINESS_MODULE_RECEIPT_REQUIRED'),
    ('unknown_module', 'API_BUSINESS_MODULE_UNKNOWN'),
    ('contract_sha', 'API_BUSINESS_OWNER_CONTRACT_SHA_MISMATCH'),
    ('unapproved', 'API_BUSINESS_OWNER_CONTRACT_NOT_APPROVED'),
    ('duplicate_owner', 'API_BUSINESS_PATH_OWNER_DUPLICATE'),
    ('duplicate_route', 'API_BUSINESS_ROUTE_OWNER_DUPLICATE'),
])
def test_owner_binding_negative_cases(tmp_path, damage, code):
    active = setup_active(tmp_path)
    if damage == 'unapproved': change_contract(active, lambda c: c.update(status='PROPOSED'))
    if damage == 'duplicate_owner': change_contract(active, lambda c: c['modules'][1]['paths'].append('modules/alpha.py'))
    if damage == 'duplicate_route': change_contract(active, lambda c: c['modules'][1]['routes'].append({'method': 'GET', 'path': '/alpha'}))
    source, receipt = make_delta(active, 'bad', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    value = json.loads(receipt.read_text())
    if damage == 'missing_module': value.pop('business_module')
    if damage == 'unknown_module': value['business_module']['module_id'] = 'unknown'
    if damage == 'contract_sha': value['business_module']['owner_contract_sha256'] = '0' * 64
    dump(receipt, value)
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    with pytest.raises(ValueError, match=code):
        integration.build_integrated_app(active_api_plist_path=active['plist'], source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt)
    assert list(candidate.iterdir()) == []


@pytest.mark.parametrize('order', [('alpha', 'beta'), ('beta', 'alpha')])
def test_sequential_module_releases_preserve_other_bytes(tmp_path, order):
    active = setup_active(tmp_path)
    for index, module in enumerate(order):
        candidate = build(active, f'release-{module}', module, {f'modules/{module}.py': f'{module.upper()} = 1\n'.encode()})
        synthetic_commit(active, candidate)
        assert integration.read_active_release(active['plist'])['generation'] == index + 1
    app = Path(integration.read_active_release(active['plist'])['app_root'])
    assert (app / 'modules/alpha.py').read_bytes() == b'ALPHA = 1\n'
    assert (app / 'modules/beta.py').read_bytes() == b'BETA = 1\n'
    before = {x['path']: x for x in integration.inventory_tree(active['initial_app'])}
    after = {x['path']: x for x in integration.inventory_tree(app)}
    assert {p: x for p, x in before.items() if not p.startswith('modules/')} == {p: x for p, x in after.items() if not p.startswith('modules/')}
    assert (active['state'] / 'sentinel').read_bytes() == b'NEVER_WRITE\n'


def test_same_base_second_candidate_rejected_then_rebuilt(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    b = build(active, 'B-stale', 'beta', {'modules/beta.py': b'BETA = 1\n'})
    synthetic_commit(active, a)
    current = active['plist'].read_bytes()
    with pytest.raises(ValueError, match='ACTIVE_BASE_CHANGED'):
        synthetic_commit(active, b)
    assert active['plist'].read_bytes() == current
    b2 = build(active, 'B-rebuilt', 'beta', {'modules/beta.py': b'BETA = 1\n'})
    synthetic_commit(active, b2)
    assert (b2 / 'app/modules/alpha.py').read_bytes() == b'ALPHA = 1\n'


def test_unbound_contract_cannot_self_authorize(tmp_path):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'bad', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    payload = plistlib.loads(active['plist'].read_bytes())
    payload['ProgramArguments'] = [s for s in payload['ProgramArguments'] if not s.startswith('V35_API_MODULE_OWNERSHIP_')]
    active['plist'].write_bytes(plistlib.dumps(payload))
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    with pytest.raises(ValueError, match='API_BUSINESS_OWNER_BINDING_REQUIRED'):
        integration.build_integrated_app(active_api_plist_path=active['plist'], source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt)
    assert list(candidate.iterdir()) == []


def prepare_rollback(active, target, name='reverse-A'):
    return integration.prepare_module_rollback(
        active_api_plist_path=active['plist'], target_release_root=target,
        expected_manifest_sha256=sha((target / 'release-manifest.json').read_bytes()),
        output_root=active['root'] / name,
    )


def build_rollback(active, prepared, name='rollback-A'):
    candidate = active['root'] / name
    builder.build_module_candidate(source_root=Path(prepared['source_root']), candidate_root=candidate,
        active_api_plist_path=active['plist'], release_id=name, role='gateway',
        api_integration_delta_receipt_path=Path(prepared['delta_receipt_path']),
        module_id=prepared['module_id'], formal_release_root=active['root'] / 'unused-formal',
        include_untracked_paths=prepared['include_untracked_paths'])
    return candidate


@pytest.mark.parametrize('added', [False, True])
def test_reverse_delta_rolls_back_only_alpha_and_preserves_beta(tmp_path, added):
    active = setup_active(tmp_path)
    changes = {'modules/alpha.py': b'ALPHA = 1\n'}
    if added: changes['modules/alpha_extra.py'] = b'EXTRA = True\n'
    a = build(active, 'A', 'alpha', changes); synthetic_commit(active, a)
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 2\n'}); synthetic_commit(active, b)
    before = integration.inventory_tree(b / 'app')
    prepared = prepare_rollback(active, a)
    reverse = build_rollback(active, prepared); synthetic_commit(active, reverse)
    assert (reverse / 'app/modules/alpha.py').read_bytes() == b'ALPHA = 0\n'
    assert not (reverse / 'app/modules/alpha_extra.py').exists()
    assert (reverse / 'app/modules/beta.py').read_bytes() == b'BETA = 2\n'
    assert [x for x in integration.inventory_tree(reverse / 'app') if not x['path'].startswith('modules/alpha')] == [x for x in before if not x['path'].startswith('modules/alpha')]
    assert integration.read_active_release(active['plist'])['generation'] == 3
    assert (active['state'] / 'sentinel').read_bytes() == b'NEVER_WRITE\n'


def test_later_same_module_release_blocks_old_rollback(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    a2 = build(active, 'A2', 'alpha', {'modules/alpha.py': b'ALPHA = 2\n'}); synthetic_commit(active, a2)
    before = active['plist'].read_bytes()
    with pytest.raises(ValueError, match='API_BUSINESS_ROLLBACK_LATER_MODULE_DEPENDENCY'):
        prepare_rollback(active, a)
    assert active['plist'].read_bytes() == before
    assert not (tmp_path / 'reverse-A').exists()


def test_later_dependent_module_blocks_rollback(tmp_path):
    active = setup_active(tmp_path)
    change_contract(active, lambda c: c['modules'][1].update(depends_on=['alpha']))
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 2\n'}); synthetic_commit(active, b)
    with pytest.raises(ValueError, match='API_BUSINESS_ROLLBACK_LATER_MODULE_DEPENDENCY'):
        prepare_rollback(active, a)


def test_stale_inverse_receipt_refused_after_new_release(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    reverse = prepare_rollback(active, a)
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 2\n'}); synthetic_commit(active, b)
    before = active['plist'].read_bytes()
    with pytest.raises(ValueError, match='API_RELEASE_DELTA_BASE_IDENTITY_MISMATCH'):
        build_rollback(active, reverse)
    assert active['plist'].read_bytes() == before
    assert not (tmp_path / 'rollback-A').exists()


def test_unrelated_target_is_not_a_rollback_ancestor(tmp_path):
    active = setup_active(tmp_path)
    orphan = build(active, 'orphan', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 2\n'}); synthetic_commit(active, b)
    with pytest.raises(ValueError, match='API_BUSINESS_ROLLBACK_TARGET_NOT_ANCESTOR'):
        prepare_rollback(active, orphan)


def test_rollback_output_cannot_write_owner_state(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    with pytest.raises(ValueError, match='API_BUSINESS_OUTPUT_BOUNDARY'):
        integration.prepare_module_rollback(active_api_plist_path=active['plist'], target_release_root=a,
            expected_manifest_sha256=sha((a / 'release-manifest.json').read_bytes()), output_root=active['state'] / 'bad')
    assert list(active['state'].iterdir()) == [active['state'] / 'sentinel']


def test_current_launch_binding_change_rejects_before_commit(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    value = plistlib.loads(active['plist'].read_bytes())
    value['ProgramArguments'].insert(1, 'UNRELATED_CURRENT_BINDING=new')
    active['plist'].write_bytes(plistlib.dumps(value))
    with pytest.raises(ValueError, match='API_BUSINESS_LAUNCH_BINDINGS_CHANGED'):
        synthetic_commit(active, a)


@pytest.mark.parametrize('kind', ['copy', 'manifest', 'plan'])
def test_builder_failure_cleans_candidate_and_preserves_current(tmp_path, monkeypatch, kind):
    active = setup_active(tmp_path)
    before = active['plist'].read_bytes()
    def failure(*args, **kwargs): raise OSError('SYNTHETIC_' + kind)
    if kind == 'copy': monkeypatch.setattr(integration.shutil, 'copytree', failure)
    elif kind == 'manifest': monkeypatch.setattr(builder, '_json_dump', failure)
    else: monkeypatch.setattr(builder, 'render_module_cutover', failure)
    with pytest.raises(OSError, match='SYNTHETIC_'):
        build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    assert active['plist'].read_bytes() == before
    assert not (tmp_path / 'A').exists()
    receipt = json.loads((tmp_path / 'A-failure-receipt.json').read_text())
    assert receipt['status'] == 'FAILED_CLOSED' and receipt['launchctl_called'] is False


def test_original_builder_cli_accepts_business_module_id(tmp_path, capsys):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'cli', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    result = builder.main(['--source-root', str(source), '--candidate-root', str(tmp_path / 'CLI'),
        '--api-plist', str(active['plist']), '--release-id', 'CLI', '--api-module-id', 'alpha',
        '--api-integration-delta-receipt', str(receipt), '--formal-release-root', str(tmp_path / 'formal')])
    assert result == 0
    value = json.loads(capsys.readouterr().out)
    assert value['business_module']['module_id'] == 'alpha'
    assert value['launchctl_called'] is False


@pytest.mark.parametrize('destination', ['candidate', 'receipt'])
def test_business_builder_rejects_state_output_before_any_write(tmp_path, destination):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'boundary', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    candidate = active['state'] / 'A' if destination == 'candidate' else tmp_path / 'A'
    kwargs = {'receipt_path': active['state'] / 'receipt.json'} if destination == 'receipt' else {}
    before = integration.inventory_tree(active['state'])
    with pytest.raises(ValueError, match='API_BUSINESS_OUTPUT_BOUNDARY'):
        builder.build_module_candidate(source_root=source, candidate_root=candidate,
            active_api_plist_path=active['plist'], release_id='A', role='gateway', module_id='alpha',
            api_integration_delta_receipt_path=receipt, formal_release_root=tmp_path / 'formal', **kwargs)
    assert integration.inventory_tree(active['state']) == before
    assert not candidate.exists()


def test_legacy_full_builder_refuses_module_before_candidate_or_state_write(tmp_path):
    import sys
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'legacy', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    with pytest.raises(ValueError, match='API_BUSINESS_MODULE_ENTRY_REQUIRED'):
        builder.build_candidate(source_root=source, candidate_root=tmp_path / 'legacy-candidate',
            api_plist_path=active['plist'], scheduler_plist_path=active['plist'], python=Path(sys.executable),
            release_id='legacy-candidate', api_integration_delta_receipt_path=receipt,
            formal_release_root=tmp_path / 'formal', dependency_names=())
    assert not (tmp_path / 'legacy-candidate').exists()


def test_legacy_cutover_refuses_module_before_state_write(tmp_path):
    from ops.prepare_api_only_cutover import render_cutover
    active = setup_active(tmp_path)
    candidate = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    before = integration.inventory_tree(candidate)
    with pytest.raises(ValueError, match='API_BUSINESS_MODULE_ENTRY_REQUIRED'):
        render_cutover(source_plist_path=active['plist'], candidate_root=candidate, release_id='A',
            manifest_path=candidate / 'release-manifest.json', manifest_sha256=sha((candidate / 'release-manifest.json').read_bytes()),
            source_root=tmp_path / 'A-source', formal_release_root=tmp_path / 'formal', current_manager_state_root=active['state'])
    assert integration.inventory_tree(candidate) == before


def test_service_role_mode_cannot_omit_business_module_id(tmp_path):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'role', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    with pytest.raises(ValueError, match='API_BUSINESS_MODULE_ID_REQUIRED'):
        builder.build_module_candidate(source_root=source, candidate_root=tmp_path / 'A',
            active_api_plist_path=active['plist'], release_id='A', role='gateway',
            api_integration_delta_receipt_path=receipt, formal_release_root=tmp_path / 'formal')
    assert not (tmp_path / 'A').exists()


@pytest.mark.parametrize('damage,code', [
    ('source_symlink', 'SYMLINK'), ('traversal', 'PATH'), ('missing_file', 'alpha.py'),
    ('source_sha', 'SOURCE_SHA_MISMATCH'), ('base_manifest', 'BASE_IDENTITY_MISMATCH'),
    ('base_release', 'BASE_IDENTITY_MISMATCH'), ('generation', 'STALE_GENERATION'),
    ('duplicate_delta', 'DUPLICATE'), ('dependency_cycle', 'API_BUSINESS_DEPENDENCY_CYCLE'),
])
def test_path_manifest_and_dependency_negative_cases(tmp_path, damage, code):
    active = setup_active(tmp_path)
    if damage == 'dependency_cycle':
        change_contract(active, lambda c: (c['modules'][0].update(depends_on=['beta']), c['modules'][1].update(depends_on=['alpha'])))
    source, receipt = make_delta(active, 'negative', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    value = json.loads(receipt.read_text())
    if damage == 'source_symlink':
        (source / 'modules/alpha.py').unlink(); (source / 'modules/alpha.py').symlink_to(active['state'] / 'sentinel')
    if damage == 'traversal': value['entries'][0]['path'] = '../escape.py'
    if damage == 'missing_file': (source / 'modules/alpha.py').unlink()
    if damage == 'source_sha': (source / 'modules/alpha.py').write_bytes(b'UNDECLARED\n')
    if damage == 'base_manifest': value['base']['release_manifest_sha256'] = '0' * 64
    if damage == 'base_release': value['base']['release_id'] = 'OTHER'
    if damage == 'generation': value['business_module']['base_generation'] = 999
    if damage == 'duplicate_delta': value['entries'].append(dict(value['entries'][0]))
    dump(receipt, value)
    candidate = tmp_path / 'negative-candidate'; candidate.mkdir()
    before = active['plist'].read_bytes()
    with pytest.raises((ValueError, FileNotFoundError), match=code):
        integration.build_integrated_app(active_api_plist_path=active['plist'], source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt)
    assert list(candidate.iterdir()) == []
    assert active['plist'].read_bytes() == before
    assert (active['state'] / 'sentinel').read_bytes() == b'NEVER_WRITE\n'


def _process_commit(active, candidate, ready, proceed, results):
    ready.set()
    if not proceed.wait(10): raise RuntimeError('SYNTHETIC_SYNC_TIMEOUT')
    try:
        synthetic_commit(active, candidate)
        results.put(('PASS', candidate.name))
    except ValueError as error:
        results.put(('REFUSED', str(error)))


def test_two_processes_same_base_commit_cannot_overwrite_first_module(tmp_path):
    import multiprocessing
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 1\n'})
    context = multiprocessing.get_context('spawn')
    ready_a, ready_b, go_a, go_b = (context.Event() for _ in range(4))
    results = context.Queue()
    workers = [context.Process(target=_process_commit, args=(active, candidate, ready, go, results))
               for candidate, ready, go in [(a, ready_a, go_a), (b, ready_b, go_b)]]
    try:
        for worker in workers: worker.start()
        assert ready_a.wait(10) and ready_b.wait(10)
        go_a.set(); assert results.get(timeout=10) == ('PASS', 'A')
        current = active['plist'].read_bytes()
        go_b.set(); status, reason = results.get(timeout=10)
        assert status == 'REFUSED' and 'ACTIVE_BASE_CHANGED' in reason
        assert active['plist'].read_bytes() == current
        assert (a / 'app/modules/alpha.py').read_bytes() == b'ALPHA = 1\n'
    finally:
        for worker in workers:
            worker.join(5)
            if worker.is_alive(): worker.terminate(); worker.join(5)
        results.close(); results.join_thread()
    assert all(worker.exitcode == 0 for worker in workers)


def test_forged_inverse_receipt_cannot_choose_arbitrary_module_bytes(tmp_path):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    prepared = prepare_rollback(active, a)
    receipt = Path(prepared['delta_receipt_path']); value = json.loads(receipt.read_text())
    forged = b'ALPHA = 999\n'; (Path(prepared['source_root']) / 'modules/alpha.py').write_bytes(forged)
    value['entries'][0]['after_sha256'] = sha(forged)
    value['entries'][0]['unified_diff_sha256'], value['entries'][0]['unified_diff_hunk_count'] = integration._diff_proof(b'ALPHA = 1\n', forged)
    dump(receipt, value)
    with pytest.raises(ValueError, match='API_BUSINESS_REVERSE_DELTA_MISMATCH'):
        build_rollback(active, prepared)
    assert integration.read_active_release(active['plist'])['release_id'] == 'A'


@pytest.mark.parametrize('destination', ['active_app', 'candidate_app', 'candidate_manifest', 'launch_agents'])
def test_review_receipt_cannot_mutate_active_or_candidate_artifacts(tmp_path, destination):
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'review', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    candidate = tmp_path / 'A'
    output = {
        'active_app': active['initial_app'] / 'unexpected.json',
        'candidate_app': candidate / 'app/modules/beta.py',
        'candidate_manifest': candidate / 'release-manifest.json',
        'launch_agents': active['plist'].parent / 'unexpected.json',
    }[destination]
    initial = integration.inventory_tree(active['initial_app'])
    before = active['plist'].read_bytes()
    with pytest.raises(ValueError, match='API_BUSINESS_(OUTPUT_BOUNDARY|RECEIPT_OVERLAPS_CANDIDATE)'):
        builder.build_module_candidate(source_root=source, candidate_root=candidate, active_api_plist_path=active['plist'],
            release_id='A', role='gateway', module_id='alpha', api_integration_delta_receipt_path=receipt,
            receipt_path=output, formal_release_root=tmp_path / 'formal')
    assert integration.inventory_tree(active['initial_app']) == initial
    assert active['plist'].read_bytes() == before
    assert not candidate.exists()


def _hold_gateway_lock(plist, ready, release):
    with integration.shared_api_release_lock(plist):
        ready.set()
        if not release.wait(10): raise RuntimeError('SYNTHETIC_LOCK_TIMEOUT')


def test_real_process_lock_blocks_builder_before_candidate_write(tmp_path):
    import multiprocessing
    active = setup_active(tmp_path)
    source, receipt = make_delta(active, 'locked', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    worker = context.Process(target=_hold_gateway_lock, args=(active['plist'], ready, release))
    worker.start()
    try:
        assert ready.wait(10)
        with pytest.raises(ValueError, match='API_RELEASE_SHARED_LOCK_BUSY'):
            builder.build_module_candidate(source_root=source, candidate_root=tmp_path / 'A', active_api_plist_path=active['plist'],
                release_id='A', role='gateway', module_id='alpha', api_integration_delta_receipt_path=receipt,
                formal_release_root=tmp_path / 'formal')
        assert not (tmp_path / 'A').exists()
        assert integration.read_active_release(active['plist'])['release_id'] == 'G'
    finally:
        release.set(); worker.join(5)
        if worker.is_alive(): worker.terminate(); worker.join(5)
    assert worker.exitcode == 0


@pytest.mark.parametrize('output', ['reverse', 'candidate', 'receipt'])
def test_review_every_retained_release_is_protected_from_output(tmp_path, output):
    active = setup_active(tmp_path)
    a = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'}); synthetic_commit(active, a)
    b = build(active, 'B', 'beta', {'modules/beta.py': b'BETA = 1\n'}); synthetic_commit(active, b)
    c = build(active, 'C', 'beta', {'modules/beta.py': b'BETA = 2\n'}); synthetic_commit(active, c)
    initial = integration.inventory_tree(b / 'app')
    forbidden = b / 'app/review-output'
    with pytest.raises(ValueError, match='API_BUSINESS_OUTPUT_BOUNDARY'):
        if output == 'reverse':
            integration.prepare_module_rollback(active_api_plist_path=active['plist'], target_release_root=a,
                expected_manifest_sha256=sha((a / 'release-manifest.json').read_bytes()), output_root=forbidden)
        else:
            source, receipt = make_delta(active, 'review-history', 'beta', {'modules/beta.py': b'BETA = 3\n'})
            candidate = forbidden if output == 'candidate' else tmp_path / 'review-output'
            kwargs = {'receipt_path': forbidden} if output == 'receipt' else {}
            builder.build_module_candidate(source_root=source, candidate_root=candidate, active_api_plist_path=active['plist'],
                release_id='review-output', role='gateway', module_id='beta', api_integration_delta_receipt_path=receipt,
                formal_release_root=tmp_path / 'formal', **kwargs)
    assert integration.inventory_tree(b / 'app') == initial
    assert not forbidden.exists()
    assert prepare_rollback(active, a)['status'] == 'READY_FOR_REVIEW'


@pytest.mark.parametrize('key', ['V4_MANAGER_SCREEN_AUTHORITY_ROOT', 'V4_MANAGER_NEWS_OWNER_ROOT',
    'V4_DAILY_REVIEW_ROOT', 'V4_PRESELECTION_SOURCE_ROOT', 'V4_INTRADAY_RESEARCH_ROOT',
    'V4_WECHAT_ARCHIVE_ROOT', 'V4_SECURITY_MASTER_ROOT'])
def test_review_all_external_product_roots_are_protected(tmp_path, key):
    active = setup_active(tmp_path)
    products = tmp_path / 'synthetic-products'; products.mkdir(); (products / 'sentinel').write_bytes(b'UNTOUCHED')
    payload = plistlib.loads(active['plist'].read_bytes())
    payload['ProgramArguments'].insert(1, f'{key}={products}')
    active['plist'].write_bytes(plistlib.dumps(payload))
    source, receipt = make_delta(active, 'products', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    with pytest.raises(ValueError, match='API_BUSINESS_OUTPUT_BOUNDARY'):
        builder.build_module_candidate(source_root=source, candidate_root=products / 'A', active_api_plist_path=active['plist'],
            release_id='A', role='gateway', module_id='alpha', api_integration_delta_receipt_path=receipt,
            formal_release_root=tmp_path / 'formal')
    assert list(products.iterdir()) == [products / 'sentinel']


def test_review_cutover_config_symlink_cannot_write_state(tmp_path):
    import shutil
    from ops.prepare_api_only_cutover import render_module_cutover
    active = setup_active(tmp_path)
    candidate = build(active, 'A', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    shutil.rmtree(candidate / 'config'); (candidate / 'config').symlink_to(active['state'], target_is_directory=True)
    before = integration.inventory_tree(active['state'])
    with pytest.raises(ValueError, match='API_BUSINESS_CONFIG_PATH_SYMLINK_OR_ALIAS'):
        render_module_cutover(source_active_plist_path=active['plist'], candidate_root=candidate,
            release_id='A', manifest_path=candidate / 'release-manifest.json',
            manifest_sha256=sha((candidate / 'release-manifest.json').read_bytes()), role='gateway',
            source_root=tmp_path / 'A-source', module_id='alpha', formal_release_root=tmp_path / 'formal')
    assert integration.inventory_tree(active['state']) == before


def test_declared_external_root_without_plist_env_is_protected(tmp_path):
    active = setup_active(tmp_path)
    products = tmp_path / 'synthetic-default-products'; products.mkdir()
    change_contract(active, lambda c: c.update(protected_external_roots=[str(active['state']), str(products)]))
    source, receipt = make_delta(active, 'defaults', 'alpha', {'modules/alpha.py': b'ALPHA = 1\n'})
    with pytest.raises(ValueError, match='API_BUSINESS_OUTPUT_BOUNDARY'):
        builder.build_module_candidate(source_root=source, candidate_root=products / 'A', active_api_plist_path=active['plist'],
            release_id='A', role='gateway', module_id='alpha', api_integration_delta_receipt_path=receipt,
            formal_release_root=tmp_path / 'formal')
    assert list(products.iterdir()) == []


@pytest.mark.parametrize('shared_path,code', [('shared/*.py', 'API_BUSINESS_SOURCE_PATH_FORBIDDEN'),
    ('shared', 'API_BUSINESS_PATH_OWNER_OVERLAP')])
def test_review_shared_contract_cannot_hide_registry_ownership(tmp_path, shared_path, code):
    active = setup_active(tmp_path)
    def damage(contract):
        contract['shared_paths'][0]['path'] = shared_path
        contract['modules'][0]['paths'].append('shared/registry.py')
    change_contract(active, damage)
    source, receipt = make_delta(active, 'ambiguous-shared', 'alpha', {'shared/registry.py': b'ROUTES = ()\n'})
    before = active['plist'].read_bytes()
    with pytest.raises(ValueError, match=code):
        builder.build_module_candidate(source_root=source, candidate_root=tmp_path / 'A', active_api_plist_path=active['plist'],
            release_id='A', role='gateway', module_id='alpha', api_integration_delta_receipt_path=receipt,
            formal_release_root=tmp_path / 'formal')
    assert not (tmp_path / 'A').exists()
    assert active['plist'].read_bytes() == before
