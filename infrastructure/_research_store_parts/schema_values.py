"""Multiline schema and keyword values; called at original assignment time."""
from ._namespace import read_global as _v4_global


def _value__MANAGER_OVERLAY_PROOF_FIELDS(_v4_scope, /):
    return (
        _v4_global(_v4_scope, 'frozenset')(
    {
        "schema_version",
        "type",
        "rule_id",
        "rule_version",
        "source_date",
        "target_trade_date",
        "base_supply_ref",
        "successor_supply_ref",
        "candidate_ids",
        "candidate_set_sha256",
        "records",
        "envelope_changed_paths",
        "safety",
    }
)
    )


def _value__MANAGER_OVERLAY_SUPPLY_REF_FIELDS(_v4_scope, /):
    return (
        _v4_global(_v4_scope, 'frozenset')(
    {
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "run_id",
        "source_date",
        "target_trade_date",
    }
)
    )


def _value_MANAGER_OVERLAY_CARD_CHANGED_PATHS(_v4_scope, /):
    return (
        _v4_global(_v4_scope, 'frozenset')(
    {
        "candidate_claim_status",
        "catalyst.status",
        "claim_status",
        "confirmation_conditions",
        "content_source_receipts",
        "counterevidence_cn",
        "evidence_level",
        "independent_evidence_dimensions.research.status",
        "invalidation_conditions",
        "investment_thesis_cn",
        "manager_research",
        "official_facts",
        "official_source.identity_status",
        "primary_fact_review",
        "promotion_missing_fields",
        "review_direction",
        "review_priority_bucket",
        "review_status",
        "source.receipt_path",
        "source.receipt_sha256",
        "source.source_class",
        "typed_gaps",
    }
)
    )


def _value_MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS(_v4_scope, /):
    return (
        _v4_global(_v4_scope, 'frozenset')(
    {
        "frozen_payload.conditional_watch_candidates",
        "frozen_payload.delivery_timing.actual_generated_at",
        "frozen_payload.delivery_timing.origin",
        "frozen_payload.event_cards[*]",
        "frozen_payload.formal_shortlist",
        "frozen_payload.generated_at",
        "frozen_payload.origin",
        "frozen_payload.primary_fact_reviews",
        "frozen_payload.run_id",
        "frozen_payload.source_receipts",
        "frozen_payload_sha256",
        "generated_at",
        "run_id",
    }
)
    )
