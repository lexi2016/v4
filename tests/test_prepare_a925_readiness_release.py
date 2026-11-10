from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import prepare_a925_readiness_release as release


def test_stage_locator_migrates_own_upstreams_and_preserves_external_dependency():
    baseline = dict(WorkingDirectory='/old/stage', ProgramArguments=['python', '-B',
        '/old/stage/ops/run_stage_center_nodes.py', '--config', '/old/stage/stage_center_tick_config.json'],
        EnvironmentVariables=dict(PYTHONPATH='/old/stage/upstreams:/fixed/shared/app',
                                 STAGE_CENTER_CONFIG='/old/stage/stage_center_tick_config.json'))
    service = dict(baseline_payload=baseline, old_app_root='/old/stage', app_root='/new/stage',
                   release_id='new-stage', manifest='/new/manifest.json', manifest_sha256='new-sha')
    result = release.expected_plist(service, 'stage')
    assert result['EnvironmentVariables']['PYTHONPATH'] == '/new/stage/upstreams:/fixed/shared/app'
    assert result['ProgramArguments'][2] == '/new/stage/ops/run_stage_center_nodes.py'
    assert result['ProgramArguments'][4] == '/new/stage/stage_center_tick_config.json'
    assert baseline['EnvironmentVariables']['PYTHONPATH'] == '/old/stage/upstreams:/fixed/shared/app'


def test_pin_migration_changes_only_exact_stage_api_dependencies(tmp_path):
    old = tmp_path / 'old-api'
    new = tmp_path / 'new-api'
    old.mkdir()
    new.mkdir()
    (old / 'reader.py').write_text('old')
    (new / 'reader.py').write_text('new')
    services = {'main': {'live_plist': '/main.plist'},
        'api': dict(live_plist='/api.plist', draft_plist_sha256='new-api',
                    old_app_root=str(old), app_root=str(new)),
        'stage': dict(live_plist='/stage.plist', draft_plist_sha256='new-stage',
                      old_app_root='/stage-old', app_root='/stage-new')}
    pins = {'pins': [{'path': '/protected/history', 'kind': 'managed_path'}],
        'expected_main_app_root': '/same-main', 'source_bindings': [
            {'path': '/api.plist', 'sha256': 'old-api'},
            {'path': '/stage.plist', 'sha256': 'old-stage'},
            {'path': str(old / 'reader.py'), 'sha256': release.sha(old / 'reader.py')},
            {'path': '/unrelated', 'sha256': 'unchanged'}]}
    before = deepcopy(pins)
    result = release.migrated_pins(pins, services)
    assert pins == before
    assert result['pins'] == pins['pins']
    assert result['expected_main_app_root'] == '/same-main'
    assert result['source_bindings'] == [
        {'path': '/api.plist', 'sha256': 'new-api'},
        {'path': '/stage.plist', 'sha256': 'new-stage'},
        {'path': str(new / 'reader.py'), 'sha256': release.sha(new / 'reader.py')},
        {'path': '/unrelated', 'sha256': 'unchanged'}]
    pins['source_bindings'].append({'path': '/main.plist', 'sha256': 'cycle'})
    with pytest.raises(ValueError, match='MAIN_PLIST_REVERSE_PIN_CYCLE'):
        release.migrated_pins(pins, services)


def fixture(tmp_path, monkeypatch, *, stage_running=False, bootstrap_failure=False):
    services = {}
    for role, label in release.LABELS.items():
        live = tmp_path / (role + '.plist')
        draft = tmp_path / (role + '-candidate.plist')
        live.write_text('before-' + role)
        draft.write_text('after-' + role)
        services[role] = dict(label=label, live_plist=str(live), draft_plist=str(draft),
            before_sha256=release.sha(live), draft_plist_sha256=release.sha(draft),
            old_app_root='/old/' + role, app_root='/new/' + role if role != 'main' else '/old/main',
            old_manifest_sha256='old-' + role, manifest_sha256='new-' + role if role != 'main' else 'old-main')
    lock_root = tmp_path / 'locks'
    lock_root.mkdir()
    packet = tmp_path / 'PACKET.json'
    packet.write_text(json.dumps(dict(services=services, control_roles=['api', 'main', 'stage'],
                                     scheduler_lane_lock_root=str(lock_root))))
    review = tmp_path / 'REVIEW.json'
    review.write_text(json.dumps(dict(verdict='PASS', packet_sha256=release.sha(packet))))
    monkeypatch.setattr(release, 'validate', lambda *a, **k: {})
    monkeypatch.setattr(release, 'exact_homepage', lambda *a, **k: {})
    monkeypatch.setattr(release, 'loaded_environment_check', lambda s: 100)
    monkeypatch.setattr(release, 'stage_loaded_environment', lambda s: None)
    monkeypatch.setattr(release.svc, 'wait_drained', lambda *a, **k: None)
    monkeypatch.setattr(release.svc, 'wait_running', lambda *a, **k: None)
    monkeypatch.setattr(release.svc, 'wait_homepage', lambda: [])
    monkeypatch.setattr(release.svc, 'descendants', lambda pid: [pid] if pid else [])
    def loaded(label):
        role = next(k for k, value in release.LABELS.items() if value == label)
        running = role != 'stage' or stage_running
        state = 'running' if running else 'not running'
        return SimpleNamespace(returncode=0, stdout=f'state = {state}\n/old/{role} old-{role}'), 100 if running else None
    monkeypatch.setattr(release.svc, 'loaded', loaded)
    calls = []
    failed = False
    def run(args):
        nonlocal failed
        calls.append(args)
        if bootstrap_failure and args[1] == 'bootstrap' and not failed:
            failed = True
            return SimpleNamespace(check_returncode=lambda: (_ for _ in ()).throw(RuntimeError('bootstrap-failure')))
        return SimpleNamespace(check_returncode=lambda: None)
    monkeypatch.setattr(release.svc, 'run', run)
    return packet, review, services, calls


def test_running_stage_is_never_stopped_for_install(tmp_path, monkeypatch):
    packet, review, services, calls = fixture(tmp_path, monkeypatch, stage_running=True)
    with pytest.raises(RuntimeError, match='STAGE_NOT_CALENDAR_IDLE_NO_CUTOVER'):
        release.cutover(packet, review)
    assert calls == []
    assert all(Path(s['live_plist']).read_text() == 'before-' + r for r, s in services.items())


def test_busy_main_is_never_stopped_for_install(tmp_path, monkeypatch):
    packet, review, services, calls = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(release.svc, 'descendants', lambda pid: [pid, 200])
    with pytest.raises(RuntimeError, match='MAIN_NOT_IDLE_OR_ACTIVE_CHILDREN'):
        release.cutover(packet, review)
    assert calls == []
    assert all(Path(s['live_plist']).read_text() == 'before-' + r for r, s in services.items())


def test_idle_three_service_install_uses_one_complete_tuple(tmp_path, monkeypatch):
    packet, review, services, calls = fixture(tmp_path, monkeypatch)
    result = release.cutover(packet, review)
    assert result['status'] == 'ACTIVATED_STAGE_CONSUMERS_MAIN_IDENTITY_PRESERVED'
    assert [call[1] for call in calls] == ['bootout'] * 3 + ['bootstrap'] * 3
    assert all(Path(s['live_plist']).read_bytes() == Path(s['draft_plist']).read_bytes() for s in services.values())


def test_bootstrap_failure_restores_original_complete_tuple(tmp_path, monkeypatch):
    packet, review, services, calls = fixture(tmp_path, monkeypatch, bootstrap_failure=True)
    with pytest.raises(RuntimeError, match='bootstrap-failure'):
        release.cutover(packet, review)
    assert all(Path(s['live_plist']).read_text() == 'before-' + role for role, s in services.items())
    receipt = json.loads((tmp_path / 'ACTIVATION_RECEIPT.json').read_text())
    assert receipt['recovery']['status'] == 'RESTORED_EXACT_PREVIOUS_TUPLE'
    assert receipt['business_data_written'] is False
