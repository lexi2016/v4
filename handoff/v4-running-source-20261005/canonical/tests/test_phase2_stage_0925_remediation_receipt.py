from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/evidence/phase2-stage-0925-v11-remediation-20260801.json"


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


def _assert_commit(commit: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0


def _validate(receipt: dict) -> None:
    assert receipt["schema_version"] == "v3_5.phase2_stage_0925_remediation.v1"
    assert receipt["status"] == "PASS_FROZEN_MODEL_PARITY_WITH_RUNTIME_GAPS"
    assert receipt["evidence_semantic_hash"] == _semantic_hash(
        receipt, "evidence_semantic_hash"
    )
    for commit in receipt["commits"].values():
        _assert_commit(commit)
    for reference in receipt["frozen_contracts"].values():
        path = ROOT / reference["path"]
        payload = _load(path)
        assert reference["raw_sha256"] == _raw_sha(path)
        assert reference["semantic_hash"] == payload["semantic_hash"]
        assert payload["semantic_hash"] == _semantic_hash(
            payload, "semantic_hash"
        )
    adapter_path = ROOT / receipt["implementation"]["adapter_path"]
    assert receipt["implementation"]["adapter_sha256"] == _raw_sha(adapter_path)
    data_contract = _load(
        ROOT / receipt["frozen_contracts"]["data_chain"]["path"]
    )
    parity_contract = _load(
        ROOT / receipt["frozen_contracts"]["model_parity"]["path"]
    )
    expected = data_contract["expected"]
    assert receipt["outcomes"] == {
        "candidate_a": expected["candidate_a"],
        "missing_symbols": expected["missing_symbols"],
        "model_projection_sha256": parity_contract["expected"][
            "projection_sha256"
        ],
        "model_version": "1.1",
        "requested_a": expected["requested_a"],
        "selected_a": expected["selected_a"],
        "source_a": expected["source_a"],
        "source_method": "pytdx.hq.get_history_transaction_data",
    }
    performance_ref = receipt["performance_status"]
    performance = _load(ROOT / performance_ref["path"])
    assert performance_ref["semantic_hash"] == performance[
        "evidence_semantic_hash"
    ]
    assert performance_ref["status"] == performance["status"]
    assert performance["claims"]["current_performance_verified"] is True
    assert performance["claims"]["current_rebenchmark_required"] is False
    assert receipt["claims"] == {
        "current_performance_verified": True,
        "data_chain_counts_verified": True,
        "deployed": False,
        "frozen_v3_v11_model_parity_verified": True,
        "legacy_live_source_parity_verified": False,
        "ui_verified": False,
    }
    assert receipt["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
        "v3_written": False,
        "windows_tasks_changed": False,
    }


def test_phase2_stage_0925_receipt_is_evidence_bound_and_fail_closed() -> None:
    _validate(_load(RECEIPT))


@pytest.mark.parametrize(
    "mutation",
    ("projection", "counts", "ui", "performance", "adapter"),
)
def test_phase2_stage_0925_receipt_rejects_rehashed_tamper(
    mutation: str,
) -> None:
    receipt = deepcopy(_load(RECEIPT))
    if mutation == "projection":
        receipt["outcomes"]["model_projection_sha256"] = "f" * 64
    elif mutation == "counts":
        receipt["outcomes"]["selected_a"] = 49
    elif mutation == "ui":
        receipt["claims"]["ui_verified"] = True
    elif mutation == "performance":
        receipt["claims"]["current_performance_verified"] = False
    else:
        receipt["implementation"]["adapter_sha256"] = "f" * 64
    receipt["evidence_semantic_hash"] = _semantic_hash(
        receipt, "evidence_semantic_hash"
    )

    with pytest.raises(AssertionError):
        _validate(receipt)
