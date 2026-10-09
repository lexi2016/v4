"""Independent R3 review probes. All writable fixtures are under tmp_path."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(os.environ.get("V4_R3_REVIEW_APP_ROOT", str(ROOT / "candidate")))
EXACT = {
    "infrastructure/_research_peripheral_store_parts/_namespace.py",
    "infrastructure/scheduling/manager_announcement_supervisor.py",
    "ops/render_manager_announcement_binding.py",
    "ops/run_manager_announcement_cycle.py",
    "v3_shared_data/shared_data/hk_daily_supplement.py",
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_is_exact_five_key_addition_and_all_previous_rules_unchanged():
    before = load("review_policy_before", ROOT / "release_policy_review/before/ops/api_release_integration.py")
    after = load("review_policy_after", ROOT / "release_policy_review/after/ops/api_release_integration.py")
    expected = deepcopy(before.POLICY)
    assert not (EXACT & expected["shared"].keys())
    expected["shared"].update({path: ["manager"] for path in EXACT})
    assert after.POLICY == expected
    assert before.POLICY_SHA256 != after.POLICY_SHA256
    for path in EXACT:
        with pytest.raises(ValueError, match="SHARED_PATH_NOT_ALLOWED"):
            before.module_scope("manager", [path])
        assert after._validate_module_scope(after.module_scope("manager", [path]), [path])
        with pytest.raises(ValueError, match="SHARED_PATHS_NOT_EXACT"):
            after._validate_module_scope(after.module_scope("manager"), [path])
        for module in set(after.POLICY["modules"]) - {"manager"}:
            with pytest.raises(ValueError, match="SHARED_PATH_NOT_ALLOWED"):
                after.module_scope(module, [path])
        for neighbor in (path + ".bak", str(Path(path).parent / "neighbor.py")):
            with pytest.raises(ValueError, match="SHARED_PATH_NOT_ALLOWED"):
                after.module_scope("manager", [neighbor])


def test_previous_receipt_cannot_become_valid_by_adopting_the_new_policy():
    before = load("review_old_policy", ROOT / "release_policy_review/before/ops/api_release_integration.py")
    after = load("review_new_policy", ROOT / "release_policy_review/after/ops/api_release_integration.py")
    original_scope = before.module_scope("manager")
    with pytest.raises(ValueError, match="SCOPE_POLICY_MISMATCH"):
        after._validate_module_scope(original_scope, ["v4/manager_research/service.py"])
    assert original_scope["policy_sha256"] == before.POLICY_SHA256


def test_two_card_projection_keeps_each_native_reference_with_its_own_anchor():
    from v4.manager_research.workspace_daily_channels import _references

    refs = [
        {"card_id": "card-a", "source_date": "20261008", "source_refs": [
            {"owner": "original-panel", "payload_path": "panel-a.parquet",
             "payload_sha256": "a" * 64, "manifest_path": "panel-a.json",
             "manifest_sha256": "b" * 64, "body": "synthetic large body" * 10000,
             "source_refs": [{"payload_sha256": "c" * 64}]}
        ]},
        {"card_id": "card-b", "art_code": "AN_SYNTHETIC", "source_refs": [
            {"owner": "original-master", "artifact_path": "master.csv",
             "artifact_sha256": "d" * 64, "source_id": "master", "run_id": "e" * 32,
             "pointer_path": "latest.json", "pointer_sha256": "f" * 64}
        ]},
    ]
    original = deepcopy(refs)
    result = _references(refs)
    by_owner = {row["owner"]: row for row in result if "owner" in row}
    assert by_owner["original-panel"]["card_id"] == "card-a"
    assert by_owner["original-panel"]["manifest_sha256"] == "b" * 64
    assert by_owner["original-master"]["card_id"] == "card-b"
    assert by_owner["original-master"]["art_code"] == "AN_SYNTHETIC"
    assert by_owner["original-master"]["pointer_sha256"] == "f" * 64
    encoded = json.dumps(result)
    assert "synthetic large body" not in encoded and "c" * 64 not in encoded
    assert all(not isinstance(value, (dict, list)) for row in result for value in row.values())
    assert refs == original


def make_delivery(tmp_path):
    verifier = load("independent_delivery_verifier", ROOT / "tools/verify_delivery.py")
    package, source = tmp_path / "package", tmp_path / "isolated-source"
    package.mkdir()
    source.mkdir()
    before, after = b"old\n", b"new\n"
    paths = {}
    for side, raw in (("before", before), ("after", after)):
        relative = f"{side}/worker/ops/owned.py"
        path = package / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        paths.update({side + "_path": relative, side + "_sha256": verifier.sha(raw), side + "_bytes": len(raw)})
    patch = b"synthetic fixed patch bytes\n"
    (package / "worker.patch").write_bytes(patch)
    (source / "ops").mkdir()
    (source / "ops/owned.py").write_bytes(before)
    manifest = {"schema_version": verifier.SCHEMA,
        "files": [{"profile": "worker", "path": "ops/owned.py", **paths}],
        "profiles": {"worker": {"patch_path": "worker.patch", "patch_sha256": verifier.sha(patch)}}}
    (package / "source_manifest.json").write_text(json.dumps(manifest))
    return verifier, package, source


def tree_identity(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_verifier_before_after_and_directory_alias_are_read_only(tmp_path):
    verifier, package, source = make_delivery(tmp_path)
    identity = tree_identity(tmp_path)
    result = verifier.verify(package, profile="worker", source_root=source, against="before")
    assert result["status"] == "PASS" and result["source_checked"] == ["ops/owned.py"]
    assert result["source_writes"] == 0 and result["business_io"] is False
    with pytest.raises(ValueError, match="SOURCE_AFTER_MISMATCH"):
        verifier.verify(package, profile="worker", source_root=source, against="after")
    assert tree_identity(tmp_path) == identity
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="SOURCE_ROOT_NOT_EXACT_DIRECTORY"):
        verifier.verify(package, profile="worker", source_root=alias, against="before")


def test_verifier_rejects_traversal_and_source_subdirectory_symlink(tmp_path):
    verifier, package, source = make_delivery(tmp_path)
    with pytest.raises(ValueError, match="UNSAFE_RELATIVE_PATH"):
        verifier.read_file(source, "ops/../../external.py")
    (source / "ops/owned.py").unlink()
    (source / "ops").rmdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "owned.py").write_bytes(b"old\n")
    (source / "ops").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="SYMLINK_REJECTED"):
        verifier.verify(package, profile="worker", source_root=source, against="before")


def test_frozen_protected_files_match_the_r3_source_identities():
    expected = {
        "apps/api/v35_api/app.py": "5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5",
        "apps/api/v35_api/preselection_router.py": "718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae",
        "apps/api/v35_api/preselection_service.py": "cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044",
        "ops/run_v35_macos_scheduler_daemon.py": "19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec",
    }
    for path, wanted in expected.items():
        assert hashlib.sha256((APP_ROOT / path).read_bytes()).hexdigest() == wanted
