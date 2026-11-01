"""Source-bound components omitted from the existing KB daily projection.

The caller supplies the same prefix, indicator cache, and source detector
results already used for the current KB fields. These helpers do no I/O and
do not change signal definitions, issue orders, or fetch data.
"""
from __future__ import annotations

import math


RULE_ID = "ZGE_SOURCE_SIGNAL_COMPONENTS_LOCAL_V1"


def _finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _available(n):
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("KB_COMPONENT_AVAILABLE_BARS_INVALID")
    return n


def yidong_above_60d_at(closes, *, index, vol_ratio_5, pct_chg):
    """Source position test, only after its actual anomaly preconditions.

    This is the current observation's position against the unrounded 60-bar
    mean. It does not select an earlier pre-rise anchor.
    """
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(closes):
        raise ValueError("KB_COMPONENT_INDEX_INVALID")
    n = index + 1
    out = {"kb_yidong_above_60d": None, "kb_yidong_above_60d_status": None,
           "kb_yidong_above_60d_required_bars": 65, "kb_yidong_above_60d_available_bars": n}
    if n < 65:
        out["kb_yidong_above_60d_status"] = "INSUFFICIENT_HISTORY"
    elif not _finite(vol_ratio_5) or not _finite(pct_chg):
        out["kb_yidong_above_60d_status"] = "INVALID_RATIO_OR_PCT_CHANGE"
    elif float(vol_ratio_5) < 2 or float(pct_chg) <= 0:
        out["kb_yidong_above_60d_status"] = "NOT_APPLICABLE_SOURCE_PRECONDITION"
    elif not all(_finite(x) for x in closes[n - 60:n]) or float(closes[index]) <= 0:
        out["kb_yidong_above_60d_status"] = "INVALID_CLOSE_IN_60_BAR_WINDOW"
    else:
        ma60 = sum(float(x) for x in closes[n - 60:n]) / 60
        if ma60 <= 0:
            out["kb_yidong_above_60d_status"] = "INVALID_MA60"
        else:
            out["kb_yidong_above_60d"] = float(closes[index]) >= ma60 * 0.95
            out["kb_yidong_above_60d_status"] = "OBSERVED_SOURCE_POSITION"
    return out


def double_gun_components(source_result, *, signal, available_bars, input_valid):
    """Use the same detector return that yielded the existing double-gun flag."""
    n = _available(available_bars)
    out = {"kb_double_gun_vol1": None, "kb_double_gun_vol2": None, "kb_double_gun_gap_days": None,
           "kb_double_gun_components_status": None, "kb_double_gun_components_required_bars": 24,
           "kb_double_gun_components_available_bars": n}
    if n < 24:
        out["kb_double_gun_components_status"] = "INSUFFICIENT_HISTORY"
    elif input_valid is not True or signal is None:
        out["kb_double_gun_components_status"] = "INVALID_OR_UNBOUND_INPUT"
    elif signal is False:
        out["kb_double_gun_components_status"] = "NOT_APPLICABLE_NO_SIGNAL"
    elif signal is not True or not isinstance(source_result, dict) or source_result.get("is_double_gun") is not True:
        out["kb_double_gun_components_status"] = "SOURCE_RESULT_UNBOUND_OR_CONFLICT"
    else:
        v1, v2, gap = (source_result.get(key) for key in ("double_gun_vol1", "double_gun_vol2", "double_gun_gap_days"))
        if not _finite(v1) or not _finite(v2) or float(v1) <= 0 or float(v2) <= 0 or isinstance(gap, bool) or not isinstance(gap, int) or not 3 <= gap <= 10:
            out["kb_double_gun_components_status"] = "SOURCE_COMPONENT_INVALID"
        else:
            out.update(kb_double_gun_vol1=float(v1), kb_double_gun_vol2=float(v2),
                       kb_double_gun_gap_days=gap, kb_double_gun_components_status="OBSERVED_SOURCE_RESULT")
    return out


def bowl_components(white, yellow, *, available_bars, close_prefix_valid):
    """Return source-named white/yellow lines, including when no bowl is hit."""
    n = _available(available_bars)
    out = {"kb_bowl_upper": None, "kb_bowl_lower": None, "kb_bowl_components_status": None,
           "kb_bowl_required_bars": 120, "kb_bowl_available_bars": n}
    if n < 120:
        out["kb_bowl_components_status"] = "INSUFFICIENT_HISTORY"
    elif close_prefix_valid is not True or not _finite(white) or not _finite(yellow) or float(white) <= 0 or float(yellow) <= 0:
        out["kb_bowl_components_status"] = "INVALID_LINE_OR_PREFIX"
    else:
        out.update(kb_bowl_upper=round(float(white), 2), kb_bowl_lower=round(float(yellow), 2),
                   kb_bowl_components_status="OBSERVED_SOURCE_LINES")
    return out


def violence_k_components(source_events, *, signal, available_bars, input_valid):
    """Use the latest event returned by the existing daily violence-K detector."""
    n = _available(available_bars)
    out = {"kb_violence_k_type": None, "kb_violence_k_body": None,
           "kb_violence_k_components_status": None, "kb_violence_k_required_bars": 21,
           "kb_violence_k_available_bars": n}
    if n < 21:
        out["kb_violence_k_components_status"] = "INSUFFICIENT_HISTORY"
    elif input_valid is not True or signal is None:
        out["kb_violence_k_components_status"] = "INVALID_OR_UNBOUND_INPUT"
    elif signal is False:
        out["kb_violence_k_components_status"] = "NOT_APPLICABLE_NO_SIGNAL"
    elif signal is not True or not isinstance(source_events, list):
        out["kb_violence_k_components_status"] = "SOURCE_RESULT_UNBOUND_OR_CONFLICT"
    else:
        matches = [x for x in source_events if isinstance(x, dict) and x.get("is_latest") is True]
        if len(matches) != 1 or matches[0].get("type") not in {"大暴力", "小暴力"} or not _finite(matches[0].get("body_pct")) or float(matches[0]["body_pct"]) < 0:
            out["kb_violence_k_components_status"] = "SOURCE_RESULT_UNBOUND_OR_CONFLICT"
        else:
            out.update(kb_violence_k_type=matches[0]["type"], kb_violence_k_body=float(matches[0]["body_pct"]),
                       kb_violence_k_components_status="OBSERVED_SOURCE_EVENT")
    return out
