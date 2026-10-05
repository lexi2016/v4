"""Exact-date read-only review composition and one server-bound manual trigger."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import importlib
import hashlib
import json
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


def _unavailable_metric() -> dict[str, Any]:
    return {
        "evidence_status": "CANNOT_CONFIRM",
        "selected_count": None,
        "selected_codes": [],
        "hit_count": None,
        "hit_codes": [],
        "coverage": None,
        "precision": None,
        "coverage_pct": None,
        "precision_pct": None,
    }


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _project_hk_review(trade_date: str, source: Mapping[str, Any]) -> dict[str, Any]:
    """Project a verified Review Core DTO without re-verifying its evidence."""
    reasons = _strings(source.get("cannot_confirm"))
    source_date = str(source.get("trade_date") or "")
    source_role = str(source.get("role") or "")
    artifact = source.get("artifact")
    if source_date != trade_date:
        reasons.append(f"HK_REVIEW_CORE_DATE_MISMATCH:{source_date or 'missing'}:{trade_date}")
        artifact = None
    if source_role != HK_CLOSE_REVIEW_V1:
        reasons.append(f"HK_REVIEW_CORE_ROLE_MISMATCH:{source_role or 'missing'}")
        artifact = None

    artifact_map = artifact if isinstance(artifact, Mapping) else None
    artifact_status = str(
        (artifact_map or {}).get("status") or source.get("status") or "CANNOT_CONFIRM"
    )
    mapped_status = _STATUS_MAP.get(artifact_status, "CANNOT_CONFIRM")
    if artifact_map is None:
        mapped_status = "CANNOT_CONFIRM"
        reasons.append(HK_REVIEW_CORE_UNAVAILABLE)
    if mapped_status == "CANNOT_CONFIRM" and HK_REVIEW_CORE_UNAVAILABLE not in reasons:
        reasons.append(HK_REVIEW_CORE_UNAVAILABLE)
    reasons = list(dict.fromkeys(reasons))

    if artifact_map is None:
        models = {"0.2_prob_active": _unavailable_metric()}
        stage_union = _unavailable_metric()
        observed_stage_union: dict[str, Any] | None = None
        close_top20: list[Any] = []
        top20_attribution: list[Any] = []
        missing_stages: list[str] = []
        row_counts: dict[str, Any] = {}
    else:
        raw_models = artifact_map.get("models")
        models = deepcopy(dict(raw_models)) if isinstance(raw_models, Mapping) else {}
        models.setdefault("0.2_prob_active", _unavailable_metric())
        raw_stage_union = artifact_map.get("stage_union")
        if not isinstance(raw_stage_union, Mapping) and isinstance(artifact_map.get("kpi"), Mapping):
            raw_stage_union = artifact_map["kpi"].get("stage_union")
        stage_union = (
            deepcopy(dict(raw_stage_union))
            if isinstance(raw_stage_union, Mapping)
            else _unavailable_metric()
        )
        raw_observed_stage_union = artifact_map.get("observed_stage_union")
        observed_stage_union = (
            deepcopy(dict(raw_observed_stage_union))
            if isinstance(raw_observed_stage_union, Mapping)
            else None
        )
        close_top20 = (
            deepcopy(artifact_map.get("close_top20"))
            if isinstance(artifact_map.get("close_top20"), list)
            else []
        )
        top20_attribution = (
            deepcopy(artifact_map.get("top20_attribution"))
            if isinstance(artifact_map.get("top20_attribution"), list)
            else []
        )
        missing_stages = _strings(artifact_map.get("missing_stages"))
        if not missing_stages:
            missing_stages = _strings(artifact_map.get("missing_stage_roles"))
        row_counts = (
            deepcopy(dict(artifact_map.get("row_counts")))
            if isinstance(artifact_map.get("row_counts"), Mapping)
            else {}
        )
        reasons = list(dict.fromkeys(reasons + _strings(artifact_map.get("cannot_confirm"))))

    source_sha = str(source.get("artifact_sha256") or "")
    review = {
        "schema_version": str((artifact_map or {}).get("schema_version") or HK_CLOSE_REVIEW_V1),
        "artifact_role": str((artifact_map or {}).get("role") or source_role or HK_CLOSE_REVIEW_V1),
        "artifact_version": str((artifact_map or {}).get("version") or HK_CLOSE_REVIEW_V1),
        "trade_date": trade_date,
        "status": mapped_status,
        "artifact_status": artifact_status,
        "source_role": source_role or HK_CLOSE_REVIEW_V1,
        "source_run_id": str(source.get("run_id") or ""),
        "source_sha256": source_sha,
        "artifact_sha256": source_sha,
        "manifest_sha256": str(source.get("manifest_sha256") or ""),
        "receipt_sha256": str(source.get("receipt_sha256") or ""),
        "paths": deepcopy(dict(source.get("paths"))) if isinstance(source.get("paths"), Mapping) else {},
        "row_counts": row_counts,
        "models": models,
        "stage_union": stage_union,
        "observed_stage_union": observed_stage_union,
        "close_top20": close_top20,
        "top20_attribution": top20_attribution,
        "missing_stages": missing_stages,
        "cannot_confirm": reasons,
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        "reference_snapshot": False,
        **_SAFETY_FLAGS,
    }
    return review


def _hk_parent(trade_date: str, source: Mapping[str, Any]) -> dict[str, Any]:
    review = _project_hk_review(trade_date, source)
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": review["status"],
        "artifact_status": review["artifact_status"],
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": str(source.get("role") or HK_CLOSE_REVIEW_V1),
        "source_merge_role": "SOURCE_ONLY",
        "source_run_id": review["source_run_id"],
        "source_sha256": review["source_sha256"],
        "artifact_sha256": review["artifact_sha256"],
        "manifest_sha256": review["manifest_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "model_selection_review": review,
        **_SAFETY_FLAGS,
    }


def _native_hk_parent(trade_date: str, reference: Mapping[str, Any]) -> dict[str, Any]:
    """Project a strictly verified V3.5 native close-review artifact."""
    digest = _sha256(reference)
    reference_snapshot = bool(reference.get("reference_snapshot"))
    review = deepcopy(dict(reference))
    review.update(
        {
            "artifact_role": "V3_5_NATIVE_CLOSE_MODEL",
            "artifact_version": "v3_5.close_review.v1",
            "artifact_status": str(reference.get("status") or "CANNOT_CONFIRM"),
            "source_role": "V3_5_NATIVE_CLOSE_MODEL",
            "source_merge_role": "V35_NATIVE_REVIEW_STORE",
            "source_sha256": str(reference.get("close_source_sha256") or digest),
            "artifact_sha256": digest,
            "manifest_sha256": "",
            "receipt_sha256": "",
            "stage_selection_eligible": False,
            "reference_snapshot": reference_snapshot,
            **_SAFETY_FLAGS,
        }
    )
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": review.get("status", "CANNOT_CONFIRM"),
        "artifact_status": review["artifact_status"],
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": review["source_role"],
        "source_merge_role": review["source_merge_role"],
        "source_run_id": "",
        "source_sha256": review["source_sha256"],
        "artifact_sha256": review["artifact_sha256"],
        "manifest_sha256": review["manifest_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "model_selection_review": review,
        **_SAFETY_FLAGS,
    }


def _native_hk_invalid_parent(trade_date: str, error: Exception) -> dict[str, Any]:
    review = {
        "schema_version": "v3_5.close_review.v1",
        "trade_date": trade_date,
        "status": "CANNOT_CONFIRM",
        "artifact_status": "CANNOT_CONFIRM",
        "artifact_role": "V3_5_NATIVE_CLOSE_MODEL",
        "artifact_version": "v3_5.close_review.v1",
        "source_role": "V3_5_NATIVE_CLOSE_MODEL",
        "source_merge_role": "V35_NATIVE_REVIEW_STORE",
        "models": {"0.2_prob_active": _unavailable_metric()},
        "stages": {},
        "stage_union": _unavailable_metric(),
        "kpi": {},
        "row_counts": {},
        "close_top20": [],
        "model_rows": [],
        "stage_rows": [],
        "top20_attribution": [],
        "missing_stages": [],
        "cannot_confirm": [f"V35_NATIVE_CLOSE_REVIEW_INVALID:{type(error).__name__}: {error}"],
        "source_sha256": "",
        "artifact_sha256": "",
        "manifest_sha256": "",
        "receipt_sha256": "",
        "reference_snapshot": False,
        "stage_selection_eligible": False,
        **_SAFETY_FLAGS,
    }
    return {
        "market": "HK",
        "display_name": "港股通复盘",
        "trade_date": trade_date,
        "status": "CANNOT_CONFIRM",
        "artifact_status": "CANNOT_CONFIRM",
        "artifact_role": review["artifact_role"],
        "artifact_version": review["artifact_version"],
        "source_role": review["source_role"],
        "source_merge_role": review["source_merge_role"],
        "source_run_id": "",
        "source_sha256": "",
        "artifact_sha256": "",
        "manifest_sha256": "",
        "receipt_sha256": "",
        "model_selection_review": review,
        **_SAFETY_FLAGS,
    }


def _native_hk_review(data_root: Path, trade_date: str) -> tuple[dict[str, Any] | None, bool]:
    """Return (parent, present) and never bridge around a present invalid artifact."""
    store = ReviewStore(data_root)
    artifact_path = store.root / "close_reviews" / f"{trade_date}.json"
    if not artifact_path.is_file():
        return None, False
    try:
        reference = store.read_reference(trade_date)
    except (OSError, ValueError) as error:
        return _native_hk_invalid_parent(trade_date, error), True
    if reference is None:
        return _native_hk_invalid_parent(trade_date, ValueError("native artifact is absent")), True
    return _native_hk_parent(trade_date, reference), True


def _read_shared_stage_center_rows(
    trade_date: str, stage_id: str
) -> tuple[Mapping[str, Any], list[dict[str, Any]]] | None:
    """Read the optional shared selection consumer without a write path."""
    root_value = os.environ.get("V35_STAGE_CENTER_SELECTION_ROOT", "").strip()
    if not root_value:
        return None
    root = Path(root_value).expanduser()
    if not root.is_dir():
        return None
    try:
        consumer_module = importlib.import_module("stage_center.consumer")
        consumer_type = getattr(consumer_module, "StageSelectionConsumer")
        configured_names = os.environ.get("V35_PRESELECTION_SOURCE_ROOT", "").strip()
        name_kwargs = {"a_name_pool_root": Path(configured_names).expanduser()} if configured_names else {}
        payload = consumer_type(root, **name_kwargs).get(trade_date, stage_id)
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    if any(payload.get(flag) is not False for flag in _SAFETY_FLAGS):
        return None
    if str(payload.get("trade_date") or "") != trade_date:
        return None
    nested_stage = payload.get("stage")
    declared_stage = (
        nested_stage.get("stage_id")
        if isinstance(nested_stage, Mapping)
        else payload.get("stage_id")
    )
    if str(declared_stage or "") != stage_id:
        return None
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        return None
    a_market = markets.get("A_SHARE")
    if not isinstance(a_market, Mapping):
        return None
    raw_rows = a_market.get("rows")
    if not isinstance(raw_rows, list):
        return None
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        if not _row_matches_exact_date(raw, trade_date):
            continue
        if not _is_safe_watch_only_row(raw):
            continue
        row = deepcopy(dict(raw))
        row.update(
            {
                "trade_date": trade_date,
                "market": "A",
                "recommendation_status": "WATCH_ONLY",
            }
        )
        if row.get("symbol") in (None, "") and row.get("code") not in (None, ""):
            row["symbol"] = row["code"]
        rows.append(row)
    return payload, rows


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
    runner: StageRunner | None = None
    rows: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    for stage_id in FROZEN_STAGE_IDS:
        shared_result = _read_shared_stage_center_rows(trade_date, stage_id)
        if shared_result is not None:
            payload, raw_rows = shared_result
        else:
            if runner is None:
                runner = StageRunner(StageStore(data_root))
            try:
                payload = runner.read_workbench(trade_date, stage_id, limit=50)
            except (OSError, ValueError):
                # A corrupt or incomplete stage is not usable evidence.  The
                # review remains compact unless another exact stage has rows.
                continue
            raw_rows = payload.get("unified_rows") if isinstance(payload, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trade_date") or "") != trade_date:
            continue
        stage = payload.get("stage")
        declared_stage = (
            stage.get("stage_id")
            if isinstance(stage, Mapping)
            else payload.get("stage_id")
        )
        if str(declared_stage or "") != stage_id:
            continue
        if not isinstance(raw_rows, list):
            continue
        stage_rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            if raw.get("market") != "A":
                continue
            if not _is_safe_watch_only_row(raw):
                continue
            if not _row_matches_exact_date(raw, trade_date):
                continue
            row = deepcopy(dict(raw))
            row.update(
                {
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "role_type": "stage_validation_anchor",
                    "primary_role": "stage_validation_anchor",
                    "recommendation_status": "WATCH_ONLY",
                    "formal_eligible": False,
                    "validation_scope": f"{trade_date} {stage_id} exact-date stage evidence",
                    "cannot_confirm": "CANNOT_CONFIRM_FORMAL_REVIEW_BUNDLE",
                }
            )
            if row.get("stock_code") in (None, "") and row.get("symbol") not in (None, ""):
                row["stock_code"] = row["symbol"]
            stage_rows.append(row)
        if not stage_rows:
            continue
        markets = payload.get("markets")
        a_market = markets.get("A_SHARE") if isinstance(markets, Mapping) else None
        run_receipt = payload.get("run_receipt")
        materialized_snapshot = payload.get("materialized_snapshot")
        run_id = str(
            payload.get("run_id")
            or (a_market.get("run_id") if isinstance(a_market, Mapping) else "")
            or (run_receipt.get("run_id") if isinstance(run_receipt, Mapping) else "")
            or (
                materialized_snapshot.get("run_id")
                if isinstance(materialized_snapshot, Mapping)
                else ""
            )
            or ""
        )
        response_source = str(payload.get("response_source") or "")
        source_role = str(
            payload.get("source_role")
            or payload.get("role")
            or response_source
            or ""
        )
        stage_status = (
            stage.get("status")
            if isinstance(stage, Mapping)
            else payload.get("status")
        )
        artifact_id = (
            payload.get("artifact_id")
            or payload.get("bundle_artifact_id")
            or (a_market.get("artifact_id") if isinstance(a_market, Mapping) else "")
            or payload.get("id")
            or ""
        )
        algorithm_id = payload.get("algorithm_id") or (
            a_market.get("algorithm_id") if isinstance(a_market, Mapping) else ""
        )
        algorithm_sha256 = payload.get("algorithm_sha256") or (
            a_market.get("algorithm_sha256") if isinstance(a_market, Mapping) else ""
        )
        raw_artifact_sha256 = payload.get("raw_artifact_sha256") or (
            a_market.get("raw_artifact_sha256") if isinstance(a_market, Mapping) else ""
        )
        source_refs.append(
            {
                "source_role": source_role,
                "response_source": response_source,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "artifact_id": str(artifact_id),
                "run_id": run_id,
                "algorithm_id": str(algorithm_id or ""),
                "algorithm_sha256": str(algorithm_sha256 or ""),
                "raw_artifact_sha256": str(raw_artifact_sha256 or ""),
                "artifact_sha256": _sha256(payload),
                "row_count": len(stage_rows),
                "status": str(stage_status or ""),
            }
        )
        rows.extend(stage_rows)
    return rows, source_refs


def _partial_stage_review(
    trade_date: str,
    stage_rows: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    source_sha = _sha256(
        {"trade_date": trade_date, "source_refs": source_refs, "stage_rows": stage_rows}
    )
    cannot_confirm = [
        "REVIEW_CORE_BUNDLE_NOT_MATERIALIZED",
        "FORMAL_PRIOR_PLAN_NOT_MATERIALIZED",
        "FORMAL_BOARD_COVERAGE_NOT_MATERIALIZED",
        "FORMAL_MAINLINE_NOT_MATERIALIZED",
        "FORMAL_CORE_NOT_MATERIALIZED",
        "DAILY_VIDEO_NOT_LOCKED",
    ]
    review = build_a_share_review(
        trade_date,
        big_picture=[],
        mainlines=[],
        core_stocks=[],
        observation_pool=deepcopy(stage_rows),
        trigger_rows=[],
        quality_gate_rows=deepcopy(source_refs),
        source_sha256=source_sha,
        market_regime="CANNOT_CONFIRM",
        risk_tone="CANNOT_CONFIRM",
        cannot_confirm=cannot_confirm,
        model_review={
            "status": "NOT_MATERIALIZED",
            "cannot_confirm": ["A_SHARE_CLOSE_MODEL_NOT_MATERIALIZED"],
        },
        source_evidence=deepcopy(source_refs),
        source_role="V3_5_STAGE_EVIDENCE_PARTIAL",
    )
    review.update(
        {
            "status": "PARTIAL_STAGE_EVIDENCE",
            "headline": f"A股复盘 {trade_date} · 阶段候选仅作 WATCH_ONLY 验证锚",
            "stage_validation_rows": deepcopy(stage_rows),
            "summary_cards": [],
            "market_rows": [],
            "prior_plan_rows": [],
            "board_rows": [],
            "anchor_rows": [],
            "anchor_role_v3_rows": [],
            "intraday_handoff_rows": [],
            "catalyst_rows": [],
            "trigger_rows": [],
            "scenario_tree_rows": [],
            "video": {
                "status": "CANNOT_CONFIRM",
                "date_scope": "DAILY_VIDEO_NOT_LOCKED",
                "target_trade_date": trade_date,
                "trade_date": trade_date,
                "artifact_refs": [],
                "cannot_confirm": ["DAILY_VIDEO_NOT_LOCKED"],
            },
            "video_gap_rows": [],
            "source_status_rows": deepcopy(source_refs),
            "formal_pool_validation": {
                "status": "CANNOT_CONFIRM",
                "cannot_confirm": ["FORMAL_REVIEW_CORE_NOT_MATERIALIZED"],
            },
            "rule_adoption_rows": [],
            "video_learning_rows": [],
            "cannot_confirm_items": cannot_confirm,
            "source_run_id": "",
            "artifact_sha256": "",
            "review_core_bundle": {
                "status": "NOT_MATERIALIZED",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": trade_date,
                "cannot_confirm": ["REVIEW_CORE_BUNDLE_NOT_MATERIALIZED"],
            },
            "review_surface": {
                "tier": "V3_RICH_PARTIAL",
                "status": "PARTIAL_STAGE_EVIDENCE",
                "trade_date": trade_date,
                "source_role": "V3_5_NATIVE_STAGE_SNAPSHOT",
                "source_refs": deepcopy(source_refs),
                "stage_validation_count": len(stage_rows),
                "formal_sections": {
                    "prior_plan": "CANNOT_CONFIRM",
                    "board_coverage": "CANNOT_CONFIRM",
                    "mainlines": "CANNOT_CONFIRM",
                    "core_stocks": "CANNOT_CONFIRM",
                },
                "cannot_confirm": cannot_confirm,
            },
            **_SAFETY_FLAGS,
        }
    )
    return review


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
    from infrastructure.owned_io import SafeRoot, LockAcquireTimeout
    from domains.research_review_generation.assembly import assemble_runtime
    from domains.research_review_generation import run_generation

    if not bindings_path or not bindings_sha256 or not review_root:
        raise _manual_error(503, "GENERATION_NOT_CONFIGURED", "手动生成尚未绑定服务端配置。")
    try:
        path = Path(bindings_path)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("binding path")
        raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=128 * 1024)
        if hashlib.sha256(raw).hexdigest() != bindings_sha256:
            raise ValueError("binding digest")
        binding = json.loads(raw)
        if (set(binding) != {"schema_version", "config_root", "review_root", "dates"}
                or binding["schema_version"] != "v4.manual_review_bindings.v1"
                or not isinstance(binding["dates"], dict)):
            raise ValueError("binding schema")
        if date not in binding["dates"]:
            raise _manual_error(404, "DATE_NOT_CONFIGURED", "该日期没有单独批准的生成配置。")
        item = binding["dates"][date]
        if set(item) != {"config", "config_sha256", "source_manifest_sha256"}:
            raise ValueError("date binding")
        root = Path(binding["config_root"])
        output = Path(binding["review_root"])
        if (not root.is_absolute() or ".." in root.parts or not output.is_absolute()
                or ".." in output.parts or output != Path(review_root)):
            raise ValueError("root mismatch")
        # Validate every ancestry using the shared safe reader before assembly.
        SafeRoot(root).read_bytes(item["config"], max_bytes=128 * 1024)
        runtime = assemble_runtime(config_path=root / item["config"],
            config_sha256=item["config_sha256"],
            implementation_manifest_sha256=item["source_manifest_sha256"],
            transport=transport, client_factory=client_factory)
        if output != runtime.state_root / "reviews":
            raise ValueError("reader/writer root mismatch")
        asof = datetime.fromisoformat(runtime.configuration["data_as_of"])
        if asof.tzinfo is None or asof.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") != date:
            raise _manual_error(422, "CONFIG_DATE_MISMATCH", "生成配置的事实日期与所选日期不一致。")
    except HTTPException:
        raise
    except Exception:
        # Do not relay config paths, arbitrary SDK messages or credential data.
        raise _manual_error(503, "GENERATION_BINDING_INVALID", "服务端生成绑定未通过校验。") from None

    identity = {"date": date, "config_sha256": item["config_sha256"],
                "source_manifest_sha256": item["source_manifest_sha256"]}
    io = SafeRoot(runtime.state_root)
    relative = f"manual_generation/{date}.json"

    def existing() -> dict[str, Any] | None:
        result = load_daily_research_review(date, review_root=output)
        if result.get("status") == "READY":
            return {"status": "ALREADY_EXISTS", "trade_date": date,
                    "artifact_sha256": result.get("artifact_sha256", ""), **_SAFETY_FLAGS}
        return None

    def save(status: str) -> None:
        value = {"schema_version": "v4.manual_review_attempt.v1", **identity,
                 "status": status, **_SAFETY_FLAGS}
        io.write_bytes(relative, (json.dumps(value, sort_keys=True) + "\n").encode())

    ready = existing()
    if ready is not None:
        return ready
    try:
        # Uses the existing SafeRoot kernel lock; generation still obtains its
        # own public same-date lock and never receives replace=True.
        with io.kernel_lock(f"manual_generation/{date}.lock", timeout=0):
            ready = existing()
            if ready is not None:
                return ready
            try:
                previous = json.loads(io.read_bytes(relative, max_bytes=8192))
            except FileNotFoundError:
                previous = None
            if previous is not None:
                raise _manual_error(409, "ATTEMPT_REQUIRES_REVIEW", "该日期已有生成尝试，请核对记录后再处理；未重复请求模型。")
            save("RUNNING")
            try:
                result = run_generation(date, review_root=output, runtime=runtime)
                save("SUCCEEDED")
                return {"status": result["status"], "trade_date": date,
                        "artifact_sha256": result["artifact_sha256"], **_SAFETY_FLAGS}
            except Exception:
                ready = existing()  # Another caller of the existing CLI may have won.
                if ready is not None:
                    save("ALREADY_EXISTS")
                    return ready
                save("FAILED")
                raise _manual_error(502, "GENERATION_FAILED", "生成未完成；请核对本地记录，未自动重试。") from None
    except LockAcquireTimeout:
        raise _manual_error(409, "GENERATION_RUNNING", "该日期正在生成，请勿重复提交。") from None
    except HTTPException:
        raise
    except Exception:
        raise _manual_error(503, "GENERATION_STATE_UNAVAILABLE", "生成状态无法安全确认，请核对本地记录。") from None


def create_review_router(
    data_root: Path,
    review_root: Path | str | None = None,
    *,
    hk_close_root: Path | str | None = None,
    generation_bindings_path: Path | str | None = None,
    generation_bindings_sha256: str | None = None,
    intraday_root: Path | str | None = None,
    _generation_transport: Any = None,
    _generation_client_factory: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v3", tags=["review"])
    resolved_hk_close_root = (
        Path(hk_close_root).expanduser() if hk_close_root is not None else Path(data_root)
    )

    @router.post("/review/generate")
    async def generate(body: ManualReviewRequest, request: Request) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.url.netloc or parsed.scheme != request.url.scheme:
                raise _manual_error(403, "ORIGIN_REFUSED", "仅允许同源研究面板触发生成。")
        return await run_in_threadpool(_manual_generate, body.date,
            bindings_path=generation_bindings_path, bindings_sha256=generation_bindings_sha256,
            review_root=review_root, transport=_generation_transport,
            client_factory=_generation_client_factory)

    @router.get("/review")
    def review(date: str = Query(..., pattern=r"^\d{8}$")) -> dict[str, Any]:
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError as error:
            raise HTTPException(status_code=422, detail="date must be a real calendar date") from error

        native_hk, native_present = _native_hk_review(resolved_hk_close_root, date)
        if native_present:
            # A local exact-date ReviewStore artifact is authoritative.  An
            # invalid present artifact fails closed; it must not be replaced
            # by a less authoritative bridge result.
            hk_payload = native_hk
        elif _HAS_HK_REVIEW_CORE:
            hk_source = load_hk_close_review(date, resolved_hk_close_root)
            hk_payload = _hk_parent(date, hk_source)
        else:
            # Compatibility for the pre-T183 checkout: preserve the existing
            # ReviewStore response shape while the candidate supplies the
            # Review Core bridge implementation.
            hk_payload = close_review(ReviewStore(resolved_hk_close_root), date)["market_reviews"]["HK"]

        strict_review_core = _HAS_REVIEW_EVIDENCE_LAYERS and review_core_a_share_bundle_required(
            data_root, date
        )
        bundle_error = ""
        partial_stage_rows: list[dict[str, Any]] = []
        partial_stage_refs: list[dict[str, Any]] = []
        if strict_review_core:
            try:
                a_payload = load_review_core_a_share_review(date, data_root)
            except Exception as error:
                a_payload = None
                bundle_error = f"REVIEW_CORE_BUNDLE_INVALID: {type(error).__name__}: {error}"
        else:
            a_share_reviews = AShareReviewStore(data_root)
            try:
                a_payload = a_share_reviews.read_review(date)
            except ValueError:
                a_payload = None
            if a_payload is not None and a_payload.get("source_role") != "V3_5_NATIVE_CLOSE_MODEL":
                a_payload = None
            if a_payload is None:
                partial_stage_rows, partial_stage_refs = _read_exact_stage_review_rows(data_root, date)
                if partial_stage_rows:
                    a_payload = _partial_stage_review(
                        date,
                        partial_stage_rows,
                        partial_stage_refs,
                    )
        envelope = review_envelope(date, a_review=a_payload, hk_review=hk_payload or {})
        a_document = envelope["market_reviews"]["A"]
        if bundle_error:
            a_document["cannot_confirm"] = [bundle_error]
            envelope["review_core_bundle"] = {
                "status": "CANNOT_CONFIRM",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": date,
                "cannot_confirm": [bundle_error],
            }
        elif strict_review_core:
            envelope["review_core_bundle"] = {
                "status": "READY",
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "trade_date": date,
                "source_sha256": str(a_payload.get("source_sha256") or "")
                if isinstance(a_payload, Mapping)
                else "",
            }
            a_document["review_surface"] = {
                "tier": "V3_RICH_READY",
                "status": str(a_document.get("status") or "READY"),
                "trade_date": date,
                "source_role": "REVIEW_CORE_BUNDLE_V1",
                "source_refs": deepcopy(a_document.get("source_evidence") or []),
            }
        if _HAS_REVIEW_EVIDENCE_LAYERS:
            envelope["review_evidence_layers"] = load_review_evidence_layers(
                data_root,
                date,
                envelope["market_reviews"]["A"],
            )
        # The daily research review is an optional exact-date read-only
        # projection.  Its source root is explicit (argument or
        # V4_DAILY_REVIEW_ROOT); missing configuration remains visible as
        # CANNOT_CONFIRM and never falls back to latest.json.
        from domains.intraday_research import read_intraday_day
        try:
            envelope["intraday_research"] = read_intraday_day(
                date, intraday_root=Path(intraday_root) if intraday_root else None,
                review_root=Path(review_root) if review_root else None)
        except (OSError, ValueError, KeyError, TypeError):
            envelope["intraday_research"] = {"status": "CANNOT_CONFIRM", "slots": [],
                "cannot_confirm": ["INTRADAY_BOUNDARY_REFUSED"], **_SAFETY_FLAGS}
        envelope["research_review"] = load_daily_research_review(
            date,
            review_root=review_root,
        )
        hk_document = (
            hk_payload.get("model_selection_review")
            if isinstance(hk_payload, Mapping)
            else None
        )
        envelope["reference_snapshot"] = bool(
            (hk_document or {}).get(
                "reference_snapshot",
                hk_payload.get("reference_snapshot", False)
                if isinstance(hk_payload, Mapping)
                else False,
            )
        )
        return envelope

    return router
