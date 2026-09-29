"""Atomic total receipts for two-market shared stage bundles."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .hashing import sha256_json
from .hashing import sha256_file
from .paths import resolve_under, validate_date, validate_role
from .store import ConflictError, SafeRootStore, StoreError

BUNDLE_SCHEMA_VERSION = "v3_shared_data.stage_bundle_receipt.v1"
BUNDLE_LATEST_SCHEMA_VERSION = "v3_shared_data.stage_bundle_latest.v1"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def publish_bundle_receipt(
    store_root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    status: str,
    markets: Mapping[str, Mapping[str, Any]],
    error: str = "",
    historical_backfill: bool = False,
    expected_previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one immutable attempt and atomically advance bundle_latest.

    Failed attempts may be superseded by a later retry.  Once a READY bundle
    owns the date/stage slot, only byte-equivalent idempotent re-entry is
    accepted; any different successful input conflicts.
    """
    trade_date = validate_date(trade_date)
    validate_role(stage_id)
    if status not in {"READY", "FAILED"}:
        raise StoreError(f"invalid bundle status {status!r}")
    market_payload = {key: dict(value) for key, value in sorted(markets.items())}
    if not market_payload or not set(market_payload).issubset({"A_SHARE", "HK_CONNECT"}):
        raise StoreError("bundle contains an invalid market set")
    if status == "READY" and any(value.get("status") != "READY" for value in market_payload.values()):
        raise StoreError("READY bundle requires both market runs READY")

    idempotency_key = sha256_json(
        {
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": status,
            "markets": market_payload,
            "error": str(error or ""),
        }
    )
    role_slug = stage_id.lower().replace("_", "-")
    bundle_id = f"{trade_date}-{role_slug}-{idempotency_key[:12]}"
    receipt_relative = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}/receipt.json"
    latest_path = Path(store_root) / "bundle_latest.json"
    store = SafeRootStore(Path(store_root))

    with store._lock():  # package-owned atomic serialization with component runs
        if latest_path.exists():
            latest = store._read_json(latest_path)
            if (
                latest.get("schema_version") != BUNDLE_LATEST_SCHEMA_VERSION
                or not isinstance(latest.get("entries"), Mapping)
            ):
                raise StoreError("bundle_latest.json corrupt")
        else:
            latest = {"schema_version": BUNDLE_LATEST_SCHEMA_VERSION, "entries": {}}
        key = f"{trade_date}/{stage_id}"
        existing = latest["entries"].get(key)
        previous_identity: dict[str, Any] | None = None
        supersession_relative: str | None = None
        if isinstance(existing, Mapping):
            if existing.get("idempotency_key") == idempotency_key:
                receipt_path = resolve_under(Path(store_root), str(existing["receipt_relative"]))
                receipt = store._read_json(receipt_path)
                if expected_previous is not None:
                    current_identity = {
                        "bundle_id": receipt.get("bundle_id"),
                        "idempotency_key": receipt.get("idempotency_key"),
                        "receipt_relative": str(existing["receipt_relative"]),
                        "receipt_sha256": sha256_file(receipt_path),
                    }
                    if any(
                        current_identity.get(field) != value
                        for field, value in expected_previous.items()
                    ):
                        raise ConflictError("expected_previous bundle identity mismatch")
                return {
                    "ok": receipt.get("status") == "READY",
                    "already_exists": True,
                    "bundle_id": receipt["bundle_id"],
                    "status": receipt["status"],
                    "receipt_relative": str(existing["receipt_relative"]),
                }
            if existing.get("status") == "READY":
                if not historical_backfill:
                    raise ConflictError(
                        f"bundle slot {key} already has READY bundle {existing.get('bundle_id')}"
                    )
                old_receipt_path = resolve_under(Path(store_root), str(existing["receipt_relative"]))
                old_receipt = store._read_json(old_receipt_path)
                if (
                    old_receipt.get("schema_version") != BUNDLE_SCHEMA_VERSION
                    or old_receipt.get("bundle_id") != existing.get("bundle_id")
                    or old_receipt.get("idempotency_key") != existing.get("idempotency_key")
                    or old_receipt.get("status") != "READY"
                    or old_receipt.get("trade_date") != trade_date
                    or old_receipt.get("stage_id") != stage_id
                    or any(old_receipt.get(flag) is not False for flag in (
                        "production_allowed", "buy_gate_updated", "orders_sent"
                    ))
                ):
                    raise StoreError("existing READY bundle receipt is invalid")
                previous_identity = {
                    "bundle_id": old_receipt.get("bundle_id"),
                    "idempotency_key": old_receipt.get("idempotency_key"),
                    "receipt_relative": str(existing["receipt_relative"]),
                    "receipt_sha256": sha256_file(old_receipt_path),
                }
                if expected_previous is not None and any(
                    previous_identity.get(field) != value
                    for field, value in expected_previous.items()
                ):
                    raise ConflictError("expected_previous bundle identity mismatch")

        receipt_path = resolve_under(Path(store_root), receipt_relative)
        if previous_identity is not None:
            supersession_relative = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}/supersession.json"
        if receipt_path.exists():
            previous = store._read_json(receipt_path)
            if previous.get("idempotency_key") != idempotency_key:
                raise ConflictError(f"bundle run dir exists for a different key: {receipt_path.parent}")
        receipt = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "owner": "v3_shared_data",
            "bundle_id": bundle_id,
            "idempotency_key": idempotency_key,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": status,
            "error": str(error or ""),
            "markets": market_payload,
            "finished_at": _now_iso(),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if previous_identity is not None:
            receipt.update(
                {
                    "historical_backfill": True,
                    "supersedes": previous_identity,
                    "supersession_relative": supersession_relative,
                }
            )
        store._write_json(receipt_path, receipt)
        if previous_identity is not None and supersession_relative is not None:
            store._write_json(
                resolve_under(Path(store_root), supersession_relative),
                {
                    "schema_version": "v3_shared_data.supersession.v1",
                    "owner": "v3_shared_data",
                    "reason": "historical_backfill",
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "previous": previous_identity,
                    "replacement": {
                        "bundle_id": bundle_id,
                        "idempotency_key": idempotency_key,
                        "receipt_relative": receipt_relative,
                        "receipt_sha256": sha256_file(receipt_path),
                    },
                },
            )
        entries = dict(latest["entries"])
        entries[key] = {
            "bundle_id": bundle_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "receipt_relative": receipt_relative,
            "updated_at": _now_iso(),
        }
        if previous_identity is not None and supersession_relative is not None:
            entries[key].update(
                {
                    "superseded_from": previous_identity,
                    "supersession_relative": supersession_relative,
                }
            )
        store._write_json(
            latest_path,
            {"schema_version": BUNDLE_LATEST_SCHEMA_VERSION, "entries": entries},
        )
    return {
        "ok": status == "READY",
        "already_exists": False,
        "bundle_id": bundle_id,
        "status": status,
        "receipt_relative": receipt_relative,
    }
