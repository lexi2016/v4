"""Exact-date, V3.5-owned storage for optional preselection pool projections."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.owned_path import resolve_owned_path


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POOL_IDS = (
    "a_share_baimao_research_map",
    "wechat_public_account_v3_preselect",
)
_TOP_FIELDS = {
    "schema_version",
    "trade_date",
    "module_id",
    "source_status",
    "source_signal_date",
    "effective_trade_date",
    "source_manifest_sha256",
    "source_rows_sha256",
    "source_row_count",
    "write_policy",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
    "pools",
    "cannot_confirm",
}
_ROW_FIELDS = {
    "market",
    "market_label",
    "pool_id",
    "rank",
    "pool_rank",
    "code",
    "ts_code",
    "symbol",
    "name",
    "stock_name",
    "display_name",
    "score",
    "pool_score",
    "status",
    "recommendation_status",
    "trade_status_contract",
    "role",
    "source_label",
    "source_lanes",
    "source_tags",
    "signal_date",
    "source_signal_date",
    "effective_trade_date",
    "selector_score_date",
    "target_date",
    "date_match_status",
    "wechat_publish_date",
    "wechat_article_title",
    "wechat_hit_count",
    "wechat_source_ref",
    "next_action",
    "stage_selection_eligible",
    "formal_pool_write",
    "buy_gate_write",
    "production_allowed",
    "orders_sent",
}


class PreselectionOverlayStore:
    """Immutable optional-pool artifacts kept separate from selector inputs."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _read(self, relative: str) -> Any:
        return json.loads(self._path(relative).read_text(encoding="utf-8"))

    def _write(self, relative: str, value: Mapping[str, Any]) -> None:
        destination = self._path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(_canonical_bytes(value))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def _lock(self):
        path = self._path("preselection_overlays/.import.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 10
        token = f"{os.getpid()}:{uuid4().hex}"
        while True:
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, token.encode("ascii"))
                os.close(handle)
                break
            except FileExistsError:
                try:
                    if time.time() - path.stat().st_mtime > 30:
                        path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise ValueError("preselection overlay import lock timeout")
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if path.read_text(encoding="ascii") == token:
                    path.unlink()
            except FileNotFoundError:
                pass

    def _paths(self, trade_date: str) -> tuple[str, str, str]:
        payload = f"preselection_overlays/{trade_date}.json"
        receipt = f"preselection_overlays/receipts/{trade_date}.json"
        manifest = "preselection_overlays/manifest.json"
        for relative in (payload, receipt, manifest, "preselection_overlays/.import.lock"):
            self._path(relative)
        return payload, receipt, manifest

    def import_overlay(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_preselection_overlay(payload)
        payload_path, receipt_path, manifest_path = self._paths(trade_date)
        digest = _sha256(payload)
        receipt = {
            "schema_version": "v3_5.preselection_overlay_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": digest,
            "source_manifest_sha256": payload["source_manifest_sha256"],
            "source_rows_sha256": payload["source_rows_sha256"],
            "trade_date": trade_date,
        }
        with self._lock():
            manifest_file = self._path(manifest_path)
            if manifest_file.exists() and not manifest_file.is_file():
                raise ValueError("preselection overlay manifest path is not a regular file")
            manifest = self._read(manifest_path) if manifest_file.is_file() else {}
            if not isinstance(manifest, dict):
                raise ValueError("preselection overlay manifest is invalid")
            existing = manifest.get(payload_path)
            payload_file = self._path(payload_path)
            receipt_file = self._path(receipt_path)
            if existing is not None:
                if (
                    existing != digest
                    or not payload_file.is_file()
                    or _sha256(self._read(payload_path)) != digest
                    or not receipt_file.is_file()
                    or self._read(receipt_path) != receipt
                ):
                    raise ValueError("preselection overlay conflicting re-import")
                return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}
            if payload_file.exists():
                if (
                    not payload_file.is_file()
                    or _sha256(self._read(payload_path)) != digest
                    or (receipt_file.exists() and (
                        not receipt_file.is_file() or self._read(receipt_path) != receipt
                    ))
                ):
                    raise ValueError("preselection overlay interrupted import SHA mismatch")
                if not receipt_file.exists():
                    self._write(receipt_path, receipt)
                manifest[payload_path] = digest
                self._write(manifest_path, manifest)
                return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}
            if receipt_file.exists():
                raise ValueError("preselection overlay orphan receipt")
            self._write(payload_path, payload)
            self._write(receipt_path, receipt)
            manifest[payload_path] = digest
            self._write(manifest_path, manifest)
        return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}

    def read_overlay(self, trade_date: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        payload_path, receipt_path, manifest_path = self._paths(trade_date)
        payload_file = self._path(payload_path)
        receipt_file = self._path(receipt_path)
        manifest_file = self._path(manifest_path)
        present = (payload_file.exists(), receipt_file.exists(), manifest_file.exists())
        if any(path.exists() and not path.is_file() for path in (payload_file, receipt_file, manifest_file)):
            raise ValueError("preselection overlay evidence path is not a regular file")
        if not present[0] and not present[1]:
            if not present[2]:
                return None
            manifest = self._read(manifest_path)
            if not isinstance(manifest, dict):
                raise ValueError("preselection overlay manifest is invalid")
            if payload_path not in manifest:
                return None
            raise ValueError("preselection overlay is partially materialized")
        if not all(present):
            raise ValueError("preselection overlay is partially materialized")
        payload = self._read(payload_path)
        receipt = self._read(receipt_path)
        manifest = self._read(manifest_path)
        digest = _sha256(payload)
        expected_receipt = {
            "schema_version": "v3_5.preselection_overlay_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": digest,
            "source_manifest_sha256": payload.get("source_manifest_sha256"),
            "source_rows_sha256": payload.get("source_rows_sha256"),
            "trade_date": trade_date,
        }
        if not isinstance(manifest, dict) or manifest.get(payload_path) != digest or receipt != expected_receipt:
            raise ValueError("preselection overlay manifest or receipt SHA mismatch")
        if validate_preselection_overlay(payload) != trade_date:
            raise ValueError("preselection overlay identity mismatch")
        return payload


def validate_preselection_overlay(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or set(payload) != _TOP_FIELDS:
        raise ValueError("invalid preselection overlay fields")
    if payload.get("schema_version") != "v3_5.preselection_overlay.v1":
        raise ValueError("invalid preselection overlay schema")
    trade_date = _date(str(payload.get("trade_date", "")))
    if payload.get("module_id") != "preselection_optional_pools":
        raise ValueError("invalid preselection overlay module")
    if payload.get("source_status") != "WECHAT_V3_PRESELECT_READY":
        raise ValueError("invalid preselection overlay source status")
    if _date(str(payload.get("source_signal_date", ""))) != trade_date:
        raise ValueError("preselection overlay signal date mismatch")
    _date(str(payload.get("effective_trade_date", "")))
    if any(not _SHA256.fullmatch(str(payload.get(field, ""))) for field in ("source_manifest_sha256", "source_rows_sha256")):
        raise ValueError("invalid preselection overlay source SHA")
    if isinstance(payload.get("source_row_count"), bool) or not isinstance(payload.get("source_row_count"), int) or payload["source_row_count"] < 1:
        raise ValueError("invalid preselection overlay source row count")
    fixed = {
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        raise ValueError("unsafe preselection overlay proof")
    if not isinstance(payload.get("cannot_confirm"), list):
        raise ValueError("invalid preselection overlay cannot_confirm")
    pools = payload.get("pools")
    if not isinstance(pools, list) or [pool.get("pool_id") for pool in pools if isinstance(pool, Mapping)] != list(_POOL_IDS):
        raise ValueError("invalid preselection overlay pool identities")
    _validate_baimao_pool(pools[0], trade_date)
    _validate_wechat_pool(pools[1], payload)
    _assert_research_only(payload)
    return trade_date


def _validate_baimao_pool(pool: Mapping[str, Any], trade_date: str) -> None:
    expected = {
        "pool_id": "a_share_baimao_research_map",
        "market": "A",
        "display_name": "白毛卡点研究池",
        "status": "CANNOT_CONFIRM",
        "recommendation_status": "RESEARCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
        "stage_selection_eligible": False,
        "write_policy": "RESEARCH_ONLY",
        "production_allowed": False,
        "opens_buy_gate": False,
        "pool_size": 0,
        "returned_rows": 0,
        "trade_date": trade_date,
        "rows": [],
        "cannot_confirm": ["BAIMAO_RESEARCH_MAP_NOT_FOUND"],
        "evidence_paths": {"research_map": ""},
    }
    if pool != expected:
        raise ValueError("invalid Baimao optional-pool proof")


def _validate_wechat_pool(pool: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    rows = pool.get("rows")
    if not isinstance(rows, list) or len(rows) != payload["source_row_count"]:
        raise ValueError("invalid WeChat optional-pool row count")
    expected_fixed = {
        "pool_id": "wechat_public_account_v3_preselect",
        "market": "WECHAT",
        "display_name": "公众号股票池",
        "status": "WECHAT_V3_PRESELECT_READY",
        "recommendation_status": "RESEARCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
        "stage_selection_eligible": False,
        "formal_pool_write": False,
        "production_allowed": False,
        "date_match_status": "MATCH",
        "source_signal_date": payload["source_signal_date"],
        "target_date": payload["trade_date"],
        "pool_size": len(rows),
        "returned_rows": len(rows),
    }
    if any(pool.get(key) != value for key, value in expected_fixed.items()):
        raise ValueError("invalid WeChat optional-pool proof")
    allowed_pool_fields = set(expected_fixed) | {"rows", "cannot_confirm", "evidence_paths"}
    if set(pool) != allowed_pool_fields:
        raise ValueError("invalid WeChat optional-pool fields")
    if not isinstance(pool.get("cannot_confirm"), list) or not pool["cannot_confirm"]:
        raise ValueError("missing WeChat research-only boundary")
    evidence = pool.get("evidence_paths")
    if not isinstance(evidence, Mapping) or set(evidence) != {"manifest", "all_rows"}:
        raise ValueError("invalid WeChat optional-pool evidence")
    seen: set[str] = set()
    ranks: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _ROW_FIELDS:
            raise ValueError("invalid WeChat optional-pool row fields")
        symbol = str(row.get("symbol") or "")
        if not re.fullmatch(r"A\.\d{6}", symbol) or symbol in seen:
            raise ValueError("invalid or duplicate WeChat symbol")
        seen.add(symbol)
        rank = row.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or row.get("pool_rank") != rank:
            raise ValueError("invalid WeChat row rank")
        ranks.append(rank)
        if row.get("pool_score") != row.get("score") or isinstance(row.get("score"), bool) or not isinstance(row.get("score"), (int, float)):
            raise ValueError("invalid WeChat row score")
        if row.get("signal_date") != payload["trade_date"] or row.get("target_date") != payload["trade_date"]:
            raise ValueError("invalid WeChat row date binding")
    if ranks != list(range(1, len(rows) + 1)):
        raise ValueError("invalid WeChat row rank sequence")


def _assert_research_only(value: Any) -> None:
    unsafe_true = {
        "production_allowed", "buy_gate_updated", "orders_sent", "formal_pool_write",
        "buy_gate_write", "stage_selection_eligible", "opens_buy_gate", "order_allowed",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = key.casefold()
            if folded in unsafe_true and nested not in (False, 0, None, ""):
                raise ValueError("unsafe optional-pool trading field")
            if folded in {"recommendation", "recommendation_status"} and nested != "RESEARCH_ONLY":
                raise ValueError("unsafe optional-pool recommendation")
            if folded == "trade_status_contract" and nested != "RESEARCH_ONLY_NO_BUY_GATE":
                raise ValueError("unsafe optional-pool trade status")
            _assert_research_only(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_research_only(nested)
