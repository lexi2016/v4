"""Selection group union (192 + backtest) & ST name-transition vs real entity conflict."""
from __future__ import annotations


def classify_name_change(old_name: str, new_name: str) -> tuple[str, bool]:
    """Return (status_code, eligible_candidate). Separates ST transitions from real entity conflicts."""
    clean_old = old_name.replace("*ST", "").replace("ST", "").strip()
    clean_new = new_name.replace("*ST", "").replace("ST", "").strip()
    if old_name == new_name:
        return ("NAME_MATCH", True)
    if clean_old and clean_old == clean_new:
        return ("NAME_CHANGED_ST_TRANSITION", True)
    return ("IDENTITY_CONFLICT_REAL", False)


def merge_selection_groups(group_192: list[str], group_backtest: list[str]) -> dict[str, str]:
    """Merge 192 and backtest lists into a deduplicated symbol -> group map."""
    s192 = set(group_192)
    sbt = set(group_backtest)
    merged: dict[str, str] = {}
    for sym in sorted(s192 | sbt):
        if sym in s192 and sym in sbt:
            merged[sym] = "both"
        elif sym in s192:
            merged[sym] = "192"
        else:
            merged[sym] = "backtest"
    return merged
