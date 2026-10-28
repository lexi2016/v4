"""apps.api.v35_api.research_lane_router: status_response (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __status_only_lane_response_body(_v4_scope, /, status_lane, *, research_date, endpoint_mode, page_trade_date, source_binding, morning_news, peripherals):
    """Project dispatcher receipts without inventing an archive/feed."""

    timeline = _v4_global(_v4_scope, 'dict')(status_lane)
    zsxq = _v4_global(_v4_scope, 'dict')(timeline.pop("zsxq_hourly", {}))
    cannot_confirm = [f"RESEARCH_ARCHIVE_NOT_MATERIALIZED:{research_date}"]
    cannot_confirm.extend(
        item
        for row in timeline.get("slots", [])
        for item in (row.get("cannot_confirm") or [])
        if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str'))
    )
    if zsxq.get("scheduled_0830", {}).get("status") not in {"READY", "SUCCEEDED"}:
        cannot_confirm.extend(item for item in zsxq.get("cannot_confirm", []) if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')))
    quality = {
        "raw_item_count": 0,
        "research_item_count": 0,
        "stock_evidence_count": 0,
        "stock_daily_count": 0,
        "l2_medium_count": 0,
        "l3_strong_count": 0,
        "source_counts": {},
        "source_schema_version": "v3_5.research_status_only.v1",
        "source_generated_at": "",
    }
    exact_peripherals = _v4_global(_v4_scope, 'dict')(peripherals or {})
    has_partial_content = morning_news is not None or _v4_global(_v4_scope, 'any')(
        payload is not None for payload in exact_peripherals.values()
    )
    status = "LIVE_PERIPHERAL_ONLY" if has_partial_content else "NOT_MATERIALIZED"
    projection_mode = (
        "STATUS_WITH_PERIPHERALS" if has_partial_content else "STATUS_ONLY"
    )
    return {
        "schema_version": "v3_5.research_lane.v1",
        "status": status,
        "projection_mode": projection_mode,
        "reason": (
            "RESEARCH_ARCHIVE_NOT_MATERIALIZED_WITH_PERIPHERALS"
            if has_partial_content
            else "RESEARCH_LANE_SNAPSHOT_NOT_FOUND"
        ),
        "research_date": research_date,
        "trade_date": research_date,
        "intelligence_date": research_date,
        "source_binding": _v4_global(_v4_scope, 'dict')(source_binding or {}),
        "page_trade_date": page_trade_date,
        "date_binding_policy": "explicit_research_date_with_page_context",
        "endpoint_mode": endpoint_mode,
        "stock_research_daily": [],
        "stock_research_timeline": [],
        "research_pool_bridge": [],
        "research_quality_summary": quality,
        "morning_news": _v4_global(_v4_scope, '_morning_news_response')(morning_news),
        "zsxq_hourly": zsxq,
        "external_finance": _v4_global(_v4_scope, '_peripheral_response')(
            "external_finance", exact_peripherals.get("external_finance")
        ),
        "ai_news": _v4_global(_v4_scope, '_peripheral_response')(
            "ai_news", exact_peripherals.get("ai_news")
        ),
        "ocr_ingestion": {
            "status": "NOT_MATERIALIZED",
            "items": [],
            "cannot_confirm": ["OCR_INGESTION_NOT_MATERIALIZED"],
        },
        "news_workbench": {
            "schema_version": "v3_5.news_workbench.v1",
            "status": "READ_ONLY_EMPTY",
            "action_rows": [],
            "cannot_confirm": ["LANE_NEWS_WORKBENCH_ACTIONS_NOT_MATERIALIZED"],
        },
        "key_investment_messages": [],
        "research_intelligence_timeline": timeline,
        "hourly_research": {
            "schema_version": "v3_5.hourly_research_status_only.v1",
            "status": "STATUS_ONLY",
            "slot_count": timeline.get("slot_count", 0),
            "latest_slot": timeline.get("latest_slot", ""),
            "source_schema_version": timeline.get("schema_version", ""),
            "source_generated_at": "",
            "source_counts": {},
            "cannot_confirm": ["HOURLY_RESEARCH_ARCHIVE_NOT_MATERIALIZED"],
        },
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
