"""V3.5-owned A-share TDX daily synchronizer.

The seed implementation is imported from the read-only research-panel runtime
source ``tdxpy_daily_vipdoc_sync_v1.py``.  This release-owned module keeps the
binary ``.day`` codec but routes execution through the bounded reconnect core;
all run artifacts are written below the caller-provided state/runtime root.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import os
import signal
import stat
import struct
import tempfile
import threading
import time
import zlib
from datetime import datetime
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # Keep the validation/sync core importable in tests without pytdx.
    from pytdx.config.hosts import hq_hosts
    from pytdx.hq import TdxHq_API
    from pytdx.errors import TdxFunctionCallError
except ImportError:  # pragma: no cover - production installs pytdx.
    hq_hosts = ()
    TdxHq_API = None
    TdxFunctionCallError = None


TASK_NAME = "tdxpy_daily_vipdoc_sync_v1"
TDX_ROOT = Path(r"C:\new_tdx_mock")
DATA_ROOT = Path(__file__).resolve().parents[3]
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
# Runtime output must be supplied by the state root, never written beside an
# immutable release module.  The macOS adapter overrides ``RUN_DIR`` with its
# receipt-root-owned path; the CLI uses this explicit environment override.
_RUN_ROOT = Path(os.environ.get("V35_A_SYNC_RUN_ROOT", "/tmp/v35-a-sync-runtime"))
RUN_DIR = _RUN_ROOT / RUN_TS

DAY_STRUCT = struct.Struct("<IIIIIfII")
MAX_CROSS_DAY_CLOSE_RATIO = 1.5
_PROTOCOL_PARSE_EXCEPTION_TYPES = (struct.error, zlib.error, EOFError, UnicodeDecodeError)
_PROTOCOL_PARSE_EXCEPTION_NAMES = {
    ("pytdx.parser.base", "ResponseHeaderRecvFails"),
    ("pytdx.parser.base", "ResponseRecvFails"),
}

# The outer executor for the native A lane is 600 seconds.  These defaults
# leave room for the authority adapter to write a typed receipt before that
# boundary while retaining the installed SDK's 1.5 second socket timeout.
DEFAULT_REQUEST_DEADLINE_SECONDS = 9.0
DEFAULT_SYMBOL_BUDGET_SECONDS = 45.0
DEFAULT_RUN_BUDGET_SECONDS = 540.0
PROGRESS_SCHEMA_VERSION = "v3_5.a_share.tdx_progress.v1"

# These codes are part of the synchronizer's reconciliation contract.  The
# older ``failure_type`` strings remain available below for callers that still
# display the original v1 diagnostics.
EMPTY_RESPONSE = "EMPTY_RESPONSE"
PROTOCOL_RESPONSE_MALFORMED = "PROTOCOL_RESPONSE_MALFORMED"
TARGET_DATE_MISSING = "TARGET_DATE_MISSING"
DUPLICATE_DATE = "DUPLICATE_DATE"
NON_MONOTONIC_DATE = "NON_MONOTONIC_DATE"
CROSS_DAY_CLOSE_RATIO = "CROSS_DAY_CLOSE_RATIO"
OUT_OF_SCOPE_AFTER_TARGET_DATE = "OUT_OF_SCOPE_AFTER_TARGET_DATE"
INVALID_BAR = "INVALID_BAR"
SOURCE_DATE_AFTER_TARGET = "SOURCE_DATE_AFTER_TARGET"
SOURCE_IDENTITY_CHANGED = "SOURCE_IDENTITY_CHANGED"
RULE_ID = "A-FI-SYNC-001"
RULE_VERSION = "1"
FIELD_RULE_ID = "A-FI-SYNC-001.FIELD_SIGNATURE"
FIELD_RULE_VERSION = "1"
KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE = "KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE"
KNOWN_MALFORMED_AMOUNT_BITS = 0x00400000
TRUSTED_CAS_RULE_ID = "A-SYNC-CAS-LOCAL-REUSE-001"
TRUSTED_CAS_RULE_VERSION = "1"
TRUSTED_CAS_TARGET_DATE = "20260907"
TRUSTED_CAS_INPUTS_ENV = "V35_A_SYNC_TRUSTED_CAS_INPUTS"

_COMPAT_FAILURE_TYPES = {
    EMPTY_RESPONSE: "empty_response",
    PROTOCOL_RESPONSE_MALFORMED: PROTOCOL_RESPONSE_MALFORMED,
    TARGET_DATE_MISSING: "target_date_missing",
    DUPLICATE_DATE: "duplicate_date",
    NON_MONOTONIC_DATE: "non_monotonic_date",
    CROSS_DAY_CLOSE_RATIO: "continuity_close_ratio",
    OUT_OF_SCOPE_AFTER_TARGET_DATE: "out_of_scope_after_target_date",
    SOURCE_DATE_AFTER_TARGET: "source_date_after_target",
    SOURCE_IDENTITY_CHANGED: "source_identity_changed",
}
_TERMINAL_CONTENT_FAILURE_CODES = {
    EMPTY_RESPONSE,
    TARGET_DATE_MISSING,
    DUPLICATE_DATE,
    NON_MONOTONIC_DATE,
    CROSS_DAY_CLOSE_RATIO,
    OUT_OF_SCOPE_AFTER_TARGET_DATE,
    SOURCE_DATE_AFTER_TARGET,
    INVALID_BAR,
    SOURCE_IDENTITY_CHANGED,
    KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
    "ACTION_REFERENCE_IDENTITY_MISMATCH",
}
# An empty provider payload is transient at the route layer. It remains a
# typed quarantine for the current symbol, while the next symbol may reuse the
# healthy session and host. A later bounded run reopens the empty symbol.
_RETRYABLE_CONTENT_FAILURE_CODES = {EMPTY_RESPONSE}
_NONRETRYABLE_CONTENT_FAILURE_CODES = _TERMINAL_CONTENT_FAILURE_CODES - _RETRYABLE_CONTENT_FAILURE_CODES
MARKET_BY_PREFIX = {
    "sh": 1,
    "sz": 0,
    "bj": 2,
}
EQUITY_CODE_PREFIXES_BY_MARKET = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("8", "9"),
}
DIR_BY_MARKET = {
    "a": [("sh", TDX_ROOT / "vipdoc" / "sh" / "lday"), ("sz", TDX_ROOT / "vipdoc" / "sz" / "lday")],
    "bj": [("bj", TDX_ROOT / "vipdoc" / "bj" / "lday")],
}


@dataclass(frozen=True)
class DailyTarget:
    """One immutable local A-share daily-file target."""

    code: str
    market: int
    path: Path


class SyncTimeoutError(RuntimeError):
    """A bounded A-sync operation exceeded its local wall-clock budget."""

    def __init__(
        self,
        scope: str,
        deadline_seconds: float,
        elapsed_seconds: float,
        *,
        unsupported_context: bool = False,
    ) -> None:
        self.scope = str(scope).upper()
        self.deadline_seconds = float(deadline_seconds)
        self.elapsed_seconds = float(elapsed_seconds)
        self.unsupported_context = bool(unsupported_context)
        super().__init__(
            f"A_SYNC_TIMEOUT:{self.scope}:elapsed={self.elapsed_seconds:.6f}"
            f":deadline={self.deadline_seconds:.6f}"
        )


def _positive_budget(value: Any, name: str) -> float:
    try:
        budget = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite positive number") from error
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return budget


@contextlib.contextmanager
def _deadline_guard(seconds: float, *, scope: str) -> Any:
    """Interrupt one synchronous SDK call without leaving a worker thread.

    The native lane is serial and runs on the main thread.  ``SIGALRM`` is
    therefore the only cancellation mechanism used here: it interrupts the
    socket or provider call in place and is always restored in ``finally``.
    A caller without that native main-thread deadline primitive fails before
    entering the provider call; a post-call check cannot truthfully claim an
    in-call wall-clock bound.
    """
    budget = _positive_budget(seconds, "deadline_seconds")
    started = time.monotonic()
    can_alarm = (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )
    if not can_alarm:
        raise SyncTimeoutError(
            f"{scope}_UNSUPPORTED_CONTEXT",
            budget,
            0.0,
            unsupported_context=True,
        )
    previous_handler: Any = None
    previous_timer: tuple[float, float] | None = None
    if can_alarm:
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)

        def _alarm_handler(_signum: int, _frame: Any) -> None:
            raise SyncTimeoutError(scope, budget, time.monotonic() - started)

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        if can_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer and previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        if elapsed > budget:
            raise SyncTimeoutError(scope, budget, elapsed)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Atomically persist a small progress/receipt object in its parent."""
    ensure_dir(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _target_scope_fingerprint(targets: list[DailyTarget]) -> str:
    descriptors = [
        {
            "code": str(item.code),
            "market": int(item.market),
            "path": str(Path(item.path).resolve()),
        }
        for item in targets
    ]
    descriptors.sort(key=lambda item: (item["code"], item["market"], item["path"]))
    encoded = json.dumps(descriptors, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _target_scope_keys(targets: Iterable[DailyTarget]) -> list[dict[str, Any]]:
    """Return the exact identity set carried by the sync receipt."""
    keys = [
        {
            "symbol": str(item.code),
            "market": int(item.market),
            "path": str(Path(item.path).resolve()),
        }
        for item in targets
    ]
    return sorted(keys, key=lambda item: (item["symbol"], item["market"], item["path"]))


def _validate_target_scope(targets: list[DailyTarget]) -> None:
    """Reject ambiguous duplicate target identities before provider work."""
    keys = [(str(item.code), int(item.market), str(Path(item.path).resolve())) for item in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("A_SYNC_TARGET_SCOPE_DUPLICATE")


def _path_has_symlink_component(path: Path) -> bool:
    """Return whether a target path or any existing ancestor is a symlink.

    ``Path.exists()`` is false for a dangling symlink, so callers must inspect
    the link bit before using existence or opening the path.  Checking every
    component also prevents a regular-looking leaf from writing through a
    linked directory into an unrelated source tree.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor or "/")
    for part in candidate.parts[1:] if candidate.anchor else candidate.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _local_path_failure(path: Path) -> str | None:
    """Validate a local source path before reading or appending bytes."""
    if _path_has_symlink_component(path):
        return f"{INVALID_BAR}:source_symlink"
    try:
        if path.exists() and not path.is_file():
            return f"{INVALID_BAR}:source_not_regular"
    except OSError as error:
        return f"{INVALID_BAR}:source_stat:{error!r}"
    return None


def _file_sha256(path: Path) -> str | None:
    """Return the current regular-file identity without following symlinks."""
    try:
        if _local_path_failure(path) is not None or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _trusted_cas_sha256(value: Any, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"A_SYNC_TRUSTED_CAS_INVALID_SHA:{label}")
    return digest


def _trusted_cas_read_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute() or _path_has_symlink_component(path) or not path.is_file():
        raise ValueError(f"A_SYNC_TRUSTED_CAS_INVALID_PATH:{label}")
    observed_sha = _file_sha256(path)
    if observed_sha != expected_sha256:
        raise ValueError(f"A_SYNC_TRUSTED_CAS_SHA_DRIFT:{label}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"A_SYNC_TRUSTED_CAS_INVALID_JSON:{label}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"A_SYNC_TRUSTED_CAS_OBJECT_REQUIRED:{label}")
    return payload


def _trusted_cas_safety_ok(payload: Mapping[str, Any]) -> bool:
    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        safety = payload
    return (
        safety.get("RESEARCH_ONLY") is True
        and safety.get("production_allowed") is False
        and safety.get("buy_gate_updated") is False
        and safety.get("orders_sent") is False
    )


def _trusted_cas_map(
    payload: Mapping[str, Any],
    *,
    label: str,
    expected_count: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Read one accepted CAS stage without rescanning it per target symbol."""
    apply = payload.get("apply") if isinstance(payload.get("apply"), Mapping) else payload
    candidate = apply.get("candidate_sha256_per_symbol")
    after = apply.get("after_sha256_per_symbol")
    before = apply.get("native_before_sha256_per_symbol")
    symbols = apply.get("applied_symbols")
    if not isinstance(candidate, Mapping) or not isinstance(after, Mapping) or not isinstance(before, Mapping):
        raise ValueError(f"A_SYNC_TRUSTED_CAS_MISSING_MAP:{label}")
    if not isinstance(symbols, list) or len(symbols) != expected_count:
        raise ValueError(f"A_SYNC_TRUSTED_CAS_COUNT_MISMATCH:{label}")
    symbol_set = {str(symbol) for symbol in symbols}
    if len(symbol_set) != expected_count or set(candidate) != symbol_set or set(after) != symbol_set or set(before) != symbol_set:
        raise ValueError(f"A_SYNC_TRUSTED_CAS_SYMBOL_SET_MISMATCH:{label}")
    indexed: dict[str, dict[str, Any]] = {}
    for raw_symbol in sorted(symbol_set):
        symbol = str(raw_symbol)
        candidate_sha = _trusted_cas_sha256(candidate.get(symbol), f"{label}.{symbol}.candidate")
        after_sha = _trusted_cas_sha256(after.get(symbol), f"{label}.{symbol}.after")
        before_sha = _trusted_cas_sha256(before.get(symbol), f"{label}.{symbol}.before")
        if candidate_sha != after_sha:
            raise ValueError(f"A_SYNC_TRUSTED_CAS_AFTER_MISMATCH:{label}:{symbol}")
        indexed[symbol] = {
            "symbol": symbol,
            "candidate_after_sha256": candidate_sha,
            "native_before_sha256": before_sha,
            "receipt_path": str(payload.get("_receipt_path") or ""),
            "receipt_sha256": str(payload.get("_receipt_sha256") or ""),
            "cohort": label,
        }
    return indexed, {symbol: str(symbol) for symbol in sorted(symbol_set)}


def _trusted_cas_load_inputs(
    path_value: Path | str | None,
    target_int: int,
    expected_target_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Load reviewed CAS references once; ignore them for an uncovered date."""
    if path_value in (None, ""):
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute() or _path_has_symlink_component(path) or not path.is_file():
        raise ValueError(f"A_SYNC_TRUSTED_CAS_INPUTS_PATH_INVALID:{path}")
    config_sha = _file_sha256(path)
    if config_sha is None:
        raise ValueError("A_SYNC_TRUSTED_CAS_INPUTS_SHA_UNAVAILABLE")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("A_SYNC_TRUSTED_CAS_INPUTS_INVALID_JSON") from error
    if not isinstance(config, dict) or config.get("schema_version") != "v3_5.a_sync.trusted_cas_inputs.v1":
        raise ValueError("A_SYNC_TRUSTED_CAS_INPUTS_SCHEMA_MISMATCH")
    # A global environment variable may remain installed for a later date. It
    # is deliberately inert when the receipt's exact target date is absent.
    if str(config.get("target_date") or "") != str(target_int):
        return None
    if str(config.get("target_date")) != TRUSTED_CAS_TARGET_DATE:
        raise ValueError("A_SYNC_TRUSTED_CAS_TARGET_DATE_MISMATCH")
    config_fingerprint = str(config.get("target_fingerprint") or "").lower()
    if len(config_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in config_fingerprint):
        raise ValueError("A_SYNC_TRUSTED_CAS_TARGET_FINGERPRINT_INVALID")
    if expected_target_fingerprint is not None and config_fingerprint != str(expected_target_fingerprint).lower():
        raise ValueError("A_SYNC_TRUSTED_CAS_TARGET_FINGERPRINT_MISMATCH")
    if config.get("rule_id") != TRUSTED_CAS_RULE_ID or str(config.get("rule_version")) != TRUSTED_CAS_RULE_VERSION:
        raise ValueError("A_SYNC_TRUSTED_CAS_RULE_MISMATCH")
    if config.get("field_rule_id") != FIELD_RULE_ID or str(config.get("field_rule_version")) != FIELD_RULE_VERSION:
        raise ValueError("A_SYNC_TRUSTED_CAS_FIELD_RULE_MISMATCH")
    if not _trusted_cas_safety_ok(config):
        raise ValueError("A_SYNC_TRUSTED_CAS_SAFETY_MISMATCH")

    old_spec = config.get("old4662")
    new_spec = config.get("new483")
    if not isinstance(old_spec, Mapping) or not isinstance(new_spec, Mapping):
        raise ValueError("A_SYNC_TRUSTED_CAS_COHORT_CONFIG_MISSING")
    old_expected = int(old_spec.get("expected_count", 0))
    new_expected = int(new_spec.get("expected_count", 0))
    if old_expected != 4662 or new_expected != 483:
        raise ValueError("A_SYNC_TRUSTED_CAS_COHORT_COUNT_MISMATCH")

    old_ref = old_spec.get("integration_receipt")
    if not isinstance(old_ref, Mapping):
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_REF_MISSING")
    old_path = Path(str(old_ref.get("path") or ""))
    old_sha = _trusted_cas_sha256(old_ref.get("sha256"), "old4662.receipt")
    old_receipt = _trusted_cas_read_json(old_path, old_sha, "old4662.receipt")
    old_receipt["_receipt_path"] = str(old_path)
    old_receipt["_receipt_sha256"] = old_sha
    if old_receipt.get("schema_version") != "v3_5.static_cas.parent_native_integration.v1" or old_receipt.get("status") != "APPLIED_RECONCILED_AWAITING_INDEPENDENT_INTEGRATION_REVIEW":
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_STATUS_INVALID")
    if int(old_receipt.get("applied_count", -1)) != old_expected or int(old_receipt.get("native_after_sha_match_count", -1)) != old_expected:
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_COUNT_INVALID")
    if not _trusted_cas_safety_ok(old_receipt):
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_RECEIPT_SAFETY_INVALID")
    old_entries: dict[str, dict[str, Any]] = {}
    stage_refs = old_receipt.get("stage_receipts")
    if not isinstance(stage_refs, list) or len(stage_refs) != 2:
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_STAGE_REFS_INVALID")
    for stage_ref in stage_refs:
        if not isinstance(stage_ref, Mapping):
            raise ValueError("A_SYNC_TRUSTED_CAS_OLD_STAGE_REF_INVALID")
        stage_path = Path(str(stage_ref.get("path") or ""))
        stage_sha = _trusted_cas_sha256(stage_ref.get("sha256"), "old4662.stage")
        stage = _trusted_cas_read_json(stage_path, stage_sha, "old4662.stage")
        stage["_receipt_path"] = str(stage_path)
        stage["_receipt_sha256"] = stage_sha
        if stage.get("schema_version") != "v3_5.static_byte_cas.staged_stage_receipt.v1" or stage.get("status") != "APPLIED":
            raise ValueError("A_SYNC_TRUSTED_CAS_OLD_STAGE_STATUS_INVALID")
        stage_count = int(stage.get("stage_member_count", -1))
        stage_entries, _ = _trusted_cas_map(stage, label="old4662", expected_count=stage_count)
        if stage_count <= 0 or set(old_entries) & set(stage_entries):
            raise ValueError("A_SYNC_TRUSTED_CAS_OLD_STAGE_OVERLAP")
        summaries = stage.get("member_summaries")
        if not isinstance(summaries, list) or len(summaries) != stage_count:
            raise ValueError("A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_INVALID")
        summary_by = {str(row.get("symbol")): row for row in summaries if isinstance(row, Mapping)}
        if len(summary_by) != stage_count or not set(stage_entries).issubset(summary_by):
            raise ValueError("A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_SCOPE_INVALID")
        for symbol, entry in stage_entries.items():
            summary = summary_by[symbol]
            record_count = summary.get("record_count")
            if (
                str(summary.get("candidate_sha256")) != entry["candidate_after_sha256"]
                or str(summary.get("native_path")) == ""
                or not isinstance(record_count, int)
                or record_count <= 0
            ):
                raise ValueError(f"A_SYNC_TRUSTED_CAS_OLD_MEMBER_SUMMARY_BINDING:{symbol}")
            entry["native_path"] = str(Path(str(summary["native_path"])).resolve())
            entry["candidate_path"] = str(summary.get("candidate_path") or "")
            entry["record_count"] = int(record_count)
        old_entries.update(stage_entries)
    if len(old_entries) != old_expected:
        raise ValueError("A_SYNC_TRUSTED_CAS_OLD_INDEX_COUNT_INVALID")

    new_refs = {
        key: new_spec.get(key)
        for key in ("native_apply_result", "candidate_manifest", "cohort_review")
    }
    if any(not isinstance(value, Mapping) for value in new_refs.values()):
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_REF_MISSING")
    new_paths = {key: Path(str(value.get("path") or "")) for key, value in new_refs.items()}
    new_shas = {key: _trusted_cas_sha256(value.get("sha256"), f"new483.{key}") for key, value in new_refs.items()}
    new_result = _trusted_cas_read_json(new_paths["native_apply_result"], new_shas["native_apply_result"], "new483.native_apply_result")
    new_result["_receipt_path"] = str(new_paths["native_apply_result"])
    new_result["_receipt_sha256"] = new_shas["native_apply_result"]
    if new_result.get("schema_version") != "v35.remaining_ohlc_integration.executor_receipt.v1" or new_result.get("status") != "APPLIED_RECONCILED_AWAITING_SCHEDULER_RESTORE" or new_result.get("pass_signal") is not True or new_result.get("native_integration_status") != "APPLIED_RECONCILED":
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_STATUS_INVALID")
    if not _trusted_cas_safety_ok(new_result) or int((new_result.get("apply") or {}).get("applied_count", -1)) != new_expected:
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_SAFETY_OR_COUNT_INVALID")
    checks = new_result.get("checks")
    if not isinstance(checks, Mapping) or checks.get("independent_cohort_review_receipt_sha256") != new_shas["cohort_review"] or checks.get("candidate_manifest_sha256") != new_shas["candidate_manifest"]:
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_RECEIPT_BINDING_INVALID")
    review = _trusted_cas_read_json(new_paths["cohort_review"], new_shas["cohort_review"], "new483.cohort_review")
    verdict = review.get("verdict")
    oracles = review.get("cohort_oracles")
    bound = review.get("bound_artifacts")
    bound_manifest = bound.get("candidate_manifest") if isinstance(bound, Mapping) else None
    if (
        review.get("schema_version") != "v35.remaining_ohlc.cohort_review.v2"
        or review.get("reviewer") != "a_ohlc_canary_review"
        or not isinstance(verdict, Mapping)
        or verdict.get("REVIEWED") != "PASS"
        or verdict.get("overall") != "PASS_FROZEN_COHORT_AND_INTEGRATION_METADATA_ONLY"
        or not isinstance(oracles, Mapping)
        or oracles.get("all_oracles_pass") is not True
        or oracles.get("candidate_pass_symbols") != new_expected
        or not isinstance(bound, Mapping)
        or not isinstance(bound_manifest, Mapping)
        or bound_manifest.get("sha256") != new_shas["candidate_manifest"]
    ):
        raise ValueError("A_SYNC_TRUSTED_CAS_COHORT_REVIEW_INVALID")
    manifest = _trusted_cas_read_json(new_paths["candidate_manifest"], new_shas["candidate_manifest"], "new483.candidate_manifest")
    candidates = manifest.get("candidates")
    if manifest.get("schema_version") != "v3_5.remaining_ohlc_cohort.candidate_manifest.v1" or manifest.get("candidate_count") != new_expected or not isinstance(candidates, list) or len(candidates) != new_expected:
        raise ValueError("A_SYNC_TRUSTED_CAS_CANDIDATE_MANIFEST_INVALID")
    manifest_by: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("A_SYNC_TRUSTED_CAS_CANDIDATE_ROW_INVALID")
        symbol = str(candidate.get("symbol") or "")
        if not symbol or symbol in manifest_by or candidate.get("status") != "CANDIDATE_PASS" or candidate.get("strict_gate_status") != "PASS":
            raise ValueError("A_SYNC_TRUSTED_CAS_CANDIDATE_ROW_NOT_ACCEPTED")
        candidate_sha = _trusted_cas_sha256(candidate.get("candidate_sha256"), f"new483.{symbol}.candidate")
        after_sha = _trusted_cas_sha256(candidate.get("after_sha256"), f"new483.{symbol}.after")
        native_before_sha = _trusted_cas_sha256(candidate.get("native_before_sha256"), f"new483.{symbol}.before")
        gate_results = candidate.get("gate_results")
        if (
            candidate_sha != after_sha
            or not isinstance(gate_results, Mapping)
            or gate_results.get("full_candidate_gate") is not True
            or not isinstance(candidate.get("native_path"), str)
        ):
            raise ValueError(f"A_SYNC_TRUSTED_CAS_CANDIDATE_BINDING_INVALID:{symbol}")
        manifest_by[symbol] = {
            "symbol": symbol,
            "candidate_after_sha256": candidate_sha,
            "native_before_sha256": native_before_sha,
            "native_path": str(Path(candidate["native_path"]).resolve()),
            "candidate_path": str(candidate.get("candidate_path") or ""),
            "cohort": "new483",
            "receipt_path": str(new_paths["native_apply_result"]),
            "receipt_sha256": new_shas["native_apply_result"],
            "cohort_review_path": str(new_paths["cohort_review"]),
            "cohort_review_sha256": new_shas["cohort_review"],
            "candidate_manifest_path": str(new_paths["candidate_manifest"]),
            "candidate_manifest_sha256": new_shas["candidate_manifest"],
            "record_count": int(candidate.get("native_record_count", 0)),
        }
        if manifest_by[symbol]["record_count"] <= 0:
            raise ValueError(f"A_SYNC_TRUSTED_CAS_CANDIDATE_RECORD_COUNT_INVALID:{symbol}")
    new_entries: dict[str, dict[str, Any]] = {}
    new_apply = new_result.get("apply")
    if not isinstance(new_apply, Mapping):
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_APPLY_MISSING")
    for stage_name in ("canary", "remainder"):
        stage = new_apply.get(stage_name)
        if not isinstance(stage, Mapping):
            raise ValueError("A_SYNC_TRUSTED_CAS_NEW_STAGE_MISSING")
        stage_entries, _ = _trusted_cas_map(stage, label="new483", expected_count=int(stage.get("applied_count", -1)))
        if set(new_entries) & set(stage_entries):
            raise ValueError("A_SYNC_TRUSTED_CAS_NEW_STAGE_OVERLAP")
        for symbol, stage_entry in stage_entries.items():
            manifest_entry = manifest_by.get(symbol)
            if manifest_entry is None or manifest_entry["candidate_after_sha256"] != stage_entry["candidate_after_sha256"] or manifest_entry["native_before_sha256"] != stage_entry["native_before_sha256"]:
                raise ValueError(f"A_SYNC_TRUSTED_CAS_NEW_MANIFEST_BINDING:{symbol}")
            new_entries[symbol] = dict(manifest_entry)
    if len(new_entries) != new_expected:
        raise ValueError("A_SYNC_TRUSTED_CAS_NEW_INDEX_COUNT_INVALID")
    if set(old_entries) & set(new_entries):
        raise ValueError("A_SYNC_TRUSTED_CAS_COHORT_OVERLAP")
    indexed = dict(old_entries)
    indexed.update(new_entries)
    return {
        "schema_version": config["schema_version"],
        "config_path": str(path),
        "config_sha256": config_sha,
        "target_date": str(target_int),
        "target_fingerprint": str(config.get("target_fingerprint") or ""),
        "rule_id": TRUSTED_CAS_RULE_ID,
        "rule_version": TRUSTED_CAS_RULE_VERSION,
        "field_rule_id": FIELD_RULE_ID,
        "field_rule_version": FIELD_RULE_VERSION,
        "entries": indexed,
        "cohort_counts": {"old4662": len(old_entries), "new483": len(new_entries), "total": len(indexed)},
    }


def _trusted_cas_local_reuse(
    index: Mapping[str, Any] | None,
    target: DailyTarget,
    target_int: int,
    current_sha: str | None,
    history: Sequence[Mapping[str, Any]],
    history_failure: str | None,
    field_violations: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return a receipt-bound no-provider reuse only after strict local gates."""
    if not isinstance(index, Mapping) or str(index.get("target_date")) != str(target_int):
        return None
    if history_failure is not None or field_violations or not history or day_int(dict(history[-1])) != target_int:
        return None
    valid, _reason = valid_hq_bar(dict(history[-1]))
    if not valid or not current_sha:
        return None
    # Re-read the file identity after the full history scan so a concurrent
    # native mutation cannot be accepted under the digest captured before the
    # scan.
    verified_sha = _file_sha256(Path(target.path))
    if verified_sha is None or verified_sha.lower() != current_sha.lower():
        return None
    entry = (index.get("entries") or {}).get(str(target.code))
    if not isinstance(entry, Mapping):
        return None
    if str(Path(str(entry.get("native_path") or "")).resolve()) != str(Path(target.path).resolve()):
        return None
    candidate_sha = str(entry.get("candidate_after_sha256") or "").lower()
    if len(candidate_sha) != 64 or verified_sha.lower() != candidate_sha:
        return None
    expected_record_count = entry.get("record_count")
    if not isinstance(expected_record_count, int) or expected_record_count <= 0 or len(history) != expected_record_count:
        return None
    if str(entry.get("cohort") or "") not in {"old4662", "new483"}:
        return None
    return entry


# Optional, SHA-pinned correction of the comparison denominator only.
# These two event identities/terms are the full reviewed scope; prices remain raw.
ACTION_REFERENCE_MANIFEST_ENV = "V35_A_SYNC_ACTION_REFERENCE_MANIFEST"
ACTION_REFERENCE_SHA256_ENV = "V35_A_SYNC_ACTION_REFERENCE_SHA256"
ACTION_REFERENCE_IDENTITY_MISMATCH = "ACTION_REFERENCE_IDENTITY_MISMATCH"
_ACTION_REFERENCE_CONTEXT: dict[str, Any] | None = None
_ACTION_REFERENCE_AUDIT: list[dict[str, Any]] = []
_ACTION_REFERENCE_TERMS = {
    ("301550", 0, 20260529): (20260528, 0.30, 0.45, 0.45, 0.0),
    ("688489", 1, 20260527): (20260526, 0.0, 0.47, 0.48, 0.0),
}


class ActionReferenceError(ValueError):
    """Invalid configuration or drifted identity; never an unconditional waiver."""


def _action_reference_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ActionReferenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _action_reference_read(ref: Mapping[str, Any]) -> bytes:
    path = Path(str(ref["path"]))
    digest = ref["sha256"]
    if (not path.is_absolute() or _path_has_symlink_component(path)
            or not path.is_file() or not isinstance(digest, str)
            or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ActionReferenceError("invalid artifact identity")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ActionReferenceError(f"artifact SHA mismatch: {path}")
    return data


def _load_action_reference_manifest(
    path: Path | str | None, expected_sha256: str | None,
) -> dict[str, Any] | None:
    if path in (None, "") and expected_sha256 in (None, ""):
        return None
    if path in (None, "") or expected_sha256 in (None, ""):
        raise ActionReferenceError("manifest path and SHA must be configured together")
    data = _action_reference_read({"path": str(path), "sha256": expected_sha256})
    def nonfinite(_value: str) -> Any:
        raise ActionReferenceError("non-finite JSON value")
    try:
        payload = json.loads(data, object_pairs_hook=_action_reference_json_pairs,
                             parse_constant=nonfinite)
    except (TypeError, json.JSONDecodeError) as error:
        raise ActionReferenceError("invalid manifest JSON") from error
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "events"}
            or payload["schema_version"] != "v192.action_reference.v1"
            or not isinstance(payload["events"], list) or not payload["events"]):
        raise ActionReferenceError("invalid manifest schema")
    indexed: dict[tuple[str, int, int], dict[str, Any]] = {}
    event_keys = {"code", "market", "event_date", "prior_date", "prior_close",
                  "event_close", "prior_bar_sha256", "event_bar_sha256", "terms", "evidence", "source_response"}
    term_keys = {"cash_per_share", "share_change_ratio", "nominal_share_ratio", "rights_price"}
    for event in payload["events"]:
        if not isinstance(event, dict) or set(event) != event_keys:
            raise ActionReferenceError("invalid event schema")
        code, market, date = event["code"], event["market"], event["event_date"]
        if (not isinstance(code, str) or len(code) != 6 or not code.isascii()
                or not code.isdigit() or type(market) is not int or type(date) is not int):
            raise ActionReferenceError("invalid exact code/market/date")
        key = (code, market, date)
        expected = _ACTION_REFERENCE_TERMS.get(key)
        if expected is None or key in indexed:
            raise ActionReferenceError("unsupported or duplicate event identity")
        for field in ("prior_bar_sha256", "event_bar_sha256"):
            digest = event[field]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ActionReferenceError("invalid exact bar identity")
        terms = event["terms"]
        if not isinstance(terms, dict) or set(terms) != term_keys:
            raise ActionReferenceError("invalid terms schema")
        values = [terms[k] for k in ("cash_per_share", "share_change_ratio", "nominal_share_ratio", "rights_price")]
        if (type(event["prior_date"]) is not int or event["prior_date"] != expected[0]
                or any(not _is_finite_real(v) or float(v) < 0 for v in values)
                or tuple(float(v) for v in values) != expected[1:]
                or any(not _is_finite_real(event[k]) or float(event[k]) <= 0
                       for k in ("prior_close", "event_close"))
                or float(event["prior_close"]) <= float(terms["cash_per_share"])):
            raise ActionReferenceError("invalid prior identity or official terms")
        evidence = event["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ActionReferenceError("official evidence required")
        for ref in evidence:
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256", "url", "pdf_pages"}
                    or not isinstance(ref["url"], str)
                    or not ref["url"].startswith(("https://disc.static.szse.cn/", "https://docs.static.szse.cn/", "https://dataclouds.cninfo.com.cn/"))
                    or "*" in ref["url"] or not isinstance(ref["pdf_pages"], list)
                    or not ref["pdf_pages"] or any(type(v) is not int or v <= 0 for v in ref["pdf_pages"])):
                raise ActionReferenceError("invalid official evidence reference")
            if not _action_reference_read(ref).startswith(b"%PDF-"):
                raise ActionReferenceError("evidence is not PDF")
        ref = event["source_response"]
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "request", "observed_at"}:
            raise ActionReferenceError("invalid response identity")
        response = json.loads(_action_reference_read(ref))
        request = ref["request"]
        if (not isinstance(request, dict)
                or request != {"category": 9, "market": market, "code": code, "start": 0,
                               "count": 800, "target_date": 20261020,
                               "previous_close": None, "after_date": None}
                or response.get("request") != request
                or not isinstance(ref["observed_at"], str)
                or response.get("observed_at") != ref["observed_at"]):
            raise ActionReferenceError("response request/time identity mismatch")
        try:
            datetime.fromisoformat(ref["observed_at"])
            pair = {d: [bar for bar in response["response_rows"] if day_int(bar) == d]
                    for d in (event["prior_date"], date)}
            if (any(len(bars) != 1 for bars in pair.values())
                    or float(pair[event["prior_date"]][0]["close"]) != float(event["prior_close"])
                    or float(pair[date][0]["close"]) != float(event["event_close"])
                    or hashlib.sha256(pack_hq_bar(pair[event["prior_date"]][0])).hexdigest() != event["prior_bar_sha256"]
                    or hashlib.sha256(pack_hq_bar(pair[date][0])).hexdigest() != event["event_bar_sha256"]):
                raise ActionReferenceError("response event pair identity mismatch")
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ActionReferenceError):
                raise
            raise ActionReferenceError("invalid response event pair") from error
        indexed[key] = event
    return {"path": str(path), "sha256": expected_sha256, "events": indexed}


def _action_reference_target(path: Path) -> tuple[str, int] | None:
    stem = Path(path).stem
    if len(stem) == 8 and stem[:2] in MARKET_BY_PREFIX and stem[2:].isascii() and stem[2:].isdigit():
        return stem[2:], MARKET_BY_PREFIX[stem[:2]]
    return None


def _continuity_reference(
    references: Mapping[str, Any] | None, code: str, market: int,
    prior_date: int | None, prior_close: float, event_date: int, event_close: float,
    audit: list[dict[str, Any]] | None = None,
    prior_bar: Mapping[str, Any] | None = None, event_bar: Mapping[str, Any] | None = None,
) -> float:
    if references is None:
        return prior_close
    event = references["events"].get((code, market, event_date))
    if event is None:
        return prior_close
    terms = event["terms"]
    reference = ((prior_close - terms["cash_per_share"]
                  + terms["rights_price"] * terms["share_change_ratio"])
                 / (1.0 + terms["share_change_ratio"]))
    try:
        prior_digest = hashlib.sha256(pack_hq_bar(dict(prior_bar))).hexdigest() if prior_bar is not None else None
        event_digest = hashlib.sha256(pack_hq_bar(dict(event_bar))).hexdigest() if event_bar is not None else None
    except (KeyError, TypeError, ValueError, OverflowError, struct.error):
        prior_digest, event_digest = None, None
    valid = (prior_digest == event["prior_bar_sha256"] and event_digest == event["event_bar_sha256"]
             and prior_date == event["prior_date"] and prior_close == event["prior_close"]
             and event_close == event["event_close"] and math.isfinite(reference) and reference > 0)
    row = {"code": code, "market": market, "event_date": event_date,
           "prior_date": prior_date, "prior_close": prior_close, "event_close": event_close,
           "expected_prior_date": event["prior_date"], "expected_prior_close": event["prior_close"],
           "expected_event_close": event["event_close"], "calculated_reference": reference,
           "reference_used": reference if valid else None,
           "identity_match": valid, "manifest_sha256": references["sha256"],
           "prior_bar_sha256": prior_digest, "event_bar_sha256": event_digest}
    if audit is not None:
        audit.append(row)
    if not valid:
        raise ActionReferenceError(ACTION_REFERENCE_IDENTITY_MISMATCH)
    return reference


def _observed_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _is_finite_real(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _field_rule_identity_current(value: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(value, Mapping)
        and str(value.get("field_rule_id") or "") == FIELD_RULE_ID
        and str(value.get("field_rule_version") or "") == FIELD_RULE_VERSION
    )


def _has_known_malformed_amount_volume_signature(raw: bytes) -> bool:
    """Match only the frozen native 32-byte amount/volume signature."""
    if len(raw) != DAY_STRUCT.size:
        return False
    amount_bits = struct.unpack_from("<I", raw, 20)[0]
    volume_raw = struct.unpack_from("<I", raw, 24)[0]
    return amount_bits == KNOWN_MALFORMED_AMOUNT_BITS and volume_raw == 0


def _field_signature_violation(
    *,
    symbol: str,
    market: int,
    date_value: int,
    row_index: int,
    raw: bytes,
    source_ref: str,
    source_file_sha256: str | None,
    native_path: str | None,
    run_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "symbol": str(symbol),
        "market": int(market),
        "date": int(date_value),
        "row_index": int(row_index),
        "native_path": native_path,
        "source_ref": source_ref,
        "source_file_sha256": source_file_sha256,
        "native_file_sha256": source_file_sha256,
        "raw_row_sha256": hashlib.sha256(raw).hexdigest(),
        "amount_bits": f"0x{struct.unpack_from('<I', raw, 20)[0]:08x}",
        "volume_raw_uint32": struct.unpack_from("<I", raw, 24)[0],
        "reason_code": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
        "field_rule_id": FIELD_RULE_ID,
        "field_rule_version": FIELD_RULE_VERSION,
        "run_id": run_id,
        "recorded_at": recorded_at,
        "transform_applied": False,
    }


def _local_field_signature_violations(
    path: Path,
    *,
    symbol: str,
    market: int,
    run_id: str,
    recorded_at: str,
) -> list[dict[str, Any]]:
    """Scan every existing native record without decoding away raw bits."""
    if _local_path_failure(path) is not None or not path.exists():
        return []
    try:
        raw_file = path.read_bytes()
    except OSError:
        return []
    if len(raw_file) % DAY_STRUCT.size:
        return []
    source_sha256 = hashlib.sha256(raw_file).hexdigest()
    violations: list[dict[str, Any]] = []
    for row_index, offset in enumerate(range(0, len(raw_file), DAY_STRUCT.size)):
        raw = raw_file[offset : offset + DAY_STRUCT.size]
        if not _has_known_malformed_amount_volume_signature(raw):
            continue
        date_value = struct.unpack_from("<I", raw, 0)[0]
        violations.append(
            _field_signature_violation(
                symbol=symbol,
                market=market,
                date_value=date_value,
                row_index=row_index,
                raw=raw,
                source_ref=f"{path}:byte_offset={offset}",
                source_file_sha256=source_sha256,
                native_path=str(path),
                run_id=run_id,
                recorded_at=recorded_at,
            )
        )
    return violations


def _provider_field_signature_violation(
    bar: Mapping[str, Any],
    *,
    symbol: str,
    market: int,
    row_index: int,
    run_id: str,
    recorded_at: str,
) -> dict[str, Any] | None:
    try:
        raw = pack_hq_bar(dict(bar))
    except (KeyError, TypeError, ValueError, OverflowError, struct.error):
        return None
    if not _has_known_malformed_amount_volume_signature(raw):
        return None
    return _field_signature_violation(
        symbol=symbol,
        market=market,
        date_value=day_int(dict(bar)),
        row_index=row_index,
        raw=raw,
        source_ref=f"provider:{symbol}:response_index={row_index}",
        source_file_sha256=None,
        native_path=None,
        run_id=run_id,
        recorded_at=recorded_at,
    )


def _bars_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Compare a revalidated target bar without introducing a rewrite path."""
    try:
        if day_int(dict(left)) != day_int(dict(right)):
            return False
        for key in ("open", "high", "low", "close"):
            if not math.isclose(float(left[key]), float(right[key]), rel_tol=1e-9, abs_tol=0.005):
                return False
        for key in ("amount", "vol"):
            if not math.isclose(float(left[key]), float(right[key]), rel_tol=1e-6, abs_tol=1e-6):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _local_history_status(
    path: Path, target_date: int, *, action_references: Mapping[str, Any] | None = None,
    symbol: str | None = None, market: int | None = None,
    reference_audit: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Validate existing source bytes before an accepted-only handoff.

    The formula reader currently keeps the last duplicate key.  This gate
    audits the source in its original order first, so a malformed local file
    is quarantined instead of being silently repaired by a downstream reader.
    """
    path_failure = _local_path_failure(path)
    if path_failure is not None:
        return [], path_failure
    if not path.exists():
        return [], None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size % DAY_STRUCT.size:
            return [], f"{INVALID_BAR}:source_file_shape"
        bars = read_hq_day_bars(path)
    except (OSError, ValueError, struct.error) as error:
        return [], f"{INVALID_BAR}:source_read:{error!r}"
    references = action_references if action_references is not None else _ACTION_REFERENCE_CONTEXT
    audit = reference_audit if reference_audit is not None else _ACTION_REFERENCE_AUDIT
    identity = (symbol, market) if symbol is not None and market is not None else _action_reference_target(path)
    if references is not None and identity is None:
        return bars, ACTION_REFERENCE_IDENTITY_MISMATCH
    dates: list[int] = []
    previous_close: float | None = None
    previous_bar: Mapping[str, Any] | None = None
    for bar in bars:
        valid, reason = valid_hq_bar(bar)
        if not valid:
            return bars, f"{INVALID_BAR}:source_{reason}"
        date_value = day_int(bar)
        if dates and date_value == dates[-1]:
            return bars, DUPLICATE_DATE
        if dates and date_value < dates[-1]:
            return bars, NON_MONOTONIC_DATE
        if date_value > target_date:
            return bars, OUT_OF_SCOPE_AFTER_TARGET_DATE
        close = float(bar["close"])
        if previous_close is not None:
            try:
                reference = _continuity_reference(references, identity[0] if identity else "",
                                                  identity[1] if identity else -1, dates[-1],
                                                  previous_close, date_value, close, audit, previous_bar, bar)
            except ActionReferenceError:
                return bars, ACTION_REFERENCE_IDENTITY_MISMATCH
            ratio = close / reference
            if ratio > MAX_CROSS_DAY_CLOSE_RATIO or ratio < 1.0 / MAX_CROSS_DAY_CLOSE_RATIO:
                return bars, CROSS_DAY_CLOSE_RATIO
        dates.append(date_value)
        previous_close = close
        previous_bar = bar
    return bars, None


def _new_progress(target_int: int, targets: list[DailyTarget], *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "field_rule_id": FIELD_RULE_ID,
        "field_rule_version": FIELD_RULE_VERSION,
        "target_date": str(target_int),
        "target_count": len(targets),
        "target_fingerprint": _target_scope_fingerprint(targets),
        "dry_run": bool(dry_run),
        "completed_symbols": [],
        "symbol_progress": {},
        "failed_hosts": [],
        "host_events": [],
        "last_event": None,
    }


def _load_progress(path: Path, target_int: int, targets: list[DailyTarget], *, dry_run: bool) -> dict[str, Any]:
    expected = _new_progress(target_int, targets, dry_run=dry_run)
    if not path.exists():
        return expected
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"A_SYNC_PROGRESS_UNREADABLE:{path}") from error
    if not isinstance(loaded, dict):
        raise RuntimeError(f"A_SYNC_PROGRESS_INVALID:{path}")
    if str(loaded.get("schema_version")) != PROGRESS_SCHEMA_VERSION:
        raise RuntimeError(f"A_SYNC_PROGRESS_SCHEMA_MISMATCH:{path}")
    if str(loaded.get("target_date")) != str(target_int):
        raise RuntimeError(f"A_SYNC_PROGRESS_DATE_MISMATCH:{path}")
    if str(loaded.get("target_fingerprint")) != expected["target_fingerprint"]:
        raise RuntimeError(f"A_SYNC_PROGRESS_SCOPE_MISMATCH:{path}")
    if bool(loaded.get("dry_run", False)) != bool(dry_run):
        raise RuntimeError(f"A_SYNC_PROGRESS_MODE_MISMATCH:{path}")
    completed = loaded.get("completed_symbols", [])
    loaded["completed_symbols"] = sorted({str(value) for value in completed if str(value).strip()})
    loaded.setdefault("symbol_progress", {})
    loaded.setdefault("failed_hosts", [])
    loaded.setdefault("host_events", [])
    loaded.setdefault("last_event", None)
    return loaded


def _resume_target_order(
    targets: list[DailyTarget],
    progress: Mapping[str, Any],
    target_int: int | None = None,
) -> list[DailyTarget]:
    """Prioritize exact-target local files while preserving all other order.

    The last-date read is only a scheduling hint.  Every target still enters
    the unchanged local history, field, date, continuity, and source-identity
    gates below; a malformed or drifted exact-target file is rejected there.
    ``progress`` remains part of this seam for receipt compatibility, but
    durable pending/retry labels must not starve an already-current file.
    """
    if target_int is None:
        try:
            target_int = int(progress["target_date"])
        except (KeyError, TypeError, ValueError):
            return list(targets)

    current: list[DailyTarget] = []
    remainder: list[DailyTarget] = []
    for target in targets:
        try:
            is_current = read_last_date(Path(target.path)) == target_int
        except (OSError, ValueError, struct.error):
            is_current = False
        (current if is_current else remainder).append(target)
    return current + remainder


def _persist_progress(path: Path, progress: Mapping[str, Any]) -> None:
    payload = (json.dumps(dict(progress), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)


def _host_label(host: str, port: int) -> str:
    return f"{host}:{int(port)}"


def _connect_session(api: Any, host: str, port: int, timeout: float) -> None:
    connect = getattr(api, "connect", None)
    if not callable(connect):
        raise RuntimeError("TDX provider has no connect method")
    try:
        connected = connect(host, int(port), time_out=float(timeout))
    except TypeError:
        connected = connect(host, int(port), timeout=float(timeout))
    if connected is False:
        raise RuntimeError("connect returned false")


def _disconnect_session(api: Any) -> None:
    disconnect = getattr(api, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass


def _is_tdx_function_call_error(error: BaseException) -> bool:
    """Recognize the SDK wrapper without weakening import-time test support."""

    if TdxFunctionCallError is not None and isinstance(error, TdxFunctionCallError):
        return True
    error_type = type(error)
    return (
        error_type.__name__ == "TdxFunctionCallError"
        and error_type.__module__.startswith("pytdx.")
    )


def _exception_chain(error: BaseException) -> list[dict[str, str]]:
    """Capture the SDK wrapper and its original parser exception for receipts."""

    chain: list[dict[str, str]] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        current_type = type(current)
        chain.append(
            {
                "type": f"{current_type.__module__}.{current_type.__qualname__}",
                "message": str(current),
                "repr": repr(current),
            }
        )
        original = getattr(current, "original_exception", None)
        if isinstance(original, BaseException):
            current = original
            continue
        cause = current.__cause__
        if isinstance(cause, BaseException):
            current = cause
            continue
        context = current.__context__
        current = context if isinstance(context, BaseException) else None
    return chain


def _protocol_response_details(error: BaseException) -> dict[str, Any] | None:
    """Return typed details only for an SDK-wrapped parser/framing failure."""

    if not _is_tdx_function_call_error(error):
        return None
    original = getattr(error, "original_exception", None)
    original_type = type(original) if isinstance(original, BaseException) else None
    original_name = (
        (original_type.__module__, original_type.__name__)
        if original_type is not None
        else None
    )
    if not (
        isinstance(original, _PROTOCOL_PARSE_EXCEPTION_TYPES)
        or original_name in _PROTOCOL_PARSE_EXCEPTION_NAMES
    ):
        return None
    return {
        "error": repr(error),
        "exception_type": type(error).__name__,
        "original_exception_type": original_type.__name__ if original_type else None,
        "original_exception_module": original_type.__module__ if original_type else None,
        "original_exception": repr(original),
        "exception_chain": _exception_chain(error),
    }


def _fetch_valid_target_bars(
    api: Any,
    target: DailyTarget,
    target_date: int,
    previous_close: float | None,
    count: int,
    after_date: int | None = None,
    *,
    capture_response: Callable[[Any], None] | None = None,
    field_violations: list[dict[str, Any]] | None = None,
    run_id: str = "",
    recorded_at: str = "",
    action_references: Mapping[str, Any] | None = None,
    previous_date: int | None = None,
    previous_bar: Mapping[str, Any] | None = None,
    reference_audit: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch one symbol and validate the provider response in wire order.

    Sorting here would turn a provider ordering defect into apparently valid
    evidence.  The response is therefore checked exactly as returned.  Once
    the exact target date is present, every bar after ``after_date`` through
    the target is handed to the append path so an incremental gap is not
    silently dropped.
    """

    bars = api.get_security_bars(9, target.market, target.code, 0, max(1, int(count)))
    if capture_response is not None:
        capture_response(bars)
    if not bars:
        return [], EMPTY_RESPONSE
    normalized: list[dict[str, Any]] = []
    for response_index, raw in enumerate(bars):
        ok, reason = valid_hq_bar(raw)
        if not ok:
            return [], f"{INVALID_BAR}:{reason}"
        normalized_bar = dict(raw)
        if "vol" not in normalized_bar and "volume" in normalized_bar:
            normalized_bar["vol"] = normalized_bar["volume"]
        field_violation = _provider_field_signature_violation(
            normalized_bar,
            symbol=str(target.code),
            market=int(target.market),
            row_index=response_index,
            run_id=run_id,
            recorded_at=recorded_at,
        )
        if field_violation is not None:
            if field_violations is not None:
                field_violations.append(field_violation)
            return [], KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE
        normalized.append(normalized_bar)
    dates = [day_int(bar) for bar in normalized]
    if len(set(dates)) != len(dates):
        return [], DUPLICATE_DATE
    if any(right < left for left, right in zip(dates, dates[1:])):
        return [], NON_MONOTONIC_DATE
    if any(date_value > target_date for date_value in dates):
        return [], OUT_OF_SCOPE_AFTER_TARGET_DATE
    exact = [bar for bar in normalized if day_int(bar) == target_date]
    if not exact:
        return [], TARGET_DATE_MISSING
    if after_date is not None and int(after_date) >= target_date:
        eligible = exact
    else:
        cutoff = int(after_date) if after_date is not None else 0
        eligible = [
            bar
            for bar in normalized
            if cutoff < day_int(bar) <= target_date
        ]
    prior = float(previous_close) if previous_close and previous_close > 0 else None
    prior_date = previous_date
    prior_bar = previous_bar
    references = action_references if action_references is not None else _ACTION_REFERENCE_CONTEXT
    audit = reference_audit if reference_audit is not None else _ACTION_REFERENCE_AUDIT
    for bar in eligible:
        close = float(bar["close"])
        date_value = day_int(bar)
        if prior is not None:
            try:
                reference = _continuity_reference(references, str(target.code), int(target.market),
                                                  prior_date, prior, date_value, close, audit, prior_bar, bar)
            except ActionReferenceError:
                return [], ACTION_REFERENCE_IDENTITY_MISMATCH
            ratio = close / reference
            if ratio > MAX_CROSS_DAY_CLOSE_RATIO or ratio < 1.0 / MAX_CROSS_DAY_CLOSE_RATIO:
                return [], CROSS_DAY_CLOSE_RATIO
        prior = close
        prior_date = date_value
        prior_bar = bar
    # The caller still applies its own last-date filter before append.  This
    # return preserves every validated missing day while excluding future bars.
    return eligible, "OK"


def _reason_code(failure_type: str) -> str:
    return str(failure_type).split(":", 1)[0].upper()


def _compat_failure_type(failure_type: str) -> str:
    code = _reason_code(failure_type)
    if code == INVALID_BAR and ":" in str(failure_type):
        return "invalid_bar:" + str(failure_type).split(":", 1)[1]
    return _COMPAT_FAILURE_TYPES.get(code, str(failure_type))


def _snapshot_json_value(value: Any) -> Any:
    """Keep provider response objects JSON-replayable without changing them."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _snapshot_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_json_value(item) for item in value]
    return repr(value)


def _write_raw_response_snapshot(
    *,
    target_date: int,
    target: DailyTarget,
    request: Mapping[str, Any],
    host: str,
    host_ordinal: int,
    attempt_ordinal: int,
    response_rows: Any = None,
    response_error: str | None = None,
    run_id: str | None = None,
    rule_id: str = RULE_ID,
    rule_version: str = RULE_VERSION,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Persist one immutable provider-response object under the sync run root."""
    snapshot = {
        "schema_version": "v3_5.a_share.tdx_raw_response_snapshot.v1",
        "target_date": str(target_date),
        "symbol": str(target.code),
        "request": dict(request),
        "host": host,
        "host_ordinal": int(host_ordinal),
        "attempt_ordinal": int(attempt_ordinal),
        "run_id": run_id,
        "rule_id": rule_id,
        "rule_version": rule_version,
        "observed_at": observed_at or _observed_at(),
        "response_rows": _snapshot_json_value(response_rows),
        "response_error": response_error,
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    symbol_path = str(target.code).replace("/", "_").replace("\\", "_")
    root = Path(RUN_DIR) / "raw_responses" / str(target_date) / symbol_path
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        try:
            before = os.lstat(path)
        except OSError as error:
            raise RuntimeError(f"raw response snapshot identity unavailable: {path}") from error
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise RuntimeError(f"raw response snapshot identity is unsafe: {path}")
        read_flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            read_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            read_flags |= os.O_NOFOLLOW
        read_fd: int | None = None
        try:
            try:
                read_fd = os.open(str(path), read_flags)
            except OSError as error:
                raise RuntimeError(f"raw response snapshot cannot be opened safely: {path}") from error
            opened = os.fstat(read_fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise RuntimeError(f"raw response snapshot identity changed: {path}")
            with os.fdopen(read_fd, "rb") as stream:
                read_fd = None
                existing = stream.read()
        finally:
            if read_fd is not None:
                try:
                    os.close(read_fd)
                except OSError:
                    pass
        if existing != encoded:
            raise RuntimeError(f"raw response snapshot content conflict: {path}")
    else:
        open_fd: int | None = fd
        try:
            with os.fdopen(fd, "wb") as stream:
                open_fd = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            if open_fd is not None:
                try:
                    os.close(open_fd)
                except OSError:
                    pass
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
    return {
        "capture_id": digest,
        "path": str(path),
        "sha256": digest,
        "host": host,
        "host_ordinal": int(host_ordinal),
        "attempt_ordinal": int(attempt_ordinal),
    }


def run_sync(
    targets: Iterable[DailyTarget],
    *,
    target_date: str,
    api_factory: Any,
    host_candidates: Iterable[tuple[str, int]],
    count: int = 20,
    timeout: float = 1.5,
    dry_run: bool = False,
    request_deadline_seconds: float = DEFAULT_REQUEST_DEADLINE_SECONDS,
    symbol_budget_seconds: float = DEFAULT_SYMBOL_BUDGET_SECONDS,
    run_budget_seconds: float = DEFAULT_RUN_BUDGET_SECONDS,
    progress_path: Path | str | None = None,
    trusted_cas_inputs: Path | str | None = None,
    action_reference_manifest: Path | str | None = None,
    action_reference_sha256: str | None = None,
) -> dict[str, Any]:
    """Synchronize A daily files with bounded host failover and resume.

    A malformed response invalidates only the symbol currently being fetched.
    A request timeout interrupts the synchronous SDK call in place, so no
    executor thread is left behind.  Accepted symbols are persisted after the
    exact-date append and are skipped on a later run with the same target
    scope.  Connect/request failures quarantine the endpoint for this run;
    Empty responses rotate through the configured hosts within the existing
    symbol/run budgets; a persistent empty result remains symbol-specific
    quarantine evidence. Other content failures remain terminal.
    A reviewed CAS input is indexed once and can only accept an exact-date
    local file after the same history, field, path, record-count, and SHA
    gates pass; uncovered or changed files continue through the owner route.
    """

    # Reset before any admission failure: a later run cannot inherit prior authorization.
    global _ACTION_REFERENCE_CONTEXT, _ACTION_REFERENCE_AUDIT
    _ACTION_REFERENCE_CONTEXT = None
    _ACTION_REFERENCE_AUDIT = []
    manifest_path = action_reference_manifest or os.environ.get(ACTION_REFERENCE_MANIFEST_ENV)
    manifest_sha = action_reference_sha256 or os.environ.get(ACTION_REFERENCE_SHA256_ENV)
    references = _load_action_reference_manifest(manifest_path, manifest_sha)
    _ACTION_REFERENCE_CONTEXT = references
    target_text = str(target_date).replace("-", "").replace("/", "")
    if len(target_text) != 8 or not target_text.isdigit():
        raise ValueError(f"invalid target date: {target_date!r}")
    try:
        datetime.strptime(target_text, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"invalid target date: {target_date!r}") from error
    target_int = int(target_text)
    target_list = list(targets)
    _validate_target_scope(target_list)
    hosts = [(str(host), int(port)) for host, port in host_candidates]
    if not hosts:
        raise ValueError("TDX host candidates are empty")
    request_deadline = _positive_budget(request_deadline_seconds, "request_deadline_seconds")
    symbol_budget = _positive_budget(symbol_budget_seconds, "symbol_budget_seconds")
    run_budget = _positive_budget(run_budget_seconds, "run_budget_seconds")
    target_fingerprint = _target_scope_fingerprint(target_list)
    if progress_path is None:
        progress_file = Path(RUN_DIR) / "progress" / f"{target_int}-{target_fingerprint}.json"
    else:
        progress_file = Path(progress_path)
    trusted_cas_path = trusted_cas_inputs
    if trusted_cas_path in (None, ""):
        trusted_cas_path = os.environ.get(TRUSTED_CAS_INPUTS_ENV)
    trusted_cas_index = _trusted_cas_load_inputs(
        trusted_cas_path,
        target_int,
        expected_target_fingerprint=target_fingerprint,
    )
    progress = _load_progress(progress_file, target_int, target_list, dry_run=dry_run)
    run_id = f"{target_int}-{target_fingerprint[:16]}-{time.time_ns()}"
    prior_completed_symbols = {
        str(value)
        for value in progress.get("completed_symbols", [])
        if str(value).strip()
    }
    processed_symbols: set[str] = set()
    progress["last_run_id"] = run_id
    progress["rule_id"] = RULE_ID
    progress["rule_version"] = RULE_VERSION
    progress["field_rule_id"] = FIELD_RULE_ID
    progress["field_rule_version"] = FIELD_RULE_VERSION
    progress["last_run_started_at"] = _observed_at()
    run_history = list(progress.get("run_history", [])) if isinstance(progress.get("run_history"), list) else []
    run_history.append(
        {
            "run_id": run_id,
            "target_date": str(target_int),
            "rule_id": RULE_ID,
            "rule_version": RULE_VERSION,
            "field_rule_id": FIELD_RULE_ID,
            "field_rule_version": FIELD_RULE_VERSION,
        }
    )
    progress["run_history"] = run_history[-32:]
    target_list = _resume_target_order(target_list, progress, target_int)
    # Endpoint quarantine is intentionally scoped to this invocation.  The
    # durable progress file retains accepted symbols, host events, and raw
    # snapshots as evidence, but a transient outage must not make a later
    # recovery skip every configured endpoint forever.
    progress["failed_hosts"] = []
    _persist_progress(progress_file, progress)
    started_at = time.monotonic()
    run_deadline = started_at + run_budget
    by_symbol: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    raw_response_snapshots: list[dict[str, Any]] = []
    api: Any | None = None
    host_position = -1
    host_info: tuple[str, int] | None = None
    last_host_attempted: tuple[str, int] | None = None
    failed_hosts: set[str] = set()
    run_timeout = False
    timeout_scope: str | None = None
    interrupted = False
    pending_rows: list[dict[str, Any]] = []

    def remaining_run() -> float:
        return run_deadline - time.monotonic()

    def persist_event(
        symbol: str | None,
        *,
        event: str,
        host: str | None = None,
        attempt_ordinal: int | None = None,
        failure_type: str | None = None,
    ) -> None:
        if symbol is not None:
            item = dict(progress.get("symbol_progress", {}).get(symbol, {}))
            item.update(
                {
                    "symbol": symbol,
                    "target_date": str(target_int),
                    "event": event,
                    "host": host,
                    "attempt_ordinal": attempt_ordinal,
                    "failure_type": failure_type,
                }
            )
            progress.setdefault("symbol_progress", {})[symbol] = item
        progress["failed_hosts"] = sorted(failed_hosts)
        events = list(progress.get("host_events", []))
        if host is not None:
            events.append(
                {
                    "symbol": symbol,
                    "event": event,
                    "host": host,
                    "attempt_ordinal": attempt_ordinal,
                    "failure_type": failure_type,
                    "at": time.monotonic(),
                }
            )
            # Keep the durable cursor bounded even when a live run has many
            # empty provider responses.
            progress["host_events"] = events[-2048:]
        progress["last_event"] = {
            "symbol": symbol,
            "event": event,
            "host": host,
            "attempt_ordinal": attempt_ordinal,
            "failure_type": failure_type,
        }
        _persist_progress(progress_file, progress)

    def mark_completed(symbol: str, row: Mapping[str, Any]) -> None:
        if dry_run:
            return
        completed = {str(value) for value in progress.get("completed_symbols", [])}
        completed.add(symbol)
        progress["completed_symbols"] = sorted(completed)
        progress.setdefault("symbol_progress", {})[symbol] = {
            "symbol": symbol,
            "target_date": str(target_int),
            "status": str(row.get("status") or "ACCEPTED"),
            "classification": "ACCEPTED",
            "target_date_ready": bool(row.get("target_date_ready")),
            "last_date_after": row.get("last_date_after"),
            "host": row.get("host"),
            "attempt_ordinal": row.get("attempt_ordinal"),
            "source_sha256_before": row.get("source_sha256_before"),
            "source_sha256_after": row.get("source_sha256_after"),
            "raw_response_snapshots": list(row.get("raw_response_snapshots") or []),
            "run_id": row.get("run_id") or run_id,
            "rule_id": row.get("rule_id") or RULE_ID,
            "rule_version": row.get("rule_version") or RULE_VERSION,
            "field_rule_id": row.get("field_rule_id") or FIELD_RULE_ID,
            "field_rule_version": row.get("field_rule_version") or FIELD_RULE_VERSION,
            "recorded_at": row.get("recorded_at") or _observed_at(),
        }
        for key in (
            "trusted_cas_rule_id",
            "trusted_cas_rule_version",
            "trusted_cas_cohort",
            "trusted_cas_receipt_ref",
            "trusted_cas_receipt_sha256",
            "trusted_cas_cohort_review_ref",
            "trusted_cas_cohort_review_sha256",
            "trusted_cas_candidate_manifest_ref",
            "trusted_cas_candidate_manifest_sha256",
            "candidate_after_sha256",
        ):
            if key in row:
                progress["symbol_progress"][symbol][key] = row[key]
        persist_event(symbol, event="COMPLETED", host=row.get("host"), attempt_ordinal=row.get("attempt_ordinal"))

    def append_pending(start_index: int, reason: str) -> None:
        for pending in target_list[start_index:]:
            symbol = str(pending.code)
            if symbol in by_symbol:
                continue
            source_sha = _file_sha256(Path(pending.path))
            recorded_at = _observed_at()
            row = {
                "symbol": symbol,
                "market": int(pending.market),
                "status": "CANNOT_CONFIRM",
                "fetch_status": "A_SYNC_TIMEOUT",
                "classification": "UNPROCESSED",
                "reason_code": "A_SYNC_TIMEOUT",
                "quarantine": False,
                "path": str(pending.path),
                "target_date_ready": False,
                "last_date_before": read_last_date(pending.path),
                "last_date_after": read_last_date(pending.path),
                "source_sha256_before": source_sha,
                "source_sha256_after": source_sha,
                "host": "not_attempted",
                "failure_type": reason,
                "raw_response_snapshots": [],
                "run_id": run_id,
                "rule_id": RULE_ID,
                "rule_version": RULE_VERSION,
                "field_rule_id": FIELD_RULE_ID,
                "field_rule_version": FIELD_RULE_VERSION,
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = row
            reconciliation_rows.append(dict(row))
            pending_rows.append(row)
            # Do not overwrite a prior accepted marker merely because this
            # invocation ran out of budget before reaching that target.
            if symbol not in prior_completed_symbols:
                progress.setdefault("symbol_progress", {})[symbol] = dict(row)
        progress["pending_symbols"] = sorted(row["symbol"] for row in pending_rows)

    def open_next_host(symbol: str, symbol_deadline: float) -> tuple[Any, tuple[str, int]]:
        nonlocal host_position, last_host_attempted
        last_error: Exception | None = None
        while host_position + 1 < len(hosts):
            host_position += 1
            candidate = hosts[host_position]
            candidate_label = _host_label(*candidate)
            if candidate_label in failed_hosts:
                continue
            last_host_attempted = candidate
            candidate_api = api_factory(candidate[0], candidate[1])
            try:
                remaining = min(symbol_deadline - time.monotonic(), remaining_run())
                if remaining <= 0:
                    raise SyncTimeoutError("SYMBOL", symbol_budget, symbol_budget)
                with _deadline_guard(remaining, scope="CONNECT"):
                    _connect_session(candidate_api, candidate[0], candidate[1], timeout)
                persist_event(symbol, event="HOST_CONNECTED", host=candidate_label)
                return candidate_api, candidate
            except Exception as error:
                last_error = error
                deadline_exhausted = (
                    isinstance(error, SyncTimeoutError)
                    and (
                        error.unsupported_context
                        or remaining_run() <= 0
                        or symbol_deadline - time.monotonic() <= 0
                    )
                )
                if (
                    isinstance(error, SyncTimeoutError)
                    and not deadline_exhausted
                ) or not isinstance(error, (ValueError, TypeError, SyncTimeoutError)):
                    failed_hosts.add(candidate_label)
                persist_event(
                    symbol,
                    event="HOST_FAILED",
                    host=candidate_label,
                    failure_type=str(error),
                )
                _disconnect_session(candidate_api)
                if deadline_exhausted:
                    # A symbol/run deadline is terminal for this attempt.  Do
                    # not probe another endpoint after the budget is exhausted;
                    # the outer loop preserves the typed scope and evidence.
                    raise
        raise RuntimeError(f"no usable TDX host remains: {last_error!r}")

    for item_index, item in enumerate(target_list):
        if remaining_run() <= 0:
            run_timeout = True
            timeout_scope = "RUN"
            append_pending(item_index, "A_SYNC_TIMEOUT:RUN")
            break
        symbol = str(item.code)
        processed_symbols.add(symbol)
        recorded_at = _observed_at()
        source_sha_before = _file_sha256(Path(item.path))
        history, history_failure = _local_history_status(
            Path(item.path), target_int, action_references=references, symbol=symbol,
            market=int(item.market), reference_audit=_ACTION_REFERENCE_AUDIT,
        )
        field_violations = _local_field_signature_violations(
            Path(item.path),
            symbol=symbol,
            market=int(item.market),
            run_id=run_id,
            recorded_at=recorded_at,
        )
        existing = history[-2:]
        last_date = day_int(history[-1]) if history else None
        if last_date == target_int and len(history) >= 2:
            previous_close = float(history[-2]["close"])
            previous_date = day_int(history[-2])
            previous_bar = history[-2]
        else:
            previous_close = float(history[-1]["close"]) if history else None
            previous_date = day_int(history[-1]) if history else None
            previous_bar = history[-1] if history else None
        prior_entry = progress.get("symbol_progress", {}).get(symbol, {})
        if not isinstance(prior_entry, Mapping):
            prior_entry = {}
        prior_source_sha = prior_entry.get("source_sha256_after") or prior_entry.get("source_sha256_before")
        source_identity_changed = (
            symbol in prior_completed_symbols
            and (not isinstance(prior_source_sha, str) or prior_source_sha != source_sha_before)
        )
        prior_target_date = str(prior_entry.get("target_date") or target_int)
        prior_reason = str(prior_entry.get("reason_code") or "").split(":", 1)[0].upper()
        terminal_source_unchanged = (
            prior_target_date == str(target_int)
            and isinstance(prior_source_sha, str)
            and prior_source_sha == source_sha_before
            and prior_reason in _NONRETRYABLE_CONTENT_FAILURE_CODES
            and str(prior_entry.get("classification") or "").upper() == "QUARANTINED"
            and _field_rule_identity_current(prior_entry)
        )
        trusted_cas_entry = _trusted_cas_local_reuse(
            trusted_cas_index,
            item,
            target_int,
            source_sha_before,
            history,
            history_failure,
            field_violations,
        )
        if trusted_cas_entry is not None:
            # The reviewed-CAS path is a local, receipt-bound acceptance.  It
            # deliberately happens before source_identity_changed and before
            # any provider session is opened, while retaining the original
            # target/date/field gates above.
            trusted_accepted = {
                "symbol": symbol,
                "market": int(item.market),
                "status": "TRUSTED_CAS_CURRENT",
                "fetch_status": "TRUSTED_CAS_REUSE",
                "classification": "ACCEPTED",
                "reason_code": None,
                "quarantine": False,
                "path": str(item.path),
                "target_date_ready": True,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "host": "trusted_cas",
                "records_written": 0,
                "attempt_ordinal": 0,
                "raw_response_snapshots": [],
                "source_sha256_before": source_sha_before,
                "source_sha256_after": source_sha_before,
                "candidate_after_sha256": trusted_cas_entry.get("candidate_after_sha256"),
                "trusted_cas_rule_id": TRUSTED_CAS_RULE_ID,
                "trusted_cas_rule_version": TRUSTED_CAS_RULE_VERSION,
                "trusted_cas_cohort": trusted_cas_entry.get("cohort"),
                "trusted_cas_receipt_ref": trusted_cas_entry.get("receipt_path"),
                "trusted_cas_receipt_sha256": trusted_cas_entry.get("receipt_sha256"),
                "trusted_cas_cohort_review_ref": trusted_cas_entry.get("cohort_review_path"),
                "trusted_cas_cohort_review_sha256": trusted_cas_entry.get("cohort_review_sha256"),
                "trusted_cas_candidate_manifest_ref": trusted_cas_entry.get("candidate_manifest_path"),
                "trusted_cas_candidate_manifest_sha256": trusted_cas_entry.get("candidate_manifest_sha256"),
                "run_id": run_id,
                "rule_id": RULE_ID,
                "rule_version": RULE_VERSION,
                "field_rule_id": FIELD_RULE_ID,
                "field_rule_version": FIELD_RULE_VERSION,
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = trusted_accepted
            reconciliation_rows.append(dict(trusted_accepted))
            mark_completed(symbol, trusted_accepted)
            if remaining_run() <= 0:
                run_timeout = True
                timeout_scope = "RUN"
                append_pending(item_index + 1, "A_SYNC_TIMEOUT:RUN")
                break
            continue
        symbol_started_at = time.monotonic()
        symbol_deadline = symbol_started_at + symbol_budget
        symbol_snapshots: list[dict[str, Any]] = []
        prior_snapshots = prior_entry.get("raw_response_snapshots")
        prior_raw_response_snapshots = (
            list(prior_snapshots) if isinstance(prior_snapshots, list) else []
        )
        final_failure: dict[str, Any] | None = None
        terminal_content_failure = False
        if field_violations and prior_reason != KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                "reason_code": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                "field_violations": field_violations,
            }
            terminal_content_failure = True
        elif history_failure is not None:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": history_failure,
                # Keep the current scan's typed field evidence alongside the
                # primary history failure. A changed source may expose both
                # a duplicate date and the known malformed signature.
                "field_violations": field_violations,
            }
        elif terminal_source_unchanged:
            # Same-date content/history failures are terminal for this source
            # identity.  Retain their raw evidence without spending another
            # provider call; a new target date or changed bytes reopens them.
            final_failure = {
                "symbol": symbol,
                "host": prior_entry.get("host") or "retained_quarantine",
                "failure_type": str(prior_entry.get("failure_type") or prior_reason),
                "reason_code": prior_reason,
                "raw_response_snapshots": list(prior_entry.get("raw_response_snapshots") or []),
                "field_violations": list(prior_entry.get("field_violations") or []),
                "retained_quarantine": True,
            }
        elif field_violations:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                "reason_code": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                "field_violations": field_violations,
            }
            terminal_content_failure = True
        elif last_date is not None and last_date > target_int:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": SOURCE_DATE_AFTER_TARGET,
            }
        if (
            final_failure is None
            and last_date == target_int
            and history
            and valid_hq_bar(history[-1])[0]
            and not source_identity_changed
        ):
            accepted = {
                "symbol": symbol,
                "market": int(item.market),
                "status": "ALREADY_CURRENT",
                "fetch_status": "ALREADY_CURRENT",
                "classification": "ACCEPTED",
                "reason_code": None,
                "quarantine": False,
                "path": str(item.path),
                "target_date_ready": True,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "raw_response_snapshots": [],
                "source_sha256_before": source_sha_before,
                "source_sha256_after": source_sha_before,
                "run_id": run_id,
                "rule_id": RULE_ID,
                "rule_version": RULE_VERSION,
                "field_rule_id": FIELD_RULE_ID,
                "field_rule_version": FIELD_RULE_VERSION,
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = accepted
            reconciliation_rows.append(dict(accepted))
            mark_completed(symbol, accepted)
            if remaining_run() <= 0:
                run_timeout = True
                timeout_scope = "RUN"
                append_pending(item_index + 1, "A_SYNC_TIMEOUT:RUN")
                break
            continue
        # A failed symbol may have consumed the full host list.  Start the
        # next symbol from the first configured endpoint, while preserving the
        # run-wide failed endpoint quarantine and any healthy live session.
        if api is None:
            host_position = -1
            host_info = None
            last_host_attempted = None
        while True:
            if final_failure is not None:
                break
            remaining = min(symbol_deadline - time.monotonic(), remaining_run())
            if remaining <= 0:
                final_failure = {
                    "symbol": symbol,
                    "host": _host_label(*(last_host_attempted or host_info))
                    if (last_host_attempted or host_info)
                    else "not_attempted",
                    "failure_type": "A_SYNC_TIMEOUT:RUN" if remaining_run() <= 0 else "A_SYNC_TIMEOUT:SYMBOL",
                }
                if str(final_failure["failure_type"]).endswith(":RUN"):
                    run_timeout = True
                    timeout_scope = "RUN"
                break
            if api is None:
                try:
                    api, host_info = open_next_host(symbol, symbol_deadline)
                except SyncTimeoutError as error:
                    effective_timeout_scope = (
                        "UNSUPPORTED_CONTEXT"
                        if error.unsupported_context
                        else "RUN"
                        if error.scope == "RUN" or remaining_run() <= 0
                        else "SYMBOL"
                        if error.scope == "SYMBOL" or symbol_deadline - time.monotonic() <= 0
                        else error.scope
                    )
                    timeout_failure_type = str(error)
                    if effective_timeout_scope == "UNSUPPORTED_CONTEXT":
                        timeout_failure_type = "A_SYNC_TIMEOUT:UNSUPPORTED_CONTEXT"
                    elif effective_timeout_scope != error.scope:
                        timeout_failure_type = timeout_failure_type.replace(
                            f"A_SYNC_TIMEOUT:{error.scope}",
                            f"A_SYNC_TIMEOUT:{effective_timeout_scope}",
                            1,
                        )
                    final_failure = {
                        "symbol": symbol,
                        "host": _host_label(*(last_host_attempted or host_info))
                        if (last_host_attempted or host_info)
                        else "unavailable",
                        "failure_type": timeout_failure_type,
                        "timeout_scope": effective_timeout_scope,
                        "deadline_seconds": error.deadline_seconds,
                        "elapsed_seconds": error.elapsed_seconds,
                        "unsupported_context": bool(error.unsupported_context),
                    }
                    if effective_timeout_scope in {"RUN", "UNSUPPORTED_CONTEXT"}:
                        run_timeout = True
                        timeout_scope = effective_timeout_scope
                    elif effective_timeout_scope == "SYMBOL":
                        timeout_scope = "SYMBOL"
                    break
                except Exception as error:
                    final_failure = {
                        "symbol": symbol,
                        "host": _host_label(*(last_host_attempted or host_info))
                        if (last_host_attempted or host_info)
                        else "unavailable",
                        "failure_type": "host_unavailable",
                        "error": repr(error),
                    }
                    break
            assert host_info is not None
            attempt_ordinal = len(symbol_snapshots) + 1
            attempt_snapshots: list[dict[str, Any]] = []
            attempt_field_violations: list[dict[str, Any]] = []
            host_label = _host_label(*host_info)

            def capture_response(rows: Any) -> None:
                attempt_snapshots.append(
                    _write_raw_response_snapshot(
                        target_date=target_int,
                        target=item,
                        request={
                            "code": symbol,
                            "count": max(1, int(count)),
                            "kline": 9,
                            "market": int(item.market),
                            "start": 0,
                            "target_date": str(target_int),
                        },
                        host=_host_label(*host_info),
                        host_ordinal=host_position + 1,
                        attempt_ordinal=attempt_ordinal,
                        response_rows=rows,
                        run_id=run_id,
                        rule_id=RULE_ID,
                        rule_version=RULE_VERSION,
                        observed_at=recorded_at,
                    )
                )

            try:
                remaining = min(symbol_deadline - time.monotonic(), remaining_run())
                if remaining <= 0:
                    raise SyncTimeoutError("RUN" if remaining_run() <= 0 else "SYMBOL", symbol_budget, symbol_budget)
                with _deadline_guard(min(request_deadline, remaining), scope="REQUEST"):
                    bars, failure_type = _fetch_valid_target_bars(
                        api,
                        item,
                        target_int,
                        previous_close,
                        count,
                        after_date=last_date,
                        capture_response=capture_response,
                        field_violations=attempt_field_violations,
                        run_id=run_id,
                        recorded_at=recorded_at,
                        action_references=references,
                        previous_date=previous_date,
                        previous_bar=previous_bar,
                        reference_audit=_ACTION_REFERENCE_AUDIT,
                    )
                symbol_snapshots.extend(attempt_snapshots)
                if attempt_field_violations and attempt_snapshots:
                    for violation in attempt_field_violations:
                        violation["source_snapshot"] = dict(attempt_snapshots[-1])
                        violation["source_file_sha256"] = attempt_snapshots[-1]["sha256"]
                        violation["source_ref"] = (
                            f"{attempt_snapshots[-1]['path']}#response_index={violation['row_index']}"
                        )
                if failure_type in {"OK", "ok"}:
                    if last_date == target_int:
                        if not history or not _bars_equivalent(history[-1], bars[-1]):
                            final_failure = {
                                "symbol": symbol,
                                "host": host_label,
                                "failure_type": SOURCE_IDENTITY_CHANGED,
                            }
                            terminal_content_failure = True
                            persist_event(
                                symbol,
                                event="CONTENT_FAILURE",
                                host=host_label,
                                attempt_ordinal=attempt_ordinal,
                                failure_type=SOURCE_IDENTITY_CHANGED,
                            )
                            break
                        bars_to_write: list[dict[str, Any]] = []
                        accepted_status = "REVALIDATED_CURRENT"
                        accepted_fetch_status = "REVALIDATED"
                    else:
                        bars_to_write = [bar for bar in bars if day_int(bar) > (last_date or 0)]
                        accepted_status = "UPDATED"
                        accepted_fetch_status = "OK"
                    append_field_violations = [
                        violation
                        for row_index, bar in enumerate(bars_to_write)
                        if (
                            violation := _provider_field_signature_violation(
                                bar,
                                symbol=symbol,
                                market=int(item.market),
                                row_index=row_index,
                                run_id=run_id,
                                recorded_at=recorded_at,
                            )
                        ) is not None
                    ]
                    if append_field_violations:
                        for violation in append_field_violations:
                            if attempt_snapshots:
                                violation["source_snapshot"] = dict(attempt_snapshots[-1])
                                violation["source_file_sha256"] = attempt_snapshots[-1]["sha256"]
                                violation["source_ref"] = (
                                    f"{attempt_snapshots[-1]['path']}#response_index={violation['row_index']}"
                                )
                        final_failure = {
                            "symbol": symbol,
                            "host": host_label,
                            "failure_type": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                            "reason_code": KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                            "field_violations": append_field_violations,
                        }
                        terminal_content_failure = True
                        persist_event(
                            symbol,
                            event="CONTENT_FAILURE",
                            host=host_label,
                            attempt_ordinal=attempt_ordinal,
                            failure_type=KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE,
                        )
                        break
                    if not dry_run:
                        append_bars(item.path, bars_to_write)
                    last_after = last_date if not bars_to_write else day_int(bars_to_write[-1])
                    source_sha_after = _file_sha256(Path(item.path))
                    accepted = {
                        "symbol": symbol,
                        "market": int(item.market),
                        "status": accepted_status,
                        "fetch_status": accepted_fetch_status,
                        "classification": "ACCEPTED",
                        "reason_code": None,
                        "quarantine": False,
                        "path": str(item.path),
                        "target_date_ready": last_after == target_int,
                        "last_date_before": last_date,
                        "last_date_after": last_after,
                        "host": _host_label(*host_info),
                        "records_written": len(bars_to_write),
                        "attempt_ordinal": attempt_ordinal,
                        "raw_response_snapshots": prior_raw_response_snapshots + list(symbol_snapshots),
                        "source_sha256_before": source_sha_before,
                        "source_sha256_after": source_sha_after,
                        "run_id": run_id,
                        "rule_id": RULE_ID,
                        "rule_version": RULE_VERSION,
                        "field_rule_id": FIELD_RULE_ID,
                        "field_rule_version": FIELD_RULE_VERSION,
                        "recorded_at": recorded_at,
                    }
                    by_symbol[symbol] = accepted
                    reconciliation_rows.append(dict(accepted))
                    mark_completed(symbol, accepted)
                    final_failure = None
                    if remaining_run() <= 0:
                        run_timeout = True
                        timeout_scope = "RUN"
                    break
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": failure_type,
                    "reason_code": _reason_code(failure_type),
                    "field_violations": list(attempt_field_violations),
                }
                terminal_content_failure = (
                    _reason_code(failure_type) in _NONRETRYABLE_CONTENT_FAILURE_CODES
                )
                persist_event(
                    symbol,
                    event="CONTENT_FAILURE",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=str(failure_type),
                )
            except SyncTimeoutError as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _write_raw_response_snapshot(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": max(1, int(count)),
                                "kline": 9,
                                "market": int(item.market),
                                "start": 0,
                                "target_date": str(target_int),
                            },
                            host=host_label,
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error=str(error),
                            run_id=run_id,
                            rule_id=RULE_ID,
                            rule_version=RULE_VERSION,
                            observed_at=recorded_at,
                        )
                    )
                # A request deadline is still symbol-scoped evidence while
                # the run remains inside its global budget.  Do not turn one
                # slow symbol into a run-wide endpoint quarantine: the next
                # symbol must be able to use the same provider lane.
                effective_timeout_scope = (
                    "UNSUPPORTED_CONTEXT"
                    if error.unsupported_context
                    else "RUN"
                    if error.scope == "RUN" or remaining_run() <= 0
                    else "SYMBOL"
                )
                timeout_failure_type = str(error)
                if effective_timeout_scope == "UNSUPPORTED_CONTEXT":
                    timeout_failure_type = "A_SYNC_TIMEOUT:UNSUPPORTED_CONTEXT"
                elif effective_timeout_scope != error.scope:
                    timeout_failure_type = timeout_failure_type.replace(
                        f"A_SYNC_TIMEOUT:{error.scope}",
                        f"A_SYNC_TIMEOUT:{effective_timeout_scope}",
                        1,
                    )
                if effective_timeout_scope == "RUN":
                    failed_hosts.add(host_label)
                persist_event(
                    symbol,
                    event="REQUEST_TIMEOUT",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=timeout_failure_type,
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": timeout_failure_type,
                    "timeout_scope": effective_timeout_scope,
                    "deadline_seconds": error.deadline_seconds,
                    "elapsed_seconds": error.elapsed_seconds,
                    "unsupported_context": bool(error.unsupported_context),
                }
                if effective_timeout_scope in {"RUN", "UNSUPPORTED_CONTEXT"}:
                    run_timeout = True
                    timeout_scope = effective_timeout_scope
                elif effective_timeout_scope == "SYMBOL":
                    timeout_scope = "SYMBOL"
            except KeyboardInterrupt as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _write_raw_response_snapshot(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": max(1, int(count)),
                                "kline": 9,
                                "market": int(item.market),
                                "start": 0,
                                "target_date": str(target_int),
                            },
                            host=host_label,
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error="A_SYNC_INTERRUPTED",
                            run_id=run_id,
                            rule_id=RULE_ID,
                            rule_version=RULE_VERSION,
                            observed_at=recorded_at,
                        )
                    )
                interrupted = True
                timeout_scope = "INTERRUPTED"
                persist_event(
                    symbol,
                    event="INTERRUPTED",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type="A_SYNC_INTERRUPTED",
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": "A_SYNC_INTERRUPTED",
                    "error": repr(error),
                }
            except Exception as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _write_raw_response_snapshot(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": max(1, int(count)),
                                "kline": 9,
                                "market": int(item.market),
                                "start": 0,
                                "target_date": str(target_int),
                            },
                            host=_host_label(*host_info),
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error=repr(error),
                            run_id=run_id,
                            rule_id=RULE_ID,
                            rule_version=RULE_VERSION,
                            observed_at=recorded_at,
                        )
                    )
                protocol_details = _protocol_response_details(error)
                failure_type = (
                    PROTOCOL_RESPONSE_MALFORMED
                    if protocol_details is not None
                    else "request_error"
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": failure_type,
                    **(
                        protocol_details
                        if protocol_details is not None
                        else {"error": repr(error)}
                    ),
                }
                failed_hosts.add(host_label)
                persist_event(
                    symbol,
                    event="REQUEST_FAILURE",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=failure_type,
                )
            # Every failed provider request, including EMPTY_RESPONSE, closes
            # the current session before the next attempt.  EMPTY_RESPONSE is
            # retryable for this symbol, so the next iteration advances to the
            # next host while terminal content failures remain symbol-final.
            _disconnect_session(api)
            api = None
            if run_timeout or interrupted or symbol_deadline - time.monotonic() <= 0:
                break
            if terminal_content_failure:
                break
            if host_position + 1 >= len(hosts):
                break
            final_failure = None
        if final_failure is not None:
            failure_type = str(final_failure.get("failure_type") or "REQUEST_ERROR")
            quarantined = {
                "symbol": symbol,
                "market": int(item.market),
                "status": "CANNOT_CONFIRM" if failure_type.startswith("A_SYNC_TIMEOUT") else "FAILED",
                "fetch_status": "REBUILD_REQUIRED",
                "classification": "QUARANTINED",
                "reason_code": _reason_code(failure_type),
                "quarantine": True,
                "path": str(item.path),
                "target_date_ready": False,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "source_sha256_before": source_sha_before,
                "source_sha256_after": _file_sha256(Path(item.path)),
                "raw_response_snapshots": prior_raw_response_snapshots + list(symbol_snapshots),
                "field_violations": list(final_failure.get("field_violations") or []),
                "run_id": run_id,
                "rule_id": RULE_ID,
                "rule_version": RULE_VERSION,
                "field_rule_id": FIELD_RULE_ID,
                "field_rule_version": FIELD_RULE_VERSION,
                "recorded_at": recorded_at,
                **final_failure,
            }
            # Keep the legacy failure list byte-for-byte compatible while the
            # reconciliation carries the typed reason used by new consumers.
            quarantined["failure_type"] = _compat_failure_type(failure_type)
            by_symbol[symbol] = quarantined
            reconciliation_rows.append(dict(quarantined))
            progress.setdefault("symbol_progress", {})[symbol] = {
                **quarantined,
                "failure_type": failure_type,
                "reason_code": _reason_code(failure_type),
                "field_rule_id": FIELD_RULE_ID,
                "field_rule_version": FIELD_RULE_VERSION,
            }
            failure_entry = dict(final_failure)
            failure_entry["failure_type"] = _compat_failure_type(failure_type)
            failures.append(failure_entry)
            if failure_type.startswith("A_SYNC_TIMEOUT"):
                run_timeout = run_timeout or failure_type.endswith(":RUN") or remaining_run() <= 0
                if final_failure.get("unsupported_context"):
                    # Preserve the explicit pre-provider context failure so a
                    # fail-closed authority receipt does not call it a real
                    # elapsed RUN timeout.
                    timeout_scope = timeout_scope or "UNSUPPORTED_CONTEXT"
                elif run_timeout:
                    timeout_scope = "RUN"
            # Reset the endpoint cursor after an exhausted symbol.  This is
            # essential after all hosts return EMPTY_RESPONSE: the next symbol
            # must begin at the first configured endpoint.
            _disconnect_session(api)
            api = None
            host_position = -1
            host_info = None
            last_host_attempted = None
        raw_response_snapshots.extend(symbol_snapshots)
        if run_timeout or interrupted:
            append_pending(item_index + 1, "A_SYNC_INTERRUPTED" if interrupted else "A_SYNC_TIMEOUT:RUN")
            break

    _disconnect_session(api)
    completed_count = sum(row.get("classification") == "ACCEPTED" for row in reconciliation_rows)
    status = "INTERRUPTED" if interrupted else "TIMEOUT" if run_timeout else "PASS" if not failures else "FAILED"
    accepted_count = sum(row.get("classification") == "ACCEPTED" for row in reconciliation_rows)
    quarantine_count = sum(row.get("classification") == "QUARANTINED" for row in reconciliation_rows)
    target_count = len(target_list)
    progress["failed_hosts"] = sorted(failed_hosts)
    current_accepted_symbols = {
        symbol
        for symbol, row in by_symbol.items()
        if row.get("classification") == "ACCEPTED"
    }
    if dry_run:
        progress["completed_symbols"] = []
    else:
        target_symbols = {str(item.code) for item in target_list}
        # A bounded run may stop before reaching a prior accepted target after
        # pending work is moved to the front.  Retain that durable marker until
        # the target is actually processed and fails; then replace it with the
        # current accepted union.  This prevents a partial receipt from
        # reclassifying untouched completed work as unprocessed.
        carried_completed = prior_completed_symbols - processed_symbols
        pending_symbols = {str(row["symbol"]) for row in pending_rows}
        progress["completed_symbols"] = sorted(
            ((carried_completed | current_accepted_symbols) - pending_symbols) & target_symbols
        )
    progress["pending_symbols"] = sorted(row["symbol"] for row in pending_rows)
    progress["last_event"] = {
        "symbol": None,
        "event": "INTERRUPTED" if interrupted else "TIMEOUT" if run_timeout else "COMPLETE",
        "timeout_scope": timeout_scope,
    }
    _persist_progress(progress_file, progress)
    reconciliation = {
        "target_count": target_count,
        "accepted_count": accepted_count,
        "quarantine_count": quarantine_count,
        "pending_count": len(pending_rows),
        "symbols": reconciliation_rows,
    }
    return {
        "task_name": TASK_NAME,
        "run_id": run_id,
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "field_rule_id": FIELD_RULE_ID,
        "field_rule_version": FIELD_RULE_VERSION,
        "status": status,
        "exit_code": 0 if status == "PASS" else 130 if status == "INTERRUPTED" else 124 if status == "TIMEOUT" else 2,
        "target_date": str(target_int),
        "target_fingerprint": target_fingerprint,
        "target_keys": _target_scope_keys(target_list),
        "target_count": target_count,
        "updated_count": sum(item.get("status") == "UPDATED" for item in by_symbol.values()),
        "accepted_count": accepted_count,
        "quarantine_count": quarantine_count,
        "completed_count": completed_count,
        "pending_count": len(pending_rows),
        "timeout": bool(run_timeout),
        "interrupted": bool(interrupted),
        "timeout_scope": timeout_scope,
        "progress_path": str(progress_file),
        "progress": progress,
        "budgets": {
            "request_deadline_seconds": request_deadline,
            "symbol_budget_seconds": symbol_budget,
            "run_budget_seconds": run_budget,
            "run_elapsed_seconds": max(0.0, time.monotonic() - started_at),
        },
        "accepted_target_date_file_count": accepted_count,
        "coverage_rate": (accepted_count / target_count) if target_count else None,
        "authority_status": "CANNOT_CONFIRM" if run_timeout else "PASS" if not failures else "REBUILD_REQUIRED" if accepted_count else "FAILED",
        "reconciliation": reconciliation,
        "symbol_reconciliation": reconciliation_rows,
        "raw_response_snapshots": raw_response_snapshots,
        "failures": failures,
        "by_symbol": by_symbol,
        "host": _host_label(*host_info) if host_info else None,
        "action_reference": {
            "configured": references is not None,
            "manifest_path": references["path"] if references else None,
            "manifest_sha256": references["sha256"] if references else None,
            "comparisons": _ACTION_REFERENCE_AUDIT,
        },
        "trusted_cas": {
            "configured": trusted_cas_path not in (None, ""),
            "loaded": trusted_cas_index is not None,
            "config_path": trusted_cas_index.get("config_path") if trusted_cas_index else None,
            "config_sha256": trusted_cas_index.get("config_sha256") if trusted_cas_index else None,
            "target_date": trusted_cas_index.get("target_date") if trusted_cas_index else None,
            "cohort_counts": trusted_cas_index.get("cohort_counts") if trusted_cas_index else None,
        },
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    keys: List[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})


def day_int(bar: Dict[str, Any]) -> int:
    return int(bar["year"]) * 10000 + int(bar["month"]) * 100 + int(bar["day"])


def read_last_date(path: Path) -> Optional[int]:
    if _local_path_failure(path) is not None or not path.exists():
        return None
    if path.stat().st_size < DAY_STRUCT.size:
        return None
    with path.open("rb") as f:
        f.seek(-DAY_STRUCT.size, os.SEEK_END)
        return int(DAY_STRUCT.unpack(f.read(DAY_STRUCT.size))[0])


def pack_hq_bar(bar: Dict[str, Any]) -> bytes:
    return DAY_STRUCT.pack(
        day_int(bar),
        int(round(float(bar["open"]) * 100)),
        int(round(float(bar["high"]) * 100)),
        int(round(float(bar["low"]) * 100)),
        int(round(float(bar["close"]) * 100)),
        float(bar["amount"]),
        int(round(float(bar["vol"]) * 100)),
        0,
    )


def valid_hq_bar(bar: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        if not isinstance(bar, Mapping):
            return False, "bar_not_mapping"
        required_date_fields = ("year", "month", "day")
        if any(
            not isinstance(bar.get(field), int) or isinstance(bar.get(field), bool)
            for field in required_date_fields
        ):
            return False, "date_not_integer"
        date_value = day_int(bar)
        values = {field: bar[field] for field in ("open", "high", "low", "close")}
        if any(not _is_finite_real(value) for value in values.values()):
            return False, "ohlc_not_finite_numeric"
        open_v = float(values["open"])
        high_v = float(values["high"])
        low_v = float(values["low"])
        close_v = float(values["close"])
    except Exception as exc:
        return False, f"parse_error:{exc!r}"
    if "amount" not in bar:
        return False, "missing_amount"
    volume_key = "vol" if "vol" in bar else "volume" if "volume" in bar else None
    if volume_key is None:
        return False, "missing_volume"
    if not _is_finite_real(bar["amount"]):
        return False, "amount_not_finite_numeric"
    if not _is_finite_real(bar[volume_key]):
        return False, "volume_not_finite_numeric"
    amount_v = float(bar["amount"])
    volume_v = float(bar[volume_key])
    if amount_v < 0:
        return False, "negative_amount"
    if volume_v < 0:
        return False, "negative_volume"
    if not (19900101 <= date_value <= 21000101):
        return False, f"bad_date:{date_value}"
    try:
        datetime(
            int(bar["year"]),
            int(bar["month"]),
            int(bar["day"]),
        )
    except (TypeError, ValueError, OverflowError):
        return False, f"bad_calendar_date:{date_value}"
    if min(open_v, high_v, low_v, close_v) <= 0:
        return False, "non_positive_ohlc"
    if high_v < low_v:
        return False, "high_lt_low"
    if close_v > high_v or close_v < low_v:
        return False, "close_outside_high_low"
    return True, "ok"


def read_hq_day_bars(path: Path, tail_records: Optional[int] = None) -> List[Dict[str, Any]]:
    if _local_path_failure(path) is not None or not path.exists():
        return []
    size = path.stat().st_size
    count = size // DAY_STRUCT.size
    start = max(0, count - tail_records) if tail_records else 0
    rows: List[Dict[str, Any]] = []
    with path.open("rb") as f:
        f.seek(start * DAY_STRUCT.size)
        data = f.read((count - start) * DAY_STRUCT.size)
    for offset in range(0, len(data), DAY_STRUCT.size):
        date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = DAY_STRUCT.unpack_from(data, offset)
        rows.append({
            "year": date_i // 10000, "month": date_i // 100 % 100, "day": date_i % 100,
            "open": open_i / 100.0, "high": high_i / 100.0, "low": low_i / 100.0,
            "close": close_i / 100.0, "amount": amount_f, "vol": vol_u / 100.0,
        })
    return rows


def build_rebuild_candidate(
    source_path: Path,
    replacements: List[Dict[str, Any]],
    candidate_path: Path,
    *,
    expected_source_sha256: Optional[str] = None,
    expected_replacement_sha256: Optional[Mapping[int, str]] = None,
    expected_replacement_dates: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Write a side-by-side corrected ``.day`` candidate.

    Existing records are carried as their original 32-byte bytes.  Repacking
    the whole file through :func:`read_hq_day_bars` loses reserved bytes and
    silently collapses duplicate dates, so only explicitly supplied dates are
    encoded with the existing ``pack_hq_bar`` codec.  Missing dates retain the
    historical append/insert behavior, while an existing date is replaced
    in-place in the date-sorted stream.
    """
    source_path = Path(source_path)
    candidate_path = Path(candidate_path)
    source_failure = _local_path_failure(source_path)
    if source_failure is not None:
        raise OSError(f"A_SYNC_SOURCE_PATH_REJECTED:{source_path}:{source_failure}")

    candidate_failure = _local_path_failure(candidate_path)
    if candidate_failure is not None:
        raise OSError(f"A_SYNC_CANDIDATE_PATH_REJECTED:{candidate_path}:{candidate_failure}")
    if source_path.absolute() == candidate_path.absolute():
        raise OSError(f"A_SYNC_SOURCE_CANDIDATE_PATH_COLLISION:{source_path}")
    if source_path.exists() and candidate_path.exists():
        try:
            if source_path.samefile(candidate_path):
                raise OSError(f"A_SYNC_SOURCE_CANDIDATE_PATH_COLLISION:{source_path}")
        except FileNotFoundError:
            pass

    source_bytes = b""
    if source_path.exists():
        if not source_path.is_file():
            raise OSError(f"A_SYNC_SOURCE_PATH_REJECTED:{source_path}:source_not_regular")
        try:
            source_bytes = source_path.read_bytes()
        except OSError as exc:
            raise OSError(f"A_SYNC_SOURCE_READ_FAILED:{source_path}:{exc!r}") from exc
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if expected_source_sha256 is not None and source_sha256.lower() != str(expected_source_sha256).lower():
        raise ValueError(
            f"A_SYNC_SOURCE_SHA_MISMATCH:expected={expected_source_sha256}:actual={source_sha256}"
        )
    if len(source_bytes) % DAY_STRUCT.size:
        raise ValueError(
            f"A_SYNC_SOURCE_FILE_SHAPE_REJECTED:truncated:size={len(source_bytes)}:record_size={DAY_STRUCT.size}"
        )

    source_records: List[Tuple[int, bytes]] = []
    previous_date: Optional[int] = None
    for row_index, offset in enumerate(range(0, len(source_bytes), DAY_STRUCT.size)):
        raw = source_bytes[offset : offset + DAY_STRUCT.size]
        date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = DAY_STRUCT.unpack(raw)
        bar = {
            "year": date_i // 10000,
            "month": date_i // 100 % 100,
            "day": date_i % 100,
            "open": open_i / 100.0,
            "high": high_i / 100.0,
            "low": low_i / 100.0,
            "close": close_i / 100.0,
            "amount": amount_f,
            "vol": vol_u / 100.0,
        }
        valid, reason = valid_hq_bar(bar)
        if not valid:
            raise ValueError(f"A_SYNC_SOURCE_RECORD_REJECTED:row={row_index}:date={date_i}:{reason}")
        if previous_date is not None:
            if date_i == previous_date:
                raise ValueError(f"A_SYNC_SOURCE_DUPLICATE_DATE:row={row_index}:date={date_i}")
            if date_i < previous_date:
                raise ValueError(
                    f"A_SYNC_SOURCE_NON_MONOTONIC_DATE:row={row_index}:date={date_i}:previous={previous_date}"
                )
        source_records.append((date_i, raw))
        previous_date = date_i

    replacement_records: Dict[int, bytes] = {}
    for row_index, replacement in enumerate(replacements):
        if not isinstance(replacement, Mapping):
            raise ValueError(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:bar_not_mapping")
        try:
            date_value = day_int(dict(replacement))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:bad_date:{exc!r}") from exc
        if date_value in replacement_records:
            raise ValueError(f"A_SYNC_REPLACEMENT_DUPLICATE_DATE:row={row_index}:date={date_value}")
        valid, reason = valid_hq_bar(replacement)
        if not valid:
            raise ValueError(f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:date={date_value}:{reason}")
        try:
            packed = pack_hq_bar(dict(replacement))
        except (KeyError, TypeError, ValueError, OverflowError, struct.error) as exc:
            raise ValueError(
                f"A_SYNC_REPLACEMENT_REJECTED:row={row_index}:date={date_value}:pack_error:{exc!r}"
            ) from exc
        if int(DAY_STRUCT.unpack_from(packed, 0)[0]) != date_value:
            raise ValueError(f"A_SYNC_REPLACEMENT_DATE_MISMATCH:row={row_index}:date={date_value}")
        replacement_records[date_value] = packed

    if expected_replacement_dates is not None:
        try:
            expected_dates = [int(date_value) for date_value in expected_replacement_dates]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"A_SYNC_EXPECTED_REPLACEMENT_DATES_INVALID:{exc!r}") from exc
        if len(expected_dates) != len(set(expected_dates)):
            raise ValueError("A_SYNC_EXPECTED_REPLACEMENT_DATES_DUPLICATE")
        if sorted(expected_dates) != sorted(replacement_records):
            raise ValueError(
                "A_SYNC_REPLACEMENT_DATES_MISMATCH:"
                f"expected={sorted(expected_dates)}:actual={sorted(replacement_records)}"
            )

    if expected_replacement_sha256 is not None:
        expected_sha_by_date = {int(date_value): str(digest).lower() for date_value, digest in expected_replacement_sha256.items()}
        if set(expected_sha_by_date) != set(replacement_records):
            raise ValueError(
                "A_SYNC_REPLACEMENT_SHA_SCOPE_MISMATCH:"
                f"expected={sorted(expected_sha_by_date)}:actual={sorted(replacement_records)}"
            )
        for date_value, packed in replacement_records.items():
            actual = hashlib.sha256(packed).hexdigest()
            if actual != expected_sha_by_date[date_value]:
                raise ValueError(
                    f"A_SYNC_REPLACEMENT_SHA_MISMATCH:date={date_value}:"
                    f"expected={expected_sha_by_date[date_value]}:actual={actual}"
                )

    replacement_dates = sorted(replacement_records)
    replacement_index = 0
    output_records: List[Tuple[int, bytes]] = []
    for date_value, raw in source_records:
        while replacement_index < len(replacement_dates) and replacement_dates[replacement_index] < date_value:
            inserted_date = replacement_dates[replacement_index]
            output_records.append((inserted_date, replacement_records[inserted_date]))
            replacement_index += 1
        if replacement_index < len(replacement_dates) and replacement_dates[replacement_index] == date_value:
            output_records.append((date_value, replacement_records[date_value]))
            replacement_index += 1
        else:
            output_records.append((date_value, raw))
    while replacement_index < len(replacement_dates):
        inserted_date = replacement_dates[replacement_index]
        output_records.append((inserted_date, replacement_records[inserted_date]))
        replacement_index += 1

    candidate_bytes = b"".join(raw for _date_value, raw in output_records)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_failure = _local_path_failure(candidate_path)
    if candidate_failure is not None:
        raise OSError(f"A_SYNC_CANDIDATE_PATH_REJECTED:{candidate_path}:{candidate_failure}")
    with candidate_path.open("wb") as handle:
        handle.write(candidate_bytes)

    source_chunks = [
        source_bytes[offset : offset + DAY_STRUCT.size]
        for offset in range(0, len(source_bytes), DAY_STRUCT.size)
    ]
    candidate_chunks = [
        candidate_bytes[offset : offset + DAY_STRUCT.size]
        for offset in range(0, len(candidate_bytes), DAY_STRUCT.size)
    ]
    changed_rows = (
        [row_index for row_index, (before, after) in enumerate(zip(source_chunks, candidate_chunks)) if before != after]
        if len(source_chunks) == len(candidate_chunks)
        else None
    )
    changed_byte_offsets = [
        offset
        for offset, (before, after) in enumerate(zip(source_bytes, candidate_bytes))
        if before != after
    ]
    return {
        "source_path": str(source_path),
        "candidate_path": str(candidate_path),
        "replaced_dates": replacement_dates,
        "source_sha256": source_sha256,
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "source_record_count": len(source_records),
        "candidate_record_count": len(output_records),
        "changed_rows": changed_rows,
        "changed_byte_offsets": changed_byte_offsets,
    }


def discover_targets(markets: Iterable[str], tdx_root: Path) -> List[Tuple[str, int, str, Path, Optional[int]]]:
    targets: List[Tuple[str, int, str, Path, Optional[int]]] = []
    for market_name in markets:
        for prefix, template_dir in DIR_BY_MARKET.get(market_name, []):
            directory = Path(str(template_dir).replace(str(TDX_ROOT), str(tdx_root)))
            if not directory.exists():
                continue
            for path in directory.glob(f"{prefix}*.day"):
                code = path.stem[len(prefix):]
                if len(code) != 6 or not code.isdigit():
                    continue
                if not code.startswith(EQUITY_CODE_PREFIXES_BY_MARKET[prefix]):
                    continue
                targets.append((prefix, MARKET_BY_PREFIX[prefix], code, path, read_last_date(path)))
    return targets


def append_bars(path: Path, bars: List[Dict[str, Any]]) -> None:
    failure = _local_path_failure(path)
    if failure is not None:
        raise OSError(f"A_SYNC_SOURCE_PATH_REJECTED:{path}:{failure}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after creating the parent chain.  This keeps a race that turns
    # an ancestor into a link from becoming an outside write.
    failure = _local_path_failure(path)
    if failure is not None:
        raise OSError(f"A_SYNC_SOURCE_PATH_REJECTED:{path}:{failure}")
    with path.open("ab") as f:
        for bar in bars:
            f.write(pack_hq_bar(bar))


def _runtime_host_candidates(preferred_host: Optional[str]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    if preferred_host:
        host, _, port_text = str(preferred_host).partition(":")
        candidates.append((host, int(port_text or 7709)))
    for item in hq_hosts:
        if len(item) >= 3:
            _name, host, port = item[:3]
            candidates.append((str(host), int(port)))
        elif len(item) == 2:
            host, port = item
            candidates.append((str(host), int(port)))
    return list(dict.fromkeys(candidates))


def _runtime_api_factory(host: str, _port: int) -> Any:
    if TdxHq_API is None:
        raise RuntimeError("pytdx is not installed")
    return TdxHq_API(auto_retry=False, raise_exception=True)


def run(args: argparse.Namespace) -> Dict[str, Any]:
    """Run the bounded sync and persist a truthful summary."""

    ensure_dir(RUN_DIR)
    markets = [x.strip().lower() for x in args.markets.split(",") if x.strip()]
    discovered = discover_targets(markets, args.tdx_root)
    if args.limit:
        discovered = discovered[: args.limit]
    targets = [
        DailyTarget(code=code, market=market, path=path)
        for _prefix, market, code, path, _last_date in discovered
    ]
    target_date = getattr(args, "target_date", None)
    if not target_date:
        raise ValueError("tdx daily sync requires an exact target_date")
    result = run_sync(
        targets,
        target_date=str(target_date),
        api_factory=_runtime_api_factory,
        host_candidates=_runtime_host_candidates(getattr(args, "host", None)),
        count=args.count,
        timeout=args.timeout,
        dry_run=bool(args.dry_run),
        request_deadline_seconds=getattr(args, "request_deadline_seconds", DEFAULT_REQUEST_DEADLINE_SECONDS),
        symbol_budget_seconds=getattr(args, "symbol_budget_seconds", DEFAULT_SYMBOL_BUDGET_SECONDS),
        run_budget_seconds=getattr(args, "run_budget_seconds", DEFAULT_RUN_BUDGET_SECONDS),
        progress_path=getattr(args, "progress_path", None),
        trusted_cas_inputs=getattr(args, "trusted_cas_inputs", None),
        action_reference_manifest=getattr(args, "action_reference_manifest", None),
        action_reference_sha256=getattr(args, "action_reference_sha256", None),
    )
    result.update(
        {
            "run_dir": str(RUN_DIR),
            "tdx_root": str(args.tdx_root),
            "markets": markets,
            "dry_run": bool(args.dry_run),
            "count": args.count,
            "note": "This sync updates SH/SZ/BJ vipdoc daily files only. HK extended market ExHQ is not written by this script.",
        }
    )
    write_csv(RUN_DIR / "file_results.csv", list(result["by_symbol"].values()))
    write_json(RUN_DIR / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync latest SH/SZ/BJ daily bars from pytdx into local TDX vipdoc .day files.")
    parser.add_argument("--tdx-root", type=Path, default=TDX_ROOT)
    parser.add_argument("--target-date", required=True, help="Exact YYYYMMDD target required for a truthful sync.")
    parser.add_argument("--markets", default="a,bj", help="Comma separated: a,bj. HK extended market is intentionally not supported here.")
    parser.add_argument("--count", type=int, default=20, help="Latest bars to request per symbol.")
    parser.add_argument("--host", default=None, help="Optional host:port override.")
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--request-deadline-seconds",
        type=float,
        default=DEFAULT_REQUEST_DEADLINE_SECONDS,
        help="Whole SDK request wall-clock deadline, including response-body reads.",
    )
    parser.add_argument(
        "--symbol-budget-seconds",
        type=float,
        default=DEFAULT_SYMBOL_BUDGET_SECONDS,
        help="Cumulative wall-clock budget for one symbol across endpoint attempts.",
    )
    parser.add_argument(
        "--run-budget-seconds",
        type=float,
        default=DEFAULT_RUN_BUDGET_SECONDS,
        help="Overall A-sync wall-clock budget below the outer executor timeout.",
    )
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=None,
        help="Optional date-bound atomic progress receipt path.",
    )
    parser.add_argument(
        "--trusted-cas-inputs",
        type=Path,
        default=None,
        help="Optional receipt-bound reviewed CAS references; exact target-date only.",
    )
    parser.add_argument("--action-reference-manifest", type=Path, default=None,
                        help="Explicit SHA-pinned two-event continuity reference manifest.")
    parser.add_argument("--action-reference-sha256", default=None,
                        help="Required SHA-256 for --action-reference-manifest; env equivalents supported.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    result = run(parse_args(argv))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
