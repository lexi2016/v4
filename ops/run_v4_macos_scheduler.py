"""Minute-level macOS scheduler entry for the fixed V4 workload slots.

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
from types import FunctionType
from typing import Any

from infrastructure.scheduling.executor_registry import STAGE_BY_SLOT
from infrastructure.http_transport import apply_proxy_environment, build_proxy_environment
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
from stage_center.candidate_input import CandidateInputError, read_candidate_input
from stage_center.consumer import StageSelectionConsumer

RESULT_SCHEMA = "v3_5.macos_scheduler_result.v1"
SHARED_STAGE_BY_SLOT = {
    slot: stage_id for slot, stage_id in STAGE_BY_SLOT.items() if slot != "0925"
}
STAGE_INPUT_SLOTS = frozenset(STAGE_BY_SLOT)
# 09:15 owns the HK opening-auction workload, not a Stage Center stage.  It
# may nevertheless warm the exact-date A aggregate so the first real stage
# does not race candidate publication at pre-open.
STAGE_CANDIDATE_PREWARM_SLOTS = frozenset({"0915"})

try:
    from . import run_v4_macos_scheduler_due as _due
except ImportError:  # pragma: no cover - exercised by direct script imports
    import run_v4_macos_scheduler_due as _due

_DUE_CONSTANT_NAMES = (
    "CATCHUP_HOURLY_SLOTS",
    "CATCHUP_EXACT_PRIORITY_SLOTS",
    "CATCHUP_FIXED_SLOTS",
    "POST_CLOSE_CATCHUP_SLOTS",
    "CRITICAL_SAME_DAY_SLOT",
    "CRITICAL_SAME_DAY_CATCHUP_END_HOUR",
    "DEFAULT_CATCHUP_WINDOW_MINUTES",
    "FAILED_SLOT_RETRY_BACKOFF_SECONDS",
    "MAX_FAILED_SLOT_ATTEMPTS",
    "RETRYABLE_FAILURE_CLASSES",
    "TERMINAL_FAILURE_CLASSES",
)
_DUE_FUNCTION_NAMES = (
    "_fixed_slot_catchup_allowed",
    "_slot_retry_deadline",
    "current_slot",
    "_slot_blocks_retry",
    "_slot_has_retryable_failure",
    "resolve_due_slot",
)


def _rebind_due_function(source: FunctionType) -> FunctionType:
    rebound = FunctionType(
        source.__code__,
        globals(),
        source.__name__,
        source.__defaults__,
        source.__closure__,
    )
    rebound.__kwdefaults__ = source.__kwdefaults__
    rebound.__annotations__ = source.__annotations__
    rebound.__doc__ = source.__doc__
    rebound.__dict__.update(source.__dict__)
    rebound.__qualname__ = source.__qualname__
    rebound.__module__ = __name__
    return rebound


for _due_constant_name in _DUE_CONSTANT_NAMES:
    globals()[_due_constant_name] = getattr(_due, _due_constant_name)
for _due_function_name in _DUE_FUNCTION_NAMES:
    globals()[_due_function_name] = _rebind_due_function(
        getattr(_due, _due_function_name)
    )


del _due_constant_name, _due_function_name
del _DUE_CONSTANT_NAMES, _DUE_FUNCTION_NAMES, _rebind_due_function, _due
del FunctionType


def _is_non_trading_day(business_date: str) -> bool:
    """Return whether both stage markets are closed for the exact date.

    Stage candidate input is a prerequisite only on an eligible market day.
    The dispatcher remains the authority for the terminal result; this guard
    only prevents a non-trading date from invoking the prerequisite first.
    """

    states = resolve_market_states(load_market_calendar(), business_date)
    return all(
        states[key] is TradingDayState.NON_TRADING_DAY
        for key in ("a_share", "hk_connect")
    )


def _with_runtime_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize scheduler result metadata without inventing success evidence."""

    result = dict(payload)
    for field in ("failure_class", "retry_after"):
        value = result.get(field)
        result[field] = value if value not in (None, "") else None
    for field, env_name in (
        ("release_id", "V4_RELEASE_ID"),
        ("upstream_fingerprint", "V4_UPSTREAM_FINGERPRINT"),
    ):
        value = result.get(field) or os.environ.get(env_name)
        result[field] = value if value not in (None, "") else None
    try:
        result["attempt"] = max(0, int(result.get("attempt") or 0))
    except (TypeError, ValueError):
        result["attempt"] = 0
    return result


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
    """Acquire the fixed shared stage bundle before V4 materialization."""
    stage_id = SHARED_STAGE_BY_SLOT.get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT"}
    universe = ensure_stage_candidate_input(
        data_root=data_root,
        business_date=business_date,
        universe_materializer=universe_materializer,
    )
    bundled_stage_root = (
        Path(__file__).resolve().parents[1] / "upstreams" / "v3_shared_data"
    )
    if not (bundled_stage_root / "scripts" / "run_scheduled_stage_bundle.py").is_file():
        raise RuntimeError(
            "BUNDLED_STAGE_ACQUISITION_MISSING:" + str(bundled_stage_root)
        )
    panel = resolve_selector_panel(selector_data_root, business_date)
    pointer = selector_data_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    env = build_proxy_environment(os.environ.copy())
    env.update(
        {
            "V3_SHARED_DATA_STORE_ROOT": str(shared_data_root),
            "V4_DATA_ROOT": str(data_root),
            "V3_SHARED_SELECTOR_READY_PANEL_POINTER": str(pointer),
            "V3_SHARED_SELECTOR_READY_PANEL": str(panel),
            "V3_SHARED_FUTU_PYTHON": sys.executable,
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    completed = process_runner(
        [
            sys.executable,
            "-m",
            "scripts.run_scheduled_stage_bundle",
            "--trade-date",
            business_date,
            "--stage-id",
            stage_id,
        ],
        cwd=bundled_stage_root,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    payload = _last_json_object(completed.stdout)
    if completed.returncode != 0 or not payload.get("ok") or payload.get("status") != "READY":
        detail = payload.get("error") or completed.stderr[-1200:] or payload.get("status")
        raise RuntimeError(f"SHARED_STAGE_ACQUISITION_FAILED:{stage_id}:{detail}")
    unsafe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if payload.get(key) is not False
    ]
    if unsafe:
        raise RuntimeError("SHARED_STAGE_ACQUISITION_UNSAFE:" + ",".join(unsafe))
    return {
        "status": "READY",
        "stage_id": stage_id,
        "receipt_path": payload.get("receipt_path"),
        "stage_acquisition_universe": {
            "status": universe["status"],
            "row_count": universe["row_count"],
            "run_id": universe.get("run_id"),
            "current_path": str(universe.get("current_path") or ""),
            "idempotent": bool(universe.get("idempotent")),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def ensure_stage_candidate_input(
    *,
    data_root: Path,
    business_date: str,
    universe_materializer=None,
) -> dict[str, Any]:
    """Idempotently ensure the stage consumer has a verified candidate input.

    The shared Stage Center remains the sole raw/selection producer.  This
    small prerequisite is owned by the V4 scheduler so consume-only mode
    cannot leave a stage slot without the exact-date acquisition universe.
    """

    materializer = universe_materializer or materialize_stage_acquisition_universe
    universe = materializer(data_root, business_date)
    artifact = universe.get("artifact") if isinstance(universe, dict) else None
    if (
        not isinstance(universe, dict)
        or universe.get("status") not in {"READY", "SUPERSEDED"}
        or not isinstance(universe.get("row_count"), int)
        or isinstance(universe.get("row_count"), bool)
        or universe["row_count"] <= 0
        or not isinstance(artifact, dict)
    ):
        raise RuntimeError("STAGE_ACQUISITION_UNIVERSE_NOT_READY")
    unsafe_universe = [
        key
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
        if artifact.get(key) is not False
    ]
    if unsafe_universe:
        raise RuntimeError(
            "STAGE_ACQUISITION_UNIVERSE_UNSAFE:" + ",".join(unsafe_universe)
        )
    declared_current = universe.get("current_path")
    try:
        if not isinstance(declared_current, (str, Path)) or not str(declared_current):
            raise CandidateInputError("materializer current_path missing")
        candidate = read_candidate_input(data_root, business_date)
        current_path = Path(declared_current).expanduser()
        if not current_path.is_file():
            raise CandidateInputError("materializer current_path unreadable")
        canonical_current = candidate.root / candidate.current_relative
        if current_path.resolve(strict=True) != canonical_current.resolve(strict=True):
            raise CandidateInputError("materializer current_path is not canonical current")
        expected_bindings = {
            "row_count": len(candidate.codes),
            "run_id": candidate.run_id,
            "artifact_sha256": candidate.artifact_sha256,
            "manifest_sha256": candidate.manifest_sha256,
            "receipt_sha256": candidate.receipt_sha256,
        }
        if any(universe.get(key) != value for key, value in expected_bindings.items()):
            raise CandidateInputError("materializer result does not match verified current")
    except (CandidateInputError, OSError, TypeError, ValueError) as error:
        raise RuntimeError("STAGE_ACQUISITION_UNIVERSE_NOT_READY") from error
    return {
        "status": universe["status"],
        "row_count": universe["row_count"],
        "run_id": universe.get("run_id"),
        "current_path": str(current_path.resolve(strict=True)),
        "artifact_sha256": universe.get("artifact_sha256"),
        "manifest_sha256": universe.get("manifest_sha256"),
        "receipt_sha256": universe.get("receipt_sha256"),
        "idempotent": bool(universe.get("idempotent")),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def consume_shared_stage_selection(
    *,
    business_date: str,
    slot: str,
    selection_root: Path,
    stage_acquisition_universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the shared selection consumed by this scheduler.

    An explicit ``V4_STAGE_CENTER_SELECTION_ROOT`` changes this boundary to
    read-only consumption.  In particular, this helper deliberately does not
    invoke the bundled raw/selection producer or publish an artifact.  The
    scheduler owns only the exact-date candidate-input prerequisite and
    reports its verified evidence alongside the consume-only envelope.
    """
    stage_id = STAGE_BY_SLOT.get(slot)
    if stage_id is None:
        return {"status": "NOT_STAGE_SLOT", "write_performed": False}
    result = {
        "status": "CONSUME_ONLY",
        "stage_id": stage_id,
        "business_date": business_date,
        "selection_root": str(selection_root.expanduser().resolve()),
        "direct_acquisition_called": False,
        "producer_called": False,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if stage_acquisition_universe is not None:
        result["stage_acquisition_universe"] = dict(stage_acquisition_universe)
    selection = StageSelectionConsumer(selection_root).get(business_date, stage_id)
    result.update(
        {
            "selection_status": selection.get("status", "CANNOT_CONFIRM"),
            "selection_artifact_id": selection.get("artifact_id"),
            "selection_run_id": selection.get("run_id"),
            "selection_markets": selection.get("markets", {}),
            "cannot_confirm": list(selection.get("cannot_confirm") or []),
        }
    )
    return result


def apply_research_proxy_environment(*, proxy_url: str | None = None) -> dict[str, str]:
    """Install the sanitized research proxy environment at scheduler start."""
    return apply_proxy_environment(proxy_url=proxy_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the due fixed V4 macOS slot")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--hk-universe-root", type=Path)
    parser.add_argument("--shared-package-root", type=Path)
    parser.add_argument("--selector-data-root", type=Path)
    parser.add_argument("--preselection-input-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument(
        "--hk-0-2-python",
        type=Path,
        default=(
            Path(os.environ["V4_HK_0_2_PYTHON"])
            if os.environ.get("V4_HK_0_2_PYTHON")
            else None
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--a-daily-timeout-seconds", type=float)
    parser.add_argument("--slot", choices=ALL_SLOTS, help="fixed-slot canary override")
    parser.add_argument("--date", help="YYYYMMDD canary date; requires --slot")
    parser.add_argument("--repair-expected-old-input-sha256")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--release-id", default=os.environ.get("V4_RELEASE_ID", ""))
    parser.add_argument("--upstream-fingerprint", default=os.environ.get("V4_UPSTREAM_FINGERPRINT", ""))
    args = parser.parse_args(argv)
    if args.date and not args.slot:
        parser.error("--date requires --slot")
    if args.repair_expected_old_input_sha256 and (not args.date or not args.slot):
        parser.error(
            "--repair-expected-old-input-sha256 requires explicit --date and --slot"
        )

    # launchd does not guarantee proxy variable casing for child processes.
    # Install the bounded research transport environment at this scheduler
    # boundary so hourly peripheral executors inherit the same proxy-first,
    # loopback-direct policy as the shared-stage child.
    apply_research_proxy_environment()

    detected_date, detected_slot = current_slot()
    if args.slot:
        due = {
            "business_date": args.date or detected_date,
            "observed_slot": detected_slot,
            "slot": args.slot,
            "catchup": False,
            "lag_minutes": 0,
        }
    else:
        due = resolve_due_slot(
            ledger_root=args.ledger_root,
            release_id=args.release_id or None,
            upstream_fingerprint=args.upstream_fingerprint or None,
        )
    if due.get("retry_blocked"):
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "RETRY_BACKOFF",
                "business_date": due["business_date"],
                "observed_slot": due["observed_slot"],
                "slot": None,
                "catchup": {"applied": False, "lag_minutes": 0},
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0
    slot = str(due["slot"])
    business_date = args.date or str(due["business_date"])
    if slot not in ALL_SLOTS:
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "NO_DUE_SLOT",
                "business_date": business_date,
                "observed_slot": due["observed_slot"],
                "catchup": {
                    "applied": False,
                    "lag_minutes": 0,
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 0

    shared_acquisition: dict[str, Any] = {"status": "NOT_STAGE_SLOT"}
    from infrastructure.scheduling.execution_ledger import ExecutionLedger, SchedulerLaneExpired
    def lane_admission():
        try:
            ExecutionLedger(args.ledger_root).validate_scheduler_lane(business_date, slot)
            return True
        except SchedulerLaneExpired:
            _emit({"schema_version": RESULT_SCHEMA, "status": "EXPIRED", "failure_class": "NOT_DUE",
                "business_date": business_date, "slot": slot, "reason": "SCHEDULER_SLOT_EXPIRED",
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
            return False
    try:
        if not lane_admission(): return 0
        dates = compute_dates(business_date=business_date, slot=slot)
        stage_slot = slot in STAGE_INPUT_SLOTS
        candidate_prewarm_slot = slot in STAGE_CANDIDATE_PREWARM_SLOTS
        candidate_input_slot = stage_slot or candidate_prewarm_slot
        non_trading_stage = (
            not args.dry_run
            and candidate_input_slot
            and _is_non_trading_day(business_date)
        )
        if non_trading_stage:
            shared_acquisition = {
                "status": "SKIPPED_NON_TRADING_DAY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        elif (
            not args.dry_run
            and candidate_input_slot
            and args.stage_selection_root is not None
        ):
            if candidate_prewarm_slot:
                try:
                    stage_acquisition_universe = ensure_stage_candidate_input(
                        data_root=args.data_root,
                        business_date=business_date,
                    )
                    shared_acquisition = {
                        "status": stage_acquisition_universe.get("status", "CANNOT_CONFIRM"),
                        "business_date": business_date,
                        "selection_root": str(
                            args.stage_selection_root.expanduser().resolve()
                        ),
                        "lane": "A_SHARE",
                        "stage_acquisition_universe": stage_acquisition_universe,
                        "candidate_input_write_performed": not bool(
                            stage_acquisition_universe.get("idempotent")
                        ),
                        "stage_selection_write_performed": False,
                        "selection_consumed": False,
                        "direct_acquisition_called": False,
                        "producer_called": False,
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                except (OSError, RuntimeError, ValueError) as error:
                    # The opening auction must still reach its independent
                    # dispatcher workload when the A prewarm is unavailable.
                    # Keep the A lane explicitly fail-closed and never invoke
                    # the Stage Center raw/selection producer here.
                    shared_acquisition = {
                        "status": "CANNOT_CONFIRM",
                        "business_date": business_date,
                        "selection_root": str(
                            args.stage_selection_root.expanduser().resolve()
                        ),
                        "lane": "A_SHARE",
                        "stage_input_error": f"{type(error).__name__}: {error}",
                        "candidate_input_write_performed": False,
                        "stage_selection_write_performed": False,
                        "selection_consumed": False,
                        "direct_acquisition_called": False,
                        "producer_called": False,
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
            else:
                try:
                    stage_acquisition_universe = ensure_stage_candidate_input(
                        data_root=args.data_root,
                        business_date=business_date,
                    )
                    shared_acquisition = consume_shared_stage_selection(
                        business_date=business_date,
                        slot=slot,
                        selection_root=args.stage_selection_root,
                        stage_acquisition_universe=stage_acquisition_universe,
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    # A stage-input outage must not starve an independent
                    # hourly/panel workload dispatched at the same heartbeat.
                    # Keep the failure visible and fail closed for the stage;
                    # ``run_scheduled_slot`` remains the owner of other due
                    # workloads and their receipts.
                    shared_acquisition = {
                        "status": "CANNOT_CONFIRM",
                        "stage_id": STAGE_BY_SLOT.get(slot),
                        "business_date": business_date,
                        "selection_root": str(args.stage_selection_root.expanduser().resolve()),
                        "lane": "A_SHARE",
                        "stage_input_error": f"{type(error).__name__}: {error}",
                        "selection_consumed": False,
                        "direct_acquisition_called": False,
                        "producer_called": False,
                        "write_performed": False,
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
        elif not args.dry_run and stage_slot:
            raise ValueError("stage selection root is required for consume-only stage slots")
        if not lane_admission(): return 0
        result = run_scheduled_slot(
            data_root=args.data_root,
            slot=slot,
            business_date=dates["business_date"],
            scheduled_date=dates["scheduled_date"],
            target_date=dates["target_date"],
            ledger_root=args.ledger_root,
            shared_data_root=args.shared_data_root,
            hk_universe_root=args.hk_universe_root,
            shared_package_root=args.shared_package_root,
            hk_0_2_python_executable=args.hk_0_2_python,
            selector_data_root=args.selector_data_root,
            preselection_input_root=args.preselection_input_root,
            stage_selection_root=args.stage_selection_root,
            repair_date=args.date if args.repair_expected_old_input_sha256 else None,
            repair_slot=args.slot if args.repair_expected_old_input_sha256 else None,
            repair_expected_old_input_sha256=args.repair_expected_old_input_sha256,
            timeout_seconds=args.timeout_seconds,
            a_daily_timeout_seconds=args.a_daily_timeout_seconds,
            dry_run=args.dry_run,
        )
    except Exception as error:  # launchd boundary: always emit fail-closed JSON
        _emit(
            {
                "schema_version": RESULT_SCHEMA,
                "status": "FAILED",
                "slot": slot,
                "business_date": business_date,
                "reason": f"{type(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 1

    _emit(
        {
            **result,
            "macos_scheduler_schema_version": RESULT_SCHEMA,
            "shared_acquisition": shared_acquisition,
            "observed_slot": due["observed_slot"],
            "catchup": {
                "applied": bool(due["catchup"]),
                "lag_minutes": int(due["lag_minutes"]),
                "scheduled_slot": slot,
            },
        }
    )
    return 0 if result["status"] in ZERO_EXIT_STATUSES or result["status"] == "EXPIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
