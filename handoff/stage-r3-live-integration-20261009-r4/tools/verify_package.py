#!/usr/bin/env python3
"""Verify exact R4 delivery bytes and reviewed scopes without touching a runtime.

The fixed Git commit / externally recorded ZIP SHA is the trust anchor. These
manifests detect incomplete extraction and byte drift; they are not signatures.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
APP_PATHS = {'api': ('apps/api/v35_api/app.py', 'stage_center/consumer.py',
                    'stage_center/execution_evidence.py', 'stage_center/research_read_binding.py'),
             'ui': ('apps/web/src/App.vue', 'apps/web/src/contracts/runtime.ts',
                    'apps/web/src/components/review/StageExecutionEvidencePanel.vue')}
RELEASE_MODIFIED = ('ops/api_release_integration.py', 'ops/create_api_module_delta.py', 'ops/build_release_candidate.py')
RELEASE_PATHS = RELEASE_MODIFIED + ('ops/prepare_api_only_cutover.py', 'ops/release_candidate_sources.py',
    'ops/release_candidate_audit.py', 'ops/release_candidate_ports.py', 'ops/build_release_candidate_stage.py',
    'ops/stage_service_overlay_contract.py')
REQUIRED_SUITES = ('api', 'ui', 'release', 'integration', 'review_gates')
BASE_COMMIT = '137431f5de3917ff4526784351f5638e115061e5'
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


class PackageError(ValueError):
    pass


def require(condition, error):
    if not condition:
        raise PackageError(error)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(value):
    require(isinstance(value, str) and value and '\\' not in value, 'PACKAGE_PATH_INVALID')
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and '.' not in path.parts
            and str(path) == value, 'PACKAGE_PATH_NOT_CANONICAL:' + value)
    return value


def read(root, value):
    value = relative(value)
    path = root
    for part in PurePosixPath(value).parts:
        path = path / part
        require(not path.is_symlink(), 'PACKAGE_SYMLINK_REJECTED:' + value)
    require(path.is_file(), 'PACKAGE_FILE_MISSING:' + value)
    return path.read_bytes()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'PACKAGE_JSON_DUPLICATE_KEY:' + key)
        result[key] = value
    return result


def document(root, name):
    value = json.loads(read(root, name), object_pairs_hook=no_duplicate_keys,
                       parse_constant=lambda value: (_ for _ in ()).throw(PackageError('NONFINITE_JSON:' + value)))
    require(isinstance(value, dict), 'PACKAGE_JSON_OBJECT_REQUIRED:' + name)
    return value


def files_under(root, prefix=''):
    base = root / prefix
    require(base.is_dir() and not base.is_symlink(), 'PACKAGE_DIRECTORY_MISSING:' + prefix)
    result = set()
    for path in base.rglob('*'):
        rel = path.relative_to(root).as_posix()
        require(not path.is_symlink(), 'PACKAGE_SYMLINK_REJECTED:' + rel)
        if path.is_dir():
            continue
        require(path.is_file(), 'PACKAGE_SPECIAL_FILE_REJECTED:' + rel)
        require(not ({'.git', '__pycache__', 'node_modules', '.venv', 'venv'} & set(path.relative_to(root).parts)),
                'PACKAGE_RUNTIME_CACHE_REJECTED:' + rel)
        result.add(rel)
    return result


def check_blob(root, row, phase):
    raw = read(root, row[phase + '_path'])
    require(digest(raw) == row[phase + '_sha256'], 'SOURCE_SHA_MISMATCH:' + row[phase + '_path'])
    require(type(row[phase + '_bytes']) is int and len(raw) == row[phase + '_bytes'],
            'SOURCE_SIZE_MISMATCH:' + row[phase + '_path'])


def check_sources(root, mapping, *, release=False):
    rows = mapping.get('files')
    require(isinstance(rows, list), 'SOURCE_MAP_FILES_REQUIRED')
    expected = set(RELEASE_PATHS) if release else {(g, p) for g, paths in APP_PATHS.items() for p in paths}
    observed = []
    after_paths, before_paths = set(), set()
    for row in rows:
        require(isinstance(row, dict), 'SOURCE_MAP_ROW_INVALID')
        rel = relative(row['relative_path'])
        key = rel if release else (row['group'], rel)
        require(key in expected, 'SOURCE_PATH_OUTSIDE_REVIEW:' + rel)
        require(key not in observed, 'SOURCE_PATH_DUPLICATE:' + rel)
        observed.append(key)
        operation = row['operation']
        before_prefix = 'release_tools/before/' if release else 'before/' + row['group'] + '/'
        after_prefix = 'release_tools/after/' if release else 'after/' + row['group'] + '/'
        require(row['after_path'] == after_prefix + rel, 'SOURCE_AFTER_PATH_MISMATCH:' + rel)
        if not release and rel == 'stage_center/research_read_binding.py':
            require(operation == 'add' and row.get('before_path') is None
                    and row.get('before_sha256') is None and row.get('before_bytes') == 0
                    and row.get('accepted_before_sha256') == [], 'ADD_REQUIRES_ABSENT_BEFORE:' + rel)
        else:
            expected_operation = 'unchanged' if release and rel not in RELEASE_MODIFIED else 'modify'
            require(operation == expected_operation, 'SOURCE_OPERATION_MISMATCH:' + rel)
            require(row['before_path'] == before_prefix + rel, 'SOURCE_BEFORE_PATH_MISMATCH:' + rel)
            check_blob(root, row, 'before')
            before_paths.add(row['before_path'])
            if not release:
                require(row.get('accepted_before_sha256') == [row['before_sha256']],
                        'SOURCE_BEFORE_ALLOWLIST_MISMATCH:' + rel)
            if operation == 'unchanged':
                require(row['before_sha256'] == row['after_sha256'], 'UNCHANGED_DEPENDENCY_MODIFIED:' + rel)
        check_blob(root, row, 'after')
        after_paths.add(row['after_path'])
    require(set(observed) == expected, 'SOURCE_REVIEW_SCOPE_INCOMPLETE')
    require(files_under(root, 'release_tools/after' if release else 'after') == after_paths,
            'AFTER_TREE_DIFFERS_FROM_SOURCE_MAP')
    require(files_under(root, 'release_tools/before' if release else 'before') == before_paths,
            'BEFORE_TREE_DIFFERS_FROM_SOURCE_MAP')
    return rows


def expected_patch(root, rows):
    result = []
    for row in sorted(rows, key=lambda value: value['relative_path']):
        if row['operation'] == 'unchanged':
            continue
        added = row['operation'] == 'add'
        before = [] if added else read(root, row['before_path']).decode('utf-8').splitlines(True)
        after = read(root, row['after_path']).decode('utf-8').splitlines(True)
        result.extend(difflib.unified_diff(before, after,
            fromfile='/dev/null' if added else 'a/' + row['relative_path'], tofile='b/' + row['relative_path']))
    return ''.join(result).encode('utf-8')


def check_expectations(root):
    value = document(root, 'TEST_EXPECTATIONS.json')
    require(value.get('schema_version') == 'V4_STAGE_R4_TEST_EXPECTATIONS_V1'
            and value.get('maximum_skipped') == 0, 'TEST_EXPECTATIONS_CONTRACT_INVALID')
    for name in ('expected_tests', 'expected_case_ids', 'suite_files'):
        require(isinstance(value.get(name), dict) and set(value[name]) == set(REQUIRED_SUITES),
                'TEST_EXPECTATIONS_SUITES_INCOMPLETE:' + name)
    for suite in REQUIRED_SUITES:
        count, cases, suite_files = value['expected_tests'][suite], value['expected_case_ids'][suite], value['suite_files'][suite]
        require(type(count) is int and count > 0 and isinstance(cases, list) and len(cases) == count
                and all(isinstance(case, str) and case for case in cases) and len(set(cases)) == count,
                'TEST_EXPECTATIONS_CASES_INVALID:' + suite)
        definitions = files_under(root, 'tests/' + suite)
        if suite == 'api' and (root / 'test_support/r3/checks/api/tests').is_dir():
            definitions |= files_under(root, 'test_support/r3/checks/api/tests')
        require(isinstance(suite_files, dict) and suite_files
                and set(suite_files) == definitions,
                'TEST_DEFINITION_INVENTORY_MISMATCH:' + suite)
        for name, expected in suite_files.items():
            require(digest(read(root, name)) == expected, 'TEST_DEFINITION_SHA_MISMATCH:' + name)
    return value['expected_tests']


def verify(root):
    result = {'status': 'FAIL', 'scope': 'PACKAGE_BYTES_AND_REVIEW_SCOPE_ONLY_NOT_DEPLOYMENT',
              'write_performed': False, 'failures': [], **FLAGS}
    try:
        root = Path(root).resolve(strict=True)
        all_files = files_under(root)
        manifest = document(root, 'DELIVERY_MANIFEST.json')
        require(manifest.get('schema_version') == 'V4_STAGE_R4_DELIVERY_MANIFEST_V1', 'DELIVERY_MANIFEST_SCHEMA_INVALID')
        rows = manifest['files']
        require(isinstance(rows, list) and rows, 'DELIVERY_FILE_INVENTORY_REQUIRED')
        names = [relative(row['path']) for row in rows]
        require(names == sorted(set(names)), 'DELIVERY_FILE_INVENTORY_UNSORTED_OR_DUPLICATE')
        require(set(names) == all_files - {'DELIVERY_MANIFEST.json', 'SHA256SUMS'}, 'DELIVERY_FILE_INVENTORY_MISMATCH')
        for row in rows:
            raw = read(root, row['path'])
            require(type(row['bytes']) is int and len(raw) == row['bytes'] and digest(raw) == row['sha256'],
                    'DELIVERY_BYTES_MISMATCH:' + row['path'])
        checksums = ''.join(digest(read(root, name)) + '  ' + name + '\n'
                            for name in sorted(all_files - {'SHA256SUMS'}))
        require(read(root, 'SHA256SUMS').decode('utf-8') == checksums, 'SHA256SUMS_MISMATCH')
        mapping = document(root, 'SOURCE_MAP.json')
        require(mapping.get('schema_version') == 'V4_STAGE_R4_SOURCE_MAP_V1'
                and mapping.get('base_commit') == BASE_COMMIT, 'SOURCE_MAP_BASE_OR_SCHEMA_MISMATCH')
        require(all(mapping.get(key) is expected for key, expected in FLAGS.items()), 'SAFETY_FLAGS_CHANGED')
        for filename, key in [('CANARY_SOURCE_POLICY.json', 'canary_source_policy_sha256'),
                              ('TEST_EXPECTATIONS.json', 'test_expectations_sha256'),
                              ('TOOLS_SOURCE_MAP.json', 'tools_source_map_sha256')]:
            require(mapping.get(key) == digest(read(root, filename)), 'BOUND_POLICY_SHA_MISMATCH:' + filename)
        policy = document(root, 'CANARY_SOURCE_POLICY.json')
        require(policy.get('schema_version') == 'V4_CANARY_SOURCE_POLICY_V1'
                and set(policy.get('groups', {})) == {'api', 'ui'}, 'CANARY_POLICY_SCOPE_INVALID')
        for group, copy_roots in [('api', ['.']), ('ui', ['apps/web'])]:
            configured = policy['groups'][group]
            require(configured.get('copy_roots') == copy_roots and configured.get('optional_roots', []) == []
                    and configured.get('symlinks', []) == [], 'CANARY_POLICY_CHANGED:' + group)
        app_rows = check_sources(root, mapping)
        release_rows = check_sources(root, document(root, 'TOOLS_SOURCE_MAP.json'), release=True)
        for group in APP_PATHS:
            require(read(root, 'patches/' + group + '-before-to-after.patch') == expected_patch(root,
                    [row for row in app_rows if row['group'] == group]), 'PATCH_DIFFERS_FROM_FULL_IMAGES:' + group)
        require(read(root, 'patches/release-tools-before-to-after.patch') == expected_patch(root, release_rows),
                'PATCH_DIFFERS_FROM_FULL_IMAGES:release')
        expected_tests = check_expectations(root)
        result.update(status='PASS', base_commit=BASE_COMMIT, source_map_sha256=digest(read(root, 'SOURCE_MAP.json')),
                      test_expectations_sha256=digest(read(root, 'TEST_EXPECTATIONS.json')),
                      delivery_manifest_sha256=digest(read(root, 'DELIVERY_MANIFEST.json')),
                      production_files=len(app_rows), release_tool_files=len(release_rows),
                      delivery_files=len(all_files), expected_tests=expected_tests)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        result['failures'].append({'error': str(error), 'type': type(error).__name__})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    result = verify(args.package)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result['status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
