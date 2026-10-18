"""Futu US board facts used by the existing US close snapshot producer.

This is a small adapter only: it does not own a schedule, store, or data lane.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any


FUTU_INDUSTRY_SCHEMA_VERSION = "v3_5.futu_us_industry_snapshot.v1"
FUTU_PROVIDER = "Futu OpenD"
FUTU_SESSION_TIMEZONE = "America/New_York"
_US_CODE = re.compile(r"^US\.([A-Z][A-Z0-9.]*)$")
_RELATION_SYMBOLS = frozenset({"NVDA", "AMD", "DLR", "EQIX", "STX", "VRT"})
_PLATE_STOCK_REQUEST_LIMIT = 10
_PLATE_STOCK_REQUEST_WINDOW_SECONDS = 30.0
_monotonic = time.monotonic
_sleep = time.sleep

# Only exact, observed Futu board names are wired. Labels without an exact
# board remain explicit CANNOT_CONFIRM rows; ETF and stock-basket references
# never fill this map.
FUTU_BOARD_MAP: tuple[dict[str, str | None], ...] = (
    {"label": "AI算力", "plate_type": None, "plate_name": None},
    {"label": "CPO", "plate_type": None, "plate_name": None},
    {"label": "半导体", "plate_type": "INDUSTRY", "plate_name": "半导体"},
    {"label": "存储", "plate_type": "CONCEPT", "plate_name": "存储概念"},
    {"label": "数据中心", "plate_type": "CONCEPT", "plate_name": "IDC概念"},
    {"label": "云计算", "plate_type": "CONCEPT", "plate_name": "云计算服务商"},
    {"label": "商业航天", "plate_type": None, "plate_name": None},
    {"label": "卫星", "plate_type": None, "plate_name": None},
    {"label": "机器人", "plate_type": "CONCEPT", "plate_name": "机器人概念股"},
    {"label": "自动驾驶", "plate_type": "CONCEPT", "plate_name": "智能驾驶概念股"},
    {"label": "核电", "plate_type": "CONCEPT", "plate_name": "核电"},
    {"label": "电网", "plate_type": None, "plate_name": None},
    {"label": "军工", "plate_type": "INDUSTRY", "plate_name": "航空航天与国防"},
    {"label": "新能源", "plate_type": None, "plate_name": None},
    {"label": "光伏", "plate_type": "CONCEPT", "plate_name": "光伏太阳能"},
    {"label": "锂电池", "plate_type": "CONCEPT", "plate_name": "锂电池"},
    {"label": "石油", "plate_type": None, "plate_name": None},
    {"label": "天然气", "plate_type": "CONCEPT", "plate_name": "天然气"},
    {"label": "铜/有色", "plate_type": None, "plate_name": None},
    {"label": "黄金", "plate_type": "INDUSTRY", "plate_name": "黄金"},
    {"label": "银行金融", "plate_type": None, "plate_name": None},
    {"label": "生物医药", "plate_type": None, "plate_name": None},
    {"label": "消费", "plate_type": None, "plate_name": None},
    {"label": "稀土", "plate_type": "CONCEPT", "plate_name": "稀土概念"},
)


def _scalar(value: Any) -> Any:
    """Convert common pandas/numpy scalar values to strict JSON values."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    # numpy scalar types expose item(); pandas NA/NaN are handled as null.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _scalar(item())
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        if value != value:  # NaN and pandas NaT
            return None
    except (TypeError, ValueError):
        pass
    return value if isinstance(value, str) else None


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        source = value
    elif hasattr(value, "to_dict"):
        try:
            source = value.to_dict("records")
        except TypeError:
            source = value.to_dict(orient="records")
    else:
        source = value
    if not isinstance(source, (list, tuple)):
        return []
    return [
        {str(key): _scalar(item) for key, item in row.items()}
        for row in source
        if isinstance(row, Mapping)
    ]


def _canonical_sha256(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _response(ret: Any, data: Any) -> list[dict[str, Any]]:
    return _records(data) if ret == 0 else []


def _wait_for_plate_stock_request(request_times: list[float]) -> None:
    """Keep this producer under Futu's 10 get_plate_stock calls per 30s cap."""
    while True:
        now = _monotonic()
        request_times[:] = [
            requested_at for requested_at in request_times
            if now - requested_at < _PLATE_STOCK_REQUEST_WINDOW_SECONDS
        ]
        if len(request_times) < _PLATE_STOCK_REQUEST_LIMIT:
            request_times.append(_monotonic())
            return
        _sleep(max(
            0.0,
            _PLATE_STOCK_REQUEST_WINDOW_SECONDS - (now - request_times[0]),
        ))


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


def _session_date_token(value: Any) -> str:
    raw = str(value).strip()
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date() if re.fullmatch(r"20\d{6}", raw) else date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("invalid US session date") from error
    return parsed.strftime("%Y%m%d")


def _date_from_update_time(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).date().strftime("%Y%m%d")
    except ValueError:
        return None


def _empty_row(mapping: Mapping[str, str | None], reason: str, *, code: str | None = None) -> dict[str, Any]:
    return {
        "label": mapping["label"],
        "metric_kind": "OFFICIAL_BOARD",
        "market": "US",
        "plate_type": mapping["plate_type"],
        "expected_board_name": mapping["plate_name"],
        "board_name": mapping["plate_name"] if code else None,
        "board_code": code,
        "update_time": None,
        "session_date": None,
        "timezone": FUTU_SESSION_TIMEZONE,
        "last": None,
        "previous_close": None,
        "change_pct": None,
        "plate_valid": None,
        "rise_count": None,
        "fall_count": None,
        "equal_count": None,
        "member_count": None,
        "relation_constituents": [],
        "membership_status": "CANNOT_CONFIRM",
        "membership_sha256": "",
        "source_response_sha256": "",
        "status": "CANNOT_CONFIRM",
        "cannot_confirm": [reason],
    }


def empty_futu_board_snapshot(session_date: str, reason: str) -> dict[str, Any]:
    requested_date = _session_date_token(session_date)
    return {
        "schema_version": FUTU_INDUSTRY_SCHEMA_VERSION,
        "status": "CANNOT_CONFIRM",
        "provider": FUTU_PROVIDER,
        "market": "US",
        "timezone": FUTU_SESSION_TIMEZONE,
        "capture_session_date": requested_date,
        "source_response_sha256": "",
        "rows": [_empty_row(mapping, reason) for mapping in FUTU_BOARD_MAP],
        "cannot_confirm": [reason],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def validate_futu_board_snapshot(value: Any, *, expected_session_date: str | None = None) -> dict[str, Any]:
    """Validate the persisted Futu board contract without promoting gaps."""
    if not isinstance(value, Mapping):
        raise ValueError("invalid Futu board snapshot")
    required = {
        "schema_version", "status", "provider", "market", "timezone",
        "capture_session_date", "source_response_sha256", "rows", "cannot_confirm",
        "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
    }
    if not required.issubset(value):
        raise ValueError("invalid Futu board snapshot fields")
    if value.get("schema_version") != FUTU_INDUSTRY_SCHEMA_VERSION or value.get("provider") != FUTU_PROVIDER:
        raise ValueError("invalid Futu board snapshot identity")
    if value.get("market") != "US" or value.get("timezone") != FUTU_SESSION_TIMEZONE:
        raise ValueError("invalid Futu board snapshot market or timezone")
    session_date = _session_date_token(value.get("capture_session_date"))
    if expected_session_date is not None and session_date != _session_date_token(expected_session_date):
        raise ValueError("Futu board snapshot session date mismatch")
    digest = value.get("source_response_sha256")
    if not isinstance(digest, str) or (digest and not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid Futu board snapshot source hash")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != len(FUTU_BOARD_MAP):
        raise ValueError("Futu board snapshot must contain the 24 configured themes")
    if not isinstance(value.get("cannot_confirm"), list) or any(not isinstance(item, str) or not item for item in value["cannot_confirm"]):
        raise ValueError("invalid Futu board snapshot cannot_confirm")
    if value.get("RESEARCH_ONLY") is not True or value.get("production_allowed") is not False or value.get("buy_gate_updated") is not False or value.get("orders_sent") is not False:
        raise ValueError("unsafe Futu board snapshot safety flags")

    ready_count = 0
    row_reasons: set[str] = set()
    legacy_unmapped_military = _empty_row(
        {"label": "军工", "plate_type": None, "plate_name": None},
        "FUTU_BOARD_MATCH_UNCONFIRMED",
    )
    for row, mapping in zip(rows, FUTU_BOARD_MAP):
        if not isinstance(row, Mapping):
            raise ValueError("invalid Futu board snapshot row")
        mapping_matches = all(row.get(key) == expected for key, expected in {
            "label": mapping["label"],
            "metric_kind": "OFFICIAL_BOARD",
            "market": "US",
            "plate_type": mapping["plate_type"],
            "expected_board_name": mapping["plate_name"],
            "timezone": FUTU_SESSION_TIMEZONE,
        }.items())
        # Preserve read compatibility for the exact historical unknown row;
        # it remains CANNOT_CONFIRM and is never promoted to the new mapping.
        legacy_placeholder = (
            mapping["label"] == "军工"
            and mapping["plate_type"] == "INDUSTRY"
            and mapping["plate_name"] == "航空航天与国防"
            and dict(row) == legacy_unmapped_military
        )
        if not mapping_matches and not legacy_placeholder:
            raise ValueError("Futu board snapshot theme mapping mismatch")
        status = row.get("status")
        if status not in {"READY", "CANNOT_CONFIRM"}:
            raise ValueError("invalid Futu board row status")
        reasons = row.get("cannot_confirm")
        if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons):
            raise ValueError("invalid Futu board row cannot_confirm")
        row_reasons.update(reasons)
        code = row.get("board_code")
        if code is not None and (not isinstance(code, str) or not _US_CODE.fullmatch(code)):
            raise ValueError("invalid Futu board code")
        if row.get("board_name") is not None and row.get("board_name") != mapping["plate_name"]:
            raise ValueError("Futu board name does not match exact configured name")
        row_date = row.get("session_date")
        if row_date is not None:
            row_date = _session_date_token(row_date)
        if row.get("plate_valid") not in {True, False, None}:
            raise ValueError("invalid Futu plate_valid")
        counts = [row.get("rise_count"), row.get("fall_count"), row.get("equal_count")]
        if row.get("plate_valid") is not True and any(count is not None for count in counts):
            raise ValueError("invalid Futu board counts when plate_valid is not true")
        if any(count is not None and _count(count) != count for count in counts):
            raise ValueError("invalid Futu board breadth count")
        if row.get("last") is not None and _positive_number(row.get("last")) is None:
            raise ValueError("invalid Futu board last price")
        if row.get("previous_close") is not None and _positive_number(row.get("previous_close")) is None:
            raise ValueError("invalid Futu board previous close")
        change = row.get("change_pct")
        if change is not None and (isinstance(change, bool) or not isinstance(change, (int, float)) or not math.isfinite(float(change))):
            raise ValueError("invalid Futu board change")
        if status == "READY":
            ready_count += 1
            if (
                not code or row.get("board_name") != mapping["plate_name"]
                or row_date != session_date or row.get("plate_valid") is not True
                or any(_count(count) is None for count in counts)
                or _positive_number(row.get("last")) is None
                or _positive_number(row.get("previous_close")) is None
                or not isinstance(change, (int, float)) or isinstance(change, bool)
                or round((float(row["last"]) - float(row["previous_close"])) / float(row["previous_close"]) * 100, 6) != round(float(change), 6)
            ):
                raise ValueError("incomplete Futu board row marked READY")
        elif change is not None:
            raise ValueError("CANNOT_CONFIRM Futu board row has a sector change value")
        membership_status = row.get("membership_status")
        if membership_status not in {"READY", "CANNOT_CONFIRM"}:
            raise ValueError("invalid Futu membership status")
        member_count = row.get("member_count")
        if member_count is not None and _count(member_count) != member_count:
            raise ValueError("invalid Futu membership count")
        relation_symbols = row.get("relation_constituents")
        if (
            not isinstance(relation_symbols, list)
            or any(not isinstance(symbol, str) or symbol not in _RELATION_SYMBOLS for symbol in relation_symbols)
            or len(relation_symbols) != len(set(relation_symbols))
        ):
            raise ValueError("invalid Futu relation constituent symbols")
        for hash_field in ("membership_sha256", "source_response_sha256"):
            hash_value = row.get(hash_field)
            if not isinstance(hash_value, str) or (hash_value and not re.fullmatch(r"[0-9a-f]{64}", hash_value)):
                raise ValueError("invalid Futu board row hash")
    expected_status = "READY" if ready_count == len(rows) else "PARTIAL" if ready_count else "CANNOT_CONFIRM"
    if value.get("status") != expected_status:
        raise ValueError("invalid aggregate Futu board snapshot status")
    if expected_status != "READY" and not value.get("cannot_confirm"):
        raise ValueError("incomplete Futu board snapshot requires cannot_confirm")
    if not row_reasons.issubset(set(value.get("cannot_confirm") or [])):
        raise ValueError("Futu board snapshot omitted row reasons")
    return dict(value)


def build_futu_board_snapshot(
    session_date: str,
    *,
    quote_context: Any,
    market: Any = "US",
    industry_plate: Any = "INDUSTRY",
    concept_plate: Any = "CONCEPT",
) -> dict[str, Any]:
    """Capture exact Futu board rows and only the reviewed-relation symbols.

    Futu board ``update_time`` is interpreted in America/New_York as specified
    by the provider. A latest value from another session is retained as
    evidence but never projected as the requested session's metric.
    """
    requested_date = _session_date_token(session_date)
    plate_args = {"INDUSTRY": industry_plate, "CONCEPT": concept_plate}
    plate_rows: dict[str, list[dict[str, Any]]] = {}
    discovery_errors: dict[str, str] = {}
    for plate_type, plate_enum in plate_args.items():
        try:
            ret, frame = quote_context.get_plate_list(market, plate_enum)
            rows = _response(ret, frame)
            if ret != 0:
                discovery_errors[plate_type] = f"FUTU_PLATE_LIST_FAILED:{plate_type}:{ret}"
            plate_rows[plate_type] = rows
        except Exception as error:  # preserve failure reason at this source boundary
            discovery_errors[plate_type] = f"FUTU_PLATE_LIST_FAILED:{plate_type}:{type(error).__name__}"
            plate_rows[plate_type] = []

    resolved: list[tuple[Mapping[str, str | None], str | None, str | None]] = []
    codes: list[str] = []
    rows: list[dict[str, Any]] = []
    for mapping in FUTU_BOARD_MAP:
        if not mapping["plate_type"] or not mapping["plate_name"]:
            rows.append(_empty_row(mapping, "FUTU_BOARD_MATCH_UNCONFIRMED"))
            resolved.append((mapping, None, None))
            continue
        candidates = [
            row for row in plate_rows.get(mapping["plate_type"], [])
            if row.get("plate_name") == mapping["plate_name"]
            and isinstance(row.get("code"), str)
            and _US_CODE.fullmatch(row["code"])
        ]
        if len(candidates) != 1:
            reason = discovery_errors.get(mapping["plate_type"], "FUTU_BOARD_MATCH_MISSING" if not candidates else "FUTU_BOARD_MATCH_AMBIGUOUS")
            rows.append(_empty_row(mapping, reason))
            resolved.append((mapping, None, None))
            continue
        code = candidates[0]["code"]
        rows.append(_empty_row(mapping, "FUTU_BOARD_SNAPSHOT_NOT_RETURNED", code=code))
        resolved.append((mapping, code, None))
        codes.append(code)

    board_records: dict[str, dict[str, Any]] = {}
    snapshot_error = ""
    if codes:
        try:
            ret, frame = quote_context.get_market_snapshot(codes)
            if ret == 0:
                for record in _records(frame):
                    code = record.get("code")
                    if isinstance(code, str) and code in codes and code not in board_records:
                        board_records[code] = record
            else:
                snapshot_error = f"FUTU_BOARD_SNAPSHOT_FAILED:{ret}"
        except Exception as error:
            snapshot_error = f"FUTU_BOARD_SNAPSHOT_FAILED:{type(error).__name__}"

    board_response_sha = _canonical_sha256([board_records[key] for key in sorted(board_records)])
    membership_records: dict[str, dict[str, Any]] = {}
    membership_request_times: list[float] = []
    for code in codes:
        _wait_for_plate_stock_request(membership_request_times)
        try:
            ret, frame = quote_context.get_plate_stock(code)
            members = _response(ret, frame)
            if ret == 0:
                symbols = sorted({
                    match.group(1)
                    for row in members
                    if isinstance(row.get("code"), str)
                    if (match := _US_CODE.fullmatch(row["code"]))
                    if match.group(1) in _RELATION_SYMBOLS
                })
                membership_records[code] = {
                    "member_count": len(members),
                    "relation_constituents": symbols,
                    "membership_status": "READY",
                    "membership_sha256": _canonical_sha256(members),
                }
            else:
                membership_records[code] = {
                    "member_count": None,
                    "relation_constituents": [],
                    "membership_status": "CANNOT_CONFIRM",
                    "membership_sha256": "",
                }
        except Exception:
            membership_records[code] = {
                "member_count": None,
                "relation_constituents": [],
                "membership_status": "CANNOT_CONFIRM",
                "membership_sha256": "",
            }

    projected_rows: list[dict[str, Any]] = []
    for row, (mapping, code, _) in zip(rows, resolved):
        if code is None:
            projected_rows.append(row)
            continue
        source = board_records.get(code)
        if source is None:
            if snapshot_error:
                row["cannot_confirm"] = [snapshot_error]
            projected_rows.append(row)
            continue
        raw_time = source.get("update_time")
        source_date = _date_from_update_time(raw_time)
        last = _positive_number(source.get("last_price"))
        previous_close = _positive_number(source.get("prev_close_price"))
        plate_valid = source.get("plate_valid") if isinstance(source.get("plate_valid"), bool) else None
        rise = _count(source.get("plate_raise_count"))
        fall = _count(source.get("plate_fall_count"))
        equal = _count(source.get("plate_equal_count"))
        reasons: list[str] = []
        if source_date is None:
            reasons.append("FUTU_BOARD_UPDATE_TIME_INVALID")
        elif source_date != requested_date:
            reasons.append("FUTU_BOARD_SESSION_DATE_MISMATCH")
        if plate_valid is not True:
            reasons.append("FUTU_BOARD_INVALID_OR_MISSING_PLATE_VALID")
        if last is None or previous_close is None:
            reasons.append("FUTU_BOARD_PRICE_MISSING_OR_INVALID")
        if plate_valid is True and None in (rise, fall, equal):
            reasons.append("FUTU_BOARD_BREADTH_FIELDS_MISSING_OR_INVALID")
        valid = not reasons
        membership = membership_records.get(code, {})
        row.update({
            "update_time": raw_time if isinstance(raw_time, str) else None,
            "session_date": source_date,
            "last": last,
            "previous_close": previous_close,
            "change_pct": round((last - previous_close) / previous_close * 100, 6) if valid and previous_close else None,
            "plate_valid": plate_valid,
            "rise_count": rise if plate_valid is True else None,
            "fall_count": fall if plate_valid is True else None,
            "equal_count": equal if plate_valid is True else None,
            **membership,
            "source_response_sha256": _canonical_sha256({"plate": source, "snapshot_sha256": board_response_sha}),
            "status": "READY" if valid else "CANNOT_CONFIRM",
            "cannot_confirm": reasons,
        })
        projected_rows.append(row)

    reasons = sorted({reason for row in projected_rows for reason in row["cannot_confirm"]})
    ready_count = sum(row["status"] == "READY" for row in projected_rows)
    status = "READY" if ready_count == len(projected_rows) else "PARTIAL" if ready_count else "CANNOT_CONFIRM"
    source_material = {
        "plate_lists": {key: plate_rows[key] for key in sorted(plate_rows)},
        "board_snapshots": board_records,
        "board_snapshot_sha256": board_response_sha,
        "membership": membership_records,
    }
    return {
        "schema_version": FUTU_INDUSTRY_SCHEMA_VERSION,
        "status": status,
        "provider": FUTU_PROVIDER,
        "market": "US",
        "timezone": FUTU_SESSION_TIMEZONE,
        "capture_session_date": requested_date,
        "source_response_sha256": _canonical_sha256(source_material),
        "rows": projected_rows,
        "cannot_confirm": reasons,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def capture_futu_board_snapshot(session_date: str) -> dict[str, Any]:
    """Open the configured local OpenD connection, capture, and always close."""
    try:
        from futu import Market, OpenQuoteContext, Plate
    except ImportError as error:
        return empty_futu_board_snapshot(session_date, f"FUTU_SDK_UNAVAILABLE:{type(error).__name__}")
    context = None
    try:
        context = OpenQuoteContext(host="127.0.0.1", port=11111)
        return build_futu_board_snapshot(
            session_date,
            quote_context=context,
            market=Market.US,
            industry_plate=Plate.INDUSTRY,
            concept_plate=Plate.CONCEPT,
        )
    except Exception as error:
        return empty_futu_board_snapshot(session_date, f"FUTU_OPEND_UNAVAILABLE:{type(error).__name__}")
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


