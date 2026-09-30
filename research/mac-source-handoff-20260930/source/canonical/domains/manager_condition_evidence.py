"""Read-only condition-input diagnostics on the EXISTING 15:30 owner archives.

This is the evidence-insufficient branch of R2, not a new authority/producer.
It never fetches, publishes, imports a reference panel, approves a numeric rule,
or returns a true/false volume/position predicate. A prior snapshot contributes
only after the native universe/snapshot readers validate its actual bytes.

The 20 prior full HK_CONNECT sessions are a labelled DIAGNOSTIC window, not an
approved trading rule or minimum sample requirement. Price samples here are
same-clock last trades, NOT daily OHLC highs/lows, oversold or breakout signals.
Explicit comparison metadata is required; nothing is inferred from code names,
provider volume_ratio, D-1 model scores, mtime, or BREAKOUT strings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from domains.manager_research_evidence import (
    BRIDGE_OWNER, BRIDGE_REL, SNAPSHOT_SCHEMA, EvidenceError, VerifiedSnapshot, VerifiedUniverse,
    admitted, FLAGS, RECEIPT_SCHEMA,
    read_snapshot_evidence, read_universe_evidence,
)
from infrastructure.manager_input_attestation import PublicationError, aware, digest, encoded, resolve

HK = ZoneInfo('Asia/Hong_Kong')
CONTRACT_VERSION = 'manager-condition-input-audit-r2-v1'
DIAGNOSTIC_WINDOW_SESSIONS = 20
_SEAL = object()
_BASE_FIELDS = ('security_id', 'session_definition', 'trading_status')
_VOLUME_FIELDS = ('volume_unit', 'volume_measure', 'volume_adjustment', 'share_basis_id')
_PRICE_FIELDS = ('price_currency', 'price_unit', 'price_adjustment', 'price_adjustment_basis_id')
_APP_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ConditionAudit:
    """Immutable, content-bound diagnostic; deliberately not a condition approval."""
    snapshot_sha256: str
    universe_sha256: str
    as_of: str
    content: bytes
    _seal: object = field(default=None, repr=False, compare=False)
    _content_sha256: str | None = field(default=None, repr=False, compare=False)


def _number(value: Any) -> float | None:
    # Source quote JSON may legitimately carry numeric strings, never booleans.
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _quote_time(row: Mapping[str, Any], date: str, available: datetime) -> datetime | None:
    value = row.get('update_time')
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    # Exactly the existing Futu bridge's HK update_time convention. Availability
    # and other timestamps never use this conversion or a file-mtime fallback.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HK)
    dt = dt.astimezone(HK)
    if dt.strftime('%Y%m%d') != date or dt > available or not time(15, 30) <= dt.time() < time(15, 32):
        return None
    return dt


def _row_gaps(row: Mapping[str, Any], *, kind: str, date: str, available: datetime) -> list[str]:
    fields = _BASE_FIELDS + (_VOLUME_FIELDS if kind == 'volume' else _PRICE_FIELDS)
    gaps = ['MISSING_' + k.upper() for k in fields if _text(row.get(k)) is None]
    if row.get('market') is not None and row.get('market') not in ('HK', 'HK_CONNECT', 'HKEX'):
        gaps.append('CONFLICTING_EXPLICIT_MARKET')
    required = {'session_definition': 'HKEX_FULL_DAY_REGULAR_V1', 'trading_status': 'NORMAL'}
    if kind == 'volume':
        required.update(volume_unit='SHARES', volume_measure='CUMULATIVE_REGULAR_SESSION', volume_adjustment='NONE')
        value = _number(row.get('volume'))
        if value is None or value < 0:
            gaps.append('INVALID_VOLUME')
    else:
        required.update(price_currency='HKD', price_unit='HKD_PER_SHARE', price_adjustment='NONE')
        value = _number(row.get('last_price'))
        if value is None or value <= 0:
            gaps.append('INVALID_PRICE')
        if row.get('currency') is not None and row.get('currency') != row.get('price_currency'):
            gaps.append('CONFLICTING_PRICE_CURRENCY')
    gaps.extend('UNSUPPORTED_' + k.upper() for k, v in required.items() if row.get(k) != v)
    if _quote_time(row, date, available) is None:
        gaps.append('QUOTE_OUTSIDE_EXACT_SLOT_OR_AFTER_AVAILABILITY')
    return sorted(set(gaps))


def _prior_dates(app_root: Path, date: str) -> tuple[list[str], str, list[str]]:
    from contracts.trading_calendar import (
        CALENDAR_PATH, TradingDayState, load_market_calendar, previous_session, resolve_market_states,
    )
    # Bind the native frozen calendar bytes, not a reconstructed weekday list.
    path = Path(CALENDAR_PATH)
    path.relative_to(app_root)  # Never silently consume another application's calendar.
    before = path.read_bytes()
    calendar = load_market_calendar()
    if path.read_bytes() != before:
        raise EvidenceError('CONDITION_CALENDAR_CHANGED_DURING_READ')
    if resolve_market_states(calendar, date)['hk_connect'] != TradingDayState.FULL_TRADING_DAY:
        raise EvidenceError('CONDITION_CURRENT_FULL_SESSION_UNVERIFIED')
    dates: list[str] = []
    gaps: list[str] = []
    cursor = date
    # The native previous_session function is bounded by its frozen contract
    # year. No older panel/latest pointer or weekday fallback is permitted.
    while len(dates) < DIAGNOSTIC_WINDOW_SESSIONS:
        try:
            cursor = previous_session(calendar, cursor, market='hk_connect')
        except ValueError:
            gaps.append('CONDITION_CALENDAR_WINDOW_INCOMPLETE')
            break
        if resolve_market_states(calendar, cursor)['hk_connect'] == TradingDayState.FULL_TRADING_DAY:
            dates.append(cursor)
    return sorted(dates), digest(before), gaps


def _snapshot_binding(root: Path, snap: VerifiedSnapshot) -> dict[str, Any]:
    source = snap.source
    path = resolve(root, source['artifact_ref'])
    raw = path.read_bytes()
    if digest(raw) != source['sha256']:
        raise EvidenceError('CONDITION_SNAPSHOT_CHANGED_AFTER_ADMISSION')
    # The native reader has already reconstructed/validated the receipt. Bind
    # its bytes to this diagnostic as well; check the receipt against this raw
    # snapshot again to prevent a replacement between the two reads.
    receipt_ref = source['receipt_ref']
    receipt_bytes = resolve(root, receipt_ref).read_bytes()
    value = json.loads(raw)
    expected = {'schema_version': RECEIPT_SCHEMA, 'market': 'HK_CONNECT',
                'trade_date': source['source_date'], 'slot': '1530',
                'artifact_ref': source['artifact_ref'], 'artifact_sha256': source['sha256'],
                'bridge': value['bridge'], 'row_count': len(snap.rows),
                'universe_sha256': snap.universe_sha256, 'available_at': source['available_at'],
                'run_id': source['run_id'], **FLAGS}
    if encoded(json.loads(receipt_bytes)) != encoded(expected):
        raise EvidenceError('CONDITION_RECEIPT_CHANGED_AFTER_ADMISSION')
    return {'artifact_ref': source['artifact_ref'], 'artifact_sha256': source['sha256'],
            'receipt_ref': receipt_ref, 'receipt_sha256': digest(receipt_bytes),
            'run_id': source['run_id'], 'available_at': source['available_at'],
            'owner': source['owner'], 'source_date': source['source_date'],
            'bridge': value['bridge'], 'universe_sha256': snap.universe_sha256}


def _published_snapshot(root: Path, binding: Mapping[str, Any], *, expected_date: str,
                        as_of: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-read one existing native snapshot and its immutable receipt.

    The API consumer receives only a diagnostic projection.  When it is asked
    to consume the new projection, bind every reference back to the existing
    15:30 owner bytes and the bridge identity already used by the native
    reader.  This is deliberately a read-only check; it does not discover a
    replacement source or recompute a receipt.
    """
    try:
        artifact_ref = binding['artifact_ref']
        receipt_ref = binding['receipt_ref']
        expected_ref = f'workbench_research/{expected_date}/inputs/1530_futu_snapshot.json'
        if artifact_ref != expected_ref or receipt_ref != artifact_ref + '.receipt.json':
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_REF_INVALID')
        artifact_path = resolve(root, artifact_ref)
        receipt_path = resolve(root, receipt_ref)
        raw = artifact_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
        artifact_sha = digest(raw)
        receipt_sha = digest(receipt_raw)
        if artifact_sha != binding['artifact_sha256'] or receipt_sha != binding['receipt_sha256']:
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_SHA_MISMATCH')
        artifact = json.loads(raw)
        receipt = json.loads(receipt_raw)
        if encoded(artifact) != raw or not isinstance(artifact, dict) or not isinstance(receipt, dict):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_NONCANONICAL')
        if (artifact.get('schema_version') != SNAPSHOT_SCHEMA
            or artifact.get('market') != 'HK_CONNECT' or artifact.get('trade_date') != expected_date
            or artifact.get('slot') != '1530' or artifact.get('normalization') != 'NONFINITE_TO_NULL_V1'):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_IDENTITY_INVALID')
        if any(artifact.get(key) is not expected for key, expected in FLAGS.items()):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_SAFETY_INVALID')
        if (artifact.get('bridge') != {
                'owner': BRIDGE_OWNER,
                'code_ref': BRIDGE_REL,
                'code_sha256': digest(resolve(_APP_ROOT, BRIDGE_REL).read_bytes()),
            }):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_BRIDGE_INVALID')
        rows = artifact.get('rows')
        errors = artifact.get('errors')
        if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or not isinstance(errors, list) or not all(isinstance(error, str) for error in errors)):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_ROWS_INVALID')
        bridge_return = artifact.get('bridge_return_json')
        if (not isinstance(bridge_return, str)
            or digest(bridge_return.encode()) != artifact.get('bridge_return_sha256')):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_BRIDGE_RETURN_INVALID')
        normalized = json.loads(bridge_return, parse_constant=lambda _value: None)
        if not isinstance(normalized, dict):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_BRIDGE_RETURN_INVALID')
        if (artifact.get('rows') != normalized.get('rows')
            or artifact.get('errors') != [str(item)[:160] for item in normalized.get('errors', [])]):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_NORMALIZATION_INVALID')
        available = aware(artifact['available_at'])
        started = aware(artifact['started_at'])
        if (started.strftime('%Y%m%d') != expected_date
            or available.strftime('%Y%m%d') != expected_date
            or not time(15, 30) <= started.time() < time(15, 32)
            or started > available or available.time() >= time(15, 32)
            or available > as_of):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_TIME_INVALID')
        if (aware(binding['available_at']) != available
            or artifact.get('universe_sha256') != binding['universe_sha256']
            or artifact.get('bridge') != binding['bridge']):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_BINDING_INVALID')
        prior_universe = artifact.get('universe_source')
        if not isinstance(prior_universe, dict) or prior_universe.get('sha256') != artifact.get('universe_sha256'):
            raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_UNIVERSE_INVALID')
        expected_receipt = {
            'schema_version': RECEIPT_SCHEMA,
            'market': 'HK_CONNECT',
            'trade_date': expected_date,
            'slot': '1530',
            'artifact_ref': artifact_ref,
            'artifact_sha256': artifact_sha,
            'bridge': artifact['bridge'],
            'row_count': len(rows),
            'universe_sha256': artifact['universe_sha256'],
            'available_at': artifact['available_at'],
            'run_id': 'mcs-' + artifact_sha[:24],
            **FLAGS,
        }
        if encoded(receipt) != encoded(expected_receipt) or binding['run_id'] != receipt['run_id']:
            raise EvidenceError('CONDITION_PROJECTION_RECEIPT_INVALID')
        return artifact, receipt
    except EvidenceError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise EvidenceError('CONDITION_PROJECTION_ARCHIVE_UNREADABLE') from exc


def _published_row(snapshot: Mapping[str, Any], *, symbol: str, date: str,
                   kind: str) -> tuple[Mapping[str, Any], datetime]:
    rows = [row for row in snapshot['rows'] if row.get('code') == symbol]
    if len(rows) != 1:
        raise EvidenceError('CONDITION_PROJECTION_QUOTE_IDENTITY_INVALID')
    available = aware(snapshot['available_at'])
    observed = _quote_time(rows[0], date, available)
    if observed is None:
        raise EvidenceError('CONDITION_PROJECTION_QUOTE_TIME_INVALID')
    return rows[0], observed


def _same_number(left: Any, right: Any) -> bool:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return left_value is right_value
    return math.isclose(left_value, right_value, rel_tol=1e-12, abs_tol=1e-12)


def _validate_published_projection(body: Mapping[str, Any], *, kind: str, symbol: str,
                                   as_of: datetime, state_root: Path) -> None:
    current = body['current_snapshot']
    current_snapshot, _ = _published_snapshot(
        state_root, current, expected_date=as_of.astimezone(HK).strftime('%Y%m%d'), as_of=as_of,
    )
    current_row, _ = _published_row(
        current_snapshot, symbol=symbol, date=as_of.astimezone(HK).strftime('%Y%m%d'), kind=kind,
    )
    if body['current_quote_sha256'] != digest(encoded(current_row)):
        raise EvidenceError('CONDITION_PROJECTION_CURRENT_QUOTE_MISMATCH')
    samples = body['samples']
    values: list[float] = []
    value_field = 'volume' if kind == 'volume' else 'last_price'
    for sample in samples:
        day = sample['trade_date']
        snapshot, _ = _published_snapshot(state_root, sample, expected_date=day, as_of=as_of)
        row, observed = _published_row(snapshot, symbol=symbol, date=day, kind=kind)
        if (sample['trade_date'] != sample['source_date']
            or sample['artifact_ref'] != f'workbench_research/{day}/inputs/1530_futu_snapshot.json'
            or sample['observed_at'] != observed.isoformat()
            or sample['quote_sha256'] != digest(encoded(row))
            or not _same_number(sample['value'], row.get(value_field))):
            raise EvidenceError('CONDITION_PROJECTION_SAMPLE_CONTENT_MISMATCH')
        sample_value = _number(row.get(value_field))
        if sample_value is None:
            raise EvidenceError('CONDITION_PROJECTION_QUOTE_VALUE_INVALID')
        values.append(sample_value)
    if kind == 'volume':
        mean = None
        ratio = None
        if values:
            scale = max(values)
            mean = (math.fsum(value / scale for value in values) / len(values)) * scale if scale else 0.0
            current_value = _number(current_row.get(value_field))
            if current_value is None:
                raise EvidenceError('CONDITION_PROJECTION_CURRENT_VALUE_INVALID')
            if mean > 0:
                ratio = current_value / mean
        if not _same_number(body.get('diagnostic_baseline_mean'), mean):
            raise EvidenceError('CONDITION_PROJECTION_VOLUME_SUMMARY_MISMATCH')
        if not _same_number(body.get('diagnostic_ratio'), ratio):
            raise EvidenceError('CONDITION_PROJECTION_VOLUME_RATIO_MISMATCH')
    else:
        low = min(values) if values else None
        high = max(values) if values else None
        relative = None
        current_value = _number(current_row.get(value_field))
        if values and current_value is None:
            raise EvidenceError('CONDITION_PROJECTION_CURRENT_VALUE_INVALID')
        if high is not None and current_value is not None:
            relative = (current_value / high - 1) * 100
        if (not _same_number(body.get('sampled_low'), low)
            or not _same_number(body.get('sampled_high'), high)
            or not _same_number(body.get('relative_to_sampled_high_pct'), relative)):
            raise EvidenceError('CONDITION_PROJECTION_PRICE_SUMMARY_MISMATCH')



def _compare(current: Mapping[str, Any], *, kind: str, date: str, as_of: datetime,
             archives: Sequence[tuple[str, VerifiedSnapshot, Mapping[str, Any], set[str]]]) -> dict[str, Any]:
    current_gaps = _row_gaps(current, kind=kind, date=date, available=as_of)
    current_time = _quote_time(current, date, as_of)
    fields = _BASE_FIELDS + (_VOLUME_FIELDS if kind == 'volume' else _PRICE_FIELDS)
    samples: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    symbol = current['code']
    for prior_date, snap, binding, eligible in archives:
        candidates = [r for r in snap.rows if r.get('code') == symbol]
        gaps: list[str] = []
        if symbol not in eligible:
            gaps.append('HISTORICAL_MEMBERSHIP_UNVERIFIED')
        if len(candidates) != 1:
            gaps.append('DUPLICATE_QUOTE' if len(candidates) > 1 else 'QUOTE_MISSING')
        if current_gaps:
            gaps.append('CURRENT_COMPARISON_CONTRACT_INCOMPLETE')
        if gaps:
            excluded.append({'trade_date': prior_date, 'reasons': gaps})
            continue
        previous = candidates[0]
        available = aware(snap.source['available_at'])
        gaps.extend(_row_gaps(previous, kind=kind, date=prior_date, available=available))
        old_time = _quote_time(previous, prior_date, available)
        if current_time is None or old_time is None or old_time.time() != current_time.time():
            gaps.append('CLOCK_NOT_EXACTLY_COMPARABLE')
        gaps.extend('MISMATCH_' + key.upper() for key in fields if previous.get(key) != current.get(key))
        if gaps:
            excluded.append({'trade_date': prior_date, 'reasons': sorted(set(gaps))})
            continue
        samples.append({**binding, 'trade_date': prior_date, 'symbol': symbol,
                        'observed_at': old_time.isoformat(), 'quote_sha256': digest(encoded(previous)),
                        'value': _number(previous.get('volume' if kind == 'volume' else 'last_price'))})
    result: dict[str, Any] = {
        'state': 'DIAGNOSTIC_ONLY_RULE_UNAPPROVED', 'predicate': 'unknown',
        'sample_count_basis': 'NATIVE_ARCHIVE_AND_EXPLICIT_METADATA_CHECK_ONLY_NOT_RULE_ADMISSION',
        'valid_sample_count': len(samples), 'approved_valid_sample_count': None,
        'required_min_samples': None, 'current_gaps': current_gaps,
        'gaps': ['VOLUME_RULE_UNAPPROVED' if kind == 'volume' else 'HISTORICAL_POSITION_AUTHORITY_AND_RULE_UNBOUND'],
        'samples': samples, 'excluded_samples': excluded,
        'current_quote_sha256': digest(encoded(current)),
        'comparison_clock': current_time.isoformat() if current_time else None,
    }
    values = [s['value'] for s in samples]
    if not values:
        result['gaps'].append('NO_COMPARABLE_SAMPLES')
    if kind == 'volume':
        mean = ratio = None
        if values:
            # Scale before summing: even sum(max_float/3, ... x3) can overflow.
            scale = max(values)
            mean = (math.fsum(x / scale for x in values) / len(values)) * scale if scale else 0.0
            if mean > 0:
                raw_ratio = _number(current.get('volume')) / mean
                if math.isfinite(raw_ratio):
                    ratio = raw_ratio
                else:
                    result['gaps'].append('VOLUME_RATIO_NONFINITE')
            else:
                result['gaps'].append('ZERO_VOLUME_BASELINE')
        result.update(diagnostic_baseline_mean=mean, diagnostic_ratio=ratio,
                      volume_measure='CUMULATIVE_REGULAR_SESSION', volume_unit='SHARES')
    else:
        low = min(values) if values else None
        high = max(values) if values else None
        relative = None
        if high is not None:
            raw_relative = (_number(current.get('last_price')) / high - 1) * 100
            if math.isfinite(raw_relative):
                relative = raw_relative
            else:
                result['gaps'].append('PRICE_RELATIVE_VALUE_NONFINITE')
        result.update(sample_basis='SAME_CLOCK_LAST_TRADE_ONLY_NOT_DAILY_OHLC',
                      sampled_low=low, sampled_high=high, relative_to_sampled_high_pct=relative,
                      daily_ohlc_authority='UNBOUND', historical_position_state='UNKNOWN',
                      daily_price_window={'state': 'INPUT_UNBOUND', 'valid_sample_count': None,
                          'window_sessions': None, 'last_usable_bar_date': None,
                          'required_evidence': ['ACTUAL_DAILY_OHLC_BYTES_AND_SHA',
                              'EXISTING_OWNER_MANIFEST_AND_RECEIPT', 'BAR_AVAILABLE_AT',
                              'SECURITY_MARKET_CURRENCY_AND_UNIT', 'ADJUSTMENT_AND_FACTOR_VINTAGE',
                              'WINDOW_AND_SESSION_COMPLETENESS', 'AS_OF_CUTOFF',
                              'AUTHORIZED_OVERSOLD_OR_BREAKOUT_RULE']})
    return result


def read_condition_audit(*, state_root: Path, universe_root: Path, app_root: Path,
                         trade_date: str, as_of: datetime, universe: VerifiedUniverse,
                         snapshot: VerifiedSnapshot,
                         clock: Callable[[], datetime] = lambda: datetime.now(HK)) -> ConditionAudit:
    """Read exact prior owned archives once. No directory glob, fetch or write.

    ``clock`` is the existing native reader's availability-witness seam for
    isolated SIMULATED tests. The CLI/production owner never supplies it.
    Missing/bad historical inputs are isolated, not a failure of the live scan.
    """
    if (as_of.tzinfo is None or not admitted(universe, snapshot, snapshot.rows)
        or as_of.astimezone(HK).strftime('%Y%m%d') != trade_date
        or aware(snapshot.source['available_at']) != as_of
        or snapshot.source.get('source_date') != trade_date):
        raise EvidenceError('CONDITION_CURRENT_SNAPSHOT_UNBOUND')
    current_binding = _snapshot_binding(state_root, snapshot)
    try:
        dates, calendar_sha, window_gaps = _prior_dates(app_root, trade_date)
    except (OSError, ValueError):
        dates, calendar_sha, window_gaps = [], None, ['CONDITION_CALENDAR_UNVERIFIED']
    archives = []
    archive_gaps = []
    for day in dates:
        ref = f'workbench_research/{day}/inputs/1530_futu_snapshot.json'
        try:
            # Both native reader paths are read-only. This current witness is
            # NOT backdated: read_snapshot_evidence validates the immutable
            # original universe availability witness captured by that owner.
            old_u = read_universe_evidence(universe_root, day, clock=clock)
            old_s = read_snapshot_evidence(state_root, day, as_of=as_of, universe=old_u, app_root=app_root)
            if not admitted(old_u, old_s, old_s.rows):
                raise EvidenceError('CONDITION_HISTORICAL_SNAPSHOT_UNBOUND')
            binding = _snapshot_binding(state_root, old_s)
            archives.append((day, old_s, binding, set(old_u.codes)))
        except (OSError, ValueError, KeyError, TypeError):
            # Do not expose host paths, exception strings, or treat any
            # invalid/missing archive as a zero-volume/zero-price observation.
            archive_gaps.append({'trade_date': day, 'artifact_ref': ref,
                                 'reason': 'EXACT_OWNER_ARCHIVE_MISSING_OR_INVALID'})
    counts = Counter(row.get('code') for row in snapshot.rows)
    symbols = {}
    for row in snapshot.rows:
        code = row.get('code')
        if code not in universe.codes or counts[code] != 1:
            continue
        symbols[code] = {kind: _compare(row, kind=kind, date=trade_date, as_of=as_of, archives=archives)
                         for kind in ('volume', 'price')}
    content = encoded({
        'contract_version': CONTRACT_VERSION, 'trade_date': trade_date, 'market': 'HK_CONNECT',
        'as_of': as_of.isoformat(), 'current_snapshot': current_binding,
        'validator_sha256': digest(Path(__file__).read_bytes()),
        'window': {'mode': 'DIAGNOSTIC_NOT_APPROVED_RULE', 'requested_sessions': DIAGNOSTIC_WINDOW_SESSIONS,
                   'dates': dates, 'calendar_market': 'hk_connect', 'calendar_sha256': calendar_sha,
                   'archive_accepted_count': len(archives), 'archive_unavailable_count': len(archive_gaps),
                   'gaps': window_gaps},
        'rules': {'volume_authorized': False, 'price_authorized': False,
                  'numeric_thresholds': None, 'source_metadata_authority': 'NOT_PROMOTED_BY_THIS_AUDIT'},
        'archive_gaps': archive_gaps, 'symbols': symbols,
    })
    return ConditionAudit(snapshot.source['sha256'], universe.source['sha256'], as_of.isoformat(),
                          content, _SEAL, digest(content))


def condition_details(evidence: ConditionAudit, *, universe: VerifiedUniverse,
                      snapshot: VerifiedSnapshot, as_of: datetime) -> dict[str, Any]:
    """Only the same admitted snapshot/date may consume the immutable audit."""
    if (not isinstance(evidence, ConditionAudit) or evidence._seal is not _SEAL
        or evidence._content_sha256 != digest(evidence.content)
        or not admitted(universe, snapshot, snapshot.rows)
        or evidence.snapshot_sha256 != snapshot.source['sha256']
        or evidence.universe_sha256 != universe.source['sha256']
        or evidence.as_of != as_of.isoformat()):
        raise EvidenceError('CONDITION_AUDIT_NOT_BOUND_TO_CURRENT_SNAPSHOT')
    result = json.loads(evidence.content)
    result['audit_sha256'] = digest(evidence.content)
    return result


def validate_condition_projection(value: Any, *, kind: str, symbol: str, as_of: datetime,
                                  sources: Sequence[Mapping[str, Any]],
                                  state_root: Path | None = None,
                                  verify_published_sources: bool = False) -> None:
    """Read-only consumer contract, not source authentication or rule approval.

    A checksum cannot grant authority. Even a self-rehashed payload must remain
    diagnostic/unknown and be bound to this candidate's admitted source identity.
    This validator never fetches archives or writes from an API GET.
    """
    if not isinstance(value, Mapping):
        raise EvidenceError('CONDITION_PROJECTION_NOT_OBJECT')
    body = dict(value)
    expected_sha = body.pop('diagnostic_content_sha256', None)
    if digest(encoded(body)) != expected_sha:
        raise EvidenceError('CONDITION_PROJECTION_CONTENT_SHA_MISMATCH')
    if (body.get('contract_version') != CONTRACT_VERSION
        or body.get('state') != 'DIAGNOSTIC_ONLY_RULE_UNAPPROVED'
        or body.get('predicate') != 'unknown'
        or body.get('approved_valid_sample_count') is not None
        or body.get('required_min_samples') is not None):
        raise EvidenceError('CONDITION_PROJECTION_MUST_REMAIN_UNKNOWN')
    rules = body['rules']
    if (rules['volume_authorized'] is not False or rules['price_authorized'] is not False
        or rules['numeric_thresholds'] is not None
        or rules['source_metadata_authority'] != 'NOT_PROMOTED_BY_THIS_AUDIT'):
        raise EvidenceError('CONDITION_PROJECTION_RULE_NOT_AUTHORIZED')
    current = body['current_snapshot']
    if aware(current['available_at']) != as_of:
        raise EvidenceError('CONDITION_PROJECTION_CURRENT_TIME_MISMATCH')
    if not any(s.get('role') == 'EXISTING_SHARED_FUTU_1530_SNAPSHOT'
               and all(s.get(k) == current.get(v) for k, v in (
                   ('artifact_ref', 'artifact_ref'), ('sha256', 'artifact_sha256'),
                   ('receipt_ref', 'receipt_ref'), ('run_id', 'run_id'),
                   ('owner', 'owner'), ('source_date', 'source_date'), ('available_at', 'available_at')))
               for s in sources):
        raise EvidenceError('CONDITION_PROJECTION_CURRENT_SOURCE_MISMATCH')
    samples = body['samples']
    count = body['valid_sample_count']
    if not isinstance(samples, list) or type(count) is not int or count != len(samples):
        raise EvidenceError('CONDITION_PROJECTION_SAMPLE_COUNT_INVALID')
    dates = []
    for sample in samples:
        day = sample['trade_date']
        dt = datetime.strptime(day, '%Y%m%d')
        if (dt.strftime('%Y%m%d') != day or day >= as_of.astimezone(HK).strftime('%Y%m%d')
            or sample['symbol'] != symbol or sample['source_date'] != day
            or aware(sample['available_at']) > as_of):
            raise EvidenceError('CONDITION_PROJECTION_HISTORICAL_IDENTITY_INVALID')
        for field in ('artifact_sha256', 'receipt_sha256', 'quote_sha256'):
            sha = sample[field]
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                raise EvidenceError('CONDITION_PROJECTION_SAMPLE_SHA_INVALID')
        dates.append(day)
    if len(dates) != len(set(dates)):
        raise EvidenceError('CONDITION_PROJECTION_DUPLICATE_SAMPLE_DATE')
    if kind == 'price':
        daily = body['daily_price_window']
        if (body['daily_ohlc_authority'] != 'UNBOUND' or body['historical_position_state'] != 'UNKNOWN'
            or daily['state'] != 'INPUT_UNBOUND' or any(daily[k] is not None for k in
                ('valid_sample_count', 'window_sessions', 'last_usable_bar_date'))):
            raise EvidenceError('CONDITION_DAILY_PRICE_INPUT_NOT_ADMITTED')
    if verify_published_sources:
        if state_root is None:
            raise EvidenceError('CONDITION_PROJECTION_SOURCE_ROOT_REQUIRED')
        _validate_published_projection(body, kind=kind, symbol=symbol, as_of=as_of,
                                       state_root=state_root)
