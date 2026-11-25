"""ACT-059A Task B, using only ACT-058A frozen events, controls and Reader."""
from __future__ import annotations

from collections import Counter
import gc
import json
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time

import numpy as np
import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits

from metric_a import CENSORS, NEW_METRICS, OLD, new_features

ROOT = Path(__file__).resolve().parent
ORIGINAL = OLD.ROOT / "delivery" / OLD.FILES["waves"]
OLD_FINAL = OLD.ROOT / "ACT058A_FINAL_DELIVERY_VERIFIED.json"
OLD_COMPUTE = OLD.ROOT / "evidence/compute_receipt.json"
WAVE = ROOT / "delivery/ACT059A_108_WAVES_SUPPLEMENT.csv"
STATS = ROOT / "evidence/wave_control_stats.csv"
RECEIPT = ROOT / "evidence/wave_receipt.json"
OBSERVED = "OBSERVED"
HIT = "FROZEN_HIT"
NO_HIT = "NO_FROZEN_HIT"
UNAVAILABLE = "UNAVAILABLE"
ENDPOINTS = (5, 10, 20)
MIN_LOW = "min_low_D1_D5_vs_Dclose_pct"
MIN_LOW_CLIPPED = "min_low_D1_D5_vs_Dclose_clipped_zero_pct"
PAIR_OUTCOMES = ("close_ret_D5_pct", MIN_LOW)
OUTCOMES = (*(f"close_ret_D{h}_pct" for h in ENDPOINTS), MIN_LOW, MIN_LOW_CLIPPED)
PEAK_METRICS = ("raw_max_rise_pct", "peak_day", "peak_post5_max_dd_pct",
                "peak_post5_sessions_to_trough")
WARNING_NAMES = ("white_downcross", "yellow_downcross", "bearish_high_fade")
EVENT_METHOD = (
    "For D with D+1 openable, either matured frozen T+2 net close return >=7% or "
    "matured frozen T+5 net close return >=15%; exclude two consecutive one-price "
    "limit-ups in D-4..D. Keep the earliest qualifying D in each stock, collapse "
    "candidates from retained D through D+9, and allow the next independent D "
    "at D+10 or later. Four-family capture is checked on each retained D."
)


def date_at(calendar, ordinal):
    return str(calendar[ordinal]) if 0 <= ordinal < len(calendar) else None


def missing_slots(slots, calendar, at):
    return "|".join(f"{offset}:{date_at(calendar, at + offset) or '-'}:{status}"
                    for offset, status in slots)


def coverage_status(observed, total):
    if observed == total:
        return "COMPLETE"
    return "PARTIAL" if observed else UNAVAILABLE


def d_basis_bars(stock, at, horizon):
    anchor = stock.available_rows[at]
    assert stock.valid[anchor]
    pairs = [stock.get(at + offset, anchor)[1:] for offset in range(horizon + 1)]
    bars, statuses = zip(*pairs)
    assert statuses[0] == OBSERVED
    return bars, statuses


def outcomes(bars, statuses, calendar, at, horizons):
    baseline = bars[0][3]
    out = {"D_basis_close_verified": baseline}
    for h in horizons:
        tag = f"close_ret_D{h}"
        endpoint = bars[h]
        out.update({
            f"{tag}_pct": (endpoint[3] / baseline - 1) * 100 if endpoint is not None else None,
            f"{tag}_status": statuses[h],
            f"{tag}_date": date_at(calendar, at + h),
            f"{tag}_close_d_basis": endpoint[3] if endpoint is not None else None,
        })
    low_missing = [(h, statuses[h]) for h in range(1, 6) if bars[h] is None]
    low_value, low_offset = None, None
    if not low_missing:
        low_offset = min(range(1, 6), key=lambda h: (bars[h][2], h))
        low_value = float((bars[low_offset][2] / baseline - 1) * 100)
    out.update({
        MIN_LOW: low_value,
        MIN_LOW_CLIPPED: min(0.0, low_value) if low_value is not None else None,
        "min_low_D1_D5_observed_n": 5 - len(low_missing),
        "min_low_D1_D5_status": coverage_status(5 - len(low_missing), 5),
        "min_low_D1_D5_unavailable_slots": missing_slots(low_missing, calendar, at),
        "min_low_D1_D5_offset": low_offset,
        "min_low_D1_D5_date": date_at(calendar, at + low_offset) if low_offset is not None else None,
        "min_low_D1_D5_d_basis": bars[low_offset][2] if low_offset is not None else None,
    })
    return out


def summarize_first(hits, unknown, calendar, at, start, end, signal=False):
    total = end - start + 1
    first = hits[0] if hits else None
    earlier_unknown = sum(offset < first for offset, _ in unknown) if hits else None
    coverage = coverage_status(total - len(unknown), total)
    if not hits:
        first_state = (NO_HIT if signal else "NO_OBSERVED_HIT") if coverage == "COMPLETE" else UNAVAILABLE
    elif earlier_unknown:
        first_state = "EARLIEST_OBSERVED_PARTIAL"
    else:
        first_state = "FIRST_CONFIRMED_WITHIN_WINDOW"
    return {
        "first_offset": first,
        "first_date": date_at(calendar, at + first) if first is not None else None,
        "first_status": first_state,
        "earlier_unavailable_n": earlier_unknown,
        "window_status": coverage,
        "window_available_n": total - len(unknown),
        "window_unavailable_n": len(unknown),
        "window_unavailable_slots": missing_slots(unknown, calendar, at),
    }


def frozen_signal_window(stock, at, signal_by_ordinal, original):
    out = {}
    statuses = {}
    base_status = {}
    for off in range(-5, 6):
        hit_at = signal_by_ordinal.get(at + off, {})
        base_status[off] = OLD.signal_status(stock, at + off)
        statuses[off] = {
            fam: HIT if hit_at.get(fam) else base_status[off]
            for fam in OLD.FAMILIES
        }
    for fam in (*OLD.FAMILIES, "any_frozen_signal"):
        is_any = fam == "any_frozen_signal"
        tag_status = {
            h: ((HIT if signal_by_ordinal.get(at + h, {}).get("forward_any") else base_status[h])
                if is_any else statuses[h][fam])
            for h in statuses
        }
        hits = [h for h, status in tag_status.items() if status == HIT]
        unknown = [(h, status) for h, status in tag_status.items() if status not in (HIT, NO_HIT)]
        summary = summarize_first(hits, unknown, stock.calendar, at, -5, 5, signal=True)
        first = summary["first_offset"]
        category = (summary["first_status"] if first is None else
                    "D_BEFORE" if first < 0 else "D_DAY" if first == 0 else "D_AFTER")
        out.update({f"{fam}_{k}": v for k, v in summary.items()})
        out[f"{fam}_first_timing"] = category
        if is_any:
            at_first = statuses.get(first, {})
            out["any_frozen_signal_first_families"] = "|".join(
                family for family, status in at_first.items() if status == HIT
            )
            continue
        # Keep the original per-slot status encoding. Exact missing causes stay in the slot ledger.
        for h, status in tag_status.items():
            rendered = status if status in (HIT, NO_HIT) else UNAVAILABLE
            col = f"{fam}_D{h:+d}"
            if h <= 0:
                assert original[col] == rendered, (original["event_id"], col)
            else:
                out[col] = rendered
                out[f"{col}_date"] = date_at(stock.calendar, at + h)
        pre = [h for h in hits if h <= 0]
        post = [h for h in hits if h > 0]
        assert original[f"{fam}_actual_offsets"] == "|".join(map(str, pre))
        assert original[f"{fam}_actual_dates"] == "|".join(date_at(stock.calendar, at + h) for h in pre)
        assert original[f"{fam}_unavailable_slots"] == missing_slots(
            [(h, status) for h, status in unknown if h <= 0], stock.calendar, at)
        out[f"{fam}_post_actual_offsets"] = "|".join(map(str, post))
        out[f"{fam}_post_actual_dates"] = "|".join(date_at(stock.calendar, at + h) for h in post)
    return out


def crossing(previous, current, previous_state, current_state, line_index):
    if previous is None:
        return None, f"PRIOR_{previous_state}", None
    if current is None:
        return None, f"CURRENT_{current_state}", None
    if not np.isfinite(previous[line_index]) or not np.isfinite(current[line_index]):
        sides = "BOTH" if not (np.isfinite(previous[line_index]) or np.isfinite(current[line_index])) else (
            "PRIOR" if not np.isfinite(previous[line_index]) else "CURRENT")
        return None, f"{sides}_LINE_UNAVAILABLE", None
    hit = previous[3] >= previous[line_index] and current[3] < current[line_index]
    evidence = {"prior_close_d_basis": previous[3], "prior_line_d_basis": previous[line_index],
                "close_d_basis": current[3], "line_d_basis": current[line_index]}
    return hit, OBSERVED, evidence


def bearish_fade(current, current_state):
    if current is None:
        return None, f"CURRENT_{current_state}", None
    open_, high, _, close, *_ = current
    assert high > 0
    ratio = close / high
    evidence = {"open_d_basis": open_, "high_d_basis": high, "close_d_basis": close,
                "close_vs_high_pct": (ratio - 1) * 100}
    return close < open_ and ratio <= 0.95, OBSERVED, evidence


def warnings_in_window(bars, statuses, calendar, at):
    tests = {name: {} for name in WARNING_NAMES}
    for h in range(1, 21):
        for name, line_index in (("white_downcross", 5), ("yellow_downcross", 6)):
            tests[name][h] = crossing(bars[h - 1], bars[h], statuses[h - 1], statuses[h], line_index)
        tests["bearish_high_fade"][h] = bearish_fade(bars[h], statuses[h])
    out = {}
    for name, checks in tests.items():
        hit_offsets = [h for h, (hit, _, _) in checks.items() if hit]
        unknown = [(h, state) for h, (hit, state, _) in checks.items() if hit is None]
        summary = summarize_first(hit_offsets, unknown, calendar, at, 1, 20)
        evidence = checks[hit_offsets[0]][2] if hit_offsets else {}
        tag = f"warning_{name}"
        out.update({f"{tag}_{k}": v for k, v in (summary | evidence).items()})
    return out


def nearest_matches(event_rows, ordinary, calendar):
    years = np.asarray(calendar, dtype=int) // 10000
    available = {}
    for at in ordinary:
        available.setdefault(years[at], set()).add(int(at))
    matches = {}
    for row in sorted(event_rows, key=lambda item: (item["D"], item["event_id"])):
        at = int(row["D_ordinal"])
        same_year = available.get(years[at], set())
        choice = min(same_year, key=lambda candidate: (abs(candidate - at), candidate), default=None)
        if choice is not None:
            same_year.remove(choice)
        matches[row["event_id"]] = choice
    return matches


def count_sign(x):
    x = np.asarray(x, dtype=float)
    return {"positive_n": int((x > 0).sum()), "negative_n": int((x < 0).sum()),
            "zero_n": int((x == 0).sum()), "missing_n": int((~np.isfinite(x)).sum())}


def verify_pair_choices(rows, ordinary, matches, calendar):
    # Independent replay by ranked calendar positions with each previous pair removed.
    available = set(map(int, ordinary))
    for row in sorted(rows, key=lambda item: (item["D"], item["event_id"])):
        at, event_id = int(row["D_ordinal"]), row["event_id"]
        year = row["D"][:4]
        selected = matches[event_id]
        ranked = sorted((abs(p - at), p) for p in available if str(calendar[p])[:4] == year)
        if not ranked:
            assert selected is None
            continue
        assert selected == ranked[0][1] and abs(selected - at) > OLD.END_ORDINAL_GUARD
        available.remove(selected)


def verify_predicate_boundaries():
    prior = np.array([20., 22., 18., 20., 100., 20., 20.])
    current = np.array([20., 20., 18., 19., 100., 20., 20.])
    assert crossing(prior, current, OBSERVED, OBSERVED, 5)[0]
    assert crossing(None, current, "NO_READER_BAR_ON_SESSION", OBSERVED, 5)[0] is None
    assert bearish_fade(current, OBSERVED)[0]
    assert not bearish_fade(current - np.array([1, 0, 0, 0, 0, 0, 0]), OBSERVED)[0]
    dates = ["20260105", "20260106", "20260107", "20260108"]
    summary = summarize_first([2], [(1, "NO_READER_BAR_ON_SESSION")], dates, 0, 1, 2)
    assert summary["first_status"] == "EARLIEST_OBSERVED_PARTIAL" and summary["first_offset"] == 2
    rows = [
        {"D": "20260107", "D_ordinal": "2", "event_id": "test/20260107"},
        {"D": "20260105", "D_ordinal": "0", "event_id": "test/20260105"},
    ]
    assert nearest_matches(rows, [1, 3], dates) == {"test/20260105": 1, "test/20260107": 3}
    assert nearest_matches(rows[:1], [1, 3], dates) == {"test/20260107": 1}
    bars = [prior, current, None, current, current, current]
    result = outcomes(bars, [OBSERVED, OBSERVED, "NO_READER_BAR_ON_SESSION"] + [OBSERVED] * 3, dates, 0, [5])
    assert result[MIN_LOW] is None and result["close_ret_D5_pct"] is not None


def pair_record(row, status_map, selected, stock, old, added, event_out):
    at = int(row["D_ordinal"])
    event_sig = status_map[at]
    assert event_sig["reverse_independent"]
    out = {
        "section": "wave_matched_pair", "security_id": stock.code, "year": int(row["D"][:4]),
        "event_id": row["event_id"], "event_D": row["D"], "event_D_ordinal": at,
        "event_group": row["event_group"], "archetype": row["archetype"],
        "event_frozen_forward_status": HIT if event_sig["forward_any"] else NO_HIT,
        "matching_status": "MATCHED" if selected is not None else "UNMATCHED",
    }
    if selected is None:
        out["matching_reason"] = "NO_UNUSED_SAME_STOCK_CALENDAR_YEAR_ORDINARY"
    else:
        control_D = date_at(stock.calendar, selected)
        control_sig = status_map.get(selected, {})
        assert not control_sig.get("reverse_independent", False)
        control_status = HIT if control_sig.get("forward_any") else OLD.signal_status(stock, selected)
        control_families = "|".join(f for f in OLD.FAMILIES if control_sig.get(f, False))
        bars, states = d_basis_bars(stock, selected, 5)
        control_out = outcomes(bars, states, stock.calendar, selected, [5])
        out.update({
            "control_id": f"{stock.code}/{control_D}", "control_D": control_D,
            "control_D_ordinal": selected, "control_frozen_forward_status": control_status,
            "control_frozen_forward_families": control_families,
            "control_signed_distance_sessions": selected - at,
            "control_distance_sessions": abs(selected - at),
        })
    for tag, ordinal, result in (("event", at, event_out),
                                 ("control", selected, control_out if selected is not None else {})):
        if ordinal is None:
            continue
        for source in (old.loc[ordinal], added.loc[ordinal]):
            out.update({f"{tag}_{field}": value for field, value in source.items()})
        for metric, status, slots in (
            (PAIR_OUTCOMES[0], "close_ret_D5_status", None),
            (PAIR_OUTCOMES[1], "min_low_D1_D5_status", "min_low_D1_D5_unavailable_slots"),
        ):
            out[f"{tag}_{metric}"] = result[metric]
            out[f"{tag}_{metric}_reason"] = result[status] if result[metric] is not None or slots is None else result[slots]
    return out


def pairs_summary(pairs, metrics):
    rows = []
    for metric in metrics:
        event = pairs[f"event_{metric}"].astype(float)
        control = pairs[f"control_{metric}"].astype(float)
        frame = pairs[["security_id", "year", "matching_status"]].assign(
            event_value=event, control_value=control, diff=event - control)
        for side in ("event", "control"):
            reason = f"{side}_{metric}_reason"
            frame[f"{side}_reason"] = pairs[reason] if reason in pairs else "FROZEN_PRECURSOR_UNAVAILABLE"
        year_means = frame.groupby(["security_id", "year"])["diff"].mean()
        stock_means = year_means.groupby(level="security_id").mean()

        def aggregate(sample, scope, code, year, unit, value):
            both = sample.loc[sample.matching_status.eq("MATCHED")]
            delta = both["diff"]
            matched_n, valid_n = len(delta), int(delta.notna().sum())
            raw_counts = count_sign(delta)
            record = {
                "section": "wave_pair_metric_summary", "pair_scope": scope, "security_id": code,
                "year": year, "metric": metric, "event_n": len(sample), "raw_pair_n": matched_n,
                "unmatched_n": len(sample) - matched_n, "paired_valid_n": valid_n,
                "pair_delta_weight_unit": unit, "pair_delta_mean": value,
                "valid_stock_year_n": int(both.loc[delta.notna(), ["security_id", "year"]].drop_duplicates().shape[0]),
                "valid_stock_n": int(both.loc[delta.notna(), "security_id"].nunique()),
                "pair_delta_raw_pooled_mean": delta.mean(),
            }
            record.update({f"pair_delta_{key}": val for key, val in raw_counts.items()})
            for side in ("event", "control"):
                side_values = both[f"{side}_value"]
                deltas_valid = side_values.loc[delta.notna()]
                record[f"{side}_pair_valid_raw_mean"] = deltas_valid.mean()
                record[f"{side}_valid_n"] = int(side_values.notna().sum())
                record.update({f"{side}_{key}": val for key, val in count_sign(side_values).items()})
                reasons = Counter(both.loc[side_values.isna(), f"{side}_reason"].fillna("CANNOT_CONFIRM"))
                record[f"{side}_missing_reason_counts"] = json.dumps(reasons, sort_keys=True)
            rows.append(record)

        for (code, year), sample in frame.groupby(["security_id", "year"], sort=True):
            aggregate(sample, "STOCK_YEAR", code, year, "PAIRED_EVENTS", year_means.at[(code, year)])
        for code, sample in frame.groupby("security_id", sort=True):
            aggregate(sample, "STOCK", code, None, "EQUAL_VALID_YEARS", stock_means.at[code])
        aggregate(frame, "ALL", "ALL", None, "EQUAL_VALID_STOCKS_OF_EQUAL_VALID_YEARS", stock_means.mean())
    return pd.DataFrame.from_records(rows)


def wave_distributions(waves):
    records = []
    for code, sample in [*waves.groupby("security_id", sort=True), ("ALL", waves)]:
        full = sample["peak_status"].eq("FULL_WINDOW")
        peak_post5 = full & sample["peak_post5_status"].eq("COMPLETE")
        for metric in (*OUTCOMES, *PEAK_METRICS):
            vals = pd.to_numeric(sample[metric], errors="raise")
            if metric in OUTCOMES:
                cohorts = [("INDEPENDENT_VALUE_VALIDITY", vals)]
            else:
                required = full if metric in PEAK_METRICS[:2] else peak_post5
                cohorts = [("STRICT_FROZEN_COMPLETE", vals.where(required)),
                           ("ALL_FROZEN_RECORDED_VALUES_INCLUDING_OBSERVED_ONLY", vals)]
            for policy, series in cohorts:
                values = series.to_numpy(dtype=float)
                finite = values[np.isfinite(values)]
                labels = {**OLD.quantiles(values), **count_sign(values)}
                records.append({
                    "section": "wave_continuous_distribution", "security_id": code,
                    "metric": metric, "validity_scope": policy, "event_n": len(sample),
                    "min": finite.min() if len(finite) else None,
                    "max": finite.max() if len(finite) else None, **labels,
                })
        for h in ENDPOINTS:
            col = f"close_ret_D{h}_pct"
            peak = pd.to_numeric(sample.raw_max_rise_pct)
            endpoint = pd.to_numeric(sample[col])
            delta = (peak - endpoint).where(full & peak.notna() & endpoint.notna())
            pair_valid = delta.notna()
            values = delta.to_numpy(dtype=float)
            records.append({
                "section": "wave_peak_endpoint_contrast", "security_id": code,
                "metric": f"frozen_peak_high_return_minus_{col}",
                "validity_scope": "STRICT_FULL20_PEAK_AND_VALID_ENDPOINT", "event_n": len(sample),
                **OLD.quantiles(values), **count_sign(values),
                "peak_gt_zero_endpoint_below_zero_n": int((pair_valid & (peak > 0) & (endpoint < 0)).sum()),
                "peak_gt_zero_endpoint_eq_zero_n": int((pair_valid & (peak > 0) & (endpoint == 0)).sum()),
                "peak_gt_zero_endpoint_gt_zero_n": int((pair_valid & (peak > 0) & (endpoint > 0)).sum()),
            })
    return pd.DataFrame.from_records(records)


def wave_examples(waves):
    numeric = waves.copy()
    for col in (*PEAK_METRICS, *OUTCOMES):
        numeric[col] = pd.to_numeric(numeric[col], errors="raise")
    cols = ["event_id", "peak_status", "peak_post5_status", "peak_D", *PEAK_METRICS,
            *OUTCOMES, *(f"close_ret_D{h}_status" for h in ENDPOINTS)]
    cases = []
    for code, sample in [*numeric.groupby("security_id", sort=True), ("ALL", numeric)]:
        full = sample[sample.peak_status.eq("FULL_WINDOW")]
        endpoint = full[full.close_ret_D20_pct.notna()]
        post = full[full.peak_post5_status.eq("COMPLETE") & full.peak_post5_max_dd_pct.notna()]
        rank_by = [
            ("largest_frozen_peak", full, full.raw_max_rise_pct),
            ("largest_frozen_peak_minus_D20_close", endpoint, endpoint.raw_max_rise_pct - endpoint.close_ret_D20_pct),
            ("deepest_frozen_peak_post5_drawdown", post, -post.peak_post5_max_dd_pct),
        ]
        for label, valid, score in rank_by:
            if not valid.empty:
                row = valid.loc[score.idxmax(), cols]
                cases.append({"scope": code, "rule": label, **row.to_dict()})
    extra = numeric.loc[numeric.event_id.eq("601899.SH/20261102"), cols].iloc[0].to_dict()
    return cases + [{"scope": "601899.SH", "rule": "original_observed_only", **extra}]


def gather_waves(cfg, frame, cal, event, signals, original, ordinary_by_stock):
    wave_records, pair_records, controls_n = {}, [], {}
    original_rows = original.to_dict("records")
    wave_codes = set(original.security_id)
    for code, daily in frame.loc[frame.canonical.isin(wave_codes)].groupby("canonical", sort=True):
        stock = OLD.Stock(code, daily, cfg["events"][code], cal)
        rows = [row for row in original_rows if row["security_id"] == code]
        local = event.loc[event.security_id.eq(code)].set_index("D")
        signal_rows = signals.loc[signals.security_id.eq(code)].set_index("exchange_session_ordinal")
        assert np.array_equal(cal[signal_rows.index].astype(int), signal_rows.D)
        status_map = signal_rows.to_dict("index")
        ordinals = local.exchange_session_ordinal.to_numpy()
        assert np.array_equal(cal[ordinals].astype(int), local.index)
        ordinary = OLD.ordinary(stock, ordinals)
        assert len(ordinary) == ordinary_by_stock[code]
        controls_n[code] = len(ordinary)

        matches = nearest_matches(rows, ordinary, cal)
        verify_pair_choices(rows, ordinary, matches, cal)
        anchors = np.array([int(row["D_ordinal"]) for row in rows]
                           + [selected for selected in matches.values() if selected is not None])
        assert len(np.unique(anchors)) == len(anchors)
        old = OLD.features(stock, anchors).set_axis(anchors)
        added = new_features(stock, anchors).set_axis(anchors)
        original_old = pd.DataFrame(rows).set_index(pd.Index(anchors[:len(rows)]))[old.columns]
        baseline_old = original_old.replace("", np.nan).astype(float)
        np.testing.assert_allclose(old.loc[baseline_old.index].to_numpy(dtype=float),
                                   baseline_old.to_numpy(), rtol=5e-12, atol=1e-12, equal_nan=True)

        for row in rows:
            at = int(row["D_ordinal"])
            key = row["event_id"]
            frozen = local.loc[int(row["D"])]
            assert key == f"{code}/{cal[at]}" and at == frozen.exchange_session_ordinal
            assert row["archetype"] == frozen.archetype and row["name"] == frozen["name"]
            assert row["event_group"] == ("hidden" if frozen.hidden else "visible")
            assert stock.available_rows[at] == status_map[at]["event_slice_end_bar"]
            bars, statuses = d_basis_bars(stock, at, 20)
            assert sum(status == OBSERVED for status in statuses[1:]) == int(row["observed_sessions"])
            assert sum(status == "RIGHT_CENSORED_AT_20261120" for status in statuses[1:]) == int(row["right_censored_rows"])
            out = outcomes(bars, statuses, cal, at, ENDPOINTS)
            assert np.isclose(out["D_basis_close_verified"], float(row["d_close_basis"]), rtol=5e-12, atol=1e-12)
            wave_records[key] = (
                added.loc[at].to_dict() | out | frozen_signal_window(stock, at, status_map, row)
                | warnings_in_window(bars, statuses, cal, at)
            )
            pair_records.append(pair_record(row, status_map, matches[key], stock, old, added, out))
    appended = pd.DataFrame.from_records([wave_records[key] for key in original.event_id])
    collisions = set(original).intersection(appended)
    assert not collisions, sorted(collisions)
    waves = pd.concat([original, appended], axis=1)
    pairs = pd.DataFrame.from_records(pair_records).sort_values(["event_D", "event_id"])
    metrics = (*old.columns, *NEW_METRICS, *CENSORS, *PAIR_OUTCOMES)
    return waves, pairs, metrics, controls_n


def validate(waves, pairs, stats, original, metrics):
    keys = ["event_id", "security_id", "D"]
    assert waves[keys].equals(original[keys])
    assert len(waves) == len(pairs) == 108 and waves.event_id.is_unique and pairs.event_id.is_unique
    assert waves.security_id.value_counts().to_dict() == OLD.WAVES
    assert waves.event_group.value_counts().to_dict() == {"hidden": 102, "visible": 6}
    assert waves.peak_status.eq("FULL_WINDOW").sum() == 107
    partial = waves.loc[waves.event_id.eq("601899.SH/20261102")].iloc[0]
    assert (partial.observed_sessions, partial.scheduled_sessions, partial.peak_status) == (
        "14", "20", "OBSERVED_WINDOW_ONLY"
    )
    assert partial.close_ret_D5_status == partial.close_ret_D10_status == OBSERVED
    assert partial.close_ret_D20_status == "RIGHT_CENSORED_AT_20261120"
    assert np.isfinite(partial.close_ret_D5_pct) and np.isfinite(partial.close_ret_D10_pct) and pd.isna(partial.close_ret_D20_pct)
    for h in ENDPOINTS:
        tag = f"close_ret_D{h}"
        assert waves[f"{tag}_pct"].notna().equals(waves[f"{tag}_status"].eq(OBSERVED))
    assert waves[MIN_LOW].notna().equals(waves.min_low_D1_D5_observed_n.eq(5))
    np.testing.assert_equal(waves[MIN_LOW_CLIPPED].to_numpy(), np.minimum(waves[MIN_LOW].to_numpy(), 0))

    matched = pairs.loc[pairs.matching_status.eq("MATCHED")]
    assert matched.control_id.is_unique and not set(matched.control_id) & set(waves.event_id)
    assert matched.control_D.str[:4].astype(int).eq(matched.year).all()
    assert matched.control_id.str.split("/").str[0].eq(matched.security_id).all()
    assert matched.control_distance_sessions.gt(OLD.END_ORDINAL_GUARD).all()
    assert matched.control_frozen_forward_status.isin([HIT, NO_HIT]).all()
    assert pairs.event_frozen_forward_status.eq(HIT).equals(pairs.event_group.eq("visible"))
    summary = stats.loc[stats.section.eq("wave_pair_metric_summary") & stats.pair_scope.eq("ALL")].set_index("metric")
    assert len(summary) == len(metrics)
    for metric in metrics:
        reported = summary.loc[metric]
        valid = matched[[f"event_{metric}", f"control_{metric}"]].notna().all(axis=1)
        assert reported.paired_valid_n == valid.sum()
        assert reported.raw_pair_n == len(matched)
        assert reported.pair_delta_missing_n + reported.paired_valid_n == len(matched)
        assert (reported.pair_delta_positive_n + reported.pair_delta_negative_n
                + reported.pair_delta_zero_n) == valid.sum()
        # Replay weighting via explicit per-stock, per-year lists independently of pandas group reductions.
        src = matched.loc[valid].assign(
            diff=lambda f: f[f"event_{metric}"].astype(float) - f[f"control_{metric}"].astype(float)
        )
        per_stock = {}
        for pair in src.itertuples():
            per_stock.setdefault(pair.security_id, {}).setdefault(pair.year, []).append(pair.diff)
        values = [np.mean([np.mean(group) for group in years.values()]) for years in per_stock.values()]
        expected = np.mean(values) if values else np.nan
        np.testing.assert_allclose(reported.pair_delta_mean, expected, rtol=1e-10, atol=1e-12)
    verify_predicate_boundaries()


def clean_json(item):
    if isinstance(item, dict):
        return {key: clean_json(value) for key, value in item.items()}
    if isinstance(item, list):
        return [clean_json(value) for value in item]
    if isinstance(item, np.generic):
        return clean_json(item.item())
    if isinstance(item, float) and not np.isfinite(item):
        return None
    return item


def main():
    start, start_cpu = perf_counter(), process_time()
    wall, cpu, previous, previous_cpu = {}, {}, start, start_cpu

    def stage(name):
        nonlocal previous, previous_cpu
        now, now_cpu = perf_counter(), process_time()
        wall[name], cpu[name] = now - previous, now_cpu - previous_cpu
        previous, previous_cpu = now, now_cpu

    pa.set_cpu_count(4)
    pa.set_io_thread_count(2)
    with threadpool_limits(limits=1):
        _, event, signals, _, r56, r50, sources = OLD.frozen_inputs()
        prior_final = OLD.read_json(OLD_FINAL)
        prior_delivery = OLD.ROOT / "delivery/ACT058A_0FIT_RECEIPT.json"
        prior_items = {item["name"]: item for item in prior_final["files"]}
        for path in (ORIGINAL, prior_delivery):
            identity = OLD.identity(path)
            assert all(identity[k] == prior_items[path.name][k] for k in ("bytes", "sha256"))
            sources[path.name] = identity
        sources[OLD_COMPUTE.name] = OLD.identity(OLD_COMPUTE)
        assert sources[OLD_COMPUTE.name]["sha256"] == OLD.read_json(prior_delivery)["compute_evidence"]["sha256"]
        original = pd.read_csv(ORIGINAL, dtype=str, keep_default_na=False)
        prior = OLD.read_json(OLD_COMPUTE)
        ordinary = prior["precursor"]["ordinary_by_stock"]
        assert len(ordinary) == 42 and sum(ordinary.values()) == 99793
        cfg, frame, calendar, binding = OLD.bind_projection(r56, r50)
        assert cfg["provenance"]["bound"] == prior["frozen_reader"]
        for path in (OLD_FINAL, Path(OLD.__file__), OLD.ACT56 / "task2/export.py",
                     Path(OLD.pft.__file__), ROOT / "metric_a.py",
                     ROOT / "inputs/05_ACT059A_CODEX_MAC_PROMPT.md"):
            sources[path.name] = OLD.identity(path)
        stage("reading")

        waves, pairs, metrics, controls = gather_waves(cfg, frame, calendar, event, signals, original, ordinary)
        distributed = wave_distributions(waves)
        examples = wave_examples(waves)
        stats = pd.concat([distributed, pairs, pairs_summary(pairs, metrics)], ignore_index=True)
        stats_rows = len(stats)
        stage("computing")

        validate(waves, pairs, stats, original, metrics)
        for path, table in ((WAVE, waves), (STATS, stats)):
            table.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.12g")
            assert 0 < path.stat().st_size <= 9_500_000
        output = pd.read_csv(WAVE, dtype=str, keep_default_na=False)
        pd.testing.assert_frame_equal(output[original.columns], original, check_exact=True)
        assert output.shape == waves.shape
        stat_output = pd.read_csv(STATS, dtype=str, keep_default_na=False)
        assert stat_output.shape == stats.shape and stat_output.section.equals(stats.section)
        pair_output = stat_output.loc[stat_output.section.eq("wave_matched_pair")]
        assert pair_output.event_id.tolist() == pairs.event_id.tolist()
        assert pair_output.control_id.tolist() == pairs.control_id.fillna("").tolist()
        outcomes_n = {field: int(waves[field].notna().sum()) for field in OUTCOMES}
        receipt = {
            "task": "ACT059A Task B", "status": "PASS_108_EXACT_ENDPOINT_VALIDITY_AND_MATCH_LINEAGE",
            "sample_counts": {"waves": len(waves), "per_stock": OLD.WAVES, "full20": 107,
                              "observed_only": 1, "hidden": 102, "visible": 6},
            "source_inputs": sources, "code": OLD.identity(Path(__file__)),
            "event_method": {
                "rule": EVENT_METHOD,
                "source": str(Path(OLD.pft.__file__)),
                "source_lines": [214, 223, 290, 340],
                "qualification_detail": (
                    "Frozen D eligibility: physically valid, outside IPO warm-up, not one-price limit-up, "
                    "known limit. D+1 must be exact, valid, same epoch, limit-known, and free of regular/alt5 "
                    "opening cap proxy. Mature target must be exact, valid, same epoch, known limit and free of "
                    "regular/alt5 close-down cap. Frozen fee and D+1 opening denominator belong to the old "
                    "selection rule only. The new descriptive outcomes use each record's D close denominator."
                ),
            },
            "reader": {"frozen": cfg["provenance"]["bound"], "projection": binding},
            "old_wave_columns_verified_as_original_parse_cells": len(original.columns),
            "fixed_outcome_valid_n": outcomes_n,
            "fixed_outcome_status_counts": {
                col: waves[col].value_counts().to_dict() for col in [
                    *(f"close_ret_D{h}_status" for h in ENDPOINTS), "min_low_D1_D5_status",
                ]
            },
            "frozen_signal_first_timing": {
                fam: waves[f"{fam}_first_timing"].value_counts().to_dict()
                for fam in (*OLD.FAMILIES, "any_frozen_signal")
            },
            "frozen_signal_window_coverage": {
                fam: waves[f"{fam}_window_status"].value_counts().to_dict()
                for fam in (*OLD.FAMILIES, "any_frozen_signal")
            },
            "warning_first_status_and_window_coverage": {
                name: {key: waves[f"warning_{name}_{key}"].value_counts().to_dict()
                       for key in ("first_status", "window_status")}
                for name in WARNING_NAMES
            },
            "matches": {
                "event_n": len(pairs), "matched_n": int(pairs.matching_status.eq("MATCHED").sum()),
                "unmatched_event_ids": pairs.loc[pairs.matching_status.eq("UNMATCHED"), "event_id"].tolist(),
                "ordinary_mother_pool_n": 99793, "ordinary_eligible_seven_by_stock": controls,
                "rule": (
                    "Within stock and calendar year, process event D then event_id. Select nearest exchange "
                    "calendar ordinal, preferring earlier date on a tie. Remove each selected control. Match "
                    "before reading outcomes. Ordinary eligibility is the exact ACT-058A frozen mother pool."
                ),
                "control_frozen_forward_status": pairs.control_frozen_forward_status.value_counts().to_dict(),
                "stats_pair_valid": "Use event minus ordinary, complete pairs per field; within-stock year mean, equal valid years per stock, equal valid stocks.",
            },
            "representative_examples": examples,
            "all_wave_continuous_and_peak_endpoint": distributed.loc[distributed.security_id.eq("ALL")].to_dict("records"),
            "outputs": [OLD.identity(path) for path in (WAVE, STATS)],
            "governance": {
                "FIT": 0, "cumulative_FIT": 291, "model_load": 0, "predict": 0, "tune": 0,
                "simulate": 0, "order": 0, "STRICT_PIT": 0, "TRAIN_ADMITTED": 0,
                "NO_GO_BLOCKED": True, "RESEARCH_ONLY": True, "production_allowed": False,
                "orders_sent": False, "buy_gate_updated": False,
            },
        }
        stage("verification")
        del frame, event, signals, original, stats, stat_output, waves, pairs, output
        gc.collect()
        stage("cleanup")

    receipt["runtime"] = {
        "interpreter": sys.executable, "python_version": sys.version.split()[0],
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "phase_wall_s": wall | {"upload": None}, "phase_process_cpu_s": cpu,
        "upload_status": "NOT_RUN_WRITER",
        "wall_s_through_cleanup": perf_counter() - start, "process_cpu_s_through_cleanup": process_time() - start_cpu,
        "logical_distinct_listed_explicit_input_bytes": sum(x["bytes"] for x in sources.values()),
        "projected_reader_deep_bytes": binding["retained_table_deep_bytes"],
        "logical_csv_output_bytes": sum(x["bytes"] for x in receipt["outputs"]),
        "physical_backing_io_bytes": None,
    }
    receipt["cleanup"] = {"temporary_files_created": 0, "temporary_files_removed": 0,
                          "retained_reader_copies": 0, "dedicated_workers_started": 0,
                          "in_memory_frames_released": True}
    RECEIPT.write_text(json.dumps(clean_json(receipt), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    assert RECEIPT.stat().st_size <= 9_500_000
    assert OLD.read_json(RECEIPT)["fixed_outcome_valid_n"] == outcomes_n
    print(json.dumps({"status": receipt["status"], "outcomes": outcomes_n,
                      "matched_n": receipt["matches"]["matched_n"],
                      "stats_rows": stats_rows,
                      "outputs": [(x["path"].split("/")[-1], x["bytes"]) for x in receipt["outputs"]],
                      "runtime": receipt["runtime"]["phase_wall_s"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
