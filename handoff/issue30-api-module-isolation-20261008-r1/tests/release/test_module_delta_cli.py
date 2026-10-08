"""Create an explicit delta from reviewed file pins, never an old whole tree."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from ops import api_release_integration as integration
from test_api_release_integration import _write_active_release


def _setup(tmp_path):
    active = _write_active_release(tmp_path, tmp_path/'LaunchAgents/com.lexi.v35.api-only.plist')
    after_root = tmp_path/'reviewed-after'
    rel = 'apps/api/v35_api/app.py'
    target = after_root/rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b'VALUE = 2\n')
    target.chmod(0o644)
    change_set = {'schema_version':'v4.api_module_change_set.v1', 'module':'preselection',
        'shared_paths':[rel], 'files':[{'path':rel,
            'before_sha256':hashlib.sha256(b'VALUE = 1\n').hexdigest(),
            'after_sha256':hashlib.sha256(b'VALUE = 2\n').hexdigest(),
            'before_mode':'0644', 'after_mode':'0644'}]}
    pins = tmp_path/'reviewed-change-set.json'
    pins.write_text(json.dumps(change_set)+'\n')
    return active,after_root,pins,change_set


def _run(active, after_root, pins, output):
    tool = Path(__file__).resolve().parents[1]/'ops/create_api_module_delta.py'
    return subprocess.run([sys.executable,'-B',str(tool),
        '--active-api-plist',str(active['api_plist']), '--after-root',str(after_root),
        '--change-set',str(pins),'--output',str(output)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_delta_cli_creates_v2_candidate_receipt_without_changing_inputs(tmp_path):
    active,after_root,pins,_ = _setup(tmp_path)
    pointer_before = Path(active['api_plist']).read_bytes()
    output = tmp_path/'reviewed-delta.json'
    result = _run(active,after_root,pins,output)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text())
    assert receipt['schema_version'] == 'v4.api_release_delta_receipt.v2'
    assert receipt['module_scope']['module'] == 'preselection'
    assert receipt['base']['api_plist_sha256'] == hashlib.sha256(pointer_before).hexdigest()
    assert receipt['entries'][0]['path'] == 'apps/api/v35_api/app.py'
    candidate = tmp_path/'candidate'; candidate.mkdir()
    report = integration.build_integrated_app(active_api_plist_path=Path(active['api_plist']),
        source_root=after_root,candidate_root=candidate,delta_receipt_path=output)
    assert (candidate/'app/stable-module.py').read_bytes() == b'STABLE = True\n'
    assert report['source_workspace_full_tree_copied'] is False
    assert Path(active['api_plist']).read_bytes() == pointer_before


@pytest.mark.parametrize('damage',['before','after','mode','module','extra_field','duplicate_key','source_alias'])
def test_delta_cli_rejects_unreviewed_or_invalid_change_set(tmp_path,damage):
    active,after_root,pins,change_set = _setup(tmp_path)
    if damage == 'before': change_set['files'][0]['before_sha256'] = 'f'*64
    if damage == 'after': (after_root/'apps/api/v35_api/app.py').write_bytes(b'UNREVIEWED = True\n')
    if damage == 'mode': (after_root/'apps/api/v35_api/app.py').chmod(0o755)
    if damage == 'module': change_set['module'] = 'unknown_module'
    if damage == 'extra_field': change_set['ignore_before'] = True
    if damage == 'source_alias':
        alias = tmp_path/'after-alias';alias.symlink_to(after_root,target_is_directory=True);after_root = alias
    pins.write_text(json.dumps(change_set)+'\n')
    if damage == 'duplicate_key':
        pins.write_text(pins.read_text().replace('"module": "preselection"','"module": "manager", "module": "preselection"'))
    output = tmp_path/'rejected-delta.json'
    result = _run(active,after_root,pins,output)
    assert result.returncode != 0
    assert 'API_MODULE_DELTA_' in result.stderr or 'API_RELEASE_' in result.stderr, result.stderr
    assert not output.exists()


def test_delta_cli_never_overwrites_an_existing_receipt(tmp_path):
    active,after_root,pins,_ = _setup(tmp_path)
    output = tmp_path/'existing.json'; output.write_bytes(b'existing proof\n')
    result = _run(active,after_root,pins,output)
    assert result.returncode != 0
    assert output.read_bytes() == b'existing proof\n'
