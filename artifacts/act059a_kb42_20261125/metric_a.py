"""ACT-059A Task A, additive D−1 metrics for the frozen ACT-058A Reader roster."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time

import numpy as np
import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
PREV = ROOT.parent / "act058a_hidden_kb42_20261125"
SPEC = importlib.util.spec_from_file_location("act058a_compute", PREV / "compute.py")
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)

BODY_METRICS = tuple(
    f"bear_body_{measure}_{size}"
    for size in (3, 5) for measure in ("count", "longest_run", "trailing_run")
)
OWN_METRICS = tuple(f"volume_Dm{k}_vs_own_prev20" for k in (1, 2, 3))
COMMON_METRICS = tuple(f"volume_Dm{k}_vs_common_base20" for k in (1, 2, 3))
NEW_METRICS = (*BODY_METRICS, *OWN_METRICS, *COMMON_METRICS)
CENSORS = tuple(f"bear_body_run_left_censored_{size}" for size in (3, 5))
OK = "OK"
VOLUME_EPS = 1e-12
OLD_METRICS = tuple(metric.replace("bear_body", "down_close") for metric in BODY_METRICS) + (
    "volume_mean3_vs_prev20",
)


def metric_period(metric):
    if metric in BODY_METRICS:
        return f"D-{metric[-1]}..D-1"
    k = int(metric.split("_")[1][-1])
    first, last = (k + 20, k + 1) if metric in OWN_METRICS else (23, 4)
    return f"D-{k}/mean(D-{first}..D-{last})"


def missing_reasons(stock, anchors, bars):
    """Keep ACT-058A validity and explain the first failing prerequisite category."""
    ordinals = anchors[:, None] + OLD.DS
    rows = OLD.lookup_rows(stock, ordinals)
    safe = np.maximum(rows, 0)
    categories = np.full(rows.shape, "D_MINUS_1_BASIS_NONPOSITIVE_OR_NONFINITE_OHLCV", dtype=object)
    categories[stock.basis[safe] != stock.basis[safe[:, -1], None]] = "PRICE_BASIS_ALIAS_DISCONTINUITY"
    categories[~stock.valid[safe]] = "READER_BAR_WITHOUT_VALID_ACTIVITY_OR_BASIS"
    categories[rows < 0] = "NO_READER_BAR_ON_SESSION"
    categories[ordinals < 0] = "LEFT_CENSORED_BY_CALENDAR"
    categories[np.isfinite(bars[:, :, 3])] = OK
    d1_missing = categories[:, -1] != OK
    categories[d1_missing] = np.char.add("D_MINUS_1_", categories[d1_missing, -1].astype(str))[:, None]
    return categories


def select_reason(categories):
    """Use the earliest affected required exchange slot as the primary reason."""
    bad = categories != OK
    return categories[np.arange(len(categories)), bad.argmax(axis=1)]


def new_features(stock, anchors):
    """Compute exactly 12 features and support fields, with RangeIndex in input order."""
    anchors = np.asarray(anchors, dtype=np.int64)
    if anchors.ndim != 1:
        raise ValueError("anchors must be a one-dimensional sequence of exchange session ordinals")
    if not len(stock.positions):
        absent = pd.DataFrame(np.nan, index=pd.RangeIndex(len(anchors)), columns=NEW_METRICS)
        for metric in NEW_METRICS:
            absent[f"{metric}_reason"] = "D_MINUS_1_NO_READER_BAR_ON_SESSION"
        for flag in CENSORS:
            absent[flag] = pd.array([pd.NA] * len(anchors), dtype="boolean")
        return absent

    bars = OLD.basis_windows(stock, anchors)
    categories = missing_reasons(stock, anchors, bars)
    out, reasons, flags = {}, {}, {}
    o, c, v = (bars[:, :, k] for k in (0, 3, 4))
    for size in (3, 5):
        bear = c[:, -size:] < o[:, -size:]
        category = select_reason(categories[:, -size:])
        valid = category == OK
        trailing = np.zeros(len(anchors), dtype=int)
        longest = np.zeros(len(anchors), dtype=int)
        for is_bear in bear.T:
            trailing = (trailing + 1) * is_bear
            longest = np.maximum(longest, trailing)
        for name, value in (("count", bear.sum(axis=1)), ("longest_run", longest), ("trailing_run", trailing)):
            metric = f"bear_body_{name}_{size}"
            out[metric] = np.where(valid, value, np.nan)
            reasons[f"{metric}_reason"] = category
        flags[f"bear_body_run_left_censored_{size}"] = pd.array(
            np.where(valid, bear.all(axis=1).astype(object), None), dtype="boolean"
        )

    for names, shared in ((OWN_METRICS, False), (COMMON_METRICS, True)):
        for k, metric in enumerate(names, start=1):
            end = 3 if shared else k
            den_window = slice(-end - 20, -end)
            denominator = v[:, den_window].mean(axis=1)
            category = select_reason(np.column_stack((categories[:, den_window], categories[:, -k])))
            ratio = OLD.ratio(v[:, -k], denominator)
            category[(category == OK) & ~np.isfinite(ratio)] = "NONPOSITIVE_OR_NONFINITE_DENOMINATOR_OR_RATIO"
            out[metric] = np.where(category == OK, ratio, np.nan)
            reasons[f"{metric}_reason"] = category

    assert tuple(out) == NEW_METRICS
    return pd.DataFrame({**out, **reasons, **flags})


def session_diagnostics(stock, anchors, calendar, features):
    bars = OLD.basis_windows(stock, anchors)
    o, c = bars[:, :, 0], bars[:, :, 3]
    diag, cases = {}, {}
    for size in (3, 5):
        body_open, body_close, prior_close = o[:, -size:], c[:, -size:], c[:, -size-1:-1]
        jointly_valid = np.isfinite(body_open) & np.isfinite(body_close) & np.isfinite(prior_close)
        was_bear = body_close < body_open
        was_down = body_close < prior_close
        cases_in_window = {
            "eligible_for_both_definitions": jointly_valid,
            "bear_body_without_down_close": jointly_valid & was_bear & ~was_down,
            "down_close_without_bear_body": jointly_valid & was_down & ~was_bear,
            "equal_open_close": np.isfinite(body_open) & (body_close == body_open),
        }
        for name, mask in cases_in_window.items():
            diag[f"{name}_{size}"] = mask.sum(axis=1)
            if name == "eligible_for_both_definitions" or not mask.any():
                continue
            row, col = np.argwhere(mask)[0]
            at = anchors[row] - size + col
            cases[f"{name}_{size}"] = {
                "security_id": stock.code, "D": str(calendar[anchors[row]]),
                "bar_date": str(calendar[at]), "offset": int(col - size),
                "O": float(body_open[row, col]), "C": float(body_close[row, col]),
                "Cprev": float(prior_close[row, col]) if np.isfinite(prior_close[row, col]) else None,
            }
        censored = features[f"bear_body_run_left_censored_{size}"].fillna(False).to_numpy()
        if censored.any():
            for name, row in (("first", np.flatnonzero(censored)[0]), ("last", np.flatnonzero(censored)[-1])):
                cases[f"{name}_left_censored_{size}"] = {
                    "security_id": stock.code, "D": str(calendar[anchors[row]]),
                    "prior_session_dates": calendar[anchors[row]-size:anchors[row]].tolist(),
                    "observed_run": size, "left_censored": True,
                }
        reason = features[f"bear_body_count_{size}_reason"].to_numpy()
        gap = np.char.find(reason.astype(str), "NO_READER_BAR_ON_SESSION") >= 0
        if gap.any():
            row = np.flatnonzero(gap)[0]
            slots = np.arange(anchors[row] - size, anchors[row])
            absent = OLD.lookup_rows(stock, slots) < 0
            cases[f"first_gap_{size}"] = {
                "security_id": stock.code, "D": str(calendar[anchors[row]]),
                "missing_dates": calendar[slots[absent & (slots >= 0)]].tolist(),
                "reason": reason[row], "count_longest_trailing": [None] * 3,
            }
    return pd.DataFrame(diag), cases


def gather(cfg, frame, calendar, events, signals, prof, prior, verify_times):
    canaries_by_code = {}
    for row in prior["physical_prefix_canaries"]:
        canaries_by_code.setdefault(row["security_id"], []).append(row)
    profiles = prof.set_index("security_id")["archetype"].to_dict()
    assembled, samples, examples, controls_by_code = [], [], {}, {}
    for code, daily in frame.groupby("canonical", sort=True):
        stock = OLD.Stock(code, daily, cfg["events"][code], calendar)
        e = events.loc[events.security_id.eq(code)].sort_values("exchange_session_ordinal")
        s = signals.loc[signals.security_id.eq(code)]
        event_pos = e.exchange_session_ordinal.to_numpy()
        reverse = s[s.reverse_independent]
        assert np.array_equal(calendar[event_pos].astype(int), e.D)
        assert np.array_equal(calendar[s.exchange_session_ordinal].astype(int), s.D)
        assert np.array_equal(OLD.lookup_rows(stock, reverse.exchange_session_ordinal.to_numpy()),
                              reverse.event_slice_end_bar)
        controls = OLD.ordinary(stock, event_pos)
        controls_by_code[code] = len(controls)
        anchors = np.sort(np.r_[event_pos, controls])
        assert len(anchors) == len(np.unique(anchors))
        added = new_features(stock, anchors)
        original = OLD.features(stock, anchors).loc[:, list(OLD_METRICS)]
        diag, stock_cases = session_diagnostics(stock, anchors, calendar, added)
        for name, case in stock_cases.items():
            edge = max if name.startswith("last_") else min
            if name in examples:
                case = edge((examples[name], case), key=lambda item: (item["D"], item["security_id"]))
            examples[name] = case
        part = pd.concat((added, original, diag), axis=1).set_axis(anchors)
        part["D_ordinal"], part["D"] = anchors, calendar[anchors]
        part["year"], part["security_id"] = calendar[anchors].astype(int) // 10000, code
        part["group"], part["archetype"] = "ordinary", profiles[code]
        part.loc[event_pos, "group"] = np.where(e.hidden, "hidden", "visible")
        part["forward_hit"] = np.isin(anchors, s.loc[s.forward_any, "exchange_session_ordinal"])
        assembled.append(part)

        t, cpu = perf_counter(), process_time()
        for earlier in canaries_by_code.get(code, []):
            at = int(np.searchsorted(calendar, earlier["D"]))
            prefix = daily[daily.trade_date.lt(calendar[at])].copy()
            assert not prefix.empty and prefix.trade_date.max() == earlier["last_prefix_reader_day"]
            assert calendar[at] == earlier["D"] and part.at[at, "group"] == earlier["group"]
            prefix_stock = OLD.Stock(code, prefix, cfg["events"][code], calendar)
            check = new_features(prefix_stock, [at])
            pd.testing.assert_frame_equal(check, part.loc[[at], check.columns].reset_index(drop=True),
                                          check_exact=True)
            samples.append({**earlier, "features_equal_including_nan": len(NEW_METRICS),
                            "reason_and_censor_support_equal": True})
        verify_times["wall"] += perf_counter() - t
        verify_times["cpu"] += process_time() - cpu

    study = pd.concat(assembled, ignore_index=True)
    assert controls_by_code == prior["ordinary_by_stock"]
    assert set(profiles) == set(controls_by_code) and len(profiles) == 42
    keys = ["security_id", "D"]
    assert not study.duplicated(keys).any()
    rebuilt_events = study.loc[~study.group.eq("ordinary"), [*keys,"D_ordinal","group","archetype"]].copy()
    rebuilt_events["D"] = rebuilt_events.D.astype(int)
    rebuilt_events["hidden"] = rebuilt_events.group.eq("hidden")
    rebuilt_events = rebuilt_events.rename(columns={"D_ordinal": "exchange_session_ordinal"})
    event_cols = [*keys, "exchange_session_ordinal", "hidden", "archetype"]
    pd.testing.assert_frame_equal(rebuilt_events[event_cols].sort_values(keys, ignore_index=True),
                                  events[event_cols].sort_values(keys, ignore_index=True), check_dtype=False)
    assert study.groupby(["archetype","group"]).size().unstack(fill_value=0).to_dict("index") == prior["group_by_archetype"]
    actual_forward = study.loc[study.group.eq("ordinary")].groupby("archetype").forward_hit.sum().to_dict()
    assert actual_forward == prior["ordinary_forward_hits_by_archetype"]
    sample_keys = ("security_id", "D", "case", "group", "last_prefix_reader_day")
    key_sequence = lambda seq: [tuple(r[c] for c in sample_keys) for r in seq]
    assert len(samples) == 40 and key_sequence(samples) == key_sequence(prior["physical_prefix_canaries"])
    return study, samples, examples, controls_by_code


def check_original(study, original_csv):
    old_csv = pd.read_csv(original_csv)
    original = old_csv.loc[old_csv.section.eq("descriptive") & old_csv.metric.isin(OLD_METRICS)]
    rebuilt = pd.DataFrame(OLD.summarize_descriptive(study, OLD_METRICS))
    cols = ["archetype", "group", "metric", "total_n", "valid_n", "missing_n", "mean", "q25", "median", "q75"]
    assert len(original) == len(rebuilt) == 105
    order = ["archetype", "group", "metric"]
    pd.testing.assert_frame_equal(original[cols].sort_values(order, ignore_index=True),
                                  rebuilt[cols].sort_values(order, ignore_index=True),
                                  check_dtype=False, rtol=1e-11, atol=1e-12)
    shared = study[list(COMMON_METRICS)].to_numpy(float)
    old_ratio = study.volume_mean3_vs_prev20.to_numpy(float)
    all_valid = np.isfinite(shared).all(axis=1)
    assert np.array_equal(all_valid, np.isfinite(old_ratio))
    shared_mean = shared.mean(axis=1)
    np.testing.assert_allclose(shared_mean[all_valid], old_ratio[all_valid], rtol=VOLUME_EPS, atol=VOLUME_EPS)
    own = study[list(OWN_METRICS)].to_numpy(float)
    own_mean = own.mean(axis=1)
    jointly_valid = np.isfinite(own_mean) & all_valid
    max_gap = np.nanmax(np.abs(shared_mean - old_ratio))
    different = jointly_valid & ~np.isclose(own_mean, old_ratio, rtol=VOLUME_EPS, atol=VOLUME_EPS)
    study["common_old_joint_valid"] = all_valid
    study["own_old_joint_valid"] = jointly_valid
    study["own_old_mean_different"] = different
    study["own_three_leg_max"] = np.nan
    own_valid = np.isfinite(own).all(axis=1)
    maximum = own[own_valid].max(axis=1, keepdims=True)
    tied = (own[own_valid] == maximum).sum(axis=1) > 1
    study.loc[own_valid, "own_three_leg_max"] = np.where(tied, 0, own[own_valid].argmax(axis=1) + 1)
    study["common_any_gt1_old_le1"] = all_valid & (shared > 1).any(axis=1) & (old_ratio <= 1)
    first = int(np.flatnonzero(different)[0])
    case = study.iloc[first]
    numerics = {
        "security_id": case.security_id, "D": case.D, "old": float(old_ratio[first]),
        "common_mean": float(shared_mean[first]), "own_mean": float(own_mean[first]),
        "common_by_Dm1_Dm2_Dm3": shared[first].tolist(), "own_by_Dm1_Dm2_Dm3": own[first].tolist(),
    }
    for metric in NEW_METRICS:
        assert np.array_equal(np.isfinite(study[metric]), study[f"{metric}_reason"].eq(OK))
    return {
        "legacy_descriptive_cells_matched": len(rebuilt), "jointly_valid_common_and_old": int(all_valid.sum()),
        "jointly_valid_own_and_old": int(jointly_valid.sum()), "own_mean_differs_from_old": int(different.sum()),
        "max_abs_common_mean_vs_old": float(max_gap), "rtol": VOLUME_EPS, "atol": VOLUME_EPS,
        "common_missing_masks_equal": True, "rolling_counterexample": numerics,
    }


def descriptive_rows(data, label, arch, stock_id=None):
    common = {"scope": label, "archetype": arch, "security_id": stock_id}
    grouped = {group: block for group, block in data.groupby("group", sort=False)}
    rows = []
    for group in OLD.GROUPS:
        block = grouped.get(group, data.iloc[:0])
        meta = {**common, "group": group, "total_n": len(block), "stocks_n": block.security_id.nunique()}
        for metric in NEW_METRICS:
            values = block[metric].to_numpy(float)
            stats = OLD.quantiles(values)
            measured = {"metric": metric, "period": metric_period(metric)}
            rows.append({"section": "descriptive", **meta, **measured, **stats,
                         "valid_stocks_n": block.loc[np.isfinite(values), "security_id"].nunique(),
                         "missing_rate": stats["missing_n"] / len(block) if len(block) else np.nan,
                         "status": "OK" if stats["valid_n"] else "NO_OBSERVATIONS"})
            reasons = Counter(block[f"{metric}_reason"])
            assert sum(n for reason, n in reasons.items() if reason != OK) == stats["missing_n"]
            rows.extend({"section": "missing_reason", **meta, **measured, "missing_reason": reason,
                         "missing_reason_n": n, "missing_reason_rate": n / len(block)}
                        for reason, n in sorted(reasons.items()) if reason != OK)

        for size in (3, 5):
            flag = block[f"bear_body_run_left_censored_{size}"]
            rows.append({"section": "window_diagnostics", **meta, "period": f"D-{size}..D-1",
                         "metric": f"bear_body_run_left_censored_{size}", "valid_n": flag.notna().sum(),
                         "missing_n": flag.isna().sum(), "left_censored_n": flag.sum(),
                         **{name: block[f"{name}_{size}"].sum() for name in (
                             "eligible_for_both_definitions", "bear_body_without_down_close",
                             "down_close_without_bear_body", "equal_open_close")},
                         })
        for current, old in zip(BODY_METRICS, OLD_METRICS):
            paired = block[current].notna() & block[old].notna()
            rows.append({"section": "legacy_definition_contrast", **meta, "period": metric_period(current),
                         "metric": current, "original_metric": old, "joint_valid_n": paired.sum(),
                         "current_only_valid_n": (block[current].notna() & block[old].isna()).sum(),
                         "old_only_valid_n": (block[current].isna() & block[old].notna()).sum(),
                         "different_n": (paired & block[current].ne(block[old])).sum()})
        rows.append({"section": "volume_diagnostics", **meta, "metric": "three_daily_volume_ratios",
                     "period": "D-23..D-1",
                     "common_old_joint_valid_n": block.common_old_joint_valid.sum(),
                     "own_old_joint_valid_n": block.own_old_joint_valid.sum(),
                     "own_mean_differs_from_old_n": block.own_old_mean_different.sum(),
                     "common_any_gt1_old_le1_n": block.common_any_gt1_old_le1.sum(),
                     "own_all_valid_n": block.own_three_leg_max.notna().sum(),
                     "own_tied_max_n": block.own_three_leg_max.eq(0).sum(),
                     **{f"own_Dm{k}_max_n": block.own_three_leg_max.eq(k).sum() for k in (1,2,3)}})
    return rows


def statistics(study, prof):
    rows = descriptive_rows(study, "ALL", "ALL")
    for arch, block in study.groupby("archetype", sort=True):
        rows.extend(descriptive_rows(block, "archetype", arch))
    for code, block in study.groupby("security_id", sort=True):
        rows.extend(descriptive_rows(block, "stock", block.archetype.iat[0], code))
    for row in OLD.separations(study, prof, NEW_METRICS) + OLD.cross_archetype(study, NEW_METRICS):
        row["period"] = metric_period(row["metric"])
        row["bh_family"] = f"ACT059A/new/{row['bh_family']}"
        row["scope"] = "ALL" if row["archetype"] == "ALL" else "archetype"
        rows.append(row)
    stats = pd.DataFrame.from_records(rows)
    is_descriptive = stats.section.eq("descriptive")
    assert is_descriptive.sum() == (42 + 5) * 3 * len(NEW_METRICS)
    assert stats.loc[stats.archetype.eq("D"), ["p_value", "bh_q_value"]].isna().all().all()
    return stats


def main():
    clock = {"wall": {}, "cpu": {}}
    started, start_cpu = perf_counter(), process_time()
    last, last_cpu = started, start_cpu

    def mark(phase):
        nonlocal last, last_cpu
        now, now_cpu = perf_counter(), process_time()
        clock["wall"][phase], clock["cpu"][phase] = now - last, now_cpu - last_cpu
        last, last_cpu = now, now_cpu

    prior_receipt_path = PREV / "evidence/compute_receipt.json"
    prior_seal_path = PREV / "ACT058A_FINAL_DELIVERY_VERIFIED.json"
    original_path = PREV / "delivery" / OLD.FILES["statistics"]
    prior_record = OLD.read_json(prior_receipt_path)
    prior_seal = OLD.read_json(prior_seal_path)
    old_identity = OLD.identity(original_path)
    old_manifest = next(row for row in prior_seal["files"] if row["name"] == original_path.name)
    assert old_identity["sha256"] == old_manifest["sha256"] and old_identity["bytes"] == old_manifest["bytes"]
    assert OLD.identity(PREV / "compute.py") == prior_record["code"]
    pa.set_cpu_count(4)
    pa.set_io_thread_count(2)
    verify_times = {"wall": 0.0, "cpu": 0.0}
    with threadpool_limits(limits=1):
        prof, events, signals, _, r56, r50, sources = OLD.frozen_inputs()
        assert sources == prior_record["source_identity"]
        cfg, frame, calendar, binding = OLD.bind_projection(r56, r50)
        assert cfg["provenance"]["bound"] == prior_record["frozen_reader"]
        assert json.loads(json.dumps(binding)) == prior_record["reader_projection"]
        sources.update(act058a_compute=prior_record["code"], act058a_compute_receipt=OLD.identity(prior_receipt_path),
                       act058a_delivery_seal=OLD.identity(prior_seal_path), act058a_old_statistics=old_identity,
                       act059a_prompt=OLD.identity(ROOT / "inputs/05_ACT059A_CODEX_MAC_PROMPT.md"))
        mark("reading")
        study, canaries, examples, controls = gather(
            cfg, frame, calendar, events, signals, prof, prior_record["precursor"], verify_times
        )
        before_checks, before_checks_cpu = perf_counter(), process_time()
        identity = check_original(study, original_path)
        verify_times["wall"] += perf_counter() - before_checks
        verify_times["cpu"] += process_time() - before_checks_cpu
        for size in (3, 5):
            assert {f"{name}_{size}" for name in (
                "bear_body_without_down_close", "down_close_without_bear_body", "equal_open_close",
                "first_left_censored", "last_left_censored", "first_gap",
            )} <= set(examples)
            assert examples[f"first_gap_{size}"]["missing_dates"]
        stats = statistics(study, prof)
        mark("computing")

    csv = ROOT / "evidence" / "metric_stats.csv"
    stats.to_csv(csv, index=False, encoding="utf-8-sig", float_format="%.12g")
    readback = pd.read_csv(csv, low_memory=False)
    code_cols = ["section", "scope", "archetype", "security_id", "group", "metric", "contrast"]
    assert readback.shape == stats.shape
    pd.testing.assert_frame_equal(stats[code_cols].fillna(""), readback[code_cols].fillna(""),
                                  check_dtype=False)
    numeric_readback = ["total_n", "valid_n", "missing_n", "auc", "thin_auc", "p_value", "bh_q_value"]
    pd.testing.assert_frame_equal(stats[numeric_readback], readback[numeric_readback],
                                  check_dtype=False, rtol=1e-11, atol=1e-12)
    csv_identity = OLD.identity(csv)
    sorted_keys = study[["security_id", "D", "D_ordinal", "group", "archetype"]].to_csv(index=False)
    cohort_digest = sha256(sorted_keys.encode("utf-8")).hexdigest()
    totals = study.groupby("group").size().to_dict()
    by_archetype = study.groupby(["archetype", "group"]).size().unstack(fill_value=0).to_dict("index")
    assert totals == {"hidden":3244, "visible":130, "ordinary":99793}
    all_stats = stats[stats.scope.eq("ALL")]
    wide_summaries = {}
    for group in OLD.GROUPS:
        wide_summaries[group] = {}
        group_stats = all_stats[all_stats.group.eq(group)]
        for sec, columns in (
            ("descriptive", ["metric", "total_n", "valid_n", "missing_n", "median", "mean"]),
            ("missing_reason", ["metric", "missing_reason", "missing_reason_n"]),
            ("window_diagnostics", ["metric", "left_censored_n", "eligible_for_both_definitions",
                                    "bear_body_without_down_close", "down_close_without_bear_body",
                                    "equal_open_close"]),
            ("legacy_definition_contrast", ["metric", "joint_valid_n", "current_only_valid_n",
                                            "old_only_valid_n", "different_n"]),
            ("volume_diagnostics", ["metric", "common_old_joint_valid_n", "own_old_joint_valid_n",
                                    "own_mean_differs_from_old_n", "common_any_gt1_old_le1_n", "own_all_valid_n",
                                    "own_tied_max_n", "own_Dm1_max_n", "own_Dm2_max_n", "own_Dm3_max_n"]),
        ):
            wide_summaries[group][sec] = group_stats.loc[group_stats.section.eq(sec), columns].to_dict("records")
    n_stats = stats.section.value_counts().to_dict()
    rank = stats[stats.section.eq("within_stock_year_rank") & stats.stable_effect.eq(True)]
    rank_fields = ["archetype", "contrast", "metric", "auc", "thin_auc", "matched_stocks_n",
                   "thin_matched_stocks_n", "p_value", "bh_q_value"]
    stable = rank[rank_fields].replace({np.nan: None}).to_dict("records")
    mark("verifying")
    for kind in verify_times:
        clock[kind]["computing"] -= verify_times[kind]
        clock[kind]["verifying"] += verify_times[kind]
    del sorted_keys, study, frame, stats, readback, rank, all_stats, group_stats
    gc.collect()
    mark("cleanup")

    evidence = {
        "action": "ACT-059A/task_A", "state": "TASK_A_LOCAL_PASS", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "FIT": 0, "model_load_calls": 0, "predict_calls": 0, "tune_calls": 0, "simulated_trades": 0,
        "STRICT_PIT": 0, "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
        "source_identity": sources, "frozen_reader": cfg["provenance"]["bound"], "reader_projection": binding,
        "cohort": {"stocks": len(controls), "events": len(events), **totals,
                   "stock_archetypes": prof.archetype.value_counts().to_dict(), "by_archetype": by_archetype,
                   "ordinary_by_stock": controls, "key_digest_sha256": cohort_digest,
                   "key_digest_columns": ["security_id", "D", "D_ordinal", "group", "archetype"],
                   "identity_check": "exact event keys and exact ACT058A ordinary selector/inputs, per-stock and forward-hit totals"},
        "metrics": NEW_METRICS, "original_metrics_frozen": OLD_METRICS, "feature_cutoff": "D-1",
        "stats_sections": n_stats, "stats_file": csv_identity, "code": OLD.identity(Path(__file__)),
        "aggregates": wide_summaries, "stable_ranks": stable,
        "meaning_of_diagnostics": {
            "window_body_counterexamples": "exchange slots encountered in windows, with repeated dates across anchors counted by window",
            "joint_valid_n": "both descriptors valid on the same anchor",
            "censor": "full window all C<O; outside-window run length unknown",
            "common_any_gt1_old_le1": "one or more shared-base daily ratios >1 while old ratio <=1",
            "tied_own_max": "two or more maximum own-rolling ratios exactly equal",
        },
        "volume_identity": identity, "counterexamples": examples, "physical_prefix_canaries": canaries,
        "frozen_bh": "ACT058A untouched; ACT059A/new separately by archetype/contrast stock_sign and A/B/C Kruskal",
        "runtime": {"interpreter": sys.executable, "phase_wall_s": {**clock["wall"], "uploading": None},
                    "phase_process_cpu_s": {**clock["cpu"], "uploading": None},
                    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                    "logical_distinct_explicit_input_file_bytes": sum(item["bytes"] for item in sources.values()),
                    "logical_stats_output_bytes": csv_identity["bytes"],
                    "physical_io_accounting": "CANNOT_CONFIRM; Reader physical backing and cache I/O unmetered"},
        "cleanup": {"disk_temp_created": [], "disk_temp_removed": [], "in_memory_projection_and_statistics_released": True},
    }
    path = ROOT / "evidence" / "metric_receipt.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    assert OLD.read_json(path)["cohort"]["key_digest_sha256"] == cohort_digest
    print(f"TASK_A_LOCAL_PASS 42/{len(events)}/{totals['ordinary']} prefix=40 stats={sum(n_stats.values())}", flush=True)


if __name__ == "__main__":
    main()
