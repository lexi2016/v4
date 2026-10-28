"""Finite row accounting and strict readiness for the existing HK panel owner.

Staging is a derived, immutable audit view; it never advances an authority
pointer. Structural admission is deliberately separate from units/PIT proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from .hashing import canonical_bytes, sha256_file
from .store import StoreError

FIELDS = ('open', 'high', 'low', 'close', 'amount', 'trade')
KEYS = ['code_norm', 'trade_date_compact']
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _code(value):
    text = str(value).strip().upper()
    match = re.fullmatch(r'(?:HK\.)?(\d{1,5})(?:\.HK(?:_CONNECT)?)?', text)
    return 'HK.' + match[1].zfill(5) if match and int(match[1]) else ''


def _date(value):
    text = str(value).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        text = text.replace('-', '')
    if re.fullmatch(r'\d{8}', text):
        try:
            datetime.strptime(text, '%Y%m%d')
            return text
        except ValueError:
            pass
    return ''


def _instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed


def audit_frame(frame, *, package, source_sha256, through_date=None):
    """Return normalized facts, one disposition per original row and a profile.

    Reference (source SHA, zero-based source row) is lossless into the retained
    original. Equal facts merge references; conflicting same-package facts are
    all quarantined. No magnitude-based scaling, filling or outlier repair.
    """
    import numpy as np
    import pandas as pd

    if package not in ('C', 'B', 'INCREMENT'):
        raise StoreError('HK_PANEL_PACKAGE_INVALID')
    if re.fullmatch(r'[a-f0-9]{64}', source_sha256) is None:
        raise StoreError('HK_PANEL_SOURCE_SHA_INVALID')
    if through_date is not None and not _date(through_date):
        raise StoreError('HK_PANEL_BOUND_INVALID')
    facts = frame.copy().reset_index(drop=True)
    code_column = 'code_norm' if 'code_norm' in facts else 'code'
    date_column = next((c for c in ('trade_date_compact', 'trade_date', 'date') if c in facts), None)
    facts['code_norm'] = facts[code_column].map(_code) if code_column in facts else ''
    facts['trade_date_compact'] = facts[date_column].map(_date) if date_column else ''
    reasons = pd.Series('', index=facts.index, dtype='str')

    def mark(mask, reason):
        reasons.loc[mask] += reason + ';'

    mark(facts.code_norm.eq(''), 'INVALID_HK_CODE')
    mark(facts.trade_date_compact.eq(''), 'INVALID_CALENDAR_DATE')
    profile = {}
    for field in FIELDS:
        raw = facts[field] if field in facts else pd.Series(float('nan'), index=facts.index)
        numeric = pd.to_numeric(raw, errors='coerce').astype(float)
        finite = np.isfinite(numeric)
        # Object/mixed columns can contain booleans too. Inspect the original
        # value before numeric coercion so True/False never become 1/0 facts.
        boolean = raw.map(lambda value: isinstance(value, (bool, np.bool_)))
        finite &= ~boolean
        mark(boolean, 'BOOLEAN_' + field.upper())
        mark(~finite, 'NONFINITE_' + field.upper())
        mark(finite & (numeric.le(0) if field in FIELDS[:4] else numeric.lt(0)), 'NONPOSITIVE_' + field.upper() if field in FIELDS[:4] else 'NEGATIVE_' + field.upper())
        facts[field] = numeric
        profile[field] = dict(missing=int(raw.isna().sum()), nonfinite=int((~finite).sum()),
                              zero=int(numeric.eq(0).sum()), negative=int(numeric.lt(0).sum()))
    mark(facts.high.lt(facts[['open', 'close', 'low']].max(axis=1)) |
         facts.low.gt(facts[['open', 'close', 'high']].min(axis=1)), 'OHLC_ORDER_INVALID')
    if 'market_type' in facts:
        mark(facts.market_type.notna() & ~facts.market_type.isin(['HK']), 'MARKET_NOT_HK')
    keyed = facts.code_norm.ne('') & facts.trade_date_compact.ne('')
    unique_facts = facts.loc[keyed, KEYS + list(FIELDS)].drop_duplicates()
    conflict_keys = unique_facts.loc[unique_facts.duplicated(KEYS, keep=False), KEYS].drop_duplicates()
    key_index = pd.MultiIndex.from_frame(facts[KEYS])
    conflict = key_index.isin(pd.MultiIndex.from_frame(conflict_keys))
    mark(conflict, 'SAME_KEY_CONFLICT')
    disposition = pd.Series('ACCEPTED', index=facts.index, dtype='str')
    disposition.loc[reasons.ne('')] = 'QUARANTINED'
    if through_date:
        outside = facts.trade_date_compact.ne('') & facts.trade_date_compact.gt(through_date)
        # Keep structural reason codes even when the final disposition is outside.
        disposition.loc[outside] = 'OUT_OF_WINDOW'
        mark(outside, 'AFTER_FROZEN_END')
    duplicate = facts.duplicated(KEYS, keep='first') & disposition.eq('ACCEPTED')
    disposition.loc[duplicate] = 'DUPLICATE_IDENTICAL'
    mark(duplicate, 'IDENTICAL_FACT_RETAINED_REFERENCE')
    first = pd.Series(facts.index, index=facts.index).groupby(key_index, sort=False).transform('first')
    ledger = pd.DataFrame(dict(source_package=package, source_sha256=source_sha256,
        source_row=facts.index, code_norm=facts.code_norm, trade_date_compact=facts.trade_date_compact,
        disposition=disposition, reasons=reasons.str.rstrip(';'), representative_source_row=first))
    facts['source_package'] = package
    facts['source_sha256'] = source_sha256
    facts['source_row'] = facts.index
    facts['provider_identity'] = facts['source'].fillna('UNKNOWN') if 'source' in facts else 'UNKNOWN'
    # This is a reader/container identity; it never asserts a market-data vendor.
    facts['container_identity'] = 'PARQUET_RAW_FACTS'
    if 'source' in facts:
        native = facts.source.eq('tdx_vipdoc_71_day')
        facts.loc[native, 'provider_identity'] = 'UNKNOWN_PACKED_DAY_UPSTREAM'
        facts.loc[native, 'container_identity'] = 'VIPDOC_71_DAY'
    dates = facts.loc[facts.trade_date_compact.ne(''), 'trade_date_compact']
    sources = facts['source'].fillna('UNKNOWN').astype(str).value_counts().to_dict() if 'source' in facts else {'UNKNOWN':len(facts)}
    metadata_coverage = {column:int(facts[column].notna().sum()) for column in
        ('history_available_at', 'history_source_available_at', 'available_at', 'captured_at',
         'volume_unit_status', 'continuity_break') if column in facts}
    # Compact finite date/code/source coverage; no outcome/label columns read.
    coverage = facts.loc[keyed].groupby('trade_date_compact').agg(rows=('code_norm','size'), codes=('code_norm','nunique')).reset_index().to_dict('records')
    ordered = facts.loc[keyed].sort_values(KEYS)
    previous = ordered.groupby('code_norm', sort=False).close.shift()
    ratio = ordered.close / previous
    suspicious = int((ratio.gt(1.5) | ratio.lt(1/1.5)).sum())
    summary = dict(coverage_by_date=coverage, suspicious_close_ratio_edges=suspicious, heuristic_action='OBSERVATION_ONLY_NO_REPAIR', input_rows=len(facts), code_count=int(facts.code_norm.replace('', None).nunique()),
        date_count=int(dates.nunique()), min_date=dates.min() if len(dates) else None,
        max_date=dates.max() if len(dates) else None, fields=profile, sources=sources,
        metadata_nonnull=metadata_coverage, conflicting_keys=len(conflict_keys),
        dispositions=disposition.value_counts().to_dict())
    assert sum(summary['dispositions'].values()) == len(frame)
    return facts, ledger, summary


def reconcile_frames(c_frame, b_frame, *, c_sha256, b_sha256, through_date, policy=None):
    """C owns all overlap keys; B only supplements keys absent from raw C."""
    import pandas as pd

    c, cl, cp = audit_frame(c_frame, package='C', source_sha256=c_sha256, through_date=through_date)
    b, bl, bp = audit_frame(b_frame, package='B', source_sha256=b_sha256, through_date=through_date)
    overlaps = pd.MultiIndex.from_frame(b[KEYS]).isin(pd.MultiIndex.from_frame(c[KEYS]))
    shadow = overlaps & bl.disposition.isin(['ACCEPTED', 'DUPLICATE_IDENTICAL'])
    bl.loc[shadow, 'disposition'] = 'SHADOWED_BY_C'
    bl.loc[shadow, 'reasons'] = 'C_OWNS_OVERLAP_B_AUDIT_ONLY'
    if policy is not None:
        policy.check_panel(c_sha256)
        c = policy.project_frame(c)
        # Sparse existing decisions are retained, including retrospective nature.
        holds = {}
        for (code, date), record in policy.decisions.items():
            held = policy.held_fields(code, date)
            if held:
                holds[(code, date)] = ','.join(held)
        held_fields = pd.Series([holds.get(tuple(key), '') for key in c[KEYS].itertuples(index=False, name=None)], index=c.index, dtype='str')
        # A held volume field does not quarantine independent price/amount use.
        # Retain the row and carry every held field into the candidate/ledger.
        held = cl.disposition.eq('ACCEPTED') & held_fields.ne('')
        cl.loc[held, 'disposition'] = 'ACCEPTED_WITH_FIELD_HOLDS'
        cl.loc[held, 'reasons'] = 'EXISTING_RESOLUTION_FIELD_HOLD:' + held_fields.loc[held]
        c['resolution_held_fields'] = held_fields
        for (code, date), correction in policy.corrections.items():
            mask = c.code_norm.eq(code) & c.trade_date_compact.eq(date)
            for field, value in correction['values'].items():
                c.loc[mask, field] = value
            c.loc[mask, 'provider_identity'] = 'TDXPY_RETROSPECTIVE_CORRECTION'
    candidate = pd.concat([c.loc[cl.disposition.isin(['ACCEPTED', 'ACCEPTED_WITH_FIELD_HOLDS'])], b.loc[bl.disposition.eq('ACCEPTED')]], ignore_index=True)
    candidate = candidate.sort_values(KEYS).reset_index(drop=True)
    for field in ('price', 'amount', 'currency', 'adjustment', 'pit', 'eligibility', 'suspension'):
        candidate[field + '_readiness'] = 'PENDING'
    candidate['readiness_reason'] = 'MISSING_SOURCE_UNITS_CURRENCY_PIT_ACTION_MEMBERSHIP_STATUS_PROOF'
    ledger = pd.concat([cl, bl], ignore_index=True)
    assert not candidate.duplicated(KEYS).any()
    assert len(ledger) == len(c_frame) + len(b_frame)
    return candidate, ledger, dict(C=cp, B=bp, reconciliation=ledger.groupby('source_package').disposition.value_counts().unstack(fill_value=0).to_dict('index'),
        candidate_rows=len(candidate), c_over_b_overlap_rows=int(overlaps.sum()),
        resolution_manifest_sha256=policy.manifest_sha256 if policy is not None else None)


def _immutable(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise StoreError('HK_PANEL_IMMUTABLE_CONFLICT')
    else:
        with path.open('xb') as output:
            output.write(raw)


def stage_hk_panel_candidate(c_path, b_path, destination, *, expected_c_sha256,
                             expected_b_sha256, through_date, policy=None, input_evidence=()):
    """Stage immutable derived facts/ledger/profile, without live pointer writes."""
    import pandas as pd

    c_path, b_path, destination = Path(c_path), Path(b_path), Path(destination)
    for path, expected in ((c_path, expected_c_sha256), (b_path, expected_b_sha256)):
        if sha256_file(path) != expected:
            raise StoreError('HK_PANEL_FROZEN_SOURCE_CHANGED')
    c, b = pd.read_parquet(c_path), pd.read_parquet(b_path)
    candidate, ledger, profile = reconcile_frames(c, b, c_sha256=expected_c_sha256,
        b_sha256=expected_b_sha256, through_date=through_date, policy=policy)
    # Rehash after reading: a profile cannot silently combine different versions.
    for path, expected in ((c_path, expected_c_sha256), (b_path, expected_b_sha256)):
        if sha256_file(path) != expected:
            raise StoreError('HK_PANEL_FROZEN_SOURCE_CHANGED')
    destination.mkdir(parents=True, exist_ok=True)
    # Bytes are deterministic with the same pandas/arrow versions; existing files
    # must match and cannot be silently rewritten.
    from io import BytesIO
    artifacts = {}
    for name, frame in (('candidate.parquet', candidate), ('row_dispositions.parquet', ledger)):
        buffer = BytesIO()
        frame.to_parquet(buffer, index=False)
        raw = buffer.getvalue()
        _immutable(destination / name, raw)
        artifacts[name] = hashlib.sha256(raw).hexdigest()
    profile_raw = canonical_bytes(profile)
    _immutable(destination / 'profile.json', profile_raw)
    artifacts['profile.json'] = hashlib.sha256(profile_raw).hexdigest()
    manifest = dict(schema_version='hk_panel_audit_candidate.v1', through_date=through_date,
        inputs=dict(C=dict(path=str(c_path), sha256=expected_c_sha256), B=dict(path=str(b_path), sha256=expected_b_sha256)),
        source_sha256=sha256_file(Path(__file__)), artifacts=artifacts, input_evidence=list(input_evidence),
        resolution_manifest_sha256=profile['resolution_manifest_sha256'], input_rows=len(ledger),
        candidate_rows=len(candidate), authority_precedence='C_OVER_B_ABSENT_KEYS_ONLY',
        semantic_status='CANNOT_CONFIRM', missing_proof=['CURRENCY', 'AMOUNT_UNIT', 'VOLUME_UNIT',
        'PIT_ADJUSTMENT_CORPORATE_ACTIONS', 'HISTORICAL_AVAILABILITY', 'EFFECTIVE_MEMBERSHIP', 'SUSPENSION_STATUS'], **SAFETY)
    _immutable(destination / 'manifest.json', canonical_bytes(manifest))
    return manifest


def load_staged_hk_panel_candidate(manifest_path, expected_manifest_sha256):
    """Read only an explicitly pinned candidate, never a live CURRENT pointer."""
    import pandas as pd

    path = Path(manifest_path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise StoreError('HK_PANEL_CANDIDATE_MANIFEST_SHA_MISMATCH')
    manifest = json.loads(raw)
    if manifest.get('schema_version') != 'hk_panel_audit_candidate.v1' or any(manifest.get(k) != v for k, v in SAFETY.items()):
        raise StoreError('HK_PANEL_CANDIDATE_CONTRACT_INVALID')
    for name, expected in manifest['artifacts'].items():
        if Path(name).name != name or (path.parent / name).is_symlink() or sha256_file(path.parent / name) != expected:
            raise StoreError('HK_PANEL_CANDIDATE_ARTIFACT_SHA_MISMATCH')
    frame = pd.read_parquet(path.parent / 'candidate.parquet')
    if len(frame) != manifest['candidate_rows'] or frame.duplicated(KEYS).any():
        raise StoreError('HK_PANEL_CANDIDATE_ROWS_INVALID')
    return frame, manifest


def strict_window_readiness(rows, *, code, sessions, cutoff, panel_sha256, proof=None, target_date=None):
    """Assess an explicitly frozen 21-session window; never infer vendor facts.

    Membership, listing and suspension are checked only for explicit target_date;
    no target date means those gates remain PENDING. Historical membership is
    not required for price/amount window admission.

    Proof is an operator-supplied iterable of per-code/date material records,
    bound to the panel SHA, available by cutoff, and carrying source references.
    This helper cannot acquire or create that missing historical material.
    """
    code = _code(code)
    sessions = list(sessions)
    fields = {name:'PASS' for name in ('price', 'amount', 'currency', 'adjustment', 'pit', 'eligibility', 'suspension')}
    reasons = []
    refs = []

    def pending(field, reason):
        if fields[field] != 'REJECT':
            fields[field] = 'PENDING'
        if reason not in reasons:
            reasons.append(reason)

    try:
        cutoff_time = _instant(cutoff)
    except (TypeError, ValueError):
        cutoff_time = None
    window_valid = (len(sessions) == 21 and all(_date(s) == s for s in sessions) and
                    sessions == sorted(set(sessions)) and code and cutoff_time is not None and
                    sessions[-1] <= cutoff_time.strftime('%Y%m%d') and
                    re.fullmatch(r'[a-f0-9]{64}', panel_sha256 or '') is not None)
    if not window_valid:
        return dict(schema_version='hk_panel_strict_readiness.v1', status='PENDING', code=code,
            dependency_dates=sessions, target_date=target_date, cutoff=cutoff, panel_sha256=panel_sha256,
            field_readiness={name:'PENDING' for name in fields}, reasons=['FROZEN_WINDOW_IDENTITY_INVALID'], evidence_refs=[])
    indexed = {}
    records = rows.to_dict('records') if hasattr(rows, 'to_dict') else rows
    for row in records:
        if _code(row.get('code_norm', row.get('code', ''))) != code:
            continue
        date = _date(row.get('trade_date_compact', row.get('trade_date', row.get('date', ''))))
        if date in sessions:
            indexed.setdefault(date, []).append(row)
    materials = {}
    if not isinstance(proof, (list, tuple)):
        proof = ()
    for material in proof:
        if not isinstance(material, dict):
            continue
        if _code(material.get('code', '')) == code:
            materials.setdefault(_date(material.get('date', '')), []).append(material)
    def verified_material(date):
        entries = materials.get(date, [])
        material = entries[0] if len(entries) == 1 else {}
        try:
            evidence_refs = material['evidence_refs']
            bound = (material['panel_sha256'] == panel_sha256 and _instant(material['available_at']) <= cutoff_time and
                bool(evidence_refs) and all(re.fullmatch(r'[a-f0-9]{64}', r['sha256']) and r['reference'] for r in evidence_refs))
            # Require byte-bound local material, rather than trusting booleans
            # supplied by a caller. This format is an engineering interface;
            # no existing historical source is automatically certified into it.
            record = {key:value for key,value in material.items() if key != 'evidence_refs'}
            supported = False
            for ref in evidence_refs:
                source = Path(ref['reference'])
                if not source.is_absolute() or source.is_symlink() or not source.is_file() or sha256_file(source) != ref['sha256']:
                    bound = False
                    break
                payload = json.loads(source.read_bytes())
                if (payload.get('schema_version') == 'hk_panel_strict_material.v1' and
                        payload.get('market') == 'HK' and payload.get('panel_sha256') == panel_sha256 and
                        isinstance(payload.get('records'), list) and
                        any(isinstance(source_record, dict) and
                            json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False) ==
                            json.dumps(source_record, sort_keys=True, separators=(',', ':'), allow_nan=False)
                            for source_record in payload['records']) and
                        all(payload.get(k) is v for k,v in SAFETY.items())):
                    supported = True
            bound = bound and supported
        except (TypeError, ValueError, KeyError, OSError, AttributeError):
            bound = False
        return material if bound else {}, evidence_refs if bound else []

    for date in sessions:
        values = indexed.get(date, [])
        if len(values) != 1:
            pending('price', 'MISSING_OR_DUPLICATE_WINDOW_ROW')
            pending('amount', 'MISSING_OR_DUPLICATE_WINDOW_ROW')
        else:
            row = values[0]
            held_fields = set(str(row.get('resolution_held_fields', '')).split(','))
            if held_fields.intersection(('open','high','low','close')):
                pending('price', 'EXISTING_RESOLUTION_PRICE_FIELD_HOLD')
            if 'amount' in held_fields and date != sessions[0]:
                pending('amount', 'EXISTING_RESOLUTION_AMOUNT_FIELD_HOLD')
            for field, columns in [('price', ('open', 'high', 'low', 'close')), ('amount', ('amount',))]:
                if field == 'amount' and date == sessions[0]:
                    continue
                numbers = [row.get(column) for column in columns]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (field == 'price' and v == 0) for v in numbers):
                    pending(field, 'WINDOW_NUMERIC_FACT_INVALID')
            if all(isinstance(row.get(k), (int, float)) for k in ('open', 'high', 'low', 'close')) and (row['high'] < max(row[k] for k in ('open', 'low', 'close')) or row['low'] > min(row[k] for k in ('open', 'high', 'close'))):
                pending('price', 'WINDOW_OHLC_ORDER_INVALID')
        material, evidence_refs = verified_material(date)
        if not material:
            for field in ('currency', 'adjustment', 'pit'):
                pending(field, field.upper() + '_PROOF_MISSING_OR_TIME_UNSAFE')
            continue
        refs.extend(evidence_refs)
        if material.get('price_currency') != 'HKD' or material.get('amount_currency') != 'HKD' or material.get('amount_unit') != 'HKD':
            pending('currency', 'HKD_PRICE_AMOUNT_UNITS_UNPROVEN')
        if material.get('adjustment') != 'PIT_ADJUSTED' or material.get('corporate_actions_complete') is not True:
            pending('adjustment', 'PIT_CORPORATE_ACTION_BASIS_UNPROVEN')
        if material.get('pit_available') is not True:
            pending('pit', 'HISTORICAL_AVAILABILITY_UNPROVEN')
    # Target eligibility/status has its own dated material and cutoff. It must
    # neither demand membership during the price window nor borrow that window.
    if not _date(target_date) or _date(target_date) < sessions[-1]:
        target_material, target_refs = {}, []
    else:
        target_material, target_refs = verified_material(_date(target_date))
    if not target_material:
        pending('eligibility', 'TARGET_MEMBERSHIP_LISTING_PROOF_MISSING_OR_TIME_UNSAFE')
        pending('suspension', 'TARGET_STATUS_PROOF_MISSING_OR_TIME_UNSAFE')
    else:
        refs.extend(target_refs)
        if target_material.get('eligible') is False:
            fields['eligibility'] = 'REJECT'
            reasons.append('NOT_ELIGIBLE_AT_TARGET')
        elif target_material.get('eligible') is not True:
            pending('eligibility', 'TARGET_MEMBERSHIP_UNPROVEN')
        listing_date = _date(target_material.get('listing_date', ''))
        if not listing_date:
            pending('eligibility', 'TARGET_LISTING_UNPROVEN')
        elif listing_date > _date(target_date):
            fields['eligibility'] = 'REJECT'
            reasons.append('NOT_LISTED_AT_TARGET')
        if target_material.get('suspended') is True:
            fields['suspension'] = 'REJECT'
            reasons.append('SUSPENDED_AT_TARGET')
        elif target_material.get('suspended') is not False:
            pending('suspension', 'TARGET_STATUS_UNPROVEN')
    status = 'REJECT' if 'REJECT' in fields.values() else 'PENDING' if 'PENDING' in fields.values() else 'PASS'
    return dict(schema_version='hk_panel_strict_readiness.v1', status=status, code=code,
        dependency_dates=sessions, target_date=target_date, cutoff=cutoff, panel_sha256=panel_sha256, field_readiness=fields,
        reasons=reasons, evidence_refs=list({json.dumps(r, sort_keys=True):r for r in refs}.values()))
