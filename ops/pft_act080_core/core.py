"""The single forward-only implementation for bars, eligibility and cooldown."""

from collections import deque
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from .anchors import KeyKDetector


CONFIG_PATH = Path(__file__).with_name("config.json")
CONFIG_BYTES = CONFIG_PATH.read_bytes()
CONFIG = json.loads(CONFIG_BYTES)
CONFIG_SHA256 = sha256(CONFIG_BYTES).hexdigest()
ARM_ORDER = tuple(CONFIG["cooldown"]["arms_in_tie_order"])
FEATURE_NAMES = (
    "W", "Y", "atr14", "key_k_atr_distance", "white_bias", "yellow_bias",
    "wy_opening", "wy_opening_atr", "W_slope", "Y_slope", "wy_opening_slope",
    "washout_volume_ratio", "upper_wick_disagreement", "kdj_j", "return_D",
    "prior5_return", "close_location", "range3", "ema50_slope",
)
ID_FIELDS = ("candidate_event_id", "security_id", "trade_date", "session_idx")
WAVE_FIELDS = (
    "structure_episode_id", "key_k_date", "key_k_low", "key_k_session_idx",
    "anchor_primary_type", "anchor_types", "anchor_breakout", "anchor_reversal",
    "anchor_violent", "anchor_funding_activity", "anchor_age_sessions",
    "episode_opened_D", "episode_start_reason", "last_valid_structure_maintenance_idx",
    "episode_role", "accepted_role",
)
LEDGER_FIELDS = (
    *ID_FIELDS, "qualification_arm", "qualification_source", "day_eligible_arms",
    "day_candidate_rank", *WAVE_FIELDS,
    "last_accepted_session_idx_before", "gap_trading_days",
    "last_accepted_session_idx_after", "gap_trading_days_after",
    "accepted_flag", "reject_reason",
    "archive_sha256", "source_chain_sha256", "code_sha256", "config_sha256",
    "cooldown_calendar", "price_basis", "historical_adjustment_pit",
)
FEATURE_FIELDS = (
    *ID_FIELDS, "qualification_arm", *WAVE_FIELDS, "accepted_flag",
    "archive_sha256", "source_chain_sha256", "code_sha256", "config_sha256",
    "price_basis", "historical_adjustment_pit", *FEATURE_NAMES,
)


@dataclass(frozen=True, slots=True)
class Bar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def positive_ohlc(self):
        return min(self.open, self.high, self.low, self.close) > 0

    def __post_init__(self):
        if date.fromisoformat(self.trade_date).isoformat() != self.trade_date:
            raise ValueError(f"noncanonical date {self.trade_date!r}")
        prices = (self.open, self.high, self.low, self.close)
        if not all(isfinite(x) for x in prices):
            raise ValueError(f"invalid OHLC on {self.trade_date}")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError(f"inconsistent OHLC on {self.trade_date}")
        if not isfinite(self.volume) or self.volume < 0:
            raise ValueError(f"invalid volume on {self.trade_date}")


@dataclass(frozen=True, slots=True)
class Provenance:
    archive_sha256: str
    source_chain_sha256: str
    code_sha256: str
    config_sha256: str = CONFIG_SHA256

    def record(self):
        return {
            "archive_sha256": self.archive_sha256,
            "source_chain_sha256": self.source_chain_sha256,
            "code_sha256": self.code_sha256,
            "config_sha256": self.config_sha256,
            "price_basis": CONFIG["price_basis"],
            "historical_adjustment_pit": CONFIG["historical_adjustment_pit"],
        }


@dataclass(slots=True)
class Cooldown:
    last_accepted_session_idx: int | None = None

    def consider(self, session_idx, day_candidate_rank):
        before = self.last_accepted_session_idx
        gap = None if before is None else session_idx - before
        if gap is not None and gap < 0:
            raise ValueError("cooldown sessions out of order")
        if day_candidate_rank > 1:
            reason = "DUPLICATE_SAME_DAY"
        elif gap is None or gap > CONFIG["cooldown"]["gap_sessions"]:
            self.last_accepted_session_idx = session_idx
            reason = ""
        else:
            reason = "COOLDOWN_LE5"
        after = self.last_accepted_session_idx
        return {
            "last_accepted_session_idx_before": before,
            "gap_trading_days": gap,
            "last_accepted_session_idx_after": after,
            "gap_trading_days_after": None if after is None else session_idx - after,
            "accepted_flag": not reason,
            "reject_reason": reason,
        }


def _ema(previous, current, period):
    if previous is None:
        return current
    weight = 2.0 / (period + 1)
    return current * weight + previous * (1.0 - weight)


def _div(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _relative(current, reference):
    if current is None or current <= 0:
        return None
    ratio = _div(current, reference)
    return None if ratio is None else ratio - 1.0


def _diff(first, second):
    return None if first is None or second is None else first - second


class Indicators:
    def __init__(self):
        self.closes = deque(maxlen=114)
        self.volumes = deque(maxlen=5)
        self.highs = deque(maxlen=9)
        self.lows = deque(maxlen=9)
        self.w_seed = self.w = self.y = self.ema50 = self.opening = self.atr = None
        self.atr_seed = []
        self.k = self.d = 50.0

    def advance(self, bar):
        prior = self.closes[-1] if self.closes else None
        prior5 = _relative(prior, self.closes[-6]) if len(self.closes) >= 6 else None
        volume_mean = sum(self.volumes) / 5 if len(self.volumes) == 5 else None
        self.volumes.append(bar.volume)
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        previous_w, previous_y, previous_opening = self.w, self.y, self.opening
        previous_ema50 = self.ema50
        self.w_seed = _ema(self.w_seed, bar.close, 10)
        self.w = _ema(self.w, self.w_seed, 10)
        if len(self.closes) == 114:
            closes = list(self.closes)
            self.y = sum(sum(closes[-n:]) / n for n in (14, 28, 57, 114)) / 4
        self.ema50 = _ema(self.ema50, bar.close, 50)
        self.opening = (
            _div(_diff(self.w, self.y), self.y) if self.w > 0 else None
        )

        span = bar.high - bar.low
        true_range = span if prior is None else max(span, abs(bar.high - prior), abs(bar.low - prior))
        if self.atr is None:
            self.atr_seed.append(true_range)
            if len(self.atr_seed) == 14:
                self.atr = sum(self.atr_seed) / 14
        else:
            self.atr = (13 * self.atr + true_range) / 14

        j = None
        if len(self.lows) == 9 and min(self.lows) > 0:
            low, high = min(self.lows), max(self.highs)
            rsv = _div(100 * (bar.close - low), high - low)
            if rsv is not None:
                self.k = (2 * self.k + rsv) / 3
                self.d = (2 * self.d + self.k) / 3
                j = 3 * self.k - 2 * self.d
        range3 = None
        if len(self.lows) >= 3:
            range3 = _relative(max(list(self.highs)[-3:]), min(list(self.lows)[-3:]))
        return {
            "W": self.w,
            "Y": self.y,
            "atr14": self.atr,
            "white_bias": _relative(bar.close, self.w),
            "yellow_bias": _relative(bar.close, self.y),
            "wy_opening": self.opening,
            "wy_opening_atr": (
                _div(_diff(self.w, self.y), self.atr)
                if self.w > 0 and self.y is not None and self.y > 0 else None
            ),
            "W_slope": _relative(self.w, previous_w),
            "Y_slope": _relative(self.y, previous_y),
            "wy_opening_slope": _diff(self.opening, previous_opening),
            "washout_volume_ratio": _div(bar.volume, volume_mean),
            "upper_wick_disagreement": _div(bar.high - max(bar.open, bar.close), span),
            "kdj_j": j,
            "return_D": _relative(bar.close, prior),
            "prior5_return": prior5,
            "close_location": _div(bar.close - bar.low, span),
            "range3": range3,
            "ema50_slope": _diff(self.ema50, previous_ema50),
        }


def _ge(value, minimum):
    return value is not None and value >= minimum


def _le(value, maximum):
    return value is not None and value <= maximum


def _between(value, limits):
    return value is not None and limits[0] <= value <= limits[1]


def _abs(value):
    return None if value is None else abs(value)


def qualified_arms(values):
    thresholds = CONFIG["qualification"]
    a, b, c = (thresholds[arm] for arm in ARM_ORDER)
    w, y = values["W"], values["Y"]
    day, bias, volume = (values[key] for key in ("return_D", "white_bias", "washout_volume_ratio"))
    a_hit = (
        y is not None and y > 0 and w > 0
        and (_ge(_diff(w, y), 0) or _le(_abs(values["wy_opening_atr"]), a["glue_atr_max"]))
        and (_between(bias, a["white_bias"]) or _le(_abs(values["yellow_bias"]), a["yellow_abs_bias_max"]))
        and (_le(volume, a["volume_ratio_max"]) or _le(values["kdj_j"], a["j_max"]))
        and _between(day, a["return"])
    )
    b_hit = (
        _ge(day, b["return_min"])
        and _ge(values["close_location"], b["close_location_min"])
        and _ge(volume, b["volume_ratio_min"])
        and _le(values["prior5_return"], b["prior5_return_max"])
        and _between(bias, b["white_bias"])
    )
    c_hit = (
        y is not None and y > 0 and w > y
        and _between(bias, c["white_bias"])
        and _le(volume, c["volume_ratio_max"])
        and _le(values["range3"], c["range3_max"])
        and values["ema50_slope"] is not None and values["ema50_slope"] > 0
    )
    return tuple(arm for arm, hit in zip(ARM_ORDER, (a_hit, b_hit, c_hit), strict=True) if hit)


def _stable_id(namespace, *parts):
    version = CONFIG["candidate_id_namespace"] if namespace == "CANDIDATE" else CONFIG["schema"]
    return sha256("|".join((version, namespace, *parts)).encode("ascii")).hexdigest()


@dataclass(slots=True)
class Episode:
    episode_id: str
    key_k_date: str
    key_k_low: float
    anchor_idx: int
    anchor_tags: tuple[str, ...]
    start_reason: str
    last_maintenance_idx: int
    has_raw: bool = False
    raw_confirmed: bool = False
    has_accepted: bool = False
    accepted_confirmed: bool = False

    def raw_day_role(self, b_eligible):
        if not self.has_raw:
            self.has_raw = True
            return "FIRST"
        if b_eligible and not self.raw_confirmed:
            self.raw_confirmed = True
            return "CONFIRM"
        return "REPEAT"

    def accepted_role(self, b_eligible):
        if not self.has_accepted:
            self.has_accepted = True
            return "FIRST"
        if b_eligible and not self.accepted_confirmed:
            self.accepted_confirmed = True
            return "CONFIRM"
        return "REPEAT"


class ReplayState:
    """Retain this per-security state across chunks or call it for a single new bar."""

    def __init__(self, security_id, provenance):
        self.security_id = security_id
        self.provenance = provenance
        self.last_date = None
        self.session_idx = -1
        self.indicators = Indicators()
        self.key_k = KeyKDetector()
        self.episode = None
        self.pending_start_reason = "INITIAL_KEY_K"
        self.cooldown = Cooldown()

    def _advance_episode(self, bar, values):
        episode = self.episode
        rules = CONFIG["episode"]
        if episode is not None:
            if bar.close < episode.key_k_low:
                self.pending_start_reason = "AFTER_ANCHOR_LOW_BREAK"
                episode = None
            elif self.session_idx - episode.last_maintenance_idx > rules["maintenance_gap_limit_sessions"]:
                self.pending_start_reason = "AFTER_MAINTENANCE_EXPIRY"
                episode = None

        tags = self.key_k.advance(bar)
        if tags:
            reason = "REPLACED_BY_NEW_KEY_K" if episode is not None else self.pending_start_reason
            episode = Episode(
                _stable_id("EPISODE", self.security_id, bar.trade_date),
                bar.trade_date, bar.low, self.session_idx, tags, reason, self.session_idx,
            )
        self.episode = episode
        if episode is None or not bar.positive_ohlc or bar.close < episode.key_k_low:
            return False

        w, y, gap_atr = (values[name] for name in ("W", "Y", "wy_opening_atr"))
        if w <= 0 or y is None or y <= 0:
            return False
        maintained = (w >= y and bar.close >= y) or (
            gap_atr is not None and abs(gap_atr) <= rules["glue_atr_max"] and bar.close >= w
        )
        if maintained:
            episode.last_maintenance_idx = self.session_idx
        return maintained

    def consume(self, bars):
        ledger, features = [], []
        source = self.provenance.record()
        for bar in bars:
            if self.last_date is not None and bar.trade_date <= self.last_date:
                raise ValueError(f"{self.security_id}: repeated or out-of-order D {bar.trade_date}")
            self.last_date = bar.trade_date
            self.session_idx += 1

            values = self.indicators.advance(bar)
            if not self._advance_episode(bar, values):
                continue
            episode = self.episode
            age = self.session_idx - episode.anchor_idx
            rules = CONFIG["episode"]
            if not rules["candidate_age_min_sessions"] <= age < rules["candidate_age_limit_exclusive_sessions"]:
                continue
            arms = qualified_arms(values)
            if not arms:
                continue
            b_eligible = "B" in arms
            raw_role = episode.raw_day_role(b_eligible)
            values["key_k_atr_distance"] = _div(bar.close - episode.key_k_low, values["atr14"])
            for rank, arm in enumerate(arms, 1):
                order = self.cooldown.consider(self.session_idx, rank)
                accepted = order["accepted_flag"]
                identity = {
                    "candidate_event_id": _stable_id("CANDIDATE", self.security_id, bar.trade_date, arm),
                    "security_id": self.security_id,
                    "trade_date": bar.trade_date,
                    "session_idx": self.session_idx,
                    "qualification_arm": arm,
                }
                wave = {
                    "structure_episode_id": episode.episode_id,
                    "key_k_date": episode.key_k_date,
                    "key_k_low": episode.key_k_low,
                    "key_k_session_idx": episode.anchor_idx,
                    "anchor_primary_type": episode.anchor_tags[0],
                    "anchor_types": "|".join(episode.anchor_tags),
                    "anchor_breakout": "BREAKOUT" in episode.anchor_tags,
                    "anchor_reversal": "REVERSAL" in episode.anchor_tags,
                    "anchor_violent": "VIOLENT" in episode.anchor_tags,
                    "anchor_funding_activity": "FUNDING_ACTIVITY" in episode.anchor_tags,
                    "anchor_age_sessions": age,
                    "episode_opened_D": age == 0,
                    "episode_start_reason": episode.start_reason,
                    "last_valid_structure_maintenance_idx": episode.last_maintenance_idx,
                    "episode_role": raw_role if rank == 1 else "REPEAT",
                    "accepted_role": episode.accepted_role(b_eligible) if accepted else None,
                }
                ledger.append({
                    **identity, **wave, **order, **source,
                    "qualification_source": f'{CONFIG["qualification_source"]}_{arm}',
                    "day_eligible_arms": "|".join(arms),
                    "day_candidate_rank": rank,
                    "cooldown_calendar": CONFIG["cooldown_calendar"],
                })
                features.append({**identity, **wave, **source, "accepted_flag": accepted, **values})
        return ledger, features
