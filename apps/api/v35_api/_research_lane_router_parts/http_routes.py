"""apps.api.v35_api.research_lane_router: http_routes (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


from typing import Any, Mapping

def _build_research_lane_route_context(_v4_scope, data_root, *, shared_data_root, morning_news_data_root, ledger_root, us_market_data_root):
    router = _v4_global(_v4_scope, 'APIRouter')(prefix="/api/v3/research", tags=["research-lane"])
    source = _v4_global(_v4_scope, 'ResearchLaneSource')(data_root, ledger_root=ledger_root)
    daily_store = _v4_global(_v4_scope, 'ResearchArchiveStore')(data_root)
    peripheral_source = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
    # A bounded consumer binding; no data copying and no fallback across roots.
    market_source = _v4_global(_v4_scope, 'ResearchPeripheralStore')(
        _v4_global(_v4_scope, 'Path')(us_market_data_root) if us_market_data_root is not None else data_root
    )
    market_binding = {
        "source_root": _v4_global(_v4_scope, 'str')(market_source.root),
        "source": "external_finance",
        "read_policy": "EXACT_MANIFEST_RECEIPT_VERIFIED",
        "write_policy": "read_only",
    }
    resolved_morning_news_root = (
        morning_news_data_root
        if morning_news_data_root is not None
        else shared_data_root
    )
    morning_source = (
        _v4_global(_v4_scope, 'SharedMorningNewsReader')(resolved_morning_news_root)
        if resolved_morning_news_root is not None
        else None
    )

    def read_morning(selected: str) -> dict[str, Any] | None:
        return morning_source.read(selected) if morning_source else None

    def read_peripherals(selected: str) -> dict[str, dict[str, Any] | None]:
        return {
            "external_finance": peripheral_source.read_exact(
                selected, "external_finance"
            ),
            "ai_news": peripheral_source.read_exact(selected, "ai_news"),
        }

    def read_daily_archive(selected: str) -> dict[str, Any]:
        """Consume only an exact-date, authoritative full-day product."""
        try:
            product = daily_store.read_day_exact(selected)
        except _v4_global(_v4_scope, 'ValueError') as error:
            consumed = _v4_global(_v4_scope, 'consume_authoritative_research_day')(
                None,
                requested_date=selected,
            )
            consumed["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
                _v4_global(_v4_scope, 'set')(consumed.get("cannot_confirm") or [])
                | {f"RESEARCH_DAY_PRODUCT_READ_FAILED:{error}"}
            )
            return consumed
        return _v4_global(_v4_scope, 'consume_authoritative_research_day')(
            product,
            requested_date=selected,
        )

    def resolve_requested_date(
        research_date: str,
        date: str | None,
    ) -> str | None:
        """Resolve the exact-date compatibility alias without latest fallback."""

        primary = _v4_global(_v4_scope, 'str')(research_date or "").strip()
        alias = _v4_global(_v4_scope, 'str')(date or "").strip()
        if primary and alias and primary != alias:
            raise _v4_global(_v4_scope, 'HTTPException')(
                status_code=422,
                detail="research_date and date must identify the same exact date",
            )
        selected = primary or alias
        if not selected:
            return None
        if not (_v4_global(_v4_scope, 'len')(selected) == 8 and selected.isdigit()):
            raise _v4_global(_v4_scope, 'HTTPException')(status_code=422, detail="research_date must use YYYYMMDD")
        try:
            return _v4_global(_v4_scope, '_date')(selected)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'HTTPException')(
                status_code=422,
                detail="research_date must be a real calendar date",
            ) from error

    def _read_lane(
        research_date: str = _v4_global(_v4_scope, 'Query')(default=""),
        date: str | None = _v4_global(_v4_scope, 'Query')(default=None),
    ) -> dict:
        selected = resolve_requested_date(research_date, date)
        if selected is None:
            payload, hourly_slot, hourly_slot_count = source.read_latest_lane()
            if payload is None:
                return _v4_global(_v4_scope, '_missing')(
                    research_date="",
                    reason="NO_RESEARCH_ARCHIVE_LATEST",
                    identity="LATEST",
                    endpoint_mode="LATEST",
                )
            source_binding = source.artifact_binding(
                _v4_global(_v4_scope, 'str')(payload["archive_date"]),
                slot=hourly_slot,
            )
            return _v4_global(_v4_scope, '_lane_response')(
                payload,
                research_date=_v4_global(_v4_scope, 'str')(payload["archive_date"]),
                endpoint_mode="LATEST",
                daily_archive=read_daily_archive(_v4_global(_v4_scope, 'str')(payload["archive_date"])),
                hourly_slot=hourly_slot,
                hourly_slot_count=hourly_slot_count,
                source_binding=source_binding,
                morning_news=read_morning(_v4_global(_v4_scope, 'str')(payload["archive_date"])),
                peripherals=read_peripherals(_v4_global(_v4_scope, 'str')(payload["archive_date"])),
            )
        payload, hourly_slot, hourly_slot_count = source.read_exact_lane(selected)
        if payload is None:
            status_lane = source.read_status_lane(selected)
            if status_lane is not None:
                return _v4_global(_v4_scope, '_status_only_lane_response')(
                    status_lane,
                    research_date=selected,
                    endpoint_mode="EXACT",
                    page_trade_date=None,
                    source_binding={
                        **source.binding(),
                        "status": "STATUS_ONLY",
                        "source_date": selected,
                        "slot": "",
                        "mode": "LIVE",
                    },
                    morning_news=read_morning(selected),
                    peripherals=read_peripherals(selected),
                )
            return _v4_global(_v4_scope, '_missing')(
                research_date=selected,
                reason="RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
                identity=selected,
                endpoint_mode="EXACT",
            )
        source_binding = source.artifact_binding(selected, slot=hourly_slot)
        return _v4_global(_v4_scope, '_lane_response')(
            payload,
            research_date=selected,
            endpoint_mode="EXACT",
            daily_archive=read_daily_archive(selected),
            hourly_slot=hourly_slot,
            hourly_slot_count=hourly_slot_count,
            source_binding=source_binding,
            morning_news=read_morning(selected),
            peripherals=read_peripherals(selected),
        )
    return {
        "router": router, "source": source, "daily_store": daily_store,
        "peripheral_source": peripheral_source, "market_source": market_source,
        "market_binding": market_binding, "morning_source": morning_source,
        "read_lane": _read_lane,
    }
