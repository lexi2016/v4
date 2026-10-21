"""Exact-date incident adapter: replay a pinned existing provider response, zero network."""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from collections import Counter
import hashlib
import json
import math

DATE, STAGE = '20261021', 'STAGE_0930_0935'
START, END = '2026-10-21 09:30:00', '2026-10-21 09:35:00'
TIMES = tuple(f'2026-10-21 09:{m:02d}:00' for m in range(31, 36))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def audit_cache(pins):
    path = Path(pins['capture_path'])
    require(not path.is_symlink() and path.is_file(), 'capture is not regular')
    require(sha(path) == pins['capture_sha256'], 'capture bytes changed')
    d = json.loads(path.read_text())
    codes = pins['expected_codes']
    require(d['trade_date'] == DATE and d['stage_id'] == 'STAGE_0935_0940', 'source capture slot changed')
    require(d['market'] == 'HK_CONNECT' and d['adjustment'] == 'NONE', 'source market/adjustment changed')
    require(d['captured_at'] == '2026-10-21T09:41:22.678854+08:00', 'original capture clock changed')
    require(len(d['codes']) == 100 and set(d['codes']) == set(codes), 'source100 changed')
    require(not d['errors'] and not d['no_data_codes'], 'source errors require new review')
    target = [r for r in d['rows'] if START < str(r.get('time_key', '')) <= END]
    require(len(target) == 500 and {r['code'] for r in target} == set(codes), 'target500/100 changed')
    for code in codes:
        rows = [r for r in target if r['code'] == code]
        require(tuple(sorted(r['time_key'] for r in rows)) == TIMES, f'window gap/duplicate: {code}')
        for row in rows:
            for field in ('open', 'high', 'low', 'close', 'volume', 'turnover'):
                value = row.get(field)
                require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
                        f'nonfinite target {code}:{field}')
            require(all(row[f] > 0 for f in ('open', 'high', 'low', 'close')) and row['volume'] >= 0 and row['turnover'] >= 0,
                    f'invalid target value: {code}')
    return d, target


def cached_collector(runtime, config, pins, observed):
    from stage_center import live_collectors as lc
    dataset, target = audit_cache(pins)
    calls = []

    def replay_process(argv, **kwargs):
        request = json.loads(kwargs['input'])
        require(len(argv) == 3 and argv[0] == str(config.python_path) and argv[1] == '-c', 'probe argv changed')
        require(request == {'codes': list(pins['expected_codes']), 'num_bars': 1000, 'market': 'HK_CONNECT'},
                'cached request scope changed')
        require(kwargs.get('shell') is False, 'shell must be false')
        require(not calls, 'second provider replay refused')
        calls.append(request)
        payload = {k: dataset[k] for k in ('captured_at', 'rows', 'errors', 'no_data_codes')}
        return SimpleNamespace(returncode=0, stdout='__FUTU_MINUTE_JSON__' + json.dumps(payload, ensure_ascii=False), stderr='')

    def collect(plan, market):
        require(market == 'HK_CONNECT' and plan.trade_date == DATE and plan.stage_id == STAGE, 'collector scope changed')
        codes = tuple(plan.codes_for(market))
        require(list(codes) == pins['expected_codes'], 'ordered collector100 changed')
        require(plan.same_day_late_observation_recovery is True and not plan.historical_backfill, 'late observation mode absent')
        audit_cache(pins)
        source = lc.collect_hk_minute(plan, codes=codes, python_path=config.python_path,
            shared_root=config.shared_data_root, snapshot_root=None, process_runner=replay_process,
            replay_provider=None)
        require(source.source_id == 'futu' and source.status == 'PARTIAL_WITH_ROWS', 'observation route changed')
        require(len(source.rows) == 100 and not source.missing_symbols, 'aggregate100 incomplete')
        require({'FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE', 'HK_HISTORICAL_ORDERBOOK_UNAVAILABLE'} <= set(source.cannot_confirm),
                'observation gaps absent')
        require(all(r['window_start'] == TIMES[0] and r['window_end'] == TIMES[-1] and r['bar_count'] == 5 for r in source.rows),
                'strict bar window changed')
        source = replace(source, source_evidence=(*source.source_evidence,
            f"futu_capture_path={pins['capture_path']}", f"futu_capture_sha256={pins['capture_sha256']}",
            'recovery_route=EXISTING_FUTU_CAPTURE_CACHE_NO_REQUEST',
            'recovery_target_window=(09:30:00,09:35:00] Asia/Hong_Kong',
            'recovered_observation=true', 'natural_time_capture=CANNOT_CONFIRM',
            'formal_stage_eligibility=CANNOT_CONFIRM', 'pit_safe=false',
            'temporal_cutoff_safe_scope=BAR_TIMESTAMPS_ONLY_NOT_CAPTURE_CLOCK',
            'active_snapshot_authority=CANNOT_CONFIRM', 'provider_network_requests=0'))
        observed.update(collector_bound_codes=list(codes), aggregate_codes=[r['code'] for r in source.rows],
            original_capture_time=dataset['captured_at'], target_provider_bars=len(target),
            preserved_update_times=sorted({r['update_time'] for r in source.rows}),
            cached_bridge_replay_invocations=len(calls), provider_network_requests=0,
            source_cannot_confirm=list(source.cannot_confirm))
        return source
    return collect
