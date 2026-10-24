"""apps.api.v35_api.research_lane_router: lane_response (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __lane_response_body(_v4_scope, /, archive, *, research_date, endpoint_mode, daily_archive=None, hourly_slot='', hourly_slot_count=0, source_binding=None, morning_news=None, peripherals=None):
    articles = _v4_global(_v4_scope, 'list')(archive["articles"])
    timeline = [
        {
            **article,
            "evidence_id": article["article_id"],
            "event_id": article["article_id"],
            "event_time": article["published_at"],
        }
        for article in articles
    ]
    pool = _v4_global(_v4_scope, 'list')(archive["stock_pool"])
    cannot_confirm = _v4_global(_v4_scope, 'list')(archive["cannot_confirm"])
    zsxq_articles = [
        article
        for article in articles
        if hourly_slot
        and _v4_global(_v4_scope, 'str')(article.get("source_type") or "").strip().lower() == "zsxq"
    ]
    available_peripheral = {"zsxq_hourly"} if zsxq_articles else _v4_global(_v4_scope, 'set')()
    available_peripheral.update(
        name
        for name, peripheral in (peripherals or {}).items()
        if peripheral is not None
    )
    missing_peripheral = [
        name
        for name in (
            "zsxq_hourly",
            "external_finance",
            "ai_news",
            "key_investment_messages",
            "ocr_ingestion",
        )
        if name not in archive and name not in available_peripheral
    ]
    cannot_confirm.extend(
        f"LANE_PERIPHERAL_NOT_MATERIALIZED:{name}" for name in missing_peripheral
    )
    key_investment_messages = archive.get("key_investment_messages")
    if not hourly_slot:
        cannot_confirm.append("HOURLY_SLOT_ARTIFACTS_NOT_IN_ARCHIVE")
    zsxq_hourly = {
        "schema_version": "v3_5.zsxq_hourly_projection.v1",
        "status": "LIVE_HOURLY" if hourly_slot else "ARCHIVE_ONLY",
        "items": zsxq_articles,
        "item_count": _v4_global(_v4_scope, 'len')(zsxq_articles),
        "topic_count": _v4_global(_v4_scope, 'len')(zsxq_articles),
        "latest_slot": hourly_slot,
        "slot_count": hourly_slot_count,
        "source_schema_version": archive["source_schema_version"],
        "source_generated_at": archive["source_generated_at"],
        "cannot_confirm": (
            []
            if zsxq_articles
            else ["ZSXQ_HOURLY_ITEMS_NOT_MATERIALIZED"]
        ),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    is_hourly = _v4_global(_v4_scope, 'bool')(hourly_slot)
    daily_archive_ready = (
        _v4_global(_v4_scope, 'isinstance')(daily_archive, _v4_global(_v4_scope, 'Mapping'))
        and daily_archive.get("status") == "READY"
        and daily_archive.get("authoritative") is True
    )
    daily_archive_status = "READY" if daily_archive_ready else "NOT_MATERIALIZED"
    if not daily_archive_ready:
        cannot_confirm.extend(
            item
            for item in (daily_archive or {}).get("cannot_confirm", [])
            if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str'))
        )
    lane_status = "LIVE_HOURLY" if is_hourly else "DAILY_ARCHIVE"
    response = {
        "schema_version": "v3_5.research_lane.v1",
        # Keep READY for archive consumers, but never let an hourly snapshot
        # masquerade as a daily archive at the top level.
        "status": "LIVE_HOURLY" if is_hourly else "READY",
        "lane_status": lane_status,
        "daily_archive_status": daily_archive_status,
        "research_date": research_date,
        "source_binding": _v4_global(_v4_scope, 'dict')(source_binding or {}),
        "endpoint_mode": endpoint_mode,
        "stock_research_daily": pool,
        "stock_research_timeline": timeline,
        "research_pool_bridge": pool,
        "research_quality_summary": _v4_global(_v4_scope, '_quality_summary')(archive),
        "morning_news": _v4_global(_v4_scope, '_morning_news_response')(morning_news),
        "zsxq_hourly": zsxq_hourly,
        "external_finance": _v4_global(_v4_scope, '_peripheral_response')(
            "external_finance", (peripherals or {}).get("external_finance")
        ),
        "ai_news": _v4_global(_v4_scope, '_peripheral_response')(
            "ai_news", (peripherals or {}).get("ai_news")
        ),
        "news_workbench": {
            "schema_version": "v3_5.news_workbench.v1",
            "status": "READ_ONLY_EMPTY",
            "action_rows": [],
            "cannot_confirm": [
                "LANE_NEWS_WORKBENCH_ACTIONS_NOT_MATERIALIZED"
            ],
        },
        "hourly_research": {
            "schema_version": "v3_5.hourly_research.v1",
            "status": "LIVE_HOURLY" if hourly_slot else "ARCHIVE_ONLY",
            "slot_count": hourly_slot_count,
            "latest_slot": hourly_slot,
            "source_schema_version": archive["source_schema_version"],
            "source_generated_at": archive["source_generated_at"],
            "source_counts": _v4_global(_v4_scope, 'dict')(archive["source_counts"]),
            "cannot_confirm": (
                [] if hourly_slot else ["HOURLY_SLOT_ARTIFACTS_NOT_IN_ARCHIVE"]
            ),
            "daily_archive_status": daily_archive_status,
            "source_binding": _v4_global(_v4_scope, 'dict')(source_binding or {}),
        },
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if _v4_global(_v4_scope, 'isinstance')(key_investment_messages, _v4_global(_v4_scope, 'list')):
        response["key_investment_messages"] = key_investment_messages
    return _v4_global(_v4_scope, 'project_report_roles')(response)
