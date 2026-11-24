"""Frozen-source Reader binding and causal ACT036A input projection."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_replay as act033
from ops import pft_act034a_replay as act034
from ops import pft_act034a_rules as r34
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as r35


OOT_FIRST, OOT_LAST = "20260901", "20261022"
LATEST = "20261123"
CUTOFF = LATEST
MODEL_ROOT = r35.ROOT / "pft_act023_s_v3_20261123" / "run"
FORECAST_HISTORY = 400
HISTORY_COLUMNS = (*f35.COLUMNS, "bars_since_list")
OFFICIAL = "D_OFFICIAL_TDX_G4DAY"
PROXY = "V4_REBASED_PANEL_STANDARD_BOARD_PROXY"
RAW_DIAGNOSTIC = "V4_REBASED_PANEL_ALL_A_DIAGNOSTIC"
EXACT_ADMISSION = "D_OFFICIAL_DATED_NON_ST"
UNKNOWN_ST = "D_ST_UNKNOWN_RESEARCH_ONLY"
CENTS = Decimal(".01")


def require(predicate, problem):
    if not predicate:
        raise act031.ContractError(f"ACT036A_{problem}")


@dataclass
class Sources:
    previous: r35.SealedInputs
    official_days: dict
    oot: list
    dev: list
    calendar: list
    model_receipt: dict
    model_expected: dict


def load_sources():
    previous = r35.load_signal_inputs(r35.ROOT)
    calendar = f35.exchange_days(previous.calendar.schedule)
    oot = [day for day in calendar if OOT_FIRST <= day <= OOT_LAST]
    dev = previous.signal_dates
    require(len(oot) == 32 and len(dev) == 21
            and calendar[calendar.index(oot[0]):calendar.index(CUTOFF) + 1] == [*oot, *dev, CUTOFF]
            and set([*oot, *dev, CUTOFF]) <= set(previous.inputs["days"]), "FROZEN_SIGNAL_CALENDAR_DRIFT")
    official = dict(previous.observed)
    for day in (*oot, LATEST):
        quotes, ref = act031.day_quotes(day, previous.inputs["days"][day])
        official[day] = (quotes or {}, ref)
    seal031 = act031.read_ref(previous.references["act031"])
    model_receipt = seal031["plan"]
    model_expected = act031.read_ref(model_receipt)["model"]
    require(model_expected["cutoff"] == "20260831" and len(model_expected["feature_order"]) == 43,
            "ACT031_MODEL_FREEZE_DRIFT")
    return Sources(previous, official, oot, dev, calendar, model_receipt, model_expected)


def load_model(expected, model_root=MODEL_ROOT):
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1):
        models, identity = act031.prior.load_frozen(model_root)
    require(identity == expected, "ACT031_MODEL_IDENTITY_DRIFT")
    return models


@dataclass
class Reader:
    binding: tuple
    symbols: dict
    asof: str
    identity: dict


def bind_reader(sources, day):
    source = sources.previous.inputs["days"][day]
    if day == f35.ASOF:
        bound, symbols, identity = f35.bind(source)
        return Reader(bound, symbols, day, identity)
    require(day == LATEST and source["panel_role"] == "backtest", "UNKNOWN_READER_ROLE")
    bound = act031.bind_panel(day, source)
    producer = act031.read_ref(source["producer_ref"])
    ref = producer["adjustment_snapshot"]
    snapshot = act031.read_ref(ref)
    require(ref["sha256"] == producer["snapshot_file_sha256"]
            and act034.qfq.canonical_sha(snapshot) == producer["input_sha256"]
            and str(snapshot["asof_date"]) == str(snapshot["coverage_end_date"]) == day
            and (snapshot["price_basis"], snapshot["volume_basis"], snapshot["amount_basis"])
            == ("QFQ_ASOF", "QFQ_EVENT_VOLUME", "RAW_TURNOVER"), "LATEST_ADJUSTMENT_AUTHORITY_DRIFT")
    return Reader(bound, snapshot["symbols"], day, {"backtest": source, "adjustment": ref,
                  "historical_pit": "CANNOT_CONFIRM", "snapshot_historical_pit": snapshot.get("historical_PIT")})


def read_history(bound, lo, hi, codes=None, columns=HISTORY_COLUMNS):
    require(lo <= hi <= bound.asof, "READER_DATE_SCOPE")
    frame = act031.read_panel(bound.binding, lo, hi, columns, codes=codes, optional=("bars_since_list",))
    if codes is None:
        family = {code for code in frame.ts_code.unique() if act031.a_share_instrument_rejection(code) is None}
        frame = frame.loc[frame.ts_code.isin(family)].reset_index(drop=True)
    return frame


def finance_history(bound, lo, day, codes):
    return act033.read_finance(bound.binding, lo, day, codes)


class Basis:
    """Read-only affine inverse matching ACT030/035's order and volume handling."""

    def __init__(self, reader):
        self.reader = reader
        self.act030 = f35.load_act030()

    @lru_cache(maxsize=None)
    def events(self, code):
        item = self.reader.symbols.get(code)
        if not item or item.get("event_coverage_complete") is not True or "events" not in item:
            return None
        events = self.act030.events_after(item["events"], self.reader.asof, self.reader.asof)
        require(not events, "ADJUSTMENT_POST_ASOF_EVENT")
        first = str(item["history_start_date"])
        require(all(first < str(event["ex_date"]) for event in item["events"]),
                f"ADJUSTMENT_EVENT_PRECEDES_HISTORY:{code}")
        return first, tuple(item["events"])

    @lru_cache(maxsize=100_000)
    def inverse(self, code, day):
        timeline = self.events(code)
        if timeline is None or timeline[0] > day:
            return None
        suffix = [event for event in reversed(timeline[1]) if str(event["ex_date"]) > day]
        a = v = 1.
        b = 0.
        for event in suffix:
            factor = float(event["a"])
            a /= factor
            b = (b - float(event["b"])) / factor
            v /= float(event["volume_a"])
        return a, b, v

    def prefix(self, frame, day, lo):
        require(day <= self.reader.asof and lo <= day, "INVERSE_D_SCOPE")
        prefix = frame.loc[frame.trade_date.between(lo, day)].copy()
        present = prefix.ts_code.unique()
        identity = {code: self.inverse(code, day) for code in present}
        keep = {code for code, factors in identity.items() if factors is not None}
        prefix = prefix.loc[prefix.ts_code.isin(keep)]
        for code, first in {c: self.events(c)[0] for c in keep}.items():
            # All rows normally satisfy ledger start. A row predating the
            # authority cannot be admitted even if later history is covered.
            if first > lo:
                identity[code] = (*identity[code], first)
        first_map = {code: factors[3] for code, factors in identity.items() if factors and len(factors) == 4}
        if first_map:
            first_allowed = prefix.ts_code.map(first_map).fillna(lo)
            prefix = prefix.loc[prefix.trade_date.ge(first_allowed)].copy()
        changed = {code: factors[:3] for code, factors in identity.items()
                   if factors is not None and factors[:3] != (1., 0., 1.)}
        if changed:
            affected = prefix.ts_code.isin(changed)
            data = prefix.loc[affected, "ts_code"]
            factors = np.asarray([changed[code] for code in data])
            prices = [name for name in f35.PRICE if name in prefix]
            prefix.loc[affected, prices] = prefix.loc[affected, prices].to_numpy() * factors[:, :1] + factors[:, 1:2]
            prefix.loc[affected, "vol"] *= factors[:, 2]
        require(prefix.trade_date.le(day).all(), "POST_D_IN_MODEL_PREFIX")
        return prefix, {"unknown_adjustment_symbols_n": len(present) - len(keep),
                        "post_d_rebased_symbols_n": len(changed), "reader_prefix_rows_n": len(prefix)}

    def raw_quote(self, code, day, archived):
        factors = self.inverse(code, day)
        if factors is None:
            return None
        a, b, v = factors
        names = ("open", "high", "low", "close")
        values = {name: to_cent(archived.get(name), a, b) for name in (*names, "pre_close")}
        amount = act031.positive(archived.get("amount"))
        vol = act031.positive(archived.get("vol"))
        if archived.get("tradeable_basic") != 1 or None in values.values() or amount is None or vol is None:
            return None
        o, h, low, c = (values[name] for name in names)
        previous = values.pop("pre_close")
        if not low <= min(o, c) <= max(o, c) <= h:
            return None
        return {**values, "symbol": code, "name": None, "prev_close": previous, "amount_cny": amount,
                "volume_shares": vol * v, "eligible_for_daily_gain_rank": True, "zero_volume": False,
                "change_pct": 100 * (c / previous - 1), "quote_evidence": PROXY,
                "dated_st": None, "source_date": day,
                "prev_close_source": "REBASED_QFQ_PRE_CLOSE_NOT_OFFICIAL"}


def to_cent(value, a=1., b=0.):
    value = act031.prior.finite(value)
    if value is None:
        return None
    rebased = value * a + b
    rounded = float(Decimal(str(rebased)).quantize(CENTS, rounding=ROUND_HALF_UP))
    # Decimal-cent raw OHLC must reproduce the dated basis within native
    # half-cent tolerance; the theoretical pre-close remains a flagged proxy.
    return rounded if rounded > 0 and r34.same_price(rounded, rebased) else None


def quotes_for_day(frame, day, basis, official):
    if official:
        return {code: {**quote, "quote_evidence": OFFICIAL, "dated_st": act031.special_treatment(quote.get("name"))}
                for code, quote in official.items()}, OFFICIAL
    observed = {}
    for record in frame.loc[frame.trade_date.eq(day)].to_dict("records"):
        code = record["ts_code"]
        row = basis.raw_quote(code, day, record)
        if row is not None:
            observed[code] = row
    return observed, PROXY


def historical_admission(prefix, day, quotes, authority):
    exact = prefix.loc[prefix.trade_date.eq(day)]
    bar_counts = {row.ts_code: int(row.bars_since_list) for row in exact.itertuples(index=False)
                  if act031.positive(row.bars_since_list) is not None}
    uncounted = set(exact.ts_code) - set(bar_counts)
    if uncounted:
        bar_counts.update(prefix.loc[prefix.ts_code.isin(uncounted)].groupby("ts_code").size().to_dict())
    if authority == OFFICIAL:
        admitted, counts = act031.select_eligible(exact, quotes, bar_counts)
        for entry in admitted.values():
            entry["D_admission"] = EXACT_ADMISSION
        return admitted, counts
    admitted, counts = {}, Counter()
    for row in exact.itertuples(index=False):
        code, quote = row.ts_code, quotes.get(row.ts_code)
        if quote is None or row.tradeable_basic != 1:
            counts["D_NONTRADABLE_OR_INVALID"] += 1
        elif bar_counts.get(code, 0) < 65:
            counts["D_LT_65_K"] += 1
        elif quote["dated_st"] is True:
            counts["D_ST"] += 1
        else:
            admitted[code] = {"name": quote["name"], "bars_observed": bar_counts[code],
                              "white": act031.prior.finite(row.zge_white_line),
                              "yellow": act031.prior.finite(row.zge_yellow_line),
                              "D_admission": UNKNOWN_ST if quote["dated_st"] is None else EXACT_ADMISSION}
            counts["ELIGIBLE"] += 1
            counts[admitted[code]["D_admission"]] += 1
    return admitted, dict(counts)


CAPITAL_COMMIT = "98e4ec8ee255c5b23400a8523e39e66d10be03c4"
CAPITAL_BLOB = "b89e76522899c10161ac74507106d47c1edce6f0"
CAPITAL_OWNER_SHA = "a05f2f93d2920ec03a1f080367e78d9815c0e960a7535e585af43a4e0f6f58c0"
CAPITAL_TABLE_SHA = "0ace81c96f3c30ed1c75911d4692b46f59078bf0b6d6a3e0a37dc0b0f006fe90"
CAPITAL_SOURCE = "V4_GBBQ_DATED_EVENT_RECONSTRUCTED_NOT_HISTORICAL_PIT"


def capital_projection(reader, asof):
    import pyarrow.parquet as pq

    require(reader.asof == f35.ASOF and asof <= reader.asof, "GBBQ_ASOF_SCOPE")
    ref = act031.read_ref(reader.identity["backtest"]["producer_ref"])["turnover_input"]["binding"]["gbbq"]
    derived = ref["derived_parquet"]
    require(derived["sha256"] == CAPITAL_TABLE_SHA, "GBBQ_DERIVED_SHA_DRIFT")
    source_path = act033.checked(derived)
    frame = pq.read_table(source_path, filters=[("datetime", "<=", int(asof))]).to_pandas()
    require(frame.datetime.le(int(asof)).all(), "GBBQ_POST_SCOPE_IN_PROJECTION")
    return frame, {"table": derived, "owner_commit": CAPITAL_COMMIT, "owner_blob": CAPITAL_BLOB,
                   "owner_sha256": CAPITAL_OWNER_SHA, "rows_projected": len(frame), "max_date": asof,
                   "source_provenance": CAPITAL_SOURCE, "historical_PIT": "CANNOT_CONFIRM"}


@lru_cache(maxsize=1)
def capital_owner():
    import hashlib
    import subprocess
    import sys
    from types import ModuleType

    owned = "ops/research_panel_turnover.py"
    version = f"{CAPITAL_COMMIT}:{owned}"
    repo = Path(__file__).resolve().parents[1]
    blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse", version], text=True).strip()
    payload = subprocess.check_output(["git", "-C", str(repo), "show", version])
    require(blob == CAPITAL_BLOB and hashlib.sha256(payload).hexdigest() == CAPITAL_OWNER_SHA,
            "GBBQ_OWNER_SOURCE_DRIFT")
    name = "_pft_act036a_pinned_capital_owner"
    module = ModuleType(name)
    sys.modules[name] = module
    exec(compile(payload, version, "exec"), module.__dict__)
    return module.CapitalIndex


def recover_capital(day, rows, quotes, table):
    recover = {code for code, row in rows.items() if row.get("final_state") in {"CONFIRMED_S", "UNKNOWN_BORDERLINE"}
               and (code.startswith("60") and code.endswith(".SH") or code.startswith("00") and code.endswith(".SZ"))
               and act031.positive(row.get("float_mv_d_cny")) is None and quotes.get(code)}
    raw_codes = {code[:6] for code in recover}
    if not raw_codes:
        return rows, {}
    date_n = int(day)
    scoped = table.loc[table.datetime.le(date_n) & table.code.astype(str).str.zfill(6).isin(raw_codes)]
    require(scoped.datetime.le(date_n).all(), "GBBQ_POST_D_IN_INDEX")
    index = capital_owner().from_frame(scoped, date_n)
    updated, counts = dict(rows), Counter()
    for code in sorted(recover):
        row, quote = rows[code], quotes.get(code)
        if code[:6] not in raw_codes or act031.positive(row.get("float_mv_d_cny")) is not None or not quote:
            continue
        values, why, dates = index.resolve(code, [date_n])
        value, reason, at = act031.positive(values[0]), str(why[0]), int(dates[0])
        require(at <= date_n, f"GBBQ_EVENT_AFTER_D:{code}")
        counts[reason] += 1
        fields = {"float_cap_status": reason, "float_cap_event_date": str(at) if at > 0 else None}
        close = act031.positive(quote.get("close"))
        if reason == "GBBQ_DATED_SNAPSHOT" and value is not None and close is not None:
            fields |= {"float_mv_d_cny": value * 10_000 * close, "float_cap_source": CAPITAL_SOURCE}
        updated[code] = row | fields
    return updated, dict(counts)
