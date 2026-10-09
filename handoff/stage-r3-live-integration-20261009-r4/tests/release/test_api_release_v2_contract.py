"""Consumer-visible v2 contract and real local concurrency regression tests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from ops import api_release_integration as integration
from test_api_release_integration import _write_active_release, _integrated_candidate


def receipt_fixture(tmp_path: Path, *, relative="apps/api/v35_api/app.py", addition=False, module="preselection"):
    files = {"stable-module.py": b"STABLE = True\n"}
    before = None if addition else b"VALUE = 1\n"
    if before is not None:
        files[relative] = before
    active = _write_active_release(tmp_path, tmp_path / "LaunchAgents/com.lexi.v35.api-only.plist", files=files)
    source = tmp_path / "source"
    after = b"VALUE = 2\n"
    path = source / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(after)
    path.chmod(0o640)
    base = integration.read_active_release(Path(active["api_plist"]))
    proof, hunks = integration._diff_proof(before, after) if before is not None else (None, None)
    shared = [relative] if relative in integration.POLICY["shared"] else []
    receipt = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(base),
        "module_scope": integration.module_scope(module, shared),
        "entries": [{"path": relative,
            "before_sha256": hashlib.sha256(before).hexdigest() if before is not None else None,
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "before_mode": f"{stat.S_IMODE((Path(active['app_root']) / relative).stat().st_mode):04o}" if before is not None else None,
            "after_mode": "0640", "unified_diff_sha256": proof, "unified_diff_hunk_count": hunks}],
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    kwargs = dict(active_api_plist_path=Path(active["api_plist"]), source_root=source,
        candidate_root=candidate, delta_receipt_path=receipt_path,
        explicit_untracked_paths=[relative] if addition else [])
    return active, receipt, kwargs


def save_receipt(receipt: dict, kwargs: dict):
    kwargs["delta_receipt_path"].write_text(json.dumps(receipt, sort_keys=True) + "\n")


@pytest.mark.parametrize("level", ["receipt", "entry", "base", "scope"])
def test_unknown_contract_fields_are_refused_before_copy(tmp_path, level):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    target = {"receipt": receipt, "entry": receipt["entries"][0], "base": receipt["base"], "scope": receipt["module_scope"]}[level]
    target["undeclared_override"] = True
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


@pytest.mark.parametrize("field,value", [
    ("after_sha256", "G" * 64), ("before_sha256", "a" * 63),
    ("unified_diff_sha256", "F" * 64), ("unified_diff_hunk_count", True),
    ("before_mode", "644"), ("after_mode", "0899"), ("after_mode", 0o640),
    ("after_sha256", None), ("path", "../escape.py"), ("path", "."),
    ("path", "C:\\escape.py"), ("path", "apps//api/v35_api/app.py"),
])
def test_malformed_entry_contract_is_refused(tmp_path, field, value):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    receipt["entries"][0][field] = value
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


@pytest.mark.parametrize("change", ["unknown_module", "policy_mismatch", "missing_shared", "extra_shared", "platform_as_preselection"])
def test_module_scope_cannot_expand_ownership(tmp_path, change):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    scope = receipt["module_scope"]
    if change == "unknown_module":
        scope["module"] = "any_file_owner"
    elif change == "policy_mismatch":
        scope["policy_sha256"] = "f" * 64
    elif change == "missing_shared":
        scope["shared_paths"] = []
    elif change == "extra_shared":
        scope["shared_paths"].append("apps/api/v35_api/config.py")
    else:
        receipt["entries"][0]["path"] = "ops/api_release_integration.py"
        scope["shared_paths"] = ["ops/api_release_integration.py"]
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


def test_other_module_file_is_refused_even_with_valid_policy_hash(tmp_path):
    _, receipt, kwargs = receipt_fixture(tmp_path, relative="domains/manager_research/job.py", module="manager")
    receipt["module_scope"] = integration.module_scope("preselection")
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError, match="PATH_NOT_OWNED"):
        integration.build_integrated_app(**kwargs)


def test_duplicate_json_key_is_refused_before_copy(tmp_path):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    raw = json.dumps(receipt, sort_keys=True)
    kwargs["delta_receipt_path"].write_text('{"entries": [], ' + raw[1:])
    with pytest.raises(ValueError, match="DUPLICATE_KEY"):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


def test_declared_addition_preserves_existing_file_and_exact_mode(tmp_path):
    active, _, kwargs = receipt_fixture(tmp_path, relative="apps/api/v35_api/preselection_service.py", addition=True)
    (kwargs["source_root"] / "stable-module.py").write_bytes(b"STABLE = False\n")
    result = integration.build_integrated_app(**kwargs)
    app = kwargs["candidate_root"] / "app"
    assert (app / "stable-module.py").read_bytes() == b"STABLE = True\n"
    assert (app / "apps/api/v35_api/preselection_service.py").read_bytes() == b"VALUE = 2\n"
    assert stat.S_IMODE((app / "apps/api/v35_api/preselection_service.py").stat().st_mode) == 0o640
    assert (Path(active["app_root"]) / "stable-module.py").read_bytes() == b"STABLE = True\n"
    assert result["delta_entries"][0]["before_mode"] is None


def test_declared_before_mode_must_match_active_file(tmp_path):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    receipt["entries"][0]["before_mode"] = "0777"
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError, match="BEFORE_MODE"):
        integration.build_integrated_app(**kwargs)


def test_declared_after_mode_must_match_source_file(tmp_path):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    receipt["entries"][0]["after_mode"] = "0755"
    save_receipt(receipt, kwargs)
    with pytest.raises(ValueError, match="SOURCE_MODE"):
        integration.build_integrated_app(**kwargs)


def test_build_rejects_non_delta_change_after_delta_verification(tmp_path, monkeypatch):
    _, _, kwargs = receipt_fixture(tmp_path)
    original = integration._verify_delta_files
    def change(**values):
        result = original(**values)
        (kwargs["candidate_root"] / "app/stable-module.py").write_bytes(b"STABLE = False\n")
        return result
    monkeypatch.setattr(integration, "_verify_delta_files", change)
    with pytest.raises(ValueError):
        integration.build_integrated_app(**kwargs)


@pytest.mark.parametrize("target", ["candidate_manifest", "base_manifest", "delta_receipt"])
def test_verify_rechecks_all_pinned_metadata_at_return(tmp_path, monkeypatch, target):
    active, candidate, _ = _integrated_candidate(tmp_path)
    path = {"candidate_manifest": candidate / "release-manifest.json",
            "base_manifest": Path(active["manifest_path"]),
            "delta_receipt": candidate / integration.DELTA_RECEIPT_NAME}[target]
    original = integration._verify_delta_files
    def change(**values):
        result = original(**values)
        path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(integration, "_verify_delta_files", change)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=Path(active["api_plist"]))


def test_recorded_base_can_be_verified_while_active_pointer_absent(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    result = integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=Path(active["api_plist"]))
    Path(active["api_plist"]).unlink()
    verified = integration.verify_recorded_base(result["base"])
    assert verified["release_id"] == "active-release"
    assert verified["inventory"][1]["path"] == "stable-module.py"


def test_real_child_process_is_blocked_until_lock_released(tmp_path):
    pointer = tmp_path / "com.lexi.v35.api-only.plist"
    script = '''from pathlib import Path
import sys
from ops.api_release_integration import shared_api_release_lock
try:
    with shared_api_release_lock(Path(sys.argv[1]), timeout_seconds=0.06):
        print("ACQUIRED")
except ValueError as error:
    print(str(error))
    raise SystemExit(9)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(integration.__file__).resolve().parents[1]), PYTHONDONTWRITEBYTECODE="1")
    def child():
        return subprocess.run([sys.executable, "-B", "-c", script, str(pointer)], env=env,
                              capture_output=True, text=True, timeout=5, cwd=tmp_path)
    with integration.shared_api_release_lock(pointer) as lease:
        integration.assert_api_release_lock(lease, pointer)
        blocked = child()
        assert blocked.returncode == 9
        assert blocked.stdout.strip() == "API_RELEASE_SHARED_LOCK_BUSY"
        held_inode = integration.api_release_lock_path(pointer).stat().st_ino
    assert integration.api_release_lock_path(pointer).stat().st_ino == held_inode
    unblocked = child()
    assert unblocked.returncode == 0
    assert unblocked.stdout.strip() == "ACQUIRED"
    assert integration.api_release_lock_path(pointer).stat().st_ino == held_inode


def test_forged_expired_and_replaced_lock_leases_are_rejected(tmp_path):
    pointer = tmp_path / "com.lexi.v35.api-only.plist"
    with integration.shared_api_release_lock(pointer) as lease:
        with pytest.raises(ValueError):
            integration.assert_api_release_lock(copy.copy(lease), pointer)
        lock = integration.api_release_lock_path(pointer)
        lock.rename(tmp_path / "parked-lock")
        lock.write_bytes(b"")
        with pytest.raises(ValueError):
            integration.assert_api_release_lock(lease, pointer)
    with pytest.raises(ValueError):
        integration.assert_api_release_lock(lease, pointer)


def test_lock_path_symlink_is_refused_without_touching_target(tmp_path):
    pointer = tmp_path / "com.lexi.v35.api-only.plist"
    outside = tmp_path / "outside-file"
    outside.write_bytes(b"KEEP\n")
    integration.api_release_lock_path(pointer).symlink_to(outside)
    with pytest.raises(ValueError):
        with integration.shared_api_release_lock(pointer):
            pytest.fail("unsafe lock acquired")
    assert outside.read_bytes() == b"KEEP\n"


def test_lock_lease_is_rechecked_after_delta_validation(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    pointer = Path(active["api_plist"])
    original = integration._verify_delta_files
    def change(**values):
        result = original(**values)
        path = integration.api_release_lock_path(pointer)
        path.rename(path.with_suffix(".parked"))
        path.write_bytes(b"")
        return result
    with integration.shared_api_release_lock(pointer) as lease:
        monkeypatch.setattr(integration, "_verify_delta_files", change)
        with pytest.raises(ValueError, match="LOCK_LEASE"):
            integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=pointer,
                lock_lease=lease, require_shared_lock=True)


@pytest.mark.parametrize("inside", ["active", "source"])
def test_candidate_cannot_be_built_inside_an_input_root(tmp_path, inside):
    active, _, kwargs = receipt_fixture(tmp_path)
    root = Path(active["app_root"]) if inside == "active" else kwargs["source_root"]
    forbidden = root / "candidate"
    forbidden.mkdir()
    kwargs["candidate_root"] = forbidden
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    with pytest.raises(ValueError, match="OVERLAPS_INPUT_ROOT"):
        integration.build_integrated_app(**kwargs)
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*")) == before


def test_readonly_active_directories_are_preserved_after_applying_delta(tmp_path):
    active, _, kwargs = receipt_fixture(tmp_path)
    Path(active["app_root"]).chmod(0o555)
    integration.build_integrated_app(**kwargs)
    app = kwargs["candidate_root"] / "app"
    assert stat.S_IMODE(app.stat().st_mode) == 0o555
    assert (app / "apps/api/v35_api/app.py").read_bytes() == b"VALUE = 2\n"
    assert (Path(active["app_root"]) / "apps/api/v35_api/app.py").read_bytes() == b"VALUE = 1\n"


def test_an_explicit_mode_only_delta_is_bound_and_preserves_content(tmp_path):
    _, receipt, kwargs = receipt_fixture(tmp_path)
    path = kwargs["source_root"] / "apps/api/v35_api/app.py"
    path.write_bytes(b"VALUE = 1\n")
    entry = receipt["entries"][0]
    entry["after_sha256"] = entry["before_sha256"]
    entry["unified_diff_sha256"] = hashlib.sha256(b"").hexdigest()
    entry["unified_diff_hunk_count"] = 0
    save_receipt(receipt, kwargs)
    result = integration.build_integrated_app(**kwargs)
    changed = kwargs["candidate_root"] / "app/apps/api/v35_api/app.py"
    assert changed.read_bytes() == b"VALUE = 1\n"
    assert stat.S_IMODE(changed.stat().st_mode) == 0o640
    assert result["delta_entries"][0]["after_mode"] == "0640"
