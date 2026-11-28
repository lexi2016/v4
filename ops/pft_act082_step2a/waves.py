"""Raw P1B opportunities and D-only coverage screens, without cooldown callers."""

from collections import defaultdict

from ops.pft_act080_core.core import CONFIG, Cooldown, ReplayState, qualified_arms

from .calendar import DEV_END, LabelUnavailable, build_labels, day_status, OBSERVED, require_dev_bars
from .sampling import B2_INITIAL, B3_EXPAND, B3_SHRINK, Candidate, group_frame

JUNDA = "002865.SZ"


def continuation_screen(bar, prior_launch):
    if prior_launch is None or not (
        0 < bar.close - bar.open < prior_launch.close - prior_launch.open and bar.close >= prior_launch.low
    ):
        return None
    if bar.volume < prior_launch.volume:
        return B3_SHRINK
    if bar.volume > prior_launch.volume:
        return B3_EXPAND
    return None


def raw_opportunities(chain, calendar, suspensions):
    """Replay the frozen P1B causal episode transitions, including uncooled proposals."""
    security = chain.security_id
    if security == JUNDA:
        raise ValueError("DEBUG_ONLY_JUNDA cannot enter DEV")
    require_dev_bars(chain.bars, calendar)
    replay = ReplayState(security, chain.provenance)
    prior_b_proposal = {}
    last_break = None
    age_range = CONFIG["episode"]
    for bar in chain.bars:
        if day_status(bar.trade_date, bar, suspensions) != OBSERVED:
            continue
        replay.session_idx += 1
        prev = replay.episode
        values = replay.indicators.advance(bar)
        if prev is not None and bar.close < prev.key_k_low:
            last_break = (prev.key_k_date, bar.trade_date)
            yield Candidate(
                security, prev.episode_id, bar.trade_date, prev.key_k_date,
                (prev.key_k_date,), "P1B_ANCHOR_LOW_BREAK_PROPOSAL",
            ), ("C",), replay.session_idx
        valid = replay._advance_episode(bar, values)
        current = replay.episode
        if not valid:
            continue
        age = replay.session_idx - current.anchor_idx
        if not age_range["candidate_age_min_sessions"] <= age < age_range["candidate_age_limit_exclusive_sessions"]:
            continue
        arms = qualified_arms(values)
        coverage = set()
        prior_launch = prior_b_proposal.get(current.episode_id)
        continuation = continuation_screen(bar, prior_launch)
        if {"A", "C"}.intersection(arms):
            coverage.add("A")
        if "B" in arms and bar.close > bar.open:
            coverage.add(B2_INITIAL)
            prior_b_proposal[current.episode_id] = bar
        elif continuation:
            coverage.add(continuation)
        if not arms and not continuation:
            continue
        dates = (current.key_k_date,)
        if last_break and current.start_reason == "AFTER_ANCHOR_LOW_BREAK":
            dates += last_break
            coverage.add("C")
        yield Candidate(
            security, current.episode_id, bar.trade_date, current.key_k_date, dates,
            ("P1B_RAW_" + "".join(arms)) if arms else "POST_LAUNCH_POSITIVE_CONTINUATION_PROPOSAL",
        ), tuple(sorted(coverage)), replay.session_idx


def dev_frame(chains, calendars, suspensions):
    eligible, unavailable = [], defaultdict(int)
    raw = []
    intervals = {}
    for chain in chains:
        stock = chain.security_id
        bars = {bar.trade_date: bar for bar in chain.bars}
        cal = calendars[stock[-2:]]
        for candidate, coverage, clock in raw_opportunities(chain, cal, suspensions.get(stock, frozenset())):
            raw.append((candidate, clock))
            try:
                info = build_labels(candidate, bars, cal, suspensions.get(stock, frozenset()))
            except LabelUnavailable as exc:
                unavailable[str(exc)] += 1
                continue
            if info["label_end_date_actual"] > DEV_END:
                raise AssertionError("future DEV interval passed")
            intervals[candidate] = info
            eligible.append((candidate, coverage))
    return group_frame(eligible), intervals, raw, dict(unavailable)


def vault_b_cooldown(raw):
    """Compute after frame lock. This mapping cannot be consumed by sampling."""
    lookup = {}
    clocks = defaultdict(Cooldown)
    rank = defaultdict(int)
    for candidate, clock in raw:
        identity = candidate.security_id, clock
        rank[identity] += 1
        row = clocks[candidate.security_id].consider(clock, rank[identity])
        lookup[candidate] = {
            "exec_cooldown_isolated": row["accepted_flag"],
            "exec_cooldown_reason": row["reject_reason"],
            "exec_cooldown_gap_sessions": row["gap_trading_days"],
        }
    return lookup

