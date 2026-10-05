import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
import httpx

sys.modules.setdefault("httpx2", httpx)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.research_router import create_research_router
from contracts.research_day_product import validate_manager_decision_projection
from infrastructure.research_store import ResearchSelectionStore
from domains.research_day_product import build_selection_research_product


V4_ROOT = Path(
    "/Users/lexi/Desktop/学习/助手/白毛研究员/research/20260828/"
    "2200_initial_supply_20260831_v4_manager_bridge"
)
SUPPLY_PATH = V4_ROOT / "materialized/research_supply.json"
RECEIPT_PATH = V4_ROOT / "materialized/research_supply_receipt.json"
DECISION_PATH = V4_ROOT / "manager_decision.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_product(*, decision_ref: bool = True, mutate_unselected_review: bool = False):
    envelope = json.loads(SUPPLY_PATH.read_text(encoding="utf-8"))
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
    cards = []
    for index, original_card in enumerate(envelope["frozen_payload"]["event_cards"]):
        card = copy.deepcopy(original_card)
        if mutate_unselected_review and card["ticker"].startswith("02155"):
            # A review bucket is descriptive context only.  It must not create
            # a manager role/order when the typed decision did not select it.
            card["primary_fact_review"] = {
                "status": "READY",
                "priority_bucket": "PRIORITY",
            }
            card["manager_research"] = {
                "status": "READY",
                "priority_bucket": "PRIORITY",
            }
        cards.append(
            {
                "card": card,
                "source_ref": {
                    "type": "RESEARCH_SUPPLY_FROZEN_ENVELOPE",
                    "path": str(SUPPLY_PATH),
                    "raw_sha256": _sha(SUPPLY_PATH),
                    "frozen_payload_sha256": envelope["frozen_payload_sha256"],
                    "json_pointer": f"/frozen_payload/event_cards/{index}",
                    "source_date": "20260828",
                    "source_time": envelope["generated_at"],
                    "supply_receipt_path": str(RECEIPT_PATH),
                    "supply_receipt_sha256": _sha(RECEIPT_PATH),
                },
            }
        )
    ref = {
        "path": str(DECISION_PATH),
        "raw_sha256": _sha(DECISION_PATH),
    }
    return build_selection_research_product(
        "20260828",
        "20260831",
        source_cards=cards,
        source_envelope=envelope,
        generated_at=decision["generated_at"],
        cutoff_at=decision["cutoff_at"],
        run_id=decision["run_id"],
        origin="MANUAL_RECOVERY",
        manager_decision=decision,
        manager_decision_ref=ref if decision_ref else None,
    )


def test_typed_manager_decision_projects_role_and_order_only_to_selected_candidates():
    product = _decision_product(mutate_unselected_review=True)
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
    expected = {
        row["candidate_id"]: ("CORE", order, row["reason"])
        for order, row in enumerate(decision["core"], 1)
    }
    expected.update(
        {
            row["candidate_id"]: ("CONDITIONAL", order, row["reason"])
            for order, row in enumerate(decision["conditional"], 1)
        }
    )

    candidates = {
        candidate["candidate_id"]: candidate
        for candidate in product["research_candidates"]
    }
    assert set(product["snapshots"]["2200"]["candidate_ids"]) == set(expected)
    for candidate_id, candidate in candidates.items():
        card = candidate["source_metadata"]["supply_card"]
        assert "manager_decision" not in card
        if candidate_id not in expected:
            assert "manager_decision" not in candidate
            continue
        role, order, reason = expected[candidate_id]
        assert candidate["manager_decision"] == {
            "schema_version": "v3_5.manager_research_decision.v1",
            "phase": "2200",
            "decision_state": "INITIAL_RESEARCH_DELTA",
            "source_date": "20260828",
            "target_trade_date": "20260831",
            "run_id": "baimao-20260830-manager-research-overlay-v4",
            "generated_at": "2026-08-30T13:38:58.510320+08:00",
            "cutoff_at": "2026-08-28T22:27:18+08:00",
            "role": role,
            "order": order,
            "reason": reason,
        }


def test_manager_decision_requires_a_valid_reference_before_projection():
    with pytest.raises(ValueError, match="manager decision reference"):
        _decision_product(decision_ref=False)


def test_projection_rejects_cutoff_after_generated_at():
    projection = copy.deepcopy(
        next(
            candidate["manager_decision"]
            for candidate in _decision_product()["research_candidates"]
            if "manager_decision" in candidate
        )
    )
    projection["generated_at"] = "2026-08-28T22:00:00+08:00"

    with pytest.raises(ValueError, match="cutoff must not be later than generated_at"):
        validate_manager_decision_projection(
            projection,
            source_date="20260828",
            target_trade_date="20260831",
            cutoff_at="2026-08-28T22:27:18+08:00",
        )


def _projected_ids(product):
    return {
        candidate["candidate_id"]
        for candidate in product["research_candidates"]
        if "manager_decision" in candidate
    }


def test_store_round_trip_preserves_frozen_cards_and_projects_typed_decision(tmp_path):
    product = _decision_product()
    envelope = json.loads(SUPPLY_PATH.read_text(encoding="utf-8"))
    frozen_cards = {
        f"HK.{card['ticker'].split('.')[0]}|{card['ticker']}": card
        for card in envelope["frozen_payload"]["event_cards"]
    }

    store = ResearchSelectionStore(tmp_path)
    published = store.publish(product)
    stored, lineage = store.read_exact_with_lineage("20260831")

    assert published["target_trade_date"] == "20260831"
    assert lineage is not None
    assert stored is not None
    assert _projected_ids(stored) == {
        "HK.02315|02315.HK",
        "HK.03738|03738.HK",
        "HK.06951|06951.HK",
        "HK.06078|06078.HK",
        "HK.01304|01304.HK",
        "HK.01952|01952.HK",
        "HK.02676|02676.HK",
        "HK.02410|02410.HK",
    }
    for candidate in stored["research_candidates"]:
        candidate_id = candidate["candidate_id"]
        assert candidate["source_metadata"] == {
            "supply_card": frozen_cards[candidate_id]
        }


def test_store_api_exact_selection_exposes_only_typed_manager_projection(tmp_path):
    product = _decision_product()
    store = ResearchSelectionStore(tmp_path)
    store.publish(product)

    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    response = TestClient(app).get(
        "/api/v3/research/selection?target_trade_date=20260831"
    )

    assert response.status_code == 200
    body = response.json()
    candidates = {
        candidate["candidate_id"]: candidate
        for candidate in body["research_candidates"]
    }
    assert [
        candidate["candidate_id"]
        for candidate in sorted(
            (
                candidate
                for candidate in candidates.values()
                if candidate.get("manager_decision", {}).get("role") == "CORE"
            ),
            key=lambda candidate: candidate["manager_decision"]["order"],
        )
    ] == [
        "HK.02315|02315.HK",
        "HK.03738|03738.HK",
        "HK.06951|06951.HK",
    ]
    assert [
        candidate["candidate_id"]
        for candidate in sorted(
            (
                candidate
                for candidate in candidates.values()
                if candidate.get("manager_decision", {}).get("role") == "CONDITIONAL"
            ),
            key=lambda candidate: candidate["manager_decision"]["order"],
        )
    ] == [
        "HK.06078|06078.HK",
        "HK.01304|01304.HK",
        "HK.01952|01952.HK",
        "HK.02676|02676.HK",
        "HK.02410|02410.HK",
    ]
    assert "manager_decision" not in candidates["HK.09926|09926.HK"]


@pytest.mark.parametrize("tamper", ["reason", "order", "role"])
def test_store_rejects_projection_tampering_against_decision_document(tmp_path, tamper):
    product = _decision_product()
    candidates = {
        candidate["candidate_id"]: candidate
        for candidate in product["research_candidates"]
    }
    if tamper == "reason":
        candidates["HK.02315|02315.HK"]["manager_decision"]["reason"] += " tampered"
    elif tamper == "order":
        first = candidates["HK.02315|02315.HK"]["manager_decision"]
        second = candidates["HK.03738|03738.HK"]["manager_decision"]
        first["order"], second["order"] = second["order"], first["order"]
    else:
        core = candidates["HK.02315|02315.HK"]["manager_decision"]
        conditional = candidates["HK.06078|06078.HK"]["manager_decision"]
        core["role"], conditional["role"] = "CONDITIONAL", "CORE"

    with pytest.raises(ValueError, match="manager decision projection"):
        ResearchSelectionStore(tmp_path).publish(product)


def test_store_rejects_partial_projection_against_ready_decision_snapshot(tmp_path):
    product = _decision_product()
    for candidate in product["research_candidates"]:
        if candidate["candidate_id"] == "HK.02315|02315.HK":
            candidate.pop("manager_decision")
            break

    with pytest.raises(ValueError, match="manager decision projection"):
        ResearchSelectionStore._verify_product_sources(product)


def test_legacy_product_without_projection_remains_readable(tmp_path):
    product = _decision_product()
    for candidate in product["research_candidates"]:
        candidate.pop("manager_decision", None)

    store = ResearchSelectionStore(tmp_path)
    store.publish(product)
    stored, _ = store.read_exact_with_lineage("20260831")

    assert stored is not None
    assert all("manager_decision" not in candidate for candidate in stored["research_candidates"])
