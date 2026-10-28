"""Materialize one exact-date V4 research day from eight named slots."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

import contracts.research_day_product as contract_module
import domains.research_day_product as domain_module
from contracts.research_day_product import EXPECTED_RESEARCH_SLOTS
from domains.research_day_product import build_research_day_product
from infrastructure.data_store import _sha256
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore


def _transformer_identity_sha256() -> str:
    """Identify the canonical contract and domain code used by this wrapper."""

    files: dict[str, str] = {}
    for module in (contract_module, domain_module):
        path = inspect.getsourcefile(module)
        if path is None:
            raise ValueError("research day transformer source is unavailable")
        files[module.__name__] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    value = {
        "schema_version": "v3_5.research_day_transformer_identity.v1",
        "components": files,
    }
    return _sha256(value)


def _hourly_source_ref(
    hourly: HourlyResearchStore,
    payload: Mapping[str, Any],
    *,
    archive_date: str,
    slot: str,
) -> dict[str, Any]:
    artifact_path = hourly._relative(archive_date, slot, "LIVE")
    receipt_path = hourly._receipt_relative(archive_date, slot, "LIVE")
    artifact_sha = _sha256(payload)
    receipt = hourly._receipt(payload, artifact_sha, slot=slot, mode="LIVE")
    return {
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha,
        "receipt_path": receipt_path,
        "receipt_sha256": _sha256(receipt),
        "source_input_sha256": str(payload["source_input_sha256"]),
    }


def materialize_research_day(
    data_root: Path,
    archive_date: str,
    *,
    expected_slots: tuple[str, ...] = EXPECTED_RESEARCH_SLOTS,
    stock_mentions_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read exactly the requested LIVE slots and publish one exact-date product."""

    if tuple(expected_slots) != EXPECTED_RESEARCH_SLOTS:
        raise ValueError("research day expected slots are frozen")

    root = Path(data_root)
    hourly = HourlyResearchStore(root)
    daily_store = ResearchArchiveStore(root)
    slots: dict[str, Mapping[str, Any]] = {}
    source_refs: dict[str, Mapping[str, Any]] = {}
    missing: list[str] = []
    invalid: list[str] = []

    for slot in EXPECTED_RESEARCH_SLOTS:
        try:
            payload = hourly.read_exact(archive_date, slot, mode="LIVE")
        except (OSError, ValueError):
            invalid.append(slot)
            continue
        if payload is None:
            missing.append(slot)
            continue
        slots[slot] = payload
        source_refs[slot] = _hourly_source_ref(
            hourly,
            payload,
            archive_date=archive_date,
            slot=slot,
        )

    if missing or invalid:
        reasons = [f"MISSING_SLOT:{slot}" for slot in missing]
        reasons.extend(f"HOURLY_SLOT_INVALID:{slot}" for slot in invalid)
        return {
            "schema_version": "v3_5.research_day_materialize.v1",
            "status": "NOT_MATERIALIZED",
            "archive_date": archive_date,
            "date_mode": "EXACT",
            "expected_slots": list(EXPECTED_RESEARCH_SLOTS),
            # The typed gap contract represents the incomplete day as missing
            # all required inputs; cannot_confirm carries the precise slots.
            "missing_slots": list(EXPECTED_RESEARCH_SLOTS),
            "cannot_confirm": sorted(reasons),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    product = build_research_day_product(
        archive_date,
        slots,
        source_refs=source_refs,
        stock_mentions_registry=stock_mentions_registry,
        transformer_identity_sha256=_transformer_identity_sha256(),
    )
    publication = daily_store.publish_day_product(product)
    return {
        **product,
        **publication,
        "schema_version": product["schema_version"],
        "status": product["status"],
        "archive_date": archive_date,
        "date_mode": "EXACT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize one exact-date V4 research day"
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = materialize_research_day(args.data_root, args.date)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] != "NOT_MATERIALIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
