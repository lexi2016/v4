"""Binary packing and snapshot validation for daily panel inputs."""

from __future__ import annotations

import hashlib
import json
import re
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


HK_VOLUME_OVERFLOW_SIDECAR_SCHEMA = "v4.hk_daily_volume_overflow_sidecar.v1"
HK_VOLUME_OVERFLOW_SIDECAR_DIR = ".v4_hk_volume_overflow"
HK_VOLUME_UINT32_MAX = (1 << 32) - 1


def _hk_volume(row: Mapping[str, Any]) -> int:
    # Preserve the existing UInt32-path rounding semantics.
    return int(round(_number(row, "volume", "vol", default=1)))


def _exact_hk_volume(row: Mapping[str, Any]) -> int:
    return _hk_volume(row)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _hk_sidecar_root(destination: Path | str) -> Path:
    return Path(destination).expanduser().resolve() / "vipdoc" / "ds" / "lday" / HK_VOLUME_OVERFLOW_SIDECAR_DIR


def _sidecar_path(destination: Path, target_date: str) -> Path:
    return _hk_sidecar_root(destination) / f"{target_date}.json"


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_hk_volume_sidecars(
    destination: Path | str,
    rows: Iterable[Mapping[str, Any]],
    *,
    target_date: str,
    source_capture_sha256: str | None = None,
    source_capture_raw_sha256: str | None = None,
    require_source_capture_binding: bool = False,
) -> dict[str, Any]:
    """Check that the one dated overflow ledger exactly matches this capture."""
    root = Path(destination).expanduser().resolve()
    target = _date(target_date)
    incoming = _rows(rows)
    overflow_rows = [row for row in incoming if _hk_volume(row) > HK_VOLUME_UINT32_MAX]
    expected = {_code(row).zfill(5): row for row in overflow_rows}
    if len(expected) != len(overflow_rows):
        raise SnapshotGateError("HK overflow sidecar input has duplicate codes")
    sidecar_root = _hk_sidecar_root(root)
    path = _sidecar_path(root, target)
    if not expected:
        if sidecar_root.is_symlink() or path.exists() or path.is_symlink():
            raise SnapshotGateError("unexpected HK volume overflow sidecar")
        return {"status": "READY", "target_date": target, "codes": [], "ledger_path": "", "ledger_sha256": ""}
    if sidecar_root.is_symlink() or path.is_symlink() or not path.is_file():
        raise SnapshotGateError("HK overflow sidecar ledger missing or symlinked")
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotGateError("HK overflow sidecar ledger unreadable") from error
    if not isinstance(ledger, dict) or ledger.get("schema_version") != HK_VOLUME_OVERFLOW_SIDECAR_SCHEMA or ledger.get("target_date") != target:
        raise SnapshotGateError("HK overflow sidecar identity mismatch")
    claimed_sha = ledger.get("ledger_sha256")
    body = dict(ledger)
    body.pop("ledger_sha256", None)
    if claimed_sha != _json_sha256(body):
        raise SnapshotGateError("HK overflow sidecar ledger SHA mismatch")
    capture_sha256 = ledger.get("source_capture_sha256")
    capture_raw_sha256 = ledger.get("source_capture_raw_sha256")
    if not _is_sha256(capture_sha256) or not _is_sha256(capture_raw_sha256):
        raise SnapshotGateError("HK overflow sidecar capture SHA missing")
    if require_source_capture_binding and source_capture_sha256 is not None and capture_sha256 != source_capture_sha256:
        raise SnapshotGateError("HK overflow sidecar capture SHA mismatch")
    if require_source_capture_binding and source_capture_raw_sha256 is not None and capture_raw_sha256 != source_capture_raw_sha256:
        raise SnapshotGateError("HK overflow sidecar raw capture SHA mismatch")
    entries = ledger.get("rows")
    if not isinstance(entries, list) or {str(item.get("code") or "") for item in entries if isinstance(item, Mapping)} != {f"HK.{code}" for code in expected} or len(entries) != len(expected):
        raise SnapshotGateError("HK overflow sidecar code set mismatch")
    day_root = root / "vipdoc" / "ds" / "lday"
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise SnapshotGateError("HK overflow sidecar row invalid")
        code = str(entry.get("code") or "")
        digits = code.removeprefix("HK.")
        source_row = entry.get("source_row")
        if code not in {f"HK.{value}" for value in expected} or not isinstance(source_row, Mapping):
            raise SnapshotGateError("HK overflow sidecar row identity mismatch")
        expected_volume = _hk_volume(expected[digits])
        if (
            source_row != expected[digits]
            or entry.get("source_row_sha256") != _json_sha256(source_row)
            or entry.get("volume_shares") != expected_volume
            or entry.get("volume_unit") != "shares"
        ):
            raise SnapshotGateError(f"HK overflow sidecar row differs from capture: {code}")
        prefix = entry.get("native_prefix")
        if not isinstance(prefix, Mapping) or prefix.get("path") != f"71#{digits}.day":
            raise SnapshotGateError(f"HK overflow sidecar native binding invalid: {code}")
        day_path = day_root / f"71#{digits}.day"
        if day_path.is_symlink():
            raise SnapshotGateError(f"HK overflow sidecar native file is symlinked: {code}")
        day_bytes = day_path.read_bytes() if day_path.is_file() else b""
        size = prefix.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or not _is_sha256(prefix.get("sha256")) or len(day_bytes) < size or hashlib.sha256(day_bytes[:size]).hexdigest() != prefix.get("sha256"):
            raise SnapshotGateError(f"HK overflow sidecar native prefix changed: {code}")
        if len(day_bytes) % HK_DAY_STRUCT.size:
            raise SnapshotGateError(f"existing .day has trailing bytes: {day_path.name}")
        dates = [int(HK_DAY_STRUCT.unpack(day_bytes[offset:offset + HK_DAY_STRUCT.size])[0]) for offset in range(0, len(day_bytes), HK_DAY_STRUCT.size)]
        if int(target) in dates or (dates and int(target) < max(dates)):
            raise SnapshotGateError(f"HK overflow sidecar conflicts with native .day history: {code}")
    return {
        "status": "READY", "target_date": target,
        "codes": sorted(str(item["code"]) for item in entries),
        "ledger_path": str(path), "ledger_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_capture_sha256": ledger["source_capture_sha256"],
        "source_capture_raw_sha256": ledger["source_capture_raw_sha256"],
    }


def _panel_frame(panel_path: Path) -> list[dict[str, Any]]:
    if not panel_path.is_file():
        raise SnapshotGateError(f"A seed panel missing: {panel_path}")
    try:
        import pandas as pd

        from ops.research_panel_logical import read_frame
        frame = read_frame(panel_path)
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
        _hk_volume(row),
        0,
    )


def _build_hk_volume_sidecar_entry(
    source_row: Mapping[str, Any],
    *,
    target_date: str,
    code: str,
    day_path: Path,
) -> dict[str, Any]:
    if source_row.get("source") != "FUTU_HKCONNECT_SNAPSHOT":
        raise SnapshotGateError("HK overflow sidecar requires the Futu daily capture source")
    native_bytes = day_path.read_bytes() if day_path.is_file() else b""
    if day_path.is_symlink() or len(native_bytes) % HK_DAY_STRUCT.size:
        raise SnapshotGateError(f"HK sidecar native .day file invalid: {day_path.name}")
    native_dates = [int(HK_DAY_STRUCT.unpack(native_bytes[i:i + HK_DAY_STRUCT.size])[0]) for i in range(0, len(native_bytes), HK_DAY_STRUCT.size)]
    if int(target_date) in native_dates:
        raise SnapshotGateError(f"HK overflow sidecar conflicts with an existing target-date .day row: {day_path.name}")
    if native_dates and int(target_date) < max(native_dates):
        raise SnapshotGateError(f"HK overflow sidecar target date is older than native .day history: {day_path.name}")
    return {
        "code": f"HK.{code}",
        "source_row": dict(source_row),
        "source_row_sha256": _json_sha256(source_row),
        "volume_shares": _hk_volume(source_row),
        "volume_unit": "shares",
        "native_prefix": {
            "path": day_path.name,
            "size_bytes": len(native_bytes),
            "sha256": hashlib.sha256(native_bytes).hexdigest(),
        },
    }


def _write_hk_volume_sidecar_ledger(
    destination: Path,
    *,
    target_date: str,
    entries: list[dict[str, Any]],
    capture_sha256: str,
    capture_raw_sha256: str,
    source_rows: list[dict[str, Any]],
    already_current: bool = False,
) -> dict[str, Any]:
    root = _hk_sidecar_root(destination)
    if root.is_symlink():
        raise SnapshotGateError("HK overflow sidecar root must not be a symlink")
    ledger_path = root / f"{target_date}.json"
    if ledger_path.is_symlink():
        raise SnapshotGateError("HK overflow sidecar ledger must not be a symlink")
    if ledger_path.exists():
        summary = validate_hk_volume_sidecars(
            destination, source_rows, target_date=target_date,
        )
        if set(summary.get("codes") or ()) != {str(entry["code"]) for entry in entries}:
            raise SnapshotGateError("HK overflow sidecar ledger conflicts with current input")
        return summary | {"already_current": True}
    ledger = {
        "schema_version": HK_VOLUME_OVERFLOW_SIDECAR_SCHEMA,
        "target_date": target_date,
        "source_capture_sha256": capture_sha256,
        "source_capture_raw_sha256": capture_raw_sha256,
        "rows": sorted(entries, key=lambda item: str(item["code"])),
    }
    ledger["ledger_sha256"] = _json_sha256(ledger)
    encoded = json.dumps(ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    _atomic_write(ledger_path, encoded)
    if ledger_path.is_symlink() or ledger_path.read_bytes() != encoded:
        raise SnapshotGateError("HK overflow sidecar ledger readback mismatch")
    return validate_hk_volume_sidecars(
        destination, source_rows, target_date=target_date,
        source_capture_sha256=capture_sha256,
        source_capture_raw_sha256=capture_raw_sha256,
        require_source_capture_binding=True,
    ) | {"already_current": already_current}


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


def pack_hk_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 600, expected_codes: set[str] | None = None, source_capture_sha256: str | None = None, source_capture_raw_sha256: str | None = None) -> dict[str, Any]:
    destination = Path(destination).expanduser().resolve()
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

    source_by_code: dict[str, dict[str, Any]] = {}
    for source in incoming:
        code = _code(source).zfill(5)
        if code in source_by_code:
            raise SnapshotGateError(f"HK snapshot duplicate code: {code}")
        source_by_code[code] = source
    checked_codes = {str(row["code"]).zfill(5) for row in checked}
    if set(source_by_code) != checked_codes:
        raise SnapshotGateError("HK normalized input code set changed during validation")

    overflow_by_code = {
        code: source for code, source in source_by_code.items()
        if _exact_hk_volume(source) > HK_VOLUME_UINT32_MAX
    }
    if overflow_by_code and (
        not _is_sha256(source_capture_sha256)
        or not _is_sha256(source_capture_raw_sha256)
    ):
        raise SnapshotGateError("HK overflow sidecar requires validated source capture SHA values")

    sidecar_path = _sidecar_path(destination, _date(target_date))
    existing_sidecar_summary = None
    if overflow_by_code and sidecar_path.exists():
        existing_sidecar_summary = validate_hk_volume_sidecars(
            destination,
            incoming,
            target_date=target_date,
        ) | {"already_current": True}
    elif not overflow_by_code:
        validate_hk_volume_sidecars(destination, incoming, target_date=target_date)

    overflow_entries: list[dict[str, Any]] = []
    if existing_sidecar_summary is None:
        for code, source in sorted(overflow_by_code.items()):
            if source.get("source") != "FUTU_HKCONNECT_SNAPSHOT":
                raise SnapshotGateError("HK overflow sidecar requires the Futu daily capture source")
            day_path = destination / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
            overflow_entries.append(
                _build_hk_volume_sidecar_entry(
                    source,
                    target_date=_date(target_date),
                    code=code,
                    day_path=day_path,
                )
            )

    results = []
    for row in checked:
        code = str(row["code"]).zfill(5)
        if code in overflow_by_code:
            continue
        path = destination / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
        result = _pack_day_file(
            path,
            [row],
            target_date,
            lane="HK",
            minimum_rows=1,
            record_struct=HK_DAY_STRUCT,
            record_builder=_hk_record,
        )
        result.update({"storage": "TDX_DAY", "code": f"HK.{code}"})
        results.append(result)

    if overflow_by_code:
        sidecar_summary = existing_sidecar_summary or _write_hk_volume_sidecar_ledger(
            destination,
            target_date=_date(target_date),
            entries=overflow_entries,
            capture_sha256=str(source_capture_sha256),
            capture_raw_sha256=str(source_capture_raw_sha256),
            source_rows=incoming,
        )
        expected_overflow = {f"HK.{code}" for code in overflow_by_code}
        if set(sidecar_summary.get("codes") or ()) != expected_overflow:
            raise SnapshotGateError("HK overflow sidecar code set mismatch after write")
        for code, source in sorted(overflow_by_code.items()):
            results.append({
                "status": "READY",
                "storage": "VOLUME_SIDECAR",
                "code": f"HK.{code}",
                "already_current": bool(sidecar_summary.get("already_current", False)),
                "target_date": _date(target_date),
                "row_count": 1,
                "coverage_rate": 1.0,
                "sha256": sidecar_summary["ledger_sha256"],
                "path": sidecar_summary["ledger_path"],
                "volume_shares": _exact_hk_volume(source),
                "volume_unit": "shares",
                **SAFETY_FLAGS,
            })
    else:
        sidecar_summary = validate_hk_volume_sidecars(
            destination,
            incoming,
            target_date=target_date,
        )

    packed = _grouped_result(results, target_date, lane="HK") | {"coverage_rate": coverage}
    packed["volume_overflow_sidecar"] = sidecar_summary
    return packed

def validate_snapshot(rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int, expected_codes: set[str] | None = None, lane: str) -> dict[str, Any]:
    checked, _ = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    actual = {_code(row) for row in checked}
    expected = {_code({"code": code}) for code in expected_codes} if expected_codes else actual
    if actual != expected:
        raise SnapshotGateError(f"{lane} coverage mismatch: {len(actual)}/{len(expected)}")
    canonical = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"trade_date": _date(target_date), "row_count": len(checked), "coverage_rate": len(actual) / max(len(expected), 1), "sha256": hashlib.sha256(canonical).hexdigest(), **SAFETY_FLAGS}
