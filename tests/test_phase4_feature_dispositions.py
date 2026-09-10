from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "contracts" / "migration" / "phase4_feature_disposition_v1.json"
BASELINE = REPO / "contracts" / "migration" / "v3_graph_baseline_v2.json"
INVENTORY = REPO / "contracts" / "migration" / "v35_replacement_inventory_v2.json"
EXPECTED_FEATURES = {
    "navigation.dates",
    "preselection.pools",
    "stage.workbench",
    "stage.model_review_close",
    "review.close",
    "research.desk",
    "runtime.status",
    "tasks.registry",
    "orphan.loadConsole",
    "orphan.loadMorningLane",
    "orphan.loadWechatLane",
}
ORPHANS = {
    "orphan.loadConsole": "loadConsole",
    "orphan.loadMorningLane": "loadMorningLane",
    "orphan.loadWechatLane": "loadWechatLane",
}
LEGACY_ROOT = (
    REPO
    / ".runtime"
    / "evidence"
    / "phase0"
    / "frozen_inputs_graph_baseline_v2_20260801T010442"
    / "legacy_sources"
    / "30_runtime"
    / "opening_advisor_8771"
)
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase4_disposition_contract_is_graph_bound_and_self_hashed() -> None:
    contract = _load(CONTRACT)
    baseline = _load(BASELINE)
    inventory = _load(INVENTORY)
    claimed_hash = contract.pop("semantic_hash")
    actual_hash = hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert claimed_hash == actual_hash
    assert contract["schema_version"] == "v3_5.phase4_feature_disposition.v1"
    assert contract["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    assert contract["inventory_v2_semantic_hash"] == inventory["inventory_semantic_hash"]
    assert contract["safety"] == SAFETY

    records = contract["features"]
    assert {record["feature_id"] for record in records} == EXPECTED_FEATURES
    assert [record["feature_id"] for record in records] == sorted(EXPECTED_FEATURES)
    registry = set(baseline["graph_node_registry"]["ids"])
    inventory_by_feature = {
        record["feature_id"]: record for record in inventory["features"]
    }
    for record in records:
        feature_id = record["feature_id"]
        assert record["inventory_graph_node_count"] == len(
            inventory_by_feature[feature_id]["graph_node_ids"]
        )
        assert record["inventory_source_gaps"] == inventory_by_feature[feature_id][
            "source_gaps"
        ]
        assert set(record["evidence_graph_node_ids"]) <= registry
        inventory_nodes = set(inventory_by_feature[feature_id]["graph_node_ids"])
        if inventory_nodes:
            assert set(record["evidence_graph_node_ids"]) <= inventory_nodes
        elif record["evidence_graph_node_ids"]:
            assert "GRAPH_NODE_NOT_RECONCILED" in record["inventory_source_gaps"]
            assert all(
                node_id.startswith(("api:", "api_ref:"))
                for node_id in record["evidence_graph_node_ids"]
            )
        assert record["proposed_disposition"] in {"KEEP", "COMPAT", "REMOVE"}
        assert record["safety"] == SAFETY
        assert record["replacement_paths"] == sorted(
            set(record["replacement_paths"])
        )
        assert record["test_paths"] == sorted(set(record["test_paths"]))
        for relative in [*record["replacement_paths"], *record["test_paths"]]:
            assert (REPO / relative).is_file(), (feature_id, relative)
        for reference in record["parity_receipts"]:
            path = REPO / reference["path"]
            assert path.is_file(), (feature_id, reference["path"])
            receipt = _load(path)
            receipt_hash = receipt.pop("receipt_semantic_hash")
            actual_receipt_hash = hashlib.sha256(
                json.dumps(
                    receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            assert receipt_hash == reference["semantic_hash"] == actual_receipt_hash
            assert receipt["feature_id"] == feature_id
            assert receipt["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
            assert receipt["verdict"] == "CANNOT_CONFIRM"
            assert receipt["safety"] == SAFETY
            assert set(receipt["graph_node_ids"]) & inventory_nodes


def test_phase4_keep_compat_and_remove_have_fail_closed_statuses() -> None:
    records = {record["feature_id"]: record for record in _load(CONTRACT)["features"]}
    for record in records.values():
        disposition = record["proposed_disposition"]
        if disposition == "KEEP":
            assert record["reachability"] == "REACHABLE"
            assert record["decision_status"] == "VERIFIED_IN_V35_SCOPE"
            assert record["replacement_paths"]
            assert record["test_paths"]
        elif disposition == "COMPAT":
            assert record["decision_status"] == "CANNOT_CONFIRM_FULL_V3_EQUIVALENCE"
            assert record["cannot_confirm"]
            assert record["replacement_paths"]
        else:
            assert record["reachability"] == "UNREACHABLE"
            assert record["decision_status"] == "USER_APPROVAL_REQUIRED"
            assert record["replacement_paths"] == []
            assert "NO_REACHABLE_CALL_FROM_LOAD_ACTIVE_VIEW" in record["cannot_confirm"]


def test_phase4_optional_pool_ownership_and_live_evidence_are_current() -> None:
    records = {record["feature_id"]: record for record in _load(CONTRACT)["features"]}
    navigation = records["navigation.dates"]
    preselection = records["preselection.pools"]
    research = records["research.desk"]
    tasks = records["tasks.registry"]

    optional_paths = {
        "infrastructure/preselection_overlay_store.py",
        "ops/import_preselection_overlays.py",
    }
    optional_tests = {
        "tests/test_phase2_preselection_optional_pools_remediation_receipt.py",
        "tests/test_preselection_optional_pools.py",
    }
    assert optional_paths <= set(preselection["replacement_paths"])
    assert optional_paths.isdisjoint(navigation["replacement_paths"])
    assert optional_tests <= set(preselection["test_paths"])
    assert optional_tests.isdisjoint(navigation["test_paths"])

    stale_runtime_gaps = {
        "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE",
        "V35_LIVE_SERVICE_NOT_RELOADED",
    }
    assert stale_runtime_gaps.isdisjoint(preselection["cannot_confirm"])
    assert stale_runtime_gaps.isdisjoint(research["cannot_confirm"])
    assert "BUSINESS_PARITY_SOURCE_SHA_MISMATCH" in preselection["cannot_confirm"]
    assert "LIVE_HOURLY_RESEARCH_PRODUCER_NOT_STARTED" in research["cannot_confirm"]
    assert "FULL_35_TASK_IDENTITY_MAPPING_DEFERRED_TO_PHASE_5" not in tasks[
        "cannot_confirm"
    ]
    assert "DISABLED_RUNTIME_TASKS_HAVE_NO_EXECUTION_RECEIPTS" in tasks[
        "cannot_confirm"
    ]


def test_phase4_legacy_orphan_reachability_is_source_specific() -> None:
    records = {record["feature_id"]: record for record in _load(CONTRACT)["features"]}
    runtime_roots = [
        REPO / "apps" / "api",
        REPO / "apps" / "web" / "src",
        REPO / "domains",
        REPO / "infrastructure",
    ]
    for feature_id, symbol in ORPHANS.items():
        hits: list[str] = []
        for root in runtime_roots:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".ts", ".vue"}:
                    continue
                if symbol in path.read_text(encoding="utf-8"):
                    hits.append(path.relative_to(REPO).as_posix())
        assert hits == [], (feature_id, hits)

    v3_path = LEGACY_ROOT / "frontend" / "fupan_dashboard_v3.html"
    v4_path = LEGACY_ROOT / "frontend" / "fupan_dashboard_v4.html"
    main_path = LEGACY_ROOT / "backend" / "main.py"
    v3_text = v3_path.read_text(encoding="utf-8")
    v4_text = v4_path.read_text(encoding="utf-8")
    main_text = main_path.read_text(encoding="utf-8")

    console = records["orphan.loadConsole"]
    assert console["proposed_disposition"] == "COMPAT"
    assert console["reachability"] == "LEGACY_V4_REACHABLE"
    assert len(re.findall(r"\bloadConsole\s*\(", v3_text)) == 1
    assert len(re.findall(r"\bloadConsole\s*\(", v4_text)) == 3
    assert 'app.get(V4_DASHBOARD_PATH' in main_text
    reachability = console["legacy_reachability"]
    assert reachability["source_path"] == (
        "30_runtime/opening_advisor_8771/frontend/fupan_dashboard_v4.html"
    )
    assert reachability["route_source_path"] == (
        "30_runtime/opening_advisor_8771/backend/main.py"
    )
    assert reachability["definition_count"] == 1
    assert reachability["reachable_call_count"] == 2
    assert hashlib.sha256(v4_path.read_bytes()).hexdigest() == reachability[
        "source_sha256"
    ]
    assert hashlib.sha256(main_path.read_bytes()).hexdigest() == reachability[
        "route_source_sha256"
    ]

    for feature_id, symbol in {
        "orphan.loadMorningLane": "loadMorningLane",
        "orphan.loadWechatLane": "loadWechatLane",
    }.items():
        record = records[feature_id]
        assert record["proposed_disposition"] == "REMOVE"
        assert record["reachability"] == "UNREACHABLE"
        assert len(re.findall(rf"\b{symbol}\s*\(", v3_text)) == 1
        dead_symbol = record["legacy_dead_symbol"]
        assert dead_symbol["source_path"] == (
            "30_runtime/opening_advisor_8771/frontend/fupan_dashboard_v3.html"
        )
        assert dead_symbol["definition_count"] == 1
        assert dead_symbol["reachable_call_count"] == 0
        assert hashlib.sha256(v3_path.read_bytes()).hexdigest() == dead_symbol[
            "source_sha256"
        ]
