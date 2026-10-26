"""Synthetic caller-context tests only; no R5/provider/native data execution."""
import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'ops/macos_research_panel_daily_authority.py'
R3_OPS = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/local-panel-history-source-20261025-r3/app/ops')
# W predates the split. Reuse only the unchanged R3 common/pack dependency
# modules read-only; never copy them or select the old W monolith.
package = ModuleType('_seed_context_candidate')
package.__path__ = [str(R3_OPS)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + '.macos_research_panel_daily_authority', SOURCE)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

PATH_ENV = 'V35_A_SYNC_SEED_ADJUSTMENT_INPUTS'
SHA_ENV = 'V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256'
MODULE = SimpleNamespace(SEED_ADJUSTMENT_INPUTS_ENV=PATH_ENV, SEED_ADJUSTMENT_INPUTS_SHA256_ENV=SHA_ENV)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv(PATH_ENV, raising=False)
    monkeypatch.delenv(SHA_ENV, raising=False)


@pytest.fixture
def accepted(tmp_path):
    root = tmp_path / 'tdx'
    source = root / 'vipdoc/sh/lday/sh603629.day'
    source.parent.mkdir(parents=True)
    source.write_bytes(h.A_DAY_STRUCT.pack(20261026, 1000, 1100, 900, 1000, 1000.0, 1000, 0))
    receipts = tmp_path / 'receipts'
    run = receipts / 'a_sync_authority/20261026'
    run.mkdir(parents=True)
    (run / 'file_results.csv').write_text('synthetic_fixture_only\n')
    row = dict(path=str(source), status='REVALIDATED_CURRENT', fetch_status='REVALIDATED',
               classification='ACCEPTED', source_sha256_after=h._sha(source), symbol='920002.BJ')
    return dict(root=root, source=source, receipts=receipts, run=run, row=row)


def accept(fixture, callback, context):
    return h._accepted_formula_input_root(fixture['root'], 20261026, fixture['receipts'], fixture['run'],
        target_files=[fixture['source']], authority_status='REBUILD_REQUIRED',
        _history_status=callback, _seed_evidence=context,
        _rows_impl=lambda *_args: [fixture['row']])


def test_explicit_trusted_args_override_environment(monkeypatch):
    monkeypatch.setenv(PATH_ENV, '/synthetic/environment.json')
    monkeypatch.setenv(SHA_ENV, 'b' * 64)
    args = argparse.Namespace(seed_adjustment_inputs='/synthetic/explicit.json', seed_adjustment_inputs_sha256='a' * 64)
    assert h._authority_seed_context(MODULE, args) == dict(path='/synthetic/explicit.json', expected_sha256='a' * 64, records=[])


def test_original_r5_environment_fallback(monkeypatch):
    monkeypatch.setenv(PATH_ENV, '/synthetic/environment.json')
    monkeypatch.setenv(SHA_ENV, 'b' * 64)
    args = argparse.Namespace(seed_adjustment_inputs=None, seed_adjustment_inputs_sha256=None)
    assert h._authority_seed_context(MODULE, args) == dict(path='/synthetic/environment.json', expected_sha256='b' * 64, records=[])


@pytest.mark.parametrize('path,sha', [(None, 'a' * 64), ('/synthetic/a.json', None),
    ('relative.json', 'a' * 64), ('/synthetic/a.json', 'bad'), ('/synthetic/a.json', 'G' * 64)])
def test_incomplete_or_invalid_config_fails_closed(path, sha):
    with pytest.raises(h.SnapshotGateError, match='context is missing or invalid'):
        h._authority_seed_context(MODULE, argparse.Namespace(seed_adjustment_inputs=path, seed_adjustment_inputs_sha256=sha))


def test_unconfigured_legacy_callback_remains_two_positional_arguments(accepted):
    assert h._authority_seed_context(MODULE, argparse.Namespace()) is None
    calls = []
    def legacy(path, target):
        calls.append((path, target))
        return [], None
    result = accept(accepted, legacy, None)
    assert calls == [(accepted['source'], 20261026)]
    assert result['accepted_target_date_file_count'] == 1


def test_callback_gets_original_context_and_canonical_exact_symbol(accepted):
    context = dict(path='/synthetic/external_descriptor.json', expected_sha256='a' * 64, records=[])
    calls = []
    def original_callback(path, target, *, seed_evidence, symbol):
        assert seed_evidence is context
        calls.append((path, target, symbol))
        return [], None
    result = accept(accepted, original_callback, context)
    assert calls == [(accepted['source'], 20261026, '603629.SH')]
    assert result['accepted_target_date_file_count'] == 1
    assert accepted['row']['symbol'] == '920002.BJ'  # Never trust the row's self-described symbol.
    assert Path(result['formula_tdx_root']).joinpath('vipdoc/sh/lday/sh603629.day').read_bytes() == accepted['source'].read_bytes()


@pytest.mark.parametrize('raises', [False, True])
def test_original_callback_failure_is_not_downgraded_or_bypassed(accepted, raises):
    def rejecting(path, target, *, seed_evidence, symbol):
        assert seed_evidence == {} and symbol == '603629.SH'
        if raises:
            raise ValueError('external_descriptor_pin_mismatch')
        return [], 'CROSS_DAY_CLOSE_RATIO'
    with pytest.raises(h.SnapshotGateError, match='native history validat'):
        accept(accepted, rejecting, {})
    assert not (accepted['receipts'] / 'formula_inputs').exists()


def test_source_sha_gate_still_runs_after_context_callback(accepted):
    accepted['row']['source_sha256_after'] = '0' * 64
    def callback(*_args, **_kwargs):
        return [], None
    with pytest.raises(h.SnapshotGateError, match='accepted source SHA drift'):
        accept(accepted, callback, dict(path='/synthetic/a.json', expected_sha256='a' * 64, records=[]))
    assert not (accepted['receipts'] / 'formula_inputs').exists()


def test_outer_authority_threads_same_trusted_context_into_accepted_callback(accepted, monkeypatch):
    calls = []
    def callback(path, target, *, seed_evidence, symbol):
        calls.append((seed_evidence, symbol))
        return [], None
    module = SimpleNamespace(SEED_ADJUSTMENT_INPUTS_ENV=PATH_ENV,
        SEED_ADJUSTMENT_INPUTS_SHA256_ENV=SHA_ENV, _local_history_status=callback,
        run=lambda args: dict(status='REBUILD_REQUIRED', exit_code=0, run_dir=str(accepted['run'])))
    monkeypatch.setattr(h, '_load_authority_module', lambda *_args: module)
    original = h._accepted_formula_input_root
    def accepted_inputs(*args, **kwargs):
        kwargs['_rows_impl'] = lambda *_args: [accepted['row']]
        return original(*args, **kwargs)
    monkeypatch.setattr(h, '_accepted_formula_input_root', accepted_inputs)
    scope = dict(authority_status='REBUILD_REQUIRED', accepted_count=1, quarantine_count=0,
                 pending_count=0, target_count=1, target_fingerprint='synthetic', target_keys=[])
    result = h.run_windows_a_sync_authority('/synthetic/no_execution.py', accepted['root'], '20261026', accepted['receipts'],
        authority_args=dict(seed_adjustment_inputs='/synthetic/trusted.json', seed_adjustment_inputs_sha256='c' * 64),
        _target_files_impl=lambda _root: [accepted['source']], _scope_audit_impl=lambda *_args, **_kwargs: scope)
    assert calls == [(dict(path='/synthetic/trusted.json', expected_sha256='c' * 64, records=[]), '603629.SH')]
    assert result['formula_input_mode'] == 'ACCEPTED_ONLY' and result['accepted_target_date_file_count'] == 1
