import json

import numpy as np
import pandas as pd
import pytest

from ops import pft_act020_adv as adv


def fixture_history():
    # Distinct session list; holidays/weekends are not observations to invent.
    sessions = pd.bdate_range('2022-12-01', periods=24).strftime('%Y%m%d').tolist()
    history = pd.DataFrame({'ts_code': '000001.SZ', 'trade_date': sessions,
                            'amount': np.arange(1., 25.)})
    return sessions, history


def roll(history, sessions, day):
    return adv.rollup_security(('000001.SZ', history, [day], sessions, [])).iloc[0]


def test_inclusive_d_exact_twenty_sessions_and_no_future_dependency():
    sessions, history = fixture_history()
    day = sessions[20]
    row = roll(history, sessions, day)
    assert row.adv20_cny == sum(range(2, 22)) / 20
    assert row.adv20_valid_count == 20
    history.loc[history.trade_date.gt(day), 'amount'] = 1e18
    assert roll(history, sessions, day).adv20_cny == row.adv20_cny
    assert roll(history[history.trade_date.le(day)], sessions, day).adv20_cny == row.adv20_cny


def test_recorded_zero_counts_as_valid_without_denominator_change():
    sessions, history = fixture_history()
    history.loc[0, 'amount'] = 0
    row = roll(history, sessions, sessions[19])
    assert row.adv20_valid_count == 20
    assert row.adv20_cny == sum(range(2, 21)) / 20
    history['amount'] = 0
    assert roll(history, sessions, sessions[19]).adv20_cny == 0


@pytest.mark.parametrize('bad', [None, -1, float('nan'), float('inf'), -float('inf')])
def test_invalid_original_amount_preserves_unknown(bad):
    sessions, history = fixture_history()
    history.loc[7, 'amount'] = bad
    row = roll(history, sessions, sessions[19])
    assert pd.isna(row.adv20_cny)
    assert row.adv20_valid_count == 19


def test_missing_session_not_replaced_by_older_observation():
    sessions, history = fixture_history()
    row = roll(history.drop(index=10), sessions, sessions[20])
    assert pd.isna(row.adv20_cny)
    assert row.adv20_valid_count == 19
    row = roll(history.iloc[:0], sessions, sessions[20])
    assert pd.isna(row.adv20_cny)
    assert row.adv20_valid_count == 0


def test_bse_alias_uses_existing_effective_date_precedence():
    sessions, history = fixture_history()
    history['ts_code'] = '830001.BJ'
    old = history.copy()
    history['ts_code'] = '920001.BJ'
    history['amount'] = 1000
    crosswalk = [dict(old='830001.BJ', new='920001.BJ', effective=sessions[10])]
    row = adv.rollup_security(('920001.BJ', pd.concat([old, history]), [sessions[19]], sessions, crosswalk)).iloc[0]
    assert row.adv20_cny == (sum(range(1, 11)) + 10 * 1000) / 20


def test_amount_receipt_requires_matching_generation_and_raw_basis(tmp_path):
    source = {'identity': {'generation_id': 'gen', 'a_market_basis': {'amount_basis': 'RAW_TURNOVER'}},
              'backtest': {'panel_sha256': 'sha'}}
    receipt = {'status': 'PASS', 'amount_unit': 'CNY_RAW', 'factor': 1,
               'producer_basis': 'RAW_TURNOVER', 'generation': 'gen', 'backtest_panel_sha256': 'sha',
               'samples': [dict(code=code, v4_raw_amount=100, official_amount_cny=100)
                           for code in ['000001.SZ', '000002.SZ', '600000.SH', '600001.SH', '920001.BJ']]}
    path = tmp_path / 'amount.json'
    path.write_text(json.dumps(receipt))
    assert adv.validate_amount_receipt(path, source)['factor'] == 1
    receipt['generation'] = 'other'
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='SOURCE_DRIFT'):
        adv.validate_amount_receipt(path, source)
