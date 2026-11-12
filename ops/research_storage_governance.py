"""Nondeleting admission for registered V4 materializers.

One shared pool registry and kernel writer lock; no filesystem quota, GC, collector,
new data layout or formula computation. Unregistered callers remain outside scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import time
import types
import uuid
import weakref

from ops.research_storage_retention import (RetentionError, atomic_json, canonical,
    digest, safe_path, stamp, logical_bytes, under, files)

SCHEMA = 'v4_storage_governance_v2'
GIB = 1024**3
MIB = 1024**2
# One bounded mutable slot is reserved before a new task may write data.
CONTROL_SLOT_BYTES = 256 * 1024
ADMISSION_MARGIN_BYTES = 16 * 1024
_ACTIVE = ContextVar('v4_storage_claim', default=None)
_DEPTH = ContextVar('v4_storage_depth', default=0)
_ARTIFACT_CACHE = {}
_ADAPTER_LOCK = threading.RLock()
_ADAPTER_SCOPES = ContextVar('v4_storage_adapter_scopes', default={})


class SpaceBlocked(RetentionError):
    pass


def billing_files(path):
    """Read-only inventory: legitimate hardlinks are not deletion candidates."""
    path=safe_path(path)
    mode=path.stat().st_mode
    if stat.S_ISREG(mode):
        yield path;return
    if not stat.S_ISDIR(mode):raise RetentionError('BILLING_NONREGULAR_PATH:'+str(path))
    def error(exc):raise exc
    for base,dirs,names in os.walk(path,followlinks=False,onerror=error):
        for name in dirs:safe_path(Path(base)/name)
        for name in names:
            item=safe_path(Path(base)/name)
            if not stat.S_ISREG(item.stat().st_mode):raise RetentionError('BILLING_NONREGULAR_PATH:'+str(item))
            yield item


def billing_bytes(path, *, seen=None):
    seen=seen if seen is not None else set()
    total=0
    for item in billing_files(path):
        value=item.stat();inode=(value.st_dev,value.st_ino)
        if inode not in seen:
            seen.add(inode);total+=value.st_size
    return total


def computation_identity(*, inputs, scope, calculation, schema, environment=None):
    """Presentation, output directories, timestamps and repository HEAD are absent.

    Callers supply actual dependency hashes (including dirty executed bytes).
    Scope preserves supplied order and leading zeroes; we never infer equivalence.
    """
    for values in (inputs, scope, calculation, schema):
        if not values:
            raise RetentionError('COMPUTATION_IDENTITY_INCOMPLETE')
    return canonical(json.loads(json.dumps(dict(inputs=inputs, scope=scope, calculation=calculation,
                          schema=schema, environment=environment or {}),default=str)))


def process_identity(pid=None):
    pid = pid or os.getpid()
    try:
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return dict(pid=pid, started=result.stdout.strip())


def owner_state(owner):
    """UNKNOWN never permits lock stealing; PID reuse is a different process."""
    try:
        os.kill(owner['pid'], 0)
    except ProcessLookupError:
        return 'DEAD'
    except (OSError, KeyError, TypeError):
        return 'UNKNOWN'
    observed = process_identity(owner['pid'])
    if observed is None:
        return 'UNKNOWN'
    return 'LIVE' if observed == owner else 'DEAD'


def configuration(policy):
    value = dict(policy.get('governance') or {})
    if not value.get('enabled', False):
        return None
    # The controller binds all APFS volumes sharing storage to this SAME root/id.
    # st_dev is deliberately not used as an APFS shared-pool identifier.
    if not value.get('pool_id') or value.get('pool_identity_verified') is not True:
        raise RetentionError('VERIFIED_SHARED_POOL_REQUIRED')
    safe_path(value['registry_root'], exists=False)
    defaults = dict(reserve_bytes=64*GIB, safety_bytes=4*GIB,
        minimum_free_ratio=.10, optional_full_min_ratio=.15,
        max_registry_bytes=4*MIB, max_tasks=512, own_budget_bytes=512*MIB,
        max_debug_file_bytes=64*MIB, max_debug_job_bytes=256*MIB,
        debug_budget_bytes=16*GIB, ordinary_peak_budget_bytes=160*GIB,
        future_quarantine_budget_bytes=32*GIB, wait_seconds=0, max_attempts=3)
    for key, default in defaults.items():
        value.setdefault(key, default)
    for key in defaults:
        if not isinstance(value[key], (int, float)) or isinstance(value[key], bool) or value[key] < 0:
            raise RetentionError('INVALID_GOVERNANCE_LIMIT:'+key)
    if value['reserve_bytes'] < 64*GIB or not .10 <= value['minimum_free_ratio'] < 1:
        raise RetentionError('GLOBAL_RESERVE_CANNOT_BE_LOWERED')
    if (value['max_debug_file_bytes'] > 64*MIB or value['max_debug_job_bytes'] > 256*MIB
            or value['wait_seconds'] > 30 or value['max_registry_bytes'] > 4*MIB):
        raise RetentionError('GOVERNANCE_BOUND_EXCEEDED')
    if value['max_attempts'] < 1:
        raise RetentionError('RETRY_BOUND_REQUIRED')
    value['accounting_roots']=dict(value.get('accounting_roots') or {})
    value['accounting_roots']['ordinary']=list(set(value['accounting_roots'].get('ordinary',[]))|set(value.get('product_output_roots',[])))
    value['resident_policy']={key:policy.get(key) for key in ('pointers','formal_roots','run_root','data_root','keep_completed')}
    if set(policy.get('formal_roots',{}))=={'selector','backtest'} and set(policy.get('pointers',{}))=={'selector','backtest'}:
        value['creation_roots']=[policy['run_root'],*policy['formal_roots'].values()]
    else:
        value['accounting_roots']['ordinary'].append(policy['run_root'])
        value['creation_roots']=[]
    value['extra_owned_roots']=[str(Path(policy['run_root'])/'storage_retention_ownership')]
    if os.environ.get('V4_STORAGE_PAIR_ROOT'):
        value['extra_owned_roots'].append(str(safe_path(os.environ['V4_STORAGE_PAIR_ROOT'],exists=False)))
    return value


def ordinary_resident_paths(config):
    """Exact current plus its baseline-SHA rollback, not every legacy run."""
    policy=config['resident_policy']
    if not config['creation_roots']:return []
    from ops.research_storage_retention import inventory, pointer_state
    ready,_,_=inventory(policy)
    targets={item['target'] for item in pointer_state(policy).values()}
    current=[item for item in ready if set(item['status']['candidates'].values())==targets]
    if len(current)!=1:raise RetentionError('ORDINARY_CURRENT_RESIDENT_UNKNOWN')
    baseline=current[0]['status']['baseline_panel_sha256']
    rollback=[item for item in ready if item['status']['candidate_sha256']==baseline]
    if policy.get('keep_completed',2)!=1 and len(rollback)!=1:
        raise RetentionError('ORDINARY_ROLLBACK_RESIDENT_UNKNOWN')
    retained=[current[0]] if policy.get('keep_completed',2)==1 else [current[0],rollback[0]]
    paths=[]
    from ops.research_panel_logical import closure
    for item in retained:
        paths.extend(item['status']['candidates'].values())
        checkpoints=item['run']/'symbol_checkpoints'
        if checkpoints.exists():paths.append(str(checkpoints))
        for path in item['status']['candidates'].values():
            paths.extend(block['path'] for block in closure(Path(path)))
    for path in paths:safe_path(path)
    return paths


def unique_roots(paths):
    roots={Path(path) for path in paths}
    # under(path, other) means equality or lexical parent membership. Equality
    # was excluded above, so only this path's ancestors can cover it. Looking
    # those up avoids all-pairs comparisons for logical generations' blocks.
    return {path for path in roots if not any(parent in roots for parent in path.parents)}


class Registry:
    def __init__(self, config, disk_root):
        self.config, self.disk_root = config, Path(disk_root)
        self.root = safe_path(config['registry_root'], exists=False)
        self.path = self.root/'registry.json'

    @contextmanager
    def transaction(self):
        self.root.mkdir(parents=True, exist_ok=True)
        safe_path(self.root)
        lock = safe_path(self.root/'registry.lock', exists=False)
        with lock.open('a+') as stream:
            deadline=time.monotonic()+self.config['wait_seconds']
            while True:
                try:
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise RetentionError('REGISTRY_BUSY_BOUNDED_WAIT')
                    time.sleep(min(.05,max(0,deadline-time.monotonic())))
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def read(self):
        if not self.path.exists():
            return dict(schema=SCHEMA, pool_id=self.config['pool_id'], tasks={},resident_baseline_paths=None)
        safe_path(self.path)
        if self.path.stat().st_size > self.config['max_registry_bytes']:
            raise RetentionError('REGISTRY_BUDGET')
        value = json.loads(self.path.read_bytes())
        if value.get('schema') != SCHEMA or value.get('pool_id') != self.config['pool_id']:
            raise RetentionError('REGISTRY_POOL_OR_SCHEMA_DRIFT')
        if not isinstance(value.get('tasks'),dict):raise RetentionError('REGISTRY_TASK_SCHEMA')
        for key,row in value['tasks'].items():
            if (not isinstance(row,dict) or row.get('state') not in {'RUNNING','VALIDATING','READY','FAILED_RECOVERABLE','SPACE_BLOCKED','ABANDONED'}
                    or row.get('category') not in {'ordinary','debug'}
                    or any(type(row.get(field)) is not int or row[field]<0 for field in ('reserved_bytes','written_bytes'))
                    or row['written_bytes']>row['reserved_bytes']):
                raise RetentionError('REGISTRY_TASK_SCHEMA')
            safe_path(row['directory'],exists=False)
        return value

    @staticmethod
    def encoded(value):
        # Measure the exact bytes that will be persisted (the former compact
        # estimate followed by indented atomic_json could exceed the 4MiB cap).
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':')).encode() + b'\n'

    def save(self, value, *, admitting=False):
        for row in value['tasks'].values():
            row.pop('_control_reserve', None)
            if row['state'] not in {'READY', 'ABANDONED'}:
                used = len(self.encoded(row))
                if used > CONTROL_SLOT_BYTES:
                    raise RetentionError('TASK_CONTROL_SLOT_EXCEEDED')
                # Replaced by bounded terminal metadata, not additional space.
                row['_control_reserve'] = ' ' * max(0, CONTROL_SLOT_BYTES-used-24)
        raw = self.encoded(value)
        limit = self.config['max_registry_bytes'] - (ADMISSION_MARGIN_BYTES if admitting else 0)
        if len(raw) > limit or len(value['tasks']) > self.config['max_tasks']:
            raise RetentionError('REGISTRY_BUDGET_PROTECTED_EVIDENCE_RETAINED')
        extra=sum(billing_bytes(Path(path)) for path in self.config.get('extra_owned_roots',[]) if Path(path).exists() and not under(Path(path),self.root))
        # Old file plus atomic temporary; no daily database copies or archives.
        if billing_bytes(self.root) + extra + len(raw) > self.config['own_budget_bytes']:
            raise RetentionError('GOVERNANCE_OWN_OUTPUT_BUDGET')
        temporary = self.path.with_name('registry.json.pending')
        safe_path(temporary, exists=False)
        try:
            with temporary.open('wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            from ops.research_storage_retention import fsync_dir
            fsync_dir(self.root)
        finally:
            temporary.unlink(missing_ok=True)

    def remaining(self, record):
        return max(0, record['reserved_bytes'] - record.get('written_bytes', 0))

    def space(self, state, key, remaining, *, category, optional_full, category_used=0, category_remaining_bytes=None):
        usage = shutil.disk_usage(self.disk_root)
        ratio = usage.free / usage.total
        if ratio < self.config['minimum_free_ratio'] or (optional_full and ratio < self.config['optional_full_min_ratio']):
            raise SpaceBlocked('SPACE_RATIO_BLOCKED')
        others = sum(self.remaining(row) for task, row in state['tasks'].items()
                     if task != key and row['state'] in {'RUNNING','VALIDATING','FAILED_RECOVERABLE','SPACE_BLOCKED'})
        if usage.free - others - remaining < self.config['reserve_bytes'] + self.config['safety_bytes']:
            raise SpaceBlocked('SPACE_RESERVATION_BLOCKED')
        limit = self.config['debug_budget_bytes'] if category == 'debug' else self.config['ordinary_peak_budget_bytes']
        category_remaining=sum(max(0,row['reserved_bytes']-row.get('logical_written_bytes',row.get('written_bytes',0))) for task,row in state['tasks'].items()
            if task!=key and row['category']==category and row['state'] in {'RUNNING','VALIDATING','FAILED_RECOVERABLE','SPACE_BLOCKED'})
        if category_used + category_remaining + (remaining if category_remaining_bytes is None else category_remaining_bytes) > limit:
            raise SpaceBlocked('CATEGORY_BUDGET_BLOCKED')
        return dict(free_bytes=usage.free, total_bytes=usage.total, remaining_bytes=remaining,
                    other_remaining_bytes=others, ratio_denominator='disk_usage.total shared pool capacity')

    @contextmanager
    def writer(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = safe_path(self.root/'pool-writer.lock', exists=False)
        with path.open('a+') as stream:
            deadline = time.monotonic() + self.config['wait_seconds']
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RetentionError('POOL_WRITER_BUSY_BOUNDED_WAIT')
                    time.sleep(min(.05, max(0, deadline-time.monotonic())))
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def abandon_task(policy, *, key, expected_registry_sha256, expected_token, reason):
    """Explicit controller operation, never called by normal failure recovery.

    Serializes with the pool writer and CAS-binds the exact registry/token.
    The terminal row remains evidence and denies automatic same-key recovery.
    No payload or stage file is removed; deletion is a separate reviewed action.
    """
    if not reason or len(reason) > 1024:
        raise RetentionError('ABANDON_REASON_REQUIRED')
    config = configuration(policy)
    if config is None:raise RetentionError('ABANDON_GOVERNANCE_REQUIRED')
    registry = Registry(config, policy['data_root'])
    with registry.writer(), registry.transaction():
        if digest(registry.path) != expected_registry_sha256:
            raise RetentionError('ABANDON_REGISTRY_DRIFT')
        state = registry.read();row = state['tasks'].get(key)
        if not row or row.get('token') != expected_token:
            raise RetentionError('ABANDON_TASK_DRIFT')
        if row['state'] not in {'FAILED_RECOVERABLE', 'SPACE_BLOCKED'}:
            raise RetentionError('ABANDON_ONLY_TERMINAL_FAILED_TASK')
        before = {k:v for k,v in row.items() if k != '_control_reserve'}
        row.update(state='ABANDONED', reserved_bytes=0, written_bytes=0,
                   logical_written_bytes=0, abandonment=dict(reason=reason,
                   previous_sha256=canonical(before), previous_state=before['state'],
                   released_reserved_bytes=before['reserved_bytes'],
                   released_billing_paths=before.get('billing_paths', [])))
        row['billing_paths'] = []
        registry.save(state)
        return row


def artifact_records(paths):
    result = []
    for item in paths:
        path = safe_path(item)
        before = stamp(path)
        sha = digest(path)
        if stamp(path) != before:
            raise RetentionError('ARTIFACT_CHANGED_DURING_VALIDATION')
        result.append(dict(path=str(path), stat=before, sha256=sha))
    return result


def validate_artifacts(records):
    if not records:
        raise RetentionError('SUCCESS_WITHOUT_ARTIFACT_MANIFEST')
    for row in records:
        path = safe_path(row['path'])
        observed = stamp(path)
        # Full SHA is persisted at validation. Any stat drift rehashes and fails
        # on changed content; we do not hash full unchanged panels every minute.
        if observed != row['stat']:
            if digest(path) != row['sha256'] or stamp(path) != observed:
                raise RetentionError('READY_ARTIFACT_CORRUPT')


class Claim:
    def __init__(self, registry, key, directory, predicted, *, category='ordinary', optional_full=False, category_used=0):
        self.registry, self.key = registry, key
        self.directory, self.predicted = str(directory), predicted
        self.category, self.optional_full, self.category_used = category, optional_full, category_used
        self.owner = process_identity()
        self.token = uuid.uuid4().hex
        self.observed = {}
        self.baselines = {}
        self.initial_inodes = {}
        self.mutex = threading.RLock()
        self.paused = False
        self.finalized = False
        self.recording_failed = False

    def begin(self, *, reuse_ready=True):
        if self.owner is None or not isinstance(self.predicted,int) or self.predicted <= 0:
            raise RetentionError('CLAIM_OWNER_OR_BUDGET_UNKNOWN')
        with self.registry.transaction():
            state = self.registry.read()
            old = state['tasks'].get(self.key)
            if old and old['state'] == 'ABANDONED':
                raise RetentionError('TASK_USER_ABANDONED_NO_RESUME')
            if old and old['directory'] != self.directory:
                raise RetentionError('IDENTITY_REQUIRES_ORIGINAL_DIRECTORY:'+old['directory'])
            if old and old['state'] == 'READY' and reuse_ready:
                validate_artifacts(old['artifacts'])
                return old['result']
            for key, row in state['tasks'].items():
                if row['state'] in {'RUNNING','VALIDATING'}:
                    live = owner_state(row['owner'])
                    if live != 'DEAD':
                        raise RetentionError('OWNER_LIVE_OR_UNKNOWN_NO_STEAL')
                    if key != self.key:
                        raise RetentionError('DEAD_OWNER_RECONCILIATION_REQUIRED')
            attempts = old.get('attempts',0)+1 if old and old['state'] != 'READY' else 1
            if attempts > self.registry.config['max_attempts']:
                raise RetentionError('RETRY_BOUND_RECOVERY_REQUIRES_NEW_EVIDENCE')
            roots=set(self.registry.config['accounting_roots'].get(self.category,[]))
            if self.category=='ordinary':
                resident=ordinary_resident_paths(self.registry.config)
                if state.get('resident_baseline_paths') is None:
                    state['resident_baseline_paths']=resident
                roots.update(state.get('resident_baseline_paths') or [])
                roots.update(resident)
                for row in state['tasks'].values():
                    if row['category']=='ordinary':roots.update(row.get('billing_paths',[]))
                # Same-identity recovery retains the original absence boundary.
                self.initial_children=(old or {}).get('initial_children') or {
                    root:sorted(path.name for path in safe_path(root).iterdir())
                    for root in self.registry.config['creation_roots']}
                roots.update(self.new_billing_paths())
            else:
                roots.update(row['directory'] for row in state['tasks'].values() if row['category']==self.category)
                roots.add(self.directory)
                self.initial_children={}
            roots=unique_roots(roots)
            seen=set()
            measured=sum(billing_bytes(path,seen=seen) for path in roots if path.exists())
            self.category_used=max(self.category_used,measured)
            sample = self.registry.space(state,self.key,self.predicted,category=self.category,
                optional_full=self.optional_full,category_used=self.category_used)
            state['tasks'][self.key] = dict(state='RUNNING',owner=self.owner,token=self.token,
                directory=self.directory, reserved_bytes=self.predicted,written_bytes=0,
                logical_written_bytes=0,category=self.category,attempts=attempts,
                resumed=bool(old),heartbeat=time.time(),space=sample,
                category_baseline_bytes=self.category_used,initial_children=self.initial_children,
                billing_paths=sorted(set((old or {}).get('billing_paths',[]))|set(self.new_billing_paths())))
            self.registry.save(state, admitting=True)
        directory=Path(self.directory)
        if directory.exists():
            for path in billing_files(directory):
                st=path.stat();self.baselines[path]=(st.st_size,st.st_blocks*512)
                self.initial_inodes[(st.st_dev,st.st_ino)]=(st.st_size,st.st_blocks*512)
        return None

    def new_billing_paths(self):
        # New top-level generation directories are charged once even after they
        # age out of CURRENT/rollback. GC-off never hides retained V2 outputs.
        paths=[]
        for root,before in getattr(self,'initial_children',{}).items():
            for path in safe_path(root).iterdir():
                if path.name not in before:paths.append(str(path))
        return paths

    def watch(self, path):
        path = Path(path)
        safe_path(path, exists=False)
        if path not in self.baselines:
            st = path.stat() if path.exists() else None
            self.baselines[path] = (st.st_size,st.st_blocks*512) if st else (0,0)

    def observe(self, path):
        path = Path(path)
        with self.mutex:
            if path not in self.baselines:
                # Only explicitly watched pre-existing paths can be credited.
                # New result paths may already exist on resume: zero credit.
                self.watch(path)
            if path.exists():
                safe_path(path)
                st = path.stat()
                logical, allocated = self.baselines[path]
                if not stat.S_ISREG(st.st_mode):raise RetentionError('BILLING_NONREGULAR_PATH:'+str(path))
                known=self.initial_inodes.get((st.st_dev,st.st_ino),(0,0))
                logical=max(logical,known[0]);allocated=max(allocated,known[1])
                self.observed[path] = (max(0,st.st_size-logical),max(0,st.st_blocks*512-allocated),(st.st_dev,st.st_ino))

    def checkpoint(self, *, incoming=0):
        with self.mutex, self.registry.transaction():
            if self.paused:raise SpaceBlocked('CLAIM_ALREADY_PAUSED')
            state = self.registry.read()
            row = state['tasks'][self.key]
            if row.get('token') != self.token or row['owner'] != self.owner:
                raise RetentionError('CLAIM_OWNER_DRIFT')
            # Existing owner renames *.pending -> *.parquet. Reconcile that
            # same inode before spending a reservation, rather than charging
            # both names or crediting a removed temporary allocation.
            for path in list(self.observed):
                if not path.exists():
                    del self.observed[path]
                    if path.suffix=='.pending':
                        final=path.with_suffix('.parquet')
                        if final.exists():
                            if final not in self.baselines:self.baselines[final]=(0,0)
                            self.observe(final)
            unique={}
            for logical_bytes,written_bytes,inode in self.observed.values():
                old=unique.get(inode,(0,0))
                unique[inode]=(max(old[0],logical_bytes),max(old[1],written_bytes))
            logical = sum(v[0] for v in unique.values())
            written = sum(v[1] for v in unique.values())
            if self.category == 'debug' and logical+incoming > self.registry.config['max_debug_job_bytes']:
                self.paused=True
                raise SpaceBlocked('DEBUG_JOB_BUDGET')
            if written+incoming > row['reserved_bytes']:
                self.paused=True
                raise SpaceBlocked('PREDICTED_PEAK_EXCEEDED')
            row.update(written_bytes=written, logical_written_bytes=logical, heartbeat=time.time(),
                billing_paths=sorted(set(row.get('billing_paths',[]))|set(self.new_billing_paths())))
            try:
                row['space'] = self.registry.space(state,self.key,max(incoming,self.registry.remaining(row)),
                    category=self.category,optional_full=self.optional_full,category_used=self.category_used+logical,
                    category_remaining_bytes=max(incoming,row['reserved_bytes']-logical))
            except SpaceBlocked:
                self.paused=True
                row['state']='SPACE_BLOCKED'
                self.registry.save(state)
                raise
            self.registry.save(state)

    def finish(self, result=None, paths=(), error=None):
        if _DEPTH.get()>1:return
        records = artifact_records(paths) if error is None else []
        if error is None and not records:raise RetentionError('SUCCESS_WITHOUT_ARTIFACT_MANIFEST')
        with self.registry.transaction():
            state = self.registry.read();row = state['tasks'][self.key]
            if row.get('token') != self.token:
                raise RetentionError('CLAIM_OWNER_DRIFT')
            row.pop('_control_reserve', None)
            row['billing_paths']=sorted(set(row.get('billing_paths',[]))|set(self.new_billing_paths()))
            row.update(state=('SPACE_BLOCKED' if self.paused else 'FAILED_RECOVERABLE') if error else 'READY',heartbeat=time.time())
            if error:
                row['error'] = str(error)[:1024]
            else:
                if len(json.dumps(result)) > 128*1024:
                    raise RetentionError('RESULT_METADATA_BUDGET')
                row.update(result=result,artifacts=records,reserved_bytes=0,written_bytes=0)
            self.registry.save(state)
            self.finalized=True


@contextmanager
def admission(policy, *, key, directory, predicted, category='ordinary', optional_full=False, category_used=0, reuse_ready=True):
    config = configuration(policy)
    if category not in {'ordinary','debug'}:raise RetentionError('UNREGISTERED_BILLING_CATEGORY')
    if config is None:
        yield None, None
        return
    active = _ACTIVE.get()
    if active is not None:
        if (active.registry.config['pool_id'] != config['pool_id'] or active.registry.root != Path(config['registry_root'])):
            raise RetentionError('NESTED_SHARED_POOL_BINDING_CONFLICT')
        # Only the same task may inherit a reservation; unrelated nested work
        # must have been included in its explicit peak and scope.
        if key != active.key:
            raise RetentionError('NESTED_TASK_IDENTITY_CONFLICT')
        depth=_DEPTH.set(_DEPTH.get()+1)
        try:yield active, None
        finally:_DEPTH.reset(depth)
        return
    directory=safe_path(directory,exists=False)
    ancestor=directory
    while not ancestor.exists():ancestor=ancestor.parent
    members=set(config.get('pool_member_devices') or [Path(policy['data_root']).stat().st_dev])
    if ancestor.stat().st_dev not in members:
        raise RetentionError('OUTPUT_OUTSIDE_VERIFIED_SHARED_POOL')
    registry = Registry(config, policy['data_root'])
    with registry.writer():
        claim=Claim(registry,key,directory,predicted,category=category,optional_full=optional_full,category_used=category_used)
        cached=claim.begin(reuse_ready=reuse_ready)
        if cached is not None:
            yield None,cached
            return
        token=_ACTIVE.set(claim);depth=_DEPTH.set(1)
        try:
            yield claim,None
            if not claim.finalized and not claim.recording_failed:
                claim.finish(error=RetentionError('UNFINISHED_CONTEXT_EXIT_RETAINED'))
        except BaseException as error:
            try:
                if not claim.finalized and not claim.recording_failed:claim.finish(error=error)
            except (OSError, ValueError, RetentionError):
                # Durable prior RUNNING state retains reservation; kernel lock
                # releases, so a later reconciliation fails closed. Read safe.
                pass
            raise
        finally:
            _ACTIVE.reset(token);_DEPTH.reset(depth)


class _AdapterLease:
    def __init__(self, claim):
        self.claim, self.active = claim, True
        self.futures = []

    def owns(self):
        return self.active and _ACTIVE.get() is self.claim

    def retire(self):
        self.active = False
        for reference, originals, wrappers in self.futures:
            future = reference()
            if future is None:
                continue
            for name, wrapper in wrappers.items():
                if future.__dict__.get(name) is wrapper:
                    if name in originals:
                        setattr(future, name, originals[name])
                    else:
                        delattr(future, name)
        self.futures.clear()

    def thread_call(self, function):
        # A distinct Context for each submitted function/callback: Context.run
        # cannot concurrently enter the same Context in multiple workers.
        context = copy_context()
        def call(*args, **kwargs):
            if self.active:
                return context.run(function, *args, **kwargs)
            return function(*args, **kwargs)
        return call


@contextmanager
def _adapter_scope(kind, modules, claim):
    if claim is None or _ACTIVE.get() is not claim:
        yield None, []
        return
    installed = _ADAPTER_SCOPES.get()
    selected = [module for module in modules if not (
        (prior := installed.get((kind, id(module)))) is not None
        and prior.claim is claim and prior.active)]
    if not selected:
        # Includes explicitly propagated workers entering the same adapter;
        # don't try to acquire the installer's thread-owned RLock again.
        yield None, []
        return
    with _ADAPTER_LOCK:
        lease = _AdapterLease(claim)
        state = dict(installed)
        state.update({(kind, id(module)): lease for module in selected})
        token = _ADAPTER_SCOPES.set(state)
        try:
            yield lease, selected
        finally:
            lease.retire()
            _ADAPTER_SCOPES.reset(token)


def _guard_future(future, lease, observe):
    """Keep the actual Future (including wait/as_completed internals)."""
    original_result = future.result
    original_callback = future.add_done_callback
    originals = {name:future.__dict__[name] for name in ('result','add_done_callback') if name in future.__dict__}
    def result(*args, **kwargs):
        value = original_result(*args, **kwargs)
        if lease.owns():
            observe()
        return value
    def add_done_callback(function, *args, **kwargs):
        if lease.owns():
            function = lease.thread_call(function)
        return original_callback(function, *args, **kwargs)
    future.result = result
    future.add_done_callback = add_done_callback
    lease.futures.append((weakref.ref(future), originals, dict(result=result, add_done_callback=add_done_callback)))
    return future


@contextmanager
def qfq_write_seams(module, claim):
    """Caller-scoped gates; foreign threads retain exact original behavior.

    Participating ThreadPool work/callbacks explicitly inherit their admission.
    Process work remains unchanged, guarded at parent submit/result boundaries.
    Module-local pq proxies never mutate shared PyArrow objects.
    """
    with _adapter_scope('qfq', [module], claim) as (lease, _):
        if lease is None:
            yield
            return
        originals = {}
        def replace(name, value):
            originals[name] = getattr(module, name)
            setattr(module, name, value)
        def write(path, payload):
            if not lease.owns():
                return originals['_write'](path, payload)
            path = Path(path)
            claim.watch(path)
            control = str(path) in getattr(claim, 'control_paths', set()) and len(payload) <= 192*1024
            final_receipt = (getattr(claim, 'publication_committed', False)
                and path.name in {'qfq_expected_current.json', 'qfq_readiness.json', 'meta.json', 'task_summary.json', 'stage_status.json'}
                and len(payload) <= 16*MIB)
            if control or final_receipt:
                allowance=getattr(claim,'publication_control_reserved_bytes',0)
                if allowance <= 0 or (final_receipt and allowance != 64*MIB):
                    raise SpaceBlocked('PUBLICATION_CONTROL_NOT_RESERVED')
                claim.control_written = getattr(claim, 'control_written', 0) + len(payload)
                if claim.control_written > allowance:
                    raise SpaceBlocked('PUBLICATION_CONTROL_BUDGET')
            diagnostic = (path.name == 'stage_status.json' and len(payload) <= 64*1024
                          and json.loads(payload).get('status') == 'FAILED')
            if not diagnostic and not control and not final_receipt:
                claim.checkpoint(incoming=len(payload))
            result = originals['_write'](path, payload)
            if lease.owns():
                claim.observe(path)
            return result
        def guarded(function):
            def call(*args, **kwargs):
                if lease.owns():
                    claim.checkpoint()
                return function(*args, **kwargs)
            return call
        class Writer:
            def __new__(cls, *args, **kwargs):
                if not lease.owns():
                    return originals['pq'].ParquetWriter(*args, **kwargs)
                return super().__new__(cls)
            def __init__(self, path, *args, **kwargs):
                self.path = Path(path)
                claim.watch(self.path)
                claim.checkpoint()
                self.inner = originals['pq'].ParquetWriter(path, *args, **kwargs)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                try:
                    return self.inner.__exit__(*args)
                finally:
                    if lease.owns():
                        claim.observe(self.path)
            def __getattr__(self, name):
                return getattr(self.inner, name)
            def write_table(self, table, *args, **kwargs):
                if lease.owns():
                    claim.observe(self.path)
                    claim.checkpoint(incoming=table.nbytes)
                result = self.inner.write_table(table, *args, **kwargs)
                if lease.owns():
                    claim.observe(self.path)
                return result
            def write_batch(self, batch, *args, **kwargs):
                if lease.owns():
                    claim.observe(self.path)
                    claim.checkpoint(incoming=batch.nbytes)
                result = self.inner.write_batch(batch, *args, **kwargs)
                if lease.owns():
                    claim.observe(self.path)
                return result
            def close(self):
                result = self.inner.close()
                if lease.owns():
                    claim.observe(self.path)
                return result
        class ParquetProxy:
            def __getattr__(self, name):
                return getattr(originals['pq'], name)
            ParquetWriter = Writer
            def write_table(self, table, path, *args, **kwargs):
                if lease.owns():
                    claim.watch(path)
                    claim.checkpoint(incoming=table.nbytes)
                result = originals['pq'].write_table(table, path, *args, **kwargs)
                if lease.owns():
                    claim.observe(path)
                return result
        def executor_type(base, *, threaded):
            class Executor:
                def __new__(cls, *args, **kwargs):
                    if not lease.owns():
                        return base(*args, **kwargs)
                    return super().__new__(cls)
                def __init__(self, *args, **kwargs):
                    self.inner = base(*args, **kwargs)
                def __enter__(self):
                    self.inner.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.inner.__exit__(*args)
                def __getattr__(self, name):
                    return getattr(self.inner, name)
                def submit(self, function, *args, **kwargs):
                    if not lease.owns():
                        return self.inner.submit(function, *args, **kwargs)
                    claim.checkpoint()
                    paths = []
                    if getattr(function, '__name__', None) == '_symbol_process_task':
                        payload = args[0]
                        root, code = Path(payload[4]), payload[0]
                        paths = [root/(code+suffix) for suffix in ('.parquet', '.receipt.json')]
                        for path in paths:
                            claim.watch(path)
                    if threaded:
                        function = lease.thread_call(function)
                    future = self.inner.submit(function, *args, **kwargs)
                    def observe():
                        for path in paths:
                            claim.observe(path)
                    return _guard_future(future, lease, observe)
            return Executor
        def checkpoint_function(*args, **kwargs):
            if not lease.owns():
                return originals['_symbol_checkpoint'](*args, **kwargs)
            code, _, _, _, root = args[:5]
            paths = [Path(root)/(code+suffix) for suffix in ('.parquet', '.receipt.json')]
            for path in paths:
                claim.watch(path)
            claim.checkpoint()
            result = originals['_symbol_checkpoint'](*args, **kwargs)
            if lease.owns():
                for path in paths:
                    claim.observe(path)
            return result
        def transaction(name):
            def call(*args, **kwargs):
                if not lease.owns():
                    return originals[name](*args, **kwargs)
                # The64MiB control allowance is carved out of the existing
                # forecast before entering ANY pointer transaction. It is not
                # an additional postcommit quota exemption.
                allowance=64*MIB if name=='publish_pair' else 192*1024
                claim.checkpoint(incoming=allowance)
                claim.publication_control_reserved_bytes=allowance
                if name == 'publish_pair':
                    from ops.research_storage_pair import publication_preflight
                    publication_preflight()
                    pointers, journal = args[0], args[3]
                else:
                    journal, pointers = args[:2]
                prior = getattr(claim, 'control_paths', set())
                claim.control_paths = {str(path) for path in pointers.values()} | {str(journal)}
                try:
                    result = originals[name](*args, **kwargs)
                    if name == 'publish_pair':
                        claim.publication_committed = True
                        from ops.research_storage_pair import publish_configured
                        try:publish_configured(args[1])
                        except (OSError,ValueError,KeyError,RetentionError) as error:
                            claim.pair_recording_error=str(error)[:1024]
                    else:
                        # Original recovery runs under qfq_publish.lock before
                        # inputs/large writes. Reconcile a prior committed pair
                        # gap before allowing another generation to proceed.
                        from ops.research_storage_pair import publish_configured, settings
                        if settings() is not None:
                            publish_configured({role:Path(pointer.read_text(encoding='utf-8-sig').strip())
                                                for role,pointer in pointers.items()})
                    return result
                finally:
                    claim.control_paths = prior
            return call
        try:
            replace('_write', write)
            replace('pq', ParquetProxy())
            replace('spool_current', guarded(module.spool_current))
            for name in ('publish_pair', 'recover_pair'):
                replace(name, transaction(name))
            replace('_symbol_checkpoint', checkpoint_function)
            for name in ('ThreadPoolExecutor', 'ProcessPoolExecutor'):
                replace(name, executor_type(getattr(module, name), threaded=name == 'ThreadPoolExecutor'))
            yield
        finally:
            lease.retire()
            for name, value in originals.items():
                setattr(module, name, value)


def debug_projection(*, policy, source, output_root, symbols=None, columns=None, output_days=20):
    """Project existing computed rows. Full formula history is never truncated.

    This path does no computation. Source date/column values, nulls and discrete
    signals remain exact. It is NOT a replacement for formal formula validation.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    from ops.research_panel_logical import parquet as pq
    config=configuration(policy)
    if config is None:raise RetentionError('DEBUG_GOVERNANCE_REQUIRED')
    source=safe_path(source);root=safe_path(output_root,exists=False)
    approved=[safe_path(path,exists=False) for path in config.get('debug_output_roots',[])]
    if not any(under(root,path) for path in approved):raise RetentionError('DEBUG_OUTPUT_ROOT_NOT_APPROVED')
    dataset=ds.dataset(source,format='parquet')
    if not 1 <= output_days <= 20:raise RetentionError('EXPLICIT_FULL_MODE_REQUIRED')
    if symbols is None:
        found=set()
        for batch in dataset.scanner(columns=['ts_code'],batch_size=1024).to_batches():
            found.update(batch['ts_code'].to_pylist())
            if len(found)>=3:break
        symbols=sorted(found)[:3]
    symbols=list(symbols)
    if not 1 <= len(symbols) <= 3 or len(set(symbols)) != len(symbols):raise RetentionError('DEBUG_SCOPE_MAX_THREE')
    if not all(isinstance(code,str) and __import__('re').fullmatch(r'\d{6}\.(SH|SZ|BJ)',code) for code in symbols):
        raise RetentionError('DEBUG_SYMBOL_IDENTITY')
    columns=list(columns or ['ts_code','trade_date','close'])
    if not {'ts_code','trade_date'}<=set(columns) or not set(columns)<=set(dataset.schema.names):raise RetentionError('DEBUG_COLUMNS')
    # Dates only, then a bounded projection; no formula warmup is recalculated.
    date_table=dataset.to_table(columns=['trade_date'],filter=ds.field('ts_code').isin(symbols))
    dates=sorted(set(date_table['trade_date'].to_pylist()))[-output_days:]
    if not dates:raise RetentionError('DEBUG_SOURCE_EMPTY')
    identity=computation_identity(inputs=dict(source=str(source),stat=stamp(source)),scope=dict(symbols=symbols,dates=dates),
        calculation=dict(projection='existing_rows_v1'),schema=columns)
    directory=root/identity
    budget=config['max_debug_job_bytes']
    used=billing_bytes(root) if root.exists() else 0
    with admission(policy,key=identity,directory=directory,predicted=budget,category='debug',category_used=used) as (claim,cached):
        if cached is not None:return cached
        if directory.exists():
            # Failed partials resume in this same path, only known output names.
            if set(p.name for p in directory.iterdir())-{'projection.parquet','manifest.json'}:raise RetentionError('DEBUG_DIRECTORY_UNKNOWN_FILES')
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/'projection.parquet';claim.watch(path)
        table=dataset.to_table(columns=columns,filter=ds.field('ts_code').isin(symbols)&ds.field('trade_date').isin(dates))
        # Serialize in RAM under the job limit before touching a data file.
        if table.nbytes>config['max_debug_job_bytes']:raise SpaceBlocked('DEBUG_MEMORY_OUTPUT_BUDGET')
        buffer=pa.BufferOutputStream();pq.write_table(table,buffer)
        raw=buffer.getvalue().to_pybytes()
        if len(raw)>config['max_debug_file_bytes']:raise SpaceBlocked('DEBUG_FILE_BUDGET')
        claim.checkpoint(incoming=len(raw))
        atomic_bytes(path,raw);claim.observe(path)
        result=dict(status='READY',identity=identity,output=str(path),symbols=symbols,dates=dates,
                    calculation='NONE_EXISTING_COMPUTED_ROWS',source=str(source),formula_lookback='UNCHANGED_SHARED_SOURCE')
        manifest=directory/'manifest.json';claim.watch(manifest)
        claim.checkpoint(incoming=len(json.dumps(result).encode())*2);atomic_json(manifest,result);claim.observe(manifest)
        claim.finish(result,[path,manifest]);return result


def atomic_bytes(path, payload):
    import tempfile
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def read_only_status(policy):
    """No lock creation, DB recovery, output file, or data mutation on safe reads."""
    config=configuration(policy)
    if config is None:return dict(status='DISABLED',auto_gc_enabled=False,dry_run=True)
    registry=Registry(config,policy['data_root'])
    try:
        state=registry.read()
        usage=shutil.disk_usage(registry.disk_root)
        owned_bytes=billing_bytes(registry.root) if registry.root.exists() else 0
        owned_bytes+=sum(billing_bytes(Path(path)) for path in config.get('extra_owned_roots',[]) if Path(path).exists() and not under(Path(path),registry.root))
        latest={}
        for row in state['tasks'].values():
            if row.get('heartbeat',0)>=latest.get(row['category'],{}).get('heartbeat',0):latest[row['category']]=row
        counts={}
        for row in state['tasks'].values():counts[row['state']]=counts.get(row['state'],0)+1
        return dict(status='READ_ONLY',pool_id=config['pool_id'],states=counts,
            remaining_reservations=sum(registry.remaining(row) for row in state['tasks'].values()
                if row['state'] in {'RUNNING','VALIDATING','FAILED_RECOVERABLE','SPACE_BLOCKED'}),
            free_bytes=usage.free,total_bytes=usage.total,own_bytes=owned_bytes,
            own_budget_bytes=config['own_budget_bytes'],detailed_output_allowed=owned_bytes<config['own_budget_bytes'],
            category_last_observed={key:dict(bytes=row.get('category_baseline_bytes',0)+row.get('logical_written_bytes',0),observed_at=row.get('heartbeat')) for key,row in latest.items()},
            resident_baseline_paths=state.get('resident_baseline_paths'),
            tracked_ordinary_roots=sorted({path for row in state['tasks'].values() if row['category']=='ordinary' for path in row.get('billing_paths',[])}),
            history_24h_7d_30d='DATA_ACCUMULATING_NO_INFERRED_TRENDS',
            auto_gc_enabled=False,dry_run=True,reader_coordination='UNREGISTERED_CONSUMERS_GC_BLOCKED')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RetentionError) as error:
        return dict(status='REGISTRY_UNAVAILABLE_SAFE_READS_UNAFFECTED',error=str(error)[:1024],auto_gc_enabled=False,dry_run=True)


def qfq_invocation_key(module, data_root, target, kwargs):
    snapshot=module.input_path(data_root)
    files={key:dict(path=str(kwargs[key]),sha256=digest(safe_path(kwargs[key])))
           for key in ('driver_path','formula_path','contract_csv')}
    refreshing=kwargs.get('refresh_inputs') is True
    # This is a storage operation key, never a READY numerical cache identity.
    # The original owner refreshes this mutable file INSIDE the admitted call.
    # Binding its pre-refresh SHA creates a second reservation on failed retry.
    # Final numerical inputs/generation remain validated by the unchanged owner
    # and recorded in its result; offline explicit snapshots still bind SHA.
    files['snapshot']=dict(path=str(snapshot),sha256=('OWNER_REFRESHED_TARGET_BOUND_IN_RESULT' if refreshing
        else digest(snapshot) if snapshot.exists() else 'MISSING_PRE_REFRESH'))
    # Exact source bytes, not governance code or an entire repository commit.
    files['owner']=dict(path=module.__file__,sha256=digest(Path(module.__file__)))
    return computation_identity(inputs=files,scope=dict(target=target,market='A',input_scope='OWNER_MANAGED_REFRESH_OPERATION' if refreshing else 'OWNER_SNAPSHOT'),
        calculation=dict(owner_mode='EXISTING_QFQ_GENERATION_AUTHORITY',arguments=json.loads(json.dumps({key:value for key,value in kwargs.items() if key not in {'workers','publish','driver_path','formula_path','contract_csv'}},default=str))),
        schema='a_share_qfq_panel_v1',environment=dict(python=__import__('sys').version))


def verified_qfq_current(module, policy, target, kwargs):
    """Validate exact owner identities and pair integrity, never a READY marker."""
    snapshot=module.load_snapshot(module.input_path(Path(policy['data_root'])),target)
    identity=module.generation_identity(snapshot,kwargs['driver_path'],kwargs['formula_path'],kwargs['contract_csv'])
    from ops.research_panel_turnover import load_daily
    identity['turnover_input_sha256']=load_daily(Path(policy['data_root']),kwargs['tdx_root'],target).identity
    paths={role:safe_path(Path(value).read_text(encoding='utf-8-sig').strip()) for role,value in policy['pointers'].items()}
    if any(not under(path,Path(policy['formal_roots'][role])) for role,path in paths.items()):
        raise RetentionError('CURRENT_FORMAL_PATH_ESCAPE')
    contracts={role:module.panel_contract(path) for role,path in paths.items()}
    ids={row.get('generation_id') for row in contracts.values()}
    if len(ids)!=1 or None in ids or any(row.get('asof_date')!=target or any(row.get(k)!=v for k,v in identity.items()) for row in contracts.values()):
        return None  # Stale cheap control state: use owner, never force rebuilding.
    generation=next(iter(ids))
    run=Path(policy['run_root'])/('qfq_'+generation[:20])
    status=json.loads((run/'stage_status.json').read_bytes())
    receipt=json.loads((run/'candidate_receipt.json').read_bytes())
    if (status.get('status')!='READY' or status.get('generation_id')!=generation
            or status.get('run_dir')!=str(run) or status.get('selector_pointer_ready') is not True
            or status.get('backtest_pointer_ready') is not True
            or any(status.get(key)!=value for key,value in __import__('ops.research_storage_retention',fromlist=['FLAGS']).FLAGS.items())
            or receipt.get('generation_id')!=generation
            or status.get('candidates')!={key:str(value) for key,value in paths.items()}
            or receipt.get('candidate_sha256')!=status.get('candidate_sha256')):
        raise RetentionError('CURRENT_READY_RECEIPT_CONFLICT')
    # Reuse stat-bound prior verification, otherwise verify the exact pair once.
    cache=dict(_ARTIFACT_CACHE)
    config=configuration(policy)
    if config:
        try:
            for row in Registry(config,policy['data_root']).read()['tasks'].values():
                for item in row.get('artifacts',[]):cache[item['path']]=item
        except (OSError,ValueError,KeyError,RetentionError):pass
    for role,path in paths.items():
        prior=cache.get(str(path));observed=stamp(path)
        if prior is None or prior['stat']!=observed or prior['sha256']!=status['candidate_sha256'][role]:
            if digest(path)!=status['candidate_sha256'][role] or stamp(path)!=observed:
                raise RetentionError('CURRENT_ARTIFACT_CORRUPT')
            _ARTIFACT_CACHE[str(path)]=dict(path=str(path),stat=observed,sha256=status['candidate_sha256'][role])
    # The actual retention READY path already holds the original publication
    # lock. Reconcile the single paired commit here as well, so failure after
    # original CURRENT commit cannot strand all future Readers on an old pair.
    # Only bounded footer/receipt/manifest metadata is read; no producer/rehash.
    from ops.research_storage_pair import publish_configured
    pair_manifest=publish_configured(paths)
    pair_state=({'storage_pair':dict(status='VERIFIED_REUSE_PAIR_RECONCILED',id=pair_manifest['id'])}
                if pair_manifest is not None else {})
    return {**status,**pair_state,'already_current':True,'selector':str(paths['selector']),'backtest':str(paths['backtest'])}


def qfq_registry_summary(result):
    """Reference the original complete owner receipts, never copy stock detail.

    Candidate publication precedes registry recording. Both the immutable
    candidate evidence and its READY completion must match this exact result.
    The normal Claim.finish artifact validation and metadata budget still apply.
    """
    from ops.research_storage_retention import FLAGS
    run = safe_path(result['run_dir'])
    refs = {}
    documents = {}
    for name in ('candidate_receipt', 'stage_status'):
        path = safe_path(run / (name + '.json'))
        before = stamp(path)
        raw = path.read_bytes()
        if stamp(path) != before:
            raise RetentionError('QFQ_OWNER_RECEIPT_CHANGED')
        documents[name] = json.loads(raw)
        refs[name] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    candidate, ready = documents['candidate_receipt'], documents['stage_status']
    if (result.get('status') != 'READY' or ready.get('status') != 'READY'
            or candidate.get('status') not in {'CANDIDATE_READY', 'READY'}
            or not ready.get('generation_id')
            or set(ready.get('candidates', {})) != {'selector', 'backtest'}
            or set(ready.get('candidate_sha256', {})) != {'selector', 'backtest'}
            or any(result.get(role) != ready['candidates'][role] for role in ('selector', 'backtest'))
            or ready.get('selector_pointer_ready') is not True
            or ready.get('backtest_pointer_ready') is not True):
        raise RetentionError('QFQ_OWNER_RECEIPT_NOT_READY')
    for document in (candidate, ready):
        if (any(document.get(key) != ready.get(key) for key in
                ('generation_id', 'target_date', 'run_dir', 'candidates', 'candidate_sha256'))
                or any(document.get(key) != value for key, value in FLAGS.items())):
            raise RetentionError('QFQ_OWNER_RECEIPT_CONFLICT')
    # The original idempotent owner intentionally returns a smaller shape.
    # Only this exact shape may omit fields present in its complete receipts.
    identity_keys = ('generation_id', 'candidates', 'candidate_sha256')
    idempotent = result.get('already_current') is True
    if (any(result.get(key) != ready.get(key) for key in ('target_date', 'run_dir'))
            or any(result.get(key) != value for key, value in FLAGS.items())
            or any((key not in result and not idempotent)
                   or (key in result and result[key] != ready.get(key)) for key in identity_keys)):
        raise RetentionError('QFQ_OWNER_RECEIPT_CONFLICT')
    if idempotent:
        authority = result.get('authority') or {}
        if (authority.get('final_status') != 'PASS_QFQ_FULL_HISTORY_IDEMPOTENT'
                or authority.get('generation_id') != ready['generation_id']
                or authority.get('source_sha256') != ready.get('input_sha256')
                or not ready.get('input_sha256')
                or result.get('selector_pointer_ready') is not True
                or result.get('backtest_pointer_ready') is not True):
            raise RetentionError('QFQ_OWNER_IDEMPOTENT_RECEIPT_CONFLICT')
    return dict(schema='qfq_registry_owner_receipt_summary.v1', status='READY',
        generation_id=ready['generation_id'], target_date=ready['target_date'],
        selector=result['selector'], backtest=result['backtest'],
        candidate_sha256=ready['candidate_sha256'],
        complete_owner_receipt=refs['candidate_receipt'],
        ready_owner_receipt=refs['stage_status'], **FLAGS)


def governed_qfq(rebuild, policy, reservation, *, data_root, return_root, pointers, target, **kwargs):
    import importlib
    module=importlib.import_module('ops.research_panel_qfq')
    key=qfq_invocation_key(module,data_root,target,kwargs)
    # Root is unchanged: QFQ chooses its exact generation directory and resumes
    # compatible completed stocks using its existing full identity checks.
    with admission(policy,key=key,directory=return_root,predicted=reservation['predicted_bytes'],
            category_used=0,reuse_ready=False) as (claim,_):
        with qfq_write_seams(module,claim), input_write_seams(claim):
            result=rebuild(data_root=data_root,return_root=return_root,pointers=pointers,target=target,**kwargs)
        if claim:
            if getattr(claim,'pair_recording_error',None):
                result['storage_pair']=dict(status='RECONCILIATION_REQUIRED_OLD_IMMUTABLE_PAIR_RETAINED',error=claim.pair_recording_error)
            if result.get('status')=='READY':
                try:claim.finish(qfq_registry_summary(result),[result['selector'],result['backtest']])
                except (OSError,ValueError,RetentionError) as error:
                    claim.recording_failed=True
                    result['storage_governance']=dict(status='COMMITTED_REGISTRY_RECORDING_BLOCKED',error=str(error)[:1024])
            else:claim.finish(error=RetentionError('OWNER_NOT_READY:'+str(result.get('status'))))
        return result


def configured_policy():
    from ops.research_storage_retention import load_policy
    path=os.environ.get('V4_RESEARCH_RETENTION_POLICY');sha=os.environ.get('V4_RESEARCH_RETENTION_POLICY_SHA256')
    if not path and not sha:return None
    if not path or not sha:raise RetentionError('POLICY_PATH_AND_SHA_REQUIRED')
    policy=load_policy(Path(path),expected_sha256=sha)
    from ops.research_storage_retention import read_json
    inventory=read_json(Path(policy['managed_pin_inventory']['path']))
    if digest(Path(policy['managed_pin_inventory']['path']))!=policy['managed_pin_inventory']['sha256']:
        raise RetentionError('MANAGED_PIN_INVENTORY_HASH_DRIFT')
    if inventory.get('expected_main_app_root')!=str(Path(__file__).resolve().parents[1]):
        raise RetentionError('MAIN_APP_ROOT_BINDING_FAILED')
    return policy


def governed_product(function, /, *args, **kwargs):
    from ops.research_storage_pair import request_binding
    data = kwargs.get('data_root', args[0] if args else None)
    with request_binding(data):
        return _governed_product(function, *args, **kwargs)


def daily_derivatives_registry_summary(result):
    """Bounded registry metadata; immutable owner receipts retain full detail.

    The daily owner writes its attempt before the F10 continuation. Therefore
    validate every original field against that attempt, and bind F10 separately
    to the same exact attempt. Publication index/before hashes are historical
    CAS evidence: F10 may legitimately advance the shared index afterwards.
    """
    from ops.research_storage_retention import FLAGS

    def document(ref):
        path = safe_path(ref['path'])
        before = stamp(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref['sha256'] or stamp(path) != before:
            raise RetentionError('DERIVATIVES_OWNER_RECEIPT_DRIFT')
        return json.loads(raw)

    attempt = document(result['attempt'])
    original = {key: value for key, value in result.items()
                if key not in {'attempt', 'f10', 'storage_governance'}}
    if (original != attempt or attempt.get('schema') != 'V4_A_DAILY_DERIVATIVES_V1'
            or attempt.get('status') != 'COMPLETE_DESCRIPTIVE_NONPIT'
            or attempt.get('completeness_scope') != 'CURRENT_DAY_DERIVATIVES'
            or not attempt.get('data_date') or not attempt.get('source_generation')
            or any(attempt.get(key) != value for key, value in FLAGS.items())):
        raise RetentionError('DERIVATIVES_OWNER_RECEIPT_CONFLICT')
    day, generation = attempt['data_date'], attempt['source_generation']
    numeric = attempt['completed_source_provenance']['numeric_manifest']
    # Resolve the immutable published Top200 through the existing owner index.
    # Do not compare its current bytes to the earlier publication CAS hash.
    publication = attempt['top200']
    if publication.get('status') == 'REUSED':
        top_ref = publication['artifact']
    elif publication.get('status') == 'PUBLISHED_TOP200':
        index = json.loads(safe_path(publication['index']['path']).read_bytes())
        if index.get('dates', {}).get(day) != numeric:
            raise RetentionError('DERIVATIVES_NUMERIC_BINDING_DRIFT')
        top_ref = index['top200'][day]
    else:
        raise RetentionError('DERIVATIVES_TOP200_NOT_PUBLISHED')
    top = document(top_ref)
    if (top.get('schema') != 'V4_A_SHARE_TOP200_V1' or top.get('data_date') != day
            or top.get('source_generation') != generation or top.get('numeric_manifest') != numeric
            or any(top.get(key) != value for key, value in FLAGS.items())):
        raise RetentionError('DERIVATIVES_TOP200_BINDING_DRIFT')
    summary = dict(schema='v4.a_share.daily_derivatives_registry_summary.v1',
        status=result['status'], completeness_scope=result['completeness_scope'],
        data_date=day, source_generation=generation, complete_owner_receipt=result['attempt'],
        history_status=result['history_status'], historical_completion=result['historical_completion'],
        history_bootstrap_in_daily_path=result['history_bootstrap_in_daily_path'],
        history={key: result['history'][key] for key in
                 ('candidate_count', 'complete_stocks', 'incomplete_stocks', 'missing_label_date_count')
                 if key in result['history']},
        top200=dict(status=publication['status'], artifact=top_ref,
                    top200_count=top.get('top200_count')), **FLAGS)
    if 'f10' in result:
        returned = result['f10']
        f10 = document(returned['receipt'])
        if (f10.get('schema') not in {'v4.a_share.f10_daily_receipt.v1', 'v4.a_share.f10_daily_failure.v1'}
                or f10.get('data_date') != day or f10.get('source_generation') != generation
                or f10.get('upstream_success_receipt') != result['attempt']
                or f10.get('status') != returned.get('status')
                or any(f10.get(key) != value for key, value in FLAGS.items())):
            raise RetentionError('DERIVATIVES_F10_BINDING_DRIFT')
        summary['f10'] = dict(status=f10['status'], complete_owner_receipt=returned['receipt'])
        if f10['schema'] == 'v4.a_share.f10_daily_receipt.v1':
            counts = dict(requested=f10['requested'], observed=f10['observed'],
                          failure_count=len(f10['failures']), remaining_count=len(f10['remaining']))
            if any(returned.get(key) != value for key, value in counts.items()):
                raise RetentionError('DERIVATIVES_F10_COUNTS_DRIFT')
            summary['f10'].update(counts)
    return summary


def _governed_product(function, /, *args, **kwargs):
    """Actual daily/Top200/recovery callsites; original producer keeps ownership.

    No cache shortcut: the original producer validates/reuses immutable results.
    Guards run at stock, stage and existing save boundaries. Direct unregistered
    scripts and writer helpers bypassing these boundaries remain explicit gaps.
    """
    policy=configured_policy()
    if not policy or not configuration(policy):return function(*args,**kwargs)
    if any(kwargs.get(key) is not None for key in ('evaluate','chart_png_renderer')):
        raise RetentionError('UNREGISTERED_COMPUTATION_CALLBACK')
    import importlib
    owner=importlib.import_module('ops.research_panel_daily_product')
    data=Path(kwargs.get('data_root',args[0] if args else policy['data_root']))
    target=int(kwargs.get('target',args[1] if len(args)>1 else 0))
    context=owner.SourceContext(data,target)
    root=safe_path(kwargs.get('output_root') or (args[2] if len(args)>2 else context.root),exists=False)
    approved=[safe_path(path,exists=False) for path in configuration(policy).get('product_output_roots',[])]
    if not any(under(root,path) for path in approved):raise RetentionError('PRODUCT_OUTPUT_ROOT_NOT_APPROVED')
    selected=kwargs['symbols'] if kwargs.get('symbols') is not None else sorted(context.scope)
    key=computation_identity(inputs=dict(source=context.identity,config=context.config_ref),
        scope=dict(symbols=selected,history_dates=list(kwargs.get('history_dates',())),target=target),
        calculation=dict(owner=reference_source(owner.__file__),entry=function.__name__,
            top200=reference_source(function.__globals__.get('__file__',owner.__file__))),schema='existing_daily_product_v1')
    forecast=policy['governance'].get('product_peak_bytes')
    if not isinstance(forecast,int) or isinstance(forecast,bool) or forecast<=0:
        raise RetentionError('FORMAL_PRODUCT_FORECAST_REQUIRED')
    used=billing_bytes(root) if root.exists() else 0
    with admission(policy,key=key,directory=root,predicted=forecast,category_used=used,reuse_ready=False) as (claim,_):
        modules=[owner]
        parallel=importlib.import_module('ops.research_daily_product_parallel')
        projection=importlib.import_module('ops.render_original_formula_projection')
        modules.extend([parallel,projection])
        if function.__module__!='ops.research_panel_daily_product':modules.append(importlib.import_module(function.__module__))
        with product_write_seams(modules,claim):result=function(*args,**kwargs)
        # Product/status response may be partial; retain exact recovery points,
        # never claim READY just because an index exists.
        if claim:
            index=root/'index.json'
            if index.is_file() and result.get('status') not in {'FAILED','CANNOT_CONFIRM'}:
                try:
                    metadata = (daily_derivatives_registry_summary(result)
                                if result.get('schema') == 'V4_A_DAILY_DERIVATIVES_V1' else result)
                    claim.finish(metadata,[index])
                except (OSError,ValueError,RetentionError) as error:
                    claim.recording_failed=True
                    result['storage_governance']=dict(status='COMMITTED_REGISTRY_RECORDING_BLOCKED',error=str(error)[:1024])
            else:claim.finish(error=RetentionError('PRODUCT_PARTIAL_RETAINED'))
            # The owner has already published numeric/index and committed its
            # original receipt. Maintenance never changes that result or gate.
            if claim.finalized and not claim.recording_failed:
                _after_product_compaction(claim, context, root, args, kwargs, result)
        return result


def _after_product_compaction(claim, context, root, args, kwargs, result):
    if result.get('schema') != 'V4_A_DAILY_DERIVATIVES_V1' or result.get('status') != 'COMPLETE_DESCRIPTIVE_NONPIT':
        return
    try:
        from ops.research_storage_compaction import completed_event
        receipts = kwargs.get('receipt_root', args[3] if len(args) > 3 else None)
        if receipts is None:raise RetentionError('COMPACTION_COMPLETION_RECEIPT_ROOT_REQUIRED')
        completed_event(claim=claim, context=context, product_root=root,
            receipt_root=Path(receipts), result=result)
    except Exception as error:
        # Keep housekeeping failures outside business receipts, registry READY
        # metadata and delivery eligibility. No exception escapes this seam.
        try:atomic_json(claim.registry.root/'compaction/last_event_error.json',
            dict(schema='v4.daily_storage_compaction.v1',status='FAILED',error=str(error)[:1024],
                RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))
        except (OSError,ValueError,RetentionError):pass


def reference_source(path):
    path=safe_path(path);return dict(path=str(path),sha256=digest(path))


@contextmanager
def product_write_seams(modules, claim):
    with _adapter_scope('product', modules, claim) as (lease, selected):
        if lease is None:
            yield
            return
        originals = []
        def replace(module, name, value):
            originals.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        def save(original):
            def call(path, value, *args, **kwargs):
                if not lease.owns():
                    return original(path, value, *args, **kwargs)
                path = Path(path)
                claim.watch(path)
                size = len(json.dumps(value, default=str).encode())
                diagnostic = (path.name in {'publication_error.json', 'latest_receipt.json'} and size <= 64*1024
                    and isinstance(value, dict) and value.get('status') == 'CANNOT_CONFIRM')
                if not diagnostic:
                    claim.checkpoint(incoming=size*2)
                result = original(path, value, *args, **kwargs)
                if lease.owns():
                    claim.observe(path)
                return result
            return call
        def boundary(original):
            def call(*args, **kwargs):
                if not lease.owns():
                    return original(*args, **kwargs)
                claim.checkpoint()
                result = original(*args, **kwargs)
                if not lease.owns():
                    return result
                if original.__name__ in {'retain_owner_result', 'finalize_owner_charts'} and len(args) >= 2:
                    directory = Path(args[1])
                    paths = ([directory/'original_retained'/(args[2]+'.json.gz')] if original.__name__ == 'retain_owner_result'
                        else list(billing_files(directory)))
                    for path in paths:
                        if path not in claim.baselines:
                            claim.baselines[path] = (0, 0)
                        claim.observe(path)
                if original.__name__ in {'run_incremental_history', 'publish_current_history_view', 'build', 'stage', 'finalize_owner_charts'}:
                    root = Path(claim.directory)
                    if root.exists():
                        for path in billing_files(root):
                            if path not in claim.baselines:
                                claim.baselines[path] = (0, 0)
                            claim.observe(path)
                claim.checkpoint()
                return result
            return call
        def executor_type(base, *, threaded):
            class Executor:
                def __new__(cls, *args, **kwargs):
                    if not lease.owns():
                        return base(*args, **kwargs)
                    return super().__new__(cls)
                def __init__(self, *args, **kwargs):
                    initargs = kwargs.get('initargs', ())
                    self.parts = Path(initargs[3]) if len(initargs) >= 4 else None
                    self.root = Path(initargs[2]) if len(initargs) >= 4 else None
                    self.inner = base(*args, **kwargs)
                def __enter__(self):
                    self.inner.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.inner.__exit__(*args)
                def __getattr__(self, name):
                    return getattr(self.inner, name)
                def submit(self, function, *args, **kwargs):
                    if not lease.owns():
                        return self.inner.submit(function, *args, **kwargs)
                    paths = []
                    symbol = args[0] if args and isinstance(args[0], str) else None
                    if self.parts is not None and symbol is not None:
                        paths = [self.parts/(symbol+'.json'), self.parts/'original_retained'/(symbol+'.json.gz')]
                        for path in paths:
                            claim.watch(path)
                    claim.checkpoint()
                    if threaded:
                        function = lease.thread_call(function)
                    future = self.inner.submit(function, *args, **kwargs)
                    def observe():
                        if self.root is not None and symbol is not None:
                            paths.extend(self.root.glob('history/*/'+symbol+'/checkpoint.json'))
                        for path in paths:
                            if path not in claim.baselines:
                                claim.baselines[path] = (0, 0)
                            claim.observe(path)
                    return _guard_future(future, lease, observe)
            return Executor
        try:
            for module in selected:
                for name in ('ThreadPoolExecutor', 'ProcessPoolExecutor'):
                    if hasattr(module, name):
                        replace(module, name, executor_type(getattr(module, name), threaded=name == 'ThreadPoolExecutor'))
                if hasattr(module, 'save'):
                    replace(module, 'save', save(module.save))
                if hasattr(module, 'write_json'):
                    replace(module, 'write_json', save(module.write_json))
                for name in ('compute_stock', 'run_incremental_history', 'publish_current_history_view', 'build', 'stage', 'record_daily_attempt', 'retain_owner_result', 'finalize_owner_charts', 'owner_pngs'):
                    if hasattr(module, name):
                        replace(module, name, boundary(getattr(module, name)))
            yield
        finally:
            lease.retire()
            for module, name, value in reversed(originals):
                setattr(module, name, value)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--policy-sha256',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    project=sub.add_parser('project')
    project.add_argument('--source',type=Path,required=True)
    project.add_argument('--output-root',type=Path,required=True)
    project.add_argument('--symbols',nargs='+')
    project.add_argument('--columns',nargs='+')
    args=parser.parse_args()
    from ops.research_storage_retention import load_policy
    policy=load_policy(args.policy,expected_sha256=args.policy_sha256)
    result=(read_only_status(policy) if args.command=='status' else debug_projection(policy=policy,
        source=args.source,output_root=args.output_root,symbols=args.symbols,columns=args.columns))
    print(json.dumps(result,ensure_ascii=False,default=str))


if __name__=='__main__':main()


def input_forecast(tdx_root):
    root=safe_path(tdx_root)
    native=[path for path in billing_files(root) if path.suffix.lower()=='.day']
    native_bytes=sum(path.stat().st_size for path in native)
    return dict(predicted_bytes=2*native_bytes+64*MIB,native_bytes=native_bytes,
                native_files=len(native),basis='two existing native copies +32MiB bounded official package +32MiB response/control')


@contextmanager
def input_preflight(*, tdx_root, receipt_root, target):
    """Actual raw-sync facade, before download/module invocation.

    Protected raw inputs are not ordinary-reclaimable residents. This temporary
    ordinary peak reservation bounds the source operation, while existing raw
    bytes remain reflected in real filesystem free space. The source keeps its
    existing per-request limits and native recovery semantics.
    """
    policy=configured_policy()
    if not policy or not configuration(policy):
        yield None
        return
    root=safe_path(tdx_root)
    # Existing source writes one accepted full-file view and can stage one native
    # rewrite; conservatively reserve twice the exact native inventory plus the
    # existing official package maximum32MiB and response/control headroom32MiB.
    predicted=input_forecast(root)['predicted_bytes']
    directory=safe_path(Path(receipt_root)/'a_sync_authority'/str(target),exists=False)
    key=computation_identity(inputs=dict(native_root=str(root)),scope=dict(target=str(target),market='A'),
        calculation=dict(entry='existing_raw_sync',source=reference_source(__file__)),schema='raw_sync_storage_only_v1')
    with admission(policy,key=key,directory=directory,predicted=predicted,reuse_ready=False) as (claim,_):
        yield claim
        if claim:
            # Raw provenance remains protected; this is not a READY derived
            # artifact or future deletion credential. A tiny storage receipt is
            # sufficient to release the operation's peak reservation.
            receipt=claim.registry.root/('input_'+key+'.json')
            atomic_json(receipt,dict(key=key,status='SOURCE_OPERATION_COMPLETED',
                source_directory=str(directory),protected_raw=True,predicted_bytes=predicted))
            claim.finish(dict(status='SOURCE_OPERATION_COMPLETED'),[receipt])


@contextmanager
def input_write_seams(claim):
    """Catch imported-by-value helper aliases at their real existing boundaries.

    Source files/algorithm identities stay byte-identical. These modules are
    installed only in the admitted QFQ call context and retired with its lease.
    Direct standalone invocations remain explicitly outside this scoped adapter.
    """
    if claim is None:yield;return
    import importlib
    modules=[importlib.import_module('ops.'+name) for name in (
        'research_panel_adjustment_inputs','research_panel_tdx_adjustment_inputs',
        'research_panel_daily_source','research_panel_factor_cache')]
    with _adapter_scope('input',modules,claim) as (lease,selected):
        if lease is None:yield;return
        originals=[]
        for module in selected:
            for name in ('_write','_save_bytes','_json'):
                if not hasattr(module,name):continue
                original=getattr(module,name);originals.append((module,name,original))
                def guarded(path,payload,*args,_original=original,_name=name,**kwargs):
                    if not lease.owns():return _original(path,payload,*args,**kwargs)
                    path=Path(path);claim.watch(path)
                    size=len(json.dumps(payload,default=str).encode())*2 if _name=='_json' else len(payload)
                    claim.checkpoint(incoming=size)
                    result=_original(path,payload,*args,**kwargs)
                    if lease.owns():claim.observe(path)
                    return result
                setattr(module,name,guarded)
        tdx=next(m for m in selected if m.__name__.endswith('research_panel_tdx_adjustment_inputs'))
        original_fallback=tdx.build_fallback
        originals.append((tdx,'build_fallback',original_fallback))
        def fallback(root,codes,target,**kwargs):
            if not lease.owns():return original_fallback(root,codes,target,**kwargs)
            factory=kwargs.get('parser_factory')
            class Parser:
                def get_df(self,path):
                    selected_factory=factory
                    if selected_factory is None:
                        # Same original parser and pin/gates, loaded at the
                        # exact point the existing owner would instantiate it.
                        import importlib.util
                        config=json.loads((Path(root)/'qfq_tdx_official_source.json').read_bytes())
                        spec=importlib.util.spec_from_file_location('qfq_official_gbbq_parser',config['parser']['path'])
                        parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
                        selected_factory=parser.GbbqReader
                    frame=selected_factory().get_df(path)
                    class Frame:
                        def __len__(self):return len(frame)
                        def __getattr__(self,name):return getattr(frame,name)
                        def __getitem__(self,key):return frame[key]
                        def to_parquet(self,path,*args,**kw):
                            if not lease.owns():return frame.to_parquet(path,*args,**kw)
                            path=Path(path);claim.watch(path)
                            claim.checkpoint(incoming=int(frame.memory_usage(index=True,deep=True).sum())+64*1024)
                            result=frame.to_parquet(path,*args,**kw)
                            if lease.owns():claim.observe(path)
                            return result
                    return Frame()
            return original_fallback(root,codes,target,**{**kwargs,'parser_factory':Parser})
        tdx.build_fallback=fallback
        try:yield
        finally:
            lease.retire()
            for module,name,original in reversed(originals):setattr(module,name,original)


def raw_write_size(name, payload):
    """Measure the existing raw owner's on-disk serializer, not a JSON proxy.

    JSON/CSV helpers write directly; only _atomic_write_bytes stages a second
    file. In either case incoming is one new encoded payload alongside the
    already observed allocations, not twice an unrelated serialization.
    """
    if name == '_atomic_write_bytes':return len(payload)
    if name == 'write_json':
        encoder=json.JSONEncoder(ensure_ascii=False,indent=2,default=str)
        return sum(len(chunk.encode('utf-8')) for chunk in encoder.iterencode(payload))
    if name != 'write_csv':raise RetentionError('UNKNOWN_RAW_WRITE_SERIALIZER')
    class Counter:
        # utf-8-sig writes one BOM, including for an empty CSV header.
        size=3
        def write(self, value):
            self.size+=len(value.encode('utf-8'))
            return len(value)
    counter=Counter()
    keys=list(dict.fromkeys(key for row in payload for key in row))
    writer=csv.DictWriter(counter,fieldnames=keys)
    writer.writeheader()
    for row in payload:writer.writerow({key:row.get(key) for key in keys})
    return counter.size


def guarded_raw_run(module,args,claim):
    if claim is None:return module.run(args)
    with _adapter_scope('raw',[module],claim) as (lease,_):
        if lease is None:return module.run(args)
        originals=[]
        for name in ('_atomic_write_bytes','write_json','write_csv'):
            if not hasattr(module,name):continue
            original=getattr(module,name);originals.append((name,original))
            def guarded(path,payload,*a,_original=original,_name=name,**kw):
                if not lease.owns():return _original(path,payload,*a,**kw)
                path=Path(path);claim.watch(path)
                size=raw_write_size(_name,payload)
                claim.checkpoint(incoming=size)
                result=_original(path,payload,*a,**kw)
                if lease.owns():claim.observe(path)
                return result
            setattr(module,name,guarded)
        try:
            claim.checkpoint()
            return module.run(args)
        finally:
            lease.retire()
            for name,original in reversed(originals):setattr(module,name,original)
