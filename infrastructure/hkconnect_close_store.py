"""V3.5-owned storage for verified full-universe HK Connect close snapshots."""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.stage_store import _assert_safe_tree


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HK_CODE = re.compile(r"^HK\.\d{5}$")


def _positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def validate_close_snapshot(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_5.hkconnect_close_snapshot.v1":
        raise ValueError("invalid HK Connect close snapshot schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    fixed = {
        "status": "READY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("invalid HK Connect close snapshot boundary")
    source_sha = payload.get("source_input_sha256")
    if not isinstance(source_sha, str) or not _SHA256.fullmatch(source_sha):
        raise ValueError("invalid close source SHA-256")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 600:
        raise ValueError("full HK Connect close snapshot requires at least 600 rows")
    universe_count = payload.get("universe_count")
    same_date_count = payload.get("same_date_row_count")
    if (
        isinstance(universe_count, bool)
        or isinstance(same_date_count, bool)
        or universe_count != len(rows)
        or same_date_count != len(rows)
        or float(payload.get("coverage_ratio") or 0.0) < 1.0
    ):
        raise ValueError("close snapshot coverage proof mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("invalid close row")
        code = str(row.get("code") or "")
        if (
            str(row.get("trade_date") or "") != trade_date
            or not _HK_CODE.fullmatch(code)
            or code in seen
            or not _positive(row.get("close"))
            or not _positive(row.get("pre_close"))
        ):
            raise ValueError("invalid or duplicate close row")
        seen.add(code)
    _assert_safe_tree(payload)
    return trade_date


class CloseSnapshotStore(NativeDataStore):
    def import_snapshot(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_close_snapshot(payload)
        relative = f"hkconnect_close_snapshots/{trade_date}.json"
        receipt = f"receipts/hkconnect_close_snapshots/{trade_date}.json"
        with self._lock():
            result = self._import(relative, payload, receipt)
        return {**result, "payload_path": relative}

    def read_snapshot(self, trade_date: str) -> tuple[dict[str, Any], str]:
        trade_date = _date(trade_date)
        relative = f"hkconnect_close_snapshots/{trade_date}.json"
        receipt_path = f"receipts/hkconnect_close_snapshots/{trade_date}.json"
        if not self._path(relative).is_file():
            raise FileNotFoundError(relative)
        try:
            payload = self._read(relative)
            digest = _sha256(payload)
            manifest = self._manifest()
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("HK Connect close snapshot evidence cannot be read") from error
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": trade_date,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("HK Connect close snapshot manifest or receipt mismatch")
        if validate_close_snapshot(payload) != trade_date:
            raise ValueError("HK Connect close snapshot identity mismatch")
        return payload, digest
