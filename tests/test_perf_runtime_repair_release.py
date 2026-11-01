"""Frozen repair helper: inheritance, unload ordering, CAS and recovery only."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def repair():
    path = Path(__file__).resolve().parents[1] / "docs/handoffs/perf-runtime-repair-20261101/release_repair.py"
    spec = importlib.util.spec_from_file_location("perf_repair_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_overlay_preserves_inherited_module_bytes(repair):
    old = b"one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    new = old.replace(b"two\n", b"two fixed\n")
    inherited = old + b"inherited SOP and routing\n"
    assert repair.exact_overlay(old, new, inherited) == new + b"inherited SOP and routing\n"
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        repair.exact_overlay(old, new, inherited.replace(b"three\n", b"changed context\n"))
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        repair.exact_overlay(old, new, old + old)


def test_unload_waits_for_both_job_and_listener(repair, monkeypatch):
    calls = []
    states = iter([0, 0, 1, 1])
    listeners = iter([True, False])

    def launch(*args):
        calls.append(args)
        code = next(states) if args[0] == "print" else 0
        return SimpleNamespace(returncode=code, stderr="Could not find service" if code else "")

    monkeypatch.setattr(repair, "launchctl", launch)
    monkeypatch.setattr(repair, "listener_present", lambda: next(listeners))
    monkeypatch.setattr(repair.time, "sleep", lambda _: None)
    repair.unload()
    assert [args[0] for args in calls] == ["print", "bootout", "print", "print", "print"]


def test_unload_timeout_never_bootstraps(repair, monkeypatch):
    calls = []
    clock = iter([0, 0, 21])
    monkeypatch.setattr(repair.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(repair.time, "sleep", lambda _: None)

    def launch(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(repair, "launchctl", launch)
    with pytest.raises(RuntimeError, match="UNLOAD_OR_LISTENER_TIMEOUT"):
        repair.unload()
    assert "bootstrap" not in [args[0] for args in calls]


def _switch_fixture(repair, monkeypatch, tmp_path):
    old, new = b"old pinned plist", b"new pinned plist"
    plist, staged, backup, receipt = (tmp_path / name for name in ("live", "new", "old", "receipt"))
    plist.write_bytes(old)
    staged.write_bytes(new)
    backup.write_bytes(old)
    receipt.write_text(json.dumps({"candidate_plist_sha256": repair.sha(new), "manifest_sha256": "manifest"}))
    for key, value in (("PLIST", plist), ("STAGED_PLIST", staged), ("BACKUP", backup),
                       ("RECEIPT", receipt), ("PLIST_SHA", repair.sha(old))):
        monkeypatch.setattr(repair, key, value)
    monkeypatch.setattr(repair, "release_lock", lambda: nullcontext())
    monkeypatch.setattr(repair, "verify_candidate", lambda **_: {"status": "PASS"})
    monkeypatch.setattr(repair, "validate_process_files", lambda _: {"status": "PASS"})
    return plist, old, new


def test_plist_cas_conflict_never_unloads(repair, monkeypatch, tmp_path):
    plist, _, _ = _switch_fixture(repair, monkeypatch, tmp_path)
    plist.write_bytes(b"other owner")
    monkeypatch.setattr(repair, "unload", lambda: pytest.fail("CAS must precede unload"))
    with pytest.raises(ValueError, match="ACTIVE_PLIST_CAS_CHANGED"):
        repair.switch()
    assert plist.read_bytes() == b"other owner"


def test_failed_cutover_restores_original_and_verifies_recovery(repair, monkeypatch, tmp_path):
    plist, old, new = _switch_fixture(repair, monkeypatch, tmp_path)
    events = []
    monkeypatch.setattr(repair, "unload", lambda: events.append("unload"))

    def start(raw, *, frontend):
        events.append((raw, frontend))
        assert plist.read_bytes() == raw
        if raw == new:
            raise RuntimeError("bootstrap or readiness failed")

    monkeypatch.setattr(repair, "start_and_validate", start)
    with pytest.raises(RuntimeError, match="AUTOMATIC_ROLLBACK_VERIFIED"):
        repair.switch()
    assert events == ["unload", (new, True), "unload", (old, False)]
    assert plist.read_bytes() == old


def test_real_pinned_live_manifest_preflight(repair):
    # Deliberately no mocked tooling or compatible invented role contract:
    # this exercises the exact package that rejected the first helper.
    manifest, inventory = repair.preflight_base()
    assert manifest["candidate"]["module_role"] == "api"
    assert manifest["candidate"]["root"] == str(repair.BASE.parent)
    assert len(inventory) == 1301
    assert repair.api_tools().inventory_digest(inventory) == "e6ff115888bdda8e2c09c46ce53a2c0bae47d9cad9da67a19922bad2e8291de9"
    assert set(repair.checked_overlay()) == set(repair.BASE_FILES)


def test_owner_change_during_unload_prevents_recovery_service_action(repair, monkeypatch, tmp_path):
    plist, _, _ = _switch_fixture(repair, monkeypatch, tmp_path)
    calls = []

    def unload():
        calls.append("unload")
        plist.write_bytes(b"other owner started a different service")

    monkeypatch.setattr(repair, "unload", unload)
    monkeypatch.setattr(repair, "start_and_validate", lambda *a, **kw: pytest.fail("must not start"))
    with pytest.raises(RuntimeError, match="ROLLBACK_CAS_CONFLICT"):
        repair.switch()
    assert calls == ["unload"]
    assert plist.read_bytes() == b"other owner started a different service"


def test_top_level_nested_identity_and_baseline_provenance_match(repair):
    manifest = {"schema_version": "v4.release_candidate.v1",
        "release_id": repair.BASE.name, "app_root": str(repair.BASE / "app"),
        "candidate": {"module_role": "api"}}
    repair.set_candidate_metadata(manifest)
    repair.assert_manifest_identity(manifest, repair.TARGET)
    assert manifest["release_id"] == manifest["candidate"]["release_id"] == repair.TARGET.name
    assert manifest["app_root"] == manifest["candidate"]["app_root"] == str(repair.TARGET / "app")
    assert manifest["source_root"] == str(repair.SOURCE)
    assert manifest["source_commit"] == manifest["source_provenance"]["baseline_commit"] == repair.BASE_COMMIT
    assert manifest["source_provenance"]["commit_contains_repair"] is False
    assert set(manifest["source_provenance"]["reviewed_source_sha256"]) == set(repair.BASE_FILES)
    for key, wrong in (("release_id", repair.BASE.name), ("app_root", str(repair.BASE / "app")),
                       ("source_root", "/old/worktree")):
        broken = {**manifest, key: wrong}
        with pytest.raises(ValueError, match="TOP_LEVEL_IDENTITY_OR_PROVENANCE"):
            repair.assert_manifest_identity(broken, repair.TARGET)


def test_detailed_identity_filters_only_active_plist_comparison(repair):
    env = {"V4_APP_ROOT": str(repair.TARGET / "app"), "V4_RELEASE_ID": repair.TARGET.name,
           "V4_RELEASE_MANIFEST_SHA256": "a" * 64}
    detail = {"status": "DRIFT", "release_id_status": "VERIFIED", "app_root_status": "VERIFIED",
        "release_manifest_sha_status": "VERIFIED", "declared_environment": env,
        "plist_binding_status": "DRIFT", "plist_bindings": {"V4_RELEASE_ID": {"status": "DRIFT"}},
        "receipt_status": "CANNOT_CONFIRM", "runtime_inventory_status": "CANNOT_CONFIRM",
        "runtime_dependency_manifest_status": "CANNOT_CONFIRM", "selected_modules_status": "VERIFIED"}
    checked = repair.check_detailed_identity(detail, env)
    assert checked["staged_release_pins"] == "VERIFIED"
    assert checked["statuses"]["receipt_status"] == "CANNOT_CONFIRM"
    assert checked["statuses"]["runtime_inventory_status"] == "CANNOT_CONFIRM"
    with pytest.raises(ValueError, match="DETAILED_IDENTITY_DRIFT"):
        repair.check_detailed_identity({**detail, "selected_imported_modules": [{"status": "DRIFT"}]}, env)
    with pytest.raises(ValueError, match="FIELD_NOT_VERIFIED:release_id_status"):
        repair.check_detailed_identity({**detail, "release_id_status": "DRIFT"}, env)
