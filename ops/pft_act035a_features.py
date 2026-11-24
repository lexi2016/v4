"""Bounded D-prefix measurements for the ACT035A research replay."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.trading_calendar import TradingDayState, direct_market_state
from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates
from ops import pft_act034a_rules as rules
from ops import research_panel_daily_product as daily_product
from ops import research_panel_logical as reader

ACT030 = {
    "path": str(Path.home() / ".codex/worktrees/pft-act030-feature-parity-20261123/ops/pft_act030_features.py"),
    "sha256": "463cd3cc5e810bfb87e0078037e87d2703d90b1c48b20c083ea5c84bbe5b8072",
    "commit": "a9445421ebdb85e109cd31175db5281064a95763",
}
ASOF = "20261120"
GENERATION = "4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268"
PANEL_SHA = "2ce50ea1ec19be7e7011f8326d5daba8f32f6029e33dba6022d650f862c124ec"
MANIFEST_SHA = "e00b0cbffbd36a80242facc74db583845d3466ae8fe9590f7920cfc6e5b6e633"
SNAPSHOT_SHA = "4d17921c1de7394e738aaf0984f3ba2d74f4a004074c9e8692dbcf5d4bd1542d"
COLUMNS = ("open", "high", "low", "close", "vol", "amount", "zge_white_line", "zge_yellow_line", "bbi",
           "j", "pre_close", "tradeable_basic")
PRICE = ("open", "high", "low", "close", "zge_white_line", "zge_yellow_line", "bbi", "pre_close")
WINDOW = 41
LIQUIDITY_CNY = 50_000_000
P515_FIELDS = ("advance_from_low20_pp", "prior_attack_runup_pp", "amount_ratio_20", "close_vs_white_pp",
               "J", "drawdown_from_prior20_high_pp", "prior20_volatility_pp", "adv20_cny",
               "median_amount20_cny", "days_since_20d_vol_peak", "pullback_vol_decay_ratio", "l50m", "hard_climax",
               "amount_ratio_20_act006_v4", "d_qfq_return_5d", "d_basis_close")
V_PROXY_FIELDS = (
    "hinted_anchor_date", "active_anchor_date", "active_anchor_source", "active_anchor_low", "active_anchor_mid",
    "active_anchor_body_return", "active_anchor_prior5_volume_ratio", "active_anchor_close_vs_white_pct",
    "prior_anchor_breach", "intact_anchor", "V01", "V02", "V03", "V04", "V05", "V06",
    "v02_extension", "v02_distribution", "v02_healthy_breakout", "d_upper_wick_range_fraction",
    "d_close_location", "d_prior5_volume_ratio", "d_anchor_volume_ratio", "v06_supply_date",
    "v06_supply_body_return", "v06_supply_platform_vol_ratio", "v06_supply_anchor_vol_ratio",
    "v06_supply_atr_ratio", "v06_supply_close_location", "v06_later_close_reclaimed",
    "pft_status", "v01_v03_v05_status", "anchor_window_status",
)
POLICY = {
    "P515_BASE20": "Contiguous exchange sessions. Earliest min low in D-20..D-3, max high strictly after it through D-1. Drawdown and volatility use prior20. Volatility is population std of close/pre_close-1 in pp. Amount uses raw CNY, prior20 arithmetic mean and D-inclusive 20 median.",
    "P515_L50M": "SH/SZ, valid positive non-flat D OHLC, positive D volume, dated non-ST official name, D-inclusive 20 contiguous median raw CNY amount >=50m.",
    "P515_CLIMAX": "(BASE20 runup >25pp AND D amount/prior20 >1.2) OR (D close/white >15pp AND native J >80).",
    "P515_PEAK_DECAY": "Most recent tied maximum on last 20 valid positive-volume bars including D. Descending post-peak time includes D. Decay is mean later volume/peak; D peak leaves decay unknown.",
    "PFT_ANCHOR": "A valid causal hint has positive body return >=3%, volume over prior5 >=1.2, and anchor close >= then white. Otherwise use the last qualifying prior-20 bar. Mid = (O+C)/2. D close >= active low and no earlier intervening close below active low require complete anchor window.",
    "V02_LOCAL_PROXY": "Close/white >15pp OR (BASE20 runup >25pp and close >=95% of prior20 H), AND (wick/range >=35% or bearish body) AND close location <65% AND V/prior5 >=1.2 AND V/anchor >=1. Exclude healthy positive body, close location >=65%, strict pre-D 20-session high break.",
    "V04_LOCAL_PROXY": "D close below selected active anchor low; earlier close breach reported independently.",
    "V06_LOCAL_PROXY": "In last five at or after selected active anchor, bearish body <=-3%, close location <=35%, V/ACT030 dated platform >=1.2, V/anchor >=1, and TR/prior20 ATR >=1.2. Remains true until a later close reaches supply bar open through D.",
    "V01_V03_V05": "SPEC_REQUIRES_CONTEXT; left null.",
    "historical_pit": "CANNOT_CONFIRM. Exact asof source and positive D-only windows; documented post-D price and volume transforms are undone. Earlier snapshots, historical revisions and full PFT Gold rule semantics are unverified.",
}


def require(condition, reason):
    if not condition:
        raise act031.ContractError(f"ACT035A_{reason}")


def load_act030():
    return daily_product.module(ACT030, "_pft_act035a_pinned_act030")


def bind(source):
    require(source["source_generation"] == GENERATION and source["panel_sha256"] == PANEL_SHA
            and source["producer_ref"]["sha256"] == MANIFEST_SHA and source["panel_role"] == "backtest"
            and source["price_basis"] == "QFQ_ASOF" and source["volume_basis"] == "QFQ_EVENT_VOLUME",
            "ACT030_BACKTEST_SOURCE_DRIFT")
    bound = act031.bind_panel(ASOF, source)
    receipt = act031.read_ref(source["producer_ref"])
    snap_ref = receipt["adjustment_snapshot"]
    require(snap_ref["sha256"] == SNAPSHOT_SHA == receipt["snapshot_file_sha256"],
            "ACT030_ADJUSTMENT_SNAPSHOT_DRIFT")
    snapshot = act031.read_ref(snap_ref)
    require(snapshot["asof_date"] == snapshot["coverage_end_date"] == int(ASOF)
            and snapshot["price_basis"] == "QFQ_ASOF" and snapshot["volume_basis"] == "QFQ_EVENT_VOLUME"
            and snapshot["amount_basis"] == "RAW_TURNOVER", "ACT030_ADJUSTMENT_SCOPE_DRIFT")
    schema = reader.parquet.read_schema(bound[0])
    require(set(COLUMNS) <= {column.lower() for column in schema.names}, "ACT030_REQUIRED_COLUMN_MISSING")
    identity = {"backtest": source, "adjustment": snap_ref, "ACT030": ACT030,
                "historical_pit": "CANNOT_CONFIRM",
                "snapshot_historical_pit": snapshot.get("historical_PIT"),
                "pre_close_basis": "V4 QFQ REF(CLOSE,1) under the same adjustment as close"}
    return bound, snapshot["symbols"], identity


def exchange_days(schedule):
    day, end = date(schedule.year, 1, 1), date(schedule.year, 12, 31)
    valid = {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}
    days = []
    while day <= end:
        if direct_market_state(day, schedule.markets["a_share"]) in valid:
            days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return days


def earlier(day, days):
    return (date.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}") - timedelta(days=days)).strftime("%Y%m%d")


def observations(bound, start, end, codes):
    return act031.read_panel(bound, start, end, COLUMNS, codes=codes)


def observed_histories(frame):
    return {str(code): part.reset_index(drop=True) for code, part in frame.groupby("ts_code", sort=False)}


class Adjustment:
    def __init__(self, symbols, act030):
        self.symbols = symbols
        self.act030 = act030

    @lru_cache(maxsize=None)
    def timeline(self, code):
        item = self.symbols.get(code)
        if not item or item.get("event_coverage_complete") is not True or "events" not in item:
            return None
        # A malformed event in the source ledger is a source error. Coverage
        # gaps for an otherwise bound row remain unknown at the row level.
        self.act030.events_after(item["events"], ASOF, ASOF)
        return str(item["history_start_date"]), tuple(item["events"])

    def suffix(self, code, day, start):
        timeline = self.timeline(code)
        if timeline is None or start < timeline[0]:
            return None
        return tuple(event for event in reversed(timeline[1]) if str(event["ex_date"]) > day)

    def for_window(self, code, day, frame):
        if frame is None:
            return None, None
        last = frame.trade_date.searchsorted(day, side="right")
        prefix = frame.iloc[:last]
        if prefix.empty or prefix.trade_date.iat[-1] != day:
            return None, None
        suffix = self.suffix(code, day, str(prefix.trade_date.iat[0]))
        if suffix is None:
            return None, None
        if suffix:
            prefix = prefix.copy()
            for event in suffix:
                prefix[list(PRICE)] = (prefix[list(PRICE)] - float(event["b"])) / float(event["a"])
                prefix["vol"] /= float(event["volume_a"])
        return prefix, len(suffix)


def divide(numerator, denominator):
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    num, den = np.broadcast_arrays(num, den)
    return np.divide(num, den, out=np.full(num.shape, np.nan), where=np.isfinite(num) & np.isfinite(den) & (den > 0))


def valid_bars(data):
    o, h, low, c, v = (data[k] for k in ("open", "high", "low", "close", "vol"))
    return ((o > 0) & (low > 0) & (c > 0) & (v > 0) & (h >= np.maximum(o, c)) & (low <= np.minimum(o, c))
            & np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c) & np.isfinite(v))


def tri_and(*args):
    result = np.ones(np.shape(args[0]))
    for value in args:
        result = np.where((result == 0) | (value == 0), 0, np.where(np.isnan(result) | np.isnan(value), np.nan, 1))
    return result


def tri_or(*args):
    return 1 - tri_and(*(1 - value for value in args))


def known_mask(values, test):
    return np.where(np.isfinite(values), test(values).astype(float), np.nan)


def base20(arrays, admits):
    """Compute the declared 21-column D-20..D grid; gaps are NaN."""
    require(arrays["open"].shape[1] == 21, "BASE20_EXACT_SESSION_SCOPE")
    bar = valid_bars(arrays)
    h, low, c, vol = (np.where(bar, arrays[k], np.nan) for k in ("high", "low", "close", "vol"))
    pri_h, pri_low = h[:, :-1], low[:, :-1]
    base = np.argmin(np.where(np.isfinite(pri_low[:, :18]), pri_low[:, :18], np.inf), axis=1)
    base_low = pri_low[np.arange(len(c)), base]
    after = np.arange(20)[None, :] > base[:, None]
    attack_high = np.max(np.where(after & np.isfinite(pri_h), pri_h, -np.inf), axis=1)
    complete = bar[:, :-1].all(axis=1)
    prior_high = np.where(complete, np.max(pri_h, axis=1), np.nan)
    runup = np.where(complete, 100 * (divide(attack_high, base_low) - 1), np.nan)
    dp = 100 * (divide(c[:, -1], prior_high) - 1)
    amount = arrays["amount"]
    # Amount depends on well-formed observed activity; QFQ chart values can
    # legitimately be negative for very old histories, so raw activity is the authority.
    usable_amount = np.where((amount > 0) & np.isfinite(amount), amount, np.nan)
    adv = np.mean(usable_amount[:, :-1], axis=1)
    ratio = divide(usable_amount[:, -1], adv)
    median = np.median(usable_amount[:, 1:], axis=1)
    c_white = 100 * (divide(c[:, -1], arrays["zge_white_line"][:, -1]) - 1)
    j = np.where(bar[:, -1], arrays["j"][:, -1], np.nan)
    vol20 = np.std(100 * (divide(c[:, :-1], arrays["pre_close"][:, :-1]) - 1), axis=1, ddof=0)
    l50m = tri_and(admits, known_mask(median, lambda a: a >= LIQUIDITY_CNY))
    climax = tri_or(tri_and(known_mask(runup, lambda a: a > 25), known_mask(ratio, lambda a: a > 1.2)),
                    tri_and(known_mask(c_white, lambda a: a > 15), known_mask(j, lambda a: a > 80)))
    legacy_ratio = divide(usable_amount[:, -1], np.mean(usable_amount[:, 1:], axis=1))
    return {"amount_ratio_20_act006_v4": legacy_ratio, "d_basis_close": c[:, -1],
            "d_qfq_return_5d": divide(c[:, -1], c[:, -6]) - 1, "prior_attack_runup_pp": runup, "amount_ratio_20": ratio, "close_vs_white_pp": c_white,
            "J": j, "drawdown_from_prior20_high_pp": dp, "prior20_volatility_pp": vol20, "adv20_cny": adv,
            "median_amount20_cny": median, "l50m": l50m, "hard_climax": climax,
            "advance_from_low20_pp": 100 * (divide(c[:, -1], np.min(pri_low, axis=1)) - 1)}


def admissions(codes, quotes, arrays):
    valid = valid_bars(arrays)[:, -1] & (arrays["tradeable_basic"][:, -1] == 1)
    out = np.full(len(codes), np.nan)
    for i, code in enumerate(codes):
        if code.endswith(".BJ"):
            out[i] = 0
            continue
        quote = quotes.get(code)
        if not quote:
            continue
        st = act031.special_treatment(quote.get("name"))
        if st is True:
            out[i] = 0
        elif st is False and quote.get("eligible_for_daily_gain_rank"):
            prices = [act031.positive(quote.get(k)) for k in ("open", "high", "low", "close")]
            if all(v is not None for v in prices):
                if prices[1] == prices[2]:
                    out[i] = 0
                elif valid[i]:
                    out[i] = 1
    return out


def day_aligned(arrays, codes, quotes):
    """Check the archived basis at D against the sealed official raw OHLC."""
    aligned = np.full(len(codes), False)
    for i, code in enumerate(codes):
        quote = quotes.get(code)
        if quote and quote.get("eligible_for_daily_gain_rank"):
            aligned[i] = all(rules.same_price(gates.finite(arrays[key][i, -1]), act031.positive(quote.get(key)))
                             for key in ("open", "high", "low", "close"))
    return aligned


def p515_for_day(day, codes, days, history, adjust, quotes):
    pos = days.index(day)
    window = days[pos - 20:pos + 1]
    require(len(window) == 21, "BASE20_EXCHANGE_LOOKBACK_MISSING")
    mapping, grids = {}, {}
    for key in COLUMNS:
        grids[key] = np.full((len(codes), len(window)), np.nan)
    affected = {}
    for i, code in enumerate(codes):
        item = history.get(code)
        if item is None:
            continue
        idx = item.index.get_indexer(window)
        matched = idx >= 0
        if matched.any():
            mapping[i] = True
            for key in COLUMNS:
                grids[key][i, matched] = item[key].to_numpy()[idx[matched]]
        suffix = adjust.suffix(code, day, window[0])
        if suffix is None:
            for key in (*PRICE, "vol"):
                grids[key][i] = np.nan
            continue
        if suffix:
            affected[i] = suffix
    for i, suffix in affected.items():
        for event in suffix:
            for key in PRICE:
                grids[key][i] = (grids[key][i] - float(event["b"])) / float(event["a"])
            grids["vol"][i] /= float(event["volume_a"])
    aligned = day_aligned(grids, codes, quotes)
    admit = admissions(codes, quotes, grids)
    for key in (*PRICE, "vol", "j"):
        grids[key][~aligned] = np.nan
    # A known BJ or flat/ST veto still determines L50M; missing alignment
    # cannot turn the median amount rule into a verified inclusion.
    admit[(admit == 1) & ~aligned] = np.nan
    measured = base20(grids, admit)
    for key in ("days_since_20d_vol_peak", "pullback_vol_decay_ratio"):
        measured[key] = np.full(len(codes), np.nan)
    for i, code in enumerate(codes):
        if aligned[i]:
            peak, decay = peak_decay(code, day, history.get(code), adjust)
            if peak is not None:
                measured["days_since_20d_vol_peak"][i] = peak
            if decay is not None:
                measured["pullback_vol_decay_ratio"][i] = decay
    return measured, {"reader_present_n": len(mapping), "D_raw_ohlc_aligned_n": int(aligned.sum())}


def scalar_grid(grids, index):
    row = {name: gates.finite(values[index]) for name, values in grids.items()}
    for field in ("l50m", "hard_climax"):
        if row[field] is not None:
            row[field] = bool(row[field])
    return row


def diagnostic_window(data, width):
    frame = data.iloc[-width:]
    return frame if len(frame) == width else None


def body_return(bar):
    return gates.ratio(act031.positive(bar.close), act031.positive(bar.open))


def bar_position(bar):
    width = bar.high - bar.low
    if not np.isfinite(width) or width <= 0:
        return None, None
    return (bar.close - bar.low) / width, (bar.high - max(bar.open, bar.close)) / width


def anchor_evidence(prefix, pos):
    row = prefix.iloc[pos]
    required = prefix.vol.iloc[max(0, pos - 5):pos]
    gain = body_return(row)
    vol_ratio = gates.ratio(act031.positive(row.vol), float(required.mean()) if
                           len(required) == 5 and (required > 0).all() else None)
    white_ratio = gates.ratio(act031.positive(row.close), act031.positive(row.zge_white_line))
    return gates.conjunction(gates.gte(gain, 1.03), gates.gte(vol_ratio, 1.2), gates.gte(white_ratio, 1.0)), {
        "active_anchor_body_return": gain - 1 if gain is not None else None,
        "active_anchor_prior5_volume_ratio": vol_ratio,
        "active_anchor_close_vs_white_pct": white_ratio - 1 if white_ratio is not None else None,
    }


def choose_anchor(prefix, hinted):
    i = prefix.trade_date.searchsorted(hinted) if hinted else -1
    if 0 <= i < len(prefix) and prefix.trade_date.iloc[i] == hinted:
        passed, evidence = anchor_evidence(prefix, i)
        if passed is True:
            return i, "VALID_CAUSAL_HINT", evidence
    for i in range(len(prefix) - 2, max(-1, len(prefix) - 22), -1):
        passed, evidence = anchor_evidence(prefix, i)
        if passed is True:
            return i, "LATEST_QUALIFYING_PRIOR20", evidence
    return None, "NO_OBSERVED_QUALIFYING_ANCHOR", {}


def observed_anchor_status(prefix, i, session_days):
    anchor, day = prefix.iloc[i], prefix.iloc[-1]
    low = act031.positive(anchor.low)
    observed = prefix.iloc[i:]
    closes = observed.close.iloc[1:-1]
    prior_breach = bool(closes.lt(low).any()) if low is not None else None
    expected = [d for d in session_days if anchor.trade_date <= d <= day.trade_date] if session_days else None
    full = (expected is not None and len(expected) == len(observed)
            and expected == observed.trade_date.tolist() and closes.gt(0).all() and closes.notna().all())
    if not full and prior_breach is False:
        prior_breach = None
    dclose = act031.positive(day.close)
    v04 = dclose < low if dclose is not None and low is not None else None
    return {"prior_anchor_breach": prior_breach, "V04": v04,
            "intact_anchor": gates.conjunction(gates.negation(v04), gates.negation(prior_breach)),
            "anchor_window_status": "EXACT_CONTIGUOUS_EXCHANGE_SESSIONS" if full else
                                    "OBSERVED_BARS_CALENDAR_OR_WINDOW_INCOMPLETE"}


def v02_proxy(prefix, anchor_volume, p515):
    day = prefix.iloc[-1]
    loc, wick = bar_position(day)
    current_body = body_return(day)
    vol5 = prefix.vol.iloc[-6:-1]
    prior20_high = prefix.high.iloc[-21:-1]
    pivot = float(prior20_high.max()) if len(prior20_high) == 20 and prior20_high.gt(0).all() else None
    vr5 = gates.ratio(act031.positive(day.vol), float(vol5.mean()) if len(vol5) == 5 and vol5.gt(0).all() else None)
    vr_anchor = gates.ratio(act031.positive(day.vol), anchor_volume)
    vs_pivot = gates.ratio(act031.positive(day.close), pivot)
    extension = gates.disjunction(
        gates.negation(gates.lte(p515.get("close_vs_white_pp"), 15)),
        gates.conjunction(gates.negation(gates.lte(p515.get("prior_attack_runup_pp"), 25)),
                          gates.gte(vs_pivot, .95)),
    )
    bearish = gates.negation(gates.gte(current_body, 1))
    distribution = gates.conjunction(gates.disjunction(gates.gte(wick, .35), bearish),
                                     gates.negation(gates.gte(loc, .65)), gates.gte(vr5, 1.2),
                                     gates.gte(vr_anchor, 1.0))
    breakout = gates.conjunction(gates.negation(gates.lte(current_body, 1)), gates.gte(loc, .65),
                                 gates.negation(gates.lte(vs_pivot, 1)))
    return {"V02": gates.conjunction(extension, distribution, gates.negation(breakout)),
            "v02_extension": extension, "v02_distribution": distribution, "v02_healthy_breakout": breakout,
            "d_upper_wick_range_fraction": wick, "d_close_location": loc,
            "d_prior5_volume_ratio": vr5, "d_anchor_volume_ratio": vr_anchor}


def v06_proxy(prefix, start, anchor_volume):
    unknown = len(prefix) < 5
    traces = []
    lows, highs, closes = (prefix[col].to_numpy() for col in ("low", "high", "close"))
    prev_close = np.r_[np.nan, closes[:-1]]
    tr = np.maximum.reduce((highs - lows, np.abs(highs - prev_close), np.abs(lows - prev_close)))
    volumes = prefix.vol.to_numpy()
    for i in range(max(start, len(prefix) - 5), len(prefix)):
        bar = prefix.iloc[i]
        body = body_return(bar)
        loc, _ = bar_position(bar)
        platform = volumes[max(0, i - 24):max(0, i - 4)]
        preatr = tr[max(0, i - 20):i]
        volume = act031.positive(bar.vol)
        platform_ratio = gates.ratio(volume, float(platform.mean()) if len(platform) == 20 and (platform > 0).all() else None)
        anchor_ratio = gates.ratio(volume, anchor_volume)
        atr_ratio = gates.ratio(gates.finite(tr[i]),
                                float(preatr.mean()) if len(preatr) == 20 and np.isfinite(preatr).all() else None)
        supply = gates.conjunction(gates.lte(body, .97), gates.lte(loc, .35),
                                   gates.gte(platform_ratio, 1.2), gates.gte(anchor_ratio, 1),
                                   gates.gte(atr_ratio, 1.2))
        if supply is None:
            unknown = True
        if supply is not True:
            continue
        later_closes = closes[i + 1:]
        reclaim = bool(np.any(later_closes >= bar.open)) if np.isfinite(later_closes).all() else None
        traces.append((reclaim, {
            "v06_supply_date": bar.trade_date, "v06_supply_body_return": body - 1,
            "v06_supply_platform_vol_ratio": platform_ratio, "v06_supply_anchor_vol_ratio": anchor_ratio,
            "v06_supply_atr_ratio": atr_ratio, "v06_supply_close_location": loc,
            "v06_later_close_reclaimed": reclaim,
        }))
    for reclaim, trace in reversed(traces):
        if reclaim is False:
            return {"V06": True, **trace}
    unknown = unknown or any(reclaim is None for reclaim, _ in traces)
    return {"V06": None if unknown else False, **(traces[-1][1] if traces else {})}


def bar_window(prefix, sessions, width):
    if not sessions:
        return diagnostic_window(prefix, width)
    day = prefix.trade_date.iloc[-1]
    pos = bisect_right(sessions, day)
    days = sessions[max(0, pos - width):pos]
    if len(days) < width:
        return None
    panel = prefix.set_index("trade_date")
    if not set(days) <= set(panel.index):
        return None
    return panel.loc[days].reset_index()


def act030_features(prefix, root_date, active_date, anchor_low, anchor_mid, act030):
    cols = {"vol": "volume", "amount": "amount_cny", "zge_white_line": "white", "zge_yellow_line": "yellow"}
    working = prefix.rename(columns=cols)
    fields = [*act030.PRICE_COLUMNS, "volume", "amount_cny"]
    ready = working[fields].notna().all(axis=1) & working.volume.ge(0) & working.amount_cny.ge(0)
    ready &= working.high.ge(working[["open", "close", "low"]].max(axis=1))
    ready &= working.low.le(working[["open", "close", "high"]].min(axis=1))
    if not ready.iat[-1]:
        return None
    # Current-window features need at most 35 observations. Retain distant
    # anchor rows explicitly and leave an insufficient contiguous suffix null.
    first_bad_distance = np.flatnonzero(~ready.to_numpy()[::-1])
    n = min(35, int(first_bad_distance[0]) if len(first_bad_distance) else len(working))
    relevant = working.iloc[-n:]
    if n == 35:
        anchors = working.loc[ready & working.trade_date.isin([root_date, active_date])]
        relevant = pd.concat([anchors, relevant]).drop_duplicates("trade_date").sort_values("trade_date")
    levels = act030.Anchors(root_date or "", active_date or "", anchor_low, anchor_mid, anchor_low)
    return act030.features(relevant, prefix.trade_date.iat[-1], levels)


def pft_measure(code, day, frame, hinted, root_date, p515, adjustment, sessions, quote):
    prefix, undo = adjustment.for_window(code, day, frame)
    if prefix is None:
        return {"pft_status": "CANNOT_CONFIRM_D_ROW_OR_ADJUSTMENT", "hinted_anchor_date": hinted}
    if quote and (
        not quote.get("eligible_for_daily_gain_rank")
        or not all(rules.same_price(gates.finite(prefix.iloc[-1][key]), act031.positive(quote.get(key)))
                   for key in ("open", "high", "low", "close"))
    ):
        return {"pft_status": "CANNOT_CONFIRM_D_RAW_ALIGNMENT", "hinted_anchor_date": hinted, "deduced_post_d_events_n": undo}
    if not valid_bars({key: prefix[key].to_numpy() for key in COLUMNS})[-1]:
        return {"pft_status": "CANNOT_CONFIRM_INVALID_D_BAR", "hinted_anchor_date": hinted}
    # Exact recent replay flags require complete exchange windows. Diagnostics
    # for historical external keys describe the available observed daily bars.
    anchor_idx, source, geom = choose_anchor(prefix, hinted)
    active_date = prefix.trade_date.iloc[anchor_idx] if anchor_idx is not None else None
    anchor = prefix.iloc[anchor_idx] if anchor_idx is not None else None
    low = act031.positive(anchor.low) if anchor is not None else None
    mid = act031.positive((anchor.open + anchor.close) / 2) if anchor is not None else None
    volume = act031.positive(anchor.vol) if anchor is not None else None
    values = act030_features(prefix, root_date, active_date, low, mid, adjustment.act030) or {}
    statuses = observed_anchor_status(prefix, anchor_idx, sessions) if anchor_idx is not None else {}
    distribution_window = bar_window(prefix, sessions, 21)
    v02 = v02_proxy(distribution_window, volume, p515) if distribution_window is not None else {}
    recent = bar_window(prefix, sessions, 30)
    v06 = {}
    if recent is not None and active_date is not None:
        v06 = v06_proxy(recent, recent.trade_date.searchsorted(active_date), volume)
    return {
        **values, **geom, **statuses, **v02, **v06,
        "pft_status": "D_RAW_ALIGNED" if quote else "D_BASIS_FROM_ARCHIVED_LEDGER_RAW_D_UNVERIFIED",
        "hinted_anchor_date": hinted, "active_anchor_source": source, "active_anchor_date": active_date,
        "active_anchor_low": low, "active_anchor_mid": mid, "root_anchor_date": root_date,
        "anchor_age_sessions": (sum(active_date < d <= day for d in sessions) if active_date and sessions else None),
        "v01_v03_v05_status": "SPEC_REQUIRES_CONTEXT", "deduced_post_d_events_n": undo,
    }


def external_p515(code, prefix, sessions, quote):
    """Produce strict BASE20 only where the exchange schedule is verifiable."""
    if prefix is None:
        return {}
    strict = bar_window(prefix, sessions, 21) if sessions else None
    if strict is None:
        return {"l50m": False} if code.endswith(".BJ") else {}
    arrays = {key: strict[key].to_numpy()[None, :] for key in COLUMNS}
    quotes = {code: quote} if quote is not None else {}
    if quote is not None and not day_aligned(arrays, [code], quotes)[0]:
        return {"l50m": False} if code.endswith(".BJ") else {}
    return scalar_grid(base20(arrays, admissions([code], quotes, arrays)), 0)


def external_observed_proxy_inputs(prefix, actual_p515):
    """Only V02 diagnostic bypasses strict historical calendar for observed bars."""
    if prefix is None or actual_p515.get("prior_attack_runup_pp") is not None:
        return actual_p515
    observed = diagnostic_window(prefix, 21)
    if observed is None:
        return actual_p515
    arrays = {key: observed[key].to_numpy()[None, :] for key in COLUMNS}
    computed = scalar_grid(base20(arrays, np.full(1, np.nan)), 0)
    return actual_p515 | {key: computed[key] for key in ("prior_attack_runup_pp", "close_vs_white_pp")}


def peak_decay(code, day, history, adjustment):
    """Use 20 observed valid bars and the most recent tied maximum."""
    if history is None or day not in history.index:
        return None, None
    current = history.index.searchsorted(day, side="right")
    data = history.iloc[:current]
    suffix = adjustment.suffix(code, day, str(data.index[0]))
    if suffix is None:
        return None, None
    # A post-D volume transform scales the whole prefix by one positive
    # constant. It changes neither the choice of peak nor the decay ratio.
    values = data["vol"].to_numpy()
    valid = data["_valid_bar"].to_numpy(dtype=bool)
    if not valid[-1]:
        return None, None
    recent = values[valid][-20:]
    if len(recent) < 20:
        return None, None
    age = int(np.argmax(recent[::-1]))
    return age, float(recent[-age:].mean() / recent[-age-1]) if age else None
