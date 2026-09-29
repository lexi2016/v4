from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs" / "evidence" / "phase7-inventory-checkpoint-20260801.json"
TERMINAL = ROOT / "contracts" / "migration" / "v35_replacement_inventory_v3.json"
BASE = ROOT / "contracts" / "migration" / "v35_replacement_inventory_v2.json"
IMPLEMENTATION_COMMIT = "573d77fcdbdc51b7e2bdcc65686b2e5c18cfbc0c"
IMPLEMENTATION_FILES = {
    "contracts/migration/v35_replacement_inventory_v3.json",
    "ops/migration/terminal_inventory.py",
    "tests/test_phase7_terminal_inventory.py",
}
EXPECTED_BLOCKERS = [
    "NO_COMPLETE_INVENTORY_RECORDS",
    "NON_PASSING_ARTIFACT_API_PAGE_PARITY_RECEIPTS",
    "DISABLED_RUNTIME_TASKS_HAVE_NO_EXECUTION_RECEIPTS",
]
EXPECTED_VALIDATION = {
    "frontend": {
        "build": "PASS",
        "typecheck": "PASS",
        "vue_tests": {"files_passed": 4, "tests_passed": 24},
    },
    "python_full_suite": {"passed": 326, "skipped": 1},
    "live_acceptance_and_gate_tests": {"passed": 16},
    "terminal_inventory_tests": {"passed": 9},
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: dict, field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _implementation_files(commit: str) -> set[str]:
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert exists.returncode == 0
    changed = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=True,
    )
    return set(changed.stdout.decode("utf-8").splitlines())


def _validate_checkpoint(checkpoint: dict) -> None:
    terminal = _load(TERMINAL)
    base = _load(BASE)

    assert checkpoint["schema_version"] == "v3_5.phase7_inventory_checkpoint.v1"
    assert checkpoint["phase"] == "PHASE_7"
    assert checkpoint["status"] == "AUDIT_COMPLETE_GATE_NOT_PASSED"
    assert checkpoint["evidence_semantic_hash"] == _semantic_hash(
        checkpoint, "evidence_semantic_hash"
    )
    assert checkpoint["inventory"]["base_v2"] == {
        "path": "contracts/migration/v35_replacement_inventory_v2.json",
        "raw_sha256": _raw_sha(BASE),
        "semantic_hash": base["inventory_semantic_hash"],
    }
    terminal_reference = checkpoint["inventory"]["terminal_v3"]
    assert terminal_reference["path"] == (
        "contracts/migration/v35_replacement_inventory_v3.json"
    )
    assert terminal_reference["raw_sha256"] == _raw_sha(TERMINAL)
    assert terminal_reference["semantic_hash"] == terminal["terminal_semantic_hash"]
    assert terminal_reference["terminal_counts"] == terminal["terminal_counts"]
    assert terminal_reference["terminal_counts"] == {
        "by_status": {"CANNOT_CONFIRM": 506},
        "by_terminal_class": {
            "CANNOT_CONFIRM": 500,
            "COMPAT": 4,
            "REMOVE_PROPOSED": 2,
        },
        "complete": 0,
        "total": 506,
    }
    assert checkpoint["claims"] == {
        "business_parity_verified": False,
        "deployed": False,
        "inventory_accounting_complete": True,
        "local_deployed": True,
        "phase7_business_gate_passed": False,
        "phase8_entry_allowed": False,
        "ready_to_replace": False,
        "ui_verified": True,
        "user_final_acceptance": False,
    }
    assert checkpoint["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
        "v3_written": False,
        "windows_tasks_changed": False,
    }
    assert checkpoint["blockers"] == EXPECTED_BLOCKERS
    live_reference = checkpoint["live_acceptance"]
    live = _load(ROOT / live_reference["path"])
    assert live_reference["semantic_hash"] == live["evidence_semantic_hash"]
    assert live["evidence_semantic_hash"] == _semantic_hash(
        live, "evidence_semantic_hash"
    )
    assert live_reference["status"] == live["status"]
    assert checkpoint["implementation_commit"] == IMPLEMENTATION_COMMIT
    assert _implementation_files(checkpoint["implementation_commit"]) == (
        IMPLEMENTATION_FILES
    )
    assert checkpoint["validation"] == EXPECTED_VALIDATION
    authorities = checkpoint["non_passing_slice_receipt_authorities"]
    assert [item["feature_id"] for item in authorities] == [
        "preselection.pools",
        "review.close",
        "stage.workbench",
        "research.desk",
    ]
    for item in authorities:
        authority_path = ROOT / item["authority_path"]
        assert authority_path.is_file()
        authority = _load(authority_path)
        assert item["authority_raw_sha256"] == _raw_sha(authority_path)
        assert item["authority_gate_semantic_hash"] == authority[
            "gate_semantic_hash"
        ]
        assert authority["gate_semantic_hash"] == _semantic_hash(
            authority, "gate_semantic_hash"
        )
        assert authority["safety"] == {
            "buy_gate_updated": False,
            "orders_sent": False,
            "production_allowed": False,
        }
        receipt = authority["parity_receipts"][item["feature_id"]]
        assert item["receipt_semantic_hash"] == receipt[
            "receipt_semantic_hash"
        ]
        assert item["verdict"] == receipt["verdict"] == "CANNOT_CONFIRM"


def test_phase7_checkpoint_is_honest_and_evidence_bound() -> None:
    _validate_checkpoint(_load(CHECKPOINT))


@pytest.mark.parametrize(
    "mutation",
    (
        "complete",
        "phase8",
        "ready",
        "safety",
        "receipt_path",
        "receipt_hash",
        "commit",
        "blocker",
        "validation",
    ),
)
def test_phase7_checkpoint_rejects_rehashed_false_gate_claims(mutation: str) -> None:
    checkpoint = deepcopy(_load(CHECKPOINT))
    if mutation == "complete":
        checkpoint["inventory"]["terminal_v3"]["terminal_counts"]["complete"] = 506
    elif mutation == "phase8":
        checkpoint["claims"]["phase8_entry_allowed"] = True
    elif mutation == "ready":
        checkpoint["claims"]["ready_to_replace"] = True
    elif mutation == "safety":
        checkpoint["safety"]["production_allowed"] = True
    elif mutation == "receipt_path":
        checkpoint["non_passing_slice_receipt_authorities"][0][
            "authority_path"
        ] = "fabricated/missing/receipt.json"
    elif mutation == "receipt_hash":
        checkpoint["non_passing_slice_receipt_authorities"][0][
            "receipt_semantic_hash"
        ] = "f" * 64
    elif mutation == "commit":
        checkpoint["implementation_commit"] = "0" * 40
    elif mutation == "blocker":
        checkpoint["blockers"][0] = "FABRICATED_BLOCKER"
    else:
        checkpoint["validation"]["python_full_suite"]["passed"] = 999999
    checkpoint["evidence_semantic_hash"] = _semantic_hash(
        checkpoint, "evidence_semantic_hash"
    )

    with pytest.raises(AssertionError):
        _validate_checkpoint(checkpoint)
