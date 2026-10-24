"""Frozen research metrics. No files, data owners, network or trading access."""
from __future__ import annotations

from datetime import datetime
import math
import statistics

HORIZONS = (1, 2, 5)
METRIC_POLICY = {
    'version': 'US_HK_REPLAY_METRICS_V1', 'horizons': HORIZONS,
    'entry': 'NEXT_HK_SESSION_OPEN', 'exit': 'HORIZON_HK_SESSION_CLOSE',
    'benchmark': 'EFFECTIVE_DATED_HK_CONNECT_FULL_MARKET', 'costs': 'GROSS_ONLY',
    'daily_curve': 'UNIQUE_SELECTED_EQUAL_WEIGHT_1D; NA_BREAKS_SEGMENT',
    'missing_selected_price': 'WHOLE_DAY_NA_NO_REWEIGHTING',
    'sealed_fraction': 'FINAL_20_PERCENT_CEILING', 'purge_sessions': 5,
    'candidate_comparator': 'ORIGINAL_ORDER_UNIQUE_TOP10',
}


def frozen_split(sessions, eligible_dates):
    if list(sessions) != sorted(set(sessions)) or not set(eligible_dates) <= set(sessions):
        raise ValueError('SPLIT_DATES_INVALID')
    eligible = sorted(set(eligible_dates))
    if not eligible:
        return {'eligible_dates': [], 'train_dates': [], 'sealed_dates': [], 'purged_dates': []}
    count = math.ceil(len(eligible) / 5)
    sealed = eligible[-count:]
    boundary = sessions.index(sealed[0])
    purged = [d for d in eligible[:-count] if sessions.index(d) + 5 >= boundary]
    return {'eligible_dates': eligible, 'train_dates': [d for d in eligible[:-count] if d not in purged],
            'sealed_dates': sealed, 'purged_dates': purged}


def adjustment_available(events, *, as_of):
    """Every action actually used must be both effective and known by its price as-of."""
    try:
        cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
        if cutoff.tzinfo is None:
            return False
        for event in events:
            if event.get('applied') is not True:
                continue
            effective = datetime.fromisoformat(event['effective_at'].replace('Z', '+00:00'))
            available = datetime.fromisoformat(event['available_at'].replace('Z', '+00:00'))
            if effective.tzinfo is None or available.tzinfo is None or max(effective, available) > cutoff:
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def candidate_top10(symbols):
    return list(dict.fromkeys(symbols))[:10]


def rank_ic(scores, returns, *, same_date_universe_verified):
    if not same_date_universe_verified or set(scores) != set(returns) or len(scores) < 3:
        return None
    keys = sorted(scores)
    try:
        x, y = [float(scores[k]) for k in keys], [float(returns[k]) for k in keys]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in x + y) or len(set(x)) < 2 or len(set(y)) < 2:
        return None

    def ranks(values):
        ordered = sorted(range(len(values)), key=values.__getitem__)
        answer = [0.0] * len(values)
        start = 0
        while start < len(values):
            end = start + 1
            while end < len(values) and values[ordered[end]] == values[ordered[start]]:
                end += 1
            for i in ordered[start:end]:
                answer[i] = (start + end - 1) / 2
            start = end
        return answer

    a, b = ranks(x), ranks(y)
    ma, mb = statistics.mean(a), statistics.mean(b)
    return sum((i-ma)*(j-mb) for i, j in zip(a, b)) / math.sqrt(
        sum((i-ma)**2 for i in a) * sum((j-mb)**2 for j in b))


def _price(bars, symbol, day, field):
    value = bars.get(symbol, {}).get(day, {}).get(field)
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def evaluate_day(*, signal_date, sessions, selected_symbols, bars, complete,
                 pending_count, pit_price_verified, benchmark=None, scores=None,
                 entry_timestamp_verified=True, signal_cutoff=None):
    """Returns are decimal gross returns; price/PIT certification belongs to owner evidence.

    This pure function receives already frozen evidence, never resolves a universe.
    Intraday callers must supply a verified entry timestamp or remain engineering-only.
    """
    if list(sessions) != sorted(set(sessions)) or signal_date not in sessions:
        raise ValueError('SIGNAL_CALENDAR_INVALID')
    selected = list(dict.fromkeys(selected_symbols))
    common = []
    if complete is not True:
        common.append('INCOMPLETE_INPUT')
    if pending_count and not selected:
        common.append('PENDING_DECISIONS')
    if pit_price_verified is not True:
        common.append('PIT_PRICE_UNVERIFIED')
    if entry_timestamp_verified is not True:
        common.append('ENTRY_TIMESTAMP_UNVERIFIED')
    index = sessions.index(signal_date)
    output = {'signal_date': signal_date, 'unique_selected': selected, 'gross_only': True,
              'daily_1d_return': None, 'horizons': {}}
    for horizon in HORIZONS:
        reasons = list(common)
        row = {'horizon': horizon, 'interpretation': 'DAILY_PORTFOLIO' if horizon == 1 else 'OVERLAPPING_EVENT_RETURNS_NOT_PORTFOLIO',
               'status': 'NOT_EVALUABLE', 'mean': None, 'median': None, 'positive_fraction': None,
               'benchmark_mean': None, 'excess': None, 'rank_ic': None, 'events': {}, 'reasons': reasons}
        output['horizons'][str(horizon)] = row
        if reasons:
            continue
        if not selected:
            row.update(status='GENUINE_EMPTY', reasons=['NO_SELECTED_EVENTS'])
            if horizon == 1:
                output['daily_1d_return'] = 0.0
            continue
        if index + horizon >= len(sessions):
            reasons.append('EXIT_SESSION_UNAVAILABLE')
            continue
        entry_date, exit_date = sessions[index + 1], sessions[index + horizon]
        row.update(entry_date=entry_date, exit_date=exit_date)
        missing = []
        for symbol in selected:
            entry, exit_price = _price(bars, symbol, entry_date, 'open'), _price(bars, symbol, exit_date, 'close')
            if entry is None or exit_price is None:
                missing.append(symbol)
            else:
                row['events'][symbol] = exit_price / entry - 1
        if missing:
            reasons.append('SELECTED_ENTRY_OR_EXIT_MISSING')
            row['missing_symbols'] = missing
            # Preserve diagnostic partial events, never use them as the portfolio.
            continue
        values = list(row['events'].values())
        row.update(status='EVALUABLE_GROSS', mean=statistics.mean(values), median=statistics.median(values),
                   positive_fraction=sum(v > 0 for v in values) / len(values))
        if horizon == 1:
            output['daily_1d_return'] = row['mean']
        try:
            as_of = datetime.fromisoformat(signal_cutoff.replace('Z', '+00:00'))
            known = datetime.fromisoformat(benchmark['available_at'].replace('Z', '+00:00'))
            available = bool(as_of.tzinfo and known.tzinfo and known <= as_of)
        except (TypeError, ValueError, AttributeError, KeyError):
            available = False
        try:
            valid_interval = all(datetime.strptime(benchmark[k], '%Y%m%d').strftime('%Y%m%d') == benchmark[k]
                                 for k in ('effective_from', 'effective_through'))
        except (TypeError, ValueError, KeyError):
            valid_interval = False
        benchmark_ok = bool(isinstance(benchmark, dict)
            and benchmark.get('universe_ref') == 'HK_CONNECT_FULL_MARKET'
            and benchmark.get('verification') == 'VERIFIED'
            and isinstance(benchmark.get('source_sha256'), str) and len(benchmark['source_sha256']) == 64
            and all(c in '0123456789abcdef' for c in benchmark['source_sha256'])
            and available and valid_interval
            and benchmark.get('effective_from', '') <= entry_date <= benchmark.get('effective_through', '')
            and benchmark.get('symbols'))
        if not benchmark_ok:
            reasons.append('EFFECTIVE_DATED_BENCHMARK_UNAVAILABLE')
            continue
        returns = {}
        for symbol in dict.fromkeys(benchmark['symbols']):
            entry, exit_price = _price(bars, symbol, entry_date, 'open'), _price(bars, symbol, exit_date, 'close')
            if entry is None or exit_price is None:
                break
            returns[symbol] = exit_price / entry - 1
        if len(returns) != len(set(benchmark['symbols'])):
            reasons.append('BENCHMARK_ENTRY_OR_EXIT_MISSING')
            continue
        row['benchmark_mean'] = statistics.mean(returns.values())
        row['excess'] = row['mean'] - row['benchmark_mean']
        if scores is not None:
            row['rank_ic'] = rank_ic(scores, returns, same_date_universe_verified=True)
    return output


def continuous_curve(dates, daily_returns):
    """Reset at every NA. No continuous wealth/drawdown claim across missing dates."""
    segments, segment = [], None
    if list(dates) != sorted(set(dates)):
        raise ValueError('CURVE_DATES_INVALID')
    for day in dates:
        value = daily_returns.get(day)
        if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
            segment = None
            continue
        if segment is None:
            segment = {'dates': [], 'equity': [], 'initial_equity': 1.0}
            segments.append(segment)
        previous = segment['equity'][-1] if segment['equity'] else 1.0
        segment['dates'].append(day)
        segment['equity'].append(previous * (1 + float(value)))
    return segments
