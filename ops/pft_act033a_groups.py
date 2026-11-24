"""ACT-033A fixed, D-only group predicates and pre-execution ranks."""
from __future__ import annotations

from datetime import datetime
from math import isclose
from statistics import mean

import pandas as pd

from ops import pft_act031_frozen_forward as act031

GROUPS = ("BASE", "A0", "A1", "B1", "C1")
C1_ARMS = ("C1_A1", "C1_B1")
ALL_GROUPS = GROUPS + C1_ARMS
FINANCE_SOURCE = "TDX_DATED_PANEL_GBBQ_FLOAT_SHARE_AND_NATIVE_TURNOVER"
CONTRADICTION = "RAW_HEAD_DECISION_CONTRADICTION"



def main_board(code):
    return ((code.endswith(".SH") and code.startswith("60"))
            or (code.endswith(".SZ") and code.startswith("00")))


def finite(value):
    return act031.prior.finite(value)


def gte(value, limit):
    if value is None:
        return None
    return value > limit or isclose(value, limit, rel_tol=0, abs_tol=1e-12)


def lte(value, limit):
    if value is None:
        return None
    return value < limit or isclose(value, limit, rel_tol=0, abs_tol=1e-12)


def within(value, lower, upper, *, lower_closed=True):
    return conjunction(gte(value, lower) if lower_closed else negation(lte(value, lower)), lte(value, upper))


def negation(value):
    return None if value is None else not value


def conjunction(*values):
    if False in values:
        return False
    return None if None in values else True


def disjunction(*values):
    if True in values:
        return True
    return None if None in values else False


def ratio(numerator, denominator):
    den = act031.positive(denominator)
    return numerator / den if numerator is not None and den is not None else None


def distance_days(anchor, day):
    anchor = act031.act028.date8(anchor)
    if anchor is None or anchor > day:
        return None
    return (datetime.strptime(day, "%Y%m%d") - datetime.strptime(anchor, "%Y%m%d")).days


def positive_at(hist, field, day):
    return act031.positive(hist.get(day, {}).get(field))


def consecutive(hist, field, days, *, positive=True):
    parser = act031.positive if positive else finite
    values = [parser(hist.get(day, {}).get(field)) for day in days]
    if None in values or not positive and any(value < 0 for value in values):
        return None
    return values


def main_board_d_cap(quote):
    if not quote or not quote.get("eligible_for_daily_gain_rank"):
        return None
    from decimal import Decimal, ROUND_HALF_UP

    previous = act031.positive(quote.get("prev_close"))
    if previous is None:
        return None
    o, h, low, close = (quote[k] for k in ("open", "high", "low", "close"))
    def cap(factor):
        return float((Decimal(str(previous)) * Decimal(factor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    lower, upper = cap("0.90"), cap("1.10")
    if h > upper + 1e-6 or low < lower - 1e-6:
        return "STANDARD_DAILY_LIMIT_EXCEPTION"
    if o == h == low == close:
        return "ONE_PRICE"
    if close >= upper - 1e-6 or close <= lower + 1e-6:
        return "CLOSE_AT_DAILY_LIMIT"
    return "NON_LIMIT_NON_ONE_PRICE"


def evidence(row, hist, quote, days):
    """Measure volume and lines on one exact-D QFQ prefix, tradeability in raw prices."""
    day = days[-1]
    anchor = act031.act028.date8(row.invalidation_anchor_date)
    quote = quote or {}
    current = hist.get(day, {})
    close = act031.positive(current.get("close"))
    invalidation = act031.positive(row.invalidation_price)
    raw_close = act031.positive(quote.get("close"))
    raw_previous = act031.positive(quote.get("prev_close"))
    o, h, low = (act031.positive(quote.get(k)) for k in ("open", "high", "low"))
    vol = act031.positive(current.get("vol"))
    vol_prev = positive_at(hist, "vol", days[-2])
    volumes5 = consecutive(hist, "vol", days[-5:])
    volumes10 = consecutive(hist, "vol", days[-10:])
    volumes_prior3 = consecutive(hist, "vol", days[-4:-1])
    turnover = consecutive(hist, "turnover_rate_pct", days[-20:], positive=False)
    shares = act031.positive(current.get("float_share_10k"))
    qfq_low = act031.positive(current.get("low"))
    white, yellow = act031.positive(row.white), act031.positive(row.yellow)
    p = finite(row.projected_p_s)
    vol_ratio = ratio(vol, vol_prev)
    close5 = positive_at(hist, "close", days[-6])
    highs = consecutive(hist, "high", days[-20:])
    lows = consecutive(hist, "low", days[-20:])
    prior_closes = consecutive(hist, "close", days[-21:-1])
    amplitude20 = (mean((upper - lower) / previous for upper, lower, previous in zip(highs, lows, prior_closes))
                   if highs and lows and prior_closes else None)
    turnover20 = mean(turnover) if turnover else None
    market_cap = shares * 10_000 * raw_close if None not in (shares, raw_close) else None
    dividend_style = conjunction(negation(lte(market_cap, 50e9)),
                                 disjunction(negation(gte(turnover20, 1.5)), negation(gte(amplitude20, .03))))
    return {
        "close_d": close,
        "return_d": raw_close / raw_previous - 1 if raw_close is not None and raw_previous is not None else None,
        "raw_bullish": raw_close > o if None not in (raw_close, o) else None,
        "amount_d_cny": act031.positive(quote.get("amount_cny")),
        "amplitude_d": (h - low) / raw_previous if None not in (h, low, raw_previous) else None,
        "close_bar_fraction": (raw_close - low) / (h - low) if None not in (raw_close, h, low) and h > low else None,
        "board_cap_status": main_board_d_cap(quote),
        "anchor_age_calendar_days": distance_days(anchor, day),
        "cushion": (close - invalidation) / close if None not in (close, invalidation) else None,
        "vol_d": vol,
        "vol_d1_prior": vol_prev,
        "vol_ma5_d": mean(volumes5) if volumes5 else None,
        "vol_ma10_d": mean(volumes10) if volumes10 else None,
        "vol_min_prior3": min(volumes_prior3) if volumes_prior3 else None,
        "anchor_vol": positive_at(hist, "vol", anchor) if anchor else None,
        "kdj_j": finite(current.get("j")),
        "defended_white_yellow": gte(qfq_low, max(white, yellow)) if None not in (white, yellow) else None,
        "turnover_ma20_pct": turnover20,
        "amplitude_ma20": amplitude20,
        "float_mv_d_cny": market_cap,
        "dividend_style_proxy": dividend_style,
        "return_5d": close / close5 - 1 if None not in (close, close5) else None,
        "vol_ratio_prior_day": vol_ratio,
        "b2_rank_score": vol_ratio * p if None not in (vol_ratio, p) else None,
    }


def structural(row, data):
    main = main_board(row.ts_code)
    base = row.final_state == "CONFIRMED_S"
    post_repair = row.stage == "POST_REPAIR"
    high_p = gte(finite(row.projected_p_s), .85)
    old = gte(data["anchor_age_calendar_days"], 8)
    a0 = conjunction(main, base, row.main_tactic in ("pullback", "rebuild"), high_p, old,
                     within(data["cushion"], 0, .10, lower_closed=False))
    a1_volume = disjunction(lte(ratio(data["vol_d"], data["vol_ma5_d"]), .8),
                            lte(ratio(data["vol_d"], data["anchor_vol"]), .7))
    daily_move = data["return_d"]
    a1_price = disjunction(lte(abs(daily_move) if daily_move is not None else None, .035),
                           conjunction(lte(data["kdj_j"], 20), data["defended_white_yellow"]))
    a1 = conjunction(a0, post_repair, a1_volume, a1_price)
    b1_core = conjunction(main, base, post_repair, high_p, old, within(data["cushion"], .05, .20, lower_closed=False))
    b1_supplement = main and row.final_state == "UNKNOWN_BORDERLINE" and row.route_reasons == CONTRADICTION
    b1 = disjunction(b1_core, b1_supplement)
    d_status = data["board_cap_status"]
    b2_filters = {
        "prior_contraction": lte(ratio(data["vol_min_prior3"], data["vol_ma10_d"]), .75),
        "d_amplification": gte(data["vol_ratio_prior_day"], 1.30),
        "d_return": within(daily_move, .02, .075),
        "d_bullish": data["raw_bullish"],
        "d_close_location": gte(data["close_bar_fraction"], .65),
        "turnover_ma20": gte(data["turnover_ma20_pct"], 1.5),
        "amplitude_ma20": gte(data["amplitude_ma20"], .03),
        "float_market_cap": lte(data["float_mv_d_cny"], 50e9),
        "return_5d": lte(data["return_5d"], .15),
        "d_non_limit_non_one_price": (None if d_status in (None, "STANDARD_DAILY_LIMIT_EXCEPTION")
                                       else d_status == "NON_LIMIT_NON_ONE_PRICE"),
        "b2_score": True if data["b2_rank_score"] is not None else None,
    }
    b2 = conjunction(b1, *b2_filters.values())
    return {
        "BASE_eligible": base, "A0_eligible": a0, "A1_eligible": a1, "B1_eligible": b2,
        "b1_structural_eligible": b1,
        "a1_volume_gate": a1_volume, "a1_price_gate": a1_price, "b1_confirmed_arm": b1_core,
        "b1_exact_contradiction_arm": b1_supplement,
        "b2_failed_atoms": "|".join(key for key, value in b2_filters.items() if value is False) if b1 is True else None,
        "b2_unknown_atoms": "|".join(key for key, value in b2_filters.items() if value is None) if b1 is True else None,
    }


def overlay_scope(signal):
    """Only confirmed plausible A/B rows and the exact B1 exception need D overlays."""
    return set(signal.loc[
        signal.final_state.eq("CONFIRMED_S")
        | (signal.ts_code.map(main_board) & signal.final_state.eq("UNKNOWN_BORDERLINE")
           & signal.route_reasons.eq(CONTRADICTION)),
        "ts_code"
    ])


def a1_size(baseline_confirmed):
    return 3 if baseline_confirmed > 120 else 5


def select_day(signal, overlay, quotes, days):
    """Select before reading D+1; selected ranks never refill after open failures."""
    history = {code: frame.set_index("trade_date").to_dict("index")
               for code, frame in overlay.groupby("ts_code", sort=False)}
    rows = []
    for row in signal.itertuples(index=False):
        data = evidence(row, history.get(row.ts_code, {}), quotes.get(row.ts_code), days)
        rows.append({**data, **structural(row, data)})
    result = pd.concat([signal.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    result["dividend_style_proxy"] = result["dividend_style_proxy"].astype("boolean")
    for group in GROUPS[:-1]:
        result[f"{group}_eligible"] = result[f"{group}_eligible"].astype("boolean")
    result["b1_structural_eligible"] = result["b1_structural_eligible"].astype("boolean")
    result["BASE"] = result.BASE_eligible.fillna(False).astype(bool)
    baseline_confirmed = int(result.BASE.sum())
    cap1 = a1_size(baseline_confirmed)
    for group, cap, fields, order in (
        ("A0", 5, ["anchor_age_calendar_days", "projected_p_s", "ts_code"], [False, False, True]),
        ("A1", cap1, ["anchor_age_calendar_days", "projected_p_s", "ts_code"], [False, False, True]),
        ("B1", 8, ["b2_rank_score", "ts_code"], [False, True]),
    ):
        ranked = result.loc[result[f"{group}_eligible"].eq(True)].sort_values(fields, ascending=order)
        result[f"{group}_rank"] = pd.Series(range(1, len(ranked) + 1), index=ranked.index, dtype="Int64")
        result[group] = result[f"{group}_rank"].le(cap).fillna(False)
    arm_a = result.A1.mask(result.A1_eligible.isna(), pd.NA)
    arm_b = result.B1.mask(result.B1_eligible.isna(), pd.NA)
    for group, mask in (("C1", arm_a | arm_b), ("C1_A1", arm_a), ("C1_B1", arm_b)):
        result[f"{group}_eligible"] = mask.where(mask.eq(False), pd.NA).astype("boolean")
        result[group] = False
    summary = {
        "a1_confirmed_crowd_count": baseline_confirmed,
        "a1_crowd_class": "SEVERE" if baseline_confirmed > 120 else "CROWDED" if baseline_confirmed > 80 else "NORMAL",
        "b1_structural_confirmed_n": int(result.b1_structural_eligible.sum()),
        "b1_structural_unknown_n": int(result.b1_structural_eligible.isna().sum()),
        "a1_daily_cap": cap1,
        "groups": {group: {"eligible_n": int(result[f"{group}_eligible"].sum()),
                           "unknown_n": int(result[f"{group}_eligible"].isna().sum()),
                           "selected_n": int(result[group].sum()) if group not in ("C1", *C1_ARMS) else None}
                   for group in ALL_GROUPS},
    }
    return result, summary
