"""Daily owner adapter for panel-reference event fields. No acquisition or scoring."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from domains import p5162_event_position_fields as position

FLAGS = position.FLAGS
SCHEMA = 'v4.p5162.event_fields_index.v1'
ALGORITHM = 'panel_reference_k_geometry_v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def ref(path):
    path = Path(path).resolve(strict=True)
    return {'path':str(path), 'sha256':sha(path)}


def checked(value):
    path = Path(value['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path or sha(path) != value['sha256']:
        raise ValueError('EVENT_FIELDS_REFERENCE_CONFLICT')
    return json.loads(path.read_bytes())


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)+b'\n'
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('EVENT_FIELDS_IMMUTABLE_CONFLICT')
    else:
        tmp = path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
        with tmp.open('xb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    return ref(path)


def algorithm_identity():
    return {'name':ALGORITHM, 'domain_sha256':sha(position.__file__), 'adapter_sha256':sha(__file__)}


def target_bars(context, requested):
    """One target-date-only selector projection; no per-stock history scans."""
    import pyarrow as pa
    import pyarrow.dataset as ds
    binding = (str(context.panel), str(context.target), context.generation,
               context.identity.get('selector_artifact_sha256'), digest(sorted(requested)))
    previous = getattr(context, '_p5162_target_bars', None)
    if previous is not None and previous['binding'] == binding:
        return previous['bars']
    dataset = ds.dataset(context.panel, format='parquet')
    required = {'ts_code','trade_date','exchange','close','volume'}
    if not required <= set(dataset.schema.names):
        raise ValueError('TARGET_BAR_REQUIRED_COLUMNS_MISSING')
    dt = dataset.schema.field('trade_date').type
    target = int(context.target) if pa.types.is_integer(dt) else str(context.target)
    rows = dataset.to_table(columns=sorted(required), filter=(ds.field('trade_date') == target)
                            & ds.field('ts_code').isin(requested)).to_pylist()
    bars = {}; duplicates = set()
    for row in rows:
        symbol = row['ts_code']
        if symbol in bars:
            duplicates.add(symbol)
        else:
            # Convert Arrow scalar/decimal values to portable JSON representation.
            bars[symbol] = {k:(str(v) if k in ('close','volume') and v is not None else v)
                            for k,v in row.items()}
    for symbol in duplicates:
        bars[symbol] = {'_error':'DUPLICATE_TARGET_BARS'}
    context._p5162_target_bars = {'binding':binding, 'bars':bars}
    return bars


def materialize(context, product, numeric_manifest, *, output_root=None, symbols=None, save_function=None):
    """Called by the original daily owner after numeric completion.

    Explicit sample runs require an isolated output root and cannot publish an
    index or event. A full run returns a descriptor for the existing owner.
    """
    context.unchanged()
    target = str(context.target); generation = context.generation
    manifest = checked(numeric_manifest)
    if (str(manifest.get('data_date')) != target or manifest.get('source_generation') != generation
            or manifest.get('input_sha256') != context.identity.get('input_sha256')):
        raise ValueError('EVENT_FIELDS_NUMERIC_MANIFEST_IDENTITY_CONFLICT')
    artifact = manifest.get('artifact')
    if not isinstance(artifact, dict) or checked(artifact) != product:
        raise ValueError('EVENT_FIELDS_NUMERIC_ARTIFACT_IDENTITY_CONFLICT')
    if (product.get('schema_version') != 'v4.a_share.daily_product.v1'
            or str(product.get('data_date')) != target or product.get('source_generation') != generation
            or product.get('source_identity') != context.identity):
        raise ValueError('EVENT_FIELDS_PARENT_GENERATION_OR_SCHEMA_CONFLICT')
    universe = product.get('processed_universe')
    refs = product.get('row_refs')
    if not isinstance(universe, list) or not isinstance(refs, dict) or len(universe) != len(set(universe)) or set(universe) != set(refs):
        raise ValueError('EVENT_FIELDS_PARENT_SCOPE_CONFLICT')
    requested = sorted(universe if symbols is None else symbols)
    if len(requested) != len(set(requested)) or not set(requested) <= set(universe):
        raise ValueError('EVENT_FIELDS_REQUESTED_SCOPE_CONFLICT')
    if symbols is not None and output_root is None:
        raise ValueError('EVENT_FIELDS_SAMPLE_REQUIRES_ISOLATED_ROOT')
    root = Path(output_root).resolve() if output_root is not None else context.root/'p5162_event_fields'
    if symbols is not None and (root == context.root or root.is_relative_to(context.root)):
        raise ValueError('EVENT_FIELDS_SAMPLE_ROOT_NOT_ISOLATED')
    # The daily owner injects its existing governed immutable save boundary.
    # Isolated replays use this module's equivalent local immutable saver.
    def persist(path, value):
        return save_function(path, value, immutable=True) if save_function else save(path, value)
    rules = algorithm_identity(); basis = context.identity.get('basis')
    # One same-generation target-date projection is reused by the canary and
    # later work in this context; it does not materialize historic prices.
    bars = target_bars(context, universe)
    calendar_sha = {k:digest(v) for k,v in context.calendars.items()}
    items = {}; counts = {'total':0, 'reference_age_available':0, 'reference_price_available':0,
        'reference_volume_available':0, 'source_isolated':0, 'r3_model_admitted':0}
    computed = reused = 0
    for symbol in requested:
        row_ref = refs[symbol]; row = None; error = None
        try:
            row = checked(row_ref)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error = 'SOURCE_ROW_UNREADABLE:'+str(exc)
        day = bars.get(symbol)
        if isinstance(day, dict) and day.get('_error'):
            error = day['_error']
        ev = row.get('evaluation', {}) if isinstance(row, dict) else {}
        event_ids = [f'PANEL_REFERENCE_K:{symbol}:{p.get("anchor_date")}'
                     for p in ev.get('filter_anchor_paths',[]) if isinstance(p,dict)] if isinstance(ev,dict) and isinstance(ev.get('filter_anchor_paths'),list) else []
        identity = dict(symbol=symbol, data_date=target, input_generation=generation,
            input_sha256=context.identity['input_sha256'], source_schema=product['schema_version'],
            source_config=product.get('source_config'), source_row=row_ref,
            event_identities=event_ids, price_basis=basis,
            exchange_calendar_sha256=calendar_sha.get(symbol[-2:]), target_bar_sha256=digest(day),
            algorithm=rules, source_error=error)
        key = digest(identity); directory = root/'stock_cache'/symbol/key
        matches = sorted(directory.glob('*.json')) if directory.exists() else []
        if len(matches) > 1:
            raise ValueError('EVENT_FIELDS_CACHE_MULTIPLE_CONTENTS')
        if matches:
            path = matches[0]
            if path.stem != sha(path):
                raise ValueError('EVENT_FIELDS_CACHE_CONTENT_DRIFT')
            record = checked(ref(path))
            if record.get('cache_identity') != identity:
                raise ValueError('EVENT_FIELDS_CACHE_IDENTITY_CONFLICT')
            reused += 1
        else:
            try:
                record = position.isolated(symbol,target,row_ref,error) if error else position.project(
                    symbol,target,generation,row,row_ref,day,context.calendars.get(symbol[-2:]),basis)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                record = position.isolated(symbol,target,row_ref,str(exc))
            record.update(source_generation=generation, cache_identity=identity)
            content_sha = hashlib.sha256(canonical(record)+b'\n').hexdigest()
            path = directory/(content_sha+'.json')
            persist(path,record); computed += 1
        items[symbol] = ref(path); counts['total'] += 1
        fields = record['panel_reference']['fields']
        for field, count in (('reference_age_sessions','reference_age_available'),
                ('reference_high_to_close_pct','reference_price_available'), ('reference_volume_ratio','reference_volume_available')):
            counts[count] += fields[field] is not None
        counts['source_isolated'] += record['status'] == 'SOURCE_ISOLATED'
    context.unchanged()
    index = dict(schema=SCHEMA, data_date=target, source_generation=generation,
        input_sha256=context.identity['input_sha256'], numeric_manifest=numeric_manifest,
        numeric_artifact=artifact, source_identity=context.identity, source_schema=product['schema_version'],
        source_config=product.get('source_config'), algorithm=rules, price_basis=basis,
        exchange_calendar_sha256=calendar_sha, sample_only=symbols is not None,
        requested_count=len(requested), source_universe_count=len(universe), items=items, counts=counts,
        historical_PIT=False, **FLAGS)
    index_ref = persist(root/'indexes'/(digest(index)+'.json'), index)
    context._p5162_event_fields_last_run = {'computed':computed,'reused':reused}
    reference_complete = all(counts[k] == counts['total'] for k in
        ('reference_age_available','reference_price_available','reference_volume_available'))
    return dict(status='PARTIAL_WITH_UNKNOWN', reference_status='READY' if reference_complete else 'PARTIAL_WITH_UNKNOWN',
        r3_model_status='CANNOT_CONFIRM',
        index=index_ref, data_date=target, source_generation=generation,
        input_sha256=context.identity['input_sha256'], numeric_manifest=numeric_manifest,
        counts=counts, sample_only=symbols is not None, **FLAGS)


def read_model_fields(index_ref, symbol, *, data_date, generation):
    index = checked(index_ref)
    if (index.get('schema') != SCHEMA or index.get('data_date') != str(data_date)
            or index.get('source_generation') != generation):
        raise ValueError('MODEL_READER_INDEX_IDENTITY_CONFLICT')
    if symbol not in index.get('items',{}):
        raise ValueError('MODEL_READER_SYMBOL_NOT_IN_SCOPE')
    record = checked(index['items'][symbol])
    return position.read_model_fields(record,symbol=symbol,data_date=data_date,generation=generation)
