"""Exact-date read-only review composition and one server-bound manual trigger."""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime
import importlib
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from contracts.stages import FROZEN_STAGE_IDS
from domains.a_share_review import build_a_share_review
from domains.close_review import close_review
from domains.daily_research_review import load_daily_research_review
from domains.review_envelope import review_envelope
from domains.stages import StageRunner
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.data_store import _sha256
from infrastructure.review_store import ReviewStore
from infrastructure.stage_store import StageStore

try:  # T183 adds the strict Review Core evidence layers.
    from domains.review_evidence_layers import (
        load_review_core_a_share_review,
        load_review_evidence_layers,
        review_core_a_share_bundle_required,
    )
except ImportError:  # Keep older source checkouts compatible until overlaid.
    _HAS_REVIEW_EVIDENCE_LAYERS = False

    def review_core_a_share_bundle_required(data_root: Path, trade_date: str) -> bool:
        return False

    def load_review_core_a_share_review(trade_date: str, data_root: Path) -> dict[str, Any]:
        raise ValueError("Review Core evidence layers are unavailable")

    def load_review_evidence_layers(
        data_root: Path, trade_date: str, a_review: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {}
else:
    _HAS_REVIEW_EVIDENCE_LAYERS = True

try:  # T183's bridge is optional in the older worktree checkout.
    from infrastructure.review_core_hk_review_source import (
        HK_CLOSE_REVIEW_V1,
        HK_REVIEW_CORE_UNAVAILABLE,
        load_hk_close_review,
    )
except ImportError:  # pragma: no cover - exercised by the legacy compatibility tests.
    _HAS_HK_REVIEW_CORE = False
    HK_CLOSE_REVIEW_V1 = "HK_CLOSE_REVIEW_V1"
    HK_REVIEW_CORE_UNAVAILABLE = "HK_REVIEW_CORE_UNAVAILABLE"

    def load_hk_close_review(trade_date: str, data_root: Path) -> dict[str, Any]:
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "role": HK_CLOSE_REVIEW_V1,
            "artifact": None,
            "run_id": "",
            "artifact_sha256": "",
            "manifest_sha256": "",
            "receipt_sha256": "",
            "paths": {},
            "cannot_confirm": [HK_REVIEW_CORE_UNAVAILABLE],
        }
else:
    _HAS_HK_REVIEW_CORE = True


_STATUS_MAP = {
    "READY": "MODEL_REVIEW_READY",
    "PARTIAL": "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
    "CANNOT_CONFIRM": "CANNOT_CONFIRM",
    "MODEL_REVIEW_READY": "MODEL_REVIEW_READY",
    "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE": "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
}
_SAFETY_FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}

# The historical prefix asset is an independently produced research surface.
# It is deliberately consumed through a runtime binding with fixed file
# digests; the review endpoint never searches for a ``latest`` directory or
# infers an asset from the daily panel's current pointer.
_HK_PREFIX_PANEL_SCHEMA = "v4.hk_prefix_research.panel_projection.v1"
_HK_PREFIX_ASSET_SCHEMA = "v4.hk_prefix_research.v2"
_HK_PREFIX_ASSET_ID = "ZGE_HISTORY_V4_20260914"
_HK_PREFIX_COMPARISON_STATUS = "NOT_SUPPORTED_TERMINAL_COVERAGE"
_HK_PREFIX_MAPPING_COMPARISON_STATUS = "TERMINAL_BINARY_DESCRIPTIVE_UNREGISTERED_CONTROL_THRESHOLD"
_HK_PREFIX_METRIC_CONTRACT = "v4.hk_prefix_research.terminal_metric.v1"
_HK_PREFIX_REQUIRED_COMPLETE_PAIRS = 18
_HK_PREFIX_EXPECTED_STATES = {
    "NO_ACTIVE_SETUP",
    "WARMUP",
    "BROKEN_PENDING",
    "RECLAIMED",
    "REPAIR_FAILED_TIMEOUT",
    "UNKNOWN",
    "RETEST_HELD_PROVISIONAL",
    "RETEST_HELD_HORIZON_COMPLETE",
}
_HK_PREFIX_INDEX_FIELDS = {
    "series_id",
    "prefix_file",
    "row_count",
    "input_sha256",
    "prefix_content_sha256",
    "review_status",
}
_HK_PREFIX_MAPPING_FIELDS = {
    "series_id",
    "pair_group_id",
    "group_index",
    "role",
    "code",
    "event_date",
    "event_type",
    "row_count",
    "source_observed_rows",
    "source_missing_rows",
    "terminal_state",
    "unknown_count",
    "indeterminate_count",
    "known_count",
    "qualifying_count",
    "terminal_unknown",
    "terminal_determinable",
    "terminal_lower",
    "terminal_upper",
    "terminal_indeterminate_reason",
    "terminal_qualifies",
    "occupancy_lower_rate",
    "occupancy_upper_rate",
    "unknown_reason_counts",
    "input_sha256",
    "prefix_content_sha256",
    "comparison_status",
}
_HK_PREFIX_WINDOW_FIELDS = {
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
}
_HK_PREFIX_FILE_KEYS = {
    "receipt",
    "source_manifest",
    "anonymous_index",
    "results_mapping",
    "frozen_binding",
    "matched_verdict",
    "field_isolation",
    "future_isolation",
    "past_positive_control",
    "replay_log",
    "source_window_replay_log",
    "pair_metrics",
    "summary_by_event_type",
    "terminal_contract_gate",
    "metrics_contract",
    "raw_window_reuse",
    "corrected_metric_contract_log",
}


def _panel_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _panel_read_bytes(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("evidence file exceeds bounded read size")
    return payload


def _panel_read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(_panel_read_bytes(path).decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("evidence JSON must be an object")
    return value


def _panel_safe_relative(root: Path, relative: Any) -> Path:
    value = Path(str(relative))
    if not value.parts or value.is_absolute() or ".." in value.parts:
        raise ValueError("unsafe evidence relative path")
    root_resolved = root.expanduser().resolve(strict=False)
    candidate = (root_resolved / value).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError("evidence path escapes asset root") from error
    return candidate


def _panel_safe_binding_path(value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("runtime binding path must be absolute")
    return path.resolve(strict=False)


def _panel_int(value: Any, *, field: str, minimum: int = 0) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid integer field: {field}") from error
    if result < minimum:
        raise ValueError(f"invalid non-negative field: {field}")
    return result


def _panel_float(value: Any, *, field: str) -> float:
    try:
        result = float(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid numeric field: {field}") from error
    if not math.isfinite(result):
        raise ValueError(f"invalid non-finite field: {field}")
    return result


def _panel_sha(value: Any, *, field: str) -> str:
    result = str(value or "")
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result.lower()):
        raise ValueError(f"invalid SHA-256 field: {field}")
    return result.lower()


def _panel_safety(value: Mapping[str, Any], *, label: str) -> None:
    research_only = value.get("RESEARCH_ONLY", value.get("research_only"))
    if research_only is not True:
        raise ValueError(f"{label} is not research-only")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if value.get(key) is not False:
            raise ValueError(f"{label} safety flag is not false: {key}")


def _panel_cannot_confirm(requested_date: str, reasons: list[str]) -> dict[str, Any]:
    from apps.api.v35_api._review_router_parts.panel_io import __panel_cannot_confirm_body as _v4_impl
    return _v4_impl(globals(), requested_date, reasons)


def _panel_log_status(path: Path, required: tuple[str, ...]) -> str:
    text = _panel_read_bytes(path, max_bytes=512 * 1024).decode("utf-8")
    return "PASS" if all(token in text for token in required) else "CANNOT_CONFIRM"


def _read_hk_prefix_research_asset(
    requested_date: str,
    *,
    root_value: Path | str | None = None,
    binding_value: Path | str | None = None,
) -> dict[str, Any]:
    """Read the fixed, anonymous historical prefix asset for the review UI.

    This is a bounded consumer projection.  It reads only the runtime binding,
    output receipt/manifest, anonymous windows and machine evidence; identity
    rows are used for aggregate state counts and are never returned to the
    browser.  Any missing or mismatched digest fails closed with a typed
    ``CANNOT_CONFIRM`` payload.
    """
    from apps.api.v35_api._review_router_parts.hk_prefix_asset import __read_hk_prefix_research_asset_body as _v4_impl
    return _v4_impl(globals(), requested_date, root_value=root_value, binding_value=binding_value)


def _unavailable_metric() -> dict[str, Any]:
    from apps.api.v35_api._review_router_parts.panel_io import __unavailable_metric_body as _v4_impl
    return _v4_impl(globals())


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _project_hk_review(trade_date: str, source: Mapping[str, Any]) -> dict[str, Any]:
    """Project a verified Review Core DTO without re-verifying its evidence."""
    from apps.api.v35_api._review_router_parts.hk_projection import __project_hk_review_body as _v4_impl
    return _v4_impl(globals(), trade_date, source)


def _hk_parent(trade_date: str, source: Mapping[str, Any]) -> dict[str, Any]:
    from apps.api.v35_api._review_router_parts.hk_projection import __hk_parent_body as _v4_impl
    return _v4_impl(globals(), trade_date, source)


def _native_hk_parent(trade_date: str, reference: Mapping[str, Any]) -> dict[str, Any]:
    """Project a strictly verified V3.5 native close-review artifact."""
    from apps.api.v35_api._review_router_parts.hk_projection import __native_hk_parent_body as _v4_impl
    return _v4_impl(globals(), trade_date, reference)


def _native_hk_invalid_parent(trade_date: str, error: Exception) -> dict[str, Any]:
    from apps.api.v35_api._review_router_parts.hk_projection import __native_hk_invalid_parent_body as _v4_impl
    return _v4_impl(globals(), trade_date, error)


def _native_hk_review(data_root: Path, trade_date: str) -> tuple[dict[str, Any] | None, bool]:
    """Return (parent, present) and never bridge around a present invalid artifact."""
    from apps.api.v35_api._review_router_parts.hk_projection import __native_hk_review_body as _v4_impl
    return _v4_impl(globals(), data_root, trade_date)


def _read_shared_stage_center_rows(
    trade_date: str, stage_id: str
) -> tuple[Mapping[str, Any], list[dict[str, Any]]] | None:
    """Read the optional shared selection consumer without a write path."""
    from apps.api.v35_api._review_router_parts.stage_rows import __read_shared_stage_center_rows_body as _v4_impl
    return _v4_impl(globals(), trade_date, stage_id)


def _is_safe_watch_only_row(raw: Mapping[str, Any]) -> bool:
    statuses = [
        raw.get(key)
        for key in ("recommendation_status", "trade_status")
        if key in raw and raw.get(key) not in (None, "")
    ]
    if not statuses or any(status != "WATCH_ONLY" for status in statuses):
        return False
    return "formal_eligible" not in raw or raw.get("formal_eligible") is False


def _row_matches_exact_date(raw: Mapping[str, Any], trade_date: str) -> bool:
    """Allow envelope-derived dates, but reject every explicit cross-date row."""
    return not any(
        raw.get(key) not in (None, "") and str(raw.get(key)) != trade_date
        for key in ("trade_date", "target_trade_date")
    )


def _read_exact_stage_review_rows(
    data_root: Path, trade_date: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read only published, exact-date A-share WATCH_ONLY stage rows.

    This is a consumer-side projection of the existing StageStore.  It never
    produces a stage, reads another date, or promotes a stage candidate into a
    formal review conclusion.
    """
    from apps.api.v35_api._review_router_parts.stage_rows import __read_exact_stage_review_rows_body as _v4_impl
    return _v4_impl(globals(), data_root, trade_date)


def _partial_stage_review(
    trade_date: str,
    stage_rows: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    from apps.api.v35_api._review_router_parts.stage_partial import __partial_stage_review_body as _v4_impl
    return _v4_impl(globals(), trade_date, stage_rows, source_refs)


class ManualReviewRequest(BaseModel):
    """Only the selected date crosses the browser boundary."""
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str = Field(pattern=r"^\d{8}$")

    @field_validator("date")
    @classmethod
    def real_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y%m%d")
        return value


def _manual_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _manual_generate(date: str, *, bindings_path, bindings_sha256, review_root,
                     transport=None, client_factory=None) -> dict[str, Any]:
    """One server-pinned request, existing assembly/graph/writer and task lock.

    A small date-keyed attempt receipt prevents a browser retry after a charged
    failure or interrupted request. No background job or scheduler is created.
    Operator reconciliation is required for failed/unknown attempts; the HTTP
    surface never exposes replace, paths, credentials or a reset operation.
    """
    from apps.api.v35_api._review_router_parts.manual_review import __manual_generate_body as _v4_impl
    return _v4_impl(globals(), date, bindings_path=bindings_path, bindings_sha256=bindings_sha256, review_root=review_root, transport=transport, client_factory=client_factory)


def create_review_router(
    data_root: Path,
    review_root: Path | str | None = None,
    *,
    generation_bindings_path: Path | str | None = None,
    generation_bindings_sha256: str | None = None,
    intraday_root: Path | str | None = None,
    historical_prefix_root: Path | str | None = None,
    historical_prefix_binding_path: Path | str | None = None,
    _generation_transport: Any = None,
    _generation_client_factory: Any = None,
) -> APIRouter:
    from apps.api.v35_api._review_router_parts.http_routes import _create_review_router_body as _v4_impl
    return _v4_impl(globals(), data_root, review_root, generation_bindings_path=generation_bindings_path, generation_bindings_sha256=generation_bindings_sha256, intraday_root=intraday_root, historical_prefix_root=historical_prefix_root, historical_prefix_binding_path=historical_prefix_binding_path, _generation_transport=_generation_transport, _generation_client_factory=_generation_client_factory)
