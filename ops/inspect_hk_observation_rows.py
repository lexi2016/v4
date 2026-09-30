"""Read-only issue10 collector-row accounting, NOT a pool/selection authority.

Reads an explicit serialized SourceResult and its explicit requested-code list.
Never fetches quotes, creates a pool, chooses a latest directory, or publishes
market data. Row-accounting success is not bar-series/PIT/producer validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot

_WINDOWS = {'STAGE_1300_1315': ('13:00:00', '13:15:00'),
            'STAGE_1445_1500': ('14:45:00', '15:00:00')}
_CODE = re.compile(r'HK\.\d{5}\Z')
_TZ = ZoneInfo('Asia/Hong_Kong')


def inspect_rows(source: Mapping[str, Any], codes: Sequence[str], *,
                 trade_date: str, stage_id: str) -> dict[str, Any]:
    """Account for every requested code, without discarding bad evidence."""
    errors: list[str] = []
    if trade_date != '20260930' or stage_id not in _WINDOWS:
        errors.append('OUTSIDE_ISSUE10_EXHQ_AFTERNOON_SCOPE')
    if (not isinstance(codes, (list, tuple)) or not codes
            or any(not isinstance(c, str) or not _CODE.fullmatch(c) for c in codes)):
        errors.append('REQUEST_CODES_INVALID')
        codes = []
    expected = set(codes)
    if len(expected) != len(codes):
        errors.append('REQUEST_CODES_DUPLICATED')
    if not isinstance(source, Mapping):
        source = {}
        errors.append('SOURCE_RESULT_NOT_OBJECT')
    if source.get('source_id') != 'pytdx_exhq' or source.get('status') not in ('READY', 'PARTIAL_WITH_ROWS'):
        errors.append('SOURCE_RESULT_NOT_USABLE_EXHQ')
    if type(source.get('requested_rows')) is not int or source['requested_rows'] != len(codes):
        errors.append('DECLARED_REQUEST_COUNT_MISMATCH')
    rows = source.get('rows')
    if not isinstance(rows, (list, tuple)) or not rows:
        rows = []
        errors.append('FULL_ROWS_MISSING_OR_EMPTY')
    missing = source.get('missing_symbols')
    if not isinstance(missing, (list, tuple)) or any(not isinstance(c, str) for c in missing):
        missing = []
        errors.append('MISSING_SYMBOLS_INVALID')
    if len(set(missing)) != len(missing) or not set(missing) <= expected:
        errors.append('MISSING_SYMBOLS_DUPLICATED_OR_OUTSIDE_REQUEST')
    observed: set[str] = set()
    naive_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f'ROW_NOT_OBJECT:{index}')
            continue
        code = row.get('code')
        if not isinstance(code, str) or code not in expected or code in observed:
            errors.append(f'ROW_CODE_DUPLICATED_OR_OUTSIDE_REQUEST:{index}')
            continue
        observed.add(code)
        try:
            # A time-only string cannot prove the requested date. Naive full
            # timestamps are reported as using the original market timezone.
            stamp = datetime.fromisoformat(str(row.get('update_time') or '').replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                naive_count += 1
                stamp = stamp.replace(tzinfo=_TZ)
            stamp = stamp.astimezone(_TZ)
            window = _WINDOWS.get(stage_id)
            if (stamp.strftime('%Y%m%d') != trade_date or window is None
                    or not datetime.fromisoformat(f'2026-09-30T{window[0]}').replace(tzinfo=_TZ)
                    <= stamp <= datetime.fromisoformat(f'2026-09-30T{window[1]}').replace(tzinfo=_TZ)):
                raise ValueError('outside date/window')
        except ValueError:
            errors.append(f'ROW_TIME_UNPROVEN_OR_OUTSIDE_WINDOW:{index}')
    if observed & set(missing):
        errors.append('OBSERVED_AND_MISSING_OVERLAP')
    unaccounted = expected - observed - set(missing)
    if unaccounted:
        errors.append('REQUEST_CODES_NOT_PERSISTED_OR_DECLARED_MISSING')
    limitations = source.get('cannot_confirm')
    return {'schema_version': 'stage_center.issue10.row_accounting.v1',
        'status': 'INCOMPLETE_OR_INVALID' if errors else 'ROW_ACCOUNTING_COMPLETE',
        'scope': 'PERSISTED_SOURCE_RESULT_ROWS_ONLY_NOT_POOL_ADMISSION',
        'trade_date': trade_date, 'stage_id': stage_id, 'source_status': source.get('status'),
        'requested_code_count': len(codes), 'persisted_row_count': len(rows),
        'persisted_unique_rows': len(observed), 'declared_missing_count': len(missing),
        'unaccounted_code_count': len(unaccounted), 'unaccounted_codes': sorted(unaccounted),
        'source_limitations': list(limitations) if isinstance(limitations, (list, tuple)) else [],
        'naive_row_timestamp_count': naive_count, 'naive_timestamp_assumption': 'Asia/Hong_Kong',
        'errors': errors, 'recommendation_status': 'RESEARCH_ONLY',
        'bar_series_verified': False, 'pool_membership_verified': False,
        'observation_pool_admitted': False, 'stage_selection_generated': False,
        'api_ui_verified': False, 'production_allowed': False,
        'buy_gate_updated': False, 'orders_sent': False, 'write_performed': False}


def inspect_files(*, root: Path, source_relative: str, source_sha256: str,
                  codes_relative: str, codes_sha256: str, trade_date: str, stage_id: str):
    io = SafeRoot(root)
    decoded = []
    for relative, expected in ((source_relative, source_sha256), (codes_relative, codes_sha256)):
        raw = io.read_bytes(relative)
        if not re.fullmatch(r'[0-9a-f]{64}', expected) or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'EVIDENCE_BYTE_SHA_MISMATCH:{relative}')
        decoded.append(json.loads(raw))
    return {**inspect_rows(decoded[0], decoded[1], trade_date=trade_date, stage_id=stage_id),
            'source_file_sha256': source_sha256, 'requested_codes_file_sha256': codes_sha256}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    for key in ('source-relative', 'source-sha256', 'codes-relative', 'codes-sha256', 'trade-date', 'stage-id'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_files(**vars(args))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f'evidence inspection refused: {error}\n')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] == 'ROW_ACCOUNTING_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
