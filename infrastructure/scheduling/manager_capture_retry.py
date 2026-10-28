"""Bounded LIVE 1530 retry admission. No acquisition and no alternate scheduler.

The existing dispatcher claim serializes reserve_attempt. A durable start marker
counts an interrupted attempt even when no receipt was committed. Reads fail
closed on malformed/ambiguous ledger evidence; existing receipts are not edited.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot

POLICY = 'v4.manager_capture_retry.10s.3attempts.v1'
HK = ZoneInfo('Asia/Hong_Kong')
MAX_ATTEMPTS = 3
RETRY_SECONDS = 10
RETRYABLE = frozenset({'UPSTREAM_NOT_READY', 'NETWORK', 'EXTERNAL_SOURCE'})
SAFETY = ('production_allowed', 'buy_gate_updated', 'orders_sent')


def _digest(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != 'ledger_sha256'}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _clock(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('CAPTURE_CLOCK_NOT_AWARE')
    return result.astimezone(HK)


def window(date: str) -> tuple[datetime, datetime]:
    if not isinstance(date, str) or not re.fullmatch(r'\d{8}', date):
        raise ValueError('CAPTURE_DATE_INVALID')
    start = datetime.strptime(date, '%Y%m%d').replace(hour=15, minute=30, tzinfo=HK)
    return start, start + timedelta(minutes=2)


def retry_metadata(date: str, attempt: int, finished_at: datetime) -> dict:
    start, end = window(date)
    finish = _clock(finished_at)
    if type(attempt) is not int or not 1 <= attempt <= MAX_ATTEMPTS:
        raise ValueError('CAPTURE_ATTEMPT_INVALID')
    status = 'RETRY_SCHEDULED'
    retry = finish + timedelta(seconds=RETRY_SECONDS)
    if attempt >= MAX_ATTEMPTS:
        status = 'ATTEMPT_BUDGET_EXHAUSTED'
    elif not start <= finish < end or retry >= end:
        status = 'RETRY_OUTSIDE_WINDOW'
    return {'policy': POLICY, 'attempt': attempt, 'max_attempts': MAX_ATTEMPTS,
            'deadline': end.isoformat(), 'status': status,
            'retry_after': retry.isoformat() if status == 'RETRY_SCHEDULED' else ''}


def _path(root: Path, relative: str) -> Path:
    root = Path(root)
    path = root / relative
    if '..' in path.parts:
        raise ValueError('LEDGER_PATH_INVALID')
    # Inspect ancestors as well as descendants. resolve() alone follows symlinks.
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('LEDGER_SYMLINK')
    return path


def _read(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError('LEDGER_FILE_INVALID')
    # O_NOFOLLOW closes the final-component replacement window on supported hosts.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as f:
        data = f.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise ValueError('LEDGER_FILE_TOO_LARGE')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('LEDGER_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError('LEDGER_NOT_OBJECT')
    return value


def _identity(p: dict, date: str) -> None:
    if any(p.get(k) != v for k, v in {'mode': 'LIVE', 'slot': '1530',
                                    'business_date': date, 'scheduled_date': date,
                                    'target_date': date}.items()):
        raise ValueError('LEDGER_IDENTITY')
    if not re.fullmatch(r'[0-9a-f]{32}', str(p.get('run_id', ''))):
        raise ValueError('LEDGER_RUN_ID')


def _evidence(root: Path, date: str, now: datetime) -> tuple[list[dict], list[dict]]:
    receipts: list[dict] = []
    directory = _path(root, f'receipts/live/{date}/1530')
    if directory.exists():
        paths = list(directory.iterdir())
        if len(paths) > 32:
            raise ValueError('LEDGER_TOO_MANY_RECEIPTS')
        for path in paths:
            _path(root, str(path.relative_to(root)))
            if not path.name.endswith('.dispatch-receipt.json'):
                raise ValueError('LEDGER_UNEXPECTED_FILE')
            p = _read(path)
            _identity(p, date)
            if (p.get('schema_version') != 'v3_5.dispatch.v1'
                    or path.name != p['run_id'] + '.dispatch-receipt.json'
                    or p.get('ledger_sha256') != _digest(p)
                    or any(p.get(k) is not False for k in SAFETY)
                    or p.get('selected_workload_ids') != ['hourly_research']
                    or _clock(p['finished_at']) > now):
                raise ValueError('LEDGER_RECEIPT_INVALID')
            receipts.append(p)
    # Require a complete, linear original receipt hash chain, not mtime order.
    ordered: list[dict] = []
    previous = ''
    while receipts:
        next_items = [p for p in receipts if p.get('prev_ledger_sha256') == previous]
        if len(next_items) != 1:
            raise ValueError('LEDGER_CHAIN_INVALID')
        p = next_items[0]; ordered.append(p); receipts.remove(p)
        previous = p['ledger_sha256']
    if len({p['run_id'] for p in ordered}) != len(ordered):
        raise ValueError('LEDGER_DUPLICATE_RUN')
    starts: list[dict] = []
    directory = _path(root, f'capture_attempts/live/{date}/1530')
    if directory.exists():
        paths = list(directory.iterdir())
        if len(paths) > MAX_ATTEMPTS:
            raise ValueError('LEDGER_TOO_MANY_STARTS')
        for path in paths:
            _path(root, str(path.relative_to(root)))
            p = _read(path); _identity(p, date)
            n = p.get('attempt')
            if (p.get('schema_version') != POLICY or type(n) is not int
                    or not 1 <= n <= MAX_ATTEMPTS or path.name != f'{n}.json'
                    or p.get('ledger_sha256') != _digest(p)
                    or any(p.get(k) is not False for k in SAFETY)
                    or not window(date)[0] <= _clock(p['started_at']) < window(date)[1]
                    or _clock(p['started_at']) > now):
                raise ValueError('LEDGER_START_INVALID')
            starts.append(p)
        starts.sort(key=lambda p: p['attempt'])
        if len({p['run_id'] for p in starts}) != len(starts):
            raise ValueError('LEDGER_DUPLICATE_START')
    return ordered, starts


def _alive(pid: object) -> bool:
    if type(pid) is not int or pid <= 0:
        raise ValueError('LEDGER_PID_INVALID')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def capture_state(root: Path, date: str, now: datetime, *, claimed_run_id: str | None = None) -> dict:
    """Read-only admission. A due result still requires original dispatch lock."""
    def state(status, attempts=0, retry_after=''):
        return {'policy': POLICY, 'status': status, 'due': status == 'DUE',
                'attempts': attempts, 'retry_after': retry_after, 'deadline': end.isoformat()}
    try:
        start, end = window(date); now = _clock(now)
    except (ValueError, TypeError, AttributeError):
        return {'policy': POLICY, 'status': 'CLOCK_INVALID', 'due': False, 'attempts': 0,
                'retry_after': '', 'deadline': ''}
    if now.strftime('%Y%m%d') != date or not start <= now < end:
        return state('WINDOW_CLOSED')
    try:
        root = Path(root); _path(root, '')
        receipts, starts = _evidence(root, date, now)
        runs = {p['run_id'] for p in receipts + starts}; count = len(runs)
        if count > MAX_ATTEMPTS:
            return state('ATTEMPT_BUDGET_EXHAUSTED', count)
        # Never reinterpret a prior success or terminal failure as retryable.
        for p in receipts:
            if p.get('status') != 'FAILED' or p.get('failure_class') not in RETRYABLE:
                return state('TERMINAL_RECEIPT', count)
        if count >= MAX_ATTEMPTS:
            return state('ATTEMPT_BUDGET_EXHAUSTED', count)
        claim_path = _path(root, f'claims/live/{date}/1530/dispatch.claim.json')
        if claim_path.exists():
            claim = _read(claim_path); _identity(claim, date)
            if claim['run_id'] == claimed_run_id and claim.get('pid') == os.getpid():
                pass  # Caller has just acquired the original dispatch claim.
            elif _alive(claim.get('pid')):
                return state('IN_FLIGHT', count)
            elif claim['run_id'] not in {p['run_id'] for p in starts}:
                return state('UNTRACKED_INTERRUPTED_CLAIM', count)
        times = []
        for p in receipts:
            if not p.get('retry_after'):
                return state('TERMINAL_RECEIPT', count)
            retry = _clock(p['retry_after'])
            if retry < _clock(p['finished_at']):
                raise ValueError('LEDGER_RETRY_REVERSED')
            if 'capture_retry' in p:
                expected = retry_metadata(date, p['attempt'], _clock(p['finished_at']))
                if p['capture_retry'] != expected or p['retry_after'] != expected['retry_after']:
                    raise ValueError('LEDGER_RETRY_POLICY_MISMATCH')
            if retry >= end:
                return state('RETRY_OUTSIDE_WINDOW', count, retry.isoformat())
            times.append(retry)
        completed = {p['run_id'] for p in receipts}
        times.extend(_clock(p['started_at']) + timedelta(seconds=RETRY_SECONDS)
                     for p in starts if p['run_id'] not in completed)
        next_at = max(times) if times else start
        if next_at >= end:
            return state('RETRY_OUTSIDE_WINDOW', count, next_at.isoformat())
        return state('DUE' if now >= next_at else 'RETRY_WAIT', count, next_at.isoformat())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return state('LEDGER_INVALID')


def reserve_attempt(root: Path, date: str, run_id: str, now: datetime) -> int:
    """Reserve under the existing dispatch claim with no-replace SafeRoot I/O.

    Keep the project's descriptor-pinned ancestry boundary: a checked pathname
    plus leaf O_NOFOLLOW is not sufficient against parent replacement. A fully
    flushed temporary record is published without replacing an existing marker.
    A post-publication read must still resolve through the safe root; a changed
    namespace is rejected, and an uncertain committed marker is never deleted
    (doing so could replenish the attempt budget after interruption).
    """
    now = _clock(now); start, end = window(date)
    if not start <= now < end or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('CAPTURE_RESERVATION_INVALID')
    root = Path(root)
    if not capture_state(root, date, now, claimed_run_id=run_id)['due']:
        raise ValueError('CAPTURE_ADMISSION_CHANGED_UNDER_CLAIM')
    receipts, starts = _evidence(root, date, now)
    runs = {p['run_id'] for p in receipts + starts}
    if run_id in runs or len(runs) >= MAX_ATTEMPTS:
        raise ValueError('CAPTURE_ATTEMPT_BUDGET')
    n = len(runs) + 1
    p = dict(schema_version=POLICY, run_id=run_id, attempt=n, pid=os.getpid(),
             mode='LIVE', slot='1530', business_date=date, scheduled_date=date, target_date=date,
             started_at=now.isoformat(), production_allowed=False, buy_gate_updated=False, orders_sent=False)
    p['ledger_sha256'] = _digest(p)
    relative = f'capture_attempts/live/{date}/1530/{n}.json'
    raw = json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    store = SafeRoot(root)
    store.write_bytes(relative, raw, require_absent=True)
    if store.read_bytes(relative, max_bytes=256 * 1024) != raw:
        raise ValueError('CAPTURE_RESERVATION_READBACK_MISMATCH')
    return n
