from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from ops.migration.terminal_inventory import (
    TerminalInventoryError,
    build_terminal_inventory,
    semantic_hash,
    validate_terminal_inventory,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "contracts" / "migration" / "v35_replacement_inventory_v2.json"
GRAPH = ROOT / "contracts" / "migration" / "v3_graph_baseline_v2.json"
PHASE4 = ROOT / "contracts" / "migration" / "phase4_feature_disposition_v1.json"
PHASE5 = (
    ROOT
    / "contracts"
    / "migration"
    / "phase5_runtime_governance_audit_v1.json"
)
TERMINAL = (
    ROOT
    / "contracts"
    / "migration"
    / "v35_replacement_inventory_v3.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs() -> tuple[dict, dict, dict, dict]:
    return _load(BASE), _load(GRAPH), _load(PHASE4), _load(PHASE5)


def test_checked_in_terminal_inventory_matches_deterministic_builder() -> None:
    base, graph, phase4, phase5 = _inputs()
    expected = build_terminal_inventory(
        base_inventory=base,
        graph_baseline=graph,
        phase4_contract=phase4,
        phase5_audit=phase5,
        repo_root=ROOT,
    )
    actual = _load(TERMINAL)

    assert actual == expected
    validate_terminal_inventory(
        actual,
        base_inventory=base,
        graph_baseline=graph,
        phase4_contract=phase4,
        phase5_audit=phase5,
        repo_root=ROOT,
    )


def test_terminal_inventory_has_no_pending_and_no_false_complete() -> None:
    terminal = _load(TERMINAL)
    records = [
        record
        for group in ("sources", "entrypoints", "runtime_tasks", "features")
        for record in terminal[group]
    ]

    assert len(records) == 506
    assert Counter(record["status"] for record in records) == {
        "CANNOT_CONFIRM": 506
    }
    assert Counter(record["terminal_class"] for record in records) == {
        "CANNOT_CONFIRM": 500,
        "COMPAT": 4,
        "REMOVE_PROPOSED": 2,
    }
    assert terminal["terminal_counts"]["complete"] == 0
    assert terminal["claims"] == {
        "business_parity_verified": False,
        "deployed": False,
        "inventory_accounting_complete": True,
        "ready_to_replace": False,
        "ui_verified": False,
    }
    assert terminal["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_terminal_inventory_preserves_source_lineage_without_claiming_replacement() -> None:
    base = _load(BASE)
    terminal = _load(TERMINAL)
    base_by_id = {record["atlas_file_id"]: record for record in base["sources"]}

    assert Counter(record["source_state"] for record in terminal["sources"]) == {
        "MATCHES_ATLAS": 316,
        "MODIFIED_SINCE_ATLAS": 20,
    }
    for record in terminal["sources"]:
        original = base_by_id[record["atlas_file_id"]]
        assert record["source_sha256"] == original["sha256"]
        assert record["old_source"] == original["old_source"]
        assert record["target_modules"] == []
        assert record["cannot_confirm"] == [
            "NO_RECORD_LEVEL_REPLACEMENT_EVIDENCE"
        ]


@pytest.mark.parametrize(
    "mutation",
    ("complete", "missing", "record_hash", "evidence_hash", "pending"),
)
def test_terminal_inventory_rejects_rehashed_semantic_tamper(
    mutation: str,
) -> None:
    base, graph, phase4, phase5 = _inputs()
    terminal = _load(TERMINAL)
    if mutation == "complete":
        terminal["sources"][0]["status"] = "COMPLETE"
    elif mutation == "missing":
        terminal["entrypoints"].pop()
    elif mutation == "record_hash":
        terminal["runtime_tasks"][0]["base_record_sha256"] = "f" * 64
    elif mutation == "evidence_hash":
        terminal["features"][0]["gap_evidence"][0]["raw_sha256"] = "f" * 64
    else:
        terminal["features"][0]["status"] = "PENDING"
    body = {
        key: value
        for key, value in terminal.items()
        if key != "terminal_semantic_hash"
    }
    terminal["terminal_semantic_hash"] = semantic_hash(body)

    with pytest.raises(TerminalInventoryError):
        validate_terminal_inventory(
            terminal,
            base_inventory=base,
            graph_baseline=graph,
            phase4_contract=phase4,
            phase5_audit=phase5,
            repo_root=ROOT,
        )


def test_terminal_inventory_rejects_changed_base_after_rehash() -> None:
    base, graph, phase4, phase5 = _inputs()
    terminal = _load(TERMINAL)
    changed_base = deepcopy(base)
    changed_base["sources"][0]["target_owner"] = (
        "apps/api"
        if changed_base["sources"][0]["target_owner"] == "ops"
        else "ops"
    )

    with pytest.raises(TerminalInventoryError):
        validate_terminal_inventory(
            terminal,
            base_inventory=changed_base,
            graph_baseline=graph,
            phase4_contract=phase4,
            phase5_audit=phase5,
            repo_root=ROOT,
        )
