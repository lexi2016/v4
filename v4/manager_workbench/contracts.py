"""MWB_V1_20261013: shared A/B/C contract. No legacy business imports."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer

SCHEMA_VERSION = "v4.manager_workbench.v1"
HK = ZoneInfo("Asia/Hong_Kong")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Phase(str, Enum):
    PREOPEN = "PREOPEN"
    INTRADAY = "INTRADAY"
    NEXT_DAY = "NEXT_DAY"
    RETROSPECTIVE = "RETROSPECTIVE"
    MANUAL = "MANUAL"


class Lane(str, Enum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    US_MAPPING = "US_MAPPING"
    OVERSOLD = "OVERSOLD"
    STAGE_REFERENCE = "STAGE_REFERENCE"
    CLOSE_REFERENCE = "CLOSE_REFERENCE"


class LaneState(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    READY = "READY"
    READY_EMPTY = "READY_EMPTY"
    PARTIAL = "PARTIAL"
    INPUT_MISSING = "INPUT_MISSING"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    USER_STOPPED = "USER_STOPPED"


class Decision(str, Enum):
    SELECTED = "SELECTED"
    CONDITIONAL_WATCH = "CONDITIONAL_WATCH"
    UNASSESSED = "UNASSESSED"
    NOT_SELECTED = "NOT_SELECTED"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


class Verification(str, Enum):
    VERIFIED = "VERIFIED"
    CANNOT_CONFIRM = "CANNOT_CONFIRM"
    INVALID = "INVALID"


def iso_time(v: str) -> str:
    try:
        d = datetime.fromisoformat(v)
    except (ValueError, TypeError) as exc:
        raise ValueError("TIME_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("TIME_TZ_REQUIRED")
    return v


def validate_date(v: str) -> str:
    if not isinstance(v, str) or len(v) != 8 or not v.isascii() or not v.isdigit():
        raise ValueError("DATE_FORMAT_INVALID")
    try:
        datetime.strptime(v, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("DATE_INVALID") from exc
    return v


def canonical(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


class RunContext(StrictModel):
    market: Literal["HK_CONNECT"] = "HK_CONNECT"
    target_date: str
    phase: Phase
    cutoff: str
    trigger: Literal["SCHEDULED", "MANUAL"]
    source_sessions: dict[str, str | None] = Field(default_factory=dict)
    rules_version: str
    scope_refs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_date")
    @classmethod
    def date_check(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("cutoff")
    @classmethod
    def cutoff_check(cls, v: str) -> str:
        return iso_time(v)


class EvidenceRef(StrictModel):
    evidence_id: str
    owner: str
    role: str
    source_date: str | None = None
    source_session: str | None = None
    observed_at: str | None = None
    captured_at: str | None = None
    available_at: str | None = None
    sha256: str | None = None
    artifact_ref: str | None = None
    manifest_ref: str | None = None
    receipt_ref: str | None = None
    source_url: str | None = None
    verification: Verification
    gaps: list[str] = Field(default_factory=list)

    @field_validator("observed_at", "captured_at", "available_at")
    @classmethod
    def time_check(cls, v: str | None) -> str | None:
        return iso_time(v) if v is not None else None


class Coverage(StrictModel):
    scope_count: int | None = Field(default=None, ge=0)
    observed_count: int | None = Field(default=None, ge=0)
    assessed_count: int | None = Field(default=None, ge=0)
    unassessed_count: int | None = Field(default=None, ge=0)
    gaps: list[str] = Field(default_factory=list)


class InputBatch(StrictModel):
    context: RunContext
    lane: Lane
    universe_ref: str | None
    records: list[dict[str, Any]]
    evidence_refs: list[EvidenceRef]
    input_sha256: str
    scope_description: str
    coverage: Coverage
    gaps: list[str] = Field(default_factory=list)


class MappingPath(StrictModel):
    path_id: str
    symbol: str
    us_symbol: str | None = None
    relation_type: str | None = None
    role: Literal["INDIVIDUAL", "SECTOR_CONTEXT"] = "INDIVIDUAL"
    scope: Literal["current_supported", "dated_weak", "pending", "excluded"] = "pending"
    status: Literal["PASS", "PENDING", "REJECT"] = "PENDING"
    direction: Literal["POSITIVE", "NEGATIVE", "UNKNOWN"] = "UNKNOWN"
    strict_supported: bool = False
    primary_theme: str | None = None
    return_pct: str | None = None
    source_session: str | None = None
    available_at: str | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    # Absent in historical snapshots; only the normalizer certifies source quotes.
    quote_verified: bool | None = None
    quote_available_at: str | None = None
    focus_theme: str | None = None

    @model_serializer(mode="wrap")
    def serialize_quote_compatible(self, handler):
        value=handler(self)
        if self.quote_verified is None:value.pop("quote_verified",None)
        if self.quote_available_at is None:value.pop("quote_available_at",None)
        if self.focus_theme is None:value.pop("focus_theme",None)
        return value


class ResearchCandidate(StrictModel):
    symbol: str
    name: str | None = None
    research_state: Literal["current_supported", "dated_weak", "pending"]
    direction: Literal["POSITIVE", "NEGATIVE", "CONFLICT", "UNKNOWN"] = "UNKNOWN"
    primary_path_id: str | None = None
    paths: list[MappingPath] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    # None denotes an older saved contract. Omit it to preserve its product hash.
    industry_matches: list[dict[str, Any]] | None = None

    @model_serializer(mode="wrap")
    def serialize_industry_compatible(self, handler):
        value = handler(self)
        if self.industry_matches is None:
            value.pop("industry_matches", None)
        return value


class GateDecision(StrictModel):
    gate: str
    state: Literal["PASS", "PENDING", "REJECT"]
    actual: Any = None
    threshold: Any = None
    reasons: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class StrictSelectionDecision(StrictModel):
    symbol: str
    state: Literal["PASS", "PENDING", "REJECT"]
    decision: Literal["SELECTED", "QUALIFIED_NOT_SELECTED", "PENDING", "REJECTED"]
    qualified: bool = False
    rank: int | None = None
    primary_path_id: str | None = None
    primary_theme: str | None = None
    primary_return_pct: str | None = None
    gates: list[GateDecision] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_selection(self):
        if self.decision in {"SELECTED", "QUALIFIED_NOT_SELECTED"} and (
                self.state != "PASS" or not self.qualified or not self.gates
                or any(g.state != "PASS" for g in self.gates)):
            raise ValueError("STRICT_SELECTION_REQUIRES_ALL_GATES_PASS")
        return self


class TriggeredFocusDecision(StrictModel):
    symbol: str
    decision: Literal["SELECTED", "CAPPED", "NOT_TRIGGERED", "PENDING"]
    eligible: bool = False
    rank: int | None = None
    primary_path_id: str | None = None
    primary_us_symbol: str | None = None
    primary_theme: str | None = None
    primary_return_pct: str | None = None
    hk_mean_turnover20_hkd: str | None = None
    reasons: list[str] = Field(default_factory=list)


class TriggeredFocusSummary(StrictModel):
    cutoff: str
    source_session: str | None = None
    policy_version: str
    policy_sha256: str
    counts: dict[str, int]
    decisions: list[TriggeredFocusDecision]

    @model_validator(mode="after")
    def consistent_focus(self):
        if len({d.symbol for d in self.decisions})!=len(self.decisions):raise ValueError("FOCUS_DUPLICATE_SYMBOL")
        expected={key:sum(d.decision==state for d in self.decisions) for key,state in
            [('selected','SELECTED'),('capped','CAPPED'),('not_triggered','NOT_TRIGGERED'),('pending','PENDING')]}
        expected.update(candidate_count=len(self.decisions),eligible=sum(d.eligible for d in self.decisions))
        if any(self.counts.get(key)!=value for key,value in expected.items()):raise ValueError("FOCUS_COUNTS_MISMATCH")
        if expected['selected']>10:raise ValueError("FOCUS_TOP10_CAP")
        themes={}
        for d in self.decisions:
            if d.eligible!=(d.decision in {'SELECTED','CAPPED'}):raise ValueError("FOCUS_ELIGIBILITY_MISMATCH")
            if d.decision=='SELECTED':
                if not d.primary_theme or d.rank is None:raise ValueError("FOCUS_PRIMARY_OR_RANK_MISSING")
                themes[d.primary_theme]=themes.get(d.primary_theme,0)+1
        if any(v>3 for v in themes.values()):raise ValueError("FOCUS_THEME3_CAP")
        return self


class MappingSelectionSummary(StrictModel):
    schema_version: Literal["v4.us_hk.selection.v1"] = "v4.us_hk.selection.v1"
    policy_version: str
    policy_sha256: str
    engine_identity: str
    target_date: str
    source_session: str | None = None
    price_session: str | None = None
    cutoff: str
    candidates: list[ResearchCandidate] = Field(default_factory=list)
    strict_decisions: list[StrictSelectionDecision] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    evaluation_complete: bool = False
    gaps: list[str] = Field(default_factory=list)
    listing_mode: Literal["INDUSTRY_MATCH", "TRIGGERED_FOCUS"] | None = None
    listing_policy_version: str | None = None
    listing_policy_sha256: str | None = None
    focus: TriggeredFocusSummary | None = None

    @model_serializer(mode="wrap")
    def serialize_industry_compatible(self, handler):
        value = handler(self)
        for key in ("listing_mode", "listing_policy_version", "listing_policy_sha256", "focus"):
            if getattr(self, key) is None:
                value.pop(key, None)
        return value


class LaneResult(StrictModel):
    lane: Lane
    state: LaneState
    rows: list[dict[str, Any]]
    coverage: Coverage
    input_sha256: str
    rules_version: str
    run_id: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    selection: MappingSelectionSummary | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy_compatible(self, handler):
        value = handler(self)
        if self.selection is None:
            value.pop("selection", None)
        return value


class StockDecision(StrictModel):
    market: Literal["HK_CONNECT"] = "HK_CONNECT"
    symbol: str = Field(pattern=r"^HK\.[0-9]{5}$")
    name: str | None = None
    decision: Decision
    lane_decisions: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    membership_status: str | None = None

    @field_validator("symbol")
    @classmethod
    def symbol_check(cls, v: str) -> str:
        import re
        if re.fullmatch(r"HK\.[0-9]{5}", v) is None:
            raise ValueError("SYMBOL_INVALID")
        return v


class Counts(StrictModel):
    selected: int | None = Field(default=None, ge=0)
    watch: int | None = Field(default=None, ge=0)
    unassessed: int | None = Field(default=None, ge=0)
    observation_only: int | None = Field(default=None, ge=0)
    not_selected: int | None = Field(default=None, ge=0)


class Safety(StrictModel):
    RESEARCH_ONLY: Literal[True] = True
    production_allowed: Literal[False] = False
    buy_gate_updated: Literal[False] = False
    orders_sent: Literal[False] = False


class PlanSnapshot(Safety):
    schema_version: Literal["v4.manager_workbench.v1"] = SCHEMA_VERSION
    context: RunContext
    run_id: str
    input_sha256: str
    product_sha256: str
    generated_at: str
    available_at: str
    lanes: list[LaneResult]
    stocks: list[StockDecision]
    counts: Counts
    changes: dict[str, Any] = Field(default_factory=dict)
    review_refs: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("generated_at", "available_at")
    @classmethod
    def time_check(cls, v: str) -> str:
        return iso_time(v)

    @model_validator(mode="after")
    def ensure_consistent(self) -> "PlanSnapshot":
        for lane in self.lanes:
            if lane.run_id != self.run_id:
                raise ValueError("LANE_RUN_MISMATCH")
            if lane.rules_version != self.context.rules_version:
                raise ValueError("RULES_VERSION_MISMATCH")
        if self.product_sha256 != product_digest(self.model_dump(mode="json")):
            raise ValueError("PRODUCT_SHA_MISMATCH")
        if len({s.symbol for s in self.stocks}) != len(self.stocks):
            raise ValueError("DUPLICATE_STOCK")
        by_decision = {
            "selected": Decision.SELECTED, "watch": Decision.CONDITIONAL_WATCH,
            "unassessed": Decision.UNASSESSED, "observation_only": Decision.OBSERVATION_ONLY,
            "not_selected": Decision.NOT_SELECTED,
        }
        for key, decision in by_decision.items():
            actual = sum(row.decision == decision for row in self.stocks)
            count = getattr(self.counts, key)
            if count is not None and count != actual:
                raise ValueError("COUNTS_MISMATCH")
        return self


class JobRecord(StrictModel):
    job_id: str
    run_id: str
    context: RunContext
    state: JobState
    step: str
    started_at: str | None = None
    finished_at: str | None = None
    last_progress_at: str | None = None
    completed_count: int = Field(default=0, ge=0)
    total_count: int | None = Field(default=None, ge=0)
    failed_steps: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    retryable: bool = False
    execution_refs: list[dict[str, Any]] = Field(default_factory=list)


class ReviewSummary(StrictModel):
    target_date: str
    plan_run_id: str
    evaluation_scope_ref: str | None = None
    mode: str
    ranking_date: str | None = None
    top20_rows: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    strict_coverage: dict[str, Any] = Field(default_factory=dict)
    extended_coverage: dict[str, Any] = Field(default_factory=dict)
    selected_denominator: int | None = Field(default=None, ge=0)
    lane_incremental_coverage: dict[str, Any] = Field(default_factory=dict)
    uncovered_reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("target_date")
    @classmethod
    def date_check(cls, v: str) -> str:
        return validate_date(v)


def product_digest(snapshot: dict[str, Any]) -> str:
    """Hash every persisted field except the self-referential product_sha256."""
    return digest({k: v for k, v in snapshot.items() if k != "product_sha256"})


def seal_snapshot(data: dict[str, Any]) -> PlanSnapshot:
    body = {"schema_version": SCHEMA_VERSION, **Safety().model_dump(), **data}
    # Hash the exact normalized persisted representation, including nested defaults.
    body["context"] = RunContext.model_validate(body["context"]).model_dump(mode="json")
    body["lanes"] = [LaneResult.model_validate(row).model_dump(mode="json") for row in body["lanes"]]
    body["stocks"] = [StockDecision.model_validate(row).model_dump(mode="json") for row in body["stocks"]]
    body["counts"] = Counts.model_validate(body["counts"]).model_dump(mode="json")
    for key, default in (("changes", {}), ("review_refs", []), ("gaps", [])):
        body.setdefault(key, default)
    body["product_sha256"] = product_digest(body)
    return PlanSnapshot.model_validate(body)


def schema() -> dict[str, Any]:
    """Public JSON Schema, stable schema identity, with explicit type definitions."""
    definitions = {model.__name__: model.model_json_schema() for model in (
        RunContext, EvidenceRef, Coverage, InputBatch, LaneResult,
        StockDecision, Counts, PlanSnapshot, JobRecord, ReviewSummary,
        MappingPath, ResearchCandidate, GateDecision, StrictSelectionDecision, MappingSelectionSummary,
    )}
    return {"schema_version": SCHEMA_VERSION, "models": definitions}


def envelope(state: str, data: Any = None, gaps: list[str] | None = None) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "state": state, "data": data,
            "gaps": gaps or [], **Safety().model_dump()}
