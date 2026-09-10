from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "preselection_optional_pools"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"
RECEIPT = FIXTURE_ROOT / "receipt_20260801.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: dict, field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fixture_manifest() -> dict:
    manifest = _load(FIXTURE_MANIFEST)
    assert manifest["schema_version"] == "v3_5.test_fixture_manifest.v1"
    assert manifest["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return manifest


def _fixture_reference(reference: dict) -> Path:
    relative = Path(reference["relative_path"])
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    path = FIXTURE_ROOT / relative
    assert path.is_file(), path
    assert reference["sha256"] == _raw_sha(path)
    return path


def _fixture_for_original(original_path: str) -> Path:
    manifest = _fixture_manifest()
    for reference in manifest["files"].values():
        if reference["original_path"] == original_path:
            return _fixture_reference(reference)
    raise AssertionError(f"missing frozen fixture for {original_path}")


def _assert_commit(value: str) -> None:
    manifest = _fixture_manifest()
    commit = manifest["commits"].get(value)
    assert commit is not None, value
    assert commit["commit"] == value
    for reference in commit["files"].values():
        _fixture_reference(reference)


def _materialize_data_root(receipt: dict, root: Path) -> Path:
    """Materialize only the frozen base/overlay evidence into an isolated root."""
    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    base = _fixture_for_original(receipt["frozen_inputs"]["base_payload"]["path"])
    shutil.copyfile(base, data_root / "preselection" / "20260730.json")
    base_receipt = _fixture_for_original("receipts/20260730.json")
    shutil.copyfile(base_receipt, data_root / "receipts" / "20260730.json")
    (data_root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (data_root / "manifest.json").write_text(
        json.dumps(
            {"preselection/20260730.json": receipt["frozen_inputs"]["base_payload"]["raw_sha256"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    for original, destination in (
        (
            receipt["materialized_overlay"]["payload"]["path"],
            data_root / "preselection_overlays" / "20260730.json",
        ),
        (
            receipt["materialized_overlay"]["manifest"]["path"],
            data_root / "preselection_overlays" / "manifest.json",
        ),
        (
            receipt["materialized_overlay"]["receipt"]["path"],
            data_root / "preselection_overlays" / "receipts" / "20260730.json",
        ),
    ):
        shutil.copyfile(_fixture_for_original(original), destination)
    return data_root


def _validate(receipt: dict) -> None:
    manifest = _fixture_manifest()
    assert set(receipt["commits"].values()) == set(manifest["commits"])
    assert manifest["files"]["receipt"]["original_path"] == (
        "docs/evidence/phase2-preselection-optional-pools-remediation-20260801.json"
    )
    _fixture_reference(manifest["files"]["receipt"])
    assert receipt["schema_version"] == "v3_5.phase2_preselection_optional_pools_remediation.v1"
    assert receipt["status"] == (
        "PASS_FROZEN_ARTIFACT_API_AND_PAGE_WITH_DECLARED_PARITY_GAPS"
    )
    assert receipt["evidence_semantic_hash"] == _semantic_hash(receipt, "evidence_semantic_hash")
    for commit in receipt["commits"].values():
        _assert_commit(commit)
    contract_path = _fixture_for_original(receipt["contract"]["path"])
    contract = _load(contract_path)
    assert receipt["contract"]["raw_sha256"] == _raw_sha(contract_path)
    assert receipt["contract"]["semantic_hash"] == contract["semantic_hash"]
    assert contract["semantic_hash"] == _semantic_hash(contract, "semantic_hash")
    for reference in receipt["implementation"].values():
        assert reference["sha256"] == _raw_sha(_fixture_for_original(reference["path"]))
    assert receipt["frozen_inputs"]["base_payload"]["raw_sha256"] == _raw_sha(
        _fixture_for_original(receipt["frozen_inputs"]["base_payload"]["path"])
    )
    for field in ("payload", "manifest", "receipt"):
        reference = receipt["materialized_overlay"][field]
        assert reference["raw_sha256"] == _raw_sha(_fixture_for_original(reference["path"]))

    with tempfile.TemporaryDirectory(
        prefix="phase2-preselection-optional-",
        dir=os.environ.get("TMPDIR"),
    ) as temporary:
        data_root = _materialize_data_root(receipt, Path(temporary))
        base = NativeDataStore(data_root).read_payload(receipt["business_date"])
        assert len(base["rows"]) == receipt["frozen_inputs"]["base_payload"]["row_count"]
        response = TestClient(create_app(data_root=data_root)).get(
            "/api/v3/preselection-pools",
            params={"date": receipt["business_date"], "limit": 200},
        )
        assert response.status_code == 200
        body = response.json()
        expected = receipt["in_process_api"]
        assert [pool["pool_id"] for pool in body["pools"]] == expected["pool_order"]
        assert [pool["pool_size"] for pool in body["pools"]] == expected["pool_sizes"]
        for field in ("pool_count", "row_count", "unified_row_count", "a_all_pool_row_count", "optional_pool_status"):
            assert body[field] == expected[field]
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == expected["canonical_payload_sha256"]
        assert len(base["rows"]) == 259
    live_reference = receipt["live_acceptance"]
    live = _load(_fixture_for_original(live_reference["path"]))
    assert live_reference["semantic_hash"] == live["evidence_semantic_hash"]
    assert live["evidence_semantic_hash"] == _semantic_hash(
        live, "evidence_semantic_hash"
    )
    assert live_reference["status"] == live["status"]
    assert receipt["live_runtime_observation"] == {
        "status": "PASS_CURRENT_SERVICE_RELOADED",
        "payload_sha256": expected["canonical_payload_sha256"],
        "pool_count": 7,
        "row_count": 302,
    }
    assert receipt["claims"] == {
        "base_payload_unchanged": True,
        "optional_overlay_materialized": True,
        "seven_independent_pools_verified_in_process": True,
        "stage_input_reads_base_only": True,
        "cannot_confirm_visible_in_component_test": True,
        "deployed": False,
        "local_deployed": True,
        "seven_independent_pools_verified_live": True,
        "ui_verified": True,
        "user_final_acceptance": False,
    }
    assert receipt["cannot_confirm"] == [
        "BUSINESS_PARITY_SOURCE_SHA_MISMATCH",
        "ORIGINAL_ATLAS_038_NOT_PRESENT",
    ]
    assert receipt["validation"]["full_python"] == {"passed": 387, "skipped": 1}
    assert receipt["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "v3_written": False,
        "windows_tasks_changed": False,
    }


def test_preselection_optional_pool_receipt_is_machine_bound() -> None:
    _validate(_load(RECEIPT))


@pytest.mark.parametrize("mutation", ("count", "order", "deployed", "overlay_sha", "safety"))
def test_preselection_optional_pool_receipt_rejects_rehashed_tamper(mutation: str) -> None:
    receipt = deepcopy(_load(RECEIPT))
    if mutation == "count":
        receipt["in_process_api"]["row_count"] = 301
    elif mutation == "order":
        receipt["in_process_api"]["pool_order"].reverse()
    elif mutation == "deployed":
        receipt["claims"]["deployed"] = True
    elif mutation == "overlay_sha":
        receipt["materialized_overlay"]["payload"]["raw_sha256"] = "f" * 64
    else:
        receipt["safety"]["buy_gate_updated"] = True
    receipt["evidence_semantic_hash"] = _semantic_hash(receipt, "evidence_semantic_hash")
    with pytest.raises(AssertionError):
        _validate(receipt)
