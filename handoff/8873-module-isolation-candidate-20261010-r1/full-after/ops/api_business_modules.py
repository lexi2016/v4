"""Business ownership policy for the existing single-gateway release chain.

This module has no publisher, lock, filesystem writer or service controller.
The approved authority comes from the current LaunchAgent, never from a delta.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = 'v4.api_business_module_owners.v1'
AUTHORITY_PATH_KEY = 'V35_API_MODULE_OWNERSHIP_PATH'
AUTHORITY_SHA_KEY = 'V35_API_MODULE_OWNERSHIP_SHA256'
IDENTITY_KEYS = (AUTHORITY_PATH_KEY, AUTHORITY_SHA_KEY)
_ID = re.compile(r'[a-z][a-z0-9_.-]{0,79}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SHARED_EXACT = frozenset({
    'apps/api/v35_api/app.py', 'apps/api/v35_api/run.py',
    'apps/api/v35_api/module_proxy.py', 'pyproject.toml', 'uv.lock',
})
_SHARED_PREFIXES = ('apps/web/', 'deployment/', 'config/', 'contracts/', 'infrastructure/')
_STATE_PARTS = frozenset({'data', 'state', 'runtime', 'node_modules', '.venv', 'venv', '__pycache__'})


def _duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('API_BUSINESS_JSON_DUPLICATE_KEY:' + str(key))
        result[key] = value
    return result


def _name(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(code)
    return value


def forbidden_source_path(path: str) -> bool:
    parts = Path(path).parts
    return (any(p in _STATE_PARTS or p.startswith('.') for p in parts)
            or path.endswith(('.plist', '.pem', '.key', '.pyc')))


def shared_source_path(path: str) -> bool:
    return path in _SHARED_EXACT or path.startswith(_SHARED_PREFIXES) or path.startswith('ops/')


def generation(identity: Mapping[str, Any]) -> int:
    manifest = identity.get('manifest', {})
    integration = manifest.get('api_integration', {}) if isinstance(manifest, Mapping) else {}
    module = integration.get('business_module', {}) if isinstance(integration, Mapping) else {}
    value = module.get('generation', 0) if isinstance(module, Mapping) else None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError('API_BUSINESS_GENERATION_INVALID')
    return value


def launch_bindings_digest(payload: Mapping[str, Any], *, _api) -> str:
    """Hash preserved launch/state/safety bindings without storing their values."""
    value = deepcopy(dict(payload))
    rewritten = {'V35_APP_ROOT', 'V35_RELEASE_ID', 'V35_RELEASE_MANIFEST_PATH',
                 'V35_RELEASE_MANIFEST_SHA256', 'PYTHONPATH'}
    arguments = value.get('ProgramArguments', [])
    value['ProgramArguments'] = [
        item.split('=', 1)[0] + '=<release>'
        if isinstance(item, str) and '=' in item and item.split('=', 1)[0] in rewritten else item
        for item in arguments
    ]
    if isinstance(value.get('EnvironmentVariables'), dict):
        value['EnvironmentVariables'] = {key: '<release>' if key in rewritten else content
                                         for key, content in value['EnvironmentVariables'].items()}
    if 'WorkingDirectory' in value:
        value['WorkingDirectory'] = '<release>'
    return _api.sha256_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def read_owner_contract(authority: Mapping[str, Any], *, _api) -> tuple[dict, str, str]:
    values = authority.get('identity_from_plist', {})
    path_value, expected = (values.get(k) for k in IDENTITY_KEYS)
    if not isinstance(path_value, str) or not isinstance(expected, str) or not _SHA.fullmatch(expected):
        raise ValueError('API_BUSINESS_OWNER_BINDING_REQUIRED')
    path = _api._exact_path(Path(path_value), kind='file', label='API_BUSINESS_OWNER_CONTRACT')
    if not Path(path_value).is_absolute() or path.is_relative_to(Path(authority['app_root'])):
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_MUST_BE_EXTERNAL')
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_TOO_LARGE')
    if _api.sha256_bytes(raw) != expected:
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_SHA_MISMATCH')
    try:
        contract = json.loads(raw.decode('utf-8'), object_pairs_hook=_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_JSON_INVALID') from error
    if not isinstance(contract, dict) or contract.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_SCHEMA_INVALID')
    if contract.get('status') != 'APPROVED' or not isinstance(contract.get('approval_id'), str) or not contract['approval_id'].strip():
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_NOT_APPROVED')
    external = contract.get('protected_external_roots')
    if not isinstance(external, list) or any(not isinstance(path, str) for path in external):
        raise ValueError('API_BUSINESS_EXTERNAL_BOUNDARIES_REQUIRED')
    if len(external) != len(set(external)):
        raise ValueError('API_BUSINESS_EXTERNAL_BOUNDARY_DUPLICATE')
    for path_value in external:
        if not Path(path_value).is_absolute():
            raise ValueError('API_BUSINESS_EXTERNAL_BOUNDARY_MUST_BE_ABSOLUTE')
        _api._exact_path(Path(path_value), kind='directory', label='API_BUSINESS_EXTERNAL_BOUNDARY')
    modules = contract.get('modules')
    shared = contract.get('shared_paths')
    if not isinstance(modules, list) or not modules or not isinstance(shared, list):
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_ENTRIES_REQUIRED')
    module_ids, owners, paths, routes = set(), set(), {}, set()
    for module in modules:
        if not isinstance(module, dict):
            raise ValueError('API_BUSINESS_MODULE_OWNER_INVALID')
        module_id = _name(module.get('module_id'), 'API_BUSINESS_MODULE_ID_INVALID')
        owner = _name(module.get('source_owner'), 'API_BUSINESS_SOURCE_OWNER_INVALID')
        if module_id in module_ids or owner in owners:
            raise ValueError('API_BUSINESS_MODULE_OWNER_DUPLICATE')
        module_ids.add(module_id); owners.add(owner)
        if module.get('state_compatibility') != 'UNCHANGED':
            raise ValueError('API_BUSINESS_STATE_COMPATIBILITY_UNCONFIRMED')
        owned = module.get('paths')
        if not isinstance(owned, list) or not owned:
            raise ValueError('API_BUSINESS_MODULE_PATHS_REQUIRED')
        for relative in owned:
            relative = _api._normalise_relative(relative)
            if any(c in relative for c in '*?[') or forbidden_source_path(relative):
                raise ValueError('API_BUSINESS_SOURCE_PATH_FORBIDDEN:' + relative)
            if relative in paths:
                raise ValueError('API_BUSINESS_PATH_OWNER_DUPLICATE:' + relative)
            paths[relative] = module_id
        module_routes = module.get('routes')
        dependencies = module.get('depends_on')
        if not isinstance(module_routes, list) or not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise ValueError('API_BUSINESS_ROUTE_OR_DEPENDENCY_INVALID')
        for route in module_routes:
            if (not isinstance(route, dict) or route.get('method') not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}
                    or not isinstance(route.get('path'), str) or not route['path'].startswith('/')):
                raise ValueError('API_BUSINESS_ROUTE_INVALID')
            key = (route['method'], route['path'])
            if key in routes:
                raise ValueError('API_BUSINESS_ROUTE_OWNER_DUPLICATE')
            routes.add(key)
    for module in modules:
        dependencies = module['depends_on']
        if (len(dependencies) != len(set(dependencies)) or module['module_id'] in dependencies
                or set(dependencies) - module_ids):
            raise ValueError('API_BUSINESS_DEPENDENCY_INVALID')
    remaining = {module['module_id']: len(module['depends_on']) for module in modules}
    dependents = {module_id: [] for module_id in module_ids}
    for module in modules:
        for dependency in module['depends_on']:
            dependents[dependency].append(module['module_id'])
    ready = [module_id for module_id, count in remaining.items() if count == 0]
    visited = 0
    while ready:
        module_id = ready.pop()
        visited += 1
        for dependent in dependents[module_id]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    if visited != len(modules):
        raise ValueError('API_BUSINESS_DEPENDENCY_CYCLE')
    for entry in shared:
        if not isinstance(entry, dict):
            raise ValueError('API_BUSINESS_SHARED_OWNER_INVALID')
        relative = _api._normalise_relative(entry.get('path'))
        if any(c in relative for c in '*?[') or forbidden_source_path(relative):
            raise ValueError('API_BUSINESS_SOURCE_PATH_FORBIDDEN:' + relative)
        _name(entry.get('source_owner'), 'API_BUSINESS_SHARED_OWNER_INVALID')
        if relative in paths:
            raise ValueError('API_BUSINESS_PATH_OWNER_DUPLICATE:' + relative)
        paths[relative] = None
    for relative in paths:
        if any(parent.as_posix() in paths for parent in Path(relative).parents):
            raise ValueError('API_BUSINESS_PATH_OWNER_OVERLAP:' + relative)
    return contract, expected, str(path)


def validate_business_module(*, receipt: Mapping[str, Any], base_identity: Mapping[str, Any],
                             authority_identity: Mapping[str, Any], required: bool, _api) -> dict | None:
    module = receipt.get('business_module')
    values = authority_identity.get('identity_from_plist', {})
    bound = any(key in values for key in IDENTITY_KEYS)
    if module is None and not required and not bound:
        return None  # Legacy inactive role fixtures; native gateway publication requires this policy.
    if not isinstance(module, dict):
        raise ValueError('API_BUSINESS_MODULE_RECEIPT_REQUIRED')
    contract, expected, contract_path = read_owner_contract(authority_identity, _api=_api)
    if module.get('owner_contract_sha256') != expected:
        raise ValueError('API_BUSINESS_OWNER_CONTRACT_SHA_MISMATCH')
    module_id = module.get('module_id')
    owner = next((entry for entry in contract['modules'] if entry['module_id'] == module_id), None)
    if owner is None:
        raise ValueError('API_BUSINESS_MODULE_UNKNOWN')
    base_generation = base_identity.get('generation', 0)
    if type(module.get('base_generation')) is not int or module['base_generation'] != base_generation:
        raise ValueError('API_BUSINESS_STALE_GENERATION')
    if module.get('operation') not in {'forward', 'rollback'}:
        raise ValueError('API_BUSINESS_OPERATION_INVALID')
    if module['operation'] == 'forward' and 'rollback_of' in module:
        raise ValueError('API_BUSINESS_ROLLBACK_BINDING_INVALID')
    shared = {entry['path'] for entry in contract['shared_paths']}
    owners = {path: entry['module_id'] for entry in contract['modules'] for path in entry['paths']}
    for entry in receipt['entries']:
        path = entry['path']
        if forbidden_source_path(path):
            raise ValueError('API_BUSINESS_SOURCE_PATH_FORBIDDEN:' + path)
        if shared_source_path(path) or path in shared:
            raise ValueError('API_BUSINESS_SHARED_SEAM_REQUIRES_JOINT_INTEGRATION:' + path)
        if path not in owners:
            raise ValueError('API_BUSINESS_PATH_OWNER_UNKNOWN:' + path)
        if owners[path] != module_id:
            raise ValueError('API_BUSINESS_PATH_OWNER_CONFLICT:' + path)
    for entry in base_identity.get('inventory', []):
        if entry.get('kind') != 'file' or forbidden_source_path(entry['path']):
            raise ValueError('API_BUSINESS_ACTIVE_SOURCE_BOUNDARY_UNCONFIRMED:' + entry['path'])
    result = {
        'module_id': module_id, 'source_owner': owner['source_owner'],
        'owner_contract_path': contract_path, 'owner_contract_sha256': expected,
        'approval_id': contract['approval_id'], 'base_generation': base_generation,
        'generation': base_generation + 1, 'operation': module['operation'],
        'state_schema_changed': False, 'shared_paths_changed': False,
    }
    if module['operation'] == 'rollback':
        if not isinstance(module.get('rollback_of'), dict):
            raise ValueError('API_BUSINESS_ROLLBACK_BINDING_INVALID')
        result['rollback_of'] = dict(module['rollback_of'])
    return result
