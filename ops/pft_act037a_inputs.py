"""ACT037A frozen input and model-free D-stage evidence."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import prod
from pathlib import Path
import resource
from time import perf_counter

import numpy as np
import pandas as pd

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as g
from ops import pft_act033a_replay as a33
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36i
from ops import pft_act036a_replay as a36

ROOT = a35.ROOT
OUTPUT = ROOT / "pft_act037a_timing_20261124"
FRIDAY, MONDAY = "20261120", "20261123"
ACT036_SEAL = {"path": str(a36.OUT / "SELECTION_SEAL.json"),
               "sha256": "ca8325d2dab6e564e571df64e6730db74e070dde162890175021b8a4871a1435"}
ACT036_SUMMARY_EXPECTED = {"path": str(a36.OUT / "SUMMARY.json"),
                         "sha256": "56cdafbc5d680f3b1c3263c585c0eaaa56c0375efb8dccfc64bad31518f6ac0a"}
ACT036_DELIVERY = {"path": str(a36.OUT / "delivery" / a36.CSV_NAME),
                   "sha256": "d5dc34657dbce08ba23b9e559c8ea6d952c859c20376ee93c65652fcd1ddb004"}
ACT013 = {"path": str(ROOT / "pft_act013_market_risk_20261123/market/MARKET_REGIME_DAILY_2022_2026.csv"),
          "sha256": "343c31cf59f97a39ee4a4649e8d91976c44516735e379a604f07d8f6f0d6f390"}
WARMUP = ("20260826", "20260827", "20260828", "20260831")
WINDOW = a36i.FORECAST_HISTORY
STAGE_COLUMNS = (*a31.old.INPUTS[3:], "pre_close", "amount", "tradeable_basic", "bars_since_list")
SCHEMA = "pft.act037a.timing_and_friday.v1"
EXT3 = "EXT3"
BASELINE = "A1_BASE"
RUN_START = "RUN_STARTED.json"
SEAL_NAME = "SELECTION_SEAL.json"


def require(condition, reason):
    if not condition:
        raise a31.ContractError(f"ACT037A_{reason}")


@dataclass
class Sources:
    prior: a35.SealedInputs
    oot: list
    dev: list
    calendar: list
    checkpoints: dict
    checkpoint_refs: dict
    quotes: dict
    breadth: dict
    breadth_identity: dict

    @property
    def days(self):
        return self.oot + self.dev


def act013_breadth(days):
    names = ("cw_share", "cy_share", "wy_share")
    frame = pd.read_csv(a33.checked(ACT013), usecols=("D", *names), dtype={"D": str})
    require(not frame.D.duplicated().any(), "ACT013_BREADTH_DUPLICATE_DATE")
    # Under the exact source, validate the supplied
    # 2022–25 calibration records and never derive the operative threshold.
    historic = frame.loc[frame.D.between("20220101", "20251231"), list(names)].dropna()
    values = historic.mean(axis=1).to_numpy()
    quantiles = np.quantile(values, [1 / 3, 2 / 3])
    wy_quantiles = np.quantile(historic["wy_share"].to_numpy(), [1 / 3, 2 / 3])
    require(len(values) == 969 and list(np.round(quantiles, 4)) == [.3619, .5414],
            "ACT013_COMPOSITE_QUANTILE_IDENTITY_DRIFT")
    projected = {}
    for item in frame.loc[frame.D.isin(days)].to_dict("records"):
        row = {name: g.finite(item[name]) for name in names}
        composite = sum(row.values()) / 3 if all(value is not None for value in row.values()) else None
        projected[item["D"]] = row | {"composite_breadth_share": composite}
    return projected, {"reference": ACT013, "formula": "arithmetic mean of cw_share, cy_share, wy_share",
                       "training_cut_dates": ["20220101", "20251231"], "training_n": len(values),
                       "composite_q33_q67": quantiles.tolist(), "wy_standalone_q33_q67": wy_quantiles.tolist(),
                       "frozen_operating_threshold": .3619}


def load_sources():
    sealed = a31.read_ref(ACT036_SEAL)
    prior = a35.load_signal_inputs(ROOT)
    calendar = f35.exchange_days(prior.calendar.schedule)
    oot, dev = sealed["oot_dates"], sealed["dev_dates"]
    days = oot + dev
    require(len(oot) == 32 and len(dev) == 21 and dev == prior.signal_dates
            and days == calendar[calendar.index("20260901"):calendar.index(FRIDAY) + 1]
            and sealed["days"] == [*days, MONDAY] and sealed["cutoff"] == MONDAY
            and sealed["observations_opened_before_seal"] is False, "ACT036_SEALED_SCOPE_DRIFT")
    warm_start = calendar.index(oot[0])
    require(list(WARMUP) == calendar[warm_start - 4:warm_start], "T3_WARMUP_CALENDAR_DRIFT")
    references = {day: sealed["checkpoints"][day] for day in days}
    records = {}
    for day, reference in references.items():
        record, verified_ref = a36.read_checkpoint(Path(reference["path"]), day, sealed["run_started"]["sha256"])
        require(reference == verified_ref, f"ACT036_D_CHECKPOINT_SHA_DRIFT:{day}")
        records[day] = record
    quotes = dict(prior.observed)
    for day in (*WARMUP, *oot):
        day_input = prior.inputs["days"].get(day, {})
        day_quotes, official_ref = a31.day_quotes(day, day_input)
        quotes[day] = day_quotes or {}, official_ref
    breadth, breadth_id = act013_breadth(days)
    return Sources(prior, oot, dev, calendar, records, references, quotes, breadth, breadth_id)


def bound(sources, asof):
    # Reuse the ACT036 binding without opening Monday observations during signal
    # calculations. The adapter needs only the previous input contract.
    proxy = a36i.Sources(sources.prior, {}, sources.oot, sources.dev, sources.calendar, {}, {})
    return a36i.bind_reader(proxy, asof)


def archived_stage_read(sources, reader, pending):
    first, last = min(pending), max(pending)
    lo, hi = f35.earlier(first, WINDOW), last
    data = a36i.read_history(reader, lo, hi, columns=STAGE_COLUMNS)
    n = data.ts_code.nunique()
    require(n > 0 and len(data) <= n * 345, "READER_SCOPE_TOO_LARGE")
    return data, {"reader_bounds": [lo, hi], "symbols": n, "rows": len(data),
                  "projected_memory_bytes": int(data.memory_usage(deep=True, index=True).sum())}


def valid_for_stage(frame):
    valid = frame[list(a31.old.INPUTS[3:])].notna().all(axis=1)
    valid &= np.isfinite(frame[list(a31.old.INPUTS[3:])]).all(axis=1)
    valid &= frame[list(a31.old.INPUTS[3:])].gt(0).all(axis=1)
    valid &= frame.high.ge(frame[["open", "close"]].max(axis=1))
    valid &= frame.low.le(frame[["open", "close"]].min(axis=1))
    return valid


def damaged_evidence(frame, day, eligible):
    """Return tri-state DAMAGED from the same pre-HGB shape and readiness."""
    subset = frame.loc[frame.ts_code.isin(eligible), list(a31.old.INPUTS)]
    require(subset.trade_date.le(day).all(), "T1_POST_D_CONTEXT")
    if subset.empty:
        return {}
    tail = subset.groupby("ts_code", sort=False).tail(65)
    checks = tail.assign(_valid=valid_for_stage(tail)).groupby("ts_code", sort=False)["_valid"].agg(["size", "all"])
    valid = set(checks.index[checks["size"].eq(65) & checks["all"]])
    if not valid:
        return {}
    current = a31.old.causal_shapes(subset.loc[subset.ts_code.isin(valid)], start=day, end=day)
    current = current.loc[current.feature_ready.eq(True)]
    results = {}
    for row in current.itertuples(index=False):
        # This is ACT021 observable_stage's exact precedence for DAMAGED. The
        # anchor ledger only informs later branches and does not change it.
        results[row.ts_code] = bool(row.active_damage and not 0 <= row.repair_age < 2)
    return results


def stage_stats(day, archive, basis, official, saved, frozen_audit, earliest_dev, original_checkpoint):
    lo = f35.earlier(day, WINDOW)
    prefix, restore = basis.prefix(archive, day, lo)
    quotes, authority = a36i.quotes_for_day(archive, day, basis, official)
    admitted, admission = a36i.historical_admission(prefix, day, quotes, authority)
    if saved is None:
        expected = frozen_audit["eligible_n"]
        require(len(admitted) == expected, f"ACT036_OOT_ADMISSION_COUNT_DRIFT:{day}")
        eligible = set(admitted)
        confirmed = frozen_audit["final_state"].get("CONFIRMED_S", 0)
        known_stages = {}
        signal_scope_status = "ACT036_OOT_RECONSTRUCTED_EXACT_COUNT"
    else:
        eligible = set(saved.ts_code)
        if day == earliest_dev:
            # ACT033A projection includes every confirmed final state even
            # though the complete stock-level state output was not retained.
            confirmed = frozen_audit["confirmed_exact_from_projection"]
            signal_scope_status = "ACT033A_1023_FROZEN_ELIGIBLE_SYMBOLS"
            known_stages = {row.ts_code: row.stage == "DAMAGED" for row in saved.itertuples(index=False)
                            if pd.notna(row.stage) and row.stage != "UNKNOWN"}
        else:
            confirmed = int(saved.final_state.eq("CONFIRMED_S").sum())
            detailed = a35.source_frame(original_checkpoint, ["ts_code", "stage", "prediction_status"])
            require(set(detailed.ts_code) == eligible, f"ACT031_DEV_STAGE_SCOPE_DRIFT:{day}")
            known_stages = {row.ts_code: row.stage == "DAMAGED" for row in detailed.itertuples(index=False)
                            if pd.notna(row.stage) and row.stage != "UNKNOWN"}
            signal_scope_status = "ACT031_FROZEN_ELIGIBLE_SYMBOLS"
    recovered = damaged_evidence(prefix, day, eligible)
    common = known_stages.keys() & recovered.keys()
    conflicts = sorted(code for code in common if recovered[code] != known_stages[code])
    if day == FRIDAY:
        require(len(common) >= 3 and not conflicts, "FRIDAY_KNOWN_STAGE_CANARY_PARITY")
    # Keep the original stages whenever preserved. Observed disagreement is
    # surfaced separately from newly recovered, archive-derived rows.
    combined = recovered | known_stages
    counts = Counter(combined.values())
    n, damaged, missing = len(eligible), counts[True], len(eligible - combined.keys())
    return {
        "eligible_n": n, "confirmed_n": confirmed, "stage_known_n": len(combined), "stage_unknown_n": missing,
        "damaged_n": damaged, "damaged_share_all_eligible_min": damaged / n if n else None,
        "damaged_share_all_eligible_max": (damaged + missing) / n if n else None,
        "damaged_share_known_stage": damaged / len(combined) if combined else None,
        "frozen_known_stage_n": len(known_stages), "frozen_damaged_n": sum(known_stages.values()),
        "recovered_only_stage_n": len(combined.keys() - known_stages.keys()),
        "recovered_exact_match_n": len(common) - len(conflicts), "recovered_known_conflicts": conflicts,
        "signal_scope_status": signal_scope_status, "quote_source": authority, "archive_admitted_n": len(admitted),
        "admission": admission, "projection": restore, "chart_end": day,
        "maturity": "STRICT_D_PREFIX_400_DAYS_WITH_65_VALID_BARS_AND_ACT020_READY",
        "historical_pit": "CANNOT_CONFIRM",
    }


def market_close_day(data, day, basis, official, official_ref):
    current = data.loc[data.trade_date.eq(day)]
    quotes, identity = a36i.quotes_for_day(current, day, basis, official)
    return a33.market_day(quotes) | {"source": identity, "official_ref": official_ref, "trade_date": day}


def market_window(day, calendar, closes):
    i = calendar.index(day)
    dates = calendar[i - 4:i + 1]
    missing = [date for date in dates if closes[date]["equal_weight_return"] is None]
    total = None if missing else prod(1 + closes[d]["equal_weight_return"] for d in dates) - 1
    kind = ("CANNOT_CONFIRM" if missing else "OFFICIAL_ONLY" if
            all(closes[d]["source"] == a36i.OFFICIAL for d in dates) else "INCLUDES_V4_REBASED_PANEL_DIAGNOSTIC")
    return {"trailing_5_return": total, "source": kind, "dates": dates, "missing_dates": missing}
