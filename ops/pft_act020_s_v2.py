"""ACT-020 S_V2: causal structure mining and exactly four frozen S fits.

Research mining proxies, not a universal definition of the tactics. All labels
are D-only weak supervision. UNKNOWN is never a negative. No economics, B
models, authority writes, or full physical panel copies are produced.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act015_execution as base  # only existing read_projected
from ops import pft_s_v12_full_a as v12

SCHEMA = "pft_act020_s_v2.v1"
SIGNED_DOC = "1an39i0-dB6B_bKnom0sAPk8MbbO9Zq-k4218XbzDpd0"
GENERATION = "4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268"
START, TRAIN_END, VALID_START, END = "20241101", "20260831", "20260901", "20261120"
CLASSES = ("pullback", "readvance", "rebuild", "invalid_fake")
MODEL_NAMES = ("binary_lr", "binary_hgb", "tactic_lr", "tactic_hgb")
PRIMARY = "hgb"  # fixed before seeing any metrics
LR_CONFIG = dict(C=1., solver="lbfgs", class_weight="balanced", random_state=0, max_iter=1000, tol=1e-8)
HGB_CONFIG = dict(max_iter=100, learning_rate=.05, max_leaf_nodes=7, max_depth=3,
                  l2_regularization=1., early_stopping=False, random_state=0, class_weight="balanced")
LABEL_SCOPE = {
    "kind": "high-purity D-only weak research mining proxies; cutoffs are not universal tactic gates",
    "white": "consecutive valid closes below D end-of-day white; no inferred intraday dynamic-line cross",
    "yellow": "two consecutive valid closes; single recapture is insufficient for rebuild",
    "anchors": "prior K low, true repair K low, repair body midpoint and platform resistance are separate evidence",
    "volume": "prior expansion nonbull compares close to previous close, distinct from candle body; volume uses prior5 baseline",
    "fake": "recent positive-ish evidence required; no investor-identity inference",
}
FLAGS = dict(v12.FLAGS)
INPUTS = ("ts_code", "trade_date", "market_type", "open", "high", "low", "close", "vol",
          "zge_white_line", "zge_yellow_line")
# Continuous primitive shape quantities only; no branch flags, label thresholds,
# target encoding, symbol, date, BBI/J, decision flags or forward values.
FEATURE_UNITS = {
    "body_frac": "(close-open)/prior close", "wick_frac": "upper wick/prior close",
    "range_frac": "(high-low)/prior close", "volume_ratio": "volume/prior5 mean",
    "volume_compression": "recent5 mean/prior15 mean", "range_compression": "recent5 mean/prior15 mean",
    "prior_volume_compression": "prior5 mean/preceding15 mean",
    "prior_range_compression": "prior5 mean/preceding15 mean",
    "white_slope": "white 5-bar fractional slope/bar", "yellow_slope": "yellow 5-bar fractional slope/bar",
    "line_spread": "white/yellow-1", "white_distance": "close/white-1",
    "yellow_distance": "close/yellow-1", "resistance_distance": "close/prior10 high-1",
    "trailing_peak_distance": "close/trailing30 high-1", "prior_impulse_body": "prior K body/prior close",
    "prior_impulse_volume": "prior K volume/prior5 mean", "anchor_distance": "close/prior K low-1",
    "anchor_age": "security bars since prior K", "repair_age": "security bars since true recapture",
    "repair_distance": "close/repair low-1",
}
FEATURES = tuple(FEATURE_UNITS)
REQUIRED_EXTERNAL = {"source", "case_id", "ts_code", "trade_date", "s_label", "tactic", "split", "episode_id"}


class ContractError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return v12._sha_file(path)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
    temp.replace(path)


def security_group(code: str) -> str:
    return "validation" if int(hashlib.sha256(code.encode()).hexdigest()[:8], 16) % 5 == 0 else "train"


def _safe_ratio(a: Any, b: Any) -> Any:
    return a / b.where(b.gt(0))


def causal_shapes(raw: Any, *, start: str = START, end: str = END) -> Any:
    """Only rolling/shift-positive prefix operations; state never sees D+1.

    Reuses V1.2's grouped rolling implementation. Its full vectorizer also
    calculates forward economic targets and B flags, so is intentionally not
    invoked here. Only INPUTS are admitted before either features or labelling.
    """
    import numpy as np
    import pandas as pd
    missing = set(INPUTS) - set(raw.columns)
    if missing:
        raise ContractError(f"MISSING_CAUSAL_INPUT:{sorted(missing)}")
    out = raw.loc[:, list(INPUTS)].copy()
    out["trade_date"] = v12._normalize_observed_column(out.trade_date, lambda d: v12._day(d, "trade_date"), "trade_date")
    out["ts_code"] = v12._normalize_observed_column(out.ts_code, v12._code, "ts_code")
    out = out.loc[out.trade_date.le(end)].sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)
    if out.duplicated(["ts_code", "trade_date"]).any():
        raise ContractError("DUPLICATE_CAUSAL_KEY")
    for column in INPUTS[3:]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    g = out.groupby("ts_code", sort=False)
    out["seq"] = g.cumcount()
    out["prev"] = g.close.shift(1)
    out["bar_range"] = _safe_ratio(out.high - out.low, out.close)
    roll = lambda c, n, shift=0, operation="mean": v12._group_roll(out, c, n, shift=shift, operation=operation)
    out["prior5v"], out["prior15v"] = roll("vol", 5, 1), roll("vol", 15, 5)
    out["prior15r"] = roll("bar_range", 15, 5)
    out["prior10high"] = roll("high", 10, 1, "max")
    out["high30"] = roll("high", 30, 0, "max")
    out["body_frac"] = _safe_ratio(out.close-out.open, out.prev)
    out["wick_frac"] = _safe_ratio(out.high-out[["open", "close"]].max(axis=1), out.prev)
    out["range_frac"] = _safe_ratio(out.high-out.low, out.prev)
    out["volume_ratio"] = _safe_ratio(out.vol, out.prior5v)
    out["volume_compression"] = _safe_ratio(roll("vol", 5), out.prior15v)
    out["range_compression"] = _safe_ratio(roll("bar_range", 5), out.prior15r)
    out["prior_volume_compression"] = _safe_ratio(out.prior5v, roll("vol", 15, 6))
    out["prior_range_compression"] = _safe_ratio(roll("bar_range", 5, 1), roll("bar_range", 15, 6))
    out["white_slope"] = (out.zge_white_line/g.zge_white_line.shift(5)-1)/5
    out["yellow_slope"] = (out.zge_yellow_line/g.zge_yellow_line.shift(5)-1)/5
    out["line_spread"] = _safe_ratio(out.zge_white_line, out.zge_yellow_line)-1
    out["white_distance"] = _safe_ratio(out.close, out.zge_white_line)-1
    out["yellow_distance"] = _safe_ratio(out.close, out.zge_yellow_line)-1
    out["resistance_distance"] = _safe_ratio(out.close, out.prior10high)-1
    out["trailing_peak_distance"] = _safe_ratio(out.close, out.high30)-1
    valid = (np.isfinite(out[list(INPUTS[3:])].to_numpy()).all(axis=1)
             & out[list(INPUTS[3:])].gt(0).all(axis=1)
             & out.high.ge(out[["open", "close", "low"]].max(axis=1))
             & out.low.le(out[["open", "close", "high"]].min(axis=1)))
    # A malformed bar invalidates the causal context, not just the D row.
    out["valid_bar"] = valid
    out["context_valid"] = roll("valid_bar", 61, 0, "min").eq(1)
    records = []
    for _, part in out.groupby("ts_code", sort=False):
        anchor = None
        damage = None
        repair = None
        expansion = deque(maxlen=4)
        last_positive = -1000
        prior = None
        white_below_count = 0
        for row in part.to_dict("records"):
            i, day, code = int(row["seq"]), row["trade_date"], row["ts_code"]
            # Prior-event anchors are captured before D can become a new K.
            row.update(prior_impulse_body=anchor["body_frac"] if anchor else -1.,
                       prior_impulse_volume=anchor["volume_ratio"] if anchor else -1.,
                       anchor_distance=row["close"]/anchor["low"]-1 if anchor else -1.,
                       anchor_age=float(i-anchor["seq"]) if anchor else -1.,
                       anchor_date=anchor["trade_date"] if anchor else "",
                       anchor_low=anchor["low"] if anchor else None)
            if anchor and row["valid_bar"] and row["close"] < anchor["low"]:
                anchor["failed"] = True
            # Preserve an old break until genuine recapture; do not replace it
            # with each above-both pair or silently forget unresolved damage.
            below_y = row["close"] < row["zge_yellow_line"]
            if (row["valid_bar"] and below_y and prior is not None and prior["valid_bar"]
                    and prior["close"] < prior["zge_yellow_line"]):
                damage = {"seq": i, "trade_date": day}
                repair = None
            above = row["close"] > max(row["zge_white_line"], row["zge_yellow_line"])
            white_below_count = (white_below_count+1 if row["valid_bar"] and row["close"] < row["zge_white_line"] else 0)
            if repair and row["valid_bar"] and row["low"] < repair["low"]:
                repair["failed"] = True
            if (row["valid_bar"] and damage and repair is None and above and row["body_frac"] >= .01
                    and row["volume_ratio"] >= 1.1 and row["close"] > (prior["high"] if prior else float("inf"))):
                repair = {"seq": i, "trade_date": day, "low": row["low"], "high": row["high"], "midpoint": (row["open"]+row["close"])/2, "failed": False}
            row.update(repair_age=float(i-repair["seq"]) if repair else -1.,
                       repair_distance=row["close"]/repair["low"]-1 if repair else -1.,
                       repair_date=repair["trade_date"] if repair else "",
                       damage_date=damage["trade_date"] if damage else "",
                       damage_age=i-damage["seq"] if damage else -1,
                       repair_failed=bool(repair and repair["failed"]),
                       anchor_failed=bool(anchor and anchor.get("failed")),
                       repair_high=repair["high"] if repair else None,
                       repair_midpoint=repair["midpoint"] if repair else None,
                       white_below_observations=white_below_count)
            row["prior_expansion_nonbull"] = sum(x[1] for x in expansion if i-x[0] <= 20)
            row["prior_expansion_count"] = sum(i-x[0] <= 20 for x in expansion)
            row["recent_positive"] = i-last_positive <= 10
            label = label_shape(row)
            row.update(label)
            row["feature_ready"] = bool(row["context_valid"] and np.isfinite([row[f] for f in FEATURES]).all())
            if not row["feature_ready"]:
                row.update(tactic="UNKNOWN", s_label="UNKNOWN", unknown_reason="MISSING_OR_INVALID_CAUSAL_CONTEXT", episode_id="")
            if start <= day <= end:
                records.append(row)
            if row["valid_bar"] and row["volume_ratio"] >= 1.2:
                expansion.append((i, row["close"] < row["prev"]))
            impulse = (row["valid_bar"] and row["close"]/row["prev"]-1 >= .035
                       and row["volume_ratio"] >= 1.2 and row["body_frac"] >= .02
                       and row["wick_frac"] <= .025)
            if impulse:
                anchor = dict(row, failed=False)
            if impulse or (above and row["body_frac"] >= .01 and row["white_slope"] > 0):
                last_positive = i
            prior = row
    return pd.DataFrame(records)


def label_shape(r: dict[str, Any]) -> dict[str, Any]:
    """High-purity mining taxonomy. Ambiguous/conflicting evidence => UNKNOWN.

    Cutoffs are frozen study proxies. G1/G2 are inherited shape concepts, never
    claims that these cuts universally define the named market tactics.
    """
    import math
    def finite(*names: str) -> bool:
        return all(isinstance(r.get(n), (int, float)) and math.isfinite(r[n]) for n in names)
    ready = bool(r.get("context_valid")) and finite("body_frac", "volume_ratio", "range_compression", "white_slope")
    g1 = r.get("line_spread", -1) > 0
    g2 = ((r.get("yellow_distance", -1) >= .35-1e-12 and (r.get("wick_frac", 0) >= .03-1e-12 or r.get("body_frac", 0) < 0))
          or (r.get("yellow_distance", -1) >= .25-1e-12 and r.get("wick_frac", 0) >= .04-1e-12 and r.get("volume_ratio", 0) >= 1.5)
          or (r.get("trailing_peak_distance", 0) <= -.22+1e-12 and r.get("range_frac", 0) >= .08-1e-12))
    anchor = bool(r.get("anchor_date")) and not r.get("anchor_failed", True) and 3 <= r.get("anchor_age", -1) <= 35
    hold = anchor and r["low"] >= max(r["anchor_low"], r["zge_white_line"]*.995)
    compressed = r.get("volume_compression", 99) <= .8 and r.get("range_compression", 99) <= .85
    compact_prior = r.get("prior_volume_compression", 99) <= .85 and r.get("prior_range_compression", 99) <= .85
    damage = bool(r.get("damage_date"))
    repaired = bool(r.get("repair_date")) and not r.get("repair_failed", True)
    active_damage = damage and not (repaired and r.get("repair_age", -1) >= 2)
    post_repair = (repaired and 2 <= r.get("repair_age", -1) <= 15
                   and 2 <= r.get("damage_age", -1) <= 25 and compressed
                   and r["low"] >= r["zge_white_line"]*.995
                   and r["close"] <= r["repair_high"]*1.04)
    positive = []
    if ready and g1 and not g2:
        if hold and compressed and r["volume_ratio"] <= 1 and r["resistance_distance"] <= 0 and not active_damage and not post_repair and (not damage or r.get("repair_age", -1) > 15) and r["white_slope"] > 0:
            positive.append("pullback")
        if hold and compact_prior and r["resistance_distance"] > .003 and r["volume_ratio"] >= 1.2 and r["body_frac"] >= .01 and not active_damage and not post_repair:
            positive.append("readvance")
        if post_repair and r["white_distance"] > 0 and r["yellow_distance"] > 0:
            positive.append("rebuild")
    risks = []
    if ready and r.get("recent_positive"):
        if r.get("prior_expansion_count", 0) >= 4 and r.get("prior_expansion_nonbull", 0) >= 3:
            risks.append("PRIOR_VOLUME_NONBULL_3_OF_4")
        if (r.get("anchor_failed") or (r.get("white_below_observations", 0) >= 2 and r.get("white_distance", 0) < -.01)):
            risks.append("UNRESOLVED_WHITE_OR_K_BREAK")
        if r.get("repair_failed"):
            risks.append("FAILED_REPAIR_ANCHOR")
        if abs(r.get("line_spread", 99)) < .003 and abs(r.get("white_slope", 99)) < .0003 and abs(r.get("yellow_slope", 99)) < .0003:
            risks.append("TANGENT_LINES_WITHOUT_TREND")
        if g2 or (r.get("volume_ratio", 0) >= 2 and r.get("wick_frac", 0) >= .025):
            risks.append("CLIMAX_OR_UPPER_WICK")
        if r.get("anchor_age", -1) > 40:
            risks.append("EXPIRED_KEY_ANCHOR")
    # Conflicting positive and fake evidence is excluded, never forced negative.
    tactic = positive[0] if len(positive) == 1 and not risks else ("invalid_fake" if not positive and risks else "UNKNOWN")
    s_label = "UNKNOWN" if tactic == "UNKNOWN" else ("FALSE" if tactic == "invalid_fake" else "TRUE")
    if tactic == "rebuild":
        event = f"repair:{r.get('damage_date')}:{r.get('repair_date')}"
    elif tactic == "invalid_fake":
        event = f"fake:{r.get('anchor_date') or r.get('repair_date') or r.get('damage_date') or 'none'}:{','.join(risks)}"
    else:
        event = f"K:{r.get('anchor_date')}"
    episode = f"{r.get('ts_code')}:{event}" if tactic != "UNKNOWN" else ""
    return {"tactic": tactic, "s_label": s_label, "episode_id": episode,
            "g1_evidence": g1, "g2_evidence": g2, "support_held": hold,
            "compressed_evidence": compressed, "compact_prior_evidence": compact_prior,
            "active_damage": active_damage, "post_repair_consolidation": post_repair,
            "positive_evidence": "|".join(positive), "counterevidence": "|".join(risks),
            "unknown_reason": "" if tactic != "UNKNOWN" else ("CONFLICTING_EVIDENCE" if positive and risks else "AMBIGUOUS_OR_MISSING_STRUCTURE")}


def select_samples(frame: Any, external_codes: set[str], *, validation_cap: int = 1000) -> Any:
    """One row per class/structural episode, disjoint securities and time.

    Sampling uses a key hash only, never probabilities/metrics. No train cap;
    training uses every deduplicated known eligible training-security episode.
    """
    import pandas as pd
    out = frame.loc[frame.tactic.isin(CLASSES) & frame.feature_ready & ~frame.ts_code.isin(external_codes)].copy()
    out["security_group"] = out.ts_code.map(security_group)
    out["split"] = "coverage_only"
    out.loc[out.trade_date.between(START, TRAIN_END) & out.security_group.eq("train"), "split"] = "train"
    out.loc[out.trade_date.between(VALID_START, END) & out.security_group.eq("validation"), "split"] = "validation"
    out = out.loc[out.split.ne("coverage_only")].sort_values(["trade_date", "ts_code"], kind="mergesort")
    out = out.drop_duplicates(["split", "tactic", "episode_id"], keep="first")
    out["sample_key"] = [digest([c, d, e]) for c, d, e in zip(out.ts_code, out.trade_date, out.episode_id)]
    train = out.loc[out.split.eq("train")]
    validation = out.loc[out.split.eq("validation")].sort_values("sample_key").groupby("tactic", sort=False).head(validation_cap)
    result = pd.concat([train, validation], ignore_index=True)
    if set(train.ts_code) & set(validation.ts_code) or set(train.episode_id) & set(validation.episode_id):
        raise ContractError("CROSSING_SECURITY_OR_EPISODE")
    return result


def model_factory(name: str) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if name not in MODEL_NAMES:
        raise ContractError("UNAUTHORIZED_MODEL")
    if name.endswith("lr"):
        return make_pipeline(StandardScaler(), LogisticRegression(**LR_CONFIG))
    return HistGradientBoostingClassifier(**HGB_CONFIG)


def load_weight(path: Path) -> Any:
    """Narrow upstream NumPy 2.5/joblib compatibility warning only."""
    import joblib
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Setting the shape on a NumPy array has been deprecated.*", category=DeprecationWarning, module="joblib.numpy_pickle")
        return joblib.load(path)


def fit_four(samples: Any, output: Path, identity: dict[str, Any], *, factory: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Durable pre-fit reservation; an uncertain/incomplete fit cannot repeat.

    Identical complete checkpoints reload and verify replay. A crash after a fit
    but before its completion receipt is deliberately fail-closed for controller
    adjudication, so there is never a silent fifth fit.
    """
    import joblib
    import numpy as np
    train = samples.loc[samples.split.eq("train")].sort_values(["ts_code", "trade_date", "episode_id"])
    if set(train.tactic) != set(CLASSES):
        raise ContractError(f"TRAIN_CLASS_MISSING:{sorted(set(CLASSES)-set(train.tactic))}")
    x = train.loc[:, list(FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(x).all():
        raise ContractError("NONFINITE_TRAIN_FEATURE")
    key = digest({"identity": identity, "code": sha(Path(__file__)), "features": FEATURES,
                  "training": hashlib.sha256(train[["ts_code", "trade_date", "episode_id", "tactic", *FEATURES]].to_csv(index=False).encode()).hexdigest()})
    ledger_path = output/"fit_ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        if ledger["fit_identity"] != key:
            raise ContractError("FIT_IDENTITY_CHANGED_NO_REFIT")
    else:
        ledger = {"schema": SCHEMA, "fit_identity": key, "S": 0, "B": 0, "tuning": 0,
                  "primary": PRIMARY, "models": {}, "identity": identity, "features": FEATURE_UNITS,
                  "model_config": {"lr": LR_CONFIG, "hgb": HGB_CONFIG, "lr_scaler": "StandardScaler fit TRAIN only"}, **FLAGS}
        write_json(ledger_path, ledger)
    models = {}
    factory = factory or model_factory
    for name in MODEL_NAMES:
        path = output/f"{name}.joblib"
        previous = ledger["models"].get(name)
        y = (train.s_label.eq("TRUE").astype(int).to_numpy() if name.startswith("binary")
             else train.tactic.map({c: i for i, c in enumerate(CLASSES)}).to_numpy(dtype=int))
        replay_x = x[:min(128, len(x))]
        if previous:
            if previous["state"] != "COMPLETE" or not path.is_file() or sha(path) != previous["weight_sha256"]:
                raise ContractError(f"UNCERTAIN_FIT_DO_NOT_REPEAT:{name}")
            model = load_weight(path)
        else:
            if path.exists():
                raise ContractError(f"UNRECEIPTED_WEIGHT:{name}")
            ledger["models"][name] = {"state": "RESERVED", "n": len(y)}
            ledger["S"] += 1
            write_json(ledger_path, ledger)
            model = factory(name)
            model.fit(x, y)
            joblib.dump(model, path)
            before = model.predict_proba(replay_x)
            model = load_weight(path)
            if not np.array_equal(before, model.predict_proba(replay_x)):
                raise ContractError(f"RELOAD_REPLAY_MISMATCH:{name}")
            ledger["models"][name] = {"state": "COMPLETE", "n": len(y), "weight_sha256": sha(path),
                                      "classes": [int(c) for c in model.classes_],
                                      "replay_sha256": hashlib.sha256(before.tobytes()).hexdigest()}
            write_json(ledger_path, ledger)
        if hashlib.sha256(model.predict_proba(replay_x).tobytes()).hexdigest() != ledger["models"][name]["replay_sha256"]:
            raise ContractError(f"REPLAY_CHANGED:{name}")
        models[name] = model
    if ledger["S"] != 4 or ledger["B"] != 0 or len(models) != 4:
        raise ContractError("FOUR_S_ZERO_B_FIT_MISMATCH")
    return models, ledger


def predict(frame: Any, models: dict[str, Any]) -> Any:
    import numpy as np
    out = frame.copy()
    if not len(out):
        return out
    x = out.loc[:, list(FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(x).all():
        raise ContractError("NONFINITE_PREDICTION_INPUT")
    for name, model in models.items():
        p = model.predict_proba(x)
        expected = [0, 1] if name.startswith("binary") else list(range(4))
        if list(model.classes_) != expected:
            raise ContractError(f"MODEL_CLASS_ORDER:{name}")
        if name.startswith("binary"):
            out[f"p_{name}"] = p[:, 1]
            out[f"pred_{name}"] = (p[:, 1] >= .5).astype(int)
        else:
            for i, c in enumerate(CLASSES):
                out[f"p_{name}_{c}"] = p[:, i]
            out[f"pred_{name}"] = [CLASSES[i] for i in np.argmax(p, axis=1)]
    return out


def metrics(predictions: Any) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, roc_auc_score
    result = {}
    for name in MODEL_NAMES:
        binary = name.startswith("binary")
        known = predictions.s_label.isin(["TRUE", "FALSE"]) if binary else predictions.tactic.isin(CLASSES)
        part = predictions.loc[known]
        if not len(part) or f"pred_{name}" not in part:
            result[name] = {"n": 0, "status": "CANNOT_CONFIRM"}
            continue
        y = part.s_label.eq("TRUE").astype(int) if binary else part.tactic
        yp = part[f"pred_{name}"]
        labels = [0, 1] if binary else list(CLASSES)
        entry = {"n": len(part), "labels": labels, "confusion_matrix": confusion_matrix(y, yp, labels=labels).tolist(),
                 "accuracy": float(accuracy_score(y, yp)), "macro_f1": float(f1_score(y, yp, labels=labels, average="macro", zero_division=0))}
        if binary:
            entry["auc"] = float(roc_auc_score(y, part[f"p_{name}"])) if y.nunique() == 2 else None
        result[name] = entry
    return result


def read_external_cases(path: Path) -> Any:
    import pandas as pd
    cases = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not REQUIRED_EXTERNAL.issubset(cases.columns):
        raise ContractError(f"EXTERNAL_HEADERS:{sorted(REQUIRED_EXTERNAL-set(cases.columns))}")
    if cases.duplicated(["source", "case_id"]).any():
        raise ContractError("DUPLICATE_EXTERNAL_ID")
    for name in ("ts_code", "trade_date"):
        parser = v12._code if name == "ts_code" else lambda d: v12._day(d, "external_date")
        cases[name] = [parser(x) if x.strip() else "" for x in cases[name]]
    cases["s_label"] = cases.s_label.str.upper()
    if not cases.s_label.isin(["TRUE", "FALSE", "UNKNOWN", "EXCLUDED"]).all():
        raise ContractError("INVALID_EXTERNAL_LABEL")
    return cases


def read_external_symbol(panel: Path, code: str, dates: list[str]) -> Any:
    """Small per-security logical read with bounded prehistory; no new source."""
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel)
    actual = {x.lower(): x for x in schema.names}
    mapping = {s: next((actual[a] for a in v12.ALIASES[s] if a in actual), None) for s in INPUTS}
    if not all(mapping.values()):
        raise ContractError("EXTERNAL_REQUIRED_COLUMN_MISSING")
    lower = (datetime.strptime(min(dates), "%Y%m%d")-timedelta(days=400)).strftime("%Y%m%d")
    filters = [(mapping["ts_code"], "=", code),
               (mapping["trade_date"], ">=", v12._arrow_date_value(schema, mapping["trade_date"], lower)),
               (mapping["trade_date"], "<=", v12._arrow_date_value(schema, mapping["trade_date"], max(dates)))]
    frame = parquet.read_table(panel, columns=list(mapping.values()), filters=filters).to_pandas().rename(columns={v:k for k,v in mapping.items()})
    return frame


def external_inference(cases: Any, panel: Path, models: dict[str, Any], *, reader: Any = None) -> Any:
    import pandas as pd
    reader = reader or read_external_symbol
    results = []
    lookup = {}
    for code, group in cases.loc[cases.ts_code.ne("") & cases.trade_date.ne("")].groupby("ts_code", sort=True):
        dates = sorted(group.trade_date.unique())
        frame = reader(panel, code, dates)
        if len(frame):
            shapes = causal_shapes(frame, start=min(dates), end=max(dates))
            lookup.update({(code, row["trade_date"]): row for row in shapes.to_dict("records") if row["trade_date"] in dates})
    for case in cases.to_dict("records"):
        row = dict(case)
        evidence = lookup.get((case["ts_code"], case["trade_date"]))
        if case["s_label"] == "EXCLUDED":
            row["prediction_status"] = "EXCLUDED_BY_ADJUDICATED_REFERENCE"
        elif not case["trade_date"]:
            row["prediction_status"] = "UNKNOWN_DATE_NO_SUBSTITUTE"
        elif not case["ts_code"]:
            row["prediction_status"] = "UNKNOWN_SECURITY"
        elif evidence is None:
            row["prediction_status"] = "EXACT_D_NOT_IN_BOUND_PANEL"
        elif not evidence["feature_ready"]:
            row["prediction_status"] = "MISSING_CAUSAL_HISTORY"
        else:
            p = predict(pd.DataFrame([evidence]), models).iloc[0]
            row.update({k: p[k] for k in p.index if k.startswith(("p_", "pred_"))})
            row.update(prediction_status="PREDICTED", mined_tactic=evidence["tactic"], mined_episode_id=evidence["episode_id"],
                       shape_counterevidence=evidence["counterevidence"], shape_positive_evidence=evidence["positive_evidence"])
        results.append(row)
    return pd.DataFrame(results)


def compact_shapes(frame: Any) -> Any:
    columns = ["ts_code", "trade_date", "market_type", "tactic", "s_label", "episode_id", "feature_ready",
               "anchor_date", "anchor_low", "repair_date", "damage_date", "damage_age", "repair_high", "repair_midpoint", "white_below_observations", "anchor_failed", "repair_failed",
               "g1_evidence", "g2_evidence", "support_held", "compressed_evidence", "compact_prior_evidence", "active_damage",
               "post_repair_consolidation", "positive_evidence", "counterevidence", "unknown_reason", "recent_positive",
               "prior_expansion_count", "prior_expansion_nonbull", *FEATURES]
    return frame.loc[:, list(dict.fromkeys(columns))]


def cohorts(raw: Any, size: int = 256):
    import numpy as np
    if not 1 <= size <= 256:
        raise ContractError("COHORT_MUST_BE_1_TO_256")
    codes = raw.ts_code.to_numpy()
    edges = np.r_[0, np.flatnonzero(codes[1:] != codes[:-1])+1, len(raw)]
    for first in range(0, len(edges)-1, size):
        yield raw.iloc[edges[first]:edges[min(first+size, len(edges)-1)]]


def census(frame: Any) -> Any:
    out = frame.assign(rows=1, valid_causal_d=frame.valid_bar.astype(int), eligible_rule_universe=(frame.feature_ready & frame.g1_evidence & ~frame.g2_evidence).astype(int), known=frame.tactic.isin(CLASSES).astype(int), unknown=frame.tactic.eq("UNKNOWN").astype(int),
                       feature_ready_n=frame.feature_ready.astype(int), g1_n=frame.g1_evidence.astype(int), g2_n=frame.g2_evidence.astype(int))
    for c in CLASSES:
        out[c] = frame.tactic.eq(c).astype(int)
    return out.groupby(["trade_date", "market_type"], observed=True)[["rows", "valid_causal_d", "eligible_rule_universe", "known", "unknown", "feature_ready_n", "g1_n", "g2_n", *CLASSES]].sum().reset_index()


def prepare(raw: Any, cases: Any, output: Path) -> tuple[Any, Any, Any]:
    import pandas as pd
    samples, counts, oos = [], [], []
    excluded = set(cases.ts_code)-{""}
    for i, block in enumerate(cohorts(raw)):
        shape = causal_shapes(block)
        if not len(shape):
            continue
        counts.append(census(shape))
        oos.append(compact_shapes(shape.loc[shape.trade_date.ge(VALID_START) & shape.feature_ready]))
        # Early per-episode reduction bounds memory; final selection performs
        # the global deterministic per-class validation cap.
        known = compact_shapes(shape.loc[shape.tactic.isin(CLASSES)])
        samples.append(select_samples(known, excluded, validation_cap=1000))
        print(json.dumps({"stage": "causal_labels", "cohort": i+1, "symbols": block.ts_code.nunique(), "rows": len(shape)}), flush=True)
    if not samples:
        raise ContractError("NO_KNOWN_LABELS")
    all_samples = pd.concat(samples, ignore_index=True)
    # Re-apply cap globally, preserving the same fixed membership and hash order.
    selected = select_samples(all_samples, excluded)
    daily = pd.concat(counts).groupby(["trade_date", "market_type"], observed=True).sum(numeric_only=True).reset_index()
    selected.to_csv(output/"labels.csv", index=False)
    daily.to_csv(output/"source_census_daily.csv", index=False)
    daily.assign(month=daily.trade_date.str[:6]).drop(columns="trade_date").groupby(["month", "market_type"], observed=True).sum(numeric_only=True).to_csv(output/"source_census_monthly.csv")
    return selected, daily, pd.concat(oos, ignore_index=True)


def oos_coverage(projection: Any, models: dict[str, Any], external_codes: set[str], daily: Any) -> Any:
    """Score the reused RAM-only OOS projection, retain compact daily counts.

    UNKNOWN rows and exposed-reference codes remain in coverage denominators.
    They are never silently relabelled or used as supervised validation.
    """
    import pandas as pd
    aggregate = []
    for first in range(0, len(projection), 100000):
        scored = predict(projection.iloc[first:first+100000], models)
        scored["scored_rows"] = 1
        scored["external_reference_rows"] = scored.ts_code.isin(external_codes).astype(int)
        scored["unknown_structure_rows"] = scored.tactic.eq("UNKNOWN").astype(int)
        scored["heldout_security_rows"] = scored.ts_code.map(security_group).eq("validation").astype(int)
        columns = ["scored_rows", "external_reference_rows", "unknown_structure_rows", "heldout_security_rows"]
        for name in MODEL_NAMES:
            if name.startswith("binary"):
                column = f"positive_{name}"
                scored[column] = scored[f"pred_{name}"]
                columns.append(column)
            else:
                for c in CLASSES:
                    column = f"positive_{name}_{c}"
                    scored[column] = scored[f"pred_{name}"].eq(c).astype(int)
                    columns.append(column)
        aggregate.append(scored.groupby(["trade_date", "market_type"], observed=True)[columns].sum().reset_index())
    baseline = daily.loc[daily.trade_date.ge(VALID_START)].copy()
    if aggregate:
        scores = pd.concat(aggregate).groupby(["trade_date", "market_type"], observed=True).sum(numeric_only=True).reset_index()
        baseline = baseline.merge(scores, on=["trade_date", "market_type"], how="left", validate="one_to_one")
        for column in scores.columns.difference(["trade_date", "market_type"]):
            baseline[column] = baseline[column].fillna(0).astype(int)
    else:
        baseline["scored_rows"] = 0
    baseline["no_score_rows"] = baseline.rows-baseline.scored_rows
    return baseline


def resource_snapshot() -> dict[str, Any]:
    import shutil
    import subprocess
    result = {"logical_cpus": os.cpu_count(), "output_budget_bytes": 1024**3, "cohort_max": 256, "threads": min(12, max(1, (os.cpu_count() or 2)-4))}
    try:
        import psutil
        vm = psutil.virtual_memory()
        result.update(memory_bytes=vm.total, available_memory_bytes=vm.available)
    except ImportError:
        result["available_memory_bytes"] = "CANNOT_CONFIRM"
    if sys.platform == "darwin":
        result["memory_pressure"] = subprocess.run(["/usr/bin/memory_pressure", "-Q"], capture_output=True, text=True, check=False).stdout[-1000:]
    result["source_free_bytes"] = shutil.disk_usage(APP_ROOT).free
    return result


def run(data_root: Path, output: Path, external_path: Path) -> dict[str, Any]:
    import pandas as pd
    from threadpoolctl import threadpool_limits
    output = output.resolve()
    authority = data_root.resolve()
    if output == authority or authority in output.parents:
        raise ContractError("OUTPUT_INSIDE_AUTHORITY")
    output.mkdir(parents=True, exist_ok=True)
    import shutil
    if shutil.disk_usage(output).free < 2*1024**3:
        raise ContractError("INSUFFICIENT_OUTPUT_BUDGET")
    lock = output/"run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractError("RUN_LOCK_EXISTS_NO_DUPLICATE_RUN") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        resources = resource_snapshot()
        cases = read_external_cases(external_path)
        with v12.bind_current_panels(data_root) as (panel, source, recheck):
            if source.get("generation_id") != GENERATION or str(source.get("asof_date")) != END:
                raise ContractError("FROZEN_SOURCE_IDENTITY_MISMATCH")
            write_json(output/"run_identity.json", {"schema": SCHEMA, "source": source, "signed_doc": SIGNED_DOC,
                       "external_sha256": sha(external_path), "source_sha256": sha(Path(__file__)), "resources": resources,
                       "model_primary": PRIMARY, "thresholds": {"binary": .5, "multiclass": "argmax_fixed_class_order"},
                       "label_semantics": LABEL_SCOPE, "unknown_in_training": False,
                       "split": "TRAIN 20241101..20260831 hash(code)%5!=0; validation 20260901..20261120 hash(code)%5==0; all external codes excluded both",
                       "economic_evaluation": "NOT_RUN", "full_panel_disk_writes": 0, **FLAGS})
            raw, read_meta = base.read_projected(panel)
            raw = raw.loc[:, list(INPUTS)]
            samples, daily, oos = prepare(raw, cases, output)
            del raw
            identity = {"generation": GENERATION, "source": source, "external_sha256": sha(external_path)}
            with threadpool_limits(limits=resources["threads"]):
                models, fit = fit_four(samples, output, identity)
                validation = predict(samples.loc[samples.split.eq("validation")], models)
                validation.to_csv(output/"validation_predictions.csv", index=False)
                external = external_inference(cases, panel, models)
                external.to_csv(output/"external_predictions.csv", index=False)
                coverage = oos_coverage(oos, models, set(cases.ts_code)-{""}, daily)
                coverage.to_csv(output/"coverage_oos_daily.csv", index=False)
            rechecked = recheck()
            if rechecked is False:
                raise ContractError("SOURCE_CHANGED_DURING_RUN")
            # Group metrics preserve external corpus + supplied split; exposed
            # references never become an unseen validation claim.
            external_metrics = {}
            for key, group in external.loc[external.prediction_status.eq("PREDICTED")].groupby(["source", "split"], dropna=False):
                external_metrics["/".join(key)] = metrics(group)
            summary = {"schema": SCHEMA, "source": source, "source_recheck": "PASS_NO_EXCEPTION",
                       "read_metadata": read_meta, "resources": resources, "actual_fit": {"S": fit["S"], "B": fit["B"], "tuning": 0},
                       "primary": PRIMARY, "feature_units": FEATURE_UNITS, "class_order": CLASSES, "label_scope": LABEL_SCOPE,
                       "sample_counts": samples.groupby(["split", "tactic"]).size().to_dict(),
                       "internal_validation": metrics(validation), "external_exposed_reference": external_metrics,
                       "external_status_counts": external.prediction_status.value_counts().to_dict(),
                       "census_trade_dates": int(daily.trade_date.nunique()), "census_rows": int(daily.rows.sum()),
                       "oos_coverage_trade_dates": int(coverage.trade_date.nunique()) if len(coverage) else 0,
                       "labels_are_weak_structure_proxies": True, "economic_evaluation": "NOT_RUN", **FLAGS}
            summary["sample_counts"] = {"/".join(k): int(v) for k,v in summary["sample_counts"].items()}
            used = sum(p.stat().st_size for p in output.iterdir() if p.is_file())
            if used > 1024**3:
                raise ContractError("OUTPUT_BUDGET_EXCEEDED")
            summary["artifact_bytes"] = used
            summary["artifacts"] = {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in output.iterdir() if p.is_file() and p.name not in {"run.lock", "summary.json"}}
            write_json(output/"summary.json", summary)
            return summary
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--external-cases", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="explicitly run the authorized 4-fit research study")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute required; importing or help never fits")
    try:
        summary = run(args.data_root, args.output_dir, args.external_cases)
        print(json.dumps({"status": "COMPLETE_RESEARCH_ONLY", "actual_fit": summary["actual_fit"]}))
        return 0
    except (ContractError, v12.StudyError, OSError, ValueError) as exc:
        print(f"ACT020_S_V2_FAILED:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
