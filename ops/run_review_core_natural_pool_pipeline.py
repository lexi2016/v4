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

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



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
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __as_text_path_body as _v4_impl
    return _v4_impl(globals(), value, label)


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
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __reject_symlink_components_body as _v4_impl
    return _v4_impl(globals(), path, label)


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
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __read_calendar_body as _v4_impl
    return _v4_impl(globals(), path)


def _market_open(
    calendar: Mapping[str, Any],
    day: str,
    market: str,
    seen: set[str] | None = None,
) -> bool:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __market_open_body as _v4_impl
    return _v4_impl(globals(), calendar, day, market, seen)


def resolve_adjacent_dates(
    trade_date: str,
    calendar: Mapping[str, Any],
) -> tuple[str, str]:
    """Return (previous HK-connect day, next A-share day)."""
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _resolve_adjacent_dates_body as _v4_impl
    return _v4_impl(globals(), trade_date, calendar)


def resolve_trade_dates(
    trade_date: str | None,
    *,
    previous_trade_date: str | None = None,
    target_date: str | None = None,
    calendar_path: Path | str | None = None,
) -> tuple[str, str, str, str, str]:
    """Resolve and verify current, previous, and next dates from a calendar."""
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _resolve_trade_dates_body as _v4_impl
    return _v4_impl(globals(), trade_date, previous_trade_date=previous_trade_date, target_date=target_date, calendar_path=calendar_path)


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
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _validate_request_body as _v4_impl
    return _v4_impl(globals(), trade_date=trade_date, calendar_path=calendar_path, review_core_package_root=review_core_package_root, shared_package_root=shared_package_root, shared_store_root=shared_store_root, runtime_root=runtime_root, hk_root=hk_root, close_root=close_root, fupan_store_root=fupan_store_root, stage7_store_root=stage7_store_root, bundle_root=bundle_root, previous_trade_date=previous_trade_date, target_date=target_date)


def build_command(request: PipelineRequest, *, python_executable: str | None = None) -> list[str]:
    """Build argv for the official module without shell interpolation."""
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _build_command_body as _v4_impl
    return _v4_impl(globals(), request, python_executable=python_executable)


def build_environment(
    request: PipelineRequest,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Bind package/store roots and remove inherited checkout import paths."""
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _build_environment_body as _v4_impl
    return _v4_impl(globals(), request, base_env=base_env)


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
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __has_provenance_body as _v4_impl
    return _v4_impl(globals(), workload)


def _copy_provenance_fields(item: dict[str, Any]) -> None:
    nested = item.get("provenance")
    if not isinstance(nested, Mapping):
        return
    for name in PROVENANCE_FIELDS:
        if not str(item.get(name) or "").strip() and str(nested.get(name) or "").strip():
            item[name] = nested[name]


def _base_envelope(request: PipelineRequest) -> dict[str, Any]:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __base_envelope_body as _v4_impl
    return _v4_impl(globals(), request)


def validate_official_result(
    official: Mapping[str, Any],
    request: PipelineRequest,
    *,
    official_exit_code: int | None = None,
    exit_code: int | None = None,
    stderr: str = "",
) -> dict[str, Any]:
    """Validate the official receipt and return the adapter envelope."""
    from ops._run_review_core_natural_pool_pipeline_parts.official_validation import _validate_official_result_body as _v4_impl
    return _v4_impl(globals(), official, request, official_exit_code=official_exit_code, exit_code=exit_code, stderr=stderr)


def _execution_metadata(
    request: PipelineRequest,
    command: list[str],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __execution_metadata_body as _v4_impl
    return _v4_impl(globals(), request, command, environment)


def run_pipeline(
    request: PipelineRequest,
    *,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Invoke the released module once and return a typed adapter envelope."""
    from ops._run_review_core_natural_pool_pipeline_parts.pipeline_execution import _run_pipeline_body as _v4_impl
    return _v4_impl(globals(), request, runner=runner)


def _parser() -> argparse.ArgumentParser:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __parser_body as _v4_impl
    return _v4_impl(globals())


def _failure_envelope(error: Exception) -> dict[str, Any]:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import __failure_envelope_body as _v4_impl
    return _v4_impl(globals(), error)


def main(argv: list[str] | None = None) -> int:
    from ops._run_review_core_natural_pool_pipeline_parts.cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


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
