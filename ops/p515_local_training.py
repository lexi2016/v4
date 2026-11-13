"""Build the bounded P5.15 development projection and admit only certified targets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import file_digest, sha256
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
import json
import platform
import sys
from tempfile import gettempdir

import numpy as np
import pandas as pd


KEY = ["stable_security_id", "observation_date", "event_id"]
SOURCE_KEY = ["ts_code", "D", "canonical_event_id"]
PHASES = [
    "BUILDUP_STRUCTURE_CANDIDATE", "IGNITION", "ADVANCE", "TREND_CONSOLIDATION",
    "HIGH_LEVEL_RISK", "DISTRIBUTION_RISK_CANDIDATE", "STRUCTURE_FAILURE", "UNKNOWN",
]
OUTCOMES = ["SUCCESS", "FAILURE", "NOT_STARTED", "UNKNOWN", "CENSORED"]
LABEL_COLUMNS = KEY + [
    "root_anchor_id", "wave_id", "phase_label", "pullback_label", "label_source",
    "label_maturity_date", "label_confidence", "PIT_status", "UNKNOWN_reason",
]
META = SOURCE_KEY + [
    "stable_security_id", "query_id", "original_opportunity_type", "PIT_grade",
    "root_original_unique_anchor_identity", "native_reference_K_date", "effective_event_anchor_date",
    "anchor_date", "buildup_start_date", "f04_washout_day_k",
]
D_ONLY = SOURCE_KEY + [
    "feature_max_date", "true_wave_sequence", "root_anchor_status", "industry_PIT_status",
    "industry_snapshot_NONPIT", "effective_event_age_bars", "original_pb_depth_pct",
    "D_over_prev_volume", "D_over_prior20_mean_volume", "D_over_effective_volume",
    "attack_mean_volume", "pullback_mean_volume", "pullback_over_attack_volume",
    "history_n", "history_max_available", "history_max_obs_end",
]
RAW = [
    "query_id", "ts_code", "stable_security_id", "D", "trade_date", "open", "high",
    "low", "close", "volume", "amount", "PIT_status", "price_basis",
]
HISTORY = [
    "ts_code", "query_D", "query_event_id", "canonical_event_id", "raw_anchor_date",
    "obs_end_date", "available_at_t5",
]
LANDMARK = [
    "ts_code", "D", "query_event", "history_event", "anchor_date", "history_obs_end",
    "history_available_at_t5", "landmark_date", "feature_path_max_date",
    "dd_close_pct", "prefix_min_volume_to_anchor",
]
MARKET = ("market_relative_return_1d", "market_breadth_1d")
PRICE = ("bar_return_pct", "bar_range_pct", "volume_over_prior20_mean", "amount_over_prior20_mean")
STRUCTURE = (
    "root_body_position", "attack_gain_pct", "attack_duration_sessions",
    "true_pullback_age_sessions", "current_true_pullback_depth_pct", "pullback_over_attack_volume",
    "distance_to_root_low_pct", "close_reclaimed_root_low",
)
PERSONALITY = (
    "same_role_history_event_n", "own_depth_median_shrunk_pct", "own_duration_median_shrunk",
    "own_volume_ratio_shrunk", "own_support_failure_rate_shrunk",
)
SECTOR = tuple(
    f"sector_loo_{field}_{window}d"
    for field in ("return", "breadth", "amount_change") for window in (1, 5, 20)
) + ("sector_loo_relative_return_5d", "leader_relative_return_5d", "target_minus_leader_return_5d")

# These are experiment inputs from a separately certified bundle. The current proxy
# projection deliberately uses different names and therefore cannot be fed here.
EXPERIMENTS = {
    "A_PRICE": ("A", "phase_label", PRICE, PHASES[:-1]),
    "A_STRUCTURE": ("A", "phase_label", PRICE + STRUCTURE, PHASES[:-1]),
    "B_DEPTH_PRICE": ("B", "terminal_pullback_depth_pct", PRICE, None),
    "B_DEPTH_STRUCTURE": ("B", "terminal_pullback_depth_pct", PRICE + STRUCTURE, None),
    "B_TIME_PRICE": ("B", "sessions_to_pullback_outcome", PRICE, None),
    "B_TIME_STRUCTURE": ("B", "sessions_to_pullback_outcome", PRICE + STRUCTURE, None),
    "B_SUPPORT_PRICE": ("B", "support_label", PRICE, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "B_SUPPORT_STRUCTURE": ("B", "support_label", PRICE + STRUCTURE, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "C_MARKET": ("C", "support_label", MARKET, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "C_MARKET_SECTOR": ("C", "support_label", MARKET + SECTOR, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "C_MARKET_PERSONALITY": ("C", "support_label", MARKET + PERSONALITY, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "C_ALL": ("C", "support_label", MARKET + SECTOR + PERSONALITY, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "D_MARKET": ("D", "support_label", MARKET, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
    "D_SECTOR": ("D", "support_label", MARKET + SECTOR, ["SUPPORT_HELD", "STRUCTURE_FAILURE"]),
}
LEDGER = [
    "model", "variant", "target", "status", "block_reason", "attempt", "last_stage",
    "estimator_fit_count", "estimator_fit_completed_count",
    "preprocessing_fit_count", "calibration_fit_count", "prediction_calls",
    "train_rows", "train_stocks", "train_events", "train_dates", "dev_rows", "dev_stocks",
    "dev_events", "dev_dates", "feature_count", "label_source", "source_sha256",
    "data_sha256", "weight_sha256", "environment", "reload_max_abs_error",
    "prefit_sha256", "fit_approval_sha256",
]
FLAGS = dict(RESEARCH_ONLY=True, EXPERIMENTAL_FIT_ALLOWED=True, PRODUCTION_ALLOWED=False,
             BUY_GATE_UPDATED=False, ORDERS_SENT=False)


def sha(path: Path) -> str:
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def record_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read_csv(path, columns):
    return pd.read_csv(path, usecols=columns)


def stats(df):
    return {
        "rows": len(df), "stocks": df.stable_security_id.nunique(),
        "events": len(df[["stable_security_id", "event_id"]].drop_duplicates()),
        "dates": df.observation_date.nunique(),
        "first": int(df.observation_date.min()) if len(df) else None,
        "last": int(df.observation_date.max()) if len(df) else None,
    }


def bind_sources(research, audit):
    supp = research / "p5148_research_supplement_20261113"
    features = research / "p5148_conf_failure_personality_20261113"
    r1 = research / "claude_kb_role_stage_20261111/run_20261112_000900/data"
    historical = research / "p5_14_6_codex_event_personalization_20261110/run_20261110_092832"
    files = {
        "conf": (supp / "ORIGINAL_CONF_586.csv", supp / "SHA256SUMS.txt"),
        "raw": (supp / "DAILY_BARS_455.parquet", supp / "SHA256SUMS.txt"),
        "worst": (supp / "WORST_LOSS_20_CASES.csv", supp / "SHA256SUMS.txt"),
        "pb2": (supp / "PB2_36_CASES.csv", supp / "SHA256SUMS.txt"),
        "chart_current": (supp / "CHART_INDEX.csv", supp / "SHA256SUMS.txt"),
        "chart_historical": (supp / "HISTORICAL_PAIR_CASES.csv", supp / "SHA256SUMS.txt"),
        "d_only": (features / "FEATURES_D_ONLY.csv", features / "SHA256SUMS.txt"),
        "history": (features / "HISTORY_EVENT_EVIDENCE.csv", features / "SHA256SUMS.txt"),
        "landmarks": (features / "SAMEAGE_HISTORICAL_EVIDENCE.csv", features / "SHA256SUMS.txt"),
        "r0": (audit / "original/P5_15_PHASE1_CURRICULUM_R0.zip", audit / "SHA256SUMS.txt"),
        "r0_mapping": (audit / "KNOWLEDGE_TO_CODE_MAPPING.csv", audit / "SHA256SUMS.txt"),
        "r0_models": (audit / "MODEL_AND_FIELD_LINEAGE.csv", audit / "SHA256SUMS.txt"),
        "r0_receipt": (audit / "INTAKE_RECEIPT.json", audit / "SHA256SUMS.txt"),
        "observed_roles": (r1 / "LABEL_SOURCE_OBSERVED_ROLE_PROVENANCE.csv",
                           "8c31c2dfa22663deaba6bb9254aaa883633408b7bc23300950d3b12462770208"),
        "ai_roles": (research / "kb_indicator_training_20261112/ai_research_round/AI_ROLE_LABELS_244.csv",
                     "2535decaa9625073af93d1ecf7af8a68aa8241cd3ce96fb483cf1595b99d2abe"),
        "prior_forward": (historical / "event/forward/FORWARD_PULLBACK_ADJUDICATION.parquet", None),
        "prior_report": (historical / "MASTER_REPORT_CN.md", None),
        "prior_contract": (historical / "ACTUAL_MODEL_FEATURE_CONTRACT.json", None),
    }
    prior_manifest_path = historical / "SHA256_MANIFEST.csv"
    prior_expected = read_csv(prior_manifest_path, ["path", "sha256", "bytes"]).set_index("path")
    for name, basename in (("prior_report", "MASTER_REPORT_CN.md"), ("prior_contract", "ACTUAL_MODEL_FEATURE_CONTRACT.json")):
        files[name] = (historical / basename, prior_expected.loc[basename, "sha256"])
    forward_manifest_path = historical / "event/FORWARD_INCREMENT_MANIFEST.json"
    forward_entries = {row["path"]: row for row in json.loads(forward_manifest_path.read_text())["files"]}
    forward_expected = forward_entries["forward/FORWARD_PULLBACK_ADJUDICATION.parquet"]
    forward_receipt = forward_entries["forward/FORWARD_COVERAGE_RECEIPT.json"]
    files["prior_forward_receipt"] = (historical / "event" / forward_receipt["path"], forward_receipt["sha256"])
    manifests = {}
    binding = {}
    for name, (path, binding_source) in files.items():
        if isinstance(binding_source, Path):
            if binding_source not in manifests:
                manifests[binding_source] = dict(
                    (row.split(None, 1)[1].lstrip("*"), row.split(None, 1)[0])
                    for row in binding_source.read_text().splitlines() if row.strip()
                )
            expected = manifests[binding_source][str(path.relative_to(binding_source.parent))]
        else:
            expected = binding_source
        # Read the prior Parquet footer only. Its rows may contain protected outcomes.
        digest = sha(path) if name != "prior_forward" else None
        if expected is not None and digest != expected:
            raise ValueError(f"Frozen source SHA mismatch: {path}")
        binding[name] = {"path": str(path), "sha256": digest, "expected_sha256": expected}
    if files["prior_forward"][0].stat().st_size != forward_expected["bytes"]:
        raise ValueError("Historical forward artifact size mismatches its frozen manifest")
    binding["prior_forward"].update(
        expected_sha256=forward_expected["sha256"], declared_bytes=forward_expected["bytes"],
        binding_manifest=str(forward_manifest_path), verification="FOOTER_AND_SIZE_ONLY_NOT_REHASHED",
    )
    for name in ("prior_report", "prior_contract"):
        binding[name]["binding_manifest"] = str(prior_manifest_path)
    binding["prior_forward_receipt"]["binding_manifest"] = str(forward_manifest_path)
    return {name: path for name, (path, _) in files.items()}, binding


def source_cohort(paths):
    meta = read_csv(paths["conf"], META)
    d_only = read_csv(paths["d_only"], D_ONLY)
    if len(meta) != 586 or len(d_only) != 586 or not meta.query_id.is_unique:
        raise ValueError("Original CONF and D-only cohorts must each have 586 unique observations")
    merged = meta.merge(d_only, on=SOURCE_KEY, validate="one_to_one")
    if len(merged) != len(meta) or not merged.feature_max_date.eq(merged.D).all():
        raise ValueError("D-only join or snapshot cutoff mismatch")
    for field in ["anchor_date", "buildup_start_date", "native_reference_K_date", "effective_event_anchor_date"]:
        if not (merged[field].isna() | merged[field].le(merged.D)).all():
            raise ValueError(f"Future reference date: {field}")
    if not merged.f04_washout_day_k.eq(merged.f04_washout_day_k.astype(int)).all():
        raise ValueError("Invalid observation index")
    if not merged.PIT_grade.eq("CURRENT_VERSION_RETROSPECTIVE_REPLAY_NONPIT").all():
        raise ValueError("Original cohort PIT status changed; re-audit inputs")
    merged = merged.rename(columns={"D": "observation_date", "canonical_event_id": "event_id"})
    merged = merged.sort_values(["observation_date", "stable_security_id", "event_id"]).reset_index(drop=True)
    summary = stats(merged)
    if [summary[x] for x in ("rows", "stocks", "events", "dates")] != [586, 455, 557, 38]:
        raise ValueError("Original population counts changed")
    pb2 = set(read_csv(paths["pb2"], ["query_id"]).query_id)
    worst = set(read_csv(paths["worst"], ["query_id"]).query_id)
    charts = read_csv(paths["chart_current"], ["query_id", "D", "bars_max_date"])
    historical_charts = read_csv(paths["chart_historical"], ["pair_id", "event_id", "bars_max_date", "chart_cutoff"])
    if (len(pb2), len(worst), len(charts), len(historical_charts)) != (36, 20, 58, 6):
        raise ValueError("Frozen case counts changed")
    if not charts.bars_max_date.le(charts.D).all() or not historical_charts.bars_max_date.le(historical_charts.chart_cutoff).all():
        raise ValueError("Chart cutoff exceeded")
    if set(merged.loc[merged.original_opportunity_type.str.startswith("PB2"), "query_id"]) != pb2:
        raise ValueError("Frozen PB2 cases do not match original observations")
    summary.update(
        pb2=len(pb2), pb3=int(merged.original_opportunity_type.str.startswith("PB3").sum()),
        worst=len(worst), pb2_worst_overlap=len(pb2 & worst), current_charts=len(charts),
        historical_charts=len(historical_charts),
    )
    if summary["pb3"] != 59 or not (pb2 | worst | set(charts.query_id)).issubset(set(merged.query_id)):
        raise ValueError("Frozen case identity mismatch")
    merged["reviewed_pb2_case"] = merged.query_id.isin(pb2)
    merged["historical_worst_case_membership"] = merged.query_id.isin(worst)
    merged["published_chart_available"] = merged.query_id.isin(charts.query_id)
    return merged, summary


def ratio(value, denominator):
    if pd.isna(value) or pd.isna(denominator) or denominator <= 0:
        return None
    return float(value / denominator)


def raw_features(prefix, effective_date):
    observed = prefix.iloc[-1]
    prior = prefix.iloc[:-1]
    recent = prior.tail(20)
    complete_prior = len(recent) == 20 and recent[["volume", "amount"]].notna().all().all()
    if pd.isna(observed.close):
        return {}
    daily_range = observed.high - observed.low
    previous_close = prior.close.iloc[-1] if len(prior) else None
    features = {
        "raw_d_bar_open_close_pct": 100 * (observed.close / observed.open - 1),
        "raw_d_bar_range_pct": 100 * daily_range / observed.open,
        "raw_d_close_location_in_bar": ratio(observed.close - observed.low, daily_range),
        "raw_d_upper_wick_fraction": ratio(observed.high - max(observed.open, observed.close), daily_range),
        "raw_d_lower_wick_fraction": ratio(min(observed.open, observed.close) - observed.low, daily_range),
        "raw_d_close_vs_previous_observed_close": ratio(observed.close, previous_close),
        "raw_d_volume_over_prior20_mean": ratio(observed.volume, recent.volume.mean()) if complete_prior else None,
        "raw_d_amount_over_prior20_mean": ratio(observed.amount, recent.amount.mean()) if complete_prior else None,
        "raw_d_volume_over_prior20_median": ratio(observed.volume, recent.volume.median()) if complete_prior else None,
        "raw_d_close_vs_prior20_high": ratio(observed.close, recent.high.max()) if complete_prior else None,
        "raw_d_close_vs_prior20_low": ratio(observed.close, recent.low.min()) if complete_prior else None,
    }
    eligible = prefix.loc[prefix.trade_date.ge(effective_date)]
    if eligible.empty or eligible.trade_date.iloc[0] != effective_date:
        return features
    if not eligible[["open", "high", "low", "close"]].notna().all().all():
        return features
    anchor = eligible.iloc[0]
    top = eligible.loc[eligible.high.idxmax()]
    close_to_prior_max = eligible.high.cummax().shift()
    # Daily OHLC does not reveal whether an intraday high preceded the low.
    preceding_high_to_later_low = 100 * (1 - eligible.low / close_to_prior_max)
    return features | {
        "raw_effective_anchor_body_position_d": ratio(observed.close - min(anchor.open, anchor.close), abs(anchor.close - anchor.open)),
        "raw_effective_anchor_high_vs_close": ratio(observed.close, anchor.high),
        "raw_effective_anchor_close_to_observed_peak_pct": 100 * (top.high / anchor.close - 1),
        "raw_effective_anchor_to_peak_observed_bars": int(eligible.index.get_loc(top.name)),
        "raw_d_close_drawdown_from_effective_segment_peak_pct": 100 * (1 - observed.close / top.high),
        "raw_effective_segment_max_preceding_high_to_low_drawdown_pct": (
            max(0.0, float(preceding_high_to_later_low.max())) if preceding_high_to_later_low.notna().any() else None
        ),
        "raw_effective_segment_peak_to_d_observed_bars": len(eligible) - 1 - int(eligible.index.get_loc(top.name)),
        "raw_d_close_below_effective_low": int(observed.close < anchor.low),
        "raw_d_low_broke_effective_low_then_closed_above": int(observed.low < anchor.low <= observed.close),
        "raw_d_volume_over_effective_anchor_volume": ratio(observed.volume, anchor.volume),
    }


def raw_projection(path, meta):
    raw = pd.read_parquet(path, columns=RAW)
    data = raw.merge(meta[["query_id", "stable_security_id", "ts_code", "observation_date"]],
                     left_on=["query_id", "stable_security_id", "ts_code", "D"],
                     right_on=["query_id", "stable_security_id", "ts_code", "observation_date"],
                     validate="many_to_one")
    prices = data[["open", "high", "low", "close"]]
    raw_available = prices.notna().all(axis=1)
    if len(data) != len(raw) or set(data.query_id) != set(meta.query_id):
        raise ValueError("Raw prefixes failed source identity join")
    if not data.trade_date.le(data.D).all() or data.duplicated(["query_id", "trade_date"]).any():
        raise ValueError("Future or duplicate raw bar at query level")
    if len(data.loc[data.trade_date.eq(data.D)]) != len(meta):
        raise ValueError("Every query needs exactly one terminal bar identity")
    finite = np.isfinite(data.loc[raw_available, ["open", "high", "low", "close", "volume", "amount"]]).all().all()
    valid = data.loc[raw_available]
    if not (finite and (valid[["open", "high", "low", "close"]] > 0).all().all()
            and (valid.high >= valid[["open", "low", "close"]].max(axis=1)).all()
            and (valid.low <= valid[["open", "high", "close"]].min(axis=1)).all()
            and valid.price_basis.eq("TDX_RAW_UNADJUSTED").all()
            and data.PIT_status.eq("DATE_TRUNCATED_RETROSPECTIVE_NONPIT").all()):
        raise ValueError("Raw prefix price binding or OHLC geometry changed")
    prefix = data.sort_values(["query_id", "trade_date"])
    grouped = prefix.groupby("query_id", sort=False)
    rows = []
    for row in meta.itertuples(index=False):
        bars = grouped.get_group(row.query_id)
        raw_d = raw_features(bars, row.effective_event_anchor_date)
        rows.append({"query_id": row.query_id, "prefix_last_date": int(bars.trade_date.iloc[-1]),
                     "raw_bars": int(bars.close.notna().sum()), **raw_d})
    return pd.DataFrame(rows), {
        "prefix_expanded_rows": len(raw), "raw_ohlc_rows": int(raw_available.sum()),
        "prefix_qualified_pit_rows": 0, "raw_d_quotes": int((raw_available & data.trade_date.eq(data.D)).sum()),
    }


def historical_projection(paths, meta):
    history = read_csv(paths["history"], HISTORY)
    landmarks = read_csv(paths["landmarks"], LANDMARK)
    raw_history_key = ["ts_code", "query_D", "query_event_id", "canonical_event_id", "raw_anchor_date"]
    raw_histories = history.rename(columns={"query_D": "D", "query_event_id": "query_event",
                                           "canonical_event_id": "history_event", "raw_anchor_date": "anchor_date"})
    hkeys = ["ts_code", "D", "query_event", "history_event", "anchor_date"]
    joined = landmarks.merge(raw_histories[hkeys + ["obs_end_date", "available_at_t5"]], on=hkeys, validate="one_to_one")
    query_keys = meta.rename(columns={"observation_date": "D", "event_id": "query_event"})[
        ["ts_code", "D", "query_event", "buildup_start_date", "effective_event_anchor_date"]]
    historical_queries = raw_histories.merge(query_keys, on=hkeys[:3], validate="many_to_one")
    if not (len(historical_queries) == len(history)
            and historical_queries.obs_end_date.lt(historical_queries.buildup_start_date).all()
            and historical_queries.anchor_date.ne(historical_queries.effective_event_anchor_date).all()
            and joined.history_obs_end.eq(joined.obs_end_date).all()
            and joined.history_available_at_t5.eq(joined.available_at_t5).all()):
        raise ValueError("Historical root exclusion or frozen landmark linkage changed")
    if len(history) != 8518 or history.duplicated(raw_history_key).any() or len(joined) != len(landmarks):
        raise ValueError("Historical observed links or raw composite key changed")
    if not (history.available_at_t5.lt(history.query_D).all() and history.obs_end_date.lt(history.query_D).all()
            and history.canonical_event_id.ne(history.query_event_id).all()
            and landmarks.feature_path_max_date.le(landmarks.landmark_date).all()
            and landmarks.landmark_date.le(landmarks.history_obs_end).all()
            and landmarks.history_available_at_t5.lt(landmarks.D).all()):
        raise ValueError("Historical data after observation or same-family evidence")
    key = ["ts_code", "D", "query_event"]
    grouped = landmarks.groupby(key)
    summaries = grouped.agg(
        sameage_observed_raw_links=("history_event", "size"),
        sameage_observed_canon_count=("history_event", "nunique"),
        sameage_history_reference_prefix_dd_close_median_pct=("dd_close_pct", "median"),
        sameage_history_reference_prefix_min_vol_anchor_median=("prefix_min_volume_to_anchor", "median"),
    ).reset_index().rename(columns={"D": "observation_date", "query_event": "event_id"})
    return summaries, {
        "historical_links": len(history), "historical_canonical_ids": history.canonical_event_id.nunique(),
        "historical_distinct_stock_canon_raw_anchor": len(history[["ts_code", "canonical_event_id", "raw_anchor_date"]].drop_duplicates()),
        "sameage_links": len(landmarks), "sameage_queries": len(summaries), "certified_same_role_links": 0,
    }


def prior_label_evidence(paths):
    import pyarrow.parquet as pq

    roles = read_csv(paths["observed_roles"], ["sample_id", "role", "source_statuses"])
    ai = read_csv(paths["ai_roles"], ["sample_id", "role", "ai_state", "historical_PIT_certified"])
    previous = pq.ParquetFile(paths["prior_forward"])
    previous_report = paths["prior_report"].read_text()
    forward_receipt = json.loads(paths["prior_forward_receipt"].read_text())
    required = {"stage_label_source", "path_label_qualification", "historical_source_available_at"}
    if not required.issubset(previous.schema.names) or "静态" not in previous_report:
        raise ValueError("Historical model scope changed")
    model_contract = json.loads(paths["prior_contract"].read_text())
    widths = {k: len(d["columns"]) for k, d in model_contract.items()}
    if widths != {"M0": 23, "M1": 43, "M2_CURRENT_FINE": 45}:
        raise ValueError("Historical model feature identity changed")
    return {
        "source_role_security_days": roles.sample_id.nunique(),
        "source_role_rows": len(roles), "source_role_counts": roles.role.value_counts().to_dict(),
        "source_role_provenance_counts": roles.source_statuses.value_counts().to_dict(),
        "ai_role_security_days": ai.sample_id.nunique(), "ai_role_rows": len(ai),
        "ai_role_states": ai.ai_state.value_counts().to_dict(),
        "ai_historical_pit_certified": int(ai.historical_PIT_certified.eq(True).sum()),
        "p5146_forward_rows_footer_only": previous.metadata.num_rows,
        "p5146_prior_target_source": "P5.14.6 research-rule outcomes and independently scoped frozen T2 targets, separate from P5.15 adjudication",
        "p5146_prior_pit_scope": forward_receipt["sector_cross_tab_scope"],
        "p5146_prior_label_scope": forward_receipt["t2_label_scope"],
        "p5146_feature_widths": widths,
    }


def feature_pool(meta, raw, history):
    features = meta.merge(raw, on="query_id", validate="one_to_one").merge(
        history, on=["ts_code", "observation_date", "event_id"], how="left", validate="one_to_one")
    features["sameage_observed_raw_links"] = features.sameage_observed_raw_links.fillna(0).astype(int)
    features["sameage_observed_canon_count"] = features.sameage_observed_canon_count.fillna(0).astype(int)
    features["certified_same_role_history_event_n"] = pd.NA
    features["history_evidence_level"] = np.where(
        features.sameage_observed_canon_count.lt(3), "LOW_CONFIDENCE", "PARTIAL_NONPIT")
    features = features.rename(columns={
        "f04_washout_day_k": "obs_day_index",
        "effective_event_age_bars": "effective_event_age_observed_bars_proxy",
        "original_pb_depth_pct": "frozen_f05_current_dynamic_ref_depth_pct",
        "D_over_prev_volume": "frozen_d_volume_over_previous_observed_volume",
        "D_over_prior20_mean_volume": "frozen_d_volume_over_prior20_mean",
        "D_over_effective_volume": "frozen_d_volume_over_effective_volume",
        "attack_mean_volume": "frozen_observed_attack_mean_volume_proxy",
        "pullback_mean_volume": "frozen_observed_pullback_mean_volume_proxy",
        "pullback_over_attack_volume": "frozen_observed_pullback_over_attack_volume_proxy",
    })
    # Exact upstream effective sessions were audited on a single case. Computing a
    # row-count from this window would create a third clock, not recover that field.
    features["effective_days_since_event"] = pd.NA
    for field in sorted(set(STRUCTURE + PERSONALITY + SECTOR + MARKET)):
        features[field] = pd.NA
    if not (features.history_max_available.lt(features.observation_date).all()
            and features.history_max_obs_end.lt(features.observation_date).all()):
        raise ValueError("Frozen same-stock history cutoff exceeded")
    for field in ["root_original_unique_anchor_identity", "root_anchor_status", "true_wave_sequence", "industry_PIT_status"]:
        if not features[field].str.startswith("UNKNOWN").all():
            raise ValueError("Source now declares known fields; re-adjudicate before fitting")
    features["pool_level"] = np.where(features.raw_bars.gt(0), "PARTIAL", "UNKNOWN")
    return features


def label_register(features):
    labels = features[KEY].copy()
    labels["root_anchor_id"] = pd.NA
    labels["wave_id"] = pd.NA
    labels["phase_label"] = "UNKNOWN"
    labels["pullback_label"] = "UNKNOWN"
    labels["label_source"] = "NO_ADMITTED_INDEPENDENT_P515_LABEL_SOURCE"
    labels["label_maturity_date"] = pd.NA
    labels["label_confidence"] = "UNKNOWN"
    labels["PIT_status"] = features.PIT_grade
    labels["UNKNOWN_reason"] = (
        "INDEPENDENT_PHASE_AND_PULLBACK_LABELS_MISSING|ROOT_AND_WAVE_UNAUTHENTICATED|HISTORICAL_PIT_UNCERTIFIED"
    )
    labels["pool_level"] = features.pool_level
    labels.loc[labels.pool_level.eq("UNKNOWN"), "UNKNOWN_reason"] += "|RAW_PREFIX_UNAVAILABLE"
    labels["sector_status"] = features.industry_PIT_status
    labels["query_id"] = features.query_id
    return labels[LABEL_COLUMNS + ["pool_level", "sector_status", "query_id"]]


ADJUDICATION_COLUMNS = LABEL_COLUMNS + [
    "label_source_sha256", "feature_evidence_sha256", "feature_available_at",
    "decision_at", "event_start_date", "terminal_pullback_depth_pct", "sessions_to_pullback_outcome", "support_label",
]
CERTIFIED_COLUMNS = list(dict.fromkeys(ADJUDICATION_COLUMNS + list(PRICE + MARKET + STRUCTURE + PERSONALITY + SECTOR)))
MIN_CLASS_TRAIN_EVENTS = 5
MIN_CLASS_DEV_EVENTS = 2
MIN_CONTINUOUS_TRAIN_EVENTS = 20
MIN_CONTINUOUS_DEV_EVENTS = 8


def read_certified_bundle(manifest_path, approved_sha256, synthetic_root=None):
    """A separate same-run authenticated development bundle, with explicit evidence joins."""
    manifest_bytes = manifest_path.read_bytes()
    if sha256(manifest_bytes).hexdigest() != approved_sha256:
        raise ValueError("Development approval digest does not match this manifest")
    manifest = json.loads(manifest_bytes)
    schema = "p515-synthetic-fixture/1" if synthetic_root else "p515-certified-development/1"
    reviewer = manifest.get("independent_reviewer")
    if manifest.get("schema") != schema or not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Missing independently reviewed manifest for the selected data mode")
    if manifest.get("runner_sha256") != sha(Path(__file__)):
        raise ValueError("Development approval bound a different runner")
    cutoff = pd.to_datetime(str(manifest["development_label_cutoff"]), format="%Y%m%d", errors="raise")
    def bundle_file(relative):
        path = (manifest_path.parent / relative).resolve()
        if synthetic_root and not path.is_relative_to(synthetic_root):
            raise ValueError("Synthetic bundle payload escaped the fixture root")
        return path

    dataset = bundle_file(manifest["dataset"])
    dataset_bytes = dataset.read_bytes()
    if sha256(dataset_bytes).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("Certified development dataset SHA mismatch")
    evidence = {"independent_label_adjudication": {}, "historical_pit_and_features": {}}
    for item in manifest["evidence"]:
        path = bundle_file(item["path"])
        binding = evidence[item["kind"]]
        if sha(path) != item["sha256"] or item["sha256"] in binding or not item.get("owner"):
            raise ValueError(f"Evidence SHA, owner or kind mismatch: {path}")
        binding[item["sha256"]] = item["owner"]
    labels = set(evidence["independent_label_adjudication"])
    features = set(evidence["historical_pit_and_features"])
    if not labels or not features or labels & features:
        raise ValueError("Label and historical feature certifications require distinct evidence")
    targets = {spec[1] for spec in EXPERIMENTS.values()}
    required_columns = set(ADJUDICATION_COLUMNS) - targets
    date_columns = {name: "Int64" for name in ("observation_date", "label_maturity_date", "event_start_date")}
    text_columns = {name: "string" for name in required_columns - set(date_columns)}
    data = pd.read_csv(BytesIO(dataset_bytes), usecols=lambda name: name in CERTIFIED_COLUMNS, dtype={**date_columns, **text_columns})
    if not required_columns.issubset(data.columns):
        raise ValueError("Certified inputs require full identity, timing and provenance columns")
    data = data.reindex(columns=CERTIFIED_COLUMNS)
    data["phase_label"] = data.phase_label.astype("string").fillna("UNKNOWN")
    data["support_label"] = data.support_label.astype("string")
    if data.empty or data[KEY].isna().any().any() or data.duplicated(KEY).any():
        raise ValueError("Certified dataset needs unique and nonempty P5.15 sample keys")
    code_pattern = r"SYNTHETIC_[0-9]{6}" if synthetic_root else r"[0-9]{6}\.(SH|SZ|BJ)"
    if not data.stable_security_id.str.fullmatch(code_pattern).all():
        raise ValueError("Sample security keys do not match the selected data mode")
    if not set(data.label_source_sha256.dropna()).issubset(labels) or not set(data.feature_evidence_sha256.dropna()).issubset(features):
        raise ValueError("Evidence hash and certification kind must match")
    if not data.phase_label.isin(PHASES).all() or not data.pullback_label.isin(OUTCOMES).all():
        raise ValueError("Phase and pullback status require explicit contract codes")
    for field in date_columns:
        pd.to_datetime(data[field].dropna().astype(str), format="%Y%m%d", errors="raise")
    numeric_targets = targets - {"phase_label", "support_label"}
    for field in sorted(numeric_targets | set(PRICE + MARKET + STRUCTURE + PERSONALITY + SECTOR)):
        data[field] = pd.to_numeric(data[field], errors="coerce")
    return data.sort_values(KEY).reset_index(drop=True), manifest["dataset_sha256"], int(cutoff.strftime("%Y%m%d")), reviewer.strip()


def certified_rows(data, target, development_label_cutoff):
    authenticated = (
        data.root_anchor_id.notna() & data.wave_id.notna()
        & ~data.root_anchor_id.str.strip().str.upper().isin(["", "UNKNOWN", "NONE", "UNRESOLVED"])
        & ~data.wave_id.str.strip().str.upper().isin(["", "UNKNOWN", "NONE", "UNRESOLVED"])
        & ~data.root_anchor_id.str.upper().str.startswith("UNKNOWN", na=True)
        & ~data.wave_id.str.upper().str.startswith("UNKNOWN", na=True)
        & data.label_confidence.eq("VERIFIED") & data.PIT_status.eq("VERIFIED_DATED")
        & data.label_source.notna() & data.label_source_sha256.notna()
        & data.feature_evidence_sha256.notna()
    )
    known_at = pd.to_datetime(data.feature_available_at, errors="coerce", utc=True, format="ISO8601")
    decision = pd.to_datetime(data.decision_at, errors="coerce", utc=True, format="ISO8601")
    decision_date = pd.to_numeric(decision.dt.tz_convert("Asia/Shanghai").dt.strftime("%Y%m%d"), errors="coerce")
    zone_suffix = r"(?:Z|[+-]\d{2}:\d{2})$"
    explicit_timezone = (
        data.feature_available_at.str.contains(zone_suffix, regex=True, na=False)
        & data.decision_at.str.contains(zone_suffix, regex=True, na=False)
    )
    verified_time = explicit_timezone & known_at.le(decision) & decision_date.eq(data.observation_date)
    mature = pd.to_numeric(data.label_maturity_date, errors="coerce")
    eligible = (
        authenticated & verified_time & mature.between(data.observation_date, development_label_cutoff)
        & data.event_start_date.le(data.observation_date)
    )
    if target == "phase_label":
        return eligible & data.phase_label.isin(PHASES[:-1])
    eligible &= data.pullback_label.isin(["SUCCESS", "FAILURE"])
    if target == "support_label":
        return eligible & data.support_label.isin(["SUPPORT_HELD", "STRUCTURE_FAILURE"])
    numeric = pd.to_numeric(data[target], errors="coerce")
    valid_value = np.isfinite(numeric) & numeric.ge(0)
    if target == "sessions_to_pullback_outcome":
        valid_value &= numeric.mod(1).eq(0)
    return eligible & valid_value


def groups(frame):
    # Stable security IDs are paired with both event lineage keys.
    return set(zip(frame.stable_security_id, frame.root_anchor_id)), set(zip(frame.stable_security_id, frame.event_id))


def time_folds(rows, target, classes):
    # Dev dates are never mixed across folds. A train label must already be known
    # before the first dev D and related event/root keys are purged.
    dates = sorted(rows.observation_date.unique())
    if len(dates) < 5:
        return []
    cut = len(dates) * 3 // 5
    middle = len(dates) * 4 // 5
    folds = []
    for segment in (dates[cut:middle], dates[middle:]):
        dev = rows.loc[rows.observation_date.isin(segment)]
        dev_roots, dev_events = groups(dev)
        train_mask = rows.observation_date.lt(segment[0]) & rows.label_maturity_date.lt(segment[0])
        share_root = pd.MultiIndex.from_frame(rows[["stable_security_id", "root_anchor_id"]]).isin(dev_roots)
        share_event = pd.MultiIndex.from_frame(rows[["stable_security_id", "event_id"]]).isin(dev_events)
        earliest_dev_event = rows.stable_security_id.map(dev.groupby("stable_security_id").event_start_date.min())
        same_stock_interval_overlap = rows.label_maturity_date.ge(earliest_dev_event).fillna(False)
        train = rows.loc[train_mask & ~share_root & ~share_event & ~same_stock_interval_overlap]
        if classes:
            for frame, minimum in ((train, MIN_CLASS_TRAIN_EVENTS), (dev, MIN_CLASS_DEV_EVENTS)):
                support = frame[[target, "stable_security_id", "root_anchor_id"]].drop_duplicates()[target].value_counts()
                if not all(support.get(label, 0) >= minimum for label in classes):
                    return []
        elif len(groups(train)[0]) < MIN_CONTINUOUS_TRAIN_EVENTS or len(groups(dev)[0]) < MIN_CONTINUOUS_DEV_EVENTS:
            return []
        folds.append((train, dev))
    return folds


def result_metrics(model, target, classes, dev, yhat, probability):
    from sklearn.metrics import confusion_matrix, f1_score, mean_absolute_error, recall_score

    actual = dev[target]
    if classes is None:
        return {"MAE": float(mean_absolute_error(actual, yhat)), "unit": "sessions" if target.startswith("sessions") else "percentage_points"}
    confusion = confusion_matrix(actual, yhat, labels=classes)
    info = {
        "classes": classes, "macro_f1": float(f1_score(actual, yhat, average="macro", labels=classes, zero_division=0)),
        "per_class_recall": dict(zip(classes, recall_score(actual, yhat, labels=classes, average=None, zero_division=0).tolist())),
        "confusion_matrix": confusion.tolist(),
    }
    if model == "A":
        accepted = np.max(probability, axis=1) >= 0.5
        info["known_evaluation_abstention_rate"] = float(1 - accepted.mean())
        info["independent_unknown_slice_metrics"] = "NOT_TESTED"
    if "STRUCTURE_FAILURE" in classes:
        info["risk_false_negative_rate"] = 1 - info["per_class_recall"]["STRUCTURE_FAILURE"]
    if model in {"C", "D"}:
        correctness = pd.Series(actual.to_numpy() == yhat, index=dev.index)
        info["by_date_correct"] = {str(key): float(value) for key, value in correctness.groupby(dev.observation_date).mean().items()}
    if model == "C":
        strata = pd.cut(dev.same_role_history_event_n, [-1, 2, 7, np.inf], labels=["0–2", "3–7", "8+"])
        info["history_count_strata"] = {
            str(key): {"stocks": int(dev.loc[part.index].stable_security_id.nunique()),
                       "rows": int(len(part)), "accuracy": float(part.mean())}
            for key, part in correctness.groupby(strata, observed=True)
        }
    return info


def select_folds(certified, cutoff):
    common_columns = {}
    for model, target, names, _ in EXPERIMENTS.values():
        common_columns.setdefault((model, target), set()).update(names)
    by_target = {}
    for model, target, _, classes in EXPERIMENTS.values():
        key = (model, target)
        if key in by_target:
            continue
        if certified.empty:
            by_target[key] = []
            continue
        candidate = certified.loc[certified_rows(certified, target, cutoff)]
        numeric = candidate[sorted(common_columns[key])].apply(pd.to_numeric, errors="coerce")
        # Valid zero-history rows remain on common support when their prior is available.
        common_support = np.isfinite(numeric).all(axis=1)
        if "same_role_history_event_n" in numeric:
            count = numeric["same_role_history_event_n"]
            common_support &= count.ge(0) & count.mod(1).eq(0)
        candidate = candidate.loc[common_support]
        by_target[key] = time_folds(candidate, target, classes)
    return {name: by_target[spec[:2]] for name, spec in EXPERIMENTS.items()}


def freeze_payload(variants, environment, cutoff, manifest_sha, dataset_sha, feature_contract_sha, verified_sha,
                   writer, reviewer, synthetic=False, retry_failed_once=False):
    def cohort(frame):
        keys = frame[KEY].sort_values(KEY).to_csv(index=False).encode()
        return {"keys_sha256": sha256(keys).hexdigest(), **stats(frame)}

    scope = {
        "market": "SYNTHETIC_FIXTURE" if synthetic else "A_SHARE",
        "use": "SYNTHETIC_FIXTURE_ONLY" if synthetic else "RESEARCH_DEVELOPMENT_ONLY",
        "development_label_cutoff": cutoff, "retry_failed_once": retry_failed_once,
        "experimental_fit_allowed": True, "production_allowed": False,
        "proposed_variants": {
            name: [{"train": cohort(train), "dev": cohort(dev)} for train, dev in folds]
            for name, folds in variants.items() if folds
        },
    }
    return {
        "schema": "p515-prefit-freeze/1", "plan_author": writer, "scope": scope,
        "manifest_reviewer": reviewer,
        "certified_manifest_sha256": manifest_sha, "certified_input_sha256": dataset_sha,
        "runner_sha256": sha(Path(__file__)), "feature_contract_sha256": feature_contract_sha,
        "verified_data_sha256": verified_sha, "environment": environment,
    }


def verify_fit_approval(prefit_path, receipt_path, approval_sha, expected):
    """Verify external review’s declared scope and bytes, not the signer identity."""
    approval_bytes = receipt_path.read_bytes()
    if sha256(approval_bytes).hexdigest() != approval_sha:
        raise ValueError("Independently supplied approval receipt SHA does not match")
    plan_bytes = prefit_path.read_bytes()
    plan = json.loads(plan_bytes)
    receipt = json.loads(approval_bytes)
    frozen_at = datetime.fromisoformat(plan.pop("frozen_at_utc"))
    reviewed_at = datetime.fromisoformat(receipt["reviewed_at_utc"])
    if frozen_at.tzinfo is None or reviewed_at.tzinfo is None or reviewed_at <= frozen_at:
        raise ValueError("Review must be dated after the separately frozen plan")
    if plan.get("feature_contract_sha256") != expected["feature_contract_sha256"]:
        raise ValueError("Frozen feature contract SHA does not match the runtime contract")
    if plan != expected:
        raise ValueError("Execution context differs from the earlier frozen plan")
    verdict = ("APPROVED_SYNTHETIC_FIXTURE_FIT" if expected["scope"]["market"] == "SYNTHETIC_FIXTURE"
               else "APPROVED_RESEARCH_DEVELOPMENT_FIT")
    if (receipt.get("schema") != "p515-fit-approval/1"
            or receipt.get("verdict") != verdict
            or receipt.get("prefit_freeze_sha256") != sha256(plan_bytes).hexdigest()):
        raise ValueError("Receipt did not approve this exact PREFIT_FREEZE")
    bindings = ["certified_manifest_sha256", "certified_input_sha256", "runner_sha256",
                "feature_contract_sha256", "verified_data_sha256", "scope"]
    if any(receipt.get(key) != expected[key] for key in bindings):
        raise ValueError("Fit approval belongs to a different dataset, runner, features or experiment scope")
    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip() or reviewer.strip().casefold() == expected["plan_author"].casefold():
        raise ValueError("Review owner must be recorded and differ from the plan author")
    if reviewer.strip().casefold() != expected["manifest_reviewer"].casefold():
        raise ValueError("Approval reviewer differs from the independently reviewed manifest")
    return {
        "approval_receipt_sha256": approval_sha, "reviewer": reviewer,
        "prefit_freeze_sha256": receipt["prefit_freeze_sha256"], "reviewed_at_utc": receipt["reviewed_at_utc"],
        "identity_verification": "DECLARED_BY_INDEPENDENT_REVIEW_RECEIPT_NOT_CRYPTOGRAPHICALLY_AUTHENTICATED",
    }


WEIGHT_COLUMNS = [
    "model", "variant", "attempt", "status", "weight_path", "sha256", "reload_max_abs_error",
]


def write_experiment_csv(path, rows, columns):
    pending = path.with_suffix(".tmp")
    pd.DataFrame(rows, columns=columns).to_csv(pending, index=False)
    pending.replace(path)


def fit_fold(out, train, dev, spec, record, checkpoint):
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits

    model, target, names, classes = spec
    record["last_stage"] = "PREPARE"
    x_train, x_dev = train[list(names)].astype(float), dev[list(names)].astype(float)
    estimator_type = HistGradientBoostingClassifier if classes else HistGradientBoostingRegressor
    estimator = estimator_type(max_iter=60, max_leaf_nodes=7, min_samples_leaf=3, random_state=515, early_stopping=False)
    basename = record["variant"].replace("/", "_")
    if record["attempt"] > 1:
        basename += f"_attempt{record['attempt']}"
    weight = out / "weights" / f"{basename}.joblib"
    # Stage before publishing. A weight enters the inventory only after a complete dump.
    pending = weight.with_suffix(".joblib.pending")
    with threadpool_limits(limits=1):
        record.update(last_stage="ESTIMATOR_FIT", status="FIT_STARTED")
        checkpoint()
        record["estimator_fit_count"] += 1
        estimator.fit(x_train, train[target])
        record["estimator_fit_completed_count"] = 1
        record["last_stage"] = "WEIGHT_SAVE"
        if weight.exists() or pending.exists():
            raise FileExistsError(weight)
        joblib.dump({"estimator": estimator, "feature_names": list(names), "target": target}, pending)
        pending.rename(weight)
        record["weight_sha256"] = sha(weight)
        record["weight_path"] = str(weight.relative_to(out))

        predict = "predict_proba" if classes else "predict"
        predict_unloaded = getattr(estimator, predict)
        record["last_stage"] = "DEV_PREDICT"
        checkpoint()
        record["prediction_calls"] += 1
        value = predict_unloaded(x_dev)
        record["last_stage"] = "WEIGHT_RELOAD"
        if sha(weight) != record["weight_sha256"]:
            raise RuntimeError(f"Weight file changed after save: {weight}")
        payload = joblib.load(weight)
        if payload["feature_names"] != list(names) or payload["target"] != target:
            raise RuntimeError(f"Weight metadata reload mismatch: {weight}")
        loaded = payload["estimator"]
        if classes and not np.array_equal(estimator.classes_, loaded.classes_):
            raise RuntimeError(f"Weight class order mismatch: {weight}")
        predict_reloaded = getattr(loaded, predict)
        record["last_stage"] = "RELOADED_PREDICT"
        checkpoint()
        record["prediction_calls"] += 1
        actual = predict_reloaded(x_dev)

    if value.shape != actual.shape:
        raise RuntimeError(f"Weight reload output shape mismatch: {weight}")
    difference = float(np.max(np.abs(value - actual)))
    if np.isfinite(difference):
        record["reload_max_abs_error"] = difference
    if difference != 0.0:
        raise RuntimeError(f"Weight reload mismatch: {weight}")
    record["last_stage"] = "EVALUATE"
    estimates = estimator.classes_[np.argmax(value, axis=1)] if classes else value
    metrics = result_metrics(model, target, classes, dev, estimates, value)
    return dict(variant=record["variant"], attempt=record["attempt"], **metrics)


def run_experiments(out, certified, bound_data_sha, environment, variants, approval, retry_failed_once=False):
    if any(variants.values()) and approval is None:
        raise ValueError("Certified fits require independent approval of a separate frozen plan")
    results = []
    ledger = []
    source_digest = sha(Path(__file__))

    def checkpoint():
        write_experiment_csv(out / "EXPERIMENT_LEDGER.csv", ledger, LEDGER)
        inventory = [row for row in ledger if row.get("weight_sha256")]
        inventory = [{**row, "sha256": row["weight_sha256"]} for row in inventory]
        write_experiment_csv(out / "WEIGHT_INVENTORY.csv", inventory, WEIGHT_COLUMNS)

    for variant, spec in EXPERIMENTS.items():
        model, target, names, _ = spec
        base = dict(model=model, variant=variant, target=target, feature_count=len(names),
                    status="BLOCKED", block_reason="NO_VERIFIED_DATASET", attempt=0, last_stage="ADMISSION",
                    estimator_fit_count=0, estimator_fit_completed_count=0,
                    preprocessing_fit_count=0, calibration_fit_count=0,
                    prediction_calls=0, label_source="", source_sha256=source_digest,
                    environment=json.dumps(environment, sort_keys=True), data_sha256=bound_data_sha,
                    weight_sha256="", reload_max_abs_error=None,
                    prefit_sha256=approval["prefit_freeze_sha256"] if approval else "",
                    fit_approval_sha256=approval["approval_receipt_sha256"] if approval else "")
        base |= {f"{part}_{item}": 0 for part in ("train", "dev") for item in ("rows", "stocks", "events", "dates")}
        folds = variants[variant]
        if not certified.empty:
            base["block_reason"] = "INSUFFICIENT_CERTIFIED_COMMON_SUPPORT_OR_SPLIT"
        if not folds:
            ledger.append(base)
            continue
        (out / "weights").mkdir(exist_ok=True)

        for fold_id, (train, dev) in enumerate(folds, start=1):
            fold_record = dict(base, variant=f"{variant}/F{fold_id}", block_reason="", status="ATTEMPT_STARTED")
            for part, frame in (("train", train), ("dev", dev)):
                fold_record.update({f"{part}_{key}": count for key, count in stats(frame).items()
                                    if key in {"rows", "stocks", "events", "dates"}})
            fold_record["label_source"] = "|".join(sorted(set(train.label_source) | set(dev.label_source)))
            for attempt in range(1, 3 if retry_failed_once else 2):
                record = dict(fold_record, attempt=attempt)
                ledger.append(record)
                try:
                    result = fit_fold(out, train, dev, spec, record, checkpoint)
                except Exception as error:
                    record.update(status="ATTEMPT_FAILED", block_reason=f"{type(error).__name__}: {error}")
                    checkpoint()
                    continue
                record.update(status="RELOAD_PASSED", last_stage="COMPLETE")
                results.append(result)
                checkpoint()
                break
    checkpoint()
    if results:
        result_by_variant = {item["variant"]: item for item in results}
        contrasts = []
        for name, (model, target, _, _) in EXPERIMENTS.items():
            baseline = next(
                key for key, spec in EXPERIMENTS.items() if spec[:2] == (model, target)
            )
            if name == baseline:
                continue
            for fold in ("F1", "F2"):
                candidate = result_by_variant.get(f"{name}/{fold}")
                comparator = result_by_variant.get(f"{baseline}/{fold}")
                if not candidate or not comparator:
                    continue
                metric = "macro_f1" if "macro_f1" in candidate else "MAE"
                contrasts.append({"candidate": candidate["variant"], "comparator": comparator["variant"],
                                  "metric": metric, "candidate_minus_comparator": candidate[metric] - comparator[metric]})
        record_json(out / "EXPERIMENT_METRICS.json", {"per_variant": results, "matched_development_contrasts": contrasts})
    return ledger


def feature_contract(binding, features):
    raw_features_available = {
        field: int(features[field].notna().sum()) for field in features
        if field.startswith(("raw_", "frozen_", "sameage_")) and field != "raw_bars"
    }
    covered_knowledge = {
        "M1": ["K001/K002 active-bar OHLCV", "K003/K004/K005 effective-anchor geometry proxy",
               "K006 upper wick and position proxies, no distribution label"],
        "M2": ["K007 observed trajectory drawdown and original f05 separate",
               "K008 obs_day_index exact and effective-event observed-bar age proxy separate",
               "K009/K010 historical PB cohort flags metadata only", "K011 prior source evidence only",
               "K012 dated daily-bar break/reclaim proxy"],
        "M3": ["K013/K015 observed volume and amount with named denominators",
               "K014 asymmetry research only", "K016 observable price and volume context"],
        "M4": ["K017 chronological T5-maturity guards for available old history",
               "K018 historical raw composite keys", "K019/K020 same-age proxy summaries only"],
        "M5": ["K021/K022 sector membership-timed contract", "K023 leader selection contract"],
        "M6": ["K024/K025/K026 endpoint and validation reference only",
               "K027 chronological, maturity-aware and event-purged dev comparisons",
               "K028 D-prefix projection and future-row guard"],
    }
    return {
        "schema": "p515-local/1",
        "flags": FLAGS, "key": KEY, "timezone": "Asia/Shanghai", "course_feature_mapping": covered_knowledge,
        "source_bindings": binding, "sample_tiers": {
            "VERIFIED": "Separately adjudicated labels with authenticated root/wave and certified historical availability.",
            "PARTIAL": "Usable dated retrospective price prefix, P515 supervised target and historical PIT uncertified.",
            "UNKNOWN": "RAW prefix missing in addition to the independent-label and PIT gaps.",
        },
        "labels": {
            "phase_label": PHASES, "known_phase_fit_classes": PHASES[:-1], "unknown": "Abstain or separate independent evaluation; excluded from fit.",
            "pullback_label": OUTCOMES, "mature_pullback_targets": ["terminal_pullback_depth_pct", "sessions_to_pullback_outcome", "support_label"],
            "terminal_pullback_depth": "Maximum realized anchor-to-low depth over the independently adjudicated interval, using one price basis.",
            "sessions_to_pullback_outcome": "Exchange sessions from the independently adjudicated start to terminal support failure/confirmed completion.",
            "support_label": ["SUPPORT_HELD", "STRUCTURE_FAILURE"],
            "label_maturity_date": "First available adjudication date. Used with event_start_date to purge dev overlap. Censored, unresolved and not-started rows remain outside target fits.",
            "old_T5_context": "R4 row outcome D+1 open to D+5 close gross, and raw-episode max label; excluded from all targets and inputs here.",
            "T2_T5_net": "A separate independent mature net-return evaluation, excluded from this experiment.",
        },
        "feature_policies": {
            "raw_price": "TDX unadjusted historic OHLCV reconstructed and date-truncated, empirical evidence only; gaps or corporate actions can distort ratios.",
            "d_only": "Read by exact column allowlist. Frozen volume/attack/pullback quantities use the original rules and price basis.",
            "obs_day_index": "Frozen f04 tracker observation number.",
            "effective_days_since_event": "Exact upstream fallback-aware effective trade-session field is absent as a full cohort. Null. effective_event_age_observed_bars_proxy is the frozen observed-bar count.",
            "frozen_f05_current_dynamic_ref_depth_pct": "Original current dynamic reference high to D close, fallback retained by source.",
            "raw_effective_segment_max_preceding_high_to_low_drawdown_pct": "Percent maximum observed earlier bar high to later bar low, starting at effective technical anchor. Same-bar high-low order excluded.",
            "max_dd_anchor_high_pct": "Old fixed raw anchor signed max of close distance, least deep when negatives; never read as a numeric input or used as earliest-high drawdown.",
            "history": "D-visible by original T5 maturity check only, with composite raw keys. Same-age observations align technical effective/raw roles, not authenticated equivalent roles. No return values are loaded.",
            "history_shrinkage": "For certified comparable history, local estimate mixed with expanding train-only prior using n/(n+5). At n=0 use prior; 0–2 roots is LOW_CONFIDENCE and inputs remain research-only.",
            "sector_loo": "Exact-date membership and instrument price/turnover revisions available by the decision timestamp; exclude target from peers and denominators. Require predeclared leader and >=2 remaining valid peers.",
            "market": "Dated base universe, common as-of timestamps, market breadth and target relative return.",
            "study_controls": "Chronological dev, purge same security root and event from training and require all train outcomes mature before dev begins; no hyperparameter search, no fitted preprocessing or probability calibration.",
            "input_leakage_exclusions": ["frozen strategy score, rank and decisions", "PB labels, worst-loss membership",
                                           "labels, grading, case metadata, eligibility fields and identifying columns", "D+N and all frozen returns"],
        },
        "materialized_nonpit_feature_counts": raw_features_available,
        "experiments": {variant: {"model": model, "target": target, "feature_names": names, "classes": classes}
                        for variant, (model, target, names, classes) in EXPERIMENTS.items()},
        "min_support_per_split": {
            "classification_train_min_root_events_per_class": MIN_CLASS_TRAIN_EVENTS,
            "classification_dev_min_root_events_per_class": MIN_CLASS_DEV_EVENTS,
            "continuous_train_min_root_events": MIN_CONTINUOUS_TRAIN_EVENTS,
            "continuous_dev_min_root_events": MIN_CONTINUOUS_DEV_EVENTS,
            "qualification": "Minimal development run support only.",
        }
    }


def write_reports(out, counts, quality, prior, ledger, verified_count):
    rows = counts["rows"]
    like = f"{rows} 条观察、{counts['stocks']} 只股票、{counts['events']} 个现役事件键及 {counts['dates']} 个交易日"
    dates = f"{counts['first']} 至 {counts['last']}"
    by_model = {model: sum(row["estimator_fit_count"] for row in ledger if row["model"] == model) for model in "ABCD"}
    fit_status = {model: ("DEVELOPMENT_METRICS_SAVED" if any(row["model"] == model and row["status"] == "RELOAD_PASSED"
                                                             for row in ledger) else "NOT_TESTED") for model in "ABCD"}
    reports = {
        "P5_15_LOCAL_TRAINING_PLAN.md": f"""# P5.15 Mac 本地知识模型实验

开发候选池有 {like}（{dates}）。复用 P5.14.8 修复版及已公开图索引，覆盖 PB2 {counts['pb2']} 条、PB3 {counts['pb3']} 条、最差 {counts['worst']} 条，PB2 与最差重叠 {counts['pb2_worst_overlap']} 条。64 组图索引由当期 58 组及历史 6 组构成。最差归属只为核对研究样本，禁止进模型特征。

| 样本层 | 条数 | 用途 |
|---|---:|---|
| VERIFIED | {verified_count} | 独立准入集，采用已核验的真值、根锚波次与当时可得性 |
| PARTIAL | {quality['raw_d_quotes']} | 计算价量及走势代理、前缀审计 |
| UNKNOWN | {rows - quality['raw_d_quotes']} | 原始行情缺口，保留身份与原因 |

训练合同上，阶段 7 个观察类和 UNKNOWN 分列，UNKNOWN 不作为负标签。回调状态分为成功、失败、未启动、未知和删失。回调深度、时间和结构失效设独立目标。收益评价另需独立成熟净收益，现有 T2/T5 只引用历史口径。实验按时间切训练与开发，清除同根和同事件交叉及开发窗口前未成熟的训练标签。固定价格基线及结构对照，个股画像和板块各自验证。

当前导入的标签来源覆盖历史 {prior['source_role_security_days']} 个证券日与 {prior['source_role_rows']} 条角色观察，AI 角色 {prior['ai_role_rows']} 条。两者均为旧角色口径与已曝光开发材料，历史 PIT 未认证。P5.14.6 冻结研究规则路径为 {prior['p5146_forward_rows_footer_only']:,} 行，已核原表头与研究报告。其净 T+2 及回调规则结果沿用既有研究身份。P5.14.3 的 A/B/C、M2、旧 M3/M3D、真 C3/C6、Dot 与相似度 Model D 以本地独立审查的模型血统为依据。P5.15 的四个实验使用独立命名。

当前计数见 EXPERIMENT_LEDGER.csv。VERIFIED_TRAINING_DATASET.csv 是独立准入集。DEVELOPMENT_CANDIDATES.csv 是有限投影，训练目标及明确缺件原因见 UNKNOWN_AND_EXCLUDED_LABELS.csv。特征、试验字段、函数与门槛见 FEATURE_CONTRACT_P515.json。建议补独立阶段与回调判卷及逐日根锚波次身份、历史可得时间，再只复核发生变化的样本与任务。
""",
        "MODEL_A_STAGE_RESULTS.md": f"""# 模型 A 阶段识别

{like}（{dates}）内，独立八状态判卷、原根锚及真实波次三者交集为 0。输出可计算的当日幅度、上下影、价格相对位置、成交量和成交额、effective 段到高点的观察根数。阶段转换、真实攻击段起止、原关键 K 语义留待独立标注。

历史角色标签有 {prior['source_role_rows']} 条，属于异动、反转、买点、风险的局部观察。AI 标签 244 条均无历史 PIT 认证。真实阶段分类的 Macro-F1、每类召回、混淆矩阵和 UNKNOWN 覆盖为 {fit_status['A']}。当前 fit 为 {by_model['A']}。若取得独立 D 日真值，冻结价格基线对比加入结构项，同日同样本评价，保留质疑或无法归类案例。UNKNOWN 状态单独作为弃权及独立判卷切片的指标。
""",
        "MODEL_B_PULLBACK_RESULTS.md": f"""# 模型 B 回调质量

冻结 f05 保留原动态活动高点语义。另以原始日 bars 算有效参考段 D 收相对已见高点和前一累计高到后续低的回撤，避开同根高低先后。原状态机 `obs_day_index` 来自 f04，保留；全样本精确 `effective_days_since_event` 无对应投影，留空，现有 observed-bar proxy 单列。历史 `max_dd_anchor_high_pct` 是固定 raw 锚下签名距离最大值。它在冻结负值域取最浅观测距离。

已曝光的 PB 类型、历史 T5 标签、旧回调规则的成败各有原用途。现役候选的可认证根锚、真实起止、完成或失效真值与 PIT 未闭合。模型 fit 为 {by_model['B']}，成熟深度 MAE、成熟时长 MAE、结构失效召回和风险漏判为 {fit_status['B']}。取得独立成熟回调标签后，在共同支持上分别评估深度、会话龄和风险目标。
""",
        "MODEL_C_PERSONALITY_ABLATION.md": f"""# 模型 C 个股历史画像消融

{quality['historical_links']:,} 条历史关联引用 {quality['historical_distinct_stock_canon_raw_anchor']:,} 个证券、历史 CANON 和 raw 锚组合。{quality['sameage_links']:,} 条已有同龄价格观测供有限描述。历史 dates 与 T5 成熟度守卫逐条通过；活动 effective 与历史 raw 角色可比性及当时可得性缺证。历史实际同角色成熟数保留 UNKNOWN，代理覆盖少于 3 条历史 CANON 的观察标为 LOW_CONFIDENCE。

固定市场、市场加行业、市场加个股、市场加行业和个股四组以完全相同的开发集和标签比较，对各日期及 0–2、3–7、8+ 已认证同股历史做分层。弱历史按 expanding train-only 共享先验收缩。当前 fit 为 {by_model['C']}，本轮画像增量 {fit_status['C']}。P5.14.6 的 M0/M1/M2 使用 23/43/45 列，M1 与 M2 的改善未跨历史时间折稳定，原 M0 留作旧研究参考。
""",
        "MODEL_D_SECTOR_READINESS.md": f"""# 模型 D 板块共振

历史行业成分、可得时间、事前龙头身份在 {rows} 个原查询的准入均未核实。原静态分组保留在研究元数据，计划中的 PIT 数值保持空白。当前 fit 为 {by_model['D']}，独立对照为 {fit_status['D']}。

| 计划字段 | 点时要求与计算 |
|---|---|
| 1、5、20 日同行收益 | 成分成员关系按日可得，等权聚合合格同行同期收益，剔除目标，记录有效同行数 |
| 1、5、20 日涨跌广度 | 缺价同行单独统计，观察样本中的上涨比例，窗口内合成公式须先冻结 |
| 1、5、20 日同行成交额变动 | 目标剔除后的合计成交额相对固定前窗的变化，保持成交额单位和成员口径 |
| 行业持续性与相对市场 | 同窗相对市场收益和多窗口强弱持久性，按交易日和当时可得数据归一 |
| 龙头与目标相对强度 | 使用 D 前冻结的流动性及趋势标准选龙头，以固定 5 日收益比较，缺龙头时记 UNKNOWN |

P5.14.6 的静态 TDX 行业剔目标描述可作工程参照。P5.15 的 D 需历史点时成员、行业分类版本、有效同行和逐字段 available_at。最小实验在已认证的同行统计上对照同样本的市场基线，再根据历史独立开发折结果决定能否进入 A/B 研究。
""",
    }
    for name, content in reports.items():
        (out / name).write_text(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--synthetic-fixture-root", type=Path, help="SYNTHETIC_* fixture bundle in an OS temporary directory.")
    parser.add_argument("--retry-failed-once", action="store_true", help="Freeze and approve one retry per unsuccessful attempt.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--certified-development-manifest", type=Path)
    parser.add_argument("--approved-manifest-sha256", help="Independently approved digest. No default.")
    parser.add_argument("--freeze-only", action="store_true", help="Write the proposed experiment plan for independent review.")
    parser.add_argument("--plan-author", help="Identity of the author in freeze-only mode.")
    parser.add_argument("--prefit-freeze", type=Path, help="PREFIT_FREEZE.json from a prior freeze-only invocation.")
    parser.add_argument("--fit-approval-receipt", type=Path, help="Independent review receipt for the exact frozen plan.")
    parser.add_argument("--fit-approval-sha256", help="Receipt digest obtained independently from the reviewer.")
    args = parser.parse_args()
    synthetic = args.synthetic_fixture_root.resolve() if args.synthetic_fixture_root else None
    if synthetic:
        if args.research_root or args.audit or not args.certified_development_manifest:
            parser.error("synthetic fixtures require their own manifest and no historical source arguments")
        temp = Path(gettempdir()).resolve()
        if not synthetic.is_dir() or synthetic.parent not in {temp, Path("/tmp").resolve()} or not synthetic.name.startswith("p515-synthetic-"):
            parser.error("synthetic fixture root must be a p515-synthetic-* directory in system temporary storage")
    elif not (args.research_root and args.audit):
        parser.error("real research mode requires --research-root and --audit")
    elif args.certified_development_manifest:
        parser.error("formal execution awaits the authoritative COMMON_TRAINING_MANIFEST.json and its approved SHA")
    if args.retry_failed_once and not args.certified_development_manifest:
        parser.error("a retry requires a frozen, approved experiment plan")
    if bool(args.certified_development_manifest) != bool(args.approved_manifest_sha256):
        parser.error("a certified manifest must be paired with its independently approved SHA-256")
    approval_inputs = (args.prefit_freeze, args.fit_approval_receipt, args.fit_approval_sha256)
    if args.freeze_only:
        if not (args.certified_development_manifest and args.plan_author and args.plan_author.strip()) or any(approval_inputs):
            parser.error("freeze-only requires a certified manifest and plan author, with no fit approval arguments")
    elif args.plan_author or (args.certified_development_manifest and not all(approval_inputs)):
        parser.error("certified fit requires a separate frozen plan, approval receipt and independent receipt SHA")
    elif not args.certified_development_manifest and any(approval_inputs):
        parser.error("fit approval arguments require certified development input")
    output = args.output.resolve()
    artifacts = synthetic if synthetic else args.audit.resolve().parent
    if ((not synthetic and artifacts.name != "artifacts") or not output.is_relative_to(artifacts)
            or not output.name.startswith("p5_15_local_training")):
        parser.error("output must be a P5.15 isolated V4 artifacts directory beside the source audit")
    readonly = [args.audit, args.research_root, args.certified_development_manifest, args.prefit_freeze, args.fit_approval_receipt]
    if any(path and (output.is_relative_to(path.resolve()) or path.resolve().is_relative_to(output)) for path in readonly):
        parser.error("output must be isolated from the prior plan, receipt and other read-only inputs")
    if synthetic and any(path and not path.resolve().is_relative_to(synthetic) for path in readonly):
        parser.error("all synthetic inputs and outputs must stay inside the fixture root")
    if args.prefit_freeze and (args.prefit_freeze.name != "PREFIT_FREEZE.json"
            or not args.prefit_freeze.resolve().is_relative_to(artifacts)):
        parser.error("a prior local PREFIT_FREEZE.json is required")
    output.mkdir(exist_ok=not args.certified_development_manifest)
    allowed_existing = {"SCOPE.json", "SOURCE_INTAKE.json"}
    if any(path.name not in allowed_existing for path in output.iterdir()):
        raise FileExistsError(f"Use a new local experiment directory: {output}")
    if synthetic:
        binding = {"input_mode": "SYNTHETIC_FIXTURE_ONLY"}
        features = pd.DataFrame()
        counts = quality = prior = {}
        labels = pd.DataFrame(columns=["pool_level"])
        cohort_digest = None
    else:
        paths, binding = bind_sources(args.research_root.resolve(), args.audit.resolve())
        meta, counts = source_cohort(paths)
        raw, quality = raw_projection(paths["raw"], meta)
        history, history_quality = historical_projection(paths, meta)
        quality.update(history_quality)
        prior = prior_label_evidence(paths)
        features = feature_pool(meta, raw, history)
        labels = label_register(features)
        features.to_csv(output / "DEVELOPMENT_CANDIDATES.csv", index=False)
        labels.to_csv(output / "UNKNOWN_AND_EXCLUDED_LABELS.csv", index=False)
        cohort_digest = sha(output / "DEVELOPMENT_CANDIDATES.csv")
    verified = pd.DataFrame(columns=CERTIFIED_COLUMNS)
    certified_sha = cutoff = reviewer = None
    if args.certified_development_manifest:
        candidate, certified_sha, cutoff, reviewer = read_certified_bundle(
            args.certified_development_manifest, args.approved_manifest_sha256, synthetic)
        targets = {spec[1] for spec in EXPERIMENTS.values()}
        eligible = pd.concat([certified_rows(candidate, target, cutoff) for target in sorted(targets)], axis=1).any(axis=1)
        verified = candidate.loc[eligible]
    verified.to_csv(output / "VERIFIED_TRAINING_DATASET.csv", index=False)
    contract = feature_contract(binding, features)
    contract["strict_fit_feature_counts_current"] = {
        name: int(verified[name].notna().sum()) if name in verified else 0
        for name in sorted(set(PRICE + MARKET + STRUCTURE + PERSONALITY + SECTOR))
    }
    record_json(output / "FEATURE_CONTRACT_P515.json", contract)
    environment = {"python": sys.version.split()[0], "interpreter": sys.executable, "arch": platform.machine()}
    environment.update({name: version(name) for name in ("pandas", "numpy", "pyarrow", "scikit-learn", "joblib")})
    variants = select_folds(verified, cutoff)
    approval = None
    if args.certified_development_manifest:
        author = args.plan_author.strip() if args.freeze_only else json.loads(args.prefit_freeze.read_text())["plan_author"]
        frozen = freeze_payload(variants, environment, cutoff, args.approved_manifest_sha256, certified_sha,
                                sha(output / "FEATURE_CONTRACT_P515.json"), sha(output / "VERIFIED_TRAINING_DATASET.csv"),
                                author, reviewer, bool(synthetic), args.retry_failed_once)
        if args.freeze_only:
            record_json(output / "PREFIT_FREEZE.json", {**frozen, "frozen_at_utc": datetime.now(timezone.utc).isoformat()})
            print("PREFIT_FREEZE_WRITTEN")
            return
        approval = verify_fit_approval(args.prefit_freeze, args.fit_approval_receipt, args.fit_approval_sha256, frozen)
        record_json(output / "FIT_APPROVAL_VERIFICATION.json", approval)
    ledger = run_experiments(output, verified, certified_sha or cohort_digest, environment, variants,
                             approval, args.retry_failed_once)
    if not synthetic:
        write_reports(output, counts, quality, prior, ledger, len(verified))
    failed = {row["variant"] for row in ledger if row["status"] == "ATTEMPT_FAILED"}
    passed = {row["variant"] for row in ledger if row["status"] == "RELOAD_PASSED"}
    terminal_failed = sorted(failed - passed)
    status = "EXPERIMENT_FAILURES" if terminal_failed else ("DEVELOPMENT_METRICS_SAVED" if passed else "DEVELOPMENT_ONLY")
    record_json(output / "RUN_RECEIPT.json", {
        "utc": datetime.now(timezone.utc).isoformat(), "flags": FLAGS, "status": status,
        "input_mode": "SYNTHETIC_FIXTURE_ONLY" if synthetic else "REAL_RESEARCH",
        "terminal_failed_folds": terminal_failed, "successful_fold_count": len(passed),
        "failed_attempt_count": sum(row["status"] == "ATTEMPT_FAILED" for row in ledger),
        "retry_attempt_count": sum(row["attempt"] > 1 for row in ledger),
        "source_sha256": sha(Path(__file__)), "environment": environment, "cohort": counts,
        "data_checks": quality, "prior_label_evidence": prior,
        "verified": stats(verified), "original_development_pool_levels": labels.pool_level.value_counts().to_dict(),
        "replay_586_T2": 0, "market_scan": 0, "sealed_payload_opened": False,
        "estimator_fit_count": sum(row["estimator_fit_count"] for row in ledger),
        "estimator_fit_completed_count": sum(row["estimator_fit_completed_count"] for row in ledger),
        "preprocessing_fit_count": sum(row["preprocessing_fit_count"] for row in ledger),
        "calibration_fit_count": sum(row["calibration_fit_count"] for row in ledger),
        "prediction_calls": sum(row["prediction_calls"] for row in ledger),
        "feature_contract_sha256": sha(output / "FEATURE_CONTRACT_P515.json"),
        "development_data_sha256": cohort_digest, "verified_data_sha256": sha(output / "VERIFIED_TRAINING_DATASET.csv"),
        "certified_input_sha256": certified_sha, "fit_approval": approval, "new_weight_files": sum(bool(row["weight_sha256"]) for row in ledger),
    })
    print(json.dumps({"cohort": counts, "quality": quality, "prior_labels": prior, "verified": len(verified),
                      "fit_calls": sum(row["estimator_fit_count"] for row in ledger), "status": status}, ensure_ascii=False))
    return int(bool(terminal_failed))


if __name__ == "__main__":
    sys.exit(main())
