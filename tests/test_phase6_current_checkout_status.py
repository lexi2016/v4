from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/evidence/phase6-current-checkout-status-20260801.json"


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


def _file_sha_at_commit(commit: str, relative: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return hashlib.sha256(completed.stdout).hexdigest()


def _assert_commit_exists(commit: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def _validate(payload: dict) -> None:
    assert payload["schema_version"] == "v3_5.phase6_current_checkout_status.v1"
    assert payload["status"] == "HISTORICAL_AND_CURRENT_PERFORMANCE_PASS"
    assert payload["evidence_semantic_hash"] == _semantic_hash(
        payload, "evidence_semantic_hash"
    )
    historical = payload["historical_phase6"]
    contract_ref = historical["contract"]
    evidence_ref = historical["evidence"]
    contract_path = ROOT / contract_ref["path"]
    evidence_path = ROOT / evidence_ref["path"]
    contract = _load(contract_path)
    evidence = _load(evidence_path)
    assert contract_ref["raw_sha256"] == _raw_sha(contract_path)
    assert contract_ref["semantic_hash"] == contract["semantic_hash"]
    assert contract["semantic_hash"] == _semantic_hash(contract, "semantic_hash")
    assert evidence_ref["raw_sha256"] == _raw_sha(evidence_path)
    assert evidence_ref["semantic_hash"] == evidence["evidence_semantic_hash"]
    assert evidence["evidence_semantic_hash"] == _semantic_hash(
        evidence, "evidence_semantic_hash"
    )
    assert evidence_ref["optimized_commit"] == evidence["optimized"]["code_commit"]
    assert {
        path: _file_sha_at_commit(evidence_ref["optimized_commit"], path)
        for path in contract["business_contract_sha256"]
    } == contract["business_contract_sha256"]

    current = {
        path: _raw_sha(ROOT / path)
        for path in contract["business_contract_sha256"]
    }
    reasons = {
        "contracts/migration/stage_0925_tdxpy_frozen_regression_v1.json": (
            "GRAPH_BOUND_V3_V11_PARITY_REMEDIATION"
        ),
        "domains/preselection.py": "GRAPH_BOUND_PRESELECTION_POOL_REMEDIATION",
    }
    changed = [
        {
            "current_sha256": current[path],
            "frozen_sha256": frozen_sha,
            "path": path,
            "reason": reasons[path],
        }
        for path, frozen_sha in contract["business_contract_sha256"].items()
        if current[path] != frozen_sha
    ]
    assert payload["current_checkout"]["business_contract_changed"] == changed
    assert payload["current_checkout"]["business_contract_unchanged_count"] == (
        len(current) - len(changed)
    )
    observed_commit = payload["current_checkout"]["observed_commit"]
    for item in changed:
        assert _file_sha_at_commit(observed_commit, item["path"]) == item[
            "current_sha256"
        ]
    authority_ref = payload["change_authority"]
    authority_path = ROOT / authority_ref["path"]
    authority = _load(authority_path)
    assert authority_ref["raw_sha256"] == _raw_sha(authority_path)
    assert authority_ref["semantic_hash"] == authority["semantic_hash"]
    assert authority["semantic_hash"] == _semantic_hash(authority, "semantic_hash")
    _assert_commit_exists(authority_ref["implementation_commit"])
    current_rebenchmark = payload["current_rebenchmark"]
    current_contract_ref = current_rebenchmark["contract"]
    current_evidence_ref = current_rebenchmark["evidence"]
    current_contract_path = ROOT / current_contract_ref["path"]
    current_evidence_path = ROOT / current_evidence_ref["path"]
    current_contract = _load(current_contract_path)
    current_evidence = _load(current_evidence_path)
    assert current_contract_ref["raw_sha256"] == _raw_sha(current_contract_path)
    assert current_contract_ref["semantic_hash"] == current_contract["semantic_hash"]
    assert current_contract["semantic_hash"] == _semantic_hash(
        current_contract, "semantic_hash"
    )
    assert current_evidence_ref["raw_sha256"] == _raw_sha(current_evidence_path)
    assert current_evidence_ref["semantic_hash"] == current_evidence[
        "evidence_semantic_hash"
    ]
    assert current_evidence["evidence_semantic_hash"] == _semantic_hash(
        current_evidence, "evidence_semantic_hash"
    )
    assert current_rebenchmark["status"] == current_evidence["status"] == "PASS"
    assert current_evidence["current"]["code_commit"] == observed_commit
    assert payload["claims"] == {
        "current_performance_verified": True,
        "current_rebenchmark_required": False,
        "historical_phase6_pass_verified": True,
    }
    assert payload["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
    }


def test_phase6_status_separates_historical_pass_from_current_checkout() -> None:
    _validate(_load(STATUS))


@pytest.mark.parametrize(
    "mutation",
    ("current_verified", "rebenchmark", "changed_path", "changed_sha"),
)
def test_phase6_status_rejects_rehashed_current_drift_tamper(
    mutation: str,
) -> None:
    payload = deepcopy(_load(STATUS))
    if mutation == "current_verified":
        payload["claims"]["current_performance_verified"] = False
    elif mutation == "rebenchmark":
        payload["claims"]["current_rebenchmark_required"] = True
    elif mutation == "changed_path":
        payload["current_checkout"]["business_contract_changed"][0][
            "path"
        ] = "fabricated.json"
    else:
        payload["current_checkout"]["business_contract_changed"][0][
            "current_sha256"
        ] = "f" * 64
    payload["evidence_semantic_hash"] = _semantic_hash(
        payload, "evidence_semantic_hash"
    )

    with pytest.raises(AssertionError):
        _validate(payload)
