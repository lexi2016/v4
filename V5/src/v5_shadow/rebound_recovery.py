"""Read-only recovery worklist for the original rebound owner's missing inputs.

This is neither a panel publisher nor a market-data collector. Native records
are candidates for the existing owner's recovery, not evidence of units,
adjustment, point-in-time availability, membership or completed sessions.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import re
import struct

from . import rebound_observation as observation
from . import rebound_owner as owner
from .composition import no_symlinks
from .contracts import exact_keys, sha, trade_date
from .digests import canonical_bytes, sha256_json
from .module_api import _open_directory, _read_regular
from .source_capsule import checked_path

DAY = struct.Struct('<IfffffII')
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False,
              orders_sent=False, collection_performed=False, panel_published=False,
              formal_eligibility_verified=False, natural_verified=False)


def build_recovery_plan(artifact):
    """Use a committed observation readback, retaining exact calendar windows."""
    observation._validate(artifact)
    if artifact['computation_status'] != 'NATIVE_VALUES_OBSERVED':
        raise ValueError('RECOVERY_OBSERVATION_REQUIRED')
    history = artifact['history_sessions']
    days60, days5 = history['prior60'], history['previous5']
    if (len(days60) != 60 or len(set(days60)) != 60 or len(days5) != 5
            or len(set(days5)) != 5 or not set(days5).issubset(days60)):
        raise ValueError('RECOVERY_CALENDAR_WINDOWS')
    signal = trade_date(artifact['request']['signal_date'])
    for day in days60:
        if trade_date(day) >= signal: raise ValueError('RECOVERY_HISTORY_DATE')
    cells, duplicates, unresolved = [], [], []
    for row in artifact['rows']:
        for target, prefix, reason in ((cells, 'missing', 'MISSING_ROW'),
                                      (duplicates, 'duplicate', 'DUPLICATE_PANEL_DATE')):
            highs = set(row[prefix+'_prior60_dates'])
            volumes = set(row[prefix+'_previous5_dates'])
            if not highs.issubset(days60) or not volumes.issubset(days5):
                raise ValueError('RECOVERY_GAP_OUTSIDE_CALENDAR')
            for day in sorted(highs | volumes):
                target.append(dict(code=row['code'], date=day,
                    fields=([ 'high' ] if day in highs else []) + ([ 'trade' ] if day in volumes else []),
                    reason=reason))
        # The old screen reports aggregate invalid counts. Do not claim their
        # dates are known or that acquiring just the absent rows repairs them.
        if row['numeric_input_status'] != 'KNOWN':
            unresolved.append(dict(code=row['code'], reasons=list(row['input_gaps']),
                action='RECHECK_CORE_VALUES_AFTER_MISSING_ROWS_AND_DUPLICATES_ARE_RESOLVED'))
    cells.sort(key=lambda x: (x['code'], x['date']))
    duplicates.sort(key=lambda x: (x['code'], x['date']))
    identity = dict(source_run_id=artifact['run_id'], source_artifact_sha256=sha256_json(artifact),
        target_date=artifact['request']['target_date'], signal_date=signal,
        panel_sha256=artifact['source_identity']['panel_sha256'],
        panel_manifest_sha256=artifact['source_identity']['panel_manifest_sha256'],
        calendar_sha256=history['calendar_sha256'])
    plan = dict(schema_version='v5.rebound_recovery_plan.v1', **identity,
        history_sessions=copy.deepcopy(history), cells=cells, duplicate_cells=duplicates,
        unlocalized_numeric_gaps=unresolved,
        counts=dict(observed_codes=len(artifact['rows']), missing_code_dates=len(cells),
            missing_core_values=sum(len(c['fields']) for c in cells),
            duplicate_code_dates=len(duplicates), incomplete_codes=len(unresolved)),
        append_updater_can_repair_internal_gaps=False,
        repair_owner='EXISTING_HK_0_2_PANEL_OWNER',
        collection=dict(status='HOLD', requests_authorized=0,
            sequence=['AUDIT_EXACT_LOCAL_VIPDOC_BYTES', 'AUDIT_UNCONVERTED_EXISTING_PROVIDER_CAPTURES',
                      'MAC_CHECK_CURRENT_AUTHORIZED_PROVIDER_CAPABILITY', 'MAC_BOUND_REMAINING_REQUESTS']),
        requirements=dict(
            arithmetic=['60_EXACT_PRIOR_SESSION_POSITIVE_HIGHS', '5_EXACT_PRIOR_FULL_SESSION_VOLUMES',
                        'POSITIVE_CURRENT_CLOSE', 'NONNEGATIVE_CURRENT_VOLUME', 'POSITIVE_PREVIOUS5_MEAN'],
            admission=['PRICE_BASIS_AND_SCALE_OVER_SELECTED_HISTORY', 'VOLUME_UNIT_AND_SCALE_OVER_ALL_SIX_SESSIONS',
                       'SOURCE_BYTE_LINEAGE_AND_STABILITY', 'ACTUAL_AVAILABILITY_BY_CUTOFF',
                       'COMPLETED_HK_DAILY_SESSION_EVIDENCE', 'EXACT_TARGET_MEMBERSHIP'],
            observations_only=['AMOUNT', 'PRE_CLOSE', 'LOW', '20_RECORD_VOLUME', '3_AND_5_RECORD_RETURN'],
            unused_master_fields=['outstanding_shares', 'circular_market_val', 'listing_date', 'lot_size'],
            separate_acceptance=['NATURAL_SCHEDULE_RUN'],
            provider_final_flag_required=False,
            finality_policy='DOCUMENTED_DAILY_SOURCE_CONTRACT_PLUS_ACTUAL_POST_SESSION_CAPTURE; NO_SYNTHETIC_1500_CLOCK'),
        **SAFETY)
    return dict(plan, plan_sha256=sha256_json(plan))


def _validate_plan(plan):
    body = {k: v for k, v in plan.items() if k != 'plan_sha256'}
    if (plan.get('schema_version') != 'v5.rebound_recovery_plan.v1'
            or sha256_json(body) != plan.get('plan_sha256')
            or any(plan.get(k) is not v for k, v in SAFETY.items())):
        raise ValueError('RECOVERY_PLAN_IDENTITY')
    signal = trade_date(plan['signal_date'])
    days60, days5 = plan['history_sessions']['prior60'], plan['history_sessions']['previous5']
    if (len(days60) != 60 or len(set(days60)) != 60 or len(days5) != 5
            or len(set(days5)) != 5 or not set(days5).issubset(days60)
            or any(trade_date(day) >= signal for day in days60)):
        raise ValueError('RECOVERY_CALENDAR_WINDOWS')
    keys = set()
    for cell in plan['cells']:
        exact_keys(cell, ('code', 'date', 'fields', 'reason'))
        key = (cell['code'], trade_date(cell['date']))
        if (not re.fullmatch(r'HK\.\d{5}', cell['code']) or key in keys
                or cell['reason'] != 'MISSING_ROW' or not cell['fields']
                or cell['fields'] not in (['high'], ['trade'], ['high', 'trade'])
                or cell['date'] >= signal
                or ('high' in cell['fields'] and cell['date'] not in days60)
                or ('trade' in cell['fields'] and cell['date'] not in days5)):
            raise ValueError('RECOVERY_CELL_CONTRACT')
        keys.add(key)


def audit_vipdoc_candidates(plan, request):
    """Inspect only explicitly SHA-bound files; never glob, fill zeros or scale.

    The record layout is the original hk_0_2.py `_VIPDOC_DAY_STRUCT` layout.
    Its raw trade field is uint32 at offset 24, not a proven share/lot unit.
    """
    _validate_plan(plan)
    exact_keys(request, ('schema_version', 'input_root', 'files'))
    if request['schema_version'] != 'v5.rebound_native_audit_request.v1':
        raise ValueError('RECOVERY_NATIVE_REQUEST_SCHEMA')
    root = no_symlinks(request['input_root'])
    if not root.is_dir(): raise ValueError('RECOVERY_NATIVE_ROOT')
    files = request['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 2000:
        raise ValueError('RECOVERY_NATIVE_FILE_BOUND')
    needed = {}
    for cell in plan['cells']: needed.setdefault(cell['code'], set()).add(cell['date'])
    selected, identities, total = {}, {}, 0
    for relative, expected in sorted(files.items()):
        match = re.fullmatch(r'vipdoc/ds/lday/71#(\d{5})\.day', relative)
        if match is None or 'HK.' + match[1] not in needed:
            raise ValueError('RECOVERY_NATIVE_UNREQUESTED_FILE')
        sha(expected)
        path = checked_path(root, relative)
        directory = _open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally: os.close(directory)
        try: raw = _read_regular(fd, 8 * 1024**2)
        finally: os.close(fd)
        total += len(raw)
        if total > 256 * 1024**2: raise ValueError('RECOVERY_NATIVE_TOTAL_BYTES')
        if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('RECOVERY_NATIVE_SHA')
        if len(raw) % DAY.size: raise ValueError('RECOVERY_NATIVE_TRAILING_BYTES')
        code = 'HK.' + match[1]
        identities[relative] = dict(sha256=expected, bytes=len(raw))
        for offset in range(0, len(raw), DAY.size):
            record = raw[offset:offset+DAY.size]
            values = DAY.unpack(record)
            day = str(values[0])
            if day not in needed[code]: continue
            selected.setdefault((code, day), []).append(dict(
                source_relative=relative, file_sha256=expected, record_offset=offset,
                record_sha256=hashlib.sha256(record).hexdigest(),
                values=dict(zip(('open', 'high', 'low', 'close', 'amount', 'trade', 'position'), values[1:]))))
    rows = []
    for cell in plan['cells']:
        matches = selected.get((cell['code'], cell['date']), [])
        status, candidate = 'NOT_PRESENT', None
        if len(matches) > 1: status = 'DUPLICATE_NATIVE_DATE'
        elif matches:
            candidate = matches[0]
            v = candidate['values']
            valid = all(math.isfinite(v[k]) and v[k] > 0 for k in ('open', 'high', 'low', 'close'))
            valid = valid and v['low'] <= min(v['open'], v['close']) <= max(v['open'], v['close']) <= v['high']
            # Amount is not a two-gate input. Preserve a nonfinite optional
            # amount as unknown without discarding otherwise valid OHLC/trade.
            if not math.isfinite(v['amount']): v['amount'] = None
            status = 'EXACT_NATIVE_ROW' if valid else 'INVALID_NATIVE_VALUE'
            if not valid: candidate = {k: v for k, v in candidate.items() if k != 'values'}
        rows.append(dict(cell, status=status, match_count=len(matches), candidate=candidate))
    result = dict(schema_version='v5.rebound_native_audit.v1', plan_sha256=plan['plan_sha256'],
        input_files=identities, input_files_sha256=sha256_json(identities), rows=rows,
        counts={status: sum(r['status'] == status for r in rows) for status in
                ('EXACT_NATIVE_ROW', 'NOT_PRESENT', 'DUPLICATE_NATIVE_DATE', 'INVALID_NATIVE_VALUE')},
        conversion_applied=False, scale_applied=1, volume_unit=None, price_basis='NOT_PROVEN',
        finality_status='NOT_PROVEN', usable_for_formal_selection=False,
        next_action='EXISTING_OWNER_VERIFY_SEMANTICS_AND_PUBLISH_IMMUTABLE_INTERNAL_GAP_REPAIR', **SAFETY)
    return dict(result, audit_sha256=sha256_json(result))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observation-root', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--native-request', type=Path)
    args = parser.parse_args()
    artifact = observation.read_rebound_observation(args.observation_root, owner._json(args.reference.read_bytes()))
    plan = build_recovery_plan(artifact)
    return dict(plan=plan, native_audit=(audit_vipdoc_candidates(plan, owner._json(args.native_request.read_bytes()))
                                      if args.native_request else None))


if __name__ == '__main__':
    print(canonical_bytes(main()).decode())
