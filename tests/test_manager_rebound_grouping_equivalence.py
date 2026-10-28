from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
ACTIVE_APP = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260924-manual-ui-api-r1/app')
EVIDENCE_ROOT = Path('/Users/lexi/Downloads/V4_MANAGER_SUMMARY_PERF_20260924/performance_optimization')
BASELINE = EVIDENCE_ROOT / 'preimages/canonical_workspace_plan.py'
CANDIDATE = REPO / 'v4/manager_research/workspace_plan.py'
PREIMAGE_HASH = '2e8ed3a5214a8ca739b812cde115ef22ea9e13e2e89a22ce49182e58cbf26259'
TARGET_DAY = '20240331'
SYMBOLS = ('HK.00001', 'HK.00002', 'HK.00003', 'HK.00004', 'BAD-CODE')


def _load_reader(path: Path, suffix: str):
    sys.path.insert(0, str(ACTIVE_APP))
    sys.path.insert(0, str(REPO))
    name = f'v4.manager_research.workspace_plan_group_equivalence_{suffix}'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _input_frame(*, duplicate_target: bool = False) -> tuple[pd.DataFrame, dict]:
    import datetime as dt

    target = dt.date(2024, 3, 31)
    prior60 = [(target - dt.timedelta(days=offset)).strftime('%Y%m%d') for offset in range(60, 0, -1)]
    previous5 = prior60[-5:]
    half_day = prior60[-6]
    rows = []
    for code in SYMBOLS:
        for session in prior60:
            if code == 'HK.00003' and session == prior60[-1]:
                continue  # one missing prior-60 and full previous-5 date
            volume = 1000.0 if session == half_day else 10.0
            rows.append(dict(trade_date_compact=session, code_norm=code, name=code,
                             open=80.0, high=100.0, low=60.0, close=75.0,
                             amount=10_000_000.0, trade=volume, pre_close=80.0))
        if code == 'HK.00004':
            # A duplicate prior-5 day must retain its fail-closed unknown state.
            rows.append(dict(trade_date_compact=previous5[-1], code_norm=code, name=code,
                             open=80.0, high=100.0, low=60.0, close=75.0,
                             amount=10_000_000.0, trade=10.0, pre_close=80.0))
    targets = [
        ('HK.00002', 90.0),  # near: volume passes, oversold fails
        ('BAD-CODE', 75.0),  # invalid-looking code remains evaluated as before
        ('HK.00004', 75.0),  # duplicate history remains unknown
        ('HK.00001', 75.0),  # strict: both gates pass
        ('HK.00003', 75.0),  # missing full-session history remains unknown
    ]
    for code, close in targets:
        rows.append(dict(trade_date_compact=TARGET_DAY, code_norm=code, name=code,
                         open=80.0, high=95.0, low=70.0, close=close,
                         amount=10_000_000.0, trade=20.0, pre_close=80.0))
    if duplicate_target:
        rows.append(dict(trade_date_compact=TARGET_DAY, code_norm='HK.00001', name='duplicate',
                         open=80.0, high=95.0, low=70.0, close=75.0,
                         amount=10_000_000.0, trade=20.0, pre_close=80.0))
    # Must not enter any history metric because it is after the verified session.
    rows.append(dict(trade_date_compact='20240401', code_norm='HK.00001', name='future',
                     open=100.0, high=10000.0, low=99.0, close=9999.0,
                     amount=999_000_000.0, trade=999_000.0, pre_close=80.0))
    return pd.DataFrame(rows), {
        'prior60': prior60,
        'previous5': previous5,
        'calendar_sha256': 'a' * 64,
    }


def _read_result(module, monkeypatch, *, duplicate_target: bool = False,
                 include_panel_only_target: bool = True) -> dict:
    frame, sessions = _input_frame(duplicate_target=duplicate_target)
    if not include_panel_only_target:
        frame = frame.loc[
            ~((frame['code_norm'] == 'BAD-CODE')
              & (frame['trade_date_compact'] == TARGET_DAY))
        ].copy()
    panel = {
        'owner': 'FIXTURE_PANEL_OWNER', 'panel_path': '/fixture/panel.parquet',
        'panel_sha256': 'b' * 64, 'panel_manifest_path': '/fixture/manifest.json',
        'panel_manifest_sha256': 'c' * 64, 'source_contract': 'fixture-contract',
        'panel_rows': len(frame), 'panel_code_count': len(SYMBOLS),
        'price_currency': 'HKD', 'price_basis': 'RAW',
        'session_kind': 'FULL_DAY_CLOSE', 'amount_unit': 'HKD',
    }
    names = {code: {'name': f'Name {code}'} for code in SYMBOLS if code != 'BAD-CODE'}
    master = {
        'owner': 'FIXTURE_MASTER_OWNER', 'manifest_path': '/fixture/master-manifest.json',
        'manifest_sha256': 'd' * 64, 'artifact_path': '/fixture/master.csv',
        'artifact_sha256': 'e' * 64, 'row_count': len(names), 'run_id': 'fixture',
        'captured_at': '2024-03-30T12:00:00+00:00', 'names': names,
    }
    with monkeypatch.context() as patch:
        patch.setattr(module, '_read_hk02_panel_witness', lambda root, day: (panel, []))
        patch.setattr(module, '_screen_security_master_witness', lambda root, day: (master, {}))
        patch.setattr(module, 'rebound_history_sessions', lambda day: sessions)
        patch.setattr(pd, 'read_parquet', lambda path, columns=None: frame.copy())
        return module.read_rebound_screen(Path('/fixture/authority'), {
            'market_session': TARGET_DAY, 'plan_trade_date': '20240401',
        })


def _same_contract(left: dict, right: dict) -> None:
    assert left['status'] == right['status']
    assert left['rule_version'] == right['rule_version']
    assert left['target_trade_date'] == right['target_trade_date']
    assert left['verified_session'] == right['verified_session']
    assert left['gaps'] == right['gaps']
    coverage_fields = (
        'input_candidate_count', 'history_complete_count', 'history_pending_count',
        'strict_count', 'near_candidate_count', 'near_count', 'selected_count',
        'pending_codes',
    )
    assert {key: left['coverage'][key] for key in coverage_fields} == {
        key: right['coverage'][key] for key in coverage_fields
    }
    semantic_fields = (
        'code', 'name', 'classification', 'history_status', 'history_unknown_reasons',
        'close', 'prev_close', 'current_volume', 'amount_hkd',
        'prior60_session_count', 'previous5_session_count', 'prior60_session_high',
        'previous5_mean_volume', 'volume_ratio_5d', 'oversold_flag',
        'volume_flag_5d_ge_1_5', 'strict_two_gate_oversold_5dvolume',
        'near_two_gate_one_missing', 'near_failed_gate', 'near_failed_value',
        'near_gate_value', 'near_gate_gap_ratio', 'near_gate_gap_value',
        'research_priority_method', 'research_priority_rank', 'reason_for_group',
    )
    for key in ('cards', 'strict', 'near', 'pending'):
        project = lambda rows: [
            {field: row.get(field) for field in semantic_fields} for row in rows
        ]
        assert project(left[key]) == project(right[key])
    assert left['status'] == 'READY_WITH_GAPS'
    assert left['coverage']['input_candidate_count'] == len(SYMBOLS) - 1
    assert left['coverage']['strict_count'] == 1
    assert left['coverage']['near_count'] == 1
    assert left['coverage']['history_pending_count'] == 2
    assert [row['code'] for row in left['strict']] == ['HK.00001']
    assert [row['code'] for row in left['near']] == ['HK.00002']
    assert {row['code'] for row in left['pending']} == {'HK.00003', 'HK.00004'}
    assert 'SCREEN_HISTORY_DUPLICATE_DATE:HK.00004' in left['gaps']
    # The huge half-day volume is in prior60 but is outside the five full sessions.
    strict = next(row for row in left['strict'] if row['code'] == 'HK.00001')
    assert strict['previous5_mean_volume'] == 10.0
    assert strict['volume_ratio_5d'] == 2.0
    assert strict['prior60_session_count'] == 60
    assert strict['prior60_session_high'] == 100.0
    assert strict['oversold_flag'] is True
    assert strict['volume_flag_5d_ge_1_5'] is True
    near = left['near'][0]
    assert near['oversold_flag'] is False
    assert near['volume_flag_5d_ge_1_5'] is True


def test_real_reader_equivalence_preserves_grouped_history_contract(monkeypatch):
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == PREIMAGE_HASH
    before = _load_reader(BASELINE, 'before')
    after = _load_reader(CANDIDATE, 'after')
    # The baseline reader used all target rows as its input universe. Remove
    # the panel-only target row from both equivalence inputs so this comparison
    # covers exactly the verified master universe.
    old_result = _read_result(before, monkeypatch, include_panel_only_target=False)
    new_result = _read_result(after, monkeypatch, include_panel_only_target=False)
    _same_contract(old_result, new_result)
    panel_only_result = _read_result(after, monkeypatch)
    assert panel_only_result['coverage']['master_universe_count'] == len(SYMBOLS) - 1
    assert panel_only_result['coverage']['panel_only_excluded_count'] == 1
    assert panel_only_result['coverage']['panel_only_excluded_codes'] == ['BAD-CODE']
    assert 'SCREEN_PANEL_ONLY_CODES_EXCLUDED:BAD-CODE' in panel_only_result['gaps']
    assert 'BAD-CODE' not in {
        row['code'] for row in [
            *panel_only_result['strict'], *panel_only_result['near'], *panel_only_result['pending'],
        ]
    }


def test_real_reader_duplicate_target_still_fails_closed_identically(monkeypatch):
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == PREIMAGE_HASH
    before = _load_reader(BASELINE, 'duplicate_before')
    after = _load_reader(CANDIDATE, 'duplicate_after')
    old_result = _read_result(before, monkeypatch, duplicate_target=True)
    new_result = _read_result(after, monkeypatch, duplicate_target=True)
    assert old_result == new_result
    assert old_result['status'] == 'CANNOT_CONFIRM'
    assert old_result['gaps'] == ['SCREEN_PANEL_TARGET_DUPLICATE_CODE']
