"""Complete exact formula-group Workbench supplements at the daily owner.

The canonical numeric product remains unchanged. This module writes only
date-scoped formula-group supplements and reuses the existing F10 and score
owners against the exact committed roster.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
HISTORICAL_PIT = False
FORMULA_SHA = 'd35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'
ENGINE_SHA = 'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _reference(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': _sha(path.read_bytes())}


def _checked(reference, *, root=None):
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        raise ValueError('FORMULA_SUPPLEMENT_REFERENCE_INVALID')
    path = Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('FORMULA_SUPPLEMENT_PATH_INVALID')
    if root is not None and not path.is_relative_to(root):
        raise ValueError('FORMULA_SUPPLEMENT_OUTSIDE_OWNER_ROOT')
    raw = path.read_bytes()
    if _sha(raw) != reference.get('sha256'):
        raise ValueError('FORMULA_SUPPLEMENT_SHA_DRIFT')
    return json.loads(raw)


def _immutable(root, value):
    raw = _canonical(value) + b'\n'
    digest = _sha(raw)
    path = Path(root) / (digest + '.json')
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('FORMULA_SUPPLEMENT_IMMUTABLE_CONFLICT')
        return {'path':str(path.resolve()),'sha256':digest}
    from ops.research_daily_capacity import serialized_write
    with serialized_write(path,raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('FORMULA_SUPPLEMENT_IMMUTABLE_CONFLICT')
        else:
            temporary = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.pending')
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        return {'path': str(path.resolve()), 'sha256': digest}


def _atomic_pointer(path, value, expected_sha):
    path = Path(path)
    before = _sha(path.read_bytes()) if path.exists() else 'ABSENT'
    if before != expected_sha:
        raise ValueError('FORMULA_SUPPLEMENT_POINTER_MOVED')
    raw = _canonical(value) + b'\n'
    from ops.research_daily_capacity import serialized_write
    with serialized_write(path,raw):
        temporary = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.pending')
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if (_sha(path.read_bytes()) if path.exists() else 'ABSENT') != expected_sha:
            temporary.unlink(missing_ok=True)
            raise ValueError('FORMULA_SUPPLEMENT_POINTER_MOVED')
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {'path': str(path.resolve()), 'sha256': _sha(raw)}


def _numeric_product(context):
    from ops.research_panel_f10 import _exact_numeric_product

    root = context.root
    manifest_ref, manifest, product, event = _exact_numeric_product(context, root)
    return manifest_ref, manifest, product, event


def _group_identity(context, formula_ref, formula_receipt_ref, numeric_manifest, artifact, product):
    day = datetime.strptime(str(context.target), '%Y%m%d').date().isoformat()
    symbols = [row.get('symbol') for row in artifact.get('rows', [])]
    if (not isinstance(symbols, list) or any(not isinstance(symbol, str)
            or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol) for symbol in symbols)
            or len(symbols) != len(set(symbols)) or not set(symbols) <= set(product.get('row_refs', {}))
            or not set(symbols) <= set(product.get('processed_universe', []))):
        raise ValueError('FORMULA_SUPPLEMENT_ROSTER_CONFLICT')
    for symbol in symbols:
        row = _checked(product['row_refs'][symbol])
        if (row.get('symbol') != symbol or row.get('data_date') != str(context.target)
                or any(row.get(key) is not value for key, value in FLAGS.items())):
            raise ValueError('FORMULA_SUPPLEMENT_NUMERIC_ROW_CONFLICT:' + symbol)
    if (artifact.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1'
            or artifact.get('source_date') != day or artifact.get('generation') != context.generation
            or artifact.get('input_sha256') != context.identity.get('input_sha256')
            or artifact.get('numeric_manifest') != numeric_manifest
            or artifact.get('selector_sha256') != context.identity.get('selector_artifact_sha256')
            or artifact.get('formula_sha256') is None
            or formula_receipt_ref.get('path') is None):
        raise ValueError('FORMULA_SUPPLEMENT_GROUP_IDENTITY_CONFLICT')
    receipt = _checked(formula_receipt_ref)
    if (receipt.get('status') != 'COMMITTED' or receipt.get('artifact') != formula_ref
            or receipt.get('source_date') != day or receipt.get('generation') != context.generation
            or receipt.get('numeric_manifest') != numeric_manifest
            or any(receipt.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('FORMULA_SUPPLEMENT_GROUP_RECEIPT_CONFLICT')
    ordered = sorted(symbols)
    return day, ordered, _sha(_canonical(ordered))


def _chart_rows(bars, day):
    target = datetime.strptime(day, '%Y%m%d').date()
    first = (target - timedelta(days=250)).strftime('%Y%m%d')
    selected = [bar for bar in bars if first <= str(bar.get('trade_date')) <= day]
    result = []
    for bar in selected[-120:]:
        values = {}
        for source, target_name in (('open', 'open'), ('high', 'high'), ('low', 'low'),
                                    ('close', 'close'), ('vol', 'volume')):
            try:
                number = float(bar[source])
            except (TypeError, ValueError, KeyError) as error:
                from ops.research_daily_capacity import propagate_capacity_error
                propagate_capacity_error(error)
                raise ValueError('FORMULA_SUPPLEMENT_CHART_BAR_INVALID') from error
            if not math.isfinite(number) or (target_name == 'volume' and number < 0):
                raise ValueError('FORMULA_SUPPLEMENT_CHART_BAR_INVALID')
            values[target_name] = number
        if (values['low'] > min(values['open'], values['close'])
                or values['high'] < max(values['open'], values['close'])):
            raise ValueError('FORMULA_SUPPLEMENT_CHART_BAR_INVALID')
        result.append(dict(trade_date=str(bar['trade_date']), **values))
    if not result or result[-1]['trade_date'] != day or len({row['trade_date'] for row in result}) != len(result):
        raise ValueError('FORMULA_SUPPLEMENT_CHART_WINDOW_CONFLICT')
    return result


def _d35c_item(context, symbol, bars, qualification, chart_rows):
    if qualification.get('status') != 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
        raise ValueError('FORMULA_SUPPLEMENT_SOURCE_NOT_ACCEPTED')
    if not bars or bars[-1].get('trade_date') != context.target:
        raise ValueError('FORMULA_SUPPLEMENT_TARGET_BAR_MISSING')
    engine = context.engine()
    result = engine.json_ready(engine.compute(bars, mode='prefix'))
    inventory = engine.inventory()
    assignments = [item.get('name') for item in inventory.get('assignments', [])]
    if (result.get('formula_sha256') != FORMULA_SHA or result.get('mode') != 'prefix'
            or result.get('field_count') != 51 or result.get('drawing_count') != 22
            or len(result.get('rows', [])) != len(bars)
            or not {'白线', '黄线'} <= set(assignments)):
        raise ValueError('FORMULA_SUPPLEMENT_ENGINE_IDENTITY_CONFLICT')
    tail = result['rows'][-len(chart_rows):]
    if [str(row.get('trade_date')) for row in tail] != [row['trade_date'] for row in chart_rows]:
        raise ValueError('FORMULA_SUPPLEMENT_ENGINE_WINDOW_CONFLICT')
    marks, unresolved = [], 0
    for row in tail:
        drawings = row.get('drawings')
        if not isinstance(drawings, list) or len(drawings) != 22:
            raise ValueError('FORMULA_SUPPLEMENT_DRAWING_COVERAGE_CONFLICT')
        for drawing in drawings:
            condition = drawing.get('condition')
            if condition is None:
                unresolved += 1
                continue
            if type(condition) is not bool:
                raise ValueError('FORMULA_SUPPLEMENT_DRAWING_CONDITION_INVALID')
            if not condition:
                continue
            y = drawing.get('y')
            if y is None:
                raise ValueError('FORMULA_SUPPLEMENT_DRAWING_Y_MISSING')
            marks.append(dict(trade_date=str(row['trade_date']), id=drawing.get('id'),
                kind=drawing.get('kind'), payload=drawing.get('payload'), styles=drawing.get('styles'),
                y=str(y)))
    lines = {}
    for name in ('白线', '黄线'):
        points = []
        for source, chart in zip(tail, chart_rows):
            values = source.get('values')
            if not isinstance(values, dict) or name not in values:
                raise ValueError('FORMULA_SUPPLEMENT_LINE_VALUE_MISSING:' + name)
            value = values[name]
            points.append(dict(trade_date=chart['trade_date'], y=None if value is None else str(value)))
        lines[name] = points
    return dict(status='READY' if unresolved == 0 else 'PARTIAL_WITH_UNKNOWN',
        source_kind='DERIVED_BOUND_SELECTOR_PREFIX',
        source_sha256=_sha(_canonical(result)), unresolved_conditions=unresolved,
        chart_rows_sha256=_sha(_canonical(chart_rows)), marks=marks, lines=lines)


def _d35c_projection_is_renderable(item):
    """Accept only a structurally intact projection for retry reuse."""
    if (not isinstance(item, dict)
            or item.get('status') not in {'READY', 'PARTIAL_WITH_UNKNOWN'}
            or item.get('source_kind') != 'DERIVED_BOUND_SELECTOR_PREFIX'
            or type(item.get('unresolved_conditions')) is not int
            or item['unresolved_conditions'] < 0
            or not all(re.fullmatch(r'[0-9a-f]{64}', str(item.get(key) or ''))
                for key in ('source_sha256', 'chart_rows_sha256'))
            or not isinstance(item.get('marks'), list)):
        return False
    lines = item.get('lines')
    if not isinstance(lines, dict) or not {'白线', '黄线'} <= set(lines):
        return False
    white, yellow = lines['白线'], lines['黄线']
    if (not isinstance(white, list) or not isinstance(yellow, list)
            or not white or len(white) != len(yellow)):
        return False
    def valid_points(points):
        return all(isinstance(point, dict)
            and isinstance(point.get('trade_date'), str) and point['trade_date']
            and ('y' in point) and (point['y'] is None or isinstance(point['y'], str))
            for point in points)
    if (not valid_points(white) or not valid_points(yellow)
            or [point['trade_date'] for point in white]
                != [point['trade_date'] for point in yellow]):
        return False
    required_mark_fields = {'trade_date', 'id', 'kind', 'payload', 'styles', 'y'}
    return all(isinstance(mark, dict) and required_mark_fields <= set(mark)
        and isinstance(mark.get('trade_date'), str) and bool(mark['trade_date'])
        and (mark.get('y') is None or isinstance(mark.get('y'), str))
        for mark in item['marks'])


def _build_d35c_bundle(context, product, numeric_manifest, formula_ref, formula_artifact,
                       source_date, symbols, roster_sha256, previous_bundle=None):
    selector = dict(path=str(context.panel), sha256=context.identity['selector_artifact_sha256'])
    basis = context.identity['basis']
    bundle = dict(schema='V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1',
        formula_sha256=FORMULA_SHA, engine_sha256=ENGINE_SHA,
        source_date=source_date, generation=context.generation,
        input_sha256=context.identity['input_sha256'], numeric_manifest=numeric_manifest,
        selector=selector, snapshot=context.snapshot_ref,
        formula_group_sha256=formula_ref['sha256'], price_basis='QFQ_ASOF_' + str(context.target),
        volume_basis=basis['volume_basis'], roster_symbols_sha256=roster_sha256,
        items={}, historical_PIT=HISTORICAL_PIT, **FLAGS)
    for symbol in symbols:
        previous_item = (previous_bundle or {}).get('items', {}).get(symbol)
        if _d35c_projection_is_renderable(previous_item):
            # Older releases marked unresolved drawing predicates READY. Carry
            # their already verified projections forward and correct only the
            # status; do not discard known marks/lines or re-evaluate all bars
            # on every F10 retry.
            normalized_status = ('PARTIAL_WITH_UNKNOWN'
                if previous_item['unresolved_conditions'] else 'READY')
            bundle['items'][symbol] = (previous_item if previous_item.get('status') == normalized_status
                else {**previous_item, 'status': normalized_status})
            continue
        try:
            context.unchanged()
            bars, _ = context.read(symbol)
            qualification = context.qualify(symbol)
            chart_rows = _chart_rows(bars, str(context.target))
            bundle['items'][symbol] = _d35c_item(context, symbol, bars, qualification, chart_rows)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            from ops.research_daily_capacity import propagate_capacity_error
            propagate_capacity_error(error)
            bundle['items'][symbol] = dict(status='CANNOT_CONFIRM', reason=type(error).__name__ + ':' + str(error)[:200])
    context.unchanged()
    return bundle


def _build_score_replay(context, product, numeric_manifest, formula_ref, symbols, artifact_root,
                        previous_binding=None):
    from ops.materialize_workbench_score_action import authority_identity, materialize

    artifact_root = Path(artifact_root).resolve()
    expected_rules = authority_identity()
    old_index = None
    old_items = {}
    if isinstance(previous_binding, dict) and previous_binding.get('receipt'):
        previous_replay = _checked(previous_binding['receipt'])
        previous_descriptor = previous_replay.get('descriptor') or {}
        if (previous_replay.get('status') == 'PREPARED_EXACT_OWNER_REPLAY'
                and previous_replay.get('same_rule_sha') is True
                and previous_replay.get('formula_group_sha256') == formula_ref['sha256']
                and previous_descriptor.get('data_date') == str(context.target)
                and previous_descriptor.get('source_generation') == context.generation
                and previous_descriptor.get('input_sha256') == context.identity['input_sha256']
                and previous_descriptor.get('numeric_manifest') == numeric_manifest
                and Path(previous_binding.get('artifact_root', '')).resolve() == artifact_root):
            candidate = _checked(previous_descriptor['index'])
            if (candidate.get('numeric_manifest') != numeric_manifest
                    or candidate.get('source_generation') != context.generation
                    or candidate.get('input_sha256') != context.identity['input_sha256']
                    or candidate.get('source_selector_sha256') != context.identity['selector_artifact_sha256']
                    or candidate.get('rules') != expected_rules
                    or any(candidate.get(key) is not value for key, value in FLAGS.items())):
                raise ValueError('FORMULA_SUPPLEMENT_PRIOR_SCORE_IDENTITY_CONFLICT')
            old_index = candidate
            old_items = {symbol: ref for symbol, ref in candidate.get('items', {}).items()
                         if symbol in symbols}
            for symbol, reference in old_items.items():
                row = _checked(reference)
                if (row.get('symbol') != symbol or str(row.get('trade_date')) != str(context.target)
                        or any(row.get(key) is not value for key, value in FLAGS.items())):
                    raise ValueError('FORMULA_SUPPLEMENT_PRIOR_SCORE_ROW_CONFLICT:' + symbol)

    missing = sorted(set(symbols) - set(old_items))
    descriptor = None
    if missing:
        partial = materialize(context, product, numeric_manifest, output_root=artifact_root,
                              workers=1, symbols=missing)
        partial_index = _checked(partial['index'])
        if partial_index.get('rules') != expected_rules:
            raise ValueError('FORMULA_SUPPLEMENT_SCORE_RULE_SHA_CONFLICT')
        if old_index is None:
            index = partial_index
        else:
            if old_index.get('price_basis') != partial_index.get('price_basis'):
                raise ValueError('FORMULA_SUPPLEMENT_SCORE_BASIS_MOVED')
            index = dict(old_index, items={**old_items, **partial_index.get('items', {})})
        records = [_checked(reference) for reference in index['items'].values()]
        counts = dict(total=len(records),
            materialized=sum(row.get('status') == 'MATERIALIZED' for row in records),
            unknown=sum(row.get('status') == 'UNKNOWN' for row in records))
        index['counts'] = counts
        index_ref = _immutable(artifact_root / 'indexes', index)
        descriptor = dict(partial, index=index_ref, counts=counts,
            status='READY' if counts['unknown'] == 0 else 'PARTIAL_WITH_UNKNOWN')
    elif previous_binding and previous_binding.get('descriptor'):
        descriptor = previous_binding['descriptor']
    if descriptor is None:
        raise ValueError('FORMULA_SUPPLEMENT_SCORE_DESCRIPTOR_MISSING')

    index = _checked(descriptor['index'])
    if set(index.get('items', {})) != set(symbols):
        raise ValueError('FORMULA_SUPPLEMENT_SCORE_ROSTER_INCOMPLETE')
    statuses = {}
    for symbol in symbols:
        reference = index['items'][symbol]
        record = _checked(reference)
        hold = record.get('hold_score') or {}
        statuses[symbol] = dict(record_status=record.get('status'),
            score_status=hold.get('kb_hold_score_status', 'UNKNOWN'),
            score=hold.get('kb_hold_score'))
    receipt = dict(schema='V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1',
        status='PREPARED_EXACT_OWNER_REPLAY', same_rule_sha=True,
        descriptor=descriptor, statuses=statuses,
        score_rules=index.get('rules'), price_basis=index.get('price_basis'),
        score_rule_map_sha256=_sha(_canonical(index.get('rules'))),
        source_date=datetime.strptime(str(context.target), '%Y%m%d').date().isoformat(),
        source_generation=context.generation, input_sha256=context.identity['input_sha256'],
        numeric_manifest=numeric_manifest, formula_group_sha256=formula_ref['sha256'],
        **FLAGS)
    return descriptor, receipt


def _f10_roster_coverage(context, numeric_manifest, symbols, binding):
    """Partition only exact formula-roster symbols by their verified F10 result."""
    roster = set(symbols)
    reference = binding.get('receipt') if isinstance(binding, dict) else None
    if not isinstance(reference, dict):
        return set(), set(), set(roster)
    owner_root = (Path(context.root).resolve(strict=True) / 'f10'
        / str(context.target) / context.generation[:16])
    if not _f10_owner_ref_path(reference, owner_root, 'receipts'):
        raise ValueError('FORMULA_SUPPLEMENT_F10_RECEIPT_PATH_CONFLICT')
    receipt = _checked(reference, root=owner_root)
    if (receipt.get('schema') != 'v4.a_share.f10_daily_receipt.v1'
            or receipt.get('data_date') != str(context.target)
            or receipt.get('source_generation') != context.generation
            or receipt.get('input_sha256') != context.identity['input_sha256']
            or receipt.get('selector_sha256') != context.identity['selector_artifact_sha256']
            or receipt.get('numeric_manifest') != numeric_manifest
            or receipt.get('scope', {}).get('kind') != 'ADMITTED_DAILY_UNIVERSE'
            or receipt.get('priority_scope') != dict(symbols=sorted(symbols), count=len(symbols))
            or any(receipt.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('FORMULA_SUPPLEMENT_F10_RECEIPT_CONFLICT')
    checkpoint_ref = receipt.get('checkpoint')
    if not _f10_owner_ref_path(checkpoint_ref, owner_root, 'checkpoints'):
        raise ValueError('FORMULA_SUPPLEMENT_F10_CHECKPOINT_PATH_CONFLICT')
    checkpoint = _checked(checkpoint_ref, root=owner_root)
    identity = checkpoint.get('identity', {})
    if (checkpoint.get('schema') != 'v4.a_share.f10_checkpoint.v1'
            or identity.get('data_date') != str(context.target)
            or identity.get('source_generation') != context.generation
            or identity.get('input_sha256') != context.identity['input_sha256']
            or identity.get('selector_sha256') != context.identity['selector_artifact_sha256']
            or identity.get('scope_sha256') != receipt.get('scope_sha256')
            or checkpoint.get('upstream_success_receipt') != receipt.get('upstream_success_receipt')
            or any(checkpoint.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('FORMULA_SUPPLEMENT_F10_CHECKPOINT_CONFLICT')
    checkpoint_items = checkpoint.get('items')
    if not isinstance(checkpoint_items, dict):
        raise ValueError('FORMULA_SUPPLEMENT_F10_ITEMS_INVALID')
    if receipt.get('observed') != len(checkpoint_items):
        raise ValueError('FORMULA_SUPPLEMENT_F10_OBSERVED_COUNT_CONFLICT')
    claimed_observed = set()
    for symbol, ref in checkpoint_items.items():
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(symbol)):
            raise ValueError('FORMULA_SUPPLEMENT_F10_ITEM_SYMBOL_INVALID')
        if symbol not in roster:
            # The checkpoint is admitted-universe scoped. Its other immutable
            # stock shards are outside this roster decision and need not be read.
            continue
        claimed_observed.add(symbol)
    failures = receipt.get('failures', {})
    remaining_raw = receipt.get('remaining', [])
    if not isinstance(failures, dict) or not isinstance(remaining_raw, list):
        raise ValueError('FORMULA_SUPPLEMENT_F10_OUTCOME_PARTITION_INVALID')
    claimed_failed = set(failures) & roster
    if not set(failures) <= roster:
        raise ValueError('FORMULA_SUPPLEMENT_F10_FAILURE_OUTSIDE_PRIORITY_SCOPE')
    if any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(symbol)) for symbol in failures):
        raise ValueError('FORMULA_SUPPLEMENT_F10_FAILURE_SYMBOL_INVALID')
    if any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(symbol)) for symbol in remaining_raw):
        raise ValueError('FORMULA_SUPPLEMENT_F10_REMAINING_SYMBOL_INVALID')
    remaining_set = set(remaining_raw)
    if len(remaining_set) != len(remaining_raw):
        raise ValueError('FORMULA_SUPPLEMENT_F10_REMAINING_DUPLICATE')
    claimed_remaining = remaining_set & roster
    if (claimed_observed & claimed_failed or claimed_observed & claimed_remaining
            or claimed_failed & claimed_remaining):
        raise ValueError('FORMULA_SUPPLEMENT_F10_DUPLICATE_OUTCOME')
    observed, failed = set(), set(claimed_failed)
    for symbol in sorted(claimed_observed):
        try:
            if not _f10_owner_ref_path(checkpoint_items[symbol], owner_root, 'stocks', symbol):
                raise ValueError('FORMULA_SUPPLEMENT_F10_ITEM_PATH_CONFLICT')
            row = _checked(checkpoint_items[symbol], root=owner_root)
            if (not isinstance(row, dict) or row.get('symbol') != symbol
                    or row.get('status') != 'OBSERVED' or row.get('historical_PIT') is not False
                    or any(row.get(key) is not value for key, value in FLAGS.items())):
                raise ValueError('FORMULA_SUPPLEMENT_F10_ITEM_CONFLICT')
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as _capacity_error:
            from ops.research_daily_capacity import propagate_capacity_error
            propagate_capacity_error(_capacity_error)
            failed.add(symbol)
        else:
            observed.add(symbol)
    remaining = claimed_remaining | (roster - claimed_observed - claimed_failed)
    if observed & failed or observed & remaining or failed & remaining:
        raise ValueError('FORMULA_SUPPLEMENT_F10_OUTCOME_PARTITION_CONFLICT')
    return observed, failed, remaining


def _f10_owner_ref_path(reference, owner_root, directory, symbol=None):
    if not isinstance(reference, dict):
        return False
    digest = reference.get('sha256')
    path_text = reference.get('path')
    if (not isinstance(path_text, str) or not isinstance(digest, str)
            or not re.fullmatch(r'[0-9a-f]{64}', digest)):
        return False
    expected_parent = Path(owner_root) / directory
    if symbol is not None:
        expected_parent = expected_parent / symbol
    return Path(path_text) == expected_parent / (digest + '.json')


def _f10_roster_complete(symbols, observed, failed, remaining):
    roster = set(symbols)
    return observed == roster and not failed and not remaining


def _d35c_roster_complete(reference, symbols):
    if not isinstance(reference, dict):
        return False
    bundle = _checked(reference)
    items = bundle.get('items')
    return (isinstance(items, dict) and set(items) == set(symbols)
        and all(_d35c_projection_is_renderable(item) and item.get('status') == 'READY'
            and item.get('unresolved_conditions') == 0 for item in items.values()))


def _current_supplement(day_root, expected):
    latest = day_root / 'supplements' / 'latest.json'
    if not latest.exists():
        return latest, 'ABSENT', None
    if latest.is_symlink() or latest.resolve(strict=True) != latest:
        raise ValueError('FORMULA_SUPPLEMENT_LATEST_PATH_INVALID')
    raw = latest.read_bytes()
    pointer_sha = _sha(raw)
    pointer = json.loads(raw)
    artifact_ref, receipt_ref = pointer.get('artifact'), pointer.get('receipt')
    if (pointer.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1'
            or pointer.get('module') != 'formula_group_supplement'
            or pointer.get('source_date') != expected['source_date']
            or any(pointer.get(key) != value for key, value in FLAGS.items())
            or not isinstance(artifact_ref, dict) or not isinstance(receipt_ref, dict)):
        raise ValueError('FORMULA_SUPPLEMENT_POINTER_CONFLICT')
    supplement_root = latest.parent.resolve(strict=True)
    for reference in (artifact_ref, receipt_ref):
        path = Path(reference.get('path', ''))
        if not path.is_absolute() or not path.is_relative_to(supplement_root):
            raise ValueError('FORMULA_SUPPLEMENT_REFERENCE_OUTSIDE_DATE_ROOT')
    if any(pointer.get(key) != value for key, value in expected.items()):
        # The previous pointer can be valid for an older generation or roster.
        # Never read or reuse those artifact bytes for the new current identity.
        return latest, pointer_sha, None
    artifact = _checked(artifact_ref)
    receipt = _checked(receipt_ref)
    if (receipt.get('status') != 'COMMITTED' or receipt.get('artifact') != artifact_ref
            or any(receipt.get(key) is not value for key, value in FLAGS.items())
            or any(receipt.get(key) != value for key, value in expected.items())
            or any(artifact.get(key) != value for key, value in expected.items())):
        raise ValueError('FORMULA_SUPPLEMENT_RECEIPT_CONFLICT')
    return latest, pointer_sha, dict(pointer=pointer, artifact=artifact, artifact_ref=artifact_ref,
                                      receipt=receipt, receipt_ref=receipt_ref)


def complete(context, formula_groups_root, formula_ref, formula_receipt_ref):
    from ops.research_storage_governance import configured_policy, governed_formula_supplements
    from ops.research_daily_capacity import enabled, current_writer, CapacityProofError
    policy = configured_policy()
    if policy and enabled(policy) and current_writer() is None:
        import sys
        return governed_formula_supplements(context,formula_groups_root,formula_ref,formula_receipt_ref,
                                           module=sys.modules[__name__])
    return _complete_owned(context,formula_groups_root,formula_ref,formula_receipt_ref)


def _complete_owned(context, formula_groups_root, formula_ref, formula_receipt_ref):
    """Build/reuse dated F10, chart and score supplements for the committed roster."""
    result = dict(status='CANNOT_CONFIRM', data_date=str(context.target), **FLAGS)
    try:
        context.unchanged()
        numeric_manifest, manifest, product, event = _numeric_product(context)
        formula_artifact = _checked(formula_ref)
        source_date, symbols, roster_sha256 = _group_identity(context, formula_ref,
            formula_receipt_ref, numeric_manifest, formula_artifact, product)
        observation_date = formula_artifact['observation_date']
        expected = dict(source_date=source_date, observation_date=observation_date,
            generation=context.generation, input_sha256=context.identity['input_sha256'],
            numeric_manifest=numeric_manifest, selector_sha256=context.identity['selector_artifact_sha256'],
            formula_group_sha256=formula_ref['sha256'], roster_symbols_sha256=roster_sha256,
            roster_count=len(symbols))
        result.update(expected)
        day_root = Path(formula_groups_root) / source_date
        latest, previous_sha, previous = _current_supplement(day_root, expected)
        if previous and previous['artifact'].get('status') == 'COMPLETE':
            # A prior writer version could count failed rows as attempted. Only
            # a fresh exact-roster readback may retain COMPLETE on this no-write
            # path. Incorrect legacy COMPLETE is corrected below by publishing
            # a new PARTIAL supplement pointer, without changing source data.
            previous_f10 = previous['artifact'].get('f10') or {}
            try:
                prev_observed, prev_failed, prev_remaining = _f10_roster_coverage(
                    context, numeric_manifest, symbols, previous_f10) if symbols else (set(), set(), set())
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as _capacity_error:
                from ops.research_daily_capacity import propagate_capacity_error
                propagate_capacity_error(_capacity_error)
                prev_observed, prev_failed, prev_remaining = set(), set(), set(symbols)
            previous_chart_complete = False
            try:
                previous_chart_complete = _d35c_roster_complete(
                    previous['artifact'].get('d35c_marks'), symbols)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as _capacity_error:
                from ops.research_daily_capacity import propagate_capacity_error
                propagate_capacity_error(_capacity_error)
                previous_chart_complete = False
            if (_f10_roster_complete(symbols, prev_observed, prev_failed, prev_remaining)
                    and previous_chart_complete
                    and previous['artifact'].get('d35c_status') == 'READY'):
                return dict(status='ALREADY_COMMITTED', pointer=previous['pointer'], receipt=previous['receipt_ref'],
                            artifact=previous['artifact_ref'], **expected, **FLAGS)

        previous_artifact = previous['artifact'] if previous else {}
        previous_bundle = None
        previous_bundle_ref = previous_artifact.get('d35c_marks')
        if isinstance(previous_bundle_ref, dict):
            candidate = _checked(previous_bundle_ref)
            required_bundle_identity = dict(source_date=source_date, generation=context.generation,
                input_sha256=context.identity['input_sha256'], numeric_manifest=numeric_manifest,
                formula_group_sha256=formula_ref['sha256'], roster_symbols_sha256=roster_sha256)
            if (candidate.get('schema') != 'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1'
                    or candidate.get('formula_sha256') != FORMULA_SHA
                    or candidate.get('engine_sha256') != ENGINE_SHA
                    or any(candidate.get(key) != value for key, value in required_bundle_identity.items())
                    or any(candidate.get(key) is not value for key, value in (FLAGS | {'historical_PIT': False}).items())
                    or set(candidate.get('items', {})) != set(symbols)):
                raise ValueError('FORMULA_SUPPLEMENT_PRIOR_D35C_IDENTITY_CONFLICT')
            previous_bundle = candidate
        bundle = _build_d35c_bundle(context, product, numeric_manifest, formula_ref,
                                    formula_artifact, source_date, symbols, roster_sha256,
                                    previous_bundle=previous_bundle)
        bundle_ref = _immutable(day_root / 'supplements' / 'artifacts' / 'd35c_marks', bundle)
        chart_ready = sum(item.get('status') == 'READY' for item in bundle['items'].values())
        chart_status = 'READY' if chart_ready == len(symbols) else 'PARTIAL_WITH_UNKNOWN'

        score_binding = previous_artifact.get('score_action') or dict(status='CANNOT_CONFIRM', reason='SCORE_NOT_RUN')
        try:
            if symbols:
                descriptor, replay = _build_score_replay(context, product, numeric_manifest, formula_ref,
                    symbols, context.root / 'score_action', previous_binding=score_binding)
                replay_ref = _immutable(day_root / 'supplements' / 'receipts' / 'score_action', replay)
                score_binding = dict(status=descriptor['status'], receipt=replay_ref,
                    artifact_root=str((context.root / 'score_action').resolve()), descriptor=descriptor)
            else:
                score_binding = dict(status='READY_EMPTY', receipt=None,
                                     artifact_root=str((context.root / 'score_action').resolve()), descriptor=None)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            from ops.research_daily_capacity import propagate_capacity_error
            propagate_capacity_error(error)
            score_binding = dict(status='CANNOT_CONFIRM', reason=type(error).__name__ + ':' + str(error)[:200])

        f10_binding = previous_artifact.get('f10') or dict(status='NOT_RUN_EMPTY_ROSTER' if not symbols else 'CANNOT_CONFIRM')
        try:
            observed, failed, unattempted = _f10_roster_coverage(
                context, numeric_manifest, symbols, f10_binding) if symbols else (set(), set(), set())
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as _capacity_error:
            from ops.research_daily_capacity import propagate_capacity_error
            propagate_capacity_error(_capacity_error)
            observed, failed, unattempted = set(), set(), set(symbols)
            f10_binding = dict(status='CANNOT_CONFIRM')
        if symbols:
            if failed or unattempted or f10_binding.get('status') == 'CANNOT_CONFIRM':
              try:
                from ops.research_panel_f10 import complete_f10, exact_daily_source_receipt, publish_f10_completion
                source_ready = exact_daily_source_receipt(context, context.root, context.root)
                f10 = complete_f10(context, source_ready, context.root,
                    workers=min(4, max(1, int(os.environ.get('RESEARCH_PANEL_QFQ_WORKERS', '4')))),
                    priority_symbols=symbols, priority_only=True)
                f10['publication'] = publish_f10_completion(context, context.root, f10['receipt'])
                f10_binding = dict(status=f10.get('status'), receipt=f10.get('receipt'), publication=f10.get('publication'),
                    requested=f10.get('requested'), observed=f10.get('observed'),
                    failure_count=f10.get('failure_count'), remaining_count=f10.get('remaining_count'))
                observed, failed, unattempted = _f10_roster_coverage(context, numeric_manifest, symbols, f10_binding)
              except (ValueError, OSError, KeyError, TypeError, AttributeError, RuntimeError) as error:
                from ops.research_daily_capacity import propagate_capacity_error
                propagate_capacity_error(error)
                retry_error = type(error).__name__ + ':' + str(error)[:200]
                if isinstance(f10_binding, dict) and isinstance(f10_binding.get('receipt'), dict):
                    # Keep the last immutable, source-bound partial receipt
                    # available if reacquisition or publication fails.
                    f10_binding = {**f10_binding, 'retry_status':'CANNOT_CONFIRM',
                        'retry_reason':retry_error}
                else:
                    f10_binding = dict(status='CANNOT_CONFIRM', reason=retry_error)

        score_status = score_binding.get('status')
        score_receipt = _checked(score_binding['receipt']) if score_binding.get('receipt') else {}
        score_outcomes = set(score_receipt.get('statuses', {}))
        f10_covered = _f10_roster_complete(symbols, observed, failed, unattempted) if symbols else True
        complete_stages = (set(bundle.get('items', {})) == set(symbols)
            and chart_status == 'READY'
            and score_outcomes == set(symbols)
            and (score_status in {'READY', 'PARTIAL_WITH_UNKNOWN', 'READY_EMPTY'})
            and f10_covered)
        supplement = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1',
            status='COMPLETE' if complete_stages else 'PARTIAL', **expected,
            formula_group_artifact=formula_ref, formula_group_receipt=formula_receipt_ref,
            d35c_marks=bundle_ref, d35c_status=chart_status,
            score_action=score_binding, f10=f10_binding,
            counts=dict(roster=len(symbols), d35c_ready=chart_ready,
                        f10_observed=len(observed), f10_failed=len(failed),
                        f10_unattempted=len(unattempted)), **FLAGS)
        supplement_ref = _immutable(day_root / 'supplements' / 'artifacts', supplement)
        receipt = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1',
            status='COMMITTED', artifact=supplement_ref, **expected, **FLAGS)
        receipt_ref = _immutable(day_root / 'supplements' / 'receipts', receipt)
        pointer = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1',
            module='formula_group_supplement', **expected,
            status=supplement['status'], artifact=supplement_ref, receipt=receipt_ref, **FLAGS)
        if previous and pointer == previous.get('pointer'):
            return dict(status=supplement['status'], pointer=previous['pointer'],
                receipt=previous['receipt_ref'], artifact=previous['artifact_ref'],
                f10=f10_binding, score_action=score_binding, d35c_status=chart_status,
                counts=supplement['counts'], idempotent=True, **expected, **FLAGS)
        pointer_ref = _atomic_pointer(latest, pointer, previous_sha)
        context.unchanged()
        return dict(status=supplement['status'], pointer=pointer_ref, receipt=receipt_ref,
            artifact=supplement_ref, f10=f10_binding, score_action=score_binding,
            d35c_status=chart_status, counts=supplement['counts'], **expected, **FLAGS)
    except Exception as error:
        from ops.research_daily_capacity import propagate_capacity_error
        propagate_capacity_error(error)
        return {**result, 'status': 'CANNOT_CONFIRM', 'reason': type(error).__name__ + ':' + str(error)[:240]}


__all__ = ['complete']
