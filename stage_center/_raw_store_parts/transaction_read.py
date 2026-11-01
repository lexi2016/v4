"""stage_center.raw_store: transaction_read (review candidate, not deployment)."""
from __future__ import annotations
from stage_center.calendar import calendar_provenance
from stage_center.contracts import SAFETY_FLAGS
from typing import Mapping
import csv
from stage_center.raw_store import ARTIFACT_FIELDS, RAW_BUNDLE_SCHEMA_VERSION, RAW_MANIFEST_SCHEMA_VERSION, RAW_RECEIPT_SCHEMA_VERSION, RAW_STATUSES, RawStoreError, _expected_bundle_markets, _read_json, _safe_relative, _sha_file, _stage, _validate_date, _validate_slug, canonical_sha


def _RawStore__verify_run_paths_body(self, *, trade_date, stage_id, market, run_id, expected_owner):
    _validate_date(trade_date)
    _stage(stage_id)
    role = self._role(stage_id, market)
    _validate_slug(run_id, "run_id")
    prefix = f"runs/{trade_date}/{role}/{run_id}"
    run_dir = _safe_relative(self.root, prefix)
    artifact = _safe_relative(self.root, f"{prefix}/artifact.csv")
    manifest_path = _safe_relative(self.root, f"{prefix}/manifest.json")
    receipt_path = _safe_relative(self.root, f"{prefix}/receipt.json")
    if not run_dir.is_dir() or not all(path.is_file() for path in (artifact, manifest_path, receipt_path)):
        raise RawStoreError("run trio incomplete")
    manifest = _read_json(manifest_path)
    receipt = _read_json(receipt_path)
    if manifest.get("schema_version") != RAW_MANIFEST_SCHEMA_VERSION:
        raise RawStoreError("manifest schema mismatch")
    if receipt.get("schema_version") != RAW_RECEIPT_SCHEMA_VERSION:
        raise RawStoreError("receipt schema mismatch")
    for payload, label in ((manifest, "manifest"), (receipt, "receipt")):
        if payload.get("owner") != expected_owner:
            raise RawStoreError(f"{label} owner mismatch")
        if payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id or payload.get("market") != market:
            raise RawStoreError(f"{label} identity mismatch")
        if payload.get("run_id") != run_id:
            raise RawStoreError(f"{label} run_id mismatch")
        for key in SAFETY_FLAGS:
            if payload.get(key) is not False:
                raise RawStoreError(f"{label} safety flag {key!r} must be false")
    expected_artifact = f"{prefix}/artifact.csv"
    if manifest.get("artifact_relative") != expected_artifact:
        raise RawStoreError("manifest artifact path mismatch")
    if receipt.get("artifact_relative") != expected_artifact:
        raise RawStoreError("receipt artifact path mismatch")
    actual_artifact_sha = _sha_file(artifact)
    if manifest.get("artifact_sha256") != actual_artifact_sha or receipt.get("artifact_sha256") != actual_artifact_sha:
        raise RawStoreError("artifact sha mismatch")
    with artifact.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != ARTIFACT_FIELDS:
            raise RawStoreError("raw artifact fields mismatch")
        rows = list(reader)
    row_count = len(rows)
    if manifest.get("row_count") != row_count or receipt.get("row_count") != row_count:
        raise RawStoreError("row_count mismatch")
    canonical_manifest_sha = canonical_sha(manifest)
    if receipt.get("manifest_sha256") != canonical_manifest_sha:
        raise RawStoreError("manifest sha mismatch")
    status = receipt.get("status")
    if status not in RAW_STATUSES or manifest.get("status") != status:
        raise RawStoreError("raw status mismatch")
    if status == "READY" and (row_count <= 0 or manifest.get("temporal_cutoff_safe") is not True):
        raise RawStoreError("READY lacks rows or temporal proof")
    if status == "READY_EMPTY" and row_count != 0:
        raise RawStoreError("READY_EMPTY contains rows")
    if status == "PARTIAL_WITH_ROWS" and row_count <= 0:
        raise RawStoreError("PARTIAL_WITH_ROWS lacks rows")
    return {
        "owner": expected_owner,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "role": role,
        "run_id": run_id,
        "status": status,
        "artifact_relative": expected_artifact,
        "manifest_relative": f"{prefix}/manifest.json",
        "receipt_relative": f"{prefix}/receipt.json",
        "artifact_sha256": actual_artifact_sha,
        "manifest_sha256": canonical_manifest_sha,
        "receipt_sha256": canonical_sha(receipt),
        "receipt_file_sha256": _sha_file(receipt_path),
        "row_count": row_count,
        "requested_rows": manifest.get("requested_rows", row_count),
        "source_rows": manifest.get("source_rows", row_count),
        "coverage_ratio": manifest.get("coverage_ratio", 1.0),
        "missing_symbols": list(manifest.get("missing_symbols", [])),
        "source_evidence": list(manifest.get("source_evidence", [])),
        "cannot_confirm": list(manifest.get("cannot_confirm", [])),
        "calendar": dict(manifest.get("calendar", calendar_provenance())),
        "source_id": receipt.get("source_id"),
        "source_status": receipt.get("source_status"),
        "idempotency_key": receipt.get("idempotency_key"),
        "window": receipt.get("window"),
        "cutoff_at": receipt.get("cutoff_at"),
    }


def _RawStore__verify_bundle_body(self, trade_date, stage_id, bundle_id):
    prefix = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}"
    receipt_relative = f"{prefix}/receipt.json"
    receipt_path = _safe_relative(self.root, receipt_relative)
    if not receipt_path.is_file():
        raise RawStoreError("bundle receipt missing")
    receipt = _read_json(receipt_path)
    if receipt.get("schema_version") != RAW_BUNDLE_SCHEMA_VERSION or receipt.get("owner") != "stage_center":
        raise RawStoreError("bundle receipt schema/owner mismatch")
    if receipt.get("trade_date") != trade_date or receipt.get("stage_id") != stage_id or receipt.get("bundle_id") != bundle_id:
        raise RawStoreError("bundle receipt identity mismatch")
    if receipt.get("receipt_relative") != receipt_relative:
        raise RawStoreError("bundle receipt path mismatch")
    for key in SAFETY_FLAGS:
        if receipt.get(key) is not False:
            raise RawStoreError(f"bundle receipt safety flag {key!r} must be false")
    markets = receipt.get("markets")
    if not isinstance(markets, Mapping):
        raise RawStoreError("bundle markets missing")
    expected_markets = set(_expected_bundle_markets(stage_id, trade_date))
    if set(markets) != expected_markets:
        raise RawStoreError("bundle market set mismatch")
    observed_statuses: set[str] = set()
    for market, entry in markets.items():
        if not isinstance(entry, Mapping):
            raise RawStoreError("bundle market entry malformed")
        verified = self.verify_run(trade_date, stage_id, market, str(entry.get("run_id")))
        if entry.get("receipt_sha256") != verified["receipt_sha256"] or entry.get("manifest_sha256") != verified["manifest_sha256"]:
            raise RawStoreError("bundle market SHA mismatch")
        observed_statuses.add(verified["status"])
    if observed_statuses == {"READY"}:
        expected_status = "READY"
    elif observed_statuses == {"READY_EMPTY"}:
        expected_status = "READY_EMPTY"
    elif observed_statuses == {"CANNOT_CONFIRM"} and all(
        self.verify_run(trade_date, stage_id, market, str(markets[market].get("run_id")))["row_count"] == 0
        for market in markets
    ):
        expected_status = "CANNOT_CONFIRM"
    else:
        expected_status = "PARTIAL_WITH_ROWS"
    if receipt.get("status") != expected_status:
        raise RawStoreError("bundle status summary mismatch")
    if receipt.get("calendar") != calendar_provenance():
        raise RawStoreError("bundle calendar provenance mismatch")
    return {
        "receipt": receipt,
        "receipt_sha256": canonical_sha(receipt),
        "receipt_file_sha256": _sha_file(receipt_path),
        "receipt_relative": receipt_relative,
    }
