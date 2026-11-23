"""Signed CODEX_MAC ACT-018 (499 days), aggregate-only low-turnover study.

Run with -B/PYTHONDONTWRITEBYTECODE; consumes the bound V4 reader in RAM.
No panel/stock/trade rows are persisted. Research proxies, never real fills.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act017_execution as prior

base = prior.base
SIGNED_DOC = "1lutfb93TaCO_osqKFEwG20r0PQ4knH_x1Zy4tHcVKP0"
GENERATION = "4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268"
FEATURES, PARAMS, QUARTERS = prior.FEATURES, prior.PARAMS, prior.QUARTERS
TARGET = "exec_t10_target"
METHOD = {
    "ranking": "accepted causal global s_rule_score descending, ts_code ascending; F5/B before daily TopK, never replace blocked ranks",
    "portfolio": "at most K distinct occupied single-name lots, no duplicate name; each entry min(free cash, current marked NAV/K), fees inside budget; no leverage",
    "fixed_exit": "signal D+H exchange-session close; blocked exits retry subsequent closes, no forced liquidation after asof",
    "dynamic_exit": "observe close C<White OR close/running observed-close peak-1<=-8%; peak starts at buy price; signal sells next exchange-session open, T+1 settlement; blocked signals retry opens",
    "dynamic_cap": "20th market session including buy session (buy+19) close predetermined; blocked cap exits retry closes; no future-asof forced fills",
    "opening_sell_proxy": "ACT015 exit_status with open substituted for OHLC, finite positive open validity and synthetic unit volume; prior-close/native down limit and tradeability unchanged; no same-session volume/high/low/close consulted",
    "execution_status_ambiguity": "accepted opening buy gate uses same-session positive daily volume and tradeable_basic; these are conservative research proxies, intraday status timestamp/PIT CANNOT_CONFIRM",
    "execution": "ACT017/015 conservative estimated gates, not exact exchange auction or real fills; tail D-close decision/fill counterfactual, never future-ranked",
    "fees": "15bp each side net vs actual same-gates zero-fee run; drag gross-minus-net compounded cumulative return in percentage points",
    "turnover": "annualized sum of actual buy+sale notionals / previous close NAV *252/observed sessions; two-sided, not halved; also reported halved",
    "holding": "realized market sessions inclusive of buy/sale day; elapsed session gaps also reported; residual lots excluded",
    "marking": "valid observed closes, otherwise last mark retained and stale count reported; all occupied lots consume capacity; buys near asof retained as residual",
    "benchmark": "accepted ACT015 external gross all-A EW close-to-close, fully invested not exposure matched; first evaluation return zero; regimes same accepted lagged 60-session rule",
    "target": "exact gross T1 open to D+10 close less same signal-D all-A EW exact endpoint return >=5%, full observed-close path running MDD from buy >=-8%; ACT017 entry/exact exit eligibility",
    "fit": "9 chronological fixed HGBClassifier quarters 2024Q4..2026Q4, prior 4 completed calendar quarters, target date strictly before test quarter; shared K/repair purge TRAIN only; fixed accepted features/params, TRAIN class balance; no tuning",
    "group_partition": "accepted ACT017 full-held-quarter observable structural K/repair IDs define retrospective research partition and TRAIN-only purge; fit membership is not a deployable as-of-quarter-start partition",
}


class Act018Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Arm:
    experiment: str
    pool: str
    top: int
    horizon: int
    clock: str
    f5: bool = False
    dynamic: bool = False
    model: bool = False

    @property
    def name(self) -> str:
        return f"{self.experiment}_{self.pool}_TOP{self.top}_H{self.horizon}_{self.clock}_F5{int(self.f5)}{'_DYNAMIC' if self.dynamic else ''}"


def arms() -> list[Arm]:
    out = [Arm("E1", pool, top, h, clock, f5)
           for pool in ("hard", "hard_b") for top in (3, 5, 20)
           for h in (10, 15) for clock in ("close", "open") for f5 in (False, True)]
    out += [Arm("E2", pool, 5, h, "open", dynamic=dynamic)
            for pool in ("hard", "hard_b") for h, dynamic in ((20, True), (3, False), (10, False))]
    out += [Arm("E3", "hard", top, 10, "open", f5, model=True)
            for top in (3, 5) for f5 in (False, True)]
    return out


def open_exit_status(book: Any, day: int, code: int) -> tuple[bool, str]:
    """Conservative point-in-time reuse of accepted sell proxy; no future OHLC."""
    import numpy as np
    opening = book.values["open"][day, code]
    values = {key: np.array([[value[day, code]]]) for key, value in book.values.items()
              if key in {"tradeable_basic", "limit_down_price", "limit_down_approx", "pre_close"}}
    values.update({key: np.array([[opening]]) for key in ("open", "high", "low", "close")})
    values["vol"] = np.ones((1, 1))
    view = SimpleNamespace(values=values, codes=[book.codes[code]],
                           valid=np.array([[np.isfinite(opening) and opening > 0]]))
    return base.exit_status(view, 0, 0)


def simulate(book: Any, signals: dict[int, list[int]], arm: Arm, fee: float,
             start: str = base.START, end: str = base.END) -> tuple[Any, dict[str, Any]]:
    """Self-financing K-slot portfolio; signals contain only frozen daily TopK."""
    import numpy as np
    import pandas as pd
    days = [i for i, d in enumerate(book.dates) if start <= d <= end]
    if not days:
        raise Act018Error("EMPTY_EVALUATION")
    cash, previous_nav = 1., 1.
    holdings, rows = [], []
    stats = dict(buys=0, sales=0, attempts=0, buy_fees=0., sell_fees=0.,
                 stale_mark_sessions=0, delayed_exit_attempts=0, dynamic_white_unknown=0)
    blocked = defaultdict(int)
    exit_reasons = defaultdict(int)
    realized_inclusive, realized_elapsed = [], []
    for day in days:
        events = dict(attempts=0, fills=0, sales=0, buy_notional=0., sell_notional=0., fees=0.,
                      realized_hold_sessions_sum=0, realized_elapsed_sessions_sum=0)
        def sell(position: dict[str, Any], clock: str) -> bool:
            nonlocal cash
            if day <= position["buy_day"]:  # A-share T+1 share settlement
                return False
            allowed, reason = (open_exit_status(book, day, position["code"]) if clock == "open"
                               else base.exit_status(book, day, position["code"]))
            if not allowed:
                blocked["exit_" + reason] += 1
                stats["delayed_exit_attempts"] += 1
                return False
            price = book.values[clock][day, position["code"]]
            if not np.isfinite(price) or price <= 0:
                raise Act018Error("GATE_ALLOWED_INVALID_EXIT")
            notional = position["shares"] * price
            cash += notional * (1-fee)
            events["sell_notional"] += notional
            events["fees"] += notional * fee
            events["sales"] += 1
            stats["sales"] += 1
            stats["sell_fees"] += notional * fee
            hold, elapsed = day-position["buy_day"]+1, day-position["buy_day"]
            realized_inclusive.append(hold)
            realized_elapsed.append(elapsed)
            events["realized_hold_sessions_sum"] += hold
            events["realized_elapsed_sessions_sum"] += elapsed
            exit_reasons[position.get("reason", "fixed")] += 1
            return True

        # Next-open stop orders predate this session's OHLC and entry decisions.
        holdings = [p for p in holdings if not (arm.dynamic and p.get("pending", day+1) <= day and sell(p, "open"))]
        # Existing holdings marked at today's open before new opening budgets.
        for p in holdings:
            opening = book.values["open"][day, p["code"]]
            if prior.raw_open_allowed(book, day, p["code"]):
                p["mark"] = float(opening)

        def enter(signal_day: int, clock: str) -> None:
            nonlocal cash
            if signal_day < days[0]:
                return
            sleeve_budget = (cash + sum(p["shares"]*p["mark"] for p in holdings))/arm.top
            # Never backfill a blocked/occupied rank with rank K+1.
            for code in list(dict.fromkeys(signals.get(signal_day, [])))[:arm.top]:
                events["attempts"] += 1
                stats["attempts"] += 1
                if len(holdings) >= arm.top or any(p["code"] == code for p in holdings):
                    blocked["capacity_or_occupied"] += 1
                    continue
                allowed, reason = (base.entry_status(book, day, code) if clock == "open"
                                   else prior.tail_close_allowed(book, day, code))
                price = book.values[clock][day, code]
                if not allowed or not np.isfinite(price) or price <= 0:
                    blocked["entry_"+reason] += 1
                    continue
                budget = min(cash, sleeve_budget)
                if budget <= 1e-12:
                    blocked["no_cash"] += 1
                    continue
                notional = budget/(1+fee)
                cash -= budget
                events["buy_notional"] += notional
                events["fees"] += notional*fee
                events["fills"] += 1
                stats["buys"] += 1
                stats["buy_fees"] += notional*fee
                holdings.append(dict(code=code, shares=notional/price, mark=float(price),
                                     buy_day=day, peak=float(price),
                                     target=day+19 if arm.dynamic else signal_day+arm.horizon))
        if arm.clock == "open":
            enter(day-1, "open")
        retained = []
        for p in holdings:
            code = p["code"]
            close = book.values["close"][day, code]
            if book.valid[day, code] and np.isfinite(close) and close > 0:
                p["mark"] = float(close)
                p["peak"] = max(p["peak"], float(close))
                if arm.dynamic and "pending" not in p:
                    white = book.values.get("zge_white_line")
                    known = white is not None and np.isfinite(white[day, code]) and white[day, code] > 0
                    if not known:
                        stats["dynamic_white_unknown"] += 1
                    below = known and close < white[day, code]
                    trailing = close/p["peak"]-1 <= -.08
                    if below or trailing:
                        p.update(pending=day+1, reason="white" if below else "trailing8")
            else:
                stats["stale_mark_sessions"] += 1
            if day >= p["target"]:
                p["reason"] = "cap20" if arm.dynamic else "fixed"
                if sell(p, "close"):
                    continue
            retained.append(p)
        holdings = retained
        if arm.clock == "close":
            enter(day, "close")
        invested = sum(p["shares"]*p["mark"] for p in holdings)
        nav = cash+invested
        if not np.isfinite(nav) or nav <= 0 or cash < -1e-10 or len(holdings) > arm.top or len({p["code"] for p in holdings}) != len(holdings):
            raise Act018Error("SELF_FINANCING_OR_CAPACITY_INVALID")
        rows.append(dict(trade_date=book.dates[day], nav=nav, cash=cash, invested=invested,
                         holding_count=len(holdings), gross_exposure=invested/nav,
                         turnover=(events["buy_notional"]+events["sell_notional"])/previous_nav,
                         fee_nav_fraction=events["fees"]/previous_nav, **events))
        previous_nav = nav
    stats.update(blocked=dict(blocked), exit_reasons=dict(exit_reasons), residual_positions=len(holdings),
                 residual_market_value=sum(p["shares"]*p["mark"] for p in holdings),
                 avg_realized_hold_sessions=float(np.mean(realized_inclusive)) if realized_inclusive else None,
                 avg_realized_elapsed_sessions=float(np.mean(realized_elapsed)) if realized_elapsed else None,
                 max_holding=max(r["holding_count"] for r in rows), real_fills_confirmed=False)
    return pd.DataFrame(rows), stats


def attach_targets(candidates: Any, book: Any) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    out = candidates.copy()
    close, opening = book.values["close"], book.values["open"]
    benchmark = np.full(len(book.dates), np.nan)
    for day in range(len(book.dates)-10):
        valid = book.valid[day+1] & book.valid[day+10] & np.isfinite(opening[day+1]) & (opening[day+1] > 0)
        if valid.any():
            benchmark[day] = np.mean(close[day+10, valid]/opening[day+1, valid]-1)
    target = np.full(len(out), np.nan)
    reasons = defaultdict(int)
    for i, (day, code) in enumerate(zip(out.session.astype(int), out.code_index.astype(int))):
        if day+10 >= len(book.dates):
            reasons["immature"] += 1
            continue
        if not base.entry_status(book, day+1, code)[0] or not base.exit_status(book, day+10, code)[0]:
            reasons["entry_or_exit_blocked"] += 1
            continue
        if not book.valid[day+1:day+11, code].all() or not np.isfinite(benchmark[day]):
            reasons["incomplete_path_or_benchmark"] += 1
            continue
        path = np.r_[opening[day+1, code], close[day+1:day+11, code]]
        mdd = np.min(path/np.maximum.accumulate(path)-1)
        excess = path[-1]/path[0]-1-benchmark[day]
        target[i] = float(excess >= .05 and mdd >= -.08)
        reasons["eligible"] += 1
    out[TARGET] = target
    out[TARGET+"_date"] = [book.dates[int(d)+10] if int(d)+10 < len(book.dates) else "" for d in out.session]
    return out, dict(known=int(np.isfinite(target).sum()), positive=int(np.nansum(target)),
                     eligibility=dict(reasons), target=METHOD["target"], maturity="exact target date strictly before held quarter")


def model_contract(binding: dict[str, Any]) -> dict[str, Any]:
    return dict(signed_doc=SIGNED_DOC, binding=binding, features=list(FEATURES), params=PARAMS,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                dependencies={Path(m.__file__).name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                              for m in (base, prior, base.a9, base.a9b, base.v12)}, method=METHOD)


def fit_models(candidates: Any, binding: dict[str, Any], output: Path, progress: Callable | None = None,
               resume: bool = False, estimator_factory: Callable | None = None) -> tuple[Any, dict[str, Any]]:
    import joblib
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    out, reports = candidates.copy(), []
    out["t10_score"] = np.nan
    contract = model_contract(binding)
    for q in QUARTERS:
        train, predict, report = prior.quarter_masks(out, q, TARGET)
        y = out.loc[train, TARGET].to_numpy(dtype=int)
        report.update(kind="exec_t10", fits=0, reused=False, target=TARGET,
                      train_positive=int(y.sum()), train_negative=int(len(y)-y.sum()),
                      class_weight_positive=float(len(y)/(2*(y == 1).sum())) if (y == 1).any() else None,
                      class_weight_negative=float(len(y)/(2*(y == 0).sum())) if (y == 0).any() else None)
        path = output/f"exec_t10_{q}.joblib"
        if path.exists():
            if not resume:
                raise Act018Error("CHECKPOINT_EXISTS_USE_RESUME")
            stored = joblib.load(path)
            expected = {k: v for k, v in report.items() if k not in {"fits", "reused"}}
            observed = {k: v for k, v in stored["fit"].items() if k not in {"fits", "reused", "status"}}
            if stored.get("contract") != contract or expected != observed:
                raise Act018Error("CHECKPOINT_CONTRACT_OR_POPULATION_MISMATCH")
            model = stored["model"]
            report.update(reused=True, status="REUSED")
        else:
            if not predict.any() or len(np.unique(y)) != 2:
                raise Act018Error(f"INSUFFICIENT_FIXED_QUARTER:{q}")
            model = estimator_factory() if estimator_factory else HistGradientBoostingClassifier(**PARAMS)
            x = out.loc[train, list(FEATURES)].to_numpy(dtype=float, copy=True)
            x[~np.isfinite(x)] = np.nan
            weights = np.where(y == 0, len(y)/(2*(y == 0).sum()), len(y)/(2*(y == 1).sum()))
            if progress:
                progress("model", "FIT_STARTED", report)
            model.fit(x, y, sample_weight=weights)
            report.update(fits=1, status="FIT_COMPLETE")
            tmp = path.with_suffix(".joblib.tmp")
            joblib.dump(dict(model=model, contract=contract, fit=report), tmp)
            tmp.replace(path)
        x = out.loc[predict, list(FEATURES)].to_numpy(dtype=float, copy=True)
        x[~np.isfinite(x)] = np.nan
        scores = model.predict_proba(x)[:, 1]
        reloaded = joblib.load(path)["model"]
        if not np.array_equal(scores, reloaded.predict_proba(x)[:, 1]):
            raise Act018Error("MODEL_RELOAD_PREDICTION_MISMATCH")
        out.loc[predict, "t10_score"] = scores
        reports.append({**report, "model_file":path.name,
                        "model_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                        "reload_prediction_check":"PASS"})
        accounting = dict(S=0, search=0, actual_fits=sum(r["fits"] for r in reports),
                          reused=sum(r["reused"] for r in reports), quarters=reports)
        base._write_json(output/"fit_accounting.json", accounting)
        if progress:
            progress("model", "QUARTER_COMPLETE", reports[-1])
    return out, accounting


def segment_metrics(daily: Any) -> Any:
    import numpy as np
    import pandas as pd
    metrics = base.aggregate_metrics(daily)
    extra = []
    for (strategy, horizon, mode), group in daily.groupby(["strategy", "horizon", "mode"], sort=True):
        segments = [("full", "ALL", group)]
        segments += [("quarter", str(k), p) for k, p in group.groupby(group.trade_date.map(base.quarter))]
        segments += [("regime", str(k), p) for k, p in group.groupby("regime")]
        for kind, key, part in segments:
            sales = int(part.sales.sum())
            extra.append(dict(strategy=strategy, horizon=horizon, mode=mode, segment_kind=kind, segment=key,
                actual_buys=int(part.fills.sum()), actual_sales=sales,
                annualized_actual_turnover_two_sided=float(part.turnover.mean()*252),
                annualized_actual_turnover_one_way=float(part.turnover.mean()*126),
                actual_fee_pp_initial_nav=float(part.fees.sum()*100),
                fee_nav_fraction_sum_pp=float(part.fee_nav_fraction.sum()*100),
                avg_realized_hold_sessions=float(part.realized_hold_sessions_sum.sum()/sales) if sales else None))
    metrics = metrics.merge(pd.DataFrame(extra), on=["strategy", "horizon", "mode", "segment_kind", "segment"], validate="one_to_one")
    pairs = metrics.loc[metrics["mode"].eq("ZERO"), ["strategy", "horizon", "segment_kind", "segment", "absolute_return"]].rename(columns={"absolute_return":"paired_zero_absolute_return"})
    metrics = metrics.merge(pairs, on=["strategy", "horizon", "segment_kind", "segment"], validate="many_to_one")
    metrics["paired_fee_drag_pp"] = (metrics.paired_zero_absolute_return-metrics.absolute_return)*100
    metrics["absolute_minus_benchmark_pp"] = (metrics.absolute_return-metrics.benchmark_return)*100
    return metrics


def run_once(data_root: Path, output_dir: Path, resume: bool = False) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import resource
    import shutil
    output_dir, data_root = Path(output_dir).resolve(), Path(data_root).resolve()
    if output_dir == data_root or data_root in output_dir.parents or output_dir in data_root.parents:
        raise Act018Error("OUTPUT_MUST_PRESERVE_AUTHORITY")
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir/"run_summary.json").exists() and not resume:
        raise Act018Error("EXISTING_RUN_REQUIRES_RESUME")
    if shutil.disk_usage(output_dir).free < 2*1024**3:
        raise Act018Error("INSUFFICIENT_WRITE_BUDGET_HEADROOM")
    plan = arms()
    summary = dict(schema="pft_act018_low_turnover.v1", signed_doc=SIGNED_DOC, status="RUNNING",
                   evaluation_window=[base.START, base.END], expected_sessions=499,
                   methodology=METHOD, arms=[dict(name=a.name, **asdict(a)) for a in plan],
                   fit_plan=dict(classifier=9, search=0), row_export_files=0,
                   full_panel_written=False, write_budget_bytes=1024**3, **base.FLAGS)
    def progress(stage: str, status: str, details: dict) -> None:
        base.a9._append_progress(output_dir/"run_progress.jsonl", stage, status, details)
    base._write_json(output_dir/"run_summary.json", summary)
    try:
        with base.v12.bind_current_panels(data_root) as (panel_path, source, recheck):
            binding = base.a9._assert_bound_source(source)
            if binding.get("generation_id") != GENERATION or binding.get("asof_date") != base.END or binding.get("price_basis") != "QFQ_ASOF" or binding.get("volume_basis") != "QFQ_EVENT_VOLUME":
                raise Act018Error("SIGNED_V4_BINDING_MISMATCH")
            summary.update(binding=binding, model_contract=model_contract(binding))
            raw, read = base.read_projected(panel_path)
            book = base.PriceBook.from_frame(raw)
            # Add only the already projected authoritative White column to RAM book.
            white = np.full(book.valid.shape, np.nan)
            di, ci = {d:i for i,d in enumerate(book.dates)}, {c:i for i,c in enumerate(book.codes)}
            white[raw.trade_date.map(di).to_numpy(dtype=int), raw.ts_code.map(ci).to_numpy(dtype=int)] = pd.to_numeric(raw.zge_white_line, errors="coerce").to_numpy()
            book.values["zge_white_line"] = white
            dates = [d for d in book.dates if base.START <= d <= base.END]
            if len(dates) != 499 or dates[0] != base.START or dates[-1] != base.END:
                raise Act018Error("EXPECTED_499_EVALUATION_DATES")
            candidates, meta = base.build_candidates(raw, book, read["formula_prep_start"], progress)
            del raw
            recheck()
            summary.update(read=read, candidate_rows=len(candidates))
            frames, reports = [], []
            def evaluate(arm: Arm) -> None:
                signals = prior.ranked_signals(candidates, "t10_score" if arm.model else "s_rule_score", arm.top, arm.f5, arm.pool == "hard_b")
                for mode, fee in (("NET", .0015), ("ZERO", 0.)):
                    daily, stats = simulate(book, signals, arm, fee)
                    daily = daily.assign(strategy=arm.name, horizon=arm.horizon, mode=mode)
                    daily["daily_return"] = daily.nav.pct_change().fillna(daily.nav.iloc[0]-1)
                    benchmark = daily.trade_date.map(meta["all_a_d_returns"]).astype(float)
                    benchmark.iloc[0] = 0.
                    if not np.isfinite(benchmark).all():
                        raise Act018Error("MISSING_ACCEPTED_BENCHMARK")
                    daily["benchmark_daily_return"] = benchmark
                    daily["benchmark_nav"] = (1+benchmark).cumprod()
                    daily["relative_nav"] = daily.nav/daily.benchmark_nav
                    daily["regime"] = daily.trade_date.map(meta["regimes"])
                    frames.append(daily)
                    reports.append(dict(strategy=arm.name, mode=mode, **stats))
                progress("portfolio", "ARM_COMPLETE", dict(arm=arm.name))
            for arm in plan:
                if not arm.model:
                    evaluate(arm)
            candidates, maturity = attach_targets(candidates, book)
            base._write_json(output_dir/"target_maturity_ledger.json", maturity)
            candidates, fit_report = fit_models(candidates, binding, output_dir, progress, resume)
            summary.update(target_maturity=maturity, fit_accounting=fit_report)
            for arm in plan:
                if arm.model:
                    evaluate(arm)
            daily = pd.concat(frames, ignore_index=True)
            metrics = segment_metrics(daily)
            daily.to_csv(output_dir/"daily_portfolio_nav.csv", index=False)
            metrics.to_csv(output_dir/"quarter_regime_metrics.csv", index=False)
            metrics.loc[metrics["mode"].eq("NET")].to_csv(output_dir/"paired_fee_metrics.csv", index=False)
            base._write_json(output_dir/"execution_accounting.json", reports)
            recheck()
            size = sum(p.stat().st_size for p in output_dir.iterdir() if p.is_file())
            if size > 1024**3:
                raise Act018Error("WRITE_BUDGET_EXCEEDED")
            summary.update(status="COMPLETED_ESTIMATED_EXECUTION_RESEARCH", metric_rows=len(metrics),
                           daily_aggregate_rows=len(daily), arm_count=len(plan), output_bytes=size,
                           peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           exact_limit_prices_and_real_fills="CANNOT_CONFIRM")
            base._write_json(output_dir/"run_summary.json", summary)
            progress("run", "COMPLETED", dict(actual_fits=fit_report["actual_fits"], reused=fit_report["reused"]))
            return summary
    except Exception as exc:
        summary.update(status="FAILED", error=f"{type(exc).__name__}:{exc}")
        base._write_json(output_dir/"run_summary.json", summary)
        progress("run", "FAILED", dict(error=summary["error"]))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true", help="Reuse exact-contract completed quarter weights, fit missing quarters only")
    args = parser.parse_args(argv)
    run_once(args.data_root, args.output_dir, args.resume)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
