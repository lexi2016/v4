"""Background orchestration for the independent manager research product."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import os
from uuid import uuid4
import threading
import time
from typing import Any, Callable, Mapping

from .contracts import (
    FOUR_FLAGS,
    JOB_SCHEMA_VERSION,
    PRODUCT_SCHEMA_VERSION,
    ContractError,
    cutoff_at as contract_cutoff_at,
    normalise_observation_input,
    sha256_json,
    strict_trade_date,
)
from .event_source import (
    EVENT_FOCUS_WINDOW_DAYS,
    EVENT_SCHEMA_VERSION,
    _EVENT_BODY_STRONG_TOKENS,
    _classify_hkex_business_clause,
    _is_routine_hkex_event_title,
    build_catalyst_advice,
    event_is_focus_eligible,
)
from .ports import ObservationReader, ResearchSourceProvider
from .reader_source import read_public_news_batch
from .recommendation import (
    RECOMMENDATION_SCHEMA_VERSION,
    assign_investment_priorities,
    build_research_recommendation,
    derive_investment_advice,
    extract_financial_evidence,
    recommendation_summary,
)
from .store import ManagerResearchStore, StoreConflict, StoreError
from .cache_contract import validate_cached_product
from .errors import public_error
from .safety import assert_manager_safe_tree

# Compatibility re-exports: existing imports keep working without I/O coupling.
from .financial_projection import (
    _usable_fact,
    _has_researchable_fact_set,
    _fact_value,
    _fact_label_cn,
    _is_adjusted_fact,
    _financial_rows,
    _raw_decimal,
    _financial_value_map,
    _first_financial,
    _first_financial_with_adjustment,
    _is_aggregate_revenue_label,
    _label_matches,
    _is_statutory_result_label,
    _financial_values,
    _comparison_columns,
    _amount_text,
    _period_short,
    _change_text,
    _financial_summary_sentence,
    _build_research_sections,
    _financial_counterevidence_for_row,
    _PDF_PAGE_LOCATOR_RE,
    _PRIMARY_FINANCIAL_TOKENS,
    _REVENUE_COMPONENT_TOKENS,
    _SERVICE_CURRENCY_CN,
    _SERVICE_UNIT_CN,
    _STATUTORY_ATTRIBUTABLE_RE,
    _STATUTORY_EXCLUDED_LABEL_RE,
    _STATUTORY_RESULT_RE,
    _STATUTORY_RESULT_TOKENS,
    _STRUCTURED_FACT_KINDS,
)
from .catalyst_projection import (
    _cached_event_semantic_class,
    _cached_event_requires_semantic_downgrade,
    _downgrade_cached_event,
    _assign_catalyst_focus_ranks,
    _project_cached_catalysts,
    _CACHED_EVENT_LEGAL_TOKENS,
)


SAFE_DECISION = "暂不买入，等待验证"
SAFE_CANNOT_DECISION = "暂不买入，补充研究不可确认"
# The public web contract remains v2 for the frozen frontend.  This revision
# is the backend cache boundary for R3: newly written products carry it, while
# legacy products that show either a revenue-component headline or an annual
# report are invalidated and must be re-collected.
CONTENT_CONTRACT_VERSION = "v2.pypdf-6.10.0-structured-cn"
CONTENT_CONTRACT_REVISION = "r3.aggregate-report-bound.latest-report-fail-closed"


def _current_product(product: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Reject products made by the pre-R1 excerpt parser.

    The date/input path remains the same, but a content parser change is an
    explicit cache boundary.  Returning ``None`` here makes the next GET
    expose the old job as retryable and prevents a stale English fragment from
    reaching the UI.
    """

    if not isinstance(product, Mapping) or product.get("content_contract_version") != CONTENT_CONTRACT_VERSION:
        return None
    if product.get("content_contract_revision") == CONTENT_CONTRACT_REVISION:
        return dict(product)
    if product.get("content_contract_revision") in {None, ""} and not _legacy_product_requires_r3_refresh(product):
        # Preserve unaffected R2 products so R3 can refresh only the dates
        # whose actual source selection/content is affected.  Products with
        # the two discovered generic failure shapes are rejected below.
        return dict(product)
    return None


def _legacy_product_requires_r3_refresh(product: Mapping[str, Any]) -> bool:
    rows = product.get("rows")
    if not isinstance(rows, list):
        return True
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") != "READY":
            continue
        source = row.get("source")
        title = str(source.get("document_title", "")) if isinstance(source, Mapping) else ""
        # An old annual/final report may have hidden a newer effective interim
        # report.  Re-run it through the report-period binding before showing
        # it again, without hardcoding an issuer or date.
        if re.search(r"\b(?:annual|final)\s+results\b", title, flags=re.IGNORECASE):
            return True
        facts = row.get("facts")
        if not isinstance(facts, list):
            continue
        financial = [fact for fact in facts if isinstance(fact, Mapping) and fact.get("fact_kind") == "financial"]
        revenue_rows = [
            fact
            for fact in financial
            if _label_matches(_fact_value(fact, "label").lower(), "revenue")
        ]
        if revenue_rows and not any(_is_aggregate_revenue_label(_fact_value(fact, "label")) for fact in revenue_rows):
            return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_v2_recommendation(value: Any) -> bool:
    if not isinstance(value, Mapping) or value.get("schema_version") != RECOMMENDATION_SCHEMA_VERSION:
        return False
    return (
        isinstance(value.get("investment_advice"), Mapping)
        and isinstance(value.get("execution_gate"), Mapping)
        and isinstance(value.get("as_of"), Mapping)
        and isinstance(value.get("evidence"), Mapping)
    )


def _row_date_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()[:10].replace("-", "")
    return token if re.fullmatch(r"20\d{6}", token) else None


def _empty_catalyst_row(
    code: str,
    *,
    status: str = "CANNOT_CONFIRM",
    reason: str = "EVENT_SOURCE_NOT_RUN",
) -> dict[str, Any]:
    """Keep event coverage explicit when the independent event lane is absent."""

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "events": [],
        "historical_events": [],
        "current_events": [],
        "catalyst_advice": {
            "status": "CANNOT_CONFIRM",
            "label": "CANNOT_CONFIRM（催化）",
            "priority_rank": None,
            "priority_reason": "催化来源尚未运行；不把财报或行情字段当作事件证据。",
            "summary": "事件、财务意见和执行门保持分开。",
        },
        "source_coverage": [],
        "source_receipts": [],
        "coverage": {
            "requested_candidates": 1,
            "source_count": 0,
            "historical_event_count": 0,
            "current_event_count": 0,
            "no_match_is_not_complete": True,
            "completeness": "EVENT_SOURCE_NOT_RUN",
        },
        "current_event_as_of": None,
        "financial_counterevidence": [],
        "market_confirmation_gap": ["EVENT_SOURCE_NOT_RUN"],
        "code": code,
    }


def _reader_materials(bundle: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return the bounded reader rows in display order, without classification."""

    if not isinstance(bundle, Mapping):
        return []
    materials: list[dict[str, Any]] = []
    for key in ("materials", "company_news", "background"):
        values = bundle.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, Mapping):
                materials.append(dict(item))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in materials:
        key = str(item.get("id") or item.get("source_url") or item.get("title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(item)
    result.sort(key=lambda item: (str(item.get("published_at") or ""), str(item.get("id") or "")), reverse=True)
    return result


def _attach_reader_batch(
    event_batch: Mapping[str, Any],
    reader_batch: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach source material to each exact row while keeping event semantics separate."""

    updated = dict(event_batch)
    raw_rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
    reader_rows = reader_batch.get("rows") if isinstance(reader_batch.get("rows"), Mapping) else {}
    rows: dict[str, dict[str, Any]] = {}
    for observation in observations:
        code = str(observation.get("code") or "")
        base = raw_rows.get(code) if isinstance(raw_rows, Mapping) else None
        row = dict(base) if isinstance(base, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
        bundle = reader_rows.get(code) if isinstance(reader_rows, Mapping) else None
        bundle_copy = dict(bundle) if isinstance(bundle, Mapping) else {
            "schema": "v4.manager_research.material_reader.v1",
            "status": "CANNOT_CONFIRM",
            "code": code,
            "name": observation.get("name"),
            "source_gaps": ["PUBLIC_NEWS_ROW_MISSING"],
            "materials": [],
            "company_news": [],
            "background": [],
        }
        display_materials = _reader_materials(bundle_copy)
        row["reader_bundle"] = bundle_copy
        row["reader_materials"] = display_materials
        row["reader_status"] = bundle_copy.get("status", "CANNOT_CONFIRM")
        row["reader_source_gaps"] = list(bundle_copy.get("source_gaps") or []) if isinstance(bundle_copy.get("source_gaps"), list) else []
        rows[code] = row
    updated["rows"] = rows
    source_count = reader_batch.get("source_counts")
    if isinstance(source_count, Mapping):
        updated["reader_source_counts"] = [dict(source_count)]
    else:
        updated["reader_source_counts"] = []
    reader_coverage = dict(reader_batch.get("coverage")) if isinstance(reader_batch.get("coverage"), Mapping) else {
        "status": "CANNOT_CONFIRM",
        "completeness": "BOUNDED_FIXED_CANDIDATE_PUBLIC_NEWS",
    }
    updated["reader_coverage"] = reader_coverage
    updated["reader_current_as_of"] = reader_batch.get("queried_at") or _now()
    coverage = dict(updated.get("coverage")) if isinstance(updated.get("coverage"), Mapping) else {}
    coverage.update({
        "reader_material_count": sum(len(row.get("reader_materials", [])) for row in rows.values()),
        "reader_candidate_count": sum(1 for row in rows.values() if row.get("reader_materials")),
        "reader_status": reader_batch.get("status", "CANNOT_CONFIRM"),
        "reader_coverage": reader_coverage,
        "full_day_coverage": "NOT_VERIFIED",
        "no_material_is_not_no_candidate": True,
    })
    updated["coverage"] = coverage
    reader_material_count = int(coverage.get("reader_material_count") or 0)
    if reader_material_count and str(updated.get("status") or "").upper() == "CANNOT_CONFIRM":
        # The event source may be unavailable while the independent reader is
        # healthy.  Preserve the per-source gap and expose the partial product.
        updated["status"] = "PARTIAL_WITH_ROWS"
        updated["reason"] = "PUBLIC_NEWS_READER_AVAILABLE_EVENT_SOURCE_PARTIAL"
    return updated


class ManagerResearchJobService:
    """Own job state, deduplication and product assembly.

    A job's identity is ``target_trade_date + input_identity``.  The service
    never accepts a symbol list from the HTTP client; the injected observer is
    the only source of the fixed stage rows.
    """

    def __init__(
        self,
        store: ManagerResearchStore,
        observation_reader: ObservationReader | Callable[[str], Mapping[str, Any]] | None,
        source_provider: ResearchSourceProvider | Callable[..., Mapping[str, Any]] | None,
        *,
        max_workers: int = 4,
        row_timeout_seconds: float = 45.0,
        reader_fetcher: Callable[..., Any] | None = None,
        max_pending_jobs: int = 16,
        material_store: Any | None = None,
        catalyst_data_root: Path | None = None,
        catalyst_news_owner_root: Path | None = None,
        existing_research_source: Any | None = None,
        close_observation_reader: Any | None = None,
        workspace_ledger_root: Path | None = None,
        workspace_security_master_root: Path | None = None,
        workspace_screen_authority_root: Path | None = None,
        workspace_us_market_reader: Any | None = None,
    ) -> None:
        self.store = store
        self._instance_id = uuid4().hex
        self.max_pending_jobs = max(1, int(max_pending_jobs))
        self.observation_reader = observation_reader
        self.source_provider = source_provider
        self.row_timeout_seconds = max(1.0, float(row_timeout_seconds))
        # Only the production HKEX provider opts into the external public-news
        # reader.  Fixture providers remain fully offline unless a test passes
        # an explicit fetcher, so event tests never make accidental requests.
        self.reader_fetcher = reader_fetcher
        # A shared material store turns the public reader into a fetch-once
        # lane too: the same bounded search response is reused across jobs
        # until its TTL expires instead of being requested again.
        self._material_store = material_store
        self._catalyst_data_root = catalyst_data_root
        self._catalyst_news_owner_root = catalyst_news_owner_root
        self._existing_research_source = existing_research_source
        self._close_observation_reader = close_observation_reader
        self._workspace_ledger_root = workspace_ledger_root
        self._workspace_security_master_root = workspace_security_master_root
        self._workspace_screen_authority_root = workspace_screen_authority_root
        self._workspace_us_market_reader = workspace_us_market_reader
        self._material_reader_fetcher: Callable[..., Any] | None = None
        if material_store is not None and reader_fetcher is None:
            from .reader_source import material_reader_fetcher

            self._material_reader_fetcher = material_reader_fetcher(material_store)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="manager-research")
        # Shared across jobs: timeouts must not create a fresh set of
        # unbounded stranded provider threads on every retry. Running calls
        # cannot be killed by Python; their own transport timeout still applies.
        self._row_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="manager-research-row")
        self._active: dict[str, Future[Any]] = {}
        self._cancelled: set[tuple[str, Any]] = set()
        self._active_generations: dict[str, str] = {}
        self._closed = False
        from .workspace_read_control import ProjectionMemo, ReadCoordinator
        self._workspace_projection_memo = ProjectionMemo()
        self._workspace_reads = ReadCoordinator()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)
        self._row_executor.shutdown(wait=False, cancel_futures=True)

    def admit_catalyst_materials(self, bundle_path: Path, *, expected_sha256: str) -> dict[str, Any]:
        from .catalyst_observations import admit
        return admit(self.store, self._material_store, bundle_path, expected_sha256=expected_sha256)

    def get_catalyst_observations(self, target_trade_date: str) -> dict[str, Any]:
        from .catalyst_observations import read
        return read(self.store, self._material_store, target_trade_date,
                    data_root=self._catalyst_data_root, owner_root=self._catalyst_news_owner_root,
                    archive_source=self._existing_research_source,security_master_root=self._workspace_security_master_root)

    def refresh_catalyst_observations(self, target_trade_date: str) -> dict[str, Any]:
        from .workspace import refresh_with_tracking
        return refresh_with_tracking(self, target_trade_date)

    def get_workspace(self, target_trade_date: str, *, view: str = "dynamic",
                      now: datetime | None = None, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        # Legacy internal callers retain dynamic semantics. The browser GET
        # explicitly supplies auto (historical for past HK dates).
        from .workspace import get_workspace
        target_trade_date = strict_trade_date(target_trade_date)
        if view not in {"auto", "historical", "dynamic"}:
            raise ValueError("WORKSPACE_VIEW_INVALID")
        key = (target_trade_date, view, now.isoformat() if now is not None else "SERVER_CLOCK")
        return self._workspace_reads.run(key,
            lambda: get_workspace(self, target_trade_date, view=view, now=now), cancelled=cancel_event)

    def refresh_announcements(self, target_trade_date: str, *, resume: bool = False,
                              schedule: Mapping[str, Any] | None = None,
                              source_scope: str | None = None,
                              issuer_code: str | None = None,
                              issuer_codes: list[str] | None = None) -> dict[str, Any]:
        """Explicit bounded capture by this owner, separate from plan projection."""
        from .workspace_announcements import refresh
        return refresh(self, target_trade_date, resume=resume, schedule=schedule,
                       source_scope=source_scope, issuer_code=issuer_code,
                       issuer_codes=issuer_codes)

    def get_announcements(self, target_trade_date: str, *, scope_id: str | None = None) -> dict[str, Any]:
        from .workspace_announcements import read
        return read(self, target_trade_date, scope_id=scope_id)

    def get_workspace_plan(self, target_trade_date: str) -> dict[str, Any] | None:
        from .workspace import _read_plan
        return _read_plan(self.store, strict_trade_date(target_trade_date))

    def refresh_workspace_plan(self, target_trade_date: str, *, execution_kind: str = 'MANUAL_REFRESH',
                               now: datetime | None = None, deadline: datetime | None = None) -> dict[str, Any]:
        from .workspace import refresh_workspace_plan
        return refresh_workspace_plan(self, target_trade_date, execution_kind=execution_kind, now=now, deadline=deadline)

    def _read_input(self, target_trade_date: str) -> dict[str, Any]:
        target_trade_date = strict_trade_date(target_trade_date)
        if self.observation_reader is None:
            raise ContractError("STAGE_OBSERVATION_READER_UNAVAILABLE")
        if hasattr(self.observation_reader, "read"):
            raw = self.observation_reader.read(target_trade_date)  # type: ignore[union-attr]
        else:
            raw = self.observation_reader(target_trade_date)  # type: ignore[operator]
        if raw is None:
            raise ContractError("STAGE_OBSERVATION_NOT_MATERIALIZED")
        input_data = normalise_observation_input(raw)
        if input_data["target_trade_date"] != target_trade_date:
            raise ContractError("STAGE_OBSERVATION_TARGET_DATE_MISMATCH")
        return input_data

    @staticmethod
    def _job_id(input_data: Mapping[str, Any]) -> str:
        return f"mr-{input_data['target_trade_date']}-{str(input_data['input_identity'])[:32]}"

    @staticmethod
    def _legacy_input_identity(input_data: Mapping[str, Any]) -> str | None:
        """Return the pre-stage-evidence identity for a compatible cache read."""

        identity_payload = input_data.get("identity_payload")
        if not isinstance(identity_payload, Mapping):
            return None
        legacy_payload = {
            key: value
            for key, value in identity_payload.items()
            if key not in {"source_status", "cannot_confirm"}
        }
        try:
            return sha256_json(legacy_payload)
        except ContractError:
            return None

    def _read_cached_product(self, input_data: Mapping[str, Any]) -> dict[str, Any] | None:
        """Read the exact product, then one validated pre-evidence alias."""

        target_trade_date = str(input_data["target_trade_date"])
        input_identity = str(input_data["input_identity"])
        exact = self.store.read_product(target_trade_date, input_identity)
        if exact is not None:
            try:
                validate_cached_product(exact, input_data)
            except ValueError as exc:
                raise StoreError("CACHE_INPUT_IDENTITY_MISMATCH") from exc
            return exact
        legacy_identity = self._legacy_input_identity(input_data)
        if legacy_identity is None or legacy_identity == input_identity:
            return None
        return self.store.read_compatible_product(
            target_trade_date,
            legacy_input_identity=legacy_identity,
            input_source_sha256=input_data.get("input_source_sha256"),
            input_row_count=int(input_data["input_row_count"]),
            stage_id=str(input_data["stage_id"]),
            market=str(input_data["market"]),
            normalized_rows=input_data.get("rows", []),
        )

    @staticmethod
    def _bind_product_to_input(
        input_data: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Bind a validated legacy product to the current stage identity."""

        current_identity = str(input_data["input_identity"])
        if product.get("input_identity") == current_identity:
            return dict(product), False
        bound = dict(product)
        bound.update(
            {
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": current_identity,
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "product_id": f"manager-research-{input_data['target_trade_date']}-{current_identity[:24]}",
            }
        )
        return bound, True

    @staticmethod
    def _progress(total: int, results: Mapping[str, Mapping[str, Any]]) -> dict[str, int | float]:
        ready = sum(1 for item in results.values() if item.get("status") == "READY" and item.get("facts"))
        cannot = sum(1 for item in results.values() if item.get("status") != "READY" or not item.get("facts"))
        completed = len(results)
        return {
            "total": total,
            "completed": completed,
            "ready": ready,
            "cannot_confirm": cannot,
            "failed": sum(1 for item in results.values() if item.get("failure_detail") or item.get("reason", "").endswith("FAILED")),
            "coverage_ratio": round(ready / total, 6) if total else 0.0,
        }

    def _envelope(
        self,
        input_data: Mapping[str, Any],
        *,
        product: Mapping[str, Any] | None = None,
        job: Mapping[str, Any] | None = None,
        status: str | None = None,
        cannot_confirm: list[str] | None = None,
    ) -> dict[str, Any]:
        terminal_failure = (job or {}).get("status") if (job or {}).get("status") in {"FAILED", "CANCELLED"} else None
        resolved_status = status or terminal_failure or (product or {}).get("status") or (job or {}).get("status") or "NOT_MATERIALIZED"
        return {
            "schema_version": PRODUCT_SCHEMA_VERSION,
            "kind": "MANAGER_RESEARCH",
            "target_trade_date": input_data["target_trade_date"],
            "stage_id": input_data["stage_id"],
            "market": input_data["market"],
            "cutoff_at": input_data["cutoff_at"],
            "input_identity": input_data["input_identity"],
            "input_source_sha256": input_data.get("input_source_sha256"),
            "input_row_count": input_data["input_row_count"],
            "status": resolved_status,
            "product": dict(product) if product is not None else None,
            "job": dict(job) if job is not None else None,
            "can_ensure": resolved_status in {"NOT_MATERIALIZED", "CANNOT_CONFIRM", "FAILED", "PARTIAL_WITH_ROWS"},
            "can_retry": resolved_status in {"CANNOT_CONFIRM", "FAILED", "PARTIAL_WITH_ROWS"},
            "cannot_confirm": list(cannot_confirm or []),
            **FOUR_FLAGS,
            "safety": dict(FOUR_FLAGS),
        }

    def _unowned_job_envelope(
        self, input_data: Mapping[str, Any], job: Mapping[str, Any]
    ) -> dict[str, Any]:
        # A persisted receipt is not evidence that this process owns a worker.
        # Do not overwrite it or start a second worker: another process may live.
        result = self._envelope(
            input_data, job=job, status="CANNOT_CONFIRM",
            cannot_confirm=["JOB_OWNER_UNCONFIRMED"],
        )
        result.update(can_ensure=False, can_retry=False)
        return result

    @staticmethod
    def _reassemble_cached_recommendations(
        input_data: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Attach the recommendation contract to an existing exact-date cache.

        This is a cache migration only.  It reuses the persisted stage row,
        official source receipt and structured facts; it never calls the
        provider and never widens the candidate universe.  A row without the
        market/timing evidence required by the new contract stays
        ``DATA_INSUFFICIENT`` rather than being promoted from a legacy
        decision string.
        """

        if not isinstance(product, Mapping):
            return None
        rows = product.get("rows")
        stage_rows = input_data.get("rows")
        if not isinstance(rows, list) or not isinstance(stage_rows, list):
            return None
        target_trade_date = str(input_data.get("target_trade_date") or "")
        if not target_trade_date:
            return None
        product_date = _row_date_token(product.get("target_trade_date"))
        if product_date is not None and product_date != target_trade_date:
            return None
        cutoff = str(input_data.get("cutoff_at") or product.get("cutoff_at") or contract_cutoff_at(target_trade_date))
        # A v1 product's generated_at describes the old materialization.  A
        # v2 cache migration is a new pure derivation and records its own
        # event time; subsequent reads remain stable because the migrated
        # product is persisted.
        generated_at = _now()
        # The exact stage input is the authority for a legacy product whose
        # new evidence fields are absent.  In particular, an overall product
        # status of READY only describes provider rows; it cannot stand in for
        # a missing stage status and must never upgrade PARTIAL_WITH_ROWS.
        stage_status_value = input_data.get("stage_status") or input_data.get("source_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            stage_status_value = product.get("stage_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            stage_status_value = product.get("source_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            product_status = product.get("status")
            stage_status_value = product_status if product_status in {"PARTIAL_WITH_ROWS", "CANNOT_CONFIRM"} else "CANNOT_CONFIRM"
        stage_status = str(stage_status_value).strip()
        cannot_confirm = input_data.get("cannot_confirm") if "cannot_confirm" in input_data else product.get("cannot_confirm")
        if cannot_confirm is None:
            cannot_confirm = product.get("cannot_confirm", [])
        input_source_sha256 = input_data.get("input_source_sha256")
        stage_by_code: dict[str, Mapping[str, Any]] = {}
        for stage_row in stage_rows:
            if not isinstance(stage_row, Mapping):
                return None
            code = stage_row.get("code")
            if isinstance(code, str) and code.strip():
                stage_by_code[code.strip()] = stage_row
        migrated_rows: list[dict[str, Any]] = []
        recommendations: list[Mapping[str, Any]] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                return None
            row = dict(raw_row)
            row_target = _row_date_token(row.get("target_trade_date"))
            if row_target is not None and row_target != target_trade_date:
                return None
            row_observation = row.get("observation")
            persisted_observation = dict(row_observation) if isinstance(row_observation, Mapping) else {}
            code_value = row.get("code") or persisted_observation.get("code")
            code = str(code_value).strip() if isinstance(code_value, str) else ""
            if not code or code not in stage_by_code:
                return None
            nested_target = _row_date_token(persisted_observation.get("target_trade_date"))
            if nested_target is not None and nested_target != target_trade_date:
                return None
            # The exact stage row supplies gate and market fields.  Persisted
            # observation fields are retained, with exact input taking
            # precedence on conflicts so a stale row cannot override it.
            observation = dict(persisted_observation)
            observation.update(dict(stage_by_code[code]))
            observation.update({"code": code, "target_trade_date": target_trade_date, "input_identity": input_data.get("input_identity")})
            for key in (
                "name", "action_level", "trade_status", "trade_status_contract", "formal_eligible",
                "source_last_bar_time", "observed_at", "last_price", "current_price", "price", "support",
                "support_price", "support_primary_price", "pressure", "pressure_price", "resistance",
                "resistance_price", "volume", "volume_ratio", "pct_chg", "current_change_pct",
            ):
                if key not in observation and key in row:
                    observation[key] = row[key]
            raw_facts = row.get("facts")
            facts = raw_facts if isinstance(raw_facts, list) else []
            source = row.get("source") if isinstance(row.get("source"), Mapping) else None
            provider_status = row.get("source_status") or row.get("status")
            row["observation"] = observation
            row["stage_observation"] = dict(observation)
            # Make the execution input visible to API/UI consumers without
            # overwriting the provider row's own READY/CANNOT_CONFIRM status.
            for key in (
                "action_level", "trade_status", "trade_status_contract", "formal_eligible", "last_price",
                "current_price", "price", "support", "support_price", "support_primary_price", "pressure",
                "pressure_price", "resistance", "resistance_price", "volume", "volume_ratio", "rank",
            ):
                if key in observation:
                    row[key] = observation[key]
            row["stage_rank"] = observation.get("stage_rank")
            row["stage_row_status"] = observation.get("status")
            recommendation = build_research_recommendation(
                observation=observation,
                result={
                    "status": "READY" if provider_status == "READY" and facts else provider_status,
                    "reason": row.get("source_reason"),
                    "source": source,
                    "facts": facts,
                },
                target_trade_date=target_trade_date,
                cutoff_at=cutoff,
                generated_at=generated_at,
                input_source_sha256=input_source_sha256 if isinstance(input_source_sha256, str) else None,
                stage_status=stage_status,
                cannot_confirm=cannot_confirm,
            )
            row["research_recommendation"] = recommendation
            row["observation_timing_status"] = recommendation.get("timing_status")
            recommendations.append(recommendation)
            migrated_rows.append(row)
        assign_investment_priorities(migrated_rows)
        recommendations = [
            row["research_recommendation"]
            for row in migrated_rows
            if isinstance(row.get("research_recommendation"), Mapping)
        ]
        migrated = dict(product)
        migrated["rows"] = migrated_rows
        migrated["target_trade_date"] = target_trade_date
        migrated["input_identity"] = input_data.get("input_identity")
        migrated["input_source_sha256"] = input_source_sha256
        migrated["input_row_count"] = input_data.get("input_row_count")
        migrated["stage_id"] = input_data.get("stage_id")
        migrated["market"] = input_data.get("market")
        migrated["cutoff_at"] = cutoff
        migrated["product_id"] = f"manager-research-{target_trade_date}-{str(input_data.get('input_identity'))[:24]}"
        migrated["stage_status"] = stage_status
        migrated["cannot_confirm"] = cannot_confirm
        migrated["recommendation_summary"] = recommendation_summary(recommendations)
        migrated["generated_at"] = generated_at
        return migrated

    @staticmethod
    def _project_cached_financial_advice(product: Mapping[str, Any]) -> dict[str, Any]:
        """Reproject research advice from persisted facts without collecting data."""
        rows = product.get("rows")
        if not isinstance(rows, list):
            return dict(product)

        projected = dict(product)
        projected_rows: list[Any] = []
        recommendations: list[Mapping[str, Any]] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                projected_rows.append(raw_row)
                continue
            row = dict(raw_row)
            recommendation = row.get("research_recommendation")
            if not isinstance(recommendation, Mapping):
                projected_rows.append(row)
                continue

            finance = _financial_counterevidence_for_row(row)
            reevaluation = finance.get("financial_re_evaluation")
            if not isinstance(reevaluation, Mapping):
                projected_rows.append(row)
                continue

            current_recommendation = dict(recommendation)
            for field in ("status", "action", "label_cn"):
                if field in reevaluation:
                    current_recommendation[field] = reevaluation[field]
            current_recommendation["missing_fields"] = list(reevaluation.get("missing_dimensions") or [])
            investment_advice = current_recommendation.get("investment_advice")
            if isinstance(investment_advice, Mapping):
                current_advice = dict(investment_advice)
                for field in ("status", "action", "label_cn", "reason", "missing_dimensions", "evidence_grade"):
                    if field in reevaluation:
                        current_advice[field] = reevaluation[field]
                current_recommendation["investment_advice"] = current_advice
            row["research_recommendation"] = current_recommendation

            catalyst_result = row.get("catalyst_result")
            if isinstance(catalyst_result, Mapping):
                current_catalyst = dict(catalyst_result)
                current_catalyst["financial_counterevidence"] = list(finance.get("financial_counterevidence") or [])
                current_catalyst["financial_counterevidence_refs"] = list(finance.get("financial_counterevidence_refs") or [])
                current_catalyst["financial_re_evaluation"] = dict(reevaluation)
                row["catalyst_result"] = current_catalyst

            current_research = row.get("current_research")
            if isinstance(current_research, Mapping):
                current_view = dict(current_research)
                current_view["financial_advice"] = dict(reevaluation)
                current_view["financial_counterevidence"] = list(finance.get("financial_counterevidence") or [])
                current_view["financial_counterevidence_refs"] = list(finance.get("financial_counterevidence_refs") or [])
                row["current_research"] = current_view

            recommendations.append(current_recommendation)
            projected_rows.append(row)

        projected["rows"] = projected_rows
        if len(recommendations) == len(projected_rows):
            projected["recommendation_summary"] = recommendation_summary(recommendations)
        return projected

    def _current_or_migrated_product(
        self, input_data: Mapping[str, Any], raw_product: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Pure cache projection. GET never publishes aliases or migrations."""
        if raw_product is None:
            return None
        product, _bound_from_legacy = self._bind_product_to_input(input_data, raw_product)
        current_product = _current_product(product)
        if current_product is not None:
            rows = current_product.get("rows")
            has_recommendations = (
                isinstance(rows, list)
                and all(isinstance(row, Mapping) and _is_v2_recommendation(row.get("research_recommendation")) for row in rows)
                and isinstance(current_product.get("recommendation_summary"), Mapping)
                and "stage_status" in current_product and "cannot_confirm" in current_product
            )
            if has_recommendations:
                projected = _project_cached_catalysts(current_product)
                projected = self._project_cached_financial_advice(projected)
                assert_manager_safe_tree(projected)
                return projected
        if (product.get("content_contract_version") == CONTENT_CONTRACT_VERSION
            and product.get("content_contract_revision") in {CONTENT_CONTRACT_REVISION, None, ""}
            and not _legacy_product_requires_r3_refresh(product)):
            migrated = self._reassemble_cached_recommendations(input_data, product)
            if migrated is not None:
                assert_manager_safe_tree(migrated)
                return migrated
        return current_product

    def get(self, target_trade_date: str) -> dict[str, Any]:
        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            # A typed missing-source response is useful to the UI and avoids a
            # synthetic empty product when the stage host is not configured.
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        try:
            raw_product = self._read_cached_product(input_data)
            product = self._current_or_migrated_product(input_data, raw_product)
        except (StoreError, ValueError) as exc:
            return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=[public_error(exc)])
        job_id = self._job_id(input_data)
        with self._lock:
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if (job is not None and job.get("status") in {"QUEUED", "RUNNING"}
                    and (running is None or running.done())):
                return self._unowned_job_envelope(input_data, job)
        if product is not None:
            return self._envelope(input_data, product=product, job=job)
        # A terminal READY job can outlive the content revision that produced
        # its product.  Keep the stale product hidden, but expose an explicit
        # ensure signal so the existing date-page flow starts one bounded
        # refresh.  Returning the old READY status here made the UI believe
        # the stale result was current and skipped the POST /ensure step.
        if raw_product is not None and job is not None and job.get("status") == "READY":
            return self._envelope(
                input_data,
                job=job,
                status="NOT_MATERIALIZED",
                cannot_confirm=["STALE_CONTENT_CONTRACT"],
            )
        if job is not None:
            return self._envelope(input_data, job=job)
        return self._envelope(input_data)

    def ensure(self, target_trade_date: str, *, force: bool = False) -> dict[str, Any]:
        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        job_id = self._job_id(input_data)
        with self._lock:
            if self._closed:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["SERVICE_CLOSED"])
            if sum(not future.done() for future in self._active.values()) >= self.max_pending_jobs:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["JOB_QUEUE_CAPACITY_REACHED"])
            try:
                raw_product = self._read_cached_product(input_data)
                product = self._current_or_migrated_product(input_data, raw_product)
            except (StoreError, ValueError) as exc:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=[public_error(exc)])
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if running is not None and not running.done():
                return self._envelope(input_data, product=product, job=job, status="RUNNING")
            if job is not None and job.get("status") in {"QUEUED", "RUNNING"}:
                return self._unowned_job_envelope(input_data, job)
            if product is not None and not force:
                return self._envelope(input_data, product=product, job=job)
            attempt = int(job.get("attempt", 0)) + 1 if job else 1
            now = _now()
            new_job = {
                "schema_version": JOB_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH_JOB",
                "job_id": job_id,
                "generation": uuid4().hex,
                "owner_pid": os.getpid(),
                "owner_instance": self._instance_id,
                "attempt": attempt,
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": input_data["input_identity"],
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "status": "QUEUED",
                "progress": self._progress(input_data["input_row_count"], {}),
                "results": {},
                "error": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "can_retry": False,
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
            try:
                self.store.admit_job(new_job)
            except StoreConflict as exc:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=[public_error(exc)])
            future = self._executor.submit(self._run_job, input_data, new_job)
            self._active[job_id] = future
            self._active_generations[job_id] = new_job["generation"]
            return self._envelope(input_data, job=new_job, status="QUEUED")

    @staticmethod
    def _event_job_id(input_data: Mapping[str, Any]) -> str:
        return f"mr-events-{input_data['target_trade_date']}-{str(input_data['input_identity'])[:32]}"

    def ensure_events(self, target_trade_date: str, *, force: bool = False) -> dict[str, Any]:
        """Refresh catalysts for an existing product without recollecting PDFs."""

        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        with self._lock:
            if self._closed:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["SERVICE_CLOSED"])
            if sum(not future.done() for future in self._active.values()) >= self.max_pending_jobs:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["JOB_QUEUE_CAPACITY_REACHED"])
            try:
                raw_product = self._read_cached_product(input_data)
                product = self._current_or_migrated_product(input_data, raw_product)
            except (StoreError, ValueError) as exc:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=[public_error(exc)])
            if product is None:
                return self._envelope(
                    input_data,
                    status="NOT_MATERIALIZED",
                    cannot_confirm=["FINANCIAL_PRODUCT_NOT_MATERIALIZED"],
                )
            job_id = self._event_job_id(input_data)
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if running is not None and not running.done():
                return self._envelope(input_data, product=product, job=job, status="RUNNING")
            if job is not None and job.get("status") in {"QUEUED", "RUNNING"}:
                return self._unowned_job_envelope(input_data, job)
            if job is not None and job.get("status") in {"READY", "PARTIAL_WITH_ROWS", "CANNOT_CONFIRM", "FAILED"} and not force:
                return self._envelope(input_data, product=product, job=job, status=job.get("status"))
            now = _now()
            new_job = {
                "schema_version": JOB_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH_EVENT_REFRESH_JOB",
                "job_id": job_id,
                "generation": uuid4().hex,
                "owner_pid": os.getpid(),
                "owner_instance": self._instance_id,
                "attempt": int(job.get("attempt", 0)) + 1 if job else 1,
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": input_data["input_identity"],
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "status": "QUEUED",
                "mode": "EVENT_REFRESH",
                "progress": {"total": input_data["input_row_count"], "completed": 0, "event_rows": 0},
                "results": {},
                "error": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "can_retry": False,
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
            try:
                self.store.admit_job(new_job)
            except StoreConflict as exc:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=[public_error(exc)])
            future = self._executor.submit(self._run_event_refresh_job, input_data, new_job, product)
            self._active[job_id] = future
            self._active_generations[job_id] = new_job["generation"]
            return self._envelope(input_data, product=product, job=new_job, status="QUEUED")

    def _run_event_refresh_job(
        self,
        input_data: Mapping[str, Any],
        job: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> None:
        job_id = str(job["job_id"])
        job_state = dict(job)
        job_state.update(status="RUNNING", started_at=_now(), updated_at=_now())
        job_state.setdefault("mode", "EVENT_REFRESH")
        try:
            self.store.write_job(job_state)
        except StoreConflict:
            self._finish_active(job_id, job_state.get("generation"))
            return
        observations = list(input_data["rows"])
        try:
            previous_rows = {
                str(row.get("code")): row.get("catalyst_result")
                for row in product.get("rows", [])
                if isinstance(row, Mapping) and isinstance(row.get("code"), str) and isinstance(row.get("catalyst_result"), Mapping)
            }
            event_batch = self._collect_events(input_data, observations, previous_rows=previous_rows)
            updated = self._attach_catalyst_to_product(product, event_batch, observations)
            if self._is_cancelled(job_state):
                job_state.update(status="CANCELLED", error="CANCELLED_BY_REQUEST", can_retry=True)
            else:
                rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
                result_map = {
                    str(code): {
                        "status": item.get("status", "CANNOT_CONFIRM"),
                        "event_count": len(item.get("events", [])) if isinstance(item.get("events"), list) else 0,
                        "reader_material_count": len(item.get("reader_materials", [])) if isinstance(item.get("reader_materials"), list) else 0,
                        "reader_status": item.get("reader_status", "CANNOT_CONFIRM"),
                    }
                    for code, item in rows.items()
                    if isinstance(item, Mapping)
                }
                event_count = sum(int(item.get("event_count", 0)) for item in result_map.values())
                reader_material_count = sum(int(item.get("reader_material_count", 0)) for item in result_map.values())
                batch_status = str(event_batch.get("status") or "CANNOT_CONFIRM")
                reader_coverage = event_batch.get("reader_coverage") if isinstance(event_batch.get("reader_coverage"), Mapping) else {}
                reader_status = str(reader_coverage.get("status") or "CANNOT_CONFIRM")
                # A source-wide failure is authoritative even when a malformed
                # provider result happens to report a non-zero row count.  Do
                # not let the refresh job manufacture READY from that count.
                final_status = (
                    batch_status
                    if batch_status in {"CANNOT_CONFIRM", "FAILED"}
                    else "READY" if event_count or reader_status == "READY" else batch_status
                )
                job_state.update(
                    status=final_status,
                    results=result_map,
                    progress={"total": len(observations), "completed": len(result_map), "event_rows": event_count, "reader_materials": reader_material_count},
                    can_retry=final_status != "READY",
                )
                job_state.update(completed_at=_now(), updated_at=_now())
                self.store.commit_result(
                    job_state,
                    updated,
                    {
                        "schema_version": "v4.manager_research.catalyst_receipt.v1",
                        "job_id": job_id,
                        "target_trade_date": input_data["target_trade_date"],
                        "input_identity": input_data["input_identity"],
                        "status": final_status,
                        "progress": job_state["progress"],
                        "catalyst_status": updated.get("catalyst_status"),
                        "catalyst_coverage": updated.get("catalyst_coverage"),
                        "catalyst_source_counts": updated.get("catalyst_source_counts"),
                        "catalyst_source_receipt_count": len(updated.get("catalyst_source_receipts", [])),
                        "reader_coverage": updated.get("reader_coverage"),
                        "reader_source_counts": updated.get("reader_source_counts"),
                        "reader_current_as_of": updated.get("reader_current_as_of"),
                        "reader_material_count": reader_material_count,
                        "financial_recollection": False,
                        **FOUR_FLAGS,
                    },
                    merge=lambda latest: self._attach_catalyst_to_product(latest, event_batch, observations),
                )
                return
            job_state.update(completed_at=_now(), updated_at=_now())
            self.store.write_job(job_state)
        except StoreConflict:
            return
        except Exception as exc:
            job_state.update(
                status="FAILED",
                error=public_error(exc),
                completed_at=_now(),
                updated_at=_now(),
                can_retry=True,
            )
            try:
                self.store.write_job(job_state)
            except StoreConflict:
                pass
        finally:
            self._finish_active(job_id, job_state.get("generation"))

    def retry(self, target_trade_date: str) -> dict[str, Any]:
        return self.ensure(target_trade_date, force=True)

    def job(self, job_id: str, target_trade_date: str | None = None) -> dict[str, Any] | None:
        job = self.store.read_job(job_id)
        if job is None:
            return None
        if target_trade_date is not None and job.get("target_trade_date") != target_trade_date:
            return None
        return job

    def cancel(self, job_id: str, target_trade_date: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            job = self.store.cancel_job(job_id, target_trade_date)
            if job is not None and job.get("status") == "CANCELLED":
                self._cancelled.add((job_id, job.get("generation")))
            return job

    def _is_cancelled(self, job: Mapping[str, Any]) -> bool:
        if (str(job["job_id"]), job.get("generation")) in self._cancelled:
            return True
        current = self.store.read_job(str(job["job_id"]))
        return current is not None and (
            current.get("status") == "CANCELLED"
            or current.get("generation") != job.get("generation")
            or current.get("attempt", 0) != job.get("attempt", 0)
        )

    def _finish_active(self, job_id: str, generation: Any) -> None:
        with self._lock:
            if self._active_generations.get(job_id) == generation:
                self._active.pop(job_id, None)
                self._active_generations.pop(job_id, None)

    def _collect_one(self, target_trade_date: str, cutoff_at: str, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.source_provider is None:
            return {
                "status": "CANNOT_CONFIRM",
                "reason": "SOURCE_PROVIDER_UNAVAILABLE",
                "failure_detail": "no official research source provider is configured",
                "issuer": None,
                "source": None,
                "facts": [],
            }
        try:
            if hasattr(self.source_provider, "collect"):
                result = self.source_provider.collect(  # type: ignore[union-attr]
                    target_trade_date=target_trade_date,
                    cutoff_at=cutoff_at,
                    observation=observation,
                )
            else:
                result = self.source_provider(  # type: ignore[operator]
                    target_trade_date=target_trade_date,
                    cutoff_at=cutoff_at,
                    observation=observation,
                )
            if not isinstance(result, Mapping):
                raise ContractError("source provider returned a non-object")
            status = result.get("status")
            facts = result.get("facts")
            if status == "READY" and not isinstance(facts, list):
                return {
                    **dict(result),
                    "status": "CANNOT_CONFIRM",
                    "reason": "SOURCE_FACTS_MISSING",
                    "failure_detail": "provider claimed READY without extracted facts",
                    "facts": [],
                }
            if status == "READY":
                verifiable_facts = [
                    fact
                    for fact in facts
                    if _usable_fact(fact)
                ]
                if not verifiable_facts:
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_FACTS_NOT_STRUCTURED",
                        "failure_detail": "provider claimed READY without Chinese, page-locatable structured facts",
                        "facts": [],
                    }
                if not _has_researchable_fact_set(verifiable_facts):
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_FACTS_NOT_RESEARCHABLE",
                        "failure_detail": "parsed financial rows contain no primary operating, profit/loss, or cash-flow metric",
                        "facts": [],
                    }
                source = result.get("source")
                if not isinstance(source, Mapping):
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_RECEIPT_MISSING",
                        "failure_detail": "structured facts are not bound to an official source receipt",
                        "facts": [],
                    }
                result = {**dict(result), "facts": verifiable_facts}
            if status not in {"READY", "CANNOT_CONFIRM", "NO_MATCH"}:
                return {
                    **dict(result),
                    "status": "CANNOT_CONFIRM",
                    "reason": "SOURCE_STATUS_INVALID",
                    "failure_detail": f"unsupported provider status: {status!r}",
                    "facts": [],
                }
            assert_manager_safe_tree(result)
            return dict(result)
        except Exception as exc:
            return {
                "status": "CANNOT_CONFIRM",
                "reason": "SOURCE_PROVIDER_FAILED",
                "failure_detail": public_error(exc),
                "issuer": None,
                "source": None,
                "facts": [],
            }

    @staticmethod
    def _empty_event_batch(
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        rows = {
            str(observation.get("code")): _empty_catalyst_row(
                str(observation.get("code")),
                reason=reason,
            )
            for observation in observations
            if observation.get("code")
        }
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "status": "CANNOT_CONFIRM",
            "source_id": None,
            "rows": rows,
            "source_counts": [],
            "coverage": {
                "requested_candidates": len(observations),
                "event_count": 0,
                "historical_event_count": 0,
                "current_event_count": 0,
                "completeness": "EVENT_SOURCE_NOT_RUN",
                "no_match_is_not_complete": True,
                "reason": reason,
            },
            "current_event_as_of": _now(),
            "historical_cutoff_at": input_data.get("cutoff_at"),
        }

    def _collect_events(
        self,
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        *,
        previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        """Run only the bounded event lane and keep its failure independent."""

        collector = getattr(self.source_provider, "collect_events", None) if self.source_provider is not None else None
        try:
            if callable(collector):
                result = collector(
                    target_trade_date=input_data["target_trade_date"],
                    cutoff_at=input_data["cutoff_at"],
                    observations=observations,
                    previous_rows=previous_rows or {},
                    current_event_as_of=_now(),
                )
                if not isinstance(result, Mapping):
                    raise ContractError("event provider returned a non-object")
                raw_rows = result.get("rows")
                rows: dict[str, Mapping[str, Any]] = {}
                if isinstance(raw_rows, Mapping):
                    for observation in observations:
                        code = str(observation.get("code") or "")
                        item = raw_rows.get(code)
                        rows[code] = item if isinstance(item, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
                else:
                    rows = {
                        str(observation.get("code")): _empty_catalyst_row(
                            str(observation.get("code")),
                            reason="EVENT_ROWS_MISSING",
                        )
                        for observation in observations
                        if observation.get("code")
                    }
                normalized = {**dict(result), "rows": rows}
            else:
                # The public reader can be exercised independently of the
                # optional event provider (for example in a canary or a
                # source outage).  Preserve that source boundary per row.
                normalized = self._empty_event_batch(input_data, observations, "EVENT_PROVIDER_UNAVAILABLE")
            reader_fetcher = self.reader_fetcher or self._material_reader_fetcher
            reader_enabled = bool(getattr(self.source_provider, "reader_source_enabled", False)) or reader_fetcher is not None
            if not reader_enabled:
                return normalized
            reader_batch = read_public_news_batch(
                observations,
                target_date=str(input_data["target_trade_date"]),
                queried_at=_now(),
                fetcher=reader_fetcher,
            )
            return _attach_reader_batch(normalized, reader_batch, observations)
        except Exception as exc:
            return self._empty_event_batch(
                input_data,
                observations,
                f"EVENT_PROVIDER_FAILED:{type(exc).__name__}",
            )

    @staticmethod
    def _attach_catalyst_to_product(
        product: Mapping[str, Any],
        event_batch: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Attach event evidence while preserving every financial field."""

        event_rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
        updated = dict(product)
        updated_rows: list[dict[str, Any]] = []
        catalyst_receipts: list[dict[str, Any]] = []
        for observation in observations:
            code = str(observation.get("code") or "")
            existing = next(
                (row for row in product.get("rows", []) if isinstance(row, Mapping) and str(row.get("code") or "") == code),
                None,
            )
            if not isinstance(existing, Mapping):
                continue
            row = dict(existing)
            catalyst = event_rows.get(code) if isinstance(event_rows, Mapping) else None
            catalyst_result = dict(catalyst) if isinstance(catalyst, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
            catalyst_result.setdefault("code", code)
            finance = _financial_counterevidence_for_row(row)
            financial_text = list(finance.get("financial_counterevidence") or [])
            financial_refs = list(finance.get("financial_counterevidence_refs") or [])
            financial_revaluation = finance.get("financial_re_evaluation")
            catalyst_result["financial_counterevidence"] = financial_text
            catalyst_result["financial_counterevidence_refs"] = financial_refs
            catalyst_result["financial_re_evaluation"] = financial_revaluation
            catalyst_gaps = list(catalyst_result.get("market_confirmation_gap") or [])
            if finance.get("market_price_volume_unconfirmed"):
                catalyst_gaps.append("MARKET_PRICE_VOLUME_UNCONFIRMED")
            catalyst_result["market_confirmation_gap"] = list(dict.fromkeys(str(item) for item in catalyst_gaps if item))
            enriched_events: list[dict[str, Any]] = []
            event_by_key: dict[str, dict[str, Any]] = {}
            for event_item in catalyst_result.get("events", []) if isinstance(catalyst_result.get("events"), list) else []:
                if not isinstance(event_item, Mapping):
                    continue
                event = dict(event_item)
                event["financial_counterevidence"] = list(dict.fromkeys([
                    *([str(item) for item in event.get("financial_counterevidence", []) if item]),
                    *financial_text,
                ]))
                event["financial_counterevidence_refs"] = financial_refs
                event["financial_re_evaluation"] = financial_revaluation
                event_gaps = list(event.get("market_confirmation_gap") or [])
                if finance.get("market_price_volume_unconfirmed"):
                    event_gaps.append("MARKET_PRICE_VOLUME_UNCONFIRMED")
                event["market_confirmation_gap"] = list(dict.fromkeys(str(item) for item in event_gaps if item))
                enriched_events.append(event)
                event_key = str(event.get("event_id") or event.get("source_url") or event.get("source_title") or "")
                if event_key:
                    event_by_key[event_key] = event
            # Copy the event so a provider's result object cannot be mutated
            # outside this product assembly boundary, and keep the historical
            # and current projections consistent with the enriched event list.
            catalyst_result["events"] = enriched_events
            for projection in ("historical_events", "current_events"):
                raw_projection = catalyst_result.get(projection)
                if not isinstance(raw_projection, list):
                    continue
                catalyst_result[projection] = [
                    event_by_key.get(
                        str(event.get("event_id") or event.get("source_url") or event.get("source_title") or ""),
                        dict(event),
                    )
                    for event in raw_projection
                    if isinstance(event, Mapping)
                ]
            row["catalyst_result"] = catalyst_result
            row["current_research"] = {
                "status": catalyst_result.get("status", "CANNOT_CONFIRM"),
                "catalyst_advice": catalyst_result.get("catalyst_advice"),
                "financial_advice": financial_revaluation,
                "financial_counterevidence": financial_text,
                "financial_counterevidence_refs": financial_refs,
                "execution_gate": row.get("research_recommendation", {}).get("execution_gate")
                if isinstance(row.get("research_recommendation"), Mapping)
                else None,
                "research_only": True,
            }
            updated_rows.append(row)
            receipts = catalyst_result.get("source_receipts")
            if isinstance(receipts, list):
                catalyst_receipts.extend(item for item in receipts if isinstance(item, Mapping))
        # The backend owns the small focus set.  All exact candidates remain
        # in ``rows`` with their complete event evidence, while only up to
        # three interpretable recent rows receive unique continuous ranks.
        _assign_catalyst_focus_ranks(
            updated_rows,
            str(product.get("target_trade_date") or ""),
        )
        for row in updated_rows:
            result = row.get("catalyst_result")
            if isinstance(result, Mapping):
                current_research = dict(row.get("current_research")) if isinstance(row.get("current_research"), Mapping) else {}
                current_research["catalyst_advice"] = result.get("catalyst_advice")
                row["current_research"] = current_research
        updated["rows"] = updated_rows
        updated["catalyst_schema_version"] = EVENT_SCHEMA_VERSION
        updated["catalyst_status"] = str(event_batch.get("status") or "CANNOT_CONFIRM")
        updated["catalyst_coverage"] = dict(event_batch.get("coverage")) if isinstance(event_batch.get("coverage"), Mapping) else {
            "completeness": "BOUNDED_SOURCES_ONLY",
            "no_match_is_not_complete": True,
        }
        updated["catalyst_source_counts"] = list(event_batch.get("source_counts")) if isinstance(event_batch.get("source_counts"), list) else []
        updated["catalyst_source_receipts"] = catalyst_receipts
        updated["catalyst_current_event_as_of"] = event_batch.get("current_event_as_of") or _now()
        updated["reader_coverage"] = dict(event_batch.get("reader_coverage")) if isinstance(event_batch.get("reader_coverage"), Mapping) else {
            "status": "CANNOT_CONFIRM",
            "completeness": "READER_NOT_RUN",
        }
        updated["reader_source_counts"] = list(event_batch.get("reader_source_counts")) if isinstance(event_batch.get("reader_source_counts"), list) else []
        updated["reader_current_as_of"] = event_batch.get("reader_current_as_of")
        updated["current_research"] = {
            "status": updated["catalyst_status"],
            "catalyst_coverage": updated["catalyst_coverage"],
            "catalyst_source_counts": updated["catalyst_source_counts"],
            "catalyst_current_event_as_of": updated["catalyst_current_event_as_of"],
            "reader_coverage": updated["reader_coverage"],
            "reader_current_as_of": updated["reader_current_as_of"],
            "financial_research_status": product.get("status"),
            "research_only": True,
        }
        return updated

    def _run_job(self, input_data: Mapping[str, Any], job: Mapping[str, Any]) -> None:
        job_id = str(job["job_id"])
        job_state = dict(job)
        job_state["status"] = "RUNNING"
        job_state["started_at"] = _now()
        job_state["updated_at"] = _now()
        try:
            self.store.write_job(job_state)
        except StoreConflict:
            self._finish_active(job_id, job_state.get("generation"))
            return
        results: dict[str, Mapping[str, Any]] = {}
        observations = list(input_data["rows"])
        # Four bounded provider calls keep the public endpoint responsive while
        # still exposing each row's status as soon as it finishes.
        row_workers = min(4, max(1, len(observations)))
        deadline = time.monotonic() + self.row_timeout_seconds * max(1, len(observations) // row_workers + 1)
        futures: dict[Future[Any], Mapping[str, Any]] = {}
        try:
            futures = {
                self._row_executor.submit(self._collect_one, input_data["target_trade_date"], input_data["cutoff_at"], observation): observation
                for observation in observations
            }
            try:
                completed_futures = as_completed(
                    futures,
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                for future in completed_futures:
                    if self._is_cancelled(job_state):
                        for pending in futures:
                            pending.cancel()
                        break
                    observation = futures[future]
                    code = str(observation["code"])
                    try:
                        result = dict(future.result(timeout=max(0.1, deadline - time.monotonic())))
                    except Exception as exc:
                        result = {
                            "status": "CANNOT_CONFIRM",
                            "reason": "SOURCE_PROVIDER_FAILED",
                            "failure_detail": public_error(exc),
                            "issuer": None,
                            "source": None,
                            "facts": [],
                        }
                    results[code] = result
                    job_state["results"] = {key: dict(value) for key, value in results.items()}
                    job_state["progress"] = self._progress(len(observations), results)
                    job_state["updated_at"] = _now()
                    self.store.write_job(job_state)
            except FutureTimeoutError:
                # A public source can stall independently of the HTTP
                # request.  Finish every unfinished row as visible
                # CANNOT_CONFIRM instead of leaving a forever-running job.
                for pending, observation in futures.items():
                    code = str(observation["code"])
                    if code in results:
                        continue
                    pending.cancel()
                    results[code] = {
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_PROVIDER_TIMEOUT",
                        "failure_detail": f"provider exceeded {self.row_timeout_seconds:.1f}s row budget",
                        "issuer": None,
                        "source": None,
                        "facts": [],
                    }
                job_state["results"] = {key: dict(value) for key, value in results.items()}
                job_state["progress"] = self._progress(len(observations), results)
                job_state["updated_at"] = _now()
                self.store.write_job(job_state)
            # The catalyst lane is independent of the financial collection.
            # A source failure here remains visible on the product and never
            # discards already parsed official financial facts.
            if self._is_cancelled(job_state):
                return
            event_batch = self._collect_events(input_data, observations)
            product = self._build_product(input_data, observations, results, event_batch=event_batch)
            if self._is_cancelled(job_state):
                job_state["status"] = "CANCELLED"
                job_state["error"] = "CANCELLED_BY_REQUEST"
                job_state["completed_at"] = _now()
                job_state["updated_at"] = _now()
                job_state["can_retry"] = True
                self.store.write_job(job_state)
                return
            final_status = product["status"]
            job_state["status"] = final_status
            job_state["completed_at"] = _now()
            job_state["updated_at"] = _now()
            job_state["can_retry"] = final_status != "READY"
            self.store.commit_result(
                job_state,
                product,
                {
                    "schema_version": "v4.manager_research.receipt.v1",
                    "job_id": job_id,
                    "target_trade_date": input_data["target_trade_date"],
                    "input_identity": input_data["input_identity"],
                    "provider_id": getattr(self.source_provider, "provider_id", type(self.source_provider).__name__ if self.source_provider else None),
                    "status": final_status,
                    "progress": job_state["progress"],
                    "source_receipt_count": len(product.get("source_receipts", [])),
                    "content_contract_version": CONTENT_CONTRACT_VERSION,
                    "content_contract_revision": CONTENT_CONTRACT_REVISION,
                    "pdf_parser": "pypdf",
                    "pdf_parser_version": "6.10.0",
                    "generated_at": product["generated_at"],
                    **FOUR_FLAGS,
                },
            )
        except StoreConflict:
            return
        except Exception as exc:
            job_state["status"] = "FAILED"
            job_state["error"] = public_error(exc)
            job_state["updated_at"] = _now()
            job_state["completed_at"] = _now()
            job_state["can_retry"] = True
            try:
                self.store.write_job(job_state)
            except StoreConflict:
                pass
        finally:
            # Never wait here for a timed-out public transport. Cancel queued
            # calls; running calls are bounded by the shared four-worker pool.
            for pending in futures:
                pending.cancel()
            self._finish_active(job_id, job_state.get("generation"))

    @staticmethod
    def _build_product(
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        results: Mapping[str, Mapping[str, Any]],
        *,
        event_batch: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        generated = _now()
        raw_stage_status = input_data.get("stage_status", input_data.get("source_status"))
        stage_status = raw_stage_status.strip() if isinstance(raw_stage_status, str) and raw_stage_status.strip() else "CANNOT_CONFIRM"
        stage_cannot_confirm = input_data.get("cannot_confirm", [])
        ready_count = sum(1 for result in results.values() if result.get("status") == "READY" and result.get("facts"))
        if ready_count == len(observations):
            overall_status = "READY"
        elif ready_count > 0:
            overall_status = "PARTIAL_WITH_ROWS"
        else:
            overall_status = "CANNOT_CONFIRM"
        product_rows: list[dict[str, Any]] = []
        source_receipts: list[dict[str, Any]] = []
        for observation in observations:
            code = str(observation["code"])
            result = results.get(
                code,
                {
                    "status": "CANNOT_CONFIRM",
                    "reason": "ROW_NOT_COMPLETED",
                    "failure_detail": "row did not receive a provider response",
                    "facts": [],
                    "source": None,
                },
            )
            row_status = "READY" if result.get("status") == "READY" and result.get("facts") else "CANNOT_CONFIRM"
            facts: list[dict[str, Any]] = []
            for fact in result.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                if not _usable_fact(fact):
                    continue
                source_map = result.get("source") if isinstance(result.get("source"), Mapping) else {}
                facts.append(
                    {
                        "statement_cn": str(fact["statement_cn"]).strip(),
                        "fact_type": "OFFICIAL_FACT",
                        "fact_kind": str(fact["fact_kind"]),
                        "locator": str(fact["locator"]),
                        "page": int(fact["page"]),
                        "source_excerpt": str(fact["source_excerpt"]).strip(),
                        "fields": dict(fact["fields"]),
                        "source_url": source_map.get("url"),
                        "source_sha256": source_map.get("sha256"),
                    }
                )
            source = dict(result.get("source")) if isinstance(result.get("source"), Mapping) else None
            receipt = {"code": code, "status": row_status, "reason": result.get("reason")}
            if source is not None:
                receipt.update(source)
            # Keep one receipt slot per requested row even when the provider
            # could not establish an issuer mapping.  The absence of a URL is
            # itself visible evidence for CANNOT_CONFIRM, never a title-only
            # substitute.
            source_receipts.append(receipt)
            source_url = source.get("url") if source else None
            sections = _build_research_sections(
                str(result.get("issuer") or observation.get("name") or code),
                code,
                facts,
                observation,
            ) if row_status == "READY" else {
                "thesis_cn": "官方来源尚未形成可核实正文事实，不能把标题或行情写成完整公司深研。",
                "inferences_cn": [],
                "counterevidence_cn": ["当前没有可复核的正文事实，不能据此形成公司判断。"],
                "confirmation_conditions": ["补齐官方正文、页码和同日来源回执后再研究。"],
                "invalidation_conditions": ["若身份、日期或正文继续无法确认，保持不可确认。"],
            }
            thesis = str(sections["thesis_cn"])
            observation_full = dict(observation)
            observation_full.update(
                {
                    "code": code,
                    "name": observation.get("name", code),
                    "market": input_data["market"],
                    "stage_id": input_data["stage_id"],
                    "target_trade_date": input_data["target_trade_date"],
                    "input_identity": input_data.get("input_identity"),
                }
            )
            research_row = {
                "status": row_status,
                "code": code,
                "market": "HK_CONNECT",
                "name": observation.get("name", code),
                "issuer": result.get("issuer"),
                "target_trade_date": input_data["target_trade_date"],
                "decision": SAFE_DECISION if row_status == "READY" else SAFE_CANNOT_DECISION,
                "direction": "观察" if row_status == "READY" else "UNVERIFIED",
                "thesis_cn": thesis,
                "facts": facts,
                "inferences_cn": list(sections["inferences_cn"]),
                "counterevidence_cn": list(sections["counterevidence_cn"]),
                "confirmation_conditions": list(sections["confirmation_conditions"]),
                "invalidation_conditions": list(sections["invalidation_conditions"]),
                "research_next_action": (
                    "按原文页码复核上述字段，并补下一期同口径数据与阶段承接。"
                    if row_status == "READY"
                    else "保留本股原始观察，按来源回执补齐可复核公司材料。"
                ),
                # Keep the complete exact stage row alongside the provider
                # facts.  This is required for a provider-zero v1->v2
                # re-projection to recover gate and market fields by code.
                "observation": observation_full,
                "stage_observation": dict(observation_full),
                "observation_source": {
                    "kind": "LIVE_STAGE_ARTIFACT",
                    "stage_id": input_data["stage_id"],
                    "source_last_bar_time": observation.get("source_last_bar_time"),
                    "artifact_sha256": input_data.get("input_source_sha256"),
                    "code": code,
                },
                "source": source,
                "source_url": source_url,
                "source_status": row_status,
                "source_reason": result.get("reason"),
                "source_failure_detail": result.get("failure_detail"),
                # The recommendation builder below classifies the observation
                # timing from the exact target date, stage bar, source publish
                # time and product generation time.  Keep the legacy fields,
                # but derive them so a complete current-day row is not
                # mislabeled as an historical backfill before it is reviewed.
                "origin": "CURRENT_DAY_RESEARCH",
                "historical_system_available": False,
                "historical_system_note": "当前日目标09:40之后生成；仅证明请求时点可对齐，不证明系统在09:40已消费；研究建议仍受 RESEARCH_ONLY 边界约束。",
                **FOUR_FLAGS,
            }
            for key in (
                "action_level", "trade_status", "trade_status_contract", "formal_eligible", "last_price",
                "current_price", "price", "support", "support_price", "support_primary_price", "pressure",
                "pressure_price", "resistance", "resistance_price", "volume", "volume_ratio", "rank",
            ):
                if key in observation:
                    research_row[key] = observation[key]
            research_row["stage_rank"] = observation.get("stage_rank")
            research_row["stage_row_status"] = observation.get("status")
            research_row["stage_status"] = stage_status
            recommendation = build_research_recommendation(
                observation=observation,
                result={**dict(result), "status": row_status, "facts": facts, "source": source},
                target_trade_date=input_data["target_trade_date"],
                cutoff_at=input_data["cutoff_at"],
                generated_at=generated,
                input_source_sha256=input_data.get("input_source_sha256"),
                stage_status=stage_status,
                cannot_confirm=stage_cannot_confirm,
            )
            research_row["research_recommendation"] = recommendation
            research_row["observation_timing_status"] = recommendation.get("timing_status")
            if recommendation.get("timing_status") != "CURRENT_AFTER_CUTOFF":
                research_row["origin"] = "AUTOMATIC_HISTORICAL_BACKFILL"
                research_row["historical_system_available"] = False
                research_row["historical_system_note"] = "本产品由目标日请求后回溯采集；不证明目标09:40系统当时已消费该研究。"
            product_rows.append(research_row)
        assign_investment_priorities(product_rows)
        recommendations = [
            row["research_recommendation"]
            for row in product_rows
            if isinstance(row.get("research_recommendation"), Mapping)
        ]
        current_day_rows = bool(recommendations) and all(
            recommendation.get("timing_status") == "CURRENT_AFTER_CUTOFF"
            for recommendation in recommendations
        )
        product = {
            "schema_version": PRODUCT_SCHEMA_VERSION,
            "kind": "MANAGER_RESEARCH_PRODUCT",
            "product_id": f"manager-research-{input_data['target_trade_date']}-{input_data['input_identity'][:24]}",
            "owner": "stock_investment_research_manager",
            "provider_id": next(
                (
                    receipt.get("provider_id")
                    for receipt in source_receipts
                    if isinstance(receipt.get("provider_id"), str) and receipt.get("provider_id")
                ),
                None,
            ),
            "target_trade_date": input_data["target_trade_date"],
            "stage_id": input_data["stage_id"],
            "market": input_data["market"],
            "cutoff_at": input_data["cutoff_at"],
            "input_identity": input_data["input_identity"],
            "input_source_sha256": input_data.get("input_source_sha256"),
            "input_row_count": input_data["input_row_count"],
            "status": overall_status,
            "stage_status": stage_status,
            "cannot_confirm": stage_cannot_confirm,
            "content_contract_version": CONTENT_CONTRACT_VERSION,
            "content_contract_revision": CONTENT_CONTRACT_REVISION,
            "pdf_parser": "pypdf",
            "pdf_parser_version": "6.10.0",
            "coverage": {
                "requested_rows": len(observations),
                "ready_rows": ready_count,
                "cannot_confirm_rows": len(observations) - ready_count,
                "coverage_ratio": round(ready_count / len(observations), 6) if observations else 0.0,
            },
            "rows": product_rows,
            "recommendation_summary": recommendation_summary(recommendations),
            "source_receipts": source_receipts,
            "generated_at": generated,
            "historical_system_available": False,
            "historical_system_note": (
                "当前日目标09:40之后生成；仅证明请求时点可对齐，不证明系统在09:40已消费；研究建议仍受 RESEARCH_ONLY 边界约束。"
                if current_day_rows
                else "自动研究结果是目标日请求后的历史回溯；不回填旧人工日期 JSON，也不宣称当时已在线消费。"
            ),
            **FOUR_FLAGS,
            "safety": dict(FOUR_FLAGS),
        }
        if event_batch is not None:
            return ManagerResearchJobService._attach_catalyst_to_product(product, event_batch, observations)
        return product
