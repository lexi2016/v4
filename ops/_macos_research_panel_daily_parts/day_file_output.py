"""ops.macos_research_panel_daily: day_file_output (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __pack_day_file_body(_v4_scope, /, destination, rows, target_date, *, lane, minimum_rows, record_struct, record_builder):
    checked, coverage = _v4_global(_v4_scope, '_validate_rows')(_v4_global(_v4_scope, '_rows')(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    encoded = b"".join(record_struct.pack(*record_builder(row)) for row in checked)
    existing = _v4_global(_v4_scope, '_existing_records')(destination, record_struct)
    target_int = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_date')(target_date))
    existing_dates = [_v4_global(_v4_scope, 'int')(record[0]) for record in existing]
    if existing_dates and target_int < _v4_global(_v4_scope, 'max')(existing_dates):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} target date is older than existing file: {target_date}")
    existing_target = [record_struct.pack(*record) for record in existing if _v4_global(_v4_scope, 'int')(record[0]) == target_int]
    if existing_target:
        if b"".join(existing_target) != encoded:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} target-date conflict: {destination}")
        return {
            "status": "READY",
            "already_current": True,
            "target_date": _v4_global(_v4_scope, '_date')(target_date),
            "row_count": _v4_global(_v4_scope, 'len')(checked),
            "coverage_rate": coverage,
            "sha256": _v4_global(_v4_scope, '_sha')(destination),
            "path": _v4_global(_v4_scope, 'str')(destination),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    payload = destination.read_bytes() if destination.exists() else b""
    _v4_global(_v4_scope, '_atomic_write')(destination, payload + encoded)
    return {
        "status": "READY",
        "already_current": False,
        "target_date": _v4_global(_v4_scope, '_date')(target_date),
        "row_count": _v4_global(_v4_scope, 'len')(checked),
        "coverage_rate": coverage,
        "sha256": _v4_global(_v4_scope, '_sha')(destination),
        "path": _v4_global(_v4_scope, 'str')(destination),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def __grouped_result_body(_v4_scope, /, results, target_date, *, lane):
    if not results:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} empty grouped result")
    return {
        "status": "READY",
        "target_date": _v4_global(_v4_scope, '_date')(target_date),
        "row_count": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'int')(result.get("row_count", 0)) for result in results),
        "file_count": _v4_global(_v4_scope, 'len')(results),
        "coverage_rate": 1.0,
        "sha256": _v4_global(_v4_scope, 'hashlib').sha256("".join(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'str')(result["sha256"]) for result in results)).encode()).hexdigest(),
        "files": results,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def _pack_a_day_body(_v4_scope, /, destination, rows, *, target_date, minimum_rows):
    destination = _v4_global(_v4_scope, 'Path')(destination)
    incoming = _v4_global(_v4_scope, '_rows')(rows)
    if destination.suffix.lower() == ".day":
        raise _v4_global(_v4_scope, 'SnapshotGateError')("pack_a_day destination must be a TDX root, not a single .day file")
    checked, _ = _v4_global(_v4_scope, '_validate_rows')(incoming, target_date, minimum_rows=minimum_rows, lane="A")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in checked:
        grouped.setdefault(_v4_global(_v4_scope, '_code')(row), []).append(row)
    results = []
    for code, code_rows in _v4_global(_v4_scope, 'sorted')(grouped.items()):
        exchange = _v4_global(_v4_scope, '_a_exchange')(code_rows[0])
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code.zfill(6)}.day"
        results.append(_v4_global(_v4_scope, '_pack_day_file')(path, code_rows, target_date, lane="A", minimum_rows=1, record_struct=_v4_global(_v4_scope, 'A_DAY_STRUCT'), record_builder=_v4_global(_v4_scope, '_a_record')))
    return _v4_global(_v4_scope, '_grouped_result')(results, target_date, lane="A")


def _pack_hk_day_body(_v4_scope, /, destination, rows, *, target_date, minimum_rows, expected_codes):
    destination = _v4_global(_v4_scope, 'Path')(destination)
    incoming = _v4_global(_v4_scope, '_rows')(rows)
    if destination.suffix.lower() == ".day":
        raise _v4_global(_v4_scope, 'SnapshotGateError')("pack_hk_day destination must be a TDX root, not a single .day file")
    checked, coverage = _v4_global(_v4_scope, '_validate_rows')(incoming, target_date, minimum_rows=minimum_rows, lane="HK")
    if expected_codes is not None:
        expected = {"".join(ch for ch in _v4_global(_v4_scope, 'str')(code) if ch.isdigit()).zfill(5) for code in expected_codes}
        actual = {_v4_global(_v4_scope, 'str')(row["code"]).zfill(5) for row in checked}
        if actual != expected:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"HK snapshot coverage mismatch: {_v4_global(_v4_scope, 'len')(actual)}/{_v4_global(_v4_scope, 'len')(expected)}")
        coverage = _v4_global(_v4_scope, 'len')(actual) / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(expected), 1)
    results = []
    for row in checked:
        code = _v4_global(_v4_scope, 'str')(row["code"]).zfill(5)
        path = destination / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
        results.append(_v4_global(_v4_scope, '_pack_day_file')(path, [row], target_date, lane="HK", minimum_rows=1, record_struct=_v4_global(_v4_scope, 'HK_DAY_STRUCT'), record_builder=_v4_global(_v4_scope, '_hk_record')))
    return _v4_global(_v4_scope, '_grouped_result')(results, target_date, lane="HK") | {"coverage_rate": coverage}
