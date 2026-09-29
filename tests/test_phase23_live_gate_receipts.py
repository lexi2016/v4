from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PHASE2 = ROOT / "docs/evidence/phase2-gate-receipt-20260801.json"
PHASE3 = ROOT / "docs/evidence/phase3-gate-receipt-20260801.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _validate(payload: dict, phase: str) -> None:
    assert payload["schema_version"] == "v3_5.phase_gate_receipt.v1"
    assert payload["phase"] == phase
    assert payload["status"] == "PASS_WITH_DECLARED_CANNOT_CONFIRM"
    assert payload["gate_semantic_hash"] == _semantic_hash(
        payload, "gate_semantic_hash"
    )

    reference = payload["live_acceptance"]
    live = _load(ROOT / reference["path"])
    assert reference["semantic_hash"] == live["evidence_semantic_hash"]
    assert live["evidence_semantic_hash"] == _semantic_hash(
        live, "evidence_semantic_hash"
    )
    assert reference["status"] == live["status"]

    claims = payload["claims"]
    assert claims["implemented"] is True
    assert claims["tested"] is True
    assert claims["integrated"] is True
    assert claims["artifact_lane_verified"] is True
    assert claims["live_api_lane_verified"] is True
    assert claims["page_lane_verified"] is True
    assert claims["ui_verified"] is True
    assert claims["local_deployed"] is True
    assert claims["deployed"] is False
    assert claims["business_parity_verified"] is False
    assert claims["user_final_acceptance"] is False
    assert "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE" not in payload["cannot_confirm"]
    assert "V35_LIVE_SERVICE_NOT_RELOADED" not in payload["cannot_confirm"]
    assert payload["validation"]["codex_in_app_browser"] == "PASS"
    assert payload["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
    }

    if phase == "PHASE_2":
        assert payload["outcomes"]["a_share_0925"] == {
            "candidate": 50,
            "missing_symbols": ["A.300333"],
            "model_version": "1.1",
            "requested": 147,
            "selected": 50,
            "source": 146,
            "source_method": "pytdx.hq.get_history_transaction_data",
        }
        assert payload["outcomes"]["preselection_pool_sizes"] == {
            "a_d1_fupan_watchlist_pool": 64,
            "a_d1_premarket_pool": 19,
            "a_d1_stage7_fenshi_review_pool": 70,
            "a_share_baimao_research_map": 0,
            "a_share_research_recommendation_pool": 6,
            "hkconnect_d1_top100": 100,
            "wechat_public_account_v3_preselect": 43,
        }
    else:
        contract = payload["outcomes"]["research_contract"]
        assert contract["exact_date_isolated"] is True
        assert contract["not_materialized_typed"] is True
        assert contract["exact_page_article_count"] == 336
        assert contract["exact_page_stock_pool_count"] == 205
        assert contract["latest_missing_placeholder_visible"] is True
        assert contract["loading_ended"] is True


@pytest.mark.parametrize(("path", "phase"), ((PHASE2, "PHASE_2"), (PHASE3, "PHASE_3")))
def test_phase_gate_live_evidence_is_self_hashed_and_fail_closed(
    path: Path, phase: str
) -> None:
    _validate(_load(path), phase)


@pytest.mark.parametrize(("path", "phase"), ((PHASE2, "PHASE_2"), (PHASE3, "PHASE_3")))
@pytest.mark.parametrize("mutation", ("ui", "deployment", "parity", "safety"))
def test_phase_gate_rejects_rehashed_claim_inflation(
    path: Path, phase: str, mutation: str
) -> None:
    payload = deepcopy(_load(path))
    if mutation == "ui":
        payload["claims"]["ui_verified"] = False
    elif mutation == "deployment":
        payload["claims"]["deployed"] = True
    elif mutation == "parity":
        payload["claims"]["business_parity_verified"] = True
    else:
        payload["safety"]["orders_sent"] = True
    payload["gate_semantic_hash"] = _semantic_hash(payload, "gate_semantic_hash")
    with pytest.raises(AssertionError):
        _validate(payload, phase)
