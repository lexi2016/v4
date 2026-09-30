#!/usr/bin/env python3
"""Run only R3-B tests against an explicit isolated app; never install/deploy."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys

EXPECTED = {
    'v4.manager_research.workspace': '8a1ce5122be59f2d56e258522909ca0ff76345a32aed3b4a2517e9cfb2e7c190',
    'v4.manager_research.connect_selection': 'b6c5300172f59b6979dbab15927036ff1ab3599a2adae2b4f0e5a1e4868a6248',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    app = args.app_root.resolve(strict=True)
    output = args.output_dir.absolute()
    if output.exists() or output.is_symlink() or output == app or app in output.parents:
        parser.error('output must be a NEW directory outside app')
    for name, expected in EXPECTED.items():
        source = app / (name.replace('.', '/') + '.py')
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            parser.error('EXACT_CANDIDATE_MISMATCH:' + name)
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(app))
    sys.dont_write_bytecode = True
    import os
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.environ.pop('PYTEST_ADDOPTS', None)
    os.environ.pop('PYTEST_PLUGINS', None)
    identities = {}
    for name, expected in EXPECTED.items():
        module = importlib.import_module(name)
        file = Path(module.__file__).resolve()
        if file != app / (name.replace('.', '/') + '.py'):
            raise RuntimeError('IMPORTED_WRONG_APP:' + name)
        identities[name] = {'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
    import pytest
    test = Path(__file__).resolve().parents[1] / 'tests/test_r3b_saved_diagnostics.py'
    command = [str(test), '-q', '--tb=short', '-c', str(test.parents[1] / 'pytest.ini'),
               '-p', 'no:cacheprovider', '--basetemp=' + str(output / 'tmp'),
               '--junitxml=' + str(output / 'junit.xml')]
    start = datetime.now(timezone.utc).isoformat()
    with (output / 'pytest.log').open('x', encoding='utf-8') as log:
        with redirect_stdout(log), redirect_stderr(log):
            code = int(pytest.main(command))
    imported = {}
    for name, module in sorted(sys.modules.items()):
        p = getattr(module, '__file__', None)
        if p:
            p = Path(p).resolve()
            if p.is_relative_to(app) and p.is_file():
                imported[str(p.relative_to(app))] = hashlib.sha256(p.read_bytes()).hexdigest()
    receipt = dict(scope='R3B_ONLY_SYNTHETIC_UPSTREAM_REAL_FILESYSTEM',
        started_at=start, finished_at=datetime.now(timezone.utc).isoformat(),
        app_root=str(app), python=sys.version, platform=platform.platform(),
        command=command, exit_code=code, focal_imports=identities, imported_app_files=imported,
        independent_review_claimed=False, deployment=False, live_api_verified=False)
    (output / 'run_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print((output / 'pytest.log').read_text(encoding='utf-8'), end='')
    print('R3B_RECEIPT=' + str(output / 'run_receipt.json'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
