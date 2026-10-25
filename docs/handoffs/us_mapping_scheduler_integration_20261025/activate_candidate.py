"""Native US scheduler control binding; only explicit prepare/execute writes.

The existing FreezeGuardian is the lifecycle state machine. Old release CLI and
old PREPARED/intent validators are intentionally not used. atomic_plist and sha
below are exact source migrations from the independently bound owner primitive;
only this module's LIVE is the scheduler. The legacy files remain unmodified.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import signal
import stat
import subprocess
import sys
import tempfile
from uuid import uuid4

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIVATE = Path('/Users/lexi/.codex/worktrees/us-mapping-workflow-cleanup-20261025/v4_app/.superpowers/sdd/2026-10-25-us-mapping-workflow-cleanup/runtime-integration-r1/lifecycle-binding-r1')
LIVE = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')
RELEASES = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
PARENT = RELEASES / 'local-panel-history-source-20261025-r3'
CANDIDATE = RELEASES / 'us-mapping-focus-scheduler-20261025-r1'
NATIVE_SHA = '6c8485a06bcfe3a79ac1d7516f380809727fa9cb20e87d102eaf86590b27b316'
CANDIDATE_SHA = '842898cd49fab0f46bc3e02aaf7ddaba7a6b5fa8b4736eb09aa34916c7ebeaf4'
PARENT_SHA = '70aa9cc0a4165471bef3c08ec96b53e2a417646042487b7a864c12b7054a1b2e'
PLIST_SHA = '3a2d33c87f69f1aa5d704be3e0bc2aab4f303adf3feb9c8bf718c09b80b16199'
QFQ_SHA = '7ce737550d855dd9e95bc62ebef2209bfc1c4b2bbe70f16cb51b75688342f445'
ATOMIC_ORIGIN_SHA = 'dec2c48103f67f67516fdd80f9f9503f08d09dbc59fae4c37f4a273e077955a1'
DEPENDENCIES = {
 'docs/handoffs/us_hk_selection_closure_20261023/deployment/activate_release.py':'95cfa4ccf8ebbe05d5afbe740894889fdc5ce06a9a7ffc193c09d4c1c47b660c',
 'docs/handoffs/us_hk_selection_closure_20261023/deployment/prepare_release.py':'be86d5c7e5f3efb925e959b41767ca47ab0b9245bd38a25893639b63d350b601',
 'docs/handoffs/us_hk_selection_closure_20261023/deployment/recover_legacy_activity.py':'9e43e9a5c7ba475dfbb9fdfc4a4fc65066fa5d781647abebf7eacb6edadb6a92',
 'ops/api_release_integration.py':'2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'}
BINDING_SCHEMA = 'v4.us_mapping.native_lifecycle_binding.v1'
INTENT_SCHEMA = 'v4.us_mapping.native_guardian_intent.v1'
RESULT_SCHEMA = 'v4.us_mapping.native_lifecycle_result.v1'
LEGACY_ROOT = Path('/Users/lexi/.codex/worktrees/us-hk-selection-closure-20261023/v4_app/.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment/authorized-four-recovery')
LEGACY_ACTIVITY_PINS = dict(
    authority=dict(path=str(LEGACY_ROOT/'AUTHORIZATION.json'),sha256='f3fb7b7d34fd07cb9afa60fcdad293f5becdc5b76f57049483f225d524eda5df'),
    receipt=dict(path=str(LEGACY_ROOT/'private-originals-c88210c851277da946682eb13af64c474ad049ba177839bffe792091b858b725/DISPOSITION.json'),
        sha256='75b7ca00ac3266e3761a86cdf36d655b13465b606808c1eb98c6f5d25a5acab4'),
    authenticator_sha256='9e43e9a5c7ba475dfbb9fdfc4a4fc65066fa5d781647abebf7eacb6edadb6a92')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def atomic_plist(raw,expected):
 if sha(LIVE)!=expected:raise RuntimeError('LIVE_PLIST_CAS_CONFLICT')
 st=LIVE.stat()
 if LIVE.is_symlink() or not stat.S_ISREG(st.st_mode):raise RuntimeError('PLIST_TYPE_CONFLICT')
 fd,name=tempfile.mkstemp(prefix='.history-owned-',dir=LIVE.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),stat.S_IMODE(st.st_mode));os.fchown(f.fileno(),st.st_uid,st.st_gid)
  if sha(LIVE)!=expected:raise RuntimeError('LIVE_PLIST_CAS_CONFLICT')
  os.replace(name,LIVE)
  df=os.open(LIVE.parent,os.O_RDONLY)
  try:os.fsync(df)
  finally:os.close(df)
 finally:
  if os.path.exists(name):os.unlink(name)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_pin(pin):
    path = Path(pin['path'])
    require(path.is_absolute() and not path.is_symlink() and path.resolve() == path, 'PIN_PATH_ALIAS')
    require(sha(path) == pin['sha256'], 'PIN_DRIFT:' + str(path))
    return json.loads(path.read_bytes())


def pin(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy():
    for relative, expected in DEPENDENCIES.items():
        require(sha(ROOT / relative) == expected, 'CONTROL_PRIMITIVE_DRIFT:' + relative)
    if '_native_existing_guardian' not in sys.modules:
        folder = ROOT / 'docs/handoffs/us_hk_selection_closure_20261023/deployment'
        if 'prepare_release' in sys.modules:
            require(Path(sys.modules['prepare_release'].__file__) == folder / 'prepare_release.py', 'PREPARE_MODULE_ALIAS')
        else:
            sys.modules['prepare_release'] = load_module('prepare_release', folder / 'prepare_release.py')
        sys.modules['_native_existing_guardian'] = load_module('_native_existing_guardian', folder / 'activate_release.py')
    return sys.modules['_native_existing_guardian']


def legacy_recovery():
    legacy()  # Authenticate the unchanged source before using only its readers.
    return load_module('_native_four_metadata_readers', ROOT/'docs/handoffs/us_hk_selection_closure_20261023/deployment/recover_legacy_activity.py')


def verify_legacy_activity(pins):
    """Rebind exactly four existing administrative records, never old products."""
    require(pins == LEGACY_ACTIVITY_PINS, 'LEGACY_ACTIVITY_PINS_NOT_EXACT')
    reader = legacy_recovery()
    authority = reader.authority(pins['authority'])
    receipt = read_pin(pins['receipt'])
    require(receipt.get('schema') == 'v4.us_hk.legacy_disposition.v1' and receipt.get('authority') == pins['authority'] and
        receipt.get('disposition') == reader.DISPOSITION and receipt.get('execution_state') == 'UNKNOWN' and
        receipt.get('original_records_changed') is False and receipt.get('completion_or_idle_proven') is False,
        'LEGACY_ACTIVITY_DISPOSITION_INVALID')
    root = Path(pins['receipt']['path']).parent
    require(stat.S_IMODE(root.stat().st_mode) == 0o700 and
        stat.S_IMODE(Path(pins['authority']['path']).stat().st_mode) == 0o644 and
        stat.S_IMODE(Path(pins['receipt']['path']).stat().st_mode) == 0o600,
        'LEGACY_ACTIVITY_EVIDENCE_MODE_DRIFT')
    records = receipt.get('records', [])
    require(len(records) == 4 and [{k:v for k,v in row.items() if k != 'backup_path'} for row in records] == authority['records'],
        'LEGACY_ACTIVITY_RECORD_IDENTITY_DRIFT')
    for index, record in enumerate(records):
        raw = reader.original(record)
        path, backup = Path(record['path']), Path(record['backup_path'])
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, 'LEGACY_ORIGINAL_MODE_DRIFT')
        require(backup == root/(str(index)+'-'+record['sha256']+'.original.json') and
            not backup.is_symlink() and backup.resolve() == backup and backup.is_file() and
            stat.S_IMODE(backup.stat().st_mode) == 0o600 and backup.stat().st_size == len(raw) and backup.read_bytes() == raw,
            'LEGACY_ORIGINAL_BACKUP_DRIFT')
    # operator_capsule/prepared_products remain historical receipt bytes. They
    # are not read or treated as authority for this native lifecycle product.
    return receipt


def native_lifecycle(scope, pins):
    """One metadata admission adapter; the entire original activity scan runs."""
    parent = legacy().LaunchctlLifecycle
    class NativeLifecycle(parent):
        def inspect(self):
            value = super().inspect()
            receipt = verify_legacy_activity(pins)
            require(self.scope['role'] == 'scheduler', 'LEGACY_ACTIVITY_ROLE_NOT_EXACT')
            row = next(r for r in receipt['records'] if r['kind'] == 'Workbench')
            target = str(Path(self.scope['activity']['workbench_root'])/'attempts/07bfabf09f144360ab8869214aeecea8.json')
            require(row['job_id'] == '07bfabf09f144360ab8869214aeecea8' and row['path'] == target and
                value['busy_work'].count(target) == 1, 'LEGACY_ACTIVITY_PATH_MISSING_OR_DUPLICATE')
            return dict(value, busy_work=[p for p in value['busy_work'] if p != target],
                activity_sha256=legacy().digest(legacy().json_bytes(dict(original_activity_sha256=value['activity_sha256'],
                    legacy_activity_disposition=pins))), original_activity_sha256=value['activity_sha256'],
                legacy_activity_disposition=pins, administratively_disposed_work=[target],
                legacy_execution_state='UNKNOWN', original_records_changed=False, completion_or_idle_proven=False)
    return NativeLifecycle(scope)


def private_path(path, *, absent=False):
    path = Path(path).absolute()
    require(path.resolve() == path and path.is_relative_to(PRIVATE) and path != PRIVATE, 'PRIVATE_EVIDENCE_ESCAPE')
    require(not path.is_symlink() and (not absent or not path.exists()), 'PRIVATE_EVIDENCE_COLLISION')
    return path


def write_new(path, value):
    path = private_path(path, absent=True)
    with path.open('xb') as stream:
        stream.write(value if isinstance(value, bytes) else legacy().json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def native_product(prepared_pin, review_pin):
    """Validate this native schema as itself, without calling the old verifier."""
    require(prepared_pin == dict(path=str(CANDIDATE / 'PREPARED.json'), sha256=NATIVE_SHA), 'NATIVE_PREPARED_PIN')
    prepared = read_pin(prepared_pin)
    require(prepared.get('state') == 'PREPARED_NOT_ACTIVATED' and prepared.get('candidate') == str(CANDIDATE), 'NATIVE_PREPARED_SCHEMA')
    require(prepared.get('manifest_sha256') == CANDIDATE_SHA and prepared.get('exact_overlay_count') == 12 and
        prepared.get('non_delta_bytes_modes_preserved') is True and prepared.get('activation') == 'NOT_RUN', 'NATIVE_PREPARED_CONTENT')
    candidate = read_pin(dict(path=str(CANDIDATE / 'release-manifest.json'), sha256=CANDIDATE_SHA))
    parent = read_pin(dict(path=str(PARENT / 'release-manifest.json'), sha256=PARENT_SHA))
    require(candidate['task_overlay']['parent_outer_manifest_sha256'] == PARENT_SHA and
        candidate['application_inventory']['entry_count'] == 999 and parent['application_inventory']['entry_count'] == 996, 'NATIVE_PARENT_IDENTITY')
    review = read_pin(review_pin)
    require(review.get('verdict') == 'REVIEWED/PASS' and review.get('candidate_manifest_sha256') == CANDIDATE_SHA and
        review.get('candidate') == str(CANDIDATE), 'CANDIDATE_INDEPENDENT_REVIEW_REQUIRED')
    for relative, expected in review['source_sha256'].items():
        require(sha(ROOT / relative) == expected, 'ACCEPTED_SOURCE_DRIFT')
    return candidate


def current_candidate_inventory(manifest):
    # CAS freshness, not a repeat engine/test acceptance. Reuse the independently
    # reviewed native preparer's exact file/link/directory inventory schema.
    profile = load_module('_accepted_native_inventory', HERE / 'prepare_candidate.py')
    tool = legacy().inventory_tool(dict(path=str(ROOT / 'ops/api_release_integration.py'),
        sha256=DEPENDENCIES['ops/api_release_integration.py']))
    actual = profile.complete_inventory(CANDIDATE / 'app', tool)
    require([actual[k] for k in sorted(actual)] == manifest['application_inventory']['entries'], 'CANDIDATE_BYTES_OR_MODE_DRIFT')


def lifecycle_review(review_pin):
    value = read_pin(review_pin)
    relative = str(Path(__file__).relative_to(ROOT))
    require(value.get('verdict') == 'REVIEWED/PASS' and value.get('source_sha256', {}).get(relative) == sha(__file__),
        'INDEPENDENT_LIFECYCLE_SOURCE_REVIEW_REQUIRED')
    return value


def proposed_plist(raw, candidate_manifest_sha=CANDIDATE_SHA):
    """Exactly five environment selectors and two owner-entry fields may change."""
    old = plistlib.loads(raw)
    require(old['WorkingDirectory'] == str(PARENT / 'app'), 'PARENT_PLIST_CWD')
    require(old['ProgramArguments'] == ['/bin/bash', str(PARENT / 'app/ops/launch_v35_macos_scheduler.sh')], 'PARENT_LAUNCHER')
    result = json.loads(json.dumps(old))
    result['WorkingDirectory'] = str(CANDIDATE / 'app')
    result['ProgramArguments'][1] = str(CANDIDATE / 'app/ops/launch_v35_macos_scheduler.sh')
    env = result['EnvironmentVariables']
    env.update(V35_APP_ROOT=str(CANDIDATE / 'app'), V35_RELEASE_ID=CANDIDATE.name,
        V35_RELEASE_MANIFEST_PATH=str(CANDIDATE / 'release-manifest.json'), V35_RELEASE_MANIFEST_SHA256=candidate_manifest_sha,
        PYTHONPATH=':'.join([str(CANDIDATE / 'app'), str(CANDIDATE / 'app/upstreams'), old['EnvironmentVariables'].get('PYTHONPATH', '')]).rstrip(':'))
    allowed = {'V35_APP_ROOT', 'V35_RELEASE_ID', 'V35_RELEASE_MANIFEST_PATH', 'V35_RELEASE_MANIFEST_SHA256', 'PYTHONPATH'}
    require({k for k in env.keys() | old['EnvironmentVariables'].keys() if env.get(k) != old['EnvironmentVariables'].get(k)} <= allowed,
        'UNRELATED_ENVIRONMENT_CHANGE')
    require(all(result[k] == v for k,v in old.items() if k not in {'WorkingDirectory', 'ProgramArguments', 'EnvironmentVariables'}), 'UNRELATED_PLIST_CHANGE')
    return plistlib.dumps(result, sort_keys=False)


def checked_protected(config_pin):
    value = read_pin(config_pin)
    refs = value['source_identity_refs']
    require(len(refs) == 21 and len({r['path'] for r in refs}) == 21, 'PROTECTED_21_REFS_REQUIRED')
    for ref in refs:
        require(sha(ref['path']) == ref['sha256'], 'PROTECTED_SOURCE_DRIFT')
    require(dict(path=str(PARENT / 'app/ops/research_panel_qfq.py'), sha256=QFQ_SHA) in refs and
        dict(path=str(PARENT / 'release-manifest.json'), sha256=PARENT_SHA) in refs, 'PROTECTED_PARENT_QFQ_BINDING')
    require(sha(value['python']) == value['binary_sha256'], 'RUNTIME_BINARY_DRIFT')
    return value


def prepare(spec_pin, output):
    """Read-only capture and private artifacts only; no lock, signal or lifecycle."""
    spec = read_pin(spec_pin)
    require(spec.get('schema') == 'v4.us_mapping.native_lifecycle_spec.v1', 'NATIVE_SPEC_SCHEMA')
    lifecycle_review(spec['lifecycle_review'])
    current_candidate_inventory(native_product(spec['native_prepared'], spec['candidate_review']))
    protected = checked_protected(spec['protected_owner_config'])
    disposition = spec.get('legacy_activity_disposition', LEGACY_ACTIVITY_PINS)
    verify_legacy_activity(disposition)
    old = LIVE.read_bytes()
    require(sha(LIVE) == PLIST_SHA, 'PARENT_LIVE_PLIST_DRIFT')
    target = proposed_plist(old)
    env = legacy().effective_plist_environment(plistlib.loads(old))
    config_path = Path(env['V4_MANAGER_WORKBENCH_CONFIG_PATH'])
    config = json.loads(config_path.read_bytes())
    activity = dict(uid=os.getuid(), workbench_root=str(legacy().actual_store_root(PARENT / 'app', config['state_root'])),
        data_root=env['V35_DATA_ROOT'], dispatcher_root=env['V35_DISPATCH_LEDGER_ROOT'],
        release_lock_path=str(LIVE.parent / '.com.lexi.v35.scheduler.release.lock'),
        existing_kernel_locks=spec['existing_kernel_locks'], admission_files={side:{relative:sha(root / 'app' / relative)
            for relative in sorted(legacy().ADMISSION_FILES['scheduler'])} for side,root in [('parent', PARENT), ('candidate', CANDIDATE)]})
    require(all(len(rows) == 17 for rows in activity['admission_files'].values()), 'CONTROL_17_REFS_REQUIRED')
    scope = dict(role='scheduler', parent_root=str(PARENT), candidate_root=str(CANDIDATE), source_root=str(ROOT),
        plist=dict(path=str(LIVE)), inventory_tool=dict(path=str(ROOT / 'ops/api_release_integration.py'),
        sha256=DEPENDENCIES['ops/api_release_integration.py']), dependencies=[pin(config_path)],
        runtime_probe=dict(python=dict(path=protected['python'], sha256=protected['binary_sha256'])), activity=activity)
    observed = legacy().LaunchctlLifecycle(dict(scope, activity=dict(activity, expected_pid=spec['expected_parent_pid']))).identity()
    require(observed['state'] == 'running' and observed['app_root'] == str(PARENT / 'app') and
        observed['pid'] == spec['expected_parent_pid'], 'PARENT_RUNTIME_DRIFT')
    owner = legacy().signal_identity(observed['pid'])
    require(owner['status'] in (2,3), 'OWNER_NOT_RUNNING')
    activity.update(expected_owner=owner, expected_pid=owner['pid'])
    legacy().lifecycle_identity(scope)  # Decode audit UID/PID/version; not just PID equality.
    require(sha(LIVE) == PLIST_SHA and legacy().same_process(owner), 'PREPARE_OWNER_OR_PLIST_DRIFT')
    output = private_path(output, absent=True)
    output.mkdir()
    backup, proposal = output / 'parent.plist', output / 'candidate.plist'
    write_new(backup, old); write_new(proposal, target)
    body = dict(schema=BINDING_SCHEMA, state='PREPARED_NOT_ACTIVATED', source_root=str(ROOT),
        native_prepared=spec['native_prepared'], candidate_review=spec['candidate_review'], lifecycle_review=spec['lifecycle_review'],
        protected_owner_config=spec['protected_owner_config'], protected_refs=protected['source_identity_refs'],
        legacy_activity_disposition=disposition, legacy_execution_state='UNKNOWN',
        original_records_changed=False, completion_or_idle_proven=False,
        helper_sha256=sha(__file__), dependency_sha256=DEPENDENCIES, atomic_origin_sha256=ATOMIC_ORIGIN_SHA,
        scope=scope, plists=dict(original_plist=str(backup), original_plist_sha256=sha(backup),
        candidate_plist=str(proposal), candidate_plist_sha256=sha(proposal)), qfq_data_root=env['V35_RESEARCH_PANEL_A_DATA_ROOT'],
        evidence_root=str(output), data_pointer_changes=[], source_cutoff_changed=False)
    for direction in ('activate', 'rollback'):
        legacy().verify_activity_closure(scope, body['plists'], direction)
    write_new(output / 'BINDING.json', body)
    return pin(output / 'BINDING.json')


def verify_binding(binding_pin):
    body = read_pin(binding_pin)
    require(body.get('schema') == BINDING_SCHEMA and body.get('state') == 'PREPARED_NOT_ACTIVATED', 'NATIVE_BINDING_SCHEMA')
    require(body['helper_sha256'] == sha(__file__) and body['dependency_sha256'] == DEPENDENCIES, 'BINDING_HELPER_DRIFT')
    require(body['source_root'] == str(ROOT) and body['data_pointer_changes'] == [] and not body['source_cutoff_changed'], 'BINDING_SCOPE_DRIFT')
    lifecycle_review(body['lifecycle_review'])
    verify_legacy_activity(body.get('legacy_activity_disposition'))
    require(body.get('legacy_execution_state') == 'UNKNOWN' and body.get('original_records_changed') is False and
        body.get('completion_or_idle_proven') is False, 'LEGACY_ACTIVITY_STATE_PROMOTION_FORBIDDEN')
    current_candidate_inventory(native_product(body['native_prepared'], body['candidate_review']))
    require(checked_protected(body['protected_owner_config'])['source_identity_refs'] == body['protected_refs'], 'PROTECTED_REFS_DRIFT')
    require(body['scope']['parent_root'] == str(PARENT) and body['scope']['candidate_root'] == str(CANDIDATE) and
        body['scope']['role'] == 'scheduler' and body['scope']['plist']['path'] == str(LIVE), 'CONTROL_ROLE_DRIFT')
    private_path(body['evidence_root'])
    plists = body['plists']
    for name in ('original', 'candidate'):
        private_path(plists[name+'_plist'])
        require(sha(plists[name+'_plist']) == plists[name+'_plist_sha256'], 'CONTROL_PLIST_DRIFT')
    require(plists['original_plist_sha256'] == PLIST_SHA and
        Path(plists['candidate_plist']).read_bytes() == proposed_plist(Path(plists['original_plist']).read_bytes()), 'CONTROL_PLIST_PROPOSAL_DRIFT')
    environment = legacy().effective_plist_environment(plistlib.loads(Path(plists['original_plist']).read_bytes()))
    require(body['qfq_data_root'] == environment['V35_RESEARCH_PANEL_A_DATA_ROOT'], 'QFQ_LOCK_ROOT_DRIFT')
    for direction in ('activate', 'rollback'):
        legacy().verify_activity_closure(body['scope'], plists, direction)
    return body


def execution_authority(authority_pin, binding_pin, body, direction):
    value = read_pin(authority_pin)
    require(value.get('schema') == 'v4.us_mapping.native_execution_authority.v1' and value.get('action') == direction and
        value.get('binding') == binding_pin and value.get('helper_sha256') == body['helper_sha256'] and
        value.get('lifecycle_review') == body['lifecycle_review'] and
        value.get('legacy_activity_disposition') == body.get('legacy_activity_disposition'), 'EXECUTION_AUTHORITY_MISMATCH')
    if body.get('legacy_activity_disposition') is not None:
        verify_legacy_activity(body['legacy_activity_disposition'])
    return value


def owner_for_transition(body, binding_pin, direction, observed, recovery_pin):
    """Rollback only this activation's exact new owner or proved committed absence."""
    keys = legacy()._OWNER_KEYS
    if direction == 'activate':
        expected = body['scope']['activity']['expected_owner']
        require(observed['state'] == 'running' and observed['app_root'] == str(PARENT / 'app'), 'ACTIVATION_OWNER_ROOT')
    else:
        require(recovery_pin is not None, 'ROLLBACK_RECEIPT_REQUIRED')
        recovery = read_pin(recovery_pin)
        require(recovery.get('schema') == RESULT_SCHEMA and recovery.get('direction') == 'activate' and
            recovery.get('binding') == binding_pin and recovery.get('helper_sha256') == body['helper_sha256'] and
            recovery.get('after_plist_sha256') == body['plists']['candidate_plist_sha256'] and
            recovery.get('state') in {'ACTIVATED', 'FAILED_REQUIRES_INSPECTION'}, 'ROLLBACK_RECEIPT_BINDING')
        if observed['state'] == 'absent':
            require(recovery.get('state') == 'FAILED_REQUIRES_INSPECTION' and recovery.get('committed') is True and
                recovery.get('named_job_absent') is True and recovery.get('current_runtime_readback', {}).get('state') == 'absent',
                'ABSENT_ROLLBACK_PROOF_REQUIRED')
            return None
        require(observed['state'] == 'running' and observed['app_root'] == str(CANDIDATE / 'app'), 'ROLLBACK_OWNER_ROOT')
        if recovery['state'] == 'FAILED_REQUIRES_INSPECTION':
            recorded = recovery.get('recorded_new_owner')
            require(isinstance(recorded, dict) and
                recorded.get('runtime_readback', {}).get('app_root') == str(CANDIDATE / 'app'), 'ROLLBACK_RECORDED_NEW_OWNER_REQUIRED')
            expected = recorded.get('runtime_kernel_identity')
            require(expected == recovery.get('runtime_kernel_identity'), 'ROLLBACK_RECORDED_OWNER_CONFLICT')
        else:
            expected = recovery.get('runtime_kernel_identity')
    require(isinstance(expected, dict) and all(k in expected for k in keys), 'FULL_KERNEL_IDENTITY_REQUIRED')
    actual = legacy().signal_identity(observed['pid'])
    require(all(actual.get(k) == expected[k] for k in keys) and legacy().same_process(actual), 'CURRENT_KERNEL_OWNER_DRIFT')
    return actual


@contextmanager
def guards(body):
    """Retain existing release/announcement/kernel locks plus exact QFQ publisher."""
    with legacy().release_guards(body['scope']):
        before = list(sys.path)
        sys.path[:0] = [str(PARENT / 'app'), str(PARENT / 'app/upstreams')]
        try:
            require(sha(PARENT / 'app/ops/research_panel_qfq.py') == QFQ_SHA, 'QFQ_PRIMITIVE_DRIFT')
            module = load_module('_native_existing_qfq_lock', PARENT / 'app/ops/research_panel_qfq.py')
            with module.publication_lock(Path(body['qfq_data_root'])):
                yield
        finally:
            sys.path[:] = before


class NativeGuardianOps:
    """Metadata adapter for the unchanged guardian; no lifecycle state machine."""
    def __init__(self, intent):
        self.intent = intent
        require(intent.get('schema') == INTENT_SCHEMA and intent.get('mode') == 'NATIVE_RELEASE', 'NATIVE_INTENT_SCHEMA')
        self.body = verify_binding(intent['binding'])
        self.direction = intent['direction']
        execution_authority(intent['authority'], intent['binding'], self.body, self.direction)
        require(intent['helper_sha256'] == sha(__file__) and intent['controller_pid'] > 1, 'NATIVE_INTENT_HELPER')
        self.scope = self.body['scope']
        self.lifecycle = native_lifecycle(self.scope, self.body['legacy_activity_disposition'])
        self.pointer = LIVE
        self.expected = self.body['plists']['original_plist_sha256' if self.direction == 'activate' else 'candidate_plist_sha256']
        self.source = self.body['plists']['candidate_plist' if self.direction == 'activate' else 'original_plist']
        self.raw = Path(self.source).read_bytes()
        self.before = self.pointer.read_bytes()
        self.previous = str((PARENT if self.direction == 'activate' else CANDIDATE) / 'app')
        self.target = str((CANDIDATE if self.direction == 'activate' else PARENT) / 'app')
        self.calls, self.last_new_owner = [], None
        for key in ('journal', 'receipt_path'):
            path = private_path(intent[key], absent=True)
            require(path.parent == Path(self.body['evidence_root']), 'GUARDIAN_EVIDENCE_BINDING')
        require(sha(self.pointer) == self.expected, 'CURRENT_PLIST_CAS_DRIFT')

    def verify_before_freeze(self):
        verify_binding(self.intent['binding'])
        execution_authority(self.intent['authority'], self.intent['binding'], self.body, self.direction)
        require(sha(self.pointer) == self.expected, 'CURRENT_PLIST_CAS_DRIFT')
        observed = self.lifecycle.identity()
        token = owner_for_transition(self.body, self.intent['binding'], self.direction, observed, self.intent.get('recovery'))
        intent_token = self.intent['owner_token']
        require((token is None and intent_token is None) or (token is not None and intent_token is not None and
            all(token[k] == intent_token[k] for k in legacy()._OWNER_KEYS)), 'GUARDIAN_OWNER_TOKEN_DRIFT')

    def frozen_activity(self):
        value = self.lifecycle.inspect()
        token = self.intent['owner_token']
        require(value['state'] == ('running' if token else 'absent'), 'FROZEN_OWNER_STATE_DRIFT')
        if token:
            require(value['pid'] == token['pid'] and value['app_root'] == self.previous, 'FROZEN_OWNER_IDENTITY_DRIFT')
        return value

    def verify_commit(self):
        self.verify_before_freeze()
        require(Path(self.source).read_bytes() == self.raw, 'GUARDIAN_TARGET_DRIFT')

    def replace_binding(self):
        atomic_plist(self.raw, self.expected)

    def restore_precommit(self):
        current = self.pointer.read_bytes()
        require(current in (self.before, self.raw), 'PRECOMMIT_THIRD_PARTY_PLIST_DRIFT')
        if current == self.raw:
            atomic_plist(self.before, legacy().digest(self.raw))

    # These generic methods use only the attributes/interface defined above.
    def bootout(self): return legacy().RealGuardianOps.bootout(self)
    def job_state(self): return legacy().RealGuardianOps.job_state(self)
    def bootstrap_once(self): return legacy().RealGuardianOps.bootstrap_once(self)
    def remember_new_owner(self, value, token):
        # The readiness callback may refresh observations of one kernel owner;
        # it cannot transfer rollback authority to a replacement process.
        progress = json.loads(Path(self.intent['journal']).read_bytes())
        previous = self.last_new_owner or progress.get('last_observed_new_owner')
        if previous is not None:
            expected = previous['runtime_kernel_identity']
            require(all(token.get(k) == expected.get(k) for k in legacy()._OWNER_KEYS), 'NEW_RUNTIME_KERNEL_OWNER_DRIFT')
        return legacy().RealGuardianOps.remember_new_owner(self, value, token)

    def final_readback(self):
        value, kernel = legacy().wait_for_readiness(self.lifecycle, self.target, self.pointer, legacy().digest(self.raw), remember=self.remember_new_owner)
        result = dict(schema=RESULT_SCHEMA, state='ACTIVATED' if self.direction == 'activate' else 'ROLLED_BACK',
            binding=self.intent['binding'], helper_sha256=sha(__file__), direction=self.direction,
            before_plist_sha256=self.expected, after_plist_sha256=sha(self.pointer), runtime_readback=value,
            runtime_kernel_identity=kernel, committed=True, named_job_absent=False,
            guardian_journal=self.intent['journal'], data_pointer_changes=[], source_cutoff_changed=False,
            admission_fence='KERNEL_STOP_EXACT_IDLE_OWNER', lifecycle_calls=self.calls)
        write_new(self.intent['receipt_path'], result)
        return result

    def finish_journal(self):
        if Path(self.intent['receipt_path']).exists(): return
        progress = json.loads(Path(self.intent['journal']).read_bytes())
        try:
            value = self.lifecycle.identity()
            kernel = legacy().signal_identity(value['pid']) if value['state'] == 'running' else None
        except Exception:
            value, kernel = dict(state='unknown'), None
        recorded = self.last_new_owner or progress.get('last_observed_new_owner')
        # Never acquire authority from the failure-time observation. In
        # particular, no remembered readiness owner means no running owner is
        # authorized for rollback, even if the current process looks plausible.
        remembered_value = recorded['runtime_readback'] if recorded is not None else dict(state='unknown')
        remembered_kernel = recorded['runtime_kernel_identity'] if recorded is not None else None
        write_new(self.intent['receipt_path'], dict(schema=RESULT_SCHEMA, state='FAILED_REQUIRES_INSPECTION',
            binding=self.intent['binding'], helper_sha256=sha(__file__), direction=self.direction,
            before_plist_sha256=self.expected, after_plist_sha256=legacy().digest(self.raw), current_plist_sha256=sha(self.pointer),
            runtime_readback=remembered_value, runtime_kernel_identity=remembered_kernel,
            recorded_new_owner=recorded, current_runtime_readback=value, current_runtime_kernel_identity=kernel,
            runtime_observation='LAST_REMEMBERED_OWNER' if recorded is not None else 'NO_REMEMBERED_OWNER',
            committed=progress['committed'],
            named_job_absent=value['state'] == 'absent' and progress['committed'] and progress['phase'] in
                {'OLD_OWNER_EXITED', 'STOPPED_AFTER_COMMIT_NO_BOOTSTRAP'},
            guardian_journal=self.intent['journal'], guardian_phase=progress['phase'], retry_permitted=False,
            data_pointer_changes=[], lifecycle_calls=self.calls))


class ProtocolOnlyOps:
    """Real child/parser/guardian protocol test; incapable of signaling any owner."""
    def __init__(self, intent):
        require(intent.get('owner_token') is None and intent.get('mode') == 'PROTOCOL_ONLY', 'PROTOCOL_CANNOT_OWN_PROCESS')
        self.intent = intent
        root = private_path(intent['protocol_root'])
        require(root.name.startswith('protocol-'), 'PROTOCOL_ROOT')
        for key in ('journal', 'receipt_path'):
            require(private_path(intent[key], absent=True).parent == root, 'PROTOCOL_PATH_ESCAPE')
        self.marker = root / 'marker.json'
    def verify_before_freeze(self): pass
    def frozen_activity(self): return dict(busy_work=['TEST_BUSY'] if self.intent.get('busy') else [])
    def verify_commit(self): pass
    def replace_binding(self): write_new(self.marker, dict(binding='candidate'))
    def restore_precommit(self): pass
    def bootout(self): raise AssertionError('PROTOCOL_BOOTOUT_FORBIDDEN')
    def job_state(self): return dict(state='absent')
    def bootstrap_once(self): write_new(self.marker.parent / 'bootstrap.json', dict(count=1))
    def final_readback(self):
        value = dict(state='PROTOCOL_ONLY_FINISHED', engine_calls=0, real_lifecycle_calls=0)
        write_new(self.intent['receipt_path'], value)
        return value


def guardian_main(intent_pin):
    intent = read_pin(intent_pin)
    require(intent.get('schema') == INTENT_SCHEMA, 'NATIVE_INTENT_SCHEMA')
    ops = ProtocolOnlyOps(intent) if intent.get('mode') == 'PROTOCOL_ONLY' else NativeGuardianOps(intent)
    def interrupted(signum, frame): raise legacy().Stop('NATIVE_GUARDIAN_INTERRUPTION:' + str(signum))
    signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGINT, interrupted)
    stack = guards(ops.body) if isinstance(ops, NativeGuardianOps) else ExitStack()
    with stack:
        try:
            legacy().FreezeGuardian(ops, intent, sys.stdin, sys.stdout).run()
        finally:
            if isinstance(ops, NativeGuardianOps) and Path(intent['journal']).exists(): ops.finish_journal()


def execute(binding_pin, authority_pin, direction, receipt_path, recovery_pin=None):
    """One independent guardian session, one bootstrap; no retry or blind recovery."""
    require(direction in ('activate', 'rollback'), 'DIRECTION_INVALID')
    body = verify_binding(binding_pin)
    execution_authority(authority_pin, binding_pin, body, direction)
    receipt = private_path(receipt_path, absent=True)
    require(receipt.parent == Path(body['evidence_root']), 'RECEIPT_PATH_ESCAPE')
    lifecycle = native_lifecycle(body['scope'], body['legacy_activity_disposition'])
    observed = lifecycle.identity()
    token = owner_for_transition(body, binding_pin, direction, observed, recovery_pin)
    require(token is None or token['status'] in (2,3), 'OWNER_ALREADY_STOPPED_OR_UNKNOWN')
    run = uuid4().hex
    intent_path = receipt.parent / ('intent-' + run + '.json')
    journal = receipt.parent / ('guardian-' + run + '.json')
    intent = dict(schema=INTENT_SCHEMA, mode='NATIVE_RELEASE', controller_pid=os.getpid(), owner_token=token,
        binding=binding_pin, authority=authority_pin, direction=direction, recovery=recovery_pin,
        journal=str(journal), receipt_path=str(receipt), helper_sha256=sha(__file__))
    write_new(intent_path, intent)
    stderr = private_path(receipt.parent / ('stderr-' + run + '.txt'), absent=True)
    with stderr.open('x') as stream:
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '_guardian',
            str(intent_path), sha(intent_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stream, text=True, start_new_session=True, close_fds=True)
    def event(expected):
        value = legacy().read_control(child.stdout, 45)
        require(value is not None and value.get('event') == expected, 'GUARDIAN_PROTOCOL_FAILED:' + str(value))
        return value
    try:
        ack = event('OWNED')
        require(ack.get('guardian_pid') == child.pid, 'GUARDIAN_ACK_PID')
        owned = json.loads(journal.read_bytes())
        require(owned['phase'] == 'OWNED' and owned['owner_token'] == token and owned['controller_pid'] == os.getpid() and
            owned['guardian_pid'] == child.pid, 'GUARDIAN_OWNERSHIP_JOURNAL')
        legacy().emit_control(child.stdin, dict(action='FREEZE')); event('FROZEN_IDLE')
        legacy().emit_control(child.stdin, dict(action='COMMIT')); event('BOOTOUT_COMMITTED'); event('OLD_OWNER_EXITED')
        legacy().emit_control(child.stdin, dict(action='START')); event('FINISHED')
        child.stdin.close(); child.wait(timeout=10)
        require(child.returncode == 0, 'GUARDIAN_EXIT_UNKNOWN')
        result = json.loads(receipt.read_bytes())
        require(result['state'] in {'ACTIVATED', 'ROLLED_BACK'}, 'GUARDIAN_RESULT_NOT_SUCCESS')
        return result
    except BaseException:
        if not child.stdin.closed: child.stdin.close()
        # Pipe EOF delegates unwind to the independent guardian; never kill it.
        try: child.wait(timeout=20)
        except subprocess.TimeoutExpired: raise ValueError('GUARDIAN_STILL_OWNS_RECOVERY:' + str(journal))
        raise
    finally:
        if child.poll() is not None:
            child.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('spec'); prepare_parser.add_argument('spec_sha'); prepare_parser.add_argument('output')
    guardian = sub.add_parser('_guardian'); guardian.add_argument('intent'); guardian.add_argument('intent_sha')
    for action in ('activate', 'rollback'):
        command = sub.add_parser(action)
        for name in ('binding', 'binding_sha', 'authority', 'authority_sha', 'receipt'): command.add_argument(name)
        command.add_argument('--recovery'); command.add_argument('--recovery-sha')
    args = parser.parse_args()
    if args.action == 'prepare': result = prepare(dict(path=args.spec, sha256=args.spec_sha), args.output)
    elif args.action == '_guardian': guardian_main(dict(path=args.intent, sha256=args.intent_sha)); return
    else:
        recovery = dict(path=args.recovery, sha256=args.recovery_sha) if args.recovery and args.recovery_sha else None
        result = execute(dict(path=args.binding, sha256=args.binding_sha), dict(path=args.authority, sha256=args.authority_sha),
            args.action, args.receipt, recovery)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
