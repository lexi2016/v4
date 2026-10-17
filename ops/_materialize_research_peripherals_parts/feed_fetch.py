"""ops.materialize_research_peripherals: feed_fetch (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __feed_receipt_body(_v4_scope, /, feed_id, url, receipt, *, error):
    """Normalize transport evidence into a stable per-feed contract."""
    source = _v4_global(_v4_scope, 'dict')(receipt or {})
    elapsed = source.get("elapsed_ms", 0)
    try:
        elapsed_ms = _v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(elapsed))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        elapsed_ms = 0
    status = source.get("http_status")
    if status is not None:
        try:
            status = _v4_global(_v4_scope, 'int')(status)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            status = None
    return {
        "feed_id": _v4_global(_v4_scope, 'str')(feed_id),
        "url": _v4_global(_v4_scope, 'str')(url),
        "elapsed_ms": elapsed_ms,
        "http_status": status,
        "error": error if error is not None else source.get("error"),
        "proxy_used": _v4_global(_v4_scope, 'bool')(source.get("proxy_used", False)),
        "fallback_used": _v4_global(_v4_scope, 'bool')(source.get("fallback_used", False)),
    }


def __fetch_feed_body(_v4_scope, /, fetcher, url, timeout, *, transport):
    """Fetch one feed and retain transport metadata for its source receipt."""
    if fetcher is _v4_global(_v4_scope, 'fetch_url'):
        result = (transport or _v4_global(_v4_scope, '_default_http_transport')()).fetch(url, timeout=timeout)
    else:
        result = _v4_global(_v4_scope, '_call_fetcher')(fetcher, url, timeout)
    if _v4_global(_v4_scope, 'isinstance')(result, _v4_global(_v4_scope, 'FetchResult')):
        return result.body, _v4_global(_v4_scope, 'dict')(result.receipt)
    return result, {
        "elapsed_ms": 0,
        "http_status": None,
        "error": None,
        "proxy_used": False,
        "fallback_used": False,
    }


def __publish_or_hourly_refresh_body(_v4_scope, /, store, payload):
    """Publish once, then CAS-refresh the same exact-date source hourly."""
    existing = store.read_exact(_v4_global(_v4_scope, 'str')(payload["trade_date"]), _v4_global(_v4_scope, 'str')(payload["source"]))
    if existing is None:
        return store.publish(payload)
    if (
        existing.get("status") in _v4_global(_v4_scope, '_REUSABLE_STATUSES')
        and payload.get("status") == "CANNOT_CONFIRM"
    ):
        attempt = store.record_refresh_attempt(
            payload,
            retained_payload=existing,
            reason="FAILED_REFRESH_RETAINED_LAST_READY",
        )
        trade_date = _v4_global(_v4_scope, 'str')(existing["trade_date"])
        source = _v4_global(_v4_scope, 'str')(existing["source"])
        return {
            "payload": existing,
            "trade_date": trade_date,
            "source": source,
            "payload_path": store._relative(trade_date, source),
            "receipt_path": store._receipt_relative(trade_date, source),
            "payload_sha256": _v4_global(_v4_scope, '_sha256')(existing),
            "item_count": _v4_global(_v4_scope, 'int')(existing["item_count"]),
            "retained_previous": True,
            **attempt,
        }
    return store.replace(
        payload,
        expected_sha256=_v4_global(_v4_scope, '_sha256')(existing),
        reason="HOURLY_REFRESH",
    )
