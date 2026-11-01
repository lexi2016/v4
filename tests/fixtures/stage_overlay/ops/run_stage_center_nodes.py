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
from stage_center.commit_store import (
    DEADLINE_BUDGET_NS,
    STRICT_PUBLICATION_MODE,
    StageCommitStore,
    publication_mode,
)
from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS, STAGE_BY_ID
from ops.run_stage_center_worker import execute_strict_stage


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

    states = resolve_market_states(trade_date)
    serialized = {key: state.value for key, state in states.items()}
    if any(state is TradingDayState.UNKNOWN for state in states.values()):
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "calendar": serialized,
            "error": "CALENDAR_UNKNOWN",
            **_safe_flags(),
        }
    relevant = tuple(
        states["a_share"] if market == "A_SHARE" else states["hk_securities"]
        for market in markets
    )
    if relevant and all(state is TradingDayState.NON_TRADING_DAY for state in relevant):
        return {
            "status": "SKIPPED_NON_TRADING_DAY",
            "trade_date": trade_date,
            "calendar": serialized,
            "markets": list(markets),
            **_safe_flags(),
        }
    return {
        "status": "ELIGIBLE",
        "trade_date": trade_date,
        "calendar": serialized,
        "markets": list(markets),
        **_safe_flags(),
    }


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("node config must be a JSON object")
    for key in REQUIRED_CONFIG_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError(f"explicit absolute config root required: {key}")
    for key, value in payload.items():
        if key.endswith("_root") or key.endswith("_path"):
            if value is None or not str(value).startswith("/"):
                raise ValueError(f"config path must be absolute: {key}")
    if payload.get("schema_version") not in (None, "stage_center.tick_config.v1"):
        raise ValueError("unsupported stage-center config schema")
    max_attempts = int(payload.get("node_max_attempts", DEFAULT_MAX_ATTEMPTS))
    if max_attempts < 1 or max_attempts > 3:
        raise ValueError("node_max_attempts must be between 1 and 3")
    retry_backoff = float(
        payload.get("node_retry_backoff_seconds", DEFAULT_RETRY_BACKOFF_SECONDS)
    )
    if retry_backoff < 0 or retry_backoff > 3600:
        raise ValueError("node_retry_backoff_seconds is outside the bounded range")
    max_nodes = int(payload.get("node_max_nodes_per_run", DEFAULT_MAX_NODES_PER_RUN))
    if max_nodes < 1 or max_nodes > len(NODES):
        raise ValueError("node_max_nodes_per_run is outside the bounded range")
    payload["node_max_attempts"] = max_attempts
    payload["node_retry_backoff_seconds"] = retry_backoff
    payload["node_max_nodes_per_run"] = max_nodes
    return payload


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
    path = _receipt_path(config, trade_date, stage_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("trade_date") != trade_date or value.get("stage_id") != stage_id:
        return None
    pending = _deadline.pending_receipt_marker(path)
    if pending.exists() or pending.is_symlink():
        value = dict(value)
        value["deadline_original_status"] = value.get("status")
        value.update(
            status="CANNOT_CONFIRM",
            node_outcome="TRANSIENT",
            first_failed_layer="END_TO_END_DEADLINE",
            deadline_status="CANNOT_CONFIRM",
            deadline_receipt_pending=True,
            deadline_receipt_pending_marker_path=str(pending),
        )
    return value


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
    if not receipt:
        return True
    retry_after = receipt.get("retry_after")
    if isinstance(retry_after, str) and retry_after:
        try:
            retry_time = _as_shanghai(datetime.fromisoformat(retry_after))
        except ValueError:
            retry_time = None
        if retry_time is not None:
            return evaluated_at >= retry_time
    attempted_at = receipt.get("attempted_at")
    if isinstance(attempted_at, str) and attempted_at:
        try:
            attempt_time = _as_shanghai(datetime.fromisoformat(attempted_at))
        except ValueError:
            attempt_time = None
        if attempt_time is not None:
            return evaluated_at >= attempt_time + timedelta(seconds=retry_backoff_seconds)
    return False


def _bounded_wait_until(
    target: datetime,
    now: datetime,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = MAX_CALENDAR_WAIT_SECONDS,
) -> tuple[datetime, float]:
    """Wait only for an exact cutoff inside the five-second calendar window."""

    current = _as_shanghai(now)
    cutoff = _as_shanghai(target)
    delta = (cutoff - current).total_seconds()
    # The caller may pass a smaller test window, but never enlarge the
    # coordinator's production wait budget through a config or seam value.
    wait_window = min(max(float(max_wait_seconds), 0.0), MAX_CALENDAR_WAIT_SECONDS)
    if 0 < delta <= wait_window:
        _deadline.event("CALENDAR_WAIT_START", wait_seconds=delta)
        sleep(delta)
        _deadline.checkpoint("CALENDAR_WAIT_END")
        return cutoff, delta
    return current, 0.0


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

    from stage_center.candidate_input import CandidateInputError, read_candidate_input

    try:
        candidate = read_candidate_input(
            Path(str(config["candidate_acquisition_root"])), trade_date
        )
    except (CandidateInputError, OSError, ValueError):
        return None
    return {
        "status": "PREP_ALREADY_VERIFIED",
        "trade_date": trade_date,
        "run_id": candidate.run_id,
        "current_sha256": candidate.current_sha256,
        "row_count": len(candidate.codes),
        "current_relative": candidate.current_relative,
        "source_evidence": list(candidate.source_evidence),
        "idempotent": True,
        **_safe_flags(),
    }


def materialize_candidate(
    config: Mapping[str, Any],
    trade_date: str,
    *,
    materializer: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare one exact-date canonical ``a_all_pool_rows`` current pointer."""

    gate = _calendar_gate(trade_date, markets=("A_SHARE",))
    if gate["status"] != "ELIGIBLE":
        return {**gate, "node_id": PREP_NODE_ID}
    existing = _candidate_current_is_verified(config, trade_date)
    if existing is not None:
        return {**existing, "node_id": PREP_NODE_ID}

    # The canonical materializer reads the same candidate root that owns the
    # current pointer.  It derives codes only from ``a_all_pool_rows`` and its
    # store supplies the exact-date lock, immutable run trio, and idempotent
    # current pointer.  Optional Baimao/WeChat lanes remain explicit missing
    # evidence inside the projection; they are not promoted to core input.
    if materializer is None:
        from ops.materialize_stage_acquisition_universe import (
            materialize_stage_acquisition_universe,
        )

        materializer = materialize_stage_acquisition_universe
    root = Path(str(config["candidate_acquisition_root"])).expanduser().resolve()
    try:
        output = materializer(root, trade_date)
        if not isinstance(output, Mapping):
            raise ValueError("canonical candidate materializer returned a non-object")
        if output.get("trade_date") not in (None, trade_date):
            raise ValueError("canonical candidate materializer trade_date mismatch")
        if output.get("status") not in {"READY", "NOOP_ALREADY_VERIFIED"}:
            raise ValueError(
                f"canonical candidate materializer status is {output.get('status')!r}"
            )
        result = {"node_id": PREP_NODE_ID, **dict(output), **_safe_flags()}
        result.setdefault("status", "PREP_READY")
        return result
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        return {
            "status": "CANNOT_CONFIRM",
            "node_id": PREP_NODE_ID,
            "trade_date": trade_date,
            "error": str(error),
            "blocked_layer": "A_SHARE_CANONICAL_A_ALL_POOL_ROWS",
            "core_input": "BLOCKED",
            **_safe_flags(),
        }


def _build_runner(config: Mapping[str, Any]):
    """Build production runner with fixed HK D-1 authority and no preflight."""

    from stage_center.runner import build_production_config, StageCenterRunner

    if not config.get("hk_d1_root"):
        raise ValueError("fixed HK D-1 Top100 root is required")
    kwargs = {
        key: Path(str(config[key]))
        for key in REQUIRED_CONFIG_KEYS
        if key in config and key != "candidate_source_root"
    }
    if config.get("v4_morning_news_root") is not None:
        kwargs["v4_morning_news_root"] = Path(str(config["v4_morning_news_root"]))
    # The runner's production constructor does not accept arbitrary config
    # metadata.  ``hk_full_universe_root`` is retained in the release config
    # for lineage, but with hk_d1_root present it is never selected as a
    # fallback by the Stage-8 path.
    return StageCenterRunner(build_production_config(**kwargs))


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
    if (_receipt_path(config, trade_date, str((receipt or {}).get("stage_id", ""))).parent / "dependency_rearm.json").exists():
        return None
    if not receipt or evaluated_at.tzinfo is None:
        return None
    now = _rearm_wall_now()
    if (trade_date != _as_shanghai(now).strftime("%Y%m%d")
            or trade_date != _as_shanghai(evaluated_at).strftime("%Y%m%d")
            or evaluated_at > now or receipt.get("trade_date") != trade_date):
        return None
    attempts = receipt.get("node_attempt_count")
    used = receipt.get("dependency_rearm_count", 0)
    cap = _config_int(config, "node_max_attempts", DEFAULT_MAX_ATTEMPTS)
    if (type(attempts) is not int or attempts != cap
            or type(used) is not int or used != 0
            or receipt.get("retry_exhausted") is not True
            or receipt.get("status") != "CANNOT_CONFIRM"
            or receipt.get("schema_version") != "stage_center.runner.receipt.v1"
            or receipt.get("first_failed_layer") != "EXACT_SELECTION_INPUT_BINDING"
            or receipt.get("stage_id") not in STAGE_BY_ID
            or any(receipt.get(k) is not False for k in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return None
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
    if (not isinstance(hk, Mapping) or hk.get("status") != "CANNOT_CONFIRM"
            or type(hk.get("selected_rows")) is not int or hk["selected_rows"] != 0
            or hk.get("cannot_confirm") != ["exact-date input missing: hkconnect_d1_top100.json"]
            or not config.get("hk_d1_root")):
        return None
    from stage_center.runner import _build_hk_d1_binding
    from stage_center.acquisition import StageUniverseBinding
    try:
        binding = _build_hk_d1_binding(
            Path(str(config["hk_d1_root"])),
            trade_date,
            preselection_source_root=config.get("preselection_source_root"),
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if (not isinstance(binding, StageUniverseBinding) or binding.status != "READY"
            or binding.market != "HK_CONNECT" or binding.trade_date != trade_date
            or binding.role != "HK_CONNECT_D1_TOP100"
            or len(binding.codes) != 100 or len(set(binding.codes)) != 100
            or not re.fullmatch(r"[0-9a-f]{64}", binding.sha256)
            or binding.source_run_id != "hk-d1-" + binding.sha256[:16]):
        return None
    return {
        "dependency_rearm_count": 1,
        "dependency_rearm_reason": "EXACT_HK_D1_BINDING_RECOVERED_SAME_DAY",
        "dependency_rearm_source_run_id": binding.source_run_id,
        "dependency_rearm_source_sha256": binding.sha256,
        "dependency_rearm_reserved_at": now.isoformat(),
    }


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

    if stage_id not in STAGE_BY_ID:
        raise ValueError(f"unknown stage node {stage_id!r}")
    publication_policy = publication_mode(config)
    strict_publication = publication_policy == STRICT_PUBLICATION_MODE
    if publication_policy not in {"legacy", STRICT_PUBLICATION_MODE}:
        return {
            "status": "CANNOT_CONFIRM", "stage_id": stage_id,
            "trade_date": trade_date, "blocked_layer": "STAGE_PUBLICATION_POLICY",
            "cannot_confirm": ["STAGE_PUBLICATION_POLICY_INVALID"], **_safe_flags(),
        }
    # Strict attempts take their one wall from dispatch entry. The same anchor
    # is passed to the child; neither lock acquisition nor validation restarts it.
    strict_entry_ns = time.monotonic_ns() if strict_publication else None
    strict_deadline_ns = (
        strict_entry_ns + DEADLINE_BUDGET_NS if strict_entry_ns is not None else None
    )
    gate = _calendar_gate(trade_date, markets=STAGE_BY_ID[stage_id].markets)
    if gate["status"] != "ELIGIBLE":
        return {**gate, "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode}
    runner = runner or _build_runner(config)
    max_attempts = _config_int(config, "node_max_attempts", DEFAULT_MAX_ATTEMPTS)
    retry_backoff = _config_float(
        config, "node_retry_backoff_seconds", DEFAULT_RETRY_BACKOFF_SECONDS
    )
    receipt = _read_receipt(config, trade_date, stage_id)
    attempt_count = _node_attempt_count(receipt)
    existing_status = str((receipt or {}).get("status") or "")
    if strict_publication:
        strict_store = StageCommitStore(Path(str(config["receipt_root"])))
        prior_commit = strict_store.read_verified(trade_date, stage_id)
        if prior_commit.get("status") in {"READY", "READY_EMPTY"}:
            return {
                "status": "SKIPPED_ALREADY_SETTLED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "SETTLED",
                "node_attempt_count": attempt_count,
                "write_performed": False,
                "transaction_id": prior_commit.get("transaction_id"),
                "commit_receipt_sha256": prior_commit.get("commit_receipt_sha256"),
                "commit_receipt_path": prior_commit.get("commit_receipt_path"),
                "witness_path": prior_commit.get("witness_path"),
                "terminal_monotonic_ns": prior_commit.get("terminal_monotonic_ns"),
                "elapsed_ns": prior_commit.get("elapsed_ns"),
                "deadline_verified": True,
                **_safe_flags(),
            }
        if prior_commit.get("reason") == "STRICT_COMMIT_LOCK_UNAVAILABLE":
            return {
                "status": "CANNOT_CONFIRM", "stage_id": stage_id,
                "trade_date": trade_date, "blocked_layer": "STRICT_COMMIT_LOCK",
                "cannot_confirm": ["STRICT_COMMIT_LOCK_UNAVAILABLE"], **_safe_flags(),
            }
        # A settled legacy receipt without the strict generation proof cannot
        # suppress a strict attempt or authorize any strict reader.
        if _stage_settled(receipt):
            attempt_count = 0
            existing_status = ""
    # The inner runner may replace receipt.json before it exits. This immutable
    # reservation survives that write and prevents a crash from reopening retries.
    rearm_marker = _receipt_path(config, trade_date, stage_id).parent / "dependency_rearm.json"
    if rearm_marker.exists() and not _stage_settled(receipt):
        attempt_count = max(attempt_count, max_attempts + 1)
        existing_status = "CANNOT_CONFIRM"
    if (
        _stage_settled(receipt)
        and existing_status not in TRANSIENT_STATUSES
        and not strict_publication
    ):
        return {
            "status": "SKIPPED_ALREADY_SETTLED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "node_outcome": (receipt or {}).get("node_outcome", "SETTLED"),
            "node_attempt_count": attempt_count,
            "write_performed": False,
            **_safe_flags(),
        }
    rearm = None
    if existing_status in TRANSIENT_STATUSES:
        if attempt_count >= max_attempts:
            rearm = _exact_hk_d1_dependency_rearm(config, trade_date, receipt, evaluated_at)
        if attempt_count >= max_attempts and rearm is None:
            previous = receipt or {}
            return {
                "status": "SKIPPED_RETRY_EXHAUSTED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT_EXHAUSTED",
                "node_attempt_count": attempt_count,
                "retry_exhausted": True,
                "first_failed_layer": (
                    previous.get("first_failed_layer")
                    or previous.get("blocked_layer")
                    or "STAGE_RETRY_BUDGET_EXHAUSTED"
                ),
                "error": previous.get("error"),
                "write_performed": False,
                **_safe_flags(),
            }
        if rearm is None and not _retry_is_due(
            receipt,
            _as_shanghai(evaluated_at),
            retry_backoff_seconds=retry_backoff,
        ):
            return {
                "status": "SKIPPED_RETRY_BACKOFF",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT",
                "node_attempt_count": attempt_count,
                "retry_after": (receipt or {}).get("retry_after"),
                "write_performed": False,
                **_safe_flags(),
            }

    from stage_center.runner import SlotLock, _slot_lock_path

    decision = next(
        item
        for item in runner.due_decisions(
            trade_date, _as_shanghai(evaluated_at), historical_backfill=False
        )
        if item.stage_id == stage_id
    )
    if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY"}:
        return {
            "status": decision.status,
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_safe_flags(),
        }

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _deadline.checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return {
            "status": "SKIPPED_SLOT_LOCKED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_safe_flags(),
        }
    try:
        _deadline.checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        # Recheck after acquiring the original lock; never overwrite a newer run.
        if _read_receipt(config, trade_date, stage_id) != receipt:
            return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                    "trade_date": trade_date, "write_performed": False, **_safe_flags()}
        if rearm is not None:
            rearm = _exact_hk_d1_dependency_rearm(config, trade_date, receipt, evaluated_at)
            if rearm is None:
                return {"status": "SKIPPED_DEPENDENCY_NOT_READY", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_safe_flags()}
            rearm_marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                with rearm_marker.open("x", encoding="utf-8") as stream:
                    json.dump({"schema_version": "stage_center.dependency_rearm.v1",
                               "trade_date": trade_date, "stage_id": stage_id,
                               **rearm, **_safe_flags()}, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_safe_flags()}
            runner._write_receipt({**(receipt or {}), **rearm}, trade_date, stage_id)
        # Stage-8 pre-capture is scheduled at 15:50 and, when a launch lands
        # exactly on 15:55:00, may be retried once more before the 15:55:05
        # consumer cutoff.  Never invoke it after the immutable window.
        captured = list(precaptures or ())
        attempt_count += 1
        _deadline.due(
            decision.scheduled_at,
            trade_date=trade_date,
            stage_id=stage_id,
            due_status=decision.status,
            dispatch_mode=mode,
        )
        _deadline.checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        if strict_publication:
            strict_result = execute_strict_stage(
                app_root=APP_ROOT,
                config=config,
                trade_date=trade_date,
                stage_id=stage_id,
                evaluated_at=evaluated_at,
                entry_monotonic_ns=int(strict_entry_ns),
                deadline_monotonic_ns=int(strict_deadline_ns),
                supervisor_metadata={
                    "node_attempt_count": attempt_count,
                    "dispatch_mode": mode,
                    "due_status": decision.status,
                },
            )
            strict_result.update(
                {
                    "node_id": stage_id,
                    "dispatch_mode": mode,
                    "node_attempt_count": attempt_count,
                    "pre_captures": captured or strict_result.get("pre_captures", []),
                }
            )
            strict_result.update(
                {key: value for key, value in (receipt or {}).items()
                 if key.startswith("dependency_rearm_")}
            )
            if rearm is not None:
                strict_result.update(rearm)
            if strict_result.get("status") not in {"READY", "READY_EMPTY"}:
                strict_result["status"] = "CANNOT_CONFIRM"
                strict_result["node_outcome"] = "TRANSIENT"
                strict_result["retry_exhausted"] = attempt_count >= max_attempts
                if not strict_result["retry_exhausted"]:
                    strict_result["retry_after"] = (
                        _as_shanghai(evaluated_at) + timedelta(seconds=retry_backoff)
                    ).isoformat()
                failed_receipt = runner._write_receipt(
                    {
                        **strict_result,
                        "first_failed_layer": strict_result.get("blocked_layer") or "STRICT_STAGE_EXECUTION",
                        "write_performed": False,
                        **_safe_flags(),
                    },
                    trade_date,
                    stage_id,
                )
                return {**failed_receipt, **strict_result, "status": "CANNOT_CONFIRM"}
            strict_result["node_outcome"] = "SETTLED"
            strict_result["retry_exhausted"] = False
            strict_result.pop("retry_after", None)
            return strict_result
        result = dict(runner._run_one(decision))
        _deadline.event("BUSINESS_RETURN", status=result.get("status"))
        result.update(
            {
                "node_id": stage_id,
                "dispatch_mode": mode,
                "node_attempt_count": attempt_count,
                "pre_captures": captured,
            }
        )
        # Preserve consumed re-arm metadata across both success and failure.
        result.update({k: v for k, v in (receipt or {}).items()
                       if k.startswith("dependency_rearm_")})
        if rearm is not None:
            result.update(rearm)
        status = str(result.get("status") or "CANNOT_CONFIRM")
        if status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            # A partial status without a committed write is not a valid
            # settled partial.  Reclassify it into the bounded retry lane.
            result["status"] = status = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        outcome = _node_outcome(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = bool(
            outcome == "TRANSIENT" and attempt_count >= max_attempts
        )
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _as_shanghai(evaluated_at)
                + timedelta(seconds=retry_backoff)
            ).isoformat()
        else:
            result.pop("retry_after", None)
        # _record_dispatch_metadata is the existing receipt writer and keeps
        # the base runner's schema and safety flags.  The final write adds the
        # node cap metadata atomically through the same per-stage lock.
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _deadline.complete_receipt(
            runner._receipt_path(trade_date, stage_id),
            persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        return persisted
    finally:
        lock.release()


def _node_candidates(
    trade_date: str,
    evaluated_at: datetime,
    *,
    explicit_node: str | None,
    config: Mapping[str, Any],
) -> tuple[Node, ...]:
    current = _as_shanghai(evaluated_at)
    if explicit_node is not None:
        node = NODE_BY_ID.get(explicit_node)
        if node is None:
            raise ValueError(f"unknown node {explicit_node!r}")
        return (node,) if _node_due(node, trade_date, current) else ()
    due = [node for node in NODES if _node_due(node, trade_date, current)]
    strict_publication = publication_mode(config) != "legacy"
    due = [
        node
        for node in due
        if node.is_prep
        or strict_publication
        or not _stage_settled(_read_receipt(config, trade_date, node.stage_id or ""))
    ]
    return tuple(due[: _config_int(config, "node_max_nodes_per_run", DEFAULT_MAX_NODES_PER_RUN)])


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

    evaluated = _as_shanghai(evaluated_at)
    if not _valid_trade_date(trade_date):
        return {
            "status": "CANNOT_CONFIRM",
            "error": "TRADE_DATE_INVALID",
            "trade_date": trade_date,
            "node_schedule_version": NODE_SCHEDULE_VERSION,
            **_safe_flags(),
        }
    nodes = _node_candidates(
        trade_date, evaluated, explicit_node=explicit_node, config=config
    )
    if not nodes:
        status = "TOO_EARLY" if explicit_node else "NO_NODE_DUE"
        return {
            "status": status,
            "trade_date": trade_date,
            "evaluated_at": evaluated.isoformat(),
            "node_id": explicit_node,
            "nodes": [],
            "node_schedule_version": NODE_SCHEDULE_VERSION,
            **_safe_flags(),
        }

    results: list[dict[str, Any]] = []
    prepared_snapshots: dict[str, list[Mapping[str, Any]]] = {}
    for node in nodes:
        if node.is_prep:
            gate = _calendar_gate(trade_date, markets=("A_SHARE",))
            if node.node_id == PREP_NODE_ID:
                if gate["status"] != "ELIGIBLE":
                    result = {**gate, "node_id": node.node_id, "dispatch_mode": _node_mode(node, trade_date, evaluated)}
                else:
                    result = materialize_candidate(config, trade_date, materializer=materializer)
                    result["dispatch_mode"] = _node_mode(node, trade_date, evaluated)
                    result["node_id"] = node.node_id
            else:
                gate = _calendar_gate(trade_date, markets=("HK_CONNECT",))
                if gate["status"] != "ELIGIBLE":
                    result = {**gate, "node_id": node.node_id, "stage_id": "STAGE_1545_1555", "dispatch_mode": _node_mode(node, trade_date, evaluated)}
                else:
                    runner = runner or _build_runner(config)
                    captures = list(
                        runner._prepare_hk_active_snapshots(
                            trade_date,
                            evaluated,
                            stage_id="STAGE_1545_1555",
                        )
                    )
                    prepared_snapshots["STAGE_1545_1555"] = captures
                    capture_statuses = {str(item.get("status") or "") for item in captures}
                    if "CANNOT_CONFIRM" in capture_statuses:
                        capture_status = "CANNOT_CONFIRM"
                    elif captures and capture_statuses <= {"READY", "NOOP_ALREADY_VERIFIED"}:
                        capture_status = "PRECAPTURE_COMPLETE"
                    else:
                        capture_status = "PRECAPTURE_NOT_DUE"
                    result = {
                        "status": capture_status,
                        "node_id": node.node_id,
                        "stage_id": "STAGE_1545_1555",
                        "trade_date": trade_date,
                        "dispatch_mode": _node_mode(node, trade_date, evaluated),
                        "pre_captures": captures,
                        **_safe_flags(),
                    }
            results.append(result)
            continue

        stage = STAGE_BY_ID[node.stage_id or ""]
        mode = _node_mode(node, trade_date, evaluated)
        target = datetime.strptime(
            f"{trade_date} {stage.cutoff}", "%Y%m%d %H:%M:%S"
        ).replace(tzinfo=SHANGHAI)
        after_wait, waited = _bounded_wait_until(target, evaluated, sleep=sleep)
        if waited:
            evaluated = after_wait
            mode = "NATURAL"
        stage_precaptures = prepared_snapshots.get(node.stage_id or "")
        if (
            node.stage_id == "STAGE_1545_1555"
            and stage_precaptures is None
            and evaluated <= target.replace(second=0)
        ):
            if publication_mode(config) == "legacy":
                runner = runner or _build_runner(config)
                stage_precaptures = list(
                    runner._prepare_hk_active_snapshots(
                        trade_date,
                        evaluated,
                        stage_id=node.stage_id,
                    )
                )
                prepared_snapshots[node.stage_id] = stage_precaptures
        result = _dispatch_stage(
            config,
            trade_date,
            node.stage_id or node.node_id,
            evaluated,
            mode=mode,
            runner=runner,
            precaptures=stage_precaptures,
        )
        results.append(result)

    statuses = {str(item.get("status") or "") for item in results}
    exhausted = [item for item in results if item.get("status") == "SKIPPED_RETRY_EXHAUSTED"]
    if exhausted:
        overall = "RETRY_EXHAUSTED"
    elif statuses <= {"SKIPPED_ALREADY_SETTLED", "SKIPPED_RETRY_BACKOFF", "SKIPPED_SLOT_LOCKED"}:
        overall = "RECOVERY_COMPLETE" if any(item.get("dispatch_mode") == "RECOVERY" for item in results) else "NODES_SKIPPED"
    elif statuses & TRANSIENT_STATUSES:
        overall = "CANNOT_CONFIRM"
    else:
        overall = "NODES_COMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "trade_date": trade_date,
        "evaluated_at": evaluated.isoformat(),
        "node_schedule_version": NODE_SCHEDULE_VERSION,
        "nodes": results,
        "node_count": len(results),
        "recovery": any(item.get("dispatch_mode") == "RECOVERY" for item in results),
        "exhausted_stages": [
            {
                "stage_id": item.get("stage_id"),
                "node_attempt_count": item.get("node_attempt_count"),
                "first_failed_layer": item.get("first_failed_layer"),
                "error": item.get("error"),
            }
            for item in exhausted
        ],
        "first_failed_layer": next(
            (item.get("first_failed_layer") for item in exhausted if item.get("first_failed_layer")),
            None,
        ),
        **_safe_flags(),
    }


def _compact(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _compact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if key in {"rows", "files"}:
            return {"count": len(value), "truncated": True}
        return [_compact(item) for item in value[:16]] + ([{"truncated": True, "count": len(value)}] if len(value) > 16 else [])
    if isinstance(value, str) and len(value) > 512:
        return value[:509] + "..."
    return value


def _print_json(payload: Mapping[str, Any]) -> None:
    compact = _compact(payload)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) > 4095:
        # Keep failures ahead of successful PREP nodes. Full diagnostics remain
        # in the dated receipt; stdout has a strict launchd envelope budget.
        node_rows = list(payload.get("nodes") or [])
        node_rows.sort(key=lambda node: not (node.get("error") or any(
            lane.get("first_error") or lane.get("cannot_confirm")
            for lane in (node.get("markets") or {}).values())))
        compact = {
            "schema_version": SCHEMA_VERSION,
            "status": str(payload.get("status") or "CANNOT_CONFIRM"),
            "trade_date": payload.get("trade_date"),
            "node_schedule_version": NODE_SCHEDULE_VERSION,
            "output_truncated": True,
            "first_failed_layer": payload.get("first_failed_layer"),
            "nodes": [{"stage_id": node.get("stage_id"), "status": node.get("status"),
                       "error": str(node.get("error") or "")[:100],
                       "first_failed_layer": node.get("first_failed_layer"),
                       "markets": {market: {"status": lane.get("status", lane.get("selection_status")),
                                    "first_error": str(lane.get("first_error") or next(iter(lane.get("cannot_confirm") or []), ""))[:120]}
                                   for market, lane in (node.get("markets") or {}).items()
                                   if market in {"A_SHARE", "HK_CONNECT"}}}
                      for node in node_rows[:2]],
            **_safe_flags(),
        }
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    print(encoded.decode("utf-8"))


def _exit_code(status: str) -> int:
    return 0 if status in {
        "CHECK_OK",
        "NODES_COMPLETE",
        "NODES_SKIPPED",
        "RECOVERY_COMPLETE",
        "NO_NODE_DUE",
        "TOO_EARLY",
        "SKIPPED_NON_TRADING_DAY",
        "DEADLINE_ONLY_NOT_DUE",
        "DEADLINE_CHAIN_READY",
        "SKIPPED_RETRY_BACKOFF",
        "SKIPPED_RETRY_EXHAUSTED",
        "SKIPPED_ALREADY_SETTLED",
        "SKIPPED_SLOT_LOCKED",
        "SKIPPED_RECEIPT_CHANGED",
        "SKIPPED_DEPENDENCY_NOT_READY",
    } else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded stage-center calendar node")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--node", choices=NODE_IDS)
    parser.add_argument("--trade-date")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--deadline-only", action="store_true")
    parser.add_argument("--historical-backfill", action="store_true")
    args = parser.parse_args(argv)
    trace = None
    try:
        if os.environ.get("V4_STAGE_CANARY_ROOT"):
            _deadline.install_offline_canary_guard(Path(os.environ["V4_STAGE_CANARY_ROOT"]))
        trace = _deadline.install(
            _ENTRY_MONOTONIC_NS if argv is None and __name__ == "__main__" else time.monotonic_ns(),
            _ENTRY_WALL_NS if argv is None and __name__ == "__main__" else time.time_ns(),
        )
        _deadline.checkpoint("IMPORTS_ARGUMENTS_DONE")
        config = _load_config(args.config)
        _deadline.checkpoint("CONFIG_LOADED")
        now = datetime.now(SHANGHAI)
        evaluated = (
            _as_shanghai(datetime.fromisoformat(args.evaluated_at))
            if args.evaluated_at
            else now
        )
        trade_date = args.trade_date or evaluated.strftime("%Y%m%d")
        if args.check:
            result = {
                "schema_version": SCHEMA_VERSION,
                "status": "CHECK_OK",
                "config": str(args.config.resolve()),
                "node_ids": list(NODE_IDS),
                "calendar_intervals": [
                    {"hour": node.hour, "minute": node.minute, "node_id": node.node_id}
                    for node in NODES
                ],
                "max_attempts": config["node_max_attempts"],
                **_safe_flags(),
            }
        elif args.deadline_only:
            from ops.run_stage_center_tick import deadline_chain_check, _deadline_stage_for

            stage_id = _deadline_stage_for(evaluated.hour, evaluated.minute)
            if stage_id is None:
                result = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "DEADLINE_ONLY_NOT_DUE",
                    "trade_date": trade_date,
                    "stage_id": None,
                    "provider_invocations": 0,
                    "business_writes": 0,
                    **_safe_flags(),
                }
            else:
                calendar_gate = _calendar_gate(
                    trade_date, markets=STAGE_BY_ID[stage_id].markets
                )
                if calendar_gate["status"] != "ELIGIBLE":
                    result = {
                        **calendar_gate,
                        "schema_version": SCHEMA_VERSION,
                        "stage_id": stage_id,
                        "provider_invocations": 0,
                        "business_writes": 0,
                    }
                else:
                    result = deadline_chain_check(
                        Path(str(config["raw_root"])),
                        Path(str(config["selection_root"])),
                        trade_date,
                        stage_id,
                    )
        elif not args.historical_backfill and trade_date != now.strftime("%Y%m%d"):
            result = {
                "schema_version": SCHEMA_VERSION,
                "status": "CANNOT_CONFIRM",
                "trade_date": trade_date,
                "error": "HISTORICAL_BACKFILL_FLAG_REQUIRED",
                **_safe_flags(),
            }
        else:
            result = run_nodes(
                config,
                trade_date=trade_date,
                evaluated_at=evaluated,
                explicit_node=args.node,
            )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "CANNOT_CONFIRM",
            "error": str(error),
            **_safe_flags(),
        }
    timing = _deadline.summary()
    if timing is not None:
        result["end_to_end_deadline"] = timing
    _print_json(result)
    if trace is not None:
        trace.close()
        _deadline.set_current(None)
    return _exit_code(str(result.get("status") or "CANNOT_CONFIRM"))


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
