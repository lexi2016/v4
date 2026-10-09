from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

TOOLS = Path(os.environ.get('R4_TOOL_ROOT', Path(__file__).resolve().parents[1] / 'tools'))


def module(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root):
    return {p.relative_to(root).as_posix(): (digest(p.read_bytes()), stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def setup(tmp_path):
    package = tmp_path / 'package'
    actual = tmp_path / 'actual'
    web = actual / 'apps/web'
    (web / 'src').mkdir(parents=True)
    (web / 'dist/assets').mkdir(parents=True)
    (web / 'dist/manager-selection').mkdir(parents=True)
    (web / 'package.json').write_text(json.dumps({'name': 'fixture', 'scripts': {'build': 'vite build'}}))
    (web / 'package-lock.json').write_text('{"lockfileVersion":3}\n')
    (web / 'src/App.vue').write_text('<template>before</template>\n')
    (web / 'dist/index.html').write_text('old entry')
    (web / 'dist/manager-selection/index.html').write_text('old manager entry')
    (web / 'dist/assets/old.js').write_text('old bundle')
    after = package / 'after/ui/apps/web/src/App.vue'
    after.parent.mkdir(parents=True)
    after.write_text('<template>research</template>\n')
    policy = {'schema_version': 'V4_CANARY_SOURCE_POLICY_V1', 'groups': {'ui': {'copy_roots': ['apps/web']}}}
    raw_policy = (json.dumps(policy, sort_keys=True) + '\n').encode()
    (package / 'CANARY_SOURCE_POLICY.json').write_bytes(raw_policy)
    mapping = {'canary_source_policy_sha256': digest(raw_policy), 'RESEARCH_ONLY': True,
               'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
               'files': [{'group': 'ui', 'relative_path': 'apps/web/src/App.vue',
                          'after_path': 'after/ui/apps/web/src/App.vue',
                          'after_sha256': digest(after.read_bytes()),
                          'accepted_before_sha256': [digest((web / 'src/App.vue').read_bytes())]}]}
    (package / 'SOURCE_MAP.json').write_text(json.dumps(mapping))
    for p in actual.rglob('*'):
        p.chmod(0o555 if p.is_dir() else 0o444)
    actual.chmod(0o555)
    prepared = tmp_path / 'prepared'
    result = module('prepare_canary').prepare(package, 'ui', actual, prepared)
    assert result['status'] == 'CANARY_PREPARED', result
    return SimpleNamespace(package=package, actual=actual, prepared=prepared,
                           destination=tmp_path / 'build', before=tree(actual), prepared_before=tree(prepared))


def fake_npm(monkeypatch, builder, *, failure=None, mutate_source=False, symlink=False, omit_manager=False,
             missing_script=False, manifest_to_mutate=None):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        cwd = Path(kwargs['cwd'])
        assert cwd.name == 'web'
        assert cwd.stat().st_mode & stat.S_IWUSR
        assert (cwd / 'src/App.vue').stat().st_mode & stat.S_IWUSR
        if failure == command[1]:
            return SimpleNamespace(returncode=9, stdout='failed fixture command\n', stderr='fixture error\n')
        if command[1:3] == ['run', 'build']:
            dist = cwd / 'dist'
            (dist / 'assets').mkdir(parents=True)
            script = '/assets/missing-main.js' if missing_script else '/assets/new.js'
            (dist / 'index.html').write_text('<script type="module" src="' + script + '"></script>')
            if not omit_manager:
                (dist / 'manager-selection').mkdir()
                (dist / 'manager-selection/index.html').write_text('<script src="../assets/new.js"></script>')
            if symlink:
                (dist / 'assets/new.js').symlink_to(cwd / 'src/App.vue')
            else:
                (dist / 'assets/new.js').write_text('compiled fixture artifact')
            if mutate_source:
                (cwd / 'src/App.vue').write_text('unexpected build source mutation')
            if manifest_to_mutate:
                value = json.loads(manifest_to_mutate.read_text())
                value['source_root'] = '/changed/source/root'
                manifest_to_mutate.write_text(json.dumps(value))
        return SimpleNamespace(returncode=0, stdout='fixture command\n', stderr='')

    monkeypatch.setattr(builder.subprocess, 'run', run)
    return calls


def test_readonly_prepared_ui_builds_in_new_writable_tree_and_preserves_history_entry(setup, monkeypatch):
    builder = module('build_stage_ui')
    calls = fake_npm(monkeypatch, builder)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'UI_BUILD_PREPARED', result
    assert calls == [['npm', 'ci'], ['npm', 'run', 'build']]
    assert tree(setup.actual) == setup.before
    assert tree(setup.prepared) == setup.prepared_before
    assert result['source_bytes_and_modes_unchanged'] is True
    assert result['build_source_bytes_unchanged'] is True
    assert result['source_map_sha256'] == digest((setup.package / 'SOURCE_MAP.json').read_bytes())
    paths = {x['path'] for x in result['static_inventory']}
    assert 'apps/web/dist/manager-selection/index.html' in paths
    assert 'apps/web/dist/assets/old.js' not in paths
    assert len(result['static_inventory_sha256']) == 64
    assert json.loads((setup.destination / 'BUILD_RECEIPT.json').read_text()) == result


def test_prepared_source_drift_rejects_before_output_or_npm(setup, monkeypatch):
    builder = module('build_stage_ui')
    changed = setup.prepared / 'apps/web/src/App.vue'
    changed.chmod(0o644)
    changed.write_text('drift')
    calls = fake_npm(monkeypatch, builder)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'PREFLIGHT_FAILED'
    assert calls == [] and not setup.destination.exists()


def test_missing_prepare_manifest_rejects_before_output(setup, monkeypatch):
    builder = module('build_stage_ui')
    setup.prepared.chmod(0o755)
    (setup.prepared / 'CANARY_SOURCE_MANIFEST.json').unlink()
    calls = fake_npm(monkeypatch, builder)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'PREFLIGHT_FAILED'
    assert calls == [] and not setup.destination.exists()


def test_failed_npm_ci_is_not_a_build_pass(setup, monkeypatch):
    builder = module('build_stage_ui')
    calls = fake_npm(monkeypatch, builder, failure='ci')
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert calls == [['npm', 'ci']]
    assert result['commands'][0]['exit_code'] == 9
    assert tree(setup.prepared) == setup.prepared_before
    assert result.get('static_inventory_sha256') is None


def test_build_changing_source_cannot_seal_static_artifacts(setup, monkeypatch):
    builder = module('build_stage_ui')
    fake_npm(monkeypatch, builder, mutate_source=True)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert result['build_source_bytes_unchanged'] is False
    assert result.get('static_inventory_sha256') is None
    assert tree(setup.prepared) == setup.prepared_before


def test_static_symlink_is_rejected(setup, monkeypatch):
    builder = module('build_stage_ui')
    fake_npm(monkeypatch, builder, symlink=True)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert result.get('static_inventory_sha256') is None


def test_missing_existing_manager_entry_is_rejected(setup, monkeypatch):
    builder = module('build_stage_ui')
    fake_npm(monkeypatch, builder, omit_manager=True)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert 'STATIC_ENTRY_REMOVED:manager-selection/index.html' in result['errors']


def test_output_inside_prepared_source_is_rejected(setup, monkeypatch):
    builder = module('build_stage_ui')
    calls = fake_npm(monkeypatch, builder)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared,
                                   destination=setup.prepared / 'bad-output')
    assert result['status'] == 'PREFLIGHT_FAILED'
    assert calls == [] and not (setup.prepared / 'bad-output').exists()


def test_missing_local_entry_script_cannot_seal_unrelated_javascript(setup, monkeypatch):
    builder = module('build_stage_ui')
    fake_npm(monkeypatch, builder, missing_script=True)
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert result.get('static_inventory_sha256') is None
    assert any(error.startswith('STATIC_LOCAL_DEPENDENCY_MISSING:') for error in result['errors'])


def test_prepare_manifest_changed_during_build_cannot_seal_outputs(setup, monkeypatch):
    builder = module('build_stage_ui')
    fake_npm(monkeypatch, builder, manifest_to_mutate=setup.prepared / 'CANARY_SOURCE_MANIFEST.json')
    result = builder.build_stage_ui(package=setup.package, prepared_ui=setup.prepared, destination=setup.destination)
    assert result['status'] == 'BUILD_FAILED'
    assert result.get('static_inventory_sha256') is None
    assert result['source_bytes_and_modes_unchanged'] is False
