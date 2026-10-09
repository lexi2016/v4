#!/usr/bin/env python3
"""Run frozen R4 checks in a NEW output; no live service or market I/O.

Retains R3 JUnit/TAP outcome accounting and additionally requires frozen case
identities, source files, real TAP assertions and its plan. Expectations are
pinned by SOURCE_MAP and are never learned from the current test run.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
REQUIRED_SUITES = ('api', 'ui', 'release', 'integration', 'review_gates')
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
IGNORED = {'__pycache__', '.pytest_cache'}
SCOPE = 'ISOLATED_SOURCE_FIXTURE_AND_COMPILED_VUE_TESTS_NOT_LIVE_HTTP_DEPLOYMENT_OR_NATURAL_ACCEPTANCE'
R3_READER = 'checks/api/after/source/actual_api/stage_center/execution_evidence.py'
R3_CONSUMER = 'checks/api/after/conditional_api/stage_center/consumer.py'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def no_links(path):
    for part in (Path(path), *Path(path).parents):
        if part.is_symlink():
            raise ValueError('SYMLINK_PATH_NOT_ALLOWED:' + str(part))


def regular(path):
    path = Path(path); no_links(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('REGULAR_FILE_REQUIRED:' + str(path))
        raw = stream.read(); after = os.fstat(stream.fileno())
    current = path.stat(); no_links(path)
    token = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                           value.st_mtime_ns, value.st_ctime_ns)
    if token(before) != token(after) or token(before) != token(current) or len(raw) != before.st_size:
        raise ValueError('INPUT_CHANGED_DURING_READ:' + str(path))
    return raw


def read_json(path):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value: raise ValueError('DUPLICATE_JSON_KEY:' + key)
            value[key] = item
        return value
    def invalid(value): raise ValueError('INVALID_JSON_CONSTANT:' + value)
    value = json.loads(regular(path), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict): raise ValueError('JSON_OBJECT_REQUIRED:' + str(path))
    return value


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or '\x00' in value
            or PurePosixPath(value).is_absolute() or str(PurePosixPath(value)) != value
            or any(part in {'.', '..'} for part in PurePosixPath(value).parts)):
        raise ValueError('CANONICAL_RELATIVE_PATH_REQUIRED')
    return value


def exact_directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts: raise ValueError('ABSOLUTE_DIRECTORY_REQUIRED')
    no_links(path)
    if not path.is_dir(): raise ValueError('DIRECTORY_MISSING:' + str(path))
    return path


def new_output(path, inputs):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts: raise ValueError('ABSOLUTE_NEW_OUTPUT_REQUIRED')
    no_links(path); exact_directory(path.parent)
    if os.path.lexists(path): raise ValueError('OUTPUT_ALREADY_EXISTS')
    if any(path == root or root in path.parents or path in root.parents for root in map(Path, inputs)):
        raise ValueError('OUTPUT_OVERLAPS_INPUT')
    return path


def suite_roots(suite):
    return ['tests/' + suite] + (['test_support/r3/checks/api/tests'] if suite == 'api' else [])


def suite_inventory(package, suite):
    result = {}
    for relative_root in suite_roots(suite):
        folder = exact_directory(package / relative_root)
        for path in sorted(folder.rglob('*')):
            no_links(path)
            if any(part in IGNORED for part in path.relative_to(folder).parts): continue
            if path.is_file(): result[path.relative_to(package).as_posix()] = digest(regular(path))
            elif not path.is_dir(): raise ValueError('SPECIAL_TEST_SOURCE_ENTRY:' + str(path))
    return result


def load_expectations(package):
    """Frozen reviewed counts, IDs and files, never current output counts."""
    package = Path(package); path = package / 'TEST_EXPECTATIONS.json'
    raw = regular(path); value = read_json(path)
    counts, ids, files = (value[key] for key in ('expected_tests', 'expected_case_ids', 'suite_files'))
    if (value.get('schema_version') != 'V4_STAGE_R4_TEST_EXPECTATIONS_V1'
            or set(counts) != set(REQUIRED_SUITES) or set(ids) != set(REQUIRED_SUITES)
            or set(files) != set(REQUIRED_SUITES)
            or any(type(number) is not int or number < 1 for number in counts.values())
            or value.get('maximum_skipped') != 0):
        raise ValueError('EXACT_REQUIRED_SUITE_COUNTS_AND_ZERO_SKIPS_REQUIRED')
    if read_json(package / 'SOURCE_MAP.json').get('test_expectations_sha256') != digest(raw):
        raise ValueError('TEST_EXPECTATIONS_SOURCE_MAP_SHA_MISMATCH')
    for suite in REQUIRED_SUITES:
        names, pinned = ids[suite], files[suite]
        if (not isinstance(names, list) or len(names) != counts[suite]
                or any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != len(names)):
            raise ValueError('FROZEN_TESTCASE_IDS_INVALID:' + suite)
        if not isinstance(pinned, dict) or not pinned: raise ValueError('FROZEN_TEST_FILES_REQUIRED:' + suite)
        for name, expected in pinned.items():
            if (not any(relative(name).startswith(root + '/') for root in suite_roots(suite))
                    or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)):
                raise ValueError('FROZEN_TEST_FILE_PIN_INVALID:' + suite)
        if suite_inventory(package, suite) != pinned:
            raise ValueError('FROZEN_TEST_FILE_SET_OR_SHA_MISMATCH:' + suite)
    return value, digest(raw)


def junit_case_id(case):
    """Portable pytest module/class/name; API aggregate prefixes r3/ or r4/."""
    parts = case.get('classname', '').split('.')
    prefix = parts[0] + '/' if parts[0] in {'r3', 'r4'} else ''
    start = next((i for i in range(len(parts) - 1, -1, -1) if parts[i].startswith('test_')), len(parts) - 1)
    owner, name = '.'.join(parts[start:]), case.get('name')
    if not owner or not isinstance(name, str) or not name: raise ValueError('JUNIT_TESTCASE_ID_MISSING')
    return prefix + owner + '::' + name


def _case_identity_gate(detail, observed, expected_ids):
    detail['case_ids'] = observed
    if len(set(observed)) != len(observed): detail.update(status='FAIL', reason='DUPLICATE_TESTCASE_ID')
    if expected_ids is not None and sorted(observed) != sorted(expected_ids):
        detail.update(status='FAIL', reason='FROZEN_TESTCASE_IDS_MISMATCH')
    return detail


def junit_gate(path, expected, expected_ids=None):
    """Accepted R3 testcase/declared-total accounting plus exact IDs."""
    detail = {'status': 'FAIL', 'expected_tests': expected, 'observed_tests': None,
              'passed': None, 'skipped': None, 'failures': None, 'errors': None}
    try:
        raw = regular(path); root = ET.fromstring(raw); cases = root.findall('.//testcase')
        suites = [root] if root.tag == 'testsuite' else root.findall('./testsuite')
        if root.tag not in ('testsuite', 'testsuites') or not suites: raise ValueError('missing JUnit testsuite')
        observed = {'tests': len(cases), 'skipped': sum(c.find('skipped') is not None for c in cases),
                    'failures': sum(c.find('failure') is not None for c in cases),
                    'errors': sum(c.find('error') is not None for c in cases)}
        declared = {name: sum(int(s.attrib[name]) for s in suites) for name in observed}
        if declared != observed or any(value < 0 for value in declared.values()):
            raise ValueError('JUnit declared totals do not match testcase outcomes')
        passed = sum(not any(c.find(name) is not None for name in ('skipped', 'failure', 'error')) for c in cases)
        detail.update(observed_tests=observed['tests'], passed=passed, skipped=observed['skipped'],
                      failures=observed['failures'], errors=observed['errors'], declared=declared, junit_sha256=digest(raw))
        if observed['tests'] == expected and passed == expected and not any(observed[k] for k in ('skipped', 'failures', 'errors')):
            detail['status'] = 'PASS'
        else: detail['reason'] = 'EXACT_COUNT_AND_ZERO_SKIPS_FAILURES_ERRORS_REQUIRED'
        _case_identity_gate(detail, [junit_case_id(case) for case in cases], expected_ids)
    except (OSError, ET.ParseError, ValueError, KeyError) as error:
        detail.update(status='FAIL', reason='JUNIT_MISSING_OR_INVALID', detail=str(error))
    return detail


def tap_gate(stdout, expected, expected_ids=None):
    """Accepted R3 summary accounting plus real flat assertions, plan and IDs."""
    detail = {'status': 'FAIL', 'expected_tests': expected, 'observed_tests': None,
              'passed': None, 'skipped': None, 'failures': None, 'cancelled': None, 'todo': None}
    values = {}
    for name in ('tests', 'pass', 'fail', 'skipped', 'cancelled', 'todo'):
        matches = re.findall(r'^# ' + name + r' (\d+)\s*$', stdout, re.M)
        if len(matches) != 1:
            detail['reason'] = 'TAP_SUMMARY_MISSING_OR_AMBIGUOUS'; return detail
        values[name] = int(matches[0])
    detail.update(observed_tests=values['tests'], passed=values['pass'], failures=values['fail'],
                  skipped=values['skipped'], cancelled=values['cancelled'], todo=values['todo'])
    if values['tests'] == expected and values['pass'] == expected and not any(values[k] for k in ('fail', 'skipped', 'cancelled', 'todo')):
        detail['status'] = 'PASS'
    else: detail['reason'] = 'EXACT_COUNT_AND_ZERO_SKIPS_FAILURES_CANCELLED_TODO_REQUIRED'
    assertions = re.findall(r'^(ok|not ok) (\d+) - (.+)$', stdout, re.M)
    plans = re.findall(r'^1\.\.(\d+)\s*$', stdout, re.M)
    if (plans != [str(expected)] or len(assertions) != expected
            or [int(row[1]) for row in assertions] != list(range(1, expected + 1))
            or any(row[0] != 'ok' or re.search(r'\s#\s*(SKIP|TODO)(?:\s|$)', row[2], re.I) for row in assertions)):
        detail.update(status='FAIL', reason='EXACT_TAP_ASSERTIONS_AND_PLAN_REQUIRED')
    return _case_identity_gate(detail, [row[2] for row in assertions], expected_ids)


def aggregate_api_junit(paths, destination):
    """Derived aggregate retains the original per-process XML files and SHAs."""
    root = ET.Element('testsuites'); sources = {}
    for namespace, path in paths.items():
        raw = regular(path); original = ET.fromstring(raw)
        suites = [original] if original.tag == 'testsuite' else original.findall('./testsuite')
        if original.tag not in {'testsuite', 'testsuites'} or not suites: raise ValueError('API_JUNIT_MISSING_SUITE')
        for suite in suites:
            copied = deepcopy(suite)
            for case in copied.findall('.//testcase'):
                case.set('classname', namespace + '.' + case.get('classname', ''))
            root.append(copied)
        sources[namespace] = {'path': str(path), 'sha256': digest(raw)}
    destination.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    return sources


def source_pins(source, mapping):
    selected = [row for row in mapping['files'] if row['group'] == 'api']; result = {}
    if not selected: raise ValueError('API_SOURCE_MAP_EMPTY')
    for row in selected:
        name = relative(row['relative_path']); expected = row['after_sha256']
        if name in result or digest(regular(source / name)) != expected:
            raise ValueError('API_AFTER_SOURCE_SHA_MISMATCH:' + name)
        result[name] = expected
    return result


def tree_pins(root):
    result = {}
    for path in sorted(root.rglob('*')):
        no_links(path)
        if any(part in IGNORED for part in path.relative_to(root).parts): continue
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'sha256': digest(regular(path)),
                                                        'mode': stat.S_IMODE(path.stat().st_mode)}
        elif not path.is_dir(): raise ValueError('SPECIAL_SOURCE_ENTRY:' + str(path))
    return result


def copy_release_fixture(package, destination):
    """Keep original release-test path assumptions without editing test bytes."""
    expected = {}
    for original, name in ((package / 'release_tools/after/ops', 'ops'), (package / 'tests/release', 'tests')):
        observed = tree_pins(original)
        if not observed: raise ValueError('RELEASE_FIXTURE_INPUT_EMPTY:' + str(original))
        expected.update({name + '/' + path: row for path, row in observed.items()})
        shutil.copytree(original, destination / name, ignore=shutil.ignore_patterns(*IGNORED))
    if tree_pins(destination) != expected: raise ValueError('RELEASE_FIXTURE_COPY_MISMATCH')
    return expected


def verify_package(package):
    spec = importlib.util.spec_from_file_location('_r4_runner_verify_package', package / 'tools/verify_package.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.verify(package)


def validate_fixture(folder, expected_source, before_app_sha):
    folder = exact_directory(folder); receipt = read_json(folder / 'FIXTURE_RECEIPT.json')
    if (receipt.get('status') != 'PASS' or receipt.get('fixture_only') is not True
            or receipt.get('http_service_started') is not False or receipt.get('real_market_acquisition') is not False
            or any(receipt.get(key) is not value for key, value in FLAGS.items())
            or receipt.get('natural_verified') is not False or receipt.get('execution_verified') is not False
            or receipt.get('after_source_sha256') != expected_source
            or receipt.get('before_api_app_sha256') != before_app_sha):
        raise ValueError('FRESH_FIXTURE_SOURCE_OR_SCOPE_MISMATCH')
    payloads = {}
    for label in ('consumer_response', 'workbench_response'):
        path = folder / (label + '.json')
        if receipt['files'][label] != {'path': str(path), 'sha256': digest(regular(path))}:
            raise ValueError('FRESH_FIXTURE_FILE_PIN_MISMATCH:' + label)
        payloads[label] = read_json(path)
    consumer, workbench = payloads['consumer_response'], payloads['workbench_response']
    for payload in (consumer, workbench):
        if (payload.get('trade_date') != '20261009' or payload.get('stage_id') != 'STAGE_0930_0935'
                or any(payload.get(key) is not value for key, value in FLAGS.items())
                or payload.get('natural_verified') is not False or payload.get('execution_verified') is not False):
            raise ValueError('FRESH_FIXTURE_SAFETY_OR_DATE_STAGE_MISMATCH')
        evidence = payload['execution_evidence']
        if (evidence.get('receipt_history_binding') != 'OWNER_HISTORY_SHA_BOUND'
                or evidence.get('natural_verified') is not False or evidence.get('execution_verified') is not False):
            raise ValueError('FRESH_FIXTURE_OWNER_HISTORY_UNBOUND')
    if workbench.get('recommendation_status') != 'WATCH_ONLY': raise ValueError('FRESH_FIXTURE_WATCH_ONLY_REQUIRED')
    identities = {}
    for market, ui_market, requested, observed in (('A_SHARE', 'A', 216, 206), ('HK_CONNECT', 'HK', 695, 695)):
        lane = consumer['markets'][market]
        comparison = [workbench['selection_markets'][market], workbench['markets'][ui_market],
                      workbench['execution_evidence']['selection_results'][market]]
        identity = {key: lane[key] for key in ('run_id', 'artifact_id', 'algorithm_sha256', 'raw_artifact_sha256')}
        if (any(not isinstance(value, str) or not value for value in identity.values())
                or any(not re.fullmatch('[a-f0-9]{64}', identity[key]) for key in ('algorithm_sha256', 'raw_artifact_sha256'))
                or any(any(other.get(key) != value for key, value in identity.items()) for other in comparison)
                or len(lane['rows']) != 10 or len(comparison[0]['rows']) != 10
                or comparison[2]['selected_rows'] != 10 or comparison[2]['status'] != 'RESULT_AVAILABLE'
                or sum(row['market'] == ui_market for row in workbench['unified_rows']) != 10
                or lane['requested_rows'] != requested or lane['source_rows'] != observed
                or receipt['markets'][market] != {'run_id': lane['run_id'], 'selected_rows': 10,
                                                   'requested_rows': requested, 'source_rows': observed}):
            raise ValueError('FRESH_FIXTURE_SAME_RUN_IDENTITY_OR_COUNT_MISMATCH:' + market)
        identities[market] = {**identity, 'selected_rows': 10, 'requested_rows': requested, 'source_rows': observed}
    return {'status': 'PASS', 'scope': receipt['scope'], 'fixture_receipt_sha256': digest(regular(folder / 'FIXTURE_RECEIPT.json')),
            'files': receipt['files'], 'markets': identities, 'after_source_sha256': expected_source, **FLAGS}


def runtime_identity(node, runtime, env):
    script = ("const fs=require('node:fs'),crypto=require('node:crypto');"
              "const r=require('node:module').createRequire(process.argv[1]+'/package.json');"
              "const deps=Object.fromEntries(['vue','@vue/compiler-sfc','@vue/server-renderer','@babel/parser'].map(name=>{"
              "const path=r.resolve(name+'/package.json'),raw=fs.readFileSync(path);"
              "return [name,{version:JSON.parse(raw).version,path,sha256:crypto.createHash('sha256').update(raw).digest('hex')}]}));"
              "console.log(JSON.stringify({node:process.version,executable:process.execPath,dependencies:deps}));")
    completed = subprocess.run([node, '-e', script, str(runtime)], env=env, cwd=runtime, capture_output=True, text=True)
    if completed.returncode: raise ValueError('EXPLICIT_INSTALLED_VUE_RUNTIME_REQUIRED:' + completed.stderr.strip())
    result = json.loads(completed.stdout)
    result.update(runtime_root=str(runtime), runtime_package_sha256=digest(regular(runtime / 'package.json')))
    lock = runtime / 'package-lock.json'
    result['runtime_lock_sha256'] = digest(regular(lock)) if lock.is_file() else None
    return result


def pytest_command(package, output, label, path):
    test_root = package if path.is_relative_to(package) else path.parent
    return [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-c', str(output / 'pytest.ini'),
            '--rootdir=' + str(test_root), str(path), '--basetemp=' + str(output / (label + '_tmp')),
            '--junitxml=' + str(output / (label + '.junit.xml'))]


def execute_checks(*, package, output, ui_runtime, api_source_root=None):
    report = {'schema_version': 'V4_STAGE_R4_CHECK_RESULTS_V1', 'status': 'FAIL_OR_NOT_RUN', 'scope': SCOPE,
              'results': {}, 'errors': [], 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'python_executable': sys.executable, 'platform': platform.platform(), **FLAGS}
    created = False
    try:
        package = exact_directory(package); runtime = exact_directory(ui_runtime)
        original_source = exact_directory(api_source_root or package / 'after/api')
        output = new_output(output, [package, runtime, original_source]); output.mkdir(mode=0o700); created = True
        report.update(package_root=str(package), output_root=str(output), api_source_input=str(original_source))
        validation = verify_package(package); report['package_before'] = validation
        if validation.get('status') != 'PASS': raise ValueError('PACKAGE_VERIFICATION_FAILED')
        expectations, expectations_sha = load_expectations(package)
        mapping = read_json(package / 'SOURCE_MAP.json'); map_sha = digest(regular(package / 'SOURCE_MAP.json'))
        pins = source_pins(original_source, mapping)
        report.update(test_expectations_sha256=expectations_sha, source_map_sha256=map_sha,
                      expected_tests=expectations['expected_tests'], expected_tests_total=sum(expectations['expected_tests'].values()),
                      api_after_source_sha256=pins)
        app = output / 'work/api_after'
        for name in pins:
            target = app / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(regular(original_source / name)); target.chmod(stat.S_IMODE((original_source / name).stat().st_mode))
        if source_pins(app, mapping) != pins: raise ValueError('ISOLATED_API_COPY_MISMATCH')
        r3 = output / 'work/r3'
        shutil.copytree(package / 'test_support/r3', r3, ignore=shutil.ignore_patterns(*IGNORED))
        for name, source_name in ((R3_READER, 'stage_center/execution_evidence.py'), (R3_CONSUMER, 'stage_center/consumer.py')):
            if digest(regular(r3 / name)) != pins[source_name]: raise ValueError('R3_REGRESSION_SOURCE_SHA_MISMATCH:' + name)
        report.update(isolated_api_after_root=str(app), isolated_r3_fixture_root=str(r3))
        release = output / 'work/release'
        release_pins = copy_release_fixture(package, release)
        report.update(isolated_release_fixture_root=str(release), release_fixture_source_sha256_and_modes=release_pins)
        clean = {key: value for key, value in os.environ.items() if key not in {'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'NODE_OPTIONS', 'NODE_PATH'}}
        env = {**clean, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
               'R3_PACKAGE': str(r3), 'R4_PACKAGE_ROOT': str(package), 'R4_TOOL_ROOT': str(package / 'tools'),
               'R4_RELEASE_TOOL_ROOT': str(package / 'release_tools/after/ops'),
               'R4_PUBLICATION_REFERENCE_ROOT': str(package / 'test_support/publication'),
               'R4_API_AFTER_ROOT': str(app), 'R4_API_BEFORE_ROOT': str(package / 'before/api'),
               'R4_API_TOOL_ROOT': str(package / 'tools'), 'R4_API_TEST_ROOT': str(package / 'tests/api'),
               'STAGE_API_PHASE': 'after', 'STAGE_MINIMAL_READER_FILE': str(app / 'stage_center/execution_evidence.py'),
               'STAGE_CONSUMER_FILE': str(app / 'stage_center/consumer.py'),
               'STAGE_UI_PHASE': 'after', 'STAGE_UI_RUNTIME': str(runtime),
               'STAGE_UI_SOURCE_ROOT': str(package / 'after/ui/apps/web/src'),
               'STAGE_UI_BEFORE_SOURCE_ROOT': str(package / 'before/ui/apps/web/src'),
               'PYTHONPATH': os.pathsep.join(map(str, [app, package / 'release_tools/after', package / 'tests/release', package / 'tools']))}
        node = shutil.which('node')
        if not node: raise ValueError('NODE_EXECUTABLE_REQUIRED')
        report['ui_runtime'] = runtime_identity(node, runtime, env)
        config = output / 'pytest.ini'; config.write_text('[pytest]\n')

        def run(label, command, junit=None, extra=None):
            try:
                completed = subprocess.run(command, cwd=package, env={**env, **(extra or {})}, text=True,
                                           capture_output=True, timeout=300, check=False)
                stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
            except (OSError, subprocess.TimeoutExpired) as error: stdout, stderr, code = '', str(error), None
            out, err = output / (label + '.stdout.log'), output / (label + '.stderr.log')
            out.write_text(stdout); err.write_text(stderr)
            detail = {'command': command, 'cwd': str(package), 'exit_code': code, 'stdout_path': str(out),
                      'stdout_sha256': digest(regular(out)), 'stderr_path': str(err), 'stderr_sha256': digest(regular(err))}
            if label in REQUIRED_SUITES:
                count, ids = expectations['expected_tests'][label], expectations['expected_case_ids'][label]
                detail['gate'] = junit_gate(junit, count, ids) if junit else tap_gate(stdout, count, ids)
            report['results'][label] = detail
            print(json.dumps({'check': label, 'exit_code': code, 'gate': detail.get('gate', {}).get('status')}), flush=True)
            return code == 0 and detail.get('gate', {}).get('status', 'PASS') == 'PASS'

        for label, path in (('api_r4', package / 'tests/api'), ('api_r3', r3 / 'checks/api/tests')):
            run(label, pytest_command(package, output, label, path))
        try:
            xml = output / 'api.junit.xml'
            parts = aggregate_api_junit({name: output / ('api_' + name + '.junit.xml') for name in ('r4', 'r3')}, xml)
            report['results']['api'] = {'exit_code': 0 if all(report['results'][name]['exit_code'] == 0 for name in ('api_r4', 'api_r3')) else 3,
                'scope': 'DERIVED_AGGREGATE_OF_TWO_RETAINED_PYTEST_REPORTS', 'source_reports': parts,
                'gate': junit_gate(xml, expectations['expected_tests']['api'], expectations['expected_case_ids']['api'])}
        except (OSError, ValueError, ET.ParseError) as error:
            report['results']['api'] = {'exit_code': 3, 'status': 'FAIL', 'error': str(error)}
        for label in ('release', 'integration', 'review_gates'):
            test_path = release / 'tests' if label == 'release' else package / 'tests' / label
            extra = {'PYTHONPATH': os.pathsep.join([str(release), str(release / 'tests'), env['PYTHONPATH']])} if label == 'release' else None
            run(label, pytest_command(package, output, label, test_path), output / (label + '.junit.xml'), extra=extra)
        fixture = output / 'full_chain_fixture'
        exported = run('fixture_exporter', [sys.executable, '-B', str(package / 'tools/export_research_binding_fixture.py'), '--output', str(fixture)])
        fixture_ok = False
        if exported:
            try:
                report['results']['fixture_identity'] = validate_fixture(fixture, pins, digest(regular(package / 'before/api/apps/api/v35_api/app.py')))
                fixture_ok = True
            except (OSError, ValueError, TypeError, KeyError) as error:
                report['results']['fixture_identity'] = {'status': 'FAIL', 'error': str(error)}
        else: report['results']['fixture_identity'] = {'status': 'NOT_RUN', 'reason': 'FIXTURE_EXPORT_FAILED'}
        if fixture_ok:
            files = sorted(name for name in expectations['suite_files']['ui'] if name.endswith('.test.mjs'))
            if not files: raise ValueError('FROZEN_UI_TEST_FILES_MISSING')
            run('ui', [node, '--test', '--test-reporter=tap', *[str(package / name) for name in files]],
                extra={'STAGE_UI_CONSUMER_FIXTURE': str(fixture / 'consumer_response.json'), 'STAGE_UI_GENERATED_DIR': str(output / 'vue_compiled')})
        else: report['results']['ui'] = {'status': 'NOT_RUN', 'reason': 'FRESH_EXACT_API_FIXTURE_UNAVAILABLE', 'exit_code': None}
        final, final_sha = load_expectations(package)
        if (final != expectations or final_sha != expectations_sha or digest(regular(package / 'SOURCE_MAP.json')) != map_sha
                or source_pins(original_source, mapping) != pins or source_pins(app, mapping) != pins
                or tree_pins(release) != release_pins):
            raise ValueError('FROZEN_INPUT_CHANGED_DURING_CHECKS')
        report['package_after'] = verify_package(package)
        required = set(REQUIRED_SUITES) | {'api_r4', 'api_r3', 'fixture_exporter', 'fixture_identity'}
        passed = (set(report['results']) == required and report['package_after'].get('status') == 'PASS'
                  and all(report['results'][name].get('exit_code') == 0 and report['results'][name].get('gate', {}).get('status') == 'PASS' for name in REQUIRED_SUITES)
                  and all(report['results'][name].get('exit_code') == 0 for name in ('api_r4', 'api_r3', 'fixture_exporter'))
                  and report['results']['fixture_identity'].get('status') == 'PASS')
        report['status'] = 'PASS' if passed else 'FAIL_OR_NOT_RUN'
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError) as error:
        report['errors'].append(str(error)); report['status'] = 'FAIL_OR_NOT_RUN'
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        if created: (output / 'RESULTS.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True, help='new absolute output outside inputs')
    parser.add_argument('--ui-runtime', type=Path, required=True, help='existing installed Vue runtime; never installed here')
    parser.add_argument('--api-source-root', type=Path, help='optional read-only source; every R4 API after SHA must match')
    args = parser.parse_args()
    report = execute_checks(package=args.package, output=args.output, ui_runtime=args.ui_runtime, api_source_root=args.api_source_root)
    print(json.dumps({'status': report['status'], 'scope': report['scope'], 'expected_tests': report.get('expected_tests'),
                      'errors': report['errors'], 'results_path': str(args.output / 'RESULTS.json') if 'output_root' in report else None, **FLAGS}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
