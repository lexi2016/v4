from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "docs/evidence/phase4-gate-receipt-20260801.json"
CONTRACT = ROOT / "contracts/migration/phase4_feature_disposition_v1.json"


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


def _validate(gate: dict) -> None:
    contract = _load(CONTRACT)
    assert gate["schema_version"] == "v3_5.phase_gate_receipt.v1"
    assert gate["phase"] == "PHASE_4"
    assert gate["status"] == "PASS_WITH_DECLARED_CANNOT_CONFIRM"
    assert gate["gate_semantic_hash"] == _semantic_hash(gate, "gate_semantic_hash")
    assert gate["phase4_contract_raw_sha256"] == _raw_sha(CONTRACT)
    assert gate["phase4_contract_semantic_hash"] == contract["semantic_hash"]
    assert contract["semantic_hash"] == _semantic_hash(contract, "semantic_hash")

    live_reference = gate["live_acceptance"]
    live = _load(ROOT / live_reference["path"])
    assert live_reference["semantic_hash"] == live["evidence_semantic_hash"]
    assert live["evidence_semantic_hash"] == _semantic_hash(
        live, "evidence_semantic_hash"
    )
    assert live_reference["status"] == live["status"]

    claims = gate["claims"]
    assert claims["ui_verified"] is True
    assert claims["local_deployed"] is True
    assert claims["deployed"] is False
    assert claims["business_parity_verified"] is False
    assert claims["user_final_acceptance"] is False
    assert "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE" not in gate["cannot_confirm"]
    assert "V35_LIVE_SERVICE_NOT_RELOADED" not in gate["cannot_confirm"]
    assert "FULL_35_TASK_IDENTITY_MAPPING_DEFERRED_TO_PHASE_5" not in gate[
        "cannot_confirm"
    ]
    assert "DISABLED_RUNTIME_TASKS_HAVE_NO_EXECUTION_RECEIPTS" in gate[
        "cannot_confirm"
    ]
    assert gate["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
    }


def test_phase4_live_gate_is_contract_and_browser_bound() -> None:
    _validate(_load(GATE))


@pytest.mark.parametrize("mutation", ("contract", "ui", "deployed", "safety"))
def test_phase4_live_gate_rejects_rehashed_tamper(mutation: str) -> None:
    gate = deepcopy(_load(GATE))
    if mutation == "contract":
        gate["phase4_contract_raw_sha256"] = "f" * 64
    elif mutation == "ui":
        gate["claims"]["ui_verified"] = False
    elif mutation == "deployed":
        gate["claims"]["deployed"] = True
    else:
        gate["safety"]["buy_gate_updated"] = True
    gate["gate_semantic_hash"] = _semantic_hash(gate, "gate_semantic_hash")
    with pytest.raises(AssertionError):
        _validate(gate)
