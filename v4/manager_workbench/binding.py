"""Default native assembly, reusable by existing V4 application and one-shot CLI."""
from __future__ import annotations
from contracts.trading_calendar import load_market_calendar, resolve_market_states, next_session, TradingDayState
from . import engines
from .inputs import NativeAdapters
from .executors.codex import CodexExecutor, IsolationNotVerified
from .executors.local_cli import LocalCliRunner


class CalendarAdapter:
    def __init__(self): self.calendar=load_market_calendar()
    def is_hk_session(self, date):
        state=resolve_market_states(self.calendar,date)["hk_securities"]
        if state==TradingDayState.UNKNOWN: raise ValueError("HK_CALENDAR_UNKNOWN")
        return state in (TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM)
    def next_hk_session(self,date): return next_session(self.calendar,date,market="hk_securities")
    def session_state(self,date): return resolve_market_states(self.calendar,date)["hk_securities"].value


class StageFeed:
    def __init__(self,adapters): self.adapters=adapters
    def completed_runs(self,date):
        from datetime import datetime
        from .contracts import RunContext,Phase,HK
        context=RunContext(target_date=date,phase=Phase.INTRADAY,cutoff=datetime.now(HK).isoformat(),
            trigger="SCHEDULED",rules_version=self.adapters.config.rules_version)
        value=self.adapters.stage(context)
        runs={}
        for row in value.records:
            runs[row["stage_run_id"]]={"run_id":row["stage_run_id"],"input_sha256":value.input_sha256}
        return list(runs.values())


def create_native_binding(config):
    adapters=NativeAdapters(config)
    runner=None
    isolation_gap=None
    try: runner=LocalCliRunner(config.codex_binary)
    except IsolationNotVerified as exc: isolation_gap=str(exc)
    return {"adapters":adapters,"engines":engines,"executor":CodexExecutor(config,isolation_runner=runner),
            "calendar":CalendarAdapter(),"stage_feed":StageFeed(adapters),"isolation_gap":isolation_gap}
