"""ops.a_share_daily_sync: progress (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


# Historical seed evidence is opt-in and read-only.  It never enters the
# provider-response validator or rewrites a raw price/volume field.
import hashlib
import json
import math
from datetime import datetime
from numbers import Real
from pathlib import Path

_SEED_EVIDENCE_SCHEMA = 'a_share_daily_sync.seed_adjustment_evidence.v1'


def _evidence_bytes(ref, *, limit=128 * 1024 * 1024):
    if not isinstance(ref, dict):
        raise ValueError('missing_reference')
    path = Path(ref.get('path', ''))
    expected = ref.get('sha256')
    if (not path.is_absolute() or not isinstance(expected, str) or
            len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
        raise ValueError('invalid_reference')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('reference_shape_or_size')
    data = path.read_bytes()
    if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('reference_sha256_mismatch')
    return data


def _evidence_json(ref):
    value = json.loads(_evidence_bytes(ref))
    if not isinstance(value, dict):
        raise ValueError('reference_not_object')
    return value


def _evidence_day(value):
    if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
        raise ValueError('date_not_integer')
    datetime.strptime(str(value), '%Y%m%d')
    return value


def _evidence_number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError('coefficient_not_finite')
    if positive and value <= 0:
        raise ValueError('coefficient_not_positive')
    return float(value)


def _seed_evidence_bundle(context, target_date):
    if 'bundle' in context:
        return context['bundle']
    if 'load_error' in context:
        raise ValueError(context['load_error'])
    # The expected digest is supplied by trusted invocation configuration,
    # never from the self-described evidence chain.  The caller's release
    # manifest/config approval is the trust root; this module only enforces it.
    expected = context.get('expected_sha256')
    if (not isinstance(expected, str) or len(expected) != 64 or
            any(c not in '0123456789abcdef' for c in expected)):
        raise ValueError('external_descriptor_pin_missing_or_malformed')
    path = Path(context['path'])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('descriptor_shape_or_size')
    data = path.read_bytes()
    if len(data) > 64 * 1024:
        raise ValueError('descriptor_shape_or_size')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('external_descriptor_pin_mismatch')
    descriptor = json.loads(data)
    if descriptor.get('schema_version') != _SEED_EVIDENCE_SCHEMA:
        raise ValueError('descriptor_schema')
    snapshot_ref = descriptor['snapshot']
    snapshot = _evidence_json(snapshot_ref)
    receipt = _evidence_json(descriptor['adoption_receipt'])
    if (receipt.get('schema') != 'ACTUAL_COUPLED_ADOPTION_READBACK_R1' or
            receipt.get('status') != 'COMMITTED_PAIR_AND_FIVE_METADATA_READBACK_MATCH' or
            receipt.get('journal_status') != 'COMMITTED' or
            receipt.get('research_only') is not True or
            any(receipt.get(k) is not False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise ValueError('adoption_not_committed_research')
    if not any(r.get('sha256') == snapshot_ref['sha256'] and
               Path(r.get('path', '')).name == 'qfq_adjustment_input.json'
               for r in receipt.get('five_metadata', []) if isinstance(r, dict)):
        raise ValueError('snapshot_not_adopted')
    roles = receipt['roles']
    selector, backtest = roles['selector'], roles['backtest']
    if (not selector.get('generation_id') or not selector.get('input_sha256') or
            any(selector.get(k) != backtest.get(k) for k in ('generation_id', 'input_sha256'))):
        raise ValueError('adoption_pair_identity')
    journal = _evidence_json(receipt['journal'])
    if (journal.get('status') != 'COMMITTED' or not any(
            r.get('after', {}).get('sha256') == snapshot_ref['sha256'] and
            Path(r.get('path', '')).name == 'qfq_adjustment_input.json'
            for r in journal.get('metadata', []) if isinstance(r, dict))):
        raise ValueError('journal_snapshot_identity')
    if (snapshot.get('schema') != 'a_share_qfq_adjustment_input_v1' or
            snapshot.get('price_basis') != 'QFQ_ASOF' or
            snapshot.get('convention') != 'FUTU_AFFINE_WITH_EXPLICIT_TDX_UNSUPPORTED_FALLBACK_V1'):
        raise ValueError('snapshot_convention')
    asof = _evidence_day(snapshot['asof_date'])
    coverage = _evidence_day(snapshot['coverage_end_date'])
    if coverage > asof or asof > target_date:
        raise ValueError('snapshot_date_scope')
    checkpoint = _evidence_json(descriptor['factor_cache_checkpoint'])
    if checkpoint.get('asof_date') != asof:
        raise ValueError('provider_asof_mismatch')
    bundle = {'descriptor': descriptor, 'descriptor_sha256': hashlib.sha256(data).hexdigest(),
              'snapshot': snapshot, 'checkpoint': checkpoint, 'coverage': coverage,
              'generation_id': selector['generation_id'], 'symbols': {}}
    context['bundle'] = bundle
    return bundle


def _seed_symbol_evidence(scope, bundle, symbol):
    if symbol in bundle['symbols']:
        return bundle['symbols'][symbol]
    item = bundle['snapshot']['symbols'][symbol]
    start = _evidence_day(item['history_start_date'])
    end = _evidence_day(item['history_end_date'])
    if (item.get('event_coverage_complete') is not True or
            item.get('source_method') != 'FUTU_GET_REHAB_AFFINE' or
            item.get('raw_resolution') != 'ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2'):
        raise ValueError('symbol_evidence_policy')
    cache_item = bundle['checkpoint']['symbols'][symbol]
    if cache_item.get('status') != 'OK' or cache_item.get('asof_date') != bundle['snapshot']['asof_date']:
        raise ValueError('provider_status')
    response_ref = cache_item['response']
    response = _evidence_json(response_ref)
    code, market = symbol.split('.')
    if (response.get('source') != 'Futu OpenD get_rehab' or
            response.get('code') != f'{market}.{code}' or type(response.get('return_code')) is not int or
            response.get('return_code') != 0):
        raise ValueError('provider_identity')

    def event_map(rows, provider=False):
        events = {}
        for row in rows:
            if provider:
                date_text = row['ex_div_date']
                if not isinstance(date_text, str):
                    raise ValueError('provider_event_date')
                day = int(datetime.strptime(date_text[:10], '%Y-%m-%d').strftime('%Y%m%d'))
                coefficients = (row['forward_adj_factorA'], row['forward_adj_factorB'], row['backward_adj_factorA'])
            else:
                day = _evidence_day(row['ex_date'])
                coefficients = (row['a'], row['b'], row['volume_a'])
            if day in events:
                raise ValueError('duplicate_event_date')
            events[day] = tuple(_evidence_number(v, positive=i != 1) for i, v in enumerate(coefficients))
        return events

    accepted = event_map(item['events'])
    provider = event_map(response['rows'], True)
    # A same-date label is insufficient: all accepted in-coverage coefficients
    # must equal the original provider data, with no missing/extra event.
    in_scope = lambda events: {d: v for d, v in events.items() if start <= d <= bundle['coverage']}
    if in_scope(accepted) != in_scope(provider):
        raise ValueError('provider_event_conflict')
    refs = item['raw_files']
    roles = [r.get('source_role') for r in refs]
    if (not refs or len(set(roles)) != len(roles) or 'archive' not in roles or
            any(role not in ('archive', 'native') for role in roles)):
        raise ValueError('raw_resolution_unsupported')
    selected = {}
    codec = _v4_global(scope, 'DAY_STRUCT')
    # Same accepted whole-row policy: archive wins; native contributes only
    # missing dates.  Never cherry-pick a matching conflicting alternative.
    for ref in sorted(refs, key=lambda r: r['source_role'] != 'archive'):
        data = _evidence_bytes(ref, limit=4 * 1024 * 1024)
        if not data or len(data) % codec.size:
            raise ValueError('raw_source_shape')
        seen = set()
        previous = 0
        floor = ref.get('from_date_exclusive', 0)
        for index, offset in enumerate(range(0, len(data), codec.size)):
            row = data[offset:offset + codec.size]
            day, _o, _h, _l, close, _amount, _volume, _reserved = codec.unpack(row)
            _evidence_day(day)
            if day in seen or day < previous:
                raise ValueError('raw_source_date_order')
            seen.add(day)
            previous = day
            if day > floor and day not in selected:
                selected[day] = {'close': close / 100.0, 'source_ref': dict(ref),
                                 'row_index': index, 'row_sha256': hashlib.sha256(row).hexdigest()}
    evidence = {'start': start, 'end': end, 'events': accepted, 'selected': selected,
                'provider_response': response_ref}
    bundle['symbols'][symbol] = evidence
    return evidence


def _explain_seed_pair(scope, context, symbol, target_date, previous_date, current_date, previous_close, close):
    record = {'symbol': symbol, 'previous_date': previous_date, 'current_date': current_date,
              'previous_close': previous_close, 'close': close, 'raw_ratio': close / previous_close,
              'status': 'UNEXPLAINED', 'evidence_path': str(context['path']),
              'expected_descriptor_sha256': context.get('expected_sha256') if isinstance(context.get('expected_sha256'), str) else None}
    try:
        try:
            bundle = _seed_evidence_bundle(context, target_date)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
            context['load_error'] = str(error)
            raise
        evidence = _seed_symbol_evidence(scope, bundle, symbol)
        if not evidence['start'] <= previous_date < current_date <= min(bundle['coverage'], evidence['end']):
            raise ValueError('pair_coverage_missing')
        selected = evidence['selected']
        if any(d not in selected or selected[d]['close'] != value
               for d, value in ((previous_date, previous_close), (current_date, close))):
            raise ValueError('pair_raw_basis_conflict')
        events = [(day, values) for day, values in sorted(evidence['events'].items())
                  if previous_date < day <= current_date]
        if not events:
            raise ValueError('pair_event_missing')
        denominator = previous_close
        for _day, (a, b, _volume_a) in events:
            denominator = denominator * a + b
            if not math.isfinite(denominator) or denominator <= 0:
                raise ValueError('transformed_close_not_positive_finite')
        ratio = close / denominator
        maximum = _v4_global(scope, 'MAX_CROSS_DAY_CLOSE_RATIO')
        if not math.isfinite(ratio) or not 1.0 / maximum <= ratio <= maximum:
            raise ValueError('transformed_ratio_out_of_bounds')
        record.update(status='EXPLAINED_ACCEPTED_AFFINE', transformed_previous_close=denominator,
                      transformed_ratio=ratio, events=[{'ex_date': d, 'a': v[0], 'b': v[1], 'volume_a': v[2]} for d, v in events],
                      pair_sources=[selected[previous_date], selected[current_date]],
                      provider_response=evidence['provider_response'], generation_id=bundle['generation_id'],
                      descriptor_sha256=bundle['descriptor_sha256'],
                      snapshot=bundle['descriptor']['snapshot'], adoption_receipt=bundle['descriptor']['adoption_receipt'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        record['reason'] = str(error)
    context.setdefault('records', []).append(record)
    return record['status'] == 'EXPLAINED_ACCEPTED_AFFINE'


def __local_history_status_body(_v4_scope, /, path, target_date, *, seed_evidence=None, symbol=None):
    """Validate existing source bytes before an accepted-only handoff.

    The formula reader currently keeps the last duplicate key.  This gate
    audits the source in its original order first, so a malformed local file
    is quarantined instead of being silently repaired by a downstream reader.
    """
    path_failure = _v4_global(_v4_scope, '_local_path_failure')(path)
    if path_failure is not None:
        return [], path_failure
    if not path.exists():
        return [], None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size % _v4_global(_v4_scope, 'DAY_STRUCT').size:
            return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_file_shape"
        bars = _v4_global(_v4_scope, 'read_hq_day_bars')(path)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error) as error:
        return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_read:{error!r}"
    dates: list[int] = []
    previous_close: float | None = None
    for bar in bars:
        valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(bar)
        if not valid:
            return bars, f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_{reason}"
        date_value = _v4_global(_v4_scope, 'day_int')(bar)
        if dates and date_value == dates[-1]:
            return bars, _v4_global(_v4_scope, 'DUPLICATE_DATE')
        if dates and date_value < dates[-1]:
            return bars, _v4_global(_v4_scope, 'NON_MONOTONIC_DATE')
        if date_value > target_date:
            return bars, _v4_global(_v4_scope, 'OUT_OF_SCOPE_AFTER_TARGET_DATE')
        close = _v4_global(_v4_scope, 'float')(bar["close"])
        if previous_close is not None:
            ratio = close / previous_close
            if ratio > _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO') or ratio < 1.0 / _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO'):
                if (seed_evidence is None or symbol is None or not _explain_seed_pair(
                        _v4_scope, seed_evidence, symbol, target_date, dates[-1], date_value, previous_close, close)):
                    return bars, _v4_global(_v4_scope, 'CROSS_DAY_CLOSE_RATIO')
        dates.append(date_value)
        previous_close = close
    return bars, None


def __new_progress_body(_v4_scope, /, target_int, targets, *, dry_run):
    return {
        "schema_version": _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "target_date": _v4_global(_v4_scope, 'str')(target_int),
        "target_count": _v4_global(_v4_scope, 'len')(targets),
        "target_fingerprint": _v4_global(_v4_scope, '_target_scope_fingerprint')(targets),
        "dry_run": _v4_global(_v4_scope, 'bool')(dry_run),
        "completed_symbols": [],
        "symbol_progress": {},
        "failed_hosts": [],
        "host_events": [],
        "last_event": None,
    }


def __load_progress_body(_v4_scope, /, path, target_int, targets, *, dry_run):
    expected = _v4_global(_v4_scope, '_new_progress')(target_int, targets, dry_run=dry_run)
    if not path.exists():
        return expected
    try:
        loaded = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_UNREADABLE:{path}") from error
    if not _v4_global(_v4_scope, 'isinstance')(loaded, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_INVALID:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("schema_version")) != _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCHEMA_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_date")) != _v4_global(_v4_scope, 'str')(target_int):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_DATE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_fingerprint")) != expected["target_fingerprint"]:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCOPE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'bool')(loaded.get("dry_run", False)) != _v4_global(_v4_scope, 'bool')(dry_run):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_MODE_MISMATCH:{path}")
    completed = loaded.get("completed_symbols", [])
    loaded["completed_symbols"] = _v4_global(_v4_scope, 'sorted')({_v4_global(_v4_scope, 'str')(value) for value in completed if _v4_global(_v4_scope, 'str')(value).strip()})
    loaded.setdefault("symbol_progress", {})
    loaded.setdefault("failed_hosts", [])
    loaded.setdefault("host_events", [])
    loaded.setdefault("last_event", None)
    return loaded


def __resume_target_order_body(_v4_scope, /, targets, progress, target_int):
    """Prioritize exact-target local files while preserving all other order.

    The last-date read is only a scheduling hint.  Every target still enters
    the unchanged local history, field, date, continuity, and source-identity
    gates below; a malformed or drifted exact-target file is rejected there.
    ``progress`` remains part of this seam for receipt compatibility, but
    durable pending/retry labels must not starve an already-current file.
    """
    if target_int is None:
        try:
            target_int = _v4_global(_v4_scope, 'int')(progress["target_date"])
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            return _v4_global(_v4_scope, 'list')(targets)

    current: list[DailyTarget] = []
    remainder: list[DailyTarget] = []
    for target in targets:
        try:
            is_current = _v4_global(_v4_scope, 'read_last_date')(_v4_global(_v4_scope, 'Path')(target.path)) == target_int
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error):
            is_current = False
        (current if is_current else remainder).append(target)
    return current + remainder
