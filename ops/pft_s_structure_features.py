"""Deterministic, causal PFT-S yellow-line and prior-key-K features."""
from __future__ import annotations

import math
from typing import Any


SCHEMA = "pft_s_structure_repair.v1"
YELLOW_WINDOW_SESSIONS = 16  # D plus 15 prior trading sessions
KEY_SEARCH_PRIOR_SESSIONS = 40
KEY_MIN_RETURN = 0.035
KEY_MIN_RELATIVE_VOLUME = 1.2
KEY_INITIAL_HOLD_SESSIONS = 5
STRUCTURE_REPAIR_CONTRACT = {
    "schema": SCHEMA,
    "yellow_window_sessions": YELLOW_WINDOW_SESSIONS,
    "yellow_break_rule": "two_consecutive_closes_strictly_below_observed_yellow_line",
    "yellow_repair_rule": "two_consecutive_closes_strictly_above_observed_yellow_line",
    "yellow_equal_close_state": "ON_LINE_NOT_BELOW_OR_REPAIRED",
    "yellow_missing_encoding": -1,
    "key_k_search_prior_sessions": KEY_SEARCH_PRIOR_SESSIONS,
    "key_k_min_return": KEY_MIN_RETURN,
    "key_k_min_relative_prev5_volume": KEY_MIN_RELATIVE_VOLUME,
    "key_k_D_in_anchor_search": False,
    "key_k_initial_hold_sessions": KEY_INITIAL_HOLD_SESSIONS,
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _status(value: int) -> str:
    return {1: "TRUE", 0: "FALSE", -1: "UNKNOWN"}[value]


def _tri(value: bool | None) -> int:
    return -1 if value is None else int(value)


def _date(row: dict[str, Any]) -> str:
    return str(row.get("trade_date", ""))


def _yellow_relation(row: dict[str, Any]) -> str:
    close = _number(row.get("close"))
    yellow = _number(row.get("zge_yellow_line"))
    if close is None or yellow is None or yellow <= 0:
        return "UNKNOWN"
    if close < yellow:
        return "BELOW"
    if close > yellow:
        return "ABOVE"
    return "ON"


def _yellow_state(
    window: list[dict[str, Any]], target_date: str, *, prior_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    prior_rows = prior_rows or []
    relations = [_yellow_relation(row) for row in window]
    expected = YELLOW_WINDOW_SESSIONS
    known_count = sum(value != "UNKNOWN" for value in relations)
    complete = len(window) == expected and known_count == expected
    events: list[dict[str, Any]] = []
    index = 0
    while index < len(relations):
        if relations[index] != "BELOW":
            index += 1
            continue
        first = index
        while index + 1 < len(relations) and relations[index + 1] == "BELOW":
            index += 1
        if index - first + 1 >= 2:
            prior_relation = _yellow_relation(prior_rows[-1]) if prior_rows else "UNKNOWN"
            clipped_left = first == 0 and prior_relation in {"BELOW", "UNKNOWN"}
            start_date = _date(window[first])
            confirm_date = _date(window[first + 1])
            confirm_yellow = _number(window[first + 1].get("zge_yellow_line"))
            start_known = True
            if clipped_left:
                full_relations = [_yellow_relation(row) for row in prior_rows]
                cursor = len(full_relations) - 1
                while cursor >= 0 and full_relations[cursor] == "BELOW":
                    cursor -= 1
                if cursor < 0 or (cursor >= 0 and full_relations[cursor] == "UNKNOWN"):
                    # The run reaches the available panel boundary or a missing
                    # line value, so its actual start and confirmation are unknown.
                    start_date = None
                    confirm_date = None
                    confirm_yellow = None
                    start_known = False
                else:
                    first_full_index = cursor + 1
                    full_rows = prior_rows + window
                    start_date = _date(full_rows[first_full_index])
                    confirm_date = _date(full_rows[first_full_index + 1])
                    confirm_yellow = _number(full_rows[first_full_index + 1].get("zge_yellow_line"))
            confirm = first + 1
            events.append({
                "start_index": first,
                "confirm_index": confirm,
                "end_index": index,
                "start_date": start_date,
                "confirm_date": confirm_date,
                "start_known": start_known,
                "clipped_left": clipped_left,
                "end_date": _date(window[index]),
                "yellow_at_confirm": confirm_yellow,
            })
        index += 1

    historical_tri = 1 if events else (0 if complete else -1)
    latest = events[-1] if events else None
    repair_tri = -1
    pending_tri = -1
    repair_state = "NOT_APPLICABLE"
    repair_date = None
    if latest is not None:
        repair_tri = 0
        pending_tri = 0
        after = latest["confirm_index"] + 1
        post_event = relations[after:]
        recovery_evidence = any(value in {"ABOVE", "ON"} for value in post_event)
        incomplete_after_event = "UNKNOWN" in post_event
        for j in range(after, len(relations) - 1):
            if relations[j] == relations[j + 1] == "ABOVE":
                repair_tri = 1
                pending_tri = 0
                repair_state = "REPAIRED_TWO_CONSECUTIVE_ABOVE"
                repair_date = _date(window[j + 1])
                break
        if repair_tri == 0 and incomplete_after_event:
            repair_tri = -1
            pending_tri = -1
            repair_state = "PENDING_OR_REPAIRED_UNKNOWN_DUE_TO_LINE_GAP" if recovery_evidence else "UNKNOWN_DUE_TO_LINE_GAP"
        elif repair_tri == 0 and recovery_evidence:
            pending_tri = 1
            repair_state = "PENDING_REPAIR_ONE_ABOVE_OR_EQUAL"
        elif repair_tri == 0:
            repair_state = "UNREPAIRED_NO_ABOVE_OR_EQUAL_CLOSE"

    current_relation = relations[-1] if relations else "UNKNOWN"
    prior_relation = relations[-2] if len(relations) > 1 else "UNKNOWN"
    current_below_count: int | None
    current_below_observed_count: int | None
    current_below_duration_status: str
    if current_relation == "UNKNOWN":
        current_below_count = None
        current_below_observed_count = None
        current_below_duration_status = "CURRENT_RELATION_UNKNOWN"
    elif current_relation != "BELOW":
        current_below_count = 0
        current_below_observed_count = 0
        current_below_duration_status = "NOT_CURRENTLY_BELOW"
    else:
        observed_count = 0
        cursor = len(relations) - 1
        while cursor >= 0 and relations[cursor] == "BELOW":
            observed_count += 1
            cursor -= 1
        current_below_observed_count = observed_count
        if cursor >= 0 and relations[cursor] == "UNKNOWN":
            current_below_count = None
            current_below_duration_status = "MISSING_PREVIOUS_RELATION"
        elif cursor < 0:
            current_below_count = None
            current_below_duration_status = "LEFT_CENSORED_WINDOW"
        else:
            current_below_count = observed_count
            current_below_duration_status = "KNOWN"

    if current_relation == "BELOW" and current_below_observed_count is not None and current_below_observed_count >= 2:
        # Two observed D-ending closes establish an active break even when
        # an older missing/censored row makes the total duration unknown.
        active_tri = 1
    elif current_below_count is None:
        active_tri = -1
    else:
        active_tri = int(current_below_count >= 2)

    if current_relation == "ABOVE" and prior_relation == "BELOW":
        if (latest is not None and repair_tri == 0
                and latest["end_index"] == len(relations) - 2):
            first_reclaim_tri = 1
        elif historical_tri == 0:
            first_reclaim_tri = 0
        elif latest is not None and repair_tri == 1:
            first_reclaim_tri = 0
        else:
            first_reclaim_tri = -1
    elif current_relation == "UNKNOWN" or prior_relation == "UNKNOWN":
        first_reclaim_tri = -1
    else:
        first_reclaim_tri = 0

    current_yellow = _number(window[-1].get("zge_yellow_line")) if window else None
    current_close = _number(window[-1].get("close")) if window else None
    features = {
        "yellow_line_D_available": float(current_yellow is not None and current_yellow > 0),
        "yellow_history_known_fraction": known_count / expected,
        "yellow_2below_historical_tri": float(historical_tri),
        "yellow_latest_event_repaired_tri": float(repair_tri),
        "yellow_pending_repair_tri": float(pending_tri),
        "yellow_active_confirmed_break_tri": float(active_tri),
        "yellow_first_reclaim_candidate_tri": float(first_reclaim_tri),
        "yellow_current_below_run_count": float(current_below_count if current_below_count is not None else -1),
    }
    diagnostic = {
        "schema": SCHEMA,
        "target_date": target_date,
        "yellow_window_expected_sessions": expected,
        "yellow_window_observed_sessions": len(window),
        "yellow_line_known_sessions": known_count,
        "yellow_window_complete": complete,
        "yellow_current_close": current_close,
        "yellow_current_value": current_yellow,
        "yellow_current_relation": current_relation,
        "yellow_historical_completed_2below": _status(historical_tri),
        "yellow_latest_event_start_date": latest["start_date"] if latest else None,
        "yellow_latest_event_confirmed_date": latest["confirm_date"] if latest else None,
        "yellow_latest_event_start_known": latest["start_known"] if latest else None,
        "yellow_latest_event_clipped_left": latest["clipped_left"] if latest else False,
        "yellow_latest_event_window_observed_start_date": (
            _date(window[latest["start_index"]]) if latest else None
        ),
        "yellow_latest_event_window_observed_confirm_date": (
            _date(window[latest["confirm_index"]]) if latest else None
        ),
        "yellow_latest_event_end_date": latest["end_date"] if latest else None,
        "yellow_latest_event_yellow_at_confirmation": latest["yellow_at_confirm"] if latest else None,
        "yellow_latest_event_repaired": _status(repair_tri) if latest else "NOT_APPLICABLE",
        "yellow_latest_event_repair_state": repair_state,
        "yellow_latest_event_pending_repair": _status(pending_tri) if latest else "NOT_APPLICABLE",
        "yellow_repaired_date": repair_date,
        "yellow_current_below_consecutive_count": current_below_count,
        "yellow_current_below_observed_consecutive_count": current_below_observed_count,
        "yellow_current_below_duration_status": current_below_duration_status,
        "yellow_current_below_consecutive_status": "UNKNOWN" if current_below_count is None else "KNOWN",
        "yellow_active_confirmed_break": _status(active_tri),
        "yellow_first_reclaim_candidate": _status(first_reclaim_tri),
        "yellow_single_day_below_warning": bool(current_below_count == 1) if current_below_count is not None else None,
        "tri_state_encoding": {"TRUE": 1, "FALSE": 0, "UNKNOWN": -1},
    }
    return features, diagnostic


def _key_k_state(prefix: list[dict[str, Any]], target_date: str) -> tuple[dict[str, float], dict[str, Any]]:
    current = prefix[-1]
    close_d = _number(current.get("close"))
    prior = prefix[-KEY_SEARCH_PRIOR_SESSIONS - 1:-1]
    anchor = None
    for row in reversed(prior):
        i = prefix.index(row)
        if i < 5:
            continue
        close = _number(row.get("close"))
        prev_close = _number(prefix[i - 1].get("close"))
        volume = _number(row.get("vol"))
        previous_volumes = [_number(item.get("vol")) for item in prefix[i - 5:i]]
        if (close is None or prev_close is None or prev_close <= 0 or volume is None
                or any(value is None for value in previous_volumes)):
            continue
        prior_mean = sum(value for value in previous_volumes if value is not None) / 5.0
        if prior_mean <= 0:
            continue
        return_pct = close / prev_close - 1.0
        relative_volume = volume / prior_mean
        if return_pct >= KEY_MIN_RETURN and relative_volume >= KEY_MIN_RELATIVE_VOLUME:
            anchor = {
                "index": i,
                "row": row,
                "return_pct": return_pct,
                "relative_volume": relative_volume,
                "previous5_mean_volume": prior_mean,
            }
            break

    features = {
        "key_k_anchor_available": float(anchor is not None),
        "key_k_relative_prev5_volume": -1.0,
        "key_k_distance_to_low_pct": -1.0,
        "key_k_D_low_vs_anchor_low_pct": -1.0,
        "key_k_close_above_body_mid_tri": -1.0,
        "key_k_prior_close_break_tri": -1.0,
        "key_k_current_under_low_tri": -1.0,
        "key_k_reclaim_low_tri": -1.0,
        "key_k_D_intraday_probe_recovered_tri": -1.0,
        "key_k_D_low_held_above_tri": -1.0,
        "key_k_held_initial5_tri": -1.0,
    }
    diagnostic = {
        "key_k_search_prior_sessions": KEY_SEARCH_PRIOR_SESSIONS,
        "key_k_return_threshold": KEY_MIN_RETURN,
        "key_k_relative_volume_threshold": KEY_MIN_RELATIVE_VOLUME,
        "key_k_candidate_date": None,
        "key_k_candidate_low": None,
        "key_k_candidate_body_midpoint": None,
        "key_k_candidate_return_pct": None,
        "key_k_candidate_relative_prev5_volume": None,
        "key_k_candidate_previous5_mean_volume": None,
        "key_k_earlier_close_break_historical": "UNKNOWN",
        "key_k_presently_under_low": "UNKNOWN",
        "key_k_reclaim_low_on_D": "UNKNOWN",
        "key_k_held_first5_after_anchor": "UNKNOWN",
        "key_k_D_close_above_body_midpoint": "UNKNOWN",
        "key_k_status": "UNAVAILABLE_NO_QUALIFYING_PRIOR_SURGE",
        "key_k_D_close": close_d,
        "key_k_D_low": _number(current.get("low")),
        "key_k_previous_close": _number(prefix[-2].get("close")) if len(prefix) > 1 else None,
        "key_k_D_excluded_from_anchor_search": True,
    }
    if anchor is None:
        if len(prior) < KEY_SEARCH_PRIOR_SESSIONS:
            diagnostic["key_k_status"] = "UNKNOWN_INSUFFICIENT_PRIOR_WINDOW"
        return features, diagnostic

    i = anchor["index"]
    row = anchor["row"]
    low = _number(row.get("low"))
    open_ = _number(row.get("open"))
    close = _number(row.get("close"))
    body_midpoint = (open_ + close) / 2.0 if open_ is not None and close is not None else None
    if low is None or low <= 0 or close_d is None or body_midpoint is None:
        return features, {**diagnostic, "key_k_status": "UNKNOWN_INVALID_ANCHOR_NUMERIC"}

    earlier = prefix[i + 1:-1]
    earlier_closes = [_number(item.get("close")) for item in earlier]
    earlier_break = (None if any(value is None for value in earlier_closes)
                     else any(value < low for value in earlier_closes if value is not None))
    prior_close = _number(prefix[-2].get("close")) if len(prefix) > 1 else None
    current_under = close_d < low
    reclaim = None if prior_close is None else (prior_close <= low and close_d > low)
    low_d = _number(current.get("low"))
    d_low_vs_anchor = None if low_d is None else low_d / low - 1.0
    probe_recovered = None if low_d is None else (low_d <= low and close_d > low)
    d_low_held = None if low_d is None else (low_d > low)
    after = prefix[i + 1:i + 1 + KEY_INITIAL_HOLD_SESSIONS]
    if len(after) < KEY_INITIAL_HOLD_SESSIONS:
        held_initial = None
    else:
        after_closes = [_number(item.get("close")) for item in after]
        held_initial = None if any(value is None for value in after_closes) else all(value >= low for value in after_closes if value is not None)
    close_above_mid = close_d >= body_midpoint

    features.update({
        "key_k_relative_prev5_volume": anchor["relative_volume"],
        "key_k_distance_to_low_pct": close_d / low - 1.0,
        "key_k_D_low_vs_anchor_low_pct": d_low_vs_anchor if d_low_vs_anchor is not None else -1.0,
        "key_k_close_above_body_mid_tri": float(int(close_above_mid)),
        "key_k_prior_close_break_tri": float(_tri(earlier_break)),
        "key_k_current_under_low_tri": float(int(current_under)),
        "key_k_reclaim_low_tri": float(_tri(reclaim)),
        "key_k_D_intraday_probe_recovered_tri": float(_tri(probe_recovered)),
        "key_k_D_low_held_above_tri": float(_tri(d_low_held)),
        "key_k_held_initial5_tri": float(_tri(held_initial)),
    })
    diagnostic.update({
        "key_k_candidate_date": _date(row),
        "key_k_candidate_low": low,
        "key_k_candidate_body_midpoint": body_midpoint,
        "key_k_candidate_return_pct": anchor["return_pct"],
        "key_k_candidate_relative_prev5_volume": anchor["relative_volume"],
        "key_k_candidate_previous5_mean_volume": anchor["previous5_mean_volume"],
        "key_k_earlier_close_break_historical": _status(_tri(earlier_break)),
        "key_k_presently_under_low": _status(int(current_under)),
        "key_k_reclaim_low_on_D": _status(_tri(reclaim)),
        "key_k_held_first5_after_anchor": _status(_tri(held_initial)),
        "key_k_D_close_above_body_midpoint": _status(int(close_above_mid)),
        "key_k_status": "AVAILABLE",
        "key_k_D_close_to_low_pct": close_d / low - 1.0,
        "key_k_D_low_vs_anchor_low_pct": d_low_vs_anchor,
        "key_k_D_intraday_probe_recovered": _status(_tri(probe_recovered)),
        "key_k_D_low_held_above": _status(_tri(d_low_held)),
    })
    return features, diagnostic


def structure_repair_features(
    panel_rows: list[dict[str, Any]], *, target_date: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Return the structure feature vector and audit detail using only dates <= D."""
    prefix = sorted((row for row in panel_rows
                     if row.get("trade_date") is not None and str(row["trade_date"]) <= target_date),
                    key=lambda row: str(row["trade_date"]))
    if not prefix or str(prefix[-1]["trade_date"]) != target_date:
        raise ValueError("EXACT_D_ROW_MISSING")
    if len({str(row["trade_date"]) for row in prefix}) != len(prefix):
        raise ValueError("DUPLICATE_PANEL_KEY_WITHIN_PREFIX")
    yellow_window = prefix[-YELLOW_WINDOW_SESSIONS:]
    yellow_features, yellow_diagnostic = _yellow_state(
        yellow_window, target_date, prior_rows=prefix[:-len(yellow_window)],
    )
    key_features, key_diagnostic = _key_k_state(prefix, target_date)
    return {**yellow_features, **key_features}, {**yellow_diagnostic, **key_diagnostic}
