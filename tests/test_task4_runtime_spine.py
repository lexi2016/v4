from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs/evidence/task4-runtime-spine-20260802.json"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sources() -> dict[str, dict]:
    return {
        "v35_replacement_inventory_v4": _load(
            REPO / "contracts/migration/v35_replacement_inventory_v4.json"
        ),
        "task2_graph_lineage": _load(
            REPO / "docs/evidence/task2-graph-lineage-20260802.json"
        ),
        "runtime_workloads": _load(REPO / "contracts/runtime_workloads.json"),
        "phase5_runtime_governance_audit": _load(
            REPO / "contracts/migration/phase5_runtime_governance_audit_v1.json"
        ),
    }


def _assert_evidence_bound(
    evidence: dict, sources: dict[str, dict]
) -> None:
    claimed = evidence.pop("semantic_hash", None)
    assert claimed == _semantic_hash(evidence), "top-level evidence hash mismatch"
    assert evidence["schema_version"] == "v3_5.task4_runtime_spine.v1"
    assert evidence["status"] == "PASS"
    assert evidence["engineering_runtime_spine"] == "PASS"
    assert evidence["business_producer_parity"] is False
    assert evidence["retained_gaps"] == {
        "business_producer_parity": "CANNOT_CONFIRM",
        "deployed": False,
        "ui_business_readiness": "CANNOT_CONFIRM",
    }
    assert evidence["safety"] == SAFETY

    for name, binding in evidence["bindings"].items():
        path = REPO / binding["path"]
        source = sources[name]
        assert binding["raw_sha256"] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest(), "raw binding mismatch"
        assert binding["semantic_sha256"] == _semantic_hash(
            source
        ), "semantic binding mismatch"
        if "claimed_semantic_hash" in binding:
            assert binding["claimed_semantic_hash"] == source["semantic_hash"]
        assert source["safety"] == SAFETY, "unsafe source safety boundary"

    catalog = sources["runtime_workloads"]
    for registration in catalog["task_registrations"]:
        assert registration["enabled"] is False
        assert registration["execution_allowed"] is False
        assert registration["safety"] == SAFETY
        assert "command" not in registration, "executable placeholder command"
        assert "owner_id" not in registration, "executable placeholder owner"


def test_task4_runtime_spine_evidence_is_bound_and_engineering_only() -> None:
    _assert_evidence_bound(_load(EVIDENCE), _sources())


@pytest.mark.parametrize(
    ("mutate", "expected_guard"),
    [
        (
            lambda evidence, sources: evidence["bindings"][
                "runtime_workloads"
            ].update({"raw_sha256": "0" * 64}),
            "raw binding mismatch",
        ),
        (
            lambda evidence, sources: (
                sources["runtime_workloads"]["safety"].update(
                    {"production_allowed": True}
                ),
                evidence["bindings"]["runtime_workloads"].update(
                    {"semantic_sha256": _semantic_hash(sources["runtime_workloads"])}
                ),
            ),
            "unsafe source safety boundary",
        ),
        (
            lambda evidence, sources: (
                sources["runtime_workloads"]["task_registrations"][0].update(
                    {"command": ["python", "-m", "placeholder"]}
                ),
                evidence["bindings"]["runtime_workloads"].update(
                    {"semantic_sha256": _semantic_hash(sources["runtime_workloads"])}
                ),
            ),
            "executable placeholder command",
        ),
    ],
    ids=["binding-tamper", "unsafe", "executable-placeholder"],
)
def test_task4_rejects_critical_tamper_unsafe_and_placeholder(
    mutate, expected_guard: str,
) -> None:
    evidence = _load(EVIDENCE)
    sources = deepcopy(_sources())
    mutate(evidence, sources)
    evidence["semantic_hash"] = _semantic_hash(
        {key: value for key, value in evidence.items() if key != "semantic_hash"}
    )

    with pytest.raises(AssertionError, match=expected_guard):
        _assert_evidence_bound(evidence, sources)


def test_task4_runtime_spine_counts_and_set_differences_are_exact() -> None:
    evidence = _load(EVIDENCE)
    sources = _sources()
    audit = sources["phase5_runtime_governance_audit"]
    catalog = sources["runtime_workloads"]

    assert evidence["counts"] == {
        "actual_windows_tasks": 36,
        "canonical_task_specs": 35,
        "runtime_inventory_records": 69,
        "timeline_nodes": 34,
    }
    assert audit["counts"] == {
        "actual_windows_tasks": 36,
        "canonical_task_specs": 35,
        "catalog_workloads": 5,
        "entrypoints": 90,
        "inventory_runtime_tasks": 69,
        "launcher_files": 33,
        "task_registrations": 34,
        "timeline_nodes": 34,
    }
    assert audit["extra_actual_windows_tasks"] == [
        "OpeningAdvisorV3_RuntimeGraphCollector"
    ]
    assert audit["missing_actual_windows_tasks"] == []
    assert audit["missing_launcher_tasks"] == [
        "OpeningAdvisorV3_1605_HKModelReview",
        "OpeningAdvisorV3_2130_WQ101Prewarm",
    ]
    assert audit["enabled_available_runner_workload_ids"] == ["hourly_research"]
    assert evidence["runnable_canonical_workload"] == {
        "count": 1,
        "ids": ["hourly_research"],
    }
    assert audit["unregistered_unresolved_task_ids"] == []

    identity_sets = {
        "canonical_task_specs": [
            row["graph_task_spec_id"] for row in audit["canonical_tasks"]
        ],
        "actual_windows_tasks": [
            task_id
            for row in audit["canonical_tasks"]
            for task_id in row["actual_windows_task_ids"]
        ]
        + audit["extra_actual_windows_tasks"],
        "timeline_nodes": audit["timeline_node_ids"],
        "runtime_inventory_records": [
            f"{row['record_type']}:"
            f"{row['task_name'] if row['record_type'] == 'windows_task' else row['node_id']}"
            for row in sources["v35_replacement_inventory_v4"]["runtime_tasks"]
        ],
    }
    for identity, values in identity_sets.items():
        assert len(values) == len(set(values)) == evidence["counts"][identity]
        assert evidence["identity_set_sha256"][identity] == _semantic_hash(
            sorted(values)
        )

    disabled = evidence["disabled_graph_task_registrations"]
    assert disabled["count"] == len(disabled["ids"]) == len(set(disabled["ids"])) == 34
    assert disabled["ids_semantic_sha256"] == _semantic_hash(disabled["ids"])
    assert disabled["enabled"] is False
    assert disabled["execution_allowed"] is False
    assert disabled["producer_ready"] is False
    assert disabled["ids"] == audit["registered_cannot_confirm_task_ids"]
    assert disabled["ids"] == [
        registration["legacy_task_id"]
        for registration in catalog["task_registrations"]
    ]
