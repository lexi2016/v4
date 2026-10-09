"""Pure V3 stage-selection formulas and an isolated selection artifact store.

This module intentionally has no imports from V3/V3.5.  Inputs are normalized
records supplied by the stage-center acquisition boundary; the functions only
compute deterministic observations and never authorize a trade.
"""
from __future__ import annotations

import csv
import copy
import hashlib
import json
import math
import os
import re
import tempfile
import time
from infrastructure.interprocess_lock import owned_interprocess_lock
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4

from .calendar import calendar_provenance
from .contracts import (
    EIGHT_STAGES,
    SAFETY_FLAGS,
    SELECTION_ALGORITHM_ID,
    SELECTION_STATUSES,
    STAGE_RECOMMENDATION_LIMIT,
)


from stage_center._selection_parts import schema_values as _v4_definitions
SELECTION_ARTIFACT_FIELDS_V1 = _v4_definitions._value_SELECTION_ARTIFACT_FIELDS_V1(globals())
SELECTION_ARTIFACT_FIELDS_V2 = _v4_definitions._value_SELECTION_ARTIFACT_FIELDS_V2(globals())
# Preserve the historical public constant for callers that describe the v1
# wire shape. New envelopes use v2, while ``artifact.csv`` remains a v1
# projection so the immutable V3 consumer can read the shared run.
SELECTION_ARTIFACT_FIELDS = SELECTION_ARTIFACT_FIELDS_V1
SELECTION_SCHEMA_VERSION_V1 = "stage_center.selection.v1"
SELECTION_SCHEMA_VERSION = "stage_center.selection.v2"
SELECTION_SCHEMA_VERSIONS = frozenset({SELECTION_SCHEMA_VERSION_V1, SELECTION_SCHEMA_VERSION})
SELECTION_MANIFEST_SCHEMA_VERSION = "stage_center.selection.manifest.v1"
SELECTION_RECEIPT_SCHEMA_VERSION = "stage_center.selection.receipt.v1"
SELECTION_LATEST_SCHEMA_VERSION = "stage_center.selection.latest.v1"
SELECTION_STATUSES = frozenset(SELECTION_STATUSES)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_STALE_SECONDS = 30.0

# The formula-margin shadow is an explicitly opt-in observation hook.  Keeping
# the stage allowlist here makes it impossible for a caller to accidentally
# capture the 09:25 auction contract or an unrelated selector through this
# hook.  The callback is side-effect-only: the selector never consumes its
# return value and callback failures are isolated below.
HK_FORMULA_MARGIN_SHADOW_STAGES = frozenset(
    {
        "STAGE_0930_0935",
        "STAGE_0945_1030",
        "STAGE_1445_1500",
    }
)

# This is an explicit version manifest, rather than a caller-provided label.
# The digest is consequently stable across processes and binds the coefficients
# and status mapping used by this module.
LEGACY_ALGORITHM_MANIFEST: dict[str, Any] = _v4_definitions._value_LEGACY_ALGORITHM_MANIFEST(globals())
LEGACY_ALGORITHM_SOURCE_BYTES = json.dumps(
    LEGACY_ALGORITHM_MANIFEST, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
LEGACY_ALGORITHM_SHA256 = hashlib.sha256(LEGACY_ALGORITHM_SOURCE_BYTES).hexdigest()

# Top-10 truncation is part of the producer identity. A new SHA prevents a
# capped artifact from being confused with a legacy run that exposed the
# complete candidate rows, while the allowlist below keeps old artifacts
# readable.
TOP10_ALGORITHM_MANIFEST: dict[str, Any] = {
    **LEGACY_ALGORITHM_MANIFEST,
    "version": "stage_center.selection.v3_top10",
    "recommendation_limit": STAGE_RECOMMENDATION_LIMIT,
    "a_share": {
        **LEGACY_ALGORITHM_MANIFEST["a_share"],
        "formal_filter": "formal_metadata_overlay_only_exact_authority; stage_acquisition_rows_ranked",
        "truncate": "stable_sorted_rows[:10]",
    },
    "hk_connect": {
        **LEGACY_ALGORITHM_MANIFEST["hk_connect"],
        "membership": "exact_date_STRICT_0_2_READY_prob_active_top100",
        "truncate": "stable_sorted_rows[:10]",
    },
}
TOP10_ALGORITHM_SOURCE_BYTES = json.dumps(
    TOP10_ALGORITHM_MANIFEST, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
ALGORITHM_MANIFEST = TOP10_ALGORITHM_MANIFEST
ALGORITHM_SOURCE_BYTES = TOP10_ALGORITHM_SOURCE_BYTES
ALGORITHM_SHA256 = hashlib.sha256(TOP10_ALGORITHM_SOURCE_BYTES).hexdigest()

LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST: dict[str, Any] = _v4_definitions._value_LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST(globals())
LEGACY_A_SHARE_LIVE_ALGORITHM_SOURCE_BYTES = json.dumps(
    LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256 = hashlib.sha256(LEGACY_A_SHARE_LIVE_ALGORITHM_SOURCE_BYTES).hexdigest()
A_SHARE_LIVE_TOP10_ALGORITHM_MANIFEST: dict[str, Any] = {
    **LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST,
    "version": "stage_center.selection.a_share_live.v2_top10",
    "recommendation_limit": STAGE_RECOMMENDATION_LIMIT,
    "formal_metadata": "exact_authority_overlay_only; nonformal_rows_explicit_false",
    "tie_break": "acquisition_rank_before_lexical_code",
}
A_SHARE_LIVE_TOP10_ALGORITHM_SOURCE_BYTES = json.dumps(
    A_SHARE_LIVE_TOP10_ALGORITHM_MANIFEST,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
A_SHARE_LIVE_ALGORITHM_MANIFEST = A_SHARE_LIVE_TOP10_ALGORITHM_MANIFEST
A_SHARE_LIVE_ALGORITHM_SOURCE_BYTES = A_SHARE_LIVE_TOP10_ALGORITHM_SOURCE_BYTES
A_SHARE_LIVE_ALGORITHM_SHA256 = hashlib.sha256(A_SHARE_LIVE_TOP10_ALGORITHM_SOURCE_BYTES).hexdigest()
PRE_V11_TOP10_ALGORITHM_SHA256 = "fa010779606766f2bb94e2b5ef028a06df218ca6e68b48284a94c64bf0919657"
V11_PIT_TOP10_ALGORITHM_SHA256 = "8e04f83945294bd9c6c9a6bc1fa75b046c999860a3515f5d4f0538211fd09878"
ALGORITHM_SHA_ALLOWLIST = _v4_definitions._value_ALGORITHM_SHA_ALLOWLIST(globals())


class SelectionError(ValueError):
    """Fail-closed selection formula, envelope, or artifact error."""


def _canonical_sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _selection_identity_ids(
    trade_date: str,
    stage_id: str,
    market: str,
    raw_artifact_sha256: str,
    algorithm_sha256: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    """Return the immutable IDs for the shared selection identity.

    Every algorithm uses the same canonical payload: the logical slot,
    external raw-artifact SHA, algorithm SHA, and final serialized rows. No
    legacy or compatible identity is accepted by :class:`SelectionStore`.
    """
    from stage_center._selection_parts.primitives_io import __selection_identity_ids_body as _v4_impl
    return _v4_impl(globals(), trade_date, stage_id, market, raw_artifact_sha256, algorithm_sha256, rows)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    from stage_center._selection_parts.primitives_io import __atomic_write_bytes_body as _v4_impl
    return _v4_impl(globals(), path, data)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8"),
    )


def _atomic_write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] = SELECTION_ARTIFACT_FIELDS_V2,
) -> None:
    from stage_center._selection_parts.primitives_io import __atomic_write_csv_body as _v4_impl
    return _v4_impl(globals(), path, rows, fields=fields)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise SelectionError(f"invalid selection JSON: {path}") from error
    if not isinstance(payload, dict):
        raise SelectionError(f"selection JSON object required: {path}")
    return payload


def _safe_relative(root: Path, relative: str) -> Path:
    from stage_center._selection_parts.primitives_io import __safe_relative_body as _v4_impl
    return _v4_impl(globals(), root, relative)


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise SelectionError("trade_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise SelectionError("trade_date is not a real date") from error
    return value


def _validate_stage(stage_id: str) -> None:
    if not any(stage.stage_id == stage_id for stage in EIGHT_STAGES):
        raise SelectionError(f"unknown stage {stage_id!r}")


def _validate_market(stage_id: str, market: str) -> None:
    _validate_stage(stage_id)
    if market not in next(stage for stage in EIGHT_STAGES if stage.stage_id == stage_id).markets:
        raise SelectionError(f"market {market!r} is not scheduled for {stage_id!r}")


def _validate_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise SelectionError(f"{label} must be a lowercase SHA256")
    return value


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(number) else number


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _live_safe_float(value: Any) -> float | None:
    """Match the Windows scheduler's finite ``safe_float`` conversion."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _live_first_float(value: Any) -> float | None:
    if isinstance(value, list) and value:
        return _live_safe_float(value[0])
    return _live_safe_float(value)


def _live_bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _live_pct_change(new_value: float | None, old_value: float | None) -> float | None:
    if new_value is None or old_value in (None, 0):
        return None
    return (new_value / old_value - 1.0) * 100.0


def _stage_card_evidence(
    source: Mapping[str, Any],
    *,
    code: str,
    open_price: Any = None,
    last_price: Any = None,
    high_price: Any = None,
    low_price: Any = None,
    source_last_bar_time: Any = None,
    next_validation_time: Any = None,
) -> dict[str, Any]:
    """Normalize the evidence that both stage-center consumers render.

    The old V3 formulas only needed a code and score.  The shared artifact is
    also the UI's evidence boundary, so all stage-card fields are carried in
    one place.  Price-level defaults intentionally follow the old V3 rule:
    support/invalidation are the observed stage low and pressure is the stage
    high.  No code is ever used as a display name.
    """
    from stage_center._selection_parts.primitives_io import __stage_card_evidence_body as _v4_impl
    return _v4_impl(globals(), source, code=code, open_price=open_price, last_price=last_price, high_price=high_price, low_price=low_price, source_last_bar_time=source_last_bar_time, next_validation_time=next_validation_time)


def _live_close_position(
    last_price: float | None, high_price: float | None, low_price: float | None
) -> float:
    if last_price is None or high_price is None or low_price is None or high_price <= low_price:
        return 0.5
    return _live_bounded((last_price - low_price) / (high_price - low_price), 0.0, 1.0)


def _live_bid_pressure(bid_vol1: float | None, ask_vol1: float | None) -> float:
    if bid_vol1 is None or ask_vol1 is None or bid_vol1 + ask_vol1 <= 0:
        return 0.0
    return _live_bounded((bid_vol1 / (bid_vol1 + ask_vol1) - 0.5) * 12.0, -6.0, 6.0)


def live_stage_quality_score(
    qmt: Mapping[str, Any], candidate: Mapping[str, Any], stage_id: str = ""
) -> float:
    """Port Windows V3 ``live_stage_quality_score`` without backend imports."""
    from stage_center._selection_parts.market_quality import _live_stage_quality_score_body as _v4_impl
    return _v4_impl(globals(), qmt, candidate, stage_id)


def _live_rank_int(value: Any) -> int:
    try:
        return int(float(str(value or "999999")))
    except (TypeError, ValueError):
        return 999999


def stage_row_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, str]:
    """Port Windows V3 ``stage_row_sort_key`` exactly."""
    from stage_center._selection_parts.market_quality import _stage_row_sort_key_body as _v4_impl
    return _v4_impl(globals(), row)


def a_stage_score(*, window_change_pct: float, close_position: float, amount: float, complete: bool) -> float:
    """Port V3 ``_stage_score`` exactly, including clamp and two decimals."""
    coverage_penalty = 0 if complete else 18
    score = (
        50
        + _number(window_change_pct) * 8
        + _number(close_position) * 25
        + min(_number(amount) / 100_000_000, 4) * 3
        - coverage_penalty
    )
    return round(_clamp(score), 2)


def a_stage_label(window_change_pct: float, close_position: float, complete: bool) -> tuple[str, str]:
    """Port V3 ``_label`` while retaining research-only wording."""
    from stage_center._selection_parts.a_stage import _a_stage_label_body as _v4_impl
    return _v4_impl(globals(), window_change_pct, close_position, complete)


def _a_row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _a_normalized_row(row: Mapping[str, Any], *, source_mode: str) -> dict[str, Any]:
    from stage_center._selection_parts.primitives_io import __a_normalized_row_body as _v4_impl
    return _v4_impl(globals(), row, source_mode=source_mode)


def _selection_envelope(
    *,
    trade_date: str,
    stage_id: str,
    market: str,
    raw_artifact_sha256: str,
    source_status: str,
    input_rows: int,
    rows: Sequence[Mapping[str, Any]],
    requested_rows: int | None,
    missing_symbols: Sequence[str],
    cannot_confirm: Sequence[str],
    source_evidence: Sequence[str],
    algorithm_sha256: str = ALGORITHM_SHA256,
) -> dict[str, Any]:
    from stage_center._selection_parts.selection_envelope import __selection_envelope_body as _v4_impl
    return _v4_impl(globals(), trade_date=trade_date, stage_id=stage_id, market=market, raw_artifact_sha256=raw_artifact_sha256, source_status=source_status, input_rows=input_rows, rows=rows, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence, algorithm_sha256=algorithm_sha256)


def _legacy_backfill(source_evidence: Sequence[str]) -> bool:
    """Identify an explicitly labelled historical artifact compatibility path."""
    return any(str(item) == "HISTORICAL_BACKFILL" for item in source_evidence)


def _top10_contract(source_evidence: Sequence[str]) -> bool:
    """Return whether the caller opted into the new immutable Top-10 SHA."""
    return any(
        str(item) == "selection_contract=V3_TOP10_RECOMMENDATION"
        for item in source_evidence
    )


def _cap_recommendations(
    rows: Sequence[Mapping[str, Any]], *, preserve_legacy: bool = False
) -> list[dict[str, Any]]:
    """Return the immutable legacy V3 recommendation slice.

    Ranking is completed by each selector before this helper is called. The
    helper therefore only applies the public Top-10 boundary and re-numbers
    the exposed slice; it never re-sorts or manufactures rows. Python's list
    order remains the authoritative tie-break order.
    """
    from stage_center._selection_parts.selection_envelope import __cap_recommendations_body as _v4_impl
    return _v4_impl(globals(), rows, preserve_legacy=preserve_legacy)


def select_a_stage(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    stage_id: str,
    raw_artifact_sha256: str,
    *,
    source_status: str = "READY",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
    formal_incomplete: bool = False,
    source_mode: str = "A_SHARE_STAGE_BARS",
) -> dict[str, Any]:
    """Materialize A-share stage rows with V3's formal-pool semantics."""
    from stage_center._selection_parts.a_stage import _select_a_stage_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, stage_id, raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence, formal_incomplete=formal_incomplete, source_mode=source_mode)


def select_a_live_stage(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    stage_id: str,
    raw_artifact_sha256: str,
    *,
    source_status: str = "READY",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    """Materialize A rows using the Windows V3 live-stage formula.

    Each source row carries a ``qmt`` snapshot and a ``candidate`` formal-pool
    record (or their flattened equivalents).  This deliberately bypasses the
    older minute-bar ``select_a_stage`` formula: historical 09:40-09:45 rows
    must be recomputed from the exact pytdx adapter and formal candidate pool.
    """
    from stage_center._selection_parts.a_live import _select_a_live_stage_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, stage_id, raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence)


def select_a_0925_auction(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    raw_artifact_sha256: str,
    *,
    next_validation_time: str | None = None,
    source_status: str = "READY",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    """Port V3 ``_rows_from_auction`` for exact-date 09:25 evidence.

    The auction price is compared with the exact previous close and passed
    through the Windows V3 live-stage formula.  Auction amount is only the
    bounded liquidity bonus; it is never exposed as the recommendation score.
    Rows are ranked descending by the bounded score with Python-stable ties,
    and the route records the exact-date/time contract in evidence rather than
    falling through to minute-bar scoring.
    """
    from stage_center._selection_parts.a_auction import _select_a_0925_auction_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, raw_artifact_sha256, next_validation_time=next_validation_time, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence)


def _hk_float(row: Mapping[str, Any], *names: str) -> float | None:
    return _optional_number(_a_row_value(row, *names))


def _hk_money_yi(row: Mapping[str, Any]) -> float | None:
    value = _hk_float(row, "turnover_hkd_yi")
    if value is not None:
        return value
    raw = _hk_float(row, "turnover_hkd")
    return raw / 100_000_000 if raw is not None else None


def _hk_continuation_passes(row: Mapping[str, Any], stage_id: str, cap_limit_yi: float) -> bool:
    from stage_center._selection_parts.primitives_io import __hk_continuation_passes_body as _v4_impl
    return _v4_impl(globals(), row, stage_id, cap_limit_yi)


def hk_four_lane_score(
    row: Mapping[str, Any],
    stage_id: str | None = None,
    cap_limit_yi: float = 100.0,
) -> dict[str, Any]:
    """Port V3 ``_four_lane_score`` and return its evidence without mutation."""
    from stage_center._selection_parts.hk_formula_score import _hk_four_lane_score_body as _v4_impl
    return _v4_impl(globals(), row, stage_id, cap_limit_yi)


def hk_legacy_stage_sort_key(row: Mapping[str, Any]) -> tuple[int, int, float, float, float]:
    """Port the Windows V3 HK non-09:25 ordering tuple verbatim.

    ``hk_demon_service`` sorts the already-scored rows in descending tuple
    order.  The contract gate is deliberately evaluated before any later
    WATCH_ONLY presentation normalization.
    """
    from stage_center._selection_parts.market_quality import _hk_legacy_stage_sort_key_body as _v4_impl
    return _v4_impl(globals(), row)


def merge_hk_four_lane_candidates(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge same-code V3 lane rows while preserving lane/source precedence.

    The Windows service builds one row from several lane inputs.  The first
    non-empty live quote is authoritative for names and quote fields; later
    static-lane rows only contribute their lane labels and missing metadata.
    """
    from stage_center._selection_parts.hk_four_lanes import _merge_hk_four_lane_candidates_body as _v4_impl
    return _v4_impl(globals(), rows)


def hk_0925_pool_rank(row: Mapping[str, Any]) -> int:
    """Preserve the old pool/preopen/HK rank authority for 09:25."""
    return _live_rank_int(row.get("pool_rank") or row.get("preopen_rank") or row.get("hk_stage_rank"))


def _invoke_hk_formula_margin_shadow(
    callback: Callable[..., Any],
    *,
    raw_rows: Sequence[Mapping[str, Any]],
    sorted_rows: Sequence[Mapping[str, Any]],
    production_rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    stage_id: str,
    raw_artifact_sha256: str,
    source_status: str,
    requested_rows: int | None,
    source_evidence: Sequence[str],
    shadow_context: Mapping[str, Any] | None,
    error_callback: Callable[..., Any] | None,
) -> None:
    """Call the opt-in shadow observer with isolated copies of selector data.

    ``sorted_rows`` is copied immediately after the real comparator has run and
    before the public recommendation cap.  ``production_rows`` is the exact
    capped slice which the selector is about to return.  A callback therefore
    gets both the full rank source and the production Top10 without changing
    the selector envelope.  The copies also prevent an observer from mutating
    the rows subsequently returned by the production selector.

    This boundary intentionally swallows observer failures.  A research
    capture or its disk cannot change a production selection result.  Callers
    that want an immutable invalid ledger can provide ``error_callback``;
    errors from that callback are isolated as well.
    """
    from stage_center._selection_parts.shadow_capture import __invoke_hk_formula_margin_shadow_body as _v4_impl
    return _v4_impl(globals(), callback, raw_rows=raw_rows, sorted_rows=sorted_rows, production_rows=production_rows, trade_date=trade_date, stage_id=stage_id, raw_artifact_sha256=raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, source_evidence=source_evidence, shadow_context=shadow_context, error_callback=error_callback)


def select_hk_four_lane(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    stage_id: str,
    raw_artifact_sha256: str,
    *,
    source_status: str = "READY",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
    cap_limit_yi: float = 100.0,
    shadow_capture: Callable[..., Any] | None = None,
    shadow_context: Mapping[str, Any] | None = None,
    shadow_capture_error: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    from stage_center._selection_parts.hk_four_lanes import _select_hk_four_lane_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, stage_id, raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence, cap_limit_yi=cap_limit_yi, shadow_capture=shadow_capture, shadow_context=shadow_context, shadow_capture_error=shadow_capture_error)


def select_hk_0925_second_filter(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    raw_artifact_sha256: str,
    *,
    source_status: str = "READY",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    """Preserve the authoritative 09:20 second-filter rank/order verbatim."""
    from stage_center._selection_parts.hk_auction_filter import _select_hk_0925_second_filter_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence)


def select_hk_0925_d1_reference(
    rows: Sequence[Mapping[str, Any]],
    trade_date: str,
    raw_artifact_sha256: str,
    *,
    source_status: str = "CANNOT_CONFIRM",
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    """Expose the old-V3 D-1 Top10 while the exact 09:20 filter is missing.

    This is deliberately a reference lane, not a second-filter result.  It
    carries the frozen D-1 rank/name/score only, leaves quote fields empty,
    and keeps the envelope ``CANNOT_CONFIRM`` so consumers cannot treat the
    rows as a confirmed opening recommendation.
    """
    from stage_center._selection_parts.hk_auction_reference import _select_hk_0925_d1_reference_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date, raw_artifact_sha256, source_status=source_status, requested_rows=requested_rows, missing_symbols=missing_symbols, cannot_confirm=cannot_confirm, source_evidence=source_evidence)


def _artifact_fields_for_schema(schema_version: str | None) -> tuple[str, ...]:
    if schema_version == SELECTION_SCHEMA_VERSION_V1:
        return SELECTION_ARTIFACT_FIELDS_V1
    if schema_version in (None, SELECTION_SCHEMA_VERSION):
        # ``artifact.csv`` deliberately remains the legacy 12-column
        # projection.  The manifest envelope is the v2 carrier for the full
        # stage-card evidence, which lets the immutable V3 consumer continue
        # reading the shared run while V3.5 receives the richer envelope.
        return SELECTION_ARTIFACT_FIELDS_V1
    raise SelectionError("selection schema version mismatch")


def _artifact_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] = SELECTION_ARTIFACT_FIELDS_V2,
) -> list[dict[str, Any]]:
    from stage_center._selection_parts.artifact_codec import __artifact_rows_body as _v4_impl
    return _v4_impl(globals(), rows, fields=fields)


def _decode_artifact_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    from stage_center._selection_parts.artifact_codec import __decode_artifact_rows_body as _v4_impl
    return _v4_impl(globals(), rows, fields=fields)


class SelectionStore:
    """SafeRoot-style immutable selection runs with a separate latest pointer."""

    def __init__(self, root: Path | str):
        root_path = Path(root).expanduser()
        if root_path.exists() and root_path.is_symlink():
            raise SelectionError("selection store root symlink is forbidden")
        self.root = root_path.resolve()
        self.runs_root = self.root / "selection_runs"
        self.latest_path = self.root / "selection_latest.json"
        self.lock_path = self.root / ".selection.store.lock"

    @contextmanager
    def _lock(self):
        with owned_interprocess_lock(self.lock_path, timeout_seconds=_LOCK_TIMEOUT_SECONDS, timeout_message='selection store lock timeout', timeout_error=SelectionError):
            yield

    def _latest(self) -> dict[str, Any]:
        if not self.latest_path.exists():
            return {"schema_version": SELECTION_LATEST_SCHEMA_VERSION, "owner": "stage_center", "entries": {}, **SAFETY_FLAGS}
        latest = _read_json(self.latest_path)
        if latest.get("schema_version") != SELECTION_LATEST_SCHEMA_VERSION or latest.get("owner") != "stage_center":
            raise SelectionError("selection latest schema/owner mismatch")
        if not isinstance(latest.get("entries"), Mapping):
            raise SelectionError("selection latest entries missing")
        if any(latest.get(flag) is not False for flag in SAFETY_FLAGS):
            raise SelectionError("selection latest safety flag must be false")
        return latest

    @staticmethod
    def _key(trade_date: str, stage_id: str, market: str) -> str:
        return f"{_validate_date(trade_date)}/{stage_id}/{market}"

    @staticmethod
    def _role(stage_id: str, market: str) -> str:
        _validate_market(stage_id, market)
        return f"{market}_SELECTION_{stage_id}"

    def _verify_run(self, trade_date: str, stage_id: str, market: str, run_id: str) -> dict[str, Any]:
        from stage_center._selection_parts.store_verification import _SelectionStore__verify_run_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, stage_id, market, run_id)

    def publish(self, envelope: Mapping[str, Any], *, market: str) -> dict[str, Any]:
        from stage_center._selection_parts.store_publication import _SelectionStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, envelope, market=market)

    def read_verified(self, trade_date: str, stage_id: str, market: str) -> dict[str, Any]:
        latest = self._latest()
        key = self._key(trade_date, stage_id, market)
        entry = latest["entries"].get(key)
        if not isinstance(entry, Mapping):
            raise SelectionError(f"no selection latest for {key}")
        verified = self._verify_run(trade_date, stage_id, market, str(entry.get("run_id")))
        if entry.get("manifest_sha256") != verified["manifest_sha256"] or entry.get("receipt_sha256") != verified["receipt_sha256"]:
            raise SelectionError("selection latest pointer SHA mismatch")
        return verified["envelope"]


def publish_selection(root: Path | str, envelope: Mapping[str, Any], *, market: str) -> dict[str, Any]:
    return SelectionStore(root).publish(envelope, market=market)


def read_verified_selection(root: Path | str, trade_date: str, stage_id: str, market: str) -> dict[str, Any]:
    return SelectionStore(root).read_verified(trade_date, stage_id, market)


__all__ = _v4_definitions._value___all__(globals())
