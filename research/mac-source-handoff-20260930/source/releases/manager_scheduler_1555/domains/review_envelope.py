"""Pure composition of V3.5-owned market-review projections."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from contracts.a_share_review import A_SHARE_REVIEW_SCHEMA, SAFETY_FLAGS
from domains.a_share_review import validate_a_share_review
from infrastructure.data_store import _date


def _not_materialized(trade_date: str) -> dict[str, Any]:
    return {
        "schema_version": A_SHARE_REVIEW_SCHEMA,
        "trade_date": trade_date,
        "status": "NOT_MATERIALIZED",
        "headline": f"A股复盘 {trade_date}",
        "market_regime": "CANNOT_CONFIRM",
        "risk_tone": "CANNOT_CONFIRM",
        "big_picture": [],
        "mainlines": [],
        "core_stocks": [],
        "observation_pool": [],
        "next_day_trigger_tree": [],
        "quality_gate": [],
        "cannot_confirm": ["A_SHARE_REVIEW_NOT_MATERIALIZED"],
        "model_review": {
            "status": "NOT_MATERIALIZED",
            "cannot_confirm": ["A_SHARE_CLOSE_MODEL_NOT_MATERIALIZED"],
        },
        "source_evidence": [],
        "source_role": "NOT_MATERIALIZED",
        "source_sha256": "",
        "review_surface": {
            "tier": "COMPACT_NOT_MATERIALIZED",
            "status": "NOT_MATERIALIZED",
            "trade_date": trade_date,
            "source_role": "NOT_MATERIALIZED",
            "source_refs": [],
        },
        "write_policy": "review_only_read_only",
        **SAFETY_FLAGS,
    }


def _legacy_projection(review: Mapping[str, Any]) -> dict[str, Any]:
    """Project the canonical A object; this function never reads or writes a store."""
    projection = {
        "trade_date": review["trade_date"],
        "headline": review["headline"],
        "market_regime": review["market_regime"],
        "risk_tone": review["risk_tone"],
        "first_screen_big_picture": deepcopy(review["big_picture"]),
        "mainlines": deepcopy(review["mainlines"]),
        "core_stocks": deepcopy(review["core_stocks"]),
        "observation_pool": deepcopy(review["observation_pool"]),
        "next_day_trigger_tree_v2": deepcopy(review["next_day_trigger_tree"]),
        "human_video_gap_scorecard": deepcopy(review["quality_gate"]),
        "localized_role_rows": deepcopy(review["core_stocks"]),
        "replay_model_v1": deepcopy(review["model_review"]),
        "cannot_confirm": deepcopy(review["cannot_confirm"]),
        **SAFETY_FLAGS,
    }
    # Keep the old V3-shaped view useful without dropping Review Core's rich
    # rows.  These are A-share-only fields; HK remains copied verbatim by the
    # outer envelope.
    rich_fields = (
        "summary_cards", "market_rows", "prior_plan_rows", "board_rows", "anchor_rows",
        "anchor_role_v3_rows", "intraday_handoff_rows", "catalyst_rows", "trigger_rows",
        "scenario_tree_rows", "video", "video_gap_rows", "source_status_rows",
        "formal_pool_validation", "rule_adoption_rows", "video_learning_rows",
        "cannot_confirm_items", "review_core_bundle", "review_surface", "stage_validation_rows",
        "source_run_id", "artifact_sha256",
    )
    for key in rich_fields:
        if key in review:
            projection[key] = deepcopy(review[key])
    return projection


def review_envelope(
    trade_date: str,
    *,
    a_review: Mapping[str, Any] | None,
    hk_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose one canonical A review, the existing HK review, and a compatibility view."""
    trade_date = _date(trade_date)
    if a_review is None:
        canonical_a = _not_materialized(trade_date)
    else:
        canonical_a = deepcopy(dict(a_review))
        if validate_a_share_review(canonical_a) != trade_date:
            raise ValueError("A-share review does not match requested trade date")
    return {
        "schema_version": "v3_5.review_envelope.v1",
        "trade_date": trade_date,
        "market_reviews": {"A": canonical_a, "HK": deepcopy(dict(hk_review))},
        "fupan_review_v3": _legacy_projection(canonical_a),
        **SAFETY_FLAGS,
    }
