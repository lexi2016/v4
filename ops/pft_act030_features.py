"""ACT030 causal, continuous diagnostics. No fitting, labels, scores or panel writes.

Model-safe anchors are explicit D-time public inputs. Gemini reference anchors are
accepted ONLY by ``diagnostic_reference_features`` and never by ``features``.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
import math
from typing import Mapping

import numpy as np
import pandas as pd

SCHEMA = 'PFT_ACT030_CONTINUOUS_V1'
GROUPS = {
    'anchor': ('active_intact_margin_atr', 'active_close_vs_low_pct',
               'active_close_vs_mid_pct', 'invalidation_dist_atr', 'root_intact_margin_atr'),
    'volume': ('max_dn_vol5_vs_plat', 'vol_contraction_vs_platform',
               'vol_contraction_vs_wave_peak', 'vol_d_vs_platform', 'up_vol_purity_20d'),
    'shape': ('hl_convergence_slope_15d', 'box_tightness_5d', 'box_tightness_10d',
              'atr_contraction_5v20'),
    'line': ('close_vs_white_pct', 'close_vs_yellow_pct'),
}
FEATURES = tuple(n for group in GROUPS.values() for n in group)
PRICE_COLUMNS = ('open', 'high', 'low', 'close', 'white', 'yellow', 'bbi')
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
TOLERANCE = {n: (5e-6 if n == 'hl_convergence_slope_15d' else
                 5e-5 if n.endswith('_pct') or n.startswith('box_') else 5e-4) for n in FEATURES}


def day(value) -> str:
    if value is None or value == '' or str(value).lower() in ('nan', 'nat'):
        return ''
    if isinstance(value, (float, int, np.number)):
        # Numeric reference dates are Excel serial dates, never implicit labels.
        if 30000 <= float(value) <= 60000:
            return (date(1899, 12, 30) + timedelta(days=float(value))).strftime('%Y%m%d')
        value = str(int(value))
    result = str(value).replace('-', '')[:8]
    if len(result) != 8 or not result.isdigit():
        raise ValueError('INVALID_DATE')
    date(int(result[:4]), int(result[4:6]), int(result[6:]))
    return result


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def divide(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def checked_history(history: pd.DataFrame, endpoint) -> pd.DataFrame:
    """Fail on future/duplicate/invalid bars rather than silently clipping them."""
    h = history.copy()
    h['trade_date'] = h.trade_date.map(day)
    d = day(endpoint)
    if h.empty or h.trade_date.duplicated().any() or not h.trade_date.is_monotonic_increasing:
        raise ValueError('HISTORY_EMPTY_DUPLICATED_OR_UNSORTED')
    if h.trade_date.gt(d).any() or h.trade_date.iloc[-1] != d:
        raise ValueError('POST_D_OR_MISSING_ENDPOINT')
    required = [*PRICE_COLUMNS, 'volume', 'amount_cny']
    values = h[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or h.volume.lt(0).any() or h.amount_cny.lt(0).any():
        raise ValueError('NONFINITE_OR_NEGATIVE_ACTIVITY')
    if h.high.lt(h[['open', 'close', 'low']].max(axis=1)).any() or h.low.gt(h[['open', 'close', 'high']].min(axis=1)).any():
        raise ValueError('MALFORMED_OHLC')
    return h


def events_after(events, endpoint, snapshot_asof):
    """Validate complete event chronology; only reverse the baked post-D suffix."""
    d, asof = int(day(endpoint)), int(day(snapshot_asof))
    seen = []
    for event in events:
        ex = int(day(event['ex_date']))
        a, b, v = (float(event[k]) for k in ('a', 'b', 'volume_a'))
        if not np.isfinite([a, b, v]).all() or a <= 0 or v <= 0 or ex > asof:
            raise ValueError('INVALID_ADJUSTMENT_EVENT')
        seen.append(ex)
    if seen != sorted(set(seen)):
        raise ValueError('EVENT_ORDER_OR_DUPLICATE')
    if d > asof:
        raise ValueError('D_AFTER_SNAPSHOT')
    return [e for e in reversed(events) if int(day(e['ex_date'])) > d]


def inverse_price(value, events, endpoint, snapshot_asof):
    value = number(value)
    if value is None:
        return None
    for e in events_after(events, endpoint, snapshot_asof):
        value = (value - float(e['b'])) / float(e['a'])
    return value


def to_d_basis(history, events, endpoint, snapshot_asof):
    """Undo affine prices and independent volume factors. Amount stays raw CNY.

    This is an audit of already-normalized archived observations, not a claim
    that a 2026 factor snapshot was available in 2020. No positivity clipping.
    """
    h = checked_history(history, endpoint)
    suffix = events_after(events, endpoint, snapshot_asof)
    for e in suffix:
        before = h.trade_date.lt(day(e['ex_date']))
        h.loc[before, list(PRICE_COLUMNS)] = (h.loc[before, list(PRICE_COLUMNS)] - float(e['b'])) / float(e['a'])
        h.loc[before, 'volume'] /= float(e['volume_a'])
    checked_history(h, endpoint)
    return h, dict(events_undone=len(suffix), event_dates=[day(e['ex_date']) for e in suffix],
                   order='newest_first', amount_unchanged=bool(h.amount_cny.equals(history.amount_cny)),
                   price_clipping=False, post_d_price_bars=0, factor_suffix_purpose='undo_baked_future_normalization')


@dataclass(frozen=True)
class Anchors:
    root_date: str = ''
    active_date: str = ''
    active_low: float | None = None
    active_mid: float | None = None
    invalidation_price: float | None = None


def public_anchors(case: Mapping, events, endpoint, snapshot_asof):
    """Public hints are in the archive's QFQ basis and require the same inverse."""
    low = inverse_price(case.get('anchor_low_hint'), events, endpoint, snapshot_asof)
    mid = inverse_price(case.get('anchor_mid_hint'), events, endpoint, snapshot_asof)
    return Anchors(day(case.get('root_anchor_D_hint')), day(case.get('near_anchor_D_hint')), low, mid, low)


def _bar(h, value, endpoint):
    value = day(value)
    if not value or value > day(endpoint):
        return None
    selected = h.loc[h.trade_date.eq(value)]
    return selected.iloc[0] if len(selected) == 1 else None


def _mean(series, n):
    return float(series.iloc[-n:].mean()) if len(series) >= n else None


def _slope(series):
    y = series.to_numpy(float)
    x = np.arange(len(y), dtype=float)
    x -= x.mean()
    return float(x @ (y - y.mean()) / (x @ x))


def features(history, endpoint, anchors: Anchors):
    """Sixteen continuous values, with null for insufficient/unknown inputs.

    Active geometry uses the supplied causal low/mid. Root uses its dated bar;
    an absent anchor never becomes zero. D-time invalidation defaults to active
    low in public_anchors. Candle-down is C<O; up-volume is C>previous C.
    """
    h = checked_history(history, endpoint)
    d = h.iloc[-1]
    close = float(d.close)
    out = dict.fromkeys(FEATURES)
    tr = pd.concat([h.high - h.low, (h.high-h.close.shift()).abs(),
                    (h.low-h.close.shift()).abs()], axis=1).max(axis=1)
    atr20, atr5 = _mean(tr, 20), _mean(tr, 5)
    root = _bar(h, anchors.root_date, endpoint)
    active = _bar(h, anchors.active_date, endpoint)
    # Fail closed for an unavailable / post-D active bar, even if a level exists.
    low = number(anchors.active_low) if active is not None else None
    mid = number(anchors.active_mid) if active is not None else None
    invalid = number(anchors.invalidation_price) if active is not None else None
    out['active_intact_margin_atr'] = divide(close-low, atr20) if low is not None else None
    out['active_close_vs_low_pct'] = divide(close, low)
    out['active_close_vs_mid_pct'] = divide(close, mid)
    for name in ('active_close_vs_low_pct', 'active_close_vs_mid_pct'):
        out[name] = out[name]-1 if out[name] is not None else None
    out['invalidation_dist_atr'] = divide(close-invalid, atr20) if invalid is not None else None
    out['root_intact_margin_atr'] = divide(close-float(root.low), atr20) if root is not None else None
    out['close_vs_white_pct'] = divide(close, float(d.white))
    out['close_vs_yellow_pct'] = divide(close, float(d.yellow))
    for name in ('close_vs_white_pct', 'close_vs_yellow_pct'):
        out[name] = out[name]-1 if out[name] is not None else None
    for n in (5, 10):
        w = h.iloc[-n:]
        out[f'box_tightness_{n}d'] = divide(float(w.high.max()-w.low.min()), _mean(h.close, n)) if len(w) == n else None
    if len(h) >= 15:
        out['hl_convergence_slope_15d'] = divide(_slope(h.low.iloc[-15:])-_slope(h.high.iloc[-15:]), _mean(h.close, 15))
    out['atr_contraction_5v20'] = divide(atr5, atr20)
    platform = float(h.volume.iloc[-25:-5].mean()) if len(h) >= 25 else None
    peak = float(h.volume.iloc[-35:-5].nlargest(3).mean()) if len(h) >= 35 else None
    vol3 = _mean(h.volume, 3)
    out['vol_contraction_vs_platform'] = divide(vol3, platform)
    out['vol_contraction_vs_wave_peak'] = divide(vol3, peak)
    out['vol_d_vs_platform'] = divide(float(d.volume), platform)
    if len(h) >= 5 and platform is not None:
        down = h.iloc[-5:].loc[lambda x: x.close.lt(x.open), 'volume']
        out['max_dn_vol5_vs_plat'] = divide(float(down.max()) if len(down) else 0., platform)
    if len(h) >= 21:
        up = h.close.gt(h.close.shift()).iloc[-20:]
        out['up_vol_purity_20d'] = divide(float(h.volume.iloc[-20:][up].sum()), float(h.volume.iloc[-20:].sum()))
    if any(v is not None and not math.isfinite(v) for v in out.values()):
        raise ValueError('NONFINITE_FEATURE')
    return out


def diagnostic_reference_features(history, endpoint, reference):
    """DIAGNOSTIC ONLY: isolate published numeric anchor/version residuals.

    Reference levels are not passed into the production-safe public API.
    Reported reference dates use dated bars, reported low where available;
    midpoint is that dated bar's (O+C)/2. No reference label/flag is accepted.
    """
    h = checked_history(history, endpoint)
    active = _bar(h, reference.get('active_key_k_date'), endpoint)
    low = number(reference.get('active_anchor_low'))
    if low is None and active is not None:
        low = float(active.low)
    mid = float((active.open+active.close)/2) if active is not None else None
    anchors = Anchors(day(reference.get('root_key_k_date')), day(reference.get('active_key_k_date')),
                      low, mid, number(reference.get('invalidation_price')))
    return features(h, endpoint, anchors)
