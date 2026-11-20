"""Explicit same-input QFQ task re-keying, with no producer or live activation.

A reviewed plan is prepared from immutable owner evidence. Applying it is a
separate controller action under the original owner and shared-pool locks.
The row and its reservation move together in one existing registry commit.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ops.research_storage_retention import RetentionError, canonical, digest, safe_path, stamp

SCHEMA = 'v4.qfq_task_root_migration.v1'
JOURNAL = 'qfq_root_migrations'
MAX_MIGRATIONS = 16


def _policy_identity(policy):
    governance = {key:value for key,value in (policy.get('governance') or {}).items()
                  if key != 'qfq_legacy_resume'}
    return canonical({**policy, 'governance':governance})


def _check_owner_roots(policy, data_root, return_root):
    if (str(safe_path(data_root)) != policy.get('data_root')
            or str(safe_path(return_root)) != policy.get('run_root')):
        raise RetentionError('QFQ_MIGRATION_POLICY_OWNER_ROOT_DRIFT')


def _reference(path):
    path = safe_path(path)
    before = stamp(path)
    result = dict(path=str(path), sha256=digest(path))
    if stamp(path) != before:
        raise RetentionError('QFQ_MIGRATION_REFERENCE_CHANGED')
    return result


def _read_reference(ref):
    path = safe_path(ref['path'])
    before = stamp(path)
    raw = path.read_bytes()
    import hashlib
    if hashlib.sha256(raw).hexdigest() != ref['sha256'] or stamp(path) != before:
        raise RetentionError('QFQ_MIGRATION_REFERENCE_DRIFT')
    return json.loads(raw)


def _identity(module, data_root, target, kwargs, old_root):
    from ops.research_storage_governance import qfq_invocation_key
    owner = safe_path(module.__file__)
    if owner.name != 'research_panel_qfq.py' or owner.parent.name != 'ops':
        raise RetentionError('QFQ_MIGRATION_OWNER_ROLE_REQUIRED')
    old_root = safe_path(old_root)
    old_owner = old_root / 'ops/research_panel_qfq.py'
    if digest(safe_path(old_owner)) != digest(owner):
        raise RetentionError('QFQ_MIGRATION_OWNER_BYTES_CHANGED')
    old_kwargs = dict(kwargs)
    driver = safe_path(kwargs['driver_path'])
    bundled = owner.parent / 'vendor/data_layer_daily_formula_increment_update_v1.py'
    if driver == bundled:
        old_driver = old_root / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py'
        if digest(safe_path(old_driver)) != digest(driver):
            raise RetentionError('QFQ_MIGRATION_DRIVER_BYTES_CHANGED')
        old_kwargs['driver_path'] = old_driver
    old_module = SimpleNamespace(__file__=str(old_owner), input_path=module.input_path)
    old_key = qfq_invocation_key(old_module, data_root, target, old_kwargs, legacy=True)
    key = qfq_invocation_key(module, data_root, target, kwargs)
    return old_key, key


def _validate_owner_evidence(module, target, kwargs, directory, snapshot, owner_receipt, evidence_refs):
    receipt = _read_reference(owner_receipt)
    snapshot_value = _read_reference(snapshot)
    if (receipt.get('target_date') != target or snapshot_value.get('asof_date') != target
            or receipt.get('snapshot_file_sha256') != snapshot['sha256']
            or receipt.get('adapter_sha256') != digest(Path(module.__file__))
            or receipt.get('driver_sha256') != digest(Path(kwargs['driver_path']))
            or receipt.get('formula_sha256') != digest(Path(kwargs['formula_path']))
            or receipt.get('field_contract_sha256') != digest(Path(kwargs['contract_csv']))
            or receipt.get('input_sha256') != canonical(snapshot_value)):
        raise RetentionError('QFQ_MIGRATION_OWNER_INPUT_EVIDENCE_CONFLICT')
    generation = receipt.get('generation_id')
    run = safe_path(receipt['run_dir'])
    if (not isinstance(generation, str) or len(generation) != 64
            or run != Path(directory) / ('qfq_' + generation[:20])
            or safe_path(owner_receipt['path']).parent != run
            or receipt.get('status') not in {'CANDIDATE_READY', 'READY'}):
        raise RetentionError('QFQ_MIGRATION_OWNER_RUN_CONFLICT')
    if not evidence_refs or len(evidence_refs) > 16:
        raise RetentionError('QFQ_MIGRATION_REVIEW_EVIDENCE_REQUIRED')
    for ref in evidence_refs:
        _read_reference(ref)


def _validate_linkage(ref, **expected):
    # The mutable-refresh operation key has no final generation field. A
    # controller must supply reviewed ownership evidence before mapping an
    # old task row to a particular frozen input; date or directory alone fails.
    value = _read_reference(ref)
    if (not isinstance(value, dict) or value.get('schema') != 'v4.qfq_task_artifact_linkage.v1'
            or value.get('status') != 'REVIEWED_SAME_TASK' or value.get('evidence_closed') is not True
            or not isinstance(value.get('reviewer'), str) or not value['reviewer'].strip()
            or any(value.get(key) != item for key, item in expected.items())):
        raise RetentionError('QFQ_MIGRATION_TASK_ARTIFACT_LINKAGE_UNPROVEN')


def prepare_qfq_migration(module, policy, *, data_root, return_root, target, kwargs,
                          old_root, expected_registry_sha256, expected_token,
                          owner_receipt, evidence_refs, linkage_review):
    """Prepare exact, bounded metadata only. No locks or registry writes."""
    from ops.research_storage_governance import Registry, configuration
    config = configuration(policy)
    if config is None:
        raise RetentionError('QFQ_MIGRATION_GOVERNANCE_REQUIRED')
    _check_owner_roots(policy, data_root, return_root)
    registry = Registry(config, data_root)
    if digest(registry.path) != expected_registry_sha256:
        raise RetentionError('QFQ_MIGRATION_REGISTRY_DRIFT')
    old_key, key = _identity(module, data_root, target, kwargs, old_root)
    state = registry.read()
    row = state['tasks'].get(old_key)
    if not row or row.get('token') != expected_token:
        raise RetentionError('QFQ_MIGRATION_TASK_DRIFT')
    directory = str(safe_path(return_root))
    if row.get('directory') != directory:
        raise RetentionError('IDENTITY_REQUIRES_ORIGINAL_DIRECTORY')
    if row['state'] not in {'FAILED_RECOVERABLE', 'SPACE_BLOCKED'} or row['category'] != 'ordinary':
        raise RetentionError('QFQ_MIGRATION_ONLY_RECOVERABLE_ORDINARY_TASK')
    if key in state['tasks']:
        raise RetentionError('QFQ_MIGRATION_NEW_KEY_EXISTS')
    snapshot = _reference(module.input_path(data_root))
    _validate_owner_evidence(module, target, kwargs, directory, snapshot, owner_receipt, evidence_refs)
    _validate_linkage(linkage_review, row_sha256=canonical(row), old_key=old_key, target=target,
                      registry_root=str(registry.root), data_root=str(safe_path(data_root)),
                      directory=directory, snapshot=snapshot, owner_receipt=owner_receipt)
    sources = {name:_reference(kwargs[name]) for name in ('driver_path', 'formula_path', 'contract_csv')}
    result = dict(schema=SCHEMA, old_key=old_key, key=key, target=target,
        policy_identity_sha256=_policy_identity(policy),
        pool_id=config['pool_id'], registry_root=str(registry.root), data_root=str(safe_path(data_root)),
        directory=directory, old_root=str(safe_path(old_root)), owner=_reference(module.__file__),
        sources=sources, snapshot=snapshot, owner_receipt=owner_receipt, evidence_refs=evidence_refs,
        linkage_review=linkage_review,
        expected_registry_sha256=expected_registry_sha256, token=expected_token, row_sha256=canonical(row),
        arguments=json.loads(json.dumps(kwargs, default=str)))
    if len(json.dumps(result).encode()) > 16 * 1024:
        raise RetentionError('QFQ_MIGRATION_PLAN_BUDGET')
    return result


def _validate_plan(module, policy, plan, data_root, return_root, target, kwargs):
    from ops.research_storage_governance import Registry, configuration
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA or type(plan.get('target')) is not int:
        raise RetentionError('QFQ_MIGRATION_SCHEMA')
    config = configuration(policy)
    if config is None:
        raise RetentionError('QFQ_MIGRATION_GOVERNANCE_REQUIRED')
    _check_owner_roots(policy, data_root, return_root)
    registry = Registry(config, data_root)
    expected = dict(policy_identity_sha256=_policy_identity(policy), pool_id=config['pool_id'], registry_root=str(registry.root),
        data_root=str(safe_path(data_root)), directory=str(safe_path(return_root)), target=target,
        arguments=json.loads(json.dumps(kwargs, default=str)))
    if any(plan.get(k) != v for k,v in expected.items()):
        raise RetentionError('QFQ_MIGRATION_SCOPE_DRIFT')
    old_key, key = _identity(module, data_root, target, kwargs, plan['old_root'])
    if plan.get('old_key') != old_key or plan.get('key') != key:
        raise RetentionError('QFQ_MIGRATION_IDENTITY_DRIFT')
    if plan.get('owner') != _reference(module.__file__):
        raise RetentionError('QFQ_MIGRATION_OWNER_DRIFT')
    for name in ('driver_path', 'formula_path', 'contract_csv'):
        if plan['sources'].get(name) != _reference(kwargs[name]):
            raise RetentionError('QFQ_MIGRATION_SOURCE_DRIFT')
    if plan.get('snapshot') != _reference(module.input_path(data_root)):
        raise RetentionError('QFQ_MIGRATION_SNAPSHOT_DRIFT')
    _validate_owner_evidence(module, target, kwargs, plan['directory'], plan['snapshot'],
                             plan['owner_receipt'], plan['evidence_refs'])
    _validate_linkage(plan['linkage_review'], row_sha256=plan['row_sha256'], old_key=old_key,
                      target=target, registry_root=str(registry.root), data_root=str(safe_path(data_root)),
                      directory=plan['directory'], snapshot=plan['snapshot'], owner_receipt=plan['owner_receipt'])
    return registry


def migrate_qfq_task(module, policy, plan, *, data_root, return_root, target, kwargs,
                     rollback=False, expected_registry_sha256=None):
    """Explicit reversible CAS operation. Existing locks fence every state write.

    An idempotent retry after the one atomic registry replace verifies both row
    and journal. A partially written temporary never forms a second task.
    """
    from ops.research_storage_governance import owner_state
    from ops.research_storage_retention import owner_lock
    registry = _validate_plan(module, policy, plan, data_root, return_root, target, kwargs)
    with owner_lock(policy), owner_lock(policy, publication=True), registry.writer(), registry.transaction():
        registry = _validate_plan(module, policy, plan, data_root, return_root, target, kwargs)
        state = registry.read()
        journal = state.setdefault(JOURNAL, {})
        if not isinstance(journal, dict) or len(journal) > MAX_MIGRATIONS:
            raise RetentionError('QFQ_MIGRATION_JOURNAL_BUDGET')
        migration_id = canonical(plan)
        previous = journal.get(migration_id)
        from_key, to_key = (plan['key'], plan['old_key']) if rollback else (plan['old_key'], plan['key'])
        desired = 'ROLLED_BACK' if rollback else 'COMMITTED'
        row = state['tasks'].get(from_key)
        if previous and previous.get('state') == desired:
            existing = state['tasks'].get(to_key)
            if (from_key in state['tasks'] or not existing
                    or canonical(existing) != plan['row_sha256']):
                raise RetentionError('QFQ_MIGRATION_ALREADY_APPLIED_ROW_DRIFT')
            return dict(status='ALREADY_' + desired, key=to_key, registry_sha256=digest(registry.path))
        required_sha = expected_registry_sha256 if rollback else plan['expected_registry_sha256']
        if required_sha is None or digest(registry.path) != required_sha:
            raise RetentionError('QFQ_MIGRATION_REGISTRY_DRIFT')
        if (not row or row.get('token') != plan['token'] or canonical(row) != plan['row_sha256']
                or row.get('directory') != plan['directory']):
            raise RetentionError('QFQ_MIGRATION_TASK_DRIFT')
        if row['state'] not in {'FAILED_RECOVERABLE', 'SPACE_BLOCKED'} or owner_state(row.get('owner')) != 'DEAD':
            raise RetentionError('QFQ_MIGRATION_OWNER_LIVE_OR_UNKNOWN')
        if to_key in state['tasks']:
            raise RetentionError('QFQ_MIGRATION_NEW_KEY_EXISTS')
        if rollback and (not previous or previous.get('state') != 'COMMITTED'):
            raise RetentionError('QFQ_MIGRATION_ROLLBACK_WITHOUT_COMMIT')
        if not previous and len(journal) >= MAX_MIGRATIONS:
            raise RetentionError('QFQ_MIGRATION_JOURNAL_BUDGET')
        record = dict(state=desired, old_key=plan['old_key'], key=plan['key'], target=target,
            row_sha256=plan['row_sha256'], owner_sha256=plan['owner']['sha256'],
            snapshot_sha256=plan['snapshot']['sha256'], before_registry_sha256=required_sha)
        state['tasks'][to_key] = state['tasks'].pop(from_key)
        journal[migration_id] = record
        registry.save(state)
        return dict(status=desired, key=to_key, registry_sha256=digest(registry.path), migration_id=migration_id)


def require_migrated_resume(module, policy, data_root, return_root, target, kwargs, key):
    """Normal owner entry never silently migrates an explicit legacy bridge."""
    configured = (policy.get('governance') or {}).get('qfq_legacy_resume')
    if not configured:
        from ops.research_storage_governance import Registry, configuration, qfq_invocation_key
        config = configuration(policy)
        if config is not None:
            registry = Registry(config, data_root)
            legacy_key = qfq_invocation_key(module, data_root, target, kwargs, legacy=True)
            legacy = registry.read()['tasks'].get(legacy_key)
            if legacy and legacy['state'] in {'FAILED_RECOVERABLE', 'SPACE_BLOCKED', 'RUNNING', 'VALIDATING'}:
                raise RetentionError('QFQ_LEGACY_RESUME_CONTROL_REQUIRED')
        return None
    plan = _read_reference(configured)
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA or type(plan.get('target')) is not int:
        raise RetentionError('QFQ_MIGRATION_SCHEMA')
    if plan.get('target') != target:
        return None
    registry = _validate_plan(module, policy, plan, data_root, return_root, target, kwargs)
    state = registry.read()
    record = state.get(JOURNAL, {}).get(canonical(plan))
    if (key != plan['key'] or plan['old_key'] in state['tasks'] or not record
            or record.get('state') != 'COMMITTED' or key not in state['tasks']):
        raise RetentionError('QFQ_LEGACY_RESUME_MIGRATION_REQUIRED')
    return plan
