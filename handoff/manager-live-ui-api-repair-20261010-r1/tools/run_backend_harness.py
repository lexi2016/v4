#!/usr/bin/env python3
"""Run the delivered offline unittest suite and record source identities."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--support-root', type=Path, required=True)
    parser.add_argument('--tests-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--pattern', default='test_backend*.py')
    args = parser.parse_args()
    source, support, tests = [p.resolve(strict=True) for p in
                              (args.source_root, args.support_root, args.tests_root)]
    report = args.report.resolve()
    loaded: set[Path] = set()

    def audit(event, values):
        if event == 'exec' and values:
            filename = getattr(values[0], 'co_filename', '')
            if filename and not filename.startswith('<'):
                path = Path(filename).resolve()
                if any(path.is_relative_to(root) for root in (source, support, tests)):
                    loaded.add(path)

    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    sys.path[:0] = [str(source), str(support), str(tests)]
    started = datetime.now(timezone.utc).isoformat()
    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(tests), pattern=args.pattern)
    if suite.countTestCases() == 0:
        raise RuntimeError('No backend regression tests discovered')
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    failures = [{'test': case.id(), 'traceback': trace} for case, trace in result.failures]
    errors = [{'test': case.id(), 'traceback': trace} for case, trace in result.errors]
    modules = []
    for path in sorted(loaded):
        if not path.is_file():
            continue
        origin = next((label for root, label in ((source, 'SOURCE_UNDER_TEST'),
                      (support, 'RECOVERED_TEST_SUPPORT'), (tests, 'TEST'))
                      if path.is_relative_to(root)), 'UNKNOWN')
        data = path.read_bytes()
        modules.append(dict(path=str(path), origin=origin, bytes=len(data),
                            sha256=hashlib.sha256(data).hexdigest()))
    value = dict(schema_version='offline-manager-backend-tests.v1',
                 mode='OFFLINE_SYNTHETIC_SOURCE_AND_PLAN_TESTS',
                 live_api_ui='LIVE_API_UI_NOT_RUN',
                 command=[sys.executable, *sys.argv], python_version=platform.python_version(),
                 platform=platform.platform(), source_root=str(source), support_root=str(support),
                 tests_root=str(tests), started_at=started,
                 finished_at=datetime.now(timezone.utc).isoformat(),
                 status='PASS' if result.wasSuccessful() else 'FAIL',
                 tests_run=result.testsRun, failure_count=len(failures), error_count=len(errors),
                 skipped=[dict(test=case.id(), reason=reason) for case, reason in result.skipped],
                 failures=failures, errors=errors, source_modules=modules)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    report.with_suffix('.log').write_text(output.getvalue())
    print(json.dumps({key: value[key] for key in
                     ('status', 'tests_run', 'failure_count', 'error_count', 'live_api_ui')}))
    print(f'Report: {report}')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
