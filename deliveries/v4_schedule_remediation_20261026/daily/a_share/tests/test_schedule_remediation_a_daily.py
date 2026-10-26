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


from pathlib import Path
import argparse
import csv
import hashlib
import json
import struct

import pytest
from ops import macos_research_panel_daily_authority as authority


def _partial_native_inputs(tmp_path):
    root = tmp_path / 'tdx'
    path = root / 'vipdoc/sh/lday/sh603629.day'
    path.parent.mkdir(parents=True)
    path.write_bytes(struct.pack('<IIIIIfII', 20261023, 1000, 1100, 900, 1000, 1000.0, 100, 0)
                    + struct.pack('<IIIIIfII', 20261026, 700, 700, 600, 640, 1000.0, 100, 0))
    quarantined = path.with_name('sh600000.day')
    quarantined.write_bytes(b'original quarantine bytes')
    receipts = tmp_path / 'receipts'
    run_dir = receipts / 'a_sync_authority/20261026'
    run_dir.mkdir(parents=True)
    fields = ['path', 'status', 'fetch_status', 'classification', 'source_sha256_after']
    with (run_dir / 'file_results.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(path=str(path), status='ALREADY_CURRENT', fetch_status='ALREADY_CURRENT',
                             classification='ACCEPTED', source_sha256_after=hashlib.sha256(path.read_bytes()).hexdigest()))
        writer.writerow(dict(path=str(quarantined), status='FAILED', fetch_status='REBUILD_REQUIRED',
                             classification='QUARANTINED', source_sha256_after=hashlib.sha256(quarantined.read_bytes()).hexdigest()))
    return root, path, quarantined, receipts, run_dir


@pytest.mark.parametrize("entrypoint", ["implementation", "public_facade"])
def test_partial_handoff_forwards_same_config_and_retains_pair_provenance(tmp_path, monkeypatch, entrypoint):
    from ops import macos_research_panel_daily as facade
    owner = authority if entrypoint == "implementation" else facade
    root, path, quarantine, receipts, run_dir = _partial_native_inputs(tmp_path)
    pin = 'a' * 64
    observed = []
    def validator(source, target, *, seed_evidence=None, symbol=None):
        observed.append((source, target, symbol, dict(seed_evidence)))
        if seed_evidence['expected_sha256'] != pin:
            return [], 'CROSS_DAY_CLOSE_RATIO'
        seed_evidence['records'].append(dict(symbol=symbol, status='EXPLAINED_ACCEPTED_AFFINE', descriptor_sha256=pin))
        return [], None
    module = SimpleNamespace(_local_history_status=validator)
    def run(args):
        monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256', 'b' * 64)
        return dict(run_dir=str(run_dir), status='REBUILD_REQUIRED', exit_code=0)
    module.run = run
    monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS', '/pinned/descriptor.json')
    monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256', pin)
    monkeypatch.setattr(owner, '_load_authority_module', lambda *a: module)
    originals = {p: p.read_bytes() for p in (path, quarantine)}
    result = owner.run_windows_a_sync_authority('fixture', root, '20261026', receipts,
        _target_files_impl=lambda root: [path, quarantine],
        _scope_audit_impl=lambda *a, **k: dict(authority_status='REBUILD_REQUIRED', accepted_count=1,
            quarantine_count=1, pending_count=0, target_count=2, target_fingerprint='fixture', target_keys=[]))
    assert observed[0][2] == '603629.SH'
    assert observed[0][3]['expected_sha256'] == pin
    manifest = json.loads(Path(result['formula_input_manifest']).read_text())
    assert result['accepted_target_date_file_count'] == 1
    assert result['excluded_rebuild_candidate_count'] == 1
    assert manifest['files'][0]['native_history_validation']['explanations'][0]['descriptor_sha256'] == pin
    assert result['coverage_rate'] == 0.5
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert (Path(result['formula_tdx_root']) / 'vipdoc/sh/lday/sh603629.day').read_bytes() == originals[path]
    assert not (Path(result['formula_tdx_root']) / 'vipdoc/sh/lday/sh600000.day').exists()


@pytest.mark.parametrize('digest', [None, 'b' * 64])
def test_handoff_unexplained_or_drifted_evidence_still_blocks(tmp_path, digest):
    root, path, quarantine, receipts, run_dir = _partial_native_inputs(tmp_path)
    original = path.read_bytes()
    def validator(source, target, *, seed_evidence=None, symbol=None):
        assert symbol == '603629.SH'
        assert seed_evidence['expected_sha256'] == digest
        return [], 'CROSS_DAY_CLOSE_RATIO'
    evidence = dict(path='/pinned/descriptor.json', expected_sha256=digest, records=[])
    with pytest.raises(authority.SnapshotGateError, match='CROSS_DAY_CLOSE_RATIO'):
        authority._accepted_formula_input_root(root, 20261026, receipts, run_dir,
            target_files=[path, quarantine], authority_status='REBUILD_REQUIRED',
            _history_status=validator, _history_evidence=evidence)
    assert path.read_bytes() == original
    assert not (receipts / 'formula_inputs').exists()


def test_legacy_validator_signature_retains_two_argument_call(tmp_path, monkeypatch):
    root, path, quarantine, receipts, run_dir = _partial_native_inputs(tmp_path)
    called = []
    def legacy(source, target):
        called.append((source, target))
        return [], None
    monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS', '/unrelated/env')
    assert authority._native_history_evidence(SimpleNamespace(_local_history_status=legacy), argparse.Namespace()) is None
    result = authority._accepted_formula_input_root(root, 20261026, receipts, run_dir,
        target_files=[path, quarantine], authority_status='REBUILD_REQUIRED', _history_status=legacy)
    assert called == [(path, 20261026)]
    assert 'native_history_validation' not in json.loads(Path(result['formula_input_manifest']).read_text())['files'][0]


def test_native_config_uses_explicit_args_and_absence_stays_unexplained(monkeypatch):
    def validator(source, target, *, seed_evidence=None, symbol=None):
        return [], None
    module = SimpleNamespace(_local_history_status=validator)
    monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS', '/environment/descriptor')
    monkeypatch.setenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256', 'a' * 64)
    args = argparse.Namespace(seed_adjustment_inputs='/explicit/descriptor', seed_adjustment_inputs_sha256='b' * 64)
    assert authority._native_history_evidence(module, args) == dict(path='/explicit/descriptor', expected_sha256='b' * 64, records=[])
    monkeypatch.delenv('V35_A_SYNC_SEED_ADJUSTMENT_INPUTS')
    assert authority._native_history_evidence(module, argparse.Namespace()) is None


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



def _hk_cache_fixture(monkeypatch, tmp_path):
    from infrastructure.scheduling import executor_registry_preselection as preselection
    from infrastructure import isolated_package_loader
    rows = [dict(code=f'HK.{index:05}', rank=index, pool_score=index / 1000,
                 history_resolution_identity='f' * 64, signal_date='20261026', target_date='20261027',
                 production_allowed=False, buy_gate_updated=False, orders_sent=False)
            for index in range(1, 101)]
    payload = dict(pool_id='hkconnect_d1_top100', market='HK', trade_date='20261027',
        target_date='20261027', signal_date='20261026', source_role='SHARED_VERIFIED_HK_0_2',
        stage_selection_eligible=True, status='STRICT_0_2_READY', rows=rows,
        source_sha256='a' * 64, source_artifact_sha256='a' * 64,
        source_manifest_sha256='b' * 64, source_receipt_sha256='c' * 64, source_run_id='exact-source',
        production_allowed=False, buy_gate_updated=False, orders_sent=False)
    class LocalStore:
        def __init__(self, *args):
            pass
        def read_pool(self, date, pool_id):
            assert date == '20261027'
            if pool_id == 'a_d1_premarket_pool':
                raise FileNotFoundError(pool_id)
            return payload
    verified = SimpleNamespace(rows=[dict(code_norm=row['code'], rank=row['rank'],
        score_prob_active=row['pool_score'], history_resolution_identity=row['history_resolution_identity']) for row in rows],
        run=SimpleNamespace(receipt={'status': 'READY'}, verification=dict(artifact_sha256='a' * 64,
            manifest_sha256='b' * 64, receipt_sha256='c' * 64, run_id='exact-source')))
    def read(root, *, target_date, expected_signal_date):
        assert target_date == '20261027'
        assert expected_signal_date == '20261026'
        return verified
    monkeypatch.setattr(preselection, 'PreselectionPoolStore', LocalStore)
    monkeypatch.setattr(isolated_package_loader, 'load_isolated_package_module',
        lambda *a, **k: SimpleNamespace(read_verified_hk_0_2_pool=read))
    return preselection, payload


def test_exact_hk_lane_reused_while_a_is_missing(tmp_path, monkeypatch):
    import subprocess
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    preselection, payload = _hk_cache_fixture(monkeypatch, tmp_path)
    package = tmp_path / 'package'
    (package / 'scripts').mkdir(parents=True)
    for script in ['capture_public_fupan.py', 'materialize_v192_selector.py']:
        (package / 'scripts' / script).write_text('# fixture')
    before = json.dumps(payload, sort_keys=True)
    calls = []
    def runner(command, **kwargs):
        module = command[2]
        calls.append(module)
        if module == 'ops.materialize_shared_v192_preselection':
            return subprocess.CompletedProcess(command, 1, json.dumps(dict(status='CANNOT_CONFIRM')), '')
        if module == 'ops.materialize_scheduled_preselection':
            return subprocess.CompletedProcess(command, 1, json.dumps(dict(status='FAILED', formal_pool_gate=dict(
                status='FAILED', required={'a_d1_premarket_pool': dict(ready=False),
                    'hkconnect_d1_top100': dict(ready=True, research_ready=True, status='STRICT_0_2_READY')}))), '')
        return subprocess.CompletedProcess(command, 0, '', '')
    registry = FixedExecutorRegistry(data_root=tmp_path / 'local-data', shared_data_root=tmp_path / 'shared',
        hk_universe_root=tmp_path / 'universe', shared_package_root=package,
        selector_data_root=tmp_path / 'missing-a', preselection_input_root=tmp_path / 'inputs',
        repo_root=tmp_path, runner=runner)
    request = DispatchRequest(scheduled_date='20261026', business_date='20261026',
        target_date='20261027', slot='1730', mode=DispatchMode.LIVE)
    result = registry._preselection_pools(request)
    assert result['a_selector_status'] == 'CANNOT_CONFIRM'
    assert result['hk_lane_status'] == 'READY'
    assert result['hk_lane_reuse']['hk_source_sha256'] == 'a' * 64
    assert not {'scripts.update_hk_0_2_panel', 'ops.ensure_hk_security_master', 'scripts.materialize_hk_0_2'}.intersection(calls)
    assert json.dumps(payload, sort_keys=True) == before
    assert result['status'] == 'FAILED'  # A gap is still explicit.


@pytest.mark.parametrize('changed_field,value', [
    ('source_sha256', '0' * 64), ('source_manifest_sha256', '0' * 64),
    ('source_receipt_sha256', '0' * 64), ('signal_date', '20261023'),
])
def test_hk_independent_reuse_rejects_source_or_date_drift(tmp_path, monkeypatch, changed_field, value):
    preselection, payload = _hk_cache_fixture(monkeypatch, tmp_path)
    payload[changed_field] = value
    owner = SimpleNamespace(data_root=tmp_path, shared_package_root=tmp_path / 'package', shared_data_root=tmp_path / 'shared')
    assert preselection._verified_formal_pool_reuse(owner, '20261027', _hk_only=True) is None


def test_hk_independent_reuse_rejects_split_eligibility_date(tmp_path, monkeypatch):
    preselection, _ = _hk_cache_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(preselection, '_hk_price_and_eligibility_dates', lambda date: ('20261026', '20261023'))
    owner = SimpleNamespace(data_root=tmp_path, shared_package_root=tmp_path / 'package', shared_data_root=tmp_path / 'shared')
    assert preselection._verified_formal_pool_reuse(owner, '20261027', _hk_only=True) is None
