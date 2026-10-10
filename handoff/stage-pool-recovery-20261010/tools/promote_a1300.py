#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

E = Path('/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/recovery_20261009_all_stages_20261010')
C = E / 'candidate/stage_runner_canary_04_corrected_morning_binding'
OUT = E / 'execution/a1300_backfill_promotion_20261010_01'
PLAN = C / 'evidence/PROMOTION_API_BINDING_PLAN_V3.json'
REVIEW = E / 'evidence/review/A1300_BACKFILL_PROMOTION_PLAN_V3_REVIEW_20261010.json'
INVENTORY = C / 'evidence/CANARY_FILE_MANIFEST_FINAL.json'
BASELINE = C / 'evidence/EXISTING_A_RESULTS_AFTER.json'
R3 = Path('/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/stage_app')
API_CWD = Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app')
API_PID = 10321
EXPECTED = {
    'plan_sha256': '6ea6ab601fd84b4f2f246e5073af76af3b6b5b76258a925cbd88177ca1141737',
    'review_sha256': '5f961bec95d1d267ea1ad5c724fda74a17dac2a5c0f650800c03a277a6e9e0b1',
    'inventory_sha256': 'aa928d03ce464cc89dba190e422745220fdf782492ee8bc0fbdcca9658ae6fea',
    'baseline_sha256': '3d67e1f8b1be86513eec6ce57791466f255525f5d1e308f7ad0be98b31189fea',
    'selection_latest_sha256': 'bfb0ad6b3f5d2261c03fd8db71bf27c3912f581807c7904a2e6fc02217785cd0',
    'api_app_sha256': 'a51b927e98e23ccdd33a849644abfa544232809aab29c2e7223969cc2308d0b8',
    'api_consumer_sha256': '16f004edb60ab256993f02ec4df36caa5d2cb3aa55bff643834c3119ec86d207',
    'api_web_sha256': '8f1c00c4b278fd46736d9176d94752539f46e7c04d38fc13129084e6b9164c0f',
    'r3_runner_sha256': 'ea9909bb4f39c4248032771aedd9611a852353e940451e0b0c7273bde8c26345',
    'r3_slot_lock_sha256': 'f90d3c8e3fba34d157bf45e1f544e9169a575931a3f2f33340e97c25879f5c1d',
    'r3_interprocess_lock_sha256': '9b0cb80a1fe1bcbdebb3936134c8f0bad258c9c9236356022551ff7753351df0',
    'api_selection_sha256': '31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9',
    'r3_selection_sha256': 'ccf7dddfb72fe88b5bff68ce9501e0a8ef9f41a212008a495824017943675294',
}
RUN_ID = '67f131d7732641659c89837dbfd7ea16'
TARGET_KEY = '20261009/STAGE_1300_1315/A_SHARE'
EXPECTED_SELECTION_RUN = 'run-2e40cc6a40d0e6d3c65d8f72'
SAFETY_FALSE = ('production_allowed', 'buy_gate_updated', 'orders_sent')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    raise RuntimeError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_once(path: Path, value) -> str:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        raise
    return hashlib.sha256(raw).hexdigest()


def no_symlink_path(path: Path, *, require_dir: bool = False) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if os.path.lexists(current):
            st = current.lstat()
            require(not stat.S_ISLNK(st.st_mode), f'symlink forbidden: {current}')
            if current != path and not stat.S_ISDIR(st.st_mode):
                fail(f'non-directory path ancestor: {current}')
    if os.path.lexists(path):
        st = path.lstat()
        require(not stat.S_ISLNK(st.st_mode), f'symlink forbidden: {path}')
        if require_dir:
            require(stat.S_ISDIR(st.st_mode), f'not a directory: {path}')


def mode_text(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def verify_inventory() -> dict:
    require(sha(PLAN) == EXPECTED['plan_sha256'], 'pinned PLAN_V3 SHA mismatch')
    require(sha(REVIEW) == EXPECTED['review_sha256'], 'pinned independent review SHA mismatch')
    require(sha(INVENTORY) == EXPECTED['inventory_sha256'], 'pinned candidate inventory SHA mismatch')
    require(sha(BASELINE) == EXPECTED['baseline_sha256'], 'pinned 51-result baseline manifest SHA mismatch')
    plan = read_json(PLAN)
    review = read_json(REVIEW)
    inventory = read_json(INVENTORY)
    require(plan.get('status') == 'PREPARED_NOT_PROMOTED', 'plan is not PREPARED_NOT_PROMOTED')
    require(review.get('verdict', {}).get('status') == 'PASS_PLAN_ONLY', 'independent review is not PASS_PLAN_ONLY')
    require(review.get('verdict', {}).get('plan_ready_for_parent_execution') is True, 'review does not authorize parent execution')
    require(review.get('artifacts', {}).get('plan_v3', {}).get('sha256') == EXPECTED['plan_sha256'], 'review does not bind pinned plan')
    require(plan.get('run', {}).get('backfill_run_id') == RUN_ID, 'run id mismatch')
    require(plan.get('run', {}).get('trade_date') == '20261009' and plan.get('run', {}).get('stage') == 'STAGE_1300_1315', 'date/stage mismatch')
    require(plan.get('run', {}).get('a_share_selected_count') == 10 and plan.get('run', {}).get('candidate_status') == 'PARTIAL_WITH_ROWS', 'candidate status/count mismatch')
    require(plan.get('run', {}).get('hk_status') == 'CANNOT_CONFIRM', 'HK boundary changed')
    require(plan.get('run', {}).get('research_only') is True, 'RESEARCH_ONLY changed')
    for flag in SAFETY_FALSE:
        require(plan.get('run', {}).get(flag) is False, f'{flag} changed')
    require(plan.get('run', {}).get('natural_verified') is False, 'natural verification flag changed')
    require(inventory.get('status') == 'FINAL_CANDIDATE_INVENTORY' and inventory.get('backfill_run_id') == RUN_ID, 'candidate inventory identity mismatch')
    require(inventory.get('files_count') == len(inventory.get('files', [])) == 28, 'candidate inventory count mismatch')
    for entry in inventory['files']:
        rel = PurePosixPath(entry['relative_path'])
        require(not rel.is_absolute() and '..' not in rel.parts, f'unsafe inventory path: {rel}')
        path = C.joinpath(*rel.parts)
        no_symlink_path(path)
        require(path.is_file(), f'inventory file missing: {rel}')
        require(path.stat().st_size == entry['size_bytes'], f'inventory size mismatch: {rel}')
        require(mode_text(path) == entry['mode'], f'inventory mode mismatch: {rel}')
        require(sha(path) == entry['sha256'], f'inventory SHA mismatch: {rel}')
    return {'plan': plan, 'review': review, 'inventory': inventory}


def verify_sources(plan: dict) -> dict:
    result = {}
    for name, spec in plan['candidate_source_trees'].items():
        root = Path(spec['path'])
        no_symlink_path(root, require_dir=True)
        expected = {entry['path']: entry for entry in spec['files']}
        actual, transient = {}, []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            base = Path(dirpath)
            for dirname in list(dirnames):
                p = base / dirname
                require(not p.is_symlink(), f'source symlink directory forbidden: {p}')
            for filename in filenames:
                p = base / filename
                require(not p.is_symlink(), f'source symlink file forbidden: {p}')
                rel = p.relative_to(root).as_posix()
                st = p.stat()
                if rel not in expected:
                    if st.st_size == 0 and ('.lock' in filename or '.mutex' in filename):
                        transient.append(rel)
                        continue
                    fail(f'unmanifested source file: {name}/{rel}')
                actual[rel] = {'size_bytes': st.st_size, 'sha256': sha(p), 'mode': mode_text(p)}
        require(set(actual) == set(expected), f'source file set mismatch: {name}')
        for rel, entry in expected.items():
            require(actual[rel]['size_bytes'] == entry['size_bytes'], f'source size mismatch: {name}/{rel}')
            require(actual[rel]['sha256'] == entry['sha256'], f'source SHA mismatch: {name}/{rel}')
            require(actual[rel]['mode'] == entry['mode'], f'source mode mismatch: {name}/{rel}')
        result[name] = {'source': str(root), 'files': len(actual), 'transient_empty_locks_ignored': transient}
    return result


def verify_baseline(plan: dict) -> dict:
    expected = plan['cas_preconditions']['existing_10_09_a_results']['manifest']
    require(expected['sha256'] == EXPECTED['baseline_sha256'] and expected['count'] == 51, 'baseline pin mismatch')
    data = read_json(BASELINE)
    require(data.get('status') == 'UNCHANGED' and data.get('count') == 51 and data.get('unchanged_count') == 51, 'baseline receipt not unchanged/51')
    require(not data.get('changed') and not data.get('missing'), 'baseline receipt reports changes/missing files')
    require(len(data.get('files', [])) == 51, 'baseline manifest does not contain 51 files')
    for item in data['files']:
        path = Path(item['path'])
        no_symlink_path(path)
        require(path.is_file(), f'existing A artifact missing: {path}')
        require(path.stat().st_size == item['size_bytes'], f'existing A artifact size changed: {path}')
        require(sha(path) == item['sha256'], f'existing A artifact SHA changed: {path}')
    return {'count': 51, 'status': 'UNCHANGED', 'manifest_sha256': sha(BASELINE)}


def verify_pointer(plan: dict) -> str:
    pointer = Path(plan['cas_preconditions']['selection_latest']['path'])
    no_symlink_path(pointer)
    require(pointer.is_file(), 'selection_latest is missing')
    digest = sha(pointer)
    require(digest == EXPECTED['selection_latest_sha256'], 'selection_latest SHA changed')
    data = read_json(pointer)
    key = plan['cas_preconditions']['selection_backfill_same_key_candidates']['key']
    require(isinstance(data.get('entries'), dict) and key not in data['entries'], 'selection_latest already has target key')
    return digest


def same_key_scan(selection_root: Path) -> list:
    backfill = selection_root / 'backfill'
    no_symlink_path(backfill, require_dir=True)
    hits = []
    for child in sorted(backfill.iterdir()):
        st = child.lstat()
        require(not stat.S_ISLNK(st.st_mode), f'symlink in selection backfill scan root: {child}')
        if not stat.S_ISDIR(st.st_mode):
            continue
        latest = child / 'selection_latest.json'
        if not os.path.lexists(latest):
            continue
        no_symlink_path(latest)
        require(latest.is_file(), f'non-file selection latest candidate: {latest}')
        data = read_json(latest)
        require(isinstance(data, dict) and isinstance(data.get('entries'), dict), f'malformed selection latest candidate: {latest}')
        if TARGET_KEY in data['entries']:
            hits.append({'backfill_run_id': child.name, 'entry': data['entries'][TARGET_KEY]})
    return hits


def runtime_identity(plan: dict) -> dict:
    binding = plan['existing_api_binding']
    expected_cwd = binding['working_directory']
    try:
        command = subprocess.check_output(['ps', '-p', str(API_PID), '-o', 'command='], text=True).strip()
    except subprocess.CalledProcessError:
        fail(f'API pid {API_PID} is not running')
    require(command, 'API command is empty')
    require('apps.api.v35_api.run' in command and '--port 8873' in command, 'API command/port differs from pinned process')
    require(binding['configured_selection_root'] in command, 'API command selection root differs from plan')
    cwd_out = subprocess.check_output(['lsof', '-a', '-p', str(API_PID), '-d', 'cwd', '-Fn'], text=True)
    cwd = next((line[1:] for line in cwd_out.splitlines() if line.startswith('n/')), '')
    require(cwd == expected_cwd, f'API cwd differs from plan: {cwd}')
    listener = subprocess.check_output(['lsof', '-nP', '-iTCP:8873', '-sTCP:LISTEN'], text=True)
    listener_lines = [line for line in listener.splitlines()[1:] if line.split() and line.split()[1] == str(API_PID)]
    require(any('127.0.0.1:8873' in line for line in listener_lines), 'pinned API pid not listening on 127.0.0.1:8873')
    hashes = {
        'api_app': sha(API_CWD / 'apps/api/v35_api/app.py'),
        'api_consumer': sha(API_CWD / 'stage_center/consumer.py'),
        'api_selection': sha(API_CWD / 'stage_center/selection.py'),
        'api_web': sha(API_CWD / 'apps/web/src/App.vue'),
    }
    require(hashes['api_app'] == EXPECTED['api_app_sha256'], 'active API app source SHA differs from plan')
    require(hashes['api_consumer'] == EXPECTED['api_consumer_sha256'], 'active Stage consumer SHA differs from plan')
    require(hashes['api_selection'] == EXPECTED['api_selection_sha256'], 'active selection reader SHA differs from independent review pin')
    require(hashes['api_web'] == EXPECTED['api_web_sha256'], 'active web App.vue SHA differs from plan')
    return {'pid': API_PID, 'command': command, 'cwd': cwd, 'listener': '127.0.0.1:8873', 'source_hashes': hashes}


def verify_r3_lock_sources() -> dict:
    sources = {
        'runner': (R3 / 'stage_center/runner.py', EXPECTED['r3_runner_sha256']),
        'slot_lock': (R3 / 'stage_center/_runner_parts/slot_lock.py', EXPECTED['r3_slot_lock_sha256']),
        'interprocess_lock': (R3 / 'infrastructure/interprocess_lock.py', EXPECTED['r3_interprocess_lock_sha256']),
    }
    actual = {}
    for name, (path, expected) in sources.items():
        no_symlink_path(path)
        require(path.is_file(), f'pinned R3 lock source missing: {path}')
        actual[name] = sha(path)
        require(actual[name] == expected, f'pinned R3 {name} source SHA mismatch')
    selection = R3 / 'stage_center/selection.py'
    actual['selection'] = sha(selection)
    require(actual['selection'] == EXPECTED['r3_selection_sha256'], 'pinned R3 SelectionStore source SHA mismatch')
    return actual


def renameatx_call(src: Path, dst: Path) -> None:
    libc = ctypes.CDLL(ctypes.util.find_library('c') or None, use_errno=True)
    fn = getattr(libc, 'renameatx_np', None)
    require(fn is not None, 'macOS renameatx_np unavailable')
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    at_fdcwd, rename_excl = -2, 0x00000004
    rc = fn(at_fdcwd, os.fsencode(src), at_fdcwd, os.fsencode(dst), rename_excl)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(dst))


def rename_exclusive(src: Path, dst: Path) -> None:
    require(src.exists() and not src.is_symlink(), f'atomic rename source absent/symlink: {src}')
    no_symlink_path(dst.parent, require_dir=True)
    require(not os.path.lexists(dst), f'atomic rename destination exists: {dst}')
    require(src.stat().st_dev == dst.parent.stat().st_dev, f'cross-device atomic rename forbidden: {src} -> {dst}')
    renameatx_call(src, dst)


def probe_renameatx() -> dict:
    probe = OUT / 'renameatx_probe_02'
    no_symlink_path(probe)
    require(not os.path.lexists(probe), 'renameatx probe path already exists')
    probe.mkdir(mode=0o700)
    source = probe / 'source'
    destination = probe / 'destination'
    source.mkdir()
    (source / 'marker.txt').write_text('exclusive-rename-probe\n')
    marker_sha = sha(source / 'marker.txt')
    rename_exclusive(source, destination)
    require(not source.exists() and sha(destination / 'marker.txt') == marker_sha, 'exclusive rename probe did not move exact bytes')
    conflict_source, conflict_destination = probe / 'conflict_source', probe / 'conflict_destination'
    conflict_source.mkdir(); (conflict_source / 'marker.txt').write_text('source-kept\n')
    conflict_destination.mkdir(); (conflict_destination / 'marker.txt').write_text('destination-kept\n')
    prior_dest = sha(conflict_destination / 'marker.txt')
    try:
        renameatx_call(conflict_source, conflict_destination)
    except OSError as error:
        require(error.errno in (17, 18), f'unexpected no-overwrite errno in probe: {error.errno}')
    else:
        fail('renameatx_np overwrote existing target in probe')
    require(conflict_source.exists() and sha(conflict_destination / 'marker.txt') == prior_dest, 'existing target was changed by no-overwrite probe')
    return {'status': 'PASS', 'function': 'renameatx_np(RENAME_EXCL)', 'target_absent_move': True, 'target_exists_preserved': True, 'evidence_path': str(probe)}


def verify_tree(root: Path, spec: dict) -> dict:
    expected = {entry['path']: entry for entry in spec['files']}
    actual = {}
    no_symlink_path(root, require_dir=True)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for dirname in dirnames:
            require(not (base / dirname).is_symlink(), f'symlink in published tree: {base / dirname}')
        for filename in filenames:
            path = base / filename
            require(not path.is_symlink(), f'symlink in published tree: {path}')
            rel = path.relative_to(root).as_posix()
            actual[rel] = {'size_bytes': path.stat().st_size, 'sha256': sha(path), 'mode': mode_text(path)}
    require(set(actual) == set(expected), f'published file set mismatch: {root}')
    for rel, item in expected.items():
        require(actual[rel]['size_bytes'] == item['size_bytes'], f'published size mismatch: {root}/{rel}')
        require(actual[rel]['sha256'] == item['sha256'], f'published SHA mismatch: {root}/{rel}')
        require(actual[rel]['mode'] == item['mode'], f'published mode mismatch: {root}/{rel}')
    return {'files': len(actual), 'tree_sha256': hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def copy_to_stage(spec: dict, stage: Path) -> dict:
    no_symlink_path(stage)
    require(not os.path.lexists(stage), f'staging path already exists: {stage}')
    parent = stage.parent
    no_symlink_path(parent)
    if not parent.exists():
        parent.mkdir(mode=0o700)
    no_symlink_path(parent, require_dir=True)
    stage.mkdir(mode=0o700)
    source = Path(spec['path'])
    for entry in spec['files']:
        rel = PurePosixPath(entry['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, f'unsafe source path: {rel}')
        src, dst = source.joinpath(*rel.parts), stage.joinpath(*rel.parts)
        no_symlink_path(src)
        require(src.is_file(), f'source file missing: {src}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=False)
        os.chmod(dst, int(entry['mode'], 8))
    return verify_tree(stage, spec)


def candidate_dirs(plan: dict) -> tuple[dict, dict, dict]:
    roots = {name: Path(path) for name, path in plan['destination_preflight']['target_roots'].items()}
    targets = {name: roots[name] / 'backfill' / RUN_ID for name in ('raw', 'selection', 'receipts')}
    stages = {name: roots[name] / '.promotion-staging' / RUN_ID for name in ('raw', 'selection', 'receipts')}
    quarantine = {name: Path(path) for name, path in plan['review_exact_paths']['quarantine_paths'].items()} if 'review_exact_paths' in plan else None
    return roots, targets, stages


def paths_from(plan: dict, review: dict):
    roots = {name: Path(path) for name, path in plan['destination_preflight']['target_roots'].items()}
    targets = {name: roots[name] / 'backfill' / RUN_ID for name in ('raw', 'selection', 'receipts')}
    stages = {name: roots[name] / '.promotion-staging' / RUN_ID for name in ('raw', 'selection', 'receipts')}
    quarantine = {name: Path(path) for name, path in review['evidence']['exact_paths']['quarantine_paths'].items()}
    for name in ('raw', 'selection', 'receipts'):
        require(targets[name] == Path(plan['cas_preconditions']['no_target_paths'][name]['path']), f'target path mismatch: {name}')
        require(quarantine[name].name == name and quarantine[name].parent.name == RUN_ID, f'quarantine path mismatch: {name}')
    return roots, targets, stages, quarantine


def verify_destinations(plan: dict, review: dict) -> dict:
    roots, targets, stages, quarantine = paths_from(plan, review)
    for name in ('raw', 'selection', 'receipts'):
        no_symlink_path(roots[name], require_dir=True)
        no_symlink_path(roots[name] / 'backfill', require_dir=True)
        require(not os.path.lexists(targets[name]), f'target already exists: {targets[name]}')
        no_symlink_path(stages[name].parent)
        require(not os.path.lexists(stages[name]), f'staging path already exists: {stages[name]}')
        no_symlink_path(quarantine[name].parent)
        require(not os.path.lexists(quarantine[name]), f'quarantine path already exists: {quarantine[name]}')
        require(roots[name].stat().st_dev == (roots[name] / 'backfill').stat().st_dev, f'backfill is on different device: {name}')
    pointer_sha = verify_pointer(plan)
    require(same_key_scan(roots['selection']) == [], 'same-key selection backfill candidate already exists')
    baseline = verify_baseline(plan)
    return {'targets_absent': True, 'staging_absent': True, 'quarantine_absent': True, 'selection_latest_sha256': pointer_sha, 'same_key_candidates': [], 'existing_a_results': baseline, 'device_ids': {k: v.stat().st_dev for k, v in roots.items()}}


def acquire_locks(roots: dict):
    sys.path.insert(0, str(R3))
    from stage_center.runner import SlotLock
    from stage_center.selection import SelectionStore
    slot_path = roots['receipts'] / '.locks' / '20261009-STAGE_1300_1315.lock'
    store = SelectionStore(roots['selection'])
    return SlotLock(slot_path), store._lock()


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_exact(spec: dict, stage: Path) -> dict:
    summary = copy_to_stage(spec, stage)
    for dirpath, dirnames, filenames in os.walk(stage, topdown=False):
        for name in filenames:
            with (Path(dirpath) / name).open('rb') as stream:
                os.fsync(stream.fileno())
        fsync_directory(Path(dirpath))
    return summary


def api_readback(out: Path, plan: dict) -> tuple[dict, dict]:
    url = 'http://127.0.0.1:8873/api/v3/workbench/stage?date=20261009&stage=STAGE_1300_1315&limit=50'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
    with opener.open(request, timeout=20) as response:
        status_code = response.status
        raw = response.read()
    require(status_code == 200, f'ordinary API returned HTTP {status_code}')
    payload = json.loads(raw.decode('utf-8'))
    path = out / 'ordinary_api_readback.json'
    digest = write_once(path, payload)
    require(payload.get('trade_date') == '20261009', 'API trade date mismatch')
    require((payload.get('stage') or {}).get('stage_id') == 'STAGE_1300_1315', 'API stage mismatch')
    require(payload.get('RESEARCH_ONLY') is True, 'API RESEARCH_ONLY flag is not true')
    for flag in SAFETY_FALSE:
        require(payload.get(flag) is False, f'API safety flag {flag} is not false')
    markets = payload.get('markets') or {}
    a = markets.get('A')
    hk = markets.get('HK')
    require(isinstance(a, dict), 'API A market projection is unavailable')
    require(a.get('backfill_run_id') == RUN_ID, 'API selected a different backfill run id')
    require(a.get('run_id') == EXPECTED_SELECTION_RUN, 'API selected a different selection run id')
    require(a.get('runner_receipt_verified') is True, 'API runner receipt is not verified')
    require(a.get('selected_rows') == 10 and len(a.get('rows') or []) == 10, 'API A selected row count is not 10')
    require(a.get('status') == 'PARTIAL_WITH_ROWS', 'API A status changed')
    require(isinstance(hk, dict) and hk.get('status') == 'CANNOT_CONFIRM', 'API HK gap was hidden or changed')
    summary = {
        'http_status': status_code, 'url': url, 'response_sha256': digest,
        'trade_date': payload.get('trade_date'), 'stage_id': (payload.get('stage') or {}).get('stage_id'),
        'overall_status': payload.get('status'), 'selection_mode': payload.get('selection_mode'),
        'RESEARCH_ONLY': payload.get('RESEARCH_ONLY'), 'production_allowed': payload.get('production_allowed'),
        'buy_gate_updated': payload.get('buy_gate_updated'), 'orders_sent': payload.get('orders_sent'),
        'A_SHARE': {k: a.get(k) for k in ('status','backfill_run_id','run_id','runner_receipt_verified','runner_receipt_status','selected_rows','requested_rows','source_rows','selection_mode')},
        'HK_CONNECT': {k: hk.get(k) for k in ('status','selected_rows','cannot_confirm')},
        'rows_returned': len(a.get('rows') or []), 'natural_verified_candidate_boundary': plan['run'].get('natural_verified'),
        'response_path': str(path),
    }
    return payload, summary


def quarantine_owned(roots: dict, targets: dict, stages: dict, quarantine: dict, stage_owned: set, published: set, result: dict) -> None:
    moved = []
    for name in ('selection', 'receipts', 'raw'):
        src = targets[name] if name in published else stages[name] if name in stage_owned else None
        if src is None or not os.path.lexists(src):
            continue
        if name in published:
            # Never infer ownership from the run ID alone; only quarantine a target
            # that this execution successfully published itself.
            require(verify_tree(src, result['_source_specs'][name]), f'published tree changed before quarantine: {src}')
        no_symlink_path(quarantine[name].parent)
        if not quarantine[name].parent.exists():
            quarantine[name].parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        no_symlink_path(quarantine[name].parent, require_dir=True)
        require(not os.path.lexists(quarantine[name]), f'quarantine target appeared: {quarantine[name]}')
        rename_exclusive(src, quarantine[name])
        fsync_directory(quarantine[name].parent)
        moved.append({'name': name, 'from': str(src), 'to': str(quarantine[name])})
    result['quarantined'] = moved
    result['own_run_visible_after_quarantine'] = any(os.path.lexists(targets[n]) for n in ('selection','receipts','raw'))


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    result = {'schema': 'a1300_backfill_promotion_execution_v1', 'mode': 'DRY_RUN' if args.dry_run else 'EXECUTE', 'started_at_utc': started,
              'plan_sha256': None, 'review_sha256': None, 'inventory_sha256': None, 'runtime_before': None, 'runtime_after': None,
              'destination_preflight': None, 'source_trees': None, 'same_key_before': None, 'same_key_before_commit': None,
              'same_key_after_commit': None, 'published': [], 'quarantined': [], 'api_readback': None,
              'selection_latest_sha256_before': None, 'selection_latest_sha256_after': None,
              'existing_a_results_before': None, 'existing_a_results_after': None, 'renameatx_probe': None,
              'status': 'STARTED', 'error': None, 'rollback_error': None}
    stage_owned, published = set(), set()
    roots = targets = stages = quarantine = None
    plan = review = None
    try:
        require(Path('/').is_dir(), 'host path unavailable')
        pins = verify_inventory()
        plan, review = pins['plan'], pins['review']
        result['plan_sha256'] = sha(PLAN); result['review_sha256'] = sha(REVIEW); result['inventory_sha256'] = sha(INVENTORY)
        result['source_trees'] = verify_sources(plan)
        result['_source_specs'] = plan['candidate_source_trees']
        result['runtime_before'] = runtime_identity(plan)
        verify_r3_lock_sources()
        roots, targets, stages, quarantine = paths_from(plan, review)
        result['destination_preflight'] = verify_destinations(plan, review)
        result['selection_latest_sha256_before'] = verify_pointer(plan)
        result['existing_a_results_before'] = verify_baseline(plan)
        result['same_key_before'] = same_key_scan(roots['selection'])
        require(result['same_key_before'] == [], 'same-key competitor present before execution')
        if args.dry_run:
            result['renameatx_probe'] = probe_renameatx()
            result['status'] = 'DRY_RUN_PASS'
            result['same_key_before_commit'] = result['same_key_before']
            result['selection_latest_sha256_after'] = verify_pointer(plan)
            result['existing_a_results_after'] = verify_baseline(plan)
            result['runtime_after'] = runtime_identity(plan)
            result.pop('_source_specs', None)
            result['script_sha256'] = sha(Path(__file__))
            result['receipt_sha256'] = write_once(OUT / 'PREFLIGHT_02.json', result)
            receipt = OUT / 'PREFLIGHT_02.json'
            print(json.dumps({'status': result['status'], 'receipt': str(receipt), 'receipt_sha256': result['receipt_sha256'], 'renameatx_probe': result['renameatx_probe']}, indent=2))
            return 0

        # Revalidate all CAS inputs under the same existing R3 base locks as the runner.
        slot_lock, selection_lock = acquire_locks(roots)
        with slot_lock:
            with selection_lock:
                result['same_key_before_commit'] = same_key_scan(roots['selection'])
                require(result['same_key_before_commit'] == [], 'same-key competitor appeared before commit')
                result['destination_preflight_under_locks'] = verify_destinations(plan, review)
                result['selection_latest_sha256_before_commit'] = verify_pointer(plan)
                result['existing_a_results_before_commit'] = verify_baseline(plan)
                for name in ('raw', 'receipts', 'selection'):
                    copied = copy_exact(plan['candidate_source_trees'][name], stages[name])
                    stage_owned.add(name)
                    result.setdefault('staged', {})[name] = {'path': str(stages[name]), **copied}
                # Raw and runner receipts become readable before the selection visibility commit.
                for name in ('raw', 'receipts'):
                    require(not os.path.lexists(targets[name]), f'publish target appeared: {targets[name]}')
                    rename_exclusive(stages[name], targets[name])
                    stage_owned.discard(name); published.add(name)
                    fsync_directory(targets[name].parent)
                    result['published'].append({'name': name, 'path': str(targets[name]), **verify_tree(targets[name], plan['candidate_source_trees'][name])})
                require(not os.path.lexists(targets['selection']), 'selection target appeared before visibility commit')
                require(same_key_scan(roots['selection']) == [], 'same-key competitor appeared after raw/receipt publish')
                rename_exclusive(stages['selection'], targets['selection'])
                stage_owned.discard('selection'); published.add('selection')
                fsync_directory(targets['selection'].parent)
                result['published'].append({'name': 'selection', 'path': str(targets['selection']), **verify_tree(targets['selection'], plan['candidate_source_trees']['selection'])})
                result['same_key_after_commit'] = same_key_scan(roots['selection'])
                require(len(result['same_key_after_commit']) == 1 and result['same_key_after_commit'][0]['backfill_run_id'] == RUN_ID, 'post-commit same-key scan is not exactly this run')
                result['selection_latest_sha256_after_commit'] = verify_pointer(plan)
                result['existing_a_results_after_commit'] = verify_baseline(plan)

        # API is read-only. Verify the pinned process still owns the ordinary route before and after it.
        result['runtime_after_commit_before_api'] = runtime_identity(plan)
        _, api_summary = api_readback(OUT, plan)
        result['api_readback'] = api_summary
        result['runtime_after'] = runtime_identity(plan)
        result['same_key_after_api'] = same_key_scan(roots['selection'])
        require(len(result['same_key_after_api']) == 1 and result['same_key_after_api'][0]['backfill_run_id'] == RUN_ID, 'post-API same-key scan changed')
        result['selection_latest_sha256_after'] = verify_pointer(plan)
        result['existing_a_results_after'] = verify_baseline(plan)
        result['status'] = 'PROMOTED_API_VERIFIED'
        result['completed_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        receipt = OUT / 'PROMOTION_EXECUTION_RECEIPT.json'
        result.pop('_source_specs', None)
        result['script_sha256'] = sha(Path(__file__))
        result['receipt_sha256'] = write_once(receipt, result)
        print(json.dumps({'status': result['status'], 'receipt': str(receipt), 'receipt_sha256': result['receipt_sha256'], 'api_readback': result['api_readback']}, ensure_ascii=False, indent=2))
        return 0
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        if args.execute and roots is not None and targets is not None and stages is not None and quarantine is not None and (stage_owned or published):
            try:
                slot_lock, selection_lock = acquire_locks(roots)
                with slot_lock:
                    with selection_lock:
                        quarantine_owned(roots, targets, stages, quarantine, stage_owned, published, result)
                        result['same_key_after_quarantine'] = same_key_scan(roots['selection'])
                        require(not any(x.get('backfill_run_id') == RUN_ID for x in result['same_key_after_quarantine']), 'own run still visible after quarantine')
                        result['selection_latest_sha256_after_quarantine'] = verify_pointer(plan)
                        result['existing_a_results_after_quarantine'] = verify_baseline(plan)
                result['status'] = 'QUARANTINED_AFTER_GATE_FAILURE'
            except BaseException as rollback_error:
                result['rollback_error'] = f'{type(rollback_error).__name__}: {rollback_error}'
                result['status'] = 'ROLLBACK_BLOCKED_PRESERVE_STATE'
        else:
            result['status'] = 'FAILED_BEFORE_STATE_WRITE' if args.execute else 'DRY_RUN_FAILED'
        result['completed_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        result.pop('_source_specs', None)
        receipt = OUT / ('PROMOTION_EXECUTION_RECEIPT.json' if args.execute else 'PREFLIGHT_02.json')
        try:
            result['script_sha256'] = sha(Path(__file__))
            result['receipt_sha256'] = write_once(receipt, result)
        except BaseException as receipt_error:
            print(json.dumps({'status': result['status'], 'error': result['error'], 'receipt_write_error': f'{type(receipt_error).__name__}: {receipt_error}'}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
        print(json.dumps({'status': result['status'], 'error': result['error'], 'rollback_error': result['rollback_error'], 'receipt': str(receipt), 'receipt_sha256': result['receipt_sha256']}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
