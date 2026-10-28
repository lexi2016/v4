"""Focused regressions for manager plan identity reuse; no owner or live store reads."""
from copy import deepcopy
from pathlib import Path
from contextlib import nullcontext

from v4.manager_research.workspace_identity import (
    INPUT_IDENTITY_SCHEMA,
    identity_component,
    semantic_digest,
)
from v4.manager_research import workspace as workspace_module


DATE = "20260930"
SEMANTIC_VERSION = "20260921.manager-semantic.r3.v1"
BINDINGS = {"plan_date": DATE, "selection_date": DATE, "announcement_date": DATE}


def verified_registry_binding(**overrides):
    payload = "a" * 64
    value = {
        "source_id": "V35_RESEARCH_DATA_ROOT",
        "status": "VERIFIED",
        "manifest_path": "manifest.json",
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "source_root": "/research/readonly",
        "source_date": DATE,
        "mode": "LIVE",
        "slot": "0930",
        "payload_path": f"research/hourly/live/{DATE}/0930.json",
        "receipt_path": f"receipts/research/hourly/live/{DATE}/0930.json",
        "payload_sha256": payload,
        "receipt_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "manifest_entry_sha256": payload,
        "source_row": {"code": "HK.00001", "value": 1},
    }
    value.update(overrides)
    return value


def workspace_with_binding(binding):
    source_input = {"input_bindings": [binding]}
    source_component = identity_component(source_input)
    components = {
        "source_material": source_component,
        "date_bindings": identity_component(BINDINGS),
    }
    identity = semantic_digest({
        "semantic_version": SEMANTIC_VERSION,
        "date_bindings": BINDINGS,
        "components": {key: value["sha256"] for key, value in components.items()},
    })
    return {
        "target_trade_date": DATE,
        "input_identity": identity,
        "input_identity_schema": INPUT_IDENTITY_SCHEMA,
        "input_identity_components": components,
        "date_bindings": dict(BINDINGS),
        "semantic_version": SEMANTIC_VERSION,
        "plan_context": {"research_cutoff": "2026-09-30T09:29:00+08:00"},
        "stocks": [], "lanes": [], "gaps": [], "runtime_gaps": [],
        "run_accounting": {}, "continuity_gap": {}, "market_screen": {},
        "market_screen_evidence": {}, "owner_chain": {},
        "announcement_review": {}, "announcement_observation": {},
        "us_market_attention": {}, "research_attention": {},
        "stage_read_timing": {}, "repair_contract": {}, "selection_diagnostics": {},
    }


class ReadOnlyStore:
    root = Path("/NOT_LIVE/manager-repair-test")

    def __init__(self):
        self.rows = {}

    def _read(self, _path):
        from copy import deepcopy
        return deepcopy(self.rows.get(str(_path)))

    def put(self, relative, value):
        from copy import deepcopy
        self.rows[str(self.root / relative)] = deepcopy(value)

    def _transaction(self, *_args):
        return nullcontext()


def saved_plan(workspace, store):
    run_id = "a" * 32
    product = {
        "schema_version": workspace_module.PLAN_SCHEMA,
        "target_trade_date": DATE,
        "run_id": run_id,
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "execution_kind": "MANUAL_REFRESH",
        "input_identity": workspace["input_identity"],
        "workspace": deepcopy(workspace),
        "generated_at": "2026-09-30T09:28:59+08:00",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    product["sha256"] = workspace_module.digest(product)
    attempt = workspace_module.seal_attempt({
        "schema_version": workspace_module.ATTEMPT_SCHEMA,
        "target_trade_date": DATE,
        "run_id": run_id,
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "execution_kind": "MANUAL_REFRESH",
        "state": "PARTIAL",
        "started_at": "2026-09-30T09:28:58+08:00",
        "finished_at": "2026-09-30T09:28:59+08:00",
        "input_identity": workspace["input_identity"],
        "failure_reasons": ["SYNTHETIC_INCOMPLETE_INPUT"],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    })
    store.put(f"workspace_plan_runs/{DATE}/latest.json", attempt)
    store.put(f"workspace_plan_runs/{DATE}/{run_id}.json", attempt)
    return product


def test_verified_manifest_registry_fingerprint_does_not_change_semantic_identity():
    before = verified_registry_binding()
    after = {**before, "manifest_sha256": "e" * 64}
    assert semantic_digest({"input_bindings": [before]}) == semantic_digest({"input_bindings": [after]})
    before_component = identity_component({"input_bindings": [before]})
    after_component = identity_component({"input_bindings": [after]})
    assert before_component["sha256"] == after_component["sha256"]
    assert before_component["sources"][0]["manifest_sha256"] != after_component["sources"][0]["manifest_sha256"]


def test_verified_manifest_only_change_keeps_saved_plan_consumed(monkeypatch):
    before = workspace_with_binding(verified_registry_binding())
    after = workspace_with_binding(verified_registry_binding(manifest_sha256="e" * 64))
    store = ReadOnlyStore()
    saved = saved_plan(before, store)
    monkeypatch.setattr(workspace_module, "_read_plan", lambda *_args: saved)

    result = workspace_module._readback_plan(store, DATE, after)

    assert result["plan_product"]["status"] == "CURRENT"
    assert result["plan_product"]["consumed"] is True
    assert result["plan_product"]["input_identity_diagnostics"]["status"] == "MATCH"


def test_payload_or_source_row_change_still_rejects_saved_plan(monkeypatch):
    before_binding = verified_registry_binding()
    current_binding = verified_registry_binding(payload_sha256="f" * 64,
        manifest_entry_sha256="f" * 64)
    before = workspace_with_binding(before_binding)
    current = workspace_with_binding(current_binding)
    store = ReadOnlyStore()
    saved = saved_plan(before, store)
    monkeypatch.setattr(workspace_module, "_read_plan", lambda *_args: saved)

    result = workspace_module._readback_plan(store, DATE, current)

    assert result["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert result["plan_product"]["consumed"] is False
    diagnostics = result["plan_product"]["input_identity_diagnostics"]
    assert diagnostics["status"] == "CHANGED"
    assert "source_material" in {row["component"] for row in diagnostics["changed_components"]}


def test_unverified_binding_manifest_change_remains_semantic():
    before = verified_registry_binding(status="UNVERIFIED")
    after = {**before, "manifest_sha256": "e" * 64}
    assert semantic_digest({"input_bindings": [before]}) != semantic_digest({"input_bindings": [after]})


def test_legacy_saved_plan_without_identity_components_fails_closed(monkeypatch):
    current = workspace_with_binding(verified_registry_binding())
    legacy = deepcopy(current)
    legacy.pop("input_identity_schema")
    legacy.pop("input_identity_components")
    store = ReadOnlyStore()
    saved = saved_plan(legacy, store)
    monkeypatch.setattr(workspace_module, "_read_plan", lambda *_args: saved)

    result = workspace_module._readback_plan(store, DATE, current)

    assert result["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert result["plan_product"]["consumed"] is False
    diagnostics = result["plan_product"]["input_identity_diagnostics"]
    assert diagnostics["status"] == "CANNOT_CONFIRM"
    assert diagnostics["reason"] == "SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED"


def test_source_row_remains_in_semantic_identity():
    before = verified_registry_binding()
    after = deepcopy(before)
    after["source_row"]["value"] = 2
    assert semantic_digest({"input_bindings": [before]}) != semantic_digest({"input_bindings": [after]})

