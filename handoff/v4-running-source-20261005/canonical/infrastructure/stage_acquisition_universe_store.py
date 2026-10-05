"""Immutable exact-date A-share stage-acquisition universe evidence.

The producer is intentionally a small boundary around the already-authoritative
``domains.preselection.preselection`` projection.  It stores canonical symbols,
not copies of physical pool rows, so auxiliary review lanes cannot silently
become stage candidates.
"""
from __future__ import annotations

import re
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.trading_safety import assert_safe_tree


ARTIFACT_ROLE = "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"
SCHEMA_VERSION = ARTIFACT_ROLE
ARTIFACT_VERSION = "V2"
MANIFEST_SCHEMA = "v3_5.stage_acquisition_universe.manifest.v2"
RECEIPT_SCHEMA = "v3_5.stage_acquisition_universe.receipt.v2"
CURRENT_SCHEMA = "v3_5.stage_acquisition_universe.current.v2"
_CODE_RE = re.compile(r"^A\.\d{6}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")


def _safe_run_id(value: Any) -> str:
    if not isinstance(value, str) or not _RUN_RE.fullmatch(value):
        raise ValueError("run_id must be a safe slug")
    return value


def _digest(value: Any) -> str:
    return _sha256(value)


def _assert_safe_tree(value: Any) -> None:
    """Reject accidental promotion/order semantics anywhere in the artifact."""

    assert_safe_tree(value, label="stage-acquisition")


def _canonical_code(row: Mapping[str, Any], index: int) -> str:
    """Return one canonical A-share symbol without changing source order."""

    market = str(row.get("market") or "").strip().upper()
    value = row.get("symbol")
    if value in (None, ""):
        value = row.get("normalized_code")
    if value in (None, ""):
        value = row.get("code")
    if value in (None, ""):
        value = row.get("stock_code")
    if value in (None, ""):
        value = row.get("ts_code")
    text = str(value or "").strip().upper()
    if text.endswith(".SH") or text.endswith(".SZ") or text.endswith(".BJ"):
        text = text[:-3]
    if re.fullmatch(r"\d{6}", text):
        text = f"A.{text}"
    if not _CODE_RE.fullmatch(text):
        raise ValueError(f"a_all_pool_rows[{index}] is not a canonical A code")
    if market and market not in {"A", "A_SHARE", "ASHARE", "A股"}:
        raise ValueError(f"a_all_pool_rows[{index}] market is not A")
    return text


def _pool_provenance(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    pools = projection.get("pools")
    if pools is None:
        return []
    if not isinstance(pools, list):
        raise ValueError("preselection projection pools must be a list")
    provenance: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, pool in enumerate(pools):
        if not isinstance(pool, Mapping):
            raise ValueError(f"preselection projection pool {index} is invalid")
        pool_id = str(pool.get("pool_id") or "").strip()
        if not pool_id or pool_id in seen:
            raise ValueError("preselection projection pool identity is invalid")
        rows = pool.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError(f"preselection projection pool {pool_id} rows are invalid")
        seen.add(pool_id)
        pool_sha = _digest(pool)
        provenance.append(
            {
                "pool_id": pool_id,
                "status": str(pool.get("status") or ""),
                "row_count": len(rows),
                "pool_sha256": pool_sha,
            }
        )
    return provenance


def build_stage_acquisition_universe(
    projection: Mapping[str, Any],
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Build the V2 artifact from one complete preselection projection.

    The source is deliberately the projection's ``a_all_pool_rows`` field.  No
    pool files, HTTP endpoints, V3 modules, or source-lane rows are inspected.
    """

    if not isinstance(projection, Mapping):
        raise ValueError("preselection projection must be an object")
    source_date = _date(str(projection.get("trade_date") or ""))
    requested_date = source_date if trade_date is None else _date(str(trade_date))
    if source_date != requested_date:
        raise ValueError("preselection projection trade_date mismatch")
    if projection.get("ok") is not True:
        raise ValueError("preselection projection is not confirmed")
    rows = projection.get("a_all_pool_rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("preselection projection has no a_all_pool_rows")
    reported_count = projection.get("a_all_pool_row_count")
    if isinstance(reported_count, bool) or not isinstance(reported_count, int):
        raise ValueError("preselection a_all_pool_row_count is invalid")
    if reported_count != len(rows):
        raise ValueError("preselection a_all_pool_rows count is truncated")

    codes: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"a_all_pool_rows[{index}] is invalid")
        code = _canonical_code(row, index)
        if code in seen:
            raise ValueError(f"duplicate canonical A code: {code}")
        seen.add(code)
        codes.append(code)

    projection_digest = _digest(projection)
    provenance = _pool_provenance(projection)
    source_status = str(projection.get("data_status") or projection.get("status") or "")
    cannot_confirm = [str(item) for item in projection.get("cannot_confirm", []) or [] if str(item)]
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "artifact_role": ARTIFACT_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "status": "READY",
        "trade_date": source_date,
        "codes": codes,
        "row_count": len(codes),
        "codes_sha256": _digest(codes),
        "source_projection_sha256": projection_digest,
        "source_projection_row_count": reported_count,
        "source_projection_status": source_status,
        "source_pool_provenance": provenance,
        "source_pool_provenance_sha256": _digest(provenance),
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "cannot_confirm": cannot_confirm,
    }
    validate_stage_acquisition_universe(artifact)
    return artifact


def validate_stage_acquisition_universe(payload: Mapping[str, Any]) -> str:
    """Validate artifact identity, lineage, ordered codes, and safety flags."""

    if not isinstance(payload, Mapping):
        raise ValueError("stage-acquisition artifact must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid stage-acquisition universe schema")
    if (
        payload.get("artifact_role") != ARTIFACT_ROLE
        or payload.get("artifact_version") != ARTIFACT_VERSION
    ):
        raise ValueError("invalid stage-acquisition universe identity")
    trade_date = _date(str(payload.get("trade_date") or ""))
    if payload.get("status") != "READY":
        raise ValueError("stage-acquisition universe must be READY")
    codes = payload.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("stage-acquisition universe codes are missing")
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code) or code in seen:
            raise ValueError("invalid or duplicate canonical A code")
        seen.add(code)
    row_count = payload.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(codes):
        raise ValueError("stage-acquisition universe row_count mismatch")
    for name in ("codes_sha256", "source_projection_sha256"):
        value = payload.get(name)
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            raise ValueError(f"invalid {name}")
    if payload["codes_sha256"] != _digest(codes):
        raise ValueError("stage-acquisition codes SHA mismatch")
    if payload.get("source_projection_row_count") != row_count:
        raise ValueError("stage-acquisition source projection row_count mismatch")
    provenance = payload.get("source_pool_provenance")
    if not isinstance(provenance, list) or not provenance:
        raise ValueError("stage-acquisition source pool provenance is missing")
    expected_ids: list[str] = []
    for item in provenance:
        if not isinstance(item, Mapping):
            raise ValueError("invalid stage-acquisition source pool provenance")
        pool_id = str(item.get("pool_id") or "")
        if not pool_id or pool_id in expected_ids:
            raise ValueError("duplicate stage-acquisition source pool provenance")
        if isinstance(item.get("row_count"), bool) or not isinstance(item.get("row_count"), int) or item["row_count"] < 0:
            raise ValueError("invalid stage-acquisition source pool row_count")
        if not isinstance(item.get("pool_sha256"), str) or not _DIGEST_RE.fullmatch(item["pool_sha256"]):
            raise ValueError("invalid stage-acquisition source pool SHA")
        expected_ids.append(pool_id)
    if payload.get("source_pool_provenance_sha256") != _digest(provenance):
        raise ValueError("stage-acquisition source pool provenance mismatch")
    fixed = {
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("invalid stage-acquisition safety boundary")
    cannot = payload.get("cannot_confirm")
    if not isinstance(cannot, list) or any(not isinstance(item, str) for item in cannot):
        raise ValueError("invalid stage-acquisition cannot_confirm")
    _assert_safe_tree(payload)
    return trade_date


class StageAcquisitionUniverseStore(NativeDataStore):
    """Immutable run trio plus one exact-date current pointer for V2."""

    def current_path(self, trade_date: str) -> Path:
        date = _date(trade_date)
        return self._path(f"current/{date}/{ARTIFACT_ROLE}/current.json")

    def _run_dir(self, trade_date: str, run_id: str) -> Path:
        return self._path(f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}")

    def _paths(self, trade_date: str, run_id: str) -> dict[str, Path]:
        directory = self._run_dir(trade_date, run_id)
        return {
            "artifact": directory / "artifact.json",
            "manifest": directory / "manifest.json",
            "receipt": directory / "receipt.json",
        }

    def _manifest_payload(
        self,
        trade_date: str,
        run_id: str,
        artifact: Mapping[str, Any],
        artifact_sha256: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": run_id,
            "status": artifact["status"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_sha256": artifact_sha256,
            "artifact_relative": f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}/artifact.json",
            **{name: False for name in _FLAGS},
        }

    def _receipt_payload(
        self,
        trade_date: str,
        run_id: str,
        artifact: Mapping[str, Any],
        artifact_sha256: str,
        manifest_sha256: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_SCHEMA,
            "trade_date": trade_date,
            "role": ARTIFACT_ROLE,
            "run_id": run_id,
            "status": artifact["status"],
            "row_count": artifact["row_count"],
            "codes_sha256": artifact["codes_sha256"],
            "source_projection_sha256": artifact["source_projection_sha256"],
            "artifact_sha256": artifact_sha256,
            "manifest_sha256": manifest_sha256,
            **{name: False for name in _FLAGS},
        }

    def _verify_run(self, trade_date: str, run_id: str) -> dict[str, Any]:
        paths = self._paths(trade_date, run_id)
        if any(not path.is_file() for path in paths.values()):
            raise ValueError("stage-acquisition artifact, manifest, and receipt trio is incomplete")
        try:
            artifact = self._read(str(paths["artifact"].relative_to(self.root)))
            manifest = self._read(str(paths["manifest"].relative_to(self.root)))
            receipt = self._read(str(paths["receipt"].relative_to(self.root)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stage-acquisition evidence cannot be read") from error
        if not isinstance(artifact, Mapping) or not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("stage-acquisition trio must contain objects")
        if validate_stage_acquisition_universe(artifact) != trade_date:
            raise ValueError("stage-acquisition artifact identity mismatch")
        expected_relative = f"runs/{trade_date}/{ARTIFACT_ROLE}/{run_id}/artifact.json"
        if (
            manifest.get("schema_version") != MANIFEST_SCHEMA
            or manifest.get("trade_date") != trade_date
            or manifest.get("role") != ARTIFACT_ROLE
            or manifest.get("run_id") != run_id
            or manifest.get("artifact_relative") != expected_relative
            or receipt.get("schema_version") != RECEIPT_SCHEMA
            or receipt.get("trade_date") != trade_date
            or receipt.get("role") != ARTIFACT_ROLE
            or receipt.get("run_id") != run_id
        ):
            raise ValueError("stage-acquisition manifest or receipt identity mismatch")
        for item in (manifest, receipt):
            if any(item.get(name) is not False for name in _FLAGS):
                raise ValueError("stage-acquisition manifest or receipt safety mismatch")
        artifact_sha256 = _digest(artifact)
        manifest_sha256 = _digest(manifest)
        receipt_sha256 = _digest(receipt)
        if (
            manifest.get("artifact_sha256") != artifact_sha256
            or receipt.get("artifact_sha256") != artifact_sha256
            or receipt.get("manifest_sha256") != manifest_sha256
            or manifest.get("row_count") != artifact.get("row_count")
            or receipt.get("row_count") != artifact.get("row_count")
            or manifest.get("codes_sha256") != artifact.get("codes_sha256")
            or receipt.get("codes_sha256") != artifact.get("codes_sha256")
            or manifest.get("source_projection_sha256") != artifact.get("source_projection_sha256")
            or receipt.get("source_projection_sha256") != artifact.get("source_projection_sha256")
            or manifest.get("status") != artifact.get("status")
            or receipt.get("status") != artifact.get("status")
        ):
            raise ValueError("stage-acquisition trio integrity mismatch")
        return {
            "run_id": run_id,
            "artifact": dict(artifact),
            "manifest": dict(manifest),
            "receipt": dict(receipt),
            "artifact_path": paths["artifact"],
            "manifest_path": paths["manifest"],
            "receipt_path": paths["receipt"],
            "artifact_sha256": artifact_sha256,
            "manifest_sha256": manifest_sha256,
            "receipt_sha256": receipt_sha256,
        }

    def _verify_current(self, trade_date: str) -> dict[str, Any]:
        pointer_path = self.current_path(trade_date)
        if not pointer_path.is_file():
            raise FileNotFoundError(f"exact current missing: {trade_date}/{ARTIFACT_ROLE}")
        try:
            pointer = self._read(str(pointer_path.relative_to(self.root)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stage-acquisition current pointer cannot be read") from error
        if not isinstance(pointer, Mapping) or pointer.get("schema_version") != CURRENT_SCHEMA:
            raise ValueError("stage-acquisition current pointer schema mismatch")
        run_id = _safe_run_id(pointer.get("run_id"))
        if pointer.get("trade_date") != trade_date or pointer.get("role") != ARTIFACT_ROLE:
            raise ValueError("stage-acquisition current pointer identity mismatch")
        if any(pointer.get(name) is not False for name in _FLAGS):
            raise ValueError("stage-acquisition current pointer safety mismatch")
        verified = self._verify_run(trade_date, run_id)
        expected = {
            "status": verified["receipt"]["status"],
            "row_count": verified["receipt"]["row_count"],
            "codes_sha256": verified["artifact"]["codes_sha256"],
            "source_projection_sha256": verified["artifact"]["source_projection_sha256"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_relative": verified["manifest"]["artifact_relative"],
        }
        if any(pointer.get(key) != value for key, value in expected.items()):
            raise ValueError("stage-acquisition current pointer integrity mismatch")
        return {"current": dict(pointer), **verified, "current_path": pointer_path}

    def publish(self, payload: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        trade_date = validate_stage_acquisition_universe(payload)
        artifact = deepcopy(dict(payload))
        artifact_sha256 = _digest(artifact)
        selected_run = _safe_run_id(
            run_id or f"{trade_date}-{ARTIFACT_ROLE.lower()}-{artifact_sha256[:12]}"
        )
        paths = self._paths(trade_date, selected_run)
        manifest = self._manifest_payload(trade_date, selected_run, artifact, artifact_sha256)
        manifest_sha256 = _digest(manifest)
        receipt = self._receipt_payload(
            trade_date, selected_run, artifact, artifact_sha256, manifest_sha256
        )
        with self._lock():
            pointer_path = self.current_path(trade_date)
            if pointer_path.exists():
                if not pointer_path.is_file():
                    raise ValueError("stage-acquisition current pointer is not a file")
                existing = self._verify_current(trade_date)
                if existing["artifact_sha256"] == artifact_sha256:
                    return self._result(existing, idempotent=True)
                raise ValueError(f"exact slot conflict: {trade_date}/{ARTIFACT_ROLE}")

            paths["artifact"].parent.mkdir(parents=True, exist_ok=True)
            if paths["artifact"].exists():
                if not paths["artifact"].is_file() or _digest(self._read(str(paths["artifact"].relative_to(self.root)))) != artifact_sha256:
                    raise ValueError("stage-acquisition immutable artifact conflict")
            else:
                self._write(str(paths["artifact"].relative_to(self.root)), artifact)
            self._ensure_file(paths["manifest"], manifest)
            self._ensure_file(paths["receipt"], receipt)
            verified = self._verify_run(trade_date, selected_run)
            pointer = {
                "schema_version": CURRENT_SCHEMA,
                "trade_date": trade_date,
                "role": ARTIFACT_ROLE,
                "run_id": selected_run,
                "status": artifact["status"],
                "row_count": artifact["row_count"],
                "codes_sha256": artifact["codes_sha256"],
                "source_projection_sha256": artifact["source_projection_sha256"],
                "artifact_sha256": artifact_sha256,
                "manifest_sha256": verified["manifest_sha256"],
                "receipt_sha256": verified["receipt_sha256"],
                "artifact_relative": manifest["artifact_relative"],
                **{name: False for name in _FLAGS},
            }
            self._write(str(pointer_path.relative_to(self.root)), pointer)
            verified_current = self._verify_current(trade_date)
            result = self._result(verified_current, idempotent=False)
        return result

    def _ensure_file(self, path: Path, expected: Mapping[str, Any]) -> None:
        relative = str(path.relative_to(self.root))
        if path.exists():
            if not path.is_file() or self._read(relative) != dict(expected):
                raise ValueError("stage-acquisition immutable evidence conflict")
            return
        self._write(relative, expected)

    @staticmethod
    def _result(verified: Mapping[str, Any], *, idempotent: bool) -> dict[str, Any]:
        return {
            "status": verified["receipt"]["status"],
            "idempotent": idempotent,
            "trade_date": verified["receipt"]["trade_date"],
            "role": ARTIFACT_ROLE,
            "run_id": verified["run_id"],
            "row_count": verified["receipt"]["row_count"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "artifact_path": verified["artifact_path"],
            "manifest_path": verified["manifest_path"],
            "receipt_path": verified["receipt_path"],
            "current_path": verified.get("current_path") or None,
        }

    def read_verified(self, trade_date: str) -> dict[str, Any]:
        date = _date(trade_date)
        return self._verify_current(date)


__all__ = [
    "ARTIFACT_ROLE",
    "ARTIFACT_VERSION",
    "CURRENT_SCHEMA",
    "MANIFEST_SCHEMA",
    "RECEIPT_SCHEMA",
    "SCHEMA_VERSION",
    "StageAcquisitionUniverseStore",
    "build_stage_acquisition_universe",
    "validate_stage_acquisition_universe",
]
