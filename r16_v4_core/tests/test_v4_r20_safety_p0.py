"""P0 regressions observed against the r19 isolated baseline."""
from hashlib import sha256
import json
import stat

import pytest
from fastapi.testclient import TestClient

from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.runner.cli import main
from v4_core.runner.safe_archive import ManifestCoverageError, filter_safe_archive_paths, load_manifest_paths


def test_stage_details_batch_and_provenance_keep_partial_and_unverified(tmp_path):
    app = create_app(V4Config.from_env(tmp_path))
    source_ref = "sha256:" + "a" * 64
    app.state.store.upsert_stage_selections([
        {"trade_date": "2026-11-26", "stage": "STAGE_0925", "market": "A", "symbol": "000001.SZ",
         "status": "PARTIAL", "execution_ref": source_ref,
         "payload": {"owner_selection_status": "WATCH_ONLY", "natural_verified": True, "data_level": "OFFICIAL"}},
        {"trade_date": "2026-11-25", "stage": "STAGE_0925", "market": "HK", "symbol": "00001.HK"},
    ])
    with TestClient(app) as client:
        detail = client.get("/api/v4/workbench/stage?date=20261126&stage=STAGE_0925").json()
        batch = client.get("/api/v4/workbench/stage-batch?date=20261126&stages=STAGE_0925").json()
        default_opening = client.get("/api/v4/workbench/stage?date=20261126").json()

    assert batch["items"][0]["payload"] == {key: value for key, value in detail.items() if key != "backfill_run_id"}
    assert batch["stages"]["STAGE_0925"]["stage"] == detail["stage"]
    assert batch["status"] == detail["status"] == detail["stage"]["status"] == "PARTIAL"
    assert batch["natural_verified"] is detail["natural_verified"] is detail["markets"]["A"]["natural_verified"] is False
    assert detail["markets"]["A"]["data_level"] == "OBSERVATION_UNVERIFIED"
    assert detail["markets"]["HK"]["status"] == "CANNOT_CONFIRM"
    assert detail["markets"]["HK"]["selected_rows"] is None
    assert detail["selection_markets"]["A_SHARE"]["selection_manifest_receipt_verified"] is False
    assert detail["selection_markets"]["A_SHARE"]["source_evidence"] == [source_ref]
    assert detail["selection_markets"]["HK_CONNECT"]["source_evidence"] == []
    assert detail["execution_evidence"]["execution_verified"] is False
    assert detail["execution_evidence"]["natural_verified"] is False
    row = detail["rows"][0]
    assert row["status"] == "PARTIAL" and row["owner_selection_status"] == "WATCH_ONLY"
    assert row["natural_verified"] is False and row["data_level"] == "OBSERVATION_UNVERIFIED"
    assert row["readback_provenance"]["stored_execution_ref"] == source_ref
    assert row["readback_provenance"]["stored_trade_date"] == "2026-11-26"
    assert default_opening["status"] == "CANNOT_CONFIRM" and default_opening["rows"] == []


def test_scheduler_slot_records_never_prove_running_process(tmp_path):
    app = create_app(V4Config.from_env(tmp_path))
    app.state.store.record_slot_execution("2026-11-25", "slot_1_preopen_research", "slot1", "07:00", "DONE", "manual")
    app.state.store.record_slot_execution("2026-11-25", "slot_2_preopen_pool_freeze", "slot2", "09:25", "RUNNING", "old-attempt")
    with TestClient(app) as client:
        empty = client.get("/api/v4/tasks/status?date=20261126").json()
        recorded = client.get("/api/v4/tasks/status?date=20261125").json()

    for result in (empty, recorded):
        assert result["scheduler_observation"]["status"] == "CANNOT_CONFIRM"
        assert result["scheduler_observation"]["process_status"] == "CANNOT_CONFIRM"
        assert result["groups"]["active_owners"] == result["groups"]["registrations"] == []
    assert empty["scheduler_observation"]["receipt_count"] == 0
    assert recorded["scheduler_observation"]["receipt_count"] == 2
    assert recorded["scheduler_observation"]["executed_slots"] == 1


def test_serve_uses_env_and_overrides_before_starting_app(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.append((app.state.config.api_port, kwargs["port"])))
    monkeypatch.setenv("V4_API_PORT", "19420")
    assert main(["serve", "--home", str(tmp_path)]) == 0
    assert main(["serve", "--home", str(tmp_path), "--port", "19421"]) == 0
    assert seen == [(19420, 19420), (19421, 19421)]


@pytest.mark.parametrize("configured_port", [None, "8873", "0", "65536", "invalid"])
def test_serve_blocks_unsafe_implicit_port_before_any_write(tmp_path, monkeypatch, configured_port):
    def unexpected_start(*args, **kwargs):
        pytest.fail("Unsafe serve unexpectedly reached uvicorn")

    monkeypatch.setattr("uvicorn.run", unexpected_start)
    monkeypatch.delenv("V4_API_PORT", raising=False)
    if configured_port is not None:
        monkeypatch.setenv("V4_API_PORT", configured_port)
    home = tmp_path / "not-created"
    with pytest.raises(SystemExit) as error:
        main(["serve", "--home", str(home)])
    assert error.value.code == 2 and not home.exists()




def test_stage_partial_outside_first_page_and_unverified_payload_cannot_promote(tmp_path):
    app = create_app(V4Config.from_env(tmp_path))
    ref = "sha256:" + "b" * 64
    dangerous_payload = {
        "source_status": "READY", "selection_status": "READY", "display_mode": "OFFICIAL",
        "execution_evidence": {"natural_verified": True}, "production_allowed": True,
        "orders_sent": True, "buy_gate_updated": True, "RESEARCH_ONLY": False,
        "owner_selection_status": "READY", "source_path": "retained/path",
        "metadata": {"orders_sent": True, "owner_note": "retained"},
    }
    common = {"trade_date": "2026-11-26", "stage": "STAGE_0930_0935", "market": "A"}
    app.state.store.upsert_stage_selections([
        {**common, "symbol": f"{rank:06}.SZ", "rank": rank, "status": "ready", "execution_ref": ref,
         "payload": dangerous_payload}
        for rank in range(1, 51)
    ] + [
        {**common, "symbol": "000051.SZ", "rank": 51, "status": "PARTIAL"},
        {**common, "market": "HK", "symbol": "00001.HK", "rank": 52, "status": "READY"},
        {**common, "trade_date": "2026-11-25", "symbol": "000052.SZ", "status": "PARTIAL"},
        {**common, "stage": "STAGE_0925", "symbol": "000053.SZ", "status": "PARTIAL"},
    ])
    params = {"date": "20261126", "stage": common["stage"]}
    with TestClient(app) as client:
        detail = client.get("/api/v4/workbench/stage", params=params).json()
        expanded = client.get("/api/v4/workbench/stage", params={**params, "limit": 51}).json()
        hk = client.get("/api/v4/workbench/stage", params={**params, "market": "HK"}).json()
        batch = client.get("/api/v4/workbench/stage-batch",
                           params={"date": "20261126", "stages": common["stage"]}).json()
        manager = client.get("/api/v4/manager/stage-selection", params=params).json()
        center = client.get("/api/v4/stage-center/selection", params=params).json()
        opening = client.get("/api/v4/research/opening-observation",
                             params={"date": "20261126", "symbol": "000001.SZ"}).json()

    assert detail["status"] == expanded["status"] == batch["status"] == manager["status"] == center["status"] == "PARTIAL"
    assert detail["status"] == batch["stages"][common["stage"]]["status"]
    assert len(detail["rows"]) == 50 and len(expanded["rows"]) == 51
    assert detail["markets"]["A"]["status"] == "PARTIAL"
    assert detail["markets"]["HK"]["status"] == "OBSERVATION_UNVERIFIED"
    assert hk["status"] == "OBSERVATION_UNVERIFIED" and hk["markets"]["A"]["status"] == "CANNOT_CONFIRM"
    assert batch["items"][0]["payload"]["items"] == detail["items"]
    row = detail["rows"][0]
    assert opening["rows"][0] == row
    assert row["status"] == "OBSERVATION_UNVERIFIED"
    assert row["selection_status"] == row["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert row["source_status"] == "CANNOT_CONFIRM"
    assert row["owner_selection_status"] == "CANNOT_CONFIRM"
    assert row["execution_evidence"]["natural_verified"] is False
    assert row["production_allowed"] is row["orders_sent"] is row["buy_gate_updated"] is False
    assert row["RESEARCH_ONLY"] is True
    assert row["source_path"] == "retained/path"
    assert row["metadata"] == {"owner_note": "retained"}
    assert row["readback_provenance"]["stored_status"] == "ready"
    assert row["readback_provenance"]["stored_execution_ref"] == ref


def test_opening_observation_aggregates_only_requested_rows_like_stage_workbench(tmp_path):
    app = create_app(V4Config.from_env(tmp_path))
    common = {"trade_date": "2026-11-26", "stage": "STAGE_0930_0935", "market": "A"}
    app.state.store.upsert_stage_selections([
        {**common, "symbol": "000001.SZ", "status": "PARTIAL", "payload": {"natural_verified": True}},
    ])
    endpoint = "/api/v4/research/opening-observation"
    params = {"date": "20261126"}
    with TestClient(app) as client:
        workbench = client.get("/api/v4/workbench/stage", params=params).json()
        single = client.get(endpoint, params={**params, "symbol": "000001.SZ"}).json()
        app.state.store.upsert_stage_selections([{**common, "symbol": "000002.SZ", "status": "READY"}])
        mixed = client.get(endpoint, params=params).json()
        unverified = client.get(endpoint, params={**params, "symbol": "000002.SZ"}).json()
        missing = client.get(endpoint, params={**params, "symbol": "000003.SZ"}).json()

    assert single["status"] == workbench["status"] == single["rows"][0]["status"] == "PARTIAL"
    assert single["rows"] == workbench["rows"] and len(single["rows"]) == 1
    assert mixed["status"] == "PARTIAL" and len(mixed["rows"]) == 2
    assert unverified["status"] == "OBSERVATION_UNVERIFIED"
    assert missing["status"] == "CANNOT_CONFIRM" and missing["rows"] == []
    assert all(body["natural_verified"] is False for body in (single, mixed, unverified, missing))


def _complete_archive_group(tmp_path):
    roles = {}
    for role in ("api", "main", "stage"):
        app_root = tmp_path.resolve() / f"{role}-app"
        app_root.mkdir()
        live_file = app_root / f"{role}-live.py"
        live_file.write_text(role)
        info = live_file.stat()
        entries = [{
            "path": live_file.name, "kind": "file", "sha256": sha256(live_file.read_bytes()).hexdigest(),
            "size": info.st_size, "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        }]
        entries_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        (tmp_path / f"{role}-startup.json").write_text(json.dumps({
            "app_root": str(app_root),
            "application_inventory": {
                "entries": entries, "entry_count": len(entries),
                "aggregate_sha256": sha256(entries_bytes).hexdigest(),
            },
        }))
        (tmp_path / f"{role}.json").write_text(json.dumps({
            "role": role, "app_root": str(app_root), "startup_manifest": {"path": f"{role}-startup.json"},
        }))
        roles[role] = {"path": f"{role}.json"}
    group = tmp_path / "group.json"
    group.write_text(json.dumps({"activation_status": "ACTIVE", "roles": roles}))
    return group


@pytest.mark.parametrize("invalid_child", [None, "{malformed", "[]", "{}", '{"application_inventory": {}}',
                                           '{"application_inventory": {"entries": []}}',
                                           '{"role": "stage", "app_files": ["stage-live.py"]}'])
def test_incomplete_archive_manifest_never_yields_partial_paths(tmp_path, invalid_child):
    group = _complete_archive_group(tmp_path)
    child = tmp_path / "stage.json"
    if invalid_child is None:
        child.unlink()
    else:
        child.write_text(invalid_child)
    with pytest.raises(ManifestCoverageError):
        load_manifest_paths(group)
    with pytest.raises(ManifestCoverageError):
        load_manifest_paths(tmp_path / "missing.json")


@pytest.mark.parametrize("defect", ["missing_role", "shared_child", "missing_startup", "wrong_child_sha",
                                     "partial_startup", "missing_entry_proof", "wrong_entry_count", "wrong_entry_sha"])
def test_archive_rejects_incomplete_role_graph_and_bad_startup_references(tmp_path, defect):
    principal = _complete_archive_group(tmp_path)
    group = json.loads(principal.read_text())
    roles = group["roles"]
    child = tmp_path / "stage.json"
    startup = tmp_path / "stage-startup.json"
    if defect == "missing_role":
        del roles["stage"]
    elif defect == "shared_child":
        roles["stage"] = roles["main"]
    elif defect == "missing_startup":
        startup.unlink()
    elif defect == "wrong_child_sha":
        roles["stage"]["sha256"] = "a" * 64
    elif defect == "partial_startup":
        startup.write_text(json.dumps({"app_files": ["stage-live.py"]}))
    else:
        data = json.loads(startup.read_text())
        inventory = data["application_inventory"]
        if defect == "missing_entry_proof":
            del inventory["aggregate_sha256"]
        elif defect == "wrong_entry_count":
            inventory["entry_count"] += 1
        else:
            inventory["aggregate_sha256"] = "a" * 64
        startup.write_text(json.dumps(data))
    principal.write_text(json.dumps(group))
    assert child.exists()
    with pytest.raises(ManifestCoverageError):
        load_manifest_paths(principal)


@pytest.mark.parametrize("proof", [None, set(), {"known.py"}])
def test_archive_plain_path_hints_never_authorize_omitted_active_file(tmp_path, proof):
    (tmp_path / "api-live.py").write_text("active file")
    result = filter_safe_archive_paths(["api-live.py"], {"api-live.py"}, proof, repo_root=tmp_path)
    assert result["safe_to_archive"] == []
    assert result["skipped_protected_evidence"] == ["api-live.py"]


def test_single_active_looking_inventory_cannot_authorize_omitted_active_file(tmp_path):
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"activation_status": "ACTIVE", "app_files": ["known.py"]}))
    with pytest.raises(ManifestCoverageError):
        load_manifest_paths(partial)


@pytest.mark.parametrize("change", ["unlink_root", "unlink_startup", "change_equivalent_reference", "replace_startup"])
def test_archive_requires_original_unchanged_complete_graph_at_decision(tmp_path, change):
    principal = _complete_archive_group(tmp_path)
    paths = load_manifest_paths(principal)
    for name in ("candidate.py", "api-live.py"):
        (tmp_path / name).write_text(name)
    candidates = ["candidate.py", "api-live.py"]
    tracked = set(candidates)
    assert filter_safe_archive_paths(candidates, tracked, paths, repo_root=tmp_path)["safe_to_archive"] == ["candidate.py"]
    if change == "unlink_root":
        principal.unlink()
    elif change == "unlink_startup":
        (tmp_path / "api-startup.json").unlink()
    elif change == "change_equivalent_reference":
        group = json.loads(principal.read_text())
        group["roles"]["api"]["path"] = "./api.json"
        principal.write_text(json.dumps(group))
    else:
        startup = tmp_path / "api-startup.json"
        startup.write_text(startup.read_text() + " ")
    assert filter_safe_archive_paths(candidates, tracked, paths, repo_root=tmp_path)["safe_to_archive"] == []


@pytest.mark.parametrize("affected_role", ["api", "main", "stage"])
def test_self_consistent_archive_inventory_cannot_hide_existing_runtime_file(tmp_path, affected_role):
    group = _complete_archive_group(tmp_path)
    app_root = tmp_path / f"{affected_role}-app"
    (app_root / "omitted.py").write_text("not present in the valid count and aggregate")
    with pytest.raises(ManifestCoverageError):
        load_manifest_paths(group)


@pytest.mark.parametrize("change", ["file_added", "file_bytes_changed", "wrong_app_root"])
def test_archive_rechecks_runtime_inventory_before_allowing_candidate(tmp_path, change):
    group = _complete_archive_group(tmp_path)
    active = load_manifest_paths(group)
    candidate = tmp_path / "candidate.py"
    candidate.write_text("source candidate")
    assert filter_safe_archive_paths([candidate.name], {candidate.name}, active, repo_root=tmp_path)["safe_to_archive"]
    app_root = tmp_path / "api-app"
    if change == "file_added":
        (app_root / candidate.name).write_text("now active")
    elif change == "file_bytes_changed":
        (app_root / "api-live.py").write_text("new")
    else:
        startup = tmp_path / "api-startup.json"
        data = json.loads(startup.read_text())
        data["app_root"] = str(tmp_path / "main-app")
        startup.write_text(json.dumps(data))
        with pytest.raises(ManifestCoverageError):
            load_manifest_paths(group)
    assert filter_safe_archive_paths([candidate.name], {candidate.name}, active, repo_root=tmp_path)["safe_to_archive"] == []


def test_archive_protects_verified_runtime_paths_and_respects_owned_cache_rule(tmp_path):
    group = _complete_archive_group(tmp_path)
    app_root = tmp_path / "api-app"
    cache = app_root / "__pycache__"
    cache.mkdir()
    (cache / "api-live.cpython-314.pyc").write_bytes(b"generated cache")
    alias = app_root / "alias"
    alias.symlink_to("__pycache__", target_is_directory=True)
    startup = tmp_path / "api-startup.json"
    data = json.loads(startup.read_text())
    inv = data["application_inventory"]
    inv["entries"].insert(0, {"path": "alias", "kind": "symlink", "target": "__pycache__", "target_exists": True})
    inv["entry_count"] += 1
    raw = json.dumps(inv["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    inv["aggregate_sha256"] = sha256(raw).hexdigest()
    startup.write_text(json.dumps(data))
    active = load_manifest_paths(group)
    candidates = ["api-app/api-live.py", "candidate.py"]
    (tmp_path / "candidate.py").write_text("source code")
    result = filter_safe_archive_paths(candidates, set(candidates), active, repo_root=tmp_path)
    assert result["safe_to_archive"] == ["candidate.py"]
    assert result["skipped_active_manifest"] == ["api-app/api-live.py"]


def test_archive_protects_directory_symlink_target_and_descendants(tmp_path):
    group = _complete_archive_group(tmp_path)
    shared = tmp_path / "shared"
    (shared / "nested").mkdir(parents=True)
    (shared / "nested" / "module.py").write_text("in use through the active app")
    (tmp_path / "api-app" / "lib").symlink_to("../shared", target_is_directory=True)
    startup = tmp_path / "api-startup.json"
    data = json.loads(startup.read_text())
    inv = data["application_inventory"]
    inv["entries"].append({"path": "lib", "kind": "symlink", "target": "../shared", "target_exists": True})
    inv["entry_count"] = len(inv["entries"])
    raw = json.dumps(inv["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    inv["aggregate_sha256"] = sha256(raw).hexdigest()
    startup.write_text(json.dumps(data))
    sibling = tmp_path / "shared-other"
    sibling.mkdir()
    (sibling / "module.py").write_text("unrelated")
    candidates = ["shared/nested/module.py", "api-app/lib/nested/module.py", "shared-other/module.py"]

    result = filter_safe_archive_paths(candidates, set(candidates), load_manifest_paths(group), repo_root=tmp_path)

    assert result["safe_to_archive"] == ["shared-other/module.py"]
    assert result["skipped_active_manifest"] == candidates[:2]


def test_archive_protects_real_files_of_verified_group_release_and_startup_manifests(tmp_path):
    group = _complete_archive_group(tmp_path)
    # Names bypass the generic "manifest" keyword and are outside every application root.
    group_alias = tmp_path / "entry.json"
    group_alias.symlink_to(group.name)
    (tmp_path / "candidate.py").write_text("unrelated")
    protected = [group.name, "api.json", "api-startup.json", "main.json", "main-startup.json",
                 "stage.json", "stage-startup.json"]
    candidates = [*protected, "candidate.py"]

    result = filter_safe_archive_paths(candidates, set(candidates), load_manifest_paths(group_alias), repo_root=tmp_path)

    assert result["safe_to_archive"] == ["candidate.py"]
    assert result["skipped_active_manifest"] == protected
