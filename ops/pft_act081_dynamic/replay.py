"""Live positive-root episode, a single P1B clock and D-only decision evidence."""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from ops.pft_act080_core.anchors import KeyKDetector
from ops.pft_act080_core.core import Cooldown, Indicators
from ops.pft_act081_kb.features import LAUNCH_TAGS, POSITION_SESSIONS, bearish_retracement, runup_and_zone


CORE = "DYN_B1_CORE"
STRICT = "DYN_B1_STRICT"
METHOD_PATH = Path(__file__).with_name("method.json")
METHOD = json.loads(METHOD_PATH.read_text(encoding="utf-8"))
ROOT = METHOD["root"]
S1 = METHOD["distribution"]
STRUCTURE = METHOD["structure"]
BALANCE = METHOD["balance"]
STRICT_RULE = METHOD["strict"]


def stable_id(namespace, security_id, day):
    return sha256(f"ACT081_P2|{namespace}|{security_id}|{day}".encode("ascii")).hexdigest()


def valid(bars, expected):
    return len(bars) == expected and all(bar.positive_ohlc for bar in bars)


def bear(bar):
    return bar.close < bar.open


def bull(bar):
    return bar.close > bar.open


def volumes(window):
    return sum(bar.volume for bar in window if bull(bar)), sum(bar.volume for bar in window if bear(bar))


def meets_red_green(red, green, threshold):
    return red > 0 and red >= threshold * green


def mean_volume(window, expected):
    return sum(bar.volume for bar in window) / expected if valid(window, expected) else 0


def root_evidence(history, bar):
    """Return the fixed formation window and kind, in preregistered priority order."""
    if not history or not bar.positive_ohlc or not bull(bar) or bar.volume <= 0:
        return None
    previous = history[-1]
    if not previous.positive_ohlc or bar.close <= previous.close:
        return None
    volume_sessions = ROOT["volume_base_sessions"]
    base = mean_volume(history[-volume_sessions:], volume_sessions)
    min_change = Decimal(str(1 + ROOT["single_return_min"]))
    if base > 0 and bar.volume >= ROOT["single_volume_ratio"] * base and (
        Decimal(str(bar.close)) >= Decimal(str(previous.close)) * min_change
    ):
        return "BULL_SINGLE", [bar]
    stack_n = ROOT["stack_sessions"]
    prior_count = stack_n - 1
    stack = [*history[-prior_count:], bar]
    stack_base = mean_volume(history[-volume_sessions-prior_count:-prior_count], volume_sessions)
    if stack_base > 0 and valid(stack, stack_n) and all(map(bull, stack)) and (
        all(a.close < b.close for a, b in zip(stack, stack[1:]))
        and sum(b.volume for b in stack) >= stack_n * ROOT["stack_volume_ratio"] * stack_base
    ):
        return "BULL_STACK", stack
    gentle_n = ROOT["gentle_sessions"]
    gentle = [*history[-(gentle_n - 1):], bar]
    if len(history) >= gentle_n and history[-gentle_n].positive_ohlc and valid(gentle, gentle_n):
        red, green = volumes(gentle)
        if (
            bar.close > history[-gentle_n].close
            and sum(map(bull, gentle)) > sum(map(bear, gentle))
            and meets_red_green(red, green, ROOT["gentle_red_green_min"])
        ):
            return "GENTLE_RED_FAT", gentle
    return None


def high_distribution(history, bar, previous_atr):
    window_n = ROOT["volume_base_sessions"]
    recent = history[-window_n:]
    base = mean_volume(recent, window_n)
    if not bar.positive_ohlc or base <= 0 or bar.volume < S1["volume_ratio"] * base:
        return False
    high, low = max(b.high for b in recent), min(b.low for b in recent)
    if high <= low or bar.high < low + S1["high_position"] * (high - low):
        return False
    span = bar.high - bar.low
    wick = span > 0 and bar.high - max(bar.open, bar.close) >= S1["upper_wick_share"] * span
    heavy_bear = (
        previous_atr is not None and previous_atr > 0 and bear(bar) and bar.close < recent[-1].close
        and bar.open - bar.close >= S1["heavy_bear_body_atr"] * previous_atr
    )
    return wick or heavy_bear


@dataclass(slots=True)
class Mother:
    episode_id: str
    kind: str
    day: str
    session: int
    start_D: str
    floor: float
    bull_peak: float
    red: float
    green: float
    has_first: bool = False

    @classmethod
    def create(cls, security_id, session, evidence):
        kind, window = evidence
        last = window[-1]
        red, green = volumes(window)
        assert bull(last) and red > 0
        return cls(
            stable_id("MOTHER", security_id, last.trade_date), kind, last.trade_date, session,
            window[0].trade_date, min(bar.low for bar in window),
            max(bar.volume for bar in window if bull(bar)), red, green,
        )

    def observe(self, bar):
        if bull(bar):
            self.red += bar.volume
        elif bear(bar):
            self.green += bar.volume

    def invalidation(self, session, bar, previous, previous_atr, distribution):
        if session - self.session > ROOT["age_max"]:
            return "ANCHOR_EXPIRED"
        if not bar.positive_ohlc:
            return "UNKNOWN_OHLC_AFTER_ANCHOR"
        if bar.low < self.floor:
            return "ANCHOR_LOW_BREACHED"
        if distribution:
            return "S1_HIGH_VOLUME_DISTRIBUTION"
        if previous_atr is not None and previous_atr > 0 and (
            bear(bar) and bar.close < previous.close
            and bar.volume >= S1["pullback_bear_peak_ratio"] * self.bull_peak
            and bar.open - bar.close >= S1["pullback_bear_body_atr"] * previous_atr
        ):
            return "S1_ABNORMAL_BEAR_PULLBACK"
        return ""


def ordered_structure(window, atr):
    leg = STRUCTURE["leg_sessions"]
    if not valid(window, 2 * leg) or atr is None or atr <= 0:
        return False
    older, newer = window[:leg], window[leg:]
    old_low, new_low = min(b.low for b in older), min(b.low for b in newer)
    old_high, new_high = max(b.high for b in older), max(b.high for b in newer)
    tolerance = STRUCTURE["lower_shift_atr"] * atr
    if new_low < old_low - tolerance and new_high < old_high - tolerance:
        return False
    higher_low = new_low > old_low and new_high >= old_high - STRUCTURE["higher_low_max_high_drop_atr"] * atr
    platform = abs(new_low - old_low) <= tolerance and (
        max(old_high, new_high) - min(old_low, new_low) <= STRUCTURE["platform_max_span_atr"] * atr
    )
    return higher_low or platform


def order_line(w, y, previous_w, previous_y, atr):
    if y is None or y <= 0 or w < y:
        return False
    crossed = previous_y is not None and previous_w < previous_y
    return not crossed or (
        atr is not None and y - previous_y >= -STRUCTURE["fresh_cross_max_y_drop_atr"] * atr
    )


def balance_checks(history, bar, atr, w, y, mother):
    base_sessions = BALANCE["range_base_sessions"]
    recent = history[-base_sessions:]
    minimum = bar.positive_ohlc and atr is not None and atr > 0 and valid(recent, base_sessions)
    span = bar.high - bar.low
    mean_range = sum(b.high - b.low for b in recent) / base_sessions if minimum else None
    checks = {
        "D_RANGE_CONTRACTION": minimum and (
            span <= BALANCE["range_relative_ceiling"] * mean_range or span <= BALANCE["range_atr_ceiling"] * atr
        ),
        "D_BODY_CONTRACTION": minimum and abs(bar.close - bar.open) <= BALANCE["body_atr_ceiling"] * atr,
        "D_NO_PRICE_PULSE_CHASE": minimum and abs(bar.close - history[-1].close) <= (
            BALANCE["close_jump_atr_ceiling"] * atr
        ) and bar.close <= w + BALANCE["line_distance_atr"] * atr,
        "D_VOLUME_BELOW_TRUE_BULL_PEAK": mother is not None and 0 < bar.volume < mother.bull_peak,
        "D_SUPPORT_BAND": minimum and mother is not None and (
            w > 0 and abs(bar.close - w) <= BALANCE["line_distance_atr"] * atr
            or y is not None and y > 0 and abs(bar.close - y) <= BALANCE["line_distance_atr"] * atr
            or mother.floor <= bar.close <= mother.floor + BALANCE["anchor_distance_atr"] * atr
        ),
    }
    return checks, mean_range


def replay(security_id, bars):
    indicators, danger_keys, clock = Indicators(), KeyKDetector(), Cooldown()
    lows = deque(maxlen=POSITION_SESSIONS)
    warning_pairs = deque(maxlen=S1["false_breakout_sessions"])
    history = deque(maxlen=ROOT["volume_base_sessions"] + ROOT["stack_sessions"] - 1)
    previous_launch = False
    last_mother_end = ""
    mother = None
    daily, events = [], []
    for session, bar in enumerate(bars):
        prior = list(history)
        previous = prior[-1] if prior else None
        if previous is not None and bar.trade_date <= previous.trade_date:
            raise ValueError(f"{security_id}: observed sessions must be strictly ordered")
        previous_w, previous_y, previous_atr = indicators.w, indicators.y, indicators.atr
        values = indicators.advance(bar)
        w, y = values["W"], values["Y"]
        current_launch = bool(LAUNCH_TAGS.intersection(danger_keys.advance(bar)))
        distribution = high_distribution(prior, bar, previous_atr)
        if previous is not None:
            warning_pairs.append(bearish_retracement(previous, bar, previous_launch))
        warning = True if any(warning_pairs) else (
            False if len(warning_pairs) == S1["false_breakout_sessions"] else None
        )
        if mother is not None:
            invalidation = mother.invalidation(session, bar, previous, previous_atr, distribution)
            if invalidation:
                last_mother_end = invalidation
                mother = None
            else:
                mother.observe(bar)
        new_root = root_evidence(prior, bar) if mother is None and not distribution else None
        if new_root is not None:
            mother = Mother.create(security_id, session, new_root)
        age = session - mother.session if mother else None
        lows.append(bar.low)
        runup, zone = runup_and_zone(bar.close, lows)
        structure_n = STRUCTURE["leg_sessions"] * 2
        checks = {
            "L1_LIVE_BULL_MOTHER_AGE_3_45": age is not None and ROOT["age_min"] <= age <= ROOT["age_max"],
            "L1_NO_HIGH_VOLUME_DISTRIBUTION": not distribution,
            "L1_NO_3Q_BEAR_FALSE_BREAKOUT": warning is False,
            "L1_WHITE_GE_YELLOW_ORDER": order_line(w, y, previous_w, previous_y, previous_atr),
            "L1_HIGHER_LOW_OR_PLATFORM": ordered_structure(
                [*prior[-(structure_n - 1):], bar], previous_atr
            ),
        }
        dynamic, mean_range = balance_checks(prior, bar, previous_atr, w, y, mother)
        checks.update(dynamic)
        core_ok = all(checks.values())
        strict_checks = {
            "STRICT_RED_GREEN_GE_1_5": mother is not None and (
                meets_red_green(mother.red, mother.green, STRICT_RULE["red_green_min"])
            ),
            "STRICT_LOW_FIRST_WAVE_60D": zone == "LOW_FIRST_WAVE",
        }
        strict_ok = all(strict_checks.values())
        row = {
            "security_id": security_id, "trade_date": bar.trade_date, "session_idx": session,
            "structure_episode_id": mother.episode_id if mother else None,
            "key_k_date": mother.day if mother else None, "anchor_age_sessions": age,
            "mother_session_idx": mother.session if mother else None,
            "mother_formation_start_D": mother.start_D if mother else None,
            "mother_kind": mother.kind if mother else None,
            "mother_floor": mother.floor if mother else None,
            "mother_true_bull_peak": mother.bull_peak if mother else None,
            "mother_red_volume": mother.red if mother else None,
            "mother_green_volume": mother.green if mother else None,
            "last_mother_end_reason": last_mother_end,
            "W": w, "Y": y, "prior_ATR14": previous_atr, "prior10_mean_range": mean_range,
            "range_D": bar.high - bar.low, "body_D": abs(bar.close - bar.open),
            "volume_D": bar.volume, "close_D": bar.close,
            "warning_3q_bear": warning, "s1_high_distribution": distribution,
            "runup_60d": runup, "position_60d": zone,
            "core_eligible": core_ok, "strict_eligible_pre_cooldown": core_ok and strict_ok,
            "core_failed_gates": "|".join(k for k, accepted in checks.items() if not accepted),
            "strict_failed_gates": "|".join(k for k, accepted in strict_checks.items() if not accepted),
        }
        daily.append(row)
        if core_ok:
            order = clock.consider(session, 1)
            role = None
            if order["accepted_flag"]:
                role = "REPEAT" if mother.has_first else "FIRST"
                mother.has_first = True
            events.append({
                "candidate_event_id": stable_id(CORE, security_id, bar.trade_date),
                **row, **order, "track": CORE, "accepted_role": role,
                "strict_first_hit": role == "FIRST" and strict_ok,
            })
        history.append(bar)
        previous_launch = current_launch
    return daily, events
