"""Fixed-horizon ex-post research, isolated from qualification and image selection."""

from collections import Counter, defaultdict
from statistics import fmean, median

from ops.pft_act080_p2.outcomes import pricing_outcomes, summarize


MAX_HORIZON = 20
REFERENCE_HORIZON = 10
VICINITY = 10
ROUND_TRIP_COST = 0.003


def screen_clean(events, references, policy):
    retained, proof = [], []
    for row in events:
        stock, d = row["security_id"], row["session_idx"]
        held = True
        for sample, sample_day, reference in references.get(stock, ()):
            delta = d - reference
            nearby = abs(delta) <= VICINITY
            first = max(d, reference) + 1
            last = min(d + MAX_HORIZON, reference + REFERENCE_HORIZON)
            overlap = first <= last
            if not (nearby or overlap):
                continue
            held = False
            reasons = ("D_PLUS_MINUS_10" if nearby else "", "HOLDING_20_VS_10_OVERLAP" if overlap else "")
            proof.append({
                "policy": policy, "security_id": stock, "candidate_event_id": row["candidate_event_id"],
                "structure_episode_id": row["structure_episode_id"], "event_D": row["D"],
                "event_session_idx": d, "sample_id": sample, "sample_D": sample_day,
                "sample_session_idx": reference, "signed_session_gap": delta,
                "exclusion_reason": "|".join(reason for reason in reasons if reason),
                "overlap_start_session_idx": first if overlap else None,
                "overlap_end_session_idx": last if overlap else None,
            })
        if held:
            retained.append(row)
    if len(retained) + len({row["candidate_event_id"] for row in proof}) != len(events):
        raise ValueError(f"{policy}: exclusion conservation failure")
    return retained, proof


def outcomes(prices, session, cutoff_exclusive=None):
    values = pricing_outcomes(prices, session, cutoff_exclusive)
    dates, _, closed, _ = prices
    end, entry = session + MAX_HORIZON, values["entry_open"]
    available = end < len(dates) and (cutoff_exclusive is None or dates[end] < cutoff_exclusive)
    values["T20_D"] = dates[end] if available else None
    values["T20"] = closed[end] / entry - 1 - ROUND_TRIP_COST if (
        entry is not None and available and closed[end] > 0
    ) else None
    return values


def attach_outcomes(events, prices, cutoff_exclusive=None):
    for row in events:
        stock_prices = prices[row["security_id"]]
        dates = stock_prices[0]
        idx = row["session_idx"]
        if not 0 <= idx < len(dates) or dates[idx] != row["D"]:
            raise ValueError(f"row does not align to observed stock ordinal: {row['candidate_event_id']}")
        row.update(outcomes(stock_prices, idx, cutoff_exclusive))


def summary(rows):
    values = summarize(rows)
    mature = [row["T20"] for row in rows if row["T20"] is not None]
    values.update({
        "T20_mature": len(mature), "T20_unknown": len(rows) - len(mature),
        "T20_mean": fmean(mature) if mature else None,
        "T20_median": median(mature) if mature else None,
        "T20_win_rate": sum(v > 0 for v in mature) / len(mature) if mature else None,
    })
    return values


def nonoverlap(rows):
    """Greedy first-D on [D+1, D+20]; selection ignores return/maturity."""
    free = {}
    chosen = []
    for row in sorted(rows, key=lambda r: (r["security_id"], r["session_idx"], r["candidate_event_id"])):
        stock, d = row["security_id"], row["session_idx"]
        if d >= free.get(stock, -1):
            chosen.append(row)
            free[stock] = d + MAX_HORIZON
    return chosen


def robustness(policies, stocks, anchor_policy):
    reference = defaultdict(float)
    for row in policies[anchor_policy]:
        if row["T5"] is not None:
            reference[row["security_id"]] += row["T5"]
    top3 = sorted(reference, key=lambda stock: (-reference[stock], stock))[:3]
    rows, loso, worst = [], [], {}
    for policy, events in policies.items():
        # Summary input is already one FIRST per independent episode.
        if len({row["structure_episode_id"] for row in events}) != len(events):
            raise ValueError("robustness expected independent FIRST rows")
        for experiment, group in (
            ("NONOVERLAP_T20", nonoverlap(events)),
            ("EQUAL_WEIGHT_EPISODE", events),
            ("REMOVE_SHARED_TOP3_B1_T5_SUM", [row for row in events if row["security_id"] not in top3]),
        ):
            rows.append({"policy": policy, "scenario": experiment, **summary(group)})
        estimates = []
        for stock in stocks:
            subset = [row for row in events if row["security_id"] != stock]
            estimate = {
                "policy": policy, "removed_security_id": stock,
                "removed_triggers": len(events) - len(subset), **summary(subset),
            }
            loso.append(estimate)
            if estimate["T5_mean"] is not None:
                estimates.append(estimate)
        if estimates:
            worst[policy] = min(estimates, key=lambda r: (r["T5_mean"], r["removed_security_id"]))
    return rows, loso, {"top3": top3, "loso_worst_T5_mean": worst}


def fold_flows(events):
    answers = []
    for track in sorted({row["track"] for row in events}):
        track_rows = [row for row in events if row["track"] == track]
        for fold in ("ALL", "TRAIN", "VAL", "OOT", "EXCLUDED"):
            group = track_rows if fold == "ALL" else [row for row in track_rows if row["fold"] == fold]
            roles = Counter(row["accepted_role"] for row in group)
            answers.append({
                "track": track, "fold": fold, "raw": len(group), "rejected": roles[None],
                "accepted": len(group) - roles[None], "first": roles["FIRST"], "repeat": roles["REPEAT"],
                "stocks": len({row["security_id"] for row in group}),
            })
    return answers
