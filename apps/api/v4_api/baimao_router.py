"""Read-only Baimao X API served from a V4-owned digest under ``data_root``."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from infrastructure.baimao_source import BaimaoXSource
from infrastructure.baimao_research_observation_store import (
    load_baimao_research_observations,
)


_OBSERVATION_SCHEMA = "BAIMAO_RESEARCH_OBSERVATION_V1"
_OBSERVATION_MODULE_NOTE = "研究观察/解释模块，不是公众号全文池或正式推荐"


def _base(status: str, *, ok: bool = False) -> dict:
    return {
        "ok": ok,
        "status": status,
        "schema_version": "v3_5.baimao_x.v1",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _observations_cannot_confirm(source_date: str | None) -> dict:
    return {
        "ok": False,
        "status": "CANNOT_CONFIRM",
        "schema_version": _OBSERVATION_SCHEMA,
        "source_date": source_date if isinstance(source_date, str) else "",
        "effective_trade_date": "",
        "source_run_id": "",
        "source_artifact_sha256": "",
        "source_report_sha256": "",
        "article_url": "",
        "title": "",
        "published_at": "",
        "counts": {"a_bj": 0, "hk": 0, "total": 0},
        "observations": {"a_bj": [], "hk": []},
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "module_note": _OBSERVATION_MODULE_NOTE,
    }


def create_baimao_router(data_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v4/baimao", tags=["baimao"])
    source = BaimaoXSource(data_root)

    @router.get("/x/latest")
    def baimao_x_latest() -> dict:
        try:
            payload = source.read_latest()
        except ValueError:
            return _base("CANNOT_CONFIRM")
        if payload is None:
            return _base("NO_BAIMAO_X_DIGEST")
        return {
            **payload,
            "schema_version": "v3_5.baimao_x.v1",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/observations")
    def baimao_observations(source_date: str | None = None) -> dict:
        try:
            payload = load_baimao_research_observations(source_date or "")
        except Exception:
            return _observations_cannot_confirm(source_date)
        return {
            "ok": True,
            "status": "READY",
            **payload,
            "module_note": _OBSERVATION_MODULE_NOTE,
        }

    return router


__all__ = ["create_baimao_router"]
