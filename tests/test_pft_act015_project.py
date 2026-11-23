import numpy as np
import pandas as pd
from ops.pft_act015_common import bucket, canonical_history
from ops.pft_act015_project import project_security, rank_labels, gates
from ops.pft_s_full_ashare_features import feature_frame


def history(n=100, start='2022-01-03'):
    return pd.DataFrame({'trade_date': pd.bdate_range(start, periods=n).strftime('%Y%m%d'),
        'ts_code': '000001.SZ', 'open': 10., 'high': 10.2, 'low': 9.8, 'close': 10., 'vol': 100.,
        'bbi': 10.1, 'zge_white_line': 9.9, 'zge_yellow_line': 9.5, 'kdj_k': 20., 'kdj_d': 23.,
        'kdj_j': 14., 'tradeable_basic': 1., 'user_v1_B1': 1., 'user_v1_B2': 0., 'user_v1_B3': 0.,
        'limit_up_approx': 0., 'limit_down_approx': 0.})


def test_both_outer_halves_are_disjoint_and_cover_all():
    codes = [f'{i:06d}.SZ' for i in range(100)]
    halves = [{c for c in codes if bucket(c) == b} for b in (0, 1)]
    assert not halves[0] & halves[1]
    assert halves[0] | halves[1] == set(codes)
    assert all(bucket(c, 'INNER') in (0, 1, 2) for c in codes)


def test_effective_bse_alias_and_no_silent_duplicate():
    f = history(2)
    f.ts_code = '830001.BJ'
    newer = f.copy(); newer.ts_code = '920001.BJ'; newer.close = 11.
    cross = [dict(old='830001.BJ', new='920001.BJ', effective=f.trade_date.iloc[1])]
    out = canonical_history(pd.concat([f, newer]), cross)
    assert out.close.tolist() == [10., 11.]
    assert out.ts_code.tolist() == ['830001.BJ', '920001.BJ']


def test_natural_oos_not_presampled_or_label_filtered_and_short_raw_visible():
    h = history(120, '2026-01-01')
    natural, sample, stats = project_security(('000001.SZ', h, [], h.trade_date.tolist()))
    assert len(natural) == 120
    assert natural.D.tolist() == h.trade_date.tolist()
    assert natural.rank_status.eq('OOS_2026_NOT_READ').all()
    assert natural.loc[~natural.eligible].raw_trigger.all()
    assert sample.empty and stats['prefix_parity_checks'] == 2


def test_rank_exact_calendar_and_unknown_path():
    h = history(8)
    out = rank_labels(h, [h.trade_date.iloc[0]], h.trade_date.tolist()).iloc[0]
    assert out.target_end == h.trade_date.iloc[5]
    assert out.rank_status == 'VALID' and out.rank_target < 0
    h.loc[3, 'close'] = np.nan
    out = rank_labels(h, [h.trade_date.iloc[0]], h.trade_date.tolist()).iloc[0]
    assert out.rank_status == 'PATH_UNKNOWN' and np.isnan(out.rank_target)


def test_g2_35_removed_from_weak_evidence_and_prefix_parity():
    s = feature_frame(history())
    s.loc[99, ['c_vs_yellow_pct', 'd_upper_shadow_pct', 'd_vr5', 'dd_from_pk30_pct', 'd_amp_pct']] = [40, 1, 1, -1, 3]
    revised = gates(s)
    assert revised.iloc[-1].gate_pass == 1
    assert revised.iloc[-1].g2_s26_reject == 0


def test_h5_training_target_must_not_read_2026_price():
    h = history(8, '2025-12-25')
    out = rank_labels(h, [h.trade_date.iloc[0]], h.trade_date.tolist()).iloc[0]
    assert out.rank_status == 'TARGET_AFTER_TRAIN_ALLOWED_RANGE'
    assert np.isnan(out.rank_target)
