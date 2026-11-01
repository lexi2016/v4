import contextlib
import importlib.util
import json
from pathlib import Path
import plistlib

import pytest


PATH = Path(__file__).resolve().parents[1] / 'ops/junda_single_release.py'
SPEC = importlib.util.spec_from_file_location('junda_single_release', PATH)
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)


def test_plist_preserves_unrelated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(operator, 'TARGET', tmp_path / 'candidate')
    original = {'Label': 'com.lexi.v4.api', 'WorkingDirectory': '/old/app',
                'ProgramArguments': ['/exact/live/python', '-m', 'server'],
                'EnvironmentVariables': {'EXISTING_OTHER_OWNER': 'kept', 'V4_APP_ROOT': '/old/app'}}
    stage = {'new_binding': {'sha256': 'a' * 64}}
    result = operator.staged_payload(plistlib.dumps(original), 'b' * 64, stage)
    operator.validate_payload_delta(original, result, 'b' * 64, stage)
    assert result['ProgramArguments'] == original['ProgramArguments']
    assert result['EnvironmentVariables']['EXISTING_OTHER_OWNER'] == 'kept'
    result['EnvironmentVariables']['EXISTING_OTHER_OWNER'] = 'overwritten'
    with pytest.raises(ValueError, match='PLIST_UNLISTED_CHANGE'):
        operator.validate_payload_delta(original, result, 'b' * 64, stage)


def test_allowlist_rejects_unreviewed_asset_change(tmp_path):
    old = tmp_path / 'old.json'
    new = tmp_path / 'new.json'
    old.write_text(json.dumps({'files': [{'path': 'workbench.html', 'sha256': 'old'},
                                         {'path': 'other.js', 'sha256': 'keep'}]}))
    new.write_text(json.dumps({'files': [{'path': 'workbench.html', 'sha256': 'new'},
                                         {'path': 'other.js', 'sha256': 'keep'}]}))
    stage = {'old_asset_manifest': {'path': str(old)}, 'new_asset_manifest': {'path': str(new)},
             'changes': [{'kind': 'site', 'path': 'workbench.html', 'after': {'sha256': 'new'}}]}
    operator.check_allowlist(stage)
    new.write_text(json.dumps({'files': [{'path': 'workbench.html', 'sha256': 'new'},
                                         {'path': 'other.js', 'sha256': 'changed'}]}))
    with pytest.raises(ValueError, match='ASSET_MANIFEST_DELTA_INVALID'):
        operator.check_allowlist(stage)


def test_rollback_refuses_restarted_service_before_unload(monkeypatch, tmp_path):
    old, new = b'previous plist', b'candidate plist'
    plist = tmp_path / 'active.plist'
    backup = tmp_path / 'backup.plist'
    staged = tmp_path / 'staged.plist'
    receipt_path = tmp_path / 'preparation.json'
    activation_path = tmp_path / 'activation.json'
    plist.write_bytes(new)
    backup.write_bytes(old)
    staged.write_bytes(new)
    receipt = {'status': 'PREPARED_NOT_ACTIVATED', 'smoke': {'status': 'PASS'},
               'candidate_plist_sha256': operator.sha(new)}
    receipt_path.write_text(json.dumps(receipt))
    activation_path.write_text(json.dumps({'candidate_plist_sha256': operator.sha(new),
                                           'process': {'pid': 101, 'start_and_command': 'original start'}}))
    for key, value in {'PLIST': plist, 'BACKUP': backup, 'STAGED_PLIST': staged,
                       'RECEIPT': receipt_path, 'ACTIVE_RECEIPT': activation_path}.items():
        monkeypatch.setattr(operator, key, value)
    monkeypatch.setattr(operator, 'release_lock', lambda: contextlib.nullcontext())
    monkeypatch.setattr(operator, 'load_stage', lambda: ({}, {}, {}))
    monkeypatch.setattr(operator, 'live_process', lambda: {'pid': 202, 'start_and_command': 'restarted'})
    called = []
    monkeypatch.setattr(operator, 'unload', lambda: called.append(True))
    with pytest.raises(ValueError, match='ACTIVE_PROCESS_CAS_CHANGED'):
        operator.switch(receipt_sha=operator.file_sha(receipt_path), rollback=True,
                        activation_sha=operator.file_sha(activation_path))
    assert called == []
    assert plist.read_bytes() == new


def test_switch_rejects_changed_plist_and_changed_pid():
    process = {'pid': 1, 'start_and_command': 'one'}
    with pytest.raises(ValueError, match='ACTIVE_PLIST_CAS_CHANGED'):
        operator.assert_switch_identity(current_plist_sha='different', expected_plist_sha='expected',
                                        current_process=process, expected_process=process)
    with pytest.raises(ValueError, match='ACTIVE_PROCESS_CAS_CHANGED'):
        operator.assert_switch_identity(current_plist_sha='same', expected_plist_sha='same',
                                        current_process={'pid': 2}, expected_process=process)


@pytest.fixture
def transaction(monkeypatch, tmp_path):
    old_process = {'pid': 101, 'start_and_command': 'old process'}
    new_process = {'pid': 202, 'start_and_command': 'candidate process'}
    old = plistlib.dumps({'EnvironmentVariables': {'V4_RELEASE_ID': 'old', 'V4_RELEASE_MANIFEST_SHA256': 'a' * 64, 'V4_APP_ROOT': '/old/app'}})
    new = plistlib.dumps({'EnvironmentVariables': {'V4_RELEASE_ID': 'candidate', 'V4_RELEASE_MANIFEST_SHA256': 'b' * 64, 'V4_APP_ROOT': '/candidate/app'}})
    files = {'PLIST': tmp_path / 'active.plist', 'BACKUP': tmp_path / 'backup.plist',
             'STAGED_PLIST': tmp_path / 'staged.plist', 'RECEIPT': tmp_path / 'preparation.json',
             'ACTIVE_RECEIPT': tmp_path / 'activation.json', 'ATTEMPT': tmp_path / 'attempt.json', 'TARGET': tmp_path}
    for key, value in files.items():
        monkeypatch.setattr(operator, key, value)
    files['PLIST'].write_bytes(old)
    files['BACKUP'].write_bytes(old)
    files['STAGED_PLIST'].write_bytes(new)
    monkeypatch.setattr(operator, 'PLIST_SHA', operator.sha(old))
    monkeypatch.setattr(operator, 'BASE_MANIFEST_SHA', 'a' * 64)
    monkeypatch.setattr(operator, 'STAGE_SHA', 'c' * 64)
    monkeypatch.setattr(operator, 'POINTERS', {})
    receipt = {'status': 'PREPARED_NOT_ACTIVATED', 'smoke': {'status': 'PASS'},
               'candidate_plist_sha256': operator.sha(new), 'manifest_sha256': 'b' * 64,
               'base_process': old_process, 'base_live': {'pool_rows_sha256': 'pool'}}
    files['RECEIPT'].write_text(json.dumps(receipt))
    monkeypatch.setattr(operator, 'release_lock', lambda: contextlib.nullcontext())
    monkeypatch.setattr(operator, 'load_stage', lambda: ({}, {}, {}))
    monkeypatch.setattr(operator, 'verify_candidate', lambda *args, **kwargs: None)
    monkeypatch.setattr(operator, 'verify_http', lambda *args, **kwargs: {'pool_rows_sha256': 'pool'})
    monkeypatch.setattr(operator, 'assert_live_root', lambda *args, **kwargs: None)
    return files, receipt, old, new, old_process, new_process


def test_unload_timeout_after_job_stopped_restores_previous(monkeypatch, transaction):
    files, _, old, _, old_process, _ = transaction
    monkeypatch.setattr(operator, 'live_process', lambda: old_process)
    stopped = []
    def failed_unload():
        stopped.append(True)
        raise RuntimeError('UNLOAD_OR_LISTENER_TIMEOUT')
    monkeypatch.setattr(operator, 'unload', failed_unload)
    monkeypatch.setattr(operator, 'service_state', lambda: ('stopped', None))
    restored = []
    def bootstrap(raw, *, single, **kwargs):
        restored.append(raw)
        return old_process, {'pool_rows_sha256': 'pool'}
    monkeypatch.setattr(operator, 'bootstrap_validate', bootstrap)
    with pytest.raises(RuntimeError, match='AUTOMATIC_ROLLBACK_VERIFIED'):
        operator.switch(receipt_sha=operator.file_sha(files['RECEIPT']))
    assert stopped == [True] and restored == [old] and files['PLIST'].read_bytes() == old
    journal = json.loads(files['ATTEMPT'].read_text())
    assert journal['status'] == 'BEFORE_UNLOAD' and journal['before_process'] == old_process


@pytest.mark.parametrize('drift', ['pid', 'plist'])
def test_drift_during_http_check_never_unloads(monkeypatch, transaction, drift):
    files, _, _, _, old_process, _ = transaction
    state = {'process': old_process}
    monkeypatch.setattr(operator, 'live_process', lambda: state['process'])
    def verify_then_drift(*args, **kwargs):
        if drift == 'pid':
            state['process'] = {'pid': 303, 'start_and_command': 'new owner'}
        else:
            files['PLIST'].write_bytes(b'external plist')
        return {'pool_rows_sha256': 'pool'}
    monkeypatch.setattr(operator, 'verify_http', verify_then_drift)
    called = []
    monkeypatch.setattr(operator, 'unload', lambda: called.append(True))
    with pytest.raises(ValueError, match='ACTIVE_PROCESS_CAS_CHANGED|ACTIVE_PLIST_CAS_CHANGED'):
        operator.switch(receipt_sha=operator.file_sha(files['RECEIPT']))
    assert called == []


def make_interrupted_attempt(files, receipt, old_process, new_process):
    value = {'schema': 'junda_single_activation_attempt.v1', 'status': 'CANDIDATE_PROCESS_CAPTURED',
             'preparation_sha256': operator.file_sha(files['RECEIPT']), 'stage_sha256': operator.STAGE_SHA,
             'before_plist_sha256': operator.PLIST_SHA, 'candidate_plist_sha256': receipt['candidate_plist_sha256'],
             'before_plist_path': str(files['BACKUP']), 'candidate_plist_path': str(files['STAGED_PLIST']),
             'before_manifest_sha256': operator.BASE_MANIFEST_SHA, 'candidate_manifest_sha256': receipt['manifest_sha256'],
             'before_process': old_process, 'candidate_process': new_process}
    files['ATTEMPT'].write_text(json.dumps(value))


def test_recover_health_verified_candidate_without_activation_receipt(monkeypatch, transaction):
    files, receipt, old, new, old_process, new_process = transaction
    files['PLIST'].write_bytes(new)
    make_interrupted_attempt(files, receipt, old_process, new_process)
    state = {'running': True}
    monkeypatch.setattr(operator, 'service_state', lambda: ('running', new_process) if state['running'] else ('stopped', None))
    monkeypatch.setattr(operator, 'unload', lambda: state.update(running=False))
    monkeypatch.setattr(operator, 'atomic_plist', lambda raw: files['PLIST'].write_bytes(raw))
    monkeypatch.setattr(operator, 'bootstrap_validate', lambda raw, **kw: (old_process, {'pool_rows_sha256': 'pool'}))
    operator.recover_interrupted(receipt_sha=operator.file_sha(files['RECEIPT']), attempt_sha=operator.file_sha(files['ATTEMPT']))
    assert files['PLIST'].read_bytes() == old
    assert json.loads((files['TARGET'] / 'interrupted-recovery.json').read_text())['status'] == 'INTERRUPTED_ACTIVATION_ROLLED_BACK'


@pytest.mark.parametrize('drift', ['pid', 'plist'])
def test_recover_refuses_external_change_before_unload(monkeypatch, transaction, drift):
    files, receipt, _, new, old_process, new_process = transaction
    files['PLIST'].write_bytes(new if drift == 'pid' else b'external plist')
    make_interrupted_attempt(files, receipt, old_process, new_process)
    observed = {'pid': 303, 'start_and_command': 'someone else'} if drift == 'pid' else new_process
    monkeypatch.setattr(operator, 'service_state', lambda: ('running', observed))
    called = []
    monkeypatch.setattr(operator, 'unload', lambda: called.append(True))
    before = files['PLIST'].read_bytes()
    with pytest.raises(ValueError, match='RECOVERY_CANDIDATE_PROCESS_CHANGED|RECOVERY_PLIST_CAS_CONFLICT'):
        operator.recover_interrupted(receipt_sha=operator.file_sha(files['RECEIPT']), attempt_sha=operator.file_sha(files['ATTEMPT']))
    assert called == [] and files['PLIST'].read_bytes() == before
