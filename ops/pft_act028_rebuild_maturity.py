"""ACT028: one frozen Rebuild maturity guard over archived ACT025 routes.

No fitting, inference, tuning, backtest, MR execution, or authority writes.
Only confirmed Rebuild prefixes are read through the existing ACT021 Reader.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import shutil
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from contracts import trading_calendar as calendar
from ops import pft_act025_s_v3_rebuild as act025

prior, act023, review = act025.prior, act025.act023, act025.review
ContractError = prior.ContractError
ROOT = prior.ARTIFACT_ROOT
OUTPUT = ROOT / "pft_act028_s_v3_20261123/run"
EXTERNAL_SHA = "1bd22bd6958c647fb41155ead8abb1ab88bca29d2b685ae1e061ac2837ec6fd7"
REBUILD20_SHA = "67168cd69e88c8a8d74d1366500be79a27f19363262abc1cde48460a19ffd689"
TOP200_SHA = "8823dec22a3bc9045b9fb285b3287ba6e9a0145ee089e882f864f773c004cbcf"
REASON = "REBUILD_REPAIR_AGE_LT_4D"
MIN_AGE = 4
CALENDAR_SHA = "9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb"
POLICY = {
    "baseline": "exact ACT025 route over archived frozen ACT023 43D HGB raw scores",
    "precedence": "strict observed G1, valid projected S<0.10, all existing ACT025 guards, then maturity",
    "scope": "ACT025 CONFIRMED_S with published main_tactic rebuild only",
    "anchor": "latest repair role event in the unchanged ACT023/ACT021 causal role stack",
    "age": "A-share exchange sessions in (repair_anchor_date,D]; anchor day age 0",
    "guard": "missing anchor or unavailable calendar or age<4 => UNKNOWN_BORDERLINE; clear main tactic",
    "exact_four": "retain baseline exactly",
    "reason": REASON,
    "probabilities": "unchanged; no fitting, re-inference, threshold search, B, backtest or MR",
}


def date8(value):
    text = str(value or "").replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def tactic(value):
    return "rebuild" if value == "S_REBUILD" else value


class ExchangeSessions:
    """Canonical 2026 schedule plus explicitly bounded historical V4 dates."""

    def __init__(self, extra=None):
        prior.checked(calendar.CALENDAR_PATH, CALENDAR_SHA)
        self.schedule = calendar.load_market_calendar()
        self.identity = {"canonical_path": str(calendar.CALENDAR_PATH),
                         "canonical_sha256": act023.sha(calendar.CALENDAR_PATH),
                         "canonical_schema": self.schedule.schema_version}
        self.extra = None
        if extra is not None:
            import pandas as pd
            frame = pd.read_csv(extra, dtype=str, keep_default_na=False)
            required = {"session_date", "source_ref", "source_sha256", "coverage_start", "coverage_end"}
            if not required <= set(frame) or frame.empty:
                raise ContractError("EXTRA_CALENDAR_REQUIRES_PROVENANCE_AND_COVERAGE")
            for name in ("source_ref", "source_sha256", "coverage_start", "coverage_end"):
                if frame[name].nunique() != 1 or not frame.iloc[0][name]:
                    raise ContractError("EXTRA_CALENDAR_SINGLE_VERIFIED_COVERAGE")
            first = frame.iloc[0]
            lo, hi = date8(first.coverage_start), date8(first.coverage_end)
            dates = [date8(d) for d in frame.session_date]
            if (lo is None or hi is None or lo > hi or None in dates or len(set(dates)) != len(dates)
                    or any(not lo <= d <= hi for d in dates)
                    or not re.fullmatch(r"[0-9a-f]{64}", first.source_sha256)):
                raise ContractError("EXTRA_CALENDAR_INVALID_DATES_OR_SHA")
            self.extra = (lo, hi, set(dates))
            self.identity["extra"] = {"path": str(extra), "sha256": act023.sha(extra),
                                      **{k: first[k] for k in required if k != "session_date"}, "sessions": dates}

    def age(self, anchor, day):
        anchor, day = date8(anchor), date8(day)
        if anchor is None:
            return None, "MISSING_REPAIR_ANCHOR"
        if day is None or anchor > day:
            return None, "INVALID_ANCHOR_OR_DECISION_DATE"
        if anchor[:4] == day[:4] == str(self.schedule.year):
            start = datetime.strptime(anchor, "%Y%m%d").date()
            end = datetime.strptime(day, "%Y%m%d").date()
            days = [start + timedelta(days=i) for i in range((end-start).days+1)]
            states = [calendar.direct_market_state(d, self.schedule.markets["a_share"]) for d in days]
            valid = {calendar.TradingDayState.FULL_TRADING_DAY, calendar.TradingDayState.HALF_TRADING_DAY_AM}
            if states[0] not in valid or states[-1] not in valid:
                return None, "ANCHOR_OR_DECISION_NOT_EXCHANGE_SESSION"
            return sum(s in valid for s in states[1:]), "CANONICAL_2026_EXCHANGE_SESSIONS"
        if self.extra is not None:
            lo, hi, dates = self.extra
            if lo <= anchor <= day <= hi:
                if anchor not in dates or day not in dates:
                    return None, "ANCHOR_OR_DECISION_NOT_EXCHANGE_SESSION"
                return sum(anchor < d <= day for d in dates), "VERIFIED_V4_HISTORICAL_EXCHANGE_SESSIONS"
        return None, "MISSING_EXCHANGE_CALENDAR"


def maturity(baseline, anchor, day, sessions, *, anchor_status="ARCHIVED_LATEST_REPAIR"):
    """Pure post-router guard; baseline probabilities and all other fields survive."""
    result = dict(baseline)
    applicable = baseline["final_state"] == "CONFIRMED_S" and baseline["main_tactic"] == "rebuild"
    result.update(repair_anchor_date=date8(anchor), repair_age_sessions=None,
                  repair_age_status="NOT_APPLICABLE", repair_anchor_status=anchor_status,
                  maturity_guard_applied=False)
    if not applicable:
        return result
    age, status = sessions.age(anchor, day)
    result.update(repair_age_sessions=age, repair_age_status=status)
    if age is None or age < MIN_AGE:
        reasons = [r for r in baseline["route_reasons"].split(";") if r]
        result.update(final_state="UNKNOWN_BORDERLINE", main_tactic="",
                      route_reasons=";".join(dict.fromkeys([*reasons, REASON])),
                      final_decision_contradiction=False, maturity_guard_applied=True)
    return result


def replay(row, score_prefix, state_key, tactic_key, reasons_key):
    root = prior.finite(row.get(score_prefix+"raw_p_s"))
    children = [prior.finite(row.get(score_prefix+"raw_p_"+c)) for c in prior.old.CLASSES]
    evidence = {"status": row["prediction_status"],
                **{k: prior.finite(row.get(k)) for k in ("white", "yellow", "yellow_extension")}}
    baseline = act025.route(root, children, evidence)
    for key, expected in (("final_state", row[state_key]), ("main_tactic", tactic(row[tactic_key])),
                          ("route_reasons", row[reasons_key])):
        if baseline[key] != expected:
            raise ContractError(f"ACT025_ARCHIVED_REPLAY:{row.get('case_id', row['ts_code'])}:{key}")
    saved_projection = prior.finite(row.get(score_prefix+"projected_p_s"))
    actual = baseline["projected_p_s"]
    if ((saved_projection is None) != (actual is None)
            or actual is not None and abs(saved_projection-actual) > 1e-14):
        raise ContractError("ARCHIVED_PROJECTED_S_CHANGED")
    return baseline


def metrics(frame):
    result = {}
    for cohort, part in [("ALL", frame), *list(frame.groupby("cohort", sort=True))]:
        data = {"n": len(part), "truth_states": part.truth_state.value_counts().to_dict()}
        for arm in ("act025", "act028"):
            state = part[arm+"_final_state"]
            confirmed, truth_positive = state.eq("CONFIRMED_S"), part.truth_state.eq("CONFIRMED_S")
            known_negative = part.truth_state.eq("REJECTED_FAKE")
            n, hit = int(confirmed.sum()), int((confirmed & truth_positive).sum())
            determinate = int((confirmed & (truth_positive | known_negative)).sum())
            data[arm] = {"states": state.value_counts().to_dict(),
                         "state_hits": int(state.eq(part.truth_state).sum()),
                         "state_hit_rate": float(state.eq(part.truth_state).mean()),
                         "confirmed_n": n, "truth_confirmed_and_confirmed_n": hit,
                         "strict_confirmation_precision": hit/n if n else None,
                         "determinate_only_precision": hit/determinate if determinate else None,
                         "truth_boundary_n": int(part.truth_state.eq("UNKNOWN_BORDERLINE").sum()),
                         "truth_boundary_retained_n": int((part.truth_state.eq("UNKNOWN_BORDERLINE") & state.eq("UNKNOWN_BORDERLINE")).sum()),
                         "known_negative_false_positive_n": int((known_negative & confirmed).sum())}
        result[cohort] = data
    prior_tp = frame.cohort.eq("REBUILD20") & frame.truth_state.eq("CONFIRMED_S") & frame.act025_final_state.eq("CONFIRMED_S")
    denominator = int(prior_tp.sum())
    result["rebuild20_prior_true_positive_retention"] = {
        "denominator": denominator, "expected_frozen_denominator": 4,
        "retained": int((prior_tp & frame.act028_final_state.eq("CONFIRMED_S")).sum())}
    return result


def external(external_path, rebuild_path, sessions):
    import pandas as pd
    records = []
    original = pd.read_csv(external_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    rebuild = pd.read_csv(rebuild_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if (len(original) != 93 or original.cohort.value_counts().to_dict() != {"GOLD40":40,"ANCHOR20":20,"COMMON61":33}
            or original.duplicated(["cohort", "case_id"]).any()
            or len(rebuild) != 20 or rebuild.case_id.duplicated().any()):
        raise ContractError("EXTERNAL_93_PLUS_REBUILD20_IDENTITY")
    for is_rebuild, source in ((False, original), (True, rebuild)):
        for row in source.to_dict("records"):
            if is_rebuild:
                baseline = replay(row, "", "act025_state", "act025_primary_tactic", "route_reasons")
                row.update(cohort="REBUILD20", truth_state=row["gemini_state"],
                           truth_tactic=tactic(row["gemini_primary_tactic"]))
            else:
                baseline = replay(row, "act025_", "act025_final_state", "act025_main_tactic", "act025_route_reasons")
            after = maturity(baseline, row.get("repair_anchor_date"), row["trade_date"], sessions)
            records.append({**row, "state_source": "ARCHIVED_FROZEN_43D_HGB_RAW_ACT025_REPLAY",
                            **{"act025_"+k:v for k,v in baseline.items()},
                            **{"act028_"+k:v for k,v in after.items()}})
    frame = pd.DataFrame(records)
    if frame.duplicated(["cohort", "case_id"]).any():
        raise ContractError("EXTERNAL_DUPLICATE_KEY")
    summary = metrics(frame)
    if summary["rebuild20_prior_true_positive_retention"]["denominator"] != 4:
        raise ContractError("FROZEN_REBUILD20_PRIOR_TP_DENOMINATOR")
    return frame, summary


def validate_top200(frame, groups):
    if (len(frame) != 1000 or frame.duplicated(["ts_code", "trade_date"]).any()
            or sorted(g["decision_date"] for g in groups) != list(prior.DAYS)):
        raise ContractError("EXACT_ORIGINAL_TOP200_1000_REQUIRED")
    for g in groups:
        part = frame.loc[frame.trade_date.eq(g["decision_date"])]
        expected = {(r["ts_code"], r["source_rank"]) for r in g["rows"]}
        actual = {(r.ts_code, int(r.source_rank)) for r in part.itertuples()}
        if len(part) != 200 or expected != actual:
            raise ContractError("TOP200_ARCHIVED_DATE_RANK_CODE_MISMATCH")
        for key in ("source_date", "observation_date", "source_generation", "panel_sha256", "ranking_sha256", "price_basis"):
            if not part[key].eq(str(g[key])).all():
                raise ContractError("TOP200_ARCHIVED_SOURCE_MISMATCH:"+key)
        if not part.panel_generation.eq(str(g.get("panel_generation", g["source_generation"]))).all():
            raise ContractError("TOP200_ARCHIVED_PANEL_GENERATION_MISMATCH")


def top200(path, groups_path, sessions):
    import pandas as pd
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    groups, identity = review.load_groups(groups_path)
    validate_top200(frame, groups)
    baselines = []
    for row in frame.to_dict("records"):
        # The archived 1000 are ACT024; verify those states before applying ACT025.
        e = {"status":row["prediction_status"], **{k:prior.finite(row.get(k)) for k in ("white","yellow","yellow_extension")}}
        root = prior.finite(row.get("act024_raw_p_s"))
        children = [prior.finite(row.get("act024_raw_p_"+c)) for c in prior.old.CLASSES]
        original = prior.route(root, children, e)
        if any(original[k] != row["act024_"+k] for k in ("final_state","main_tactic","route_reasons")):
            raise ContractError("ACT024_TOP200_ARCHIVE_REPLAY")
        projection = prior.finite(row.get("act024_projected_p_s"))
        if ((projection is None) != (original["projected_p_s"] is None)
                or projection is not None and abs(projection-original["projected_p_s"]) > 1e-14):
            raise ContractError("ACT024_TOP200_ARCHIVED_PROJECTION")
        baselines.append(act025.route(root, children, e))
    anchors, bindings = {}, []
    for g in groups:
        indices = [i for i,b in enumerate(baselines) if frame.iloc[i].trade_date == g["decision_date"]
                   and b["final_state"] == "CONFIRMED_S" and b["main_tactic"] == "rebuild"]
        codes = [frame.iloc[i].ts_code for i in indices]
        if not codes:
            continue
        subset = {**g, "rows":[r for r in g["rows"] if r["ts_code"] in set(codes)]}
        try:
            panel, before = review.bind_panel(subset)
            if panel is None:
                raise ContractError("EXACT_BOUND_PANEL_UNAVAILABLE")
            raw = review.read_group(panel, subset)
            _, evidence = prior.extract_structure(raw, g["decision_date"], codes)
            for code, e in zip(codes, evidence):
                if e["status"] != "READY":
                    anchors[(code,g["decision_date"])] = (None, e["status"])
                    continue
                row = frame.loc[frame.ts_code.eq(code) & frame.trade_date.eq(g["decision_date"])].iloc[0]
                if any(prior.finite(e.get(k)) is None or abs(float(e[k])-float(row[k])) > 1e-12
                       for k in ("white","yellow","yellow_extension")):
                    raise ContractError("ARCHIVED_PREFIX_LINE_EVIDENCE_CHANGED")
                event = next((x for x in reversed(e["anchors"]["events"]) if x["role"] == "repair"), None)
                anchors[(code,g["decision_date"])] = (event["date"] if event else None, "EXACT_V4_PREFIX_LATEST_REPAIR")
            _, after = review.bind_panel(subset)
            if review.clean(before) != review.clean(after):
                raise ContractError("BOUND_SOURCE_CHANGED")
            bindings.append({"day":g["decision_date"], "requested_codes":codes, "binding":before,
                             "source_before_after":"PASS", "raw_rows":len(raw)})
        except (OSError, ContractError) as error:
            # Missing evidence cannot manufacture maturity; preserve all original rows.
            for code in codes:
                anchors[(code,g["decision_date"])] = (None, "CANNOT_CONFIRM:"+str(error))
            bindings.append({"day":g["decision_date"], "requested_codes":codes,
                             "status":"CANNOT_CONFIRM", "reason":str(error)})
    records = []
    for row, baseline in zip(frame.to_dict("records"), baselines):
        anchor, status = anchors.get((row["ts_code"],row["trade_date"]), (None,"NOT_APPLICABLE"))
        after = maturity(baseline, anchor, row["trade_date"], sessions, anchor_status=status)
        records.append({**row, "state_source":"ARCHIVED_ACT024_RAW_ACT025_REPLAY_WITH_EXACT_V4_REPAIR_PREFIX",
                        **{"act025_"+k:v for k,v in baseline.items()},
                        **{"act028_"+k:v for k,v in after.items()}})
    result = pd.DataFrame(records)
    def count(part):
        return {arm:{"states":part[arm+"_final_state"].value_counts().to_dict(),
                     "confirmed_tactics":part.loc[part[arm+"_final_state"].eq("CONFIRMED_S"),arm+"_main_tactic"].value_counts().to_dict()}
                for arm in ("act025","act028")}
    return result, {"n":1000, "groups":identity, "bindings":bindings,
                    "aggregate":count(result), "daily":{d:count(p) for d,p in result.groupby("trade_date")},
                    "truth_validation":"NOT_GROUND_TRUTH_VALIDATED", "archive_replay":"PASS_1000_ACT024_THEN_ACT025"}


def run(args):
    if args.output.resolve() != OUTPUT.resolve():
        raise ContractError("OUTPUT_CONFINED_TO_ACT028_RUN")
    inputs = {args.external:EXTERNAL_SHA, args.rebuild20:REBUILD20_SHA,
              args.top200:TOP200_SHA, args.groups:prior.GROUPS_SHA}
    for path, expected in inputs.items():
        prior.checked(path, expected)
    # Verify archived model identity without loading a model or invoking predict/fit.
    model_inputs = {args.act023_run/"frozen_plan.json":prior.PLAN_SHA,
                    args.act023_run/"fit_ledger.json":prior.LEDGER_SHA,
                    **{args.act023_run/(name+".joblib"):sha for name,sha in prior.WEIGHTS.items()}}
    for path, expected in model_inputs.items():
        prior.checked(path, expected)
    plan = json.loads((args.act023_run/"frozen_plan.json").read_text())
    if plan["features"] != list(act023.STRUCT_FEATURES) or len(plan["features"]) != 43:
        raise ContractError("FROZEN_MODEL_REQUIRES_EXACT_43D_STRUCTURE")
    sessions = ExchangeSessions(args.calendar_extra)
    args.output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output).free < 64*1024**2:
        raise ContractError("REQUIRES_64_MIB_FREE")
    policy = {"schema":"pft_act028_rebuild_maturity.v1", "policy":POLICY,
              "script_sha256":act023.sha(Path(__file__)), "inputs":{str(p):h for p,h in inputs.items()},
              "models":{str(p):h for p,h in model_inputs.items()}, "calendar":sessions.identity,
              "output_budget_bytes":16*1024**2, "temporary_artifacts":[], **review.FLAGS}
    frozen = args.output/"frozen_policy.json"
    if frozen.exists() and json.loads(frozen.read_text()) != policy:
        raise ContractError("FROZEN_POLICY_OR_INPUT_CHANGED_NO_SEARCH")
    act023.write_json(frozen, policy)
    cases, case_metrics = external(args.external, args.rebuild20, sessions)
    ranked, rank_summary = top200(args.top200, args.groups, sessions)
    contradictions = sum(int(f["act028_final_hierarchy_contradiction"].fillna(False).sum())
                         +int(f["act028_final_decision_contradiction"].fillna(False).sum()) for f in (cases,ranked))
    if contradictions:
        raise ContractError("FINAL_CONTRADICTIONS")
    for path, expected in {**inputs, **model_inputs}.items():
        prior.checked(path, expected)
    if sessions.identity != ExchangeSessions(args.calendar_extra).identity:
        raise ContractError("CALENDAR_CHANGED")
    cases.to_csv(args.output/"external_predictions.csv", index=False, encoding="utf-8-sig")
    ranked.to_csv(args.output/"top200_predictions.csv", index=False, encoding="utf-8-sig")
    summary = {"schema":policy["schema"], "created_at":act023.now(), "policy":POLICY,
               "external_n":len(cases), "external_metrics":case_metrics, "top200":rank_summary,
               "calendar":sessions.identity, "actual_fit":{"S":0,"B":0,"tuning":0}, "backtest_count":0,
               "model_predict_count":0, "multirocket_execution":False, "multirocket_weights_loaded":False,
               "final_contradiction_n":contradictions, "source_recheck":"PASS", **review.FLAGS}
    for name, f in (("external",cases),("top200",ranked)):
        summary[name+"_audit"] = {"state_sources":f.state_source.value_counts().to_dict(),
            "repair_age_status":f.act028_repair_age_status.value_counts().to_dict(),
            "repair_anchor_status":f.act028_repair_anchor_status.value_counts().to_dict(),
            "changed_n":int(f.act025_final_state.ne(f.act028_final_state).sum())}
    summary["outputs"] = {n:{"sha256":act023.sha(args.output/n), "bytes":(args.output/n).stat().st_size}
                          for n in ("external_predictions.csv","top200_predictions.csv","frozen_policy.json")}
    act023.write_json(args.output/"summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    for name, default in (("external",ROOT/"pft_act025_s_v3_20261123/run/external_predictions.csv"),
                          ("rebuild20",ROOT/"pft_act027_s_v3_rebuild_20261123/CODEX_MAC_ACT-027_SV3_REBUILD20_COMPARISON_20261123.csv"),
                          ("top200",ROOT/"pft_act024_s_v3_20261123/run/top200_predictions.csv"),
                          ("groups",ROOT/"pft_act021_s_v3_20261123/verified_groups.json"),
                          ("act023-run",ROOT/"pft_act023_s_v3_20261123/run"), ("output",OUTPUT)):
        parser.add_argument("--"+name,type=Path,default=default)
    parser.add_argument("--calendar-extra",type=Path)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps({"external_n":summary["external_n"],"top200_n":summary["top200"]["n"],
                      "actual_fit":summary["actual_fit"],"output":str(args.output)}))


if __name__ == "__main__":
    main()
