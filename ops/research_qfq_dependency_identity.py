"""Read-only QFQ computation closure, shared by admission and migration.

Only the original owner and its statically resolved imports are inspected.
No producer is imported or executed, and market-data refs are never read here.
"""
from __future__ import annotations

import ast
import base64
import csv
from contextlib import contextmanager
from contextvars import ContextVar
import io
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import sysconfig

from ops.research_storage_retention import RetentionError, canonical, safe_path, stamp

SCHEMA = 'v4.qfq_computation_dependencies.v1'
REQUIRED = (
    'ops/research_panel_qfq.py', 'ops/research_panel_turnover.py',
    'ops/research_panel_factor_cache.py', 'ops/research_panel_adjustment_inputs.py',
    'ops/research_panel_tdx_adjustment_inputs.py', 'ops/research_panel_daily_source.py',
    'ops/research_panel_logical.py', 'ops/research_panel_delta.py',
    'contracts/a_share_generation_compatibility.json', 'contracts/a_share_daily_source_policy.json',
)
# Imports from these authorities use only the named pure functions. Their full
# bytes and top-level imports remain bound, while unrelated CLI bodies do not run.
FRONTIERS = {
    'ops/research_storage_retention.py': {'RetentionError', 'canonical', 'safe_path', 'stamp'},
    'ops/a_share_daily_sync.py': {'valid_hq_bar', 'day_int'},
    'ops/macos_research_panel_daily.py': {'_a_day_files'},
    'ops/macos_research_panel_daily_common.py': {'_a_day_files'},
    'ops/macos_research_panel_daily_collectors.py': set(),
    'ops/macos_research_panel_daily_authority.py': set(),
    'ops/macos_research_panel_daily_pack.py': set(),
    'ops/macos_research_panel_daily_gate.py': set(),
}
DYNAMIC = {
    'ops/research_panel_qfq.py': {
        "importlib.util.spec_from_file_location(name, path)",
        'spec.loader.exec_module(module)',
        "_load(formula_path, FORMULA_SHA, 'qfq_original_canonical_formula')",
        "_load(driver_path, DRIVER_SHA, 'qfq_original_daily_driver')",
    },
    'ops/research_panel_tdx_adjustment_inputs.py': {
        "importlib.util.spec_from_file_location('qfq_official_gbbq_parser', config['parser']['path'])",
        'spec.loader.exec_module(module)',
    },
    'ops/vendor/data_layer_daily_formula_increment_update_v1.py': {
        "importlib.util.spec_from_file_location('v192_canonical_formula_authority', CANONICAL_FORMULA_PATH)",
        'spec.loader.exec_module(module)',
    },
    'ops/_a_share_daily_sync_parts/official_daily_package.py': {
        'importlib.util.spec_from_file_location(module_name, adapter_path)',
        "exec(compile(adapter_raw, str(adapter_path), 'exec'), module.__dict__)",
    },
}
RUNTIME_PACKAGES = {'numpy', 'pandas', 'pyarrow', 'psutil', 'pytdx', 'futu', 'packaging'}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
_PACKAGE_HASHES = {}
_SYNC_SUMMARIES = {}
_ACTIVE_CLAIM = ContextVar('qfq_computation_claim', default=None)


def _read(path):
    path = safe_path(path)
    before = stamp(path)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise RetentionError('QFQ_DEPENDENCY_SOURCE_BUDGET')
    raw = path.read_bytes()
    if stamp(path) != before:
        raise RetentionError('QFQ_DEPENDENCY_CHANGED_DURING_READ')
    return path, raw, before


def _selected_nodes(tree, selected):
    definitions = {n.name:n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    nodes = [n for n in tree.body if n not in definitions.values()]
    if selected is None:
        return list(tree.body)
    pending = list(selected)
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        node = definitions[name]
        nodes.append(node)
        pending.extend(n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id in definitions)
    return nodes


def _imports(node, relative):
    if isinstance(node, ast.Import):
        return [(alias.name, None) for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    module = node.module or ''
    if node.level:
        package = list(Path(relative).with_suffix('').parts[:-node.level])
        module = '.'.join(package + ([module] if module else []))
    if any(a.name == '*' for a in node.names) and module.split('.')[0] not in sys.stdlib_module_names:
        raise RetentionError('QFQ_DEPENDENCY_WILDCARD_IMPORT_UNREVIEWED')
    return [(module, {a.name for a in node.names})]


def _refs(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            if not isinstance(value.get('path'), str) or not re.fullmatch('[0-9a-f]{64}', str(value.get('sha256', ''))):
                raise RetentionError('QFQ_DEPENDENCY_REFERENCE_SHA_REQUIRED')
            yield value
        for item in value.values():
            yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def _named_refs(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and isinstance(item, dict) and 'path' in item:
                yield item
            yield from _named_refs(item, names)
    elif isinstance(value, list):
        for item in value:
            yield from _named_refs(item, names)


def _is_executable_ref(value, ref):
    return any(item is ref for item in _named_refs(value, {'parser', 'calendar_adapter'}))


def _artifact_sha(path):
    path = safe_path(path)
    observed = stamp(path)
    cached = _PACKAGE_HASHES.get(str(path))
    if cached and cached[0] == observed:
        return cached[1]
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    if stamp(path) != observed:
        raise RetentionError('QFQ_DEPENDENCY_RUNTIME_CHANGED_DURING_READ')
    value = digest.hexdigest()
    _PACKAGE_HASHES[str(path)] = (observed, value)
    return value


def environment_identity(packages):
    executable = Path(sys.executable).resolve()
    execution_root = Path(__file__).resolve().parents[1]
    search_path = []
    for item in sys.path:
        entry = Path(item or os.getcwd()).absolute()
        relative = entry.relative_to(execution_root) if entry.is_relative_to(execution_root) else None
        search_path.append(('$APP_ROOT' + ('/' + relative.as_posix() if relative != Path('.') else '')) if relative is not None else str(entry))
    result = dict(python=sys.version, executable=str(executable),
                  executable_sha256=_artifact_sha(executable),
                  cache_tag=sys.implementation.cache_tag, prefix=sys.prefix,
                  flags={name:getattr(sys.flags, name) for name in ('debug', 'inspect', 'optimize', 'dont_write_bytecode', 'no_user_site', 'no_site', 'ignore_environment', 'isolated', 'safe_path', 'utf8_mode')},
                  search_path=search_path,
                  computation_environment={key:os.environ.get(key) for key in (
                      'V4_A_QFQ_COMPUTE_BACKEND', 'V4_A_QFQ_SOURCE_REPAIR_DATE',
                      'V4_A_QFQ_SOURCE_REPAIR_INPUT', 'V4_A_QFQ_SOURCE_REPAIR_INPUT_SHA256',
                      'V4_QFQ_CONVENTION_ACCEPTANCE_PATH', 'V4_QFQ_CONVENTION_ACCEPTANCE_SHA256',
                      'RESEARCH_PANEL_QFQ_REFRESH_FACTORS')}, packages={})
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    runtime_files = []
    for path in sorted(stdlib.rglob('*')):
        if 'site-packages' in path.relative_to(stdlib).parts or path.suffix not in {'.py', '.pyc', '.so', '.dylib'} or not path.is_file():
            continue
        runtime_files.append((path.relative_to(stdlib).as_posix(), _artifact_sha(path)))
    if not runtime_files:
        raise RetentionError('QFQ_DEPENDENCY_STDLIB_ARTIFACTS_UNBOUND')
    result['stdlib'] = dict(root=str(stdlib), artifact_count=len(runtime_files),
                            actual_artifacts_sha256=canonical(runtime_files))
    if not packages:
        return result
    from packaging.requirements import Requirement
    mapping = importlib.metadata.packages_distributions()
    verified_paths = set()
    pending = []
    for package in sorted(packages):
        names = mapping.get(package) or []
        if not names:
            if package == 'psutil':
                result['packages'][package] = dict(status='ABSENT_OPTIONAL_RESOURCE_SIZING')
                continue
            raise RetentionError('QFQ_DEPENDENCY_RUNTIME_PACKAGE_UNBOUND:' + package)
        pending.extend(names)
    seen = set()
    while pending:
        name = pending.pop()
        dist = importlib.metadata.distribution(name)
        name = dist.metadata['Name']
        if name in seen:
            continue
        seen.add(name)
        metadata, record = dist.read_text('METADATA'), dist.read_text('RECORD')
        if metadata is None or record is None:
            raise RetentionError('QFQ_DEPENDENCY_RUNTIME_RECORD_UNBOUND:' + name)
        actual = []
        ignored_cli = []
        import_root = Path(dist.locate_file('')).resolve()
        for relative, expected, size in csv.reader(io.StringIO(record)):
            path = Path(dist.locate_file(relative)).resolve()
            if not path.is_relative_to(import_root):
                ignored_cli.append(relative)
                continue
            # RECORD itself is bound separately. Missing generated bytecode is
            # allowed, but present bytecode is bound by its actual bytes.
            if not expected and path.suffix != '.pyc':
                continue
            if not path.exists():
                if path.suffix == '.pyc' and not expected:
                    actual.append((relative, 'ABSENT_GENERATED_BYTECODE'))
                    continue
                raise RetentionError('QFQ_DEPENDENCY_RUNTIME_ARTIFACT_MISSING:' + name)
            digest = _artifact_sha(path)
            verified_paths.add(str(path))
            if expected:
                algorithm, encoded = expected.split('=', 1)
                if algorithm != 'sha256' or base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip('=') != encoded:
                    raise RetentionError('QFQ_DEPENDENCY_RUNTIME_ARTIFACT_CONFLICT:' + name + ':' + relative)
            actual.append((relative, digest))
        result['packages'][name] = dict(version=dist.version,
            metadata_sha256=hashlib.sha256(metadata.encode()).hexdigest(),
            record_sha256=hashlib.sha256(record.encode()).hexdigest(),
            artifact_count=len(actual), verified_artifacts_sha256=canonical(sorted(actual)),
            excluded_installer_cli=sorted(ignored_cli))
        for dependency in dist.requires or []:
            required = Requirement(dependency)
            if required.marker is None or required.marker.evaluate({'extra':''}):
                pending.append(required.name)
    from importlib.util import find_spec
    for package in sorted(packages - {'psutil'}):
        loaded = sys.modules.get(package)
        origin = getattr(loaded, '__file__', None) if loaded is not None else None
        if origin is None:
            spec = find_spec(package)
            origin = spec.origin if spec is not None else None
        if not origin or str(Path(origin).resolve()) not in verified_paths:
            raise RetentionError('QFQ_DEPENDENCY_RUNTIME_IMPORT_SHADOWED:' + package)
    return result


def computation_dependencies(module, kwargs, *, snapshot=None, runtime_root=None):
    """Return a root-neutral, closed manifest or fail before owner execution.

    External paths retain their exact identity. Local paths are lexical,
    repository-relative and must resolve without a symlink or escape.
    """
    owner = safe_path(module.__file__)
    if owner.name != 'research_panel_qfq.py' or owner.parent.name != 'ops':
        raise RetentionError('QFQ_DEPENDENCY_OWNER_ROLE_REQUIRED')
    root = owner.parent.parent
    records = {}
    paths = {}
    observations = {}
    scanned = {}
    queue = [(relative, None, 'mandatory owner closure') for relative in REQUIRED]
    queue += [(relative, None, 'package initialization') for relative in ('ops/__init__.py', 'contracts/__init__.py') if (root / relative).is_file()]
    queue += [(str(safe_path(kwargs[key])), None, key) for key in ('driver_path', 'formula_path', 'contract_csv')]
    packages = set()
    external_code_refs = {}
    dynamic_edges = []
    if runtime_root is not None:
        for name in ('qfq_tdx_official_source.json', 'qfq_factor_cache_binding.json'):
            source = safe_path(runtime_root) / name
            if source.is_file():
                queue.append((str(source), None, 'runtime input selection configuration'))
    if snapshot is not None:
        for ref in _refs(snapshot):
            if Path(ref['path']).suffix == '.py':
                previous = external_code_refs.setdefault(ref['path'], ref['sha256'])
                if previous != ref['sha256']:
                    raise RetentionError('QFQ_DEPENDENCY_REFERENCE_CONFLICT')
                queue.append((ref['path'], None if _is_executable_ref(snapshot, ref) else False, 'frozen snapshot source reference'))
    while queue:
        name, requested, used_by = queue.pop()
        candidate = Path(name)
        path = candidate if candidate.is_absolute() else root / candidate
        path = safe_path(path)
        if not candidate.is_absolute() and (candidate.as_posix() != name or '..' in candidate.parts or not path.is_relative_to(root)):
            raise RetentionError('QFQ_DEPENDENCY_PATH_ESCAPE')
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else None
        role = 'repository:' + relative if relative else 'external:' + str(path)
        if relative is not None:
            for parent in Path(relative).parents:
                initializer = parent / '__init__.py'
                if parent != Path('.') and (root / initializer).is_file() and initializer.as_posix() != relative:
                    init_role = 'repository:' + initializer.as_posix()
                    if init_role not in records:
                        queue.append((initializer.as_posix(), None, 'parent package initialization'))
        prior = records.get(role)
        used = sorted(set(prior['used_by'] if prior else []) | {used_by})
        if prior:
            prior['used_by'] = used
            if requested is False:
                continue
            if role in scanned and (scanned[role] is None or requested is not None and set(requested).issubset(scanned[role])):
                continue
        if requested is not False:
            old_selection = scanned.get(role, set())
            scanned[role] = None if requested is None or old_selection is None else old_selection | set(requested)
        path, raw, observed = _read(path)
        digest = hashlib.sha256(raw).hexdigest()
        if str(path) in external_code_refs and digest != external_code_refs[str(path)]:
            raise RetentionError('QFQ_DEPENDENCY_FROZEN_CODE_SHA_CONFLICT')
        if str(path) in paths and paths[str(path)] != role:
            raise RetentionError('QFQ_DEPENDENCY_PATH_CONFLICT')
        paths[str(path)] = role
        observations[str(path)] = observed
        records[role] = dict(role=role, path=relative or str(path), sha256=digest,
            affects_output=True, used_by=used, external=relative is None)
        if requested is False:
            continue
        if path.suffix == '.json':
            if path.name == 'qfq_factor_cache_binding.json':
                continue
            value = json.loads(raw)
            # Contract references bind executable calendar adapters. Other
            # source refs stay SHA-bound in the exact contract/snapshot bytes.
            for ref in _refs(value):
                if Path(ref['path']).suffix == '.py':
                    prior = external_code_refs.setdefault(ref['path'], ref['sha256'])
                    if prior != ref['sha256']:
                        raise RetentionError('QFQ_DEPENDENCY_REFERENCE_CONFLICT')
                    queue.append((ref['path'], None if _is_executable_ref(value, ref) else False, role))
            continue
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(raw, filename=str(path))
        except (SyntaxError, ValueError) as exc:
            raise RetentionError('QFQ_DEPENDENCY_SOURCE_UNPARSEABLE:' + role) from exc
        selected = FRONTIERS.get(relative)
        if relative and relative.startswith('ops/_'):
            selected = requested
        selected_nodes = _selected_nodes(tree, selected)
        aliases = {}
        for top in selected_nodes:
            for node in ast.walk(top):
                if isinstance(node, ast.Import):
                    aliases.update({a.asname or a.name.split('.')[0]:a.name for a in node.names})
                elif isinstance(node, ast.ImportFrom) and node.module in {'importlib', 'importlib.util', 'builtins'}:
                    aliases.update({a.asname or a.name:node.module + '.' + a.name for a in node.names})
        for top in selected_nodes:
            parents = {id(child):parent for parent in ast.walk(top) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(top):
                reference = ast.unparse(node) if isinstance(node, (ast.Attribute, ast.Name)) else ''
                first_ref, _, rest_ref = reference.partition('.')
                resolved_ref = aliases.get(first_ref, first_ref) + ('.' + rest_ref if rest_ref else '')
                loader_ref = resolved_ref in {'importlib.import_module', 'importlib.util.spec_from_file_location', 'builtins.__import__', 'builtins.exec', 'builtins.eval', '__import__', 'exec', 'eval'}
                parent = parents.get(id(node))
                if loader_ref and not (isinstance(parent, ast.Call) and parent.func is node):
                    raise RetentionError('QFQ_DEPENDENCY_DYNAMIC_ALIAS_UNREVIEWED:' + role)
                if isinstance(node, ast.Call):
                    expression = ast.unparse(node)
                    function = ast.unparse(node.func)
                    first, _, rest = function.partition('.')
                    resolved = aliases.get(first, first) + ('.' + rest if rest else '')
                    alias_dynamic = resolved in {'importlib.import_module', 'importlib.util.spec_from_file_location', 'builtins.__import__', 'builtins.exec', 'builtins.eval'}
                    indirect_dynamic = (isinstance(node.func, ast.Name) and node.func.id == 'getattr' and node.args
                        and ast.unparse(node.args[0]).split('.')[0] in {name for name,value in aliases.items() if value.startswith(('importlib','builtins'))})
                    dynamic = alias_dynamic or indirect_dynamic or (relative == 'ops/research_panel_qfq.py' and isinstance(node.func, ast.Name) and node.func.id == '_load') or (isinstance(node.func, ast.Attribute) and node.func.attr in {'spec_from_file_location', 'import_module', 'exec_module'}
                        or isinstance(node.func, ast.Name) and node.func.id in {'exec', 'eval', '__import__'})
                    if dynamic:
                        stdlib_import = (isinstance(node.func, ast.Name) and node.func.id == '__import__'
                            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in sys.stdlib_module_names)
                        if not stdlib_import and expression not in DYNAMIC.get(relative, set()):
                            raise RetentionError('QFQ_DEPENDENCY_DYNAMIC_UNREVIEWED:' + role + ':' + expression)
                        dynamic_edges.append(dict(source=role, expression=expression))
                for imported, names in _imports(node, relative or path.name):
                    first = imported.split('.')[0]
                    if first in {'ops', 'contracts', 'infrastructure'}:
                        base = imported.replace('.', '/')
                        destinations = [(base + '.py', names)]
                        if names:
                            destinations += [(base + '/' + item + '.py', None) for item in names]
                        found = False
                        for destination, selected_names in destinations:
                            if (root / destination).is_file():
                                found = True
                                queue.append((destination, selected_names, role))
                        if not found:
                            package_init = root / base / '__init__.py'
                            if not package_init.is_file():
                                raise RetentionError('QFQ_DEPENDENCY_LOCAL_IMPORT_MISSING:' + imported)
                            queue.append((base + '/__init__.py', None, role))
                    elif first in RUNTIME_PACKAGES:
                        packages.add(first)
                    elif first not in sys.stdlib_module_names and first != '__future__':
                        raise RetentionError('QFQ_DEPENDENCY_EXTERNAL_IMPORT_UNREVIEWED:' + imported)
    if any(edge['source'] == 'repository:ops/_a_share_daily_sync_parts/official_daily_package.py' for edge in dynamic_edges):
        policy = json.loads((root / 'contracts/a_share_daily_source_policy.json').read_bytes())
        calendar = policy.get('calendar_adapter')
        if (not isinstance(calendar, dict) or calendar.get('path') not in paths
                or not re.fullmatch('[0-9a-f]{64}', str(calendar.get('sha256', '')))):
            raise RetentionError('QFQ_DEPENDENCY_DYNAMIC_TARGET_UNBOUND:calendar_adapter')
    if any(edge['source'] == 'repository:ops/research_panel_tdx_adjustment_inputs.py' for edge in dynamic_edges):
        parser_refs = [ref for source in (snapshot or {},) for ref in _named_refs(source, {'parser'})]
        if runtime_root is not None:
            config = Path(runtime_root) / 'qfq_tdx_official_source.json'
            if config.is_file():
                parser_refs.extend(_named_refs(json.loads(config.read_bytes()), {'parser'}))
        if not parser_refs or any(ref['path'] not in paths for ref in parser_refs):
            raise RetentionError('QFQ_DEPENDENCY_DYNAMIC_TARGET_UNBOUND:official_parser')
    # No file may change after it has been consumed during this collection.
    for name, expected in observations.items():
        if stamp(safe_path(name)) != expected:
            raise RetentionError('QFQ_DEPENDENCY_CHANGED_DURING_READ')
    environment = environment_identity(packages)
    for name, expected in observations.items():
        if stamp(safe_path(name)) != expected:
            raise RetentionError('QFQ_DEPENDENCY_CHANGED_DURING_READ')
    result = dict(schema=SCHEMA, dependencies=sorted(records.values(), key=lambda r:r['role']),
        dynamic_edges=[dict(source=source, expression=expression) for source,expression in sorted({(r['source'],r['expression']) for r in dynamic_edges})],
        environment=environment)
    if snapshot is not None:
        result['frozen_input_sha256'] = canonical(snapshot)
    validate_manifest(result)
    return result


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA:
        raise RetentionError('QFQ_DEPENDENCY_MANIFEST_SCHEMA')
    rows = manifest.get('dependencies')
    if not isinstance(rows, list) or not 10 <= len(rows) <= 256:
        raise RetentionError('QFQ_DEPENDENCY_MANIFEST_MEMBERSHIP')
    roles = set()
    paths = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('role'), str)
                or row['role'] in roles or row.get('path') in paths
                or not re.fullmatch('[0-9a-f]{64}', str(row.get('sha256', '')))):
            raise RetentionError('QFQ_DEPENDENCY_MANIFEST_CONFLICT')
        path = Path(row['path'])
        if ('..' in path.parts or row.get('external') and (not path.is_absolute() or row['role'] != 'external:' + path.as_posix())
                or not row.get('external') and (path.is_absolute() or row['role'] != 'repository:' + path.as_posix())):
            raise RetentionError('QFQ_DEPENDENCY_PATH_ESCAPE')
        roles.add(row['role']); paths.add(row['path'])
    if not {'repository:' + path for path in REQUIRED}.issubset(roles):
        raise RetentionError('QFQ_DEPENDENCY_MANIFEST_MEMBERSHIP')
    return manifest


def validate_turnover_evidence(module, kwargs, target, evidence):
    """Validate the exact existing load_daily result without calculating shares."""
    if not isinstance(evidence, dict) or evidence.get('schema') != 'v4.qfq_turnover_evidence.v1':
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_EVIDENCE_REQUIRED')
    helper = safe_path(module.__file__).with_name('research_panel_turnover.py')
    _, raw, _ = _read(helper)
    policies = [ast.literal_eval(n.value) for n in ast.parse(raw).body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'POLICY' for t in n.targets)]
    if len(policies) != 1 or evidence.get('target') != target or evidence.get('policy') != policies[0]:
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_POLICY_CONFLICT')
    sync = safe_path(kwargs['tdx_root']).parent / 'receipts/a_sync_authority' / str(target) / 'summary.json'
    if evidence.get('sync_path') != str(sync):
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_SCOPE_CONFLICT')
    binding, failure = evidence.get('binding'), evidence.get('failure')
    if not isinstance(binding, dict):
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_BINDING_REQUIRED')
    if evidence.get('state') == 'MISSING':
        if sync.exists() or binding or failure != 'DAILY_SYNC_RECEIPT_MISSING':
            raise RetentionError('QFQ_DEPENDENCY_TURNOVER_ABSENCE_CHANGED')
    elif evidence.get('state') == 'BOUND':
        descriptor = binding.get('gbbq') or {}
        if (failure is not None or set(binding) != {'sync', 'package', 'input_ref', 'gbbq'}
                or binding['sync'].get('path') != str(sync)
                or not {'capture', 'raw', 'archive', 'parser', 'category_policy', 'derived_parquet', 'derived_receipt'}.issubset(descriptor)):
            raise RetentionError('QFQ_DEPENDENCY_TURNOVER_BINDING_REQUIRED')
        required_refs = [binding[key] for key in ('sync', 'package', 'input_ref')]
        required_refs.extend(descriptor[key] for key in ('capture', 'raw', 'archive', 'parser', 'category_policy', 'derived_parquet', 'derived_receipt'))
        for ref in required_refs:
            if (not isinstance(ref, dict) or not isinstance(ref.get('path'), str)
                    or not re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', '')))):
                raise RetentionError('QFQ_DEPENDENCY_TURNOVER_REFERENCE_REQUIRED')
            if _artifact_sha(safe_path(ref['path'])) != ref['sha256']:
                raise RetentionError('QFQ_DEPENDENCY_TURNOVER_SOURCE_CONFLICT')
    else:
        # Broad load_daily error strings have no complete immutable source
        # witness. They cannot establish cross-root continuation.
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_FAILURE_UNPROVEN')
    if evidence.get('state') == 'BOUND':
        _validate_turnover_calendar(module, binding, target)
    expected = canonical(dict(policy=policies[0], helper_sha256=hashlib.sha256(raw).hexdigest(),
                              target=target, binding=binding, failure=failure))
    if evidence.get('identity') != expected:
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_IDENTITY_CONFLICT')
    return evidence


@contextmanager
def computation_scope(claim):
    token = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(token)


def observe_generation(snapshot, dependencies):
    claim = _ACTIVE_CLAIM.get()
    if claim is not None:
        expected = getattr(claim, 'qfq_expected_dependencies', None)
        if expected is not None and dependencies != expected:
            raise RetentionError('QFQ_RESUME_COMPUTATION_DEPENDENCY_CHANGED')
        invocation = getattr(claim, 'qfq_invocation_dependencies', None)
        if invocation is not None:
            actual = {row['role']:(row['path'], row['sha256']) for row in dependencies['dependencies']}
            if (invocation['environment'] != dependencies['environment']
                    or any(actual.get(row['role']) != (row['path'], row['sha256']) for row in invocation['dependencies'])):
                raise RetentionError('QFQ_COMPUTATION_DEPENDENCY_CHANGED_BEFORE_GENERATION')
        claim.qfq_bound_snapshot = snapshot
        prior = getattr(claim, 'qfq_computation_dependencies', None)
        if prior is not None and prior != dependencies:
            raise RetentionError('QFQ_COMPUTATION_DEPENDENCY_CHANGED_DURING_BUILD')
        claim.qfq_computation_dependencies = dependencies


def observe_turnover(module_file, data_root, tdx_root, target, value, policy):
    claim = _ACTIVE_CLAIM.get()
    if claim is None:
        return
    sync = Path(tdx_root).parent / 'receipts/a_sync_authority' / str(target) / 'summary.json'
    evidence = dict(schema='v4.qfq_turnover_evidence.v1', target=target,
        sync_path=str(sync), policy=policy,
        state='MISSING' if value.failure == 'DAILY_SYNC_RECEIPT_MISSING' else 'BOUND' if value.failure is None else 'UNPROVEN',
        binding=value.binding, failure=value.failure, identity=value.identity)
    preload = getattr(claim, 'qfq_turnover_preload', None)
    if preload is not None and (value.failure is None and any(value.binding.get(key) != ref for key,ref in preload.items())):
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_CHANGED_DURING_LOAD')
    expected = getattr(claim, 'qfq_resume_turnover', None)
    if expected is not None or evidence['state'] in {'BOUND', 'MISSING'}:
        from types import SimpleNamespace
        validate_turnover_evidence(SimpleNamespace(__file__=module_file),
            claim.qfq_dependency_context['kwargs'], target, evidence)
        if expected is not None and evidence != expected:
            raise RetentionError('QFQ_RESUME_TURNOVER_CHANGED')
    claim.qfq_turnover_evidence = evidence


def _bound_control(ref, *, limit=8 * 1024 * 1024):
    if (not isinstance(ref, dict) or not isinstance(ref.get('path'), str)
            or not re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', '')))):
        raise RetentionError('QFQ_DEPENDENCY_TYPED_CONTROL_REF_REQUIRED')
    path = safe_path(ref['path'])
    before = stamp(path)
    if before['size'] > limit:
        raise RetentionError('QFQ_DEPENDENCY_TYPED_CONTROL_BUDGET')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256'] or stamp(path) != before:
        raise RetentionError('QFQ_DEPENDENCY_TYPED_CONTROL_CHANGED')
    return json.loads(raw)


def _validate_turnover_calendar(module, binding, target):
    policy_path = safe_path(module.__file__).parent.parent / 'contracts/a_share_daily_source_policy.json'
    policy = json.loads(_read(policy_path)[1])
    expected = {name:policy.get(name) for name in ('calendar', 'calendar_adapter')}
    if not all(isinstance(ref, dict) and isinstance(ref.get('path'), str)
               and re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', ''))) for ref in expected.values()):
        raise RetentionError('QFQ_DEPENDENCY_CALENDAR_POLICY_UNBOUND')
    for ref in expected.values():
        if _artifact_sha(safe_path(ref['path'])) != ref['sha256']:
            raise RetentionError('QFQ_DEPENDENCY_CALENDAR_SOURCE_CONFLICT')
    sync = _sync_summary(binding['sync'])
    source = sync.get('official_daily_source') or {}
    actual_input = source.get('input_ref')
    if (not _same_sync_target(sync.get('target_date'), target) or source.get('source_kind') != 'TDX_OFFICIAL_G4DAY'
            or not isinstance(actual_input, dict)
            or any(actual_input.get(name) != binding['input_ref'].get(name) for name in ('path', 'sha256'))
            or source.get('package') != binding['package']):
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_INPUT_DESCRIPTOR_CONFLICT')
    history = actual_input.get('history_inputs', [])
    if not isinstance(history, list) or len(history) > 32:
        raise RetentionError('QFQ_DEPENDENCY_CALENDAR_HISTORY_UNBOUND')
    previous = target + 1
    for index, ref in enumerate([binding['input_ref'], *history]):
        value = _bound_control(ref)
        date = value.get('target_date')
        if (type(date) is not int or not date < previous or index == 0 and date != target
                or 'target_date' in ref and ref['target_date'] != date
                or value.get('schema_version') != 'a_sync_official_daily_input.v1'
                or value.get('source_kind') != 'TDX_OFFICIAL_G4DAY'
                or any(value.get(name) != expected[name] for name in expected)):
            raise RetentionError('QFQ_DEPENDENCY_CALENDAR_ADAPTER_CONFLICT')
        previous = date


def validate_turnover_before_load(module_file, tdx_root, target):
    """Fence typed executable calendar inputs before the existing loader runs."""
    from types import SimpleNamespace
    sync_path = safe_path(tdx_root).parent / 'receipts/a_sync_authority' / str(target) / 'summary.json'
    if not sync_path.exists():
        return
    sync_ref = dict(path=str(sync_path), sha256=_artifact_sha(sync_path))
    sync = _sync_summary(sync_ref)
    source = sync.get('official_daily_source') or {}
    ref = source.get('input_ref')
    if not isinstance(ref, dict) or not isinstance(source.get('package'), dict):
        raise RetentionError('QFQ_DEPENDENCY_TURNOVER_INPUT_DESCRIPTOR_CONFLICT')
    binding = dict(sync=sync_ref, input_ref={key:ref.get(key) for key in ('path', 'sha256')}, package=source['package'])
    _validate_turnover_calendar(SimpleNamespace(__file__=module_file), binding, target)
    claim = _ACTIVE_CLAIM.get()
    if claim is not None:
        claim.qfq_turnover_preload = binding


def _same_sync_target(value, target):
    return ((type(value) is int and value == target)
            or (type(value) is str and re.fullmatch('[0-9]{8}', value) is not None and value == str(target)))


def _sync_summary(ref):
    path = safe_path(ref['path'])
    observed = stamp(path)
    prior = _SYNC_SUMMARIES.get(str(path))
    if prior and prior[:2] == (observed, ref['sha256']):
        return json.loads(prior[2])
    # The existing owner permits 192 MiB control files. Keep that accepted
    # summary scope while input/history descriptors retain the smaller bound.
    summary = _bound_control(ref, limit=192 * 1024 * 1024)
    projection = {key:summary.get(key) for key in ('target_date', 'official_daily_source')}
    if len(_SYNC_SUMMARIES) >= 16:
        _SYNC_SUMMARIES.pop(next(iter(_SYNC_SUMMARIES)))
    _SYNC_SUMMARIES[str(path)] = (observed, ref['sha256'], json.dumps(projection))
    return projection
