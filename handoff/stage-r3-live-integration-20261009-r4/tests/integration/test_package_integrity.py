"""Delivery acceptance binds executable bytes, review scope and complete inventories."""
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


TOOLS = Path(os.environ.get('R4_TOOL_ROOT', Path(__file__).resolve().parents[1] / 'tools'))


def verifier():
    spec = importlib.util.spec_from_file_location('_r4_package_verifier', TOOLS / 'verify_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def dump(path, value):
    write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def seal(root):
    paths = sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                   if p.is_file() and p.name not in {'DELIVERY_MANIFEST.json', 'SHA256SUMS'})
    dump(root / 'DELIVERY_MANIFEST.json', {
        'schema_version': 'V4_STAGE_R4_DELIVERY_MANIFEST_V1',
        'files': [{'path': p, 'sha256': sha(root / p), 'bytes': (root / p).stat().st_size} for p in paths]})
    paths.append('DELIVERY_MANIFEST.json')
    write(root / 'SHA256SUMS', ''.join(f'{sha(root / p)}  {p}\n' for p in sorted(paths)))


def patch(root, rows):
    parts = []
    for row in sorted(rows, key=lambda r: r['relative_path']):
        if row['operation'] == 'unchanged':
            continue
        before = [] if row['operation'] == 'add' else (root / row['before_path']).read_text().splitlines(True)
        parts.extend(difflib.unified_diff(before, (root / row['after_path']).read_text().splitlines(True),
                     fromfile='/dev/null' if row['operation'] == 'add' else 'a/' + row['relative_path'],
                     tofile='b/' + row['relative_path']))
    return ''.join(parts)


@pytest.fixture
def package(tmp_path):
    root = tmp_path / 'package'; root.mkdir()
    tool = verifier()
    entries = []
    for group, paths in tool.APP_PATHS.items():
        for relative in paths:
            added = relative == 'stage_center/research_read_binding.py'
            before = None if added else f'before/{group}/{relative}'
            after = f'after/{group}/{relative}'
            if before:
                write(root / before, '# reviewed before\n')
            write(root / after, '# reviewed after\n')
            entries.append({'group': group, 'relative_path': relative,
                            'operation': 'add' if added else 'modify',
                            'before_path': before, 'before_sha256': sha(root / before) if before else None,
                            'before_bytes': (root / before).stat().st_size if before else 0,
                            'accepted_before_sha256': [sha(root / before)] if before else [],
                            'after_path': after, 'after_sha256': sha(root / after),
                            'after_bytes': (root / after).stat().st_size})
    release = []
    for relative in tool.RELEASE_PATHS:
        changed = relative in tool.RELEASE_MODIFIED
        before, after = f'release_tools/before/{relative}', f'release_tools/after/{relative}'
        write(root / before, '# original release tool\n')
        write(root / after, '# modified release tool\n' if changed else '# original release tool\n')
        release.append({'relative_path': relative, 'operation': 'modify' if changed else 'unchanged',
                        'before_path': before, 'before_sha256': sha(root / before),
                        'before_bytes': (root / before).stat().st_size,
                        'after_path': after, 'after_sha256': sha(root / after),
                        'after_bytes': (root / after).stat().st_size})
    dump(root / 'TOOLS_SOURCE_MAP.json', {'files': release})
    for group in tool.APP_PATHS:
        write(root / f'patches/{group}-before-to-after.patch', patch(root, [r for r in entries if r['group'] == group]))
    write(root / 'patches/release-tools-before-to-after.patch', patch(root, release))
    expectations = {'schema_version': 'V4_STAGE_R4_TEST_EXPECTATIONS_V1', 'maximum_skipped': 0,
                    'expected_tests': {}, 'expected_case_ids': {}, 'suite_files': {}}
    for suite in tool.REQUIRED_SUITES:
        path = f'tests/{suite}/' + ('fixture.test.mjs' if suite == 'ui' else 'test_fixture.py')
        write(root / path, '// fixture\n' if suite == 'ui' else '# fixture\n')
        expectations['expected_tests'][suite] = 1
        expectations['expected_case_ids'][suite] = ['one' if suite == 'ui' else 'test_fixture::one']
        expectations['suite_files'][suite] = {path: sha(root / path)}
    dump(root / 'TEST_EXPECTATIONS.json', expectations)
    dump(root / 'CANARY_SOURCE_POLICY.json', {'schema_version': 'V4_CANARY_SOURCE_POLICY_V1',
        'groups': {'api': {'copy_roots': ['.']}, 'ui': {'copy_roots': ['apps/web']}}})
    mapping = {'schema_version': 'V4_STAGE_R4_SOURCE_MAP_V1', 'base_commit': tool.BASE_COMMIT,
               'files': sorted(entries, key=lambda r: (r['group'], r['relative_path'])), **tool.FLAGS,
               'test_expectations_sha256': sha(root / 'TEST_EXPECTATIONS.json'),
               'tools_source_map_sha256': sha(root / 'TOOLS_SOURCE_MAP.json'),
               'canary_source_policy_sha256': sha(root / 'CANARY_SOURCE_POLICY.json')}
    dump(root / 'SOURCE_MAP.json', mapping)
    seal(root)
    return root


def rewrite_map(package, name, mutate):
    value = json.loads((package / name).read_text()); mutate(value)
    dump(package / name, value); seal(package)


def test_complete_reviewed_package_passes_without_writing(package):
    before = {str(p.relative_to(package)): sha(p) for p in package.rglob('*') if p.is_file()}
    result = verifier().verify(package)
    assert result['status'] == 'PASS', result
    assert result['production_files'] == 7
    assert result['release_tool_files'] == 9
    assert result['write_performed'] is False
    assert before == {str(p.relative_to(package)): sha(p) for p in package.rglob('*') if p.is_file()}


@pytest.mark.parametrize('defect', ['changed_bytes', 'undeclared_file', 'symlink', 'checksum_only', 'missing_manifest'])
def test_delivery_inventory_rejects_incomplete_or_changed_package(package, tmp_path, defect):
    selected = package / 'after/api/stage_center/consumer.py'
    if defect == 'changed_bytes': selected.write_text('# altered source\n')
    if defect == 'undeclared_file': write(package / 'extra.txt', 'unreviewed\n')
    if defect == 'symlink':
        outside = tmp_path / 'outside'; outside.write_bytes(selected.read_bytes())
        selected.unlink(); selected.symlink_to(outside)
    if defect == 'checksum_only': (package / 'SHA256SUMS').write_text('')
    if defect == 'missing_manifest': (package / 'DELIVERY_MANIFEST.json').unlink()
    assert verifier().verify(package)['status'] == 'FAIL'


@pytest.mark.parametrize('defect', ['unmapped_after', 'add_with_preimage', 'wrong_before_sha', 'path_escape',
                                  'missing_owned_file', 'changed_patch', 'unsafe_flags', 'unbound_tests',
                                  'changed_test', 'unfrozen_regression', 'release_dependency_changed', 'release_scope_expanded'])
def test_even_resealed_bytes_must_match_review_scope(package, defect):
    if defect == 'unmapped_after': write(package / 'after/api/unreviewed.py', '# extra\n'); seal(package)
    elif defect == 'add_with_preimage':
        def mutate(value):
            row = next(r for r in value['files'] if r['operation'] == 'add')
            row['before_sha256'] = 'a' * 64
        rewrite_map(package, 'SOURCE_MAP.json', mutate)
    elif defect == 'wrong_before_sha':
        rewrite_map(package, 'SOURCE_MAP.json', lambda v: v['files'][0].update(before_sha256='a' * 64))
    elif defect == 'path_escape':
        rewrite_map(package, 'SOURCE_MAP.json', lambda v: v['files'][0].update(after_path='../outside.py'))
    elif defect == 'missing_owned_file':
        rewrite_map(package, 'SOURCE_MAP.json', lambda v: v['files'].pop())
    elif defect == 'changed_patch': write(package / 'patches/ui-before-to-after.patch', ''); seal(package)
    elif defect == 'unsafe_flags':
        rewrite_map(package, 'SOURCE_MAP.json', lambda v: v.update(production_allowed=True))
    elif defect == 'unbound_tests':
        rewrite_map(package, 'SOURCE_MAP.json', lambda v: v.update(test_expectations_sha256='b' * 64))
    elif defect == 'changed_test': write(package / 'tests/api/test_fixture.py', '# replaced tests\n'); seal(package)
    elif defect == 'unfrozen_regression':
        write(package / 'test_support/r3/checks/api/tests/test_extra.py', '# unreviewed regression definition\n'); seal(package)
    elif defect == 'release_dependency_changed':
        selected = package / 'release_tools/after/ops/release_candidate_sources.py'
        write(selected, '# changed frozen dependency\n')
        def mutate(value):
            row = next(r for r in value['files'] if r['relative_path'].endswith('release_candidate_sources.py'))
            row['after_sha256'], row['after_bytes'] = sha(selected), selected.stat().st_size
        rewrite_map(package, 'TOOLS_SOURCE_MAP.json', mutate)
    elif defect == 'release_scope_expanded':
        write(package / 'release_tools/after/ops/unreviewed_publisher.py', '# extra\n'); seal(package)
    assert verifier().verify(package)['status'] == 'FAIL'
