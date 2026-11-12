"""Verified V4-owned storage for the opening second-filter v1.1 artifact."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from domains.opening_second_filter import MODEL_ID, SCHEMA_VERSION, TOP_N
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.stage_store import _assert_safe_tree


def validate_opening_second_filter(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid v1.1 opening second-filter schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    if (
        payload.get("model_id") != MODEL_ID
        or payload.get("version") != "1.1"
        or payload.get("stage_id") != "STAGE_0925"
        or payload.get("signal_cutoff") != "09:19:59"
        or payload.get("publication_time") != "09:20:00"
        or payload.get("required_row_count") != TOP_N
    ):
        raise ValueError("invalid frozen v1.1 identity")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("row_count") != len(rows):
        raise ValueError("invalid v1.1 row count")
    if payload.get("status") == "AUCTION_SECOND_FILTER_READY" and len(rows) != TOP_N:
        raise ValueError("ready v1.1 artifact must contain Top20")
    if [row.get("rank") for row in rows if isinstance(row, Mapping)] != list(
        range(1, len(rows) + 1)
    ):
        raise ValueError("invalid v1.1 row ranks")
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not str(row.get("code") or "").startswith("HK.")
            or row.get("recommendation_status") != "WATCH_ONLY"
        ):
            raise ValueError("invalid v1.1 row")
    fixed = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("unsafe v1.1 boundary")
    _assert_safe_tree(payload)
    return trade_date


class OpeningSecondFilterStore(NativeDataStore):
    def publish(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        trade_date = validate_opening_second_filter(payload)
        relative = f"opening_second_filter/{trade_date}/STAGE_0925.json"
        receipt = f"receipts/opening_second_filter/{trade_date}/STAGE_0925.json"
        with self._lock():
            result = self._import(relative, payload, receipt)
        return {
            **result,
            "payload_path": relative,
            "row_count": int(payload["row_count"]),
        }

    def read(self, trade_date: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        relative = f"opening_second_filter/{trade_date}/STAGE_0925.json"
        receipt_path = f"receipts/opening_second_filter/{trade_date}/STAGE_0925.json"
        if not self._path(relative).is_file():
            return None
        payload = self._read(relative)
        digest = _sha256(payload)
        manifest = self._manifest()
        receipt = self._read(receipt_path)
        if (
            manifest.get(relative) != digest
            or receipt.get("schema_version") != "v3_import_receipt.v1"
            or receipt.get("payload_path") != relative
            or receipt.get("source_sha256") != digest
            or receipt.get("trade_date") != trade_date
        ):
            raise ValueError("v1.1 manifest or receipt mismatch")
        if validate_opening_second_filter(payload) != trade_date:
            raise ValueError("v1.1 artifact identity mismatch")
        return payload
