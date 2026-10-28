"""Binary packing and snapshot validation for daily panel inputs."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .macos_research_panel_daily_common import (
    A_DAY_STRUCT,
    COMMON_A_PREFIXES,
    HK_DAY_STRUCT,
    SAFETY_FLAGS,
    SnapshotGateError,
    _atomic_write,
    _code,
    _date,
    _number,
    _rows,
    _sha,
    _validate_rows,
)


def _panel_frame(panel_path: Path) -> list[dict[str, Any]]:
    if not panel_path.is_file():
        raise SnapshotGateError(f"A seed panel missing: {panel_path}")
    try:
        import pandas as pd

        frame = pd.read_parquet(panel_path)
        return _rows(frame)
    except Exception as error:
        raise SnapshotGateError(f"A seed panel unreadable: {panel_path}") from error


def bootstrap_a_vipdoc_from_panel(panel_path: Path | str, tdx_root: Path | str, *, tail_records: int = 260) -> dict[str, Any]:
    """Seed SH/SZ/BJ VIPDOC files from a panel tail without overwriting history."""
    if int(tail_records) < 1:
        raise SnapshotGateError("tail_records must be positive")
    rows = _panel_frame(Path(panel_path))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for source in rows:
        code_value = str(source.get("ts_code") or source.get("code") or "").strip().upper()
        if "." not in code_value:
            continue
        code, exchange = code_value.split(".", 1)
        exchange = exchange.split("_", 1)[0].lower()
        if exchange not in {"sh", "sz", "bj"}:
            continue
        if not code.isdigit() or len(code) != 6:
            continue
        if not code.startswith(COMMON_A_PREFIXES[exchange]):
            continue
        row = {
            "trade_date": _date(source.get("trade_date") or source.get("trade_date_compact")),
            "code": code,
            "exchange": exchange,
            "open": _number(source, "open"),
            "high": _number(source, "high"),
            "low": _number(source, "low"),
            "close": _number(source, "close"),
            "volume": _number(source, "volume", "vol"),
            "turnover": _number(source, "amount", "turnover"),
        }
        if min(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < row["low"] or row["close"] < row["low"] or row["close"] > row["high"]:
            raise SnapshotGateError(f"A seed invalid OHLC: {code}")
        grouped.setdefault((exchange, code), []).append(row)
    if not grouped:
        raise SnapshotGateError("A seed panel has no SH/SZ/BJ rows")
    results = []
    destination = Path(tdx_root)
    for (exchange, code), code_rows in sorted(grouped.items()):
        ordered = sorted(code_rows, key=lambda item: int(item["trade_date"]))[-int(tail_records):]
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code}.day"
        checked = _validate_seed_rows(ordered)
        encoded = b"".join(A_DAY_STRUCT.pack(*_a_record(row)) for row in checked)
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise SnapshotGateError(f"A seed conflict: {path}")
            already_current = True
        else:
            _atomic_write(path, encoded)
            already_current = False
        results.append({"status": "READY", "already_current": already_current, "target_date": checked[-1]["trade_date"], "row_count": len(checked), "coverage_rate": 1.0, "sha256": _sha(path), "path": str(path), **SAFETY_FLAGS})
    return _grouped_result(results, max(str(item["target_date"]) for item in results), lane="A") | {"seed_panel": str(Path(panel_path)), "tail_records": int(tail_records)}


def _validate_seed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise SnapshotGateError("A seed has no rows")
    dates: set[int] = set()
    checked = []
    for row in rows:
        date_value = int(_date(row.get("trade_date")))
        if date_value in dates:
            raise SnapshotGateError(f"A seed duplicate date: {date_value}")
        dates.add(date_value)
        if min(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) <= 0:
            raise SnapshotGateError(f"A seed non-positive OHLC: {row.get('code')}")
        checked.append(dict(row, trade_date=str(date_value)))
    return sorted(checked, key=lambda item: int(item["trade_date"]))


def _day_file_last_date(path: Path, record_struct: struct.Struct) -> int | None:
    records = _existing_records(path, record_struct)
    return int(records[-1][0]) if records else None


def _existing_records(path: Path, record_struct: struct.Struct) -> list[tuple[Any, ...]]:
    if not path.exists():
        return []
    payload = path.read_bytes()
    if len(payload) % record_struct.size:
        raise SnapshotGateError(f"existing .day has trailing bytes: {path.name}")
    return [record_struct.unpack(payload[offset : offset + record_struct.size]) for offset in range(0, len(payload), record_struct.size)]


def _a_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        int(round(_number(row, "open") * 100)),
        int(round(_number(row, "high") * 100)),
        int(round(_number(row, "low") * 100)),
        int(round(_number(row, "close") * 100)),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol"))),
        0,
    )


def _hk_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        _number(row, "open"),
        _number(row, "high"),
        _number(row, "low"),
        _number(row, "close"),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol", default=1))),
        0,
    )


def _pack_day_file(destination: Path, rows: Iterable[Mapping[str, Any]], target_date: str, *, lane: str, minimum_rows: int, record_struct: struct.Struct, record_builder: Callable[[Mapping[str, Any]], tuple[Any, ...]]) -> dict[str, Any]:
    checked, coverage = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    encoded = b"".join(record_struct.pack(*record_builder(row)) for row in checked)
    existing = _existing_records(destination, record_struct)
    target_int = int(_date(target_date))
    existing_dates = [int(record[0]) for record in existing]
    if existing_dates and target_int < max(existing_dates):
        raise SnapshotGateError(f"{lane} target date is older than existing file: {target_date}")
    existing_target = [record_struct.pack(*record) for record in existing if int(record[0]) == target_int]
    if existing_target:
        if b"".join(existing_target) != encoded:
            raise SnapshotGateError(f"{lane} target-date conflict: {destination}")
        return {
            "status": "READY",
            "already_current": True,
            "target_date": _date(target_date),
            "row_count": len(checked),
            "coverage_rate": coverage,
            "sha256": _sha(destination),
            "path": str(destination),
            **SAFETY_FLAGS,
        }
    payload = destination.read_bytes() if destination.exists() else b""
    _atomic_write(destination, payload + encoded)
    return {
        "status": "READY",
        "already_current": False,
        "target_date": _date(target_date),
        "row_count": len(checked),
        "coverage_rate": coverage,
        "sha256": _sha(destination),
        "path": str(destination),
        **SAFETY_FLAGS,
    }


def _a_exchange(row: Mapping[str, Any]) -> str:
    exchange = str(row.get("exchange") or row.get("market") or "").strip().lower()
    if exchange in {"sh", "sz", "bj"}:
        return exchange
    code = _code(row)
    if code.startswith(("6",)):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    raise SnapshotGateError(f"cannot infer A exchange for {code}")


def _grouped_result(results: list[dict[str, Any]], target_date: str, *, lane: str) -> dict[str, Any]:
    if not results:
        raise SnapshotGateError(f"{lane} empty grouped result")
    return {
        "status": "READY",
        "target_date": _date(target_date),
        "row_count": sum(int(result.get("row_count", 0)) for result in results),
        "file_count": len(results),
        "coverage_rate": 1.0,
        "sha256": hashlib.sha256("".join(sorted(str(result["sha256"]) for result in results)).encode()).hexdigest(),
        "files": results,
        **SAFETY_FLAGS,
    }


def pack_a_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 1) -> dict[str, Any]:
    destination = Path(destination)
    incoming = _rows(rows)
    if destination.suffix.lower() == ".day":
        raise SnapshotGateError("pack_a_day destination must be a TDX root, not a single .day file")
    checked, _ = _validate_rows(incoming, target_date, minimum_rows=minimum_rows, lane="A")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in checked:
        grouped.setdefault(_code(row), []).append(row)
    results = []
    for code, code_rows in sorted(grouped.items()):
        exchange = _a_exchange(code_rows[0])
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code.zfill(6)}.day"
        results.append(_pack_day_file(path, code_rows, target_date, lane="A", minimum_rows=1, record_struct=A_DAY_STRUCT, record_builder=_a_record))
    return _grouped_result(results, target_date, lane="A")


def pack_hk_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 600, expected_codes: set[str] | None = None) -> dict[str, Any]:
    destination = Path(destination)
    incoming = _rows(rows)
    if destination.suffix.lower() == ".day":
        raise SnapshotGateError("pack_hk_day destination must be a TDX root, not a single .day file")
    checked, coverage = _validate_rows(incoming, target_date, minimum_rows=minimum_rows, lane="HK")
    if expected_codes is not None:
        expected = {"".join(ch for ch in str(code) if ch.isdigit()).zfill(5) for code in expected_codes}
        actual = {str(row["code"]).zfill(5) for row in checked}
        if actual != expected:
            raise SnapshotGateError(f"HK snapshot coverage mismatch: {len(actual)}/{len(expected)}")
        coverage = len(actual) / max(len(expected), 1)
    results = []
    for row in checked:
        code = str(row["code"]).zfill(5)
        path = destination / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
        results.append(_pack_day_file(path, [row], target_date, lane="HK", minimum_rows=1, record_struct=HK_DAY_STRUCT, record_builder=_hk_record))
    return _grouped_result(results, target_date, lane="HK") | {"coverage_rate": coverage}


def validate_snapshot(rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int, expected_codes: set[str] | None = None, lane: str) -> dict[str, Any]:
    checked, _ = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    actual = {_code(row) for row in checked}
    expected = {_code({"code": code}) for code in expected_codes} if expected_codes else actual
    if actual != expected:
        raise SnapshotGateError(f"{lane} coverage mismatch: {len(actual)}/{len(expected)}")
    canonical = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"trade_date": _date(target_date), "row_count": len(checked), "coverage_rate": len(actual) / max(len(expected), 1), "sha256": hashlib.sha256(canonical).hexdigest(), **SAFETY_FLAGS}
