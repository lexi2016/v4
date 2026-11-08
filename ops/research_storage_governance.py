"""Nondeleting admission for registered V4 materializers.

One shared pool registry and kernel writer lock; no filesystem quota, GC, collector,
new data layout or formula computation. Unregistered callers remain outside scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
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

from ops.research_storage_retention import (RetentionError, atomic_json, canonical,
    digest, safe_path, stamp, logical_bytes, under, files)

SCHEMA = 'v4_storage_governance_v2'
GIB = 1024**3
MIB = 1024**2
_ACTIVE = ContextVar('v4_storage_claim', default=None)
_DEPTH = ContextVar('v4_storage_depth', default=0)
_ARTIFACT_CACHE = {}
_ADAPTER_LOCK = threading.RLock()


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
    value['resident_policy']={key:policy.get(key) for key in ('pointers','formal_roots','run_root','data_root')}
    if set(policy.get('formal_roots',{}))=={'selector','backtest'} and set(policy.get('pointers',{}))=={'selector','backtest'}:
        value['creation_roots']=[policy['run_root'],*policy['formal_roots'].values()]
    else:
        value['accounting_roots']['ordinary'].append(policy['run_root'])
        value['creation_roots']=[]
    value['extra_owned_roots']=[str(Path(policy['run_root'])/'storage_retention_ownership')]
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
    if len(rollback)!=1:raise RetentionError('ORDINARY_ROLLBACK_RESIDENT_UNKNOWN')
    paths=[]
    for item in (current[0],rollback[0]):
        paths.extend(item['status']['candidates'].values())
        paths.append(str(item['run']/'symbol_checkpoints'))
    for path in paths:safe_path(path)
    return paths


def unique_roots(paths):
    roots={Path(path) for path in paths}
    return {path for path in roots if not any(path!=other and under(path,other) for other in roots)}


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
            if (not isinstance(row,dict) or row.get('state') not in {'RUNNING','VALIDATING','READY','FAILED_RECOVERABLE','SPACE_BLOCKED'}
                    or row.get('category') not in {'ordinary','debug'}
                    or any(type(row.get(field)) is not int or row[field]<0 for field in ('reserved_bytes','written_bytes'))
                    or row['written_bytes']>row['reserved_bytes']):
                raise RetentionError('REGISTRY_TASK_SCHEMA')
            safe_path(row['directory'],exists=False)
        return value

    def save(self, value):
        raw = json.dumps(value).encode()
        if len(raw) > self.config['max_registry_bytes'] or len(value['tasks']) > self.config['max_tasks']:
            raise RetentionError('REGISTRY_BUDGET_PROTECTED_EVIDENCE_RETAINED')
        # No rotation/deletion of evidence. Stop new materialization on this bound.
        extra=sum(billing_bytes(Path(path)) for path in self.config.get('extra_owned_roots',[]) if Path(path).exists() and not under(Path(path),self.root))
        if billing_bytes(self.root) + extra + 2*len(raw) > self.config['own_budget_bytes']:
            raise RetentionError('GOVERNANCE_OWN_OUTPUT_BUDGET')
        atomic_json(self.path, value)

    def remaining(self, record):
        return max(0, record['reserved_bytes'] - record.get('written_bytes', 0))

    def space(self, state, key, remaining, *, category, optional_full, category_used=0):
        usage = shutil.disk_usage(self.disk_root)
        ratio = usage.free / usage.total
        if ratio < self.config['minimum_free_ratio'] or (optional_full and ratio < self.config['optional_full_min_ratio']):
            raise SpaceBlocked('SPACE_RATIO_BLOCKED')
        others = sum(self.remaining(row) for task, row in state['tasks'].items()
                     if task != key and row['state'] in {'RUNNING','VALIDATING','FAILED_RECOVERABLE','SPACE_BLOCKED'})
        if usage.free - others - remaining < self.config['reserve_bytes'] + self.config['safety_bytes']:
            raise SpaceBlocked('SPACE_RESERVATION_BLOCKED')
        limit = self.config['debug_budget_bytes'] if category == 'debug' else self.config['ordinary_peak_budget_bytes']
        category_remaining=sum(self.remaining(row) for task,row in state['tasks'].items()
            if task!=key and row['category']==category and row['state'] in {'RUNNING','VALIDATING','FAILED_RECOVERABLE','SPACE_BLOCKED'})
        if category_used + category_remaining + remaining > limit:
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
            self.registry.save(state)
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
                    category=self.category,optional_full=self.optional_full,category_used=self.category_used+logical)
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


@contextmanager
def qfq_write_seams(module, claim):
    """Scoped interception of existing parent/batch/write seams; source unchanged.

    One shared writer is held. Module-local pq proxy never mutates PyArrow.
    Spawn workers are checked at parent submit/result boundaries; at most the
    existing bounded worker batch is in flight. No kill or formula interruption.
    """
    if claim is None:
        yield
        return
    with _ADAPTER_LOCK:
        originals = {}
        def replace(name,value):
            originals[name]=getattr(module,name);setattr(module,name,value)
        def write(path,payload):
            path=Path(path);claim.watch(path)
            # A bounded failure/checkpoint receipt remains possible after pause;
            # no data write is disguised as an arbitrary small JSON exemption.
            control=(str(path) in getattr(claim,'control_paths',set()) and len(payload)<=192*1024)
            final_receipt=(getattr(claim,'publication_committed',False)
                and path.name in {'qfq_expected_current.json','qfq_readiness.json','meta.json','task_summary.json','stage_status.json'}
                and len(payload)<=16*MIB)
            if control or final_receipt:
                claim.control_written=getattr(claim,'control_written',0)+len(payload)
                if claim.control_written>64*MIB:raise SpaceBlocked('PUBLICATION_CONTROL_BUDGET')
            diagnostic=(path.name=='stage_status.json' and len(payload)<=64*1024
                        and json.loads(payload).get('status')=='FAILED')
            if not diagnostic and not control and not final_receipt:claim.checkpoint(incoming=len(payload))
            originals['_write'](path,payload);claim.observe(path)
        def guarded(function):
            def call(*args,**kwargs):
                claim.checkpoint();return function(*args,**kwargs)
            return call
        class Writer:
            def __init__(self,path,*args,**kwargs):
                self.path=Path(path);claim.watch(self.path);claim.checkpoint()
                self.inner=originals['pq'].ParquetWriter(path,*args,**kwargs)
            def __enter__(self):return self
            def __exit__(self,*args):
                try:return self.inner.__exit__(*args)
                finally:claim.observe(self.path)
            def __getattr__(self,name):return getattr(self.inner,name)
            def write_table(self,table,*args,**kwargs):
                claim.observe(self.path);claim.checkpoint(incoming=table.nbytes)
                result=self.inner.write_table(table,*args,**kwargs);claim.observe(self.path);return result
            def write_batch(self,batch,*args,**kwargs):
                claim.observe(self.path);claim.checkpoint(incoming=batch.nbytes)
                result=self.inner.write_batch(batch,*args,**kwargs);claim.observe(self.path);return result
            def close(self):
                result=self.inner.close();claim.observe(self.path);return result
        class ParquetProxy:
            def __getattr__(self,name):return getattr(originals['pq'],name)
            ParquetWriter=Writer
            def write_table(self,table,path,*args,**kwargs):
                claim.watch(path);claim.checkpoint(incoming=table.nbytes)
                result=originals['pq'].write_table(table,path,*args,**kwargs);claim.observe(path);return result
        def executor_type(base):
            class Executor:
                def __init__(self,*args,**kwargs):self.inner=base(*args,**kwargs)
                def __enter__(self):self.inner.__enter__();return self
                def __exit__(self,*args):return self.inner.__exit__(*args)
                def __getattr__(self,name):return getattr(self.inner,name)
                def submit(self,function,*args,**kwargs):
                    claim.checkpoint()
                    # Owner checkpoint naming is fixed and verified from source.
                    paths=[]
                    if function.__name__=='_symbol_process_task':
                        payload=args[0];root=Path(payload[4]);code=payload[0]
                        paths=[root/(code+suffix) for suffix in ('.parquet','.receipt.json')]
                        for path in paths:claim.watch(path)
                    future=self.inner.submit(function,*args,**kwargs)
                    class Future:
                        def __getattr__(self,name):return getattr(future,name)
                        def result(self,*a,**k):
                            result=future.result(*a,**k)
                            for path in paths:claim.observe(path)
                            return result
                    return Future()
            return Executor
        def checkpoint_function(*args,**kwargs):
            code,_,_,_,root=args[:5]
            paths=[Path(root)/(code+suffix) for suffix in ('.parquet','.receipt.json')]
            for path in paths:claim.watch(path)
            claim.checkpoint();result=originals['_symbol_checkpoint'](*args,**kwargs)
            for path in paths:claim.observe(path)
            return result
        try:
            replace('_write',write)
            replace('pq',ParquetProxy())
            replace('spool_current',guarded(module.spool_current))
            def transaction(name):
                def call(*args,**kwargs):
                    if name=='publish_pair':
                        claim.checkpoint(incoming=64*MIB)
                        pointers,journal=args[0],args[3]
                    else:
                        journal,pointers=args[:2]
                        # Recovery is only a bounded owner control transaction.
                    prior=getattr(claim,'control_paths',set())
                    claim.control_paths={str(path) for path in pointers.values()}|{str(journal)}
                    try:
                        result=originals[name](*args,**kwargs)
                        if name=='publish_pair':claim.publication_committed=True
                        return result
                    finally:claim.control_paths=prior
                return call
            for name in ('publish_pair','recover_pair'):replace(name,transaction(name))
            replace('_symbol_checkpoint',checkpoint_function)
            for name in ('ThreadPoolExecutor','ProcessPoolExecutor'):
                replace(name,executor_type(getattr(module,name)))
            yield
        finally:
            for name,value in originals.items():setattr(module,name,value)


def debug_projection(*, policy, source, output_root, symbols=None, columns=None, output_days=20):
    """Project existing computed rows. Full formula history is never truncated.

    This path does no computation. Source date/column values, nulls and discrete
    signals remain exact. It is NOT a replacement for formal formula validation.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
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
    files['snapshot']=dict(path=str(snapshot),sha256=digest(snapshot) if snapshot.exists() else 'MISSING_PRE_REFRESH')
    # Exact source bytes, not governance code or an entire repository commit.
    files['owner']=dict(path=module.__file__,sha256=digest(Path(module.__file__)))
    return computation_identity(inputs=files,scope=dict(target=target,market='A',input_scope='OWNER_SNAPSHOT'),
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
    return {**status,'already_current':True,'selector':str(paths['selector']),'backtest':str(paths['backtest'])}


def governed_qfq(rebuild, policy, reservation, *, data_root, return_root, pointers, target, **kwargs):
    import importlib
    module=importlib.import_module('ops.research_panel_qfq')
    key=qfq_invocation_key(module,data_root,target,kwargs)
    # Root is unchanged: QFQ chooses its exact generation directory and resumes
    # compatible completed stocks using its existing full identity checks.
    with admission(policy,key=key,directory=return_root,predicted=reservation['predicted_bytes'],
            category_used=0,reuse_ready=False) as (claim,_):
        with qfq_write_seams(module,claim):
            result=rebuild(data_root=data_root,return_root=return_root,pointers=pointers,target=target,**kwargs)
        if claim:
            if result.get('status')=='READY':
                try:claim.finish(result,[result['selector'],result['backtest']])
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
                try:claim.finish(result,[index])
                except (OSError,ValueError,RetentionError) as error:
                    claim.recording_failed=True
                    result['storage_governance']=dict(status='COMMITTED_REGISTRY_RECORDING_BLOCKED',error=str(error)[:1024])
            else:claim.finish(error=RetentionError('PRODUCT_PARTIAL_RETAINED'))
        return result


def reference_source(path):
    path=safe_path(path);return dict(path=str(path),sha256=digest(path))


@contextmanager
def product_write_seams(modules,claim):
    if claim is None:
        yield;return
    with _ADAPTER_LOCK:
        originals=[]
        def replace(module,name,value):originals.append((module,name,getattr(module,name)));setattr(module,name,value)
        def save(original):
            def call(path,value,*args,**kwargs):
                path=Path(path);claim.watch(path)
                size=len(json.dumps(value,default=str).encode())
                diagnostic=(path.name in {'publication_error.json','latest_receipt.json'} and size<=64*1024
                    and isinstance(value,dict) and value.get('status')=='CANNOT_CONFIRM')
                if not diagnostic:claim.checkpoint(incoming=size*2)
                result=original(path,value,*args,**kwargs);claim.observe(path);return result
            return call
        def boundary(original):
            def call(*args,**kwargs):
                claim.checkpoint()
                result=original(*args,**kwargs)
                if original.__name__ in {'retain_owner_result','finalize_owner_charts'} and len(args)>=2:
                    directory=Path(args[1])
                    paths=([directory/'original_retained'/(args[2]+'.json.gz')] if original.__name__=='retain_owner_result'
                        else list(billing_files(directory)))
                    for path in paths:
                        if path not in claim.baselines:claim.baselines[path]=(0,0)
                        claim.observe(path)
                if original.__name__ in {'run_incremental_history','publish_current_history_view','build','stage','finalize_owner_charts'}:
                    root=Path(claim.directory)
                    if root.exists():
                        for path in billing_files(root):
                            if path not in claim.baselines:claim.baselines[path]=(0,0)
                            claim.observe(path)
                claim.checkpoint()
                return result
            return call
        def executor_type(base):
            class Executor:
                def __init__(self,*args,**kwargs):
                    self.parts=Path(kwargs['initargs'][3]);self.root=Path(kwargs['initargs'][2])
                    self.inner=base(*args,**kwargs)
                def __enter__(self):self.inner.__enter__();return self
                def __exit__(self,*args):return self.inner.__exit__(*args)
                def __getattr__(self,name):return getattr(self.inner,name)
                def submit(self,function,symbol,*args,**kwargs):
                    paths=[self.parts/(symbol+'.json'),self.parts/'original_retained'/(symbol+'.json.gz')]
                    for path in paths:claim.watch(path)
                    claim.checkpoint()
                    future=self.inner.submit(function,symbol,*args,**kwargs)
                    original=future.result
                    def result(*a,**k):
                        value=original(*a,**k)
                        paths.extend(self.root.glob('history/*/'+symbol+'/checkpoint.json'))
                        for path in paths:
                            # Admission captured pre-existing file baselines;
                            # unknown paths were created by this guarded job.
                            if path not in claim.baselines:claim.baselines[path]=(0,0)
                            claim.observe(path)
                        return value
                    future.result=result
                    return future
            return Executor
        try:
            for module in modules:
                if hasattr(module,'ProcessPoolExecutor'):replace(module,'ProcessPoolExecutor',executor_type(module.ProcessPoolExecutor))
                if hasattr(module,'save'):replace(module,'save',save(module.save))
                if hasattr(module,'write_json'):replace(module,'write_json',save(module.write_json))
                for name in ('compute_stock','run_incremental_history','publish_current_history_view','build','stage','record_daily_attempt','retain_owner_result','finalize_owner_charts','owner_pngs'):
                    if hasattr(module,name):replace(module,name,boundary(getattr(module,name)))
            yield
        finally:
            for module,name,value in reversed(originals):setattr(module,name,value)


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
