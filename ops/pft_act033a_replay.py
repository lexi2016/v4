"""ACT-033A research-only causal replay with a sealed signal/outcome boundary."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
from math import prod
from statistics import mean
import sys
from tempfile import TemporaryDirectory

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import pandas as pd

from contracts import trading_calendar
from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates

SCHEMA = "pft_act033a_replay.v1"
CUTOFF, TRAINING_END = "20261123", "20260831"
SIGNAL_COUNT, RECENT_COUNT = 60, 20
FIT_CALLS = {"S": 0, "B": 0, "tuning": 0, "MR": 0}
ContractError = act031.ContractError
OVERLAY = ("open", "high", "low", "close", "vol", "j")
FINANCE_COLUMNS = ("turnover_rate_pct", "turnover_rate_status",
                   "turnover_rate_volume_source", "turnover_rate_denominator_10k")
ALLOWED_TURNOVER = {"GBBQ_DATED_SNAPSHOT"}
SIGNAL_POLICY = {
    "base": "Original ACT031 eligibility and CONFIRMED_S",
    "A0": "Main-board pullback/rebuild, projected p >= .85, calendar anchor age >= 8, 0 < cushion <= .10, age-desc/p-desc/symbol-asc top 5",
    "A1": "A0 full eligible pool + POST_REPAIR + two volume alternatives + two price alternatives, ranked by A0 order; >120 total same-D baseline confirmed top 3 otherwise top 5",
    "B1_structural": "Main-board POST_REPAIR CONFIRMED_S p >= .85, calendar anchor age >= 8, .05 < cushion <= .20; UNION main-board exact RAW_HEAD_DECISION_CONTRADICTION UNKNOWN",
    "B1": "B1 structural pool + D-only activity/price/liquidity filters, score = D/D-1 QFQ volume ratio * projected p; cap 8 then execute with +5% gap ceiling",
    "C1": "CANNOT_CONFIRM_P5_15_NUMERIC_POLICY; eligible arms A1 and B1 preserved",
    "a1_j_defense": "D QFQ low at or above both D W and Y",
    "rolling": "D-inclusive five/ten-session QFQ volume and 20-session PIT raw turnover, exact exchange sessions; 5-session QFQ close change",
    "finance_source": gates.FINANCE_SOURCE,
}


def checked(reference):
    return act031.review.checked_file(reference["path"], reference["sha256"])


def previous_days(schedule, last, count):
    days = [last]
    for _ in range(count):
        days.append(trading_calendar.previous_session(schedule, days[-1], market="a_share"))
    return days[::-1]


def load_inputs(path):
    input_ref = act031.ref(path)
    inputs = act031.read_ref(input_ref)
    sessions = act031.act028.ExchangeSessions()
    days = previous_days(sessions.schedule, CUTOFF, SIGNAL_COUNT)
    if (inputs.get("cutoff") != CUTOFF or inputs.get("signal_dates") != days[:-1]
            or inputs.get("observation_dates") != days or set(inputs.get("days", {})) != set(days)):
        raise ContractError("ACT033A_FROZEN_WINDOW_OR_CALENDAR_MISMATCH")
    required = {"inputs", "signal_seal", "outcome_receipt"}
    if set(inputs.get("prior_act031", {})) != required:
        raise ContractError("ACT033A_PRIOR_BINDING_REQUIRES_INPUTS_SIGNAL_SEAL_AND_OUTCOME_RECEIPT")
    return inputs, input_ref, sessions


def prior_signals(inputs):
    references = inputs["prior_act031"]
    prior_input, prior_sessions = act031.load_inputs(checked(references["inputs"]))
    recent = inputs["signal_dates"][-RECENT_COUNT:]
    if (prior_input["signal_dates"] != recent
            or any(prior_input["days"][day] != inputs["days"][day] for day in (*recent, CUTOFF))):
        raise ContractError("ACT033A_ACT031_PRIOR_SOURCE_IDENTITY_DRIFT")
    prior_seal = act031.load_seal(prior_input, references["inputs"], checked(references["signal_seal"]))
    if prior_seal["evaluable_days"] != recent or prior_seal.get("observations_opened_in_signal_phase") is not False:
        raise ContractError("ACT033A_ACT031_PRIOR_SIGNAL_COVERAGE_OR_CAUSALITY")
    model = act031.read_ref(prior_seal["plan"])["model"]
    if model.get("cutoff") != TRAINING_END:
        raise ContractError("ACT033A_PRIOR_TRAINING_CUTOFF_CHANGED")
    return prior_seal, model, prior_sessions


def read_finance(bound, start, day, scope):
    """PIT-only values; older static finance carried by the panel is excluded."""
    from ops.research_panel_logical import parquet, stamp

    panel, expected_stamp = bound
    if stamp(panel) != expected_stamp:
        raise ContractError("ACT033A_FINANCE_PANEL_MOVED_BEFORE_READ")
    schema = parquet.read_schema(panel)
    fields = ("ts_code", "trade_date", *FINANCE_COLUMNS)
    if not set(fields) <= set(schema.names):
        return pd.DataFrame(columns=["ts_code", "trade_date", "turnover_rate_pct", "float_share_10k"])
    day_value = act031.v12._arrow_date_value
    frame = parquet.read_table(panel, columns=list(fields), filters=[
        ("trade_date", ">=", day_value(schema, "trade_date", start)),
        ("trade_date", "<=", day_value(schema, "trade_date", day)),
        ("ts_code", "in", sorted(scope)),
    ]).to_pandas()
    if stamp(panel) != expected_stamp:
        raise ContractError("ACT033A_FINANCE_PANEL_MOVED_DURING_READ")
    frame["ts_code"] = act031.v12._normalize_observed_column(frame.ts_code, act031.v12._code, "ts_code")
    frame["trade_date"] = act031.v12._normalize_observed_column(frame.trade_date, act031.review.day, "trade_date")
    if (frame.duplicated(["ts_code", "trade_date"]).any() or not frame.trade_date.between(start, day).all()
            or not set(frame.ts_code) <= scope):
        raise ContractError("ACT033A_FINANCE_PIT_SCOPE_OR_DUPLICATE_KEYS")
    valid = frame.turnover_rate_status.isin(ALLOWED_TURNOVER) & frame.turnover_rate_volume_source.eq(
        "TDX_OFFICIAL_G4DAY_NATIVE_SHARES")
    frame["turnover_rate_pct"] = pd.to_numeric(frame.turnover_rate_pct.where(valid), errors="coerce")
    frame["float_share_10k"] = pd.to_numeric(frame.turnover_rate_denominator_10k.where(valid), errors="coerce")
    return frame[["ts_code", "trade_date", "turnover_rate_pct", "float_share_10k"]]


def read_overlay(day, source, signal, days):
    scope = gates.overlay_scope(signal)
    if not scope:
        return pd.DataFrame(columns=["ts_code", "trade_date", *OVERLAY]), {"scope_n": 0}
    anchors = [act031.act028.date8(value) for value in signal.loc[signal.ts_code.isin(scope), "invalidation_anchor_date"]]
    start = min([days[-21], *[value for value in anchors if value is not None]])
    mode = source.get("signal_mode", "EXACT_PANEL")
    if mode == "EXACT_PANEL":
        bound = act031.existing_panel(day, source)
        if not bound:
            return pd.DataFrame(columns=["ts_code", "trade_date", *OVERLAY]), {"reason": "EXACT_D_OVERLAY_PANEL_UNAVAILABLE"}
        overlay = act031.read_panel(bound, start, day, OVERLAY, codes=scope, optional=("j",))
        finance = read_finance(bound, days[-20], day, scope)
        return overlay.merge(finance, how="left", on=["ts_code", "trade_date"], validate="one_to_one"), {
            "scope_n": len(scope), "mode": "EXACT_D_QFQ", "bounds": [start, day],
            "finance_rows": int(finance.turnover_rate_pct.count()),
            "exact_d_finance_rows": int(finance.loc[finance.trade_date.eq(day), "float_share_10k"].count()),
        }
    if mode == "DATED_V4_RAW_PREFIX":
        from ops.pft_act031_raw_prefix import read_recovered

        overlay = read_recovered(day, source, scope)
        return overlay.loc[overlay.trade_date.between(start, day)], {
            "scope_n": len(scope), "mode": mode, "bounds": [start, day], "recovery": overlay.attrs["recovery"],
            "missing_fields": ["j", "turnover_rate_pct", "float_share_10k"],
        }
    raise ContractError(f"ACT033A_OVERLAY_SOURCE_MODE_UNKNOWN:{day}:{mode}")


def covered_source(source):
    return bool(source.get("official_ref") and not source.get("unavailable_reason")
                and (source.get("signal_mode") == "DATED_V4_RAW_PREFIX"
                     or source.get("panel_path") and Path(source["panel_path"]).is_file()))


def projected_signal(frame):
    columns = ["trade_date", "ts_code", "name", "white", "yellow", "stage", "invalidation_price",
               "invalidation_anchor_date", "projected_p_s", "final_state", "main_tactic", "route_reasons",
               "feature_context_end"]
    return frame[columns]


def make_day(day, source, previous, sessions, output, plan_ref, models):
    record = {"schema": SCHEMA, "trade_date": day, "input_source": source, "plan": plan_ref, **act031.FLAGS}
    if previous:
        raw_ref = previous["signals"]
    elif not covered_source(source):
        return {**record, "status": "CANNOT_CONFIRM",
                "reason": source.get("unavailable_reason") or source.get("panel_missing_reason")
                or "EXACT_D_OFFICIAL_AND_PANEL_SOURCE_UNAVAILABLE", "groups": None}
    else:
        with TemporaryDirectory(prefix=f".model-{day}-", dir=output) as temporary:
            previous_run = act031.compute_signal_day(day, source, Path(temporary), plan_ref["sha256"], models, sessions)
            if previous_run["signals"] is None:
                return {**record, "status": "CANNOT_CONFIRM", "reason": previous_run["reason"], "groups": None}
            signal = projected_signal(pd.read_parquet(checked(previous_run["signals"])))
        raw_ref = None
    if previous:
        signal = projected_signal(pd.read_parquet(checked(raw_ref)))
    if (signal.empty or signal.ts_code.duplicated().any() or signal.trade_date.ne(day).any()
            or signal.feature_context_end.dropna().ne(day).any()):
        raise ContractError(f"ACT033A_SIGNAL_KEYS_OR_CAUSAL_PREFIX_INVALID:{day}")
    quotes, quote_identity = act031.day_quotes(day, source)
    if quotes is None:
        raise ContractError(f"ACT033A_D_OFFICIAL_QUOTES_MISSING_AFTER_ADMISSION:{day}")
    days = previous_days(sessions.schedule, day, 20)
    overlay, overlay_identity = read_overlay(day, source, signal, days)
    selected, stats = gates.select_day(signal, overlay, quotes, days)
    report_scope = selected.BASE | selected.b1_structural_eligible.fillna(True)
    return {
        **record, "status": "SIGNALS_FROZEN", "source_quotes": quote_identity,
        "overlay": overlay_identity, "prior_signals": raw_ref, "signals_scored_n": len(signal),
        "model_execution": "ACT031_REUSE" if previous else "NEW_FROZEN_INFERENCE",
        "d_official_a_market": market_day(quotes), "eligibility": stats,
        "groups": act031.frame_atomic(output / f"{day}.parquet", selected.loc[report_scope]),
        "eligible_all_a": (None if previous else
                           act031.frame_atomic(output / f"{day}_eligible_a.parquet", signal[["ts_code"]])),
    }


def market_day(quotes):
    gains = [quote["change_pct"] / 100 for quote in quotes.values() if quote["eligible_for_daily_gain_rank"]]
    return {"eligible_quote_n": len(gains), "equal_weight_return": mean(gains) if gains else None}


def market_regime(day, sessions, market_days):
    window = previous_days(sessions.schedule, day, 4)
    values = [market_days.get(date, {}).get("equal_weight_return") for date in window]
    missing = [date for date, value in zip(window, values) if value is None]
    if missing:
        return {"name": "UNKNOWN", "trailing_5_return": None, "missing_days": missing, "source_days": window}
    change = prod(1 + value for value in values) - 1
    name = "UP" if gates.gte(change, .01) else "DOWN" if gates.lte(change, -.01) else "FLAT"
    return {"name": name, "trailing_5_return": change, "missing_days": [], "source_days": window}


def select_checkpoint(path, day, source, plan_ref):
    record = act031.read_ref(act031.ref(path))
    if (record.get("schema") != SCHEMA or record.get("trade_date") != day
            or record.get("input_source") != source or record.get("plan") != plan_ref
            or record.get("status") not in {"SIGNALS_FROZEN", "CANNOT_CONFIRM"}
            or bool(record.get("groups")) != (record["status"] == "SIGNALS_FROZEN")):
        raise ContractError(f"ACT033A_CHECKPOINT_SCOPE_OR_IDENTITY_CHANGED:{day}")
    for key in ("groups", "eligible_all_a", "prior_signals"):
        if record.get(key):
            checked(record[key])
    return record


_WORK_MODELS = None
_WORK_SESSIONS = None


def initialize_worker(models, sessions):
    global _WORK_MODELS, _WORK_SESSIONS
    _WORK_MODELS, _WORK_SESSIONS = models, sessions
    act031.initialize_worker(models, sessions)


def checkpoint(day, source, prior, output, plan_ref):
    record = make_day(day, source, prior, _WORK_SESSIONS, output, plan_ref, _WORK_MODELS)
    act031.json_atomic(output / f"{day}.json", record)
    return day, record


def code_identity():
    files = [APP_ROOT / "ops" / f"{name}.py" for name in (
        "pft_act033a_replay", "pft_act033a_groups", "pft_act033a_outcomes", "pft_act031_frozen_forward",
        "pft_act031_raw_prefix", "research_panel_logical", "research_panel_qfq", "research_panel_top200",
        "_a_share_daily_sync_parts/official_daily_package",
    )]
    files += [Path(module.__file__).resolve() for module in act031.SOURCE_MODULES]
    return {path.stem: act031.ref(path) for path in files}


def seal_records(inputs, input_ref, seal_path):
    seal = act031.read_ref(act031.ref(seal_path))
    dates = inputs["signal_dates"]
    if (seal.get("schema") != SCHEMA or seal.get("input") != input_ref
            or set(seal.get("daily_receipts", {})) != set(dates)
            or seal.get("observations_opened_in_signal_phase") is not False):
        raise ContractError("ACT033A_SEAL_SCOPE_OR_INPUT_CHANGED")
    plan = act031.read_ref(seal["plan"])
    for reference in plan["code"].values():
        checked(reference)
    for day in dates:
        checked(seal["daily_receipts"][day])
    records = {day: select_checkpoint(Path(seal["daily_receipts"][day]["path"]), day,
                                      inputs["days"][day], seal["plan"]) for day in dates}
    if (seal["evaluable_days"] != [day for day, row in records.items() if row["groups"]]
            or seal["unavailable_days"] != {day: row["reason"] for day, row in records.items() if not row["groups"]}):
        raise ContractError("ACT033A_SEAL_DENOMINATOR_CHANGED")
    return seal, records


def signal_phase(inputs, input_ref, sessions, model_dir, output, workers):
    target = output / "signals"
    target.mkdir(exist_ok=True)
    seal_path = target / "SEAL.json"
    if seal_path.exists():
        return seal_records(inputs, input_ref, seal_path)[0]
    prior_seal, model_identity, prior_sessions = prior_signals(inputs)
    if sessions.identity != prior_sessions.identity:
        raise ContractError("ACT033A_CANONICAL_CALENDAR_CHANGED_FROM_ACT031")
    days = inputs["signal_dates"]
    sources = inputs["days"]
    recent = prior_seal["daily_receipts"]
    plan = {"schema": SCHEMA, "input": input_ref, "code": code_identity(), "calendar": sessions.identity,
            "model": model_identity, "prior_seal": inputs["prior_act031"]["signal_seal"],
            "signal_dates": days, "training_overlap_days": [day for day in days if day <= TRAINING_END],
            "policy": SIGNAL_POLICY, "fit_calls": FIT_CALLS, **act031.FLAGS}
    plan_ref = act031.json_atomic(target / "PLAN.json", plan)
    records, pending = {}, []
    for day in days:
        path = target / f"{day}.json"
        if path.exists():
            records[day] = select_checkpoint(path, day, sources[day], plan_ref)
        elif day in recent:
            pending.append((day, act031.read_ref(recent[day])))
        elif covered_source(sources[day]):
            pending.append((day, None))
        else:
            records[day] = make_day(day, sources[day], None, sessions, target, plan_ref, None)
            act031.json_atomic(path, records[day])
    models = None
    if any(prior is None for _, prior in pending):
        from threadpoolctl import threadpool_limits

        if model_dir is None:
            raise ContractError("ACT033A_MODELS_PATH_REQUIRED_FOR_NEW_PRE_RECENT_INFERENCE")
        with threadpool_limits(limits=1):
            models, identity = act031.prior.load_frozen(model_dir)
        if identity != model_identity:
            raise ContractError("ACT033A_REPLAY_MODEL_DIFFERS_FROM_ACT031")
    if pending:
        with ProcessPoolExecutor(max_workers=min(workers, len(pending)), initializer=initialize_worker,
                                 initargs=(models, sessions)) as executor:
            futures = [executor.submit(checkpoint, day, sources[day], prior, target, plan_ref)
                       for day, prior in pending]
            for future in as_completed(futures):
                day, record = future.result()
                records[day] = record
                print(json.dumps({"phase": "signals", "date": day, "status": record["status"],
                                  "model_execution": record.get("model_execution"),
                                  "counts": (record.get("eligibility") or {}).get("groups")}), flush=True)
    market_days = {}
    needed = set().union(*(previous_days(sessions.schedule, day, 4) for day in days))
    for day in days:
        if day not in needed:
            continue
        record = records[day]
        if record.get("d_official_a_market"):
            market_days[day] = record["d_official_a_market"]
        elif sources[day].get("official_ref"):
            quotes, identity = act031.day_quotes(day, sources[day])
            market_days[day] = {**market_day(quotes), "official_ref": identity["official_input"]}
    seal = {"schema": SCHEMA, "input": input_ref, "plan": plan_ref,
            "daily_receipts": {day: act031.ref(target / f"{day}.json") for day in days},
            "evaluable_days": [day for day in days if records[day]["groups"]],
            "unavailable_days": {day: records[day]["reason"] for day in days if not records[day]["groups"]},
            "regimes": {day: market_regime(day, sessions, market_days) for day in days},
            "market_days": market_days,
            "observations_opened_in_signal_phase": False, "fit_calls": FIT_CALLS, **act031.FLAGS}
    act031.json_atomic(seal_path, seal)
    return seal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("signals", "outcomes"))
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("workers must be positive")
    inputs, input_ref, sessions = load_inputs(args.inputs.resolve(strict=True))
    output = args.output.resolve()
    with act031.exclusive_run(output):
        if args.phase == "signals":
            result = signal_phase(inputs, input_ref, sessions, args.models, output, args.workers)
        else:
            from ops.pft_act033a_outcomes import outcome_phase

            result = outcome_phase(inputs, input_ref, sessions, output)
    print(json.dumps({"phase": args.phase, "status": result.get("status", "SIGNALS_SEALED"),
                      "evaluable_days": result.get("evaluable_days", []), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
