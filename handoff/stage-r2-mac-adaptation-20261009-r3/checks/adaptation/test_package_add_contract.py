"""Exact new-file contract and policy fingerprints, using small synthetic packages."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'tools/verify_package.py'


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(tmp_path):
    root = tmp_path / 'synthetic_package'
    relative = 'apps/web/src/components/review/StageExecutionEvidencePanel.vue'
    after = '<template><p>explicit synthetic new file</p></template>\n'
    after_path = 'after/ui/' + relative
    sha = write(root / after_path, after)
    write(root / ('checks/api/after/' + relative), after)
    item = {'group': 'ui', 'operation': 'add', 'relative_path': relative,
            'before_path': None, 'before_sha256': None, 'accepted_before_sha256': [],
            'after_path': after_path, 'after_sha256': sha}
    mapping = {'base_commit': 'SYNTHETIC_TEST_ONLY', 'files': [item], 'RESEARCH_ONLY': True,
               'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    write(root / 'SOURCE_MAP.json', json.dumps(mapping))
    for group in ('stage', 'api', 'ui'):
        patch = ''.join(difflib.unified_diff([], after.splitlines(True), fromfile='/dev/null', tofile='b/' + relative)) if group == 'ui' else ''
        write(root / f'patches/{group}-before-to-after.patch', patch)
    write(root / 'test_support/SOURCE_MANIFEST.json', '{"files": []}')
    ref = write(root / 'test_support/api_projection_reference.py', '# synthetic projection reference\n')
    write(root / 'test_support/API_PROJECTION_REFERENCE.json', json.dumps({'fixture_file_sha256': ref}))
    return root, mapping


def run(root):
    result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--package', str(root)],
                            capture_output=True, text=True)
    assert result.stderr == ''
    return result.returncode, json.loads(result.stdout)


def test_explicit_absent_before_with_dev_null_patch_is_valid_new_file(tmp_path):
    root, _ = package(tmp_path)
    code, result = run(root)
    assert code == 0, result
    assert result['status'] == 'PASS'


@pytest.mark.parametrize('mutation', ['missing_add', 'invented_before', 'accepted_before', 'unknown_operation'])
def test_ambiguous_or_fabricated_new_file_contract_rejected(tmp_path, mutation):
    root, mapping = package(tmp_path)
    item = mapping['files'][0]
    if mutation == 'missing_add':
        del item['operation']
    elif mutation == 'invented_before':
        item['before_sha256'] = '0' * 64
    elif mutation == 'accepted_before':
        item['accepted_before_sha256'] = ['0' * 64]
    else:
        item['operation'] = 'replace_whatever'
    write(root / 'SOURCE_MAP.json', json.dumps(mapping))
    code, result = run(root)
    assert code != 0
    assert result['status'] == 'FAIL'


@pytest.mark.parametrize('name,key', [('CANARY_SOURCE_POLICY.json', 'canary_source_policy_sha256'),
                                      ('TEST_EXPECTATIONS.json', 'test_expectations_sha256')])
def test_tool_policy_bytes_must_match_reviewed_source_map(tmp_path, name, key):
    root, mapping = package(tmp_path)
    mapping[key] = write(root / name, '{"synthetic": true}\n')
    write(root / 'SOURCE_MAP.json', json.dumps(mapping))
    assert run(root)[0] == 0
    write(root / name, '{"synthetic": false}\n')
    code, result = run(root)
    assert code != 0
    assert result['status'] == 'FAIL'


def test_unbound_existing_policy_file_is_rejected(tmp_path):
    root, _ = package(tmp_path)
    write(root / 'CANARY_SOURCE_POLICY.json', '{"synthetic": true}\n')
    code, result = run(root)
    assert code != 0
    assert result['status'] == 'FAIL'
