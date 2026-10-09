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

from verify_package import verify


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

    def run(label, command, cwd, extra=None):
        current_env = {**env, **(extra or {})}
        completed = subprocess.run(command, cwd=cwd, env=current_env, text=True, capture_output=True)
        (output / (label + '.stdout.log')).write_text(completed.stdout)
        (output / (label + '.stderr.log')).write_text(completed.stderr)
        detail = {'command': command, 'cwd': str(cwd), 'exit_code': completed.returncode}
        passed = re.search(r'(\d+) passed', completed.stdout)
        if passed:
            detail['passed'] = int(passed.group(1))
        for key in ('tests', 'pass', 'fail', 'skipped'):
            match = re.search(r'^# ' + key + r' (\d+)\s*$', completed.stdout, re.M)
            if match:
                detail[key] = int(match.group(1))
        results[label] = detail
        print(json.dumps({'check': label, **detail}), flush=True)
        return completed.returncode == 0

    run('stage', [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(package / 'tests'),
                  '--junitxml=' + str(output / 'stage.junit.xml')], package)
    run('api', [sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests',
                '--junitxml=' + str(output / 'api.junit.xml')], api)
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
        run('fixture_vue', [node, str(api / 'tests/verify_integrated_fixture.mjs'), str(fixture)], api, ui_env)
    else:
        results['vue'] = {'status': 'NOT_RUN', 'reason': 'EXPLICIT_UI_RUNTIME_OR_NODE_OR_CONSUMER_FIXTURE_UNAVAILABLE', 'exit_code': 3}
    passed = all(item.get('exit_code') == 0 for item in results.values()) and results.get('vue', {}).get('skipped') == 0
    report = {'status': 'PASS' if passed else 'FAIL_OR_NOT_RUN',
              'scope': 'ISOLATED_SOURCE_FIXTURE_TESTS_NOT_MAC_MARKET_API_DEPLOYMENT_OR_NATURAL_ACCEPTANCE',
              'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'platform': platform.platform(), 'stage_app': str(app),
              'package': validation, 'results': results,
              'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    (output / 'RESULTS.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 3


if __name__ == '__main__':
    raise SystemExit(main())
