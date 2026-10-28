"""domains.research_day_product: consumer (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _consume_authoritative_research_day_body(_v4_scope, /, product, *, requested_date):
    """White-hair consumer: exact-date and authoritative-only, fail closed."""

    requested_date = _v4_global(_v4_scope, '_date')(requested_date)
    if product is None:
        return _v4_global(_v4_scope, '_consumer_gap')(
            requested_date,
            f"RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED:{requested_date}",
        )
    try:
        validated_date = _v4_global(_v4_scope, 'validate_research_day_product')(product)
    except _v4_global(_v4_scope, 'ValueError') as error:
        return _v4_global(_v4_scope, '_consumer_gap')(
            requested_date,
            f"RESEARCH_DAY_PRODUCT_INVALID:{error}",
        )
    if (
        validated_date != requested_date
        or product.get("status") != "READY"
        or not product.get("authoritative")
    ):
        return _v4_global(_v4_scope, '_consumer_gap')(
            requested_date,
            _v4_global(_v4_scope, 'str')(
                (product.get("cannot_confirm") or [
                    f"RESEARCH_DAY_NOT_AUTHORITATIVE:{requested_date}"
                ])[0]
            ),
            resolved_date=validated_date if validated_date == requested_date else None,
        )
    return _v4_global(_v4_scope, 'dict')(product)


def __consumer_gap_body(_v4_scope, /, requested_date, reason, *, resolved_date):
    """Return a complete diagnostic envelope without exposing a non-authority pool."""

    empty_coverage = {
        "expected_slots": _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')),
        "ready_slots": 0,
        "missing_slots": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')),
        "complete": False,
        "slot_matrix": [],
    }
    return {
        "schema_version": _v4_global(_v4_scope, 'PRODUCT_SCHEMA_VERSION'),
        "contract_id": _v4_global(_v4_scope, 'CONTRACT_ID'),
        "workflow_name": _v4_global(_v4_scope, 'WORKFLOW_NAME'),
        "pass_signal": _v4_global(_v4_scope, 'PASS_SIGNAL'),
        "status": "CANNOT_CONFIRM",
        "authoritative": False,
        "endpoint_mode": "EXACT",
        "date_mode": _v4_global(_v4_scope, 'DATE_MODE'),
        "archive_date": requested_date,
        "requested_date": requested_date,
        "resolved_date": resolved_date,
        "timezone": _v4_global(_v4_scope, 'TIMEZONE'),
        "is_full_day": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "expected_slots": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'EXPECTED_RESEARCH_SLOTS')),
        "coverage": empty_coverage,
        "counts": {
            "raw_rows": 0,
            "evidence_rows": 0,
            "excluded_rows": 0,
            "mention_pairs": 0,
            "urls": 0,
            "stock_rollups": 0,
            "high_priority": 0,
            "duplicate_pairs": 0,
        },
        "exclusions": {
            "date_mismatch": 0,
            "pit_violation": 0,
            "invalid_row": 0,
        },
        "excluded_by_date": {},
        "slot_matrix": [],
        "evidence_rows": [],
        "mention_pairs": [],
        "stock_rollups": [],
        "high_priority": [],
        "high_priority_status": {
            "status": "CANNOT_CONFIRM",
            "rule_id": None,
            "registry": "MISSING",
            "cannot_confirm": "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
        },
        "jyg_coverage": {
            "status": "CANNOT_CONFIRM",
            "articles": None,
            "expected_articles": None,
            "stock_mentions": None,
            "registry": "MISSING",
            "gap": _v4_global(_v4_scope, '_MISSING_REGISTRY_GAP'),
        },
        "lineage": None,
        "cannot_confirm": [reason],
        "loading_complete": True,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
