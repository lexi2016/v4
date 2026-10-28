"""ops.a_share_daily_sync: day_file_format (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _write_csv_body(_v4_scope, /, path, rows):
    _v4_global(_v4_scope, 'ensure_dir')(path.parent)
    keys: List[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = _v4_global(_v4_scope, 'csv').DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})


def _valid_hq_bar_body(_v4_scope, /, bar):
    try:
        if not _v4_global(_v4_scope, 'isinstance')(bar, _v4_global(_v4_scope, 'Mapping')):
            return False, "bar_not_mapping"
        required_date_fields = ("year", "month", "day")
        if _v4_global(_v4_scope, 'any')(
            not _v4_global(_v4_scope, 'isinstance')(bar.get(field), _v4_global(_v4_scope, 'int')) or _v4_global(_v4_scope, 'isinstance')(bar.get(field), _v4_global(_v4_scope, 'bool'))
            for field in required_date_fields
        ):
            return False, "date_not_integer"
        date_value = _v4_global(_v4_scope, 'day_int')(bar)
        values = {field: bar[field] for field in ("open", "high", "low", "close")}
        if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, '_is_finite_real')(value) for value in values.values()):
            return False, "ohlc_not_finite_numeric"
        open_v = _v4_global(_v4_scope, 'float')(values["open"])
        high_v = _v4_global(_v4_scope, 'float')(values["high"])
        low_v = _v4_global(_v4_scope, 'float')(values["low"])
        close_v = _v4_global(_v4_scope, 'float')(values["close"])
    except _v4_global(_v4_scope, 'Exception') as exc:
        return False, f"parse_error:{exc!r}"
    if "amount" not in bar:
        return False, "missing_amount"
    volume_key = "vol" if "vol" in bar else "volume" if "volume" in bar else None
    if volume_key is None:
        return False, "missing_volume"
    if not _v4_global(_v4_scope, '_is_finite_real')(bar["amount"]):
        return False, "amount_not_finite_numeric"
    if not _v4_global(_v4_scope, '_is_finite_real')(bar[volume_key]):
        return False, "volume_not_finite_numeric"
    amount_v = _v4_global(_v4_scope, 'float')(bar["amount"])
    volume_v = _v4_global(_v4_scope, 'float')(bar[volume_key])
    if amount_v < 0:
        return False, "negative_amount"
    if volume_v < 0:
        return False, "negative_volume"
    if not (19900101 <= date_value <= 21000101):
        return False, f"bad_date:{date_value}"
    try:
        _v4_global(_v4_scope, 'datetime')(
            _v4_global(_v4_scope, 'int')(bar["year"]),
            _v4_global(_v4_scope, 'int')(bar["month"]),
            _v4_global(_v4_scope, 'int')(bar["day"]),
        )
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
        return False, f"bad_calendar_date:{date_value}"
    if _v4_global(_v4_scope, 'min')(open_v, high_v, low_v, close_v) <= 0:
        return False, "non_positive_ohlc"
    if high_v < low_v:
        return False, "high_lt_low"
    if close_v > high_v or close_v < low_v:
        return False, "close_outside_high_low"
    return True, "ok"


def _read_hq_day_bars_body(_v4_scope, /, path, tail_records):
    if _v4_global(_v4_scope, '_local_path_failure')(path) is not None or not path.exists():
        return []
    size = path.stat().st_size
    count = size // _v4_global(_v4_scope, 'DAY_STRUCT').size
    start = _v4_global(_v4_scope, 'max')(0, count - tail_records) if tail_records else 0
    rows: List[Dict[str, Any]] = []
    with path.open("rb") as f:
        f.seek(start * _v4_global(_v4_scope, 'DAY_STRUCT').size)
        data = f.read((count - start) * _v4_global(_v4_scope, 'DAY_STRUCT').size)
    for offset in _v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(data), _v4_global(_v4_scope, 'DAY_STRUCT').size):
        date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = _v4_global(_v4_scope, 'DAY_STRUCT').unpack_from(data, offset)
        rows.append({
            "year": date_i // 10000, "month": date_i // 100 % 100, "day": date_i % 100,
            "open": open_i / 100.0, "high": high_i / 100.0, "low": low_i / 100.0,
            "close": close_i / 100.0, "amount": amount_f, "vol": vol_u / 100.0,
        })
    return rows


def _append_bars_body(_v4_scope, /, path, bars):
    failure = _v4_global(_v4_scope, '_local_path_failure')(path)
    if failure is not None:
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_PATH_REJECTED:{path}:{failure}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after creating the parent chain.  This keeps a race that turns
    # an ancestor into a link from becoming an outside write.
    failure = _v4_global(_v4_scope, '_local_path_failure')(path)
    if failure is not None:
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_PATH_REJECTED:{path}:{failure}")
    with path.open("ab") as f:
        for bar in bars:
            f.write(_v4_global(_v4_scope, 'pack_hq_bar')(bar))
