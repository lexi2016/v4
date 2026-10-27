"""Only collector for the V4 read model. Durable event batches, no periodic scan."""
from __future__ import annotations
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from infrastructure.runtime_graph.current import FLAGS, SCHEMA, atomic_json, read_json, safe, sha, state_root


def _targets(event, descriptors):
    nid = event['node_id']
    owner = event['owner']
    ids = {r['node_id'] for r in descriptors}
    if owner == 'STAGE_CENTER':
        return {'stage:' + nid} if 'stage:' + nid in ids else set()
    if owner == 'REVIEW_CORE_DAILY':
        return {'review_core_daily', 'fupan_video_check'}.intersection(ids)
    matched = next((r for r in descriptors if r['node_id'] == nid), {})
    if (owner == 'MAIN' and matched.get('kind') == 'MAIN') or owner == matched.get('owner'):
        return {nid}.intersection(ids)
    return set()


def collect_events(config, get, *, initialize=False, business_date=None, quiet_seconds=2.0, max_wait=10.0, sleep=time.sleep, clock=time.monotonic):
    root = state_root(config); root.mkdir(parents=True, exist_ok=True)
    inbox = Path(config['inbox'])
    if inbox.resolve() != inbox or inbox.is_symlink():
        raise ValueError('GRAPH_INBOX_UNSAFE')
    inbox.mkdir(parents=True, exist_ok=True)
    with (root / 'collector.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'BUSY', 'snapshot_published': False, **FLAGS}
        start = clock(); last_change = start; previous = None
        while True:
            paths = sorted(inbox.glob('*.json'))
            if len(paths) > 1024:
                paths = paths[:1024]
            signature = tuple(p.name for p in paths)
            if signature != previous:
                last_change = clock(); previous = signature
            if not paths or clock() - last_change >= quiet_seconds or clock() - start >= max_wait:
                break
            sleep(min(0.05, max_wait))
        try:
            old, old_raw = read_json(root / 'snapshot.json', root)
            if old.get('schema_version') != SCHEMA or old.get('config_sha256') != config['_sha256']:
                old = {}
        except (OSError, ValueError):
            old = {}
        if not paths and old and not initialize:
            return {'status': 'IDLE', 'snapshot_published': False, **FLAGS}
        # Capture immutable bytes; later arrivals are never acknowledged here.
        batches = {}
        rejected = []
        for path in paths:
            try:
                event, raw = read_json(path, inbox); safe(event)
                date = event['business_date']; datetime.strptime(date, '%Y%m%d')
                if event.get('schema_version') != 'v4.runtime_graph_hint.v1' or event.get('phase') not in {'EXECUTOR_ENTERED', 'COMMITTED'}:
                    raise ValueError('GRAPH_HINT_SCHEMA')
                if not event.get('node_id') or not event.get('owner'):
                    raise ValueError('GRAPH_HINT_OWNER')
                observed = datetime.fromisoformat(event['observed_at'])
                if observed.tzinfo is None or observed.timestamp() > time.time() + 5:
                    raise ValueError('GRAPH_HINT_OBSERVED_TIME')
                batches.setdefault(date, []).append((path, event, sha(raw)))
            except (OSError, ValueError, TypeError, KeyError):
                rejected.append(path)
        if initialize or (not old and not batches):
            today = business_date or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
            datetime.strptime(today, '%Y%m%d')
            batches.setdefault(today, [])
        results = []
        for date, captured in sorted(batches.items()):
            previous = old if old.get('business_date') == date else {}
            previous_ref={'path':str(root/'snapshot.json'),'sha256':sha(old_raw)} if previous else None
            if not previous:
                try:
                    dated,dated_raw=read_json(root/('snapshot-'+date+'.json'),root);safe(dated)
                    if (dated.get('schema_version')==SCHEMA and dated.get('business_date')==date
                            and dated.get('config_sha256')==config['_sha256'] and dated.get('authority_identity')==config['main']
                            and isinstance(dated.get('nodes'),list) and isinstance(dated.get('descriptors'),list)):
                        previous=dated;previous_ref={'path':str(root/('snapshot-'+date+'.json')),'sha256':sha(dated_raw)}
                except (OSError,ValueError):pass

            descriptors = previous.get('descriptors', [])
            targets = set().union(*(_targets(e, descriptors) for _, e, _ in captured)) if descriptors else set()
            full = initialize or not previous
            if not full and not targets:
                # Still ask only the unknown owner, so it is visible rather
                # than triggering every API reader for e.g. each PDF page.
                targets = {e['node_id'] for _, e, _ in captured}
            query = '' if full else '&node_ids=' + ','.join(sorted(targets))
            try:
                dto = get('/api/v3/runtime-graph/authorities?date=' + date + '&projection=compact' + query)
                safe(dto)
                if dto.get('schema_version') != 'v4.runtime_graph_authority.v1' or dto.get('business_date') != date:
                    raise ValueError('AUTHORITY_DTO_IDENTITY')
                if dto.get('authority_identity') != config['main']:
                    raise ValueError('AUTHORITY_MAIN_BINDING_DRIFT')
                nodes = {n['node_id']: n for n in previous.get('nodes', [])}
                nodes.update({n['node_id']: n for n in dto['nodes']})
                now = datetime.now(timezone.utc).isoformat()
                for n in dto['nodes']:
                    nodes[n['node_id']]['last_validated_at'] = now
                # Notifications cannot confer RUNNING/READY. Keep start hints
                # as observations distinct from current authority proof.
                for _, event, _ in captured:
                    for nid in _targets(event, dto['descriptors']):
                        if nid in nodes:
                            nodes[nid]['last_lifecycle_hint'] = {k:event.get(k) for k in ('phase','observed_at','run_id','pid')}
                payload = {'schema_version': SCHEMA, 'business_date': date,
                    'config_sha256': config['_sha256'], 'authority_identity': dto['authority_identity'],
                    'runtime_binding':dto.get('runtime_binding', {'status':'CANNOT_CONFIRM'}),
                    'api_template_catalog_sha256': dto['api_template_catalog_sha256'],
                    'descriptors': dto['descriptors'], 'nodes': list(nodes.values()),
                    'status': 'OBSERVED', 'last_collection_at': now, 'generated_at': now,
                    'last_source_event_at': max((e['observed_at'] for _,e,_ in captured), default=previous.get('last_source_event_at')),
                    'event_applied_at': now if captured else previous.get('event_applied_at'),
                    'previous_snapshot':previous_ref,
                    'last_collection_scope': 'ALL_BOUND_OWNERS' if full else sorted(targets), **FLAGS}
                atomic_json(root / ('snapshot-' + date + '.json'), payload)
                # An older business date event never replaces a newer view.
                if not old or date >= old.get('business_date', ''):
                    atomic_json(root / 'snapshot.json', payload); old = payload
                history = root / 'events'; history.mkdir(exist_ok=True)
                for path, event, digest in captured:
                    atomic_json(history / path.name, {'hint': event, 'hint_sha256': digest, 'applied_at': now, **FLAGS})
                # ACK after complete snapshot and event-history persistence.
                for path, _, digest in captured:
                    if sha(path.read_bytes()) == digest:
                        path.unlink()
                failed_root = root / 'failed'
                if failed_root.is_dir():
                    resolved = root / 'resolved_failures'
                    for failure in list(failed_root.glob('*.json'))[:1024]:
                        try:
                            hint, _ = read_json(failure, failed_root)
                            if hint.get('business_date') == date and _targets(hint, dto['descriptors']).issubset(set(n['node_id'] for n in dto['nodes'])):
                                resolved.mkdir(exist_ok=True)
                                failure.rename(resolved / failure.name)
                        except (OSError, ValueError, KeyError):
                            continue
                atomic_json(root / 'monitor.json', {'state': 'IDLE', 'last_success_at': now, 'config_sha256': config['_sha256'], **FLAGS})
                results.append({'date': date, 'status': 'PUBLISHED', 'node_count': len(nodes), 'validated_count': len(dto['nodes'])})
            except Exception as exc:
                failed = root / 'failed'; failed.mkdir(exist_ok=True)
                for path, _, _ in captured:
                    if path.exists():
                        path.rename(failed / path.name)
                atomic_json(root / 'monitor.json', {'state': 'FAILED', 'reason': type(exc).__name__ + ':' + str(exc),
                    'last_failure_at': datetime.now(timezone.utc).isoformat(), 'config_sha256': config['_sha256'], **FLAGS})
                results.append({'date':date, 'status':'FAILED', 'reason':str(exc)})
        bad = root / 'rejected'; bad.mkdir(exist_ok=True)
        for path in rejected:
            path.rename(bad / path.name)
        return {'status': 'FAILED' if any(r['status']=='FAILED' for r in results) else 'COLLECTED',
                'batches': results, 'rejected_count': len(rejected), **FLAGS}
