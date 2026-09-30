"""V3.5-owned, offline JSON storage for date and preselection contracts."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from typing import Any, Mapping

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.market_time import shanghai_now
from infrastructure.trading_safety import assert_safe_tree, ACTION_KEYS, FALSE_ONLY_KEYS


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("date must be a real calendar date") from error
    return value


class NativeDataStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._io = SafeRoot(self.root)

    def _path(self, relative: str) -> Path:
        return self.root / relative

    def _read(self, relative: str) -> Any:
        return json.loads(self._io.read_bytes(relative).decode("utf-8"))

    def _write(self, relative: str, value: Any) -> None:
        self._io.write_bytes(relative, _canonical_bytes(value))

    @contextmanager
    def _lock(self):
        path = self._path(".import.lock")
        with owned_interprocess_lock(
            path,
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            yield

    def _manifest(self) -> dict[str, str]:
        path = self._path("manifest.json")
        return self._read("manifest.json") if path.exists() else {}

    def _write_manifest(self, manifest: dict[str, str]) -> None:
        self._write("manifest.json", manifest)

    def _import(self, relative: str, value: Mapping[str, Any], receipt_path: str) -> dict[str, str]:
        digest = _sha256(value)
        manifest = self._manifest()
        existing = manifest.get(relative)
        if existing and existing != digest:
            raise ValueError("conflicting re-import")
        receipt = {"schema_version": "v3_import_receipt.v1", "payload_path": relative, "source_sha256": digest, "trade_date": value.get("trade_date")}
        receipt_file = self._path(receipt_path)
        payload_file = self._path(relative)
        if not existing and payload_file.exists():
            if _sha256(self._read(relative)) != digest:
                raise ValueError("conflicting interrupted payload")
            if receipt_file.exists() and self._read(receipt_path) != receipt:
                raise ValueError("conflicting interrupted receipt")
            if not receipt_file.exists():
                self._write(receipt_path, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
            return {"sha256": digest, "receipt_path": receipt_path}
        if not existing and receipt_file.exists():
            raise ValueError("orphan import receipt")
        if existing:
            if not payload_file.exists() or _sha256(self._read(relative)) != digest or not receipt_file.exists() or self._read(receipt_path) != receipt:
                raise ValueError("idempotent import integrity mismatch")
            return {"sha256": digest, "receipt_path": receipt_path}
        self._write(relative, value)
        self._write(receipt_path, receipt)
        manifest[relative] = digest
        self._write_manifest(manifest)
        return {"sha256": digest, "receipt_path": receipt_path}

    def import_catalog(self, catalog: Mapping[str, Any]) -> dict[str, str]:
        _validate_catalog(catalog)
        with self._lock():
            return self._import("date_catalog.json", catalog, "receipts/date_catalog.json")

    def import_payload(self, payload: Mapping[str, Any]) -> dict[str, str]:
        date = _validate_payload(payload)
        with self._lock():
            return self._import(f"preselection/{date}.json", payload, f"receipts/{date}.json")

    def read_catalog(self) -> dict[str, Any]:
        path = self._path("date_catalog.json")
        if not path.exists():
            return {"schema_version": "v3_trade_calendar.v1", "system_date": shanghai_now().strftime("%Y%m%d"), "stage_dates": [], "future_target_dates": [], "materialized_rows": {}}
        catalog = self._read("date_catalog.json")
        manifest = self._manifest()
        receipt = self._read("receipts/date_catalog.json")
        digest = _sha256(catalog)
        if manifest.get("date_catalog.json") != digest or receipt != {"schema_version": "v3_import_receipt.v1", "payload_path": "date_catalog.json", "source_sha256": digest, "trade_date": None}:
            raise ValueError("catalog manifest or receipt mismatch")
        _validate_catalog(catalog)
        return catalog

    def read_payload(self, date: str) -> dict[str, Any]:
        date = _date(date)
        relative, receipt_path = f"preselection/{date}.json", f"receipts/{date}.json"
        if not self._path(relative).exists():
            raise FileNotFoundError(date)
        payload, manifest, receipt = self._read(relative), self._manifest(), self._read(receipt_path)
        digest = _sha256(payload)
        if manifest.get(relative) != digest or receipt.get("schema_version") != "v3_import_receipt.v1" or receipt.get("source_sha256") != digest or receipt.get("payload_path") != relative or receipt.get("trade_date") != date:
            raise ValueError("manifest or receipt SHA mismatch")
        if _validate_payload(payload) != date:
            raise ValueError("payload identity mismatch")
        return payload


def _validate_catalog(catalog: Mapping[str, Any]) -> None:
    assert_safe_tree(catalog, label="date catalog")
    if not isinstance(catalog, Mapping):
        raise ValueError("invalid calendar payload")
    if catalog.get("schema_version") != "v3_trade_calendar.v1":
        raise ValueError("invalid calendar schema")
    _date(str(catalog.get("system_date", "")))
    for field in ("stage_dates", "future_target_dates"):
        if not isinstance(catalog.get(field), list):
            raise ValueError(f"invalid {field}")
        for value in catalog[field]:
            _date(value)
    materialized = catalog.get("materialized_rows", {})
    if not isinstance(materialized, Mapping):
        raise ValueError("invalid materialized_rows")
    for value, rows in materialized.items():
        _date(value)
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("invalid materialized row count")


def _validate_payload(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid preselection payload")
    if payload.get("schema_version") != "v3_preselection_pools.v1":
        raise ValueError("invalid preselection schema")
    date = _date(str(payload.get("trade_date", "")))
    _validate_payload_proof(payload)
    return date


def _validate_payload_proof(payload: Mapping[str, Any]) -> None:
    fixed = {
        "schema_version": "v3_preselection_pools.v1",
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        raise ValueError("invalid fixed preselection proof")
    for key in ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "pools"):
        if not isinstance(payload.get(key), list):
            raise ValueError("invalid row projection schema")
    if any(not isinstance(pool, Mapping) or not isinstance(pool.get("rows"), list) for pool in payload["pools"]):
        raise ValueError("invalid pool schema")

    complete = payload.get("producer_status") == "CANONICAL_COMPLETE"
    if complete:
        expected = {
            "data_status": "READY_WITH_ROWS",
            "canonical_main_pool_confirmed": True,
            "source_lane": "CANONICAL_MAIN",
            "selector_status": "READY",
            "strict_0_2_status": "STRICT_0_2_READY",
        }
    elif payload.get("producer_status") == "PARTIAL":
        expected = {
            "data_status": "PARTIAL_WITH_ROWS",
            "canonical_main_pool_confirmed": False,
            "source_lane": "NON_CANONICAL_OBSERVATION",
            "selector_status": "CANNOT_CONFIRM",
            "strict_0_2_status": "CANNOT_CONFIRM",
        }
    else:
        raise ValueError("unproven canonical producer status")
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("inconsistent producer proof")

    projected_rows: list[Any] = []
    for key in ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows"):
        projected_rows.extend(payload[key])
    for pool in payload["pools"]:
        projected_rows.extend(pool["rows"])
    if not payload["rows"]:
        raise ValueError("WITH_ROWS payload requires rows")
    for row in projected_rows:
        if not isinstance(row, Mapping) or row.get("recommendation_status") != "WATCH_ONLY":
            raise ValueError("all projected rows must be WATCH_ONLY objects")
    _assert_watch_only(payload, expected_lane=expected["source_lane"], expected_selector=expected["selector_status"])


def _assert_watch_only(value: Any, *, expected_lane: str, expected_selector: str) -> None:
    assert_safe_tree(value, label="watch-only product")
    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                folded = key.casefold()
                if folded in {"recommendation", "recommendation_status"} and nested not in ("WATCH_ONLY", "WATCH_ONLY_BACKTEST_GATED"):
                    raise ValueError("unsafe recommendation semantics")
                if folded in {"source_lane", "lane"} and nested != expected_lane:
                    raise ValueError("unexpected source lane")
                if folded == "selector_status" and nested != expected_selector:
                    raise ValueError("unexpected selector status")
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)
    visit(value)
