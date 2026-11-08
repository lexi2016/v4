#!/usr/bin/env python3
"""Capacity heartbeat and explicit directory inventories. Writes audit history only."""
import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import os
import hashlib
from pathlib import Path
import uuid

BASE = Path(__file__).resolve().parent
UTC = dt.timezone.utc
PERIODS = {'24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400}


def threshold(percent):
    if not 0 <= percent <= 100:
        raise ValueError('available percent must be between 0 and 100')
    if percent > 30:
        return 'HEALTHY'
    if percent >= 20:
        return 'WATCH'
    if percent >= 15:
        return 'WARNING'
    if percent >= 10:
        return 'LOW'
    return 'CRITICAL'


def load_history(path):
    rows, errors = [], []
    if not path.exists():
        return rows, errors
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('history row is not an object')
                rows.append(row)
            except (ValueError, TypeError) as exc:
                errors.append({'line': number, 'error': str(exc)})
    return rows, errors


def historical_changes(current, rows):
    result = {}
    for label, seconds in PERIODS.items():
        target = current['timestamp'] - seconds
        # Require a baseline at least this old, within 20% of the period.
        candidates = [r for r in rows if isinstance(r.get('timestamp'), (int, float))
                      and target - seconds * .2 <= r['timestamp'] <= target
                      and r.get('volume_path') == current['volume_path']
                      and r.get('total_bytes') == current['total_bytes']
                      and isinstance(r.get('available_bytes'), (int, float))]
        if not candidates:
            result[label] = {'status': 'UNKNOWN', 'reason': 'No matching baseline at least this old within 20% tolerance'}
            continue
        old = max(candidates, key=lambda r: r['timestamp'])
        result[label] = {'status': 'KNOWN', 'baseline_utc': old.get('observed_utc'),
                         'elapsed_seconds': current['timestamp'] - old['timestamp'],
                         'available_change_bytes': current['available_bytes'] - old['available_bytes'],
                         'space_consumed_bytes': old['available_bytes'] - current['available_bytes']}
    return result


def capacity_snapshot(volume, now=None):
    now = now or dt.datetime.now(UTC)
    info = os.statvfs(volume)
    unit = info.f_frsize or info.f_bsize
    total = info.f_blocks * unit
    if total <= 0:
        raise ValueError('Filesystem returned zero capacity')
    available = info.f_bavail * unit
    percent = available / total * 100
    return dict(observed_utc=now.isoformat(), timestamp=now.timestamp(), volume_path=os.path.realpath(volume),
                total_bytes=total, available_bytes=available, filesystem_free_bytes=info.f_bfree * unit,
                available_percent=round(percent, 4), threshold=threshold(percent),
                reclaimable_bytes='UNKNOWN', source='os.statvfs; APFS shared/purgeable/snapshots not reconciled')


def append_json(path, row):
    with path.open('a') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def save_json(path, row):
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w') as stream:
        json.dump(row, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temp, path)


def run(config, mode):
    history = Path(config.get('history_dir', str(BASE / 'history'))).expanduser().resolve()
    audit_root = Path(config.get('audit_root', str(BASE.parent))).expanduser().resolve()
    if history != audit_root and audit_root not in history.parents:
        raise ValueError('History output must stay inside Mac_Storage_Audit')
    history.mkdir(parents=True, exist_ok=True)
    with (history / 'monitor.lock').open('a') as lock:
        # Lock affects this audit writer only; it does not stop any service/process.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows, errors = load_history(history / 'capacity.jsonl')
        snapshot = capacity_snapshot(config.get('volume_path', '/'))
        snapshot['historical_changes'] = historical_changes(snapshot, rows)
        snapshot['mode'] = mode
        snapshot['history_parse_errors'] = errors
        snapshot['source_writes'] = False
        if not (history / 'capacity.jsonl').exists() or (history / 'capacity.jsonl').stat().st_size < config.get('legacy_history_append_cap_bytes', 8 * 1024**2):
            append_json(history / 'capacity.jsonl', snapshot)
        else:
            snapshot['legacy_append'] = 'SUPPRESSED_PROTECTED_HISTORY_AT_CAP'
        report = {'capacity': snapshot, 'directory_inventories': [],
                  'directory_growth_status': 'UNKNOWN: daily capacity mode does not scan directories'}
        if mode != 'daily':
            # Existing weekly/monthly path lists are historical configuration,
            # not authorization for an unbounded per-file scan in this entry.
            report['directory_growth_status'] = 'SUPPRESSED_DEEP_INVENTORY_REQUIRES_SEPARATE_BUDGETED_TASK'
        save_json(history / 'latest.json', report)
        report['ordinary_retention'] = ordinary_retention(config, report)
        return report


OWNER = 'v4.mac_storage_monitor.ordinary.v1'


def _safe_owned_path(root, name):
    path = root / name
    if Path(name).name != name or path.is_symlink() or not path.is_file():
        raise ValueError('ORDINARY_PATH_OR_TYPE_DRIFT:' + name)
    return path


def ordinary_retention(config, report, *, now=None):
    """14 ordinary detailed RUNS, 90 calendar days of lightweight trends.

    Only positively owned files created by this version in the explicitly bound
    new directory qualify. Legacy history/inventories and unique errors do not.
    The existing scheduler calls this function; it introduces no timer.
    """
    rule = config.get('ordinary_retention')
    if not rule:
        return {'status': 'NOT_CONFIGURED', 'deleted_bytes': 0}
    root = Path(rule['root']).expanduser()
    approved = Path(rule['approved_root']).expanduser()
    audit = Path(config['audit_root']).resolve()
    if (not root.is_absolute() or root != approved or '..' in root.parts
            or audit not in root.parents or any(p.is_symlink() for p in [root, *root.parents])):
        raise ValueError('ORDINARY_ROOT_BINDING_FAILED')
    root.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.now(UTC)
    marker = root / 'ownership.json'
    identity = {'owner': OWNER, 'root': str(root), 'authorization': 'FUTURE_ORDINARY_REPORTS_ONLY'}
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text()) != identity:
            raise ValueError('ORDINARY_OWNERSHIP_DRIFT')
    else:
        # Never adopt pre-existing contents into the new rotation scope.
        if list(root.iterdir()):
            raise ValueError('ORDINARY_ROOT_PREEXISTS_UNOWNED')
        save_json(marker, identity)
    lockpath = root / 'retention.lock'
    if lockpath.is_symlink():
        raise ValueError('ORDINARY_LOCK_ALIAS')
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        index = root / 'index.json'
        if index.is_symlink():
            raise ValueError('ORDINARY_INDEX_ALIAS')
        state = json.loads(index.read_text()) if index.exists() else {'owner': OWNER, 'reports': []}
        if state.get('owner') != OWNER:
            raise ValueError('ORDINARY_INDEX_OWNER')
        cap = min(int(rule.get('max_bytes', 16 * 1024**2)), 32 * 1024**2)
        used = sum(p.stat().st_size for p in root.iterdir() if p.is_file() and not p.is_symlink())
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True) + '\n').encode()
        rows, errors = load_history(root / 'trend.jsonl')
        if errors:
            return {'status': 'SUPPRESSED_INVALID_TREND_PRESERVED', 'errors': errors, 'deleted_bytes': 0}
        dry = rule.get('dry_run', True) or rule.get('allow_future_owned_ordinary_rotation') is not True
        protected = set(rule.get('protected_report_ids', []))
        # Error/acceptance/recovery reports never become ordinary candidates.
        critical = bool(report.get('critical_evidence') or report['capacity'].get('history_parse_errors')
                        or report.get('directory_history_parse_errors'))
        name = now.strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex[:8] + '.json'
        if len(raw) > 64 * 1024:
            return {'status': 'SUPPRESSED_OWN_BUDGET_PROTECTED_EVIDENCE_RETAINED', 'used_bytes': used, 'cap_bytes': cap, 'deleted_bytes': 0}
        path = root / name
        record = dict(name=name, timestamp=now.timestamp(), critical=critical,
                      sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), status='PREPARED')
        state['reports'].append(record)
        light = {key: report['capacity'][key] for key in ('observed_utc', 'timestamp', 'volume_path', 'total_bytes', 'available_bytes', 'threshold')}
        rows.append(light)
        cutoff = now.timestamp() - 90 * 86400
        kept = [row for row in rows if isinstance(row.get('timestamp'), (int, float)) and row['timestamp'] >= cutoff]
        if any(not isinstance(row.get('timestamp'), (int, float)) for row in rows):
            raise ValueError('ORDINARY_TREND_INVALID_TIMESTAMP')
        trend_raw = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in (rows if dry else kept)).encode()
        trend_allowed = len(trend_raw) <= 8 * 1024**2
        def size(value):
            # Exact save_json encoding, including its final newline.
            return len((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
        old_index = index.stat().st_size if index.exists() else 0
        old_trend_path = root / 'trend.jsonl'
        old_trend = old_trend_path.stat().st_size if old_trend_path.exists() else 0
        prepared_bytes = size(state)
        record['status']='COMMITTED'
        committed_bytes = size(state)
        possible = sorted([row for row in state['reports'] if row['status']=='COMMITTED'
                           and not row['critical'] and row['name'] not in protected],
                          key=lambda row:(row['timestamp'],row['name']))
        possible = possible[:-14] if len(possible)>14 else []
        # Reserve the actual entire replacement index, including worst-case
        # bounded failure text for every potential candidate. Existing critical
        # records cannot be discarded to make maintenance fit.
        failure_state=json.loads(json.dumps(state))
        possible_names={row['name'] for row in possible}
        for row in failure_state['reports']:
            if row['name'] in possible_names:row['rotation_error']='\x00'*512
        final_index_bound=size(failure_state)
        after_prepared=used-old_index+prepared_bytes
        after_commit=used-old_index+committed_bytes+len(raw)
        after_trend=after_commit-old_trend+len(trend_raw) if trend_allowed else after_commit
        peak=max(used+prepared_bytes,
                 after_prepared+len(raw)+committed_bytes,
                 after_commit+(len(trend_raw) if trend_allowed else 0),
                 after_trend+final_index_bound)
        if peak > cap:
            return dict(status='SUPPRESSED_OWN_BUDGET_PROTECTED_EVIDENCE_RETAINED',
                        used_bytes=used,cap_bytes=cap,maintenance_peak_bytes=peak,deleted_bytes=0)
        # Ownership intent precedes the report. An interrupted PREPARED record
        # is preserved, never adopted as a successful ordinary candidate.
        record['status']='PREPARED';save_json(index,state)
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        record['status']='COMMITTED';save_json(index,state)
        if trend_allowed:
            temp = root / 'trend.jsonl.pending'
            if temp.is_symlink():raise ValueError('ORDINARY_TREND_ALIAS')
            temp.write_bytes(trend_raw);os.replace(temp,old_trend_path)
        ordinary = sorted([row for row in state['reports'] if row['status'] == 'COMMITTED'
                           and not row['critical'] and row['name'] not in protected],
                          key=lambda row: (row['timestamp'], row['name']))
        candidates = ordinary[:-14] if len(ordinary) > 14 else []
        # Latest14 are retained by count even when all runs occur on one day.
        decisions, deleted = [], 0
        for row in candidates:
            try:
                candidate = _safe_owned_path(root, row['name'])
                if candidate.stat().st_nlink != 1 or candidate.stat().st_size != row['size'] or hashlib.sha256(candidate.read_bytes()).hexdigest() != row['sha256']:
                    raise ValueError('ORDINARY_REPORT_IDENTITY_DRIFT')
                if not dry:
                    candidate.unlink();deleted += row['size'];state['reports'].remove(row)
                decisions.append({'name': row['name'], 'status': 'DRY_RUN' if dry else 'REMOVED', 'bytes': row['size']})
            except (OSError, ValueError) as exc:
                # Failure evidence remains in this bounded index; do not touch
                # an altered report or continue attributing it to our ownership.
                row['rotation_error'] = str(exc)[:512]
                decisions.append({'name': row['name'], 'status': 'BLOCKED', 'error': str(exc)[:512]})
        save_json(index, state)
        return dict(status='DRY_RUN' if dry else 'APPLIED', detailed_keep_runs=14,
                    trend_keep_days=90, decisions=decisions, deleted_bytes=deleted,
                    trend_expired_rows=max(0,len(rows)-len(kept)), dry_run=dry,
                    scope='NEW_OWNED_ORDINARY_ONLY', legacy_outputs_rotated=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(BASE / 'config.json'))
    parser.add_argument('--mode', choices=['daily', 'weekly', 'monthly', 'quarterly'], default='daily')
    args = parser.parse_args()
    with open(args.config) as stream:
        config = json.load(stream)
    print(json.dumps(run(config, args.mode), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
