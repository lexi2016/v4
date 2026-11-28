"""Exchange sessions, physical DEV cutoff, and actual label execution clock."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date

DEV_END = "2025-09-30"
PURGE_START = "2025-10-01"
PURGE_END = "2025-11-12"
SEAL_START = "2025-11-13"
MARKETS = ("SH", "SZ", "BJ")
HORIZONS = (2, 5, 10, 20)
SUSPENDED = "SUSPENDED"
MISSING = "MISSING_UNCONFIRMED"
OBSERVED = "OBSERVED"
INVALID = "INVALID_OBSERVATION"
FEE_NET = 0.003


class LabelUnavailable(ValueError):
    """No reproducible stock execution path within the allowed time cut."""


@dataclass(frozen=True, slots=True)
class ExchangeCalendar:
    market: str
    sessions: tuple[str, ...]
    source_sha256: str

    def __post_init__(self):
        if self.market not in MARKETS:
            raise ValueError("unsupported exchange")
        if not self.sessions or self.sessions != tuple(sorted(set(self.sessions))):
            raise ValueError("exchange sessions must be unique ascending")
        for value in self.sessions:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("noncanonical session date")
        if len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("missing calendar source digest")

    def between(self, left, right):
        return self.sessions[bisect_left(self.sessions, left):bisect_right(self.sessions, right)]


def validate_purge(calendars):
    sh = calendars["SH"].between(PURGE_START, PURGE_END)
    sz = calendars["SZ"].between(PURGE_START, PURGE_END)
    if sh != sz or len(sh) != 25:
        raise ValueError("frozen SSE/SZSE purge calendar mismatch")
    for market, cal in calendars.items():
        if cal.market != market or cal.between(DEV_END, DEV_END) != (DEV_END,) or (
            cal.between(SEAL_START, SEAL_START) != (SEAL_START,)
        ):
            raise ValueError("frozen boundaries missing on authoritative calendar")
    return sh


def require_dev_bars(bars, cal):
    dates = tuple(bar.trade_date for bar in bars)
    if not dates or dates[-1] > DEV_END or dates != tuple(sorted(set(dates))):
        raise ValueError("non-DEV, empty, or nonmonotonic price payload")
    if set(dates) - set(cal.sessions):
        raise ValueError("observations outside the frozen exchange calendar")


def day_status(day, bar, suspensions):
    if day in suspensions:
        if bar is not None and (bar.volume != 0 or not (bar.open == bar.high == bar.low == bar.close)):
            raise ValueError("suspension conflicts with traded observation")
        return SUSPENDED
    if bar is None:
        return MISSING
    if not bar.positive_ohlc or bar.volume <= 0:
        return INVALID
    return OBSERVED


def build_labels(candidate, bars_by_date, cal, suspensions, *, outcomes=False):
    """Use stock-observed tradable bars, skipping documented suspensions only."""
    day = candidate.D
    if not (candidate.mother_start_date <= day <= DEV_END):
        raise LabelUnavailable("invalid information interval")
    if not cal.between(day, day) or day_status(day, bars_by_date.get(day), suspensions) != OBSERVED:
        raise LabelUnavailable("D is not a proved observed exchange session")
    observed = []
    skipped = []
    for session in cal.between(day, DEV_END)[1:]:
        bar = bars_by_date.get(session)
        state = day_status(session, bar, suspensions)
        if state == SUSPENDED:
            skipped.append(session)
            continue
        if state != OBSERVED:
            raise LabelUnavailable("unconfirmed or invalid observed-path session")
        observed.append(bar)
        if len(observed) == max(HORIZONS):
            break
    if len(observed) != max(HORIZONS):
        raise LabelUnavailable("T+20 actual endpoint is outside DEV or unavailable")
    result = {
        "mother_start_date": candidate.mother_start_date,
        "D": day,
        "feature_available_date": day,
        "label_start_date": observed[0].trade_date,
        "label_end_date_actual": observed[-1].trade_date,
        "exchange_calendar": cal.market,
        "exchange_calendar_sha256": cal.source_sha256,
        "suspended_sessions_skipped": "|".join(skipped),
    }
    result.update({f"t{h}_actual_date": observed[h - 1].trade_date for h in HORIZONS})
    result["max_drawdown_t20_close_end_date"] = observed[-1].trade_date
    if outcomes:
        entry = observed[0].open
        returns = {h: observed[h - 1].close / entry - 1.0 - FEE_NET for h in HORIZONS}
        mae = min(bar.low for bar in observed[:5]) / entry - 1.0 - FEE_NET
        peak, drawdown = entry, 0.0
        for bar in observed:
            peak = max(peak, bar.close)
            drawdown = min(drawdown, bar.close / peak - 1.0)
        result.update({f"t{h}_net": value for h, value in returns.items()})
        result.update(
            mae5_net=mae, standard_tail=returns[2] <= -0.05 or mae <= -0.07, auxiliary_tail=returns[5] <= -0.05,
            max_drawdown_t20_close=drawdown,
        )
    return result


def verify_actual_intervals(rows):
    for row in rows:
        values = tuple(row[key] for key in (
            "mother_start_date", "D", "feature_available_date", "label_start_date",
            "t2_actual_date", "t5_actual_date", "t10_actual_date", "t20_actual_date", "label_end_date_actual",
        ))
        if not (values == tuple(sorted(values)) and values[1] == values[2] and values[2] < values[3]
                and values[-2] == values[-1] == row["max_drawdown_t20_close_end_date"] <= DEV_END < SEAL_START):
            raise ValueError("actual information interval intersects a forbidden boundary")
    return {"actual_information_intersections": 0, "dev_label_end_max": max(
        (row["label_end_date_actual"] for row in rows), default=None
    )}

