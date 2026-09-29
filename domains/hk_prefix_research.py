"""V4-owned, research-only historical HK prefix reconstruction.

This module consumes one checksum-bound historical daily-bar asset and the
already accepted R1 calendar/group binding.  It derives 60 market-session
prefixes ending on the session immediately before each frozen pseudo-event,
then delegates the observable state calculation to the accepted zero-fit
``prefix_repair.scan_prefix`` reference implementation.

The module deliberately keeps three identities separate:

* the source and calendar manifests are machine-verified inputs;
* ``derived_windows/series_*.csv`` is anonymous OHLCV review material; and
* ``identity/`` contains the event/control mapping and paired results.

No labels, event metadata, model fitting, network client, scheduler, or live
panel pointer is used here.  The source rows are read through the existing
``hk_0_2`` owner reader; missing source rows remain explicit UNKNOWN rows in a
calendar-complete derived prefix.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from upstreams.v3_shared_data.shared_data.hk_0_2 import (
    HistoricalHK02ResearchAsset,
    load_historical_hk_0_2_research_asset,
)


SCHEMA_VERSION = "v4.hk_prefix_research.v2"
METRIC_CONTRACT_VERSION = "v4.hk_prefix_research.terminal_metric.v1"
PROTOCOL_ID = "ZGE_OBSERVABLE_REPAIR_PROXY_V1"
EVIDENCE_BASIS = "FROZEN_HISTORY_RECONSTRUCTION"
LOOKBACK = 20
BAND_FRACTION = 0.25
RECLAIM_DAYS = 2
RETEST_DAYS = 5
PREFIX_LENGTH = 60
MAX_YEAR = 2025
PRICE_BASIS = "RAW_UNADJUSTED_ACTION_NOT_AUTHENTICATED"
VOLUME_SOURCE_COLUMN = "trade"
VOLUME_UNIT = "lots"
CALENDAR_SOURCE = "observed_union_daily_bars_691"
CALENDAR_CERTIFICATION = "CANNOT_CONFIRM_OFFICIAL_MARKET_CALENDAR"
SAFETY = {
    "RESEARCH_ONLY": True,
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

PREFIX_FIELDS: tuple[str, ...] = (
    "series_id",
    "session_index",
    "close_at",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "price_basis",
    "quality",
)
_PREFIX_FIELD_SET = frozenset(PREFIX_FIELDS)
_FORBIDDEN_PREFIX_FIELDS = frozenset(
    {
        "event_id",
        "event_date",
        "event_type",
        "case_id",
        "case_code",
        "control_future_label",
        "outcome",
        "label",
        "role",
        "pair_group_id",
    }
)
_KNOWN_STATES = frozenset(
    {
        "WARMUP",
        "NO_ACTIVE_SETUP",
        "BROKEN_PENDING",
        "RECLAIMED",
        "REPAIR_FAILED_TIMEOUT",
        "REBREAK",
        "RETEST_HELD_PROVISIONAL",
        "RETEST_HELD_HORIZON_COMPLETE",
    }
)
_QUALIFYING_STATES = frozenset(
    {"RETEST_HELD_PROVISIONAL", "RETEST_HELD_HORIZON_COMPLETE"}
)
_INDETERMINATE_TERMINAL_STATES = frozenset({"UNKNOWN", "WARMUP"})
MIN_COMPLETE_TERMINAL_PAIRS = 18
_REQUIRED_CALENDAR_COLUMNS = (
    "sdt_id",
    "S",
    "D",
    "T",
    "calendar_source",
    "calendar_certification",
)
_REQUIRED_PARITY_COLUMNS = (
    "S",
    "D",
    "T",
    "calendar_source",
    "calendar_certification",
)
_REQUIRED_GROUP_FIELDS = {
    "pair_group_id",
    "episode_id",
    "event_date",
    "event_type",
    "case_code",
    "controls",
}
_SHA256_RE = frozenset("0123456789abcdef")


class HKPrefixResearchError(ValueError):
    """A sanitized, deterministic rejection of a research input."""


@dataclass(frozen=True)
class FrozenPrefixGroup:
    """One immutable event/control group from the accepted binding."""

    pair_group_id: str
    episode_id: str
    event_date: str
    event_type: str
    case_code: str
    controls: tuple[str, ...]


@dataclass(frozen=True)
class FrozenMarketCalendar:
    dates: tuple[str, ...]
    date_to_index: Mapping[str, int]
    calendar_path: Path
    calendar_sha256: str
    parity_path: Path
    parity_sha256: str
    calendar_source: str
    calendar_certification: str
    row_count: int
    parity_row_count: int
    receipt_path: Path | None = None
    receipt_sha256: str | None = None
    code_path: Path | None = None
    code_sha256: str | None = None


@dataclass(frozen=True)
class PrefixArtifact:
    series_id: str
    group_index: int
    pair_group_id: str
    role: str
    code: str
    event_date: str
    event_type: str
    rows: tuple[dict[str, Any], ...]
    scan_rows: tuple[dict[str, Any], ...]
    input_sha256: str
    prefix_content_sha256: str
    terminal_state: str
    row_count: int
    unknown_count: int
    indeterminate_count: int
    known_count: int
    qualifying_count: int
    terminal_unknown: bool
    terminal_determinable: bool
    terminal_lower: float
    terminal_upper: float
    terminal_indeterminate_reason: str
    terminal_qualifies: bool
    occupancy_lower_rate: float
    occupancy_upper_rate: float
    unknown_reason_counts: Mapping[str, int]
    source_observed_rows: int
    source_missing_rows: int


def _terminal_endpoint_metrics(states: Sequence[str]) -> dict[str, Any]:
    """Return the terminal indicator and its uncertainty interval.

    The terminal state is the only primary endpoint.  A qualifying state is
    one, a non-qualifying known state is zero, and UNKNOWN/WARMUP are
    indeterminate endpoints with the conservative [0, 1] interval.  Path
    occupancy is calculated separately by ``_scan_artifact`` and must never
    stand in for this endpoint.
    """
    from domains._hk_prefix_research_parts.io_primitives import __terminal_endpoint_metrics_body as _v4_impl
    return _v4_impl(globals(), states)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _safe_json(value: Any) -> Any:
    """Convert pandas/numpy scalars and nonfinite values for receipts."""
    from domains._hk_prefix_research_parts.io_primitives import __safe_json_body as _v4_impl
    return _v4_impl(globals(), value)


def _read_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise HKPrefixResearchError(f"invalid JSON input: {path}") from error
    if not isinstance(value, Mapping):
        raise HKPrefixResearchError(f"JSON object required: {path}")
    return dict(value)


def _read_csv(path: Path | str) -> list[dict[str, str]]:
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as error:
        raise HKPrefixResearchError(f"cannot read CSV input: {path}") from error


def _iso_date(value: Any, *, field: str) -> str:
    from domains._hk_prefix_research_parts.io_primitives import __iso_date_body as _v4_impl
    return _v4_impl(globals(), value, field=field)


def _aware_eod(date_text: str) -> str:
    """Return the explicit reconstructed HK EOD timestamp used by this run."""

    date_value = datetime.strptime(date_text, "%Y-%m-%d").replace(
        hour=16, minute=0, second=0, microsecond=0, tzinfo=timezone(timedelta(hours=8))
    )
    return date_value.isoformat()


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("HK."):
        text = text[3:]
    elif text.endswith(".HK"):
        text = text[:-3]
    digits = "".join(character for character in text if character.isdigit())
    return f"HK.{digits.zfill(5)}" if digits and len(digits) <= 5 else ""


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and set(text) <= _SHA256_RE


def _assert_safe_flags(value: Mapping[str, Any], *, label: str) -> None:
    from domains._hk_prefix_research_parts.io_primitives import __assert_safe_flags_body as _v4_impl
    return _v4_impl(globals(), value, label=label)


def load_frozen_group_binding(
    binding_path: Path | str,
    *,
    matched_verdict_path: Path | str | None = None,
) -> tuple[list[FrozenPrefixGroup], dict[str, Any]]:
    """Read and verify the exact 24-group/72-control binding without sampling."""
    from domains._hk_prefix_research_parts.frozen_binding import _load_frozen_group_binding_body as _v4_impl
    return _v4_impl(globals(), binding_path, matched_verdict_path=matched_verdict_path)


def _validate_calendar_frame(frame: Any, *, label: str, required: Sequence[str]) -> Any:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise HKPrefixResearchError(f"{label} missing columns: {','.join(missing)}")
    out = frame[list(required)].copy()
    for column in ("S", "D", "T"):
        out[column] = out[column].map(lambda value: _iso_date(value, field=column))
    if out[list(("S", "D", "T"))].isna().any().any():
        raise HKPrefixResearchError(f"{label} contains null market dates")
    return out


def load_frozen_market_calendar(
    calendar_path: Path | str,
    parity_path: Path | str,
    *,
    receipt_path: Path | str | None = None,
    code_path: Path | str | None = None,
) -> FrozenMarketCalendar:
    """Load the accepted R1 calendar and validate its S/D/T semantics.

    The market-day index is made only from the frozen ``calendar_sdt.parquet``
    S/D/T rows.  It never derives dates from nonempty per-security bars.
    ``calendar_parity_rows`` is read as a separate identity/semantic check.
    """
    from domains._hk_prefix_research_parts.frozen_binding import _load_frozen_market_calendar_body as _v4_impl
    return _v4_impl(globals(), calendar_path, parity_path, receipt_path=receipt_path, code_path=code_path)


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _csv_number(value: Any) -> str:
    from domains._hk_prefix_research_parts.io_primitives import __csv_number_body as _v4_impl
    return _v4_impl(globals(), value)


def _row_from_source(
    source_row: Mapping[str, Any] | None,
    *,
    series_id: str,
    session_index: int,
    date_text: str,
) -> dict[str, Any]:
    from domains._hk_prefix_research_parts.prefix_rows import __row_from_source_body as _v4_impl
    return _v4_impl(globals(), source_row, series_id=series_id, session_index=session_index, date_text=date_text)


def build_prefix_rows(
    source_frame: Any,
    calendar: FrozenMarketCalendar,
    *,
    code: str,
    event_date: str,
    series_id: str,
) -> tuple[tuple[dict[str, Any], ...], int, int]:
    """Build exactly 60 calendar-indexed rows through event_date minus one."""
    from domains._hk_prefix_research_parts.prefix_rows import _build_prefix_rows_body as _v4_impl
    return _v4_impl(globals(), source_frame, calendar, code=code, event_date=event_date, series_id=series_id)


def _validate_scan_input(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        if set(row) != _PREFIX_FIELD_SET:
            raise HKPrefixResearchError("prefix scan input must use the exact reference whitelist")
        if set(row).intersection(_FORBIDDEN_PREFIX_FIELDS):
            raise HKPrefixResearchError("prefix scan input contains event/outcome identity")


def _load_scan_function(path: Path | str) -> Callable[..., list[dict[str, Any]]]:
    from domains._hk_prefix_research_parts.scan_execution import __load_scan_function_body as _v4_impl
    return _v4_impl(globals(), path)


def _scan_artifact(
    rows: tuple[dict[str, Any], ...],
    *,
    scan: Callable[..., list[dict[str, Any]]],
    expected_rows: int | None = None,
    asof: str | None = None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    from domains._hk_prefix_research_parts.scan_execution import __scan_artifact_body as _v4_impl
    return _v4_impl(globals(), rows, scan=scan, expected_rows=expected_rows, asof=asof)


def _write_new_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as error:
        raise HKPrefixResearchError(f"refuse to overwrite existing evidence: {path}") from error


def _write_json_new(path: Path, value: Any) -> dict[str, Any]:
    payload = _canonical_bytes(_safe_json(value)) + b"\n"
    _write_new_bytes(path, payload)
    return {"path": str(path), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def _write_csv_new(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    from domains._hk_prefix_research_parts.io_primitives import __write_csv_new_body as _v4_impl
    return _v4_impl(globals(), path, fields, rows)


def _artifact_digest(artifacts: Sequence[PrefixArtifact]) -> str:
    from domains._hk_prefix_research_parts.artifact_build import __artifact_digest_body as _v4_impl
    return _v4_impl(globals(), artifacts)


def _make_artifact(
    source_frame: Any,
    calendar: FrozenMarketCalendar,
    *,
    group_index: int,
    group: FrozenPrefixGroup,
    role: str,
    code: str,
    series_id: str,
    scan: Callable[..., list[dict[str, Any]]],
) -> PrefixArtifact:
    from domains._hk_prefix_research_parts.artifact_build import __make_artifact_body as _v4_impl
    return _v4_impl(globals(), source_frame, calendar, group_index=group_index, group=group, role=role, code=code, series_id=series_id, scan=scan)


def _group_artifacts(
    source_frame: Any,
    calendar: FrozenMarketCalendar,
    groups: Sequence[FrozenPrefixGroup],
    *,
    scan: Callable[..., list[dict[str, Any]]],
    group_limit: int | None = None,
) -> list[PrefixArtifact]:
    from domains._hk_prefix_research_parts.artifact_build import __group_artifacts_body as _v4_impl
    return _v4_impl(globals(), source_frame, calendar, groups, scan=scan, group_limit=group_limit)


def _write_prefix_csv(path: Path, artifact: PrefixArtifact) -> dict[str, Any]:
    return _write_csv_new(path, PREFIX_FIELDS, artifact.rows)


def _anonymous_index(artifacts: Sequence[PrefixArtifact], prefix_dir: Path) -> list[dict[str, Any]]:
    from domains._hk_prefix_research_parts.io_primitives import __anonymous_index_body as _v4_impl
    return _v4_impl(globals(), artifacts, prefix_dir)


def _identity_rows(artifacts: Sequence[PrefixArtifact]) -> list[dict[str, Any]]:
    from domains._hk_prefix_research_parts.comparison_rows import __identity_rows_body as _v4_impl
    return _v4_impl(globals(), artifacts)


def _pair_rows(
    artifacts: Sequence[PrefixArtifact],
    groups: Sequence[FrozenPrefixGroup],
) -> list[dict[str, Any]]:
    from domains._hk_prefix_research_parts.comparison_rows import __pair_rows_body as _v4_impl
    return _v4_impl(globals(), artifacts, groups)


def _terminal_contract_gate(pair_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate the frozen terminal endpoint coverage gate without tuning."""
    from domains._hk_prefix_research_parts.control_checks import __terminal_contract_gate_body as _v4_impl
    return _v4_impl(globals(), pair_rows)


def _summary_rows(pair_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from domains._hk_prefix_research_parts.comparison_rows import __summary_rows_body as _v4_impl
    return _v4_impl(globals(), pair_rows)


def _unknown_rows(artifacts: Sequence[PrefixArtifact]) -> list[dict[str, Any]]:
    from domains._hk_prefix_research_parts.comparison_rows import __unknown_rows_body as _v4_impl
    return _v4_impl(globals(), artifacts)


def _future_isolation_check(
    artifacts: Sequence[PrefixArtifact],
    *,
    scan: Callable[..., list[dict[str, Any]]],
) -> dict[str, Any]:
    """Append a changed future row and prove every prior result is unchanged."""
    from domains._hk_prefix_research_parts.control_checks import __future_isolation_check_body as _v4_impl
    return _v4_impl(globals(), artifacts, scan=scan)


def _positive_control_check(scan: Callable[..., list[dict[str, Any]]]) -> dict[str, Any]:
    """Use a fixed pre-2026 synthetic path as a past-positive machine control."""
    from domains._hk_prefix_research_parts.control_checks import __positive_control_check_body as _v4_impl
    return _v4_impl(globals(), scan)


def _field_check(artifacts: Sequence[PrefixArtifact]) -> dict[str, Any]:
    from domains._hk_prefix_research_parts.control_checks import __field_check_body as _v4_impl
    return _v4_impl(globals(), artifacts)


def _copy_exact_source(path: Path, destination: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise HKPrefixResearchError(f"cannot read frozen identity source: {path}") from error
    _write_new_bytes(destination, payload)
    return {"path": str(destination), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def _write_artifact_set(
    root: Path,
    artifacts: Sequence[PrefixArtifact],
    *,
    groups: Sequence[FrozenPrefixGroup],
    write_identity: bool,
) -> dict[str, Any]:
    from domains._hk_prefix_research_parts.io_primitives import __write_artifact_set_body as _v4_impl
    return _v4_impl(globals(), root, artifacts, groups=groups, write_identity=write_identity)


def _read_reused_prefix_csv(path: Path, *, series_id: str) -> tuple[dict[str, Any], ...]:
    """Read one already materialized prefix without touching the raw parquet."""
    from domains._hk_prefix_research_parts.reuse import __read_reused_prefix_csv_body as _v4_impl
    return _v4_impl(globals(), path, series_id=series_id)


def _reused_artifacts(
    source_root: Path,
    index_rows: Sequence[Mapping[str, str]],
    mapping_rows: Sequence[Mapping[str, str]],
    groups: Sequence[FrozenPrefixGroup],
    *,
    extractor_path: Path | str,
) -> list[PrefixArtifact]:
    """Reconstruct corrected metrics from the frozen 96 CSVs only.

    The old raw parquet is intentionally not opened in this path. Re-running
    the accepted zero-fit scanner on each already frozen window recovers the
    full state sequence needed to distinguish UNKNOWN/WARMUP endpoints while
    retaining the original window bytes for export.
    """
    from domains._hk_prefix_research_parts.reuse import __reused_artifacts_body as _v4_impl
    return _v4_impl(globals(), source_root, index_rows, mapping_rows, groups, extractor_path=extractor_path)


def _write_reused_result(
    root: Path,
    artifacts: Sequence[PrefixArtifact],
    *,
    groups: Sequence[FrozenPrefixGroup],
) -> dict[str, Any]:
    """Write corrected identity/metric ledgers for copied anonymous windows."""
    from domains._hk_prefix_research_parts.reuse import __write_reused_result_body as _v4_impl
    return _v4_impl(globals(), root, artifacts, groups=groups)


def rewrite_hk_prefix_research_result(
    *,
    source_root: Path | str,
    output_dir: Path | str,
    extractor_path: Path | str,
    qa_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Reissue the fixed historical asset using the original CSV bytes.

    This is a bounded correction pass after the metric-contract review. It
    reads the old manifest, binding, identity CSV and 96 derived windows, but
    never scans or rewrites the 691-symbol source parquet.
    """
    from domains._hk_prefix_research_parts.rewrite import _rewrite_hk_prefix_research_result_body as _v4_impl
    return _v4_impl(globals(), source_root=source_root, output_dir=output_dir, extractor_path=extractor_path, qa_receipt_sha256=qa_receipt_sha256)


def _manifest_identity(
    asset: HistoricalHK02ResearchAsset,
    calendar: FrozenMarketCalendar,
    binding_meta: Mapping[str, Any],
    *,
    source_path: Path,
    source_manifest_path: Path,
    binding_path: Path,
    extractor_path: Path,
    extractor_sha256: str,
) -> dict[str, Any]:
    from domains._hk_prefix_research_parts.manifest import __manifest_identity_body as _v4_impl
    return _v4_impl(globals(), asset, calendar, binding_meta, source_path=source_path, source_manifest_path=source_manifest_path, binding_path=binding_path, extractor_path=extractor_path, extractor_sha256=extractor_sha256)


def run_hk_prefix_research(
    *,
    source_path: Path | str,
    source_manifest_path: Path | str,
    source_sha256: str,
    calendar_path: Path | str,
    parity_path: Path | str,
    binding_path: Path | str,
    matched_verdict_path: Path | str,
    extractor_path: Path | str,
    output_dir: Path | str,
    calendar_receipt_path: Path | str | None = None,
    calendar_code_path: Path | str | None = None,
    cpu_threads: int = 4,
) -> dict[str, Any]:
    """Run one canary group, then all frozen 24 groups in one process."""
    from domains._hk_prefix_research_parts.research_run import _run_hk_prefix_research_body as _v4_impl
    return _v4_impl(globals(), source_path=source_path, source_manifest_path=source_manifest_path, source_sha256=source_sha256, calendar_path=calendar_path, parity_path=parity_path, binding_path=binding_path, matched_verdict_path=matched_verdict_path, extractor_path=extractor_path, output_dir=output_dir, calendar_receipt_path=calendar_receipt_path, calendar_code_path=calendar_code_path, cpu_threads=cpu_threads)


__all__ = [
    "BAND_FRACTION",
    "CALENDAR_CERTIFICATION",
    "CALENDAR_SOURCE",
    "EVIDENCE_BASIS",
    "METRIC_CONTRACT_VERSION",
    "FrozenMarketCalendar",
    "FrozenPrefixGroup",
    "HKPrefixResearchError",
    "LOOKBACK",
    "PREFIX_FIELDS",
    "PREFIX_LENGTH",
    "PRICE_BASIS",
    "RECLAIM_DAYS",
    "RETEST_DAYS",
    "MIN_COMPLETE_TERMINAL_PAIRS",
    "build_prefix_rows",
    "load_frozen_group_binding",
    "load_frozen_market_calendar",
    "rewrite_hk_prefix_research_result",
    "run_hk_prefix_research",
    "sha256_file",
]
