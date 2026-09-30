"""ops.materialize_research_peripherals: feed_admission (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __is_article_url_body(_v4_scope, /, value):
    """Accept a publisher article or Google News article redirect only."""
    url = _v4_global(_v4_scope, 'clean_text')(value)
    parsed = _v4_global(_v4_scope, 'urllib').parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    raw_path = _v4_global(_v4_scope, 'urllib').parse.unquote(parsed.path or "")
    if not raw_path or raw_path == "/" or raw_path.endswith("/"):
        return False
    path = raw_path.rstrip("/")
    if host == "news.google.com":
        parts = [part for part in path.split("/") if part]
        return _v4_global(_v4_scope, 'len')(parts) >= 2 and parts[-2] in {"articles", "read"}
    if not path:
        return False
    lower_path = path.lower()
    if _v4_global(_v4_scope, 're').search(r"/(?:etfs?|symbols?|markets?|categories?|topics?|tags?|search)(?:/|$)", lower_path):
        return False
    if lower_path.rsplit("/", 1)[-1] in {"news", "business", "finance", "stocks", "home", "index"}:
        return False
    return True


def __row_admission_reasons_body(_v4_scope, /, row, *, fetched_at, lookback_days):
    """Return deterministic source admission failures for one finance row."""
    reasons: list[str] = []
    published_raw = _v4_global(_v4_scope, 'clean_text')(row.get("published_at"))
    if not published_raw:
        reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_MISSING")
        published = None
    else:
        try:
            published = _v4_global(_v4_scope, '_coerce_datetime')(published_raw)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
            published = None
            reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_INVALID")
    try:
        fetched = _v4_global(_v4_scope, '_coerce_datetime')(fetched_at or row.get("fetched_at"))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
        fetched = None
    if published is not None and fetched is not None:
        if published > fetched:
            reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_AFTER_FETCHED_AT")
        elif fetched - published > _v4_global(_v4_scope, 'timedelta')(days=_v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(lookback_days))):
            reasons.append("EXTERNAL_FINANCE_ITEM_STALE")

    url = _v4_global(_v4_scope, '_row_url')(row)
    if not url:
        reasons.append("EXTERNAL_FINANCE_ARTICLE_URL_MISSING")
    elif not _v4_global(_v4_scope, '_is_article_url')(url):
        if _v4_global(_v4_scope, 'clean_text')(row.get("original_url_status")).upper() == "CANNOT_CONFIRM":
            reasons.append("EXTERNAL_FINANCE_ORIGINAL_URL_UNRESOLVED")
        else:
            reasons.append("EXTERNAL_FINANCE_PAGE_NOT_ARTICLE")
    elif _v4_global(_v4_scope, 'clean_text')(row.get("original_url_status")).upper() == "CANNOT_CONFIRM":
        reasons.append("EXTERNAL_FINANCE_ORIGINAL_URL_UNRESOLVED")
    return _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(reasons))


def __admit_external_rows_body(_v4_scope, /, rows, *, fetched_at, lookback_days):
    admitted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        reasons = _v4_global(_v4_scope, '_row_admission_reasons')(
            row,
            fetched_at=fetched_at,
            lookback_days=lookback_days,
        )
        if reasons:
            rejected.extend(reasons)
            continue
        admitted.append(_v4_global(_v4_scope, 'dict')(row))
    return admitted, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(rejected))
