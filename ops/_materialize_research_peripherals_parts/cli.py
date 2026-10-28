"""ops.materialize_research_peripherals: cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __detect_named_entities_body(_v4_scope, /, text):
    normalized = _v4_global(_v4_scope, '_clean_markup')(text)
    seen: list[str] = []
    suffix_pattern = r"([\u4e00-\u9fa5A-Za-z]{2,10}(?:科技|电子|通信|股份|精密|光电|新材|材料|药业|能源|集团|证券|电力))"
    known_names = ("英伟达", "康宁", "海力士", "三星", "美光", "联芸科技", "江波龙", "兆易创新", "兴福电子", "华泰电子")
    for name in known_names:
        if name in normalized and name not in seen:
            seen.append(name)
    for match in _v4_global(_v4_scope, 're').finditer(suffix_pattern, normalized):
        name = _v4_global(_v4_scope, '_normalize_entity_name')(match.group(1))
        if _v4_global(_v4_scope, '_is_noise_entity')(name):
            continue
        if name not in seen and name not in {"核心要点", "文字观点"} and "等硬科技" not in name:
            if name.startswith(("在", "及", "和")):
                continue
            seen.append(name)
    return seen[:8]


def __map_ah_relevance_body(_v4_scope, /, title, description, subscription_id):
    haystack = f"{title} {description}".lower()
    mapped: list[str] = []
    for needle, labels in _v4_global(_v4_scope, 'AH_KEYWORDS'):
        if needle in haystack:
            for label in labels:
                if label not in mapped:
                    mapped.append(label)
    if subscription_id in {
        "authority_china_hk",
        "china_hk_stocks",
        "china_tech_ai_semis",
        "hk_ipo_new_economy",
    } and "A/H股票复核" not in mapped:
        mapped.append("A/H股票复核")
    return mapped[:8]


def _dedupe_and_rank_body(_v4_scope, /, rows, max_items, *, fetched_at, lookback_days, rejected_reasons):
    best_by_key: dict[str, dict[str, Any]] = {}
    for source_row in rows:
        row = _v4_global(_v4_scope, 'dict')(source_row)
        reasons = _v4_global(_v4_scope, '_row_admission_reasons')(
            row,
            fetched_at=fetched_at,
            lookback_days=lookback_days,
        )
        if reasons:
            if rejected_reasons is not None:
                rejected_reasons.extend(reasons)
            continue
        if not _v4_global(_v4_scope, '_is_high_signal')(row):
            continue
        key = _v4_global(_v4_scope, 'normalize_key')(_v4_global(_v4_scope, 'str')(row.get("title") or ""))
        if not key:
            continue
        previous = best_by_key.get(key)
        if previous is None or _v4_global(_v4_scope, 'int')(row.get("score") or 0) > _v4_global(_v4_scope, 'int')(previous.get("score") or 0):
            best_by_key[key] = row
    return _v4_global(_v4_scope, 'sorted')(
        best_by_key.values(),
        key=lambda row: (
            _v4_global(_v4_scope, 'int')(row.get("score") or 0),
            _v4_global(_v4_scope, 'str')(row.get("published_at") or row.get("fetched_at") or ""),
            _v4_global(_v4_scope, 'str')(row.get("id") or ""),
        ),
        reverse=True,
    )[: _v4_global(_v4_scope, 'max')(0, max_items)]


def _parse_args_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description=_v4_global(_v4_scope, '__doc__'))
    parser.add_argument("--data-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument(
        "--source",
        choices=("external_finance", "ai_news", "both"),
        default="both",
    )
    parser.add_argument("--ai-url", default=_v4_global(_v4_scope, 'AIHOT_URL'))
    parser.add_argument("--lookback-days", type=_v4_global(_v4_scope, 'int'), default=2)
    parser.add_argument("--limit-per-feed", type=_v4_global(_v4_scope, 'int'), default=10)
    parser.add_argument("--max-items", type=_v4_global(_v4_scope, 'int'), default=36)
    parser.add_argument("--limit", type=_v4_global(_v4_scope, 'int'), default=30)
    parser.add_argument("--timeout", type=_v4_global(_v4_scope, 'int'), default=30)
    parser.add_argument(
        "--translate-existing",
        action="store_true",
        help="Translate current exact-date artifacts without refetching sources.",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Use validated exact-date artifacts and fetch only missing sources.",
    )
    return parser.parse_args(_v4_global(_v4_scope, 'list')(argv) if argv is not None else None)


def _main_body(_v4_scope, /, argv):
    args = _v4_global(_v4_scope, 'parse_args')(argv)
    outputs: list[dict[str, Any]] = []
    selected_sources = (
        ("external_finance", "ai_news")
        if args.source == "both"
        else (args.source,)
    )
    if args.reuse_existing:
        store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(args.data_root)
        for source in selected_sources:
            payload = store.read_exact(args.trade_date, source)
            if _v4_global(_v4_scope, 'reuse_existing_payload')(payload):
                outputs.append(
                    {
                        "payload": payload,
                        "payload_path": f"research/peripherals/{args.trade_date}/{source}.json",
                        "receipt_path": f"receipts/research/peripherals/{args.trade_date}/{source}.json",
                        "reused": True,
                    }
                )
        selected_sources = _v4_global(_v4_scope, 'tuple')(
            source
            for source in selected_sources
            if not _v4_global(_v4_scope, 'any')(item["payload"]["source"] == source for item in outputs)
        )
    if args.translate_existing:
        for source in selected_sources:
            outputs.append(
                _v4_global(_v4_scope, 'materialize_existing_translations')(
                    data_root=args.data_root,
                    trade_date=args.trade_date,
                    source=source,
                    timeout=args.timeout,
                )
            )
    elif "external_finance" in selected_sources:
        outputs.append(
            _v4_global(_v4_scope, 'materialize_external_finance')(
                data_root=args.data_root,
                trade_date=args.trade_date,
                lookback_days=args.lookback_days,
                limit_per_feed=args.limit_per_feed,
                max_items=args.max_items,
                timeout=args.timeout,
            )
        )
    if not args.translate_existing and "ai_news" in selected_sources:
        outputs.append(
            _v4_global(_v4_scope, 'materialize_ai_news')(
                data_root=args.data_root,
                trade_date=args.trade_date,
                source_url=args.ai_url,
                timeout=args.timeout,
                limit=args.limit,
            )
        )
    _v4_global(_v4_scope, 'print')(
        _v4_global(_v4_scope, 'json').dumps(
            {
                "trade_date": args.trade_date,
                "source": args.source,
                "outputs": [
                    {
                        "source": item["payload"]["source"],
                        "status": item["payload"]["status"],
                        "item_count": item["payload"]["item_count"],
                        "payload_path": item["payload_path"],
                        "receipt_path": item["receipt_path"],
                    }
                    for item in outputs
                ],
            },
            ensure_ascii=False,
        )
    )
    safe_status = _v4_global(_v4_scope, 'all')(
        item["payload"]["status"] in {"READY", "READY_EMPTY"}
        and "ZH_TRANSLATION_INCOMPLETE" not in item["payload"]["cannot_confirm"]
        for item in outputs
    )
    return 0 if safe_status else 2
