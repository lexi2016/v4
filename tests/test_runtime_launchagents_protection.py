"""Shared LaunchAgents snapshot and activation plan-list verification."""
import hashlib
import importlib
import json
import os
import plistlib
from pathlib import Path

import pytest

from ops import activate_runtime_main_stage_api as main
from ops.prepare_runtime_governance_publication import LABELS, snapshot_launch_agents


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _plist(label, **extra):
    payload = {'Label': label, 'ProgramArguments': ['/bin/true'], 'EnvironmentVariables': {}}
    payload.update(extra)
    return plistlib.dumps(payload)


def _write(path, label, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_plist(label, **extra))
    return path


@pytest.fixture
def fixed():
    value = importlib.reload(main.fixed)
    yield value
    importlib.reload(value)


def test_full_live_snapshot_excludes_targets_and_pins_symlink():
    root = Path.home() / 'Library/LaunchAgents'
    rows = snapshot_launch_agents()
    expected = {path.name for path in root.glob('*.plist')
                if path.stem not in set(LABELS.values())}
    assert {Path(row['plist_path']).name for row in rows} == expected
    by_name = {Path(row['plist_path']).name: row for row in rows}
    link = root / 'com.codex.v3.macos.scheduler.plist'
    if link.is_symlink():
        row = by_name[link.name]
        target = Path(os.path.realpath(link))
        assert row['kind'] == 'symlink'
        assert row['label'] == plistlib.loads(target.read_bytes())['Label']
        assert row['readlink'] == os.readlink(link)
        assert row['resolved_target'] == str(target)
        assert row['target']['sha256'] == _sha(target.read_bytes())
        assert row['plist_sha256'] == row['target']['sha256']
        assert row['target']['path'] == str(target)


def test_target_labels_are_excluded_by_name_and_label(tmp_path):
    targets = set(LABELS.values())
    for label in targets:
        _write(tmp_path / (label + '.plist'), label)
    _write(tmp_path / 'renamed.plist', 'com.lexi.v4.api')
    keep = _write(tmp_path / 'com.example.keep.plist', 'com.example.keep')
    rows = snapshot_launch_agents(tmp_path, target_labels=targets)
    assert [row['label'] for row in rows] == ['com.example.keep']
    assert rows[0]['plist_path'] == str(keep)


def test_symlink_identity_and_target_bytes_are_pinned(tmp_path):
    first_target = _write(tmp_path / 'targets' / 'one.plist', 'com.example.link')
    second_target = _write(tmp_path / 'targets' / 'two.plist', 'com.example.link')
    link = tmp_path / 'com.example.link.plist'
    link.symlink_to(first_target)
    original = snapshot_launch_agents(tmp_path)
    assert original[0]['kind'] == 'symlink'
    assert original[0]['readlink'] == str(first_target)

    link.unlink(); link.symlink_to(second_target)
    assert snapshot_launch_agents(tmp_path) != original
    link.unlink(); link.symlink_to(first_target)
    restored = snapshot_launch_agents(tmp_path)
    first_target.write_bytes(_plist('com.example.link', WorkingDirectory='/changed'))
    assert snapshot_launch_agents(tmp_path) != restored

    regular = _write(tmp_path / 'com.example.file.plist', 'com.example.file')
    regular_baseline = snapshot_launch_agents(tmp_path)
    regular.write_bytes(_plist('com.example.file', WorkingDirectory='/changed'))
    assert snapshot_launch_agents(tmp_path) != regular_baseline


def test_broken_symlink_is_rejected(tmp_path):
    link = tmp_path / 'com.example.broken.plist'
    link.symlink_to(tmp_path / 'missing.plist')
    with pytest.raises(ValueError, match='PROTECTED_LABEL_INVALID'):
        snapshot_launch_agents(tmp_path)


def test_prepare_requires_plan_snapshot_match(tmp_path, monkeypatch, fixed):
    plan = {'protected_labels': [{'kind': 'file', 'label': 'x',
                                  'plist_path': '/x', 'plist_sha256': '0' * 64}]}
    evidence = tmp_path / 'evidence'
    monkeypatch.setattr(fixed, 'EVIDENCE', evidence)
    monkeypatch.setattr(fixed.sys, 'executable', str(fixed.PYTHON))
    monkeypatch.setattr(fixed, 'guards', lambda: pytest.fail('guards must not run'))
    monkeypatch.setattr(main, 'snapshot_launch_agents', lambda: [])
    with pytest.raises(ValueError, match='PROTECTED_LABELS_CHANGED'):
        main.prepare(tmp_path / 'plan.json', plan)
    assert not evidence.exists()


def test_switch_requires_prepared_snapshot_before_unload(tmp_path, monkeypatch, fixed):
    evidence = tmp_path / 'evidence'; evidence.mkdir(); records = {}
    for role, pid in (('main', 101), ('stage', None), ('api', 202)):
        original = role.encode() + b'old'; staged = role.encode() + b'new'
        (evidence / (role + '.original.plist')).write_bytes(original)
        (evidence / (role + '.staged.plist')).write_bytes(staged)
        records[role] = {'label': role, 'path': str(tmp_path / (role + '.plist')),
                         'mode': 0o644, 'original_sha256': _sha(original),
                         'staged_sha256': _sha(staged),
                         'loaded': {'pid': pid, 'state': 'running' if pid else 'not running'}}
    plan = {'roles': {role: {'preimage': {'V4_APP_ROOT': str(tmp_path / 'old' / role / 'app'),
                                           'V4_RELEASE_MANIFEST_SHA256': 'old'},
                              'candidate': {'app_root': str(tmp_path / 'new' / role / 'app'),
                                            'manifest_sha256': 'new'},
                              'label': role} for role in ('main', 'stage', 'api')}}
    plan_path = tmp_path / 'plan.json'; plan_path.write_text(json.dumps(plan))
    prepared_labels = [{'kind': 'file', 'label': 'com.example.keep',
                        'plist_path': '/x', 'plist_sha256': '0' * 64}]
    (evidence / 'preparation.json').write_text(json.dumps({
        'records': records, 'script_pins': {}, 'plan_path': str(plan_path.resolve()),
        'plan_sha256': _sha(plan_path.read_bytes()), 'protection': {},
        'data_protection': {}, 'protected_labels': prepared_labels}))
    monkeypatch.setattr(fixed, 'EVIDENCE', evidence)
    monkeypatch.setattr(fixed, 'TARGETS', main.prepared_targets(plan))
    monkeypatch.setattr(fixed, 'pinned', lambda *args: None)
    monkeypatch.setattr(fixed, 'guards', lambda: pytest.fail('guards must not run'))
    monkeypatch.setattr(main, 'snapshot_launch_agents', lambda: [])
    with pytest.raises(ValueError, match='PROTECTED_LABELS_CHANGED'):
        main.switch('fixture', plan_path)


def test_switch_rechecks_snapshot_after_protection_postchecks(tmp_path, monkeypatch, fixed):
    evidence = tmp_path / 'evidence'; evidence.mkdir(); records = {}
    for role, pid in (('main', 101), ('stage', None), ('api', 202)):
        original = role.encode() + b'old'; staged = role.encode() + b'new'
        (evidence / (role + '.original.plist')).write_bytes(original)
        (evidence / (role + '.staged.plist')).write_bytes(staged)
        records[role] = {'label': role, 'path': str(tmp_path / (role + '.plist')),
                         'mode': 0o644, 'original_sha256': _sha(original),
                         'staged_sha256': _sha(staged),
                         'loaded': {'pid': pid, 'state': 'running' if pid else 'not running'}}
    plan = {'roles': {role: {'preimage': {'V4_APP_ROOT': str(tmp_path / 'old' / role / 'app'),
                                           'V4_RELEASE_MANIFEST_SHA256': 'old'},
                              'candidate': {'app_root': str(tmp_path / 'new' / role / 'app'),
                                            'manifest_sha256': 'new'},
                              'label': role} for role in ('main', 'stage', 'api')}}
    plan_path = tmp_path / 'plan.json'; plan_path.write_text(json.dumps(plan))
    (evidence / 'preparation.json').write_text(json.dumps({
        'records': records, 'script_pins': {}, 'plan_path': str(plan_path.resolve()),
        'plan_sha256': _sha(plan_path.read_bytes()), 'protection': {},
        'data_protection': {}, 'protected_labels': []}))
    monkeypatch.setattr(fixed, 'EVIDENCE', evidence)
    monkeypatch.setattr(fixed, 'TARGETS', main.prepared_targets(plan))
    monkeypatch.setattr(fixed, 'pinned', lambda *args: None)
    monkeypatch.setattr(fixed, 'guards', lambda: __import__('contextlib').nullcontext())
    monkeypatch.setattr(fixed, 'loaded', lambda label, *args, **kwargs: records[label]['loaded'])
    monkeypatch.setattr(fixed, 'cas', lambda *args: None)
    monkeypatch.setattr(fixed, 'assert_idle', lambda *args: None)
    monkeypatch.setattr(main, 'zero_admission', lambda *args: {})
    monkeypatch.setattr(fixed, 'external_protection', lambda: {})
    monkeypatch.setattr(fixed, 'data_protection', lambda: {})
    monkeypatch.setattr(fixed, 'verify_release', lambda *args: None)
    monkeypatch.setattr(fixed, 'unload', lambda *args: None)
    monkeypatch.setattr(fixed, 'replace', lambda *args: None)
    monkeypatch.setattr(fixed, 'start', lambda role, raw, ownership: records[role]['loaded'])
    monkeypatch.setattr(fixed, 'verify_forward', lambda: {})
    monkeypatch.setattr(fixed, 'restore_touched', lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(fixed, 'write_json', lambda *args: None)
    snapshots = iter([[], [{'kind': 'file', 'label': 'changed'}]])
    monkeypatch.setattr(main, 'snapshot_launch_agents', lambda: next(snapshots))
    with pytest.raises(ValueError, match='PROTECTED_LABELS_CHANGED'):
        main.switch('fixture', plan_path)