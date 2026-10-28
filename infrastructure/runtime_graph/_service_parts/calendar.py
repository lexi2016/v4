"""infrastructure.runtime_graph.service: calendar (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __next_market_trade_date_body(_v4_scope, /, business_date, market):
    """Return the next eligible session for one lane's market only."""
    if market not in {"a_share", "hk_connect", "hk_securities"}:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_MARKET_INVALID")
    parsed = _v4_global(_v4_scope, 'datetime').strptime(business_date, "%Y%m%d").date()
    calendar = _v4_global(_v4_scope, 'load_market_calendar')()
    for offset in _v4_global(_v4_scope, 'range')(1, 371):
        candidate = parsed + _v4_global(_v4_scope, 'timedelta')(days=offset)
        text = candidate.strftime("%Y%m%d")
        state = _v4_global(_v4_scope, 'resolve_market_states')(calendar, text)[market]
        if state not in {_v4_global(_v4_scope, 'TradingDayState').NON_TRADING_DAY, _v4_global(_v4_scope, 'TradingDayState').UNKNOWN}:
            return text
    raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_TARGET_DATE_UNAVAILABLE")


def __calendar_decision_body(_v4_scope, /, run_policy, business_date, *, evaluator):
    date = _v4_global(_v4_scope, '_valid_date')(business_date)
    if run_policy == "natural_day":
        return {"should_run": True, "status": "NATURAL_DAY", "business_date": date}
    policy_by_name = {
        "a_share_trade_day": (_v4_global(_v4_scope, 'RunPolicy').A_SHARE_TRADE_DAY, _v4_global(_v4_scope, 'MarketScope').A_SHARE),
        "hk_connect_trade_day": (_v4_global(_v4_scope, 'RunPolicy').HK_CONNECT_TRADE_DAY, _v4_global(_v4_scope, 'MarketScope').HK_CONNECT),
        "hk_securities_trade_day": (_v4_global(_v4_scope, 'RunPolicy').HK_SECURITIES_TRADE_DAY, _v4_global(_v4_scope, 'MarketScope').HK_CONNECT),
        "a_or_hk_connect_trade_day": (
            _v4_global(_v4_scope, 'RunPolicy').A_OR_HK_CONNECT_TRADE_DAY,
            _v4_global(_v4_scope, 'MarketScope').CROSS_MARKET,
        ),
        "a_or_hk_securities_trade_day": (
            _v4_global(_v4_scope, 'RunPolicy').A_OR_HK_SECURITIES_TRADE_DAY,
            _v4_global(_v4_scope, 'MarketScope').CROSS_MARKET,
        ),
    }
    selected = policy_by_name.get(run_policy)
    if selected is None:
        return {"should_run": False, "status": "CALENDAR_UNAVAILABLE"}
    policy, scope = selected
    try:
        decision = (evaluator or _v4_global(_v4_scope, 'evaluate_run_policy'))(
            policy=policy,
            trade_date=date,
            slot=None,
            market_scope=scope,
            session_requirement=_v4_global(_v4_scope, 'SessionRequirement').DAY_ELIGIBILITY_ONLY,
        )
    except _v4_global(_v4_scope, 'Exception'):
        return {"should_run": False, "status": "CALENDAR_UNAVAILABLE"}
    if not _v4_global(_v4_scope, 'getattr')(decision, "eligible", False):
        return {
            "should_run": False,
            "status": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(decision, "calendar_status", "UNKNOWN")),
        }
    return {
        "should_run": True,
        "status": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(decision, "calendar_status", "TRADING_DAY")),
        "business_date": date,
    }
