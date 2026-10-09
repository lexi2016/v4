"""Plan verified close-review slots; never execute jobs or certify their inputs.

A slot key identifies an opportunity to run. The shared daily logical key is
not an executed run id and cannot, by itself, prevent duplicate calculation.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import types

from .composition import no_symlinks
from .contracts import aware
from .digests import sha256_json

BASE = Path(__file__).resolve().parents[2]
SOURCE_ROOT = BASE / 'vendor' / 'daily_schedule_baseline' / 'contracts'
PINS = {
    'trading_calendar.py': '584f28d18273a8824c5f68a701aa4404123b5c71900caada3e2772828991ee8f',
    'market_calendar_2026.json': '9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb',
    'runtime_workloads.json': '7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef',
}
OWNERS = (
    ('a_share_close_review', 'A', 'a_share', 'A_SHARE_TRADE_DAY'),
    ('hk_connect_close_review', 'HK', 'hk_securities', 'HK_SECURITIES_TRADE_DAY'),
)
TZ = timezone(timedelta(hours=8))
_LOCK = threading.RLock()


class _CalendarBytes:
    """Supply pinned bytes to the original parser without a second file read."""
    def __init__(self, raw):
        self.raw = raw

    def read_text(self, *, encoding):
        return self.raw.decode(encoding)


def _sources():
    result = {}
    for name, expected in PINS.items():
        path = no_symlinks(SOURCE_ROOT / name)
        with path.open('rb') as stream:
            raw = stream.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('DAILY_SCHEDULE_SOURCE_IDENTITY')
        result[name] = raw
    return result


def _market_states(sources, target):
    # Dataclasses require their module to exist during class construction.
    # Serialize the short isolated load and restore any previous registration.
    name = '_v5_daily_close_calendar'
    with _LOCK:
        previous = sys.modules.get(name)
        module = types.ModuleType(name)
        module.__file__ = str(SOURCE_ROOT / 'trading_calendar.py')
        sys.modules[name] = module
        try:
            exec(compile(sources['trading_calendar.py'], module.__file__, 'exec'), module.__dict__)
            module.CALENDAR_PATH = _CalendarBytes(sources['market_calendar_2026.json'])
            calendar = module.load_market_calendar()
            return {key: state.value for key, state in module.resolve_market_states(calendar, target).items()}
        finally:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def plan_close_day(now):
    instant = aware(now).astimezone(TZ)
    target = instant.strftime('%Y%m%d')
    sources = _sources()
    states = _market_states(sources, target)
    catalog = json.loads(sources['runtime_workloads.json'])
    workloads = catalog['workloads']
    jobs = []
    for owner, market, calendar_key, policy in OWNERS:
        candidates = [row for row in workloads if row.get('workload_id') == owner]
        if len(candidates) != 1:
            raise ValueError('DAILY_SCHEDULE_OWNER_IDENTITY')
        row = candidates[0]
        if (row.get('enabled') is not True or row.get('run_policy') != policy
                or row.get('session_requirement') != 'POST_CLOSE'
                or row.get('target_date_role') != 'BUSINESS_DATE'):
            raise ValueError('DAILY_SCHEDULE_POLICY_IDENTITY')
        slots = row['slots']
        if not isinstance(slots, list) or not slots or len(set(slots)) != len(slots):
            raise ValueError('DAILY_SCHEDULE_SLOT_IDENTITY')
        logical = {'module_id': owner, 'market': market, 'target_date': target}
        state = states[calendar_key]
        for slot in slots:
            if not isinstance(slot, str) or len(slot) != 4 or not slot.isascii() or not slot.isdigit():
                raise ValueError('DAILY_SCHEDULE_SLOT_IDENTITY')
            hour, minute = int(slot[:2]), int(slot[2:])
            if hour > 23 or minute > 59:
                raise ValueError('DAILY_SCHEDULE_SLOT_IDENTITY')
            scheduled = None
            if state == 'UNKNOWN':
                status = 'CALENDAR_UNKNOWN'
            elif state == 'NON_TRADING_DAY':
                status = 'NON_TRADING_DAY'
            elif state != 'FULL_TRADING_DAY':
                # The catalog has full-day slots only. A half-day session does
                # not prove a half-day trigger or collector binding exists.
                status = 'SCHEDULE_BINDING_UNVERIFIED'
            else:
                scheduled = datetime(instant.year, instant.month, instant.day, hour, minute, tzinfo=TZ)
                status = 'DUE' if instant >= scheduled else 'WAITING_TIME'
            jobs.append({
                **logical, 'slot': slot,
                'logical_run_key': sha256_json(logical),
                'job_key': sha256_json({**logical, 'slot': slot}),
                'scheduled_at': scheduled.isoformat() if scheduled else None,
                'market_state': state, 'connect_state': states['hk_connect'],
                'run_policy': policy, 'status': status,
                'run_id': None, 'run_status': 'NOT_RUN',
                'input_admission': 'NOT_CHECKED', 'deduplication_checked': False,
            })
    return {
        'schema_version': 'v5.daily_close_plan.v1',
        'planned_for': instant.isoformat(), 'target_date': target,
        'schedule_source_sha256': PINS['runtime_workloads.json'],
        'calendar_source_sha256': PINS['market_calendar_2026.json'],
        'calendar_code_sha256': PINS['trading_calendar.py'],
        'execution_performed': False, 'natural_verified': False, 'jobs': jobs,
    }
