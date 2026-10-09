#!/usr/bin/env python3
"""Reproduce this candidate's checks in new output directories, without live I/O."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from verify_package import verify


REQUIRED_SUITES = ('stage', 'api', 'adaptation', 'vue', 'vue_actual')


def load_expectations(package):
    """Frozen reviewed counts, never learned from the current test run."""
    path = package / 'TEST_EXPECTATIONS.json'
    value = json.loads(path.read_text())
    counts = value['expected_tests']
    if (value.get('schema_version') != 'V4_TEST_EXPECTATIONS_V1'
            or set(counts) != set(REQUIRED_SUITES)
            or any(type(n) is not int or n < 1 for n in counts.values())
            or value.get('maximum_skipped') != 0):
        raise ValueError('exact nonzero counts for every required suite and maximum_skipped=0 required')
    return counts, hashlib.sha256(path.read_bytes()).hexdigest()


def junit_gate(path, expected):
    """Count actual testcase outcomes as well as JUnit's declared totals."""
    detail = {'status': 'FAIL', 'expected_tests': expected, 'observed_tests': None,
              'passed': None, 'skipped': None, 'failures': None, 'errors': None}
    try:
        root = ET.fromstring(path.read_bytes())
        cases = root.findall('.//testcase')
        suites = [root] if root.tag == 'testsuite' else root.findall('./testsuite')
        if root.tag not in ('testsuite', 'testsuites') or not suites:
            raise ValueError('missing JUnit testsuite')
        observed = {'tests': len(cases), 'skipped': sum(c.find('skipped') is not None for c in cases),
                    'failures': sum(c.find('failure') is not None for c in cases),
                    'errors': sum(c.find('error') is not None for c in cases)}
        declared = {name: sum(int(s.attrib[name]) for s in suites) for name in observed}
        if declared != observed or any(value < 0 for value in declared.values()):
            raise ValueError('JUnit declared totals do not match testcase outcomes')
        passed = sum(not any(c.find(name) is not None for name in ('skipped', 'failure', 'error')) for c in cases)
        detail.update(observed_tests=observed['tests'], passed=passed, skipped=observed['skipped'],
                      failures=observed['failures'], errors=observed['errors'], declared=declared,
                      junit_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if observed['tests'] == expected and passed == expected and not any(observed[k] for k in ('skipped', 'failures', 'errors')):
            detail['status'] = 'PASS'
        else:
            detail['reason'] = 'EXACT_COUNT_AND_ZERO_SKIPS_FAILURES_ERRORS_REQUIRED'
    except (OSError, ET.ParseError, ValueError, KeyError) as error:
        detail['reason'] = 'JUNIT_MISSING_OR_INVALID'
        detail['detail'] = str(error)
    return detail


def tap_gate(stdout, expected):
    detail = {'status': 'FAIL', 'expected_tests': expected, 'observed_tests': None,
              'passed': None, 'skipped': None, 'failures': None, 'cancelled': None, 'todo': None}
    values = {}
    for name in ('tests', 'pass', 'fail', 'skipped', 'cancelled', 'todo'):
        matches = re.findall(r'^# ' + name + r' (\d+)\s*$', stdout, re.M)
        if len(matches) != 1:
            detail['reason'] = 'TAP_SUMMARY_MISSING_OR_AMBIGUOUS'
            return detail
        values[name] = int(matches[0])
    detail.update(observed_tests=values['tests'], passed=values['pass'], failures=values['fail'],
                  skipped=values['skipped'], cancelled=values['cancelled'], todo=values['todo'])
    if values['tests'] == expected and values['pass'] == expected and not any(values[k] for k in ('fail', 'skipped', 'cancelled', 'todo')):
        detail['status'] = 'PASS'
    else:
        detail['reason'] = 'EXACT_COUNT_AND_ZERO_SKIPS_FAILURES_CANCELLED_TODO_REQUIRED'
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stage-app', type=Path, help='Use an already prepared complete canary application')
    parser.add_argument('--ui-runtime', type=Path, help='Directory containing package.json and installed Vue/compiler/server-renderer')
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    validation = verify(package)
    if validation['status'] != 'PASS':
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 3
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        expectations, expectations_sha = load_expectations(package)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'status': 'FAIL_OR_NOT_RUN', 'error': 'TEST_EXPECTATIONS_INVALID', 'detail': str(error)}
        (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
        return 3
    mapping = json.loads((package / 'SOURCE_MAP.json').read_text())
    if args.stage_app:
        app = args.stage_app.resolve()
    else:
        app = output / 'work/stage_app'
        shutil.copytree(package / 'test_support/stage_base_app', app,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
        for item in mapping['files']:
            if item['group'] == 'stage':
                shutil.copy2(package / item['after_path'], app / item['relative_path'])
    mismatches = []
    for item in mapping['files']:
        if item['group'] == 'stage':
            path = app / item['relative_path']
            observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if observed != item['after_sha256']:
                mismatches.append({'path': str(path), 'expected': item['after_sha256'], 'observed': observed})
    if mismatches:
        (output / 'RESULTS.json').write_text(json.dumps({'status': 'SOURCE_MISMATCH', 'files': mismatches}, indent=2) + '\n')
        print('Candidate after SHA mismatch; no tests or collectors were started.')
        return 3
    started = datetime.now(timezone.utc).isoformat()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'STAGE_CHECK_APP': str(app),
           'A_QUOTE_APP': str(app), 'PYTHONPATH': str(app), 'STAGE_API_PHASE': 'after', 'STAGE_UI_PHASE': 'after'}
    env.update(CANARY_TEST_PACKAGE=str(package), CANARY_TEST_STAGE_APP=str(app),
               CANARY_TEST_DRIVER=str(package / 'tools/run_current_research_canary.py'))
    api = package / 'checks/api'
    results = {}

    def run(label, command, cwd, extra=None, junit=None):
        current_env = {**env, **(extra or {})}
        completed = subprocess.run(command, cwd=cwd, env=current_env, text=True, capture_output=True)
        (output / (label + '.stdout.log')).write_text(completed.stdout)
        (output / (label + '.stderr.log')).write_text(completed.stderr)
        detail = {'command': command, 'cwd': str(cwd), 'exit_code': completed.returncode}
        if label in expectations:
            gate = junit_gate(junit, expectations[label]) if junit else tap_gate(completed.stdout, expectations[label])
            detail.update(gate=gate, passed=gate['passed'], skipped=gate['skipped'])
        results[label] = detail
        print(json.dumps({'check': label, **detail}), flush=True)
        return completed.returncode == 0 and detail.get('gate', {}).get('status', 'PASS') == 'PASS'

    run('stage', [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(package / 'tests'),
                  '--junitxml=' + str(output / 'stage.junit.xml')], package, junit=output / 'stage.junit.xml')
    run('api', [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests',
                '--junitxml=' + str(output / 'api.junit.xml')], api, junit=output / 'api.junit.xml')
    run('adaptation', [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                      str(package / 'checks/adaptation'), '--junitxml=' + str(output / 'adaptation.junit.xml')],
        package, junit=output / 'adaptation.junit.xml')
    fixture = output / 'full_chain_fixture'
    exported = run('fixture_runner', [sys.executable, '-B', str(package / 'tools/export_integration_fixture.py'),
                                     '--output', str(fixture)], package)
    readback = exported and run('fixture_api', [sys.executable, '-B', str(api / 'tests/read_integrated_fixture.py'), str(fixture)], api)
    runtime = args.ui_runtime or (Path(os.environ['STAGE_UI_RUNTIME']) if os.environ.get('STAGE_UI_RUNTIME') else None)
    node = shutil.which('node')
    if runtime and node and readback:
        ui_env = {'STAGE_UI_RUNTIME': str(runtime.resolve()),
                  'STAGE_UI_CONSUMER_FIXTURE': str(fixture / 'consumer_response.json'),
                  'STAGE_UI_GENERATED_DIR': str(output / 'vue_compiled')}
        run('vue', [node, '--test', '--test-reporter=tap', 'tests/legacy_presentation.test.mjs',
                    'tests/research_presentation.test.mjs'], api, ui_env)
        run('vue_actual', [node, '--test', '--test-reporter=tap', 'tests/current_app_presentation.test.mjs'], api, ui_env)
        run('fixture_vue', [node, str(api / 'tests/verify_integrated_fixture.mjs'), str(fixture)], api, ui_env)
    else:
        for label in ('vue', 'vue_actual', 'fixture_vue'):
            results[label] = {'status': 'NOT_RUN', 'reason': 'EXPLICIT_UI_RUNTIME_OR_NODE_OR_CONSUMER_FIXTURE_UNAVAILABLE', 'exit_code': 3}
    required = set(REQUIRED_SUITES) | {'fixture_runner', 'fixture_api', 'fixture_vue'}
    passed = (set(results) == required and all(item.get('exit_code') == 0 for item in results.values())
              and all(results[label].get('gate', {}).get('status') == 'PASS' for label in REQUIRED_SUITES))
    report = {'status': 'PASS' if passed else 'FAIL_OR_NOT_RUN',
              'scope': 'ISOLATED_SOURCE_FIXTURE_TESTS_NOT_MAC_MARKET_API_DEPLOYMENT_OR_NATURAL_ACCEPTANCE',
              'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'platform': platform.platform(), 'stage_app': str(app),
              'package': validation, 'test_expectations_sha256': expectations_sha,
              'expected_tests': expectations, 'results': results,
              'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    (output / 'RESULTS.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 3


if __name__ == '__main__':
    raise SystemExit(main())
