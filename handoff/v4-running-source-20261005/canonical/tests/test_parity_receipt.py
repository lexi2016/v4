from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from contracts.parity import (
    ParityReceiptError,
    classify_parity_receipt_against_slice,
    seal_graph_slice_contract,
    seal_parity_receipt,
    validate_graph_slice_contract,
    validate_parity_receipt,
    validate_parity_receipt_against_graph,
)
from infrastructure.parity_store import ParityReceiptStore


ROOT = Path(__file__).resolve().parents[1]


def _file(path: str, character: str) -> dict[str, str]:
    return {"path": path, "sha256": character * 64}


def _receipt() -> dict[str, object]:
    graph = _graph()
    payload: dict[str, object] = {
        "schema_version": "v3_5.parity_receipt.v1",
        "feature_id": "preselection.pools",
        "graph_baseline_semantic_hash": graph["semantic_hash"],
        "graph_node_ids": [
            "api:GET /preselection-pools",
            "timeline_node:ashare_v193_slot_selector_premarket",
        ],
        "business_date": "20260730",
        "view_id": "review",
        "viewport": {
            "width": 1440,
            "height": 900,
            "device_scale_factor": 1.0,
            "source": "BUILT_IN_BROWSER",
        },
        "source_sha256": {"v3": "b" * 64, "v35": "b" * 64},
        "raw_input_sha256": "a" * 64,
        "lanes": {
            "artifact": {
                "status": "PASS",
                "observed_date": "20260730",
                "v3_artifact": _file("v3/artifact.json", "d"),
                "v3_manifest": _file("v3/manifest.json", "e"),
                "v35_artifact": _file("v35/artifact.json", "f"),
                "v35_manifest": _file("v35/manifest.json", "1"),
                "row_counts": {"v3": 50, "v35": 50},
                "differences": [],
                "cannot_confirm": [],
            },
            "api": {
                "status": "PASS",
                "observed_date": "20260730",
                "endpoints": {
                    "v3": "http://127.0.0.1:8771/api/v3/preselection?date=20260730",
                    "v35": "http://127.0.0.1:8872/api/v3/preselection?date=20260730",
                },
                "http_status": {"v3": 200, "v35": 200},
                "payload_sha256": {"v3": "2" * 64, "v35": "3" * 64},
                "row_counts": {"v3": 50, "v35": 50},
                "differences": [],
                "cannot_confirm": [],
            },
            "page": {
                "status": "PASS",
                "observed_date": "20260730",
                "urls": {
                    "v3": "http://127.0.0.1:8771/?date=20260730",
                    "v35": "http://127.0.0.1:8872/?date=20260730",
                },
                "titles": {"v3": "V3", "v35": "V3.5"},
                "row_counts": {"v3": 50, "v35": 50},
                "screenshots": {
                    "v3": _file("screenshots/v3.png", "4"),
                    "v35": _file("screenshots/v35.png", "5"),
                },
                "console_errors": {"v3": [], "v35": []},
                "console_warnings": {"v3": [], "v35": []},
                "timing_ms": {"v3": 120.0, "v35": 100.0},
                "loading_complete": {"v3": True, "v35": True},
                "horizontal_overflow": {"v3": False, "v35": False},
                "differences": [],
                "cannot_confirm": [],
            },
        },
        "verdict": "PASS",
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    return seal_parity_receipt(payload)


def _graph() -> dict[str, object]:
    return json.loads(
        (ROOT / "contracts/migration/v3_graph_baseline_v2.json").read_text(
            encoding="utf-8"
        )
    )


def _inventory() -> dict[str, object]:
    return json.loads(
        (ROOT / "contracts/migration/v35_replacement_inventory_v2.json").read_text(
            encoding="utf-8"
        )
    )


def _store(tmp_path: Path) -> ParityReceiptStore:
    return ParityReceiptStore(
        tmp_path,
        graph_baseline=_graph(),
        inventory_v2=_inventory(),
    )


def test_valid_parity_receipt_has_independent_lanes_and_self_hash() -> None:
    receipt = _receipt()

    validate_parity_receipt(receipt)
    assert receipt["receipt_semantic_hash"]
    assert set(receipt["lanes"]) == {"artifact", "api", "page"}


def test_parity_receipt_rejects_unknown_schema_before_seal() -> None:
    receipt = _receipt()
    receipt["schema_version"] = "unknown"

    with pytest.raises(ParityReceiptError, match="schema"):
        seal_parity_receipt(receipt)


def test_parity_receipt_binds_hash_and_nodes_to_frozen_graph() -> None:
    receipt = _receipt()

    validate_parity_receipt_against_graph(receipt, _graph(), _inventory())
    wrong_hash = deepcopy(receipt)
    wrong_hash["graph_baseline_semantic_hash"] = "f" * 64
    wrong_hash = seal_parity_receipt(wrong_hash)
    with pytest.raises(ParityReceiptError, match="graph baseline hash"):
        validate_parity_receipt_against_graph(wrong_hash, _graph(), _inventory())
    invented = _graph()
    invented["graph_node_registry"]["ids"].append("invented:node")
    with pytest.raises(ParityReceiptError, match="semantic hash"):
        validate_parity_receipt_against_graph(receipt, invented, _inventory())


def test_parity_receipt_rejects_registered_but_unrelated_feature_node() -> None:
    receipt = _receipt()
    receipt["graph_node_ids"] = ["api:GET /health"]
    receipt = seal_parity_receipt(receipt)

    with pytest.raises(ParityReceiptError, match="feature-owned"):
        validate_parity_receipt_against_graph(receipt, _graph(), _inventory())


def test_parity_receipt_rejects_invented_graph_node() -> None:
    receipt = _receipt()
    receipt["graph_node_ids"] = sorted(
        [*receipt["graph_node_ids"], "invented:node"]
    )
    receipt = seal_parity_receipt(receipt)

    with pytest.raises(ParityReceiptError, match="unknown graph node"):
        validate_parity_receipt_against_graph(receipt, _graph(), _inventory())


def test_parity_receipt_rejects_tamper_after_seal() -> None:
    receipt = _receipt()
    receipt["lanes"]["api"]["row_counts"]["v35"] = 49

    with pytest.raises(ParityReceiptError, match="semantic hash"):
        validate_parity_receipt(receipt)


def test_parity_receipt_rejects_lane_date_mismatch_after_reseal() -> None:
    receipt = _receipt()
    receipt["lanes"]["artifact"]["observed_date"] = "20260729"

    with pytest.raises(ParityReceiptError, match="date mismatch"):
        seal_parity_receipt(receipt)


def test_parity_receipt_rejects_url_date_mismatch_after_reseal() -> None:
    receipt = _receipt()
    receipt["lanes"]["api"]["endpoints"]["v3"] = (
        "http://127.0.0.1:8771/api/v3/preselection?date=20260729"
    )

    with pytest.raises(ParityReceiptError, match="date mismatch"):
        seal_parity_receipt(receipt)


def test_pass_page_lane_rejects_incomplete_loading_after_reseal() -> None:
    receipt = _receipt()
    receipt["lanes"]["page"]["loading_complete"]["v35"] = False

    with pytest.raises(ParityReceiptError, match="loading"):
        seal_parity_receipt(receipt)


def test_page_lane_can_visibly_carry_built_in_browser_cannot_confirm() -> None:
    receipt = _receipt()
    receipt["lanes"]["page"]["status"] = "CANNOT_CONFIRM"
    receipt["lanes"]["page"]["cannot_confirm"] = [
        "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE"
    ]
    receipt["verdict"] = "CANNOT_CONFIRM"

    sealed = seal_parity_receipt(receipt)

    validate_parity_receipt(sealed)
    assert sealed["lanes"]["page"]["cannot_confirm"] == [
        "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE"
    ]


def test_source_sha_mismatch_cannot_be_sealed_as_pass() -> None:
    receipt = _receipt()
    receipt["source_sha256"]["v35"] = "c" * 64

    with pytest.raises(ParityReceiptError, match="source SHA mismatch"):
        seal_parity_receipt(receipt)


def test_playwright_fallback_cannot_be_sealed_as_page_pass() -> None:
    receipt = _receipt()
    receipt["viewport"]["source"] = "PLAYWRIGHT_FALLBACK"

    with pytest.raises(ParityReceiptError, match="fallback"):
        seal_parity_receipt(receipt)


def test_parity_receipt_rejects_windows_absolute_evidence_path() -> None:
    receipt = _receipt()
    receipt["lanes"]["page"]["screenshots"]["v3"]["path"] = "C:/outside.png"

    with pytest.raises(ParityReceiptError, match="screenshot path"):
        seal_parity_receipt(receipt)


def test_parity_store_is_atomic_idempotent_and_tamper_evident(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _receipt()

    first = store.write(receipt)
    second = store.write(deepcopy(receipt))

    assert first == second
    assert store.read("20260730", "preselection.pools", "review") == receipt
    target = tmp_path / first["receipt_path"]
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ParityReceiptError, match="semantic hash|schema"):
        store.read("20260730", "preselection.pools", "review")


def test_parity_store_rejects_conflicting_same_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_receipt())
    conflict = _receipt()
    conflict["lanes"]["artifact"]["row_counts"]["v35"] = 49
    conflict["lanes"]["artifact"]["status"] = "FAIL"
    conflict["lanes"]["artifact"]["differences"] = ["ROW_COUNT_MISMATCH"]
    conflict["verdict"] = "FAIL"
    conflict = seal_parity_receipt(conflict)

    with pytest.raises(ParityReceiptError, match="conflicting"):
        store.write(conflict)


def test_parity_store_serializes_concurrent_conflicting_writers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _receipt()
    second = deepcopy(first)
    second["lanes"]["artifact"]["row_counts"]["v35"] = 49
    second["lanes"]["artifact"]["status"] = "FAIL"
    second["lanes"]["artifact"]["differences"] = ["ROW_COUNT_MISMATCH"]
    second["verdict"] = "FAIL"
    second = seal_parity_receipt(second)
    barrier = Barrier(2)

    def write(receipt: dict[str, object]) -> str:
        barrier.wait()
        try:
            store.write(receipt)
            return "WRITTEN"
        except ParityReceiptError as error:
            assert "conflicting" in str(error)
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, [first, second]))

    assert sorted(results) == ["CONFLICT", "WRITTEN"]


def test_machine_authority_supersedes_exploratory_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    exploratory = _receipt()
    exploratory["view_id"] = "exploratory"
    exploratory = seal_parity_receipt(exploratory)
    authoritative = _receipt()
    authoritative["view_id"] = "authoritative"
    authoritative = seal_parity_receipt(authoritative)
    store.write(exploratory)
    store.write(authoritative)

    authority = store.set_authority(
        "20260730",
        "preselection.pools",
        active_view_id="authoritative",
        superseded_view_ids=["exploratory"],
    )

    assert store.read_authority("20260730", "preselection.pools") == authority
    assert authority["active_receipt"]["receipt_semantic_hash"] == (
        authoritative["receipt_semantic_hash"]
    )
    assert [
        item["receipt_semantic_hash"] for item in authority["superseded_receipts"]
    ] == [exploratory["receipt_semantic_hash"]]


def _slice(*, expected: str = "PASS") -> dict[str, object]:
    receipt = _receipt()
    return seal_graph_slice_contract(
        {
            "feature_id": receipt["feature_id"],
            "graph_baseline_semantic_hash": receipt["graph_baseline_semantic_hash"],
            "graph_node_ids": receipt["graph_node_ids"],
            "parity_slice": {
                "legacy_source_refs": [_file("v3/source.py", "a")],
                "raw_input_refs": [{"path": "input/raw.json", "sha256": "a" * 64, "origin": "RAW_SOURCE", "use": "LIVE"}],
                "business_date": receipt["business_date"],
                "cutoff": "2026-07-30T09:00:00+08:00",
                "v3_identities": {"producers": ["producer"], "api": ["GET /preselection"], "dom": ["#pool"]},
                "expected_v3_behavior": ["same rows"],
                "allowed_paths": ["domains/preselection.py"],
                "rules": {"PASS": ["all lanes pass"], "REJECT": ["critical cannot confirm"]},
                "expected_gate_classification": expected,
            },
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )


def test_graph_slice_accepts_one_normal_receipt_canary() -> None:
    slice_contract = _slice()
    receipt = _receipt()
    receipt["graph_slice_semantic_hash"] = slice_contract["semantic_hash"]
    assert classify_parity_receipt_against_slice(seal_parity_receipt(receipt), slice_contract) == "PASS"


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ("graph_node_ids", "graph node"), ("legacy_source_refs", "graph slice"),
        ("raw_input_sha256", "raw input"), ("business_date", "graph slice"),
        ("cutoff", "graph slice"), ("v3_identities", "graph slice"),
        ("expected_v3_behavior", "graph slice"), ("allowed_paths", "graph slice"),
        ("rules", "graph slice"), ("expected_gate_classification", "graph slice"),
        ("safety", "unsafe"), ("legacy_final_api_live", "LEGACY_FINAL_API"),
        ("critical_cannot_confirm", "classification"),
    ],
)
def test_graph_slice_rejects_critical_invalid_inputs(target: str, match: str) -> None:
    slice_contract = _slice()
    if target == "critical_cannot_confirm":
        receipt = _receipt()
        receipt["lanes"]["page"].update(status="CANNOT_CONFIRM", cannot_confirm=["BUILT_IN_BROWSER_CONTROL_UNAVAILABLE"])
        receipt["verdict"] = "CANNOT_CONFIRM"
        receipt["graph_slice_semantic_hash"] = slice_contract["semantic_hash"]
        with pytest.raises(ParityReceiptError, match=match):
            classify_parity_receipt_against_slice(seal_parity_receipt(receipt), slice_contract)
        return
    slice_contract.pop("semantic_hash")
    if target == "graph_node_ids":
        slice_contract.pop(target)
    elif target == "safety":
        slice_contract["production_allowed"] = True
    elif target == "legacy_final_api_live":
        slice_contract["parity_slice"]["raw_input_refs"][0].update(origin="LEGACY_FINAL_API")
    elif target == "raw_input_sha256":
        slice_contract["parity_slice"]["raw_input_refs"][0].pop("sha256")
    else:
        slice_contract["parity_slice"].pop(target)
    with pytest.raises(ParityReceiptError, match=match):
        seal_graph_slice_contract(slice_contract)


def test_checked_in_research_slice_fails_closed_as_expected() -> None:
    slice_contract = json.loads(
        (ROOT / "contracts/migration/research_desk_graph_contract_v1.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (ROOT / "docs/evidence/task3-graph-slice-gate-20260802.json").read_text(encoding="utf-8")
    )
    validate_graph_slice_contract(slice_contract)
    assert evidence == {
        "schema_version": "v3_5.graph_slice_gate_evidence.v1",
        "slice_contract": "contracts/migration/research_desk_graph_contract_v1.json",
        "slice_semantic_hash": slice_contract["semantic_hash"],
        "classification": "EXPECTED_FAIL_NOT_PARITY",
        "critical_cannot_confirm": [
            "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE",
            "LEGACY_FINAL_API_EXPECTED_ANSWER_ORACLE_ONLY",
            "NO_PASSING_ARTIFACT_API_PAGE_PARITY_RECEIPT",
        ],
        "lanes": {
            "artifact_manifest": "CANNOT_CONFIRM",
            "api": "CANNOT_CONFIRM",
            "visible_page": "CANNOT_CONFIRM",
        },
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    receipt = _receipt()
    receipt.update(
        feature_id=slice_contract["feature_id"],
        graph_baseline_semantic_hash=slice_contract["graph_baseline_semantic_hash"],
        graph_node_ids=sorted(slice_contract["graph_node_ids"]),
        business_date=slice_contract["parity_slice"]["business_date"],
        raw_input_sha256=slice_contract["parity_slice"]["raw_input_refs"][0]["sha256"],
        graph_slice_semantic_hash=slice_contract["semantic_hash"],
        verdict="CANNOT_CONFIRM",
    )
    for lane in receipt["lanes"].values():
        lane.update(status="CANNOT_CONFIRM", differences=[], cannot_confirm=["BUILT_IN_BROWSER_CONTROL_UNAVAILABLE"])
    assert classify_parity_receipt_against_slice(seal_parity_receipt(receipt), slice_contract) == evidence["classification"]
