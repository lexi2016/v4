"""ACT-023 controlled S study: frozen ACT020 / structure+CH / structure+MR+CH.

Only --run can fit, exactly two binary/four-way HGB pairs. --prepare consumes
an identity-only external projection. Truth is opened only after every new
checkpoint is complete. No B fit, backtest, authority write or panel copy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act020_s_v2 as old
from ops import pft_act021_s_v3 as review
from ops import pft_act021_transform as rocket

SCHEMA = "pft_act023_s_v3.v1"
SEED = 20261123
TRAIN_PER_CLASS = 1000
CANDIDATES_PER_CLASS = 1200
IDENTITY_COLUMNS = ("cohort", "case_id", "ts_code", "trade_date")
ALLOWED_IDENTITY_COLUMNS = {*IDENTITY_COLUMNS, "episode_id"}
ARMS = ("structure_ch", "structure_mr_ch")
MODELS = tuple(f"{arm}_{task}" for arm in ARMS for task in ("binary", "tactic"))
MR_WIDTH = 2*7*84*len(rocket.DILATIONS)*2*len(rocket.BIASES)*len(rocket.OPERATORS)
# Fixed, data-independent spread through every representation/channel/kernel.
MR_INDICES = tuple(sorted(map(int, __import__("numpy").random.default_rng(SEED).choice(MR_WIDTH, 192, replace=False))))
EXTRA_FEATURES = (
    "advance_from_low20", "advance_from_low60", "volume_relative_anchor",
    "range_relative_anchor", "root_age", "root_close_distance", "root_low_distance",
    "root_min_close_distance", "root_min_low_distance", "active_age",
    "active_close_distance", "active_low_distance", "active_min_close_distance",
    "active_min_low_distance", "repair_event_age", "repair_event_close_distance",
    "repair_event_low_distance", "repair_event_min_close_distance", "repair_event_min_low_distance",
    "prior_invalidated_anchor_count", "prior_low_reclaim_count",
    "extension_uncontracted_severity",
)
STRUCT_FEATURES = (*old.FEATURES, *EXTRA_FEATURES)
POLICY = {
    "root_projection": "C-HMCNN max(raw_binary_S, raw_pullback, raw_readvance, raw_rebuild); children unchanged",
    "positive": "projected root>=0.5 AND best positive child>=0.5 AND best positive child>fake",
    "rejection": "strict observed finite W<Y OR fake>=0.5 OR projected root<0.5",
    "otherwise": "UNKNOWN_BORDERLINE; no definite tactic",
    "g1": "strict W<Y only; equality and missing are not assumed failures",
    "boundary": "extension/contraction and anchor counterevidence are features/audit evidence, never forced-negative external boundaries",
    "graded_extension_counterevidence": "max(close/yellow-1,0) * max(volume_compression,range_compression); continuous, no heldout-calibrated cutoff",
    "baseline": "frozen ACT020 raw HGB untouched; same hierarchy/g1 overlay separately named",
    "flags": "stage and boolean mining-rule flags excluded from features",
    "sampling": "first 1200 TRAIN-only hash-ranked candidates/class; first 1000 causally complete/class; no truth/probability selection",
    "transform": "fixed ACT021 engineering variant, not upstream fitted MultiRocket; exact sparse 192 columns; FIT=0",
}
FLAGS = dict(review.FLAGS)
ContractError = old.ContractError
RECOVERY_FILES = {"frozen_plan.json", "features.npz", "training_membership.csv", "external_keys.csv",
                  "external_evidence.json", "archived_baseline.json", "training_evidence.json"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return old.sha(path)


def digest(value: Any) -> str:
    return review.digest(review.clean(value))


def write_json(path: Path, value: Any) -> None:
    review.write_json(path, value)


def write_json_gzip(path: Path, value: Any) -> None:
    import io
    temp = path.with_suffix(path.suffix+".tmp")
    with temp.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as stream:
                json.dump(review.clean(value), stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
    temp.replace(path)


def read_identities(path: Path) -> Any:
    import pandas as pd
    out = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not set(IDENTITY_COLUMNS) <= set(out) or not set(out) <= ALLOWED_IDENTITY_COLUMNS:
        raise ContractError("IDENTITY_ONLY_INPUT_REQUIRED_NO_TRUTH_COLUMNS")
    out = out.loc[:, list(IDENTITY_COLUMNS)].copy()
    out.ts_code = out.ts_code.map(old.v12._code)
    out.trade_date = out.trade_date.map(review.day)
    if len(out) != 93 or out.duplicated(["cohort", "case_id"]).any():
        raise ContractError("EXTERNAL_REQUIRES_93_UNIQUE_COHORT_CASES")
    if out.cohort.value_counts().to_dict() != {"GOLD40": 40, "ANCHOR20": 20, "COMMON61": 33}:
        raise ContractError("EXTERNAL_COHORT_COUNT")
    return out


def select_training(labels_path: Path, identities: Any) -> Any:
    """Frozen pseudo-labels and TRAIN eligibility only; reserve whole codes."""
    import pandas as pd
    columns = ["ts_code", "trade_date", "tactic", "s_label", "episode_id", "split", "security_group", "sample_key", *old.FEATURES]
    frame = pd.read_csv(labels_path, dtype=str, usecols=columns, keep_default_na=False)
    frame = frame.loc[frame.split.eq("train") & frame.security_group.eq("train")
                      & frame.trade_date.between(old.START, old.TRAIN_END)
                      & frame.tactic.isin(old.CLASSES) & ~frame.ts_code.isin(set(identities.ts_code))].copy()
    if (frame.duplicated(["tactic", "episode_id"]).any()
            or not frame.s_label.eq(frame.tactic.map(lambda c: "FALSE" if c == "invalid_fake" else "TRUE")).all()):
        raise ContractError("FROZEN_LABEL_EPISODE_OR_BINARY_MISMATCH")
    frame["selection_hash"] = [digest([SEED, c, d, e]) for c, d, e in zip(frame.ts_code, frame.trade_date, frame.episode_id)]
    counts = frame.tactic.value_counts().to_dict()
    if any(counts.get(c, 0) < TRAIN_PER_CLASS for c in old.CLASSES):
        raise ContractError(f"TRAIN_ONLY_CLASS_AVAILABILITY:{counts}")
    result = frame.sort_values("selection_hash").groupby("tactic", sort=False).head(CANDIDATES_PER_CLASS).reset_index(drop=True)
    result.attrs["eligible_train_counts"] = counts
    return result


def bind_training_panel(baseline: Path) -> tuple[Path, dict[str, Any]]:
    from ops.pft_s_first_baseline import _contract_identity
    from ops.research_panel_qfq import panel_contract
    record = json.loads((baseline/"run_identity.json").read_text())
    source = record["source"]
    if source["generation_id"] != old.GENERATION or source["asof_date"] != old.END:
        raise ContractError("ACT020_SOURCE_GENERATION_OR_DATE")
    pinned = source["backtest"]
    panel = review.checked_file(pinned["path"], pinned["panel_sha256"])
    identity, current = _contract_identity("backtest", panel, panel_contract(panel))
    if (identity != source["identity"] or current["generation_manifest_sha256"] != pinned["generation_manifest_sha256"]
            or current["panel_sha256"] != pinned["panel_sha256"]):
        raise ContractError("ACT020_PINNED_CONTRACT_CHANGED")
    return panel, {"identity": identity, "source": current, "original_run_identity_sha256": sha(baseline/"run_identity.json")}


def read_targets(panel: Path, targets: Any) -> Any:
    """V4 existing logical Reader; bounded symbols/dates/columns in RAM only."""
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel)
    actual = {x.lower(): x for x in schema.names}
    mapping = {s: next((actual[a] for a in old.v12.ALIASES[s] if a in actual), None) for s in old.INPUTS}
    if not all(mapping.values()):
        raise ContractError("READER_REQUIRED_COLUMN_MISSING")
    lower = (datetime.strptime(min(targets.trade_date), "%Y%m%d")-timedelta(days=400)).strftime("%Y%m%d")
    upper = max(targets.trade_date)
    requested = set(targets.ts_code)
    filters = [(mapping["ts_code"], "in", sorted(requested)),
               (mapping["trade_date"], ">=", old.v12._arrow_date_value(schema, mapping["trade_date"], lower)),
               (mapping["trade_date"], "<=", old.v12._arrow_date_value(schema, mapping["trade_date"], upper))]
    raw = parquet.read_table(panel, columns=list(mapping.values()), filters=filters).to_pandas().rename(columns={v:k for k,v in mapping.items()})
    # Arrow dictionary columns retain unused HK categories even for bounded
    # A-only rows. Normalize observed cells, never the categorical dictionary.
    raw.trade_date = old.v12._normalize_observed_column(raw.trade_date, review.day, "trade_date")
    raw.ts_code = old.v12._normalize_observed_column(raw.ts_code, old.v12._code, "ts_code")
    import pandas as pd
    for column in old.INPUTS[3:]:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    if (raw.duplicated(["ts_code", "trade_date"]).any() or not set(raw.ts_code) <= requested
            or (len(raw) and (raw.trade_date.min() < lower or raw.trade_date.max() > upper))
            or not raw.market_type.astype(str).str.upper().isin(review.A_MARKETS).all()):
        raise ContractError("READER_SCOPE_OR_MARKET_VIOLATION")
    return raw.sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)


def sparse_transform(batch: Any, indices: tuple[int, ...] = MR_INDICES) -> Any:
    """Exact indexed ACT021 transform: identical arithmetic/order for each column.

    Decode flatten order representation/dilation/padding/bias/channel/kernel/op.
    Pooling is reused unchanged. Only required channel/kernel convolutions are
    evaluated, and no transform matrix is fitted or selected from observations.
    """
    import numpy as np
    x = np.asarray(batch, dtype=np.float64)
    if x.ndim != 3 or x.shape[1:] != (7, 60) or not np.isfinite(x).all():
        raise ContractError("EXPECTED_FINITE_N_7_60")
    if any(i < 0 or i >= MR_WIDTH for i in indices):
        raise ContractError("TRANSFORM_INDEX_RANGE")
    kernels = rocket.kernels()[np.random.default_rng(rocket.SEED).permutation(84)]
    decoded = {}
    for col, index in enumerate(indices):
        rep, di, pad, bias, channel, kernel, operator = np.unravel_index(index, (2, 3, 2, 3, 7, 84, 4))
        decoded.setdefault((rep, di, pad), {}).setdefault((channel, kernel), []).append((col, bias, operator))
    output = np.empty((len(x), len(indices)), dtype=np.float64)
    representations = (x, np.diff(x, axis=-1))
    for (rep, di, padded), pairs in decoded.items():
        channel_indices, kernel_indices = map(list, zip(*pairs))
        values = representations[rep][:, channel_indices]
        dilation = rocket.DILATIONS[di]
        span = 8*dilation+1
        work = np.pad(values, ((0, 0), (0, 0), (span//2, span//2))) if padded else values
        windows = np.lib.stride_tricks.sliding_window_view(work, span, axis=-1)[..., ::dilation]
        conv = np.einsum("nptj,pj->npt", windows, kernels[kernel_indices], optimize=False)
        pooled = {bi: rocket._pool(conv, rocket.BIASES[bi]) for bi in {e[1] for entries in pairs.values() for e in entries}}
        for pair_index, entries in enumerate(pairs.values()):
            for col, bi, op in entries:
                output[:, col] = pooled[bi][:, pair_index, op]
    return output


def structural_features(context: Any, shape: dict[str, Any]) -> tuple[list[float], dict[str, Any]]:
    """Independent continuous evidence; stage/rule flags stay out of model X."""
    import numpy as np
    history = review.anchor_history(context)
    rows = context.to_dict("records")
    last = rows[-1]
    close, low = float(last["close"]), float(last["low"])
    extra = {"advance_from_low20": close/float(context.low.tail(20).min())-1,
             "advance_from_low60": close/float(context.low.tail(60).min())-1,
             "volume_relative_anchor": float("nan"), "range_relative_anchor": float("nan")}
    active = history["active"]
    # Relative shrinkage compares recent bars to the SAME preceding anchor
    # wave, not to an absolute all-security volume/amplitude cutoff.
    if active:
        event_index = active["bar_index"]
        wave = context.iloc[max(0, event_index-4):event_index+1]
        recent = context.tail(5)
        extra["volume_relative_anchor"] = float(recent.vol.mean()/wave.vol.mean())
        wave_range = float(((wave.high-wave.low)/wave.close).mean())
        extra["range_relative_anchor"] = float(((recent.high-recent.low)/recent.close).mean()/wave_range) if wave_range > 0 else float("nan")
    else:
        # Missing anchor has NaN semantics, supported natively by HGB.
        pass
    repair_event = next((e for e in reversed(history["events"]) if e["role"] == "repair"), None)
    for role, event in (("root", history["root"]), ("active", active), ("repair_event", repair_event)):
        vals = ([float(len(rows)-1-event["bar_index"]), close/event["low"]-1,
                 low/event["low"]-1, event["min_close_since_anchor"]/event["low"]-1,
                 event["min_low_since_anchor"]/event["low"]-1] if event else [float("nan")]*5)
        for suffix, value in zip(("age", "close_distance", "low_distance", "min_close_distance", "min_low_distance"), vals):
            extra[f"{role}_{suffix}"] = value
    extra["prior_invalidated_anchor_count"] = float(sum(e["close_broken_flag"] for e in history["events"][:-1]))
    extra["prior_low_reclaim_count"] = float(sum(len(e["same_day_low_pierce_reclaim_dates"]) for e in history["events"]))
    extra["extension_uncontracted_severity"] = max(float(shape["yellow_distance"]), 0.)*max(float(shape["volume_compression"]), float(shape["range_compression"]))
    stage, flags = review.observable_stage(context, shape, history, True)
    audit = {"white": last["zge_white_line"], "yellow": last["zge_yellow_line"],
             "g1_strict_failure": bool(last["zge_white_line"] < last["zge_yellow_line"]),
             "white_yellow_equal": bool(last["zge_white_line"] == last["zge_yellow_line"]),
             "yellow_extension": shape["yellow_distance"], "advance_from_low60": extra["advance_from_low60"],
             "volume_compression": shape["volume_compression"], "range_compression": shape["range_compression"],
             "uncontracted_counterevidence": bool(shape["volume_compression"] >= 1 or shape["range_compression"] >= 1),
             "extension_uncontracted_severity": extra["extension_uncontracted_severity"],
             "stage": stage, "stage_flags": flags, "anchors": history,
             "missing_extra_features": [k for k,v in extra.items() if not math.isfinite(v)]}
    values = [float(shape[k]) for k in old.FEATURES]+[extra[k] for k in EXTRA_FEATURES]
    if not np.isfinite(values[:len(old.FEATURES)]).all() or np.isinf(values).any():
        raise ContractError("NONFINITE_BASE_OR_INFINITE_STRUCTURAL_FEATURE")
    return values, audit


def extract(panel: Path, targets: Any, *, frozen_features: bool = False) -> tuple[Any, Any, list[dict[str, Any]]]:
    import numpy as np
    targets = targets.reset_index(drop=True)
    x = np.full((len(targets), len(STRUCT_FEATURES)), np.nan)
    mr = np.full((len(targets), len(MR_INDICES)), np.nan)
    evidence = [{"status": "EXACT_D_NOT_IN_BOUND_PANEL"} for _ in range(len(targets))]
    codes = sorted(set(targets.ts_code))
    for first in range(0, len(codes), 128):
        part = targets.loc[targets.ts_code.isin(codes[first:first+128])]
        raw = read_targets(panel, part)
        shaped = old.causal_shapes(raw, start=min(part.trade_date), end=max(part.trade_date))
        shapes = {(r["ts_code"], r["trade_date"]): r for r in shaped.to_dict("records")}
        by_code = {c: f.reset_index(drop=True) for c,f in raw.groupby("ts_code", sort=False)}
        pending, channels = [], []
        for index, target in part.iterrows():
            key = (target.ts_code, target.trade_date)
            exact = by_code.get(target.ts_code)
            exact = exact.loc[exact.trade_date.eq(target.trade_date)] if exact is not None else None
            line_evidence = {}
            if exact is not None and len(exact) == 1:
                current = exact.iloc[0]
                line_evidence = {"white": current.zge_white_line, "yellow": current.zge_yellow_line,
                                 "ts_code": target.ts_code, "trade_date": target.trade_date, "panel_path": str(panel)}
            shape = shapes.get(key)
            if not shape or not shape["feature_ready"]:
                evidence[index] = {**line_evidence, "status": "MISSING_CAUSAL_CONTEXT" if shape else "EXACT_D_NOT_IN_BOUND_PANEL"}
                continue
            lower = (datetime.strptime(target.trade_date, "%Y%m%d")-timedelta(days=400)).strftime("%Y%m%d")
            context = by_code[target.ts_code].loc[lambda f: f.trade_date.between(lower, target.trade_date)]
            # Preserve invalid/missing semantics: require all exact 65 bars for
            # 60 transform observations, with no dropna/resampling/imputation.
            if len(context) < 65 or not all(review.valid_bar(r) for r in context.tail(65).to_dict("records")):
                evidence[index] = {**line_evidence, "status": "MISSING_65_VALID_CAUSAL_BARS"}
                continue
            values, audit = structural_features(context, shape)
            if frozen_features:
                values[:len(old.FEATURES)] = [float(target[k]) for k in old.FEATURES]
            x[index] = values
            evidence[index] = {"status": "READY", "ts_code": target.ts_code, "trade_date": target.trade_date,
                               "panel_path": str(panel), "context_start": min(context.trade_date),
                               "context_end": max(context.trade_date), "causal_bars": len(context), **audit}
            pending.append(index)
            channels.append(rocket.channels(context.tail(65)))
        if pending:
            mr[pending] = sparse_transform(np.stack(channels))
        print(json.dumps({"stage": "causal_features", "symbols_done": min(first+128, len(codes)), "symbols": len(codes), "targets": len(targets), "ready_block": len(pending)}), flush=True)
    return x, mr, evidence


def baseline_manifest(directory: Path) -> dict[str, Any]:
    ledger_path = directory/"fit_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("S") != 4 or ledger.get("B") != 0 or ledger.get("tuning") != 0 or ledger.get("model_config", {}).get("hgb") != old.HGB_CONFIG:
        raise ContractError("ACT020_FROZEN_LEDGER_OR_HGB_CONFIG")
    names = ("run_identity.json", "labels.csv", "external_predictions.csv", "fit_ledger.json", "binary_hgb.joblib", "tactic_hgb.joblib")
    result = {name: {"path": str(directory/name), "sha256": sha(directory/name)} for name in names}
    for name in ("binary_hgb", "tactic_hgb"):
        if ledger["models"][name].get("state") != "COMPLETE" or result[f"{name}.joblib"]["sha256"] != ledger["models"][name]["weight_sha256"]:
            raise ContractError("ACT020_WEIGHT_LINKAGE")
    return result


def archived_baseline(baseline: Path, reveal_path: Path, identities: Any) -> dict[str, Any]:
    """Read ONLY pre-existing raw model scores and code/D, never adjudication."""
    import numpy as np
    import pandas as pd
    archive = pd.read_csv(baseline/"external_predictions.csv", dtype=str, keep_default_na=False)
    columns = ["p_binary_hgb", *[f"p_tactic_hgb_{c}" for c in old.CLASSES]]
    result = {}
    for (code, day), group in archive.loc[archive.prediction_status.eq("PREDICTED")].groupby(["ts_code", "trade_date"], sort=False):
        numbers = group[columns].astype(float).to_numpy()
        if not np.allclose(numbers, numbers[0], rtol=0, atol=0):
            raise ContractError("ARCHIVED_EXACT_D_BASELINE_CONFLICT")
        result[f"{code}/{day}"] = {"probabilities": numbers[0].tolist(), "linkage": "ACT020_ARCHIVED_EXACT_CODE_D_RAW_HGB",
                                   "source_path": str(baseline/"external_predictions.csv"), "source_sha256": sha(baseline/"external_predictions.csv")}
    reveal = json.loads(reveal_path.read_text())
    gold = set(zip(identities.loc[identities.cohort.eq("GOLD40"), "ts_code"], identities.loc[identities.cohort.eq("GOLD40"), "trade_date"]))
    found = set()
    for case in reveal["cases"]:
        key = (old.v12._code(case["ts_code"]), review.day(case["decision_date"]))
        if key not in gold:
            continue
        diagnostic = case.get("raw_model_diagnostic", {})
        if "binary_hgb" not in diagnostic or "tactic_hgb" not in diagnostic:
            raise ContractError(f"GOLD_ARCHIVED_RAW_DIAGNOSTIC_MISSING:{key}")
        numbers = [float(diagnostic["binary_hgb"]["raw_positive_probability"]),
                   *[float(diagnostic["tactic_hgb"]["raw_tactic_probabilities"][c]) for c in old.CLASSES]]
        result["/".join(key)] = {"probabilities": numbers, "linkage": "ACT021_SEALED_REVEAL_ACT020_RAW_HGB_EXACT_D",
                               "source_path": str(reveal_path), "source_sha256": sha(reveal_path)}
        found.add(key)
    if found != gold:
        raise ContractError("GOLD_ARCHIVED_RAW_LINKAGE_INCOMPLETE")
    requested = {f"{c}/{d}" for c,d in zip(identities.ts_code, identities.trade_date)}
    return {key: value for key,value in result.items() if key in requested}


def prepare(baseline: Path, groups_path: Path, identities_path: Path, output: Path) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import shutil
    output.mkdir(parents=True, exist_ok=True)
    if (output/"prepared.json").exists():
        return verify_prepared(baseline, groups_path, identities_path, output)
    if (output/"fit_ledger.json").exists():
        raise ContractError("FIT_EXISTS_WITHOUT_PREPARED_RECEIPT")
    if shutil.disk_usage(output).free < 1024**3:
        raise ContractError("PREPARE_REQUIRES_1G_FREE_BUDGET")
    identities = read_identities(identities_path)
    provenance = baseline_manifest(baseline)
    panel, source = bind_training_panel(baseline)
    groups, group_identity = review.load_groups(groups_path)
    reveal_path = groups_path.parent/"run"/"private_reveal.json"
    if not reveal_path.is_file():
        raise ContractError("ACT021_PRIVATE_REVEAL_REQUIRED_FOR_FROZEN_GOLD_RAW")
    plan = {"schema": SCHEMA, "code_sha256": sha(Path(__file__)), "baseline": provenance,
            "external_identities_sha256": sha(identities_path), "groups_sha256": sha(groups_path),
            "features": STRUCT_FEATURES, "mr_indices": MR_INDICES, "mr_version": rocket.VERSION,
            "hgb_config": old.HGB_CONFIG, "policy": POLICY, "class_order": old.CLASSES,
            "fit_budget": {"S": 4, "B": 0, "tuning": 0}, "backtest_count": 0,
            "cutoff": old.TRAIN_END, "whole_external_codes_reserved": sorted(set(identities.ts_code)),
            "transform_source_sha256": sha(Path(rocket.__file__)), "act020_source_sha256": sha(Path(old.__file__)),
            "baseline_reveal": {"path": str(reveal_path), "sha256": sha(reveal_path)},
            "act021_source_sha256": sha(Path(review.__file__)), "created_at": now(),
            "resources": old.resource_snapshot(), "full_panel_disk_writes": 0,
            "output_budget_bytes": 128*1024**2, "temporary_artifacts": [], **FLAGS}
    plan["training_evidence_format"] = "gzip JSON; local reproducibility derivative only"
    write_json(output/"frozen_plan.json", plan)  # before any new predictions/features
    write_json(output/"archived_baseline.json", archived_baseline(baseline, reveal_path, identities))
    candidates = select_training(baseline/"labels.csv", identities)
    counts = candidates.attrs["eligible_train_counts"]
    tx, tm, te = extract(panel, candidates, frozen_features=True)
    ready = np.array([e["status"] == "READY" for e in te])
    selected = candidates.loc[ready].sort_values("selection_hash").groupby("tactic", sort=False).head(TRAIN_PER_CLASS)
    if selected.tactic.value_counts().to_dict() != {c: TRAIN_PER_CLASS for c in old.CLASSES}:
        write_json(output/"prepare_failure.json", {"class_counts": selected.tactic.value_counts().to_dict(), "statuses": pd.Series([e["status"] for e in te]).value_counts().to_dict()})
        raise ContractError("CAUSALLY_COMPLETE_TRAIN_CLASS_UNDERFILLED_NO_FIT")
    indices = selected.index.to_numpy()
    tx, tm = tx[indices], tm[indices]
    training = selected.loc[:, ["ts_code", "trade_date", "episode_id", "tactic", "s_label", "selection_hash"]].reset_index(drop=True)
    training.to_csv(output/"training_membership.csv", index=False)
    if set(training.ts_code) & set(identities.ts_code) or training.trade_date.gt(old.TRAIN_END).any():
        raise ContractError("TRAIN_EXTERNAL_SECURITY_OR_DATE_LEAKAGE")
    unique = identities[["ts_code", "trade_date"]].drop_duplicates().sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    ex = np.full((len(unique), len(STRUCT_FEATURES)), np.nan)
    em = np.full((len(unique), len(MR_INDICES)), np.nan)
    ee = [{"status": "NO_EXACT_D_SOURCE_BINDING"} for _ in range(len(unique))]
    bindings = []
    gold_keys = set(zip(identities.loc[identities.cohort.eq("GOLD40"), "ts_code"], identities.loc[identities.cohort.eq("GOLD40"), "trade_date"]))
    for day, target in unique.groupby("trade_date", sort=True):
        exact = [g for g in groups if g["decision_date"] == day]
        gold_on_day = any((r.ts_code, day) in gold_keys for r in target.itertuples())
        if gold_on_day:
            if len(exact) != 1:
                raise ContractError(f"GOLD_REQUIRES_UNIQUE_EXACT_D_GROUP:{day}")
            external_panel, binding = review.bind_panel(exact[0])
            if external_panel is None:
                bindings.append({"day": day, "binding": binding})
                continue
        else:
            external_panel, binding = panel, source
        sx, sm, se = extract(external_panel, target.reset_index(drop=True))
        ex[target.index], em[target.index] = sx, sm
        for i, e in zip(target.index, se):
            ee[i] = e
        bindings.append({"day": day, "binding": binding, "panel_path": str(external_panel), "target_count": len(target),
                         "read_scope": "requested symbols and causal <=D bars only"})
    unique.to_csv(output/"external_keys.csv", index=False)
    # Pure feature/result derivatives only; never a physical price-panel copy.
    np.savez_compressed(output/"features.npz", train_structure=tx, train_mr=tm, external_structure=ex, external_mr=em)
    write_json(output/"external_evidence.json", ee)
    write_json_gzip(output/"training_evidence.json.gz", [te[i] for i in indices])
    # Pin models and source again; no current/latest substitution or silent drift.
    if baseline_manifest(baseline) != provenance or bind_training_panel(baseline)[1] != source or sha(groups_path) != group_identity["sha256"]:
        raise ContractError("SOURCE_CHANGED_DURING_PREPARE")
    files = ("frozen_plan.json", "archived_baseline.json", "training_membership.csv", "external_keys.csv", "features.npz", "external_evidence.json", "training_evidence.json.gz")
    receipt = {"schema": SCHEMA, "status": "PREPARED_FIT_ZERO", "actual_fit": {"S": 0, "B": 0},
               "plan_sha256": sha(output/"frozen_plan.json"), "source": source, "groups": group_identity,
               "external_bindings": bindings, "eligible_train_counts": counts, "train_n": len(training),
               "train_counts": training.tactic.value_counts().to_dict(), "external_n": len(identities),
               "external_unique_n": len(unique), "external_statuses": pd.Series([e["status"] for e in ee]).value_counts().to_dict(),
               "files": {n: sha(output/n) for n in files}, "prepared_at": now(), **FLAGS}
    receipt["artifact_bytes"] = sum((output/n).stat().st_size for n in files)
    if receipt["artifact_bytes"] > plan["output_budget_bytes"]:
        raise ContractError("PREPARED_DERIVATIVE_OUTPUT_BUDGET_EXCEEDED")
    write_json(output/"prepared.json", receipt)
    return receipt


def recover_prepared(baseline: Path, groups_path: Path, identities_path: Path, output: Path,
                     manifest_path: Path, manifest_sha256: str) -> dict[str, Any]:
    """Certify exact controller-pinned FIT=0 outputs; compress audit, no reread.

    All feature/membership bytes remain unchanged. Only audit serialization,
    code identity and receipt completion change. Any mismatching byte or fit
    evidence stops recovery instead of silently recomputing or reserving FIT.
    """
    import numpy as np
    import pandas as pd
    import shutil
    import re
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) or sha(manifest_path) != manifest_sha256:
        raise ContractError("RECOVERY_CONTROLLER_MANIFEST_SHA_MISMATCH")
    recovery_hashes = json.loads(manifest_path.read_text())
    if set(recovery_hashes) != RECOVERY_FILES or not all(re.fullmatch(r"[0-9a-f]{64}", v) for v in recovery_hashes.values()):
        raise ContractError("RECOVERY_CONTROLLER_MANIFEST_FIXED_FILES_REQUIRED")
    if (output/"prepared.json").exists():
        return verify_prepared(baseline, groups_path, identities_path, output)
    if (output/"fit_ledger.json").exists() or (output/"run.lock").exists() or list(output.glob("*.joblib*")):
        raise ContractError("RECOVERY_REQUIRES_ZERO_FIT_AND_NO_RUN_LOCK")
    for name, expected in recovery_hashes.items():
        if sha(output/name) != expected:
            raise ContractError(f"RECOVERY_INTACT_OUTPUT_MISMATCH:{name}")
    original_plan = json.loads((output/"frozen_plan.json").read_text())
    identities = read_identities(identities_path)
    if (not re.fullmatch(r"[0-9a-f]{64}", original_plan["code_sha256"])
            or original_plan["groups_sha256"] != sha(groups_path)
            or original_plan["external_identities_sha256"] != sha(identities_path)
            or original_plan["baseline"] != baseline_manifest(baseline)
            or original_plan["features"] != list(STRUCT_FEATURES)
            or original_plan["mr_indices"] != list(MR_INDICES)
            or original_plan["hgb_config"] != old.HGB_CONFIG or original_plan["policy"] != POLICY
            or original_plan["transform_source_sha256"] != sha(Path(rocket.__file__))
            or original_plan["act020_source_sha256"] != sha(Path(old.__file__))
            or original_plan["act021_source_sha256"] != sha(Path(review.__file__))
            or original_plan["baseline_reveal"]["sha256"] != sha(Path(original_plan["baseline_reveal"]["path"]))):
        raise ContractError("RECOVERY_FROZEN_INPUT_OR_FEATURE_CONTRACT_CHANGED")
    panel, source = bind_training_panel(baseline)
    groups, group_identity = review.load_groups(groups_path)
    train = pd.read_csv(output/"training_membership.csv", dtype=str, keep_default_na=False)
    candidates = select_training(baseline/"labels.csv", identities)
    available = candidates.set_index("selection_hash")
    if (len(train) != 4000 or train.tactic.value_counts().to_dict() != {c:1000 for c in old.CLASSES}
            or not set(train.selection_hash) <= set(available.index)
            or set(train.ts_code) & set(identities.ts_code)
            or not train.trade_date.between(old.START, old.TRAIN_END).all()
            or train.duplicated(["tactic", "episode_id"]).any()):
        raise ContractError("RECOVERY_MEMBERSHIP_CONTRACT")
    matched = available.loc[train.selection_hash]
    for name in ("ts_code", "trade_date", "episode_id", "tactic", "s_label"):
        if matched[name].tolist() != train[name].tolist():
            raise ContractError("RECOVERY_MEMBERSHIP_NOT_FROZEN_TRAIN_LABELS")
    keys = pd.read_csv(output/"external_keys.csv", dtype=str, keep_default_na=False)
    expected_keys = identities[["ts_code", "trade_date"]].drop_duplicates().sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    if not keys.equals(expected_keys):
        raise ContractError("RECOVERY_EXTERNAL_KEYS_CHANGED")
    with np.load(output/"features.npz") as arrays:
        expected_shapes = {"train_structure":(4000,len(STRUCT_FEATURES)), "train_mr":(4000,len(MR_INDICES)),
                           "external_structure":(len(keys),len(STRUCT_FEATURES)), "external_mr":(len(keys),len(MR_INDICES))}
        if set(arrays.files) != set(expected_shapes) or any(arrays[k].shape != v or np.isinf(arrays[k]).any() for k,v in expected_shapes.items()):
            raise ContractError("RECOVERY_FEATURE_SHAPE_OR_INFINITY")
        if not np.isfinite(arrays["train_mr"]).all():
            raise ContractError("RECOVERY_TRAIN_TRANSFORM_MISSING")
        np.testing.assert_allclose(arrays["train_structure"][:, :len(old.FEATURES)], matched.loc[:,list(old.FEATURES)].to_numpy(dtype=float), rtol=0, atol=0)
    training_evidence = json.loads((output/"training_evidence.json").read_text())
    if len(training_evidence) != len(train) or any(e["status"] != "READY" or e["ts_code"] != r.ts_code or e["trade_date"] != r.trade_date
            or e["context_end"] != r.trade_date or any(a["date"] > r.trade_date for a in e["anchors"]["events"])
            for e,r in zip(training_evidence, train.itertuples())):
        raise ContractError("RECOVERY_TRAIN_CAUSAL_AUDIT_MISMATCH")
    del training_evidence
    ee = json.loads((output/"external_evidence.json").read_text())
    if len(ee) != len(keys):
        raise ContractError("RECOVERY_EXTERNAL_EVIDENCE_COUNT")
    gold_keys = set(zip(identities.loc[identities.cohort.eq("GOLD40"),"ts_code"], identities.loc[identities.cohort.eq("GOLD40"),"trade_date"]))
    bindings = []
    for day, targets in keys.groupby("trade_date", sort=True):
        if any((r.ts_code,day) in gold_keys for r in targets.itertuples()):
            exact = [g for g in groups if g["decision_date"] == day]
            if len(exact) != 1:
                raise ContractError("RECOVERY_GOLD_EXACT_GROUP")
            external_panel, binding = review.bind_panel(exact[0])
            if external_panel is None:
                raise ContractError("RECOVERY_GOLD_SOURCE_UNAVAILABLE")
        else:
            external_panel, binding = panel, source
        if any(e.get("panel_path") != str(external_panel) or e.get("trade_date") != r.trade_date
               or e.get("context_end",r.trade_date) != r.trade_date for e,r in zip([ee[i] for i in targets.index],targets.itertuples())):
            raise ContractError("RECOVERY_EXTERNAL_CAUSAL_SOURCE_MISMATCH")
        bindings.append({"day":day,"binding":binding,"panel_path":str(external_panel),"target_count":len(targets),"read_scope":"rebound existing exact-D source; intact feature bytes reused"})
    marker = {"schema":SCHEMA,"action":"RECOVER_INTACT_PREFIT_BUDGET_FAILURE_GZIP_AUDIT_ONLY", "started_at":now(),
              "original_output_sha256":recovery_hashes,"controller_manifest_path":str(manifest_path),"controller_manifest_sha256":manifest_sha256,
              "new_code_sha256":sha(Path(__file__)),"actual_fit":{"S":0,"B":0},
              "membership_and_arrays":"PASS_FROZEN_KEYS_LABELS_SHAPES_NO_INF", "sources":"PASS_REBOUND_PINNED_CONTRACTS", **FLAGS}
    write_json(output/"prepare_recovery_started.json", marker)
    preserved_plan = output/"frozen_plan_pre_gzip_recovery.json"
    if preserved_plan.exists() and sha(preserved_plan) != recovery_hashes["frozen_plan.json"]:
        raise ContractError("RECOVERY_ORIGINAL_PLAN_ARCHIVE_CONFLICT")
    if not preserved_plan.exists():
        shutil.copyfile(output/"frozen_plan.json", preserved_plan)
    raw_audit, packed_audit = output/"training_evidence.json", output/"training_evidence.json.gz"
    temp = packed_audit.with_suffix(".gz.tmp")
    with raw_audit.open("rb") as source_stream, temp.open("wb") as target_stream:
        with gzip.GzipFile(filename="",mode="wb",fileobj=target_stream,mtime=0,compresslevel=6) as stream:
            shutil.copyfileobj(source_stream,stream,1024*1024)
    restored_hash = hashlib.sha256()
    with gzip.open(temp,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            restored_hash.update(block)
    if restored_hash.hexdigest() != recovery_hashes["training_evidence.json"]:
        raise ContractError("RECOVERY_GZIP_UNCOMPRESSED_SHA_MISMATCH")
    temp.replace(packed_audit)
    plan = dict(original_plan)
    plan.update(code_sha256=sha(Path(__file__)),training_evidence_format="gzip JSON; local reproducibility derivative only",
                recovery={"original_plan_path":str(preserved_plan),"original_plan_sha256":sha(preserved_plan),
                          "original_code_sha256":original_plan["code_sha256"],"original_audit_sha256":recovery_hashes["training_evidence.json"],
                          "controller_manifest_path":str(manifest_path),"controller_manifest_sha256":manifest_sha256})
    write_json(output/"frozen_plan.json",plan)
    completion = {**marker,"status":"PASS_GZIP_BYTES_RESTORED_SHA_EQUAL","finished_at":now(),
                  "original_audit_bytes":raw_audit.stat().st_size,"compressed_audit_bytes":packed_audit.stat().st_size,
                  "compressed_audit_sha256":sha(packed_audit),"feature_and_membership_bytes_changed":False,
                  "disposition":"original task-owned redundant training_evidence.json removed after receipt; gzip preserves exact original bytes"}
    write_json(output/"prepare_recovery.json",completion)
    files = ("frozen_plan.json","frozen_plan_pre_gzip_recovery.json","prepare_recovery_started.json","prepare_recovery.json",
             "archived_baseline.json","training_membership.csv","external_keys.csv","features.npz","external_evidence.json","training_evidence.json.gz")
    receipt = {"schema":SCHEMA,"status":"PREPARED_FIT_ZERO_RECOVERED_GZIP_AUDIT_ONLY","actual_fit":{"S":0,"B":0},
               "plan_sha256":sha(output/"frozen_plan.json"),"source":source,"groups":group_identity,"external_bindings":bindings,
               "eligible_train_counts":candidates.attrs["eligible_train_counts"],"train_n":len(train),"train_counts":train.tactic.value_counts().to_dict(),
               "external_n":len(identities),"external_unique_n":len(keys),"external_statuses":pd.Series([e["status"] for e in ee]).value_counts().to_dict(),
               "files":{n:sha(output/n) for n in files},"artifact_bytes":sum((output/n).stat().st_size for n in files),"prepared_at":now(),**FLAGS}
    if receipt["artifact_bytes"] > plan["output_budget_bytes"]:
        raise ContractError("RECOVERY_COMPRESSED_OUTPUT_BUDGET_EXCEEDED")
    write_json(output/"prepared.json",receipt)
    raw_audit.unlink()  # exact self-produced redundant bytes preserved in gzip
    return receipt


def verify_prepared(baseline: Path, groups: Path, identities: Path, output: Path) -> dict[str, Any]:
    receipt = json.loads((output/"prepared.json").read_text())
    for name, expected in receipt["files"].items():
        if sha(output/name) != expected:
            raise ContractError(f"PREPARED_ARTIFACT_CHANGED:{name}")
    plan = json.loads((output/"frozen_plan.json").read_text())
    recovery = plan.get("recovery")
    if recovery and sha(Path(recovery["controller_manifest_path"])) != recovery["controller_manifest_sha256"]:
        raise ContractError("PREPARED_RECOVERY_MANIFEST_CHANGED")
    if (plan["code_sha256"] != sha(Path(__file__)) or plan["groups_sha256"] != sha(groups)
            or plan["external_identities_sha256"] != sha(identities) or plan["baseline"] != baseline_manifest(baseline)
            or plan["baseline_reveal"]["sha256"] != sha(Path(plan["baseline_reveal"]["path"]))
            or plan["transform_source_sha256"] != sha(Path(rocket.__file__))
            or plan["act020_source_sha256"] != sha(Path(old.__file__)) or plan["act021_source_sha256"] != sha(Path(review.__file__))):
        raise ContractError("PREPARED_INPUT_OR_CODE_CHANGED_NO_REFIT")
    if review.clean(bind_training_panel(baseline)[1]) != receipt["source"]:
        raise ContractError("PREPARED_PINNED_SOURCE_CHANGED")
    original_groups, _ = review.load_groups(groups)
    for binding in receipt["external_bindings"]:
        match = [g for g in original_groups if g["decision_date"] == binding["day"]]
        if match and binding.get("panel_path") == match[0].get("panel_path"):
            _, rebound = review.bind_panel(match[0])
            if review.clean(rebound) != binding["binding"]:
                raise ContractError("PREPARED_EXTERNAL_SOURCE_CHANGED")
    return receipt


def fit_models(training: Any, arrays: Any, output: Path, *, factory: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Four durable reservations, checkpoints before downstream work; no retry."""
    import joblib
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    key = digest({"prepared": sha(output/"prepared.json"), "model_names": MODELS, "hgb": old.HGB_CONFIG})
    ledger_path = output/"fit_ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        if ledger["fit_identity"] != key:
            raise ContractError("FIT_IDENTITY_CHANGED_NO_REFIT")
    else:
        ledger = {"schema": SCHEMA, "fit_identity": key, "S": 0, "B": 0, "tuning": 0,
                  "transform_fit": 0, "models": {}, "events": [], "config": old.HGB_CONFIG, **FLAGS}
        write_json(ledger_path, ledger)
    models = {}
    for name in MODELS:
        arm, task = name.rsplit("_", 1)
        x = arrays["train_structure"] if arm == "structure_ch" else np.column_stack([arrays["train_structure"], arrays["train_mr"]])
        y = training.s_label.eq("TRUE").astype(int).to_numpy() if task == "binary" else training.tactic.map({c:i for i,c in enumerate(old.CLASSES)}).to_numpy()
        path = output/f"{name}.joblib"
        state = ledger["models"].get(name)
        if state:
            if state["state"] != "COMPLETE" or not path.exists() or sha(path) != state["weight_sha256"]:
                raise ContractError(f"UNCERTAIN_FIT_DO_NOT_REPEAT:{name}")
            model = old.load_weight(path)
        else:
            if path.exists() or ledger["S"] >= 4:
                raise ContractError("FIT_BUDGET_OR_UNRECEIPTED_WEIGHT")
            model = factory(name) if factory else HistGradientBoostingClassifier(**old.HGB_CONFIG)
            ledger["S"] += 1
            ledger["models"][name] = {"state": "RESERVED", "rows": len(y), "features": x.shape[1], "started_at": now()}
            ledger["events"].append({"model": name, "event": "FIT_START_RESERVED", "time": now()})
            write_json(ledger_path, ledger)
            # No exception-triggered retry; RESERVED is fail closed on restart.
            print(json.dumps({"stage": "fit_start", "model": name, "reserved_S": ledger["S"], "rows": len(y), "features": x.shape[1]}), flush=True)
            try:
                model.fit(x, y)
            except Exception as exc:
                ledger["models"][name].update(state="FAILED_NO_RETRY", error=f"{type(exc).__name__}:{exc}", finished_at=now())
                ledger["events"].append({"model": name, "event": "FIT_FAILED_NO_RETRY", "time": now(), "error": type(exc).__name__})
                write_json(ledger_path, ledger)
                raise
            temp = path.with_suffix(".joblib.tmp")
            joblib.dump(model, temp)
            temp.replace(path)
            replay = model.predict_proba(x[:128])
            model = old.load_weight(path)
            if not np.array_equal(replay, model.predict_proba(x[:128])):
                raise ContractError(f"CHECKPOINT_RELOAD_REPLAY:{name}")
            ledger["models"][name].update(state="COMPLETE", finished_at=now(), weight_sha256=sha(path),
                                           classes=list(map(int, model.classes_)), replay_sha256=hashlib.sha256(replay.tobytes()).hexdigest())
            ledger["events"].append({"model": name, "event": "FIT_COMPLETE_CHECKPOINTED", "time": now()})
            write_json(ledger_path, ledger)
            print(json.dumps({"stage": "fit_complete_checkpoint", "model": name, "S": ledger["S"], "weight_sha256": sha(path)}), flush=True)
        if hashlib.sha256(model.predict_proba(x[:128]).tobytes()).hexdigest() != ledger["models"][name]["replay_sha256"]:
            raise ContractError(f"CHECKPOINT_REPLAY_CHANGED:{name}")
        models[name] = model
    if ledger["S"] != 4 or ledger["B"] != 0 or len(models) != 4:
        raise ContractError("FOUR_S_ZERO_B_REQUIRED")
    return models, ledger


def coherent(root: float, children: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    """Canonical max constraint and a common fixed monotonic decision gate."""
    import numpy as np
    p = np.asarray(children, dtype=float)
    if p.shape != (4,) or not np.isfinite(p).all() or not math.isfinite(root) or (p < 0).any() or (p > 1).any() or not 0 <= root <= 1 or not np.isclose(p.sum(), 1):
        raise ContractError("INVALID_HIERARCHY_PROBABILITY")
    projected = max(float(root), float(p[:3].max()))
    best = int(p[:3].argmax())
    w, y = evidence.get("white"), evidence.get("yellow")
    observed = all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (w, y))
    strict = bool(observed and w < y)
    if strict:
        state, tactic, reason = "REJECTED_FAKE", "invalid_fake", "STRICT_OBSERVED_W_BELOW_Y"
    elif not observed:
        state, tactic, reason = "UNKNOWN_BORDERLINE", "", "MISSING_LINE_EVIDENCE"
    elif p[3] >= .5 or projected < .5:
        state, tactic, reason = "REJECTED_FAKE", "invalid_fake", "COHERENT_MODEL_REJECTION"
    elif p[best] >= .5 and p[best] > p[3] and projected >= .5:
        state, tactic, reason = "CONFIRMED_S", old.CLASSES[best], "COHERENT_POSITIVE_CHILD"
    else:
        state, tactic, reason = "UNKNOWN_BORDERLINE", "", "NO_DEFINITE_POSITIVE_CHILD"
    return {"projected_p_s": projected, "projected_p_fake": float(p[3]),
            **{f"projected_p_{c}": float(p[i]) for i,c in enumerate(old.CLASSES[:3])},
            "final_state": state, "main_tactic": tactic, "decision_reason": reason,
            "strict_g1_failure": strict, "line_evidence_observed": observed,
            "raw_hierarchy_contradiction": bool(root < float(p[:3].max())),
            "raw_decision_contradiction": bool((root >= .5) == (int(p.argmax()) == 3)),
            "final_hierarchy_contradiction": bool(projected < float(p[:3].max())),
            "final_decision_contradiction": bool(state == "CONFIRMED_S" and (tactic == "invalid_fake" or strict))}


def predict_external(models: dict[str, Any], baseline: Path, arrays: Any, keys: Any, evidence: Any, archived: dict[str, Any]) -> Any:
    import numpy as np
    import pandas as pd
    output = keys.copy()
    baseline_models = {task: old.load_weight(baseline/f"{task}_hgb.joblib") for task in ("binary", "tactic")}
    for i, row in output.iterrows():
        e = evidence[i]
        output.loc[i, "prediction_status"] = e["status"]
        for arm in ("baseline", *ARMS):
            archived_score = archived.get(f"{row.ts_code}/{row.trade_date}") if arm == "baseline" else None
            if archived_score:
                probabilities = archived_score["probabilities"]
                root, children = float(probabilities[0]), probabilities[1:]
                output.loc[i, "baseline_linkage"] = archived_score["linkage"]
                output.loc[i, "baseline_raw_source_sha256"] = archived_score["source_sha256"]
            elif e["status"] != "READY":
                w, y = e.get("white"), e.get("yellow")
                strict = all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (w,y)) and w < y
                output.loc[i, f"{arm}_final_state"] = "REJECTED_FAKE" if strict else "UNKNOWN_BORDERLINE"
                output.loc[i, f"{arm}_main_tactic"] = "invalid_fake" if strict else ""
                output.loc[i, f"{arm}_decision_reason"] = "STRICT_OBSERVED_W_BELOW_Y" if strict else e["status"]
                output.loc[i, f"{arm}_strict_g1_failure"] = strict
                output.loc[i, f"{arm}_prediction_status"] = e["status"]
                continue
            else:
                x = arrays["external_structure"][i:i+1]
                if arm == "baseline":
                    x, pair = x[:, :len(old.FEATURES)], baseline_models
                    output.loc[i, "baseline_linkage"] = "ACT020_EXACT_FROZEN_WEIGHTS_D_ONLY_PROJECTED_INPUT"
                else:
                    if arm == "structure_mr_ch":
                        x = np.column_stack([x, arrays["external_mr"][i:i+1]])
                    pair = {task: models[f"{arm}_{task}"] for task in ("binary", "tactic")}
                if list(pair["binary"].classes_) != [0,1] or list(pair["tactic"].classes_) != [0,1,2,3]:
                    raise ContractError("MODEL_CLASS_ORDER")
                root = float(pair["binary"].predict_proba(x)[0,1])
                children = pair["tactic"].predict_proba(x)[0]
            result = coherent(root, children, e)
            output.loc[i, f"{arm}_prediction_status"] = "PREDICTED_ARCHIVED_RAW" if archived_score else "PREDICTED"
            output.loc[i, f"{arm}_raw_p_s"] = root
            output.loc[i, f"{arm}_raw_binary_state"] = "CONFIRMED_S" if root >= .5 else "REJECTED_FAKE"
            output.loc[i, f"{arm}_raw_main_tactic"] = old.CLASSES[int(np.argmax(children))]
            for j, c in enumerate(old.CLASSES):
                output.loc[i, f"{arm}_raw_p_{c}"] = float(children[j])
            for k,v in result.items():
                output.loc[i, f"{arm}_{k}"] = v
        for key in ("white", "yellow", "yellow_extension", "advance_from_low60", "volume_compression", "range_compression", "uncontracted_counterevidence", "extension_uncontracted_severity", "stage"):
            output.loc[i, key] = e.get(key)
        output.loc[i, "anchor_evidence_ref"] = f"external_evidence.json#{i}"
    return output


def evaluate(predictions: Any, truth_path: Path) -> tuple[Any, dict[str, Any]]:
    """First truth access; called only after all four checkpoint receipts."""
    import pandas as pd
    truth = pd.read_csv(truth_path, dtype=str, keep_default_na=False)
    required = {*IDENTITY_COLUMNS, "truth_state", "truth_tactic"}
    if not required <= set(truth) or len(truth) != 93 or truth.duplicated(["cohort", "case_id"]).any():
        raise ContractError("TRUTH_CONTRACT")
    truth.trade_date = truth.trade_date.map(review.day)
    truth.ts_code = truth.ts_code.map(old.v12._code)
    if not truth.truth_state.isin(["CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE"]).all():
        raise ContractError("TRUTH_STATE_ENUM")
    gold = truth.cohort.eq("GOLD40")
    if (not truth.truth_tactic.isin(["", *old.CLASSES]).all()
            or not truth.loc[gold & truth.truth_state.eq("CONFIRMED_S"), "truth_tactic"].isin(old.CLASSES[:3]).all()
            or not truth.loc[gold & truth.truth_state.eq("REJECTED_FAKE"), "truth_tactic"].eq("invalid_fake").all()):
        raise ContractError("TRUTH_STATE_TACTIC_CONSISTENCY")
    joined = truth.merge(predictions, on=list(IDENTITY_COLUMNS), how="outer", validate="one_to_one", indicator=True)
    if not joined._merge.eq("both").all():
        raise ContractError("TRUTH_IDENTITY_MISMATCH")
    joined = joined.drop(columns="_merge")
    metrics = {}
    for cohort, frame in [("ALL", joined), *list(joined.groupby("cohort", sort=True))]:
        cohort_result = {"n": len(frame), "true_state_counts": frame.truth_state.value_counts().to_dict(), "arms": {}}
        for arm in ("baseline", *ARMS):
            pstate = frame[f"{arm}_final_state"]
            ptactic = frame.get(f"{arm}_main_tactic", pd.Series("", index=frame.index)).fillna("")
            positives = frame.truth_state.eq("CONFIRMED_S")
            tactic_known = positives & frame.truth_tactic.isin(old.CLASSES[:3])
            fake = frame.truth_state.eq("REJECTED_FAKE")
            boundary = frame.truth_state.eq("UNKNOWN_BORDERLINE")
            entry = {"predicted_state_counts": pstate.value_counts().to_dict(),
                     "state_accuracy": float(pstate.eq(frame.truth_state).mean()),
                     "confirmed_s_recall": float(pstate[positives].eq("CONFIRMED_S").mean()) if positives.any() else None,
                     "confirmed_s_false_reject_n": int((positives & pstate.eq("REJECTED_FAKE")).sum()),
                     "fake_accept_n": int((fake & pstate.eq("CONFIRMED_S")).sum()),
                     "boundary_forced_accept_n": int((boundary & pstate.eq("CONFIRMED_S")).sum()),
                     "boundary_forced_reject_n": int((boundary & pstate.eq("REJECTED_FAKE")).sum()),
                     "tactic_truth_n": int(tactic_known.sum()),
                     "tactic_accuracy_confirmed_s": float(ptactic[tactic_known].eq(frame.loc[tactic_known, "truth_tactic"]).mean()) if tactic_known.any() else None,
                     "per_tactic": {c: {"n": int((positives & frame.truth_tactic.eq(c)).sum()),
                                        "correct": int((positives & frame.truth_tactic.eq(c) & ptactic.eq(c) & pstate.eq("CONFIRMED_S")).sum())} for c in old.CLASSES[:3]}}
            for key in ("raw_hierarchy_contradiction", "raw_decision_contradiction", "final_hierarchy_contradiction", "final_decision_contradiction"):
                column = f"{arm}_{key}"
                entry[f"{key}_n"] = int(frame[column].fillna(False).astype(bool).sum()) if column in frame else None
            if arm == "baseline":
                raw_state = frame.get("baseline_raw_binary_state", pd.Series("", index=frame.index))
                raw_tactic = frame.get("baseline_raw_main_tactic", pd.Series("", index=frame.index))
                entry["frozen_raw_state_accuracy"] = float(raw_state.eq(frame.truth_state).mean())
                entry["frozen_raw_confirmed_s_recall"] = float(raw_state[positives].eq("CONFIRMED_S").mean()) if positives.any() else None
                entry["frozen_raw_tactic_accuracy_confirmed_s"] = float(raw_tactic[tactic_known].eq(frame.loc[tactic_known, "truth_tactic"]).mean()) if tactic_known.any() else None
            cohort_result["arms"][arm] = entry
        metrics[cohort] = cohort_result
    return joined, metrics


def run(baseline: Path, groups: Path, identities_path: Path, truth: Path, output: Path) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    from threadpoolctl import threadpool_limits
    verify_prepared(baseline, groups, identities_path, output)
    lock = output/"run.lock"
    try:
        fd = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractError("RUN_LOCK_EXISTS_NO_DUPLICATE_FIT") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        training = pd.read_csv(output/"training_membership.csv", dtype=str, keep_default_na=False)
        arrays = np.load(output/"features.npz")
        with threadpool_limits(limits=old.resource_snapshot()["threads"]):
            models, ledger = fit_models(training, arrays, output)
            keys = pd.read_csv(output/"external_keys.csv", dtype=str)
            evidence = json.loads((output/"external_evidence.json").read_text())
            archived = json.loads((output/"archived_baseline.json").read_text())
            unique_predictions = predict_external(models, baseline, arrays, keys, evidence, archived)
        identities = read_identities(identities_path)
        predictions = identities.merge(unique_predictions, on=["ts_code", "trade_date"], how="left", validate="many_to_one")
        predictions.to_csv(output/"predictions_without_truth.csv", index=False)
        # Persist all predictions before opening truth. Failures below reuse
        # completed weights and cannot reserve another fit.
        joined, metrics = evaluate(predictions, truth)
        joined.to_csv(output/"predictions.csv", index=False)
        summary = {"schema": SCHEMA, "status": "COMPLETE_RESEARCH_ONLY", "actual_fit": {"S": ledger["S"], "B": ledger["B"], "tuning": 0},
                   "backtest_count": 0, "transform_fit": 0, "external_rows": len(joined),
                   "truth_sha256": sha(truth), "truth_first_read": "AFTER_FOUR_COMPLETE_FITS_AND_PREDICTION_CHECKPOINT",
                   "metrics": metrics, "policy": POLICY, "prepared_sha256": sha(output/"prepared.json"),
                   "fit_ledger_sha256": sha(output/"fit_ledger.json"),
                   "limitations": ["External references are adjudicated diagnostics, not unseen generalization or economic evidence", "Gold40 has no positive Rebuild; metrics cannot establish Rebuild recall", "Fixed ACT021 transform is an engineering variant, not upstream fitted MultiRocket", "Old ACT020 training exposure is inherited; new arms reserve all external securities", "Anchor history is left-censored to 400 calendar days"],
                   "finished_at": now(), **FLAGS}
        write_json(output/"summary.json", summary)
        return summary
    finally:
        lock.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    """Synthetic arithmetic/causality only, no actual estimator fitting."""
    import numpy as np
    import pandas as pd
    x = np.random.default_rng(7).normal(size=(2,7,60))
    full = rocket.transform(x)
    sparse = sparse_transform(x)
    if not np.array_equal(full[:, MR_INDICES], sparse):
        raise ContractError("SPARSE_TRANSFORM_NOT_EXACT")
    for root, children in ((.2,[.7,.1,.1,.1]), (.99,[.01,.01,.01,.97]), (.7,[.3,.25,.2,.25])):
        r = coherent(root, children, {"white": 11., "yellow": 10.})
        assert r["projected_p_s"] >= max(children[:3]) and not r["final_decision_contradiction"]
        assert coherent(root, children, {"white": 9., "yellow": 10.})["final_state"] == "REJECTED_FAKE"
    assert not coherent(.8,[.7,.1,.1,.1],{"white":10.,"yellow":10.})["strict_g1_failure"]
    assert coherent(.8,[.7,.1,.1,.1],{"white":None,"yellow":10.})["final_state"] == "UNKNOWN_BORDERLINE"
    dates = pd.bdate_range("2025-01-01", periods=100).strftime("%Y%m%d")
    close = np.linspace(10, 16, 100)
    raw = pd.DataFrame({"ts_code":"000001.SZ", "trade_date":dates, "market_type":"A_SHARE", "open":close*.99,
                        "high":close*1.02,"low":close*.98,"close":close,"vol":1000.,"zge_white_line":close*.95,"zge_yellow_line":close*.9})
    shapes = old.causal_shapes(raw, start=dates[0], end=dates[-1])
    prefix = raw.iloc[:90]
    pshape = old.causal_shapes(prefix, start=dates[0], end=dates[89]).iloc[-1].to_dict()
    a, _ = structural_features(prefix, pshape)
    b, _ = structural_features(raw.iloc[:90], shapes.loc[shapes.trade_date.eq(dates[89])].iloc[0].to_dict())
    np.testing.assert_equal(a,b)
    assert np.array_equal(rocket.channels(prefix.tail(65)), rocket.channels(raw.iloc[:90].tail(65)))
    return {"status":"PASS_SYNTHETIC_ONLY", "sparse_exact_columns":len(MR_INDICES), "canonical_hierarchy":"PASS", "g1_strict_equality_missing":"PASS", "prefix_causality":"PASS", "actual_fit":{"S":0,"B":0}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--groups", type=Path)
    parser.add_argument("--external-identities", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--recovery-manifest", type=Path, help="controller-certified local hash manifest; recovery only")
    parser.add_argument("--recovery-manifest-sha256", help="controller-pinned manifest SHA; recovery only")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="identity-only causal features, FIT=0")
    mode.add_argument("--recover-prepared", action="store_true", help="exact controller-pinned FIT=0 budget failure only; reuse features, gzip audit")
    mode.add_argument("--run", action="store_true", help="sole audited real four-fit command; requires prepared receipt")
    mode.add_argument("--self-test", action="store_true", help="synthetic/mock checks only, FIT=0")
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        else:
            if any(getattr(args, k) is None for k in ("baseline_dir", "groups", "external_identities", "output_dir")):
                parser.error("baseline-dir, groups, external-identities and output-dir required")
            if args.prepare or args.recover_prepared:
                if args.truth is not None:
                    parser.error("--prepare forbids --truth; use identity-only projection")
                params = (args.baseline_dir.resolve(), args.groups.resolve(), args.external_identities.resolve(), args.output_dir.resolve())
                if args.recover_prepared:
                    if args.recovery_manifest is None or args.recovery_manifest_sha256 is None:
                        parser.error("recovery requires --recovery-manifest and --recovery-manifest-sha256")
                    result = recover_prepared(*params,args.recovery_manifest.resolve(),args.recovery_manifest_sha256)
                else:
                    result = prepare(*params)
            else:
                if args.truth is None:
                    parser.error("--run requires --truth for post-fit evaluation")
                result = run(args.baseline_dir.resolve(), args.groups.resolve(), args.external_identities.resolve(), args.truth.resolve(), args.output_dir.resolve())
        print(json.dumps(review.clean(result), ensure_ascii=False, allow_nan=False))
        return 0
    except (ContractError, OSError, ValueError, KeyError) as exc:
        print(f"ACT023_FAILED:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
