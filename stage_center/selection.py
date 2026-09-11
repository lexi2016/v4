"""Pure V3 stage-selection formulas and an isolated selection artifact store.

This module intentionally has no imports from V3/V3.5.  Inputs are normalized
records supplied by the stage-center acquisition boundary; the functions only
compute deterministic observations and never authorize a trade.
"""
from __future__ import annotations

import csv
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
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from .calendar import calendar_provenance
from .contracts import (
    EIGHT_STAGES,
    SAFETY_FLAGS,
    SELECTION_ALGORITHM_ID,
    SELECTION_STATUSES,
    STAGE_RECOMMENDATION_LIMIT,
)


SELECTION_ARTIFACT_FIELDS_V1 = (
    "code",
    "score",
    "rank",
    "status",
    "formal_eligible",
    "support",
    "pressure",
    "invalidation",
    "source_mode",
    "lane_evidence",
    "action_level",
    "trade_status",
)
SELECTION_ARTIFACT_FIELDS_V2 = (
    *SELECTION_ARTIFACT_FIELDS_V1,
    "name",
    "stock_name",
    "current_change_pct",
    "open_price",
    "last_price",
    "high_price",
    "low_price",
    "source_last_bar_time",
    "next_validation_time",
    # V3 and V3.5 use different public spellings.  Persist both in the
    # producer so neither consumer has to infer missing evidence.
    "support_primary_price",
    "pressure_price",
    "invalidation_price",
)
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

# This is an explicit version manifest, rather than a caller-provided label.
# The digest is consequently stable across processes and binds the coefficients
# and status mapping used by this module.
LEGACY_ALGORITHM_MANIFEST: dict[str, Any] = {
    "algorithm_id": SELECTION_ALGORITHM_ID,
    "version": "stage_center.selection.v2",
    "a_share": {
        "score": "round(clamp(50 + 8*window_change_pct + 25*close_position + 3*min(amount/1e8,4) - (0 if complete else 18)),0,100),2)",
        "sort": "score_desc_python_stable_input_order",
        "formal_filter": "eligible_rows_if_any_else_empty_when_FORMAL_INCOMPLETE_else_all",
    },
    "hk_connect": {
        "four_lane_score_base": 42,
        "caps": {"small_cap_yi": 100.0, "continuation_soft_yi": 150.0},
        "action_boundary": "all_actions_NO_BUY_trade_status_research_only",
        "0925": "preserve_second_filter_rank_and_order",
    },
}
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

LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST: dict[str, Any] = {
    "algorithm_id": SELECTION_ALGORITHM_ID,
    "version": "stage_center.selection.a_share_live.v1",
    "score": "round(50 + 9*window_change_pct + 25*close_position + min(amount/1e8,6)*2.5 + bid_pressure + clamp(pool_score/125,0,1)*8,6)",
    "bid_pressure": "clamp((bid_vol1/(bid_vol1+ask_vol1)-0.5)*12,-6,6), else 0 when either side missing or sum<=0",
    "stage_0925": "round(50 + clamp(gap_change_pct,-10,10)*10 + amount_bonus + bid_pressure + clamp(pool_score/125,0,1)*3,6)",
    "sort": "(-stage_score,-qmt_amount,formal_rank,stock_code); STAGE_0925 uses (-stage_score,-qmt_gap_pct,-int(qmt_amount),stock_code)",
    "research_bonus": "min((news_quality_score+research_quality_score)/40,5)",
}
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
ALGORITHM_SHA_ALLOWLIST = frozenset(
    {
        LEGACY_ALGORITHM_SHA256,
        ALGORITHM_SHA256,
        LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256,
        A_SHARE_LIVE_ALGORITHM_SHA256,
        PRE_V11_TOP10_ALGORITHM_SHA256,
        V11_PIT_TOP10_ALGORITHM_SHA256,
    }
)


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
    identity = {
        "identity": f"{trade_date}/{stage_id}/{market}",
        "raw_artifact_sha256": raw_artifact_sha256,
        "algorithm_sha256": algorithm_sha256,
        "rows": list(rows),
    }
    canonical = _canonical_sha(identity)
    return f"selection-{canonical[:24]}", f"run-{canonical[:24]}"


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=fields,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise SelectionError(f"invalid selection JSON: {path}") from error
    if not isinstance(payload, dict):
        raise SelectionError(f"selection JSON object required: {path}")
    return payload


def _safe_relative(root: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or (len(relative) > 1 and relative[1] == ":")
    ):
        raise SelectionError("selection path must be normalized and relative")
    parsed = PurePosixPath(relative)
    if parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise SelectionError("selection path must be normalized and relative")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise SelectionError("selection symlink component is forbidden")
    try:
        current.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise SelectionError("selection path escapes store root") from error
    return current


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
    def first(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    normalized_open = _optional_number(first(open_price, source.get("open_price"), source.get("open"), source.get("first_open")))
    normalized_last = _optional_number(first(last_price, source.get("last_price"), source.get("last"), source.get("last_close"), source.get("close")))
    normalized_high = _optional_number(first(high_price, source.get("high_price"), source.get("high")))
    normalized_low = _optional_number(first(low_price, source.get("low_price"), source.get("low")))
    current_change = _optional_number(source.get("current_change_pct"))
    if current_change is None:
        current_change = _live_pct_change(normalized_last, normalized_open)
    support = _optional_number(first(source.get("support"), source.get("support_primary_price"), source.get("support_price")))
    pressure = _optional_number(first(source.get("pressure"), source.get("pressure_price"), source.get("resistance_price")))
    invalidation = _optional_number(first(source.get("invalidation"), source.get("invalidation_price")))
    support = normalized_low if support is None else support
    pressure = normalized_high if pressure is None else pressure
    invalidation = support if invalidation is None else invalidation
    name = first(source.get("name"), source.get("stock_name"))
    if name is not None and str(name).strip() == code:
        name = None
    last_bar_time = first(source_last_bar_time, source.get("source_last_bar_time"), source.get("update_time"), source.get("source_last_tick_time"))
    validation_time = first(next_validation_time, source.get("next_validation_time"))
    return {
        "name": name,
        "stock_name": name,
        "current_change_pct": None if current_change is None else round(current_change, 4),
        "open_price": normalized_open,
        "last_price": normalized_last,
        "high_price": normalized_high,
        "low_price": normalized_low,
        "support": support,
        "pressure": pressure,
        "invalidation": invalidation,
        "source_last_bar_time": last_bar_time,
        "next_validation_time": validation_time,
        "support_primary_price": support,
        "pressure_price": pressure,
        "invalidation_price": invalidation,
    }


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
    open_price = _live_safe_float(qmt.get("open")) or _live_safe_float(qmt.get("lastPrice"))
    last_price = _live_safe_float(qmt.get("lastPrice"))
    prev_close = _live_safe_float(qmt.get("lastClose"))
    high_price = _live_safe_float(qmt.get("high")) or last_price
    low_price = _live_safe_float(qmt.get("low")) or last_price
    amount = _live_safe_float(qmt.get("amount")) or 0.0
    bid_vol1 = _live_first_float(qmt.get("bidVol"))
    ask_vol1 = _live_first_float(qmt.get("askVol"))
    pool_score = _live_safe_float(candidate.get("score")) or 0.0
    gap_change = _live_pct_change(open_price, prev_close) or 0.0
    window_change = _live_pct_change(last_price, open_price) or 0.0
    amount_bonus = min(amount / 100_000_000.0, 6.0) * 2.5
    bid_pressure = _live_bid_pressure(bid_vol1, ask_vol1)
    pool_ratio = _live_bounded(pool_score / 125.0, 0.0, 1.0)
    if stage_id == "STAGE_0925":
        score = (
            50.0
            + _live_bounded(gap_change, -10.0, 10.0) * 10.0
            + amount_bonus
            + bid_pressure
            + pool_ratio * 3.0
        )
        return round(score, 6)
    score = (
        50.0
        + window_change * 9.0
        + _live_close_position(last_price, high_price, low_price) * 25.0
        + amount_bonus
        + bid_pressure
        + pool_ratio * 8.0
    )
    return round(score, 6)


def _live_rank_int(value: Any) -> int:
    try:
        return int(float(str(value or "999999")))
    except (TypeError, ValueError):
        return 999999


def stage_row_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, str]:
    """Port Windows V3 ``stage_row_sort_key`` exactly."""
    gap_value = _live_safe_float(row.get("qmt_gap_pct"))
    gap_tiebreak = -999999.0 if gap_value is None else gap_value
    amount_tiebreak = _live_safe_float(row.get("qmt_amount")) or 0.0
    if row.get("stage_id") == "STAGE_0925":
        second_key = gap_tiebreak
        third_key = -int(amount_tiebreak)
    else:
        second_key = amount_tiebreak
        third_key = _live_rank_int(row.get("stage1_formal_rank") or row.get("pool_rank"))
    acquisition_rank = row.get("acquisition_rank", row.get("source_order"))
    if acquisition_rank not in (None, ""):
        try:
            tie_break = f"{int(float(str(acquisition_rank))):09d}"
        except (TypeError, ValueError):
            tie_break = str(acquisition_rank)
    else:
        # Historical callers that do not carry an explicit acquisition rank
        # retain the old lexical fallback. Production rows always carry the
        # validated raw ``batch_index`` so ties cannot be filled by code order.
        tie_break = str(row.get("stock_code") or "")
    score_value = _live_safe_float(row.get("stage_score"))
    return (
        -(-999999.0 if score_value is None else score_value),
        -second_key,
        third_key,
        tie_break,
    )


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
    window_change = _number(window_change_pct)
    close = _number(close_position)
    if not complete:
        return "阶段数据不完整观察", "窗口内分钟线覆盖不足，只能作为部分观察。"
    if window_change >= 2 and close >= 0.65:
        return "阶段强承接观察", "窗口内上涨并靠近高位收，作为阶段观察。"
    if window_change > 0 and close >= 0.45:
        return "阶段承接一般观察", "窗口内小幅上涨或承接一般，等待下一阶段确认。"
    if window_change <= -3:
        return "阶段明显转弱观察", "窗口内明显回落，不能升级为买入依据。"
    return "仅观察", "窗口结构不清晰，只保留观察。"


def _a_row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _a_normalized_row(row: Mapping[str, Any], *, source_mode: str) -> dict[str, Any]:
    code = str(_a_row_value(row, "code", "ts_code", "stock_code") or "").strip()
    if not code:
        raise SelectionError("A selection row code is required")
    first_open = _optional_number(_a_row_value(row, "first_open", "open"))
    last_close = _optional_number(_a_row_value(row, "last_close", "close"))
    high = _optional_number(_a_row_value(row, "high", "high_price"))
    low = _optional_number(_a_row_value(row, "low", "low_price"))
    can_compute = first_open is not None and last_close is not None and high is not None and low is not None
    window_change = _optional_number(row.get("window_change_pct"))
    if window_change is None:
        window_change = ((last_close / first_open - 1) * 100) if can_compute and first_open else 0.0
    close_position = _optional_number(row.get("close_position"))
    if close_position is None:
        close_position = ((last_close - low) / (high - low)) if can_compute and high != low else 0.5
    observed_rows = _optional_number(row.get("bar_count"))
    expected_rows = _optional_number(row.get("expected_rows"))
    complete_default = bool(
        observed_rows is not None and expected_rows is not None and observed_rows >= expected_rows
    )
    complete = _truthy(row.get("complete"), complete_default)
    amount = _number(_a_row_value(row, "amount", "amount_in_window"))
    label, note = a_stage_label(window_change, close_position, complete)
    card = _stage_card_evidence(
        row,
        code=code,
        open_price=first_open,
        last_price=last_close,
        high_price=high,
        low_price=low,
    )
    support = card["support"]
    pressure = card["pressure"]
    invalidation = card["invalidation"]
    return {
        "code": code,
        "score": a_stage_score(
            window_change_pct=window_change,
            close_position=close_position,
            amount=amount,
            complete=complete,
        ),
        "status": label,
        "formal_eligible": _truthy(row.get("formal_eligible")),
        "support": support,
        "pressure": pressure,
        "invalidation": invalidation,
        "source_mode": source_mode,
        "lane_evidence": ["A_SHARE_FORMAL_POOL" if _truthy(row.get("formal_eligible")) else "A_SHARE_STAGE_BARS"],
        "action_level": "WATCH_ONLY",
        "trade_status": "WATCH_ONLY",
        "note": note,
        "window_change_pct": round(window_change, 4),
        "close_position": round(close_position, 4),
        "complete": complete,
        **card,
    }


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
    _validate_date(trade_date)
    _validate_market(stage_id, market)
    _validate_sha(raw_artifact_sha256, "raw_artifact_sha256")
    if algorithm_sha256 not in ALGORITHM_SHA_ALLOWLIST:
        raise SelectionError("selection algorithm binding mismatch")
    if source_status not in SELECTION_STATUSES:
        source_status = "CANNOT_CONFIRM" if source_status in {"READ_FAILED", "CANNOT_CONFIRM"} else "READY"
    output_rows = [dict(row) for row in rows]
    cannot = list(dict.fromkeys(str(item) for item in cannot_confirm if str(item)))
    missing = list(dict.fromkeys(str(item) for item in missing_symbols if str(item)))
    requested = input_rows if requested_rows is None else int(requested_rows)
    if requested < 0:
        raise SelectionError("requested_rows must be non-negative")
    if not output_rows:
        status = "CANNOT_CONFIRM" if cannot or source_status in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"} else "READY_EMPTY"
    elif source_status == "CANNOT_CONFIRM" or cannot:
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "PARTIAL_WITH_ROWS":
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "READY" and requested > input_rows:
        # A collector that returns fewer rows than its declared request is
        # partial even when it did not provide an explicit missing-symbol
        # list. A Top-10 cap does not trigger this branch because ``input_rows``
        # remains the full exact-date acquisition count.
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "READY_EMPTY":
        status = "CANNOT_CONFIRM"
    else:
        status = "READY"
    coverage = round(min(len(output_rows) / requested, 1.0), 6) if requested else (1.0 if not output_rows else 0.0)
    artifact_id, run_id = _selection_identity_ids(
        trade_date,
        stage_id,
        market,
        raw_artifact_sha256,
        algorithm_sha256,
        output_rows,
    )
    envelope = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "artifact_id": artifact_id,
        "run_id": run_id,
        "algorithm_id": SELECTION_ALGORITHM_ID,
        "algorithm_sha256": algorithm_sha256,
        "raw_artifact_sha256": raw_artifact_sha256,
        "source_status": source_status,
        "selection_status": status,
        "requested_rows": requested,
        "source_rows": input_rows,
        "selected_rows": len(output_rows),
        "coverage_ratio": coverage,
        "missing_symbols": missing,
        "rows": output_rows,
        "source_evidence": list(dict.fromkeys(str(item) for item in source_evidence if str(item))),
        "cannot_confirm": cannot,
        **SAFETY_FLAGS,
    }
    return envelope


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
    capped = [dict(row) for row in (rows if preserve_legacy else rows[:STAGE_RECOMMENDATION_LIMIT])]
    for rank, row in enumerate(capped, start=1):
        row["rank"] = rank
    return capped


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
    _validate_date(trade_date)
    _validate_market(stage_id, "A_SHARE")
    normalized_input = [_a_normalized_row(row, source_mode=source_mode) for row in rows]
    for source in rows:
        row_date = str(_a_row_value(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise SelectionError("A selection trade_date drift")
        row_stage = str(source.get("stage_id") or "").strip()
        if row_stage and row_stage != stage_id:
            raise SelectionError("A selection stage_id drift")
    eligible = [row for source, row in zip(rows, normalized_input) if _truthy(source.get("formal_eligible"))]
    if eligible:
        selected = [row for source, row in zip(rows, normalized_input) if _truthy(source.get("formal_eligible"))]
    elif formal_incomplete:
        return _selection_envelope(
            trade_date=trade_date,
            stage_id=stage_id,
            market="A_SHARE",
            raw_artifact_sha256=raw_artifact_sha256,
            source_status="CANNOT_CONFIRM",
            input_rows=len(rows),
            rows=(),
            requested_rows=requested_rows,
            missing_symbols=missing_symbols,
            cannot_confirm=(*cannot_confirm, "FORMAL_INCOMPLETE_WITHOUT_ELIGIBLE_ROWS"),
            source_evidence=source_evidence,
        )
    else:
        selected = normalized_input
    # Python's stable sort is intentional: V3 ranks equal scores according to
    # authoritative source order, never lexical code order.
    top10 = _top10_contract(source_evidence)
    # The explicit production contract has priority over historical replay
    # compatibility evidence.  A production artifact must never widen back
    # to the old unbounded historical slice merely because its source also
    # carries a replay marker.
    legacy = _legacy_backfill(source_evidence) and not top10
    selected = _cap_recommendations(
        sorted(selected, key=lambda item: item["score"], reverse=True), preserve_legacy=legacy
    )
    algorithm_sha = (
        ALGORITHM_SHA256 if top10 else LEGACY_ALGORITHM_SHA256
    )
    evidence = (*source_evidence, f"algorithm_sha256={algorithm_sha}", f"source_mode={source_mode}")
    return _selection_envelope(
        trade_date=trade_date,
        stage_id=stage_id,
        market="A_SHARE",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status,
        input_rows=len(rows),
        rows=selected,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=evidence,
        algorithm_sha256=algorithm_sha,
    )


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
    _validate_date(trade_date)
    _validate_market(stage_id, "A_SHARE")
    selected: list[dict[str, Any]] = []
    for source in rows:
        code = str(_a_row_value(source, "code", "stock_code", "ts_code") or "").strip()
        if not code:
            raise SelectionError("A live stage row code is required")
        row_date = str(_a_row_value(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise SelectionError("A live stage trade_date drift")
        row_stage = str(source.get("stage_id") or "").strip()
        if row_stage and row_stage != stage_id:
            raise SelectionError("A live stage stage_id drift")
        qmt_value = source.get("qmt")
        qmt = dict(qmt_value) if isinstance(qmt_value, Mapping) else {
            "open": source.get("qmt_open", source.get("open")),
            "lastPrice": source.get("qmt_last", source.get("lastPrice", source.get("price"))),
            "lastClose": source.get("qmt_prev_close", source.get("lastClose")),
            "high": source.get("qmt_high", source.get("high")),
            "low": source.get("qmt_low", source.get("low")),
            "amount": source.get("qmt_amount", source.get("amount")),
            "bidVol": source.get("qmt_bid_vol1", source.get("bidVol")),
            "askVol": source.get("qmt_ask_vol1", source.get("askVol")),
        }
        candidate_value = source.get("candidate")
        candidate = dict(candidate_value) if isinstance(candidate_value, Mapping) else {
            "score": source.get("pool_score", source.get("candidate_score", source.get("score", 0.0))),
        }
        live_score = live_stage_quality_score(qmt, candidate, stage_id)
        news_score = _live_safe_float(source.get("news_quality_score")) or 0.0
        research_score = _live_safe_float(source.get("research_quality_score")) or 0.0
        research_bonus = min((news_score + research_score) / 40.0, 5.0)
        stage_score = round(live_score + research_bonus, 6)
        card = _stage_card_evidence(
            source,
            code=code,
            open_price=qmt.get("open"),
            last_price=qmt.get("lastPrice"),
            high_price=qmt.get("high"),
            low_price=qmt.get("low"),
        )
        formal_eligible = _truthy(source.get("formal_eligible"), False)
        lane_evidence = list(source.get("lane_evidence") or ())
        if formal_eligible:
            if not lane_evidence:
                lane_evidence = ["A_SHARE_FORMAL_POOL"]
        else:
            # A stale upstream lane marker is not authority.  Non-formal
            # acquisition rows must not retain the formal-pool identity.
            lane_evidence = [item for item in lane_evidence if item != "A_SHARE_FORMAL_POOL"]
            if "STAGE_ACQUISITION_UNIVERSE" not in lane_evidence:
                lane_evidence.append("STAGE_ACQUISITION_UNIVERSE")
        stage_row = {
            "code": code,
            "score": stage_score,
            "status": "WATCH_ONLY",
            "formal_eligible": formal_eligible,
            **card,
            "source_mode": "A_SHARE_WINDOWS_V3_LIVE_STAGE",
            "lane_evidence": list(dict.fromkeys((*lane_evidence, "WINDOWS_V3_LIVE_FORMULA"))),
            "action_level": "WATCH_ONLY",
            "trade_status": "WATCH_ONLY",
            "stage_id": stage_id,
            "trade_date": trade_date,
            "stage_score": stage_score,
            "stage1_formal_rank": str(source.get("stage1_formal_rank") or source.get("formal_rank") or ""),
            "pool_score": str(candidate.get("score") or ""),
            "qmt_amount": _live_safe_float(qmt.get("amount")) or 0.0,
            "qmt_gap_pct": _live_pct_change(
                _live_safe_float(qmt.get("open")) or _live_safe_float(qmt.get("lastPrice")),
                _live_safe_float(qmt.get("lastClose")),
            ) or 0.0,
            "stock_code": code,
            "acquisition_rank": source.get("acquisition_rank", source.get("source_order", "")),
            "news_quality_score": news_score,
            "research_quality_score": research_score,
            "research_bonus": research_bonus,
            "latest_research_slot": source.get("latest_research_slot", ""),
            "research_delta_hits": source.get("research_delta_hits", 0),
            "news_research_reason": source.get("news_research_reason", ""),
            "source_health": source.get("source_health", ""),
        }
        selected.append(stage_row)
    top10 = _top10_contract(source_evidence)
    legacy = _legacy_backfill(source_evidence) and not top10
    selected = _cap_recommendations(sorted(selected, key=stage_row_sort_key), preserve_legacy=legacy)
    algorithm_sha = (
        A_SHARE_LIVE_ALGORITHM_SHA256 if top10 else LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256
    )
    envelope = _selection_envelope(
        trade_date=trade_date,
        stage_id=stage_id,
        market="A_SHARE",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status,
        input_rows=len(rows),
        rows=selected,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(
            *source_evidence,
            f"algorithm_sha256={algorithm_sha}",
            "formula=windows_v3_live_stage_quality_score",
            "sort=windows_v3_stage_row_sort_key",
        ),
        algorithm_sha256=algorithm_sha,
    )
    return envelope


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
    _validate_date(trade_date)
    _validate_market("STAGE_0925", "A_SHARE")
    normalized: list[dict[str, Any]] = []
    invalid_evidence: list[str] = []
    for index, source in enumerate(rows):
        row_date = str(_a_row_value(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise SelectionError("A 09:25 auction trade_date drift")
        time_value = str(_a_row_value(source, "time", "captured_at", "update_time") or "")
        time_match = re.search(r"(?:^|\D)(\d{1,2}):(\d{2})(?:\D|$)", time_value)
        if time_match:
            hhmm_value: int | None = int(time_match.group(1)) * 100 + int(time_match.group(2))
        elif re.fullmatch(r"\d{4}", time_value.strip()):
            hhmm_value = int(time_value.strip())
        else:
            hhmm_value = None
        if hhmm_value is None:
            invalid_evidence.append(f"row {index + 1} lacks a verifiable auction time")
            continue
        if not (920 <= hhmm_value <= 930):
            invalid_evidence.append(f"row {index + 1} outside 09:20-09:30 auction window")
            continue
        if not _truthy(source.get("is_open_call_auction_match"), True):
            invalid_evidence.append(f"row {index + 1} is not an opening auction match")
            continue
        code = str(_a_row_value(source, "code", "ts_code", "stock_code") or "").strip()
        if not code:
            raise SelectionError("A 09:25 auction row code is required")
        amount = _number(_a_row_value(source, "amount_yuan", "auction_amount_est_yuan", "amount"))
        price = _optional_number(_a_row_value(source, "price", "open_price", "last_price"))
        prev_close = _optional_number(
            _a_row_value(source, "prev_close_price", "prev_close", "last_close")
        )
        current_change = _live_pct_change(price, prev_close)
        qmt = {
            "open": price,
            "lastPrice": price,
            "lastClose": prev_close,
            "high": _optional_number(_a_row_value(source, "high_price", "high")) or price,
            "low": _optional_number(_a_row_value(source, "low_price", "low")) or price,
            "amount": amount,
            "bidVol": _a_row_value(source, "bid_vol", "bid_vol1"),
            "askVol": _a_row_value(source, "ask_vol", "ask_vol1"),
        }
        bounded_score = _clamp(
            live_stage_quality_score(
                qmt,
                {"score": _a_row_value(source, "pool_score", "candidate_score")},
                "STAGE_0925",
            )
        )
        card_source = dict(source)
        card_source["current_change_pct"] = current_change
        card = _stage_card_evidence(
            card_source,
            code=code,
            open_price=_a_row_value(source, "open_price", "open"),
            last_price=_a_row_value(source, "last_price", "close", "price"),
            high_price=_a_row_value(source, "high_price", "high"),
            low_price=_a_row_value(source, "low_price", "low"),
            source_last_bar_time=_a_row_value(source, "update_time", "time"),
            next_validation_time=next_validation_time or _a_row_value(source, "next_validation_time"),
        )
        normalized.append(
            {
                "code": code,
                "score": round(bounded_score, 6),
                "status": "集合竞价成交代理观察",
                "formal_eligible": False,
                "prev_close_price": prev_close,
                "current_change_pct": None if current_change is None else round(current_change, 4),
                "qmt_gap_pct": 0.0 if current_change is None else round(current_change, 6),
                "qmt_amount": amount,
                "stage_score": round(bounded_score, 6),
                "support": price,
                "pressure": price,
                "invalidation": price,
                "source_mode": "A_SHARE_AUCTION_TRANSACTION_STAGE_0925",
                "lane_evidence": [
                    "A_SHARE_EXACT_DATE_AUCTION_TRANSACTION",
                    "window=09:20-09:30",
                    "exact_date=true",
                    "formula=windows_v3_live_stage_quality_score",
                    "score_bounded_0_100=true",
                    "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE",
                ],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "bar_order": index,
                **card,
            }
        )
    normalized = _cap_recommendations(sorted(normalized, key=lambda item: item["score"], reverse=True))
    cannot = (*cannot_confirm, *invalid_evidence)
    top10 = _top10_contract(source_evidence)
    legacy = _legacy_backfill(source_evidence) and not top10
    algorithm_sha = A_SHARE_LIVE_ALGORITHM_SHA256 if top10 else LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256
    evidence = (
        *source_evidence,
        "route=a_share_exact_date_auction_transaction",
        "exact_date=true",
        "window=09:20-09:30",
        "formula=windows_v3_live_stage_quality_score",
        "score_bounded_0_100=true",
        "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE",
        f"algorithm_sha256={algorithm_sha}",
    )
    return _selection_envelope(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="A_SHARE",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status if not invalid_evidence else "CANNOT_CONFIRM",
        input_rows=len(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot,
        source_evidence=evidence,
        algorithm_sha256=algorithm_sha,
    )


def _hk_float(row: Mapping[str, Any], *names: str) -> float | None:
    return _optional_number(_a_row_value(row, *names))


def _hk_money_yi(row: Mapping[str, Any]) -> float | None:
    value = _hk_float(row, "turnover_hkd_yi")
    if value is not None:
        return value
    raw = _hk_float(row, "turnover_hkd")
    return raw / 100_000_000 if raw is not None else None


def _hk_continuation_passes(row: Mapping[str, Any], stage_id: str, cap_limit_yi: float) -> bool:
    stage_ids = [stage.stage_id for stage in EIGHT_STAGES]
    if stage_id not in stage_ids or stage_ids.index(stage_id) < stage_ids.index("STAGE_0940_0945"):
        return False
    lanes = set(row.get("candidate_lanes") or [])
    if not {"PREOPEN_AUCTION_CONTINUATION", "LIVE_HKCONNECT_GAINER"}.issubset(lanes):
        return False
    cap = _hk_float(row, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
    if cap is not None and cap > max(cap_limit_yi, 150.0):
        return False
    pct = _hk_float(row, "pct_chg")
    window = _hk_float(row, "stage_window_change_pct", "window_change_pct")
    turnover = _hk_money_yi(row)
    return ((pct is not None and pct >= 4) or (window is not None and window >= 3)) and turnover is not None and turnover >= 0.2


def hk_four_lane_score(
    row: Mapping[str, Any],
    stage_id: str | None = None,
    cap_limit_yi: float = 100.0,
) -> dict[str, Any]:
    """Port V3 ``_four_lane_score`` and return its evidence without mutation."""
    stage = stage_id or str(row.get("stage_id") or "STAGE_0930_0935")
    lanes = list(dict.fromkeys(str(item) for item in (row.get("candidate_lanes") or ([row.get("lane")] if row.get("lane") else []))))
    # Never trust an adapter's precomputed continuation flag; the V3 lane,
    # stage, cap, strength, and turnover evidence is recomputed here.
    continuation_pass = _hk_continuation_passes(row, stage, cap_limit_yi)
    pct = _hk_float(row, "pct_chg")
    window_change = _hk_float(row, "stage_window_change_pct", "window_change_pct")
    volume_ratio = _hk_float(row, "volume_ratio")
    turnover_yi = _hk_money_yi(row)
    turnover_rate = _hk_float(row, "turnover_rate", "futu_turnover_rate")
    platform_cap_yi = _hk_float(row, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
    offer_float_yi = _hk_float(row, "offer_float_market_cap_hkd_yi")
    score = 42
    reasons: list[str] = []
    risks: list[str] = []
    if "LIVE_HKCONNECT_GAINER" in lanes:
        score += 16
        reasons.append("港股通实时强势")
    if "PREOPEN_AUCTION_CONTINUATION" in lanes:
        score += 4
        reasons.append("09:20二筛命中")
    if continuation_pass:
        score += 8
        reasons.append("09:20二筛后续阶段承接确认")
    if platform_cap_yi is not None:
        if platform_cap_yi <= cap_limit_yi:
            score += 14
            reasons.append(f"平台流通市值{platform_cap_yi:.2f}亿港元<=100亿")
        elif continuation_pass:
            score += 4
            reasons.append(f"平台流通市值{platform_cap_yi:.2f}亿港元>100亿但<=150亿，且二筛延续确认")
        else:
            score -= 12
            risks.append(f"平台流通市值{platform_cap_yi:.2f}亿港元>100亿，降为强势主题观察")
            if "STRENGTH_THEME_WATCH" not in lanes:
                lanes.append("STRENGTH_THEME_WATCH")
    if offer_float_yi is not None:
        if "LOW_FLOAT_FILTER" not in lanes:
            lanes.append("LOW_FLOAT_FILTER")
        if offer_float_yi <= 20:
            score += 8
            reasons.append(f"非AH实际流通估算{offer_float_yi:.2f}亿港元")
        elif offer_float_yi <= 50:
            score += 4
            reasons.append(f"非AH中低实际流通估算{offer_float_yi:.2f}亿港元")
    elif "LOW_FLOAT_FILTER" in lanes:
        score += 4
        reasons.append("非AH低流通名单命中")
    if pct is not None:
        if pct >= 15:
            score += 22
            reasons.append(f"涨幅{pct:.2f}%")
            risks.append("盘中涨幅较大，不能追高，必须等回踩承接")
        elif pct >= 10:
            score += 18
            reasons.append(f"涨幅{pct:.2f}%")
        elif pct >= 5:
            score += 12
            reasons.append(f"涨幅{pct:.2f}%")
        elif pct > 0:
            score += 5
            reasons.append(f"红盘{pct:.2f}%")
        elif pct <= -5:
            score -= 10
            risks.append(f"当日下跌{pct:.2f}%")
    if volume_ratio is not None:
        if volume_ratio >= 3:
            score += 12
            reasons.append(f"量比{volume_ratio:.2f}")
        elif volume_ratio >= 1.5:
            score += 8
            reasons.append(f"量比{volume_ratio:.2f}")
        elif volume_ratio >= 1:
            score += 4
            reasons.append(f"量比{volume_ratio:.2f}")
        else:
            score -= 6
            risks.append("量比不足")
    if turnover_yi is not None:
        if turnover_yi >= 1:
            score += 7
            reasons.append(f"成交额{turnover_yi:.2f}亿港元")
        elif turnover_yi >= 0.2:
            score += 3
            reasons.append(f"成交额{turnover_yi:.2f}亿港元")
    if turnover_rate is not None:
        if turnover_rate >= 20:
            score += 10
            reasons.append(f"换手{turnover_rate:.2f}%")
        elif turnover_rate >= 8:
            score += 7
            reasons.append(f"换手{turnover_rate:.2f}%")
        elif turnover_rate >= 3:
            score += 4
            reasons.append(f"换手{turnover_rate:.2f}%")
    if "OLD_DEMON_MEMORY" in lanes:
        score += 5
        reasons.append("老妖记忆命中")
    if "NEW_HKCONNECT_BATCH" in lanes:
        score += 3
        reasons.append("新调入名单命中")
    if len(lanes) >= 3:
        score += 4
        reasons.append("多路共振")
    if "STRENGTH_THEME_WATCH" in lanes and not continuation_pass:
        score = min(score, 74)
    if stage in {"STAGE_1300_1315", "STAGE_1445_1500", "STAGE_1545_1555"} and pct is not None and pct >= 5:
        score += 4
        reasons.append("午后/尾盘仍保持强度")
    if pct is not None and pct < 3:
        score = min(score, 78)
        risks.append("涨幅不足3%，只能观察承接，不能排在妖股主榜前列")
    elif pct is not None and pct < 5:
        score = min(score, 88)
        risks.append("涨幅不足5%，需二次放量才可升级")
    if continuation_pass and window_change is not None:
        if window_change >= 3:
            score += 6
            reasons.append(f"阶段涨幅{window_change:.2f}%且守住09:20参考价")
        elif window_change < 0:
            score -= 8
            risks.append("09:20二筛后阶段转弱")
    if "OPENING_INITIAL_SCREEN" in lanes:
        status = "OPENING_INITIAL_SCREEN_RESEARCH_ONLY" if score >= 45 else "WATCH_ONLY"
    elif "PREOPEN_AUCTION_CONTINUATION" in lanes and score >= 72:
        status = "WAIT_FOR_TRIGGER"
    elif "STRENGTH_THEME_WATCH" in lanes:
        status = "WATCH_ONLY"
    elif score >= 84:
        status = "WAIT_FOR_TRIGGER"
    elif score >= 62:
        status = "WATCH_ONLY"
    else:
        status = "NO_TRADE"
    return {
        "score": int(_clamp(score)),
        "lane_evidence": lanes,
        "reasons": reasons,
        "risks": risks,
        "trade_status": status,
        "explanation": "；".join(reasons[:6]) if reasons else "四路融合证据不足",
        "continuation_pass": continuation_pass,
    }


def hk_legacy_stage_sort_key(row: Mapping[str, Any]) -> tuple[int, int, float, float, float]:
    """Port the Windows V3 HK non-09:25 ordering tuple verbatim.

    ``hk_demon_service`` sorts the already-scored rows in descending tuple
    order.  The contract gate is deliberately evaluated before any later
    WATCH_ONLY presentation normalization.
    """
    bucket = str(row.get("candidate_bucket") or "")
    bucket_weight = {
        "SMALLCAP_DEMON_MAIN": 2,
        "FOUR_LANE_OBSERVATION": 1,
    }.get(bucket, 0)
    contract = str(row.get("trade_status_contract") or row.get("trade_status") or "")
    no_trade_gate = 0 if contract == "NO_TRADE" else 1
    stage_score_value = _hk_float(row, "stage_score", "score")
    pct_chg_value = _hk_float(row, "pct_chg")
    volume_ratio_value = _hk_float(row, "volume_ratio")
    stage_score = 0.0 if stage_score_value is None else stage_score_value
    # Old V3 uses ``item.get("pct_chg") or -999`` and
    # ``item.get("volume_ratio") or 0`` verbatim: an explicit numeric zero is
    # therefore treated like a missing/empty value, while negative and positive
    # observations retain their values.
    pct_chg = pct_chg_value or -999.0
    volume_ratio = volume_ratio_value or 0.0
    return bucket_weight, no_trade_gate, stage_score, pct_chg, volume_ratio


def merge_hk_four_lane_candidates(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge same-code V3 lane rows while preserving lane/source precedence.

    The Windows service builds one row from several lane inputs.  The first
    non-empty live quote is authoritative for names and quote fields; later
    static-lane rows only contribute their lane labels and missing metadata.
    """
    merged: dict[str, dict[str, Any]] = {}
    for raw in rows:
        code = str(_a_row_value(raw, "code", "ts_code") or "").strip()
        if not code:
            continue
        incoming = dict(raw)
        current = merged.get(code)
        if current is None:
            incoming["candidate_lanes"] = list(dict.fromkeys(str(item) for item in (incoming.get("candidate_lanes") or ())))
            merged[code] = incoming
            continue
        current["candidate_lanes"] = list(
            dict.fromkeys(
                [
                    *(str(item) for item in (current.get("candidate_lanes") or ())),
                    *(str(item) for item in (incoming.get("candidate_lanes") or ())),
                ]
            )
        )
        for key, value in incoming.items():
            if key == "candidate_lanes":
                continue
            if value not in (None, "", (), [], {}):
                if current.get(key) in (None, "", (), [], {}):
                    current[key] = value
                elif key in {"candidate_bucket", "trade_status_contract"}:
                    current[key] = value
    return list(merged.values())


def hk_0925_pool_rank(row: Mapping[str, Any]) -> int:
    """Preserve the old pool/preopen/HK rank authority for 09:25."""
    return _live_rank_int(row.get("pool_rank") or row.get("preopen_rank") or row.get("hk_stage_rank"))


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
) -> dict[str, Any]:
    _validate_date(trade_date)
    _validate_market(stage_id, "HK_CONNECT")
    selected: list[dict[str, Any]] = []
    for source in rows:
        code = str(_a_row_value(source, "code", "ts_code") or "").strip()
        if not code:
            raise SelectionError("HK selection row code is required")
        scored = hk_four_lane_score(source, stage_id, cap_limit_yi)
        raw_contract = str(source.get("trade_status_contract") or scored["trade_status"])
        raw_bucket = str(source.get("candidate_bucket") or "")
        raw_stage_score = _hk_float(source, "stage_score")
        raw_pct = _hk_float(source, "pct_chg")
        raw_volume = _hk_float(source, "volume_ratio")
        scored_lanes = list(scored["lane_evidence"])
        if raw_bucket:
            candidate_bucket = raw_bucket
        else:
            cap_value = _hk_float(source, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
            is_smallcap = cap_value is not None and cap_value <= cap_limit_yi
            if (is_smallcap or scored["continuation_pass"]) and "LIVE_HKCONNECT_GAINER" in scored_lanes:
                candidate_bucket = "SMALLCAP_DEMON_MAIN"
            elif "STRENGTH_THEME_WATCH" in scored_lanes:
                candidate_bucket = "STRENGTH_THEME_WATCH"
            else:
                candidate_bucket = "FOUR_LANE_OBSERVATION"
        lane_evidence = list(scored["lane_evidence"])
        lane_evidence.extend(
            item
            for item in (
                f"candidate_bucket={candidate_bucket}" if candidate_bucket else "",
                f"trade_status_contract={raw_contract}" if raw_contract else "",
            )
            if item and item not in lane_evidence
        )
        card = _stage_card_evidence(
            source,
            code=code,
            open_price=source.get("open_price"),
            last_price=source.get("last_price"),
            high_price=source.get("high_price"),
            low_price=source.get("low_price"),
            source_last_bar_time=source.get("update_time"),
        )
        selected.append(
            {
                "code": code,
                "score": scored["score"],
                "status": scored["trade_status"],
                "formal_eligible": False,
                **card,
                "source_mode": "HK_CONNECT_FOUR_LANE",
                "candidate_lanes": scored_lanes,
                "lane_evidence": lane_evidence,
                "action_level": "NO_BUY",
                "trade_status": scored["trade_status"],
                "candidate_bucket": candidate_bucket,
                "trade_status_contract": raw_contract,
                "stage_score": scored["score"] if raw_stage_score is None else raw_stage_score,
                "pct_chg": _hk_float(source, "pct_chg") if raw_pct is not None else None,
                "volume_ratio": _hk_float(source, "volume_ratio") if raw_volume is not None else None,
                "d1_status": source.get("d1_status", ""),
                "d1_model_id": source.get("d1_model_id", ""),
                "d1_prob_active": source.get("d1_prob_active", ""),
                "d1_rank": source.get("d1_rank", ""),
                "d1_score": source.get("d1_score", ""),
                "d1_source_evidence": list(source.get("d1_source_evidence") or ()),
                "second_filter_rank": source.get("second_filter_rank", ""),
                "second_filter_score": source.get("second_filter_score", ""),
                "second_filter_status": source.get("second_filter_status", ""),
                "second_filter_action_level": source.get("second_filter_action_level", ""),
            }
        )
    if stage_id == "STAGE_0925":
        selected.sort(key=hk_0925_pool_rank)
    else:
        selected.sort(key=hk_legacy_stage_sort_key, reverse=True)
    top10 = _top10_contract(source_evidence)
    legacy = _legacy_backfill(source_evidence) and not top10
    selected = _cap_recommendations(selected, preserve_legacy=legacy)
    algorithm_sha = (
        ALGORITHM_SHA256 if top10 else LEGACY_ALGORITHM_SHA256
    )
    return _selection_envelope(
        trade_date=trade_date,
        stage_id=stage_id,
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status,
        input_rows=len(rows),
        rows=selected,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(*source_evidence, f"algorithm_sha256={algorithm_sha}"),
        algorithm_sha256=algorithm_sha,
    )


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
    _validate_date(trade_date)
    normalized: list[dict[str, Any]] = []
    signal_dates: list[str] = []
    for index, source in enumerate(rows, start=1):
        # ``signal_date`` is the prior trading session for the 09:20 auction;
        # only target_date binds this stage's trade-date identity.
        for date_key in ("target_date",):
            value = str(source.get(date_key) or "").replace("-", "")
            if value and value != trade_date:
                raise SelectionError(f"HK 0925 {date_key} drift")
        signal_date = str(source.get("signal_date") or "").replace("-", "")
        if signal_date:
            _validate_date(signal_date)
            if signal_date == trade_date:
                raise SelectionError("HK 0925 signal_date must be prior to trade_date")
            if signal_date not in signal_dates:
                signal_dates.append(signal_date)
        code = str(_a_row_value(source, "code", "ts_code") or "").strip()
        if not code:
            raise SelectionError("HK 0925 row code is required")
        raw_rank = _optional_number(source.get("rank"))
        rank = int(raw_rank) if raw_rank is not None else index
        card = _stage_card_evidence(
            source,
            code=code,
            open_price=source.get("open_price"),
            last_price=source.get("last_price"),
            high_price=source.get("high_price"),
            low_price=source.get("low_price"),
            source_last_bar_time=source.get("update_time"),
        )
        normalized.append(
            {
                "code": code,
                "score": round(_number(source.get("auction_score")), 6),
                "rank": rank,
                "status": str(source.get("second_filter_status") or "WATCH_ONLY"),
                "formal_eligible": False,
                "support": _hk_float(source, "reference_price_hkd", "last_price"),
                "pressure": _hk_float(source, "ask_price"),
                "invalidation": _hk_float(source, "strict_failure_price_hkd", "bid_price"),
                "source_mode": "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925",
                "lane_evidence": [
                    str(source.get("preselect_lane") or ""),
                    str(source.get("second_filter_status") or ""),
                ],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                **card,
            }
        )
    # Do not sort: source rank/order is itself the oracle and may be non-lexical.
    top10 = _top10_contract(source_evidence)
    legacy = _legacy_backfill(source_evidence) and not top10
    normalized = _cap_recommendations(normalized, preserve_legacy=legacy)
    algorithm_sha = (
        ALGORITHM_SHA256 if top10 else LEGACY_ALGORITHM_SHA256
    )
    status = "READY" if normalized and source_status not in {"CANNOT_CONFIRM", "READ_FAILED"} else ("READY_EMPTY" if not normalized else "PARTIAL_WITH_ROWS")
    result = _selection_envelope(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=status,
        input_rows=len(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(
            *source_evidence,
            "route=hk_connect_0915_0920_auction_second_filter",
            *(f"signal_date={value}" for value in signal_dates),
            f"algorithm_sha256={algorithm_sha}",
        ),
        algorithm_sha256=algorithm_sha,
    )
    # The source status is an envelope-level fact; keep malformed/failed source
    # evidence fail-closed instead of silently replacing it with READY.
    if source_status in {"CANNOT_CONFIRM", "READ_FAILED"} and normalized:
        result["source_status"] = "CANNOT_CONFIRM"
        result["selection_status"] = "PARTIAL_WITH_ROWS"
    return result


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
    _validate_date(trade_date)
    _validate_market("STAGE_0925", "HK_CONNECT")
    indexed: list[tuple[int, int, Mapping[str, Any]]] = []
    for index, source in enumerate(rows, start=1):
        row_date = str(
            _a_row_value(source, "target_date", "trade_date", "date8") or ""
        ).replace("-", "")
        if row_date and row_date != trade_date:
            raise SelectionError("HK 0925 D1 reference target_date drift")
        code = str(_a_row_value(source, "code", "ts_code", "stock_code") or "").strip()
        if not code:
            raise SelectionError("HK 0925 D1 reference row code is required")
        raw_rank = _optional_number(
            _a_row_value(source, "pool_rank", "d1_rank", "rank")
        )
        indexed.append((int(raw_rank) if raw_rank is not None else index, index, source))

    indexed.sort(key=lambda item: (item[0], item[1]))
    normalized: list[dict[str, Any]] = []
    for output_rank, (rank, _index, source) in enumerate(
        indexed[:STAGE_RECOMMENDATION_LIMIT], start=1
    ):
        code = str(_a_row_value(source, "code", "ts_code", "stock_code") or "").strip()
        name = _a_row_value(source, "name", "stock_name", "security_name", "display_name")
        score = _optional_number(
            _a_row_value(source, "pool_score", "score_prob_active", "d1_score", "score")
        )
        lane_evidence = list(
            dict.fromkeys(
                (
                    "D1_PRESELECT_REFERENCE",
                    "WAITING_0920_SECOND_FILTER",
                    "exact_date=true",
                    "post_open_snapshot_used=false",
                    "future_snapshot_used=false",
                    *(str(item) for item in (source.get("source_evidence") or ()) if str(item)),
                )
            )
        )
        normalized.append(
            {
                "code": code,
                "name": name,
                "stock_name": name,
                "score": 0.0 if score is None else round(score, 6),
                "rank": output_rank,
                "status": "WAITING_0920_SECOND_FILTER",
                "formal_eligible": False,
                "support": None,
                "pressure": None,
                "invalidation": None,
                "source_mode": "HK_CONNECT_D1_PRESELECT_REFERENCE",
                "lane_evidence": lane_evidence,
                "candidate_lanes": ["D1_PRESELECT_REFERENCE"],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "d1_status": source.get("d1_status", "STRICT_0_2_READY"),
                "d1_model_id": source.get(
                    "d1_model_id",
                    source.get("model_id", source.get("model", "prob_active")),
                ),
                "d1_prob_active": source.get(
                    "d1_prob_active", source.get("prob_active", source.get("score_prob_active", ""))
                ),
                "d1_rank": source.get("d1_rank", source.get("pool_rank", rank)),
                "d1_score": source.get("d1_score", source.get("pool_score", score)),
                "d1_source_evidence": list(source.get("d1_source_evidence") or ()),
                "second_filter_status": "WAITING_0920_SECOND_FILTER",
                "second_filter_rank": None,
                "second_filter_score": None,
                "current_change_pct": None,
                "open_price": None,
                "last_price": None,
                "high_price": None,
                "low_price": None,
                "source_last_bar_time": None,
                "next_validation_time": "09:20:05",
                "support_primary_price": None,
                "pressure_price": None,
                "invalidation_price": None,
            }
        )
    evidence = tuple(
        dict.fromkeys(
            (
                *source_evidence,
                "route=old_v3_opening_second_screen_d1_fallback",
                "D1_PRESELECT_REFERENCE",
                "WAITING_0920_SECOND_FILTER",
                "exact_date=true",
                "post_open_snapshot_used=false",
                "future_snapshot_used=false",
                "selection_contract=V3_TOP10_RECOMMENDATION",
            )
        )
    )
    cannot = tuple(
        dict.fromkeys(
            (
                *cannot_confirm,
                "WAITING_0920_SECOND_FILTER",
                "HK_0920_EXACT_SECOND_FILTER_UNAVAILABLE",
            )
        )
    )
    algorithm_sha = ALGORITHM_SHA256
    result = _selection_envelope(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status="CANNOT_CONFIRM" if source_status in {"CANNOT_CONFIRM", "READ_FAILED"} else source_status,
        input_rows=len(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot,
        source_evidence=(*evidence, f"algorithm_sha256={algorithm_sha}"),
        algorithm_sha256=algorithm_sha,
    )
    # ``_selection_envelope`` normally marks rows under a failed source as
    # PARTIAL_WITH_ROWS.  This lane is intentionally stronger: rows are only
    # a D-1 reference and the stage remains unconfirmed at every level.
    if normalized:
        result["selection_status"] = "CANNOT_CONFIRM"
    return result


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
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                field: json.dumps(row.get(field), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if field == "lane_evidence"
                else ("" if row.get(field) is None else row.get(field))
                for field in fields
            }
        )
    return output


def _decode_artifact_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        if fields is None:
            raw_fields = tuple(row)
            if set(raw_fields) == set(SELECTION_ARTIFACT_FIELDS_V1):
                fields = SELECTION_ARTIFACT_FIELDS_V1
            elif set(raw_fields) == set(SELECTION_ARTIFACT_FIELDS_V2):
                fields = SELECTION_ARTIFACT_FIELDS_V2
            else:
                raise SelectionError("selection artifact fields mismatch")
        if set(row) != set(fields):
            raise SelectionError("selection artifact fields mismatch")
        if row.get("lane_evidence"):
            try:
                row["lane_evidence"] = json.loads(row["lane_evidence"])
            except ValueError as error:
                raise SelectionError("selection lane evidence is invalid") from error
        else:
            row["lane_evidence"] = []
        for field in ("rank",):
            if field in row and row[field] != "":
                row[field] = int(row[field])
        for field in ("score", "support", "pressure", "invalidation", "current_change_pct", "open_price", "last_price", "high_price", "low_price", "support_primary_price", "pressure_price", "invalidation_price"):
            if field in row and row[field] != "":
                row[field] = float(row[field])
            elif field in row:
                row[field] = None
        row["formal_eligible"] = str(row.get("formal_eligible", "")).lower() in {"true", "1", "yes"}
        for field in SELECTION_ARTIFACT_FIELDS_V2:
            if field not in row:
                row[field] = None
        row["lane_evidence"] = list(row.get("lane_evidence") or ())
        output.append(row)
    return output


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
        role = self._role(stage_id, market)
        if not _ROLE_RE.fullmatch(run_id):
            raise SelectionError("selection run_id is unsafe")
        prefix = f"selection_runs/{trade_date}/{role}/{run_id}"
        run_dir = _safe_relative(self.root, prefix)
        artifact_path = _safe_relative(self.root, f"{prefix}/artifact.csv")
        manifest_path = _safe_relative(self.root, f"{prefix}/manifest.json")
        receipt_path = _safe_relative(self.root, f"{prefix}/receipt.json")
        if not run_dir.is_dir() or not all(path.is_file() for path in (artifact_path, manifest_path, receipt_path)):
            raise SelectionError("selection run trio incomplete")
        manifest = _read_json(manifest_path)
        receipt = _read_json(receipt_path)
        if manifest.get("schema_version") != SELECTION_MANIFEST_SCHEMA_VERSION or receipt.get("schema_version") != SELECTION_RECEIPT_SCHEMA_VERSION:
            raise SelectionError("selection manifest/receipt schema mismatch")
        for payload, label in ((manifest, "manifest"), (receipt, "receipt")):
            if payload.get("owner") != "stage_center" or payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id or payload.get("market") != market or payload.get("run_id") != run_id:
                raise SelectionError(f"selection {label} identity mismatch")
            if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
                raise SelectionError(f"selection {label} safety flag must be false")
        expected_artifact = f"{prefix}/artifact.csv"
        if manifest.get("artifact_relative") != expected_artifact or receipt.get("artifact_relative") != expected_artifact:
            raise SelectionError("selection artifact path mismatch")
        actual_artifact_sha = _sha_file(artifact_path)
        if manifest.get("artifact_sha256") != actual_artifact_sha or receipt.get("artifact_sha256") != actual_artifact_sha:
            raise SelectionError("selection artifact SHA mismatch")
        with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            artifact_fields = tuple(reader.fieldnames or ())
            if artifact_fields not in (SELECTION_ARTIFACT_FIELDS_V1, SELECTION_ARTIFACT_FIELDS_V2):
                raise SelectionError("selection artifact fields mismatch")
            artifact_rows = _decode_artifact_rows(list(reader), fields=artifact_fields)
        envelope = manifest.get("selection_envelope")
        if not isinstance(envelope, Mapping):
            raise SelectionError("selection envelope missing")
        envelope_schema = str(envelope.get("schema_version") or "")
        if envelope_schema not in SELECTION_SCHEMA_VERSIONS:
            raise SelectionError("selection envelope schema mismatch")
        expected_projection_fields = _artifact_fields_for_schema(envelope_schema)
        if envelope_schema == SELECTION_SCHEMA_VERSION_V1 and artifact_fields != expected_projection_fields:
            raise SelectionError("selection artifact/schema version mismatch")
        if envelope_schema == SELECTION_SCHEMA_VERSION and artifact_fields not in (
            expected_projection_fields,
            SELECTION_ARTIFACT_FIELDS_V2,
        ):
            raise SelectionError("selection artifact/schema version mismatch")
        expected_rows = _decode_artifact_rows(
            _artifact_rows(list(envelope.get("rows") or []), fields=artifact_fields),
            fields=artifact_fields,
        )
        if expected_rows != artifact_rows:
            raise SelectionError("selection artifact rows mismatch")
        if manifest.get("row_count") != len(artifact_rows) or receipt.get("row_count") != len(artifact_rows):
            raise SelectionError("selection row_count mismatch")
        if receipt.get("manifest_sha256") != _canonical_sha(manifest):
            raise SelectionError("selection manifest SHA mismatch")
        manifest_algorithm = manifest.get("algorithm_sha256")
        receipt_algorithm = receipt.get("algorithm_sha256")
        if manifest_algorithm not in ALGORITHM_SHA_ALLOWLIST or receipt_algorithm != manifest_algorithm:
            raise SelectionError("selection algorithm SHA mismatch")
        if envelope.get("algorithm_sha256") != manifest_algorithm:
            raise SelectionError("selection envelope algorithm SHA mismatch")
        if manifest.get("raw_artifact_sha256") != envelope.get("raw_artifact_sha256") or receipt.get("raw_artifact_sha256") != envelope.get("raw_artifact_sha256"):
            raise SelectionError("selection raw artifact SHA mismatch")
        expected_artifact_id, expected_run_id = _selection_identity_ids(
            trade_date,
            stage_id,
            market,
            str(envelope.get("raw_artifact_sha256") or ""),
            manifest_algorithm,
            list(envelope.get("rows") or []),
        )
        if envelope.get("artifact_id") != expected_artifact_id or envelope.get("run_id") != expected_run_id or run_id != expected_run_id:
            raise SelectionError("selection identity mismatch")
        if envelope.get("selection_status") not in SELECTION_STATUSES:
            raise SelectionError("selection status mismatch")
        return {
            "envelope": dict(envelope),
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "artifact_relative": expected_artifact,
            "artifact_sha256": actual_artifact_sha,
            "manifest_sha256": _canonical_sha(manifest),
            "receipt_sha256": _canonical_sha(receipt),
            "idempotency_key": receipt.get("idempotency_key"),
        }

    def publish(self, envelope: Mapping[str, Any], *, market: str) -> dict[str, Any]:
        data = dict(envelope)
        required = {"trade_date", "stage_id", "raw_artifact_sha256", "algorithm_sha256", "rows", "selection_status"}
        if not required.issubset(data):
            raise SelectionError("selection envelope fields missing")
        trade_date = _validate_date(str(data["trade_date"]))
        stage_id = str(data["stage_id"])
        _validate_market(stage_id, market)
        if data.get("market") != market:
            raise SelectionError("selection envelope market mismatch")
        _validate_sha(str(data["raw_artifact_sha256"]), "raw_artifact_sha256")
        if data.get("algorithm_id") != SELECTION_ALGORITHM_ID:
            raise SelectionError("selection algorithm binding mismatch")
        if any(data.get(flag) is not False for flag in SAFETY_FLAGS):
            raise SelectionError("selection safety flag must be false")
        rows = list(data.get("rows") or [])
        envelope_schema = str(data.get("schema_version") or SELECTION_SCHEMA_VERSION)
        if envelope_schema not in SELECTION_SCHEMA_VERSIONS:
            raise SelectionError("selection envelope schema mismatch")
        # New envelopes are explicitly v2, but ``artifact.csv`` stays a
        # fixed v1 projection for the old V3 verifier.  Full card evidence is
        # bound into the manifest/receipt envelope and selection identity.
        artifact_fields = SELECTION_ARTIFACT_FIELDS_V1
        artifact_rows = _artifact_rows(rows, fields=artifact_fields)
        algorithm_sha = str(data["algorithm_sha256"])
        if algorithm_sha not in ALGORITHM_SHA_ALLOWLIST:
            raise SelectionError("selection algorithm binding mismatch")
        if algorithm_sha in {A_SHARE_LIVE_ALGORITHM_SHA256, LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256} and market != "A_SHARE":
            raise SelectionError("live algorithm is restricted to A_SHARE")
        if algorithm_sha in {A_SHARE_LIVE_ALGORITHM_SHA256, LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256} and not any(
            "formula=windows_v3_live_stage_quality_score" in str(item)
            for item in data.get("source_evidence") or ()
        ):
            raise SelectionError("live algorithm evidence missing")
        identity_payload = {
            "identity": self._key(trade_date, stage_id, market),
            "raw_artifact_sha256": data["raw_artifact_sha256"],
            "algorithm_sha256": algorithm_sha,
            "rows": rows,
        }
        authority_hashes = tuple(
            str(item)
            for item in data.get("source_evidence") or ()
            if any(
                str(item).startswith(prefix)
                for prefix in (
                    "a_d1_premarket_pool_sha256=",
                    "a_research_panel_receipt_sha256=",
                    "a_research_panel_selector_sha256=",
                )
            )
        )
        if authority_hashes:
            identity_payload["authority_source_hashes"] = list(dict.fromkeys(authority_hashes))
        input_sha = _canonical_sha(identity_payload)
        role = self._role(stage_id, market)
        expected_artifact_id, expected_run_id = _selection_identity_ids(
            trade_date,
            stage_id,
            market,
            str(data["raw_artifact_sha256"]),
            algorithm_sha,
            rows,
        )
        if data.get("run_id") not in (None, expected_run_id) or data.get("artifact_id") not in (None, expected_artifact_id):
            raise SelectionError("selection identity mismatch")
        run_id = expected_run_id
        artifact_id = expected_artifact_id
        data["run_id"] = run_id
        data["artifact_id"] = artifact_id
        idem_key = _canonical_sha({"identity": self._key(trade_date, stage_id, market), "raw_artifact_sha256": data["raw_artifact_sha256"], "algorithm_sha256": algorithm_sha, "input_sha256": input_sha})
        data["source_evidence"] = list(data.get("source_evidence") or [])
        data["cannot_confirm"] = list(data.get("cannot_confirm") or [])
        prefix = f"selection_runs/{trade_date}/{role}/{run_id}"
        artifact_relative = f"{prefix}/artifact.csv"
        manifest_relative = f"{prefix}/manifest.json"
        receipt_relative = f"{prefix}/receipt.json"
        with self._lock():
            latest = self._latest()
            key = self._key(trade_date, stage_id, market)
            existing = latest["entries"].get(key)
            if isinstance(existing, Mapping):
                if existing.get("idempotency_key") != idem_key:
                    raise SelectionError(f"selection slot conflict: {key}")
                verified = self._verify_run(trade_date, stage_id, market, str(existing.get("run_id")))
                if verified["envelope"] != data:
                    raise SelectionError("selection idempotency payload mismatch")
                return dict(data)
            run_dir = _safe_relative(self.root, prefix)
            if run_dir.exists():
                raise SelectionError("immutable selection run path already exists without latest pointer")
            run_dir.mkdir(parents=True, exist_ok=False)
            artifact_path = _safe_relative(self.root, artifact_relative)
            _atomic_write_csv(artifact_path, artifact_rows, fields=artifact_fields)
            artifact_sha = _sha_file(artifact_path)
            manifest = {
                "schema_version": SELECTION_MANIFEST_SCHEMA_VERSION,
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "artifact_relative": artifact_relative,
                "artifact_sha256": artifact_sha,
                "row_count": len(rows),
                "selection_status": data["selection_status"],
                "raw_artifact_sha256": data["raw_artifact_sha256"],
                "algorithm_id": SELECTION_ALGORITHM_ID,
                "algorithm_sha256": algorithm_sha,
                "selection_envelope": data,
                "calendar": calendar_provenance(),
                **SAFETY_FLAGS,
            }
            receipt = {
                "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "artifact_relative": artifact_relative,
                "artifact_sha256": artifact_sha,
                "manifest_sha256": _canonical_sha(manifest),
                "row_count": len(rows),
                "selection_status": data["selection_status"],
                "raw_artifact_sha256": data["raw_artifact_sha256"],
                "algorithm_id": SELECTION_ALGORITHM_ID,
                "algorithm_sha256": algorithm_sha,
                "idempotency_key": idem_key,
                "calendar": calendar_provenance(),
                **SAFETY_FLAGS,
            }
            _atomic_write_json(_safe_relative(self.root, manifest_relative), manifest)
            _atomic_write_json(_safe_relative(self.root, receipt_relative), receipt)
            verified = self._verify_run(trade_date, stage_id, market, run_id)
            entries = dict(latest.get("entries", {}))
            entries[key] = {
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "artifact_relative": artifact_relative,
                "artifact_sha256": artifact_sha,
                "manifest_sha256": verified["manifest_sha256"],
                "receipt_sha256": verified["receipt_sha256"],
                "idempotency_key": idem_key,
                **SAFETY_FLAGS,
            }
            latest["entries"] = entries
            _atomic_write_json(self.latest_path, latest)
            return dict(data)

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


__all__ = [
    "ALGORITHM_MANIFEST",
    "ALGORITHM_SHA256",
    "TOP10_ALGORITHM_MANIFEST",
    "LEGACY_ALGORITHM_SHA256",
    "A_SHARE_LIVE_ALGORITHM_MANIFEST",
    "A_SHARE_LIVE_ALGORITHM_SHA256",
    "A_SHARE_LIVE_TOP10_ALGORITHM_MANIFEST",
    "LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256",
    "SELECTION_ARTIFACT_FIELDS_V1",
    "SELECTION_ARTIFACT_FIELDS_V2",
    "SELECTION_ARTIFACT_FIELDS",
    "SelectionError",
    "SelectionStore",
    "a_stage_label",
    "a_stage_score",
    "hk_four_lane_score",
    "merge_hk_four_lane_candidates",
    "live_stage_quality_score",
    "publish_selection",
    "read_verified_selection",
    "select_a_0925_auction",
    "select_a_live_stage",
    "select_a_stage",
    "select_hk_0925_second_filter",
    "select_hk_0925_d1_reference",
    "select_hk_four_lane",
    "stage_row_sort_key",
]
