"""Explicit, immutable quote expansion through the existing US market owner."""
from __future__ import annotations

from ._namespace import read_global as _v4_global
from .futu_boards import empty_futu_board_snapshot


_SCOPE_SHA256 = "6d163c286d90d1dfd00b18fa134d3f4ec308d9d2efdd51e5cbba800f3d61acf8"
_SCOPE_SCHEMA = "v4.manual_us_quote_scope.v1"
_CAPTURE_MODE = "MANUAL_QUOTE_SCOPE_EXPANSION"
_CANARY_MODE = "MANUAL_QUOTE_SCOPE_CANARY"
_CANARY_EXTRA_SYMBOLS = ("AAGIY", "MDLZ", "SHEL", "KIE", "XLU")


def _canonical_digest(_v4_scope, value):
    encoded = _v4_global(_v4_scope, 'json').dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return _v4_global(_v4_scope, 'hashlib').sha256(encoded).hexdigest()


def _validated_scope(_v4_scope, scope):
    if not _v4_global(_v4_scope, 'isinstance')(scope, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_OBJECT_REQUIRED")
    unhashed = {key: value for key, value in scope.items() if key != "scope_sha256"}
    if (scope.get("schema_version") != _SCOPE_SCHEMA
            or scope.get("scope_sha256") != _SCOPE_SHA256
            or _canonical_digest(_v4_scope, unhashed) != _SCOPE_SHA256):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_IDENTITY_INVALID")
    symbols = scope.get("symbols")
    if (not _v4_global(_v4_scope, 'isinstance')(symbols, _v4_global(_v4_scope, 'list'))
            or len(symbols) != 547 or symbols != sorted(set(symbols))
            or any(not isinstance(value, str) or not _v4_global(_v4_scope, '_SAFE_US_SYMBOL').fullmatch(value)
                   for value in symbols)
            or scope.get("symbol_counts", {}).get("requested_total") != len(symbols)):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_SYMBOL_SET_INVALID")
    return list(symbols)


def _build_manual_quote_scope_snapshot_body(
    _v4_scope, /, session_date, *, scope, captured_at, fetch_quotes, fetch_quote,
    transport, timeout, universe_contract=None, symbols_override=None,
    effective_scope_sha256=None, capture_mode=_CAPTURE_MODE,
):
    """Capture exact-scope quotes, isolating provider failures per symbol."""
    from contracts.us_equity_calendar import latest_completed_session, session

    full_symbols = _validated_scope(_v4_scope, scope)
    symbols = full_symbols if symbols_override is None else list(symbols_override)
    if (not symbols or symbols != sorted(set(symbols))
            or not set(symbols).issubset(full_symbols)
            or any(not _v4_global(_v4_scope, '_SAFE_US_SYMBOL').fullmatch(value) for value in symbols)):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_SELECTED_SYMBOLS_INVALID")
    active_scope_sha = effective_scope_sha256 or _SCOPE_SHA256
    if not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-f]{64}", active_scope_sha):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_ACTIVE_HASH_INVALID")
    if fetch_quotes is not None and fetch_quote is not None:
        raise _v4_global(_v4_scope, 'ValueError')("provide only one quote fetch seam")
    selected_date = _v4_global(_v4_scope, '_date')(session_date)
    captured = _v4_global(_v4_scope, '_parse_capture_timestamp')(captured_at)
    latest = latest_completed_session(captured)
    if latest.session_date != selected_date:
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SESSION_NOT_LATEST_COMPLETED")
    official = session(selected_date)
    if official.close_at is None:
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SESSION_HAS_NO_OFFICIAL_CLOSE")

    base_contract = _v4_global(_v4_scope, '_configured_us_universe_contract')()
    base_symbols = set(base_contract["symbols"])
    extras = sorted(set(symbols) - base_symbols)
    checked_contract = _v4_global(_v4_scope, 'validate_us_universe_contract')(
        _v4_global(_v4_scope, 'build_us_universe_contract')(extras)
    ) if universe_contract is None else _v4_global(_v4_scope, 'validate_us_universe_contract')(universe_contract)
    if set(checked_contract.get("symbols", [])) != set(symbols):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_UNIVERSE_CONTRACT_MISMATCH")

    quote_url = f"{_v4_global(_v4_scope, 'TENCENT_QUOTE_ENDPOINT')}{','.join(f'us{symbol}' for symbol in symbols)}"
    fetcher = fetch_quotes or fetch_quote
    provider_receipt = None
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
    except (_v4_global(_v4_scope, 'TransportError'), _v4_global(_v4_scope, 'TimeoutError'),
            _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'),
            _v4_global(_v4_scope, 'TypeError')) as error:
        raise _v4_global(_v4_scope, 'ValueError')(
            f"US_MANUAL_QUOTE_SCOPE_FETCH_FAILED:{type(error).__name__}"
        ) from error
    if _v4_global(_v4_scope, 'isinstance')(response, _v4_global(_v4_scope, 'FetchResult')):
        raw = response.body
        provider_receipt = response.receipt
    elif _v4_global(_v4_scope, 'isinstance')(response, (_v4_global(_v4_scope, 'bytes'),
                                                         _v4_global(_v4_scope, 'str'),
                                                         _v4_global(_v4_scope, 'Mapping'))):
        raw = response
    else:
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_RESPONSE_INVALID")
    response_sha = _v4_global(_v4_scope, '_response_sha256')(raw)
    parsed, parse_reasons = _v4_global(_v4_scope, 'parse_tencent_quotes_diagnostic')(
        raw, symbols, expected_session_date=selected_date
    )

    valid_quotes = {}
    failures = dict(parse_reasons)
    session_day = _v4_global(_v4_scope, 'datetime').strptime(selected_date, "%Y%m%d").date()
    for symbol in symbols:
        record = parsed.get(symbol)
        if record is None:
            failures.setdefault(symbol, "QUOTE_SYMBOL_MISSING")
            continue
        if record.get("session_date") != selected_date:
            failures[symbol] = "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"
            continue
        try:
            observed = _v4_global(_v4_scope, 'datetime').combine(
                session_day,
                _v4_global(_v4_scope, 'datetime').strptime(record.get("session_time") or "", "%H:%M:%S").time(),
                tzinfo=_v4_global(_v4_scope, 'US_TZ'),
            )
        except (TypeError, ValueError):
            failures[symbol] = "QUOTE_SESSION_TIMESTAMP_INVALID"
            continue
        if observed < official.close_at:
            failures[symbol] = "QUOTE_PROVIDER_TIMESTAMP_BEFORE_OFFICIAL_CLOSE"
            continue
        if observed > captured:
            failures[symbol] = "QUOTE_PROVIDER_TIMESTAMP_AFTER_CAPTURE"
            continue
        valid_quotes[symbol] = {
            "symbol": symbol,
            "exchange": "US",
            "session_date": selected_date,
            "session_time": record["session_time"],
            "last": record["last"],
            "previous_close": record["previous_close"],
            "change_pct": record["pct_change"],
            "provider": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        }

    failures = {symbol: failures[symbol] for symbol in symbols if symbol not in valid_quotes}
    quote_symbols = set(valid_quotes)
    rows = []
    for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP'):
        proxy_symbols = list(mapping["proxy_symbols"])
        available = [symbol for symbol in proxy_symbols if symbol in quote_symbols]
        missing = [symbol for symbol in proxy_symbols if symbol not in quote_symbols]
        changes = [float(valid_quotes[symbol]["change_pct"]) for symbol in available]
        change = round(sum(changes) / len(changes), 6) if changes else None
        row_status = "CANNOT_CONFIRM" if not available else "READY" if not missing else "PARTIAL"
        rows.append({
            "label": mapping["label"], "group": mapping["group"],
            "mapping_type": mapping["mapping_type"], "proxy_symbols": proxy_symbols,
            "available_symbols": available, "missing_symbols": missing,
            "requested_symbol_count": len(proxy_symbols), "available_symbol_count": len(available),
            "coverage": {"available": len(available), "requested": len(proxy_symbols)},
            "coverage_pct": round(len(available) / len(proxy_symbols) * 100, 3),
            "change_pct": change, "pct_change": change,
            "direction": "CANNOT_CONFIRM" if change is None else "UP" if change > 0 else "DOWN" if change < 0 else "FLAT",
            "status": row_status,
            "quote_session_dates": sorted({valid_quotes[symbol]["session_date"] for symbol in available}),
            "quote_session_times": sorted({valid_quotes[symbol]["session_time"] for symbol in available}),
            "cannot_confirm": sorted({failures[symbol] for symbol in missing if symbol in failures}),
        })
    status = "READY" if len(valid_quotes) == len(symbols) else "PARTIAL" if valid_quotes else "CANNOT_CONFIRM"
    reasons = [] if status == "READY" else (
        ["MANUAL_QUOTE_SCOPE_PARTIAL"] if status == "PARTIAL" else ["MANUAL_QUOTE_SCOPE_NO_VALID_QUOTES"]
    )
    reasons.extend(f"{reason}:{symbol}" for symbol, reason in sorted(failures.items()))
    snapshot = {
        "schema_version": _v4_global(_v4_scope, 'MARKET_SNAPSHOT_SCHEMA_VERSION'),
        "status": status,
        "source": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider": _v4_global(_v4_scope, 'TENCENT_PROVIDER'),
        "provider_url": _v4_global(_v4_scope, 'TENCENT_QUOTE_ENDPOINT'),
        "quote_url": quote_url,
        "source_response_sha256": response_sha,
        "capture_phase": _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'),
        "capture_mode": capture_mode,
        "capture_session_date": selected_date,
        "captured_at": _v4_global(_v4_scope, 'isoformat_utc')(captured),
        "generated_at": _v4_global(_v4_scope, 'isoformat_utc')(captured),
        "mapping_version": _v4_global(_v4_scope, 'MARKET_MAPPING_VERSION'),
        "universe_contract": checked_contract,
        "requested_symbol_count": len(symbols),
        "available_symbol_count": len(valid_quotes),
        "provider_session_dates": [selected_date] if valid_quotes else [],
        "provider_session_times": sorted({quote["session_time"] for quote in valid_quotes.values()}),
        "quotes": list(valid_quotes.values()),
        "rows": rows,
        "quote_failures": failures,
        "manual_quote_scope": {
            "schema_version": _SCOPE_SCHEMA,
            "scope_sha256": active_scope_sha,
            "parent_scope_sha256": _SCOPE_SHA256,
            "scope_mode": "CANARY" if capture_mode == _CANARY_MODE else "FULL",
            "symbols_sha256": _canonical_digest(_v4_scope, symbols),
            "symbols": symbols,
            "requested_symbol_count": len(symbols),
            "available_symbol_count": len(valid_quotes),
            "missing_symbols": sorted(failures),
            "quote_failures": failures,
            "captured_at": _v4_global(_v4_scope, 'isoformat_utc')(captured),
        },
        "futu_board_snapshot": empty_futu_board_snapshot(
            selected_date, "FUTU_BOARD_CAPTURE_NOT_REQUESTED"),
        "cannot_confirm": sorted(set(reasons)),
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if provider_receipt is not None:
        snapshot["provider_receipt"] = dict(provider_receipt)
    return snapshot


def _build_manual_quote_scope_payload_body(
    _v4_scope, /, trade_date, *, session_date, scope, now, fetch_quotes, fetch_quote,
    transport, timeout,
):
    from contracts.us_equity_calendar import latest_completed_session

    selected_trade_date = _v4_global(_v4_scope, '_date')(trade_date)
    captured = _v4_global(_v4_scope, '_capture_now')(now)
    selected_session = _v4_global(_v4_scope, '_date')(session_date)
    if latest_completed_session(captured).session_date != selected_session:
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SESSION_NOT_LATEST_COMPLETED")
    symbols = _validated_scope(_v4_scope, scope)
    fetched_iso = _v4_global(_v4_scope, 'isoformat_utc')(captured)
    payload = _v4_global(_v4_scope, 'build_external_finance_payload')(
        selected_trade_date, fetched_at=fetched_iso, subscriptions=(), timeout=timeout
    )
    metadata = _v4_global(_v4_scope, 'build_capture_metadata')(
        selected_session,
        _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'),
        captured_at=fetched_iso,
        capture_id=("manual-us-quote:" + selected_session + ":" + _SCOPE_SHA256[:12] + ":" + fetched_iso),
        run_id=("manual-us-quote-scope:" + selected_session + ":" + _SCOPE_SHA256[:12]),
        capture_origin=_v4_global(_v4_scope, 'HISTORICAL_BACKFILL'),
        original_time_capture=False,
    )
    metadata["capture_mode"] = _CAPTURE_MODE
    annotated = _v4_global(_v4_scope, '_annotate_payload')(payload, metadata)
    snapshot = _v4_global(_v4_scope, 'build_us_market_snapshot')(
        selected_session,
        capture_phase=_v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'),
        captured_at=fetched_iso,
        fetch_quotes=fetch_quotes,
        fetch_quote=fetch_quote,
        transport=transport,
        timeout=timeout,
        manual_quote_scope_sha256=_SCOPE_SHA256,
        manual_quote_scope=scope,
    )
    annotated["market_snapshot"] = snapshot
    annotated["market_snapshot_status"] = snapshot["status"]
    annotated["cannot_confirm"] = sorted(
        set(annotated.get("cannot_confirm") or []) | set(snapshot.get("cannot_confirm") or [])
    )
    return annotated


def _build_manual_quote_scope_canary_body(
    _v4_scope, /, *, session_date, scope, now=None, fetch_quotes=None,
    fetch_quote=None, transport=None, timeout=20,
):
    """Read-only owner canary over the existing 48 plus five frozen additions."""
    from contracts.us_equity_calendar import latest_completed_session

    captured = _v4_global(_v4_scope, '_capture_now')(now)
    selected_session = _v4_global(_v4_scope, '_date')(session_date)
    if latest_completed_session(captured).session_date != selected_session:
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SESSION_NOT_LATEST_COMPLETED")
    full_symbols = _validated_scope(_v4_scope, scope)
    # Keep this canary fixed to the frozen 48-symbol V3 scope plus five names,
    # even when an unconfigured developer caller uses the 33-symbol fallback.
    base = _v4_global(_v4_scope, 'build_us_universe_contract')()["symbols"]
    selected = sorted(set(base) | set(_CANARY_EXTRA_SYMBOLS))
    if not set(selected).issubset(full_symbols):
        raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_CANARY_SCOPE_NOT_SUBSET")
    child_scope = {
        "schema_version": "v4.manual_us_quote_scope_canary.v1",
        "parent_scope_sha256": _SCOPE_SHA256,
        "symbols": selected,
    }
    child_sha = _canonical_digest(_v4_scope, child_scope)
    contract = _v4_global(_v4_scope, 'build_us_universe_contract')(
        sorted(set(selected) - set(base))
    )
    return _build_manual_quote_scope_snapshot_body(
        _v4_scope, selected_session, scope=scope,
        captured_at=_v4_global(_v4_scope, 'isoformat_utc')(captured),
        fetch_quotes=fetch_quotes, fetch_quote=fetch_quote,
        transport=transport, timeout=timeout, universe_contract=contract,
        symbols_override=selected, effective_scope_sha256=child_sha,
        capture_mode=_CANARY_MODE,
    )


def _materialize_manual_quote_scope_backfill_body(
    _v4_scope, /, *, data_root, trade_date, session_date, scope, now=None,
    fetch_quotes=None, fetch_quote=None, transport=None, timeout=20,
):
    """Publish the manual expansion once into the existing immutable backfill lane."""
    from infrastructure.interprocess_lock import owned_interprocess_lock

    if not _v4_global(_v4_scope, 'Path')(data_root).is_absolute():
        raise _v4_global(_v4_scope, 'ValueError')("US_OWNED_DATA_ROOT_MUST_BE_ABSOLUTE")
    selected_trade_date = _v4_global(_v4_scope, '_date')(trade_date)
    _validated_scope(_v4_scope, scope)
    store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
    relative = store._historical_backfill_relative(selected_trade_date, "external_finance")
    receipt_relative = store._historical_backfill_receipt_relative(selected_trade_date, "external_finance")
    with owned_interprocess_lock(
        _v4_global(_v4_scope, 'Path')(data_root) / ".locks" / f"us-manual-quote-scope-{selected_trade_date}.lock",
        timeout_seconds=300, timeout_message="US_MANUAL_QUOTE_SCOPE_OWNER_BUSY",
    ):
        manifest = store._manifest()
        if (relative in manifest or store._path(relative).exists() or store._path(receipt_relative).exists()):
            raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_BACKFILL_PATH_ALREADY_EXISTS")
        payload = _v4_global(_v4_scope, '_build_manual_quote_scope_payload')(
            selected_trade_date, session_date=session_date, scope=scope, now=now,
            fetch_quotes=fetch_quotes, fetch_quote=fetch_quote, transport=transport, timeout=timeout,
        )
        snapshot = payload.get("market_snapshot") or {}
        if not snapshot.get("available_symbol_count"):
            raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_QUOTE_SCOPE_NO_VALID_QUOTES")
        result = store.publish_historical_backfill(payload)
    return {"payload": payload, **result}


__all__ = [
    "_build_manual_quote_scope_canary_body",
    "_build_manual_quote_scope_payload_body",
    "_build_manual_quote_scope_snapshot_body",
    "_materialize_manual_quote_scope_backfill_body",
]
