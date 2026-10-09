#!/usr/bin/env python3
"""Stage R4 adapter around the unchanged reviewed API publication transaction.

prepare/preflight are read-only with respect to the API and its state. Only
execute and rollback can call the original publisher's leased service/pointer
functions. The wrapper never assigns its frozen constants or changes a writer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import types
import uuid
from urllib.parse import urlencode

sys.dont_write_bytecode = True
SCHEMA = 'V4_STAGE_API_PUBLICATION_PLAN_V1'
PUBLISHER_SHA256 = '864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25'
OLD_GUARD_SHA256 = '1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050'
STAGE_GUARD_SHA256 = '5325f7a81acadb4016385416c88319e4baab0a26974ac19ed17dd7debb7e0f29'
COORDINATOR_SHA256 = '442a90b4c0832ff9fec193865e7fc0a00be32fce002e8728fe49edf413d23fa2'
BINDING_HELPER_SHA256 = 'c564dbdb739f239c8243f3dd38705d73a2998ff11e0757b50899e80503daedc9'
CURRENT_API_APP_SHA256 = '5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5'
READER_SOURCES = {
    'apps/api/v35_api/app.py': 'a51b927e98e23ccdd33a849644abfa544232809aab29c2e7223969cc2308d0b8',
    'stage_center/consumer.py': '16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207',
    'stage_center/execution_evidence.py': '1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b',
    'stage_center/research_read_binding.py': 'c33a1452df34c7dcc7fc96e61b1177079c54c467164b7cb957d773f2d2e0ba05',
}
APPROVED_RESEARCH_RUN = {
    'trade_date': '20261009', 'stage_id': 'STAGE_0930_0935',
    'backfill_run_id': '85e29661ecd848fe9b8344ea59279e86',
    'run_manifest_sha256': '9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857',
    'source_map_sha256': '3ec3e7774119bd106185c03be0b5c572b6fe2ca4148b93379d8b116a72994457',
    'candidate_source_manifest_sha256': '88ca1c64f6e80ec91feff01af2e7e9cf235bb16f91cacff400fede0f56430fa2',
    'selection_run_ids': {'A_SHARE': 'run-2688466a1ae4464ba7237f0b',
                          'HK_CONNECT': 'run-cfbdc9b36a7308da178d193a'},
}
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False,
         'buy_gate_updated': False, 'orders_sent': False}
CONFIRM_EXECUTE = 'SWITCH_API_ONLY_TO_STAGE_RESEARCH_R4_20261009'
CONFIRM_ROLLBACK = 'ROLLBACK_STAGE_RESEARCH_R4_TO_RECORDED_PREIMAGE'
DEFAULT_PUBLISHER = Path('/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py')
_BUNDLED_PUBLISHER = Path(__file__).resolve().parents[1] / 'test_support/publication/api_only_cutover_issue32_r4.py'
if _BUNDLED_PUBLISHER.is_file():
    DEFAULT_PUBLISHER = _BUNDLED_PUBLISHER
_MODULES = {}
_SELF_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_HISTORY_LANE_KEYS = ('market', 'run_id', 'artifact_id', 'algorithm_sha256', 'raw_artifact_sha256',
    'selection_status', 'source_status', 'source_rows', 'requested_rows', 'selected_rows', 'observation_count')
_ROW_KEYS = ('code', 'symbol', 'name', 'market', 'rank', 'score', 'selection_rank', 'source_mode',
             'trade_date', 'stage_id', 'action_level', 'trade_status', 'formal_eligible', 'status')


class PublicationFailure(ValueError):
    """A failed attempt with machine-readable continuation evidence."""

    def __init__(self, message, context):
        super().__init__(message)
        self.context = context


def _check(condition, code):
    if not condition:
        raise ValueError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    _check(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'EXACT_SHA256_REQUIRED')
    return value


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _object(raw, label):
    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result, label + '_DUPLICATE_KEY')
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(label + '_NONFINITE')))
    _check(isinstance(result, dict), label + '_OBJECT_REQUIRED')
    return result


def _path(value, *, directory=False):
    path = Path(value)
    _check(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_UNALIASED_PATH_REQUIRED')
    _check(not any(p.is_symlink() for p in (path, *path.parents)), 'SYMLINK_PATH_REJECTED')
    if directory:
        _check(path.is_dir(), 'DIRECTORY_REQUIRED')
    return path


def _read(value):
    path = _path(value)
    before = path.lstat()
    _check(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 16 * 1024 * 1024,
           'REGULAR_BOUNDED_SINGLE_LINK_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        _check((info.st_dev, info.st_ino) == (before.st_dev, before.st_ino), 'FILE_CHANGED_DURING_OPEN')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        _check((info.st_size, info.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
               and len(raw) <= 16 * 1024 * 1024, 'FILE_CHANGED_DURING_READ')
    finally:
        os.close(fd)
    _path(path)
    _check((path.lstat().st_dev, path.lstat().st_ino) == (before.st_dev, before.st_ino), 'FILE_REPLACED_DURING_READ')
    return raw


def _pinned(path, digest):
    raw = _read(path)
    _check(_sha(raw) == _digest(digest), 'PINNED_FILE_SHA_MISMATCH:' + Path(path).name)
    return raw


def _module(path, digest, name):
    path = _path(path); raw = _pinned(path, digest)
    key = (str(path), digest)
    if key not in _MODULES:
        module = types.ModuleType(name + '_' + uuid.uuid4().hex)
        module.__file__ = str(path)
        sys.modules[module.__name__] = module
        try:
            exec(compile(raw, str(path), 'exec'), module.__dict__)
        except BaseException:
            sys.modules.pop(module.__name__, None)
            raise
        _MODULES[key] = module
    return _MODULES[key]


def _load_publisher(path):
    return _module(path, PUBLISHER_SHA256, '_stage_original_publisher')


def _safe_flags(value):
    _check(all(value.get(key) is expected for key, expected in FLAGS.items()), 'RESEARCH_SAFETY_FLAGS_INVALID')


def _tree_flags(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'production_allowed', 'buy_gate_updated', 'orders_sent'}:
                _check(item is False, 'UNSAFE_HTTP_FLAG')
            if key in {'natural_verified', 'execution_verified'}:
                _check(item is False, 'RESEARCH_CANNOT_ASSERT_EXECUTION_OR_NATURAL')
            _tree_flags(item)
    elif isinstance(value, list):
        for item in value:
            _tree_flags(item)


def _financial_tree_flags(value):
    """Historical natural/execution evidence retains its original meaning."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'production_allowed', 'buy_gate_updated', 'orders_sent'}:
                _check(item is False, 'HISTORICAL_FINANCIAL_SAFETY_CHANGED')
            if key == 'RESEARCH_ONLY' and item is not None:
                _check(item is True, 'HISTORICAL_RESEARCH_FLAG_CHANGED')
            _financial_tree_flags(item)
    elif isinstance(value, list):
        for item in value:
            _financial_tree_flags(item)


def _roots(publisher, raw):
    value = plistlib.loads(raw)
    _, env, command = publisher._split_env_arguments(value)
    other = value.get('EnvironmentVariables', {})
    _check(isinstance(other, dict), 'PLIST_ENVIRONMENT_INVALID')
    _check(all(key not in env or env[key] == item for key, item in other.items()), 'PLIST_ENVIRONMENT_PRODUCERS_DISAGREE')
    env = {**other, **env}
    roots = []
    for i, item in enumerate(command):
        if item == '--stage-selection-root':
            _check(i + 1 < len(command), 'STAGE_ROOT_VALUE_MISSING'); roots.append(command[i + 1])
        elif isinstance(item, str) and item.startswith('--stage-selection-root='):
            roots.append(item.split('=', 1)[1])
    _check(len(roots) == 1, 'EXACT_STAGE_SELECTION_ROOT_REQUIRED')
    history = _path(roots[0], directory=True)
    manager = _path(env.get('V4_MANAGER_RESEARCH_STATE_ROOT', ''), directory=True)
    _check(manager == publisher.FORMAL_MANAGER_STATE, 'CURRENT_MANAGER_ROOT_MISMATCH')
    _check(all(env.get(key) == expected for key, expected in publisher.SAFETY_EXPECTED.items()), 'PLIST_SAFETY_INVALID')
    return history, manager


def _preserved_plist(publisher, before_raw, target):
    value = plistlib.loads(before_raw)
    _check(value.get('Label') == publisher.LABEL and value.get('KeepAlive') is True
           and value.get('RunAtLoad') is False, 'LAUNCH_AGENT_POLICY_MISMATCH')
    prefix, environment, command = publisher._split_env_arguments(value)
    replacements = {'V35_APP_ROOT': target['app_root'], 'V35_RELEASE_ID': target['release_id'],
        'V35_RELEASE_MANIFEST_PATH': str(Path(target['release_root']) / 'release-manifest.json'),
        'V35_RELEASE_MANIFEST_SHA256': target['release_manifest_sha256'],
        'PYTHONPATH': target['app_root'] + '/upstreams:' + target['app_root']}
    _check(set(replacements).issubset(environment), 'RELEASE_IDENTITY_KEYS_MISSING')
    _check(value.get('WorkingDirectory') == environment['V35_APP_ROOT'], 'CURRENT_WORKING_DIRECTORY_MISMATCH')
    after = deepcopy(value)
    after['ProgramArguments'] = ['/usr/bin/env', *[key + '=' + replacements.get(key, environment[key]) for key in prefix], *command]
    if 'EnvironmentVariables' in after:
        for key in replacements:
            if key in after['EnvironmentVariables']:
                after['EnvironmentVariables'][key] = replacements[key]
    after['WorkingDirectory'] = target['app_root']
    _check(_roots(publisher, before_raw) == _roots(publisher, plistlib.dumps(after)), 'RUNTIME_ROOT_CHANGED')
    return after


def _history(root):
    root = _path(root, directory=True)
    raw = _read(root / 'selection_latest.json'); latest = _object(raw, 'SELECTION_LATEST')
    entries = latest.get('entries'); _check(isinstance(entries, dict), 'SELECTION_LATEST_ENTRIES_REQUIRED')
    dates = sorted(p.name for p in (root / 'selection_runs').iterdir()
                   if re.fullmatch('[0-9]{8}', p.name) and _path(p, directory=True))
    pairs = set()
    target = (APPROVED_RESEARCH_RUN['trade_date'], APPROVED_RESEARCH_RUN['stage_id'])
    for row in entries.values():
        day, stage = row.get('trade_date'), row.get('stage_id')
        _check(isinstance(day, str) and re.fullmatch('[0-9]{8}', day)
               and isinstance(stage, str) and re.fullmatch('STAGE_[0-9]{4}_[0-9]{4}', stage), 'HISTORICAL_SELECTION_IDENTITY_INVALID')
        if (day, stage) != target:
            pairs.add((day, stage))
    _check(dates and pairs, 'HISTORICAL_SELECTIONS_REQUIRED')
    _check(set(dates) - {target[0]} <= {day for day, stage in pairs}, 'HISTORICAL_DATE_WITHOUT_READBACK_PAIR')
    return {'root': str(root), 'selection_latest_sha256': _sha(raw), 'selection_dates': dates,
            'pairs': [list(pair) for pair in sorted(pairs)]}


def _request(publisher, day, stage):
    query = '/api/v3/workbench/stage?' + urlencode({'date': day, 'stage': stage, 'limit': 50})
    status, raw = publisher._http_get(query)
    _check(status == 200, 'STAGE_HTTP_STATUS:' + str(status))
    return _object(raw, 'STAGE_HTTP')


def _history_semantics(payload):
    _check(all(payload.get(key) is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent')),
           'HISTORICAL_FINANCIAL_SAFETY_CHANGED')
    _financial_tree_flags(payload)
    markets = payload.get('markets')
    _check(isinstance(markets, dict) and set(markets) == {'A', 'HK'}, 'HISTORY_MARKET_BOUNDARY_INVALID')
    return {'trade_date': payload.get('trade_date'), 'stage_id': payload.get('stage_id'),
        'financial_flags': {key: {'present': key in payload, 'value': payload.get(key)} for key in FLAGS},
        'markets': {market: {**{key: lane.get(key) for key in _HISTORY_LANE_KEYS},
            'rows': [{key: row.get(key) for key in _ROW_KEYS} for row in lane.get('rows', [])]}
            for market, lane in markets.items()}}


def _history_http(publisher, history):
    records = []
    for day, stage in history['pairs']:
        value = _history_semantics(_request(publisher, day, stage))
        _check(value['trade_date'] == day and value['stage_id'] == stage, 'HISTORY_RESPONSE_DATE_STAGE_MISMATCH')
        records.append({'trade_date': day, 'stage_id': stage, 'semantic_sha256': _sha(_json(value))})
    return records


def _binding(publisher, plan):
    app = Path(plan['target']['app_root']); history = Path(plan['history']['root'])
    raw = _read(app / 'stage_center/approved_research_read.json')
    sidecar = _read(app / 'stage_center/approved_research_read.sha256')
    _check(sidecar == (_sha(raw) + '\n').encode('ascii'), 'BINDING_SIDECAR_INVALID')
    document = _object(raw, 'APPROVED_BINDING'); _safe_flags(document)
    _check(document.get('reader_sources') == READER_SOURCES, 'READER_SOURCE_PINS_INVALID')
    for name, digest in READER_SOURCES.items():
        _pinned(app / name, digest)
    for key, value in APPROVED_RESEARCH_RUN.items():
        if key == 'selection_run_ids':
            _check({k: v.get('run_id') for k, v in document.get('markets', {}).items()} == value, 'APPROVED_RUN_IDS_MISMATCH')
        else:
            _check(document.get(key) == value, 'APPROVED_RESEARCH_IDENTITY_MISMATCH:' + key)
    helper = _module(Path(plan['source']['binding_helper_path']), BINDING_HELPER_SHA256, '_stage_binding_verifier')
    command = [str(publisher.PINNED_PYTHON), '-I', '-B', '-c', helper._BUILD,
        plan['api_release_integration']['base']['app_root'], str(app), document['manifest_path'], str(history)]
    child = subprocess.run(command, cwd=app, capture_output=True, text=True, timeout=90)
    _check(child.returncode == 0, 'RESEARCH_BINDING_REVERIFICATION_FAILED:' +
           (child.stderr.strip().splitlines()[-1] if child.stderr.strip() else 'NO_DETAIL'))
    _check(_object(child.stdout, 'REBUILT_BINDING') == document, 'RESEARCH_BINDING_DOCUMENT_MISMATCH')
    rows = {}; envelopes = {}
    for market, evidence in document['markets'].items():
        relative = PurePosixPath(evidence['manifest_relative'])
        _check(not relative.is_absolute() and '..' not in relative.parts, 'SELECTION_MANIFEST_PATH_INVALID')
        manifest = _object(_pinned(Path(document['selection_root']) / relative,
                                  evidence['manifest_bytes_sha256']), 'SELECTION_MANIFEST')
        envelope = manifest['selection_envelope']
        rows[market] = envelope['rows']
        envelopes[market] = {key: envelope.get(key) for key in ('trade_date', 'stage_id', 'market',
            'run_id', 'artifact_id', 'algorithm_id', 'algorithm_sha256', 'raw_artifact_sha256',
            'requested_rows', 'source_rows', 'selected_rows', 'source_status', 'selection_status', 'source_evidence')}
    return {'path': str(app / 'stage_center/approved_research_read.json'), 'sha256': _sha(raw),
            'document': document, 'rows': rows, 'envelopes': envelopes}


def _static(guard, app):
    records = []
    for row in guard.inventory_tree(app / 'apps/web/dist'):
        relative = row['path']
        url = '/' if relative == 'index.html' else ('/' + relative[:-10] if relative.endswith('/index.html') else '/' + relative)
        records.append({'path': relative, 'url': url, 'sha256': row['sha256']})
    _check({'index.html', 'manager-selection/index.html'} <= {row['path'] for row in records}, 'REQUIRED_STATIC_ENTRIES_MISSING')
    return records


def _stage_verify(publisher, guard, plan, *, lease=None, active_pointer='base'):
    if lease is not None:
        publisher._require_release_lock(lease)
    result = guard.verify_api_release_candidate(candidate_root=Path(plan['target']['release_root']),
        active_api_plist_path=publisher.ACTIVE_API_PLIST,
        expected_manifest_sha256=plan['target']['release_manifest_sha256'], active_pointer=active_pointer)
    if lease is not None:
        publisher._require_release_lock(lease)
    _check(result['shared_lock_path'] == str(publisher.ACTIVE_API_PLIST.with_name('.com.lexi.v35.api-only.release.lock')),
           'SHARED_LOCK_PATH_MISMATCH')
    expected_pointer = (plan['before']['active_api_plist_sha256'] if active_pointer == 'base'
                        else plan['target']['staged_api_plist_sha256'])
    _check(result.get('active_api_plist_sha256') == expected_pointer, 'ACTIVE_POINTER_PLAN_SHA_MISMATCH')
    return result


def _sources(plan, *, require_candidate_tools=True):
    _check(plan['source']['wrapper_sha256'] == _SELF_SHA256, 'PUBLICATION_WRAPPER_LOADED_SHA_MISMATCH')
    _pinned(Path(__file__).absolute(), _SELF_SHA256)
    publisher = _load_publisher(Path(plan['source']['publisher_path']))
    _check(plan['source']['publisher_sha256'] == PUBLISHER_SHA256
           and publisher.INTEGRATION_GUARD_SHA256 == OLD_GUARD_SHA256, 'ORIGINAL_PUBLICATION_IDENTITY_MISMATCH')
    _pinned(publisher.INTEGRATION_GUARD_PATH, OLD_GUARD_SHA256)
    if require_candidate_tools:
        _pinned(plan['source']['preparation_receipt_path'], plan['source']['preparation_receipt_sha256'])
        _pinned(plan['source']['preserving_plan_path'], plan['source']['preserving_plan_sha256'])
        _pinned(plan['source']['coordinator_path'], COORDINATOR_SHA256)
        guard = _module(Path(plan['source']['stage_guard_path']), STAGE_GUARD_SHA256, '_stage_publication_guard')
        _check(plan['source']['stage_guard_sha256'] == STAGE_GUARD_SHA256, 'STAGE_GUARD_PLAN_PIN_INVALID')
        return publisher, guard
    return publisher, None


def _plan(path, expected):
    path = _path(path); raw = _pinned(path, expected); plan = _object(raw, 'PUBLICATION_PLAN')
    _check(plan.get('schema_version') == SCHEMA and plan.get('plan_path') == str(path), 'PUBLICATION_PLAN_IDENTITY_INVALID')
    _safe_flags(plan)
    root = _path(plan['publication_root'], directory=True)
    _check(path == root / 'verified-publication-plan.json'
           and plan.get('operation_root') == str(root / 'operations'), 'PUBLICATION_OUTPUT_BOUNDARY_INVALID')
    _check(plan.get('activation_status') == 'NOT_ACTIVATED' and plan.get('automatic_activation') is False,
           'PUBLICATION_PLAN_ACTIVATION_INVALID')
    return plan


def _preflight(plan, plan_path, plan_sha, *, lease=None):
    _check(_plan(plan_path, plan_sha) == plan, 'PUBLICATION_PLAN_CHANGED')
    publisher, guard = _sources(plan)
    if lease is not None:
        publisher._require_release_lock(lease)
    before_raw = _pinned(publisher.ACTIVE_API_PLIST, plan['before']['active_api_plist_sha256'])
    _check(publisher._file_metadata(publisher.ACTIVE_API_PLIST) == plan['before']['active_api_plist_metadata'],
           'API_PLIST_METADATA_CHANGED')
    staged_raw = _pinned(plan['target']['staged_api_plist_path'], plan['target']['staged_api_plist_sha256'])
    _check(plistlib.loads(staged_raw) == _preserved_plist(publisher, before_raw, plan['target']), 'STAGED_PLIST_PRESERVATION_MISMATCH')
    loaded = publisher._observe_loaded()
    _check(loaded.get('state') == 'LOADED' and loaded.get('identity') == plan['before']['loaded_identity'], 'LOADED_BASE_IDENTITY_CHANGED')
    integration = _stage_verify(publisher, guard, plan, lease=lease)
    _check(integration == plan['api_release_integration'], 'CANDIDATE_INTEGRATION_CHANGED')
    _check(_history(plan['history']['root']) == plan['history'], 'STAGE_HISTORY_CHANGED')
    _check(_binding(publisher, plan) == plan['research_binding'], 'RESEARCH_BINDING_CHANGED')
    _check(_static(guard, Path(plan['target']['app_root'])) == plan['static_http'], 'CANDIDATE_STATIC_CHANGED')
    readonly = publisher._verify_readonly_guards(plan)
    _check(_history_http(publisher, plan['history']) == plan['historical_http'], 'HISTORICAL_STAGE_READBACK_CHANGED')
    _check(_plan(plan_path, plan_sha) == plan, 'PUBLICATION_PLAN_CHANGED')
    if lease is not None:
        publisher._require_release_lock(lease)
    return publisher, guard, integration, readonly


def prepare_stage_publication(*, preparation_receipt, expected_preparation_sha256,
                              publisher_path=DEFAULT_PUBLISHER, stage_guard_path):
    receipt_path = _path(preparation_receipt)
    receipt = _object(_pinned(receipt_path, expected_preparation_sha256), 'PREPARATION_RECEIPT')
    _safe_flags(receipt)
    _check(receipt.get('schema_version') == 'V4_STAGE_LIVE_RELEASE_PREPARATION_V1'
           and receipt.get('status') == 'CANDIDATE_READY_NOT_DEPLOYED' and receipt.get('deployed') is False,
           'PREPARED_RELEASE_REQUIRED')
    destination = _path(receipt['destination'], directory=True)
    _check(receipt_path == destination / 'PREPARATION_RECEIPT.json', 'PREPARATION_RECEIPT_PATH_INVALID')
    root = _path(destination / 'stage-publication', directory=True)
    plan_path = root / 'verified-publication-plan.json'
    _check(not os.path.lexists(plan_path), 'PUBLICATION_PLAN_ALREADY_EXISTS')
    prepared_path = root / 'api-only-preserved-plan.json'
    _check(receipt['prepared_plan_path'] == str(prepared_path), 'PRESERVING_PLAN_PATH_INVALID')
    prepared = _object(_pinned(prepared_path, receipt['prepared_plan_sha256']), 'PRESERVING_PLAN')
    _safe_flags(prepared)
    _check(prepared.get('schema_version') == 'V4_STAGE_PRESERVED_API_PREPARATION_V1'
           and prepared.get('status') == 'PREPARED_NOT_DEPLOYED' and prepared.get('launchctl_called') is False,
           'PRESERVING_PLAN_REQUIRED')
    publisher = _load_publisher(_path(publisher_path))
    guard_path = _path(stage_guard_path)
    _check(guard_path == Path(receipt['package']) / 'release_tools/after/ops/api_release_integration.py', 'STAGE_GUARD_PACKAGE_PATH_MISMATCH')
    guard = _module(guard_path, STAGE_GUARD_SHA256, '_stage_publication_guard')
    before_raw = _pinned(publisher.ACTIVE_API_PLIST, prepared['source_plist']['sha256'])
    _check(prepared['source_plist']['path'] == str(publisher.ACTIVE_API_PLIST), 'PREPARED_POINTER_PATH_MISMATCH')
    history, manager = _roots(publisher, before_raw)
    _check(not root.is_relative_to(history) and not root.is_relative_to(manager), 'PUBLICATION_OVERLAPS_STATE')
    target = {'release_root': receipt['candidate_root'], 'app_root': receipt['candidate_app'],
        'release_id': prepared['release_id'], 'release_manifest_sha256': receipt['manifest_sha256'],
        'staged_api_plist_path': receipt['staged_api_plist_path'],
        'staged_api_plist_sha256': receipt['staged_api_plist_sha256'],
        'application_inventory_sha256': receipt['verification']['candidate']['application_inventory_sha256']}
    _check(Path(target['release_root']).parent == destination / 'candidate'
           and target['app_root'] == str(Path(target['release_root']) / 'app'), 'CANDIDATE_OUTPUT_BOUNDARY_INVALID')
    _check(prepared['candidate_root'] == target['release_root']
           and prepared['candidate_manifest'] == {'path': receipt['manifest_path'], 'sha256': target['release_manifest_sha256']}
           and prepared['candidate_plist'] == {'path': target['staged_api_plist_path'], 'sha256': target['staged_api_plist_sha256']}
           and Path(target['staged_api_plist_path']) == root / 'com.lexi.v35.api-only.plist', 'PREPARED_CANDIDATE_IDENTITY_MISMATCH')
    staged_raw = _pinned(target['staged_api_plist_path'], target['staged_api_plist_sha256'])
    _check(plistlib.loads(staged_raw) == _preserved_plist(publisher, before_raw, target), 'STAGED_PLIST_PRESERVATION_MISMATCH')
    observation = publisher._observe_loaded()
    _check(observation.get('state') == 'LOADED' and observation['identity'].get('pid')
           and publisher._identity_matches(observation['identity'], {'state': 'running', **publisher._identity_from_plist(before_raw)}),
           'CURRENT_API_RUNTIME_IDENTITY_UNVERIFIED')
    source = {'publisher_path': str(publisher_path), 'publisher_sha256': PUBLISHER_SHA256,
        'stage_guard_path': str(guard_path), 'stage_guard_sha256': STAGE_GUARD_SHA256,
        'preparation_receipt_path': str(receipt_path), 'preparation_receipt_sha256': expected_preparation_sha256,
        'preserving_plan_path': str(prepared_path), 'preserving_plan_sha256': receipt['prepared_plan_sha256'],
        'coordinator_path': str(Path(receipt['package']) / 'tools/prepare_live_release.py'),
        'binding_helper_path': str(Path(receipt['package']) / 'tools/prepare_research_binding.py'),
        'wrapper_sha256': _SELF_SHA256}
    plan = {'schema_version': SCHEMA, 'activation_status': 'NOT_ACTIVATED', 'automatic_activation': False,
        'plan_path': str(plan_path), 'publication_root': str(root), 'operation_root': str(root / 'operations'),
        'source': source, 'target': target, 'manager_state_root': str(manager), 'history': _history(history),
        'before': {'active_api_plist_path': str(publisher.ACTIVE_API_PLIST),
            'active_api_plist_sha256': _sha(before_raw), 'active_api_plist_metadata': publisher._file_metadata(publisher.ACTIVE_API_PLIST),
            'loaded_identity': observation['identity'],
            'scheduler_plist_sha256': _sha(_read(publisher.ACTIVE_SCHEDULER_PLIST)),
            'stage_center_scheduler_plist_sha256': _sha(_read(publisher.STAGE_CENTER_SCHEDULER_PLIST))},
        'guards': {'disabled_binding_path': str(publisher.DISABLED_BINDING_PATH),
            'disabled_binding_sha256': _sha(_read(publisher.DISABLED_BINDING_PATH))},
        'natural_verified': False, 'execution_verified': False, **FLAGS}
    _sources(plan)
    integration = _stage_verify(publisher, guard, plan)
    _check(integration == receipt['verification'] and integration == prepared['api_release_integration'], 'PREPARATION_INTEGRATION_MISMATCH')
    _pinned(Path(integration['base']['app_root']) / 'apps/api/v35_api/app.py', CURRENT_API_APP_SHA256)
    plan['api_release_integration'] = integration
    publisher._verify_readonly_guards(plan)
    plan['research_binding'] = _binding(publisher, plan)
    plan['static_http'] = _static(guard, Path(target['app_root']))
    plan['historical_http'] = _history_http(publisher, plan['history'])
    _check(_history(history) == plan['history'] and _read(publisher.ACTIVE_API_PLIST) == before_raw,
           'PREPARATION_INPUT_CHANGED')
    raw = _json(plan)
    publisher._write_exclusive(plan_path, raw, mode=0o400)
    publisher._fsync_directory(root)
    _check(_read(plan_path) == raw, 'PUBLICATION_PLAN_WRITEBACK_MISMATCH')
    return {'status': 'STAGE_PUBLICATION_PREPARED_NOT_DEPLOYED', 'plan_path': str(plan_path),
        'plan_sha256': _sha(raw), 'current_plist_sha256': _sha(before_raw),
        'staged_plist_sha256': target['staged_api_plist_sha256'],
        'operation_root': plan['operation_root'], 'deployed': False, 'natural_verified': False, **FLAGS}


def preflight_stage_publication(*, plan_path, expected_plan_sha256):
    plan = _plan(plan_path, expected_plan_sha256)
    _preflight(plan, plan_path, expected_plan_sha256)
    return {'status': 'STAGE_PUBLICATION_PREFLIGHT_PASS', 'deployed': False, 'natural_verified': False,
            'history_dates': len(plan['history']['selection_dates']), **FLAGS}


def _new_operation(plan):
    root = _path(plan['operation_root'])
    if not root.exists():
        root.mkdir(mode=0o700)
    _path(root, directory=True)
    path = root / uuid.uuid4().hex
    path.mkdir(mode=0o700)
    return path


def _after(plan):
    return {key: plan['target'][key] for key in ('release_id', 'app_root', 'release_manifest_sha256',
        'application_inventory_sha256', 'staged_api_plist_path', 'staged_api_plist_sha256')}


def _candidate(plan):
    target = plan['target']
    return {'release_id': target['release_id'], 'release_root': target['release_root'], 'app_root': target['app_root'],
        'manifest_path': str(Path(target['release_root']) / 'release-manifest.json'),
        'manifest_sha256': target['release_manifest_sha256'], 'inventory_sha256': target['application_inventory_sha256']}


def _failure_context(publisher, receipt_path, recovery_status):
    try:
        current = (_sha(_read(publisher.ACTIVE_API_PLIST))
                   if os.path.lexists(publisher.ACTIVE_API_PLIST) else 'ABSENT')
    except (OSError, ValueError):
        current = 'UNAVAILABLE'
    return {'receipt_path': str(receipt_path), 'receipt_sha256': _sha(_read(receipt_path)),
            'observed_current_plist_sha256': current, 'recovery_status': recovery_status}


def _research_http(publisher, plan):
    document = plan['research_binding']['document']
    payload = _request(publisher, document['trade_date'], document['stage_id'])
    _safe_flags(payload); _tree_flags(payload)
    _check(payload.get('mode') == 'BACKFILL' and payload.get('recommendation_status') == 'WATCH_ONLY'
           and payload.get('trade_date') == document['trade_date'] and payload.get('stage_id') == document['stage_id']
           and payload.get('backfill_run_id') == document['backfill_run_id'], 'RESEARCH_HTTP_ENVELOPE_MISMATCH')
    evidence = payload.get('research_read_binding', {})
    _check(evidence.get('status') == 'EXACT_APPROVED_RESEARCH_BINDING_VERIFIED'
           and evidence.get('binding_sha256') == plan['research_binding']['sha256']
           and evidence.get('reader_sources') == READER_SOURCES and evidence.get('history_root_preserved') is True,
           'RESEARCH_HTTP_READER_BINDING_MISMATCH')
    for key in ('run_manifest_sha256', 'source_map_sha256', 'candidate_source_manifest_sha256',
                'owner_receipt_sha256', 'owner_history_sha256'):
        _check(evidence.get(key) == document[key], 'RESEARCH_HTTP_EVIDENCE_MISMATCH:' + key)
    execution = payload.get('execution_evidence', {})
    _safe_flags(execution)
    _check(execution.get('natural_verified') is False and execution.get('execution_verified') is False
           and execution.get('observed_sha256') == document['owner_receipt_sha256']
           and execution.get('receipt_history_binding') == 'OWNER_HISTORY_SHA_BOUND', 'OWNER_RECEIPT_HTTP_BINDING_MISMATCH')
    counts = {}; markets = payload.get('markets', {}); unified_expected = []
    _check(set(markets) == {'A', 'HK'}, 'RESEARCH_HTTP_MARKET_ISOLATION_MISMATCH')
    for wire, market in (('A', 'A_SHARE'), ('HK', 'HK_CONNECT')):
        lane = markets[wire]; bound = document['markets'][market]
        envelope = plan['research_binding']['envelopes'][market]
        expected = {key: bound[key] for key in ('run_id', 'artifact_id', 'algorithm_sha256', 'raw_artifact_sha256')}
        expected.update(selection_artifact_sha256=bound['artifact_bytes_sha256'],
            selection_manifest_sha256=bound['manifest_canonical_sha256'], selection_receipt_sha256=bound['receipt_canonical_sha256'],
            runner_receipt_sha256=document['owner_receipt_sha256'], market=market)
        _check(all(lane.get(key) == value for key, value in expected.items()), 'RESEARCH_HTTP_MARKET_IDENTITY_MISMATCH:' + market)
        _check(all(lane.get(key) == envelope[key] for key in ('algorithm_id', 'requested_rows', 'source_rows',
                   'source_status', 'selection_status')), 'RESEARCH_HTTP_MARKET_COUNTS_OR_STATUS_MISMATCH:' + market)
        _check(lane.get('selection_manifest_receipt_verified') is True and lane.get('runner_receipt_verified') is True,
               'RESEARCH_HTTP_MARKET_EVIDENCE_UNVERIFIED')
        rows = lane.get('rows', []); actual_rows = plan['research_binding']['rows'][market]
        _check(len(rows) == len(actual_rows) == bound['selected_rows'] == 10, 'RESEARCH_HTTP_ROW_COUNT_MISMATCH')
        for row, original in zip(rows, actual_rows):
            _check(row.get('code') == original.get('code') and row.get('rank') == original.get('rank')
                   and row.get('score') == original.get('score'), 'RESEARCH_HTTP_ROW_IDENTITY_MISMATCH')
            unified_expected.append((wire, row.get('code'), row.get('rank'), row.get('score'),
                                     document['trade_date'], document['stage_id']))
        if lane.get('selected_rows') is None:
            _check(wire == 'HK' and lane.get('observation_count') == envelope['selected_rows'], 'RESEARCH_HTTP_OBSERVATION_COUNT_MISMATCH')
        else:
            _check(lane.get('selected_rows') == envelope['selected_rows'], 'RESEARCH_HTTP_SELECTED_COUNT_MISMATCH')
        selected = execution.get('selection_results', {}).get(market, {})
        trio = execution.get('selection_artifact_bindings', {}).get(market, {})
        _check(selected.get('run_id') == bound['run_id'] and selected.get('artifact_id') == bound['artifact_id']
               and selected.get('selected_rows') == 10 and trio.get('run_id') == bound['run_id']
               and trio.get('status') == 'BOUND_TO_VERIFIED_SELECTION_TRIO', 'RESEARCH_HTTP_EXECUTION_SELECTION_MISMATCH')
        _check(all(selected.get(key) == envelope[key] for key in ('trade_date', 'stage_id', 'market',
                   'algorithm_sha256', 'raw_artifact_sha256', 'requested_rows', 'source_rows',
                   'selected_rows', 'selection_status', 'source_evidence')), 'RESEARCH_HTTP_SELECTED_EVIDENCE_MISMATCH:' + market)
        for key in ('artifact_bytes_sha256', 'manifest_bytes_sha256', 'manifest_canonical_sha256',
                    'receipt_bytes_sha256', 'receipt_canonical_sha256'):
            _check(trio.get(key) == bound[key], 'RESEARCH_HTTP_TRIO_SHA_MISMATCH')
        counts[market] = len(rows)
    unified = payload.get('unified_rows')
    _check(isinstance(unified, list) and [(row.get('market'), row.get('code'), row.get('rank'), row.get('score'),
           row.get('trade_date'), row.get('stage_id')) for row in unified] == unified_expected,
           'RESEARCH_HTTP_UNIFIED_ROWS_MISMATCH')
    selected_a, selected_hk = markets['A'].get('selected_rows'), markets['HK'].get('selected_rows')
    total = None if selected_a is None or selected_hk is None else selected_a + selected_hk
    _check(payload.get('selected_a_rows') == selected_a and payload.get('selected_hk_rows') == selected_hk
           and payload.get('selected_total_rows') == total, 'RESEARCH_HTTP_TOP_COUNTS_MISMATCH')
    return {'status': 'EXACT_APPROVED_RESEARCH_HTTP_VERIFIED', 'market_row_counts': counts,
        'binding_sha256': plan['research_binding']['sha256'], 'run_manifest_sha256': document['run_manifest_sha256'],
        'selection_run_ids': {market: row['run_id'] for market, row in document['markets'].items()},
        'execution_verified': False, 'natural_verified': False, **FLAGS}


def _wait_ready(publisher, plan, lease):
    """Wait through launchd/HTTP startup, never through an unknown identity."""
    deadline = publisher.time.monotonic() + 60
    expected = publisher._candidate_runtime_identity(plan)
    polls = 0
    while True:
        publisher._require_release_lock(lease)
        observed = publisher._observe_loaded(); polls += 1
        state = observed.get('state')
        if state == 'LOADED':
            _check(observed['identity'].get('pid') and publisher._identity_matches(observed['identity'], expected),
                   'CANDIDATE_RUNTIME_UNKNOWN_IDENTITY')
            try:
                http = publisher._verify_openapi(require_manager_route=True)
                return observed, {'poll_count': polls, 'openapi': http}
            except (OSError, ValueError) as error:
                message = str(error)
                _check(isinstance(error, OSError) or message.startswith('API_ONLY_HTTP_READBACK_FAILED:')
                       or message in {'API_OPENAPI_HTTP_STATUS:502', 'API_OPENAPI_HTTP_STATUS:503',
                                      'API_OPENAPI_HTTP_STATUS:504'}, 'CANDIDATE_HTTP_SEMANTIC_MISMATCH:' + message)
        else:
            _check(state in {'NOT_LOADED', 'LOADED_UNVERIFIED'}, 'CANDIDATE_RUNTIME_UNKNOWN_STATE')
        remaining = deadline - publisher.time.monotonic()
        _check(remaining > 0, 'CANDIDATE_STARTUP_TIMEOUT')
        publisher.time.sleep(min(0.5, remaining))


def _runtime_verify(publisher, guard, plan, lease):
    publisher._require_release_lock(lease)
    observed, readiness = _wait_ready(publisher, plan, lease)
    _sources(plan)
    _stage_verify(publisher, guard, plan, lease=lease, active_pointer='candidate')
    research = _research_http(publisher, plan)
    for row in plan['static_http']:
        status, raw = publisher._http_get(row['url'])
        _check(status == 200 and _sha(raw) == row['sha256'], 'CANDIDATE_STATIC_HTTP_MISMATCH:' + row['url'])
    history = _history_http(publisher, plan['history'])
    _check(history == plan['historical_http'] and _history(plan['history']['root']) == plan['history'], 'HISTORICAL_STAGE_READBACK_CHANGED')
    publisher._verify_readonly_guards(plan)
    _sources(plan)
    _stage_verify(publisher, guard, plan, lease=lease, active_pointer='candidate')
    publisher._require_release_lock(lease)
    return {'runtime': observed['identity'], 'readiness': readiness, 'research': research,
        'static_http': {'status': 'BYTE_IDENTICAL_TO_REVIEWED_STATIC_TREE', 'verified_files': len(plan['static_http'])},
        'history': {'status': 'HISTORICAL_SELECTION_SEMANTICS_UNCHANGED', 'checked_pairs': len(history),
                    'selection_dates': plan['history']['selection_dates']},
        'browser_verified': False, 'natural_verified': False}


def execute_stage_publication(*, plan_path, expected_plan_sha256, confirmation,
                              expected_current_sha256, expected_staged_sha256):
    _check(confirmation == CONFIRM_EXECUTE, 'EXPLICIT_STAGE_EXECUTE_CONFIRMATION_REQUIRED')
    plan = _plan(plan_path, expected_plan_sha256)
    _check(expected_current_sha256 == plan['before']['active_api_plist_sha256']
           and expected_staged_sha256 == plan['target']['staged_api_plist_sha256'], 'EXPECTED_POINTER_SHA_ARGUMENT_MISMATCH')
    publisher, _ = _sources(plan)
    with publisher._switch_lock() as lease:
        publisher, guard, integration, readonly = _preflight(plan, plan_path, expected_plan_sha256, lease=lease)
        source_raw = _pinned(publisher.ACTIVE_API_PLIST, expected_current_sha256)
        staged_raw = _pinned(plan['target']['staged_api_plist_path'], expected_staged_sha256)
        operation = _new_operation(plan); backup = operation / 'active_api_only.preimage.plist'
        publisher._write_exclusive(backup, source_raw, mode=plan['before']['active_api_plist_metadata']['mode'])
        publisher._apply_file_metadata(publisher.ACTIVE_API_PLIST, backup)
        metadata = publisher._file_metadata(backup)
        _check(metadata == plan['before']['active_api_plist_metadata'], 'BACKUP_METADATA_MISMATCH')
        details = {'before': plan['before'], 'after': _after(plan), 'candidate_release': _candidate(plan),
            'api_release_integration': {**integration, 'shared_lock_required': True,
                'guard_path': plan['source']['stage_guard_path'], 'guard_sha256': STAGE_GUARD_SHA256,
                'lease_authority': 'UNCHANGED_ISSUE32_PUBLISHER_AND_ISSUE30_GUARD'},
            'backup_path': str(backup), 'backup_sha256': expected_current_sha256, 'backup_metadata': metadata,
            'scheduler_preimage_sha256': readonly['scheduler_plist_sha256'],
            'stage_center_scheduler_preimage_sha256': readonly['stage_center_scheduler_plist_sha256'],
            'disabled_binding_sha256': readonly['disabled_binding_sha256']}
        transaction = publisher._create_prepared_transaction(plan, operation, details, lock_lease=lease)
        receipt_path = operation / 'operation_receipt.json'
        publisher._record(receipt_path, 'PREPARED', {}, prepared_transaction=transaction)
        bootout_started = False
        try:
            _preflight(plan, plan_path, expected_plan_sha256, lease=lease)
            publisher._assert_prepared_transaction(transaction, lease)
            publisher._verify_recovery_backup(plan, backup, source_raw, metadata, integration['base'], lock_lease=lease)
            publisher._require_release_lock(lease)
            bootout_started = True
            publisher._launchctl_action('bootout')
            absence = publisher._wait_for_unloaded([plan['before']['loaded_identity']], timeout_s=30)
            _check(absence.get('wait_status') == 'ABSENT_CONFIRMED', 'BOOTOUT_ABSENCE_NOT_CONFIRMED')
            _check(_plan(plan_path, expected_plan_sha256) == plan, 'PUBLICATION_PLAN_CHANGED')
            _sources(plan)
            _pinned(publisher.ACTIVE_API_PLIST, expected_current_sha256)
            publisher._verify_readonly_guards(plan)
            _check(_stage_verify(publisher, guard, plan, lease=lease) == integration, 'CANDIDATE_CHANGED_BEFORE_POINTER_WRITE')
            _check(_binding(publisher, plan) == plan['research_binding'] and _history(plan['history']['root']) == plan['history'],
                   'RESEARCH_OR_HISTORY_CHANGED_BEFORE_POINTER_WRITE')
            _pinned(plan['target']['staged_api_plist_path'], expected_staged_sha256)
            publisher._assert_prepared_transaction(transaction, lease)
            publisher._atomic_replace_bytes(publisher.ACTIVE_API_PLIST, staged_raw, publisher.ACTIVE_API_PLIST,
                                            expected_current_sha=expected_current_sha256, lock_lease=lease)
            publisher._require_release_lock(lease)
            publisher._launchctl_action('bootstrap')
            verification = _runtime_verify(publisher, guard, plan, lease)
            _check(_plan(plan_path, expected_plan_sha256) == plan, 'PUBLICATION_PLAN_CHANGED')
            publisher._assert_prepared_transaction(transaction, lease)
            final = publisher._record(receipt_path, 'STAGE_API_SWITCHED_AND_READBACK_VERIFIED',
                {'runtime_verification': verification, 'after': {**_after(plan), 'loaded_identity': verification['runtime']},
                 'bootout_absence_verification': absence,
                 'deployed': True, 'natural_verified': False, 'browser_verified': False}, prepared_transaction=transaction)
            return {'status': final['status'], 'receipt_path': str(receipt_path),
                'receipt_sha256': _sha(_read(receipt_path)), 'receipt_content_sha256': final['receipt_sha256'],
                'runtime_verification': verification, 'deployed': True, 'natural_verified': False, **FLAGS}
        except Exception as error:
            if not bootout_started:
                publisher._record(receipt_path, 'ABORTED_BEFORE_BOOTOUT', {'reason': str(error)}, prepared_transaction=transaction)
                raise PublicationFailure(str(error), _failure_context(publisher, receipt_path, 'ABORTED_BEFORE_BOOTOUT')) from error
            recovery = publisher._restore_after_failure(plan, backup, source_raw, expected_staged_sha256,
                operation, str(error), metadata, lock_lease=lease, base_record=integration['base'],
                prepared_transaction=transaction)
            if recovery.get('status') != 'ROLLED_BACK_TO_PREIMAGE':
                raise PublicationFailure('STAGE_SWITCH_FAILED_ROLLBACK_INCOMPLETE:' + str(recovery.get('reason')),
                    _failure_context(publisher, receipt_path, 'ROLLBACK_INCOMPLETE')) from error
            raise PublicationFailure('STAGE_SWITCH_FAILED_AND_ROLLED_BACK:' + str(error),
                _failure_context(publisher, receipt_path, 'ROLLED_BACK_TO_PREIMAGE')) from error


def _continuation(publisher, plan, receipt_path, receipt_sha, lease):
    publisher._require_release_lock(lease)
    root = _path(plan['operation_root'], directory=True)
    receipt_path = _path(receipt_path)
    _check(receipt_path.name == 'operation_receipt.json' and receipt_path.parent.parent == root,
           'ROLLBACK_RECEIPT_OUTSIDE_PUBLICATION_ROOT')
    _pinned(receipt_path, receipt_sha)
    receipt, observed_sha = publisher._signed_receipt(receipt_path, 'STAGE_ROLLBACK_RECEIPT')
    _check(all(receipt.get(key) is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent')),
           'ROLLBACK_RECEIPT_SAFETY_INVALID')
    _financial_tree_flags(receipt)
    allowed = {'PREPARED', 'ABORTED_BEFORE_BOOTOUT', 'STAGE_API_SWITCHED_AND_READBACK_VERIFIED',
               'ROLLBACK_INCOMPLETE', 'ROLLED_BACK_TO_PREIMAGE'}
    _check(receipt.get('schema_version') == publisher.RECEIPT_SCHEMA and receipt.get('status') in allowed,
           'ROLLBACK_RECEIPT_IDENTITY_INVALID')
    _check(receipt.get('active_api_plist') == str(publisher.ACTIVE_API_PLIST) and receipt.get('active_label') == publisher.LABEL,
           'ROLLBACK_RECEIPT_POINTER_MISMATCH')
    reference = receipt.get('prepared_receipt')
    _check(isinstance(reference, dict) and set(reference) == {'path', 'sha256'}, 'PREPARED_REFERENCE_REQUIRED')
    prepared_path = _path(reference['path'])
    _check(prepared_path.name == 'prepared_receipt.json' and prepared_path.parent.parent == root, 'PREPARED_RECEIPT_OUTSIDE_OPERATION_ROOT')
    _pinned(prepared_path, reference['sha256'])
    prepared, prepared_sha = publisher._signed_receipt(prepared_path, 'STAGE_PREPARED_RECEIPT')
    _check(all(prepared.get(key) is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent')),
           'PREPARED_RECEIPT_SAFETY_INVALID')
    _financial_tree_flags(prepared)
    _check(prepared.get('status') == 'PREPARED' and prepared.get('schema_version') == publisher.RECEIPT_SCHEMA
           and prepared.get('active_api_plist') == str(publisher.ACTIVE_API_PLIST) and prepared.get('active_label') == publisher.LABEL
           and prepared.get('plan_sha256') == publisher._canonical_sha(plan)
           and prepared.get('origin_operation_dir') == str(prepared_path.parent)
           and prepared.get('backup_path') == str(prepared_path.parent / 'active_api_only.preimage.plist'), 'PREPARED_PLAN_OR_ORIGIN_MISMATCH')
    for key in publisher._PREPARED_CONTRACT_KEYS:
        _check(key in receipt and publisher._contract_value_matches(key, receipt[key], prepared), 'PREPARED_CONTRACT_MISMATCH:' + key)
    _check(prepared.get('before') == plan['before'] and prepared.get('after') == _after(plan)
           and prepared.get('candidate_release') == _candidate(plan)
           and prepared.get('backup_sha256') == plan['before']['active_api_plist_sha256']
           and prepared.get('backup_metadata') == plan['before']['active_api_plist_metadata'], 'PREPARED_RELEASE_BINDING_MISMATCH')
    expected_integration = {**plan['api_release_integration'], 'shared_lock_required': True,
        'guard_path': plan['source']['stage_guard_path'], 'guard_sha256': STAGE_GUARD_SHA256,
        'lease_authority': 'UNCHANGED_ISSUE32_PUBLISHER_AND_ISSUE30_GUARD'}
    _check(prepared.get('api_release_integration') == expected_integration, 'PREPARED_INTEGRATION_BINDING_MISMATCH')
    _check(prepared.get('scheduler_preimage_sha256') == plan['before']['scheduler_plist_sha256']
           and prepared.get('stage_center_scheduler_preimage_sha256') == plan['before']['stage_center_scheduler_plist_sha256']
           and prepared.get('disabled_binding_sha256') == plan['guards']['disabled_binding_sha256'], 'PREPARED_READONLY_GUARDS_MISMATCH')
    transaction = {'record': prepared, 'reference': dict(reference),
        'source_receipt_path': str(receipt_path), 'source_receipt_sha256': observed_sha}
    publisher._assert_prepared_transaction(transaction, lease)
    return receipt, transaction


def rollback_stage_publication(*, plan_path, expected_plan_sha256, receipt_path,
                               expected_receipt_sha256, confirmation, expected_current_sha256):
    _check(confirmation == CONFIRM_ROLLBACK, 'EXPLICIT_STAGE_ROLLBACK_CONFIRMATION_REQUIRED')
    plan = _plan(plan_path, expected_plan_sha256)
    publisher, _ = _sources(plan, require_candidate_tools=False)
    with publisher._switch_lock() as lease:
        receipt, transaction = _continuation(publisher, plan, receipt_path, expected_receipt_sha256, lease)
        prepared = transaction['record']; backup = Path(prepared['backup_path'])
        original = _pinned(backup, plan['before']['active_api_plist_sha256'])
        publisher._verify_recovery_backup(plan, backup, original, prepared['backup_metadata'],
            prepared['api_release_integration']['base'], lock_lease=lease)
        publisher._verify_readonly_guards(plan)
        publisher._recovery_state(plan, plan['target']['staged_api_plist_sha256'],
            expected_current_sha=expected_current_sha256, wait_for_transition=True)
        _check(_plan(plan_path, expected_plan_sha256) == plan, 'PUBLICATION_PLAN_CHANGED')
        transaction['expected_current_sha'] = expected_current_sha256
        operation = _new_operation(plan)
        publisher._record(operation / 'operation_receipt.json', 'PREPARED', {}, prepared_transaction=transaction)
        result = publisher._restore_after_failure(plan, backup, original, plan['target']['staged_api_plist_sha256'],
            operation, 'OPERATOR_REQUESTED_STAGE_ROLLBACK', prepared['backup_metadata'], lock_lease=lease,
            base_record=prepared['api_release_integration']['base'], prepared_transaction=transaction,
            expected_current_sha=expected_current_sha256)
        result['receipt_content_sha256'] = result['receipt_sha256']
        result['receipt_sha256'] = _sha(_read(result['receipt_path']))
        result.update(_failure_context(publisher, result['receipt_path'], result['status']))
        result.update(natural_verified=False, execution_verified=False, **FLAGS)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--preparation-receipt', type=Path, required=True)
    prepare.add_argument('--expected-preparation-sha256', required=True)
    prepare.add_argument('--publisher-path', type=Path, default=DEFAULT_PUBLISHER)
    prepare.add_argument('--stage-guard-path', type=Path, required=True)
    for name in ('plan', 'preflight', 'execute', 'rollback'):
        command = sub.add_parser(name)
        command.add_argument('--plan-path', type=Path, required=True)
        command.add_argument('--expected-plan-sha256', required=True)
        if name in {'execute', 'rollback'}:
            command.add_argument('--confirmation', required=True)
            command.add_argument('--expected-current-sha256', required=True)
        if name == 'execute':
            command.add_argument('--expected-staged-sha256', required=True)
        if name == 'rollback':
            command.add_argument('--receipt-path', type=Path, required=True)
            command.add_argument('--expected-receipt-sha256', required=True)
    args = vars(parser.parse_args(argv)); action = args.pop('command')
    try:
        if action == 'plan':
            plan = _plan(args['plan_path'], args['expected_plan_sha256'])
            result = {'status': 'PLANNED_NOT_DEPLOYED', 'target': plan['target'],
                'history_root': plan['history']['root'], 'manager_state_root': plan['manager_state_root'],
                'operation_root': plan['operation_root'], 'deployed': False, 'natural_verified': False, **FLAGS}
        else:
            result = {'prepare': prepare_stage_publication, 'preflight': preflight_stage_publication,
                      'execute': execute_stage_publication, 'rollback': rollback_stage_publication}[action](**args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result.get('status') == 'ROLLBACK_INCOMPLETE' else 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'FAILED_CLOSED', 'reason': str(error),
            'live_state_after_error': 'CANNOT_CONFIRM' if action in {'execute', 'rollback'} else 'UNCHANGED',
            'natural_verified': False, **FLAGS, **getattr(error, 'context', {})}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
