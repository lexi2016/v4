"""Readiness gates and CLI orchestration for the daily panel adapter."""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from .macos_research_panel_daily_common import (
    LANE_CHOICES,
    SAFETY_FLAGS,
    SnapshotGateError,
    _a_day_files,
    _absolute_path_argument,
    _after_1700_attempt_path,
    _atomic_write,
    _compact_datetime,
    _date,
    _normalize_lane,
    _not_requested_lane,
    _scheduled_day_is_cross_market_trading_day,
    _today_shanghai,
    build_subprocess_command,
)
from .macos_research_panel_daily_collectors import collect_hk_futu_rows
from .macos_research_panel_daily_authority import (
    _parquet_max_date,
    run_hk_0_2_authority,
    run_windows_a_formula_authority,
    run_windows_a_sync_authority,
)
from .macos_research_panel_daily_pack import (
    _panel_frame,
    bootstrap_a_vipdoc_from_panel,
    pack_hk_day,
)


DEFAULT_A_SYNC_RUN_BUDGET_SECONDS = 540.0
A_SYNC_RUN_BUDGET_ENV = "V4_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"
A_SYNC_HOST_ENV = "V4_A_SYNC_HOST"


def _resolve_a_sync_run_budget(raw: Any | None) -> float:
    """Resolve the A sync wall-clock budget, rejecting unsafe values."""
    if raw is None:
        return DEFAULT_A_SYNC_RUN_BUDGET_SECONDS
    if isinstance(raw, bool):
        raise ValueError("A sync run budget must be a positive finite number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("A sync run budget must be a positive finite number") from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("A sync run budget must be a positive finite number")
    return value


def selector_pointer_is_ready(pointer: Path | str, target_date: str) -> bool:
    """Require the current paired QFQ generation and current factor revision."""
    from ops.research_panel_qfq import input_path, pointer_ready
    pointer_path = Path(pointer).expanduser().resolve()
    return pointer_ready(pointer_path, int(_date(target_date)), input_path(pointer_path.parent.parent))

def _read_lane_receipt(receipt_root: Path | str, lane: str, target_date: str) -> Mapping[str, Any] | None:
    """Read only the exact dated lane receipt used by the after-1700 gate."""

    path = Path(receipt_root).expanduser().resolve() / f"{lane.lower()}-{_date(target_date)}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None

def _receipt_safety_is_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name) is False for name in SAFETY_FLAGS)

def _a_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    selector_ready: bool,
    payload: Mapping[str, Any] | None = None,
) -> tuple[bool, bool]:
    """Require exact A selector plus the formula's exact backtest readiness."""
    receipt = payload if payload is not None else _read_lane_receipt(receipt_root, "A", target_date)
    readiness = getattr(
        __import__(
            "ops.macos_research_panel_daily_receipts",
            fromlist=("a_receipt_readiness",),
        ),
        "a_receipt_readiness",
    )
    context = globals().get("_A_RECEIPT_POINTER_CONTEXT")
    if not isinstance(context, Mapping):
        context = {}
    return readiness(
        receipt,
        target_date,
        selector_ready=selector_ready,
        selector_pointer=context.get("selector_pointer"),
        backtest_pointer=context.get("backtest_pointer"),
    )

def _hk_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Require the exact HK date receipt and a non-empty verified snapshot."""

    receipt = payload if payload is not None else _read_lane_receipt(receipt_root, "HK", target_date)
    if not isinstance(receipt, Mapping):
        return False
    if receipt.get("schema_version") != "v3.macos.research_panel_receipt.v1" or receipt.get("lane") != "HK":
        return False

    def finite(value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return number == number and number not in (float("inf"), float("-inf"))

    try:
        raw_row_count = receipt.get("row_count")
        raw_coverage_rate = receipt.get("coverage_rate")
        if isinstance(raw_row_count, bool) or not isinstance(raw_row_count, int):
            return False
        if (
            isinstance(raw_coverage_rate, bool)
            or not isinstance(raw_coverage_rate, int | float)
            or not finite(raw_coverage_rate)
            or not 0.0 <= float(raw_coverage_rate) <= 1.0
        ):
            return False
        row_count = raw_row_count
        coverage_rate = float(raw_coverage_rate)
    except (TypeError, ValueError):
        return False
    digest = receipt.get("sha256")
    return bool(
        receipt.get("status") == "READY"
        and receipt.get("target_date") == _date(target_date)
        and _receipt_safety_is_false(receipt)
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdefABCDEF" for character in digest)
        and row_count > 0
        and coverage_rate > 0.0
    )

def ensure_after_1700(
    *,
    target_date: str,
    receipt_root: Path | str,
    selector_pointer: Path | str,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str | None = None,
    now: _datetime.datetime | None = None,
) -> dict[str, Any]:
    """Idempotently ensure A after 15:30 and other lanes after 17:00.

    StartInterval can invoke this function repeatedly.  Explicit lane callers
    use only their exact dated receipt as a fast path: A requires selector and
    backtest readiness, HK requires a verified HK snapshot, and ALL requires
    both.  The dated attempt marker applies only a bounded time backoff and
    never converts a stale pointer into a permanent success or permanent
    lockout.
    """

    target = _date(target_date)
    previous_context = globals().get("_A_RECEIPT_POINTER_CONTEXT")
    inherited_context = previous_context if isinstance(previous_context, Mapping) else {}
    backtest_pointer = inherited_context.get("backtest_pointer")
    globals()["_A_RECEIPT_POINTER_CONTEXT"] = {
        "selector_pointer": selector_pointer,
        "backtest_pointer": backtest_pointer,
    }

    def restore_context(value: dict[str, Any]) -> dict[str, Any]:
        if isinstance(previous_context, Mapping):
            globals()["_A_RECEIPT_POINTER_CONTEXT"] = previous_context
        else:
            globals().pop("_A_RECEIPT_POINTER_CONTEXT", None)
        return value

    requested_lane = _normalize_lane(lane or "ALL")
    strict_lane_readiness = lane is not None
    moment = now or _datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        moment = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    common = {
        "schema_version": "v3.macos.research_panel_after_1700_ensure.v1",
        "target_date": target,
        "observed_at": moment.isoformat(),
        "selector_pointer": str(Path(selector_pointer).expanduser().resolve()),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    earliest_slot = "1530" if requested_lane == "A" else "1700"
    if moment.strftime("%H%M") < earliest_slot:
        return restore_context({**common, "status": f"BEFORE_{earliest_slot}", "runner_called": False, "idempotent": True})
    selector_ready = selector_pointer_is_ready(selector_pointer, target)
    common["selector_pointer_ready"] = selector_ready
    a_ready, backtest_ready = _a_lane_receipt_ready(
        receipt_root,
        target,
        selector_ready,
    )
    hk_ready = _hk_lane_receipt_ready(receipt_root, target)
    common.update(
        {
            "a_lane_ready": a_ready,
            "hk_lane_ready": hk_ready,
            "backtest_pointer_ready": backtest_ready,
        }
    )
    already_ready = (
        (requested_lane == "A" and a_ready)
        or (requested_lane == "HK" and hk_ready)
        or (requested_lane == "ALL" and a_ready and hk_ready)
    )
    # Calls that predate the explicit lane contract retain the old selector
    # fast path; launchd and all current callers pass lane explicitly.
    if selector_ready and ((not strict_lane_readiness and requested_lane == "ALL") or already_ready):
        return restore_context({**common, "status": "ALREADY_READY", "runner_called": False, "idempotent": True})

    attempt_path = _after_1700_attempt_path(receipt_root, target)
    if attempt_path.is_file():
        try:
            payload = json.loads(attempt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, Mapping):
            attempt_count = int(payload.get("attempt_count") or 1)
            previous_raw = str(payload.get("observed_at") or "")
            try:
                previous = _datetime.datetime.fromisoformat(previous_raw)
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                elapsed = (moment - previous.astimezone(ZoneInfo("Asia/Shanghai"))).total_seconds()
            except (TypeError, ValueError, OverflowError):
                elapsed = 300.0
            if elapsed < 300.0:
                return restore_context({
                    **common,
                    **dict(payload),
                    "status": "RETRY_BACKOFF",
                    "runner_called": False,
                    "idempotent": True,
                })
        else:
            attempt_count = 1
    else:
        attempt_count = 0

    result = run_lanes(
        target_date=target,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=requested_lane,
    )
    selector_ready_after = selector_pointer_is_ready(selector_pointer, target)
    a_payload = (result.get("lanes") or {}).get("A") if isinstance(result.get("lanes"), Mapping) else None
    hk_payload = (result.get("lanes") or {}).get("HK") if isinstance(result.get("lanes"), Mapping) else None
    a_ready_after, backtest_ready_after = _a_lane_receipt_ready(
        receipt_root,
        target,
        selector_ready_after,
        a_payload if isinstance(a_payload, Mapping) else None,
    )
    hk_ready_after = _hk_lane_receipt_ready(
        receipt_root, target, hk_payload if isinstance(hk_payload, Mapping) else None
    )
    lane_ready = (
        (requested_lane == "A" and a_ready_after)
        or (requested_lane == "HK" and hk_ready_after)
        or (requested_lane == "ALL" and a_ready_after and hk_ready_after)
    )
    payload = {
        **common,
        "status": "ATTEMPTED",
        "runner_called": True,
        "idempotent": False,
        "attempt_count": attempt_count + 1,
        "overall_status": result.get("overall_status"),
        "requested_lane": requested_lane,
        "lanes": result.get("lanes", {}),
        "selector_pointer_ready": selector_ready_after,
        "a_lane_ready": a_ready_after,
        "hk_lane_ready": hk_ready_after,
        "backtest_pointer_ready": backtest_ready_after,
        "lane_ready": lane_ready,
    }
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(attempt_path, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return restore_context(payload)

def ensure_exit_code(result: Mapping[str, Any]) -> int:
    """Map an after-17:00 result to a truthful process exit code.

    A retry marker or a completed attempt is not success evidence while the
    selector pointer still misses the exact target date.  launchd must keep
    retrying those results instead of recording a false healthy run.
    """

    status = str(result.get("status") or "")
    if "lane_ready" in result:
        lane_ready = result.get("lane_ready") is True
        if status in {"BEFORE_1530", "BEFORE_1700"}:
            return 0
        if status in {"ALREADY_READY", "ATTEMPTED"} and lane_ready:
            return 0
        return 2
    pointer_ready = result.get("selector_pointer_ready") is True
    backtest_pointer = result.get("backtest_pointer_ready")
    if backtest_pointer is None:
        lanes = result.get("lanes")
        if isinstance(lanes, Mapping):
            a_lane = lanes.get("A") or lanes.get("a")
            if isinstance(a_lane, Mapping):
                formula = a_lane.get("formula")
                if isinstance(formula, Mapping):
                    backtest_pointer = formula.get("backtest_pointer_ready")
    if backtest_pointer is False:
        pointer_ready = False
    if status in {"BEFORE_1530", "BEFORE_1700"}:
        return 0
    if status == "ALREADY_READY" and pointer_ready:
        return 0
    if status == "ATTEMPTED" and pointer_ready:
        return 0
    return 2

def _receipt(root: Path, lane: str, target_date: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        **dict(outcome),
        "schema_version": "v3.macos.research_panel_receipt.v1",
        "lane": lane,
        "target_date": _date(target_date),
        **SAFETY_FLAGS,
    }
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / f"{lane.lower()}-{_date(target_date)}.json", (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload

def run_lanes(*, target_date: str, receipt_root: Path | str, a_runner: Callable[[str], Mapping[str, Any]], hk_runner: Callable[[str], Mapping[str, Any]], lane: str = "ALL") -> dict[str, Any]:
    target_date = _date(target_date)
    requested_lane = _normalize_lane(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes: dict[str, dict[str, Any]] = {}
    for lane, runner in (("A", a_runner), ("HK", hk_runner)):
        if lane not in requested:
            lanes[lane] = _not_requested_lane()
            continue
        outcome: dict[str, Any] = {}
        try:
            outcome = dict(runner(target_date))
            outcome.setdefault("status", "READY")
            if outcome.get("target_date", target_date) != target_date:
                raise SnapshotGateError(f"{lane} exact target date mismatch")
            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, {**outcome, "runner_called": True, "receipt_written": True})
        except Exception as error:  # independent lane: never prevent the other lane
            structured = getattr(error, "result", None)
            failure = dict(structured) if isinstance(structured, Mapping) else dict(outcome)
            error_text = failure.get("error")
            if not error_text:
                error_text = str(error) if isinstance(structured, Mapping) else f"{type(error).__name__}: {error}"
            return_code = getattr(error, "returncode", None)
            if isinstance(return_code, int):
                failure.setdefault("exit_code", return_code)
            for field in ("stdout", "stderr"):
                value = getattr(error, field, None)
                if value not in (None, ""):
                    failure.setdefault(field, value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value))
            failure.update(
                {
                    "status": "FAILED",
                    "error": error_text,
                    "runner_called": True,
                    "receipt_written": True,
                }
            )
            failure.setdefault("exit_code", 1)
            failure.setdefault("exception_type", type(error).__name__)
            # A failed lane has no coverage observation; null is distinct from
            # a measured zero and keeps the receipt fail-closed.
            failure.setdefault("coverage_rate", None)
            failure.setdefault("sha256", "")
            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, failure)
    statuses = {lanes[name].get("status") for name in requested}
    overall = "READY" if statuses == {"READY"} else "FAILED" if statuses == {"FAILED"} else "PARTIAL"
    return {"schema_version": "v3.macos.research_panel_daily.v1", "target_date": target_date, "requested_lane": requested_lane, "overall_status": overall, "lanes": lanes, **SAFETY_FLAGS}

def _non_trading_day_result(target_date: str, receipt_root: Path | str, *, lane: str = "ALL") -> dict[str, Any]:
    """Emit explicit no-op receipts for an implicit non-trading-day launch."""
    target_date = _date(target_date)
    requested_lane = _normalize_lane(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes = {
        lane: _receipt(
            Path(receipt_root),
            lane,
            target_date,
            {
                "status": "NON_TRADING_DAY",
                "reason_code": "IMPLICIT_DATE_NOT_CROSS_MARKET_TRADING_DAY",
                "coverage_rate": 0.0,
                "row_count": 0,
                "sha256": "",
                "runner_called": False,
            },
        )
        for lane in requested
    }
    lanes.update({name: _not_requested_lane() for name in {"A", "HK"} - requested})
    return {
        "schema_version": "v3.macos.research_panel_daily.v1",
        "target_date": target_date,
        "requested_lane": requested_lane,
        "overall_status": "NON_TRADING_DAY",
        "lanes": lanes,
        "runner_called": False,
        **SAFETY_FLAGS,
    }

def run_scheduled_lanes(
    *,
    target_date: str | None,
    receipt_root: Path | str,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str = "ALL",
) -> dict[str, Any]:
    """Run launchd's implicit date only on a proven A/H business day.

    Callers that supply ``target_date`` retain the existing explicit replay
    semantics, including the ability to diagnose a holiday snapshot.
    """
    explicit_date = target_date is not None
    resolved = _date(target_date if explicit_date else _today_shanghai())
    if not explicit_date and not _scheduled_day_is_cross_market_trading_day(resolved):
        return _non_trading_day_result(resolved, receipt_root, lane=lane)
    return run_lanes(
        target_date=resolved,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=lane,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only A/H daily lane receipt helper")
    parser.add_argument("--date", required=False, default=None)
    parser.add_argument("--lane", choices=LANE_CHOICES, default="ALL")
    parser.add_argument("--receipt-root", required=True, type=Path)
    parser.add_argument("--a-tdx-root", required=True, type=Path)
    parser.add_argument("--hk-tdx-root", required=True, type=Path)
    parser.add_argument("--a-universe", required=False, type=Path, help="Legacy collector input; ignored by authority chain")
    parser.add_argument("--a-minimum-rows", type=int, default=1)
    parser.add_argument("--a-limit", type=int, default=None, help="Canary-only A universe limit; never lowers HK minimum 600")
    parser.add_argument(
        "--a-sync-run-budget-seconds",
        default=None,
        help=f"Positive finite A sync wall-clock budget in seconds (default: {int(DEFAULT_A_SYNC_RUN_BUDGET_SECONDS)}; env: {A_SYNC_RUN_BUDGET_ENV})",
    )
    parser.add_argument(
        "--a-host",
        default=os.environ.get(A_SYNC_HOST_ENV) or None,
        help=f"Explicit pytdx HQ host override (default: env {A_SYNC_HOST_ENV}); otherwise probe official hq_hosts",
    )
    parser.add_argument("--a-port", type=int, default=None, help="Explicit pytdx HQ port (requires --a-host)")
    parser.add_argument("--a-sync-script", type=Path, required=False)
    parser.add_argument("--a-formula-script", type=Path, required=False)
    parser.add_argument("--a-seed-panel", type=Path, required=False)
    parser.add_argument("--a-data-root", type=Path, required=False)
    parser.add_argument("--a-selector-pointer", type=Path, required=False)
    parser.add_argument("--a-backtest-pointer", type=Path, required=False)
    parser.add_argument("--a-selector-seed", type=Path, required=False)
    parser.add_argument("--a-backtest-seed", type=Path, required=False)
    parser.add_argument("--a-contract-csv", type=Path, required=False)
    parser.add_argument("--a-canonical-formula", type=Path, required=False)
    parser.add_argument("--a-return-root", type=Path, required=False)
    parser.add_argument("--hk-updater-script", type=Path, required=False)
    parser.add_argument("--hk-python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--hk-asset-root", type=Path, required=False)
    args = parser.parse_args()
    raw_a_sync_run_budget = args.a_sync_run_budget_seconds
    if raw_a_sync_run_budget is None:
        raw_a_sync_run_budget = os.environ.get(A_SYNC_RUN_BUDGET_ENV)
    try:
        a_sync_run_budget = _resolve_a_sync_run_budget(raw_a_sync_run_budget)
    except ValueError as error:
        parser.error(str(error))
    args.receipt_root = _absolute_path_argument(parser, args.receipt_root, "--receipt-root")
    args.a_tdx_root = _absolute_path_argument(parser, args.a_tdx_root, "--a-tdx-root")
    args.hk_tdx_root = _absolute_path_argument(parser, args.hk_tdx_root, "--hk-tdx-root")
    if args.a_minimum_rows < 1:
        parser.error("--a-minimum-rows must be positive")
    if args.a_limit is not None and (args.a_limit < 1 or args.a_minimum_rows > args.a_limit):
        parser.error("--a-minimum-rows cannot exceed --a-limit")
    if args.a_port is not None and args.a_host is None:
        parser.error("--a-port requires --a-host")
    if args.a_port is not None and not 1 <= int(args.a_port) <= 65535:
        parser.error("--a-port must be between 1 and 65535")
    if args.a_port is not None and ":" in str(args.a_host):
        parser.error("--a-host must omit the port when --a-port is used")
    authority_paths = {
        "--a-sync-script": args.a_sync_script,
        "--a-formula-script": args.a_formula_script,
        "--a-seed-panel": args.a_seed_panel,
        "--a-data-root": args.a_data_root,
        "--a-selector-pointer": args.a_selector_pointer,
        "--a-backtest-pointer": args.a_backtest_pointer,
        "--a-selector-seed": args.a_selector_seed,
        "--a-backtest-seed": args.a_backtest_seed,
        "--a-contract-csv": args.a_contract_csv,
        "--a-canonical-formula": args.a_canonical_formula,
        "--a-return-root": args.a_return_root,
        "--hk-updater-script": args.hk_updater_script,
        "--hk-asset-root": args.hk_asset_root,
    }
    missing = [name for name, value in authority_paths.items() if value is None]
    if missing:
        parser.error("authority chain requires explicit paths: " + ", ".join(missing))
    for name, value in authority_paths.items():
        authority_paths[name] = _absolute_path_argument(parser, value, name)
    python_executable = _absolute_path_argument(parser, args.hk_python_executable, "--hk-python-executable")

    def run_a(target: str) -> dict[str, Any]:
        day_files_before = _a_day_files(args.a_tdx_root)
        bootstrap = None
        if not day_files_before:
            # QFQ input cannot be bootstrapped from an unknown-basis old panel.
            raise SnapshotGateError(f"QFQ_ORIGINAL_TDX_DAY_AUTHORITY_MISSING:{args.a_tdx_root}")
        sync_authority_args: dict[str, Any] = {"run_budget_seconds": a_sync_run_budget}
        if args.a_host is not None:
            sync_host = str(args.a_host)
            if args.a_port is not None:
                sync_host = f"{sync_host}:{int(args.a_port)}"
            sync_authority_args["host"] = sync_host
        sync = run_windows_a_sync_authority(
            authority_paths["--a-sync-script"],
            args.a_tdx_root,
            target,
            args.receipt_root,
            minimum_target_date_files=max(args.a_minimum_rows, 1),
            authority_args=sync_authority_args,
        )
        formula = run_windows_a_formula_authority(
            authority_paths["--a-formula-script"],
            tdx_root=sync.get("formula_tdx_root") or args.a_tdx_root,
            qfq_original_tdx_root=args.a_tdx_root,
            data_root=authority_paths["--a-data-root"],
            selector_pointer=authority_paths["--a-selector-pointer"],
            backtest_pointer=authority_paths["--a-backtest-pointer"],
            selector_seed=authority_paths["--a-selector-seed"],
            backtest_seed=authority_paths["--a-backtest-seed"],
            contract_csv=authority_paths["--a-contract-csv"],
            canonical_formula_path=authority_paths["--a-canonical-formula"],
            return_root=authority_paths["--a-return-root"],
            target_date=target,
        )
        builder = getattr(
            __import__(
                "ops.macos_research_panel_daily_receipts",
                fromlist=("build_a_lane_outcome",),
            ),
            "build_a_lane_outcome",
        )
        return builder(sync, formula, target, bootstrap)

    def run_hk(target: str) -> dict[str, Any]:
        # Every collector invocation gets a fresh manifest identity.  The
        # collector must return the exact immutable path it wrote; resolving a
        # manifest by target date would allow a retry to consume stale bytes.
        capture_manifest_path = args.receipt_root / "hk_capture" / target / (
            f"{target}-{os.getpid()}-{os.urandom(12).hex()}.json"
        )
        previous_capture_path = os.environ.get("V4_HK_CAPTURE_PATH")
        previous_capture_run_id = os.environ.get("V4_HK_CAPTURE_RUN_ID")
        os.environ["V4_HK_CAPTURE_PATH"] = str(capture_manifest_path)
        os.environ["V4_HK_CAPTURE_RUN_ID"] = capture_manifest_path.stem
        try:
            collected = collect_hk_futu_rows(target, minimum_universe_count=600, required_coverage_ratio=0.0)
        finally:
            if previous_capture_path is None:
                os.environ.pop("V4_HK_CAPTURE_PATH", None)
            else:
                os.environ["V4_HK_CAPTURE_PATH"] = previous_capture_path
            if previous_capture_run_id is None:
                os.environ.pop("V4_HK_CAPTURE_RUN_ID", None)
            else:
                os.environ["V4_HK_CAPTURE_RUN_ID"] = previous_capture_run_id

        reported_capture_path = (
            collected.get("capture_manifest_path")
            if isinstance(collected, Mapping)
            else None
        )
        if not reported_capture_path:
            raise SnapshotGateError("HK collector did not return its exact capture manifest path")
        reported_capture_path = Path(str(reported_capture_path)).expanduser()
        if reported_capture_path.is_symlink():
            raise SnapshotGateError("HK capture manifest path must not be a symlink")
        capture_manifest_path = reported_capture_path.resolve()
        try:
            capture_manifest_path.relative_to(Path(args.receipt_root).expanduser().resolve())
        except ValueError as error:
            raise SnapshotGateError("HK collector returned a capture path outside receipt root") from error
        capture = None
        manifest_exists = capture_manifest_path.is_file()
        if manifest_exists:
            try:
                envelope = json.loads(capture_manifest_path.read_bytes().decode("utf-8-sig"))
                envelope_data = envelope if isinstance(envelope, Mapping) else {}
                candidate = envelope_data.get("capture")
                if not isinstance(candidate, Mapping):
                    raise SnapshotGateError("HK capture manifest capture payload is invalid")
                raw_reference = envelope_data.get("capture_relative_path") or envelope_data.get("capture_path")
                if not isinstance(raw_reference, str) or not raw_reference or Path(raw_reference).is_absolute():
                    raise SnapshotGateError("HK capture raw path must be relative")
                raw_unresolved = capture_manifest_path.parent / raw_reference
                if raw_unresolved.is_symlink():
                    raise SnapshotGateError("HK capture raw path must not be a symlink")
                raw_path = raw_unresolved.resolve()
                try:
                    raw_path.relative_to(capture_manifest_path.parent.resolve())
                except ValueError as error:
                    raise SnapshotGateError("HK capture raw path escapes manifest root") from error
                raw_bytes = raw_path.read_bytes()
                raw_candidate = json.loads(raw_bytes.decode("utf-8-sig"))
                raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                raw_matches = raw_candidate == candidate
                valid_manifest = raw_matches and envelope_data.get("schema_version") == "v3.macos.research_panel_hk_capture_manifest.v1" and envelope_data.get("status") == "READY" and envelope_data.get("target_date") == target and envelope_data.get("capture_raw_sha256") == raw_sha256 and envelope_data.get("capture_sha256") == candidate.get("capture_sha256") and envelope_data.get("codes") == candidate.get("codes")
                if not valid_manifest:
                    raise SnapshotGateError("HK capture manifest is invalid or stale")
                capture = candidate
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
                raise SnapshotGateError("HK capture manifest cannot be confirmed") from error
        if not isinstance(capture, Mapping):
            raise SnapshotGateError("HK panel capture missing after collector")
        # Validate the capture before pack/updater can advance any panel
        # pointer.  The final call below repeats the validation with the
        # immutable panel SHA bound by the updater.
        from ops.ensure_hk_security_master import (
            _is_sha256,
            _panel_capture_binding_sha256,
            _validated_capture,
        )

        _validated_capture(capture, trade_date=target, panel_sha256=None)
        source_payload = capture["source_payload"]
        expected_panel_codes = set(capture["codes"]) - set(source_payload["excluded_codes"])
        if not isinstance(collected, Mapping) or collected.get("target_date") != target or collected.get("rows") != capture["rows"] or collected.get("source_sha256") != capture["source_sha256"]:
            raise SnapshotGateError("HK snapshot coverage mismatch: collector rows differ from capture manifest")
        packed = pack_hk_day(
            args.hk_tdx_root,
            capture["rows"],
            target_date=target,
            minimum_rows=600,
            expected_codes=expected_panel_codes,
        )
        packed_day_root = Path(args.hk_tdx_root).expanduser().resolve() / "vipdoc" / "ds" / "lday"
        expected_day_names = {f"71#{code[3:]}.day" for code in expected_panel_codes}
        packed_files = packed.get("files") if isinstance(packed, Mapping) else None
        if not isinstance(packed_files, list):
            raise SnapshotGateError("HK packed panel file ledger missing")
        packed_paths: set[Path] = set()
        for item in packed_files:
            if not isinstance(item, Mapping) or not item.get("path"):
                raise SnapshotGateError("HK packed panel file ledger invalid")
            path = Path(str(item["path"])).expanduser().resolve()
            try:
                path.relative_to(packed_day_root)
            except ValueError as error:
                raise SnapshotGateError("HK packed panel file escapes TDX root") from error
            if not path.is_file():
                raise SnapshotGateError("HK packed panel file missing")
            packed_paths.add(path)
        actual_day_names = {path.name for path in packed_paths}
        if len(packed_paths) != len(packed_files) or actual_day_names != expected_day_names:
            raise SnapshotGateError(f"HK packed panel code set mismatch: actual={len(actual_day_names)},expected={len(expected_day_names)}")
        stale_files: list[dict[str, Any]] = []
        orphan_files: list[dict[str, Any]] = []
        for path in sorted(packed_day_root.glob("*.day")):
            if not path.is_file() or path.name in expected_day_names:
                continue
            entry = {"path": str(path), "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            bucket = stale_files if path.name.startswith("71#") and path.name[3:-4].isdigit() and len(path.name[3:-4]) == 5 else orphan_files
            bucket.append(entry)
        authority = run_hk_0_2_authority(
            authority_paths["--hk-updater-script"],
            python_executable,
            authority_paths["--hk-asset-root"],
            args.hk_tdx_root,
            target,
        )
        from ops.ensure_hk_security_master import _read_verified_hk_panel_authority, ensure_hk_security_master

        asset_root = Path(args.hk_asset_root).expanduser().resolve(); store_root = asset_root.parent.parent
        package_root = Path(authority_paths["--hk-updater-script"]).expanduser().resolve().parents[1]
        panel_sha256 = authority.get("panel_sha256")
        if not _is_sha256(panel_sha256):
            raise SnapshotGateError("HK panel authority SHA invalid")
        if authority.get("through_date_code_count") != len(expected_panel_codes):
            raise SnapshotGateError("HK panel and Futu capture universe coverage mismatch")
        panel_sha256 = _read_verified_hk_panel_authority(asset_root=asset_root, package_root=package_root, authority=authority, trade_date=target)
        try:
            manifest = json.loads((asset_root / str(authority["manifest_relative"])).read_text(encoding="utf-8"))
            panel_path = (asset_root / str(manifest["panel_relative"])).resolve()
            panel_path.relative_to(asset_root)
            panel_rows = _panel_frame(panel_path)
        except Exception as error:
            raise SnapshotGateError("HK panel authority parquet unreadable") from error
        raw_codes = [row.get("code_norm") for row in panel_rows if _compact_datetime(row.get("trade_date_compact")) == target]
        normalized_codes = [f"HK.{digits[-5:].zfill(5)}" if (digits := "".join(character for character in str(value or "") if character.isdigit())) else "" for value in raw_codes]
        panel_codes = set(normalized_codes)
        if not raw_codes or any(not code for code in normalized_codes) or len(panel_codes) != len(raw_codes):
            raise SnapshotGateError("HK panel authority target code_norm invalid")
        verified_panel_sha256 = _read_verified_hk_panel_authority(asset_root=asset_root, package_root=package_root, authority=authority, trade_date=target)
        if verified_panel_sha256.lower() != panel_sha256.lower():
            raise SnapshotGateError("HK panel SHA changed during code-set binding")
        if panel_codes != expected_panel_codes:
            raise SnapshotGateError(f"HK panel code set mismatch: actual={len(panel_codes)},expected={len(expected_panel_codes)}")
        panel_binding_sha256 = _panel_capture_binding_sha256(capture, panel_sha256)
        security_master = ensure_hk_security_master(
            store_root=store_root,
            universe_root=store_root,
            shared_package_root=package_root,
            trade_date=target,
            futu_python=python_executable,
            capture=capture,
            panel_sha256=panel_sha256,
            panel_binding_sha256=panel_binding_sha256,
        )
        if security_master.get("panel_capture_binding_sha256") != panel_binding_sha256:
            raise SnapshotGateError("HK panel capture binding SHA mismatch")
        return {
            **collected,
            **packed,
            "authority": authority,
            "security_master": security_master,
            "panel_capture_binding_sha256": panel_binding_sha256,
            "source_sha256": collected["source_sha256"],
            "persistent_stale_files": stale_files,
            "persistent_orphan_files": orphan_files,
            "persistent_out_of_scope_count": len(stale_files) + len(orphan_files),
        }

    if args.date is None:
        previous_context = globals().get("_A_RECEIPT_POINTER_CONTEXT")
        globals()["_A_RECEIPT_POINTER_CONTEXT"] = {
            "selector_pointer": authority_paths["--a-selector-pointer"],
            "backtest_pointer": authority_paths["--a-backtest-pointer"],
        }
        try:
            result = ensure_after_1700(
                target_date=_today_shanghai(),
                receipt_root=args.receipt_root,
                selector_pointer=authority_paths["--a-selector-pointer"],
                a_runner=run_a,
                hk_runner=run_hk,
                lane=args.lane,
            )
        finally:
            if isinstance(previous_context, Mapping):
                globals()["_A_RECEIPT_POINTER_CONTEXT"] = previous_context
            else:
                globals().pop("_A_RECEIPT_POINTER_CONTEXT", None)
    else:
        result = run_scheduled_lanes(target_date=args.date, receipt_root=args.receipt_root, a_runner=run_a, hk_runner=run_hk, lane=args.lane)
    overall_status = result.get("overall_status", result.get("status", "CANNOT_CONFIRM"))
    status = result.get("status", overall_status)
    summary_keys = ("status", "target_date", "row_count", "coverage_rate", "sha256", "authority_status", "reason", "error", "persistent_stale_files", "persistent_orphan_files", "persistent_out_of_scope_count", *SAFETY_FLAGS)
    lanes = result.get("lanes") if isinstance(result.get("lanes"), Mapping) else {}
    envelope = {"schema_version": "v3.macos.research_panel_authority_envelope.v1", "status": status, "overall_status": overall_status, "target_date": result.get("target_date"), "lane": result.get("requested_lane"), "lanes": {name: {key: item[key] for key in summary_keys if key in item} for name, item in lanes.items() if isinstance(item, Mapping)}, **SAFETY_FLAGS}
    print(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return ensure_exit_code(result) if args.date is None else 0 if status in {"READY", "PARTIAL", "NON_TRADING_DAY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
