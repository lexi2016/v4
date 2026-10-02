"""Verified daily HK Connect security metadata shared by V3 consumers.

The master contains reference fields only.  A stage consumer combines
``outstanding_shares`` with that stage's cutoff-safe last price; a later
snapshot price is never used to score an earlier stage.
"""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .hashing import canonical_bytes, sha256_file, sha256_json
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


def load_verified_hk_security_master(
    store_root: Path | str, trade_date: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    trade_date = validate_date(trade_date)
    asset_root = Path(store_root) / "assets" / "hk_security_master"
    try:
        latest = json.loads((asset_root / "latest.json").read_text(encoding="utf-8"))
        if latest.get("schema_version") != LATEST_SCHEMA_VERSION:
            raise StoreError("HK security-master latest schema mismatch")
        entry = latest["entries"][trade_date]
        manifest_path = resolve_under(asset_root, str(entry["manifest_relative"]))
        receipt_path = resolve_under(asset_root, str(entry["receipt_relative"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact = resolve_under(asset_root, str(manifest["artifact_relative"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StoreError(f"HK security-master metadata invalid: {error}") from error
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "READY"
        or manifest.get("trade_date") != trade_date
        or manifest.get("run_id") != entry.get("run_id")
        or receipt.get("run_id") != entry.get("run_id")
        or manifest.get("later_snapshot_price_allowed") is not False
        or any(manifest.get(key) is not False or receipt.get(key) is not False for key in _SAFETY)
    ):
        raise StoreError("HK security-master identity or safety contract invalid")
    if sha256_file(artifact) != manifest.get("artifact_sha256") or receipt.get("artifact_sha256") != manifest.get("artifact_sha256"):
        raise StoreError("HK security-master artifact checksum mismatch")
    if sha256_json(manifest) != receipt.get("manifest_sha256"):
        raise StoreError("HK security-master manifest checksum mismatch")
    rows: dict[str, dict[str, Any]] = {}
    with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().upper()
            if not code or code in rows:
                raise StoreError("HK security-master artifact code invalid")
            rows[code] = dict(row)
    if len(rows) != int(manifest.get("row_count") or -1):
        raise StoreError("HK security-master row count mismatch")
    return rows, manifest


__all__ = [
    "load_verified_hk_security_master",
    "publish_hk_security_master",
]


from scripts.live_acquisition.universe import resolve_stage_universe as _hk_asof_universe_reader

def read_verified_hk_eligibility_asof(
    store_root: Path | str, source_date: str, *, universe_root: Path | str | None = None,
) -> dict[str, Any]:
    """Bind reference metadata to the ORIGINAL captured membership authority.

    A security-master timestamp is never a substitute for a membership capture.
    The existing universe reader owns authority/plate/count/SHA validation. This
    adds the capture-date and cross-source binding needed by the HK-only owner.
    No old authority is reconstructed and no existing file is written.
    """
    from zoneinfo import ZoneInfo

    source_date = validate_date(source_date)
    root = Path(universe_root) if universe_root is not None else Path(store_root)
    try:
        universe = _hk_asof_universe_reader(root, source_date, "HK_CONNECT")
        raw = universe.path.read_bytes()
        payload = json.loads(raw)
        captured_at = payload.get("captured_at")
        captured = datetime.fromisoformat(captured_at)
        if (captured.tzinfo is None
                or captured.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") != source_date
                or payload.get("source_date") != source_date
                or universe.source_role != "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
                or payload.get("captured_at") != captured_at):
            raise ValueError("membership capture/date/source mismatch")
        current_relative = f"universes/{source_date}/HK_CONNECT_FULL_MARKET.current.json"
        current_path = resolve_under(root, current_relative)
        current_raw = current_path.read_bytes()
        current = json.loads(current_raw)
        run_id = current["run_id"]
        manifest_relative = f"universes/{source_date}/HK_CONNECT_FULL_MARKET.authority/{run_id}/manifest.json"
        receipt_relative = f"universes/{source_date}/HK_CONNECT_FULL_MARKET.authority/{run_id}/receipt.json"
        manifest_raw = resolve_under(root, manifest_relative).read_bytes()
        receipt_raw = resolve_under(root, receipt_relative).read_bytes()
        manifest = json.loads(manifest_raw)
        if (manifest.get("captured_at") != captured_at
                or manifest.get("artifact_sha256") != sha256_file(universe.path)
                or manifest.get("source_materialization") not in {
                    "FRESH_FUTU_ARTIFACT", "VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION"}):
            raise ValueError("original membership manifest/capture mismatch")
        rows, master = load_verified_hk_security_master(store_root, source_date)
        master_time = datetime.fromisoformat(master["captured_at"])
        if (master_time.tzinfo is None
                or master_time.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") != source_date
                or master["universe_codes_sha256"] != universe.codes_sha256
                or set(rows) != set(universe.codes)):
            raise ValueError("master is not bound to the verified membership")
        # Refuse a pointer move during this read; all original verification
        # remains in the existing reader, including its count/plate contract.
        again = _hk_asof_universe_reader(root, source_date, "HK_CONNECT")
        if (again != universe or universe.path.read_bytes() != raw
                or current_path.read_bytes() != current_raw):
            raise ValueError("membership changed during as-of verification")
        import hashlib
        return {
            "schema_version": "v4.hk_eligibility_asof.v1",
            "source_date": source_date, "captured_at": captured_at,
            "validity": "EXACT_CAPTURE_DATE_ONLY", "source_role": universe.source_role,
            "source_sha256": universe.source_sha256,
            "codes_sha256": universe.codes_sha256, "code_count": len(universe.codes),
            "authority_run_id": run_id,
            "authority_artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "authority_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "authority_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "authority_current_sha256": hashlib.sha256(current_raw).hexdigest(),
            "security_master_run_id": master["run_id"],
            "security_master_artifact_sha256": master["artifact_sha256"],
            "security_master_captured_at": master["captured_at"],
            # Capture is real evidence, but natural scheduler execution still
            # requires its original parent receipt; a unit test cannot grant it.
            "natural_verified": False, **_SAFETY,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise StoreError(f"HK eligibility source CANNOT_CONFIRM: {error}") from error

