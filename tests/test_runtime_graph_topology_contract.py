from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.runtime_graph.v35_topology import (
    ALLOWED_EDGE_KINDS,
    ALLOWED_NODE_TYPES,
    BASELINE_SHA,
    CONTRACT_PATH,
    build_v35_topology,
    canonical_payload,
    load_v35_topology,
    validate_v35_topology,
)


ROOT = Path(__file__).resolve().parents[1]


def test_contract_has_exactly_nineteen_derived_timeline_nodes_and_complete_chains() -> None:
    payload = load_v35_topology(CONTRACT_PATH)
    validate_v35_topology(payload)

    assert len(payload["timeline_nodes"]) == 19
    assert [item["position"] for item in payload["timeline_nodes"]] == list(range(1, 20))
    assert len(payload["timeline_chains"]) == 19
    assert {item["position"] for item in payload["timeline_chains"]} == set(range(1, 20))
    required = ALLOWED_NODE_TYPES - {"artifact_trio"}
    for chain in payload["timeline_chains"]:
        node_types = {node["type"] for node in chain["nodes"]}
        assert required <= node_types
        assert "artifact_trio" in node_types
        assert chain["edges"]

    for timeline in payload["timeline_nodes"]:
        assert timeline["planned_slot"] == timeline["workload"]["slot"]
        assert timeline["launcher"]["plist"]
        assert timeline["dispatcher"]
        assert timeline["executor"]
        assert timeline["producer"]
        assert timeline["store"]
        assert {"artifact", "manifest", "receipt", "sha256_fields"} <= set(timeline["artifact_trio"])
        assert set(timeline["artifact_trio"]["sha256_fields"]) == {"artifact", "manifest", "receipt"}
        assert timeline["current"].endswith("/current.json")
        assert timeline["latest"].endswith("/latest.json")
        assert timeline["api_route"].startswith("/api/")
        assert timeline["page_consumer"]


def test_contract_preserves_old_v3_baseline_and_only_allowed_edge_kinds() -> None:
    payload = load_v35_topology(CONTRACT_PATH)
    assert payload["baseline_sha"] == BASELINE_SHA
    assert payload["baseline_role"] == "design_only_migration_semantics"
    assert {edge["kind"] for edge in payload["edges"]} <= ALLOWED_EDGE_KINDS
    assert all(node["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    } for node in payload["nodes"])


def test_semantic_sha_is_self_consistent_and_generation_is_byte_stable() -> None:
    payload = load_v35_topology(CONTRACT_PATH)
    canonical = canonical_payload(payload)
    assert payload["semantic_sha"] == hashlib.sha256(canonical).hexdigest()

    generated = build_v35_topology(
        workloads_path=ROOT / "contracts" / "runtime_workloads.json",
        app_path=ROOT / "apps" / "web" / "src" / "App.vue",
        baseline_path=Path("/Users/lexi/Desktop/学习/v3_system/_ops/v3_timeline_nodes.json"),
    )
    assert json.dumps(generated, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def test_live_binding_is_separate_and_cannot_claim_deployed_state() -> None:
    from infrastructure.runtime_graph.v35_bindings import empty_live_binding_snapshot

    snapshot = empty_live_binding_snapshot()
    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["binding"] == {}
    assert snapshot["production_allowed"] is False


def test_code_tour_has_real_anchors_and_architecture_depth() -> None:
    tour_path = ROOT / ".tours" / "architect-v35-runtime-selection-research.tour"
    tour = json.loads(tour_path.read_text(encoding="utf-8"))
    assert 14 <= len(tour["steps"]) <= 18
    assert "file" in tour["steps"][0] or "directory" in tour["steps"][0]
    for step in tour["steps"]:
        path = step.get("file") or step.get("directory")
        if not path:
            continue
        target = ROOT / path
        assert target.exists(), path
        if "line" in step:
            assert 1 <= step["line"] <= len(target.read_text(encoding="utf-8").splitlines())
