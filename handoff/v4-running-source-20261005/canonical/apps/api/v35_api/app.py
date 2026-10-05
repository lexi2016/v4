from datetime import datetime
import importlib
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apps.api.v35_api.baimao_router import create_baimao_router
from apps.api.v35_api.manager_research_router import create_manager_research_router
from apps.api.v35_api.manager_workbench_router import create_manager_workbench_router, ManagerWorkbenchResearchReader
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
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
from stage_center.consumer import StageSelectionConsumer


_MANAGER_RESEARCH_RUNTIME_PACKAGE = "_v4_manager_research_runtime"
_V35_STATE_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v35.local"
    / "state"
)
_CANONICAL_MANAGER_RESEARCH_STATE_ROOT = _V35_STATE_ROOT / "manager_auto_research"


def _resolve_manager_research_state_root(
    manager_research_state_root: Path | str | None,
    data_root: Path | str | None,
) -> Path:
    """Resolve the manager lane below its one canonical state root.

    ``V35_DATA_ROOT`` points at the shared host data tree and is also passed as
    ``data_root`` by the live launcher.  The manager product has its own
    sibling state directory, so that host argument must not become a nested
    manager store.  A noncanonical explicit data root remains isolated for
    embedded tests and callers; the dedicated manager argument and env
    override always take precedence.
    """

    if manager_research_state_root is not None:
        return Path(manager_research_state_root)
    env_state_root = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    if env_state_root:
        return Path(env_state_root)
    if data_root is not None:
        explicit_data_root = Path(data_root).expanduser()
        if explicit_data_root.resolve() == (_V35_STATE_ROOT / "data").resolve():
            return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT
        return explicit_data_root / "manager_auto_research"
    return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT


class _RevalidatingStaticFiles(StaticFiles):
    """Serve HTML entry points with revalidation, hashed assets as usual.

    A cached HTML document can reference a hashed asset that a later release
    no longer ships, so documents must be revalidated (``no-cache``) instead
    of being served from heuristic freshness; content-hashed assets keep
    their default caching because their names change with their bytes.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["cache-control"] = "no-cache"
        return response


def _load_manager_research_components() -> tuple[type[Any], type[Any], type[Any], type[Any]]:
    """Load only the independent manager package from its own directory.

    The live host may receive ``v4/manager_research`` without the historical
    V4 Gate 0 package.  Importing ``v4.manager_research`` in that layout would
    execute a parent ``v4/__init__.py`` and pull unrelated gate modules into
    the host.  A private package alias keeps relative imports inside the
    manager package intact while making its minimal closure explicit.
    """

    loaded = sys.modules.get(_MANAGER_RESEARCH_RUNTIME_PACKAGE)
    if loaded is not None:
        return (
            loaded.ManagerResearchJobService,
            loaded.ManagerResearchStore,
            loaded.HkexOfficialProvider,
            loaded.MaterialStore,
        )
    package_dir = Path(__file__).resolve().parents[3] / "v4" / "manager_research"
    init_path = package_dir / "__init__.py"
    if not init_path.is_file():
        raise RuntimeError(f"independent manager research package is missing: {init_path}")
    spec = importlib.util.spec_from_file_location(
        _MANAGER_RESEARCH_RUNTIME_PACKAGE,
        init_path,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create independent manager research package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MANAGER_RESEARCH_RUNTIME_PACKAGE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_MANAGER_RESEARCH_RUNTIME_PACKAGE, None)
        raise
    return (
        module.ManagerResearchJobService,
        module.ManagerResearchStore,
        module.HkexOfficialProvider,
        module.MaterialStore,
    )


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
    manager_research_state_root: Path | str | None = None,
    manager_research_observation_reader: Any | None = None,
    manager_research_source_provider: Any | None = None,
    research_data_root: Path | str | None = None,
    research_ledger_root: Path | str | None = None,
    morning_news_data_root: Path | str | None = None,
    preselection_source_root: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(title="V3.5", version="0.1.0")
    store = NativeDataStore(data_root or Path.cwd() / ".runtime" / "data")
    review_store = ReviewStore(store.root)
    configured_research_root = research_data_root or os.environ.get("V35_RESEARCH_DATA_ROOT")
    resolved_research_root = Path(configured_research_root).expanduser() if configured_research_root else store.root
    configured_pool_source = (
        preselection_source_root or os.environ.get("V35_PRESELECTION_SOURCE_ROOT")
    )
    resolved_pool_source = (
        Path(configured_pool_source).expanduser()
        if configured_pool_source
        else store.root
    )
    configured_morning_news_root = (
        morning_news_data_root or os.environ.get("V35_MORNING_NEWS_DATA_ROOT")
    )
    configured_research_ledger = research_ledger_root
    if configured_research_ledger:
        resolved_research_ledger = Path(configured_research_ledger).expanduser()
    elif ledger_root is not None and not configured_research_root:
        # Preserve the existing single-root application contract for callers
        # that have not configured a separate research producer root.
        resolved_research_ledger = Path(ledger_root).expanduser()
    else:
        resolved_research_ledger = resolved_research_root.parent / "dispatcher"
    research_source = ResearchLaneSource(
        resolved_research_root,
        ledger_root=resolved_research_ledger,
    )
    configured_selection_root = stage_center_selection_root
    shared_selection_consumer = (
        StageSelectionConsumer(
            configured_selection_root,
            a_name_pool_root=resolved_pool_source,
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
        return date_catalog(
            store,
            current_date=current_date,
            stage_selection_root=configured_selection_root,
        )

    def _stage_projection_status(
        markets: Mapping[str, Mapping[str, Any]],
        fallback: Any,
    ) -> str:
        """Reduce market statuses without hiding a lane-level evidence gap."""
        statuses = {str(item.get("status") or "CANNOT_CONFIRM") for item in markets.values()}
        has_rows = any(int(item.get("selected_rows") or item.get("candidate_count") or 0) > 0 for item in markets.values())
        if not statuses:
            return str(fallback or "CANNOT_CONFIRM")
        if statuses == {"READY"}:
            return "READY"
        if statuses == {"READY_EMPTY"}:
            return "READY_EMPTY"
        if "CANNOT_CONFIRM" in statuses:
            return "PARTIAL_WITH_ROWS" if has_rows else "CANNOT_CONFIRM"
        if "PARTIAL_WITH_ROWS" in statuses or str(fallback) == "PARTIAL_WITH_ROWS":
            return "PARTIAL_WITH_ROWS"
        return str(fallback or "PARTIAL_WITH_ROWS")

    def _hk_display_mode(
        market_payload: Mapping[str, Any],
        rows: list[dict],
        execution_market: Mapping[str, Any] | None,
    ) -> tuple[str, list[str]]:
        """Only call HK rows formal after selection and execution binding agree."""
        status = str(market_payload.get("status") or "CANNOT_CONFIRM")
        selection_status = str(market_payload.get("selection_status") or status)
        reasons = [str(item) for item in market_payload.get("cannot_confirm") or []]
        identity_present = all(
            isinstance(market_payload.get(field), str) and market_payload.get(field)
            for field in ("artifact_id", "run_id", "raw_artifact_sha256")
        )
        requested_rows = market_payload.get("requested_rows")
        source_rows = market_payload.get("source_rows")
        selected_rows = market_payload.get("selected_rows")
        source_evidence = market_payload.get("source_evidence")
        complete_empty_evidence = (
            isinstance(requested_rows, int)
            and not isinstance(requested_rows, bool)
            and requested_rows >= 0
            and isinstance(source_rows, int)
            and not isinstance(source_rows, bool)
            and source_rows == requested_rows
            and isinstance(selected_rows, int)
            and not isinstance(selected_rows, bool)
            and selected_rows == 0
            and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
            and isinstance(source_evidence, (list, tuple))
            and any(isinstance(item, str) and item.strip() for item in source_evidence)
            and not market_payload.get("missing_symbols")
            and not market_payload.get("cannot_confirm")
        )
        verified_empty = (
            status == "READY_EMPTY"
            and selection_status == "READY_EMPTY"
            and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
            and identity_present
            and not rows
            and complete_empty_evidence
            and not reasons
        )
        if verified_empty:
            return "READY_EMPTY", []

        if status == "READY_EMPTY":
            if not complete_empty_evidence:
                reasons.append("HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE")
            if market_payload.get("source_status") not in {"READY", "READY_EMPTY"}:
                reasons.append("HK_READY_EMPTY_SOURCE_STATUS_NOT_READY")
            if selection_status != "READY_EMPTY":
                reasons.append("HK_READY_EMPTY_SELECTION_STATUS_MISMATCH")
            if not identity_present:
                reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
            return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

        if status == "CANNOT_CONFIRM" or not identity_present:
            if not reasons:
                reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
            return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), reasons

        execution = execution_market if isinstance(execution_market, Mapping) else {}
        binding = execution.get("selection_binding")
        unsafe_rows = any(
            isinstance(row, Mapping) and row.get("formal_eligible") is False
            for row in rows
        )
        selection_ready = (
            status == "READY"
            and selection_status == "READY"
            and not reasons
        )
        execution_bound = binding == "BOUND_TO_VERIFIED_SELECTION"
        if selection_ready and execution_bound and rows and not unsafe_rows:
            return "FORMAL", []

        if selection_ready and not rows:
            reasons.append("HK_READY_SELECTION_HAS_NO_ROWS")

        if unsafe_rows:
            reasons.append("HK_FORMAL_ELIGIBILITY_FALSE")
        if not execution_bound:
            execution_reasons = execution.get("reasons")
            reasons.extend(str(item) for item in execution_reasons or [])
            reasons.append(f"HK_EXECUTION_SELECTION_BINDING_{binding or 'CANNOT_CONFIRM'}")
        if not selection_ready:
            reasons.append(f"HK_SELECTION_STATUS_{status}")
        return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), list(dict.fromkeys(reasons))

    def project_shared_selection(
        payload: dict,
        limit: int = 50,
        *,
        ordinary_hk_display: bool = False,
    ) -> dict:
        canonical_markets = payload.get("markets", {})
        frontend_markets: dict[str, dict] = {}
        unified_rows: list[dict] = []
        aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
        execution_markets = (
            (payload.get("execution_evidence") or {}).get("markets") or {}
        )
        backfill_provenance_fields = frozenset(
            {
                "selection_mode",
                "backfill_run_id",
                "backfill_run_ids",
                "selection_manifest_sha256",
                "selection_receipt_sha256",
                "selection_artifact_sha256",
                "selection_manifest_receipt_verified",
                "runner_receipt_verified",
                "runner_receipt_status",
                "runner_receipt_sha256",
                "recovery_provenance",
            }
        )
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
                    "source_evidence",
                    "missing_symbols",
                    "cannot_confirm",
                    "name_authority_status",
                    "name_authority_source",
                    "name_authority_receipt_sha256",
                    "name_authority_selector_sha256",
                    "name_authority_source_sha256",
                    "name_authority_selector_sha_source",
                    "name_authority_pool_ids",
                    "name_authority_applied_count",
                    "name_authority_missing_count",
                    "name_authority_error",
                    "selection_mode",
                    "backfill_run_id",
                    "backfill_run_ids",
                    "selection_manifest_sha256",
                    "selection_receipt_sha256",
                    "selection_artifact_sha256",
                    "selection_manifest_receipt_verified",
                    "runner_receipt_verified",
                    "runner_receipt_status",
                    "runner_receipt_sha256",
                    "recovery_provenance",
                )
                if key not in backfill_provenance_fields or key in market_payload
            }
            frontend_markets[alias]["candidate_count"] = len(rows)
            frontend_markets[alias]["rows"] = rows
            if canonical_market == "HK_CONNECT" and ordinary_hk_display:
                display_mode, display_reasons = _hk_display_mode(
                    market_payload, rows, execution_markets.get(canonical_market)
                )
                frontend_markets[alias]["display_mode"] = display_mode
                frontend_markets[alias]["display_reasons"] = display_reasons
                frontend_markets[alias]["observation_count"] = len(rows)
                if display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}:
                    frontend_markets[alias]["candidate_count"] = None
                    frontend_markets[alias]["status"] = (
                        "PARTIAL_WITH_ROWS" if display_mode == "OBSERVATION_UNVERIFIED" else "CANNOT_CONFIRM"
                    )
                    frontend_markets[alias]["selected_rows"] = None
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
        hk_display_mode = frontend_markets.get("HK", {}).get("display_mode")
        selected_hk = (
            None if hk_display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}
            else len(hk_rows)
        )
        selected_total = None if selected_hk is None else selected_a + selected_hk
        stage_id = payload.get("stage_id")
        stage_definition = STAGE_DEFINITIONS.get(stage_id, {})
        stage_status = _stage_projection_status(frontend_markets, payload.get("status", "CANNOT_CONFIRM"))
        cannot_confirm: list[str] = [str(item) for item in payload.get("cannot_confirm") or []]
        for market, market_payload in frontend_markets.items():
            market_status = str(market_payload.get("status") or "CANNOT_CONFIRM")
            reasons = list(market_payload.get("cannot_confirm") or ())
            if market == "HK":
                reasons.extend(market_payload.get("display_reasons") or ())
                reasons = list(dict.fromkeys(reasons))
            if not reasons and market_status == "CANNOT_CONFIRM":
                reasons = [f"{market}_SELECTION_CANNOT_CONFIRM"]
            # A lane can have rows and still carry a hard evidence boundary.
            # Keep every lane reason visible at the stage boundary; the
            # status reducer above deliberately remains PARTIAL_WITH_ROWS.
            for reason in reasons:
                value = f"{market}:{reason}"
                if value not in cannot_confirm:
                    cannot_confirm.append(value)
        return {
            **payload,
            "status": stage_status,
            "selection_markets": canonical_markets,
            "markets": frontend_markets,
            "market_summaries": frontend_markets,
            "unified_rows": unified_rows,
            "cannot_confirm": cannot_confirm,
            "stage": {
                "stage_id": stage_id,
                "label": stage_definition.get("label", stage_id),
                "window": stage_definition.get("window", ""),
                "status": stage_status,
                "display_status": stage_status,
                "cannot_confirm": cannot_confirm,
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
            "research_dates": research_source.list_dates(),
            "research_source": research_source.binding(),
        }
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

    @app.get("/api/v3/preselection-pools")
    def preselection_pools(
        date: str | None = None,
        limit: int = Query(default=200, ge=1, le=300),
        offset: int = Query(default=0, ge=0),
        page: int | None = Query(default=None, ge=1),
    ) -> dict:
        requested = _strict_date(date) if date is not None else None
        catalog = _catalog()
        selected = requested or catalog["default_date"] or catalog["system_date"]
        page_offset = (page - 1) * limit if page is not None else offset
        response = preselection(store, selected, limit, offset=page_offset)
        response["requested_date"] = requested
        response["selected_date"] = selected
        response["page"] = page if page is not None else (page_offset // limit) + 1
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
            return project_shared_selection(
                shared_selection_consumer.get(selected, stage, allow_backfill=True),
                limit,
                ordinary_hk_display=True,
            )
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
                ordinary_hk_display=True,
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
        return project_shared_selection(
            shared_selection_consumer.get(selected, stage),
            limit,
            ordinary_hk_display=True,
        )

    @app.get("/api/v3/manager/stage-selection")
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
        selected = _strict_date(date)
        if stage != "STAGE_0935_0940":
            raise HTTPException(status_code=422, detail="stage must be STAGE_0935_0940")
        if market != "HK_CONNECT":
            raise HTTPException(status_code=422, detail="market must be HK_CONNECT")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(
            shared_selection_consumer.get(selected, stage, markets=("HK_CONNECT",)),
            limit,
        )

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
        return project_shared_selection(
            shared_selection_consumer.ensure(selected, stage, force=force),
            limit=200,
            ordinary_hk_display=True,
        )

    app.include_router(
        create_runtime_router(
            store.root,
            ledger_root=ledger_root,
            stage_selection_root=configured_selection_root,
            current_date=current_date,
        )
    )
    app.include_router(create_runtime_graph_router(store.root))
    app.include_router(create_review_router(
        store.root,
        review_root=os.environ.get("V4_DAILY_REVIEW_ROOT"),
        generation_bindings_path=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_PATH"),
        generation_bindings_sha256=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_SHA256"),
        intraday_root=os.environ.get("V4_INTRADAY_RESEARCH_ROOT"),
    ))
    app.include_router(
        create_research_router(
            store.root,
            # Legacy article/day/hourly GETs use the same explicit producer
            # binding as the decision-desk lane; selection/materialization
            # ownership stays on the V4 consumer root inside the router.
            research_read_root=resolved_research_root,
            wechat_archive_root=os.environ.get("V4_WECHAT_ARCHIVE_ROOT"),
        )
    )

    # Research is an owned V3.5 read-only slice.  Register the compatibility
    # routes unconditionally so a caller does not need the removed V3 module
    # roots or the legacy router signature.  Missing archives remain typed
    # NOT_MATERIALIZED responses from the owned stores.
    app.include_router(create_baimao_router(store.root))
    app.include_router(
        # Only the GET-only research decision-desk lane consumes the explicit
        # producer root.  The legacy-compatible research router above keeps
        # its V4 store root for any materialization/write owner.
        create_research_lane_router(
            resolved_research_root,
            shared_data_root=shared_data_root,
            morning_news_data_root=configured_morning_news_root,
            ledger_root=resolved_research_ledger,
            # US digest already writes the native data store.  Do not move the
            # independent research lane, morning news or external-news reader.
            us_market_data_root=store.root,
        )
    )

    # V4 manager research is a separate date/input keyed job lane.  This
    # adapter only reads the already materialized HK_CONNECT stage response;
    # it never instantiates a V3 producer or accepts browser supplied rows.
    if manager_research_observation_reader is None:
        class _SharedManagerObservationReader:
            def read(self, target_trade_date: str) -> Mapping[str, Any]:
                if shared_selection_consumer is None:
                    return shared_selection_unconfigured(target_trade_date, "STAGE_0935_0940")
                return project_shared_selection(
                    shared_selection_consumer.get(
                        target_trade_date,
                        "STAGE_0935_0940",
                        markets=("HK_CONNECT",),
                    ),
                    limit=50,
                )

        manager_research_observation_reader = _SharedManagerObservationReader()
    resolved_manager_research_state_root = _resolve_manager_research_state_root(
        manager_research_state_root,
        data_root,
    )
    (
        manager_research_job_service,
        manager_research_store,
        hkex_official_provider,
        manager_material_store_class,
    ) = _load_manager_research_components()
    # One shared material store backs every manager research fetch lane: the
    # same URL is retrieved once and reused across official PDFs, media events,
    # and the public reader (cached parses included) until its TTL expires.
    manager_material_store = manager_material_store_class(
        Path(resolved_manager_research_state_root) / "materials"
    )
    if manager_research_source_provider is not None:
        manager_research_provider = manager_research_source_provider
    else:
        manager_research_provider = hkex_official_provider(material_store=manager_material_store)
    manager_bridge = importlib.import_module(
        f"{_MANAGER_RESEARCH_RUNTIME_PACKAGE}.us_market_bridge"
    )
    manager_us_market_reader = manager_bridge.ResearchPeripheralUsMarketReader(store.root)
    manager_research_service = manager_research_job_service(
        manager_research_store(resolved_manager_research_state_root),
        manager_research_observation_reader,
        manager_research_provider,
        existing_research_source=research_source,
        close_observation_reader=ManagerWorkbenchResearchReader(resolved_manager_research_state_root),
        workspace_ledger_root=Path(ledger_root) if ledger_root is not None else None,
        workspace_security_master_root=(Path(os.environ["V4_MANAGER_SECURITY_MASTER_ROOT"])
            if os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") else
            (Path(shared_data_root) if shared_data_root is not None else None)),
        workspace_screen_authority_root=(Path(os.environ["V4_MANAGER_SCREEN_AUTHORITY_ROOT"])
            if os.environ.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT") else
            (Path(os.environ["V4_MANAGER_SECURITY_MASTER_ROOT"])
             if os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") else
             (Path(shared_data_root) if shared_data_root is not None else None))),
        material_store=manager_material_store,
        catalyst_data_root=(Path(os.environ["V4_MANAGER_NEWS_DATA_ROOT"])
                            if os.environ.get("V4_MANAGER_NEWS_DATA_ROOT") else store.root),
        catalyst_news_owner_root=(Path(os.environ["V4_MANAGER_NEWS_OWNER_ROOT"])
                                  if os.environ.get("V4_MANAGER_NEWS_OWNER_ROOT") else None),
        workspace_us_market_reader=manager_us_market_reader,
    )
    app.state.manager_research_service = manager_research_service
    app.include_router(create_manager_research_router(manager_research_service))
    app.include_router(create_manager_workbench_router(resolved_manager_research_state_root))

    preview_root = Path(__file__).resolve().parents[2] / "web" / "preview"
    if preview_root.is_dir():
        app.mount("/preview", StaticFiles(directory=preview_root, html=True), name="preview")

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=dist, html=True), name="web")

    return app
