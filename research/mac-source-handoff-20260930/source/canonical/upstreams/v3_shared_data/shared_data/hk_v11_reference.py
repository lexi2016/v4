"""Verified frozen V3 v1.1 universe reference imported for shared consumers."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .hashing import canonical_bytes, sha256_file, sha256_json
from .paths import resolve_under
from .store import StoreError


SCHEMA_VERSION = "v3_shared_data.hk_v11_reference.v1"
_FIELDS = ("code", "name", "source_universe", "circular_market_cap_hkd_yi")


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


def import_hk_v11_reference(
    store_root: Path | str, source_path: Path | str
) -> dict[str, Any]:
    source_path = Path(source_path)
    if not source_path.is_file():
        raise StoreError(f"V3 v1.1 reference source missing: {source_path}")
    rows: dict[str, dict[str, Any]] = {}
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for source in csv.DictReader(handle):
            code = str(source.get("code") or "").strip().upper()
            if not code.startswith("HK.") or len(code) != 8 or not code[3:].isdigit():
                continue
            try:
                cap = float(source.get("circular_market_cap_hkd_yi"))
            except (TypeError, ValueError):
                cap = ""
            rows[code] = {
                "code": code,
                "name": str(source.get("name") or "").strip(),
                "source_universe": "LIVE_HKCONNECT_GAINER",
                "circular_market_cap_hkd_yi": cap,
            }
    if not rows:
        raise StoreError("V3 v1.1 reference source has no valid rows")
    ordered = [rows[code] for code in sorted(rows)]
    source_sha = sha256_file(source_path)
    run_id = sha256_json({"source_sha256": source_sha, "rows": ordered})[:24]
    root = Path(store_root) / "assets" / "hk_v11_reference"
    run_root = root / "runs" / run_id
    artifact = run_root / "artifact.csv"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".artifact.", suffix=".tmp", dir=artifact.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(ordered)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, artifact)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "source_sha256": source_sha,
        "source_kind": "V3_FROZEN_LIVE_HKCONNECT_GAINER_REFERENCE",
        "artifact_relative": f"runs/{run_id}/artifact.csv",
        "artifact_sha256": sha256_file(artifact),
        "row_count": len(ordered),
        "runtime_v3_read_allowed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _atomic_write(run_root / "manifest.json", canonical_bytes(manifest))
    _atomic_write(root / "latest.json", canonical_bytes({
        "schema_version": SCHEMA_VERSION,
        "manifest_relative": f"runs/{run_id}/manifest.json",
    }))
    return manifest


def load_verified_hk_v11_reference(
    store_root: Path | str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    root = Path(store_root) / "assets" / "hk_v11_reference"
    try:
        latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        if latest.get("schema_version") != SCHEMA_VERSION:
            raise StoreError("V3 v1.1 reference pointer schema mismatch")
        manifest_path = resolve_under(root, str(latest["manifest_relative"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = resolve_under(root, str(manifest["artifact_relative"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StoreError(f"V3 v1.1 reference metadata invalid: {error}") from error
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("runtime_v3_read_allowed") is not False
        or any(manifest.get(key) is not False for key in (
            "production_allowed", "buy_gate_updated", "orders_sent"
        ))
        or sha256_file(artifact) != manifest.get("artifact_sha256")
    ):
        raise StoreError("V3 v1.1 reference contract invalid")
    rows: dict[str, dict[str, Any]] = {}
    with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().upper()
            if not code or code in rows:
                raise StoreError("V3 v1.1 reference artifact invalid")
            rows[code] = dict(row)
    if len(rows) != int(manifest.get("row_count") or -1):
        raise StoreError("V3 v1.1 reference row count mismatch")
    return rows, manifest


__all__ = ["import_hk_v11_reference", "load_verified_hk_v11_reference"]
