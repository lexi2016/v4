"""Recover eligible original-slot jobs from existing durable observations.

Read-only, current-day, per-job recovery. A corrupt or ambiguous latest entry
quarantines that logical job; another valid job remains independently usable.
Claims, lane locks, markets and business execution remain owned by the existing
scheduler/dispatcher.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Callable

QUEUED = frozenset({'QUEUED', 'QUEUED_BEHIND', 'CHILD_START_FAILED'})
TERMINAL = frozenset({'FINISHED', 'FINISHED_CANNOT_CONFIRM', 'EXPIRED', 'CLAIM_OR_RECEIPT_BLOCKED'})
SAFETY = ('production_allowed', 'buy_gate_updated', 'orders_sent')


def _digest(value):
    body={k:v for k,v in value.items() if k!='ledger_sha256'}
    return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def recover_queued_jobs(root: Path, moment: datetime, *, slots, lane_for: Callable, cutoff_for: Callable):
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError('QUEUE_HANDOVER_CLOCK_REQUIRES_TIMEZONE')
    root=Path(root);day=moment.strftime('%Y%m%d');branch=root/'scheduler_observations/live'/day
    jobs={};blocked={}
    for slot in slots:
        key=(day,slot);directory=branch/slot
        try:
            for p in (root,root/'scheduler_observations',root/'scheduler_observations/live',branch,directory):
                if p.is_symlink():raise ValueError('QUEUE_HANDOVER_PATH_ALIAS')
            if not directory.exists():continue
            if not directory.is_dir():raise ValueError('QUEUE_HANDOVER_PATH_INVALID')
            paths=list(directory.glob('*.observation.json'))
            if not paths:continue
            if any(p.is_symlink() or not p.is_file() for p in paths):
                raise ValueError('QUEUE_HANDOVER_OBSERVATION_ALIAS')
            # Publication order is the existing atomic file's nanosecond mtime.
            # Never parse an older valid record after a newer corrupt record.
            latest_time=max(p.stat().st_mtime_ns for p in paths)
            latest=[p for p in paths if p.stat().st_mtime_ns==latest_time]
            if len(latest)!=1:raise ValueError('QUEUE_HANDOVER_LATEST_AMBIGUOUS')
            p=latest[0]
            if p.stat().st_size>65536:raise ValueError('QUEUE_HANDOVER_OBSERVATION_OVERSIZED')
            raw=p.read_bytes();value=json.loads(raw)
            if not isinstance(value,dict) or value.get('ledger_sha256')!=_digest(value):
                raise ValueError('QUEUE_HANDOVER_OBSERVATION_HASH_INVALID')
            if (value.get('schema_version')!='v4.scheduler_observation.v1'
                    or value.get('business_date')!=day or value.get('slot')!=slot
                    or value.get('lane')!=lane_for(slot)
                    or any(value.get(k) is not False for k in SAFETY)):
                raise ValueError('QUEUE_HANDOVER_OBSERVATION_IDENTITY_INVALID')
            state=value.get('status')
            if state in TERMINAL:continue
            if state not in QUEUED:raise ValueError('QUEUE_HANDOVER_OWNER_UNRESOLVED')
            stamps={name:datetime.fromisoformat(value[name]) for name in ['planned_at','queued_at','cutoff_at','observed_at']}
            if any(x.tzinfo is None or x.utcoffset() is None for x in stamps.values()):
                raise ValueError('QUEUE_HANDOVER_TIMEZONE_MISSING')
            planned=datetime.strptime(day+slot,'%Y%m%d%H%M').replace(tzinfo=moment.tzinfo)
            if stamps['planned_at']!=planned or stamps['cutoff_at']!=cutoff_for(day,slot):
                raise ValueError('QUEUE_HANDOVER_ORIGINAL_SLOT_OR_CUTOFF_CHANGED')
            if stamps['queued_at']>stamps['observed_at'] or stamps['observed_at']>moment:
                raise ValueError('QUEUE_HANDOVER_OBSERVATION_TIME_INVALID')
            if moment>stamps['cutoff_at']:continue
            job={'business_date':day,'slot':slot,'planned_at':value['planned_at'],
                 'queued_at':value['queued_at'],'cutoff_at':value['cutoff_at']}
            if state=='CHILD_START_FAILED':
                job['next_start_at']=(stamps['observed_at']+timedelta(seconds=300)).isoformat()
            jobs[key]=job
        except (OSError,ValueError,TypeError,KeyError,UnicodeError) as error:
            blocked[key]=str(error) if str(error).startswith('QUEUE_HANDOVER_') else 'QUEUE_HANDOVER_OBSERVATION_INVALID'
    return jobs,blocked
