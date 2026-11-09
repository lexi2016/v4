"""Projection of the daily panel's own reference K; never an R3 trigger producer."""
from __future__ import annotations

from datetime import datetime
import math
import re

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'v4.p5162.panel_reference_event_position.v1'
R3_FIELDS = ('observed_trigger_age_sessions', 'trigger_high_to_close_pct', 'vol_ratio_anchor')


def date(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{8}', str(value)):
        raise ValueError('INVALID_DATE')
    datetime.strptime(str(value), '%Y%m%d')
    return int(value)


def number(value, *, positive=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) and (not positive or out > 0) else None


def empty_r3():
    # A panel key and preK segment are not the original R3 tracker event.
    return dict(namespace='P5162_R3_ORIGINAL_TRIGGER', status='CANNOT_CONFIRM',
        reason='SEMANTIC_MAPPING_NOT_CERTIFIED',
        missing=['ORIGINAL_12_2_TRACKER_CHECKPOINT_AND_PRESTEP', 'INDEPENDENT_TRIGGER_ID_ROLE_AND_BRANCH',
                 'RAW_QFQ_BOTH_DATES_AND_CROSS_DAY_SCALE', 'VOLUME_UNIT_AND_SOURCE_EVIDENCE',
                 'ORIGINAL_R3_EXCHANGE_CALENDAR_BINDING'],
        fields={k: None for k in R3_FIELDS}, event_id=None)


def _projection_base(symbol, target, row_ref):
    return dict(schema=SCHEMA, symbol=symbol, data_date=str(target), source_row=row_ref,
        groups=None, pending_groups=None, reasons=None, risk_clear=None, risk=None,
        primary_path_redgreen=None, all_new_key_dates=None, prior10_dates=None,
        anchor_paths=[], panel_reference=dict(event_id=None, anchor_date=None,
        fields={'reference_age_sessions':None, 'reference_high_to_close_pct':None,
                'reference_volume_ratio':None}, reasons=[]),
        r3_model=empty_r3(), event_family_status='UNKNOWN_NOT_BOUND',
        event_end_status='RULE_NOT_BOUND', historical_PIT=False, **FLAGS)


def isolated(symbol, target, row_ref, reason):
    out = _projection_base(symbol, target, row_ref)
    out['status'] = 'SOURCE_ISOLATED'
    out['panel_reference']['reasons'] = [str(reason)]
    return out


def project(symbol, target, generation, row, row_ref, current_bar, calendar, basis):
    """One saved evaluation and its same-generation target bar, no formula runs.

    An isolated or unqualified source never borrows another stock or date.
    Each component remains nullable independently when a prerequisite is absent.
    """
    target = date(target)
    out = _projection_base(symbol, target, row_ref)
    if not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', symbol):
        raise ValueError('SYMBOL_INVALID')
    if row.get('symbol') != symbol or str(row.get('data_date')) != str(target):
        raise ValueError('SOURCE_ROW_SYMBOL_OR_DATE_CONFLICT')
    ev = row.get('evaluation')
    if not isinstance(ev, dict) or ev.get('symbol') != symbol or date(ev.get('asof')) != target:
        raise ValueError('EVALUATION_SYMBOL_OR_DATE_CONFLICT')
    out.update(groups=row.get('groups'), pending_groups=row.get('pending_groups'),
               reasons=row.get('reasons'), risk_clear=row.get('risk_clear'), risk=ev.get('risk'),
               primary_path_redgreen=ev.get('primary_path_redgreen'),
               all_new_key_dates=ev.get('all_new_key_dates'), prior10_dates=ev.get('prior10_dates'))
    qual = row.get('qualification') or {}
    if qual.get('status') != 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
        out['status'] = 'UNKNOWN_SOURCE_QUALIFICATION'
        out['panel_reference']['reasons'] = ['SOURCE_QUALIFICATION:' + str(qual.get('reason') or 'UNKNOWN')]
        return out
    if (qual.get('symbol') != symbol or str(qual.get('target_date')) != str(target)
            or qual.get('source_generation') != generation):
        raise ValueError('QUALIFICATION_IDENTITY_CONFLICT')
    if (not isinstance(basis, dict) or basis.get('price_basis') != 'QFQ_ASOF'
            or basis.get('volume_basis') != 'QFQ_EVENT_VOLUME' or str(basis.get('asof_date')) != str(target)):
        raise ValueError('PRICE_OR_VOLUME_BASIS_CONFLICT')
    paths = ev.get('filter_anchor_paths')
    if not isinstance(paths, list):
        out['status'] = 'UNKNOWN_NO_REFERENCE_PATHS'
        out['panel_reference']['reasons'] = ['REFERENCE_PATHS_MISSING']
        return out
    latest = ev.get('latest_prior_new_key_date')
    latest = date(latest) if latest is not None else None
    if latest is not None and latest >= target:
        raise ValueError('FUTURE_OR_SAME_DAY_ANCHOR')
    actual_dates = ev.get('all_new_key_dates')
    if not isinstance(actual_dates, list):
        raise ValueError('ALL_NEW_KEY_DATES_MISSING')
    known_dates = [date(d) for d in actual_dates]
    if any(d > target for d in known_dates):
        raise ValueError('FUTURE_KEY_IN_SOURCE')
    if latest is not None and (latest not in known_dates or latest != max((d for d in known_dates if d < target), default=None)):
        raise ValueError('LATEST_ANCHOR_INCONSISTENT')
    seen = set()
    primary = None
    for path in paths:
        if not isinstance(path, dict):
            raise ValueError('REFERENCE_PATH_INVALID')
        d = date(path.get('anchor_date'))
        key = path.get('key') or {}; bar = path.get('ohlcv') or {}; pre = path.get('preK') or {}
        role = path.get('role')
        if (d >= target or d in seen or d not in known_dates or date(key.get('date')) != d
                or date(bar.get('date')) != d or key.get('candidate') != 'TRUE'):
            raise ValueError('ANCHOR_IDENTITY_OR_DATE_CONFLICT')
        if role not in ('LATEST_PRIOR_NEW_KEY','EARLIER_REFERENCE_RETAINED_NOT_SELECTED'):
            raise ValueError('ANCHOR_ROLE_UNKNOWN')
        if (role == 'LATEST_PRIOR_NEW_KEY') != (d == latest):
            raise ValueError('ANCHOR_ROLE_CONFLICT')
        seen.add(d)
        item = dict(event_id=f'PANEL_REFERENCE_K:{symbol}:{d}', anchor_date=d, role=role,
                    key=key, ohlcv=bar, same_anchor_support=path.get('same_anchor_support'),
                    preK=dict(status=pre.get('status'), reason=pre.get('reason'), selected=pre.get('selected'),
                              unknown_lengths=pre.get('unknown_lengths'),
                              identity='ORIGINAL_PANEL_PREK_SEGMENT_NOT_R3_JCB'))
        out['anchor_paths'].append(item)
        if d == latest:
            primary = item
    if latest is None or primary is None:
        out['status'] = 'UNKNOWN_NO_LATEST_REFERENCE'
        out['panel_reference']['reasons'] = ['LATEST_REFERENCE_NOT_AVAILABLE']
        return out
    ref = out['panel_reference']; ref.update(event_id=primary['event_id'],anchor_date=latest)
    fields = ref['fields']; reasons = ref['reasons']
    if not isinstance(calendar, (list, tuple)):
        reasons.append('EXCHANGE_CALENDAR_MISSING')
    else:
        dates = [date(d) for d in calendar]
        if dates != sorted(set(dates)):
            raise ValueError('EXCHANGE_CALENDAR_INVALID')
        lookup = {d:i for i,d in enumerate(dates)}
        if latest in lookup and target in lookup and lookup[target] > lookup[latest]:
            fields['reference_age_sessions'] = lookup[target] - lookup[latest]
        else:
            reasons.append('ANCHOR_OR_TARGET_NOT_IN_EXCHANGE_CALENDAR')
    day = current_bar if isinstance(current_bar, dict) else {}
    if day and (day.get('ts_code') != symbol or str(day.get('trade_date')) != str(target)
                or day.get('exchange') != symbol[-2:]):
        raise ValueError('TARGET_BAR_IDENTITY_CONFLICT')
    close = number(day.get('close'), positive=True); volume = number(day.get('volume'), positive=True)
    high = number(primary['ohlcv'].get('h'), positive=True); anchor_vol = number(primary['ohlcv'].get('v'), positive=True)
    support = primary.get('same_anchor_support') or {}
    saved_close = number(support.get('D_close'), positive=True)
    if close is not None and saved_close is not None and not math.isclose(close, saved_close, rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError('TARGET_CLOSE_SOURCE_CONFLICT')
    if high is None or close is None:
        reasons.append('REFERENCE_HIGH_OR_TARGET_CLOSE_MISSING')
    else:
        fields['reference_high_to_close_pct'] = (high-close)/high*100.0
    if anchor_vol is None or volume is None:
        reasons.append('REFERENCE_OR_TARGET_VOLUME_MISSING')
    else:
        fields['reference_volume_ratio'] = volume/anchor_vol
    out['current_bar'] = {k:day.get(k) for k in ('ts_code','trade_date','exchange','close','volume')} if day else None
    out['status'] = 'REFERENCE_AVAILABLE' if not reasons else 'REFERENCE_PARTIAL'
    return out


def read_model_fields(record, *, symbol, data_date, generation):
    """Reject unbound R3 inputs rather than returning NaNs to a model caller.

    No present adapter certifies equivalence to the original 12.2 producer;
    a future original-authority integration must change this admission contract.
    """
    if (record.get('schema') != SCHEMA or record.get('symbol') != symbol
            or record.get('data_date') != str(data_date)
            or record.get('source_generation') != generation):
        raise ValueError('MODEL_READER_IDENTITY_CONFLICT')
    model = record.get('r3_model') or {}
    if model.get('namespace') != 'P5162_R3_ORIGINAL_TRIGGER':
        raise ValueError('MODEL_NAMESPACE_CONFLICT')
    raise ValueError('R3_MODEL_INPUT_NOT_ADMITTED:' + str(model.get('reason') or 'CONTRACT_NOT_BOUND'))
