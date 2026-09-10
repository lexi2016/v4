import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.modules.setdefault("httpx2", httpx)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.research_router import create_research_router
from contracts.research_day_product import (
    SAFETY_FLAGS,
    SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION,
    SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE,
    selection_source_scope_invalidation_id,
)
from infrastructure.research_store import ResearchSelectionStore


OLD_ARTIFACT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "research/selection/20260831/manager-20260831-0830-freeze-v1.json"
)
OLD_ARTIFACT_SHA256 = "0c4a8d4f27b7df693c2394dbcdee60afeb8e68b748807935457cbaa928ab6b85"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _old_product() -> dict:
    assert _sha(OLD_ARTIFACT) == OLD_ARTIFACT_SHA256
    return json.loads(OLD_ARTIFACT.read_text(encoding="utf-8"))


def _scope_invalidation(product: dict, evidence_root: Path) -> dict:
    evidence_root.mkdir(parents=True, exist_ok=True)
    dispatcher_path = evidence_root / "dispatcher.json"
    hourly_path = evidence_root / "hourly.json"
    dispatcher_path.write_text(
        json.dumps({"eligible_markets": ["a_share"]}), encoding="utf-8"
    )
    hourly_path.write_text(
        json.dumps({"market_scope": "A_SHARE", "row_count": 379}),
        encoding="utf-8",
    )
    record = {
        "schema_version": SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION,
        "type": SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE,
        "invalidation_id": None,
        "source_date": product["source_date"],
        "target_trade_date": product["target_trade_date"],
        "prior_run_id": product["run_id"],
        "prior_product_sha256": OLD_ARTIFACT_SHA256,
        "expected_market_focus": "HK_CONNECT",
        "observed_source_scope": "A_SHARE",
        "evidence_refs": [
            {
                "kind": "DISPATCHER",
                "path": str(dispatcher_path),
                "raw_sha256": _sha(dispatcher_path),
                "json_pointer": "/eligible_markets",
                "observed_source_scope": "A_SHARE",
            },
            {
                "kind": "HOURLY",
                "path": str(hourly_path),
                "raw_sha256": _sha(hourly_path),
                "json_pointer": "/market_scope",
                "observed_source_scope": "A_SHARE",
            },
        ],
        "reason": "UPSTREAM_MARKET_SCOPE_MISMATCH",
        "generated_at": "2026-08-31T10:00:00+08:00",
        "safety": dict(SAFETY_FLAGS),
    }
    record["invalidation_id"] = selection_source_scope_invalidation_id(record)
    return record


def _api(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    return TestClient(app)


def test_selection_api_forces_hk_connect_market_focus(tmp_path):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))

    response = TestClient(app).get(
        "/api/v3/research/selection?target_trade_date=20260831&market_focus=A_SHARE"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANNOT_CONFIRM"
    assert body["first_failed_layer"] == "SELECTION_MARKET_FOCUS_FORCED:HK_CONNECT"
    assert body["cannot_confirm"] == ["SELECTION_MARKET_FOCUS_FORCED:HK_CONNECT"]
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_old_hk_product_is_invalidated_by_a_share_upstream_scope_record(tmp_path):
    store = ResearchSelectionStore(tmp_path)
    product = _old_product()
    published = store.publish(product)
    artifact_path = tmp_path / published["artifact_path"]
    current_path = tmp_path / published["current_path"]
    artifact_before = artifact_path.read_bytes()
    current_before = current_path.read_bytes()
    record = _scope_invalidation(product, tmp_path / "evidence")
    record["prior_product_sha256"] = published["artifact_sha256"]
    record["invalidation_id"] = selection_source_scope_invalidation_id(record)
    store.publish_source_scope_invalidation(record)

    assert artifact_path.read_bytes() == artifact_before
    assert current_path.read_bytes() == current_before

    body = _api(tmp_path).get(
        "/api/v3/research/selection?target_trade_date=20260831"
    ).json()

    assert body["status"] == "CANNOT_CONFIRM"
    assert body["research_candidates"] == []
    assert body["first_failed_layer"].startswith("SELECTION_PRODUCT_INVALID:")
    assert "SOURCE_SCOPE_INVALIDATED" in body["first_failed_layer"]
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_strict_hk_product_without_matching_scope_record_remains_readable(tmp_path):
    product = _old_product()
    ResearchSelectionStore(tmp_path).publish(product)

    body = _api(tmp_path).get(
        "/api/v3/research/selection?target_trade_date=20260831"
    ).json()

    assert body["status"] == "READY_WITH_DECLARED_GAPS"
    assert len(body["research_candidates"]) == 124
    assert {row["market"] for row in body["research_candidates"]} == {"HK"}
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


@pytest.mark.parametrize("tamper_kind", ["record", "evidence"])
def test_scope_invalidation_tamper_or_evidence_sha_mismatch_fails_closed(
    tmp_path, tamper_kind
):
    store = ResearchSelectionStore(tmp_path)
    product = _old_product()
    published = store.publish(product)
    evidence_root = tmp_path / "evidence"
    record = _scope_invalidation(product, evidence_root)
    record["prior_product_sha256"] = published["artifact_sha256"]
    record["invalidation_id"] = selection_source_scope_invalidation_id(record)
    result = store.publish_source_scope_invalidation(record)

    if tamper_kind == "record":
        record_path = tmp_path / result["record_path"]
        record_path.write_text(
            record_path.read_text(encoding="utf-8").replace(
                "UPSTREAM_MARKET_SCOPE_MISMATCH", "TAMPERED"
            ),
            encoding="utf-8",
        )
    else:
        evidence_path = Path(record["evidence_refs"][0]["path"])
        evidence_path.write_text(
            evidence_path.read_text(encoding="utf-8").replace(
                "a_share", "hk_connect"
            ),
            encoding="utf-8",
        )

    response = _api(tmp_path).get(
        "/api/v3/research/selection?target_trade_date=20260831"
    )
    body = response.json()
    assert body["status"] == "CANNOT_CONFIRM"
    assert body["research_candidates"] == []
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False
