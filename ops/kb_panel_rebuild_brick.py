"""Bounded KB rebuild/brick observations for the existing daily producer.

The local rule identifiers below distinguish the repaired calculation from
both the original copied defect and the source file's SHA. No I/O, scheduling,
transaction decision or second market-data producer is performed here.
"""
from __future__ import annotations

import math


REBUILD_RULE = "ZGE_REBUILD_FULL_PREFIX_124_LOCAL_V1"
BRICK_RULE = "ZGE_BRICK_B195_WARMUP_FLIP_DESC_LOCAL_V1"
BRICK_SERIES_ID = "KB_AUTHORITY_BRICK_SERIES_B195_V1"
COMPLEX_SOURCE_SHA256 = "304544550c0a6cd34231a3f883c6c44a5ff881bc19c65f80cb2a5d7d9aec698d"
BRICK_SOURCE_SHA256 = "a87ed7f6025387b6c1977d27ff0662bce0ed4f97b3360bc86a004cf83292401e"


def _index(index, length):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < length:
        raise ValueError("KB_INDEX_OUTSIDE_BOUND_PREFIX")
    return index + 1


def _finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def rebuild_at(closes, volumes, pct_chgs, *, index):
    """Calculate only one as-of row from its supplied prefix, with null guards.

    Inputs are same-security daily arrays from the existing QFQ producer.
    Percent changes are already validated producer inputs. No future row is
    read. The original early partial-five-day volume divisor and first-match
    behavior are preserved and recorded as source limitations, not silently
    reinterpreted as a new formula.
    """
    if len(closes) != len(volumes) or len(closes) != len(pct_chgs):
        raise ValueError("KB_REBUILD_INPUT_LENGTH_MISMATCH")
    n = _index(index, len(closes))
    result = {"kb_rebuild": None, "kb_rebuild_reason": None,
              "kb_rebuild_required_bars": 124, "kb_rebuild_available_bars": n,
              "kb_rebuild_rule_id": REBUILD_RULE, "components": None}
    if n < 124:
        result["kb_rebuild_reason"] = "INSUFFICIENT_HISTORY"
        return result
    window = closes[n - 124:n]
    if not all(_finite(value) for value in window):
        result["kb_rebuild_reason"] = "INVALID_CLOSE_IN_REQUIRED_WINDOW"
        return result
    if not all(_finite(value) and float(value) > 0 for value in volumes[n - 15:n]):
        result["kb_rebuild_reason"] = "INVALID_VOLUME_IN_REQUIRED_WINDOW"
        return result
    if not all(_finite(value) for value in pct_chgs[n - 14:n]):
        result["kb_rebuild_reason"] = "INVALID_PCT_CHANGE_IN_REQUIRED_WINDOW"
        return result
    # All four MAs use the complete window ending on the relevant date. The
    # source's [: -4] and [: -9] offsets are inclusive-date conventions.
    prices = [float(x) for x in window]

    def yellow(end):
        return sum(sum(prices[end - period:end]) / period for period in (14, 28, 57, 114)) / 4

    yellow_today, yellow_5, yellow_10 = yellow(124), yellow(120), yellow(115)
    vs, pcts = [float(x) for x in volumes[n - 15:n]], pct_chgs[n - 15:n]
    candidate = None
    for i in range(1, 15):
        # Intentional source semantics: for i < 5 the source still divides by 5.
        previous_5_avg = sum(vs[max(0, i - 5):i]) / 5
        if float(pcts[i]) > 5 and vs[i] > previous_5_avg * 1.5:
            candidate = i
            break
    vol_shrink = candidate is not None and vs[-1] < vs[candidate] * 0.6
    near_yellow = abs(prices[-1] - yellow_today) / yellow_today < 0.02 if yellow_today > 0 else False
    yellow_up = yellow_5 > yellow_10
    result["kb_rebuild"] = bool(candidate is not None and vol_shrink and near_yellow and yellow_up)
    result["components"] = {"yellow_today": yellow_today, "yellow_5": yellow_5, "yellow_10": yellow_10,
                            "yellow_up": yellow_up, "near_yellow": near_yellow,
                            "volume_shrink": vol_shrink,
                            "up_volume_day_index": n - 15 + candidate if candidate is not None else None}
    return result


def brick_fields_at(brick_values, *, index, prefix_valid, prefix_seed_bound, series_id):
    """Extract source brick color/count and the locally repaired description.

    ``brick_values`` must be the existing authority's full-prefix cached series
    for this security. A source color before two actual >=12-bar brick values
    is not a real observation. Runs that extend back into warmup remain null
    until an observed color transition determines their starting point.
    """
    n = _index(index, len(brick_values))
    result = {"kb_brick_trend": None, "kb_brick_trend_reason": None,
              "kb_brick_count": None, "kb_brick_count_reason": None,
              "kb_brick_action_desc": None, "kb_brick_action_desc_reason": None,
              "kb_brick_required_bars": 13, "kb_brick_available_bars": n,
              "kb_brick_observed_run_lower_bound": None, "kb_brick_rule_id": BRICK_RULE}
    if series_id != BRICK_SERIES_ID or prefix_seed_bound is not True:
        reason = "SOURCE_PREFIX_OR_BRICK_KERNEL_UNBOUND"
    elif prefix_valid is not True:
        reason = "INVALID_HLC_INPUT_IN_REQUIRED_PREFIX"
    elif n < 13:
        reason = "INSUFFICIENT_HISTORY"
    elif not all(_finite(x) for x in brick_values[n - 2:n]):
        reason = "INVALID_BRICK_VALUE_IN_REQUIRED_PREFIX"
    else:
        reason = None
    if reason:
        for key in ("kb_brick_trend_reason", "kb_brick_count_reason", "kb_brick_action_desc_reason"):
            result[key] = reason
        return result

    def color(i):
        if not _finite(brick_values[i]) or not _finite(brick_values[i - 1]):
            return None
        return 1 if float(brick_values[i]) >= float(brick_values[i - 1]) else -1

    def run_ending(i):
        current = color(i)
        j = i
        while j >= 12:
            previous = color(j)
            if previous is None:
                return i - j, None
            if previous != current:
                return i - j, True
            j -= 1
        count = i - j
        # j >= 12 proves a genuine opposite color after warmup; otherwise the
        # count may extend into the source's synthetic zero-value warmup.
        return count, False

    current = color(index)
    result["kb_brick_trend"] = "RED" if current == 1 else "GREEN"
    count, origin_known = run_ending(index)
    result["kb_brick_observed_run_lower_bound"] = count
    if origin_known is None:
        result["kb_brick_count_reason"] = "INVALID_BRICK_VALUE_IN_REQUIRED_RUN"
        result["kb_brick_action_desc_reason"] = "INVALID_BRICK_VALUE_IN_REQUIRED_RUN"
        return result
    if not origin_known:
        result["kb_brick_count_reason"] = "BRICK_RUN_ORIGIN_IN_WARMUP"
        result["kb_brick_action_desc_reason"] = "BRICK_RUN_ORIGIN_IN_WARMUP"
        return result
    result["kb_brick_count"] = count
    previous = color(index - 1) if index >= 13 else None
    if current == -1 and previous == 1:
        previous_count, previous_origin_known = run_ending(index - 1)
        if previous_origin_known is None:
            result["kb_brick_action_desc_reason"] = "INVALID_BRICK_VALUE_IN_PREVIOUS_RED_RUN"
        elif not previous_origin_known:
            result["kb_brick_action_desc_reason"] = "PREVIOUS_RED_RUN_ORIGIN_IN_WARMUP"
        else:
            # Upstream mistakenly interpolates the new green run count (1) as
            # the length of the preceding red run. Use the actual prior run.
            result["kb_brick_action_desc"] = f"红砖翻绿！立刻止损（连续红砖{previous_count}块后翻绿）"
    elif current == 1 and count >= 4:
        result["kb_brick_action_desc"] = ("红砖已满4块，至少减仓一半" if count == 4 else
                                          f"红砖已延续{count}块，趋势延续中，但未减仓需警惕")
    elif current == -1:
        result["kb_brick_action_desc"] = (f"绿砖已连续{count}块，跌势可能接近尾声但仍禁止抄底" if count >= 4 else
                                          f"绿砖下跌中（{count}块），绝不抄底，先数4块")
    else:
        result["kb_brick_action_desc"] = f"红砖上涨中（{count}块），继续持有"
    return result
