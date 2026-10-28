"""Same-origin manual recovery surface; no browser paths or quote parameters."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from infrastructure.manual_collection import CollectionRefused, ManualCollectionService


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str = Field(pattern=r"^\d{8}$")
    target: Literal["HK_STAGE", "HK_CLOSE"]
    stage_id: Literal["STAGE_1545_1555"] | None = None

    @field_validator("date")
    @classmethod
    def real_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y%m%d")
        return value


def create_manual_collection_router(data_root: Path, *, stage_selection_root=None,
                                    service: ManualCollectionService | None = None) -> APIRouter:
    service = service or ManualCollectionService(data_root, stage_selection_root=stage_selection_root,
                                                 stage_config_path=os.environ.get("V4_MANUAL_COLLECTION_STAGE_CONFIG"))
    router = APIRouter(prefix="/api/v3/manual-collection", tags=["manual-collection"])

    @router.post("")
    def start(body: CollectionRequest, request: Request):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != request.url.scheme or parsed.netloc != request.url.netloc:
                raise HTTPException(403, detail={"code": "ORIGIN_REFUSED", "message": "仅允许同源页面触发补采。"})
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, detail={"code": "ORIGIN_REFUSED", "message": "仅允许同源页面触发补采。"})
        try:
            return service.start(body.date, body.target, body.stage_id)
        except CollectionRefused as error:
            raise HTTPException(409, detail={"code": error.code, "message": error.message}) from error
        except ValueError as error:
            if str(error) == "COLLECTION_BUSY":
                raise HTTPException(409, detail={"code": "COLLECTION_BUSY", "message": "已有补采正在登记，请稍后查看。"}) from error
            raise

    @router.get("/{job_id}")
    def read(job_id: str):
        try:
            return service.read(job_id)
        except FileNotFoundError as error:
            raise HTTPException(404, detail="补采回执不存在。") from error

    return router
