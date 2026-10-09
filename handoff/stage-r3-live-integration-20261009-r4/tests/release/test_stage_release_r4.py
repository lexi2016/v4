"""Stage R4: exact active-base integration and complete generated static tree."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from ops import api_release_integration as guard
from ops import create_api_module_delta as delta
from ops import build_release_candidate as builder
from test_api_release_integration import _write_active_release
from test_build_release_candidate import _scheduler_plist


DIST = 'apps/web/dist/'
CODE = [
    'apps/api/v35_api/app.py',
    'apps/web/src/App.vue',
    'apps/web/src/components/review/StageExecutionEvidencePanel.vue',
    'apps/web/src/contracts/runtime.ts',
    'stage_center/consumer.py',
    'stage_center/execution_evidence.py',
    'stage_center/research_read_binding.py',
    'stage_center/approved_research_read.json',
    'stage_center/approved_research_read.sha256',
]
SHARED = sorted(['apps/api/v35_api/app.py', 'apps/web/src/App.vue',
                 'apps/web/src/contracts/runtime.ts'])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def dump(path, value):
    write(path, (json.dumps(value, sort_keys=True, indent=2)+'\n').encode())


def static_record(rows):
    entries = sorted([row for row in rows if row['path'].startswith(DIST)],
                     key=lambda row: row['path'])
    return {'entry_count': len(entries), 'aggregate_sha256': guard.inventory_digest(entries),
            'entries': entries}


def case(tmp_path):
    files = {path: b'OLD = True\n' for path in CODE[:6]}
    files.update({
        'v4/manager_research/keep.py': b'ISSUE32_MANAGER = True\n',
        'domains/preselection.py': b'ISSUE32_PRESELECTION = True\n',
        'ops/launch_v35_macos_scheduler.sh': b'#!/bin/bash\nexit 0\n',
        DIST+'index.html': b'<script src="/assets/main-old.js"></script>\n',
        DIST+'assets/main-old.js': b'import "./manager-old.js";\n',
        DIST+'assets/manager-old.js': b'export const manager = 32;\n',
        DIST+'assets/stable.css': b'body { color: black; }\n',
    })
    active = _write_active_release(tmp_path, tmp_path/'LaunchAgents/com.lexi.v35.api-only.plist',
                                   files=files)
    after = tmp_path/'reviewed-after'
    built = tmp_path/'built-dist'
    for path in CODE:
        write(after/path, b'NEW = True\n' if not path.endswith('.json') else b'{"approved":true}\n')
    for rel, raw in {
        'index.html': b'<script src="/assets/main-new.js"></script>\n',
        'assets/main-new.js': b'import "./manager-new.js";\n',
        'assets/manager-new.js': b'export const manager = 32; export const stage = 4;\n',
        'assets/stable.css': files[DIST+'assets/stable.css'],
    }.items():
        write(built/rel, raw)
        write(after/DIST/rel, raw)
    base_rows = guard.inventory_tree(Path(active['app_root']))
    source_rows = guard.inventory_tree(after)
    before = {row['path']: row for row in base_rows}
    final = {row['path']: row for row in source_rows}
    rows = []
    for path in sorted(set(CODE) | set(before) | set(final)):
        if path not in CODE and not path.startswith(DIST):
            continue
        old, new = before.get(path), final.get(path)
        if old == new:
            continue
        rows.append({'path':path,
            'before_sha256':old['sha256'] if old else None,
            'after_sha256':new['sha256'] if new else None,
            'before_mode':old['mode'] if old else None,
            'after_mode':new['mode'] if new else None})
    proof = {'schema_version':'v4.api_release_static_tree.v1', 'root':'apps/web/dist',
             'before':static_record(base_rows), 'after':static_record(source_rows)}
    changes = {'schema_version':delta.CHANGE_SET_SCHEMA, 'module':'stage',
               'shared_paths':SHARED, 'files':rows, 'static_tree':proof}
    pins = tmp_path/'changes.json'
    dump(pins, changes)
    return active, after, built, pins, changes


def make_delta(tmp_path, *, mutate=None):
    active, after, built, pins, changes = case(tmp_path)
    if mutate:
        mutate(active, after, built, changes)
        dump(pins, changes)
    output = tmp_path/'delta.json'
    delta.create_module_delta(active_api_plist_path=Path(active['api_plist']),
                              after_root=after, change_set_path=pins, output_path=output)
    return active, after, built, pins, changes, output


def integrated(tmp_path):
    active, after, built, pins, changes, receipt = make_delta(tmp_path)
    root = tmp_path/'candidate'
    root.mkdir()
    result = guard.build_integrated_app(active_api_plist_path=Path(active['api_plist']),
        source_root=after, candidate_root=root, delta_receipt_path=receipt)
    entries = guard.inventory_tree(root/'app')
    manifest = {'schema_version':'v4.release_candidate.v1', 'activation_status':'NOT_ACTIVATED',
                'candidate':{'root':str(root), 'app_root':str(root/'app'), 'release_id':'candidate'},
                'application_inventory':{'entry_count':len(entries), 'entries':entries,
                                         'aggregate_sha256':guard.inventory_digest(entries)},
                'api_integration':result}
    dump(root/'release-manifest.json', manifest)
    return active, after, built, changes, root, manifest


def test_stage_exact_ownership_and_shared_scope_are_supported():
    scope = guard.module_scope('stage', SHARED)
    assert guard._validate_module_scope(scope, sorted(CODE+[DIST+'assets/new.js'])) == scope


@pytest.mark.parametrize('path', [
    'stage_center/selection.py', 'stage_center/runner.py',
    'domains/preselection.py', 'v4/manager_research/keep.py',
    'apps/api/v35_api/config.py', 'apps/api/v35_api/run.py',
    'apps/web/src/components/ManagerPanel.vue', 'ops/prepare_api_only_cutover.py',
])
def test_stage_does_not_acquire_other_owners(path):
    with pytest.raises(ValueError):
        guard._validate_module_scope(guard.module_scope('stage'), [path])


def test_stage_generated_tree_replaces_only_exact_static_delta(tmp_path):
    active, after, built, changes, root, manifest = integrated(tmp_path)
    actual = guard.verify_api_release_candidate(candidate_root=root,
        active_api_plist_path=Path(active['api_plist']))
    assert actual['status'] == 'PASS'
    assert manifest['api_integration']['static_tree'] == changes['static_tree']
    assert static_record(guard.inventory_tree(root/'app')) == changes['static_tree']['after']
    assert not (root/'app'/DIST/'assets/main-old.js').exists()
    assert (root/'app/v4/manager_research/keep.py').read_bytes() == b'ISSUE32_MANAGER = True\n'
    assert (root/'app/domains/preselection.py').read_bytes() == b'ISSUE32_PRESELECTION = True\n'
    assert (Path(active['app_root'])/DIST/'assets/main-old.js').exists()


def test_static_replacement_preserves_readonly_active_directory_modes(tmp_path):
    active,after,built,pins,changes=case(tmp_path)
    app=Path(active['app_root'])
    for path in sorted(app.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path.is_dir():path.chmod(0o555)
    app.chmod(0o555)
    before=guard._inventory_snapshot(app)
    receipt=tmp_path/'delta.json'
    delta.create_module_delta(active_api_plist_path=Path(active['api_plist']),after_root=after,
                              change_set_path=pins,output_path=receipt)
    root=tmp_path/'candidate';root.mkdir()
    guard.build_integrated_app(active_api_plist_path=Path(active['api_plist']),source_root=after,
                               candidate_root=root,delta_receipt_path=receipt)
    assert guard._inventory_snapshot(app)==before
    assert stat.S_IMODE((root/'app').stat().st_mode)==0o555
    assert stat.S_IMODE((root/'app'/DIST/'assets').stat().st_mode)==0o555
    assert not (root/'app'/DIST/'assets/main-old.js').exists()


@pytest.mark.parametrize('remove_binary',[False,True])
def test_binary_static_changes_use_exact_sha_mode_tree_proof(tmp_path,remove_binary):
    active=_write_active_release(tmp_path,tmp_path/'LaunchAgents/com.lexi.v35.api-only.plist',
        files={DIST+'index.html':b'index\n',DIST+'favicon.ico':b'\x00OLD_ICON'})
    after=tmp_path/'after';write(after/DIST/'index.html',b'index\n')
    if not remove_binary:write(after/DIST/'favicon.ico',b'\x00NEW_ICON')
    previous=static_record(guard.inventory_tree(Path(active['app_root'])))
    following=static_record(guard.inventory_tree(after))
    row={'path':DIST+'favicon.ico','before_sha256':sha(b'\x00OLD_ICON'),'before_mode':'0644',
         'after_sha256':None if remove_binary else sha(b'\x00NEW_ICON'),
         'after_mode':None if remove_binary else '0644'}
    changes={'schema_version':delta.CHANGE_SET_SCHEMA,'module':'stage','shared_paths':[],
             'files':[row], 'static_tree':{'schema_version':'v4.api_release_static_tree.v1',
             'root':'apps/web/dist','before':previous,'after':following}}
    pins=tmp_path/'changes.json';dump(pins,changes)
    receipt=tmp_path/'delta.json'
    delta.create_module_delta(active_api_plist_path=Path(active['api_plist']),after_root=after,
                              change_set_path=pins,output_path=receipt)
    root=tmp_path/'candidate';root.mkdir()
    report=guard.build_integrated_app(active_api_plist_path=Path(active['api_plist']),source_root=after,
                                      candidate_root=root,delta_receipt_path=receipt)
    assert report['delta_entries'][0]['unified_diff_sha256'] is None
    assert static_record(guard.inventory_tree(root/'app'))==following


@pytest.mark.parametrize('damage', ['missing_proof', 'digest', 'wrong_base', 'omitted_entry',
                                  'missing_after', 'extra_after', 'wrong_module', 'source_delete',
                                  'duplicate_static_path', 'static_symlink', 'unknown_proof_field'])
def test_static_changes_require_complete_exact_reviewed_proof(tmp_path, damage):
    def mutate(active, after, built, changes):
        if damage == 'missing_proof': changes.pop('static_tree')
        if damage == 'digest': changes['static_tree']['after']['aggregate_sha256'] = 'f'*64
        if damage == 'wrong_base': changes['files'][0]['before_sha256'] = 'f'*64
        if damage == 'omitted_entry':
            changes['files'] = [row for row in changes['files'] if row['path'] != DIST+'assets/main-old.js']
        if damage == 'missing_after': (after/DIST/'assets/main-new.js').unlink()
        if damage == 'extra_after': write(after/DIST/'unreviewed.js', b'UNREVIEWED\n')
        if damage == 'wrong_module': changes['module'] = 'preselection'
        if damage == 'source_delete':
            row = next(row for row in changes['files'] if row['path']=='stage_center/consumer.py')
            row['after_sha256'] = row['after_mode'] = None
            (after/row['path']).unlink()
        if damage == 'duplicate_static_path':
            record = changes['static_tree']['after']
            record['entries'].append(deepcopy(record['entries'][0]))
            record['entry_count'] += 1
            record['aggregate_sha256'] = guard.inventory_digest(record['entries'])
        if damage == 'static_symlink':
            path=after/DIST/'assets/stable.css'; path.unlink(); path.symlink_to(built/'assets/stable.css')
        if damage == 'unknown_proof_field': changes['static_tree']['allow_arbitrary_delete'] = True
    with pytest.raises((ValueError, FileNotFoundError)):
        make_delta(tmp_path, mutate=mutate)
    assert not (tmp_path/'delta.json').exists()


@pytest.mark.parametrize('damage', ['undeclared_static', 'missing_static', 'manager', 'mode', 'active_drift'])
def test_complete_candidate_verifier_rejects_resealed_drift(tmp_path, damage):
    active, after, built, changes, root, manifest = integrated(tmp_path)
    if damage == 'undeclared_static': write(root/'app'/DIST/'rogue.js', b'ROGUE\n')
    if damage == 'missing_static': (root/'app'/DIST/'assets/main-new.js').unlink()
    if damage == 'manager': write(root/'app/v4/manager_research/keep.py', b'OVERWRITTEN\n')
    if damage == 'mode': (root/'app'/DIST/'assets/main-new.js').chmod(0o755)
    if damage == 'active_drift': write(Path(active['app_root'])/'stage_center/consumer.py', b'DRIFT\n')
    inventory = guard.inventory_tree(root/'app')
    manifest['application_inventory'] = {'entry_count':len(inventory), 'entries':inventory,
        'aggregate_sha256':guard.inventory_digest(inventory)}
    dump(root/'release-manifest.json',manifest)
    with pytest.raises(ValueError):
        guard.verify_api_release_candidate(candidate_root=root,
            active_api_plist_path=Path(active['api_plist']))


def prepared_source(tmp_path, readonly=False):
    active, after, built, pins, changes = case(tmp_path)
    code_changes = {key:value for key,value in changes.items() if key != 'static_tree'}
    code_changes['files'] = [row for row in changes['files'] if not row['path'].startswith(DIST)]
    dump(pins,code_changes)
    if readonly:
        for path in CODE: (after/path).chmod(0o444)
        for path in sorted(after.rglob('*'), key=lambda p:len(p.parts), reverse=True):
            if path.is_dir(): path.chmod(0o555)
        after.chmod(0o555)
    before = guard._inventory_snapshot(Path(active['app_root']))
    originals = guard._inventory_snapshot(after)
    assert hasattr(delta, 'prepare_stage_source'), 'Stage R4 needs supported isolated Git source staging'
    source = tmp_path/'source-staging'
    merged = tmp_path/'complete-changes.json'
    result = delta.prepare_stage_source(active_api_plist_path=Path(active['api_plist']),
        after_root=after, change_set_path=pins, built_dist_root=built,
        expected_static_inventory_sha256=changes['static_tree']['after']['aggregate_sha256'],
        source_root=source, output_change_set_path=merged)
    assert guard._inventory_snapshot(Path(active['app_root'])) == before
    assert guard._inventory_snapshot(after) == originals
    return active, after, built, source, merged, result


def test_preparation_creates_concrete_git_source_without_modifying_readonly_inputs(tmp_path):
    active, after, built, source, merged, result = prepared_source(tmp_path,readonly=True)
    assert not (Path(active['app_root'])/'.git').exists()
    tracked = subprocess.check_output(['git','-C',str(source),'ls-files','-z']).decode().split('\0')
    assert sorted(filter(None,tracked)) == sorted(CODE)
    assert all(not path.startswith(DIST) for path in tracked)
    assert result['source_root'] == str(source)
    assert all(path.startswith(DIST) for path in result['include_untracked_paths'])
    assert set(result['include_untracked_paths']) == {row['path'] for row in json.loads(merged.read_text())['files']
        if row['path'].startswith(DIST) and row['after_sha256'] is not None}
    for path in CODE:
        assert stat.S_IMODE((source/path).stat().st_mode)==0o644
        assert stat.S_IMODE((after/path).stat().st_mode)==0o444


def test_existing_full_builder_accepts_isolated_source_and_reports_real_static_origin(tmp_path):
    active, after, built, source, merged, prepared = prepared_source(tmp_path)
    receipt = tmp_path/'delta.json'
    delta.create_module_delta(active_api_plist_path=Path(active['api_plist']),after_root=source,
                             change_set_path=merged,output_path=receipt)
    scheduler = tmp_path/'scheduler.plist'
    _scheduler_plist(scheduler,Path(active['app_root']))
    formal = tmp_path/'formal';formal.mkdir()
    root = tmp_path/'candidate'
    result = builder.build_candidate(source_root=source,candidate_root=root,
        api_plist_path=Path(active['api_plist']),scheduler_plist_path=scheduler,
        python=Path(sys.executable),release_id='candidate',formal_release_root=formal,
        dependency_names=(),api_integration_delta_receipt_path=receipt,
        include_untracked_paths=prepared['include_untracked_paths'])
    assert result['activation_status']=='NOT_ACTIVATED'
    manifest=json.loads((root/'release-manifest.json').read_text())
    assert manifest['frontend_dist']['included_from_current_source'] is True
    assert manifest['frontend_dist']['preserved_from_active_release'] is False
    assert manifest['source']['working_tree_dist_included'] is True
    assert manifest['api_integration']['non_delta_active_release_bytes_preserved'] is True
    assert not (root/'.candidate-build-in-progress').exists()


def test_candidate_verification_cli_requires_pinned_manifest_and_is_readonly(tmp_path):
    active, after, built, changes, root, manifest = integrated(tmp_path)
    before = guard._inventory_snapshot(tmp_path)
    tool = Path(builder.__file__)
    args = [sys.executable,'-B',str(tool),'--verify-api-candidate',
            '--candidate-root',str(root),'--api-plist',str(active['api_plist']),
            '--expected-manifest-sha256',sha((root/'release-manifest.json').read_bytes())]
    result = subprocess.run(args,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']=='PASS'
    assert guard._inventory_snapshot(tmp_path)==before
    rejected=subprocess.run(args[:-2],capture_output=True,text=True)
    assert rejected.returncode!=0
    assert guard._inventory_snapshot(tmp_path)==before


def test_staging_detects_generated_source_drift_before_ready(tmp_path,monkeypatch):
    original=delta.subprocess.check_output
    def mutate(*args,**kwargs):
        value=original(*args,**kwargs)
        write(tmp_path/'source-staging/stage_center/consumer.py',b'UNREVIEWED\n')
        return value
    monkeypatch.setattr(delta.subprocess,'check_output',mutate)
    with pytest.raises(ValueError,match='API_STAGE_SOURCE'):
        prepared_source(tmp_path)
    assert not (tmp_path/'complete-changes.json').exists()


def test_staging_cannot_use_an_independent_extra_git_commit_as_source_proof(tmp_path,monkeypatch):
    original=delta.subprocess.check_output
    def mutate(*args,**kwargs):
        value=original(*args,**kwargs)
        source=tmp_path/'source-staging'
        write(source/'stolen.txt',b'UNREVIEWED\n')
        subprocess.run(['git','-C',str(source),'add','--','stolen.txt'],check=True)
        return value
    monkeypatch.setattr(delta.subprocess,'check_output',mutate)
    with pytest.raises(ValueError,match='API_STAGE_SOURCE'):
        prepared_source(tmp_path)
    assert not (tmp_path/'complete-changes.json').exists()


@pytest.mark.parametrize('damage',['existing_source','alias_dist','wrong_dist_sha','extra_code',
                                  'wrong_after_sha','output_in_active'])
def test_source_preparation_refuses_unreviewed_or_unsafe_staging(tmp_path,damage):
    active, after, built, pins, changes=case(tmp_path)
    changes.pop('static_tree')
    changes['files']=[row for row in changes['files'] if not row['path'].startswith(DIST)]
    source=tmp_path/'source'
    output=tmp_path/'complete.json'
    digest=static_record(guard.inventory_tree(after))['aggregate_sha256']
    if damage=='existing_source': source.mkdir(); write(source/'untouched',b'KEEP\n')
    if damage=='alias_dist':
        alias=tmp_path/'dist-alias';alias.symlink_to(built,target_is_directory=True);built=alias
    if damage=='wrong_dist_sha': digest='f'*64
    if damage=='extra_code':
        row=deepcopy(changes['files'][0]);row['path']='v4/manager_research/keep.py'
        changes['files'].append(row)
    if damage=='wrong_after_sha': changes['files'][0]['after_sha256']='f'*64
    if damage=='output_in_active':output=Path(active['app_root'])/'output.json'
    dump(pins,changes)
    assert hasattr(delta,'prepare_stage_source'), 'Stage R4 staging API missing'
    with pytest.raises((ValueError,FileExistsError,FileNotFoundError)):
        delta.prepare_stage_source(active_api_plist_path=Path(active['api_plist']),after_root=after,
            change_set_path=pins,built_dist_root=built,expected_static_inventory_sha256=digest,
            source_root=source,output_change_set_path=output)
    assert not output.exists()
    if damage=='existing_source': assert (source/'untouched').read_bytes()==b'KEEP\n'
