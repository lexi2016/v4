"""Frozen paired Hit@50 oracle for historical reconstruction only."""
from model194 import EXPOSED, FLAGS, require, number, top50, save

BOOTSTRAP = dict(method="NON_CIRCULAR_MOVING_BLOCK", block_dates=5,
                 replicates=2000, seed=194, percentiles=[2.5,97.5],
                 minimum_oof_dates=20, mean_delta_minimum=1.0, lower_ci_strict_minimum=0.0)


def moving_block_ci(deltas):
    import numpy as np
    n=len(deltas)
    if n<5:
        return None
    values=np.asarray(deltas,dtype=float)
    starts=np.random.default_rng(194).integers(0,n-5+1,size=(2000,(n+4)//5))
    samples=values[(starts[:,:,None]+np.arange(5)).reshape(2000,-1)[:,:n]].mean(axis=1)
    return [float(x) for x in np.percentile(samples,[2.5,97.5])]


def evaluate(dates, baseline, candidate, truth, calendar):
    require(len(dates)==len(set(dates)) and not set(dates)&EXPOSED,"EVALUATION_DATES_INVALID")
    by_key={(r["target_date"],r["code"]):int(number(r["label"])) for r in truth}
    require(len(by_key)==len(truth),"DUPLICATE_TRUTH_KEY")
    by_date={r["target_date"]:r for r in calendar}
    require(len(by_date)==len(calendar),"DUPLICATE_CALENDAR_DATE")
    counts={}
    for d in dates:
        require(d in by_date,"MISSING_DATE_NOT_ZERO")
        count=by_date[d]["truth_positive_denominator"]
        require(count is not None and count!="","EVALUATED_DENOMINATOR_MISSING")
        counts[d]=int(count)
    pools=[]
    for predictions in (baseline,candidate):
        require(set(r["target_date"] for r in predictions)<=set(dates),"PREDICTION_DATE_OUTSIDE_OOF")
        selected=top50(predictions)
        require(len(selected)==len(predictions),"INPUT_MUST_BE_TOP50")
        pools.append({d:{r["code"] for r in selected if r["target_date"]==d} for d in dates})
    daily=[]
    for d in dates:
        require(d in counts,"MISSING_DATE_NOT_ZERO")
        positives={c for (dt,c),label in by_key.items() if dt==d and label==1}
        require(len(positives)==counts[d],"TRUTH_DENOMINATOR_DRIFT")
        b,c=pools[0][d],pools[1][d]
        require(all((d,code) in by_key for code in b|c),"SELECTED_KEY_MISSING_TRUTH")
        bh,ch=len(b&positives),len(c&positives)
        daily.append(dict(target_date=d,baseline_hits=bh,candidate_hits=ch,delta_hits=ch-bh,
                          common_hits=len(b&c&positives),new_hits=len((c-b)&positives),
                          lost_hits=len((b-c)&positives),baseline_selected=len(b),candidate_selected=len(c),
                          fixed_selection_slots=50,truth_positive_denominator=counts[d]))
    require(daily,"EMPTY_OOF")
    delta=[r["delta_hits"] for r in daily];mean=sum(delta)/len(delta);ci=moving_block_ci(delta)
    enough=len(daily)>=20
    passed=enough and mean>=1.0 and ci is not None and ci[0]>0
    status="EFFECT_GATE_CANDIDATE_DIRECTION_ONLY" if passed else ("NO_BREAKTHROUGH" if enough else "CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES")
    slots=50*len(daily);denom=sum(r["truth_positive_denominator"] for r in daily)
    result=dict(status=status,evidence_level="DIRECTION_ONLY",sealed_data=False,primary_mean_delta_hits=mean,
                paired_block_95_ci=ci,bootstrap=BOOTSTRAP,oof_dates=len(daily),fixed_selection_slots=slots,
                truth_positive_denominator=denom,daily=daily,**FLAGS)
    for arm in ("baseline","candidate"):
        hits=sum(r[arm+"_hits"] for r in daily);actual=sum(r[arm+"_selected"] for r in daily)
        result[arm]=dict(hits=hits,actual_selection_slots=actual,precision_at_fixed50=hits/slots,
                         precision_at_actual=hits/actual if actual else None,recall=hits/denom if denom else None)
    return result


def write_report(directory, result, coverage):
    from pathlib import Path
    directory=Path(directory)
    save(directory/"OOF_METRICS.json",{**result,"coverage":coverage})
    text=("# 194-R0 重建研究结果\n\n"
          f"状态：{result['status']}；证据：DIRECTION_ONLY / PUBLICATION_TIME_RECONSTRUCTION。\n\n"
          f"OOF {result['oof_dates']}日，日均配对ΔHit@50={result['primary_mean_delta_hits']:.6f}，"
          f"5日非环形moving-block 95%CI={result['paired_block_95_ci']}。\n\n"
          f"baseline={result['baseline']}\n\n194={result['candidate']}\n\n"
          f"固定slots={result['fixed_selection_slots']}；正例分母={result['truth_positive_denominator']}。\n\n"
          f"覆盖/排除/失败：{coverage}\n\n无sealed/live/生产/交易结论；未来输入不存在时不提供虚构未来名单。\n")
    with (directory/"REPORT.md").open("x") as f:f.write(text)
