"""HTTP contract for preselection pools; data ownership stays in its service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query

from apps.api.v4_api.preselection_service import PreselectionPoolService


def create_preselection_router(
    service: PreselectionPoolService,
    *,
    get_catalog: Callable[[], dict[str, Any]],
    validate_date: Callable[[str], str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v4/preselection-pools")
    def preselection_pools(
        date: str | None = None,
        limit: int = Query(default=200, ge=1, le=300),
        offset: int = Query(default=0, ge=0),
        page: int | None = Query(default=None, ge=1),
    ) -> dict:
        requested = validate_date(date) if date is not None else None
        if requested is not None:
            # An exact-date read has no dependency on historical date discovery.
            # The service still verifies that date's original source trios.
            selected = requested
        else:
            catalog = get_catalog()
            selected = catalog["default_date"] or catalog["system_date"]
        page_offset = (page - 1) * limit if page is not None else offset
        response = service.read(selected, limit, offset=page_offset)
        response["requested_date"] = requested
        response["selected_date"] = selected
        response["page"] = page if page is not None else (page_offset // limit) + 1
        return response


    @router.get("/api/v4/research/a-share/top200-hit")
    def top200_hit(date: str) -> dict:
        from pathlib import Path
        import os
        from fastapi import HTTPException
        from ops.build_a_share_pool_top200 import read_daily_projection
        selected=validate_date(date)
        configured=os.environ.get('V4_A_SHARE_DAILY_PRODUCT_ROOT')
        stages=os.environ.get('V4_OPENING_SELECTION_ROOT')
        if not configured or not stages:raise HTTPException(503,'TOP200_SOURCE_ROOT_NOT_CONFIGURED')
        root=Path(configured)
        if (root/'daily_products/a_share/index.json').is_file():root=root/'daily_products/a_share'
        legacy=Path(__file__).resolve().parents[3]/'apps/web/dist/top200-hit.json'
        try:return read_daily_projection(selected,service.read,root,Path(stages),legacy)
        except (OSError,ValueError,KeyError,TypeError)as error:raise HTTPException(409,'TOP200_EXACT_SOURCE_UNCONFIRMED:'+str(error))from error

    return router
