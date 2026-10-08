from __future__ import annotations

import hashlib
import importlib.util
import json
import plistlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


HELPER_PATH = Path(__file__).parents[1] / "tools/api_only_cutover.py"
SPEC = importlib.util.spec_from_file_location("api_only_cutover", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
cutover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _product_baseline_fixture() -> dict:
    current_sha = "8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157"
    legacy_sha = "7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278"
    workspace_gap = "ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"
    return {"scope": "ROOT_READ_ONLY_PRE_SWITCH_PRODUCT_BASELINE", "results": [
        {"name": "current_analysis",
         "path": "/api/v4/manager/research/announcements/analysis?date=20261008&publication_date=2026-10-07",
         "http_status": 200,
         "analysis": {"status": "VERIFIED", "product_sha256": current_sha, "gaps": []},
         "stock_selection": {"status": "VERIFIED", "product_sha256": current_sha, "gaps": []},
         "stock_selection_list_lengths": {"stocks": 529, "article_decisions": 613, "gaps": 0},
         "owner_import_receipt": {"product_sha256": current_sha, "publication_date": "2026-10-07",
             "status": "VERIFIED", "target_trade_date": "20261008"}},
        {"name": "legacy_analysis",
         "path": "/api/v4/manager/research/announcements/analysis?date=20261007&publication_date=2026-10-06",
         "http_status": 200,
         "analysis": {"status": "VERIFIED", "product_sha256": legacy_sha, "gaps": []},
         "stock_selection": {"status": "VERIFIED", "product_sha256": legacy_sha, "gaps": []},
         "stock_selection_list_lengths": {"stocks": 524, "article_decisions": 580, "gaps": 0},
         "owner_import_receipt": None},
        {"name": "current_workspace",
         "path": "/api/v4/manager/research/workspace?date=20261008&selection_date=20261007&announcement_date=20261007&view=dynamic",
         "http_status": 200,
         "workspace_analysis": {"status": "CANNOT_CONFIRM", "gaps": [workspace_gap]}}
    ]}


def _historical_api_payload(row: dict) -> dict:
    analysis = row.get("analysis")
    if isinstance(analysis, dict):
        selection = row["stock_selection"]
        lengths = row["stock_selection_list_lengths"]
        return {"analysis": {**analysis, "stock_selection": {**selection,
            "stocks": [{} for _ in range(lengths["stocks"])],
            "article_decisions": [{} for _ in range(lengths["article_decisions"])],
            "gaps": []}},
            "owner_import_receipt": row.get("owner_import_receipt")}
    return {"announcement_reviewed_analysis": row["workspace_analysis"],
            "announcement_review": {"status": "NOT_RUN"},
            "plan_product": {"status": "NOT_MATERIALIZED"},
            "read_context": {"status": "VERIFIED_WITH_GAPS"}}


def _consumption_validation_payload(row: dict, name: str) -> dict:
    legacy = name == "legacy_analysis"
    product_sha = row["analysis"]["product_sha256"]
    return {
        "schema_version": cutover.CONSUMPTION_VALIDATION_SCHEMA,
        "target_trade_date": "20261007" if legacy else "20261008",
        "publication_date": "2026-10-06" if legacy else "2026-10-07",
        "status": "NOT_CONSUMED_INVALID" if legacy else "VERIFIED",
        "validation_status": "CANNOT_CONFIRM" if legacy else "VERIFIED",
        "consumed": False,
        "product_sha256": product_sha,
        "source_manifest_sha256": None,
        "catalog_product_sha256": None,
        "source_run_id": None,
        "evidence_run_id": None,
        "handoff_manifest_sha256": None,
        "agent_judgment_receipt_sha256": None,
        "owner_import_receipt_sha256": None,
        "owner_handoff_binding_status": "NOT_VERIFIED",
        "decision_status": None,
        "selection_status": "NOT_ASSESSED",
        "stock_count": None,
        "selected_stock_count": None,
        "conditional_watch_count": None,
        "not_selected_stock_count": None,
        "not_assessed_stock_count": None,
        "reviewed_at": None,
        "owner_available_at": None,
        "latest_source_or_review_at": None,
        "plan_cutoff": None,
        "cutoff_status": "NOT_REQUESTED",
        "failure_stage": "JUDGMENT_RECEIPT" if legacy else None,
        "gaps": ["ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"] if legacy else [],
        "research_references": [],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "phase2/drafts").mkdir(parents=True)
    (task_root / "phase2/receipts").mkdir(parents=True)
    plan_path = task_root / "phase2/drafts/api_only_cutover_plan.json"
    staged_plist_path = task_root / "phase2/drafts/com.lexi.v35.api-only.plist"
    staged_diff_path = task_root / "phase2/drafts/staged_api_plist_diff.json"
    stage_receipt_path = task_root / "phase2/receipts/api_release_stage_receipt.json"
    product_baseline_path = task_root / "control/pre_switch_product_baseline.json"
    source_app = task_root / "candidate/api/app"
    release_root = tmp_path / "releases/manager-workbench-r1-mac-20261008-api"
    app_root = release_root / "app"
    for root in (source_app, app_root):
        dist = root / "apps/web/dist"
        (dist / "manager-selection").mkdir(parents=True)
        (dist / "assets").mkdir()
        (root / "ops").mkdir(parents=True, exist_ok=True)
        (dist / "manager-selection/index.html").write_text(
            '<html><head><script type="module" src="/assets/manager.js"></script>'
            '<link rel="stylesheet" href="/assets/manager.css">'
            '<link rel="modulepreload" href="/assets/runtime.js"></head><body></body></html>',
            encoding="utf-8")
        (dist / "assets/manager.js").write_bytes(b"manager-r1-bundle")
        (dist / "assets/manager.css").write_bytes(b"manager-r1-style")
        (dist / "assets/runtime.js").write_bytes(b"runtime-bundle")
    # The exact inventory implementation is taken from the frozen R1 API
    # candidate, alongside its one local import dependency.
    real_ops = cutover.TASK_ROOT / "candidate/api/app/ops"
    for name in ("build_release_candidate.py", "prepare_api_only_cutover.py"):
        shutil.copy2(real_ops / name, source_app / "ops" / name)
        shutil.copy2(real_ops / name, app_root / "ops" / name)
    backend = source_app / "ops/build_release_candidate.py"

    monkeypatch.setattr(cutover, "TASK_ROOT", task_root)
    monkeypatch.setattr(cutover, "EXPECTED_RELEASE_ROOT", release_root)
    monkeypatch.setattr(cutover, "EXPECTED_API_ROOT", app_root)
    monkeypatch.setattr(cutover, "INVENTORY_BACKEND_PATH", backend)
    monkeypatch.setattr(cutover, "EXPECTED_API_INVENTORY_SHA256", "0" * 64)
    monkeypatch.setattr(cutover, "EXPECTED_DIST_TREE_SHA256", "1" * 64)
    monkeypatch.setattr(cutover, "PINNED_PYTHON", Path(sys.executable))
    monkeypatch.setattr(cutover, "PLAN_PATH", plan_path)
    monkeypatch.setattr(cutover, "STAGED_API_PLIST_PATH", staged_plist_path)
    monkeypatch.setattr(cutover, "STAGED_API_PLIST_DIFF_PATH", staged_diff_path)
    monkeypatch.setattr(cutover, "RELEASE_STAGE_RECEIPT_PATH", stage_receipt_path)
    monkeypatch.setattr(cutover, "PRODUCT_BASELINE_PATH", product_baseline_path)

    # Import the approved inventory function after the local dependency is in
    # place; then freeze identical source and release trees for this test.
    plan_stub = {"source": {"inventory_backend_path": str(backend),
                            "inventory_backend_sha256": _sha(backend.read_bytes())}}
    inventory = cutover._load_inventory_backend(plan_stub)
    entries = inventory.inventory_tree(source_app)
    inventory_sha = inventory.inventory_digest(entries)
    assert inventory.inventory_tree(app_root) == entries
    monkeypatch.setattr(cutover, "EXPECTED_API_INVENTORY_SHA256", inventory_sha)
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "activation_status": "NOT_ACTIVATED",
        "candidate": {"release_id": release_root.name, "app_root": str(app_root)},
        "application_inventory": {"entry_count": len(entries), "aggregate_sha256": inventory_sha,
                                  "entries": entries},
    }
    manifest_path = release_root / "release-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_sha = _sha(manifest_path.read_bytes())

    api_inventory_receipt = task_root / "receipts/api_candidate_p2_delta.json"
    api_inventory_receipt.parent.mkdir(parents=True)
    api_inventory_receipt.write_text(json.dumps({"aggregate_sha256": inventory_sha}), encoding="utf-8")
    monkeypatch.setattr(cutover, "API_INVENTORY_RECEIPT_SHA256", _sha(api_inventory_receipt.read_bytes()))
    p2_receipt = task_root / "receipts/p2_delta_receipt.json"
    p2_receipt.write_text(json.dumps({"dist_sync": {"same_paths_and_bytes": True,
        "source_tree_sha256": "1" * 64, "target_tree_sha256": "1" * 64}}), encoding="utf-8")
    monkeypatch.setattr(cutover, "P2_DELTA_RECEIPT_SHA256", _sha(p2_receipt.read_bytes()))
    p2_review = task_root / "review/p2_delta_independent_review.json"
    p2_review.parent.mkdir()
    p2_review.write_text(json.dumps({"status": {"REVIEWED": "PASS",
        "BEHAVIOR_VERIFIED": "PASS for the fixture"}}), encoding="utf-8")
    monkeypatch.setattr(cutover, "P2_REVIEW_PATH", p2_review)
    monkeypatch.setattr(cutover, "P2_REVIEW_SHA256", _sha(p2_review.read_bytes()))

    active = tmp_path / "LaunchAgents/com.lexi.v35.api-only.plist"
    scheduler = tmp_path / "LaunchAgents/com.lexi.v35.scheduler.plist"
    stage_center = tmp_path / "LaunchAgents/com.lexi.stage-center.scheduler.plist"
    active.parent.mkdir(parents=True)
    old_root = tmp_path / "releases/old-r3/app"
    old_identity = {"V35_APP_ROOT": str(old_root),
        "V35_RELEASE_ID": "manager-daily-chain-20261008-r3-api",
        "V35_RELEASE_MANIFEST_SHA256": "a" * 64}
    binding_path = tmp_path / "disabled-binding.json"
    formal_state = tmp_path / "manager_state"
    formal_state.mkdir()
    binding_path.write_text(json.dumps({"enabled": False, "announcement_collection_enabled": False,
        "plan_material_refresh_only": False, "manager_state_root": str(formal_state)}), encoding="utf-8")
    monkeypatch.setattr(cutover, "ACTIVE_API_PLIST", active)
    monkeypatch.setattr(cutover, "ACTIVE_SCHEDULER_PLIST", scheduler)
    monkeypatch.setattr(cutover, "STAGE_CENTER_SCHEDULER_PLIST", stage_center)
    monkeypatch.setattr(cutover, "DISABLED_BINDING_PATH", binding_path)
    monkeypatch.setattr(cutover, "FORMAL_MANAGER_STATE", formal_state)
    monkeypatch.setattr(cutover, "LAUNCHCTL", tmp_path / "launchctl")
    monkeypatch.setattr(cutover, "SCREEN_AUTHORITY_ROOT", Path("/preserved/manager/screen-authority"))
    old_env = {**old_identity,
        "V35_RELEASE_MANIFEST_PATH": str(tmp_path / "old-r3/release-manifest.json"),
        "PYTHONPATH": str(old_root / "upstreams") + ":" + str(old_root),
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
        "V4_MANAGER_SCREEN_AUTHORITY_ROOT": str(cutover.SCREEN_AUTHORITY_ROOT),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(formal_state), **cutover.SAFETY_EXPECTED}
    old_plist = {"Label": cutover.LABEL, "KeepAlive": True, "RunAtLoad": False,
        "WorkingDirectory": str(old_root),
        "ProgramArguments": ["/usr/bin/env", *[f"{key}={value}" for key, value in old_env.items()],
                             str(cutover.PINNED_PYTHON), "-B", "-m", "apps.api.v35_api.run"]}
    old_raw = plistlib.dumps(old_plist, fmt=plistlib.FMT_XML, sort_keys=True)
    active.write_bytes(old_raw)
    scheduler.write_bytes(b"scheduler-preimage")
    stage_center.write_bytes(b"stage-center-preimage")

    product_baseline = _product_baseline_fixture()
    monkeypatch.setattr(cutover, "CONSUMPTION_VALIDATION_CANONICAL_SHA256", {
        name: cutover._consumption_validation_sha(_consumption_validation_payload(
            next(row for row in product_baseline["results"] if row["name"] == name), name))
        for name in ("current_analysis", "legacy_analysis")})
    for row in product_baseline["results"]:
        row["response_sha256"] = _sha(json.dumps(_historical_api_payload(row)).encode())
    product_baseline_path.parent.mkdir(parents=True)
    product_baseline_raw = (json.dumps(product_baseline, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    product_baseline_path.write_bytes(product_baseline_raw)
    monkeypatch.setattr(cutover, "PRODUCT_BASELINE_SHA256", _sha(product_baseline_raw))
    baseline_rows = {row["name"]: row for row in product_baseline["results"]}

    stage_receipt_unsigned = {"schema_version": "v4.manager_workbench_r1_mac.api_release_stage.v1",
        "status": "STAGED_AND_VERIFIED_NOT_DEPLOYED", "release_root": str(release_root),
        "release_manifest_sha256": manifest_sha, "application_inventory_sha256": inventory_sha,
        "application_inventory_entries": len(entries)}
    stage_receipt = {**stage_receipt_unsigned,
        "receipt_sha256": cutover._canonical_sha(stage_receipt_unsigned)}
    stage_receipt_path.write_text(json.dumps(stage_receipt, sort_keys=True), encoding="utf-8")

    plan = {
        "schema_version": cutover.PLAN_SCHEMA, "task_root": str(task_root),
        "target": {"release_root": str(release_root), "app_root": str(app_root),
            "release_id": release_root.name, "release_manifest_sha256": manifest_sha,
            "application_inventory_sha256": inventory_sha,
            "staged_api_plist_path": str(staged_plist_path),
            "staged_api_plist_diff_path": str(staged_diff_path),
            "staged_api_plist_sha256": None, "staged_api_plist_diff_sha256": None},
        "before": {"active_api_plist_path": str(active), "active_api_plist_sha256": _sha(old_raw),
            "loaded_identity": {"state": "running", "pid": "1297", **old_identity},
            "scheduler_plist_path": str(scheduler), "scheduler_plist_sha256": _sha(scheduler.read_bytes()),
            "stage_center_scheduler_plist_path": str(stage_center),
            "stage_center_scheduler_plist_sha256": _sha(stage_center.read_bytes())},
        "source": {"source_candidate_app_root": str(source_app),
            "inventory_backend_path": str(backend), "inventory_backend_sha256": _sha(backend.read_bytes()),
            "p2_independent_review_sha256": _sha(p2_review.read_bytes()),
            "release_stage_receipt": "phase2/receipts/api_release_stage_receipt.json",
            "release_stage_receipt_sha256": _sha(stage_receipt_path.read_bytes()),
            "pre_switch_product_baseline": "control/pre_switch_product_baseline.json",
            "pre_switch_product_baseline_sha256": _sha(product_baseline_raw)},
        "guards": {"disabled_binding_path": str(binding_path),
            "disabled_binding_sha256": _sha(binding_path.read_bytes())}}

    loaded: dict[str, str] | None = dict(plan["before"]["loaded_identity"])
    launchctl_calls: list[tuple[str, str]] = []

    def fake_print() -> str:
        if loaded is None:
            raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:could not find service")
        return ("state = running\n" + f"pid = {loaded['pid']}\n" +
                "".join(f"{key}={loaded[key]}\n" for key in (
                    "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")))

    def fake_action(action: str) -> None:
        nonlocal loaded
        launchctl_calls.append((action, cutover.LABEL))
        if action == "bootout":
            loaded = None
        elif action == "bootstrap":
            loaded = {"state": "running", "pid": str(2000 + len(launchctl_calls)),
                      **cutover._identity_from_plist(active.read_bytes())}

    def fake_http(path: str) -> tuple[int, bytes]:
        if path == "/openapi.json":
            return 200, json.dumps({"paths": {cutover.MANAGER_WORKSPACE_ROUTE: {"get": {}}}}).encode()
        if path == cutover.MANAGER_SELECTION_HTML:
            return 200, (app_root / "apps/web/dist/manager-selection/index.html").read_bytes()
        for name in ("current_analysis", "legacy_analysis"):
            row = baseline_rows[name]
            if path == row["path"]:
                payload = _historical_api_payload(row)
                if loaded is not None and loaded.get("V35_RELEASE_ID") == release_root.name:
                    payload["consumption_validation"] = _consumption_validation_payload(row, name)
                return 200, json.dumps(payload).encode()
        if path == baseline_rows["current_workspace"]["path"]:
            return 200, json.dumps(_historical_api_payload(baseline_rows["current_workspace"])).encode()
        return 200, (app_root / "apps/web/dist" / path.lstrip("/")).read_bytes()

    monkeypatch.setattr(cutover, "_launchctl_print", fake_print)
    monkeypatch.setattr(cutover, "_launchctl_action", fake_action)
    monkeypatch.setattr(cutover, "_http_get", fake_http)
    candidate = cutover._load_candidate_release(plan)
    staged_raw = cutover._candidate_plist_bytes(old_raw, plan, candidate)
    diff = cutover._staged_plist_diff(old_raw, staged_raw, candidate)
    diff_raw = (json.dumps(diff, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    plan["target"]["staged_api_plist_sha256"] = _sha(staged_raw)
    plan["target"]["staged_api_plist_diff_sha256"] = _sha(diff_raw)
    staged_plist_path.write_bytes(staged_raw)
    staged_diff_path.write_bytes(diff_raw)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return SimpleNamespace(plan=plan, app_root=app_root, release_root=release_root,
        active=active, scheduler=scheduler, stage_center=stage_center, old_raw=old_raw,
        old_identity=old_identity, launchctl_calls=launchctl_calls, get_loaded=lambda: loaded,
        staged_plist_path=staged_plist_path, staged_diff_path=staged_diff_path,
        product_baseline=product_baseline)


def test_checked_plan_is_scoped_to_api_only_and_does_not_call_runtime(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    assert preflight["status"] == "READY_API_ONLY_R1_CUTOVER"
    assert preflight["before"]["loaded_identity"]["pid"] == "1297"
    assert preflight["after"]["release_id"] == fixture.release_root.name
    assert preflight["candidate_release"]["frontend"]["asset_reference_count"] == 3
    history = preflight["historical_product_readback"]["results"]
    assert history["current_analysis"]["product_sha256"] == "8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157"
    assert history["current_analysis"]["owner_import_receipt"]["baseline_status"] == "VERIFIED"
    assert history["legacy_analysis"]["product_sha256"] == "7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278"
    assert history["legacy_analysis"]["owner_import_receipt"]["baseline_status"] == "ABSENT_LEGACY_R3_COMPATIBLE"
    assert history["current_workspace"]["status"] == "CANNOT_CONFIRM"
    assert history["current_workspace"]["judgment_receipt"] == "CANNOT_CONFIRM"
    assert history["current_workspace"]["data_loss_conclusion"] == "CANNOT_CONFIRM"
    assert preflight["allowed_live_write"] == str(fixture.active)
    assert preflight["scheduler_action"] == "UNCHANGED"
    assert fixture.launchctl_calls == []


def test_historical_analysis_owner_receipt_must_match_pinned_baseline(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get
    current_path = fixture.product_baseline["results"][0]["path"]

    def receipt_drift(path: str):
        status, raw = original_http_get(path)
        if path == current_path:
            payload = json.loads(raw.decode())
            payload["owner_import_receipt"] = {"status": "INVALID"}
            return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", receipt_drift)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_RESPONSE_SHA_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback()


def test_candidate_post_switch_accepts_current_verified_and_legacy_invalid_projection(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get

    def candidate_readback(path: str):
        status, raw = original_http_get(path)
        for name in ("current_analysis", "legacy_analysis"):
            row = next(row for row in fixture.product_baseline["results"] if row["name"] == name)
            if path == row["path"]:
                payload = json.loads(raw.decode())
                payload["consumption_validation"] = _consumption_validation_payload(row, name)
                return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", candidate_readback)
    result = cutover._verify_historical_product_readback(allow_r1_consumption_validation=True)
    current = result["results"]["current_analysis"]["consumption_validation"]
    legacy = result["results"]["legacy_analysis"]["consumption_validation"]
    current_readback = result["results"]["current_analysis"]
    assert result["status"] == "HISTORICAL_ANALYSIS_PRODUCTS_VERIFIED_WORKSPACE_CANNOT_CONFIRM"
    assert current["status"] == "VERIFIED"
    assert current["validation_status"] == "VERIFIED"
    assert current["product_sha256"] == "8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157"
    assert current_readback["response_sha256_matches_baseline"] is False
    assert current_readback["baseline_comparison_sha256_matches"] is True
    assert current_readback["baseline_comparison_method"] == "R1_ADDITIVE_CONSUMPTION_VALIDATION_STRIPPED"
    assert legacy["status"] == "NOT_CONSUMED_INVALID"
    assert legacy["validation_status"] == "CANNOT_CONFIRM"
    assert legacy["failure_stage"] == "JUDGMENT_RECEIPT"
    assert legacy["gaps"] == ["ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"]
    assert legacy["product_sha256"] == "7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278"


def test_candidate_post_switch_rejects_consumption_projection_for_other_product(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get
    current_path = fixture.product_baseline["results"][0]["path"]

    def mismatched_product(path: str):
        status, raw = original_http_get(path)
        for name in ("current_analysis", "legacy_analysis"):
            row = next(row for row in fixture.product_baseline["results"] if row["name"] == name)
            if path == row["path"]:
                payload = json.loads(raw.decode())
                value = _consumption_validation_payload(row, name)
                if path == current_path:
                    value["product_sha256"] = "f" * 64
                payload["consumption_validation"] = value
                return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", mismatched_product)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback(allow_r1_consumption_validation=True)


def test_candidate_post_switch_rejects_wrong_current_consumption_semantics(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get
    current_path = fixture.product_baseline["results"][0]["path"]

    def invalid_current(path: str):
        status, raw = original_http_get(path)
        if path == current_path:
            payload = json.loads(raw.decode())
            value = _consumption_validation_payload(fixture.product_baseline["results"][0], "current_analysis")
            value["status"] = "NOT_CONSUMED_INVALID"
            payload["consumption_validation"] = value
            return status, json.dumps(payload).encode()
        if path == fixture.product_baseline["results"][1]["path"]:
            payload = json.loads(raw.decode())
            payload["consumption_validation"] = _consumption_validation_payload(
                fixture.product_baseline["results"][1], "legacy_analysis")
            return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", invalid_current)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback(allow_r1_consumption_validation=True)


def test_candidate_post_switch_rejects_unknown_validation_schema_key(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get

    def unknown_key(path: str):
        status, raw = original_http_get(path)
        for name in ("current_analysis", "legacy_analysis"):
            row = next(row for row in fixture.product_baseline["results"] if row["name"] == name)
            if path == row["path"]:
                payload = json.loads(raw.decode())
                value = _consumption_validation_payload(row, name)
                value["future_unreviewed_field"] = "ignored?"
                payload["consumption_validation"] = value
                return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", unknown_key)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_SCHEMA_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback(allow_r1_consumption_validation=True)


def test_candidate_post_switch_rejects_original_product_content_tamper(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get

    def tamper_original_content(path: str):
        status, raw = original_http_get(path)
        current_path = fixture.product_baseline["results"][0]["path"]
        legacy_path = fixture.product_baseline["results"][1]["path"]
        if path in {current_path, legacy_path}:
            payload = json.loads(raw.decode())
            name = "current_analysis" if path == current_path else "legacy_analysis"
            row = next(row for row in fixture.product_baseline["results"] if row["name"] == name)
            payload["consumption_validation"] = _consumption_validation_payload(row, name)
            if path == current_path:
                payload["analysis"]["stock_selection"]["stocks"][0]["symbol"] = "TAMPERED"
            return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", tamper_original_content)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_RESPONSE_SHA_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback(allow_r1_consumption_validation=True)


def test_preflight_oracle_remains_strict_when_r1_projection_is_present(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get
    current_path = fixture.product_baseline["results"][0]["path"]

    def candidate_readback(path: str):
        status, raw = original_http_get(path)
        if path == current_path:
            payload = json.loads(raw.decode())
            payload["consumption_validation"] = _consumption_validation_payload(
                fixture.product_baseline["results"][0], "current_analysis")
            return status, json.dumps(payload).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", candidate_readback)
    with pytest.raises(ValueError, match="HISTORICAL_ANALYSIS_RESPONSE_SHA_MISMATCH:current_analysis"):
        cutover._verify_historical_product_readback()


def test_consumption_projection_sha_pins_are_stable():
    assert cutover.CONSUMPTION_VALIDATION_CANONICAL_SHA256 == {
        "current_analysis": "796e437a76c1a40acf7ade7c1bac64be53c7aaa4cd21e387d3ca7e3e2c72aee9",
        "legacy_analysis": "25ed3622660ce7602bb782257cf3b85d7346c1c7838e8fc1488b9dbf245ab726",
    }


def test_staged_metadata_projection_fixture_uses_pinned_source_order_serializer():
    fixture_path = Path(__file__).parents[2] / "completion_20261008/metadata_only_projection_fixture.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["raw_response_body_retained"] is False
    baseline = cutover._load_product_baseline()["rows"]
    for name in ("current_analysis", "legacy_analysis"):
        source = fixture["products"][name]
        projection = source["projection"]
        ordered = {key: projection[key] for key in source["projection_key_order"]}
        assert set(ordered) == cutover.CONSUMPTION_VALIDATION_KEYS
        assert cutover._consumption_validation_sha(ordered) == cutover.CONSUMPTION_VALIDATION_CANONICAL_SHA256[name]
        assert cutover._canonical_sha(ordered) != cutover.CONSUMPTION_VALIDATION_CANONICAL_SHA256[name]
        summary = cutover._validate_consumption_validation(
            name, ordered, baseline[name], baseline[name]["analysis"]["product_sha256"])
        assert summary["safety_flags_match"] is True
        if name == "legacy_analysis":
            assert summary["status"] == "NOT_CONSUMED_INVALID"
            assert summary["validation_status"] == "CANNOT_CONFIRM"
            assert summary["consumed"] is False
            assert summary["gaps"] == ["ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"]


def test_workspace_envelope_drift_remains_explicit_cannot_confirm(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_http_get = cutover._http_get
    workspace_path = fixture.product_baseline["results"][2]["path"]

    def workspace_envelope_drift(path: str):
        status, raw = original_http_get(path)
        if path == workspace_path:
            payload = json.loads(raw.decode())
            payload["briefing"] = {"status": "DYNAMIC_ENVELOPE_DRIFT"}
            return status, json.dumps(payload, sort_keys=True).encode()
        return status, raw

    monkeypatch.setattr(cutover, "_http_get", workspace_envelope_drift)
    result = cutover._verify_historical_product_readback()
    workspace = result["results"]["current_workspace"]
    assert result["status"] == "HISTORICAL_ANALYSIS_PRODUCTS_VERIFIED_WORKSPACE_CANNOT_CONFIRM"
    assert workspace["response_sha_matches_baseline"] is False
    assert workspace["baseline_response_sha256"] == fixture.product_baseline["results"][2]["response_sha256"]
    assert workspace["observed_response_sha256"] != workspace["baseline_response_sha256"]
    assert workspace["observed_status"] == "CANNOT_CONFIRM"
    assert workspace["known_invalid_judgment_gap_present"] is True
    assert workspace["announcement_review_status"] == "NOT_RUN"
    assert workspace["plan_product_status"] == "NOT_MATERIALIZED"
    assert workspace["data_loss_conclusion"] == "CANNOT_CONFIRM"


def test_preflight_treats_api_pid_as_observation_but_pins_release_identity(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    identity = fixture.plan["before"]["loaded_identity"]
    output = ("state = running\npid = 2299\n" +
              "".join(f"{key}={identity[key]}\n" for key in (
                  "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")))
    monkeypatch.setattr(cutover, "_launchctl_print", lambda: output)
    preflight = cutover._preflight(fixture.plan)
    assert preflight["before"]["loaded_identity"]["pid"] == "2299"
    assert preflight["before"]["loaded_identity"]["V35_RELEASE_ID"] == fixture.old_identity["V35_RELEASE_ID"]


def test_staged_plist_changes_only_release_identity_and_working_directory(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    staged = plistlib.loads(fixture.staged_plist_path.read_bytes())
    original = plistlib.loads(fixture.old_raw)
    _old_prefix, old_env, _old_command = cutover._split_env_arguments(original)
    _new_prefix, new_env, _new_command = cutover._split_env_arguments(staged)
    expected_changes = {"V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
                        "V35_RELEASE_MANIFEST_SHA256", "PYTHONPATH"}
    assert {key for key in set(old_env) | set(new_env) if old_env.get(key) != new_env.get(key)} == expected_changes
    assert staged["WorkingDirectory"] == str(fixture.app_root)
    assert new_env["V4_MANAGER_SCREEN_AUTHORITY_ROOT"] == old_env["V4_MANAGER_SCREEN_AUTHORITY_ROOT"]
    assert new_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == old_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"]
    diff = json.loads(fixture.staged_diff_path.read_text())
    assert all(row["unchanged"] for row in diff["preserved_runtime_bindings"].values())
    assert diff["disabled_binding"]["enabled"] is False


def test_stage_plist_command_is_idempotent_and_never_operates_service(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    original_active = fixture.active.read_bytes()
    result = cutover._stage_api_plist(fixture.plan)
    assert result["status"] == "STAGED_API_PLIST_READY_NOT_DEPLOYED"
    assert result["launchctl_mutation_called"] is False
    assert result["launchctl_readonly_prints"] is True
    assert result["active_api_plist_written"] is False
    assert fixture.active.read_bytes() == original_active
    assert fixture.launchctl_calls == []


def test_switch_writes_only_api_plist_and_verifies_api_plus_static_bundle(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    result = cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
        expected_current_sha=preflight["before"]["active_api_plist_sha256"],
        expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert result["status"] == "API_ONLY_R1_SWITCHED_AND_READBACK_VERIFIED"
    assert result["runtime_verification"]["http"]["manager_workspace_get"] == "AVAILABLE"
    assert result["runtime_verification"]["ui_static_readback"]["static_bundle_status"] == "BYTE_IDENTICAL_TO_RELEASE"
    assert [action for action, label in fixture.launchctl_calls] == ["bootout", "bootstrap"]
    assert {label for _action, label in fixture.launchctl_calls} == {cutover.LABEL}
    assert fixture.scheduler.read_bytes() == b"scheduler-preimage"
    assert fixture.stage_center.read_bytes() == b"stage-center-preimage"
    assert plistlib.loads(fixture.active.read_bytes())["WorkingDirectory"] == str(fixture.app_root)


def test_frontend_readback_failure_restores_exact_api_preimage(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    good_http = cutover._http_get

    def failed_asset_readback(path: str) -> tuple[int, bytes]:
        if path == "/assets/manager.js":
            return 503, b""
        return good_http(path)

    ticks = {"count": 0}

    def bounded_monotonic() -> float:
        ticks["count"] += 1
        return 0.0 if ticks["count"] <= 2 else 61.0

    monkeypatch.setattr(cutover.time, "monotonic", bounded_monotonic)
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cutover, "_http_get", failed_asset_readback)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
            expected_current_sha=preflight["before"]["active_api_plist_sha256"],
            expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert fixture.active.read_bytes() == fixture.old_raw
    assert fixture.get_loaded() == {"state": "running", "pid": fixture.get_loaded()["pid"],
                                    **fixture.old_identity}
    assert [action for action, _label in fixture.launchctl_calls] == ["bootout", "bootstrap", "bootout", "bootstrap"]


def test_scheduler_drift_after_bootout_is_preserved_while_api_preimage_recovers(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    old_action = cutover._launchctl_action
    changed = False

    def drift_scheduler_after_bootout(action: str) -> None:
        nonlocal changed
        old_action(action)
        if action == "bootout" and not changed:
            fixture.scheduler.write_bytes(b"external-scheduler-change")
            changed = True

    monkeypatch.setattr(cutover, "_launchctl_action", drift_scheduler_after_bootout)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
            expected_current_sha=preflight["before"]["active_api_plist_sha256"],
            expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert fixture.active.read_bytes() == fixture.old_raw
    assert fixture.scheduler.read_bytes() == b"external-scheduler-change"
    assert fixture.get_loaded()["V35_RELEASE_ID"] == fixture.old_identity["V35_RELEASE_ID"]


def test_bootstrap_failure_restores_old_api_and_readback(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    old_action = cutover._launchctl_action
    bootstrap_count = 0

    def fail_first_bootstrap(action: str) -> None:
        nonlocal bootstrap_count
        if action == "bootstrap":
            bootstrap_count += 1
            if bootstrap_count == 1:
                fixture.launchctl_calls.append((action, cutover.LABEL))
                raise ValueError("simulated bootstrap refusal")
        old_action(action)

    monkeypatch.setattr(cutover, "_launchctl_action", fail_first_bootstrap)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
            expected_current_sha=preflight["before"]["active_api_plist_sha256"],
            expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert fixture.active.read_bytes() == fixture.old_raw
    assert fixture.get_loaded()["V35_RELEASE_ID"] == fixture.old_identity["V35_RELEASE_ID"]
    assert bootstrap_count == 2


def test_missing_plist_after_replace_io_error_is_restored_exclusively(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)

    def remove_then_fail(path: Path, _raw: bytes, _metadata_source: Path,
                         expected_current_sha: str) -> None:
        assert cutover._sha_file(path) == expected_current_sha
        path.unlink()
        raise OSError("simulated atomic replace failure after target removal")

    monkeypatch.setattr(cutover, "_atomic_replace_bytes", remove_then_fail)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
            expected_current_sha=preflight["before"]["active_api_plist_sha256"],
            expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert fixture.active.read_bytes() == fixture.old_raw
    assert fixture.get_loaded()["V35_RELEASE_ID"] == fixture.old_identity["V35_RELEASE_ID"]


def test_manual_rollback_uses_success_receipt_and_exact_backup(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    preflight = cutover._preflight(fixture.plan)
    result = cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
        expected_current_sha=preflight["before"]["active_api_plist_sha256"],
        expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    rollback = cutover._run_rollback(fixture.plan, receipt_path=Path(result["receipt_path"]),
        confirmation=cutover.CONFIRM_ROLLBACK,
        expected_current_sha=preflight["after"]["staged_api_plist_sha256"])
    assert rollback["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert fixture.active.read_bytes() == fixture.old_raw
    assert fixture.get_loaded()["V35_RELEASE_ID"] == fixture.old_identity["V35_RELEASE_ID"]


def test_wrong_confirmation_and_stale_cas_refuse_before_launchctl(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EXPLICIT_API_ONLY_SWITCH_CONFIRMATION_REQUIRED"):
        cutover._run_switch(fixture.plan, confirmation="", expected_current_sha="x", expected_staged_sha="y")
    preflight = cutover._preflight(fixture.plan)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_EXPECTED_SHA_ARGUMENT_MISMATCH"):
        cutover._run_switch(fixture.plan, confirmation=cutover.CONFIRM_SWITCH,
            expected_current_sha="0" * 64,
            expected_staged_sha=preflight["after"]["staged_api_plist_sha256"])
    assert fixture.launchctl_calls == []
