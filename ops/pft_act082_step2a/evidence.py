"""Translate D-only bars to schema-constrained, anonymous visual evidence."""

from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
import json

from ops.pft_act080_core.core import Bar, Indicators

from .calendar import INVALID, MISSING, OBSERVED, SUSPENDED, day_status

PROTOCOL = "AI_DUAL_BLIND_WITH_HUMAN_BATCH_AUDIT"
QUALITY_TIER = "DEV_SILVER_DRAFT"
WEEK_COUNT = 52
DEFAULT_LEFT = 120
EXTENDED_LEFT = 240
FOCUS_LEFT = 35


def canonical_json(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def _number(value):
    return None if value is None else round(value, 8)


def _values(bar, indicators, price, volume):
    vals = indicators.advance(bar)
    ohlc = tuple(_number(100 * x / price) for x in (bar.open, bar.high, bar.low, bar.close))
    return {
        "o": ohlc[0], "h": ohlc[1], "l": ohlc[2], "c": ohlc[3], "v": _number(bar.volume / volume),
        "W": _number(100 * vals["W"] / price),
        "Y": _number(100 * vals["Y"] / price) if vals["Y"] is not None else None,
        "K": _number(indicators.k) if vals["kdj_j"] is not None else None,
        "D_signal": _number(indicators.d) if vals["kdj_j"] is not None else None,
        "J": _number(vals["kdj_j"]),
    }


def _weekly(bars, candidate, calendar, suspensions, price, volume):
    by_week = defaultdict(list)
    for session in calendar.between(bars[0].trade_date, candidate.D):
        monday = date.fromisoformat(session)
        monday -= timedelta(days=monday.weekday())
        by_week[monday].append(session)
    first_monday = min(by_week)
    first_sessions = calendar.between(first_monday.isoformat(), (first_monday + timedelta(days=6)).isoformat())
    if first_sessions and first_sessions[0] < bars[0].trade_date:
        # The name/market/listing inception is not inferred from a partially observed first week.
        del by_week[first_monday]
    bars_by_date = {bar.trade_date: bar for bar in bars}
    result = []
    indicators = Indicators()
    for monday, sessions in sorted(by_week.items()):
        full_week = calendar.between(monday.isoformat(), (monday + timedelta(days=6)).isoformat())
        observed_count = len(sessions)
        scheduled_count = len(full_week)
        partial = observed_count < scheduled_count
        states = [day_status(day, bars_by_date.get(day), suspensions) for day in sessions]
        usable = [bars_by_date[day] for day, state in zip(sessions, states, strict=True) if state == OBSERVED]
        missing = states.count(MISSING)
        suspended = states.count(SUSPENDED)
        invalid = states.count(INVALID)
        if usable:
            last = usable[-1]
            aggregate = Bar(
                last.trade_date, usable[0].open, max(bar.high for bar in usable),
                min(bar.low for bar in usable), last.close, sum(bar.volume for bar in usable),
            )
            values = _values(aggregate, indicators, price, volume)
            values["mean_v_per_elapsed_exchange_day"] = _number(aggregate.volume / volume / observed_count)
        else:
            values = dict.fromkeys(("o", "h", "l", "c", "W", "Y", "K", "D_signal", "J"), None)
            values.update(v=0.0, mean_v_per_elapsed_exchange_day=0.0)
        result.append({
            **values, "partial": partial, "elapsed": observed_count, "scheduled": scheduled_count,
            "suspended": suspended, "missing": missing, "invalid": invalid, "observed": len(usable),
            "week_status": "PARTIAL" if partial else ("CLOSED_GAPPED" if missing or invalid else "CLOSED"),
        })
    return result[-WEEK_COUNT:]


def evidence_payload(bars, candidate, calendar, suspensions):
    """The only date-bearing arguments are internal. The UTC-free payload is relative."""
    dates = tuple(bar.trade_date for bar in bars)
    limit = bisect_right(dates, candidate.D)
    prefix = bars[:limit]
    if not prefix or prefix[-1].trade_date != candidate.D or not prefix[-1].positive_ohlc:
        raise ValueError("anonymous evidence requires the actual D bar")
    prefix_days = {bar.trade_date for bar in prefix}
    if any(day > candidate.D for day in candidate.root_dates):
        raise ValueError("future anchor at D")
    visible = {bar.trade_date for bar in prefix[-(DEFAULT_LEFT + 1):]}
    extend = not set(candidate.root_dates).issubset(visible)
    wide_limit = EXTENDED_LEFT if extend else DEFAULT_LEFT
    required = set(candidate.root_dates)
    visible_wide = {bar.trade_date for bar in prefix[-(wide_limit + 1):]}

    price_base = prefix[-1].close
    volume_base = max(bar.volume for bar in prefix[-(EXTENDED_LEFT + 1):])
    if volume_base <= 0:
        raise ValueError("anonymous evidence has no positive visual volume basis")
    indicators = Indicators()
    by_date, offsets = {}, {}
    for offset, bar in enumerate(prefix, 1 - len(prefix)):
        v = _values(bar, indicators, price_base, volume_base)
        offsets[bar.trade_date] = offset
        by_date[bar.trade_date] = {"i": offset, **v}
    daily = [by_date[bar.trade_date] for bar in prefix[-(wide_limit + 1):]]
    focus = daily[-(FOCUS_LEFT + 1):]
    weekly = _weekly(prefix, candidate, calendar, suspensions, price_base, volume_base)
    roots = [offsets[day] if day in prefix_days and day in visible_wide else "UNKNOWN"
             for day in candidate.root_dates]
    return {
        "daily_wide": daily, "daily_focus": focus, "weekly": weekly,
        "wide_left_sessions": wide_limit, "root_relative_positions": roots,
        "left_context": "AVAILABLE" if required <= visible_wide else "UNKNOWN",
        "weekly_context": "AVAILABLE" if weekly and all(row["W"] is not None and row["Y"] is not None
                                                        for row in weekly[-1:]) else "UNKNOWN",
        "market_context": "UNKNOWN", "price_scale": "D_CLOSE_100",
        "volume_scale": "ACTUAL_VOLUME_IN_COMMON_RELATIVE_UNITS",
        "brick_reference": "UNVERIFIED_CLASSROOM_VERSION_REFERENCE_ONLY",
    }

