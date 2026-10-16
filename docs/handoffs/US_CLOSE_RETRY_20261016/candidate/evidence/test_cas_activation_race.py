from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CAS_SCRIPT = Path(__file__).resolve().parents[1] / "us_only_cas_activation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("us_only_cas_activation_under_test", CAS_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def set_activation_fixture(tmp_path, monkeypatch, *, active_bytes=b"original-plist"):
    module = load_module()
    active = tmp_path / "active.plist"
    original = tmp_path / "original.plist"
    candidate_plist = tmp_path / "candidate.plist"
    baseline_manifest = tmp_path / "baseline-manifest.json"
    candidate_manifest = tmp_path / "candidate-manifest.json"
    original.write_bytes(b"original-plist")
    candidate_plist.write_bytes(b"candidate-plist")
    active.write_bytes(active_bytes)
    baseline_manifest.write_bytes(b"baseline-manifest")
    candidate_manifest.write_bytes(b"candidate-manifest")
    original_sha = module.hashlib.sha256(original.read_bytes()).hexdigest()
    candidate_plist_sha = module.hashlib.sha256(candidate_plist.read_bytes()).hexdigest()
    baseline_manifest_sha = module.hashlib.sha256(baseline_manifest.read_bytes()).hexdigest()
    candidate_manifest_sha = module.hashlib.sha256(candidate_manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "ACTIVE_PLIST", active)
    monkeypatch.setattr(module, "ORIGINAL_PLIST", original)
    monkeypatch.setattr(module, "CANDIDATE_PLIST", candidate_plist)
    monkeypatch.setattr(module, "CANDIDATE_MANIFEST", candidate_manifest)
    monkeypatch.setattr(module, "ORIGINAL_PLIST_SHA256", original_sha)
    monkeypatch.setattr(module, "CANDIDATE_PLIST_SHA256", candidate_plist_sha)
    monkeypatch.setattr(module, "CANDIDATE_MANIFEST_SHA256", candidate_manifest_sha)
    monkeypatch.setitem(module.EXPECTED, module.US_LABEL, {
        "plist_path": str(active), "plist_sha256": original_sha,
        "manifest_path": str(baseline_manifest), "manifest_sha256": baseline_manifest_sha,
    })
    return module, active, baseline_manifest, candidate_manifest


@pytest.mark.parametrize("race", ["plist", "manifest"])
def test_activation_rechecks_both_us_pins_after_bootout(tmp_path, monkeypatch, race):
    module, active, baseline_manifest, _ = set_activation_fixture(tmp_path, monkeypatch)
    concurrent = b"concurrent-us-version"
    calls = []

    def launchctl(*args):
        calls.append(args)
        if args[0] == "bootout":
            if race == "plist":
                active.write_bytes(concurrent)
            else:
                baseline_manifest.write_bytes(b"concurrent-manifest-version")

    monkeypatch.setattr(module, "launchctl", launchctl)
    with pytest.raises(RuntimeError, match="US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT"):
        module.apply_activation({module.US_LABEL: {"manifest_declared_sha256": module.EXPECTED[module.US_LABEL]["manifest_sha256"]}})
    assert active.read_bytes() == (concurrent if race == "plist" else b"original-plist")
    assert calls == [("bootout", f"{module.DOMAIN}/{module.US_LABEL}"), ("bootstrap", module.DOMAIN, str(active))]
    assert not list(tmp_path.glob(".us-market-digest.*.tmp"))


def test_activation_rollback_skips_a_concurrent_us_plist(tmp_path, monkeypatch):
    module, active, _, candidate_manifest = set_activation_fixture(tmp_path, monkeypatch, active_bytes=b"candidate-plist")
    # The pre-activation state is candidate, with candidate manifest present.
    original_bytes = module.ORIGINAL_PLIST.read_bytes()
    module.CANDIDATE_MANIFEST.write_bytes(candidate_manifest.read_bytes())
    calls = []

    def launchctl(*args):
        calls.append(args)
        if args[0] == "bootout":
            active.write_bytes(b"concurrent-us-version")

    monkeypatch.setattr(module, "launchctl", launchctl)
    with pytest.raises(RuntimeError, match="US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT"):
        module.apply_rollback({})
    assert active.read_bytes() == b"concurrent-us-version"
    assert calls == [("bootout", f"{module.DOMAIN}/{module.US_LABEL}"), ("bootstrap", module.DOMAIN, str(active))]
    assert module.ORIGINAL_PLIST.read_bytes() == original_bytes


def test_atomic_replace_rechecks_us_manifest_after_temp_is_written(tmp_path, monkeypatch):
    module, active, baseline_manifest, _ = set_activation_fixture(tmp_path, monkeypatch)
    original_active = active.read_bytes()
    original_sha = module.sha

    def race_before_manifest_check(path):
        if path == baseline_manifest:
            baseline_manifest.write_bytes(b"concurrent-manifest-version")
        return original_sha(path)

    monkeypatch.setattr(module, "sha", race_before_manifest_check)
    with pytest.raises(RuntimeError, match="US_ACTIVE_MANIFEST_CAS_MISMATCH_BEFORE_REPLACE"):
        module.atomic_install(
            b"candidate-plist",
            expected_current_sha256=module.ORIGINAL_PLIST_SHA256,
            expected_current_manifest_path=baseline_manifest,
            expected_current_manifest_sha256=module.EXPECTED[module.US_LABEL]["manifest_sha256"],
        )
    assert active.read_bytes() == original_active
    assert not list(tmp_path.glob(".us-market-digest.*.tmp"))


def test_manifest_check_race_rechecks_plist_before_replace(tmp_path, monkeypatch):
    module, active, baseline_manifest, _ = set_activation_fixture(tmp_path, monkeypatch)
    concurrent = b"concurrent-us-version-during-manifest-check"
    original_sha = module.sha

    def race_during_manifest_check(path):
        result = original_sha(path)
        if path == baseline_manifest:
            active.write_bytes(concurrent)
        return result

    monkeypatch.setattr(module, "sha", race_during_manifest_check)
    with pytest.raises(RuntimeError, match="US_ACTIVE_PLIST_CAS_MISMATCH_BEFORE_REPLACE"):
        module.atomic_install(
            b"candidate-plist",
            expected_current_sha256=module.ORIGINAL_PLIST_SHA256,
            expected_current_manifest_path=baseline_manifest,
            expected_current_manifest_sha256=module.EXPECTED[module.US_LABEL]["manifest_sha256"],
        )
    assert active.read_bytes() == concurrent
    assert not list(tmp_path.glob(".us-market-digest.*.tmp"))
