from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CAS_SCRIPT = Path(__file__).resolve().parent / 'us_only_cas_activation_r3.py'


def load_module():
    spec = importlib.util.spec_from_file_location('us_only_cas_activation_r3_under_test', CAS_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def set_activation_fixture(tmp_path, monkeypatch, *, active_bytes=b'original-plist'):
    module = load_module()
    active = tmp_path / 'active.plist'
    original = tmp_path / 'original.plist'
    candidate_plist = tmp_path / 'candidate.plist'
    baseline_manifest = tmp_path / 'baseline-manifest.json'
    candidate_manifest = tmp_path / 'candidate-manifest.json'
    original.write_bytes(b'original-plist')
    candidate_plist.write_bytes(b'candidate-plist')
    active.write_bytes(active_bytes)
    baseline_manifest.write_bytes(b'baseline-manifest')
    candidate_manifest.write_bytes(b'candidate-manifest')
    original_sha = module.hashlib.sha256(original.read_bytes()).hexdigest()
    candidate_plist_sha = module.hashlib.sha256(candidate_plist.read_bytes()).hexdigest()
    baseline_manifest_sha = module.hashlib.sha256(baseline_manifest.read_bytes()).hexdigest()
    candidate_manifest_sha = module.hashlib.sha256(candidate_manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(module, 'ACTIVE_PLIST', active)
    monkeypatch.setattr(module, 'ORIGINAL_PLIST', original)
    monkeypatch.setattr(module, 'CANDIDATE_PLIST', candidate_plist)
    monkeypatch.setattr(module, 'CANDIDATE_MANIFEST', candidate_manifest)
    monkeypatch.setattr(module, 'ORIGINAL_PLIST_SHA256', original_sha)
    monkeypatch.setattr(module, 'CANDIDATE_PLIST_SHA256', candidate_plist_sha)
    monkeypatch.setattr(module, 'CANDIDATE_MANIFEST_SHA256', candidate_manifest_sha)
    monkeypatch.setitem(module.EXPECTED, module.US_LABEL, {
        'plist_path': str(active), 'plist_sha256': original_sha,
        'manifest_path': str(baseline_manifest), 'manifest_sha256': baseline_manifest_sha,
    })
    monkeypatch.setattr(module, 'R1_ACTIVE_MANIFEST', baseline_manifest)
    monkeypatch.setattr(module, 'R1_ACTIVE_MANIFEST_SHA256', baseline_manifest_sha)
    return module, active, baseline_manifest


@pytest.mark.parametrize('race', ['plist', 'manifest'])
def test_r3_activation_rechecks_r1_plist_and_manifest_after_bootout(tmp_path, monkeypatch, race):
    module, active, r1_manifest = set_activation_fixture(tmp_path, monkeypatch)
    concurrent = b'concurrent-us-version'
    calls = []

    def launchctl(*args):
        calls.append(args)
        if args[0] == 'bootout':
            if race == 'plist':
                active.write_bytes(concurrent)
            else:
                r1_manifest.write_bytes(b'concurrent-manifest-version')

    monkeypatch.setattr(module, 'launchctl', launchctl)
    with pytest.raises(RuntimeError, match='US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT'):
        module.apply_activation({module.US_LABEL: {}})
    assert active.read_bytes() == (concurrent if race == 'plist' else b'original-plist')
    assert calls == [
        ('bootout', f'{module.DOMAIN}/{module.US_LABEL}'),
        ('bootstrap', module.DOMAIN, str(active)),
    ]
    assert not list(tmp_path.glob('.us-market-digest.*.tmp'))


def test_r3_atomic_install_rechecks_r1_manifest_then_plist(tmp_path, monkeypatch):
    module, active, r1_manifest = set_activation_fixture(tmp_path, monkeypatch)
    concurrent = b'concurrent-us-version-during-manifest-check'
    original_sha = module.sha

    def race_during_manifest_check(path):
        result = original_sha(path)
        if path == r1_manifest:
            active.write_bytes(concurrent)
        return result

    monkeypatch.setattr(module, 'sha', race_during_manifest_check)
    with pytest.raises(RuntimeError, match='US_ACTIVE_PLIST_CAS_MISMATCH_BEFORE_REPLACE'):
        module.atomic_install(
            b'r3-candidate-plist',
            expected_current_sha256=module.ORIGINAL_PLIST_SHA256,
            expected_current_manifest_path=r1_manifest,
            expected_current_manifest_sha256=module.R1_ACTIVE_MANIFEST_SHA256,
        )
    assert active.read_bytes() == concurrent
    assert not list(tmp_path.glob('.us-market-digest.*.tmp'))
