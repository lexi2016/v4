"""Authority adapters for the daily research-panel lanes."""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import hashlib
import importlib.util
import inspect
import os
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .macos_research_panel_daily_common import (
    A_DAY_STRUCT,
    SAFETY_FLAGS,
    SnapshotGateError,
    _a_day_files,
    _atomic_write,
    _date,
    _sha,
)
from .macos_research_panel_daily_pack import _day_file_last_date


def _load_authority_module(script_path: Path | str, module_name: str) -> Any:
    path = Path(script_path).resolve()
    if not path.is_file():
        raise SnapshotGateError(f"authority script missing: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SnapshotGateError(f"authority module cannot load: {path}")
    module = importlib.util.module_from_spec(spec)
    missing = object()
    previous = sys.modules.get(module_name, missing)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is missing:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    sys.modules[module_name] = module
    return module


def _formula_artifact_binding(selector: Path, backtest: Path) -> dict[str, str]:
    """Bind the formula lane to the exact bytes behind both current pointers."""
    selector_sha = _sha(selector)
    backtest_sha = _sha(backtest)
    combined = hashlib.sha256(
        f"selector:{selector_sha}\nbacktest:{backtest_sha}\n".encode("ascii")
    ).hexdigest()
    return {
        "selector": str(selector),
        "selector_sha256": selector_sha,
        "backtest": str(backtest),
        "backtest_sha256": backtest_sha,
        "sha256": combined,
    }


def _path_has_symlink_component(path: Path) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor or "/")
    parts = candidate.parts[1:] if candidate.anchor else candidate.parts
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _safe_root_path(
    root: Path,
    raw_path: Path | str,
    *,
    require_file: bool = True,
    _link_check: Any = _path_has_symlink_component,
) -> Path:
    """Resolve a ledger path without following a source-tree link."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.absolute()
    root = root.resolve()
    if _link_check(candidate):
        raise SnapshotGateError(f"A sync source path contains a symlink: {candidate}")
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except ValueError as error:
        raise SnapshotGateError(f"A sync result path outside TDX root: {candidate}") from error
    if resolved != candidate:
        raise SnapshotGateError(f"A sync source path changed through a link: {candidate}")
    if require_file and (not candidate.is_file() or candidate.is_symlink()):
        raise SnapshotGateError(f"A sync source is not a regular file: {candidate}")
    return candidate


def _a_target_key(root: Path, path: Path) -> tuple[str, int, str]:
    relative = path.relative_to(root)
    if len(relative.parts) != 4 or relative.parts[0] != "vipdoc" or relative.parts[2] != "lday":
        raise SnapshotGateError(f"A sync source path is not a canonical daily file: {path}")
    exchange = relative.parts[1]
    market = {"sz": 0, "sh": 1, "bj": 2}.get(exchange)
    if market is None or not relative.name.startswith(exchange):
        raise SnapshotGateError(f"A sync source path has an unsupported market: {path}")
    code = relative.stem[len(exchange) :]
    if len(code) != 6 or not code.isdigit():
        raise SnapshotGateError(f"A sync source path has an invalid code: {path}")
    return code, market, str(path)


def _canonical_scope_fingerprint(keys: Sequence[tuple[str, int, str]]) -> str:
    descriptors = [
        {"code": code, "market": int(market), "path": path}
        for code, market, path in sorted(keys)
    ]
    return hashlib.sha256(
        json.dumps(descriptors, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical_target_files(
    root: Path,
    *,
    _safe_path: Any = _safe_root_path,
) -> list[Path]:
    """Freeze the discovered canonical pool before the provider mutates bytes."""
    return sorted({_safe_path(root, raw) for raw in _a_day_files(root)})


def _reported_reconciliation_rows(reported: Mapping[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    for value in (reported.get("symbol_reconciliation"), reported.get("reconciliation")):
        if isinstance(value, Mapping):
            value = value.get("symbols")
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    results_path = run_dir / "file_results.csv"
    if not results_path.is_file():
        return []
    previous_limit = csv.field_size_limit()
    try:
        byte_size = results_path.stat().st_size
        csv.field_size_limit(max(previous_limit, byte_size))
        with results_path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as error:
        raise SnapshotGateError(f"A sync accepted-input ledger unreadable: {results_path}") from error
    finally:
        csv.field_size_limit(previous_limit)


def _row_classification(row: Mapping[str, Any]) -> str:
    classification = str(row.get("classification") or "").strip().upper()
    status = str(row.get("status") or "").strip().upper()
    fetch_status = str(row.get("fetch_status") or "").strip().upper()
    accepted_tuples = {
        ("ALREADY_CURRENT", "ALREADY_CURRENT", "ACCEPTED"),
        ("REVALIDATED_CURRENT", "REVALIDATED", "ACCEPTED"),
        ("UPDATED", "OK", "ACCEPTED"),
        # Keep the historical CURRENT spelling accepted only when all three
        # fields agree.  A single accepted-looking field is never enough.
        ("CURRENT", "CURRENT", "ACCEPTED"),
        ("UPDATED", "OK_WITH_SKIPPED_INVALID", "ACCEPTED"),
        # Reviewed exact-date local reuse is accepted only as this complete
        # producer tuple.  The receipt-bound source/date/history gates still
        # run below and in the formula handoff.
        ("TRUSTED_CAS_CURRENT", "TRUSTED_CAS_REUSE", "ACCEPTED"),
    }
    quarantined_tuples = {
        ("FAILED", "REBUILD_REQUIRED", "QUARANTINED"),
        ("CANNOT_CONFIRM", "REBUILD_REQUIRED", "QUARANTINED"),
    }
    pending_tuples = {
        ("CANNOT_CONFIRM", "A_SYNC_TIMEOUT", "UNPROCESSED"),
    }
    row_tuple = (status, fetch_status, classification)
    if row_tuple in pending_tuples:
        return "PENDING"
    if row_tuple in quarantined_tuples:
        return "QUARANTINED"
    if row_tuple in accepted_tuples:
        return "ACCEPTED"
    return "UNKNOWN"


_NORMAL_RUN_TIMEOUT_MINIMUM_ACCEPTED = 5000
_GLOBAL_FAILURE_FIELDS = (
    "global_failure", "global_error", "provider_failure", "shared_provider_failure",
    "system_failure", "unsupported_context", "run_failure",
)
_PRODUCER_TIMEOUT_SCOPES = frozenset({"RUN", "SYMBOL", "CONNECT", "REQUEST", "UNSUPPORTED_CONTEXT"})


def _producer_timeout_scope(failure_type: str) -> str | None:
    """Return a producer timeout scope only when its delimiter is exact."""
    prefix, separator, remainder = failure_type.partition(":")
    if prefix != "A_SYNC_TIMEOUT" or not separator or not remainder:
        return None
    scope = remainder.split(":", 1)[0]
    return scope if scope in _PRODUCER_TIMEOUT_SCOPES else None


def _is_normal_bounded_run_timeout(reported: Mapping[str, Any], exit_code: int) -> bool:
    """Recognize only the owner-controlled bounded RUN timeout envelope.

    A real RUN timeout is still a source-level ``TIMEOUT``/124 result and must
    remain visible in the authority payload.  This predicate only decides
    whether that audited envelope may continue to the strict reconciliation
    and accepted-only materialization gates.
    """
    status = str(reported.get("status") or "").upper()
    if status not in {"TIMEOUT", "A_SYNC_TIMEOUT"}:
        return False
    if exit_code != 124 or reported.get("timeout") is not True:
        return False
    if reported.get("interrupted") is not False:
        return False
    if str(reported.get("timeout_scope") or "").upper() != "RUN":
        return False

    accepted = reported.get("accepted_count")
    quarantine = reported.get("quarantine_count")
    pending = reported.get("pending_count")
    if (
        not isinstance(accepted, int)
        or isinstance(accepted, bool)
        or accepted < _NORMAL_RUN_TIMEOUT_MINIMUM_ACCEPTED
        or not isinstance(quarantine, int)
        or isinstance(quarantine, bool)
        or quarantine <= 0
        or not isinstance(pending, int)
        or isinstance(pending, bool)
        or pending <= 0
    ):
        return False
    progress = reported.get("progress")
    if any(
        bool(reported.get(field))
        or (isinstance(progress, Mapping) and bool(progress.get(field)))
        for field in _GLOBAL_FAILURE_FIELDS
    ):
        return False

    failures = reported.get("failures")
    if not isinstance(failures, list):
        return False
    bounded_run_failure = False
    for failure in failures:
        if not isinstance(failure, Mapping):
            return False
        failure_type = str(failure.get("failure_type") or "").upper()
        timeout_scope = _producer_timeout_scope(failure_type)
        if timeout_scope is not None:
            if timeout_scope == "RUN":
                bounded_run_failure = True
            elif timeout_scope == "UNSUPPORTED_CONTEXT":
                return False
            continue
        if failure_type.startswith("A_SYNC_TIMEOUT"):
            return False
        if ":RUN" in failure_type or "UNSUPPORTED_CONTEXT" in failure_type or "SYSTEM" in failure_type:
            return False
    return bounded_run_failure


def _row_signature(
    root: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    _row_key: Any,
    _classify: Any,
) -> tuple[tuple[tuple[str, int, str], str], ...]:
    """Canonicalize one native row set for exact top/nested comparison."""
    signatures: list[tuple[tuple[str, int, str], str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise SnapshotGateError("A sync reconciliation row is malformed")
        key = _row_key(root, row)
        classification = _classify(row)
        if classification == "UNKNOWN":
            raise SnapshotGateError("A sync reconciliation has an unknown row classification")
        signatures.append((key, classification))
    if len(signatures) != len(set(signatures)):
        raise SnapshotGateError("A sync reconciliation row set is duplicated")
    return tuple(sorted(signatures))


def _assert_nested_reconciliation_coherent(
    root: Path,
    reported: Mapping[str, Any],
    *,
    _row_key: Any,
    _classify: Any,
) -> None:
    """Require the producer's duplicated row/count views to agree exactly."""
    if "reconciliation" not in reported:
        return
    nested = reported.get("reconciliation")
    if not isinstance(nested, Mapping):
        raise SnapshotGateError("A sync nested reconciliation is malformed")
    required = ("symbols", "target_count", "accepted_count", "quarantine_count", "pending_count")
    missing = [name for name in required if name not in nested]
    if missing:
        raise SnapshotGateError(
            "A sync nested reconciliation is missing required fields: " + ",".join(missing)
        )
    top_rows = reported.get("symbol_reconciliation")
    nested_rows = nested["symbols"]
    if not isinstance(top_rows, list) or not isinstance(nested_rows, list):
        raise SnapshotGateError("A sync nested reconciliation rows are malformed")
    if _row_signature(root, top_rows, _row_key=_row_key, _classify=_classify) != _row_signature(
        root, nested_rows, _row_key=_row_key, _classify=_classify
    ):
        raise SnapshotGateError("A sync nested reconciliation rows mismatch")
    for name in ("target_count", "accepted_count", "quarantine_count", "pending_count"):
        value = nested[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SnapshotGateError(f"A sync nested reconciliation metric invalid: {name}={value!r}")
        if value != reported.get(name):
            raise SnapshotGateError(
                f"A sync nested reconciliation metric mismatch: {name}={value},top={reported.get(name)}"
            )


def _reported_row_key(
    root: Path,
    row: Mapping[str, Any],
    *,
    _safe_path: Any = _safe_root_path,
    _path_key: Any = _a_target_key,
) -> tuple[str, int, str]:
    raw_path = str(row.get("path") or "").strip()
    if not raw_path:
        raise SnapshotGateError("A sync reconciliation row is missing path")
    path = _safe_path(root, Path(raw_path))
    key = _path_key(root, path)
    raw_symbol = row.get("symbol") or row.get("code")
    if raw_symbol is not None and str(raw_symbol).strip() and str(raw_symbol).strip() != key[0]:
        raise SnapshotGateError(f"A sync reconciliation symbol/path mismatch: {raw_symbol} != {key[0]}")
    raw_market = row.get("market")
    if raw_market is not None and str(raw_market).strip() and int(raw_market) != key[1]:
        raise SnapshotGateError(f"A sync reconciliation market/path mismatch: {raw_market} != {key[1]}")
    return key


def _audit_sync_scope(
    root: Path,
    target: int,
    target_files: Sequence[Path],
    reported: Mapping[str, Any],
    *,
    _safe_path: Any = _safe_root_path,
    _path_key: Any = _a_target_key,
    _fingerprint: Any = _canonical_scope_fingerprint,
    _row_key: Any = _reported_row_key,
    _classify: Any = _row_classification,
    _rows_impl: Any = _reported_reconciliation_rows,
    allow_bounded_run_timeout: bool = False,
) -> dict[str, Any]:
    """Require exact date, key, count, and failure closure before handoff."""
    reported_date = reported.get("target_date")
    if reported_date is None or _date(reported_date) != str(target):
        raise SnapshotGateError(
            f"A sync target date mismatch: requested={target},reported={reported_date}"
        )
    expected_paths = {_safe_path(root, path) for path in target_files}
    expected_keys = {_path_key(root, path) for path in expected_paths}
    if len(expected_paths) != len(expected_keys):
        raise SnapshotGateError("A sync target scope has duplicate canonical keys")
    expected_fingerprint = _fingerprint(sorted(expected_keys))
    reported_fingerprint = str(reported.get("target_fingerprint") or "").strip()
    if not reported_fingerprint:
        raise SnapshotGateError("A sync target fingerprint is missing")
    if reported_fingerprint != expected_fingerprint:
        raise SnapshotGateError("A sync target fingerprint mismatch")
    reported_keys = reported.get("target_keys")
    if reported_keys is not None:
        if not isinstance(reported_keys, list) or not reported_keys:
            raise SnapshotGateError("A sync target key set is missing or invalid")
        parsed_keys = [_row_key(root, row) for row in reported_keys if isinstance(row, Mapping)]
        if len(parsed_keys) != len(reported_keys) or len(parsed_keys) != len(set(parsed_keys)):
            raise SnapshotGateError("A sync target key set is duplicated or malformed")
        if set(parsed_keys) != expected_keys:
            raise SnapshotGateError("A sync target key set mismatch")

    _assert_nested_reconciliation_coherent(
        root,
        reported,
        _row_key=_row_key,
        _classify=_classify,
    )
    rows = _rows_impl(reported, Path(str(reported.get("run_dir") or "")))
    if not rows:
        raise SnapshotGateError("A sync reconciliation rows are missing")
    row_keys: list[tuple[str, int, str]] = []
    classifications: list[str] = []
    for row in rows:
        key = _row_key(root, row)
        path = Path(key[2])
        if key not in expected_keys:
            raise SnapshotGateError(f"A sync reconciliation key outside frozen scope: {key}")
        if key in row_keys:
            raise SnapshotGateError(f"A sync reconciliation key duplicated: {key}")
        classification = _classify(row)
        if classification == "ACCEPTED" and _day_file_last_date(path, A_DAY_STRUCT) != target:
            raise SnapshotGateError(f"A sync reconciliation source is not exact-date: {path}")
        row_keys.append(key)
        classifications.append(classification)
    if set(row_keys) != expected_keys:
        missing = sorted(expected_keys - set(row_keys))
        extra = sorted(set(row_keys) - expected_keys)
        raise SnapshotGateError(f"A sync reconciliation scope mismatch: missing={missing[:3]},extra={extra[:3]}")

    accepted_count = classifications.count("ACCEPTED")
    quarantine_count = classifications.count("QUARANTINED")
    pending_count = classifications.count("PENDING")
    if classifications.count("UNKNOWN"):
        raise SnapshotGateError("A sync reconciliation has an unknown row classification")
    expected_count = len(expected_keys)
    def _metric(name: str, fallback: int) -> int:
        value = reported.get(name, fallback)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SnapshotGateError(f"A sync reconciliation metric invalid: {name}={value!r}")
        if int(value) != int(fallback):
            raise SnapshotGateError(f"A sync reconciliation metric mismatch: {name}={value},rows={fallback}")
        return int(value)

    target_count = _metric("target_count", expected_count)
    reported_accepted = _metric("accepted_count", accepted_count)
    reported_quarantine = _metric("quarantine_count", quarantine_count)
    reported_pending = _metric("pending_count", pending_count)
    if "completed_count" in reported:
        _metric("completed_count", accepted_count)
    if target_count != expected_count or reported_accepted + reported_quarantine + reported_pending != target_count:
        raise SnapshotGateError("A sync reconciliation count equation is invalid")
    progress = reported.get("progress")
    failed_hosts = reported.get("failed_hosts")
    if failed_hosts is None and isinstance(progress, Mapping):
        failed_hosts = progress.get("failed_hosts")
    # Endpoint failures are run-scoped diagnostics. A healthy fallback can
    # close accepted rows while retaining the failed endpoint label.
    if any(
        bool(reported.get(field))
        or (isinstance(progress, Mapping) and bool(progress.get(field)))
        for field in _GLOBAL_FAILURE_FIELDS
    ):
        raise SnapshotGateError("A sync authority cannot close after a global provider failure")
    timeout_scope = str(reported.get("timeout_scope") or "").upper()
    if timeout_scope in {"RUN", "UNSUPPORTED_CONTEXT", "INTERRUPTED"} and not (
        allow_bounded_run_timeout and timeout_scope == "RUN"
    ):
        raise SnapshotGateError("A sync authority cannot close after a run-wide timeout")
    for failure in reported.get("failures") or []:
        if not isinstance(failure, Mapping):
            continue
        failure_type = str(failure.get("failure_type") or "").upper()
        timeout_token_scope = _producer_timeout_scope(failure_type)
        if timeout_token_scope is None and failure_type.startswith("A_SYNC_TIMEOUT"):
            raise SnapshotGateError("A sync authority cannot close after an unrecognized timeout scope")
        if timeout_token_scope == "RUN" and not allow_bounded_run_timeout:
            raise SnapshotGateError("A sync authority cannot close after a global failure")
        if timeout_token_scope == "UNSUPPORTED_CONTEXT":
            raise SnapshotGateError("A sync authority cannot close after an unsupported timeout")
        if timeout_token_scope is not None:
            continue
        if ":RUN" in failure_type or "UNSUPPORTED_CONTEXT" in failure_type or "SYSTEM" in failure_type:
            raise SnapshotGateError("A sync authority cannot close after a global failure")

    reported_status = str(reported.get("status") or "").upper()
    raw_exit = reported.get("exit_code", 0)
    try:
        exit_code = int(raw_exit)
    except (TypeError, ValueError):
        exit_code = -1
    if reported_status == "PASS":
        if (
            exit_code != 0
            or quarantine_count != 0
            or pending_count != 0
            or accepted_count != expected_count
        ):
            raise SnapshotGateError("A sync PASS did not prove complete exact-date closure")
        authority_status = "PASS"
    elif reported_status in {"FAILED", "REBUILD_REQUIRED"}:
        if accepted_count <= 0 or quarantine_count <= 0:
            raise SnapshotGateError("A sync partial closure has no healthy accepted subset")
        if reported_status == "FAILED" and exit_code == 0:
            raise SnapshotGateError("A sync FAILED report has a zero exit code")
        authority_status = "REBUILD_REQUIRED"
    elif allow_bounded_run_timeout and reported_status in {"TIMEOUT", "A_SYNC_TIMEOUT"}:
        if not _is_normal_bounded_run_timeout(reported, exit_code):
            raise SnapshotGateError("A sync bounded RUN timeout envelope is invalid")
        if reported_accepted < _NORMAL_RUN_TIMEOUT_MINIMUM_ACCEPTED:
            raise SnapshotGateError("A sync bounded RUN timeout accepted floor failed")
        if reported_quarantine <= 0 or reported_pending <= 0:
            raise SnapshotGateError("A sync bounded RUN timeout must retain pending and quarantine rows")
        authority_status = "REBUILD_REQUIRED"
    else:
        raise SnapshotGateError(
            f"A sync authority did not prove exact-date success: status={reported.get('status')},exit_code={raw_exit}"
        )
    return {
        "authority_status": authority_status,
        "target_count": target_count,
        "accepted_count": reported_accepted,
        "quarantine_count": reported_quarantine,
        "pending_count": reported_pending,
        "target_fingerprint": expected_fingerprint,
        "target_keys": [
            {"symbol": code, "market": market, "path": path}
            for code, market, path in sorted(expected_keys)
        ],
        "rows": rows,
    }


def _recheck_full_sync_scope(
    root: Path,
    target: int,
    target_files: Sequence[Path],
    reported: Mapping[str, Any],
    *,
    _safe_path: Any = _safe_root_path,
    _path_key: Any = _a_target_key,
    _rows_impl: Any = _reported_reconciliation_rows,
    _classify: Any = _row_classification,
) -> None:
    """Recheck the frozen FULL_SYNC key set and accepted source bytes."""
    current_files = _canonical_target_files(root, _safe_path=_safe_path)
    frozen_keys = {_path_key(root, _safe_path(root, path)) for path in target_files}
    current_keys = {_path_key(root, path) for path in current_files}
    if current_keys != frozen_keys:
        raise SnapshotGateError(
            "A sync FULL_SYNC canonical scope drift: "
            f"frozen={len(frozen_keys)},current={len(current_keys)}"
        )

    rows = _rows_impl(reported, Path(str(reported.get("run_dir") or "")))
    rows_by_key: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    for row in rows:
        key = _reported_row_key(root, row, _safe_path=_safe_path, _path_key=_path_key)
        if _classify(row) != "ACCEPTED":
            raise SnapshotGateError("A sync FULL_SYNC contains a non-accepted handoff row")
        if key in rows_by_key:
            raise SnapshotGateError(f"A sync FULL_SYNC handoff row duplicated: {key}")
        rows_by_key[key] = row
    if set(rows_by_key) != current_keys:
        raise SnapshotGateError("A sync FULL_SYNC handoff rows do not match canonical scope")

    for path in current_files:
        key = _path_key(root, path)
        row = rows_by_key[key]
        recorded_sha = str(
            row.get("source_sha256_after")
            or row.get("source_sha256")
            or row.get("sha256")
            or ""
        ).strip().lower()
        if len(recorded_sha) != 64 or any(char not in "0123456789abcdef" for char in recorded_sha):
            raise SnapshotGateError(f"A sync FULL_SYNC source SHA missing or invalid: {path}")
        observed_sha = _sha(path)
        if observed_sha != recorded_sha:
            raise SnapshotGateError(
                f"A sync FULL_SYNC source SHA drift: {path} recorded={recorded_sha} observed={observed_sha}"
            )


def _native_history_evidence(module: Any, args: Any) -> dict[str, Any] | None:
    """Reuse the producer's opt-in pinned seed configuration at handoff.

    Earlier authorities expose a two-argument validator. They keep their
    original call; only the existing evidence-aware authority accepts this
    context. The authority itself verifies every pin and explains each pair.
    """
    validator = getattr(module, "_local_history_status", None)
    if not callable(validator):
        return None
    parameters = inspect.signature(validator).parameters
    if not {"seed_evidence", "symbol"}.issubset(parameters):
        return None
    path = getattr(args, "seed_adjustment_inputs", None)
    if path in (None, ""):
        path = os.environ.get(getattr(module, "SEED_ADJUSTMENT_INPUTS_ENV", "V35_A_SYNC_SEED_ADJUSTMENT_INPUTS"))
    if path in (None, ""):
        return None
    digest = getattr(args, "seed_adjustment_inputs_sha256", None)
    if digest in (None, ""):
        digest = os.environ.get(getattr(module, "SEED_ADJUSTMENT_INPUTS_SHA256_ENV", "V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256"))
    return {"path": path, "expected_sha256": digest, "records": []}


def _accepted_formula_input_root(
    root: Path,
    target: int,
    receipt_root: Path,
    run_dir: Path,
    *,
    target_files: Sequence[Path],
    authority_status: str,
    _safe_path: Any = _safe_root_path,
    _link_check: Any = _path_has_symlink_component,
    _classify: Any = _row_classification,
    _history_status: Any = None,
    _history_evidence: dict[str, Any] | None = None,
    _rows_impl: Any = _reported_reconciliation_rows,
) -> dict[str, Any]:
    """Materialize only exact-date, non-rebuild inputs for a partial sync.

    The daily authority deliberately keeps its aggregate ``REBUILD_REQUIRED``
    result and its rebuild candidates.  Formula must not read those candidates
    from the mutable sync root, though it may consume the ordinary exact-date
    files that were accepted by the same run.  The isolated tree is immutable
    and content-addressed so a later retry cannot silently mix input sets.
    """
    receipt_root = receipt_root.resolve()
    run_dir = run_dir.resolve()
    try:
        run_dir.relative_to(receipt_root)
    except ValueError as error:
        raise SnapshotGateError(f"A sync run directory outside receipt root: {run_dir}") from error
    results_path = run_dir / "file_results.csv"
    if not results_path.is_file():
        raise SnapshotGateError(f"A sync accepted-input ledger missing: {results_path}")

    target_set = {
        _safe_path(root, path)
        for path in target_files
    }
    accepted: dict[Path, dict[str, Any]] = {}
    excluded_rebuild = 0
    rows = _rows_impl({}, run_dir)
    for row in rows:
        raw_path = str(row.get("path") or "").strip()
        if not raw_path:
            continue
        source = _safe_path(root, Path(raw_path))
        relative = source.relative_to(root)
        status = str(row.get("fetch_status") or "").strip().upper()
        classification = _classify(row)
        if classification in {"QUARANTINED", "PENDING", "UNKNOWN"}:
            excluded_rebuild += 1
            continue
        if source not in target_set:
            raise SnapshotGateError(f"A sync accepted path is outside frozen target scope: {source}")
        if status not in {
            "OK",
            "OK_WITH_SKIPPED_INVALID",
            "ALREADY_CURRENT",
            "CURRENT",
            "REVALIDATED",
            "TRUSTED_CAS_REUSE",
        }:
            raise SnapshotGateError(f"A sync accepted row has unsupported status: {status}")
        if _day_file_last_date(source, A_DAY_STRUCT) != target:
            raise SnapshotGateError(f"A sync accepted source is not exact-date: {source}")
        if not callable(_history_status):
            raise SnapshotGateError("A sync native history validator is unavailable")
        first_explanation = len(_history_evidence["records"]) if _history_evidence is not None else 0
        try:
            if _history_evidence is None:
                _history, history_failure = _history_status(source, target)
            else:
                from ops.macos_research_panel_daily_authority import _a_target_key
                code, market, _path = _a_target_key(root, source)
                suffix = {0: "SZ", 1: "SH", 2: "BJ"}[market]
                symbol = f"{code}.{suffix}"
                _history, history_failure = _history_status(
                    source, target, seed_evidence=_history_evidence, symbol=symbol,
                )
        except (OSError, ValueError, TypeError, struct.error) as error:
            raise SnapshotGateError(
                f"A sync native history validation failed: {source}: {error}"
            ) from error
        if history_failure is not None:
            raise SnapshotGateError(
                f"A sync accepted source failed native history validation: {source}: {history_failure}"
            )
        recorded_sha = str(
            row.get("source_sha256_after")
            or row.get("source_sha256")
            or row.get("sha256")
            or ""
        ).strip().lower()
        if len(recorded_sha) != 64 or any(char not in "0123456789abcdef" for char in recorded_sha):
            raise SnapshotGateError(f"A sync accepted source SHA missing or invalid: {source}")
        if source in accepted:
            raise SnapshotGateError(f"A sync accepted source key is duplicated: {source}")
        observed_sha = _sha(source)
        if observed_sha != recorded_sha:
            raise SnapshotGateError(
                f"A sync accepted source SHA drift: {source} recorded={recorded_sha} observed={observed_sha}"
            )
        accepted[source] = {
            "path": str(source),
            "relative_path": str(relative),
            "sha256": recorded_sha,
            "fetch_status": status,
        }
        if _history_evidence is not None:
            accepted[source]["native_history_validation"] = {
                "seed_evidence_config": {
                    "path": str(_history_evidence["path"]),
                    "expected_sha256": _history_evidence["expected_sha256"],
                },
                "explanations": _history_evidence["records"][first_explanation:],
            }

    if not accepted:
        raise SnapshotGateError(
            "A sync REBUILD_REQUIRED has no accepted exact-date files for formula"
        )

    descriptors = [accepted[path] for path in sorted(accepted)]
    input_digest = hashlib.sha256(
        json.dumps(
            {
                "target_date": target,
                "files": descriptors,
                "excluded_rebuild_candidate_count": excluded_rebuild,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    formula_root = receipt_root / "formula_inputs" / str(target) / input_digest
    if _link_check(formula_root):
        raise SnapshotGateError(f"A formula input root contains a symlink: {formula_root}")
    formula_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(accepted):
        destination = formula_root / accepted[source]["relative_path"]
        if _link_check(destination.parent):
            raise SnapshotGateError(f"A formula input destination contains a symlink: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise SnapshotGateError(f"A formula input unexpectedly symlinked: {destination}")
        source_bytes = source.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != accepted[source]["sha256"]:
            raise SnapshotGateError(f"A formula input source changed during read: {source}")
        if destination.exists():
            if destination.read_bytes() != source_bytes:
                raise SnapshotGateError(f"A formula input conflict: {destination}")
        else:
            _atomic_write(destination, source_bytes)
        if _sha(destination) != accepted[source]["sha256"]:
            raise SnapshotGateError(f"A formula input SHA changed during copy: {source}")

    manifest = {
        "schema_version": "v3_5.a_sync.accepted_formula_input.v1",
        "authority_status": authority_status,
        "target_date": target,
        "source_run_dir": str(run_dir),
        "files": descriptors,
        "excluded_rebuild_candidate_count": excluded_rebuild,
        **SAFETY_FLAGS,
    }
    manifest_path = formula_root / "manifest.json"
    encoded_manifest = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if manifest_path.exists():
        if manifest_path.read_bytes() != encoded_manifest:
            raise SnapshotGateError(f"A formula input manifest conflict: {manifest_path}")
    else:
        _atomic_write(manifest_path, encoded_manifest)
    return {
        "formula_tdx_root": str(formula_root),
        "formula_input_mode": "ACCEPTED_ONLY",
        "formula_input_manifest": str(manifest_path),
        "accepted_target_date_file_count": len(accepted),
        "excluded_rebuild_candidate_count": excluded_rebuild,
    }


def run_windows_a_sync_authority(
    script_path: Path | str,
    tdx_root: Path | str,
    target_date: str,
    receipt_root: Path | str,
    *,
    minimum_target_date_files: int = 1,
    module_name: str = "macos_windows_a_sync_authority",
    authority_args: Mapping[str, Any] | None = None,
    _target_files_impl: Any = _canonical_target_files,
    _scope_audit_impl: Any = _audit_sync_scope,
    _full_scope_impl: Any = _recheck_full_sync_scope,
    _bounded_timeout_impl: Any = _is_normal_bounded_run_timeout,
) -> dict[str, Any]:
    # The public facade rebinds this function's globals; keep the new helper
    # anchored to its implementation module, like the frozen default gates.
    from ops.macos_research_panel_daily_authority import _native_history_evidence

    target = int(_date(target_date))
    root = Path(tdx_root).resolve()
    module = _load_authority_module(script_path, module_name)
    module.TDX_ROOT = root
    module.DATA_ROOT = Path(receipt_root).resolve()
    # Keep the durable cursor and raw snapshots date-bound.  A retry for a
    # different target date must never inherit a prior run's progress scope.
    module.RUN_DIR = Path(receipt_root).resolve() / "a_sync_authority" / str(target)
    module.DIR_BY_MARKET = {
        "a": [("sh", root / "vipdoc" / "sh" / "lday"), ("sz", root / "vipdoc" / "sz" / "lday")],
        "bj": [("bj", root / "vipdoc" / "bj" / "lday")],
    }
    authority_options = dict(authority_args or {})
    sync_host = authority_options.pop("host", None)
    sync_port = authority_options.pop("port", None)
    if sync_port is not None:
        if sync_host is None:
            raise SnapshotGateError("A sync port requires an explicit host")
        if ":" in str(sync_host):
            raise SnapshotGateError("A sync host must omit the port when port is supplied separately")
        try:
            normalized_port = int(sync_port)
        except (TypeError, ValueError) as error:
            raise SnapshotGateError("A sync port must be an integer") from error
        if not 1 <= normalized_port <= 65535:
            raise SnapshotGateError("A sync port must be between 1 and 65535")
        sync_host = f"{sync_host}:{normalized_port}"
    args = argparse.Namespace(
        tdx_root=root,
        target_date=target,
        markets="a,bj",
        limit=0,
        host=sync_host,
        timeout=1.5,
        count=20,
        sleep=0.0,
        progress_every=10_000,
        dry_run=False,
        **authority_options,
    )
    frozen_target_files = _target_files_impl(root)
    history_evidence = _native_history_evidence(module, args)
    reported = dict(module.run(args))
    reported_status = str(reported.get("status") or "").upper()
    raw_exit_code = reported.get("exit_code", 0)
    try:
        exit_code = int(raw_exit_code)
    except (TypeError, ValueError):
        exit_code = -1
    timeout_signal = reported_status in {"TIMEOUT", "A_SYNC_TIMEOUT", "INTERRUPTED"} or bool(
        reported.get("timeout") or reported.get("interrupted")
    )
    bounded_run_timeout = _bounded_timeout_impl(reported, exit_code)
    if timeout_signal and not bounded_run_timeout:
        # A bounded partial run is useful evidence, but it is not a sync
        # authority and must not feed the formula lane.  Persist the explicit
        # failure receipt before raising so the dispatcher can expose the
        # first failed layer after the child exits normally.
        receipt = Path(receipt_root) / "a_sync_authority.json"
        timeout_payload = {
            "status": "CANNOT_CONFIRM",
            "authority_status": "CANNOT_CONFIRM",
            "RESEARCH_ONLY": True,
            "reason_code": "A_SYNC_INTERRUPTED" if reported_status == "INTERRUPTED" else "A_SYNC_TIMEOUT",
            "first_failed_layer": "A_SYNC",
            "target_date": target,
            "target_count": reported.get("target_count"),
            "accepted_count": reported.get("accepted_count"),
            "quarantine_count": reported.get("quarantine_count"),
            "completed_count": reported.get("completed_count"),
            "pending_count": reported.get("pending_count"),
            "timeout_scope": reported.get("timeout_scope"),
            "progress_path": reported.get("progress_path"),
            "authority": reported,
            **SAFETY_FLAGS,
        }
        _atomic_write(
            receipt,
            (json.dumps(timeout_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        )
        raise SnapshotGateError(
            "A sync stopped before exact-date authority closure: "
            f"scope={reported.get('timeout_scope')},pending={reported.get('pending_count')}"
        )
    target_files = frozen_target_files
    scope = _scope_audit_impl(
        root,
        target,
        target_files,
        reported,
        allow_bounded_run_timeout=bounded_run_timeout,
    )
    authority_status = str(scope["authority_status"])
    accepted_value = int(scope["accepted_count"])
    quarantine_value = int(scope["quarantine_count"])
    pending_value = int(scope["pending_count"])
    target_value = int(scope["target_count"])
    partial_sync = authority_status == "REBUILD_REQUIRED"
    input_info: dict[str, Any]
    if partial_sync:
        run_dir_value = reported.get("run_dir") or str(module.RUN_DIR)
        input_info = _accepted_formula_input_root(
            root,
            target,
            Path(receipt_root),
            Path(run_dir_value),
            target_files=target_files,
            authority_status=authority_status,
            _history_status=getattr(module, "_local_history_status", None),
            _history_evidence=history_evidence,
        )
        effective_target_count = int(input_info["accepted_target_date_file_count"])
    else:
        _full_scope_impl(root, target, target_files, reported)
        effective_target_count = len(target_files)
        input_info = {
            "formula_tdx_root": str(root),
            "formula_input_mode": "FULL_SYNC",
            "formula_input_manifest": None,
            "accepted_target_date_file_count": effective_target_count,
            "excluded_rebuild_candidate_count": 0,
        }
    if partial_sync and effective_target_count != accepted_value:
        raise SnapshotGateError(
            "A sync reconciliation accepted count does not match exact-date files: "
            f"reported={accepted_value},materialized={effective_target_count}"
        )
    # The original owner floor applies equally to a partial/rebuild handoff;
    # quarantines do not authorize a weaker formula-input threshold.
    required_count = int(minimum_target_date_files)
    if effective_target_count < required_count:
        raise SnapshotGateError(f"A sync target-date postcondition failed: {effective_target_count} < {required_count}")
    if target_value <= 0:
        raise SnapshotGateError("A sync target-date coverage cannot be confirmed")
    coverage_rate = accepted_value / target_value
    if not 0.0 <= float(coverage_rate) <= 1.0:
        raise SnapshotGateError("A sync target-date coverage is invalid")
    receipt = Path(receipt_root) / "a_sync_authority.json"
    payload = {
        "status": "READY",
        "authority_status": authority_status,
        "target_date": target,
        "target_date_file_count": effective_target_count,
        "target_scope_file_count": len(target_files),
        "target_count": target_value,
        "accepted_count": accepted_value,
        "quarantine_count": quarantine_value,
        "pending_count": pending_value,
        "target_fingerprint": scope["target_fingerprint"],
        "target_keys": scope["target_keys"],
        "coverage_rate": coverage_rate,
        "reconciliation": reported.get("reconciliation"),
        "files": [str(path) for path in target_files],
        "authority": reported,
        **input_info,
        **SAFETY_FLAGS,
    }
    _atomic_write(receipt, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def _parquet_max_date(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["trade_date"])
        values = table.column("trade_date").to_pylist()
        return max(int(str(value).replace("-", "")) for value in values) if values else None
    except Exception as error:
        raise SnapshotGateError(f"parquet target-date audit failed: {path}") from error


def _ensure_pointer_seed(pointer: Path, seed: Path | str | None) -> Path:
    if pointer.exists():
        target = Path(pointer.read_text(encoding="utf-8-sig").strip())
        if target.is_file():
            return target
        raise SnapshotGateError(f"pointer target missing: {pointer}")
    if seed is None:
        raise SnapshotGateError(f"pointer missing and no seed: {pointer}")
    target = Path(seed).resolve()
    if not target.is_file():
        raise SnapshotGateError(f"pointer seed missing: {target}")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(pointer, (str(target) + "\n").encode())
    return target


def run_windows_a_formula_authority(
    script_path: Path | str,
    *,
    tdx_root: Path | str,
    data_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str | None,
    backtest_seed: Path | str | None,
    contract_csv: Path | str,
    canonical_formula_path: Path | str,
    return_root: Path | str,
    target_date: str,
    module_name: str = "macos_windows_formula_authority",
    formula_max_workers: int | None = None,
    qfq_original_tdx_root: Path | str | None = None,
) -> dict[str, Any]:
    from ops.research_panel_qfq import run_daily_rebuild
    # Keep the original entry, native sync and artifact envelope. The original
    # native full-history root is distinct from sync's accepted-only tail view.
    target = int(_date(target_date))
    data = Path(data_root).resolve()
    tdx = Path(qfq_original_tdx_root or tdx_root).resolve()
    selector_ptr, backtest_ptr = Path(selector_pointer).resolve(), Path(backtest_pointer).resolve()
    _ensure_pointer_seed(selector_ptr, selector_seed)
    _ensure_pointer_seed(backtest_ptr, backtest_seed)
    pinned_driver = Path(__file__).resolve().parent / "vendor/data_layer_daily_formula_increment_update_v1.py"
    result = run_daily_rebuild(
        driver_path=pinned_driver, formula_path=Path(canonical_formula_path).resolve(),
        tdx_root=tdx, data_root=data, pointers={"selector": selector_ptr, "backtest": backtest_ptr},
        contract_csv=Path(contract_csv).resolve(), return_root=Path(return_root).resolve(), target=target,
        publish=True, workers=int(formula_max_workers or __import__("os").environ.get("RESEARCH_PANEL_QFQ_WORKERS", "2")),
        refresh_inputs=True,
    )
    artifact = _formula_artifact_binding(Path(result["selector"]), Path(result["backtest"]))
    current_rows = result.get("counts", {}).get("selector", {}).get("target_date_symbols")
    if current_rows is not None:
        result["authority"]["selector_increment_rows"] = int(current_rows)
    return {**result, **artifact, "legacy_cli_formula_source": str(Path(script_path).resolve()),
            "formula_authority_driver": str(pinned_driver), "qfq_original_tdx_root": str(tdx)}


def run_hk_0_2_authority(updater_script: Path | str, python_executable: Path | str, asset_root: Path | str, tdx_root: Path | str, target_date: str) -> dict[str, Any]:
    target = _date(target_date)
    argv = [str(python_executable), str(Path(updater_script)), "--asset-root", str(Path(asset_root)), "--tdx-root", str(Path(tdx_root)), "--through-date", target]
    completed = subprocess.run(argv, shell=False, check=True, capture_output=True, text=True)

    class DuplicateJSONKey(ValueError):
        pass

    def strict_object(text: str) -> dict[str, Any]:
        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise DuplicateJSONKey(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-standard JSON constant: {value}")

        outcome = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
        if not isinstance(outcome, Mapping):
            raise ValueError("authority output must be a JSON object")
        return dict(outcome)

    raw_stdout = completed.stdout
    if isinstance(raw_stdout, bytes):
        try:
            output = raw_stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SnapshotGateError("HK authority output is not UTF-8") from error
    else:
        output = str(raw_stdout or "")
    try:
        outcome = strict_object(output.strip())
    except DuplicateJSONKey as error:
        raise SnapshotGateError("HK authority output is not JSON") from error
    except (json.JSONDecodeError, TypeError, ValueError):
        candidates: list[Mapping[str, Any]] = []
        for line in output.splitlines():
            try:
                candidate = strict_object(line.strip())
            except DuplicateJSONKey as error:
                raise SnapshotGateError("HK authority output is not JSON") from error
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            candidates.append(candidate)
        if len(candidates) != 1:
            reason = "ambiguous" if len(candidates) > 1 else "not JSON"
            raise SnapshotGateError(f"HK authority output is {reason}")
        outcome = dict(candidates[0])
    if not isinstance(outcome, Mapping):
        raise SnapshotGateError("HK authority output is not a JSON object")
    if outcome.get("status") != "READY" or _date(outcome.get("through_date")) != target:
        raise SnapshotGateError(f"HK authority through-date postcondition failed: {outcome}")
    return {**outcome, "target_date": target, "argv": argv, **SAFETY_FLAGS}
