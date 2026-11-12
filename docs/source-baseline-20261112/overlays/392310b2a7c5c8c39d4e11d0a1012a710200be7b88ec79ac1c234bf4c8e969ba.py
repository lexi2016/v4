"""HTTP routes moved out of ``create_app``.

Each route reads its stores and the projection context through an explicit
``RouteContext``. ``stage_workbench`` itself stays beside the three
contexts it assembles.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query

from apps.api.v4_api.projection import ProjectionContext, project_shared_selection
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS


@dataclass(frozen=True)
class RouteContext:
    app: FastAPI
    catalog: Callable[[], dict]
    strict_date: Callable[[str], str]
    review_store: Any
    research_source: Any
    projection: ProjectionContext
    shared_selection_consumer: Any
    stage_runner: Any
    read_stage_workbench: Callable[..., dict]
    stage_timeline_summary: Callable[[Any], dict]
    bounded_summaries: Callable[..., dict]
    batch_capacity: int

def unconfigured_selection(trade_date: str, stage_id: str) -> dict:
    return {
        "schema_version": "stage_center.selection_consumer.v1",
        "response_source": "SHARED_STAGE_CENTER",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "status": "CANNOT_CONFIRM",
        "markets": {},
        "selection_markets": {},
        "market_summaries": {},
        "unified_rows": [],
        "artifact_id": None,
        "bundle_artifact_id": None,
        "cannot_confirm": ["SHARED_STAGE_CENTER_NOT_CONFIGURED"],
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def register_routes(ctx: RouteContext) -> None:
    app = ctx.app

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, bool]:
        return dict(TRADING_SAFETY_FLAGS)

    @app.get("/api/v4/meta/stages")
    def stage_metadata() -> dict:
        return {
            "stages": list(FROZEN_STAGE_IDS),
            "definitions": [
                {"stage_id": stage_id, **STAGE_DEFINITIONS[stage_id]}
                for stage_id in FROZEN_STAGE_IDS
            ],
        }

    @app.get("/api/v1/runs/date-list")
    def run_date_list(date: str | None = None) -> dict:
        requested = ctx.strict_date(date) if date is not None else None
        response = {
            **ctx.catalog(),
            "review_dates": ctx.review_store.list_dates(),
            "research_dates": ctx.research_source.list_dates(),
            "research_source": ctx.research_source.binding(),
        }
        # ``stage_artifacts`` and ``independent_pool_evidence`` are navigation
        # inputs only: they feed the date lists above and have no client or
        # server consumer. Serializing them added ~2.4 MB to this response.
        response.pop("stage_artifacts", None)
        response.pop("independent_pool_evidence", None)
        response["requested_date"] = requested
        response["selected_date"] = requested or response["navigation_date"]
        # Reuse the existing read-only validator. A configured string alone is
        # not proof of a running release; no path or exception detail is exposed.
        from infrastructure.scheduling.dispatcher import validate_release_identity
        identity = {"application": "V4", "status": "CANNOT_CONFIRM",
                    "release_id": "", "process_status": "CANNOT_CONFIRM"}
        try:
            verified = validate_release_identity()
            identity.update(status="MANIFEST_EXECUTION_FILES_VERIFIED",
                            release_id=verified["release_id"],
                            manifest_sha256=verified["release_manifest_sha256"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
        response["runtime_identity"] = identity
        return response

    @app.post("/api/v4/workbench/stage/ensure")
    def stage_workbench_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = ctx.strict_date(date) if date is not None else ctx.catalog()["default_date"]
        if not selected:
            selected = ctx.catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if ctx.shared_selection_consumer is not None:
            return project_shared_selection(ctx.projection,
                ctx.shared_selection_consumer.ensure(selected, stage, force=force),
                limit=50,
                ordinary_hk_display=True,
            )
        return ctx.stage_runner.ensure(selected, stage, force=force)

    @app.get("/api/v4/workbench/stage-batch")
    def stage_workbench_batch(
        date: str | None = None,
        stages: str | None = None,
    ) -> dict:
        """Timeline summaries for several stages in one round trip."""
        selected = ctx.strict_date(date) if date is not None else ctx.catalog()["default_date"]
        if not selected:
            selected = ctx.catalog()["system_date"]
        requested = [item for item in (stages or "").split(",") if item]
        if any(stage_id not in FROZEN_STAGE_IDS for stage_id in requested):
            raise HTTPException(status_code=422, detail="unknown stage")
        ordered = [
            stage_id
            for stage_id in FROZEN_STAGE_IDS
            if not requested or stage_id in requested
        ]

        def _summary_for(stage_id: str) -> tuple[str, dict | None]:
            try:
                payload = ctx.read_stage_workbench(selected, stage_id, 50)
            except HTTPException:
                return stage_id, None
            except (OSError, ValueError, TypeError, KeyError):
                return stage_id, None
            return stage_id, ctx.stage_timeline_summary(payload)

        summaries: dict[str, dict] = {}
        if ordered:
            workers = min(
                len(ordered),
                max(1, int(os.environ.get("V4_STAGE_BATCH_WORKERS", "8") or "8")),
            )
            timeout_seconds = float(os.environ.get("V4_STAGE_BATCH_TIMEOUT_SECONDS", "12") or "12")
            summaries = ctx.bounded_summaries(
                _summary_for, ordered, workers=min(workers, ctx.batch_capacity),
                timeout_seconds=timeout_seconds,
            )

        return {
            "schema_version": "v4.stage_timeline_batch.v1",
            "trade_date": selected,
            "stages": summaries,
            **dict(TRADING_SAFETY_FLAGS),
            "RESEARCH_ONLY": True,
            "write_performed": False,
        }

    @app.get("/api/v4/stage-center/selection")
    def shared_stage_selection(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        selected = ctx.strict_date(date) if date is not None else ctx.catalog()["default_date"]
        if not selected:
            selected = ctx.catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if ctx.shared_selection_consumer is None:
            return unconfigured_selection(selected, stage)
        return project_shared_selection(ctx.projection,
            ctx.shared_selection_consumer.get(selected, stage),
            limit,
            ordinary_hk_display=True,
        )

    @app.get("/api/v4/manager/stage-selection")
    def manager_stage_selection(
        date: str | None = None,
        stage: str | None = None,
        market: str | None = None,
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict:
        """Read the manager's exact HK_CONNECT stage lane only.

        The shared stage-center route remains a compatibility projection for
        its historical scheduled-market response.  This dedicated route is a
        narrower boundary for the manager consumer and never falls back to
        the unified or A-share lane.
        """
        if date is None:
            raise HTTPException(status_code=422, detail="date is required")
        selected = ctx.strict_date(date)
        if stage != "STAGE_0935_0940":
            raise HTTPException(status_code=422, detail="stage must be STAGE_0935_0940")
        if market != "HK_CONNECT":
            raise HTTPException(status_code=422, detail="market must be HK_CONNECT")
        if ctx.shared_selection_consumer is None:
            return unconfigured_selection(selected, stage)
        return project_shared_selection(ctx.projection,
            ctx.shared_selection_consumer.get(selected, stage, markets=("HK_CONNECT",)),
            limit,
        )

    @app.post("/api/v4/stage-center/selection/ensure")
    def shared_stage_selection_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = ctx.strict_date(date) if date is not None else ctx.catalog()["default_date"]
        if not selected:
            selected = ctx.catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if ctx.shared_selection_consumer is None:
            return unconfigured_selection(selected, stage)
        return project_shared_selection(ctx.projection,
            ctx.shared_selection_consumer.ensure(selected, stage, force=force),
            limit=200,
            ordinary_hk_display=True,
        )
