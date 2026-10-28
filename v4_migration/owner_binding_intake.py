"""Explicit-file, read-only preselection owner intake. Never binds an owner.

A digest proves the bytes read, not who approved them or what ran on a host.
No inspected source is imported. No adapter, producer, or scheduler is called.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import plistlib
import stat
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .contracts import canonical_sha256, valid_sha
from .owner_bindings import REQUIRED_ACTIONS
from .safe_io import open_absolute_dir, open_relative_parent

# Byte limits, not calibrated memory/time guarantees. All are fail-closed.
MAX_REQUEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_COLLECTION_READ_BYTES = 64 * 1024 * 1024
_READ_BUDGET: ContextVar[list[int] | None] = ContextVar('owner_intake_read_budget', default=None)


class ReadLimitExceeded(ValueError):
    """A configured I/O limit was exceeded; reject the whole collection."""


def _bounded_fd_read(fd: int, limit: int) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('REGULAR_FILE_REQUIRED')
    if before.st_size > limit:
        raise ReadLimitExceeded('READ_LIMIT_EXCEEDED')
    budget = _READ_BUDGET.get()
    if budget is not None and before.st_size > budget[0]:
        raise ReadLimitExceeded('COLLECTION_READ_BUDGET_EXCEEDED')
    chunks: list[bytes] = []
    total = 0
    while True:
        # One sentinel byte detects a file growing after fstat. Never read the
        # entire changed file before checking limits.
        count = min(1024 * 1024, limit - total + 1)
        if budget is not None:
            count = min(count, budget[0] + 1)
        chunk = os.read(fd, count)
        if not chunk:
            break
        total += len(chunk)
        if budget is not None:
            budget[0] -= len(chunk)
        if total > limit:
            raise ReadLimitExceeded('READ_LIMIT_EXCEEDED')
        if budget is not None and budget[0] < 0:
            raise ReadLimitExceeded('COLLECTION_READ_BUDGET_EXCEEDED')
        chunks.append(chunk)
    after = os.fstat(fd)
    def identity(st: os.stat_result) -> tuple[int, ...]:
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if identity(before) != identity(after) or total != before.st_size:
        raise ValueError('FILE_CHANGED_DURING_READ')
    return b''.join(chunks)


def _read_limited(root: str | Path, relative: str, limit: int) -> bytes:
    # Reuse accepted descriptor traversal; do not resolve or follow symlinks.
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_NONBLOCK'):
        raise ValueError('NOFOLLOW_NONBLOCK_PLATFORM_REQUIRED')
    root_fd = open_absolute_dir(root)
    try:
        parent_fd, leaf = open_relative_parent(root_fd, relative)
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)
            fd = os.open(leaf, flags, dir_fd=parent_fd)
            try:
                return _bounded_fd_read(fd, limit)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)


def read_relative_file(root: str | Path, relative: str) -> bytes:
    """Local bounded reader; safe_io and all other consumers stay unchanged."""
    return _read_limited(root, relative, MAX_FILE_BYTES)


def read_absolute_file(path: str | Path) -> bytes:
    """Requests use their own smaller cap, including validation and rereads."""
    absolute = _absolute(str(path))
    return _read_limited(absolute.parent, absolute.name, MAX_REQUEST_BYTES)

SCHEMA = 'v4.owner_binding.readonly_request.v1'
EVIDENCE_ROLES = ('owner_context', 'runtime_receipt', 'scheduler_receipt',
                  'scope_decision', 'authorization_policy')
ACTION_REQUIREMENTS = {
    'fence': {
        'implementation_sites': ['source store gate', 'target store gate', 'two preselection workloads'],
        'owner_facts': ['exact date/pool keyset', 'owner/release/root identity',
                        'caller write_gate_context', 'gate revision under existing locks',
                        'scheduled/direct/recovery writer coverage'],
        'must_not_substitute': 'Holding a lock or stopping a claim is not a persistent fence.'},
    'drain': {
        'implementation_sites': ['execution ledger', 'parent/child lifecycle', 'both store barriers'],
        'owner_facts': ['active nonterminal claims', 'parent/child birth identity',
                        'fence revision retained', 'source then target barrier protocol'],
        'must_not_substitute': 'Historical success or no new dispatch is not zero in-flight work.'},
    'final_delta': {
        'implementation_sites': ['source and target snapshot readers under agreed barriers'],
        'owner_facts': ['exact keyset', 'two physical roots', 'fenced revisions',
                        'artifact/manifest/receipt identities', 'drift/no-loss disposition'],
        'must_not_substitute': 'No latest/mtime/row-count winner selection.'},
    'switch': {
        'implementation_sites': ['preselection-only workload target', 'explicit owner revision resolver'],
        'owner_facts': ['expected before revision and digest', 'approved after mapping',
                        'separate authorization trust root', 'unrelated workload exclusion'],
        'must_not_substitute': 'Do not change the shared scheduler global data root.'},
    'readback': {
        'implementation_sites': ['loaded store/API exact date/pool reader'],
        'owner_facts': ['loaded release/runtime', 'resolved owner/root revision',
                        'physical trio digests', 'read lease and drift handling'],
        'must_not_substitute': 'A static function declaration is not live loaded-path readback.'},
    'rollback': {
        'implementation_sites': ['owner revision CAS recovery', 'gated recovery readback'],
        'owner_facts': ['expected current revision', 'captured prior revision',
                        'post-switch writes preservation', 'failed rollback keeps gates closed'],
        'must_not_substitute': 'A simulation or deleted helper is not implemented real rollback.'},
}
FALSE_FLAGS = {
    'owner_binding_established': False, 'authority_cutover_authorized': False,
    'production_switch_executed': False, 'writer_fenced': False, 'writer_drained': False,
    'canonical_root_changed': False, 'scheduler_changed': False, 'old_system_retired': False,
    'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
    'execution_performed': False, 'module_imported': False,
}


def _keys(value: Any, allowed: set[str], required: set[str]) -> None:
    if not isinstance(value, dict):
        raise ValueError('OBJECT_REQUIRED')
    if set(value) - allowed:
        raise ValueError('UNEXPECTED_FIELDS:' + ','.join(sorted(set(value) - allowed)))
    if required - set(value):
        raise ValueError('MISSING_FIELDS:' + ','.join(sorted(required - set(value))))


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('DUPLICATE_JSON_KEY:' + key)
        out[key] = value
    return out


def _bad_constant(value: str) -> None:
    raise ValueError('NONFINITE_JSON_NUMBER:' + value)


def _json(data: bytes) -> Any:
    return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_bad_constant)


def _absolute(value: Any) -> Path:
    if (not isinstance(value, str) or not value or not os.path.isabs(value)
            or '..' in Path(value).parts or '\x00' in value):
        raise ValueError('ABSOLUTE_NONTRAVERSING_PATH_REQUIRED')
    return Path(os.path.abspath(value))


def _scope_path(value: str | Path) -> None:
    """Fixed exclusions apply to the whole lexical path, independent of root split."""
    lower = str(value).casefold()
    if any(token in lower for token in ('wechat', 'weixin', '公众号', 'manager', 'vibe', '8910')):
        raise ValueError('EXCLUDED_SCOPE')
    if any(part in ('preselection_pools', 'evidence_current_raw') for part in PurePosixPath(lower).parts):
        raise ValueError('DATA_PAYLOAD_EXCLUDED')


def _relative(value: Any) -> str:
    if (not isinstance(value, str) or not value or '\\' in value or '\x00' in value
            or value.startswith('/') or any(x in ('', '.', '..') for x in value.split('/'))):
        raise ValueError('RELATIVE_PATH_INVALID')
    _scope_path(value)
    if PurePosixPath(value).suffix not in ('.py', '.json', '.plist'):
        raise ValueError('UNSUPPORTED_SOURCE_OR_RECEIPT_TYPE')
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value or not all(p.isidentifier() for p in value.split('.')):
        raise ValueError('QUALIFIED_NAME_INVALID')
    return value


def _decl(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Only module functions or explicitly named class methods, not nested functions."""
    body = tree.body
    parts = name.split('.')
    for i, part in enumerate(parts):
        matches = [n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part]
        if len(matches) != 1:
            return None
        node = matches[0]
        if i == len(parts) - 1:
            return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        if not isinstance(node, ast.ClassDef):
            return None
        body = node.body
    return None


def _calls(node: ast.FunctionDef | ast.AsyncFunctionDef, expression: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    pending = list(node.body)
    while pending:
        item = pending.pop()
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(item, ast.Call) and ast.unparse(item.func) == expression:
            result.append({'line': item.lineno, 'expression': expression,
                           'keyword_names': [k.arg for k in item.keywords]})
        pending.extend(ast.iter_child_nodes(item))
    return sorted(result, key=lambda r: r['line'])


def _declaration(spec: dict[str, Any] | None, trees: dict[str, ast.Module]) -> dict[str, Any]:
    if spec is None:
        return {'status': 'NOT_SUPPLIED'}
    name = spec['qualified_name']; tree = trees.get(spec['file_id'])
    n = _decl(tree, name) if tree is not None else None
    if n is None:
        return {'status': 'STATIC_DECLARATION_MISSING_OR_AMBIGUOUS',
                'file_id': spec['file_id'], 'qualified_name': name, 'matching_calls': []}
    row = {'status': 'STATIC_DECLARATION_FOUND', 'file_id': spec['file_id'],
           'qualified_name': name, 'line_start': n.lineno, 'line_end': n.end_lineno,
           'signature': ast.unparse(n.args), 'async': isinstance(n, ast.AsyncFunctionDef),
           'decorated': bool(n.decorator_list), 'runtime_resolution_verified': False}
    if 'call_expression' in spec:
        row['matching_calls'] = _calls(n, spec['call_expression'])
        row['receiver_binding_verified'] = False
    return row


def _check_decl(spec: Any, files: dict[str, Any], *, caller: bool = False) -> None:
    if spec is None:
        return
    required = {'file_id', 'qualified_name'} | ({'call_expression'} if caller else set())
    _keys(spec, required, required)
    if spec['file_id'] not in files or not files[spec['file_id']]['relative_path'].endswith('.py'):
        raise ValueError('DECLARATION_PYTHON_FILE_REFERENCE_REQUIRED')
    _name(spec['qualified_name'])
    if caller:
        _name(spec['call_expression'])


def _validate(plan: Any, allowed_roots: Iterable[str]) -> dict[str, Path]:
    fields = {'schema', 'request_id', 'scope', 'roots', 'protected_roots', 'files', 'primitives', 'actions'}
    _keys(plan, fields, fields)
    if plan['schema'] != SCHEMA or plan['scope'] != 'PRESELECTION_ONLY':
        raise ValueError('SCHEMA_OR_SCOPE_INVALID')
    if not isinstance(plan['request_id'], str) or not plan['request_id'].strip():
        raise ValueError('REQUEST_ID_REQUIRED')
    roots = plan['roots']; files = plan['files']
    if not isinstance(roots, dict) or not roots or not isinstance(files, dict) or len(files) > 128:
        raise ValueError('ROOTS_OR_FILE_LIST_INVALID')
    allowed = {_absolute(str(p)) for p in allowed_roots}
    actual = {name: _absolute(p) for name, p in roots.items()}
    if not all(isinstance(k, str) and k for k in roots) or any(p not in allowed for p in actual.values()):
        raise ValueError('ROOT_NOT_EXPLICITLY_ALLOWED')
    if not isinstance(plan['protected_roots'], list):
        raise ValueError('PROTECTED_ROOT_LIST_REQUIRED')
    for p in plan['protected_roots']:
        _absolute(p)
    paths: set[str] = set()
    for file_id, row in files.items():
        if not isinstance(file_id, str) or not file_id:
            raise ValueError('FILE_ID_INVALID')
        _keys(row, {'root_id', 'relative_path', 'sha256', 'bytes'}, {'root_id', 'relative_path', 'sha256', 'bytes'})
        if row['root_id'] not in actual:
            raise ValueError('FILE_ROOT_UNBOUND')
        relative = _relative(row['relative_path'])
        unpinned = row['sha256'] is None and row['bytes'] is None
        if not unpinned and (not valid_sha(row['sha256']) or type(row['bytes']) is not int or not 0 <= row['bytes'] <= MAX_FILE_BYTES):
            raise ValueError('FILE_IDENTITY_INVALID')
        path = str(actual[row['root_id']] / relative)
        _scope_path(path)
        if path in paths:
            raise ValueError('DUPLICATE_FILE_PATH')
        paths.add(path)
    if not isinstance(plan['primitives'], list):
        raise ValueError('PRIMITIVE_LIST_REQUIRED')
    for p in plan['primitives']:
        _check_decl(p, files)
        if p is None:
            raise ValueError('PRIMITIVE_REFERENCE_REQUIRED')
    _keys(plan['actions'], set(REQUIRED_ACTIONS), set(REQUIRED_ACTIONS))
    for row in plan['actions'].values():
        if row is None:
            continue
        f = {'owner_claim', 'adapter', 'caller', 'evidence'}
        _keys(row, f, f)
        if row['owner_claim'] is not None and (not isinstance(row['owner_claim'], str) or not row['owner_claim'].strip()):
            raise ValueError('OWNER_CLAIM_INVALID')
        _check_decl(row['adapter'], files); _check_decl(row['caller'], files, caller=True)
        _keys(row['evidence'], set(EVIDENCE_ROLES), set(EVIDENCE_ROLES))
        for file_id in row['evidence'].values():
            if file_id is not None and (not isinstance(file_id, str) or file_id not in files or not files[file_id]['relative_path'].endswith(('.json', '.plist'))):
                raise ValueError('EVIDENCE_FILE_REFERENCE_INVALID')
    return actual


def collect_request(path: str | Path, *, expected_sha256: str,
                    allowed_roots: Iterable[str]) -> dict[str, Any]:
    """One collection budget includes the request, each source and every reread."""
    budget = [MAX_COLLECTION_READ_BYTES]
    token = _READ_BUDGET.set(budget)
    try:
        result = _collect_request(path, expected_sha256=expected_sha256, allowed_roots=tuple(allowed_roots))
        result['resource_limits'] = {
            'request_bytes': MAX_REQUEST_BYTES, 'file_bytes': MAX_FILE_BYTES,
            'collection_read_bytes': MAX_COLLECTION_READ_BYTES,
            'observed_read_bytes': MAX_COLLECTION_READ_BYTES - budget[0],
            'scope': 'BYTE_IO_LIMITS_NOT_RSS_OR_TIME_BOUND',
        }
        return result
    finally:
        _READ_BUDGET.reset(token)


def _collect_request(path: str | Path, *, expected_sha256: str,
                     allowed_roots: Iterable[str]) -> dict[str, Any]:
    """Read only named files twice. Supplied receipts are NOT treated as approvals."""
    request_path = _absolute(str(path)); raw = read_absolute_file(request_path)
    if not valid_sha(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('REQUEST_IDENTITY_MISMATCH')
    plan = _json(raw); roots = _validate(plan, allowed_roots)
    results: dict[str, Any] = {}; trees: dict[str, ast.Module] = {}; seen: dict[str, tuple[str, int]] = {}
    for file_id, ref in plan['files'].items():
        row = {'file_id': file_id, **ref, 'path': str(roots[ref['root_id']] / ref['relative_path']),
               'attestation_verified': False}
        try:
            data = read_relative_file(roots[ref['root_id']], ref['relative_path'])
            row.update(observed_sha256=hashlib.sha256(data).hexdigest(), observed_bytes=len(data))
            unpinned = ref['sha256'] is None and ref['bytes'] is None
            if not unpinned and (row['observed_sha256'] != ref['sha256'] or len(data) != ref['bytes']):
                row['status'] = 'IDENTITY_MISMATCH'
            else:
                suffix = PurePosixPath(ref['relative_path']).suffix
                if suffix == '.py':
                    trees[file_id] = ast.parse(data.decode('utf-8'), filename=ref['relative_path'])
                else:
                    parsed = plistlib.loads(data) if suffix == '.plist' else _json(data)
                    if not isinstance(parsed, dict):
                        raise ValueError('RECEIPT_OBJECT_REQUIRED')
                row['status'] = 'OBSERVED_UNPINNED' if unpinned else 'BYTES_VERIFIED_AT_READ'
                seen[file_id] = (row['observed_sha256'], len(data))
        except ReadLimitExceeded:
            raise
        except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError) as exc:
            row['status'] = 'UNREADABLE_OR_UNSAFE' if isinstance(exc, OSError) else 'CONTENT_SHAPE_INVALID'
            row['error_type'] = type(exc).__name__
        results[file_id] = row
    # Every sampled source is reopened. This is point-in-time drift detection, not a lock/lease.
    for file_id, before in seen.items():
        ref = plan['files'][file_id]
        try:
            again = read_relative_file(roots[ref['root_id']], ref['relative_path'])
            stable = (hashlib.sha256(again).hexdigest(), len(again)) == before
        except ReadLimitExceeded:
            raise
        except (OSError, ValueError):
            stable = False
        if not stable:
            results[file_id]['status'] = 'CHANGED_DURING_COLLECTION'; trees.pop(file_id, None)
    if read_absolute_file(request_path) != raw:
        raise ValueError('REQUEST_CHANGED_DURING_COLLECTION')
    actions: dict[str, Any] = {}
    for action in REQUIRED_ACTIONS:
        spec = plan['actions'][action]
        missing: list[str] = []
        if spec is None:
            spec = {'owner_claim': None, 'adapter': None, 'caller': None, 'evidence': {k: None for k in EVIDENCE_ROLES}}
        adapter = _declaration(spec['adapter'], trees); caller = _declaration(spec['caller'], trees)
        if not spec['owner_claim']: missing.append('OWNER_ASSERTION_REQUIRED')
        if adapter['status'] != 'STATIC_DECLARATION_FOUND': missing.append('EXACT_ADAPTER_SOURCE_REQUIRED')
        if caller['status'] != 'STATIC_DECLARATION_FOUND': missing.append('EXACT_CALLER_SOURCE_REQUIRED')
        if not caller.get('matching_calls'): missing.append('CALLSITE_NOT_FOUND')
        for role in ('adapter', 'caller'):
            if spec[role] is not None and results[spec[role]['file_id']]['status'] != 'BYTES_VERIFIED_AT_READ':
                missing.append(role.upper() + '_SOURCE_PIN_REQUIRED')
        for role, file_id in spec['evidence'].items():
            if file_id is None or results[file_id]['status'] != 'BYTES_VERIFIED_AT_READ':
                missing.append(role.upper() + '_REQUIRED')
        # collect_candidate has an unbounded third read. Do not call or monkey-
        # patch the inherited module. Qualified declarations above are from the
        # two bounded reads, and the historical observation is explicitly absent.
        actions[action] = {'binding_status': 'UNBOUND', 'owner_claim_untrusted': spec['owner_claim'],
                           'input_completeness': 'INCOMPLETE' if missing else 'SUPPLIED_NOT_ATTESTED',
                           'adapter_declaration': adapter, 'caller_declaration': caller,
                           'evidence_refs': spec['evidence'], 'missing': missing,
                           'inherited_collector_observation': None,
                           'inherited_collector_status': 'NOT_CALLED_UNBOUNDED_LEGACY_READER',
                           'remaining_review': ['owner/runtime/caller relationship', 'real writer coverage',
                                                'external approval and authorization trust root']}
    primitives = [_declaration(p, trees) for p in plan['primitives']]
    return {'schema': 'v4.owner_binding.readonly_collection.v1',
            'status': 'COLLECTION_ONLY_NOT_OWNER_BOUND', 'request_id': plan['request_id'],
            'request_sha256': expected_sha256, 'request_bytes': len(raw),
            'files': results, 'primitives': primitives,
            'primitive_error_count': sum(p['status'] != 'STATIC_DECLARATION_FOUND' for p in primitives),
            'actions': actions, 'missing_action_count': sum(bool(x['missing']) for x in actions.values()),
            'file_error_count': sum(r['status'] != 'BYTES_VERIFIED_AT_READ' for r in results.values()),
            'snapshot_consistency': 'POINT_IN_TIME_READS_NOT_A_LOCK_OR_LEASE',
            'adapter_invocations': 0, **FALSE_FLAGS}


def _nearest_existing_path(path: Path) -> Path | None:
    """Resolve the nearest existing path so aliases/symlinks share filesystem identity."""
    current = path
    while not os.path.lexists(current):
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return Path(os.path.realpath(current))


def _output_is_within_root(root: Path, output: Path) -> bool:
    """Check lexical containment, then physical directory ancestry without case-folding."""
    try:
        if os.path.commonpath((str(root), str(output))) == str(root):
            return True
    except ValueError:
        pass
    if not os.path.exists(root):
        return False
    current = _nearest_existing_path(output)
    while current is not None:
        try:
            if os.path.samefile(root, current):
                return True
        except OSError:
            pass
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return False


def validate_output_path(path: str | Path, plan_path: str | Path, allowed_roots: Iterable[str],
                         *, expected_sha256: str) -> Path:
    """Reject reports inside any named or protected source root before creating a file."""
    allowed_roots = tuple(allowed_roots)
    request_path = _absolute(str(plan_path))
    output = _absolute(str(path)); raw = read_absolute_file(request_path)
    if not valid_sha(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('REQUEST_IDENTITY_MISMATCH')
    plan = _json(raw)
    _validate(plan, allowed_roots)
    protected = [*allowed_roots, *plan['roots'].values(), *plan['protected_roots']]
    for root in map(_absolute, map(str, protected)):
        if _output_is_within_root(root, output):
            raise ValueError('OUTPUT_IN_PROTECTED_ROOT')
    if output == request_path:
        raise ValueError('OUTPUT_IS_REQUEST')
    if os.path.lexists(output) and os.path.lexists(request_path):
        try:
            if os.path.samefile(output, request_path):
                raise ValueError('OUTPUT_IS_REQUEST')
        except OSError:
            pass
    return output


def simulation_contract(scenario_id: str) -> dict[str, Any]:
    """Describe obligations via the accepted pure dry-run; no synthetic executor."""
    from .cutover_controller import execute_dry_run
    base = execute_dry_run(cutover_id=scenario_id, payload={})
    return {**base, 'schema': 'v4.owner_binding.simulation_contract.v1',
            'status': 'CONTRACT_DESCRIPTION_ONLY', 'action_requirements': ACTION_REQUIREMENTS,
            'requirements_sha256': canonical_sha256(ACTION_REQUIREMENTS),
            'fault_cases': [
                {'condition': 'queued writer', 'obligation': 'recheck persistent exact-key gate under commit lock'},
                {'condition': 'active child', 'obligation': 'do not claim drained; preserve fence'},
                {'condition': 'source drift after fence', 'obligation': 'reject switch without choosing a winner'},
                {'condition': 'readback fails', 'obligation': 'real CAS recovery requires owner implementation and evidence'},
                {'condition': 'rollback fails', 'obligation': 'keep gates closed and preserve all source/target bytes'},
            ], 'runtime_validation_status': 'NOT_PERFORMED', 'rollback_executed': False,
            'actual_rollback_verified': False, **FALSE_FLAGS}
