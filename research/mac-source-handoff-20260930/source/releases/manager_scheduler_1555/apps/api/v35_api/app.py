from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apps.api.v35_api.baimao_router import create_baimao_router
from apps.api.v35_api.research_lane_router import create_research_lane_router
from apps.api.v35_api.runtime_router import create_runtime_router
from apps.api.v35_api.runtime_graph_router import create_runtime_graph_router
from apps.api.v35_api.review_router import create_review_router
from apps.api.v35_api.research_router import create_research_router
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains.preselection import date_catalog, preselection
from domains.stage_input_producer import ReadOnlyQuoteProvider, StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.review_store import ReviewStore
from infrastructure.research_store import ResearchArchiveStore
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
from stage_center.consumer import StageSelectionConsumer


def _strict_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from error
    return value


def create_app(
    data_root: Path | None = None,
    quote_provider: ReadOnlyQuoteProvider | None = None,
    shared_data_root: Path | str | None = None,
    ledger_root: Path | None = None,
    stage_center_selection_root: Path | None = None,
    current_date: str | None = None,
) -> FastAPI:
    app = FastAPI(title="V3.5", version="0.1.0")
    store = NativeDataStore(data_root or Path.cwd() / ".runtime" / "data")
    review_store = ReviewStore(store.root)
    research_store = ResearchArchiveStore(store.root)
    configured_selection_root = stage_center_selection_root
    shared_selection_consumer = (
        StageSelectionConsumer(
            configured_selection_root,
            a_name_authority_root=store.root.parent / "research_panel_daily" / "receipts",
        )
        if configured_selection_root is not None
        else None
    )
    if shared_selection_consumer is None:
        stage_store = StageStore(store.root)
        resolved_quote_provider = quote_provider or StageQuoteProvider(
            primary=FutuQuoteProvider(),
            a_replay=TdxMinuteReplayProvider(),
            references=stage_store,
            hk_replay=HkConnectStageReplayProvider(),
        )
        stage_runner = StageRunner(
            stage_store,
            input_producer=StageInputProducer(
                store,
                stage_store,
                resolved_quote_provider,
            ),
            opening_second_filter_store=OpeningSecondFilterStore(store.root),
        )
    else:
        # Explicit shared-root mode is read-only: do not instantiate a quote
        # provider, input producer, or StageRunner writer path at all.
        stage_runner = None

    def shared_selection_unconfigured(trade_date: str, stage_id: str) -> dict:
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

    def _catalog() -> dict:
        return date_catalog(store, current_date=current_date)

    def project_shared_selection(payload: dict, limit: int = 50) -> dict:
        canonical_markets = payload.get("markets", {})
        frontend_markets: dict[str, dict] = {}
        unified_rows: list[dict] = []
        aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
        for canonical_market, market_payload in canonical_markets.items():
            alias = aliases.get(canonical_market, canonical_market)
            rows = list(market_payload.get("rows") or [])[:limit]
            frontend_markets[alias] = {
                key: market_payload.get(key)
                for key in (
                    "market",
                    "status",
                    "selection_status",
                    "artifact_id",
                    "run_id",
                    "algorithm_id",
                    "algorithm_sha256",
                    "raw_artifact_sha256",
                    "source_status",
                    "requested_rows",
                    "source_rows",
                    "selected_rows",
                    "coverage_ratio",
                    "missing_symbols",
                    "cannot_confirm",
                    "name_authority_status",
                    "name_authority_receipt_sha256",
                    "name_authority_selector_sha256",
                    "name_authority_selector_sha_source",
                    "name_authority_applied_count",
                    "name_authority_missing_count",
                    "name_authority_error",
                )
            }
            frontend_markets[alias]["candidate_count"] = len(rows)
            frontend_markets[alias]["rows"] = rows
            for row in rows:
                unified_rows.append(
                    {
                        **dict(row),
                        "market": alias,
                        "symbol": row.get("code"),
                        "selection_rank": row.get("rank"),
                    }
                )
        a_rows = frontend_markets.get("A", {}).get("rows", [])
        hk_rows = frontend_markets.get("HK", {}).get("rows", [])
        selected_a = len(a_rows)
        selected_hk = len(hk_rows)
        selected_total = selected_a + selected_hk
        stage_id = payload.get("stage_id")
        stage_definition = STAGE_DEFINITIONS.get(stage_id, {})
        stage_status = payload.get("status", "CANNOT_CONFIRM")
        return {
            **payload,
            "selection_markets": canonical_markets,
            "markets": frontend_markets,
            "market_summaries": frontend_markets,
            "unified_rows": unified_rows,
            "stage": {
                "stage_id": stage_id,
                "label": stage_definition.get("label", stage_id),
                "window": stage_definition.get("window", ""),
                "status": stage_status,
                "display_status": stage_status,
            },
            "selected_a_rows": selected_a,
            "selected_hk_rows": selected_hk,
            "selected_total_rows": selected_total,
            "selection_mode": "SHARED_STAGE_CENTER_READ_ONLY",
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, bool]:
        return dict(TRADING_SAFETY_FLAGS)

    @app.get("/api/v3/meta/stages")
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
        requested = _strict_date(date) if date is not None else None
        response = {
            **_catalog(),
            "review_dates": review_store.list_dates(),
            "research_dates": research_store.list_dates(),
        }
        response["requested_date"] = requested
        response["selected_date"] = requested or response["default_date"] or response["system_date"]
        return response

    @app.get("/api/v3/preselection-pools")
    def preselection_pools(date: str | None = None, limit: int = Query(default=200, ge=1, le=300)) -> dict:
        requested = _strict_date(date) if date is not None else None
        catalog = _catalog()
        selected = requested or catalog["default_date"] or catalog["system_date"]
        response = preselection(store, selected, limit)
        response["requested_date"] = requested
        response["selected_date"] = selected
        return response

    @app.get("/api/v3/workbench/stage")
    def stage_workbench(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is not None:
            return project_shared_selection(shared_selection_consumer.get(selected, stage), limit)
        return stage_runner.read_workbench(selected, stage, limit)

    @app.post("/api/v3/workbench/stage/ensure")
    def stage_workbench_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is not None:
            return project_shared_selection(
                shared_selection_consumer.ensure(selected, stage, force=force),
                limit=50,
            )
        return stage_runner.ensure(selected, stage, force=force)

    @app.get("/api/v3/stage-center/selection")
    def shared_stage_selection(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(shared_selection_consumer.get(selected, stage), limit)

    @app.post("/api/v3/stage-center/selection/ensure")
    def shared_stage_selection_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(shared_selection_consumer.ensure(selected, stage, force=force), limit=200)

    app.include_router(
        create_runtime_router(
            store.root,
            ledger_root=ledger_root,
            stage_selection_root=configured_selection_root,
            current_date=current_date,
        )
    )
    app.include_router(create_runtime_graph_router(store.root))
    app.include_router(create_review_router(store.root))
    app.include_router(create_research_router(store.root))

    # Research is an owned V3.5 read-only slice.  Register the compatibility
    # routes unconditionally so a caller does not need the removed V3 module
    # roots or the legacy router signature.  Missing archives remain typed
    # NOT_MATERIALIZED responses from the owned stores.
    app.include_router(create_baimao_router(store.root))
    app.include_router(
        create_research_lane_router(
            store.root,
            shared_data_root=shared_data_root,
        )
    )

    preview_root = Path(__file__).resolve().parents[2] / "web" / "preview"
    if preview_root.is_dir():
        app.mount("/preview", StaticFiles(directory=preview_root, html=True), name="preview")

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app
