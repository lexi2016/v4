"""Strict V3.5-owned market-calendar contract types and loading."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
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


def _date8(value: Any, *, year: int) -> date:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError("calendar date must use YYYYMMDD")
    try:
        parsed = datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError("calendar date must be real") from error
    if parsed.year != year:
        raise ValueError("calendar date must match contract year")
    return parsed


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


def load_market_calendar(path: Path | None = None) -> MarketCalendar:
    source_path = CALENDAR_PATH if path is None else Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("market calendar cannot be loaded") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "year",
        "timezone",
        "official_sources",
        "markets",
    }:
        raise ValueError("invalid market calendar envelope")
    if payload["schema_version"] != SCHEMA_VERSION or payload["year"] != 2026:
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
        year=payload["year"],
        timezone=payload["timezone"],
        official_sources=tuple(official_sources),
        markets=validated,
    )


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
    calendar: MarketCalendar,
    trade_date: str,
) -> dict[str, TradingDayState]:
    parsed = parse_trade_date(trade_date, year=calendar.year)
    if parsed is None:
        return {
            "a_share": TradingDayState.UNKNOWN,
            "hk_securities": TradingDayState.UNKNOWN,
            "hk_connect": TradingDayState.UNKNOWN,
        }
    a_share = direct_market_state(parsed, calendar.markets["a_share"])
    hk_securities = direct_market_state(parsed, calendar.markets["hk_securities"])
    if TradingDayState.NON_TRADING_DAY in {a_share, hk_securities}:
        hk_connect = TradingDayState.NON_TRADING_DAY
    elif TradingDayState.HALF_TRADING_DAY_AM in {a_share, hk_securities}:
        hk_connect = TradingDayState.HALF_TRADING_DAY_AM
    else:
        hk_connect = TradingDayState.FULL_TRADING_DAY
    return {
        "a_share": a_share,
        "hk_securities": hk_securities,
        "hk_connect": hk_connect,
    }


def previous_session(
    calendar: MarketCalendar,
    trade_date: str,
    *,
    market: str,
) -> str:
    if market not in {"a_share", "hk_securities", "hk_connect"}:
        raise ValueError("unsupported previous-session market")
    parsed = parse_trade_date(trade_date, year=calendar.year)
    if parsed is None:
        raise ValueError("previous-session date is outside frozen calendar")
    cursor = parsed - timedelta(days=1)
    while cursor.year == calendar.year:
        date8 = cursor.strftime("%Y%m%d")
        state = resolve_market_states(calendar, date8)[market]
        if state in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }:
            return date8
        cursor -= timedelta(days=1)
    raise ValueError("previous session is outside frozen calendar")


def next_session(
    calendar: MarketCalendar,
    trade_date: str,
    *,
    market: str,
) -> str:
    if market not in {"a_share", "hk_securities", "hk_connect"}:
        raise ValueError("unsupported next-session market")
    parsed = parse_trade_date(trade_date, year=calendar.year)
    if parsed is None:
        raise ValueError("next-session date is outside frozen calendar")
    cursor = parsed + timedelta(days=1)
    while cursor.year == calendar.year:
        date8 = cursor.strftime("%Y%m%d")
        state = resolve_market_states(calendar, date8)[market]
        if state in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }:
            return date8
        cursor += timedelta(days=1)
    raise ValueError("next session is outside frozen calendar")
