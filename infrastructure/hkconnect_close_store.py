"""V3.5-owned storage for verified full-universe HK Connect close snapshots."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, time, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.stage_store import _assert_safe_tree


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HK_CODE = re.compile(r"^HK\.\d{5}$")
_FUTU_SOURCE_MODE = "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT"
_FUTU_TIMEZONE_NAME = "Asia/Shanghai"
_FUTU_TIMEZONE = ZoneInfo(_FUTU_TIMEZONE_NAME)
_FINAL_CLOSE_CUTOFF = time.fromisoformat("16:10:00")
_FUTU_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")


def parse_futu_update_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        return None
    return parsed.replace(tzinfo=_FUTU_TIMEZONE)


def futu_close_capture_time_gap(
    payload: Mapping[str, Any], trade_date: str
) -> str | None:
    """Return a typed gap when a Futu close artifact lacks verified source time."""
    if not isinstance(payload, Mapping) or payload.get("source_mode") != _FUTU_SOURCE_MODE:
        return None
    capture = payload.get("source_capture")
    if not isinstance(capture, Mapping):
        return "HK_CLOSE_SOURCE_CAPTURE_TIME_UNVERIFIED"
    if (
        capture.get("provider") != "FUTU_OPENAPI"
        or capture.get("api") != "get_market_snapshot"
        or capture.get("timestamp_field") != "update_time"
        or capture.get("timezone") != _FUTU_TIMEZONE_NAME
        or capture.get("plate_codes") != list(_FUTU_PLATE_CODES)
    ):
        return "HK_CLOSE_SOURCE_CAPTURE_TIME_UNVERIFIED"

    queried_at_raw = capture.get("queried_at")
    try:
        queried_at = datetime.fromisoformat(queried_at_raw)
    except (TypeError, ValueError):
        return "HK_CLOSE_QUERY_TIME_UNVERIFIED"
    if (
        queried_at.tzinfo is None
        or queried_at.utcoffset() != timedelta(hours=8)
        or queried_at.isoformat(timespec="seconds") != queried_at_raw
    ):
        return "HK_CLOSE_QUERY_TIME_UNVERIFIED"

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return "HK_CLOSE_SOURCE_CAPTURE_TIME_UNVERIFIED"
    parsed_times: list[datetime] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return "HK_CLOSE_SOURCE_CAPTURE_TIME_UNVERIFIED"
        parsed = parse_futu_update_time(row.get("update_time"))
        if parsed is None:
            return "HK_CLOSE_SOURCE_TIME_MISSING_OR_INVALID"
        if parsed.strftime("%Y%m%d") != trade_date:
            return "HK_CLOSE_SOURCE_TIME_DATE_MISMATCH"
        if parsed.time() < _FINAL_CLOSE_CUTOFF:
            return "HK_CLOSE_SOURCE_TIME_BEFORE_FINAL_CLOSE_CUTOFF"
        parsed_raw = row.get("source_update_time")
        try:
            declared = datetime.fromisoformat(parsed_raw)
        except (TypeError, ValueError):
            return "HK_CLOSE_SOURCE_TIME_MISSING_OR_INVALID"
        if (
            declared.tzinfo is None
            or declared.utcoffset() != timedelta(hours=8)
            or declared.isoformat(timespec="seconds") != parsed_raw
            or declared.astimezone(_FUTU_TIMEZONE) != parsed
            or row.get("source_timezone") != _FUTU_TIMEZONE_NAME
        ):
            return "HK_CLOSE_SOURCE_TIME_MISSING_OR_INVALID"
        parsed_times.append(parsed)

    if (
        capture.get("source_time_min")
        != min(parsed_times).isoformat(timespec="seconds")
        or capture.get("source_time_max")
        != max(parsed_times).isoformat(timespec="seconds")
    ):
        return "HK_CLOSE_SOURCE_CAPTURE_TIME_UNVERIFIED"

    capture_base = dict(capture)
    declared_sha = capture_base.pop("source_sha256", None)
    if (
        not isinstance(declared_sha, str)
        or not _SHA256.fullmatch(declared_sha)
        or payload.get("source_input_sha256") != declared_sha
    ):
        return "HK_CLOSE_SOURCE_CAPTURE_SHA_UNVERIFIED"
    source_bytes = json.dumps(
        {
            "trade_date": trade_date,
            "plate_codes": list(_FUTU_PLATE_CODES),
            "rows": rows,
            "source_capture": capture_base,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(source_bytes).hexdigest() != declared_sha:
        return "HK_CLOSE_SOURCE_CAPTURE_SHA_UNVERIFIED"
    return None


def _positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def validate_close_snapshot(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_5.hkconnect_close_snapshot.v1":
        raise ValueError("invalid HK Connect close snapshot schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    fixed = {
        "status": "READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("invalid HK Connect close snapshot boundary")
    source_sha = payload.get("source_input_sha256")
    if not isinstance(source_sha, str) or not _SHA256.fullmatch(source_sha):
        raise ValueError("invalid close source SHA-256")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 600:
        raise ValueError("full HK Connect close snapshot requires at least 600 rows")
    universe_count = payload.get("universe_count")
    same_date_count = payload.get("same_date_row_count")
    if (
        isinstance(universe_count, bool)
        or isinstance(same_date_count, bool)
        or universe_count != len(rows)
        or same_date_count != len(rows)
        or float(payload.get("coverage_ratio") or 0.0) < 1.0
    ):
        raise ValueError("close snapshot coverage proof mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("invalid close row")
        code = str(row.get("code") or "")
        if (
            str(row.get("trade_date") or "") != trade_date
            or not _HK_CODE.fullmatch(code)
            or code in seen
            or not _positive(row.get("close"))
            or not _positive(row.get("pre_close"))
        ):
            raise ValueError("invalid or duplicate close row")
        seen.add(code)
    _assert_safe_tree(payload)
    if payload.get("source_mode") == _FUTU_SOURCE_MODE and "source_capture" in payload:
        capture_gap = futu_close_capture_time_gap(payload, trade_date)
        if capture_gap is not None:
            raise ValueError(capture_gap)
    return trade_date


class CloseSnapshotStore(NativeDataStore):
    def import_snapshot(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_close_snapshot(payload)
        relative = f"hkconnect_close_snapshots/{trade_date}.json"
        receipt = f"receipts/hkconnect_close_snapshots/{trade_date}.json"
        with self._lock():
            result = self._import(relative, payload, receipt)
        return {**result, "payload_path": relative}

    def read_snapshot(self, trade_date: str) -> tuple[dict[str, Any], str]:
        trade_date = _date(trade_date)
        relative = f"hkconnect_close_snapshots/{trade_date}.json"
        receipt_path = f"receipts/hkconnect_close_snapshots/{trade_date}.json"
        if not self._path(relative).is_file():
            raise FileNotFoundError(relative)
        try:
            payload = self._read(relative)
            digest = _sha256(payload)
            manifest = self._manifest()
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("HK Connect close snapshot evidence cannot be read") from error
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": trade_date,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("HK Connect close snapshot manifest or receipt mismatch")
        if validate_close_snapshot(payload) != trade_date:
            raise ValueError("HK Connect close snapshot identity mismatch")
        return payload, digest
