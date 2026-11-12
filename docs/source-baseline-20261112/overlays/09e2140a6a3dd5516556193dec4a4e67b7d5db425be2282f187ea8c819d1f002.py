"""Stage-8-only immutable pre-capture orchestration."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..calendar import TradingDayState, resolve_market_states
from ..contracts import SAFETY_FLAGS


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STAGE_ID = "STAGE_1545_1555"
_PRECAPTURE_SECONDS = 5 * 60


UniverseLoader = Callable[[], tuple[Any, Sequence[str], str]]
SnapshotPreparer = Callable[..., Mapping[str, Any]]


def prepare_due_snapshot(
    config: Any,
    trade_date: str,
    evaluated_at: datetime,
    *,
    stage_id: str | None,
    historical_backfill: bool,
    universe_loader: UniverseLoader,
    snapshot_preparer: SnapshotPreparer,
) -> list[dict[str, Any]]:
    """Capture once in the 15:50-15:55 retry window, otherwise do nothing."""

    if historical_backfill or config.injected_test_mode:
        return []
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        return []
    if stage_id not in (None, _STAGE_ID):
        return []
    current = evaluated_at
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI)
    current = current.astimezone(_SHANGHAI)
    if current.strftime("%Y%m%d") != trade_date:
        return []
    try:
        states = resolve_market_states(trade_date)
    except Exception as error:
        return [{
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": _STAGE_ID,
            "error": f"calendar:{type(error).__name__}",
            **SAFETY_FLAGS,
        }]
    if states.get("hk_securities") not in {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }:
        return []
    cutoff = datetime.strptime(
        f"{trade_date} 15:55:00", "%Y%m%d %H:%M:%S"
    ).replace(tzinfo=_SHANGHAI)
    capture_start = cutoff - timedelta(seconds=_PRECAPTURE_SECONDS)
    if current < capture_start or current > cutoff:
        return []
    window = {
        "capture_window_start": capture_start.isoformat(),
        "capture_window_end": cutoff.isoformat(),
    }
    if config.hk_d1_root is None and config.hk_full_universe_root is None:
        return [{
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": _STAGE_ID,
            "error": "production HK universe root is required for Stage 8 pre-capture",
            **window,
            **SAFETY_FLAGS,
        }]
    if config.shared_data_root is None or config.python_path is None:
        return [{
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": _STAGE_ID,
            "error": "production shared_data_root and python_path are required for Stage 8 pre-capture",
            **window,
            **SAFETY_FLAGS,
        }]
    try:
        _source_path, codes, universe_sha = universe_loader()
        result = snapshot_preparer(
            config.raw_root,
            trade_date=trade_date,
            stage_id=_STAGE_ID,
            codes=codes,
            python_path=config.python_path,
            shared_root=config.shared_data_root,
            captured_at=current.isoformat(),
            cutoff_at="15:55:00",
        )
        return [{
            **result,
            "trade_date": trade_date,
            "stage_id": _STAGE_ID,
            "hk_d1_top100_sha256": universe_sha,
            **window,
        }]
    except (OSError, ValueError, ImportError) as error:
        return [{
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": _STAGE_ID,
            "error": str(error),
            **window,
            **SAFETY_FLAGS,
        }]
