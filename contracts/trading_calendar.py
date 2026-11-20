"""Strict V3.5-owned market-calendar contract types and loading."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


CALENDAR_PATH = Path(__file__).with_name("market_calendar_2026.json")
SCHEMA_VERSION = "v3_5.market_calendar_2026.v1"
MARKET_KEYS = {"a_share", "hk_securities", "hk_connect_southbound"}
MARKET_FIELDS = {
    "label",
    "derives_from",
    "full_day_sessions",
    "half_day_sessions",
    "full_day_close",
    "half_day_close",
    "half_days",
    "holiday_periods",
}


class RunPolicy(StrEnum):
    NATURAL_DAY = "NATURAL_DAY"
    A_SHARE_TRADE_DAY = "A_SHARE_TRADE_DAY"
    HK_SECURITIES_TRADE_DAY = "HK_SECURITIES_TRADE_DAY"
    HK_CONNECT_TRADE_DAY = "HK_CONNECT_TRADE_DAY"
    A_OR_HK_CONNECT_TRADE_DAY = "A_OR_HK_CONNECT_TRADE_DAY"
    A_OR_HK_SECURITIES_TRADE_DAY = "A_OR_HK_SECURITIES_TRADE_DAY"


class MarketScope(StrEnum):
    A_SHARE = "A_SHARE"
    HK_CONNECT = "HK_CONNECT"
    CROSS_MARKET = "CROSS_MARKET"


class SessionRequirement(StrEnum):
    DAY_ELIGIBILITY_ONLY = "DAY_ELIGIBILITY_ONLY"
    SESSION_OPEN = "SESSION_OPEN"
    POST_CLOSE = "POST_CLOSE"


class TradingDayState(StrEnum):
    FULL_TRADING_DAY = "FULL_TRADING_DAY"
    HALF_TRADING_DAY_AM = "HALF_TRADING_DAY_AM"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OfficialSource:
    market: str
    name: str
    url: str


@dataclass(frozen=True)
class MarketCalendar:
    schema_version: str
    year: int
    timezone: str
    official_sources: tuple[OfficialSource, ...]
    markets: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class MarketCalendarRange:
    """An explicitly SHA-bound set of complete per-year calendars."""

    calendars: Mapping[int, MarketCalendar]
    sha256_by_year: Mapping[int, str]

    def __post_init__(self) -> None:
        calendars = dict(self.calendars)
        digests = dict(self.sha256_by_year)
        if not calendars or set(calendars) != set(digests):
            raise ValueError("invalid market calendar range")
        for year, calendar in calendars.items():
            if type(year) is not int or not isinstance(calendar, MarketCalendar) or calendar.year != year:
                raise ValueError("market calendar range year conflict")
            digest = digests[year]
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid market calendar range SHA-256")
        object.__setattr__(self, "calendars", MappingProxyType(calendars))
        object.__setattr__(self, "sha256_by_year", MappingProxyType(digests))

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted(self.calendars))


class CalendarYearMissing(ValueError):
    """Raised when a market/date is outside the supplied calendar years."""

    def __init__(self, *, year: int, market: str, trade_date: str) -> None:
        self.year = year
        self.market = market
        self.trade_date = trade_date
        super().__init__(
            f"calendar year missing: year={year} market={market} trade_date={trade_date}"
        )


def _date8(value: Any, *, year: int) -> date:
    parsed = _parse_date8(value)
    if parsed.year != year:
        raise ValueError("calendar date must match contract year")
    return parsed


def _parse_date8(value: Any) -> date:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("calendar date must use YYYYMMDD")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError("calendar date must be real") from error


def _hhmm(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = str(value or "")
    if len(text) != 4 or not text.isdigit():
        raise ValueError("calendar time must use HHMM")
    hour, minute = int(text[:2]), int(text[2:])
    if hour > 23 or minute > 59:
        raise ValueError("calendar time must be real")
    return text


def _validate_market(name: str, value: Any, *, year: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MARKET_FIELDS:
        raise ValueError(f"invalid market calendar fields: {name}")
    if not isinstance(value["label"], str) or not value["label"].strip():
        raise ValueError(f"invalid market label: {name}")
    derives = value["derives_from"]
    if not isinstance(derives, list) or any(item not in MARKET_KEYS for item in derives):
        raise ValueError(f"invalid market derivation: {name}")
    for field in ("full_day_sessions", "half_day_sessions"):
        sessions = value[field]
        if not isinstance(sessions, list):
            raise ValueError(f"invalid sessions: {name}")
        for session in sessions:
            if not isinstance(session, dict) or set(session) != {"start", "end"}:
                raise ValueError(f"invalid session fields: {name}")
            start = _hhmm(session["start"])
            end = _hhmm(session["end"])
            if start >= end:
                raise ValueError(f"invalid session interval: {name}")
    _hhmm(value["full_day_close"])
    _hhmm(value["half_day_close"], nullable=True)
    half_days = value["half_days"]
    if not isinstance(half_days, list) or len(set(half_days)) != len(half_days):
        raise ValueError(f"invalid half days: {name}")
    for day in half_days:
        _date8(day, year=year)
    periods = value["holiday_periods"]
    if not isinstance(periods, list):
        raise ValueError(f"invalid holiday periods: {name}")
    for period in periods:
        if not isinstance(period, dict) or set(period) != {"name", "start", "end"}:
            raise ValueError(f"invalid holiday period fields: {name}")
        start = _date8(period["start"], year=year)
        end = _date8(period["end"], year=year)
        if start > end or not str(period["name"]).strip():
            raise ValueError(f"invalid holiday period: {name}")
    return value


def _load_market_calendar_bytes(raw: bytes) -> MarketCalendar:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("market calendar cannot be loaded") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "year",
        "timezone",
        "official_sources",
        "markets",
    }:
        raise ValueError("invalid market calendar envelope")
    year = payload["year"]
    if type(year) is not int or not 1 <= year <= 9999:
        raise ValueError("unsupported market calendar identity")
    expected_schema_version = f"v3_5.market_calendar_{year}.v1"
    if payload["schema_version"] != expected_schema_version:
        raise ValueError("unsupported market calendar identity")
    if payload["timezone"] != "Asia/Shanghai":
        raise ValueError("unsupported market calendar timezone")
    sources = payload["official_sources"]
    if not isinstance(sources, list):
        raise ValueError("invalid official sources")
    official_sources: list[OfficialSource] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"market", "name", "url"}:
            raise ValueError("invalid official source fields")
        if source["market"] not in MARKET_KEYS or not str(source["name"]).strip():
            raise ValueError("invalid official source identity")
        if not str(source["url"]).startswith("https://"):
            raise ValueError("official source must use HTTPS")
        official_sources.append(OfficialSource(**source))
    if {source.market for source in official_sources} != MARKET_KEYS:
        raise ValueError("each market requires official provenance")
    markets = payload["markets"]
    if not isinstance(markets, dict) or set(markets) != MARKET_KEYS:
        raise ValueError("invalid market set")
    validated = {
        name: _validate_market(name, market, year=payload["year"])
        for name, market in markets.items()
    }
    if validated["hk_connect_southbound"]["derives_from"] != [
        "a_share",
        "hk_securities",
    ]:
        raise ValueError("HK Connect must derive from A-share and HK securities")
    return MarketCalendar(
        schema_version=payload["schema_version"],
        year=year,
        timezone=payload["timezone"],
        official_sources=tuple(official_sources),
        markets=validated,
    )


def _calendar_bytes(path: Path, expected_sha256: str | None = None) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("market calendar cannot be loaded") from error
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("invalid market calendar SHA-256")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("market calendar SHA-256 mismatch")
    return raw


def load_market_calendar(
    path: Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> MarketCalendar:
    """Load one complete calendar, optionally binding it to an expected digest."""
    source_path = CALENDAR_PATH if path is None else Path(path)
    return _load_market_calendar_bytes(_calendar_bytes(source_path, expected_sha256))


def load_market_calendar_range(
    calendars_by_year: Mapping[Any, Mapping[str, Any]],
    *,
    legacy_reference: Mapping[str, Any] | None = None,
) -> MarketCalendarRange:
    """Load SHA-bound year references, optionally retaining the legacy single ref."""
    if not isinstance(calendars_by_year, Mapping):
        raise ValueError("market calendars must be keyed by year")
    calendars: dict[int, MarketCalendar] = {}
    sha256_by_year: dict[int, str] = {}

    def add_reference(reference: Mapping[str, Any], *, expected_year: int | None) -> None:
        if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
            raise ValueError("invalid market calendar reference fields")
        path_value = reference["path"]
        if not isinstance(path_value, (str, Path)):
            raise ValueError("invalid market calendar reference path")
        source_path = Path(path_value)
        try:
            path_is_canonical = (
                source_path.is_absolute()
                and not source_path.is_symlink()
                and source_path.resolve(strict=True) == source_path
            )
        except OSError:
            path_is_canonical = False
        if not path_is_canonical:
            raise ValueError("invalid market calendar reference path")
        digest = reference["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid market calendar SHA-256")
        raw = _calendar_bytes(source_path, digest)
        calendar = _load_market_calendar_bytes(raw)
        if expected_year is not None and calendar.year != expected_year:
            raise ValueError(
                "market calendar reference year conflict: "
                f"key={expected_year} actual={calendar.year}"
            )
        if calendar.year in calendars:
            raise ValueError(f"duplicate market calendar year: year={calendar.year}")
        calendars[calendar.year] = calendar
        sha256_by_year[calendar.year] = digest

    for key, reference in calendars_by_year.items():
        try:
            year = int(key)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid market calendar reference year") from error
        if type(key) is bool or str(year) != str(key) or not 1 <= year <= 9999:
            raise ValueError("invalid market calendar reference year")
        add_reference(reference, expected_year=year)
    if legacy_reference is not None:
        add_reference(legacy_reference, expected_year=None)
    if not calendars:
        raise ValueError("market calendar range requires at least one reference")
    return MarketCalendarRange(calendars, sha256_by_year)


def parse_trade_date(value: str, *, year: int) -> date | None:
    try:
        return _date8(value, year=year)
    except ValueError:
        return None


def direct_market_state(
    trade_date: date,
    market: Mapping[str, Any],
) -> TradingDayState:
    date8 = trade_date.strftime("%Y%m%d")
    if trade_date.weekday() >= 5:
        return TradingDayState.NON_TRADING_DAY
    for period in market["holiday_periods"]:
        if period["start"] <= date8 <= period["end"]:
            return TradingDayState.NON_TRADING_DAY
    if date8 in market["half_days"]:
        return TradingDayState.HALF_TRADING_DAY_AM
    return TradingDayState.FULL_TRADING_DAY


def resolve_market_states(
    calendar: MarketCalendar | MarketCalendarRange,
    trade_date: str,
) -> dict[str, TradingDayState]:
    try:
        parsed = _parse_date8(trade_date)
    except ValueError:
        return {
            "a_share": TradingDayState.UNKNOWN,
            "hk_securities": TradingDayState.UNKNOWN,
            "hk_connect": TradingDayState.UNKNOWN,
        }
    try:
        year_calendar = _calendar_for_date(calendar, parsed, market="a_share", trade_date=trade_date)
    except CalendarYearMissing:
        return {
            "a_share": TradingDayState.UNKNOWN,
            "hk_securities": TradingDayState.UNKNOWN,
            "hk_connect": TradingDayState.UNKNOWN,
        }
    a_share = direct_market_state(parsed, year_calendar.markets["a_share"])
    hk_securities = direct_market_state(parsed, year_calendar.markets["hk_securities"])
    southbound = direct_market_state(parsed, year_calendar.markets["hk_connect_southbound"])
    if TradingDayState.NON_TRADING_DAY in {a_share, hk_securities, southbound}:
        hk_connect = TradingDayState.NON_TRADING_DAY
    elif TradingDayState.HALF_TRADING_DAY_AM in {a_share, hk_securities, southbound}:
        hk_connect = TradingDayState.HALF_TRADING_DAY_AM
    else:
        hk_connect = TradingDayState.FULL_TRADING_DAY
    return {
        "a_share": a_share,
        "hk_securities": hk_securities,
        "hk_connect": hk_connect,
    }


def _market_key(market: str) -> str:
    if market not in {"a_share", "hk_securities", "hk_connect"}:
        raise ValueError("unsupported market")
    return market


def _calendar_for_date(
    calendar: MarketCalendar | MarketCalendarRange,
    parsed: date,
    *,
    market: str,
    trade_date: str,
) -> MarketCalendar:
    market = _market_key(market)
    if isinstance(calendar, MarketCalendarRange):
        selected = calendar.calendars.get(parsed.year)
        if selected is None:
            raise CalendarYearMissing(year=parsed.year, market=market, trade_date=trade_date)
        return selected
    if not isinstance(calendar, MarketCalendar):
        raise TypeError("unsupported market calendar")
    if parsed.year != calendar.year:
        raise CalendarYearMissing(year=parsed.year, market=market, trade_date=trade_date)
    return calendar


def resolve_market_state(
    calendar: MarketCalendar | MarketCalendarRange,
    trade_date: str,
    *,
    market: str,
) -> TradingDayState:
    """Resolve one market and raise with date/market identity if its year is absent."""
    market = _market_key(market)
    parsed = _parse_date8(trade_date)
    year_calendar = _calendar_for_date(
        calendar,
        parsed,
        market=market,
        trade_date=trade_date,
    )
    states = resolve_market_states(year_calendar, trade_date)
    return states[market]


def _session_search_limit(calendar: MarketCalendar | MarketCalendarRange) -> int:
    return 366 * (len(calendar.calendars) if isinstance(calendar, MarketCalendarRange) else 1)


def previous_session(
    calendar: MarketCalendar | MarketCalendarRange,
    trade_date: str,
    *,
    market: str,
) -> str:
    if market not in {"a_share", "hk_securities", "hk_connect"}:
        raise ValueError("unsupported previous-session market")
    market = _market_key(market)
    try:
        parsed = _parse_date8(trade_date)
    except ValueError as error:
        raise ValueError("previous-session date is outside frozen calendar") from error
    _calendar_for_date(calendar, parsed, market=market, trade_date=trade_date)
    cursor = parsed - timedelta(days=1)
    for _ in range(_session_search_limit(calendar)):
        date8 = cursor.strftime("%Y%m%d")
        state = resolve_market_state(calendar, date8, market=market)
        if state in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }:
            return date8
        cursor -= timedelta(days=1)
    raise ValueError(f"previous session unresolved: market={market} trade_date={trade_date}")


def next_session(
    calendar: MarketCalendar | MarketCalendarRange,
    trade_date: str,
    *,
    market: str,
) -> str:
    if market not in {"a_share", "hk_securities", "hk_connect"}:
        raise ValueError("unsupported next-session market")
    market = _market_key(market)
    try:
        parsed = _parse_date8(trade_date)
    except ValueError as error:
        raise ValueError("next-session date is outside frozen calendar") from error
    _calendar_for_date(calendar, parsed, market=market, trade_date=trade_date)
    cursor = parsed + timedelta(days=1)
    for _ in range(_session_search_limit(calendar)):
        date8 = cursor.strftime("%Y%m%d")
        state = resolve_market_state(calendar, date8, market=market)
        if state in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }:
            return date8
        cursor += timedelta(days=1)
    raise ValueError(f"next session unresolved: market={market} trade_date={trade_date}")
