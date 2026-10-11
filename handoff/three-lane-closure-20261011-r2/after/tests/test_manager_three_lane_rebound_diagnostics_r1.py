"""Real Parquet/calendar calculations with synthetic owner-reader boundaries.

These tests exercise the existing screen math and identity contracts. They do
not attest a live HK panel, market data, a Mac owner run, or a natural schedule.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pandas as pd
import pytest

from v4.manager_research import workspace_plan as plan
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace_projection import build_workspace, digest


@pytest.fixture
def tabular_input(tmp_path, monkeypatch):
    context = plan.plan_context('20261012', now=datetime.fromisoformat('2026-10-11T12:00:00+08:00'))
    day = plan.screen_context(context)['market_session']
    assert day == '20261009'
    sessions = plan.rebound_history_sessions(day)
    missing = [sessions['prior60'][0], sessions['previous5'][1]]
    duplicate = sessions['previous5'][2]
    rows = []
    for code in ('HK.00001', 'HK.00002'):
        for session in [*sessions['prior60'], day]:
            if code == 'HK.00002' and session in missing:
                continue
            row = dict(trade_date_compact=session, code_norm=code, name='Synthetic '+code,
                open=8.0, high=10.0, low=7.0, close=8.0, pre_close=7.8,
                trade=200.0 if session == day else 100.0, amount=10000.0)
            rows.append(row)
            if code == 'HK.00002' and session == duplicate:
                rows.append(deepcopy(row))
    panel_path = tmp_path/'synthetic-panel.parquet'
    pd.DataFrame(rows).to_parquet(panel_path, index=False)
    manifest_path = tmp_path/'synthetic-panel.manifest.json'
    manifest_path.write_text(json.dumps(dict(synthetic_fixture=True)), encoding='utf-8')
    master_path = tmp_path/'synthetic-master.json'
    master_path.write_text(json.dumps(dict(synthetic_fixture=True)), encoding='utf-8')
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    panel = dict(owner='V4_SHARED_HK_0_2_PANEL_AUTHORITY', panel_path=str(panel_path),
        panel_sha256=sha(panel_path), panel_manifest_path=str(manifest_path),
        panel_manifest_sha256=sha(manifest_path), panel_rows=len(rows), panel_code_count=2,
        source_contract='SYNTHETIC_READER_BOUNDARY_NOT_OWNER_ATTESTATION')
    master = dict(owner='V4_SHARED_HK_SECURITY_MASTER', captured_at='2026-10-09T17:00:00+08:00',
        artifact_path=str(master_path), artifact_sha256=sha(master_path),
        manifest_path=str(master_path), manifest_sha256=sha(master_path),
        names={code:dict(name='Synthetic '+code) for code in ('HK.00001', 'HK.00002')})
    calls = []

    def panel_reader(root, requested, **kwargs):
        calls.append(('panel', requested, deepcopy(kwargs)))
        assert requested == day
        assert kwargs['required_history_date'] == sessions['previous5'][-1]
        return deepcopy(panel), []

    def master_reader(root, requested):
        calls.append(('master', requested))
        return deepcopy(master), dict(synthetic_fixture=True)

    monkeypatch.setattr(plan, '_read_hk02_panel_witness', panel_reader)
    monkeypatch.setattr(plan, '_screen_security_master_witness', master_reader)
    monkeypatch.setattr(plan, '_read_hk02_daily_supplement_witness', lambda *args, **kwargs: None)
    return dict(root=tmp_path, context=context, day=day, sessions=sessions,
        missing=missing, duplicate=duplicate, panel=panel, master=master, calls=calls)


def attention(screen, context):
    return build_research_attention('20261012', context=context, market_screen=screen,
        stocks=[], material_cards=[], themes=[], announcement_observation=None, us_market=None)


def test_optional_diagnostics_preserve_complete_screen_plan_and_ledger_identities(tabular_input):
    fixture = tabular_input
    diagnostics = {'rows':['stale'], 'gaps':['stale'], 'source_screen_decision_identity':'stale'}
    original_shape = plan.read_rebound_screen(fixture['root'], fixture['context'])
    diagnostic_shape = plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
    assert original_shape == diagnostic_shape
    assert diagnostic_shape['status'] == 'READY_WITH_GAPS'
    assert diagnostic_shape['coverage']['input_candidate_count'] == 2
    assert len(diagnostic_shape['pending']) == 2  # Unattested panel volume stays unknown.
    assert diagnostic_shape['coverage']['strict_count'] == 0
    assert all(row['volume_unit_status'] == 'NOT_PROVEN' for row in diagnostic_shape['pending'])
    assert attention(original_shape, fixture['context']) == attention(diagnostic_shape, fixture['context'])
    kwargs = dict(catalyst=dict(target_trade_date='20261012', status='NOT_MATERIALIZED', cards=[], gaps=[]),
        plan_context=fixture['context'])
    old_plan = build_workspace('20261012', market_screen=original_shape, **kwargs)
    new_plan = build_workspace('20261012', market_screen=diagnostic_shape, **kwargs)
    assert old_plan == new_plan
    assert old_plan['input_identity'] == new_plan['input_identity']
    assert len(fixture['calls']) == 4  # Diagnostics add no second owner read.
    assert diagnostics['source_screen_input_identity'] == diagnostic_shape['input_identity']
    assert diagnostics['source_screen_decision_identity'] == diagnostic_shape['decision_identity']
    assert diagnostics['research_cutoff'] == fixture['context']['research_cutoff']
    assert diagnostics['verified_session'] == fixture['day']
    assert diagnostics['target_trade_date'] == '20261012'
    assert diagnostics['sha256'] == digest({key:value for key,value in diagnostics.items() if key != 'sha256'})
    assert diagnostics['diagnostic_only'] is True
    assert diagnostics['selection_verdict_modified'] is False


def test_missing_and_duplicate_sessions_are_exact_and_diagnostic_refs_are_isolated(tabular_input):
    fixture = tabular_input
    diagnostics = {}
    screen = plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
    rows = {row['symbol']:row for row in diagnostics['rows']}
    assert rows['HK.00001']['missing_prior60_dates'] == []
    assert rows['HK.00001']['missing_previous5_dates'] == []
    assert rows['HK.00001']['history_numeric_status'] == 'KNOWN'
    missing = rows['HK.00002']
    assert missing['missing_prior60_dates'] == fixture['missing']
    assert missing['missing_previous5_dates'] == [fixture['sessions']['previous5'][1]]
    assert missing['duplicate_prior60_dates'] == [fixture['duplicate']]
    assert missing['duplicate_previous5_dates'] == [fixture['duplicate']]
    assert missing['history_numeric_status'] == 'PARTIAL_UNKNOWN'
    assert missing['volume_source'] == 'V4_SHARED_HK_0_2_PANEL_AUTHORITY'
    assert missing['source_refs'][0]['payload_sha256'] == fixture['panel']['panel_sha256']
    before = deepcopy(screen)
    missing['source_refs'][0]['payload_sha256'] = 'changed only in diagnostic output'
    assert screen == before
    assert all('missing_prior60_dates' not in row for row in screen['pending'])


def test_mid_calculation_failure_discards_partial_diagnostics_and_prior_output(tabular_input, monkeypatch):
    fixture = tabular_input
    diagnostics = {'rows':['prior success'], 'gaps':['prior gap'],
        'source_screen_decision_identity':'prior identity', 'sha256':'prior sha'}
    seen = []

    class FailingNames(dict):
        def get(self, key, default=None):
            seen.append(key)
            if key == 'HK.00002':
                raise RuntimeError('synthetic second-row read failure')
            return super().get(key, default)

    master = deepcopy(fixture['master'])
    master['names'] = FailingNames(master['names'])
    monkeypatch.setattr(plan, '_screen_security_master_witness', lambda *args: (master, {}))
    result = plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
    assert seen == ['HK.00001', 'HK.00002']
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['coverage']['input_candidate_count'] is None
    assert diagnostics['status'] == 'CANNOT_CONFIRM'
    assert diagnostics['rows'] == []
    assert diagnostics['sha256'] is None
    assert diagnostics['source_screen_input_identity'] is None
    assert 'source_screen_decision_identity' not in diagnostics
    assert 'gaps' not in diagnostics

