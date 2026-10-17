"""Self-contained 2026 trading-calendar contract for the stage center.

The package deliberately does not import V3/V3.5 ``contracts``.  These
constants mirror the frozen local 2026 contract: weekdays are trading days
except the listed market closure periods; dates outside 2026 are unknown and
therefore fail closed.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum


class TradingDayState(StrEnum):
    FULL_TRADING_DAY = "FULL_TRADING_DAY"
    HALF_TRADING_DAY_AM = "HALF_TRADING_DAY_AM"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    UNKNOWN = "UNKNOWN"


# The package carries the validated calendar contract's identity rather than
# importing V3.5 at runtime.  The SHA pins the deployed canonical JSON asset
# used to derive the frozen closure periods below.
CALENDAR_SCHEMA_VERSION = "v3_5.market_calendar_2026.v1"
CALENDAR_SOURCE_SHA256 = "9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb"
CALENDAR_TIMEZONE = "Asia/Shanghai"


def calendar_provenance() -> dict[str, str]:
    return {
        "schema_version": CALENDAR_SCHEMA_VERSION,
        "source_sha256": CALENDAR_SOURCE_SHA256,
        "timezone": CALENDAR_TIMEZONE,
    }


_YEAR = 2026
_A_HOLIDAY_PERIODS = (
    ("20260101", "20260104"),
    ("20260215", "20260223"),
    ("20260404", "20260406"),
    ("20260501", "20260505"),
    ("20260619", "20260621"),
    ("20260925", "20260927"),
    ("20261001", "20261007"),
)
_HK_HOLIDAY_PERIODS = (
    ("20260101", "20260101"),
    ("20260217", "20260219"),
    ("20260403", "20260403"),
    ("20260406", "20260407"),
    ("20260501", "20260501"),
    ("20260525", "20260525"),
    ("20260619", "20260619"),
    ("20260701", "20260701"),
    ("20261001", "20261001"),
    ("20261019", "20261019"),
    ("20261225", "20261225"),
)
_HK_HALF_DAYS = frozenset(("20260216", "20261224", "20261231"))


def _parse_trade_date(value: str) -> date | None:
    try:
        parsed = datetime.strptime(str(value), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None
    return parsed if parsed.year == _YEAR else None


def _in_periods(date8: str, periods: tuple[tuple[str, str], ...]) -> bool:
    return any(start <= date8 <= end for start, end in periods)


def _direct_state(parsed: date, periods: tuple[tuple[str, str], ...], half_days: frozenset[str] = frozenset()) -> TradingDayState:
    date8 = parsed.strftime("%Y%m%d")
    if parsed.weekday() >= 5 or _in_periods(date8, periods):
        return TradingDayState.NON_TRADING_DAY
    if date8 in half_days:
        return TradingDayState.HALF_TRADING_DAY_AM
    return TradingDayState.FULL_TRADING_DAY


def resolve_market_states(trade_date: str) -> dict[str, TradingDayState]:
    """Resolve A/HK securities/HK Connect states; unknown dates are explicit."""
    parsed = _parse_trade_date(trade_date)
    if parsed is None:
        return {
            "a_share": TradingDayState.UNKNOWN,
            "hk_securities": TradingDayState.UNKNOWN,
            "hk_connect": TradingDayState.UNKNOWN,
        }
    a_share = _direct_state(parsed, _A_HOLIDAY_PERIODS)
    hk = _direct_state(parsed, _HK_HOLIDAY_PERIODS, _HK_HALF_DAYS)
    if TradingDayState.NON_TRADING_DAY in {a_share, hk}:
        connect = TradingDayState.NON_TRADING_DAY
    elif TradingDayState.HALF_TRADING_DAY_AM in {a_share, hk}:
        connect = TradingDayState.HALF_TRADING_DAY_AM
    else:
        connect = TradingDayState.FULL_TRADING_DAY
    return {"a_share": a_share, "hk_securities": hk, "hk_connect": connect}


def eligible_stage_markets(markets: tuple[str, ...], trade_date: str) -> tuple[str, ...]:
    """Resolve the stage's active A/HK observation lanes for one date.

    HK stage work is eligible whenever HK securities are open, including
    Southbound-closed sessions; the HK Connect calendar state remains separate
    evidence and does not open or close the Hong Kong securities market.
    """
    states = resolve_market_states(trade_date)
    if any(state is TradingDayState.UNKNOWN for state in states.values()):
        raise ValueError("market calendar unknown for trade_date")
    open_states = {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }
    market_state = {
        "A_SHARE": states["a_share"],
        "HK_CONNECT": states["hk_securities"],
    }
    if any(market not in market_state for market in markets):
        raise ValueError("stage contains an unknown market")
    eligible = tuple(
        market for market in markets if market_state[market] in open_states
    )
    return eligible


__all__ = [
    "CALENDAR_SCHEMA_VERSION",
    "CALENDAR_SOURCE_SHA256",
    "CALENDAR_TIMEZONE",
    "TradingDayState",
    "calendar_provenance",
    "eligible_stage_markets",
    "resolve_market_states",
]
