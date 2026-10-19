"""ops.us_market_digest: market_snapshot (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global
from .futu_boards import empty_futu_board_snapshot, validate_futu_board_snapshot


def __empty_market_snapshot_body(_v4_scope, /, us_session_date, *, capture_phase, captured_at, reasons, source_response_sha256, provider_receipt, futu_board_snapshot=None, universe_contract=None):
    captured_iso = _v4_global(_v4_scope, 'isoformat_utc')(_v4_global(_v4_scope, '_parse_capture_timestamp')(captured_at))
    checked_contract = _v4_global(_v4_scope, 'validate_us_universe_contract')(
        universe_contract if universe_contract is not None else _v4_global(_v4_scope, '_configured_us_universe_contract')()
    )
    unique_symbols = checked_contract["symbols"]
    rows = []
    for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP'):
        symbols = _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"])
        rows.append({
            "label": mapping["label"],
            "group": mapping["group"],
            "mapping_type": mapping["mapping_type"],
            "proxy_symbols": symbols,
            "available_symbols": [],
            "missing_symbols": symbols,
            "requested_symbol_count": _v4_global(_v4_scope, 'len')(symbols),
            "available_symbol_count": 0,
            "coverage": {"available": 0, "requested": _v4_global(_v4_scope, 'len')(symbols)},
            "coverage_pct": 0.0,
            "change_pct": None,
            "pct_change": None,
            "direction": "CANNOT_CONFIRM",
            "status": "CANNOT_CONFIRM",
            "quote_session_dates": [],
            "quote_session_times": [],
            "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(reasons)),
        })
    result: dict[str, Any] = {
        "schema_version": _v4_global(_v4_scope, 'MARKET_SNAPSHOT_SCHEMA_VERSION'),
        "status": "CANNOT_CONFIRM",
        "source": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider_url": _v4_global(_v4_scope, 'TENCENT_QUOTE_ENDPOINT'),
        "source_response_sha256": source_response_sha256,
        "capture_phase": _v4_global(_v4_scope, 'str')(capture_phase),
        "capture_session_date": _v4_global(_v4_scope, '_date')(us_session_date),
        "captured_at": captured_iso,
        "generated_at": captured_iso,
        "mapping_version": _v4_global(_v4_scope, 'MARKET_MAPPING_VERSION'),
        "universe_contract": checked_contract,
        "requested_symbol_count": _v4_global(_v4_scope, 'len')(unique_symbols),
        "available_symbol_count": 0,
        "provider_session_dates": [],
        "provider_session_times": [],
        "quotes": [],
        "rows": rows,
        "futu_board_snapshot": validate_futu_board_snapshot(futu_board_snapshot, expected_session_date=us_session_date)
        if futu_board_snapshot is not None
        else empty_futu_board_snapshot(us_session_date, "FUTU_BOARD_CAPTURE_NOT_ATTEMPTED"),
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(reasons)),
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if provider_receipt is not None:
        result["provider_receipt"] = _v4_global(_v4_scope, 'dict')(provider_receipt)
    return result


def _build_us_market_snapshot_body(_v4_scope, /, us_session_date, *, capture_phase, captured_at, fetch_quotes, fetch_quote, transport, timeout, fetch_futu_boards=None, universe_contract=None):
    """Capture the configured US universe inside the existing 24-theme producer."""
    if fetch_quotes is not None and fetch_quote is not None:
        raise _v4_global(_v4_scope, 'ValueError')("provide only one quote fetch seam")
    fetcher = fetch_quotes or fetch_quote
    session_date = _v4_global(_v4_scope, '_date')(us_session_date)
    phase = _v4_global(_v4_scope, '_phase')(capture_phase)
    captured_iso = _v4_global(_v4_scope, 'isoformat_utc')(_v4_global(_v4_scope, '_parse_capture_timestamp')(captured_at))
    mappings = _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP')
    checked_contract = _v4_global(_v4_scope, 'validate_us_universe_contract')(
        universe_contract if universe_contract is not None else _v4_global(_v4_scope, '_configured_us_universe_contract')()
    )
    # This helper is the quote boundary itself.  Only the scheduled close
    # capture may request provider prices; every other phase gets a complete
    # fail-closed surface without invoking a fetch seam.
    if phase != "POST_CLOSE":
        return _v4_global(_v4_scope, '_empty_market_snapshot')(
            session_date,
            capture_phase=phase,
            captured_at=captured_iso,
            reasons=[
                "MARKET_SNAPSHOT_NOT_DUE_PRE_OPEN"
                if phase == "PRE_OPEN"
                else "MARKET_SNAPSHOT_NOT_DUE_POST_CLOSE"
            ],
            universe_contract=checked_contract,
        )
    if fetch_futu_boards is None:
        futu_board_snapshot = empty_futu_board_snapshot(session_date, "FUTU_BOARD_CAPTURE_NOT_REQUESTED")
    else:
        try:
            futu_board_snapshot = validate_futu_board_snapshot(
                fetch_futu_boards(session_date), expected_session_date=session_date
            )
        except Exception as error:
            futu_board_snapshot = empty_futu_board_snapshot(
                session_date, f"FUTU_BOARD_CAPTURE_FAILED:{type(error).__name__}"
            )
    symbols = _v4_global(_v4_scope, 'list')(checked_contract["symbols"])
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, '_SAFE_US_SYMBOL').fullmatch(symbol) for symbol in symbols):
        raise _v4_global(_v4_scope, 'ValueError')("invalid fixed US proxy symbol")
    from v4.manager_workbench.inputs.us_mapping_close_scope import (
        configured_request_scope, build_scope_observations,
    )
    supplemental_request = configured_request_scope()
    request_symbols = sorted(set(symbols) | set(supplemental_request["symbols"])) if supplemental_request else symbols
    quote_url = f"{_v4_global(_v4_scope, 'TENCENT_QUOTE_ENDPOINT')}{','.join(f'us{symbol}' for symbol in request_symbols)}"
    reasons: set[str] = _v4_global(_v4_scope, 'set')()
    provider_receipt: Mapping[str, Any] | None = None
    source_response_sha256 = ""
    try:
        if fetcher is not None:
            if fetcher is _v4_global(_v4_scope, 'fetch_url'):
                active_transport = transport or _v4_global(_v4_scope, 'ProxyAwareHTTPTransport')(timeout=timeout)
                response = active_transport.fetch(quote_url, timeout=timeout)
            else:
                response = fetcher(quote_url, timeout)
        else:
            active_transport = transport or _v4_global(_v4_scope, 'ProxyAwareHTTPTransport')(timeout=timeout)
            response = active_transport.fetch(quote_url, timeout=timeout)
        if _v4_global(_v4_scope, 'isinstance')(response, _v4_global(_v4_scope, 'FetchResult')):
            raw: bytes | str | Mapping[str, Any] = response.body
            provider_receipt = response.receipt
        elif _v4_global(_v4_scope, 'isinstance')(response, (_v4_global(_v4_scope, 'bytes'), _v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Mapping'))):
            raw = response
        else:
            raise _v4_global(_v4_scope, 'TypeError')("quote fetch seam returned unsupported body")
        source_response_sha256 = _v4_global(_v4_scope, '_response_sha256')(raw)
        parsed, parse_reasons = _v4_global(_v4_scope, 'parse_tencent_quotes_diagnostic')(
            raw,
            request_symbols,
            expected_session_date=session_date,
        )
        supplemental = build_scope_observations(
            supplemental_request, parsed, parse_reasons, source_session=session_date,
            captured_at=captured_iso, source_response_sha256=source_response_sha256,
            raw_response=raw,
        ) if supplemental_request else None
        # Supplement failures never change the established 48-symbol surface.
        parsed = {symbol: row for symbol, row in parsed.items() if symbol in symbols}
        parse_reasons = {symbol: reason for symbol, reason in parse_reasons.items() if symbol in symbols}
        reasons.update(parse_reasons.values())
        # Keep the aggregate reason deterministic and attributable to the
        # provider record.  The unqualified reason remains for compatibility
        # with existing receipts, while the qualified form identifies the
        # exact symbol that prevented a complete close snapshot.
        reasons.update(
            f"{reason}:{symbol}"
            for symbol, reason in _v4_global(_v4_scope, 'sorted')(parse_reasons.items())
        )
    except (_v4_global(_v4_scope, 'TransportError'), _v4_global(_v4_scope, 'TimeoutError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')) as error:
        if _v4_global(_v4_scope, 'isinstance')(error, _v4_global(_v4_scope, 'TransportError')):
            provider_receipt = error.receipt
        reasons.add(f"US_MARKET_QUOTE_FETCH_FAILED:{_v4_global(_v4_scope, 'type')(error).__name__}")
        return _v4_global(_v4_scope, '_empty_market_snapshot')(
            session_date,
            capture_phase=phase,
            captured_at=captured_iso,
            reasons=_v4_global(_v4_scope, 'sorted')(reasons),
            source_response_sha256=source_response_sha256,
            provider_receipt=provider_receipt,
            futu_board_snapshot=futu_board_snapshot,
            universe_contract=checked_contract,
        )

    if not parsed:
        reasons.add("US_MARKET_QUOTE_RESPONSE_UNPARSED")
    records_by_symbol = parsed
    provider_dates = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(record["session_date"])
        for record in records_by_symbol.values()
        if record.get("session_date")
    })
    provider_times = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(record["session_time"])
        for record in records_by_symbol.values()
        if record.get("session_time")
    })
    if _v4_global(_v4_scope, 'len')(provider_dates) > 1:
        reasons.add("QUOTE_SESSION_DATE_MIXED")
    if _v4_global(_v4_scope, 'len')(provider_times) > 1:
        reasons.add("QUOTE_SESSION_TIME_MIXED")
    rows: list[dict[str, Any]] = []
    quotes = [
        {
            "symbol": symbol,
            "exchange": "US",
            "session_date": record.get("session_date") or "",
            "session_time": record.get("session_time") or "",
            "last": record.get("last"),
            "previous_close": record.get("previous_close"),
            "change_pct": _v4_global(_v4_scope, 'float')(record["pct_change"]),
            "provider": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        }
        for symbol, record in _v4_global(_v4_scope, 'sorted')(records_by_symbol.items())
    ]
    for mapping in mappings:
        proxy_symbols = _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"])
        available = [symbol for symbol in proxy_symbols if symbol in records_by_symbol]
        missing = [symbol for symbol in proxy_symbols if symbol not in records_by_symbol]
        changes = [_v4_global(_v4_scope, 'float')(records_by_symbol[symbol]["pct_change"]) for symbol in available]
        pct_change = _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, 'sum')(changes) / _v4_global(_v4_scope, 'len')(changes), 6) if changes else None
        direction = (
            "UP" if pct_change is not None and pct_change > 0
            else "DOWN" if pct_change is not None and pct_change < 0
            else "FLAT" if pct_change is not None
            else "CANNOT_CONFIRM"
        )
        # Per-symbol arithmetic/date failures belong to their theme row.  Do
        # not smear one bad provider record across otherwise valid rows.
        row_reasons = {
            reason
            for reason in reasons
            if reason not in _v4_global(_v4_scope, '_QUOTE_HARD_FAILURES') and ":" not in reason
        }
        row_reasons.update(
            parse_reasons[symbol]
            for symbol in proxy_symbols
            if symbol in parse_reasons
        )
        if missing:
            row_reasons.add("QUOTE_SYMBOL_MISSING")
            reasons.update(f"QUOTE_SYMBOL_MISSING:{symbol}" for symbol in missing)
        row_dates = _v4_global(_v4_scope, 'sorted')({
            _v4_global(_v4_scope, 'str')(records_by_symbol[symbol]["session_date"])
            for symbol in available
            if records_by_symbol[symbol].get("session_date")
        })
        row_times = _v4_global(_v4_scope, 'sorted')({
            _v4_global(_v4_scope, 'str')(records_by_symbol[symbol]["session_time"])
            for symbol in available
            if records_by_symbol[symbol].get("session_time")
        })
        if _v4_global(_v4_scope, 'len')(available) == _v4_global(_v4_scope, 'len')(proxy_symbols) and not missing and not row_dates:
            row_reasons.add("QUOTE_SESSION_DATE_MISSING")
        if _v4_global(_v4_scope, 'len')(available) == _v4_global(_v4_scope, 'len')(proxy_symbols) and not missing and not row_times:
            row_reasons.add("QUOTE_SESSION_TIME_MISSING")
        row_status = (
            "CANNOT_CONFIRM" if not available or row_reasons & _v4_global(_v4_scope, '_QUOTE_HARD_FAILURES')
            else "READY" if not missing and row_dates and row_times and _v4_global(_v4_scope, 'len')(row_dates) == 1 and _v4_global(_v4_scope, 'len')(row_times) == 1
            else "PARTIAL"
        )
        rows.append({
            "label": mapping["label"],
            "group": mapping["group"],
            "mapping_type": mapping["mapping_type"],
            "proxy_symbols": proxy_symbols,
            "available_symbols": available,
            "missing_symbols": missing,
            "requested_symbol_count": _v4_global(_v4_scope, 'len')(proxy_symbols),
            "available_symbol_count": _v4_global(_v4_scope, 'len')(available),
            "coverage": {"available": _v4_global(_v4_scope, 'len')(available), "requested": _v4_global(_v4_scope, 'len')(proxy_symbols)},
            "coverage_pct": _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, 'len')(available) / _v4_global(_v4_scope, 'len')(proxy_symbols) * 100, 3),
            "change_pct": pct_change,
            "pct_change": pct_change,
            "direction": direction,
            "status": row_status,
            "quote_session_dates": row_dates,
            "quote_session_times": row_times,
            "cannot_confirm": _v4_global(_v4_scope, 'sorted')(row_reasons),
        })
    available_count = _v4_global(_v4_scope, 'len')(records_by_symbol)
    all_rows_ready = _v4_global(_v4_scope, 'all')(row["status"] == "READY" for row in rows)
    if not provider_dates:
        reasons.add("QUOTE_SESSION_DATE_MISSING")
    if not provider_times:
        reasons.add("QUOTE_SESSION_TIME_MISSING")
    if not all_rows_ready or not available_count or reasons:
        # A close snapshot is complete only when all 24 rows are READY.  Keep
        # every row (including confirmed rows) for diagnosis, but never let a
        # partial provider response masquerade as an actionable snapshot.
        reasons.add("MARKET_SNAPSHOT_INCOMPLETE")
    status = "READY" if all_rows_ready and available_count and not reasons else "CANNOT_CONFIRM"
    result = {
        "schema_version": _v4_global(_v4_scope, 'MARKET_SNAPSHOT_SCHEMA_VERSION'),
        "status": status,
        "source": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider_url": _v4_global(_v4_scope, 'TENCENT_QUOTE_ENDPOINT'),
        "quote_url": quote_url,
        "source_response_sha256": source_response_sha256,
        "capture_phase": phase,
        "capture_session_date": session_date,
        "captured_at": captured_iso,
        "generated_at": captured_iso,
        "mapping_version": _v4_global(_v4_scope, 'MARKET_MAPPING_VERSION'),
        "universe_contract": checked_contract,
        "requested_symbol_count": _v4_global(_v4_scope, 'len')(symbols),
        "available_symbol_count": available_count,
        "provider_session_dates": provider_dates,
        "provider_session_times": provider_times,
        "quotes": quotes,
        "rows": rows,
        "futu_board_snapshot": futu_board_snapshot,
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(reasons),
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if provider_receipt is not None:
        result["provider_receipt"] = _v4_global(_v4_scope, 'dict')(provider_receipt)
    if supplemental is not None:
        result["scheduled_quote_scope"] = supplemental
    return result
