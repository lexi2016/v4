from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path('/workspace/scratch/ff44f882fe5c')
REPO = ROOT / 'candidate'
PACKAGE = ROOT / 'publication/handoff/three-lane-selection-repair-20261011-r1'
BASE = '31f5a39ce1ee7cd76bbf268e68760b6adc319774'
CANDIDATE = 'cd93198cb0de06c8f32386ed1fc808a5b4e53bec'
MANIFEST = json.loads((PACKAGE / 'BEFORE_AFTER_SHA256.json').read_text())
rows = MANIFEST['files']
records = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def check(name, package=PACKAGE, target=None, phase='before', success=True, expect_error=None):
    watched = snapshot(target) if target else None
    cmd = [sys.executable, str(package / 'check_candidate.py')]
    if target is not None:
        cmd += ['--target', str(target), '--phase', phase]
    run = subprocess.run(cmd, capture_output=True, text=True)
    result = json.loads(run.stdout)
    assert run.returncode == (0 if success else 2), (name, run.returncode, result, run.stderr)
    assert result['status'] == ('BYTES_MATCH' if success else 'CANNOT_CONFIRM'), (name, result)
    assert not run.stderr, (name, run.stderr)
    if target:
        assert snapshot(target) == watched, name + ': helper wrote target'
    if expect_error:
        assert expect_error in result.get('error', ''), (name, result)
    if success:
        assert len(result['files']) == 12
    records.append({'name': name, 'status': 'PASS', 'exit_code': run.returncode,
        'observed_status': result['status'], 'error': result.get('error'),
        'target_bytes_unchanged': True if target else None,
        'helper_reported_target_writes': result.get('target_writes'),
        'command': cmd})


with tempfile.TemporaryDirectory(prefix='three-lane-delivery-', dir=ROOT / 'verification') as temporary:
    tmp = Path(temporary)
    baseline = tmp / 'baseline'
    baseline.mkdir()
    archive = subprocess.check_output(['git', '-C', str(REPO), 'archive', BASE])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(baseline, filter='data')
    original = snapshot(baseline)
    check('package_after_artifacts_present_and_exact')
    check('fixed_baseline_before_matches_and_helper_read_only', target=baseline)
    check('committed_candidate_after_matches_and_helper_read_only', target=REPO, phase='after')
    cmd = ['git', '-C', str(baseline), 'apply', '--check', str(PACKAGE / 'changes.patch')]
    subprocess.run(cmd, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(baseline), 'apply', str(PACKAGE / 'changes.patch')], check=True, capture_output=True)
    patched = snapshot(baseline)
    changed = sorted(path for path in set(original) | set(patched) if original.get(path) != patched.get(path))
    assert changed == sorted(row['path'] for row in rows)
    for row in rows:
        assert digest(baseline / row['path']) == row['after_sha256']
        assert (baseline / row['path']).read_bytes() == (REPO / row['path']).read_bytes()
    check('applied_patch_after_matches_and_helper_read_only', target=baseline, phase='after')
    subprocess.run(['git', '-C', str(baseline), 'apply', '--reverse', '--check', str(PACKAGE / 'changes.patch')], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(baseline), 'apply', '--reverse', str(PACKAGE / 'changes.patch')], check=True, capture_output=True)
    assert snapshot(baseline) == original
    check('reverse_patch_restores_exact_baseline', target=baseline)

    altered = baseline / rows[0]['path']
    altered.write_bytes(altered.read_bytes() + b'\nlocal parallel edit\n')
    check('local_parallel_edit_rejected_without_writing', target=baseline, success=False)

    def bad_package(name):
        target = tmp / name
        target.mkdir()
        shutil.copyfile(PACKAGE / 'check_candidate.py', target / 'check_candidate.py')
        shutil.copyfile(PACKAGE / 'BEFORE_AFTER_SHA256.json', target / 'BEFORE_AFTER_SHA256.json')
        shutil.copytree(PACKAGE / 'after', target / 'after')
        return target

    def set_manifest(package, value):
        (package / 'BEFORE_AFTER_SHA256.json').write_text(json.dumps(value))

    bad = bad_package('null_after')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    for row in data['files']:
        row['after_sha256'] = None
        row['after_bytes'] = 0
        (bad / 'after' / row['path']).unlink()
    set_manifest(bad, data)
    check('reviewer_null_after_false_positive_regression', bad, success=False,
          expect_error='PATCH_MANIFEST_NULL_IDENTITY_INVALID')

    bad = bad_package('non_object_manifest')
    set_manifest(bad, [])
    check('non_object_manifest_rejected_as_structured_error', bad, success=False, expect_error='PATCH_MANIFEST_NOT_OBJECT')

    bad = bad_package('non_object_row')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    data['files'][0] = None
    set_manifest(bad, data)
    check('non_object_row_rejected_as_structured_error', bad, success=False, expect_error='PATCH_MANIFEST_ROW_NOT_OBJECT')

    bad = bad_package('missing_after')
    (bad / 'after' / rows[0]['path']).unlink()
    check('missing_after_file_rejected', bad, success=False, expect_error='PATCH_AFTER_BYTES_MISMATCH')

    bad = bad_package('tampered_after')
    (bad / 'after' / rows[0]['path']).write_bytes(b'unreviewed replacement')
    check('tampered_after_file_rejected', bad, success=False, expect_error='PATCH_AFTER_BYTES_MISMATCH')

    bad = bad_package('symlink_after')
    leaf = bad / 'after' / rows[0]['path']
    leaf.unlink()
    leaf.symlink_to(PACKAGE / 'after' / rows[0]['path'])
    check('after_symlink_rejected_even_when_content_matches', bad, success=False, expect_error='SYMLINK_PATH_REJECTED')

    bad = bad_package('symlink_after_root')
    shutil.rmtree(bad / 'after')
    (bad / 'after').symlink_to(PACKAGE / 'after', target_is_directory=True)
    check('after_root_symlink_rejected', bad, success=False, expect_error='ROOT_MUST_BE_NON_SYMLINK_DIRECTORY')

    bad = bad_package('boolean_byte_count')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    data['files'][0]['after_bytes'] = True
    set_manifest(bad, data)
    check('boolean_byte_count_rejected', bad, success=False, expect_error='PATCH_MANIFEST_BYTE_IDENTITY_INVALID')

    bad = bad_package('unsafe_path')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    data['files'][0]['path'] = '../escape.py'
    set_manifest(bad, data)
    check('parent_path_rejected', bad, success=False, expect_error='UNSAFE_RELATIVE_PATH')

    bad = bad_package('duplicate_path')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    data['files'][0]['path'] = data['files'][1]['path']
    set_manifest(bad, data)
    check('duplicate_manifest_path_rejected', bad, success=False, expect_error='PATCH_MANIFEST_PATHS_INVALID')

    altered.write_bytes(subprocess.check_output(['git', '-C', str(REPO), 'show', BASE + ':' + rows[0]['path']]))
    missing_target = tmp / 'missing_modified_target'
    shutil.copytree(baseline, missing_target)
    (missing_target / rows[0]['path']).unlink()
    bad = bad_package('modified_null_before')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    assert data['files'][0]['change'] == 'modified'
    data['files'][0]['before_sha256'] = None
    data['files'][0]['before_bytes'] = None
    set_manifest(bad, data)
    check('modified_null_before_cannot_accept_missing_business_file', bad, target=missing_target,
          success=False, expect_error='PATCH_MANIFEST_CHANGE_IDENTITY_INVALID')

    bad = bad_package('added_with_before')
    data = json.loads((bad / 'BEFORE_AFTER_SHA256.json').read_text())
    new_row = next(row for row in data['files'] if row['change'] == 'added_test')
    new_row['before_sha256'] = new_row['after_sha256']
    new_row['before_bytes'] = new_row['after_bytes']
    set_manifest(bad, data)
    check('added_test_cannot_declare_existing_before_image', bad, success=False,
          expect_error='PATCH_MANIFEST_CHANGE_IDENTITY_INVALID')

result = {
    'schema_version': 'three_lane.delivery_verification.v1',
    'scope': 'LOCAL_TEMPORARY_PATCH_APPLICATION_AND_READ_ONLY_HELPER_ONLY',
    'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'baseline_commit': BASE, 'candidate_commit': CANDIDATE,
    'patch_sha256': digest(PACKAGE / 'changes.patch'),
    'manifest_sha256': digest(PACKAGE / 'BEFORE_AFTER_SHA256.json'),
    'helper_sha256': digest(PACKAGE / 'check_candidate.py'),
    'python': sys.version, 'helper_checks_passed': len(records), 'helper_checks_failed': 0,
    'patch_apply_and_reverse_verified': True, 'patched_paths_exact': changed,
    'all_original_unmodified_paths_preserved': True, 'temporary_fixture_removed': True,
    'candidate_source_unmodified': subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain']) == b'',
    'live_mac_tested': False, 'deployed': False, 'owner_run_verified': False,
    'api_ui_verified': False, 'natural_run_verified': False,
    'checks': records,
}
(PACKAGE / 'checks/DELIVERY_VERIFICATION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k:v for k,v in result.items() if k != 'checks'}, ensure_ascii=False))
