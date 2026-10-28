"""ops.materialize_research_peripherals: ai_feeds (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _AIHotParser_handle_starttag_body(_v4_scope, /, self, tag, attrs_list):
    attrs = {key: value or "" for key, value in attrs_list}
    classes = _v4_global(_v4_scope, 'set')((attrs.get("class") or "").split())
    if tag == "div" and "timeline-item" in classes:
        self.pending = {
            "time": "",
            "selected": "timeline-item-selected" in classes,
        }
    if self.pending is not None and "timeline-time" in classes:
        self.capture_stack.append((tag, "time"))
    if tag == "article" and self.pending is not None:
        self.current = self.pending
        self.pending = None
        self.current.setdefault("tags", [])
    if self.current is None:
        return
    if tag == "div" and attrs.get("data-item-id"):
        self.current["item_id"] = attrs["data-item-id"]
    elif "timeline-source" in classes:
        self.capture_stack.append((tag, "source"))
    elif "uc-handle" in classes:
        self.capture_stack.append((tag, "handle"))
    elif "timeline-score" in classes:
        self.capture_stack.append((tag, "score"))
    elif tag == "a" and "timeline-title" in classes:
        self.current["url"] = attrs.get("href", "")
        self.capture_stack.append((tag, "title"))
    elif tag == "p" and "timeline-summary" in classes:
        self.capture_stack.append((tag, "summary"))
    elif "tag-static" in classes:
        self.capture_stack.append((tag, "tag"))
    elif "timeline-reason" in classes:
        self.capture_stack.append((tag, "reason"))


def _AIHotParser_handle_data_body(_v4_scope, /, self, data):
    if not self.capture_stack:
        return
    field = self.capture_stack[-1][1]
    target = self.current if self.current is not None else self.pending
    if target is None:
        return
    if field == "tag":
        target.setdefault("_tag_buf", "")
        target["_tag_buf"] += data
        return
    target.setdefault("_text", {})
    target["_text"].setdefault(field, "")
    target["_text"][field] += data


def _AIHotParser_handle_endtag_body(_v4_scope, /, self, tag):
    if self.capture_stack and self.capture_stack[-1][0] == tag:
        _, field = self.capture_stack.pop()
        target = self.current if self.current is not None else self.pending
        if target is not None and field == "tag":
            value = _v4_global(_v4_scope, 'clean_text')(target.pop("_tag_buf", ""))
            if value:
                target.setdefault("tags", []).append(value)
    if tag != "article" or self.current is None:
        return
    text_map = self.current.pop("_text", {})
    for key, value in text_map.items():
        self.current[key] = _v4_global(_v4_scope, 'clean_text')(value)
    score_text = _v4_global(_v4_scope, 'str')(self.current.get("score") or "").strip()
    self.current["score"] = _v4_global(_v4_scope, 'int')(score_text) if score_text.isdigit() else None
    if self.current.get("title") or self.current.get("summary"):
        self.items.append(self.current)
    self.current = None


def _parse_aihot_items_body(_v4_scope, /, page_html, *, fetched_at, source_url, limit):
    parser = _v4_global(_v4_scope, 'AIHotParser')()
    parser.feed(page_html)
    fetched_iso = _v4_global(_v4_scope, 'isoformat_utc')(fetched_at)
    items: list[dict[str, Any]] = []
    for raw in parser.items[: _v4_global(_v4_scope, 'max')(0, limit)]:
        item = _v4_global(_v4_scope, 'dict')(raw)
        item["source_url"] = source_url
        item["original_url"] = _v4_global(_v4_scope, '_original_url')(item)
        item["fetched_at"] = fetched_iso
        item["cannot_confirm"] = ["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"]
        item["recommendation_status"] = "RESEARCH_ONLY"
        item.setdefault("source_name", item.get("source") or item.get("handle") or "AIHot")
        item.setdefault(
            "item_id",
            _v4_global(_v4_scope, 'hashlib').sha256(
                f"{item.get('title','')}|{item.get('url','')}|{item.get('time','')}".encode("utf-8")
            ).hexdigest()[:16],
        )
        items.append(item)
    return items


def _build_ai_items_body(_v4_scope, /, raw_items, *, fetched_at, source_url):
    """Build the V3-equivalent unified AI records and retain only score Top8.

    The function deliberately consumes already-materialized public rows.  It
    never imports or reads the legacy V3/assistant tree; all transformations
    are deterministic local equivalents of the former ``build_ai_items``
    helpers.
    """
    fallback_fetched = _v4_global(_v4_scope, 'isoformat_utc')(fetched_at)
    records: list[dict[str, Any]] = []
    for raw_row in raw_items:
        if not _v4_global(_v4_scope, 'isinstance')(raw_row, _v4_global(_v4_scope, 'Mapping')):
            continue
        raw = _v4_global(_v4_scope, 'dict')(raw_row)
        title = _v4_global(_v4_scope, 'clean_text')(raw.get("title")) or "未命名 AI 动态"
        summary = _v4_global(_v4_scope, 'clean_text')(raw.get("summary"))
        reason = _v4_global(_v4_scope, 'clean_text')(raw.get("reason"))
        tags = [_v4_global(_v4_scope, 'clean_text')(tag) for tag in (raw.get("tags") or []) if _v4_global(_v4_scope, 'clean_text')(tag)]
        text = f"{title}\n{summary}\n{' '.join(tags)}"
        entities = _v4_global(_v4_scope, '_detect_named_entities')(text)
        symbols = []
        for match in _v4_global(_v4_scope, 're').finditer(
            r"([\u4e00-\u9fa5A-Za-z]{2,12})[（(](\d{6}\.(?:SH|SZ|BJ|HK))[）)]",
            text,
        ):
            symbol = f"{match.group(1)}({match.group(2)})"
            if symbol not in symbols:
                symbols.append(symbol)
        symbols = symbols[:8]
        article_url = _v4_global(_v4_scope, '_absolute_http_url')(
            raw.get("original_url") or raw.get("url"),
            raw.get("source_url") or source_url,
        )
        page_url = _v4_global(_v4_scope, '_absolute_http_url')(raw.get("source_url"), source_url)
        source_link = article_url or page_url
        source_name = _v4_global(_v4_scope, 'clean_text')(raw.get("source") or raw.get("source_name")) or "AIHOT"
        fetched_display = _v4_global(_v4_scope, '_format_cst_time')(raw.get("fetched_at") or fallback_fetched)
        item: dict[str, Any] = {
            "id": f"ai-{raw.get('item_id') or _v4_global(_v4_scope, 'len')(records) + 1}",
            "title": title,
            "summary": summary,
            "source_type": "AI",
            "source_name": source_name,
            "fetched_at": fetched_display,
            "published_at": raw.get("time"),
            "symbols": symbols,
            "named_entities": entities,
            "stock_focus": _v4_global(_v4_scope, '_detect_stock_focus')(text, symbols, entities),
            "hk_connect_mapping": [],
            "theme": _v4_global(_v4_scope, '_infer_theme')(text),
            "theme_candidates": _v4_global(_v4_scope, '_top_theme_candidates')(text),
            "evidence_level": "L1",
            "event_fact": _v4_global(_v4_scope, '_short_text')(summary or reason or title, 220),
            "investment_implication": _v4_global(_v4_scope, '_infer_implication')(text),
            "impact_chain": _v4_global(_v4_scope, '_infer_impact_chain')(text),
            "target_price": None,
            "rating": None,
            "earnings_forecast": None,
            "valuation_assumption": None,
            "catalysts": _v4_global(_v4_scope, '_infer_catalysts')(text),
            "risks": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, '_AI_RISKS')),
            "cross_validation": [],
            "source_url": source_link,
            "original_url": source_link,
            "score": raw.get("score"),
            "tags": tags,
            "freshness_label": "本轮抓取",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(raw.get("cannot_confirm") or [])),
        }
        for field in ("title_zh", "summary_zh", "translation_status", "translation_source"):
            if field in raw:
                item[field] = raw[field]
        item["priority_score"] = _v4_global(_v4_scope, '_priority_score')(item)
        records.append(item)
    return _v4_global(_v4_scope, 'sorted')(records, key=lambda item: _v4_global(_v4_scope, '_score_value')(item.get("score")), reverse=True)[:_v4_global(_v4_scope, '_AI_MAX_ITEMS')]


def _build_ai_news_payload_body(_v4_scope, /, trade_date, *, page_html, fetched_at, source_url, limit, translate_text, translation_timeout, feed_receipts):
    selected_date = _v4_global(_v4_scope, '_date')(trade_date)
    fetched_iso = _v4_global(_v4_scope, 'isoformat_utc')(fetched_at)
    raw_items = _v4_global(_v4_scope, 'parse_aihot_items')(
        page_html,
        fetched_at=fetched_iso,
        source_url=source_url,
        limit=limit,
    )
    cannot_confirm = ["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"]
    if translate_text is not None:
        raw_items = _v4_global(_v4_scope, '_translate_rows')(
            raw_items,
            translate_text=translate_text,
            timeout=translation_timeout,
        )
        if _v4_global(_v4_scope, 'any')(row.get("translation_status") == "CANNOT_CONFIRM" for row in raw_items):
            cannot_confirm.append("ZH_TRANSLATION_INCOMPLETE")
    items = _v4_global(_v4_scope, 'build_ai_items')(
        raw_items,
        fetched_at=fetched_iso,
        source_url=source_url,
    )
    status = "READY" if items else "READY_EMPTY"
    return _v4_global(_v4_scope, '_base_payload')(
        trade_date=selected_date,
        source="ai_news",
        status=status,
        source_url=source_url,
        fetched_at=fetched_iso,
        raw_item_count=_v4_global(_v4_scope, 'len')(raw_items),
        item_count=_v4_global(_v4_scope, 'len')(items),
        overview=[],
        details=[],
        items=items,
        cannot_confirm=cannot_confirm,
        feed_receipts=feed_receipts,
    )
