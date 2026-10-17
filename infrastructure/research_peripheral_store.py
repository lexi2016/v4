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
_LATE_RECOVERY_MAX_AGE = timedelta(hours=24)
_LEGACY_MARKET_SNAPSHOT_RECEIPT_FIELDS = frozenset({
    "market_snapshot_captured_at",
    "market_snapshot_source_response_sha256",
})


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
    from infrastructure._research_peripheral_store_parts.primitives import __validate_item_list_body as _v4_impl
    return _v4_impl(globals(), value, field)


def _validate_us_session_captures(value: Any) -> list[dict[str, Any]]:
    from infrastructure._research_peripheral_store_parts.session_validation import __validate_us_session_captures_body as _v4_impl
    return _v4_impl(globals(), value)


def _validate_market_snapshot(value: Any) -> dict[str, Any]:
    from infrastructure._research_peripheral_store_parts.market_validation import __validate_market_snapshot_body as _v4_impl
    return _v4_impl(globals(), value)


def validate_research_peripheral(
    payload: Mapping[str, Any],
    *,
    expected_trade_date: str | None = None,
    expected_source: str | None = None,
) -> tuple[str, str]:
    from infrastructure._research_peripheral_store_parts.envelope_validation import _validate_research_peripheral_body as _v4_impl
    return _v4_impl(globals(), payload, expected_trade_date=expected_trade_date, expected_source=expected_source)


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
        from infrastructure._research_peripheral_store_parts.publish_read import _ResearchPeripheralStore__receipt_body as _v4_impl
        return _v4_impl(globals(), cls, payload, digest)

    @classmethod
    def _receipt_matches(
        cls,
        payload: Mapping[str, Any],
        digest: str,
        stored_receipt: Any,
    ) -> bool:
        from infrastructure._research_peripheral_store_parts.publish_read import _ResearchPeripheralStore_receipt_matches_body as _v4_impl
        return _v4_impl(globals(), cls, payload, digest, stored_receipt)

    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from infrastructure._research_peripheral_store_parts.publish_read import _ResearchPeripheralStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload)

    def replace(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str,
        reason: str,
    ) -> dict[str, Any]:
        """CAS-replace one exact source while preserving its previous payload."""
        from infrastructure._research_peripheral_store_parts.replacement import _ResearchPeripheralStore_replace_body as _v4_impl
        return _v4_impl(globals(), self, payload, expected_sha256=expected_sha256, reason=reason)

    def publish_historical_backfill(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish a development-only retrospective source artifact.

        Historical backfills live outside the exact-date live artifact so they
        cannot silently replace an original-time capture.  The payload itself
        carries the explicit ``HISTORICAL_BACKFILL`` identity and remains
        research-only.
        """
        from infrastructure._research_peripheral_store_parts.historical_backfill import _ResearchPeripheralStore_publish_historical_backfill_body as _v4_impl
        return _v4_impl(globals(), self, payload)

    def read_historical_backfill(
        self,
        trade_date: str,
        source: str = "external_finance",
    ) -> dict[str, Any] | None:
        from infrastructure._research_peripheral_store_parts.historical_backfill import _ResearchPeripheralStore_read_historical_backfill_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, source)

    def record_refresh_attempt(
        self,
        attempted_payload: Mapping[str, Any],
        *,
        retained_payload: Mapping[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """Record a failed refresh without replacing a verified READY value."""
        from infrastructure._research_peripheral_store_parts.refresh_audit import _ResearchPeripheralStore_record_refresh_attempt_body as _v4_impl
        return _v4_impl(globals(), self, attempted_payload, retained_payload=retained_payload, reason=reason)

    def read_exact(self, trade_date: str, source: str) -> dict[str, Any] | None:
        from infrastructure._research_peripheral_store_parts.publish_read import _ResearchPeripheralStore_read_exact_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, source)

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
