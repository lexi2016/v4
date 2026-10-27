"""Runtime status API router."""
from __future__ import annotations

import os
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
    configured_ledger = ledger_root or os.environ.get("V4_TASK_STATUS_LEDGER_ROOT")
    ledger = ExecutionLedger(
        Path(configured_ledger).expanduser() if configured_ledger is not None else Path(data_root).parent / "dispatcher"
    )
    us_root = os.environ.get("V4_TASK_STATUS_US_LEDGER_ROOT")
    us_ledger = ExecutionLedger(Path(us_root).expanduser()) if us_root else None
    # This reader binding is local to task status; other API data consumers keep
    # their existing data_root and provenance contracts.
    evidence_root = Path(os.environ.get("V4_TASK_STATUS_EVIDENCE_ROOT") or data_root).expanduser()

    @router.get("/status")
    def task_status(date: str | None = None) -> dict:
        business_date = _business_date(
            date if date is not None else (current_date or _current_business_date())
        )
        return build_task_status(
            load_workload_catalog(),
            ledger,
            business_date,
            data_root=evidence_root,
            us_ledger=us_ledger,
            stage_selection_root=stage_selection_root,
        )

    return router
