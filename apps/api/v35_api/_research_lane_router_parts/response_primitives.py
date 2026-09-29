"""apps.api.v35_api.research_lane_router: response_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __is_verifiable_close_snapshot_body(_v4_scope, /, result):
    """Return whether a projected snapshot can anchor the market-date picker.

    The date discovery endpoint also sees generic ``external_finance``
    articles.  Reuse the normal projection above so manifest, receipt, row
    shape, and capture identity checks remain the single validation path.  A
    projected snapshot is eligible only when its close phase, session date,
    provider-date binding, and raw provider response evidence are present.
    ``PARTIAL`` remains eligible: date discovery must not turn an explicitly
    partial close into a missing date merely because some quotes are absent.
    """

    if result.get("status") not in {"READY", "PARTIAL"}:
        return False
    if result.get("capture_phase") != "POST_CLOSE":
        return False
    source_date = _v4_global(_v4_scope, 'str')(result.get("source_date") or "")
    if not source_date:
        return False
    provider_dates = result.get("provider_session_dates")
    if provider_dates != [source_date]:
        return False
    source_response_sha256 = result.get("source_response_sha256")
    if (
        not _v4_global(_v4_scope, 'isinstance')(source_response_sha256, _v4_global(_v4_scope, 'str'))
        or _v4_global(_v4_scope, 'len')(source_response_sha256) != 64
        or _v4_global(_v4_scope, 'any')(character not in "0123456789abcdefABCDEF" for character in source_response_sha256)
    ):
        return False
    return True


def __missing_body(_v4_scope, /, *, research_date, reason, identity, endpoint_mode):
    return {
        "schema_version": "v3_5.research_lane.v1",
        "status": "NOT_MATERIALIZED",
        "research_date": research_date,
        "endpoint_mode": endpoint_mode,
        "reason": reason,
        "cannot_confirm": [f"RESEARCH_LANE_NOT_MATERIALIZED:{identity}"],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def __no_event_body(_v4_scope, /, reason):
    return {
        "ok": True,
        "status": reason,
        "schema_version": "v3_5.research_publish.v1",
        "module_id": "research_intelligence",
        "event_id": "",
        "write_policy": "read_only",
        "default_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def __quality_summary_body(_v4_scope, /, payload):
    articles = payload["articles"]
    stock_pool = payload["stock_pool"]
    evidence_levels: dict[str, int] = {}
    for article in articles:
        level = _v4_global(_v4_scope, 'str')(article.get("evidence_level") or "UNKNOWN")
        evidence_levels[level] = evidence_levels.get(level, 0) + 1
    return {
        "raw_item_count": _v4_global(_v4_scope, 'int')(payload["article_count"]),
        "research_item_count": _v4_global(_v4_scope, 'int')(payload["article_count"]),
        "stock_evidence_count": _v4_global(_v4_scope, 'int')(payload["article_count"]),
        "stock_daily_count": _v4_global(_v4_scope, 'int')(payload["stock_pool_count"]),
        "l2_medium_count": evidence_levels.get("L2_MEDIUM", 0),
        "l3_strong_count": evidence_levels.get("L3_STRONG", 0),
        "source_counts": _v4_global(_v4_scope, 'dict')(payload["source_counts"]),
        "source_schema_version": payload["source_schema_version"],
        "source_generated_at": payload["source_generated_at"],
    }
