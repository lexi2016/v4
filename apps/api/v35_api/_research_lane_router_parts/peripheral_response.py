"""apps.api.v35_api.research_lane_router: peripheral_response (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __morning_news_response_body(_v4_scope, /, payload):
    if payload is None:
        return {
            "status": "NOT_MATERIALIZED",
            "articles": [],
            "articles_count": 0,
            "stock_mentions_count": 0,
            "cannot_confirm": ["MORNING_NEWS_SEPARATE_SOURCE_NOT_MATERIALIZED"],
        }
    return {
        "status": _v4_global(_v4_scope, 'str')(payload.get("status") or "CANNOT_CONFIRM"),
        "articles": _v4_global(_v4_scope, 'list')(payload.get("articles") or []),
        "articles_count": _v4_global(_v4_scope, 'int')(payload.get("article_count") or 0),
        "stock_mentions_count": _v4_global(_v4_scope, 'int')(payload.get("mention_count") or 0),
        "required_news_contract": _v4_global(_v4_scope, 'dict')(payload.get("required_news_contract") or {}),
        "cannot_confirm": _v4_global(_v4_scope, 'list')(payload.get("cannot_confirm") or []),
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
    }


def __peripheral_response_body(_v4_scope, /, source, payload):
    if payload is None:
        return {
            "schema_version": "v3_5.research_peripheral.v1",
            "source": source,
            "status": "NOT_MATERIALIZED",
            "source_url": "",
            "fetched_at": "",
            "raw_item_count": 0,
            "item_count": 0,
            "overview": [],
            "details": [],
            "items": [],
            "feed_receipts": [],
            "us_session_captures": [],
            "cannot_confirm": [
                f"{source.upper()}_PERIPHERAL_NOT_MATERIALIZED"
            ],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    response = {
        "schema_version": _v4_global(_v4_scope, 'str')(payload["schema_version"]),
        "source": source,
        "status": _v4_global(_v4_scope, 'str')(payload["status"]),
        "source_url": _v4_global(_v4_scope, 'str')(payload["source_url"]),
        "fetched_at": _v4_global(_v4_scope, 'str')(payload["fetched_at"]),
        "raw_item_count": _v4_global(_v4_scope, 'int')(payload["raw_item_count"]),
        "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
        "overview": _v4_global(_v4_scope, 'list')(payload["overview"]),
        "details": _v4_global(_v4_scope, 'list')(payload["details"]),
        "items": _v4_global(_v4_scope, 'list')(payload["items"]),
        "feed_receipts": _v4_global(_v4_scope, 'list')(payload.get("feed_receipts") or []),
        "us_session_captures": _v4_global(_v4_scope, 'list')(payload.get("us_session_captures") or []),
        "cannot_confirm": _v4_global(_v4_scope, 'list')(payload["cannot_confirm"]),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field in ("capture_origin", "original_time_capture"):
        if field in payload:
            response[field] = payload[field]
    return response
