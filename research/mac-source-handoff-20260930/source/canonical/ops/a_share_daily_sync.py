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

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))


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
    from ops._a_share_daily_sync_parts.scope_validation import __deadline_guard_body as _v4_impl
    return (yield from _v4_impl(globals(), seconds, scope=scope))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Atomically persist a small progress/receipt object in its parent."""
    from ops._a_share_daily_sync_parts.cli_runtime import __atomic_write_bytes_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _target_scope_fingerprint(targets: list[DailyTarget]) -> str:
    from ops._a_share_daily_sync_parts.scope_validation import __target_scope_fingerprint_body as _v4_impl
    return _v4_impl(globals(), targets)


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
    from ops._a_share_daily_sync_parts.scope_validation import __path_has_symlink_component_body as _v4_impl
    return _v4_impl(globals(), path)


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
    from ops._a_share_daily_sync_parts.cli_runtime import __file_sha256_body as _v4_impl
    return _v4_impl(globals(), path)


def _trusted_cas_sha256(value: Any, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"A_SYNC_TRUSTED_CAS_INVALID_SHA:{label}")
    return digest


def _trusted_cas_read_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    from ops._a_share_daily_sync_parts.trusted_cas import __trusted_cas_read_json_body as _v4_impl
    return _v4_impl(globals(), path, expected_sha256, label)


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
    from ops._a_share_daily_sync_parts.trusted_cas import __trusted_cas_map_body as _v4_impl
    return _v4_impl(globals(), payload, label=label, expected_count=expected_count)


def _trusted_cas_load_inputs(
    path_value: Path | str | None,
    target_int: int,
    expected_target_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Load reviewed CAS references once; ignore them for an uncovered date."""
    from ops._a_share_daily_sync_parts.trusted_cas import __trusted_cas_load_inputs_body as _v4_impl
    return _v4_impl(globals(), path_value, target_int, expected_target_fingerprint)


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
    from ops._a_share_daily_sync_parts.trusted_cas import __trusted_cas_local_reuse_body as _v4_impl
    return _v4_impl(globals(), index, target, target_int, current_sha, history, history_failure, field_violations)


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
    from ops._a_share_daily_sync_parts.field_rules import __field_signature_violation_body as _v4_impl
    return _v4_impl(globals(), symbol=symbol, market=market, date_value=date_value, row_index=row_index, raw=raw, source_ref=source_ref, source_file_sha256=source_file_sha256, native_path=native_path, run_id=run_id, recorded_at=recorded_at)


def _local_field_signature_violations(
    path: Path,
    *,
    symbol: str,
    market: int,
    run_id: str,
    recorded_at: str,
) -> list[dict[str, Any]]:
    """Scan every existing native record without decoding away raw bits."""
    from ops._a_share_daily_sync_parts.field_rules import __local_field_signature_violations_body as _v4_impl
    return _v4_impl(globals(), path, symbol=symbol, market=market, run_id=run_id, recorded_at=recorded_at)


def _provider_field_signature_violation(
    bar: Mapping[str, Any],
    *,
    symbol: str,
    market: int,
    row_index: int,
    run_id: str,
    recorded_at: str,
) -> dict[str, Any] | None:
    from ops._a_share_daily_sync_parts.field_rules import __provider_field_signature_violation_body as _v4_impl
    return _v4_impl(globals(), bar, symbol=symbol, market=market, row_index=row_index, run_id=run_id, recorded_at=recorded_at)


def _bars_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Compare a revalidated target bar without introducing a rewrite path."""
    from ops._a_share_daily_sync_parts.field_rules import __bars_equivalent_body as _v4_impl
    return _v4_impl(globals(), left, right)


def _local_history_status(path: Path, target_date: int) -> tuple[list[dict[str, Any]], str | None]:
    """Validate existing source bytes before an accepted-only handoff.

    The formula reader currently keeps the last duplicate key.  This gate
    audits the source in its original order first, so a malformed local file
    is quarantined instead of being silently repaired by a downstream reader.
    """
    from ops._a_share_daily_sync_parts.progress import __local_history_status_body as _v4_impl
    return _v4_impl(globals(), path, target_date)


def _new_progress(target_int: int, targets: list[DailyTarget], *, dry_run: bool) -> dict[str, Any]:
    from ops._a_share_daily_sync_parts.progress import __new_progress_body as _v4_impl
    return _v4_impl(globals(), target_int, targets, dry_run=dry_run)


def _load_progress(path: Path, target_int: int, targets: list[DailyTarget], *, dry_run: bool) -> dict[str, Any]:
    from ops._a_share_daily_sync_parts.progress import __load_progress_body as _v4_impl
    return _v4_impl(globals(), path, target_int, targets, dry_run=dry_run)


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
    from ops._a_share_daily_sync_parts.progress import __resume_target_order_body as _v4_impl
    return _v4_impl(globals(), targets, progress, target_int)


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
    from ops._a_share_daily_sync_parts.network_session import __exception_chain_body as _v4_impl
    return _v4_impl(globals(), error)


def _protocol_response_details(error: BaseException) -> dict[str, Any] | None:
    """Return typed details only for an SDK-wrapped parser/framing failure."""
    from ops._a_share_daily_sync_parts.network_session import __protocol_response_details_body as _v4_impl
    return _v4_impl(globals(), error)


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
) -> tuple[list[dict[str, Any]], str]:
    """Fetch one symbol and validate the provider response in wire order.

    Sorting here would turn a provider ordering defect into apparently valid
    evidence.  The response is therefore checked exactly as returned.  Once
    the exact target date is present, every bar after ``after_date`` through
    the target is handed to the append path so an incremental gap is not
    silently dropped.
    """
    from ops._a_share_daily_sync_parts.network_session import __fetch_valid_target_bars_body as _v4_impl
    return _v4_impl(globals(), api, target, target_date, previous_close, count, after_date, capture_response=capture_response, field_violations=field_violations, run_id=run_id, recorded_at=recorded_at)


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
    from ops._a_share_daily_sync_parts.response_capture import __write_raw_response_snapshot_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, target=target, request=request, host=host, host_ordinal=host_ordinal, attempt_ordinal=attempt_ordinal, response_rows=response_rows, response_error=response_error, run_id=run_id, rule_id=rule_id, rule_version=rule_version, observed_at=observed_at)


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
    from ops._a_share_daily_sync_parts.sync_workflow import _run_sync_body as _v4_impl
    return _v4_impl(globals(), targets, target_date=target_date, api_factory=api_factory, host_candidates=host_candidates, count=count, timeout=timeout, dry_run=dry_run, request_deadline_seconds=request_deadline_seconds, symbol_budget_seconds=symbol_budget_seconds, run_budget_seconds=run_budget_seconds, progress_path=progress_path, trusted_cas_inputs=trusted_cas_inputs)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    from ops._a_share_daily_sync_parts.day_file_format import _write_csv_body as _v4_impl
    return _v4_impl(globals(), path, rows)


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
    from ops._a_share_daily_sync_parts.day_file_format import _valid_hq_bar_body as _v4_impl
    return _v4_impl(globals(), bar)


def read_hq_day_bars(path: Path, tail_records: Optional[int] = None) -> List[Dict[str, Any]]:
    from ops._a_share_daily_sync_parts.day_file_format import _read_hq_day_bars_body as _v4_impl
    return _v4_impl(globals(), path, tail_records)


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
    from ops._a_share_daily_sync_parts.rebuild import _build_rebuild_candidate_body as _v4_impl
    return _v4_impl(globals(), source_path, replacements, candidate_path, expected_source_sha256=expected_source_sha256, expected_replacement_sha256=expected_replacement_sha256, expected_replacement_dates=expected_replacement_dates)


def discover_targets(markets: Iterable[str], tdx_root: Path) -> List[Tuple[str, int, str, Path, Optional[int]]]:
    from ops._a_share_daily_sync_parts.cli_runtime import _discover_targets_body as _v4_impl
    return _v4_impl(globals(), markets, tdx_root)


def append_bars(path: Path, bars: List[Dict[str, Any]]) -> None:
    from ops._a_share_daily_sync_parts.day_file_format import _append_bars_body as _v4_impl
    return _v4_impl(globals(), path, bars)


def _runtime_host_candidates(preferred_host: Optional[str]) -> list[tuple[str, int]]:
    from ops._a_share_daily_sync_parts.cli_runtime import __runtime_host_candidates_body as _v4_impl
    return _v4_impl(globals(), preferred_host)


def _runtime_api_factory(host: str, _port: int) -> Any:
    if TdxHq_API is None:
        raise RuntimeError("pytdx is not installed")
    return TdxHq_API(auto_retry=False, raise_exception=True)



def connect_hq(preferred_host: Optional[str], timeout: float) -> Tuple[Any, Dict[str, Any]]:
    """Compatibility probe for callers that still use the v1 connection API.

    The production sync path uses :func:`run_sync` and its bounded host route.
    This narrow adapter preserves the existing test/diagnostic entry point
    while constructing the same strict ``raise_exception=True`` provider.
    """
    from ops._a_share_daily_sync_parts.network_session import _connect_hq_body as _v4_impl
    return _v4_impl(globals(), preferred_host, timeout)

def run(args: argparse.Namespace) -> Dict[str, Any]:
    """Run the bounded sync and persist a truthful summary."""
    from ops._a_share_daily_sync_parts.cli_runtime import _run_body as _v4_impl
    return _v4_impl(globals(), args)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    from ops._a_share_daily_sync_parts.cli_runtime import _parse_args_body as _v4_impl
    return _v4_impl(globals(), argv)


def main(argv: Iterable[str] | None = None) -> int:
    result = run(parse_args(argv))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
