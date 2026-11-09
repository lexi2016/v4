"""Bounded inactive packet support for the 2026-11-09 release repair.

Runtime V4 files are patched in place in PRIVATE candidate copies. Canonical
V35 source is not overlaid wholesale onto the newer installed V4 runtime.
No producer, service control, or business-data write is performed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ops.api_release_integration import validate_api_manifest_shape


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_inventory(app: Path, base_entries: list[dict]) -> list[dict]:
    """Reuse the existing inventory, including its one sealed Python cache.

    The integration scanner reports generated 3.14 cache separately. Preserve
    already sealed cache entries rather than silently dropping their bytes.
    """
    from ops.api_release_integration import _inventory_tree_with_generated_cache
    entries, generated = _inventory_tree_with_generated_cache(app)
    regular_paths = {item['path'] for item in entries}
    pinned_cache = {item['path']: item for item in base_entries
                    if '/__pycache__/' in item['path'] and item['path'] not in regular_paths}
    observed = {item['path']: dict(item, kind='file') for item in generated}
    for relative, item in pinned_cache.items():
        if observed.get(relative) != item:
            raise ValueError('SEALED_CACHE_DRIFT:' + relative)
        entries.append(item)
    return sorted(entries, key=lambda item: item['path'])


def clone_release(app: Path, target: Path, manifest: dict) -> None:
    import shutil
    expected = manifest['application_inventory']
    from ops.api_release_integration import inventory_digest
    if (expected['entry_count'] != len(expected['entries'])
            or inventory_digest(expected['entries']) != expected['aggregate_sha256']
            or frozen_inventory(app, expected['entries']) != expected['entries']):
        raise ValueError('BASE_INVENTORY_DRIFT:' + str(app))
    shutil.copytree(app, target, symlinks=True)
    if frozen_inventory(target, expected['entries']) != expected['entries']:
        raise ValueError('COPY_INVENTORY_DRIFT')


def seal_manifest(base: dict, *, app: Path, release_id: str, role: str,
                  delta_paths: set[str], base_manifest: Path) -> dict:
    from copy import deepcopy
    from ops.api_release_integration import inventory_digest
    manifest = deepcopy(base)
    before = {item['path']: item for item in base['application_inventory']['entries']}
    entries = frozen_inventory(app, base['application_inventory']['entries'])
    after = {item['path']: item for item in entries}
    if set(before) - set(after):
        raise ValueError('RELEASE_FILES_REMOVED')
    changes = [path for path in set(before) | set(after) if before.get(path) != after.get(path)]
    if set(changes) != delta_paths:
        raise ValueError('EXPLICIT_DELTA_MISMATCH:' + repr(sorted(set(changes) ^ delta_paths)))
    manifest.update(release_id=release_id, app_root=str(app),
        application_inventory={'entries': entries, 'entry_count': len(entries),
                               'aggregate_sha256': inventory_digest(entries)})
    if role == 'api':
        validate_api_manifest_shape(manifest)
        manifest['candidate'].update(root=str(app.parent), app_root=str(app), release_id=release_id)
    else:
        manifest['candidate'] = deepcopy(base.get('candidate'))
        if isinstance(manifest['candidate'], dict):
            manifest['candidate'].update(root=str(app.parent), app_root=str(app), release_id=release_id)
        elif isinstance(manifest['candidate'], str):
            manifest['candidate'] = release_id
    manifest['app_files'] = [dict(path=item['path'], sha256=item['sha256'], size=item['size'])
                             for item in entries if item['kind'] == 'file']
    manifest['daily_materials_release_repair'] = {
        'base_manifest': {'path': str(base_manifest), 'sha256': sha(base_manifest)},
        'delta': [{'path': path, 'before': before.get(path), 'after': after.get(path)} for path in sorted(changes)],
        'non_delta_entries_preserved': len(before) - len(set(changes) & set(before)),
        'scope': 'SOURCE_DELTA_ONLY_NO_PRODUCER_REPLAY',
    }
    validate_packet_manifest(manifest, role=role)
    return manifest


def patch_dispatcher(source: str) -> str:
    old = '    if (payload.get("schema_version") != "v4.release_candidate.v1"\n'
    new = ('    if (not isinstance(payload, dict)\n'
           '            or not isinstance(payload.get("candidate"), dict)\n'
           '            or not isinstance(payload.get("application_inventory"), dict)\n'
           '            or payload.get("schema_version") != "v4.release_candidate.v1"\n')
    if source.count(old) != 1:
        raise ValueError("DISPATCHER_PATCH_PREIMAGE_MISMATCH")
    return source.replace(old, new, 1)


def patch_frontend_identity(source: str) -> str:
    old = "        manifest=json.loads(raw);candidate=manifest.get('candidate',{})\n"
    new = ("        manifest=json.loads(raw)\n"
           "        if not isinstance(manifest,dict):raise ValueError('API_MANIFEST_OBJECT_REQUIRED')\n"
           "        candidate=manifest.get('candidate')\n"
           "        if not isinstance(candidate,dict):raise ValueError('API_CANDIDATE_OBJECT_REQUIRED')\n")
    if source.count(old) != 1:
        raise ValueError("FRONTEND_IDENTITY_PATCH_PREIMAGE_MISMATCH")
    return source.replace(old, new, 1)


def patch_stage_owner_reader(source: str) -> str:
    """Keep exact pins; permit a declared same-release manifest filename.

    Existing singleton transitions and their special 20261102 witness stay
    intact. Five exact historical pins preserve the preceding Main owners
    across the observed 11/06 and this 11/09 daily-hook cutover.
    """
    edits = [
        ("                      required: tuple[str, ...]) -> dict:",
         "                      required: tuple[str, ...], manifest_path: str | None = None) -> dict:"),
        ("    raw = SafeRoot(app.parent).read_bytes('release-manifest.json', max_bytes=16 * 1024 * 1024)",
         "    locator = Path(manifest_path) if manifest_path is not None else app.parent / 'release-manifest.json'\n"
         "    if (not locator.is_absolute() or locator.parent != app.parent or '..' in locator.parts\n"
         "        or str(locator) != str(app.parent / locator.name) or not re.fullmatch(r'release-manifest(?:-[a-z0-9-]+)?\\.json', locator.name)):\n"
         "        raise PublicationError('RESEARCH_RELEASE_MANIFEST_PATH_INVALID')\n"
         "    raw = SafeRoot(app.parent).read_bytes(locator.name, max_bytes=16 * 1024 * 1024)"),
        ("set(binding) != {'app_root', 'release_id', 'manifest_sha256'}\n        or not isinstance(binding.get('release_id'), str)",
         "set(binding) not in ({'app_root', 'release_id', 'manifest_sha256'},\n"
         "                                 {'app_root', 'release_id', 'manifest_sha256', 'manifest_path'})\n"
         "        or not isinstance(binding.get('release_id'), str)"),
        ("    _release_manifest(owner, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES)",
         "    _release_manifest(owner, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES,\n"
         "                      manifest_path=binding.get('manifest_path'))"),
        ("set(binding) != {'app_root', 'release_id', 'manifest_sha256'}\n            or not isinstance(binding.get('release_id'), str)",
         "set(binding) not in ({'app_root', 'release_id', 'manifest_sha256'},\n"
         "                                     {'app_root', 'release_id', 'manifest_sha256', 'manifest_path'})\n"
         "            or not isinstance(binding.get('release_id'), str)"),
        ("        _release_manifest(previous, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES)",
         "        _release_manifest(previous, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES,\n"
         "                          manifest_path=binding.get('manifest_path'))"),
    ]
    for old, new in edits:
        if source.count(old) != 1:
            raise ValueError("STAGE_OWNER_PATCH_PREIMAGE_MISMATCH:" + old[:50])
        source = source.replace(old, new, 1)
    old = "not isinstance(historical, list) or len(historical) > 3"
    if source.count(old) != 1:
        raise ValueError("STAGE_HISTORICAL_BOUND_PATCH_PREIMAGE_MISMATCH")
    return source.replace(old, "not isinstance(historical, list) or len(historical) > 5", 1)



def validate_packet_manifest(manifest: Any, *, role: str) -> None:
    if role == "api":
        validate_api_manifest_shape(manifest)
    elif (not isinstance(manifest, dict)
          or manifest.get("schema_version") != "v4.runtime_graph_repair_release.v1"
          or not isinstance(manifest.get("app_root"), str)
          or not isinstance(manifest.get("release_id"), str)
          or not isinstance(manifest.get("application_inventory"), dict)):
        raise ValueError("RUNTIME_RELEASE_MANIFEST_IDENTITY_INVALID")


def homepage_smoke(base_url: str) -> list[dict]:
    """GET-only admission evidence for the two actual homepage prerequisites."""
    results = []
    for path in ("/api/v1/runs/date-list", "/api/v4/runtime-graph/frontend-build"):
        with urlopen(base_url.rstrip('/') + path, timeout=30) as response:
            raw = response.read(8 * 1024 * 1024)
            if response.status != 200:
                raise ValueError("HOMEPAGE_GET_FAILED:" + path)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("HOMEPAGE_RESPONSE_OBJECT_REQUIRED:" + path)
        if path.endswith('frontend-build') and payload.get('status') != 'VERIFIED':
            raise ValueError("HOMEPAGE_FRONTEND_IDENTITY_UNVERIFIED")
        if path.endswith('date-list'):
            if not payload.get('dates') or payload.get('default_date') not in payload['dates']:
                raise ValueError("HOMEPAGE_DATES_EMPTY_OR_DEFAULT_UNBOUND")
            if (payload.get('runtime_identity') or {}).get('status') != 'MANIFEST_EXECUTION_FILES_VERIFIED':
                raise ValueError("HOMEPAGE_DATE_RUNTIME_IDENTITY_UNVERIFIED")
        results.append({'path': path, 'http_status': 200, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'status': payload.get('status'), 'date_count': len(payload.get('dates', []))})
    return results


def validate_dependency_packet(packet: dict, *, installed: bool = False, old: bool = False) -> dict:
    """Check every outgoing/reverse reference using draft or installed bytes.

    In draft mode the only substitutions are the three known live plist
    addresses. All other source files are read at their actual pinned paths.
    """
    import plistlib
    from ops.api_release_integration import inventory_digest
    validate_runtime_locations(packet)
    for key in ('company_delta', 'company_score_delta'):
        reference = packet.get(key)
        if reference and sha(Path(reference['path'])) != reference['sha256']:
            raise ValueError('REVIEWED_DELTA_INPUT_DRIFT:' + key)
    for reference in packet.get('tool_source_files', []):
        if sha(Path(reference['path'])) != reference['sha256']:
            raise ValueError('REVIEWED_TOOL_SOURCE_DRIFT:' + reference['path'])
    substitutions = {}
    for role, service in packet['services'].items():
        live = Path(service['live_plist'])
        draft = Path(service['draft_plist'])
        if sha(draft) != service['draft_plist_sha256']:
            raise ValueError('DRAFT_PLIST_DRIFT:' + role)
        expected_live = service['before_sha256'] if old or not installed else service['draft_plist_sha256']
        if sha(live) != expected_live:
            raise ValueError('LIVE_PLIST_DRIFT:' + role)
        substitutions[str(live)] = live if installed or old else draft
    if old:
        return {'status': 'EXACT_PREVIOUS_PLISTS_RESTORED'}
    for role, service in packet['services'].items():
        plist_path = substitutions[service['live_plist']]
        plist = plistlib.loads(plist_path.read_bytes())
        env = plist['EnvironmentVariables']
        if plist.get('WorkingDirectory') != service['app_root']:
            raise ValueError('PLIST_WORKING_DIRECTORY_DRIFT:' + role)
        if role in {'main', 'stage'}:
            entry = 'launch_v4_macos_scheduler.sh' if role == 'main' else 'run_stage_center_nodes.py'
            if str(Path(service['app_root']) / 'ops' / entry) not in plist.get('ProgramArguments', []):
                raise ValueError('PLIST_ENTRY_OWNER_DRIFT:' + role)
        if role == 'stage' and env.get('STAGE_CENTER_CONFIG') != str(Path(service['app_root']) / 'stage_center_tick_config.json'):
            raise ValueError('PLIST_STAGE_CONFIG_OWNER_DRIFT')
        if any(env.get(key) != service[value] for key, value in (
            ('V4_APP_ROOT', 'app_root'), ('V4_RELEASE_ID', 'release_id'),
            ('V4_RELEASE_MANIFEST_PATH', 'manifest'), ('V4_RELEASE_MANIFEST_SHA256', 'manifest_sha256'))):
            raise ValueError('PLIST_RELEASE_IDENTITY_DRIFT:' + role)
        manifest_path = Path(env['V4_RELEASE_MANIFEST_PATH'])
        if sha(manifest_path) != env['V4_RELEASE_MANIFEST_SHA256']:
            raise ValueError('RELEASE_MANIFEST_SHA_DRIFT:' + role)
        manifest = json.loads(manifest_path.read_text())
        validate_packet_manifest(manifest, role=role)
        identity = manifest['candidate'] if role == 'api' else manifest
        if identity.get('app_root') != service['app_root'] or identity.get('release_id') != service['release_id']:
            raise ValueError('MANIFEST_RELEASE_IDENTITY_DRIFT:' + role)
        inventory = manifest['application_inventory']
        if (inventory.get('entry_count') != len(inventory['entries'])
                or inventory_digest(inventory['entries']) != inventory.get('aggregate_sha256')):
            raise ValueError('RELEASE_INVENTORY_DIGEST_DRIFT:' + role)
        if frozen_inventory(Path(service['app_root']), manifest['application_inventory']['entries']) != manifest['application_inventory']['entries']:
            raise ValueError('RELEASE_INVENTORY_DRIFT:' + role)
    stage = packet['services']['stage']
    config = json.loads((Path(stage['app_root']) / 'stage_center_tick_config.json').read_text())
    main = packet['services']['main']
    owner = config['research_owner_binding']
    if owner != {'app_root': main['app_root'], 'release_id': main['release_id'],
                 'manifest_sha256': main['manifest_sha256'], 'manifest_path': main['manifest']}:
        raise ValueError('STAGE_MAIN_OWNER_DRIFT')
    main_env = plistlib.loads(substitutions[main['live_plist']].read_bytes())['EnvironmentVariables']
    policy_path = Path(main_env['V4_RESEARCH_RETENTION_POLICY'])
    if sha(policy_path) != main_env['V4_RESEARCH_RETENTION_POLICY_SHA256']:
        raise ValueError('MAIN_POLICY_SHA_DRIFT')
    policy = json.loads(policy_path.read_text())
    if policy['auto_gc_enabled'] is not False or policy['dry_run'] is not True:
        raise ValueError('GOVERNANCE_MODE_CHANGED')
    pin_ref = policy['managed_pin_inventory']
    pins_path = Path(pin_ref['path'])
    if sha(pins_path) != pin_ref['sha256']:
        raise ValueError('POLICY_PINS_SHA_DRIFT')
    pins = json.loads(pins_path.read_text())
    if pins['expected_main_app_root'] != main['app_root']:
        raise ValueError('PINS_MAIN_OWNER_DRIFT')
    for ref in pins['source_bindings']:
        source = substitutions.get(ref['path'], Path(ref['path']))
        if sha(source) != ref['sha256']:
            raise ValueError('REVERSE_SOURCE_HASH_DRIFT:' + ref['path'])
    static = packet['static']
    asset_manifest = Path(static['manifest'])
    if sha(asset_manifest) != static['manifest_sha256']:
        raise ValueError('STATIC_MANIFEST_SHA_DRIFT')
    api = packet['services']['api']
    api_env = plistlib.loads(substitutions[api['live_plist']].read_bytes())['EnvironmentVariables']
    if (api_env['V4_RESEARCH_PANEL_ROOT'] != static['root']
            or api_env['V4_RESEARCH_PANEL_ASSET_MANIFEST'] != static['manifest']):
        raise ValueError('API_STATIC_LOCATOR_DRIFT')
    for item in json.loads(asset_manifest.read_text())['files']:
        path = Path(static['root']) / item['path']
        if sha(path) != item['sha256']:
            raise ValueError('STATIC_ASSET_SHA_DRIFT:' + item['path'])
    return {'status': 'PASS_FULL_DEPENDENCY_TUPLE', 'source_bindings_checked': len(pins['source_bindings']),
            'mode': 'INSTALLED' if installed else 'DRAFT_PLIST_SUBSTITUTION_ONLY',
            'main_manifest_preserved': main['old_manifest_sha256'] == main['manifest_sha256'],
            'main_delta_scope': packet.get('main_delta_scope')}


def validate_runtime_locations(packet: dict) -> None:
    """Reject the observed Desktop launchd failure before any cutover.

    Only this packet's executable app/static/config locators are restricted.
    Existing business inputs and historical evidence retain their real paths.
    """
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    root = Path(packet.get('runtime_candidate_root', ''))
    if (not root.is_absolute() or root == approved or not root.is_relative_to(approved)
            or root.is_symlink() or root.resolve() != root):
        raise ValueError('RUNTIME_CANDIDATE_MUST_USE_EXISTING_LIBRARY_ROOT')
    paths = [packet['policy']['path'], packet['pins']['path'],
             packet['static']['root'], packet['static']['manifest']]
    for service in packet['services'].values():
        paths.extend(service[key] for key in ('app_root', 'manifest', 'draft_plist'))
    for value in paths:
        path = Path(value)
        if (not path.is_absolute() or not path.is_relative_to(root)
                or path.is_symlink() or path.resolve() != path):
            raise ValueError('RUNTIME_LOCATOR_OUTSIDE_LIBRARY_PACKET:' + str(path))
