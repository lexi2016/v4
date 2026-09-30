"""infrastructure.research_peripheral_store: market_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_market_snapshot_body(_v4_scope, /, value):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot")

    required = {
        "schema_version",
        "status",
        "source",
        "provider",
        "source_response_sha256",
        "capture_phase",
        "capture_session_date",
        "captured_at",
        "generated_at",
        "mapping_version",
        "requested_symbol_count",
        "available_symbol_count",
        "provider_session_dates",
        "provider_session_times",
        "quotes",
        "rows",
        "cannot_confirm",
        "recommendation_status",
        "RESEARCH_ONLY",
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    }

    if not required.issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot fields")

    if value.get("schema_version") != _v4_global(_v4_scope, '_MARKET_SNAPSHOT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot schema")

    if value.get("mapping_version") != _v4_global(_v4_scope, '_MARKET_MAPPING_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot mapping version")

    if value.get("status") not in _v4_global(_v4_scope, '_MARKET_SNAPSHOT_STATUSES'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot status")

    for field in ("source", "provider", "mapping_version"):
        if not _v4_global(_v4_scope, 'isinstance')(value.get(field), _v4_global(_v4_scope, 'str')) or not value[field].strip():
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral market_snapshot {field}")

    response_sha = value.get("source_response_sha256")

    if not _v4_global(_v4_scope, 'isinstance')(response_sha, _v4_global(_v4_scope, 'str')) or (response_sha and not _v4_global(_v4_scope, '_SHA256').fullmatch(response_sha)):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot source response hash")

    if value.get("capture_phase") not in _v4_global(_v4_scope, '_CAPTURE_PHASES'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot capture_phase")

    try:
        capture_session_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(value.get("capture_session_date") or ""))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot capture_session_date") from error

    _v4_global(_v4_scope, '_aware_timestamp')(value.get("captured_at"), "market_snapshot.captured_at")

    _v4_global(_v4_scope, '_aware_timestamp')(value.get("generated_at"), "market_snapshot.generated_at")

    if "late" in value and _v4_global(_v4_scope, 'type')(value["late"]) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot late must be boolean")

    if "capture_mode" in value and (
        not _v4_global(_v4_scope, 'isinstance')(value["capture_mode"], _v4_global(_v4_scope, 'str'))
        or not value["capture_mode"].strip()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot capture_mode")

    if value.get("capture_mode") == _v4_global(_v4_scope, '_LATE_CAPTURE_MODE') and value.get("late") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("late market_snapshot mode requires late identity")

    for field in ("requested_symbol_count", "available_symbol_count"):
        count = value.get(field)
        if _v4_global(_v4_scope, 'type')(count) is not _v4_global(_v4_scope, 'int') or count < 0:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral market_snapshot {field}")

    _v4_global(_v4_scope, '_string_list')(value.get("provider_session_dates"), "market_snapshot.provider_session_dates")

    _v4_global(_v4_scope, '_string_list')(value.get("provider_session_times"), "market_snapshot.provider_session_times")

    for provider_date in value.get("provider_session_dates"):
        try:
            normalized_provider_date = _v4_global(_v4_scope, '_date')(provider_date)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot provider session date") from error
        if normalized_provider_date != capture_session_date:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot provider session date mismatch")

    for provider_time in value.get("provider_session_times"):
        if not _v4_global(_v4_scope, '_US_SESSION_TIME').fullmatch(provider_time):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot provider session time")

    _v4_global(_v4_scope, '_string_list')(value.get("cannot_confirm"), "market_snapshot.cannot_confirm")

    quotes = value.get("quotes")

    if not _v4_global(_v4_scope, 'isinstance')(quotes, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quotes")
    quote_symbols = _b04_validate_market_snapshot_quotes(_v4_scope, value, quotes, capture_session_date)
    rows = value.get("rows")

    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(rows) != _v4_global(_v4_scope, '_MARKET_SNAPSHOT_THEME_COUNT'):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot must contain 24 rows")
    requested_symbols, available_symbols = _b04_validate_market_snapshot_rows(_v4_scope, value, quotes, rows, capture_session_date)
    if value.get("requested_symbol_count") != _v4_global(_v4_scope, 'len')(requested_symbols):
        raise _v4_global(_v4_scope, 'ValueError')("invalid aggregate market_snapshot requested symbol count")

    if value.get("available_symbol_count") != _v4_global(_v4_scope, 'len')(available_symbols):
        raise _v4_global(_v4_scope, 'ValueError')("invalid aggregate market_snapshot available symbol count")

    if quote_symbols != available_symbols:
        raise _v4_global(_v4_scope, 'ValueError')("market_snapshot quotes do not match available symbols")

    quote_dates = _v4_global(_v4_scope, 'sorted')({quote["session_date"] for quote in quotes})

    provider_dates = value.get("provider_session_dates")

    if value.get("status") == "READY":
        if provider_dates != quote_dates:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot provider session dates mismatch")
    elif not _v4_global(_v4_scope, 'set')(quote_dates).issubset(provider_dates):
        raise _v4_global(_v4_scope, 'ValueError')("market_snapshot provider session dates mismatch")

    quote_times = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(quote["session_time"])
        for quote in quotes
        if _v4_global(_v4_scope, 'str')(quote.get("session_time") or "").strip()
    })

    provider_times = value.get("provider_session_times")

    if value.get("status") == "READY":
        if provider_times != quote_times:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot provider session times mismatch")
    elif not _v4_global(_v4_scope, 'set')(quote_times).issubset(provider_times):
        raise _v4_global(_v4_scope, 'ValueError')("market_snapshot provider session times mismatch")

    if value.get("status") in {"PARTIAL", "CANNOT_CONFIRM"} and not value.get("cannot_confirm"):
        raise _v4_global(_v4_scope, 'ValueError')("market_snapshot incomplete status requires cannot_confirm")

    if value.get("status") == "READY":
        if _v4_global(_v4_scope, 'any')(row.get("status") != "READY" for row in rows):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY status has non-ready row")
        if value.get("cannot_confirm"):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY status has cannot_confirm reasons")
        if value.get("provider_session_dates") != [capture_session_date]:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY session date invalid")

    if value.get("status") == "CANNOT_CONFIRM" and value.get("available_symbol_count"):
        # A failed or invalid quote can retain partial provider data, but the
        # failure must remain explicit at the snapshot boundary.
        if not value.get("cannot_confirm"):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot CANNOT_CONFIRM reason is missing")

    if "provider_receipt" in value and not _v4_global(_v4_scope, 'isinstance')(value["provider_receipt"], _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot provider receipt")

    if value.get("recommendation_status") != "RESEARCH_ONLY":
        raise _v4_global(_v4_scope, 'ValueError')("unsafe market_snapshot recommendation status")

    if value.get("production_allowed") is not False or value.get("buy_gate_updated") is not False or value.get("orders_sent") is not False:
        raise _v4_global(_v4_scope, 'ValueError')("unsafe market_snapshot safety flag")

    if value.get("RESEARCH_ONLY") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("unsafe market_snapshot research flag")

    return _v4_global(_v4_scope, 'dict')(value)

def _b04_validate_market_snapshot_quotes(_v4_scope, value, quotes, capture_session_date):
    quote_symbols: set[str] = _v4_global(_v4_scope, 'set')()

    for quote in quotes:
        if not _v4_global(_v4_scope, 'isinstance')(quote, _v4_global(_v4_scope, 'Mapping')) or not {
            "symbol",
            "exchange",
            "session_date",
            "session_time",
            "last",
            "previous_close",
            "change_pct",
            "provider",
        }.issubset(quote):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote")
        symbol = quote.get("symbol")
        if (
            not _v4_global(_v4_scope, 'isinstance')(symbol, _v4_global(_v4_scope, 'str'))
            or not symbol.strip()
            or symbol not in _v4_global(_v4_scope, '_CANONICAL_SYMBOLS')
            or symbol in quote_symbols
        ):
            raise _v4_global(_v4_scope, 'ValueError')("invalid or duplicate research peripheral market_snapshot quote symbol")
        quote_symbols.add(symbol)
        if quote.get("exchange") != "US" or not _v4_global(_v4_scope, 'isinstance')(quote.get("provider"), _v4_global(_v4_scope, 'str')) or not quote["provider"].strip():
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote identity")
        if quote.get("session_date") != capture_session_date:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot quote session date mismatch")
        if not _v4_global(_v4_scope, 'isinstance')(quote.get("session_date"), _v4_global(_v4_scope, 'str')) or not quote.get("session_date"):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote session_date")
        if not _v4_global(_v4_scope, 'isinstance')(quote.get("session_time"), _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote session_time")
        if quote.get("session_time") and not _v4_global(_v4_scope, '_US_SESSION_TIME').fullmatch(quote["session_time"]):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote session_time")
        if not quote.get("session_time") and (
            value.get("status") == "READY"
            or "QUOTE_SESSION_TIME_MISSING" not in value.get("cannot_confirm", [])
        ):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot quote session_time")
        for field in ("last", "previous_close", "change_pct"):
            _v4_global(_v4_scope, '_finite_number')(quote.get(field), f"market_snapshot quote {field}")
        last = _v4_global(_v4_scope, 'float')(quote["last"])
        previous_close = _v4_global(_v4_scope, 'float')(quote["previous_close"])
        if previous_close == 0:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot quote previous_close must be nonzero")
        derived_change = (last - previous_close) / previous_close * 100
        if (
            not _v4_global(_v4_scope, 'math').isfinite(derived_change)
            or _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, 'float')(quote["change_pct"]) - derived_change)
            > _v4_global(_v4_scope, '_QUOTE_CHANGE_TOLERANCE')
        ):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot quote change arithmetic mismatch")
    return quote_symbols

def _b04_validate_market_snapshot_rows(_v4_scope, value, quotes, rows, capture_session_date):
    labels: list[str] = []

    available_symbols: set[str] = _v4_global(_v4_scope, 'set')()

    requested_symbols: set[str] = _v4_global(_v4_scope, 'set')()

    for index, row in _v4_global(_v4_scope, 'enumerate')(rows):
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot row")
        for field in (
            "label",
            "group",
            "mapping_type",
            "proxy_symbols",
            "available_symbols",
            "missing_symbols",
            "requested_symbol_count",
            "available_symbol_count",
            "coverage",
            "coverage_pct",
            "change_pct",
            "pct_change",
            "direction",
            "status",
            "quote_session_dates",
            "quote_session_times",
            "cannot_confirm",
        ):
            if field not in row:
                raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral market_snapshot row fields")
        _v4_global(_v4_scope, '_canonical_row_shape')(row, index)
        label = row.get("label")
        if not _v4_global(_v4_scope, 'isinstance')(label, _v4_global(_v4_scope, 'str')) or not label.strip() or label in labels:
            raise _v4_global(_v4_scope, 'ValueError')("invalid or duplicate research peripheral market_snapshot label")
        labels.append(label)
        for field in ("group", "mapping_type"):
            if not _v4_global(_v4_scope, 'isinstance')(row.get(field), _v4_global(_v4_scope, 'str')) or not row[field].strip():
                raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral market_snapshot {field}")
        symbol_lists: dict[str, list[str]] = {}
        for field in ("proxy_symbols", "available_symbols", "missing_symbols"):
            symbols = row.get(field)
            if not _v4_global(_v4_scope, 'isinstance')(symbols, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(
                not _v4_global(_v4_scope, 'isinstance')(symbol, _v4_global(_v4_scope, 'str')) or not symbol.strip() for symbol in symbols
            ) or _v4_global(_v4_scope, 'len')(symbols) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(symbols)):
                raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral market_snapshot {field}")
            symbol_lists[field] = symbols
        if not _v4_global(_v4_scope, 'set')(symbol_lists["available_symbols"]).issubset(symbol_lists["proxy_symbols"]):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot available symbols are outside proxy mapping")
        if _v4_global(_v4_scope, 'set')(symbol_lists["available_symbols"]) | _v4_global(_v4_scope, 'set')(symbol_lists["missing_symbols"]) != _v4_global(_v4_scope, 'set')(symbol_lists["proxy_symbols"]):
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot coverage symbols do not partition proxy mapping")
        requested_count = row.get("requested_symbol_count")
        available_count = row.get("available_symbol_count")
        if _v4_global(_v4_scope, 'type')(requested_count) is not _v4_global(_v4_scope, 'int') or requested_count != _v4_global(_v4_scope, 'len')(symbol_lists["proxy_symbols"]):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot requested symbol count")
        if _v4_global(_v4_scope, 'type')(available_count) is not _v4_global(_v4_scope, 'int') or available_count != _v4_global(_v4_scope, 'len')(symbol_lists["available_symbols"]):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot available symbol count")
        coverage = row.get("coverage")
        if not _v4_global(_v4_scope, 'isinstance')(coverage, _v4_global(_v4_scope, 'Mapping')) or coverage.get("available") != available_count or coverage.get("requested") != requested_count:
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot coverage")
        coverage_pct = row.get("coverage_pct")
        if (
            _v4_global(_v4_scope, 'isinstance')(coverage_pct, _v4_global(_v4_scope, 'bool'))
            or not _v4_global(_v4_scope, 'isinstance')(coverage_pct, (_v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'float')))
            or not _v4_global(_v4_scope, 'math').isfinite(_v4_global(_v4_scope, 'float')(coverage_pct))
            or coverage_pct < 0
            or coverage_pct > 100
            or _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, 'float')(coverage_pct) - available_count / requested_count * 100) > _v4_global(_v4_scope, '_QUOTE_CHANGE_TOLERANCE')
        ):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot coverage_pct")
        pct_change = row.get("pct_change")
        if pct_change is not None:
            _v4_global(_v4_scope, '_finite_number')(pct_change, "market_snapshot pct_change")
        change_pct = row.get("change_pct")
        if change_pct is not None:
            _v4_global(_v4_scope, '_finite_number')(change_pct, "market_snapshot change_pct")
        if change_pct != pct_change:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot change_pct and pct_change mismatch")
        if row.get("direction") not in _v4_global(_v4_scope, '_MARKET_SNAPSHOT_DIRECTIONS'):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot direction")
        if row.get("status") not in _v4_global(_v4_scope, '_MARKET_SNAPSHOT_STATUSES'):
            raise _v4_global(_v4_scope, 'ValueError')("invalid market_snapshot row status")
        _v4_global(_v4_scope, '_string_list')(row.get("quote_session_dates"), "market_snapshot.row.quote_session_dates")
        _v4_global(_v4_scope, '_string_list')(row.get("quote_session_times"), "market_snapshot.row.quote_session_times")
        _v4_global(_v4_scope, '_string_list')(row.get("cannot_confirm"), "market_snapshot.row.cannot_confirm")
        available = symbol_lists["available_symbols"]
        row_quotes = [quote for quote in quotes if quote["symbol"] in available]
        expected_row_dates = _v4_global(_v4_scope, 'sorted')({
            _v4_global(_v4_scope, 'str')(quote["session_date"])
            for quote in row_quotes
            if _v4_global(_v4_scope, 'str')(quote.get("session_date") or "").strip()
        })
        expected_row_times = _v4_global(_v4_scope, 'sorted')({
            _v4_global(_v4_scope, 'str')(quote["session_time"])
            for quote in row_quotes
            if _v4_global(_v4_scope, 'str')(quote.get("session_time") or "").strip()
        })
        if row.get("quote_session_dates") != expected_row_dates:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot row session dates mismatch")
        if row.get("quote_session_times") != expected_row_times:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot row session times mismatch")
        expected_changes = [
            _v4_global(_v4_scope, 'float')(quote["change_pct"])
            for quote in quotes
            if quote["symbol"] in available
        ]
        if expected_changes:
            expected_row_change = _v4_global(_v4_scope, 'sum')(expected_changes) / _v4_global(_v4_scope, 'len')(expected_changes)
            if (
                change_pct is None
                or _v4_global(_v4_scope, 'abs')(_v4_global(_v4_scope, 'float')(change_pct) - expected_row_change) > _v4_global(_v4_scope, '_QUOTE_CHANGE_TOLERANCE')
            ):
                raise _v4_global(_v4_scope, 'ValueError')("market_snapshot row change arithmetic mismatch")
        elif change_pct is not None or pct_change is not None:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot empty row cannot have change")
        expected_direction = (
            "CANNOT_CONFIRM" if change_pct is None
            else "UP" if _v4_global(_v4_scope, 'float')(change_pct) > 0
            else "DOWN" if _v4_global(_v4_scope, 'float')(change_pct) < 0
            else "FLAT"
        )
        if row.get("direction") != expected_direction:
            raise _v4_global(_v4_scope, 'ValueError')("market_snapshot row direction mismatch")
        if row.get("status") == "READY":
            if _v4_global(_v4_scope, 'len')(available) != _v4_global(_v4_scope, 'len')(symbol_lists["proxy_symbols"]):
                raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY row coverage incomplete")
            if row.get("quote_session_dates") != [capture_session_date]:
                raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY row session date invalid")
            if not row.get("quote_session_times"):
                raise _v4_global(_v4_scope, 'ValueError')("market_snapshot READY row session time missing")
        available_symbols.update(symbol_lists["available_symbols"])
        requested_symbols.update(symbol_lists["proxy_symbols"])
    return requested_symbols, available_symbols
