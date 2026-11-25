"""ACT-061A strict same-stock control reconstruction from the frozen V4 Reader."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time
from zipfile import ZipFile

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits


BASELINE = "5477c6a3440fdec9dbf7d90b61e520e74fe9626b"
BASE = Path("/Users/lexi/Desktop/学习/v4_app")
BATCH = BASE / "artifacts/act061a_kb42_exit_20261125"
WORKTREE_ARTIFACTS = Path(__file__).resolve().parents[1]
ACT060 = "act060a_kb35_20261125"
ACT059 = "act059a_kb42_20261125"
CSV_NAME = "ACT061A_KB42_CLEAN_CONTROLS_84.csv"
RECEIPT = "ACT061A_CONTROLS_COMPUTE.json"
CANARY_RECEIPT = "ACT061A_CONTROLS_CANARY.json"
CANARY = "600016.SH"
GUARD = 25
HORIZON = 20
RULE = (
    "ACT058A ordinary parent; exact known D-1 Reader close>=white and close>=yellow; "
    "absolute exchange-session distance >=25; control D outside every frozen event's "
    "inclusive [-5,+20]; no overlap of inclusive D..D+20 windows; >=20 sessions before "
    "freeze; 20 valid same-D-basis OHLCV slots. Rank same year first, then absolute "
    "ordinal distance, then earlier date. Future bars contribute presence/validity only."
)


def load_helpers():
    sys.path[:0] = [
        str(WORKTREE_ARTIFACTS / ACT060),
        str(BASE / "artifacts" / ACT059),
    ]
    import compute060 as inherited
    from metric_a import OLD
    import wave_b

    return inherited, OLD, wave_b


def read_inputs(batch, inherited, old, wave_b):
    """Lock all main keys using only dates and accepted completeness flags."""
    manifest_path = batch / "inputs/source_manifest.json"
    manifest = old.read_json(manifest_path)
    sources = {"dispatch_manifest": old.identity(manifest_path)}
    for name, stamp in manifest["local_inputs"].items():
        sources[name] = inherited.assert_identity(batch / "inputs" / name, stamp)
    for name, stamp in manifest["accepted_local_inputs"].items():
        sources[Path(name).name] = inherited.assert_identity(BASE / name, stamp)

    prior060 = BASE / "artifacts" / ACT060
    final_path = prior060 / "ACT060A_FINAL_DELIVERY_VERIFIED.json"
    final = old.read_json(final_path)
    assert final["source_commit"] == BASELINE
    sources["act060_final"] = old.identity(final_path)
    deliveries = {entry["name"]: entry for entry in final["files"]}
    pair_name = inherited.PAIR_NAME
    assert sources[pair_name]["sha256"] == deliveries[pair_name]["sha256"]
    receipt_path = prior060 / "delivery/ACT060A_0FIT_RECEIPT.json"
    sources["act060_receipt"] = inherited.assert_identity(receipt_path, deliveries[receipt_path.name])
    receipt = old.read_json(receipt_path)
    compute_path = prior060 / "evidence/ACT060A_COMPUTE_RECEIPT.json"
    sources["act060_compute"] = inherited.assert_identity(
        compute_path, receipt["local_evidence"][compute_path.name]["identity"])
    accepted = old.read_json(compute_path)
    for name, path in {
        "act058_compute_receipt": old.ROOT / "evidence/compute_receipt.json",
        "compute.py": Path(old.__file__),
        "wave_b.py": Path(wave_b.__file__),
        "metric_a.py": BASE / "artifacts" / ACT059 / "metric_a.py",
        "export.py": old.ACT56 / "task2/export.py",
        "scan050.py": Path(old.pft.__file__),
    }.items():
        sources[name] = inherited.assert_identity(path, accepted["sources"][name])
    sources["compute060.py"] = inherited.assert_identity(Path(inherited.__file__), accepted["code"])
    prior = old.read_json(Path(sources["act058_compute_receipt"]["path"]))
    assert prior["precursor"]["ordinary"] == sum(prior["precursor"]["ordinary_by_stock"].values()) == 99793
    for name, stamp in prior["source_identity"].items():
        sources[name] = inherited.assert_identity(Path(stamp["path"]), accepted["sources"][name])
    r56 = old.read_json(Path(sources["r56_path"]["path"]))
    r50 = old.read_json(Path(sources["r50_path"]["path"]))
    event_key_path = Path(sources["key_path"]["path"])
    frozen = old.read_json(event_key_path)
    key_columns = ["security_id", "D", "exchange_session_ordinal", "full20", "hidden"]
    keys = pd.DataFrame(frozen["rows"], columns=frozen["event_columns"])[key_columns]
    assert len(keys) == 3374 and int(keys.hidden.sum()) == 3244
    assert not keys.duplicated(["security_id", "D"]).any()
    assert not keys.duplicated(["security_id", "exchange_session_ordinal"]).any()

    cards_path = Path(sources["02_ACT058B_KB42_CARDS.csv"]["path"])
    cards = pd.read_csv(cards_path, usecols=["security_id", "name", "archetype_frozen"]).set_index("security_id")
    assert len(cards) == 42 and cards.index.is_unique and set(cards.index) == set(keys.security_id)
    assert cards.archetype_frozen.value_counts().to_dict() == {"A": 18, "B": 16, "C": 7, "D": 1}
    table060 = pd.read_csv(Path(sources[pair_name]["path"]),
                           usecols=["security_id", "case_id", "role", "D", "D_ordinal", "sample_window",
                                    "bars_Dm10_to_Dp20_json", "full20"])
    assumed35 = {code for group in inherited.ROSTER.values() for code in group.split()}
    mains060 = table060[table060.role.eq("MAIN_REVERSE_EVENT")].set_index("security_id")
    assert len(mains060) == 35 and mains060.index.is_unique and set(mains060.index) == assumed35
    assert mains060.full20.all()
    assert all(row.case_id == f"{code}/{row.D}" for code, row in mains060.iterrows())
    assert mains060.at[CANARY, "case_id"] == "600016.SH/20241114"
    assert mains060[mains060.sample_window.ne("RECENT_2Y")].index.tolist() == [CANARY]
    for code, row in mains060.iterrows():
        assert accepted["by_stock"][code]["main_case_id"] == row.case_id

    old_keys = set(old.WAVES)
    assert old_keys == set(cards.index) - assumed35
    accepted059 = pd.read_csv(Path(sources["ACT059A_108_WAVES_SUPPLEMENT.csv"]["path"]),
                              usecols=["security_id", "D", "event_id", "peak_status"])
    recent = keys[keys.security_id.isin(old_keys) & keys.D.between(int(old.START), int(old.END))]
    joined = recent.merge(accepted059, on=["security_id", "D"], validate="one_to_one")
    assert len(joined) == len(accepted059) == len(recent) == 108 and int(joined.full20.sum()) == 107
    assert joined.full20.eq(joined.peak_status.eq("FULL_WINDOW")).all()
    mains059 = joined[joined.full20].sort_values("D").groupby("security_id").tail(1)
    assert set(mains059.security_id) == old_keys
    locks = {
        code: (row.case_id, int(row.D), int(row.D_ordinal), row.sample_window, "ACT060A_FIXED_KEY")
        for code, row in mains060.iterrows()
    }
    locks.update({
        row.security_id: (row.event_id, int(row.D), int(row.exchange_session_ordinal),
                          "RECENT_2Y", "LATEST_COMPLETE_RECENT_ACT059A")
        for row in mains059.itertuples(index=False)
    })
    confirmations = keys.set_index(["security_id", "D"])
    for code, (key, day, ordinal, _, _) in locks.items():
        row = confirmations.loc[(code, day)]
        assert key == f"{code}/{day}" and row.full20 and int(row.exchange_session_ordinal) == ordinal
    main_lock_path = batch / "inputs/ACT061A_MAIN_PATH_LOCK.json"
    main_lock = old.read_json(main_lock_path)["rows"]
    assert len(main_lock) == len(locks) == 42
    assert {row["security_id"]: (row["main_id"], row["D"], row["scope"]) for row in main_lock} == {
        code: (key, day, "ACT059A_LATEST_FULL20" if code in old_keys else window)
        for code, (key, day, _, window, _) in locks.items()
    }
    sources["main_path_lock"] = old.identity(main_lock_path)
    return cards, keys, locks, r56, r50, prior, accepted, table060, sources


def complete_windows(stock, ordinals):
    """Check only presence, validity and same-basis geometry, as in Stock.get."""
    columns = ordinals[:, None] + np.arange(1, HORIZON + 1)
    row_by_ordinal = np.full(len(stock.calendar), -1, dtype=int)
    row_by_ordinal[stock.positions] = np.arange(len(stock.positions))
    rows = row_by_ordinal[columns]
    anchors = row_by_ordinal[ordinals]
    assert (anchors >= 0).all() and stock.valid[anchors].all()
    observed = (rows >= 0) & stock.valid[rows]
    observed &= stock.basis[rows] == stock.basis[anchors, None]
    numbers = stock.values[rows, :5].copy()
    numbers[:, :, :4] = (numbers[:, :, :4] - stock.b[anchors, None, None]) / stock.a[anchors, None, None]
    numbers[:, :, 4] /= stock.v[anchors, None]
    observed &= (np.isfinite(numbers) & (numbers > 0)).all(axis=2)
    return observed.all(axis=1)


def choose_control(stock, main, ordinary, event_ordinals, inherited):
    main_state = inherited.known_state(stock, main)
    counts = {"ordinary_parent_n": len(ordinary)}
    pool = ordinary[np.abs(ordinary - main) >= GUARD]
    counts["after_main_distance_n"] = len(pool)
    delta = pool[:, None] - event_ordinals[None, :]
    pool = pool[~((delta >= -5) & (delta <= HORIZON)).any(axis=1)]
    counts["after_all_event_intervals_n"] = len(pool)
    pool = pool[(pool + HORIZON < main) | (pool > main + HORIZON)]
    counts["after_window_nonoverlap_n"] = len(pool)
    pool = pool[len(stock.calendar) - 1 - pool >= HORIZON]
    counts["after_freeze_distance_n"] = len(pool)
    pool = np.array([day for day in pool
                     if main_state is not None and inherited.known_state(stock, day) == main_state], dtype=int)
    counts["after_exact_known_Dm1_state_n"] = len(pool)
    pool = pool[complete_windows(stock, pool)]
    counts["after_complete20_same_D_basis_n"] = len(pool)
    year = str(stock.calendar[main])[:4]
    same = pool[np.char.startswith(stock.calendar[pool], year)]
    counts["same_year_final_n"] = len(same)
    counts["cross_year_final_n"] = len(pool) - len(same)
    ranked = same if same.size else pool
    rank_order = sorted((abs(int(day) - main), int(day)) for day in ranked)
    selected = rank_order[0][1] if rank_order else None
    if selected is not None:
        tier = "SAME_YEAR" if same.size else "FALLBACK_CROSS_YEAR"
        order = np.lexsort((ranked, np.abs(ranked - main)))
        assert int(ranked[order[0]]) == selected
        reason = None
    else:
        tier = "CANNOT_CONFIRM_UNMATCHED"
        reason = ("MAIN_D_MINUS_1_STATE_UNKNOWN" if main_state is None else
                  next(name for name, n in counts.items() if n == 0))
    return selected, {
        **counts,
        "match_tier": tier,
        "unmatched_reason": reason,
        "main_Dm1_line_state": inherited.state_text(main_state),
        "rank_pool_ordinals_sha256": sha256(inherited.compact(sorted(map(int, ranked))).encode()).hexdigest(),
        "rank_first_two_distance_and_ordinals": rank_order[:2],
        "control_D": str(stock.calendar[selected]) if selected is not None else None,
    }


def signals_after_lock(old, sources, keys):
    with ZipFile(sources["zip_path"]["path"]) as archive:
        base = pd.read_csv(archive.open("kb47_all_signals_and_breakouts.csv"), usecols=old.SIG_COLS)
    with ZipFile(sources["htfz_path"]["path"]) as archive:
        extra = pd.read_csv(archive.open("000547_all_signals_and_breakouts.csv"), usecols=old.SIG_COLS)
    signals = pd.concat([base, extra], ignore_index=True)
    reverse = signals[signals.reverse_independent][["security_id", "D", "exchange_session_ordinal", "forward_any"]]
    aligned = keys.merge(reverse, on=["security_id", "D", "exchange_session_ordinal"], validate="one_to_one")
    assert len(aligned) == len(reverse) == len(keys) and aligned.hidden.eq(~aligned.forward_any).all()
    assert signals.forward_any.eq(signals[list(old.FAMILIES)].any(axis=1)).all()
    assert not signals.duplicated(["security_id", "exchange_session_ordinal"]).any()
    return signals


def event_interval_audit(ordinal, event_ordinals, calendar):
    differences = ordinal - event_ordinals
    minimum = int(np.abs(differences).min())
    nearest = int(event_ordinals[np.argmin(np.abs(differences))])
    return {
        "min_dist_to_any_event": minimum,
        "nearest_known_event_D": str(calendar[nearest]),
        "signed_dist_to_nearest_known_event": ordinal - nearest,
        "D_in_any_known_event_exclusion_window": bool(
            ((differences >= -5) & (differences <= HORIZON)).any()),
    }


def measure_row(stock, at, events, signals, inherited, old, wave_b):
    path = inherited.path_context(stock, at)
    post_path = path[10:]
    statuses = tuple(bar[2] for bar in post_path)
    bars = tuple(bar[-1] for bar in post_path)
    assert statuses[0] == "OBSERVED"
    missing = [bar[0] for bar in post_path[1:] if bar[2] != "OBSERVED"]
    lines_missing = [bar[0] for bar in post_path[1:] if bar[-1] is None or None in bar[-1][5:7]]
    endpoints = wave_b.outcomes(bars, statuses, stock.calendar, at, (5, 10, 20))
    d_signal = signals.get(at, {})
    signal_timing = inherited.pair_signal(stock, at, signals)
    anchor = stock.available_rows[at]
    price_scale, price_offset, volume_scale = stock.a[anchor], stock.b[anchor], stock.v[anchor]
    signal_fields = {
        key: value for key, value in signal_timing.items()
        if key.startswith("any_frozen_signal_") or "_first_" in key or "_actual_" in key
    }
    return {
        "case_id": f"{stock.code}/{stock.calendar[at]}",
        "D": str(stock.calendar[at]),
        "calendar_year": str(stock.calendar[at])[:4],
        "D_ordinal": at,
        "D_minus_1_date": str(stock.calendar[at - 1]),
        "D_minus_1_line_state": inherited.state_text(inherited.known_state(stock, at)),
        "D_frozen_status": wave_b.HIT if d_signal.get("forward_any") else old.signal_status(stock, at),
        "D_frozen_families": "|".join(fam for fam in old.FAMILIES if d_signal.get(fam)),
        **signal_fields,
        "bars_to_freeze_date": len(stock.calendar) - 1 - at,
        "complete_20bars": not missing,
        "missing_D1_D20_n": len(missing),
        "missing_D1_D20_offsets": inherited.compact(missing),
        "missing_D1_D20_dual_line_n": len(lines_missing),
        **event_interval_audit(at, events, stock.calendar),
        "d_affine_price_scale": price_scale,
        "d_affine_price_offset": price_offset,
        "d_affine_volume_scale": volume_scale,
        "bars_layout": "|".join(inherited.BAR_LAYOUT),
        "bar_values_layout": "|".join(inherited.FIELDS),
        "bars_Dm10_to_Dp20_json": inherited.compact(path),
        **endpoints,
    }


def rows_for_pair(stock, plan, card, signals, inherited, old, wave_b):
    key, _, main, window, source = plan["main"]
    control, events = plan["control"], plan["event_ordinals"]
    control_id = f"{stock.code}/{stock.calendar[control]}" if control is not None else None
    distance = control - main if control is not None else None
    group = {
        "pair_id": key,
        "security_id": stock.code,
        "name": card["name"],
        "archetype": card.archetype_frozen,
        "fixed_main_source": source,
        "main_sample_window": window,
        "main_recent_2y_status": "0_IN_2Y" if window == "FALLBACK_HISTORY" else "HAS_COMPLETE_IN_2Y",
        "matching_status": "MATCHED" if control is not None else "CANNOT_CONFIRM_UNMATCHED",
        "match_tier": plan["audit"]["match_tier"],
        "unmatched_reason": plan["audit"]["unmatched_reason"],
        "distance_sessions": abs(distance) if distance is not None else None,
        "signed_control_minus_main_sessions": distance,
        "overlap_days": max(0, HORIZON + 1 - abs(distance)) if distance is not None else None,
        **{name: value for name, value in plan["audit"].items() if name.endswith("_n")},
    }
    signal_map = signals.set_index("exchange_session_ordinal").to_dict("index")
    for row in signals.itertuples(index=False):
        assert int(stock.calendar[row.exchange_session_ordinal]) == row.D
    main_data = measure_row(stock, main, events, signal_map, inherited, old, wave_b)
    assert main_data["case_id"] == key and main_data["complete_20bars"]
    assert main_data["D_frozen_status"] == (wave_b.NO_HIT if plan["main_hidden"] else wave_b.HIT)
    main_row = group | {"role": "MAIN_REVERSE_EVENT", "matched_case_id": control_id} | main_data
    control_data = dict.fromkeys(main_data)
    if control is not None:
        control_data = measure_row(stock, control, events, signal_map, inherited, old, wave_b)
        assert control_data["case_id"] == control_id
        assert control_data["min_dist_to_any_event"] > 5
        assert not control_data["D_in_any_known_event_exclusion_window"]
        assert control_data["D_minus_1_line_state"] == main_data["D_minus_1_line_state"] != "UNKNOWN"
        assert group["overlap_days"] == 0 and abs(distance) >= GUARD
        assert control_data["complete_20bars"] and control_data["bars_to_freeze_date"] >= HORIZON
        assert all(control_data[f"close_ret_D{h}_status"] == "OBSERVED" for h in (5, 10, 20))
    control_row = group | {"role": "SAME_STOCK_ORDINARY_CONTROL", "matched_case_id": key} | control_data
    return main_row, control_row


def prior_audit(table060):
    prior_main = table060[table060.role.eq("MAIN_REVERSE_EVENT")].set_index("security_id")
    prior_control = table060[table060.role.ne("MAIN_REVERSE_EVENT")].set_index("security_id")
    assert prior_control.index.is_unique and set(prior_control.index) == set(prior_main.index)
    prior_overlap = (prior_control.D_ordinal - prior_main.D_ordinal).abs().le(HORIZON)
    assert int(prior_overlap.sum()) == 34 and int((~prior_control.full20).sum()) == 4
    right = sum(any(bar[2] == "RIGHT_CENSORED_AT_20261120" for bar in json.loads(path)[11:])
                for path in prior_control.bars_Dm10_to_Dp20_json)
    return {
        "ACT060A_pair_n": len(prior_main),
        "ACT060A_overlap_n": int(prior_overlap.sum()),
        "ACT060A_incomplete20_n": int((~prior_control.full20).sum()),
        "ACT060A_right_censored_control_n": right,
    }


def verify_csv(data, rows):
    reread = list(csv.DictReader(StringIO(data)))
    assert len(reread) == len(rows)
    for before, after in zip(rows, reread, strict=True):
        assert {k: "" if v is None else str(v) for k, v in before.items()} == after
        if before["case_id"] is None:
            assert before["matching_status"] == "CANNOT_CONFIRM_UNMATCHED"
            continue
        path = json.loads(after["bars_Dm10_to_Dp20_json"])
        assert [bar[0] for bar in path] == list(range(-10, HORIZON + 1))
        assert path[10][1] == before["D"]
        a = float(after["d_affine_price_scale"])
        b = float(after["d_affine_price_offset"])
        v = float(after["d_affine_volume_scale"])
        for bar in path:
            if bar[2] != "OBSERVED":
                continue
            raw = np.asarray(bar[4], dtype=float)
            converted = np.asarray(bar[5], dtype=float)
            expected = (raw - b) / a
            expected[4] = raw[4] / v
            expected[5:] = np.where(np.isfinite(expected[5:]) & (expected[5:] > 0), expected[5:], np.nan)
            np.testing.assert_array_equal(expected, converted)
        for h in (5, 10, 20):
            endpoint = path[10 + h]
            assert endpoint[1] == before[f"close_ret_D{h}_date"]
            assert endpoint[2] == before[f"close_ret_D{h}_status"] == "OBSERVED"
            assert endpoint[-1][3] == before[f"close_ret_D{h}_close_d_basis"]
            assert (endpoint[-1][3] / path[10][-1][3] - 1) * 100 == before[f"close_ret_D{h}_pct"]


def summarize(rows, plans, locks, table060):
    controls = rows[1::2]
    actual = [row for row in rows if row["case_id"] is not None]
    matched = [row for row in controls if row["case_id"] is not None]
    unmatched = [row for row in controls if row["case_id"] is None]
    assert len({row["case_id"] for row in actual}) == len(actual)
    assert len(rows) == len(plans) * 2
    assert [row["case_id"] for row in rows[::2]] == [locks[code][0] for code in sorted(plans)]
    return {
        "mains": len(plans), "prior_fixed_main_keys_confirmed_n": sum(p["main"][-1] == "ACT060A_FIXED_KEY"
                                                                      for p in plans.values()),
        "control_slots": len(controls), "matched": len(matched), "unmatched": len(unmatched),
        "actual_distinct_keys": len(actual), "csv_rows": len(rows),
        "same_year": sum(row["match_tier"] == "SAME_YEAR" for row in matched),
        "cross_year": sum(row["match_tier"] == "FALLBACK_CROSS_YEAR" for row in matched),
        "cross_year_keys": [row["case_id"] for row in matched if row["match_tier"] == "FALLBACK_CROSS_YEAR"],
        "min_distance_sessions": min((row["distance_sessions"] for row in matched), default=None),
        "max_distance_sessions": max((row["distance_sessions"] for row in matched), default=None),
        "median_distance_sessions": float(np.median([row["distance_sessions"] for row in matched])) if matched else None,
        "min_bars_to_freeze_date": min((row["bars_to_freeze_date"] for row in matched), default=None),
        "min_dist_to_any_event_among_matched": min((row["min_dist_to_any_event"] for row in matched), default=None),
        "matched_overlap_n": sum(row["overlap_days"] != 0 for row in matched),
        "matched_event_exclusion_violation_n": sum(row["D_in_any_known_event_exclusion_window"] for row in matched),
        "matched_without_20_bars_before_freeze_n": sum(row["bars_to_freeze_date"] < HORIZON for row in matched),
        "matched_incomplete_20bars_n": sum(not row["complete_20bars"] for row in matched),
        "matched_missing_dual_line_slots_n": sum(row["missing_D1_D20_dual_line_n"] for row in matched),
        "matched_endpoints_missing_n": {f"D+{h}": sum(row[f"close_ret_D{h}_status"] != "OBSERVED" for row in matched)
                                        for h in (5, 10, 20)},
        "matched_D_frozen_status": dict(Counter(row["D_frozen_status"] for row in matched)),
        "unmatched_reason_counts": dict(Counter(row["unmatched_reason"] for row in unmatched)),
        "unmatched_main_keys": [row["pair_id"] for row in unmatched],
        "old7_main_keys": {code: lock[0] for code, lock in sorted(locks.items())
                           if lock[-1] == "LATEST_COMPLETE_RECENT_ACT059A"},
        "historical_fallback_main_key": locks[CANARY][0],
        **prior_audit(table060),
    }


def main():
    start, cpu_start = perf_counter(), process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=BATCH)
    parser.add_argument("--canary", action="store_true")
    args = parser.parse_args()
    batch = args.batch.resolve()
    receipt_path = batch / "evidence" / (CANARY_RECEIPT if args.canary else RECEIPT)
    csv_path = batch / "delivery" / CSV_NAME
    assert not receipt_path.exists()
    assert args.canary or not csv_path.exists()
    inherited, old, wave_b = load_helpers()
    inherited.OLD, inherited.wave_b = old, wave_b
    arrow_cpu, arrow_io = 4, 2
    pa.set_cpu_count(arrow_cpu)
    pa.set_io_thread_count(arrow_io)

    times = {}
    phase_start, phase_cpu = start, cpu_start

    def checkpoint(name):
        nonlocal phase_start, phase_cpu
        stamp, cpu = perf_counter(), process_time()
        times[name] = {"wall_sec": stamp - phase_start, "cpu_sec": cpu - phase_cpu}
        phase_start, phase_cpu = stamp, cpu
        print(f"{name} {times[name]['wall_sec']:.3f}s", flush=True)

    with threadpool_limits(limits=1):
        cards, keys, locks, r56, r50, prior, accepted, table060, sources = read_inputs(
            batch, inherited, old, wave_b)
        codes = {CANARY} if args.canary else set(cards.index)
        cfg, frame, calendar, binding = inherited.project_reader(codes, r56, r50, prior)
        for field in ("bound", "calendar", "calendar_sha256"):
            assert binding[field] == accepted["reader"][field], field
        checkpoint("read_and_bind")
        stocks, plans = {}, {}
        for code, daily in frame.groupby("canonical", sort=True):
            stock = old.Stock(code, daily, cfg["events"][code], calendar)
            local = keys[keys.security_id.eq(code)].sort_values("exchange_session_ordinal")
            event_ordinals = local.exchange_session_ordinal.to_numpy()
            assert np.array_equal(calendar[event_ordinals].astype(int), local.D)
            ordinary = old.ordinary(stock, event_ordinals)
            assert len(ordinary) == prior["precursor"]["ordinary_by_stock"][code]
            locked = locks[code]
            assert int(calendar[locked[2]]) == locked[1]
            control, audit = choose_control(stock, locked[2], ordinary, event_ordinals, inherited)
            plans[code] = {"main": locked, "control": control, "audit": audit, "event_ordinals": event_ordinals,
                           "main_hidden": bool(local.loc[local.D.eq(locked[1]), "hidden"].item())}
            stocks[code] = stock
        assert set(plans) == codes
        if not args.canary:
            assert sum(p["audit"]["ordinary_parent_n"] for p in plans.values()) == 99793
        plan_text = inherited.compact({code: {
            "main": p["main"], "control": p["control"], "candidate_audit": p["audit"],
        } for code, p in plans.items()})
        plan_sha = sha256(plan_text.encode()).hexdigest()
        checkpoint("lock_control_dates")
        signals = signals_after_lock(old, sources, keys)
        checkpoint("read_frozen_signals")
        rows = []
        for code, plan in plans.items():
            rows.extend(rows_for_pair(stocks[code], plan, cards.loc[code], signals[signals.security_id.eq(code)],
                                      inherited, old, wave_b))
        rows = [inherited.clean(row) for row in rows]
        buffer = StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        data = buffer.getvalue()
        result = summarize(rows, plans, locks, table060)
        checkpoint("compute_locked_paths")
        verify_csv(data, rows)
        data_bytes = data.encode("utf-8-sig")
        assert len(data_bytes) <= inherited.HARD_BYTES
        if not args.canary:
            assert result["mains"] == 42 and result["control_slots"] == 42 and result["csv_rows"] == 84
        checkpoint("verify_csv_before_write")

    csv_identity = None
    if not args.canary:
        with csv_path.open("xb") as handle:
            handle.write(data_bytes)
        csv_identity = old.identity(csv_path)
        assert csv_identity["sha256"] == sha256(data_bytes).hexdigest()
    checkpoint("write_readback")
    status = "CANNOT_CONFIRM_UNMATCHED_CONTROLS" if result["unmatched"] else "PASS_STRICT_CONTROLS"
    if args.canary:
        status = "CANARY_" + status
    out = {
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE,
        "code": old.identity(Path(__file__).resolve()),
        "sources": sources,
        "reader": binding,
        "frozen_event_n": len(keys),
        "frozen_ordinary_parent_n": prior["precursor"]["ordinary"],
        "event_exclusion_offsets_inclusive": [-5, HORIZON],
        "minimum_distance_sessions": GUARD,
        "freeze_date": old.END,
        "control_rule": RULE,
        "old7_selection_rule": "ACT-060A main policy applied before matching. ACT-060B manual §6 fixes two extreme "
                               "cases per old stock and specifies no single fixed main. Choose the latest complete "
                               "recent ACT-057 key checked against the ACT-059A accepted 108-wave table.",
        "pair_date_plan_sha256": plan_sha,
        "summary": result,
        "by_stock": {code: {"main_case_id": plan["main"][0], **plan["audit"]} for code, plan in plans.items()},
        "output": csv_identity,
        "in_memory_csv_bytes": len(data_bytes),
        "runtime": {
            "phases": times, "total_wall_sec": perf_counter() - start, "total_cpu_sec": process_time() - cpu_start,
            "resident_peak_bytes_on_macos": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "logical_hashed_input_bytes": sum(x["bytes"] for x in sources.values()),
            "interpreter": sys.executable,
            "arrow_cpu_threads": arrow_cpu, "arrow_io_threads": arrow_io, "native_compute_threads_cap": 1,
        },
        "temporary_files_created": [],
        "FIT": 0,
        "cumulative_research_FIT": 291,
        "model_load_calls": 0,
        "model_inference_calls": 0,
        "simulated_trades": 0,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "historical_PIT": binding["bound"]["historical_PIT"],
    }
    inherited.write_json_exclusive(receipt_path, out)
    print(inherited.compact({"status": status, "summary": result, "output": csv_identity,
                             "recipe": str(receipt_path)}), flush=True)


if __name__ == "__main__":
    main()
