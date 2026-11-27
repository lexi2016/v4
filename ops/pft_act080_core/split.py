"""Forward split metadata isolated from causal features and cooldown."""

from bisect import bisect_left

from .core import CONFIG, ID_FIELDS


SPLIT_FIELDS = (
    *ID_FIELDS, "structure_episode_id", "calendar_fold", "episode_origin_fold",
    "purge", "embargo", "cross_period_episode", "assigned_fold", "split_exclusion_reasons",
)
SPLITS = CONFIG["splits"]
BOUNDARIES = (SPLITS["val_start"], SPLITS["oot_start"])
FOLDS = ("TRAIN", "VAL", "OOT")


def fold_for(day):
    if day < BOUNDARIES[0]:
        return "TRAIN"
    if day < BOUNDARIES[1]:
        return "VAL"
    return "OOT"


def split_evidence(bars, ledger):
    dates = [bar.trade_date for bar in bars]
    boundary_rows, purge_ranges, embargo_ranges = [], [], []
    for boundary in BOUNDARIES:
        ordinal = bisect_left(dates, boundary)
        before = min(ordinal, SPLITS["purge_sessions"])
        after = min(len(dates) - ordinal, SPLITS["embargo_sessions"])
        if ordinal == 0:
            status = "NO_BARS_BEFORE"
        elif ordinal == len(dates):
            status = "NO_BARS_ON_OR_AFTER"
        elif before < SPLITS["purge_sessions"] or after < SPLITS["embargo_sessions"]:
            status = "INSUFFICIENT_OBSERVED_SESSIONS"
        else:
            status = "FULL"
        purge_ranges.append(range(ordinal - before, ordinal))
        embargo_ranges.append(range(ordinal, ordinal + after))
        boundary_rows.append({
            "boundary": boundary,
            "first_on_or_after_obs_idx": ordinal if ordinal < len(dates) else None,
            "last_before_D": dates[ordinal - 1] if ordinal else None,
            "first_on_or_after_D": dates[ordinal] if ordinal < len(dates) else None,
            "observed_purge_sessions": before,
            "observed_embargo_sessions": after,
            "status": status,
        })
    rows = []
    for row in ledger:
        session = row["session_idx"]
        fold = fold_for(row["trade_date"])
        origin = fold_for(row["key_k_date"])
        purge = any(session in window for window in purge_ranges)
        embargo = any(session in window for window in embargo_ranges)
        crossing = origin != fold
        flags = (("PURGE", purge), ("EMBARGO", embargo), ("CROSS_PERIOD_EPISODE", crossing))
        rows.append({
            **{field: row[field] for field in ID_FIELDS},
            "structure_episode_id": row["structure_episode_id"],
            "calendar_fold": fold,
            "episode_origin_fold": origin,
            "purge": purge,
            "embargo": embargo,
            "cross_period_episode": crossing,
            "assigned_fold": None if purge or embargo or crossing else fold,
            "split_exclusion_reasons": "|".join(name for name, flag in flags if flag),
        })
    return rows, boundary_rows
