"""Verified daily HK Connect security metadata shared by V3 consumers.

The master contains reference fields only.  A stage consumer combines
``outstanding_shares`` with that stage's cutoff-safe last price; a later
snapshot price is never used to score an earlier stage.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .hashing import canonical_bytes, sha256_bytes, sha256_file, sha256_json
from .paths import resolve_under, validate_date
from .store import StoreError


SCHEMA_VERSION = "v3_shared_data.hk_security_master.v1"
MANIFEST_SCHEMA_VERSION = "v3_shared_data.hk_security_master_manifest.v1"
RECEIPT_SCHEMA_VERSION = "v3_shared_data.hk_security_master_receipt.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.hk_security_master_latest.v1"
_FIELDS = (
    "code", "name", "outstanding_shares", "circular_market_val", "listing_date", "lot_size",
    "stock_owner", "stock_child_type", "sec_status", "captured_at", "source",
)
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _number(value: Any) -> float | str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return number if math.isfinite(number) and number >= 0 else ""


def _normalize_rows(rows: Sequence[Mapping[str, Any]], captured_at: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in rows:
        code = str(source.get("code") or "").strip().upper()
        name = str(source.get("name") or "").strip()
        if not code.startswith("HK.") or len(code) != 8 or not code[3:].isdigit():
            raise StoreError(f"invalid HK security-master code: {code!r}")
        if code in seen:
            raise StoreError(f"duplicate HK security-master code: {code}")
        if not name or name.upper() == code:
            raise StoreError(f"missing verified HK security name: {code}")
        seen.add(code)
        normalized.append({
            "code": code,
            "name": name,
            "outstanding_shares": _number(source.get("outstanding_shares")),
            "circular_market_val": _number(source.get("circular_market_val")),
            "listing_date": str(source.get("listing_date") or "").strip(),
            "lot_size": _number(source.get("lot_size")),
            "stock_owner": str(source.get("stock_owner") or "").strip(),
            "stock_child_type": str(source.get("stock_child_type") or "").strip(),
            "sec_status": str(source.get("sec_status") or "").strip(),
            "captured_at": captured_at,
            "source": "FUTU_OPEND_MARKET_SNAPSHOT",
        })
    return sorted(normalized, key=lambda row: row["code"])


def _latest_path(store_root: Path) -> Path:
    return store_root / "assets" / "hk_security_master" / "latest.json"


def publish_hk_security_master(
    store_root: Path | str,
    *,
    trade_date: str,
    rows: Sequence[Mapping[str, Any]],
    universe_codes_sha256: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    trade_date = validate_date(trade_date)
    captured_at = captured_at or datetime.now().astimezone().isoformat(timespec="seconds")
    normalized = _normalize_rows(rows, captured_at)
    if not normalized:
        raise StoreError("HK security master cannot be empty")
    if len(str(universe_codes_sha256)) != 64:
        raise StoreError("HK security-master universe hash invalid")
    run_id = sha256_json({
        "trade_date": trade_date,
        "universe_codes_sha256": universe_codes_sha256,
        "rows": normalized,
    })[:24]
    asset_root = Path(store_root) / "assets" / "hk_security_master"
    run_root = asset_root / "runs" / trade_date / run_id
    artifact = run_root / "artifact.csv"
    if not artifact.exists():
        artifact.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".artifact.", suffix=".tmp", dir=artifact.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(normalized)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, artifact)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    relative_root = f"runs/{trade_date}/{run_id}"
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "trade_date": trade_date,
        "run_id": run_id,
        "captured_at": captured_at,
        "row_count": len(normalized),
        "universe_codes_sha256": universe_codes_sha256,
        "artifact_relative": f"{relative_root}/artifact.csv",
        "artifact_sha256": sha256_file(artifact),
        "stage_valuation_policy": "OUTSTANDING_SHARES_X_CUTOFF_LAST_PRICE",
        "valuation_eligibility_field": "circular_market_val",
        "later_snapshot_price_allowed": False,
        **_SAFETY,
    }
    manifest_path = run_root / "manifest.json"
    _atomic_write(manifest_path, canonical_bytes(manifest))
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "READY",
        "trade_date": trade_date,
        "run_id": run_id,
        "artifact_sha256": manifest["artifact_sha256"],
        "manifest_sha256": sha256_json(manifest),
        **_SAFETY,
    }
    _atomic_write(run_root / "receipt.json", canonical_bytes(receipt))
    latest_path = _latest_path(Path(store_root))
    latest = {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    if latest_path.is_file():
        try:
            loaded = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"HK security-master latest invalid: {error}") from error
        if loaded.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(loaded.get("entries"), dict):
            raise StoreError("HK security-master latest schema invalid")
        latest = loaded
    latest["entries"][trade_date] = {
        "run_id": run_id,
        "manifest_relative": f"{relative_root}/manifest.json",
        "receipt_relative": f"{relative_root}/receipt.json",
    }
    _atomic_write(latest_path, canonical_bytes(latest))
    return {**receipt, "row_count": len(normalized), "manifest": manifest}



def _copy_exact_verified_file(source: Path, destination: Path) -> bool:
    """Copy immutable evidence bytes once; an existing mismatch is a conflict."""
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise StoreError(f"HK security-master source evidence unreadable: {error}") from error
    if destination.exists():
        try:
            existing = destination.read_bytes()
        except OSError as error:
            raise StoreError(f"HK security-master target evidence unreadable: {error}") from error
        if existing != payload:
            raise StoreError(f"HK security-master target conflict: {destination}")
        return False
    _atomic_write(destination, payload)
    return True


def restore_verified_hk_security_master(
    source_store_root: Path | str,
    target_store_root: Path | str,
    *,
    trade_date: str,
) -> dict[str, Any]:
    """Restore one already-verified exact-date master into another owned root.

    This is a provenance-preserving migration path only.  It performs no live
    collection and never rewrites the artifact, manifest, or receipt bytes.
    The source must first pass the normal current reader, and the target is
    re-read with that same reader before success is returned.
    """
    trade_date = validate_date(trade_date)
    source_root = Path(source_store_root)
    target_root = Path(target_store_root)
    source_rows, source_manifest = load_verified_hk_security_master(source_root, trade_date)
    del source_rows

    source_asset_root = source_root / "assets" / "hk_security_master"
    try:
        source_latest = json.loads((source_asset_root / "latest.json").read_text(encoding="utf-8"))
        if source_latest.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(source_latest.get("entries"), dict):
            raise StoreError("HK security-master source latest schema invalid")
        source_entry = dict(source_latest["entries"][trade_date])
        source_manifest_path = resolve_under(source_asset_root, str(source_entry["manifest_relative"]))
        source_receipt_path = resolve_under(source_asset_root, str(source_entry["receipt_relative"]))
        source_artifact_path = resolve_under(source_asset_root, str(source_manifest["artifact_relative"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, StoreError):
            raise
        raise StoreError(f"HK security-master source pointer invalid: {error}") from error

    target_asset_root = target_root / "assets" / "hk_security_master"
    target_latest_path = target_asset_root / "latest.json"
    latest = {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    if target_latest_path.is_file():
        try:
            latest = json.loads(target_latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"HK security-master target latest invalid: {error}") from error
        if latest.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(latest.get("entries"), dict):
            raise StoreError("HK security-master target latest schema invalid")
        existing = latest["entries"].get(trade_date)
        if existing is not None and any(
            existing.get(key) != source_entry.get(key)
            for key in ("run_id", "manifest_relative", "receipt_relative")
        ):
            raise StoreError("HK security-master target date already points to a different run")

    copied = False
    for source_path, relative in (
        (source_artifact_path, str(source_manifest["artifact_relative"])),
        (source_manifest_path, str(source_entry["manifest_relative"])),
        (source_receipt_path, str(source_entry["receipt_relative"])),
    ):
        copied = _copy_exact_verified_file(
            source_path, resolve_under(target_asset_root, relative)
        ) or copied

    latest["entries"][trade_date] = source_entry
    _atomic_write(target_latest_path, canonical_bytes(latest))
    _, restored_manifest = load_verified_hk_security_master(target_root, trade_date)
    if (
        restored_manifest.get("run_id") != source_manifest.get("run_id")
        or restored_manifest.get("artifact_sha256") != source_manifest.get("artifact_sha256")
    ):
        raise StoreError("HK security-master restored identity mismatch")
    return {
        "status": "READY",
        "trade_date": trade_date,
        "run_id": source_manifest["run_id"],
        "artifact_sha256": source_manifest["artifact_sha256"],
        "restored": copied,
        "already_exists": not copied,
        **_SAFETY,
    }

class HKSecurityMasterReadError(StoreError):
    """A bounded reader reason and the exact index observation that failed.

    Diagnostic fields contain no exception text, file paths, or security rows.
    Missing exact-date input remains distinct from invalid referenced evidence.
    """

    def __init__(self, reason_code: str, diagnostic: Mapping[str, Any]) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.diagnostic = dict(diagnostic, reason_code=reason_code)


def load_verified_hk_security_master_snapshot(
    store_root: Path | str, trade_date: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Read one exact-date indexed run and witness the same verified bytes.

    The date index is read once. A newer pointer cannot replace the run already
    selected here, and a missing entry never consults another date or scans runs.
    Existing consumers can keep using the two-value loader below.
    """
    trade_date = validate_date(trade_date)
    asset_root = Path(store_root) / "assets" / "hk_security_master"
    diagnostic: dict[str, Any] = {
        "status": "INVALID", "reason_code": None, "requested_trade_date": trade_date,
        "validation_stage": "INDEX_READ", "latest_json_sha256": None,
        "entry_count": None, "latest_entry_date": None, "requested_entry_present": None,
    }

    def failure(reason_code: str, stage: str, *, status: str = "INVALID") -> HKSecurityMasterReadError:
        return HKSecurityMasterReadError(reason_code,
            dict(diagnostic, status=status, validation_stage=stage))

    try:
        latest_bytes = (asset_root / "latest.json").read_bytes()
    except FileNotFoundError as error:
        raise failure("HK_SECURITY_MASTER_INDEX_MISSING", "INDEX_READ", status="MISSING") from error
    except OSError as error:
        raise failure("HK_SECURITY_MASTER_INDEX_UNREADABLE", "INDEX_READ") from error
    diagnostic["latest_json_sha256"] = sha256_bytes(latest_bytes)
    try:
        latest = json.loads(latest_bytes.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise failure("HK_SECURITY_MASTER_INDEX_INVALID", "INDEX_SCHEMA") from error
    if (not isinstance(latest, dict) or latest.get("schema_version") != LATEST_SCHEMA_VERSION
            or not isinstance(latest.get("entries"), dict)):
        raise failure("HK_SECURITY_MASTER_INDEX_SCHEMA_INVALID", "INDEX_SCHEMA")
    entries = latest["entries"]
    dates = [key for key in entries if len(key) == 8 and key.isascii() and key.isdigit()]
    diagnostic.update(entry_count=len(entries), latest_entry_date=max(dates) if dates else None,
                      requested_entry_present=trade_date in entries)
    if trade_date not in entries:
        raise failure("HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING", "INDEX_LOOKUP", status="MISSING")
    entry = entries[trade_date]
    if (not isinstance(entry, dict) or not isinstance(entry.get("run_id"), str)
            or not entry["run_id"] or not isinstance(entry.get("manifest_relative"), str)
            or not isinstance(entry.get("receipt_relative"), str)):
        raise failure("HK_SECURITY_MASTER_ENTRY_INVALID", "INDEX_ENTRY")
    try:
        manifest_path = resolve_under(asset_root, entry["manifest_relative"])
        receipt_path = resolve_under(asset_root, entry["receipt_relative"])
        manifest_bytes = manifest_path.read_bytes()
        receipt_bytes = receipt_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        if not isinstance(manifest, dict) or not isinstance(receipt, dict):
            raise ValueError("metadata objects required")
        artifact = resolve_under(asset_root, manifest["artifact_relative"])
    except OSError as error:
        raise failure("HK_SECURITY_MASTER_METADATA_UNREADABLE", "METADATA_READ") from error
    except (ValueError, KeyError, TypeError) as error:
        raise failure("HK_SECURITY_MASTER_METADATA_INVALID", "METADATA_READ") from error
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "READY"
        or manifest.get("trade_date") != trade_date
        or receipt.get("trade_date") != trade_date
        or manifest.get("run_id") != entry.get("run_id")
        or receipt.get("run_id") != entry.get("run_id")
        or manifest.get("later_snapshot_price_allowed") is not False
        or any(manifest.get(key) is not False or receipt.get(key) is not False for key in _SAFETY)
    ):
        raise failure("HK_SECURITY_MASTER_IDENTITY_OR_SAFETY_INVALID", "IDENTITY")
    try:
        artifact_bytes = artifact.read_bytes()
    except OSError as error:
        raise failure("HK_SECURITY_MASTER_ARTIFACT_UNREADABLE", "ARTIFACT_READ") from error
    artifact_sha256 = sha256_bytes(artifact_bytes)
    if artifact_sha256 != manifest.get("artifact_sha256") or receipt.get("artifact_sha256") != manifest.get("artifact_sha256"):
        raise failure("HK_SECURITY_MASTER_ARTIFACT_CHECKSUM_MISMATCH", "ARTIFACT_CHECKSUM")
    if sha256_json(manifest) != receipt.get("manifest_sha256"):
        raise failure("HK_SECURITY_MASTER_MANIFEST_CHECKSUM_MISMATCH", "MANIFEST_CHECKSUM")
    rows: dict[str, dict[str, Any]] = {}
    try:
        handle = io.StringIO(artifact_bytes.decode("utf-8-sig"), newline="")
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().upper()
            if not code or code in rows:
                raise failure("HK_SECURITY_MASTER_ARTIFACT_CODE_INVALID", "ARTIFACT_ROWS")
            rows[code] = dict(row)
        expected_count = int(manifest.get("row_count") or -1)
    except (UnicodeError, csv.Error, ValueError, TypeError) as error:
        raise failure("HK_SECURITY_MASTER_ARTIFACT_INVALID", "ARTIFACT_ROWS") from error
    if len(rows) != expected_count:
        raise failure("HK_SECURITY_MASTER_ROW_COUNT_MISMATCH", "ARTIFACT_ROWS")
    diagnostic.update(status="VERIFIED", reason_code=None, validation_stage="COMPLETE")
    witness = {
        "manifest_path": str(manifest_path), "manifest_sha256": sha256_bytes(manifest_bytes),
        "artifact_path": str(artifact), "artifact_sha256": artifact_sha256,
        "receipt_path": str(receipt_path), "receipt_sha256": sha256_bytes(receipt_bytes),
        "row_count": manifest.get("row_count"), "run_id": manifest.get("run_id"),
        "captured_at": manifest.get("captured_at"), "read_diagnostic": diagnostic,
    }
    return rows, manifest, witness


def load_verified_hk_security_master(
    store_root: Path | str, trade_date: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rows, manifest, _ = load_verified_hk_security_master_snapshot(store_root, trade_date)
    return rows, manifest


__all__ = [
    "HKSecurityMasterReadError",
    "load_verified_hk_security_master",
    "load_verified_hk_security_master_snapshot",
    "publish_hk_security_master",
    "restore_verified_hk_security_master",
]
