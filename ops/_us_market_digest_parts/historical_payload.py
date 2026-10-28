"""ops.us_market_digest: historical_payload (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __us_subscriptions_body(_v4_scope, /):
    """Return the five US feeds across both reviewed materializer contracts.

    The newer reviewed materializer annotates ``DEFAULT_SUBSCRIPTIONS`` with
    market scopes.  The frozen scheduler parent predates that field, so its
    equivalent four US themed subscriptions need an explicit compatibility
    selection plus the US equities feed.  Keeping this adapter in the
    candidate producer avoids changing the parent materializer or creating a
    second feed producer.
    """
    scoped = _v4_global(_v4_scope, 'tuple')(
        subscription
        for subscription in _v4_global(_v4_scope, 'DEFAULT_SUBSCRIPTIONS')
        if "US_EQUITY" in {
            _v4_global(_v4_scope, 'str')(scope).strip()
            for scope in (subscription.get("market_scopes") or [])
        }
    )
    if scoped:
        return scoped
    fallback = _v4_global(_v4_scope, 'tuple')(
        {
            **_v4_global(_v4_scope, 'dict')(subscription),
            "market_scopes": ["US_EQUITY"],
        }
        for subscription in _v4_global(_v4_scope, 'DEFAULT_SUBSCRIPTIONS')
        if _v4_global(_v4_scope, 'str')(subscription.get("id") or "").strip()
        in _v4_global(_v4_scope, '_US_FALLBACK_SUBSCRIPTION_IDS')
    )
    if fallback:
        return (*fallback, _v4_global(_v4_scope, '_US_EQUITY_FALLBACK_SUBSCRIPTION'))
    return (_v4_global(_v4_scope, '_US_EQUITY_FALLBACK_SUBSCRIPTION'),)


def __historical_subscriptions_body(_v4_scope, /, session_date):
    """Add a provider date bound when the parent has no URL-builder seam."""
    selected = (
        session_date
        if _v4_global(_v4_scope, 'isinstance')(session_date, _v4_global(_v4_scope, 'date')) and not _v4_global(_v4_scope, 'isinstance')(session_date, _v4_global(_v4_scope, 'datetime'))
        else _v4_global(_v4_scope, '_session_date')(_v4_global(_v4_scope, 'str')(session_date))
    )
    next_date = selected + _v4_global(_v4_scope, 'timedelta')(days=1)
    bounded = []
    for subscription in _v4_global(_v4_scope, '_us_subscriptions')():
        item = _v4_global(_v4_scope, 'dict')(subscription)
        item["query"] = (
            f"{_v4_global(_v4_scope, 'clean_text')(item.get('query'))} after:{selected.isoformat()} "
            f"before:{next_date.isoformat()}"
        )
        bounded.append(item)
    return _v4_global(_v4_scope, 'tuple')(bounded)


def _build_us_historical_backfill_payload_body(_v4_scope, /, trade_date, *, development_dates, fetched_at, fetch_rss, translate_text, resolve_original_url, **kwargs):
    """Build a retrospective payload only for an explicit development allowlist."""
    if resolve_original_url is not None:
        raise _v4_global(_v4_scope, 'ValueError')("US RSS lane does not fetch publisher bodies")
    selected = _v4_global(_v4_scope, '_date')(trade_date)
    try:
        allowlist = {_v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(value)) for value in development_dates}
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'ValueError')("development date allowlist is invalid") from error
    if selected not in allowlist:
        raise _v4_global(_v4_scope, 'ValueError')("trade date is not in the development date allowlist")
    builder_kwargs = _v4_global(_v4_scope, 'dict')(
        fetched_at=fetched_at,
        fetch_rss=fetch_rss,
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        **kwargs,
    )
    if "rss_url_builder" in _v4_global(_v4_scope, 'inspect').signature(_v4_global(_v4_scope, 'build_external_finance_payload')).parameters:
        # Newer reviewed materializer: keep the exact date-bounded URL seam.
        payload = _v4_global(_v4_scope, 'build_external_finance_payload')(
            selected,
            subscriptions=_v4_global(_v4_scope, '_us_subscriptions')(),
            rss_url_builder=lambda query: _v4_global(_v4_scope, 'google_rss_historical_url')(query, selected),
            **builder_kwargs,
        )
    else:
        # Frozen scheduler parent: encode the same explicit date bound in each
        # query because its materializer only exposes ``lookback_days``.
        payload = _v4_global(_v4_scope, 'build_external_finance_payload')(
            selected,
            subscriptions=_v4_global(_v4_scope, '_historical_subscriptions')(selected),
            **builder_kwargs,
        )
    metadata = _v4_global(_v4_scope, 'build_capture_metadata')(
        selected,
        _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'),
        captured_at=payload["fetched_at"],
        capture_origin=_v4_global(_v4_scope, 'HISTORICAL_BACKFILL'),
        original_time_capture=False,
    )
    annotated = _v4_global(_v4_scope, '_annotate_payload')(
        payload,
        metadata,
    )
    annotated["market_snapshot"] = _v4_global(_v4_scope, '_empty_market_snapshot')(
        selected,
        capture_phase=_v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'),
        captured_at=payload["fetched_at"],
        reasons=["HISTORICAL_BACKFILL_QUOTE_CAPTURE_UNCONFIRMED"],
    )
    annotated["market_snapshot_status"] = _v4_global(_v4_scope, 'str')(annotated["market_snapshot"]["status"])
    annotated["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
        _v4_global(_v4_scope, 'set')(annotated.get("cannot_confirm") or [])
        | _v4_global(_v4_scope, 'set')(annotated["market_snapshot"].get("cannot_confirm") or [])
    )
    return annotated
