"""V3.5-owned exact-date storage for public research peripherals.

The store is intentionally independent from the research archive and from all
legacy V3/assistant paths.  Each source has its own immutable payload, receipt,
and manifest entry so that one source can be absent without being inferred from
the other source.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.owned_path import resolve_owned_path


PERIPHERAL_SOURCES = frozenset({"external_finance", "ai_news"})
_STATUSES = frozenset({"READY", "READY_EMPTY", "CANNOT_CONFIRM"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_RELATIVE = "research/peripherals/manifest.json"
_SCHEMA_VERSION = "v3_5.research_peripheral.v1"
_RECEIPT_SCHEMA_VERSION = "v3_5.research_peripheral_receipt.v1"
_LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS = frozenset(
    {
        "market_snapshot_captured_at",
        "market_snapshot_source_response_sha256",
    }
)
_BACKFILL_RECEIPT_SCHEMA_VERSION = "v3_5.research_peripheral_backfill_receipt.v1"
_CAPTURE_PHASES = frozenset({"PRE_OPEN", "POST_CLOSE", "HISTORICAL_BACKFILL"})
_CAPTURE_ORIGINS = frozenset({"ORIGINAL_TIME_CAPTURE", "HISTORICAL_BACKFILL", "MANUAL_RECOVERY", "MIXED"})
_US_SESSION_TZ = ZoneInfo("America/New_York")
_MARKET_SNAPSHOT_SCHEMA_VERSION = "v3_5.us_market_snapshot.v1"
_MARKET_SNAPSHOT_STATUSES = frozenset({"READY", "PARTIAL", "CANNOT_CONFIRM"})
_MARKET_SNAPSHOT_DIRECTIONS = frozenset({"UP", "DOWN", "FLAT", "CANNOT_CONFIRM"})
_MARKET_SNAPSHOT_THEME_COUNT = 24
_MARKET_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1"
_CANONICAL_THEME_GROUP = "GLOBAL_INDUSTRY"
# Keep the storage boundary independent from ops.us_market_digest.  This
# frozen tuple mirrors the producer contract and prevents a producer-side
# mapping edit from silently changing already materialized artifacts.
CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP: tuple[dict[str, Any], ...] = (
    {"label": "AI算力", "group": _CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("NVDA", "AVGO", "AMD")},
    {"label": "CPO", "group": _CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("COHR", "LITE", "CIEN")},
    {"label": "半导体", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("SOXX",)},
    {"label": "存储", "group": _CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("MU", "WDC", "STX")},
    {"label": "数据中心", "group": _CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("VRT", "DLR", "EQIX")},
    {"label": "云计算", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("CLOU",)},
    {"label": "商业航天", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ARKX",)},
    {"label": "卫星", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("UFO",)},
    {"label": "机器人", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("BOTZ",)},
    {"label": "自动驾驶", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("DRIV",)},
    {"label": "核电", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("NLR",)},
    {"label": "电网", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("GRID",)},
    {"label": "军工", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ITA",)},
    {"label": "新能源", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ICLN",)},
    {"label": "光伏", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("TAN",)},
    {"label": "锂电池", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("LIT",)},
    {"label": "石油", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("XLE",)},
    {"label": "天然气", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("FCG",)},
    {"label": "铜/有色", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("COPX",)},
    {"label": "黄金", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("GLD",)},
    {"label": "银行金融", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("KBE",)},
    {"label": "生物医药", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("XBI",)},
    {"label": "消费", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_basket_proxy", "proxy_symbols": ("XLY", "XLP")},
    {"label": "稀土", "group": _CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("REMX",)},
)
_CANONICAL_SYMBOLS = frozenset(
    symbol
    for mapping in CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP
    for symbol in mapping["proxy_symbols"]
)
_QUOTE_CHANGE_TOLERANCE = 1e-3
_US_SESSION_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$")
_LATE_CAPTURE_MODE = "CONTROLLED_LATE_POST_CLOSE"
_LATE_CAPTURE_REASON = "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY"
_MANUAL_LATE_CAPTURE_REASON = "MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION"


def _is_late_capture_identity(value: Any) -> bool:
    """Classify either explicit late marker as a late capture identity."""
    return isinstance(value, Mapping) and (
        value.get("late") is True
        or value.get("capture_mode") == _LATE_CAPTURE_MODE
    )


def _source(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in PERIPHERAL_SOURCES:
        raise ValueError("research peripheral source must be external_finance or ai_news")
    return normalized


def _aware_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"research peripheral {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid research peripheral {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"research peripheral {field} must include timezone")


def _parse_aware_timestamp(value: Any, field: str) -> datetime:
    _aware_timestamp(value, field)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _timestamps_equal(left: Any, right: Any, *, left_field: str, right_field: str) -> bool:
    return _parse_aware_timestamp(left, left_field) == _parse_aware_timestamp(
        right, right_field
    )


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid research peripheral {field}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"invalid research peripheral {field}")
    return number


def _canonical_row_shape(row: Mapping[str, Any], index: int) -> None:
    mapping = CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP[index]
    if (
        row.get("label") != mapping["label"]
        or row.get("group") != mapping["group"]
        or row.get("mapping_type") != mapping["mapping_type"]
        or row.get("proxy_symbols") != list(mapping["proxy_symbols"])
    ):
        raise ValueError("research peripheral market_snapshot canonical mapping mismatch")


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid research peripheral {field}")
    if value != sorted(set(value)):
        raise ValueError(f"research peripheral {field} must be sorted and unique")
    return value


def _validate_item_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"invalid research peripheral {field}")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"invalid research peripheral {field} row")
        normalized = dict(row)
        if normalized.get("recommendation_status") not in (None, "RESEARCH_ONLY"):
            raise ValueError("unsafe research peripheral recommendation")
        for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            if key in normalized and normalized[key] is not False:
                raise ValueError("unsafe research peripheral safety flag")
        rows.append(normalized)
    return rows


def _validate_us_session_captures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("invalid research peripheral us_session_captures")
    captures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    required = {
        "us_session_date",
        "capture_phase",
        "session_timezone",
        "capture_window_start",
        "capture_window_end",
        "capture_id",
        "run_id",
        "captured_at",
        "capture_origin",
        "original_time_capture",
    }
    for value_row in value:
        if not isinstance(value_row, Mapping) or not required.issubset(value_row):
            raise ValueError("invalid research peripheral capture fields")
        row = dict(value_row)
        us_session_date = row.get("us_session_date")
        try:
            _date(str(us_session_date))
        except ValueError as error:
            raise ValueError("invalid research peripheral us_session_date") from error
        if row.get("capture_phase") not in _CAPTURE_PHASES:
            raise ValueError("invalid research peripheral capture_phase")
        if row.get("session_timezone") != "America/New_York":
            raise ValueError("research peripheral session_timezone must be America/New_York")
        _aware_timestamp(row.get("capture_window_start"), "capture_window_start")
        _aware_timestamp(row.get("capture_window_end"), "capture_window_end")
        captured_at = _parse_aware_timestamp(row.get("captured_at"), "captured_at")
        start = datetime.fromisoformat(str(row["capture_window_start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(row["capture_window_end"]).replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("research peripheral capture window must be increasing")
        session_day = datetime.strptime(str(us_session_date), "%Y%m%d").date()
        phase = row["capture_phase"]
        capture_origin = row.get("capture_origin")
        original_time_capture = row.get("original_time_capture")
        if capture_origin not in _CAPTURE_ORIGINS:
            raise ValueError("invalid research peripheral capture_origin")
        if type(original_time_capture) is not bool:
            raise ValueError("research peripheral original_time_capture must be boolean")
        manual_late = capture_origin == "MANUAL_RECOVERY"
        if manual_late and (
            phase != "POST_CLOSE" or original_time_capture is not False
        ):
            raise ValueError("manual recovery capture identity is unsafe")
        if phase == "PRE_OPEN":
            expected_start = datetime.combine(session_day, time(9, 0), tzinfo=_US_SESSION_TZ)
            expected_end = datetime.combine(session_day, time(9, 5), tzinfo=_US_SESSION_TZ)
        elif phase == "POST_CLOSE":
            expected_start = datetime.combine(session_day, time(16, 15), tzinfo=_US_SESSION_TZ)
            expected_end = datetime.combine(session_day, time(16, 20), tzinfo=_US_SESSION_TZ)
        else:
            expected_start = datetime.combine(session_day, time.min, tzinfo=_US_SESSION_TZ)
            expected_end = datetime.combine(session_day + timedelta(days=1), time.min, tzinfo=_US_SESSION_TZ)
        if start.astimezone(_US_SESSION_TZ) != expected_start or end.astimezone(_US_SESSION_TZ) != expected_end:
            raise ValueError("research peripheral capture window timezone or phase mismatch")
        late = row.get("late", False)
        if type(late) is not bool:
            raise ValueError("research peripheral late must be boolean")
        if not late and row.get("capture_mode") == _LATE_CAPTURE_MODE:
            raise ValueError("late capture mode requires late identity")
        if phase in {"PRE_OPEN", "POST_CLOSE"}:
            local_capture = captured_at.astimezone(_US_SESSION_TZ)
            if late:
                if phase != "POST_CLOSE":
                    raise ValueError("late capture must be POST_CLOSE")
                if row.get("capture_mode") != _LATE_CAPTURE_MODE:
                    raise ValueError("invalid research peripheral late capture_mode")
                expected_reason = (
                    _MANUAL_LATE_CAPTURE_REASON if manual_late else _LATE_CAPTURE_REASON
                )
                if row.get("reason") != expected_reason:
                    raise ValueError("invalid research peripheral late capture reason")
                if row.get("capture_reason") not in (None, expected_reason):
                    raise ValueError("invalid research peripheral late capture_reason")
                for field in (
                    "natural_capture_window_start",
                    "natural_capture_window_end",
                    "allowed_recovery_window_start",
                    "allowed_recovery_window_end",
                ):
                    _aware_timestamp(row.get(field), field)
                natural_start = _parse_aware_timestamp(
                    row["natural_capture_window_start"],
                    "natural_capture_window_start",
                )
                natural_end = _parse_aware_timestamp(
                    row["natural_capture_window_end"],
                    "natural_capture_window_end",
                )
                allowed_start = _parse_aware_timestamp(
                    row["allowed_recovery_window_start"],
                    "allowed_recovery_window_start",
                )
                allowed_end = _parse_aware_timestamp(
                    row["allowed_recovery_window_end"],
                    "allowed_recovery_window_end",
                )
                if natural_start != expected_start or natural_end != expected_end:
                    raise ValueError("late capture natural window mismatch")
                expected_recovery_end = expected_start + timedelta(hours=24)
                if (
                    allowed_start != expected_start
                    or allowed_end != expected_recovery_end
                    or allowed_end <= allowed_start
                ):
                    raise ValueError("late capture recovery window mismatch")
                if not (
                    allowed_start <= local_capture < allowed_end
                    and local_capture.utcoffset() == expected_start.utcoffset()
                ):
                    raise ValueError("research peripheral late captured_at outside recovery window")
                if manual_late:
                    # A persisted manual recovery remains valid only for the
                    # latest official US session completed at its real capture
                    # instant.  Import locally to keep the store's base import
                    # graph independent from the digest producer.
                    from contracts.us_equity_calendar import latest_completed_session

                    try:
                        latest_session = latest_completed_session(captured_at)
                    except ValueError as error:
                        raise ValueError("manual recovery session resolution failed") from error
                    if latest_session.session_date != us_session_date:
                        raise ValueError("manual recovery is not the latest completed US session")
            elif not (
                expected_start <= local_capture < expected_end
                and local_capture.utcoffset() == expected_start.utcoffset()
            ):
                raise ValueError("research peripheral captured_at outside capture window")
        capture_id = row.get("capture_id")
        run_id = row.get("run_id")
        if not isinstance(capture_id, str) or not capture_id.strip():
            raise ValueError("research peripheral capture_id is missing")
        if capture_id in seen_ids:
            raise ValueError("duplicate research peripheral capture_id")
        seen_ids.add(capture_id)
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("research peripheral run_id is missing")
        if row.get("capture_phase") == "HISTORICAL_BACKFILL":
            if capture_origin != "HISTORICAL_BACKFILL" or original_time_capture is not False:
                raise ValueError("historical backfill capture identity is unsafe")
        elif manual_late:
            if not late or original_time_capture is not False:
                raise ValueError("manual recovery capture identity is unsafe")
        elif capture_origin != "ORIGINAL_TIME_CAPTURE" or original_time_capture is not True:
            raise ValueError("live capture identity is unsafe")
        captures.append(row)
    return captures


def _validate_market_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid research peripheral market_snapshot")
    required = {
        "schema_version",
        "status",
        "source",
        "provider",
        "source_response_sha256",
        "capture_phase",
        "capture_session_date",
        "captured_at",
        "generated_at",
        "mapping_version",
        "requested_symbol_count",
        "available_symbol_count",
        "provider_session_dates",
        "provider_session_times",
        "quotes",
        "rows",
        "cannot_confirm",
        "recommendation_status",
        "RESEARCH_ONLY",
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    }
    if not required.issubset(value):
        raise ValueError("invalid research peripheral market_snapshot fields")
    if value.get("schema_version") != _MARKET_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("invalid research peripheral market_snapshot schema")
    if value.get("mapping_version") != _MARKET_MAPPING_VERSION:
        raise ValueError("invalid research peripheral market_snapshot mapping version")
    if value.get("status") not in _MARKET_SNAPSHOT_STATUSES:
        raise ValueError("invalid research peripheral market_snapshot status")
    for field in ("source", "provider", "mapping_version"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"invalid research peripheral market_snapshot {field}")
    response_sha = value.get("source_response_sha256")
    if not isinstance(response_sha, str) or (response_sha and not _SHA256.fullmatch(response_sha)):
        raise ValueError("invalid research peripheral market_snapshot source response hash")
    if value.get("capture_phase") not in _CAPTURE_PHASES:
        raise ValueError("invalid research peripheral market_snapshot capture_phase")
    try:
        capture_session_date = _date(str(value.get("capture_session_date") or ""))
    except ValueError as error:
        raise ValueError("invalid research peripheral market_snapshot capture_session_date") from error
    _aware_timestamp(value.get("captured_at"), "market_snapshot.captured_at")
    _aware_timestamp(value.get("generated_at"), "market_snapshot.generated_at")
    if "late" in value and type(value["late"]) is not bool:
        raise ValueError("research peripheral market_snapshot late must be boolean")
    if "capture_mode" in value and (
        not isinstance(value["capture_mode"], str)
        or not value["capture_mode"].strip()
    ):
        raise ValueError("invalid research peripheral market_snapshot capture_mode")
    if value.get("capture_mode") == _LATE_CAPTURE_MODE and value.get("late") is not True:
        raise ValueError("late market_snapshot mode requires late identity")
    for field in ("requested_symbol_count", "available_symbol_count"):
        count = value.get(field)
        if type(count) is not int or count < 0:
            raise ValueError(f"invalid research peripheral market_snapshot {field}")
    _string_list(value.get("provider_session_dates"), "market_snapshot.provider_session_dates")
    _string_list(value.get("provider_session_times"), "market_snapshot.provider_session_times")
    for provider_date in value.get("provider_session_dates"):
        try:
            normalized_provider_date = _date(provider_date)
        except ValueError as error:
            raise ValueError("invalid market_snapshot provider session date") from error
        if normalized_provider_date != capture_session_date:
            raise ValueError("market_snapshot provider session date mismatch")
    for provider_time in value.get("provider_session_times"):
        if not _US_SESSION_TIME.fullmatch(provider_time):
            raise ValueError("invalid market_snapshot provider session time")
    _string_list(value.get("cannot_confirm"), "market_snapshot.cannot_confirm")
    quotes = value.get("quotes")
    if not isinstance(quotes, list):
        raise ValueError("invalid research peripheral market_snapshot quotes")
    quote_symbols: set[str] = set()
    for quote in quotes:
        if not isinstance(quote, Mapping) or not {
            "symbol",
            "exchange",
            "session_date",
            "session_time",
            "last",
            "previous_close",
            "change_pct",
            "provider",
        }.issubset(quote):
            raise ValueError("invalid research peripheral market_snapshot quote")
        symbol = quote.get("symbol")
        if (
            not isinstance(symbol, str)
            or not symbol.strip()
            or symbol not in _CANONICAL_SYMBOLS
            or symbol in quote_symbols
        ):
            raise ValueError("invalid or duplicate research peripheral market_snapshot quote symbol")
        quote_symbols.add(symbol)
        if quote.get("exchange") != "US" or not isinstance(quote.get("provider"), str) or not quote["provider"].strip():
            raise ValueError("invalid research peripheral market_snapshot quote identity")
        if quote.get("session_date") != capture_session_date:
            raise ValueError("market_snapshot quote session date mismatch")
        if not isinstance(quote.get("session_date"), str) or not quote.get("session_date"):
            raise ValueError("invalid research peripheral market_snapshot quote session_date")
        if not isinstance(quote.get("session_time"), str):
            raise ValueError("invalid research peripheral market_snapshot quote session_time")
        if quote.get("session_time") and not _US_SESSION_TIME.fullmatch(quote["session_time"]):
            raise ValueError("invalid research peripheral market_snapshot quote session_time")
        if not quote.get("session_time") and (
            value.get("status") == "READY"
            or "QUOTE_SESSION_TIME_MISSING" not in value.get("cannot_confirm", [])
        ):
            raise ValueError("invalid research peripheral market_snapshot quote session_time")
        for field in ("last", "previous_close", "change_pct"):
            _finite_number(quote.get(field), f"market_snapshot quote {field}")
        last = float(quote["last"])
        previous_close = float(quote["previous_close"])
        if previous_close == 0:
            raise ValueError("market_snapshot quote previous_close must be nonzero")
        derived_change = (last - previous_close) / previous_close * 100
        if (
            not math.isfinite(derived_change)
            or abs(float(quote["change_pct"]) - derived_change)
            > _QUOTE_CHANGE_TOLERANCE
        ):
            raise ValueError("market_snapshot quote change arithmetic mismatch")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != _MARKET_SNAPSHOT_THEME_COUNT:
        raise ValueError("research peripheral market_snapshot must contain 24 rows")
    labels: list[str] = []
    available_symbols: set[str] = set()
    requested_symbols: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("invalid research peripheral market_snapshot row")
        for field in (
            "label",
            "group",
            "mapping_type",
            "proxy_symbols",
            "available_symbols",
            "missing_symbols",
            "requested_symbol_count",
            "available_symbol_count",
            "coverage",
            "coverage_pct",
            "change_pct",
            "pct_change",
            "direction",
            "status",
            "quote_session_dates",
            "quote_session_times",
            "cannot_confirm",
        ):
            if field not in row:
                raise ValueError("invalid research peripheral market_snapshot row fields")
        _canonical_row_shape(row, index)
        label = row.get("label")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError("invalid or duplicate research peripheral market_snapshot label")
        labels.append(label)
        for field in ("group", "mapping_type"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"invalid research peripheral market_snapshot {field}")
        symbol_lists: dict[str, list[str]] = {}
        for field in ("proxy_symbols", "available_symbols", "missing_symbols"):
            symbols = row.get(field)
            if not isinstance(symbols, list) or any(
                not isinstance(symbol, str) or not symbol.strip() for symbol in symbols
            ) or len(symbols) != len(set(symbols)):
                raise ValueError(f"invalid research peripheral market_snapshot {field}")
            symbol_lists[field] = symbols
        if not set(symbol_lists["available_symbols"]).issubset(symbol_lists["proxy_symbols"]):
            raise ValueError("market_snapshot available symbols are outside proxy mapping")
        if set(symbol_lists["available_symbols"]) | set(symbol_lists["missing_symbols"]) != set(symbol_lists["proxy_symbols"]):
            raise ValueError("market_snapshot coverage symbols do not partition proxy mapping")
        requested_count = row.get("requested_symbol_count")
        available_count = row.get("available_symbol_count")
        if type(requested_count) is not int or requested_count != len(symbol_lists["proxy_symbols"]):
            raise ValueError("invalid market_snapshot requested symbol count")
        if type(available_count) is not int or available_count != len(symbol_lists["available_symbols"]):
            raise ValueError("invalid market_snapshot available symbol count")
        coverage = row.get("coverage")
        if not isinstance(coverage, Mapping) or coverage.get("available") != available_count or coverage.get("requested") != requested_count:
            raise ValueError("invalid market_snapshot coverage")
        coverage_pct = row.get("coverage_pct")
        if (
            isinstance(coverage_pct, bool)
            or not isinstance(coverage_pct, (int, float))
            or not math.isfinite(float(coverage_pct))
            or coverage_pct < 0
            or coverage_pct > 100
            or abs(float(coverage_pct) - available_count / requested_count * 100) > _QUOTE_CHANGE_TOLERANCE
        ):
            raise ValueError("invalid market_snapshot coverage_pct")
        pct_change = row.get("pct_change")
        if pct_change is not None:
            _finite_number(pct_change, "market_snapshot pct_change")
        change_pct = row.get("change_pct")
        if change_pct is not None:
            _finite_number(change_pct, "market_snapshot change_pct")
        if change_pct != pct_change:
            raise ValueError("market_snapshot change_pct and pct_change mismatch")
        if row.get("direction") not in _MARKET_SNAPSHOT_DIRECTIONS:
            raise ValueError("invalid market_snapshot direction")
        if row.get("status") not in _MARKET_SNAPSHOT_STATUSES:
            raise ValueError("invalid market_snapshot row status")
        _string_list(row.get("quote_session_dates"), "market_snapshot.row.quote_session_dates")
        _string_list(row.get("quote_session_times"), "market_snapshot.row.quote_session_times")
        _string_list(row.get("cannot_confirm"), "market_snapshot.row.cannot_confirm")
        available = symbol_lists["available_symbols"]
        row_quotes = [quote for quote in quotes if quote["symbol"] in available]
        expected_row_dates = sorted({
            str(quote["session_date"])
            for quote in row_quotes
            if str(quote.get("session_date") or "").strip()
        })
        expected_row_times = sorted({
            str(quote["session_time"])
            for quote in row_quotes
            if str(quote.get("session_time") or "").strip()
        })
        if row.get("quote_session_dates") != expected_row_dates:
            raise ValueError("market_snapshot row session dates mismatch")
        if row.get("quote_session_times") != expected_row_times:
            raise ValueError("market_snapshot row session times mismatch")
        expected_changes = [
            float(quote["change_pct"])
            for quote in quotes
            if quote["symbol"] in available
        ]
        if expected_changes:
            expected_row_change = sum(expected_changes) / len(expected_changes)
            if (
                change_pct is None
                or abs(float(change_pct) - expected_row_change) > _QUOTE_CHANGE_TOLERANCE
            ):
                raise ValueError("market_snapshot row change arithmetic mismatch")
        elif change_pct is not None or pct_change is not None:
            raise ValueError("market_snapshot empty row cannot have change")
        expected_direction = (
            "CANNOT_CONFIRM" if change_pct is None
            else "UP" if float(change_pct) > 0
            else "DOWN" if float(change_pct) < 0
            else "FLAT"
        )
        if row.get("direction") != expected_direction:
            raise ValueError("market_snapshot row direction mismatch")
        if row.get("status") == "READY":
            if len(available) != len(symbol_lists["proxy_symbols"]):
                raise ValueError("market_snapshot READY row coverage incomplete")
            if row.get("quote_session_dates") != [capture_session_date]:
                raise ValueError("market_snapshot READY row session date invalid")
            if not row.get("quote_session_times"):
                raise ValueError("market_snapshot READY row session time missing")
        available_symbols.update(symbol_lists["available_symbols"])
        requested_symbols.update(symbol_lists["proxy_symbols"])
    if value.get("requested_symbol_count") != len(requested_symbols):
        raise ValueError("invalid aggregate market_snapshot requested symbol count")
    if value.get("available_symbol_count") != len(available_symbols):
        raise ValueError("invalid aggregate market_snapshot available symbol count")
    if quote_symbols != available_symbols:
        raise ValueError("market_snapshot quotes do not match available symbols")
    quote_dates = sorted({quote["session_date"] for quote in quotes})
    provider_dates = value.get("provider_session_dates")
    if value.get("status") == "READY":
        if provider_dates != quote_dates:
            raise ValueError("market_snapshot provider session dates mismatch")
    elif not set(quote_dates).issubset(provider_dates):
        raise ValueError("market_snapshot provider session dates mismatch")
    quote_times = sorted({
        str(quote["session_time"])
        for quote in quotes
        if str(quote.get("session_time") or "").strip()
    })
    provider_times = value.get("provider_session_times")
    if value.get("status") == "READY":
        if provider_times != quote_times:
            raise ValueError("market_snapshot provider session times mismatch")
    elif not set(quote_times).issubset(provider_times):
        raise ValueError("market_snapshot provider session times mismatch")
    if value.get("status") in {"PARTIAL", "CANNOT_CONFIRM"} and not value.get("cannot_confirm"):
        raise ValueError("market_snapshot incomplete status requires cannot_confirm")
    if value.get("status") == "READY":
        if any(row.get("status") != "READY" for row in rows):
            raise ValueError("market_snapshot READY status has non-ready row")
        if value.get("cannot_confirm"):
            raise ValueError("market_snapshot READY status has cannot_confirm reasons")
        if value.get("provider_session_dates") != [capture_session_date]:
            raise ValueError("market_snapshot READY session date invalid")
    if value.get("status") == "CANNOT_CONFIRM" and value.get("available_symbol_count"):
        # A failed or invalid quote can retain partial provider data, but the
        # failure must remain explicit at the snapshot boundary.
        if not value.get("cannot_confirm"):
            raise ValueError("market_snapshot CANNOT_CONFIRM reason is missing")
    if "provider_receipt" in value and not isinstance(value["provider_receipt"], Mapping):
        raise ValueError("invalid research peripheral market_snapshot provider receipt")
    if value.get("recommendation_status") != "RESEARCH_ONLY":
        raise ValueError("unsafe market_snapshot recommendation status")
    if value.get("production_allowed") is not False or value.get("buy_gate_updated") is not False or value.get("orders_sent") is not False:
        raise ValueError("unsafe market_snapshot safety flag")
    if value.get("RESEARCH_ONLY") is not True:
        raise ValueError("unsafe market_snapshot research flag")
    return dict(value)


def validate_research_peripheral(
    payload: Mapping[str, Any],
    *,
    expected_trade_date: str | None = None,
    expected_source: str | None = None,
) -> tuple[str, str]:
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
    if not isinstance(payload, Mapping) or not required.issubset(payload) or set(payload) - required - optional:
        raise ValueError("invalid research peripheral fields")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("invalid research peripheral schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    source = _source(str(payload.get("source") or ""))
    if expected_trade_date is not None and trade_date != _date(expected_trade_date):
        raise ValueError("research peripheral trade-date mismatch")
    if expected_source is not None and source != _source(expected_source):
        raise ValueError("research peripheral source mismatch")
    if payload.get("status") not in _STATUSES:
        raise ValueError("invalid research peripheral status")
    if not isinstance(payload.get("source_url"), str) or not payload["source_url"].strip():
        raise ValueError("research peripheral source_url is missing")
    _aware_timestamp(payload.get("fetched_at"), "fetched_at")
    for field in ("raw_item_count", "item_count"):
        value = payload.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid research peripheral {field}")
    overview = _validate_item_list(payload.get("overview"), "overview")
    details = _validate_item_list(payload.get("details"), "details")
    items = _validate_item_list(payload.get("items"), "items")
    if source == "external_finance":
        if items or payload["item_count"] != len(details) or len(overview) > len(details):
            raise ValueError("invalid external finance projection")
    else:
        if overview or details or payload["item_count"] != len(items):
            raise ValueError("invalid AI news projection")
    if payload["raw_item_count"] < payload["item_count"]:
        raise ValueError("research peripheral item count mismatch")
    _string_list(payload.get("cannot_confirm"), "cannot_confirm")
    if "feed_receipts" in payload:
        feed_receipts = payload.get("feed_receipts")
        if not isinstance(feed_receipts, list):
            raise ValueError("invalid research peripheral feed_receipts")
        for receipt in feed_receipts:
            if not isinstance(receipt, Mapping):
                raise ValueError("invalid research peripheral feed receipt")
            if not isinstance(receipt.get("feed_id"), str) or not receipt["feed_id"].strip():
                raise ValueError("research peripheral feed receipt id is missing")
            if not isinstance(receipt.get("url"), str) or not receipt["url"].strip():
                raise ValueError("research peripheral feed receipt url is missing")
            elapsed = receipt.get("elapsed_ms")
            if type(elapsed) is not int or elapsed < 0:
                raise ValueError("invalid research peripheral feed receipt elapsed_ms")
            status = receipt.get("http_status")
            if status is not None and (type(status) is not int or status < 100 or status > 599):
                raise ValueError("invalid research peripheral feed receipt http_status")
            if receipt.get("error") is not None and not isinstance(receipt.get("error"), str):
                raise ValueError("invalid research peripheral feed receipt error")
            for key in ("proxy_used", "fallback_used"):
                if type(receipt.get(key)) is not bool:
                    raise ValueError(f"invalid research peripheral feed receipt {key}")
    if "us_session_captures" in payload:
        captures = _validate_us_session_captures(payload["us_session_captures"])
        if not captures and any(
            key in payload for key in ("capture_origin", "original_time_capture")
        ):
            raise ValueError("capture identity requires at least one capture")
        if "capture_origin" in payload and payload["capture_origin"] not in _CAPTURE_ORIGINS:
            raise ValueError("invalid research peripheral capture_origin")
        if "original_time_capture" in payload and type(payload["original_time_capture"]) is not bool:
            raise ValueError("research peripheral original_time_capture must be boolean")
        if "late" in payload and type(payload["late"]) is not bool:
            raise ValueError("research peripheral late must be boolean")
        if "capture_mode" in payload and (
            not isinstance(payload["capture_mode"], str)
            or not payload["capture_mode"].strip()
        ):
            raise ValueError("invalid research peripheral capture_mode")
        for field in ("reason", "capture_reason"):
            if field in payload and (
                not isinstance(payload[field], str) or not payload[field].strip()
            ):
                raise ValueError(f"invalid research peripheral {field}")
        if payload.get("capture_mode") == _LATE_CAPTURE_MODE and payload.get("late") is not True:
            raise ValueError("late capture payload mode requires late identity")
        late_captures = [row for row in captures if row.get("late") is True]
        if late_captures:
            if payload.get("late") is not True:
                raise ValueError("late capture payload identity is missing")
            if payload.get("capture_mode") != _LATE_CAPTURE_MODE:
                raise ValueError("late capture payload mode mismatch")
            latest_late = max(
                late_captures,
                key=lambda row: str(row.get("captured_at") or ""),
            )
            expected_late_reason = (
                _MANUAL_LATE_CAPTURE_REASON
                if latest_late.get("capture_origin") == "MANUAL_RECOVERY"
                else _LATE_CAPTURE_REASON
            )
            if payload.get("reason") != expected_late_reason:
                raise ValueError("late capture payload reason mismatch")
            if payload.get("capture_reason") not in (None, expected_late_reason):
                raise ValueError("late capture payload capture_reason mismatch")
        elif payload.get("late") is True:
            raise ValueError("late capture payload has no late capture")
        fetched_at = _parse_aware_timestamp(payload["fetched_at"], "fetched_at")
        for capture in captures:
            capture_at = _parse_aware_timestamp(capture["captured_at"], "captured_at")
            if capture_at > fetched_at:
                raise ValueError("research peripheral captured_at is after fetched_at")
        if "capture_origin" in payload and payload["capture_origin"] == "HISTORICAL_BACKFILL":
            if payload.get("original_time_capture") is not False or any(
                row["capture_origin"] != "HISTORICAL_BACKFILL" or row["original_time_capture"] is not False
                for row in captures
            ):
                raise ValueError("historical backfill payload identity is unsafe")
        if "capture_origin" in payload and payload["capture_origin"] == "ORIGINAL_TIME_CAPTURE":
            if payload.get("original_time_capture") is not True or any(
                row["capture_origin"] != "ORIGINAL_TIME_CAPTURE" or row["original_time_capture"] is not True
                for row in captures
            ):
                raise ValueError("live capture identity is unsafe")
        if "capture_origin" in payload and payload["capture_origin"] == "MANUAL_RECOVERY":
            if payload.get("original_time_capture") is not False or not captures or any(
                row["capture_origin"] != "MANUAL_RECOVERY"
                or row["original_time_capture"] is not False
                or row.get("late") is not True
                for row in captures
            ):
                raise ValueError("manual recovery payload identity is unsafe")
    elif any(key in payload for key in ("capture_origin", "original_time_capture")):
        raise ValueError("capture identity requires us_session_captures")
    if "market_snapshot" in payload:
        snapshot = _validate_market_snapshot(payload["market_snapshot"])
        if payload.get("market_snapshot_status") != snapshot.get("status"):
            raise ValueError("research peripheral market_snapshot_status mismatch")
        if (
            snapshot.get("capture_phase") == "POST_CLOSE"
            and snapshot.get("status") != "READY"
            and payload.get("status") != "CANNOT_CONFIRM"
        ):
            raise ValueError(
                "research peripheral POST_CLOSE market_snapshot failure must be CANNOT_CONFIRM"
            )
        if _parse_aware_timestamp(snapshot["captured_at"], "market_snapshot.captured_at") > _parse_aware_timestamp(
            payload["fetched_at"], "fetched_at"
        ):
            raise ValueError("research peripheral market_snapshot captured_at is after fetched_at")
        captures = payload.get("us_session_captures") or []
        snapshot_late = _is_late_capture_identity(snapshot)
        matching_capture = next(
            (
                row
                for row in captures
                if isinstance(row, Mapping)
                and row.get("us_session_date") == snapshot.get("capture_session_date")
                and row.get("capture_phase") == snapshot.get("capture_phase")
                and _is_late_capture_identity(row) == snapshot_late
            ),
            None,
        )
        if matching_capture is None:
            raise ValueError("research peripheral market_snapshot capture identity missing")
        snapshot_at = _parse_aware_timestamp(
            snapshot["captured_at"], "market_snapshot.captured_at"
        )
        if _is_late_capture_identity(matching_capture):
            capture_start = _parse_aware_timestamp(
                matching_capture["allowed_recovery_window_start"],
                "allowed_recovery_window_start",
            )
            capture_end = _parse_aware_timestamp(
                matching_capture["allowed_recovery_window_end"],
                "allowed_recovery_window_end",
            )
        else:
            capture_start = _parse_aware_timestamp(
                matching_capture["capture_window_start"], "capture_window_start"
            )
            capture_end = _parse_aware_timestamp(
                matching_capture["capture_window_end"], "capture_window_end"
            )
        capture_at = _parse_aware_timestamp(
            matching_capture["captured_at"], "captured_at"
        )
        # A retry may carry the same capture_id with a later fetch timestamp;
        # the retained quote snapshot may therefore precede the latest
        # capture record while remaining inside the explicit window.
        if (
            matching_capture.get("capture_phase") != "HISTORICAL_BACKFILL"
            and not (capture_start <= snapshot_at < capture_end)
        ) or snapshot_at > capture_at:
            raise ValueError("research peripheral market_snapshot capture timestamp mismatch")
    elif "market_snapshot_status" in payload:
        raise ValueError("market_snapshot_status requires market_snapshot")
    fixed = {
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        raise ValueError("unsafe research peripheral boundary")
    if payload["status"] == "READY" and payload["item_count"] == 0:
        raise ValueError("empty research peripheral must be READY_EMPTY or CANNOT_CONFIRM")
    if payload["status"] == "READY_EMPTY" and payload["item_count"] != 0:
        raise ValueError("non-empty research peripheral cannot be READY_EMPTY")
    return trade_date, source


class ResearchPeripheralStore(NativeDataStore):
    """Atomic exact-date artifacts for ``external_finance`` and ``ai_news``."""

    @staticmethod
    def _relative(trade_date: str, source: str) -> str:
        return f"research/peripherals/{trade_date}/{source}.json"

    @staticmethod
    def _receipt_relative(trade_date: str, source: str) -> str:
        return f"receipts/research/peripherals/{trade_date}/{source}.json"

    @staticmethod
    def _history_relative(trade_date: str, source: str, digest: str) -> str:
        return f"research/peripherals/history/{trade_date}/{source}/{digest}.json"

    @staticmethod
    def _supersession_relative(trade_date: str, source: str, digest: str) -> str:
        return (
            f"receipts/research/peripherals/supersessions/"
            f"{trade_date}/{source}/{digest}.json"
        )

    @staticmethod
    def _historical_backfill_relative(trade_date: str, source: str) -> str:
        return f"research/peripherals/history_backfill/{trade_date}/{source}.json"

    @staticmethod
    def _historical_backfill_receipt_relative(trade_date: str, source: str) -> str:
        return f"receipts/research/peripherals/history_backfill/{trade_date}/{source}.json"

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _manifest(self) -> dict[str, str]:
        path = self._path(_MANIFEST_RELATIVE)
        if not path.exists():
            return {}
        payload = self._read(_MANIFEST_RELATIVE)
        if not isinstance(payload, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in payload.items()
        ):
            raise ValueError("invalid research peripheral manifest")
        return dict(payload)

    def _write_manifest(self, manifest: Mapping[str, str]) -> None:
        self._write(_MANIFEST_RELATIVE, dict(manifest))

    @classmethod
    def _receipt(
        cls,
        payload: Mapping[str, Any],
        digest: str,
    ) -> dict[str, Any]:
        trade_date = str(payload["trade_date"])
        source = str(payload["source"])
        receipt = {
            "schema_version": _RECEIPT_SCHEMA_VERSION,
            "trade_date": trade_date,
            "source": source,
            "payload_path": cls._relative(trade_date, source),
            "payload_sha256": digest,
            "item_count": int(payload["item_count"]),
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if "feed_receipts" in payload:
            receipt["feed_receipts"] = [dict(item) for item in payload["feed_receipts"]]
        if "market_snapshot" in payload:
            receipt["market_snapshot_sha256"] = _sha256(payload["market_snapshot"])
            receipt["market_snapshot_schema_version"] = str(
                payload["market_snapshot"].get("schema_version") or ""
            )
            receipt["market_snapshot_captured_at"] = str(
                payload["market_snapshot"].get("captured_at") or ""
            )
            receipt["market_snapshot_source_response_sha256"] = str(
                payload["market_snapshot"].get("source_response_sha256") or ""
            )
            receipt["market_snapshot_status"] = str(
                payload["market_snapshot"].get("status") or "CANNOT_CONFIRM"
            )
            receipt["market_snapshot_status"] = str(
                payload.get("market_snapshot_status")
                or receipt["market_snapshot_status"]
            )
        captures = payload.get("us_session_captures")
        if isinstance(captures, list):
            late_rows = [
                row
                for row in captures
                if isinstance(row, Mapping) and row.get("late") is True
            ]
            late_capture = max(
                late_rows,
                key=lambda row: str(row.get("captured_at") or ""),
                default=None,
            )
            if isinstance(late_capture, Mapping):
                for field in (
                    "capture_id",
                    "run_id",
                    "us_session_date",
                    "capture_phase",
                    "captured_at",
                    "capture_origin",
                    "original_time_capture",
                    "rss_status",
                    "rss_item_count",
                    "rss_raw_item_count",
                    "quote_capture_status",
                    "quote_capture_reason",
                    "capture_mode",
                    "reason",
                    "capture_reason",
                    "late",
                    "natural_capture_window_start",
                    "natural_capture_window_end",
                    "allowed_recovery_window_start",
                    "allowed_recovery_window_end",
                ):
                    if field in late_capture:
                        receipt[field] = late_capture[field]
        return receipt

    @classmethod
    def _receipt_matches(
        cls,
        payload: Mapping[str, Any],
        digest: str,
        stored_receipt: Any,
    ) -> bool:
        """Accept the exact pre-R2 receipt shape when only two fields are absent.

        The compatibility case remains bound to the canonical payload SHA in
        both the manifest and receipt. The absent values are derived from the
        payload's market snapshot; callers still require normal payload
        validation before returning or replacing the artifact. No historical
        value is inferred or written back by a read.
        """
        expected = cls._receipt(payload, digest)
        if stored_receipt == expected:
            return True
        if not isinstance(stored_receipt, Mapping):
            return False
        if not _LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS.issubset(expected):
            return False
        captured_at = expected.get("market_snapshot_captured_at")
        source_response_sha256 = expected.get(
            "market_snapshot_source_response_sha256"
        )
        if (
            not isinstance(captured_at, str)
            or not captured_at
            or not isinstance(source_response_sha256, str)
            or not _SHA256.fullmatch(source_response_sha256)
        ):
            return False
        legacy_shape = {
            key: value
            for key, value in expected.items()
            if key not in _LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS
        }
        return dict(stored_receipt) == legacy_shape

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        trade_date, source = validate_research_peripheral(payload)
        relative = self._relative(trade_date, source)
        receipt_relative = self._receipt_relative(trade_date, source)
        digest = _sha256(payload)
        receipt = self._receipt(payload, digest)
        artifact_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            if existing and existing != digest:
                raise ValueError("conflicting research peripheral re-import")
            if existing:
                if (
                    not artifact_path.is_file()
                    or _sha256(self._read(relative)) != digest
                    or not receipt_path.is_file()
                    or not self._receipt_matches(
                        payload, digest, self._read(receipt_relative)
                    )
                ):
                    raise ValueError("research peripheral integrity mismatch")
            else:
                if artifact_path.exists() or receipt_path.exists():
                    raise ValueError("orphan research peripheral artifact or receipt")
                self._write(relative, payload)
                self._write(receipt_relative, receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
        return {
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "payload_sha256": digest,
            "item_count": int(payload["item_count"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def replace(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str,
        reason: str,
    ) -> dict[str, Any]:
        """CAS-replace one exact source while preserving its previous payload."""
        trade_date, source = validate_research_peripheral(payload)
        expected = str(expected_sha256 or "").strip().lower()
        normalized_reason = str(reason or "").strip()
        if not _SHA256.fullmatch(expected):
            raise ValueError("research peripheral expected SHA must be sha256")
        if not normalized_reason:
            raise ValueError("research peripheral replacement reason is required")
        relative = self._relative(trade_date, source)
        receipt_relative = self._receipt_relative(trade_date, source)
        digest = _sha256(payload)
        replacement_receipt = self._receipt(payload, digest)
        with self._lock():
            manifest = self._manifest()
            if manifest.get(relative) != expected:
                raise ValueError("research peripheral expected SHA mismatch")
            artifact_path = self._path(relative)
            receipt_path = self._path(receipt_relative)
            if not artifact_path.is_file() or not receipt_path.is_file():
                raise ValueError("research peripheral replacement source is incomplete")
            previous_payload = self._read(relative)
            previous_digest = _sha256(previous_payload)
            if (
                previous_digest != expected
                or not self._receipt_matches(
                    previous_payload,
                    previous_digest,
                    self._read(receipt_relative),
                )
                or validate_research_peripheral(
                    previous_payload,
                    expected_trade_date=trade_date,
                    expected_source=source,
                )
                != (trade_date, source)
            ):
                raise ValueError("research peripheral replacement integrity mismatch")
            if digest == previous_digest:
                return {
                    "trade_date": trade_date,
                    "source": source,
                    "payload_path": relative,
                    "receipt_path": receipt_relative,
                    "payload_sha256": digest,
                    "replaced": False,
                    "previous_payload_path": "",
                    "supersession_receipt_path": "",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            history_relative = self._history_relative(
                trade_date, source, previous_digest
            )
            supersession_relative = self._supersession_relative(
                trade_date, source, digest
            )
            history_path = self._path(history_relative)
            supersession_path = self._path(supersession_relative)
            if history_path.exists() and (
                not history_path.is_file()
                or self._read(history_relative) != previous_payload
            ):
                raise ValueError("research peripheral history conflict")
            supersession = {
                "schema_version": "v3_5.research_peripheral_supersession.v1",
                "trade_date": trade_date,
                "source": source,
                "payload_path": relative,
                "payload_sha256": digest,
                "previous_payload_path": history_relative,
                "previous_payload_sha256": previous_digest,
                "reason": normalized_reason,
                "write_policy": "read_only",
                "recommendation_status": "RESEARCH_ONLY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            if supersession_path.exists() and (
                not supersession_path.is_file()
                or self._read(supersession_relative) != supersession
            ):
                raise ValueError("research peripheral supersession conflict")
            if not history_path.exists():
                self._write(history_relative, previous_payload)
            if not supersession_path.exists():
                self._write(supersession_relative, supersession)
            self._write(relative, payload)
            self._write(receipt_relative, replacement_receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        return {
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "payload_sha256": digest,
            "replaced": True,
            "previous_payload_path": history_relative,
            "supersession_receipt_path": supersession_relative,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def publish_historical_backfill(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish a development-only retrospective source artifact.

        Historical backfills live outside the exact-date live artifact so they
        cannot silently replace an original-time capture.  The payload itself
        carries the explicit ``HISTORICAL_BACKFILL`` identity and remains
        research-only.
        """
        trade_date, source = validate_research_peripheral(payload)
        if payload.get("capture_origin") != "HISTORICAL_BACKFILL" or payload.get("original_time_capture") is not False:
            raise ValueError("historical backfill identity is required")
        relative = self._historical_backfill_relative(trade_date, source)
        receipt_relative = self._historical_backfill_receipt_relative(trade_date, source)
        digest = _sha256(payload)
        receipt = {
            "schema_version": _BACKFILL_RECEIPT_SCHEMA_VERSION,
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "payload_sha256": digest,
            "item_count": int(payload["item_count"]),
            "capture_origin": "HISTORICAL_BACKFILL",
            "original_time_capture": False,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            artifact_path = self._path(relative)
            receipt_path = self._path(receipt_relative)
            if existing and existing != digest:
                raise ValueError("conflicting historical backfill re-import")
            if existing:
                if (
                    not artifact_path.is_file()
                    or _sha256(self._read(relative)) != digest
                    or not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("historical backfill integrity mismatch")
            else:
                if artifact_path.exists() or receipt_path.exists():
                    raise ValueError("orphan historical backfill artifact or receipt")
                self._write(relative, payload)
                self._write(receipt_relative, receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
        return {
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "payload_sha256": digest,
            "item_count": int(payload["item_count"]),
            "capture_origin": "HISTORICAL_BACKFILL",
            "original_time_capture": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def read_historical_backfill(
        self,
        trade_date: str,
        source: str = "external_finance",
    ) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        source = _source(source)
        relative = self._historical_backfill_relative(trade_date, source)
        receipt_relative = self._historical_backfill_receipt_relative(trade_date, source)
        if not self._path(relative).is_file() or not self._path(receipt_relative).is_file():
            return None
        payload = self._read(relative)
        validate_research_peripheral(
            payload,
            expected_trade_date=trade_date,
            expected_source=source,
        )
        if payload.get("capture_origin") != "HISTORICAL_BACKFILL" or payload.get("original_time_capture") is not False:
            raise ValueError("historical backfill identity is unsafe")
        digest = _sha256(payload)
        manifest = self._manifest()
        receipt = self._read(receipt_relative)
        expected_receipt = {
            "schema_version": _BACKFILL_RECEIPT_SCHEMA_VERSION,
            "trade_date": trade_date,
            "source": source,
            "payload_path": relative,
            "payload_sha256": digest,
            "item_count": int(payload["item_count"]),
            "capture_origin": "HISTORICAL_BACKFILL",
            "original_time_capture": False,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("historical backfill manifest or receipt mismatch")
        return payload

    def record_refresh_attempt(
        self,
        attempted_payload: Mapping[str, Any],
        *,
        retained_payload: Mapping[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """Record a failed refresh without replacing a verified READY value."""
        trade_date, source = validate_research_peripheral(attempted_payload)
        retained_date, retained_source = validate_research_peripheral(
            retained_payload,
            expected_trade_date=trade_date,
            expected_source=source,
        )
        if (retained_date, retained_source) != (trade_date, source):
            raise ValueError("research peripheral retained identity mismatch")
        if attempted_payload.get("status") != "CANNOT_CONFIRM":
            raise ValueError("refresh attempt must be CANNOT_CONFIRM")
        if retained_payload.get("status") not in {"READY", "READY_EMPTY"}:
            raise ValueError("refresh attempt requires a retained READY payload")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("refresh attempt reason is required")
        attempted_sha = _sha256(attempted_payload)
        retained_sha = _sha256(retained_payload)
        relative = (
            f"receipts/research/peripherals/refresh_attempts/{trade_date}/"
            f"{source}/{attempted_sha}.json"
        )
        record = {
            "schema_version": "v3_5.research_peripheral_refresh_attempt.v1",
            "trade_date": trade_date,
            "source": source,
            "attempted_status": "CANNOT_CONFIRM",
            "attempted_item_count": int(attempted_payload["item_count"]),
            "attempted_fetched_at": attempted_payload["fetched_at"],
            "attempted_cannot_confirm": list(attempted_payload["cannot_confirm"]),
            "attempted_payload_sha256": attempted_sha,
            "retained_status": retained_payload["status"],
            "retained_item_count": int(retained_payload["item_count"]),
            "retained_fetched_at": retained_payload["fetched_at"],
            "retained_payload_sha256": retained_sha,
            "reason": normalized_reason,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        attempted_snapshot = attempted_payload.get("market_snapshot")
        if isinstance(attempted_snapshot, Mapping):
            record["attempted_market_snapshot_status"] = str(
                attempted_payload.get("market_snapshot_status")
                or attempted_snapshot.get("status")
                or "CANNOT_CONFIRM"
            )
            record["attempted_market_snapshot_cannot_confirm"] = list(
                attempted_snapshot.get("cannot_confirm") or []
            )
        attempted_captures = attempted_payload.get("us_session_captures")
        if isinstance(attempted_captures, list):
            attempted_capture = next(
                (
                    row
                    for row in attempted_captures
                    if isinstance(row, Mapping)
                    and row.get("capture_phase") == "POST_CLOSE"
                ),
                None,
            )
            if isinstance(attempted_capture, Mapping):
                # Preserve the failed capture identity alongside its digest;
                # the canonical artifact remains the verified last-known
                # payload and is intentionally not overwritten by this attempt.
                for field, receipt_field in (
                    ("capture_id", "attempted_capture_id"),
                    ("capture_phase", "attempted_capture_phase"),
                    ("us_session_date", "attempted_capture_session_date"),
                    ("run_id", "attempted_run_id"),
                    ("captured_at", "attempted_captured_at"),
                    ("capture_mode", "attempted_capture_mode"),
                    ("reason", "attempted_capture_reason"),
                    ("capture_reason", "attempted_capture_reason_detail"),
                    ("late", "attempted_late"),
                    (
                        "natural_capture_window_start",
                        "attempted_natural_capture_window_start",
                    ),
                    (
                        "natural_capture_window_end",
                        "attempted_natural_capture_window_end",
                    ),
                    (
                        "allowed_recovery_window_start",
                        "attempted_allowed_recovery_window_start",
                    ),
                    (
                        "allowed_recovery_window_end",
                        "attempted_allowed_recovery_window_end",
                    ),
                ):
                    if attempted_capture.get(field) is not None:
                        record[receipt_field] = (
                            bool(attempted_capture[field])
                            if field == "late"
                            else str(attempted_capture[field])
                        )
        with self._lock():
            path = self._path(relative)
            if path.exists():
                if not path.is_file() or self._read(relative) != record:
                    raise ValueError("research peripheral refresh attempt conflict")
            else:
                self._write(relative, record)
        return {
            "refresh_attempt_path": relative,
            "attempted_payload_sha256": attempted_sha,
            "retained_payload_sha256": retained_sha,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def read_exact(self, trade_date: str, source: str) -> dict[str, Any] | None:
        normalized_date = _date(trade_date)
        normalized_source = _source(source)
        relative = self._relative(normalized_date, normalized_source)
        receipt_relative = self._receipt_relative(normalized_date, normalized_source)
        artifact_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        tracked = relative in manifest
        if not artifact_path.exists() and not receipt_path.exists() and not tracked:
            return None
        if not artifact_path.is_file() or not receipt_path.is_file() or not tracked:
            raise ValueError("research peripheral manifest or receipt mismatch")
        payload = self._read(relative)
        digest = _sha256(payload)
        if (
            manifest.get(relative) != digest
            or not self._receipt_matches(
                payload, digest, self._read(receipt_relative)
            )
            or validate_research_peripheral(
                payload,
                expected_trade_date=normalized_date,
                expected_source=normalized_source,
            )
            != (normalized_date, normalized_source)
        ):
            raise ValueError("research peripheral manifest or receipt mismatch")
        return payload

    def list_dates(self, source: str | None = None) -> list[str]:
        selected_source = _source(source) if source is not None else None
        pattern = re.compile(r"^research/peripherals/(\d{8})/(external_finance|ai_news)\.json$")
        dates: set[str] = set()
        for relative in self._manifest():
            match = pattern.fullmatch(relative)
            if not match:
                continue
            if selected_source is None or match.group(2) == selected_source:
                dates.add(_date(match.group(1)))
        return sorted(dates, reverse=True)


# Short alias for callers that use the generic store name.
PeripheralStore = ResearchPeripheralStore


__all__ = [
    "CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP",
    "PERIPHERAL_SOURCES",
    "PeripheralStore",
    "ResearchPeripheralStore",
    "validate_research_peripheral",
]
