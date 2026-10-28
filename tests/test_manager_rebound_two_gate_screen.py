"""Focused synthetic regression coverage for the independent rebound screen."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import v4.manager_research.workspace_plan as workspace_plan


DAY = '20260922'
TARGET_DATE = '20260923'
AUTHORITY_ROOT = Path('/synthetic/authority')


def prior_weekdays(count: int = 60, *, before_day: str = DAY) -> list[str]:
    cursor = date(int(before_day[:4]), int(before_day[4:6]), int(before_day[6:])) - timedelta(days=1)
    sessions = []
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.strftime('%Y%m%d'))
        cursor -= timedelta(days=1)
    return list(reversed(sessions))


def history_rows(code: str, *, high: float = 138.8, volume: float = 114_216,
                 count: int = 60) -> list[dict]:
    return [{
        'trade_date_compact': session, 'code_norm': code, 'name': f'{code} synthetic',
        'open': 69.0, 'high': high, 'low': 68.5, 'close': 70.0,
        'amount': 50_000_000, 'trade': volume, 'pre_close': 70.0,
    } for session in prior_weekdays(count)[-count:]]


def current_row(code: str, *, close: float = 69.95, low: float = 69.10,
                high: float = 70.2, amount: float = 15_855_358,
                volume: float | None = 227_090, prev_close: float = 70.20,
                session: str = DAY) -> dict:
    return {
        'trade_date_compact': session, 'code_norm': code, 'name': f'{code} synthetic',
        'open': min(close, prev_close), 'high': max(high, close), 'low': low, 'close': close,
        'amount': amount, 'trade': volume, 'pre_close': prev_close,
    }


def run_screen(monkeypatch: pytest.MonkeyPatch, rows: list[dict], *, day: str = DAY,
               panel_valid: bool = True, session_spec: dict | None = None) -> dict:
    frame = pd.DataFrame(rows)
    names = {code: {'name': code + ' synthetic'} for code in frame['code_norm'].unique()}
    default_dates = prior_weekdays(60, before_day=day)
    sessions = session_spec or {
        'prior60': default_dates,
        'previous5': default_dates[-5:],
        'panel_session': default_dates[0],
        'calendar_sha256': 'e' * 64,
    }

    if panel_valid:
        panel = {
            'owner': 'SYNTHETIC_VERIFIED_PANEL', 'panel_manifest_path': 'synthetic-manifest.json',
            'panel_manifest_sha256': 'a' * 64, 'panel_path': 'synthetic.parquet',
            'panel_sha256': 'b' * 64, 'panel_max_date': day, 'panel_code_count': len(names),
            'panel_rows': len(frame), 'source_contract': 'synthetic-test-only',
        }
        monkeypatch.setattr(workspace_plan, '_read_hk02_panel_witness', lambda root, session: (panel, []))
        monkeypatch.setattr(workspace_plan, '_screen_security_master_witness', lambda root, session: ({
            'owner': 'SYNTHETIC_VERIFIED_MASTER', 'manifest_path': 'synthetic-master.json',
            'manifest_sha256': 'c' * 64, 'artifact_path': 'synthetic-master.json',
            'artifact_sha256': 'd' * 64, 'names': names,
        }, {}))
        monkeypatch.setattr(workspace_plan, 'rebound_history_sessions', lambda requested_day: sessions)
    else:
        monkeypatch.setattr(workspace_plan, '_read_hk02_panel_witness', lambda root, session: (
            None, ['SCREEN_PANEL_TARGET_MISMATCH']))

    real_read_parquet = pd.read_parquet
    monkeypatch.setattr(pd, 'read_parquet', lambda path, columns=None:
                        frame.loc[:, columns].copy() if columns else frame.copy())
    try:
        return workspace_plan.read_rebound_screen(AUTHORITY_ROOT, {
            'market_session': day, 'plan_trade_date': TARGET_DATE,
        })
    finally:
        monkeypatch.setattr(pd, 'read_parquet', real_read_parquet)


@pytest.mark.parametrize(
    ('code', 'amount', 'close', 'low'),
    [
        ('HK.02589', 15_855_358, 69.95, 69.10),  # below HKD 100m, 1.23% rebound
        ('HK.09998', 250_000_000, 69.95, 69.95),  # above HKD 200m, exactly 0% rebound
    ],
)
def test_amount_and_close_to_low_rebound_are_observations_not_gates(
    monkeypatch: pytest.MonkeyPatch, code: str, amount: float, close: float, low: float,
) -> None:
    rows = [*history_rows(code), current_row(code, amount=amount, close=close, low=low)]
    screen = run_screen(monkeypatch, rows)

    assert screen['status'] == 'READY'
    assert screen['rule_version'] == '20260923_REBOUND_TWO_GATE_V1'
    assert screen['coverage']['input_candidate_count'] == 1
    assert screen['coverage']['selected_count'] == 1
    card = screen['cards'][0]
    assert card['classification'] == 'STRICT_REBOUND'
    assert card['oversold_flag'] is True
    assert card['volume_ratio_5d'] == pytest.approx(227_090 / 114_216)
    assert card['amount_hkd'] == amount
    assert card['rebound_close_vs_low_pct'] == pytest.approx((close / low - 1) * 100)
    assert card['day_positive_close_gt_prev_close'] is False
    assert 'amount_gate_strict_100m_lt_amount_le_200m_hkd' not in card
    assert 'strict_rebound_amount_oversold_rebound_5dvolume' not in card


def test_near_requires_exactly_one_known_remaining_gate_and_unknown_stays_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codes = ['HK.01001', 'HK.01002', 'HK.01003', 'HK.01004']
    rows = []
    # Oversold passes; known 5-day ratio is 1.0, so this is near on volume only.
    rows.extend(history_rows(codes[0]))
    rows.append(current_row(codes[0], close=79.0, low=78.0, volume=114_216))
    # Volume passes; close is above 80% of the prior-60 high, so this is near on oversold only.
    rows.extend(history_rows(codes[1], high=100.0))
    rows.append(current_row(codes[1], close=81.0, low=80.5, high=82.0,
                            prev_close=82.5, volume=227_090))
    # Both known gates fail and should not appear in strict or near candidates.
    rows.extend(history_rows(codes[2], high=100.0))
    rows.append(current_row(codes[2], close=81.0, low=80.5, high=82.0,
                            prev_close=82.5, volume=114_216))
    # A missing current volume is unknown, not a near pass.
    rows.extend(history_rows(codes[3]))
    rows.append(current_row(codes[3], volume=None))

    screen = run_screen(monkeypatch, rows)

    assert screen['coverage']['input_candidate_count'] == 4
    assert screen['coverage']['strict_count'] == 0
    assert screen['coverage']['near_candidate_count'] == 2
    assert screen['coverage']['near_count'] == 2
    assert screen['coverage']['selected_count'] == 2
    assert {row['code'] for row in screen['near']} == set(codes[:2])
    failed_gates = {row['code']: row['near_failed_gate'] for row in screen['near']}
    assert failed_gates[codes[0]] == 'volume_5d_ratio'
    assert failed_gates[codes[1]] == 'oversold_close_le_80pct_prior60_high'
    assert screen['coverage']['history_pending_count'] == 1
    assert screen['pending'][0]['code'] == codes[3]
    assert screen['pending'][0]['history_status'] == 'PARTIAL_UNKNOWN'
    assert 'CURRENT_VOLUME_MISSING_OR_INVALID' in screen['pending'][0]['history_unknown_reasons']
    assert screen['pending'][0]['code'] not in {row['code'] for row in screen['near']}


def test_all_near_candidates_are_kept_without_a_top10_fill_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codes = [f'HK.{number:05d}' for number in range(11_100, 11_112)]
    rows = []
    for code in codes:
        rows.extend(history_rows(code))
        rows.append(current_row(code, close=69.95, low=69.95, volume=114_216))

    screen = run_screen(monkeypatch, rows)

    assert screen['coverage']['input_candidate_count'] == 12
    assert screen['coverage']['strict_count'] == 0
    assert screen['coverage']['near_candidate_count'] == 12
    assert screen['coverage']['selected_count'] == 12
    assert len(screen['near']) == 12
    assert 'longlist_target' not in screen


def test_incomplete_prior_history_is_pending_not_qualified(monkeypatch: pytest.MonkeyPatch) -> None:
    code = 'HK.01005'
    screen = run_screen(monkeypatch, [*history_rows(code, count=59), current_row(code)])

    assert screen['status'] == 'READY_WITH_GAPS'
    assert screen['main_screen_ready'] is True
    assert screen['coverage']['input_candidate_count'] == 1
    assert screen['coverage']['history_pending_count'] == 1
    assert screen['coverage']['selected_count'] == 0
    assert screen['pending'][0]['history_status'] == 'PARTIAL_UNKNOWN'
    assert screen['cards'] == []


@pytest.mark.parametrize('day', ['2026092', 'not-a-session'])
def test_unverified_session_date_cannot_produce_candidates(
    monkeypatch: pytest.MonkeyPatch, day: str,
) -> None:
    monkeypatch.setattr(workspace_plan, '_read_hk02_panel_witness',
                        lambda *_: pytest.fail('date guard must stop before reading the panel'))
    screen = workspace_plan.read_rebound_screen(AUTHORITY_ROOT, {
        'market_session': day, 'plan_trade_date': TARGET_DATE,
    })
    assert screen['status'] == 'CANNOT_CONFIRM'
    assert screen['main_screen_ready'] is False
    assert screen['cards'] == []
    assert 'SCREEN_MARKET_SESSION_UNVERIFIED' in screen['gaps']


def test_panel_source_date_failure_cannot_produce_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    code = 'HK.01006'
    monkeypatch.setattr(workspace_plan, '_screen_security_master_witness',
                        lambda *_: pytest.fail('invalid panel must stop before reading the master'))
    screen = run_screen(monkeypatch, [*history_rows(code), current_row(code)], panel_valid=False)
    assert screen['status'] == 'CANNOT_CONFIRM'
    assert screen['main_screen_ready'] is False
    assert screen['cards'] == []
    assert 'SCREEN_PANEL_TARGET_MISMATCH' in screen['gaps']


@pytest.mark.parametrize('missing_full_date', [None, '20261223'])
def test_half_day_is_excluded_from_previous_five_complete_sessions(
    monkeypatch: pytest.MonkeyPatch, missing_full_date: str | None,
) -> None:
    code = 'HK.02222'
    target_day = '20261229'
    full_five = ['20261217', '20261218', '20261221', '20261222', '20261223']
    earlier_full = prior_weekdays(54, before_day=full_five[0])
    prior60 = [*earlier_full, *full_five, '20261224']
    assert len(prior60) == 60
    rows = [{
        'trade_date_compact': session, 'code_norm': code, 'name': f'{code} synthetic',
        'open': 99.0, 'high': 100.0, 'low': 98.0, 'close': 99.0,
        'amount': 10_000_000, 'trade': 1 if session == '20261224' else 1_000,
        'pre_close': 99.0,
    } for session in prior60 if session != missing_full_date]
    rows.append(current_row(code, close=81.0, low=80.5, high=82.0,
                            volume=1_400, prev_close=82.5, session=target_day))
    session_spec = {
        'prior60': prior60,
        'previous5': full_five,
        'panel_session': prior60[0],
        'calendar_sha256': 'f' * 64,
    }

    screen = run_screen(monkeypatch, rows, day=target_day, session_spec=session_spec)

    assert screen['coverage']['input_candidate_count'] == 1
    assert screen['coverage']['strict_count'] == 0
    assert screen['coverage']['near_count'] == 0
    assert screen['coverage']['selected_count'] == 0
    if missing_full_date:
        assert screen['coverage']['history_complete_count'] == 0
        assert screen['coverage']['history_pending_count'] == 1
        assert screen['pending'][0]['history_status'] == 'PARTIAL_UNKNOWN'
        assert 'PREVIOUS_5_FULL_SESSION_DATES_MISSING:1' in screen['pending'][0]['history_unknown_reasons']
    else:
        assert screen['coverage']['history_complete_count'] == 1
        assert screen['coverage']['history_pending_count'] == 0


def test_duplicate_required_full_session_stays_unknown_not_near(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = 'HK.02223'
    target_day = '20261229'
    full_five = ['20261217', '20261218', '20261221', '20261222', '20261223']
    earlier_full = prior_weekdays(54, before_day=full_five[0])
    prior60 = [*earlier_full, *full_five, '20261224']
    rows = [{
        'trade_date_compact': session, 'code_norm': code, 'name': f'{code} synthetic',
        'open': 99.0, 'high': 100.0, 'low': 98.0, 'close': 99.0,
        'amount': 10_000_000, 'trade': 1_000,
        'pre_close': 99.0,
    } for session in prior60]
    # A conflicting duplicate for a required full session must invalidate this
    # stock's history; choosing this last row would create a false near pass.
    rows.append({
        'trade_date_compact': '20261223', 'code_norm': code, 'name': f'{code} synthetic',
        'open': 99.0, 'high': 100.0, 'low': 98.0, 'close': 99.0,
        'amount': 10_000_000, 'trade': 1,
        'pre_close': 99.0,
    })
    rows.append(current_row(code, close=81.0, low=80.5, high=82.0,
                            amount=15_000_000, volume=1_400, prev_close=82.5,
                            session=target_day))
    session_spec = {
        'prior60': prior60,
        'previous5': full_five,
        'panel_session': prior60[0],
        'calendar_sha256': 'f' * 64,
    }

    screen = run_screen(monkeypatch, rows, day=target_day, session_spec=session_spec)

    assert screen['coverage']['input_candidate_count'] == 1
    assert screen['coverage']['history_complete_count'] == 0
    assert screen['coverage']['history_pending_count'] == 1
    assert screen['coverage']['near_count'] == 0
    assert screen['coverage']['selected_count'] == 0
    assert screen['pending'][0]['code'] == code
    assert screen['pending'][0]['history_status'] == 'PARTIAL_UNKNOWN'
    assert 'PREVIOUS_5_FULL_SESSION_DATES_DUPLICATE:1' in screen['pending'][0]['history_unknown_reasons']
