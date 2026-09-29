"""ops.a_share_daily_sync: network_session (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __exception_chain_body(_v4_scope, /, error):
    """Capture the SDK wrapper and its original parser exception for receipts."""

    chain: list[dict[str, str]] = []
    current: BaseException | None = error
    seen: set[int] = _v4_global(_v4_scope, 'set')()
    while _v4_global(_v4_scope, 'isinstance')(current, _v4_global(_v4_scope, 'BaseException')) and _v4_global(_v4_scope, 'id')(current) not in seen:
        seen.add(_v4_global(_v4_scope, 'id')(current))
        current_type = _v4_global(_v4_scope, 'type')(current)
        chain.append(
            {
                "type": f"{current_type.__module__}.{current_type.__qualname__}",
                "message": _v4_global(_v4_scope, 'str')(current),
                "repr": _v4_global(_v4_scope, 'repr')(current),
            }
        )
        original = _v4_global(_v4_scope, 'getattr')(current, "original_exception", None)
        if _v4_global(_v4_scope, 'isinstance')(original, _v4_global(_v4_scope, 'BaseException')):
            current = original
            continue
        cause = current.__cause__
        if _v4_global(_v4_scope, 'isinstance')(cause, _v4_global(_v4_scope, 'BaseException')):
            current = cause
            continue
        context = current.__context__
        current = context if _v4_global(_v4_scope, 'isinstance')(context, _v4_global(_v4_scope, 'BaseException')) else None
    return chain


def __protocol_response_details_body(_v4_scope, /, error):
    """Return typed details only for an SDK-wrapped parser/framing failure."""

    if not _v4_global(_v4_scope, '_is_tdx_function_call_error')(error):
        return None
    original = _v4_global(_v4_scope, 'getattr')(error, "original_exception", None)
    original_type = _v4_global(_v4_scope, 'type')(original) if _v4_global(_v4_scope, 'isinstance')(original, _v4_global(_v4_scope, 'BaseException')) else None
    original_name = (
        (original_type.__module__, original_type.__name__)
        if original_type is not None
        else None
    )
    if not (
        _v4_global(_v4_scope, 'isinstance')(original, _v4_global(_v4_scope, '_PROTOCOL_PARSE_EXCEPTION_TYPES'))
        or original_name in _v4_global(_v4_scope, '_PROTOCOL_PARSE_EXCEPTION_NAMES')
    ):
        return None
    return {
        "error": _v4_global(_v4_scope, 'repr')(error),
        "exception_type": _v4_global(_v4_scope, 'type')(error).__name__,
        "original_exception_type": original_type.__name__ if original_type else None,
        "original_exception_module": original_type.__module__ if original_type else None,
        "original_exception": _v4_global(_v4_scope, 'repr')(original),
        "exception_chain": _v4_global(_v4_scope, '_exception_chain')(error),
    }


def __fetch_valid_target_bars_body(_v4_scope, /, api, target, target_date, previous_close, count, after_date, *, capture_response, field_violations, run_id, recorded_at):
    """Fetch one symbol and validate the provider response in wire order.

    Sorting here would turn a provider ordering defect into apparently valid
    evidence.  The response is therefore checked exactly as returned.  Once
    the exact target date is present, every bar after ``after_date`` through
    the target is handed to the append path so an incremental gap is not
    silently dropped.
    """

    bars = api.get_security_bars(9, target.market, target.code, 0, _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(count)))
    if capture_response is not None:
        capture_response(bars)
    if not bars:
        return [], _v4_global(_v4_scope, 'EMPTY_RESPONSE')
    normalized: list[dict[str, Any]] = []
    for response_index, raw in _v4_global(_v4_scope, 'enumerate')(bars):
        ok, reason = _v4_global(_v4_scope, 'valid_hq_bar')(raw)
        if not ok:
            return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:{reason}"
        normalized_bar = _v4_global(_v4_scope, 'dict')(raw)
        if "vol" not in normalized_bar and "volume" in normalized_bar:
            normalized_bar["vol"] = normalized_bar["volume"]
        field_violation = _v4_global(_v4_scope, '_provider_field_signature_violation')(
            normalized_bar,
            symbol=_v4_global(_v4_scope, 'str')(target.code),
            market=_v4_global(_v4_scope, 'int')(target.market),
            row_index=response_index,
            run_id=run_id,
            recorded_at=recorded_at,
        )
        if field_violation is not None:
            if field_violations is not None:
                field_violations.append(field_violation)
            return [], _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE')
        normalized.append(normalized_bar)
    dates = [_v4_global(_v4_scope, 'day_int')(bar) for bar in normalized]
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(dates)) != _v4_global(_v4_scope, 'len')(dates):
        return [], _v4_global(_v4_scope, 'DUPLICATE_DATE')
    if _v4_global(_v4_scope, 'any')(right < left for left, right in _v4_global(_v4_scope, 'zip')(dates, dates[1:])):
        return [], _v4_global(_v4_scope, 'NON_MONOTONIC_DATE')
    if _v4_global(_v4_scope, 'any')(date_value > target_date for date_value in dates):
        return [], _v4_global(_v4_scope, 'OUT_OF_SCOPE_AFTER_TARGET_DATE')
    exact = [bar for bar in normalized if _v4_global(_v4_scope, 'day_int')(bar) == target_date]
    if not exact:
        return [], _v4_global(_v4_scope, 'TARGET_DATE_MISSING')
    if after_date is not None and _v4_global(_v4_scope, 'int')(after_date) >= target_date:
        eligible = exact
    else:
        cutoff = _v4_global(_v4_scope, 'int')(after_date) if after_date is not None else 0
        eligible = [
            bar
            for bar in normalized
            if cutoff < _v4_global(_v4_scope, 'day_int')(bar) <= target_date
        ]
    prior = _v4_global(_v4_scope, 'float')(previous_close) if previous_close and previous_close > 0 else None
    for bar in eligible:
        close = _v4_global(_v4_scope, 'float')(bar["close"])
        if prior is not None:
            ratio = close / prior
            if ratio > _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO') or ratio < 1.0 / _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO'):
                return [], _v4_global(_v4_scope, 'CROSS_DAY_CLOSE_RATIO')
        prior = close
    # The caller still applies its own last-date filter before append.  This
    # return preserves every validated missing day while excluding future bars.
    return eligible, "OK"


def _connect_hq_body(_v4_scope, /, preferred_host, timeout):
    """Compatibility probe for callers that still use the v1 connection API.

    The production sync path uses :func:`run_sync` and its bounded host route.
    This narrow adapter preserves the existing test/diagnostic entry point
    while constructing the same strict ``raise_exception=True`` provider.
    """
    preferred = _v4_global(_v4_scope, 'str')(preferred_host).strip() if preferred_host else ""
    candidates = _v4_global(_v4_scope, '_runtime_host_candidates')(preferred or None)
    if not candidates:
        raise _v4_global(_v4_scope, 'RuntimeError')("No usable pytdx HQ host found")
    for ordinal, (host, port) in _v4_global(_v4_scope, 'enumerate')(candidates):
        api = _v4_global(_v4_scope, '_runtime_api_factory')(host, port)
        try:
            _v4_global(_v4_scope, '_connect_session')(api, host, port, timeout)
            probe = api.get_security_bars(9, 1, "600000", 0, 1)
            if probe:
                return api, {
                    "name": "preferred" if preferred and ordinal == 0 else "configured",
                    "host": host,
                    "port": _v4_global(_v4_scope, 'int')(port),
                    "probe_latest": probe[-1],
                }
        except _v4_global(_v4_scope, 'Exception'):
            _v4_global(_v4_scope, '_disconnect_session')(api)
    raise _v4_global(_v4_scope, 'RuntimeError')("No usable pytdx HQ host found")
