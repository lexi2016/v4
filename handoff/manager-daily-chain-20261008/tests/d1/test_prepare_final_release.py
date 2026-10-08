from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import plistlib
import stat

import pytest


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only")
SCRIPT = TASK_ROOT / "prepare_final_release.py"


def _module():
    spec = importlib.util.spec_from_file_location("d1_prepare_final_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_plan_canary_dry_run_lists_exact_owner_write_effect_only():
    module = _module()
    result = module.plan_canary_effect()
    assert result["status"] == "DRY_RUN_NO_HTTP_NO_WRITE"
    assert result["target_trade_date"] == "20260925"
    assert result["manager_state_root"] == "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research"
    assert result["durable_owner_write_paths"] == [
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plan_runs/20260925/latest.json",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plan_runs/20260925/<owner-run-id>.json",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plans/20260925/latest.json",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plans/20260925/<owner-run-id>.json",
    ]
    assert result["transport"].startswith("ASGI in-process to exact immutable API app")


@pytest.mark.parametrize("date,state", [
    ("20261008", Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")),
    ("20260925", Path("/tmp/not-formal-manager-state")),
])
def test_plan_canary_dry_run_rejects_other_date_or_state(date, state):
    with pytest.raises(ValueError, match="D1_PLAN_CANARY_TARGET_OR_STATE_NOT_AUTHORIZED"):
        _module().plan_canary_effect(target_trade_date=date, manager_state_root=state)


def test_candidate_copy_excludes_only_runtime_test_cache_and_preserves_app_bytes(tmp_path):
    module = _module()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "package").mkdir(parents=True)
    (source / "package" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "package" / "__pycache__").mkdir()
    (source / "package" / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"cache")
    (source / ".pytest_cache").mkdir()
    (source / ".pytest_cache" / "lastfailed").write_text("scratch", encoding="utf-8")
    module._tree_without_cache(source, destination)
    assert (destination / "package" / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (destination / "package" / "__pycache__").exists()
    assert not (destination / ".pytest_cache").exists()


def test_final3_inputs_are_read_and_inventory_verified_without_writes():
    module = _module()
    for name in ("api_app", "scheduler_app"):
        manifest_path, manifest = module._final3_manifest(module.FINAL3_ROOT, name)
        assert manifest_path.name == "release-manifest.c1-final3.json"
        assert manifest["status"] == "CANDIDATE_NOT_ACTIVATED"


def test_final3_plus_d1_overlay_plan_pins_each_reviewed_source_and_receipt():
    module = _module()
    files, plan = module._reviewed_api_overlay_plan(
        module.FINAL3_ROOT / "release/api_app", module.APP_ROOT)
    expected = {
        "ops/run_manager_daily_announcement.py": "bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee",
        "ops/manager_announcement_body_batch.py": "7e37ed7e904d80c135a51bdff1aaa95aec02012eecfcfdc8a1770fa31297cbdb",
        "v4/manager_research/announcement_analysis.py": "21eb0cf37bfa6f3332f17ca7825a69eaa5bf9082b33d2e3de2d293e8bc3f0685",
        "v4/manager_research/workspace_announcements.py": "60839e20df9b61be04629481752ab3072a1088d229c87980e83059b590548e50",
        "infrastructure/scheduling/manager_announcement_supervisor.py": "bb7f4d40a5cda21c2deb215c2f51edfaa36da9f14d79d3d01987d13b7161b8ee",
        "apps/api/v35_api/manager_research_router.py": "18b718fa67bb74937f885f47e1ab587bc4bf7be3ce612b3d0731ce05eac7be8c",
        "docs/manager_daily_research.md": "84763ac3e271d749154a8980b1547231e1ed496fc80d861a7ef6d30ad8482d78",
    }
    assert set(files) == set(expected)
    for path, digest in expected.items():
        assert module.sha(files[path]) == digest
        assert plan["files"][path]["result_sha256"] == digest
    assert len(plan["review_receipts"]) == 4
    assert all(item["review_status"] == "PASS" for item in plan["review_receipts"].values())


def test_final3_router_keeps_import_route_and_changes_only_refresh_hunk():
    module = _module()
    files, _ = module._reviewed_api_overlay_plan(
        module.FINAL3_ROOT / "release/api_app", module.APP_ROOT)
    router = files["apps/api/v35_api/manager_research_router.py"]
    base = (module.FINAL3_ROOT / "release/api_app/apps/api/v35_api/manager_research_router.py").read_bytes()
    reviewed = (module.APP_ROOT / "apps/api/v35_api/manager_research_router.py").read_bytes()
    marker = b'    @router.post("/workspace/refresh")'
    base_block, base_start, base_end = module._route_block(base, marker)
    refreshed_block, _, _ = module._route_block(reviewed, marker)
    result_block, result_start, result_end = module._route_block(router, marker)
    assert module.sha(base_block) == module.ROUTER_BASE_REFRESH_SHA256
    assert module.sha(refreshed_block) == module.ROUTER_REVIEWED_REFRESH_SHA256
    assert module.sha(result_block) == module.ROUTER_REVIEWED_REFRESH_SHA256
    assert router[:result_start] == base[:base_start]
    assert router[result_end:] == base[base_end:]
    import_block, _, _ = module._route_block(
        router, b'@router.post("/announcements/analysis/import")',
        b'@router.post("/announcements/refresh")')
    assert module.sha(import_block) == module.ROUTER_REVIEWED_IMPORT_SHA256
    assert module.sha(router) == module.ROUTER_REVIEWED_RESULT_SHA256


def test_staged_r2_plists_share_disabled_binding_and_exact_split_roots():
    module = _module()
    config = module.CONFIG_ROOT
    receipt_path = config / "manager_daily_chain_c1_release_receipt.final-d1-r2.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "CANDIDATE_STAGED_NOT_ACTIVATED"
    assert receipt["launchctl_called"] is False
    assert receipt["rollback"]["active_api_plist_sha256"] == receipt["source_api_plist"]["sha256"]
    assert receipt["rollback"]["active_scheduler_plist_sha256"] == receipt["source_scheduler_plist"]["sha256"]
    binding_path = Path(receipt["shared_binding"]["path"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    assert binding["enabled"] is False
    assert binding["plan_material_refresh_only"] is False
    assert binding["announcement_collection_enabled"] is False
    assert binding["app_root"] == str(module.API_RELEASE_ROOT / "app")
    assert binding["manager_state_root"] == str(module.FORMAL_MANAGER_STATE)
    assert binding["research_only"] is True
    assert binding["production_allowed"] is False
    assert binding["buy_gate_updated"] is False
    assert binding["orders_sent"] is False
    assert binding["announcement_execution_owner"]["execution_owner"] == "HEARTBEAT"
    assert binding["announcement_execution_owner"]["ownership_status"] == "HEARTBEAT_OWNED"
    assert binding["announcement_execution_owner"]["scheduler_hook_enabled"] is False

    api_plist = plistlib.loads(Path(receipt["candidate_api"]["staged_plist"]).read_bytes())
    scheduler_plist = plistlib.loads(Path(receipt["candidate_scheduler"]["staged_plist"]).read_bytes())
    from ops.prepare_api_only_cutover import extract_environment
    api_env = extract_environment(api_plist)
    scheduler_env = extract_environment(scheduler_plist)
    assert api_env["V35_APP_ROOT"] == str(module.API_RELEASE_ROOT / "app")
    assert scheduler_env["V35_APP_ROOT"] == str(module.SCHEDULER_RELEASE_ROOT / "app")
    assert api_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(binding_path)
    assert scheduler_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(binding_path)
    assert api_env["V35_RELEASE_MANIFEST_SHA256"] == receipt["candidate_api"]["manifest_sha256"]
    assert scheduler_env["V35_RELEASE_MANIFEST_SHA256"] == receipt["candidate_scheduler"]["manifest_sha256"]
    assert module.API_RELEASE_ROOT != module.SCHEDULER_RELEASE_ROOT
    assert not (module.TASK_ROOT / "plan_canary_runs/20260925/execution-01").exists()


def test_r2_app_trees_differ_from_final3_only_at_reviewed_overlay_paths():
    module = _module()
    from ops.build_release_candidate import inventory_tree

    api_base = module.FINAL3_ROOT / "release/api_app"
    api_target = module.API_RELEASE_ROOT / "app"
    scheduler_base = module.FINAL3_ROOT / "release/scheduler_app"
    scheduler_target = module.SCHEDULER_RELEASE_ROOT / "app"

    def files(root: Path) -> dict[str, str]:
        return {item["path"]: item["sha256"] for item in inventory_tree(root)
                if item.get("kind") == "file"}

    api_before, api_after = files(api_base), files(api_target)
    scheduler_before, scheduler_after = files(scheduler_base), files(scheduler_target)
    assert set(api_before) == set(api_after)
    assert set(scheduler_before) == set(scheduler_after)
    api_changed = {path for path in api_before if api_before[path] != api_after[path]}
    scheduler_changed = {path for path in scheduler_before if scheduler_before[path] != scheduler_after[path]}
    expected_api = set(module.REVIEWED_FULL_FILE_OVERLAYS) - {"ops/run_v35_macos_scheduler_daemon.py"}
    expected_api.update({"apps/api/v35_api/manager_research_router.py", "docs/manager_daily_research.md"})
    assert api_changed == expected_api
    assert scheduler_changed == {"ops/run_v35_macos_scheduler_daemon.py"}
    assert all(not path.startswith("stage_center/") for path in api_changed)
    for path in api_before:
        if path.startswith("stage_center/"):
            assert api_before[path] == api_after[path]


def test_read_only_release_mode_does_not_follow_symlinks(tmp_path):
    module = _module()
    root = tmp_path / "release"
    app = root / "app"
    app.mkdir(parents=True)
    file_path = app / "source.py"
    file_path.write_text("x=1\n", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    target = external / "state.json"
    target.write_text("{}", encoding="utf-8")
    link = app / "external-state"
    link.symlink_to(external, target_is_directory=True)
    module._make_tree_read_only(root)
    assert not (file_path.stat().st_mode & stat.S_IWUSR)
    assert link.is_symlink()
    assert target.stat().st_mode & stat.S_IWUSR
