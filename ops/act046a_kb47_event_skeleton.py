"""Append D-only ACT-046A observations to the sealed ACT-044A replay."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
import re
import zipfile

BASELINE_SHA = "3bbd6c00ceb235a9b0afe9c130695950b06d5efa9be554ecff1f2caafe7db672"
BLIND_SHA = "3e449a51d85703747fa576681dad5d2857a94ab6b567792d9aff8e68b5de31d1"
CONTRACT_SHA = "9e06fa68fd00497b393eea88e7fbd2016cbe6ee6434399cff39f23f64c2a04c8"
ACT044C_SHA = "771c4aed372b4a9df9f8de04c61c251db801512d84cf8a5e93cdf35fe78057b4"
F09_SHA = "924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6"
COURSE_MACD_SHA = "cb83ba9c3ffbb31d05f0c843db3ecceb112399d3521239cb42ea99842d8f74df"
COURSE_ADVANCE_SHA = "2360dac940bfc887cc116f9d6a223ad11220fc198b0a6c59d45a5df75e6ad724"
SAME_BASIS_LINKS = {"SAME_SEALED_ADJACENT_REFERENCE", "STITCHED_POSITIVE_RATIO_CHAIN"}
NUMBER_FIELDS = ("open", "high", "low", "close", "pre_close", "volume", "white_line",
                 "yellow_line", "bbi", "macd_dif", "macd_dea", "macd_hist", "atr14")
FLAGS = {
    "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False,
    "orders_sent": False, "S_FIT": 0, "B_FIT": 0, "preprocess_fit": 0, "parameter_search": 0,
}


def source(source_id, version, digest, locator, fields, clock_role, outputs):
    return {
        "source_id": source_id, "source_version": version, "source_hash": digest,
        "source_locator": locator, "input_fields": fields.split(), "clock_role": clock_role,
        "output_fields": outputs.split(),
    }


PROVENANCE = {
    "f09": source("USER_F09", "20261021", F09_SHA, "formula L55–57; ACT-045B §1 session join",
                  "macd_dif macd_dea relative_session basis_segment basis_link_status m17_raw_f05",
                  "MACD_SIGNAL_CROSS", "m17_USER_F09_SIGNAL_CROSS m17_USER_F09_SIGNAL_CROSS_confirmed_session "
                  "m17_USER_F09_SIGNAL_CROSS_same_day_confirmed_with_f05"),
    "axis": source("COURSE_260422_DIF_AXIS", "ZTXT-0107", COURSE_MACD_SHA,
                   "[0,1800); ACT-045B §1 session join",
                   "macd_dif relative_session basis_segment basis_link_status m17_raw_f05",
                   "MACD_ZERO_CROSS", "m17_COURSE_260422_DIF_AXIS_CROSS "
                   "m17_COURSE_260422_DIF_AXIS_CROSS_confirmed_session m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05"),
    "macd_history": source("ACT-045B", "20261125", CONTRACT_SHA, "§1 MACD diagnostics",
                           "macd_dif macd_dea macd_hist relative_session basis_segment basis_link_status",
                           "D_AND_PREDECESSOR_FACTS", "m17_macd_price_basis_id m17_macd_prev_session_verified "
                           "m17_macd_dea_D m17_macd_dif_D m17_macd_dif_delta m17_macd_dea_delta m17_macd_hist_D "
                           "m17_macd_hist_prev m17_macd_hist_prev2"),
    "r3": source("ACT-044C", "20261125", ACT044C_SHA, "R3; ACT-045B §1 price and refutation facts",
                 "open close pre_close white_line atr14", "D_R3_FACTS",
                 "r3_body_pct r3_gap_pct r3_white_dist_atr r3_is_gap_up_yin_bar r3_refutation_watch"),
    "m17_policy": source("ACT-045B", "20261125", CONTRACT_SHA, "§1 unselected track and frozen qualification",
                         "m17_eligible_state", "D_UNSELECTED_TRACK",
                         "m17_macd_turn_track_selected m17_eligible_state m17_auto_L1_confirm"),
    "repair_ledger": source("ACT-045B", "20261125", CONTRACT_SHA, "§2 state ledger, R2 and no semantic promotion",
                            "anon_id relative_session basis_segment basis_link_status "
                            "relative_anchor_session is_new_on_D low_converted_as_D m25_eligible_state",
                            "D_REPAIR_QUERY", "m25_eligible_state m25_auto_L1_confirm m25_semantic_sufficiency "
                            "m25_near_y_state m25_shrink_state m25_confirm_strength_state m25_repair_clock "
                            "m25_observed_price_clock m25_repair_clock_reason m25_verified_repair_id "
                            "m25_observed_repair_id m25_anchor_kind m25_anchor_session m25_anchor_price "
                            "m25_damage_session m25_test_session m25_observed_reclaim_session "
                            "m25_first_full_confirm_time m25_event_ledger"),
    "repair_d": source("ACT-045B", "20261125", CONTRACT_SHA, "§2 d damage; ACT-044C R2 fixed support",
                       "close yellow_line bbi volume relative_session basis_segment basis_link_status "
                       "relative_anchor_session is_new_on_D low_converted_as_D",
                       "DAMAGE", "damage_id d damage_close damage_anchor_price_at_d damage_volume"),
    "repair_t": source("ACT-045B", "20261125", CONTRACT_SHA, "§2 test observable facts",
                       "low high close yellow_line atr14 volume relative_session basis_segment basis_link_status "
                       "prior_bar.low prior_bar.yellow_line prior_bar.volume damage_bar.volume anchor_bar.volume",
                       "INDEPENDENT_TEST_OBSERVATION", "observations"),
    "repair_c": source("ACT-045B", "20261125", CONTRACT_SHA, "§2 confirmation observable facts",
                       "open close pre_close volume white_line yellow_line bbi low_converted_as_D test_bar.volume prior_bar.volume",
                       "D_PRICE_RECLAIM_OBSERVATION", "confirmation_facts c c_role"),
    "m05_sequence": source("COURSE_260429_MAIN_ADVANCE", "ZTXT-0108", COURSE_ADVANCE_SHA,
                           "[0,750), [27300,29150); ACT-045B §3",
                           "relative_session high low", "PRE_D_HIGH_LOW_FACTS", "m05_prior_high_low_sequence"),
    "m05_white": source("ACT-045B", "20261125", CONTRACT_SHA, "§3 white-line observations",
                        "relative_session close white_line basis_segment basis_link_status",
                        "TRAILING_20_OBSERVED_BARS", "m05_last20_white_observation"),
    "m05_support": source("ACT-045B", "20261125", CONTRACT_SHA, "§3 support and bearish bars; ACT-044C R2",
                          "relative_session open low close pre_close volume white_line relative_anchor_session "
                          "low_converted_as_D close_broken_through_D reclaim_through_D",
                          "D_FIXED_SUPPORT_AND_BEARISH_BARS", "m05_fixed_anchor_and_yin_trace"),
    "m05_policy": source("ACT-045B", "20261125", CONTRACT_SHA, "§3 F08/R3 review subset and pending source",
                         "m05_raw_f08 m05_r3 m05_eligible_state", "D_HUMAN_REVIEW_QUERY",
                         "m05_needs_human_fact_review m05_eligible_state m05_auto_L1_confirm m05_main_advance"),
}


def atom_binding(atom, bar, event_id):
    return {
        **PROVENANCE[atom], "as_of": bar.session, "price_basis_id": bar.basis, "event_id": event_id,
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    if value in (None, ""):
        return None
    result = float(value)
    require(isfinite(result), "NON_FINITE_D_ONLY_INPUT")
    return result


def tri(value):
    return "UNKNOWN" if value is None else "TRUE" if value else "FALSE"


def delta(a, b):
    return None if a is None or b is None else a - b


def ratio(a, b):
    return None if a is None or b is None or b <= 0 else a / b


def below(a, b):
    return None if a is None or b is None else a < b


def compact_json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class Bar:
    session: int
    basis: str
    link: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pre_close: float | None = None
    volume: float | None = None
    white_line: float | None = None
    yellow_line: float | None = None
    bbi: float | None = None
    macd_dif: float | None = None
    macd_dea: float | None = None
    macd_hist: float | None = None
    atr14: float | None = None


@dataclass(frozen=True)
class Support:
    anchor_id: str
    known: int
    kind: str
    price: float | None = None
    prior_advance_event_id: str | None = None
    wave_id: str | None = None

    def value(self, bar):
        if self.kind == "YELLOW_LINE":
            return bar.yellow_line
        if self.kind == "BBI":
            return bar.bbi
        return self.price


def contiguous(previous, current):
    return (previous is not None and current.session - previous.session == 1
            and previous.basis == current.basis and current.link in SAME_BASIS_LINKS)


def body_pct(bar):
    value = ratio(delta(bar.close, bar.open), bar.pre_close)
    return None if value is None else 100 * value


def d17(row, bars):
    current = bars[0]
    previous = bars.get(-1)
    consecutive = contiguous(previous, current)
    dif = current.macd_dif
    dea = current.macd_dea
    signal_cross = axis_cross = None
    if consecutive and None not in (dif, previous.macd_dif):
        axis_cross = previous.macd_dif <= 0 < dif
        if None not in (dea, previous.macd_dea):
            signal_cross = dif > dea and previous.macd_dif <= previous.macd_dea
    f05 = row["m17_raw_f05"]
    gap = ratio(current.open, current.pre_close)
    body = body_pct(current)

    def same_day(cross):
        if f05 == "FALSE" or cross is False:
            return "FALSE"
        return tri(cross if f05 == "TRUE" else None)

    return {
        "m17_USER_F09_SIGNAL_CROSS": tri(signal_cross),
        "m17_USER_F09_SIGNAL_CROSS_same_day_confirmed_with_f05": same_day(signal_cross),
        "m17_USER_F09_SIGNAL_CROSS_confirmed_session": 0 if signal_cross else None,
        "m17_COURSE_260422_DIF_AXIS_CROSS": tri(axis_cross),
        "m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05": same_day(axis_cross),
        "m17_COURSE_260422_DIF_AXIS_CROSS_confirmed_session": 0 if axis_cross else None,
        "m17_macd_turn_track_selected": None,
        "m17_eligible_state": row["m17_eligible_state"],
        "m17_auto_L1_confirm": "FALSE",
        "m17_macd_price_basis_id": current.basis,
        "m17_macd_prev_session_verified": tri(consecutive),
        "m17_macd_dea_D": dea,
        "m17_macd_dif_D": dif,
        "m17_macd_dif_delta": delta(dif, previous.macd_dif) if consecutive else None,
        "m17_macd_dea_delta": delta(dea, previous.macd_dea) if consecutive else None,
        "m17_macd_hist_D": current.macd_hist,
        "m17_macd_hist_prev": previous.macd_hist if consecutive else None,
        "m17_macd_hist_prev2": bars[-2].macd_hist if consecutive and contiguous(bars.get(-2), previous) else None,
        "r3_body_pct": body,
        "r3_gap_pct": None if gap is None else 100 * (gap - 1),
        "r3_white_dist_atr": ratio(delta(current.close, current.white_line), current.atr14),
        "r3_is_gap_up_yin_bar": tri(None if gap is None or body is None else gap > 1 and body < 0),
        "r3_refutation_watch": "NEEDS_HUMAN_CHECK",
    }


def test_observation(bar, prior, damage_volume, anchor_volume):
    low_dist = delta(bar.low, bar.yellow_line)
    high_dist = delta(bar.high, bar.yellow_line)
    close_dist = delta(bar.close, bar.yellow_line)
    last_low_dist = delta(prior.low, prior.yellow_line)
    intersects = None if None in (low_dist, high_dist) else low_dist <= 0 <= high_dist
    approaches = None if None in (low_dist, last_low_dist) else abs(low_dist) < abs(last_low_dist)
    volume_vs_prev = ratio(bar.volume, prior.volume)
    # These exact comparisons locate a factual candidate test. Human evidence still
    # determines whether it is a sufficient near-yellow and contraction test.
    observed = (bar.volume is not None and bar.volume > 0 and volume_vs_prev is not None
                and volume_vs_prev < 1 and (intersects is True or approaches is True))
    if None in (intersects, volume_vs_prev) or (not intersects and approaches is None):
        observed = None
    return {
        "session": bar.session, "low_minus_y": low_dist, "high_minus_y": high_dist,
        "close_minus_y": close_dist, "low_minus_y_atr": ratio(low_dist, bar.atr14),
        "low_over_y_minus_1": None if low_dist is None else ratio(low_dist, bar.yellow_line),
        "yellow_inside_static_range": intersects, "low_approached_y": approaches,
        "volume_vs_prev": volume_vs_prev, "volume_vs_damage": ratio(bar.volume, damage_volume),
        "volume_vs_anchor": ratio(bar.volume, anchor_volume), "factual_test": observed,
    }


def repair_clock(series_id, bars, support, known_test_supports=None):
    """Replay a fixed or pre-bound dynamic support and preserve closed repair events."""
    result = {
        "clock": "UNKNOWN", "observed_clock": "UNKNOWN", "reason": "PREEXISTING_ANCHOR_UNBOUND",
        "verified_repair_id": None, "events": [], "current": None,
    }
    if support is None or support.known >= 0:
        return result
    if support.known not in bars:
        result["reason"] = "TIME_ORDER_UNVERIFIED"
        return result
    bound_bars = [bar for session, bar in sorted(bars.items()) if session >= support.known]
    if not bound_bars or bound_bars[-1].session != 0:
        result["reason"] = "TIME_ORDER_UNVERIFIED"
        return result

    previous = bound_bars[0]
    previous_broken = below(previous.close, support.value(previous))
    current = None
    test_support = None
    active_support = support
    consecutive_below = False
    test_consecutive_below = False
    for bar in bound_bars[1:]:
        broken = below(bar.close, active_support.value(bar))
        if not contiguous(previous, bar) or broken is None or previous_broken is None:
            result.update(reason="TIME_ORDER_UNVERIFIED", current=current)
            return result

        dynamic = active_support.kind in {"YELLOW_LINE", "BBI"}
        # A still-unreclaimed anchor is not a fresh loss on every subsequent bar.
        new_damage = (broken and previous_broken and not consecutive_below
                      if dynamic else broken and not previous_broken)
        new_damage = active_support.known < bar.session and new_damage
        consecutive_below = previous_broken and broken

        test_failed = False
        if test_support is not None:
            test_broken = below(bar.close, test_support.value(bar))
            test_prev_broken = below(previous.close, test_support.value(previous))
            if test_broken is None or test_prev_broken is None:
                result.update(reason="TIME_ORDER_UNVERIFIED", current=current)
                return result
            if test_support.kind in {"YELLOW_LINE", "BBI"}:
                test_failed = (test_support.known <= previous.session < bar.session
                               and test_broken and test_prev_broken and not test_consecutive_below)
                test_consecutive_below = test_prev_broken and test_broken
            else:
                test_failed = test_broken and not test_prev_broken
        if new_damage or test_failed:
            if current is not None:
                current["state"] = "RESET_BY_NEW_DAMAGE"
            damage_support = active_support if new_damage else test_support
            assert damage_support is not None
            damage_dynamic = damage_support.kind in {"YELLOW_LINE", "BBI"}
            previous_broken = broken if new_damage else test_broken
            consecutive_below = damage_dynamic
            raw_id = f"{series_id}|DAILY|{support.wave_id or 'UNBOUND'}|{damage_support.anchor_id}|{bar.session}"
            repair_id = "R25_" + hashlib.sha256(raw_id.encode()).hexdigest()
            current = {
                "repair_id": repair_id, "damage_id": f"{repair_id}/d",
                "repair_of": None if current is None else current["repair_id"],
                "damage_anchor_id": damage_support.anchor_id, "damage_anchor_kind": damage_support.kind,
                "original_anchor_id": support.anchor_id,
                "anchor_known_session": damage_support.known, "d": bar.session,
                "damage_close": bar.close, "damage_anchor_price_at_d": damage_support.value(bar),
                "prior_advance_event_id": support.prior_advance_event_id, "wave_id": support.wave_id,
                "damage_volume": bar.volume, "observations": [], "t": None, "c": None,
                "first_full_confirm_time": None, "state": "DAMAGED",
                "damage_provenance": atom_binding("repair_d", bar, f"{repair_id}/d"),
            }
            active_support = damage_support
            result["events"].append(current)
            test_support = None
            test_consecutive_below = False
            previous = bar
            continue
        if current is not None and bar.session < 0:
            obs = test_observation(bar, previous, current["damage_volume"], bound_bars[0].volume)
            obs["repair_id"] = current["repair_id"]
            obs["test_observation_id"] = f"{current['repair_id']}/t/{bar.session}"
            obs["provenance"] = atom_binding("repair_t", bar, obs["test_observation_id"])
            obs["old_anchor_reclaimed"] = not broken
            current["observations"].append(obs)
            if obs["factual_test"] is True:
                current["t"] = bar.session
                current["state"] = "TEST_OBSERVED"
                nominated_support = (known_test_supports or {}).get(bar.session)
                if nominated_support is not None and nominated_support.known == bar.session:
                    test_support = nominated_support
                    test_consecutive_below = False
        previous = bar
        previous_broken = broken

    result["current"] = current
    if current is None:
        result.update(observed_clock="FALSE", clock="FALSE", reason="NO_OLD_ANCHOR_DAMAGE")
        return result
    if current["t"] is None:
        state = "UNKNOWN" if any(o["factual_test"] is None for o in current["observations"]) else "FALSE"
        # A price/volume proxy can fail even if an intervening bar is a valid human test.
        reason = "TEST_SEMANTICS_UNBOUND" if current["observations"] else "NO_INDEPENDENT_TEST_DAY"
        result.update(observed_clock=state, clock="UNKNOWN" if current["observations"] else "FALSE",
                      reason=reason)
        return result

    day = bound_bars[-1]
    current["confirmation_facts"] = {
        "session": 0, "body_pct": body_pct(day),
        "confirmation_observation_id": f"{current['repair_id']}/c/0",
        "test_observation_id": f"{current['repair_id']}/t/{current['t']}",
        "volume_vs_test": ratio(day.volume, bars[current["t"]].volume),
        "volume_vs_prev": ratio(day.volume, bars[-1].volume),
        "close_minus_old_anchor": delta(day.close, support.value(day)),
        "close_minus_damage_anchor": delta(day.close, active_support.value(day)),
        "close_minus_w": delta(day.close, day.white_line),
        "close_minus_y": delta(day.close, day.yellow_line),
        "close_minus_bbi": delta(day.close, day.bbi),
    }
    facts = current["confirmation_facts"]
    facts["provenance"] = atom_binding("repair_c", day, facts["confirmation_observation_id"])
    required = (facts["body_pct"], facts["close_minus_old_anchor"], facts["close_minus_damage_anchor"])
    if any(value is None for value in required):
        result.update(reason="D_CONFIRMATION_FACTS_UNAVAILABLE")
        return result
    if any(value < 0 for value in required) or facts["body_pct"] == 0:
        result.update(observed_clock="FALSE", clock="FALSE", reason="D_RECLAIM_OR_POSITIVE_BODY_ABSENT")
        return result

    current.update(c=day.session, c_role="PRICE_PROXY_ONLY", state="D_RECLAIM_BODY_OBSERVED")
    result.update(observed_clock="TRUE", reason="PRIOR_ADVANCE_OR_WAVE_UNBOUND")
    # Event identity/chronology and full semantic qualification deliberately diverge.
    if support.prior_advance_event_id and support.wave_id:
        result.update(clock="TRUE", verified_repair_id=current["repair_id"], reason="NEEDS_HUMAN_CHECK")
    return result


def fixed_support(anchor):
    return Support(
        f"PREEXISTING_FIXED_SUPPORT@{anchor['relative_anchor_session']}",
        int(anchor["relative_anchor_session"]), "FIXED_LOW", number(anchor["low_converted_as_D"]),
    ) if anchor["relative_anchor_session"] and anchor["is_new_on_D"] == "False" else None


def d25(row, bars, support):
    ledger = repair_clock(row["anon_id"], bars, support)
    current = ledger["current"] or {}
    return {
        "m25_eligible_state": row["m25_eligible_state"],
        "m25_auto_L1_confirm": "FALSE",
        "m25_semantic_sufficiency": "NEEDS_HUMAN_CHECK",
        "m25_near_y_state": "NEEDS_HUMAN_CHECK",
        "m25_shrink_state": "NEEDS_HUMAN_CHECK",
        "m25_confirm_strength_state": "NEEDS_HUMAN_CHECK",
        "m25_repair_clock": ledger["clock"],
        "m25_observed_price_clock": ledger["observed_clock"],
        "m25_repair_clock_reason": ledger["reason"],
        "m25_verified_repair_id": ledger["verified_repair_id"],
        "m25_observed_repair_id": current.get("repair_id"),
        "m25_anchor_kind": None if support is None else support.kind,
        "m25_anchor_session": None if support is None else support.known,
        "m25_anchor_price": None if support is None else support.price,
        "m25_damage_session": current.get("d"),
        "m25_test_session": current.get("t"),
        "m25_observed_reclaim_session": current.get("c"),
        "m25_first_full_confirm_time": None,
        "m25_event_ledger": compact_json(ledger["events"]),
    }


def d05(row, bars, support, anchor):
    needs_review = row["m05_raw_f08"] == row["m05_r3"] == "TRUE"
    facts = {key: None for key in (
        "m05_prior_high_low_sequence", "m05_last20_white_observation", "m05_fixed_anchor_and_yin_trace",
        "m05_main_advance",
    )}
    if needs_review:
        prefix = [bar for session, bar in sorted(bars.items()) if session < 0]
        sequence = [[b.session, b.high, b.low] for b in prefix]
        trailing = [*prefix[-19:], bars[0]]
        observations = [below(b.white_line, b.close) for b in trailing]
        usable = [value for value in observations if value is not None]
        w_change = delta(trailing[-1].white_line, trailing[0].white_line)
        slices = [
            {"session": b.session, "body_pct": body_pct(b), "low": b.low, "close": b.close,
             "volume": b.volume, "white_line": b.white_line}
            for b in [*prefix, bars[0]] if below(b.close, b.open) is True
        ]
        facts.update(
            m05_prior_high_low_sequence=compact_json(sequence),
            m05_last20_white_observation=compact_json({
                "first_session": trailing[0].session, "last_session": 0, "bars": len(trailing),
                "valid_pairs": len(usable), "close_above_white_count": sum(usable),
                "close_above_white_share": ratio(sum(usable), len(usable)),
                "white_endpoint_delta": w_change,
                "white_per_bar_slope": ratio(w_change, len(trailing) - 1),
                "market_sessions_complete": all(contiguous(a, b) for a, b in zip(trailing, trailing[1:])),
            }),
            m05_fixed_anchor_and_yin_trace=compact_json({
                "fixed_anchor_session": None if support is None else support.known,
                "fixed_anchor_price": None if support is None else support.price,
                "D_close_below_fixed_anchor": None if support is None else below(bars[0].close, support.price),
                "close_broken_through_D": anchor["close_broken_through_D"],
                "reclaim_through_D": anchor["reclaim_through_D"],
                "bearish_bars": slices,
            }),
            m05_main_advance="SOURCE_PENDING_ORAL_ONLY",
        )
    return {
        "m05_needs_human_fact_review": tri(needs_review), "m05_eligible_state": row["m05_eligible_state"],
        "m05_auto_L1_confirm": "FALSE", **facts,
    }


def row_provenance(anon, extra, day, prior):
    confirmed_f09 = extra["m17_USER_F09_SIGNAL_CROSS"] == "TRUE"
    confirmed_axis = extra["m17_COURSE_260422_DIF_AXIS_CROSS"] == "TRUE"
    refs = {
        "f09": atom_binding("f09", day, f"{anon}/f09/0" if confirmed_f09 else None),
        "axis": atom_binding("axis", day, f"{anon}/axis/0" if confirmed_axis else None),
        "repair_ledger": atom_binding("repair_ledger", day, extra["m25_observed_repair_id"]),
    }
    for atom in ("macd_history", "r3", "m17_policy", "m05_policy"):
        refs[atom] = atom_binding(atom, day, f"{anon}/{atom}/0")
    if extra["m05_needs_human_fact_review"] == "TRUE":
        refs["m05_sequence"] = atom_binding("m05_sequence", prior, f"{anon}/m05_sequence/{prior.session}")
        for atom in ("m05_white", "m05_support"):
            refs[atom] = atom_binding(atom, day, f"{anon}/{atom}/0")
    return compact_json(refs)


def bound(path, expected):
    data = Path(path).read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, f"INPUT_SHA256_MISMATCH: {path}")
    return data


def load_inputs(baseline, blind):
    source = csv.DictReader(io.StringIO(bound(baseline, BASELINE_SHA).decode("utf-8-sig"), newline=""))
    rows = list(source)
    fields = source.fieldnames
    require(fields is not None and len(fields) == len(set(fields)) == 171 and len(rows) == 181,
            "BASELINE_SHAPE_DRIFT")
    require([int(row["record_index"]) for row in rows] == list(range(1, 182)), "BASELINE_ORDER_DRIFT")
    ids = {row["anon_id"] for row in rows}
    require(len(ids) == 181 and all(re.fullmatch(r"R[0-9A-F]{24}", a) for a in ids)
            and all(row["input_blind_sha256"] == BLIND_SHA for row in rows), "BASELINE_KEY_OR_SEAL_DRIFT")
    bars = defaultdict(dict)
    anchors = {}
    with zipfile.ZipFile(io.BytesIO(bound(blind, BLIND_SHA))) as archive:
        with io.TextIOWrapper(archive.open("trailing_bars.csv"), encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                case, session = row["anon_id"], int(row["relative_session"])
                require(case in ids and session <= 0 and session not in bars[case], "BAR_KEY_OR_CLOCK_DRIFT")
                bars[case][session] = Bar(
                    session, row["basis_segment"], row["basis_link_status"],
                    **{key: number(row[key]) for key in NUMBER_FIELDS},
                )
        with io.TextIOWrapper(archive.open("anchor_context.csv"), encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["anchor_role"] != "PREEXISTING_FIXED_SUPPORT":
                    continue
                case = row["anon_id"]
                require(case in ids and case not in anchors, "ANCHOR_KEY_DRIFT")
                require(not row["relative_anchor_session"] or int(row["relative_anchor_session"]) <= 0,
                        "FUTURE_ANCHOR")
                anchors[case] = row
    require(set(bars) == set(anchors) == ids and all(len(w) == 60 and 0 in w for w in bars.values()),
            "BLIND_ROSTER_OR_WINDOW_DRIFT")
    return fields, rows, bars, anchors


def replay(baseline, blind):
    fields, originals, windows, anchors = load_inputs(baseline, blind)
    enriched = []
    for row in originals:
        case = row["anon_id"]
        bars, anchor = windows[case], anchors[case]
        support = fixed_support(anchor)
        extra = {
            "as_of_relative_session": 0,
            **d17(row, bars), **d25(row, bars, support), **d05(row, bars, support, anchor),
        }
        prior = bars[max(session for session in bars if session < 0)]
        extra["provenance"] = row_provenance(case, extra, bars[0], prior)
        enriched.append({**row, **{f"act046a_{key}": value for key, value in extra.items()}})
    output_fields = list(enriched[0])
    require(output_fields[:171] == fields and all(c.startswith("act046a_") for c in output_fields[171:]),
            "APPEND_ONLY_FIELD_CONTRACT")
    for row in enriched:
        require(all(value == "FALSE" for key, value in row.items() if key.endswith("_auto_L1_confirm")),
                "AUTO_L1_CONFIRM_FORBIDDEN")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, output_fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(enriched)
    text = stream.getvalue()
    readback = list(csv.DictReader(io.StringIO(text, newline="")))
    require([{key: row[key] for key in fields} for row in readback] == originals,
            "ORIGINAL_FIELD_VALUES_CHANGED")

    counts = {}
    for column in (
        "m17_USER_F09_SIGNAL_CROSS", "m17_USER_F09_SIGNAL_CROSS_same_day_confirmed_with_f05",
        "m17_COURSE_260422_DIF_AXIS_CROSS", "m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05",
        "r3_is_gap_up_yin_bar", "m17_eligible_state",
        "m25_observed_price_clock", "m25_repair_clock", "m25_repair_clock_reason",
        "m25_eligible_state", "m05_eligible_state", "m05_needs_human_fact_review",
    ):
        counts[column] = dict(Counter(row[f"act046a_{column}"] for row in enriched))
    payload = text.encode()
    return payload, {
        **FLAGS, "rows": len(enriched), "original_columns": len(fields),
        "appended_columns": len(output_fields) - len(fields), "auto_L1_confirm_new": 0,
        "baseline_sha256": BASELINE_SHA, "blind_sha256": BLIND_SHA,
        "contract_sha256": CONTRACT_SHA, "fixture_report_sha256": ACT044C_SHA,
        "output_sha256": hashlib.sha256(payload).hexdigest(), "output_bytes": len(payload),
        "macd_observation_sources": {
            "USER_F09_SIGNAL_CROSS": {"source_sha256": F09_SHA, "locator": "user formula L55–57"},
            "COURSE_260422_DIF_AXIS_CROSS": {"source_sha256": COURSE_MACD_SHA, "locator": "ZTXT-0107 [0,1800)"},
        },
        "main_advance_source": {"source_sha256": COURSE_ADVANCE_SHA, "locator": "ZTXT-0108 [0,750),[27300,29150)"},
        "counts": counts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--blind", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload, receipt = replay(args.baseline, args.blind)
    with args.output.open("xb") as stream:
        stream.write(payload)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
