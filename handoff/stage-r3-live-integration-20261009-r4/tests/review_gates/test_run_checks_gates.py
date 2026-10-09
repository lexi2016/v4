"""Independent acceptance gates: frozen files, exact cases, and real zero-exit skips."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def runner():
    home = Path(os.environ.get('R4_TOOL_ROOT', Path(__file__).resolve().parents[1] / 'delivery_tools'))
    spec = importlib.util.spec_from_file_location('independent_r4_gate_runner', home / 'run_checks.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junit(path, cases, **totals):
    values = {'tests': len(cases), 'skipped': 0, 'failures': 0, 'errors': 0, **totals}
    attrs = ' '.join(f'{key}="{value}"' for key, value in values.items())
    write(path, '<testsuites><testsuite ' + attrs + '>' + ''.join(cases) + '</testsuite></testsuites>')


def case(name='one', child=''):
    return f'<testcase classname="tests.api.test_fixture" name="{name}">{child}</testcase>'


def tap(*, name='one', assertion='ok 1 - one', tests=1, passed=1, skipped=0, failed=0,
        cancelled=0, todo=0, plan='1..1'):
    return (f'TAP version 13\n# Subtest: {name}\n{assertion}\n{plan}\n'
            f'# tests {tests}\n# pass {passed}\n# fail {failed}\n# cancelled {cancelled}\n'
            f'# skipped {skipped}\n# todo {todo}\n')


def miniature(package):
    tool = runner()
    value = {'schema_version': 'V4_STAGE_R4_TEST_EXPECTATIONS_V1', 'maximum_skipped': 0,
             'expected_tests': {name: 1 for name in tool.REQUIRED_SUITES},
             'expected_case_ids': {name: ['test_fixture::one'] if name != 'ui' else ['one']
                                   for name in tool.REQUIRED_SUITES}, 'suite_files': {}}
    for name in tool.REQUIRED_SUITES:
        relative = f'tests/{name}/' + ('one.test.mjs' if name == 'ui' else 'test_fixture.py')
        write(package / relative, '// test definition\n' if name == 'ui' else '# test definition\n')
        value['suite_files'][name] = {relative: digest(package / relative)}
        if name == 'api':
            legacy = 'test_support/r3/checks/api/tests/test_legacy.py'
            write(package / legacy, '# pinned legacy API tests\n')
            value['suite_files'][name][legacy] = digest(package / legacy)
    save_spec(package, value)
    return value


def save_spec(package, value, bound=True):
    path = package / 'TEST_EXPECTATIONS.json'
    write(path, json.dumps(value, sort_keys=True) + '\n')
    write(package / 'SOURCE_MAP.json', json.dumps({'test_expectations_sha256': digest(path) if bound else 'f' * 64}) + '\n')


def test_junit_exact_complete_cases_pass(tmp_path):
    path = tmp_path / 'result.xml'; junit(path, [case()])
    result = runner().junit_gate(path, 1, ['test_fixture::one'])
    assert result['status'] == 'PASS'
    assert result['case_ids'] == ['test_fixture::one']


def test_api_aggregate_preserves_original_reports_and_distinguishes_same_named_cases(tmp_path):
    first, second, combined = (tmp_path / name for name in ('first.xml', 'second.xml', 'combined.xml'))
    junit(first, [case()]); junit(second, [case()])
    original = {path: path.read_bytes() for path in (first, second)}
    module = runner()
    proof = module.aggregate_api_junit({'r4': first, 'r3': second}, combined)
    result = module.junit_gate(combined, 2, ['r4/test_fixture::one', 'r3/test_fixture::one'])
    assert result['status'] == 'PASS'
    assert proof == {name: {'path': str(path), 'sha256': digest(path)} for name, path in (('r4', first), ('r3', second))}
    assert original == {path: path.read_bytes() for path in (first, second)}


def test_real_pytest_commands_preserve_ids_inside_and_outside_the_package(tmp_path):
    package, output = tmp_path / 'package', tmp_path / 'test_output'
    package.mkdir(); output.mkdir()
    write(output / 'pytest.ini', '[pytest]\n')
    module = runner(); observed = {}
    for label, folder in [('inside', package / 'test_container/tests'),
                          ('release', output / 'work/release/tests')]:
        write(folder / 'test_fixture.py', 'def test_one():\n    assert True\n')
        result = subprocess.run(module.pytest_command(package, output, label, folder), cwd=package,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        observed[label] = module.junit_gate(output / (label + '.junit.xml'), 1, ['test_fixture::test_one'])
    assert {name: value['status'] for name, value in observed.items()} == {'inside': 'PASS', 'release': 'PASS'}, observed


@pytest.mark.parametrize('defect', ['missing', 'declared_only', 'skip', 'failure', 'error',
                                  'wrong_id', 'duplicate_id', 'count_changed'])
def test_junit_incomplete_or_substituted_cases_fail(tmp_path, defect):
    path = tmp_path / 'result.xml'
    if defect == 'declared_only': junit(path, [], tests=1)
    elif defect == 'skip': junit(path, [case(child='<skipped/>')], skipped=1)
    elif defect == 'failure': junit(path, [case(child='<failure/>')], failures=1)
    elif defect == 'error': junit(path, [case(child='<error/>')], errors=1)
    elif defect == 'wrong_id': junit(path, [case('replacement')])
    elif defect == 'duplicate_id': junit(path, [case(), case()])
    elif defect == 'count_changed': junit(path, [case(), case('two')])
    assert runner().junit_gate(path, 1, ['test_fixture::one'])['status'] == 'FAIL'


def test_tap_exact_complete_cases_pass():
    result = runner().tap_gate(tap(), 1, ['one'])
    assert result['status'] == 'PASS'
    assert result['case_ids'] == ['one']


@pytest.mark.parametrize('defect', ['summary_only', 'missing_plan', 'duplicate_plan', 'wrong_plan',
                                  'wrong_id', 'duplicate_id', 'not_ok', 'number_gap',
                                  'skip_directive', 'todo_directive', 'skipped', 'cancelled',
                                  'todo', 'fewer'])
def test_tap_incomplete_or_substituted_cases_fail(defect):
    values = {
        'summary_only': '# tests 1\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n',
        'missing_plan': tap(plan=''), 'duplicate_plan': tap(plan='1..1\n1..1'),
        'wrong_plan': tap(plan='1..2'), 'wrong_id': tap(assertion='ok 1 - replacement'),
        'duplicate_id': tap(assertion='ok 1 - one\nok 2 - one', tests=2, passed=2, plan='1..2'),
        'not_ok': tap(assertion='not ok 1 - one'), 'number_gap': tap(assertion='ok 2 - one'),
        'skip_directive': tap(assertion='ok 1 - one # SKIP'),
        'todo_directive': tap(assertion='ok 1 - one # TODO'),
        'skipped': tap(skipped=1), 'cancelled': tap(cancelled=1), 'todo': tap(todo=1),
        'fewer': tap(tests=0, passed=0),
    }
    assert runner().tap_gate(values[defect], 1, ['one'])['status'] == 'FAIL'


def test_bound_expectations_accept_only_the_frozen_test_files(tmp_path):
    package = tmp_path / 'package'; miniature(package)
    value, observed = runner().load_expectations(package)
    assert set(value['expected_tests']) == set(runner().REQUIRED_SUITES)
    assert observed == digest(package / 'TEST_EXPECTATIONS.json')


@pytest.mark.parametrize('defect', ['unbound_sha', 'zero_count', 'missing_suite', 'extra_suite',
                                  'wrong_id_count', 'duplicate_id', 'missing_file', 'changed_file',
                                  'added_file', 'outside_path', 'symlink_file'])
def test_expectations_reject_unreviewed_counts_cases_or_files(tmp_path, defect):
    package = tmp_path / 'package'; value = miniature(package)
    selected = package / 'tests/api/test_fixture.py'
    if defect == 'zero_count': value['expected_tests']['api'] = 0
    if defect == 'missing_suite': value['expected_tests'].pop('api')
    if defect == 'extra_suite': value['expected_tests']['other'] = 1
    if defect == 'wrong_id_count': value['expected_case_ids']['api'] = []
    if defect == 'duplicate_id':
        value['expected_case_ids']['api'] = ['test_fixture::one', 'test_fixture::one']
        value['expected_tests']['api'] = 2
    if defect == 'missing_file': selected.unlink()
    if defect == 'changed_file': selected.write_text('# substituted test\n')
    if defect == 'added_file': write(package / 'tests/api/test_added.py', '# added test\n')
    if defect == 'outside_path': value['suite_files']['api'] = {'outside.py': 'a' * 64}
    if defect == 'symlink_file':
        target = tmp_path / 'outside.py'; target.write_bytes(selected.read_bytes())
        selected.unlink(); selected.symlink_to(target)
    save_spec(package, value, bound=defect != 'unbound_sha')
    with pytest.raises((ValueError, OSError, KeyError, TypeError)):
        runner().load_expectations(package)


@pytest.mark.parametrize('framework', ['pytest', 'node'])
def test_real_zero_exit_skipped_process_is_rejected(tmp_path, framework):
    if framework == 'pytest':
        path = tmp_path / 'test_real.py'
        write(path, "import pytest\n@pytest.mark.skip(reason='real skipped process')\ndef test_one():\n    assert True\n")
        xml = tmp_path / 'result.xml'
        process = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                                  str(path), '--junitxml=' + str(xml)], capture_output=True, text=True,
                                 env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        gate = runner().junit_gate(xml, 1, ['test_real::test_one'])
    else:
        path = tmp_path / 'real.test.mjs'
        write(path, "import test from 'node:test';\ntest('one', {skip:'real skipped process'}, () => {});\n")
        node = shutil.which('node'); assert node is not None
        process = subprocess.run([node, '--test', '--test-reporter=tap', str(path)], capture_output=True, text=True)
        gate = runner().tap_gate(process.stdout, 1, ['one'])
    assert process.returncode == 0, process.stderr
    assert gate['status'] == 'FAIL'


def test_fixture_gate_requires_actual_receipt_and_responses(tmp_path):
    with pytest.raises((ValueError, OSError)):
        runner().validate_fixture(tmp_path / 'missing_fixture', {}, 'a' * 64)


def test_review_output_cannot_overlap_any_input(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    with pytest.raises((ValueError, OSError)):
        runner().new_output(source / 'nested', [source])
    assert not (source / 'nested').exists()
