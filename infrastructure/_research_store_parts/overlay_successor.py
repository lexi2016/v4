"""infrastructure.research_store: overlay_successor (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_manager_overlay_successor_body(_v4_scope, /, cls, old_payload, new_payload, *, proof_ref):
    try:
        context = _b04_read_successor_source_context(_v4_scope, cls, old_payload, new_payload, proof_ref)
        _b04_validate_successor_source_records(_v4_scope, cls, context)
        _b04_validate_successor_decision_projection(_v4_scope, cls, context, old_payload, new_payload)
    except _v4_global(_v4_scope, 'ValueError'):
        raise
    except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'AttributeError')) as error:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            f"proof verification failed: {error}",
        ) from error

def _b04_read_successor_source_context(_v4_scope, cls, old_payload, new_payload, proof_ref):
    proof, _ = cls._read_manager_overlay_json_ref(
        proof_ref,
        label="manager source successor proof",
    )

    source_date = _v4_global(_v4_scope, 'str')(old_payload.get("source_date") or "")

    target_trade_date = _v4_global(_v4_scope, 'str')(old_payload.get("target_trade_date") or "")

    if (
        new_payload.get("source_date") != source_date
        or new_payload.get("target_trade_date") != target_trade_date
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor product source/target mismatch",
        )

    cls._validate_manager_overlay_proof_shape(
        proof,
        source_date=source_date,
        target_trade_date=target_trade_date,
    )

    base_supply = cls._read_manager_overlay_supply_ref(
        proof["base_supply_ref"],
        source_date=source_date,
        target_trade_date=target_trade_date,
        label="base supply",
    )

    successor_supply = cls._read_manager_overlay_supply_ref(
        proof["successor_supply_ref"],
        source_date=source_date,
        target_trade_date=target_trade_date,
        label="successor supply",
    )

    if base_supply["run_id"] == successor_supply["run_id"]:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "base and successor run_id must differ",
        )

    if old_payload.get("origin") != "MANUAL_RECOVERY" or new_payload.get("origin") != "MANUAL_RECOVERY":
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "product origin must be MANUAL_RECOVERY",
        )

    if (
        base_supply.get("run_id") != old_payload.get("run_id")
        or successor_supply.get("run_id") != new_payload.get("run_id")
    ):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "product/source run binding mismatch",
        )

    old_refs = cls._product_supply_refs(old_payload, label="base product")

    new_refs = cls._product_supply_refs(new_payload, label="successor product")

    if _v4_global(_v4_scope, 'set')(old_refs) != _v4_global(_v4_scope, 'set')(new_refs) or _v4_global(_v4_scope, 'set')(old_refs) != _v4_global(_v4_scope, 'set')(proof["candidate_ids"]):
        raise cls._manager_overlay_error(
            "OVERLAY_MUTATION_OUT_OF_SCOPE",
            "product/source candidate set mismatch",
        )

    for candidate_id, ref in old_refs.items():
        if (
            ref.get("path") != proof["base_supply_ref"]["path"]
            or ref.get("raw_sha256") != proof["base_supply_ref"]["raw_sha256"]
            or ref.get("frozen_payload_sha256")
            != proof["base_supply_ref"]["frozen_payload_sha256"]
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"base product source ref mismatch: {candidate_id}",
            )
        successor_ref = new_refs[candidate_id]
        if (
            successor_ref.get("path") != proof["successor_supply_ref"]["path"]
            or successor_ref.get("raw_sha256") != proof["successor_supply_ref"]["raw_sha256"]
            or successor_ref.get("frozen_payload_sha256")
            != proof["successor_supply_ref"]["frozen_payload_sha256"]
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"successor product source ref mismatch: {candidate_id}",
            )

    base_cards = {
        _v4_global(_v4_scope, 'str')(card["ticker"]): card
        for card in base_supply["frozen_payload"]["event_cards"]
    }

    successor_cards = {
        _v4_global(_v4_scope, 'str')(card["ticker"]): card
        for card in successor_supply["frozen_payload"]["event_cards"]
    }

    candidate_ids = _v4_global(_v4_scope, 'list')(proof["candidate_ids"])

    def candidate_id_for_ticker(ticker: str) -> str:
        code, market = ticker.rsplit(".", 1)
        return f"{market}.{code}|{ticker}"

    expected_base_ids = _v4_global(_v4_scope, 'sorted')(candidate_id_for_ticker(ticker) for ticker in base_cards)

    expected_successor_ids = _v4_global(_v4_scope, 'sorted')(
        candidate_id_for_ticker(ticker) for ticker in successor_cards
    )

    if candidate_ids != expected_base_ids or candidate_ids != expected_successor_ids:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof candidate set does not cover every source event card",
        )

    if _v4_global(_v4_scope, 'set')(base_cards) != _v4_global(_v4_scope, 'set')(successor_cards):
        raise cls._manager_overlay_error(
            "OVERLAY_MUTATION_OUT_OF_SCOPE",
            "supply ticker set changed",
        )
    return {
        "proof": proof,
        "source_date": source_date,
        "target_trade_date": target_trade_date,
        "base_supply": base_supply,
        "successor_supply": successor_supply,
        "old_refs": old_refs,
        "new_refs": new_refs,
        "base_cards": base_cards,
        "successor_cards": successor_cards,
        "candidate_ids": candidate_ids,
    }


def _b04_validate_successor_source_records(_v4_scope, cls, context):
    proof = context["proof"]
    candidate_ids = context["candidate_ids"]
    base_supply = context["base_supply"]
    successor_supply = context["successor_supply"]
    base_cards = context["base_cards"]
    successor_cards = context["successor_cards"]
    record_by_id: dict[str, Mapping[str, Any]] = {}

    for record, candidate_id in _v4_global(_v4_scope, 'zip')(proof["records"], candidate_ids):
        if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(record) != _v4_global(_v4_scope, '_MANAGER_OVERLAY_RECORD_FIELDS'):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof record fields are invalid",
            )
        if record.get("candidate_id") != candidate_id or candidate_id in record_by_id:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof record order or identity is invalid",
            )
        ticker = record.get("ticker")
        expected_ticker = candidate_id.split("|", 1)[1] if "|" in candidate_id else ""
        if ticker != expected_ticker or ticker not in base_cards:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof ticker binding is invalid: {candidate_id}",
            )
        before_card = base_cards[ticker]
        after_card = successor_cards[ticker]
        if record.get("before_card_sha") != cls._canonical_sha(before_card):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof before card SHA mismatch: {candidate_id}",
            )
        if record.get("after_card_sha") != cls._canonical_sha(after_card):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof after card SHA mismatch: {candidate_id}",
            )
        changed_paths = record.get("changed_paths")
        if not _v4_global(_v4_scope, 'isinstance')(changed_paths, _v4_global(_v4_scope, 'list')) or changed_paths != _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(changed_paths)):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof card paths are not sorted and unique: {candidate_id}",
            )
        if not _v4_global(_v4_scope, 'set')(changed_paths).issubset(_v4_global(_v4_scope, 'MANAGER_OVERLAY_CARD_CHANGED_PATHS')):
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                f"proof expands card allowlist: {candidate_id}",
            )
        actual_paths = _v4_global(_v4_scope, '_manager_overlay_changed_paths')(before_card, after_card)
        if actual_paths != changed_paths:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof card paths do not match source: {candidate_id}",
            )
        for identity_field in ("ticker", "candidate_id", "event_id", "entity", "market"):
            if before_card.get(identity_field) != after_card.get(identity_field):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"source card identity changed: {candidate_id}.{identity_field}",
                )
        record_by_id[candidate_id] = record

    if _v4_global(_v4_scope, 'len')(record_by_id) != _v4_global(_v4_scope, 'len')(candidate_ids):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof records are not complete",
        )

    actual_envelope_paths = _v4_global(_v4_scope, '_manager_overlay_envelope_paths')(base_supply, successor_supply)

    if actual_envelope_paths != proof["envelope_changed_paths"]:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "proof envelope paths do not match source",
        )

    if not _v4_global(_v4_scope, 'set')(actual_envelope_paths).issubset(_v4_global(_v4_scope, 'MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS')):
        raise cls._manager_overlay_error(
            "OVERLAY_MUTATION_OUT_OF_SCOPE",
            "source envelope changed outside proof allowlist",
        )


def _b04_validate_successor_decision_projection(_v4_scope, cls, context, old_payload, new_payload):
    proof = context["proof"]
    source_date = context["source_date"]
    target_trade_date = context["target_trade_date"]
    base_supply = context["base_supply"]
    successor_supply = context["successor_supply"]
    old_ids = [_v4_global(_v4_scope, 'str')(row["candidate_id"]) for row in old_payload["research_candidates"]]

    new_ids = [_v4_global(_v4_scope, 'str')(row["candidate_id"]) for row in new_payload["research_candidates"]]

    old_decision, old_decision_sha = cls._read_manager_overlay_decision(
        old_payload,
        source_envelope=base_supply,
        candidate_ids=old_ids,
        label="base manager decision",
    )

    new_decision, new_decision_sha = cls._read_manager_overlay_decision(
        new_payload,
        source_envelope=successor_supply,
        candidate_ids=new_ids,
        label="successor manager decision",
    )

    if old_decision.get("baseline_ref") is not None:
        raise cls._manager_overlay_error(
            "SECOND_MANAGER_OVERLAY",
            "base manager decision already has a baseline",
        )

    old_decision_ref = old_payload.get("manager_decision_ref")

    new_decision_ref = new_payload.get("manager_decision_ref")

    if not _v4_global(_v4_scope, 'isinstance')(old_decision_ref, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(new_decision_ref, _v4_global(_v4_scope, 'Mapping')):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "manager decision reference is missing",
        )

    if new_decision.get("baseline_ref") != _v4_global(_v4_scope, 'dict')(old_decision_ref):
        raise cls._manager_overlay_error(
            "STALE_BASELINE",
            "successor baseline does not name the current base decision",
        )

    if old_decision_sha != _v4_global(_v4_scope, 'str')(old_decision_ref.get("raw_sha256") or "").lower():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "base decision SHA binding mismatch",
        )

    if new_decision_sha != _v4_global(_v4_scope, 'str')(new_decision_ref.get("raw_sha256") or "").lower():
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor decision SHA binding mismatch",
        )

    if old_decision.get("source_date") != new_decision.get("source_date") or old_decision.get(
        "target_trade_date"
    ) != new_decision.get("target_trade_date"):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "manager decision source/target mismatch",
        )

    for decision, supply_ref, label in (
        (old_decision, proof["base_supply_ref"], "base"),
        (new_decision, proof["successor_supply_ref"], "successor"),
    ):
        decision_supply_ref = decision.get("supply_ref")
        if not _v4_global(_v4_scope, 'isinstance')(decision_supply_ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'any')(
            decision_supply_ref.get(field) != supply_ref[field]
            for field in (
                "path",
                "raw_sha256",
                "frozen_payload_sha256",
                "run_id",
            )
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} manager decision supply binding mismatch",
            )

    old_decision_time = cls._manager_overlay_time(
        old_decision.get("generated_at"), "base decision generated_at"
    )

    new_decision_time = cls._manager_overlay_time(
        new_decision.get("generated_at"), "successor decision generated_at"
    )

    old_product_time = cls._manager_overlay_time(
        old_payload.get("generated_at"), "base product generated_at"
    )

    new_product_time = cls._manager_overlay_time(
        new_payload.get("generated_at"), "successor product generated_at"
    )

    target_start = _v4_global(_v4_scope, 'datetime').strptime(target_trade_date, "%Y%m%d").replace(tzinfo=_v4_global(_v4_scope, '_SHANGHAI'))

    if not (
        old_decision_time <= old_product_time
        and old_product_time < new_decision_time
        and new_decision_time <= new_product_time
        and new_product_time < target_start
    ):
        raise cls._manager_overlay_error(
            "GENERATED_AT_NOT_INCREASING",
            "decision/product generated_at chain is not ordered between base and target day",
        )

    if new_decision.get("run_id") != new_payload.get("run_id"):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor decision run binding mismatch",
        )

    if new_decision.get("supply_ref", {}).get("path") != proof["successor_supply_ref"]["path"]:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor decision supply path mismatch",
        )

    if new_decision.get("supply_ref", {}).get("raw_sha256") != proof["successor_supply_ref"]["raw_sha256"]:
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor decision supply SHA mismatch",
        )

    expected_projections = cls._manager_overlay_expected_projections(new_decision)

    projected_ids = {
        _v4_global(_v4_scope, 'str')(candidate["candidate_id"])
        for candidate in new_payload["research_candidates"]
        if "manager_decision" in candidate
    }

    if projected_ids != _v4_global(_v4_scope, 'set')(expected_projections):
        raise cls._manager_overlay_error(
            "SOURCE_SUCCESSOR_PROOF_INVALID",
            "successor manager projection set is incomplete",
        )

    cls._verify_manager_overlay_product_diff(
        old_payload,
        new_payload,
        proof=proof,
        old_supply=base_supply,
        new_supply=successor_supply,
        expected_projections=expected_projections,
    )
