"""Read a bounded drawing sidecar for the existing formula-group candles."""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import math
import re
from decimal import Decimal, InvalidOperation

SCHEMA = 'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1'
FORMULA_SHA = 'd35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'
ENGINE_SHA = 'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False, historical_PIT=False)
IDENTITY_FIELDS = ('source_date', 'generation', 'input_sha256', 'numeric_manifest', 'selector', 'snapshot',
                   'formula_group_sha256', 'price_basis', 'volume_basis')
SOURCE_KINDS = {'REUSED_ORIGINAL_V4_PROJECTION', 'DERIVED_BOUND_SELECTOR_PREFIX'}
LINE_NAMES = ('白线', '黄线')
DECIMAL_TEXT = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
COLOR = re.compile(r'COLOR(?:RED|GREEN|YELLOW|FFFFFF|FF00FF)')


def canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _validate_mark(mark, dates):
    if (not isinstance(mark, dict) or set(mark) != {'trade_date', 'id', 'kind', 'payload', 'styles', 'y'}
            or mark['trade_date'] not in dates or type(mark['id']) is not int or not 1 <= mark['id'] <= 22
            or not isinstance(mark['y'], str) or not 0 < len(mark['y']) <= 64 or not math.isfinite(float(mark['y']))
            or not isinstance(mark['payload'], str)):
        raise ValueError('ORIGINAL_D35C_MARK_INVALID')
    if mark['kind'] == 'DRAWICON' and mark['payload'] in ('1', '2') and mark['styles'] == []:
        return
    if (mark['kind'] == 'DRAWTEXT' and 0 < len(mark['payload']) <= 24
            and isinstance(mark['styles'], list) and len(mark['styles']) == 1
            and isinstance(mark['styles'][0], str) and COLOR.fullmatch(mark['styles'][0])):
        return
    raise ValueError('ORIGINAL_D35C_STYLE_INVALID')


def _decimal_string(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('ORIGINAL_D35C_LINE_VALUE_INVALID')
    text = str(value).strip()
    if len(text) > 64 or not DECIMAL_TEXT.fullmatch(text):
        raise ValueError('ORIGINAL_D35C_LINE_VALUE_INVALID')
    try:
        number = Decimal(text)
        binary = float(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError('ORIGINAL_D35C_LINE_VALUE_INVALID') from error
    if (not number.is_finite() or not math.isfinite(binary)
            or (number != 0 and binary == 0)):
        raise ValueError('ORIGINAL_D35C_LINE_VALUE_INVALID')
    return text


def _validate_lines(lines, chart_rows):
    if not isinstance(lines, dict) or set(lines) != set(LINE_NAMES):
        raise ValueError('ORIGINAL_D35C_LINE_SCHEMA_INVALID')
    dates = [row.get('trade_date') for row in chart_rows]
    result = {}
    for name in LINE_NAMES:
        points = lines[name]
        if not isinstance(points, list) or len(points) != len(dates):
            raise ValueError('ORIGINAL_D35C_LINE_COVERAGE_CONFLICT')
        checked = []
        for point, expected_date in zip(points, dates):
            if (not isinstance(point, dict) or set(point) != {'trade_date', 'y'}
                    or point.get('trade_date') != expected_date):
                raise ValueError('ORIGINAL_D35C_LINE_DATE_CONFLICT')
            value = point['y']
            if value is not None:
                value = _decimal_string(value)
            checked.append(dict(trade_date=expected_date, y=value))
        result[name] = checked
    return result


def chart_original_marks(bundle, reference, chart, symbols):
    identity = {key: chart[key] for key in IDENTITY_FIELDS}
    if (not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA
            or bundle.get('formula_sha256') != FORMULA_SHA or bundle.get('engine_sha256') != ENGINE_SHA
            or any(bundle.get(key) != value for key, value in identity.items())
            or any(bundle.get(key) is not value for key, value in FLAGS.items())
            or not isinstance(bundle.get('items'), dict) or set(bundle['items']) != set(symbols)):
        raise ValueError('ORIGINAL_D35C_SOURCE_CONFLICT')
    symbol = chart['symbol']
    item = bundle['items'][symbol]
    metadata = dict(schema=SCHEMA, symbol=symbol, formula_sha256=FORMULA_SHA, engine_sha256=ENGINE_SHA,
                    sidecar=reference, **identity)
    if item.get('status') == 'CANNOT_CONFIRM' and not item.get('marks'):
        return dict(metadata, status='CANNOT_CONFIRM', reason='ORIGINAL_D35C_SOURCE_GAP')
    if (item.get('status') != 'READY' or item.get('source_kind') not in SOURCE_KINDS
            or not re.fullmatch(r'[a-f0-9]{64}', item.get('source_sha256') or '')
            or type(item.get('unresolved_conditions')) is not int
            or not 0 <= item['unresolved_conditions'] <= len(chart['rows']) * 22
            or item.get('chart_rows_sha256') != canonical_sha(chart['rows'])
            or not isinstance(item.get('marks'), list) or len(item['marks']) > len(chart['rows']) * 22):
        raise ValueError('ORIGINAL_D35C_WINDOW_CONFLICT')
    dates = {bar['trade_date'] for bar in chart['rows']}
    identities = set()
    for mark in item['marks']:
        _validate_mark(mark, dates)
        key = (mark['trade_date'], mark['id'])
        if key in identities:
            raise ValueError('ORIGINAL_D35C_DUPLICATE_MARK')
        identities.add(key)
    result = dict(metadata, status='READY', source_kind=item['source_kind'], marks=item['marks'],
                  unresolved_conditions=item['unresolved_conditions'])
    if 'lines' in item:
        result['lines'] = _validate_lines(item['lines'], chart['rows'])
    return result


def chart_original_marks_from_projection(raw, reference, chart):
    """Project already-materialized native drawings onto the matching daily K bars.

    The projection is an original owner artifact. This adapter only validates
    its identity and window, then exposes stored marks to the existing canvas;
    it never evaluates the formula.
    """
    if (not isinstance(raw, bytes) or not isinstance(reference, dict)
            or not isinstance(reference.get('path'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', reference.get('sha256') or '')
            or hashlib.sha256(raw).hexdigest() != reference['sha256']):
        raise ValueError('ORIGINAL_D35C_PROJECTION_SHA_CONFLICT')
    try:
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                payload = stream.read(64 * 1024 * 1024 + 1)
        else:
            payload = raw
        if len(payload) > 64 * 1024 * 1024:
            raise ValueError('ORIGINAL_D35C_PROJECTION_SIZE_LIMIT')
        projection = json.loads(payload)
    except (OSError, EOFError, json.JSONDecodeError, TypeError) as error:
        raise ValueError('ORIGINAL_D35C_PROJECTION_INVALID') from error

    source_date = chart.get('source_date')
    compact_date = source_date.replace('-', '') if isinstance(source_date, str) else None
    source = projection.get('source') or {}
    lineage = projection.get('lineage') or {}
    formula = projection.get('formula_result') or {}
    rows = formula.get('rows')
    if (projection.get('schema') != 'v4.d35c.bound_candidate_projection.v1'
            or projection.get('authority') != 'DERIVED_RENDERING_ONLY'
            or projection.get('symbol') != chart.get('symbol')
            or projection.get('data_date') != compact_date
            or projection.get('historical_PIT') is not False
            or any(projection.get(key) is not value for key, value in FLAGS.items())
            or source.get('generation_id') != chart.get('generation')
            or source.get('source_input_sha256') != chart.get('input_sha256')
            or source.get('price_basis') != 'QFQ_ASOF'
            or source.get('volume_basis') != chart.get('volume_basis')
            or lineage.get('formula', {}).get('sha256') != FORMULA_SHA
            or lineage.get('engine', {}).get('sha256') != ENGINE_SHA
            or projection.get('unsupported_drawings') != []
            or formula.get('formula_sha256') != FORMULA_SHA
            or formula.get('mode') != 'prefix'
            or formula.get('field_count') != 51 or formula.get('drawing_count') != 22
            or not isinstance(rows, list) or not rows
            or not isinstance(chart.get('rows'), list)
            or len(chart['rows']) != min(120, len(rows))
            or chart.get('price_basis') != 'QFQ_ASOF_' + str(compact_date)):
        raise ValueError('ORIGINAL_D35C_PROJECTION_IDENTITY_CONFLICT')

    chart_rows = chart['rows']
    dates = [str(row.get('trade_date')) for row in chart_rows]
    formula_dates = [str(row.get('trade_date')) for row in rows]
    if (any(not re.fullmatch(r'\d{8}', value) for value in dates + formula_dates)
            or any(left >= right for left, right in zip(dates, dates[1:]))
            or any(left >= right for left, right in zip(formula_dates, formula_dates[1:]))
            or dates[-1] != compact_date or formula_dates[-1] != compact_date
            or formula_dates[-len(dates):] != dates):
        raise ValueError('ORIGINAL_D35C_WINDOW_DATE_CONFLICT')

    def exact_number(value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None

    for original, current in zip(rows[-len(chart_rows):], chart_rows):
        old_bar = original.get('ohlcv')
        if not isinstance(old_bar, dict) or str(old_bar.get('trade_date')) != current['trade_date']:
            raise ValueError('ORIGINAL_D35C_WINDOW_OHLCV_CONFLICT')
        for old_key, current_key in (('open', 'open'), ('high', 'high'), ('low', 'low'),
                                     ('close', 'close'), ('vol', 'volume')):
            old_value, current_value = exact_number(old_bar.get(old_key)), exact_number(current.get(current_key))
            if old_value is None or current_value is None or old_value != current_value:
                raise ValueError('ORIGINAL_D35C_WINDOW_OHLCV_CONFLICT')

    marks = []
    unresolved = 0
    window_rows = rows[-len(chart_rows):]
    for row in window_rows:
        drawings = row.get('drawings')
        if not isinstance(drawings, list) or len(drawings) != 22:
            raise ValueError('ORIGINAL_D35C_DRAWING_COVERAGE_CONFLICT')
        seen_ids = set()
        for drawing in drawings:
            if (not isinstance(drawing, dict) or type(drawing.get('id')) is not int
                    or not 1 <= drawing['id'] <= 22 or drawing['id'] in seen_ids
                    or drawing.get('kind') not in ('DRAWTEXT', 'DRAWICON')
                    or not isinstance(drawing.get('styles'), list)):
                raise ValueError('ORIGINAL_D35C_DRAWING_INVALID')
            seen_ids.add(drawing['id'])
            condition = drawing.get('condition')
            if condition is None:
                unresolved += 1
                continue
            if type(condition) is not bool:
                raise ValueError('ORIGINAL_D35C_DRAWING_CONDITION_INVALID')
            if not condition:
                continue
            mark = dict(trade_date=str(row['trade_date']), id=drawing['id'], kind=drawing['kind'],
                        payload=drawing.get('payload'), styles=drawing['styles'], y=drawing.get('y'))
            marks.append(mark)

    # Reuse the formula engine's stored values verbatim. Older retained
    # projections may not contain these two named fields, so their existing
    # drawing-only behavior remains valid.
    value_rows = [row.get('values') for row in window_rows]
    line_fields_present = any(isinstance(values, dict) and any(name in values for name in LINE_NAMES)
                              for values in value_rows)
    lines = None
    if line_fields_present:
        if not all(isinstance(values, dict) and all(name in values for name in LINE_NAMES)
                   for values in value_rows):
            raise ValueError('ORIGINAL_D35C_LINE_COVERAGE_CONFLICT')
        lines = {
            name: [dict(trade_date=current['trade_date'],
                        y=None if values[name] is None else _decimal_string(values[name]))
                   for values, current in zip(value_rows, chart_rows)]
            for name in LINE_NAMES
        }

    bundle = dict(schema=SCHEMA, formula_sha256=FORMULA_SHA, engine_sha256=ENGINE_SHA,
                  items={chart['symbol']: dict(status='READY', marks=marks,
                      source_kind='REUSED_ORIGINAL_V4_PROJECTION', source_sha256=reference['sha256'],
                      unresolved_conditions=unresolved, chart_rows_sha256=canonical_sha(chart_rows))},
                  **{key: chart[key] for key in IDENTITY_FIELDS}, **FLAGS)
    if lines is not None:
        bundle['items'][chart['symbol']]['lines'] = lines
    return chart_original_marks(bundle, reference, chart, [chart['symbol']])
