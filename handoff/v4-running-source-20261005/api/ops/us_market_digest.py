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

# A late recovery is deliberately narrower than an arbitrary replay. It is
# allowed only for the latest completed official session and only for the
# first 24 hours after that session's scheduled close capture. The explicit
# flag is the only way to enter this path; the scheduler never supplies it.
LATE_POST_CLOSE_CAPTURE_MODE = "CONTROLLED_LATE_POST_CLOSE"
LATE_POST_CLOSE_CAPTURE_REASON = "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY"
MANUAL_LATE_POST_CLOSE_CAPTURE_REASON = "MANUAL_RSS_ONLY_RECOVERY_LATEST_COMPLETED_SESSION"
LATE_POST_CLOSE_MAX_AGE = timedelta(hours=24)


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
    from contracts.us_equity_calendar import session

    try:
        selected = session(us_session_date)
    except ValueError as exc:
        if str(exc) == "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE":
            return {"status": "CANNOT_CONFIRM", "reason": str(exc)}
        raise
    if selected.close_at is None:
        return {
            "status": "CLOSED",
            "reason": selected.state,
            "source_url": selected.source_url,
        }
    return {
        "status": "VERIFIED",
        "reason": selected.state,
        "close_at": selected.close_at.isoformat(),
        "source_url": selected.source_url,
    }


def us_capture_window(
    us_session_date: str,
    capture_phase: str,
) -> tuple[datetime, datetime]:
    """Return a local, DST-aware capture window for one US session date."""
    selected = _session_date(us_session_date)
    phase = _phase(capture_phase)
    if phase == HISTORICAL_BACKFILL_PHASE:
        start = datetime.combine(selected, time.min, tzinfo=US_TZ)
        end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=US_TZ)
        return start, end
    start_time, end_time = _PHASE_TIMES[phase]
    return (
        datetime.combine(selected, start_time, tzinfo=US_TZ),
        datetime.combine(selected, end_time, tzinfo=US_TZ),
    )


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
    selected = _session_date(business_date)
    if not isinstance(slot, str) or len(slot) != 4 or not slot.isdigit():
        raise ValueError("US_CAPTURE_SLOT_INVALID")
    hour, minute = int(slot[:2]), int(slot[2:])
    if hour > 23 or minute > 59:
        raise ValueError("US_CAPTURE_SLOT_INVALID")
    shanghai_instant = datetime.combine(
        selected,
        time(hour, minute),
        tzinfo=SHANGHAI_TZ,
    )
    us_instant = shanghai_instant.astimezone(US_TZ)
    us_session_date = us_instant.date().strftime("%Y%m%d")
    for phase in US_CAPTURE_PHASES:
        start, end = us_capture_window(us_session_date, phase)
        if start <= us_instant < end:
            return {
                "capture_phase": phase,
                "us_session_date": us_session_date,
            }
    raise ValueError("US_CAPTURE_SLOT_NOT_DUE")


def _parse_capture_timestamp(value: datetime | str | None) -> datetime:
    if value is None:
        raise ValueError("US_CAPTURE_TIMESTAMP_REQUIRED")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("US_CAPTURE_TIMESTAMP_INVALID") from error
    else:
        raise ValueError("US_CAPTURE_TIMESTAMP_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("US_CAPTURE_TIMESTAMP_INVALID")
    return parsed


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
    """Return a bounded recovery window for the latest completed session."""
    natural_start, _ = us_capture_window(str(us_session_date), "POST_CLOSE")
    return natural_start, natural_start + LATE_POST_CLOSE_MAX_AGE


def _late_post_close_capture_id(
    us_session_date: str,
    captured_at: datetime | str,
) -> str:
    """Give a late recovery its own stable-instant identity, separate from schedule."""
    session_date = _date(str(us_session_date))
    instant = _parse_capture_timestamp(captured_at).astimezone(US_TZ).replace(microsecond=0)
    stable_seed = f"late|{session_date}|POST_CLOSE|{instant.isoformat()}"
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
    session_date = _date(us_session_date)
    natural_start, recovery_end = us_post_close_recovery_window(session_date)
    now_local = _capture_now(now)
    from contracts.us_equity_calendar import latest_completed_session

    try:
        latest = latest_completed_session(now_local)
    except ValueError as error:
        raise ValueError(f"US_LATE_POST_CLOSE_SESSION_RESOLUTION_FAILED:{error}") from error
    if latest.session_date != session_date:
        raise ValueError("US_LATE_POST_CLOSE_NOT_LATEST_COMPLETED_SESSION")
    if now_local < natural_start:
        raise ValueError("US_LATE_POST_CLOSE_NOT_YET_DUE")
    if now_local >= recovery_end:
        raise ValueError("US_LATE_POST_CLOSE_RECOVERY_WINDOW_EXPIRED")
    return now_local, natural_start, recovery_end


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
    session_date = _date(us_session_date)
    now_local, natural_start, recovery_end = _validate_late_post_close_window(
        session_date,
        now=now,
    )
    capture_timestamp = _parse_capture_timestamp(captured_at)
    capture_local = capture_timestamp.astimezone(US_TZ).replace(microsecond=0)
    if not (natural_start <= capture_local < recovery_end):
        raise ValueError("US_LATE_POST_CLOSE_CAPTURE_OUTSIDE_RECOVERY_WINDOW")
    if capture_local.utcoffset() != natural_start.utcoffset():
        raise ValueError("US_LATE_POST_CLOSE_CAPTURE_TIMEZONE_MISMATCH")
    if capture_local > now_local:
        raise ValueError("US_LATE_POST_CLOSE_CAPTURE_IN_FUTURE")
    if capture_local != now_local:
        raise ValueError("US_LATE_POST_CLOSE_CAPTURE_TIMESTAMP_NOT_CURRENT")
    return now_local, capture_local, recovery_end


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
    normalized_date = _date(str(us_session_date))
    normalized_phase = _phase(capture_phase)
    start, end = us_capture_window(normalized_date, normalized_phase)
    if type(allow_late_post_close) is not bool:
        raise ValueError("allow_late_post_close must be boolean")
    if allow_late_post_close and normalized_phase != "POST_CLOSE":
        raise ValueError("US_LATE_POST_CLOSE_ONLY")
    if original_time_capture is not None and type(original_time_capture) is not bool:
        raise ValueError("original_time_capture must be boolean")
    is_original = (
        normalized_phase in US_CAPTURE_PHASES
        if original_time_capture is None
        else bool(original_time_capture)
    )
    origin = capture_origin or (
        ORIGINAL_TIME_CAPTURE if is_original else HISTORICAL_BACKFILL
    )
    if origin not in {ORIGINAL_TIME_CAPTURE, HISTORICAL_BACKFILL, MANUAL_RECOVERY, MIXED_CAPTURE}:
        raise ValueError("unsupported capture_origin")
    if normalized_phase == HISTORICAL_BACKFILL_PHASE and (
        origin != HISTORICAL_BACKFILL or is_original
    ):
        raise ValueError("historical backfill must be explicitly non-original-time")
    if normalized_phase in US_CAPTURE_PHASES:
        manual_late = (
            allow_late_post_close
            and origin == MANUAL_RECOVERY
            and not is_original
        )
        if not manual_late and (
            origin != ORIGINAL_TIME_CAPTURE or not is_original
        ):
            raise ValueError("live capture must be explicitly original-time")
    captured_timestamp = _parse_capture_timestamp(captured_at)
    if normalized_phase in US_CAPTURE_PHASES:
        local_capture = captured_timestamp.astimezone(US_TZ)
        if allow_late_post_close:
            _validate_late_post_close_context(
                normalized_date,
                captured_at=captured_timestamp,
                now=now,
            )
        elif not (start <= local_capture < end) or local_capture.utcoffset() != start.utcoffset():
            raise ValueError("US_CAPTURE_OUTSIDE_WINDOW")
    captured_iso = isoformat_utc(captured_timestamp)
    default_capture_id = (
        _late_post_close_capture_id(normalized_date, captured_timestamp)
        if allow_late_post_close
        else _deterministic_capture_id(normalized_date, normalized_phase)
    )
    normalized_capture_id = str(capture_id or "").strip() or default_capture_id
    normalized_run_id = str(run_id or "").strip() or f"us-rss:{normalized_date}:{normalized_phase}:{normalized_capture_id}"
    metadata = {
        "us_session_date": normalized_date,
        "capture_phase": normalized_phase,
        "session_timezone": US_SESSION_TIMEZONE,
        "capture_window_start": start.isoformat(),
        "capture_window_end": end.isoformat(),
        "capture_id": normalized_capture_id,
        "run_id": normalized_run_id,
        "captured_at": captured_iso,
        "capture_origin": origin,
        "original_time_capture": is_original,
    }
    if allow_late_post_close:
        recovery_start, recovery_end = us_post_close_recovery_window(normalized_date)
        late_reason = (
            MANUAL_LATE_POST_CLOSE_CAPTURE_REASON
            if origin == MANUAL_RECOVERY
            else LATE_POST_CLOSE_CAPTURE_REASON
        )
        metadata.update(
            {
                "capture_mode": LATE_POST_CLOSE_CAPTURE_MODE,
                "reason": late_reason,
                "capture_reason": late_reason,
                "late": True,
                "natural_capture_window_start": start.isoformat(),
                "natural_capture_window_end": end.isoformat(),
                "allowed_recovery_window_start": recovery_start.isoformat(),
                "allowed_recovery_window_end": recovery_end.isoformat(),
            }
        )
    return metadata


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
    scoped = tuple(
        subscription
        for subscription in DEFAULT_SUBSCRIPTIONS
        if "US_EQUITY" in {
            str(scope).strip()
            for scope in (subscription.get("market_scopes") or [])
        }
    )
    if scoped:
        return scoped
    fallback = tuple(
        {
            **dict(subscription),
            "market_scopes": ["US_EQUITY"],
        }
        for subscription in DEFAULT_SUBSCRIPTIONS
        if str(subscription.get("id") or "").strip()
        in _US_FALLBACK_SUBSCRIPTION_IDS
    )
    if fallback:
        return (*fallback, _US_EQUITY_FALLBACK_SUBSCRIPTION)
    return (_US_EQUITY_FALLBACK_SUBSCRIPTION,)


def _historical_subscriptions(session_date: date | str) -> tuple[Mapping[str, Any], ...]:
    """Add a provider date bound when the parent has no URL-builder seam."""
    selected = (
        session_date
        if isinstance(session_date, date) and not isinstance(session_date, datetime)
        else _session_date(str(session_date))
    )
    next_date = selected + timedelta(days=1)
    bounded = []
    for subscription in _us_subscriptions():
        item = dict(subscription)
        item["query"] = (
            f"{clean_text(item.get('query'))} after:{selected.isoformat()} "
            f"before:{next_date.isoformat()}"
        )
        bounded.append(item)
    return tuple(bounded)


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
    text = str(value or "").strip()
    if _TENCENT_COMPACT_TIMESTAMP.fullmatch(text):
        timestamp_format = "%Y%m%d%H%M%S"
    elif _TENCENT_DASHED_TIMESTAMP.fullmatch(text):
        timestamp_format = "%Y-%m-%d %H:%M:%S"
    else:
        return None
    try:
        parsed = datetime.strptime(text, timestamp_format)
    except ValueError:
        return None
    return parsed.strftime("%Y%m%d"), parsed.strftime("%H:%M:%S")


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
    fields: list[Any] = []
    compact_timestamp_present = False
    explicit: Mapping[str, Any] | None = value if isinstance(value, Mapping) else None
    raw_tencent_string = isinstance(value, str)
    if explicit is not None:
        raw_fields = _mapping_value(explicit, "fields", "data", "values")
        if isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes, bytearray)):
            fields = list(raw_fields)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        fields = list(value)
    else:
        fields = str(value).split("~")

    if explicit is not None:
        current = _quote_number(_mapping_value(explicit, "last", "price", "current", "close"))
        previous = _quote_number(
            _mapping_value(explicit, "prev_close", "previous_close", "pre_close", "previous")
        )
        pct_present, pct_value = _mapping_value_present(
            explicit, "pct_change", "change_pct", "change_percent", "percent"
        )
        pct = _quote_number(pct_value) if pct_present else None
        if pct_present and pct is None:
            return None, "QUOTE_PCT_CHANGE_INVALID"
        session_date = _normalize_quote_date(
            _mapping_value(explicit, "session_date", "quote_session_date", "date", "trading_date")
        )
        session_time = _normalize_quote_time(
            _mapping_value(explicit, "session_time", "quote_session_time", "time", "trading_time")
        )
    else:
        # The public Tencent US response places current and previous close at
        # fields 3 and 4.  Small array fixtures with symbol/current/previous
        # are accepted as well, which keeps the parser independently testable.
        current = _quote_number(fields[3] if len(fields) > 4 else (fields[1] if len(fields) > 1 else None))
        previous = _quote_number(fields[4] if len(fields) > 4 else (fields[2] if len(fields) > 2 else None))
        pct = None
        session_date = None
        session_time = None
        # Tencent's documented US string layout stores the observation
        # timestamp in field 30. A raw provider string must carry that field
        # explicitly in one of the two accepted complete formats; scanning
        # fields 5/6 or any other arbitrary text would allow unrelated numbers
        # to become the session identity. Sequence fixtures remain a narrow
        # parser seam and may expose labelled date/time values instead.
        if raw_tencent_string:
            if len(fields) <= _TENCENT_SOURCE_TIMESTAMP_FIELD:
                return None, "QUOTE_SESSION_TIMESTAMP_MISSING"
            if not str(fields[_TENCENT_SOURCE_TIMESTAMP_FIELD] or "").strip():
                return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
            compact_timestamp_present = True
            compact_timestamp = _normalize_tencent_compact_timestamp(
                fields[_TENCENT_SOURCE_TIMESTAMP_FIELD]
            )
            if compact_timestamp is None:
                return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
            session_date, session_time = compact_timestamp
        elif len(fields) > _TENCENT_SOURCE_TIMESTAMP_FIELD:
            timestamp_value = fields[_TENCENT_SOURCE_TIMESTAMP_FIELD]
            if str(timestamp_value or "").strip():
                compact_timestamp_present = True
                compact_timestamp = _normalize_tencent_compact_timestamp(timestamp_value)
                if compact_timestamp is None:
                    return None, "QUOTE_SESSION_TIMESTAMP_INVALID"
                session_date, session_time = compact_timestamp

    if current is None:
        return None, "QUOTE_LAST_INVALID"
    if previous is None:
        return None, "QUOTE_PREVIOUS_CLOSE_INVALID"
    if previous == 0:
        return None, "QUOTE_PREVIOUS_CLOSE_ZERO"
    derived_pct = (current - previous) / previous * 100
    if not math.isfinite(derived_pct):
        return None, "QUOTE_RECORD_INVALID"
    if pct is not None:
        if not math.isfinite(float(pct)):
            return None, "QUOTE_PCT_CHANGE_INVALID"
        if abs(float(pct) - derived_pct) > QUOTE_CHANGE_TOLERANCE:
            return None, "QUOTE_PCT_CHANGE_MISMATCH"
    # The value computed from finite close prices is authoritative.  Provider
    # percent fields are an integrity check only and are never used as a
    # second arithmetic source.
    pct = derived_pct
    # Search all fields for provider session identity.  In Tencent's current
    # layout the date and time are late fields, while future layouts may expose
    # them under different positions.
    if session_date is None and not compact_timestamp_present:
        for field in fields:
            session_date = _normalize_quote_date(field)
            if session_date:
                break
    if session_time is None and not compact_timestamp_present:
        for field in fields:
            session_time = _normalize_quote_time(field)
            if session_time:
                break
    return {
        "symbol": symbol,
        "last": current,
        "previous_close": previous,
        "pct_change": round(float(pct), 6),
        "session_date": session_date,
        "session_time": session_time,
    }, None


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
    requested = {
        symbol
        for symbol in (str(value or "").strip().upper() for value in requested_symbols)
        if _SAFE_US_SYMBOL.fullmatch(symbol)
    }
    if not requested:
        return {}, {}
    expected_date = _date(expected_session_date) if expected_session_date else None
    records: dict[str, Any] = {}
    if isinstance(raw, Mapping):
        root: Mapping[str, Any] = raw
        nested = root.get("data")
        if isinstance(nested, Mapping):
            root = nested
        for key, value in root.items():
            symbol = _normalize_quote_symbol(key, requested)
            if symbol is not None:
                records[symbol] = value
    else:
        text = _decode_tencent_body(raw)
        # Split on semicolons instead of using eval-like parsing.  Quoted
        # provider values do not contain semicolons in the documented format.
        for segment in text.split(";"):
            if '="' not in segment:
                continue
            key, value = segment.split('="', 1)
            symbol = _normalize_quote_symbol(key, requested)
            if symbol is None:
                continue
            records[symbol] = value.rstrip('"')
    parsed: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    for symbol in sorted(records):
        record, reason = _parse_tencent_record_diagnostic(symbol, records[symbol])
        if record is None:
            reasons[symbol] = reason or "QUOTE_RECORD_INVALID"
            continue
        session_date = record.get("session_date")
        if expected_date is not None and session_date != expected_date:
            reasons[symbol] = "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"
            continue
        parsed[symbol] = record
    return parsed, reasons


def parse_tencent_quotes(
    raw: bytes | str | Mapping[str, Any],
    requested_symbols: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Parse only requested US symbols from Tencent's safe text response.

    The parser accepts the provider's ``v_usSYMBOL="...~..."`` format and a
    mapping-shaped fixture for deterministic tests.  It never evaluates or
    executes provider text.
    """
    parsed, _ = parse_tencent_quotes_diagnostic(raw, requested_symbols)
    return parsed


def _empty_market_snapshot(
    us_session_date: str,
    *,
    capture_phase: str,
    captured_at: datetime | str,
    reasons: Sequence[str],
    source_response_sha256: str = "",
    provider_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    captured_iso = isoformat_utc(_parse_capture_timestamp(captured_at))
    requested_symbols = [
        symbol
        for mapping in GLOBAL_INDUSTRY_PROXY_MAP
        for symbol in mapping["proxy_symbols"]
    ]
    unique_symbols = list(dict.fromkeys(requested_symbols))
    rows = []
    for mapping in GLOBAL_INDUSTRY_PROXY_MAP:
        symbols = list(mapping["proxy_symbols"])
        rows.append({
            "label": mapping["label"],
            "group": mapping["group"],
            "mapping_type": mapping["mapping_type"],
            "proxy_symbols": symbols,
            "available_symbols": [],
            "missing_symbols": symbols,
            "requested_symbol_count": len(symbols),
            "available_symbol_count": 0,
            "coverage": {"available": 0, "requested": len(symbols)},
            "coverage_pct": 0.0,
            "change_pct": None,
            "pct_change": None,
            "direction": "CANNOT_CONFIRM",
            "status": "CANNOT_CONFIRM",
            "quote_session_dates": [],
            "quote_session_times": [],
            "cannot_confirm": sorted(set(reasons)),
        })
    result: dict[str, Any] = {
        "schema_version": MARKET_SNAPSHOT_SCHEMA_VERSION,
        "status": "CANNOT_CONFIRM",
        "source": TENCENT_PROVIDER,
        "provider": TENCENT_PROVIDER,
        "provider_url": TENCENT_QUOTE_ENDPOINT,
        "source_response_sha256": source_response_sha256,
        "capture_phase": str(capture_phase),
        "capture_session_date": _date(us_session_date),
        "captured_at": captured_iso,
        "generated_at": captured_iso,
        "mapping_version": MARKET_MAPPING_VERSION,
        "requested_symbol_count": len(unique_symbols),
        "available_symbol_count": 0,
        "provider_session_dates": [],
        "provider_session_times": [],
        "quotes": [],
        "rows": rows,
        "cannot_confirm": sorted(set(reasons)),
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if provider_receipt is not None:
        result["provider_receipt"] = dict(provider_receipt)
    return result


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
    if fetch_quotes is not None and fetch_quote is not None:
        raise ValueError("provide only one quote fetch seam")
    fetcher = fetch_quotes or fetch_quote
    session_date = _date(us_session_date)
    phase = _phase(capture_phase)
    captured_iso = isoformat_utc(_parse_capture_timestamp(captured_at))
    mappings = GLOBAL_INDUSTRY_PROXY_MAP
    # This helper is the quote boundary itself.  Only the scheduled close
    # capture may request provider prices; every other phase gets a complete
    # fail-closed surface without invoking a fetch seam.
    if phase != "POST_CLOSE":
        return _empty_market_snapshot(
            session_date,
            capture_phase=phase,
            captured_at=captured_iso,
            reasons=[
                "MARKET_SNAPSHOT_NOT_DUE_PRE_OPEN"
                if phase == "PRE_OPEN"
                else "MARKET_SNAPSHOT_NOT_DUE_POST_CLOSE"
            ],
        )
    symbols = list(dict.fromkeys(symbol for item in mappings for symbol in item["proxy_symbols"]))
    if any(not _SAFE_US_SYMBOL.fullmatch(symbol) for symbol in symbols):
        raise ValueError("invalid fixed US proxy symbol")
    quote_url = f"{TENCENT_QUOTE_ENDPOINT}{','.join(f'us{symbol}' for symbol in symbols)}"
    reasons: set[str] = set()
    provider_receipt: Mapping[str, Any] | None = None
    source_response_sha256 = ""
    try:
        if fetcher is not None:
            if fetcher is fetch_url:
                active_transport = transport or ProxyAwareHTTPTransport(timeout=timeout)
                response = active_transport.fetch(quote_url, timeout=timeout)
            else:
                response = fetcher(quote_url, timeout)
        else:
            active_transport = transport or ProxyAwareHTTPTransport(timeout=timeout)
            response = active_transport.fetch(quote_url, timeout=timeout)
        if isinstance(response, FetchResult):
            raw: bytes | str | Mapping[str, Any] = response.body
            provider_receipt = response.receipt
        elif isinstance(response, (bytes, str, Mapping)):
            raw = response
        else:
            raise TypeError("quote fetch seam returned unsupported body")
        source_response_sha256 = _response_sha256(raw)
        parsed, parse_reasons = parse_tencent_quotes_diagnostic(
            raw,
            symbols,
            expected_session_date=session_date,
        )
        reasons.update(parse_reasons.values())
        # Keep the aggregate reason deterministic and attributable to the
        # provider record.  The unqualified reason remains for compatibility
        # with existing receipts, while the qualified form identifies the
        # exact symbol that prevented a complete close snapshot.
        reasons.update(
            f"{reason}:{symbol}"
            for symbol, reason in sorted(parse_reasons.items())
        )
    except (TransportError, TimeoutError, OSError, ValueError, TypeError) as error:
        if isinstance(error, TransportError):
            provider_receipt = error.receipt
        reasons.add(f"US_MARKET_QUOTE_FETCH_FAILED:{type(error).__name__}")
        return _empty_market_snapshot(
            session_date,
            capture_phase=phase,
            captured_at=captured_iso,
            reasons=sorted(reasons),
            source_response_sha256=source_response_sha256,
            provider_receipt=provider_receipt,
        )

    if not parsed:
        reasons.add("US_MARKET_QUOTE_RESPONSE_UNPARSED")
    records_by_symbol = parsed
    provider_dates = sorted({
        str(record["session_date"])
        for record in records_by_symbol.values()
        if record.get("session_date")
    })
    provider_times = sorted({
        str(record["session_time"])
        for record in records_by_symbol.values()
        if record.get("session_time")
    })
    if len(provider_dates) > 1:
        reasons.add("QUOTE_SESSION_DATE_MIXED")
    if len(provider_times) > 1:
        reasons.add("QUOTE_SESSION_TIME_MIXED")
    rows: list[dict[str, Any]] = []
    quotes = [
        {
            "symbol": symbol,
            "exchange": "US",
            "session_date": record.get("session_date") or "",
            "session_time": record.get("session_time") or "",
            "last": record.get("last"),
            "previous_close": record.get("previous_close"),
            "change_pct": float(record["pct_change"]),
            "provider": TENCENT_PROVIDER,
        }
        for symbol, record in sorted(records_by_symbol.items())
    ]
    for mapping in mappings:
        proxy_symbols = list(mapping["proxy_symbols"])
        available = [symbol for symbol in proxy_symbols if symbol in records_by_symbol]
        missing = [symbol for symbol in proxy_symbols if symbol not in records_by_symbol]
        changes = [float(records_by_symbol[symbol]["pct_change"]) for symbol in available]
        pct_change = round(sum(changes) / len(changes), 6) if changes else None
        direction = (
            "UP" if pct_change is not None and pct_change > 0
            else "DOWN" if pct_change is not None and pct_change < 0
            else "FLAT" if pct_change is not None
            else "CANNOT_CONFIRM"
        )
        # Per-symbol arithmetic/date failures belong to their theme row.  Do
        # not smear one bad provider record across otherwise valid rows.
        row_reasons = {
            reason
            for reason in reasons
            if reason not in _QUOTE_HARD_FAILURES and ":" not in reason
        }
        row_reasons.update(
            parse_reasons[symbol]
            for symbol in proxy_symbols
            if symbol in parse_reasons
        )
        if missing:
            row_reasons.add("QUOTE_SYMBOL_MISSING")
            reasons.update(f"QUOTE_SYMBOL_MISSING:{symbol}" for symbol in missing)
        row_dates = sorted({
            str(records_by_symbol[symbol]["session_date"])
            for symbol in available
            if records_by_symbol[symbol].get("session_date")
        })
        row_times = sorted({
            str(records_by_symbol[symbol]["session_time"])
            for symbol in available
            if records_by_symbol[symbol].get("session_time")
        })
        if len(available) == len(proxy_symbols) and not missing and not row_dates:
            row_reasons.add("QUOTE_SESSION_DATE_MISSING")
        if len(available) == len(proxy_symbols) and not missing and not row_times:
            row_reasons.add("QUOTE_SESSION_TIME_MISSING")
        row_status = (
            "CANNOT_CONFIRM" if not available or row_reasons & _QUOTE_HARD_FAILURES
            else "READY" if not missing and row_dates and row_times and len(row_dates) == 1 and len(row_times) == 1
            else "PARTIAL"
        )
        rows.append({
            "label": mapping["label"],
            "group": mapping["group"],
            "mapping_type": mapping["mapping_type"],
            "proxy_symbols": proxy_symbols,
            "available_symbols": available,
            "missing_symbols": missing,
            "requested_symbol_count": len(proxy_symbols),
            "available_symbol_count": len(available),
            "coverage": {"available": len(available), "requested": len(proxy_symbols)},
            "coverage_pct": round(len(available) / len(proxy_symbols) * 100, 3),
            "change_pct": pct_change,
            "pct_change": pct_change,
            "direction": direction,
            "status": row_status,
            "quote_session_dates": row_dates,
            "quote_session_times": row_times,
            "cannot_confirm": sorted(row_reasons),
        })
    available_count = len(records_by_symbol)
    all_rows_ready = all(row["status"] == "READY" for row in rows)
    if not provider_dates:
        reasons.add("QUOTE_SESSION_DATE_MISSING")
    if not provider_times:
        reasons.add("QUOTE_SESSION_TIME_MISSING")
    if not all_rows_ready or not available_count or reasons:
        # A close snapshot is complete only when all 24 rows are READY.  Keep
        # every row (including confirmed rows) for diagnosis, but never let a
        # partial provider response masquerade as an actionable snapshot.
        reasons.add("MARKET_SNAPSHOT_INCOMPLETE")
    status = "READY" if all_rows_ready and available_count and not reasons else "CANNOT_CONFIRM"
    result = {
        "schema_version": MARKET_SNAPSHOT_SCHEMA_VERSION,
        "status": status,
        "source": TENCENT_PROVIDER,
        "provider": TENCENT_PROVIDER,
        "provider_url": TENCENT_QUOTE_ENDPOINT,
        "quote_url": quote_url,
        "source_response_sha256": source_response_sha256,
        "capture_phase": phase,
        "capture_session_date": session_date,
        "captured_at": captured_iso,
        "generated_at": captured_iso,
        "mapping_version": MARKET_MAPPING_VERSION,
        "requested_symbol_count": len(symbols),
        "available_symbol_count": available_count,
        "provider_session_dates": provider_dates,
        "provider_session_times": provider_times,
        "quotes": quotes,
        "rows": rows,
        "cannot_confirm": sorted(reasons),
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if provider_receipt is not None:
        result["provider_receipt"] = dict(provider_receipt)
    return result


# Short aliases make the producer seam discoverable without creating another
# producer or changing the scheduled workload identity.
build_market_snapshot = build_us_market_snapshot
build_global_industry_market_snapshot = build_us_market_snapshot


def _annotate_payload(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    annotated = copy.deepcopy(dict(payload))
    origin = str(metadata["capture_origin"])
    original = bool(metadata["original_time_capture"])
    row_fields = {
        key: metadata[key]
        for key in (
            "us_session_date",
            "capture_phase",
            "session_timezone",
            "capture_window_start",
            "capture_window_end",
            "capture_id",
            "run_id",
            "capture_origin",
            "original_time_capture",
        )
    }
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
        "quote_capture_status",
        "quote_capture_reason",
    ):
        if key in metadata:
            row_fields[key] = metadata[key]
    for field in ("details", "overview"):
        rows = []
        for source_row in annotated.get(field) or []:
            row = dict(source_row)
            row.update(row_fields)
            row["first_seen_at"] = str(row.get("first_seen_at") or annotated["fetched_at"])
            row["capture_ids"] = _ordered_union(
                row.get("capture_ids"), metadata["capture_id"]
            )
            phases = set(row.get("capture_phases") or [])
            phases.add(str(metadata["capture_phase"]))
            row["capture_phases"] = sorted(phases)
            rows.append(row)
        annotated[field] = rows
    receipts = []
    for source_receipt in annotated.get("feed_receipts") or []:
        receipt = dict(source_receipt)
        receipt.update(
            {
                "us_session_date": metadata["us_session_date"],
                "capture_phase": metadata["capture_phase"],
                "capture_id": metadata["capture_id"],
                "run_id": metadata["run_id"],
                "capture_origin": origin,
                "original_time_capture": original,
            }
        )
        for key in (
            "capture_mode",
            "reason",
            "capture_reason",
            "late",
            "natural_capture_window_start",
            "natural_capture_window_end",
            "allowed_recovery_window_start",
            "allowed_recovery_window_end",
        ):
            if key in metadata:
                receipt[key] = metadata[key]
        receipts.append(receipt)
    if "feed_receipts" in annotated:
        annotated["feed_receipts"] = sorted(
            receipts,
            key=lambda row: (
                clean_text(row.get("capture_id")),
                clean_text(row.get("feed_id")),
                clean_text(row.get("url")),
            ),
        )
    annotated["us_session_captures"] = [
        {
            **dict(metadata),
            "raw_item_count": int(annotated["raw_item_count"]),
            "item_count": int(annotated["item_count"]),
        }
    ]
    cannot_confirm = set(annotated.get("cannot_confirm") or [])
    if origin == HISTORICAL_BACKFILL:
        # A date-bounded Google RSS query is a reproducible discovery slice,
        # not a completeness guarantee for the historical session.
        cannot_confirm.add("HISTORICAL_BACKFILL_COVERAGE_UNCONFIRMED")
    else:
        market_day = us_market_day_certification(str(metadata["us_session_date"]))
        if market_day["status"] != "VERIFIED":
            cannot_confirm.add(market_day["reason"])
            annotated["status"] = "CANNOT_CONFIRM"
    annotated["cannot_confirm"] = sorted(cannot_confirm)
    annotated["capture_origin"] = origin
    annotated["original_time_capture"] = original
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if key in metadata:
            annotated[key] = metadata[key]
    return annotated


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
    phase = _phase(capture_phase)
    if phase == HISTORICAL_BACKFILL_PHASE:
        raise ValueError("use build_us_historical_backfill_payload for historical data")
    if resolve_original_url is not None:
        raise ValueError("US RSS lane does not fetch publisher bodies")
    if type(allow_late_post_close) is not bool:
        raise ValueError("allow_late_post_close must be boolean")
    if type(rss_only_recovery) is not bool:
        raise ValueError("rss_only_recovery must be boolean")
    if allow_late_post_close and phase != "POST_CLOSE":
        raise ValueError("US_LATE_POST_CLOSE_ONLY")
    if rss_only_recovery and not allow_late_post_close:
        raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
    if allow_late_post_close:
        clock_now = _capture_now(now)
        metadata_now: datetime | None = clock_now
        requested_session_date = _date(us_session_date or trade_date)
        session_date = requested_session_date
        effective_fetched_at: datetime | str = (
            clock_now if fetched_at is None else fetched_at
        )
        # Validate before any RSS or quote request.  The late flag is a
        # controlled recovery acknowledgement, not permission to backdate.
        _validate_late_post_close_context(
            session_date,
            captured_at=effective_fetched_at,
            now=clock_now,
        )
    else:
        metadata_now = None
        session_date = _date(us_session_date or trade_date)
        # Validate the natural window before touching either network seam.
        # When no timestamp is supplied, take one real instant and pass it
        # through so metadata and source rows share the same actual capture.
        effective_fetched_at = (
            datetime.now(US_TZ).replace(microsecond=0)
            if fetched_at is None
            else fetched_at
        )
        build_capture_metadata(
            session_date,
            phase,
            captured_at=effective_fetched_at,
            capture_origin=ORIGINAL_TIME_CAPTURE,
            original_time_capture=True,
        )
    payload = build_external_finance_payload(
        trade_date,
        fetched_at=effective_fetched_at,
        fetch_rss=fetch_rss,
        subscriptions=_us_subscriptions(),
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        transport=transport,
        **kwargs,
    )
    # Existing unit-test fetch seams are intentionally reused for quote
    # requests when supplied.  The scheduled CLI leaves both seams unset and
    # therefore uses the same proxy-aware transport as the RSS producer.
    quote_fetcher = fetch_quotes or fetch_quote
    if quote_fetcher is None and fetch_rss is not None:
        quote_fetcher = fetch_rss
    recovery_origin = MANUAL_RECOVERY if rss_only_recovery else ORIGINAL_TIME_CAPTURE
    recovery_is_original = not rss_only_recovery
    metadata = build_capture_metadata(
        session_date,
        phase,
        captured_at=payload["fetched_at"],
        capture_id=capture_id,
        run_id=run_id,
        capture_origin=recovery_origin,
        original_time_capture=recovery_is_original,
        allow_late_post_close=allow_late_post_close,
        now=metadata_now,
    )
    if phase == "POST_CLOSE" and not rss_only_recovery:
        market_snapshot = build_us_market_snapshot(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            fetch_quotes=quote_fetcher,
            transport=transport,
            timeout=int(kwargs.get("timeout", 20)),
        )
    elif phase == "POST_CLOSE":
        market_snapshot = _empty_market_snapshot(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            reasons=["US_MARKET_QUOTE_CAPTURE_NOT_REQUESTED_RSS_ONLY_RECOVERY"],
        )
    else:
        # The existing workload may still capture a pre-open news digest, but
        # the product contract is close-only.  Keep a complete 24-row status
        # surface without making an unnecessary quote request.
        market_snapshot = _empty_market_snapshot(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            reasons=["MARKET_SNAPSHOT_NOT_DUE_PRE_OPEN"],
        )
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if key in metadata:
            market_snapshot[key] = metadata[key]
    annotated = _annotate_payload(
        payload,
        metadata,
    )
    capture_record = annotated["us_session_captures"][0]
    capture_record["rss_status"] = str(payload.get("status") or "CANNOT_CONFIRM")
    capture_record["rss_item_count"] = int(payload.get("item_count") or 0)
    capture_record["rss_raw_item_count"] = int(payload.get("raw_item_count") or 0)
    if rss_only_recovery:
        capture_record["quote_capture_status"] = "NOT_ATTEMPTED"
        capture_record["quote_capture_reason"] = "RSS_ONLY_RECOVERY"
    elif phase == "PRE_OPEN":
        capture_record["quote_capture_status"] = "NOT_DUE"
        capture_record["quote_capture_reason"] = "PRE_OPEN_HAS_NO_CLOSE_QUOTE_CAPTURE"
    else:
        capture_record["quote_capture_status"] = "ATTEMPTED"
    annotated["market_snapshot"] = market_snapshot
    annotated["market_snapshot_status"] = str(
        market_snapshot.get("status") or "CANNOT_CONFIRM"
    )
    annotated["cannot_confirm"] = sorted(
        set(annotated.get("cannot_confirm") or [])
        | set(market_snapshot.get("cannot_confirm") or [])
    )
    if phase == "POST_CLOSE" and annotated["market_snapshot_status"] != "READY":
        annotated["status"] = "CANNOT_CONFIRM"
        annotated["cannot_confirm"] = sorted(
            set(annotated["cannot_confirm"]) | {"MARKET_SNAPSHOT_CANNOT_CONFIRM"}
        )
    return annotated


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
    if resolve_original_url is not None:
        raise ValueError("US RSS lane does not fetch publisher bodies")
    selected = _date(trade_date)
    try:
        allowlist = {_date(str(value)) for value in development_dates}
    except (TypeError, ValueError) as error:
        raise ValueError("development date allowlist is invalid") from error
    if selected not in allowlist:
        raise ValueError("trade date is not in the development date allowlist")
    builder_kwargs = dict(
        fetched_at=fetched_at,
        fetch_rss=fetch_rss,
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        **kwargs,
    )
    if "rss_url_builder" in inspect.signature(build_external_finance_payload).parameters:
        # Newer reviewed materializer: keep the exact date-bounded URL seam.
        payload = build_external_finance_payload(
            selected,
            subscriptions=_us_subscriptions(),
            rss_url_builder=lambda query: google_rss_historical_url(query, selected),
            **builder_kwargs,
        )
    else:
        # Frozen scheduler parent: encode the same explicit date bound in each
        # query because its materializer only exposes ``lookback_days``.
        payload = build_external_finance_payload(
            selected,
            subscriptions=_historical_subscriptions(selected),
            **builder_kwargs,
        )
    metadata = build_capture_metadata(
        selected,
        HISTORICAL_BACKFILL_PHASE,
        captured_at=payload["fetched_at"],
        capture_origin=HISTORICAL_BACKFILL,
        original_time_capture=False,
    )
    annotated = _annotate_payload(
        payload,
        metadata,
    )
    annotated["market_snapshot"] = _empty_market_snapshot(
        selected,
        capture_phase=HISTORICAL_BACKFILL_PHASE,
        captured_at=payload["fetched_at"],
        reasons=["HISTORICAL_BACKFILL_QUOTE_CAPTURE_UNCONFIRMED"],
    )
    annotated["market_snapshot_status"] = str(annotated["market_snapshot"]["status"])
    annotated["cannot_confirm"] = sorted(
        set(annotated.get("cannot_confirm") or [])
        | set(annotated["market_snapshot"].get("cannot_confirm") or [])
    )
    return annotated


def _ordered_union(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            items = value
        else:
            items = []
        for item in items:
            normalized = str(item).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
    return result


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
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source_row in [*existing_rows, *incoming_rows]:
        row = dict(source_row)
        key = _row_key(row)
        if not key[0]:
            continue
        previous = merged.get(key)
        if previous is None:
            merged[key] = row
            continue
        winner = row if int(row.get("score") or 0) > int(previous.get("score") or 0) else previous
        winner["market_scopes"] = _ordered_union(
            previous.get("market_scopes"), row.get("market_scopes")
        )
        winner["subscription_ids"] = _ordered_union(
            previous.get("subscription_ids") or previous.get("subscription_id"),
            row.get("subscription_ids") or row.get("subscription_id"),
        )
        winner["cannot_confirm"] = sorted(
            set(previous.get("cannot_confirm") or [])
            | set(row.get("cannot_confirm") or [])
        )
        winner["capture_phases"] = sorted(
            set(previous.get("capture_phases") or [])
            | set(row.get("capture_phases") or [])
            | ({clean_text(previous.get("capture_phase"))} if clean_text(previous.get("capture_phase")) else set())
            | ({clean_text(row.get("capture_phase"))} if clean_text(row.get("capture_phase")) else set())
        )
        winner["capture_ids"] = _ordered_union(
            previous.get("capture_ids"),
            row.get("capture_ids"),
            previous.get("capture_id"),
            row.get("capture_id"),
        )
        merged[key] = winner
    return sorted(
        merged.values(),
        key=lambda row: (
            int(row.get("score") or 0),
            clean_text(row.get("published_at") or row.get("fetched_at")),
            clean_text(row.get("capture_phase")),
            clean_text(row.get("id")),
        ),
        reverse=True,
    )


def _merge_captures(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for source_capture in [*existing, *incoming]:
        row = dict(source_capture)
        capture_id = clean_text(row.get("capture_id"))
        if not capture_id:
            continue
        prior = by_id.get(capture_id)
        if prior is not None and prior != row:
            # A retry with one capture_id is one identity; retain the latest
            # deterministic payload only when its fetch timestamp is newer.
            prior = prior if clean_text(prior.get("captured_at")) >= clean_text(row.get("captured_at")) else row
        by_id[capture_id] = prior or row
    return sorted(
        by_id.values(),
        key=lambda row: (
            clean_text(row.get("us_session_date")),
            clean_text(row.get("capture_phase")),
            clean_text(row.get("capture_id")),
        ),
    )


def _merge_receipts(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source_receipt in [*existing, *incoming]:
        row = dict(source_receipt)
        key = (
            clean_text(row.get("capture_id")),
            clean_text(row.get("feed_id")),
            clean_text(row.get("url")),
        )
        if key not in merged:
            merged[key] = row
    return sorted(merged.values(), key=lambda row: (str(row.get("capture_id") or ""), str(row.get("feed_id") or ""), str(row.get("url") or "")))


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


def _validate_rss_only_recovery_baseline(
    payload: Mapping[str, Any] | None,
    us_session_date: str,
) -> None:
    """Require the exact uncertain close snapshot that RSS-only recovery preserves."""
    if not isinstance(payload, Mapping):
        raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_ARTIFACT")
    snapshot = payload.get("market_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_MARKET_SNAPSHOT")
    if (
        payload.get("status") != "CANNOT_CONFIRM"
        or payload.get("market_snapshot_status") != "CANNOT_CONFIRM"
        or snapshot.get("status") != "CANNOT_CONFIRM"
        or snapshot.get("capture_phase") != "POST_CLOSE"
        or snapshot.get("capture_session_date") != us_session_date
        or len(snapshot.get("quotes") or []) != 33
        or len(snapshot.get("rows") or []) != 24
        or "QUOTE_SESSION_TIME_MIXED" not in (snapshot.get("cannot_confirm") or [])
        or len(set(snapshot.get("provider_session_times") or [])) < 2
        or not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("source_response_sha256") or ""))
    ):
        raise ValueError("US_RSS_ONLY_RECOVERY_EXISTING_SNAPSHOT_IDENTITY_INVALID")
    captures = payload.get("us_session_captures") or []
    if not any(
        isinstance(row, Mapping)
        and row.get("capture_phase") == "POST_CLOSE"
        and row.get("us_session_date") == us_session_date
        and row.get("capture_origin") == ORIGINAL_TIME_CAPTURE
        and row.get("original_time_capture") is True
        and not _is_late_capture_identity(row)
        and row.get("captured_at") == snapshot.get("captured_at")
        for row in captures
    ):
        raise ValueError("US_RSS_ONLY_RECOVERY_ORIGINAL_CAPTURE_IDENTITY_MISSING")


def _merge_market_snapshots(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the newest scheduled quote snapshot in one exact-date artifact."""
    if existing is None and incoming is None:
        return None
    if existing is None:
        return copy.deepcopy(dict(incoming)) if incoming is not None else None
    if incoming is None:
        return copy.deepcopy(dict(existing))
    existing_time = _snapshot_timestamp(existing)
    incoming_time = _snapshot_timestamp(incoming)
    existing_valid = existing.get("status") in {"READY", "PARTIAL"}
    incoming_valid = incoming.get("status") in {"READY", "PARTIAL"}
    if existing_valid != incoming_valid:
        winner = existing if existing_valid else incoming
    elif existing_time is None and incoming_time is None:
        winner = incoming
    elif existing_time is None:
        winner = incoming
    elif incoming_time is None:
        winner = existing
    else:
        winner = incoming if incoming_time >= existing_time else existing
    merged = copy.deepcopy(dict(winner))
    # The two scheduled phases may have different provider identities.  Keep
    # every observed session value visible instead of inventing a unified date.
    for field in ("provider_session_dates", "provider_session_times"):
        merged[field] = sorted(
            {
                str(value)
                for source in (existing, incoming)
                for value in (source.get(field) or [])
                if str(value).strip()
            }
        )
    mixed_reasons: set[str] = set()
    if len(merged.get("provider_session_dates") or []) > 1:
        mixed_reasons.add("QUOTE_SESSION_DATE_MIXED")
    if len(merged.get("provider_session_times") or []) > 1:
        mixed_reasons.add("QUOTE_SESSION_TIME_MIXED")
    if mixed_reasons:
        merged["status"] = "PARTIAL"
        merged["cannot_confirm"] = sorted(
            set(merged["cannot_confirm"]) | mixed_reasons
        )
    return merged


def merge_us_phase_payloads(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    preserve_existing_market_snapshot: bool = False,
) -> dict[str, Any]:
    """Merge a new phase into one exact-date external-finance artifact."""
    existing_date, existing_source = validate_research_peripheral(existing)
    incoming_date, incoming_source = validate_research_peripheral(incoming)
    if (existing_date, existing_source) != (incoming_date, incoming_source):
        raise ValueError("US phase payload identity mismatch")
    if existing_source != "external_finance":
        raise ValueError("US phase merge requires external_finance")
    merged = copy.deepcopy(dict(existing))
    details = _merge_rows(existing.get("details") or [], incoming.get("details") or [])
    merged["details"] = details
    merged["overview"] = overview_from_details(details)
    merged["items"] = []
    merged["item_count"] = len(details)
    merged["fetched_at"] = max(
        clean_text(existing.get("fetched_at")), clean_text(incoming.get("fetched_at"))
    )
    merged["source_url"] = clean_text(incoming.get("source_url") or existing.get("source_url"))
    merged["cannot_confirm"] = sorted(
        set(existing.get("cannot_confirm") or []) | set(incoming.get("cannot_confirm") or [])
    )
    captures = _merge_captures(
        existing.get("us_session_captures") or [],
        incoming.get("us_session_captures") or [],
    )
    merged["us_session_captures"] = captures
    existing_captures = existing.get("us_session_captures") or []
    incoming_captures = incoming.get("us_session_captures") or []
    capture_counts = [
        row.get("raw_item_count")
        for row in captures
        if type(row.get("raw_item_count")) is int and row.get("raw_item_count") >= 0
    ]
    if not existing_captures:
        # The first US capture may follow a regular external-finance refresh
        # that predates capture identity.  Preserve that source count while
        # adding the new capture count; otherwise details can outnumber raw
        # rows and the exact-date store correctly rejects the merge.
        merged["raw_item_count"] = int(existing.get("raw_item_count") or 0) + int(
            incoming.get("raw_item_count") or 0
        )
    elif len(capture_counts) == len(captures):
        # Capture IDs are the idempotency boundary.  A retry of one phase
        # must not inflate the aggregate raw count.
        merged["raw_item_count"] = sum(capture_counts)
    elif not incoming_captures:
        merged["raw_item_count"] = int(existing.get("raw_item_count") or 0) + int(
            incoming.get("raw_item_count") or 0
        )
    else:
        merged["raw_item_count"] = int(existing.get("raw_item_count") or 0) + int(incoming.get("raw_item_count") or 0)
    origins = {str(row.get("capture_origin")) for row in captures}
    merged["capture_origin"] = next(iter(origins)) if len(origins) == 1 else MIXED_CAPTURE
    merged["original_time_capture"] = bool(captures) and all(
        row.get("original_time_capture") is True for row in captures
    )
    late_captures = [row for row in captures if row.get("late") is True]
    if late_captures:
        latest_late = max(
            late_captures,
            key=lambda row: clean_text(row.get("captured_at")),
        )
        merged.update(
            {
                field: latest_late[field]
                for field in (
                    "capture_mode",
                    "reason",
                    "capture_reason",
                    "late",
                    "natural_capture_window_start",
                    "natural_capture_window_end",
                    "allowed_recovery_window_start",
                    "allowed_recovery_window_end",
                )
                if field in latest_late
            }
        )
    merged["feed_receipts"] = _merge_receipts(
        existing.get("feed_receipts") or [], incoming.get("feed_receipts") or []
    )
    prior_snapshot = existing.get("market_snapshot")
    if preserve_existing_market_snapshot and not isinstance(prior_snapshot, Mapping):
        raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_MARKET_SNAPSHOT")
    merged_snapshot = (
        copy.deepcopy(dict(prior_snapshot))
        if preserve_existing_market_snapshot and isinstance(prior_snapshot, Mapping)
        else _merge_market_snapshots(prior_snapshot, incoming.get("market_snapshot"))
    )
    if merged_snapshot is not None:
        merged["market_snapshot"] = merged_snapshot
        merged["market_snapshot_status"] = str(
            merged_snapshot.get("status") or "CANNOT_CONFIRM"
        )
        merged["cannot_confirm"] = sorted(
            set(merged.get("cannot_confirm") or [])
            | set(merged_snapshot.get("cannot_confirm") or [])
        )
    if details:
        merged["status"] = (
            "CANNOT_CONFIRM"
            if "ZH_TRANSLATION_INCOMPLETE" in merged["cannot_confirm"]
            else "READY"
        )
    else:
        merged["status"] = "CANNOT_CONFIRM" if merged["cannot_confirm"] else "READY_EMPTY"
    # A close quote failure is a failure of this product's capture even when
    # the companion news rows were fetched successfully.  A PRE_OPEN-only
    # artifact keeps its news status while exposing the not-due snapshot.
    post_close_capture = any(
        row.get("capture_phase") == "POST_CLOSE"
        for row in captures
        if isinstance(row, Mapping)
    )
    if post_close_capture and merged.get("market_snapshot_status") != "READY":
        merged["status"] = "CANNOT_CONFIRM"
        merged["cannot_confirm"] = sorted(
            set(merged.get("cannot_confirm") or [])
            | {"MARKET_SNAPSHOT_CANNOT_CONFIRM"}
        )
    validate_research_peripheral(merged)
    return merged


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
    from infrastructure.interprocess_lock import owned_interprocess_lock

    if not Path(data_root).is_absolute():
        raise ValueError("US_OWNED_DATA_ROOT_MUST_BE_ABSOLUTE")
    date = _date(trade_date)
    with owned_interprocess_lock(
        Path(data_root) / ".locks" / f"us-market-{date}.lock",
        timeout_seconds=300, timeout_message="US_CAPTURE_OWNER_BUSY",
    ):
        return _materialize_us_market_phase_locked(
            data_root=data_root, trade_date=date, capture_phase=capture_phase,
            allow_late_post_close=allow_late_post_close,
            rss_only_recovery=rss_only_recovery,
            now=now, **kwargs,
        )


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
    phase = _phase(capture_phase)
    if type(allow_late_post_close) is not bool:
        raise ValueError("allow_late_post_close must be boolean")
    if type(rss_only_recovery) is not bool:
        raise ValueError("rss_only_recovery must be boolean")
    if allow_late_post_close and phase != "POST_CLOSE":
        raise ValueError("US_LATE_POST_CLOSE_ONLY")
    if rss_only_recovery and not allow_late_post_close:
        raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
    if allow_late_post_close:
        # Validate the requested US session and the current New York recovery
        # window before reading the store or deriving the idempotency
        # identity.  This is intentionally the reuse admission check; an old
        # ``fetched_at`` belonging to an already-complete capture is allowed
        # to be reused while the same recovery window is still open.
        clock_now = _capture_now(now)
        requested_session_date = _date(
            str(kwargs.get("us_session_date") or trade_date)
        )
        _validate_late_post_close_window(requested_session_date, now=clock_now)
        session_date = requested_session_date
        # ``trade_date`` remains the exact research artifact date.  The
        # provider session is a separate identity and must reach the builder
        # explicitly so a target-date artifact can hold the prior NY session.
        kwargs["us_session_date"] = session_date
        build_now: datetime | str | None = clock_now
        kwargs.setdefault(
            "capture_id",
            _late_post_close_capture_id(session_date, clock_now),
        )
    else:
        session_date = _date(str(kwargs.get("us_session_date") or trade_date))
        build_now = now
    store = ResearchPeripheralStore(data_root)
    existing = store.read_exact(trade_date, "external_finance")
    if rss_only_recovery:
        _validate_rss_only_recovery_baseline(existing, session_date)
    requested_capture_id = str(kwargs.get("capture_id") or "").strip() or _deterministic_capture_id(
        session_date, phase
    )
    if phase == "POST_CLOSE" and isinstance(existing, Mapping):
        # A valid completed capture is the idempotency boundary.  Read and
        # validate it before the producer is allowed to issue RSS or quote
        # requests; an older news-only artifact deliberately falls through.
        captures = existing.get("us_session_captures") or []
        snapshot = existing.get("market_snapshot")
        session_captures = [
            row
            for row in captures
            if isinstance(row, Mapping)
            and row.get("capture_phase") == "POST_CLOSE"
            and row.get("us_session_date") == session_date
        ]
        # A late marker may exist on the snapshot, the capture row, or the
        # payload envelope.  Any such marker makes the identity late; this
        # prevents a malformed/older artifact from being reused by the
        # default natural path after one field was omitted.
        artifact_late = (
            _is_late_capture_identity(existing)
            or _is_late_capture_identity(snapshot)
            or any(_is_late_capture_identity(row) for row in session_captures)
        )
        snapshot_matches_mode = (
            artifact_late
            if allow_late_post_close
            else not artifact_late
        )
        late_rss_capture_recorded = rss_only_recovery and any(
            isinstance(row, Mapping)
            and row.get("capture_phase") == "POST_CLOSE"
            and row.get("us_session_date") == session_date
            and row.get("capture_id") == requested_capture_id
            and row.get("quote_capture_status") == "NOT_ATTEMPTED"
            for row in session_captures
        )
        completed = (
            isinstance(snapshot, Mapping)
            and (
                snapshot.get("status") in {"READY", "PARTIAL"}
                or late_rss_capture_recorded
            )
            and snapshot.get("capture_phase") == "POST_CLOSE"
            and snapshot.get("capture_session_date") == session_date
            and snapshot_matches_mode
            and any(
                isinstance(row, Mapping)
                and row.get("capture_phase") == "POST_CLOSE"
                and row.get("us_session_date") == session_date
                and row.get("capture_id") == requested_capture_id
                and row.get("capture_origin") == (
                    MANUAL_RECOVERY if rss_only_recovery else ORIGINAL_TIME_CAPTURE
                )
                and row.get("original_time_capture") is (not rss_only_recovery)
                and (
                    _is_late_capture_identity(row)
                    if allow_late_post_close
                    else not _is_late_capture_identity(row)
                )
                for row in captures
            )
        )
        if completed:
            relative = store._relative(_date(trade_date), "external_finance")
            receipt_relative = store._receipt_relative(_date(trade_date), "external_finance")
            digest = _sha256(existing)
            return {
                "payload": existing,
                "trade_date": _date(trade_date),
                "source": "external_finance",
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "item_count": int(existing["item_count"]),
                "reused": True,
                "replaced": False,
                "market_snapshot_status": str(snapshot.get("status")),
                "capture_id": requested_capture_id,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
    if allow_late_post_close:
        # A new capture still needs an actual current timestamp.  Defer this
        # stricter check until after mode-aware reuse so a completed late
        # artifact can be returned without pretending its original timestamp
        # was the caller's current second.
        effective_fetched_at = kwargs.get("fetched_at")
        if effective_fetched_at is None:
            effective_fetched_at = clock_now
            # Keep the producer and materializer on the same second-resolved
            # capture instant when the caller leaves fetched_at unspecified.
            kwargs["fetched_at"] = effective_fetched_at
        _validate_late_post_close_context(
            session_date,
            captured_at=effective_fetched_at,
            now=clock_now,
        )
    if phase == "PRE_OPEN" and isinstance(existing, Mapping):
        # PRE_OPEN has no quote snapshot, but a same-identity successful news
        # capture is still the idempotency boundary for scheduler retries.
        captures = existing.get("us_session_captures") or []
        snapshot = existing.get("market_snapshot")
        completed = (
            isinstance(snapshot, Mapping)
            and snapshot.get("capture_phase") == "PRE_OPEN"
            and snapshot.get("capture_session_date") == session_date
            and existing.get("status") in {"READY", "READY_EMPTY"}
            and any(
                isinstance(row, Mapping)
                and row.get("capture_phase") == "PRE_OPEN"
                and row.get("us_session_date") == session_date
                and row.get("capture_id") == requested_capture_id
                and row.get("original_time_capture") is True
                for row in captures
            )
        )
        if completed:
            relative = store._relative(_date(trade_date), "external_finance")
            receipt_relative = store._receipt_relative(_date(trade_date), "external_finance")
            digest = _sha256(existing)
            return {
                "payload": existing,
                "trade_date": _date(trade_date),
                "source": "external_finance",
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "item_count": int(existing["item_count"]),
                "reused": True,
                "replaced": False,
                "market_snapshot_status": str(snapshot.get("status") or "CANNOT_CONFIRM"),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
    payload = build_us_market_phase_payload(
        trade_date,
        capture_phase=capture_phase,
        allow_late_post_close=allow_late_post_close,
        rss_only_recovery=rss_only_recovery,
        now=build_now,
        **kwargs,
    )
    if existing is None:
        result = store.publish(payload)
        return {
            "payload": payload,
            "market_snapshot_status": payload.get("market_snapshot_status"),
            "capture_id": next(
                (row.get("capture_id") for row in payload.get("us_session_captures", [])
                 if isinstance(row, Mapping) and row.get("capture_phase") == phase),
                None,
            ),
            "reused": False,
            "replaced": False,
            **result,
        }
    if (
        phase == "POST_CLOSE"
        and payload.get("market_snapshot_status") != "READY"
        and not rss_only_recovery
    ):
        incoming_captures = payload.get("us_session_captures") or []
        incoming_capture = next(
            (
                row
                for row in incoming_captures
                if isinstance(row, Mapping)
                and row.get("capture_phase") == "POST_CLOSE"
            ),
            None,
        )
        incoming_capture_id = (
            str(incoming_capture.get("capture_id") or "")
            if isinstance(incoming_capture, Mapping)
            else ""
        )
        existing_capture_ids = {
            str(row.get("capture_id") or "")
            for row in (existing.get("us_session_captures") or [])
            if isinstance(row, Mapping)
        }
        existing_snapshot = existing.get("market_snapshot")
        retained_snapshot_is_valid = (
            isinstance(existing_snapshot, Mapping)
            and existing_snapshot.get("capture_phase") == "POST_CLOSE"
            and existing_snapshot.get("capture_session_date") == session_date
            and existing_snapshot.get("status") in {"READY", "PARTIAL"}
        )
        if (
            retained_snapshot_is_valid
            and existing.get("status") in {"READY", "READY_EMPTY"}
            and incoming_capture_id
            and incoming_capture_id not in existing_capture_ids
        ):
            # A new failed close capture is an audited failure of this
            # materialization attempt.  Keep the previously verified
            # canonical artifact intact, but persist a receipt for the
            # incoming identity so the CLI and downstream audit cannot report
            # the attempt as successful.
            attempt = store.record_refresh_attempt(
                payload,
                retained_payload=existing,
                reason="US_POST_CLOSE_MARKET_SNAPSHOT_FAILED",
            )
            retained_date = _date(trade_date)
            return {
                "payload": payload,
                "status": "CANNOT_CONFIRM",
                "trade_date": retained_date,
                "source": "external_finance",
                "payload_path": "",
                "receipt_path": attempt["refresh_attempt_path"],
                "payload_sha256": attempt["attempted_payload_sha256"],
                "item_count": int(payload["item_count"]),
                "reused": False,
                "replaced": False,
                "retained_previous": True,
                "retained_payload_path": store._relative(retained_date, "external_finance"),
                "retained_receipt_path": store._receipt_relative(retained_date, "external_finance"),
                "retained_payload_sha256": attempt["retained_payload_sha256"],
                "market_snapshot_status": "CANNOT_CONFIRM",
                "cannot_confirm": list(payload.get("cannot_confirm") or []),
                **attempt,
            }
    merged = merge_us_phase_payloads(
        existing,
        payload,
        preserve_existing_market_snapshot=rss_only_recovery,
    )
    result = store.replace(
        merged,
        expected_sha256=_sha256(existing),
        reason=f"US_{str(capture_phase).upper()}_CAPTURE_MERGE",
    )
    return {
        "payload": merged,
        "market_snapshot_status": merged.get("market_snapshot_status"),
        "capture_id": requested_capture_id,
        "reused": False,
        **result,
    }


def materialize_us_historical_backfill(
    *,
    data_root: Path,
    trade_date: str,
    development_dates: Collection[str],
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_us_historical_backfill_payload(
        trade_date,
        development_dates=development_dates,
        **kwargs,
    )
    result = ResearchPeripheralStore(data_root).publish_historical_backfill(payload)
    return {"payload": payload, **result}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--capture-phase", choices=US_CAPTURE_PHASES)
    parser.add_argument(
        "--allow-late-post-close",
        action="store_true",
        help="explicitly recover only the latest completed POST_CLOSE session inside its bounded New York recovery window",
    )
    parser.add_argument(
        "--rss-only-recovery",
        action="store_true",
        help="capture recent RSS through the existing owner while leaving the quote snapshot untouched",
    )
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--development-dates-file", type=Path)
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.historical:
            if args.capture_phase or args.development_dates_file is None or args.allow_late_post_close or args.rss_only_recovery:
                raise ValueError("historical mode requires only --development-dates-file")
            allowlist_payload = json.loads(args.development_dates_file.read_text(encoding="utf-8"))
            if isinstance(allowlist_payload, Mapping):
                allowlist_payload = allowlist_payload.get("dates")
            if not isinstance(allowlist_payload, list):
                raise ValueError("development date allowlist must be a JSON list")
            result = materialize_us_historical_backfill(
                data_root=args.data_root,
                trade_date=args.trade_date,
                development_dates=allowlist_payload,
                timeout=args.timeout,
            )
        else:
            if not args.capture_phase or args.development_dates_file is not None:
                raise ValueError("live mode requires --capture-phase and no development allowlist")
            materialize_kwargs: dict[str, Any] = {}
            if args.allow_late_post_close:
                if args.capture_phase != "POST_CLOSE":
                    raise ValueError("US_LATE_POST_CLOSE_ONLY")
                recovery_now = _capture_now()
                materialize_kwargs["allow_late_post_close"] = True
                materialize_kwargs["us_session_date"] = args.trade_date
                materialize_kwargs["now"] = recovery_now
                materialize_kwargs["capture_id"] = _late_post_close_capture_id(
                    args.trade_date,
                    recovery_now,
                )
                materialize_kwargs["rss_only_recovery"] = args.rss_only_recovery
            elif args.rss_only_recovery:
                raise ValueError("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
            result = materialize_us_market_phase(
                data_root=args.data_root,
                trade_date=args.trade_date,
                capture_phase=args.capture_phase,
                timeout=args.timeout,
                **materialize_kwargs,
            )
        capture_rows = result["payload"].get("us_session_captures") or []
        capture_identity = next(
            (
                row
                for row in reversed(capture_rows)
                if isinstance(row, Mapping)
                and row.get("us_session_date") == _date(args.trade_date)
                and row.get("capture_phase") == args.capture_phase
                and (not result.get("capture_id") or row.get("capture_id") == result.get("capture_id"))
            ),
            {},
        )
        rss_capture_status = str(capture_identity.get("rss_status") or "CANNOT_CONFIRM")
        market_snapshot_status = (
            result["payload"].get("market_snapshot_status")
            or result.get("market_snapshot_status")
            or "CANNOT_CONFIRM"
        )
        lane_has_success = (
            rss_capture_status in {"READY", "READY_EMPTY"}
            or market_snapshot_status == "READY"
        )
        operation_status = (
            "CAPTURED"
            if lane_has_success and result["payload"].get("status") in {"READY", "READY_EMPTY"}
            else "CAPTURED_WITH_UNVERIFIED_LANE"
            if lane_has_success
            else "NO_LANE_READY"
        )
        print(json.dumps({
            "status": result.get("status") or result["payload"]["status"],
            "trade_date": result["payload"]["trade_date"],
            "source": result["payload"]["source"],
            "payload_path": result["payload_path"],
            "receipt_path": result.get("receipt_path"),
            "payload_sha256": result["payload_sha256"],
            "reused": result.get("reused"),
            "replaced": result.get("replaced"),
            "capture_us_session_date": capture_identity.get("us_session_date"),
            "capture_phase": capture_identity.get("capture_phase"),
            "capture_id": capture_identity.get("capture_id"),
            "capture_run_id": capture_identity.get("run_id"),
            "capture_captured_at": capture_identity.get("captured_at"),
            "capture_capture_origin": capture_identity.get("capture_origin"),
            "capture_original_time": capture_identity.get("original_time_capture"),
            "rss_capture_status": rss_capture_status,
            "rss_capture_item_count": capture_identity.get("rss_item_count"),
            "rss_capture_raw_item_count": capture_identity.get("rss_raw_item_count"),
            "quote_capture_status": capture_identity.get("quote_capture_status"),
            "quote_capture_reason": capture_identity.get("quote_capture_reason"),
            "operation_status": operation_status,
            "rss_only_recovery": args.rss_only_recovery,
            "capture_origin": result["payload"].get("capture_origin"),
            "original_time_capture": result["payload"].get("original_time_capture"),
            "capture_mode": result["payload"].get("capture_mode"),
            "reason": result["payload"].get("reason"),
            "late": result["payload"].get("late", False),
            "natural_capture_window_start": result["payload"].get("natural_capture_window_start"),
            "natural_capture_window_end": result["payload"].get("natural_capture_window_end"),
            "allowed_recovery_window_start": result["payload"].get("allowed_recovery_window_start"),
            "allowed_recovery_window_end": result["payload"].get("allowed_recovery_window_end"),
            "market_snapshot_status": market_snapshot_status,
            "cannot_confirm": list(result["payload"].get("cannot_confirm") or []),
            "refresh_attempt_path": result.get("refresh_attempt_path"),
            "retained_previous": result.get("retained_previous", False),
            "retained_payload_path": result.get("retained_payload_path"),
            "retained_payload_sha256": result.get("retained_payload_sha256"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if lane_has_success else 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "CANNOT_CONFIRM",
            "reason": f"{type(error).__name__}:{error}",
            "market_snapshot_status": "CANNOT_CONFIRM",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 2


__all__ = [
    "GOOGLE_NEWS_RSS",
    "GLOBAL_INDUSTRY_LABELS",
    "GLOBAL_INDUSTRY_PROXY_MAP",
    "HISTORICAL_BACKFILL",
    "HISTORICAL_BACKFILL_PHASE",
    "LATE_POST_CLOSE_CAPTURE_MODE",
    "LATE_POST_CLOSE_CAPTURE_REASON",
    "LATE_POST_CLOSE_MAX_AGE",
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
