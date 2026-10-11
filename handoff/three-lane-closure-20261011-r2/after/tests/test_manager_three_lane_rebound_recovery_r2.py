"""Original screen calculations with synthetic exact owner-reader inputs."""
from copy import deepcopy

import pandas as pd
import pytest

from test_manager_three_lane_rebound_diagnostics_r1 import tabular_input, attention
from v4.manager_research import workspace_plan as plan


def complete_panel(fixture, *, high_gap=False):
    path = fixture['panel']['panel_path']
    frame = pd.read_parquet(path)
    frame = frame.loc[frame['code_norm'].eq('HK.00001')].copy()
    frame['trade'] = 100.0  # Panel ratio 1; sidecar ratio 2, intentionally different.
    if high_gap:
        frame.loc[frame['trade_date_compact'].eq(fixture['sessions']['prior60'][10]), 'high'] = None
    frame.to_parquet(path, index=False)


def supplement(fixture):
    dates = [*fixture['sessions']['previous5'], fixture['day']]
    return dict(target_date=fixture['day'], status='READY', raw_capture_sha256='f'*64,
        manifest_sha256='1'*64, pointer=dict(raw_capture_relative='synthetic-raw.json',
            manifest_relative='synthetic-manifest.json'),
        manifest=dict(run_id='synthetic', method='get_instrument_bars'), records={'HK.00001':dict(
            status='READY', request_sha256='2'*64, response_sha256='3'*64,
            bars=[dict(trade_date=day, open=80.0, high=100.0, low=70.0, close=80.0,
                       trade=200.0 if day==fixture['day'] else 100.0) for day in dates])})


def row(screen):
    return next(r for group in ('strict','near','pending','excluded','screen_unresolved')
                for r in screen.get(group, []) if r['code']=='HK.00001')


def test_unproven_panel_volume_uses_original_complete_six_bar_supplement(tabular_input, monkeypatch):
    fixture = tabular_input; complete_panel(fixture)
    calls = []
    sidecar = supplement(fixture)
    def reader(*args, **kwargs):
        calls.append((args, kwargs)); return deepcopy(sidecar)
    monkeypatch.setattr(plan, '_read_hk02_daily_supplement_witness', reader)
    output = plan.read_rebound_screen(fixture['root'], fixture['context'])
    observed = row(output)
    assert len(calls) == 1
    assert observed['strict_two_gate_oversold_5dvolume'] is True
    assert observed['close'] == 8.0  # Valid panel prices are never replaced.
    assert observed['prior60_session_high'] == 10.0
    assert observed['volume_ratio_5d'] == 2.0
    assert observed['volume_unit_status'] == 'NOT_PROVEN'
    assert observed['volume_relative_comparability_status'] == 'VERIFIED_SAME_RESPONSE_RAW_FIELD_UNIT_UNKNOWN'
    assert observed['volume_source'] == 'PYTDX_EXHQ_CATEGORY_4_MARKET_71'
    # A consumed source-byte change must be material, not normalized away.
    before = attention(output, fixture['context'])
    sidecar['raw_capture_sha256'] = '9'*64
    changed = plan.read_rebound_screen(fixture['root'], fixture['context'])
    # The inherited screen input_identity covers panel/calendar/rules. The
    # full source-bearing projection and original decision ledger must change.
    assert output != changed
    assert output['authority']['daily_supplement']['raw_capture_sha256'] != changed['authority']['daily_supplement']['raw_capture_sha256']
    assert before['research_selection']['decision_identity'] != attention(changed, fixture['context'])['research_selection']['decision_identity']


@pytest.mark.parametrize('defect', ['absent','failed','partial','missing_session','missing_volume'])
def test_incomplete_supplement_never_mixes_panel_and_sidecar_volume(tabular_input, monkeypatch, defect):
    fixture = tabular_input; complete_panel(fixture)
    sidecar = supplement(fixture)
    record = sidecar['records']['HK.00001']
    if defect == 'failed': record['status'] = 'QUERY_FAILED'
    elif defect == 'partial': record['status'] = 'PARTIAL'
    elif defect == 'missing_session': record['bars'].pop(0)
    elif defect == 'missing_volume': record['bars'][0]['trade'] = None
    monkeypatch.setattr(plan, '_read_hk02_daily_supplement_witness', lambda *args, **kwargs: None if defect=='absent' else deepcopy(sidecar))
    observed = row(plan.read_rebound_screen(fixture['root'], fixture['context']))
    assert observed['strict_two_gate_oversold_5dvolume'] is False
    assert observed['volume_unit_status'] == 'NOT_PROVEN'
    assert observed['history_status'] != 'KNOWN'
    assert observed['volume_source'] == 'V4_SHARED_HK_0_2_PANEL_AUTHORITY'


def test_verified_complete_panel_keeps_its_original_volume_source(tabular_input, monkeypatch):
    fixture = tabular_input; complete_panel(fixture)
    monkeypatch.setattr(plan, '_screen_panel_volume_evidence', lambda *args, **kwargs:dict(
        status='OWNER_VERIFIED', unit_status='OWNER_VERIFIED', unit='shares', scale_applied=1,
        source='SYNTHETIC_VERIFIED_PANEL_BOUNDARY', gaps=[]))
    monkeypatch.setattr(plan, '_read_hk02_daily_supplement_witness', lambda *args, **kwargs:pytest.fail('Complete verified panel must not read supplement'))
    observed = row(plan.read_rebound_screen(fixture['root'], fixture['context']))
    assert observed['volume_source'] == 'V4_SHARED_HK_0_2_PANEL_AUTHORITY'
    assert observed['volume_ratio_5d'] == 1.0


def test_failed_original_supplement_validation_keeps_precise_recovery_reason(tabular_input, monkeypatch):
    fixture = tabular_input; complete_panel(fixture)
    def rejected(*args, **kwargs):
        raise ValueError('HK_DAILY_SUPPLEMENT_PANEL_SHA_MISMATCH')
    monkeypatch.setattr(plan, '_read_hk02_daily_supplement_witness', rejected)
    diagnostics = {}
    output = plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
    expected = 'SCREEN_DAILY_SUPPLEMENT_UNVERIFIED:HK_DAILY_SUPPLEMENT_PANEL_SHA_MISMATCH'
    assert expected in output['gaps']
    assert expected in diagnostics['daily_supplement_gaps']
    assert row(output)['history_status'] != 'KNOWN'
    assert row(output)['volume_unit_status'] == 'NOT_PROVEN'


def test_invalid_present_fields_report_exact_dates_without_identity_changes(tabular_input):
    fixture = tabular_input; complete_panel(fixture, high_gap=True)
    path = fixture['panel']['panel_path']; frame = pd.read_parquet(path)
    invalid_volume_day = fixture['sessions']['previous5'][1]
    frame.loc[frame['trade_date_compact'].eq(invalid_volume_day), 'trade'] = None
    frame.loc[frame['trade_date_compact'].eq(fixture['day']), 'close'] = None
    frame.to_parquet(path, index=False)
    diagnostics = {}
    original = plan.read_rebound_screen(fixture['root'], fixture['context'])
    output = plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
    assert output == original
    assert attention(output, fixture['context']) == attention(original, fixture['context'])
    observed = diagnostics['rows'][0]
    assert observed['missing_prior60_dates'] == []
    assert observed['invalid_prior60_high_dates'] == [fixture['sessions']['prior60'][10]]
    assert observed['invalid_previous5_volume_dates'] == [invalid_volume_day]
    assert observed['invalid_current_fields'] == ['close']
