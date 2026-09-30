"""Small, injectable collector bridges for the eight-stage raw contract.

The deployed Futu, PyTDX HQ, PyTDX ExHQ, and auction probes are intentionally
not started by this package.  Each adapter below owns the route identity and
normalizes an injected bridge result into :class:`SourceResult`; production
integration supplies the already-reviewed bridge callable, while unit tests
remain entirely offline.  This keeps route selection real and explicit rather
than leaving acquisition as an untyped facade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .acquisition import AcquisitionPlan, SourceResult, _coerce_source_result


Bridge = Callable[[str, str, str, tuple[str, ...]], SourceResult | Mapping[str, Any] | Any]


@dataclass(frozen=True)
class CollectorAdapter:
    """One route-bound bridge; its callable is injected by the caller."""

    source_id: str
    route: str
    bridge: Bridge

    def collect(self, plan: AcquisitionPlan, market: str) -> SourceResult:
        codes = plan.codes_for(market)
        try:
            raw = self.bridge(plan.trade_date, plan.stage_id, market, tuple(codes))
        except Exception as error:
            return SourceResult(
                self.source_id,
                "CANNOT_CONFIRM",
                cannot_confirm=(f"{self.route} adapter failed: {type(error).__name__}",),
                error=str(error),
                requested_rows=len(codes) if codes else None,
                source_evidence=(f"route={self.route}",),
            )
        result = _coerce_source_result(raw, self.source_id)
        if result.source_id != self.source_id:
            result = SourceResult(
                self.source_id,
                result.status,
                rows=result.rows,
                cannot_confirm=result.cannot_confirm,
                error=result.error,
                requested_rows=result.requested_rows,
                missing_symbols=result.missing_symbols,
                source_evidence=result.source_evidence,
            )
        if f"route={self.route}" not in result.source_evidence:
            result = SourceResult(
                result.source_id,
                result.status,
                rows=result.rows,
                cannot_confirm=result.cannot_confirm,
                error=result.error,
                requested_rows=result.requested_rows,
                missing_symbols=result.missing_symbols,
                source_evidence=(*result.source_evidence, f"route={self.route}"),
            )
        return result

    def __call__(self, plan: AcquisitionPlan, market: str) -> SourceResult:
        return self.collect(plan, market)


class FutuMinuteAdapter(CollectorAdapter):
    def __init__(self, bridge: Bridge):
        super().__init__("futu", "futu_read_only_minute_window", bridge)


class PyTDXHQAdapter(CollectorAdapter):
    def __init__(self, bridge: Bridge):
        super().__init__("pytdx_hq", "pytdx_hq_large_universe", bridge)


class PyTDXExHQAdapter(CollectorAdapter):
    def __init__(self, bridge: Bridge):
        super().__init__("pytdx_exhq", "futu_read_only_with_pytdx_fallback", bridge)


class AuctionAdapter(CollectorAdapter):
    """09:25 adapter preserving exact-date and auction-window evidence."""

    def __init__(self, bridge: Bridge, *, market: str):
        route = (
            "a_share_exact_date_auction_transaction"
            if market == "A_SHARE"
            else "hk_connect_0915_0920_auction_second_filter"
        )
        source_id = "a_share_auction" if market == "A_SHARE" else "hk_auction_second_filter"
        super().__init__(source_id, route, bridge)


def adapters_for_plan(
    plan: AcquisitionPlan,
    *,
    futu: CollectorAdapter | None = None,
    pytdx_hq: CollectorAdapter | None = None,
    pytdx_exhq: CollectorAdapter | None = None,
    a_share_auction: CollectorAdapter | None = None,
    hk_auction: CollectorAdapter | None = None,
) -> dict[str, CollectorAdapter]:
    """Bind route-specific adapters to the exact markets in ``plan``."""
    bound: dict[str, CollectorAdapter] = {}
    if plan.stage_id == "STAGE_0925":
        if a_share_auction is not None and "A_SHARE" in plan.markets:
            bound["A_SHARE"] = a_share_auction
        if hk_auction is not None and "HK_CONNECT" in plan.markets:
            bound["HK_CONNECT"] = hk_auction
    else:
        if "A_SHARE" in plan.markets:
            adapter = pytdx_hq if plan.a_share_route == "pytdx_hq_large_universe" else futu
            if adapter is not None:
                bound["A_SHARE"] = adapter
        if "HK_CONNECT" in plan.markets:
            adapter = pytdx_exhq or futu
            if adapter is not None:
                bound["HK_CONNECT"] = adapter
    if set(bound) != set(plan.markets):
        raise ValueError(f"missing route adapter for {plan.markets!r}")
    for market, adapter in bound.items():
        expected = plan.a_share_route if market == "A_SHARE" else plan.hk_route
        if plan.stage_id == "STAGE_0925":
            expected = (
                "a_share_exact_date_auction_transaction"
                if market == "A_SHARE"
                else "hk_connect_0915_0920_auction_second_filter"
            )
        if adapter.route != expected and not (
            market == "HK_CONNECT" and adapter.route == "futu_read_only_with_pytdx_fallback"
        ):
            raise ValueError(f"adapter route mismatch for {market}: {adapter.route!r} != {expected!r}")
    return bound


__all__ = [
    "AuctionAdapter",
    "CollectorAdapter",
    "FutuMinuteAdapter",
    "PyTDXExHQAdapter",
    "PyTDXHQAdapter",
    "adapters_for_plan",
]
