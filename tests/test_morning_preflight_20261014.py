import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from infrastructure.scheduling._executor_registry_parts.research_jobs import (
    _refresh_opening_research_pool,
)


@pytest.mark.parametrize("slot,mode,status,expected", [
    ("0830", DispatchMode.LIVE, "SUCCEEDED", True),
    ("0900", DispatchMode.LIVE, "SUCCEEDED", True),
    ("1000", DispatchMode.LIVE, "SUCCEEDED", False),
    ("0830", DispatchMode.LIVE, "FAILED", False),
])
def test_refresh_only_successful_premarket_research(slot, mode, status, expected):
    calls = []
    registry = SimpleNamespace(_research_preselection_refresh=lambda req:
        calls.append(req.business_date) or {"status": "SUCCEEDED"})
    request = DispatchRequest("20261014", "20261014", "20261014", slot, mode)
    result = _refresh_opening_research_pool(registry, request, {"status": status})
    assert calls == (["20261014"] if expected else [])
    assert ("preselection_refresh" in result) is expected


def test_refresh_failure_is_visible_without_rewriting_research_result():
    registry = SimpleNamespace(_research_preselection_refresh=lambda req: {"status": "FAILED"})
    request = SimpleNamespace(slot="0830", mode="LIVE")
    original = {"status": "SUCCEEDED", "archive_sha": "a" * 64}
    result = _refresh_opening_research_pool(registry, request, original)
    assert result["status"] == "FAILED"
    assert result["archive_sha"] == original["archive_sha"]
    assert original["status"] == "SUCCEEDED"


def test_reused_main_pool_still_resolves_panel_and_builds_review_lanes(tmp_path, monkeypatch):
    import infrastructure.scheduling.executor_registry as module
    shared = tmp_path / "package"
    (shared / "scripts").mkdir(parents=True)
    (shared / "scripts/capture_public_fupan.py").write_text("")
    panel = tmp_path / "exact-20261013.parquet"
    panel.write_bytes(b"routing-only-fixture")
    resolved, calls = [], []
    def resolve(root, date, **kwargs):
        resolved.append(date)
        return panel
    monkeypatch.setattr(module, "resolve_selector_panel", resolve)
    registry = FixedExecutorRegistry(data_root=tmp_path / "data",
        shared_data_root=tmp_path / "store", shared_package_root=shared,
        hk_universe_root=tmp_path / "store", selector_data_root=tmp_path,
        preselection_input_root=tmp_path / "inputs", repo_root=Path.cwd(),
        stage_selection_root=tmp_path / "stage", runner=lambda *a, **k: None)
    registry._verified_preselection_source = lambda **kwargs: ({"status": "READY"}, "")
    # HK helper is module-level; make its authoritative reader return the same reuse receipt.
    from infrastructure.scheduling._executor_registry_parts import preselection as parts
    monkeypatch.setattr(parts, "_FixedExecutorRegistry__verified_preselection_source_body",
                        lambda *a, **k: ({"status": "READY"}, ""))
    def run(name, args, **kwargs):
        calls.append((name, args))
        payload = {"formal_pool_gate": {"status": "READY", "required": {
            "a_d1_premarket_pool": {"status": "READY"},
            "hkconnect_d1_top100": {"status": "READY"}}}}
        return {"status": "SUCCEEDED", "exit_code": 0, "stderr": "",
                "stdout": json.dumps(payload)}
    registry._run = run
    request = DispatchRequest("20261013", "20261013", "20261014", "1800", DispatchMode.LIVE)
    registry._preselection_pools(request)
    assert resolved == ["20261013"]
    names = [name for name, _ in calls]
    assert "ops.materialize_shared_v192_preselection" not in names
    args = next(args for name, args in calls if name == "ops.materialize_d1_review_lanes")
    assert args[args.index("--selector") + 1] == str(panel)
    assert args[args.index("--target-date") + 1] == "20261014"
