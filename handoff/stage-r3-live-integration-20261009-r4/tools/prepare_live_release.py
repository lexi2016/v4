#!/usr/bin/env python3
"""Prepare one inactive Stage R4 candidate from the verified current API release.

The command independently binds the prepared UI, complete build source graph,
generated static tree, and approved research read binding to the same active
base. It writes only a NEW destination. It never switches a pointer, starts a
service, copies research data into live state, or changes input permissions.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import uuid

sys.dont_write_bytecode = True
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False,
         'buy_gate_updated': False, 'orders_sent': False}
DIST = 'apps/web/dist'
UI_PATHS = frozenset({'apps/web/src/App.vue', 'apps/web/src/contracts/runtime.ts',
                     'apps/web/src/components/review/StageExecutionEvidencePanel.vue'})
API_PATHS = frozenset({'apps/api/v35_api/app.py', 'stage_center/consumer.py',
                      'stage_center/execution_evidence.py', 'stage_center/research_read_binding.py'})
BINDING_PATHS = ('stage_center/approved_research_read.json', 'stage_center/approved_research_read.sha256')
RELEASE_SHA256 = {
    'api_release_integration.py': '5325f7a81acadb4016385416c88319e4baab0a26974ac19ed17dd7debb7e0f29',
    'create_api_module_delta.py': '594a537982c8e060d29158445468a5cfd6af585f3b78c7872fe7625bf6f8012d',
    'build_release_candidate.py': '33bd9f8b4dd1803e0ff583a7763576374b83f89d38bac6ca0249316f17a10404',
    'prepare_api_only_cutover.py': '0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c',
    'build_release_candidate_stage.py': '79cbb7ab98ca894594c2f80f802d9ed410bf64489decad469fdf3fc9d6b402df',
    'release_candidate_audit.py': '84d30676cf88d244f930eb0abc1f8184db20e53ec2e0ad7a4f32590086673cdf',
    'release_candidate_sources.py': '76d963c71cb388e1f7efc51478078f0f21dd280093646fc9d47e955dfe04a738',
    'release_candidate_ports.py': '1b70ef9725335c1570b96b937753917ac9d5114cfa66359ee08178eb282fd7d4',
    'stage_service_overlay_contract.py': '36eb27395bfd10cc78c6f0ba237eb67afe22716f653e56b5dec2ab3827e22838',
}
HELPER_SHA256 = {
    'canary_sources.py': '5c7e0079796bc599fa43b684f81aae3ce55977e6fade71a0f3580d9d72610ebb',
    'build_stage_ui.py': '06aa4fd4a034af1cf3b1e761a5e9d0c062eec1f26152f2b08f6f2c202e16e4dc',
    'prepare_research_binding.py': 'c564dbdb739f239c8243f3dd38705d73a2998ff11e0757b50899e80503daedc9',
}


def _check(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value, *, directory=False):
    value = Path(value).expanduser()
    _check(value.is_absolute() and '..' not in value.parts, 'ABSOLUTE_UNALIASED_PATH_REQUIRED')
    _check(not any(part.is_symlink() for part in (value, *value.parents)), 'INPUT_PATH_SYMLINK_REJECTED')
    if directory:
        _check(value.is_dir(), 'INPUT_DIRECTORY_REQUIRED:' + str(value))
    return value


def _read(path):
    path = _path(path)
    info = path.lstat()
    _check(stat.S_ISREG(info.st_mode), 'INPUT_REGULAR_FILE_REQUIRED')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as handle:
        opened = os.fstat(handle.fileno())
        _check(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino),
               'INPUT_FILE_CHANGED_DURING_OPEN')
        raw = handle.read()
        final = os.fstat(handle.fileno())
    observed = path.lstat()
    token = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    _check(token(info) == token(opened) == token(final) == token(observed), 'INPUT_FILE_CHANGED_DURING_READ')
    return raw


def _object(raw, label):
    def unique(pairs):
        output = {}
        for key, value in pairs:
            _check(key not in output, label + '_DUPLICATE_KEY')
            output[key] = value
        return output
    def invalid(value):
        raise ValueError(label + '_NONFINITE')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    _check(isinstance(value, dict), label + '_OBJECT_REQUIRED')
    return value


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _safe_flags(value, label):
    _check(all(value.get(key) is wanted for key, wanted in FLAGS.items()), label + '_SAFETY_FLAGS_INVALID')


def _module(name, path, raw, *, package=None):
    module = ModuleType(name)
    module.__file__, module.__package__ = str(path), package or name.rpartition('.')[0]
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def _load_release_tools(package):
    """Compile the same verified bytes under a new private module namespace."""
    package = _path(package, directory=True)
    ops = package / 'release_tools/after/ops'
    raw = {name: _read(ops / name) for name in RELEASE_SHA256}
    for name, expected in RELEASE_SHA256.items():
        _check(_sha(raw[name]) == expected, 'RELEASE_TOOL_SHA_MISMATCH:' + name)
    namespace = '_stage_r4_release_' + uuid.uuid4().hex
    parent = ModuleType(namespace); parent.__path__ = [str(ops.parent)]
    child = ModuleType(namespace + '.ops'); child.__path__ = [str(ops)]
    sys.modules[namespace], sys.modules[child.__name__] = parent, child
    loaded = {}
    order = ('api_release_integration', 'release_candidate_sources', 'release_candidate_ports',
             'release_candidate_audit', 'stage_service_overlay_contract', 'prepare_api_only_cutover',
             'build_release_candidate_stage', 'create_api_module_delta', 'build_release_candidate')
    previous = sys.modules.get('prepare_api_only_cutover')
    try:
        for name in order:
            loaded[name] = _module(child.__name__ + '.' + name, ops / (name + '.py'), raw[name + '.py'])
            if name == 'prepare_api_only_cutover':
                # The existing builder has an absolute-import compatibility
                # branch. Bind it only to this verified adjacent helper.
                sys.modules['prepare_api_only_cutover'] = loaded[name]
    finally:
        if previous is None:
            sys.modules.pop('prepare_api_only_cutover', None)
        else:
            sys.modules['prepare_api_only_cutover'] = previous
    guard = loaded['api_release_integration']
    delta, builder = loaded['create_api_module_delta'], loaded['build_release_candidate']
    _check(delta.integration is guard and builder.build_integrated_app is guard.build_integrated_app
           and builder.verify_api_release_candidate is guard.verify_api_release_candidate,
           'ADJACENT_RELEASE_GUARD_IDENTITY_MISMATCH')
    helpers = {}
    for filename, expected in HELPER_SHA256.items():
        content = _read(package / 'tools' / filename)
        _check(_sha(content) == expected, 'PREPARATION_HELPER_SHA_MISMATCH:' + filename)
        helpers[filename] = _module(namespace + '.' + filename[:-3], package / 'tools' / filename, content)
    _check(Path(helpers['build_stage_ui.py'].sources.__file__) == package / 'tools/canary_sources.py',
           'UI_SOURCE_HELPER_PATH_MISMATCH')
    return SimpleNamespace(guard=guard, delta=delta, builder=builder, cutover=loaded['prepare_api_only_cutover'],
                           sources=helpers['canary_sources.py'],
                           ui=helpers['build_stage_ui.py'], binding=helpers['prepare_research_binding.py'])


def _reviewed_files(package, mapping, active, guard):
    _safe_flags(mapping, 'SOURCE_MAP')
    selected = [row for row in mapping.get('files', []) if row.get('group') in {'api', 'ui'}]
    _check(len(selected) == 7, 'EXACT_SEVEN_REVIEWED_SOURCE_FILES_REQUIRED')
    _check({row.get('relative_path') for row in selected if row['group'] == 'api'} == API_PATHS
           and {row.get('relative_path') for row in selected if row['group'] == 'ui'} == UI_PATHS,
           'REVIEWED_SOURCE_PATH_SET_MISMATCH')
    observed = {row['path']: row for row in active['inventory']}
    changes, contents, pins = [], {}, {}
    for row in selected:
        rel = guard._normalise_relative(row['relative_path'])
        expected_after = 'after/' + row['group'] + '/' + rel
        _check(row.get('after_path') == expected_after, 'REVIEWED_AFTER_PATH_MISMATCH:' + rel)
        raw = _read(package / expected_after)
        _check(guard._is_sha(row.get('after_sha256')) and _sha(raw) == row['after_sha256'],
               'REVIEWED_AFTER_SHA_MISMATCH:' + rel)
        if 'after_bytes' in row:
            _check(type(row['after_bytes']) is int and row['after_bytes'] == len(raw), 'REVIEWED_AFTER_SIZE_MISMATCH')
        old = observed.get(rel)
        guard._safe_child(Path(active['app_root']), rel, allow_missing=True)
        if row.get('operation') == 'add':
            _check(old is None and row.get('before_sha256') is None and row.get('accepted_before_sha256') == [],
                   'REVIEWED_ADDITION_PREIMAGE_NOT_ABSENT:' + rel)
            before, mode = None, '0644'
        else:
            _check(row.get('operation') == 'modify' and old is not None and old.get('kind') == 'file'
                   and row.get('before_sha256') == old.get('sha256')
                   and old['sha256'] in row.get('accepted_before_sha256', []), 'REVIEWED_BEFORE_SHA_MISMATCH:' + rel)
            before, mode = old['sha256'], old['mode']
            before_rel = 'before/' + row['group'] + '/' + rel
            _check(row.get('before_path') == before_rel and _sha(_read(package / before_rel)) == before,
                   'PACKAGE_BEFORE_IMAGE_MISMATCH:' + rel)
            pins[package / before_rel] = before
        _check(before != row['after_sha256'], 'REVIEWED_SOURCE_HAS_NO_BYTE_CHANGE:' + rel)
        if row['group'] == 'ui':
            _check(old is not None, 'LIVE_UI_PREIMAGE_MUST_EXIST:' + rel)
        changes.append({'path': rel, 'before_sha256': before, 'after_sha256': row['after_sha256'],
                        'before_mode': old['mode'] if old else None, 'after_mode': mode})
        contents[rel] = (raw, mode)
        pins[package / expected_after] = row['after_sha256']
    return sorted(changes, key=lambda row: row['path']), contents, pins


def _non_dist(entries):
    return {path: row for path, row in entries.items() if path != DIST and not path.startswith(DIST + '/')}


def _verify_ui(*, package, mapping, mapping_sha, active, prepared_ui, receipt_path, tools):
    sources, guard = tools.sources, tools.guard
    policy = sources.load_policy(package, mapping, 'ui', sources.IGNORED)
    _check(policy['copy_roots'] == ['apps/web'] and policy['optional_roots'] == [] and policy['symlinks'] == {},
           'EXACT_CURRENT_UI_SOURCE_POLICY_REQUIRED')
    original = sources.snapshot(Path(active['app_root']), policy)
    expected = deepcopy(original['entries'])
    for row in mapping['files']:
        if row.get('group') == 'ui':
            old = expected[row['relative_path']]
            expected[row['relative_path']] = {'type': 'file', 'mode': old['mode'], 'sha256': row['after_sha256']}
    prepared = sources.snapshot(prepared_ui, policy, candidate=True)
    _check(prepared['entries'] == expected and not prepared['links'], 'PREPARED_UI_IS_NOT_EXACT_ACTIVE_PLUS_THREE')
    provenance_raw = _read(prepared_ui / sources.MANIFEST)
    provenance = _object(provenance_raw, 'PREPARED_UI_MANIFEST')
    verified = sources.verify_manifest(prepared_ui, policy, mapping_sha, prepared)
    _check(verified is not None and verified['sha256'] == _sha(provenance_raw)
           and provenance.get('source_root') == active['app_root']
           and provenance.get('destination') == str(prepared_ui)
           and provenance.get('source_tree_sha256') == sources.tree_id(original['entries'])
           and provenance.get('candidate_tree_sha256') == sources.tree_id(expected)
           and provenance.get('copy_roots') == ['apps/web'] and provenance.get('optional_roots') == []
           and provenance.get('source_links') == [] and provenance.get('quarantined_links') == []
           and provenance.get('source_bytes_and_permissions_unchanged') is True
           and provenance.get('permissions_restored') is True, 'PREPARED_UI_PROVENANCE_MISMATCH')
    raw = _read(receipt_path); receipt = _object(raw, 'UI_BUILD_RECEIPT')
    _safe_flags(receipt, 'UI_BUILD_RECEIPT')
    _check(receipt.get('schema_version') == 'V4_STAGE_UI_BUILD_V1' and receipt.get('status') == 'UI_BUILD_PREPARED'
           and receipt.get('package') == str(package) and receipt.get('prepared_ui') == str(prepared_ui)
           and receipt.get('errors') == [] and receipt.get('write_performed') is True
           and receipt.get('source_bytes_and_modes_unchanged') is True
           and receipt.get('build_source_bytes_unchanged') is True, 'UI_BUILD_RECEIPT_STATUS_INVALID')
    build_root = _path(receipt.get('destination'), directory=True)
    _check(receipt_path == build_root / 'BUILD_RECEIPT.json'
           and receipt.get('built_dist_root') == str(build_root / DIST), 'UI_BUILD_RECEIPT_ROOT_MISMATCH')
    _check(receipt.get('source_map_sha256') == mapping_sha
           and receipt.get('prepared_source_manifest_sha256') == _sha(provenance_raw)
           and receipt.get('prepared_source_tree_sha256') == sources.tree_id(expected)
           and receipt.get('prepared_source_root') == active['app_root'], 'UI_BUILD_RECEIPT_PROVENANCE_MISMATCH')
    lock_sha = _sha(_read(prepared_ui / 'apps/web/package-lock.json'))
    _check(receipt.get('lock_sha256') == lock_sha, 'UI_BUILD_LOCK_SHA_MISMATCH')
    writable = _non_dist(deepcopy(expected))
    for path, row in writable.items():
        row['mode'] = (0o700 if path == '.' else 0o755) if row['type'] == 'directory' else row['mode'] | stat.S_IWUSR
    build = sources.snapshot(build_root, policy, candidate=True)
    build_source = _non_dist(build['entries'])
    _check(build_source == writable and receipt.get('build_source_tree_sha256') == sources.tree_id(writable),
           'BUILD_SOURCE_IS_NOT_EXACT_REVIEWED_WRITABLE_CLONE')
    commands = receipt.get('commands')
    _check(isinstance(commands, list) and len(commands) == 2, 'UI_BUILD_COMMANDS_REQUIRED')
    first = commands[0].get('command')
    _check(isinstance(first, list) and len(first) == 2 and isinstance(first[0], str) and bool(first[0])
           and first[1:] == ['ci'] and commands[1].get('command') == [first[0], 'run', 'build']
           and all(type(row.get('exit_code')) is int and row['exit_code'] == 0
                   and row.get('cwd') == str(build_root / 'apps/web') for row in commands), 'UI_BUILD_COMMAND_FAILED_OR_CHANGED')
    static = tools.ui._static_inventory(build_root)
    _check(receipt.get('static_inventory') == static
           and receipt.get('static_inventory_sha256') == guard.inventory_digest(static), 'UI_BUILD_STATIC_INVENTORY_MISMATCH')
    wanted_html = sorted({path[len(DIST) + 1:] for path, row in expected.items()
                          if path.startswith(DIST + '/') and path.endswith('.html') and row['type'] == 'file'} | {'index.html'})
    _check(receipt.get('retained_html_entries') == wanted_html
           and {DIST + '/' + path for path in wanted_html} <= {row['path'] for row in static}
           and any(row['path'].endswith('.js') for row in static), 'UI_BUILD_HTML_OR_JAVASCRIPT_MISSING')
    html = tools.ui._validate_html_dependencies(build_root, static)
    if 'html_dependency_validation' in receipt:
        _check(receipt['html_dependency_validation'] == html, 'UI_BUILD_HTML_PROOF_MISMATCH')
    _check(_read(prepared_ui / sources.MANIFEST) == provenance_raw and _read(receipt_path) == raw
           and sources.snapshot(prepared_ui, policy, candidate=True) == prepared
           and sources.snapshot(build_root, policy, candidate=True) == build, 'UI_INPUT_CHANGED_DURING_PREFLIGHT')
    return {'prepared_ui': str(prepared_ui), 'build_root': str(build_root), 'built_dist_root': str(build_root / DIST),
            'source_map_sha256': mapping_sha, 'prepared_source_manifest_sha256': _sha(provenance_raw),
            'active_ui_tree_sha256': sources.tree_id(original['entries']),
            'prepared_ui_tree_sha256': sources.tree_id(expected), 'build_source_tree_sha256': sources.tree_id(writable),
            'lock_sha256': lock_sha, 'static_inventory_sha256': guard.inventory_digest(static),
            'static_inventory': static, 'html_dependency_validation': html,
            'build_receipt_path': str(receipt_path), 'build_receipt_sha256': _sha(raw)}


def _selection_root(api_plist):
    payload = plistlib.loads(_read(api_plist))
    args = payload.get('ProgramArguments')
    _check(isinstance(args, list) and all(isinstance(value, str) for value in args), 'ACTIVE_API_ARGUMENTS_INVALID')
    roots = []
    for offset, value in enumerate(args):
        if value == '--stage-selection-root':
            _check(offset + 1 < len(args), 'ACTIVE_STAGE_ROOT_VALUE_MISSING')
            roots.append(args[offset + 1])
        elif value.startswith('--stage-selection-root='):
            roots.append(value.split('=', 1)[1])
    _check(len(roots) == 1, 'EXACT_ACTIVE_STAGE_SELECTION_ROOT_REQUIRED')
    return _path(roots[0], directory=True)


def _manager_root(api_plist, cutover):
    payload = plistlib.loads(_read(api_plist))
    name = 'V4_MANAGER_RESEARCH_STATE_ROOT'
    value = cutover.extract_environment(payload).get(name)
    _check(isinstance(value, str), 'EXPLICIT_ACTIVE_MANAGER_STATE_ROOT_REQUIRED')
    declarations = [item.split('=', 1)[1] for item in payload.get('ProgramArguments', [])
                    if isinstance(item, str) and item.startswith(name + '=')]
    environment = payload.get('EnvironmentVariables', {})
    if name in environment:
        declarations.append(environment[name])
    _check(declarations and all(item == value for item in declarations), 'ACTIVE_MANAGER_ROOT_PRODUCERS_CONFLICT')
    root = _path(value, directory=True)
    info = root.lstat()
    return root, (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode))


def _prepare_preserving_plan(*, destination, candidate, release_id, manifest_sha, api_plist,
                             scheduler_plist, scheduler_sha, active, verification, manager, binding, ui,
                             mapping_sha, tools):
    """Use the existing pure renderer; retain its original builder outputs."""
    original_raw = _read(api_plist)
    _check(_sha(original_raw) == verification['active_api_plist_sha256'], 'STAGED_API_SOURCE_CHANGED')
    original = plistlib.loads(original_raw)
    manifest_path = candidate / 'release-manifest.json'
    replacements = {
        'V35_APP_ROOT': str(candidate / 'app'), 'V35_RELEASE_ID': release_id,
        'PYTHONPATH': str(candidate / 'app/upstreams') + ':' + str(candidate / 'app'),
        'V35_RELEASE_MANIFEST_PATH': str(manifest_path), 'V35_RELEASE_MANIFEST_SHA256': manifest_sha,
    }
    staged = tools.cutover.rewrite_api_only_plist(original, candidate_app_root=candidate / 'app',
        release_id=release_id, manifest_path=manifest_path, manifest_sha256=manifest_sha,
        candidate_manager_state_root=None)
    expected_args = []
    for item in original['ProgramArguments']:
        key = item.split('=', 1)[0]
        expected_args.append(key + '=' + replacements[key] if key in replacements else item)
    expected = dict(original, ProgramArguments=expected_args, WorkingDirectory=str(candidate / 'app'))
    if 'EnvironmentVariables' in original:
        expected['EnvironmentVariables'] = {key: replacements.get(key, value)
                                           for key, value in original['EnvironmentVariables'].items()}
    _check(staged == expected, 'STAGED_API_CHANGED_NONIDENTITY_ARGUMENT_OR_ENVIRONMENT')
    _check(tools.cutover.extract_environment(staged).get('V4_MANAGER_RESEARCH_STATE_ROOT') == str(manager)
           and str(_selection_root(api_plist)) == binding['history']['root'], 'STAGED_RUNTIME_ROOT_NOT_PRESERVED')
    staged_raw = plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True)
    plan_root = destination / 'stage-publication'
    staged_path = plan_root / 'com.lexi.v35.api-only.plist'
    plan_path = plan_root / 'api-only-preserved-plan.json'
    generic_path = candidate / 'config/api-only-cutover-plan.json'
    generic = {'path': str(generic_path), 'sha256': _sha(_read(generic_path)),
               'publication_eligible': False, 'reason': 'MANAGER_ROOT_ISOLATED'}
    plan = {'schema_version': 'V4_STAGE_PRESERVED_API_PREPARATION_V1', 'status': 'PREPARED_NOT_DEPLOYED',
        'candidate_root': str(candidate), 'release_id': release_id,
        'source_plist': {'path': str(api_plist), 'sha256': _sha(original_raw), 'label': original.get('Label')},
        'candidate_plist': {'path': str(staged_path), 'sha256': _sha(staged_raw)},
        'candidate_manifest': {'path': str(manifest_path), 'sha256': manifest_sha},
        'base': tools.guard._base_binding(active), 'api_release_integration': verification,
        'manager_state': {'current_root': str(manager), 'candidate_root': str(manager),
                          'root_preserved': True, 'state_copied': False},
        'history': {'root': binding['history']['root'], 'root_preserved': True},
        'scheduler_plist': {'path': str(scheduler_plist), 'sha256': scheduler_sha, 'rebound': False},
        'source_inputs': {'source_map_sha256': mapping_sha,
            'ui_build_receipt': {'path': ui['build_receipt_path'], 'sha256': ui['build_receipt_sha256']},
            'binding_proof': {'path': binding['proof_path'], 'sha256': binding['proof_sha256']}},
        'builder_only_cutover_plan': generic,
        'activation_status': 'NOT_ACTIVATED', 'launchctl_called': False, 'automatic_activation': False,
        'candidate_preparation_only': True, 'deployed': False,
        'activation_protocol': {'shared_lock_required': True, 'integration_revalidation_required': True,
            'preserving_plist_revalidation_required': True, 'automatic_activation': False}, **FLAGS}
    plan_raw = _json(plan)
    tools.guard._assert_active_snapshot(active)
    _check(_read(api_plist) == original_raw and _sha(_read(manifest_path)) == manifest_sha,
           'STAGED_API_INPUT_CHANGED_DURING_RENDER')
    tools.guard._write_candidate_bytes(destination, str(staged_path.relative_to(destination)),
                                       staged_raw, 0o600, exclusive=True)
    tools.guard._write_candidate_bytes(destination, str(plan_path.relative_to(destination)),
                                       plan_raw, 0o600, exclusive=True)
    return {'prepared_plan_path': str(plan_path), 'prepared_plan_sha256': _sha(plan_raw),
            'staged_api_plist_path': str(staged_path), 'staged_api_plist_sha256': _sha(staged_raw),
            'builder_only_cutover_plan': generic}


def _rebuild_binding(*, tools, python, active_app, api_after, manifest, history):
    # Isolated Python ignores inherited PYTHONPATH/user site. The trusted child
    # explicitly mounts only the current support tree and reviewed reader files.
    command = [str(python), '-I', '-B', '-c', tools.binding._BUILD,
               str(active_app), str(api_after), str(manifest), str(history)]
    child = subprocess.run(command, cwd=api_after, capture_output=True, text=True, timeout=120)
    if child.returncode:
        detail = child.stderr.strip().splitlines()[-1] if child.stderr.strip() else 'NO_CHILD_ERROR_DETAIL'
        raise ValueError('BINDING_REVALIDATION_FAILED:' + detail)
    return _object(child.stdout.encode(), 'REBUILT_RESEARCH_BINDING')


def _verify_binding(*, package, active, api_plist, proof_path, code_rows, tools, python):
    raw = _read(proof_path); proof = _object(raw, 'BINDING_PREPARATION_PROOF')
    _safe_flags(proof, 'BINDING_PREPARATION_PROOF')
    _check(proof.get('schema_version') == 'V4_STAGE_RESEARCH_READ_PREPARATION_V1'
           and proof.get('status') == 'PREPARED_NOT_DEPLOYED'
           and proof.get('candidate_preparation_only') is True
           and proof.get('history_root_preserved') is True
           and proof.get('history_latest_unchanged_during_preparation') is True
           and all(proof.get(key) is False for key in ('integrated', 'deployed', 'natural_verified', 'execution_verified')),
           'BINDING_PREPARATION_PROOF_STATUS_INVALID')
    root = _path(proof.get('output_root'), directory=True)
    _check(proof_path == root / 'PREPARATION_PROOF.json', 'BINDING_PROOF_ROOT_MISMATCH')
    api_after = package / 'after/api'
    expected_api = {row['path']: row['after_sha256'] for row in code_rows if row['path'] in API_PATHS}
    active_app_sha = next(row['sha256'] for row in active['inventory'] if row['path'] == 'apps/api/v35_api/app.py')
    _check(proof.get('api_source_root') == active['app_root'] and proof.get('api_after_root') == str(api_after)
           and proof.get('current_api_app_sha256') == active_app_sha
           and proof.get('reviewed_api_after_sha256') == expected_api
           and proof.get('generator_sha256') == HELPER_SHA256['prepare_research_binding.py'], 'BINDING_API_SOURCE_IDENTITY_MISMATCH')
    history = _selection_root(api_plist)
    history_record = tools.binding._history_observation(history)
    _check(proof.get('history') == history_record, 'BINDING_HISTORY_ROOT_OR_LATEST_MISMATCH')
    files = proof.get('files')
    _check(isinstance(files, list) and len(files) == 2 and [row.get('path') for row in files] == list(BINDING_PATHS),
           'EXACT_GENERATED_BINDING_PAIR_REQUIRED')
    contents = {}
    for row in files:
        _check(set(row) == {'path', 'before_sha256', 'after_sha256', 'before_mode', 'after_mode'}
               and row['before_sha256'] is None and row['before_mode'] is None and row['after_mode'] == '0644',
               'BINDING_FILE_ROW_INVALID')
        path = row['path']
        _check(not os.path.lexists(Path(active['app_root']) / path) and not os.path.lexists(api_after / path),
               'BINDING_PREIMAGE_MUST_BE_ABSENT')
        content = _read(root / path)
        _check(_sha(content) == row['after_sha256'] and stat.S_IMODE((root / path).stat().st_mode) == 0o644,
               'BINDING_FILE_SHA_OR_MODE_MISMATCH')
        contents[path] = (content, '0644')
    document = _object(contents[BINDING_PATHS[0]][0], 'RESEARCH_BINDING')
    expected_sha = _sha(contents[BINDING_PATHS[0]][0])
    _check(contents[BINDING_PATHS[1]][0] == (expected_sha + '\n').encode('ascii')
           and proof.get('binding_sha256') == expected_sha and proof.get('binding_evidence') == document
           and document.get('reader_sources') == expected_api and document.get('history_root') == str(history),
           'BINDING_PAIR_OR_EVIDENCE_MISMATCH')
    manifest = _path(document.get('manifest_path'))
    _check(_sha(_read(manifest)) == document.get('run_manifest_sha256'), 'BINDING_MANIFEST_SHA_MISMATCH')
    rebuilt = _rebuild_binding(tools=tools, python=python, active_app=Path(active['app_root']),
                               api_after=api_after, manifest=manifest, history=history)
    _check(rebuilt == document, 'BINDING_TRANSITIVE_EVIDENCE_MISMATCH')
    _check(_read(proof_path) == raw and tools.binding._history_observation(history) == history_record,
           'BINDING_PROOF_OR_HISTORY_CHANGED_DURING_PREFLIGHT')
    for path, (content, _) in contents.items():
        _check(_read(root / path) == content, 'BINDING_INPUT_CHANGED_DURING_PREFLIGHT')
    return {'proof_path': str(proof_path), 'proof_sha256': _sha(raw), 'output_root': str(root),
            'files': files, 'binding_sha256': expected_sha, 'history': history_record,
            'manifest_path': str(manifest), 'run_manifest_sha256': document['run_manifest_sha256']}, contents


def prepare_live_release(*, package, active_api_plist, scheduler_plist, prepared_ui,
                         ui_build_receipt, binding_proof, destination, python, release_id):
    package = _path(package, directory=True)
    destination = _path(destination)
    _path(destination.parent, directory=True)
    _check(not os.path.lexists(destination), 'DESTINATION_ALREADY_EXISTS')
    _check(isinstance(release_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', release_id),
           'RELEASE_ID_INVALID')
    python = Path(os.path.abspath(os.path.expanduser(str(python))))
    _check(python.is_file(), 'EXPLICIT_RUNTIME_PYTHON_REQUIRED')
    active_api_plist, scheduler_plist = _path(active_api_plist), _path(scheduler_plist)
    prepared_ui = _path(prepared_ui, directory=True)
    ui_build_receipt, binding_proof = _path(ui_build_receipt), _path(binding_proof)
    tools = _load_release_tools(package); guard = tools.guard
    active = guard.read_active_release(active_api_plist)
    manager, manager_identity = _manager_root(active_api_plist, tools.cutover)
    scheduler_raw = _read(scheduler_plist)
    mapping_raw = _read(package / 'SOURCE_MAP.json'); mapping = _object(mapping_raw, 'SOURCE_MAP')
    mapping_sha = _sha(mapping_raw)
    rows, contents, package_pins = _reviewed_files(package, mapping, active, guard)
    ui = _verify_ui(package=package, mapping=mapping, mapping_sha=mapping_sha, active=active,
                    prepared_ui=prepared_ui, receipt_path=ui_build_receipt, tools=tools)
    binding, generated = _verify_binding(package=package, active=active, api_plist=active_api_plist,
        proof_path=binding_proof, code_rows=rows, tools=tools, python=python)
    for root in (package, Path(active['release_root']), prepared_ui, Path(ui['build_root']),
                 manager, Path(binding['output_root']), Path(binding['history']['root']), Path(binding['manifest_path']).parent):
        _check(not destination.is_relative_to(root) and not root.is_relative_to(destination), 'DESTINATION_OVERLAPS_INPUT_ROOT')
    tools.cutover.assert_safe_candidate_path(destination / 'candidate' / release_id)
    package_pins.update({package / 'SOURCE_MAP.json': mapping_sha,
                         package / 'CANARY_SOURCE_POLICY.json': mapping['canary_source_policy_sha256']})
    package_pins.update({package / 'release_tools/after/ops' / name: digest for name, digest in RELEASE_SHA256.items()})
    package_pins.update({package / 'tools' / name: digest for name, digest in HELPER_SHA256.items()})
    _check(all(_sha(_read(path)) == digest for path, digest in package_pins.items()), 'PACKAGE_CHANGED_DURING_PREFLIGHT')
    guard._assert_active_snapshot(active)
    _check(_read(scheduler_plist) == scheduler_raw, 'SCHEDULER_PLIST_CHANGED_DURING_PREFLIGHT')
    result = {'schema_version': 'V4_STAGE_LIVE_RELEASE_PREPARATION_V1', 'status': 'PREPARATION_FAILED',
        'package': str(package), 'source_map_sha256': mapping_sha, 'destination': str(destination),
        'base': guard._base_binding(active), 'history_root': binding['history']['root'],
        'ui_graph_proof': ui, 'binding_proof': binding, 'runtime_python': str(python),
        'deployed': False, 'automatic_activation': False, 'natural_verified': False,
        'api_verified': False, 'ui_verified': False, 'errors': [], **FLAGS}
    destination.mkdir(mode=0o700)
    receipt_path = destination / 'PREPARATION_RECEIPT.json'
    try:
        after = destination / 'after'; after.mkdir(mode=0o700)
        for path, (raw, mode) in {**contents, **generated}.items():
            guard._write_candidate_bytes(after, path, raw, int(mode, 8), exclusive=True)
        code_rows = sorted([*rows, *binding['files']], key=lambda row: row['path'])
        shared = sorted(row['path'] for row in code_rows if row['path'] in guard.POLICY['shared'])
        changes = {'schema_version': tools.delta.CHANGE_SET_SCHEMA, 'module': 'stage',
                   'shared_paths': shared, 'files': code_rows}
        change_path = destination / 'reviewed-change-set.json'
        guard._write_candidate_bytes(destination, change_path.name, _json(changes), 0o600, exclusive=True)
        prepared = tools.delta.prepare_stage_source(active_api_plist_path=active_api_plist,
            after_root=after, change_set_path=change_path, built_dist_root=Path(ui['built_dist_root']),
            expected_static_inventory_sha256=ui['static_inventory_sha256'], source_root=destination / 'source',
            output_change_set_path=destination / 'complete-change-set.json')
        result['source_preparation'] = prepared
        delta_path = destination / 'api-delta.json'
        delta_receipt = tools.delta.create_module_delta(active_api_plist_path=active_api_plist,
            after_root=Path(prepared['source_root']), change_set_path=Path(prepared['change_set_path']), output_path=delta_path)
        result['delta_preparation'] = delta_receipt
        candidates = destination / 'candidate'; candidates.mkdir(mode=0o700)
        candidate = candidates / release_id
        built = tools.builder.build_candidate(source_root=Path(prepared['source_root']), candidate_root=candidate,
            api_plist_path=active_api_plist, scheduler_plist_path=scheduler_plist, python=python,
            release_id=release_id, api_integration_delta_receipt_path=delta_path,
            receipt_path=destination / 'build-receipt.json', include_untracked_paths=prepared['include_untracked_paths'])
        result['build_receipt'] = built
        _check(built.get('candidate_status') == 'READY_FOR_REVIEW', 'CANDIDATE_HAS_DEPENDENCY_OR_SOURCE_GAP')
        verification = guard.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=active_api_plist,
            expected_manifest_sha256=built['manifest_sha256'], active_pointer='base')
        # Re-read all input boundaries after the full builder. A complete new
        # directory is retained on failure, but no stale READY receipt is emitted.
        guard._assert_active_snapshot(active)
        _check(_read(scheduler_plist) == scheduler_raw, 'SCHEDULER_PLIST_CHANGED_DURING_BUILD')
        _check(all(_sha(_read(path)) == digest for path, digest in package_pins.items()), 'PACKAGE_CHANGED_DURING_BUILD')
        _check(ui == _verify_ui(package=package, mapping=mapping, mapping_sha=mapping_sha, active=active,
            prepared_ui=prepared_ui, receipt_path=ui_build_receipt, tools=tools), 'UI_PROOF_CHANGED_DURING_BUILD')
        repeated, repeated_contents = _verify_binding(package=package, active=active, api_plist=active_api_plist,
            proof_path=binding_proof, code_rows=rows, tools=tools, python=python)
        _check(repeated == binding and repeated_contents == generated, 'BINDING_PROOF_CHANGED_DURING_BUILD')
        _check(_manager_root(active_api_plist, tools.cutover) == (manager, manager_identity),
               'ACTIVE_MANAGER_ROOT_CHANGED_DURING_BUILD')
        publication = _prepare_preserving_plan(destination=destination, candidate=candidate, release_id=release_id,
            manifest_sha=built['manifest_sha256'], api_plist=active_api_plist, scheduler_plist=scheduler_plist,
            scheduler_sha=_sha(scheduler_raw), active=active, verification=verification, manager=manager,
            binding=binding, ui=ui, mapping_sha=mapping_sha, tools=tools)
        result.update(status='CANDIDATE_READY_NOT_DEPLOYED', source_root=prepared['source_root'],
            candidate_root=str(candidate), candidate_app=str(candidate / 'app'),
            change_set_path=prepared['change_set_path'], delta_receipt_path=str(delta_path),
            manifest_path=str(candidate / 'release-manifest.json'), manifest_sha256=built['manifest_sha256'],
            build_receipt_path=str(destination / 'build-receipt.json'), verification=verification,
            **publication,
            receipt_path=str(receipt_path), verify_command=[str(python), '-B',
                str(package / 'release_tools/after/ops/build_release_candidate.py'), '--verify-api-candidate',
                '--candidate-root', str(candidate), '--api-plist', str(active_api_plist),
                '--expected-manifest-sha256', built['manifest_sha256']])
        guard._write_candidate_bytes(destination, receipt_path.name, _json(result), 0o600, exclusive=True)
        return result
    except Exception as error:
        result['errors'].append(str(error))
        result['status'] = 'PREPARATION_FAILED'
        result['receipt_path'] = str(receipt_path)
        if not receipt_path.exists():
            guard._write_candidate_bytes(destination, receipt_path.name, _json(result), 0o600, exclusive=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('package', 'active-api-plist', 'scheduler-plist', 'prepared-ui', 'ui-build-receipt',
                 'binding-proof', 'destination', 'python'):
        parser.add_argument('--' + flag, required=True, type=Path)
    parser.add_argument('--release-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_live_release(**vars(args))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'PREPARATION_FAILED', 'error': str(error), 'deployed': False,
                          'automatic_activation': False, **FLAGS}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
