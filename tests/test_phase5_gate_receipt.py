from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "contracts/migration/phase5_runtime_governance_audit_v1.json"
CATALOG = REPO / "contracts/runtime_workloads.json"
RECEIPT = REPO / "docs/evidence/phase5-gate-receipt-20260801.json"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_hash(payload: dict, excluded_field: str) -> str:
    body = {key: value for key, value in payload.items() if key != excluded_field}
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_phase5_gate_receipt_is_bound_to_the_passing_audit() -> None:
    audit = _load(AUDIT)
    receipt = _load(RECEIPT)

    assert receipt["gate_semantic_hash"] == _semantic_hash(
        receipt, "gate_semantic_hash"
    )
    assert receipt["status"] == audit["status"] == "PASS"
    assert receipt["phase"] == "PHASE_5"
    assert receipt["next_phase"] == "PHASE_6"
    assert receipt["implementation_commit"] == "4ac6220"
    assert receipt["entrypoint_classification_commit"] == "714d5bf"
    assert receipt["audit_contract"] == (
        "contracts/migration/phase5_runtime_governance_audit_v1.json"
    )
    assert audit["blocking_gaps"] == []
    assert receipt["audit_semantic_hash"] == audit["semantic_hash"]
    assert receipt["audit_contract_raw_sha256"] == hashlib.sha256(
        AUDIT.read_bytes()
    ).hexdigest()
    assert receipt["input_raw_sha256"] == audit["input_raw_sha256"]
    assert receipt["input_raw_sha256"]["runtime_catalog"] == hashlib.sha256(
        CATALOG.read_bytes()
    ).hexdigest()
    expected_counts = {
        "actual_windows_tasks": audit["counts"]["actual_windows_tasks"],
        "canonical_task_specs": audit["counts"]["canonical_task_specs"],
        "catalog_workloads": audit["counts"]["catalog_workloads"],
        "task_registrations": audit["counts"]["task_registrations"],
        "timeline_nodes": audit["counts"]["timeline_nodes"],
        "launcher_files": audit["counts"]["launcher_files"],
        "runtime_inventory_records": audit["counts"][
            "inventory_runtime_tasks"
        ],
        "entrypoints": audit["counts"]["entrypoints"],
        "exact_catalog_tasks": audit["exact_catalog_task_count"],
        "registered_disabled_tasks": audit[
            "approved_task_registration_count"
        ],
        "exact_entrypoints": sum(
            row["mapping_status"] == "EXACT_CATALOG_IDENTITY"
            for row in audit["entrypoints"]
        ),
        "registered_entrypoints": len(
            audit["approved_registration_entrypoint_ids"]
        ),
        "owner_only_entrypoints": sum(
            row["mapping_status"] == "NON_SCHEDULED_OWNER_ONLY"
            for row in audit["entrypoints"]
        ),
        "unresolved_entrypoints": len(audit["unresolved_entrypoint_ids"]),
        "unexplained_entrypoints": len(audit["unexplained_entrypoint_ids"]),
        "enabled_runner_commands_available": len(
            audit["enabled_available_runner_workload_ids"]
        ),
        "blocking_gaps": len(audit["blocking_gaps"]),
    }
    assert receipt["counts"] == expected_counts
    assert audit["enabled_available_runner_workload_ids"] == [
        "hourly_research"
    ]
    assert receipt["approved_cannot_confirm"] == {
        "registered_task_count": 34,
        "disposition": "USER_APPROVED_DISABLED_CANNOT_CONFIRM",
        "execution_allowed": False,
        "extra_runtime_graph_collector_unchanged": True,
        "missing_launcher_tasks_unchanged": 2,
    }
    assert receipt["hourly_research_runner"] == {
        "workload_id": "hourly_research",
        "module": "ops.run_hourly_research",
        "input_contract": "FROZEN_BYTES_PLUS_SHA256",
        "point_in_time_cutoff_required": True,
        "mode_namespaces": ["LIVE", "REPLAY", "BACKFILL"],
        "latest_policy": "LIVE_ONLY_MONOTONIC",
        "missing_input_status": "NOT_MATERIALIZED",
        "legacy_v3_runtime_dependency": False,
    }
    assert receipt["validation"] == {
        "full_python": {"passed": 305, "failed": 0, "skipped": 1},
        "focused_phase5_runtime_research": {"passed": 80, "failed": 0},
        "reviewer_hourly_and_archive": {"passed": 25, "failed": 0},
        "reviewer": "PASS_P1_0_P2_0_P3_0",
        "frontend_frozen_phase5c": {
            "tests_passed": 24,
            "typecheck": "PASS",
            "build": "PASS",
            "source_commit": "88c4964",
            "current_slice_frontend_files_changed": False,
        },
        "commands": {
            "full_python": "python -m pytest -q",
            "focused_phase5_runtime_research": (
                "python -m pytest tests/test_hourly_research_runner.py "
                "tests/test_research_archive.py "
                "tests/test_runtime_workload_catalog.py "
                "tests/test_phase5_runtime_governance_audit.py "
                "tests/test_runtime_dispatcher.py "
                "tests/test_task_status_api.py -q"
            ),
            "gate_binding": (
                "python -m pytest tests/test_phase5_gate_receipt.py "
                "tests/test_phase5_runtime_governance_audit.py -q"
            ),
        },
    }
    assert receipt["claims"] == {
        "implemented": True,
        "tested": True,
        "integrated": True,
        "phase5_complete": True,
        "deployed": False,
        "ui_verified": False,
        "business_parity_verified": False,
    }
    assert receipt["mutations"] == {
        "legacy_v3_modified": False,
        "business_runners_executed": False,
        "windows_tasks_modified": False,
        "live_business_artifacts_created": False,
    }
    assert receipt["safety"] == audit["safety"] == SAFETY
    assert receipt["model_capability_routing"] == (
        "contracts/migration/model_capability_routing_v1.json"
    )
