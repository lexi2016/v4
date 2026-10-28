"""ops.materialize_research_peripherals: materialization (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _materialize_external_finance_body(_v4_scope, /, *, data_root, trade_date, fetch_rss, fetched_at, translate_text, resolve_original_url, **kwargs):
    payload = _v4_global(_v4_scope, 'build_external_finance_payload')(
        trade_date,
        fetch_rss=fetch_rss,
        fetched_at=fetched_at,
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        **kwargs,
    )
    result = _v4_global(_v4_scope, '_publish_or_hourly_refresh')(_v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root), payload)
    return {"payload": payload, **result}


def _materialize_ai_news_body(_v4_scope, /, *, data_root, trade_date, fetch_html, fetched_at, source_url, timeout, limit, translate_text, transport):
    fetched_dt = _v4_global(_v4_scope, '_coerce_datetime')(fetched_at)
    fetcher = fetch_html or _v4_global(_v4_scope, 'fetch_url')
    raw_html, receipt = _v4_global(_v4_scope, '_fetch_feed')(
        fetcher,
        source_url,
        timeout,
        transport=transport,
    )
    page_html = raw_html.decode("utf-8", errors="replace") if _v4_global(_v4_scope, 'isinstance')(raw_html, _v4_global(_v4_scope, 'bytes')) else _v4_global(_v4_scope, 'str')(raw_html)
    payload = _v4_global(_v4_scope, 'build_ai_news_payload')(
        trade_date,
        page_html=page_html,
        fetched_at=fetched_dt,
        source_url=source_url,
        limit=limit,
        translate_text=translate_text,
        translation_timeout=timeout,
        feed_receipts=(
            [_v4_global(_v4_scope, '_feed_receipt')("aihot", source_url, receipt)]
            if transport is not None or fetch_html is None
            else None
        ),
    )
    result = _v4_global(_v4_scope, '_publish_or_hourly_refresh')(_v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root), payload)
    return {"payload": payload, **result}
