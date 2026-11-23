"""ACT-024 fixed abstention router over ACT-023's frozen 43-d HGB pair.

Inference only: no fitting, threshold search, MultiRocket execution/weights,
backtest, authority writes or panel copies. All thresholds below are fixed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act023_s_v3 as act023

old, review = act023.old, act023.review
ContractError = act023.ContractError
SCHEMA = "pft_act024_s_v3_router.v1"
ARTIFACT_ROOT = Path("/Users/lexi/Desktop/学习/v4_app/artifacts")
OUTPUT = ARTIFACT_ROOT/"pft_act024_s_v3_20261123/run"
EXTERNAL_SHA = "6335f87238c649ef64c9bc3c0300ab4f726b9f328c525783a5f385ff7633f45e"
GROUPS_SHA = "bdf578efad5facf2ce8249abff8c778c11f0e879bd78473e8d0af6a86d320ea6"
PLAN_SHA = "cf8c53b0e5270e05fbe313f9fc8e4530722019dbeba864cc4cae47e235be806c"
PREPARED_SHA = "ef79cdba215240ba637292312f412fd798bf94a23ac63b115b94453d71d4ffa5"
LEDGER_SHA = "37333524aae0f006b8e65446424ed9144edfe7353b068ef8112411a8bb003e4e"
SOURCE_SHA = "e166a194db9fa3f90799675c6632446ca5e66b830d5a6c925ba81f7747d48859"
WEIGHTS = {
    "structure_ch_binary": "c8821df307cced5dd95e640c1c00e5918d84a17df923a657e710001134eab783",
    "structure_ch_tactic": "1f2d1817fceb841fad7ec25a891428f0da59246df757a8d2cdec6fe7876e4390",
}
DAYS = ("20261116", "20261117", "20261118", "20261119", "20261120")
POLICY = {
    "g1": "finite positive observed W<Y wins even without model context; equality is not failure",
    "yellow_extension": "UNKNOWN iff >0.35; missing/nonfinite fails safe",
    "line_spread": "(W-Y)/Y; UNKNOWN iff <0.015",
    "raw_head_disagreement": "(raw_p_s>=0.5) != (four-way argmax in positive classes)",
    "strong_head_disagreement": "add distinct reason iff raw_p_s>=0.70 AND p_invalid_fake>=0.50",
    "grey_band": "UNKNOWN iff 0.35<=projected_p_s<0.65",
    "otherwise": "retain ACT023 coherent state and tactic exactly",
    "projection": "ACT023 max(binary S, three positive children); children unchanged",
    "unknown_tactic": "empty; UNKNOWN is never a forced negative",
    "readiness": "ACT023 feature_ready and 65 exact valid causal bars, same 400-calendar-day prefix",
    "retired_arm": "no MultiRocket execution or weight loading; historical CSV bytes preserved separately",
    "actual_fit": {"S": 0, "B": 0, "tuning": 0},
}


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def route(root: Any, children: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    """Deterministic abstention, independent of identity, truth and other rows."""
    import numpy as np
    root = finite(root)
    try:
        p = np.asarray(children, dtype=float)
        valid = bool(p.shape == (4,) and np.isfinite(p).all() and (p >= 0).all()
                     and (p <= 1).all() and np.isclose(p.sum(), 1)
                     and root is not None and 0 <= root <= 1)
    except (TypeError, ValueError):
        p, valid = np.array([]), False
    w, y = finite(evidence.get("white")), finite(evidence.get("yellow"))
    observed = w is not None and y is not None and w > 0 and y > 0
    strict = bool(observed and w < y)
    spread = (w-y)/y if observed else None
    extension = finite(evidence.get("yellow_extension"))
    # Coherent is reused only when its probability contract is satisfied.
    base = act023.coherent(root, p, {"white": w, "yellow": y}) if valid else {}
    result = {
        "raw_p_s": root, **{f"raw_p_{c}": float(p[i]) if valid else None for i,c in enumerate(old.CLASSES)},
        "projected_p_s": base.get("projected_p_s"),
        **{f"projected_p_{c}": base.get(f"projected_p_{c}") for c in old.CLASSES[:3]},
        "projected_p_fake": base.get("projected_p_fake"),
        "line_spread": spread, "yellow_extension": extension,
        "strict_g1_failure": strict, "line_evidence_observed": observed,
        "raw_hierarchy_contradiction": base.get("raw_hierarchy_contradiction"),
        "raw_decision_contradiction": base.get("raw_decision_contradiction"),
        "final_hierarchy_contradiction": base.get("final_hierarchy_contradiction"),
        "base_final_state": base.get("final_state", "REJECTED_FAKE" if strict else "UNKNOWN_BORDERLINE"),
        "base_main_tactic": base.get("main_tactic", "invalid_fake" if strict else ""),
        "base_decision_reason": base.get("decision_reason", evidence.get("status", "MISSING_MODEL_CONTEXT")),
    }
    reasons = []
    if strict:
        state, tactic = "REJECTED_FAKE", "invalid_fake"
        reasons = ["STRICT_OBSERVED_W_BELOW_Y"]
    else:
        if not observed:
            reasons.append("MISSING_LINE_EVIDENCE")
        if evidence.get("status") != "READY":
            reasons.append("MISSING_MODEL_CONTEXT")
        if not valid:
            reasons.append("MISSING_OR_INVALID_MODEL_SCORES")
        if extension is None:
            reasons.append("MISSING_YELLOW_EXTENSION")
        elif extension > .35:
            reasons.append("YELLOW_EXTENSION_GT_035")
        if spread is not None and spread < .015:
            reasons.append("LINE_SPREAD_LT_0015")
        if valid:
            if base["raw_decision_contradiction"]:
                reasons.append("RAW_HEAD_DECISION_CONTRADICTION")
            if root >= .70 and p[3] >= .50:
                reasons.append("STRONG_BINARY_FAKE_HEAD_CONTRADICTION")
            if .35 <= base["projected_p_s"] < .65:
                reasons.append("PROJECTED_S_GREY_035_065")
        state = "UNKNOWN_BORDERLINE" if reasons else base["final_state"]
        tactic = "" if state == "UNKNOWN_BORDERLINE" else base["main_tactic"]
        if not reasons:
            reasons.append(base["decision_reason"])
    result.update(final_state=state, main_tactic=tactic,
                  route_reasons=";".join(dict.fromkeys(reasons)),
                  final_decision_contradiction=bool(state == "CONFIRMED_S" and (strict or tactic not in old.CLASSES[:3])))
    return result


def checked(path: Path, expected: str) -> Path:
    if act023.sha(path) != expected:
        raise ContractError(f"FROZEN_INPUT_SHA_CHANGED:{path.name}")
    return path


def load_frozen(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load exactly two structure weights, never a fitter or retired arm."""
    import numpy as np
    checked(Path(act023.__file__), SOURCE_SHA)
    plan = json.loads(checked(directory/"frozen_plan.json", PLAN_SHA).read_text())
    prepared = json.loads(checked(directory/"prepared.json", PREPARED_SHA).read_text())
    ledger = json.loads(checked(directory/"fit_ledger.json", LEDGER_SHA).read_text())
    if (plan["features"] != list(act023.STRUCT_FEATURES) or len(plan["features"]) != 43
            or plan["class_order"] != list(old.CLASSES) or plan["cutoff"] != "20260831"
            or plan["code_sha256"] != SOURCE_SHA or plan["groups_sha256"] != GROUPS_SHA
            or plan["hgb_config"] != old.HGB_CONFIG
            or ledger["config"] != old.HGB_CONFIG
            or [ledger.get(k) for k in ("S", "B", "tuning", "transform_fit")] != [4, 0, 0, 0]
            or set(ledger["models"]) != set(act023.MODELS)
            or any(v.get("state") != "COMPLETE" for v in ledger["models"].values())):
        raise ContractError("FROZEN_PLAN_FEATURE_CLASS_CUTOFF_OR_COMPLETE_LEDGER")
    for module, key in ((old, "act020_source_sha256"), (review, "act021_source_sha256")):
        checked(Path(module.__file__), plan[key])
    # Verify only the consumed projections; numpy lazily opens named members.
    for name in ("features.npz", "external_keys.csv", "external_evidence.json", "training_membership.csv"):
        checked(directory/name, prepared["files"][name])
    models = {}
    with np.load(directory/"features.npz", allow_pickle=False) as arrays:
        x = arrays["train_structure"]
        if x.shape != (4000, 43) or np.isinf(x).any() or not np.isfinite(x[:, :len(old.FEATURES)]).all():
            raise ContractError("FROZEN_TRAIN_STRUCTURE_SHAPE")
        for name, expected in WEIGHTS.items():
            state = ledger["models"][name]
            if state["weight_sha256"] != expected or state["features"] != 43 or state["rows"] != 4000:
                raise ContractError("STRUCTURE_WEIGHT_LEDGER_MISMATCH")
            model = old.load_weight(checked(directory/f"{name}.joblib", expected))
            classes = [0, 1] if name.endswith("binary") else [0, 1, 2, 3]
            if list(model.classes_) != classes or state["classes"] != classes or model.n_features_in_ != 43:
                raise ContractError("STRUCTURE_MODEL_FEATURE_OR_CLASS_ORDER")
            replay = model.predict_proba(x[:128])
            if hashlib.sha256(replay.tobytes()).hexdigest() != state["replay_sha256"]:
                raise ContractError(f"FROZEN_STRUCTURE_REPLAY:{name}")
            models[name.rsplit("_", 1)[1]] = model
    return models, {"plan_sha256": PLAN_SHA, "prepared_sha256": PREPARED_SHA,
                    "fit_ledger_sha256": LEDGER_SHA, "weights_sha256": WEIGHTS,
                    "feature_order": list(act023.STRUCT_FEATURES), "class_order": list(old.CLASSES),
                    "cutoff": plan["cutoff"], "training_replay": "PASS_128_EACH_STRUCTURE_HEAD"}


def batch_predict(models: dict[str, Any], x: Any, evidence: list[dict[str, Any]]) -> dict[int, tuple[float, Any]]:
    import numpy as np
    ready = [i for i,e in enumerate(evidence) if e["status"] == "READY"]
    if not ready:
        return {}
    values = np.asarray(x)[ready]
    if values.shape != (len(ready), 43) or np.isinf(values).any() or not np.isfinite(values[:, :len(old.FEATURES)]).all():
        raise ContractError("READY_STRUCTURE_FEATURE_CONTRACT")
    binary, tactic = models["binary"].predict_proba(values), models["tactic"].predict_proba(values)
    return {i: (float(binary[j, 1]), tactic[j]) for j,i in enumerate(ready)}


def extract_structure(raw: Any, day: str, codes: list[str]) -> tuple[Any, list[dict[str, Any]]]:
    """ACT023 prefix/65-bar readiness, without calling its MR-bearing extract."""
    import numpy as np
    shaped = old.causal_shapes(raw, start=day, end=day)
    shapes = {r["ts_code"]: r for r in shaped.to_dict("records")}
    by_code = {code: part.reset_index(drop=True) for code,part in raw.groupby("ts_code", sort=False)}
    x = np.full((len(codes), 43), np.nan)
    evidence = []
    for i,code in enumerate(codes):
        context = by_code.get(code, raw.iloc[:0])
        exact = context.loc[context.trade_date.eq(day)]
        e = {"ts_code": code, "trade_date": day, "status": "EXACT_D_NOT_IN_BOUND_PANEL"}
        if len(exact) == 1:
            e.update(white=exact.iloc[0].zge_white_line, yellow=exact.iloc[0].zge_yellow_line)
        shape = shapes.get(code)
        if shape and not shape["feature_ready"]:
            e["status"] = "MISSING_CAUSAL_CONTEXT"
        elif shape:
            if len(context) < 65 or not all(review.valid_bar(r) for r in context.tail(65).to_dict("records")):
                e["status"] = "MISSING_65_VALID_CAUSAL_BARS"
            else:
                x[i], audit = act023.structural_features(context, shape)
                e.update(audit, status="READY", context_start=min(context.trade_date),
                         context_end=max(context.trade_date), causal_bars=len(context))
        evidence.append(e)
    return x, evidence


def score_row(root: Any, children: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    result = route(root, children, evidence)
    return {f"act024_{key}": value for key,value in result.items()}


def reroute_external(path: Path, directory: Path, models: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    import pandas as pd
    checked(path, EXTERNAL_SHA)
    original = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if (len(original) != 93 or original.duplicated(["cohort", "case_id"]).any()
            or original.cohort.value_counts().to_dict() != {"GOLD40": 40, "ANCHOR20": 20, "COMMON61": 33}):
        raise ContractError("FROZEN_93_CASE_IDENTITY")
    keys = pd.read_csv(directory/"external_keys.csv", dtype=str, keep_default_na=False)
    evidence = json.loads((directory/"external_evidence.json").read_text())
    with np.load(directory/"features.npz", allow_pickle=False) as arrays:
        scores = batch_predict(models, arrays["external_structure"], evidence)
    if len(keys) != len(evidence) or keys.duplicated(["ts_code", "trade_date"]).any():
        raise ContractError("FROZEN_EXTERNAL_KEY_OR_EVIDENCE_CONTRACT")
    lookup = {(row.ts_code,row.trade_date): i for i,row in keys.iterrows()}
    added = []
    for _,row in original.iterrows():
        i = lookup[(row.ts_code, row.trade_date)]
        e = evidence[i]
        root = finite(row.structure_ch_raw_p_s)
        children = [finite(row[f"structure_ch_raw_p_{c}"]) for c in old.CLASSES]
        if i in scores:
            expected_root, expected_children = scores[i]
            if not np.allclose([root, *children], [expected_root, *expected_children], rtol=0, atol=1e-14):
                raise ContractError(f"EXTERNAL_FROZEN_SCORE_REPLAY:{row.case_id}")
        elif root is not None or any(v is not None for v in children):
            raise ContractError("NONREADY_EXTERNAL_HAS_STRUCTURE_SCORES")
        result = score_row(root, children, e)
        # Original coherent decisions are the frozen pre-router comparator.
        if (result["act024_base_final_state"] != row.structure_ch_final_state
                or result["act024_base_main_tactic"] != row.structure_ch_main_tactic
                or (root is not None and not np.isclose(result["act024_projected_p_s"], float(row.structure_ch_projected_p_s), rtol=0, atol=1e-14))):
            raise ContractError(f"EXTERNAL_FROZEN_COHERENT_REPLAY:{row.case_id}")
        added.append(result)
    # Retired MR history remains byte-exact at path; current export omits it.
    retained = original.loc[:, ~original.columns.str.startswith("structure_mr_ch_")].copy()
    return pd.concat([retained.reset_index(drop=True), pd.DataFrame(added)], axis=1), {
        "input_sha256": EXTERNAL_SHA, "n": len(original), "unique_code_dates": len(keys),
        "raw_and_projected_score_replay": "PASS_1E-14", "coherent_state_tactic_replay": "PASS",
        "preserved_columns": retained.columns.tolist(), "retired_columns_dropped": [c for c in original if c.startswith("structure_mr_ch_")],
    }


def counts(frame: Any, column: str) -> dict[str, Any]:
    n = len(frame)
    states = {s: int(frame[column].eq(s).sum()) for s in ("CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE")}
    if sum(states.values()) != n:
        raise ContractError(f"STATE_ENUM_OR_COVERAGE:{column}")
    return {"n": n, "states": states, "rejection_rate": states["REJECTED_FAKE"]/n if n else None,
            "unknown_rate": states["UNKNOWN_BORDERLINE"]/n if n else None}


def external_metrics(frame: Any) -> dict[str, Any]:
    """Known-positive recall plus abstention bound; truth UNKNOWN stays separate."""
    result = {}
    for name,part in [("ALL", frame), *list(frame.groupby("cohort", sort=True))]:
        cohort = {"n": len(part), "truth_state_counts": part.truth_state.value_counts().to_dict(), "arms": {}}
        positive, fake, boundary = (part.truth_state.eq(s) for s in ("CONFIRMED_S", "REJECTED_FAKE", "UNKNOWN_BORDERLINE"))
        for arm in ("baseline", "structure_ch", "act024"):
            column = f"{arm}_final_state"
            state = part[column]
            p, f = int(positive.sum()), int(fake.sum())
            tp = int((positive & state.eq("CONFIRMED_S")).sum())
            pu = int((positive & state.eq("UNKNOWN_BORDERLINE")).sum())
            fp = int((fake & state.eq("CONFIRMED_S")).sum())
            entry = {**counts(part, column), "known_positive_n": p, "true_positive_n": tp,
                     "positive_abstained_n": pu, "false_reject_n": int((positive & state.eq("REJECTED_FAKE")).sum()),
                     "known_fake_n": f, "false_accept_n": fp, "false_positive_rate_known_fake": fp/f if f else None,
                     "confirmed_s_recall": tp/p if p else None,
                     "nonrejected_positive_recall_upper_bound": (tp+pu)/p if p else None,
                     "boundary_forced_accept_n": int((boundary & state.eq("CONFIRMED_S")).sum()),
                     "boundary_forced_reject_n": int((boundary & state.eq("REJECTED_FAKE")).sum()),
                     "boundary_abstained_n": int((boundary & state.eq("UNKNOWN_BORDERLINE")).sum())}
            cohort["arms"][arm] = entry
        cohort["recall_interpretation"] = "Router only abstains; nonrejected bound is not confirmed recall or a recovered positive."
        result[name] = cohort
    return result


def scan_groups(path: Path, directory: Path, models: dict[str, Any], external: Any) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    import pandas as pd
    checked(path, GROUPS_SHA)
    groups, identity = review.load_groups(path)
    if sorted(g["decision_date"] for g in groups) != list(DAYS) or any(len(g.get("rows", [])) != 200 for g in groups):
        raise ContractError("EXACT_FIVE_ORIGINAL_TOP200_REQUIRED")
    keys = pd.read_csv(directory/"external_keys.csv", dtype=str, keep_default_na=False)
    with np.load(directory/"features.npz", allow_pickle=False) as arrays:
        frozen = arrays["external_structure"]
    lookup = {(r.ts_code,r.trade_date): frozen[i] for i,r in keys.iterrows()}
    gold = external.loc[external.cohort.eq("GOLD40")]
    if len(gold) != 40 or gold.duplicated(["ts_code", "trade_date"]).any():
        raise ContractError("GOLD40_EXACT_KEYS")
    gold_lookup = {(r.ts_code,r.trade_date): r for _,r in gold.iterrows()}
    records, bindings, matched = [], [], []
    for g in sorted(groups, key=lambda r: r["decision_date"]):
        panel, before = review.bind_panel(g)
        if panel is None:
            raise ContractError("HISTORICAL_BOUND_PANEL_REQUIRED")
        raw = review.read_group(panel, g)  # one bounded read/date, held in RAM
        codes = [r["ts_code"] for r in g["rows"]]
        x, evidence = extract_structure(raw, g["decision_date"], codes)
        scores = batch_predict(models, x, evidence)
        for i,rank in enumerate(g["rows"]):
            e = evidence[i]
            root, children = scores.get(i, (None, None))
            row = {"ts_code": rank["ts_code"], "trade_date": g["decision_date"], "source_rank": rank["source_rank"],
                   "source_date": g["source_date"], "observation_date": g["observation_date"],
                   "source_generation": g["source_generation"], "panel_generation": before["panel_generation"],
                   "panel_sha256": g["panel_sha256"], "ranking_sha256": g["ranking_sha256"],
                   "price_basis": g["price_basis"], "prediction_status": e["status"],
                   **{k: e.get(k) for k in ("white", "yellow", "yellow_extension", "context_start", "context_end", "causal_bars")},
                   **score_row(root, children, e), **review.FLAGS}
            records.append(row)
            key = (rank["ts_code"], g["decision_date"])
            if key in gold_lookup:
                prior = gold_lookup[key]
                if int(prior.gold_rank) != rank["source_rank"]:
                    raise ContractError(f"GOLD40_ORIGINAL_RANK_MISMATCH:{key}")
                if (i not in scores or not np.allclose(x[i], lookup[key], rtol=0, atol=1e-12, equal_nan=True)
                        or not np.allclose([root, *children], [float(prior.structure_ch_raw_p_s), *[float(prior[f"structure_ch_raw_p_{c}"]) for c in old.CLASSES]], rtol=0, atol=1e-14)):
                    raise ContractError(f"GOLD40_HISTORICAL_PREFIX_FEATURE_OR_SCORE_MISMATCH:{key}")
                matched.append({"ts_code": key[0], "trade_date": key[1], "source_rank": rank["source_rank"],
                                "original_rank": "PASS", "features": "PASS_43_ATOL_1E-12", "scores": "PASS_ATOL_1E-14"})
        _, after = review.bind_panel(g)
        if review.clean(before) != review.clean(after):
            raise ContractError("HISTORICAL_SOURCE_CHANGED_DURING_READ")
        bindings.append({"day": g["decision_date"], "rows": 200, "source_before_after": "PASS",
                         "binding": before, "prediction_status_counts": dict(Counter(e["status"] for e in evidence))})
        print(json.dumps({"stage": "structure_inference", "day": g["decision_date"], "rows": 200, "ready": len(scores)}), flush=True)
    checked(path, GROUPS_SHA)
    if len(matched) != 40:
        raise ContractError("GOLD40_HISTORICAL_PREFIX_CROSSCHECK_INCOMPLETE")
    frame = pd.DataFrame(records)
    if len(frame) != 1000 or frame.duplicated(["ts_code", "trade_date"]).any():
        raise ContractError("TOP200_1000_COVERAGE_OR_DUPLICATES")
    summary = {"groups": identity, "n": len(frame), "bindings": bindings, "gold40_prefix_crosscheck": matched,
               "ACT021_historical_aggregate": {"rejected_n": 694, "n": 1000, "rate": .694,
                                              "scope": "historical ACT021 aggregate, different state pipeline; not ACT024 truth"},
               "ACT023_structure_coherent": counts(frame, "act024_base_final_state"),
               "ACT024_router": counts(frame, "act024_final_state"),
               "transitions": [{"before": a, "after": b, "n": int(n)} for (a,b),n in frame.groupby(["act024_base_final_state", "act024_final_state"]).size().items()]}
    return frame, summary


def run(directory: Path, external_path: Path, groups_path: Path, output: Path, *, external_only: bool = False) -> dict[str, Any]:
    import shutil
    from threadpoolctl import threadpool_limits
    if output.resolve() != OUTPUT.resolve():
        raise ContractError("OUTPUT_CONFINED_TO_ACT024_RUN")
    output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output).free < 64*1024**2:
        raise ContractError("ACT024_REQUIRES_64_MIB_FREE")
    # Freeze this one policy before reading the public cases or evaluating it.
    policy = {"schema": SCHEMA, "policy": POLICY, "script_sha256": act023.sha(Path(__file__)),
              "act023_plan_sha256": PLAN_SHA, "external_sha256": EXTERNAL_SHA, "groups_sha256": GROUPS_SHA,
              "output_budget_bytes": 16*1024**2, "temporary_artifacts": [], **review.FLAGS}
    frozen_path = output/"frozen_route_policy.json"
    if frozen_path.exists() and json.loads(frozen_path.read_text()) != policy:
        raise ContractError("ACT024_FIXED_POLICY_CHANGED_NO_THRESHOLD_SEARCH")
    act023.write_json(frozen_path, policy)
    with threadpool_limits(limits=1):
        models, identity = load_frozen(directory)
        external, replay = reroute_external(external_path, directory, models)
        summary = {"schema": SCHEMA, "created_at": act023.now(), "policy": POLICY, "model_identity": identity,
                   "external_replay": replay, "external_metrics": external_metrics(external),
                   "actual_fit": {"S": 0, "B": 0, "tuning": 0}, "backtest_count": 0,
                   "multirocket_execution": False, "multirocket_weights_loaded": False, **review.FLAGS}
        if not external_only:
            top200, summary["top200"] = scan_groups(groups_path, directory, models, external)
            top200.to_csv(output/"top200_predictions.csv", index=False, encoding="utf-8-sig")
        external.to_csv(output/"external_predictions.csv", index=False, encoding="utf-8-sig")
        checked(external_path, EXTERNAL_SHA)
        checked(directory/"fit_ledger.json", LEDGER_SHA)
        checked(directory/"frozen_plan.json", PLAN_SHA)
        for name, expected in WEIGHTS.items():
            checked(directory/f"{name}.joblib", expected)
        summary["source_recheck"] = "PASS"
        summary["full1000_status"] = "NOT_RUN" if external_only else "PROCESSED_NOT_GROUND_TRUTH_VALIDATED"
        for name in ("act024_final_hierarchy_contradiction", "act024_final_decision_contradiction"):
            if external[name].fillna(False).astype(bool).any() or (not external_only and top200[name].fillna(False).astype(bool).any()):
                raise ContractError("FINAL_HIERARCHY_OR_DECISION_CONTRADICTION")
        summary["final_contradiction_n"] = 0
        summary["outputs"] = {name: {"bytes": (output/name).stat().st_size, "sha256": act023.sha(output/name)}
                              for name in ("external_predictions.csv", "frozen_route_policy.json", *(() if external_only else ("top200_predictions.csv",)))}
        act023.write_json(output/"summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--act023-run", type=Path, required=True)
    parser.add_argument("--external", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--external-only", action="store_true")
    args = parser.parse_args()
    result = run(args.act023_run.resolve(), args.external.resolve(), args.groups.resolve(), args.output.resolve(), external_only=args.external_only)
    print(json.dumps({"status": "COMPLETE_INFERENCE_ONLY", "external_n": result["external_replay"]["n"],
                      "full1000_status": result["full1000_status"], "actual_fit": result["actual_fit"]}))


if __name__ == "__main__":
    main()
