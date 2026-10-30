"""Offline durable reuse of accepted events; no event selection or data fetching.

Generation, input artifact and asof are provenance, not mathematical cache keys.
The explicit semantic identity and exact consumed inputs bind every stored value.
Return arithmetic and causal percentiles remain owned by research_daily_statistics.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean, median

from domains import research_daily_statistics as stats

IDENTITY_FIELDS = ('symbol', 'market', 'source_authority', 'basis', 'rule_sha256', 'formula_sha256')
HORIZONS = {'d2': 2, 'd5': 5}
DEFAULT_EDGES = (0., .2, .4, .6, .8, 1.)
VALID = {'positive', 'negative', 'flat'}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _price(value):
    """Represent the same numeric coercion as the original evaluator, including invalids."""
    status, number = stats._classify_price(value, field='cache.close')
    if status == 'valid':
        return [status, number]
    if status == 'nonpositive_price':
        return [status, float(value)]
    return [status]  # all nonfinite values have identical original classification


def _summary(cases, sessions):
    counts = {name: sum(case['status'] == name for case in cases) for name in stats._OUTCOME_STATUSES}
    values = [case['return_pct'] for case in cases if case['status'] in VALID]
    if sum(counts.values()) != len(cases):
        raise ValueError('UNRECOGNIZED_OUTCOME_STATUS')
    return dict(horizon_trading_sessions=sessions, total=len(cases), valid=len(values), **counts,
                mean_return_pct=mean(values) if values else None,
                median_return_pct=median(values) if values else None,
                positive_fraction=counts['positive'] / len(values) if values else None,
                reconciliation=dict(classified_total=len(cases), matches=True), cases=list(reversed(cases)))


class EventCaseCache:
    """One SQLite store, atomic transactions, caller-owned semantic identity.

    basis must describe the stable price/volume convention (not generation/asof).
    source_authority names the authoritative source, not an artifact generation.
    An asof QFQ price revision is detected from the consumed prices themselves.
    """
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS values_v1 (kind TEXT, identity TEXT, event TEXT, horizon TEXT, dependency TEXT, payload TEXT, PRIMARY KEY(kind,identity,event,horizon,dependency))')
        self.db.commit()
        self.counts = {}

    def close(self):
        self.db.close()

    def _get(self, kind, identity, event, horizon, dependency):
        record = self.db.execute('SELECT payload FROM values_v1 WHERE kind=? AND identity=? AND event=? AND horizon=? AND dependency=?',
                                 (kind, identity, event, horizon, dependency)).fetchone()
        return json.loads(record[0]) if record else None

    def _put(self, kind, identity, event, horizon, dependency, payload):
        self.db.execute('INSERT OR REPLACE INTO values_v1 VALUES(?,?,?,?,?,?)',
                        (kind, identity, event, horizon, dependency, _json(payload)))

    def build(self, *, identity, event_dates, close_rows, calendar, asof,
              bucket_edges=DEFAULT_EDGES, accepted_seed=None):
        """Return all outcomes and current-bin aggregates, never later-asof data.

        accepted_seed is only for exact, hash-verified accepted cases at this asof
        and with these prices/calendar/identity. The offline adapter enforces that
        binding; arbitrary or revised consumer inputs must omit it.
        """
        if any(not identity.get(key) for key in IDENTITY_FIELDS):
            raise ValueError('INCOMPLETE_SEMANTIC_IDENTITY')
        if not identity['symbol'].endswith('.' + identity['market']):
            raise ValueError('SYMBOL_MARKET_CONFLICT')
        namespace = _digest({**{key: identity[key] for key in IDENTITY_FIELDS},
                             'statistics_source_sha256': hashlib.sha256(Path(inspect.getfile(stats)).read_bytes()).hexdigest()})
        stats._iso_date(asof, field='asof')
        dates = list(calendar)
        for day in dates:
            stats._iso_date(day, field='calendar')
        if dates != sorted(set(dates)) or asof not in dates:
            raise ValueError('INVALID_CALENDAR_OR_ASOF')
        index = {day: i for i, day in enumerate(dates)}
        events = list(event_dates)
        if len(set(events)) != len(events) or any(day not in index or day > asof for day in events):
            raise ValueError('INVALID_EVENT_DATES')
        events.sort()
        rows = list(close_rows)
        row_dates = [row['date'] for row in rows]
        if row_dates != sorted(set(row_dates)):
            raise ValueError('CLOSE_DATES_NOT_UNIQUE_INCREASING')
        for day in row_dates:
            stats._iso_date(day, field='close.date')
        bydate = {row['date']: row.get('close') for row in rows if row['date'] <= asof}
        edges = tuple(bucket_edges)
        if len(edges) < 2 or edges[0] != 0 or edges[-1] != 1 or any(not math.isfinite(v) for v in edges) or any(a >= b for a, b in zip(edges, edges[1:])):
            raise ValueError('INVALID_BUCKET_EDGES')
        self.counts = dict(return_evaluations=0, return_hits=0, seeded_returns=0, percentile_evaluations=0, percentile_hits=0)
        with self.db:
            ranks = self._ranks(namespace, events, rows, asof)
            horizons = {}
            for horizon, sessions in HORIZONS.items():
                cases = []
                for event in events:
                    start = index[event]
                    stop = start + sessions
                    target = dates[stop] if stop < len(dates) else None
                    matured = stop <= index[asof]
                    inputs = dict(calendar_slice=dates[start:min(stop + 1, len(dates))], matured=matured)
                    if matured:
                        inputs['price_pair'] = [[day, day in bydate, _price(bydate.get(day))] for day in (event, target)]
                    dependency = _digest(inputs)
                    case = self._get('return', namespace, event, horizon, dependency)
                    if case is None:
                        seed = accepted_seed.get(horizon, {}).get(event) if accepted_seed else None
                        if seed is not None:
                            case = {key: seed[key] for key in ('event_date', 'target_date', 'status', 'detail_status', 'return_pct')}
                            if case['event_date'] != event or case['target_date'] != target or (case['status'] != 'not_matured') != matured:
                                raise ValueError('SEED_DATE_OR_MATURITY_CONFLICT')
                            self.counts['seeded_returns'] += 1
                        else:
                            status, detail, target, value = stats._evaluate_event_return(event_date=event, horizon_sessions=sessions,
                                calendar=dates, calendar_index=index, asof_index=index[asof], close_by_date=bydate)
                            case = dict(event_date=event, target_date=target, status=status, detail_status=detail, return_pct=value)
                            self.counts['return_evaluations'] += 1
                        if case['status'] not in stats._OUTCOME_STATUSES or (case['status'] in VALID and (isinstance(case['return_pct'], bool) or not isinstance(case['return_pct'], (int, float)) or not math.isfinite(case['return_pct']))):
                            raise ValueError('INVALID_ACCEPTED_RETURN')
                        self._put('return', namespace, event, horizon, dependency, case)
                    else:
                        self.counts['return_hits'] += 1
                    percentile, n = ranks[event]
                    cases.append({**case, 'price_percentile': percentile, 'percentile_valid_closes': n,
                                  'percentile_status': 'KNOWN' if percentile is not None else 'UNKNOWN_INSUFFICIENT_OR_INVALID_PRICE',
                                  'percentile_bucket': self._bucket(percentile, edges)})
                value = _summary(cases, sessions)
                current = ranks[asof][0]
                bucket = self._bucket(current, edges)
                members = [case for case in cases if bucket is not None and case['percentile_bucket'] == bucket]
                valid = sum(case['status'] in VALID for case in members)
                value['conditional'] = dict(bucket=bucket, bucket_label=f'{edges[bucket]*100:g}–{edges[bucket+1]*100:g}%' if bucket is not None else 'UNKNOWN',
                    current_price_percentile=current, lookback=250, member_count=len(members), valid=valid,
                    **{key: sum(case['status'] == key for case in members) for key in ('positive', 'negative', 'flat', 'not_matured')},
                    positive_fraction=sum(case['status'] == 'positive' for case in members) / valid if valid else None,
                    unknown_percentile_events=sum(case['price_percentile'] is None for case in cases),
                    missing_or_invalid_return=sum(case['status'] not in VALID | {'not_matured'} for case in members),
                    status='AVAILABLE' if valid else 'INSUFFICIENT_SAMPLE')
                horizons[horizon] = value
        return dict(asof=asof, horizons=horizons, bucket_edges=list(edges), current_price_percentile=ranks[asof][0], cache=dict(self.counts), semantic_identity_sha256=namespace)

    @staticmethod
    def _bucket(percentile, edges):
        return next((i for i in range(len(edges)-1) if percentile is not None and edges[i] <= percentile and (percentile < edges[i+1] or i == len(edges)-2 and percentile <= 1)), None)

    def _ranks(self, namespace, events, rows, asof):
        wanted = set(events) | {asof}
        fingerprints = {}
        prefix = []
        for row in rows:
            day = row['date']
            if day > asof:
                break
            price = _price(row.get('close'))
            if price[0] == 'valid':
                prefix.append([day, price[1]])
                prefix = prefix[-250:]
            if day in wanted:
                fingerprints[day] = _digest(dict(valid_prefix=prefix, own_price=price))
        ranks = {}
        missing = []
        for day in sorted(wanted):
            fingerprint = fingerprints.setdefault(day, _digest(['NO_EVENT_BAR']))
            cached = self._get('percentile', namespace, day, '250', fingerprint)
            if cached is None:
                missing.append(day)
            else:
                ranks[day] = cached
                self.counts['percentile_hits'] += 1
        if missing:
            # Reuse the original percentile implementation. Returns here are
            # intentionally absent; it never evaluates or derives a return.
            dummy = [dict(event_date=day, status='not_matured', return_pct=None) for day in missing]
            result = stats.stratify_event_cases_by_prefix_percentile(close_rows=rows, event_cases={'d2': dummy, 'd5': copy.deepcopy(dummy)}, asof=asof)
            for case in result['horizons']['d2']['cases']:
                day = case['event_date']
                ranks[day] = [case['price_percentile'], case['percentile_valid_closes']]
                self._put('percentile', namespace, day, '250', fingerprints[day], ranks[day])
                self.counts['percentile_evaluations'] += 1
        return ranks
