"""Strict validation shared by the A research-panel receipt consumers."""

from __future__ import annotations

import hashlib
import math
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from .macos_research_panel_daily_common import SAFETY_FLAGS, SnapshotGateError, _date


_SCHEMA = "v3.macos.research_panel_receipt.v1"
_PARTIAL_STATUSES = frozenset({"PARTIAL", "PARTIAL_WITH_ROWS", "REBUILD_REQUIRED"})
_COUNT_FIELDS = (
    "row_count",
    "accepted_target_date_file_count",
    "accepted_count",
    "quarantine_count",
    "target_count",
)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _combined_artifact_sha(selector_sha: str, backtest_sha: str) -> str:
    return hashlib.sha256(
        f"selector:{selector_sha}\nbacktest:{backtest_sha}\n".encode("ascii")
    ).hexdigest()


def _binding_path(value: Any, *, base: Any = None) -> Any:
    """Resolve a binding path without accepting symlinked or ambiguous paths."""
    if isinstance(value, os.PathLike):
        raw_value = os.fspath(value)
    elif isinstance(value, str):
        raw_value = value.strip()
    else:
        return None
    if not raw_value:
        return None
    try:
        raw = Path(raw_value).expanduser()
        if not raw.is_absolute():
            if base is None:
                return None
            raw = Path(base) / raw
        lexical = Path(os.path.abspath(os.fspath(raw)))
        resolved = raw.resolve(strict=True)
        if lexical != resolved:
            return None
        identity = os.lstat(lexical)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
        return None
    return lexical


def _regular_bytes(path: Any) -> bytes | None:
    """Read one regular file descriptor and reject identity changes."""
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd: int | None = os.open(os.fspath(path), flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                return None
            with os.fdopen(fd, "rb") as stream:
                fd = None
                return stream.read()
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    except (OSError, TypeError, ValueError):
        return None


def _pointer_target(pointer: Any) -> Any:
    pointer_path = _binding_path(pointer)
    if pointer_path is None:
        return None
    raw = _regular_bytes(pointer_path)
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        return None
    if not text or "\n" in text or "\r" in text:
        return None
    return _binding_path(text, base=pointer_path.parent)


def _artifact_binding_valid(
    payload: Mapping[str, Any],
    *,
    selector_pointer: Any = None,
    backtest_pointer: Any = None,
    pointer_context: Mapping[str, Any] | None = None,
) -> bool:
    if pointer_context is not None:
        selector_pointer = selector_pointer or pointer_context.get("selector_pointer") or pointer_context.get("selector")
        backtest_pointer = backtest_pointer or pointer_context.get("backtest_pointer") or pointer_context.get("backtest")
    fields = ("selector", "selector_sha256", "backtest", "backtest_sha256")
    has_binding = any(field in payload for field in fields)
    if not has_binding:
        # Existing direct callers that only know the selector pointer retain
        # their legacy tuple behavior; production gate/scheduler pass both
        # pointers and therefore require the full artifact binding below.
        return selector_pointer is None or backtest_pointer is None
    if selector_pointer is None or backtest_pointer is None or any(field not in payload for field in fields):
        return False
    selector_path = _binding_path(payload.get("selector"))
    backtest_path = _binding_path(payload.get("backtest"))
    selector_current = _pointer_target(selector_pointer)
    backtest_current = _pointer_target(backtest_pointer)
    if None in (selector_path, backtest_path, selector_current, backtest_current):
        return False
    if selector_path != selector_current or backtest_path != backtest_current:
        return False
    selector_bytes = _regular_bytes(selector_path)
    backtest_bytes = _regular_bytes(backtest_path)
    if selector_bytes is None or backtest_bytes is None:
        return False
    selector_sha = hashlib.sha256(selector_bytes).hexdigest()
    backtest_sha = hashlib.sha256(backtest_bytes).hexdigest()
    if payload.get("selector_sha256") != selector_sha or payload.get("backtest_sha256") != backtest_sha:
        return False
    return payload.get("sha256") == _combined_artifact_sha(selector_sha, backtest_sha)


def _nested_rebuild(value: Any) -> bool:
    if isinstance(value, Mapping):
        if str(value.get("authority_status") or "").upper() == "REBUILD_REQUIRED":
            return True
        if str(value.get("status") or "").upper() == "REBUILD_REQUIRED":
            return True
        if value.get("rebuild_candidates_promoted") is False:
            return True
        return any(_nested_rebuild(child) for child in value.values())
    if isinstance(value, list):
        return any(_nested_rebuild(child) for child in value)
    return False


def _readiness_values(value: Any, field: str) -> list[bool]:
    found: list[bool] = []
    if isinstance(value, Mapping):
        if field in value:
            found.append(value[field] is True)
        for child in value.values():
            found.extend(_readiness_values(child, field))
    elif isinstance(value, list):
        for child in value:
            found.extend(_readiness_values(child, field))
    return found


def _reconciliation_values(value: Any) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        nested = value.get("reconciliation")
        if isinstance(nested, Mapping):
            found.append(nested)
        for child in value.values():
            found.extend(_reconciliation_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_reconciliation_values(child))
    return found


def _reconciliation_signature(value: Mapping[str, Any]) -> tuple[int, int, int] | None:
    fields = tuple(value.get(name) for name in ("target_count", "accepted_count", "quarantine_count"))
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in fields):
        return None
    return fields  # type: ignore[return-value]


def validate_a_receipt(
    payload: Mapping[str, Any] | None,
    target_date: str,
    *,
    selector_ready: bool = True,
    selector_pointer: Any = None,
    backtest_pointer: Any = None,
    pointer_context: Mapping[str, Any] | None = None,
) -> str | None:
    """Return ``READY``/``PARTIAL_WITH_ROWS`` only for a strict A receipt."""
    if not isinstance(payload, Mapping) or not selector_ready:
        return None
    target = _date(target_date)
    if (
        payload.get("schema_version") != _SCHEMA
        or payload.get("lane") != "A"
        or payload.get("target_date") != target
        or not _is_sha256(payload.get("sha256"))
        or any(payload.get(name) is not False for name in SAFETY_FLAGS)
    ):
        return None

    selector_sha = payload.get("selector_sha256")
    backtest_sha = payload.get("backtest_sha256")
    if selector_sha is not None or backtest_sha is not None:
        if (
            not _is_sha256(selector_sha)
            or not _is_sha256(backtest_sha)
            or payload["sha256"] != _combined_artifact_sha(selector_sha, backtest_sha)
        ):
            return None
    if not _artifact_binding_valid(
        payload,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        pointer_context=pointer_context,
    ):
        return None

    counts: dict[str, int] = {}
    for field in _COUNT_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts[field] = value
    if any(counts[field] <= 0 for field in ("row_count", "accepted_target_date_file_count", "accepted_count", "target_count")):
        return None
    if counts["accepted_target_date_file_count"] != counts["accepted_count"]:
        return None
    if counts["accepted_count"] + counts["quarantine_count"] != counts["target_count"]:
        return None

    coverage = payload.get("coverage_rate")
    if isinstance(coverage, bool) or not isinstance(coverage, int | float) or not _finite(coverage):
        return None
    expected_coverage = counts["accepted_count"] / counts["target_count"]
    if not 0.0 < float(coverage) <= 1.0 or not math.isclose(float(coverage), expected_coverage, rel_tol=0.0, abs_tol=1e-9):
        return None

    reconciliations = _reconciliation_values(payload)
    if not reconciliations:
        return None
    expected_signature = (
        counts["target_count"],
        counts["accepted_count"],
        counts["quarantine_count"],
    )
    for reconciliation in reconciliations:
        if _reconciliation_signature(reconciliation) != expected_signature:
            return None
        symbols = reconciliation.get("symbols")
        if symbols is not None and (not isinstance(symbols, list) or len(symbols) != counts["target_count"]):
            return None

    readiness = _readiness_values(payload, "selector_pointer_ready")
    if readiness and not all(readiness):
        return None
    backtest = _readiness_values(payload, "backtest_pointer_ready")
    if not backtest or not all(backtest):
        return None

    status = str(payload.get("status") or "").upper()
    rebuilt = _nested_rebuild(payload)
    if status == "READY":
        return None if rebuilt else "READY"
    if status in _PARTIAL_STATUSES:
        return "PARTIAL_WITH_ROWS" if rebuilt else None
    return None


def a_receipt_readiness(
    payload: Mapping[str, Any] | None,
    target_date: str,
    *,
    selector_ready: bool = True,
    selector_pointer: Any = None,
    backtest_pointer: Any = None,
    pointer_context: Mapping[str, Any] | None = None,
) -> tuple[bool, bool]:
    """Return the legacy gate tuple while using the strict validator."""
    status = validate_a_receipt(
        payload,
        target_date,
        selector_ready=selector_ready,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        pointer_context=pointer_context,
    )
    ready = status == "READY"
    return ready, ready


def build_a_lane_outcome(
    sync: Mapping[str, Any],
    formula: Mapping[str, Any],
    target: str,
    bootstrap: Any,
) -> dict[str, Any]:
    """Combine exact A sync/formula authority into the dated lane receipt."""
    sync_authority_status = str(sync.get("authority_status") or sync.get("status") or "").upper()
    formula_authority = formula.get("authority") if isinstance(formula.get("authority"), Mapping) else {}
    formula_rebuild = _nested_rebuild(formula_authority) or any(
        str(formula.get(name) or "").upper() == "REBUILD_REQUIRED"
        for name in ("authority_status", "status")
    )
    formula_authority_status = (
        "REBUILD_REQUIRED"
        if formula_rebuild
        else str(formula_authority.get("authority_status") or formula_authority.get("status") or "").upper()
    )

    if "selector_increment_rows" in formula_authority:
        raw_row_count = formula_authority.get("selector_increment_rows")
    elif formula.get("already_current") is True:
        # Reuse has no fresh formula summary. Count the bound selector bytes;
        # accepted input files can include symbols absent from the selector.
        selector_path = _binding_path(formula.get("selector"))
        selector_bytes = _regular_bytes(selector_path) if selector_path is not None else None
        if selector_bytes is None or hashlib.sha256(selector_bytes).hexdigest() != formula.get("selector_sha256"):
            raise SnapshotGateError("A reused selector row_count has no valid artifact binding")
        try:
            import io
            import pyarrow.parquet as pq

            dates = pq.read_table(io.BytesIO(selector_bytes), columns=["trade_date"]).column("trade_date").to_pylist()
            exact_target = _date(target)
            raw_row_count = sum(str(value).replace("-", "").replace("/", "") == exact_target for value in dates)
        except Exception as error:
            raise SnapshotGateError("A reused selector exact-date row_count cannot be established") from error
    else:
        raise SnapshotGateError("A selector row_count metric is missing")
    if isinstance(raw_row_count, bool) or not isinstance(raw_row_count, int) or raw_row_count < 0:
        raise SnapshotGateError("A row_count metric is invalid")
    row_count = raw_row_count

    if "coverage_rate" in formula:
        raw_coverage_rate = formula.get("coverage_rate")
    elif "coverage_rate" in formula_authority:
        raw_coverage_rate = formula_authority.get("coverage_rate")
    elif "coverage_rate" in sync:
        raw_coverage_rate = sync.get("coverage_rate")
    else:
        accepted = sync.get("accepted_target_date_file_count")
        target_count = sync.get("target_count")
        if target_count is None and isinstance(sync.get("reconciliation"), Mapping):
            target_count = sync["reconciliation"].get("target_count")
        if target_count is None:
            target_count = sync.get("target_date_file_count")
        if (
            isinstance(accepted, int)
            and not isinstance(accepted, bool)
            and accepted >= 0
            and isinstance(target_count, int)
            and not isinstance(target_count, bool)
            and target_count > 0
        ):
            raw_coverage_rate = accepted / target_count
        else:
            raise SnapshotGateError("A coverage_rate metric is missing; cannot confirm exact coverage")
    if (
        isinstance(raw_coverage_rate, bool)
        or not isinstance(raw_coverage_rate, int | float)
        or not _finite(raw_coverage_rate)
        or not 0.0 <= float(raw_coverage_rate) <= 1.0
    ):
        raise SnapshotGateError("A coverage_rate metric is invalid")
    coverage_rate = float(raw_coverage_rate)

    if sync_authority_status == "REBUILD_REQUIRED" and row_count <= 0:
        raise SnapshotGateError("A partial sync has no accepted exact-date rows")
    if sync_authority_status == "REBUILD_REQUIRED":
        accepted_target_files = sync.get("accepted_target_date_file_count")
        if isinstance(accepted_target_files, bool) or not isinstance(accepted_target_files, int) or accepted_target_files <= 0:
            raise SnapshotGateError("A partial sync has no accepted exact-date rows")

    cannot_confirm = sync.get("cannot_confirm")
    if cannot_confirm is None and sync_authority_status == "REBUILD_REQUIRED":
        cannot_confirm = [str(sync.get("reason") or "A_SYNC_AUTHORITY_REBUILD_REQUIRED")]
    status = "PARTIAL" if sync_authority_status == "REBUILD_REQUIRED" or formula_rebuild else "READY"
    if status == "PARTIAL":
        accepted_target_files = sync.get("accepted_target_date_file_count")
        if isinstance(accepted_target_files, bool) or not isinstance(accepted_target_files, int) or accepted_target_files <= 0 or row_count <= 0:
            raise SnapshotGateError("A partial lane requires accepted exact-date rows")
    authority_status = "REBUILD_REQUIRED" if status == "PARTIAL" else formula_authority_status or sync_authority_status
    reason = (
        "A_FORMULA_AUTHORITY_REBUILD_REQUIRED"
        if formula_rebuild
        else "A_SYNC_AUTHORITY_REBUILD_REQUIRED"
        if sync_authority_status == "REBUILD_REQUIRED"
        else "READY"
    )
    selector_sha = formula.get("selector_sha256")
    backtest_sha = formula.get("backtest_sha256")
    declared_sha = formula.get("sha256")
    lane_sha = ""
    if selector_sha is not None or backtest_sha is not None:
        if not _is_sha256(selector_sha) or not _is_sha256(backtest_sha):
            raise SnapshotGateError("A formula artifact SHA binding is incomplete")
        lane_sha = _combined_artifact_sha(selector_sha, backtest_sha)
        if declared_sha is not None and declared_sha != lane_sha:
            raise SnapshotGateError("A formula artifact SHA binding is inconsistent")
    elif _is_sha256(declared_sha):
        lane_sha = declared_sha
    if not lane_sha and isinstance(formula.get("authority"), Mapping):
        source_sha = formula["authority"].get("source_sha256")
        lane_sha = source_sha if _is_sha256(source_sha) else ""
    return {
        "status": status,
        "target_date": target,
        "bootstrap": bootstrap,
        "sync": sync,
        "formula": formula,
        "authority_status": authority_status,
        "sync_authority_status": sync_authority_status,
        "formula_authority_status": formula_authority_status,
        "reason": reason,
        "formula_input_mode": sync.get("formula_input_mode"),
        "accepted_target_date_file_count": sync.get("accepted_target_date_file_count"),
        "target_date_file_count": sync.get("target_date_file_count"),
        "target_count": sync.get("target_count"),
        "accepted_count": sync.get("accepted_count"),
        "quarantine_count": sync.get("quarantine_count"),
        "reconciliation": sync.get("reconciliation"),
        "excluded_rebuild_candidate_count": sync.get("excluded_rebuild_candidate_count", 0),
        "row_count": row_count,
        "coverage_rate": coverage_rate,
        "cannot_confirm": cannot_confirm,
        "selector": formula.get("selector"),
        "selector_sha256": formula.get("selector_sha256"),
        "backtest": formula.get("backtest"),
        "backtest_sha256": formula.get("backtest_sha256"),
        "sha256": lane_sha,
        **SAFETY_FLAGS,
    }
