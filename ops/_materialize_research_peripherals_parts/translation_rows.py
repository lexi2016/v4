"""ops.materialize_research_peripherals: translation_rows (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __v3_local_chinese_title_body(_v4_scope, /, row, mappings):
    title = _v4_global(_v4_scope, 'clean_text')(row.get("title"))
    lowered = title.lower()
    source = _v4_global(_v4_scope, 'clean_text')(row.get("source_name") or row.get("source"))
    source_cn = _v4_global(_v4_scope, 'SOURCE_CN_LABELS').get(source, source or "外媒")
    theme_bucket = _v4_global(_v4_scope, 'clean_text')(row.get("theme_bucket"))
    theme = _v4_global(_v4_scope, 'THEME_LABELS').get(theme_bucket, theme_bucket or "外部财经")
    event_class = _v4_global(_v4_scope, 'clean_text')(row.get("external_event_class"))
    if "zhongji innolight" in lowered:
        return "中际旭创据称考虑赴港上市，AI光模块/CPO链需要重点复核"
    if "kingboard laminates" in lowered:
        return "建滔积层板受AI服务器材料重估带动，复核PCB/覆铜板链"
    if "deepseek" in lowered:
        return "DeepSeek相关动态升温，复核中国AI应用和算力链外溢"
    if "humanoid robots" in lowered:
        return "人形机器人产业动态更新，复核执行器、传感器和控制器链"
    if "hang seng index" in lowered:
        return "恒生指数与利率预期变化，复核港股流动性和中国资产风险偏好"
    if event_class == "IPO_LISTING" and mappings:
        return f"海外媒体提示IPO线索，复核{'、'.join(mappings[:3])}"
    if event_class == "EARNINGS" and mappings:
        return f"海外媒体提示业绩线索，复核{'、'.join(mappings[:3])}"
    if event_class == "POLICY_REGULATION" and mappings:
        return f"海外媒体提示政策监管线索，复核{'、'.join(mappings[:3])}"
    if mappings:
        return f"{source_cn}提示{theme}线索，复核{'、'.join(mappings[:3])}"
    return f"{source_cn}提示{theme}线索，保留研究观察"


def __localize_external_row_body(_v4_scope, /, source_row):
    row = _v4_global(_v4_scope, 'dict')(source_row)
    mappings = _v4_global(_v4_scope, '_map_ah_relevance')(
        _v4_global(_v4_scope, 'clean_text')(row.get("title")),
        _v4_global(_v4_scope, 'clean_text')(row.get("summary")),
        _v4_global(_v4_scope, 'clean_text')(row.get("subscription_id")),
    )
    row["ah_mapping"] = mappings
    row["theme_label"] = _v4_global(_v4_scope, 'THEME_LABELS').get(
        _v4_global(_v4_scope, 'clean_text')(row.get("theme_bucket")), _v4_global(_v4_scope, 'clean_text')(row.get("theme_bucket"))
    )
    row["title_zh"] = _v4_global(_v4_scope, '_v3_local_chinese_title')(row, mappings)
    row["summary_zh"] = _v4_global(_v4_scope, '_v3_local_summary')(row, mappings)
    row["translation_status"] = "READY"
    row["translation_source"] = "V3_LOCAL_RULES"
    row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
        item
        for item in _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or [])
        if item != "ZH_TRANSLATION_FAILED"
    )
    return row


def __resolve_original_row_body(_v4_scope, /, source_row, *, resolver, timeout):
    row = _v4_global(_v4_scope, 'dict')(source_row)
    discovery_url = _v4_global(_v4_scope, 'clean_text')(
        row.get("discovery_url") or row.get("url") or row.get("source_url")
    )
    row["discovery_url"] = discovery_url
    try:
        resolved = _v4_global(_v4_scope, 'str')(resolver(discovery_url, timeout)).strip()
        parsed = _v4_global(_v4_scope, 'urllib').parse.urlsplit(resolved)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname == "news.google.com"
            or not _v4_global(_v4_scope, '_is_article_url')(resolved)
        ):
            raise _v4_global(_v4_scope, 'ValueError')("publisher URL is not verified")
        row["original_url"] = resolved
        row["original_url_status"] = "VERIFIED_PUBLISHER_URL"
        row["url"] = resolved
        row["source_url"] = resolved
        row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            item
            for item in _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or [])
            if item != "ORIGINAL_URL_UNRESOLVED"
        )
    except (_v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'TransportError'), _v4_global(_v4_scope, 'urllib').error.URLError, _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
        row["original_url"] = ""
        row["original_url_status"] = "CANNOT_CONFIRM"
        row["url"] = ""
        row["source_url"] = _v4_global(_v4_scope, 'clean_text')(row.get("source_page_url"))
        row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or []) | {"ORIGINAL_URL_UNRESOLVED"}
        )
    return row


def __resolve_original_rows_body(_v4_scope, /, rows, *, resolver, timeout, max_workers):
    if not rows:
        return []
    workers = _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'int')(max_workers), _v4_global(_v4_scope, 'len')(rows)))
    with _v4_global(_v4_scope, 'ThreadPoolExecutor')(max_workers=workers) as executor:
        return _v4_global(_v4_scope, 'list')(
            executor.map(
                lambda row: _v4_global(_v4_scope, '_resolve_original_row')(
                    row, resolver=resolver, timeout=timeout
                ),
                rows,
            )
        )


def _google_translate_zh_body(_v4_scope, /, value, timeout):
    """Translate public-source text to Simplified Chinese via a read-only endpoint."""
    source_text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if not source_text:
        return ""
    query = _v4_global(_v4_scope, 'urllib').parse.urlencode(
        {
            "client": "gtx",
            "sl": "auto",
            "tl": "zh-CN",
            "dt": "t",
            "q": source_text,
        }
    )
    raw = _v4_global(_v4_scope, 'fetch_url')(f"{_v4_global(_v4_scope, 'GOOGLE_TRANSLATE')}?{query}", timeout=timeout)
    payload = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    segments = payload[0] if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'list')) and payload else []
    translated = "".join(
        _v4_global(_v4_scope, 'str')(segment[0])
        for segment in segments
        if _v4_global(_v4_scope, 'isinstance')(segment, _v4_global(_v4_scope, 'list')) and segment and segment[0]
    ).strip()
    if not translated:
        raise _v4_global(_v4_scope, 'ValueError')("translation endpoint returned no text")
    return translated


def _mymemory_translate_zh_body(_v4_scope, /, value, timeout, *, opener):
    """Translate one public headline through MyMemory's read-only endpoint."""
    source_text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if not source_text:
        return ""
    query = _v4_global(_v4_scope, 'urllib').parse.urlencode(
        {"q": source_text[:500], "langpair": "en|zh-CN"}
    )
    request = _v4_global(_v4_scope, 'urllib').request.Request(
        f"{_v4_global(_v4_scope, 'MYMEMORY_TRANSLATE')}?{query}", headers={"User-Agent": _v4_global(_v4_scope, 'USER_AGENT')}
    )
    with opener(request, timeout=timeout) as response:
        payload = _v4_global(_v4_scope, 'json').loads(response.read().decode("utf-8"))
    translated = _v4_global(_v4_scope, 'clean_text')(
        (payload.get("responseData") or {}).get("translatedText")
        if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping'))
        else ""
    )
    if (
        not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'int')(payload.get("responseStatus") or 0) != 200
        or not translated
        or not _v4_global(_v4_scope, '_CJK').search(translated)
    ):
        raise _v4_global(_v4_scope, 'ValueError')("MyMemory returned no verified Chinese translation")
    return translated


def __translate_row_body(_v4_scope, /, source_row, *, translate_text, timeout):
    row = _v4_global(_v4_scope, 'dict')(source_row)
    if _v4_global(_v4_scope, 'clean_text')(row.get("subscription_id")):
        localized = _v4_global(_v4_scope, '_localize_external_row')(row)
        title = _v4_global(_v4_scope, 'clean_text')(localized.get("title"))
        try:
            translated_title = _v4_global(_v4_scope, '_normalize_chinese_finance_translation')(
                _v4_global(_v4_scope, '_call_translator')(translate_text, title, timeout)
            )
            if not translated_title or not _v4_global(_v4_scope, '_CJK').search(translated_title):
                raise _v4_global(_v4_scope, 'ValueError')("event title translation is not Chinese")
            if not _v4_global(_v4_scope, '_validate_finance_translation')(title, translated_title):
                raise _v4_global(_v4_scope, 'ValueError')("event title translation amount or currency mismatch")
            localized["title_zh"] = _v4_global(_v4_scope, 'clean_text')(translated_title)
            localized["summary_zh"] = (
                f"事件：{localized['title_zh']}。"
                + _v4_global(_v4_scope, '_v3_local_summary')(localized, _v4_global(_v4_scope, 'list')(localized.get("ah_mapping") or []))
            )
            localized["translation_status"] = "READY"
            localized["translation_source"] = "PUBLIC_MACHINE_TRANSLATION"
            localized["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
                item
                for item in _v4_global(_v4_scope, 'set')(localized.get("cannot_confirm") or [])
                if item != "ZH_TRANSLATION_FAILED"
            )
        except (_v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'TransportError'), _v4_global(_v4_scope, 'urllib').error.URLError, _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
            localized.pop("title_zh", None)
            localized.pop("summary_zh", None)
            localized["translation_status"] = "CANNOT_CONFIRM"
            localized["translation_source"] = "V3_LOCAL_RULES_FALLBACK"
            localized["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
                _v4_global(_v4_scope, 'set')(localized.get("cannot_confirm") or [])
                | {
                    "ZH_TRANSLATION_AMOUNT_MISMATCH"
                    if "amount or currency mismatch" in _v4_global(_v4_scope, 'str')(error)
                    else "ZH_TRANSLATION_FAILED"
                }
            )
        return localized
    title = _v4_global(_v4_scope, 'clean_text')(row.get("title"))
    summary = _v4_global(_v4_scope, 'clean_text')(row.get("summary"))
    row["original_url"] = _v4_global(_v4_scope, '_original_url')(row)
    existing_title_zh = _v4_global(_v4_scope, 'clean_text')(row.get("title_zh"))
    existing_summary_zh = _v4_global(_v4_scope, 'clean_text')(row.get("summary_zh"))
    needs_title = _v4_global(_v4_scope, 'bool')(title and not existing_title_zh and not _v4_global(_v4_scope, '_CJK').search(title))
    needs_summary = _v4_global(_v4_scope, 'bool')(summary and not existing_summary_zh and not _v4_global(_v4_scope, '_CJK').search(summary))
    if not needs_title:
        row["title_zh"] = existing_title_zh or title
    if not needs_summary:
        row["summary_zh"] = existing_summary_zh or summary
    if not needs_title and not needs_summary:
        if (
            existing_title_zh
            and not _v4_global(_v4_scope, '_validate_finance_translation')(title, existing_title_zh)
        ) or (
            existing_summary_zh
            and not _v4_global(_v4_scope, '_validate_finance_translation')(summary, existing_summary_zh)
        ):
            row["translation_status"] = "CANNOT_CONFIRM"
            row["translation_source"] = ""
            row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
                _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or []) | {"ZH_TRANSLATION_AMOUNT_MISMATCH"}
            )
            return row
        row["translation_status"] = (
            "READY" if existing_title_zh or existing_summary_zh else "NOT_REQUIRED"
        )
        if existing_title_zh or existing_summary_zh:
            row.setdefault("translation_source", "EXISTING_VERIFIED_TRANSLATION")
        return row

    fields: list[str] = []
    values: list[str] = []
    if needs_title:
        fields.append("title_zh")
        values.append(title)
    if needs_summary:
        fields.append("summary_zh")
        values.append(summary)
    try:
        translated = _v4_global(_v4_scope, '_call_translator')(translate_text, "\n".join(values), timeout)
        pieces = [part.strip() for part in translated.split("\n", _v4_global(_v4_scope, 'len')(values) - 1)]
        if _v4_global(_v4_scope, 'len')(pieces) != _v4_global(_v4_scope, 'len')(values) or _v4_global(_v4_scope, 'any')(not part for part in pieces):
            raise _v4_global(_v4_scope, 'ValueError')("translation field boundary was not preserved")
        for field, value in _v4_global(_v4_scope, 'zip')(fields, pieces, strict=True):
            source_value = title if field == "title_zh" else summary
            if not _v4_global(_v4_scope, '_validate_finance_translation')(source_value, value):
                raise _v4_global(_v4_scope, 'ValueError')(f"{field} translation amount or currency mismatch")
            row[field] = value
        row["translation_status"] = "READY"
        row["translation_source"] = "GOOGLE_TRANSLATE_PUBLIC_READ_ONLY"
        row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            item
            for item in _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or [])
            if item != "ZH_TRANSLATION_FAILED"
        )
    except (_v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'TransportError'), _v4_global(_v4_scope, 'urllib').error.URLError, _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        row["translation_status"] = "CANNOT_CONFIRM"
        row["translation_source"] = ""
        row["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or [])
            | {
                "ZH_TRANSLATION_AMOUNT_MISMATCH"
                if "amount or currency mismatch" in _v4_global(_v4_scope, 'str')(error)
                else "ZH_TRANSLATION_FAILED"
            }
        )
    return row


def __translate_rows_body(_v4_scope, /, rows, *, translate_text, timeout, max_workers):
    if not rows:
        return []
    workers = _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'int')(max_workers), _v4_global(_v4_scope, 'len')(rows)))
    with _v4_global(_v4_scope, 'ThreadPoolExecutor')(max_workers=workers) as executor:
        return _v4_global(_v4_scope, 'list')(
            executor.map(
                lambda row: _v4_global(_v4_scope, '_translate_row')(
                    row,
                    translate_text=translate_text,
                    timeout=timeout,
                ),
                rows,
            )
        )


def _translate_existing_payload_body(_v4_scope, /, payload, *, translate_text, timeout, max_workers):
    """Enrich an existing exact-date payload without refetching source rows."""
    translated = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(payload))
    source = _v4_global(_v4_scope, 'str')(translated.get("source") or "")
    if source == "external_finance":
        details = _v4_global(_v4_scope, '_translate_rows')(
            translated.get("details") or [],
            translate_text=translate_text,
            timeout=timeout,
            max_workers=max_workers,
        )
        translated["details"] = details
        translated["overview"] = _v4_global(_v4_scope, 'overview_from_details')(details)
        rows = details
    elif source == "ai_news":
        items = _v4_global(_v4_scope, '_translate_rows')(
            translated.get("items") or [],
            translate_text=translate_text,
            timeout=timeout,
            max_workers=max_workers,
        )
        translated["items"] = items
        rows = items
    else:
        raise _v4_global(_v4_scope, 'ValueError')("unsupported research peripheral source")
    gaps = _v4_global(_v4_scope, 'set')(translated.get("cannot_confirm") or [])
    gaps.discard("ZH_TRANSLATION_INCOMPLETE")
    if _v4_global(_v4_scope, 'any')(row.get("translation_status") == "CANNOT_CONFIRM" for row in rows):
        gaps.add("ZH_TRANSLATION_INCOMPLETE")
    translated["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(gaps)
    return translated


def _materialize_existing_translations_body(_v4_scope, /, *, data_root, trade_date, source, translate_text, timeout):
    store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
    payload = store.read_exact(trade_date, source)
    if payload is None:
        raise _v4_global(_v4_scope, 'ValueError')(f"research peripheral payload is missing: {source}")
    translated = _v4_global(_v4_scope, 'translate_existing_payload')(
        payload,
        translate_text=translate_text,
        timeout=timeout,
    )
    result = store.replace(
        translated,
        expected_sha256=_v4_global(_v4_scope, '_sha256')(payload),
        reason="ADD_ZH_TRANSLATION_AND_ORIGINAL_URL",
    )
    return {"payload": translated, **result}
