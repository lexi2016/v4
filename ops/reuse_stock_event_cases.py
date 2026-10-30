"""Seed/read durable outcomes from completed frozen R2 shards, offline only.

Does not run labels, formula, source acquisition, publication, or the R2 runner.
Repeated invocations discover newly completed shards; existing outcomes are hits.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from domains.research_event_case_cache import EventCaseCache
from ops.bootstrap_stock_event_history import canonical, load, retained_sample, save, stats_date

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def consume(batch, store, output, *, symbols=None, asof=None, require_complete=False):
    permit = json.loads((batch / 'RUN_AUTHORIZATION_R2.json').read_bytes())
    contract_ref = permit['contract']
    contract = load(contract_ref)
    if permit['status'] != 'ROOT_RUN_STARTED_REGISTERED' or permit['contract_sha256'] != contract_ref['sha256']:
        raise ValueError('REGISTERED_CONTRACT_REQUIRED')
    for reference in contract['code']:
        if hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest() != reference['sha256']:
            raise ValueError('FROZEN_STATISTICS_OR_RUNNER_DRIFT')
    target = stats_date(contract['config']['target'])
    asof = asof or target
    if asof > target:
        raise ValueError('FROZEN_SOURCE_CANNOT_SUPPLY_LATER_ASOF')
    if require_complete:
        summary = json.loads((batch / 'RESULT.json').read_bytes())
        expected = set(contract['config']['symbols'])
        if (summary['status'] != 'COMPLETE_DESCRIPTIVE_NONPIT' or summary['contract'] != contract_ref or
            summary['remaining'] or summary['failures'] or summary['completed_count'] != len(expected) or
            set(summary['symbols']) != expected or set(summary['results']) != expected or
            not summary['original_numeric_and_chart_refs_unchanged']):
            raise ValueError('FROZEN_BATCH_NOT_COMPLETE')
        for reference in summary['results'].values():
            load(reference)
    requested = sorted(symbols or contract['config']['symbols'])
    if not set(requested) <= set(contract['config']['symbols']):
        raise ValueError('SYMBOL_OUTSIDE_FROZEN_SCOPE')
    calendars = load(contract['refs']['calendar'])['dates']
    cache = EventCaseCache(store)
    completed, pending = {}, []
    totals = dict(return_evaluations=0, return_hits=0, seeded_returns=0, percentile_evaluations=0, percentile_hits=0, repeat_return_evaluations=0, repeat_percentile_evaluations=0)
    try:
        for symbol in requested:
            done = batch / 'stocks' / symbol / 'RESULT.json'
            if not done.exists():
                pending.append(symbol)
                continue
            result = json.loads(done.read_bytes())
            if result['contract'] != contract_ref or result['status'] != 'COMPLETE_DESCRIPTIVE_NONPIT':
                raise ValueError('COMPLETED_STOCK_CONTRACT_CONFLICT:' + symbol)
            cases = load(result['event_cases'])
            row = load(result['row'])
            history = load(result['history_cache'])
            entry = contract['entries'][symbol]
            projection = load(entry['projection'])
            _, bars = retained_sample(projection, load(entry['source_cache']))
            bound_calendar = load(cases['calendar'])
            calendar_dates = bound_calendar['dates']
            if isinstance(calendar_dates, dict):
                calendar_dates = calendar_dates[symbol[-2:]]
            if calendar_dates != calendars[symbol[-2:]]:
                raise ValueError('ACCEPTED_CALENDAR_VALUES_CONFLICT:' + symbol)
            if (cases['symbol'] != symbol or cases['contract'] != contract_ref or
                cases['accepted_cache'] != result['history_cache'] or
                cases['projection'] != entry['projection'] or
                cases['source_generation'] != contract['source_generation'] or
                cases['input_sha256'] != contract['input_sha256'] or
                cases['statistics_sha256'] != hashlib.sha256(canonical(row['statistics'])).hexdigest() or
                history['source_identity'] != contract['source_identity']):
                raise ValueError('ACCEPTED_EVENT_SOURCE_BINDING_CONFLICT:' + symbol)
            closes = [dict(date=stats_date(bar['trade_date']), close=float(bar['close'])) for bar in bars]
            calendar = [stats_date(day) for day in calendars[symbol[-2:]]]
            basis = {key: value for key, value in contract['source_identity']['basis'].items() if key != 'asof_date'}
            identity = dict(symbol=symbol, market=symbol[-2:], basis=basis,
                source_authority=dict(reader=contract['refs']['reader']),
                rule_sha256=history['rule_sha256'], formula_sha256=contract['pins']['formula']['sha256'])
            groups = {}
            counters = []
            for group, horizons in cases['groups'].items():
                events = sorted(case['event_date'] for case in horizons['d2']['cases'] if case['event_date'] <= asof)
                if set(case['event_date'] for case in horizons['d5']['cases'] if case['event_date'] <= asof) != set(events):
                    raise ValueError('ACCEPTED_HORIZON_EVENT_CONFLICT')
                accepted_events = sorted(stats_date(day) for day, item in history['evaluations'].items() if item['groups'][group] == 'TRUE' and stats_date(day) <= asof)
                if events != accepted_events:
                    raise ValueError('ACCEPTED_CASE_COVERAGE_CONFLICT')
                seed = {key: {case['event_date']: case for case in value['cases']} for key, value in horizons.items()} if asof == target else None
                value = cache.build(identity=identity, event_dates=events, close_rows=closes, calendar=calendar, asof=asof, accepted_seed=seed)
                if asof == target and value['horizons'] != horizons:
                    raise ValueError('SEEDED_EVENT_CASE_PARITY_FAILED:' + symbol + ':' + group)
                repeated = cache.build(identity=identity, event_dates=events, close_rows=closes, calendar=calendar, asof=asof)
                if repeated['horizons'] != value['horizons'] or repeated['cache']['return_evaluations'] or repeated['cache']['percentile_evaluations']:
                    raise ValueError('PERSISTED_REPEAT_REUSE_FAILED')
                for key in value['cache']:
                    totals[key] += value['cache'][key]
                totals['repeat_return_evaluations'] += repeated['cache']['return_evaluations']
                totals['repeat_percentile_evaluations'] += repeated['cache']['percentile_evaluations']
                groups[group] = repeated['horizons']
                counters.append(dict(group=group, first=value['cache'], repeat=repeated['cache']))
            shard = dict(schema_version='v4.a_share.cached_event_cases.offline.v1', symbol=symbol, data_date=asof,
                source_event_cases=result['event_cases'], contract=contract_ref, semantic_identity=identity,
                groups=groups, reuse=counters, **FLAGS)
            completed[symbol] = save(output / 'event_cases' / f'{symbol}.json', shard)
    finally:
        cache.close()
    receipt = dict(status='OFFLINE_CACHE_CONSUMED' if not pending else 'OFFLINE_CACHE_PARTIAL_BATCH_RUNNING',
        contract=contract_ref, asof=asof, store=str(store.resolve()), requested_count=len(requested),
        completed_count=len(completed), pending=pending, event_cases=completed, reuse=totals,
        store_sha256=hashlib.sha256(store.read_bytes()).hexdigest(),
        live_installed=False, API_VERIFIED=False, UI_VERIFIED=False, **FLAGS)
    save(output / 'RECEIPT.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--symbol', action='append')
    parser.add_argument('--require-complete', action='store_true', help='Fail closed unless the exact frozen247 final R2 result is complete')
    parser.add_argument('--asof', help='Optional earlier ISO asof; uses only the frozen source')
    args = parser.parse_args()
    receipt = consume(args.batch, args.store, args.output, symbols=args.symbol, asof=args.asof, require_complete=args.require_complete)
    print(json.dumps({key: value for key, value in receipt.items() if key not in ('event_cases', 'pending')}, ensure_ascii=False))
