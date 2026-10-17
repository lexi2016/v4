## Source excerpt: `ops/run_scheduled_slot.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/run_scheduled_slot.py`

Original full-file SHA-256: `fcfa36a1a12200af5f60b752674806a6c8ff3caf11139371a9cf746949d98cf9`

Release/worktree group: `us_digest`

Existing generic next-trade-day and scheduled/business/target-date calculation.

### Full-source lines 81-111

```python

def next_trade_day(
    business_date: str,
    *,
    calendar: MarketCalendar | None = None,
    max_scan_days: int = 370,
) -> str:
    _date8(business_date, name="BUSINESS_DATE")
    calendar = calendar or load_market_calendar()
    current = date(int(business_date[:4]), int(business_date[4:6]), int(business_date[6:]))
    for offset in range(1, max(1, int(max_scan_days)) + 1):
        candidate = (current + timedelta(days=offset)).strftime("%Y%m%d")
        states = resolve_market_states(calendar, candidate)
        if any(
            states[key] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
            for key in ("a_share", "hk_connect")
        ):
            return candidate
    raise ValueError("NEXT_TRADE_DAY_UNAVAILABLE")


def compute_dates(*, business_date: str, slot: str, calendar: MarketCalendar | None = None) -> dict[str, str]:
    if slot not in ALL_SLOTS:
        raise ValueError("UNKNOWN_SLOT")
    business_date = _date8(business_date, name="BUSINESS_DATE")
    calendar = calendar or load_market_calendar()
    states = resolve_market_states(calendar, business_date)
    if all(state is TradingDayState.UNKNOWN for state in states.values()):
        raise ValueError("CALENDAR_UNKNOWN")
    target = next_trade_day(business_date, calendar=calendar) if slot in NEXT_TARGET_SLOTS else business_date
    return {"scheduled_date": business_date, "business_date": business_date, "target_date": target}


```
