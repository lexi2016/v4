#!/usr/bin/env python3
"""Run the offline backend regressions against an isolated before/after assembly.

This runner never changes a supplied source image or the production candidate.
It needs only Python's standard library. Source-owner returns and calendar
windows are synthetic test fixtures; this does not run a scheduler or live API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def support_files(root: Path) -> list[Path]:
    """Verify that the unchanged import support is exactly its recorded bytes."""
    provenance = json.loads((root / 'SOURCE_PROVENANCE.json').read_text())
    expected = {row['path']: row['sha256'] for row in provenance['files']}
    actual = {path.relative_to(root).as_posix(): path for path in root.rglob('*.py')}
    if actual.keys() != expected.keys():
        raise ValueError('Test support Python file set differs from SOURCE_PROVENANCE.json')
    for relative, path in actual.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[relative]:
            raise ValueError(f'Unchanged test support SHA256 mismatch: {relative}')
    return [actual[relative] for relative in sorted(actual)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-image', required=True, choices=('before', 'after'),
        help='before is expected to fail the new regressions; after must pass')
    args = parser.parse_args()
    delivery = Path(__file__).resolve().parents[1]
    image = delivery / args.source_image
    support = delivery / 'test_support/python'
    tests = delivery / 'tests/backend'
    required = ('workspace.py', 'workspace_projection.py', 'research_attention.py')
    for name in required:
        if not (image / 'v4/manager_research' / name).is_file():
            parser.error(f'Missing source image module: {args.source_image}/v4/manager_research/{name}')
    helper = image / 'v4/manager_research/workspace_identity.py'
    if helper.is_file() != (args.source_image == 'after'):
        parser.error('workspace_identity.py must occur only in the after image')
    if len(list(tests.glob('test_*.py'))) != 5:
        parser.error('Expected the five packaged backend regression files')
    try:
        unchanged = support_files(support)
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))

    print(f'Backend source image: {args.source_image}', flush=True)
    print('Scope: isolated real-module regressions with synthetic owner boundaries; live API/UI NOT_RUN.', flush=True)
    print('Expected result: ' + ('regression assertions fail (nonzero exit)' if args.source_image == 'before'
        else '21 tests pass (exit 0)'), flush=True)
    with tempfile.TemporaryDirectory(prefix='v4-semantic-regression-') as temporary:
        assembly = Path(temporary) / 'source'
        for source_root, paths in ((support, unchanged), (image, sorted(image.rglob('*.py')))):
            for source in paths:
                destination = assembly / source.relative_to(source_root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        env = dict(os.environ, WORKSPACE_SOURCE_ROOT=str(assembly),
            WORKSPACE_DEPENDENCY_ROOT=str(assembly), PYTHONDONTWRITEBYTECODE='1')
        # -I isolates Python from caller PYTHONPATH/user-site imports. The tests
        # explicitly import only the temporary source assembly via these envs.
        command = [sys.executable, '-I', '-B', '-m', 'unittest', 'discover',
            '-s', str(tests), '-p', 'test_*.py', '-v']
        result = subprocess.run(command, cwd=temporary, env=env, check=False)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
