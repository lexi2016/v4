from __future__ import annotations

from copy import deepcopy
import json
from collections import Counter
from pathlib import Path

import pytest

from ops.migration.inventory import (
    FROZEN_SEMANTIC_HASH,
    InventoryValidationError,
    build_inventory,
    validate_initial_snapshot,
    validate_inventory,
)


MINI_COUNTS = {"sources": 1, "entrypoints": 1, "runtime_tasks": 2, "features": 1}


def _write_mini_atlas(atlas) -> None:
    (atlas / "files.jsonl").write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "id": "file_alpha",
                        "path": "30_runtime/example.py",
                        "language": "python",
                        "layer": "live_core",
                        "authority": "current_authority",
                        "sha256": "a" * 64,
                    }
                ),
                json.dumps(
                    {
                        "id": "file_excluded",
                        "path": "discarded.py",
                        "language": "python",
                        "layer": "history",
                        "authority": "business_module",
                        "sha256": "b" * 64,
                        "scan_mode": "scope_excluded",
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (atlas / "entrypoints.json").write_text(
        json.dumps(
            [
                {
                    "id": "entrypoint_alpha",
                    "kind": "windows_task",
                    "name": "ExampleTask",
                    "status": "CANNOT_CONFIRM",
                    "evidence": {"path": "_ops/tasks.json", "line": 1},
                }
            ]
        ),
        encoding="utf-8",
    )
    (atlas / "feature_ledger.json").write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "feature.alpha",
                        "gaps": ["missing receipt"],
                        "runtime_tasks": [
                            {
                                "record_type": "timeline_node",
                                "task_name": "node_alpha",
                                "node_id": "node_alpha",
                                "feature_ids": ["feature.alpha"],
                                "evidence": {"path": "_ops/nodes.json", "line": 1},
                            },
                            {
                                "record_type": "windows_task",
                                "task_name": "ExampleTask",
                                "node_id": "node_alpha",
                                "feature_ids": ["feature.alpha"],
                                "evidence": {"path": "_ops/nodes.json", "line": 2},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (atlas / "validation.json").write_text(
        json.dumps({"semantic_hash": FROZEN_SEMANTIC_HASH}), encoding="utf-8"
    )


def _mini_inventory(tmp_path):
    atlas = tmp_path / "atlas"
    atlas.mkdir(exist_ok=True)
    _write_mini_atlas(atlas)
    return build_inventory(atlas, expected_counts=MINI_COUNTS)


def _machine_evidence() -> list[dict[str, object]]:
    return [{"kind": "pytest", "path": "tests/test_replacement.py", "line": 9}]


def test_build_inventory_excludes_non_included_source_and_preserves_source_status(tmp_path) -> None:
    inventory = _mini_inventory(tmp_path)

    assert [record["atlas_file_id"] for record in inventory["sources"]] == ["file_alpha"]
    assert inventory["sources"][0]["old_source"] == "30_runtime/example.py"
    assert inventory["entrypoints"][0]["source_status"] == "CANNOT_CONFIRM"
    validate_inventory(inventory, expected_counts=MINI_COUNTS)


def test_build_inventory_normalizes_cross_feature_duplicate_task_and_unions_features(tmp_path) -> None:
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    _write_mini_atlas(atlas)
    ledger_path = atlas / "feature_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["features"].append(
        {
            "id": "feature.beta",
            "gaps": [],
            "runtime_tasks": [
                {
                    "record_type": "timeline_node",
                    "task_name": "node_alpha",
                    "node_id": "node_alpha",
                    "feature_ids": ["feature.beta"],
                    "evidence": {"path": "_ops/other_nodes.json", "line": 4},
                }
            ],
        }
    )
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    inventory = build_inventory(
        atlas, expected_counts={"sources": 1, "entrypoints": 1, "runtime_tasks": 2, "features": 2}
    )

    node = next(record for record in inventory["runtime_tasks"] if record["record_type"] == "timeline_node")
    assert node["feature_ids"] == ["feature.alpha", "feature.beta"]
    assert node["source_evidence"] == [
        {"line": 1, "path": "_ops/nodes.json"},
        {"line": 4, "path": "_ops/other_nodes.json"},
    ]


def test_generic_validator_allows_lifecycle_dispositions_and_complete_machine_evidence(tmp_path) -> None:
    inventory = _mini_inventory(tmp_path)
    source = inventory["sources"][0]
    source["disposition"] = "REPLACE"
    source["status"] = "COMPLETE"
    source["replacement_evidence"] = _machine_evidence()
    inventory["entrypoints"][0]["disposition"] = "ARCHIVE_DATA_ONLY"
    inventory["runtime_tasks"][0]["disposition"] = "APPROVED_REMOVE"
    inventory["runtime_tasks"][0]["approval_metadata"] = {"approval_id": "MIG-42"}

    validate_inventory(inventory, expected_counts=MINI_COUNTS)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda inv: inv["sources"].append(deepcopy(inv["sources"][0])), "atlas_file_id"),
        (lambda inv: inv["entrypoints"].append(deepcopy(inv["entrypoints"][0])), "atlas_entrypoint_id"),
        (lambda inv: inv["runtime_tasks"].append(deepcopy(inv["runtime_tasks"][0])), "runtime task key"),
        (lambda inv: inv["features"].append(deepcopy(inv["features"][0])), "feature_id"),
        (lambda inv: inv["sources"][0].pop("target_owner"), "target owner"),
        (lambda inv: inv["sources"][0].pop("sha256"), "sha256"),
        (lambda inv: inv["entrypoints"][0].pop("source_evidence"), "source_evidence"),
        (lambda inv: inv["runtime_tasks"][0].update(feature_ids=[]), "feature_ids"),
        (lambda inv: inv["runtime_tasks"][0].update(feature_ids=["unknown.feature"]), "unknown feature"),
        (lambda inv: inv["features"][0].update(source_gaps="none"), "source_gaps"),
        (lambda inv: inv["sources"][0].update(target_owner="apps/arbitrary"), "target owner"),
        (lambda inv: inv["sources"][0].update(target_owner="domains/../../escape"), "target owner"),
        (lambda inv: inv["sources"][0].update(target_owner="domains\\escape"), "target owner"),
        (lambda inv: inv["sources"][0].update(disposition="DELETE"), "disposition"),
        (lambda inv: inv["sources"][0].update(status="DONE"), "status"),
        (lambda inv: inv["runtime_tasks"][0].update(record_type="cron"), "runtime record type"),
        (lambda inv: inv["sources"][0].update(sha256="not-a-sha"), "sha256"),
        (lambda inv: inv["sources"][0].update(old_source="C:/old/source.py"), "absolute"),
        (lambda inv: inv["entrypoints"][0]["source_evidence"][0].update(path="/old/evidence"), "absolute"),
        (lambda inv: inv["sources"][0].update(replacement_evidence=_machine_evidence()), "PENDING"),
        (lambda inv: inv["sources"][0].update(status="COMPLETE"), "machine evidence"),
        (lambda inv: inv["runtime_tasks"][0].update(disposition="APPROVED_REMOVE"), "approval metadata"),
    ],
)
def test_generic_validator_fails_closed_on_invalid_records(tmp_path, mutate, match) -> None:
    inventory = _mini_inventory(tmp_path)
    mutate(inventory)

    expected_counts = None if match in {"atlas_file_id", "atlas_entrypoint_id", "runtime task key", "feature_id"} else MINI_COUNTS
    with pytest.raises(InventoryValidationError, match=match):
        validate_inventory(inventory, expected_counts=expected_counts)


def test_generic_validator_accepts_approved_remove_with_explicit_metadata(tmp_path) -> None:
    inventory = _mini_inventory(tmp_path)
    inventory["sources"][0]["disposition"] = "APPROVED_REMOVE"
    inventory["sources"][0]["approval_metadata"] = {"approval_id": "MIG-99", "approved_by": "owner"}

    validate_inventory(inventory, expected_counts=MINI_COUNTS)


def test_validator_rejects_bad_hash_and_requested_count(tmp_path) -> None:
    inventory = _mini_inventory(tmp_path)
    inventory["atlas"]["semantic_hash"] = "bad"
    with pytest.raises(InventoryValidationError, match="semantic hash"):
        validate_inventory(inventory, expected_counts=MINI_COUNTS)

    inventory = _mini_inventory(tmp_path)
    with pytest.raises(InventoryValidationError, match="sources count"):
        validate_inventory(inventory, expected_counts={**MINI_COUNTS, "sources": 2})


def test_initial_snapshot_rejects_frozen_feature_omission_and_non_initial_lifecycle() -> None:
    contract_path = Path("contracts/migration/v35_replacement_inventory.json")
    inventory = json.loads(contract_path.read_text(encoding="utf-8"))
    next(record for record in inventory["features"] if record["feature_id"] == "orphan.loadConsole")["feature_id"] = "unknown.feature"
    with pytest.raises(InventoryValidationError, match="omission of frozen feature"):
        validate_initial_snapshot(inventory)

    inventory = json.loads(contract_path.read_text(encoding="utf-8"))
    inventory["sources"][0]["status"] = "IN_PROGRESS"
    with pytest.raises(InventoryValidationError, match="initial snapshot"):
        validate_initial_snapshot(inventory)


def test_checked_in_inventory_has_the_frozen_pending_replacement_boundary() -> None:
    contract_path = Path("contracts/migration/v35_replacement_inventory.json")
    inventory = json.loads(contract_path.read_text(encoding="utf-8"))

    validate_initial_snapshot(inventory)

    assert inventory["atlas"]["semantic_hash"] == FROZEN_SEMANTIC_HASH
    assert {group: len(inventory[group]) for group in ("sources", "entrypoints", "runtime_tasks", "features")} == {
        "sources": 335,
        "entrypoints": 89,
        "runtime_tasks": 69,
        "features": 11,
    }
    assert Counter(record["kind"] for record in inventory["entrypoints"]) == {
        "cli_script": 45,
        "windows_task": 35,
        "html_page": 8,
        "python_entry_candidate": 1,
    }
    assert Counter(record["record_type"] for record in inventory["runtime_tasks"]) == {
        "timeline_node": 34,
        "windows_task": 35,
    }
