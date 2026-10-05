"""Bounded dynamic-date adapter for the released Review Core 21:15 pipeline.

The adapter is intentionally separate from the frozen 20260821 canary
wrapper.  It resolves the previous HK-connect trading day and the next
A-share trading day from an explicit candidate calendar, binds every package
and store root, and invokes only ``review_core.pool_pipeline`` through a
non-shell subprocess.  It does not register or call a scheduler.

The adapter is fail-closed: only a top-level ``READY`` receipt with all three
workloads in ``READY``/``READY_EMPTY`` and complete provenance returns exit 0.
``PARTIAL``, ``CANNOT_CONFIRM``, ``FAILED``, malformed, unsafe, or incomplete
receipts return exit 2.  The three trading-safety flags are always false in
the adapter envelope and must also be false in the official receipt.
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


ADAPTER_SCHEMA = "v3_5.review_core.natural_pool_pipeline_adapter.receipt.v1"
ADAPTER_ROLE = "REVIEW_CORE_POOLS_2115_NATURAL"
OFFICIAL_SCHEMA = "review_core.pool_pipeline.receipt.v1"
WORKLOADS = ("hk_close_review", "fupan_pool", "stage7_pool")
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
PROVENANCE_FIELDS = ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256")

_DATE_RE = re.compile(r"^\d{8}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_PATH_MARKERS = ("desktop", "windows")
_APP_SUPPORT_ROOT = (Path.home() / "Library" / "Application Support").resolve()
_CANDIDATE_APP_ROOT = Path(__file__).resolve().parents[1]
_CANDIDATE_ROOT = _CANDIDATE_APP_ROOT.parent.parent
_CANDIDATE_CONTRACTS_ROOT = (_CANDIDATE_APP_ROOT / "contracts").resolve()
_CANARY_ROOT = (_CANDIDATE_ROOT / "test-tmp").resolve()


class AdapterError(ValueError):
    """Base class for fail-closed adapter validation failures."""


class PathBoundaryError(AdapterError):
    """A path is outside the formal or test-only allowlist."""


class CalendarValidationError(AdapterError):
    """The candidate market calendar cannot prove the requested dates."""


class ResultValidationError(AdapterError):
    """The official Review Core JSON receipt is malformed or unsafe."""


# Friendly compatibility names used by the frozen wrapper and by callers that
# treat calendar/date validation as one fail-closed category.
CalendarError = CalendarValidationError
FrozenDateError = CalendarValidationError


@dataclass(frozen=True)
class PipelineRequest:
    trade_date: str
    previous_trade_date: str
    target_date: str
    calendar_path: Path
    calendar_sha256: str
    review_core_package_root: Path
    shared_package_root: Path
    shared_store_root: Path
    runtime_root: Path
    hk_root: Path
    close_root: Path
    fupan_store_root: Path
    stage7_store_root: Path
    bundle_root: Path

    @property
    def shared_root(self) -> Path:
        """Compatibility alias for the official module's ``--shared-root``."""

        return self.shared_package_root


def _error(error_type: str, message: str) -> dict[str, str]:
    return {"type": error_type, "message": message}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


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
    _reject_symlink_components(path, label)
    try:
        return str(path.resolve(strict=False))
    except OSError as error:
        raise PathBoundaryError(f"{label} cannot be resolved") from error


def _path(value: Path | str, label: str) -> Path:
    return Path(_as_text_path(value, label))


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _reject_symlink_components(path: Path, label: str) -> None:
    """Reject leaf and ancestor symlinks before canonicalizing the path."""

    current = path
    while True:
        try:
            if current.is_symlink():
                raise PathBoundaryError(f"{label} rejects symlink component: {current}")
        except OSError as error:
            raise PathBoundaryError(f"{label} symlink check failed: {current}") from error
        parent = current.parent
        if parent == current:
            return
        current = parent


def _require_under(path: Path, roots: Sequence[Path], label: str) -> None:
    if not any(_under(path, root) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise PathBoundaryError(f"{label} is outside allowed roots: {allowed}")


def _require_package_root(path: Path, label: str) -> None:
    _require_under(path, (_APP_SUPPORT_ROOT, _CANARY_ROOT), label)


def _require_write_root(path: Path, label: str) -> None:
    # Formal writes are confined to Application Support.  The only other
    # route is the explicit Documents candidate canary/test root.
    _require_under(path, (_APP_SUPPORT_ROOT, _CANARY_ROOT), label)


def _require_calendar_root(path: Path, label: str) -> None:
    _require_under(
        path,
        (_APP_SUPPORT_ROOT, _CANDIDATE_CONTRACTS_ROOT, _CANARY_ROOT),
        label,
    )


def _validate_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise CalendarValidationError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise CalendarValidationError(f"{label} must be a real calendar date") from error
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
    if not isinstance(payload.get("schema_version"), str) or not str(
        payload.get("schema_version")
    ).strip():
        raise CalendarValidationError("calendar schema_version is missing")
    if isinstance(payload.get("year"), bool) or not isinstance(payload.get("year"), int):
        raise CalendarValidationError("calendar year is missing")
    if not isinstance(payload.get("timezone"), str) or not str(
        payload.get("timezone")
    ).strip():
        raise CalendarValidationError("calendar timezone is missing")
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        raise CalendarValidationError("calendar markets are missing")
    for market in ("a_share", "hk_connect_southbound"):
        if not isinstance(markets.get(market), Mapping):
            raise CalendarValidationError(f"calendar market is missing: {market}")
    for market, raw_config in markets.items():
        if not isinstance(raw_config, Mapping):
            raise CalendarValidationError(f"calendar market is invalid: {market}")
        config = raw_config
        periods = config.get("holiday_periods", [])
        explicit = config.get("trading_dates", config.get("open_dates"))
        if periods is None:
            periods = []
        if not isinstance(periods, list):
            raise CalendarValidationError(f"calendar holiday periods are invalid: {market}")
        if explicit is not None and not isinstance(explicit, list):
            raise CalendarValidationError(f"calendar trading dates are invalid: {market}")
        if explicit is None and "holiday_periods" not in config:
            raise CalendarValidationError(f"calendar dates are missing: {market}")
        for index, period in enumerate(periods):
            if not isinstance(period, Mapping):
                raise CalendarValidationError(f"calendar holiday period is invalid: {market}[{index}]")
            start = _validate_date(period.get("start"), f"{market}.holiday.start")
            end = _validate_date(period.get("end"), f"{market}.holiday.end")
            if start > end:
                raise CalendarValidationError(f"calendar holiday range is invalid: {market}")
        if explicit is not None:
            for index, item in enumerate(explicit):
                _validate_date(item, f"{market}.trading_dates[{index}]")
        dependencies = config.get("derives_from", [])
        if dependencies is None:
            dependencies = []
        if not isinstance(dependencies, list):
            raise CalendarValidationError(f"calendar dependencies are invalid: {market}")
        for dependency in dependencies:
            if not isinstance(dependency, str) or not isinstance(markets.get(dependency), Mapping):
                raise CalendarValidationError(f"calendar dependency is unknown: {market}->{dependency}")
    return dict(payload), _sha256_bytes(raw)


def _market_open(
    calendar: Mapping[str, Any],
    day: str,
    market: str,
    seen: set[str] | None = None,
) -> bool:
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
    if explicit is not None and day not in {str(item) for item in explicit}:
        return False
    if value.weekday() >= 5:
        return False
    periods = config.get("holiday_periods", [])
    for period in periods:
        start = _date(_validate_date(period.get("start"), "holiday.start"))
        end = _date(_validate_date(period.get("end"), "holiday.end"))
        if start <= value <= end:
            return False
    dependencies = config.get("derives_from", []) or []
    if any(not _market_open(calendar, day, str(dependency), active) for dependency in dependencies):
        return False
    return True


def resolve_adjacent_dates(
    trade_date: str,
    calendar: Mapping[str, Any],
) -> tuple[str, str]:
    """Return (previous HK-connect day, next A-share day)."""

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


def resolve_trade_dates(
    trade_date: str | None,
    *,
    previous_trade_date: str | None = None,
    target_date: str | None = None,
    calendar_path: Path | str | None = None,
) -> tuple[str, str, str, str, str]:
    """Resolve and verify current, previous, and next dates from a calendar."""

    if trade_date is None:
        raise CalendarValidationError("trade_date is required")
    if calendar_path is None:
        raise CalendarValidationError("calendar_path is required")
    calendar_file = _path(calendar_path, "calendar_path")
    _require_calendar_root(calendar_file, "calendar_path")
    trade = _validate_date(trade_date, "trade_date")
    supplied_previous = (
        _validate_date(previous_trade_date, "previous_trade_date")
        if previous_trade_date is not None
        else None
    )
    supplied_target = (
        _validate_date(target_date, "target_date") if target_date is not None else None
    )
    calendar, digest = _read_calendar(calendar_file)
    if not _market_open(calendar, trade, "a_share"):
        raise CalendarValidationError(f"trade date is not open: {trade}")
    expected_previous, expected_target = resolve_adjacent_dates(trade, calendar)
    if supplied_previous is not None and supplied_previous != expected_previous:
        raise CalendarValidationError(
            f"previous_trade_date mismatch: {supplied_previous} != {expected_previous}"
        )
    if supplied_target is not None and supplied_target != expected_target:
        raise CalendarValidationError(
            f"target_date mismatch: {supplied_target} != {expected_target}"
        )
    previous = supplied_previous or expected_previous
    target = supplied_target or expected_target
    if not (previous < trade < target):
        raise CalendarValidationError("date order must be previous < trade < target")
    if not _market_open(calendar, previous, "hk_connect_southbound"):
        raise CalendarValidationError(f"previous trade date is not open: {previous}")
    if not _market_open(calendar, target, "a_share"):
        raise CalendarValidationError(f"target date is not open: {target}")
    return trade, previous, target, str(calendar_file), digest


def _package_module_path(package: Path) -> Path:
    return package / "review_core" / "pool_pipeline.py"


def validate_request(
    *,
    trade_date: str,
    calendar_path: Path | str,
    review_core_package_root: Path | str,
    shared_package_root: Path | str,
    shared_store_root: Path | str,
    runtime_root: Path | str,
    hk_root: Path | str,
    close_root: Path | str,
    fupan_store_root: Path | str,
    stage7_store_root: Path | str,
    bundle_root: Path | str,
    previous_trade_date: str | None = None,
    target_date: str | None = None,
) -> PipelineRequest:
    """Validate all explicit CLI boundaries before importing Review Core."""

    calendar = _path(calendar_path, "calendar_path")
    _require_calendar_root(calendar, "calendar_path")
    trade, previous, target, calendar_text, calendar_sha = resolve_trade_dates(
        trade_date,
        previous_trade_date=previous_trade_date,
        target_date=target_date,
        calendar_path=calendar,
    )

    package = _path(review_core_package_root, "review_core_package_root")
    _require_package_root(package, "review_core_package_root")
    module_path = _package_module_path(package)
    if not module_path.is_file():
        raise PathBoundaryError(f"official Review Core pool_pipeline is missing: {module_path}")
    try:
        if not _under(module_path, package):
            raise PathBoundaryError("review_core pool_pipeline escapes package root")
    except OSError as error:
        raise PathBoundaryError("review_core pool_pipeline cannot be resolved") from error

    shared_package = _path(shared_package_root, "shared_package_root")
    _require_package_root(shared_package, "shared_package_root")

    values = {
        "shared_store_root": _path(shared_store_root, "shared_store_root"),
        "runtime_root": _path(runtime_root, "runtime_root"),
        "hk_root": _path(hk_root, "hk_root"),
        "close_root": _path(close_root, "close_root"),
        "fupan_store_root": _path(fupan_store_root, "fupan_store_root"),
        "stage7_store_root": _path(stage7_store_root, "stage7_store_root"),
        "bundle_root": _path(bundle_root, "bundle_root"),
    }
    for label, value in values.items():
        _require_write_root(value, label)

    # resolve_trade_dates read the same canonical path after boundary
    # validation, so no unbounded calendar can influence the date contract.
    if str(calendar) != calendar_text:
        raise CalendarValidationError("calendar path changed during validation")

    return PipelineRequest(
        trade_date=trade,
        previous_trade_date=previous,
        target_date=target,
        calendar_path=calendar,
        calendar_sha256=calendar_sha,
        review_core_package_root=package,
        shared_package_root=shared_package,
        shared_store_root=values["shared_store_root"],
        runtime_root=values["runtime_root"],
        hk_root=values["hk_root"],
        close_root=values["close_root"],
        fupan_store_root=values["fupan_store_root"],
        stage7_store_root=values["stage7_store_root"],
        bundle_root=values["bundle_root"],
    )


def build_command(request: PipelineRequest, *, python_executable: str | None = None) -> list[str]:
    """Build argv for the official module without shell interpolation."""

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
        str(request.shared_store_root),
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


def build_environment(
    request: PipelineRequest,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Bind package/store roots and remove inherited checkout import paths."""

    environment = dict(base_env if base_env is not None else os.environ)
    environment["PYTHONPATH"] = str(request.review_core_package_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["V3_SHARED_DATA_PACKAGE_ROOT"] = str(request.shared_package_root)
    # STORE_ROOT is the explicit adapter contract; the V3_SHARED_DATA alias is
    # retained because the released Review Core readers consume it directly.
    environment["STORE_ROOT"] = str(request.shared_store_root)
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
    # Released workloads publish provenance as sibling fields.  Accepting a
    # nested provenance object as a read-only compatibility seam is harmless,
    # but normalize it before validating so a missing field cannot be hidden.
    nested = workload.get("provenance")
    for name in PROVENANCE_FIELDS:
        value = workload.get(name)
        if not str(value or "").strip() and isinstance(nested, Mapping):
            value = nested.get(name)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def _copy_provenance_fields(item: dict[str, Any]) -> None:
    nested = item.get("provenance")
    if not isinstance(nested, Mapping):
        return
    for name in PROVENANCE_FIELDS:
        if not str(item.get(name) or "").strip() and str(nested.get(name) or "").strip():
            item[name] = nested[name]


def _base_envelope(request: PipelineRequest) -> dict[str, Any]:
    return {
        "schema": ADAPTER_SCHEMA,
        "schema_version": ADAPTER_SCHEMA,
        "role": ADAPTER_ROLE,
        "trade_date": request.trade_date,
        "previous_trade_date": request.previous_trade_date,
        "target_date": request.target_date,
        "calendar": {
            "path": str(request.calendar_path),
            "sha256": request.calendar_sha256,
        },
        "roots": {
            "review_core_package_root": str(request.review_core_package_root),
            "shared_package_root": str(request.shared_package_root),
            "shared_store_root": str(request.shared_store_root),
            "runtime_root": str(request.runtime_root),
            "hk_root": str(request.hk_root),
            "close_root": str(request.close_root),
            "fupan_store_root": str(request.fupan_store_root),
            "stage7_store_root": str(request.stage7_store_root),
            "bundle_root": str(request.bundle_root),
        },
        "run_id": "",
        "receipt_path": "",
        "status": "CANNOT_CONFIRM",
        "overall_status": "CANNOT_CONFIRM",
        "workloads": {},
        "errors": [],
        **{name: False for name in SAFETY_FLAGS},
    }


def validate_official_result(
    official: Mapping[str, Any],
    request: PipelineRequest,
    *,
    official_exit_code: int | None = None,
    exit_code: int | None = None,
    stderr: str = "",
) -> dict[str, Any]:
    """Validate the official receipt and return the adapter envelope."""

    if official_exit_code is None:
        official_exit_code = int(exit_code if exit_code is not None else 0)
    envelope = _base_envelope(request)
    errors: list[dict[str, str]] = []
    observed_status = _status(official.get("status"))
    official_schema = official.get("schema") or official.get("schema_version")
    if official_schema != OFFICIAL_SCHEMA:
        errors.append(_error("InvalidOfficialSchema", "official receipt schema is unsupported"))
    if official.get("trade_date") not in (None, request.trade_date):
        errors.append(_error("DateIdentityMismatch", "official trade_date does not match request"))
    if official.get("previous_trade_date") not in (None, request.previous_trade_date):
        errors.append(_error("DateIdentityMismatch", "official previous_trade_date does not match request"))
    if official.get("target_date") not in (None, request.target_date):
        errors.append(_error("DateIdentityMismatch", "official target_date does not match request"))
    if official_exit_code != 0:
        errors.append(_error("OfficialPipelineExit", f"official pool_pipeline exited with code {official_exit_code}"))
    if stderr.strip():
        envelope["stderr"] = stderr[-2000:]

    if observed_status not in {"READY", "READY_EMPTY", "PARTIAL", "CANNOT_CONFIRM", "FAILED"}:
        errors.append(_error("InvalidStatus", "official status is missing or unsupported"))

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
        _copy_provenance_fields(item)
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
        if not _has_provenance(item):
            errors.append(_error("MissingProvenance", name))
            if item_status in {"READY", "READY_EMPTY"}:
                item["observed_status"] = item_status
                item["status"] = "CANNOT_CONFIRM"
                item["error"] = _error("MissingProvenance", f"workload lacks provenance: {name}")
        workloads[name] = item
    envelope["workloads"] = workloads

    run_id_value = official.get("run_id") or official.get("run")
    if not isinstance(run_id_value, str) or not run_id_value.strip():
        errors.append(_error("MissingRunProvenance", "official run_id is missing"))
    envelope["run_id"] = str(run_id_value or "")
    envelope["receipt_path"] = str(official.get("receipt_path") or "")
    envelope["official_status"] = observed_status or "CANNOT_CONFIRM"
    envelope["official_result"] = dict(official)

    workload_statuses = [str(workloads[name].get("status") or "CANNOT_CONFIRM") for name in WORKLOADS]
    all_ready = all(status in {"READY", "READY_EMPTY"} for status in workload_statuses)
    if observed_status == "READY" and not all_ready:
        errors.append(_error("StatusMismatch", "READY official status requires every workload READY"))
    if observed_status == "PARTIAL" and not any(status == "PARTIAL" for status in workload_statuses):
        errors.append(_error("StatusMismatch", "PARTIAL official status requires a PARTIAL workload"))

    if errors:
        final_status = "CANNOT_CONFIRM"
    elif observed_status == "READY" and all_ready:
        final_status = "READY"
    elif observed_status == "PARTIAL":
        final_status = "PARTIAL"
    else:
        final_status = "CANNOT_CONFIRM"
    envelope["status"] = final_status
    envelope["overall_status"] = final_status
    envelope["errors"] = errors
    if errors:
        envelope["error"] = errors[0]
    return envelope


def _execution_metadata(
    request: PipelineRequest,
    command: list[str],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "mode": "subprocess",
        "shell": False,
        "cwd": str(request.review_core_package_root),
        "command": list(command),
        "env": {
            "PYTHONPATH": environment["PYTHONPATH"],
            "V3_SHARED_DATA_PACKAGE_ROOT": environment["V3_SHARED_DATA_PACKAGE_ROOT"],
            "STORE_ROOT": environment["STORE_ROOT"],
            "V3_SHARED_DATA_STORE_ROOT": environment["V3_SHARED_DATA_STORE_ROOT"],
        },
    }


def run_pipeline(
    request: PipelineRequest,
    *,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Invoke the released module once and return a typed adapter envelope."""

    command = build_command(request)
    environment = build_environment(request)
    invoke = runner or subprocess.run
    execution = _execution_metadata(request, command, environment)
    try:
        completed = invoke(
            command,
            cwd=str(request.review_core_package_root),
            env=environment,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as error:
        envelope = _base_envelope(request)
        envelope["errors"] = [_error(type(error).__name__, str(error) or type(error).__name__)]
        envelope["error"] = envelope["errors"][0]
        envelope["execution"] = execution
        envelope["official_exit_code"] = None
        envelope["exit_code"] = 2
        return envelope

    child_exit_code = int(getattr(completed, "returncode", 1))
    official = _json_stdout(getattr(completed, "stdout", ""))
    if official is None:
        envelope = _base_envelope(request)
        errors: list[dict[str, str]] = []
        if child_exit_code != 0:
            errors.append(_error("OfficialPipelineExit", f"official pool_pipeline exited with code {child_exit_code}"))
        errors.append(_error("OfficialOutputInvalid", "official pool_pipeline did not emit a JSON receipt"))
        envelope["errors"] = errors
        envelope["error"] = errors[0]
        if getattr(completed, "stderr", ""):
            envelope["stderr"] = str(getattr(completed, "stderr"))[-2000:]
        envelope["execution"] = execution
        envelope["official_exit_code"] = child_exit_code
        envelope["exit_code"] = 2
        return envelope

    envelope = validate_official_result(
        official,
        request,
        official_exit_code=child_exit_code,
        stderr=str(getattr(completed, "stderr", "") or ""),
    )
    envelope["execution"] = execution
    envelope["official_exit_code"] = child_exit_code
    envelope["exit_code"] = 0 if envelope["status"] == "READY" else 2
    return envelope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-review-core-natural-pool-pipeline")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--calendar-path", required=True)
    parser.add_argument("--review-core-package-root", required=True)
    parser.add_argument("--shared-package-root", required=True)
    parser.add_argument("--shared-store-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--hk-root", required=True)
    parser.add_argument("--close-root", required=True)
    parser.add_argument("--fupan-store-root", required=True)
    parser.add_argument("--stage7-store-root", required=True)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--previous-trade-date", required=False)
    parser.add_argument("--target-date", required=False)
    return parser


def _failure_envelope(error: Exception) -> dict[str, Any]:
    return {
        "schema": ADAPTER_SCHEMA,
        "schema_version": ADAPTER_SCHEMA,
        "role": ADAPTER_ROLE,
        "status": "CANNOT_CONFIRM",
        "overall_status": "CANNOT_CONFIRM",
        "exit_code": 2,
        "error": _error(type(error).__name__, str(error) or type(error).__name__),
        "errors": [_error(type(error).__name__, str(error) or type(error).__name__)],
        **{name: False for name in SAFETY_FLAGS},
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = validate_request(
            trade_date=args.trade_date,
            calendar_path=args.calendar_path,
            review_core_package_root=args.review_core_package_root,
            shared_package_root=args.shared_package_root,
            shared_store_root=args.shared_store_root,
            runtime_root=args.runtime_root,
            hk_root=args.hk_root,
            close_root=args.close_root,
            fupan_store_root=args.fupan_store_root,
            stage7_store_root=args.stage7_store_root,
            bundle_root=args.bundle_root,
            previous_trade_date=args.previous_trade_date,
            target_date=args.target_date,
        )
    except AdapterError as error:
        print(json.dumps(_failure_envelope(error), ensure_ascii=False, sort_keys=True))
        return 2
    result = run_pipeline(request)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result.get("exit_code", 2))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "ADAPTER_ROLE",
    "ADAPTER_SCHEMA",
    "AdapterError",
    "CalendarError",
    "CalendarValidationError",
    "FrozenDateError",
    "OFFICIAL_SCHEMA",
    "PathBoundaryError",
    "PipelineRequest",
    "ResultValidationError",
    "SAFETY_FLAGS",
    "WORKLOADS",
    "build_command",
    "build_environment",
    "main",
    "resolve_adjacent_dates",
    "resolve_trade_dates",
    "run_pipeline",
    "validate_official_result",
    "validate_request",
]
