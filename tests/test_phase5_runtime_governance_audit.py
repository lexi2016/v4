from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ops.migration.build_phase5_runtime_audit import (
    DEFAULT_OUTPUT,
    RUNTIME_EVIDENCE_OUTPUT,
    _allowed_output,
    _validated_output,
)
from ops.migration.runtime_governance import build_runtime_governance_audit
from ops.migration import runtime_governance as runtime_governance_module


REPO = Path(__file__).resolve().parents[1]
GRAPH = (
    REPO
    / ".runtime"
    / "evidence"
    / "phase0"
    / "v3_current_script_task_graph_20260801"
    / "v3_current_script_task_graph_20260801.json"
)
INVENTORY = REPO / "contracts" / "migration" / "v35_replacement_inventory_v2.json"
CATALOG = REPO / "contracts" / "runtime_workloads.json"
AUDIT_CONTRACT = (
    REPO
    / "contracts"
    / "migration"
    / "phase5_runtime_governance_audit_v1.json"
)
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(*, catalog_path: Path = CATALOG, repo_root: Path = REPO) -> dict:
    return build_runtime_governance_audit(
        graph_path=GRAPH,
        inventory_path=INVENTORY,
        catalog_path=catalog_path,
        repo_root=repo_root,
    )


def test_phase5_audit_counts_every_identity_and_fails_closed() -> None:
    audit = _build()

    assert audit["counts"] == {
        "actual_windows_tasks": 36,
        "canonical_task_specs": 35,
        "catalog_workloads": 5,
        "task_registrations": 34,
        "entrypoints": 90,
        "inventory_runtime_tasks": 69,
        "launcher_files": 33,
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
    assert audit["exact_catalog_task_count"] == 1
    assert audit["unresolved_catalog_task_count"] == 34
    assert audit["approved_task_registration_count"] == 34
    assert audit["unregistered_unresolved_task_ids"] == []
    assert audit["cross_day_graph_node_ids"] == [
        "tomorrow_pool_2005",
        "v3_next_opening_pool_guard_2100",
    ]
    assert audit["cross_day_task_ids"] == [
        "OpeningAdvisorV3_2005_TomorrowPool",
        "OpeningAdvisorV3_2108_FupanGapAndGuard",
    ]
    assert audit["cross_day_tasks_without_explicit_target_role"] == (
        audit["cross_day_task_ids"]
    )
    assert len(audit["tasks_missing_explicit_runtime_roles"]) == 34
    assert audit["dispatch_request_supports_target_date"] is True
    assert audit["enabled_workload_ids"] == ["hourly_research"]
    assert audit["enabled_available_runner_workload_ids"] == [
        "hourly_research"
    ]
    assert audit["runner_module_present_workload_ids"] == [
        "a_share_close_review",
        "hk_connect_close_review",
        "hourly_research",
        "preselection_pools",
        "stage_workbench",
    ]
    assert audit["incomplete_runner_command_workload_ids"] == []
    assert audit["available_runner_workload_ids"] == [
        "a_share_close_review",
        "hk_connect_close_review",
        "hourly_research",
        "preselection_pools",
        "stage_workbench",
    ]
    assert audit["missing_runner_workload_ids"] == []
    assert audit["blocking_gaps"] == []
    assert audit["status"] == "PASS"
    assert audit["safety"] == SAFETY


def test_phase5_audit_maps_all_records_without_claiming_false_owners() -> None:
    audit = _build()

    tasks = audit["canonical_tasks"]
    assert len(tasks) == 35
    assert [row["legacy_task_id"] for row in tasks] == sorted(
        row["legacy_task_id"] for row in tasks
    )
    assert all(row["actual_windows_task_present"] for row in tasks)
    hourly = next(
        row
        for row in tasks
        if row["legacy_task_id"] == "OpeningAdvisorV3_HourlyResearch_0700_2359"
    )
    assert hourly["catalog_workload_ids"] == ["hourly_research"]
    assert hourly["mapping_status"] == "EXACT_CATALOG_IDENTITY_RUNNER_AVAILABLE"
    unresolved = [row for row in tasks if not row["catalog_workload_ids"]]
    assert len(unresolved) == 34
    assert all(row["mapping_status"].startswith("CANNOT_CONFIRM_") for row in unresolved)
    assert all(
        row["task_registration_status"]
        == "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
        for row in unresolved
    )

    entrypoints = audit["entrypoints"]
    assert len(entrypoints) == 90
    assert [row["atlas_entrypoint_id"] for row in entrypoints] == sorted(
        row["atlas_entrypoint_id"] for row in entrypoints
    )
    assert all(row["mapping_status"] for row in entrypoints)
    assert audit["unresolved_entrypoint_ids"] == []
    assert len(audit["approved_registration_entrypoint_ids"]) == 66
    assert audit["unexplained_entrypoint_ids"] == []
    assert any(
        row["mapping_status"] == "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
        for row in entrypoints
    )
    assert any(
        row["mapping_status"] == "NON_SCHEDULED_OWNER_ONLY"
        for row in entrypoints
    )
    owner_only_ops_ids = {
        row["atlas_entrypoint_id"]
        for row in entrypoints
        if row["target_owner"] == "ops"
        and row["legacy_task_ids"] == []
        and row["catalog_workload_ids"] == []
    }
    assert len(owner_only_ops_ids) == 12
    assert all(
        row["mapping_status"] == "NON_SCHEDULED_OWNER_ONLY"
        and row["inventory_disposition"] == "REWRITE"
        and row["inventory_status"] == "PENDING"
        for row in entrypoints
        if row["atlas_entrypoint_id"] in owner_only_ops_ids
    )


def test_phase5_audit_is_self_hashed_and_reproducible() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert _load(AUDIT_CONTRACT) == first
    assert first["graph_snapshot_id"] == GRAPH.stem
    assert first["input_raw_sha256"] == {
        "graph": hashlib.sha256(GRAPH.read_bytes()).hexdigest(),
        "inventory_v2": hashlib.sha256(INVENTORY.read_bytes()).hexdigest(),
        "runtime_catalog": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
    }
    claimed = first.pop("semantic_hash")
    actual = hashlib.sha256(
        json.dumps(
            first,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert claimed == actual


@pytest.mark.parametrize(
    "entrypoint_id",
    [
        "entrypoint_06c42523fd15181d114cbec4",
        "entrypoint_0ce16ce32cb052635e472f81",
        "entrypoint_00a7718412c92cd2bd2c7d5f",
    ],
)
def test_entrypoint_without_a_graph_owner_is_blocking(
    tmp_path, entrypoint_id: str
) -> None:
    inventory = _load(INVENTORY)
    row = next(
        item
        for item in inventory["entrypoints"]
        if item["atlas_entrypoint_id"] == entrypoint_id
    )
    row["target_owner"] = None
    inventory_path = tmp_path / "inventory_without_entrypoint_owner.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    audit = build_runtime_governance_audit(
        graph_path=GRAPH,
        inventory_path=inventory_path,
        catalog_path=CATALOG,
        repo_root=REPO,
    )

    assert audit["unexplained_entrypoint_ids"] == [entrypoint_id]
    assert (
        "1_ENTRYPOINTS_HAVE_NO_GRAPH_BACKED_OWNER"
        in audit["blocking_gaps"]
    )


def test_partial_alias_cannot_promote_a_multi_node_task_to_exact(tmp_path) -> None:
    catalog = _load(CATALOG)
    hourly = next(
        row for row in catalog["workloads"] if row["workload_id"] == "hourly_research"
    )
    hourly["aliases"].append("v3_ashare_readiness_0755")
    path = tmp_path / "partial_alias_catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    audit = _build(catalog_path=path)
    startup = next(
        row
        for row in audit["canonical_tasks"]
        if row["legacy_task_id"] == "OpeningAdvisorV3_0755_StartupEnsure"
    )
    assert startup["timeline_node_ids"] == [
        "v3_ashare_readiness_0755",
        "v3_startup_ensure_0_2_hkconnect",
    ]
    assert startup["catalog_workload_ids"] == []
    assert startup["mapping_status"] == "CANNOT_CONFIRM_CATALOG_OWNER"
    assert audit["exact_catalog_task_count"] == 1
    assert audit["unresolved_catalog_task_count"] == 34
    assert audit["unregistered_unresolved_task_ids"] == []
    assert not any("CANONICAL_TASKS_HAVE_NO_PROVABLE" in gap for gap in audit["blocking_gaps"])


def test_runner_requires_declared_flag_and_placeholder_pairs(tmp_path) -> None:
    catalog = _load(CATALOG)
    hk = next(
        row
        for row in catalog["workloads"]
        if row["workload_id"] == "hk_connect_close_review"
    )
    hk["command"] = [
        "python",
        "-m",
        "ops.build_close_review",
        "{data_root}",
        "{business_date}",
    ]
    invalid_path = tmp_path / "invalid_runner_catalog.json"
    invalid_path.write_text(json.dumps(catalog), encoding="utf-8")
    invalid = _build(catalog_path=invalid_path)
    assert invalid["available_runner_workload_ids"] == [
        "a_share_close_review",
        "hourly_research",
        "preselection_pools",
        "stage_workbench",
    ]
    assert invalid["incomplete_runner_command_workload_ids"] == [
        "hk_connect_close_review"
    ]
    assert not any(
        "INCOMPLETE_ARGUMENT_BINDINGS" in gap
        for gap in invalid["blocking_gaps"]
    )

    hk["command"] = [
        "python",
        "-m",
        "ops.build_close_review",
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
    ]
    valid_path = tmp_path / "valid_runner_catalog.json"
    valid_path.write_text(json.dumps(catalog), encoding="utf-8")
    valid = _build(catalog_path=valid_path)
    assert valid["available_runner_workload_ids"] == [
        "a_share_close_review",
        "hk_connect_close_review",
        "hourly_research",
        "preselection_pools",
        "stage_workbench",
    ]
    assert valid["incomplete_runner_command_workload_ids"] == []
    assert not any(
        "INCOMPLETE_ARGUMENT_BINDINGS" in gap for gap in valid["blocking_gaps"]
    )
    assert valid["blocking_gaps"] == []


def test_workload_safety_boundary_fails_closed(tmp_path) -> None:
    catalog = _load(CATALOG)
    catalog["workloads"][0]["safety"]["production_allowed"] = True
    path = tmp_path / "unsafe_workload_catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe workload boundary"):
        _build(catalog_path=path)


def test_task_registration_boundary_fails_closed(tmp_path) -> None:
    catalog = _load(CATALOG)
    catalog["task_registrations"][0]["safety"]["orders_sent"] = True
    path = tmp_path / "unsafe_task_registration_catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="task registration contract mismatch"):
        _build(catalog_path=path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update({"owner_id": "fake.executable.owner"}),
        lambda row: row.update({"command": ["python", "-m", "fake.runner"]}),
        lambda row: row.update({"disposition": "FAKE_APPROVAL"}),
    ],
)
def test_audit_requires_the_strict_approved_registration_contract(
    tmp_path, mutate
) -> None:
    catalog = _load(CATALOG)
    mutate(catalog["task_registrations"][0])
    path = tmp_path / "invalid_registration_contract.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError):
        _build(catalog_path=path)


def test_audit_rejects_catalog_replacement_between_raw_and_strict_reads(
    tmp_path, monkeypatch
) -> None:
    legal = _load(CATALOG)
    malicious = _load(CATALOG)
    malicious["task_registrations"][0].update(
        {
            "owner_id": "fake.executable.owner",
            "command": ["python", "-m", "fake.runner"],
            "disposition": "FAKE_APPROVAL",
        }
    )
    path = tmp_path / "runtime_catalog.json"
    replacement = tmp_path / "legal_replacement.json"
    path.write_text(json.dumps(malicious), encoding="utf-8")
    replacement.write_text(json.dumps(legal), encoding="utf-8")
    strict_loader = runtime_governance_module.load_workload_catalog

    def replace_then_validate(source: Path):
        os.replace(replacement, source)
        return strict_loader(source)

    monkeypatch.setattr(
        runtime_governance_module,
        "load_workload_catalog",
        replace_then_validate,
    )

    with pytest.raises(ValueError, match="runtime catalog changed during audit"):
        _build(catalog_path=path)


def test_generator_only_writes_exact_non_input_audit_targets(tmp_path) -> None:
    assert _allowed_output(DEFAULT_OUTPUT) == DEFAULT_OUTPUT.resolve(strict=False)
    assert _allowed_output(RUNTIME_EVIDENCE_OUTPUT) == (
        RUNTIME_EVIDENCE_OUTPUT.resolve(strict=False)
    )
    with pytest.raises(ValueError, match="approved audit target"):
        _allowed_output(INVENTORY)
    with pytest.raises(ValueError, match="approved audit target"):
        _allowed_output(tmp_path / "outside.json")
    with pytest.raises(ValueError, match="overlaps a read-only input"):
        _validated_output(DEFAULT_OUTPUT, DEFAULT_OUTPUT)


def test_zero_runner_gaps_do_not_emit_zero_count_blockers(tmp_path) -> None:
    catalog = _load(CATALOG)
    complete_command = [
        "python",
        "-m",
        "ops.build_close_review",
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
    ]
    for workload in catalog["workloads"]:
        workload["command"] = complete_command
    catalog_path = tmp_path / "all_runners_available.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    module = tmp_path / "ops" / "build_close_review.py"
    module.parent.mkdir(parents=True)
    module.write_text("# test runner\n", encoding="utf-8")

    audit = _build(catalog_path=catalog_path, repo_root=tmp_path)

    assert len(audit["available_runner_workload_ids"]) == 5
    assert audit["missing_runner_workload_ids"] == []
    assert audit["incomplete_runner_command_workload_ids"] == []
    assert not any(gap.startswith("0_") for gap in audit["blocking_gaps"])
    assert not any("RUNNER" in gap for gap in audit["blocking_gaps"])
