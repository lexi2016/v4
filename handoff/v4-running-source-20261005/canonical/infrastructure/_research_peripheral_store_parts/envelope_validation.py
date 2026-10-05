"""infrastructure.research_peripheral_store: envelope_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_research_peripheral_body(_v4_scope, /, payload, *, expected_trade_date, expected_source):
    required = {
        "schema_version",
        "trade_date",
        "source",
        "status",
        "source_url",
        "fetched_at",
        "raw_item_count",
        "item_count",
        "overview",
        "details",
        "items",
        "cannot_confirm",
        "write_policy",
        "recommendation_status",
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    }

    optional = {
        "feed_receipts",
        "us_session_captures",
        "capture_origin",
        "original_time_capture",
        "market_snapshot",
        "market_snapshot_status",
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    }

    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) or not required.issubset(payload) or _v4_global(_v4_scope, 'set')(payload) - required - optional:
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral fields")

    if payload.get("schema_version") != _v4_global(_v4_scope, '_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral schema")

    trade_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(payload.get("trade_date") or ""))

    source = _v4_global(_v4_scope, '_source')(_v4_global(_v4_scope, 'str')(payload.get("source") or ""))

    if expected_trade_date is not None and trade_date != _v4_global(_v4_scope, '_date')(expected_trade_date):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral trade-date mismatch")

    if expected_source is not None and source != _v4_global(_v4_scope, '_source')(expected_source):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral source mismatch")

    if payload.get("status") not in _v4_global(_v4_scope, '_STATUSES'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral status")

    if not _v4_global(_v4_scope, 'isinstance')(payload.get("source_url"), _v4_global(_v4_scope, 'str')) or not payload["source_url"].strip():
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral source_url is missing")

    _v4_global(_v4_scope, '_aware_timestamp')(payload.get("fetched_at"), "fetched_at")

    for field in ("raw_item_count", "item_count"):
        value = payload.get(field)
        if _v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral {field}")

    overview = _v4_global(_v4_scope, '_validate_item_list')(payload.get("overview"), "overview")

    details = _v4_global(_v4_scope, '_validate_item_list')(payload.get("details"), "details")

    items = _v4_global(_v4_scope, '_validate_item_list')(payload.get("items"), "items")

    if source == "external_finance":
        if items or payload["item_count"] != _v4_global(_v4_scope, 'len')(details) or _v4_global(_v4_scope, 'len')(overview) > _v4_global(_v4_scope, 'len')(details):
            raise _v4_global(_v4_scope, 'ValueError')("invalid external finance projection")
    else:
        if overview or details or payload["item_count"] != _v4_global(_v4_scope, 'len')(items):
            raise _v4_global(_v4_scope, 'ValueError')("invalid AI news projection")

    if payload["raw_item_count"] < payload["item_count"]:
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral item count mismatch")

    _v4_global(_v4_scope, '_string_list')(payload.get("cannot_confirm"), "cannot_confirm")

    if "feed_receipts" in payload:
        feed_receipts = payload.get("feed_receipts")
        if not _v4_global(_v4_scope, 'isinstance')(feed_receipts, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral feed_receipts")
        for receipt in feed_receipts:
            if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral feed receipt")
            if not _v4_global(_v4_scope, 'isinstance')(receipt.get("feed_id"), _v4_global(_v4_scope, 'str')) or not receipt["feed_id"].strip():
                raise _v4_global(_v4_scope, 'ValueError')("research peripheral feed receipt id is missing")
            if not _v4_global(_v4_scope, 'isinstance')(receipt.get("url"), _v4_global(_v4_scope, 'str')) or not receipt["url"].strip():
                raise _v4_global(_v4_scope, 'ValueError')("research peripheral feed receipt url is missing")
            elapsed = receipt.get("elapsed_ms")
            if _v4_global(_v4_scope, 'type')(elapsed) is not _v4_global(_v4_scope, 'int') or elapsed < 0:
                raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral feed receipt elapsed_ms")
            status = receipt.get("http_status")
            if status is not None and (_v4_global(_v4_scope, 'type')(status) is not _v4_global(_v4_scope, 'int') or status < 100 or status > 599):
                raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral feed receipt http_status")
            if receipt.get("error") is not None and not _v4_global(_v4_scope, 'isinstance')(receipt.get("error"), _v4_global(_v4_scope, 'str')):
                raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral feed receipt error")
            for key in ("proxy_used", "fallback_used"):
                if _v4_global(_v4_scope, 'type')(receipt.get(key)) is not _v4_global(_v4_scope, 'bool'):
                    raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral feed receipt {key}")
    if 'us_session_captures' in payload:
        _b04_validate_us_session_captures(_v4_scope, payload, trade_date, source)
    if 'market_snapshot' in payload:
        _b04_validate_market_snapshot_capture_binding(_v4_scope, payload, trade_date, source)
    fixed = {
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    if _v4_global(_v4_scope, 'any')(payload.get(key) != value for key, value in fixed.items()):
        raise _v4_global(_v4_scope, 'ValueError')("unsafe research peripheral boundary")

    if payload["status"] == "READY" and payload["item_count"] == 0:
        raise _v4_global(_v4_scope, 'ValueError')("empty research peripheral must be READY_EMPTY or CANNOT_CONFIRM")

    if payload["status"] == "READY_EMPTY" and payload["item_count"] != 0:
        raise _v4_global(_v4_scope, 'ValueError')("non-empty research peripheral cannot be READY_EMPTY")

    return trade_date, source

def _b04_validate_us_session_captures(_v4_scope, payload, trade_date, source):
    captures = _v4_global(_v4_scope, '_validate_us_session_captures')(payload["us_session_captures"])

    if not captures and _v4_global(_v4_scope, 'any')(
        key in payload for key in ("capture_origin", "original_time_capture")
    ):
        raise _v4_global(_v4_scope, 'ValueError')("capture identity requires at least one capture")

    if "capture_origin" in payload and payload["capture_origin"] not in _v4_global(_v4_scope, '_CAPTURE_ORIGINS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral capture_origin")

    if "original_time_capture" in payload and _v4_global(_v4_scope, 'type')(payload["original_time_capture"]) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral original_time_capture must be boolean")

    if "late" in payload and _v4_global(_v4_scope, 'type')(payload["late"]) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral late must be boolean")

    if "capture_mode" in payload and (
        not _v4_global(_v4_scope, 'isinstance')(payload["capture_mode"], _v4_global(_v4_scope, 'str'))
        or not payload["capture_mode"].strip()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral capture_mode")

    for field in ("reason", "capture_reason"):
        if field in payload and (
            not _v4_global(_v4_scope, 'isinstance')(payload[field], _v4_global(_v4_scope, 'str')) or not payload[field].strip()
        ):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral {field}")

    if payload.get("capture_mode") == _v4_global(_v4_scope, '_LATE_CAPTURE_MODE') and payload.get("late") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("late capture payload mode requires late identity")

    late_captures = [row for row in captures if row.get("late") is True]

    if late_captures:
        if payload.get("late") is not True:
            raise _v4_global(_v4_scope, 'ValueError')("late capture payload identity is missing")
        if payload.get("capture_mode") != _v4_global(_v4_scope, '_LATE_CAPTURE_MODE'):
            raise _v4_global(_v4_scope, 'ValueError')("late capture payload mode mismatch")
        latest_late = _v4_global(_v4_scope, 'max')(
            late_captures,
            key=lambda row: _v4_global(_v4_scope, 'str')(row.get("captured_at") or ""),
        )
        expected_late_reason = (
            _v4_global(_v4_scope, '_MANUAL_LATE_CAPTURE_REASON')
            if latest_late.get("capture_origin") == "MANUAL_RECOVERY"
            else _v4_global(_v4_scope, '_LATE_CAPTURE_REASON')
        )
        if payload.get("reason") != expected_late_reason:
            raise _v4_global(_v4_scope, 'ValueError')("late capture payload reason mismatch")
        if payload.get("capture_reason") not in (None, expected_late_reason):
            raise _v4_global(_v4_scope, 'ValueError')("late capture payload capture_reason mismatch")
    elif payload.get("late") is True:
        raise _v4_global(_v4_scope, 'ValueError')("late capture payload has no late capture")

    fetched_at = _v4_global(_v4_scope, '_parse_aware_timestamp')(payload["fetched_at"], "fetched_at")

    for capture in captures:
        capture_at = _v4_global(_v4_scope, '_parse_aware_timestamp')(capture["captured_at"], "captured_at")
        if capture_at > fetched_at:
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral captured_at is after fetched_at")

    if "capture_origin" in payload and payload["capture_origin"] == "HISTORICAL_BACKFILL":
        if payload.get("original_time_capture") is not False or _v4_global(_v4_scope, 'any')(
            row["capture_origin"] != "HISTORICAL_BACKFILL" or row["original_time_capture"] is not False
            for row in captures
        ):
            raise _v4_global(_v4_scope, 'ValueError')("historical backfill payload identity is unsafe")

    if "capture_origin" in payload and payload["capture_origin"] == "ORIGINAL_TIME_CAPTURE":
        if payload.get("original_time_capture") is not True or _v4_global(_v4_scope, 'any')(
            row["capture_origin"] != "ORIGINAL_TIME_CAPTURE" or row["original_time_capture"] is not True
            for row in captures
        ):
            raise _v4_global(_v4_scope, 'ValueError')("live capture identity is unsafe")

    if "capture_origin" in payload and payload["capture_origin"] == "MANUAL_RECOVERY":
        if payload.get("original_time_capture") is not False or not captures or _v4_global(_v4_scope, 'any')(
            row["capture_origin"] != "MANUAL_RECOVERY"
            or row["original_time_capture"] is not False
            or row.get("late") is not True
            for row in captures
        ):
            raise _v4_global(_v4_scope, 'ValueError')("manual recovery payload identity is unsafe")


def _b04_validate_market_snapshot_capture_binding(_v4_scope, payload, trade_date, source):
    snapshot = _v4_global(_v4_scope, '_validate_market_snapshot')(payload["market_snapshot"])

    if payload.get("market_snapshot_status") != snapshot.get("status"):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot_status mismatch")

    if (
        snapshot.get("capture_phase") == "POST_CLOSE"
        and snapshot.get("status") != "READY"
        and payload.get("status") != "CANNOT_CONFIRM"
    ):
        raise _v4_global(_v4_scope, 'ValueError')(
            "research peripheral POST_CLOSE market_snapshot failure must be CANNOT_CONFIRM"
        )

    if _v4_global(_v4_scope, '_parse_aware_timestamp')(snapshot["captured_at"], "market_snapshot.captured_at") > _v4_global(_v4_scope, '_parse_aware_timestamp')(
        payload["fetched_at"], "fetched_at"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot captured_at is after fetched_at")

    captures = payload.get("us_session_captures") or []

    snapshot_late = _v4_global(_v4_scope, '_is_late_capture_identity')(snapshot)

    matching_capture = _v4_global(_v4_scope, 'next')(
        (
            row
            for row in captures
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
            and row.get("us_session_date") == snapshot.get("capture_session_date")
            and row.get("capture_phase") == snapshot.get("capture_phase")
            and _v4_global(_v4_scope, '_is_late_capture_identity')(row) == snapshot_late
        ),
        None,
    )

    if matching_capture is None:
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot capture identity missing")

    snapshot_at = _v4_global(_v4_scope, '_parse_aware_timestamp')(
        snapshot["captured_at"], "market_snapshot.captured_at"
    )

    if _v4_global(_v4_scope, '_is_late_capture_identity')(matching_capture):
        capture_start = _v4_global(_v4_scope, '_parse_aware_timestamp')(
            matching_capture["allowed_recovery_window_start"],
            "allowed_recovery_window_start",
        )
        capture_end = _v4_global(_v4_scope, '_parse_aware_timestamp')(
            matching_capture["allowed_recovery_window_end"],
            "allowed_recovery_window_end",
        )
    else:
        capture_start = _v4_global(_v4_scope, '_parse_aware_timestamp')(
            matching_capture["capture_window_start"], "capture_window_start"
        )
        capture_end = _v4_global(_v4_scope, '_parse_aware_timestamp')(
            matching_capture["capture_window_end"], "capture_window_end"
        )

    capture_at = _v4_global(_v4_scope, '_parse_aware_timestamp')(
        matching_capture["captured_at"], "captured_at"
    )

    if (
        matching_capture.get("capture_phase") != "HISTORICAL_BACKFILL"
        and not (capture_start <= snapshot_at < capture_end)
    ) or snapshot_at > capture_at:
        raise _v4_global(_v4_scope, 'ValueError')("research peripheral market_snapshot capture timestamp mismatch")
