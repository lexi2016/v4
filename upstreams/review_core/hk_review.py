"""Independent exact-date HK Connect close-review composition."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from .hk_sources import (
        HK_02_ROLE,
        STAGE_IDS,
        STAGE_ROLES,
        call_loader,
        default_close_loader,
        default_model_loader,
        default_stage_loader,
        normalize_close,
        normalize_model,
        normalize_stage,
        resolve_shared_root,
        unwrap_close,
    )
    from .pool_store import ConflictError, PoolStore, StoreError
except ImportError:  # direct focused invocation from review_core/
    from hk_sources import (
        HK_02_ROLE,
        STAGE_IDS,
        STAGE_ROLES,
        call_loader,
        default_close_loader,
        default_model_loader,
        default_stage_loader,
        normalize_close,
        normalize_model,
        normalize_stage,
        resolve_shared_root,
        unwrap_close,
    )
    from pool_store import ConflictError, PoolStore, StoreError

REVIEW_SCHEMA = "HK_CLOSE_REVIEW_V1"
REVIEW_ROLE = REVIEW_SCHEMA

def _date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise StoreError("trade_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise StoreError("trade_date must be real") from error
    return value

def _metric(selected: list[str], truth: set[str], status: str = "READY") -> dict[str, Any]:
    hits = [code for code in selected if code in truth]
    return {
        "evidence_status": status,
        "selected_count": len(selected),
        "selected_codes": selected,
        "hit_count": len(hits) if status == "READY" else None,
        "hit_codes": hits if status == "READY" else [],
        "coverage_pct": round(len(hits) / 20 * 100, 6) if status == "READY" else None,
        "precision_pct": (
            round(len(hits) / len(selected) * 100, 6)
            if selected and status == "READY"
            else 0.0
            if status == "READY"
            else None
        ),
    }

def _load_model(
    loader: Callable[..., Any], root: Path | None, date: str, signal: str
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    try:
        value = call_loader(
            loader,
            (
                ((root, date, signal), {}),
                ((root, date), {}),
                ((date, signal), {}),
                ((date,), {}),
                ((), {"store_root": root, "target_date": date, "expected_signal_date": signal}),
            ),
        )
        rows, metadata, error = normalize_model(value, date)
        return rows, metadata, ["HK_REVIEW_0_2_SHARED_SOURCE_GAP"] if error else []
    except Exception:
        return [], {
            "role": HK_02_ROLE,
            "run_id": "",
            "artifact_sha256": "",
            "manifest_sha256": "",
            "receipt_sha256": "",
        }, [
            "HK_REVIEW_0_2_SHARED_SOURCE_GAP"
        ]

def _load_close(
    value: Any,
    loader: Callable[..., Any] | None,
    root: Path | None,
    date: str,
) -> tuple[list[dict[str, Any]], int, str, list[str]]:
    try:
        if value is None:
            value = call_loader(
                loader or default_close_loader,
                (
                    ((root, date), {}),
                    ((date,), {}),
                    ((), {"root": root, "trade_date": date}),
                ),
            )
        payload, digest = unwrap_close(value)
        rows, count, error = normalize_close(payload, digest, date)
        return rows, count, digest, [f"HK_REVIEW_CLOSE_SOURCE_GAP:{error}"] if error else []
    except Exception as error:
        return [], 0, "", [f"HK_REVIEW_CLOSE_SOURCE_GAP:{type(error).__name__}"]

def _load_stages(
    roles: tuple[str, ...],
    loader: Callable[..., Any] | None,
    loaders: Mapping[str, Callable[..., Any]] | None,
    root: Path | None,
    date: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    cannot: list[str] = []
    for role in roles:
        selected = (loaders or {}).get(role) or loader or default_stage_loader
        try:
            value = call_loader(
                selected,
                (
                    ((root, date, role), {}),
                    ((root, date), {"role": role}),
                    ((date, role), {}),
                    ((role, date), {}),
                    ((date,), {}),
                    ((), {"store_root": root, "trade_date": date, "role": role}),
                ),
            )
            stage, source, error = normalize_stage(value, date, role)
            if error:
                if error == "selection_evidence_missing":
                    missing.append(role)
                    cannot.append(f"HK_REVIEW_STAGE_SELECTION_EVIDENCE_GAP:{role}")
                    continue
                raise StoreError(error)
            rows.extend(stage)
            metadata[role] = source
        except Exception as error:
            missing.append(role)
            cannot.append(f"HK_REVIEW_STAGE_SOURCE_GAP:{role}:{type(error).__name__}")
    return rows, metadata, missing, cannot

def _attribution(
    close_top20: list[dict[str, Any]],
    model_rows: list[dict[str, Any]],
    stage_rows: list[dict[str, Any]],
    stages_complete: bool,
) -> list[dict[str, Any]]:
    model_codes = {row["code"] for row in model_rows} if len(model_rows) == 100 else set()
    stage_codes = {row["code"] for row in stage_rows} if stages_complete else set()
    by_code: dict[str, list[str]] = {}
    for row in stage_rows:
        by_code.setdefault(row["code"], []).append(row["stage_id"])
    result: list[dict[str, Any]] = []
    for row in close_top20:
        code = row["code"]
        in_model, in_stage = code in model_codes, code in stage_codes
        classification = (
            "shared" if in_model and in_stage else
            "model_only" if in_model else
            "stage_only" if in_stage else "missed"
        )
        result.append({
            **row,
            "model_0_2_hit": in_model,
            "stage_union_hit": in_stage,
            "all_stages": by_code.get(code, []),
            "first_stage": (by_code.get(code) or [None])[0],
            "classification": classification,
        })
    return result


def build_hk_close_review(
    trade_date: str,
    *,
    shared_root: Path | str | None = None,
    close_root: Path | str | None = None,
    expected_signal_date: str | None = None,
    hk02_loader: Callable[..., Any] | None = None,
    hk_0_2_loader: Callable[..., Any] | None = None,
    close_loader: Callable[..., Any] | None = None,
    stage_loader: Callable[..., Any] | None = None,
    stage_loaders: Mapping[str, Callable[..., Any]] | None = None,
    stage_roles: Iterable[str] | None = None,
    close_snapshot: Any = None,
    close_snapshot_path: Path | str | None = None,
    **_options: Any,
) -> dict[str, Any]:
    date = _date(trade_date)
    authoritative_signal = expected_signal_date or _options.get("signal_date")
    if authoritative_signal is None:
        raise StoreError("authoritative signal_date is required")
    signal = _date(authoritative_signal)
    root = resolve_shared_root(shared_root)
    model_loader = hk02_loader or hk_0_2_loader or default_model_loader
    model_rows, model_source, cannot = _load_model(model_loader, root, date, signal)
    close_value = close_snapshot_path if close_snapshot_path is not None else close_snapshot
    close_rows, close_count, close_digest, close_cannot = _load_close(
        close_value,
        close_loader,
        Path(close_root) if close_root is not None else root,
        date,
    )
    cannot.extend(close_cannot)
    roles = tuple(stage_roles) if stage_roles is not None else STAGE_ROLES
    stage_rows, stage_sources, missing_stages, stage_cannot = _load_stages(
        roles, stage_loader, stage_loaders, root, date
    )
    cannot.extend(stage_cannot)
    cannot = list(dict.fromkeys(cannot))
    close_codes = {row["code"] for row in close_rows}
    model_ready = len(model_rows) == 100 and "HK_REVIEW_0_2_SHARED_SOURCE_GAP" not in cannot
    close_ready = len(close_rows) == 20 and not close_cannot
    stage_ready = not missing_stages
    status = "CANNOT_CONFIRM" if not close_ready else "READY" if model_ready and stage_ready else "PARTIAL"
    model_metric = _metric(
        [row["code"] for row in model_rows], close_codes,
        "READY" if model_ready else "MISSING",
    )
    stage_metric = _metric(
        list(dict.fromkeys(row["code"] for row in stage_rows)), close_codes,
        "READY" if stage_ready else "MISSING",
    )
    kpi = {
        "close_top20_count": len(close_rows),
        "model_0_2_close_top20_hits": model_metric["hit_count"],
        "stage_union_close_top20_hits": stage_metric["hit_count"],
        "model_0_2": model_metric,
        "stage_union": stage_metric,
    }
    sources = {
        "model_0_2": {**model_source, "role": HK_02_ROLE, "signal_date": signal, "target_date": date},
        "close": {"trade_date": date, "file_sha256": close_digest},
        "stages": {
            role: stage_sources.get(role, {"role": role, "run_id": "", "artifact_sha256": ""})
            for role in roles
        },
    }
    return {
        "schema_version": REVIEW_SCHEMA,
        "role": REVIEW_ROLE,
        "trade_date": date,
        "status": status,
        "model_rows": model_rows,
        "close_top20": close_rows,
        "stage_rows": stage_rows,
        "top20_attribution": _attribution(close_rows, model_rows, stage_rows, stage_ready),
        "row_counts": {
            "close_universe": close_count,
            "close_top20": len(close_rows),
            "model_rows": len(model_rows),
            "stage_rows": len(stage_rows),
            "stage_roles": len(roles),
            "missing_stage_roles": len(missing_stages),
        },
        "kpi": kpi,
        "KPI": kpi,
        "models": {"0.2_prob_active": model_metric},
        "sources": sources,
        "source_runs": {"model_0_2": model_source, "stages": stage_sources},
        "source_shas": {"model_0_2": model_source.get("artifact_sha256", ""), "close": close_digest},
        "close_source_sha256": close_digest,
        "missing_stage_roles": missing_stages,
        "cannot_confirm": cannot,
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        "evidence_mode": "SHARED_DATA_HK_0_2_AND_STAGE_CLOSE",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def publish_hk_close_review(
    root: Path | str, trade_date: str, review: Mapping[str, Any]
) -> dict[str, Any]:
    date = _date(trade_date)
    if review.get("schema_version") != REVIEW_SCHEMA or review.get("trade_date") != date:
        raise StoreError("HK close review schema/date mismatch")
    if any(review.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise StoreError("HK close review safety flags must be false")
    rows = review.get("model_rows")
    return PoolStore(root).publish(
        date,
        REVIEW_ROLE,
        dict(review),
        row_count=len(rows) if isinstance(rows, list) else 0,
        status=str(review.get("status") or "CANNOT_CONFIRM"),
    )


def run_hk_close_review(root: Path | str, trade_date: str, **kwargs: Any) -> dict[str, Any]:
    review = build_hk_close_review(trade_date, **kwargs)
    return {"review": review, "publication": publish_hk_close_review(root, trade_date, review)}


__all__ = [
    "REVIEW_SCHEMA",
    "REVIEW_ROLE",
    "HK_02_ROLE",
    "STAGE_IDS",
    "STAGE_ROLES",
    "build_hk_close_review",
    "publish_hk_close_review",
    "run_hk_close_review",
    "StoreError",
    "ConflictError",
]
