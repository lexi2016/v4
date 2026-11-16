"""Read a bounded drawing sidecar for the existing formula-group candles."""
from __future__ import annotations

import hashlib
import json
import math
import re

SCHEMA = 'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1'
FORMULA_SHA = 'd35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'
ENGINE_SHA = 'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False, historical_PIT=False)
IDENTITY_FIELDS = ('source_date', 'generation', 'input_sha256', 'numeric_manifest', 'selector', 'snapshot',
                   'formula_group_sha256', 'price_basis', 'volume_basis')
SOURCE_KINDS = {'REUSED_ORIGINAL_V4_PROJECTION', 'DERIVED_BOUND_SELECTOR_PREFIX'}
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
    return dict(metadata, status='READY', source_kind=item['source_kind'], marks=item['marks'],
                unresolved_conditions=item['unresolved_conditions'])
