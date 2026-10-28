"""ops.a_share_daily_sync: rebuild (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_rebuild_candidate_body(_v4_scope, /, source_path, replacements, candidate_path, *, expected_source_sha256, expected_replacement_sha256, expected_replacement_dates):
    """Write a side-by-side corrected ``.day`` candidate.

    Existing records are carried as their original 32-byte bytes.  Repacking
    the whole file through :func:`read_hq_day_bars` loses reserved bytes and
    silently collapses duplicate dates, so only explicitly supplied dates are
    encoded with the existing ``pack_hq_bar`` codec.  Missing dates retain the
    historical append/insert behavior, while an existing date is replaced
    in-place in the date-sorted stream.
    """
    source_path = _v4_global(_v4_scope, 'Path')(source_path)
    candidate_path = _v4_global(_v4_scope, 'Path')(candidate_path)
    source_failure = _v4_global(_v4_scope, '_local_path_failure')(source_path)
    if source_failure is not None:
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_PATH_REJECTED:{source_path}:{source_failure}")

    candidate_failure = _v4_global(_v4_scope, '_local_path_failure')(candidate_path)
    if candidate_failure is not None:
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_CANDIDATE_PATH_REJECTED:{candidate_path}:{candidate_failure}")
    if source_path.absolute() == candidate_path.absolute():
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_CANDIDATE_PATH_COLLISION:{source_path}")
    if source_path.exists() and candidate_path.exists():
        try:
            if source_path.samefile(candidate_path):
                raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_CANDIDATE_PATH_COLLISION:{source_path}")
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass

    source_bytes = b""
    if source_path.exists():
        if not source_path.is_file():
            raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_PATH_REJECTED:{source_path}:source_not_regular")
        try:
            source_bytes = source_path.read_bytes()
        except _v4_global(_v4_scope, 'OSError') as exc:
            raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_SOURCE_READ_FAILED:{source_path}:{exc!r}") from exc
    source_sha256 = _v4_global(_v4_scope, 'hashlib').sha256(source_bytes).hexdigest()
    if expected_source_sha256 is not None and source_sha256.lower() != _v4_global(_v4_scope, 'str')(expected_source_sha256).lower():
        raise _v4_global(_v4_scope, 'ValueError')(
            f"A_SYNC_SOURCE_SHA_MISMATCH:expected={expected_source_sha256}:actual={source_sha256}"
        )
    if _v4_global(_v4_scope, 'len')(source_bytes) % _v4_global(_v4_scope, 'DAY_STRUCT').size:
        raise _v4_global(_v4_scope, 'ValueError')(
            f"A_SYNC_SOURCE_FILE_SHAPE_REJECTED:truncated:size={_v4_global(_v4_scope, 'len')(source_bytes)}:record_size={_v4_global(_v4_scope, 'DAY_STRUCT').size}"
        )

    source_records: List[Tuple[int, bytes]] = []
    previous_date: Optional[int] = None
    for row_index, offset in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(source_bytes), _v4_global(_v4_scope, 'DAY_STRUCT').size)):
        raw = source_bytes[offset : offset + _v4_global(_v4_scope, 'DAY_STRUCT').size]
        date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = _v4_global(_v4_scope, 'DAY_STRUCT').unpack(raw)
        bar = {
            "year": date_i // 10000,
            "month": date_i // 100 % 100,
            "day": date_i % 100,
            "open": open_i / 100.0,
            "high": high_i / 100.0,
            "low": low_i / 100.0,
            "close": close_i / 100.0,
            "amount": amount_f,
            "vol": vol_u / 100.0,
        }
        valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(bar)
        if not valid:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_SOURCE_RECORD_REJECTED:row={row_index}:date={date_i}:{reason}")
        if previous_date is not None:
            if date_i == previous_date:
                raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_SOURCE_DUPLICATE_DATE:row={row_index}:date={date_i}")
            if date_i < previous_date:
                raise _v4_global(_v4_scope, 'ValueError')(
                    f"A_SYNC_SOURCE_NON_MONOTONIC_DATE:row={row_index}:date={date_i}:previous={previous_date}"
                )
        source_records.append((date_i, raw))
        previous_date = date_i

    replacement_records: Dict[int, bytes] = {}
    for row_index, replacement in _v4_global(_v4_scope, 'enumerate')(replacements):
        if not _v4_global(_v4_scope, 'isinstance')(replacement, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:bar_not_mapping")
        try:
            date_value = _v4_global(_v4_scope, 'day_int')(_v4_global(_v4_scope, 'dict')(replacement))
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as exc:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:bad_date:{exc!r}") from exc
        if date_value in replacement_records:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_REPLACEMENT_DUPLICATE_DATE:row={row_index}:date={date_value}")
        valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(replacement)
        if not valid:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:date={date_value}:{reason}")
        try:
            packed = _v4_global(_v4_scope, 'pack_hq_bar')(_v4_global(_v4_scope, 'dict')(replacement))
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError'), _v4_global(_v4_scope, 'struct').error) as exc:
            raise _v4_global(_v4_scope, 'ValueError')(
                f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:date={date_value}:pack_error:{exc!r}"
            ) from exc
        if _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'DAY_STRUCT').unpack_from(packed, 0)[0]) != date_value:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_REPLACEMENT_DATE_MISMATCH:row={row_index}:date={date_value}")
        replacement_records[date_value] = packed

    if expected_replacement_dates is not None:
        try:
            expected_dates = [_v4_global(_v4_scope, 'int')(date_value) for date_value in expected_replacement_dates]
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as exc:
            raise _v4_global(_v4_scope, 'ValueError')(f"A_SYNC_EXPECTED_REPLACEMENT_DATES_INVALID:{exc!r}") from exc
        if _v4_global(_v4_scope, 'len')(expected_dates) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(expected_dates)):
            raise _v4_global(_v4_scope, 'ValueError')("A_SYNC_EXPECTED_REPLACEMENT_DATES_DUPLICATE")
        if _v4_global(_v4_scope, 'sorted')(expected_dates) != _v4_global(_v4_scope, 'sorted')(replacement_records):
            raise _v4_global(_v4_scope, 'ValueError')(
                "A_SYNC_REPLACEMENT_DATES_MISMATCH:"
                f"expected={_v4_global(_v4_scope, 'sorted')(expected_dates)}:actual={_v4_global(_v4_scope, 'sorted')(replacement_records)}"
            )

    if expected_replacement_sha256 is not None:
        expected_sha_by_date = {_v4_global(_v4_scope, 'int')(date_value): _v4_global(_v4_scope, 'str')(digest).lower() for date_value, digest in expected_replacement_sha256.items()}
        if _v4_global(_v4_scope, 'set')(expected_sha_by_date) != _v4_global(_v4_scope, 'set')(replacement_records):
            raise _v4_global(_v4_scope, 'ValueError')(
                "A_SYNC_REPLACEMENT_SHA_SCOPE_MISMATCH:"
                f"expected={_v4_global(_v4_scope, 'sorted')(expected_sha_by_date)}:actual={_v4_global(_v4_scope, 'sorted')(replacement_records)}"
            )
        for date_value, packed in replacement_records.items():
            actual = _v4_global(_v4_scope, 'hashlib').sha256(packed).hexdigest()
            if actual != expected_sha_by_date[date_value]:
                raise _v4_global(_v4_scope, 'ValueError')(
                    f"A_SYNC_REPLACEMENT_SHA_MISMATCH:date={date_value}:"
                    f"expected={expected_sha_by_date[date_value]}:actual={actual}"
                )

    replacement_dates = _v4_global(_v4_scope, 'sorted')(replacement_records)
    replacement_index = 0
    output_records: List[Tuple[int, bytes]] = []
    for date_value, raw in source_records:
        while replacement_index < _v4_global(_v4_scope, 'len')(replacement_dates) and replacement_dates[replacement_index] < date_value:
            inserted_date = replacement_dates[replacement_index]
            output_records.append((inserted_date, replacement_records[inserted_date]))
            replacement_index += 1
        if replacement_index < _v4_global(_v4_scope, 'len')(replacement_dates) and replacement_dates[replacement_index] == date_value:
            output_records.append((date_value, replacement_records[date_value]))
            replacement_index += 1
        else:
            output_records.append((date_value, raw))
    while replacement_index < _v4_global(_v4_scope, 'len')(replacement_dates):
        inserted_date = replacement_dates[replacement_index]
        output_records.append((inserted_date, replacement_records[inserted_date]))
        replacement_index += 1

    candidate_bytes = b"".join(raw for _date_value, raw in output_records)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_failure = _v4_global(_v4_scope, '_local_path_failure')(candidate_path)
    if candidate_failure is not None:
        raise _v4_global(_v4_scope, 'OSError')(f"A_SYNC_CANDIDATE_PATH_REJECTED:{candidate_path}:{candidate_failure}")
    with candidate_path.open("wb") as handle:
        handle.write(candidate_bytes)

    source_chunks = [
        source_bytes[offset : offset + _v4_global(_v4_scope, 'DAY_STRUCT').size]
        for offset in _v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(source_bytes), _v4_global(_v4_scope, 'DAY_STRUCT').size)
    ]
    candidate_chunks = [
        candidate_bytes[offset : offset + _v4_global(_v4_scope, 'DAY_STRUCT').size]
        for offset in _v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(candidate_bytes), _v4_global(_v4_scope, 'DAY_STRUCT').size)
    ]
    changed_rows = (
        [row_index for row_index, (before, after) in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'zip')(source_chunks, candidate_chunks)) if before != after]
        if _v4_global(_v4_scope, 'len')(source_chunks) == _v4_global(_v4_scope, 'len')(candidate_chunks)
        else None
    )
    changed_byte_offsets = [
        offset
        for offset, (before, after) in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'zip')(source_bytes, candidate_bytes))
        if before != after
    ]
    return {
        "source_path": _v4_global(_v4_scope, 'str')(source_path),
        "candidate_path": _v4_global(_v4_scope, 'str')(candidate_path),
        "replaced_dates": replacement_dates,
        "source_sha256": source_sha256,
        "candidate_sha256": _v4_global(_v4_scope, 'hashlib').sha256(candidate_bytes).hexdigest(),
        "source_record_count": _v4_global(_v4_scope, 'len')(source_records),
        "candidate_record_count": _v4_global(_v4_scope, 'len')(output_records),
        "changed_rows": changed_rows,
        "changed_byte_offsets": changed_byte_offsets,
    }
