"""US-session research captures and development-only historical backfill.

This module keeps the US feed on the existing ``external_finance`` producer
and exact-date store.  It adds explicit session identity, a compare-and-merge
operation for the two US captures, and a separate historical backfill lane.
The latter is deliberately not an original-time capture and never replaces a
live artifact.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import re
from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from infrastructure.data_store import _date, _sha256
from infrastructure.research_peripheral_store import (
    ResearchPeripheralStore,
    validate_research_peripheral,
)
from infrastructure.http_transport import (
    FetchResult,
    ProxyAwareHTTPTransport,
    TransportError,
)
from ops.materialize_research_peripherals import (
    DEFAULT_SUBSCRIPTIONS,
    FetchFn,
    OriginalUrlResolver,
    TranslateFn,
    build_external_finance_payload,
    clean_text,
    fetch_url,
    isoformat_utc,
    overview_from_details,
)

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
US_SESSION_TIMEZONE = "America/New_York"
US_TZ = ZoneInfo(US_SESSION_TIMEZONE)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
US_CAPTURE_PHASES = ("PRE_OPEN", "POST_CLOSE")
HISTORICAL_BACKFILL_PHASE = "HISTORICAL_BACKFILL"
ORIGINAL_TIME_CAPTURE = "ORIGINAL_TIME_CAPTURE"
HISTORICAL_BACKFILL = "HISTORICAL_BACKFILL"
MANUAL_RECOVERY = "MANUAL_RECOVERY"
MIXED_CAPTURE = "MIXED"
MARKET_SNAPSHOT_SCHEMA_VERSION = "v3_5.us_market_snapshot.v1"
MARKET_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1"
TENCENT_QUOTE_ENDPOINT = "https://qt.gtimg.cn/q="
TENCENT_PROVIDER = "Tencent qt.gtimg.cn"
QUOTE_CHANGE_TOLERANCE = 1e-3
CANONICAL_THEME_GROUP = "GLOBAL_INDUSTRY"
QuoteFetch = Callable[[str, int], bytes | str | Mapping[str, Any] | FetchResult]

_QUOTE_HARD_FAILURES = frozenset(
    {
        "QUOTE_RECORD_INVALID",
        "QUOTE_LAST_INVALID",
        "QUOTE_PREVIOUS_CLOSE_INVALID",
        "QUOTE_PREVIOUS_CLOSE_ZERO",
        "QUOTE_PCT_CHANGE_INVALID",
        "QUOTE_PCT_CHANGE_MISMATCH",
        "QUOTE_SESSION_TIMESTAMP_INVALID",
        "QUOTE_SESSION_DATE_MISMATCH_CAPTURE",
    }
)

# These are deliberately transparent proxies for research display.  They are
# not claims that an ETF or basket is the underlying industry index itself.
GLOBAL_INDUSTRY_PROXY_MAP: tuple[dict[str, Any], ...] = (
    {"label": "AI算力", "group": CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("NVDA", "AVGO", "AMD")},
    {"label": "CPO", "group": CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("COHR", "LITE", "CIEN")},
    {"label": "半导体", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("SOXX",)},
    {"label": "存储", "group": CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("MU", "WDC", "STX")},
    {"label": "数据中心", "group": CANONICAL_THEME_GROUP, "mapping_type": "stock_basket_proxy", "proxy_symbols": ("VRT", "DLR", "EQIX")},
    {"label": "云计算", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("CLOU",)},
    {"label": "商业航天", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ARKX",)},
    {"label": "卫星", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("UFO",)},
    {"label": "机器人", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("BOTZ",)},
    {"label": "自动驾驶", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("DRIV",)},
    {"label": "核电", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("NLR",)},
    {"label": "电网", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("GRID",)},
    {"label": "军工", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ITA",)},
    {"label": "新能源", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("ICLN",)},
    {"label": "光伏", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("TAN",)},
    {"label": "锂电池", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("LIT",)},
    {"label": "石油", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("XLE",)},
    {"label": "天然气", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("FCG",)},
    {"label": "铜/有色", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("COPX",)},
    {"label": "黄金", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("GLD",)},
    {"label": "银行金融", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("KBE",)},
    {"label": "生物医药", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("XBI",)},
    {"label": "消费", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_basket_proxy", "proxy_symbols": ("XLY", "XLP")},
    {"label": "稀土", "group": CANONICAL_THEME_GROUP, "mapping_type": "etf_proxy", "proxy_symbols": ("REMX",)},
)
GLOBAL_INDUSTRY_LABELS = tuple(item["label"] for item in GLOBAL_INDUSTRY_PROXY_MAP)
_SAFE_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_QUOTE_DATE = re.compile(r"(?<!\d)(20\d{2})[-/]?(\d{2})[-/]?(\d{2})(?!\d)")
_QUOTE_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")
_TENCENT_SOURCE_TIMESTAMP_FIELD = 30
_TENCENT_COMPACT_TIMESTAMP = re.compile(r"^\d{14}$")
_TENCENT_DASHED_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_PHASE_TIMES: dict[str, tuple[time, time]] = {
    # The instant at the start of each five-minute bounded capture window is
    # the contract's scheduled event time.  ZoneInfo handles DST transitions.
    "PRE_OPEN": (time(9, 0), time(9, 5)),
    "POST_CLOSE": (time(16, 15), time(16, 20)),
}

# A late recovery is limited to the latest completed official session and
# expires 24 hours after its natural POST_CLOSE window starts. The explicit
# flag is the only way to enter this path; the scheduler never supplies it.
LATE_POST_CLOSE_CAPTURE_MODE = "CONTROLLED_LATE_POST_CLOSE"
LATE_POST_CLOSE_CAPTURE_REASON = "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY"
LATE_POST_CLOSE_RECOVERY_END = time(20, 0)
LATE_POST_CLOSE_MAX_AGE = timedelta(hours=24)
MANUAL_LATE_POST_CLOSE_CAPTURE_REASON = "MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION"


def _session_date(value: str) -> date:
    normalized = _date(str(value))
    return datetime.strptime(normalized, "%Y%m%d").date()


def _phase(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {*US_CAPTURE_PHASES, HISTORICAL_BACKFILL_PHASE}:
        raise ValueError("capture_phase must be PRE_OPEN, POST_CLOSE, or HISTORICAL_BACKFILL")
    return normalized


def us_market_day_certification(us_session_date: str) -> dict[str, str]:
    """Certify 2026 NYSE core-session identity without relaxing quote gates.

    The static calendar is an owned contract derived from the official NYSE
    holiday/trading-hours schedule.  Provider session-date and raw-response
    verification remain separate mandatory checks in the snapshot path.
    """
    from ops._us_market_digest_parts.cli_primitives import _us_market_day_certification_body as _v4_impl
    return _v4_impl(globals(), us_session_date)


def us_capture_window(
    us_session_date: str,
    capture_phase: str,
) -> tuple[datetime, datetime]:
    """Return a local, DST-aware capture window for one US session date."""
    from ops._us_market_digest_parts.session_windows import _us_capture_window_body as _v4_impl
    return _v4_impl(globals(), us_session_date, capture_phase)


def resolve_capture_for_shanghai_slot(
    business_date: str,
    slot: str,
) -> dict[str, str]:
    """Resolve a fixed Shanghai scheduler slot to an explicit US phase.

    The scheduler keeps one slot for each possible daylight-saving offset.  We
    resolve the instant through ``America/New_York`` instead of hard-coding a
    seasonal month table.  A slot that is not the active five-minute capture
    window fails closed so a second seasonal slot cannot create a duplicate
    capture or be mistaken for a market-day decision.
    """
    from ops._us_market_digest_parts.session_windows import _resolve_capture_for_shanghai_slot_body as _v4_impl
    return _v4_impl(globals(), business_date, slot)


def _parse_capture_timestamp(value: datetime | str | None) -> datetime:
    from ops._us_market_digest_parts.capture_metadata import __parse_capture_timestamp_body as _v4_impl
    return _v4_impl(globals(), value)


def _capture_now(value: datetime | str | None = None) -> datetime:
    """Return an aware, second-resolution instant in the US session zone."""
    if value is None:
        parsed = datetime.now(US_TZ)
    else:
        parsed = _parse_capture_timestamp(value).astimezone(US_TZ)
    return parsed.replace(microsecond=0)


def us_post_close_recovery_window(
    us_session_date: str,
) -> tuple[datetime, datetime]:
    """Return the bounded controlled-recovery window for one US session."""
    from ops._us_market_digest_parts.session_windows import _us_post_close_recovery_window_body as _v4_impl
    return _v4_impl(globals(), us_session_date)


def _late_post_close_capture_id(
    us_session_date: str,
    captured_at: datetime | str,
) -> str:
    """Give each actual late-capture instant a stable retry identity."""
    normalized_date = _date(str(us_session_date))
    instant = _parse_capture_timestamp(captured_at).astimezone(US_TZ).replace(microsecond=0)
    stable_seed = f"late|{normalized_date}|POST_CLOSE|{instant.isoformat()}"
    return hashlib.sha256(stable_seed.encode("utf-8")).hexdigest()[:24]


def _validate_late_post_close_window(
    us_session_date: str,
    *,
    now: datetime | str | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Validate the current New York instant for a late reuse or capture.

    Reuse is a read-only idempotency operation.  It must be admitted only for
    the requested US session while the bounded recovery window is open, but it
    must not require the caller's old capture timestamp to equal the current
    second.  The stricter timestamp check remains in
    ``_validate_late_post_close_context`` for a new network capture.
    """
    from ops._us_market_digest_parts.session_windows import __validate_late_post_close_window_body as _v4_impl
    return _v4_impl(globals(), us_session_date, now=now)


def _validate_late_post_close_context(
    us_session_date: str,
    *,
    captured_at: datetime | str | None,
    now: datetime | str | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Validate and return ``(now_local, capture_local, recovery_end)``.

    ``now`` is an internal clock seam for deterministic tests.  Production
    callers leave it unset, so the check always uses the real New York clock.
    The captured timestamp must be the current capture instant at
    second-resolution; accepting an earlier timestamp would silently turn a
    late replay into a fabricated in-window observation.
    """
    from ops._us_market_digest_parts.session_windows import __validate_late_post_close_context_body as _v4_impl
    return _v4_impl(globals(), us_session_date, captured_at=captured_at, now=now)


def _deterministic_capture_id(us_session_date: str, capture_phase: str) -> str:
    """Return the stable identity for one scheduled session/phase."""
    normalized_date = _date(str(us_session_date))
    normalized_phase = _phase(capture_phase)
    start, _ = us_capture_window(normalized_date, normalized_phase)
    stable_seed = f"{normalized_date}|{normalized_phase}|{start.isoformat()}"
    return hashlib.sha256(stable_seed.encode("utf-8")).hexdigest()[:24]


def build_capture_metadata(
    us_session_date: str,
    capture_phase: str,
    *,
    captured_at: datetime | str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
    capture_origin: str | None = None,
    original_time_capture: bool | None = None,
    allow_late_post_close: bool = False,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Build the explicit identity carried by every US capture."""
    from ops._us_market_digest_parts.capture_metadata import _build_capture_metadata_body as _v4_impl
    return _v4_impl(globals(), us_session_date, capture_phase, captured_at=captured_at, capture_id=capture_id, run_id=run_id, capture_origin=capture_origin, original_time_capture=original_time_capture, allow_late_post_close=allow_late_post_close, now=now)


def google_rss_historical_url(query: str, us_session_date: str) -> str:
    """Build a date-bounded Google News RSS discovery URL.

    Google News remains a discovery surface: the URL is retained, while the
    source body is never fetched.  The date boundary is a provider query
    constraint, not proof of original-time capture.
    """
    selected = _session_date(us_session_date)
    next_date = selected + timedelta(days=1)
    bounded_query = f"{query} after:{selected.isoformat()} before:{next_date.isoformat()}"
    return f"{GOOGLE_NEWS_RSS}?{urlencode({'q': bounded_query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"


_US_FALLBACK_SUBSCRIPTION_IDS = frozenset(
    {"ai_compute_chip", "robotics_autonomous", "commercial_space", "biopharma_ma"}
)
_US_EQUITY_FALLBACK_SUBSCRIPTION: dict[str, Any] = {
    "id": "US_EQUITY",
    "display_name": "US equities",
    "query": (
        "(US stocks OR US equities OR S&P 500 OR Nasdaq OR Dow Jones OR Wall Street) "
        "(market OR shares OR earnings OR policy)"
    ),
    "theme_bucket": "us_equity",
    "market_scopes": ["US_EQUITY"],
}


def _us_subscriptions() -> tuple[Mapping[str, Any], ...]:
    """Return the five US feeds across both reviewed materializer contracts.

    The newer reviewed materializer annotates ``DEFAULT_SUBSCRIPTIONS`` with
    market scopes.  The frozen scheduler parent predates that field, so its
    equivalent four US themed subscriptions need an explicit compatibility
    selection plus the US equities feed.  Keeping this adapter in the
    candidate producer avoids changing the parent materializer or creating a
    second feed producer.
    """
    from ops._us_market_digest_parts.historical_payload import __us_subscriptions_body as _v4_impl
    return _v4_impl(globals())


def _historical_subscriptions(session_date: date | str) -> tuple[Mapping[str, Any], ...]:
    """Add a provider date bound when the parent has no URL-builder seam."""
    from ops._us_market_digest_parts.historical_payload import __historical_subscriptions_body as _v4_impl
    return _v4_impl(globals(), session_date)


def _normalize_quote_symbol(value: Any, requested: set[str]) -> str | None:
    candidate = str(value or "").strip().replace(".", ".").upper()
    if candidate.startswith("V_"):
        candidate = candidate[2:]
    if candidate.startswith("US."):
        candidate = candidate[3:]
    elif candidate.startswith("US"):
        candidate = candidate[2:]
    if candidate in requested and _SAFE_US_SYMBOL.fullmatch(candidate):
        return candidate
    return None


def _decode_tencent_body(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        # Tencent commonly serves this endpoint as GBK.  UTF-8 is tried first
        # so a test seam or a future provider response keeps its exact text.
        for encoding in ("utf-8-sig", "gb18030", "gbk"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("gb18030", errors="replace")
    return str(raw)


def _response_sha256(raw: bytes | str | Mapping[str, Any]) -> str:
    """Hash the exact provider body retained by a quote snapshot."""
    if isinstance(raw, bytes):
        return hashlib.sha256(raw).hexdigest()
    if isinstance(raw, str):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _sha256(raw)


def _quote_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"--", "-", "N/A", "null", "None"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _normalize_quote_date(value: Any) -> str | None:
    match = _QUOTE_DATE.search(str(value or ""))
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime.strptime(f"{year}{month}{day}", "%Y%m%d").strftime("%Y%m%d")
    except ValueError:
        return None


def _normalize_quote_time(value: Any) -> str | None:
    match = _QUOTE_TIME.search(str(value or ""))
    if not match:
        return None
    hour, minute, second = match.groups()
    if int(hour) > 23 or int(minute) > 59 or (second is not None and int(second) > 59):
        return None
    return f"{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"


def _normalize_tencent_compact_timestamp(value: Any) -> tuple[str, str] | None:
    """Parse Tencent field-30's strict compact or dashed observation timestamp.

    Tencent's US quote response has no labels in its tilde-delimited fields.
    A timestamp is therefore trusted only when it is the complete value of the
    documented field 30. This helper deliberately does not scan arbitrary
    provider text for date/time fragments.
    """
    from ops._us_market_digest_parts.quote_parsing import __normalize_tencent_compact_timestamp_body as _v4_impl
    return _v4_impl(globals(), value)


def _mapping_value(record: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None and value != "":
            return value
    return None


def _mapping_value_present(record: Mapping[str, Any], *keys: str) -> tuple[bool, Any]:
    """Return whether an explicit provider field exists, including invalid values."""
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for key in keys:
        normalized = key.lower()
        if normalized in lowered:
            return True, lowered[normalized]
    return False, None


def _parse_tencent_record_diagnostic(
    symbol: str,
    value: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    from ops._us_market_digest_parts.quote_parsing import __parse_tencent_record_diagnostic_body as _v4_impl
    return _v4_impl(globals(), symbol, value)


def _parse_tencent_record(symbol: str, value: Any) -> dict[str, Any] | None:
    record, _ = _parse_tencent_record_diagnostic(symbol, value)
    return record


def parse_tencent_quotes_diagnostic(
    raw: bytes | str | Mapping[str, Any],
    requested_symbols: Sequence[str],
    *,
    expected_session_date: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Parse requested quotes and retain per-symbol fail-closed reasons."""
    from ops._us_market_digest_parts.quote_parsing import _parse_tencent_quotes_diagnostic_body as _v4_impl
    return _v4_impl(globals(), raw, requested_symbols, expected_session_date=expected_session_date)


def parse_tencent_quotes(
    raw: bytes | str | Mapping[str, Any],
    requested_symbols: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Parse only requested US symbols from Tencent's safe text response.

    The parser accepts the provider's ``v_usSYMBOL="...~..."`` format and a
    mapping-shaped fixture for deterministic tests.  It never evaluates or
    executes provider text.
    """
    from ops._us_market_digest_parts.quote_parsing import _parse_tencent_quotes_body as _v4_impl
    return _v4_impl(globals(), raw, requested_symbols)


def _empty_market_snapshot(
    us_session_date: str,
    *,
    capture_phase: str,
    captured_at: datetime | str,
    reasons: Sequence[str],
    source_response_sha256: str = "",
    provider_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from ops._us_market_digest_parts.market_snapshot import __empty_market_snapshot_body as _v4_impl
    return _v4_impl(globals(), us_session_date, capture_phase=capture_phase, captured_at=captured_at, reasons=reasons, source_response_sha256=source_response_sha256, provider_receipt=provider_receipt)


def build_us_market_snapshot(
    us_session_date: str,
    *,
    capture_phase: str = "POST_CLOSE",
    captured_at: datetime | str,
    fetch_quotes: QuoteFetch | None = None,
    fetch_quote: QuoteFetch | None = None,
    transport: ProxyAwareHTTPTransport | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Capture the fixed 24-theme proxy map inside the existing US producer."""
    from ops._us_market_digest_parts.market_snapshot import _build_us_market_snapshot_body as _v4_impl
    snapshot = _v4_impl(globals(), us_session_date, capture_phase=capture_phase, captured_at=captured_at, fetch_quotes=fetch_quotes, fetch_quote=fetch_quote, transport=transport, timeout=timeout)
    return _clear_same_session_time_dispersion(snapshot)


def _clear_same_session_time_dispersion(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Treat same-session quote seconds as diagnostics, not mixed sessions.

    The source timestamp remains visible on every quote and theme row. Only
    the false-positive time-dispersion reason is removed, and only when the
    provider dates are a single exact session. Cross-date, missing-time,
    parser, arithmetic, coverage, and other quality failures remain intact.
    """
    result = copy.deepcopy(dict(snapshot))
    dates = result.get("provider_session_dates")
    dates = dates if isinstance(dates, list) else []
    if len(set(str(value) for value in dates if value)) != 1:
        return result
    session_date = str(dates[0])
    reasons = result.get("cannot_confirm")
    reasons = list(reasons) if isinstance(reasons, list) else []
    result["cannot_confirm"] = [value for value in reasons if value != "QUOTE_SESSION_TIME_MIXED"]
    rows = result.get("rows")
    rows = rows if isinstance(rows, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_reasons = row.get("cannot_confirm")
        row_reasons = list(row_reasons) if isinstance(row_reasons, list) else []
        row["cannot_confirm"] = [value for value in row_reasons if value != "QUOTE_SESSION_TIME_MIXED"]
        row_dates = row.get("quote_session_dates")
        row_times = row.get("quote_session_times")
        requested = row.get("requested_symbol_count")
        available = row.get("available_symbol_count")
        if (row_dates == [session_date] and isinstance(row_times, list) and row_times
                and type(requested) is int and type(available) is int and requested == available
                and not row.get("missing_symbols") and not row["cannot_confirm"]):
            row["status"] = "READY"

    requested = result.get("requested_symbol_count")
    available = result.get("available_symbol_count")
    all_rows_ready = len(rows) == len(GLOBAL_INDUSTRY_PROXY_MAP) and all(
        isinstance(row, Mapping) and row.get("status") == "READY" for row in rows
    )
    complete = (type(requested) is int and type(available) is int and requested == available
                and all_rows_ready and result.get("provider_session_dates") == [session_date])
    remaining = list(result.get("cannot_confirm") or [])
    if complete and set(remaining).issubset({"MARKET_SNAPSHOT_INCOMPLETE"}):
        result["cannot_confirm"] = []
        result["status"] = "READY"
    return result


# Short aliases make the producer seam discoverable without creating another
# producer or changing the scheduled workload identity.
build_market_snapshot = build_us_market_snapshot
build_global_industry_market_snapshot = build_us_market_snapshot


def _annotate_payload(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    from ops._us_market_digest_parts.phase_payload import __annotate_payload_body as _v4_impl
    return _v4_impl(globals(), payload, metadata)


def build_us_market_phase_payload(
    trade_date: str,
    *,
    capture_phase: str,
    us_session_date: str | None = None,
    fetched_at: datetime | str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
    fetch_rss: FetchFn | None = None,
    fetch_quotes: QuoteFetch | None = None,
    fetch_quote: QuoteFetch | None = None,
    transport: ProxyAwareHTTPTransport | None = None,
    translate_text: TranslateFn | None = None,
    resolve_original_url: OriginalUrlResolver | None = None,
    allow_late_post_close: bool = False,
    rss_only_recovery: bool = False,
    now: datetime | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch and label one explicit US pre-open or post-close capture."""
    from ops._us_market_digest_parts.phase_payload import _build_us_market_phase_payload_body as _v4_impl
    return _v4_impl(globals(), trade_date, capture_phase=capture_phase, us_session_date=us_session_date, fetched_at=fetched_at, capture_id=capture_id, run_id=run_id, fetch_rss=fetch_rss, fetch_quotes=fetch_quotes, fetch_quote=fetch_quote, transport=transport, translate_text=translate_text, resolve_original_url=resolve_original_url, allow_late_post_close=allow_late_post_close, rss_only_recovery=rss_only_recovery, now=now, **kwargs)


def build_us_historical_backfill_payload(
    trade_date: str,
    *,
    development_dates: Collection[str],
    fetched_at: datetime | str | None = None,
    fetch_rss: FetchFn | None = None,
    translate_text: TranslateFn | None = None,
    resolve_original_url: OriginalUrlResolver | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a retrospective payload only for an explicit development allowlist."""
    from ops._us_market_digest_parts.historical_payload import _build_us_historical_backfill_payload_body as _v4_impl
    return _v4_impl(globals(), trade_date, development_dates=development_dates, fetched_at=fetched_at, fetch_rss=fetch_rss, translate_text=translate_text, resolve_original_url=resolve_original_url, **kwargs)


def _ordered_union(*values: Any) -> list[str]:
    from ops._us_market_digest_parts.capture_merge import __ordered_union_body as _v4_impl
    return _v4_impl(globals(), *values)


def _row_base_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        clean_text(row.get("id") or row.get("title")).lower(),
        clean_text(row.get("source_name") or row.get("source")).lower(),
        clean_text(row.get("published_at")),
    )


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    base = _row_base_key(row)
    # Keep the same report twice when it was deliberately observed at two
    # different session phases; same-phase duplicates still merge.
    return (*base, clean_text(row.get("capture_phase")))


def _merge_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    incoming_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from ops._us_market_digest_parts.capture_merge import __merge_rows_body as _v4_impl
    return _v4_impl(globals(), existing_rows, incoming_rows)


def _merge_captures(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from ops._us_market_digest_parts.capture_merge import __merge_captures_body as _v4_impl
    return _v4_impl(globals(), existing, incoming)


def _merge_receipts(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from ops._us_market_digest_parts.capture_merge import __merge_receipts_body as _v4_impl
    return _v4_impl(globals(), existing, incoming)


def _snapshot_timestamp(snapshot: Mapping[str, Any] | None) -> datetime | None:
    if not isinstance(snapshot, Mapping):
        return None
    value = snapshot.get("captured_at") or snapshot.get("generated_at")
    try:
        return _parse_capture_timestamp(str(value)) if value else None
    except ValueError:
        return None


def _is_late_capture_identity(value: Any) -> bool:
    """Treat either late marker as late for fail-closed reuse decisions."""
    return isinstance(value, Mapping) and (
        value.get("late") is True
        or value.get("capture_mode") == LATE_POST_CLOSE_CAPTURE_MODE
    )


def _merge_market_snapshots(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the newest scheduled quote snapshot in one exact-date artifact."""
    from ops._us_market_digest_parts.snapshot_merge import __merge_market_snapshots_body as _v4_impl
    merged = _v4_impl(globals(), existing, incoming)
    return _clear_same_session_time_dispersion(merged) if merged is not None else None


def merge_us_phase_payloads(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    preserve_existing_market_snapshot: bool = False,
) -> dict[str, Any]:
    """Merge a new phase into one exact-date external-finance artifact."""
    from ops._us_market_digest_parts.phase_merge import _merge_us_phase_payloads_body as _v4_impl
    return _v4_impl(globals(), existing, incoming, preserve_existing_market_snapshot=preserve_existing_market_snapshot)


def materialize_us_market_phase(
    *, data_root: Path, trade_date: str, capture_phase: str,
    allow_late_post_close: bool = False,
    rss_only_recovery: bool = False,
    now: datetime | str | None = None, **kwargs: Any,
) -> dict[str, Any]:
    """One existing capture owner per exact artifact date, including retries.

    All fetch, merge and immutable evidence logic remains the reviewed
    producer below. The shared V4 lock only closes concurrent request reuse.
    """
    from ops._us_market_digest_parts.phase_publication import _materialize_us_market_phase_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, capture_phase=capture_phase, allow_late_post_close=allow_late_post_close, rss_only_recovery=rss_only_recovery, now=now, **kwargs)


def _materialize_us_market_phase_locked(
    *,
    data_root: Path,
    trade_date: str,
    capture_phase: str,
    allow_late_post_close: bool = False,
    rss_only_recovery: bool = False,
    now: datetime | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Materialize one phase and CAS-merge it with the exact-date artifact."""
    from ops._us_market_digest_parts.phase_publication import __materialize_us_market_phase_locked_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, capture_phase=capture_phase, allow_late_post_close=allow_late_post_close, rss_only_recovery=rss_only_recovery, now=now, **kwargs)


def materialize_us_historical_backfill(
    *,
    data_root: Path,
    trade_date: str,
    development_dates: Collection[str],
    **kwargs: Any,
) -> dict[str, Any]:
    from ops._us_market_digest_parts.phase_publication import _materialize_us_historical_backfill_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, development_dates=development_dates, **kwargs)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    from ops._us_market_digest_parts.cli_primitives import _parse_args_body as _v4_impl
    return _v4_impl(globals(), argv)


def main(argv: Sequence[str] | None = None) -> int:
    from ops._us_market_digest_parts.cli_primitives import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


__all__ = [
    "GOOGLE_NEWS_RSS",
    "GLOBAL_INDUSTRY_LABELS",
    "GLOBAL_INDUSTRY_PROXY_MAP",
    "HISTORICAL_BACKFILL",
    "HISTORICAL_BACKFILL_PHASE",
    "LATE_POST_CLOSE_CAPTURE_MODE",
    "LATE_POST_CLOSE_CAPTURE_REASON",
    "LATE_POST_CLOSE_RECOVERY_END",
    "MARKET_MAPPING_VERSION",
    "MARKET_SNAPSHOT_SCHEMA_VERSION",
    "ORIGINAL_TIME_CAPTURE",
    "QUOTE_CHANGE_TOLERANCE",
    "TENCENT_QUOTE_ENDPOINT",
    "TENCENT_PROVIDER",
    "US_CAPTURE_PHASES",
    "US_SESSION_TIMEZONE",
    "build_global_industry_market_snapshot",
    "build_market_snapshot",
    "build_capture_metadata",
    "build_us_market_snapshot",
    "build_us_historical_backfill_payload",
    "build_us_market_phase_payload",
    "google_rss_historical_url",
    "main",
    "materialize_us_historical_backfill",
    "materialize_us_market_phase",
    "merge_us_phase_payloads",
    "parse_tencent_quotes",
    "parse_tencent_quotes_diagnostic",
    "parse_args",
    "resolve_capture_for_shanghai_slot",
    "us_post_close_recovery_window",
    "us_market_day_certification",
    "us_capture_window",
]


if __name__ == "__main__":
    raise SystemExit(main())
