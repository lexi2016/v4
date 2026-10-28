"""Regression: a verified canonical READY Top100 is a close-review input."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from ops import build_close_review as producer


DATE = "20261021"
POOL_ID = "hkconnect_d1_top100"


def _pool():
    run_id = f"{DATE}-hk-connect-d1-top100-0-2-0123456789ab"
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": DATE, "target_date": DATE, "signal_date": "20261020",
        "pool_id": POOL_ID, "display_name": "HK D-1 Top100", "market": "HK",
        "status": "READY", "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2", "stage_selection_eligible": True,
        "source_path": f"runs/{DATE}/HK_CONNECT_D1_TOP100_0_2/{run_id}/artifact.csv",
        "source_run_id": run_id, "source_row_count": 100,
        "source_sha256": "a" * 64, "source_artifact_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64, "source_receipt_sha256": "c" * 64,
        "rows": [{"market": "HK", "symbol": f"HK.{i:05d}", "pool_rank": i,
                  "target_date": DATE, "recommendation_status": "WATCH_ONLY"}
                 for i in range(1, 101)],
        "cannot_confirm": ["RESEARCH_ONLY_NOT_BUY_GATE"],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }


def _store(root):
    PreselectionPoolStore(root).materialize(_pool())
    CloseSnapshotStore(root).import_snapshot({
        "schema_version": "v3_5.hkconnect_close_snapshot.v1", "trade_date": DATE,
        "status": "READY", "source_mode": "TDX_VIPDOC_DAILY_PANEL",
        "source_input_sha256": "d" * 64, "universe_count": 600,
        "same_date_row_count": 600, "coverage_ratio": 1.0,
        "rows": [{"trade_date": DATE, "code": f"HK.{i:05d}",
                  "close": 100 + 601 - i, "pre_close": 100, "amount": i}
                 for i in range(1, 601)],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    })


def test_verified_ready_trio_is_consumed_by_existing_close_builder(tmp_path):
    root = tmp_path / "data"
    _store(root)
    review = producer.build_close_review(root, DATE)["review"]
    assert review["row_counts"]["model_0_2"] == 100
    metric = review["models"]["0.2_prob_active"]
    assert metric["evidence_status"] == "READY"
    assert metric["selected_count"] == 100 and metric["hit_count"] == 20
    assert metric["coverage_pct"] == 100 and metric["precision_pct"] == 20
    assert review["status"] == "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"
    assert review["missing_stages"] == list(producer._REVIEW_STAGE_IDS)
    assert review["stage_union"]["evidence_status"] == "MISSING"
    assert review["model_source_evidence"]["source_manifest_sha256"] == "b" * 64
    assert ReviewStore(root).read_reference(DATE) == review
    assert all(review[k] is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_ready_cannot_be_admitted_as_a_standalone_unverified_payload():
    assert producer._model_rows(_pool(), DATE) == []


@pytest.mark.parametrize(("key", "value"), [
    ("status", "PARTIAL_WITH_ROWS"), ("status", "CANNOT_CONFIRM"),
    ("pool_id", "other"), ("trade_date", "20261020"), ("target_date", "20261020"),
    ("schema_version", "other"), ("market", "A"),
    ("producer_id", "unverified"), ("source_role", "RAW_SOURCE"),
    ("source_role", "VERIFIED_HK_0_2_STANDARD"), ("stage_selection_eligible", False),
    ("source_sha256", "bad"), ("source_manifest_sha256", ""),
    ("source_receipt_sha256", "bad"), ("source_artifact_sha256", "e" * 64),
    ("production_allowed", True), ("buy_gate_updated", True), ("orders_sent", True),
])
def test_ready_rejects_invalid_identity_provenance_and_safety(key, value):
    payload = _pool()
    payload[key] = value
    assert producer._model_rows(payload, DATE, verified_pool=True) == []


@pytest.mark.parametrize("defect", ["short", "duplicate", "date", "market"])
def test_ready_preserves_exact_100_unique_same_date_hk_rows(defect):
    payload = _pool()
    if defect == "short":
        payload["rows"].pop()
    elif defect == "duplicate":
        payload["rows"][-1] = deepcopy(payload["rows"][0])
    elif defect == "date":
        payload["rows"][-1]["target_date"] = "20261020"
    else:
        payload["rows"][-1]["market"] = "A"
    assert producer._model_rows(payload, DATE, verified_pool=True) == []


@pytest.mark.parametrize("part", ["artifact", "manifest", "receipt"])
def test_ready_corrupt_trio_fails_before_review_publication(tmp_path, part):
    root = tmp_path / "data"
    _store(root)
    base = root / "preselection_pools" / DATE
    path = {"artifact": base / f"{POOL_ID}.json", "manifest": base / "manifest.json",
            "receipt": base / "receipts" / f"{POOL_ID}.json"}[part]
    content = json.loads(path.read_text())
    if part == "artifact":
        content["display_name"] = "tampered"
    elif part == "manifest":
        content[POOL_ID] = "0" * 64
    else:
        content["artifact_sha256"] = "0" * 64
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="manifest or receipt SHA mismatch"):
        producer.build_close_review(root, DATE)
    assert not (root / "close_reviews" / f"{DATE}.json").exists()


def test_legacy_strict_status_keeps_existing_contract():
    payload = _pool()
    payload["status"] = "STRICT_0_2_READY"
    payload["producer_id"] = "verified.legacy"
    for key in ("source_manifest_sha256", "source_receipt_sha256", "target_date", "stage_selection_eligible"):
        payload.pop(key)
    assert len(producer._model_rows(payload, DATE)) == 100
