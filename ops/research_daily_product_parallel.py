"""D29's bounded process scheduling inside the original daily-product owner.

Only missing stock checkpoints are filled. The existing parent materializer
alone publishes the product, charts, completion event and downstream receipts.
"""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import time

from ops import research_panel_daily_product as product

GIB = 1024 ** 3
_CONTEXT = None
_PARTS = None
_CHARTS = False


def bound_main_sources():
    ref = dict(path=os.environ['V4_RELEASE_MANIFEST_PATH'], sha256=os.environ['V4_RELEASE_MANIFEST_SHA256'])
    manifest = json.loads(product.checked(ref).read_text())
    app = Path(manifest['app_root']).resolve()
    paths = [Path(product.__file__).resolve(), Path(__file__).resolve()]
    inventory = {r['path']: r['sha256'] for r in manifest['application_inventory']['entries'] if r.get('kind', 'file') == 'file'}
    for path in paths:
        if app != path.parents[1] or inventory.get(str(path.relative_to(app))) != product.sha(path):
            raise ValueError('DAILY_PARALLEL_MAIN_SOURCE_BINDING:' + str(path))
    return dict(manifest=ref, code=[product.reference(path) for path in paths])


def memory_state():
    pids = [os.getpid()] + [p.pid for p in multiprocessing.active_children() if p.pid]
    rss = subprocess.run(['ps', '-o', 'rss=', '-p', ','.join(map(str, pids))], capture_output=True, text=True, check=True).stdout
    pressure = subprocess.run(['memory_pressure'], capture_output=True, text=True, check=True).stdout
    match = re.search(r'System-wide memory free percentage:\s*(\d+)%', pressure)
    if not match:
        raise ValueError('DAILY_PARALLEL_MEMORY_PRESSURE_UNAVAILABLE')
    total = int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, check=True).stdout)
    return dict(cpu_cores=os.cpu_count() or 1, physical_memory_bytes=total,
        cumulative_rss_bytes=sum(int(x.strip()) for x in rss.splitlines() if x.strip()) * 1024,
        memory_pressure_free_percent=int(match[1]), available_bytes=total * int(match[1]) // 100)


def resource_plan(observed, missing):
    # Current 18-core/128-GiB evidence gives14 workers/28 pending. Derive the
    # next run from its machine and free memory, including parent RSS.
    total = observed['physical_memory_bytes']
    guard = min(64 * GIB, total // 2)
    reserve = min(24 * GIB, total * 3 // 16)
    worker_budget = max(0, min(guard, observed['available_bytes'] - reserve) - observed['cumulative_rss_bytes'])
    workers = max(1, min(max(1, observed['cpu_cores'] - 4), worker_budget // (4 * GIB), missing))
    return dict(workers=workers, max_pending=min(workers * 2, 28), memory_guard_bytes=guard,
                reserve_available_bytes=reserve, estimated_worker_bytes=4 * GIB, observed=observed)


def checkpoint_parts(context, selected):
    runkey = product.digest(dict(identity=context.identity, config=context.config_ref, symbols=selected, history_dates=[]))
    return context.root / 'checkpoints' / str(context.target) / runkey


def initialize(data_root, target, output_root, parts, identity, config_ref, scope, sources, cache_lock, charts):
    global _CONTEXT, _PARTS, _CHARTS
    if bound_main_sources() != sources:
        raise ValueError('DAILY_PARALLEL_WORKER_SOURCE_DRIFT')
    _CONTEXT = product.SourceContext(data_root, target)
    _CONTEXT.root = Path(output_root)
    _CONTEXT._event_case_cache_lock = cache_lock
    if (_CONTEXT.identity != identity or _CONTEXT.config_ref != config_ref or sorted(_CONTEXT.scope) != scope
            or checkpoint_parts(_CONTEXT, scope) != Path(parts)):
        raise ValueError('DAILY_PARALLEL_WORKER_NAMESPACE_CONFLICT')
    _PARTS, _CHARTS = Path(parts), charts


def retained_same_day_formula(context,symbol,bars):
    """Reuse original owner retention only for an identical full same-day prefix."""
    import gzip
    if not hasattr(context,'_same_day_retained_source'):
        context._same_day_retained_source=None
        path=context.root/'index.json'
        if path.exists():
            index=json.loads(path.read_bytes());day=str(context.target);manifest_ref=index.get('dates',{}).get(day)
            charts_ref=index.get('original_charts',{}).get(day,{}).get('manifest')
            if manifest_ref and charts_ref:
                manifest=json.loads(product.checked(manifest_ref).read_bytes());old=json.loads(product.checked(manifest['artifact']).read_bytes());charts=json.loads(product.checked(charts_ref).read_bytes())
                samples=charts.get('samples',{})
                if (samples and old['source_config']==context.config_ref and old['source_identity']['basis']==context.identity['basis'] and old['data_date']==day):
                    roots={str(Path(item['source_cache']['path']).parent)for item in samples.values()}
                    if len(roots)==1:
                        directory=Path(next(iter(roots)))
                        if directory.name=='original_retained' and directory.is_relative_to(context.root/'checkpoints'/day) and not directory.is_symlink():context._same_day_retained_source=(directory,old,samples,manifest_ref)
    source=context._same_day_retained_source
    if source is None:return None
    directory,old,samples,manifest_ref=source
    if symbol not in old['row_refs']:return None
    prior_row=json.loads(product.checked(old['row_refs'][symbol]).read_bytes())
    path=directory/(symbol+'.json.gz')
    if path.is_symlink() or not path.is_file():return None
    reference=product.reference(path)
    if symbol in samples and reference!={key:samples[symbol]['source_cache'][key]for key in ('path','sha256')}:raise ValueError('DAILY_RETAINED_FORMULA_SOURCE_DRIFT')
    retained=json.loads(gzip.decompress(product.checked(reference).read_bytes()))
    if (retained.get('symbol')!=symbol or retained.get('data_date')!=str(context.target) or
            retained.get('identity')!=old['source_identity'] or retained.get('config')!=context.config_ref or
            retained.get('calendar')!=context.calendars[symbol[-2:]] or retained.get('bars_sha256')!=product.digest(bars) or
            retained.get('bar_dates')!=[bar['trade_date']for bar in bars]):return None
    result=retained['formula_result']
    if (result.get('formula_sha256')!=context.config['formula']['sha256'] or result.get('mode')!='prefix' or result.get('field_count')!=51 or result.get('drawing_count')!=22 or [row['trade_date']for row in result['rows']]!=retained['bar_dates']):raise ValueError('DAILY_RETAINED_FORMULA_SHAPE_DRIFT')
    return result,dict(source=reference,source_numeric_manifest=manifest_ref,original_identity=old['source_identity'],current_identity=context.identity,full_prefix_sha256=retained['bars_sha256'],calendar_sha256=product.digest(retained['calendar']),rules_config=context.config_ref,prior_row=old['row_refs'][symbol],prior_groups=prior_row['groups'],formula_engine_compute_calls=0)


def checkpoint(symbol):
    context = _CONTEXT
    path = _PARTS / (symbol + '.json')
    if symbol not in context.scope:
        raise ValueError('DAILY_PARALLEL_SYMBOL_OUTSIDE_SCOPE')
    if path.is_file():
        row = json.loads(path.read_text())
        if row.get('symbol') != symbol or row.get('data_date') != str(context.target):
            raise ValueError('DAILY_PARALLEL_EXISTING_CHECKPOINT_IDENTITY')
        return dict(symbol=symbol, ref=product.reference(path), chart_gaps={})
    gaps = {}
    def capture(code, bars, result):
        try:
            from ops.render_original_formula_projection import retain_owner_result
            retain_owner_result(context, _PARTS, code, bars, result)
        except Exception as error:
            gaps[code] = 'RETAINED_RESULT_UNAVAILABLE:' + str(error)
    engine=context.engine();original_compute=engine.compute;reuse=None
    def reuse_compute(bars,mode):
        nonlocal reuse
        reused=retained_same_day_formula(context,symbol,bars)if mode=='prefix'else None
        if reused is None:return original_compute(bars,mode)
        result,reuse=reused
        return result
    engine.compute=reuse_compute
    try:
        row, cache, cachepath = product.compute_stock(context, symbol, history_dates=(),
            **({'chart_capture': capture} if _CHARTS else {}))
        if reuse and row['groups']!=reuse['prior_groups']:raise ValueError('DAILY_UNCHANGED_PREFIX_GROUP_PARITY_FAILED')
        if reuse:row['same_day_formula_reuse']=reuse
        product.save(cachepath, cache)
    except (ValueError, KeyError, TypeError, OSError) as error:
        if str(error).startswith('DAILY_SOURCE_PIN_DRIFT'):
            raise
        row = dict(symbol=symbol, display_name=None, data_date=str(context.target), groups='',
            pending_groups='|'.join(product.GROUPS), latest_new_anchor='', reasons='SOURCE_ISOLATED:' + str(error),
            risk_clear='UNKNOWN', evaluation={'groups': {g: {'status': 'UNKNOWN', 'reasons': ['SOURCE_ISOLATED:' + str(error)]} for g in product.GROUPS}},
            statistics=None, historical_coverage={'known_full_history': False, 'evaluated_count': 0, 'missing': ['SOURCE_ISOLATED']},
            qualification={'status': 'UNKNOWN', 'reason': str(error)})
    finally:engine.compute=original_compute
    context.unchanged()
    row.update(product.FLAGS)
    return dict(symbol=symbol, ref=product.save(path, row, immutable=True), chart_gaps=gaps)


def run_pending(context, parts, selected, pending, *, original_charts, resources, sources):
    """One bounded wave scheduler; existing jobs drain on failure or pressure."""
    ctx = multiprocessing.get_context('spawn')
    lock = ctx.Lock()
    complete = sum((parts / (symbol + '.json')).is_file() for symbol in selected)
    state = dict(status='RUNNING', completed=complete, total=len(selected), generation=context.generation,
        target_date=context.target, source_binding=sources, resource_plan=resources, history_dates=[], **product.FLAGS)
    record = parts / ('parallel_run_' + str(os.getpid()) + '_' + str(time.time_ns()) + '.json')
    product.save(record, state)
    started = time.perf_counter()
    failure = None
    gaps = {}
    peak = resources['observed']['cumulative_rss_bytes']
    with ProcessPoolExecutor(max_workers=resources['workers'], mp_context=ctx, initializer=initialize,
            initargs=(str(context.data_root), context.target, str(context.root), str(parts), context.identity,
                      context.config_ref, selected, sources, lock, original_charts)) as pool:
        iterator = iter(pending)
        inflight = {}
        def submit_next():
            if failure is not None:
                return
            try:
                symbol = next(iterator)
            except StopIteration:
                return
            inflight[pool.submit(checkpoint, symbol)] = symbol
        for _ in range(min(resources['max_pending'], len(pending))):
            submit_next()
        while inflight:
            done, _ = wait(inflight, return_when=FIRST_COMPLETED)
            try:
                observed = memory_state()
                peak = max(peak, observed['cumulative_rss_bytes'])
                if peak > resources['memory_guard_bytes'] or observed['available_bytes'] < resources['reserve_available_bytes']:
                    failure = failure or MemoryError('DAILY_PARALLEL_RESOURCE_GUARD_DRAINED')
            except Exception as error:
                failure = failure or error
            for future in done:
                symbol = inflight.pop(future)
                try:
                    result = future.result()
                    if result['symbol'] != symbol:
                        raise ValueError('DAILY_PARALLEL_WORKER_SYMBOL_CONFLICT')
                    product.checked(result['ref'])
                    complete += 1
                    gaps.update(result['chart_gaps'])
                except Exception as error:
                    failure = failure or error
                state.update(completed=complete, last_symbol=symbol, wall_seconds=time.perf_counter() - started,
                             peak_cumulative_rss_bytes=peak, stop_new_submissions=failure is not None)
                product.save(record, state)
                product.save(parts / 'progress.json', dict(completed=complete, total=len(selected), target_date=context.target,
                    generation=context.generation, workers=resources['workers'], **product.FLAGS))
            for _ in done:
                submit_next()
    state.update(status='FAILED_DRAINED' if failure else 'CHECKPOINTS_FILLED', wall_seconds=time.perf_counter() - started)
    if failure:
        state.update(error_type=type(failure).__name__, error=str(failure))
    product.save(record, state)
    if failure:
        raise failure
    context.unchanged()
    return dict(chart_gaps=gaps, record=product.reference(record))


def prefill_missing(context, parts, selected, *, original_charts):
    sources = bound_main_sources()
    if selected != sorted(set(context.scope)) or parts != checkpoint_parts(context, selected):
        raise ValueError('DAILY_PARALLEL_PARENT_NAMESPACE_CONFLICT')
    pending = []
    for symbol in selected:
        path = parts / (symbol + '.json')
        if path.is_file():
            row = json.loads(path.read_text())
            if row.get('symbol') != symbol or row.get('data_date') != str(context.target):
                raise ValueError('DAILY_PARALLEL_CHECKPOINT_CUT_IDENTITY')
        else:
            pending.append(symbol)
    if len(pending) < 2:
        return dict(chart_gaps={})
    resources = resource_plan(memory_state(), len(pending))
    if (resources['observed']['cumulative_rss_bytes'] > resources['memory_guard_bytes']
            or resources['observed']['available_bytes'] < resources['reserve_available_bytes']):
        raise MemoryError('DAILY_PARALLEL_INITIAL_RESOURCE_GUARD')
    if resources['workers'] < 2:
        return dict(chart_gaps={})
    return run_pending(context, parts, selected, pending, original_charts=original_charts, resources=resources, sources=sources)
