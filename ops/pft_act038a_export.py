"""Export frozen S_V3 D-only research predictions and explicit missing rows."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from functools import lru_cache
from math import isclose
from multiprocessing import get_context
import os
from pathlib import Path
import resource
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as g
from ops import pft_act033a_replay as a33
from ops import pft_act034a_rules as r34
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36i
from ops import pft_act036a_replay as a36
from ops import pft_act037a_inputs as a37

ROOT = a35.ROOT
OUTPUT = ROOT / "pft_act038a_oos_export_20261124"
SEAL = "PREDICTION_SEAL.json"
START = "EXPORT_STARTED.json"
STOP_REF = {"path": str(OUTPUT / "EXPORT_STOP_RECEIPT.json"),
            "sha256": "54aad5f906a923a138dc3039f35f97002c00642d74444380e902b93f04eb0cab"}
ORIGINAL_CODE = {"path": str(OUTPUT / ".export_original_8640acc6.py"),
                 "sha256": "8640acc61922f36097ebadf0977f17bd65129cf1b247928f67268c8461ab86dd"}
PENDING_RECOVERY_DATES = ("20261023", "20261026")
SCHEMA_ID = "pft.act038a.oos_export.v1"
TRAIN_CUTOFF = "20260831"
MODEL_VERSION = "S_V3.0_FROZEN"
MODEL_COMMIT = "fc528d9da0d6"
MODEL_COMMIT_FULL = "fc528d9da0d6886e0ec8361ac0a5ac3a5f84d1b6"
MAX_BYTES = 9_500_000
RAW_COLS = ("raw_p_s", *(f"raw_p_{c}" for c in a31.old.CLASSES))
TACTICS = tuple(a31.old.CLASSES[:3])
ST_OFFICIAL = "DATED_V4_OFFICIAL_TDX_G4DAY_NAME"
ST_MISSING = "DATED_ST_STATUS_UNAVAILABLE"
STATE_DEV = "ACT031_FROZEN_D_SAVED"
STATE_EARLY = "ACT036_D_REBASED_CAUSAL_PREFIX"
STATE_EXACT_RECIPE = "V4_DATED_OWNER_RECIPE_EXACT_D"
ST_SUPPLEMENT = "ACT038_SAME_FROZEN_HEADS_DATED_ST_SUPPLEMENT"
FULL_READY = "FROZEN_HGB_D_ONLY"
SHADOW = "RAW_SHADOW_STRICT_G1"
ST_SHADOW = "RAW_SHADOW_STRICT_G1_DATED_ST_SUPPLEMENT"
EXT1 = "EXT1_LINE_SPREAD_CLEAN"
EXT3 = "EXT3_STRONG_HEAD_CONFLICT"
PURE = "PURE_HEAD_CONFLICT"
HIGH = "HIGH_P_BORDERLINE_050_085"
NONE = "NONE"
MISSING_ENUM = {"READY", "INSUFFICIENT_65_BARS", "MISSING_CONTEXT", "SUSPENDED_OR_OUT_OF_UNIVERSE"}
SCHEMA = pa.schema([
    pa.field("trade_date", pa.string(), nullable=False),
    pa.field("ts_code", pa.string(), nullable=False),
    pa.field("prediction_status", pa.string(), nullable=False),
    pa.field("missing_reason", pa.string(), nullable=False),
    pa.field("s_decision_state", pa.string()),
    pa.field("main_tactic", pa.string()),
    pa.field("best_candidate_tactic", pa.string()),
    pa.field("projected_p_s", pa.float64()),
    *[pa.field(name, pa.float64()) for name in RAW_COLS],
    pa.field("stage_code", pa.string()),
    pa.field("route_reasons", pa.string()),
    pa.field("strict_g1_failure", pa.bool_()),
    pa.field("invalidation_price", pa.float64()),
    pa.field("cushion_pct", pa.float64()),
    pa.field("anchor_age_sessions", pa.int16()),
    pa.field("repair_age", pa.int16()),
    pa.field("early_borderline_tier", pa.string(), nullable=False),
    pa.field("is_st", pa.bool_()),
    pa.field("model_version", pa.string(), nullable=False),
    pa.field("model_commit", pa.string(), nullable=False),
    pa.field("train_cutoff_date", pa.string(), nullable=False),
    pa.field("is_strict_oos_post_cutoff", pa.bool_(), nullable=False),
    pa.field("score_source", pa.string()),
    pa.field("decision_source", pa.string()),
    pa.field("missing_detail", pa.string()),
    pa.field("early_borderline_tier_source", pa.string()),
    pa.field("st_source", pa.string(), nullable=False),
    pa.field("membership_source", pa.string(), nullable=False),
    pa.field("D_name", pa.string()),
    pa.field("d_close_qfq", pa.float64()),
    pa.field("d_close_source", pa.string()),
    pa.field("feature_context_end", pa.string()),
    pa.field("invalidation_anchor_date", pa.string()),
    pa.field("repair_anchor_date", pa.string()),
    pa.field("shadow_stage_code", pa.string()),
    pa.field("known_previously_exposed", pa.bool_(), nullable=False),
], metadata={b"schema_id": SCHEMA_ID.encode(), b"market": b"A_SHARE",
             b"train_cutoff_date": TRAIN_CUTOFF.encode(), b"prices": b"D_QFQ_ASOF"})
POLICY = {
    "model": "Two SHA-pinned ACT023/ACT028 frozen heads; unchanged ACT025 route and ACT028 maturity. No fit or tuning.",
    "membership": "Date-keyed equity family from D official package, D archived Reader, prior chart existence and exact saved rows. Prior-known-only keys retain uncertain activity and no inferred future listing.",
    "ST": "Same-date official name only. Known dated ST included as supplemental inference on otherwise valid observations; unknown status remains null.",
    "strict_G1_shadow": "Ready 65-bar same-feature raw-only HGB head scores. Frozen three-state, projected score, tactic and invalidation remain unchanged. Actual raw-head availability and evidence are explicit.",
    "missing": "Unavailable score, hedge, prices, dates and age stay NULL with a typed field and explicit cause where evidence determines it.",
    "selection_seal": "Every finalized shard is SHA-locked before any D+1 outcome data are accessed by the independent metric consumer.",
}


def require(predicate, reason):
    if not predicate:
        raise a31.ContractError(f"ACT038A_{reason}")


@dataclass
class Project:
    sources: a37.Sources
    reader: a36i.Reader
    plans: dict
    frozen_model: dict
    model_ref: dict
    prior_exposure: set


def load_project():
    sources = a37.load_sources()
    plan = a31.read_ref(sources.prior.references["act031"])["plan"]
    expected = a31.read_ref(plan)["model"]
    require(expected["cutoff"] == TRAIN_CUTOFF and len(expected["feature_order"]) == 43,
            "MODEL_TRAIN_CUTOFF_OR_FEATURE_SCHEMA_DRIFT")
    known = a31.read_ref(a37.ACT036_SEAL)["known_previously_exposed_keys"]
    exposure = {(row["trade_date"], row["ts_code"]) for row in known}
    require(len(exposure) == 24, "PRIOR_EXPOSURE_IDENTITY_DRIFT")
    preserved = {}
    for day in sources.dev[1:]:
        ref = sources.prior.references["checkpoints"][day]["signal_or_universe"]
        require(isinstance(ref, dict) and ref["path"].endswith(f"/{day}.parquet"), f"DEV_SCORE_REFERENCE_DRIFT:{day}")
        preserved[day] = ref
    return Project(sources, a37.bound(sources, a37.FRIDAY), preserved, expected, plan, exposure)


def record_values(frame, names):
    return {row["ts_code"]: a35.clean_record(row) for row in frame[list(names)].to_dict("records")}


ACT031_COLS = (
    "trade_date", "ts_code", "name", "white", "yellow", "prediction_status", "feature_context_start",
    "feature_context_end", "feature_causal_bars", "stage", "invalidation_price", "invalidation_anchor_date",
    "repair_anchor_date", "strict_g1_failure", "final_state", "main_tactic", "route_reasons",
    "projected_p_s", *RAW_COLS,
)


def saved_signals(project, day):
    if day not in project.plans:
        return None
    ref = project.plans[day]
    frame = a35.source_frame(ref, list(ACT031_COLS))
    prior = project.sources.prior.all_signals[day]
    require(len(frame) == len(prior) and not frame.ts_code.duplicated().any()
            and frame.trade_date.eq(day).all() and frame.feature_context_end.dropna().eq(day).all()
            and set(frame.ts_code) == set(prior.ts_code), f"DEV_FULL_SCORE_KEYS_OR_CONTEXT_DRIFT:{day}")
    shared = [name for name in a35.SIGNAL_FIELDS if name in frame]
    pd.testing.assert_frame_equal(frame[shared].sort_values("ts_code").reset_index(drop=True),
                                  prior[shared].sort_values("ts_code").reset_index(drop=True), check_dtype=False)
    return frame


def current_rows(frame, day):
    return {row["ts_code"]: a35.clean_record(row) for row in frame.loc[frame.trade_date.eq(day)].to_dict("records")}


def stable_names(quote, prior):
    raw = quote.get("name") if quote else None
    return raw if raw else prior.get("name") if prior else None


def dated_admissions(prefix, day, official, quotes, authority, saved, eligible_day):
    restored, counts = a36i.historical_admission(prefix, day, quotes, authority)
    if saved is not None:
        candidate = set(saved.ts_code)
    elif eligible_day is not None:
        candidate = eligible_day
    else:
        candidate = set(restored)
    exact = current_rows(prefix, day)
    st_codes = set()
    bars_by_code = prefix.groupby("ts_code", sort=False).size().to_dict()
    if official:
        for code, quote in official.items():
            if a31.special_treatment(quote.get("name")) is not True:
                continue
            row = exact.get(code)
            if row and row.get("tradeable_basic") == 1 and quote.get("eligible_for_daily_gain_rank") and (
                    a31.positive(row.get("bars_since_list")) or bars_by_code.get(code, 0)) >= 65:
                st_codes.add(code)
    return candidate, st_codes, restored, counts, exact, bars_by_code


def historical_membership(history, current, official, saved, day):
    vintage = set(history.loc[history.trade_date.between(f35.earlier(day, a36i.FORECAST_HISTORY), day), "ts_code"])
    keys = vintage | set(current) | set(official) | set(saved)
    labels = {}
    for code in sorted(keys):
        if a31.a_share_instrument_rejection(code):
            continue
        if code in official:
            labels[code] = "DATED_OFFICIAL"
        elif code in current:
            labels[code] = "DATED_V4_READER_D_BAR"
        elif code in saved:
            labels[code] = "DATED_FROZEN_ELIGIBLE_KEY"
        else:
            labels[code] = "PRIOR_V4_EXISTENCE_D_ACTIVITY_UNCONFIRMED"
    return labels


def exact_recovery(day, project, universe, official):
    from ops.pft_act031_raw_prefix import read_recovered

    scope = set(universe) | {code for code, quote in official.items()
                             if a31.special_treatment(quote.get("name")) is True
                             and quote.get("eligible_for_daily_gain_rank")}
    original = project.sources.prior.inputs["days"].get(day, {})
    raw = read_recovered(day, original, scope)
    # Keep the source receipt off-frame. Pandas otherwise deep-copies the
    # large alias list on each slice and group during numerical extraction.
    receipt = raw.attrs.pop("recovery")
    require(not raw.attrs, "UNEXPECTED_DATED_PREFIX_ATTRS")
    require(not raw.duplicated(["trade_date", "ts_code"]).any()
            and raw.trade_date.le(day).all() and set(raw.ts_code) <= scope, "EXACT_D_OWNER_PREFIX_SCOPE")
    return raw, {k: v for k, v in receipt.items() if k != "same_sha_native_substitutions"} | {
        "same_sha_native_substitutions_sha256": a31.review.digest(receipt["same_sha_native_substitutions"]),
        "receipt_metadata_detached_before_projection": True,
    }


def daily_state(day, code, candidate, entry, pair, sessions):
    shadow = a31.strict_g1(candidate.get("zge_white_line"), candidate.get("zge_yellow_line"))
    if shadow:
        evidence = {"status": "NOT_INFERRED_STRICT_OBSERVED_G1", "white": candidate["zge_white_line"],
                    "yellow": candidate["zge_yellow_line"]}
        actual_scores = None, None
    else:
        evidence = entry
        actual_scores = pair
    baseline = a31.act025.route(*actual_scores, evidence)
    anchors = evidence.get("anchors", {})
    repair = next((x["date"] for x in reversed(anchors.get("events", [])) if x["role"] == "repair"), None)
    active = anchors.get("active") or {}
    result = a31.act028.maturity(baseline, repair, day, sessions, anchor_status="ACT023_ACT021_CAUSAL_ROLE_STACK")
    return result | {
        "trade_date": day, "ts_code": code, "prediction_status": evidence["status"], "stage": evidence.get("stage"),
        "feature_context_end": evidence.get("context_end"), "invalidation_price": a31.positive(active.get("low")),
        "invalidation_anchor_date": active.get("date"), "repair_anchor_date": repair,
    }


def score_context(prefix, to_score, day, models):
    if not to_score:
        return {}
    h = prefix.loc[prefix.ts_code.isin(to_score), [*a31.old.INPUTS, "bbi"]]
    require(set(h.ts_code) <= set(to_score) and h.trade_date.le(day).all(), "MODEL_POST_D_OR_EXTRA_KEY")
    x, evidence = a31.prior.extract_structure(h, day, to_score)
    predictions = a31.prior.batch_predict(models, x, evidence)
    return {code: (evidence[idx], predictions.get(idx, (None, None))) for idx, code in enumerate(to_score)}


def tied_argmax(row):
    scores = [g.finite(row.get(f"raw_p_{tactic}")) for tactic in TACTICS]
    return TACTICS[scores.index(max(scores))] if None not in scores else None


def strict_original_lines(saved, d_row):
    if not d_row:
        return False
    for original, recovered in (("white", "zge_white_line"), ("yellow", "zge_yellow_line")):
        left, right = g.finite(saved.get(original)), g.finite(d_row.get(recovered))
        if left is None or right is None or not isclose(left, right, rel_tol=1e-9, abs_tol=1e-9):
            return False
    return a31.strict_g1(d_row["zge_white_line"], d_row["zge_yellow_line"])


def verify_projected(rows, projected):
    differences = []
    for code, old in projected.items():
        new = rows.get(code)
        if not new:
            continue
        drift = [name for name in ("final_state", "stage", "route_reasons", "main_tactic", "invalidation_anchor_date")
                 if (new.get(name) or None) != (old.get(name) or None)]
        for name in ("projected_p_s", "invalidation_price"):
            left, right = g.finite(old.get(name)), g.finite(new.get(name))
            match = (left is right) if None in (left, right) else isclose(left, right, rel_tol=0, abs_tol=1e-9)
            if not match:
                drift.append(name)
        if drift:
            differences.append({"ts_code": code, "fields": drift})
    return differences


@lru_cache(maxsize=16000)
def repair_distance(sessions, anchor, day):
    if anchor is None:
        return None
    n, _ = sessions.age(anchor, day)
    return n


def audited_tiers(checkpoint):
    from ops.pft_act037a_timing import ext3_row

    tiers = {}
    for row in checkpoint["selections"]["A1_V2"]:
        if row.get("extension_only") is not True:
            continue
        code, route = row["ts_code"], row["route_reasons"]
        require(g.conjunction(*a36.a1_atoms(row, row, row["c1_pass"]).values()) is True,
                f"ACT036_TIER_ATOMS_DRIFT:{code}")
        if ext3_row(row)[0]:
            tiers[code] = EXT3, "ACT036A_A1_V2_VERIFIED_STRONG_HEAD_AND_ACT037_CUSHION"
        elif route == a36.EXACT_LINE:
            tiers[code] = EXT1, "ACT036A_A1_V2_VERIFIED_LINE_SINGLETON"
        else:
            require(False, f"ACT036_UNEXPECTED_EXTENSION_MEMBERSHIP:{code}")
    return tiers


def early_tier(row, frozen_tier):
    if row.get("final_state") != "UNKNOWN_BORDERLINE":
        return NONE, None
    if frozen_tier:
        same_route = ((frozen_tier[0] == EXT3 and a36.STRONG in (row.get("route_reasons") or "").split(";"))
                      or (frozen_tier[0] == EXT1 and row.get("route_reasons") == a36.EXACT_LINE))
        require(same_route, f"VERIFIED_EXTENSION_ROUTE_DRIFT:{row.get('ts_code')}")
        return frozen_tier
    if row.get("route_reasons") == g.CONTRADICTION:
        return PURE, "EXACT_RAW_HEAD_DISAGREEMENT_SINGLETON"
    p = g.finite(row.get("projected_p_s"))
    if p is not None and .50 <= p < .85:
        return HIGH, "CAUSAL_FROZEN_PROJECTED_S_IN_050_085"
    return NONE, "FROZEN_UNKNOWN_WITHOUT_VERIFIED_EXTENSION_OR_BROAD_TIER"


def null_reason(code, listing_source, current, official, eligible, known_st, calc, bars):
    if calc:
        return None
    if code in eligible:
        return "FIXED_ADMISSION_BUT_EXACT_D_CONTEXT_UNAVAILABLE"
    quote = official.get(code)
    if quote and quote.get("zero_volume") is True:
        return "DATED_OFFICIAL_ZERO_VOLUME_OR_HALTED"
    if listing_source == "PRIOR_V4_EXISTENCE_D_ACTIVITY_UNCONFIRMED":
        return "PRIOR_KNOWN_SYMBOL_D_ACTIVITY_UNCONFIRMED"
    if current is None:
        return "D_READER_CONTEXT_UNAVAILABLE"
    observed = a31.positive(current.get("bars_since_list")) or bars.get(code, 0)
    if current.get("tradeable_basic") == 1 and observed < 65:
        return "INSUFFICIENT_65_BARS"
    if known_st is True:
        return "DATED_ST_RETAINED_BUT_NO_VALID_D_CONTEXT"
    if quote and not quote.get("eligible_for_daily_gain_rank"):
        return "DATED_OFFICIAL_BAR_INVALID"
    if current.get("tradeable_basic") != 1:
        return "D_READER_BAR_NONTRADEABLE"
    return "D_ADMISSION_UNCONFIRMED"


def coarse_missing(score_count, diagnostic):
    if score_count:
        return "READY"
    if diagnostic in {"INSUFFICIENT_65_BARS", "MISSING_65_VALID_CAUSAL_BARS"}:
        return "INSUFFICIENT_65_BARS"
    if diagnostic in {"DATED_OFFICIAL_ZERO_VOLUME_OR_HALTED", "PRIOR_KNOWN_SYMBOL_D_ACTIVITY_UNCONFIRMED",
                      "D_READER_BAR_NONTRADEABLE", "DATED_OFFICIAL_BAR_INVALID"}:
        return "SUSPENDED_OR_OUT_OF_UNIVERSE"
    return "MISSING_CONTEXT"


def export_row(day, code, row, supplement, current, quote, membership, tiers, decision_source, sessions,
               exposure, no_context, saved_g1_line_parity):
    row = row or {}
    observed_st = a31.special_treatment(quote.get("name")) if quote else None
    raw = {name: g.finite(row.get(name)) for name in RAW_COLS}
    strict = row.get("strict_g1_failure")
    status = row.get("prediction_status", "NO_FROZEN_STATE")
    score_source, shadow_stage = None, None
    shadow_valid = supplement is not None and supplement[0]["status"] == "READY" and supplement[1][0] is not None
    if all(value is not None for value in raw.values()):
        score_source = FULL_READY if decision_source != STATE_DEV else "ACT031_FROZEN_D_SAVED"
    elif strict is True and shadow_valid and saved_g1_line_parity:
        ev, (binary, children) = supplement
        raw = dict(zip(RAW_COLS, (binary, *map(float, children))))
        score_source = ST_SHADOW if observed_st is True else SHADOW
        shadow_stage = ev.get("stage")
    elif strict is True:
        no_context = ("STRICT_G1_SHADOW_D_LINE_PARITY_UNAVAILABLE" if not saved_g1_line_parity else
                      "STRICT_G1_SHADOW_MODEL_CONTEXT_UNAVAILABLE")
    elif status == "ACT033A_SAVED_STATE_PROJECTION_ONLY":
        no_context = row.get("_missing_detail") or "ACT033A_EXACT_D_RETAINED_PROJECTION_RAW_HEADS_NOT_RETAINED"
    elif no_context is None:
        no_context = status if status != "READY" else "RAW_SCORE_MISSING"
    score_count = sum(value is not None for value in raw.values())
    require(score_count in (0, len(RAW_COLS)), f"PARTIAL_HEAD_SCORES:{day}:{code}")
    if score_count:
        require(all(0 <= v <= 1 for v in raw.values()) and
                isclose(sum(raw[k] for k in RAW_COLS[1:]), 1., rel_tol=0, abs_tol=1e-8),
                f"INVALID_HEAD_PROBABILITY:{day}:{code}")
    projected = g.finite(row.get("projected_p_s"))
    if strict is True:
        require(row.get("final_state") == "REJECTED_FAKE" and projected is None and row.get("main_tactic") == "invalid_fake",
                f"FROZEN_STRICT_G1_DECISION_DRIFT:{day}:{code}")
    price = a31.positive(row.get("invalidation_price"))
    close_d = a31.positive(current.get("close")) if current else None
    d_price_source = "REBASED_V4_READER_D_ONLY" if close_d is not None else None
    native_close = a31.positive(quote.get("close")) if quote and quote.get("eligible_for_daily_gain_rank") else None
    if close_d is not None and native_close is not None:
        if r34.same_price(close_d, native_close):
            d_price_source = "D_QFQ_ALIGNED_TO_OFFICIAL_TDX_CLOSE"
        else:
            close_d, d_price_source = None, "D_QFQ_OFFICIAL_CLOSE_DIFFERENCE"
    anchor = a31.act028.date8(row.get("invalidation_anchor_date"))
    repair_anchor = a31.act028.date8(row.get("repair_anchor_date"))
    tier, tier_source = early_tier(row, tiers.get(code))
    name = stable_names(quote, row)
    status_source = ST_OFFICIAL if observed_st is not None else ST_MISSING
    return {
        "trade_date": day, "ts_code": code, "prediction_status": status,
        "missing_reason": coarse_missing(score_count, no_context),
        "missing_detail": None if score_count else no_context,
        "s_decision_state": row.get("final_state"), "main_tactic": row.get("main_tactic"),
        "best_candidate_tactic": tied_argmax(raw), "projected_p_s": projected, **raw,
        "stage_code": row.get("stage"), "route_reasons": row.get("route_reasons"), "strict_g1_failure": strict,
        "invalidation_price": price, "cushion_pct": (close_d - price) / close_d if None not in (price, close_d) else None,
        "anchor_age_sessions": repair_distance(sessions, anchor, day), "repair_age": repair_distance(sessions, repair_anchor, day),
        "early_borderline_tier": tier, "early_borderline_tier_source": tier_source,
        "is_st": observed_st, "model_version": MODEL_VERSION, "model_commit": MODEL_COMMIT,
        "train_cutoff_date": TRAIN_CUTOFF, "is_strict_oos_post_cutoff": day > TRAIN_CUTOFF,
        "score_source": score_source, "decision_source": decision_source,
        "st_source": status_source, "membership_source": membership,
        "D_name": name, "d_close_qfq": close_d, "d_close_source": d_price_source,
        "feature_context_end": row.get("feature_context_end") or
                               (supplement[0].get("context_end") if shadow_valid and saved_g1_line_parity else None),
        "invalidation_anchor_date": anchor, "repair_anchor_date": repair_anchor, "shadow_stage_code": shadow_stage,
        "known_previously_exposed": (day, code) in exposure,
    }


def scored_day(day, archive, project, model, *, exact_override=None):
    sources = project.sources
    official, official_ref = sources.quotes[day]
    snapshot = a36i.Basis(project.reader)
    restored, restored_stats = snapshot.prefix(archive, day, f35.earlier(day, a36i.FORECAST_HISTORY))
    quotes, authority = a36i.quotes_for_day(archive, day, snapshot, official)
    saved = saved_signals(project, day)
    frozen_1023 = set(sources.prior.all_signals[day].ts_code) if day == sources.dev[0] else None
    recovery = None
    if frozen_1023 is not None:
        try:
            forecast_prefix, recovery = (exact_override if exact_override is not None else
                                         exact_recovery(day, project, frozen_1023, official))
        except (OSError, a31.ContractError, a36i.act034.qfq.QfqGateError, ValueError) as failure:
            forecast_prefix = restored.iloc[:0]
            recovery = {"status": "CANNOT_CONFIRM_DATED_OWNER_RECIPE", "error": str(failure)}
    else:
        forecast_prefix = restored
    eligible, new_st, restored_admits, admission, current, bars = dated_admissions(
        forecast_prefix, day, official, quotes, authority, saved, frozen_1023)
    if saved is None and frozen_1023 is None:
        audit = sources.checkpoints[day]["audit"]
        require(len(eligible) == audit["eligible_n"], f"ACT036_DAY_ADMISSION_SCOPE_DRIFT:{day}")
    frozen_rows = record_values(saved, ACT031_COLS) if saved is not None else {}
    exact_projection = sources.prior.overlays[day] if frozen_1023 is not None else {}
    line_verified = {code for code, row in frozen_rows.items()
                     if row.get("strict_g1_failure") is True and strict_original_lines(row, current.get(code))}
    prospective = (line_verified | new_st) if saved is not None else (eligible | new_st)
    request = sorted(prospective & current.keys())
    evidence = score_context(forecast_prefix, request, day, model)
    model_rows = dict(frozen_rows)
    modes = {code: STATE_DEV for code in frozen_rows}
    for code, (entry, scores) in evidence.items():
        if code not in model_rows:
            row = daily_state(day, code, current[code], entry, scores, sources.prior.calendar)
            model_rows[code] = row
            modes[code] = ST_SUPPLEMENT if code in new_st else STATE_EXACT_RECIPE if frozen_1023 is not None else STATE_EARLY
    if frozen_1023 is not None:
        mismatch = verify_projected(model_rows, exact_projection)
        drift = {row["ts_code"] for row in mismatch}
        recovery["ACT033A_reprojected_mismatches"] = mismatch
        recovery["ACT033A_reprojected_overlap_n"] = len(model_rows.keys() & exact_projection.keys())
        for code, old in exact_projection.items():
            if code not in model_rows or code in drift:
                model_rows[code] = old | {"prediction_status": "ACT033A_SAVED_STATE_PROJECTION_ONLY",
                    "_missing_detail": ("CANNOT_CONFIRM_ACT033A_RESTORED_STATE_OR_NUMERIC_PARITY" if code in drift else
                                        "ACT033A_EXACT_D_RETAINED_PROJECTION_RAW_HEADS_NOT_RETAINED")}
                modes[code] = "ACT033A_FROZEN_D_GROUP_PROJECTION"
    elif saved is None:
        frozen_state_counts = Counter(row["final_state"] for code, row in model_rows.items() if code in eligible)
        expected = sources.checkpoints[day]["audit"]["final_state"]
        require(dict(frozen_state_counts) == expected, f"ACT036_FROZEN_STATE_COUNT_DRIFT:{day}")
    archive_d = current_rows(archive, day)
    scope = historical_membership(archive, archive_d, official, set(model_rows) | eligible, day)
    tiers = audited_tiers(sources.checkpoints[day])
    require(set(tiers) <= set(scope), f"KNOWN_EXTENSION_UNIVERSE_DRIFT:{day}")
    rows = []
    for code, member in scope.items():
        prior = model_rows.get(code)
        d_row = current.get(code)
        official_quote = official.get(code)
        known_st = a31.special_treatment(official_quote.get("name")) if official_quote else None
        missing = null_reason(code, member, d_row, official, eligible, known_st, prior, bars)
        rows.append(export_row(day, code, prior, evidence.get(code), d_row, official_quote, member, tiers,
                               modes.get(code), sources.prior.calendar, project.prior_exposure, missing,
                               code not in frozen_rows or code in line_verified))
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    require_table(table, [day])
    extras = {
        "membership": dict(Counter(row["membership_source"] for row in rows)),
        "score_source": dict(Counter(row["score_source"] or "NO_SCORE" for row in rows)),
        "missing_reason": dict(Counter(row["missing_reason"] for row in rows)),
        "state": dict(Counter(row["s_decision_state"] or "NO_STATE" for row in rows)),
        "tier": dict(Counter(row["early_borderline_tier"] or "NO_BORDERLINE_TIER" for row in rows)),
        "st": {k: sum(("UNKNOWN" if item["is_st"] is None else "TRUE" if item["is_st"] else "FALSE") == k
                      for item in rows) for k in ("UNKNOWN", "TRUE", "FALSE")},
    }
    return table, {"rows": len(rows), "restored_model_admissible_n": len(restored_admits),
                   "frozen_admission_n": len(eligible), "dated_ST_supplement_n": len(new_st),
                   "head_feature_requests_n": len(request),
                   "head_feature_ready_n": sum(pair[0]["status"] == "READY" for pair in evidence.values()),
                   "copied_ACT031_rows": len(frozen_rows), "strict_saved_shadow_line_match_n": len(line_verified),
                   "strict_saved_shadow_line_mismatch_n": sum(row.get("strict_g1_failure") is True for row in frozen_rows.values())
                                                     - len(line_verified),
                   "D_quote_evidence": authority, "D_official": official_ref, "actual_model_source": modes and dict(Counter(modes.values())),
                   "D_basis_restore": restored_stats, "1023_dated_exact_recovery": recovery,
                   "ACT031_input": project.plans.get(day), "coverage": extras}


def require_table(table, expected_days):
    require(table.schema.equals(SCHEMA, check_metadata=True), "PARQUET_LOGICAL_SCHEMA_DRIFT")
    visible = table.select(["trade_date", "ts_code", "s_decision_state", "strict_g1_failure", "projected_p_s",
                            "best_candidate_tactic", "score_source", "missing_reason", "early_borderline_tier", *RAW_COLS]).to_pandas()
    require(set(visible.trade_date) == set(expected_days)
            and not visible.duplicated(["trade_date", "ts_code"]).any()
            and visible.ts_code.str.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)").all(),
            "PARQUET_DATE_SCOPE_OR_DUPLICATE_KEY")
    ordered = visible[["trade_date", "ts_code"]].sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    require(visible[["trade_date", "ts_code"]].reset_index(drop=True).equals(ordered),
            "PARQUET_KEY_ORDER_DRIFT")
    allowed = {"CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE"}
    strict = visible.strict_g1_failure.eq(True)
    no_raw, all_raw = visible[list(RAW_COLS)].isna().all(axis=1), visible[list(RAW_COLS)].notna().all(axis=1)
    require(set(visible.s_decision_state.dropna()) <= allowed and (no_raw | all_raw).all()
            and set(visible.missing_reason) <= MISSING_ENUM and visible.missing_reason.eq("READY").eq(all_raw).all()
            and set(visible.early_borderline_tier) <= {EXT1, EXT3, PURE, HIGH, NONE}
            and visible.loc[strict, "projected_p_s"].isna().all()
            and visible.loc[strict, "s_decision_state"].eq("REJECTED_FAKE").all()
            and visible.loc[all_raw, "best_candidate_tactic"].isin(TACTICS).all()
            and visible.loc[no_raw, "best_candidate_tactic"].isna().all(),
            "PARQUET_STATE_OR_PROBABILITY_CONTRACT_DRIFT")


def parquet_bytes(table):
    stream = pa.BufferOutputStream()
    pq.write_table(table, stream, compression="zstd", compression_level=8, use_dictionary=True,
                   write_statistics=True, row_group_size=16_384)
    return stream.getvalue().to_pybytes()


def write_checked_parquet(path, table, dates, payload=None):
    raw = parquet_bytes(table) if payload is None else payload
    require(0 < len(raw) <= MAX_BYTES, f"SHARD_BYTE_CAP:{path.name}:{len(raw)}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.pending")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        observed = pq.read_table(temporary)
        require_table(observed, dates)
        require(observed.equals(table, check_metadata=True), f"SHARD_WRITE_READ_CONTENT_DRIFT:{path.name}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return a31.ref(path) | {"rows": table.num_rows, "bytes": path.stat().st_size, "dates": list(dates)}


_WORKER = None


def initialize_export(reader, identity):
    from threadpoolctl import threadpool_limits

    global _WORKER
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    _WORKER = reader, a36i.load_model(identity), threadpool_limits(limits=1)


def day_project(project, day):
    prior = project.sources.prior
    selected = SimpleNamespace(
        all_signals={day: prior.all_signals[day]} if day in prior.all_signals else {},
        inputs={"days": {day: prior.inputs["days"].get(day, {})}},
        overlays={day: prior.overlays.get(day, {})}, calendar=prior.calendar,
    )
    sources = SimpleNamespace(quotes={day: project.sources.quotes[day]}, dev=project.sources.dev,
                              checkpoints={day: project.sources.checkpoints[day]}, prior=selected)
    plans = {day: project.plans[day]} if day in project.plans else {}
    return sources, plans, project.frozen_model, project.model_ref, project.prior_exposure


def checkpoint_task(frame, work, out, start_sha):
    reader, model, _ = _WORKER
    for day, meta in work:
        sources, plans, locked, model_ref, exposure = meta
        project = Project(sources, reader, plans, locked, model_ref, exposure)
        t = perf_counter()
        table, details = scored_day(day, frame, project, model)
        write = perf_counter()
        reference = write_checked_parquet(out / f"{day}.parquet", table, [day])
        payload = {"schema": SCHEMA_ID, "trade_date": day, "start_sha": start_sha, "file": reference,
                   "audit": details, "D_only_seconds": write - t, "parquet_seconds": perf_counter() - write,
                   "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "outcomes_opened": False, **a31.FLAGS}
        a31.json_atomic(out / f"{day}.json", payload)
        print(f"D_PREDICTIONS_CHECKPOINT {day} rows={table.num_rows} raw_ready={details['head_feature_ready_n']} "
              f"seconds={payload['D_only_seconds']:.1f} {reference['sha256'][:10]}", flush=True)


def read_daily(day, out, start_sha):
    ref = a31.ref(out / f"{day}.json")
    value = a31.read_ref(ref)
    require(value["schema"] == SCHEMA_ID and value["trade_date"] == day and value["start_sha"] == start_sha
            and value["outcomes_opened"] is False, f"DAY_CHECKPOINT_IDENTITY_DRIFT:{day}")
    item = value["file"]
    require(item["dates"] == [day] and Path(item["path"]) == out / f"{day}.parquet"
            and item["rows"] == value["audit"]["rows"], f"DAY_FILE_SCOPE_DRIFT:{day}")
    a33.checked(item)
    require(Path(item["path"]).stat().st_size == item["bytes"], f"DAY_FILE_BYTE_DRIFT:{day}")
    return value, ref


def archive_scope(project, days):
    start, last = f35.earlier(min(days), a36i.FORECAST_HISTORY), max(days)
    p = a36i.read_history(project.reader, start, last)
    cnt = p.ts_code.nunique()
    require(cnt > 0 and len(p) <= cnt * 345, "V4_ARCHIVE_PROJECTED_SCOPE_TOO_LARGE")
    return p, {"bounds": [start, last], "rows": len(p), "symbols": cnt,
               "projected_read_memory_bytes": int(p.memory_usage(deep=True, index=True).sum())}


def batches(project, pending, archive):
    for offset in range(0, len(pending), 2):
        dates = pending[offset:offset + 2]
        span = archive.loc[archive.trade_date.between(f35.earlier(dates[0], a36i.FORECAST_HISTORY), dates[-1])]
        yield span, [(d, day_project(project, d)) for d in dates]


def run_days(project, run_open, workers):
    work = OUTPUT / "daily_predictions"
    work.mkdir(exist_ok=True)
    dates = project.sources.days
    for day in dates:
        if (work / f"{day}.json").exists():
            read_daily(day, work, run_open["sha256"])
    pending = [d for d in dates if not (work / f"{d}.json").exists()]
    read_audit = {}
    if pending:
        archive, read_audit = archive_scope(project, pending)
        init = (a36.worker_archive(project.reader), project.frozen_model)
        if workers == 1:
            initialize_export(*init)
            for block in batches(project, pending, archive):
                checkpoint_task(*block, work, run_open["sha256"])
        else:
            with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"), initializer=initialize_export,
                                     initargs=init) as executor:
                todo = iter(batches(project, pending, archive))
                queue = {executor.submit(checkpoint_task, *part, work, run_open["sha256"])
                         for part in (next(todo, None) for _ in range(workers)) if part is not None}
                while queue:
                    done, queue = wait(queue, return_when=FIRST_COMPLETED)
                    for item in done:
                        item.result()
                    for _ in done:
                        part = next(todo, None)
                        if part:
                            queue.add(executor.submit(checkpoint_task, *part, work, run_open["sha256"]))
    return {day: read_daily(day, work, run_open["sha256"]) for day in dates}, read_audit


def monthly_shards(daily):
    months = defaultdict(list)
    for day, (record, _) in daily.items():
        months[day[:6]].append((day, record["file"]))
    files = []
    for month, parts in sorted(months.items()):
        dates = [day for day, _ in parts]
        table = pa.concat_tables([pq.read_table(reference["path"]) for _, reference in parts])
        require_table(table, dates)
        raw = parquet_bytes(table)
        stem = f"SV3_FROZEN_OOS_EXPORT_{month}"
        if len(raw) <= MAX_BYTES:
            files.append(write_checked_parquet(OUTPUT / f"{stem}.parquet", table, dates, raw))
        else:
            midpoint = len(parts) // 2
            first_n = sum(reference["rows"] for _, reference in parts[:midpoint])
            for i, (batch, keys) in enumerate(((table.slice(0, first_n), dates[:midpoint]),
                                                (table.slice(first_n), dates[midpoint:])), 1):
                require(keys, f"MONTH_SHARD_UNSPLITTABLE:{month}")
                files.append(write_checked_parquet(OUTPUT / f"{stem}_H{i}.parquet", batch, keys))
    return files


def bind_plan(project, workers, resume_metadata_detach=False):
    src = project.sources
    files = (Path(__file__).resolve(), Path(a31.__file__).resolve(), Path(a31.prior.__file__).resolve(),
             Path(a31.act025.__file__).resolve(), Path(a31.act028.__file__).resolve(), Path(a36i.__file__).resolve())
    proposed = {
        "schema": SCHEMA_ID, "phase": "D_EXPORT_INPUTS_FROZEN", "signal_dates": src.days,
        "oot_dates": src.oot, "dev_dates": src.dev, "ACT036_D_selection_seal": a37.ACT036_SEAL,
        "ACT031_D_full_score_files": project.plans, "ACT036_D_checkpoints": src.checkpoint_refs,
        "ACT031_model_plan": project.model_ref, "frozen_model": project.frozen_model, "model_version": MODEL_VERSION,
        "model_commit": MODEL_COMMIT, "model_commit_full": MODEL_COMMIT_FULL, "train_cutoff": TRAIN_CUTOFF,
        "D_market_reader": project.reader.identity, "proof_code": [a31.ref(path) for path in files],
        "policy": POLICY, "workers": workers, "fit_count": 0, "tuning_count": 0, "outcomes_opened": False, **a31.FLAGS,
    }
    if not resume_metadata_detach:
        require(not (OUTPUT / "EXPORT_STOP_RECEIPT.json").exists(), "CONTROLLED_RUN_REQUIRES_METADATA_RESUME")
        return a31.json_atomic(OUTPUT / START, proposed), None, None
    return resume_plan(proposed)


def resume_plan(proposed, *, write=True):
    stop = a31.read_ref(STOP_REF)
    original = a31.read_ref(stop["export_start"])
    expected = proposed | {"proof_code": [proposed["proof_code"][0] | {"sha256": ORIGINAL_CODE["sha256"]},
                                           *proposed["proof_code"][1:]]}
    a33.checked(ORIGINAL_CODE)
    require(original == expected and stop["original_code_sha256"] == ORIGINAL_CODE["sha256"]
            and tuple(stop["pending_dates"]) == PENDING_RECOVERY_DATES and stop["outcomes_opened"] is False
            and stop["all_named_run_processes_exited"] is True
            and stop["attr_neutrality_canary"]["exact_matrix_evidence_parity"] is True,
            "METADATA_RESUME_ORIGINAL_PLAN_OR_STOP_RECEIPT_DRIFT")
    require(set(stop["verified_daily_receipts"]) == set(original["signal_dates"]) - set(PENDING_RECOVERY_DATES),
            "METADATA_RESUME_PRIOR_DAYS_DRIFT")
    directory = OUTPUT / "daily_predictions"
    for day, ref in stop["verified_daily_receipts"].items():
        require(read_daily(day, directory, stop["export_start"]["sha256"])[1] == ref,
                f"METADATA_RESUME_PRIOR_CHECKPOINT_DRIFT:{day}")
    for day in PENDING_RECOVERY_DATES:
        if (directory / f"{day}.json").exists():
            read_daily(day, directory, stop["export_start"]["sha256"])
    detail = {"schema": SCHEMA_ID, "phase": "CONTINUE_SAME_EXPORT_AFTER_METADATA_DETACH",
              "export_start": stop["export_start"], "controlled_stop": STOP_REF,
              "original_exporter_bytes": ORIGINAL_CODE, "continuation_source": proposed["proof_code"][0],
              "prior_verified_daily_receipts": stop["verified_daily_receipts"],
              "only_dates_authorized_to_continue": list(PENDING_RECOVERY_DATES),
              "canary": stop["attr_neutrality_canary"], "prior_elapsed_real_seconds": stop["elapsed_real_seconds"],
              "outcomes_opened": False, "fit_count": 0, "tuning_count": 0, **a31.FLAGS}
    resumed = a31.json_atomic(OUTPUT / "EXPORT_CONTINUATION.json", detail) if write else detail
    return stop["export_start"], resumed, stop


def export(workers, resume_metadata_detach=False):
    start = perf_counter()
    project = load_project()
    opened, continuation, stopped = bind_plan(project, workers, resume_metadata_detach)
    defined = perf_counter()
    daily, archive = run_days(project, opened, workers)
    computed = perf_counter()
    parts = monthly_shards(daily)
    require(sorted(day for part in parts for day in part["dates"]) == project.sources.days
            and len({part["path"] for part in parts}) == len(parts)
            and sum(part["rows"] for part in parts) == sum(day["file"]["rows"] for day, _ in daily.values()),
            "MONTH_SHARD_UNION_PARITY")
    finish = perf_counter()
    return a31.json_atomic(OUTPUT / SEAL, {
        "schema": SCHEMA_ID, "phase": "PREDICTIONS_SEALED", "signal_dates": project.sources.days,
        "oot_dates": project.sources.oot, "dev_dates": project.sources.dev, "train_cutoff_date": TRAIN_CUTOFF,
        "files": parts, "rows": sum(part["rows"] for part in parts),
        "schema_fields": [{"name": col.name, "arrow_type": str(col.type), "nullable": col.nullable} for col in SCHEMA],
        "export_plan": opened, "execution_continuation": continuation,
        "daily_receipts": {d: ref for d, (_, ref) in daily.items()},
        "daily_coverage": {d: item["audit"] for d, (item, _) in daily.items()},
        "frozen_model": project.frozen_model, "model_version": MODEL_VERSION, "model_commit": MODEL_COMMIT,
        "model_commit_full": MODEL_COMMIT_FULL,
        "prior_exposure": [{"trade_date": d, "ts_code": c} for d, c in sorted(project.prior_exposure)],
        "outcomes_opened": False, "fit_count": 0, "tuning_count": 0, "historical_pit": "CANNOT_CONFIRM",
        "runtime": {"stage_input_seconds": defined - start, "D_scoring_and_checkpoints_seconds": computed - defined,
                    "month_shards_seconds": finish - computed, "wall_seconds_before_seal": finish - start,
                    "original_process_elapsed_real_seconds": stopped["elapsed_real_seconds"] if stopped else None,
                    "combined_original_and_continuation_seconds_before_seal": (
                        stopped["elapsed_real_seconds"] + finish - start if stopped else None),
                    "workers": workers, "worker_blas": 1, "worker_arrow_cpu": 1, "hardware_cpu_cores": os.cpu_count(),
                    "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "largest_worker_peak_rss_bytes": max(item["peak_rss_bytes"] for item, _ in daily.values()),
                    "V4_scope_read": archive, "durable_pred_shard_bytes": sum(item["bytes"] for item in parts),
                    "physical_io_bytes": "CANNOT_CONFIRM"},
        **a31.FLAGS,
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", required=True, action="store_true")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--resume-metadata-detach", action="store_true")
    args = parser.parse_args(argv)
    require(1 <= args.workers <= 12, "WORKER_LIMIT")
    pa.set_cpu_count(min(8, os.cpu_count() or 1))
    lock_root = OUTPUT / "writer_lock"
    with a31.exclusive_run(lock_root):
        require(not (OUTPUT / SEAL).exists(), "EXPORT_ALREADY_SEALED")
        result = export(args.workers, args.resume_metadata_detach)
    print("PREDICTIONS_SEALED", result["sha256"], flush=True)


if __name__ == "__main__":
    main()
