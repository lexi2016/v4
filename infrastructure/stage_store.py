"""Verified V3.5-owned storage for stage inputs and materialized workbenches."""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from contracts.stages import FROZEN_STAGE_IDS
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.trading_safety import assert_safe_tree


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MARKET_STATUSES = {"READY", "CLOSED", "CANNOT_CONFIRM"}


def _safe_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ValueError("path must be a normalized relative POSIX path")
    return value


def _validate_watch_row(row: Any) -> None:
    if not isinstance(row, Mapping) or row.get("recommendation_status") != "WATCH_ONLY":
        raise ValueError("stage rows must be explicit WATCH_ONLY objects")
    _assert_safe_tree(row)


def _assert_safe_tree(value: Any) -> None:
    assert_safe_tree(value, label="stage")


def validate_stage_input(payload: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_5.stage_input.v1":
        raise ValueError("invalid stage input schema")
    trade_date = _date(str(payload.get("trade_date", "")))
    stage_id = str(payload.get("stage_id") or "")
    if stage_id not in FROZEN_STAGE_IDS:
        raise ValueError("unknown stage_id")
    fixed = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("invalid stage input safety boundary")
    if not isinstance(payload.get("cutoff_reached"), bool):
        raise ValueError("cutoff_reached must be boolean")
    market_status = payload.get("market_status")
    if not isinstance(market_status, Mapping) or set(market_status) != {"A", "HK"}:
        raise ValueError("market_status must define A and HK")
    if any(value not in _MARKET_STATUSES for value in market_status.values()):
        raise ValueError("invalid market status")
    rows = payload.get("rows")
    if not isinstance(rows, Mapping) or set(rows) != {"A", "HK"}:
        raise ValueError("rows must define A and HK")
    for market_rows in rows.values():
        if not isinstance(market_rows, list):
            raise ValueError("stage market rows must be arrays")
        for row in market_rows:
            _validate_watch_row(row)
    evidence = payload.get("source_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("stage input requires source evidence")
    for item in evidence:
        if not isinstance(item, Mapping):
            raise ValueError("invalid source evidence")
        _safe_relative(item.get("path"))
        if not isinstance(item.get("sha256"), str) or not _SHA256.fullmatch(item["sha256"]):
            raise ValueError("invalid source evidence SHA-256")
    return trade_date, stage_id


def validate_quote_batch(payload: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_5.read_only_quote_batch.v1":
        raise ValueError("invalid read-only quote batch schema")
    trade_date = _date(str(payload.get("trade_date", "")))
    stage_id = str(payload.get("stage_id") or "")
    if stage_id not in FROZEN_STAGE_IDS:
        raise ValueError("unknown stage_id")
    if payload.get("temporal_cutoff_safe") is not True:
        raise ValueError("quote batch is not temporal cutoff safe")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(key) is not False:
            raise ValueError("unsafe quote batch boundary")
    try:
        captured = datetime.fromisoformat(str(payload.get("captured_at") or ""))
    except ValueError as error:
        raise ValueError("invalid quote batch captured_at") from error
    if captured.strftime("%Y%m%d") != trade_date:
        raise ValueError("quote batch date mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("quote batch rows must be an array")
    symbols: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("quote batch rows must be objects")
        symbol = str(row.get("symbol") or "")
        if not (symbol.startswith("A.") or symbol.startswith("HK.")) or symbol in symbols:
            raise ValueError("invalid or duplicate quote symbol")
        symbols.add(symbol)
        _assert_safe_tree(row)
    _assert_safe_tree(payload)
    return trade_date, stage_id


def validate_reference_workbench(payload: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_stage_workbench.v2":
        raise ValueError("invalid reference workbench schema")
    trade_date = _date(str(payload.get("trade_date", "")))
    stage = payload.get("stage")
    stage_id = str(stage.get("stage_id") or "") if isinstance(stage, Mapping) else ""
    if stage_id not in FROZEN_STAGE_IDS:
        raise ValueError("invalid reference workbench stage")
    fixed = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("unsafe reference workbench boundary")
    rows = payload.get("unified_rows")
    if not isinstance(rows, list):
        raise ValueError("invalid reference workbench rows")
    for row in rows:
        _validate_watch_row(row)
    for key in ("selected_a_rows", "selected_hk_rows", "selected_total_rows"):
        if isinstance(payload.get(key), bool) or not isinstance(payload.get(key), int) or payload[key] < 0:
            raise ValueError("invalid reference workbench counts")
    if payload["selected_total_rows"] != len(rows):
        raise ValueError("reference workbench row count mismatch")
    _assert_safe_tree(payload)
    return trade_date, stage_id


class StageStore(NativeDataStore):
    def import_source_snapshot(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date, stage_id = validate_quote_batch(payload)
        digest = _sha256(payload)
        relative = f"stage_sources/{trade_date}/{stage_id}/{digest}.json"
        receipt = f"receipts/stage_sources/{trade_date}/{stage_id}/{digest}.json"
        with self._lock():
            result = self._import(relative, payload, receipt)
        return {**result, "payload_path": relative}

    def import_reference_workbench(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date, stage_id = validate_reference_workbench(payload)
        normalized = deepcopy(dict(payload))
        normalized.update(
            {
                "selection_mode": "MIGRATED_REFERENCE_WORKBENCH",
                "response_source": "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
            }
        )
        relative = f"stage_references/{trade_date}/{stage_id}.json"
        receipt = f"receipts/stage_references/{trade_date}/{stage_id}.json"
        with self._lock():
            result = self._import(relative, normalized, receipt)
        return {**result, "payload_path": relative}

    def replace_reference_workbench(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str,
        reason: str,
    ) -> dict[str, str]:
        """Replace a proven-bad migrated snapshot without losing its audit chain."""
        trade_date, stage_id = validate_reference_workbench(payload)
        if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
            raise ValueError("invalid expected SHA")
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reference replacement reason is required")
        normalized = deepcopy(dict(payload))
        normalized.update(
            {
                "selection_mode": "MIGRATED_REFERENCE_WORKBENCH",
                "response_source": "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
            }
        )
        replacement_sha = _sha256(normalized)
        relative = f"stage_references/{trade_date}/{stage_id}.json"
        receipt_path = f"receipts/stage_references/{trade_date}/{stage_id}.json"
        supersession_path = (
            f"receipts/stage_reference_supersessions/{trade_date}/{stage_id}/"
            f"{expected_sha256}.json"
        )
        replacement_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": replacement_sha,
            "trade_date": trade_date,
        }
        supersession = {
            "schema_version": "v3_5.reference_supersession.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "payload_path": relative,
            "previous_sha256": expected_sha256,
            "replacement_sha256": replacement_sha,
            "reason": reason,
        }
        result = {
            "sha256": replacement_sha,
            "previous_sha256": expected_sha256,
            "receipt_path": receipt_path,
            "supersession_receipt_path": supersession_path,
            "payload_path": relative,
        }
        with self._lock():
            manifest = self._manifest()
            current_sha = manifest.get(relative)
            if current_sha == replacement_sha:
                if (
                    not self._path(relative).is_file()
                    or _sha256(self._read(relative)) != replacement_sha
                    or not self._path(receipt_path).is_file()
                    or self._read(receipt_path) != replacement_receipt
                    or not self._path(supersession_path).is_file()
                    or self._read(supersession_path) != supersession
                ):
                    raise ValueError("idempotent reference replacement integrity mismatch")
                return result
            if current_sha != expected_sha256:
                raise ValueError("reference workbench does not match expected SHA")

            # Recover a replacement interrupted before the manifest pointer update.
            if (
                self._path(relative).is_file()
                and _sha256(self._read(relative)) == replacement_sha
                and self._path(receipt_path).is_file()
                and self._read(receipt_path) == replacement_receipt
                and self._path(supersession_path).is_file()
                and self._read(supersession_path) == supersession
            ):
                manifest[relative] = replacement_sha
                self._write_manifest(manifest)
                return result

            current_receipt = {
                "schema_version": "v3_import_receipt.v1",
                "payload_path": relative,
                "source_sha256": expected_sha256,
                "trade_date": trade_date,
            }
            if (
                not self._path(relative).is_file()
                or _sha256(self._read(relative)) != expected_sha256
                or not self._path(receipt_path).is_file()
                or self._read(receipt_path) != current_receipt
            ):
                raise ValueError("reference workbench replacement source integrity mismatch")

            self._write(supersession_path, supersession)
            self._write(relative, normalized)
            self._write(receipt_path, replacement_receipt)
            manifest[relative] = replacement_sha
            self._write_manifest(manifest)
        return result

    def read_reference_workbench(self, trade_date: str, stage_id: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        if stage_id not in FROZEN_STAGE_IDS:
            raise ValueError("unknown stage_id")
        relative = f"stage_references/{trade_date}/{stage_id}.json"
        receipt_path = f"receipts/stage_references/{trade_date}/{stage_id}.json"
        if not self._path(relative).is_file():
            return None
        try:
            payload = self._read(relative)
            digest = _sha256(payload)
            manifest = self._manifest()
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("reference workbench evidence cannot be read") from error
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": trade_date,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("reference workbench manifest or receipt mismatch")
        if validate_reference_workbench(payload) != (trade_date, stage_id):
            raise ValueError("reference workbench identity mismatch")
        if (
            payload.get("selection_mode") != "MIGRATED_REFERENCE_WORKBENCH"
            or payload.get("response_source") != "V3_5_MIGRATED_REFERENCE_SNAPSHOT"
        ):
            raise ValueError("reference workbench provenance mismatch")
        return payload

    def import_input(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date, stage_id = validate_stage_input(payload)
        relative = f"stage_inputs/{trade_date}/{stage_id}.json"
        receipt = f"receipts/stage_inputs/{trade_date}/{stage_id}.json"
        with self._lock():
            return self._import(relative, payload, receipt)

    def replace_input(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str,
        reason: str,
    ) -> dict[str, str]:
        trade_date, stage_id = validate_stage_input(payload)
        if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
            raise ValueError("invalid expected SHA")
        reason = str(reason).strip()
        if not reason:
            raise ValueError("stage input replacement reason is required")
        relative = f"stage_inputs/{trade_date}/{stage_id}.json"
        receipt_path = f"receipts/stage_inputs/{trade_date}/{stage_id}.json"
        replacement_sha = _sha256(payload)
        supersession_path = (
            f"receipts/stage_input_supersessions/{trade_date}/{stage_id}/"
            f"{expected_sha256}.json"
        )
        replacement_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": replacement_sha,
            "trade_date": trade_date,
        }
        supersession = {
            "schema_version": "v3_5.stage_input_supersession.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "payload_path": relative,
            "previous_sha256": expected_sha256,
            "replacement_sha256": replacement_sha,
            "reason": reason,
        }
        with self._lock():
            manifest = self._manifest()
            current_sha = manifest.get(relative)
            if current_sha != expected_sha256:
                if current_sha == replacement_sha:
                    return {
                        "sha256": replacement_sha,
                        "previous_sha256": expected_sha256,
                        "receipt_path": receipt_path,
                        "supersession_receipt_path": supersession_path,
                    }
                raise ValueError("stage input does not match expected SHA")
            self._write(relative, payload)
            self._write(receipt_path, replacement_receipt)
            self._write(supersession_path, supersession)
            manifest[relative] = replacement_sha
            self._write_manifest(manifest)
        return {
            "sha256": replacement_sha,
            "previous_sha256": expected_sha256,
            "receipt_path": receipt_path,
            "supersession_receipt_path": supersession_path,
        }

    def read_input(self, trade_date: str, stage_id: str) -> tuple[dict[str, Any], str]:
        trade_date = _date(trade_date)
        if stage_id not in FROZEN_STAGE_IDS:
            raise ValueError("unknown stage_id")
        relative = f"stage_inputs/{trade_date}/{stage_id}.json"
        receipt_path = f"receipts/stage_inputs/{trade_date}/{stage_id}.json"
        if not self._path(relative).is_file():
            raise FileNotFoundError(relative)
        try:
            payload = self._read(relative)
            digest = _sha256(payload)
            manifest = self._manifest()
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("stage input evidence cannot be read") from error
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": trade_date,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("stage input manifest or receipt mismatch")
        if validate_stage_input(payload) != (trade_date, stage_id):
            raise ValueError("stage input identity mismatch")
        return payload, digest

    def publish(
        self,
        *,
        trade_date: str,
        stage_id: str,
        run_id: str,
        input_sha256: str,
        code_signature: str,
        output: Mapping[str, Any],
        force: bool,
    ) -> dict[str, Any]:
        with self._lock():
            try:
                existing = self.read_latest(trade_date, stage_id)
            except ValueError:
                if not force:
                    raise
                existing = None
            if existing is not None and existing["run_id"] == run_id and not force:
                return {**existing, "ensure_status": "ALREADY_COMPLETE"}

            run_root = f"stage_runs/{trade_date}/{stage_id}/{run_id}"
            artifact_path = f"{run_root}/artifact.json"
            manifest_path = f"{run_root}/manifest.json"
            receipt_path = f"{run_root}/receipt.json"
            latest_path = f"stage_latest/{trade_date}/{stage_id}.json"
            artifact_sha = _sha256(output)
            manifest = {
                "schema_version": "v3_5.stage_run_manifest.v1",
                "run_id": run_id,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "status": "COMPLETE",
                "input_sha256": input_sha256,
                "code_signature": code_signature,
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            manifest_sha = _sha256(manifest)
            receipt = {
                "schema_version": "v3_5.stage_run_receipt.v1",
                "run_id": run_id,
                "manifest_path": manifest_path,
                "manifest_sha256": manifest_sha,
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "status": "COMPLETE",
            }
            latest = {
                "schema_version": "v3_5.stage_latest.v1",
                "run_id": run_id,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "manifest_path": manifest_path,
                "manifest_sha256": manifest_sha,
                "receipt_path": receipt_path,
                "receipt_sha256": _sha256(receipt),
            }
            self._write(artifact_path, output)
            self._write(manifest_path, manifest)
            self._write(receipt_path, receipt)
            self._write(latest_path, latest)
            published = self.read_latest(trade_date, stage_id)
            if published is None:
                raise ValueError("stage publication did not become visible")
            published["ensure_status"] = "FORCED_REMATERIALIZED" if force else "STAGE_RUN_COMPLETE"
            return published

    def read_latest(self, trade_date: str, stage_id: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        if stage_id not in FROZEN_STAGE_IDS:
            raise ValueError("unknown stage_id")
        latest_path = f"stage_latest/{trade_date}/{stage_id}.json"
        if not self._path(latest_path).is_file():
            return None
        try:
            latest = self._read(latest_path)
        except (OSError, ValueError) as error:
            raise ValueError("stage latest pointer cannot be read") from error
        if (
            latest.get("schema_version") != "v3_5.stage_latest.v1"
            or latest.get("trade_date") != trade_date
            or latest.get("stage_id") != stage_id
        ):
            raise ValueError("invalid stage latest pointer")
        artifact_path = _safe_relative(latest.get("artifact_path"))
        manifest_path = _safe_relative(latest.get("manifest_path"))
        receipt_path = _safe_relative(latest.get("receipt_path"))
        try:
            artifact = self._read(artifact_path)
            manifest = self._read(manifest_path)
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("stage publication evidence cannot be read") from error
        if (
            _sha256(artifact) != latest.get("artifact_sha256")
            or _sha256(manifest) != latest.get("manifest_sha256")
            or _sha256(receipt) != latest.get("receipt_sha256")
            or manifest.get("artifact_sha256") != latest.get("artifact_sha256")
            or receipt.get("manifest_sha256") != latest.get("manifest_sha256")
            or receipt.get("artifact_sha256") != latest.get("artifact_sha256")
            or manifest.get("status") != "COMPLETE"
            or receipt.get("status") != "COMPLETE"
        ):
            raise ValueError("stage artifact, manifest, or receipt mismatch")
        return {
            **latest,
            "artifact": artifact,
            "manifest": manifest,
            "receipt": receipt,
        }

    def record_failure(
        self,
        *,
        trade_date: str,
        stage_id: str,
        run_id: str,
        input_sha256: str,
        error: Exception,
    ) -> str:
        relative = f"stage_failures/{trade_date}/{stage_id}/{run_id}.json"
        failure = {
            "schema_version": "v3_5.stage_failure_receipt.v1",
            "run_id": run_id,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": "FAILED",
            "input_sha256": input_sha256,
            "error_type": type(error).__name__,
            "error_message": str(error)[:500],
            "failed_at": datetime.now().isoformat(timespec="seconds"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        with self._lock():
            self._write(relative, failure)
        return relative
