from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import prepare_top200_scope_release as release


def _main():
    return {'ProgramArguments': ['/bin/bash', '/same/app/ops/launch.sh'], 'WorkingDirectory': '/same/app',
            'EnvironmentVariables': {'V4_APP_ROOT': '/same/app', 'V4_RELEASE_ID': 'same',
                                     'V4_RESEARCH_RETENTION_POLICY': '/old/policy.json',
                                     'V4_RESEARCH_RETENTION_POLICY_SHA256': 'old'}}


def test_main_allows_only_two_policy_environment_references():
    before = _main()
    after = deepcopy(before)
    after['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY='/new/policy.json',
                                        V4_RESEARCH_RETENTION_POLICY_SHA256='new')
    release.assert_main_policy_only(before, after)
    after['ProgramArguments'] = ['/bin/bash', '/other/entry.sh']
    with pytest.raises(ValueError, match='MAIN_CHANGE_OUTSIDE_TWO_POLICY_REFERENCES'):
        release.assert_main_policy_only(before, after)


@pytest.mark.parametrize('name', ['V4_APP_ROOT', 'V4_RELEASE_ID'])
def test_main_identity_environment_cannot_change(name):
    before = _main()
    after = deepcopy(before)
    after['EnvironmentVariables'][name] = 'different'
    with pytest.raises(ValueError, match='MAIN_CHANGE_OUTSIDE_TWO_POLICY_REFERENCES'):
        release.assert_main_policy_only(before, after)


def _fixture(tmp_path, monkeypatch, *, busy=False, fail_bootstrap=False):
    services = {}
    old_bytes = {}
    for role in ('api', 'main'):
        live, draft = tmp_path / (role + '.plist'), tmp_path / (role + '-new.plist')
        old_bytes[role] = ('old-' + role).encode()
        live.write_bytes(old_bytes[role])
        draft.write_bytes(('new-' + role).encode())
        services[role] = dict(label='com.lexi.v4.' + role, live_plist=str(live),
            before_sha256=release.sha(live), draft_plist=str(draft), draft_plist_sha256=release.sha(draft),
            old_app_root='/old/' + role, app_root='/new/api' if role == 'api' else '/old/main',
            old_manifest_sha256='old-' + role, manifest_sha256='new-api' if role == 'api' else 'old-main')
    stage = tmp_path / 'stage.plist'
    stage.write_bytes(b'stage-untouched')
    locks = tmp_path / 'locks'
    locks.mkdir()
    packet_path = tmp_path / 'PACKET.json'
    packet_path.write_text(json.dumps(dict(services=services, scheduler_lane_lock_root=str(locks))))
    review = tmp_path / 'review.json'
    review.write_text(json.dumps(dict(verdict='PASS', packet_sha256=release.sha(packet_path))))
    def validate(*args, **kwargs):
        assert stage.read_bytes() == b'stage-untouched'
        return {'status': 'TEST_ONLY_VALIDATION'}
    monkeypatch.setattr(release, 'validate', validate)
    monkeypatch.setattr(release, 'loaded_environment_check', lambda service: 100)
    monkeypatch.setattr(release, 'exact_homepage', lambda *a, **k: {})
    monkeypatch.setattr(release.service_ops, 'loaded', lambda label: (
        SimpleNamespace(returncode=0, stdout='state = running\n/old/api old-api /old/main old-main'), 100))
    monkeypatch.setattr(release.service_ops, 'descendants', lambda pid: [100, 200] if busy else [100])
    monkeypatch.setattr(release.service_ops, 'wait_drained', lambda *a, **k: None)
    monkeypatch.setattr(release.service_ops, 'wait_running', lambda *a, **k: 100)
    monkeypatch.setattr(release.service_ops, 'wait_homepage', lambda: [])
    calls = []
    failed = False
    def run(args):
        nonlocal failed
        assert all('stage' not in arg for arg in args)
        calls.append(args)
        if fail_bootstrap and args[1] == 'bootstrap' and not failed:
            failed = True
            return SimpleNamespace(check_returncode=lambda: (_ for _ in ()).throw(RuntimeError('bootstrap-test-failure')))
        return SimpleNamespace(check_returncode=lambda: None)
    monkeypatch.setattr(release.service_ops, 'run', run)
    return packet_path, review, services, stage, calls, old_bytes


def test_two_service_cutover_never_controls_or_changes_stage(tmp_path, monkeypatch):
    packet, review, services, stage, calls, _ = _fixture(tmp_path, monkeypatch)
    state = release.cutover(packet, review)
    assert state['status'] == 'ACTIVATED_API_AND_SAME_IDENTITY_MAIN_STAGE_UNCHANGED'
    assert len(calls) == 4
    assert stage.read_bytes() == b'stage-untouched'
    assert all(Path(s['live_plist']).read_bytes() == Path(s['draft_plist']).read_bytes() for s in services.values())


def test_busy_main_refuses_before_any_service_operation(tmp_path, monkeypatch):
    packet, review, services, stage, calls, old = _fixture(tmp_path, monkeypatch, busy=True)
    with pytest.raises(RuntimeError, match='MAIN_NOT_IDLE_OR_ACTIVE_CHILDREN'):
        release.cutover(packet, review)
    assert calls == []
    assert all(Path(s['live_plist']).read_bytes() == old[role] for role, s in services.items())


def test_failed_bootstrap_restores_only_api_and_main_and_keeps_stage(tmp_path, monkeypatch):
    packet, review, services, stage, calls, old = _fixture(tmp_path, monkeypatch, fail_bootstrap=True)
    with pytest.raises(RuntimeError, match='bootstrap-test-failure'):
        release.cutover(packet, review)
    assert all(Path(s['live_plist']).read_bytes() == old[role] for role, s in services.items())
    assert stage.read_bytes() == b'stage-untouched'
    state = json.loads((tmp_path / 'ACTIVATION_RECEIPT.json').read_text())
    assert state['recovery']['status'] == 'RESTORED_EXACT_PREVIOUS_TUPLE'
