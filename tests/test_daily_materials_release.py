from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from ops.api_release_integration import validate_api_manifest_shape
from ops.prepare_daily_materials_release import (
    patch_dispatcher, patch_frontend_identity, patch_stage_owner_reader,
    validate_packet_manifest,
)


@pytest.mark.parametrize('candidate', ['bad-old-packet', None, [], 3])
def test_api_admission_rejects_old_candidate_shape(candidate):
    with pytest.raises(ValueError, match='IDENTITY_OR_INVENTORY'):
        validate_api_manifest_shape({'schema_version': 'v4.release_candidate.v1',
                                     'candidate': candidate, 'application_inventory': {}})


def test_main_schema_keeps_string_candidate():
    manifest = {'schema_version': 'v4.runtime_graph_repair_release.v1',
                'candidate': 'main-release', 'app_root': '/release/app',
                'release_id': 'main-release', 'application_inventory': {}}
    validate_packet_manifest(manifest, role='main')
    with pytest.raises(ValueError, match='SCHEMA_UNSUPPORTED'):
        validate_packet_manifest(manifest, role='api')


def _function(source, name, namespace):
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<real-runtime-function>', 'exec'), namespace)
    return namespace[name]


def test_real_runtime_bad_candidate_is_controlled(runtime_source, tmp_path, monkeypatch):
    root = tmp_path / 'release/app'
    root.mkdir(parents=True)
    manifest = {'schema_version': 'v4.release_candidate.v1', 'candidate': 'old-broken-string',
                'application_inventory': {}}
    raw = json.dumps(manifest).encode()
    (root.parent / 'release-manifest.json').write_bytes(raw)
    monkeypatch.setenv('V4_RELEASE_MANIFEST_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('V4_RELEASE_MANIFEST_PATH', str(root.parent / 'release-manifest.json'))
    monkeypatch.setenv('V4_RELEASE_ID', 'test')
    monkeypatch.setenv('V4_APP_ROOT', str(root))
    import os, re
    source = patch_frontend_identity((runtime_source / 'apps/api/v4_api/runtime_graph_router.py').read_text())
    func = _function(source, '_frontend_build_identity', {'Path': Path, 'hashlib': hashlib,
        'json': json, 'os': os, 're': re, '__file__': str(root / 'apps/api/v4_api/runtime_graph_router.py')})
    assert func() == {'status': 'CANNOT_CONFIRM', 'reason': 'API_CANDIDATE_OBJECT_REQUIRED'}
    source = patch_dispatcher((runtime_source / 'infrastructure/scheduling/dispatcher.py').read_text())
    class ReadRoot:
        def __init__(self, path): self.path = path
        def read_bytes(self, name, **kwargs): return (self.path / name).read_bytes()
    func = _function(source, 'validate_release_identity', {'Path': Path, 'hashlib': hashlib,
        'json': json, 'os': os, 're': re, 'SafeRoot': ReadRoot,
        '__file__': str(root / 'infrastructure/scheduling/dispatcher.py')})
    with pytest.raises(ValueError, match='RELEASE_MANIFEST_IDENTITY_MISMATCH'):
        func()


@pytest.fixture
def runtime_source():
    import os
    root = os.environ.get('V4_REPAIR_RUNTIME_FIXTURE')
    if not root:
        pytest.skip('installed runtime fixture is opt-in; synthetic schema regression always runs')
    return Path(root)


def test_stage_patch_preserves_single_day_and_only_one_extra_history(runtime_source):
    import os
    source = (Path(os.environ['V4_REPAIR_STAGE_FIXTURE']) / 'infrastructure/manager_input_attestation.py').read_text()
    patched = patch_stage_owner_reader(source)
    compile(patched, '<patched-owner-reader>', 'exec')
    assert "len(historical) > 4" in patched
    assert "if date == transition['trade_date']" in patched
    assert "manifest_path=binding.get('manifest_path')" in patched
    with pytest.raises(ValueError, match='PREIMAGE_MISMATCH'):
        patch_stage_owner_reader(patched)


def test_stage_authority_locator_retains_sha_and_nofollow(runtime_source, tmp_path):
    import os, re
    source = patch_stage_owner_reader((Path(os.environ['V4_REPAIR_STAGE_FIXTURE']) /
                                      'infrastructure/manager_input_attestation.py').read_text())
    func = _function(source, '_release_manifest', {'Path': Path, 're': re, 'json': json,
        'PublicationError': ValueError, 'digest': lambda raw: hashlib.sha256(raw).hexdigest()})
    app = tmp_path / 'release/app'
    app.mkdir(parents=True)
    data = {'schema_version': 'v4.runtime_graph_repair_release.v1', 'app_root': str(app),
            'release_id': 'main', 'RESEARCH_ONLY': True, 'production_allowed': False,
            'buy_gate_updated': False, 'orders_sent': False,
            'application_inventory': {'entries': [], 'entry_count': 0,
                                     'aggregate_sha256': hashlib.sha256(b'[]').hexdigest()}}
    target = app.parent / 'release-manifest-authority-fixed.json'
    raw = json.dumps(data).encode()
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert func(app, 'main', digest, (), manifest_path=str(target))['release_id'] == 'main'
    with pytest.raises(ValueError, match='SHA_MISMATCH'):
        func(app, 'main', '0' * 64, (), manifest_path=str(target))
    with pytest.raises(ValueError, match='PATH_INVALID'):
        func(app, 'main', digest, (), manifest_path=str(tmp_path / target.name))
    link = app.parent / 'release-manifest-symlink.json'
    link.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        func(app, 'main', digest, (), manifest_path=str(link))


def test_bootstrap_waits_for_old_pid_after_port_is_free(monkeypatch):
    from types import SimpleNamespace
    from ops import activate_daily_materials_release as activation
    remaining = iter([True, True, False])
    waits = []
    monkeypatch.setattr(activation, 'loaded', lambda label: (SimpleNamespace(returncode=1), None))
    monkeypatch.setattr(activation, 'alive', lambda pid: next(remaining))
    monkeypatch.setattr(activation, 'listener_open', lambda: False)
    monkeypatch.setattr(activation.time, 'sleep', lambda delay: waits.append(delay))
    activation.wait_drained('api', [123], api=True)
    assert len(waits) == 2


def test_partial_cutover_restores_whole_tuple_before_any_bootstrap(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ops import activate_daily_materials_release as activation
    backup = tmp_path / 'backup'
    backup.mkdir()
    services = {}
    for index, role in enumerate(('api', 'main', 'stage')):
        old, new = f'old-{role}'.encode(), f'new-{role}'.encode()
        live = tmp_path / (role + '.plist')
        live.write_bytes(new if index == 0 else old)  # failure after API replaced
        (backup / (role + '.plist')).write_bytes(old)
        services[role] = {'label': role, 'live_plist': str(live),
                          'before_sha256': hashlib.sha256(old).hexdigest(),
                          'draft_plist_sha256': hashlib.sha256(new).hexdigest(),
                          'old_app_root': '/old/' + role, 'old_manifest_sha256': role}
    calls = []
    def run(args):
        assert all(Path(service['live_plist']).read_bytes() == ('old-' + role).encode()
                   for role, service in services.items())
        calls.append(args)
        return SimpleNamespace(check_returncode=lambda: None)
    monkeypatch.setattr(activation, 'loaded', lambda label: (SimpleNamespace(returncode=1), None))
    monkeypatch.setattr(activation, 'wait_drained', lambda *a, **k: None)
    monkeypatch.setattr(activation, 'wait_running', lambda *a, **k: None)
    monkeypatch.setattr(activation, 'wait_homepage', lambda *a, **k: [])
    monkeypatch.setattr(activation, 'run', run)
    result = activation.restore_services(services, backup, ['stage', 'main', 'api'])
    assert result['status'] == 'RESTORED_EXACT_PREVIOUS_TUPLE'
    assert len(calls) == 3
    Path(services['stage']['live_plist']).write_bytes(b'concurrent-change')
    with pytest.raises(RuntimeError, match='CONCURRENT_CHANGE_NO_OVERWRITE'):
        activation.restore_services(services, backup, ['stage', 'main', 'api'])
    assert Path(services['stage']['live_plist']).read_bytes() == b'concurrent-change'
