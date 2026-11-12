"""Byte-preserving APFS maintenance for registered, closed daily outputs.

No data/model producer, deletion policy, reader format, daemon or timer. The
existing Main completion owner supplies its exact closure and writer lease.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack, contextmanager
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
import threading
import uuid

from ops.research_storage_retention import RetentionError, atomic_json, safe_path, stamp, under

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'v4.daily_storage_compaction.v1'
COMPRESSED = getattr(stat, 'UF_COMPRESSED', 32)
MIN_BYTES = 8192


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def resources():
    cpus = os.cpu_count() or 1
    memory = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], text=True))
    pressure = subprocess.check_output(['/usr/bin/memory_pressure', '-Q'], text=True)
    free = int(pressure.rsplit(':', 1)[-1].strip().removesuffix('%'))
    # Measured machine resources, not a fixed worker count. Work is primarily
    # bounded native subprocess I/O; leave four cores / 24 GiB for foreground.
    workers = max(1, min(cpus - 4, int((memory * free / 100 - 24 * 1024**3) // (256 * 1024**2))))
    return dict(cpu_count=cpus, physical_memory_bytes=memory, memory_free_percent=free,
                workers=workers, pending_limit=workers * 2, reserve_bytes=24 * 1024**3)


def bounded_map(function, values, *, workers, pending_limit, stop=None):
    iterator = iter(values)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active = set()
        while True:
            while len(active) < pending_limit and not (stop and stop()):
                try: item = next(iterator)
                except StopIteration: break
                active.add(pool.submit(function, item))
            if not active: return
            done, active = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                yield future.result()


def inventory(roots):
    """Only registered roots; never discover or walk other dates/history."""
    found = {}
    for value in roots:
        root = safe_path(value, exists=False)
        if not root.exists(): continue
        if root.is_file(): candidates = [root]
        elif root.is_dir():
            candidates = []
            for base, dirs, names in os.walk(root, followlinks=False):
                for name in dirs: safe_path(Path(base) / name)
                candidates.extend(Path(base) / name for name in sorted(names))
        else: raise RetentionError('COMPACTION_NONREGULAR_ROOT')
        for path in candidates:
            safe_path(path)
            if path.name.startswith('.') or path.suffix.lower() not in {'.json', '.csv', '.gz'}:
                raise RetentionError('COMPACTION_UNCLOSED_OR_UNEXPECTED_FILE:' + str(path))
            identity = stamp(path)
            info = path.lstat()
            if info.st_flags & ~COMPRESSED:
                raise RetentionError('COMPACTION_UNSUPPORTED_FILE_FLAGS:' + str(path))
            found[str(path)] = dict(path=str(path), stamp=identity, logical_bytes=info.st_size,
                allocated_bytes=info.st_blocks * 512, flags=info.st_flags,
                eligible=path.suffix.lower() in {'.json', '.csv'} and info.st_size >= MIN_BYTES)
    return [found[key] for key in sorted(found)]


def stamp_digest(items):
    return digest([(x['path'], x['stamp'], x['flags']) for x in items])


def content_inventory(items, resource):
    def hashed(item):
        value = dict(item)
        value['sha256'] = file_sha(item['path'])
        if stamp(Path(item['path'])) != item['stamp']:
            raise RetentionError('COMPACTION_SOURCE_MOVED_DURING_HASH')
        return value
    return sorted(bounded_map(hashed, items, workers=resource['workers'],
                              pending_limit=resource['pending_limit']), key=lambda x: x['path'])


def content_digest(items):
    return digest([(x['path'], x['logical_bytes'], x['sha256']) for x in items])


def dry_run(job, *, resource=None):
    resource = resource or resources()
    before = inventory(job['roots'])
    values = content_inventory(before, resource)
    if stamp_digest(inventory(job['roots'])) != stamp_digest(before):
        raise RetentionError('COMPACTION_SCOPE_MOVED_DURING_PLAN')
    groups = Counter((x['logical_bytes'], x['sha256']) for x in values if x['eligible'])
    return dict(schema=SCHEMA, status='DRY_RUN_NO_DATA_WRITES', job=job, resources=resource,
        files=len(values), logical_bytes=sum(x['logical_bytes'] for x in values),
        allocated_bytes=sum(x['allocated_bytes'] for x in values),
        eligible_files=sum(x['eligible'] and not x['flags'] & COMPRESSED for x in values),
        already_compressed=sum(bool(x['flags'] & COMPRESSED) for x in values),
        excluded_files=sum(not x['eligible'] for x in values),
        exact_duplicate_files=sum(n-1 for n in groups.values()),
        duplicate_logical_bytes=sum(size*(n-1) for (size, _), n in groups.items()),
        scope_stamp_sha256=stamp_digest(values), content_identity_sha256=content_digest(values),
        clone_exclusive_savings='CANNOT_CONFIRM', **FLAGS)


def _compatible_clone_metadata(source, target):
    a, b = source.stat(), target.stat()
    if (stat.S_IMODE(a.st_mode), a.st_uid, a.st_gid) != (stat.S_IMODE(b.st_mode), b.st_uid, b.st_gid):
        return False
    # Preserve recipient provenance; do not replace unknown user/resource attrs
    # with the donor's. Native compression attrs describe storage, not content.
    def attrs(path):
        names = subprocess.check_output(['/usr/bin/xattr', str(path)], text=True).splitlines()
        if 'com.apple.ResourceFork' in names: return None
        names = [x for x in names if x not in {'com.apple.decmpfs', 'com.apple.ResourceFork'}]
        if set(names) - {'com.apple.provenance'}: return None
        return {name: subprocess.check_output(['/usr/bin/xattr', '-p', name, str(path)]) for name in names}
    left, right = attrs(source), attrs(target)
    return left is not None and right is not None and left == right


def transform(item, *, donor=None):
    """Closed owner locks + stamp CAS + full pre/post SHA; replace one file."""
    path = safe_path(item['path'])
    original = path.lstat()
    if stamp(path) != item['stamp']:
        raise RetentionError('COMPACTION_PREIMAGE_STAMP_DRIFT')
    parent = safe_path(path.parent)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_identity = os.fstat(parent_fd)
    temporary = '.storage-compact-' + uuid.uuid4().hex
    temp = parent / temporary
    action = 'NATIVE_COMPRESSED'
    try:
        if donor is not None and _compatible_clone_metadata(Path(donor), path):
            donor = safe_path(donor)
            donor_stamp = stamp(donor)
            if donor.stat().st_dev != original.st_dev or file_sha(donor) != item['sha256']:
                raise RetentionError('COMPACTION_CLONE_DONOR_DRIFT')
            subprocess.run(['/bin/cp', '-c', '-p', str(donor), str(temp)], check=True, capture_output=True)
            if stamp(donor) != donor_stamp:
                raise RetentionError('COMPACTION_CLONE_DONOR_MOVED')
            action = 'EXACT_APFS_CLONE'
        else:
            subprocess.run(['/usr/bin/ditto', '--hfsCompression', '--noclone', str(path), str(temp)],
                           check=True, capture_output=True)
        # All transforms preserve the recipient's observable file date/mode.
        os.chmod(temp, stat.S_IMODE(original.st_mode))
        os.utime(temp, ns=(original.st_atime_ns, original.st_mtime_ns))
        candidate = temp.lstat()
        if (not stat.S_ISREG(candidate.st_mode) or candidate.st_nlink != 1
                or candidate.st_dev != original.st_dev or candidate.st_size != original.st_size
                or (candidate.st_uid, candidate.st_gid) != (original.st_uid, original.st_gid)
                or file_sha(temp) != item['sha256']):
            raise RetentionError('COMPACTION_POSTIMAGE_CONFLICT')
        if action == 'NATIVE_COMPRESSED' and (not candidate.st_flags & COMPRESSED
                or candidate.st_blocks >= original.st_blocks):
            return dict(status='NO_ALLOCATED_BENEFIT', action=action, logical_bytes=original.st_size,
                        before_allocated=original.st_blocks*512, after_allocated=original.st_blocks*512)
        safe_path(parent)
        current_parent = parent.lstat()
        if (current_parent.st_dev, current_parent.st_ino) != (parent_identity.st_dev, parent_identity.st_ino):
            raise RetentionError('COMPACTION_PARENT_MOVED')
        if stamp(path) != item['stamp'] or file_sha(path) != item['sha256']:
            raise RetentionError('COMPACTION_PRECOMMIT_SOURCE_MOVED')
        fd = os.open(temp, os.O_RDONLY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
        os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        final = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (final.st_size, final.st_mtime_ns, final.st_nlink) != (original.st_size, original.st_mtime_ns, 1):
            raise RetentionError('COMPACTION_FINAL_METADATA_DRIFT')
        return dict(status='PASS', action=action, logical_bytes=final.st_size,
                    before_allocated=original.st_blocks*512, after_allocated=final.st_blocks*512)
    finally:
        try: os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError: pass
        os.close(parent_fd)


@contextmanager
def closed_owner_locks(job, *, lease_day=None):
    """Original completion, scheduler lane and qfq publication locks only."""
    descriptors = []
    try:
        for index, value in enumerate(job['owner_locks']):
            path = safe_path(value)
            before = stamp(path)
            inherited = None
            if index == 1 and os.environ.get('V4_SCHEDULER_LANE_FD'):
                from ops.sync_stock_history_completion import _inherited_owner_duplicate
                # The inherited lease belongs to the executing event, while a
                # queued closed data job can legitimately be from an older day.
                current_day = str(lease_day or os.environ.get('V4_SCHEDULER_RESOLVED_DATE') or '')
                if len(current_day) != 8 or not current_day.isdigit():
                    raise ValueError('SHARED_INHERITED_OWNER_FD_INVALID:current_event_date')
                inherited = _inherited_owner_duplicate(dict(path=str(path), device=before['device'], inode=before['inode']), current_day)
            fd = inherited if inherited is not None else os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            descriptors.append(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = os.fstat(fd)
            if (held.st_dev, held.st_ino) != (before['device'], before['inode']) or stamp(path) != before:
                raise RetentionError('COMPACTION_OWNER_LOCK_DRIFT')
        yield
    finally:
        # Closing inherited duplicates must not unlock the original open lease.
        for fd in reversed(descriptors): os.close(fd)


def compact_job(job, *, output, resource=None, seconds=None, expected_plan=None, lease_day=None):
    """Caller holds Registry.writer; native budget drains submitted work."""
    resource = resource or resources()
    started = time.monotonic()
    with closed_owner_locks(job, lease_day=lease_day):
        items = inventory(job['roots'])
        if expected_plan and stamp_digest(items) != expected_plan['scope_stamp_sha256']:
            raise RetentionError('COMPACTION_PLAN_CAS_DRIFT')
        algorithm_sha = file_sha(Path(__file__))
        prior = json.loads(Path(output).read_bytes()) if Path(output).is_file() else {}
        if prior.get('algorithm_sha256') == algorithm_sha and prior.get('status') == 'PASS' and prior.get('after_scope_stamp_sha256') == stamp_digest(items):
            return dict(prior, reused=True)
        values = content_inventory(items, resource)
        before_digest = content_digest(values)
        # Sparse private terminal cache, only for verified no-benefit cases.
        # This is progress state, not a 29k-row delivered success log. It stays
        # valid across budget passes/new files until that file or code changes.
        terminal_path = Path(output).with_name(Path(output).stem + '.no-benefit.json')
        terminal_state = json.loads(terminal_path.read_bytes()) if terminal_path.is_file() else {}
        cached = terminal_state.get('items', {}) if terminal_state.get('algorithm_sha256') == algorithm_sha else {}
        current = {x['path']: x for x in values}
        terminal = {path: proof for path, proof in cached.items()
            if path in current and proof == dict(stamp=current[path]['stamp'], sha256=current[path]['sha256'])}
        if expected_plan and before_digest != expected_plan['content_identity_sha256']:
            raise RetentionError('COMPACTION_PLAN_CONTENT_DRIFT')
        groups = {}
        for item in values:
            if item['eligible']:
                groups.setdefault((item['logical_bytes'], item['sha256']), []).append(item)
        groups = sorted(groups.values(), key=lambda rows: -sum(x['allocated_bytes'] for x in rows))
        deadline = None if seconds is None else started + seconds
        stats, failures = Counter(), []
        failure_lock = threading.Lock()
        stop_failures = threading.Event()
        failure_count = 0
        stats['REUSED_COMPRESSED'] = sum(bool(x['flags'] & COMPRESSED) for x in values)
        def group_work(rows):
            nonlocal failure_count
            results, donor = [], None
            for item in sorted(rows, key=lambda x: (not bool(x['flags'] & COMPRESSED), x['path'])):
                if item['flags'] & COMPRESSED:
                    donor = donor or item['path']; continue
                if terminal.get(item['path']) == dict(stamp=item['stamp'], sha256=item['sha256']):
                    donor = donor or item['path']; results.append(dict(status='REUSED_NO_BENEFIT')); continue
                if stop_failures.is_set() or (deadline is not None and time.monotonic() >= deadline):
                    results.append(dict(status='DEFERRED')); continue
                try:
                    result = transform(item, donor=donor)
                    donor = donor or item['path']
                    if result['status'] == 'NO_ALLOCATED_BENEFIT':
                        result.update(path=item['path'], proof=dict(stamp=item['stamp'], sha256=item['sha256']))
                    results.append(result)
                except Exception as error:
                    with failure_lock:
                        failure_count += 1
                        if failure_count >= 3: stop_failures.set()
                    results.append(dict(status='FAILED', path=item['path'], error=str(error)[:512]))
            return results
        # bounded_map never submits an unbounded queue. Workers themselves stop
        # starting native writes at deadline; submitted work is never cancelled.
        for results in bounded_map(group_work, groups, workers=resource['workers'], pending_limit=resource['pending_limit'],
                stop=lambda: stop_failures.is_set() or (deadline is not None and time.monotonic() >= deadline)):
            for result in results:
                stats[result['status']] += 1
                if result['status'] == 'PASS':
                    stats[result['action']] += 1
                    stats['allocated_block_drop_bytes'] += result['before_allocated'] - result['after_allocated']
                    if result['action'] == 'EXACT_APFS_CLONE':
                        stats['clone_logical_bytes_shared'] += result['logical_bytes']
                elif result['status'] == 'NO_ALLOCATED_BENEFIT': terminal[result['path']] = result['proof']
                elif result['status'] == 'FAILED': failures.append(result)
        stats['DEFERRED'] = sum(x['eligible'] and not x['flags'] & COMPRESSED for x in values) - sum(stats[k] for k in ('PASS', 'NO_ALLOCATED_BENEFIT', 'REUSED_NO_BENEFIT', 'FAILED'))
        after = inventory(job['roots'])
        # Every changed file was SHA-checked before atomic replacement; unchanged
        # inodes still bind to the hashed preimage. Check complete closure stamps
        # and compute its content identity independently after transformation.
        checked = content_inventory(after, resource)
        after_digest = content_digest(checked)
        if after_digest != before_digest:
            raise RetentionError('COMPACTION_COMPLETE_IDENTITY_DRIFT')
        if terminal or terminal_path.exists():
            atomic_json(terminal_path, dict(schema=SCHEMA, algorithm_sha256=algorithm_sha, items=terminal))
        result = dict(schema=SCHEMA, algorithm_sha256=algorithm_sha,
            no_benefit_terminal_count=len(terminal),
            no_benefit_terminal_index=(dict(path=str(terminal_path), sha256=file_sha(terminal_path)) if terminal else None),
            status='FAILED' if failures else 'DEFERRED' if stats['DEFERRED'] else 'PASS',
            job=job, resources=resource, files=len(values), logical_bytes=sum(x['logical_bytes'] for x in values),
            before_allocated_bytes=sum(x['allocated_bytes'] for x in values),
            after_allocated_bytes=sum(x['allocated_bytes'] for x in after),
            content_identity_sha256=before_digest, after_content_identity_sha256=after_digest,
            after_scope_stamp_sha256=stamp_digest(after), counts=dict(stats), failures=failures,
            elapsed_seconds=time.monotonic()-started, clone_exclusive_savings='CANNOT_CONFIRM',
            budget_stops_new_writes_only=True, **FLAGS)
        atomic_json(Path(output), result)
        return result


def closed_job(*, product_root, data_root, receipt_root, day, generation, numeric_manifest, snapshot):
    """Bind exact closed paths from the existing numeric owner; no discovery."""
    root, data, receipts = (safe_path(p) for p in (product_root, data_root, receipt_root))
    if len(day) != 8 or not day.isdigit() or len(generation) != 64:
        raise RetentionError('COMPACTION_DATE_GENERATION_INVALID')
    def document(reference):
        path = safe_path(reference['path'])
        before = stamp(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference['sha256'] or stamp(path) != before:
            raise RetentionError('COMPACTION_CLOSURE_REFERENCE_DRIFT')
        return json.loads(raw)
    manifest = document(numeric_manifest)
    product = document(manifest['artifact'])
    if (manifest.get('data_date') != day or manifest.get('source_generation') != generation
            or product.get('data_date') != day or product.get('source_generation') != generation
            or manifest.get('snapshot') != snapshot
            or not under(Path(numeric_manifest['path']), root / 'versions' / day)
            or not under(Path(snapshot['path']), data / 'runtime/cache/data_layer_daily_formula_increment_update_v1/adjustment_snapshots')):
        raise RetentionError('COMPACTION_CLOSURE_IDENTITY_CONFLICT')
    snapshot_path = safe_path(snapshot['path'])
    if file_sha(snapshot_path) != snapshot['sha256']:
        raise RetentionError('COMPACTION_SNAPSHOT_REFERENCE_DRIFT')
    row_parents = {str(Path(value['path']).parent) for value in product['row_refs'].values()}
    if len(row_parents) != 1 or not under(Path(next(iter(row_parents))), root / 'checkpoints' / day):
        raise RetentionError('COMPACTION_NUMERIC_CHECKPOINT_CLOSURE_INVALID')
    roots = [next(iter(row_parents)), str(root/'f10'/day/generation[:16]), str(snapshot_path),
        str(receipts/'a_sync_authority'/day), str(receipts/('a-'+day+'.json')),
        str(root/'versions'/day), str(root/'continuations'/day), str(root/'top200'/day)]
    result = dict(day=day, generation=generation, product_root=str(root), data_root=str(data),
        receipt_root=str(receipts), numeric_manifest=numeric_manifest, snapshot=snapshot, roots=roots,
        owner_locks=[str(root/'.stock-history-completion.lock'),
            '/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners/A_LONG.lock',
            str(data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publish.lock')])
    result['job_id'] = digest(dict(root=str(root), day=day, generation=generation, numeric_manifest=numeric_manifest, snapshot=snapshot))
    return result


def completed_event(*, claim, context, product_root, receipt_root, result, seconds=20, resource=None):
    """Resume only registered pending closures at the original completion event.

    The numeric/index and the original claim are already committed. This small
    private queue is never a business gate and installs no scheduler/daemon.
    """
    from ops.research_storage_governance import _ACTIVE
    if _ACTIVE.get() is not claim or not claim.finalized:
        raise RetentionError('COMPACTION_ORIGINAL_WRITER_LEASE_REQUIRED')
    if result.get('schema') != 'V4_A_DAILY_DERIVATIVES_V1' or result.get('status') != 'COMPLETE_DESCRIPTIVE_NONPIT':
        return None
    job = closed_job(product_root=product_root, data_root=context.data_root, receipt_root=receipt_root,
        day=str(context.target), generation=context.generation,
        numeric_manifest=result['completed_source_provenance']['numeric_manifest'], snapshot=context.snapshot_ref)
    state_root = claim.registry.root / 'compaction'
    queue_path = state_root / 'pending.json'
    queue = json.loads(queue_path.read_bytes()) if queue_path.is_file() else dict(schema=SCHEMA, jobs={})
    jobs = queue['jobs']
    prior_job = jobs.get(job['job_id'])
    if prior_job is not None and prior_job['job'] != job:
        raise RetentionError('COMPACTION_PENDING_CLOSURE_CONFLICT')
    if len(jobs) >= 64 and job['job_id'] not in jobs:
        raise RetentionError('COMPACTION_PENDING_LIMIT_REQUIRES_REVIEW')
    jobs.setdefault(job['job_id'], dict(job=job, registered_at=time.time()))
    atomic_json(queue_path, queue)
    resource = resource or resources()
    started = time.monotonic()
    order = [job['job_id']] + [key for key, value in sorted(jobs.items(), key=lambda pair: pair[1]['registered_at']) if key != job['job_id']]
    # Current high-yield work gets half when older pending exists; older work
    # gets the remainder, so new daily inputs cannot starve registered backlog.
    for position, key in enumerate(order):
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0: break
        item = jobs[key]
        output = state_root / (key + '.json')
        if item.get('blocked_scope') == stamp_digest(inventory(item['job']['roots'])):
            continue  # no blind retry of an identical failed input
        budget = remaining / 2 if position == 0 and len(order) > 1 else remaining
        try:
            receipt = compact_job(item['job'], output=output, resource=resource, seconds=budget, lease_day=str(context.target))
            if receipt['status'] == 'PASS': del jobs[key]
            elif receipt['status'] == 'FAILED': item['blocked_scope'] = receipt['after_scope_stamp_sha256']
        except BlockingIOError:
            # A busy owner is a transient deferral, not a permanent bad input.
            atomic_json(output, dict(schema=SCHEMA, status='DEFERRED', job=item['job'],
                reason='EXISTING_OWNER_BUSY', **FLAGS))
        except (OSError, ValueError, RetentionError) as error:
            # An invalid current execution lease is recoverable at a later
            # real owner event, independent of the immutable pending data.
            if not str(error).startswith('SHARED_INHERITED_OWNER_FD_INVALID:'):
                item['blocked_scope'] = stamp_digest(inventory(item['job']['roots']))
            atomic_json(output, dict(schema=SCHEMA, status='FAILED', job=item['job'], error=str(error)[:1024], **FLAGS))
        atomic_json(queue_path, queue)
    return dict(status='DEFERRED' if jobs else 'PASS', pending_jobs=len(jobs),
                queue=str(queue_path), elapsed_seconds=time.monotonic()-started, **FLAGS)


def execute_plan(plan, *, policy, output, seconds=None):
    """Explicit controller backfill; reuses the actual Registry writer lock."""
    from ops.research_storage_governance import Registry, configuration
    config = configuration(policy)
    if config is None or Path(plan['job']['product_root']) not in [Path(p) for p in config['product_output_roots']]:
        raise RetentionError('COMPACTION_APPROVED_PRODUCT_ROOT_REQUIRED')
    if Path(plan['job']['data_root']) != Path(policy['data_root']):
        raise RetentionError('COMPACTION_POLICY_DATA_ROOT_CONFLICT')
    with Registry(config, policy['data_root']).writer():
        return compact_job(plan['job'], output=output, resource=resources(), seconds=seconds, expected_plan=plan)
