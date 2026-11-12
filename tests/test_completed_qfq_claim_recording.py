"""Isolated original Registry.save completion; no production script execution."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from ops import research_storage_governance as g

SOURCE = Path(__file__).parents[1] / 'docs/handoffs/daily_delta_panel_20261111/finalize_completed_qfq_claim_r4.py'
spec = importlib.util.spec_from_file_location('completion_fixture', SOURCE)
script = importlib.util.module_from_spec(spec); spec.loader.exec_module(script)


def fixture(tmp_path):
    root = tmp_path / 'registry'; root.mkdir()
    directory = tmp_path / 'run'; directory.mkdir()
    config = g.configuration(dict(data_root=str(tmp_path), run_root=str(directory),
        governance=dict(enabled=True, pool_id='fixture', pool_identity_verified=True, registry_root=str(root))))
    registry = g.Registry(config, tmp_path)
    row = dict(state='RUNNING', owner=dict(pid=999999999, started='dead fixture'), token='original-token',
        attempts=1, directory=str(directory), reserved_bytes=1024, written_bytes=12,
        logical_written_bytes=21, category='ordinary', billing_paths=['original-path'], heartbeat=0)
    state = registry.read(); state['tasks']['original-key'] = row; registry.save(state)
    pointers = {}; policy = dict(pointers={})
    paths = []
    for role in ('selector', 'backtest'):
        path = tmp_path / (role + '.parquet'); path.write_bytes(role.encode()); paths.append(path)
        pointer = tmp_path / (role + '.txt'); pointer.write_text(str(path) + '\n')
        pointers[role] = pointer.read_text(); policy['pointers'][role] = str(pointer)
    ref = directory / 'receipt.json'; ref.write_text('{}')
    summary = dict(status='READY', complete_owner_receipt=dict(path=str(ref), sha256=g.digest(ref)),
                   ready_owner_receipt=dict(path=str(ref), sha256=g.digest(ref)))
    plan = dict(key='original-key', expected_registry_sha256=g.digest(registry.path),
        expected_task_sha256=script.canonical(registry.read()['tasks']['original-key']),
        expected_token=row['token'], expected_attempts=1, expected_owner=row['owner'],
        directory=row['directory'], predicted=1024)
    return registry, policy, plan, summary, g.artifact_records(paths), pointers


def test_exact_completed_recording_keeps_original_owner_attempt_and_bytes(tmp_path):
    registry, policy, plan, summary, records, pointers = fixture(tmp_path)
    original = copy.deepcopy(registry.read()['tasks'][plan['key']])
    with registry.writer():
        script.record_completion(g, registry, policy, plan, summary, records, pointers, {'path': 'operator-proof', 'sha256': 'proof'})
    row = registry.read()['tasks'][plan['key']]
    assert row['state'] == 'READY' and row['reserved_bytes'] == row['written_bytes'] == 0
    for key in ('owner', 'token', 'attempts', 'logical_written_bytes', 'billing_paths'):
        assert row[key] == original[key]
    assert row['result'] == summary and row['artifacts'] == records
    assert row['completion_reconciliation']['path'] == 'operator-proof'


@pytest.mark.parametrize('drift', ['registry', 'token', 'task', 'pointer', 'receipt', 'artifact', 'UNKNOWN'])
def test_exact_completion_denials_leave_registry_bytes_unchanged(tmp_path, monkeypatch, drift):
    registry, policy, plan, summary, records, pointers = fixture(tmp_path)
    before = registry.path.read_bytes()
    if drift == 'registry': plan['expected_registry_sha256'] = 'wrong'
    elif drift == 'token': plan['expected_token'] = 'wrong'
    elif drift == 'task': plan['expected_task_sha256'] = 'wrong'
    elif drift == 'pointer': Path(policy['pointers']['selector']).write_text('wrong')
    elif drift == 'receipt': Path(summary['complete_owner_receipt']['path']).write_text('changed')
    elif drift == 'artifact': Path(records[0]['path']).write_bytes(b'changed')
    elif drift == 'UNKNOWN': monkeypatch.setattr(g, 'owner_state', lambda owner: 'UNKNOWN')
    with registry.writer(), pytest.raises((RuntimeError, g.RetentionError)):
        script.record_completion(g, registry, policy, plan, summary, records, pointers, {})
    assert registry.path.read_bytes() == before


def test_registry_save_failure_preserves_original_durable_running_row(tmp_path, monkeypatch):
    registry, policy, plan, summary, records, pointers = fixture(tmp_path)
    before = registry.path.read_bytes()
    def failed_save(state): raise OSError('fixture write refusal')
    monkeypatch.setattr(registry, 'save', failed_save)
    with registry.writer(), pytest.raises(OSError):
        script.record_completion(g, registry, policy, plan, summary, records, pointers, {})
    assert registry.path.read_bytes() == before
