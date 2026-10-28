"""ops.materialize_research_peripherals: rss_parse (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __parse_item_datetime_body(_v4_scope, /, value):
    if not value:
        return None
    text = _v4_global(_v4_scope, 'str')(value).strip()
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(text.replace("+0800", "+08:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(_v4_global(_v4_scope, '_CST')).replace(tzinfo=None)
        return parsed
    except _v4_global(_v4_scope, 'ValueError'):
        pass
    try:
        parsed = _v4_global(_v4_scope, 'parsedate_to_datetime')(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=_v4_global(_v4_scope, 'UTC'))
        return parsed.astimezone(_v4_global(_v4_scope, '_CST')).replace(tzinfo=None)
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
        return None


def _parse_rss_items_body(_v4_scope, /, raw_xml, *, subscription_id, theme_bucket, fetched_at, source_url, limit):
    raw = raw_xml.encode("utf-8") if _v4_global(_v4_scope, 'isinstance')(raw_xml, _v4_global(_v4_scope, 'str')) else raw_xml
    root = _v4_global(_v4_scope, 'ET').fromstring(raw)
    fetched_iso = _v4_global(_v4_scope, 'isoformat_utc')(fetched_at)
    fetched_dt = _v4_global(_v4_scope, '_coerce_datetime')(fetched_at)
    rows: list[dict[str, Any]] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        raw_title = _v4_global(_v4_scope, '_element_text')(item, "title")
        source_name, source_page = _v4_global(_v4_scope, '_source_of')(item)
        title = _v4_global(_v4_scope, 'strip_title_source')(raw_title, source_name)
        description = _v4_global(_v4_scope, 're').sub(r"<[^>]+>", " ", _v4_global(_v4_scope, '_element_text')(item, "description"))
        description = _v4_global(_v4_scope, 'clean_text')(description)
        if not title or _v4_global(_v4_scope, '_is_negative')(title, description, source_name):
            continue
        published_dt = _v4_global(_v4_scope, 'parse_rss_date')(_v4_global(_v4_scope, '_element_text')(item, "pubDate"))
        published_iso = _v4_global(_v4_scope, 'isoformat_utc')(published_dt) if published_dt else ""
        tier = _v4_global(_v4_scope, 'source_tier')(source_name, title)
        age_score = 0
        if published_dt:
            age_hours = _v4_global(_v4_scope, 'max')((fetched_dt - published_dt).total_seconds() / 3600, 0)
            age_score = 12 if age_hours <= 6 else 8 if age_hours <= 24 else 3 if age_hours <= 72 else 0
        link = _v4_global(_v4_scope, 'clean_text')(_v4_global(_v4_scope, '_element_text')(item, "link"))
        score = _v4_global(_v4_scope, '_tier_score')(tier) + age_score
        stable_id = _v4_global(_v4_scope, 'hashlib').sha256(
            f"{_v4_global(_v4_scope, 'normalize_key')(title)}|{source_name}|{published_iso}".encode("utf-8")
        ).hexdigest()[:16]
        rows.append(
            {
                "id": stable_id,
                "title": title,
                "evidence_title_en": title,
                "summary": description or title,
                "published_at": published_iso,
                "fetched_at": fetched_iso,
                "source": source_name or source_page or "Google News RSS",
                "source_name": source_name or source_page or "Google News RSS",
                "source_tier": tier,
                "source_url": source_page or link or source_url,
                "source_page_url": source_page,
                "discovery_url": link or source_url,
                "url": link,
                "original_url": "",
                "original_url_status": "PENDING_RESOLUTION",
                "subscription_id": subscription_id,
                "theme_bucket": theme_bucket,
                "external_event_class": _v4_global(_v4_scope, '_event_class')(title, description),
                "score": score,
                "cannot_confirm": ["GOOGLE_NEWS_RSS_DISCOVERY_ONLY"],
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
        if _v4_global(_v4_scope, 'len')(rows) >= _v4_global(_v4_scope, 'max')(0, limit):
            break
    return rows
