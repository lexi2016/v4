from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ops.migration.graph_baseline import (
    GraphBaselineError,
    build_graph_bundle,
    build_graph_bundle_from_snapshot,
    freeze_graph_inputs,
    validate_graph_baseline,
    validate_inventory_v2,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _rehash(payload: dict[str, object], field: str) -> None:
    unhashed = {key: value for key, value in payload.items() if key != field}
    encoded = json.dumps(
        unhashed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload[field] = hashlib.sha256(encoded).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    legacy_root = tmp_path / "v3_system"
    atlas = tmp_path / "atlas"
    legacy_root.mkdir()
    atlas.mkdir()
    (legacy_root / "30_runtime").mkdir()
    (legacy_root / "30_runtime" / "current.py").write_bytes(b"print('current')\r\n")
    (legacy_root / "30_runtime" / "atlas_only.py").write_bytes(b"print('new')\n")
    (legacy_root / "30_runtime" / "v1_only.py").write_bytes(b"print('old')\n")

    current_atlas_sha = "1" * 64
    atlas_only_sha = "2" * 64
    (atlas / "files.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "id": "file_current",
                    "path": "30_runtime/current.py",
                    "language": "python",
                    "authority": "current_authority",
                    "scan_mode": "included",
                    "sha256": current_atlas_sha,
                },
                {
                    "id": "file_atlas_only",
                    "path": "30_runtime/atlas_only.py",
                    "language": "python",
                    "authority": "current_authority",
                    "scan_mode": "included",
                    "sha256": atlas_only_sha,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        atlas / "entrypoints.json",
        [
            {
                "id": "entry_current",
                "kind": "html_page",
                "path": "30_runtime/current.py",
                "status": "STATIC_SOURCE_ENTRY",
                "evidence": {"path": "30_runtime/current.py", "line": 1},
            },
            {
                "id": "entry_atlas_only",
                "kind": "html_page",
                "path": "30_runtime/atlas_only.py",
                "status": "STATIC_SOURCE_ENTRY",
                "evidence": {"path": "30_runtime/atlas_only.py", "line": 1},
            },
            {
                "id": "entry_task_only",
                "kind": "windows_task",
                "name": "TaskAlpha",
                "status": "CANNOT_CONFIRM",
                "evidence": {"path": "30_runtime/current.py", "line": 1},
            },
        ],
    )
    _write_json(
        atlas / "validation.json",
        {
            "schema_version": "v3_program_atlas.validation.v1",
            "status": "PASS",
            "semantic_hash": "a" * 64,
            "counts": {"included_files": 2, "entrypoints": 2, "parse_gaps": 0},
            "deterministic_artifact_hashes": {},
        },
    )

    runtime_graph = tmp_path / "runtime_graph.json"
    _write_json(
        runtime_graph,
        {
            "schema_version": "v3_current_script_task_graph.v1",
            "status": "CANNOT_CONFIRM_GRAPH_BUILT_WITH_FINDINGS",
            "generated_at": "2026-08-01T00:00:00",
            "counts": {
                "python_parse_errors": 0,
                "findings": 0,
                "graph_nodes": 4,
                "timeline_task_specs": 1,
                "actual_windows_tasks": 1,
                "api_route_count": 1,
                "frontend_api_ref_count": 1,
            },
            "graph": {
                "nodes": [
                    {
                        "id": "file:30_runtime/current.py",
                        "kind": "script",
                        "path": "30_runtime/current.py",
                    },
                    {
                        "id": "api:GET /review",
                        "kind": "api_route",
                        "method": "GET",
                        "path": "/review",
                    },
                    {"id": "timeline_node:node_alpha", "kind": "timeline_node"},
                    {"id": "windows_task:TaskAlpha", "kind": "windows_task"},
                ],
                "edges": [],
            },
            "findings": [],
        },
    )

    inventory_v1 = tmp_path / "inventory_v1.json"
    _write_json(
        inventory_v1,
        {
            "schema_version": "v3_5.replacement_inventory.v1",
            "atlas": {"semantic_hash": "b" * 64},
            "sources": [
                {
                    "atlas_file_id": "file_current",
                    "old_source": "30_runtime/current.py",
                    "language": "python",
                    "layer": "live_core",
                    "authority": "current_authority",
                    "sha256": current_atlas_sha,
                    "target_owner": "apps/api",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                },
                {
                    "atlas_file_id": "file_v1_only",
                    "old_source": "30_runtime/v1_only.py",
                    "language": "python",
                    "layer": "live_core",
                    "authority": "current_authority",
                    "sha256": "3" * 64,
                    "target_owner": "apps/api",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                },
            ],
            "entrypoints": [
                {
                    "atlas_entrypoint_id": "entry_current",
                    "kind": "html_page",
                    "name": None,
                    "source_evidence": [{"path": "30_runtime/current.py", "line": 1}],
                    "source_status": "STATIC_SOURCE_ENTRY",
                    "target_owner": "apps/web",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                }
            ],
            "runtime_tasks": [
                {
                    "record_type": "timeline_node",
                    "task_name": "node_alpha",
                    "node_id": "node_alpha",
                    "feature_ids": ["feature.alpha"],
                    "source_evidence": [{"path": "_ops/nodes.json", "line": 1}],
                    "target_owner": "ops",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                },
                {
                    "record_type": "windows_task",
                    "task_name": "TaskAlpha",
                    "node_id": "node_alpha",
                    "feature_ids": ["feature.alpha"],
                    "source_evidence": [{"path": "_ops/nodes.json", "line": 2}],
                    "target_owner": "ops",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                },
            ],
            "features": [
                {
                    "feature_id": "feature.alpha",
                    "source_gaps": ["ORIGINAL_ATLAS_NOT_PRESENT"],
                    "target_owner": "domains/migration",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                }
            ],
        },
    )
    return atlas, runtime_graph, inventory_v1, legacy_root


def test_bundle_records_current_bytes_and_explains_atlas_inventory_differences(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)

    baseline, inventory = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    validate_graph_baseline(baseline)
    validate_inventory_v2(inventory, baseline=baseline)
    assert baseline["reconciliation"]["unexplained_differences"] == []
    assert baseline["reconciliation"]["atlas_only_sources"] == [
        {
            "atlas_file_id": "file_atlas_only",
            "path": "30_runtime/atlas_only.py",
            "reason": "ADDED_AFTER_ORPHANED_INVENTORY",
        }
    ]
    assert baseline["reconciliation"]["inventory_v1_only_sources"] == [
        {
            "atlas_file_id": "file_v1_only",
            "path": "30_runtime/v1_only.py",
            "reason": "REMOVED_FROM_CURRENT_ATLAS_BUT_PRESENT_ON_DISK",
        }
    ]
    source = next(row for row in inventory["sources"] if row["atlas_file_id"] == "file_current")
    assert source["sha256"] != "1" * 64
    assert source["source_state"] == "MODIFIED_SINCE_ATLAS"
    assert source["graph_node_ids"] == [
        "atlas:file_current",
        "file:30_runtime/current.py",
    ]
    task_entry = next(
        row for row in inventory["entrypoints"] if row["atlas_entrypoint_id"] == "entry_task_only"
    )
    assert task_entry["graph_node_ids"] == [
        "atlas:entry_task_only",
        "file:30_runtime/current.py",
        "windows_task:TaskAlpha",
    ]
    assert {group: len(inventory[group]) for group in inventory["counts"]} == inventory["counts"]


def test_bundle_is_deterministic_for_the_same_frozen_inputs(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    first = build_graph_bundle(
        atlas_path=paths[0], runtime_graph_path=paths[1], inventory_v1_path=paths[2], legacy_root=paths[3]
    )
    second = build_graph_bundle(
        atlas_path=paths[0], runtime_graph_path=paths[1], inventory_v1_path=paths[2], legacy_root=paths[3]
    )

    assert first == second
    assert first[0]["semantic_hash"] == first[1]["graph_baseline_semantic_hash"]


def test_frozen_input_snapshot_preserves_raw_bytes_after_legacy_drift(
    tmp_path: Path,
) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    snapshot_root = tmp_path / "frozen_inputs"
    freeze_graph_inputs(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
        snapshot_root=snapshot_root,
    )

    first = build_graph_bundle_from_snapshot(snapshot_root)
    (legacy_root / "30_runtime" / "current.py").write_bytes(b"later drift\n")
    second = build_graph_bundle_from_snapshot(snapshot_root)

    assert first == second
    assert first[0]["input_snapshot"]["mode"] == "FROZEN_RAW_BYTES"
    assert first[0]["input_snapshot"]["reproducible"] is True


def test_frozen_input_snapshot_rejects_tampered_source_bytes(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    snapshot_root = tmp_path / "frozen_inputs"
    freeze_graph_inputs(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
        snapshot_root=snapshot_root,
    )
    (snapshot_root / "legacy_sources" / "30_runtime" / "current.py").write_bytes(
        b"tampered\n"
    )

    with pytest.raises(GraphBaselineError, match="frozen input hash mismatch"):
        build_graph_bundle_from_snapshot(snapshot_root)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda atlas, graph: _write_json(atlas / "validation.json", {"status": "FAIL"}), "Atlas PASS"),
        (
            lambda atlas, graph: graph["counts"].update(python_parse_errors=1),
            "parse errors",
        ),
        (
            lambda atlas, graph: graph.update(schema_version="unknown"),
            "runtime graph schema",
        ),
    ],
)
def test_bundle_fails_closed_on_untrusted_graph_inputs(tmp_path: Path, mutate, match: str) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    graph = json.loads(runtime_graph.read_text(encoding="utf-8"))
    mutate(atlas, graph)
    _write_json(runtime_graph, graph)

    with pytest.raises(GraphBaselineError, match=match):
        build_graph_bundle(
            atlas_path=atlas,
            runtime_graph_path=runtime_graph,
            inventory_v1_path=inventory_v1,
            legacy_root=legacy_root,
        )


def test_validators_reject_tampered_semantic_hash_and_missing_graph_field(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, inventory = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    tampered = deepcopy(baseline)
    tampered["semantic_hash"] = "0" * 64
    with pytest.raises(GraphBaselineError, match="semantic hash"):
        validate_graph_baseline(tampered)

    tampered_inventory = deepcopy(inventory)
    tampered_inventory["sources"][0].pop("graph_node_ids")
    _rehash(tampered_inventory, "inventory_semantic_hash")
    with pytest.raises(GraphBaselineError, match="graph_node_ids"):
        validate_inventory_v2(tampered_inventory, baseline=baseline)


def test_inventory_rejects_fabricated_graph_identity_after_rehash(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, inventory = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    inventory["sources"][0]["graph_node_ids"] = ["fabricated:not-in-frozen-graph"]
    _rehash(inventory, "inventory_semantic_hash")

    with pytest.raises(GraphBaselineError, match="unknown graph node"):
        validate_inventory_v2(inventory, baseline=baseline)


def test_inventory_rejects_evidence_free_completion_after_rehash(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, inventory = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    inventory["sources"][0].update(
        disposition="REMOVE",
        status="COMPLETE",
        replacement_evidence=[],
    )
    _rehash(inventory, "inventory_semantic_hash")

    with pytest.raises(GraphBaselineError, match="COMPLETE record requires replacement evidence"):
        validate_inventory_v2(inventory, baseline=baseline)


def test_inventory_rejects_invalid_complete_evidence_shape_after_rehash(
    tmp_path: Path,
) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, inventory = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    inventory["sources"][0].update(
        status="COMPLETE",
        replacement_evidence=[None],
    )
    _rehash(inventory, "inventory_semantic_hash")

    with pytest.raises(GraphBaselineError, match="invalid replacement evidence"):
        validate_inventory_v2(inventory, baseline=baseline)


def test_baseline_validator_requires_runtime_section_even_after_rehash(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, _ = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    baseline.pop("runtime_graph")
    _rehash(baseline, "semantic_hash")

    with pytest.raises(GraphBaselineError, match="runtime_graph"):
        validate_graph_baseline(baseline)


@pytest.mark.parametrize(
    "section",
    ["static_atlas", "inventory_v1", "current_source_snapshot", "inventory_v2_counts"],
)
def test_baseline_validator_rejects_null_required_section_after_rehash(
    tmp_path: Path, section: str
) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, _ = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    baseline[section] = None
    _rehash(baseline, "semantic_hash")

    with pytest.raises(GraphBaselineError, match=section):
        validate_graph_baseline(baseline)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda baseline: baseline["runtime_graph"]["counts"].update(
                python_parse_errors=1
            ),
            "runtime_graph",
        ),
        (
            lambda baseline: baseline["runtime_graph"].update(finding_count=-1),
            "runtime_graph",
        ),
        (
            lambda baseline: baseline["runtime_graph"]["counts"].update(
                findings=999
            ),
            "runtime_graph",
        ),
        (
            lambda baseline: baseline["graph_node_registry"]["counts"].update(
                atlas=-1, runtime="bogus"
            ),
            "graph_node_registry",
        ),
    ],
)
def test_baseline_validator_rejects_invalid_runtime_and_registry_counts(
    tmp_path: Path, mutate, match: str
) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    baseline, _ = build_graph_bundle(
        atlas_path=atlas,
        runtime_graph_path=runtime_graph,
        inventory_v1_path=inventory_v1,
        legacy_root=legacy_root,
    )

    mutate(baseline)
    _rehash(baseline, "semantic_hash")

    with pytest.raises(GraphBaselineError, match=match):
        validate_graph_baseline(baseline)


def test_common_entrypoint_identity_rejects_changed_source_path(tmp_path: Path) -> None:
    atlas, runtime_graph, inventory_v1, legacy_root = _fixture(tmp_path)
    previous = json.loads(inventory_v1.read_text(encoding="utf-8"))
    previous["entrypoints"][0]["source_evidence"][0]["path"] = (
        "30_runtime/atlas_only.py"
    )
    _write_json(inventory_v1, previous)

    with pytest.raises(GraphBaselineError, match="unexplained differences"):
        build_graph_bundle(
            atlas_path=atlas,
            runtime_graph_path=runtime_graph,
            inventory_v1_path=inventory_v1,
            legacy_root=legacy_root,
        )


def test_checked_in_graph_baseline_v2_is_reconciled_and_fails_closed() -> None:
    baseline = json.loads(
        Path("contracts/migration/v3_graph_baseline_v2.json").read_text(encoding="utf-8")
    )
    inventory = json.loads(
        Path("contracts/migration/v35_replacement_inventory_v2.json").read_text(encoding="utf-8")
    )

    validate_graph_baseline(baseline)
    validate_inventory_v2(inventory, baseline=baseline)
    assert baseline["status"] == "STATIC_RECONCILIATION_PASS_WITH_RUNTIME_GAPS"
    assert baseline["acceptance"] == {
        "scope": "STATIC_GRAPH_RECONCILIATION_ONLY",
        "static_reconciliation_accepted": True,
        "runtime_accepted": False,
        "deployment_accepted": False,
    }
    assert baseline["input_snapshot"] == {
        "mode": "FROZEN_RAW_BYTES",
        "reproducible": True,
        "snapshot_id": "frozen_inputs_graph_baseline_v2_20260801T010442",
        "semantic_hash": "6d357239d9b8ca5ef57ce7b3f555da671b48bb1bf8a9d6778b39c90327d25b9f",
        "file_count": 343,
    }
    assert baseline["semantic_hash"] == (
        "8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7"
    )
    assert inventory["inventory_semantic_hash"] == (
        "35b56c67db16ff6cd8de2ab6acd7d199dad58bb4da05c218c660622c841ae9de"
    )
    assert baseline["static_atlas"]["semantic_hash"] == (
        "912718015fba24d47dcac919b5720139666e3b5dfdf8e72a2236019badcdd033"
    )
    assert baseline["runtime_graph"]["sha256"] == (
        "2b64aeb6277dcbf17b649fd2ee2e98cefacc2397b4a3e77d0b745eac619e586b"
    )
    assert inventory["counts"] == {
        "sources": 336,
        "entrypoints": 90,
        "runtime_tasks": 69,
        "features": 11,
    }
    assert baseline["reconciliation"]["unexplained_differences"] == []
    assert all(row["graph_node_ids"] for row in inventory["runtime_tasks"])
    assert all(
        row["graph_node_ids"] or "GRAPH_NODE_NOT_RECONCILED" in row["source_gaps"]
        for row in inventory["features"]
    )
    assert inventory["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
