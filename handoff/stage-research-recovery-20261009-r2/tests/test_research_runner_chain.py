"""Synthetic file/quote inputs through the real production runner and stores.

Only the external PyTDX bridge I/O is substituted. The original candidate
reader sees an absent A input; HK files, binding, collector routing, authority,
selector, raw/selection stores and immutable owner receipt are real code.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys

import pytest

from stage_center import runner, live_collectors
from stage_center.selection import SelectionStore
from stage_center.scheduler import DueDecision
from test_hk_current_day_research import bundle, install_quote_bridge, minute_row, DAY, STAGE


def prepared(tmp_path, monkeypatch, *, hk_only=False, count=12):
    source_root, rows, pin = bundle(tmp_path, count=count)
    config = runner.build_production_config(
        candidate_acquisition_root=tmp_path / 'candidate', raw_root=tmp_path / 'raw',
        selection_root=tmp_path / 'selection', receipt_root=tmp_path / 'receipts',
        shared_data_root=tmp_path, python_path=Path(sys.executable),
        hk_current_day_research_root=source_root,
    )
    quotes = [minute_row(row['code'], i) for i, row in enumerate(rows, 1)]
    calls = install_quote_bridge(monkeypatch, quotes)
    if hk_only:
        # Isolate the real HK path for immutable full-slot reuse assertions.
        from stage_center import raw_store
        monkeypatch.setattr(runner, '_stage_markets_for_date', lambda *_: ('HK_CONNECT',))
        monkeypatch.setattr(raw_store, '_expected_bundle_markets', lambda *_: ('HK_CONNECT',))
    instance = runner.StageCenterRunner(config)
    instance._execution_origin = 'CURRENT_DAY_RESEARCH_REPLAY'
    decision = DueDecision(stage_id=STAGE, trade_date=DAY, status='DUE',
                           scheduled_at=None, idempotency_key='fixture', calendar={})
    return instance, decision, source_root, calls


def test_real_research_files_to_runner_selection_and_immutable_receipt(tmp_path, monkeypatch):
    instance, decision, source_root, calls = prepared(tmp_path, monkeypatch, count=695)
    result = instance._run_one(decision)
    hk = result['markets']['HK_CONNECT']
    assert hk.get('selected_rows') == 10, result
    assert hk['requested_rows'] == 695
    assert calls[0][0:2] == (DAY, STAGE)
    assert len(calls[0][2]) == 695
    assert instance.config.hk_d1_root is None
    assert result['markets']['A_SHARE']['selection_status'] == 'CANNOT_CONFIRM'
    assert 'A_SHARE' not in result['input_bindings']
    pin_sha = hashlib.sha256((source_root/'CURRENT_DAY_RESEARCH_PIN.json').read_bytes()).hexdigest()
    bound = result['input_bindings']['HK_CONNECT']
    assert bound['kind'] == 'HK_CURRENT_DAY_RESEARCH'
    assert bound['binding_bytes_sha256'] == pin_sha
    assert bound['membership_status'] == 'CANNOT_CONFIRM'
    research = [x for x in hk['source_evidence'] if x.startswith('research_source=')]
    assert len(research) == 1
    meta = json.loads(research[0].partition('=')[2])
    assert meta['captured_at'] == '2026-10-09T15:38:41+08:00'
    assert meta['formal_pit'] is False and meta['source_sha256'] == pin_sha
    assert all(row['source_last_bar_time'] == '2026-10-09 09:35:00' for row in hk['rows'])
    assert not any('hk_d1_sha256=' in x or 'HK_CONNECT_D1_TOP100' in x for x in hk['source_evidence'])
    verified = SelectionStore(instance.config.selection_root)._verify_run(DAY, STAGE, 'HK_CONNECT', hk['run_id'])
    assert verified['envelope']['rows'] == hk['rows']
    assert result['selection_artifacts']['HK_CONNECT']['artifact_bytes_sha256'] == verified['artifact_sha256']
    history = result['receipt_history']
    history_bytes = (instance.config.receipt_root / history['relative_path']).read_bytes()
    assert hashlib.sha256(history_bytes).hexdigest() == history['sha256']
    assert json.loads(history_bytes)['markets']['HK_CONNECT']['run_id'] == hk['run_id']
    assert result['execution_origin'] == 'CURRENT_DAY_RESEARCH_REPLAY'
    assert result['RESEARCH_ONLY'] is True
    assert all(result[key] is False for key in ('production_allowed','buy_gate_updated','orders_sent'))


def test_research_noop_revalidates_same_binding_and_does_not_recollect(tmp_path, monkeypatch):
    instance, decision, source_root, calls = prepared(tmp_path, monkeypatch, hk_only=True)
    first = instance._run_one(decision)
    assert first['markets']['HK_CONNECT'].get('selected_rows') == 10, first
    second = instance._run_one(decision)
    assert second['status'] == 'NOOP_ALREADY_VERIFIED', second
    assert second['markets']['HK_CONNECT']['run_id'] == first['markets']['HK_CONNECT']['run_id']
    assert len(calls) == 1 and second['write_performed'] is False


def test_selection_only_recovery_reuses_real_raw_and_research_binding(tmp_path, monkeypatch):
    instance, decision, source_root, calls = prepared(tmp_path, monkeypatch, hk_only=True)
    first = instance._run_one(decision)
    assert first['markets']['HK_CONNECT'].get('selected_rows') == 10, first
    raw_before = {str(p.relative_to(instance.config.raw_root)): p.read_bytes()
                  for p in instance.config.raw_root.rglob('*') if p.is_file()}
    # Model a crash after raw publication but before a selection commit.
    shutil.rmtree(instance.config.selection_root)
    second = instance._run_one(decision)
    assert second['markets']['HK_CONNECT'].get('selected_rows') == 10, second
    assert len(calls) == 1
    assert {str(p.relative_to(instance.config.raw_root)): p.read_bytes()
            for p in instance.config.raw_root.rglob('*') if p.is_file()} == raw_before
    assert [r['code'] for r in second['markets']['HK_CONNECT']['rows']] == [
        r['code'] for r in first['markets']['HK_CONNECT']['rows']]


def test_input_change_after_authority_prevents_old_binding_publication(tmp_path, monkeypatch):
    instance, decision, source_root, calls = prepared(tmp_path, monkeypatch, hk_only=True)
    original = runner._attach_hk_authority
    def changed_after_overlay(*args, **kwargs):
        result = original(*args, **kwargs)
        with (source_root / 'receipt.json').open('ab') as stream:
            stream.write(b' ')
        return result
    monkeypatch.setattr(runner, '_attach_hk_authority', changed_after_overlay)
    result = instance._run_one(decision)
    assert any('SHA_MISMATCH' in reason for reason in result['markets']['HK_CONNECT']['cannot_confirm']), result
    assert result['write_performed'] is False
    assert not (instance.config.raw_root / 'latest.json').exists()
    assert not (instance.config.selection_root / 'latest.json').exists()
