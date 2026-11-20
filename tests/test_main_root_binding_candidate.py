from __future__ import annotations

import hashlib
import json
import plistlib
import shutil
from pathlib import Path

import pytest

import ops.prepare_main_root_binding_candidate as main_binding
from ops.api_release_integration import inventory_digest, inventory_tree
from ops.prepare_main_root_binding_candidate import (
    CandidateError,
    REVIEW_SCHEMA,
    _canonical_sha256,
    _json_bytes,
    prepare_candidate,
    rollback_candidate_sandbox,
    validate_candidate_payload,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def _copy_app(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def _make_release(root: Path, source_pin_path: Path) -> dict[str, Path]:
    app = root / "app"
    (app / "ops").mkdir(parents=True)
    _write(app / "ops/launch_v4_macos_scheduler.sh", b"#!/bin/bash\nexit 0\n", 0o755)
    _write(app / "ops/entry.py", b"OWNER = 'main'\n")

    source_pin_path.parent.mkdir(parents=True, exist_ok=True)
    if not source_pin_path.exists():
        _write(source_pin_path, b'{"source":"pinned"}\n')
    source_hash = _sha(source_pin_path.read_bytes())
    pins = {
        "schema": "v4_research_managed_pin_inventory_v1",
        "status": "COMPLETE_REVIEWED",
        "expected_main_app_root": str(app),
        "consumer_scopes": {
            "main": "PINNED",
            "stage": "PINNED",
            "api": "PINNED",
        },
        "source_bindings": [{"path": str(source_pin_path), "sha256": source_hash}],
        "pins": [{"kind": "managed_path", "path": str(root / "data"), "reason": "fixture"}],
        "limits": ["preserve"],
    }
    pins_raw = _json_bytes(pins)
    manifest_path = root / "release-manifest.json"
    policy_path = root / "control/policy.json"
    pins_path = root / "control/managed-pins.json"
    plist_path = root / "launchd.plist"
    entries = inventory_tree(app)
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "release_id": root.name,
        "app_root": str(app),
        "candidate_status": "READY_FOR_REVIEW",
        "deployment_status": "CANNOT_CONFIRM",
        "activation_status": "NOT_ACTIVATED",
        "app_files": [
            {"path": row["path"], "sha256": row["sha256"], "size": row["size"]}
            for row in entries
        ],
        "application_inventory": {
            "entry_count": len(entries),
            "aggregate_sha256": inventory_digest(entries),
            "entries": entries,
        },
        "role_release_candidate": {
            "candidate_root": str(root),
            "app_root": str(app),
            "release_id": "preserved-source-provenance",
        },
    }
    _write(manifest_path, _json_bytes(manifest))
    policy = {
        "schema": "v4.research_storage_policy.v1",
        "managed_pin_inventory": {
            "path": str(pins_path),
            "sha256": _sha(pins_raw),
        },
        "data_root": str(root.parent / "data"),
        "run_root": str(root.parent / "runs"),
        "pointers": {"selector": str(root.parent / "data/selector.txt")},
        "formal_roots": {"selector": str(root.parent / "data/formal")},
        "reserve_bytes": 47_824 * 1024**3,
        "max_managed_bytes": 1_000_000_000_000,
        "max_quarantine_bytes": 500_000_000_000,
        "auto_gc_enabled": False,
        "dry_run": True,
        "governance": {"enabled": True, "pool_id": "fixture", "registry_root": str(root.parent / "registry")},
    }
    _write(policy_path, _json_bytes(policy))
    env = {
        "V4_APP_ROOT": str(app),
        "V4_RELEASE_ID": root.name,
        "V4_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V4_RELEASE_MANIFEST_SHA256": _sha(manifest_path.read_bytes()),
        "V4_RESEARCH_RETENTION_POLICY": str(policy_path),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": _sha(policy_path.read_bytes()),
        "V4_DATA_ROOT": str(root.parent / "data"),
        "production_allowed": "false",
        "buy_gate_updated": "false",
        "orders_sent": "false",
    }
    plist = {
        "Label": "com.lexi.v4.scheduler",
        "ProgramArguments": ["/bin/bash", str(app / "ops/launch_v4_macos_scheduler.sh")],
        "WorkingDirectory": str(app),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
    }
    _write(plist_path, plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))
    _write(pins_path, pins_raw)
    return {
        "root": root,
        "app": app,
        "manifest": manifest_path,
        "policy": policy_path,
        "pins": pins_path,
        "plist": plist_path,
        "source_pin": source_pin_path,
    }


def _input_sha(paths: dict[str, Path]) -> dict[str, str]:
    return {
        key: _sha(path.read_bytes())
        for key, path in paths.items()
        if key in {"manifest", "policy", "pins", "plist", "source_pin"}
    }


def _stage_plist(label: str, argument: str) -> bytes:
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/bash", argument],
        "WorkingDirectory": "/tmp/stage-fixture",
    }, fmt=plistlib.FMT_XML, sort_keys=True)


def _rebind_source_pin(old: dict[str, Path], source_path: Path, raw: bytes) -> None:
    _write(source_path, raw)
    pins = json.loads(old["pins"].read_bytes())
    pins["source_bindings"] = [{"path": str(source_path), "sha256": _sha(raw)}]
    pins_raw = _json_bytes(pins)
    _write(old["pins"], pins_raw)

    policy = json.loads(old["policy"].read_bytes())
    policy["managed_pin_inventory"]["sha256"] = _sha(pins_raw)
    _write(old["policy"], _json_bytes(policy))

    plist = plistlib.loads(old["plist"].read_bytes())
    plist["EnvironmentVariables"]["V4_RESEARCH_RETENTION_POLICY_SHA256"] = _sha(
        old["policy"].read_bytes()
    )
    _write(old["plist"], plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))


def _review_doc(pins: dict, replacements: list[dict]) -> dict:
    return {
        "schema_version": REVIEW_SCHEMA,
        "status": "PASS_SCOPE_PRESERVED",
        "consumer_scopes_sha256": _canonical_sha256(pins["consumer_scopes"]),
        "replacements": replacements,
    }


def _copy_release_for_target(old: dict[str, Path], new_root: Path) -> dict[str, Path]:
    app = _copy_app(old["app"], new_root / "app")
    return {**old, "root": new_root, "app": app}


def _prepare(old: dict[str, Path], target: dict[str, Path], output: Path,
             review: Path | None = None) -> dict:
    return prepare_candidate(
        source_app_root=target["app"],
        target_release_root=target["root"],
        manifest_path=old["manifest"],
        policy_path=old["policy"],
        pins_path=old["pins"],
        plist_path=old["plist"],
        output_dir=output,
        review_path=review,
    )


def test_t01_old_main_with_matching_policy_and_inventory_passes(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)

    result = validate_candidate_payload(
        config_dir=old["root"], app_root=old["app"], release_root=old["root"],
        require_manifest_storage_binding=False,
    )

    assert result["status"] == "PASS_MAIN_ROOT_BINDING_CHAIN"


def test_t02_new_main_with_old_inventory_fails_closed_before_owner(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target_root = tmp_path / "new-release"
    target = _copy_release_for_target(old, target_root)
    (target_root / "control").mkdir()
    shutil.copy2(old["policy"], target_root / "control/policy.json")
    shutil.copy2(old["pins"], target_root / "control/managed-pins.json")

    manifest = json.loads(old["manifest"].read_bytes())
    manifest["app_root"] = str(target["app"])
    manifest["release_id"] = target_root.name
    manifest["role_release_candidate"]["candidate_root"] = str(target_root)
    manifest["role_release_candidate"]["app_root"] = str(target["app"])
    manifest["main_storage_binding"] = {
        "schema_version": "v4.main_storage_binding.v1",
        "app_root": str(target["app"]),
        "policy_path": str(target_root / "control/policy.json"),
        "policy_sha256": _sha((target_root / "control/policy.json").read_bytes()),
        "managed_pin_inventory_path": str(target_root / "control/managed-pins.json"),
        "managed_pin_inventory_sha256": _sha((target_root / "control/managed-pins.json").read_bytes()),
    }
    _write(target_root / "release-manifest.json", _json_bytes(manifest))

    plist = plistlib.loads(old["plist"].read_bytes())
    plist["WorkingDirectory"] = str(target["app"])
    plist["ProgramArguments"][1] = str(target["app"] / "ops/launch_v4_macos_scheduler.sh")
    env = plist["EnvironmentVariables"]
    env["V4_APP_ROOT"] = str(target["app"])
    env["V4_RELEASE_ID"] = target_root.name
    env["V4_RELEASE_MANIFEST_PATH"] = str(target_root / "release-manifest.json")
    env["V4_RELEASE_MANIFEST_SHA256"] = _sha((target_root / "release-manifest.json").read_bytes())
    env["V4_RESEARCH_RETENTION_POLICY"] = str(target_root / "control/policy.json")
    _write(target_root / "launchd.plist", plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))

    owner_started: list[bool] = []
    with pytest.raises(CandidateError, match="MAIN_APP_ROOT_BINDING_FAILED"):
        validate_candidate_payload(
            config_dir=target_root, app_root=target["app"], release_root=target_root,
        )
        owner_started.append(True)
    assert owner_started == []


def test_t03_candidate_chain_compiles_with_exact_hashes_and_preserved_policy(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    before = _input_sha(old)
    output = tmp_path / "candidate-bundle"
    old_policy = json.loads(old["policy"].read_bytes())
    old_pins = json.loads(old["pins"].read_bytes())

    receipt = _prepare(old, target, output)
    verified = validate_candidate_payload(
        config_dir=output / "candidate",
        app_root=target["app"],
        release_root=target["root"],
    )
    candidate_policy = json.loads((output / "candidate/control/policy.json").read_bytes())
    candidate_pins = json.loads((output / "candidate/control/managed-pins.json").read_bytes())

    assert receipt["status"] == "READY_FOR_REVIEW"
    assert verified["status"] == "PASS_MAIN_ROOT_BINDING_CHAIN"
    assert candidate_policy["managed_pin_inventory"]["sha256"] == _sha(
        (output / "candidate/control/managed-pins.json").read_bytes()
    )
    assert candidate_policy["managed_pin_inventory"]["path"] == str(
        target["root"] / "control/managed-pins.json"
    )
    assert candidate_pins["expected_main_app_root"] == str(target["app"])
    manifest = json.loads((output / "candidate/release-manifest.json").read_bytes())
    assert manifest["main_storage_binding"]["policy_sha256"] == _sha(
        (output / "candidate/control/policy.json").read_bytes()
    )
    assert manifest["main_storage_binding"]["managed_pin_inventory_sha256"] == _sha(
        (output / "candidate/control/managed-pins.json").read_bytes()
    )
    assert candidate_policy["reserve_bytes"] == old_policy["reserve_bytes"]
    assert {k: v for k, v in candidate_policy.items() if k != "managed_pin_inventory"} == {
        k: v for k, v in old_policy.items() if k != "managed_pin_inventory"
    }
    assert {k: v for k, v in candidate_pins.items()
            if k not in {"expected_main_app_root", "source_bindings"}} == {
        k: v for k, v in old_pins.items()
        if k not in {"expected_main_app_root", "source_bindings"}
    }
    assert _input_sha(old) == before
    assert not (target["root"] / "control").exists()
    assert receipt["deployment_status"] == "NOT_RUN"


def test_unreviewed_source_change_blocks_candidate_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    source.write_bytes(b'{"source":"changed"}\n')
    output = tmp_path / "candidate-bundle"

    with pytest.raises(CandidateError, match="SOURCE_BINDING_DRIFT_UNREVIEWED"):
        _prepare(old, target, output)
    assert not output.exists()


def test_reviewed_real_source_change_updates_only_exact_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "com.lexi.stage-center.scheduler.plist"
    old = _make_release(tmp_path / "old-release", source)
    old_raw = _stage_plist("com.lexi.stage-center.scheduler", "/old/stage/runner.sh")
    new_raw = _stage_plist("com.lexi.stage-center.scheduler", "/new/stage/runner.sh")
    _rebind_source_pin(old, source, old_raw)
    old_preimage = tmp_path / "private-preimages/stage-scheduler.plist"
    _write(old_preimage, old_raw)
    _write(source, new_raw)
    monkeypatch.setattr(main_binding, "REVIEWABLE_PIN_PATHS", {
        str(source): {
            "scope_id": "stage",
            "launchd_label": "com.lexi.stage-center.scheduler",
        },
    })
    target = _copy_release_for_target(old, tmp_path / "new-release")
    old_sha = _sha(old_raw)
    new_sha = _sha(new_raw)
    pins = json.loads(old["pins"].read_bytes())
    review = _review_doc(pins, [{
            "old_path": str(source),
            "old_sha256": old_sha,
            "old_preimage_path": str(old_preimage),
            "new_path": str(source),
            "new_sha256": new_sha,
            "scope_id": "stage",
            "scope_preserved": True,
        }])
    review_path = tmp_path / "review.json"
    _write(review_path, _json_bytes(review))
    receipt = _prepare(old, target, tmp_path / "candidate-bundle", review_path)
    candidate_pins = json.loads(
        (tmp_path / "candidate-bundle/candidate/control/managed-pins.json").read_bytes()
    )
    row = candidate_pins["source_bindings"][0]

    assert row == {"path": str(source), "sha256": new_sha}
    assert receipt["source_binding_changes"][0]["old_sha256"] == old_sha
    assert receipt["source_binding_changes"][0]["new_sha256"] == new_sha
    assert candidate_pins["consumer_scopes"] == pins["consumer_scopes"]
    assert validate_candidate_payload(
        config_dir=tmp_path / "candidate-bundle/candidate",
        app_root=target["app"], release_root=target["root"],
    )["status"] == "PASS_MAIN_ROOT_BINDING_CHAIN"


def test_arbitrary_source_and_wrong_scope_reviews_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "arbitrary-owner-source.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    new_bytes = b'{"source":"changed"}\n'
    _write(source, new_bytes)
    pins = json.loads(old["pins"].read_bytes())
    old_preimage = tmp_path / "private-preimages/arbitrary-source.json"
    _write(old_preimage, b'{"source":"pinned"}\n')
    review = _review_doc(pins, [{
        "old_path": str(source),
        "old_sha256": _sha(old_preimage.read_bytes()),
        "old_preimage_path": str(old_preimage),
        "new_path": str(source),
        "new_sha256": _sha(new_bytes),
        "scope_id": "stage",
        "scope_preserved": True,
    }])
    review_path = tmp_path / "arbitrary-review.json"
    _write(review_path, _json_bytes(review))

    with pytest.raises(CandidateError, match="SOURCE_BINDING_REVIEW_PATH_NOT_ALLOWLISTED"):
        _prepare(old, target, tmp_path / "candidate-bundle", review_path)

    stage = tmp_path / "com.lexi.stage-center.scheduler.plist"
    old_stage = _stage_plist("com.lexi.stage-center.scheduler", "/old/stage/runner.sh")
    new_stage = _stage_plist("com.lexi.stage-center.scheduler", "/new/stage/runner.sh")
    _rebind_source_pin(old, stage, old_stage)
    stage_preimage = tmp_path / "private-preimages/stage-old.plist"
    _write(stage_preimage, old_stage)
    _write(stage, new_stage)
    monkeypatch.setattr(main_binding, "REVIEWABLE_PIN_PATHS", {
        str(stage): {
            "scope_id": "stage",
            "launchd_label": "com.lexi.stage-center.scheduler",
        },
    })
    pins = json.loads(old["pins"].read_bytes())
    wrong_scope = _review_doc(pins, [{
        "old_path": str(stage),
        "old_sha256": _sha(old_stage),
        "old_preimage_path": str(stage_preimage),
        "new_path": str(stage),
        "new_sha256": _sha(new_stage),
        "scope_id": "api",
        "scope_preserved": True,
    }])
    wrong_scope_path = tmp_path / "wrong-scope-review.json"
    _write(wrong_scope_path, _json_bytes(wrong_scope))
    with pytest.raises(CandidateError, match="SOURCE_BINDING_REVIEW_SCOPE_MISMATCH"):
        _prepare(old, target, tmp_path / "wrong-scope-candidate", wrong_scope_path)


def test_reviewed_pin_cannot_be_retargeted_and_old_preimage_must_be_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "com.lexi.v4.api.plist"
    old = _make_release(tmp_path / "old-release", source)
    old_raw = _stage_plist("com.lexi.v4.api", "/old/api/runner.py")
    new_raw = _stage_plist("com.lexi.v4.api", "/new/api/runner.py")
    _rebind_source_pin(old, source, old_raw)
    old_preimage = tmp_path / "private-preimages/api-old.plist"
    _write(old_preimage, old_raw)
    _write(source, new_raw)
    monkeypatch.setattr(main_binding, "REVIEWABLE_PIN_PATHS", {
        str(source): {"scope_id": "api", "launchd_label": "com.lexi.v4.api"},
    })
    target = _copy_release_for_target(old, tmp_path / "new-release")
    pins = json.loads(old["pins"].read_bytes())
    retarget = _review_doc(pins, [{
        "old_path": str(source),
        "old_sha256": _sha(old_raw),
        "old_preimage_path": str(old_preimage),
        "new_path": str(tmp_path / "other-api.plist"),
        "new_sha256": _sha(new_raw),
        "scope_id": "api",
        "scope_preserved": True,
    }])
    review_path = tmp_path / "retarget-review.json"
    _write(review_path, _json_bytes(retarget))
    with pytest.raises(CandidateError, match="SOURCE_BINDING_REVIEW_RETARGET_PROHIBITED"):
        _prepare(old, target, tmp_path / "retarget-candidate", review_path)

    _rebind_source_pin(old, source, old_raw)
    no_change_pins = json.loads(old["pins"].read_bytes())
    same_path_preimage = _review_doc(no_change_pins, [{
        "old_path": str(source),
        "old_sha256": _sha(old_raw),
        "old_preimage_path": str(source),
        "new_path": str(source),
        "new_sha256": _sha(old_raw),
        "scope_id": "api",
        "scope_preserved": True,
    }])
    same_path_review = tmp_path / "same-path-preimage-review.json"
    _write(same_path_review, _json_bytes(same_path_preimage))
    with pytest.raises(CandidateError, match="SOURCE_BINDING_OLD_PREIMAGE_NOT_SEPARATE"):
        _prepare(old, target, tmp_path / "same-path-preimage-candidate", same_path_review)


def test_candidate_and_rollback_paths_are_fenced_to_real_system_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    safe_temp = tmp_path / "allowed-system-temp"
    safe_temp.mkdir()
    protected = tmp_path / "protected-release-prefix"
    protected.mkdir()
    monkeypatch.setattr(main_binding, "_allowed_temp_roots", lambda: (safe_temp.resolve(),))

    outside_output = protected / "candidate-bundle"
    with pytest.raises(CandidateError, match="CANDIDATE_OUTPUT_OUTSIDE_SYSTEM_TEMP_ROOT"):
        _prepare(old, target, outside_output)
    assert not outside_output.exists()

    outside_bundle = protected / "existing-bundle"
    outside_bundle.mkdir()
    with pytest.raises(CandidateError, match="CANDIDATE_OUTPUT_OUTSIDE_SYSTEM_TEMP_ROOT"):
        rollback_candidate_sandbox(outside_bundle)


def test_candidate_output_symlink_cannot_escape_allowed_temp_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    safe_temp = tmp_path / "allowed-system-temp"
    safe_temp.mkdir()
    protected = tmp_path / "protected-prefix"
    protected.mkdir()
    (safe_temp / "escape").symlink_to(protected, target_is_directory=True)
    monkeypatch.setattr(main_binding, "_allowed_temp_roots", lambda: (safe_temp.resolve(),))

    escaped_output = safe_temp / "escape/candidate-bundle"
    with pytest.raises(CandidateError, match="CANDIDATE_OUTPUT_OUTSIDE_SYSTEM_TEMP_ROOT"):
        _prepare(old, target, escaped_output)
    assert not (protected / "candidate-bundle").exists()


def test_t15_exact_rollback_in_private_sandbox_and_no_input_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    before = _input_sha(old)
    output = tmp_path / "candidate-bundle"
    _prepare(old, target, output)

    sandbox = output / "rollback-sandbox"
    sandbox.mkdir(mode=0o700)
    for role, relative in {
        "manifest": Path("release-manifest.json"),
        "policy": Path("control/policy.json"),
        "pins": Path("control/managed-pins.json"),
        "plist": Path("launchd.plist"),
    }.items():
        target_path = sandbox / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path = output / "candidate" / relative
        shutil.copyfile(staged_path, target_path)
        target_path.chmod(0o600)

    result = rollback_candidate_sandbox(output)
    for role, relative in {
        "manifest": Path("release-manifest.json"),
        "policy": Path("control/policy.json"),
        "pins": Path("control/managed-pins.json"),
        "plist": Path("launchd.plist"),
    }.items():
        restored = sandbox / relative
        assert restored.read_bytes() == old[role].read_bytes()
        assert restored.stat().st_mode & 0o777 == old[role].stat().st_mode & 0o777
    assert result["status"] == "PASS_EXACT_SANDBOX_ROLLBACK"
    assert result["live_files_touched"] is False
    assert _input_sha(old) == before


def test_rollback_cas_rejects_unexpected_candidate_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    output = tmp_path / "candidate-bundle"
    _prepare(old, target, output)
    sandbox = output / "rollback-sandbox"
    sandbox.mkdir(mode=0o700)
    for relative in (
        Path("release-manifest.json"), Path("control/policy.json"),
        Path("control/managed-pins.json"), Path("launchd.plist"),
    ):
        target_path = sandbox / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output / "candidate" / relative, target_path)
        target_path.chmod(0o600)
    (sandbox / "control/policy.json").write_bytes(b"unexpected\n")

    with pytest.raises(CandidateError, match="ROLLBACK_CAS_MISMATCH"):
        rollback_candidate_sandbox(output)


def test_manifest_policy_pin_cross_binding_rejects_tamper_even_with_fresh_plist_sha(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-pin.json"
    old = _make_release(tmp_path / "old-release", source)
    target = _copy_release_for_target(old, tmp_path / "new-release")
    output = tmp_path / "candidate-bundle"
    _prepare(old, target, output)
    candidate = output / "candidate"

    manifest_path = candidate / "release-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["main_storage_binding"]["policy_sha256"] = "0" * 64
    _write(manifest_path, _json_bytes(manifest), mode=0o600)
    plist_path = candidate / "launchd.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    plist["EnvironmentVariables"]["V4_RELEASE_MANIFEST_SHA256"] = _sha(manifest_path.read_bytes())
    _write(plist_path, plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True), mode=0o600)

    with pytest.raises(CandidateError, match="MANIFEST_STORAGE_BINDING_FAILED"):
        validate_candidate_payload(
            config_dir=candidate,
            app_root=target["app"],
            release_root=target["root"],
        )
