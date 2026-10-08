from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from types import ModuleType
from pathlib import Path

import pytest

from ops import run_v35_macos_scheduler_daemon as daemon

APP_ROOT = Path('/Users/lexi/Desktop/学习/v4_app')
SUPERVISOR_TEST = APP_ROOT / 'tests/test_manager_announcement_supervisor.py'


def _fixture_helpers():
    spec = importlib.util.spec_from_file_location('d1_supervisor_fixture_helpers', SUPERVISOR_TEST)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _refresh_canary_pins(fixture, canary):
    path = fixture['canary_path']
    raw = json.dumps(canary, sort_keys=True).encode()
    path.write_bytes(raw)
    sha = _sha(raw)
    fixture['binding']['plan_activation_receipt']['sha256'] = sha
    fixture['binding_path'].write_text(json.dumps(fixture['binding'], sort_keys=True), encoding='utf-8')
    fixture['environment'][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV] = sha


def _same_root_fixture(tmp_path, monkeypatch):
    helpers = _fixture_helpers()
    binding, _ = helpers._plan_only_binding(tmp_path, same_owner_root=True)
    # The pinned test venv's bin directory is a symlink into a shared runtime;
    # the production daemon intentionally rejects symlinked parent directories.
    exact_python = Path(binding['python']).resolve(strict=True)
    binding['python'] = str(exact_python)
    binding['python_resolved'] = str(exact_python)
    binding['python_sha256'] = _sha(exact_python.read_bytes())
    canary_path = Path(binding['plan_activation_receipt']['path'])
    binding_path = tmp_path / 'plan-binding.json'
    environment = {
        daemon.ANNOUNCEMENT_BINDING_ENV: str(binding_path),
        daemon.ANNOUNCEMENT_APP_ENV: binding['app_root'],
        daemon.ANNOUNCEMENT_PYTHON_ENV: binding['python'],
        daemon.ANNOUNCEMENT_PYTHON_SHA_ENV: binding['python_sha256'],
        daemon.ANNOUNCEMENT_CYCLE_SHA_ENV: binding['files'][daemon.ANNOUNCEMENT_CYCLE_RELATIVE],
    }
    fixture = {'binding': binding, 'binding_path': binding_path, 'canary_path': canary_path,
               'environment': environment}
    binding_path.write_text(json.dumps(binding, sort_keys=True), encoding='utf-8')
    app = Path(binding['app_root'])
    from ops.build_release_candidate import inventory_tree, inventory_digest

    entries = inventory_tree(app)
    aggregate = inventory_digest(entries)
    release_id = 'd1-exact-same-root-test'
    manifest_path = app.parent / 'release-manifest.json'
    manifest = {
        'schema_version': 'v4.release_candidate.v1',
        'candidate': {'app_root': str(app), 'root': str(app.parent), 'release_id': release_id},
        'application_inventory': {'entry_count': len(entries), 'aggregate_sha256': aggregate, 'entries': entries},
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    manifest_path.write_bytes(manifest_raw)
    canary = json.loads(canary_path.read_text(encoding='utf-8'))
    canary.update(
        candidate_release_id=release_id,
        candidate_release_manifest_path=str(manifest_path),
        candidate_release_manifest_sha256=_sha(manifest_raw),
        candidate_application_inventory_sha256=aggregate,
        candidate_manager_source_inventory_sha256=hashlib.sha256(
            json.dumps(binding['files'], ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')).encode()
        ).hexdigest(),
    )
    _refresh_canary_pins(fixture, canary)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return fixture


def test_same_root_canary_passes_only_with_current_release_and_supervisor_receipts(tmp_path, monkeypatch):
    fixture = _same_root_fixture(tmp_path, monkeypatch)
    identity = daemon._load_announcement_binding(fixture['environment'])
    assert identity['plan_material_refresh_only'] is True
    assert fixture['binding']['plan_activation_receipt']['path'] == str(fixture['canary_path'])


def test_candidate_historical_guard_uses_candidate_calendar_and_restores_daemon_cache(tmp_path, monkeypatch):
    import contracts
    from contracts import trading_calendar as daemon_calendar

    fixture = _same_root_fixture(tmp_path, monkeypatch)
    canary = json.loads(fixture['canary_path'].read_text(encoding='utf-8'))
    canary['scope'] = 'HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK'
    _refresh_canary_pins(fixture, canary)
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,
                       fixture['binding']['plan_activation_receipt']['sha256'])

    cached_calls = []
    daemon_cached_calendar = ModuleType('contracts.trading_calendar')
    daemon_cached_calendar.TradingDayState = daemon_calendar.TradingDayState
    daemon_cached_calendar.load_market_calendar = lambda: cached_calls.append('load_market_calendar')
    daemon_cached_calendar.resolve_market_states = lambda *_args: {
        'hk_securities': daemon_calendar.TradingDayState.NON_TRADING_DAY,
    }
    monkeypatch.setitem(sys.modules, 'contracts.trading_calendar', daemon_cached_calendar)
    monkeypatch.setattr(contracts, 'trading_calendar', daemon_cached_calendar, raising=False)

    identity = daemon._load_announcement_binding(fixture['environment'])
    assert identity['plan_material_refresh_only'] is True
    assert cached_calls == []
    assert sys.modules['contracts.trading_calendar'] is daemon_cached_calendar
    assert contracts.trading_calendar is daemon_cached_calendar


def test_supervisor_rejects_sidecar_readback_not_present_in_hashed_http_body(tmp_path):
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding

    fixture = _fixture_helpers()
    binding, _ = fixture._plan_only_binding(
        tmp_path, same_owner_root=True, tamper_readback=True,
    )
    with pytest.raises(ValueError, match='PLAN_REFRESH_CANARY_RESPONSE_READBACK_MISMATCH'):
        validate_binding(binding, Path(binding['app_root']))


@pytest.mark.parametrize('tamper', ['source_sha', 'candidate_app', 'state_root'])
def test_same_root_canary_rejects_stale_app_or_inventory_or_state(tmp_path, monkeypatch, tamper):
    fixture = _same_root_fixture(tmp_path, monkeypatch)
    canary = json.loads(fixture['canary_path'].read_text(encoding='utf-8'))
    if tamper == 'source_sha':
        canary['candidate_manager_source_inventory_sha256'] = 'f' * 64
    elif tamper == 'candidate_app':
        canary['candidate_binding_app_root'] = str(tmp_path / 'old-app')
    else:
        canary['manager_state_root'] = str(tmp_path / 'wrong-state')
    _refresh_canary_pins(fixture, canary)
    fixture['environment'][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV] = fixture['binding']['plan_activation_receipt']['sha256']
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,
                       fixture['environment'][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV])
    with pytest.raises(daemon.DaemonConfigurationError):
        daemon._load_announcement_binding(fixture['environment'])


def test_cross_root_canary_still_requires_supervisor_migration_receipt(tmp_path, monkeypatch):
    binding, _ = _fixture_helpers()._plan_only_binding(tmp_path, same_owner_root=False)
    exact_python = Path(binding['python']).resolve(strict=True)
    binding['python'] = str(exact_python)
    binding['python_resolved'] = str(exact_python)
    binding['python_sha256'] = _sha(exact_python.read_bytes())
    canary_path = Path(binding['plan_activation_receipt']['path'])
    binding_path = tmp_path / 'plan-binding.json'
    environment = {
        daemon.ANNOUNCEMENT_BINDING_ENV: str(binding_path),
        daemon.ANNOUNCEMENT_APP_ENV: binding['app_root'],
        daemon.ANNOUNCEMENT_PYTHON_ENV: binding['python'],
        daemon.ANNOUNCEMENT_PYTHON_SHA_ENV: binding['python_sha256'],
        daemon.ANNOUNCEMENT_CYCLE_SHA_ENV: binding['files'][daemon.ANNOUNCEMENT_CYCLE_RELATIVE],
    }
    fixture = {'binding': binding, 'binding_path': binding_path, 'canary_path': canary_path,
               'environment': environment}
    binding_path.write_text(json.dumps(binding, sort_keys=True), encoding='utf-8')
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    canary = json.loads(canary_path.read_text(encoding='utf-8'))
    canary.pop('source_migration_receipt')
    _refresh_canary_pins(fixture, canary)
    fixture['environment'][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV] = binding['plan_activation_receipt']['sha256']
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,
                       fixture['environment'][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV])
    with pytest.raises(daemon.DaemonConfigurationError):
        daemon._load_announcement_binding(fixture['environment'])
