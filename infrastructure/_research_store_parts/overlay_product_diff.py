"""infrastructure.research_store: overlay_product_diff (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_manager_overlay_product_diff_body(_v4_scope, /, cls, old_payload, new_payload, *, proof, old_supply, new_supply, expected_projections):
    context = _b04_prepare_overlay_product_context(
        _v4_scope, cls, old_payload, new_payload, proof, old_supply, new_supply
    )
    _b04_validate_overlay_candidate_mutations(
        _v4_scope, cls, context, proof, expected_projections
    )
    _b04_validate_overlay_product_boundary(
        _v4_scope, cls, context, old_payload, new_payload, proof, old_supply, new_supply
    )

def _b04_prepare_overlay_product_context(_v4_scope, cls, old_payload, new_payload, proof, old_supply, new_supply):
    old_snapshots = old_payload.get("snapshots")

    new_snapshots = new_payload.get("snapshots")

    if not _v4_global(_v4_scope, 'isinstance')(old_snapshots, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(new_snapshots, _v4_global(_v4_scope, 'Mapping')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "product snapshots are invalid",
        )

    for phase in ("0830", "0935", "1620"):
        old_later = old_snapshots.get(phase)
        new_later = new_snapshots.get(phase)
        if not _v4_global(_v4_scope, 'isinstance')(old_later, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(new_later, _v4_global(_v4_scope, 'Mapping')):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"later snapshot is invalid: {phase}",
            )
        if old_later != new_later and (
            old_later.get("status") == "READY" or new_later.get("status") == "READY"
        ):
            raise cls._manager_overlay_error(
                "LATER_PHASE_READY",
                f"later snapshot is READY: {phase}",
            )

    allowed_top = {"generated_at", "run_id", "manager_decision_ref", "source_refs"}

    for key in _v4_global(_v4_scope, 'set')(old_payload) | _v4_global(_v4_scope, 'set')(new_payload):
        if key in allowed_top or key in {"research_candidates", "snapshots"}:
            continue
        if old_payload.get(key) != new_payload.get(key):
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"product field changed outside proof: {key}",
            )

    old_candidates = old_payload.get("research_candidates")

    new_candidates = new_payload.get("research_candidates")

    if not _v4_global(_v4_scope, 'isinstance')(old_candidates, _v4_global(_v4_scope, 'list')) or not _v4_global(_v4_scope, 'isinstance')(new_candidates, _v4_global(_v4_scope, 'list')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "product candidate lists are invalid",
        )

    old_ids = [_v4_global(_v4_scope, 'str')(row.get("candidate_id") or "") for row in old_candidates]

    new_ids = [_v4_global(_v4_scope, 'str')(row.get("candidate_id") or "") for row in new_candidates]

    proof_ids = _v4_global(_v4_scope, 'list')(proof["candidate_ids"])

    if old_ids != new_ids or old_ids != proof_ids:
        raise cls._manager_overlay_error(
            "OVERLAY_MUTATION_OUT_OF_SCOPE",
            "product candidate identity/order changed",
        )

    old_by_id = {row["candidate_id"]: row for row in old_candidates}

    new_by_id = {row["candidate_id"]: row for row in new_candidates}

    record_by_id = {record["candidate_id"]: record for record in proof["records"]}

    old_supply_cards = {
        _v4_global(_v4_scope, 'str')(card["ticker"]): card
        for card in old_supply["frozen_payload"]["event_cards"]
    }

    new_supply_cards = {
        _v4_global(_v4_scope, 'str')(card["ticker"]): card
        for card in new_supply["frozen_payload"]["event_cards"]
    }

    if _v4_global(_v4_scope, 'set')(record_by_id) != _v4_global(_v4_scope, 'set')(proof_ids):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof record identities do not reconcile",
        )
    return {
        "old_snapshots": old_snapshots,
        "new_snapshots": new_snapshots,
        "proof_ids": proof_ids,
        "old_by_id": old_by_id,
        "new_by_id": new_by_id,
        "record_by_id": record_by_id,
        "old_supply_cards": old_supply_cards,
        "new_supply_cards": new_supply_cards,
    }


def _b04_validate_overlay_candidate_mutations(_v4_scope, cls, context, proof, expected_projections):
    old_snapshots = context["old_snapshots"]
    new_snapshots = context["new_snapshots"]
    proof_ids = context["proof_ids"]
    old_by_id = context["old_by_id"]
    new_by_id = context["new_by_id"]
    record_by_id = context["record_by_id"]
    old_supply_cards = context["old_supply_cards"]
    new_supply_cards = context["new_supply_cards"]
    for candidate_id in proof_ids:
        before = old_by_id[candidate_id]
        after = new_by_id[candidate_id]
        record = record_by_id[candidate_id]
        for field in (
            "candidate_id",
            "event_stock_link_id",
            "market",
            "normalized_code",
            "entity_id",
            "event_id",
        ):
            if before.get(field) != after.get(field):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"candidate identity changed: {candidate_id}.{field}",
                )
        before_card = before.get("source_metadata", {}).get("supply_card")
        after_card = after.get("source_metadata", {}).get("supply_card")
        if not _v4_global(_v4_scope, 'isinstance')(before_card, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(after_card, _v4_global(_v4_scope, 'Mapping')):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"candidate source card missing: {candidate_id}",
            )
        if _v4_global(_v4_scope, 'set')(before.get("source_metadata", {})) != {"supply_card"} or _v4_global(_v4_scope, 'set')(
            after.get("source_metadata", {})
        ) != {"supply_card"}:
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"candidate source metadata changed: {candidate_id}",
            )
        ticker = _v4_global(_v4_scope, 'str')(record["ticker"])
        expected_candidate_id = (
            f"HK.{ticker.split('.', 1)[0]}|{ticker}"
            if "." in ticker
            else ""
        )
        if candidate_id != expected_candidate_id:
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"candidate identity does not reconcile with ticker: {candidate_id}",
            )
        if before_card != old_supply_cards.get(ticker) or after_card != new_supply_cards.get(ticker):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"product source card does not match bound supply: {candidate_id}",
            )
        if (
            cls._canonical_sha(before_card) != record["before_card_sha"]
            or cls._canonical_sha(after_card) != record["after_card_sha"]
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"product source card SHA does not match proof: {candidate_id}",
            )
        if before.get("source_refs") == after.get("source_refs"):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"candidate source successor ref did not change: {candidate_id}",
            )
        for field in _v4_global(_v4_scope, 'MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS'):
            if before.get(field) != after.get(field) and not record["changed_paths"]:
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"derived candidate field changed without source evidence: {candidate_id}.{field}",
                )
        for field in _v4_global(_v4_scope, 'set')(before) | _v4_global(_v4_scope, 'set')(after):
            if field in {"source_refs", "manager_decision", "source_metadata"}:
                continue
            if field in _v4_global(_v4_scope, 'MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS'):
                continue
            if before.get(field) != after.get(field):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"candidate field changed outside proof: {candidate_id}.{field}",
                )
        if "manager_decision" in before:
            raise cls._manager_overlay_error(
                "SECOND_MANAGER_OVERLAY",
                "old product already carries a manager projection",
            )
        if after.get("manager_decision") != expected_projections.get(candidate_id):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"manager projection mismatch: {candidate_id}",
            )


def _b04_validate_overlay_product_boundary(_v4_scope, cls, context, old_payload, new_payload, proof, old_supply, new_supply):
    old_snapshots = context["old_snapshots"]
    new_snapshots = context["new_snapshots"]
    old_snapshot = old_snapshots["2200"]

    new_snapshot = new_snapshots["2200"]

    if old_snapshot.get("status") != "READY" or new_snapshot.get("status") != "READY":
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "2200 snapshots must both be READY",
        )

    for phase in ("0830", "0935", "1620"):
        if old_snapshots[phase] != new_snapshots[phase]:
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"later snapshot changed: {phase}",
            )

    if old_payload["snapshots"]["2200"] == new_payload["snapshots"]["2200"]:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "2200 successor snapshot is not different",
        )

    for field in (
        "formal_shortlist",
        "formal_authority",
        "route_status",
        "gemini_status",
        "RESEARCH_ONLY",
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ):
        if old_payload.get(field) != new_payload.get(field):
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"immutable authority field changed: {field}",
            )

    for field in ("source_date", "target_trade_date", "cutoff_at"):
        if old_supply.get(field) != new_supply.get(field):
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"supply identity changed: {field}",
            )
