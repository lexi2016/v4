"""Regressions for flat legacy and nested Stage v2 release identities.

The candidate round-trip replaces only package-availability probing. Git,
plist/JSON, inventories, filesystem copying, hashes and the builder are real.
No launchd, data-root access, business collector or service reload is performed.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from ops import build_release_candidate as builder
from ops import build_release_candidate_stage as stage
from ops import stage_service_overlay_contract as contract

GOLDEN = Path(__file__).parent / "fixtures" / "stage_active_manifest_v2.json"
GOLDEN_SHA = "baf65528b367e139bd6f2a4db6d6ab41ee1fb524593028795e2b61fa6221e5b3"


def _write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _fixture(tmp_path, layout="nested"):
    root = tmp_path / "active-v2"
    app = root / "app"
    (app / "ops").mkdir(parents=True)
    (app / "upstreams/v3_shared_data").mkdir(parents=True)
    (app / "ops/run_stage_center_nodes.py").write_text("# synthetic entry\n")
    (app / "upstreams/v3_shared_data/readme.txt").write_text("synthetic package\n")
    config = {
        "preselection_source_root": "/synthetic-v35/data",
        "candidate_acquisition_root": "/synthetic-v4/data",
        "release_id": "active-v2",
        "python_path": sys.executable,
        "shared_data_root": str(app / "upstreams/v3_shared_data"),
        "node_calendar_wait_max_seconds": 5,
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": {k: False for k in ("production_allowed", "buy_gate_updated", "orders_sent")},
    }
    _write_json(app / "stage_center_tick_config.json", config)
    identity = {"app_root": str(app), "release_root": str(root), "release_id": "active-v2"}
    entries = builder.inventory_tree(app)
    manifest = {
        "application_inventory": {"entries": entries, "aggregate_sha256": builder.inventory_digest(entries)},
    }
    if layout == "flat":
        manifest.update(identity)
        manifest["schema_version"] = "fixture.active.release.v1"
    else:
        manifest["schema_version"] = "v4.stage_service_candidate.v2"
        manifest["candidate"] = {"app_root": str(app), "root": str(root), "release_id": "active-v2"}
        if layout == "both":
            manifest.update(identity)
    path = root / "release-manifest.json"
    _write_json(path, manifest)
    env = {
        "V35_RELEASE_ID": "active-v2",
        "V35_RELEASE_MANIFEST_PATH": str(path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "NODE_CALENDAR_WAIT_MAX_SECONDS": "5",
        "NODE_MAX_ATTEMPTS": "3",
        "NODE_RETRY_BACKOFF_SECONDS": "60",
    }
    plist = tmp_path / "stage.plist"
    plist.write_bytes(plistlib.dumps({
        "Label": "com.lexi.stage-center.scheduler",
        "ProgramArguments": [sys.executable, "-B", str(app / "ops/run_stage_center_nodes.py"),
                             "--config", str(app / "stage_center_tick_config.json")],
        "EnvironmentVariables": env, "WorkingDirectory": str(app),
    }))
    return root, app, path, plist, manifest, identity


def _sync_manifest(path, plist, manifest):
    _write_json(path, manifest)
    payload = plistlib.loads(plist.read_bytes())
    payload["EnvironmentVariables"]["V35_RELEASE_MANIFEST_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    plist.write_bytes(plistlib.dumps(payload))


@pytest.mark.parametrize("layout", ["flat", "nested", "both"])
def test_active_release_accepts_matching_identity_without_rewriting(tmp_path, layout):
    root, app, path, plist, manifest, identity = _fixture(tmp_path, layout)
    before = path.read_bytes()
    result = stage._active_stage_release(plist)
    assert result["identity"] == identity
    assert result["manifest"] == manifest
    assert result["manifest_sha256"] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before
    assert result["inventory"] == builder.inventory_tree(app)


def test_original_uploaded_v2_manifest_identity_and_inventory_are_read_only():
    raw = GOLDEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == GOLDEN_SHA
    original = json.loads(raw)
    snapshot = deepcopy(original)
    candidate = original["candidate"]
    identity = contract._active_stage_manifest_identity(
        original, app_root=Path(candidate["app_root"]), release_root=Path(candidate["root"])
    )
    assert identity == {"app_root": candidate["app_root"], "release_root": candidate["root"],
                        "release_id": "20260925-hk-observation-stage-r4"}
    stored = original["application_inventory"]
    assert len(stored["entries"]) == 795
    assert builder.inventory_digest(stored["entries"]) == stored["aggregate_sha256"]
    assert original == snapshot and GOLDEN.read_bytes() == raw


@pytest.mark.parametrize("field", ["app_root", "release_root", "release_id"])
def test_conflicting_flat_and_nested_identity_is_rejected(tmp_path, field):
    root, app, path, plist, manifest, _ = _fixture(tmp_path, "both")
    manifest[field] += "-conflict"
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError, match="identity conflict"):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("layout,field", [("flat", x) for x in ("app_root", "release_root", "release_id")]
                         + [("nested", x) for x in ("app_root", "root", "release_id")])
def test_missing_required_identity_cannot_be_derived_from_other_objects(tmp_path, layout, field):
    root, app, path, plist, manifest, _ = _fixture(tmp_path, layout)
    holder = manifest if layout == "flat" else manifest["candidate"]
    del holder[field]
    # Source integration_base is a *different* baseline, never a fallback.
    manifest["source"] = {"integration_base": {"app_root": str(app), "release_root": str(root),
                                               "release_id": "active-v2"}}
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("bad", [None, "", " ", 123, False, [], {}])
def test_invalid_identity_value_rejected(tmp_path, bad):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    manifest["candidate"]["release_id"] = bad
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("field,bad", [("app_root", "relative/app"), ("root", "relative/root"),
                                      ("app_root", "/other/app"), ("root", "/other")])
def test_wrong_or_relative_path_identity_rejected(tmp_path, field, bad):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    manifest["candidate"][field] = bad
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("bad", [None, [], "not-an-object"])
def test_malformed_v2_candidate_never_falls_back_to_flat(tmp_path, bad):
    root, app, path, plist, manifest, _ = _fixture(tmp_path, "both")
    manifest["candidate"] = bad
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


def test_v2_requires_its_own_complete_candidate_identity(tmp_path):
    root, app, path, plist, manifest, _ = _fixture(tmp_path, "both")
    del manifest["candidate"]["root"]
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


def test_unknown_nested_schema_not_silently_accepted(tmp_path):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    manifest["schema_version"] = "v4.stage_service_candidate.v999"
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("field,bad", [("V35_RELEASE_ID", "other"),
                                     ("V35_RELEASE_MANIFEST_PATH", "/other/release-manifest.json"),
                                     ("V35_RELEASE_MANIFEST_SHA256", "0" * 64)])
def test_declared_service_identity_must_match(tmp_path, field, bad):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    payload = plistlib.loads(plist.read_bytes())
    payload["EnvironmentVariables"][field] = bad
    plist.write_bytes(plistlib.dumps(payload))
    with pytest.raises(ValueError, match="binding mismatch"):
        stage._active_stage_release(plist)


def test_legacy_absent_environment_binding_remains_supported(tmp_path):
    root, app, path, plist, manifest, identity = _fixture(tmp_path, "flat")
    payload = plistlib.loads(plist.read_bytes())
    for key in list(payload["EnvironmentVariables"]):
        if key.startswith("V35_RELEASE_"):
            del payload["EnvironmentVariables"][key]
    plist.write_bytes(plistlib.dumps(payload))
    assert stage._active_stage_release(plist)["identity"] == identity


def test_config_release_identity_conflict_rejected(tmp_path):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    cfgpath = app / "stage_center_tick_config.json"
    cfg = json.loads(cfgpath.read_text()); cfg["release_id"] = "other"
    _write_json(cfgpath, cfg)
    entries = builder.inventory_tree(app)
    manifest["application_inventory"] = {"entries": entries, "aggregate_sha256": builder.inventory_digest(entries)}
    _sync_manifest(path, plist, manifest)
    with pytest.raises(ValueError, match="binding mismatch"):
        stage._active_stage_release(plist)


@pytest.mark.parametrize("mutation", ["digest", "missing", "bytes", "extra", "removed", "mode"])
def test_original_inventory_checks_are_preserved(tmp_path, mutation):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    if mutation == "digest":
        manifest["application_inventory"]["aggregate_sha256"] = "0" * 64
        _sync_manifest(path, plist, manifest)
    elif mutation == "missing":
        del manifest["application_inventory"]
        _sync_manifest(path, plist, manifest)
    elif mutation == "bytes":
        (app / "upstreams/v3_shared_data/readme.txt").write_text("tampered\n")
    elif mutation == "extra":
        (app / "extra.py").write_text("pass\n")
    elif mutation == "removed":
        (app / "upstreams/v3_shared_data/readme.txt").unlink()
    else:
        (app / "upstreams/v3_shared_data/readme.txt").chmod(0o600)
    with pytest.raises(ValueError, match="inventory"):
        stage._active_stage_release(plist)


def test_source_root_contract_not_bypassed(tmp_path):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    cfgpath = app / "stage_center_tick_config.json"
    cfg = json.loads(cfgpath.read_text()); del cfg["preselection_source_root"]
    _write_json(cfgpath, cfg)
    with pytest.raises(ValueError, match="preselection_source_root"):
        stage._active_stage_release(plist)


def test_manifest_binding_failure_precedes_candidate_creation(tmp_path):
    root, app, path, plist, manifest, _ = _fixture(tmp_path, "flat")
    manifest["release_id"] = "contradicts-service"
    _sync_manifest(path, plist, manifest)
    source = tmp_path / "source"; source.mkdir()
    out = tmp_path / "new-candidate"
    with pytest.raises(ValueError, match="binding mismatch"):
        stage.build_stage_service_candidate(source_root=source, candidate_root=out,
            stage_plist_path=plist, release_id="new", formal_release_root=tmp_path / "formal",
            overlay_paths=[])
    assert not out.exists()
    assert not (tmp_path / "new-candidate-stage-build-receipt.json").exists()


def test_two_successive_offline_builds_preserve_baseline_release_id(tmp_path, monkeypatch):
    root, app, path, plist, manifest, _ = _fixture(tmp_path)
    source = tmp_path / "source"; source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
    monkeypatch.setattr(stage, "_probe_stage_runtime", lambda python: {
        "status": "OBSERVED_RESOLVED", "python": str(python),
        "fixture_only": "SDK availability is outside this manifest-compatibility test"})
    baseline = path.read_bytes()
    first = stage.build_stage_service_candidate(source_root=source, candidate_root=tmp_path / "new-1",
        stage_plist_path=plist, runtime_python=Path(sys.executable), release_id="new-1",
        formal_release_root=tmp_path / "formal", overlay_paths=[])
    first_manifest = json.loads(Path(first["manifest_path"]).read_text())
    assert first_manifest["source"]["integration_base"]["release_id"] == "active-v2"
    assert first_manifest["source"]["stage_overlay"]["active_release_id"] == "active-v2"
    first_plist = Path(first["service_binding"]["path"])
    accepted = stage._active_stage_release(first_plist)
    assert accepted["identity"]["release_id"] == "new-1"
    second = stage.build_stage_service_candidate(source_root=source, candidate_root=tmp_path / "new-2",
        stage_plist_path=first_plist, runtime_python=Path(sys.executable), release_id="new-2",
        formal_release_root=tmp_path / "formal", overlay_paths=[])
    second_manifest = json.loads(Path(second["manifest_path"]).read_text())
    assert second_manifest["source"]["integration_base"]["release_id"] == "new-1"
    assert second_manifest["source"]["stage_overlay"]["active_release_id"] == "new-1"
    assert path.read_bytes() == baseline
    assert first["activation_status"] == second["activation_status"] == "NOT_ACTIVATED"
    assert first["service_binding"]["launchctl_called"] is False
    cfg = json.loads((tmp_path / "new-2/app/stage_center_tick_config.json").read_text())
    assert cfg["preselection_source_root"] == "/synthetic-v35/data"
    assert cfg["candidate_acquisition_root"] == "/synthetic-v4/data"
