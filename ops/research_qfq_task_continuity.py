"""Explicit same-input QFQ task re-keying, with no producer or live activation.

A reviewed plan is prepared from immutable owner evidence. Applying it is a
separate controller action under the original owner and shared-pool locks.
The row and its reservation move together in one existing registry commit.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ops.research_qfq_dependency_identity import computation_dependencies, validate_manifest, validate_turnover_evidence

from ops.research_storage_retention import RetentionError, canonical, digest, safe_path, stamp

SCHEMA = 'v4.qfq_task_root_migration.v1'
JOURNAL = 'qfq_root_migrations'
MAX_MIGRATIONS = 16


def _policy_identity(policy):
    governance = {key:value for key,value in (policy.get('governance') or {}).items()
                  if key not in {'qfq_legacy_resume', 'qfq_legacy_classification'}}
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
    from ops.research_storage_governance import qfq_invocation_key, qfq_helper_identity
    owner = safe_path(module.__file__)
    if owner.name != 'research_panel_qfq.py' or owner.parent.name != 'ops':
        raise RetentionError('QFQ_MIGRATION_OWNER_ROLE_REQUIRED')
    old_root = safe_path(old_root)
    old_owner = old_root / 'ops/research_panel_qfq.py'
    if digest(safe_path(old_owner)) != digest(owner):
        raise RetentionError('QFQ_MIGRATION_OWNER_BYTES_CHANGED')
    old_kwargs = dict(kwargs)
    for name in ('driver_path', 'formula_path', 'contract_csv'):
        source = safe_path(kwargs[name])
        if source.is_relative_to(owner.parent.parent):
            old_source = old_root / source.relative_to(owner.parent.parent)
            if digest(safe_path(old_source)) != digest(source):
                raise RetentionError('QFQ_MIGRATION_SOURCE_BYTES_CHANGED')
            old_kwargs[name] = old_source
    old_module = SimpleNamespace(__file__=str(old_owner), input_path=module.input_path)
    if qfq_helper_identity(old_module) != qfq_helper_identity(module):
        raise RetentionError('QFQ_MIGRATION_GENERATION_HELPER_BYTES_CHANGED')
    if computation_dependencies(old_module, old_kwargs, runtime_root=Path(module.input_path(data_root)).parent) != computation_dependencies(module, kwargs, runtime_root=Path(module.input_path(data_root)).parent):
        raise RetentionError('QFQ_MIGRATION_COMPUTATION_DEPENDENCIES_CHANGED')
    old_key = qfq_invocation_key(old_module, data_root, target, old_kwargs, legacy=True)
    key = qfq_invocation_key(module, data_root, target, kwargs)
    return old_key, key


def _validate_owner_evidence(module, target, kwargs, directory, snapshot, owner_receipt, evidence_refs):
    from ops.research_storage_governance import qfq_helper_identity
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
    if any(receipt.get(field) != sha256 for field,sha256 in qfq_helper_identity(module).items()):
        raise RetentionError('QFQ_MIGRATION_GENERATION_HELPER_EVIDENCE_CONFLICT')
    manifest = computation_dependencies(module, kwargs, snapshot=snapshot_value, runtime_root=Path(snapshot['path']).parent)
    validate_manifest(receipt.get('computation_dependencies'))
    if (receipt['computation_dependencies'] != manifest
            or receipt.get('computation_dependency_sha256') != canonical(manifest)):
        raise RetentionError('QFQ_MIGRATION_COMPUTATION_DEPENDENCY_EVIDENCE_CONFLICT')
    turnover = validate_turnover_evidence(module, kwargs, target, receipt.get('turnover_input_evidence'))
    if receipt.get('turnover_input_sha256') != turnover['identity']:
        raise RetentionError('QFQ_MIGRATION_TURNOVER_EVIDENCE_CONFLICT')
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
    from ops.research_storage_governance import Registry, configuration, qfq_helper_identity
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
        policy_identity_sha256=_policy_identity(policy), generation_helpers=qfq_helper_identity(module),
        computation_dependencies=computation_dependencies(module, kwargs, snapshot=_read_reference(snapshot), runtime_root=Path(snapshot['path']).parent),
        turnover_input_evidence=_read_reference(owner_receipt)['turnover_input_evidence'],
        pool_id=config['pool_id'], registry_root=str(registry.root), data_root=str(safe_path(data_root)),
        directory=directory, old_root=str(safe_path(old_root)), owner=_reference(module.__file__),
        sources=sources, snapshot=snapshot, owner_receipt=owner_receipt, evidence_refs=evidence_refs,
        linkage_review=linkage_review,
        expected_registry_sha256=expected_registry_sha256, token=expected_token, row_sha256=canonical(row),
        arguments=json.loads(json.dumps(kwargs, default=str)))
    if len(json.dumps(result).encode()) > 192 * 1024:
        raise RetentionError('QFQ_MIGRATION_PLAN_BUDGET')
    return result


def _validate_plan(module, policy, plan, data_root, return_root, target, kwargs):
    from ops.research_storage_governance import Registry, configuration, qfq_helper_identity
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA or type(plan.get('target')) is not int:
        raise RetentionError('QFQ_MIGRATION_SCHEMA')
    config = configuration(policy)
    if config is None:
        raise RetentionError('QFQ_MIGRATION_GOVERNANCE_REQUIRED')
    _check_owner_roots(policy, data_root, return_root)
    registry = Registry(config, data_root)
    if plan.get('snapshot') != _reference(module.input_path(data_root)):
        raise RetentionError('QFQ_MIGRATION_SNAPSHOT_DRIFT')
    validate_turnover_evidence(module, kwargs, target, plan.get('turnover_input_evidence'))
    validate_manifest(plan.get('computation_dependencies'))
    expected = dict(computation_dependencies=computation_dependencies(module, kwargs, snapshot=_read_reference(plan['snapshot']), runtime_root=Path(plan['snapshot']['path']).parent),
        policy_identity_sha256=_policy_identity(policy), generation_helpers=qfq_helper_identity(module), pool_id=config['pool_id'], registry_root=str(registry.root),
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
    if plan.get('turnover_input_evidence') != _read_reference(plan['owner_receipt']).get('turnover_input_evidence'):
        raise RetentionError('QFQ_MIGRATION_TURNOVER_EVIDENCE_CONFLICT')
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
            snapshot_sha256=plan['snapshot']['sha256'],
            computation_dependencies_sha256=canonical(plan['computation_dependencies']),
            turnover_input_sha256=plan['turnover_input_evidence']['identity'], before_registry_sha256=required_sha)
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


QFQ_NONTERMINAL = {'FAILED_RECOVERABLE', 'SPACE_BLOCKED', 'RUNNING', 'VALIDATING'}


def unclassified_qfq_rows(state, directory, current_key):
    committed = {record.get('key') for record in state.get(JOURNAL, {}).values()
                 if isinstance(record, dict) and record.get('state') == 'COMMITTED'}
    result = {}
    for key,row in state['tasks'].items():
        if (key == current_key or row.get('directory') != str(directory)
                or row.get('category') != 'ordinary' or row.get('state') not in QFQ_NONTERMINAL):
            continue
        marker = row.get('qfq_identity') or {}
        known = (isinstance(marker, dict) and marker.get('schema') == 'v4.qfq_operation_identity.v2'
                 and marker.get('key') == key)
        if key not in committed and not known:
            result[key] = canonical(row)
    return result


def check_unclassified_qfq_rows(state, directory, key, classified_rows):
    unknown = unclassified_qfq_rows(state, directory, key)
    if any(classified_rows.get(old_key) != row_sha for old_key,row_sha in unknown.items()):
        raise RetentionError('QFQ_UNCLASSIFIED_LEGACY_RESERVATION')


def _classified_for_other_dates(proof, unknown, state, target):
    entries = proof.get('classified_rows')
    if not isinstance(entries, dict) or len(entries) > 512:
        raise RetentionError('QFQ_LEGACY_CLASSIFICATION_UNPROVEN')
    result = {}
    for old_key,row_sha in unknown.items():
        item = entries.get(old_key)
        if (not isinstance(item, dict) or item.get('row_sha256') != row_sha
                or type(item.get('target')) is not int or item['target'] == target):
            raise RetentionError('QFQ_UNCLASSIFIED_LEGACY_RESERVATION')
        refs = item.get('owner_receipts')
        if not isinstance(refs, list) or not 1 <= len(refs) <= 16:
            raise RetentionError('QFQ_LEGACY_CLASSIFICATION_UNPROVEN')
        for ref in refs:
            receipt = _read_reference(ref)
            if (not isinstance(receipt, dict) or receipt.get('target_date') != item['target']
                    or not isinstance(receipt.get('run_dir'), str)
                    or safe_path(ref['path']).parent != safe_path(receipt['run_dir'])
                    or not safe_path(receipt['run_dir']).is_relative_to(Path(state['tasks'][old_key]['directory']))):
                raise RetentionError('QFQ_LEGACY_CLASSIFICATION_UNPROVEN')
        result[old_key] = row_sha
    return result


def qfq_admission_context(module, policy, data_root, return_root, target, key):
    from ops.research_storage_governance import Registry, configuration, qfq_helper_identity
    config = configuration(policy)
    if config is None:
        return None
    registry = Registry(config, data_root)
    state = registry.read()
    unknown = unclassified_qfq_rows(state, return_root, key)
    if not unknown:
        return dict(target=target, classified_rows={})
    ref = (policy.get('governance') or {}).get('qfq_legacy_classification')
    if not ref:
        raise RetentionError('QFQ_UNCLASSIFIED_LEGACY_RESERVATION')
    proof = _read_reference(ref)
    common = dict(evidence_closed=True, pool_id=config['pool_id'], registry_root=str(registry.root),
        data_root=str(safe_path(data_root)), directory=str(safe_path(return_root)))
    if (not isinstance(proof, dict) or not isinstance(proof.get('reviewer'), str)
            or not proof['reviewer'].strip() or any(proof.get(k) != v for k,v in common.items())):
        raise RetentionError('QFQ_LEGACY_CLASSIFICATION_UNPROVEN')
    if (proof.get('schema') == 'v4.qfq_legacy_task_scope.v1'
            and proof.get('status') == 'REVIEWED_TASK_SCOPES'):
        # Frozen old task scope can distinguish later dates without a daily
        # re-attestation. Same-date inputs always require the exact bridge or
        # the more specific distinct-operation proof below.
        classified = _classified_for_other_dates(proof, unknown, state, target)
    else:
        expected = dict(schema='v4.qfq_legacy_task_classification.v1', status='REVIEWED_DISTINCT_OPERATION',
            key=key, target=target, generation_helpers=qfq_helper_identity(module),
            snapshot=_reference(module.input_path(data_root)))
        if (any(proof.get(k) != v for k,v in expected.items())
                or not isinstance(proof.get('classified_rows'), dict) or len(proof['classified_rows']) > 512):
            raise RetentionError('QFQ_LEGACY_CLASSIFICATION_UNPROVEN')
        classified = proof['classified_rows']
    check_unclassified_qfq_rows(state, return_root, key, classified)
    return dict(target=target, classified_rows=classified)
