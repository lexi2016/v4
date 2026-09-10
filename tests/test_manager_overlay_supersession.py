import copy
import hashlib
import json
from pathlib import Path

import pytest

from domains.research_day_product import build_selection_research_product, _selection_snapshot
from infrastructure.research_store import (
    MANAGER_OVERLAY_CARD_CHANGED_PATHS,
    MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS,
    ResearchSelectionStore,
)
from ops.build_manager_source_successor_proof import build_proof, canonical_bytes


V2_PRODUCT_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/research/selection/20260831/"
    "baimao-20260828-2150-initial-supply-20260831-v2.json"
)
V2_SUPPLY_PATH = Path(
    "/Users/lexi/Desktop/学习/助手/白毛研究员/research/20260828/"
    "2200_initial_supply_20260831_v2/research_supply.json"
)
V2_DECISION_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/receipts/research/selection/20260831/"
    "baimao-20260828-2150-initial-supply-20260831-v2.manager_decision.json"
)
V4_ROOT = Path(
    "/Users/lexi/Desktop/学习/助手/白毛研究员/research/20260828/"
    "2200_initial_supply_20260831_v4_manager_bridge"
)
V4_SUPPLY_PATH = V4_ROOT / "materialized/research_supply.json"
V4_RECEIPT_PATH = V4_ROOT / "materialized/research_supply_receipt.json"
V4_DECISION_PATH = V4_ROOT / "manager_decision.json"
PROOF_PATH = V4_ROOT / "source_successor_proof_v2_to_v4.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _v4_product() -> dict:
    return _build_product()


def _build_product(
    *,
    decision_path: Path = V4_DECISION_PATH,
    decision: dict | None = None,
) -> dict:
    envelope = json.loads(V4_SUPPLY_PATH.read_text(encoding="utf-8"))
    decision = decision or json.loads(decision_path.read_text(encoding="utf-8"))
    supply_sha = _sha(V4_SUPPLY_PATH)
    receipt_sha = _sha(V4_RECEIPT_PATH)
    cards = []
    for index, source_card in enumerate(envelope["frozen_payload"]["event_cards"]):
        cards.append(
            {
                "card": copy.deepcopy(source_card),
                "source_ref": {
                    "type": "RESEARCH_SUPPLY_FROZEN_ENVELOPE",
                    "path": str(V4_SUPPLY_PATH),
                    "raw_sha256": supply_sha,
                    "frozen_payload_sha256": envelope["frozen_payload_sha256"],
                    "json_pointer": f"/frozen_payload/event_cards/{index}",
                    "source_date": "20260828",
                    "source_time": envelope["generated_at"],
                    "supply_receipt_path": str(V4_RECEIPT_PATH),
                    "supply_receipt_sha256": receipt_sha,
                },
            }
        )
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
        manager_decision_ref={
            "path": str(decision_path),
            "raw_sha256": _sha(decision_path),
        },
    )


def _proof_ref() -> dict[str, str]:
    return {"path": str(PROOF_PATH), "raw_sha256": _sha(PROOF_PATH)}


def _temp_proof(tmp_path: Path, mutate=None) -> dict[str, str]:
    proof = build_proof(V2_SUPPLY_PATH, V4_SUPPLY_PATH)
    if mutate is not None:
        mutate(proof)
    path = tmp_path / "source-successor-proof.json"
    path.write_bytes(canonical_bytes(proof))
    return {"path": str(path), "raw_sha256": _sha(path)}


def _temp_pair_proof(
    tmp_path: Path,
    base_supply: Path,
    successor_supply: Path,
    *,
    name: str,
) -> dict[str, str]:
    path = tmp_path / name
    path.write_bytes(canonical_bytes(build_proof(base_supply, successor_supply)))
    return {"path": str(path), "raw_sha256": _sha(path)}


def _temp_supply_with_extra_card(tmp_path: Path) -> Path:
    envelope = json.loads(V4_SUPPLY_PATH.read_text(encoding="utf-8"))
    extra = copy.deepcopy(envelope["frozen_payload"]["event_cards"][0])
    extra["ticker"] = "99999.HK"
    extra["entity"] = "99999.HK"
    extra["event_id"] = "event-extra-source-card"
    envelope["frozen_payload"]["event_cards"].append(extra)
    envelope["frozen_payload_sha256"] = hashlib.sha256(
        canonical_bytes(envelope["frozen_payload"])
    ).hexdigest()
    path = tmp_path / "successor-supply-with-extra-card.json"
    path.write_bytes(canonical_bytes(envelope))
    return path


def _temp_supply_with_duplicate_ticker(tmp_path: Path) -> Path:
    envelope = json.loads(V4_SUPPLY_PATH.read_text(encoding="utf-8"))
    duplicate = copy.deepcopy(envelope["frozen_payload"]["event_cards"][0])
    duplicate["event_id"] = "event-duplicate-ticker"
    envelope["frozen_payload"]["event_cards"].append(duplicate)
    envelope["frozen_payload_sha256"] = hashlib.sha256(
        canonical_bytes(envelope["frozen_payload"])
    ).hexdigest()
    path = tmp_path / "successor-supply-with-duplicate-ticker.json"
    path.write_bytes(canonical_bytes(envelope))
    return path


def _temp_proof_with_successor_supply(tmp_path: Path, successor_supply: Path) -> dict[str, str]:
    proof = build_proof(V2_SUPPLY_PATH, V4_SUPPLY_PATH)
    raw = json.loads(successor_supply.read_text(encoding="utf-8"))
    proof["successor_supply_ref"].update(
        {
            "path": str(successor_supply),
            "raw_sha256": _sha(successor_supply),
            "frozen_payload_sha256": raw["frozen_payload_sha256"],
        }
    )
    path = tmp_path / "source-successor-proof-extra-supply.json"
    path.write_bytes(canonical_bytes(proof))
    return {"path": str(path), "raw_sha256": _sha(path)}


def _product_with_successor_supply_binding(
    product: dict,
    successor_supply: Path,
) -> dict:
    result = copy.deepcopy(product)
    envelope = json.loads(successor_supply.read_text(encoding="utf-8"))
    binding = {
        "path": str(successor_supply),
        "raw_sha256": _sha(successor_supply),
        "frozen_payload_sha256": envelope["frozen_payload_sha256"],
    }
    for candidate in result["research_candidates"]:
        for source_ref in candidate["source_refs"]:
            source_ref.update(binding)
    return result


def _write_json(path: Path, value: dict) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


def _product_with_decision_variant(tmp_path: Path, *, generated_at: str) -> dict:
    decision = json.loads(V4_DECISION_PATH.read_text(encoding="utf-8"))
    decision["generated_at"] = generated_at
    decision_path = _write_json(tmp_path / "successor-decision.json", decision)
    return _build_product(decision_path=decision_path, decision=decision)


def _product_with_later_ready(product: dict) -> dict:
    result = copy.deepcopy(product)
    candidate_ids = list(result["snapshots"]["2200"]["candidate_ids"])
    result["snapshots"]["0830"] = _selection_snapshot(
        "0830",
        {
            "status": "READY",
            "run_id": result["run_id"],
            "event_at": "2026-08-30T14:00:00+08:00",
            "artifact_sha256": "a" * 64,
            "candidate_ids": candidate_ids,
            "changes": [],
        },
        candidate_ids=candidate_ids,
    )
    result["cannot_confirm"] = sorted(
        gap for gap in result["cannot_confirm"] if gap != "SNAPSHOT_0830_NOT_MATERIALIZED"
    )
    result["first_failed_layer"] = min(result["cannot_confirm"])
    return result


def _assert_temp_tree_unchanged(
    store: ResearchSelectionStore,
    before: dict[str, str],
) -> None:
    assert _tree_sha(store.root) == before


def _tree_sha(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_v2(store: ResearchSelectionStore) -> dict:
    v2 = json.loads(V2_PRODUCT_PATH.read_text(encoding="utf-8"))
    store.publish(v2)
    return v2


def test_ready_2200_successor_requires_explicit_source_proof(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    store.publish(json.loads(V2_PRODUCT_PATH.read_text(encoding="utf-8")))
    before = _tree_sha(store.root)

    with pytest.raises(ValueError, match="SOURCE_SUCCESSOR_PROOF_REQUIRED"):
        store.publish(_v4_product())
    _assert_temp_tree_unchanged(store, before)


def test_valid_v4_source_successor_proof_advances_temp_current(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    v2 = json.loads(V2_PRODUCT_PATH.read_text(encoding="utf-8"))
    v4 = _v4_product()
    store.publish(v2)

    result = store.publish(
        v4,
        manager_overlay_source_successor_ref=_proof_ref(),
    )

    assert result["current_updated"] is True
    stored, _ = store.read_exact_with_lineage("20260831")
    assert stored is not None
    assert stored["run_id"] == "baimao-20260830-manager-research-overlay-v4"
    assert stored["snapshots"]["2200"]["candidate_ids"] == [
        "HK.01304|01304.HK",
        "HK.01952|01952.HK",
        "HK.02315|02315.HK",
        "HK.02410|02410.HK",
        "HK.02676|02676.HK",
        "HK.03738|03738.HK",
        "HK.06078|06078.HK",
        "HK.06951|06951.HK",
    ]


def test_successor_proof_is_deterministic_and_closed_over_exact_sources() -> None:
    first = build_proof(V2_SUPPLY_PATH, V4_SUPPLY_PATH)
    second = build_proof(V2_SUPPLY_PATH, V4_SUPPLY_PATH)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert PROOF_PATH.read_bytes() == canonical_bytes(first)
    assert len(first["records"]) == 124
    assert first["candidate_ids"] == sorted(first["candidate_ids"])
    assert first["candidate_set_sha256"] == hashlib.sha256(
        canonical_bytes(first["candidate_ids"])
    ).hexdigest()
    assert first["envelope_changed_paths"] == sorted(first["envelope_changed_paths"])
    assert set(first["envelope_changed_paths"]).issubset(MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS)
    assert all(
        set(record["changed_paths"]).issubset(MANAGER_OVERLAY_CARD_CHANGED_PATHS)
        for record in first["records"]
    )
    assert all(record["changed_paths"] for record in first["records"])


def test_valid_successor_keeps_full_ledger_and_research_only_guards(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    v2 = _seed_v2(store)
    result = store.publish(_v4_product(), manager_overlay_source_successor_ref=_proof_ref())

    assert result["current_updated"] is True
    stored, _ = store.read_exact_with_lineage("20260831")
    assert stored is not None
    assert len(stored["research_candidates"]) == 124
    assert any(row["candidate_id"] == "HK.09926|09926.HK" for row in stored["research_candidates"])
    assert all(
        "manager_decision" not in row
        for row in stored["research_candidates"]
        if row["candidate_id"] == "HK.09926|09926.HK"
    )
    assert stored["snapshots"]["2200"]["candidate_ids"] == [
        "HK.01304|01304.HK",
        "HK.01952|01952.HK",
        "HK.02315|02315.HK",
        "HK.02410|02410.HK",
        "HK.02676|02676.HK",
        "HK.03738|03738.HK",
        "HK.06078|06078.HK",
        "HK.06951|06951.HK",
    ]
    assert stored["formal_shortlist"] == []
    assert all(stored["snapshots"][phase]["status"] == "NOT_MATERIALIZED" for phase in ("0830", "0935", "1620"))
    assert stored["RESEARCH_ONLY"] is True
    assert stored["production_allowed"] is False
    assert stored["buy_gate_updated"] is False
    assert stored["orders_sent"] is False
    assert store.read_run("20260831", v2["run_id"])["run_id"] == v2["run_id"]


def test_same_successor_retry_is_idempotent(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    first = store.publish(_v4_product(), manager_overlay_source_successor_ref=_proof_ref())
    before, before_lineage = store.read_exact_with_lineage("20260831")
    second = store.publish(_v4_product(), manager_overlay_source_successor_ref=_proof_ref())
    after, after_lineage = store.read_exact_with_lineage("20260831")
    assert first["current_updated"] is True
    assert second["current_updated"] is False
    assert before == after
    assert before_lineage == after_lineage


@pytest.mark.parametrize(
    ("mutate", "error_prefix"),
    [
        (lambda proof: proof["records"][0].__setitem__("before_card_sha", "0" * 64), "SOURCE_SUCCESSOR_PROOF_INVALID"),
        (lambda proof: proof["records"][0]["changed_paths"].append("candidate_id") or proof["records"][0]["changed_paths"].sort(), "OVERLAY_MUTATION_OUT_OF_SCOPE"),
        (lambda proof: proof["envelope_changed_paths"].append("frozen_payload.schema_version") or proof["envelope_changed_paths"].sort(), "OVERLAY_MUTATION_OUT_OF_SCOPE"),
        (lambda proof: proof.__setitem__("source_date", "20260829"), "SOURCE_SUCCESSOR_PROOF_INVALID"),
    ],
    ids=["tampered-card-sha", "identity-path", "envelope-path", "source-date"],
)
def test_tampered_or_expanded_proof_fails_closed(
    tmp_path: Path,
    mutate,
    error_prefix: str,
) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    proof_ref = _temp_proof(tmp_path, mutate=mutate)
    before = _tree_sha(store.root)
    with pytest.raises(ValueError, match=error_prefix):
        store.publish(_v4_product(), manager_overlay_source_successor_ref=proof_ref)
    _assert_temp_tree_unchanged(store, before)


def test_later_ready_snapshot_is_a_distinct_fail_closed_layer(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    before = _tree_sha(store.root)
    with pytest.raises(ValueError, match="LATER_PHASE_READY"):
        store.publish(
            _product_with_later_ready(_v4_product()),
            manager_overlay_source_successor_ref=_proof_ref(),
        )
    _assert_temp_tree_unchanged(store, before)


def test_proof_candidate_set_must_cover_every_bound_supply_card(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    v2 = _seed_v2(store)
    extra_supply = _temp_supply_with_extra_card(tmp_path)
    proof_ref = _temp_proof_with_successor_supply(tmp_path, extra_supply)
    successor = _product_with_successor_supply_binding(_v4_product(), extra_supply)
    before = _tree_sha(store.root)
    with pytest.raises(
        ValueError,
        match="proof candidate set does not cover every source event card",
    ):
        ResearchSelectionStore._verify_manager_overlay_successor(
            v2,
            successor,
            proof_ref,
        )
    _assert_temp_tree_unchanged(store, before)


def test_proof_candidate_set_rejects_duplicate_bound_supply_ticker(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    v2 = _seed_v2(store)
    duplicate_supply = _temp_supply_with_duplicate_ticker(tmp_path)
    proof_ref = _temp_proof_with_successor_supply(tmp_path, duplicate_supply)
    successor = _product_with_successor_supply_binding(_v4_product(), duplicate_supply)
    before = _tree_sha(store.root)
    with pytest.raises(
        ValueError,
        match="duplicate research supply ticker",
    ):
        ResearchSelectionStore._verify_manager_overlay_successor(
            v2,
            successor,
            proof_ref,
        )
    _assert_temp_tree_unchanged(store, before)


def test_stale_successor_baseline_is_rejected_without_writes(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    stale_baseline = tmp_path / "stale-baseline.json"
    stale_baseline.write_bytes(V2_DECISION_PATH.read_bytes())
    decision = json.loads(V4_DECISION_PATH.read_text(encoding="utf-8"))
    decision["baseline_ref"] = {"path": str(stale_baseline), "raw_sha256": _sha(stale_baseline)}
    decision_path = _write_json(tmp_path / "stale-successor-decision.json", decision)
    before = _tree_sha(store.root)
    with pytest.raises(ValueError, match="STALE_BASELINE"):
        store.publish(
            _build_product(decision_path=decision_path, decision=decision),
            manager_overlay_source_successor_ref=_proof_ref(),
        )
    _assert_temp_tree_unchanged(store, before)


@pytest.mark.parametrize(
    "generated_at",
    [
        "2026-08-28T23:50:00+08:00",
        "2026-08-28T15:50:00Z",
        "2026-08-28T23:55:25.832734+08:00",
        "2026-08-28T15:55:25.832734Z",
        "2026-08-31T00:00:00+08:00",
    ],
    ids=[
        "product-before-successor-decision",
        "timezone-normalized-product-before-decision",
        "product-equal-to-base-decision",
        "timezone-normalized-product-equal-to-base-decision",
        "product-at-target-day-start",
    ],
)
def test_non_increasing_successor_product_time_is_rejected(
    tmp_path: Path,
    generated_at: str,
) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    before = _tree_sha(store.root)
    product = _v4_product()
    product["generated_at"] = generated_at
    with pytest.raises(ValueError, match="GENERATED_AT_NOT_INCREASING"):
        store.publish(product, manager_overlay_source_successor_ref=_proof_ref())
    _assert_temp_tree_unchanged(store, before)


def test_successor_product_cannot_precede_successor_decision(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    product = _v4_product()
    product["generated_at"] = "2026-08-30T13:00:00+08:00"
    before = _tree_sha(store.root)
    with pytest.raises(ValueError, match="GENERATED_AT_NOT_INCREASING"):
        store.publish(product, manager_overlay_source_successor_ref=_proof_ref())
    _assert_temp_tree_unchanged(store, before)


def test_out_of_scope_product_mutation_is_rejected_without_writes(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    product = _v4_product()
    product["route_status"] = {**product["route_status"], "R2": "UNAUTHORIZED_OVERLAY_MUTATION"}
    before = _tree_sha(store.root)
    with pytest.raises(ValueError, match="OVERLAY_MUTATION_OUT_OF_SCOPE"):
        store.publish(product, manager_overlay_source_successor_ref=_proof_ref())
    _assert_temp_tree_unchanged(store, before)


def test_same_run_different_payload_is_conflict_after_successor_publish(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    _seed_v2(store)
    v4 = _v4_product()
    store.publish(v4, manager_overlay_source_successor_ref=_proof_ref())
    conflicting = copy.deepcopy(v4)
    conflicting["route_status"] = {
        **conflicting["route_status"],
        "R2": "SAME_RUN_DIFFERENT_BYTES",
    }
    with pytest.raises(ValueError, match="conflicting selection run"):
        store.publish(conflicting)


def test_legacy_product_without_manager_decision_ref_fails_closed(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    legacy = json.loads(V2_PRODUCT_PATH.read_text(encoding="utf-8"))
    legacy.pop("manager_decision_ref")
    with pytest.raises(ValueError, match="SOURCE_SUCCESSOR_PROOF_INVALID"):
        ResearchSelectionStore._verify_manager_overlay_successor(
            legacy,
            _v4_product(),
            _proof_ref(),
        )


def test_decision_generated_before_successor_supply_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="manager decision generated_at predates supply envelope"):
        _product_with_decision_variant(
            tmp_path,
            generated_at="2026-08-28T23:55:25.832734+08:00",
        )


def test_second_overlay_is_not_accepted_from_the_v4_decision(tmp_path: Path) -> None:
    store = ResearchSelectionStore(tmp_path)
    v2 = _seed_v2(store)
    store.publish(_v4_product(), manager_overlay_source_successor_ref=_proof_ref())
    current, _ = store.read_exact_with_lineage("20260831")
    assert current is not None
    reverse_proof_ref = _temp_pair_proof(
        tmp_path,
        V4_SUPPLY_PATH,
        V2_SUPPLY_PATH,
        name="reverse-source-successor-proof.json",
    )
    with pytest.raises(ValueError, match="SECOND_MANAGER_OVERLAY"):
        ResearchSelectionStore._verify_manager_overlay_successor(
            current,
            v2,
            reverse_proof_ref,
        )
