"""ACT025: fixed low-S precedence, inference-only rebuild candidate review.

No training, tuning, MR execution, future outcomes, authority writes or panel copies.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import shutil
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act024_s_v3_router as prior

act023, old, review = prior.act023, prior.old, prior.review
ContractError = prior.ContractError
ARTIFACTS = prior.ARTIFACT_ROOT
OUTPUT = ARTIFACTS/"pft_act025_s_v3_20261123/run"
EXTERNAL_SHA = "155c769a0dfa28bb4b72285503a833a48b05d813e7aa4778217b9e7a1c77b85d"
LABEL_COUNT = 145690
POLICY = {
    "precedence": "observed strict G1, then valid projected S<0.10, then exact ACT024",
    "threshold": .10, "projection": "unchanged ACT023 max(binary S, three positive children)",
    "primary": "ACT020 validation split AND validation securities, weak rebuild only",
    "exclusion": "whole prior external securities AND whole ACT023 training-member securities",
    "eligibility": "READY,60 valid bars,rebuild positive-head argmax,S>=.35,no strong fake-head contradiction,CONFIRMED_S rebuild or UNKNOWN_BORDERLINE",
    "selection": "primary first;10 high+10 boundary;fill shortage from other eligible stratum;one per security",
    "ordering": "descending rebuild probability,descending projected S,ascending date,ascending code",
    "fallback": "only if primary<20;remaining weak rebuild index,earliest date per nonexcluded security;candidate-only,not time-held-out",
    "rank": "optional official 20261123 membership;features strictly ACT021 exact 20261120 panel",
}


def route(root, children, evidence):
    result = prior.route(root, children, evidence)
    p = result["projected_p_s"]
    if not result["strict_g1_failure"] and p is not None and p < .10:
        result.update(final_state="REJECTED_FAKE", main_tactic="invalid_fake",
                      route_reasons="PROJECTED_S_LT_010", final_decision_contradiction=False)
    return result


def external_review(path):
    import pandas as pd
    prior.checked(path, EXTERNAL_SHA)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if (len(frame) != 93 or frame.duplicated(["cohort", "case_id"]).any()
            or frame.cohort.value_counts().to_dict() != {"GOLD40": 40, "ANCHOR20": 20, "COMMON61": 33}):
        raise ContractError("ACT024_93_IDENTITY")
    added = []
    for r in frame.to_dict("records"):
        root = prior.finite(r["act024_raw_p_s"])
        children = [prior.finite(r[f"act024_raw_p_{c}"]) for c in old.CLASSES]
        e = {"status": r["prediction_status"], **{k: prior.finite(r[k]) for k in ("white", "yellow", "yellow_extension")}}
        replay = prior.route(root, children, e)
        if any(str(replay[k]) != r[f"act024_{k}"] for k in ("final_state", "main_tactic", "route_reasons")):
            raise ContractError(f"ACT024_ROUTER_REPLAY:{r['case_id']}")
        added.append({f"act025_{k}": v for k,v in route(root, children, e).items()})
    result = pd.concat([frame, pd.DataFrame(added)], axis=1)
    before = prior.external_metrics(result)
    after = prior.external_metrics(result.drop(columns=[c for c in result if c.startswith("act024_")])
                                    .rename(columns=lambda c: c.replace("act025_", "act024_")))
    for cohort in after.values():
        cohort["arms"]["act025"] = cohort["arms"].pop("act024")
        cohort["recall_interpretation"] = "Low projected S may reject positives; confirmed recall, abstention upper bound and false rejection remain separate."
    changed = result.loc[result.act024_final_state.ne(result.act025_final_state)]
    audit = changed[["cohort", "case_id", "ts_code", "trade_date", "truth_state", "act024_final_state",
                     "act024_route_reasons", "act025_final_state", "act025_route_reasons", "act025_projected_p_s"]].to_dict("records")
    cleaned = [r for r in audit if r["truth_state"] == "REJECTED_FAKE" and r["act024_final_state"] == "UNKNOWN_BORDERLINE"]
    return result, {"ACT024": before, "ACT025": after, "changed": audit, "cleaned_true_negative_abstentions": cleaned,
                    "cleaned_n": len(cleaned), "expected_cleaned_n": 9, "router_replay": "PASS_93"}


def load_rank(path):
    if path is None:
        return None, {"status": "NOT_LANDED", "reason": "No official 20261123 original rank supplied"}
    data = json.loads(path.read_text())
    if data.get("rank_date") != "20261123" or not data.get("source_ref") or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("ranking_sha256"))):
        raise ContractError("OFFICIAL_D23_RANK_PROVENANCE_OR_DATE")
    rows = data.get("rows", [])
    if (len(rows) != 200 or any(type(r.get("source_rank")) is not int for r in rows)
            or {r["source_rank"] for r in rows} != set(range(1,201))
            or any(not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(r.get("ts_code"))) for r in rows)
            or len({r["ts_code"] for r in rows}) != 200):
        raise ContractError("OFFICIAL_D23_REQUIRES_200_UNIQUE_A_SECURITIES_RANKS")
    for r in rows:
        if r.get("rank_date", "20261123") != "20261123":
            raise ContractError("OFFICIAL_D23_ROW_DATE")
    return sorted(rows, key=lambda r:r["source_rank"]), {"status": "LANDED_MEMBERSHIP_ONLY", "path": str(path),
            "sha256": act023.sha(path), **{k:data[k] for k in ("rank_date", "source_ref", "ranking_sha256")}}


def candidate_index(labels, membership, exclusions):
    import pandas as pd
    excluded = pd.read_csv(exclusions, dtype=str, keep_default_na=False)
    if list(excluded) != ["ts_code"] or excluded.ts_code.duplicated().any() or not excluded.ts_code.str.fullmatch(r"\d{6}\.(SH|SZ|BJ)").all():
        raise ContractError("EXCLUSIONS_REQUIRE_UNIQUE_A_TS_CODE_ONLY")
    trained = set(pd.read_csv(membership, dtype=str).ts_code)
    frame = pd.read_csv(labels, dtype=str, keep_default_na=False,
                        usecols=["ts_code", "trade_date", "tactic", "split", "security_group", "feature_ready"])
    if len(frame) != LABEL_COUNT:
        raise ContractError("ACT020_FROZEN_LABEL_COUNT")
    frame = frame.loc[frame.tactic.eq("rebuild") & frame.feature_ready.eq("True")
                      & frame.trade_date.between(old.START, old.END) & ~frame.ts_code.isin(set(excluded.ts_code)|trained)].copy()
    frame["pool"] = "fallback"
    primary = frame.split.eq("validation") & frame.security_group.eq("validation")
    frame.loc[primary, "pool"] = "primary"
    extra = frame.loc[~primary].sort_values(["trade_date", "ts_code"]).drop_duplicates("ts_code")
    extra = extra.loc[~extra.ts_code.isin(set(frame.loc[primary, "ts_code"]))]
    targets = pd.concat([frame.loc[primary], extra], ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    return targets, {"external_securities": len(excluded), "training_securities": len(trained),
                     "primary_rows": int(primary.sum()), "fallback_rows": len(extra), "training_overlap_n": 0}


def score_targets(raw, targets, models):
    """Each D sees its own <=D, 400-calendar-day causal prefix only."""
    records, contexts = [], {}
    by_code = {c:p for c,p in raw.groupby("ts_code", sort=False)}
    for day, part in targets.groupby("trade_date", sort=True):
        lower = (datetime.strptime(day, "%Y%m%d")-timedelta(days=400)).strftime("%Y%m%d")
        pieces = [by_code[c].loc[by_code[c].trade_date.between(lower, day)] for c in part.ts_code if c in by_code]
        import pandas as pd
        context = pd.concat(pieces, ignore_index=True) if pieces else raw.iloc[:0]
        codes = part.ts_code.tolist()
        x, evidence = prior.extract_structure(context, day, codes)
        scores = prior.batch_predict(models, x, evidence)
        for i,code in enumerate(codes):
            root, children = scores.get(i, (None, None))
            e, r = evidence[i], route(root, children, evidence[i])
            prefix = context.loc[context.ts_code.eq(code)]
            row = {"ts_code": code, "trade_date": day, "prediction_status": e["status"], "stage": e.get("stage", "UNKNOWN"),
                   "missing_extra_features": json.dumps(e.get("missing_extra_features", [])), **r}
            records.append(row)
            contexts[(code, day)] = {"frame": prefix.tail(60).copy(), "evidence": e}
    return pd.DataFrame(records), contexts


def select_candidates(scores):
    import pandas as pd
    candidates = scores.loc[scores.prediction_status.eq("READY")].copy()
    positive = [f"raw_p_{c}" for c in old.CLASSES[:3]]
    rebuild_top = candidates[positive].idxmax(axis=1).eq("raw_p_rebuild")
    ok = rebuild_top & candidates.projected_p_s.ge(.35) & ~candidates.route_reasons.str.contains("STRONG_BINARY_FAKE_HEAD_CONTRADICTION", regex=False)
    high = candidates.final_state.eq("CONFIRMED_S") & candidates.main_tactic.eq("rebuild")
    boundary = candidates.final_state.eq("UNKNOWN_BORDERLINE")
    candidates = candidates.loc[ok & (high|boundary)].copy()
    candidates["stratum"] = candidates.final_state.map({"CONFIRMED_S": "high", "UNKNOWN_BORDERLINE": "boundary"})
    candidates = candidates.sort_values(["raw_p_rebuild", "projected_p_s", "trade_date", "ts_code"], ascending=[False,False,True,True], kind="mergesort")
    chosen, used = [], set()
    for pool in ("primary", "fallback"):
        part = candidates.loc[candidates.pool.eq(pool)]
        for stratum, limit in (("high",10), ("boundary",10), (None,20)):
            for r in part.to_dict("records"):
                if len(chosen) >= 20:
                    break
                if r["ts_code"] in used or (stratum and (r["stratum"] != stratum or sum(c["stratum"] == stratum for c in chosen) >= limit)):
                    continue
                chosen.append(r); used.add(r["ts_code"])
    return pd.DataFrame(chosen), {"status": "COMPLETE_20" if len(chosen) == 20 else "FAIL_INSUFFICIENT_ELIGIBLE_REBUILD",
                                 "actual_strata": dict(Counter(r["stratum"] for r in chosen)),
                                 "actual_pools": dict(Counter(r["pool"] for r in chosen)), "n": len(chosen), "eligible_n": len(candidates)}


def public_sequence(context):
    frame, e = context["frame"], context["evidence"]
    if len(frame) != 60 or not all(review.valid_bar(r) for r in frame.to_dict("records")):
        raise ContractError("PUBLIC_REQUIRES_60_VALID_OBSERVED_BARS")
    scale = float(frame.iloc[0].close)
    volume_scale = sum(float(v)/5 for v in frame.head(5).vol)
    if prior.finite(volume_scale) is None or volume_scale <= 0:
        raise ContractError("PUBLIC_REQUIRES_FINITE_POSITIVE_VOLUME_SCALE")
    bars = [{"bar_index": i, "date": r["trade_date"], "volume_rel_first5": float(r["vol"])/volume_scale,
             **{k: float(r[k])/scale for k in
             ("open", "high", "low", "close", "zge_white_line", "zge_yellow_line")}} for i,r in enumerate(frame.to_dict("records"))]
    history = e.get("anchors", {})
    return {"bars": bars, "anchors": [{"role": a["role"], "date": a["date"], "relative_low": float(a["low"])/scale,
            "relative_body_mid": float(a["mid"])/scale, "close_broken_observed": a["close_broken_flag"]} for a in history.get("events", [])],
            "guards": {"strict_observed_w_below_y": bool(e["white"] < e["yellow"]), "yellow_extension": e["yellow_extension"],
                       **{k: e[k] for k in ("volume_compression", "range_compression") if k in e},
                       "line_spread": float(e["white"])/float(e["yellow"])-1,
                       "old_close_failure_survives_new_anchor": history.get("old_close_failure_survives_new_anchor"),
                       "history_left_censored": True, "intraday_cross_time": "UNKNOWN"}}


def rank_scan(rank, groups_path, models):
    import pandas as pd
    prior.checked(groups_path, prior.GROUPS_SHA)
    groups, _ = review.load_groups(groups_path)
    group = next(g for g in groups if g["decision_date"] == "20261120")
    group = {**group, "rows": rank}
    panel, before = review.bind_panel(group)
    if panel is None:
        raise ContractError("RANK_REQUIRES_EXACT_D20_BOUND_PANEL")
    raw = review.read_group(panel, group)
    targets = pd.DataFrame([{"ts_code": r["ts_code"], "trade_date": "20261120"} for r in rank])
    scores, _ = score_targets(raw, targets, models)
    scores = pd.DataFrame(rank).merge(scores, on="ts_code", validate="one_to_one")
    _, after = review.bind_panel(group)
    if review.clean(before) != review.clean(after):
        raise ContractError("D20_RANK_SOURCE_CHANGED")
    return scores, {"n": len(scores), "feature_asof": "20261120", "membership_date": "20261123", "binding": before,
                    "states": scores.final_state.value_counts().to_dict(),
                    "confirmed_tactics": scores.loc[scores.final_state.eq("CONFIRMED_S"), "main_tactic"].value_counts().to_dict(),
                    "stages": scores.stage.value_counts().to_dict(), "missing": scores.prediction_status.value_counts().to_dict()}


def run(args):
    import pandas as pd
    from threadpoolctl import threadpool_limits
    if args.output.resolve() != OUTPUT.resolve():
        raise ContractError("OUTPUT_CONFINED_TO_ACT025_RUN")
    args.output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output).free < 64*1024**2:
        raise ContractError("REQUIRES_64_MIB_FREE")
    inputs = [args.external, args.exclusions, args.groups, args.act020_run/"labels.csv", args.act020_run/"run_identity.json",
              args.act023_run/"training_membership.csv"] + ([args.rank_input] if args.rank_input else [])
    hashes = {str(p): act023.sha(p) for p in inputs}
    policy = {"policy": POLICY, "inputs": hashes, "script_sha256": act023.sha(Path(__file__)),
              "output_budget_bytes": 32*1024**2, "temporary_artifacts": [], **review.FLAGS}
    frozen = args.output/"frozen_policy.json"
    if frozen.exists() and json.loads(frozen.read_text()) != policy:
        raise ContractError("FIXED_ACT025_POLICY_OR_INPUT_CHANGED")
    act023.write_json(frozen, policy)
    with threadpool_limits(limits=1):
        models, model_identity = prior.load_frozen(args.act023_run)
        plan = json.loads((args.act023_run/"frozen_plan.json").read_text())
        for name in ("labels.csv", "run_identity.json"):
            prior.checked(args.act020_run/name, plan["baseline"][name]["sha256"])
        targets, exclusions = candidate_index(args.act020_run/"labels.csv", args.act023_run/"training_membership.csv", args.exclusions)
        panel, binding = act023.bind_training_panel(args.act020_run)
        raw = act023.read_targets(panel, targets)  # exactly one bounded projection, RAM only
        scores, contexts = score_targets(raw, targets, models)
        scores = scores.merge(targets[["ts_code", "trade_date", "pool"]], on=["ts_code", "trade_date"], validate="one_to_one")
        # Check public-bar eligibility before selection, so missing bars cannot consume quotas.
        valid = {key for key,c in contexts.items() if len(c["frame"]) == 60 and all(review.valid_bar(r) for r in c["frame"].to_dict("records"))}
        eligible_scores = scores.loc[[(r.ts_code,r.trade_date) in valid for r in scores.itertuples()]]
        selected, selection = select_candidates(eligible_scores)
        scores.to_csv(args.output/"candidate_scores.csv", index=False, encoding="utf-8-sig")
        public = []
        for i,r in enumerate(selected.to_dict("records"), 1):
            public.append({"case_id": f"ACT025-{i:02d}", "ts_code": r["ts_code"], "trade_date": r["trade_date"],
                           "sequence_json": json.dumps(public_sequence(contexts[(r["ts_code"],r["trade_date"])]), ensure_ascii=False, allow_nan=False)})
        if len(public) == 20:
            pd.DataFrame(public).to_csv(args.output/"rebuild20.csv", index=False, encoding="utf-8-sig")
        external, metrics = external_review(args.external)
        external.to_csv(args.output/"external_predictions.csv", index=False, encoding="utf-8-sig")
        rank, rank_identity = load_rank(args.rank_input)
        if rank is not None:
            ranked, rank_summary = rank_scan(rank, args.groups, models)
            ranked.to_csv(args.output/"rank200_predictions.csv", index=False, encoding="utf-8-sig")
            rank_identity.update(rank_summary)
        _, after = act023.bind_training_panel(args.act020_run)
        if review.clean(binding) != review.clean(after):
            raise ContractError("HISTORICAL_SOURCE_CHANGED")
        for p,h in hashes.items():
            prior.checked(Path(p), h)
        summary = {"schema": "pft_act025_s_v3_rebuild.v1", "created_at": act023.now(), "model_identity": model_identity,
                   "selection": selection, "exclusions": exclusions, "binding": binding, "rank": rank_identity,
                   "external_metrics": metrics, "actual_fit": {"S":0,"B":0,"tuning":0}, "backtest_count":0,
                   "multirocket_execution": False, "source_recheck": "PASS", **review.FLAGS}
        act023.write_json(args.output/"summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    for name, default in (("act020-run", ARTIFACTS/"pft_act020_s_v2_20261123/run"),
                          ("act023-run", ARTIFACTS/"pft_act023_s_v3_20261123/run"),
                          ("external", ARTIFACTS/"pft_act024_s_v3_20261123/run/external_predictions.csv"),
                          ("groups", ARTIFACTS/"pft_act021_s_v3_20261123/verified_groups.json"), ("output", OUTPUT)):
        parser.add_argument("--"+name, type=Path, default=default)
    parser.add_argument("--rank-input", type=Path)
    parser.add_argument("--exclusions", type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({"selection": result["selection"], "rank": result["rank"]["status"], "output": str(args.output)}))
    return 0 if result["selection"]["n"] == 20 else 2


if __name__ == "__main__":
    raise SystemExit(main())
