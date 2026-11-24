"""Frozen ACT-034A D-only filters and T+1 exit rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from math import isclose, isfinite
from statistics import mean

import pandas as pd

from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates
from ops.pft_act033a_outcomes import FEE, selling_outcome

CUTOFF = "20261123"
EPS = 1e-12
# Native prices are cent-denominated. The declared tolerance accommodates
# half-cent rounding of the adjusted price, plus floating-point serialization.
PRICE_TOLERANCE = .005001


def raw_ratio(quote, numerator, denominator):
    if not quote or not quote.get("eligible_for_daily_gain_rank"):
        return None
    upper, lower = (act031.positive(quote.get(key)) for key in (numerator, denominator))
    return upper / lower - 1 if None not in (upper, lower) else None


def upper_wick(quote):
    if not quote or not quote.get("eligible_for_daily_gain_rank"):
        return None
    return (quote["high"] - max(quote["open"], quote["close"])) / quote["prev_close"]


def selection_atoms(row, wick):
    cushion = gates.finite(row.cushion)
    age = gates.gte(gates.finite(row.anchor_age_calendar_days), 8)
    p = gates.gte(gates.finite(row.projected_p_s), .85)
    confirmed = gates.conjunction(
        row.final_state == "CONFIRMED_S", row.stage == "POST_REPAIR" if pd.notna(row.stage) else False, p, age,
        gates.within(cushion, .05, .18, lower_closed=False),
    )
    pure_head = gates.conjunction(
        row.final_state == "UNKNOWN_BORDERLINE",
        row.route_reasons == gates.CONTRADICTION if pd.notna(row.route_reasons) else False, age,
        gates.within(cushion, .05, .15, lower_closed=False),
    )
    structural = gates.conjunction(gates.main_board(row.ts_code), gates.disjunction(confirmed, pure_head))

    cap = gates.finite(row.float_mv_d_cny)
    amplitude = gates.finite(row.amplitude_ma20)
    slow_dividend = cap is not None and cap > 50e9 and amplitude is not None and amplitude < .03 - EPS
    volume_ratio = gates.ratio(gates.finite(row.vol_d), gates.finite(row.vol_ma5_d))
    bullish = None if pd.isna(row.raw_bullish) else bool(row.raw_bullish)
    filters = {
        "d_volume_ma5_ratio": gates.gte(volume_ratio, 1.15),
        "d_return": gates.within(gates.finite(row.return_d), .01, .085),
        "raw_bullish": bullish,
        "d_upper_wick": gates.lte(wick, .03),
        "slow_dividend": not slow_dividend,
    }
    eligible = gates.conjunction(structural, *filters.values())

    amount = gates.finite(row.amount_d_cny)
    move5 = gates.finite(row.return_5d)
    veto = {
        "amount_below_100m": gates.negation(gates.gte(amount, 100e6)),
        "return5_above_15pct": gates.negation(gates.lte(move5, .15)),
        "upper_wick_above_3_5pct": gates.negation(gates.lte(wick, .035)),
    }
    return {
        "d_upper_wick": wick,
        "b2_d_volume_ma5_ratio": volume_ratio,
        "b2_structural": structural,
        "b2_eligible": eligible,
        "b2_arm": ("CONFIRMED_POST_REPAIR" if confirmed is True else
                   "PURE_HEAD_CONFLICT" if pure_head is True else None),
        "b2_golden_priority": pure_head is True and gates.lte(cushion, .10) is True,
        "b2_slow_dividend_veto": slow_dividend,
        "b2_slow_dividend_inputs_complete": cap is not None and amplitude is not None,
        "b2_missing_float_cap": cap is None,
        "c1_pass": gates.negation(gates.disjunction(*veto.values())),
        "c1_veto_reasons": "|".join(key for key, value in veto.items() if value is True),
        "c1_unknown_atoms": "|".join(key for key, value in veto.items() if value is None),
    }


def affine_events(item, first_date, cutoff=CUTOFF):
    """Use the same chronological adjustment convention as the V4 QFQ owner."""
    if (not item or item.get("event_coverage_complete") is not True or "events" not in item
            or int(item["history_start_date"]) > int(first_date)):
        return None
    dates = []
    events = []
    for event in item["events"]:
        date, factor, offset = (int(event["ex_date"]), float(event["a"]), float(event["b"]))
        if not int(item["history_start_date"]) < date <= int(cutoff) or not isfinite(factor) or factor <= 0 or not isfinite(offset):
            raise act031.ContractError("ACT034A_CUTOFF_AFFINE_EVENT_INVALID")
        dates.append(date)
        if int(first_date) < date:
            events.append((date, factor, offset))
    if dates != sorted(set(dates)):
        raise act031.ContractError("ACT034A_CUTOFF_AFFINE_EVENT_ORDER_OR_DUPLICATE")
    return tuple(events)


def to_cutoff_basis(price, date, events):
    value = gates.finite(price)
    if value is None or events is None:
        return None
    for ex_date, factor, offset in events:
        if int(date) < ex_date:
            value = factor * value + offset
    return act031.positive(value)


def same_price(left, right):
    return left is not None and right is not None and isclose(left, right, rel_tol=0, abs_tol=PRICE_TOLERANCE)


def verified_bar(bar, quote, date, events):
    """Use a field only when cutoff QFQ and transformed dated raw agree."""
    if not quote or not quote.get("eligible_for_daily_gain_rank"):
        return {}, "OFFICIAL_NO_VOLUME" if quote and quote.get("zero_volume") else "OFFICIAL_MISSING_OR_INVALID"
    if events is None:
        return {}, "CUTOFF_AFFINE_COVERAGE_UNKNOWN"
    if not bar or bar.get("tradeable_basic") != 1 or not act031.positive(bar.get("vol")):
        return {}, "CUTOFF_PANEL_MISSING_OR_UNTRADEABLE"
    verified = {}
    for field_name in ("open", "close", "low"):
        expected = to_cutoff_basis(quote.get(field_name), date, events)
        actual = act031.positive(bar.get(field_name))
        if same_price(expected, actual):
            verified[field_name] = actual
    status = "CUTOFF_QFQ_RAW_AFFINE_MATCH" if len(verified) == 3 else "CUTOFF_QFQ_RAW_AFFINE_MISMATCH"
    return verified, status


def cap_price(previous, multiplier):
    return float((Decimal(str(previous)) * multiplier).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def opening_sell(code, quote):
    """A lower-cap print at the opening auction cannot establish a fill."""
    if quote is None:
        return None, "EXIT_QUOTE_MISSING"
    if not quote.get("eligible_for_daily_gain_rank"):
        return (False, "EXIT_NO_VOLUME") if quote.get("zero_volume") else (None, "EXIT_INVALID_BAR")
    previous, band = act031.positive(quote.get("prev_close")), act031.inferred_band(code)
    if previous is None or band is None or act031.special_treatment(quote.get("name")) is not False:
        return None, "EXIT_STANDARD_CAP_INPUT_UNKNOWN"
    floor = cap_price(previous, 1 - Decimal(band))
    if quote["open"] < floor - 1e-6:
        return None, "EXIT_STANDARD_CAP_EXCEPTION"
    if quote["open"] <= floor + 1e-6:
        return False, "EXIT_OPEN_AT_LOWER_CAP"
    return True, "EXIT_MODELED_OPEN"


def quick_triggers(code, quote):
    high_move = raw_ratio(quote, "high", "prev_close")
    close_move = raw_ratio(quote, "close", "prev_close")
    previous = act031.positive(quote.get("prev_close")) if quote else None
    band = act031.inferred_band(code)
    unlocked = None
    if close_move is not None and band is not None and previous is not None and act031.special_treatment(quote.get("name")) is False:
        cap = cap_price(previous, 1 + Decimal(band))
        if quote["high"] <= cap + 1e-6:
            unlocked = quote["close"] < cap - 1e-6
    return {
        "D1_HIGH_GTE_4_AND_CLOSE_BELOW_CAP": gates.conjunction(gates.gte(high_move, .04), unlocked),
        "D1_CLOSE_LTE_MINUS_3_VS_OFFICIAL_PREV": gates.lte(close_move, -.03),
    }


def stop_triggers(close, anchor, entry, d1_o2c, horizon):
    gross = close / entry - 1 if close is not None else None
    return {
        "CLOSE_LT_INVALIDATION": (close < anchor - EPS if None not in (close, anchor) else None),
        "CLOSE_LOSS_GTE_7_VS_COST": gates.lte(gross, -.07),
        "D1_OPEN_TO_CLOSE_LTE_MINUS_3": gates.lte(d1_o2c, -.03) if horizon == 1 else False,
    }


@dataclass
class ExitOutcome:
    reason: str
    status: str = "CANNOT_CONFIRM"
    signal_date: str | None = None
    exit_date: str | None = None
    time: str | None = None
    price: float | None = None
    planned_time: str | None = None
    attempts: list[dict] = field(default_factory=list)
    cutoff_mark: float | None = None
    t3_ma5: float | None = None
    t3_close: float | None = None
    t5_trigger_audit: str | None = None
    unknown_decision_atoms: str | None = None


def attempt_exit(result, code, dates, start, timing, quotes, prices):
    """Attempt the original time, then retry at subsequent opens up to deadline."""
    result.planned_time = timing
    if start >= len(dates):
        result.status = "EXIT_DUE_AFTER_CUTOFF"
        if dates:
            result.cutoff_mark = prices.get(dates[-1], {}).get("close")
        return result
    for index, date in enumerate(dates[start:]):
        when = timing if index == 0 else "OPEN"
        proxy = opening_sell if when == "OPEN" else selling_outcome
        feasible, reason = proxy(code, quotes.get(date))
        price = prices.get(date, {}).get(when.lower())
        if feasible is True and price is None:
            feasible, reason = None, "EXIT_PRICE_BASIS_UNCONFIRMED"
        result.attempts.append({"date": date, "time": when, "fillable": feasible, "reason": reason})
        if feasible is True:
            result.status = "MODELED_FILLED_DELAYED" if index else "MODELED_FILLED"
            result.exit_date, result.time, result.price = date, when, price
            return result
    result.status = ("EXIT_BLOCKED_AT_DEADLINE" if all(attempt["fillable"] is False for attempt in result.attempts)
                     else "EXIT_UNRESOLVED_AT_DEADLINE")
    last_date = dates[-1]
    result.cutoff_mark = prices.get(last_date, {}).get("close")
    return result


def reason_string(triggers, status=True):
    return "|".join(key for key, triggered in triggers.items() if triggered is status)


def a1_exit(code, dates, context_dates, quotes, prices, entry, anchor, ma_closes):
    dates = dates[:5]
    extension = {}
    for index, date in enumerate(dates):
        horizon = index + 1
        close = prices.get(date, {}).get("close")
        d1_o2c = raw_ratio(quotes.get(date), "close", "open") if horizon == 1 else None
        triggers = stop_triggers(close, anchor, entry, d1_o2c, horizon)
        reason = reason_string(triggers)
        if horizon == 5:
            result = ExitOutcome("T5_HARD_CLOSE", signal_date=date, t5_trigger_audit=(
                reason or ("CANNOT_CONFIRM" if None in triggers.values() else "NONE")), **extension)
            return attempt_exit(result, code, dates, index, "CLOSE", quotes, prices)
        if reason:
            result = ExitOutcome(reason, signal_date=date, **extension)
            return attempt_exit(result, code, dates, index + 1, "OPEN", quotes, prices)
        suspended = quotes.get(date, {}).get("zero_volume") is True
        if None in triggers.values() and not suspended:
            return ExitOutcome("A1_INTERMEDIATE_STOP_EVIDENCE_UNKNOWN", signal_date=date,
                               unknown_decision_atoms=reason_string(triggers, None), **extension)
        if horizon == 3:
            position = context_dates.index(date)
            trailing = [ma_closes.get(session) for session in context_dates[max(0, position - 4):position + 1]]
            ma5 = mean(trailing) if len(trailing) == 5 and None not in trailing else None
            extension = {"t3_ma5": ma5, "t3_close": close}
            if close is not None and close > entry + EPS:
                if ma5 is None:
                    return ExitOutcome("T3_EXTENSION_MA5_UNKNOWN", signal_date=date,
                                       unknown_decision_atoms="T3_MA5", **extension)
                if close >= ma5 - EPS:
                    continue
            result = ExitOutcome("T3_PLANNED_CLOSE", signal_date=date, **extension)
            return attempt_exit(result, code, dates, index, "CLOSE", quotes, prices)
    return ExitOutcome("PLANNED_HORIZON_NOT_REACHED", status="HORIZON_IMMATURE_AT_CUTOFF", **extension)


def b2_exit(code, dates, quotes, prices):
    dates = dates[:3]
    triggers = quick_triggers(code, quotes.get(dates[0]))
    reason = reason_string(triggers)
    if reason:
        result = ExitOutcome(reason, signal_date=dates[0])
        return attempt_exit(result, code, dates, 1, "OPEN", quotes, prices)
    if None in triggers.values():
        return ExitOutcome("B2_D1_QUICK_TRIGGER_UNKNOWN", signal_date=dates[0],
                           unknown_decision_atoms=reason_string(triggers, None))
    if len(dates) < 3:
        return ExitOutcome("PLANNED_HORIZON_NOT_REACHED", status="HORIZON_IMMATURE_AT_CUTOFF")
    result = ExitOutcome("T3_PLANNED_CLOSE", signal_date=dates[2])
    return attempt_exit(result, code, dates, 2, "CLOSE", quotes, prices)


def path_low(dates, prices, result, entry):
    """Include only the exit open on an open exit. For unresolved trades, bound the mark."""
    trace = []
    for date in dates:
        if date == result.exit_date and result.time == "OPEN":
            trace.append(prices.get(date, {}).get("open"))
            break
        trace.append(prices.get(date, {}).get("low"))
        if date == result.exit_date:
            break
        if result.status == "CANNOT_CONFIRM" and date == result.signal_date:
            break
    observed = [value for value in trace if value is not None]
    return {
        "worst_observed_path_gross": min(observed) / entry - 1 if observed else None,
        "path_sessions": len(trace),
        "path_observed_sessions": len(observed),
        "path_complete": len(trace) == len(observed),
    }
