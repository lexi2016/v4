"""Mac canary wrapper for the released Review Core 21:15 pool pipeline.

The released ``review_core.pool_pipeline`` module is the only producer this
wrapper invokes.  The wrapper supplies an explicit date/calendar contract,
keeps every writable root below the bounded canary directory, and imports the
formal Review Core package only from macOS Application Support.  It does not
register a task, touch formal state, run FunASR, or expose BUY/order behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


WRAPPER_SCHEMA = "v3_5.review_core.pool_pipeline_wrapper.receipt.v1"
WRAPPER_ROLE = "REVIEW_CORE_POOLS_2115_MAC_CANARY"
WORKLOADS = ("hk_close_review", "fupan_pool", "stage7_pool")
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
PIPELINE_TIMEOUT_SECONDS = 300
WRAPPER_FAILURE_EXIT_CODE = 2
TIMEOUT_EXIT_CODE = 124

# This batch is intentionally a one-date repair/canary.  All three boundaries
# are required instead of deriving a weekday-only fallback in the wrapper.
FROZEN_TRADE_DATE = "20260821"
FROZEN_PREVIOUS_TRADE_DATE = "20260820"
FROZEN_TARGET_DATE = "20260824"

_DATE_RE = re.compile(r"^\d{8}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_PATH_MARKERS = ("desktop", "windows")
_APP_SUPPORT_ROOT = (Path.home() / "Library" / "Application Support").resolve()
_CANARY_ROOT = (
    Path.home()
    / "Documents"
    / "Codex"
    / "2026-08-13"
    / "v35-stage-selection-20260821-fix"
    / "test-tmp"
    / "fupan-pipeline"
).resolve()
_CANDIDATE_ROOT = Path(__file__).resolve().parents[3]
_CANDIDATE_APP_ROOT = Path(__file__).resolve().parents[1]
_CANDIDATE_CONTRACTS_ROOT = (_CANDIDATE_APP_ROOT / "contracts").resolve()


class WrapperError(ValueError):
    """Base class for fail-closed request/result validation."""


class PathBoundaryError(WrapperError):
    """A package, read root, or writable root escapes the Mac allowlist."""


class FrozenDateError(WrapperError):
    """The request does not match this batch's frozen date mapping."""


class CalendarValidationError(WrapperError):
    """The supplied calendar cannot prove the frozen adjacent dates."""


@dataclass(frozen=True)
class PipelineRequest:
    review_core_package_root: Path
    runtime_root: Path
    shared_root: Path
    hk_root: Path
    close_root: Path
    fupan_store_root: Path
    stage7_store_root: Path
    bundle_root: Path
    shared_store_root: Path
    trade_date: str
    previous_trade_date: str
    target_date: str
    calendar_path: Path
    calendar_sha256: str


def _error(error_type: str, message: str) -> dict[str, str]:
    return {"type": error_type, "message": message}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _as_text_path(value: Path | str, label: str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise PathBoundaryError(f"{label} must be a filesystem path") from error
    if not isinstance(text, str) or not text.strip():
        raise PathBoundaryError(f"{label} must be a non-empty absolute POSIX path")
    if "\\" in text:
        raise PathBoundaryError(f"{label} rejects backslash paths")
    if _WINDOWS_DRIVE_RE.match(text) or text.startswith("//"):
        raise PathBoundaryError(f"{label} rejects Windows/UNC paths")
    lowered = text.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PATH_MARKERS):
        raise PathBoundaryError(f"{label} rejects Desktop/Windows roots")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise PathBoundaryError(f"{label} must be absolute")
    try:
        return str(path.resolve())
    except OSError as error:
        raise PathBoundaryError(f"{label} cannot be resolved") from error


def _path(value: Path | str, label: str) -> Path:
    return Path(_as_text_path(value, label))


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _require_under(path: Path, roots: Sequence[Path], label: str) -> None:
    if not any(_under(path, root) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise PathBoundaryError(f"{label} is outside allowed roots: {allowed}")


def _validate_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise FrozenDateError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise FrozenDateError(f"{label} must be a real calendar date") from error
    return value


def _date(value: str) -> Date:
    return datetime.strptime(value, "%Y%m%d").date()


def _read_calendar(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise CalendarValidationError(f"calendar is missing: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CalendarValidationError(f"calendar is unreadable: {path}") from error
    if not isinstance(payload, Mapping):
        raise CalendarValidationError("calendar root must be an object")
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        raise CalendarValidationError("calendar markets are missing")
    for market in ("a_share", "hk_connect_southbound"):
        if not isinstance(markets.get(market), Mapping):
            raise CalendarValidationError(f"calendar market is missing: {market}")
    return dict(payload), _sha256_bytes(raw)


def _market_open(calendar: Mapping[str, Any], day: str, market: str, seen: set[str] | None = None) -> bool:
    markets = calendar.get("markets")
    config = markets.get(market) if isinstance(markets, Mapping) else None
    if not isinstance(config, Mapping):
        raise CalendarValidationError(f"calendar market is missing: {market}")
    active = set(seen or ())
    if market in active:
        raise CalendarValidationError(f"calendar dependency cycle: {market}")
    active.add(market)
    value = _date(day)
    explicit = config.get("trading_dates", config.get("open_dates"))
    if explicit is not None:
        if not isinstance(explicit, list):
            raise CalendarValidationError(f"calendar trading dates are invalid: {market}")
        if day not in {str(item) for item in explicit}:
            return False
    if value.weekday() >= 5:
        return False
    periods = config.get("holiday_periods")
    if not isinstance(periods, list):
        raise CalendarValidationError(f"calendar holiday periods are invalid: {market}")
    for period in periods:
        if not isinstance(period, Mapping):
            raise CalendarValidationError(f"calendar holiday period is invalid: {market}")
        start = _validate_date(period.get("start"), f"{market}.holiday.start")
        end = _validate_date(period.get("end"), f"{market}.holiday.end")
        if start > end:
            raise CalendarValidationError(f"calendar holiday range is invalid: {market}")
        if start <= day <= end:
            return False
    dependencies = config.get("derives_from", [])
    if dependencies is not None:
        if not isinstance(dependencies, list):
            raise CalendarValidationError(f"calendar dependencies are invalid: {market}")
        if any(not _market_open(calendar, day, str(item), active) for item in dependencies):
            return False
    return True


def _adjacent(calendar: Mapping[str, Any], trade_date: str) -> tuple[str, str]:
    current = _date(trade_date)
    previous = ""
    target = ""
    for offset in range(1, 3661):
        candidate = (current - timedelta(days=offset)).strftime("%Y%m%d")
        if _market_open(calendar, candidate, "hk_connect_southbound"):
            previous = candidate
            break
    for offset in range(1, 3661):
        candidate = (current + timedelta(days=offset)).strftime("%Y%m%d")
        if _market_open(calendar, candidate, "a_share"):
            target = candidate
            break
    if not previous or not target:
        raise CalendarValidationError("calendar cannot prove adjacent trade dates")
    return previous, target


def _validate_calendar_mapping(path: Path, trade_date: str, previous: str, target: str) -> str:
    calendar, digest = _read_calendar(path)
    if not _market_open(calendar, trade_date, "a_share"):
        raise CalendarValidationError(f"trade date is not open: {trade_date}")
    expected_previous, expected_target = _adjacent(calendar, trade_date)
    if (previous, target) != (expected_previous, expected_target):
        raise FrozenDateError(
            "calendar mapping mismatch: "
            f"expected {expected_previous}->{trade_date}->{expected_target}, "
            f"got {previous}->{trade_date}->{target}"
        )
    return digest


def validate_request(
    *,
    review_core_package_root: Path | str,
    runtime_root: Path | str,
    shared_root: Path | str,
    hk_root: Path | str,
    close_root: Path | str,
    fupan_store_root: Path | str,
    stage7_store_root: Path | str,
    bundle_root: Path | str,
    shared_store_root: Path | str,
    trade_date: str,
    previous_trade_date: str,
    target_date: str,
    calendar_path: Path | str,
) -> PipelineRequest:
    """Validate the complete frozen canary request before importing Review Core."""

    trade = _validate_date(trade_date, "trade_date")
    previous = _validate_date(previous_trade_date, "previous_trade_date")
    target = _validate_date(target_date, "target_date")
    if (trade, previous, target) != (
        FROZEN_TRADE_DATE,
        FROZEN_PREVIOUS_TRADE_DATE,
        FROZEN_TARGET_DATE,
    ):
        raise FrozenDateError(
            "this wrapper is frozen to "
            f"{FROZEN_PREVIOUS_TRADE_DATE}->{FROZEN_TRADE_DATE}->{FROZEN_TARGET_DATE}"
        )

    package = _path(review_core_package_root, "review_core_package_root")
    if not _under(package, _APP_SUPPORT_ROOT):
        raise PathBoundaryError("review_core_package_root must be under macOS Application Support")
    package_module = package / "review_core" / "pool_pipeline.py"
    if not package_module.is_file():
        raise PathBoundaryError(f"official Review Core pool_pipeline is missing: {package_module}")

    # Only the formal package is read from Application Support.  All pool,
    # receipt, and bundle roots used by this wrapper are bounded canary roots.
    runtime = _path(runtime_root, "runtime_root")
    hk = _path(hk_root, "hk_root")
    fupan = _path(fupan_store_root, "fupan_store_root")
    stage7 = _path(stage7_store_root, "stage7_store_root")
    for label, value in (
        ("runtime_root", runtime),
        ("hk_root", hk),
        ("fupan_store_root", fupan),
        ("stage7_store_root", stage7),
    ):
        _require_under(value, (_CANARY_ROOT,), label)

    shared = _path(shared_root, "shared_root")
    close = _path(close_root, "close_root")
    bundle = _path(bundle_root, "bundle_root")
    shared_store = _path(shared_store_root, "shared_store_root")
    for label, value in (
        ("shared_root", shared),
        ("close_root", close),
        ("bundle_root", bundle),
        ("shared_store_root", shared_store),
    ):
        _require_under(value, (_CANARY_ROOT, _APP_SUPPORT_ROOT), label)

    calendar = _path(calendar_path, "calendar_path")
    _require_under(calendar, (_CANARY_ROOT, _CANDIDATE_CONTRACTS_ROOT, _APP_SUPPORT_ROOT), "calendar_path")
    digest = _validate_calendar_mapping(calendar, trade, previous, target)
    return PipelineRequest(
        review_core_package_root=package,
        runtime_root=runtime,
        shared_root=shared,
        hk_root=hk,
        close_root=close,
        fupan_store_root=fupan,
        stage7_store_root=stage7,
        bundle_root=bundle,
        shared_store_root=shared_store,
        trade_date=trade,
        previous_trade_date=previous,
        target_date=target,
        calendar_path=calendar,
        calendar_sha256=digest,
    )


def build_command(request: PipelineRequest, *, python_executable: str | None = None) -> list[str]:
    """Build a fixed argv for the official module; no shell interpolation."""

    executable = python_executable or sys.executable
    return [
        executable,
        "-X",
        "utf8",
        "-m",
        "review_core.pool_pipeline",
        "--trade-date",
        request.trade_date,
        "--previous-trade-date",
        request.previous_trade_date,
        "--target-date",
        request.target_date,
        "--calendar-path",
        str(request.calendar_path),
        "--runtime-root",
        str(request.runtime_root),
        "--shared-root",
        str(request.shared_root),
        "--hk-root",
        str(request.hk_root),
        "--close-root",
        str(request.close_root),
        "--fupan-store-root",
        str(request.fupan_store_root),
        "--stage7-store-root",
        str(request.stage7_store_root),
        "--bundle-root",
        str(request.bundle_root),
        "--shared-store-root",
        str(request.shared_store_root),
    ]


def build_environment(request: PipelineRequest, *, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the isolated environment used by the formal shared-data readers."""

    environment = dict(base_env if base_env is not None else os.environ)
    # Do not inherit arbitrary checkout paths: the package root is explicit
    # and must be the only import root for this subprocess.
    environment["PYTHONPATH"] = str(request.review_core_package_root)
    # Formal Application Support is a read-only authority in this batch.  A
    # canary must not create/update bytecode beside the official source.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["V3_SHARED_DATA_PACKAGE_ROOT"] = str(request.shared_root)
    environment["V3_SHARED_DATA_STORE_ROOT"] = str(request.shared_store_root)
    return environment


def _json_stdout(stdout: Any) -> dict[str, Any] | None:
    if not isinstance(stdout, str):
        return None
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _has_provenance(workload: Mapping[str, Any]) -> bool:
    return all(str(workload.get(name) or "").strip() for name in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"))


def _base_envelope(request: PipelineRequest) -> dict[str, Any]:
    return {
        "schema": WRAPPER_SCHEMA,
        "schema_version": WRAPPER_SCHEMA,
        "role": WRAPPER_ROLE,
        "trade_date": request.trade_date,
        "previous_trade_date": request.previous_trade_date,
        "target_date": request.target_date,
        "calendar": {"path": str(request.calendar_path), "sha256": request.calendar_sha256},
        "run_id": "",
        "receipt_path": "",
        "status": "CANNOT_CONFIRM",
        "workloads": {},
        "errors": [],
        **{name: False for name in SAFETY_FLAGS},
    }


def validate_official_result(
    official: Mapping[str, Any],
    request: PipelineRequest,
    *,
    exit_code: int,
    stderr: str = "",
) -> dict[str, Any]:
    """Validate the official receipt without promoting CANNOT_CONFIRM."""

    envelope = _base_envelope(request)
    errors: list[dict[str, str]] = []
    observed_status = _status(official.get("status"))
    if official.get("trade_date") not in (None, request.trade_date):
        errors.append(_error("DateIdentityMismatch", "official trade_date does not match frozen request"))
    if official.get("previous_trade_date") not in (None, request.previous_trade_date):
        errors.append(_error("DateIdentityMismatch", "official previous_trade_date does not match frozen request"))
    if official.get("target_date") not in (None, request.target_date):
        errors.append(_error("DateIdentityMismatch", "official target_date does not match frozen request"))
    if exit_code != 0:
        errors.append(_error("OfficialPipelineExit", f"official pool_pipeline exited with code {exit_code}"))
    if stderr.strip():
        envelope["stderr"] = stderr[-2000:]

    observed_flags = {name: official.get(name) for name in SAFETY_FLAGS}
    envelope["observed_safety_flags"] = observed_flags
    for name in SAFETY_FLAGS:
        if official.get(name) is not False:
            errors.append(_error("UnsafeSafetyFlag", f"official {name} is not false"))

    raw_workloads = official.get("workloads")
    if not isinstance(raw_workloads, Mapping):
        raw_workloads = {}
        errors.append(_error("MissingWorkloads", "official workloads object is missing"))
    workloads: dict[str, dict[str, Any]] = {}
    for name in WORKLOADS:
        value = raw_workloads.get(name)
        if not isinstance(value, Mapping):
            workloads[name] = {
                "status": "CANNOT_CONFIRM",
                "error": _error("MissingWorkload", f"official workload is missing: {name}"),
            }
            errors.append(_error("MissingWorkload", name))
            continue
        item = dict(value)
        item_status = _status(item.get("status"))
        if item_status not in {"READY", "READY_EMPTY", "PARTIAL", "CANNOT_CONFIRM", "FAILED"}:
            workloads[name] = {
                "status": "CANNOT_CONFIRM",
                "observed_status": item_status,
                "error": _error("InvalidWorkloadStatus", name),
            }
            errors.append(_error("InvalidWorkloadStatus", name))
            continue
        item["status"] = item_status
        nested_flags = item.get("safety_flags")
        for flag in SAFETY_FLAGS:
            if flag in item and item.get(flag) is not False:
                errors.append(_error("UnsafeSafetyFlag", f"workload {name} {flag} is not false"))
            if isinstance(nested_flags, Mapping) and flag in nested_flags and nested_flags.get(flag) is not False:
                errors.append(_error("UnsafeSafetyFlag", f"workload {name} safety_flags.{flag} is not false"))
        if item_status == "READY" and not _has_provenance(item):
            item["observed_status"] = item_status
            item["status"] = "CANNOT_CONFIRM"
            item["error"] = _error("MissingProvenance", f"READY workload lacks provenance: {name}")
            errors.append(_error("MissingProvenance", name))
        workloads[name] = item
    envelope["workloads"] = workloads

    if not isinstance(official.get("run_id") or official.get("run"), str):
        errors.append(_error("MissingRunProvenance", "official run_id is missing"))
    envelope["run_id"] = str(official.get("run_id") or official.get("run") or "")
    envelope["receipt_path"] = str(official.get("receipt_path") or "")
    envelope["official_status"] = observed_status or "CANNOT_CONFIRM"
    envelope["official_result"] = dict(official)

    workload_statuses = [str(workloads[name].get("status") or "CANNOT_CONFIRM") for name in WORKLOADS]
    if errors or exit_code != 0 or observed_status == "CANNOT_CONFIRM":
        final_status = "CANNOT_CONFIRM"
    elif any(status in {"CANNOT_CONFIRM", "FAILED"} for status in workload_statuses):
        final_status = "CANNOT_CONFIRM"
    elif observed_status == "READY" and all(status in {"READY", "READY_EMPTY"} for status in workload_statuses):
        final_status = "READY"
    elif observed_status == "PARTIAL" and any(status == "PARTIAL" for status in workload_statuses):
        final_status = "PARTIAL"
    else:
        errors.append(_error("StatusMismatch", "official status does not match workload statuses"))
        final_status = "CANNOT_CONFIRM"
    envelope["errors"] = errors
    if errors:
        envelope["error"] = errors[0]
    envelope["status"] = final_status
    return envelope


def _execution_metadata(request: PipelineRequest, command: list[str], environment: Mapping[str, str]) -> dict[str, Any]:
    return {
        "mode": "subprocess",
        "shell": False,
        "timeout_seconds": PIPELINE_TIMEOUT_SECONDS,
        "cwd": str(request.review_core_package_root),
        "command": list(command),
        "env": {
            "V3_SHARED_DATA_PACKAGE_ROOT": environment["V3_SHARED_DATA_PACKAGE_ROOT"],
            "V3_SHARED_DATA_STORE_ROOT": environment["V3_SHARED_DATA_STORE_ROOT"],
            "PYTHONPATH": environment["PYTHONPATH"],
        },
    }


def _wrapper_exit_code(result: Mapping[str, Any], official_exit_code: int) -> int:
    """Return a non-zero CLI result for every non-READY semantic result."""

    if official_exit_code != 0:
        return official_exit_code
    return 0 if result.get("status") == "READY" else WRAPPER_FAILURE_EXIT_CODE


def run_pipeline(
    request: PipelineRequest,
    *,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run the official module with shell disabled and return a typed envelope."""

    command = build_command(request)
    environment = build_environment(request)
    invoke = runner or subprocess.run
    try:
        completed = invoke(
            command,
            cwd=str(request.review_core_package_root),
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=PIPELINE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        envelope = _base_envelope(request)
        timeout_stderr = getattr(error, "stderr", "") or ""
        if isinstance(timeout_stderr, bytes):
            timeout_stderr = timeout_stderr.decode("utf-8", errors="replace")
        envelope["errors"] = [
            _error("OfficialPipelineTimeout", f"official pool_pipeline exceeded {PIPELINE_TIMEOUT_SECONDS}s")
        ]
        envelope["error"] = envelope["errors"][0]
        if timeout_stderr:
            envelope["stderr"] = str(timeout_stderr)[-2000:]
        envelope["official_exit_code"] = None
        envelope["exit_code"] = TIMEOUT_EXIT_CODE
        envelope["execution"] = _execution_metadata(request, command, environment)
        return envelope
    except Exception as error:
        envelope = _base_envelope(request)
        envelope["errors"] = [_error(type(error).__name__, str(error) or type(error).__name__)]
        envelope["execution"] = _execution_metadata(request, command, environment)
        envelope["official_exit_code"] = None
        envelope["exit_code"] = WRAPPER_FAILURE_EXIT_CODE
        return envelope

    exit_code = int(getattr(completed, "returncode", 1))
    official = _json_stdout(getattr(completed, "stdout", ""))
    if official is None:
        envelope = _base_envelope(request)
        envelope["errors"] = []
        if exit_code != 0:
            envelope["errors"].append(_error("OfficialPipelineExit", f"official pool_pipeline exited with code {exit_code}"))
        envelope["errors"].append(_error("OfficialOutputInvalid", "official pool_pipeline did not emit a JSON receipt"))
        envelope["error"] = envelope["errors"][0]
        if getattr(completed, "stderr", ""):
            envelope["stderr"] = str(getattr(completed, "stderr"))[-2000:]
        envelope["official_exit_code"] = exit_code
        envelope["exit_code"] = _wrapper_exit_code(envelope, exit_code)
    else:
        envelope = validate_official_result(
            official,
            request,
            exit_code=exit_code,
            stderr=str(getattr(completed, "stderr", "") or ""),
        )
        envelope["official_exit_code"] = exit_code
        envelope["exit_code"] = _wrapper_exit_code(envelope, exit_code)
    envelope["execution"] = _execution_metadata(request, command, environment)
    return envelope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-review-core-pool-pipeline")
    parser.add_argument("--review-core-package-root", required=True)
    for name in (
        "runtime-root",
        "shared-root",
        "hk-root",
        "close-root",
        "fupan-store-root",
        "stage7-store-root",
        "bundle-root",
        "shared-store-root",
        "trade-date",
        "previous-trade-date",
        "target-date",
        "calendar-path",
    ):
        parser.add_argument(f"--{name}", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = validate_request(
            review_core_package_root=args.review_core_package_root,
            runtime_root=args.runtime_root,
            shared_root=args.shared_root,
            hk_root=args.hk_root,
            close_root=args.close_root,
            fupan_store_root=args.fupan_store_root,
            stage7_store_root=args.stage7_store_root,
            bundle_root=args.bundle_root,
            shared_store_root=args.shared_store_root,
            trade_date=args.trade_date,
            previous_trade_date=args.previous_trade_date,
            target_date=args.target_date,
            calendar_path=args.calendar_path,
        )
    except WrapperError as error:
        print(json.dumps({"schema": WRAPPER_SCHEMA, "status": "CANNOT_CONFIRM", "error": _error(type(error).__name__, str(error))}, ensure_ascii=False, sort_keys=True))
        return 2
    result = run_pipeline(request)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "CalendarValidationError",
    "FrozenDateError",
    "FROZEN_PREVIOUS_TRADE_DATE",
    "FROZEN_TARGET_DATE",
    "FROZEN_TRADE_DATE",
    "PathBoundaryError",
    "PIPELINE_TIMEOUT_SECONDS",
    "PipelineRequest",
    "SAFETY_FLAGS",
    "TIMEOUT_EXIT_CODE",
    "WORKLOADS",
    "WRAPPER_FAILURE_EXIT_CODE",
    "WRAPPER_ROLE",
    "WRAPPER_SCHEMA",
    "build_command",
    "build_environment",
    "main",
    "run_pipeline",
    "validate_official_result",
    "validate_request",
]
