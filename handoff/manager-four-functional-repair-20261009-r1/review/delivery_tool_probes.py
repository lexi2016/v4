"""Small independent packaging probes; never collect the 57 business tests.

This script operates exclusively on fresh package/source copies below its
own delivery_tool_cases_ directory. The real package and source are read-only.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
PACKAGE = ROOT / 'delivery/manager-four-functional-repair-20261009-r1'
CASES = Path(tempfile.mkdtemp(prefix='delivery_tool_cases_', dir=OUT))
PYTHON = sys.executable
RESULTS = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            result[name] = {'symlink': os.readlink(path)}
        elif path.is_file():
            result[name] = sha(path)
    return result


pristine = CASES / 'pristine_package'
shutil.copytree(PACKAGE, pristine, ignore=shutil.ignore_patterns('LOCAL'))
manifest = json.loads((pristine / 'source_manifest.json').read_text())
unchanged = json.loads((pristine / 'UNCHANGED_R2_TARGETS.json').read_text())
source_pristine = CASES / 'minimal_after_source'
source_pristine.mkdir()
for row in manifest['runtime_files']:
    target = source_pristine / row['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pristine / 'after' / row['path'], target)
for row in unchanged['files']:
    target = source_pristine / row['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'input/remote/package/code/r2_chat_patch_target' / row['path'], target)


def invoke(case, package, source, *, expected_exit, expected_reason=None,
           runner=False, output=None):
    before_source = snapshot(source)
    before_package = snapshot(package)
    if runner:
        output = output or (CASES / (case + '_output'))
        command = [PYTHON, '-B', str(package / 'tools/run_regression.py'),
                   '--source-root', str(source), '--output-dir', str(output)]
    else:
        command = [PYTHON, '-B', str(package / 'tools/verify_delivery.py'),
                   '--source-root', str(source), '--side', 'after']
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, cwd=CASES)
    result = {'case': case, 'command': command, 'exit_code': proc.returncode,
              'stdout': proc.stdout, 'source_unchanged': snapshot(source) == before_source,
              'package_unchanged': snapshot(package) == before_package}
    if runner and output and (output / 'environment.json').is_file():
        environment = json.loads((output / 'environment.json').read_text())
        result['runner_environment'] = {
            key: environment.get(key) for key in (
                'status', 'reason', 'pytest_exit_code', 'worker_exit_code', 'runner_exit_code',
                'passed_tests', 'original_source_differences', 'execution_source_differences')}
        assert environment['status'] == 'FAIL'
        assert environment.get('passed_tests', 0) == 0
        assert environment.get('pytest_exit_code') is None
    RESULTS.append(result)
    assert proc.returncode == expected_exit, result
    assert result['source_unchanged'], result
    assert result['package_unchanged'], result
    if expected_reason:
        proof = proc.stdout + json.dumps(result.get('runner_environment', {}))
        assert expected_reason in proof, result


def new_source(name):
    destination = CASES / name
    shutil.copytree(source_pristine, destination)
    return destination


def new_package(name):
    destination = CASES / name
    shutil.copytree(pristine, destination)
    return destination


try:
    invoke('valid_inventory_and_20_source_targets', pristine, source_pristine, expected_exit=0)

    broken_package = new_package('package_hash_drift')
    target = broken_package / 'after/v4/manager_research/connect_selection.py'
    target.write_bytes(target.read_bytes() + b'\n')
    invoke('package_hash_drift', broken_package, source_pristine, expected_exit=1,
           expected_reason='PACKAGE_CHECKSUM_MISMATCH')

    broken_source = new_source('source_runtime_hash_drift')
    target = broken_source / 'v4/manager_research/connect_selection.py'
    target.write_bytes(target.read_bytes() + b'\n')
    invoke('source_runtime_hash_drift', pristine, broken_source, expected_exit=1,
           expected_reason='SOURCE_AFTER_MISMATCH')
    invoke('runner_refuses_runtime_hash_drift_before_tests', pristine, broken_source,
           expected_exit=1, expected_reason='SOURCE_AFTER_MISMATCH', runner=True)

    unchanged_drift = new_source('source_unchanged_hash_drift')
    target = unchanged_drift / 'apps/api/v35_api/manager_research_router.py'
    target.write_bytes(target.read_bytes() + b'\n')
    invoke('unchanged_r2_hash_drift', pristine, unchanged_drift, expected_exit=1,
           expected_reason='UNCHANGED_R2_SOURCE_MISMATCH')

    source_symlink = new_source('source_target_symlink')
    target = source_symlink / 'v4/manager_research/connect_selection.py'
    outside = CASES / 'outside_same_bytes.py'
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)
    invoke('source_target_symlink_with_identical_bytes', pristine, source_symlink,
           expected_exit=1, expected_reason='SYMLINK_REJECTED')

    unsafe_package = new_package('inventory_unsafe_path')
    path = unsafe_package / 'CHECKSUMS.json'
    value = json.loads(path.read_text())
    value['files'][0]['path'] = '../outside'
    path.write_text(json.dumps(value))
    invoke('inventory_path_traversal', unsafe_package, source_pristine,
           expected_exit=1, expected_reason='UNSAFE_RELATIVE_PATH')

    extra_package = new_package('inventory_unlisted_file')
    (extra_package / 'unlisted_sentinel.txt').write_text('fixture-only extra byte source')
    invoke('unlisted_package_file', extra_package, source_pristine,
           expected_exit=1, expected_reason='PACKAGE_INVENTORY_SET_MISMATCH')

    invoke('runner_output_inside_original_source', pristine, source_pristine,
           expected_exit=1, expected_reason='OUTPUT_MUST_BE_OUTSIDE_SOURCE_ROOT',
           runner=True, output=source_pristine / 'forbidden-output')

    copy_symlink = new_source('unexpected_source_symlink')
    (copy_symlink / 'unexpected-link').symlink_to(outside)
    invoke('runner_rejects_non_target_source_symlink', pristine, copy_symlink,
           expected_exit=1, expected_reason='UNEXPECTED_SOURCE_SYMLINK', runner=True)

    # Twenty targets satisfy the byte gate but are deliberately not a complete
    # application. The worker must fail on its own missing ops package, and
    # must never borrow the original app's business namespace to turn green.
    invoke('runner_missing_dependency_has_no_ambient_source_fallback', pristine,
           source_pristine, expected_exit=1, expected_reason="No module named 'ops'",
           runner=True)
finally:
    receipt = {
        'schema_version': 'v4.four_function.independent_delivery_tool_probes.v1',
        'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Synthetic package and minimal source copies only; zero business test calls',
        'case_root': str(CASES),
        'pristine_package_inventory_sha256': sha(pristine / 'CHECKSUMS.json'),
        'tool_sha256': {name: sha(pristine / 'tools' / name)
                        for name in ('verify_delivery.py', 'run_regression.py')},
        'case_count': len(RESULTS), 'cases': RESULTS,
    }
    (OUT / 'delivery_tool_probe_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (OUT / 'delivery_tool_probes.rawlog').write_text(
        '\n'.join(json.dumps(result, indent=2) for result in RESULTS) + '\n')

print(json.dumps({'status': 'PASS', 'cases': len(RESULTS),
                  'rawlog': str(OUT / 'delivery_tool_probes.rawlog')}, indent=2))
