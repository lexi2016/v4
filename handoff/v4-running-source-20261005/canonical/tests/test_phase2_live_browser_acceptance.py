from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/phase2-live-browser-acceptance-20260801.json"
DATA_ROOT = ROOT / ".runtime/data"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: dict, field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _canonical_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _assert_commit(commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0


def _get(client: TestClient, request: str) -> dict:
    target = request.removeprefix("GET ")
    response = client.get(target)
    assert response.status_code == 200
    return response.json()


def _validate(payload: dict) -> None:
    assert payload["schema_version"] == "v3_5.phase2_live_browser_acceptance.v1"
    assert payload["status"] == (
        "PASS_LOCAL_DEPLOYMENT_API_AND_PAGE_WITH_DECLARED_PARITY_GAPS"
    )
    assert payload["evidence_semantic_hash"] == _semantic_hash(
        payload, "evidence_semantic_hash"
    )
    _assert_commit(payload["code_commit"])

    runtime = payload["runtime"]
    assert runtime["local_service_reloaded"] is True
    assert runtime["local_deployed"] is True
    assert runtime["production_deployed"] is False

    browser = payload["browser"]
    assert browser["client"] == "Codex In-app Browser"
    assert browser["browser_observed"] is True
    assert browser["user_final_acceptance"] is False
    assert browser["horizontal_overflow"] is False
    assert browser["application_console_errors"] == 0
    assert browser["application_console_warnings"] == 0
    assert browser["loading_ended"] is True

    screenshots = [
        payload["features"]["preselection.pools"]["page"]["screenshot"],
        payload["features"]["review.close"]["page"]["screenshot"],
        payload["features"]["research.desk"]["page"]["exact_screenshot"],
        payload["features"]["research.desk"]["page"]["latest_screenshot"],
    ]
    for reference in screenshots:
        path = ROOT / reference["path"]
        assert path.is_file()
        assert path.stat().st_size == reference["bytes"]
        assert _raw_sha(path) == reference["raw_sha256"]

    client = TestClient(create_app(data_root=DATA_ROOT))
    pools = payload["features"]["preselection.pools"]
    pool_body = _get(client, pools["api"]["request"])
    assert _canonical_sha(pool_body) == pools["api"]["canonical_payload_sha256"]
    assert [item["pool_id"] for item in pool_body["pools"]] == pools["api"][
        "pool_order"
    ]
    assert [item["pool_size"] for item in pool_body["pools"]] == pools["api"][
        "pool_sizes"
    ]
    for field in ("pool_count", "row_count", "unified_row_count", "a_all_pool_row_count"):
        assert pool_body[field] == pools["api"][field]

    stage = payload["features"]["stage.workbench"]
    stage_body = _get(client, stage["api"]["request"])
    assert _canonical_sha(stage_body) == stage["api"]["canonical_payload_sha256"]
    assert stage_body["selection_mode"] == stage["api"]["selection_mode"]
    assert stage_body["response_source"] == stage["api"]["response_source"]
    assert stage_body["selected_a_rows"] == stage["api"]["a_selected"] == 50
    assert stage_body["selected_hk_rows"] == stage["api"]["hk_selected"] == 20
    assert stage_body["selected_total_rows"] == stage["api"]["selected_total"] == 70
    assert stage_body["markets"]["A"]["requested_rows"] == stage["api"]["a_requested"]
    assert stage_body["markets"]["A"]["source_rows"] == stage["api"]["a_source"]
    assert stage_body["markets"]["A"]["candidate_count"] == stage["api"]["a_candidate"]
    assert stage_body["opening_second_filter"]["model_id"] == stage["api"]["model_id"]
    assert stage_body["opening_second_filter"]["version"] == stage["api"]["model_version"]

    review = payload["features"]["review.close"]
    review_body = _get(client, review["api"]["request"])
    assert _canonical_sha(review_body) == review["api"]["canonical_payload_sha256"]
    a_review = review_body["market_reviews"]["A"]
    hk_review = review_body["market_reviews"]["HK"]["model_selection_review"]
    assert len(a_review["observation_pool"]) == review["api"]["a_observation_rows"]
    assert len(a_review["core_stocks"]) == review["api"]["a_formal_core_rows"]
    assert a_review["market_regime"] == review["api"]["a_market_regime"]
    assert a_review["risk_tone"] == review["api"]["a_risk_tone"]
    assert hk_review["status"] == review["api"]["hk_status"]
    assert len(hk_review["close_top20"]) == review["api"]["hk_close_top20_rows"]

    research = payload["features"]["research.desk"]
    exact_body = _get(client, research["api"]["exact"]["request"])
    latest_body = _get(client, research["api"]["latest"]["request"])
    assert _canonical_sha(exact_body) == research["api"]["exact"][
        "canonical_payload_sha256"
    ]
    assert _canonical_sha(latest_body) == research["api"]["latest"][
        "canonical_payload_sha256"
    ]
    assert exact_body["status"] == "READY"
    assert exact_body["endpoint_mode"] == "EXACT"
    assert exact_body["article_count"] == 336
    assert exact_body["stock_pool_count"] == 205
    assert exact_body["loading_complete"] is True
    assert latest_body["status"] == "NOT_MATERIALIZED"
    assert latest_body["endpoint_mode"] == "LATEST"
    assert latest_body["article_count"] == latest_body["stock_pool_count"] == 0
    assert latest_body["loading_complete"] is True

    readyz = payload["readyz"]
    ready_body = _get(client, readyz["request"])
    assert _canonical_sha(ready_body) == readyz["canonical_payload_sha256"]
    assert ready_body == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    assert payload["claims"] == {
        "artifact_lane_verified": True,
        "live_api_lane_verified": True,
        "in_app_browser_page_lane_verified": True,
        "local_deployed": True,
        "production_deployed": False,
        "business_parity_verified": False,
        "user_final_acceptance": False,
    }
    assert payload["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "v3_written": False,
        "windows_tasks_changed": False,
    }


def test_live_browser_acceptance_is_machine_bound_and_fail_closed() -> None:
    _validate(_load(EVIDENCE))


@pytest.mark.parametrize(
    "mutation",
    ("api_sha", "page", "screenshot_sha", "production", "user_acceptance"),
)
def test_live_browser_acceptance_rejects_rehashed_tamper(mutation: str) -> None:
    payload = deepcopy(_load(EVIDENCE))
    if mutation == "api_sha":
        payload["features"]["stage.workbench"]["api"][
            "canonical_payload_sha256"
        ] = "f" * 64
    elif mutation == "page":
        payload["browser"]["application_console_errors"] = 1
    elif mutation == "screenshot_sha":
        payload["features"]["review.close"]["page"]["screenshot"][
            "raw_sha256"
        ] = "f" * 64
    elif mutation == "production":
        payload["safety"]["production_allowed"] = True
    else:
        payload["browser"]["user_final_acceptance"] = True
    payload["evidence_semantic_hash"] = _semantic_hash(
        payload, "evidence_semantic_hash"
    )
    with pytest.raises(AssertionError):
        _validate(payload)
