"""Narrow production builder for the same-day HK Stage 8 lane."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..acquisition import AcquisitionPlan, SourceResult
from .rtdata import _collect_hk_stage8_natural


_SHANGHAI = ZoneInfo("Asia/Shanghai")


def should_use_natural_route(
    trade_date: str,
    *,
    historical_backfill: bool,
    natural_now: datetime | None = None,
) -> bool:
    """Keep current-day RT_DATA isolated from every historical replay."""

    current = natural_now or datetime.now(_SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI)
    current = current.astimezone(_SHANGHAI)
    return not historical_backfill and current.strftime("%Y%m%d") == trade_date


def production_natural_collectors(
    *,
    snapshot_root: Path | str,
    natural_now: datetime | None = None,
) -> dict[str, Callable[[AcquisitionPlan, str], SourceResult]]:
    """Bind the immutable pre-capture root without changing legacy facades."""

    return {
        "HK_CONNECT": lambda stage_plan, _market: _collect_hk_stage8_natural(
            stage_plan,
            codes=stage_plan.codes_for("HK_CONNECT"),
            snapshot_root=snapshot_root,
            natural_now=natural_now,
        )
    }
