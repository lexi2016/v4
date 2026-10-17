"""domains.preselection_materializer: hourly_pool (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_hourly_research_pool_body(_v4_scope, /, data_root, trade_date, *, store):
    """Build the V3 research pool from verified V3.5 hourly archives.

    The time window is the frozen V3 window: D-1 08:30 to D 08:30 on a
    normal day and Friday 00:00 to Monday 09:00 for a Monday target.  Hourly
    archives are cumulative, so article identity is deduplicated before the
    per-stock recommendation count is calculated.
    """
    if store is None:
        from infrastructure.research_store import HourlyResearchStore

        store = HourlyResearchStore(_v4_global(_v4_scope, 'Path')(data_root))
    start, end = _v4_global(_v4_scope, '_research_window')(trade_date)
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    payloads: list[tuple[str, str, Mapping[str, Any]]] = []
    while cursor.date() <= end.date():
        archive_date = cursor.strftime("%Y%m%d")
        for slot in store.list_slots(archive_date, mode="LIVE"):
            payload = store.read_exact(archive_date, slot, mode="LIVE")
            if payload is None:
                raise _v4_global(_v4_scope, 'ValueError')("hourly research manifest points to missing payload")
            if _v4_global(_v4_scope, 'str')(payload.get("archive_date") or "") != archive_date:
                raise _v4_global(_v4_scope, 'ValueError')("hourly research archive-date mismatch")
            payloads.append((archive_date, slot, payload))
        cursor += _v4_global(_v4_scope, 'timedelta')(days=1)
    if not payloads:
        raise _v4_global(_v4_scope, 'FileNotFoundError')(f"hourly research window has no verified slots: {trade_date}")

    articles: dict[str, dict[str, Any]] = {}
    cannot_confirm: set[str] = {"RESEARCH_ONLY_NO_BUY_GATE"}
    for _archive_date, _slot, payload in payloads:
        for reason in payload.get("cannot_confirm") or []:
            if _v4_global(_v4_scope, 'str')(reason).strip():
                cannot_confirm.add(_v4_global(_v4_scope, 'str')(reason).strip())
        source_rows = payload.get("articles")
        if not _v4_global(_v4_scope, 'isinstance')(source_rows, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'ValueError')("hourly research articles are invalid")
        for raw in source_rows:
            if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("hourly research article is invalid")
            published_at = _v4_global(_v4_scope, '_parse_dt')(raw.get("published_at"))
            if published_at is None or not (start <= published_at < end):
                continue
            symbol = _v4_global(_v4_scope, '_a_symbol')(raw.get("stock_code"))
            if not symbol:
                continue
            article_id = _v4_global(_v4_scope, 'str')(raw.get("article_id") or "").strip()
            if not _v4_global(_v4_scope, 're').fullmatch(r"[A-Za-z0-9._:-]+", article_id):
                raise _v4_global(_v4_scope, 'ValueError')("hourly research article identity is invalid")
            normalized = _v4_global(_v4_scope, 'dict')(raw)
            normalized["symbol"] = symbol
            normalized["published_at_normalized"] = published_at.isoformat()
            articles.setdefault(article_id, normalized)

    grouped: dict[str, list[dict[str, Any]]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'list'))
    for article_id, article in articles.items():
        grouped[_v4_global(_v4_scope, 'str')(article["symbol"])].append({**article, "article_id": article_id})
    rows: list[dict[str, Any]] = []
    for symbol, stock_articles in grouped.items():
        stock_articles.sort(
            key=lambda item: (
                _v4_global(_v4_scope, 'str')(item["published_at_normalized"]),
                _v4_global(_v4_scope, 'str')(item["article_id"]),
            )
        )
        first = stock_articles[0]
        rows.append({
            "symbol": symbol,
            "code": symbol.removeprefix("A."),
            "market": "A",
            "pool_id": "a_share_research_recommendation_pool",
            "stock_name": _v4_global(_v4_scope, 'str')(first.get("stock_name") or symbol),
            "pool_score": _v4_global(_v4_scope, 'len')(stock_articles),
            "article_count": _v4_global(_v4_scope, 'len')(stock_articles),
            "signal_date": start.strftime("%Y%m%d"),
            "target_date": trade_date,
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "first_source_dt": _v4_global(_v4_scope, 'str')(first["published_at_normalized"]),
            "research_title": _v4_global(_v4_scope, 'str')(first.get("source_title") or ""),
            "entity_resolution_source": "hourly_research_stock_code",
            "source_article_ids": [
                _v4_global(_v4_scope, 'str')(item["article_id"]) for item in stock_articles
            ],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    rows.sort(
        key=lambda row: (
            -_v4_global(_v4_scope, 'int')(row["pool_score"]),
            _v4_global(_v4_scope, 'str')(row["first_source_dt"]),
            _v4_global(_v4_scope, 'str')(row["code"]),
        )
    )
    for index, row in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        row["pool_rank"] = index

    source_identity = [
        {
            "archive_date": archive_date,
            "slot": slot,
            "payload": payload,
        }
        for archive_date, slot, payload in payloads
    ]
    source_sha256 = _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(
            source_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    source_paths = "|".join(
        f"research/hourly/live/{archive_date}/{slot}.json"
        for archive_date, slot, _payload in payloads
    )
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date,
        pool_id="a_share_research_recommendation_pool",
        display_name="A股研报推荐股票池",
        market="A",
        status=(
            "RESEARCH_RECOMMENDATION_POOL_READY"
            if rows
            else "CANNOT_CONFIRM"
        ),
        producer_id="v3_5_hourly_research_window_v1",
        source_role="VERIFIED_HOURLY_RESEARCH",
        source_path=source_paths,
        source_sha256=source_sha256,
        rows=rows,
        cannot_confirm=_v4_global(_v4_scope, 'sorted')(cannot_confirm),
    )
