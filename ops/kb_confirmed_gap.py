"""Confirmed KB gap components on an already admitted, ordered QFQ prefix.

Only the selected dates are evaluated. Existing 57 labels and prices are
inputs, not recomputed here. The caller owns source admission and checkpoints.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ops import kb_signal_authority as kb
from ops.kb_panel_rebuild_brick import BRICK_SERIES_ID, brick_fields_at, rebuild_at
from ops.kb_panel_signal_components import (RULE_ID, bowl_components, double_gun_components,
                                            violence_k_components, yidong_above_60d_at)

CONTRACT = Path(__file__).resolve().parents[1] / 'contracts/a_share_kb_confirmed_gap_v1.json'
SPEC = json.loads(CONTRACT.read_text())
FIELD_TYPES = dict(SPEC['new_fields'])
FIELDS = frozenset(FIELD_TYPES)
DIAGNOSTICS = tuple(SPEC['diagnostic_keys'])
INPUTS = ('ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'pre_close', 'pct_chg',
          'kb_double_gun', 'kb_violence_k', 'kb_yidong_vol_ratio_5')


def rule_sha256():
    return hashlib.sha256(CONTRACT.read_bytes()).hexdigest()


def _num(value):
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _tri(value):
    if hasattr(value, 'item'):
        value = value.item()
    return value if isinstance(value, bool) else None


def prefix_hashes(frame):
    """Bind every output to all source values of its same-security prefix."""
    if set(INPUTS) - set(frame.columns):
        raise ValueError('CONFIRMED_GAP_PREFIX_INPUT_MISSING')
    running = hashlib.sha256()
    values = []
    for row in frame[list(INPUTS)].to_dict('records'):
        record = [str(row['ts_code']), str(row['trade_date'])]
        record.extend(_num(row[k]) for k in ('open','high','low','close','vol','pre_close','pct_chg','kb_yidong_vol_ratio_5'))
        record.extend(_tri(row[k]) for k in ('kb_double_gun','kb_violence_k'))
        running.update(json.dumps(record, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n')
        values.append(running.copy().hexdigest())
    return values


def project_with_reuse(frame, *, prior=None, calendar_sha256=None):
    """Reuse only prevalidated rows with the same calendar, rule and input prefix.

    ``prior`` is supplied by the existing owner after checking the saved panel
    and sidecar file SHA. A missing calendar explicitly disables cross-run
    reuse; the resulting affected-stock projection remains separately marked.
    """
    hashes = prefix_hashes(frame)
    reused = {}
    if prior is not None:
        meta = prior['metadata']
        previous = prior['frame']
        sidecar = prior['sidecar']
        if (not isinstance(calendar_sha256, str) or len(calendar_sha256) != 64
                or any(ch not in '0123456789abcdef' for ch in calendar_sha256)
                or meta.get('calendar_sha256') != calendar_sha256
                or meta.get('confirmed_gap_contract_sha256') != rule_sha256()
                or meta.get('price_basis') != 'QFQ_ASOF'
                or meta.get('volume_basis') != 'QFQ_EVENT_VOLUME'
                or meta.get('helper_sha256') != helper_sha256s()
                or meta.get('symbol') != str(frame.ts_code.iloc[0])):
            raise ValueError('CONFIRMED_GAP_REUSE_IDENTITY_CONFLICT')
        if set(FIELDS | {'kb_rebuild'}) - set(previous.columns):
            raise ValueError('CONFIRMED_GAP_REUSE_FIELDS_MISSING')
        old_hashes = prefix_hashes(previous)
        if len(sidecar) != len(previous) or len(sidecar) != len(old_hashes):
            raise ValueError('CONFIRMED_GAP_REUSE_LENGTH_CONFLICT')
        old_by_date = {}
        for i, (row, digest) in enumerate(zip(sidecar, old_hashes)):
            key = str(row.get('trade_date'))
            if (row.get('ts_code') != meta['symbol'] or key != str(previous.trade_date.iloc[i])
                    or row.get('prefix_input_sha256') != digest or key in old_by_date):
                raise ValueError('CONFIRMED_GAP_REUSE_PREFIX_CONFLICT')
            diag = json.loads(row['diagnostics_json'])
            if set(diag) != set(DIAGNOSTICS):
                raise ValueError('CONFIRMED_GAP_REUSE_DIAGNOSTICS_CONFLICT')
            old_by_date[key] = (i, digest, diag)
        for i, row in enumerate(frame.to_dict('records')):
            old = old_by_date.get(str(row['trade_date']))
            if old is not None and old[1] == hashes[i]:
                old_row = previous.iloc[old[0]]
                values = {name:old_row[name] for name in FIELDS | {'kb_rebuild'}}
                for name, value in values.items():
                    if hasattr(value, 'item'):
                        value = value.item()
                    if isinstance(value, float) and not math.isfinite(value):
                        value = None
                    values[name] = value
                reused[i] = values, old[2]
    needed = [i for i in range(len(frame)) if i not in reused]
    computed = project_selected(frame, needed)
    return {**reused, **computed}, hashes, {'reused_rows':len(reused), 'computed_rows':len(computed),
        'calendar_status':'BOUND' if calendar_sha256 else 'CANNOT_CONFIRM'}


def helper_sha256s():
    root = Path(__file__).resolve().parent
    paths = ('kb_confirmed_gap.py', 'kb_panel_rebuild_brick.py', 'kb_panel_signal_components.py', 'kb_signal_authority.py')
    result = {name:hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    for name in ('a_share_kb_rebuild_brick_v1.json', 'a_share_kb_signal_components_v1.json'):
        result['contracts/' + name] = hashlib.sha256((root.parent / 'contracts' / name).read_bytes()).hexdigest()
    return result


def project_selected(frame, indices, *, allow_existing_input_conflict=False):
    """Return {row index: (nine values, 24 diagnostics)} without future data."""
    missing = set(INPUTS) - set(frame.columns)
    if missing:
        raise ValueError('CONFIRMED_GAP_INPUT_MISSING:' + ','.join(sorted(missing)))
    rows = frame[list(INPUTS)].to_dict('records')
    indices = list(indices)
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(rows) for i in indices) or indices != sorted(set(indices)):
        raise ValueError('CONFIRMED_GAP_INDICES_INVALID')
    if not rows:
        return {}
    code = str(rows[0]['ts_code'])
    dates = [str(row['trade_date']) for row in rows]
    if (any(str(row['ts_code']) != code for row in rows) or len(code) != 9
            or not code[:6].isdigit() or code[6:] not in {'.SH', '.SZ', '.BJ'}
            or any(len(date) != 8 or not date.isdigit() for date in dates)
            or dates != sorted(set(dates))):
        raise ValueError('CONFIRMED_GAP_SYMBOL_OR_DATE_CONFLICT')
    bars, flags, closes, volumes, pcts = [], [], [], [], []
    for i, row in enumerate(rows):
        op, hi, lo, close, vol, prev, pct = (_num(row[k]) for k in ('open', 'high', 'low', 'close', 'vol', 'pre_close', 'pct_chg'))
        valid_close = close is not None and close > 0
        valid_hlc = valid_close and hi is not None and lo is not None and 0 < lo <= close <= hi
        valid_ohlc = valid_hlc and op is not None and lo <= op <= hi
        valid_vol = vol is not None and vol > 0
        valid_pct = valid_close and prev is not None and prev > 0 and pct is not None
        if valid_pct:
            # Validate the bound previous close and the source's two-decimal
            # percentage convention before using it as a source input.
            valid_pct = abs((close / prev - 1) * 100 - pct) <= 0.02
            if i and closes[-1] is not None:
                valid_pct = valid_pct and abs(prev - closes[-1]) <= max(1e-6, abs(closes[-1]) * 1e-5)
        flags.append((valid_close, valid_hlc, valid_ohlc, valid_vol, valid_pct))
        closes.append(close if valid_close else None)
        volumes.append(vol if valid_vol else None)
        pcts.append(pct if valid_pct else None)
        values = [op, hi, lo, close, vol, prev, pct]
        clean = [value if value is not None else 0.0 for value in values]
        bars.append(kb.DailyData(code, dates[i], clean[0], clean[1], clean[2], clean[3], clean[4], 0.0, clean[6], clean[5]))
    bad = [[0] for _ in range(5)]
    for flags_row in flags:
        for j in range(5):
            bad[j].append(bad[j][-1] + (not flags_row[j]))
    def ok(kind, start, end):
        return start >= 0 and bad[kind][start] == bad[kind][end]
    cache = kb._cache(bars)
    output = {}
    for i in indices:
        n = i + 1
        prefix = kb._Prefix(bars, cache, 0, n)
        hlc_prefix, close_prefix = ok(1, 0, n), ok(0, 0, n)
        rebuild = rebuild_at(closes, volumes, pcts, index=i)
        brick = brick_fields_at(cache['brick'], index=i, prefix_valid=hlc_prefix,
                                prefix_seed_bound=True, series_id=BRICK_SERIES_ID)
        anomaly = yidong_above_60d_at(closes, index=i,
            vol_ratio_5=_num(rows[i]['kb_yidong_vol_ratio_5']), pct_chg=pcts[i])
        gun_signal = _tri(rows[i]['kb_double_gun'])
        gun_valid = n >= 24 and hlc_prefix and ok(2, n-24, n) and ok(3, n-24, n) and ok(4, n-23, n)
        gun_source = kb.detect_double_gun(prefix) if gun_valid and gun_signal is True else None
        gun_source_conflict = gun_source is not None and gun_source.get('is_double_gun') is not True
        if gun_source_conflict and not allow_existing_input_conflict:
            raise ValueError('CONFIRMED_GAP_DOUBLE_GUN_SOURCE_CONFLICT:' + dates[i])
        gun = double_gun_components(gun_source, signal=gun_signal, available_bars=n, input_valid=gun_valid)
        if gun_source_conflict:gun['kb_double_gun_components_status']='EXISTING_SIGNAL_COMPONENT_SOURCE_CONFLICT'
        bowl = bowl_components(cache['white'][i], cache['yellow'][i], available_bars=n, close_prefix_valid=close_prefix)
        violence_signal = _tri(rows[i]['kb_violence_k'])
        violence_valid = n >= 21 and ok(2, n-21, n) and ok(3, n-6, n) and ok(4, n-6, n)
        violence_source = kb.detect_violence_k(prefix) if violence_valid and violence_signal is True else None
        violence = violence_k_components(violence_source, signal=violence_signal, available_bars=n, input_valid=violence_valid)
        gun_conflict = gun_signal is not None and not gun_valid
        violence_conflict = violence_signal is not None and not violence_valid
        if gun_conflict or violence_conflict:
            if not allow_existing_input_conflict:
                raise ValueError('CONFIRMED_GAP_EXISTING_SIGNAL_INPUT_CONFLICT:' + dates[i])
            if gun_conflict:gun['kb_double_gun_components_status']='EXISTING_SIGNAL_INPUT_CONFLICT'
            if violence_conflict:violence['kb_violence_k_components_status']='EXISTING_SIGNAL_INPUT_CONFLICT'
        combined = {**rebuild, **brick, **anomaly, **gun, **bowl, **violence,
                    'kb_signal_components_rule_id':RULE_ID}
        values = {name:combined[name] for name in FIELD_TYPES}
        values['kb_rebuild'] = combined['kb_rebuild']
        diag = {name:combined[name] for name in DIAGNOSTICS}
        output[i] = values, diag
    return output
