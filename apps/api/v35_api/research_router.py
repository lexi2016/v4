"""Exact-date daily and slot-only hourly research product APIs."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query

from contracts.research_day_product import (
    CONTRACT_ID,
    EXPECTED_RESEARCH_SLOTS,
    PASS_SIGNAL,
    PRODUCT_SCHEMA_VERSION,
    SELECTION_CONTRACT_ID,
    SELECTION_MARKET_FOCUS,
    SELECTION_PASS_SIGNAL,
    SELECTION_PHASES,
    SELECTION_SCHEMA_VERSION,
    SELECTION_WORKFLOW_NAME,
    validate_manager_research_decision,
    validate_selection_market_scope,
    validate_selection_research_product,
    WORKFLOW_NAME,
    validate_research_day_product,
)
from domains.research_day_product import consume_authoritative_research_day
from infrastructure.data_store import _date
from infrastructure.research_store import (
    HourlyResearchStore,
    ResearchArchiveStore,
    ResearchSelectionStore,
)


def _legacy_missing(*, archive_date: str | None, endpoint_mode: str) -> dict:
    identity = archive_date or "LATEST"
    return {
        "schema_version": "v3_5.research_articles.v1",
        "status": "NOT_MATERIALIZED",
        "endpoint_mode": endpoint_mode,
        "archive_date": archive_date,
        "timezone": "Asia/Shanghai",
        "article_count": 0,
        "stock_pool_count": 0,
        "articles": [],
        "stock_pool": [],
        "source_counts": {},
        "cannot_confirm": [f"RESEARCH_ARCHIVE_NOT_MATERIALIZED:{identity}"],
        "loading_complete": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _legacy_response(payload: dict, *, endpoint_mode: str) -> dict:
    return {
        **payload,
        "schema_version": "v3_5.research_articles.v1",
        "endpoint_mode": endpoint_mode,
        "loading_complete": True,
    }


def _day_missing(
    *,
    archive_date: str | None,
    endpoint_mode: str,
    reason_prefix: str = "RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED",
) -> dict:
    identity = archive_date or "LATEST"
    return {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "workflow_name": WORKFLOW_NAME,
        "pass_signal": PASS_SIGNAL,
        "status": "NOT_MATERIALIZED",
        "authoritative": False,
        "endpoint_mode": endpoint_mode,
        "date_mode": "EXACT",
        "archive_date": archive_date,
        "requested_date": archive_date,
        "resolved_date": None,
        "timezone": "Asia/Shanghai",
        "is_full_day": True,
        "coverage": {
            "expected_slots": len(EXPECTED_RESEARCH_SLOTS),
            "ready_slots": 0,
            "missing_slots": list(EXPECTED_RESEARCH_SLOTS),
            "complete": False,
            "slot_matrix": [],
        },
        "counts": {
            "raw_rows": 0,
            "evidence_rows": 0,
            "excluded_rows": 0,
            "mention_pairs": 0,
            "urls": 0,
            "stock_rollups": 0,
            "high_priority": 0,
            "duplicate_pairs": 0,
        },
        "evidence_rows": [],
        "mention_pairs": [],
        "stock_rollups": [],
        "high_priority": [],
        "high_priority_status": {
            "status": "CANNOT_CONFIRM",
            "rule_id": None,
            "registry": "MISSING",
            "cannot_confirm": f"{reason_prefix}:{identity}",
        },
        "jyg_coverage": {
            "status": "CANNOT_CONFIRM",
            "articles": None,
            "expected_articles": None,
            "stock_mentions": None,
            "registry": "MISSING",
            "gap": "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
        },
        "slot_matrix": [],
        "expected_slots": list(EXPECTED_RESEARCH_SLOTS),
        "exclusions": {
            "date_mismatch": 0,
            "pit_violation": 0,
            "invalid_row": 0,
        },
        "excluded_by_date": {},
        "lineage": None,
        "cannot_confirm": [f"{reason_prefix}:{identity}"],
        "loading_complete": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _day_response(
    payload: dict,
    *,
    endpoint_mode: str,
    requested_date: str | None,
) -> dict:
    validate_research_day_product(payload)
    resolved_date = str(payload["archive_date"])
    return {
        **payload,
        "endpoint_mode": endpoint_mode,
        "date_mode": "EXACT",
        "requested_date": requested_date,
        "resolved_date": resolved_date,
        "is_full_day": True,
        "loading_complete": True,
    }


def _selection_snapshot_missing(phase: str) -> dict:
    return {
        "phase": phase,
        "status": "NOT_MATERIALIZED",
        "run_id": None,
        "event_at": None,
        "artifact_sha256": None,
        "candidate_ids": [],
        "changes": [],
        "freeze_run_id": None,
        "freeze_snapshot_sha256": None,
        "snapshot_sha256": None,
    }


def _selection_missing(
    *,
    target_trade_date: str,
    reason: str,
    status: str = "NOT_MATERIALIZED",
) -> dict:
    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "contract_id": SELECTION_CONTRACT_ID,
        "workflow_name": SELECTION_WORKFLOW_NAME,
        "pass_signal": SELECTION_PASS_SIGNAL,
        "source_date": None,
        "target_trade_date": target_trade_date,
        "timezone": "Asia/Shanghai",
        "cutoff_at": None,
        "generated_at": None,
        "run_id": None,
        "origin": None,
        "status": status,
        "acceptance": "NOT_MATERIALIZED",
        "research_candidates": [],
        "formal_shortlist": [],
        "snapshots": {
            phase: _selection_snapshot_missing(phase) for phase in SELECTION_PHASES
        },
        "intraday_observations": [],
        "outcomes": [],
        "counts": {
            "research_candidates": 0,
            "formal_shortlist": 0,
            "snapshots": len(SELECTION_PHASES),
            "intraday_observations": 0,
            "outcomes": 0,
        },
        "route_status": {
            "R1": "NOT_MATERIALIZED",
            "R2": "NOT_MATERIALIZED",
            "R6": "NOT_MATERIALIZED",
            "GEMINI": "NOT_MATERIALIZED",
        },
        "gemini_status": "NOT_MATERIALIZED",
        "formal_authority": {
            "status": "NOT_MATERIALIZED",
            "target_trade_date": target_trade_date,
            "pit_status": "CANNOT_CONFIRM",
            "selector_status": "CANNOT_CONFIRM",
            "research_evidence": False,
            "manager_decision": False,
            "source_sha256": None,
            "evidence_refs": [],
            "manager_decision_ref": None,
        },
        "source_refs": [],
        "first_failed_layer": reason,
        "cannot_confirm": [reason],
        "endpoint_mode": "EXACT",
        "requested_date": target_trade_date,
        "lineage": None,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


_MANAGER_DECISION_READ_SCHEMA = "v3_5.manager_research_decision_read.v1"
_MANAGER_DECISION_DOCUMENT_SCHEMA = "v3_5.manager_research_decision.v1"
_MANAGER_DECISION_PHASE = "2200"
_MANAGER_DECISION_STATE = "INITIAL_RESEARCH_DELTA"
_MANAGER_DECISION_NOT_MATERIALIZED_REASON = "SELECTION_PRODUCT_NOT_MATERIALIZED"


def _manager_decision_missing(
    *,
    target_trade_date: str,
    reason: str,
    status: str = "CANNOT_CONFIRM",
) -> dict[str, Any]:
    """Return a typed, path-free empty decision DTO for every failed read."""

    is_not_materialized = status == "NOT_MATERIALIZED"
    return {
        "schema_version": _MANAGER_DECISION_READ_SCHEMA,
        "document_schema_version": _MANAGER_DECISION_DOCUMENT_SCHEMA,
        "endpoint_mode": "EXACT",
        "requested_date": target_trade_date,
        "target_trade_date": target_trade_date,
        "status": status,
        "source_date": None,
        "phase": None,
        "decision_state": None,
        "run_id": None,
        "generated_at": None,
        "cutoff_at": None,
        "core": [],
        "conditional": [],
        "KEEP": [],
        "ADD": [],
        "REMOVE": [],
        "qualification_refs": [],
        "safety": {
            "RESEARCH_ONLY": True,
            "WATCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "lineage": None,
        "reason": _MANAGER_DECISION_NOT_MATERIALIZED_REASON if is_not_materialized else None,
        "cannot_confirm": [] if is_not_materialized else [reason],
    }


def _manager_decision_response(
    document: Mapping[str, Any],
    *,
    target_trade_date: str,
    selection_lineage: Mapping[str, Any],
    decision_sha256: str,
) -> dict[str, Any]:
    """Project a validated persisted document without leaking any path."""

    rows = {
        field: [
            {"candidate_id": row["candidate_id"], "reason": row["reason"]}
            for row in document[field]
        ]
        for field in ("core", "conditional", "KEEP", "ADD", "REMOVE")
    }
    qualification_refs = [
        {
            "candidate_id": ref["candidate_id"],
            "status": ref["status"],
            "raw_sha256": ref["raw_sha256"],
        }
        for ref in document["qualification_refs"]
    ]
    has_rows = any(rows[field] for field in ("core", "conditional", "KEEP", "ADD", "REMOVE"))
    status = "READY" if has_rows else "READY_EMPTY"
    return {
        "schema_version": _MANAGER_DECISION_READ_SCHEMA,
        "document_schema_version": document["schema_version"],
        "endpoint_mode": "EXACT",
        "requested_date": target_trade_date,
        "target_trade_date": target_trade_date,
        "status": status,
        "source_date": document["source_date"],
        "phase": document["phase"],
        "decision_state": document["decision_state"],
        "run_id": document["run_id"],
        "generated_at": document["generated_at"],
        "cutoff_at": document["cutoff_at"],
        **rows,
        "qualification_refs": qualification_refs,
        "safety": {
            "RESEARCH_ONLY": document["safety"]["RESEARCH_ONLY"],
            "WATCH_ONLY": document["safety"]["WATCH_ONLY"],
            "production_allowed": document["safety"]["production_allowed"],
            "buy_gate_updated": document["safety"]["buy_gate_updated"],
            "orders_sent": document["safety"]["orders_sent"],
        },
        "lineage": {
            "selection_artifact_sha256": selection_lineage["artifact_sha256"],
            "selection_run_id": selection_lineage["run_id"],
            "manager_decision_raw_sha256": decision_sha256,
            "source_date": document["source_date"],
            "target_trade_date": target_trade_date,
        },
        "reason": None,
        "cannot_confirm": [],
    }


def _hourly_response(
    payload: dict,
    *,
    endpoint_mode: str,
    archive_date: str,
    slot: str,
) -> dict:
    rows = payload.get("evidence_rows") or payload.get("articles") or payload.get("rows") or []
    stock_rows = payload.get("stock_pool") or payload.get("stock_research_daily") or []
    return {
        "schema_version": "v3_5.research_hourly_product.v1",
        "status": "READY",
        "endpoint_mode": endpoint_mode,
        "date_mode": "EXACT",
        "archive_date": archive_date,
        "slot": slot,
        "timezone": "Asia/Shanghai",
        "is_full_day": False,
        "row_count": len(rows),
        "stock_count": len(stock_rows),
        "rows": rows,
        "stock_pool": stock_rows,
        "source_input_sha256": payload.get("source_input_sha256"),
        "cannot_confirm": [],
        "loading_complete": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _hourly_missing(
    *, archive_date: str | None, slot: str | None, endpoint_mode: str
) -> dict:
    identity = (
        f"{archive_date}:{slot}"
        if archive_date is not None and slot is not None
        else "LATEST_SLOT"
    )
    return {
        "schema_version": "v3_5.research_hourly_product.v1",
        "status": "NOT_MATERIALIZED",
        "endpoint_mode": endpoint_mode,
        "date_mode": "EXACT",
        "archive_date": archive_date,
        "slot": slot,
        "timezone": "Asia/Shanghai",
        "is_full_day": False,
        "row_count": 0,
        "stock_count": 0,
        "rows": [],
        "stock_pool": [],
        "cannot_confirm": [f"RESEARCH_HOURLY_SLOT_NOT_MATERIALIZED:{identity}"],
        "loading_complete": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def create_research_router(data_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v3/research", tags=["research"])
    daily_store = ResearchArchiveStore(data_root)
    hourly_store = HourlyResearchStore(data_root)
    selection_store = ResearchSelectionStore(data_root)

    @router.get("/articles/latest")
    def latest_articles() -> dict:
        legacy = daily_store.read_latest()
        if legacy is None or legacy.get("schema_version") == PRODUCT_SCHEMA_VERSION:
            return _legacy_missing(archive_date=None, endpoint_mode="LATEST")
        return _legacy_response(legacy, endpoint_mode="LATEST")

    @router.get("/day")
    def exact_day(
        archive_date: str = Query(..., pattern=r"^\d{8}$"),
    ) -> dict:
        """Return only the requested day product; no legacy/latest fallback."""

        try:
            selected = _date(archive_date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="archive_date must be a real calendar date",
            ) from error
        payload = daily_store.read_day_exact(selected)
        if payload is None:
            return _day_missing(
                archive_date=selected,
                endpoint_mode="EXACT",
            )
        return _day_response(
            payload,
            endpoint_mode="EXACT",
            requested_date=selected,
        )

    @router.get("/selection")
    def exact_selection(
        target_trade_date: str = Query(..., pattern=r"^\d{8}$"),
        market_focus: str = Query(SELECTION_MARKET_FOCUS),
    ) -> dict:
        """Read one immutable selection ledger; never resolve a latest date."""

        try:
            selected = _date(target_trade_date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="target_trade_date must be a real calendar date",
            ) from error
        try:
            validate_selection_market_scope(
                {"research_candidates": []},
                market_focus=market_focus,
            )
        except ValueError:
            return _selection_missing(
                target_trade_date=selected,
                reason="SELECTION_MARKET_FOCUS_FORCED:HK_CONNECT",
                status="CANNOT_CONFIRM",
            )
        try:
            payload, lineage = selection_store.read_exact_with_lineage(selected)
            if payload is None:
                return _selection_missing(
                    target_trade_date=selected,
                    reason=f"SELECTION_PRODUCT_NOT_MATERIALIZED:{selected}",
                )
            if lineage is None:
                return _selection_missing(
                    target_trade_date=selected,
                    reason=f"SELECTION_LINEAGE_NOT_MATERIALIZED:{selected}",
                    status="CANNOT_CONFIRM",
                )
            validate_selection_research_product(
                payload,
                market_focus=market_focus,
            )
            return {
                **payload,
                "endpoint_mode": "EXACT",
                "requested_date": selected,
                "target_trade_date": selected,
                "lineage": lineage,
                "artifact_sha256": lineage["artifact_sha256"],
                "manifest_sha256": lineage["manifest_sha256"],
                "receipt_sha256": lineage["receipt_sha256"],
                "current_sha256": lineage["current_sha256"],
            }
        except ValueError as error:
            return _selection_missing(
                target_trade_date=selected,
                reason=f"SELECTION_PRODUCT_INVALID:{error}",
                status="CANNOT_CONFIRM",
            )

    @router.get("/selection/manager-decision")
    def exact_manager_decision(
        target_trade_date: str = Query(..., pattern=r"^\d{8}$"),
    ) -> dict[str, Any]:
        """Read the persisted 22:00 manager decision through exact selection.

        The browser supplies only a date.  The selection artifact owns the
        decision reference, and the store verifies that artifact, its source
        evidence, and its reference bytes before this route projects a
        path-free DTO.
        """

        try:
            selected = _date(target_trade_date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="target_trade_date must be a real calendar date",
            ) from error

        try:
            payload, lineage = selection_store.read_exact_with_lineage(selected)
            if payload is None:
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=_MANAGER_DECISION_NOT_MATERIALIZED_REASON,
                    status="NOT_MATERIALIZED",
                )
            if lineage is None:
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"SELECTION_LINEAGE_NOT_MATERIALIZED:{selected}",
                )
            ref = payload.get("manager_decision_ref")
            if not isinstance(ref, Mapping):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_REF_MISSING:{selected}",
                )
            path_value = ref.get("path")
            expected_sha = str(ref.get("raw_sha256") or "").lower()
            if (
                not isinstance(path_value, str)
                or not path_value
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            ):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_REF_INVALID:{selected}",
                )
            decision_path = Path(path_value)
            if not decision_path.is_file() or decision_path.is_symlink():
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_REF_UNAVAILABLE:{selected}",
                )
            raw = decision_path.read_bytes()
            decision_sha = hashlib.sha256(raw).hexdigest()
            if decision_sha != expected_sha:
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_REF_SHA_MISMATCH:{selected}",
                )
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_DOCUMENT_INVALID:{selected}",
                )
            if not isinstance(document, Mapping):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_DOCUMENT_INVALID:{selected}",
                )
            raw_candidates = payload.get("research_candidates")
            if (
                not isinstance(raw_candidates, list)
                or any(
                    not isinstance(candidate, Mapping)
                    or not isinstance(candidate.get("candidate_id"), str)
                    or not candidate.get("candidate_id")
                    for candidate in raw_candidates
                )
            ):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"SELECTION_CANDIDATE_SET_INVALID:{selected}",
                )
            candidate_ids = [str(candidate["candidate_id"]) for candidate in raw_candidates]
            if len(candidate_ids) != len(set(candidate_ids)):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"SELECTION_CANDIDATE_SET_INVALID:{selected}",
                )
            snapshots = payload.get("snapshots")
            snapshot_2200 = snapshots.get("2200", {}) if isinstance(snapshots, Mapping) else {}
            snapshot_ids = snapshot_2200.get("candidate_ids") if isinstance(snapshot_2200, Mapping) else None
            if (
                not isinstance(snapshot_2200, Mapping)
                or snapshot_2200.get("status") != "READY"
                or not isinstance(snapshot_ids, list)
                or any(not isinstance(candidate_id, str) or not candidate_id for candidate_id in snapshot_ids)
                or len(snapshot_ids) != len(set(snapshot_ids))
            ):
                return _manager_decision_missing(
                    target_trade_date=selected,
                    reason=f"MANAGER_DECISION_2200_SNAPSHOT_INVALID:{selected}",
                )
            validate_manager_research_decision(
                document,
                candidate_ids=candidate_ids,
            )
            if expected_sha != str(snapshot_2200.get("artifact_sha256") or "").lower():
                raise ValueError("manager decision 2200 artifact binding mismatch")
            if document.get("run_id") != snapshot_2200.get("run_id"):
                raise ValueError("manager decision 2200 run binding mismatch")
            if document.get("generated_at") != snapshot_2200.get("event_at"):
                raise ValueError("manager decision 2200 event binding mismatch")
            if payload.get("source_date") is not None and document.get("source_date") != payload.get("source_date"):
                raise ValueError("manager decision source date binding mismatch")
            if payload.get("cutoff_at") is not None and document.get("cutoff_at") != payload.get("cutoff_at"):
                raise ValueError("manager decision cutoff binding mismatch")
            decision_ids = [
                str(row["candidate_id"])
                for field in ("core", "conditional")
                for row in document[field]
            ]
            if len(decision_ids) != len(set(decision_ids)) or set(decision_ids) != set(snapshot_ids):
                raise ValueError("manager decision 2200 candidate binding mismatch")
            if document.get("target_trade_date") != selected:
                raise ValueError("manager decision target date mismatch")
            return _manager_decision_response(
                document,
                target_trade_date=selected,
                selection_lineage=lineage,
                decision_sha256=decision_sha,
            )
        except (OSError, TypeError, ValueError, KeyError) as error:
            return _manager_decision_missing(
                target_trade_date=selected,
                reason=f"MANAGER_DECISION_INVALID:{error}",
            )

    @router.get("/articles")
    def exact_articles(archive_date: str = Query(..., pattern=r"^\d{8}$")) -> dict:
        try:
            selected = _date(archive_date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="archive_date must be a real calendar date",
            ) from error
        legacy = daily_store.read_exact(selected)
        if legacy is None or legacy.get("schema_version") == PRODUCT_SCHEMA_VERSION:
            return _legacy_missing(archive_date=selected, endpoint_mode="EXACT")
        return _legacy_response(legacy, endpoint_mode="EXACT")

    @router.get("/hourly")
    def exact_hourly(
        archive_date: str = Query(..., pattern=r"^\d{8}$"),
        slot: str = Query(..., pattern=r"^\d{4}$"),
    ) -> dict:
        try:
            selected = _date(archive_date)
            payload = hourly_store.read_exact(selected, slot, mode="LIVE")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if payload is None:
            return _hourly_missing(
                archive_date=selected,
                slot=slot,
                endpoint_mode="EXACT_SLOT",
            )
        return _hourly_response(
            payload,
            endpoint_mode="EXACT_SLOT",
            archive_date=selected,
            slot=slot,
        )

    @router.get("/hourly/latest")
    def latest_hourly() -> dict:
        pointer_path = data_root / "research" / "hourly" / "latest.json"
        payload = None
        archive_date = None
        slot = None
        if pointer_path.is_file():
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            hourly_store._validate_pointer(pointer)
            archive_date = str(pointer["archive_date"])
            slot = str(pointer["slot"])
            payload = hourly_store.read_exact(archive_date, slot, mode="LIVE")
        if payload is None:
            return _hourly_missing(
                archive_date=archive_date,
                slot=slot,
                endpoint_mode="LATEST_SLOT",
            )
        return _hourly_response(
            payload,
            endpoint_mode="LATEST_SLOT",
            archive_date=archive_date,
            slot=slot,
        )

    @router.get("/authoritative")
    def exact_authoritative(
        archive_date: str = Query(..., pattern=r"^\d{8}$"),
    ) -> dict:
        try:
            selected = _date(archive_date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="archive_date must be a real calendar date",
            ) from error
        payload = daily_store.read_day_exact(selected)
        consumed = consume_authoritative_research_day(
            payload,
            requested_date=selected,
        )
        if consumed.get("status") == "READY" and consumed.get("authoritative") is True:
            return _day_response(
                consumed,
                endpoint_mode="EXACT",
                requested_date=selected,
            )
        return consumed

    return router
