"""ACT-067B isolated semantic evaluation. Importing this file has no side effects."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable


SYMBOL = "002865.SZ"
UNKNOWN = "UNKNOWN"
TRACKS = (
    "B2_ORAL_CORE",
    "B2_1006_SCREEN",
    "B2_151_PREV_VOL_X1_20",
    "USER_FORMULA_B2_F03",
    "B2_TREND_CONFIRMATION",
)
B1_RISK_CHECKS = (
    "UNABSORBED_LARGE_BEARISH_CANDLE",
    "S1_EXHAUSTION_OR_DISTRIBUTION",
    "CLOSE_REAL_BREAK_OF_SUPPORT",
    "KEY_ANCHOR_INVALIDATION",
)


def sha256(path: Path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path: Path):
    return json.loads(path.read_bytes())


def as_date(value):
    if isinstance(value, (int, float)) and int(value) == value:
        return date(1899, 12, 30) + timedelta(days=int(value))
    return date.fromisoformat(value)


def number(value):
    if value is None or value in ("", UNKNOWN, "nan"):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite source value")
    return result


def truth(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.lower()
        if value in ("true", "1"):
            return True
        if value in ("false", "0"):
            return False
    if value in (None, "", "unknown"):
        return None
    raise ValueError(f"Invalid tri-valued flag {value!r}")


def status(value):
    return UNKNOWN if value is None else str(value).upper()


def conjunction(*values):
    if False in values:
        return False
    return None if None in values else True


def disjunction(*values):
    if True in values:
        return True
    return None if None in values else False


def compare(test: Callable, *values):
    return None if None in values else test(*values)


def tags(value):
    return frozenset() if value in ("", "NONE") else frozenset(value.split("|"))


@dataclass(frozen=True)
class Session:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    pct: float | None
    w: float | None
    y: float | None
    bbi: float | None
    j: float | None

    @classmethod
    def from_row(cls, row):
        prices = tuple(number(row[k]) for k in ("open", "high", "low", "close"))
        volume = number(row["volume"])
        if None in prices or volume is None:
            raise ValueError(f"Missing OHLCV on {row['date']}")
        op, hi, lo, cl = prices
        if lo <= 0 or lo > min(op, cl) or max(op, cl) > hi or volume < 0:
            raise ValueError(f"Invalid OHLCV on {row['date']}")
        return cls(
            as_date(row["date"]), *prices, volume,
            number(row.get("pct_change", row.get("pct_chg"))),
            *(number(row.get(key)) for key in ("W", "Y", "BBI", "J")),
        )


def read_cohort(paths: Iterable[Path]):
    fieldnames = None
    rows = {}
    previous = None
    for path in paths:
        page = read_json(path)
        values = page["values"]
        if fieldnames is None:
            fieldnames, *values = values
            if len(set(fieldnames)) != len(fieldnames):
                raise ValueError("Duplicate three-layer field")
        for values_row in values:
            row = dict(zip(fieldnames, values_row))
            day = as_date(row["date"])
            if row["ts_code"] != SYMBOL or (previous is not None and day <= previous):
                raise ValueError("Unexpected symbol or non-unique/unordered cohort dates")
            if any(as_date(row[key]) > day for key in ("m25_d_date", "m25_t_date", "m25_c_date") if row[key]):
                raise ValueError(f"Post-D historical #25 event on {day}")
            rows[day] = row
            previous = day
    if not rows:
        raise ValueError("Empty three-layer cohort")
    return rows


def read_baseline(path: Path, cohort):
    rows = {}
    last_day = max(cohort)
    previous = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            day = as_date(row["date"])
            if day > last_day:
                break
            if previous is not None and day <= previous:
                raise ValueError("Unordered or duplicate V4.0 baseline date")
            if row["ts_code"] != SYMBOL or row["engine_version"] != "V4.0" or row["action_id"] != "ACT-065A":
                raise ValueError(f"Unexpected V4.0 baseline identity on {day}")
            if day in cohort:
                if any(as_date(row[key]) > day for key in ("m25_d_date", "m25_t_date", "m25_c_date") if row[key]):
                    raise ValueError(f"Post-D V4.0 #25 event on {day}")
                rows[day] = row
            if day == last_day:
                break
            previous = day
    return rows


def through_sessions(path: Path, cutoff: date):
    """Yield through exact cutoff and stop without requesting the next row."""
    previous = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            day = as_date(row["date"])
            if day > cutoff:
                raise ValueError(f"Cutoff {cutoff} absent from session projection")
            if row.get("ts_code", SYMBOL) != SYMBOL or (previous is not None and day <= previous):
                raise ValueError(f"Wrong market/symbol or duplicate/unordered sessions at {day}")
            yield Session.from_row(row)
            if day == cutoff:
                return
            previous = day
    raise ValueError(f"Cutoff {cutoff} absent from session projection")


def validate_contract(document):
    master = document["frozen_master_decisions"]
    governance = document["governance"]
    if document["schema_id"] != "V4.1_SEMANTIC_SCHEMA_CONTRACT" or document["schema_version"] != "4.1":
        raise ValueError("Unexpected semantic contract")
    if tuple(track["track_id"] for track in master["method_20"]["tracks"]) != TRACKS:
        raise ValueError("Unexpected B2 track definitions")
    if governance["review_mode"] != "D_ONLY" or governance["S_FIT"] != 0 or governance["B_FIT"] != 0:
        raise ValueError("Unexpected governance contract")
    return master


class Shadow:
    """Only `advance` receives a session, and all evidence comes from its prefix."""

    def __init__(self, master, *, continuous_sessions):
        self.formal = master["method_19"]["formal_layer"]
        self.rebuild = master["method_25"]
        self.retest_window = master["method_20"]["lifecycle"]["D0_to_retest_window_trading_days"]
        self.continuous = continuous_sessions
        self.bars = deque(maxlen=10)
        self.raw_anchors = deque()
        self.past_events = deque(maxlen=self.retest_window[-1])
        self.latest = None
        self.index = -1

    def advance(self, bar: Session):
        if self.latest is not None and bar.day <= self.latest:
            raise ValueError("Shadow sessions must be strictly increasing")
        self.index += 1
        self.latest = bar.day
        raw = conjunction(
            compare(lambda bbi, w: bbi > w, bar.bbi, bar.w),
            compare(lambda w, y: w > y, bar.w, bar.y),
            compare(lambda j: j <= 13, bar.j),
        )
        formal = self._formal_b1(bar, raw)
        tracks, f03_details = self._b2_tracks(bar)
        retest = self._b2_retests()
        volume_diagnostics = self._volume_diagnostics(bar)
        self.raw_anchors.append({"index": self.index, "day": bar.day, "raw": raw})
        self.past_events.append((bar.day, tracks))
        self.bars.append(bar)
        return {
            "b1_raw": status(raw),
            **formal,
            **volume_diagnostics,
            **{key: status(value) for key, value in tracks.items()},
            "b2_d0_observed_tracks": "|".join(key for key, value in tracks.items() if value is True),
            **retest,
            **f03_details,
            "m25": UNKNOWN,
            "m25_reason": "ORIGINAL_DAMAGE_YELLOW_TEST_REBUILD_HISTORY_AND_RISK_NOT_RECOVERED",
            **{f"m25_{event['event_id']}_status": UNKNOWN for event in self.rebuild["event_contract"]},
            **{f"m25_{event['event_id']}_missing": "|".join(event["required_fields"]) for event in self.rebuild["event_contract"]},
            "m25_RISK_CLEAR_status": UNKNOWN,
            "m25_RISK_CLEAR_missing": "|".join(self.rebuild["independent_risk_gate"]["required_checks"]),
        }

    def _formal_b1(self, bar, raw):
        min_age, max_age = self.formal["raw_to_formal_window_trading_days"]
        while self.raw_anchors and self.index - self.raw_anchors[0]["index"] > max_age:
            self.raw_anchors.popleft()
        anchors = [anchor for anchor in self.raw_anchors if self.index - anchor["index"] >= min_age]
        known_anchors = [anchor for anchor in anchors if anchor["raw"] is True]
        maybe_anchor = any(anchor["raw"] is None for anchor in anchors) or self.index < max_age
        primary = self.formal["support_confirmation"]["primary_path"]
        dist_y = compare(lambda close, y: 100 * (close / y - 1) if y > 0 else None, bar.close, bar.y)
        dist_w = compare(lambda close, w: 100 * (close / w - 1) if w > 0 else None, bar.close, bar.w)
        support = conjunction(
            compare(lambda value: value >= primary["dist_yellow_pct_gte"], dist_y),
            compare(lambda value: value >= primary["dist_white_pct_gte"], dist_w),
            compare(lambda value: abs(value) <= primary["abs_pct_change_lte"], bar.pct),
        )
        phase = "RAW_ONLY" if raw is True else "NO_ACTIVE_RAW"
        if not self.continuous:
            result, phase, reason = None, UNKNOWN, "SESSION_CONTINUITY_NOT_VERIFIED"
        elif not known_anchors:
            result, reason = (None, "PRIOR_RAW_HISTORY_INCOMPLETE") if maybe_anchor else (False, "NO_PRIOR_RAW_IN_WINDOW")
        else:
            result, phase, reason = None, "WAIT_PULLBACK", "ANCHOR_KEYED_PULLBACK_VOLUME_AND_RISK_NOT_RECOVERED"
        return {
            "b1_formal": status(result), "b1_phase": phase, "b1_formal_reason": reason,
            "b1_prior_raw_dates": "|".join(str(anchor["day"]) for anchor in known_anchors),
            "b1_prior_raw_ages_trading_days": "|".join(str(self.index - anchor["index"]) for anchor in known_anchors),
            "b1_primary_price_diagnostic": status(support),
            "b1_dist_white_pct": dist_w,
            "b1_dist_yellow_pct": dist_y,
            "b1_risk_present": UNKNOWN,
            "b1_risk_missing": "|".join(B1_RISK_CHECKS),
            "b1_anchored_pullback": UNKNOWN,
            "b1_pullback_trading_sessions": UNKNOWN,
            "b1_pullback_drawdown_pct": UNKNOWN,
            "b1_pullback_volume_ratio_ma5": UNKNOWN,
            "b1_pullback_ma5_denominator": UNKNOWN,
            "b1_pullback_volume_ratio_ma10": UNKNOWN,
            "b1_pullback_ma10_denominator": UNKNOWN,
            "b1_pullback_volume_ratio_attack_peak": UNKNOWN,
            "b1_pullback_attack_peak_denominator": UNKNOWN,
            "b1_needle_recovery": UNKNOWN,
        }

    def _volume_diagnostics(self, bar):
        """Fixed completed-session averages as context, without a pullback anchor."""
        details = {}
        for count in (5, 10):
            window = list(self.bars)[-count:] if self.continuous and len(self.bars) >= count else []
            mean = math.fsum(item.volume for item in window) / count if window else None
            prefix = f"b1_nonqualifying_prior_ma{count}"
            details[f"{prefix}_window_start"] = str(window[0].day) if window else UNKNOWN
            details[f"{prefix}_window_end"] = str(window[-1].day) if window else UNKNOWN
            details[f"{prefix}_denominator"] = mean if mean is not None else UNKNOWN
            details[f"{prefix}_d_volume_ratio"] = bar.volume / mean if mean else UNKNOWN
        return details

    def _b2_tracks(self, bar):
        recent = list(self.bars)
        prior_j = [item.j for item in recent[-2:]] if self.continuous else []
        j_window = [None] * (2 - len(prior_j)) + prior_j + [bar.j]
        had_low_j = disjunction(*(compare(lambda j: j < 13, j) for j in j_window))
        prior_volume = recent[-1].volume if self.continuous and recent else None
        avg_volume = math.fsum(item.volume for item in recent[-4:]) / 4 if self.continuous and len(recent) >= 4 else None
        clauses = {
            "J_LT_13_WITHIN_D_MINUS_2_TO_D": had_low_j,
            "VOL_GT_1_25_TIMES_PRIOR_4_MEAN": compare(lambda v, p: v > p * 1.25, bar.volume, avg_volume),
            "PCT_GT_4": compare(lambda p: p > 4, bar.pct),
            "J_LT_70": compare(lambda j: j < 70, bar.j),
            "W_GT_Y": compare(lambda w, y: w > y, bar.w, bar.y),
        }
        tracks = dict(zip(TRACKS, (
            None,
            conjunction(compare(lambda p: p >= 4, bar.pct), compare(lambda j: j < 55, bar.j)),
            compare(lambda v, p: v > p * 1.20, bar.volume, prior_volume),
            conjunction(*clauses.values()),
            None,
        )))
        return tracks, {
            "b2_f03_failed_clauses": "|".join(name for name, value in clauses.items() if value is False),
            "b2_f03_unknown_clauses": "|".join(name for name, value in clauses.items() if value is None),
            "b2_f03_J_D_MINUS_2_TO_D": "|".join(str(j) if j is not None else UNKNOWN for j in j_window),
            "b2_f03_prior_4_mean_volume": avg_volume,
            "b2_prev_session_volume": prior_volume,
            "b2_formal_retest_source_status": "EXACT_THRESHOLDS_NOT_RECOVERED",
        }

    def _b2_retests(self):
        results = {}
        for track in TRACKS:
            history = [(day, tracks[track]) for age, (day, tracks) in enumerate(reversed(self.past_events), start=1)
                       if self.retest_window[0] <= age <= self.retest_window[1]]
            candidate_dates = [str(day) for day, value in reversed(history) if value is True]
            known_no_candidate = self.continuous and len(self.past_events) == self.retest_window[-1] and all(value is False for _, value in history)
            results[f"{track}_prior_d0_dates"] = "|".join(candidate_dates) if self.continuous else ""
            results[f"{track}_formal_retest"] = "FALSE" if known_no_candidate else UNKNOWN
        return results
