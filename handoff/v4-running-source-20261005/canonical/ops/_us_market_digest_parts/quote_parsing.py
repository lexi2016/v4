"""ops.us_market_digest: quote_parsing (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __normalize_tencent_compact_timestamp_body(_v4_scope, /, value):
    """Parse Tencent field-30's strict compact or dashed observation timestamp.

    Tencent's US quote response has no labels in its tilde-delimited fields.
    A timestamp is therefore trusted only when it is the complete value of the
    documented field 30. This helper deliberately does not scan arbitrary
    provider text for date/time fragments.
    """
    text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if _v4_global(_v4_scope, '_TENCENT_COMPACT_TIMESTAMP').fullmatch(text):
        timestamp_format = "%Y%m%d%H%M%S"
    elif _v4_global(_v4_scope, '_TENCENT_DASHED_TIMESTAMP').fullmatch(text):
        timestamp_format = "%Y-%m-%d %H:%M:%S"
    else:
        return None
    try:
        parsed = _v4_global(_v4_scope, 'datetime').strptime(text, timestamp_format)
    except _v4_global(_v4_scope, 'ValueError'):
        return None
    return parsed.strftime("%Y%m%d"), parsed.strftime("%H:%M:%S")


def __parse_tencent_record_diagnostic_body(_v4_scope, /, symbol, value):
    fields: list[Any] = []
    compact_timestamp_present = False
    explicit: Mapping[str, Any] | None = value if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) else None
    raw_tencent_string = _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str'))
    if explicit is not None:
        raw_fields = _v4_global(_v4_scope, '_mapping_value')(explicit, "fields", "data", "values")
        if _v4_global(_v4_scope, 'isinstance')(raw_fields, _v4_global(_v4_scope, 'Sequence')) and not _v4_global(_v4_scope, 'isinstance')(raw_fields, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'), _v4_global(_v4_scope, 'bytearray'))):
            fields = _v4_global(_v4_scope, 'list')(raw_fields)
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Sequence')) and not _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'), _v4_global(_v4_scope, 'bytearray'))):
        fields = _v4_global(_v4_scope, 'list')(value)
    else:
        fields = _v4_global(_v4_scope, 'str')(value).split("~")

    if explicit is not None:
        current = _v4_global(_v4_scope, '_quote_number')(_v4_global(_v4_scope, '_mapping_value')(explicit, "last", "price", "current", "close"))
        previous = _v4_global(_v4_scope, '_quote_number')(
            _v4_global(_v4_scope, '_mapping_value')(explicit, "prev_close", "previous_close", "pre_close", "previous")
        )
        pct_present, pct_value = _v4_global(_v4_scope, '_mapping_value_present')(
            explicit, "pct_change", "change_pct", "change_percent", "percent"
        )
        pct = _v4_global(_v4_scope, '_quote_number')(pct_value) if pct_present else None
        if pct_present and pct is None:
            return None, "QUOTE_PCT_CHANGE_INVALID"
        session_date = _v4_global(_v4_scope, '_normalize_quote_date')(
            _v4_global(_v4_scope, '_mapping_value')(explicit, "session_date", "quote_session_date", "date", "trading_date")
        )
        session_time = _v4_global(_v4_scope, '_normalize_quote_time')(
            _v4_global(_v4_scope, '_mapping_value')(explicit, "session_time", "quote_session_time", "time", "trading_time")
        )
    else:
        # The public Tencent US response places current and previous close at
        # fields 3 and 4.  Small array fixtures with symbol/current/previous
        # are accepted as well, which keeps the parser independently testable.
        current = _v4_global(_v4_scope, '_quote_number')(fields[3] if _v4_global(_v4_scope, 'len')(fields) > 4 else (fields[1] if _v4_global(_v4_scope, 'len')(fields) > 1 else None))
        previous = _v4_global(_v4_scope, '_quote_number')(fields[4] if _v4_global(_v4_scope, 'len')(fields) > 4 else (fields[2] if _v4_global(_v4_scope, 'len')(fields) > 2 else None))
        pct = None
        session_date = None
        session_time = None
        # Tencent's documented US string layout stores the observation
        # timestamp in field 30. A raw provider string must carry that field
        # explicitly in one of the two accepted complete formats; scanning
        # fields 5/6 or any other arbitrary text would allow unrelated numbers
        # to become the session identity. Sequence fixtures remain a narrow
        # parser seam and may expose labelled date/time values instead.
        if raw_tencent_string:
            if _v4_global(_v4_scope, 'len')(fields) <= _v4_global(_v4_scope, '_TENCENT_SOURCE_TIMESTAMP_FIELD'):
                return None, "QUOTE_SESSION_TIMESTAMP_MISSING"
            if not _v4_global(_v4_scope, 'str')(fields[_v4_global(_v4_scope, '_TENCENT_SOURCE_TIMESTAMP_FIELD')] or "").strip():
                return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
            compact_timestamp_present = True
            compact_timestamp = _v4_global(_v4_scope, '_normalize_tencent_compact_timestamp')(
                fields[_v4_global(_v4_scope, '_TENCENT_SOURCE_TIMESTAMP_FIELD')]
            )
            if compact_timestamp is None:
                return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
            session_date, session_time = compact_timestamp
        elif _v4_global(_v4_scope, 'len')(fields) > _v4_global(_v4_scope, '_TENCENT_SOURCE_TIMESTAMP_FIELD'):
            timestamp_value = fields[_v4_global(_v4_scope, '_TENCENT_SOURCE_TIMESTAMP_FIELD')]
            if _v4_global(_v4_scope, 'str')(timestamp_value or "").strip():
                compact_timestamp_present = True
                compact_timestamp = _v4_global(_v4_scope, '_normalize_tencent_compact_timestamp')(timestamp_value)
                if compact_timestamp is None:
                    return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
                session_date, session_time = compact_timestamp

    if current is None:
        return None, "QUOTE_LAST_INVALID"
    if previous is None:
        return None, "QUOTE_PREVIOUS_CLOSE_INVALID"
    if previous == 0:
        return None, "QUOTE_PREVIOUS_CLOSE_ZERO"
    derived_pct = (current - previous) / previous * 100
    if not _v4_global(_v4_scope, 'math').isfinite(derived_pct):
        return None, "QUOTE_RECORD_INVALID"
    if pct is not None:
        if not _v4_global(_v4_scope, 'math').isfinite(_v4_global(_v4_scope, 'float')(pct)):
            return None, "QUOTE_PCT_CHANGE_INVALID"
        if _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, 'float')(pct) - derived_pct) > _v4_global(_v4_scope, 'QUOTE_CHANGE_TOLERANCE'):
            return None, "QUOTE_PCT_CHANGE_MISMATCH"
    # The value computed from finite close prices is authoritative.  Provider
    # percent fields are an integrity check only and are never used as a
    # second arithmetic source.
    pct = derived_pct
    # Search all fields for provider session identity.  In Tencent's current
    # layout the date and time are late fields, while future layouts may expose
    # them under different positions.
    if session_date is None and not compact_timestamp_present:
        for field in fields:
            session_date = _v4_global(_v4_scope, '_normalize_quote_date')(field)
            if session_date:
                break
    if session_time is None and not compact_timestamp_present:
        for field in fields:
            session_time = _v4_global(_v4_scope, '_normalize_quote_time')(field)
            if session_time:
                break
    return {
        "symbol": symbol,
        "last": current,
        "previous_close": previous,
        "pct_change": _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, 'float')(pct), 6),
        "session_date": session_date,
        "session_time": session_time,
    }, None


def _parse_tencent_quotes_diagnostic_body(_v4_scope, /, raw, requested_symbols, *, expected_session_date):
    """Parse requested quotes and retain per-symbol fail-closed reasons."""
    requested = {
        symbol
        for symbol in (_v4_global(_v4_scope, 'str')(value or "").strip().upper() for value in requested_symbols)
        if _v4_global(_v4_scope, '_SAFE_US_SYMBOL').fullmatch(symbol)
    }
    if not requested:
        return {}, {}
    expected_date = _v4_global(_v4_scope, '_date')(expected_session_date) if expected_session_date else None
    records: dict[str, Any] = {}
    if _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
        root: Mapping[str, Any] = raw
        nested = root.get("data")
        if _v4_global(_v4_scope, 'isinstance')(nested, _v4_global(_v4_scope, 'Mapping')):
            root = nested
        for key, value in root.items():
            symbol = _v4_global(_v4_scope, '_normalize_quote_symbol')(key, requested)
            if symbol is not None:
                records[symbol] = value
    else:
        text = _v4_global(_v4_scope, '_decode_tencent_body')(raw)
        # Split on semicolons instead of using eval-like parsing.  Quoted
        # provider values do not contain semicolons in the documented format.
        for segment in text.split(";"):
            if '="' not in segment:
                continue
            key, value = segment.split('="', 1)
            symbol = _v4_global(_v4_scope, '_normalize_quote_symbol')(key, requested)
            if symbol is None:
                continue
            records[symbol] = value.rstrip('"')
    parsed: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    for symbol in _v4_global(_v4_scope, 'sorted')(records):
        record, reason = _v4_global(_v4_scope, '_parse_tencent_record_diagnostic')(symbol, records[symbol])
        if record is None:
            reasons[symbol] = reason or "QUOTE_RECORD_INVALID"
            continue
        session_date = record.get("session_date")
        if expected_date is not None and session_date != expected_date:
            reasons[symbol] = "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"
            continue
        parsed[symbol] = record
    return parsed, reasons


def _parse_tencent_quotes_body(_v4_scope, /, raw, requested_symbols):
    """Parse only requested US symbols from Tencent's safe text response.

    The parser accepts the provider's ``v_usSYMBOL="...~..."`` format and a
    mapping-shaped fixture for deterministic tests.  It never evaluates or
    executes provider text.
    """
    parsed, _ = _v4_global(_v4_scope, 'parse_tencent_quotes_diagnostic')(raw, requested_symbols)
    return parsed
