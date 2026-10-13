"""Default native assembly, reusable by existing V4 application and one-shot CLI."""
from __future__ import annotations
from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState
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
    def next_hk_session(self,date):
        from datetime import datetime,timedelta
        day=datetime.strptime(date,"%Y%m%d")
        for offset in range(1,32):
            candidate=(day+timedelta(days=offset)).strftime("%Y%m%d")
            if self.is_hk_session(candidate):return candidate
        raise ValueError("HK_NEXT_SESSION_UNKNOWN")
    def session_state(self,date): return resolve_market_states(self.calendar,date)["hk_securities"].value


class StageFeed:
    def __init__(self,adapters): self.adapters=adapters
    def completed_runs(self,date):
        from datetime import datetime
        from .contracts import RunContext,Phase,HK,digest
        context=RunContext(target_date=date,phase=Phase.INTRADAY,cutoff=datetime.now(HK).isoformat(),
            trigger="SCHEDULED",rules_version=self.adapters.config.rules_version)
        context=self.adapters.prepare_context(context)
        value=self.adapters.stage(context)
        groups={}
        for row in value.records:groups.setdefault(row["stage_run_id"],[]).append(row)
        evidence={ref.evidence_id:ref.model_dump(mode="json") for ref in value.evidence_refs}
        return [{"run_id":run_id,"input_sha256":digest({"run_id":run_id,"rows":rows,
                 "evidence":[evidence[eid] for eid in sorted({eid for row in rows for eid in row.get("evidence_ids",[])})]})}
                for run_id,rows in sorted(groups.items())]


def create_native_binding(config):
    adapters=NativeAdapters(config)
    runner=None
    isolation_gap=None
    try: runner=LocalCliRunner(config.codex_binary)
    except IsolationNotVerified as exc: isolation_gap=str(exc)
    return {"adapters":adapters,"engines":engines,"executor":CodexExecutor(config,isolation_runner=runner),
            "calendar":CalendarAdapter(),"stage_feed":StageFeed(adapters),"isolation_gap":isolation_gap}


def assemble_api(app, *, config, binding=None):
    """Attach the new router to the existing app and own its shutdown lifecycle."""
    from contextlib import asynccontextmanager
    from .config import WorkbenchConfig
    from .api import create_router
    from .service import create_service
    if not isinstance(config,WorkbenchConfig):config=WorkbenchConfig.model_validate(config)
    binding=binding or create_native_binding(config)
    service=create_service(config,binding['adapters'],binding['engines'],binding['executor'])
    app.state.manager_workbench_service=service
    app.state.manager_workbench_binding=binding
    app.state.manager_workbench_old_owner_excluded=True
    app.include_router(create_router(service))
    previous=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(instance):
        try:
            async with previous(instance):yield
        finally:
            service.jobs.stop()
    app.router.lifespan_context=lifespan
    return service


def api_config(*, manager_root, shared_root, stage_root, us_root, relation_root, injected=None):
    """Operator config, never browser input. No producer or capture is started."""
    from pathlib import Path
    import os
    from .config import WorkbenchConfig,load_config
    if injected is not None:
        return injected if isinstance(injected,WorkbenchConfig) else WorkbenchConfig.model_validate(injected)
    path=os.environ.get('V4_MANAGER_WORKBENCH_CONFIG_PATH')
    if path:return load_config(path)
    manager_root=Path(manager_root)
    return WorkbenchConfig(state_root=manager_root.parent/'manager_workbench',manager_root=manager_root,
        shared_root=Path(shared_root) if shared_root else None,stage_root=Path(stage_root) if stage_root else None,
        us_root=Path(us_root),relation_root=Path(relation_root),legacy_root=manager_root/'workspace_plans',
        dynamic_source_bindings=True)
