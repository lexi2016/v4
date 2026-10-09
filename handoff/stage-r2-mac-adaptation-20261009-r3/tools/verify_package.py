#!/usr/bin/env python3
"""Verify this code package's exact bytes; never inspect or change a runtime."""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    root = Path(root).resolve()
    mapping = json.loads((root / 'SOURCE_MAP.json').read_text())
    failures = []
    entries = mapping['files']
    valid_entries = []
    for item in entries:
        operation = item.get('operation', 'modify')
        if operation == 'add':
            if (item.get('before_path') is not None or item.get('before_sha256') is not None
                    or item.get('accepted_before_sha256') != []):
                failures.append({'error': 'ADD_REQUIRES_EXPLICIT_ABSENT_BEFORE', 'path': item['relative_path']})
                continue
            phases = ('after',)
        elif operation == 'modify' and item.get('before_path') and item.get('before_sha256'):
            phases = ('before', 'after')
        else:
            failures.append({'error': 'INVALID_SOURCE_OPERATION_OR_BEFORE', 'path': item['relative_path']})
            continue
        valid_entries.append(item)
        for phase in phases:
            path = root / item[phase + '_path']
            observed = digest(path) if path.is_file() else None
            if observed != item[phase + '_sha256']:
                failures.append({'path': item[phase + '_path'], 'expected': item[phase + '_sha256'], 'observed': observed})
    after_files = {str(p.relative_to(root)) for p in (root / 'after').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if after_files != {item['after_path'] for item in entries}:
        failures.append({'error': 'AFTER_TREE_DIFFERS_FROM_SOURCE_MAP'})
    for group in ('stage', 'api', 'ui'):
        expected = []
        for item in valid_entries:
            if item['group'] != group:
                continue
            added = item.get('operation') == 'add'
            expected.extend(difflib.unified_diff(
                [] if added else (root / item['before_path']).read_text().splitlines(True),
                (root / item['after_path']).read_text().splitlines(True),
                fromfile='/dev/null' if added else 'a/' + item['relative_path'], tofile='b/' + item['relative_path']))
        if (root / 'patches' / (group + '-before-to-after.patch')).read_text() != ''.join(expected):
            failures.append({'error': 'PATCH_DIFFERS_FROM_FULL_BEFORE_AFTER', 'group': group})
    support = json.loads((root / 'test_support/SOURCE_MANIFEST.json').read_text())
    for item in support['files']:
        path = root / 'test_support/stage_base_app' / item['path']
        if not path.is_file() or digest(path) != item['sha256']:
            failures.append({'error': 'OFFLINE_SUPPORT_SHA_MISMATCH', 'path': item['path']})
    projection = json.loads((root / 'test_support/API_PROJECTION_REFERENCE.json').read_text())
    if digest(root / 'test_support/api_projection_reference.py') != projection['fixture_file_sha256']:
        failures.append({'error': 'ORIGINAL_API_PROJECTION_REFERENCE_SHA_MISMATCH'})
    for filename, key in (('CANARY_SOURCE_POLICY.json', 'canary_source_policy_sha256'),
                          ('TEST_EXPECTATIONS.json', 'test_expectations_sha256')):
        path = root / filename
        if key in mapping or path.exists():
            observed = digest(path) if path.is_file() and not path.is_symlink() else None
            if not mapping.get(key) or observed != mapping[key]:
                failures.append({'error': 'TOOL_POLICY_SHA_MISMATCH', 'path': filename,
                                 'expected': mapping.get(key), 'observed': observed})
    for item in entries:
        if item['group'] == 'api':
            reference = ('checks/api/after/source/actual_api/' if item['relative_path'].endswith('execution_evidence.py')
                         else 'checks/api/after/conditional_api/') + item['relative_path']
        elif item['group'] == 'ui':
            reference = 'checks/api/after/' + item['relative_path']
        else:
            continue
        if digest(root / reference) != item['after_sha256']:
            failures.append({'error': 'TESTED_API_UI_COPY_DIFFERS', 'path': reference})
    flags = {key: mapping.get(key) for key in ('RESEARCH_ONLY', 'production_allowed', 'buy_gate_updated', 'orders_sent')}
    if flags != {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}:
        failures.append({'error': 'SAFETY_FLAGS_CHANGED'})
    return {'status': 'PASS' if not failures else 'FAIL', 'scope': 'PACKAGE_BYTES_ONLY_NOT_DEPLOYMENT',
            'base_commit': mapping['base_commit'], 'source_map_sha256': digest(root / 'SOURCE_MAP.json'),
            'production_files': len(entries), 'offline_support_files': len(support['files']),
            'failures': failures, 'write_performed': False, **flags}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = verify(args.package)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'status': 'FAIL', 'error': str(error), 'write_performed': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
