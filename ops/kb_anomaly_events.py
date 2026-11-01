"""As-of anomaly wave observations for the existing KB research authority.

All windows and thresholds are engineering interpretations frozen in the
associated contract.  This module never generates an order or BUY decision.
The native anomaly flag is an input and is never replaced here.
"""
from __future__ import annotations

import math
import pandas as pd


PROCESS_FIELDS = (
    'kb_yidong_origin_line', 'kb_yidong_origin_distance_pct', 'kb_yidong_origin_class',
    'kb_yidong_origin_ma60_distance_pct', 'kb_yidong_origin_ma60_class',
    'kb_yidong_persistence_days5', 'kb_yidong_peak_ratio20', 'kb_yidong_strong_wave',
    'kb_yidong_anchor_date', 'kb_yidong_peak_date', 'kb_yidong_peak_close',
    'kb_yidong_peak_high', 'kb_yidong_pullback_date', 'kb_yidong_pullback_pct',
    'kb_yidong_pullback_vol_ratio', 'kb_yidong_ground_volume', 'kb_yidong_support_ok',
    'kb_yidong_resume_date', 'kb_yidong_resumed', 'kb_yidong_volume_resumed',
    'kb_yidong_breakout',
)


def _number(value, *, positive=False, nonnegative=False):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(value) or positive and value <= 0 or nonnegative and value < 0:
        return None
    return value


def _origin(close, line, tolerance=.05):
    close, line = _number(close, positive=True), _number(line, positive=True)
    if close is None or line is None:
        return None, 'UNKNOWN'
    distance = close / line - 1
    near = distance <= tolerance or math.isclose(distance, tolerance, rel_tol=0, abs_tol=1e-12)
    return distance * 100, ('BELOW' if distance <= 0 else 'NEAR' if near else 'EXTENDED')


def _tri_and(*values):
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def _as_bool(value):
    if value is None or pd.isna(value):
        return None
    if value not in (True, False):
        raise ValueError('ANOMALY_FLAG_INVALID')
    return bool(value)


def project_anomaly_events(frame):
    """Return 21 aligned columns and all per-as-of anchor states.

    The anchor window contains the 20 bars strictly before each as-of bar;
    selection prefers the most advanced eligible state, then the newest
    anchor. The ledger includes all prior observed anchors in that window.
    """
    required = {'trade_date', 'open', 'high', 'low', 'close', 'volume', 'pct_chg',
                'ma60', 'zge_yellow_line', 'kb_yidong'}
    if not required.issubset(frame.columns):
        raise ValueError('ANOMALY_INPUT_MISSING:' + ','.join(sorted(required-set(frame.columns))))
    rows = frame.reset_index(drop=True).to_dict('records')
    dates = [int(row['trade_date']) for row in rows]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError('ANOMALY_DATES_NOT_UNIQUE_SORTED')
    volumes = [_number(row['volume'], nonnegative=True) for row in rows]
    pct = [_number(row['pct_chg']) for row in rows]
    out, ledger, active, expansions, coverage = [], [], [], [], []
    for i, row in enumerate(rows):
        close = _number(row['close'], positive=True)
        high = _number(row['high'], positive=True)
        low = _number(row['low'], positive=True)
        vol = volumes[i]
        yellow = _number(row['zge_yellow_line'], positive=True)
        prior_yellow = _number(rows[i-1]['zge_yellow_line'], positive=True) if i else None
        previous_close = _number(rows[i-1]['close'], positive=True) if i else None
        prior_volumes = volumes[i-5:i] if i >= 5 else []
        avg5 = sum(prior_volumes)/5 if len(prior_volumes) == 5 and all(x is not None for x in prior_volumes) else None
        ratio = vol/avg5 if vol is not None and avg5 is not None and avg5 > 0 else None
        expansions.append(None if ratio is None or pct[i] is None else ratio >= 2 and pct[i] > 0)
        window = expansions[max(0, i-4):i+1]
        persistent = sum(window) if len(window) == 5 and all(x is not None for x in window) else None
        recent = volumes[i-4:i+1] if i >= 4 else []
        preceding = volumes[i-24:i-4] if i >= 24 else []
        peak_ratio = (max(recent)/max(preceding) if len(recent) == 5 and len(preceding) == 20
                      and all(x is not None for x in recent+preceding) and max(preceding) > 0 else None)
        latest = rows[max(0, i-4):i+1]
        candles = [(_number(x['open'], positive=True), _number(x['close'], positive=True)) for x in latest]
        red = sum(c > o for o, c in candles) if len(candles) == 5 and all(o is not None and c is not None for o,c in candles) else None
        james = (None if i < 64 or ratio is None or pct[i] is None else False if ratio < 3 or pct[i] < 5
                 else None if red is None else red >= 3)
        if _as_bool(row['kb_yidong']) is None:
            james = None
        pre_origin = _origin(previous_close, prior_yellow) if i else (None, 'UNKNOWN')
        strong = _tri_and(james, None if pre_origin[1] == 'UNKNOWN' else pre_origin[1] in ('BELOW','NEAR'),
                          None if persistent is None else persistent >= 2,
                          None if peak_ratio is None else peak_ratio > 1)
        active = [e for e in active if i-e['anchor_i'] <= 20]
        for e in active:
            e['today_resumed'] = e['today_volume_resumed'] = e['today_breakout'] = None
            if e['origin_class'] not in ('BELOW','NEAR') or e['broken']:
                continue
            opening = _number(row['open'], positive=True)
            if (low is None or close is None or high is None or vol is None or opening is None
                    or not low <= close <= high or not low <= opening <= high):
                e['incomplete'] = True
                continue
            if e['incomplete']:
                continue
            e['min_low'] = min(e['min_low'], low)
            if e['min_low'] < e['anchor_low']:
                e['broken'] = True
                continue
            if e['pullback_i'] is None:
                e['today_resumed'] = e['today_volume_resumed'] = e['today_breakout'] = False
            if e['resume_i'] is not None:
                e['today_resumed'] = (None if previous_close is None else
                                      close > previous_close and close > e['pullback_close'])
                e['today_volume_resumed'] = (None if e['today_resumed'] is None or volumes[i-1] is None else
                                             e['today_resumed'] and vol > volumes[i-1])
                e['today_breakout'] = (None if e['today_volume_resumed'] is None else
                                       e['today_volume_resumed'] and close > e['high_through_q'])
                continue
            if e['pullback_i'] is not None:
                q = e['pullback_i']
                if previous_close is not None and close > previous_close and close > e['pullback_close']:
                    e['resume_i'] = i
                    e['volume_resumed'] = None if volumes[i-1] is None else vol > volumes[i-1]
                    e['breakout'] = None if e['volume_resumed'] is None else e['volume_resumed'] and close > e['high_through_q']
                    e['today_resumed'], e['today_volume_resumed'], e['today_breakout'] = True, e['volume_resumed'], e['breakout']
                    continue
                e['today_resumed'] = False if previous_close is not None else None
                e['today_volume_resumed'] = False if previous_close is not None else None
                e['today_breakout'] = False if previous_close is not None else None
                # A lower pullback close supersedes q only when it still meets the frozen shrink condition.
                if close < e['pullback_close'] and vol < e['rally_mean']:
                    e['pullback_i'], e['pullback_close'] = i, close
                    e['pullback_vol'] = vol
                    e['high_through_q'] = max(e['high_seen'], high)
                    e['stage_min'] = min(e['stage_min'], vol)
                    e['ground_tie_count'] = sum(v == vol for v in volumes[e['anchor_i']:i+1] if v is not None)
                    e['q_yellow'], e['q_yellow_slope'] = yellow, None if yellow is None or prior_yellow is None else yellow-prior_yellow
                e['high_seen'] = max(e['high_seen'], high)
                e['stage_min'] = min(e['stage_min'], vol)
                continue
            if close < e['peak_close'] and e['above_line_by_peak'] and vol < e['rally_mean']:
                e['pullback_i'], e['pullback_close'], e['pullback_vol'] = i, close, vol
                e['high_through_q'] = max(e['high_seen'], high)
                e['high_seen'] = e['high_through_q']
                e['stage_min'] = min(e['stage_min'], vol)
                e['ground_tie_count'] = sum(v == vol for v in volumes[e['anchor_i']:i+1] if v is not None)
                e['q_yellow'], e['q_yellow_slope'] = yellow, None if yellow is None or prior_yellow is None else yellow-prior_yellow
                e['today_resumed'] = e['today_volume_resumed'] = e['today_breakout'] = False
                continue
            e['rally_vol_sum'] += vol
            e['rally_vol_count'] += 1
            e['volume_peak_seen'] = max(e['volume_peak_seen'], vol)
            e['high_seen'] = max(e['high_seen'], high)
            e['stage_min'] = min(e['stage_min'], vol)
            if yellow is not None and close > yellow:
                e['has_above_line'] = True
                if e['cross_i'] is None and previous_close is not None and prior_yellow is not None and previous_close <= prior_yellow:
                    e['cross_i'] = i
            if close > e['peak_close']:
                e['peak_i'], e['peak_close'], e['peak_high'] = i, close, high
                e['rally_mean'] = e['rally_vol_sum']/e['rally_vol_count']
                e['rally_vol_peak'] = e['volume_peak_seen']
                e['rally_high'] = e['high_seen']
                e['above_line_by_peak'] = e['has_above_line']
        native = _as_bool(row['kb_yidong'])
        if native is True:
            ma_distance, ma_class = _origin(previous_close, rows[i-1]['ma60']) if i else (None,'UNKNOWN')
            distance, origin_class = pre_origin
            opening = _number(row['open'], positive=True)
            valid = (all(v is not None for v in (close, high, low, vol, opening))
                     and low <= close <= high and low <= opening <= high)
            e = dict(anchor_i=i, origin_line=prior_yellow, origin_distance_pct=distance,
                     origin_class=origin_class, origin_class_3pct=_origin(previous_close, prior_yellow, .03)[1],
                     ma60_distance_pct=ma_distance, ma60_class=ma_class,
                     anchor_low=low, anchor_vol=vol, peak_i=i, peak_close=close, peak_high=high,
                     rally_high=high, high_seen=high, volume_peak_seen=vol,
                     rally_vol_sum=vol, rally_vol_count=1, rally_mean=vol, rally_vol_peak=vol,
                     stage_min=vol, min_low=low, pullback_i=None, resume_i=None, broken=False,
                     incomplete=not valid, has_above_line=bool(valid and yellow is not None and close > yellow),
                     above_line_by_peak=bool(valid and yellow is not None and close > yellow),
                     today_resumed=False, today_volume_resumed=False, today_breakout=False,
                     cross_i=(i if valid and yellow is not None and close > yellow and previous_close is not None
                              and prior_yellow is not None and previous_close <= prior_yellow else None))
            active.append(e)
        opening = _number(row['open'], positive=True)
        bar_valid = (all(v is not None for v in (close, high, low, vol, opening, pct[i]))
                     and low <= close <= high and low <= opening <= high)
        coverage.append(bool(bar_valid and native is not None and
                             (native is False or pre_origin[1] != 'UNKNOWN')))
        known20 = (i >= 20 and bar_valid and all(coverage[i-20:i])
                   and not any(e['incomplete'] for e in active if e['anchor_i'] < i))
        result = dict.fromkeys(PROCESS_FIELDS)
        result.update(kb_yidong_persistence_days5=persistent, kb_yidong_peak_ratio20=peak_ratio,
                      kb_yidong_strong_wave=strong)
        def state(e):
            return (4 if e['resume_i'] is not None and e.get('breakout') is True else
                    3 if e['resume_i'] is not None and e.get('volume_resumed') is True else
                    2 if e['resume_i'] is not None else 1 if e['pullback_i'] is not None else 0)
        eligible = [e for e in active if e['anchor_i'] < i and e['origin_class'] in ('BELOW','NEAR') and not e['broken'] and not e['incomplete']]
        selected = max(eligible, key=lambda e:(state(e),e['anchor_i'])) if eligible else None
        if selected is not None:
            e=selected; q=e['pullback_i']; r=e['resume_i']
            result.update(kb_yidong_origin_line=e['origin_line'], kb_yidong_origin_distance_pct=e['origin_distance_pct'],
                          kb_yidong_origin_class=e['origin_class'], kb_yidong_origin_ma60_distance_pct=e['ma60_distance_pct'],
                          kb_yidong_origin_ma60_class=e['ma60_class'], kb_yidong_anchor_date=dates[e['anchor_i']],
                          kb_yidong_peak_date=dates[e['peak_i']], kb_yidong_peak_close=e['peak_close'],
                          kb_yidong_peak_high=e['peak_high'], kb_yidong_support_ok=True,
                          kb_yidong_resumed=True if r is not None else False if known20 else None,
                          kb_yidong_volume_resumed=e.get('volume_resumed') if r is not None else False if known20 else None,
                          kb_yidong_breakout=e.get('breakout') if r is not None else False if known20 else None)
            if q is not None:
                result.update(kb_yidong_pullback_date=dates[q],
                              kb_yidong_pullback_pct=100*(1-e['pullback_close']/e['peak_close']),
                              kb_yidong_pullback_vol_ratio=e['pullback_vol']/e['rally_mean'] if e['rally_mean'] else None,
                              kb_yidong_ground_volume=e['pullback_vol'] <= min(volumes[e['anchor_i']:q+1]))
            if r is not None:result['kb_yidong_resume_date']=dates[r]
        elif known20:
            result.update(kb_yidong_resumed=False, kb_yidong_volume_resumed=False, kb_yidong_breakout=False)
        ledger.append(dict(asof_date=dates[i], anchor_date=None, state='COVERAGE', complete_20=known20,
                           today_resumed=False if known20 else None,
                           today_volume_resumed=False if known20 else None,
                           today_breakout=False if known20 else None))
        for e in (event for event in active if event['anchor_i'] < i):
            q=e['pullback_i'];r=e['resume_i'];a=e['anchor_i']
            ledger.append(dict(asof_date=dates[i], anchor_date=dates[a], origin_line_version='YELLOW_CURRENT_TEXT_VERSION',
                origin_distance_pct=e['origin_distance_pct'], origin_class=e['origin_class'],
                origin_class_3pct=e['origin_class_3pct'], ma60_distance_pct=e['ma60_distance_pct'], ma60_class=e['ma60_class'],
                crossing_date=dates[e['cross_i']] if e['cross_i'] is not None else None,
                anchor_low=e['anchor_low'], peak_date=dates[e['peak_i']], peak_close=e['peak_close'], peak_high=e['peak_high'],
                rally_high=e['rally_high'],
                pullback_date=dates[q] if q is not None else None, resume_date=dates[r] if r is not None else None,
                volume_vs_anchor=(e['pullback_vol']/e['anchor_vol'] if q is not None and e['anchor_vol'] else None),
                volume_vs_rally_peak=(e['pullback_vol']/e['rally_vol_peak'] if q is not None and e['rally_vol_peak'] else None),
                volume_vs_rally_mean=(e['pullback_vol']/e['rally_mean'] if q is not None and e['rally_mean'] else None),
                ground_volume=(e['pullback_vol']<=min(volumes[a:q+1]) if q is not None else None),
                ground_tie_count=e.get('ground_tie_count'), yellow_slope=e.get('q_yellow_slope'),
                yellow_close_held=(e['pullback_close']>=e['q_yellow'] if q is not None and e.get('q_yellow') is not None else None),
                yellow_low_held=(rows[q]['low']>=e['q_yellow'] if q is not None and e.get('q_yellow') is not None else None),
                anchor_low_held=False if e['broken'] else None if e['incomplete'] else True,
                volume_resumed=e.get('volume_resumed'), breakout=e.get('breakout'),
                complete_20=known20, today_resumed=e.get('today_resumed'),
                today_volume_resumed=e.get('today_volume_resumed'), today_breakout=e.get('today_breakout'),
                state=('ANCHOR_LOW_BROKEN' if e['broken'] else 'UNKNOWN' if e['incomplete'] else
                       'EXTENDED_OR_UNKNOWN_ORIGIN' if e['origin_class'] not in ('BELOW','NEAR') else
                       'BREAKOUT' if state(e)==4 else 'VOLUME_RESUMED' if state(e)==3 else
                       'RESUMED' if state(e)==2 else 'SHRINK_PULLBACK' if state(e)==1 else 'ANOMALY_OBSERVED')))
        out.append(result)
    return pd.DataFrame(out, columns=PROCESS_FIELDS), ledger
