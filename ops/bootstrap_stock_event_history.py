"""Bounded catch-up adapter for the existing daily-product owner.

Consumes retained full-prefix formula projections; never calls a provider or
recomputes the formula. All output is isolated. --prepare only binds metadata;
--run requires the controller's registered contract receipt.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import gzip
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import re
import resource
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030')
DEFAULT_OUTPUT = BASE / 'stock_history_catchup_20261030'
MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-name-zoom-20261030-r1-main/app')
DATA = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
DAILY = BASE.parent / 'today_full_r1/daily_products/a_share'
TARGET = 20261029
GENERATION = '4787511e6c3125fa043fca9dafd2fdd3fa9496970220a3f0792cfe9732ce1a09'
INPUT = '4ece54421d52a4ab488f06a06c8598b961c30ffbaf631bc7b9933b74161068b2'
RULE = '48cccee9eb4c77d2d09965a3e25354580278d14605e835d28833998a327c39e3'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
_STATE = None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ref(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def load(reference):
    path = Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or sha(path) != reference['sha256']:
        raise ValueError('FROZEN_REFERENCE_DRIFT:' + str(path))
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + f'.{os.getpid()}.pending')
    with temporary.open('xb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return ref(path)


def load_runtime():
    """Bind the actual owner, frozen rule, and accepted additive C9 statistics."""
    paths = {
        'ops.research_panel_daily_product': MAIN / 'ops/research_panel_daily_product.py',
        'domains.research_daily_product': ROOT / 'domains/research_daily_product.py',
        'domains.research_daily_statistics': ROOT / 'domains/research_daily_statistics.py',
    }

    class PinnedImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in paths:
                return importlib.util.spec_from_file_location(fullname, paths[fullname])
            if fullname.split('.')[0] in {'ops', 'domains', 'infrastructure', 'contracts', 'shared_data', 'upstreams'}:
                source = MAIN / Path(*fullname.split('.'))
                if source.with_suffix('.py').is_file():
                    return importlib.util.spec_from_file_location(fullname, source.with_suffix('.py'))
                if (source / '__init__.py').is_file():
                    return importlib.util.spec_from_file_location(fullname, source / '__init__.py', submodule_search_locations=[str(source)])
            return None

    sys.path[:0] = [str(ROOT), str(MAIN), str(MAIN / 'upstreams')]
    sys.meta_path.insert(0, PinnedImports())
    for name in paths:
        sys.modules.pop(name, None)
    owner = importlib.import_module('ops.research_panel_daily_product')
    importlib.import_module('domains.research_daily_product')
    stats = importlib.import_module('domains.research_daily_statistics')
    if sha(paths['domains.research_daily_product']) != RULE:
        raise ValueError('FROZEN_RULE_DRIFT')
    return owner, stats, paths


def projection_bars(projection):
    result = projection['formula_result']
    bars = [dict(trade_date=int(row['trade_date']), **{key: str(row['ohlcv'][key]) for key in ('open', 'high', 'low', 'close', 'vol')}) for row in result['rows']]
    dates = [bar['trade_date'] for bar in bars]
    if dates != sorted(set(dates)) or not dates or dates[-1] != TARGET:
        raise ValueError('PROJECTION_DATE_CONFLICT')
    if result['mode'] != 'prefix' or result['field_count'] != 51 or result['drawing_count'] != 22:
        raise ValueError('PROJECTION_FORMULA_DIMENSION_CONFLICT')
    return bars


def prefix_hashes(owner, bars):
    chain = hashlib.sha256(b'[')
    values = {}
    for index, bar in enumerate(bars):
        if index:
            chain.update(b',')
        chain.update(owner.canonical(bar))
        point = chain.copy()
        point.update(b']')
        values[index + 1] = point.hexdigest()
    return values


def retained_sample(projection, source_cache):
    samples = source_cache.get('samples', [source_cache['sample']] if 'sample' in source_cache else [])
    matching = [sample for sample in samples if sample['symbol'] == projection['symbol']]
    if len(matching) != 1 or source_cache['source'] != projection['source']:
        raise ValueError('PROJECTION_SOURCE_CACHE_SYMBOL_CONFLICT:' + projection['symbol'])
    sample = matching[0]
    bars = [dict(trade_date=int(bar['date']), **{key: str(bar[key if key != 'vol' else 'volume']) for key in ('open', 'high', 'low', 'close', 'vol')}) for bar in sample['bars']]
    rendered = projection_bars(projection)
    if len(bars) != len(rendered) or any(left['trade_date'] != right['trade_date'] or any(Decimal(left[key]) != Decimal(right[key]) for key in ('open', 'high', 'low', 'close', 'vol')) for left, right in zip(bars, rendered)):
        raise ValueError('PROJECTION_PRICE_PARITY_FAILED:' + projection['symbol'])
    # The engine serializes Decimal exponents with uppercase E. Preserve the
    # original reader float strings from the source cache for owner cache SHA.
    return sample, bars


def validate_cache(owner, cache, bars, identity, config):
    """Reject stale bindings rather than letting owner silently reset a cache."""
    if cache.get('rule_sha256') != RULE or cache.get('rules_signature') != owner.digest(config):
        raise ValueError('HISTORY_RULE_OR_CONFIG_DRIFT')
    if cache.get('source_identity') != identity:
        raise ValueError('HISTORY_SOURCE_DRIFT')
    dates = {str(bar['trade_date']) for bar in bars}
    if not set(cache['evaluations']) <= dates:
        raise ValueError('HISTORY_DATE_OUTSIDE_PREFIX')
    end = max(map(int, cache['evaluations']), default=0)
    if cache.get('prefix_sha256') != owner.digest([bar for bar in bars if bar['trade_date'] <= end]):
        raise ValueError('HISTORY_PREFIX_DRIFT')
    for item in cache['evaluations'].values():
        if item['source_identity'] != identity or set(item['groups']) != set(owner.GROUPS):
            raise ValueError('HISTORY_EVALUATION_BINDING_DRIFT')
        if any(value not in {'TRUE', 'FALSE', 'UNKNOWN'} for value in item['groups'].values()):
            raise ValueError('HISTORY_TRISTATE_INVALID')


class PurePrefixCache:
    """Cache original causal helpers, never the as-of predicate itself.

    normalize is row-local. Frozen fund_keys row i reads rows[:i+1], trailing
    MA20/40, previous row/PLRY, and breakout[i]. No forward/end-dependent read
    exists. Original full-sequence outputs thus equal each prefix's outputs.
    Every call still checks exact input-prefix equality.
    """
    def __init__(self, rule, bars, formula_rows):
        self.rule = rule
        self.original_normalize, self.original_fund_keys = rule.normalize, rule.fund_keys
        self.parsed = []
        for bar in bars:
            item = dict(date=int(bar['trade_date']))
            for key, alias in [('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'vol')]:
                number = rule._decimal_or_none(bar[alias])
                item[key] = str(number) if number is not None else 'NaN'
            self.parsed.append(item)
        self.normalized = self.original_normalize(self.parsed)
        self.breakout = [None if row['values']['突破'] is None else bool(row['values']['突破']) for row in formula_rows]
        self.keys = self.original_fund_keys(self.normalized, self.breakout)

    def normalize(self, rows):
        if not rows or rows != self.parsed[:len(rows)]:
            raise ValueError('CACHED_NORMALIZE_PREFIX_DRIFT')
        return self.normalized[:len(rows)]

    def fund_keys(self, rows, breakout):
        if not rows or rows != self.normalized[:len(rows)] or breakout != self.breakout[:len(rows)]:
            raise ValueError('CACHED_FUND_KEYS_PREFIX_DRIFT')
        return self.keys[:len(rows)]

    def install(self):
        self.rule.normalize, self.rule.fund_keys = self.normalize, self.fund_keys

    def restore(self):
        self.rule.normalize, self.rule.fund_keys = self.original_normalize, self.original_fund_keys


def prepare(output):
    owner, _, paths = load_runtime()
    index_ref = ref(DAILY / 'index.json')
    index = load(index_ref)
    manifest_ref = index['dates'][str(TARGET)]
    manifest = load(manifest_ref)
    product = load(manifest['artifact'])
    config_ref = product['source_config']
    config = load(config_ref)
    context = owner.SourceContext(DATA, TARGET, source_config=(config, config_ref))
    if context.generation != GENERATION or context.identity['input_sha256'] != INPUT or context.identity != product['source_identity']:
        raise ValueError('FROZEN_GENERATION_CONFLICT')
    charts_ref = ref(BASE / 'original_formula_charts_247/MANIFEST.json')
    charts = load(charts_ref)
    symbols = sorted(charts['samples'])
    selected = sorted(row['symbol'] for row in product['rows'] if row['groups'])
    if len(symbols) != 247 or symbols != selected:
        raise ValueError('CANDIDATE247_SCOPE_CONFLICT')
    calendar_ref = save(output / 'CALENDARS.json', dict(dates=context.calendars, source_generation=GENERATION, input_sha256=INPUT, future_calendar=config['future_calendar']))
    entries = {}
    for symbol in symbols:
        chart = charts['samples'][symbol]
        projection = load(chart['projection'])
        bars = projection_bars(projection)
        source = projection['source']
        if (projection['symbol'] != symbol or projection['data_date'] != str(TARGET)
                or projection['lineage']['source_identity'] != context.identity
                or source['generation_id'] != GENERATION or source['source_input_sha256'] != INPUT
                or projection['formula_result']['formula_sha256'] != config['formula']['sha256']):
            raise ValueError('PROJECTION_SOURCE_CONFLICT:' + symbol)
        cache_source_ref = {key: projection['source_cache'][key] for key in ('path', 'sha256')}
        source_cache = load(cache_source_ref)
        sample, bars = retained_sample(projection, source_cache)
        row_ref = product['row_refs'][symbol]
        row = load(row_ref)
        qualification = context.qualify(symbol)
        if qualification != row['qualification'] or qualification['status'] != 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
            raise ValueError('SOURCE_ADMISSION_CONFLICT:' + symbol)
        cache_ref = ref(DAILY / 'history' / RULE / symbol / 'checkpoint.json')
        cache = load(cache_ref)
        validate_cache(owner, cache, bars, context.identity, config)
        missing = sorted(set(str(bar['trade_date']) for bar in bars) - set(cache['evaluations']))
        if symbol == '002003.SZ' and (missing or not cache['coverage']['known_full_history']):
            raise ValueError('ACCEPTED002003_HISTORY_MISSING')
        entries[symbol] = dict(projection=chart['projection'], source_cache=cache_source_ref, prior_row=row_ref, prior_cache=cache_ref,
            bars_sha256=owner.digest(bars), rows=len(bars), first=bars[0]['trade_date'], last=bars[-1]['trade_date'], missing_dates=missing,
            qualification_sha256=owner.digest(qualification), display_name=sample['display_name'],
            unchanged_chart={key: chart[key] for key in ('html', 'projection', 'PNG')})
        if symbol == '002003.SZ':
            entries[symbol]['accepted_event_cases'] = ref(BASE / 'readable_stock_materials/event_cases/002003.SZ.json')
            accepted_cases = load(entries[symbol]['accepted_event_cases'])
            if accepted_cases['accepted_cache'] != cache_ref or accepted_cases['statistics_sha256'] != hashlib.sha256(canonical(row['statistics'])).hexdigest():
                raise ValueError('ACCEPTED002003_EVENT_CASE_BINDING_DRIFT')
    context.unchanged()
    refs = dict(index=index_ref, numeric_manifest=manifest_ref, numeric_product=manifest['artifact'], charts=charts_ref,
        calendar=calendar_ref, source_config=config_ref, receipt=context.receipt_ref, snapshot=context.snapshot_ref,
        quarantine=context.quarantine_ref, reader=context.reader_ref,
        pointers=[ref(context.pointer), ref(context.backpointer)], runtime_manifest=ref(MAIN.parent / 'release-manifest.json'))
    code = [ref(Path(__file__)), *[ref(path) for path in paths.values()]]
    settings = dict(target=TARGET, symbols=symbols, canary='001328.SZ', reuse_complete=['002003.SZ'], workers=14, queue=28,
        job_memory_limit_GiB=64, system_available_reserve_GiB=24, checkpoint_seconds=5, checkpoint_dates=25,
        percentile_window=250, percentile_edges=[0, .2, .4, .6, .8, 1], event_cases='ALL',
        pure_prefix_cache='ORIGINAL_NORMALIZE_AND_FUND_KEYS_ONCE_EXACT_PREFIX_ARGUMENTS',
        canary_parity_prefix_indices=[0, 40, -6],
        original_formula_engine_compute_calls=0, historical_PIT=False, maximum_claim='DIRECTION_ONLY')
    contract = dict(schema='v4.stock_history_catchup.v1', status='PREPARED_WAIT_ROOT_RUN_STARTED', GOAL='Fill only missing current-generation historical evaluations for candidate247 using retained formula results',
        WRITER='/root/stock_history_catchup_writer', BASELINE_ID='D29candidate247; accepted0020035266dates', ONE_VARIABLE='missing_history_cache_initialization',
        source_generation=GENERATION, input_sha256=INPUT, source_identity=context.identity, refs=refs, pins=config,
        code=code, config=settings, config_sha256=hashlib.sha256(canonical(settings)).hexdigest(), entries=entries,
        selector=dict(path=str(context.panel), stat={key: getattr(context.panel_stat, key) for key in ('st_size', 'st_mtime_ns', 'st_ino')}),
        output_root=str(output.resolve()), ALLOWED_PATHS=[str(output.resolve())],
        PASS_SIGNAL='247 exact coverage; same source/rule/calendar; current selection and original chart bytes unchanged; allcases reconcile; resumable',
        STOP_RULE='Isolate source drift/semantic conflict with checkpoint; never silently invalidate or restart all', **FLAGS)
    frozen_path = output / ('CONTRACT_' + hashlib.sha256(canonical(contract)).hexdigest() + '.json')
    if frozen_path.exists() and json.loads(frozen_path.read_bytes()) != contract:
        raise ValueError('IMMUTABLE_CONTRACT_CONFLICT')
    contract_ref = save(frozen_path, contract) if not frozen_path.exists() else ref(frozen_path)
    save(output / 'CONTRACT.json', contract)
    print(json.dumps(dict(status=contract['status'], contract=contract_ref, config_sha256=contract['config_sha256'], code=code,
        symbols=len(entries), missing_dates=sum(len(entry['missing_dates']) for entry in entries.values()),
        canary_missing=len(entries['001328.SZ']['missing_dates']), resources=settings), ensure_ascii=False), flush=True)


class Journal:
    """Small append-only recovery blocks, with fixed shared metadata binding."""
    def __init__(self, directory, binding, groups):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'dates.jsonl'
        self.groups = tuple(groups)
        metadata = directory / 'BINDING.json'
        if metadata.exists() and json.loads(metadata.read_bytes()) != binding:
            raise ValueError('CHECKPOINT_BINDING_DRIFT')
        if not metadata.exists():
            save(metadata, binding)
        self.values = {}
        self.chain = '0' * 64
        if self.path.exists():
            with self.path.open('rb+') as stream:
                end = 0
                while raw := stream.readline():
                    if not raw.endswith(b'\n'):
                        stream.truncate(end)  # only a crash-torn final block
                        break
                    item = json.loads(raw)
                    payload = {key: value for key, value in item.items() if key != 'sha256'}
                    if item['previous'] != self.chain or hashlib.sha256(canonical(payload)).hexdigest() != item['sha256']:
                        raise ValueError('CHECKPOINT_HASH_CHAIN_DRIFT')
                    for day, states in item['dates']:
                        self._validate(day, states)
                        if day in self.values and self.values[day] != states:
                            raise ValueError('CHECKPOINT_DATE_CONFLICT')
                        self.values[day] = states
                    self.chain = item['sha256']
                    end = stream.tell()
        self.pending = []
        self.last_flush = time.perf_counter()

    def _validate(self, day, states):
        if not str(day).isdigit() or len(str(day)) != 8 or set(states) != set(self.groups) or any(value not in {'TRUE', 'FALSE', 'UNKNOWN'} for value in states.values()):
            raise ValueError('CHECKPOINT_TRISTATE_INVALID')

    def add(self, day, states):
        day = str(day)
        self._validate(day, states)
        if day in self.values:
            if self.values[day] != states:
                raise ValueError('CHECKPOINT_DATE_CONFLICT')
            return
        self.values[day] = states
        self.pending.append([day, states])
        if len(self.pending) >= 25 or time.perf_counter() - self.last_flush >= 5:
            self.flush()

    def flush(self):
        if self.pending:
            item = dict(previous=self.chain, dates=self.pending)
            item['sha256'] = hashlib.sha256(canonical(item)).hexdigest()
            with self.path.open('ab') as stream:
                stream.write(canonical(item) + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            self.chain = item['sha256']
            self.pending = []
        self.last_flush = time.perf_counter()


def full_event_cases(stats, row, cache, bars, calendar, contract, entry):
    closes = [dict(date=stats_date(bar['trade_date']), close=float(bar['close'])) for bar in bars]
    dates = [stats_date(day) for day in calendar]
    positions = {day: index for index, day in enumerate(dates)}
    bydate = {bar['date']: bar['close'] for bar in closes}
    groups = {}
    for accepted in row['statistics']['groups']:
        group = accepted['group_id']
        events = sorted(stats_date(day) for day, item in cache['evaluations'].items() if item['groups'][group] == 'TRUE')
        horizons = {}
        for key, sessions in [('d2', 2), ('d5', 5)]:
            value = stats._horizon_statistics(events, horizon_sessions=sessions, calendar=dates, calendar_index=positions,
                asof_index=positions[stats_date(TARGET)], close_by_date=bydate, case_limit=max(20, len(events)))
            prior = accepted['horizons'][key]
            if {k: v for k, v in value.items() if k != 'cases'} != {k: v for k, v in prior.items() if k != 'cases'} or value['cases'][:len(prior['cases'])] != prior['cases']:
                raise ValueError('EVENT_CASE_AGGREGATE_PARITY_FAILED:' + group + ':' + key)
            horizons[key] = value
        strata = stats.stratify_event_cases_by_prefix_percentile(close_rows=closes,
            event_cases={key: value['cases'] for key, value in horizons.items()}, asof=stats_date(TARGET))
        for key, value in horizons.items():
            value['cases'] = strata['horizons'][key]['cases']
            value['conditional'] = strata['horizons'][key]['conditional']
        groups[group] = horizons
    return dict(schema_version='v4.a_share.event_cases.v1', symbol=row['symbol'], data_date=str(TARGET),
        numeric_manifest=contract['refs']['numeric_manifest'], source_generation=GENERATION, input_sha256=INPUT,
        statistics_sha256=hashlib.sha256(canonical(row['statistics'])).hexdigest(), projection=entry['projection'],
        calendar=contract['refs']['calendar'], groups=groups, **FLAGS)


def stats_date(day):
    text = str(day)
    return f'{text[:4]}-{text[4:6]}-{text[6:8]}'


def worker(symbol):
    owner, stats, context, contract, contract_ref = _STATE
    entry = contract['entries'][symbol]
    output = Path(contract['output_root'])
    done = output / 'stocks' / symbol / 'RESULT.json'
    if done.exists():
        previous = json.loads(done.read_bytes())
        if previous['contract'] != contract_ref:
            raise ValueError('COMPLETED_STOCK_CONTRACT_DRIFT')
        for key in ('row', 'history_cache', 'event_cases'):
            load(previous[key])
        return previous
    started = time.perf_counter()
    projection = load(entry['projection'])
    _, bars = retained_sample(projection, load(entry['source_cache']))
    if owner.digest(bars) != entry['bars_sha256'] or projection['lineage']['source_identity'] != context.identity:
        raise ValueError('WORKER_PREFIX_DRIFT:' + symbol)
    prior_row = load(entry['prior_row'])
    cache = load(entry['prior_cache'])
    validate_cache(owner, cache, bars, context.identity, context.config)
    qualification = prior_row['qualification']
    binding = dict(contract=contract_ref, symbol=symbol, source_identity=context.identity, config=contract['refs']['source_config'],
        rule_sha256=RULE, projection=entry['projection'], calendar=contract['refs']['calendar'], qualification_sha256=entry['qualification_sha256'])
    journal = Journal(output / 'journals' / symbol, binding, owner.GROUPS)
    known_dates = {str(bar['trade_date']) for bar in bars}
    if not set(journal.values) <= known_dates:
        raise ValueError('JOURNAL_DATE_OUTSIDE_PREFIX')
    template = dict(source_identity=context.identity, qualification=qualification, exact_full_conditions=True,
        historical_PIT=False, historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION')
    for day, states in journal.values.items():
        if day in cache['evaluations'] and states != cache['evaluations'][day]['groups']:
            raise ValueError('JOURNAL_PRIOR_CACHE_CONFLICT')
        cache['evaluations'][day] = dict(template, groups=states)
    cache_path = output / 'daily_products/a_share/history' / RULE / symbol / 'checkpoint.json'
    context.root = output / 'daily_products/a_share'
    original_digest, original_census = owner.digest, owner._census
    original_read, original_qualify = context.read, context.qualify
    engine = context.engine()
    original_compute = engine.compute
    cached_census = getattr(owner, '_catchup_census', None)
    if cached_census is None:
        compiled = {}
        def cached_census(reference, asof, observation):
            key = (reference['sha256'], asof, observation)
            if key not in compiled:
                compiled[key] = original_census(reference, asof, observation)
            return compiled[key]
        owner._catchup_census = cached_census
    hashes = prefix_hashes(owner, bars)
    def memo_digest(value):
        if isinstance(value, list) and value and len(value) in hashes and value[0] is bars[0] and value[-1] is bars[len(value) - 1]:
            # Owner builds these lists exclusively from this bound immutable bar
            # sequence; hashes are the same original canonical list digests.
            return hashes[len(value)]
        return original_digest(value)
    formula_calls = 0
    reused_results = 0
    rule = sys.modules['domains.research_daily_product']
    pure_cache = None if symbol == '002003.SZ' else PurePrefixCache(rule, bars, projection['formula_result']['rows'])
    parity_dates = {bars[index]['trade_date'] for index in contract['config']['canary_parity_prefix_indices']} if symbol == contract['config']['canary'] else set()
    parity_path = output / 'stocks' / symbol / 'PURE_PREFIX_PARITY.json'
    parity = []
    if parity_path.exists():
        saved_parity = json.loads(parity_path.read_bytes())
        if saved_parity['contract'] != contract_ref:
            raise ValueError('CANARY_PARITY_BINDING_DRIFT')
        parity = saved_parity['cases']
    def retained_compute(prefix, mode):
        nonlocal reused_results
        if mode != 'prefix' or prefix != bars:
            raise ValueError('FORMULA_RECOMPUTATION_FORBIDDEN')
        reused_results += 1
        return projection['formula_result']
    def evaluate(**kwargs):
        from domains.research_daily_product import evaluate_daily_product
        value = evaluate_daily_product(**kwargs)
        day = int(kwargs['asof'])
        if day in parity_dates and day not in {item['date'] for item in parity}:
            pure_cache.restore()
            try:
                legacy = evaluate_daily_product(**kwargs)
            finally:
                pure_cache.install()
            if owner.canonical(value) != owner.canonical(legacy):
                raise ValueError('PURE_PREFIX_CACHE_CANARY_PARITY_FAILED:' + str(day))
            parity.append(dict(date=day, prefix_rows=len(kwargs['fullprefix']), evaluation_sha256=original_digest(value)))
            save(parity_path, dict(contract=contract_ref, cases=parity, **FLAGS))
        if day < TARGET:
            journal.add(day, {group: value['groups'][group]['status'] for group in owner.GROUPS})
        if time.perf_counter() - evaluate.last_progress >= 5:
            context.unchanged()
            save(output / 'stocks' / symbol / 'PROGRESS.json', dict(status='RUNNING', symbol=symbol,
                evaluated_dates=len(set(cache['evaluations']) | set(journal.values)), available_dates=len(bars),
                last_date=day, elapsed_seconds=time.perf_counter() - started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
            evaluate.last_progress = time.perf_counter()
        return value
    evaluate.last_progress = started
    try:
        if symbol == '002003.SZ':
            row = copy.deepcopy(prior_row)
            cache_path_ref = entry['prior_cache']
        else:
            # Seed once, not at every checkpoint. Subsequent durable blocks are
            # compact groups only; final consumer-compatible cache is saved once.
            cache['prefix_sha256'] = original_digest(bars)
            owner.save(cache_path, cache)
            context.read = lambda requested: (bars, entry['display_name']) if requested == symbol else (_ for _ in ()).throw(ValueError('OUT_OF_SCOPE_SYMBOL'))
            context.qualify = lambda requested: qualification if requested == symbol else (_ for _ in ()).throw(ValueError('OUT_OF_SCOPE_SYMBOL'))
            engine.compute = retained_compute
            owner.digest = memo_digest
            owner._census = cached_census
            pure_cache.install()
            missing = [bar['trade_date'] for bar in bars if str(bar['trade_date']) not in cache['evaluations']]
            row, final_cache, final_path = owner.compute_stock(context, symbol, evaluate=evaluate,
                history_dates=missing, reuse_history_prefix=True)
            if not final_cache['coverage']['known_full_history'] or final_cache['coverage']['missing']:
                raise ValueError('HISTORY_REMAINING_DATES')
            if parity_dates and set(item['date'] for item in parity) != parity_dates:
                raise ValueError('CANARY_PREFIX_PARITY_COVERAGE_MISSING')
            cache = final_cache
            for key in ('groups', 'pending_groups', 'latest_new_anchor', 'reasons', 'risk_clear', 'evaluation', 'qualification'):
                if owner.canonical(row[key]) != owner.canonical(prior_row[key]):
                    raise ValueError('CURRENT_SELECTION_PARITY_FAILED:' + symbol + ':' + key)
            row = {**prior_row, 'statistics': row['statistics'], 'historical_coverage': row['historical_coverage']}
            cache_path_ref = owner.save(final_path, cache)
        journal.flush()
        if set(cache['evaluations']) != known_dates:
            raise ValueError('FULL_HISTORY_DATE_COVERAGE_FAILED')
        row.update(FLAGS)
        row_ref = save(output / 'rows' / (symbol + '.json'), row)
        cases = (load(entry['accepted_event_cases']) if symbol == '002003.SZ' else
            full_event_cases(stats, row, cache, bars, context.calendars[symbol[-2:]], contract, entry))
        cases['accepted_cache'] = cache_path_ref
        cases['contract'] = contract_ref
        cases_ref = save(output / 'event_cases' / (symbol + '.json'), cases)
        context.unchanged()
        result = dict(status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=symbol, contract=contract_ref, row=row_ref,
            history_cache=cache_path_ref, event_cases=cases_ref, available_dates=len(bars), evaluated_dates=len(cache['evaluations']),
            unknown_by_group=cache['coverage']['unknown_by_group'], remaining_dates=[], reused_complete=symbol == '002003.SZ',
            resumed_dates=len(journal.values), formula_engine_compute_calls=formula_calls, retained_formula_result_reads=reused_results,
            pure_prefix_parity=parity,
            elapsed_seconds=time.perf_counter() - started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            historical_PIT=False, maximum_claim='DIRECTION_ONLY', **FLAGS)
        save(done, result)
        return result
    except Exception as error:
        journal.flush()
        save(output / 'stocks' / symbol / 'ERROR.json', dict(status='CANNOT_CONFIRM', symbol=symbol, error=repr(error),
            checkpoint_dates=len(journal.values), contract=contract_ref, **FLAGS))
        raise
    finally:
        owner.digest, owner._census = original_digest, original_census
        context.read, context.qualify = original_read, original_qualify
        engine.compute = original_compute
        if pure_cache is not None:
            pure_cache.restore()


def run(output, authorization, phase):
    global _STATE
    permit = json.loads(authorization.read_bytes())
    contract_ref = permit.get('contract') or ref(output / 'CONTRACT.json')
    contract = load(contract_ref)
    if permit.get('status') != 'ROOT_RUN_STARTED_REGISTERED' or permit.get('contract_sha256') != contract_ref['sha256'] or not re.fullmatch('[a-f0-9]{64}', permit.get('event_sha256', '')):
        raise ValueError('ROOT_REGISTERED_RUN_AUTHORIZATION_REQUIRED')
    if str(output.resolve()) != contract['output_root']:
        raise ValueError('OUTPUT_SCOPE_DRIFT')
    for reference in contract['code']:
        if sha(reference['path']) != reference['sha256']:
            raise ValueError('FROZEN_CODE_DRIFT')
    for key, reference in contract['refs'].items():
        if key == 'pointers':
            for pointer in reference:
                if ref(pointer['path']) != pointer:
                    raise ValueError('SOURCE_POINTER_DRIFT')
        elif ref(reference['path']) != reference:
            raise ValueError('FROZEN_REFERENCE_DRIFT:' + reference['path'])
    owner, stats, _ = load_runtime()
    calendars = load(contract['refs']['calendar'])['dates']
    original_calendars = owner.SourceContext._calendars
    owner.SourceContext._calendars = lambda self: calendars
    try:
        context = owner.SourceContext(DATA, TARGET, source_config=(load(contract['refs']['source_config']), contract['refs']['source_config']))
    finally:
        owner.SourceContext._calendars = original_calendars
    if context.identity != contract['source_identity']:
        raise ValueError('REGISTERED_SOURCE_IDENTITY_DRIFT')
    if any(getattr(context.panel.stat(), key) != value for key, value in contract['selector']['stat'].items()):
        raise ValueError('REGISTERED_SELECTOR_DRIFT')
    # Load pinned engine code and shared raw G4 maps once before fork. compute is
    # replaced by the retained result inside each worker; no formula calculation.
    context.engine()
    canary_qualification = load(contract['entries'][contract['config']['canary']]['prior_row'])['qualification']
    for day in context.config.get('dated_g4_packages', {}):
        context.g4_reference(contract['config']['canary'], int(day), canary_qualification)
    context.unchanged()
    _STATE = owner, stats, context, contract, contract_ref
    canary_path = output / 'CANARY_RESULT.json'
    if phase == 'canary':
        result = worker(contract['config']['canary'])
        save(canary_path, result)
        print(json.dumps(dict(event='CANARY_PASS', symbol=result['symbol'], elapsed_seconds=result['elapsed_seconds'],
            evaluated_dates=result['evaluated_dates'], peak_rss_bytes=result['peak_rss_bytes'], result=ref(canary_path))), flush=True)
        return
    if not canary_path.exists() or load(ref(canary_path))['contract'] != contract_ref:
        raise ValueError('SAME_CONTRACT_CANARY_REQUIRED')
    symbols = contract['config']['symbols']
    results = {}
    failures = {}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=contract['config']['workers'], mp_context=multiprocessing.get_context('fork')) as pool:
        pending = {}
        iterator = iter(symbols)
        def submit():
            while len(pending) < contract['config']['queue']:
                try:
                    symbol = next(iterator)
                except StopIteration:
                    break
                pending[pool.submit(worker, symbol)] = symbol
        submit()
        while pending:
            completed, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
            for future in completed:
                symbol = pending.pop(future)
                try:
                    results[symbol] = future.result()
                except Exception as error:
                    failures[symbol] = repr(error)
                print(json.dumps(dict(event='STOCK_COMPLETE' if symbol in results else 'STOCK_CANNOT_CONFIRM', symbol=symbol,
                    completed=len(results), failed=len(failures), total=len(symbols), elapsed_seconds=time.perf_counter() - started)), flush=True)
            context.unchanged()
            save(output / 'BATCH_PROGRESS.json', dict(status='RUNNING', completed=sorted(results), failures=failures,
                remaining=sorted(set(symbols) - set(results) - set(failures)), elapsed_seconds=time.perf_counter() - started, **FLAGS))
            submit()
    context.unchanged()
    # All protected chart/source refs are read back mechanically, no GUI and no
    # formula/rule evaluation is repeated by this final integrity check.
    for symbol, entry in contract['entries'].items():
        for reference in entry['unchanged_chart'].values():
            if ref(reference['path']) != {key: reference[key] for key in ('path', 'sha256')}:
                raise ValueError('PROTECTED_ORIGINAL_CHART_DRIFT:' + symbol)
    for key in ('index', 'numeric_manifest', 'numeric_product'):
        if ref(contract['refs'][key]['path']) != contract['refs'][key]:
            raise ValueError('PROTECTED_NUMERIC_PRODUCT_DRIFT')
    remaining = sorted(set(symbols) - set(results))
    summary = dict(status='COMPLETE_DESCRIPTIVE_NONPIT' if not remaining else 'PARTIAL_CANNOT_CONFIRM', contract=contract_ref,
        symbols=symbols, completed_count=len(results), remaining=remaining, failures=failures,
        evaluated_dates=sum(item['evaluated_dates'] for item in results.values()), formula_engine_compute_calls=0,
        rows={symbol: item['row'] for symbol, item in results.items()}, event_cases={symbol: item['event_cases'] for symbol, item in results.items()},
        results={symbol: ref(output / 'stocks' / symbol / 'RESULT.json') for symbol in results},
        elapsed_seconds=time.perf_counter() - started, source_generation=GENERATION, input_sha256=INPUT,
        original_numeric_and_chart_refs_unchanged=True, historical_PIT=False, maximum_claim='DIRECTION_ONLY',
        API_VERIFIED=False, UI_VERIFIED=False, DEPLOYED=False, **FLAGS)
    save(output / 'RESULT.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key not in {'rows', 'event_cases', 'results', 'symbols'}}, ensure_ascii=False), flush=True)


_RETAINED_DEFINITIONS = (
    ('original_level1', '原式一级买点', 'original', 'user_v1_level1_buy_signal'),
    ('original_level2', '原式二级买点', 'original', 'user_v1_level2_buy_signal'),
    ('original_b1', '原式B1', 'original', 'user_v1_B1'),
    ('original_b2', '原式B2', 'original', 'user_v1_B2'),
    ('original_b3', '原式B3', 'original', 'user_v1_B3'),
    ('kb_b1', 'KB B1', 'kb', 'kb_b1'), ('kb_b2', 'KB B2', 'kb', 'kb_b2'),
    ('kb_b3', 'KB B3', 'kb', 'kb_b3'), ('kb_violence_k', 'KB暴力K', 'kb', 'kb_violence_k'),
    ('kb_fanbao', 'KB反包', 'kb', 'kb_fanbao'),
)


def retained_single_stock_statistics(rows, close_rows, calendar, identity):
    """Describe already materialized chart/KB labels for one stock, not R5 groups.

    The existing statistics authority supplies exact exchange-session outcomes
    and prefix-only position buckets. A label is never inferred from an UNKNOWN.
    Caller must validate the immutable source refs before calling this function.
    """
    from domains.research_daily_statistics import build_daily_event_statistics, stratify_event_cases_by_prefix_percentile

    market = identity.get('market')
    calendar_sha = identity.get('calendar_sha256')
    if (market not in {'SH', 'SZ', 'BJ'} or not isinstance(calendar_sha, str)
            or not re.fullmatch(r'[0-9a-f]{64}', calendar_sha)):
        raise ValueError('RETAINED_MARKET_CALENDAR_IDENTITY_UNBOUND')
    grouped, coverage = [], {}
    for group_id, label, namespace, field in _RETAINED_DEFINITIONS:
        dates, known, unknown = [], 0, 0
        for row in rows:
            value = row[namespace].get(field)
            if value is None:
                unknown += 1
            elif value is True or type(value) is int and value == 1:
                known += 1
                dates.append(str(row['trade_date'])[:4]+'-'+str(row['trade_date'])[4:6]+'-'+str(row['trade_date'])[6:])
            elif value is False or type(value) is int and value == 0:
                known += 1
            else:
                raise ValueError('RETAINED_SIGNAL_TRISTATE_INVALID:' + field)
        rule = hashlib.sha256(canonical({'namespace': namespace, 'field': field,
            'source_view_sha256': identity['source_view_sha256']})).hexdigest()
        group_identity = {'generation': identity['source_generation'], 'input': identity['input_sha256'],
            'formula': identity['formula_sha256'] if namespace == 'original' else identity['kb_contract_sha256'],
            'rule_sha256': rule, 'asof': identity['asof'], 'market': market,
            'calendar_sha256': calendar_sha,
            'basis': 'QFQ', 'pit_status': 'NONPIT'}
        grouped.append({'group_id': group_id, 'rule_sha256': rule, 'source_identity': group_identity, 'event_dates': dates})
        coverage[group_id] = {'label': label, 'namespace': namespace, 'field': field,
                              'known_dates': known, 'unknown_dates': unknown, 'event_dates': len(dates)}
    stats = build_daily_event_statistics(close_rows=close_rows, market_calendar=calendar,
        asof=identity['asof'], event_groups=grouped, case_limit=len(rows))
    for group in stats['groups']:
        horizons = group['horizons']
        stratified = stratify_event_cases_by_prefix_percentile(close_rows=close_rows,
            event_cases={key: horizons[key]['cases'] for key in ('d2', 'd5')}, asof=identity['asof'])
        group['coverage'] = coverage[group['group_id']]
        group['same_position'] = stratified
    return stats


def build_retained_single_stock(candidate_ref, calendar_ref, output_root, *, history_relocation_ref=None):
    """Bootstrap isolated single-stock event shard from the accepted projection."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    candidate = load(candidate_ref)
    binding = load(candidate['binding'])
    symbol = binding.get('symbol')
    if (candidate.get('candidate_generation') != binding.get('candidate_generation')
            or not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(binding.get('source_date','')))
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(binding.get('observation_date','')))
            or binding.get('historical_PIT') is not False
            or any(binding.get(k) != v for k, v in FLAGS.items())):
        raise ValueError('RETAINED_SINGLE_IDENTITY_CONFLICT')
    view_ref, selector_ref = binding['assets']['kb'], candidate['outputs']['selector']
    view, cal = load(view_ref), load(calendar_ref)
    if history_relocation_ref:
        from infrastructure.research_workbench_host import checked_relocated_parquet
        selector_input = pa.BufferReader(checked_relocated_parquet(selector_ref, history_relocation_ref))
    else:
        selector_input = load_path(selector_ref)
    selector = pq.read_table(selector_input, columns=['trade_date', 'ts_code', 'close'])
    prices = selector.to_pylist()
    market=symbol[-2:];asof=binding['source_date']
    if (cal.get('exchange') != market or cal.get('asof') != asof
            or cal.get('source_panel_sha256') != binding['candidate_identity']['baseline_panel_sha256']['selector']
            or view.get('candidate_generation') != binding['candidate_generation']
            or view.get('source_generation') != binding['source_generation']
            or view.get('source_input_sha256') != binding['source_input_sha256']
            or len(view['rows']) != len(prices) or len(prices) != binding.get('rows') or not prices):
        raise ValueError('RETAINED_SINGLE_INPUT_CONFLICT')
    close_rows = []
    for row, price in zip(view['rows'], prices):
        day = str(price['trade_date'])
        if price['ts_code'] != symbol or int(day) != row['trade_date']:
            raise ValueError('RETAINED_SINGLE_PREFIX_CONFLICT')
        close_rows.append({'date': day[:4]+'-'+day[4:6]+'-'+day[6:], 'close': price['close']})
    identity = {'source_generation': binding['source_generation'], 'input_sha256': binding['source_input_sha256'],
        'source_view_sha256': view_ref['sha256'], 'formula_sha256': binding['candidate_identity']['formula_sha256'],
        'kb_contract_sha256': binding['candidate_identity']['source_sha256']['contracts/a_share_kb_fields_v1.json'],
        'asof': asof, 'market':market, 'calendar_sha256':calendar_ref['sha256']}
    stats = retained_single_stock_statistics(view['rows'], close_rows, cal['days'], identity)
    shard = {'schema_version': 'v4.a_share.event_cases.single_research.v1', 'symbol': symbol,
        'data_date': asof.replace('-',''), 'observation_date': binding['observation_date'], 'source_generation': identity['source_generation'],
        'input_sha256': identity['input_sha256'], 'numeric_manifest': binding['numeric_manifest'],
        'source_candidate_generation': binding['candidate_generation'], 'source_candidate': candidate_ref,
        'source_selector': selector_ref, 'source_view': view_ref, 'market_calendar': calendar_ref,
        'history_source_relocation': history_relocation_ref,
        'producer_sha256': sha(__file__), 'statistics': stats, 'historical_PIT': False,
        'qualification': 'DESCRIPTIVE_RETAINED_LABELS_NONPIT_NOT_FORECAST', **FLAGS}
    digest = hashlib.sha256(canonical(shard)).hexdigest()
    path = Path(output_root) / 'daily_products/a_share/event_cases' / asof.replace('-','') / digest / (symbol + '.json')
    if path.exists():
        if load(ref(path)) != shard:
            raise ValueError('RETAINED_SINGLE_OUTPUT_CONFLICT')
        return ref(path)
    return save(path, shard)


def build_retained_pair_history(index_ref, symbol, calendar_ref, output_root, *, expected_projection_sha256):
    """Persist statistics over a verified pair's already-projected daily labels.

    The projection is one bounded batch produced by the existing view owner.
    The pair attestation is reused through stat checks, never rescanned per stock.
    """
    import io
    import pyarrow.parquet as pq

    if not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol):
        raise ValueError('RETAINED_PAIR_SYMBOL_INVALID')
    index=load(index_ref)
    if (index.get('schema')!='v4.workbench.generic_single_index.v1'
            or index.get('historical_PIT') is not False or any(index.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('RETAINED_PAIR_INDEX_CONFLICT')
    producer=index.get('projection_producer') or {}
    if (producer.get('sha256')!=expected_projection_sha256 or not re.fullmatch(r'[0-9a-f]{64}',str(expected_projection_sha256))):
        raise ValueError('RETAINED_PAIR_PROJECTION_PRODUCER_CONFLICT')
    load_path(producer)
    pair_ref=index['paired_receipt'];receipt=load(pair_ref);attestation=load(index['verified_pair'])
    if (receipt.get('status')!='CANDIDATE_READY' or receipt.get('historical_PIT') is not False
            or any(receipt.get(k)!=v for k,v in FLAGS.items())
            or receipt.get('generation_id')!=index.get('candidate_generation')
            or receipt.get('input_sha256')!=index.get('candidate_input_sha256')
            or receipt.get('candidate_sha256')!=index.get('pair_sha256')
            or set(receipt.get('candidates',{}))!={'selector','backtest'}
            or str(receipt.get('target_date'))!=str(index.get('source_date','')).replace('-','')
            or attestation.get('status')!='PASS' or attestation.get('generation_id')!=receipt['generation_id']
            or attestation.get('input_sha256')!=receipt['input_sha256']
            or attestation.get('candidate_receipt_sha256')!=pair_ref['sha256']
            or set(attestation.get('roles',{}))!={'selector','backtest'}):
        raise ValueError('RETAINED_PAIR_RECEIPT_CONFLICT')
    stamps={}
    for role in ('selector','backtest'):
        p=Path(receipt['candidates'][role]);proof=attestation['roles'][role]
        if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p:
            raise ValueError('RETAINED_PAIR_PATH_CONFLICT:'+role)
        stat=p.stat();stamp={'device':stat.st_dev,'inode':stat.st_ino,'size':stat.st_size,
                            'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns}
        if proof.get('path')!=str(p) or proof.get('sha256')!=receipt['candidate_sha256'][role] or proof.get('stat')!=stamp:
            raise ValueError('RETAINED_PAIR_ATTESTATION_CONFLICT:'+role)
        metadata=json.loads((pq.ParquetFile(p).schema_arrow.metadata or {})[b'a_share_qfq_contract_v1'])
        if (metadata.get('generation_id')!=receipt['generation_id'] or metadata.get('input_sha256')!=receipt['input_sha256']
                or metadata.get('research_scope')!='ADMITTED_A_SHARE'):
            raise ValueError('RETAINED_PAIR_FOOTER_CONFLICT:'+role)
        stamps[role]=(p,stamp)
    source=index.get('source_generation');source_input=index.get('input_sha256')
    if (source!=receipt['generation_id'] or source_input!=receipt['input_sha256']):
        upgrade=receipt.get('kb_initial_upgrade') or {}
        if (upgrade.get('source_generation_id')!=source
                or receipt.get('materialized_reuse_source_input_sha256')!=source_input
                or upgrade.get('baseline_panel_sha256')!=receipt.get('baseline_panel_sha256')):
            raise ValueError('RETAINED_PAIR_BASELINE_CONFLICT')
        expected_panel=receipt['baseline_panel_sha256']['selector']
    else:expected_panel=receipt['candidate_sha256']['selector']
    numeric=load(index['numeric_manifest'])
    if (numeric.get('source_generation')!=source or numeric.get('input_sha256')!=source_input
            or str(numeric.get('data_date'))!=str(receipt['target_date'])):
        raise ValueError('RETAINED_PAIR_NUMERIC_CONFLICT')
    item=index.get('symbols',{}).get(symbol) or {};binding_ref=item.get('binding')
    if item.get('status')!='READY' or not binding_ref:raise ValueError('RETAINED_PAIR_BINDING_MISSING')
    binding=load(binding_ref)
    expected={'symbol':symbol,'source_date':index['source_date'],'observation_date':index['observation_date'],
        'generation':source,'input_sha256':source_input,'candidate_generation':receipt['generation_id'],
        'candidate_input_sha256':receipt['input_sha256'],'paired_receipt':pair_ref,
        'pair_sha256':receipt['candidate_sha256'],'numeric_manifest':index['numeric_manifest']}
    if (binding.get('schema')!='v4.workbench.generic_single_binding.v1'
            or any(binding.get(k)!=v for k,v in expected.items())
            or binding.get('historical_PIT') is not False or any(binding.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('RETAINED_PAIR_BINDING_CONFLICT')
    history_ref=binding['history_input'];path=load_path(history_ref)
    raw=path.read_bytes()
    if history_ref.get('encoding')!='gzip' or len(raw)!=history_ref.get('bytes') or len(raw)>8*1024*1024:
        raise ValueError('RETAINED_PAIR_HISTORY_SIZE_CONFLICT')
    with gzip.GzipFile(fileobj=io.BytesIO(raw),mode='rb') as stream:decoded=stream.read(32*1024*1024+1)
    if len(decoded)>32*1024*1024 or len(decoded)!=history_ref.get('decoded_bytes'):
        raise ValueError('RETAINED_PAIR_HISTORY_DECODED_SIZE_CONFLICT')
    history=json.loads(decoded)
    history_identity={'symbol':symbol,'source_generation':source,'source_input_sha256':source_input,
        'candidate_generation':receipt['generation_id'],'candidate_input_sha256':receipt['input_sha256'],
        'paired_receipt':pair_ref,'pair_sha256':receipt['candidate_sha256']}
    fields=[{'group_id':g,'namespace':n,'field':f} for g,_,n,f in _RETAINED_DEFINITIONS]
    if (history.get('schema')!='v4.workbench.retained_history_input.v1' or history.get('field_names')!=fields
            or any(history.get(k)!=v for k,v in history_identity.items()) or history.get('historical_PIT') is not False
            or any(history.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('RETAINED_PAIR_HISTORY_IDENTITY_CONFLICT')
    calendar=load(calendar_ref);market=symbol[-2:]
    if (calendar.get('schema') not in {'D222_PER_EXCHANGE_SOURCE_CALENDAR_V1','V4_PER_EXCHANGE_SOURCE_CALENDAR_V1'}
            or calendar.get('source_generation')!=source or calendar.get('input_sha256')!=source_input
            or calendar.get('panel_sha256')!=expected_panel or str(calendar.get('asof_date'))!=str(receipt['target_date'])
            or calendar.get('historical_PIT') is not False or any(calendar.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('RETAINED_PAIR_CALENDAR_CONFLICT')
    days=calendar.get('dates',{}).get(market)
    if not isinstance(days,list) or not days:raise ValueError('RETAINED_PAIR_MARKET_CALENDAR_MISSING')
    cal_days=[str(day)[:4]+'-'+str(day)[4:6]+'-'+str(day)[6:] for day in days]
    rows=[];close_rows=[];dates=[]
    for row in history.get('rows',[]):
        if not isinstance(row,list) or len(row)!=3 or not isinstance(row[2],list) or len(row[2])!=len(fields):
            raise ValueError('RETAINED_PAIR_HISTORY_ROW_INVALID')
        day=str(row[0]);dates.append(row[0])
        if not re.fullmatch(r'\d{8}',day):raise ValueError('RETAINED_PAIR_HISTORY_DATE_INVALID')
        values={'original':{},'kb':{}}
        for field,value in zip(fields,row[2]):values[field['namespace']][field['field']]=value
        rows.append({'trade_date':row[0],**values})
        close_rows.append({'date':day[:4]+'-'+day[4:6]+'-'+day[6:],'close':row[1]})
    if (not rows or len(rows)!=binding.get('rows') or dates!=binding.get('dates')
            or dates!=sorted(set(dates)) or str(dates[-1])!=str(receipt['target_date'])):
        raise ValueError('RETAINED_PAIR_HISTORY_DATES_CONFLICT')
    identity={'source_generation':source,'input_sha256':source_input,'source_view_sha256':history_ref['sha256'],
        'formula_sha256':receipt['user_formula_sha256'],'kb_contract_sha256':receipt['kb_field_contract_sha256'],
        'asof':index['source_date'],'market':market,'calendar_sha256':calendar_ref['sha256']}
    stats=retained_single_stock_statistics(rows,close_rows,cal_days,identity)
    for role,(p,stamp) in stamps.items():
        stat=p.stat();now={'device':stat.st_dev,'inode':stat.st_ino,'size':stat.st_size,
                           'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns}
        if now!=stamp:raise ValueError('RETAINED_PAIR_MOVED:'+role)
    shard={'schema_version':'v4.a_share.event_cases.paired_research.v1','symbol':symbol,
        'data_date':str(receipt['target_date']),'observation_date':index['observation_date'],
        'source_generation':source,'input_sha256':source_input,'numeric_manifest':index['numeric_manifest'],
        'source_candidate_generation':receipt['generation_id'],'candidate_input_sha256':receipt['input_sha256'],
        'paired_receipt':pair_ref,'verified_pair':index['verified_pair'],'projection_index':index_ref,
        'projection_binding':binding_ref,'history_input':history_ref,'market_calendar':calendar_ref,
        'producer_sha256':sha(__file__),'statistics':stats,'historical_PIT':False,
        'qualification':'DESCRIPTIVE_RETAINED_LABELS_NONPIT_NOT_FORECAST',**FLAGS}
    digest=hashlib.sha256(canonical(shard)).hexdigest()
    destination=Path(output_root)/'daily_products/a_share/event_cases'/str(receipt['target_date'])/digest/(symbol+'.json')
    if destination.exists():
        if load(ref(destination))!=shard:raise ValueError('RETAINED_PAIR_OUTPUT_CONFLICT')
        return ref(destination)
    return save(destination,shard)


def load_path(reference):
    """Return a validated non-symlink reference for a binary source."""
    path = Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or sha(path) != reference['sha256']:
        raise ValueError('FROZEN_REFERENCE_DRIFT:' + str(path))
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run-started', type=Path)
    parser.add_argument('--phase', choices=('canary', 'batch'), default='canary')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.output)
    elif args.run_started:
        run(args.output, args.run_started, args.phase)
    else:
        parser.error('--prepare or --run-started required')
