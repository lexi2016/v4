"""Frozen identity contract for the native Futu US board display."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any


FUTU_US_BOARD_REGISTRY_VERSION = "futu_us_native_board_registry.v1"
FUTU_US_BOARD_SNAPSHOT_SCHEMA_VERSION = "v3_5.futu_us_native_board_snapshot.v2"
FUTU_US_BOARD_PROVIDER = "Futu OpenD"
FUTU_US_BOARD_TIMEZONE = "America/New_York"
_US_CODE = re.compile(r"^US\.([A-Z][A-Z0-9.]*)$")

# This is a closed display set. It intentionally does not expand from the
# provider's catalog and contains no old proxy/theme aliases.
FUTU_US_BOARD_REGISTRY: tuple[dict[str, str], ...] = (
    {"board_id": "US.LIST2015", "plate_type": "INDUSTRY", "board_name": "半导体", "board_code": "US.LIST2015"},
    {"board_id": "US.LIST23925", "plate_type": "CONCEPT", "board_name": "存储概念", "board_code": "US.LIST23925"},
    {"board_id": "US.LIST2521", "plate_type": "CONCEPT", "board_name": "IDC概念", "board_code": "US.LIST2521"},
    {"board_id": "US.LIST2540", "plate_type": "CONCEPT", "board_name": "云计算服务商", "board_code": "US.LIST2540"},
    {"board_id": "US.LIST2653", "plate_type": "CONCEPT", "board_name": "机器人概念股", "board_code": "US.LIST2653"},
    {"board_id": "US.LIST23590", "plate_type": "CONCEPT", "board_name": "智能驾驶概念股", "board_code": "US.LIST23590"},
    {"board_id": "US.LIST2583", "plate_type": "CONCEPT", "board_name": "核电", "board_code": "US.LIST2583"},
    {"board_id": "US.LIST2089", "plate_type": "INDUSTRY", "board_name": "航空航天与国防", "board_code": "US.LIST2089"},
    {"board_id": "US.LIST2450", "plate_type": "CONCEPT", "board_name": "光伏太阳能", "board_code": "US.LIST2450"},
    {"board_id": "US.LIST2552", "plate_type": "CONCEPT", "board_name": "锂电池", "board_code": "US.LIST2552"},
    {"board_id": "US.LIST2582", "plate_type": "CONCEPT", "board_name": "天然气", "board_code": "US.LIST2582"},
    {"board_id": "US.LIST2110", "plate_type": "INDUSTRY", "board_name": "黄金", "board_code": "US.LIST2110"},
    {"board_id": "US.LIST23700", "plate_type": "CONCEPT", "board_name": "稀土概念", "board_code": "US.LIST23700"},
    {"board_id": "US.LIST2136", "plate_type": "CONCEPT", "board_name": "人工智能", "board_code": "US.LIST2136"},
    {"board_id": "US.LIST2548", "plate_type": "CONCEPT", "board_name": "AI芯片", "board_code": "US.LIST2548"},
    {"board_id": "US.LIST23979", "plate_type": "CONCEPT", "board_name": "光通信", "board_code": "US.LIST23979"},
    {"board_id": "US.LIST2556", "plate_type": "CONCEPT", "board_name": "太空概念", "board_code": "US.LIST2556"},
    {"board_id": "US.LIST2472", "plate_type": "INDUSTRY", "board_name": "受监管电力", "board_code": "US.LIST2472"},
    {"board_id": "US.LIST2572", "plate_type": "CONCEPT", "board_name": "可再生能源", "board_code": "US.LIST2572"},
    {"board_id": "US.LIST2224", "plate_type": "INDUSTRY", "board_name": "综合油气", "board_code": "US.LIST2224"},
    {"board_id": "US.LIST2510", "plate_type": "INDUSTRY", "board_name": "铜", "board_code": "US.LIST2510"},
    {"board_id": "US.LIST2481", "plate_type": "INDUSTRY", "board_name": "多元化银行", "board_code": "US.LIST2481"},
    {"board_id": "US.LIST2069", "plate_type": "INDUSTRY", "board_name": "生物技术", "board_code": "US.LIST2069"},
    {"board_id": "US.LIST2003", "plate_type": "INDUSTRY", "board_name": "家庭和个人用品", "board_code": "US.LIST2003"},
)


def _canonical_sha256(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


FUTU_US_BOARD_REGISTRY_SHA256 = _canonical_sha256({
    "registry_version": FUTU_US_BOARD_REGISTRY_VERSION,
    "boards": [dict(row) for row in FUTU_US_BOARD_REGISTRY],
})


def _session_date_token(value: Any) -> str:
    raw = str(value).strip()
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date() if re.fullmatch(r"20\d{6}", raw) else date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("invalid US session date") from error
    return parsed.strftime("%Y%m%d")


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or int(value) != value or value < 0:
        return None
    return int(value)


def _empty_row(identity: Mapping[str, str], reason: str) -> dict[str, Any]:
    return {
        **dict(identity),
        "metric_kind": "OFFICIAL_BOARD",
        "market": "US",
        "expected_board_name": identity["board_name"],
        "update_time": None,
        "session_date": None,
        "timezone": FUTU_US_BOARD_TIMEZONE,
        "last": None,
        "previous_close": None,
        "change_pct": None,
        "plate_valid": None,
        "rise_count": None,
        "fall_count": None,
        "equal_count": None,
        "membership_status": "CANNOT_CONFIRM",
        "member_count": None,
        "membership_sha256": "",
        "membership_cannot_confirm": ["FUTU_BOARD_MEMBERSHIP_NOT_CAPTURED"],
        "source_response_sha256": "",
        "status": "CANNOT_CONFIRM",
        "cannot_confirm": [reason],
    }


def empty_futu_us_board_snapshot(session_date: str, reason: str) -> dict[str, Any]:
    capture_date = _session_date_token(session_date)
    return {
        "schema_version": FUTU_US_BOARD_SNAPSHOT_SCHEMA_VERSION,
        "registry_version": FUTU_US_BOARD_REGISTRY_VERSION,
        "registry_sha256": FUTU_US_BOARD_REGISTRY_SHA256,
        "provider": FUTU_US_BOARD_PROVIDER,
        "market": "US",
        "timezone": FUTU_US_BOARD_TIMEZONE,
        "capture_session_date": capture_date,
        "source_response_sha256": "",
        "requested_board_count": len(FUTU_US_BOARD_REGISTRY),
        "available_board_count": 0,
        "status": "CANNOT_CONFIRM",
        "rows": [_empty_row(identity, reason) for identity in FUTU_US_BOARD_REGISTRY],
        "cannot_confirm": [reason],
        "membership_cannot_confirm": ["FUTU_BOARD_MEMBERSHIP_NOT_CAPTURED"],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def validate_futu_us_board_snapshot(value: Any, *, expected_session_date: str | None = None) -> dict[str, Any]:
    """Validate native board identities, quote facts and separate membership state."""
    if not isinstance(value, Mapping):
        raise ValueError("invalid native Futu board snapshot")
    required = {
        "schema_version", "registry_version", "registry_sha256", "provider", "market", "timezone",
        "capture_session_date", "source_response_sha256", "requested_board_count", "available_board_count",
        "status", "rows", "cannot_confirm", "membership_cannot_confirm", "RESEARCH_ONLY",
        "production_allowed", "buy_gate_updated", "orders_sent",
    }
    if not required.issubset(value):
        raise ValueError("invalid native Futu board snapshot fields")
    if any(value.get(key) != expected for key, expected in {
        "schema_version": FUTU_US_BOARD_SNAPSHOT_SCHEMA_VERSION,
        "registry_version": FUTU_US_BOARD_REGISTRY_VERSION,
        "registry_sha256": FUTU_US_BOARD_REGISTRY_SHA256,
        "provider": FUTU_US_BOARD_PROVIDER,
        "market": "US",
        "timezone": FUTU_US_BOARD_TIMEZONE,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }.items()):
        raise ValueError("invalid native Futu board snapshot identity or safety flags")
    session_date = _session_date_token(value.get("capture_session_date"))
    if expected_session_date is not None and session_date != _session_date_token(expected_session_date):
        raise ValueError("native Futu board snapshot session date mismatch")
    digest = value.get("source_response_sha256")
    if not isinstance(digest, str) or (digest and not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid native Futu board snapshot source hash")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != len(FUTU_US_BOARD_REGISTRY):
        raise ValueError("native Futu board snapshot row count does not match frozen registry")
    if type(value.get("requested_board_count")) is not int or value["requested_board_count"] != len(FUTU_US_BOARD_REGISTRY):
        raise ValueError("native Futu board requested count does not match frozen registry")
    if not isinstance(value.get("cannot_confirm"), list) or any(not isinstance(item, str) or not item for item in value["cannot_confirm"]):
        raise ValueError("invalid native Futu board cannot_confirm")
    if not isinstance(value.get("membership_cannot_confirm"), list) or any(not isinstance(item, str) or not item for item in value["membership_cannot_confirm"]):
        raise ValueError("invalid native Futu membership cannot_confirm")

    ready_count = 0
    quote_reasons: set[str] = set()
    membership_reasons: set[str] = set()
    for row, identity in zip(rows, FUTU_US_BOARD_REGISTRY):
        if not isinstance(row, Mapping):
            raise ValueError("invalid native Futu board row")
        if any(row.get(key) != expected for key, expected in identity.items()):
            raise ValueError("native Futu board identity does not match frozen registry")
        if any(row.get(key) != expected for key, expected in {
            "metric_kind": "OFFICIAL_BOARD", "market": "US", "expected_board_name": identity["board_name"],
            "timezone": FUTU_US_BOARD_TIMEZONE,
        }.items()):
            raise ValueError("invalid native Futu board row metadata")
        row_status = row.get("status")
        if row_status not in {"READY", "CANNOT_CONFIRM"}:
            raise ValueError("invalid native Futu board row status")
        reasons = row.get("cannot_confirm")
        if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons):
            raise ValueError("invalid native Futu board row reasons")
        quote_reasons.update(reasons)
        row_date = row.get("session_date")
        if row_date is not None:
            row_date = _session_date_token(row_date)
        if row.get("plate_valid") not in {True, False, None}:
            raise ValueError("invalid native Futu plate validity")
        counts = [row.get("rise_count"), row.get("fall_count"), row.get("equal_count")]
        if row.get("plate_valid") is not True and any(count is not None for count in counts):
            raise ValueError("native Futu counts require a valid board")
        if any(count is not None and _count(count) != count for count in counts):
            raise ValueError("invalid native Futu breadth count")
        last = row.get("last")
        previous_close = row.get("previous_close")
        if last is not None and _positive_number(last) is None:
            raise ValueError("invalid native Futu last price")
        if previous_close is not None and _positive_number(previous_close) is None:
            raise ValueError("invalid native Futu previous close")
        change = row.get("change_pct")
        if change is not None and (isinstance(change, bool) or not isinstance(change, (int, float)) or not math.isfinite(float(change))):
            raise ValueError("invalid native Futu change")
        row_sha = row.get("source_response_sha256")
        if not isinstance(row_sha, str) or (row_sha and not re.fullmatch(r"[0-9a-f]{64}", row_sha)):
            raise ValueError("invalid native Futu row source hash")
        if row_status == "READY":
            ready_count += 1
            if (
                row_date != session_date or row.get("plate_valid") is not True
                or not isinstance(row.get("update_time"), str)
                or not re.fullmatch(r"20\d\d-\d\d-\d\d \d\d:\d\d:\d\d", row["update_time"])
                or row["update_time"][:10].replace("-", "") != session_date
                or _positive_number(last) is None or _positive_number(previous_close) is None
                or any(_count(count) is None for count in counts)
                or not isinstance(change, (int, float)) or isinstance(change, bool)
                or round((float(last) - float(previous_close)) / float(previous_close) * 100, 6) != round(float(change), 6)
            ):
                raise ValueError("incomplete native Futu board row marked READY")
        elif change is not None:
            raise ValueError("unconfirmed native Futu board row has change")

        membership_status = row.get("membership_status")
        if membership_status not in {"READY", "CANNOT_CONFIRM"}:
            raise ValueError("invalid native Futu membership status")
        member_count = row.get("member_count")
        if member_count is not None and _count(member_count) != member_count:
            raise ValueError("invalid native Futu membership count")
        membership_sha = row.get("membership_sha256")
        if not isinstance(membership_sha, str) or (membership_sha and not re.fullmatch(r"[0-9a-f]{64}", membership_sha)):
            raise ValueError("invalid native Futu membership hash")
        member_reasons = row.get("membership_cannot_confirm")
        if not isinstance(member_reasons, list) or any(not isinstance(item, str) or not item for item in member_reasons):
            raise ValueError("invalid native Futu membership reasons")
        membership_reasons.update(member_reasons)
        if membership_status == "READY":
            if member_count is None or _count(member_count) is None or not re.fullmatch(r"[0-9a-f]{64}", membership_sha) or member_reasons:
                raise ValueError("incomplete native Futu membership marked READY")
        elif not member_reasons:
            raise ValueError("native Futu membership failure requires its own reason")

    expected_status = "READY" if ready_count == len(rows) else "PARTIAL" if ready_count else "CANNOT_CONFIRM"
    if value.get("status") != expected_status or value.get("available_board_count") != ready_count:
        raise ValueError("native Futu board count or aggregate status mismatch")
    if expected_status != "READY" and not value.get("cannot_confirm"):
        raise ValueError("incomplete native Futu snapshot requires reasons")
    if not quote_reasons.issubset(set(value.get("cannot_confirm") or [])):
        raise ValueError("native Futu snapshot omitted quote reasons")
    if not membership_reasons.issubset(set(value.get("membership_cannot_confirm") or [])):
        raise ValueError("native Futu snapshot omitted membership reasons")
    return dict(value)
