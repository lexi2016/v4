"""Minute-level macOS scheduler entry for the fixed V3.5 workload slots.

The LaunchAgent invokes this entry repeatedly. It only dispatches when the
current Shanghai ``HHMM`` is one of ``ops.run_scheduled_slot.ALL_SLOTS``; the
existing execution ledger provides cross-invocation idempotency. Test/canary
overrides remain constrained to the same fixed slot allowlist.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infrastructure.scheduling.executor_registry import STAGE_BY_SLOT, WorkloadExecutionError
from infrastructure.http_transport import build_proxy_environment
from ops.daily_materialize import resolve_selector_panel
from ops.materialize_stage_acquisition_universe import (
    materialize_stage_acquisition_universe,
)
from ops.run_scheduled_slot import (
    ALL_SLOTS,
    SHANGHAI,
    ZERO_EXIT_STATUSES,
    compute_dates,
    run_scheduled_slot,
)
from contracts.trading_calendar import (
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from stage_center.consumer import StageSelectionConsumer

from infrastructure.scheduling.manager_capture_retry import capture_state

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))


# The missing native runner closure must accept this existing runtime slot at Mac integration.
ALL_SLOTS = tuple(sorted(set(ALL_SLOTS) | {"1530"}))

RESULT_SCHEMA = "v3_5.macos_scheduler_result.v1"
CATCHUP_HOURLY_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))
# Research-panel A/H lanes are fixed canonical producer slots.  They receive
# the same fairness treatment as hourly work, while the dependent 17:30
# evidence node remains in ordered post-close catch-up below.
CATCHUP_EXACT_PRIORITY_SLOTS = frozenset(CATCHUP_HOURLY_SLOTS) | frozenset({"1700", "1720"})
# Fixed non-hourly owners must be recoverable after a five-minute launchd
# heartbeat without being confused with the neighbouring hourly workload.
# Morning stage/pre-stage slots are listed explicitly because a retryable
# 09:01 receipt must not monopolize the dispatcher after launchd wakes late.
# The post-close owners remain in ``POST_CLOSE_CATCHUP_SLOTS`` so their
# dependency ordering is preserved by the dedicated branch below.
CATCHUP_FIXED_SLOTS = (
    "0830",
    "0840",
    "0901",
    "0915",
    "0925",
    "0935",
    "0940",
    "0945",
    "1030",
    "1130",
    "1730",
    "2001",
    "2115",
)
POST_CLOSE_CATCHUP_SLOTS = (
    "1500", "1555", "1605", "1610", "1700", "1710", "1720", "1730", "1800", "2030", "2040",
    "2050", "2105", "2108", "2110", "2115", "2140",
)
# The post-close nodes are recovered in dependency order before hourly research.
# 21:40 remains the final same-day materializer slot in this ordered sequence.
CRITICAL_SAME_DAY_SLOT = "2140"
CRITICAL_SAME_DAY_CATCHUP_END_HOUR = 23
DEFAULT_CATCHUP_WINDOW_MINUTES = 59
FAILED_SLOT_RETRY_BACKOFF_SECONDS = 300
MAX_FAILED_SLOT_ATTEMPTS = 3
RETRYABLE_FAILURE_CLASSES = frozenset(
    {
        "UPSTREAM_NOT_READY",
        "NETWORK",
        "EXTERNAL_SOURCE",
        "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED",
        "INTRADAY_NO_REQUEST",
    }
)
TERMINAL_FAILURE_CLASSES = frozenset(
    {"CONTRACT", "INVALID_INPUT", "SAFETY", "NON_TRADING_DAY", "NOT_DUE"}
)
SHARED_STAGE_BY_SLOT = {
    slot: stage_id for slot, stage_id in STAGE_BY_SLOT.items() if slot != "0925"
}
STAGE_INPUT_SLOTS = frozenset(STAGE_BY_SLOT)
STAGE_WORKLOAD_IDS = frozenset(
    {"stage_workbench", "fupan_close_materials", "fupan_review_start"}
)


def _fixed_slot_catchup_allowed(slot: str, moment: datetime) -> bool:
    """Apply slot-specific catch-up deadlines to non-hourly owners.

    The 09:15 HK auction capture is an opening-window input.  A late wake can
    recover it only while the capture window is still open; after 09:19:59 a
    retry of that slot would be a false representation of the live auction.
    Other fixed slots retain the caller's normal bounded catch-up window.
    """
    from ops._run_v35_macos_scheduler_parts.schedule_selection import __fixed_slot_catchup_allowed_body as _v4_impl
    return _v4_impl(globals(), slot, moment)


def _intraday_attempt_outcome(observed: list[dict[str, Any]]) -> str | None:
    """Classify an intraday failure before release/upstream retry resets.

    A retry is safe only when the child explicitly persisted that no provider
    request was made.  A successful/ALREADY_EXISTS child is already complete;
    it must not block a retry of a failed sibling workload.  Missing, malformed,
    or contradictory attempt metadata remains unknown and blocks the scheduler,
    even if an unrelated release or upstream pointer changed.
    """
    from ops._run_v35_macos_scheduler_parts.scheduler_io import __intraday_attempt_outcome_body as _v4_impl
    return _v4_impl(globals(), observed)


def _is_non_trading_day(business_date: str) -> bool:
    """Return whether both stage markets are closed for the exact date.

    Stage candidate input is a prerequisite only on an eligible market day.
    The dispatcher remains the authority for the terminal result; this guard
    only prevents a non-trading date from invoking the prerequisite first.
    """
    from ops._run_v35_macos_scheduler_parts.scheduler_io import __is_non_trading_day_body as _v4_impl
    return _v4_impl(globals(), business_date)


def current_slot(now: datetime | None = None) -> tuple[str, str]:
    moment = now or datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    else:
        moment = moment.astimezone(SHANGHAI)
    return moment.strftime("%Y%m%d"), moment.strftime("%H%M")


def _slot_blocks_retry(
    ledger_root: Path,
    business_date: str,
    slot: str,
    *,
    moment: datetime,
    retry_backoff_seconds: int = FAILED_SLOT_RETRY_BACKOFF_SECONDS,
    max_failed_attempts: int = MAX_FAILED_SLOT_ATTEMPTS,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
) -> bool:
    from ops._run_v35_macos_scheduler_parts.schedule_selection import __slot_blocks_retry_body as _v4_impl
    return _v4_impl(globals(), ledger_root, business_date, slot, moment=moment, retry_backoff_seconds=retry_backoff_seconds, max_failed_attempts=max_failed_attempts, upstream_fingerprint=upstream_fingerprint, release_id=release_id)


def resolve_due_slot(
    *,
    ledger_root: Path,
    now: datetime | None = None,
    catchup_window_minutes: int = DEFAULT_CATCHUP_WINDOW_MINUTES,
    upstream_fingerprint: str | None = None,
    release_id: str | None = None,
    capture_only: bool = False,
) -> dict[str, Any]:
    """Resolve an exact slot or the earliest bounded unclaimed catch-up.

    Only the most recent hour and only a bounded sub-hour window are eligible.
    Claims and successful receipts block duplicates. Failed hourly receipts are
    eligible for a bounded, backoff-controlled retry so a temporary network
    outage can recover after wake. Special stage and pool slots are never
    synthesized.
    """
    from ops._run_v35_macos_scheduler_parts.schedule_selection import _resolve_due_slot_body as _v4_impl
    return _v4_impl(globals(), ledger_root=ledger_root, now=now, catchup_window_minutes=catchup_window_minutes, upstream_fingerprint=upstream_fingerprint, release_id=release_id, capture_only=capture_only)


def _with_runtime_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize scheduler result metadata without inventing success evidence."""
    from ops._run_v35_macos_scheduler_parts.runtime_validation import __with_runtime_metadata_body as _v4_impl
    return _v4_impl(globals(), payload)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(_with_runtime_metadata(payload), ensure_ascii=False, sort_keys=True))


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("shared acquisition did not emit a JSON object")


def run_shared_stage_acquisition(
    *,
    business_date: str,
    slot: str,
    data_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    selector_data_root: Path,
    timeout_seconds: float,
    process_runner=subprocess.run,
    universe_materializer=materialize_stage_acquisition_universe,
) -> dict[str, Any]:
    """Acquire the fixed shared stage bundle before V3.5 materialization."""
    from ops._run_v35_macos_scheduler_parts.scheduler_io import _run_shared_stage_acquisition_body as _v4_impl
    return _v4_impl(globals(), business_date=business_date, slot=slot, data_root=data_root, shared_data_root=shared_data_root, shared_package_root=shared_package_root, selector_data_root=selector_data_root, timeout_seconds=timeout_seconds, process_runner=process_runner, universe_materializer=universe_materializer)


def ensure_stage_candidate_input(
    *,
    data_root: Path,
    business_date: str,
    universe_materializer=None,
) -> dict[str, Any]:
    """Idempotently ensure the stage consumer has a verified candidate input.

    The shared Stage Center remains the sole raw/selection producer.  This
    small prerequisite is owned by the V3.5 scheduler so consume-only mode
    cannot leave a stage slot without the exact-date acquisition universe.
    """
    from ops._run_v35_macos_scheduler_parts.scheduler_io import _ensure_stage_candidate_input_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, business_date=business_date, universe_materializer=universe_materializer)


def consume_shared_stage_selection(
    *,
    business_date: str,
    slot: str,
    selection_root: Path,
    stage_acquisition_universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the shared selection consumed by this scheduler.

    An explicit ``V35_STAGE_CENTER_SELECTION_ROOT`` changes this boundary to
    read-only consumption.  In particular, this helper deliberately does not
    invoke the bundled raw/selection producer or publish an artifact.  The
    scheduler owns only the exact-date candidate-input prerequisite and
    reports its verified evidence alongside the consume-only envelope.
    """
    from ops._run_v35_macos_scheduler_parts.scheduler_io import _consume_shared_stage_selection_body as _v4_impl
    return _v4_impl(globals(), business_date=business_date, slot=slot, selection_root=selection_root, stage_acquisition_universe=stage_acquisition_universe)


def main(argv: list[str] | None = None) -> int:
    from ops._run_v35_macos_scheduler_parts.cli_entry import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
