"""ACT-060A frozen KB35 research export. This entry point reads the existing Reader only."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gc
from hashlib import sha256
from html import escape
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits


BASELINE = "8a4f86206bafcfa9a77651b8d4eedb213b9bfbd4"
ROSTER = {
    "A": "000058.SZ 000625.SZ 000776.SZ 001219.SZ 002074.SZ 002242.SZ 002345.SZ 002594.SZ 300582.SZ 600016.SH 600184.SH 600366.SH 600895.SH 600989.SH 601778.SH 688321.SH",
    "B": "000156.SZ 000948.SZ 002670.SZ 002779.SZ 002940.SZ 300378.SZ 300528.SZ 600601.SH 603920.SH 605378.SH 605488.SH 688787.SH",
    "C": "300689.SZ 301080.SZ 688621.SH 688663.SH 688799.SH 920039.BJ",
    "D": "920748.BJ",
}
CANARY = "600016.SH"
FIELDS = ("open", "high", "low", "close", "volume", "white", "yellow")
SHORT_FIELDS = ("O", "H", "L", "C", "V", "W", "Y")
BAR_LAYOUT = ("offset", "date", "status", "raw_security_id", "reader_qfq", "d_basis")
WAVE_NAME = "ACT060A_KB35_2Y_WAVES_ALL.csv"
PAIR_NAME = "ACT060A_KB35_REP_AND_CONTROL_70.csv"
PACK_NAME = "ACT060A_KB35_SVG_PACK_35.zip"
RECEIPT_NAME = "ACT060A_COMPUTE_RECEIPT.json"
CANARY_NAME = "ACT060A_COMPUTE_CANARY.json"
HARD_BYTES = 9_500_000
CONTROL_RULE = (
    "Within the frozen ordinary mother pool of the same security and calendar year, "
    "prefer the exact known D-1 (Reader close >= white, close >= yellow) state. "
    "If no exact known state is available, use all eligible same-year dates. "
    "Minimize absolute exchange-session distance, then prefer the earlier date. "
    "No D-day, signal or outcome values are used for ranking; one control per stock."
)


def assert_identity(path, expected):
    actual = OLD.identity(path)
    assert (actual["bytes"], actual["sha256"]) == (expected["bytes"], expected["sha256"]), str(path)
    return actual


def verify_inputs(batch, previous):
    sources = {}
    incoming = batch / "inputs"
    source_manifest = incoming / "source_manifest.json"
    sources["master_manifest"] = OLD.identity(source_manifest)
    master = OLD.read_json(source_manifest)
    for entry in master["exact_drive_source_bytes"] + master["text_projection"]:
        sources[entry["name"]] = assert_identity(incoming / entry["name"], entry)

    old_final_path = OLD.ROOT / "ACT058A_FINAL_DELIVERY_VERIFIED.json"
    final_path = previous / "ACT059A_FINAL_DELIVERY_VERIFIED.json"
    sources["act058_final"] = OLD.identity(old_final_path)
    sources["act059_final"] = OLD.identity(final_path)
    final = OLD.read_json(final_path)
    assert final["source_sync"]["commit"] == BASELINE
    for filename, stamp in final["source_sync"]["files"].items():
        filename = Path(filename).name
        sources[filename] = assert_identity(previous / filename, stamp)
    for entry in final["outputs"]:
        if entry["name"] in (wave_b.WAVE.name, "ACT059A_0FIT_RECEIPT.json"):
            sources[entry["name"]] = assert_identity(previous / "delivery" / entry["name"], entry)

    wave_receipt = OLD.read_json(wave_b.RECEIPT)
    sources["act059_wave_receipt"] = OLD.identity(wave_b.RECEIPT)
    old_receipt = OLD.ROOT / "delivery/ACT058A_0FIT_RECEIPT.json"
    previous_outputs = {entry["name"]: entry for entry in OLD.read_json(old_final_path)["files"]}
    sources[old_receipt.name] = assert_identity(old_receipt, previous_outputs[old_receipt.name])
    compute_path = OLD.ROOT / "evidence/compute_receipt.json"
    sources["act058_compute_receipt"] = assert_identity(compute_path, OLD.read_json(old_receipt)["compute_evidence"])
    prior = OLD.read_json(compute_path)

    for key, path in (("compute.py", Path(OLD.__file__)), ("export.py", OLD.ACT56 / "task2/export.py"),
                      ("scan050.py", Path(OLD.pft.__file__))):
        sources[key] = assert_identity(path, wave_receipt["source_inputs"][key])
    assert_identity(Path(OLD.__file__), prior["code"])

    prof, events, signals, fingerprints, r56, r50, frozen = OLD.frozen_inputs()
    for key, stamp in frozen.items():
        for inherited in (prior["source_identity"][key], wave_receipt["source_inputs"][key]):
            assert (stamp["sha256"], stamp["bytes"]) == (inherited["sha256"], inherited["bytes"]), key
        sources[key] = stamp
    assert frozen["key_path"]["sha256"] == OLD.read_json(Path(frozen["old_receipt"]["path"]))["event_keys"]["sha256"]

    cards = pd.read_csv(incoming / "02_ACT058B_KB42_CARDS.csv")
    expected = {code: archetype for archetype, codes in ROSTER.items() for code in codes.split()}
    assert cards.security_id.is_unique and len(cards) == 42
    assert set(cards.security_id) == set(expected) | set(OLD.WAVES)
    assert set(expected).isdisjoint(OLD.WAVES)
    assert {row.security_id: row.archetype_frozen for row in cards.itertuples()
            if row.security_id in expected} == expected
    card_shape = cards[["security_id", "name", "archetype_frozen", "all_reverse_events", "hidden_same_day_n"]]
    frozen_shape = prof[["security_id", "name", "archetype", "all_event_n", "hidden_n"]]
    for card_card, frozen_card in zip(
        card_shape.sort_values("security_id").itertuples(index=False, name=None),
        frozen_shape.sort_values("security_id").itertuples(index=False, name=None),
        strict=True,
    ):
        assert card_card == frozen_card, card_card
    with wave_b.WAVE.open(encoding="utf-8-sig", newline="") as handle:
        columns = next(csv.reader(handle))
    assert len(columns) == 344 and len(set(columns)) == len(columns)
    return cards.set_index("security_id"), events, signals, fingerprints, r56, r50, prior, sources, columns


def project_reader(codes, r56, r50, prior):
    pft = OLD.pft
    cfg = pft.p47.previous.bind()
    bound = cfg["provenance"]["bound"]
    assert bound == r50["source"]["bound"] == r56["frozen_source"] == prior["frozen_reader"]
    assert str(bound["asof"]) == OLD.END
    aliases = sorted({raw for code in codes for raw in cfg["groups"][code]})
    cols = ("ts_code", "trade_date", "exchange", "market_type", "open", "high", "low",
            "close", "vol", "tradeable_basic", "zge_white_line", "zge_yellow_line")
    observed = pft.rd.projected(cfg["panel"], cfg["schema"], aliases, columns=cols, start=pft.FIRST, end=pft.END)
    observed["trade_date"] = observed.trade_date.astype(str).str.replace("-", "", regex=False)
    original_rows = len(observed)
    ignored = set()
    for code in pft.CORRECTED_BSE.intersection(codes):
        aliases_here = set(cfg["groups"][code]) - {code}
        modern = observed.loc[observed.ts_code.eq(code)]
        old = observed.loc[observed.ts_code.isin(aliases_here)]
        assert not modern.empty and code in cfg["events"][code]
        assert set(old.trade_date) <= set(modern.trade_date), code
        assert len(old) == r50["aliases"][code]["alias_rows_discarded"], code
        ignored.update(aliases_here)
    if ignored:
        observed = observed.loc[~observed.ts_code.isin(ignored)]
    frame = pft.rd.normalize(observed, cfg["frozen"])
    assert set(frame.canonical) == set(codes)
    expected_calendar = r50["calendar"]
    assert expected_calendar == r56["calendar"]
    # The pre-census calendar includes dates contributed by the other frozen parents.
    # This key-only read uses the same 41 parents and four anchors as ACT-050.
    census = cfg["dates"]
    chosen = pft.load_inputs()[1]
    crosswalk = cfg["frozen"]["raw_to_canonical"]
    parent_codes = {crosswalk.get(row["security_id"], row["security_id"]) for row in chosen}
    historical_aliases = sorted({raw for code in parent_codes for raw in cfg["groups"][code]}
                                .union(pft.DATE_ANCHORS))
    keys = pft.rd.projected(cfg["panel"], cfg["schema"], historical_aliases,
                            columns=["ts_code", "trade_date", "exchange", "market_type"],
                            start=pft.FIRST, end=census[0])
    keys["trade_date"] = keys.trade_date.astype(str).str.replace("-", "", regex=False)
    anchors = keys.loc[keys.ts_code.isin(pft.DATE_ANCHORS), "trade_date"]
    historical_ignored = {raw for code in pft.CORRECTED_BSE for raw in cfg["groups"][code] if raw != code}
    eligible = ~keys.ts_code.isin(set(pft.DATE_ANCHORS) | historical_ignored)
    history = pft.rd.normalize(keys.loc[eligible], cfg["frozen"])
    calendar = sorted(set(frame.trade_date).union(anchors, history.trade_date, census))
    assert [d for d in calendar if d >= census[0]] == census
    assert (calendar[0], calendar[-1], len(calendar), calendar.index(census[0])) == (
        expected_calendar["start"], expected_calendar["end"],
        expected_calendar["sessions"], expected_calendar["pre_census_sessions"])
    return cfg, frame, np.asarray(calendar, dtype="U8"), {
        "bound": bound, "numeric_projected_rows": original_rows, "numeric_fields": cols,
        "retained_rows": len(frame), "retained_deep_bytes": int(frame.memory_usage(deep=True).sum()),
        "historical_calendar_key_rows": len(keys), "calendar_key_parent_n": len(parent_codes),
        "date_anchor_rows": len(anchors), "date_anchor_ids": pft.DATE_ANCHORS,
        "discarded_aliases": sorted(ignored), "calendar": expected_calendar,
        "calendar_sha256": sha256("\n".join(calendar).encode()).hexdigest(),
    }


def known_state(stock, ordinal):
    prior = stock.available_rows.get(ordinal - 1)
    if prior is None or not stock.valid[prior]:
        return None
    close, white, yellow = stock.values[prior, [3, 5, 6]]
    if not np.isfinite((close, white, yellow)).all() or min(white, yellow) <= stock.b[prior]:
        return None
    return bool(close >= white), bool(close >= yellow)


def state_text(state):
    return "".join("1" if above else "0" for above in state) if state is not None else "UNKNOWN"


def choose_pair(stock, local, ordinary):
    recent = local.D.between(int(OLD.START), int(OLD.END))
    eligible = local.loc[recent & local.full20]
    window = "RECENT_2Y"
    if eligible.empty:
        eligible = local.loc[local.full20]
        window = "FALLBACK_HISTORY"
    if eligible.empty:
        raise ValueError(f"NO_COMPLETE_FROZEN_MAIN:{stock.code}")
    selected = eligible.sort_values("D").iloc[-1]
    main = int(selected.exchange_session_ordinal)
    year = str(stock.calendar[main])[:4]
    candidates = [int(x) for x in ordinary if str(stock.calendar[x])[:4] == year]
    if not candidates:
        raise ValueError(f"NO_SAME_YEAR_ELIGIBLE_CONTROL:{stock.code}/{selected.D}")
    main_state = known_state(stock, main)
    exact = [day for day in candidates if main_state is not None and known_state(stock, day) == main_state]
    ranked = exact or candidates
    control = min(ranked, key=lambda ordinal: (abs(ordinal - main), ordinal))
    # Recheck the winning rank, without materializing D or any outcome.
    by_nearest = sorted(candidates, key=lambda day: (abs(day - main), day))
    first_exact = next((day for day in by_nearest
                        if main_state is not None and known_state(stock, day) == main_state), None)
    assert control == (first_exact if first_exact is not None else by_nearest[0])
    assert abs(control - main) > OLD.END_ORDINAL_GUARD
    return main, control, {
        "sample_window": window, "recent_event_n": int(recent.sum()),
        "recent_full20_n": int((recent & local.full20).sum()),
        "recent_complete_status": "HAS_COMPLETE_IN_2Y" if (recent & local.full20).any() else "0_IN_2Y",
        "main_reason": "LATEST_RECENT_FULL20" if window == "RECENT_2Y" else "LATEST_FROZEN_HISTORY_FULL20",
        "main_Dm1_line_state": state_text(main_state),
        "main_Dm1_date": str(stock.calendar[main - 1]),
        "control_Dm1_line_state": state_text(known_state(stock, control)),
        "control_Dm1_date": str(stock.calendar[control - 1]),
        "control_matching_mode": "EXACT_KNOWN_D_MINUS_1_LINES" if exact else "NEAREST_ELIGIBLE_FALLBACK",
        "control_same_year_pool_n": len(candidates), "control_exact_state_pool_n": len(exact),
        "control_distance_sessions": abs(control - main),
        "control_signed_distance_sessions": control - main,
    }


def first_warning(stock, at, bars, statuses):
    checks = {}
    for offset in range(1, 21):
        current, previous = bars[offset], bars[offset - 1]
        current_status, previous_status = statuses[offset], statuses[offset - 1]
        checks[offset] = {
            "white_downcross": wave_b.crossing(previous, current, previous_status, current_status, 5)[0],
            "yellow_downcross": wave_b.crossing(previous, current, previous_status, current_status, 6)[0],
            "bearish_high_fade": wave_b.bearish_fade(current, current_status)[0],
        }
    hits = [h for h, values in checks.items() if any(values.values())]
    missing = [(h, "|".join(name for name, value in values.items() if value is None))
               for h, values in checks.items() if h not in hits and None in values.values()]
    summary = wave_b.summarize_first(hits, missing, stock.calendar, at, 1, 20)
    first = summary["first_offset"]
    return {"warning_any_" + key: val for key, val in summary.items()} | {
        "warning_any_first_kinds": "|".join(name for name, value in checks[first].items() if value)
        if first is not None else "",
    }


def peak_metrics(stock, at, bars, end, frozen=None):
    available = [h for h in range(1, 21) if bars[h] is not None]
    best = max(available, key=lambda h: (bars[h][1], -h)) if available else None
    peak = float(bars[best][1]) if best is not None else None
    peak_date = wave_b.date_at(stock.calendar, at + best) if best is not None else None
    d_close = float(bars[0][3])
    end_close = end["close_ret_D20_close_d_basis"]
    if frozen is not None:
        assert int(frozen["observed_sessions"]) == len(available)
        assert_same_encoded(d_close, frozen["d_close_basis"])
        assert_same_encoded(peak, frozen["peak_high_d_basis"])
        for key, value in (("peak_day", best), ("peak_D", int(peak_date) if peak_date else None)):
            given = frozen[key]
            assert (pd.isna(given) and value is None) or given == value, (stock.code, at, key)
    delta_price = peak - end_close if peak is not None and end_close is not None else None
    direction = ("POSITIVE" if delta_price > 0 else "NEGATIVE" if delta_price < 0 else "ZERO"
                 ) if delta_price is not None else "UNAVAILABLE"
    flag = (peak > d_close and end_close < d_close) if delta_price is not None else None
    full = len(available) == 20
    return {
        "full20": full, "observed_sessions": len(available),
        "peak_status": "FULL_WINDOW" if full else "OBSERVED_WINDOW_ONLY" if available else "NO_OBSERVED_BAR",
        "peak_day": best, "peak_D": peak_date, "peak_high_d_basis": peak,
        "raw_max_rise_pct_same_basis_exact": (peak / d_close - 1) * 100 if peak is not None else None,
        "peak_minus_D20_price": delta_price, "peak_minus_D20_sign": direction,
        "peak_minus_D20_pct": delta_price / d_close * 100 if delta_price is not None else None,
        "positive_peak_negative_D20": flag,
    }


def assert_same_encoded(actual, legacy):
    if actual is None:
        assert pd.isna(legacy)
    else:
        assert (legacy == actual or
                format(float(legacy), ".12g") == format(actual, ".12g")), (actual, legacy)


def sign_and_warning(stock, at, bars, statuses, frozen=None):
    end = wave_b.outcomes(bars, statuses, stock.calendar, at, wave_b.ENDPOINTS)
    return (end | peak_metrics(stock, at, bars, end, frozen) |
            wave_b.warnings_in_window(bars, statuses, stock.calendar, at) |
            first_warning(stock, at, bars, statuses))


def pair_signal(stock, at, signals):
    baseline = {"event_id": f"{stock.code}/{stock.calendar[at]}"}
    for fam in OLD.FAMILIES:
        dates, hits, missing = [], [], []
        for offset in range(-5, 1):
            day = at + offset
            date = wave_b.date_at(stock.calendar, day)
            st = wave_b.HIT if signals.get(day, {}).get(fam) else OLD.signal_status(stock, day)
            if st == wave_b.HIT:
                hits.append(offset)
                dates.append(date)
            if st not in (wave_b.HIT, wave_b.NO_HIT):
                missing.append((offset, st))
                st = wave_b.UNAVAILABLE
            baseline[f"{fam}_D{offset:+d}"] = st
        baseline[f"{fam}_actual_offsets"] = "|".join(map(str, hits))
        baseline[f"{fam}_actual_dates"] = "|".join(dates)
        baseline[f"{fam}_unavailable_slots"] = wave_b.missing_slots(missing, stock.calendar, at)
    return wave_b.frozen_signal_window(stock, at, signals, baseline)


def build_waves(stock, local, signal_frame, signals, fingerprints):
    if local.empty:
        return []
    anchors = local.exchange_session_ordinal.to_numpy()
    old = OLD.features(stock, anchors).set_axis(anchors)
    added = new_features(stock, anchors).set_axis(anchors)
    original = OLD.detail_for(stock.code, stock, local, signal_frame, fingerprints, old)
    result = []
    frozen_by_ordinal = local.set_index("exchange_session_ordinal").to_dict("index")
    for row in original:
        at = int(row["D_ordinal"])
        authority = frozen_by_ordinal[at]
        assert str(row["D"]) == stock.calendar[at]
        assert stock.available_rows[at] == signals[at]["event_slice_end_bar"]
        bars, statuses = wave_b.d_basis_bars(stock, at, 20)
        posterior = sign_and_warning(stock, at, bars, statuses, frozen=row)
        assert posterior["full20"] == authority["full20"]
        assert int(row["right_censored_rows"]) == statuses[1:].count("RIGHT_CENSORED_AT_20261120")
        posterior["peak5"] = authority["peak5"]
        posterior["D_frozen_status"] = wave_b.NO_HIT if authority["hidden"] else wave_b.HIT
        assert bool(signals[at]["forward_any"]) == (not authority["hidden"])
        posterior["D_frozen_families"] = "|".join(f for f in OLD.FAMILIES if signals[at][f])
        posterior["path_unavailable_slots"] = wave_b.missing_slots(
            [(h, statuses[h]) for h in range(1, 21) if statuses[h] != wave_b.OBSERVED],
            stock.calendar, at)
        posterior["frozen_peak_high_d_basis_legacy_encoded"] = row["peak_high_d_basis"]
        result.append(row | added.loc[at].to_dict() |
                      wave_b.frozen_signal_window(stock, at, signals, row) | posterior)
    return result


def clean(value):
    if isinstance(value, dict):
        return {key: clean(val) for key, val in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [clean(val) for val in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if value is pd.NA or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return value


def compact(value):
    return json.dumps(clean(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def path_context(stock, at):
    anchor = stock.available_rows[at]
    raw = []
    for offset in range(-10, 21):
        ordinal = at + offset
        qfq, basis, status = stock.get(ordinal, anchor)
        source_row = stock.available_rows.get(ordinal)
        code = stock.frame.ts_code.iat[source_row] if source_row is not None else None
        raw.append((offset, wave_b.date_at(stock.calendar, ordinal), status, code, qfq, basis))
    return clean(raw)


def crossing_dates(rows):
    """Cross only between immediately adjacent schedule slots with valid, observed values."""
    result = {}
    for kind, index in (("white", 5), ("yellow", 6)):
        for direction in ("reclaim", "lose"):
            dates = []
            missing = []
            for previous, current in zip(rows, rows[1:]):
                offset, day, _, _, _, now = current
                before = previous[-1]
                valid = now is not None and before is not None and now[index] is not None and before[index] is not None
                if not valid:
                    missing.append((offset, "BAR_OR_LINE_UNKNOWN"))
                    continue
                was_above = before[3] >= before[index]
                is_above = now[3] >= now[index]
                hit = was_above and not is_above if direction == "lose" else not was_above and is_above
                if hit:
                    dates.append((offset, day))
            post = [value for value in dates if value[0] >= 0]
            post_missing = [entry for entry in missing if entry[0] >= 0]
            first_off, first_date = post[0] if post else (None, None)
            if post:
                state = ("EARLIEST_OBSERVED_PARTIAL" if any(h < first_off for h, _ in post_missing) else
                         "FIRST_CONFIRMED_WITHIN_WINDOW")
            else:
                state = "UNAVAILABLE" if post_missing else "NO_OBSERVED_HIT"
            key = f"{kind}_{direction}"
            result[f"{key}_first_from_D_offset"] = first_off
            result[f"{key}_first_from_D_date"] = first_date
            result[f"{key}_first_from_D_status"] = state
            result[f"{key}_unavailable_from_D_n"] = len(post_missing)
            result[f"{key}_observed_hits_json"] = compact(dates)
    return result


def post_peak(stock, at, out, frozen=None):
    offset = out["peak_day"]
    if offset is None:
        return {"peak5": False, "peak_post5_status": "NO_OBSERVED_PEAK",
                "peak_post5_observed_sessions": 0, "peak_post5_max_dd_pct": None,
                "peak_post5_trough_date": None, "peak_post5_sessions_to_trough": None}
    anchor = stock.available_rows[at]
    values = [stock.get(at + offset + h, anchor)[1] for h in range(1, 6)]
    observed = sum(value is not None for value in values)
    dd, trough, trough_date = None, None, None
    complete = observed == 5
    if complete:
        trough = min(range(1, 6), key=lambda h: (values[h - 1][2], h))
        dd = float(min(0., (values[trough - 1][2] / out["peak_high_d_basis"] - 1) * 100))
        trough_date = wave_b.date_at(stock.calendar, at + offset + trough)
    if frozen is not None:
        assert observed == frozen["peak_post5_observed_sessions"]
        assert (out["full20"] and complete) == frozen["peak5"]
        assert_same_encoded(dd, frozen["peak_post5_max_dd_pct"])
    return {"peak5": out["full20"] and complete,
            "peak_post5_status": "COMPLETE" if complete else "INCOMPLETE_NO_FIVE_DAY_DRAWDOWN",
            "peak_post5_observed_sessions": observed, "peak_post5_max_dd_pct": dd,
            "peak_post5_trough_date": trough_date, "peak_post5_sessions_to_trough": trough}


def make_pair_rows(stock, card, selected, signals, frozen_main, alternatives):
    main, control, context = selected
    calendar = stock.calendar
    pair_id = f"{stock.code}/{calendar[main]}"
    control_id = f"{stock.code}/{calendar[control]}"
    rows = []
    for at, role in [(main, "MAIN_REVERSE_EVENT"), (control, "SAME_STOCK_SAME_YEAR_ORDINARY")]:
        dates = path_context(stock, at)
        event_date = str(calendar[at])
        is_main = at == main
        frozen = frozen_main if is_main else None
        bars = [row[-1] for row in dates[10:]]
        # NumPy arrays preserve the inherited warning predicate's NaN treatment.
        bars = [np.asarray(row, dtype=float) if row is not None else None for row in bars]
        statuses = tuple(row[2] for row in dates[10:])
        out = sign_and_warning(stock, at, bars, statuses, frozen)
        if is_main:
            assert out["full20"]
        sig = pair_signal(stock, at, signals)
        d_hit = bool(signals.get(at, {}).get("forward_any"))
        d_signal_status = wave_b.HIT if d_hit else OLD.signal_status(stock, at)
        if is_main:
            assert d_hit == (not bool(frozen["hidden"]))
        assert d_signal_status in (wave_b.HIT, wave_b.NO_HIT)
        signal_summary = {}
        for fam in (*OLD.FAMILIES, "any_frozen_signal"):
            for key in ("first_offset", "first_date", "first_timing", "first_status",
                        "window_status", "window_unavailable_slots"):
                field = f"{fam}_{key}"
                signal_summary[field] = sig[field]
        signal_summary["any_frozen_signal_first_families"] = sig["any_frozen_signal_first_families"]
        warnings = {key: val for key, val in out.items() if not key.startswith("warning_")
                    or key.startswith("warning_any_") or "_first_" in key}
        post5 = post_peak(stock, at, out, frozen)
        anchor = stock.available_rows[at]
        summary = {
            "pair_id": pair_id, "case_id": f"{stock.code}/{event_date}", "role": role,
            "security_id": stock.code, "name": card["name"], "archetype": card.archetype_frozen,
            "D": event_date, "D_ordinal": at, "calendar_year": event_date[:4],
            "matched_case_id": control_id if is_main else pair_id, "matching_status": "MATCHED",
            "D_frozen_status": d_signal_status,
            "D_frozen_families": "|".join(fam for fam in OLD.FAMILIES if signals.get(at, {}).get(fam)),
            "D_time_reverse_group": ("visible" if d_hit else "hidden") if is_main else "",
            "d_affine_price_scale": float(stock.a[anchor]), "d_affine_price_offset": float(stock.b[anchor]),
            "d_affine_volume_scale": float(stock.v[anchor]),
            "bars_layout": "|".join(BAR_LAYOUT), "bar_values_layout": "|".join(FIELDS),
            "bars_Dm10_to_Dp20_json": compact(dates),
        }
        rows.append(summary | context | alternatives | signal_summary | warnings | post5 | crossing_dates(dates))
    return rows


def draw_chart(row):
    slots = json.loads(row["bars_Dm10_to_Dp20_json"])
    marks = [
        ("D", 0, row["D"], "#1f527a"),
        ("首个冻结信号", row["any_frozen_signal_first_offset"], row["any_frozen_signal_first_date"], "#6353af"),
        ("窗口峰", row["peak_day"], row["peak_D"], "#a16c10"),
        ("首次警示", row["warning_any_first_offset"], row["warning_any_first_date"], "#9a305d"),
    ]
    label, line, rect = case_c.label, case_c.line, case_c.rect
    w, h = 1360, 665
    left, right = 104, 1328
    top, bottom, vtop, vbottom = 162, 431, 469, 557
    dx = (right - left) / len(slots)

    def xpos(offset):
        return left + (offset + 10.5) * dx

    price, volume = chart_ranges(slots)

    def yp(n):
        return bottom - (bottom - top) * (n - price[0]) / (price[1] - price[0])

    def yv(n):
        return vbottom - (vbottom - vtop) * n / volume

    txt, muted, guide = "#152239", "#41546a", "#d8e1eb"
    white, yellow, buy, sell = "#566575", "#ae7300", "#b53038", "#167552"
    code, name, arch = row["security_id"], row["name"], row["archetype"]
    date_fmt = case_c.display_date
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<title id="title">{escape(code)} {escape(name)} 观察路径</title>',
        '<desc id="desc">冻结 Reader 前复权日 K、成交量、白线和黄线，横轴为交易所排程。</desc>',
        '<style>text{font-family:system-ui,PingFang SC,Noto Sans CJK SC,sans-serif;font-size:13px} '
        '.title{font-size:28px;font-weight:700}.axis{font-size:12px;font-variant-numeric:tabular-nums}'
        '.marker{font-size:12px;font-weight:630}</style>',
        rect(0, 0, w, h, "#f7f9fc"),
        label(26, 40, f"{name}  {code}   ·   原型 {arch}", fill=txt, **{"class": "title"}),
        label(27, 67, f"{date_fmt(slots[0][1])} 至 {date_fmt(slots[-1][1])}  ·  冻结 Reader 前复权  ·  交易所日历  ·  {row['sample_window']}", fill=muted),
        rect(left, top, right - left, bottom - top, "#ffffff"),
        rect(left, vtop, right - left, vbottom - vtop, "#ffffff"),
        label(26, top - 7, "价格（元）", fill=muted),
        label(26, vtop - 17, "成交量", fill=muted),
        line(1028, 59, 1055, 59, white, 2), label(1061, 64, "白线", fill=txt),
        line(1124, 59, 1151, 59, yellow, 2), label(1158, 64, "黄线", fill=txt),
        label(1220, 64, "红涨  绿跌", fill=muted),
    ]
    for i in range(6):
        tick = price[0] + (price[1] - price[0]) * i / 5
        y = yp(tick)
        out.extend([line(left, y, right, y, guide), label(left - 9, y + 4, f"{tick:.3f}", fill=muted, text_anchor="end", **{"class": "axis"})])
    for tick in (0, volume / 2, volume):
        y = yv(tick)
        out.extend([line(left, y, right, y, guide), label(left - 9, y + 4, f"{tick:,.0f}", fill=muted, text_anchor="end", **{"class": "axis"})])

    for i, (title, offset, day, color) in enumerate(marks):
        legend_x = 26 + 326 * i
        key = ("event", "signal", "peak", "warning")[i]
        suffix = ""
        if key == "signal" and row["any_frozen_signal_first_status"] == "EARLIEST_OBSERVED_PARTIAL":
            suffix = "＊"
        if key == "warning" and row["warning_any_first_status"] == "EARLIEST_OBSERVED_PARTIAL":
            suffix = "＊"
        details = f"{date_fmt(day)}  D{int(offset):+d}{suffix}" if offset is not None else "窗口内无已知命中"
        out.append(label(legend_x, 105, f"{title}   {details}", fill=color, **{"class": "marker"}))
        if offset is not None:
            x = xpos(offset)
            y = 128 + (i * 8)
            out.append(f'<g data-marker="{key}" data-offset="{offset}" data-date="{day}">')
            out.append(line(x, y, x, vbottom, color, 1))
            out.append(f'<circle cx="{x:.2f}" cy="{y}" r="3.2" fill="{color}"/>')
            out.append("</g>")

    for offset, day, status, _, qfq, basis in slots:
        center = xpos(offset)
        out.append(f'<g data-slot="{offset}" data-date="{day or ""}" data-status="{escape(status)}">')
        tooltip = " · ".join(f"{f} {val if val is not None and basis is not None else 'NA'}"
                             for f, val in zip(SHORT_FIELDS, qfq or [None] * len(FIELDS), strict=True))
        out.append(f"<title>{day or 'NA'} / D{offset:+d} · {escape(status)} · {tooltip}</title>")
        if basis is not None:
            o, hi, lo, c, vol, *_ = qfq
            color = buy if c > o else sell if c < o else muted
            body = min(dx * .55, 15)
            out.extend(['<g class="candle">', line(center, yp(hi), center, yp(lo), color, 1.35),
                        rect(center - body / 2, min(yp(o), yp(c)), body, max(abs(yp(o) - yp(c)), 1.25), color), '</g>',
                        rect(center - body / 2, yv(vol), body, max(vbottom - yv(vol), 0), color, opacity=".8", **{"class": "volume"})])
        else:
            out.extend([rect(center - dx / 2, top, dx, bottom - top, "#e9edf3", opacity=".65"),
                        label(center, (top + bottom) / 2, "×", fill=muted, text_anchor="middle", **{"class": "gap"})])
        offset_text = "D" if offset == 0 else f"{offset:+d}"
        date_text = day[4:6] + "/" + day[6:8] if day else "NA"
        out.extend([label(center, 586, offset_text, fill=txt, text_anchor="middle", **{"class": "axis"}),
                    label(center, 608, date_text, fill=muted, text_anchor="middle", **{"class": "axis"}), "</g>"])

    for side, index, color in (("white", 5, white), ("yellow", 6, yellow)):
        points = []
        active = [basis is not None and basis[index] is not None for _, _, _, _, _, basis in slots]
        for i, (offset, _, _, _, qfq, _) in enumerate(slots):
            if not active[i]:
                continue
            code = "L" if i and active[i - 1] else "M"
            x, y = xpos(offset), yp(qfq[index])
            points.append(f"{code}{x:.2f} {y:.2f}")
            if not (i and active[i - 1]) and not (i + 1 < len(active) and active[i + 1]):
                out.append(f'<circle data-single="{side}" cx="{x:.2f}" cy="{y:.2f}" r="2" fill="{color}"/>')
        if points:
            out.append(f'<path data-series="{side}" d="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.65" pointer-events="none"/>')
    out.extend([
        label(26, 639, "横轴每栏一个计划交易日。× 为无有效栏，白黄线缺失时断开。悬停可读 O/H/L/C/V/W/Y 原值。＊ 为最早已观察，前方存在缺证。", fill=muted),
        "</svg>",
    ])
    return "\n".join(out).encode()


def chart_ranges(slots):
    observed = [(qfq, basis) for _, _, _, _, qfq, basis in slots if basis is not None]
    values = [bar[index] for bar, basis in observed for index in (1, 2, 5, 6) if basis[index] is not None]
    span = max(max(values) - min(values), max(values) * .015)
    volume = max(bar[4] for bar, _ in observed)
    assert volume > 0
    return (min(values) - .06 * span, max(values) + .10 * span), volume


def verify_chart(data, row):
    ns = case_c.NS
    root = ET.fromstring(data)
    assert root.tag == ns + "svg"
    assert all(e.tag not in {ns + name for name in ("script", "image", "use", "a", "foreignObject")}
               for e in root.iter())
    slots = json.loads(row["bars_Dm10_to_Dp20_json"])
    groups = root.findall(f'{ns}g[@data-slot]')
    assert len(groups) == len(slots) == 31
    (lo, hi), max_volume = chart_ranges(slots)
    for group, (off, day, status, _, qfq, basis) in zip(groups, slots, strict=True):
        assert group.attrib == {"data-slot": str(off), "data-date": day or "", "data-status": status}
        title = group.find(ns + "title").text.split(" · ")
        assert title[:2] == [f"{day or 'NA'} / D{off:+d}", status]
        assert len(title) == 9
        for i, field in enumerate(SHORT_FIELDS):
            given = title[i + 2].split(" ", 1)
            intended = qfq[i] if basis is not None else None
            assert given[0] == field and (None if given[1] == "NA" else float(given[1])) == intended
        candle = group.find(f'{ns}g[@class="candle"]')
        volume = group.find(f'{ns}rect[@class="volume"]')
        assert (candle is not None) == (volume is not None) == (status == wave_b.OBSERVED)
        if candle is not None:
            wick = candle.find(ns + "line").attrib
            assert wick["y1"] == f"{431 - 269 * (qfq[1] - lo) / (hi - lo):.2f}"
            assert wick["y2"] == f"{431 - 269 * (qfq[2] - lo) / (hi - lo):.2f}"
            assert volume.attrib["height"] == f"{557 - (557 - 88 * qfq[4] / max_volume):.2f}"
    for key, index in (("white", 5), ("yellow", 6)):
        path = root.find(f'{ns}path[@data-series="{key}"]')
        points = [] if path is None else path.attrib["d"].split()
        expected = []
        for i, slot in enumerate(slots):
            basis = slot[-1]
            if basis is not None and basis[index] is not None:
                start = not i or slots[i - 1][-1] is None or slots[i - 1][-1][index] is None
                x = 104 + (i + .5) * ((1328 - 104) / 31)
                y = 431 - 269 * (slot[-2][index] - lo) / (hi - lo)
                expected.extend([f'{"M" if start else "L"}{x:.2f}', f"{y:.2f}"])
        assert points == expected
    offsets_dates = {
        "event": (0, row["D"]),
        "signal": (row["any_frozen_signal_first_offset"], row["any_frozen_signal_first_date"]),
        "peak": (row["peak_day"], row["peak_D"]),
        "warning": (row["warning_any_first_offset"], row["warning_any_first_date"]),
    }
    expected = {key: (str(offset), day) for key, (offset, day) in offsets_dates.items() if offset is not None}
    assert {e.attrib["data-marker"]: (e.attrib["data-offset"], e.attrib["data-date"])
            for e in root.findall(f'{ns}g[@data-marker]')} == expected


def package_charts(mains):
    payload = BytesIO()
    charts = {}
    with ZipFile(payload, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for row in mains:
            key = f"{row['archetype']}/{row['security_id']}_{row['D']}.svg"
            chart = draw_chart(row)
            info = ZipInfo(key, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, chart, compress_type=ZIP_DEFLATED, compresslevel=9)
            charts[key] = (row, sha256(chart).hexdigest())
    return payload.getvalue(), charts


def encode_csv(rows, fields):
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(clean(row) for row in rows)
    return buffer.getvalue().encode("utf-8-sig")


def verify_csv(data, rows, fields):
    handle = csv.DictReader(StringIO(data.decode("utf-8-sig"), newline=""))
    assert handle.fieldnames == fields
    for expected, given in zip(rows, handle, strict=True):
        for key in fields:
            value = clean(expected.get(key))
            assert given[key] == (str(value) if value is not None else ""), (key, given[key], value)


def summarize_waves(rows):
    def count(column):
        return dict(Counter(str(row[column]) for row in rows))

    def distribution(column):
        values = [value for row in rows if (value := clean(row[column])) is not None]
        return {"n": len(values), "median": float(np.median(values)) if values else None}

    complete = [row for row in rows if row["full20"]]
    reversal = [row for row in rows if row["positive_peak_negative_D20"] is not None]
    complete_reversal = [row for row in complete if row["positive_peak_negative_D20"]]
    fields = (
        "volume_mean3_vs_prev20", "volume_Dm3_vs_own_prev20", "volume_Dm2_vs_own_prev20", "volume_Dm1_vs_own_prev20",
        "volume_Dm3_vs_common_base20", "volume_Dm2_vs_common_base20", "volume_Dm1_vs_common_base20",
        "amplitude_5_high_low_pct", "dd20_close_highwater_d1_pct", "dd20_max_close_drawdown_pct",
        "bear_body_count_3", "bear_body_longest_run_3", "bear_body_trailing_run_3",
        "bear_body_count_5", "bear_body_longest_run_5", "bear_body_trailing_run_5",
        "close_ret_D5_pct", "close_ret_D10_pct", "close_ret_D20_pct",
        "raw_max_rise_pct_same_basis_exact", "peak_post5_max_dd_pct",
    )
    signals = {family: {key: count(f"{family}_{key}")
                        for key in ("first_timing", "first_status", "window_status")}
               for family in (*OLD.FAMILIES, "any_frozen_signal")}
    return {
        "event_n": len(rows), "stock_event_n": len({row["security_id"] for row in rows}),
        "full20_n": len(complete), "not_full20_n": len(rows) - len(complete),
        "peak5_n": sum(bool(row["peak5"]) for row in rows),
        "events_with_right_censored_slots_n": sum(int(row["right_censored_rows"]) > 0 for row in rows),
        "hidden_same_day_n": sum(row["event_group"] == "hidden" for row in rows),
        "visible_same_day_n": sum(row["event_group"] == "visible" for row in rows),
        "peak_status": count("peak_status"),
        "endpoints": {f"D{h}": count(f"close_ret_D{h}_status") for h in wave_b.ENDPOINTS},
        "warning_first_status": count("warning_any_first_status"),
        "peak_minus_D20_sign": count("peak_minus_D20_sign"),
        "peak_minus_D20_full20_sign": dict(Counter(row["peak_minus_D20_sign"] for row in complete)),
        "positive_peak_negative_D20_n": sum(bool(row["positive_peak_negative_D20"]) for row in reversal),
        "positive_peak_negative_D20_valid_n": len(reversal),
        "positive_peak_negative_D20_full20_n": len(complete_reversal),
        "positive_peak_negative_D20_full20_ratio": len(complete_reversal) / len(complete) if complete else None,
        "frozen_first": signals,
        "metric_medians_available": {column: distribution(column) for column in fields},
    }


def compile_batch(cards, events, signals, fingerprints, prior, cfg, frame, calendar):
    waves, paired, pools = [], [], {}
    codes = set(frame.canonical)
    local_events = events.loc[events.security_id.isin(codes)]
    local_signals = signals.loc[signals.security_id.isin(codes)]
    local_fingerprints = fingerprints.loc[fingerprints.security_id.isin(codes)]
    for code, daily in frame.groupby("canonical", sort=True):
        stock = OLD.Stock(code, daily, cfg["events"][code], calendar)
        all_events = local_events.loc[local_events.security_id.eq(code)].sort_values("D")
        assert np.array_equal(calendar[all_events.exchange_session_ordinal].astype(int), all_events.D)
        ordinary = OLD.ordinary(stock, all_events.exchange_session_ordinal.to_numpy())
        assert len(ordinary) == prior["precursor"]["ordinary_by_stock"][code], code
        # Matching finishes before any outcome summaries are computed.
        selection = choose_pair(stock, all_events, ordinary)
        pools[code] = {"mother_pool_all_years_n": len(ordinary), **selection[-1]}

        sig_frame = local_signals.loc[local_signals.security_id.eq(code)]
        assert np.array_equal(calendar[sig_frame.exchange_session_ordinal].astype(int), sig_frame.D)
        sig = sig_frame.set_index("exchange_session_ordinal").to_dict("index")
        finger = local_fingerprints.loc[local_fingerprints.security_id.eq(code)]
        recent = all_events.loc[all_events.D.between(int(OLD.START), int(OLD.END))]
        local_waves = build_waves(stock, recent, sig_frame, sig, finger)
        assert {int(row["D"]) for row in local_waves} == set(recent.D)
        waves.extend(local_waves)

        main, _, _ = selection
        selected = all_events.loc[all_events.exchange_session_ordinal.eq(main)].iloc[0]
        frozen_main = finger.loc[finger.D.eq(selected.D)].iloc[0].to_dict() | selected.to_dict()
        main_id = f"{code}/{selected.D}"
        alternates = [row for row in local_waves if row["full20"] and row["event_id"] != main_id]
        reverse = [row for row in alternates if row["positive_peak_negative_D20"]]
        deepest = [row for row in alternates if row["peak5"] and pd.notna(row["peak_post5_max_dd_pct"])]
        reversal = max(reverse, key=lambda row: (row["raw_max_rise_pct_same_basis_exact"], row["D"]), default=None)
        drawdown = min(deepest, key=lambda row: (row["peak_post5_max_dd_pct"], -row["D"]), default=None)
        alternates = {
            "alternate_positive_peak_negative_D20_key": reversal["event_id"] if reversal else None,
            "alternate_deepest_complete_peak5_drawdown_key": drawdown["event_id"] if drawdown else None,
        }
        paired.extend(make_pair_rows(stock, cards.loc[code], selection, sig, frozen_main, alternates))
        if len(pools) in (1, 10, 20, 30, len(codes)):
            print(f"stock pairs {len(pools)}/{len(codes)}; recent event keys {len(waves)}", flush=True)
    assert set(pools) == codes
    return waves, paired, pools


def verify_results(waves, pairs, pools, cards, frozen, calendar, canary):
    codes = set(pools)
    assert len(codes) == (1 if canary else 35) and len(pairs) == len(codes) * 2
    assert len({row["case_id"] for row in pairs}) == len(pairs)
    assert len({row["event_id"] for row in waves}) == len(waves)
    recent = frozen.loc[frozen.security_id.isin(codes) & frozen.D.between(int(OLD.START), int(OLD.END))]
    assert {(row["security_id"], int(row["D"])) for row in waves} == set(zip(recent.security_id, recent.D))
    main_lookup = {}
    waves_by_id = {row["event_id"]: row for row in waves}
    for main, control in zip(pairs[::2], pairs[1::2], strict=True):
        code = main["security_id"]
        assert code == control["security_id"]
        assert main["calendar_year"] == control["calendar_year"]
        assert main["pair_id"] == control["pair_id"] == main["case_id"]
        assert main["role"] == "MAIN_REVERSE_EVENT" and control["role"] == "SAME_STOCK_SAME_YEAR_ORDINARY"
        assert (main["matched_case_id"], control["matched_case_id"]) == (control["case_id"], main["case_id"])
        assert main["full20"]
        main_lookup[code] = main
        local = frozen.loc[frozen.security_id.eq(code)]
        assert int(control["D"]) not in set(local.D)
        complete = local.loc[local.full20]
        recent = complete.loc[complete.D.between(int(OLD.START), int(OLD.END))]
        assert int(main["D"]) == (recent if len(recent) else complete).D.max()
        assert main["sample_window"] == ("RECENT_2Y" if len(recent) else "FALLBACK_HISTORY")
        if len(recent):
            source = waves_by_id[main["case_id"]]
            decimals = ["D_basis_close_verified", "peak_high_d_basis", "close_ret_D20_close_d_basis",
                        "peak_minus_D20_price", "peak_minus_D20_pct", "peak_minus_D20_sign",
                        "any_frozen_signal_first_date", "warning_any_first_date"]
            assert all(source[key] == main[key] for key in decimals), main["case_id"]
        for path in (main, control):
            assert path["name"] == cards.loc[code, "name"] and path["archetype"] == cards.loc[code, "archetype_frozen"]
            slots = json.loads(path["bars_Dm10_to_Dp20_json"])
            assert len(slots) == 31
            for h, (offset, day, status, raw_id, qfq, d_basis) in enumerate(slots, -10):
                assert offset == h and day == wave_b.date_at(calendar, path["D_ordinal"] + h)
                assert (status == wave_b.OBSERVED) == (d_basis is not None)
                assert (qfq is None) == (raw_id is None)
                if d_basis is not None:
                    for field, (raw, val) in enumerate(zip(qfq, d_basis, strict=True)):
                        if val is not None:
                            exact = raw / path["d_affine_volume_scale"] if field == 4 else (
                                (raw - path["d_affine_price_offset"]) / path["d_affine_price_scale"])
                            assert val == exact
            validate_delta(path)
    for row in waves:
        validate_delta(row)
        card = cards.loc[row["security_id"]]
        assert (row["name"], row["archetype"]) == (card["name"], card["archetype_frozen"])
    assert set(main_lookup) == codes
    return list(main_lookup.values())


def validate_delta(row):
    peak, end = row["peak_high_d_basis"], row["close_ret_D20_close_d_basis"]
    if peak is None or end is None:
        assert row["peak_minus_D20_sign"] == "UNAVAILABLE"
        assert row["peak_minus_D20_price"] is row["peak_minus_D20_pct"] is row["positive_peak_negative_D20"] is None
        return
    delta = peak - end
    sign = {-1: "NEGATIVE", 0: "ZERO", 1: "POSITIVE"}[int(delta > 0) - int(delta < 0)]
    assert row["peak_minus_D20_price"] == delta and row["peak_minus_D20_sign"] == sign
    d_close = row["D_basis_close_verified"]
    assert row["positive_peak_negative_D20"] == (peak > d_close > end)
    assert row["peak_minus_D20_pct"] == (delta / d_close) * 100
    assert row["peak_minus_D20_sign"] != "NEGATIVE", row["case_id"] if "case_id" in row else row["event_id"]


def payloads_for(waves, pairs, mains, original_columns):
    wave_fields = original_columns + sorted({k for row in waves for k in row} - set(original_columns))
    pair_fields = list(dict.fromkeys(k for row in pairs for k in row))
    assert set(original_columns) <= {k for row in waves for k in row} or not waves
    pack, charts = package_charts(mains)
    return {WAVE_NAME: encode_csv(waves, wave_fields), PAIR_NAME: encode_csv(pairs, pair_fields),
            PACK_NAME: pack}, (wave_fields, pair_fields), charts


def verify_payloads(payloads, fields, charts, waves, pairs):
    assert all(0 < len(data) <= HARD_BYTES for data in payloads.values())
    verify_csv(payloads[WAVE_NAME], waves, fields[0])
    verify_csv(payloads[PAIR_NAME], pairs, fields[1])
    archive_payload = payloads[PACK_NAME]
    with ZipFile(BytesIO(archive_payload)) as handle:
        assert handle.testzip() is None and set(handle.namelist()) == set(charts)
        for key, (row, digest) in charts.items():
            data = handle.read(key)
            assert sha256(data).hexdigest() == digest
            verify_chart(data, row)


def write_json_exclusive(path, value):
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(clean(value), ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True, help="canonical local ACT-060A batch directory")
    parser.add_argument("--canary", action="store_true", help=f"one stock, {CANARY}; write only a canary receipt")
    args = parser.parse_args()
    batch = args.batch.resolve()
    previous = batch.parent / "act059a_kb42_20261125"
    output = batch / "delivery"
    evidence = batch / "evidence"
    receipt_path = evidence / (CANARY_NAME if args.canary else RECEIPT_NAME)
    planned_outputs = () if args.canary else tuple(output / name for name in (WAVE_NAME, PAIR_NAME, PACK_NAME))
    assert not any(path.exists() for path in (*planned_outputs, receipt_path)), "OUTPUT_ALREADY_EXISTS"

    global OLD, wave_b, case_c, new_features
    sys.path.insert(0, str(previous))
    import case_c
    import wave_b
    from metric_a import OLD, new_features

    start, cpu_start = perf_counter(), process_time()
    previous_wall, previous_cpu = start, cpu_start
    elapsed, cpu = {}, {}

    def checkpoint(name):
        nonlocal previous_wall, previous_cpu
        now, now_cpu = perf_counter(), process_time()
        elapsed[name], cpu[name] = now - previous_wall, now_cpu - previous_cpu
        previous_wall, previous_cpu = now, now_cpu
        print(f"{name} {elapsed[name]:.3f}s elapsed", flush=True)

    pa.set_cpu_count(4)
    pa.set_io_thread_count(2)
    with threadpool_limits(limits=1):
        cards, frozen, signals, fingers, r56, r50, prior, sources, original = verify_inputs(batch, previous)
        codes = {CANARY} if args.canary else {code for values in ROSTER.values() for code in values.split()}
        cfg, frame, calendar, binding = project_reader(codes, r56, r50, prior)
        checkpoint("reading")
        waves, pairs, pools = compile_batch(cards, frozen, signals, fingers, prior, cfg, frame, calendar)
        mains = verify_results(waves, pairs, pools, cards, frozen, calendar, args.canary)
        payloads, fields, charts = payloads_for(waves, pairs, mains, original)
        checkpoint("computing")
        verify_payloads(payloads, fields, charts, waves, pairs)
        by_arch = {}
        by_stock = {}
        for archetype, codes_text in ROSTER.items():
            have = set(codes_text.split()) & codes
            if have:
                by_arch[archetype] = summarize_waves([row for row in waves if row["archetype"] == archetype])
                by_arch[archetype]["roster_stock_n"] = len(have)
        for main, control in zip(pairs[::2], pairs[1::2], strict=True):
            code = main["security_id"]
            by_stock[code] = summarize_waves([row for row in waves if row["security_id"] == code]) | pools[code] | {
                "name": main["name"], "archetype": main["archetype"], "main_case_id": main["case_id"],
                "control_case_id": control["case_id"], "control_D_frozen_status": control["D_frozen_status"],
                "main_D_frozen_status": main["D_frozen_status"],
                "control_full20": control["full20"], "main_peak5": main["peak5"],
            }
        summaries = summarize_waves(waves)
        summaries.update({"roster_stock_n": len(codes), "main_n": len(mains), "pair_csv_rows": len(pairs),
                          "charts_n": len(charts), "wave_csv_columns": len(fields[0]), "pair_csv_columns": len(fields[1]),
                          "pairs_control_D_frozen_status": dict(Counter(row["D_frozen_status"] for row in pairs[1::2])),
                          "control_modes": dict(Counter(x["control_matching_mode"] for x in pools.values())),
                          "pairs_control_full20_n": sum(row["full20"] for row in pairs[1::2]),
                          "mains_peak5_n": sum(row["peak5"] for row in mains),
                          "zero_in_2y_codes": sorted(code for code, x in pools.items() if not x["recent_full20_n"]),
                          "no_event_in_2y_codes": sorted(code for code, x in pools.items() if not x["recent_event_n"]),
                          "exact_zero_event_keys": [row["event_id"] for row in waves if row["peak_minus_D20_sign"] == "ZERO"]})
        if not args.canary:
            assert (summaries["event_n"], summaries["full20_n"], summaries["hidden_same_day_n"]) == (475, 455, 453)
            assert summaries["zero_in_2y_codes"] == [CANARY]
            assert {key: val["event_n"] for key, val in by_arch.items()} == {"A": 147, "B": 214, "C": 92, "D": 22}
        for target in planned_outputs:
            data = payloads[target.name]
            with target.open("xb") as handle:
                handle.write(data)
            assert_identity(target, {"bytes": len(data), "sha256": sha256(data).hexdigest()})
        checkpoint("verification")
        stamps = {name: {"bytes": len(data), "sha256": sha256(data).hexdigest(),
                         "path": str(output / name) if not args.canary else None}
                  for name, data in payloads.items()}
        chart_evidence = {key: {"event_id": row["case_id"], "sha256": digest}
                          for key, (row, digest) in charts.items()}
        del frame, cfg, frozen, signals, fingers, payloads, pairs, waves, charts, mains
        gc.collect()
        checkpoint("cleanup")

    runtime = {
        "phase_wall_s": elapsed | {"upload": None}, "phase_process_cpu_s": cpu,
        "wall_s_through_cleanup": perf_counter() - start, "process_cpu_s_through_cleanup": process_time() - cpu_start,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "logical_cores": os.cpu_count(), "arrow_cpu_threads": 4, "arrow_io_threads": 2, "blas_threads": 1,
        "python": sys.executable, "python_version": sys.version.split()[0],
        "logical_explicit_listed_input_bytes": sum(s["bytes"] for s in sources.values()),
        "logical_retained_projected_reader_bytes": binding["retained_deep_bytes"],
        "logical_output_bytes": sum(entry["bytes"] for entry in stamps.values()),
        "physical_backing_io_bytes": None,
    }
    result = {
        "action": "ACT-060A", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_ONE_STOCK_FALLBACK_AND_PAIR" if args.canary else "PASS_KB35_RAW_CSV_SVG_AND_PAIR_ALIGNMENT",
        "sources": sources, "baseline_commit": BASELINE, "code": OLD.identity(Path(__file__)),
        "reader": binding, "window": [OLD.START, OLD.END], "summary": summaries,
        "by_archetype": by_arch, "by_stock": by_stock, "control_rule": CONTROL_RULE,
        "main_rule": "Latest retained full20 event in window; otherwise latest retained full20 frozen historical event.",
        "reverse_event_rule": wave_b.EVENT_METHOD,
        "precision_rule": "Subtract exact same-D-basis prices and classify sign before dividing by D close; no epsilon.",
        "chart_basis": "Frozen Reader qfq with explicit physical/D-basis availability mask, no interpolation.",
        "chart_members": chart_evidence, "outputs": stamps, "runtime": runtime,
        "cleanup": {"temporary_files_created": 0, "temporary_files_removed": 0, "reader_copies_written": 0},
        "governance": {
            "model_fit": 0, "preprocess_fit": 0, "cluster_fit": 0, "model_load": 0, "prediction": 0,
            "new_scoring": 0, "tuning": 0, "simulated_trades": 0, "production_writes": 0, "orders": 0,
            "cumulative_research_FIT": 291, "flagship": "DUAL_5_5_E4B_E4C", "RESEARCH_ONLY": True,
            "STRICT_PIT": 0, "TRAIN_ADMITTED": 0, "NO_GO_BLOCKED": True, "production_allowed": False,
            "orders_sent": False, "buy_gate_updated": False, "knowledge_base_training_complete": False,
        },
    }
    write_json_exclusive(receipt_path, result)
    print(compact({"receipt": str(receipt_path), "status": result["status"], "summary": {
        key: summaries[key] for key in ("event_n", "full20_n", "hidden_same_day_n", "main_n", "pair_csv_rows",
                                        "charts_n", "zero_in_2y_codes", "peak_minus_D20_sign", "control_modes")},
                   "outputs": stamps, "wall_s": elapsed}), flush=True)


if __name__ == "__main__":
    main()
