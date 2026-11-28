"""Frozen ACT-071R scheme B stock and stock-session selection."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping

from research.act069b.adapter import Bar
from research.act070a.case_contract import OHLCV_FIELDS, iso_day, require, sha256
from research.act071a.case_contract import CHART_SESSIONS, STOCK_PATTERN

SEED = "ACT071R_V1.1"
FIRST_D = date(2017, 10, 19)
LAST_D = date(2026, 11, 6)
QUADRANTS = (
    "BULLISH_INCREASE", "BULLISH_NOT_INCREASE",
    "NON_BULLISH_INCREASE", "NON_BULLISH_NOT_INCREASE",
)
QUOTA = 2
B2_FALSE_MINIMUM = 2


@dataclass(frozen=True)
class Session:
    day: date
    bar: Bar | None


@dataclass(frozen=True)
class Proxy:
    index: int
    day: date
    quadrant: int


@dataclass(frozen=True)
class Selection:
    stock_code: str
    sessions: tuple[Session, ...]
    chosen: tuple[Proxy, ...]


def stock_hash(code: str) -> str:
    return sha256(f"{SEED}:{code}".encode("ascii"))


def freeze_pool(stock_codes: Iterable[str], exclusions: set[str]) -> tuple[str, ...]:
    codes = tuple(stock_codes)
    require(all(isinstance(code, str) and STOCK_PATTERN.fullmatch(code) for code in codes),
            "INVALID_A_STOCK_POOL", "reader must project canonical A-share codes only")
    require(len(codes) == len(set(codes)), "DUPLICATE_STOCK_CODE", "reader stock pool")
    return tuple(sorted(set(codes) - exclusions, key=lambda code: (stock_hash(code), code)))


def session_day(value: object) -> date:
    if isinstance(value, datetime):
        require(value.time() == datetime.min.time(), "INVALID_DATE", str(value))
        return value.date()
    if isinstance(value, date):
        return value
    if type(value) is int or isinstance(value, str) and value.isascii() and value.isdigit():
        token = str(value)
        return iso_day(f"{token[:4]}-{token[4:6]}-{token[6:]}")
    return iso_day(value)


def read_sessions(rows: Iterable[Mapping[str, object]]) -> tuple[Session, ...]:
    """Keep supplied actual stock sessions in date order, including unusable rows."""
    sessions = []
    fields = {"date", *OHLCV_FIELDS}
    for row in rows:
        require(set(row) == fields, "INVALID_READER_PROJECTION", "only exact date and OHLCV")
        day = session_day(row["date"])
        require(day <= LAST_D and (not sessions or day > sessions[-1].day),
                "INVALID_SESSION_ORDER_OR_CUTOFF", str(day))
        try:
            require(not any(type(row[field]) is bool for field in OHLCV_FIELDS),
                    "INVALID_READER_PROJECTION", "boolean OHLCV")
            bar = Bar.from_row({**row, "date": day.isoformat()})
        except (ValueError, TypeError, OverflowError):
            bar = None
        sessions.append(Session(day, bar if bar is not None and bar.volume > 0 else None))
    return tuple(sessions)


def observed_proxies(sessions: tuple[Session, ...]) -> list[Proxy]:
    proxies = []
    contiguous = 0
    for index, session in enumerate(sessions):
        bar = session.bar
        contiguous = contiguous + 1 if bar is not None else 0
        if contiguous < CHART_SESSIONS or session.day < FIRST_D:
            continue
        prior = sessions[index - 1].bar
        quadrant = (0 if bar.direction == "BULLISH" else 2) + (0 if bar.volume > prior.volume else 1)
        proxies.append(Proxy(index, session.day, quadrant))
    return proxies


def earliest_disjoint(proxies: list[Proxy]) -> tuple[Proxy, ...]:
    """Exact suffix feasibility, followed by the lexicographically first feasible D tuple."""
    indices = [item.index for item in proxies]
    size = len(proxies)
    after_window = [bisect_left(indices, index + CHART_SESSIONS) for index in indices]
    radix = QUOTA + 1
    strides = [radix**k for k in range(len(QUADRANTS))]
    states = radix**len(QUADRANTS)
    available = [bytearray(size + 1) for _ in range(states)]
    available[0][:] = b"\x01" * (size + 1)
    for state in range(1, states):
        for pos in range(size - 1, -1, -1):
            stride = strides[proxies[pos].quadrant]
            take = state // stride % radix and available[state - stride][after_window[pos]]
            available[state][pos] = bool(available[state][pos + 1] or take)
    remaining = states - 1
    if not available[remaining][0]:
        return ()
    result = []
    pos = 0
    while remaining:
        item = proxies[pos]
        stride = strides[item.quadrant]
        if remaining // stride % radix and available[remaining - stride][after_window[pos]]:
            result.append(item)
            remaining -= stride
            pos = after_window[pos]
        else:
            pos += 1
    return tuple(result)


def b2_for_day(bar: Bar) -> str:
    """Independent ACT-069B necessary candle condition for a formal B2 D0."""
    return "FALSE" if bar.close <= bar.open else "UNKNOWN"


def first_feasible(pool: tuple[str, ...], load_sessions) -> tuple[Selection | None, list[dict]]:
    skips = []
    for code in pool:
        sessions = read_sessions(load_sessions(code))
        proxies = observed_proxies(sessions)
        counts = Counter(item.quadrant for item in proxies)
        entry = {
            "stock_code": code, "order_sha256": stock_hash(code),
            "session_count": len(sessions),
            "first_session": str(sessions[0].day) if sessions else None,
            "last_session": str(sessions[-1].day) if sessions else None,
            "invalid_session_count": sum(item.bar is None for item in sessions),
            "available_quadrants": {key: counts[i] for i, key in enumerate(QUADRANTS)},
        }
        reason = "INSUFFICIENT_OBSERVED_QUADRANT_DATES"
        if all(counts[i] >= QUOTA for i in range(len(QUADRANTS))):
            chosen = earliest_disjoint(proxies)
            if chosen:
                require(sum(b2_for_day(sessions[item.index].bar) == "FALSE" for item in chosen) >= B2_FALSE_MINIMUM,
                        "B2_FALSE_QUOTA", code)
                return Selection(code, sessions, chosen), skips
            reason = "NO_DISJOINT_EIGHT_WINDOW_COMBINATION"
        skips.append({**entry, "reason": reason})
    return None, skips
