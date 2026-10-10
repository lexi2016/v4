#!/usr/bin/env python3
"""Assemble a temporary snapshot and run delivered tests without live services."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--side', choices=('before', 'after'), default='after')
    parser.add_argument('--suite', choices=('backend', 'frontend', 'both'), default='both')
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_dir = args.report_dir.resolve()
    if report_dir.is_relative_to(root):
        parser.error('--report-dir must be outside the package to preserve its manifest')
    report_dir.mkdir(parents=True, exist_ok=True)
    support = root / 'test_support' / 'upstream'
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    runs = []
    with tempfile.TemporaryDirectory(prefix='v4-manager-offline-') as temporary:
        app = Path(temporary) / 'app'
        shutil.copytree(root / 'test_support' / 'current', app)
        shutil.copytree(root / args.side, app, dirs_exist_ok=True)
        commands = []
        if args.suite in ('backend', 'both'):
            commands.append(('backend', [sys.executable, str(root / 'tools/run_backend_harness.py'),
                '--source-root', str(app), '--support-root', str(support),
                '--tests-root', str(root / 'tests'),
                '--report', str(report_dir / ('backend.' + args.side + '.json'))]))
        if args.suite in ('frontend', 'both'):
            commands.append(('frontend', [args.node, str(root / 'tools/run_ui_harness.mjs'),
                '--source-root', str(app), '--support-root', str(support),
                '--tests', str(root / 'tests/catalystObservationPanel.repair.spec.ts'),
                '--report', str(report_dir / ('frontend.' + args.side + '.json'))]))
        for label, command in commands:
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
            (report_dir / (label + '.' + args.side + '.runner.log')).write_text(result.stdout + result.stderr)
            runs.append(dict(suite=label, exit_code=result.returncode, command=command))
            print(result.stdout, end='')
            if result.stderr:
                print(result.stderr, end='', file=sys.stderr)
    summary = dict(status='PASS' if all(row['exit_code'] == 0 for row in runs) else 'FAIL',
                   mode='OFFLINE_SNAPSHOT', live_api_ui='LIVE_API_UI_NOT_RUN', side=args.side, runs=runs)
    (report_dir / ('summary.' + args.side + '.json')).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
