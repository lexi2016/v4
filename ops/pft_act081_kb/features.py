"""Forward-only knowledge-base features and disjoint eligibility on P1B state."""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from ops.pft_act080_core.core import CONFIG, ReplayState, qualified_arms


B1 = "TRACK_B1_QUIET_CONSENSUS"
B2 = "TRACK_B2_LAUNCH"
KB = "TRACK_B1_KB_SUBSET"
LEGACY = "V21_FROZEN_FIRST_A"
FEATURES = (
    "kb_red_fat_green_thin_ratio",
    "kb_vol_shrink_vs_peak", "kb_fast_half_shrink_3d",
    "kb_three_quarter_bear_vol_flag",
    "kb_runup_from_60d_low", "kb_pos_zone",
)
LAUNCH_TAGS = frozenset(("BREAKOUT", "VIOLENT"))
POSITION_SESSIONS = 60


@dataclass(slots=True)
class AnchorVolume:
    """Prior episode peak with first occurrence winning ties."""

    peak_idx: int
    peak: float
    red: float = 0
    green: float = 0
    reached_half: bool = False

    def advance(self, session, bar):
        if bar.close >= bar.open:
            self.red += bar.volume
        else:
            self.green += bar.volume
        red_green = (self.red + 1.0) / (self.green + 1.0) if self.red + self.green > 0 else None
        shrink = None
        fast = None
        elapsed = session - self.peak_idx
        if elapsed > 0 and self.peak > 0:
            shrink = bar.volume / self.peak
            if elapsed <= 3 and shrink <= 0.50:
                self.reached_half = True
            if self.reached_half or elapsed >= 3:
                fast = self.reached_half
        if bar.volume > self.peak:
            self.peak_idx, self.peak = session, bar.volume
            self.reached_half = False
        return red_green, shrink, fast


def bearish_retracement(previous, bar, previous_launch):
    return (
        previous_launch and previous.close > previous.open and previous.volume > 0 and bar.positive_ohlc
        and bar.close < bar.open and bar.close < previous.close
        and bar.volume >= 0.75 * previous.volume
    )


def runup_and_zone(close, lows):
    if len(lows) < POSITION_SESSIONS or close <= 0:
        return None, None
    low = min(lows)
    if low <= 0:
        return None, None
    runup = close / low - 1
    exact_close, exact_low = Decimal(str(close)), Decimal(str(low))
    if exact_close <= Decimal("1.35") * exact_low:
        zone = "LOW_FIRST_WAVE"
    elif exact_close >= Decimal("1.80") * exact_low:
        zone = "HIGH_RUNUP"
    else:
        zone = "MID"
    return runup, zone


def b1_checks(stock, bar, previous, values, episode, age, shrink):
    twenty = stock.startswith(("300", "301", "688"))
    move_ok = range_ok = False
    if previous is not None and previous.close > 0:
        base = Decimal(str(previous.close))
        close, high, low = map(lambda value: Decimal(str(value)), (bar.close, bar.high, bar.low))
        move_ok = abs(close - base) * 100 < 2 * base
        range_ok = (high - low) * 100 < (7 if twenty else 4) * base
    return {
        "valid_current_previous": bar.positive_ohlc and previous is not None and previous.close > 0,
        "white_ge_yellow": values["Y"] is not None and values["Y"] > 0 and values["W"] >= values["Y"],
        "close_ge_yellow": values["Y"] is not None and values["Y"] > 0 and bar.close >= values["Y"],
        "small_move": move_ok,
        "small_range": range_ok,
        "active_anchor": episode is not None and 1 <= age <= 45 and bar.close >= episode.key_k_low,
        "half_peak": shrink is not None and shrink <= 0.50,
    }


def _event_id(stock, day, track):
    return sha256(f"ACT081_P1|{stock}|{day}|{track}".encode("ascii")).hexdigest()


class KnowledgeReplay(ReplayState):
    """Use the verified P1B episode lifecycle and one P1B cooldown per stock."""

    def consume(self, bars):
        # This entry point is one physical chain/prefix from a fresh state.
        if self.session_idx != -1:
            raise ValueError("KnowledgeReplay requires a fresh one-pass physical chain")
        previous, previous_launch = None, False
        anchor_volume = None
        lows, bear_pairs = deque(maxlen=POSITION_SESSIONS), deque(maxlen=5)
        first_markers = set()
        daily, events = [], []
        for session, bar in enumerate(bars):
            if previous is not None and bar.trade_date <= previous.trade_date:
                raise ValueError("observed stock sessions must be strictly ordered")
            self.session_idx = session
            values = self.indicators.advance(bar)
            maintained = self._advance_episode(bar, values)
            episode = self.episode
            age = session - episode.anchor_idx if episode else None
            if age == 0:
                anchor_volume = AnchorVolume(session, bar.volume)
            elif episode is None:
                anchor_volume = None
            red_green, shrink, fast = (
                anchor_volume.advance(session, bar) if anchor_volume is not None else (None, None, None)
            )
            if previous is not None:
                bear_pairs.append(bearish_retracement(previous, bar, previous_launch))
            warning = True if any(bear_pairs) else (False if len(bear_pairs) == 5 else None)
            lows.append(bar.low)
            runup, zone = runup_and_zone(bar.close, lows)
            features = dict(zip(FEATURES, (red_green, shrink, fast, warning, runup, zone), strict=True))
            checks = b1_checks(self.security_id, bar, previous, values, episode, age, shrink)
            b1 = all(checks.values())
            p1b_rules = CONFIG["episode"]
            b2 = maintained and p1b_rules["candidate_age_min_sessions"] <= age < (
                p1b_rules["candidate_age_limit_exclusive_sessions"]
            ) and "B" in qualified_arms(values)
            if b1 and b2:
                raise ValueError("B1/B2 predicates overlap")
            track = B1 if b1 else B2 if b2 else None
            common = {
                "security_id": self.security_id, "trade_date": bar.trade_date, "session_idx": session,
                "structure_episode_id": episode.episode_id if episode else None,
                "key_k_date": episode.key_k_date if episode else None,
                "anchor_age_sessions": age, "track": track, **features,
            }
            daily.append({**common, "b1_failed_gates": "|".join(k for k, yes in checks.items() if not yes)})
            if track:
                order = self.cooldown.consider(session, 1)
                role = None
                if order["accepted_flag"]:
                    marker = (track, episode.episode_id)
                    role = "REPEAT" if marker in first_markers else "FIRST"
                    first_markers.add(marker)
                kb_subset = track == B1 and red_green is not None and red_green >= 1.2 and warning is False
                events.append({
                    "candidate_event_id": _event_id(self.security_id, bar.trade_date, track),
                    **common, **order, "accepted_role": role, "kb_subset": kb_subset,
                })
            previous = bar
            previous_launch = age == 0 and bool(LAUNCH_TAGS.intersection(episode.anchor_tags))
        return daily, events
