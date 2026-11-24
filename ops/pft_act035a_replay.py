"""One-shot ACT035A research replay with outcome access after the selection seal."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, namedtuple
import csv
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import resource
from statistics import mean
import sys
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as arrow

from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates
from ops import pft_act033a_replay as act033
from ops import pft_act034a_replay as act034
from ops import pft_act034a_rules as rules
from ops import pft_act035a_features as features

ROOT = Path("/Users/lexi/Desktop/学习/v4_app/artifacts")
OUTPUT = ROOT / "pft_act035a_cross_project_20261124"
CUTOFF = act034.CUTOFF
CAP_BYTES = 8_500_000
CSV_NAME = "CODEX_MAC_ACT-035A_CROSS_PROJECT_ALIGN_DETAIL_20261124.csv"
SEED = 3511
N_BOOTSTRAP = 4000
BLOCK_SESSIONS = 5
SCHEMA = "pft.act035a.cross_project_replay.v1"
LOCKS = {
    "act034_selection": ("pft_act034a_s_v3_20261124/run/SELECTION_SEAL.json",
                         "43753048a1af35e33a000e6beaf111719c897efad3a803d0b6658849f4b2a97b"),
    "act034_summary": ("pft_act034a_s_v3_20261124/run/SUMMARY.json",
                       "50c2008159650fa46b687397dd821ea50fc865599e0d63625bfca60ad7d1187b"),
    "act034_trades": ("pft_act034a_s_v3_20261124/run/TRADE_DETAILS.csv",
                      "180c37a0d362c3cbaabb8fcf6e4993624647a84439ba1b7517644fedb1d10035"),
    "act031_selection": ("pft_act031_s_v3_20261124/run/signals/SEAL.json",
                         "92ba7128a2144333c8797520addc20414ba5322ff6cb51a4c68ec73533b6e150"),
    "act028_export": ("pft_act028_s_v3_20261123/CODEX_MAC_ACT-028_SV3_FINAL_113_PREDICTIONS_20261123.csv",
                      "65de0a0bc76b7722b6cbebd318ca1775467ce349cf395b03c29d110830c50aa7"),
    "act028_details": ("pft_act028_s_v3_20261123/run/external_predictions.csv",
                       "145246722de09d3defd3237c7f898e5d49ba62daf383d93770ddfde7feddcfa5"),
}
SIGNAL_FIELDS = (
    "trade_date", "ts_code", "name", "white", "yellow", "stage", "invalidation_price", "invalidation_anchor_date",
    "projected_p_s", "final_state", "main_tactic", "route_reasons", "feature_context_end",
)
BASE_A = "A1_EXIT_C1_BASELINE"
BASE_B = "B2_QUICK_BASELINE"
NO_CLIMAX = "B2_NO_CLIMAX"
C1_P515 = "C1_P515"
A1_EXT = "A1_EXT"
B2_ELASTIC = "B2_ELASTIC"
LANES = (BASE_B, NO_CLIMAX, B2_ELASTIC, BASE_A, C1_P515, A1_EXT)
A_LANES = {BASE_A, C1_P515, A1_EXT}
SELECT_POLICY = {
    NO_CLIMAX: "Frozen B2_QUICK ∧ L50M pass ∧ no hard climax. No refill.",
    C1_P515: "Frozen A1_EXIT+C1 ∧ L50M pass ∧ no hard climax. No refill.",
    A1_EXT: "Frozen A1_EXIT+C1 union exact frozen UNKNOWN_BORDERLINE with known V02/V04/V06 False, intact active anchor and existing C1. Frozen states are unchanged. Added rows use the causal proxy anchor for ACT034A A1_EXIT.",
    B2_ELASTIC: "Original B2 structural cohort, L50M pass, no hard climax, float cap <=50bn, 20-day amplitude >=3%, attack >=12pp, drawdown [-8,-2]pp, 3–10 bars since volume peak, decay <.75, amount ratio <=1.2, raw bullish, upper wick <=3% of previous close, and raw D return [1%,5%]. Original golden-priority, projected-P, symbol rank. Maximum 5/day, original B2_QUICK exit.",
}
B2_PROJECTION_PROOF = (
    "ACT033A retains BASE (every CONFIRMED_S) or b1_structural_eligible where True or unknown. "
    "Its b1 exact supplement includes every SH/SZ main-board UNKNOWN_BORDERLINE with exactly "
    "RAW_HEAD_DECISION_CONTRADICTION, without a cushion or age condition. "
    "These two cases are a superset of ACT034A B2 structure. Therefore 10/23 names outside "
    "the ACT033A projection are known outside B2 structure. The same projection does not "
    "provision the broader A1_EXT UNKNOWN_BORDERLINE eligibility on 10/23."
)
P515_SOURCE = {
    "ACT006_archive_sha256": "2b97e59e407e8b652e70c6260da7896bc733b68e120621a0abace925d99dbcc6",
    "ACT006_feature_freeze_sha256": "10c30df35a4e14829f5fb95edc9cf7ce2cf26c4b33f145fcb133315228effe08",
    "ACT006_archive": "https://drive.google.com/file/d/1LOAWQRh9gFgqn4exRFQUup4q02kjoauy/view",
    "ACT031_E3_peak_decay": "https://drive.google.com/file/d/11cyQsp3MlrMuukP8bzth3zA89dch6ye7p1Cx3kZB5Y4/view",
    "amount_difference": "Replay gates use D amount/prior20 mean. Archived V4 ACT006 uses D amount/inclusive20 mean, audited separately.",
}
OUTCOME_FIELDS = (
    "d1_date", "d1_top200_rank_source", "d1_top200_rank", "d1_top200_hit", "opening_fillable_proxy",
    "opening_status", "entry_basis_price", "exit_date", "exit_status", "exit_reason", "exit_time",
    "dynamic_gross", "dynamic_net", "worst_observed_path_gross", "path_complete", "qfq_d_anchor_alignment",
)
OUTCOME_BOOLEANS = {"d1_top200_hit", "opening_fillable_proxy", "path_complete"}
OUTCOME_NUMERIC = {"d1_top200_rank", "entry_basis_price", "dynamic_gross", "dynamic_net", "worst_observed_path_gross"}


def require(condition, reason):
    if not condition:
        raise act031.ContractError(f"ACT035A_{reason}")


def clean_record(row):
    return {name: None if value is pd.NA or value is pd.NaT else act031.review.clean(value)
            for name, value in row.items()}


def ref(root, name):
    path, digest = LOCKS[name]
    return {"path": str(root / path), "sha256": digest}


def signal_key(row):
    return row["trade_date"], row["ts_code"]


def source_frame(reference, columns=None):
    path = act033.checked(reference)
    return pd.read_parquet(path, columns=columns)


def read_dated_csv(path):
    # The exact parser preserves leading zeros and does not silently coerce labels.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass
class SealedInputs:
    inputs: dict
    calendar: object
    parent: dict
    signal_dates: list
    all_signals: dict
    overlays: dict
    observed: dict
    external: list
    references: dict


def load_signal_inputs(root):
    inputs, parent033, input_ref, ref033 = act034.load_seal(root / "pft_act033a_s_v3_20261124")
    ref034 = ref(root, "act034_selection")
    parent034 = act031.read_ref(ref034)
    dates = parent033["evaluable_days"]
    calendar = act031.act028.ExchangeSessions()
    require(
        parent034["input"] == input_ref and parent034["parent_selection_seal"] == ref033
        and parent034["signal_dates"] == dates and parent034["observed_cutoff"] == CUTOFF
        and parent034["observations_opened_in_signal_phase"] is False
        and parent034["fit_calls"] == act033.FIT_CALLS
        and act033.previous_days(calendar.schedule, CUTOFF, len(dates)) == [*dates, CUTOFF],
        "ACT034A_SELECTION_SCOPE_OR_CALENDAR_DRIFT",
    )
    prior_act031 = inputs["prior_act031"]
    require(prior_act031["signal_seal"] == ref(root, "act031_selection"), "ACT031_SEAL_BINDING_DRIFT")
    input031 = act031.read_ref(prior_act031["inputs"])
    seal031 = act031.read_ref(prior_act031["signal_seal"])
    require(
        seal031["input"] == prior_act031["inputs"] and seal031["evaluable_days"] == dates[1:]
        and seal031["observations_opened_in_signal_phase"] is False,
        "ACT031_SELECTION_OR_DATES_DRIFT",
    )
    all_signals, overlays, observed, checkpoints = {}, {}, {}, {}
    for day in dates:
        source = inputs["days"][day]
        checkpoint_ref = parent033["daily_receipts"][day]
        checkpoint = act031.read_ref(checkpoint_ref)
        group_ref = checkpoint["groups"]
        require(
            checkpoint["trade_date"] == day and checkpoint["input_source"] == source
            and checkpoint["plan"] == parent033["plan"] and checkpoint["status"] == "SIGNALS_FROZEN"
            and group_ref == parent034["checkpoints"][day],
            f"ACT033A_CHECKPOINT_DRIFT:{day}",
        )
        overlay = source_frame(group_ref)
        signal_ref = checkpoint["prior_signals"]
        if day in seal031["daily_receipts"]:
            signal_checkpoint_ref = seal031["daily_receipts"][day]
            signal_checkpoint = act031.read_ref(signal_checkpoint_ref)
            require(
                signal_checkpoint["trade_date"] == day and signal_checkpoint["source"] == source
                and input031["days"][day] == source and signal_checkpoint["status"] == "SIGNALS_FROZEN"
                and signal_checkpoint["run_identity"] == seal031["plan"]["sha256"]
                and signal_ref == signal_checkpoint["signals"],
                f"ACT031_CHECKPOINT_DRIFT:{day}",
            )
            frame = source_frame(signal_ref, list(SIGNAL_FIELDS))
            compare = frame.loc[frame.ts_code.isin(overlay.ts_code)].set_index("ts_code").sort_index()
            exact = overlay[list(SIGNAL_FIELDS)].set_index("ts_code").sort_index()
            pd.testing.assert_frame_equal(compare, exact, check_dtype=False)
        else:
            require(day == dates[0] and signal_ref is None and checkpoint["eligible_all_a"],
                    f"UNEXPECTED_ACT031_SIGNAL_GAP:{day}")
            signal_checkpoint_ref = None
            signal_ref = checkpoint["eligible_all_a"]
            frame = source_frame(signal_ref, ["ts_code"]).merge(
                overlay[list(SIGNAL_FIELDS[1:])], how="left", on="ts_code", validate="one_to_one"
            )
            frame["trade_date"] = day
        require(
            len(frame) == checkpoint["signals_scored_n"] and not frame.ts_code.duplicated().any()
            and frame.trade_date.eq(day).all() and frame.feature_context_end.dropna().eq(day).all()
            and set(overlay.ts_code) <= set(frame.ts_code) and not overlay.ts_code.duplicated().any(),
            f"CANDIDATE_SCOPE_DRIFT:{day}",
        )
        quotes, quote_ref = act031.day_quotes(day, source)
        require(quotes is not None and quote_ref == checkpoint["source_quotes"], f"D_OFFICIAL_QUOTE_DRIFT:{day}")
        observed[day] = (quotes, quote_ref)
        all_signals[day] = frame
        overlays[day] = {row["ts_code"]: clean_record(row) for row in overlay.to_dict("records")}
        checkpoints[day] = {"act033a_receipt": checkpoint_ref, "act033a_groups": group_ref,
                            "act031_receipt": signal_checkpoint_ref, "signal_or_universe": signal_ref,
                            "official_quotes": quote_ref}
    external, external_refs = load_external(root)
    return SealedInputs(inputs, calendar, parent034, dates, all_signals, overlays, observed, external,
                        {"act034a": ref034, "act033a": ref033, "act033a_input": input_ref,
                         "act031": prior_act031["signal_seal"], "checkpoints": checkpoints,
                         "external": external_refs})


def load_external(root):
    references = [ref(root, name) for name in ("act028_export", "act028_details")]
    primary, source = (read_dated_csv(act033.checked(reference)) for reference in references)
    identity = ("case_id", "cohort", "ts_code", "trade_date")
    secondary = {tuple(row[name] for name in identity): row for row in source}
    require(len(primary) == len(source) == len(secondary) == 113, "ACT028_EXTERNAL_COUNT_OR_DUPLICATE")
    fields = ("act028_final_state", "act028_main_tactic", "act028_route_reasons", "prediction_status")
    rows, seen = [], set()
    for row in primary:
        key = tuple(row[name] for name in identity)
        detail = secondary.get(key)
        require(key not in seen and detail is not None
                and all(row[name] == detail[name] for name in fields), "ACT028_EXTERNAL_IDENTITY_DRIFT")
        seen.add(key)
        rows.append({name: row[name] for name in (*identity, *fields, "truth_state", "truth_tactic",
                                                   "act025_projected_p_s")} | {
            f"frozen_act028_{name}": detail[name] or None
            for name in ("root_anchor_date", "active_anchor_date", "repair_anchor_date")
        } | {"act028_projected_p_s": detail["act028_projected_p_s"] or None})
    return rows, references


def original_rosters(sealed):
    originals = {}
    for record in sealed.parent["frozen_rosters"]:
        day, code = signal_key(record)
        strategy = record["strategy"]
        key = (day, code, strategy)
        require(key not in originals and day in sealed.overlays and code in sealed.overlays[day],
                f"ACT034A_DUPLICATE_OR_MISSING_ORIGINAL:{key}")
        row = SimpleNamespace(**sealed.overlays[day][code])
        wick = rules.upper_wick(sealed.observed[day][0].get(code))
        atoms = rules.selection_atoms(row, wick)
        require(atoms["c1_pass"] == record["c1_pass"], f"ACT034A_C1_FLAG_DRIFT:{key}")
        originals[key] = record
    require(Counter(key[-1] for key in originals) == Counter({"A1_EXIT": 66, "B2_QUICK": 34})
            and sum(key[-1] == "A1_EXIT" and row["c1_pass"] is True for key, row in originals.items()) == 52,
            "ACT034A_BASELINE_ROSTER_DRIFT")
    return originals


def outcome_record(raw):
    out = {}
    for name in OUTCOME_FIELDS:
        value = raw.get(name)
        if value == "":
            value = None
        if name in OUTCOME_BOOLEANS and value is not None:
            require(isinstance(value, bool) or value in ("True", "False"), f"OUTCOME_BAD_BOOLEAN:{name}")
            value = value is True or value == "True"
        if name in OUTCOME_NUMERIC and value is not None:
            value = int(float(value)) if name == "d1_top200_rank" else float(value)
        out[name] = value
    return out


def read_original_outcomes(root, sealed, originals, selection_ref):
    require(act031.read_ref(selection_ref)["phase"] == "SELECTION_SEALED", "OUTCOMES_BEFORE_NEW_SEAL")
    summary_ref, trade_ref = ref(root, "act034_summary"), ref(root, "act034_trades")
    summary = act031.read_ref(summary_ref)
    require(
        summary["selection_seal"] == sealed.references["act034a"] and summary["trade_details"] == trade_ref
        and summary["signal_dates"] == sealed.signal_dates and summary["observed_cutoff"] == CUTOFF,
        "ACT034A_OUTCOME_SOURCE_DRIFT",
    )
    rows = read_dated_csv(act033.checked(trade_ref))
    lookup = {(row["trade_date"], row["ts_code"], row["strategy"]): outcome_record(row) for row in rows}
    require(len(rows) == len(lookup) and set(lookup) == set(originals), "ACT034A_OUTCOME_ROSTER_DRIFT")
    return lookup, [summary_ref, trade_ref]


def calendar_book(sealed):
    return features.exchange_days(sealed.calendar.schedule)


def collect_history(bound, sealed, days, originals):
    codes = set().union(*(set(frame.ts_code) for frame in sealed.all_signals.values()))
    latest = sealed.signal_dates[-1]
    start = days[days.index(sealed.signal_dates[0]) - features.WINDOW]
    frame = features.observations(bound, start, latest, codes)
    require(len(frame) <= len(codes) * (features.WINDOW + len(sealed.signal_dates)),
            "FORWARD_HISTORY_SCOPE_TOO_LARGE")
    frame["_valid_bar"] = features.valid_bars({k: frame[k].to_numpy() for k in features.COLUMNS})
    indexed = {code: data.set_index("trade_date", drop=False) for code, data in
               features.observed_histories(frame).items()}
    receipts = [{"stage": "forward_base40", "start": start, "end": latest, "codes": len(codes),
                 "rows": len(frame), "projected_memory_bytes": int(frame.memory_usage(index=True, deep=True).sum())}]
    del frame
    requested = {}
    initial_codes = {(day, code) for day, code, _ in originals}
    for day, signals in sealed.all_signals.items():
        for row in signals.itertuples(index=False):
            if row.final_state == "UNKNOWN_BORDERLINE" or (day, row.ts_code) in initial_codes:
                anchor = act031.act028.date8(row.invalidation_anchor_date)
                if anchor and anchor <= day:
                    low = features.earlier(anchor, 35)
                    if low < start:
                        requested[row.ts_code] = min(low, requested.get(row.ts_code, low))
    if requested:
        early = min(requested.values())
        supplement = features.observations(bound, early, days[days.index(start) - 1], set(requested))
        receipts.append({"stage": "forward_older_anchors", "start": early, "end": start,
                         "codes": len(requested), "rows": len(supplement),
                         "projected_memory_bytes": int(supplement.memory_usage(index=True, deep=True).sum())})
        for code, bars in features.observed_histories(supplement).items():
            bars = bars.loc[bars.trade_date.ge(requested[code])].copy()
            bars["_valid_bar"] = features.valid_bars({k: bars[k].to_numpy() for k in features.COLUMNS})
            current = indexed.get(code)
            prev = bars.set_index("trade_date", drop=False)
            indexed[code] = pd.concat([prev, current]) if current is not None else prev

    # Bucket the sparse historical external cases by year and read only their
    # codes and needed date ranges. No full-table query or persisted copy.
    external_groups = defaultdict(list)
    for case in sealed.external:
        start_case = features.earlier(case["trade_date"], 110)
        for field in ("frozen_act028_root_anchor_date", "frozen_act028_active_anchor_date"):
            anchor = act031.act028.date8(case[field])
            if anchor is not None and anchor <= case["trade_date"]:
                start_case = min(start_case, features.earlier(anchor, 35))
        external_groups[case["trade_date"][:4]].append((start_case, case))
    external = {}
    for group in external_groups.values():
        early = min(item[0] for item in group)
        end = max(item[1]["trade_date"] for item in group)
        codes = {item[1]["ts_code"] for item in group}
        panel = features.observations(bound, early, end, codes)
        histories = features.observed_histories(panel)
        receipts.append({"stage": "historical_external", "start": early, "end": end, "codes": len(codes),
                         "rows": len(panel), "projected_memory_bytes": int(panel.memory_usage(index=True, deep=True).sum())})
        for start_case, case in group:
            key = (case["case_id"], case["cohort"])
            history = histories.get(case["ts_code"])
            external[key] = (history.loc[history.trade_date.between(start_case, case["trade_date"])].reset_index(drop=True)
                             if history is not None else None)
    return indexed, external, receipts


def record_atom_counts(values):
    known = np.isfinite(values)
    return {"known": int(known.sum()), "unknown": int((~known).sum())}


def fx_c1(quote, p515, wick):
    amount = act031.positive(quote.get("amount_cny")) if quote else None
    return gates.conjunction(gates.gte(amount, 100e6), gates.lte(p515.get("d_qfq_return_5d"), .15), gates.lte(wick, .035))


def elastic_atoms(structural, overlay, p515):
    overlay = overlay or {}
    return {
        "b2_structure": structural,
        "l50m": p515.get("l50m"),
        "no_climax": gates.negation(p515.get("hard_climax")),
        "float_cap_le_50bn": gates.lte(overlay.get("float_mv_d_cny"), 50e9),
        "amplitude20_ge_3pct": gates.gte(overlay.get("amplitude_ma20"), .03),
        "prior_attack_ge_12pp": gates.gte(p515.get("prior_attack_runup_pp"), 12),
        "actual_pullback_2_to_8pp": gates.within(p515.get("drawdown_from_prior20_high_pp"), -8, -2),
        "bars_since_peak_3_to_10": gates.within(p515.get("days_since_20d_vol_peak"), 3, 10),
        "post_peak_decay_lt_075": gates.negation(gates.gte(p515.get("pullback_vol_decay_ratio"), .75)),
        "amount_ratio_le_12": gates.lte(p515.get("amount_ratio_20"), 1.2),
        "d_bullish": overlay.get("raw_bullish"),
        "d_wick_le_3pct": gates.lte(overlay.get("d_upper_wick"), .03),
        "d_return_1_to_5pct": gates.within(overlay.get("return_d"), .01, .05),
    }


def store_flags(statuses, values):
    for name, result in values.items():
        statuses[name]["pass" if result is True else "reject" if result is False else "unknown"] += 1


def forward_phase(sealed, bound, adjust, originals):
    days = calendar_book(sealed)
    histories, ext_histories, reader_reads = collect_history(bound, sealed, days, originals)
    selected = {lane: [] for lane in LANES}
    details, daily = [], {}
    for day, signal in sealed.all_signals.items():
        quotes = sealed.observed[day][0]
        codes = signal.ts_code.tolist()
        grids, coverage = features.p515_for_day(day, codes, days, histories, adjust, quotes)
        grid_counts = {name: record_atom_counts(value) for name, value in grids.items()}
        known_r = np.isfinite(grids["amount_ratio_20"]) & np.isfinite(grids["amount_ratio_20_act006_v4"])
        grid_counts["amount_ratio_20_rule_disagreements"] = int(((grids["amount_ratio_20"] > 1.2)
            != (grids["amount_ratio_20_act006_v4"] > 1.2))[known_r].sum())
        statuses = defaultdict(Counter)
        elastic_status = defaultdict(Counter)
        elastic_sorted = []
        missing_count, display_n, pft_n = 0, 0, 0
        for idx, row in enumerate(signal.itertuples(index=False)):
            code = row.ts_code
            o_a = originals.get((day, code, "A1_EXIT"))
            o_b = originals.get((day, code, "B2_QUICK"))
            base_a = o_a is not None and o_a["c1_pass"] is True
            base_b = o_b is not None
            overlay = sealed.overlays[day].get(code)
            missing = pd.isna(row.final_state)
            extension_scope = None if missing else row.final_state == "UNKNOWN_BORDERLINE"
            missing_count += int(missing)
            # ACT033A's frozen projection includes all confirmed rows and
            # exact main-board pure-head conflicts, including structural nulls.
            wick = rules.upper_wick(quotes.get(code)) if overlay or extension_scope is not False else None
            if overlay:
                overlay = overlay | rules.selection_atoms(SimpleNamespace(**overlay), wick)
            b2_structure = overlay["b2_structural"] if overlay else False
            f = features.scalar_grid(grids, idx)
            observed = {}
            if extension_scope is True or base_a or base_b or b2_structure is not False:
                data = histories.get(code)
                observed = features.pft_measure(code, day, data.reset_index(drop=True) if data is not None else None,
                                                act031.act028.date8(row.invalidation_anchor_date), None,
                                                f, adjust, days, quotes.get(code))
                pft_n += 1
            c1 = (o_a["c1_pass"] if o_a is not None else fx_c1(quotes.get(code), f, wick)
                  if extension_scope is not False else None)
            extension = gates.conjunction(extension_scope, gates.negation(observed.get("V02")),
                                          gates.negation(observed.get("V04")), gates.negation(observed.get("V06")),
                                          observed.get("intact_anchor"), c1)
            novelty_atoms = elastic_atoms(b2_structure, overlay, f)
            elastic_pass = gates.conjunction(*novelty_atoms.values())
            keep = gates.conjunction(f["l50m"], gates.negation(f["hard_climax"]))
            flags = {BASE_B: base_b, NO_CLIMAX: gates.conjunction(base_b, keep), B2_ELASTIC: elastic_pass,
                     BASE_A: base_a, C1_P515: gates.conjunction(base_a, keep),
                     A1_EXT: gates.disjunction(base_a, extension)}
            store_flags(statuses, flags)
            if b2_structure is not False:
                store_flags(elastic_status, novelty_atoms)
            if not (o_a is not None or o_b is not None or missing or extension_scope or b2_structure is not False):
                continue
            display_n += 1
            entry = {
                "source_scope": "FORWARD_ACT034A", "trade_date": day, "ts_code": code,
                "name": row.name if pd.notna(row.name) else None,
                "frozen_state": row.final_state if not missing else None,
                "frozen_stage": row.stage if pd.notna(row.stage) else None,
                "frozen_route_reasons": row.route_reasons if pd.notna(row.route_reasons) else None,
                "frozen_projected_p_s": gates.finite(row.projected_p_s),
                "signal_evidence_status": "CANNOT_CONFIRM_ACT031_SIGNAL_1023_UNRETAINED" if missing else "FROZEN_D_ONLY",
                "pft_scope": extension_scope, "existing_c1": c1, "a1_ext_new_eligibility": extension,
                "b2_structural": b2_structure,
                "b2_arm": overlay["b2_arm"] if overlay else None,
                "b2_golden_priority": overlay["b2_golden_priority"] if overlay else None,
                "baseline_a1_rank": o_a["selection_rank"] if o_a else None,
                "baseline_b2_rank": o_b["selection_rank"] if o_b else None,
                "d_board_amplitude20": overlay.get("amplitude_ma20") if overlay else None,
                "d_float_mv_cny": overlay.get("float_mv_d_cny") if overlay else None,
                "d_official_return": rules.raw_ratio(quotes.get(code), "close", "prev_close"),
                "d_official_amount_cny": act031.positive(quotes.get(code, {}).get("amount_cny")),
                "d_official_upper_wick_vs_prev_close": wick,
                **f, **observed, **{f"{lane}_eligible": value for lane, value in flags.items()},
                **{f"{lane}_selected": value is True and lane != B2_ELASTIC for lane, value in flags.items()},
            }
            if b2_structure is not False:
                entry.update(b2_elastic_failed_atoms="|".join(k for k, v in novelty_atoms.items() if v is False),
                             b2_elastic_unknown_atoms="|".join(k for k, v in novelty_atoms.items() if v is None))
            details.append(entry)
            for lane in LANES:
                if lane != B2_ELASTIC and flags[lane] is True:
                    selected[lane].append(signal_key(entry))
            if elastic_pass is True:
                probability = gates.finite(row.projected_p_s)
                elastic_sorted.append((not overlay["b2_golden_priority"],
                                       -probability if probability is not None else float("inf"), code, entry))
        for rank, (_, _, code, entry) in enumerate(sorted(elastic_sorted)[:5], 1):
            entry[f"{B2_ELASTIC}_selected"] = True
            entry["b2_elastic_selection_rank"] = rank
            selected[B2_ELASTIC].append((day, code))
        daily[day] = {
            "eligible_all_A_n": len(signal), "full_signal_unknown_n": missing_count, "candidate_detail_rows_n": display_n,
            "pft_proxy_attempt_rows_n": pft_n, "p515_grid_known": grid_counts, "reader": coverage,
            "lane_eligibility": dict(statuses), "elastic_atoms_on_structural_scope": dict(elastic_status),
            "elastic_above_daily_cap_n": max(0, len(elastic_sorted) - 5),
        }
    for lane in LANES:
        selected[lane].sort()
    external_details = []
    for case in sealed.external:
        code, day = case["ts_code"], case["trade_date"]
        history = ext_histories[(case["case_id"], case["cohort"])]
        prefix, _ = adjust.for_window(code, day, history)
        quotes = sealed.observed.get(day)
        quote = quotes[0].get(code) if quotes else None
        sessions = days if day in days else None
        p515 = features.external_p515(code, prefix, sessions, quote)
        peak, decay = (None, None) if history is None else features.peak_decay(
            code, day, history.assign(_valid_bar=features.valid_bars({k: history[k].to_numpy()
                                                  for k in features.COLUMNS})).set_index("trade_date"), adjust)
        p515["days_since_20d_vol_peak"], p515["pullback_vol_decay_ratio"] = peak, decay
        observed = features.pft_measure(code, day, history, case["frozen_act028_active_anchor_date"],
                                       case["frozen_act028_root_anchor_date"],
                     features.external_observed_proxy_inputs(prefix, p515), adjust, sessions, quote)
        external_details.append({"source_scope": "EXTERNAL_ACT028_FROZEN", **case, **p515, **observed})
    details = sorted([*details, *external_details],
                     key=lambda r: (r["source_scope"] != "FORWARD_ACT034A", r["trade_date"], r["ts_code"],
                                    r.get("cohort", ""), r.get("case_id", "")))
    return details, selected, daily, reader_reads


def lane_strategy(lane):
    return "A1_EXIT" if lane in A_LANES else "B2_QUICK"


def read_new_outcomes(sealed, details, selected, saved):
    pending = {(day, code, lane_strategy(lane)) for lane in LANES for day, code in selected[lane]} - set(saved)
    if not pending:
        return {}, {"new_rows": 0}
    wanted = pd.DataFrame(sorted(pending), columns=["trade_date", "ts_code", "strategy"])
    bars, events, first, price_identity = act034.read_cutoff(sealed.inputs, wanted, sealed.calendar)
    observations = act034.read_observations(sealed.inputs, sealed.observed, set(wanted.ts_code))
    calendar = [first, *sealed.signal_dates, CUTOFF]
    evidence = {signal_key(row): row for row in details if row["source_scope"] == "FORWARD_ACT034A"}
    outcome_inputs = ("trade_date", "ts_code", "strategy", "close_d", "invalidation_price")
    OutcomeInput = namedtuple("OutcomeInput", outcome_inputs)
    outcomes = {}
    for day, code, strategy in sorted(pending):
        row = evidence[day, code]
        if strategy == "A1_EXIT":
            anchor, close = row.get("active_anchor_low"), row.get("d_basis_close")
            require(anchor is not None and close is not None, f"A1_EXT_SELECTED_ANCHOR_OR_CLOSE_UNKNOWN:{day}:{code}")
        else:
            overlay = sealed.overlays[day][code]
            anchor, close = overlay["invalidation_price"], overlay["close_d"]
        args = OutcomeInput(day, code, strategy, close, anchor)
        result = act034.evaluate_row(args, observations, sealed.observed, bars.get(code, {}), events[code], calendar, None)
        outcomes[day, code, strategy] = outcome_record(result)
    rank_evidence = {day: {k: v for k, v in obs.items() if k not in ("ranks", "quotes")}
                     for day, obs in observations.items()}
    return outcomes, {"new_rows": len(outcomes), "price_identity": price_identity, "rank_evidence": rank_evidence}


def zero_if_empty_rate(numerator, denominator):
    return numerator / denominator if denominator else None


def metrics(rows, day_count):
    n = len(rows)
    returns = [row["dynamic_net"] for row in rows if row["dynamic_net"] is not None]
    gross = [row["dynamic_gross"] for row in rows if row["dynamic_net"] is not None]
    buyable = [row for row in rows if row["opening_fillable_proxy"] is True]
    known = [row for row in rows if row["d1_top200_hit"] is not None]
    known_buyable = [row for row in buyable if row["d1_top200_hit"] is not None]
    hit = sum(row["d1_top200_hit"] is True for row in known)
    hit_buyable = sum(row["d1_top200_hit"] is True for row in known_buyable)
    ranks = {}
    for source in ("V4_OFFICIAL_TOP200", "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"):
        part = [row for row in rows if row["d1_top200_rank_source"] == source]
        observed = [row for row in part if row["d1_top200_hit"] is not None]
        observed_buyable = [row for row in observed if row["opening_fillable_proxy"] is True]
        ranks[source] = {
            "selected_n": len(part), "rank_known_n": len(observed), "rank_unknown_n": len(part) - len(observed),
            "hit_n": sum(row["d1_top200_hit"] is True for row in observed),
            "buyable_rank_known_n": len(observed_buyable),
            "buyable_hit_n": sum(row["d1_top200_hit"] is True for row in observed_buyable),
        }
    executed = len(returns)
    tail = sum(net < -.10 - rules.EPS for net in returns)
    return {
        "signal_days": day_count, "selected_n": n, "selected_per_day": n / day_count,
        "opening_buyable_n": len(buyable),
        "opening_known_unbuyable_n": sum(row["opening_fillable_proxy"] is False for row in rows),
        "opening_unknown_n": sum(row["opening_fillable_proxy"] is None for row in rows),
        "verified_entry_n": sum(row["entry_basis_price"] is not None for row in rows),
        "rank_known_n": len(known), "rank_unknown_n": n - len(known), "rank_hits": hit,
        "rank_hit_rate": zero_if_empty_rate(hit, len(known)),
        "buyable_rank_known_n": len(known_buyable), "buyable_rank_unknown_n": len(buyable) - len(known_buyable),
        "buyable_hits": hit_buyable, "buyable_hit_rate": zero_if_empty_rate(hit_buyable, len(known_buyable)),
        "ranks_by_source": ranks,
        "dynamic_executed_n": executed, "dynamic_unresolved_n": n - executed,
        "exit_immature_or_due_after_cutoff_n": sum(row["exit_status"] in {"HORIZON_IMMATURE_AT_CUTOFF",
                                                                         "EXIT_DUE_AFTER_CUTOFF"} for row in rows),
        "net_mean": mean(returns) if returns else None, "gross_mean": mean(gross) if gross else None,
        "net_win_n": sum(net > 0 for net in returns),
        "net_win_rate": zero_if_empty_rate(sum(net > 0 for net in returns), executed),
        "net_below_minus_10_n": tail, "net_below_minus_10_rate": zero_if_empty_rate(tail, executed),
        "net_min": min(returns) if returns else None,
        "exit_status_counts": dict(Counter(row["exit_status"] for row in rows)),
    }


def bootstrap(sides, days):
    """Paired, overlapping moving day blocks. Omit undefined draws explicitly."""
    rng = np.random.default_rng(SEED)
    offsets = rng.integers(0, len(days) - BLOCK_SESSIONS + 1,
                           (N_BOOTSTRAP, (len(days) + BLOCK_SESSIONS - 1) // BLOCK_SESSIONS))
    indices = (offsets[:, :, None] + np.arange(BLOCK_SESSIONS)).reshape(N_BOOTSTRAP, -1)[:, :len(days)]
    result = {}
    definitions = {
        "executed_net_mean": (lambda r: r["dynamic_net"] is not None, lambda r: r["dynamic_net"]),
        "buyable_rank_hit_rate": (lambda r: r["opening_fillable_proxy"] is True and r["d1_top200_hit"] is not None,
                                  lambda r: int(r["d1_top200_hit"])),
    }
    for name, (valid, value) in definitions.items():
        ratios = []
        for rows in sides:
            available = defaultdict(list)
            for day, row in rows:
                if valid(row):
                    available[day].append(value(row))
            totals = [sum(available[d]) for d in days]
            counts = [len(available[d]) for d in days]
            sampled_den = np.take(counts, indices).sum(axis=1)
            sampled_num = np.take(totals, indices).sum(axis=1)
            ratios.append(features.divide(sampled_num, sampled_den))
        deltas = ratios[0] - ratios[1]
        valid_delta = deltas[np.isfinite(deltas)]
        result[name] = {
            "bootstrap_draws_with_both_denominators": len(valid_delta),
            "bootstrap_draws_undefined": N_BOOTSTRAP - len(valid_delta),
            "paired_day_block_percentile95": [float(x) for x in np.quantile(valid_delta, [.025, .975])]
            if len(valid_delta) else None,
        }
    return result


def lane_results(details, selected, saved, new, days):
    rows = {signal_key(row): row for row in details if row["source_scope"] == "FORWARD_ACT034A"}
    outcomes = saved | new
    active = {}
    result = {}
    for lane in LANES:
        strategy = lane_strategy(lane)
        lane_rows = []
        for day, code in selected[lane]:
            key = (day, code, strategy)
            outcome = outcomes[key]
            lane_rows.append((day, outcome))
            prefix = "a1_" if strategy == "A1_EXIT" else "b2_"
            rows[day, code].update({prefix + name: value for name, value in outcome.items()})
            rows[day, code][prefix + "outcome_source"] = "ACT034A_SAVED" if key in saved else "ACT035A_NEW_REPLAY"
        active[lane] = lane_rows
        summary = metrics([row for _, row in lane_rows], len(days))
        summary["by_day"] = {day: metrics([row for when, row in lane_rows if when == day], 1) for day in days}
        result[lane] = summary
    a, b = result[BASE_A], result[BASE_B]
    require(a["selected_n"] == 52 and a["dynamic_executed_n"] == 42 and a["net_below_minus_10_n"] == 0
            and round(a["net_mean"] * 100, 2) == .53
            and b["selected_n"] == 34 and b["opening_buyable_n"] == 34 and b["rank_hits"] == 2
            and b["dynamic_executed_n"] == 30 and round(b["net_mean"] * 100, 2) == -.06
            and b["ranks_by_source"]["V4_OFFICIAL_TOP200"]["rank_known_n"] == 28
            and b["ranks_by_source"]["RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"]["rank_known_n"] == 6
            and b["ranks_by_source"]["V4_OFFICIAL_TOP200"]["hit_n"] == 2,
            "ACT034A_SAVED_BASELINE_ORACLE_FAILED")
    comparisons = {}
    for lane, baseline in ((NO_CLIMAX, BASE_B), (B2_ELASTIC, BASE_B), (C1_P515, BASE_A), (A1_EXT, BASE_A)):
        a, b = result[lane], result[baseline]
        a_roster, b_roster = set(selected[lane]), set(selected[baseline])
        comparisons[lane] = {
            "baseline": baseline, "added_n": len(a_roster - b_roster), "removed_n": len(b_roster - a_roster),
            "net_mean_delta": a["net_mean"] - b["net_mean"] if a["net_mean"] is not None and b["net_mean"] is not None else None,
            "buyable_rank_hit_rate_delta": a["buyable_hit_rate"] - b["buyable_hit_rate"]
            if a["buyable_hit_rate"] is not None and b["buyable_hit_rate"] is not None else None,
            "bootstrap": bootstrap((active[lane], active[baseline]), days),
        }
    return result, comparisons


def write_csv_atomic(path, rows):
    # Project all fields once, then validate the exact bytes to be delivered.
    headers = list(dict.fromkeys(key for row in rows for key in row))
    for field in ("V01", "V03", "V05"):
        if field not in headers:
            headers.append(field)
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = buf.getvalue().encode("utf-8-sig")
    require(len(payload) < CAP_BYTES - 30_000, "DELIVERABLE_CSV_BYTE_BUDGET")
    parsed = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline="")))
    require(len(parsed) == len(rows) and all(None not in row for row in parsed), "DELIVERABLE_CSV_PARSE_MISMATCH")
    temp = path.with_name(f".{path.name}.{os.getpid()}.pending")
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return act031.ref(path) | {"bytes": len(payload), "rows": len(rows), "columns": len(headers)}


def filter_attribution(details):
    statuses = {}
    for lane in (BASE_B, BASE_A):
        scope = [row for row in details if row.get(f"{lane}_selected") is True]
        counts = Counter((str(row["l50m"]), str(row["hard_climax"])) for row in scope)
        statuses[lane] = {
            "l50m_known_reject": sum(row["l50m"] is False for row in scope),
            "l50m_unknown": sum(row["l50m"] is None for row in scope),
            "actual_climax": sum(row["hard_climax"] is True for row in scope),
            "climax_unknown": sum(row["hard_climax"] is None for row in scope),
            "pure_anti_climax_keep_n": sum(row["hard_climax"] is False for row in scope),
            "joint_l50m_climax": {a + "|" + b: n for (a, b), n in counts.items()},
        }
    return statuses


def code_refs():
    local = Path(__file__).resolve()
    names = [local, local.with_name("pft_act035a_features.py"), Path(act034.__file__), Path(rules.__file__)]
    return [act031.ref(name) for name in names]


def replay(root, output):
    clock = perf_counter()
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    sealed = load_signal_inputs(root)
    originals = original_rosters(sealed)
    bound, symbols, source_identity = features.bind(sealed.inputs["days"][features.ASOF])
    started = act031.json_atomic(output / "RUN_STARTED.json", {
        "schema": SCHEMA, "code": code_refs(), "signal_inputs": sealed.references, "feature_source": source_identity,
        "cutoff": CUTOFF, "forward_replay_count_allowed": 1, "observations_opened": False, **act031.FLAGS,
    })
    adjustment = features.Adjustment(symbols, features.load_act030())
    targeted = perf_counter()
    details, selected, daily, reader_reads = forward_phase(sealed, bound, adjustment, originals)
    feat_elapsed = perf_counter() - targeted
    selection_ref = act031.json_atomic(output / "SELECTION_SEAL.json", {
        "schema": SCHEMA, "phase": "SELECTION_SEALED", "run_start": started, "cutoff": CUTOFF,
        "signals": sealed.signal_dates, "prior_rule_reviewed_dates": sealed.signal_dates[1:],
        "feature_policy": features.POLICY, "selection_policy": SELECT_POLICY, "p515_source": P515_SOURCE,
        "B2_projection_proof": B2_PROJECTION_PROOF,
        "source": source_identity, "selected": selected,
        "candidate_rows": len(details), "candidate_values_sha256": act031.review.digest(
            [clean_record(row) for row in details]),
        "daily_feature_coverage": daily, "filter_attribution": filter_attribution(details),
        "outcome_file_read_before_seal": False, "fit_calls": act033.FIT_CALLS, "predict_calls": 0,
        "model_load_calls": 0, **act031.FLAGS,
    })
    print(json.dumps({"phase": "SELECTION_SEALED", "counts": {key: len(value) for key, value in selected.items()},
                      "seal": selection_ref}), flush=True)
    outcome_time = perf_counter()
    saved, outcome_refs = read_original_outcomes(root, sealed, originals, selection_ref)
    new, new_refs = read_new_outcomes(sealed, details, selected, saved)
    performance, comparisons = lane_results(details, selected, saved, new, sealed.signal_dates)
    elapsed_outcomes = perf_counter() - outcome_time
    deliver_time = perf_counter()
    csv_ref = write_csv_atomic(output / CSV_NAME, details)
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    summary = {
        "schema": SCHEMA, "phase": "FORWARD_REPLAY_COMPLETE", "run_start": started, "selection_seal": selection_ref,
        "detail_csv": csv_ref, "cutoff": CUTOFF, "prior_rule_reviewed_days": 20, "signal_dates": sealed.signal_dates,
        "unavailable_act033a_dates": sealed.parent["unavailable_signal_days"],
        "reader_bound_projected_reads": reader_reads, "external_cohorts": dict(Counter(row["cohort"] for row in sealed.external)),
        "external_count_n": len(sealed.external), "external_unique_code_day_n": len({signal_key(r) for r in sealed.external}),
        "baseline_outcome_sources": outcome_refs, "new_outcomes": new_refs, "lane_metrics": performance,
        "exploratory_comparisons": comparisons, "round_trip_fee": rules.FEE,
        "bootstrap": {"seed": SEED, "draws": N_BOOTSTRAP, "block_sessions": BLOCK_SESSIONS,
                      "description": "Paired overlapping chronological moving day blocks; final block truncated. Computed only with both sample denominators. Exploratory descriptive intervals."},
        "historical_PIT": "CANNOT_CONFIRM", "fit_calls": act033.FIT_CALLS, "predict_calls": 0,
        "model_load_calls": 0, "forward_replay_calls": 1,
        "runtime": {"wall_seconds_before_summary": perf_counter() - clock,
                    "source_setup_seconds": targeted - clock, "D_feature_and_roster_seconds": feat_elapsed,
                    "outcome_and_metrics_seconds": elapsed_outcomes, "csv_seconds": perf_counter() - deliver_time,
                    "peak_rss_bytes": usage1.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                    "cpu_cores": os.cpu_count(), "arrow_threads": arrow.cpu_count(),
                    "configured_threads": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "ARROW_NUM_THREADS")},
                    "input_block_operations": usage1.ru_inblock - usage0.ru_inblock,
                    "output_block_operations": usage1.ru_oublock - usage0.ru_oublock,
                    "physical_read_write_bytes": "CANNOT_CONFIRM_MAC_RUSAGE_BLOCK_COUNTERS_ARE_NOT_BYTES",
                    "projected_memory_bytes": sum(x["projected_memory_bytes"] for x in reader_reads),
                    "detail_csv_bytes": csv_ref["bytes"], "upload_bytes": 0},
        **act031.FLAGS,
    }
    return act031.json_atomic(output / "SUMMARY.json", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", action="store_true", required=True)
    parser.parse_args()
    arrow.set_cpu_count(min(8, os.cpu_count() or 1))
    with act031.exclusive_run(OUTPUT):
        require(not any((OUTPUT / name).exists() for name in ("RUN_STARTED.json", "SELECTION_SEAL.json", "SUMMARY.json", CSV_NAME)),
                "ONE_REPLAY_RUN_ALREADY_OPENED")
        state = replay(ROOT, OUTPUT)
    print(json.dumps({"phase": "OUTCOMES_RECORDED", "summary": state}), flush=True)


if __name__ == "__main__":
    main()
