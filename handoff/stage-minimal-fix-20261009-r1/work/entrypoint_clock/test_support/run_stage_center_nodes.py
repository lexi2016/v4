"""Calendar-driven stage-center nodes with bounded, serial recovery.

This entry point is deliberately smaller than the legacy heartbeat wrapper.  A
launchd job invokes it at the frozen calendar minutes below.  The process then
dispatches one named stage at a time, after the exact-date A-share candidate
has been prepared.  It never calls the all-due ``StageCenterRunner.tick`` path
and never performs the HK full-market preflight.

The module owns scheduling policy only.  Candidate materialization, the exact
HK D-1 Top100 reader, per-stage locking, immutable raw/selection publication,
and the research-only safety flags remain in the packaged stage-center
components.
"""
from __future__ import annotations

import time as _entry_clock

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))


_ENTRY_MONOTONIC_NS = _entry_clock.monotonic_ns()
_ENTRY_WALL_NS = _entry_clock.time_ns()

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from stage_center import end_to_end_deadline as _deadline
from stage_center.calendar import TradingDayState, resolve_market_states
from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS, STAGE_BY_ID


SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "stage_center.node_schedule.v1"
NODE_SCHEDULE_VERSION = "20260907-node-schedule-v1"
MAX_CALENDAR_WAIT_SECONDS = 5.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 60.0
DEFAULT_MAX_NODES_PER_RUN = 10

# One launchd job owns these minutes.  The 09:15 node is preparation only;
# every other node maps to exactly one stage-scoped runner call.
PREP_NODE_ID = "PREP_0915"
PRECAPTURE_NODE_ID = "PRECAPTURE_1550"
PREP_NODE_IDS = frozenset({PREP_NODE_ID, PRECAPTURE_NODE_ID})
STAGE_NODE_IDS = tuple(stage.stage_id for stage in EIGHT_STAGES)
NODE_MINUTES: dict[str, tuple[int, int]] = {
    PREP_NODE_ID: (9, 15),
    "STAGE_0925": (9, 25),
    "STAGE_0930_0935": (9, 35),
    "STAGE_0935_0940": (9, 40),
    "STAGE_0940_0945": (9, 45),
    "STAGE_0945_1030": (10, 30),
    "STAGE_1300_1315": (13, 15),
    "STAGE_1445_1500": (15, 0),
    PRECAPTURE_NODE_ID: (15, 50),
    "STAGE_1545_1555": (15, 55),
}
STAGE_NODE_BY_CLOCK = {
    value: key for key, value in NODE_MINUTES.items() if key != PREP_NODE_ID
}
NODE_IDS = (PREP_NODE_ID, *STAGE_NODE_IDS[:-1], PRECAPTURE_NODE_ID, STAGE_NODE_IDS[-1])

TRANSIENT_STATUSES = frozenset({"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"})
SETTLED_STATUSES = frozenset({"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"})
REQUIRED_CONFIG_KEYS = (
    "candidate_acquisition_root",
    "raw_root",
    "selection_root",
    "receipt_root",
    "v4_research_data_root",
    "hk_d1_root",
    "preselection_source_root",
    "hk_second_filter_root",
    "hk_full_universe_root",
    "a_auction_root",
    "hk_auction_root",
    "hk_stage_replay_root",
    "a_research_panel_receipt_root",
    "shared_data_root",
    "python_path",
)


@dataclass(frozen=True)
class Node:
    node_id: str
    hour: int
    minute: int
    stage_id: str | None = None

    @property
    def is_prep(self) -> bool:
        return self.node_id in PREP_NODE_IDS

    def scheduled_at(self, trade_date: str) -> datetime:
        return datetime.strptime(
            f"{trade_date} {self.hour:02d}:{self.minute:02d}:00",
            "%Y%m%d %H:%M:%S",
        ).replace(tzinfo=SHANGHAI)


NODES = tuple(
    Node(
        node_id=node_id,
        hour=hour,
        minute=minute,
        stage_id=(
            "STAGE_1545_1555"
            if node_id == PRECAPTURE_NODE_ID
            else None
            if node_id in PREP_NODE_IDS
            else node_id
        ),
    )
    for node_id, (hour, minute) in NODE_MINUTES.items()
)
NODE_BY_ID = {node.node_id: node for node in NODES}


def _safe_flags() -> dict[str, bool]:
    return dict(SAFETY_FLAGS)


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _valid_trade_date(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _calendar_gate(trade_date: str, *, markets: Sequence[str]) -> dict[str, Any]:
    """Resolve the pure calendar contract before any materializer/network call."""
    from ops._run_stage_center_nodes_parts.node_entry import __calendar_gate_body as _v4_impl
    return _v4_impl(globals(), trade_date, markets=markets)


def _load_config(path: Path) -> dict[str, Any]:
    from ops._run_stage_center_nodes_parts.runtime_arguments import __load_config_body as _v4_impl
    return _v4_impl(globals(), path)


def _config_int(config: Mapping[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer") from error


def _config_float(config: Mapping[str, Any], key: str, default: float) -> float:
    value = config.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be numeric") from error


def _receipt_path(config: Mapping[str, Any], trade_date: str, stage_id: str) -> Path:
    return (
        Path(str(config["receipt_root"])).expanduser().resolve()
        / trade_date
        / stage_id
        / "receipt.json"
    )


def _read_receipt(
    config: Mapping[str, Any], trade_date: str, stage_id: str
) -> dict[str, Any] | None:
    from ops._run_stage_center_nodes_parts.node_entry import __read_receipt_body as _v4_impl
    return _v4_impl(globals(), config, trade_date, stage_id)


def _node_attempt_count(receipt: Mapping[str, Any] | None) -> int:
    if not receipt:
        return 0
    value = receipt.get("node_attempt_count", 0)
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, count)


def _node_outcome(status: str, result: Mapping[str, Any]) -> str:
    if status == "PARTIAL_WITH_ROWS":
        return "SETTLED_PARTIAL" if result.get("write_performed") is not False else "TRANSIENT"
    if status in SETTLED_STATUSES:
        return "SETTLED"
    if status in TRANSIENT_STATUSES:
        return "TRANSIENT"
    return "BLOCKED"


def _retry_is_due(
    receipt: Mapping[str, Any] | None,
    evaluated_at: datetime,
    *,
    retry_backoff_seconds: float,
) -> bool:
    from ops._run_stage_center_nodes_parts.node_entry import __retry_is_due_body as _v4_impl
    return _v4_impl(globals(), receipt, evaluated_at, retry_backoff_seconds=retry_backoff_seconds)


def _bounded_wait_until(
    target: datetime,
    now: datetime,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = MAX_CALENDAR_WAIT_SECONDS,
) -> tuple[datetime, float]:
    """Wait only for an exact cutoff inside the five-second calendar window."""
    from ops._run_stage_center_nodes_parts.deadline_supervision import __bounded_wait_until_body as _v4_impl
    return _v4_impl(globals(), target, now, sleep=sleep, max_wait_seconds=max_wait_seconds)


def _node_mode(node: Node, trade_date: str, evaluated_at: datetime) -> str:
    scheduled = node.scheduled_at(trade_date)
    current = _as_shanghai(evaluated_at)
    if current.date() == scheduled.date() and current >= scheduled:
        lag = (current - scheduled).total_seconds()
        if 0 <= lag <= MAX_CALENDAR_WAIT_SECONDS:
            return "NATURAL"
    return "RECOVERY"


def _node_due(node: Node, trade_date: str, evaluated_at: datetime) -> bool:
    current = _as_shanghai(evaluated_at)
    scheduled = node.scheduled_at(trade_date)
    if node.node_id == PRECAPTURE_NODE_ID:
        # The immutable Stage-8 active snapshot is only a 15:50-15:55
        # acquisition window.  Do not turn a late 15:55:01 launch into a
        # post-cutoff provider call.
        return scheduled <= current <= scheduled + timedelta(minutes=5)
    return current >= scheduled


def _stage_settled(receipt: Mapping[str, Any] | None) -> bool:
    if not receipt:
        return False
    status = str(receipt.get("status") or "")
    outcome = str(receipt.get("node_outcome") or "")
    return (
        outcome in {"SETTLED", "SETTLED_PARTIAL"}
        or status in SETTLED_STATUSES
    )


def _candidate_current_is_verified(config: Mapping[str, Any], trade_date: str) -> dict[str, Any] | None:
    """Read the exact current pointer without creating a second producer."""
    from ops._run_stage_center_nodes_parts.node_entry import __candidate_current_is_verified_body as _v4_impl
    return _v4_impl(globals(), config, trade_date)


def materialize_candidate(
    config: Mapping[str, Any],
    trade_date: str,
    *,
    materializer: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare one exact-date canonical ``a_all_pool_rows`` current pointer."""
    from ops._run_stage_center_nodes_parts.node_entry import _materialize_candidate_body as _v4_impl
    return _v4_impl(globals(), config, trade_date, materializer=materializer)


def _build_runner(config: Mapping[str, Any]):
    """Build production runner with fixed HK D-1 authority and no preflight."""
    from ops._run_stage_center_nodes_parts.node_entry import __build_runner_body as _v4_impl
    return _v4_impl(globals(), config)


def _rearm_wall_now() -> datetime:
    return datetime.now(SHANGHAI)


def _exact_hk_d1_dependency_rearm(
    config: Mapping[str, Any], trade_date: str,
    receipt: Mapping[str, Any] | None, evaluated_at: datetime,
) -> dict[str, Any] | None:
    """One extra attempt only after the existing exact-D1 validator succeeds.

    Never a historical replay permission. Persist the returned reservation under
    the existing slot lock BEFORE running, so a crash consumes this one chance.
    """
    from ops._run_stage_center_nodes_parts.node_entry import __exact_hk_d1_dependency_rearm_body as _v4_impl
    return _v4_impl(globals(), config, trade_date, receipt, evaluated_at)


def _dispatch_stage(
    config: Mapping[str, Any],
    trade_date: str,
    stage_id: str,
    evaluated_at: datetime,
    *,
    mode: str,
    runner: Any | None = None,
    precaptures: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run exactly one stage under the runner's existing per-stage lock."""
    from ops._run_stage_center_nodes_parts.stage_dispatch import __dispatch_stage_body as _v4_impl
    return _v4_impl(globals(), config, trade_date, stage_id, evaluated_at, mode=mode, runner=runner, precaptures=precaptures)


def _node_candidates(
    trade_date: str,
    evaluated_at: datetime,
    *,
    explicit_node: str | None,
    config: Mapping[str, Any],
) -> tuple[Node, ...]:
    from ops._run_stage_center_nodes_parts.node_entry import __node_candidates_body as _v4_impl
    return _v4_impl(globals(), trade_date, evaluated_at, explicit_node=explicit_node, config=config)


def run_nodes(
    config: Mapping[str, Any],
    *,
    trade_date: str,
    evaluated_at: datetime,
    explicit_node: str | None = None,
    materializer: Callable[..., Mapping[str, Any]] | None = None,
    runner: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run prep and/or serial due nodes, returning a bounded typed receipt."""
    from ops._run_stage_center_nodes_parts.node_entry import _run_nodes_body as _v4_impl
    return _v4_impl(globals(), config, trade_date=trade_date, evaluated_at=evaluated_at, explicit_node=explicit_node, materializer=materializer, runner=runner, sleep=sleep)


def _compact(value: Any, *, key: str | None = None) -> Any:
    from ops._run_stage_center_nodes_parts.node_entry import __compact_body as _v4_impl
    return _v4_impl(globals(), value, key=key)


def _print_json(payload: Mapping[str, Any]) -> None:
    from ops._run_stage_center_nodes_parts.node_entry import __print_json_body as _v4_impl
    return _v4_impl(globals(), payload)


def _exit_code(status: str) -> int:
    from ops._run_stage_center_nodes_parts.node_entry import __exit_code_body as _v4_impl
    return _v4_impl(globals(), status)


def main(argv: list[str] | None = None) -> int:
    from ops._run_stage_center_nodes_parts.node_entry import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "MAX_CALENDAR_WAIT_SECONDS",
    "NODE_IDS",
    "NODE_MINUTES",
    "NODES",
    "PRECAPTURE_NODE_ID",
    "PREP_NODE_ID",
    "SCHEMA_VERSION",
    "STAGE_NODE_IDS",
    "_bounded_wait_until",
    "_calendar_gate",
    "_load_config",
    "_node_mode",
    "_node_candidates",
    "_stage_settled",
    "main",
    "materialize_candidate",
    "run_nodes",
]
