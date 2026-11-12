"""Shared acquisition baseline facade used by the stage center.

This module intentionally exposes source routing and persistence as narrow
interfaces.  Production integration can inject the deployed Futu/PyTDX
collector callables; batch 1 never starts OpenD, QMT, or a service itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .candidate_input import CandidateInput, read_candidate_input
from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .raw_store import RawStore

SOURCE_PRIORITY = ("futu", "pytdx", "qmt_tdxqt")
FUTU_SUBSCRIPTION_LIMIT = 100


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    status: str
    rows: tuple[dict[str, Any], ...] = ()
    cannot_confirm: tuple[str, ...] = ()
    error: str = ""
    requested_rows: int | None = None
    missing_symbols: tuple[str, ...] = ()
    source_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "READY",
            "PARTIAL_WITH_ROWS",
            "READY_EMPTY",
            "CANNOT_CONFIRM",
        }:
            raise ValueError(
                "SourceResult.status must be one of READY/PARTIAL_WITH_ROWS/READY_EMPTY/CANNOT_CONFIRM"
            )
        if self.requested_rows is not None and self.requested_rows < 0:
            raise ValueError("SourceResult.requested_rows must be non-negative")

    def normalized_status(self) -> str:
        """Map collector adapter statuses to the four public raw states."""
        return {
            "READ_OK": "READY",
            "READ_FAILED": "CANNOT_CONFIRM",
            "DATA_PARTIAL": "PARTIAL_WITH_ROWS",
        }.get(self.status, self.status)


def _coerce_source_result(value: SourceResult | Any, source_id: str) -> SourceResult:
    """Adapt a deployed collector result into the stage-center four-state API."""
    if isinstance(value, SourceResult):
        result = value
    else:
        raw_status = str(getattr(value, "status", "CANNOT_CONFIRM"))
        normalized_status = {
            "READ_OK": "READY",
            "READ_FAILED": "CANNOT_CONFIRM",
            "DATA_PARTIAL": "PARTIAL_WITH_ROWS",
        }.get(raw_status, raw_status)
        result = SourceResult(
            source_id=str(getattr(value, "source_id", source_id)),
            status=normalized_status,
            rows=tuple(getattr(value, "rows", ()) or ()),
            cannot_confirm=tuple(getattr(value, "cannot_confirm", ()) or ()),
            error=str(getattr(value, "error", "") or ""),
            requested_rows=(
                getattr(value, "requested_rows", None)
                if getattr(value, "requested_rows", None) is not None
                else getattr(value, "requested_code_count", None)
            ),
            missing_symbols=tuple(
                getattr(value, "missing_symbols", ())
                or getattr(value, "no_data_codes", ())
                or ()
            ),
            source_evidence=tuple(getattr(value, "source_evidence", ()) or ()),
        )
    return result


@dataclass(frozen=True)
class StageUniverseBinding:
    """Point-in-time universe authority for one market lane.

    The A-share acquisition current and the HK full-universe authority are
    different contracts.  Keeping the binding explicit prevents a missing A
    current pointer from becoming a global Stage Center preflight failure.
    """

    market: str
    trade_date: str
    role: str
    codes: tuple[str, ...]
    source_run_id: str
    sha256: str
    evidence: tuple[str, ...] = ()
    status: str = "READY"
    error: str = ""

    def __post_init__(self) -> None:
        if self.market not in {"A_SHARE", "HK_CONNECT"}:
            raise ValueError("StageUniverseBinding.market must be A_SHARE or HK_CONNECT")
        if self.status not in {"READY", "CANNOT_CONFIRM"}:
            raise ValueError("StageUniverseBinding.status must be READY or CANNOT_CONFIRM")
        if self.status == "READY" and not self.codes:
            raise ValueError("a READY universe binding requires codes")
        if self.status == "CANNOT_CONFIRM" and not self.error:
            raise ValueError("a CANNOT_CONFIRM universe binding requires error")

    @classmethod
    def ready(
        cls,
        *,
        market: str,
        trade_date: str,
        role: str,
        codes: tuple[str, ...],
        source_run_id: str,
        sha256: str,
        evidence: tuple[str, ...] = (),
    ) -> "StageUniverseBinding":
        return cls(
            market=market,
            trade_date=trade_date,
            role=role,
            codes=tuple(codes),
            source_run_id=source_run_id,
            sha256=sha256,
            evidence=tuple(evidence),
        )

    @classmethod
    def unavailable(cls, *, market: str, trade_date: str, reason: str) -> "StageUniverseBinding":
        return cls(
            market=market,
            trade_date=trade_date,
            role="UNAVAILABLE",
            codes=(),
            source_run_id="",
            sha256="",
            evidence=(f"error={reason}",),
            status="CANNOT_CONFIRM",
            error=reason,
        )


@dataclass(frozen=True)
class AcquisitionPlan:
    trade_date: str
    stage_id: str
    markets: tuple[str, ...]
    candidate_input: CandidateInput
    a_share_route: str | None
    hk_route: str
    historical_backfill: bool = False
    universe_bindings: Mapping[str, StageUniverseBinding] = field(default_factory=dict)
    safety: Mapping[str, bool] = field(default_factory=lambda: dict(SAFETY_FLAGS))

    def codes_for(self, market: str) -> tuple[str, ...]:
        binding = self.universe_bindings.get(market)
        if binding is not None:
            return binding.codes if binding.status == "READY" else ()
        return self.candidate_input.codes if market == "A_SHARE" else ()


Collector = Callable[[AcquisitionPlan, str], SourceResult]


def build_plan(
    candidate_input_root: Path | str,
    trade_date: str,
    stage_id: str,
    *,
    expected_current_sha256: str | None = None,
    candidate: CandidateInput | None = None,
    universe_bindings: Mapping[str, StageUniverseBinding] | None = None,
    historical_backfill: bool = False,
) -> AcquisitionPlan:
    """Build a read-only plan bound to one candidate current.json SHA."""
    stage = next((item for item in EIGHT_STAGES if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    if candidate is None:
        candidate = read_candidate_input(
            candidate_input_root,
            trade_date,
            expected_current_sha256=expected_current_sha256,
        )
    if stage_id == "STAGE_0925":
        a_share_route = "a_share_exact_date_auction_transaction"
        hk_route = "hk_connect_0915_0920_auction_second_filter"
    elif stage_id == "STAGE_1545_1555":
        a_share_route = None
        hk_route = "futu_read_only_with_pytdx_fallback"
    else:
        a_share_route = (
            "pytdx_hq_large_universe"
            if len(candidate.codes) > FUTU_SUBSCRIPTION_LIMIT
            else "futu_then_pytdx_hq"
        )
        hk_route = "futu_read_only_with_pytdx_fallback"
    return AcquisitionPlan(
        trade_date=trade_date,
        stage_id=stage_id,
        markets=stage.markets,
        candidate_input=candidate,
        a_share_route=a_share_route,
        hk_route=hk_route,
        historical_backfill=historical_backfill,
        universe_bindings=dict(universe_bindings or {}),
    )


def run_source_priority(
    runners: Mapping[str, Callable[[], SourceResult]],
) -> tuple[SourceResult, tuple[SourceResult, ...]]:
    """Run the fixed Futu -> PyTDX -> QMT ordering once per source."""
    if set(runners) != set(SOURCE_PRIORITY):
        raise ValueError(f"runners must provide exactly {SOURCE_PRIORITY!r}")
    results: list[SourceResult] = []
    for source_id in SOURCE_PRIORITY:
        result = _coerce_source_result(runners[source_id](), source_id)
        if result.source_id != source_id:
            raise ValueError(f"runner {source_id!r} returned {result.source_id!r}")
        results.append(result)
        if result.normalized_status() == "READY":
            break
    selected = next((item for item in results if item.normalized_status() == "READY"), None)
    selected = selected or next((item for item in results if item.rows), None) or results[0]
    return selected, tuple(results)


def publish_stage_bundle(
    root: Path | str,
    trade_date: str,
    stage_id: str,
    results: Mapping[str, SourceResult],
) -> dict[str, Any]:
    """Publish independent market artifacts and one immutable bundle summary."""
    stage = next((item for item in EIGHT_STAGES if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    expected = set(stage.markets)
    if set(results) != expected:
        raise ValueError(f"bundle markets must equal {sorted(expected)!r}")
    market_receipts: dict[str, dict[str, Any]] = {}
    store = RawStore(root)
    for market in stage.markets:
        result = results[market]
        window = (
            stage.hk_window
            if stage_id == "STAGE_0925" and market == "HK_CONNECT"
            else stage.window
        )
        cutoff_at = (
            "09:20:05"
            if stage_id == "STAGE_0925" and market == "HK_CONNECT"
            else stage.cutoff
        )
        published = store.publish(
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            source_id=result.source_id,
            source_status=result.normalized_status(),
            rows=result.rows,
            cannot_confirm=result.cannot_confirm,
            source_evidence=tuple(
                dict.fromkeys(
                    (
                        *result.source_evidence,
                        "exact_date=" + trade_date,
                        "stage_id=" + stage_id,
                        "market=" + market,
                        "window=" + window,
                        "cutoff_at=" + cutoff_at,
                    )
                )
            ),
            requested_rows=result.requested_rows,
            missing_symbols=result.missing_symbols,
            window=window,
            cutoff_at=cutoff_at,
        )
        # ``already_exists`` is an operational return marker, not bundle
        # identity.  Excluding it keeps a byte-for-byte identical retry on
        # the same market inputs idempotent.
        published.pop("already_exists", None)
        market_receipts[market] = published
    statuses = {item["status"] for item in market_receipts.values()}
    if statuses == {"READY"}:
        status = "READY"
    elif statuses == {"READY_EMPTY"}:
        status = "READY_EMPTY"
    elif statuses == {"CANNOT_CONFIRM"} and all(item["row_count"] == 0 for item in market_receipts.values()):
        status = "CANNOT_CONFIRM"
    else:
        status = "PARTIAL_WITH_ROWS"
    return store.publish_bundle(
        trade_date=trade_date,
        stage_id=stage_id,
        status=status,
        markets=market_receipts,
    )


def collect_stage_bundle(
    root: Path | str,
    plan: AcquisitionPlan,
    collectors: Mapping[str, Collector],
) -> dict[str, Any]:
    """Run injected market collectors and publish one verified raw bundle.

    The adapter boundary is intentionally synchronous and dependency-free:
    production callers inject the deployed Futu/PyTDX bridge, while tests use
    deterministic functions.  No collector is imported, started, or inferred
    by this package.  The caller must provide exactly the markets in the
    frozen stage plan, so a missing market cannot silently become an empty
    result for the other market.
    """
    if set(collectors) != set(plan.markets):
        raise ValueError(f"collectors must provide exactly {plan.markets!r}")
    results: dict[str, SourceResult] = {}
    for market in plan.markets:
        result = _coerce_source_result(collectors[market](plan, market), market)
        if not result.source_id:
            raise ValueError(f"collector for {market!r} returned no source_id")
        results[market] = result
    return publish_stage_bundle(root, plan.trade_date, plan.stage_id, results)


def dry_run_acquisition(
    candidate_input_root: Path | str,
    trade_date: str,
    stage_id: str,
    *,
    expected_current_sha256: str | None = None,
) -> dict[str, Any]:
    """Return route and immutable input evidence without collecting or writing."""
    plan = build_plan(
        candidate_input_root,
        trade_date,
        stage_id,
        expected_current_sha256=expected_current_sha256,
    )
    return {
        "ok": True,
        "status": "DRY_RUN_READY",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "markets": list(plan.markets),
        "candidate_input_current": plan.candidate_input.current_relative,
        "candidate_input_current_sha256": plan.candidate_input.current_sha256,
        "candidate_run_id": plan.candidate_input.run_id,
        "candidate_rows": len(plan.candidate_input.codes),
        "a_share_route": plan.a_share_route,
        "hk_route": plan.hk_route,
        **SAFETY_FLAGS,
    }
