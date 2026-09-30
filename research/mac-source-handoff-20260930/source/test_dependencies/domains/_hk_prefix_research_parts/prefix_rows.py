"""domains.hk_prefix_research: prefix_rows (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __row_from_source_body(_v4_scope, /, source_row, *, series_id, session_index, date_text):
    close_at = _v4_global(_v4_scope, '_aware_eod')(date_text)
    output: dict[str, Any] = {
        "series_id": series_id,
        "session_index": _v4_global(_v4_scope, 'int')(session_index),
        "close_at": close_at,
        "available_at": close_at,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
        "price_basis": _v4_global(_v4_scope, 'PRICE_BASIS'),
        "quality": "MISSING_SOURCE_ROW",
    }
    if source_row is None:
        return output
    output.update(
        {
            "open": source_row.get("open"),
            "high": source_row.get("high"),
            "low": source_row.get("low"),
            "close": source_row.get("close"),
            "volume": source_row.get(_v4_global(_v4_scope, 'VOLUME_SOURCE_COLUMN')),
        }
    )
    numeric = _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, '_finite')(output[key]) for key in ("open", "high", "low", "close", "volume"))
    try:
        valid_ohlc = (
            numeric
            and _v4_global(_v4_scope, 'float')(output["low"]) > 0
            and _v4_global(_v4_scope, 'float')(output["low"]) <= _v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'float')(output["open"]), _v4_global(_v4_scope, 'float')(output["close"]))
            and _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'float')(output["open"]), _v4_global(_v4_scope, 'float')(output["close"])) <= _v4_global(_v4_scope, 'float')(output["high"])
            and _v4_global(_v4_scope, 'float')(output["volume"]) >= 0
        )
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
        valid_ohlc = False
    output["quality"] = "OK" if valid_ohlc else "INVALID_SOURCE_OHLCV"
    return output


def _build_prefix_rows_body(_v4_scope, /, source_frame, calendar, *, code, event_date, series_id):
    """Build exactly 60 calendar-indexed rows through event_date minus one."""

    code = _v4_global(_v4_scope, '_normalize_code')(code)
    event_date = _v4_global(_v4_scope, '_iso_date')(event_date, field="event_date")
    if _v4_global(_v4_scope, 'int')(event_date[:4]) > _v4_global(_v4_scope, 'MAX_YEAR'):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("2026 or later event entered prefix builder")
    try:
        event_index = calendar.date_to_index[event_date]
    except _v4_global(_v4_scope, 'KeyError') as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"event date absent from frozen R1 calendar: {event_date}") from error
    if event_index < _v4_global(_v4_scope, 'PREFIX_LENGTH'):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("event date has fewer than 60 frozen market sessions")
    dates = calendar.dates[event_index - _v4_global(_v4_scope, 'PREFIX_LENGTH') : event_index]
    if _v4_global(_v4_scope, 'len')(dates) != _v4_global(_v4_scope, 'PREFIX_LENGTH') or dates[-1] >= event_date:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("prefix window is not exactly the prior 60 market sessions")
    filtered = source_frame[source_frame["code"].map(_v4_global(_v4_scope, '_normalize_code')).eq(code)]
    by_date: dict[str, Mapping[str, Any]] = {}
    for row in filtered.to_dict("records"):
        date_text = _v4_global(_v4_scope, '_iso_date')(row.get("date"), field="source date")
        if date_text in dates:
            if date_text in by_date:
                raise _v4_global(_v4_scope, 'HKPrefixResearchError')("source code/date duplicate reached prefix builder")
            by_date[date_text] = row
    rows = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, '_row_from_source')(
            by_date.get(date_text),
            series_id=series_id,
            session_index=calendar.date_to_index[date_text],
            date_text=date_text,
        )
        for date_text in dates
    )
    observed = _v4_global(_v4_scope, 'sum')(row["quality"] != "MISSING_SOURCE_ROW" for row in rows)
    return rows, observed, _v4_global(_v4_scope, 'PREFIX_LENGTH') - observed
