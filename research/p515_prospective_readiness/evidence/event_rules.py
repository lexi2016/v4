"""Prefix-only research families, not authenticated original capital identities."""
from collections import deque
import math
import statistics

RULE = "P5146_EVENT_RULE_R2"
MATURE_FAMILY = {"FAILED_SUPPORT", "FAILED_RISK", "EXPIRED_NO_ADVANCE", "EXPIRED_PULLBACK", "EXPIRED_FAMILY"}
MATURE_PULLBACK = {"SUCCESS_RESTART", "FAILED_SUPPORT", "FAILED_RISK", "EXPIRED_PULLBACK"}


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (ValueError, TypeError):
        return False


def _valid(r):
    vals = [r.get(k) for k in ("open", "high", "low", "close", "volume")]
    if not all(_finite(v) for v in vals):
        return False
    o, h, l, c, v = map(float, vals)
    return min(o, h, l, c, v) > 0 and l <= min(o, c) <= max(o, c) <= h


def _median(v):
    return statistics.median(v) if v else None


def _mean(v):
    return statistics.mean(v) if v else None


def _profile(completed, date, current_depth):
    # A family is available only after a complete observed terminal condition.
    valid = [x for x in completed if x["outcome"] in MATURE_FAMILY and x["end_date"] < date]
    pull = [x for x in valid if x["final_pullback_depth_low"] is not None]
    depths = [x["final_pullback_depth_low"] for x in pull]
    lengths = [x["pullback_sessions"] for x in pull]
    vr = [x["pullback_mean_volume_over_wave"] for x in pull
          if x["pullback_mean_volume_over_wave"] is not None]
    advance = [x["advance_delay_sessions"] for x in valid if x["advance_delay_sessions"] is not None]
    n = len(valid)
    pbn = sum(x["completed_pullback_count"] for x in valid)
    return {
        "profile_prior_event_count": n,
        "profile_prior_family_count": n,
        "profile_prior_pullback_count": pbn,
        "profile_prior_families_with_pullback": len(pull),
        "profile_pullback_confidence": ("INSUFFICIENT" if not pull else
            "LOW_ONE_FAMILY" if len(pull) == 1 else "DESCRIPTIVE_NOT_VALIDATED"),
        "profile_shared_pullback_fallback_required": len(pull) < 2,
        "profile_confidence": "LOW_ONE_FAMILY" if n == 1 else ("INSUFFICIENT" if n == 0 else "DESCRIPTIVE_NOT_VALIDATED"),
        "profile_first_origin_date": valid[0]["origin_key_k_date"] if valid else None,
        "profile_latest_event_id": valid[-1]["event_id"] if valid else None,
        "profile_latest_end_date": valid[-1]["end_date"] if valid else None,
        "profile_latest_outcome": valid[-1]["outcome"] if valid else None,
        "profile_build_activity_volume_ratio_median": _median([x["activity_volume_ratio"] for x in valid]),
        "profile_build_advance_delay_median": _median(advance),
        "profile_pullback_depth_low_min": min(depths) if depths else None,
        "profile_pullback_depth_low_max": max(depths) if depths else None,
        "profile_pullback_depth_low_median": _median(depths),
        "profile_pullback_length_median": _median(lengths),
        "profile_pullback_volume_over_wave_median": _median(vr),
        "profile_current_depth_percentile": (sum(d <= current_depth for d in depths) / len(depths))
            if len(depths) >= 2 and current_depth is not None else None,
        "profile_prior_restart_fraction": sum(x["completed_restart_count"] > 0 for x in valid) / n if n else None,
        "profile_prior_failed_risk_fraction": sum(x["outcome"] in ("FAILED_RISK","FAILED_SUPPORT") for x in valid) / n if n else None,
        "profile_standard_version": RULE + "_COMPLETED_FAMILY_LAST_PB",
        "profile_shared_fallback_required": n < 2,
    }


def run_symbol(symbol, rows, calendar):
    """Each observation reads no bar or label after its own candidate_date."""
    cal = {str(d): i for i, d in enumerate(calendar)}
    prior = deque(maxlen=20)
    completed, observations, candidates, pullbacks = [], [], [], []
    current, prev_date = None, None
    seen = set()

    def finish_pullback(outcome, date):
        e=current
        if e is None or e["pullback_id"] is None:
            return
        mature = date + "T18:00:00+08:00" if outcome in MATURE_PULLBACK else None
        rec = {
            "symbol":symbol, "event_id":e["event_id"], "family_id":e["family_id"],
            "origin_key_k_date":e["origin_key_k_date"], "pullback_id":e["pullback_id"],
            "pullback_index":e["pullback_index"], "candidate_date":e["pullback_first_date"],
            "wave_start":e["wave_start"], "wave_end":e["wave_end_date"],
            "wave_end_confirmed_at":e["wave_end_confirmed_at"], "frozen_wave_high":e["frozen_wave_high"],
            "origin_high":e["origin_high"], "origin_low":e["origin_low"],
            "end_date":date if mature else None, "observed_boundary_date":date,
            "outcome":outcome, "outcome_mature_at":mature,
            "pullback_sessions":e["pullback_sessions"],
            "final_pullback_depth_low":e["final_pullback_depth_low"],
            "final_pullback_depth_close":e["final_pullback_depth_close"],
            "pullback_mean_volume_over_wave": (_mean(e["pullback_volume"]) / _mean(e["wave_volume"]))
                if e["pullback_volume"] and _mean(e["wave_volume"]) else None,
            "research_low_volume_key_date":e["research_low_volume_key_date"],
            "research_breakout_key_date":date if outcome=="SUCCESS_RESTART" else None,
            "stage_label_source":"RESEARCH_RULE_WEAK_LABEL", "rule_version":RULE,
        }
        pullbacks.append(rec)
        if mature:
            e["completed_pullbacks"].append(rec)

    def finish_family(outcome,date,reason):
        nonlocal current
        if current is None:
            return
        e=current
        matured=e["completed_pullbacks"]
        last=matured[-1] if matured else {}
        end=date if outcome in MATURE_FAMILY else None
        completed.append({
            "symbol":symbol,"event_id":e["event_id"],"family_id":e["family_id"],
            "origin_key_k_date":e["origin_key_k_date"],"origin_key_k_type":"RESEARCH_ACTIVITY_CANDIDATE",
            "origin_high":e["origin_high"],"origin_low":e["origin_low"],"origin_close":e["origin_close"],
            "origin_volume":e["origin_volume"],"activity_volume_ratio":e["activity_volume_ratio"],
            "pre_structure_start":e["pre_structure_start"],"pre_structure_end":e["pre_structure_end"],
            "pre_structure_high":e["pre_structure_high"],"pre_structure_low":e["pre_structure_low"],
            "advance_confirmed_at":e["advance_confirmed_at"],"advance_delay_sessions":e["advance_delay_sessions"],
            "completed_pullback_count":len(matured),
            "completed_restart_count":sum(p["outcome"]=="SUCCESS_RESTART" for p in matured),
            "last_pullback_id":last.get("pullback_id"),"pullback_sessions":last.get("pullback_sessions"),
            "final_pullback_depth_low":last.get("final_pullback_depth_low"),
            "final_pullback_depth_close":last.get("final_pullback_depth_close"),
            "pullback_mean_volume_over_wave":last.get("pullback_mean_volume_over_wave"),
            "end_date":end,"observed_boundary_date":date,"outcome":outcome,"end_reason":reason,
            "outcome_mature_at":end+"T18:00:00+08:00" if end else None,
            "first_known_at":e["origin_key_k_date"]+"T18:00:00+08:00",
            "source_identity":"RESEARCH_ACTIVITY_PROXY_NOT_ORIGINAL_CAPITAL_EVENT",
            "true_capital_identity":"UNKNOWN","original_preK":None,
            "historical_source_available_at":"UNKNOWN","rule_version":RULE,
        })
        current=None

    for raw in rows:
        r=dict(raw); d=str(r["trade_date"])
        if d in seen or (prev_date is not None and d<=prev_date):
            raise ValueError(f"DUPLICATE_OR_NONMONOTONIC:{symbol}:{d}")
        seen.add(d)
        if d not in cal:
            raise ValueError(f"DATE_NOT_IN_EXCHANGE_CALENDAR:{symbol}:{d}")
        if prev_date is not None and cal[d]-cal[prev_date]!=1:
            finish_pullback("UNKNOWN_DATA_GAP",d)
            finish_family("UNKNOWN_DATA_GAP",d,"MISSING_EXCHANGE_SESSION")
            prior.clear()
        if not _valid(r):
            finish_pullback("UNKNOWN_BAD_BAR",d)
            finish_family("UNKNOWN_BAD_BAR",d,"INVALID_OHLCV")
            prior.clear();prev_date=d
            continue
        r={**r,**{k:float(r[k]) for k in ("open","high","low","close","volume")}}
        prev=prior[-1] if prior else None
        median_vol=_median([x["volume"] for x in prior]) if len(prior)==20 else None
        vr=r["volume"]/median_vol if median_vol and median_vol>0 else None
        late=(r["close"]/prior[0]["close"]-1)>.25 if len(prior)==20 else None
        activity=bool(len(prior)==20 and vr>=1.5 and r["close"]>r["open"] and r["close"]>prev["close"])
        stage="NO_RESEARCH_EVENT";outcome=None;pb_outcome=None
        if current is None and activity:
            if late:
                stage="ADVANCE_LATE_ACTIVITY"
            else:
                eid=f"{RULE}:{symbol}:{d}"; pre=list(prior)[-10:]
                current={"symbol":symbol,"event_id":eid,"family_id":eid,"origin_key_k_date":d,
                    "origin_high":r["high"],"origin_low":r["low"],"origin_close":r["close"],
                    "origin_volume":r["volume"],"activity_volume_ratio":vr,
                    "pre_structure_start":str(pre[0]["trade_date"]),"pre_structure_end":str(pre[-1]["trade_date"]),
                    "pre_structure_high":max(x["high"] for x in pre),"pre_structure_low":min(x["low"] for x in pre),
                    "advance_confirmed_at":None,"advance_delay_sessions":None,
                    "wave_start":d,"wave_high":r["high"],"wave_high_date":d,"peak_since_origin":r["high"],
                    "wave_volume":[r["volume"]],"wave_end_date":None,"wave_end_confirmed_at":None,
                    "frozen_wave_high":None,"pullback_id":None,"pullback_index":0,"pullback_first_date":None,
                    "pullback_sessions":None,"research_low_volume_key_date":None,
                    "final_pullback_depth_low":None,"final_pullback_depth_close":None,
                    "pullback_min_low":None,"pullback_min_close":None,"pullback_volume":[],
                    "yang_volume":[r["volume"]],"yin_volume":[],"completed_pullbacks":[]}
                stage="BUILDUP_STRUCTURE_CANDIDATE"
        if current is not None and current["origin_key_k_date"]!=d:
            e=current
            age=cal[d]-cal[e["origin_key_k_date"]]
            risk=(median_vol is not None and e["peak_since_origin"]>=1.15*e["origin_close"] and
                r["close"]<r["open"] and r["close"]<prev["close"] and vr>=1.5)
            support_failure=r["close"]<e["origin_low"]
            if r["close"]>r["open"]:e["yang_volume"].append(r["volume"])
            elif r["close"]<r["open"]:e["yin_volume"].append(r["volume"])
            if e["pullback_id"] is not None:
                e["pullback_min_low"]=min(e["pullback_min_low"],r["low"])
                e["pullback_min_close"]=min(e["pullback_min_close"],r["close"])
                e["pullback_volume"].append(r["volume"])
                e["pullback_sessions"]=cal[d]-cal[e["pullback_first_date"]]+1
            if risk:
                stage="DISTRIBUTION_RISK_CANDIDATE";outcome=("FAILED_RISK","HIGH_VOLUME_BEAR_AFTER_ADVANCE_PROXY")
                if e["pullback_id"] is not None:pb_outcome="FAILED_RISK"
            elif support_failure:
                stage="STRUCTURE_FAILED";outcome=("FAILED_SUPPORT","CLOSE_BELOW_IMMUTABLE_ORIGIN_LOW")
                if e["pullback_id"] is not None:pb_outcome="FAILED_SUPPORT"
            elif e["advance_confirmed_at"] is None:
                if r["close"]>e["origin_high"]:
                    e["advance_confirmed_at"]=d;e["advance_delay_sessions"]=age
                    stage="ADVANCE_AFTER_ACTIVITY"
                else:
                    stage="BUILDUP_STRUCTURE_CANDIDATE"
                if r["high"]>e["wave_high"]:e["wave_high"],e["wave_high_date"]=r["high"],d
                e["wave_volume"].append(r["volume"])
            elif e["pullback_id"] is None:
                if r["close"]<prev["close"] and r["close"]<e["wave_high"]:
                    e["wave_end_date"]=e["wave_high_date"];e["wave_end_confirmed_at"]=d
                    e["frozen_wave_high"]=e["wave_high"];e["pullback_index"]+=1
                    e["pullback_id"]=e["family_id"]+":PB"+str(e["pullback_index"])
                    e["pullback_first_date"]=d;e["pullback_min_low"]=r["low"]
                    e["pullback_min_close"]=r["close"];e["pullback_volume"]=[r["volume"]]
                    e["pullback_sessions"]=1;e["research_low_volume_key_date"]=None
                    stage="SAME_EVENT_PULLBACK"
                else:
                    if r["high"]>e["wave_high"]:e["wave_high"],e["wave_high_date"]=r["high"],d
                    e["wave_volume"].append(r["volume"]);stage="ADVANCE_AFTER_ACTIVITY"
            else:
                if r["close"]>e["frozen_wave_high"]:
                    stage="RESTART_AFTER_PULLBACK";pb_outcome="SUCCESS_RESTART"
                else:stage="SAME_EVENT_PULLBACK"
            if e["pullback_id"] is not None:
                e["final_pullback_depth_low"]=(e["frozen_wave_high"]-e["pullback_min_low"])/e["frozen_wave_high"]
                e["final_pullback_depth_close"]=(e["frozen_wave_high"]-e["pullback_min_close"])/e["frozen_wave_high"]
                if len(prior)>=4 and r["volume"]<=min(x["volume"] for x in list(prior)[-4:]):
                    e["research_low_volume_key_date"]=d
                if outcome is None and pb_outcome is None and e["pullback_sessions"]>=15:
                    stage="PULLBACK_EXPIRED";pb_outcome="EXPIRED_PULLBACK"
                    outcome=("EXPIRED_PULLBACK","15_EXCHANGE_SESSIONS_WITHOUT_RESTART")
            if outcome is None and e["advance_confirmed_at"] is None and age>=40:
                outcome=("EXPIRED_NO_ADVANCE","40_EXCHANGE_SESSIONS_WITHOUT_ADVANCE")
            if outcome is None and age>=60 and (e["pullback_id"] is None or pb_outcome=="SUCCESS_RESTART"):
                outcome=("EXPIRED_FAMILY","60_EXCHANGE_SESSIONS_RESEARCH_FAMILY_LIMIT")
            e["peak_since_origin"]=max(e["peak_since_origin"],r["high"])
        if current is not None:
            e=current;pb=e["pullback_id"] is not None
            depth=(e["frozen_wave_high"]-r["close"])/e["frozen_wave_high"] if pb else None
            same=e["completed_pullbacks"];last=same[-1] if same else {}
            row={"symbol":symbol,"candidate_date":d,"stage":stage,"event_id":e["event_id"],"family_id":e["family_id"],
                "origin_key_k_date":e["origin_key_k_date"],"origin_key_k_type":"RESEARCH_ACTIVITY_CANDIDATE",
                "origin_high":e["origin_high"],"origin_low":e["origin_low"],
                "original_capital_key_date":None,"original_preK":None,
                "research_pre_structure_start":e["pre_structure_start"],"research_pre_structure_end":e["pre_structure_end"],
                "research_activity_key_date":e["origin_key_k_date"],"research_low_volume_key_date":e["research_low_volume_key_date"],
                "research_breakout_key_date":d if pb_outcome=="SUCCESS_RESTART" else None,
                "original_formula_breakout_today":r.get("user_v1_breakout"),
                "wave_start":e["wave_start"],"wave_end":e["wave_end_date"],"wave_end_confirmed_at":e["wave_end_confirmed_at"],
                "frozen_wave_high":e["frozen_wave_high"],"pullback_id":e["pullback_id"],
                "pullback_index":e["pullback_index"] if pb else None,"pullback_sessions":e["pullback_sessions"] if pb else None,
                "first_pullback_observation":bool(pb and d==e["pullback_first_date"]),
                "current_depth_close":depth,"deepest_seen_low":e["final_pullback_depth_low"] if pb else None,
                "deepest_seen_close":e["final_pullback_depth_close"] if pb else None,
                "close_over_origin_high_minus1":r["close"]/e["origin_high"]-1,
                "close_over_origin_low_minus1":r["close"]/e["origin_low"]-1,
                "volume_over_wave_mean":r["volume"]/_mean(e["wave_volume"]) if _mean(e["wave_volume"]) else None,
                "volume_over_origin":r["volume"]/e["origin_volume"],"volume_over_prior20_median":vr,
                "yang_volume_mean_over_yin_mean":(_mean(e["yang_volume"])/_mean(e["yin_volume"])) if e["yin_volume"] else None,
                "trajectory_prior_pullback_count":len(same),"trajectory_latest_pullback_id":last.get("pullback_id"),
                "trajectory_latest_pullback_end_date":last.get("end_date"),"trajectory_latest_pullback_outcome":last.get("outcome"),
                "trajectory_latest_pullback_depth_low":last.get("final_pullback_depth_low"),
                "current_open":r["open"],"current_high":r["high"],"current_low":r["low"],"current_close":r["close"],
                "current_volume":r["volume"],"first_known_at":e["origin_key_k_date"]+"T18:00:00+08:00",
                "feature_available_at":d+"T18:00:00+08:00","historical_source_available_at":"UNKNOWN",
                "stage_label_source":"RESEARCH_RULE_WEAK_LABEL","source_basis":"RETROSPECTIVE_QFQ_ASOF_20261109_NONPIT",
                "rule_version":RULE,"terminal_observed_today":outcome[0] if outcome else None}
            row.update(_profile(completed,d,depth));observations.append(row)
            if row["first_pullback_observation"]:candidates.append(row.copy())
            if pb_outcome:
                finish_pullback(pb_outcome,d)
                if pb_outcome=="SUCCESS_RESTART" and outcome is None:
                    e["wave_start"]=d;e["wave_high"]=r["high"];e["wave_high_date"]=d;e["wave_volume"]=[r["volume"]]
                    e["wave_end_date"]=None;e["wave_end_confirmed_at"]=None;e["frozen_wave_high"]=None
                    e["pullback_id"]=None;e["pullback_first_date"]=None;e["pullback_sessions"]=None
                    e["pullback_min_low"]=None;e["pullback_min_close"]=None;e["pullback_volume"]=[]
                    e["final_pullback_depth_low"]=None;e["final_pullback_depth_close"]=None
                    e["research_low_volume_key_date"]=None
            if outcome:finish_family(outcome[0],d,outcome[1])
        elif stage=="ADVANCE_LATE_ACTIVITY":
            observations.append({"symbol":symbol,"candidate_date":d,"stage":stage,"event_id":None,"family_id":None,
                "feature_available_at":d+"T18:00:00+08:00","stage_label_source":"RESEARCH_RULE_WEAK_LABEL","rule_version":RULE})
        prior.append(r);prev_date=d
    if current:
        finish_pullback("UNKNOWN_OPEN_AT_SNAPSHOT",prev_date)
        finish_family("UNKNOWN_OPEN_AT_SNAPSHOT",prev_date,"NO_END_OBSERVED")
    return observations,candidates,completed,pullbacks
