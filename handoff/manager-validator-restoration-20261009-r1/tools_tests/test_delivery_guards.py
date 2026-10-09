"""Exercise handoff guards without running git or touching a live source root."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]


def test_rejects_production_path_before_writing_outside_owned_temporary_directory(tmp_path):
    package = tmp_path / 'package'
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    manifest_path = package / 'MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['production_change']['path'] = '../escape/managerWorkspace.ts'
    manifest_path.write_text(json.dumps(manifest))
    injected = package / 'escape/managerWorkspace.ts'
    injected.parent.mkdir()
    injected.write_text('synthetic tampered metadata fixture\n')
    temporary = tmp_path / 'temporary'
    temporary.mkdir()
    result = subprocess.run([sys.executable, str(package / 'tools/verify_delivery.py')],
                            env={**os.environ, 'TMPDIR': str(temporary)},
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert 'PRODUCTION_PATH_INVALID' in result.stderr
    assert not (temporary / 'escape').exists()


@pytest.mark.parametrize('rollback', [False, True], ids=['apply', 'rollback'])
def test_pasted_commands_stop_before_git_when_target_identity_check_fails(tmp_path, rollback):
    blocks = re.findall(r'```sh\n(.*?)\n```', (PACKAGE / 'MAC_APPLY_AND_ROLLBACK.md').read_text(), re.S)
    block = next(b for b in blocks if 'verify_delivery.py' in b and ('--reverse' in b) == rollback)
    commands = block[block.index('python3 '):]
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    calls = tmp_path / 'calls.log'
    for name, body in {
        'python3': '#!/bin/sh\nprintf "identity-check\\n" >> "$CALL_LOG"\nexit 41\n',
        'git': '#!/bin/sh\nprintf "git-called\\n" >> "$CALL_LOG"\nexit 0\n',
    }.items():
        executable = binaries / name
        executable.write_text(body)
        executable.chmod(0o755)
    result = subprocess.run(['/bin/bash', '-c', commands], cwd=tmp_path,
                            env={**os.environ, 'PATH': str(binaries), 'CALL_LOG': str(calls),
                                 'REPAIR_PACKAGE': str(tmp_path / 'fixture-package'),
                                 'REPAIR_APP': str(tmp_path / 'fixture-app')},
                            text=True, capture_output=True)
    assert result.returncode == 41
    assert calls.read_text().splitlines() == ['identity-check']
