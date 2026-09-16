"""Read-only Baimao X API served from a V3.5-owned digest under ``data_root``."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from infrastructure.baimao_source import BaimaoXSource
from infrastructure.baimao_research_observation_store import (
    load_baimao_research_observations,
    BaimaoObservationReadError,
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


def _observations_cannot_confirm(source_date: str | None, reason_code: str) -> dict:
    return {
        "ok": False,
        "status": "CANNOT_CONFIRM",
        "schema_version": _OBSERVATION_SCHEMA,
        "reason_code": reason_code,
        "cannot_confirm": [reason_code],
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


def create_baimao_router(
    data_root: Path, *, observation_root: Path | str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v3/baimao", tags=["baimao"])
    source = BaimaoXSource(data_root)
    # A separate owner publishes observations. Never infer its root from
    # API data_root or fall back to a package-private .runtime directory.
    configured = observation_root if observation_root is not None else os.environ.get("V3_SHARED_BAIMAO_OBSERVATION_ROOT")
    owned_observation_root = Path(configured).expanduser() if configured else None

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
        if owned_observation_root is None:
            return _observations_cannot_confirm(source_date, "BAIMAO_OBSERVATION_ROOT_UNBOUND")
        try:
            payload = load_baimao_research_observations(source_date or "", store_root=owned_observation_root)
        except BaimaoObservationReadError as error:
            return _observations_cannot_confirm(source_date, error.reason_code)
        except FileNotFoundError:
            return _observations_cannot_confirm(source_date, "BAIMAO_OBSERVATION_NOT_FOUND")
        except ValueError:
            return _observations_cannot_confirm(source_date, "BAIMAO_OBSERVATION_INVALID")
        except Exception:
            return _observations_cannot_confirm(source_date, "BAIMAO_OBSERVATION_READ_FAILED")
        return {
            "ok": True,
            "status": "READY",
            **payload,
            "module_note": _OBSERVATION_MODULE_NOTE,
        }

    return router


__all__ = ["create_baimao_router"]
