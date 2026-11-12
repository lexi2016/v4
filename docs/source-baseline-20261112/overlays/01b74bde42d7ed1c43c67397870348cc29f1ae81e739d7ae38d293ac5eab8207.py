"""Immutable paired read binding at the existing QFQ publication seam.

No numeric transforms. A single atomic manifest selects both assets. Kernel
shared leases protect immutable generations until actual request completion;
crashes release leases, sleeping/live processes retain them without timeouts.
Lock order: existing publisher lock -> metadata coordinator -> generation lease.
Normal Readers never take the publisher lock. GC never waits for a lease while
holding metadata coordination: nonblocking exclusive acquisition or BLOCKED.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

from ops.research_storage_retention import (RetentionError, atomic_json, canonical,
    digest, safe_path, stamp, read_json)

_ACTIVE = ContextVar('v4_immutable_pair', default=None)
META = b'a_share_qfq_contract_v1'
SCHEMA = 'v4.immutable_pair.v1'


def settings(data_root=None):
    root = os.environ.get('V4_STORAGE_PAIR_ROOT')
    data = os.environ.get('V4_STORAGE_PAIR_DATA_ROOT')
    if not root and not data:return None
    if not root or not data:raise RetentionError('PAIR_CONFIG_INCOMPLETE')
    if data_root is not None and str(Path(data_root).resolve()) != data:
        raise RetentionError('PAIR_DATA_ROOT_BINDING')
    return safe_path(root, exists=False), safe_path(data)


@contextmanager
def coordination(root):
    root = safe_path(root, exists=False);root.mkdir(parents=True, exist_ok=True)
    lock = safe_path(root/'metadata.lock', exists=False)
    with lock.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle, fcntl.LOCK_UN)


def pointers(data):
    return {'selector': data/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt',
            'backtest': data/'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt'}


def describe(paths):
    from ops.research_panel_logical import parquet as pq
    if set(paths) != {'selector', 'backtest'}:raise RetentionError('PAIR_ROLE_SCOPE')
    roles = {};identities = []
    for role, value in paths.items():
        path = safe_path(value);before = stamp(path)
        schema = pq.read_schema(path);contract = json.loads((schema.metadata or {})[META])
        from ops.research_panel_logical import validate_closure
        validate_closure(path)
        receipt_path = safe_path(contract['generation_manifest_path']);receipt = read_json(receipt_path)
        if (receipt['generation_id'] != contract['generation_id'] or receipt['candidates'][role] != str(path)
                or receipt.get('input_sha256') != contract.get('input_sha256')):
            raise RetentionError('PAIR_PRODUCER_IDENTITY')
        identity = {key: contract.get(key) for key in ('generation_id','input_sha256','snapshot_file_sha256',
            'adjustment_snapshot','asof_date','schema','price_basis','volume_basis','convention','market_basis')}
        if not all(identity.get(key) for key in ('generation_id','input_sha256','snapshot_file_sha256','schema')):
            raise RetentionError('PAIR_IDENTITY_INCOMPLETE')
        if stamp(path) != before:raise RetentionError('PAIR_ARTIFACT_CHANGED')
        roles[role] = dict(path=str(path), stat=before, sha256=receipt['candidate_sha256'][role],
                           schema_sha256=hashlib.sha256(schema.serialize().to_pybytes()).hexdigest(),
                           producer_receipt=dict(path=str(receipt_path), sha256=digest(receipt_path)))
        identities.append(identity)
    if identities[0] != identities[1]:raise RetentionError('PAIR_GENERATION_IDENTITY_MISMATCH')
    body = dict(schema=SCHEMA, identity=identities[0], roles=roles)
    return {**body, 'id': canonical(body)}


def _write_generation(root, manifest):
    directory = root/'generations';directory.mkdir(exist_ok=True)
    path = safe_path(directory/(manifest['id']+'.json'), exists=False)
    if path.exists():
        if read_json(path) != manifest:raise RetentionError('PAIR_IMMUTABLE_MANIFEST_CONFLICT')
    else:
        # Immutable versions/leases have their own bounded control allowance;
        # they are also included in the governance512MiB own-output census.
        used=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if used + 2*len(json.dumps(manifest).encode()) + 64*1024 > 4*1024**2:
            raise RetentionError('PAIR_CONTROL_BUDGET_NEW_PUBLICATION_BLOCKED')
        atomic_json(path, manifest)
    return path


def commit(root, data, paths, *, initial_rollback_paths=None):
    """Caller holds original qfq_publish lock; only post-COMMITTED call allowed.

    Repeating after a crash between old pointer commit and this single commit is
    idempotent. Old/current leases remain safe while reconciliation is pending.
    """
    journal = read_json(data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json')
    if journal.get('status') not in {'COMMITTED','ROLLED_BACK','ROLLED_BACK_AFTER_INTERRUPTION'}:
        raise RetentionError('PAIR_PUBLICATION_NOT_TERMINAL')
    if any(Path(pointer.read_text(encoding='utf-8-sig').strip()) != Path(paths[role]) for role,pointer in pointers(data).items()):
        raise RetentionError('PAIR_POINTER_RECONCILIATION_REQUIRED')
    manifest = describe(paths)
    initial_rollback=describe(initial_rollback_paths) if initial_rollback_paths is not None else None
    if initial_rollback is not None:
        receipt=read_json(Path(manifest['roles']['selector']['producer_receipt']['path']))
        if {role:row['sha256'] for role,row in initial_rollback['roles'].items()} != receipt.get('baseline_panel_sha256'):
            raise RetentionError('PAIR_INITIAL_ROLLBACK_NOT_EXACT_BASELINE')
    with coordination(root):
        current_path = root/'current.json'
        old = read_json(current_path) if current_path.exists() else None
        if old and old['current']['id'] == manifest['id']:return manifest
        path = _write_generation(root, manifest)
        current = dict(id=manifest['id'],path=str(path),sha256=digest(path))
        rollback_ref=None
        if initial_rollback is not None and old is None:
            rollback_path=_write_generation(root,initial_rollback)
            rollback_ref=dict(id=initial_rollback['id'],path=str(rollback_path),sha256=digest(rollback_path))
        # Both roles switch through this ONE atomic replacement. Original pair
        # pointers remain for old consumers, whose reachable objects stay pinned.
        atomic_json(current_path, dict(schema=SCHEMA,current=current,
            rollback=old['current'] if old else rollback_ref))
    return manifest


def seed_configured(*, rollback_paths=None):
    configured = settings()
    if configured is None:raise RetentionError('PAIR_CONFIG_REQUIRED')
    root,data = configured
    # Controller may invoke this only under approved idle lock; function itself
    # obtains the real original lock before the metadata lock, never reverse.
    from ops.research_panel_qfq import publication_lock
    with publication_lock(data):
        return commit(root,data,{role:Path(path.read_text(encoding='utf-8-sig').strip()) for role,path in pointers(data).items()},initial_rollback_paths=rollback_paths)


def publication_preflight():
    configured=settings()
    if configured is None:return
    root,_=configured
    # Original publication lock already held; only bounded metadata census.
    with coordination(root):
        used=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if used + 128*1024 > 4*1024**2:
            raise RetentionError('PAIR_CONTROL_BUDGET_NEW_PUBLICATION_BLOCKED')


def publish_configured(paths):
    configured = settings()
    if configured is not None:return commit(*configured, paths)


class Binding:
    def __init__(self, manifest, handle):
        self.manifest = manifest;self.handle = handle;self.closed = False
        self.paths = MappingProxyType({role:Path(row['path']) for role,row in manifest['roles'].items()})
    def assert_open(self):
        if self.closed:raise RetentionError('PAIR_LEASE_RELEASED')
        for row in self.manifest['roles'].values():
            if stamp(safe_path(row['path'])) != row['stat']:
                raise RetentionError('PAIR_BOUND_ARTIFACT_CHANGED')
            from ops.research_panel_logical import validate_closure
            validate_closure(row['path'])
    def pointer_bytes(self, role):
        self.assert_open();return (str(self.paths[role])+'\n').encode()
    def expected(self, data):
        self.assert_open();return dict(schema='qfq_expected_current_v1',roles={role:dict(
            pointer_path=str(pointers(Path(data))[role]),pointer_sha256=hashlib.sha256(self.pointer_bytes(role)).hexdigest(),
            target_path=str(self.paths[role]),target_sha256=row['sha256']) for role,row in self.manifest['roles'].items()})
    def close(self):
        if not self.closed:
            self.closed=True;fcntl.flock(self.handle,fcntl.LOCK_UN);self.handle.close()


@contextmanager
def acquire(root):
    with coordination(root):
        active = read_json(root/'current.json');ref=active['current'];path=safe_path(ref['path'])
        if path.parent != root/'generations' or digest(path)!=ref['sha256']:raise RetentionError('PAIR_CURRENT_MANIFEST_DRIFT')
        manifest=read_json(path);body={k:v for k,v in manifest.items() if k!='id'}
        if manifest.get('schema')!=SCHEMA or canonical(body)!=manifest.get('id') or manifest['id']!=ref['id']:
            raise RetentionError('PAIR_MANIFEST_IDENTITY')
        if (root/'retired'/manifest['id']).exists():raise RetentionError('PAIR_RETIRED')
        leases=root/'leases';leases.mkdir(exist_ok=True)
        handle=safe_path(leases/(manifest['id']+'.lock'), exists=False).open('a+b')
        fcntl.flock(handle,fcntl.LOCK_SH)
        binding=Binding(manifest,handle)
        try:binding.assert_open()
        except BaseException:binding.close();raise
    try:yield binding
    finally:binding.close()


def current_binding(data_root=None):
    binding=_ACTIVE.get()
    if binding is not None:
        binding.assert_open()
        if data_root is not None:settings(data_root)
    return binding


@contextmanager
def request_binding(data_root=None):
    configured=settings(data_root)
    if configured is None:yield None;return
    existing=current_binding(data_root)
    if existing is not None:yield existing;return
    with acquire(configured[0]) as binding:
        token=_ACTIVE.set(binding)
        try:yield binding
        finally:_ACTIVE.reset(token)


def paired_request(function):
    @wraps(function)
    def call(*args,**kwargs):
        with request_binding(args[0] if args else kwargs.get('shared_data_root',kwargs.get('data_root'))):
            result=function(*args,**kwargs)
            # Current entry points return materialized dicts. Reject a future
            # lazy/streaming return rather than release its lease prematurely.
            if hasattr(result,'__next__') or hasattr(result,'__aiter__'):
                raise RetentionError('PAIR_LAZY_RETURN_REQUIRES_STREAM_SCOPE')
            return result
    return call


def bind_shared_reader(reader, binding):
    """Per-request loaded module: replace only mutable CURRENT revalidation.

    Its exact original numeric/filter/basis code still runs against explicit
    panel_path and the immutable producer manifest. Never patch shared globals.
    """
    if binding is None:return
    binding.assert_open()
    sentinel=Path(reader.__file__).parent/('.immutable_pair_'+binding.manifest['id'])
    if sentinel.exists():raise RetentionError('PAIR_READER_SENTINEL_COLLISION')
    reader.POINTER_FILE=sentinel


@contextmanager
def retire_candidate(root, generation_id):
    """Object-scoped technical gate; authorization/rebuild gates are separate.

    No unlink operation here. Exclusive kernel lock lasts across caller GC
    transaction; unknown Readers outside this object scope remain protected.
    """
    import re
    if not re.fullmatch('[0-9a-f]{64}',generation_id):raise RetentionError('PAIR_RETIRE_ID')
    read_json(safe_path(root/'generations'/(generation_id+'.json')))
    handle=None
    with coordination(root):
        state=read_json(root/'current.json')
        if generation_id in {ref['id'] for ref in (state['current'],state.get('rollback')) if ref}:
            raise RetentionError('PAIR_CURRENT_OR_ROLLBACK_PROTECTED')
        path=safe_path(root/'leases'/(generation_id+'.lock'),exists=False)
        handle=path.open('a+b')
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close();raise RetentionError('PAIR_EFFECTIVE_READER_LEASE')
        retired=root/'retired';retired.mkdir(exist_ok=True)
        atomic_json(retired/generation_id,dict(status='RETIRED_NO_NEW_READERS',generation_id=generation_id))
    try:yield
    finally:
        fcntl.flock(handle,fcntl.LOCK_UN);handle.close()
