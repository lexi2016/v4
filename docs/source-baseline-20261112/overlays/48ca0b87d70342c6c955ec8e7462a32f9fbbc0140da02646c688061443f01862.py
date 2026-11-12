"""Best-effort lifecycle wake hints. No notification I/O in a business lane.

The bounded queue is drained by a daemon thread created at module import,
before scheduler deadline checks. Hints never authorize business state.
"""
from __future__ import annotations
import atexit
import contextvars
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time
import sys
import re
import subprocess
from datetime import datetime, timezone

_pending = queue.Queue(maxsize=256)
_context = contextvars.ContextVar('runtime_graph_context', default={})
_failures = 0
_worker = None


def set_context(**fields):
    _context.set(dict(fields))


def notify(owner, node_id, business_date, phase, *, run_id=None, source_path=None):
    """Only an in-memory put; a failed or full notifier cannot fail business."""
    global _failures
    try:
        if not os.environ.get('V4_RUNTIME_GRAPH_INBOX'):
            return False
        if phase not in {'EXECUTOR_ENTERED', 'COMMITTED'}:
            return False
        fields = _context.get()
        caller = sys._getframe(1).f_code
        _pending.put_nowait({
            'schema_version': 'v4.runtime_graph_hint.v1', 'owner': str(owner),
            'node_id': str(node_id), 'business_date': str(business_date or fields.get('business_date') or ''),
            'phase': phase, 'run_id': str(run_id or fields.get('run_id') or ''),
            'slot':fields.get('slot'), 'owner_id':fields.get('owner_id'),
            'attempt':fields.get('attempt'),
            'caller_file':caller.co_filename, 'caller_function':caller.co_name,
            'parent_pid':os.getppid(),
            'source_path': str(source_path or fields.get('source_path') or ''),
            'pid': os.getpid(),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        })
        return True
    except Exception:
        _failures += 1
        return False


def process_identity(pid):
    try:
        if type(pid) is not int or pid<=0:
            return None
        out=subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart='],stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,timeout=.2,check=False,
                           env={**os.environ,'LC_ALL':'C','TZ':'UTC'})
        token=out.stdout.decode().strip()
        if out.returncode or not token:
            return None
        started=datetime.strptime(token,'%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc)
        return {'process_start_token':token,'process_started_at':started.isoformat()}
    except Exception:
        return None


def _persist(payload):
    root = Path(os.environ['V4_RUNTIME_GRAPH_INBOX'])
    if not root.is_absolute() or root.resolve() != root or root.is_symlink():
        raise ValueError('GRAPH_INBOX_UNSAFE')
    root.mkdir(parents=True, exist_ok=True)
    source = Path(payload['source_path'])
    if payload['phase'] == 'COMMITTED' and source.is_file() and not source.is_symlink():
        if source.stat().st_size <= 16 * 1024 * 1024:
            payload['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    identity = {k: payload.get(k) for k in ('owner', 'node_id', 'business_date', 'phase', 'run_id', 'source_path', 'source_sha256')}
    # Unidentified entries cannot deduplicate separate genuine executions.
    if not payload['run_id'] or payload['phase'] == 'EXECUTOR_ENTERED':
        identity['observed_at'] = payload['observed_at']
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if payload['phase']=='EXECUTOR_ENTERED':
        for field in ('owner','node_id','business_date'):
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',payload[field]):
                raise ValueError('ENTRY_OBSERVATION_SEGMENT_UNSAFE')
        birth=process_identity(payload['pid'])
        module=Path(payload['caller_file'])
        if not birth or module.resolve()!=module or module.is_symlink() or module.stat().st_size>16*1024*1024:
            raise ValueError('ENTRY_PROCESS_OR_MODULE_UNCONFIRMED')
        entry={**payload,**birth,'schema_version':'v4.runtime_execution_entry.v1',
               'caller_sha256':hashlib.sha256(module.read_bytes()).hexdigest()}
        folder=root.parent/'entry_observations'/payload['business_date']/payload['owner']/payload['node_id']
        if folder.resolve()!=folder:
            raise ValueError('ENTRY_OBSERVATION_ROOT_UNSAFE')
        folder.mkdir(parents=True,exist_ok=True)
        entry_raw=(json.dumps(entry,sort_keys=True,allow_nan=False)+'\n').encode()
        destination=folder/(key+'.json')
        with destination.open('xb') as stream:
            stream.write(entry_raw);stream.flush();os.fsync(stream.fileno())
        payload['entry_observation_path']=str(destination)
        payload['entry_observation_sha256']=hashlib.sha256(entry_raw).hexdigest()
    raw = (json.dumps(payload, sort_keys=True, allow_nan=False) + '\n').encode()
    tmp = root.parent / ('.graph-hint-' + key + '-' + str(os.getpid()) + '.tmp')
    with tmp.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, root / (key + '.json'))


def _drain():
    global _failures
    while True:
        payload = _pending.get()
        try:
            _persist(payload)
        except Exception:
            _failures += 1
        finally:
            _pending.task_done()


def flush(timeout=0.25):
    """Bounded process-exit grace after business completion, never a lane gate."""
    stop = time.monotonic() + timeout
    while _pending.unfinished_tasks and time.monotonic() < stop:
        time.sleep(0.001)
    return not _pending.unfinished_tasks


if os.environ.get('V4_RUNTIME_GRAPH_INBOX'):
    _worker = threading.Thread(target=_drain, name='graph-hints', daemon=True)
    _worker.start()
    atexit.register(flush)
