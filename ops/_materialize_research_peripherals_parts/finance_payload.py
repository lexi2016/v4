"""ops.materialize_research_peripherals: finance_payload (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _overview_from_details_body(_v4_scope, /, details):
    overview: list[dict[str, Any]] = []
    seen_theme: set[str] = _v4_global(_v4_scope, 'set')()
    for row in details:
        theme = _v4_global(_v4_scope, 'str')(row.get("theme_bucket") or "")
        if theme and theme in seen_theme and _v4_global(_v4_scope, 'len')(overview) >= 8:
            continue
        if theme:
            seen_theme.add(theme)
        overview.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "title_zh": row.get("title_zh"),
                "summary": row.get("summary"),
                "summary_zh": row.get("summary_zh"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "url": row.get("url"),
                "original_url": row.get("original_url"),
                "fetched_at": row.get("fetched_at"),
                "published_at": row.get("published_at"),
                "source_tier": row.get("source_tier"),
                "theme_bucket": row.get("theme_bucket"),
                "cannot_confirm": _v4_global(_v4_scope, 'list')(row.get("cannot_confirm") or []),
                "translation_status": row.get("translation_status"),
                "translation_source": row.get("translation_source"),
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
        if _v4_global(_v4_scope, 'len')(overview) >= 12:
            break
    return overview


def __base_payload_body(_v4_scope, /, *, trade_date, source, status, source_url, fetched_at, raw_item_count, item_count, overview, details, items, cannot_confirm, feed_receipts):
    payload = {
        "schema_version": "v3_5.research_peripheral.v1",
        "trade_date": _v4_global(_v4_scope, '_date')(trade_date),
        "source": source,
        "status": status,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "raw_item_count": _v4_global(_v4_scope, 'int')(raw_item_count),
        "item_count": _v4_global(_v4_scope, 'int')(item_count),
        "overview": overview,
        "details": details,
        "items": items,
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'str')(item) for item in cannot_confirm if _v4_global(_v4_scope, 'str')(item))),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if feed_receipts is not None:
        payload["feed_receipts"] = [_v4_global(_v4_scope, 'dict')(receipt) for receipt in feed_receipts]
    return payload


def _build_external_finance_payload_body(_v4_scope, /, trade_date, *, fetched_at, fetch_rss, subscriptions, lookback_days, limit_per_feed, max_items, timeout, translate_text, resolve_original_url, transport):
    selected_date = _v4_global(_v4_scope, '_date')(trade_date)
    fetched_dt = _v4_global(_v4_scope, '_coerce_datetime')(fetched_at)
    fetched_iso = _v4_global(_v4_scope, 'isoformat_utc')(fetched_dt)
    fetcher = fetch_rss or _v4_global(_v4_scope, 'fetch_url')
    rows: list[dict[str, Any]] = []
    cannot_confirm: list[str] = ["GOOGLE_NEWS_RSS_DISCOVERY_ONLY"]
    source_urls: list[str] = []
    feed_receipts: list[dict[str, Any]] = []
    fetch_failures = 0
    for subscription in subscriptions:
        normalized = {_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, 'str')(value) for key, value in subscription.items()}
        feed_url = _v4_global(_v4_scope, 'google_rss_url')(normalized["query"], lookback_days)
        source_urls.append(feed_url)
        try:
            raw_xml, receipt = _v4_global(_v4_scope, '_fetch_feed')(
                fetcher,
                feed_url,
                timeout,
                transport=transport,
            )
            rows.extend(
                _v4_global(_v4_scope, 'parse_rss_items')(
                    raw_xml,
                    subscription_id=normalized["id"],
                    theme_bucket=normalized.get("theme_bucket", normalized["id"]),
                    fetched_at=fetched_dt,
                    source_url=feed_url,
                    limit=limit_per_feed,
                )
            )
            feed_receipts.append(_v4_global(_v4_scope, '_feed_receipt')(normalized["id"], feed_url, receipt))
        except _v4_global(_v4_scope, 'TransportError') as error:
            fetch_failures += 1
            feed_receipts.append(
                _v4_global(_v4_scope, '_feed_receipt')(
                    normalized["id"],
                    feed_url,
                    _v4_global(_v4_scope, 'getattr')(error, "receipt", None),
                    error=(_v4_global(_v4_scope, 'getattr')(error, "receipt", {}) or {}).get("error")
                    or f"{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",
                )
            )
            cannot_confirm.append(f"EXTERNAL_FINANCE_FETCH_FAILED:{normalized['id']}")
        except (_v4_global(_v4_scope, 'ET').ParseError, _v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'urllib').error.URLError, _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
            fetch_failures += 1
            feed_receipts.append(
                _v4_global(_v4_scope, '_feed_receipt')(
                    normalized["id"],
                    feed_url,
                    error=f"{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",
                )
            )
            cannot_confirm.append(f"EXTERNAL_FINANCE_FETCH_FAILED:{normalized['id']}")
    admission_rejections: list[str] = []
    details = _v4_global(_v4_scope, 'dedupe_and_rank')(
        rows,
        max_items=max_items,
        fetched_at=fetched_dt,
        lookback_days=lookback_days,
        rejected_reasons=admission_rejections,
    )
    if resolve_original_url is not None:
        details = _v4_global(_v4_scope, '_resolve_original_rows')(
            details,
            resolver=resolve_original_url,
            timeout=timeout,
        )
        if _v4_global(_v4_scope, 'any')(
            row.get("original_url_status") != "VERIFIED_PUBLISHER_URL"
            for row in details
        ):
            cannot_confirm.append("ORIGINAL_URL_INCOMPLETE")
        details, resolved_rejections = _v4_global(_v4_scope, '_admit_external_rows')(
            details,
            fetched_at=fetched_dt,
            lookback_days=lookback_days,
        )
        admission_rejections.extend(resolved_rejections)
    cannot_confirm.extend(admission_rejections)
    translation_incomplete = False
    if translate_text is not None:
        details = _v4_global(_v4_scope, '_translate_rows')(
            details,
            translate_text=translate_text,
            timeout=timeout,
        )
        translation_incomplete = _v4_global(_v4_scope, 'any')(
            row.get("translation_status") == "CANNOT_CONFIRM" for row in details
        )
        if translation_incomplete:
            cannot_confirm.append("ZH_TRANSLATION_INCOMPLETE")
    status = (
        "CANNOT_CONFIRM"
        if details and translation_incomplete
        else "READY"
        if details
        else "CANNOT_CONFIRM"
        if fetch_failures or admission_rejections
        else "READY_EMPTY"
    )
    return _v4_global(_v4_scope, '_base_payload')(
        trade_date=selected_date,
        source="external_finance",
        status=status,
        source_url=_v4_global(_v4_scope, 'GOOGLE_NEWS_RSS'),
        fetched_at=fetched_iso,
        raw_item_count=_v4_global(_v4_scope, 'len')(rows),
        item_count=_v4_global(_v4_scope, 'len')(details),
        overview=_v4_global(_v4_scope, 'overview_from_details')(details),
        details=details,
        items=[],
        cannot_confirm=cannot_confirm,
        feed_receipts=feed_receipts,
    )
