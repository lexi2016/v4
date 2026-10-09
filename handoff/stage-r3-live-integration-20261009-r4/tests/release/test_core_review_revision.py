"""Focused regressions for reviewed additions and directory preservation.

Fixtures use real local filesystem operations and the already reviewed v2
receipt constructor. They do not start services or access business data.
"""
from __future__ import annotations

import json
from pathlib import Path
import plistlib
import stat

import pytest

from ops import api_release_integration as integration
from test_api_release_v2_contract import receipt_fixture


ADDITION = "apps/api/v35_api/preselection_service.py"
MODIFICATION = "apps/api/v35_api/app.py"


def _seal(kwargs: dict, details: dict) -> Path:
    root = kwargs["candidate_root"]
    entries = integration.inventory_tree(root / "app")
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "activation_status": "NOT_ACTIVATED",
        "candidate": {"root": str(root), "app_root": str(root / "app"),
                      "release_id": root.name},
        "application_inventory": {"entry_count": len(entries),
                                  "aggregate_sha256": integration.inventory_digest(entries),
                                  "entries": entries},
        "api_integration": details,
    }
    (root / "release-manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return root


def _verify(kwargs: dict):
    return integration.verify_api_release_candidate(
        candidate_root=kwargs["candidate_root"],
        active_api_plist_path=kwargs["active_api_plist_path"],
    )


def _candidate_with_empty_directory(tmp_path: Path):
    active, _, kwargs = receipt_fixture(tmp_path)
    empty = Path(active["app_root"]) / "retained/empty"
    empty.mkdir(parents=True)
    empty.chmod(0o750)
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    return active, kwargs


def test_receipt_authorizes_active_addition_without_untracked_flag(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    kwargs["explicit_untracked_paths"] = []
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    assert (kwargs["candidate_root"] / "app" / ADDITION).read_bytes() == b"VALUE = 2\n"
    assert _verify(kwargs)["status"] == "PASS"


def test_source_untracked_approval_can_cover_an_active_modification(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path)
    kwargs["explicit_untracked_paths"] = [MODIFICATION]
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    assert _verify(kwargs)["delta_paths"] == [MODIFICATION]


@pytest.mark.parametrize("flags", [[ADDITION, ADDITION], ["not-in-receipt.py"]])
def test_untracked_flags_must_be_unique_receipt_paths_before_copy(tmp_path, flags):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    kwargs["explicit_untracked_paths"] = flags
    with pytest.raises(ValueError):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


def test_source_allowlist_refuses_unapproved_receipt_file_before_copy(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    kwargs["source_path_allowlist"] = ["stable-module.py"]
    with pytest.raises(ValueError, match="SOURCE_PATH_NOT_ALLOWED"):
        integration.build_integrated_app(**kwargs)
    assert not (kwargs["candidate_root"] / "app").exists()


def test_source_allowlist_does_not_copy_unlisted_files(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    kwargs["explicit_untracked_paths"] = []
    extra = kwargs["source_root"] / "unrelated.py"
    extra.write_bytes(b"DO_NOT_COPY = True\n")
    kwargs["source_path_allowlist"] = [ADDITION, "unrelated.py"]
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    assert not (kwargs["candidate_root"] / "app/unrelated.py").exists()
    assert _verify(kwargs)["status"] == "PASS"


@pytest.mark.parametrize("relative", [".", "apps/api"])
def test_verifier_rejects_existing_directory_mode_drift(tmp_path, relative):
    active, kwargs = _candidate_with_empty_directory(tmp_path)
    before_mode = stat.S_IMODE((Path(active["app_root"]) / relative).stat().st_mode)
    (kwargs["candidate_root"] / "app" / relative).chmod(0o777 if before_mode != 0o777 else 0o755)
    with pytest.raises(ValueError):
        _verify(kwargs)


def test_verifier_rejects_removal_of_preserved_empty_directory(tmp_path):
    _, kwargs = _candidate_with_empty_directory(tmp_path)
    (kwargs["candidate_root"] / "app/retained/empty").rmdir()
    with pytest.raises(ValueError):
        _verify(kwargs)


def test_verifier_rejects_undeclared_empty_directory(tmp_path):
    _, kwargs = _candidate_with_empty_directory(tmp_path)
    (kwargs["candidate_root"] / "app/undeclared-empty").mkdir()
    with pytest.raises(ValueError):
        _verify(kwargs)


@pytest.mark.parametrize("drift", ["mode", "remove", "add"])
def test_verifier_binds_base_directories_even_if_candidate_matches_drift(tmp_path, drift):
    active, kwargs = _candidate_with_empty_directory(tmp_path)
    for app in (Path(active["app_root"]), kwargs["candidate_root"] / "app"):
        if drift == "mode":
            (app / "retained/empty").chmod(0o555)
        elif drift == "remove":
            (app / "retained/empty").rmdir()
        else:
            (app / "unrecorded-base-directory").mkdir()
    with pytest.raises(ValueError):
        _verify(kwargs)


def test_new_directories_are_only_required_ancestors_with_fixed_mode(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    for directory in (kwargs["source_root"] / "apps", kwargs["source_root"] / "apps/api",
                      kwargs["source_root"] / "apps/api/v35_api"):
        directory.chmod(0o777)
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    app = kwargs["candidate_root"] / "app"
    expected = ["apps", "apps/api", "apps/api/v35_api"]
    assert sorted(str(p.relative_to(app)) for p in app.rglob("*") if p.is_dir()) == expected
    assert all(stat.S_IMODE((app / p).stat().st_mode) == 0o755 for p in expected)
    proof = details["directory_preservation"]
    assert proof["added_paths"] == expected
    assert proof["new_directory_mode"] == "0755"
    assert _verify(kwargs)["directory_preservation"] == proof


def test_verifier_rejects_mode_change_to_a_declared_new_ancestor(tmp_path):
    _, _, kwargs = receipt_fixture(tmp_path, relative=ADDITION, addition=True)
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    (kwargs["candidate_root"] / "app/apps/api").chmod(0o777)
    with pytest.raises(ValueError):
        _verify(kwargs)


def test_readonly_base_directories_are_retained_while_new_directory_is_added(tmp_path):
    relative = "domains/manager_research/new_job.py"
    active, _, kwargs = receipt_fixture(tmp_path, relative=relative, addition=True, module="manager")
    root = Path(active["app_root"])
    (root / "domains").mkdir()
    (root / "domains").chmod(0o555)
    root.chmod(0o555)
    details = integration.build_integrated_app(**kwargs)
    _seal(kwargs, details)
    app = kwargs["candidate_root"] / "app"
    assert stat.S_IMODE(app.stat().st_mode) == 0o555
    assert stat.S_IMODE((app / "domains").stat().st_mode) == 0o555
    assert stat.S_IMODE((app / "domains/manager_research").stat().st_mode) == 0o755
    assert (app / relative).read_bytes() == b"VALUE = 2\n"
    assert _verify(kwargs)["status"] == "PASS"


def test_directory_proof_is_required_and_unknown_fields_are_rejected(tmp_path):
    _, kwargs = _candidate_with_empty_directory(tmp_path)
    path = kwargs["candidate_root"] / "release-manifest.json"
    manifest = json.loads(path.read_text())
    proof = manifest["api_integration"].pop("directory_preservation")
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    with pytest.raises(ValueError):
        _verify(kwargs)
    proof["unreviewed_override"] = True
    manifest["api_integration"]["directory_preservation"] = proof
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    with pytest.raises(ValueError):
        _verify(kwargs)


def test_a_new_active_v2_release_keeps_its_recorded_directory_identity(tmp_path):
    _, kwargs = _candidate_with_empty_directory(tmp_path)
    candidate = kwargs["candidate_root"]
    pointer = kwargs["active_api_plist_path"]
    payload = plistlib.loads(pointer.read_bytes())
    values = {
        "V35_APP_ROOT": str(candidate / "app"),
        "V35_RELEASE_ID": candidate.name,
        "V35_RELEASE_MANIFEST_PATH": str(candidate / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": integration.sha256_bytes((candidate / "release-manifest.json").read_bytes()),
    }
    payload["ProgramArguments"] = [
        key + "=" + values[key] if "=" in arg and (key := arg.split("=", 1)[0]) in values else arg
        for arg in payload["ProgramArguments"]
    ]
    pointer.write_bytes(plistlib.dumps(payload))
    (candidate / "app/retained/empty").chmod(0o777)
    with pytest.raises(ValueError):
        integration.read_active_release(pointer)
