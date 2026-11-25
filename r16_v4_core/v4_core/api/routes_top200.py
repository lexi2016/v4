"""Pure V4 Top200 read-only router aligned 1:1 with active 8873 path, data_date & boolean eligibility."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException, Query

from v4_core.storage.db import V4Store


def _to_bool_eligibility(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val or "").strip().lower()
    return s in {"1", "true", "yes", "eligible_daily_close", "eligible"}


def build_top200_router(store: V4Store) -> APIRouter:
    router = APIRouter(prefix="/api/v4/research", tags=["research-top200"])

    @router.get("/workbench/days/{source_date}/top200")
    def get_top200(source_date: str, revision: str | None = Query(default=None)):
        rows = store.get_top200(source_date)
        if not rows:
            raise HTTPException(status_code=404, detail=f"TOP200_NOT_PUBLISHED:{source_date}")

        formatted = [
            {
                "rank": int(r["rank"]),
                "symbol": r["symbol"],
                "name": r["name"],
                "change_pct": float(r["pct_chg"]),
                "close": float(r["close"]),
                "amount_cny": float(r["amount"]),
                "daily_gain_rank_eligibility": _to_bool_eligibility(r["daily_gain_rank_eligibility"]),
            }
            for r in rows
        ]
        compact_date = source_date.replace("-", "")
        digest = hashlib.sha256(
            json.dumps({"data_date": compact_date, "rows": formatted}, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return {
            "data_date": compact_date,
            "revision": revision,
            "source_generation": digest,
            "input_sha256": digest,
            "numeric_manifest": {"path": f"v4_core://top200/{source_date}/numeric_manifest.json", "sha256": digest},
            "status": "PARTIAL_DESCRIPTIVE",
            "top200": formatted,
            "top200_count": len(formatted),
            "historical_PIT": False,
        }

    return router
