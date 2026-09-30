"""Runtime status API router."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from domains.task_status import build_task_status
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger


def _business_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from error
    return value


def _current_business_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def create_runtime_router(
    data_root: Path,
    ledger_root: Path | None = None,
    stage_selection_root: Path | None = None,
    current_date: str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v3/tasks", tags=["runtime"])
    ledger = ExecutionLedger(
        Path(ledger_root) if ledger_root is not None else Path(data_root).parent / "dispatcher"
    )

    @router.get("/status")
    def task_status(date: str | None = None) -> dict:
        business_date = _business_date(
            date if date is not None else (current_date or _current_business_date())
        )
        return build_task_status(
            load_workload_catalog(),
            ledger,
            business_date,
            data_root=Path(data_root),
            stage_selection_root=stage_selection_root,
        )

    return router
