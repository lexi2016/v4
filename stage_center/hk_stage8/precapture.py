"""Stage-8-only immutable pre-capture orchestration."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..calendar import TradingDayState, resolve_market_states
from ..contracts import HK_SNAPSHOT_SCHEDULE, SAFETY_FLAGS


_SHANGHAI = ZoneInfo("Asia/Shanghai")


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
    """Capture the exact HK D1 snapshot inside its stage-specific window."""

    if historical_backfill or config.injected_test_mode:
        return []
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        return []
    current = evaluated_at
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI)
    current = current.astimezone(_SHANGHAI)
    if current.strftime("%Y%m%d") != trade_date:
        return []

    candidates = (
        (stage_id,)
        if stage_id in HK_SNAPSHOT_SCHEDULE
        else tuple(HK_SNAPSHOT_SCHEDULE) if stage_id is None else ()
    )
    due: list[tuple[str, str, str, str]] = []
    for candidate_stage in candidates:
        capture_start_at, capture_end_at, cutoff_at = HK_SNAPSHOT_SCHEDULE[candidate_stage]
        capture_start = datetime.strptime(
            f"{trade_date} {capture_start_at}", "%Y%m%d %H:%M:%S"
        ).replace(tzinfo=_SHANGHAI)
        capture_end = datetime.strptime(
            f"{trade_date} {capture_end_at}", "%Y%m%d %H:%M:%S"
        ).replace(tzinfo=_SHANGHAI)
        if capture_start <= current <= capture_end:
            due.append((candidate_stage, capture_start_at, capture_end_at, cutoff_at))
    if not due:
        return []
    from .snapshot import record_hk_capture_event

    def unavailable(message: str) -> list[dict[str, Any]]:
        results = []
        for candidate_stage, start, end, _cutoff in due:
            attempt = record_hk_capture_event(config.raw_root, trade_date=trade_date, stage_id=candidate_stage,
                payload={"status": "CANNOT_CONFIRM", "cannot_confirm": [message], "scope_known": False,
                         "requested_rows": None, "returned_rows": 0, "evaluated_at": current.isoformat()})
            results.append({"status": "CANNOT_CONFIRM", "trade_date": trade_date, "stage_id": candidate_stage,
                "error": message, "capture_window_start": start, "capture_window_end": end,
                "native_capture_attempts": [attempt], **SAFETY_FLAGS})
        return results

    try:
        states = resolve_market_states(trade_date)
    except Exception as error:
        return unavailable(f"calendar:{type(error).__name__}")
    if states.get("hk_securities") not in {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }:
        return []
    if config.hk_d1_root is None:
        return unavailable("production HK D1 Top100 root is required for active snapshot pre-capture")
    if config.shared_data_root is None or config.python_path is None:
        return unavailable("production shared_data_root and python_path are required for active snapshot pre-capture")

    results: list[dict[str, Any]] = []
    for candidate_stage, start, end, cutoff_at in due:
        window = {
            "capture_window_start": datetime.strptime(
                f"{trade_date} {start}", "%Y%m%d %H:%M:%S"
            ).replace(tzinfo=_SHANGHAI).isoformat(),
            "capture_window_end": datetime.strptime(
                f"{trade_date} {end}", "%Y%m%d %H:%M:%S"
            ).replace(tzinfo=_SHANGHAI).isoformat(),
        }
        try:
            _source_path, codes, universe_sha = universe_loader()
            result = snapshot_preparer(
                config.raw_root,
                trade_date=trade_date,
                stage_id=candidate_stage,
                codes=codes,
                python_path=config.python_path,
                shared_root=config.shared_data_root,
                evaluated_at=current.isoformat(),
                cutoff_at=cutoff_at,
                pool_artifact_sha256=universe_sha,
            )
            results.append({
                **result,
                "trade_date": trade_date,
                "stage_id": candidate_stage,
                "hk_d1_top100_sha256": universe_sha,
                **window,
            })
        except Exception as error:
            attempt = record_hk_capture_event(config.raw_root, trade_date=trade_date, stage_id=candidate_stage,
                payload={"status": "CANNOT_CONFIRM", "cannot_confirm": [f"HK_SNAPSHOT_UNIVERSE_OR_CAPTURE_ERROR:{type(error).__name__}:{error}"],
                         "scope_known": False, "requested_rows": None, "returned_rows": 0,
                         "evaluated_at": current.isoformat(), **window})
            results.append({
                "native_capture_attempts": [attempt],
                "status": "CANNOT_CONFIRM",
                "trade_date": trade_date,
                "stage_id": candidate_stage,
                "error": str(error),
                **window,
                **SAFETY_FLAGS,
            })
    return results
