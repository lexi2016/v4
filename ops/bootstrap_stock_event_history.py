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
SETTINGS = {}


def configure(path):
    """Bind one explicit original daily-product generation; defaults retain D29."""
    global SETTINGS, TARGET, GENERATION, INPUT, MAIN, DATA, DAILY
    SETTINGS = json.loads(Path(path).read_bytes())
    TARGET = int(SETTINGS['target'])
    GENERATION, INPUT = SETTINGS['generation'], SETTINGS['input_sha256']
    if not re.fullmatch(r'[a-f0-9]{64}', GENERATION) or not re.fullmatch(r'[a-f0-9]{64}', INPUT):
        raise ValueError('HISTORY_SETTINGS_IDENTITY_REQUIRED')
    MAIN, DATA, DAILY = (Path(SETTINGS[key]).resolve(strict=True) for key in ('main_root', 'data_root', 'daily_root'))
    if len(set(SETTINGS['symbols'])) != len(SETTINGS['symbols']) or SETTINGS['canary'] not in SETTINGS['symbols']:
        raise ValueError('HISTORY_SETTINGS_SCOPE_INVALID')


def previous_prefix_proofs(owner, context, symbols):
    """Read each prior panel once, proving retained labels across generations.

    No label is recalculated or relabelled. Old entry identities remain intact.
    OHLCV, original config/rule and dated calendars must match their old cutoff.
    """
    if not SETTINGS:
        return {}
    import pyarrow.parquet as pq
    receipt_ref = SETTINGS['prior_receipt']
    receipt = load(receipt_ref)
    prior_asof = int(receipt['asof_date'])
    panel = Path(receipt['candidates']['selector'])
    stat = panel.stat()
    table = pq.read_table(panel, columns=['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'volume'],
        filters=[('ts_code', 'in', symbols), ('trade_date', '<=', str(prior_asof))])
    grouped = {symbol: [] for symbol in symbols}
    for row in table.to_pylist():
        grouped[row['ts_code']].append(dict(trade_date=int(row['trade_date']),
            **{key: str(row[key if key != 'vol' else 'volume']) for key in ('open', 'high', 'low', 'close', 'vol')}))
    for bars in grouped.values():
        bars.sort(key=lambda bar: bar['trade_date'])
    prior_index = load(ref(DAILY / 'index.json'))
    prior_product = load(load(prior_index['dates'][str(prior_asof)])['artifact'])
    if prior_product['source_config'] != context.config_ref or prior_product['source_generation'] != receipt['generation_id']:
        raise ValueError('HISTORY_PRIOR_RULE_CONFIG_IDENTITY_DRIFT')
    if panel.stat() != stat:
        raise ValueError('HISTORY_PRIOR_PANEL_CHANGED')
    return dict(receipt=receipt_ref, panel=str(panel), panel_stat={key: getattr(stat, key) for key in ('st_size','st_mtime_ns','st_ino')},
                source_identity=prior_product['source_identity'], asof=prior_asof, bars=grouped)


def prove_retained_entries(owner, cache, bars, context, prior, symbol):
    other = {day: item for day, item in cache['evaluations'].items() if item['source_identity'] != context.identity}
    if not other:
        return {}
    if not prior or any(item['source_identity'] != prior['source_identity'] or int(day) > prior['asof'] for day,item in other.items()):
        raise ValueError('HISTORY_PREVIOUS_GENERATION_UNBOUND:' + symbol)
    old = prior['bars'][symbol]
    current = [bar for bar in bars if bar['trade_date'] <= prior['asof']]
    if len(old) != len(current) or any(left['trade_date'] != right['trade_date'] or any(Decimal(left[key]) != Decimal(right[key]) for key in ('open','high','low','close','vol')) for left,right in zip(old,current)):
        raise ValueError('HISTORY_PREVIOUS_PREFIX_PRICE_DRIFT:' + symbol)
    # The same pinned source config owns the causal formula, rule, dated G4 and
    # calendar policy. Dates are explicit exchange dates, never bar ordinals.
    exchange = symbol[-2:]
    if not set(bar['trade_date'] for bar in old) <= set(context.calendars[exchange]):
        raise ValueError('HISTORY_PREVIOUS_CALENDAR_GAP:' + symbol)
    return dict(dates=sorted(other), source_identity=prior['source_identity'], prior_receipt=prior['receipt'],
                prior_panel=prior['panel'], prior_panel_stat=prior['panel_stat'], prefix_sha256=owner.digest(current),
                config=context.config_ref, rule_sha256=RULE, calendar_dates_sha256=owner.digest([day for day in context.calendars[exchange] if day <= prior['asof']]))


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
        'ops.research_panel_daily_product': (ROOT if SETTINGS else MAIN) / 'ops/research_panel_daily_product.py',
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


def projection_identity(projection):
    lineage = projection['lineage']
    if 'source_identity' in lineage:
        return lineage['source_identity']
    product = load(lineage['product'])
    manifest = load(lineage['manifest'])
    if manifest['artifact'] != lineage['product'] or product['source_config'] != lineage['config']:
        raise ValueError('RETAINED_PROJECTION_PRODUCT_BINDING_DRIFT')
    return product['source_identity']


def retained_sample(projection, source_cache):
    if 'identity' in source_cache:
        if (source_cache['symbol'] != projection['symbol'] or source_cache['data_date'] != str(TARGET)
                or source_cache['identity'] != projection_identity(projection)
                or source_cache['config'] != projection['lineage']['config']
                or source_cache['formula_result'] != projection['formula_result']):
            raise ValueError('OWNER_RETAINED_RESULT_BINDING_DRIFT')
        bars = projection_bars(projection)
        expected = source_cache['bars_sha256']
        if hashlib.sha256(canonical(bars)).hexdigest() != expected:
            # Decimal render exponents may differ only in spelling. Recreate
            # original reader float strings, accepting them solely by exact SHA.
            bars = [dict(trade_date=bar['trade_date'], **{key:str(float(bar[key])) for key in ('open','high','low','close','vol')}) for bar in bars]
        if hashlib.sha256(canonical(bars)).hexdigest() != expected:
            raise ValueError('OWNER_RETAINED_PRICE_PREFIX_SHA_DRIFT')
        return dict(symbol=projection['symbol'], display_name=None), bars
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


def validate_cache(owner, cache, bars, identity, config, prior_proof=None):
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
    for day, item in cache['evaluations'].items():
        prior_ok = bool(prior_proof and day in prior_proof['dates'] and item['source_identity'] == prior_proof['source_identity'])
        if (item['source_identity'] != identity and not prior_ok) or set(item['groups']) != set(owner.GROUPS):
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
    charts_ref = index['original_charts'][str(TARGET)]['manifest'] if SETTINGS else ref(BASE / 'original_formula_charts_247/MANIFEST.json')
    charts = load(charts_ref)
    symbols = sorted(SETTINGS['symbols'] if SETTINGS else charts['samples'])
    selected = sorted(row['symbol'] for row in product['rows'] if row['groups'])
    if not set(symbols) <= set(selected) or (not SETTINGS and (len(symbols) != 247 or symbols != selected)):
        raise ValueError('CANDIDATE_SCOPE_CONFLICT')
    previous = previous_prefix_proofs(owner, context, symbols)
    calendar_ref = save(output / 'CALENDARS.json', dict(dates=context.calendars, source_generation=GENERATION, input_sha256=INPUT, future_calendar=config['future_calendar']))
    entries = {}
    for symbol in symbols:
        chart = charts['samples'][symbol]
        projection = load(chart['projection'])
        bars = projection_bars(projection)
        source = projection['source']
        if (projection['symbol'] != symbol or projection['data_date'] != str(TARGET)
                or projection_identity(projection) != context.identity
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
        prior_proof = prove_retained_entries(owner, cache, bars, context, previous, symbol)
        validate_cache(owner, cache, bars, context.identity, config, prior_proof)
        missing = sorted(set(str(bar['trade_date']) for bar in bars) - set(cache['evaluations']))
        if not SETTINGS and symbol == '002003.SZ' and (missing or not cache['coverage']['known_full_history']):
            raise ValueError('ACCEPTED002003_HISTORY_MISSING')
        entries[symbol] = dict(projection=chart['projection'], source_cache=cache_source_ref, prior_row=row_ref, prior_cache=cache_ref,
            bars_sha256=owner.digest(bars), rows=len(bars), first=bars[0]['trade_date'], last=bars[-1]['trade_date'], missing_dates=missing,
            qualification_sha256=owner.digest(qualification), display_name=row.get('display_name') if SETTINGS else sample['display_name'], prior_entry_reuse=prior_proof,
            unchanged_chart={key: chart[key] for key in ('html', 'projection', 'PNG')})
        if not SETTINGS and symbol == '002003.SZ':
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
    settings = dict(target=TARGET, symbols=symbols, candidate_symbols=selected, canary=SETTINGS.get('canary','001328.SZ'), reuse_complete=[] if SETTINGS else ['002003.SZ'], workers=SETTINGS.get('workers',14), queue=SETTINGS.get('queue',28),
        job_memory_limit_GiB=64, system_available_reserve_GiB=24, checkpoint_seconds=5, checkpoint_dates=25,
        percentile_window=250, percentile_edges=[0, .2, .4, .6, .8, 1], event_cases='ALL',
        pure_prefix_cache='ORIGINAL_NORMALIZE_AND_FUND_KEYS_ONCE_EXACT_PREFIX_ARGUMENTS',
        canary_parity_prefix_indices=[0, 40, -6],
        original_formula_engine_compute_calls=0, historical_PIT=False, maximum_claim='DIRECTION_ONLY')
    contract = dict(schema='v4.stock_history_catchup.v1', status='PREPARED_WAIT_ROOT_RUN_STARTED', GOAL='Fill only missing current-generation historical evaluations for candidate247 using retained formula results',
        WRITER='/root/daily_chain_completion_writer' if SETTINGS else '/root/stock_history_catchup_writer', BASELINE_ID='D29candidate247; accepted0020035266dates', ONE_VARIABLE='missing_history_cache_initialization',
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
        canary_missing=len(entries[settings['canary']]['missing_dates']), resources=settings), ensure_ascii=False), flush=True)


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
    if owner.digest(bars) != entry['bars_sha256'] or projection_identity(projection) != context.identity:
        raise ValueError('WORKER_PREFIX_DRIFT:' + symbol)
    prior_row = load(entry['prior_row'])
    cache = load(entry['prior_cache'])
    validate_cache(owner, cache, bars, context.identity, context.config, entry.get('prior_entry_reuse'))
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
    pure_cache = None if symbol in contract['config']['reuse_complete'] else PurePrefixCache(rule, bars, projection['formula_result']['rows'])
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
        if symbol in contract['config']['reuse_complete']:
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
        cases = (load(entry['accepted_event_cases']) if symbol in contract['config']['reuse_complete'] else
            full_event_cases(stats, row, cache, bars, context.calendars[symbol[-2:]], contract, entry))
        cases['accepted_cache'] = cache_path_ref
        cases['contract'] = contract_ref
        cases_ref = save(output / 'event_cases' / (symbol + '.json'), cases)
        context.unchanged()
        result = dict(status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=symbol, contract=contract_ref, row=row_ref,
            history_cache=cache_path_ref, event_cases=cases_ref, available_dates=len(bars), evaluated_dates=len(cache['evaluations']),
            unknown_by_group=cache['coverage']['unknown_by_group'], remaining_dates=[], reused_complete=symbol in contract['config']['reuse_complete'],
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run-started', type=Path)
    parser.add_argument('--phase', choices=('canary', 'batch'), default='canary')
    args = parser.parse_args()
    if args.settings:
        configure(args.settings)
    if args.prepare:
        prepare(args.output)
    elif args.run_started:
        run(args.output, args.run_started, args.phase)
    else:
        parser.error('--prepare or --run-started required')
