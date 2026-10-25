"""Regression for the observed absent-selector scheduler boundary."""
from types import SimpleNamespace

from ops import materialize_shared_v192_preselection as entry


class StoreError(RuntimeError):
    pass


def _module(*, existing):
    def read(*args, **kwargs):
        if not existing:
            raise StoreError('no latest run for 20261026')
        return SimpleNamespace(run=SimpleNamespace(
            receipt={'status': 'READY'}, verification={'artifact_sha256': 'a' * 64}))

    def materialize(*args, **kwargs):
        raise AssertionError('must not invoke the oracle without an input panel')

    return SimpleNamespace(StoreError=StoreError, read_verified_v192_pool=read,
        materialize_frozen_v192_selector=materialize)


def test_missing_selector_reports_upstream_gap_instead_of_keyerror(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('V35_SHARED_PACKAGE_ROOT', str(tmp_path / 'package'))
    monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT', str(tmp_path / 'store'))
    monkeypatch.delenv('V3_SHARED_SELECTOR_READY_PANEL', raising=False)
    monkeypatch.setattr(entry, 'load_isolated_package_module', lambda *a, **k: _module(existing=False))
    assert entry.main(['--signal-date', '20261023', '--target-date', '20261026']) == 1
    import json
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['failure_class'] == 'UPSTREAM_NOT_READY'
    assert result['reason'] == 'A_V192_EXACT_INPUT_MISSING:selector panel unavailable'
    assert result['production_allowed'] is False
    assert result['orders_sent'] is False
    assert not (tmp_path / 'store').exists()


def test_verified_existing_pool_resumes_without_selector_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('V35_SHARED_PACKAGE_ROOT', str(tmp_path / 'package'))
    monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT', str(tmp_path / 'store'))
    monkeypatch.delenv('V3_SHARED_SELECTOR_READY_PANEL', raising=False)
    monkeypatch.setattr(entry, 'load_isolated_package_module', lambda *a, **k: _module(existing=True))
    assert entry.main(['--signal-date', '20261023', '--target-date', '20261026']) == 0
    import json
    result = json.loads(capsys.readouterr().out)
    assert result['already_exists'] is True
    assert result['artifact_sha256'] == 'a' * 64
    assert not (tmp_path / 'store').exists()


import json
import subprocess
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchRequest, DispatchMode
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry


@pytest.mark.parametrize('root_mode', ['legacy_child', 'runtime', 'unrelated_same_name'])
def test_review_core_bundle_binding_reads_exact_pointer_without_double_nesting(tmp_path, monkeypatch, root_mode):
    runtime = tmp_path / 'runtime'
    configured = runtime / 'review_bundle' if root_mode == 'legacy_child' else runtime
    expected = runtime
    if root_mode == 'unrelated_same_name':
        configured = tmp_path / 'independent' / 'review_bundle'
        expected = configured
    pointer = expected / 'review_bundle' / '20261023' / 'current.json'
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({'trade_date': '20261023', 'run_id': 'exact-date-real-file'}))
    monkeypatch.setenv('V35_REVIEW_CORE_RUNTIME_ROOT', str(runtime))
    monkeypatch.setenv('V35_REVIEW_CORE_BUNDLE_ROOT', str(configured))

    def released_process(command, **kwargs):
        bundle = Path(command[command.index('--bundle-root') + 1])
        actual_pointer = bundle / 'review_bundle' / '20261023' / 'current.json'
        try:
            payload = json.loads(actual_pointer.read_text())
            status = 'READY' if payload['run_id'] == 'exact-date-real-file' else 'CANNOT_CONFIRM'
        except FileNotFoundError:
            status = 'CANNOT_CONFIRM'
        return subprocess.CompletedProcess(command, 0, json.dumps({'status': status}), '')

    registry = FixedExecutorRegistry(data_root=tmp_path / 'data', runner=released_process)
    request = DispatchRequest(scheduled_date='20261023', business_date='20261023',
        target_date='20261026', slot='2115', mode=DispatchMode.LIVE)
    result = registry._review_core_pool_pipeline(request)
    assert result['pipeline_status'] == 'READY'
    assert pointer.read_text() == json.dumps({'trade_date': '20261023', 'run_id': 'exact-date-real-file'})
