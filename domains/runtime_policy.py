"""Pure runtime-policy evaluation over the V3.5-owned market calendar."""
from __future__ import annotations

from dataclasses import dataclass

from contracts.trading_calendar import (
    MarketScope,
    RunPolicy,
    SessionRequirement,
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)


@dataclass(frozen=True)
class RunDecision:
    eligible: bool
    reason: str
    calendar_status: str
    trade_date: str
    slot: str | None
    policy: RunPolicy
    eligible_markets: tuple[str, ...]
    blocked_markets: tuple[str, ...]
    market_states: dict[str, str]
    session_status: str


def _slot(value: str | None, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    text = str(value or "")
    if len(text) != 4 or not text.isdigit():
        raise ValueError("slot must use HHMM")
    hour, minute = int(text[:2]), int(text[2:])
    if hour > 23 or minute > 59:
        raise ValueError("slot must be a real time")
    return text


def _requested_markets(policy: RunPolicy, scope: MarketScope) -> tuple[str, ...]:
    if policy is RunPolicy.A_SHARE_TRADE_DAY and scope is not MarketScope.A_SHARE:
        raise ValueError("A-share policy requires A_SHARE scope")
    if policy is RunPolicy.HK_CONNECT_TRADE_DAY and scope is not MarketScope.HK_CONNECT:
        raise ValueError("HK Connect policy requires HK_CONNECT scope")
    if scope is MarketScope.A_SHARE:
        return ("a_share",)
    if scope is MarketScope.HK_CONNECT:
        return ("hk_connect",)
    return ("a_share", "hk_connect")


def _session_eligible(
    market: dict,
    state: TradingDayState,
    slot: str,
    requirement: SessionRequirement,
) -> bool:
    if state in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}:
        return False
    if requirement is SessionRequirement.DAY_ELIGIBILITY_ONLY:
        return True
    if requirement is SessionRequirement.SESSION_OPEN:
        sessions = (
            market["half_day_sessions"]
            if state is TradingDayState.HALF_TRADING_DAY_AM
            else market["full_day_sessions"]
        )
        return any(session["start"] <= slot < session["end"] for session in sessions)
    close = (
        market["half_day_close"]
        if state is TradingDayState.HALF_TRADING_DAY_AM
        else market["full_day_close"]
    )
    return close is not None and slot >= close


def evaluate_run_policy(
    policy: RunPolicy,
    trade_date: str,
    slot: str | None,
    *,
    market_scope: MarketScope,
    session_requirement: SessionRequirement,
) -> RunDecision:
    policy = RunPolicy(policy)
    market_scope = MarketScope(market_scope)
    session_requirement = SessionRequirement(session_requirement)
    normalized_slot = _slot(
        slot,
        required=session_requirement is not SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    if policy is RunPolicy.NATURAL_DAY:
        return RunDecision(
            eligible=True,
            reason="ELIGIBLE",
            calendar_status="NATURAL_DAY",
            trade_date=trade_date,
            slot=normalized_slot,
            policy=policy,
            eligible_markets=(),
            blocked_markets=(),
            market_states={},
            session_status="NATURAL_DAY",
        )
    calendar = load_market_calendar()
    requested = _requested_markets(policy, market_scope)
    resolved = resolve_market_states(calendar, trade_date)
    market_contracts = {
        "a_share": calendar.markets["a_share"],
        "hk_connect": calendar.markets["hk_connect_southbound"],
    }
    states = {market: resolved[market] for market in requested}
    eligible = tuple(
        sorted(
            market
            for market in requested
            if _session_eligible(
                market_contracts[market],
                states[market],
                normalized_slot or "0000",
                session_requirement,
            )
        )
    )
    blocked = tuple(sorted(set(requested) - set(eligible)))
    serialized_states = {market: states[market].value for market in requested}
    all_unknown = all(state is TradingDayState.UNKNOWN for state in states.values())
    all_closed = all(state is TradingDayState.NON_TRADING_DAY for state in states.values())
    if all_unknown:
        calendar_status = "UNKNOWN"
        reason = "UNKNOWN"
        session_status = "UNKNOWN"
    elif eligible and blocked:
        calendar_status = "PARTIAL_MARKET"
        reason = "PARTIAL_MARKET_ELIGIBLE"
        session_status = "PARTIAL_MARKET_ELIGIBLE"
    elif eligible:
        calendar_status = "TRADING_DAY"
        reason = "ELIGIBLE"
        session_status = {
            SessionRequirement.DAY_ELIGIBILITY_ONLY: "DAY_ELIGIBLE",
            SessionRequirement.SESSION_OPEN: "SESSION_OPEN",
            SessionRequirement.POST_CLOSE: "POST_CLOSE_ELIGIBLE",
        }[session_requirement]
    elif all_closed:
        calendar_status = "NON_TRADING_DAY"
        reason = "NON_TRADING_DAY"
        session_status = "NON_TRADING_DAY"
    else:
        calendar_status = "REQUIRED_SESSION_CLOSED"
        reason = "REQUIRED_SESSION_CLOSED"
        session_status = "REQUIRED_SESSION_CLOSED"
    return RunDecision(
        eligible=bool(eligible),
        reason=reason,
        calendar_status=calendar_status,
        trade_date=trade_date,
        slot=normalized_slot,
        policy=policy,
        eligible_markets=eligible,
        blocked_markets=blocked,
        market_states=serialized_states,
        session_status=session_status,
    )
