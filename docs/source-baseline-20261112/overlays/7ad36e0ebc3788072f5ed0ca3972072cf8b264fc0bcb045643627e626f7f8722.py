"""V4 graph envelope and safe readers, independent of old Windows topology."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

FLAGS = {'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
SCHEMA = 'v4.runtime_graph_snapshot.v1'
MAX_BYTES = 16 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path, root=None, *, max_bytes=MAX_BYTES):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('EVIDENCE_PATH_UNSAFE')
    if root is not None and not path.is_relative_to(Path(root).resolve(strict=True)):
        raise ValueError('EVIDENCE_OUTSIDE_ROOT')
    with path.open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('EVIDENCE_TOO_LARGE')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('EVIDENCE_NOT_OBJECT')
    return value, raw


def safe(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FLAGS and child is not False:
                raise ValueError('UNSAFE_EVIDENCE')
            safe(child)
    elif isinstance(value, list):
        for child in value:
            safe(child)


def load_config(path=None):
    path = path or os.environ.get('V4_RUNTIME_GRAPH_CONFIG')
    if not path:
        raise ValueError('GRAPH_CONFIG_NOT_BOUND')
    config, raw = read_json(path)
    if config.get('schema_version') != 'v4.runtime_graph_config.v1':
        raise ValueError('GRAPH_CONFIG_SCHEMA')
    safe(config)
    config['_sha256'] = sha(raw)
    return config


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() != path.parent or path.is_symlink():
        raise ValueError('GRAPH_OUTPUT_UNSAFE')
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()
    tmp = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.tmp')
    with tmp.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)
    return sha(raw)


def state_root(config):
    root = Path(config['graph_root'])
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('GRAPH_ROOT_UNSAFE')
    state = root / 'runtime_graph' / 'v4'
    if state.resolve() != state:
        raise ValueError('GRAPH_STATE_ROOT_UNSAFE')
    return state


def read_snapshot(config, *, now=None):
    """Collection age is diagnostic; it never expires valid business proof."""
    root = state_root(config)
    now = now or datetime.now(timezone.utc)
    try:
        value, raw = read_json(root / 'snapshot.json', root)
        if value.get('schema_version') != SCHEMA or value.get('config_sha256') != config['_sha256']:
            raise ValueError('GRAPH_SNAPSHOT_BINDING_MISMATCH')
        safe(value)
        value['snapshot_sha256'] = sha(raw)
        value['collection_age_seconds'] = max(0, (now - datetime.fromisoformat(value['last_collection_at'])).total_seconds())
        for node in value.get('nodes', []):
            node['evidence_freshness'] = 'AS_RECORDED'
            if node.get('valid_until'):
                if now >= datetime.fromisoformat(node['valid_until']):
                    node['evidence_freshness'] = 'EXPIRED'
            observation=node.get('execution_observation',{})
            if observation.get('state')=='RUNNING_VERIFIED_OBSERVATION':
                from infrastructure.runtime_graph.notifications import process_identity
                birth=process_identity(observation.get('pid'))
                terminal=Path(observation.get('terminal_receipt_path',''))
                if (not terminal.is_absolute() or not terminal.is_relative_to(Path(config['ledger_root']))
                        or terminal.resolve()!=terminal):
                    observation['state']='CANNOT_CONFIRM'
                    node['execution_phase']='CANNOT_CONFIRM'
                elif terminal.exists():
                    observation['state']='TERMINAL_PRESENT_REVALIDATION_REQUIRED'
                    node['execution_phase']='CANNOT_CONFIRM_NEEDS_TERMINAL_REVALIDATION'
                elif not birth or birth['process_start_token']!=observation.get('process_start_token'):
                    observation['state']='PID_ENDED_OR_REUSED'
                    node['execution_phase']='NOT_RUNNING_PID_IDENTITY_UNCONFIRMED'
        try:
            monitor, _ = read_json(root / 'monitor.json', root)
        except (OSError, ValueError):
            monitor = {'state': 'CANNOT_CONFIRM', 'reason': 'MONITOR_RECEIPT_MISSING'}
        inbox = Path(config['inbox'])
        pending = sorted(inbox.glob('*.json'))[:1025] if inbox.is_dir() else []
        value['monitor'] = {**monitor, 'pending_count': len(pending), 'idle_pid_required': False}
        failed = list((root / 'failed').glob('*.json'))[:1025]
        value['monitor']['failed_pending_count'] = len(failed)
        if failed:
            value['monitor']['state'] = 'FAILED'
        if config.get('monitor_enabled') is not True:
            value['monitor']['state'] = 'STOPPED_PENDING_REPAIR'
        elif pending:
            value['monitor']['state'] = 'PENDING'
            # File times describe only queue transport, never business time.
            value['monitor']['oldest_pending_age_seconds'] = max(0, now.timestamp() - min(p.stat().st_mtime for p in pending))
            if value['monitor']['oldest_pending_age_seconds'] > 30:
                value['monitor']['state'] = 'BACKLOG'
        if config.get('monitor_enabled') is True:
            value['monitor']['registration'] = monitor_registration()
            if value['monitor']['registration'] != 'LOADED':
                value['monitor']['state'] = 'STOPPED_OR_UNCONFIRMED'
        value['is_current'] = value['monitor'].get('state') not in {'STOPPED_PENDING_REPAIR', 'STOPPED_OR_UNCONFIRMED', 'FAILED', 'CANNOT_CONFIRM', 'BACKLOG'}
        if value.get('business_date') != now.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'):
            value['is_current'] = False
            value['view_date_status'] = 'HISTORICAL_ASOF'
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'schema_version': SCHEMA, 'is_current': False, 'status': 'CANNOT_CONFIRM',
                'reason': str(exc), 'monitor': {'state': 'STOPPED_PENDING_REPAIR' if not config.get('monitor_enabled') else 'CANNOT_CONFIRM'},
                'nodes': [], **FLAGS}


def monitor_registration():
    """Read-only fixed-label check. Idle PID absence does not imply failure."""
    try:
        result = subprocess.run(['/bin/launchctl', 'print', f'gui/{os.getuid()}/com.lexi.v4.runtime-graph'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1, check=False)
        if result.returncode != 0:
            return 'UNLOADED'
        disabled = subprocess.run(['/bin/launchctl', 'print-disabled', f'gui/{os.getuid()}'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1, check=False)
        if disabled.returncode != 0:
            return 'CANNOT_CONFIRM'
        if b'"com.lexi.v4.runtime-graph" => true' in disabled.stdout:
            return 'DISABLED'
        return 'LOADED'
    except (OSError, subprocess.TimeoutExpired):
        return 'CANNOT_CONFIRM'


def read_events(config, node_id, limit, *, scan_limit=2000):
    if type(scan_limit) is not int or not 1 <= scan_limit <= 10000:
        raise ValueError('GRAPH_EVENT_SCAN_LIMIT_INVALID')
    root = state_root(config) / 'events'
    events = []
    # Bounded latest transport history. No writer or business call on GET.
    paths = sorted(root.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:scan_limit] if root.is_dir() else []
    for path in paths:
        try:
            event, _ = read_json(path, root)
            hint = event.get('hint', {})
            mapped = 'stage:' + str(hint.get('node_id')) if hint.get('owner') == 'STAGE_CENTER' else hint.get('node_id')
            if mapped == node_id:
                events.append(event)
                if len(events) >= limit:
                    break
        except (OSError, ValueError):
            continue
    return {'node_id': node_id, 'events':events, 'status':'OBSERVED', **FLAGS}
