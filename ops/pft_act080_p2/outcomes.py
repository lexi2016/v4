"""Frozen observed-bar outcomes and summaries shared by benchmark and candidates."""

from collections import Counter
from statistics import fmean, median

from .contracts import METHOD


def pricing_outcomes(prices, session, cutoff_exclusive=None):
    dates, opened, closed, lows = prices
    entry_idx = session + 1
    cost = METHOD["fee"]
    entry = opened[entry_idx] if entry_idx < len(dates) else None

    def available(idx):
        return idx < len(dates) and (cutoff_exclusive is None or dates[idx] < cutoff_exclusive)

    result = {"entry_D": dates[entry_idx] if available(entry_idx) else None,
              "entry_open": entry if available(entry_idx) and entry is not None and entry > 0 else None}
    entry = result["entry_open"]
    for horizon in (2, 5, 10):
        end = session + horizon
        mature = entry is not None and available(end) and closed[end] > 0
        result[f"T{horizon}_D"] = dates[end] if available(end) else None
        result[f"T{horizon}"] = closed[end] / entry - 1 - cost if mature else None
    minimum = min(lows[entry_idx:session + 6]) if available(session + 5) else None
    mae = None if entry is None or minimum is None or minimum <= 0 else minimum / entry - 1 - cost
    result["MAE5"] = mae
    t2, t5 = result["T2"], result["T5"]
    result["tail_std"] = None if t2 is None or mae is None else t2 <= -0.05 or mae <= -0.07
    result["tail_aux"] = None if t5 is None else t5 <= -0.05
    return result


def summarize(rows):
    result = {
        "triggers": len(rows), "episodes": len({r["structure_episode_id"] for r in rows}),
        "stocks": len({r["security_id"] for r in rows}),
    }
    for metric in ("T2", "T5", "T10", "MAE5"):
        got = [r[metric] for r in rows if r[metric] is not None]
        result[f"{metric}_mature"] = len(got)
        result[f"{metric}_unknown"] = len(rows) - len(got)
        result[f"{metric}_mean"] = fmean(got) if got else None
        result[f"{metric}_median"] = median(got) if got else None
        if metric != "MAE5":
            result[f"{metric}_win_rate"] = sum(v > 0 for v in got) / len(got) if got else None
    for metric in ("tail_std", "tail_aux"):
        got = [r[metric] for r in rows if r[metric] is not None]
        result[f"{metric}_mature"] = len(got)
        result[f"{metric}_unknown"] = len(rows) - len(got)
        result[f"{metric}_count"] = sum(got)
        result[f"{metric}_rate"] = sum(got) / len(got) if got else None
    return result


def nonoverlap(rows):
    free = {}
    chosen = []
    for event in sorted(rows, key=lambda r: (r["security_id"], r["session_idx"], r["candidate_event_id"])):
        stock, session = event["security_id"], event["session_idx"]
        if session < free.get(stock, -1):
            continue
        chosen.append(event)
        free[stock] = session + METHOD["horizon_sessions"]
    return chosen
