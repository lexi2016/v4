"""Verified A-share selector security registry for shared, read-only consumers.

The registry is deliberately a small adapter around the V3 selector panel
contract.  It does not score or select securities: it only snapshots the
``trade_date == signal_date`` rows whose ``ts_code`` and ``name`` satisfy the
same filtering and first-seen name mapping used by V3's research pool.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .hashing import canonical_bytes, sha256_file, sha256_json
from .paths import resolve_under, validate_date
from .store import StoreError


SCHEMA_VERSION = "v3_shared_data.a_share_security_master.v1"
MANIFEST_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_manifest.v1"
RECEIPT_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_receipt.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_latest.v1"
_FIELDS = ("ts_code", "code", "name", "market", "signal_date")
_CODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
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


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return text
    match = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})(?:[T ]|$).*", text)
    return "".join(match.groups()[:3]) if match else ""


def _selector_rows(selector_path: Path | str, signal_date: str) -> list[dict[str, str]]:
    """Read the exact selector date and apply V3 code/name semantics."""
    signal_date = validate_date(signal_date)
    selector_path = Path(selector_path)
    if not selector_path.is_file() or selector_path.is_symlink():
        raise StoreError("selector parquet must be an existing regular file")
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(selector_path)
        required = {"trade_date", "ts_code", "name"}
        missing = sorted(required - set(parquet.schema.names))
        if missing:
            raise StoreError(f"selector parquet columns missing: {','.join(missing)}")
        table = pq.read_table(selector_path, columns=["trade_date", "ts_code", "name"])
    except StoreError:
        raise
    except (ImportError, OSError, ValueError, TypeError) as error:
        raise StoreError(f"selector parquet unreadable: {error}") from error

    code_rows: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    dates_seen: set[str] = set()
    for raw_date, raw_ts_code, raw_name in zip(
        table.column("trade_date").to_pylist(),
        table.column("ts_code").to_pylist(),
        table.column("name").to_pylist(),
    ):
        row_date = _date_text(raw_date)
        if row_date:
            dates_seen.add(row_date)
        if row_date != signal_date:
            continue
        ts_code = str(raw_ts_code or "").strip().upper()
        match = _CODE_RE.fullmatch(ts_code)
        name = str(raw_name or "").strip()
        if not match or not name or len(name) < 2:
            continue
        code, market = match.groups()
        # V3 uses a set for code membership and setdefault for first-seen names.
        # Retain the first valid name for a code while preserving the input order
        # for duplicate display names.
        code_rows.setdefault(
            code,
            {
                "ts_code": ts_code,
                "code": code,
                "name": name,
                "market": market,
                "signal_date": signal_date,
            },
        )
        names.setdefault(name, code)
    if signal_date not in dates_seen:
        raise StoreError(f"selector parquet has no exact selector date: {signal_date}")
    # Keep first-seen code order.  This is intentional: V3's name mapping uses
    # ``setdefault`` while scanning the panel, so a duplicate display name must
    # resolve to the first valid code in panel order.
    rows = list(code_rows.values())
    if not rows:
        raise StoreError(f"selector parquet exact selector date is empty: {signal_date}")
    return rows


def _asset_root(store_root: Path | str) -> Path:
    return Path(store_root) / "assets" / "a_share_security_master"


def _latest_path(store_root: Path | str) -> Path:
    return _asset_root(store_root) / "latest.json"


def _entry_for_date(latest_path: Path, signal_date: str) -> dict[str, Any] | None:
    if not latest_path.is_file():
        return None
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StoreError(f"A-share security-master latest invalid: {error}") from error
    if latest.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(latest.get("entries"), dict):
        raise StoreError("A-share security-master latest schema invalid")
    entry = latest["entries"].get(signal_date)
    if entry is not None and not isinstance(entry, dict):
        raise StoreError("A-share security-master latest entry invalid")
    return entry


def publish_a_share_security_master(
    store_root: Path | str,
    *,
    signal_date: str,
    selector_path: Path | str,
) -> dict[str, Any]:
    """Publish one immutable exact-date selector registry.

    A date already present in ``latest.json`` can only be reused when the
    computed input/run identity is identical.  A different input is a hard
    conflict; the existing verified publication is never overwritten.
    """
    signal_date = validate_date(signal_date)
    selector_path = Path(selector_path)
    rows = _selector_rows(selector_path, signal_date)
    selector_sha256 = sha256_file(selector_path)
    codes = [row["code"] for row in rows]
    name_to_code: dict[str, str] = {}
    for row in rows:
        name_to_code.setdefault(row["name"], row["code"])
    run_id = sha256_json({
        "signal_date": signal_date,
        "selector_sha256": selector_sha256,
        "rows": rows,
        "name_to_code": name_to_code,
    })[:24]
    asset_root = _asset_root(store_root)
    latest_path = asset_root / "latest.json"
    existing = _entry_for_date(latest_path, signal_date)
    if existing is not None:
        if existing.get("run_id") != run_id:
            raise StoreError(f"A-share security-master conflict for {signal_date}")
        # Reusing requires a complete, untampered existing publication.
        _, manifest = load_verified_a_share_security_master(store_root, signal_date)
        if manifest.get("run_id") != run_id or manifest.get("selector_sha256") != selector_sha256:
            raise StoreError("A-share security-master existing publication identity mismatch")
        return {
            "status": "READY",
            "reused": True,
            "signal_date": signal_date,
            "run_id": run_id,
            "row_count": len(rows),
            **_SAFETY,
        }

    relative_root = f"runs/{signal_date}/{run_id}"
    run_root = asset_root / "runs" / signal_date / run_id
    artifact = run_root / "artifact.csv"
    if run_root.exists():
        raise StoreError("A-share security-master run directory conflicts")
    run_root.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".artifact.", suffix=".tmp", dir=run_root)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, artifact)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "signal_date": signal_date,
        "trade_date": signal_date,
        "run_id": run_id,
        "selector_sha256": selector_sha256,
        "row_count": len(rows),
        "code_count": len(codes),
        "name_count": len(name_to_code),
        "codes_sha256": sha256_json(codes),
        "name_to_code_sha256": sha256_json(name_to_code),
        "name_to_code": name_to_code,
        "selector_semantics": "V3_A_SHARE_PANEL_CODE_SET_AND_FIRST_SEEN_NAME_MAP",
        "source_kind": "EXPLICIT_SELECTOR_PARQUET",
        "research_only": True,
        "artifact_relative": f"{relative_root}/artifact.csv",
        "artifact_sha256": sha256_file(artifact),
        **_SAFETY,
    }
    _atomic_write(run_root / "manifest.json", canonical_bytes(manifest))
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "READY",
        "signal_date": signal_date,
        "trade_date": signal_date,
        "run_id": run_id,
        "row_count": len(rows),
        "artifact_sha256": manifest["artifact_sha256"],
        "manifest_sha256": sha256_json(manifest),
        "research_only": True,
        **_SAFETY,
    }
    _atomic_write(run_root / "receipt.json", canonical_bytes(receipt))
    latest = {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    if latest_path.is_file():
        try:
            loaded = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"A-share security-master latest invalid: {error}") from error
        if loaded.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(loaded.get("entries"), dict):
            raise StoreError("A-share security-master latest schema invalid")
        latest = loaded
    latest["entries"][signal_date] = {
        "run_id": run_id,
        "manifest_relative": f"{relative_root}/manifest.json",
        "receipt_relative": f"{relative_root}/receipt.json",
    }
    _atomic_write(latest_path, canonical_bytes(latest))
    return {
        **receipt,
        "reused": False,
        "row_count": len(rows),
        "manifest": manifest,
    }


def load_verified_a_share_security_master(
    store_root: Path | str, signal_date: str
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load and verify the immutable registry, failing closed on any mismatch."""
    signal_date = validate_date(signal_date)
    asset_root = _asset_root(store_root)
    latest_path = asset_root / "latest.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest.get("schema_version") != LATEST_SCHEMA_VERSION:
            raise StoreError("A-share security-master latest schema mismatch")
        entry = latest["entries"][signal_date]
        manifest_path = resolve_under(asset_root, str(entry["manifest_relative"]))
        receipt_path = resolve_under(asset_root, str(entry["receipt_relative"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact = resolve_under(asset_root, str(manifest["artifact_relative"]))
    except StoreError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StoreError(f"A-share security-master metadata invalid: {error}") from error
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "READY"
        or manifest.get("signal_date") != signal_date
        or manifest.get("trade_date") != signal_date
        or receipt.get("signal_date") != signal_date
        or receipt.get("trade_date") != signal_date
        or manifest.get("run_id") != entry.get("run_id")
        or receipt.get("run_id") != entry.get("run_id")
        or receipt.get("row_count") != manifest.get("row_count")
        or manifest.get("research_only") is not True
        or receipt.get("research_only") is not True
        or any(manifest.get(key) is not False or receipt.get(key) is not False for key in _SAFETY)
    ):
        raise StoreError("A-share security-master identity or safety contract invalid")
    if sha256_file(artifact) != manifest.get("artifact_sha256") or receipt.get("artifact_sha256") != manifest.get("artifact_sha256"):
        raise StoreError("A-share security-master artifact checksum mismatch")
    if sha256_json(manifest) != receipt.get("manifest_sha256"):
        raise StoreError("A-share security-master manifest checksum mismatch")
    rows: dict[str, dict[str, str]] = {}
    try:
        with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _FIELDS:
                raise StoreError("A-share security-master artifact columns invalid")
            for row in reader:
                ts_code = str(row.get("ts_code") or "").strip().upper()
                match = _CODE_RE.fullmatch(ts_code)
                code = str(row.get("code") or "").strip()
                name = str(row.get("name") or "").strip()
                if (
                    not match
                    or match.group(1) != code
                    or row.get("market") != match.group(2)
                    or row.get("signal_date") != signal_date
                    or not name
                    or len(name) < 2
                ):
                    raise StoreError("A-share security-master artifact row invalid")
                if code in rows:
                    raise StoreError("A-share security-master artifact duplicate code")
                rows[code] = dict(row)
    except StoreError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise StoreError(f"A-share security-master artifact unreadable: {error}") from error
    if len(rows) != int(manifest.get("row_count") or -1) or len(rows) != int(manifest.get("code_count") or -1):
        raise StoreError("A-share security-master row count mismatch")
    if sha256_json(list(rows)) != manifest.get("codes_sha256"):
        raise StoreError("A-share security-master code set checksum mismatch")
    name_to_code: dict[str, str] = {}
    for row in rows.values():
        name_to_code.setdefault(row["name"], row["code"])
    if (
        len(name_to_code) != int(manifest.get("name_count") or -1)
        or sha256_json(name_to_code) != manifest.get("name_to_code_sha256")
        or manifest.get("name_to_code") != name_to_code
    ):
        raise StoreError("A-share security-master name map checksum mismatch")
    return rows, manifest


__all__ = [
    "load_verified_a_share_security_master",
    "publish_a_share_security_master",
]
