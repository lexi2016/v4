"""One frozen ACT023/025/028 forward study through 2026-11-23."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from contracts.a_share_instruments import a_share_instrument_rejection
from contracts import trading_calendar
from ops import pft_act028_rebuild_maturity as act028

act025, prior = act028.act025, act028.prior
act023, old, review = prior.act023, prior.old, prior.review
v12 = old.v12
ContractError = prior.ContractError
FLAGS = dict(review.FLAGS)
FIRST, LAST, CUTOFF = "20261026", "20261120", "20261123"
HORIZONS = (1, 3, 5)
CAP_RULE_SOURCES = {
    "SH": "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml",
    "SH_RISK_WARNING": "https://star.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml",
    "SZ": "https://www.szse.cn/www/lawrules/rule/stock/t20260424_620190.html",
    "BJ": "https://www.bse.cn/jygl_list/200028217.html",
}
TACTICS = old.CLASSES[:3]
GROUPS = (*TACTICS, "CONFIRMED_S", "UNKNOWN_PROJECTED_GE_045", "ELIGIBLE_ALL_A")
SCHEMA = "pft_act031_frozen_forward.v1"
SOURCE_MODULES = (prior, act023, act025, act028, old, review)


def ref(path):
    return {"path": str(path), "sha256": act023.sha(path)}


def read_ref(reference):
    path = Path(reference["path"])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ContractError(f"ACT031_UNSAFE_JSON_SOURCE:{path}")
    from ops.pft_s_first_baseline import _read_json_stable

    value, _, digest = _read_json_stable(path)
    if digest != reference["sha256"]:
        raise ContractError(f"ACT031_SOURCE_SHA_CHANGED:{path}")
    return value


def json_atomic(path, data):
    from ops.research_panel_daily_product import save

    return save(path, review.clean(data), immutable=True)


def frame_atomic(path, frame):
    temporary = path.with_name(f".{path.name}.{os.getpid()}.pending")
    try:
        if path.suffix == ".csv":
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        else:
            frame.to_parquet(temporary, index=False, compression="zstd")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return ref(path)


@contextmanager
def exclusive_run(output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContractError("ACT031_RUN_DIRECTORY_IN_USE") from error
        yield


def load_inputs(path):
    inputs = json.loads(path.read_text())
    sessions = act028.ExchangeSessions()
    schedule = sessions.schedule
    days = [FIRST]
    while days[-1] < CUTOFF:
        days.append(trading_calendar.next_session(schedule, days[-1], market="a_share"))
    if (len(days) != 21 or days[-2:] != [LAST, CUTOFF] or inputs.get("cutoff") != CUTOFF
            or inputs.get("signal_dates") != days[:-1] or inputs.get("observation_dates") != days
            or set(inputs.get("days", {})) != set(days)):
        raise ContractError("ACT031_FROZEN_WINDOW_OR_CALENDAR_MISMATCH")
    return inputs, sessions


def bind_panel(day, source):
    """Keep ACT021 exact-day binding, streaming the SHA for physical archives."""
    from ops.research_panel_logical import stamp
    from ops.research_panel_qfq import panel_contract
    from ops.pft_s_first_baseline import _basis_asof

    role = source.get("panel_role", "backtest")
    if role not in {"backtest", "selector"}:
        raise ContractError(f"ACT031_PANEL_ROLE_UNKNOWN:{day}")
    panel = Path(source["panel_path"])
    before = stamp(panel)
    producer = source["producer_ref"]
    receipt = read_ref(producer)
    contract = panel_contract(panel)
    basis = (contract.get("market_basis") or {}).get("A") or contract
    if (contract.get("schema") != "a_share_qfq_panel_v1"
            or _basis_asof(contract) != day or act028.date8(receipt.get("target_date")) != day
            or receipt.get("status") not in {"READY", "CANDIDATE_READY"}
            or source["source_generation"] != receipt.get("generation_id")
            or source["source_generation"] != contract.get("generation_id")
            or not contract.get("formula_sha256")
            or any(v != contract["formula_sha256"] for v in (source.get("formula_sha256"), receipt.get("formula_sha256")))
            or producer["path"] != contract.get("generation_manifest_path")
            or not all(contract.get(key) and receipt.get(key) == contract[key]
                       for key in ("snapshot_file_sha256", "input_sha256"))
            or receipt.get("candidates", {}).get(role) != str(panel)
            or receipt.get("candidate_sha256", {}).get(role) != source["panel_sha256"]
            or source.get("price_basis", "QFQ_ASOF") != basis.get("price_basis")):
        raise ContractError(f"ACT031_EXACT_PANEL_SOURCE_CONFLICT:{day}")
    if act023.sha(panel) != source["panel_sha256"] or stamp(panel) != before:
        raise ContractError(f"ACT031_EXACT_PANEL_SHA_OR_STAT_CONFLICT:{day}")
    return panel, before


def existing_panel(day, source):
    path = source.get("panel_path")
    if path and Path(path).exists():
        return bind_panel(day, source)
    return None


def read_panel(bound, start, end, columns, *, codes=None, optional=()):
    import pandas as pd
    from ops.research_panel_logical import parquet, stamp

    panel, expected_stamp = bound
    if stamp(panel) != expected_stamp:
        raise ContractError("ACT031_PANEL_MOVED_BEFORE_READ")
    schema = parquet.read_schema(panel)
    actual = {name.lower(): name for name in schema.names}
    mappings = {}
    for semantic in dict.fromkeys(("ts_code", "trade_date", "market_type", *columns)):
        aliases = v12.ALIASES.get(semantic, (semantic,))
        match = next((actual[name] for name in aliases if name in actual), None)
        if match is None and semantic not in optional:
            raise ContractError(f"ACT031_PANEL_REQUIRED_COLUMN:{semantic}")
        if match is not None:
            mappings[semantic] = match
    day_col = mappings["trade_date"]
    filters = [(day_col, ">=", v12._arrow_date_value(schema, day_col, start)),
               (day_col, "<=", v12._arrow_date_value(schema, day_col, end))]
    if codes is not None:
        filters.append((mappings["ts_code"], "in", sorted(codes)))
    frame = parquet.read_table(panel, columns=list(mappings.values()), filters=filters).to_pandas()
    if stamp(panel) != expected_stamp:
        raise ContractError("ACT031_PANEL_MOVED_DURING_READ")
    frame.rename(columns={name: semantic for semantic, name in mappings.items()}, inplace=True)
    frame = frame.loc[frame.market_type.astype("string").str.strip().str.upper().isin(review.A_MARKETS)].copy()
    frame["ts_code"] = v12._normalize_observed_column(frame.ts_code, v12._code, "ts_code")
    frame["trade_date"] = v12._normalize_observed_column(frame.trade_date, review.day, "trade_date")
    if (frame.duplicated(["ts_code", "trade_date"]).any()
            or not frame.trade_date.between(start, end).all()
            or codes is not None and not set(frame.ts_code) <= set(codes)):
        raise ContractError("ACT031_PANEL_READ_SCOPE_OR_DUPLICATE_KEY")
    for semantic in columns:
        frame[semantic] = pd.to_numeric(frame[semantic], errors="coerce") if semantic in frame else float("nan")
    return frame.sort_values(["ts_code", "trade_date"], kind="stable").reset_index(drop=True)


def day_quotes(day, source):
    from ops.research_panel_top200 import official_quotes

    if not source.get("official_ref"):
        return None, None
    quotes, owner = official_quotes(source["official_ref"], int(day))
    equities = {code: row for code, row in quotes.items() if a_share_instrument_rejection(code) is None}
    return equities, {"official_input": owner.input_ref, "official_package": owner.package_ref,
                      "official_calendar": owner.calendar_ref, "previous_session": str(owner.previous),
                      "equity_family_rows": len(equities)}


def special_treatment(name):
    if not name or not str(name).strip():
        return None
    normalized = "".join(unicodedata.normalize("NFKC", str(name)).upper().split())
    return normalized.startswith(("*ST", "ST", "S*ST", "SST"))


def positive(value):
    number = prior.finite(value)
    return number if number is not None and number > 0 else None


def strict_g1(white, yellow):
    w, y = positive(white), positive(yellow)
    return w is not None and y is not None and w < y


def select_eligible(exact, quotes, bar_counts):
    lookup = {row.ts_code: row for row in exact.itertuples(index=False)}
    counts, eligible = Counter(), {}
    for code in sorted(set(lookup) | set(quotes)):
        if a_share_instrument_rejection(code) is not None:
            counts["NON_A_EQUITY_FAMILY"] += 1
            continue
        panel, quote = lookup.get(code), quotes.get(code, {})
        st = special_treatment(quote.get("name"))
        if st is True:
            counts["D_ST"] += 1
        elif st is None:
            counts["D_OFFICIAL_NAME_OR_QUOTE_MISSING"] += 1
        elif not quote.get("eligible_for_daily_gain_rank"):
            counts["D_NONTRADABLE_OR_INVALID"] += 1
        elif panel is None:
            counts["D_EXACT_PANEL_ROW_MISSING"] += 1
        elif panel.tradeable_basic != 1:
            counts["D_NONTRADABLE_OR_INVALID"] += 1
        elif bar_counts.get(code) is None:
            counts["D_K_COUNT_UNKNOWN"] += 1
        elif bar_counts[code] < 65:
            counts["D_LT_65_K"] += 1
        else:
            eligible[code] = {"name": quote["name"], "bars_observed": bar_counts[code],
                              "white": prior.finite(panel.zge_white_line), "yellow": prior.finite(panel.zge_yellow_line)}
            counts["ELIGIBLE"] += 1
    return eligible, dict(counts)


def cohort_columns(frame):
    confirmed = frame.final_state.eq("CONFIRMED_S")
    for tactic in TACTICS:
        frame[tactic] = confirmed & frame.main_tactic.eq(tactic)
    frame["CONFIRMED_S"] = confirmed
    frame["UNKNOWN_PROJECTED_GE_045"] = frame.final_state.eq("UNKNOWN_BORDERLINE") & frame.projected_p_s.ge(.45)
    frame["ELIGIBLE_ALL_A"] = True
    return frame


def route_signals(eligible, history, day, models, sessions):
    import pandas as pd

    codes = list(eligible)
    to_score = [code for code in codes if not strict_g1(eligible[code]["white"], eligible[code]["yellow"])]
    positions = {code: i for i, code in enumerate(to_score)}
    if to_score:
        matrix, evidence = prior.extract_structure(history, day, to_score)
        predicted = prior.batch_predict(models, matrix, evidence)
    rows = []
    for code in codes:
        current = eligible[code]
        index = positions.get(code)
        if index is None:
            entry = {"status": "NOT_INFERRED_STRICT_OBSERVED_G1", "white": current["white"], "yellow": current["yellow"]}
            root, children = None, None
        else:
            entry = evidence[index]
            root, children = predicted.get(index, (None, None))
            if (prior.finite(entry.get("white")) != current["white"]
                    or prior.finite(entry.get("yellow")) != current["yellow"]):
                raise ContractError(f"ACT031_D_PREFIX_LINE_DRIFT:{day}:{code}")
        baseline = act025.route(root, children, entry)
        anchor_stack = entry.get("anchors", {})
        repair = next((event["date"] for event in reversed(anchor_stack.get("events", [])) if event["role"] == "repair"), None)
        active = anchor_stack.get("active") or {}
        invalidation = positive(active.get("low"))
        result = act028.maturity(baseline, repair, day, sessions, anchor_status="ACT023_ACT021_CAUSAL_ROLE_STACK")
        rows.append({"trade_date": day, "ts_code": code, **current, "prediction_status": entry["status"],
                     "feature_context_start": entry.get("context_start"), "feature_context_end": entry.get("context_end"),
                     "feature_causal_bars": entry.get("causal_bars"), "stage": entry.get("stage"),
                     "invalidation_price": invalidation,
                     "invalidation_price_source": "ACT021_ACTIVE_ANCHOR_LOW_QFQ_ASOF_D" if invalidation is not None else "CANNOT_CONFIRM",
                     "invalidation_anchor_date": active.get("date"), "invalidation_anchor_id": active.get("anchor_id"),
                     "act025_state": baseline["final_state"], "act025_tactic": baseline["main_tactic"], **result})
    return cohort_columns(pd.DataFrame(rows))


def compute_signal_day(day, source, output, run_identity, models, sessions):
    start = (datetime.strptime(day, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
    mode = source.get("signal_mode", "EXACT_PANEL")
    if mode not in {"EXACT_PANEL", "DATED_V4_RAW_PREFIX"}:
        raise ContractError(f"ACT031_SIGNAL_MODE_UNKNOWN:{day}:{mode}")
    summary = {"schema": SCHEMA, "trade_date": day, "run_identity": run_identity, "source": source,
               "signal_mode": mode, **FLAGS}
    bound = existing_panel(day, source) if mode == "EXACT_PANEL" else None
    if not source.get("official_ref") or (mode == "EXACT_PANEL" and bound is None):
        reason = ("EXACT_D_OFFICIAL_PACKAGE_UNAVAILABLE" if not source.get("official_ref") else
                  source.get("panel_missing_reason") or "EXACT_D_PANEL_UNAVAILABLE")
        return {**summary, "status": "CANNOT_CONFIRM", "reason": reason, "signals": None}
    quotes, quote_identity = day_quotes(day, source)
    recovery = None
    if mode == "DATED_V4_RAW_PREFIX":
        from ops.pft_act031_raw_prefix import read_recovered

        raw_scope = {code for code, quote in quotes.items() if quote["eligible_for_daily_gain_rank"]
                     and special_treatment(quote["name"]) is False}
        history = read_recovered(day, source, raw_scope)
        if (not history.trade_date.between(start, day).all() or not set(history.ts_code) <= raw_scope
                or history.duplicated(["ts_code", "trade_date"]).any()):
            raise ContractError(f"ACT031_RECOVERED_PREFIX_SCOPE_OR_KEY_CONFLICT:{day}")
        recovery = history.attrs.get("recovery")
        exact = history.loc[history.trade_date.eq(day)]
    else:
        exact = read_panel(bound, day, day, ("tradeable_basic", "bars_since_list", "zge_white_line", "zge_yellow_line"),
                           optional=("bars_since_list",))
    if exact.empty:
        return {**summary, "status": "CANNOT_CONFIRM", "reason": "EXACT_D_A_PANEL_EMPTY", "signals": None}
    bar_counts = {row.ts_code: int(row.bars_since_list) for row in exact.itertuples(index=False)
                  if positive(row.bars_since_list) is not None}
    fallback = set(exact.ts_code) - set(bar_counts)
    if fallback:
        counted = (history.loc[history.ts_code.isin(fallback)] if mode == "DATED_V4_RAW_PREFIX"
                   else read_panel(bound, start, day, (), codes=fallback))
        bar_counts.update({code: int(count) for code, count in counted.groupby("ts_code").size().items()})
    eligible, disposition = select_eligible(exact, quotes, bar_counts)
    if not eligible:
        return {**summary, "status": "CANNOT_CONFIRM", "reason": "NO_ELIGIBLE_A_PER_EXACT_D", "signals": None,
                "source_quotes": quote_identity, "eligibility_disposition": disposition, "recovery": recovery}
    scoring = {code for code, row in eligible.items() if not strict_g1(row["white"], row["yellow"])}
    if mode == "DATED_V4_RAW_PREFIX":
        history = history.loc[history.ts_code.isin(scoring)]
    else:
        history = read_panel(bound, start, day, (*old.INPUTS[3:], "bbi"), codes=scoring, optional=("bbi",)) if scoring else None
    signal = route_signals(eligible, history, day, models, sessions)
    if signal.feature_context_end.dropna().ne(day).any() or signal.duplicated(["trade_date", "ts_code"]).any():
        raise ContractError(f"ACT031_SIGNALS_NOT_STRICT_LE_D:{day}")
    return {**summary, "status": "SIGNALS_FROZEN", "source_quotes": quote_identity,
            "eligibility_disposition": disposition, "bounds": [start, day], "exact_a_panel_rows": len(exact),
            "history_count_fallback_symbols": len(fallback), "scoring_symbols": len(scoring), "recovery": recovery,
            "prediction_status_counts": signal.prediction_status.value_counts().to_dict(),
            "state_counts": signal.final_state.value_counts().to_dict(),
            "group_counts": {name: int(signal[name].sum()) for name in GROUPS},
            "signals": frame_atomic(output / f"{day}.parquet", signal)}


def check_day_record(record, day, source, run_identity):
    if (record.get("schema") != SCHEMA or record.get("trade_date") != day
            or record.get("source") != source or record.get("run_identity") != run_identity
            or record.get("status") not in {"SIGNALS_FROZEN", "CANNOT_CONFIRM"}
            or bool(record.get("signals")) != (record["status"] == "SIGNALS_FROZEN")):
        raise ContractError(f"ACT031_SIGNAL_CHECKPOINT_IDENTITY_CHANGED:{day}")
    if record["signals"]:
        review.checked_file(record["signals"]["path"], record["signals"]["sha256"])
    return record


_WORKER_MODELS = None
_WORKER_SESSIONS = None
_THREAD_LIMIT = None


def initialize_worker(models, sessions):
    import pyarrow as pa
    from threadpoolctl import threadpool_limits

    global _WORKER_MODELS, _WORKER_SESSIONS, _THREAD_LIMIT
    _WORKER_MODELS, _WORKER_SESSIONS = models, sessions
    pa.set_cpu_count(1)
    pa.set_io_thread_count(2)
    _THREAD_LIMIT = threadpool_limits(limits=1)


def checkpoint_signal(day, source, target, run_identity):
    record = compute_signal_day(day, source, target, run_identity, _WORKER_MODELS, _WORKER_SESSIONS)
    json_atomic(target / f"{day}.json", record)
    return day, record


def signal_phase(inputs, sessions, input_ref, model_dir, output, workers):
    target = output / "signals"
    target.mkdir(exist_ok=True)
    seal_path = target / "SEAL.json"
    if seal_path.exists():
        return load_seal(inputs, input_ref, seal_path)
    code = {"runner": ref(Path(__file__).resolve()),
            **{module.__name__: ref(Path(module.__file__).resolve()) for module in SOURCE_MODULES}}
    for name in ("research_panel_logical", "research_panel_qfq", "research_panel_top200",
                 "_a_share_daily_sync_parts/official_daily_package"):
        code[name] = ref(APP_ROOT / "ops" / f"{name}.py")
    if any(inputs["days"][day].get("signal_mode") == "DATED_V4_RAW_PREFIX" for day in inputs["signal_dates"]):
        code["dated_raw_prefix"] = ref(APP_ROOT / "ops" / "pft_act031_raw_prefix.py")
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1):
        models, model_identity = prior.load_frozen(model_dir)
    plan = {"schema": SCHEMA, "input": input_ref, "code": code, "model": model_identity, "calendar": sessions.identity,
            "signal_dates": inputs["signal_dates"], "strict_g1_prefilter": "NO_RANK_OR_SCORE_FOR_G1_REJECTS", **FLAGS}
    run_identity = json_atomic(target / "PLAN.json", plan)["sha256"]
    cached, pending = {}, []
    for day in inputs["signal_dates"]:
        path = target / f"{day}.json"
        if path.exists():
            cached[day] = check_day_record(json.loads(path.read_text()), day, inputs["days"][day], run_identity)
        else:
            pending.append(day)
    if pending:
        with ProcessPoolExecutor(max_workers=min(workers, len(pending)), initializer=initialize_worker,
                                 initargs=(models, sessions)) as executor:
            futures = [executor.submit(checkpoint_signal, day, inputs["days"][day], target, run_identity) for day in pending]
            for future in as_completed(futures):
                day, record = future.result()
                cached[day] = record
                print(json.dumps({"stage": "signals", "day": day, "status": record["status"],
                                  "groups": record.get("group_counts")}, ensure_ascii=False), flush=True)
    seal = {"schema": SCHEMA, "input": input_ref, "plan": ref(target / "PLAN.json"),
            "daily_receipts": {day: ref(target / f"{day}.json") for day in inputs["signal_dates"]},
            "evaluable_days": [day for day in inputs["signal_dates"] if cached[day]["signals"]],
            "unavailable_days": {day: row["reason"] for day, row in sorted(cached.items()) if not row["signals"]},
            "observations_opened_in_signal_phase": False, **FLAGS}
    json_atomic(seal_path, seal)
    return seal


def load_seal(inputs, input_ref, seal_path):
    if not seal_path.is_file():
        raise ContractError("ACT031_SIGNALS_MUST_BE_SEALED_BEFORE_OUTCOMES")
    seal = json.loads(seal_path.read_text())
    if (seal.get("schema") != SCHEMA or seal.get("input") != input_ref
            or set(seal.get("daily_receipts", {})) != set(inputs["signal_dates"])):
        raise ContractError("ACT031_SIGNAL_SEAL_SCOPE_OR_INPUT_CHANGED")
    plan = read_ref(seal["plan"])
    for source in plan["code"].values():
        review.checked_file(source["path"], source["sha256"])
    records = {day: check_day_record(read_ref(seal["daily_receipts"][day]), day, inputs["days"][day], seal["plan"]["sha256"])
               for day in inputs["signal_dates"]}
    if (seal["evaluable_days"] != [day for day, record in records.items() if record["signals"]]
            or seal["unavailable_days"] != {day: record["reason"] for day, record in records.items() if not record["signals"]}):
        raise ContractError("ACT031_SIGNAL_SEAL_DENOMINATOR_CHANGED")
    return seal


def rank_for_day(day, source, quotes):
    reference = source.get("rank_ref")
    if reference is not None:
        payload = read_ref(reference)
        members = payload.get("top200", [])
        codes = [row.get("symbol", "") for row in members]
        ranks = [row.get("rank") for row in members]
        if (payload.get("schema") != "V4_A_SHARE_TOP200_V1"
                or act028.date8(payload.get("data_date")) != day
                or payload.get("source_generation") != source["source_generation"]
                or payload.get("official_input") != source.get("official_ref")
                or len(codes) != 200 or len(set(codes)) != 200
                or any(a_share_instrument_rejection(code) for code in codes)
                or any(type(rank) is not int for rank in ranks)
                or sorted(ranks) != list(range(1, 201))):
            raise ContractError(f"ACT031_OFFICIAL_RANK_DATE_GENERATION_OR_MEMBERSHIP_CONFLICT:{day}")
        return dict(zip(codes, ranks)), "V4_OFFICIAL_TOP200"
    if quotes is None:
        return {}, "CANNOT_CONFIRM"
    ordered = sorted((row for row in quotes.values() if row["eligible_for_daily_gain_rank"]),
                     key=lambda row: (-row["change_pct"], row["symbol"]))
    if len(ordered) < 200:
        return {}, "CANNOT_CONFIRM"
    return {row["symbol"]: i for i, row in enumerate(ordered[:200], 1)}, "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"


def inferred_band(code):
    # This frozen window follows the exchange rules effective July 2026.
    if a_share_instrument_rejection(code) is not None:
        return None
    if code.endswith(".BJ"):
        return "0.30"
    if code.startswith(("300", "301", "688", "689")):
        return "0.20"
    return "0.10"


def opening_assessment(code, quote):
    """Observed uniform OHLC and standard board cap proxy in raw yuan."""
    if quote is None:
        return {"one_price_upper_limit": None, "opening_buyable_proxy": None,
                "opening_status": "CANNOT_CONFIRM_D1_QUOTE_MISSING", "inferred_upper_limit": None}
    if not quote.get("eligible_for_daily_gain_rank"):
        no_trade = quote.get("zero_volume") is True
        return {"one_price_upper_limit": None, "opening_buyable_proxy": False if no_trade else None,
                "opening_status": "D1_NO_VOLUME" if no_trade else "CANNOT_CONFIRM_D1_INVALID_BAR",
                "inferred_upper_limit": None}
    o, h, l, c = (quote[field] for field in ("open", "high", "low", "close"))
    one_price = o == h == l == c
    band = inferred_band(code)
    previous = positive(quote.get("prev_close"))
    if band is None or previous is None:
        return {"one_price_upper_limit": None if one_price else False, "opening_buyable_proxy": None,
                "opening_status": "CANNOT_CONFIRM_D1_CAP_INPUT", "inferred_upper_limit": None}
    cap = float((Decimal(str(previous)) * (1 + Decimal(band))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    tolerance = 1e-6
    if o > cap + tolerance:
        return {"one_price_upper_limit": None if one_price else False, "opening_buyable_proxy": None,
                "opening_status": "CANNOT_CONFIRM_D1_CAP_EXCEPTION", "inferred_upper_limit": cap}
    at_cap = o >= cap - tolerance
    return {"one_price_upper_limit": one_price and at_cap, "opening_buyable_proxy": not at_cap,
            "opening_status": "STANDARD_CAP_AT_OPEN" if at_cap else "STANDARD_CAP_MODELED_OPEN",
            "inferred_upper_limit": cap}


def load_outcomes(inputs, code_scope):
    observations = {}
    for day in inputs["observation_dates"][1:]:
        source = inputs["days"][day]
        quotes, info = day_quotes(day, source)
        ranks, rank_source = rank_for_day(day, source, quotes)
        observations[day] = {"quotes": quotes or {}, "quote_identity": info, "ranks": ranks,
                             "rank_source": rank_source, "rank_ref": source.get("rank_ref")}
    bound = existing_panel(CUTOFF, inputs["days"][CUTOFF])
    if bound is None or not code_scope:
        return observations, None, None
    raw = read_panel(bound, FIRST, CUTOFF, ("open", "close", "vol", "tradeable_basic"), codes=code_scope)
    usable = raw.tradeable_basic.eq(1) & raw.vol.gt(0) & raw.open.gt(0) & raw.close.gt(0)
    prices = raw.loc[usable].pivot(index="ts_code", columns="trade_date", values="close")
    return observations, prices, {"asof_date": CUTOFF, "price_basis": "QFQ_ASOF", "input": inputs["days"][CUTOFF],
                                  "projected_rows": len(raw), "usable_rows": int(usable.sum())}


def day_forward(signal, day, days, observations, prices):
    import numpy as np
    import pandas as pd

    part = signal.copy()
    position = days.index(day)
    tail = days[position + 1:position + 1 + max(HORIZONS)]
    d1 = observations[tail[0]]
    quotes = [d1["quotes"].get(code) for code in part.ts_code]
    part["d1_date"] = tail[0]
    part["d1_return_source"] = "TDX_OFFICIAL_G4DAY_RAW_CLOSE_OVER_PREV_CLOSE"
    part["d1_close"] = [quote["close"] if quote else None for quote in quotes]
    part["d1_prev_close"] = [quote["prev_close"] if quote else None for quote in quotes]
    part["d1_open"] = [quote["open"] if quote else None for quote in quotes]
    part["d1_return"] = pd.Series([quote["change_pct"] / 100 if quote and quote["eligible_for_daily_gain_rank"]
                                   else np.nan for quote in quotes], index=part.index, dtype=float)
    part["d1_top200_label_source"] = d1["rank_source"]
    part["d1_top200_rank"] = part.ts_code.map(d1["ranks"]).astype("Int64")
    part["d1_top200_hit"] = (part.d1_top200_rank.notna().astype("boolean") if d1["rank_source"] != "CANNOT_CONFIRM"
                              else pd.Series(pd.NA, index=part.index, dtype="boolean"))
    if d1["rank_source"] == "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK":
        part.loc[part.d1_return.isna(), "d1_top200_hit"] = pd.NA
    opening = pd.DataFrame([opening_assessment(code, quote) for code, quote in zip(part.ts_code, quotes)], index=part.index)
    for column in opening:
        part[column] = opening[column]
    part["d1_modeled_open_close_return"] = [quote["close"] / quote["open"] - 1 if fill is True else np.nan
                                             for fill, quote in zip(opening.opening_buyable_proxy, quotes)]
    part["d1_benchmark_return"] = part.d1_return.mean()
    part["d1_benchmark_n"] = int(part.d1_return.count())
    part["d1_excess_return"] = part.d1_return - part.d1_benchmark_return
    qfq = prices.reindex(index=part.ts_code, columns=[day, *tail]) if prices is not None else None
    for n in (3, 5):
        prefix = f"t{n}"
        mature = len(tail) >= n
        part[prefix + "_date"] = tail[n - 1] if mature else None
        part[prefix + "_mature"] = mature
        if not mature or qfq is None:
            for field in ("return", "benchmark_return", "benchmark_min_daily_n", "excess_return", "modeled_open_close_return"):
                part[f"{prefix}_{field}"] = np.nan
            continue
        window = qfq.iloc[:, :n + 1]
        complete = window.notna().all(axis=1).to_numpy()
        part[prefix + "_return"] = np.where(complete, (window.iloc[:, -1] / window.iloc[:, 0]).to_numpy() - 1, np.nan)
        daily = window.iloc[:, 1:].to_numpy() / window.iloc[:, :-1].to_numpy() - 1
        daily = pd.DataFrame(daily)
        breadth = daily.count(axis=0)
        part[prefix + "_benchmark_min_daily_n"] = int(breadth.min())
        part[prefix + "_benchmark_return"] = (float((1 + daily.mean(axis=0)).prod() - 1) if breadth.gt(0).all() else np.nan)
        part[prefix + "_excess_return"] = part[prefix + "_return"] - part[prefix + "_benchmark_return"]
        # The actual D+1 raw opening return is linked to later close changes on
        # one cutoff-bound QFQ basis; no cross-generation price division.
        continuation_complete = window.iloc[:, 1:].notna().all(axis=1).to_numpy()
        close_change = (window.iloc[:, -1] / window.iloc[:, 1]).to_numpy()
        part[prefix + "_modeled_open_close_return"] = np.where(continuation_complete,
            (1 + part.d1_modeled_open_close_return.to_numpy()) * close_change - 1, np.nan)
    return part


def average(values):
    return float(values.mean()) if values.count() else None


def normalized_rate(count, available):
    return count / available if available else None


def group_metrics(part):
    data = {"n": len(part), "opening_buyable_known_n": int(part.opening_buyable_proxy.count()),
            "opening_buyable_n": int(part.opening_buyable_proxy.eq(True).sum()),
            "one_price_upper_limit_known_n": int(part.one_price_upper_limit.count()),
            "one_price_upper_limit_n": int(part.one_price_upper_limit.eq(True).sum())}
    for prefix in ("d1", "t3", "t5"):
        raw = part[prefix + "_return"]
        excess = part[prefix + "_excess_return"]
        modeled = part[prefix + "_modeled_open_close_return"]
        n, matched, simulated = int(raw.count()), int(excess.count()), int(modeled.count())
        wins, relative_wins, modeled_wins = (int(x.gt(0).sum()) for x in (raw, excess, modeled))
        data.update({f"{prefix}_mature_n": len(part) if prefix == "d1" else int(part[prefix + "_mature"].sum()),
                     f"{prefix}_economic_n": n, f"{prefix}_mean_return": average(raw),
                     f"{prefix}_matched_benchmark_n": matched,
                     f"{prefix}_mean_matched_benchmark": average(part.loc[excess.notna(), prefix + "_benchmark_return"]),
                     f"{prefix}_mean_excess": average(excess),
                     f"{prefix}_wins": wins, f"{prefix}_win_rate": normalized_rate(wins, n),
                     f"{prefix}_excess_wins": relative_wins,
                     f"{prefix}_excess_win_rate": normalized_rate(relative_wins, matched),
                     f"{prefix}_modeled_n": simulated, f"{prefix}_modeled_mean_return": average(modeled),
                     f"{prefix}_modeled_wins": modeled_wins,
                     f"{prefix}_modeled_win_rate": normalized_rate(modeled_wins, simulated)})
    below = int(part.t5_return.lt(-.10).sum())
    data.update(t5_below_minus_10pct=below, t5_below_minus_10pct_rate=normalized_rate(below, data["t5_economic_n"]))
    for key, source in (("any", None), ("official", "V4_OFFICIAL_TOP200"),
                        ("raw_fallback", "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK")):
        hits = part.d1_top200_hit if source is None else part.loc[part.d1_top200_label_source.eq(source), "d1_top200_hit"]
        available, count = int(hits.count()), int(hits.fillna(False).sum())
        data.update({f"d1_top200_{key}_denominator": available, f"d1_top200_{key}_hits": count,
                     f"d1_top200_{key}_rate": normalized_rate(count, available)})
    return data


def outcome_phase(inputs, input_ref, output):
    import pandas as pd

    seal_path = output / "signals" / "SEAL.json"
    seal = load_seal(inputs, input_ref, seal_path)
    seal_ref = ref(seal_path)
    receipt_path = output / "FORWARD_RECEIPT.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("schema") != SCHEMA or receipt.get("signal_seal") != seal_ref:
            raise ContractError("ACT031_EXISTING_OUTCOME_IDENTITY_CHANGED")
        for artifact in receipt["artifacts"].values():
            review.checked_file(artifact["path"], artifact["sha256"])
        return receipt
    signals = {day: pd.read_parquet(read_ref(seal["daily_receipts"][day])["signals"]["path"])
               for day in seal["evaluable_days"]}
    if not signals:
        raise ContractError("ACT031_NO_EVALUABLE_SIGNAL_DAYS")
    scope = set().union(*(set(frame.ts_code) for frame in signals.values()))
    observations, prices, price_source = load_outcomes(inputs, scope)
    daily, parts = [], []
    for day in inputs["signal_dates"]:
        if day not in signals:
            daily.extend({"trade_date": day, "group": group, "status": "CANNOT_CONFIRM",
                          "detail": seal["unavailable_days"][day]} for group in GROUPS)
            continue
        part = day_forward(signals[day], day, inputs["observation_dates"], observations, prices)
        parts.append(part)
        for group in GROUPS:
            daily.append({"trade_date": day, "group": group, "status": "EVALUATED",
                          "d1_date": part.d1_date.iloc[0], "d1_top200_label_source": part.d1_top200_label_source.iloc[0],
                          "d1_benchmark_n": part.d1_benchmark_n.iloc[0],
                          **{f"t{n}_benchmark_min_daily_n": part[f"t{n}_benchmark_min_daily_n"].iloc[0] for n in (3, 5)},
                          **group_metrics(part.loc[part[group]])})
    combined = pd.concat(parts, ignore_index=True)
    confirmed = combined.loc[combined.trade_date.eq(LAST) & combined.CONFIRMED_S].copy()
    confirmed["d1_official_top200_hit"] = confirmed.d1_top200_hit.where(confirmed.d1_top200_label_source.eq("V4_OFFICIAL_TOP200"))
    confirmed["d1_official_top200_rank"] = confirmed.d1_top200_rank.where(confirmed.d1_top200_label_source.eq("V4_OFFICIAL_TOP200"))
    confirmed = confirmed.sort_values(["main_tactic", "projected_p_s", "ts_code"], ascending=[True, False, True])
    daily_frame = pd.DataFrame(daily)
    metrics = {"schema": SCHEMA, "dates": inputs["signal_dates"], "outcome_cutoff": CUTOFF,
               "signal_days_expected": len(inputs["signal_dates"]), "signal_days_evaluated": len(parts),
               "signal_days_cannot_confirm": seal["unavailable_days"],
               "groups": {group: group_metrics(combined.loc[combined[group]]) for group in GROUPS},
               "units": "decimal returns and proportions, e.g. 0.10 = 10%", "aggregation": "pooled symbol-date observations",
               "benchmarks": "Same-D eligible all-A denominator. D1 equal weight over known official raw returns. T3/T5 compound each session's equal-weight QFQ return over the same original D roster with valid consecutive closes; coverage recorded per day.",
               "economic_path": "D1 official raw close/previous close; T3/T5 D-close to exact nth-session close on one cutoff QFQ basis, complete exact bar path required.",
               "opening_proxy": "Raw D1 standard exchange/board cap estimate, yuan-cent half-up. Opening at estimated cap is excluded; exception/absence is unknown. Open-to-close measures a price change with modeled opening eligibility. Same-day market depth, closing executions and actual fills unavailable. No fees.",
               "opening_proxy_sources": CAP_RULE_SOURCES,
               "rank_fallback": "Exact-date official A-equity-family raw active quotes, change descending/symbol ascending; fallback and published official membership denominators are reported separately.",
               "model": "ACT023 43D frozen structure HGB, ACT025 routing, ACT028 latest causal repair maturity", **FLAGS}
    artifacts = {"rows": frame_atomic(output / "FORWARD_ROWS.parquet", combined),
                 "daily": frame_atomic(output / "DAILY_METRICS.csv", daily_frame),
                 "confirmed_20261120": frame_atomic(output / "CONFIRMED_20261120.csv", confirmed),
                 "metrics": json_atomic(output / "METRICS.json", metrics)}
    ready = not seal["unavailable_days"] and price_source is not None and all(row["quote_identity"] for row in observations.values())
    official_last = observations[CUTOFF]["rank_source"] == "V4_OFFICIAL_TOP200"
    receipt = {"schema": SCHEMA, "status": "FROZEN_FORWARD_COMPLETE" if ready and official_last else "FROZEN_FORWARD_PARTIAL",
               "signal_seal": seal_ref, "input": input_ref, "groups": list(GROUPS), "outcome_cutoff": CUTOFF,
               "expected_signal_days": len(inputs["signal_dates"]), "evaluated_signal_days": seal["evaluable_days"],
               "unavailable_signal_days": seal["unavailable_days"], "scored_symbol_dates": len(combined),
               "confirmed_20261120_rows": len(confirmed), "official_top200_20261123_verified": official_last,
               "outcome_quotes_and_ranks": {day: {k: v for k, v in row.items() if k not in {"quotes", "ranks"}}
                                             for day, row in observations.items()},
               "cutoff_qfq": price_source, "artifacts": artifacts, "fit_calls": {"S": 0, "B": 0, "tuning": 0, "MR": 0}, **FLAGS}
    json_atomic(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("signals", "outcomes"))
    parser.add_argument("--inputs", "--input", required=True, type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.phase == "signals" and args.models is None:
        parser.error("signals require --models and a positive --workers value")
    source = args.inputs.resolve(strict=True)
    input_ref = ref(source)
    inputs, sessions = load_inputs(source)
    if ref(source) != input_ref:
        raise ContractError("ACT031_INPUT_MOVED_DURING_READ")
    output = args.output.resolve()
    with exclusive_run(output):
        result = (signal_phase(inputs, sessions, input_ref, args.models.resolve(strict=True), output, args.workers)
                  if args.phase == "signals" else outcome_phase(inputs, input_ref, output))
    print(json.dumps({"phase": args.phase, "status": result.get("status", "SIGNALS_SEALED"),
                      "evaluable_days": result.get("evaluable_days", result.get("evaluated_signal_days")),
                      "output": str(output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
