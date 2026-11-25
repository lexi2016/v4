"""Causal, source-bound local V1 N structure on one QFQ daily-bar prefix.

This module does not read data, calculate the other score components, write a
checkpoint, or create a producer. The existing producer owns all of those.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import re


RULE_ID = 'ZGE_N_TREND_CONFIRMED_5X5_CLOSE_BREAK_LOCAL_V1'
CHECKPOINT_SCHEMA = 'kb_n_structure_checkpoint_v1'
_EMPTY_DIGEST = hashlib.sha256(b'').hexdigest()
_HASH = re.compile(r'^[0-9a-f]{64}$')
_CODE = re.compile(r'^\d{6}\.(?:SZ|SH|BJ)$')


def _hash_value(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _identity(code, identity):
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError('N_STRUCTURE_SYMBOL_INVALID')
    if not isinstance(identity, dict) or identity.get('price_basis') != 'QFQ_ASOF':
        raise ValueError('N_STRUCTURE_PRICE_BASIS_UNBOUND')
    generation_id = identity.get('generation_id')
    if not isinstance(generation_id, str) or not generation_id.strip():
        raise ValueError('N_STRUCTURE_GENERATION_UNBOUND')
    keys = ('input_sha256', 'rule_sha256', 'helper_sha256', 'calendar_sha256', 'price_basis_sha256')
    result = {key: identity.get(key) for key in keys}
    for key, value in result.items():
        if value is None and key in ('calendar_sha256', 'price_basis_sha256'):
            continue
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise ValueError('N_STRUCTURE_IDENTITY_INVALID:' + key)
    result['price_basis'] = 'QFQ_ASOF'
    result['generation_id'] = generation_id
    return result


def _number(value):
    if hasattr(value, 'item'):
        try:
            value = value.item()
        except (TypeError, ValueError):
            return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _bar(code, source):
    if not isinstance(source, dict):
        raise ValueError('N_STRUCTURE_BAR_INVALID')
    if 'ts_code' in source and source['ts_code'] != code:
        raise ValueError('N_STRUCTURE_BAR_SYMBOL_CONFLICT')
    raw_date = str(source.get('trade_date', ''))
    if not re.fullmatch(r'\d{8}', raw_date):
        raise ValueError('N_STRUCTURE_DATE_INVALID')
    try:
        date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:]))
    except ValueError as exc:
        raise ValueError('N_STRUCTURE_DATE_INVALID') from exc
    high, low, close = (_number(source.get(key)) for key in ('high', 'low', 'close'))
    valid = (high is not None and low is not None and close is not None
             and low <= close <= high)
    return {'trade_date': raw_date, 'high': high, 'low': low, 'close': close, 'valid': valid}


def _next_digest(digest, bar):
    encoded = json.dumps(bar, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(bytes.fromhex(digest) + encoded).hexdigest()


def n_prefix_sha256(code, rows):
    """Recompute the canonical HLC prefix identity, without calculating N.

    The producer can use this against its bound new source to validate a saved
    checkpoint. This digest is distinct from the SHA of the raw source file.
    """
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError('N_STRUCTURE_SYMBOL_INVALID')
    digest, previous = _EMPTY_DIGEST, None
    for source in rows:
        bar = _bar(code, source)
        if previous is not None and bar['trade_date'] <= previous:
            raise ValueError('N_STRUCTURE_DATES_NOT_UNIQUE_SORTED')
        previous = bar['trade_date']
        digest = _next_digest(digest, bar)
    return digest


def _new_state(code, identity):
    return {'schema': CHECKPOINT_SCHEMA, 'rule_id': RULE_ID, 'symbol': code,
            'identity': identity, 'prefix_sha256': _EMPTY_DIGEST, 'last_trade_date': None,
            'history_bar_count': 0, 'consecutive_valid_bars': 0,
            'window': [], 'swings': [], 'disruption': None}


def _seal(state):
    payload = deepcopy(state)
    payload['checkpoint_sha256'] = _hash_value(state)
    return payload


def _resume(code, identity, checkpoint, expected_prefix_sha256):
    if not isinstance(checkpoint, dict):
        raise ValueError('N_STRUCTURE_CHECKPOINT_INVALID')
    payload = deepcopy(checkpoint)
    digest = payload.pop('checkpoint_sha256', None)
    try:
        intact = digest == _hash_value(payload)
    except (ValueError, TypeError):
        intact = False
    if not intact or payload.get('schema') != CHECKPOINT_SCHEMA or payload.get('rule_id') != RULE_ID:
        raise ValueError('N_STRUCTURE_CHECKPOINT_INTEGRITY_CONFLICT')
    if payload.get('symbol') != code:
        raise ValueError('N_STRUCTURE_CHECKPOINT_SYMBOL_CONFLICT')
    if not isinstance(expected_prefix_sha256, str) or expected_prefix_sha256 != payload.get('prefix_sha256'):
        raise ValueError('N_STRUCTURE_CHECKPOINT_PREFIX_CONFLICT')
    old = payload.get('identity')
    if not isinstance(old, dict) or any(old.get(k) != identity.get(k) for k in
            ('price_basis', 'calendar_sha256', 'price_basis_sha256', 'rule_sha256', 'helper_sha256')):
        raise ValueError('N_STRUCTURE_CHECKPOINT_IDENTITY_CONFLICT')
    if (old.get('input_sha256') != identity['input_sha256']
            or old.get('generation_id') != identity['generation_id']) and (
            not identity['calendar_sha256'] or not identity['price_basis_sha256']):
        raise ValueError('N_STRUCTURE_CROSS_GENERATION_IDENTITY_UNBOUND')
    payload['identity'] = identity
    return payload


def _add_swing(state, kind, center, confirmed_at):
    point = {'kind': kind, 'event_date': center['trade_date'], 'confirmed_at': confirmed_at,
             'price': center['low'] if kind == 'L' else center['high']}
    swings = state['swings']
    if swings and swings[-1]['kind'] == kind:
        prev = swings[-1]['price']
        if (kind == 'L' and point['price'] <= prev) or (kind == 'H' and point['price'] >= prev):
            swings[-1] = point
    else:
        swings.append(point)
        del swings[:-4]
    if len(swings) == 4:
        state['disruption'] = None


def _observe(state, bar):
    window = state['window'] + [bar]
    if not bar['valid']:
        state['consecutive_valid_bars'] = 0
        state['swings'] = []
        state['disruption'] = 'INVALID_INPUT'
    else:
        state['consecutive_valid_bars'] += 1
        if len(window) == 11 and all(item['valid'] for item in window):
            center, right = window[5], window[6:]
            high = (center['high'] == max(item['high'] for item in window)
                    and all(item['high'] != center['high'] for item in right))
            low = (center['low'] == min(item['low'] for item in window)
                   and all(item['low'] != center['low'] for item in right))
            if high and low:
                state['swings'] = []
                state['disruption'] = 'AMBIGUOUS_SAME_BAR_PIVOT'
            elif high or low:
                _add_swing(state, 'H' if high else 'L', center, bar['trade_date'])
    state['window'] = window[-10:]
    state['last_trade_date'] = bar['trade_date']
    state['history_bar_count'] += 1
    state['prefix_sha256'] = _next_digest(state['prefix_sha256'], bar)


def _result(state, bar):
    swings = state['swings']
    lows = [s for s in swings if s['kind'] == 'L']
    highs = [s for s in swings if s['kind'] == 'H']
    def point(values, offset):
        if len(values) < -offset:
            return {'event_date': None, 'confirmed_at': None, 'price': None}
        selected = values[offset]
        return {key: selected[key] for key in ('event_date', 'confirmed_at', 'price')}
    known = max(s['confirmed_at'] for s in swings) if len(swings) == 4 else None
    if not bar['valid']:
        trend, reason = None, 'INVALID_INPUT'
    elif len(swings) < 4:
        trend, reason = None, state['disruption'] or 'INSUFFICIENT_CONFIRMED_SWINGS'
    elif bar['close'] < lows[-1]['price']:
        trend, reason = False, 'BROKEN_BY_CLOSE'
    else:
        trend = lows[-1]['price'] > lows[-2]['price'] and highs[-1]['price'] > highs[-2]['price']
        reason = None if trend else 'STRUCTURE_NOT_RISING'
    status = 'TREND_UP' if trend is True else reason
    identity = state['identity']
    sidecar = {'L1': point(lows, -2), 'H1': point(highs, -2),
               'L2': point(lows, -1), 'H2': point(highs, -1),
               'structure_known_at': known, 'first_breakout_at': None,
               'state': status, 'rule_id': RULE_ID, **identity,
               'calendar_status': 'BOUND' if identity['calendar_sha256'] else 'CANNOT_CONFIRM',
               'price_basis_status': 'BOUND' if identity['price_basis_sha256'] else 'CANNOT_CONFIRM',
               'prefix_input_sha256': state['prefix_sha256'],
               'required_bars': 11, 'available_bars': min(state['consecutive_valid_bars'], 11),
               'history_bar_count': state['history_bar_count'], 'confirmed_swings': len(swings)}
    return {'ts_code': state['symbol'], 'trade_date': bar['trade_date'],
            'kb_hold_trend_up': trend, 'kb_hold_trend_up_reason': reason,
            'kb_n_structure': sidecar}


def project_n_history(code, rows, *, identity, checkpoint=None, expected_prefix_sha256=None):
    """Project ordered bars causally; return date-bound rows and a JSON checkpoint.

    On resume the owner must independently validate the prefix digest against
    the current bound inputs, then pass it as ``expected_prefix_sha256``.
    Revisions start from a verified checkpoint strictly before the changed bar.
    Neither a missing bar nor an omitted date is interpreted as a suspension.
    """
    bound = _identity(code, identity)
    if checkpoint is None:
        if expected_prefix_sha256 is not None:
            raise ValueError('N_STRUCTURE_PREFIX_WITHOUT_CHECKPOINT')
        state = _new_state(code, bound)
    else:
        state = _resume(code, bound, checkpoint, expected_prefix_sha256)
    output = []
    for source in rows:
        bar = _bar(code, source)
        if state['last_trade_date'] is not None and bar['trade_date'] <= state['last_trade_date']:
            raise ValueError('N_STRUCTURE_DATES_NOT_UNIQUE_SORTED')
        _observe(state, bar)
        output.append(_result(state, bar))
    return output, _seal(state)
